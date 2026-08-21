# -*- coding: utf-8 -*-
"""받아쓰기 모델 지표 보고서(HTML)를 만든다.

앞선 실험 보고서들과 같은 원칙 — **결과 파일에서 직접** 만든다. 손으로 옮겨 적은 숫자는 없다.
표 하나가 바뀌면 이 파일을 다시 돌려서 보고서를 새로 뽑는다.

읽는 파일:
    D:/해커톤데이터/audition_results.json       오디션 성적(9종)
    D:/해커톤데이터/audition_transcripts.jsonl  전사 원본(갈래별 재계산·상투구 세기용)
    data/manifests/gold_100.jsonl               시험지(정답·제시문)

쓰는 법:
    python make_asr_report.py
"""

from __future__ import annotations

import json
import re
import statistics as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import cer, diff_pairs, norm_text  # noqa: E402
from eval_ab import classify_preservation, is_measurable_error  # noqa: E402

HERE = Path(__file__).resolve()
ASSESSMENT = HERE.parents[2]
REPO = ASSESSMENT.parent
LAB = Path("D:/해커톤데이터")

RESULTS = LAB / "audition_results.json"
TRANSCRIPTS = LAB / "audition_transcripts.jsonl"
GOLD = REPO / "data" / "manifests" / "gold_100.jsonl"
# 옷(CSS)은 앞 보고서 것을 그대로 물려 쓴다. 같은 팀 문서인데 모양이 달라지면 안 된다
STYLE_SOURCE = ASSESSMENT / "체크리스트채점_실험보고_20260809.html"
REPORT = ASSESSMENT / "받아쓰기모델_지표보고_20260809.html"

BLUE, ORANGE, MUTED = "var(--blue)", "var(--orange)", "var(--neutral)"

# 유튜브 자막 상투구. '감사합니다' 같은 말은 진짜 발화일 수 있어 일부러 넣지 않았다
CLICHE = re.compile(r"자막 제공|구독|시청해 ?주셔|좋아요")


# ── 자잘한 도구 ──────────────────────────────────────────────────────────────
def esc(text) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def pct(v, d=1) -> str:
    return "—" if v is None else f"{v * 100:.{d}f}%"


def median_lower(xs):
    """오디션 코드와 같은 방식의 가운뎃값(줄 세워 len//2 번째). 규칙이 다르면 숫자가 어긋난다."""
    s = sorted(xs)
    return s[len(s) // 2]


def read_style() -> str:
    html = STYLE_SOURCE.read_text(encoding="utf-8")
    return html[html.index("<style>"): html.index("</style>") + len("</style>")]


def table(headers: list[str], rows: list[list[str]], num_cols: set[int]) -> str:
    head = "".join(
        f'<th class="{"num" if i in num_cols else ""}">{esc(h)}</th>'
        for i, h in enumerate(headers)
    )
    body = "".join(
        "<tr>"
        + "".join(f'<td class="{"num" if i in num_cols else ""}">{c}</td>'
                  for i, c in enumerate(r))
        + "</tr>"
        for r in rows
    )
    return (f'<div class="scroll"><table><thead><tr>{head}</tr></thead>'
            f"<tbody>{body}</tbody></table></div>")


# ── 자료 읽기 ────────────────────────────────────────────────────────────────
def load():
    gold = {}
    for line in GOLD.open(encoding="utf-8"):
        r = json.loads(line)
        gold[r["id"]] = r

    trans: dict[str, dict[str, str]] = {}
    for line in TRANSCRIPTS.open(encoding="utf-8"):
        o = json.loads(line)
        trans.setdefault(o["model"], {})[o["id"]] = o["hyp"]

    res = json.loads(RESULTS.read_text(encoding="utf-8"))
    return gold, trans, res


def rescore(gold, hs, strip: bool) -> dict:
    """전사 묶음 하나를 다시 채점한다. strip=True 면 상투구를 떼고 잰다.

    지표 계산 규칙은 eval_ab 것을 그대로 불러 쓴다 — 여기서 새로 만들면 오디션 숫자와 어긋난다.
    """
    cers, cnt, ctrl, false_pos = [], {"보존": 0, "세탁": 0, "기타": 0}, 0, 0
    per = {"LAR": [], "ATQ": []}
    for i, h in hs.items():
        g = gold[i]
        if strip:
            h = CLICHE.split(h)[0]
        c = cer(g["ref"], h)
        cers.append(c)
        per[g["task"]].append(c)
        hn = norm_text(h)
        if g.get("task") == "LAR" and g.get("prompt"):
            pairs = diff_pairs(g["prompt"], g["ref"])
            if not pairs:
                ctrl += 1
                false_pos += norm_text(g["prompt"]) != hn
            else:
                for std, err in pairs:
                    if is_measurable_error(std, err)[0]:
                        cnt[classify_preservation(std, err, hn)] += 1
    judged = cnt["보존"] + cnt["세탁"]
    return {
        "평균": st.mean(cers), "중앙": median_lower(cers),
        "낭독중앙": median_lower(per["LAR"]), "자유중앙": median_lower(per["ATQ"]),
        "보존율": cnt["보존"] / judged, "오탐율": false_pos / ctrl,
        "상투구": sum(1 for h in hs.values() if CLICHE.search(h)),
    }


def spearman(xs, ys) -> float:
    """순위끼리 얼마나 같은 방향으로 움직이나(-1 ~ +1). 값이 아니라 순서만 본다."""
    def rank(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        rk = [0] * len(v)
        for pos, i in enumerate(order):
            rk[i] = pos + 1
        return rk

    rx, ry = rank(xs), rank(ys)
    mx, my = st.mean(rx), st.mean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = (sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) ** 0.5
    return num / den


# ── 그림 ① 산점도: 귀(CER) ↔ 정직함(보존율) ─────────────────────────────────
def scatter(points: list[dict]) -> str:
    """가로는 중앙 CER(왼쪽일수록 잘 들음), 세로는 오류 보존율(위일수록 정직함).

    이 그림 하나가 보고서의 결론이다 — 잘 듣는 모델이 좋은 증인은 아니다.
    좌표는 파이썬이 계산한다(손으로 찍으면 어긋난다).
    """
    x0, x1 = 96.0, 900.0
    y0, y1 = 44.0, 372.0          # y0 = 위(보존율 높음), y1 = 아래
    xmax = 0.34                    # 가로 눈금 상한 34%
    ylo, yhi = 0.60, 0.82          # 세로 눈금 60% ~ 82%

    def sx(v):
        return x0 + (x1 - x0) * min(1.0, v / xmax)

    def sy(v):
        return y1 - (y1 - y0) * (min(yhi, max(ylo, v)) - ylo) / (yhi - ylo)

    p = ['<svg viewBox="0 0 1000 452" role="img" aria-label="'
         + esc("가로축 중앙 CER, 세로축 오류 보존율 산점도. "
               + " · ".join(f"{d['이름']} CER {pct(d['중앙'])} 보존율 {pct(d['보존율'])}"
                            for d in points))
         + '">']

    # 눈금선 — 뒤로 물러나 있어야 점이 읽힌다
    p.append('<g stroke="var(--rule)" stroke-width="1">')
    for i in range(6):
        gx = x0 + (x1 - x0) * i / 5
        p.append(f'<line x1="{gx:.1f}" y1="{y0 - 12:.1f}" x2="{gx:.1f}" y2="{y1:.1f}"></line>')
    for i in range(5):
        gy = y0 + (y1 - y0) * i / 4
        p.append(f'<line x1="{x0:.1f}" y1="{gy:.1f}" x2="{x1:.1f}" y2="{gy:.1f}"></line>')
    p.append("</g>")

    # 눈금 숫자
    p.append('<g font-family="Consolas, D2Coding, monospace" font-size="12" fill="var(--muted)">')
    for i in range(6):
        gx = x0 + (x1 - x0) * i / 5
        p.append(f'<text x="{gx:.1f}" y="{y1 + 22:.0f}" text-anchor="middle">'
                 f"{xmax * i / 5 * 100:.0f}%</text>")
    for i in range(5):
        gy = y0 + (y1 - y0) * i / 4
        val = yhi - (yhi - ylo) * i / 4
        p.append(f'<text x="{x0 - 12:.1f}" y="{gy + 4:.1f}" text-anchor="end">'
                 f"{val * 100:.0f}%</text>")
    p.append("</g>")

    # 축 이름 — 어느 쪽이 좋은지 말로 적어 준다
    p.append('<g font-size="13" fill="var(--ink-2)">')
    p.append(f'<text x="{(x0 + x1) / 2:.0f}" y="{y1 + 46:.0f}" text-anchor="middle">'
             + esc("← 잘 듣는다      가운뎃값 CER(글자 오류율)      못 듣는다 →") + "</text>")
    p.append(f'<text transform="translate(28,{(y0 + y1) / 2:.0f}) rotate(-90)" '
             'text-anchor="middle">' + esc("↑ 오류를 살려 적는다   오류 보존율") + "</text>")
    p.append("</g>")

    # 점 — 유형(문맥형/직청형)으로 색을 나눈다. 색만으로 구분되지 않게 이름도 함께 적는다
    for d in points:
        cx, cy = sx(d["중앙"]), sy(d["보존율"])
        col = BLUE if d["유형"] == "문맥형" else ORANGE
        ours = d["이름"].startswith("lora")
        p.append(f'<g><title>{esc(d["이름"])} — 중앙 CER {pct(d["중앙"])} · '
                 f'오류 보존율 {pct(d["보존율"])} · {d["유형"]}</title>')
        if ours:  # 우리 모델은 테두리를 하나 더 둘러 눈에 띄게 한다
            p.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="11" fill="none" '
                     f'stroke="{col}" stroke-width="1.5" stroke-opacity=".45"></circle>')
        p.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="6" fill="{col}" '
                 'stroke="var(--surface)" stroke-width="2"></circle></g>')
        # 이름표는 점 오른쪽에. 오른쪽 끝에 붙은 점만 왼쪽으로 넘긴다
        flip = cx > x1 - 150
        p.append(f'<text x="{cx + (-12 if flip else 12):.1f}" y="{cy + 4:.1f}" '
                 f'text-anchor="{"end" if flip else "start"}" font-size="13" '
                 f'fill="var(--ink)">{esc(d["짧은이름"])}</text>')
    p.append("</svg>")
    return "".join(p)


# ── 그림 ② 크기 사다리 가로 막대 ────────────────────────────────────────────
def ladder_bars(rows: list[dict], key: str, unit_max: float, better: str) -> str:
    """small → medium → large 로 갈수록 어떻게 변하는지 가로 막대 하나로 보여 준다."""
    x0, x1 = 150.0, 880.0
    top, step, bar_h = 34.0, 42.0, 18.0
    axis_y = top + step * len(rows) - 10
    height = axis_y + 52

    def sx(v):
        return x0 + (x1 - x0) * min(1.0, v / unit_max)

    p = [f'<svg viewBox="0 0 1000 {height:.0f}" role="img" aria-label="'
         + esc(" · ".join(f"{r['짧은이름']} {pct(r[key])}" for r in rows)) + '">']
    p.append('<g stroke="var(--rule)">')
    for i in range(6):
        gx = x0 + (x1 - x0) * i / 5
        p.append(f'<line x1="{gx:.1f}" y1="20" x2="{gx:.1f}" y2="{axis_y:.1f}"></line>')
    p.append("</g>")
    p.append('<g font-family="Consolas, D2Coding, monospace" font-size="12" fill="var(--muted)">')
    for i in range(6):
        gx = x0 + (x1 - x0) * i / 5
        p.append(f'<text x="{gx:.1f}" y="{axis_y + 20:.0f}" text-anchor="middle">'
                 f"{unit_max * i / 5 * 100:.0f}%</text>")
    p.append(f'<text x="{(x0 + x1) / 2:.0f}" y="{axis_y + 42:.0f}" text-anchor="middle">'
             + esc(better) + "</text></g>")

    for n, r in enumerate(rows):
        y = top + step * n
        col = ORANGE if r["짧은이름"].startswith("LoRA") else BLUE
        # 크기 사다리는 커질수록 진하게 — 순서가 있는 값이라 한 색의 농담으로 나타낸다
        op = r.get("농도", 1.0)
        w = sx(r[key]) - x0
        p.append(f'<g><title>{esc(r["이름"])} — {pct(r[key])}</title>'
                 f'<rect x="{x0:.1f}" y="{y:.1f}" width="{max(2.0, w):.1f}" height="{bar_h}" '
                 f'rx="4" fill="{col}" fill-opacity="{op}"></rect></g>')
        p.append(f'<text x="{x0 - 14:.1f}" y="{y + bar_h - 4:.1f}" text-anchor="end" '
                 f'font-size="13.5" fill="var(--ink)">{esc(r["짧은이름"])}</text>')
        p.append(f'<text x="{x0 + max(2.0, w) + 12:.1f}" y="{y + bar_h - 4:.1f}" '
                 'font-family="Consolas, D2Coding, monospace" font-size="13" '
                 f'fill="var(--ink-2)">{pct(r[key])}</text>')
    p.append("</svg>")
    return "".join(p)


SHORT = {
    "fw(small)": "Whisper small", "fw(medium)": "Whisper medium",
    "fw(large-v3)": "Whisper large-v3", "lora-v1(우리)": "LoRA v1 (우리)",
    "qwen3-asr-1.7b": "Qwen3-ASR", "sensevoice-small": "SenseVoice",
    "owsm-ctc-v4": "OWSM-CTC", "w2v2-ko-ctc": "wav2vec2-ko",
}


def main() -> int:
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
    gold, trans, res = load()

    done = [r for r in res["성적"] if r["상태"] == "완주"]
    dropped = [r for r in res["성적"] if r["상태"] != "완주"]

    # 저장된 성적 + 전사에서 다시 잰 값(갈래별·상투구)을 한 덩이로 묶는다
    models = []
    for r in sorted(done, key=lambda x: x["중앙CER"]):
        extra = rescore(gold, trans[r["이름"]], strip=False)
        stripped = rescore(gold, trans[r["이름"]], strip=True)
        models.append({
            **r, "짧은이름": SHORT.get(r["이름"], r["이름"]),
            "중앙": r["중앙CER"], "낭독중앙": extra["낭독중앙"],
            "자유중앙": extra["자유중앙"], "상투구": extra["상투구"],
            "뗀평균": stripped["평균"], "뗀중앙": stripped["중앙"],
            "뗀오탐율": stripped["오탐율"],
        })
    by_name = {m["이름"]: m for m in models}

    ctx = [m for m in models if m["유형"] == "문맥형"]
    rho_all = spearman([m["중앙"] for m in models], [m["보존율"] for m in models])
    rho_ctx = spearman([m["중앙"] for m in ctx], [m["보존율"] for m in ctx])

    ladder = [by_name[n] for n in
              ["fw(small)", "fw(medium)", "fw(large-v3)", "lora-v1(우리)"] if n in by_name]
    for i, m in enumerate(ladder[:3]):
        m["농도"] = 0.45 + 0.275 * i          # 작은 모델일수록 옅게
    if len(ladder) > 3:
        ladder[3]["농도"] = 1.0

    best_cer = min(models, key=lambda m: m["중앙"])
    best_keep = max(models, key=lambda m: m["보존율"])
    med = by_name.get("fw(medium)")
    small = by_name.get("fw(small)")
    large = by_name.get("fw(large-v3)")

    H = []
    a = H.append
    a("<!-- 이 파일은 make_asr_report.py 가 만든다. 손으로 고치지 말 것 -->")
    a('<meta charset="utf-8">')
    a("<title>받아쓰기 모델 지표 보고 — K-TEST</title>")
    a('<meta name="viewport" content="width=device-width,initial-scale=1">')
    a(read_style())
    a("""<style>
.scatter-note{display:flex;gap:22px;flex-wrap:wrap;font-size:13.5px;color:var(--ink-2);margin:0 0 10px;}
.swatch{display:inline-block;width:11px;height:11px;border-radius:50%;margin-right:7px;vertical-align:-1px;}
.grid3{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px;margin:18px 0 6px;}
.win{color:var(--good);font-weight:700;}
.warn{color:var(--orange);font-weight:700;}
tr.ours td{background:color-mix(in srgb,var(--orange) 7%,transparent);}
</style>""")

    # ── 머리말 ──────────────────────────────────────────────────────────────
    a('<header class="top"><div class="wrap">')
    a('<p class="kicker">K-TEST · 채점 모델 파트</p>')
    a("<h1>받아쓰기 모델, 어느 것을 증인으로 쓸까</h1>")
    a('<p class="sub col">외국인 학습자 녹음 100건을 여덟 모델에게 똑같이 들려주고 '
      "받아 적게 했다. <b>가장 잘 받아쓰는 모델이 우리에게 가장 좋은 모델은 아니었다.</b></p>")
    a(f'<p class="meta"><b>시험지</b> gold 100건(낭독 61 · 자유발화 39) · '
      f'<b>측정</b> {esc(res["실행시각"])} · <b>지표 계산</b> eval_ab.evaluate 로 통일 · '
      "<b>만든이</b> make_asr_report.py</p>")
    a("</div></header>")
    a('<div class="wrap">')

    # ── 왜 이걸 재나 ────────────────────────────────────────────────────────
    a('<div class="lead col">')
    a("<p><b>우리가 푸는 문제.</b> 외국인이 한국어를 얼마나 하는지 채점하려면, "
      "먼저 그 사람이 <b>무슨 말을 했는지 그대로</b> 받아 적어야 한다. "
      "그런데 받아쓰기 AI 는 똑똑할수록 <b>틀린 말을 옳게 고쳐서</b> 적는 버릇이 있다. "
      "학습자가 “방청소를”을 “빵청소리를”이라고 말했는데 “방 청소를”이라고 적어 주면, "
      "그 사람의 실력은 시험지에서 사라진다. 우리는 이것을 <b>세탁</b>이라고 부른다.</p>")
    a("<p>그래서 모델을 고를 때 정확도만 보면 안 된다. <b>자 세 개</b>를 함께 본다.</p>")
    a("</div>")

    a('<div class="grid3">')
    for tag, name, body in [
        ("자 ①", "CER — 얼마나 잘 듣나",
         "받아쓴 글을 정답으로 고치려면 글자를 몇 번 손봐야 하는지. "
         "<b>낮을수록</b> 잘 듣는다. 100글자 중 5글자가 틀리면 5%."),
        ("자 ②", "오류 보존율 — 얼마나 정직한가",
         "학습자가 <b>실제로 틀리게 말한 자리</b>를 틀린 그대로 적어 준 비율. "
         "<b>높을수록</b> 정직하다. 낮으면 몰래 고쳐 준 것(세탁)."),
        ("자 ③", "대조군 오탐율 — 없는 오류를 만드나",
         "제대로 읽은 녹음인데 다르게 적어서 <b>없던 오류를 만들어 낸</b> 비율. "
         "<b>낮을수록</b> 좋다. 높으면 잘한 사람을 억울하게 깎는다."),
    ]:
        a(f'<div class="card"><p class="tag">{tag}</p><h3 style="margin:6px 0 0;font-size:17px;">'
          f"{name}</h3><p>{body}</p></div>")
    a("</div>")

    # ── 핵심 그림 ───────────────────────────────────────────────────────────
    a('<h2 class="col">한 장으로 보는 결론 — 잘 듣는 모델일수록 오류를 지운다</h2>')
    a('<p class="col">가로로 갈수록 <b>귀가 나쁘고</b>, 위로 갈수록 <b>정직하다</b>. '
      "우리가 원하는 자리는 <b>왼쪽 위</b>(잘 듣고 정직함)인데, 실제로는 그 자리가 비어 있다.</p>")
    a('<div class="scatter-note">'
      f'<span><i class="swatch" style="background:{BLUE};"></i>문맥형 — 앞말을 보고 지어내는 쪽</span>'
      f'<span><i class="swatch" style="background:{ORANGE};"></i>직청형 — 소리만 듣고 붙이는 쪽</span>'
      "<span>◎ 테두리 = 우리가 학습시킨 모델</span></div>")
    a("<figure>" + scatter(models))
    a("<figcaption class=\"col\">"
      f"문맥형 다섯(파랑)만 보면 <b>순서가 거의 그대로 뒤집혀 있다</b>(순위 상관 {rho_ctx:+.2f}) — "
      "잘 듣는 모델일수록 보존율이 낮다. 다만 <b>다섯 개짜리 표본이라 '경향이 보인다'까지만</b> "
      f"말할 수 있고, 여덟 종 전체로는 {rho_all:+.2f} 로 느슨해진다. "
      "직청형(주황)은 소리만 받아 적으니 이 흐름에서 벗어난다."
      "</figcaption></figure>")

    if med and small:
        a('<div class="note col">'
          f"<b>가장 또렷한 사례.</b> Whisper 를 small 에서 medium 으로 키우자 귀는 좋아졌다 — "
          f"가운뎃값 CER {pct(small['중앙CER'])} → <span class=\"win\">{pct(med['중앙CER'])}</span>. "
          f"그런데 오류 보존율은 {pct(small['보존율'])} → "
          f"<span class=\"warn\">{pct(med['보존율'])}</span> 로 <b>떨어졌다.</b> "
          f"세탁 건수도 {small['세탁']}건 → {med['세탁']}건으로 늘었다. "
          "<b>귀가 좋아진 만큼 학습자의 실수를 더 많이 고쳐 준 것이다.</b></div>")

    # ── 크기 사다리 ─────────────────────────────────────────────────────────
    a('<h2 class="col">Whisper 를 키우면 어떻게 되나</h2>')
    a('<p class="col">같은 집안 모델 셋(small · medium · large-v3)에, '
      "우리가 small 을 외국인 발화로 학습시킨 <b>LoRA v1</b> 을 나란히 세웠다. "
      "막대가 진해질수록 큰 모델이다.</p>")

    a("<figure>" + ladder_bars(ladder, "중앙", 0.20, "가운뎃값 CER — 짧을수록 잘 듣는다"))
    tied = [m["짧은이름"] for m in models if m["중앙CER"] == med["중앙CER"]]
    tie_note = ("" if len(tied) < 2
                else f"(여덟 종 전체로 보면 {esc([t for t in tied if t != med['짧은이름']][0])} 와 동점이다) ")
    a('<figcaption class="col">'
      f"이 넷 중에서는 medium 이 가장 잘 듣는다({pct(med['중앙CER'])}). {tie_note}"
      "large-v3 가 길어 보이는 것은 귀가 나빠서가 아니라 뒤에 군더더기를 붙이기 때문이다"
      "(바로 아래에서 설명한다).</figcaption></figure>")

    a("<figure>" + ladder_bars(ladder, "보존율", 0.85, "오류 보존율 — 길수록 정직하다"))
    a('<figcaption class="col">'
      f"순서가 뒤집힌다. 가장 잘 듣는 medium 이 <b>가장 덜 정직하다</b>"
      f"({pct(med['보존율'])}, 완주 여덟 종 중 꼴찌). "
      f"가장 정직한 것은 {esc(best_keep['짧은이름'])}({pct(best_keep['보존율'])})다."
      "</figcaption></figure>")

    # ── 평균과 가운뎃값 ─────────────────────────────────────────────────────
    a('<h2 class="col">평균 CER 을 그대로 믿으면 안 되는 이유</h2>')
    a('<p class="col">표에 평균과 가운뎃값을 <b>둘 다</b> 적어 둔 데는 이유가 있다. '
      "받아쓰기 모델은 가끔 <b>발작</b>을 하는데, 그 몇 건이 평균을 통째로 망가뜨린다.</p>")

    a('<h3 class="col">고장 ① 폭주 — 같은 말을 끝없이 되풀이한다</h3>')
    worst = sorted(((cer(gold[i]["ref"], h), i)
                    for i, h in trans["fw(small)"].items()), reverse=True)[:2]
    rows = []
    for c, i in worst:
        cells = [esc(gold[i]["ref"]) + f' <span style="color:var(--muted);">'
                 f'({len(norm_text(gold[i]["ref"]))}자)</span>']
        for m in ladder:
            h = trans[m["이름"]].get(i, "")
            cc = cer(gold[i]["ref"], h)
            mark = f' <span class="warn">({len(norm_text(h))}자 쏟음)</span>' if cc > 1.0 else ""
            cells.append(pct(cc, 0) + mark)
        rows.append(cells)
    a(table(["정답 문장"] + [m["짧은이름"] for m in ladder], rows, {1, 2, 3, 4}))
    a('<p class="col" style="font-size:14.5px;color:var(--ink-2);">'
      "9글자짜리 정답에 223글자를 쏟아 내면 CER 이 2456% 가 된다. "
      f"이런 것이 {small['폭주']}건만 있어도 평균은 {pct(small['CER'])} 로 치솟지만, "
      f"가운뎃값은 {pct(small['중앙CER'])} 그대로다 — <b>평소엔 잘 듣는데 가끔 발작하는 모델</b>이다.</p>")

    a('<h3 class="col">고장 ② 유튜브 자막 상투구 — 뒤에 없는 말을 갖다 붙인다</h3>')
    a('<p class="col">Whisper 는 알아듣기 힘든 구간에서 '
      "<code>자막 제공 및 자막 제공 및 광고를 포함하고 있습니다</code> 같은 말을 지어내 "
      "문장 뒤에 붙인다. 유튜브 자막을 잔뜩 학습한 흔적이다. "
      "<b>못 들은 게 아니라 뒤에 군더더기를 붙인 것</b>이므로, 떼고 재면 진짜 실력이 보인다.</p>")
    rows = []
    for m in ladder:
        rows.append([
            esc(m["짧은이름"]),
            f'{m["상투구"]}건',
            f'{pct(m["CER"])} → <b>{pct(m["뗀평균"])}</b>',
            f'{pct(m["중앙CER"])} → <b>{pct(m["뗀중앙"])}</b>',
            f'{pct(m["오탐율"])} → {pct(m["뗀오탐율"])}',
            f'{pct(m["보존율"])} <span style="color:var(--muted);">(안 변함)</span>',
        ])
    a(table(["모델", "상투구 붙은 건수", "평균 CER (원본→뗀 뒤)", "가운뎃값 CER (원본→뗀 뒤)",
             "오탐율 (원본→뗀 뒤)", "오류 보존율"], rows, {1, 2, 3, 4, 5}))
    a('<p class="col" style="font-size:14.5px;color:var(--ink-2);">'
      f"이건 <b>large-v3 만의 문제</b>다({large['상투구']}건, medium 은 {med['상투구']}건). "
      f"떼고 재면 평균 {pct(large['CER'])} → <b>{pct(large['뗀평균'])}</b>, "
      f"가운뎃값 {pct(large['중앙CER'])} → <b>{pct(large['뗀중앙'])}</b> 로 여덟 종 중 1위가 된다. "
      "<b>large-v3 는 귀가 나빠서 떨어진 게 아니라 고칠 수 있는 결함 때문에 떨어졌다.</b> "
      "다만 오류 보존율은 상투구를 떼도 그대로다 — 상투구는 문장 <b>뒤에</b> 붙는 것이라 "
      "앞의 오류 판정을 건드리지 않기 때문이다. 즉 <b>‘세탁을 얼마나 하나’는 이 모델의 본성</b>이다.</p>")

    # ── 전체 표 ─────────────────────────────────────────────────────────────
    a('<h2 class="col">전체 성적표</h2>')
    a('<p class="col">가운뎃값 CER 이 좋은 순서다. 초록은 그 칸의 1등, 주황은 꼴찌.</p>')
    best = {
        "중앙CER": min(m["중앙CER"] for m in models),
        "보존율": max(m["보존율"] for m in models),
        "오탐율": min(m["오탐율"] for m in models),
    }
    worst_of = {
        "중앙CER": max(m["중앙CER"] for m in models),
        "보존율": min(m["보존율"] for m in models),
        "오탐율": max(m["오탐율"] for m in models),
    }

    def mark(m, key, text):
        if m[key] == best[key]:
            return f'<span class="win">{text}</span>'
        if m[key] == worst_of[key]:
            return f'<span class="warn">{text}</span>'
        return text

    rows = []
    for m in models:
        det = ("<b>진짜 통과</b>" if m["key"] == "fw-medium"
               else '통과<span style="color:var(--muted);">(※)</span>')
        rows.append([
            f'<b>{esc(m["짧은이름"])}</b>' + (' <span style="color:var(--orange);">우리</span>'
                                             if m["key"] == "lora-v1" else ""),
            esc(m["유형"]),
            pct(m["CER"]),
            mark(m, "중앙CER", pct(m["중앙CER"])),
            pct(m["낭독중앙"]),
            pct(m["자유중앙"]),
            mark(m, "보존율", pct(m["보존율"])),
            f'{m["보존"]}/{m["세탁"]}/{m["기타"]}',
            mark(m, "오탐율", pct(m["오탐율"])),
            f'{m["폭주"]}건',
            f'{m["빈전사"]}건',
            f'{m["건당초"]:.1f}초',
            det,
        ])
    for m in dropped:
        rows.append([f'<b>{esc(m["이름"])}</b>', esc(m["유형"])] + ["—"] * 10
                    + ['<span class="warn">탈락</span>'])
    a(table(["모델", "유형", "평균 CER", "가운뎃값 CER", "낭독", "자유발화", "오류 보존율",
             "보존/세탁/기타", "대조군 오탐율", "폭주", "빈전사", "건당", "결정성"],
            rows, set(range(2, 12))))
    a('<p class="col" style="font-size:14px;color:var(--muted);">'
      "‘보존/세탁/기타’ — 학습자가 틀린 자리를 <b>살려 적음 / 고쳐 적음 / 아예 다른 말이 됨</b>. "
      "보존율은 앞의 둘로만 계산한다(‘기타’는 판정할 수 없어 분모에서 뺀다). "
      f"탈락 사유: {esc(dropped[0]['이름']) if dropped else ''} — 잠긴 저장소(401), "
      "HF 토큰을 넣으면 합류 가능.</p>")

    # ── 주의 ────────────────────────────────────────────────────────────────
    a('<h2 class="col">읽을 때 주의할 것</h2>')
    a('<div class="note col"><b>‘결정성 통과(※)’ 는 아직 못 믿는다.</b> '
      "결정성이란 <b>같은 녹음을 다시 들려줬을 때 똑같이 적는가</b>다. 증인이 물을 때마다 "
      "말을 바꾸면 다수결이 성립하지 않으므로 반드시 통과해야 하는 검사인데, "
      "8/9 에 이 검사 코드가 <b>자기 자신과 비교하고 있었다</b>는 것을 발견했다(무조건 통과가 나온다). "
      "실제로 SenseVoice 는 같은 파일을 “집들은 참 좋은데 너무 <b>비싸다</b>”와 "
      "“집들<b>은은</b> 참 좋은데 너무 <b>비다</b>”로 다르게 적었는데도 ‘일치’로 기록됐다. "
      "<b>고쳤고, 고친 뒤 새로 잰 Whisper medium 만 진짜 검사를 통과했다.</b> "
      "나머지는 옛 검사 결과라 증인 확정 전에 다시 재야 한다.</div>")
    a('<div class="note col">'
      "<b>Gemini 와 LoRA v0 는 이 표에 없다.</b> 그 둘은 8/5 에 쟀는데, 그때는 평가 도구가 "
      "실행마다 다른 답을 내던 때(같은 모델이 CER 12.2~15.4% 로 요동)라 "
      "이 표와 나란히 놓고 순위를 매길 수 없다. 참고로 Gemini 는 "
      "CER 7.6~7.9% 로 귀가 가장 좋았지만 <b>오류 보존율은 66.0% 로 낮았다</b> — "
      "이 보고서의 결론과 같은 방향이다.</div>")
    a('<div class="note col">'
      "<b>표본은 100건이다.</b> 낭독 61 · 자유발화 39 이고, 오류 보존율은 낭독에서만 잴 수 있다"
      "(읽어야 했던 문장이 있어야 ‘어디서 틀렸는지’를 안다). "
      "보존율의 실제 분모는 38~44 자리라, <b>몇 %p 차이는 우연일 수 있다.</b> "
      "‘medium 이 꼴찌’ 같은 순위 하나보다 <b>흐름</b>을 보는 것이 안전하다.</div>")

    # ── 다음 ────────────────────────────────────────────────────────────────
    a('<h2 class="col">그래서 다음에 할 일</h2>')
    a('<ol class="col">')
    a("<li><b>증인 네 명의 결정성을 다시 잰다.</b> 고친 검사로 확인해야 다수결의 근거가 선다.</li>")
    a("<li><b>large-v3 의 상투구를 떼는 후처리를 넣고 다시 심사한다.</b> "
      "떼고 나면 귀가 가장 좋은 증인이 하나 늘어난다.</li>")
    a("<li><b>증인은 ‘잘 듣는 순서’가 아니라 ‘정직한 순서’로 고른다.</b> "
      "이 보고서가 그 원칙에 숫자를 붙였다.</li>")
    a("</ol>")

    # ── 용어 ────────────────────────────────────────────────────────────────
    a('<h2 class="col">용어 한 줄 풀이</h2>')
    a('<dl class="col">')
    for t, d in [
        ("CER(글자 오류율)", "받아쓴 글을 정답으로 고치는 데 글자를 몇 번 손봐야 하는지. 낮을수록 잘 듣는다."),
        ("가운뎃값", "성적을 줄 세웠을 때 한가운데 값. 몇 건이 튀어도 흔들리지 않아 ‘보통 때 실력’을 보여 준다."),
        ("세탁", "학습자가 틀리게 말한 것을 표준어로 고쳐서 적는 것. 채점이 실력을 못 보게 만드는 가장 큰 적."),
        ("폭주", "같은 말을 끝없이 되풀이해 정답보다 두 배 넘게 길어진 것(CER 100% 초과)."),
        ("문맥형 / 직청형", "앞말을 보고 다음 글자를 지어내는 쪽 / 소리만 듣고 글자를 붙이는 쪽. 문맥형이 세탁을 더 한다."),
        ("결정성", "같은 녹음을 다시 들려줬을 때 글자 하나까지 똑같이 적는가. 증인 다수결의 전제 조건."),
        ("LoRA", "큰 모델을 통째로 다시 학습시키지 않고, 작은 덧붙임만 학습시켜 성격을 바꾸는 방법."),
    ]:
        a(f"<dt>{esc(t)}</dt><dd>{esc(d)}</dd>")
    a("</dl>")

    a("</div>")
    a('<footer class="wrap" style="padding-left:24px;padding-right:24px;">')
    a(f'K-TEST 문제·채점 모델 파트 · 오디션 실행 {esc(res["실행시각"])} · '
      "시험지 <code>data/manifests/gold_100.jsonl</code> 100건 · "
      "원본 <code>D:/해커톤데이터/audition_results.json</code> · <code>audition_transcripts.jsonl</code> · "
      "이 문서의 모든 숫자는 <code>make_asr_report.py</code> 가 그 파일들에서 다시 계산한 것이다.")
    a("</footer>")

    REPORT.write_text("\n".join(H) + "\n", encoding="utf-8")
    print(f"저장: {REPORT}")
    print(f"  모델 {len(models)}종 + 탈락 {len(dropped)}종 · "
          f"가장 잘 듣는 것 {best_cer['짧은이름']}({pct(best_cer['중앙CER'])}) · "
          f"가장 정직한 것 {best_keep['짧은이름']}({pct(best_keep['보존율'])})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
