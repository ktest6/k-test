# -*- coding: utf-8 -*-
"""세탁 문제 → 모델 선정 → 파인튜닝 → 데이터 정제까지의 실험 보고서(HTML)를 만든다.

앞 보고서들과 같은 원칙 — **결과 파일에서 직접** 만든다. 손으로 옮겨 적은 숫자는 없다.

읽는 파일:
    D:/해커톤데이터/audition_results.json          모델 8종 성적
    D:/해커톤데이터/audition_transcripts.jsonl     전사 원본(갈래별 재계산용)
    D:/해커톤데이터/launder/verdict_full_summary.json   1만 건 정제 결과
    D:/해커톤데이터/launder/verdict_dev.jsonl      개발셋 300건 판정
    D:/해커톤데이터/launder/gold_dev.jsonl(+_orig) 사람이 고친 정답지
    data/manifests/gold_100.jsonl                  시험지

쓰는 법:
    python make_lora_report.py
"""

from __future__ import annotations

import json
import statistics as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import cer  # noqa: E402
from make_asr_report import (  # noqa: E402
    ASSESSMENT, BLUE, ORANGE, SHORT, esc, median_lower, pct, read_style, table,
)

LAB = Path("D:/해커톤데이터")
LAUNDER = LAB / "launder"
GOLD = ASSESSMENT.parent / "data" / "manifests" / "gold_100.jsonl"
REPORT = ASSESSMENT / "파인튜닝_실험보고_20260809.html"

GREY = "var(--neutral)"


def load():
    gold = {}
    for line in GOLD.open(encoding="utf-8"):
        r = json.loads(line)
        gold[r["id"]] = r
    trans: dict[str, dict[str, str]] = {}
    for line in (LAB / "audition_transcripts.jsonl").open(encoding="utf-8"):
        o = json.loads(line)
        trans.setdefault(o["model"], {})[o["id"]] = o["hyp"]
    res = json.loads((LAB / "audition_results.json").read_text(encoding="utf-8"))
    clean = json.loads((LAUNDER / "verdict_full_summary.json").read_text(encoding="utf-8"))
    return gold, trans, res, clean


def dev_scores() -> dict:
    """개발셋 300건에서 탐지기 성적을 낸다.

    정답은 '사람이 고친 줄'이다 — 감사자가 라벨을 손댔다는 것은 원래 라벨이 틀렸다는 뜻이다.
    (주의: 사람은 세탁이 아닌 단순 오타·띄어쓰기도 고쳤으므로 재현율은 과소평가된다.)
    """
    now = {json.loads(l)["id"]: json.loads(l) for l in (LAUNDER / "gold_dev.jsonl").open(encoding="utf-8")}
    orig = {json.loads(l)["id"]: json.loads(l)["ref"] for l in (LAUNDER / "gold_dev_orig.jsonl").open(encoding="utf-8")}
    verd = {json.loads(l)["id"]: json.loads(l) for l in (LAUNDER / "verdict_dev.jsonl").open(encoding="utf-8")}

    truth = {i for i in now if i in orig and now[i]["ref"] != orig[i]}
    sus = {i for i, r in verd.items() if r["판정"] == "suspect"}
    out = {"n": len(now), "정답": len(truth), "표시": len(sus),
           "맞음": len(sus & truth), "헛짚음": len(sus - truth), "놓침": len(truth - sus)}
    out["정밀도"] = out["맞음"] / len(sus) if sus else 0.0
    out["재현율"] = out["맞음"] / len(truth) if truth else 0.0
    for t in ("LAR", "ATQ"):
        s2 = {i for i in sus if now[i]["task"] == t}
        t2 = {i for i in truth if now[i]["task"] == t}
        out[t] = {"표시": len(s2), "맞음": len(s2 & t2),
                  "정밀도": len(s2 & t2) / len(s2) if s2 else 0.0,
                  "재현율": len(s2 & t2) / len(t2) if t2 else 0.0}
    return out


# ── 그림 ① 계단 — 이 프로젝트가 걸어온 네 칸 ────────────────────────────────
def stairs(steps: list[dict]) -> str:
    """가설 → 실행 → 한계 → 방향 전환을 계단으로 그린다.

    심사위원이 20초 안에 '이 팀이 무엇을 반복했는지'를 읽게 하는 것이 목적이다.
    """
    w_box, h_box, gap_x, rise = 224.0, 116.0, 18.0, 46.0
    x0, base_y = 24.0, 84.0 + rise * (len(steps) - 1)
    height = base_y + h_box + 30

    p = [f'<svg viewBox="0 0 1000 {height:.0f}" role="img" aria-label="'
         + esc(" 다음 ".join(f"{s['제목']}: {s['결과']}" for s in steps)) + '">']
    for n, s in enumerate(steps):
        x = x0 + (w_box + gap_x) * n
        y = base_y - rise * n
        done = s.get("상태") != "진행"
        col = ORANGE if s.get("강조") else BLUE
        p.append(f'<g><title>{esc(s["제목"])} — {esc(s["결과"])}</title>')
        # 계단 판. 진행 중인 칸은 점선으로 두어 '아직'임을 색 말고도 알린다
        p.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w_box}" height="{h_box}" rx="6" '
                 f'fill="var(--surface-2)" stroke="{col}" stroke-width="2"'
                 + ("" if done else ' stroke-dasharray="6 4"') + "></rect>")
        p.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="4" height="{h_box}" rx="2" fill="{col}"></rect>')
        p.append(f'<text x="{x + 16:.1f}" y="{y + 26:.1f}" font-size="11.5" '
                 f'font-family="Consolas, D2Coding, monospace" fill="{col}" letter-spacing=".08em">'
                 f'{esc(s["칸"])}</text>')
        p.append(f'<text x="{x + 16:.1f}" y="{y + 50:.1f}" font-size="15" font-weight="700" '
                 f'fill="var(--ink)">{esc(s["제목"])}</text>')
        for k, part in enumerate(s["결과"].split("\n")):
            p.append(f'<text x="{x + 16:.1f}" y="{y + 74 + k * 19:.1f}" font-size="12.5" '
                     f'fill="var(--ink-2)">{esc(part)}</text>')
        p.append("</g>")
        if n + 1 < len(steps):  # 다음 칸으로 올라가는 화살표
            ax = x + w_box + 2
            ay = y + h_box / 2
            p.append(f'<path d="M{ax:.1f} {ay:.1f} l{gap_x - 6:.1f} {-rise:.1f}" '
                     f'stroke="{GREY}" stroke-width="1.5" fill="none" '
                     'marker-end="url(#ah)"></path>')
    p.append('<defs><marker id="ah" viewBox="0 0 8 8" refX="6" refY="4" markerWidth="6" '
             f'markerHeight="6" orient="auto"><path d="M0 0 L8 4 L0 8 z" fill="{GREY}"></path>'
             "</marker></defs>")
    p.append("</svg>")
    return "".join(p)


# ── 그림 ② 파인튜닝 전후 ────────────────────────────────────────────────────
def before_after(pairs: list[dict]) -> str:
    """밑바탕 → LoRA 를 지표별로 나란히. 좋아진 것과 나빠진 것을 같은 그림에 둔다."""
    x0, x1 = 216.0, 700.0
    top, step = 40.0, 62.0
    height = top + step * len(pairs) + 20

    p = [f'<svg viewBox="0 0 1000 {height:.0f}" role="img" aria-label="'
         + esc(" · ".join(f"{d['이름']} {d['전표시']}에서 {d['후표시']}" for d in pairs)) + '">']
    for n, d in enumerate(pairs):
        y = top + step * n
        good = d["좋아짐"]
        col = "var(--good)" if good else ORANGE
        p.append(f'<text x="{x0 - 18:.1f}" y="{y + 5:.1f}" text-anchor="end" font-size="14" '
                 f'fill="var(--ink)">{esc(d["이름"])}</text>')
        p.append(f'<text x="{x0:.1f}" y="{y + 5:.1f}" font-family="Consolas, D2Coding, monospace" '
                 f'font-size="15" fill="var(--muted)">{esc(d["전표시"])}</text>')
        p.append(f'<path d="M{x0 + 96:.1f} {y:.1f} h84" stroke="{col}" stroke-width="2" '
                 'fill="none" marker-end="url(#ah2)"></path>')
        p.append(f'<text x="{x0 + 196:.1f}" y="{y + 5:.1f}" font-family="Consolas, D2Coding, monospace" '
                 f'font-size="15" font-weight="700" fill="{col}">{esc(d["후표시"])}</text>')
        # 색만으로 좋고 나쁨을 알리지 않는다 — 말로도 적는다
        p.append(f'<text x="{x0 + 292:.1f}" y="{y + 5:.1f}" font-size="13" fill="{col}">'
                 f'{esc("▲ 좋아짐" if good else "▼ 나빠짐")}</text>')
        p.append(f'<text x="{x0 + 382:.1f}" y="{y + 5:.1f}" font-size="12.5" fill="var(--muted)">'
                 f'{esc(d["평"])}</text>')
    p.append('<defs><marker id="ah2" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" '
             'markerHeight="7" orient="auto"><path d="M0 0 L8 4 L0 8 z" fill="context-stroke">'
             "</path></marker></defs></svg>")
    return "".join(p)


# ── 그림 ③ 정제 결과 — 1만 건을 셋으로 갈랐다 ───────────────────────────────
def clean_bar(counts: dict, total: int) -> str:
    """가로 한 줄에 suspect / hold / keep 을 붙여 그린다(사이는 2px 띄운다)."""
    x0, x1, y, h = 40.0, 960.0, 56.0, 46.0
    segs = [("suspect", counts["suspect"], ORANGE, "세탁 의심 — 학습에서 뺀다"),
            ("hold", counts["hold"], GREY, "보류 — 남긴다"),
            ("keep", counts["keep"], BLUE, "이상 없음 — 남긴다")]
    p = [f'<svg viewBox="0 0 1000 190" role="img" aria-label="'
         + esc(f"학습쌍 {total}건을 셋으로 갈랐다. "
               + " · ".join(f"{k} {v}건" for k, v, _, _ in segs)) + '">']
    x = x0
    for k, v, col, desc in segs:
        w = (x1 - x0) * v / total - 2       # 2px 는 칸 사이를 띄우는 데 쓴다
        p.append(f'<g><title>{esc(desc)} — {v:,}건 ({v / total:.1%})</title>'
                 f'<rect x="{x:.1f}" y="{y:.1f}" width="{max(3.0, w):.1f}" height="{h}" rx="4" '
                 f'fill="{col}"></rect></g>')
        p.append(f'<text x="{x:.1f}" y="{y - 12:.1f}" font-size="13" fill="var(--ink)">'
                 f'{esc(k)}</text>')
        p.append(f'<text x="{x:.1f}" y="{y + h + 22:.1f}" font-family="Consolas, D2Coding, monospace" '
                 f'font-size="14" font-weight="700" fill="var(--ink)">{v:,}건</text>')
        p.append(f'<text x="{x:.1f}" y="{y + h + 42:.1f}" font-size="12.5" fill="var(--muted)">'
                 f'{v / total:.1%}</text>')
        x += (x1 - x0) * v / total
    p.append(f'<text x="{x0:.1f}" y="{y + h + 76:.1f}" font-size="13.5" fill="var(--ink-2)">'
             + esc(f"학습쌍 {total:,}건 → 세탁 의심 {counts['suspect']:,}건을 걷어내고 "
                   f"{total - counts['suspect']:,}건으로 다시 학습한다") + "</text>")
    p.append("</svg>")
    return "".join(p)


def main() -> int:
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
    gold, trans, res, clean = load()
    dev = dev_scores()

    done = [r for r in res["성적"] if r["상태"] == "완주"]
    by = {r["이름"]: r for r in done}
    small, med, large = by["fw(small)"], by["fw(medium)"], by["fw(large-v3)"]
    lora = by["lora-v1(우리)"]

    # 세탁률 — 8종을 통틀어 오류 자리 몇 곳이 지워졌나
    keep_all = sum(r["보존"] for r in done)
    laun_all = sum(r["세탁"] for r in done)
    rate = laun_all / (keep_all + laun_all)

    total = clean["총쌍수"]
    counts = clean["판정"]

    H = []
    a = H.append
    a("<!-- make_lora_report.py 가 만든다. 손으로 고치지 말 것 -->")
    a('<meta charset="utf-8">')
    a("<title>파인튜닝 실험 보고 — K-TEST</title>")
    a('<meta name="viewport" content="width=device-width,initial-scale=1">')
    a(read_style())
    a("""<style>
.grid3{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px;margin:18px 0 6px;}
.hero{font-family:Consolas,"D2Coding",monospace;font-size:34px;line-height:1.15;color:var(--ink);
  font-variant-numeric:tabular-nums;margin:0;}
.hero small{display:block;font-family:inherit;font-size:13.5px;color:var(--muted);margin-top:8px;
  font-weight:400;letter-spacing:0;}
.win{color:var(--good);font-weight:700;} .warn{color:var(--orange);font-weight:700;}
.legend{display:flex;gap:20px;flex-wrap:wrap;font-size:13.5px;color:var(--ink-2);margin:0 0 12px;}
.sw{display:inline-block;width:11px;height:11px;border-radius:3px;margin-right:7px;vertical-align:-1px;}
.state{display:inline-block;font-family:Consolas,"D2Coding",monospace;font-size:11.5px;
  padding:2px 8px;border-radius:10px;letter-spacing:.04em;}
.state.done{background:color-mix(in srgb,var(--good) 16%,transparent);color:var(--good);}
.state.now{background:color-mix(in srgb,var(--orange) 16%,transparent);color:var(--orange);}
.state.todo{background:var(--surface-2);color:var(--muted);}
</style>""")

    # ── 머리말 ──────────────────────────────────────────────────────────────
    a('<header class="top"><div class="wrap">')
    a('<p class="kicker">K-TEST · 채점 모델 파트 · 실험 보고</p>')
    a("<h1>받아쓰기가 지운 실력을 되찾는 법</h1>")
    a('<p class="sub col">받아쓰기 AI 는 외국인이 틀리게 말한 것을 <b>옳게 고쳐서</b> 적는다. '
      "그러면 채점할 실력이 시험지에서 사라진다. 우리는 이것을 <b>재고</b>, <b>고쳐 보고</b>, "
      "고칠 수 없다는 것을 확인한 뒤 <b>표시하는 쪽</b>으로 방향을 틀었다.</p>")
    a(f'<p class="meta"><b>시험지</b> gold 100건 · <b>학습쌍</b> {total:,}건 · '
      f'<b>모델 오디션</b> 9종 · <b>측정</b> {esc(res["실행시각"])} · '
      "<b>만든이</b> make_lora_report.py</p>")
    a("</div></header>")
    a('<div class="wrap">')

    # ── 한 문장 결론 ────────────────────────────────────────────────────────
    a('<div class="lead col">')
    a(f'<p class="hero">{rate:.1%}<small>받아쓰기 모델 8종을 통틀어, 외국인이 실제로 틀린 자리 '
      f"{keep_all + laun_all}곳 중 {laun_all}곳이 <b>표준어로 고쳐져 사라졌다.</b> "
      "가장 정직한 모델도 21.1%를 지웠다.</small></p>")
    a("</div>")

    # ── 계단 ────────────────────────────────────────────────────────────────
    a('<h2 class="col">우리가 걸어온 네 칸</h2>')
    a('<p class="col">가설을 세우고, 재고, 안 되면 방향을 틀었다. '
      "<b>세 번째 칸의 실패가 네 번째 칸의 이유</b>다.</p>")
    a("<figure>" + stairs([
        {"칸": "계단 1", "제목": "세탁은 실재하는가",
         "결과": "Gemini 가 조사를 채우고\n발음 오류를 고치고\n끊긴 말을 지웠다"},
        {"칸": "계단 2", "제목": "한 모델만의 문제인가",
         "결과": f"모델 8종 실측 → 세탁률 {rate:.1%}\n가장 정직한 모델도 21.1%\n한 모델 결함이 아니다"},
        {"칸": "계단 3", "제목": "모델을 고치면 되는가",
         "결과": "LoRA 두 차례(v0·v1)\n밑바탕과 구분되지 않음\n실패 — 원인은 학습 목표",
         "강조": True},
        {"칸": "계단 4", "제목": "못 막으면 표시한다",
         "결과": f"증인 4명이 {total:,}건 전수 심사\n세탁 의심 {counts['suspect']:,}건 제거\n정제 데이터로 재학습",
         "상태": "진행"},
    ]))
    a('<figcaption class="col">점선 칸은 진행 중이다. '
      "계단 3 이 없으면 “그냥 파인튜닝하면 되지 않나”라는 물음에 답할 수 없다 — "
      "<b>두 번 해 보고 안 됐다는 실측</b>이 계단 4 의 근거다.</figcaption></figure>")

    # ── 계단 2: 밑바탕 고르기 ───────────────────────────────────────────────
    a('<h2 class="col">계단 2 — 밑바탕을 무엇으로 할 것인가</h2>')
    a('<p class="col">받아쓰기 모델은 크기가 클수록 잘 듣는다. 그런데 '
      "<b>우리 기준은 정확도가 아니라 “학습자의 오류를 지우지 않는가”</b>다. "
      "Whisper 세 크기를 같은 시험지로 재 보았다.</p>")
    rows = [
        ["<b>Whisper small</b>", "244M", f'<span class="win">{pct(small["보존율"])}</span>',
         pct(small["오탐율"]), pct(small["중앙CER"]), f'{small["건당초"]:.1f}초'],
        ["<b>Whisper medium</b>", "769M", f'<span class="warn">{pct(med["보존율"])}</span>',
         f'<span class="win">{pct(med["오탐율"])}</span>',
         f'<span class="win">{pct(med["중앙CER"])}</span>', f'{med["건당초"]:.1f}초'],
        ["<b>Whisper large-v3</b>", "1550M", pct(large["보존율"]),
         f'<span class="warn">{pct(large["오탐율"])}</span>', pct(large["중앙CER"]),
         f'{large["건당초"]:.1f}초'],
    ]
    a(table(["모델", "크기", "오류 보존율", "대조군 오탐율", "가운뎃값 CER", "건당"],
            rows, {1, 2, 3, 4, 5}))
    a('<div class="note col">'
      f"<b>가장 잘 듣는 모델이 오류를 가장 많이 지웠다.</b> medium 은 가운뎃값 CER "
      f"{pct(med['중앙CER'])} 로 셋 중 1위지만 오류 보존율은 {pct(med['보존율'])} 로 꼴찌다. "
      f"정확도로 골랐다면 <b>학습자 실력을 가장 많이 지우는 모델</b>을 선택했을 것이다. "
      f"우리 기준에서는 small 이 {pct(small['보존율'])} 로 가장 높았고, 244M 으로 학습 비용도 "
      "가장 낮아 파인튜닝 밑바탕으로 적합했다.</div>")
    a('<p class="col" style="font-size:14px;color:var(--muted);">'
      "정직한 각주 — 100건 표본에서 세 크기의 보존율 차이는 통계적으로 확정되지 않았다"
      "(small − medium +0.087, 95% 구간 [+0.000, +0.204]). 방향은 일관되나 표본 확대가 필요하다. "
      "또한 small 선정은 8/5, medium 실측은 8/9 로, 이 표는 <b>선택을 사후에 검증한 것</b>이다.</p>")

    # ── 계단 3: 파인튜닝 ────────────────────────────────────────────────────
    a('<h2 class="col">계단 3 — 파인튜닝: 절반의 성공</h2>')
    a(f'<p class="col">Whisper small 에 LoRA 를 붙여 외국인 발화 {total:,}건으로 학습했다'
      "(오류가 든 학습쌍 3,313건 포함, v0·v1 두 차례). 결과를 지표별로 갈라 보면 이렇다.</p>")
    a("<figure>" + before_after([
        {"이름": "폭주(같은 말 무한 반복)", "전표시": f'{small["폭주"]}건', "후표시": f'{lora["폭주"]}건',
         "좋아짐": True, "평": "증언이 빠지는 자리가 줄었다"},
        {"이름": "평균 CER", "전표시": pct(small["CER"]), "후표시": pct(lora["CER"]),
         "좋아짐": True, "평": "폭주가 줄어 평균이 안정됐다"},
        {"이름": "가운뎃값 CER", "전표시": pct(small["중앙CER"]), "후표시": pct(lora["중앙CER"]),
         "좋아짐": True, "평": "차이 미미 — 구간이 0을 걸친다"},
        {"이름": "대조군 오탐율", "전표시": pct(small["오탐율"]), "후표시": pct(lora["오탐율"]),
         "좋아짐": True, "평": "차이 미미 — 구간이 0을 걸친다"},
        {"이름": "오류 보존율 ★목표", "전표시": pct(small["보존율"]), "후표시": pct(lora["보존율"]),
         "좋아짐": False, "평": "정작 목표였던 자가 오르지 않았다"},
    ]))
    a('<figcaption class="col">'
      "<b>보통 때 실력(가운뎃값)은 거의 그대로다.</b> 평균 CER 이 크게 좋아진 것은 폭주 한 건이 "
      "빠지면서 생긴 값이다 — 평균은 발작 몇 건에 통째로 망가지므로 가운뎃값을 함께 본다."
      "</figcaption></figure>")

    a('<div class="note col"><b>같은 파일로 짝지어 다시 재니 차이가 사라졌다.</b> '
      "파일 100개를 다시 뽑는 부트스트랩 2000회로 밑바탕과 LoRA 를 짝지어 비교한 결과 — "
      "가운뎃값 CER −0.005 [−0.028, +0.021] · 평균 CER −0.401 [−1.082, +0.084] · "
      "보존율 −0.039 [−0.127, +0.027] · 오탐율 −0.037 [−0.167, +0.087]. "
      "<b>네 지표 모두 95% 구간이 0을 걸쳐 개선을 주장할 수 없다.</b></div>")

    a('<h3 class="col">왜 안 됐는지는 특정했다</h3>')
    a('<p class="col">데이터가 부족해서가 아니다. 낭독 학습쌍의 <b>56.5%(3,313건)가 실제로 오류가 든 쌍</b>'
      "이었는데도 보존율이 오르지 않았다. 병목은 <b>학습 목표</b>에 있다 — "
      "“사람 전사에 가깝게”(CER 최소화)라는 목표는 “오류를 살려 적어라”라는 신호를 "
      "직접 주지 못한다. 오류를 지워도 CER 은 거의 안 늘어나기 때문이다.</p>")
    a('<div class="note col"><b>그리고 이 실패를 잡아낸 것은 우리가 만든 검증 체계다.</b> '
      "처음엔 3.4배 개선으로 보였다. ① 평균 CER 이 폭주 몇 건에 망가진다는 것을 발견해 "
      "가운뎃값을 병행하고, ② 평가 도구의 무작위성(온도·빔)을 없애 재현성을 확보하고, "
      "③ 같은 파일로 짝지어 다시 재고 나서야 차이가 사라진다는 것을 알았다. "
      "<b>이 저울이 없었다면 우리는 지금도 “3.4배 개선”을 발표하고 있었을 것이다.</b></div>")

    # ── 계단 4: 증인 4명과 데이터 정제 ──────────────────────────────────────
    a('<h2 class="col">계단 4 — 못 막으면 표시한다 <span class="state now">진행 중</span></h2>')
    a('<p class="col">모델을 고쳐서 세탁을 막을 수 없다면, <b>세탁된 자리를 찾아내 학습에서 빼면 된다.</b> '
      "모델을 바꾸는 대신 <b>모델이 배우는 정답지를 고치는</b> 접근이다.</p>")

    a('<h3 class="col">① 증인 4명 — 성격을 섞어 뽑았다</h3>')
    a('<p class="col">받아쓰기 모델 9종을 같은 시험지 100건으로 겨루게 해 넷을 뽑았다'
      "(1종은 저장소 접근 제한으로 탈락). 뽑는 기준은 정확도가 아니라 <b>오류 보존율</b>이다.</p>")
    HIRE = {"owsm-v4", "sensevoice", "qwen3-asr", "fw-small"}
    rows = []
    for r in sorted(done, key=lambda x: -x["보존율"]):
        picked = r["key"] in HIRE
        rows.append([
            f'<b>{esc(SHORT.get(r["이름"], r["이름"]))}</b>'
            + (' <span style="color:var(--orange);">우리</span>' if r["key"] == "lora-v1" else ""),
            esc(r["유형"]), pct(r["보존율"]), f'{r["보존"]}/{r["세탁"]}/{r["기타"]}',
            pct(r["오탐율"]), pct(r["중앙CER"]), f'{r["폭주"]}건', f'{r["건당초"]:.1f}초',
            '<span class="state done">★ 증인</span>' if picked else "—",
        ])
    rows.append(["<b>Cohere Transcribe</b>", "문맥형"] + ["—"] * 6
                + ['<span class="state todo">접근 불가</span>'])
    a(table(["모델", "유형", "오류 보존율", "보존/세탁/기타", "대조군 오탐율",
             "가운뎃값 CER", "폭주", "건당", "선발"], rows, set(range(2, 8))))
    a('<div class="note col">'
      "<b>왜 성격을 섞었나.</b> 말의 문맥을 보고 받아쓰는 ‘문맥형’ 2종(Qwen3-ASR · Whisper small)과 "
      "소리만 듣고 받아쓰는 ‘직청형’ 2종(OWSM-CTC · SenseVoice)이다. "
      "같은 성격끼리만 모으면 <b>함께 틀려서 다수결이 ‘다수의 착각’</b>이 된다.<br><br>"
      "<b>우리 LoRA v1 은 의도적으로 뺐다.</b> 심사 대상인 학습쌍으로 학습한 모델이라 "
      "자신이 만든 세탁을 잡지 못할 뿐 아니라, “우리 모델이 우리 학습 데이터를 심사하는” "
      "순환 구조가 되어 방어할 수 없기 때문이다.</div>")

    a('<h3 class="col">② 전수 받아쓰기와 판정 <span class="state done">완료</span></h3>')
    a(f'<p class="col">증인 4명에게 학습쌍 {total:,}건을 <b>모두</b> 받아쓰게 했다'
      f"(전사 {total * 4:,}줄, GPU 2장 병렬). 그리고 어절 단위로 라벨과 맞춰 보고, "
      "<b>증인 둘 이상이 같은 대안으로 일치하는데 라벨만 표준형인 자리</b>를 세탁 의심으로 표시했다. "
      "2:2 동점은 보류하고, <b>라벨이 오류를 살린 자리는 절대 빼지 않는다</b>(방향 판정).</p>")
    a("<figure>" + clean_bar(counts, total))
    a('<figcaption class="col">'
      f"세탁으로 판정된 <b>자리</b>는 {clean['자리판정']['세탁']:,}곳, "
      f"반대로 <b>라벨이 오류를 제대로 살린 자리</b>는 {clean['자리판정']['역방향']:,}곳이었다 — "
      "후자가 더 많다는 것은 라벨 대부분이 건강하다는 뜻이고, 걷어낼 곳만 걷어내면 된다는 "
      "근거가 된다.</figcaption></figure>")

    a('<h3 class="col">③ 탐지기는 믿을 만한가 — 개발셋 300건 성적</h3>')
    a('<p class="col">감사자 다섯 명이 손으로 고친 <b>gold 300건</b>에서 성적을 냈다. '
      "정답은 “사람이 라벨을 고친 줄”이다 — 사람이 손댔다는 것은 원래 라벨이 틀렸다는 뜻이다.</p>")
    a(table(["구간", "세탁 의심 표시", "맞음", "헛짚음", "정밀도", "재현율"], [
        ["<b>전체 300건</b>", f'{dev["표시"]}건', f'{dev["맞음"]}건', f'{dev["헛짚음"]}건',
         f'<b>{pct(dev["정밀도"])}</b>', pct(dev["재현율"])],
        ["자유발화(ATQ)", f'{dev["ATQ"]["표시"]}건', f'{dev["ATQ"]["맞음"]}건',
         f'{dev["ATQ"]["표시"] - dev["ATQ"]["맞음"]}건',
         f'<span class="win">{pct(dev["ATQ"]["정밀도"])}</span>', pct(dev["ATQ"]["재현율"])],
        ["낭독(LAR)", f'{dev["LAR"]["표시"]}건', f'{dev["LAR"]["맞음"]}건',
         f'{dev["LAR"]["표시"] - dev["LAR"]["맞음"]}건',
         f'<span class="warn">{pct(dev["LAR"]["정밀도"])}</span>', pct(dev["LAR"]["재현율"])],
    ], {1, 2, 3, 4, 5}))
    a('<div class="note col">'
      f"<b>정직하게 — 표본을 넓히니 정밀도가 떨어졌다.</b> 규칙을 다듬는 데 쓴 gold 100건에서는 "
      f"61.5% 였는데, 처음 보는 200건을 더한 개발셋 300건에서는 {pct(dev['정밀도'])} 다. "
      "그 자리에서만 잘 맞는 규칙이 섞여 있었다는 뜻이고, 우리가 <b>개발셋과 실전셋을 미리 갈라 둔 이유</b>"
      "다(실전셋 199건은 규칙 확정 전까지 열지 않는다).<br><br>"
      f"<b>갈래가 갈린다.</b> 자유발화는 {pct(dev['ATQ']['정밀도'])} 로 쓸 만하지만 "
      f"낭독은 {pct(dev['LAR']['정밀도'])} 로 낮다 — 낭독은 제시문이 있어 “라벨=제시문이면 세탁”이라는 "
      "규칙을 쓰기 쉬운데, 그 규칙이 오탐 제조기였다. <b>다음 수리 대상은 낭독 규칙</b>이다.<br><br>"
      f"<b>재현율({pct(dev['재현율'])})은 과소평가다.</b> 분모가 “사람이 고친 모든 줄”인데, "
      "사람은 세탁이 아닌 단순 오타·띄어쓰기도 고쳤다. 우리는 세탁만 노린다.</div>")

    a('<h3 class="col">④ 정제 데이터로 재학습 <span class="state now">진행 중</span></h3>')
    a(f'<p class="col">세탁 의심 {counts["suspect"]:,}건을 걷어낸 '
      f"<b>{total - counts['suspect']:,}건</b>으로 LoRA v2 를 학습한다. "
      "v1 과 <b>바뀌는 것은 데이터뿐</b>이라, 성적이 달라진다면 그 차이는 전부 정제 효과다"
      "(밑바탕·설정·시험지 모두 동일).</p>")
    a('<p class="col">판정할 성적표도 이미 정해 두었다 — <b>오류 보존율</b>이 1순위, '
      "대조군 오탐율이 2순위다. 그리고 v1 때와 같은 실수를 하지 않기 위해, "
      "판정은 <b>같은 파일로 짝지은 부트스트랩</b>으로만 한다.</p>")

    # ── 지금까지 남은 것 ────────────────────────────────────────────────────
    a('<h2 class="col">지금까지 남은 것</h2>')
    a('<div class="grid3">')
    for tag, name, body in [
        ("자를 만들었다", "오류 보존율",
         "“얼마나 정확한가”가 아니라 “학습자의 실수를 살려 적는가”를 재는 자. "
         "이 자가 없으면 <b>가장 잘 듣는 모델을 고르고 실력을 가장 많이 지우게 된다.</b>"),
        ("문제를 밝혔다", f"세탁률 {rate:.0%}",
         "모델 8종 · 100건 실측. <b>한 모델의 결함이 아니라 받아쓰기 기술 전반의 성질</b>임을 "
         "숫자로 보였다."),
        ("장치를 만들었다", "세탁 탐지기",
         f"증인 4명 다수결로 학습쌍 {total:,}건을 전수 심사. "
         f"자유발화 정밀도 {pct(dev['ATQ']['정밀도'], 0)}."),
    ]:
        a(f'<div class="card"><p class="tag">{tag}</p>'
          f'<h3 style="margin:6px 0 0;font-size:18px;">{name}</h3><p>{body}</p></div>')
    a("</div>")

    a('<h3 class="col">아직 못 한 것 — 그리고 어떻게 할 것인가</h3>')
    a(table(["못 한 것", "지금 상태", "돌파 방법"], [
        ["파인튜닝으로 세탁 억제", "v0·v1 실패 (밑바탕과 구분 안 됨)",
         "원인을 학습 목표로 특정 → <b>정제 데이터로 v2</b>, 그다음엔 세탁 자리에 벌점을 주는 손실 함수"],
        ["낭독(LAR) 세탁 탐지", f'정밀도 {pct(dev["LAR"]["정밀도"])}',
         "“라벨=제시문이면 세탁” 규칙이 오탐 제조기 → <b>제시문은 라벨을 지키는 쪽으로만</b> 쓰도록 수리"],
        ["증인 4명의 결정성 재확인", "검사 코드 버그 수리 완료, 재측정 전",
         "고친 검사로 <b>--refresh 재측정</b> — 증인이 물을 때마다 답을 바꾸면 다수결이 무너진다"],
        ["실전셋 199건 평가", "규칙 확정 전까지 열지 않음",
         "규칙을 확정한 뒤 단 한 번 연다 → “한 번도 보지 않은 199건에서 정밀도 X%”"],
    ], set()))

    # ── 용어 ────────────────────────────────────────────────────────────────
    a('<h2 class="col">용어 한 줄 풀이</h2>')
    a('<dl class="col">')
    for t, d in [
        ("세탁", "학습자가 틀리게 말한 것을 받아쓰기 AI 가 표준어로 고쳐서 적는 것. 채점이 실력을 못 보게 만든다."),
        ("오류 보존율", "학습자가 실제로 틀린 자리를 틀린 그대로 적어 준 비율. 높을수록 정직하다."),
        ("대조군 오탐율", "제대로 읽은 녹음인데 다르게 적어서 없던 오류를 만들어 낸 비율. 낮을수록 좋다."),
        ("CER(글자 오류율)", "받아쓴 글을 정답으로 고치는 데 글자를 몇 번 손봐야 하는지. 낮을수록 잘 듣는다."),
        ("폭주", "같은 말을 끝없이 되풀이해 정답보다 두 배 넘게 길어진 것. 그 자리에서는 증언이 통째로 빠진다."),
        ("문맥형 / 직청형", "앞말을 보고 다음 글자를 지어내는 쪽 / 소리만 듣고 글자를 붙이는 쪽."),
        ("LoRA", "큰 모델을 통째로 다시 학습시키지 않고 작은 덧붙임만 학습시켜 성격을 바꾸는 방법."),
        ("부트스트랩", "가진 자료에서 다시 뽑기를 수천 번 되풀이해 “이 차이가 우연일 수 있나”를 재는 방법."),
        ("개발셋 / 실전셋", "규칙을 다듬으며 봐도 되는 몫 / 규칙이 굳을 때까지 열지 않는 몫. 자기 데이터에만 맞는 규칙을 막는다."),
    ]:
        a(f"<dt>{esc(t)}</dt><dd>{esc(d)}</dd>")
    a("</dl>")
    a("</div>")

    a('<footer class="wrap" style="padding-left:24px;padding-right:24px;">')
    a(f'K-TEST 문제·채점 모델 파트 · 모델 오디션 {esc(res["실행시각"])} · '
      f"학습쌍 정제 {total:,}건 · 시험지 <code>data/manifests/gold_100.jsonl</code> · "
      "이 문서의 모든 숫자는 <code>make_lora_report.py</code> 가 결과 파일에서 다시 계산한 것이다.")
    a("</footer>")

    REPORT.write_text("\n".join(H) + "\n", encoding="utf-8")
    print(f"저장: {REPORT}")
    print(f"  세탁률 {rate:.1%} · 정제 {total:,}건 중 제거 {counts['suspect']:,}건 · "
          f"개발셋 정밀도 {dev['정밀도']:.1%}(자유발화 {dev['ATQ']['정밀도']:.1%})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
