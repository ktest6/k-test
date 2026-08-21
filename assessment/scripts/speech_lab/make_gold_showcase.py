# -*- coding: utf-8 -*-
"""골든셋 교정 사례를 **파형 + 원본 라벨 + 교정 라벨** 한 묶음으로 꺼낸다.

왜 필요한가:
우리 골든셋(gold)은 AI Hub 가 준 사람 전사(원본 라벨)를 팀원이 귀로 다시 듣고
고친 것이다. "고쳤다"는 말만으로는 남이 믿어 주지 않는다. 실제로 들어 보고
어디가 어떻게 달라졌는지 눈으로 봐야 한다. 그래서 세 가지를 한 화면에 붙인다.

    ① 실제 음성 파형 (소리의 생김새 + 그 자리에서 바로 재생)
    ② 원본 라벨      (AI Hub 사람 전사가 적어 놓았던 글)
    ③ 교정 라벨      (우리 팀원이 들리는 그대로 고쳐 적은 글)

읽는 파일 (전부 이미 있는 것, 새로 만들지 않는다):
    data/manifests/gold_team399.jsonl   팀원 4명이 교정한 399건 (원본·교정 둘 다 들어 있음)
    data/manifests/gold399_audio.jsonl  그 399건의 음성 파일 위치·화자 정보
    data/manifests/gold_100.jsonl       재완이 교정한 100건 (ref 가 이미 교정본)
    data/manifests/71479_all.jsonl      그 100건의 **원본** 라벨을 되찾아 올 곳

만드는 것 (data/gold_showcase/ 아래, 저장소에는 올라가지 않음):
    골든셋_교정사례.html   보는 용도. 파형·재생버튼·달라진 곳 색칠까지 들어 있다
    교정라벨.jsonl         기계용. 한 줄에 한 건씩 원본·교정·음성경로
    audio/*.wav            16kHz 단채널로 줄여 복사한 음성 (원본은 96kHz 까지 섞여 있어 무겁다)

쓰는 법:
    python make_gold_showcase.py                  # 팀원 교정 136건 전부
    python make_gold_showcase.py --limit 12       # 발표용으로 앞 12건만
    python make_gold_showcase.py --source all     # 재완 100건까지 합쳐서
    python make_gold_showcase.py --no-audio       # 파형만, 음성 복사는 생략(가벼움)
    # 발표용으로 고른 몇 건만, 유형 설명을 붙여서 (적은 순서 그대로 나온다)
    python make_gold_showcase.py --source all --ids "00432-...=발음 오류 세탁,00565-...=없는 말"

※ 이 음성은 AI Hub 공공데이터다. 팀 밖으로 내보내지 않는다.
"""

from __future__ import annotations

import argparse
import base64
import difflib
import json
import re
import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import DATA_ROOT, enable_utf8_output, norm_text  # noqa: E402

HERE = Path(__file__).resolve()
ASSESSMENT = HERE.parents[2]

MANIFESTS = DATA_ROOT / "manifests"
TEAM = MANIFESTS / "gold_team399.jsonl"
TEAM_AUDIO = MANIFESTS / "gold399_audio.jsonl"
MINE = MANIFESTS / "gold_100.jsonl"
MINE_ORIG = MANIFESTS / "71479_all.jsonl"

OUT_DIR = DATA_ROOT / "gold_showcase"
# 옷(CSS)은 앞 보고서 것을 그대로 물려 쓴다. 같은 팀 문서인데 모양이 달라지면 안 된다
STYLE_SOURCE = ASSESSMENT / "받아쓰기모델_지표보고_20260809.html"

#: 파형을 몇 칸으로 나눠 그릴지. 이보다 잘게 쪼개도 화면에서는 구분이 안 된다
WAVE_BUCKETS = 640
#: 복사본 음성의 표본율. 원본은 16k~96k 가 섞여 있는데 듣는 데는 16k 면 충분하다
TARGET_SR = 16000


# ── 자잘한 도구 ──────────────────────────────────────────────────────────────
def esc(text) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.open(encoding="utf-8") if line.strip()]


def stem(file_name: str) -> str:
    """'0067-...-.wav' → '0067-...' — 파일명과 id 를 맞추는 열쇠."""
    return file_name[:-4] if file_name.lower().endswith(".wav") else file_name


# ── ① 음성 읽기 · 파형 그리기 ────────────────────────────────────────────────
def read_pcm(path: Path):
    """wav 를 읽어 (표본들, 표본율) 로 돌려준다. 여러 채널이면 하나로 합친다.

    soundfile 이 있으면 그걸 쓰고(96kHz·24bit 같은 것도 알아서 읽는다),
    없으면 파이썬에 기본으로 들어 있는 wave 모듈로 16비트 PCM 만 읽는다.
    실험용 도구라 둘 중 되는 쪽을 쓰면 되고, 새 의존성을 강요하지 않는다.
    """
    try:
        import numpy as np
        import soundfile as sf

        data, sr = sf.read(str(path), dtype="float32", always_2d=True)
        return np.mean(data, axis=1), sr
    except ImportError:
        import array

        with wave.open(str(path), "rb") as w:
            if w.getsampwidth() != 2:
                raise RuntimeError(f"16비트 wav 가 아니라 읽지 못했다: {path.name}")
            raw = w.readframes(w.getnframes())
            ch, sr = w.getnchannels(), w.getframerate()
        samples = array.array("h")
        samples.frombytes(raw)
        if ch > 1:  # 채널을 번갈아 담고 있으므로 첫 채널만 뽑는다
            samples = samples[::ch]
        return [s / 32768.0 for s in samples], sr


def envelope(samples, buckets: int = WAVE_BUCKETS) -> list[tuple[float, float]]:
    """표본 수십만 개를 '칸마다 가장 큰 값·가장 작은 값' 쌍으로 줄인다.

    파형 그림은 결국 소리가 큰 곳이 두툼하게 보이면 되는 것이라,
    칸마다 위아래 끝 두 값만 남겨도 눈으로 보는 모양은 똑같다.
    """
    n = len(samples)
    if n == 0:
        return [(0.0, 0.0)] * buckets
    step = max(1, n // buckets)
    out: list[tuple[float, float]] = []
    for i in range(buckets):
        chunk = samples[i * step: (i + 1) * step]
        if len(chunk) == 0:
            out.append((0.0, 0.0))
        else:
            out.append((float(min(chunk)), float(max(chunk))))
    return out


def wave_svg(env: list[tuple[float, float]], width: int = 900, height: int = 96) -> str:
    """봉우리 목록을 SVG 그림 한 조각으로 바꾼다(바깥 라이브러리 없이)."""
    peak = max((max(abs(lo), abs(hi)) for lo, hi in env), default=0.0) or 1.0
    mid = height / 2
    dx = width / len(env)
    # 위쪽 테두리를 왼→오른쪽으로 그리고, 아래쪽 테두리를 오른→왼쪽으로 되돌아오며 닫는다
    top = [f"{i * dx:.2f},{mid - (hi / peak) * mid * 0.94:.2f}" for i, (_, hi) in enumerate(env)]
    bottom = [f"{i * dx:.2f},{mid - (lo / peak) * mid * 0.94:.2f}"
              for i, (lo, _) in reversed(list(enumerate(env)))]
    points = " ".join(top + bottom)
    return (
        f'<svg class="wave" viewBox="0 0 {width} {height}" preserveAspectRatio="none" '
        f'role="img" aria-label="음성 파형">'
        f'<line x1="0" y1="{mid}" x2="{width}" y2="{mid}" class="wave-axis"/>'
        f'<polygon points="{points}"/></svg>'
    )


def save_16k_mono(samples, sr: int, dest: Path) -> None:
    """들어 보기용 복사본을 16kHz 단채널 16비트로 줄여 저장한다.

    원본을 그대로 복사하면 136건에 150MB 다. 말소리를 확인하는 데는
    16kHz 로 충분하고(전화 음질보다 좋다) 용량이 3분의 1로 준다.
    """
    ratio = sr / TARGET_SR
    if ratio > 1:
        # 가장 단순한 방식(일정 간격으로 뽑기). 듣기용이라 이 정도면 된다
        picked = [samples[int(i * ratio)] for i in range(int(len(samples) / ratio))]
    else:
        picked = list(samples)
    pcm = bytearray()
    for v in picked:
        s = int(max(-1.0, min(1.0, float(v))) * 32767)
        pcm += int(s).to_bytes(2, "little", signed=True)
    with wave.open(str(dest), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(TARGET_SR)
        w.writeframes(bytes(pcm))


# ── ② 원본 라벨 ↔ 교정 라벨 대조 ─────────────────────────────────────────────
_WORD = re.compile(r"\S+")


def mark_diff(orig: str, gold: str) -> tuple[str, str]:
    """두 글을 어절 단위로 맞춰 보고, 달라진 어절에 색칠 표시를 붙인다.

    글자 단위로 비교하면 한 글자만 달라도 문장이 온통 알록달록해져서
    무엇이 바뀌었는지 오히려 안 보인다. 사람이 "어디가 달라졌지?" 하고
    볼 때 쓰는 단위는 낱말이므로 어절로 맞춘다.
    """
    a, b = _WORD.findall(orig or ""), _WORD.findall(gold or "")
    # 공백·문장부호만 다른 것은 '같다'로 본다(감사 안내문에서 무시하라고 한 차이)
    sm = difflib.SequenceMatcher(a=[norm_text(w) for w in a], b=[norm_text(w) for w in b])
    left, right = [], []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            left += [esc(w) for w in a[i1:i2]]
            right += [esc(w) for w in b[j1:j2]]
        else:
            left += [f'<mark class="del">{esc(w)}</mark>' for w in a[i1:i2]]
            right += [f'<mark class="ins">{esc(w)}</mark>' for w in b[j1:j2]]
    return " ".join(left), " ".join(right)


# ── ③ 자료 모으기 ────────────────────────────────────────────────────────────
def collect(source: str) -> list[dict]:
    """교정 사례를 한 모양으로 모은다: {파일, 감사자, 원본, 교정, 음성경로, 화자정보}."""
    rows: list[dict] = []

    if source in ("team", "all"):
        audio = {r["id"]: r for r in read_jsonl(TEAM_AUDIO)}
        for r in read_jsonl(TEAM):
            if not r.get("corrected"):
                continue  # 고칠 데가 없던 건은 보여 줄 것이 없다
            meta = audio.get(stem(r["file"]), {})
            rows.append({
                "id": stem(r["file"]),
                "auditor": r.get("auditor", "?"),
                "orig": r["label_orig"],
                "gold": r["gold"],
                "audio": DATA_ROOT / meta.get("audio", ""),
                "meta": meta,
                "batch": "팀원 399건",
            })

    if source in ("mine", "all"):
        # 재완 몫은 gold_100 의 ref 가 이미 교정본이라, 원본은 원래 목록에서 되찾아 온다
        orig_by_id = {r["id"]: r for r in read_jsonl(MINE_ORIG)}
        for r in read_jsonl(MINE):
            src = orig_by_id.get(r["id"])
            if src is None or norm_text(src["ref"]) == norm_text(r["ref"]):
                continue
            rows.append({
                "id": r["id"],
                "auditor": "재완",
                "orig": src["ref"],
                "gold": r["ref"],
                "audio": Path(r["audio"]),
                "meta": r,
                "batch": "재완 100건",
            })

    rows.sort(key=lambda r: (r["auditor"], r["id"]))
    return rows


def pick_ids(rows: list[dict], spec: str) -> list[dict]:
    """손으로 고른 몇 건만, 적은 순서 그대로 남긴다.

    발표에서는 164건을 다 보여 주지 않는다. 유형이 겹치지 않게 몇 건을 고르고
    "이건 무슨 유형이다"라는 한 줄을 붙여야 듣는 사람이 따라온다.
    그래서 'id=설명' 으로 설명까지 같이 받는다.
    """
    by_id = {r["id"]: r for r in rows}
    picked: list[dict] = []
    for token in spec.split(","):
        token = token.strip()
        if not token:
            continue
        key, _, note = token.partition("=")
        # 파일명 전체를 다 적기 번거로우니 앞부분만 적어도 찾아 준다
        matches = [i for i in by_id if i == key.strip() or i.startswith(key.strip())]
        if len(matches) != 1:
            print(f"  [건너뜀] '{key.strip()}' 에 맞는 건이 {len(matches)}개다")
            continue
        row = dict(by_id[matches[0]])
        row["note"] = note.strip()
        picked.append(row)
    return picked


# ── ④ 보고서 만들기 ──────────────────────────────────────────────────────────
def read_style() -> str:
    try:
        html = STYLE_SOURCE.read_text(encoding="utf-8")
        return html[html.index("<style>"): html.index("</style>") + len("</style>")]
    except (OSError, ValueError):
        return ""  # 앞 보고서가 없어도 내용은 나오게 한다


EXTRA_CSS = """
<style>
.case{border:1px solid var(--rule,#e3e3e3);border-radius:12px;padding:1rem 1.1rem;margin:1.1rem 0;
      background:var(--surface,transparent)}
.case h3{margin:0 0 .2rem;font-size:1rem}
.case .who{font-size:.85rem;color:var(--muted,#777);margin:0 0 .7rem}
.wave{width:100%;height:96px;display:block}
.wave polygon{fill:var(--blue,#2f6fdb);opacity:.75}
.wave-axis{stroke:var(--neutral,#999);stroke-width:1;opacity:.35}
.case audio{width:100%;margin:.45rem 0 .8rem}
.lab{display:grid;grid-template-columns:5.6rem 1fr;gap:.5rem .8rem;align-items:baseline}
.lab dt{font-size:.82rem;color:var(--muted,#777);white-space:nowrap}
.lab dd{margin:0;line-height:1.7;word-break:keep-all}
mark.del{background:rgba(220,80,80,.18);color:inherit;text-decoration:line-through;
         text-decoration-color:rgba(220,80,80,.7);border-radius:3px;padding:0 .12em}
mark.ins{background:rgba(60,150,90,.2);color:inherit;border-radius:3px;padding:0 .12em}
.tags{font-size:.8rem;color:var(--muted,#777);margin-top:.6rem}
.note{display:inline-block;margin-left:.5rem;padding:.1rem .5rem;border-radius:999px;
      font-size:.78rem;font-weight:600;background:rgba(220,120,40,.16);color:var(--orange,#c26a12)}
.scroll{overflow-x:auto}
</style>
"""


def build_html(cases: list[dict], with_audio: bool, title: str = "골든셋 교정 사례") -> str:
    by_auditor: dict[str, int] = {}
    for c in cases:
        by_auditor[c["auditor"]] = by_auditor.get(c["auditor"], 0) + 1
    tally = " · ".join(f"{k} {v}건" for k, v in sorted(by_auditor.items()))

    blocks = []
    for n, c in enumerate(cases, 1):
        left, right = mark_diff(c["orig"], c["gold"])
        m = c["meta"]
        tags = " · ".join(str(x) for x in [
            m.get("task", ""), m.get("nationality", ""),
            f"TOPIK {m.get('topik_level')}" if m.get("topik_level") else "",
            f"{m.get('duration_sec', 0):.1f}초" if m.get("duration_sec") else "",
        ] if x)
        # embed 면 소리를 HTML 안에 넣는다(파일 하나만 보내면 되게), 아니면 옆 폴더를 가리킨다
        src = c.get("data_uri") or f'audio/{esc(c["id"])}.wav'
        player = f'<audio controls preload="none" src="{src}"></audio>' if with_audio else ""
        note = f'<span class="note">{esc(c["note"])}</span>' if c.get("note") else ""
        blocks.append(f"""
<div class="case">
  <h3>{n}. {esc(c["id"])} {note}</h3>
  <p class="who">감사자 {esc(c["auditor"])} · {esc(c["batch"])}</p>
  {c["svg"]}
  {player}
  <dl class="lab">
    <dt>원본 라벨</dt><dd>{left}</dd>
    <dt>교정 라벨</dt><dd>{right}</dd>
  </dl>
  <p class="tags">{esc(tags)}</p>
</div>""")

    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)} — 파형·원본 라벨·교정 라벨</title>
{read_style()}{EXTRA_CSS}
</head><body>
<h1>{esc(title)}</h1>
<p>AI Hub 가 준 <b>원본 라벨</b>을 우리 팀원이 녹음을 직접 듣고 고친 <b>교정 라벨</b>과
나란히 놓은 것이다. 색칠한 곳이 달라진 어절이고
(<mark class="del">지운 말</mark> / <mark class="ins">고친 말</mark>),
파형 아래 재생 단추로 실제 소리를 그 자리에서 확인할 수 있다.</p>
<p><b>{len(cases)}건</b> — {esc(tally)}</p>
<p class="tags">※ AI Hub 공공데이터. 팀 밖 공유 금지.</p>
{''.join(blocks)}
</body></html>
"""


# ── 실행 ─────────────────────────────────────────────────────────────────────
def main() -> int:
    enable_utf8_output()
    ap = argparse.ArgumentParser(description="골든셋 교정 사례를 파형·라벨과 함께 꺼낸다")
    ap.add_argument("--source", choices=["team", "mine", "all"], default="team",
                    help="team=팀원 교정본(기본) · mine=재완 교정본 · all=둘 다")
    ap.add_argument("--limit", type=int, default=0, help="앞에서 N건만 (0=전부)")
    ap.add_argument("--auditor", default="", help="감사자 이름으로 걸러 내기")
    ap.add_argument("--ids", default="",
                    help="고른 건만 (쉼표로 나열, 적은 순서대로). 'id=유형설명' 으로 설명도 붙는다")
    ap.add_argument("--title", default="골든셋 교정 사례", help="보고서 제목")
    ap.add_argument("--no-audio", action="store_true", help="음성 복사 생략(파형만)")
    ap.add_argument("--embed", action="store_true",
                    help="음성을 HTML 안에 넣어 파일 하나로 만든다(몇 건만 고를 때 쓴다)")
    ap.add_argument("--out", default=str(OUT_DIR), help="결과를 둘 폴더")
    args = ap.parse_args()

    cases = collect(args.source)
    if args.auditor:
        cases = [c for c in cases if c["auditor"] == args.auditor]
    if args.ids:
        cases = pick_ids(cases, args.ids)
    if args.limit:
        cases = cases[:args.limit]
    if not cases:
        print("교정 사례를 하나도 찾지 못했다. --source / --auditor 를 확인하라.")
        return 1

    out = Path(args.out)
    (out / "audio").mkdir(parents=True, exist_ok=True)

    kept: list[dict] = []
    for i, c in enumerate(cases, 1):
        path = c["audio"]
        if not path.exists():
            print(f"  [건너뜀] 음성 없음: {path}")
            continue
        samples, sr = read_pcm(path)
        c["svg"] = wave_svg(envelope(samples))
        if not args.no_audio:
            copy = out / "audio" / f"{c['id']}.wav"
            save_16k_mono(samples, sr, copy)
            if args.embed:
                raw = base64.b64encode(copy.read_bytes()).decode("ascii")
                c["data_uri"] = f"data:audio/wav;base64,{raw}"
        kept.append(c)
        if i % 20 == 0:
            print(f"  {i}/{len(cases)} 처리")

    report = out / "골든셋_교정사례.html"
    report.write_text(build_html(kept, with_audio=not args.no_audio, title=args.title),
                      encoding="utf-8")

    # 기계용 한 줄짜리 라벨 파일 — 다른 스크립트가 바로 읽어 쓸 수 있게 남긴다
    labels = out / "교정라벨.jsonl"
    with labels.open("w", encoding="utf-8") as f:
        for c in kept:
            m = c["meta"]
            f.write(json.dumps({
                "id": c["id"],
                "auditor": c["auditor"],
                "batch": c["batch"],
                "note": c.get("note") or None,
                "label_orig": c["orig"],
                "gold": c["gold"],
                "audio_src": str(c["audio"]),
                "audio_copy": f"audio/{c['id']}.wav" if not args.no_audio else None,
                "task": m.get("task"),
                "prompt": m.get("prompt"),
                "nationality": m.get("nationality"),
                "topik_level": m.get("topik_level"),
                "duration_sec": m.get("duration_sec"),
            }, ensure_ascii=False) + "\n")

    print(f"\n교정 사례 {len(kept)}건을 꺼냈다.")
    print(f"  보고서 : {report}")
    print(f"  라벨   : {labels}")
    if not args.no_audio:
        print(f"  음성   : {out / 'audio'} (16kHz 단채널 복사본)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
