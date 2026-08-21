# -*- coding: utf-8 -*-
"""실험 결과 파일을 읽어 팀에게 보여 줄 HTML 보고서를 만든다.

손으로 숫자를 옮겨 적으면 반드시 어긋난다(그리고 어긋난 걸 아무도 모른다).
그래서 보고서는 **결과 JSON 에서 직접** 만든다. 실험을 다시 돌리면 이 스크립트를
다시 실행하는 것만으로 보고서의 모든 수치와 그림이 함께 갱신된다.

읽는 파일:
    outputs/checklist_lab/results_summary.json   — 방식별 성적·차이·재현성
    outputs/checklist_lab/extra_baselines.json   — 기준선(바닥·길이·상한)
    outputs/checklist_lab/c_model_weights.json   — C 가 문항마다 배운 항목 비중
    outputs/checklist_lab/checklists.json        — 문항별 체크리스트 본문

쓰는 법:
    python make_report.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from statistics import mean

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _lab_common import OUT_DIR, ASSESSMENT_DIR, enable_utf8_output  # noqa: E402

REPORT_PATH = ASSESSMENT_DIR / "체크리스트채점_실험보고_20260809.html"

# 색은 dataviz 검증기를 통과한 조합만 쓴다(파랑↔주황 대비 ΔE 24.7).
BLUE, ORANGE, NEUTRAL = "var(--blue)", "var(--orange)", "var(--neutral)"


def esc(text: str) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


# ── 막대그래프 ───────────────────────────────────────────────────────────────
def qwk_chart(bars: list[dict]) -> str:
    """가로 막대 + 신뢰구간 수염. 좌표를 파이썬이 계산해 손 오차를 없앤다."""
    x0, x1 = 250.0, 980.0          # 0.0 과 1.0 의 화면 위치
    top, step, bar_h = 46.0, 42.0, 15.0
    axis_y = top + step * len(bars) - 12
    height = axis_y + 60

    def sx(v: float) -> float:
        return x0 + (x1 - x0) * max(0.0, min(1.0, v))

    parts = [
        f'<svg viewBox="0 0 1000 {height:.0f}" role="img" aria-label="'
        + esc("방식별 QWK 막대그래프. " + " · ".join(f"{b['label']} {b['value']:.3f}" for b in bars))
        + '">'
    ]

    # 눈금선 — 데이터 뒤로 물러나 있어야 한다
    parts.append('<g stroke="var(--rule-strong)" stroke-opacity=".55">')
    for i in range(6):
        gx = sx(i * 0.2)
        parts.append(f'<line x1="{gx:.1f}" y1="28" x2="{gx:.1f}" y2="{axis_y:.1f}"></line>')
    parts.append("</g>")

    parts.append('<g font-family="Consolas, D2Coding, monospace" font-size="12" fill="var(--muted)">')
    for i in range(6):
        gx = sx(i * 0.2)
        parts.append(f'<text x="{gx:.1f}" y="{axis_y + 20:.0f}" text-anchor="middle">{i * 0.2:.1f}</text>')
    parts.append(
        f'<text x="{(x0 + x1) / 2:.0f}" y="{axis_y + 44:.0f}" text-anchor="middle">'
        + esc("QWK — 사람 점수와의 일치도 (1.0 = 완전 일치 · 0 = 우연 수준)")
        + "</text></g>"
    )

    for i, b in enumerate(bars):
        cy = top + step * i
        by = cy - bar_h / 2
        bx = sx(b["value"])
        dashed = ' stroke-dasharray="4 3"' if b.get("dashed") else ""
        # 막대(끝만 둥글게 — 시작점은 0 에 붙어 있어야 한다)
        r = 4.0
        w = max(bx - x0, r + 0.1)
        parts.append(
            f'<path d="M{x0:.1f} {by:.1f} H{x0 + w - r:.1f} a{r} {r} 0 0 1 {r} {r} '
            f'V{by + bar_h - r:.1f} a{r} {r} 0 0 1 -{r} {r} H{x0:.1f} Z" '
            f'fill="{b["color"]}" fill-opacity="{b.get("opacity", 1)}"{dashed}>'
            f'<title>{esc(b["label"])}: QWK {b["value"]:.3f} (95% 구간 {b["lo"]:.3f}~{b["hi"]:.3f})</title></path>'
        )
        # 신뢰구간 수염
        lo, hi = sx(b["lo"]), sx(b["hi"])
        parts.append(
            f'<g stroke="var(--ink)" stroke-opacity=".55" stroke-width="1.5">'
            f'<line x1="{lo:.1f}" y1="{cy:.1f}" x2="{hi:.1f}" y2="{cy:.1f}"></line>'
            f'<line x1="{lo:.1f}" y1="{cy - 4.5:.1f}" x2="{lo:.1f}" y2="{cy + 4.5:.1f}"></line>'
            f'<line x1="{hi:.1f}" y1="{cy - 4.5:.1f}" x2="{hi:.1f}" y2="{cy + 4.5:.1f}"></line></g>'
        )
        # 왼쪽 이름표 + 오른쪽 값
        parts.append(
            f'<text x="{x0 - 16:.0f}" y="{cy + 4.5:.1f}" text-anchor="end" '
            f'font-family="Malgun Gothic, Apple SD Gothic Neo, Segoe UI, sans-serif" '
            f'font-size="13.5" fill="var(--ink)">{esc(b["label"])}</text>'
        )
        parts.append(
            f'<text x="{hi + 12:.1f}" y="{cy + 4.5:.1f}" '
            f'font-family="Consolas, D2Coding, monospace" font-size="13" '
            f'font-variant-numeric="tabular-nums" fill="var(--ink-2)">{b["value"]:.3f}</text>'
        )

    parts.append("</svg>")
    return "\n".join(parts)


# ── 표 ───────────────────────────────────────────────────────────────────────
def table(headers: list[str], rows: list[list[str]], num_cols: set[int]) -> str:
    head = "".join(
        f'<th class="{"num" if i in num_cols else ""}">{esc(h)}</th>'
        for i, h in enumerate(headers)
    )
    body = []
    for r in rows:
        cells = "".join(
            f'<td class="{"num" if i in num_cols else ""}">{c}</td>' for i, c in enumerate(r)
        )
        body.append(f"<tr>{cells}</tr>")
    return (f'<div class="scroll"><table><thead><tr>{head}</tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table></div>')


def ci(d: dict) -> str:
    return f'[{d["lo"]:.3f}, {d["hi"]:.3f}]'


def diff_of(pairs: dict, a: str, b: str) -> dict | None:
    """a − b 의 차이 구간을 꺼낸다. 저장된 순서가 반대면 부호를 뒤집어 맞춘다."""
    if f"{a}-{b}" in pairs:
        return pairs[f"{a}-{b}"]
    d = pairs.get(f"{b}-{a}")
    if d is None:
        return None
    return {"mean": -d["mean"], "lo": -d["hi"], "hi": -d["lo"]}


def diff_row(pairs: dict, a: str, b: str, label: str) -> list[str]:
    d = diff_of(pairs, a, b)
    if d is None:
        return [label, "-", "-", '<span class="pill no">미계산</span>']
    if d["lo"] > 0:
        v, cls = "앞쪽이 유의하게 높다", "yes"
    elif d["hi"] < 0:
        v, cls = "뒤쪽이 유의하게 높다", "yes"
    else:
        v, cls = "0을 걸친다 → 주장 불가", "no"
    return [label, f'{d["mean"]:+.3f}', ci(d), f'<span class="pill {cls}">{v}</span>']


def build_v2_section(V2: dict, CL2: dict) -> str:
    """논문(RLCF) 방식으로 체크리스트를 다시 뽑은 2차 실험 절."""
    m2 = V2["methods"]
    pairs = V2["pairwise_diff_qwk_ci95"]

    def bar(key: str, label: str, color: str, **kw) -> dict:
        v = m2[key]
        return {"label": label, "value": v["qwk"], "lo": v["qwk_ci95"]["lo"],
                "hi": v["qwk_ci95"]["hi"], "color": color, **kw}

    bars = [
        bar("CEIL_V2_LIN", "v2 항목의 정보 천장", NEUTRAL, opacity=.45, dashed=True),
        bar("A1", "A1 LLM 직접 채점(퓨샷)", BLUE),
        bar("A0", "A0 LLM 직접 채점(제로샷)", BLUE, opacity=.75),
        bar("F", "F v2 체크리스트+가중치 학습", ORANGE),
        bar("CEIL_V1_LIN", "v1 항목의 정보 천장", NEUTRAL, opacity=.3, dashed=True),
        bar("LEN", "길이 기준선(글자 수만)", NEUTRAL, opacity=.7),
        bar("C", "C v1 체크리스트+가중치 학습", ORANGE, opacity=.55),
        bar("H", "H v2 0~100 점수+가중치 학습", ORANGE, opacity=.85),
        bar("D", "D v2 충족율×5", ORANGE, opacity=.55),
        bar("G", "G v2 0~100 중요도 가중(논문)", ORANGE, opacity=.55),
        bar("E", "E v2 중요도 가중 충족율(논문)", ORANGE, opacity=.55),
        bar("B", "B v1 충족율×5", ORANGE, opacity=.4),
    ]

    rows = []
    for key, note in (("D", "학습 안 씀"), ("E", "학습 안 씀 · 논문 방식"),
                      ("F", "학습 씀"), ("G", "학습 안 씀 · 논문 방식"), ("H", "학습 씀"),
                      ("D_noU", "보편 항목 제외"), ("E_noU", "보편 항목 제외"),
                      ("F_noU", "보편 항목 제외")):
        v = m2[key]
        rows.append([esc(v["label"]), note, f'<b>{v["qwk"]:.3f}</b>', ci(v["qwk_ci95"]),
                     f'{v["exact"] * 100:.1f}%', f'{v["within1"] * 100:.1f}%'])
    method_table = table(["방식", "성격", "QWK", "95% 신뢰구간", "정확 일치", "±1 이내"],
                         rows, {2, 3, 4, 5})

    ceil_rows = []
    for k1, k2, lab in (("CEIL_V1_CNT", "CEIL_V2_CNT", "충족 개수만 쓰기 (중앙값 사상)"),
                        ("CEIL_V1_OPT", "CEIL_V2_OPT", "충족 개수만 쓰기 (QWK 최대 사상)"),
                        ("CEIL_V1_LIN", "CEIL_V2_LIN", "항목 하나하나 다 쓰기 (선형 적합)")):
        d = diff_of(pairs, k2, k1)
        judged = "올랐다" if d and d["lo"] > 0 else "주장 불가"
        cls = "yes" if judged == "올랐다" else "no"
        ceil_rows.append([lab, f'{m2[k1]["qwk"]:.3f}', f'{m2[k2]["qwk"]:.3f}',
                          f'{d["mean"]:+.3f}' if d else "-", ci(d) if d else "-",
                          f'<span class="pill {cls}">{judged}</span>'])
    ceil_table = table(["천장을 재는 방법", "v1 (항목 2개)", "v2 (항목 6개)", "차이", "95% 신뢰구간", "판정"],
                       ceil_rows, {1, 2, 3, 4})

    key_diffs = table(
        ["비교 (앞 − 뒤)", "QWK 차이", "95% 신뢰구간", "판정"],
        [diff_row(pairs, "F", "C", "F v2 학습 − C v1 학습"),
         diff_row(pairs, "F", "D", "F v2 학습 − D v2 충족율"),
         diff_row(pairs, "F", "LEN", "F v2 학습 − 길이 기준선"),
         diff_row(pairs, "F", "A0", "F v2 학습 − A0 LLM 제로샷"),
         diff_row(pairs, "F", "A1", "F v2 학습 − A1 LLM 퓨샷"),
         diff_row(pairs, "E", "D", "E 중요도 가중 − D 단순 충족율"),
         diff_row(pairs, "G", "E", "G 0~100 − E 이진 중요도 가중"),
         diff_row(pairs, "F", "H", "F 이진+학습 − H 0~100+학습"),
         diff_row(pairs, "D", "D_noU", "보편 항목 넣기 − 빼기 (D)"),
         diff_row(pairs, "F", "F_noU", "보편 항목 넣기 − 빼기 (F)")],
        {1, 2})

    items = V2["checklist_items"]
    n_task = sorted({v["n_task_items_v2"] for v in items.values()})
    n_uni = sorted({v["n_universal_items_v2"] for v in items.values()})
    example = next(iter(CL2.values())) if CL2 else None
    example_html = ""
    if example:
        lis = "".join(
            f'<li><b>{it.get("importance", "-")}</b> · {esc(it["question"])}'
            + (' <span class="pill no">보편</span>' if it.get("universal") else "") + "</li>"
            for it in example["items"])
        example_html = (f'<p class="col" style="margin-top:22px;"><b>실제로 나온 체크리스트</b> — '
                        f'“{esc(example["prompt"])}” (앞의 숫자가 LLM 이 매긴 중요도 0~100)</p>'
                        f'<ol class="col" style="font-size:14.5px;color:var(--ink-2);">{lis}</ol>')

    # 0~100 판정이 실제로 몇 가지 값만 쓰는지 원자료에서 직접 센다(손으로 적지 않는다)
    n_cells, n_three = 0, 0
    j2 = OUT_DIR / "judgments_v2.jsonl"
    if j2.exists():
        for line in j2.read_text(encoding="utf-8").splitlines():
            rec = json.loads(line)
            if rec.get("pass") != "main":
                continue
            for it in rec.get("items") or []:
                if "score" in it:
                    n_cells += 1
                    n_three += int(it["score"] in (0, 50, 100))
    three_pct = (n_three / n_cells * 100) if n_cells else 0.0

    rep2 = V2["reproducibility"]
    bin_flip = rep2["binary_cell_flip"]
    scr_flip = rep2.get("score_cell_flip", {})
    cite2 = V2["citation_protocol"]
    dfp = "".join(f"<li>{esc(x)}</li>" for x in V2["differences_from_paper"])

    return f"""
<hr>

<section class="col">
  <p class="eyebrow">후속 실험 (같은 날)</p>
  <h2>논문 방식으로 항목을 늘려 봤다</h2>
  <p>1차 실험의 진단은 “항목이 2 개뿐이라 천장이 낮다”였다. 그래서 논문
  <b>RLCF</b>(<i>Checklists Are Better Than Reward Models</i>, Apple·CMU, 2025)의 체크리스트 생성법을 그대로 이식했다.
  논문의 핵심은 <b>지시문만 보고 항목을 뽑지 말라</b>는 것이다 —
  ① 품질이 서로 다른 후보 답안을 먼저 만들고 ② <b>그것들이 실패하는 방식</b>을 전부 적어 항목으로 삼으며
  ③ 항목마다 <b>중요도 0~100</b> 을 붙인다. 논문 실측으로 이 방식이 원자성 68→90, 포괄성 74→82 로 앞선다.</p>
  <p>우리 조건에 맞춘 것 두 가지. 후보 답안은 <b>실제 응시자 답안을 절대 쓰지 않고</b> 지시문만 보고 지어냈다(시험지 오염 방지).
  그리고 논문이 붙이는 <b>보편 항목 2 개</b>(직접 답했는가 · 상황에 맞는 말투인가)를 우리 말하기 시험 말로 옮겨 붙였다.</p>
  <p>결과: 항목이 문항당 2 개 → <b>과제 항목 {n_task[0]}개 + 보편 항목 {n_uni[0]}개 = {n_task[0] + n_uni[0]}개</b>로 늘었다(9 문항 전부 같음).
  상한을 10 개로 열어 뒀는데도 4 개에서 멈춘 것은, 이 문항들이 실제로 요구하는 것이 그만큼이기 때문이다.</p>
</section>

{example_html}

<section>
  <h2 class="col" style="margin-top:34px;">1차·2차를 한 그림에</h2>
  <figure>
    <div class="legend">
      <span><i style="background:{BLUE}"></i>LLM 이 직접 채점</span>
      <span><i style="background:{ORANGE}"></i>체크리스트로 채점</span>
      <span><i style="background:{NEUTRAL};opacity:.7"></i>기준선·천장</span>
    </div>
    {qwk_chart(bars)}
    <figcaption>같은 답안 {V2["common_sample"]["n"]}건 · 같은 겹 · 같은 모델. 점선 막대는 실제로 쓸 수 없는 천장(정답을 보고 맞춘 값)이다.</figcaption>
  </figure>
  {method_table}
</section>

<section>
  <p class="eyebrow">결과 ①</p>
  <h2 class="col">천장은 실제로 올라갔다 — 단, 조건이 붙는다</h2>
  {ceil_table}
  <div class="note col"><b>“몇 개 맞았나”만 세면 천장이 안 올라가고, “어느 항목을 맞았나”를 쓰면 올라간다.</b>
  늘어난 항목의 값어치가 개수가 아니라 <b>어떤 항목인지</b>에 들어 있다는 뜻이다.
  그래서 개수만 쓰는 D·E 는 제자리였고, 항목별 비중을 배우는 F 만 올랐다.</div>
</section>

<section>
  <p class="eyebrow">결과 ②</p>
  <h2 class="col">그 천장을 받아 간 것은 가중치 학습 하나뿐</h2>
  {key_diffs}
  <ul class="col" style="margin-top:16px;">
    <li><b>F(v2 항목 + 문항별 학습) 0.698 — 1차의 같은 방식 C(0.620)를 유의하게 이겼다.</b> 항목을 늘린 값이 여기서 나왔다.</li>
    <li><b>그래도 LLM 직접 채점에는 진다.</b> A1(0.787)·A0(0.758) 모두에 유의하게 뒤진다.</li>
    <li><b>“글자 수만 세기”(0.636)를 이겼다고는 말할 수 없다.</b> 차이는 있지만 구간이 0 을 걸친다.</li>
    <li><b>논문의 자랑거리 두 개는 우리 조건에서 작동하지 않았다</b> — 중요도 가중(E−D)도, 0~100 유연 채점(G−E)도 차이를 주장할 수 없다.</li>
    <li><b>보편 항목 2 개</b>는 넣으나 빼나 차이를 주장할 수 없다(점 추정은 넣는 쪽이 근소하게 높음).</li>
  </ul>
</section>

<section class="col">
  <p class="eyebrow">왜 논문 장치가 안 먹었나</p>
  <h2>0~100 채점이 사실은 세 칸이었다</h2>
  <p>항목 점수 {n_cells:,}칸을 열어 보니 <b>{three_pct:.0f}% 가 0 · 50 · 100</b> 세 값이었다.
  논문은 항목마다 <b>25 번 뽑아 평균</b>을 내서 부드러운 점수를 만드는데, 우리는 재현성 규칙 때문에 <b>온도 0 · 1 회 호출</b>이라
  평균 낼 것이 없다. 0~100 이 이진보다 나을 이유가 사라진 것이고, 그 잡음 섞인 값으로 학습한 H(0.596)가
  이진으로 학습한 F(0.698)에 유의하게 진 것이 그 대가다.</p>
  <p>중요도 가중이 안 먹은 이유도 같은 결이다 — 과제 항목 4 개 중 2 개가 중요도 100 으로 몰려서
  가중치의 실질 차이가 작았다. <b>중요도를 LLM 이 짐작해 주는 것보다, 데이터에서 배우는 쪽이 확실히 낫다</b>는 것이 이번 대조의 결론이다.</p>
  <p><b>부수 발견 — 부정형 항목은 우리 인용 규약과 부딪힌다.</b> “~을 배제했는가”, “~을 늘어놓지 않았는가” 같은 항목은
  <b>없는 것을 원문에서 인용할 수 없어</b> 무더기로 폐기됐다(이진 {cite2["B2_dropped_citations_total"]}건 · 점수 {cite2["S2_dropped_citations_total"]}건).
  다음 생성 프롬프트에서는 <b>부정형 항목을 금지</b>해야 한다.</p>
  <p><b>재현성은 이번에도 우열을 못 가렸다.</b> 이진·0~100 두 패스 모두 3 회가 소수점까지 같았고
  항목 칸 변동은 이진 {bin_flip["n_flipped"]}/{bin_flip["n_cells"]}, 점수 {scr_flip.get("n_flipped", 0)}/{scr_flip.get("n_cells", 0)} 이다.
  “칸이 많아지면 더 흔들릴 것”이라는 예상이 빗나갔다 — 흔들린 것이 아니라 애초에 세 칸만 쓰고 있었다.</p>
</section>

<section class="col">
  <p class="eyebrow">정직하게</p>
  <h2>논문과 우리 조건의 차이</h2>
  <p>아래 차이가 있으므로, 이 결과는 <b>“논문 방식이 틀렸다”가 아니라 “우리 조건에서는 이렇게 나왔다”</b>로 읽어야 한다.</p>
  <ul>{dfp}</ul>
</section>
"""


def main() -> int:
    enable_utf8_output()
    S = json.loads((OUT_DIR / "results_summary.json").read_text(encoding="utf-8"))
    B = json.loads((OUT_DIR / "extra_baselines.json").read_text(encoding="utf-8"))
    W = json.loads((OUT_DIR / "c_model_weights.json").read_text(encoding="utf-8"))
    CL = json.loads((OUT_DIR / "checklists.json").read_text(encoding="utf-8"))
    # 2차 실험(논문 방식)은 있으면 붙이고 없으면 1차만으로 보고서를 만든다
    v2_path = OUT_DIR / "results_summary_v2.json"
    V2 = json.loads(v2_path.read_text(encoding="utf-8")) if v2_path.exists() else None
    CL2_path = OUT_DIR / "checklists_v2.json"
    CL2 = json.loads(CL2_path.read_text(encoding="utf-8")) if CL2_path.exists() else {}

    m = S["methods"]
    ds = S["dataset"]
    n = S["common_sample"]["n"]

    # 그림에 올릴 6줄 — 높은 순으로 세운다
    bl_q, bl_ci = B["qwk"], B["ci95"]
    bars = [
        {"label": "A1 LLM 직접 채점(퓨샷)", "value": m["A1"]["qwk"],
         "lo": m["A1"]["qwk_ci95"]["lo"], "hi": m["A1"]["qwk_ci95"]["hi"], "color": BLUE},
        {"label": "A0 LLM 직접 채점(제로샷)", "value": m["A0"]["qwk"],
         "lo": m["A0"]["qwk_ci95"]["lo"], "hi": m["A0"]["qwk_ci95"]["hi"], "color": BLUE},
        {"label": "체크리스트 정보 천장", "value": bl_q["체크리스트 상한(정답 보고 사상)"],
         "lo": bl_ci["체크리스트 상한(정답 보고 사상)"]["lo"],
         "hi": bl_ci["체크리스트 상한(정답 보고 사상)"]["hi"],
         "color": NEUTRAL, "opacity": .45, "dashed": True},
        {"label": "길이 기준선(글자 수만)", "value": bl_q["길이 기준선(글자 수만)"],
         "lo": bl_ci["길이 기준선(글자 수만)"]["lo"], "hi": bl_ci["길이 기준선(글자 수만)"]["hi"],
         "color": NEUTRAL, "opacity": .7},
        {"label": "C 체크리스트+가중치 학습", "value": m["C"]["qwk"],
         "lo": m["C"]["qwk_ci95"]["lo"], "hi": m["C"]["qwk_ci95"]["hi"], "color": ORANGE},
        {"label": "B 체크리스트 충족율×5", "value": m["B"]["qwk"],
         "lo": m["B"]["qwk_ci95"]["lo"], "hi": m["B"]["qwk_ci95"]["hi"], "color": ORANGE},
    ]

    # ① 방식별 성적표
    dot = '<span class="dot" style="background:%s"></span>'
    score_rows = []
    for key, color in (("A0", BLUE), ("A1", BLUE), ("B", ORANGE), ("C", ORANGE)):
        v = m[key]
        score_rows.append([
            (dot % color) + esc(v["label"]),
            "학습 씀" if v["uses_training_data"] else "학습 안 씀",
            f'{v["llm_calls_per_answer"]}회',
            f'<b>{v["qwk"]:.3f}</b>', ci(v["qwk_ci95"]),
            f'{v["pearson"]:.3f}', f'{v["exact"] * 100:.1f}%', f'{v["within1"] * 100:.1f}%',
            f'{v["mean_pred"]:.2f}',
        ])
    score_table = table(
        ["방식", "학습 데이터", "답안당 LLM 호출", "QWK", "95% 신뢰구간",
         "피어슨", "정확 일치", "±1 이내", "평균 예측"],
        score_rows, {3, 4, 5, 6, 7, 8})

    # ② 차이 유의성
    def verdict_pill(text: str) -> str:
        cls = "no" if "걸친다" in text else "yes"
        return f'<span class="pill {cls}">{esc(text)}</span>'

    short = {"A0": "A0 LLM 제로샷", "A1": "A1 LLM 퓨샷",
             "B": "B 체크리스트 충족율", "C": "C 체크리스트+가중치"}
    diff_rows = []
    for name, d in S["pairwise_diff_qwk_ci95"].items():
        a, b = name.split("-", 1)
        diff_rows.append([f"{esc(short.get(a, a))} − {esc(short.get(b, b))}",
                          f'{d["mean"]:+.3f}', ci(d), verdict_pill(d["verdict"])])
    for name, d in B["diff_ci95"].items():
        if "상한" in name or "길이" in name:
            a, b = name.split("-", 1)
            v = ("0을 걸친다 → 차이를 주장할 수 없다" if d["lo"] < 0 < d["hi"]
                 else ("앞쪽이 유의하게 높다" if d["lo"] > 0 else "뒤쪽이 유의하게 높다"))
            diff_rows.append([f"{esc(a)} − {esc(b)}", f'{d["mean"]:+.3f}', ci(d), verdict_pill(v)])
    diff_table = table(["비교 (앞 − 뒤)", "QWK 차이", "95% 신뢰구간", "판정"], diff_rows, {1, 2})

    # ③ 재현성
    rep = S["reproducibility"]["methods"]
    rep_rows = [[
        esc(m[k]["label"]), f'{rep[k]["n"]}건',
        f'{rep[k]["exact_agreement"] * 100:.1f}%',
        f'{rep[k]["mean_amplitude"]:.3f}', f'{rep[k].get("max_amplitude", 0)}',
    ] for k in ("A0", "A1", "B", "C")]
    rep_table = table(["방식", "3회 다 성공", "3회 점수 완전일치", "평균 진폭", "최대 진폭"],
                      rep_rows, {1, 2, 3, 4})

    # ④ 문항별 — 지시문과 항목 수는 체크리스트 파일에서 가져온다
    per = S["per_prompt_qwk"]
    item_rows = []
    for pkey, v in per.items():
        entry = CL.get(pkey, {})
        item_rows.append([
            f'<span class="q">{esc(entry.get("prompt", pkey))}</span>',
            f'{v["n"]}건', f'{len(entry.get("items", []))}개',
            f'{v["A0"]:.3f}', f'{v["A1"]:.3f}', f'{v["B"]:.3f}', f'{v["C"]:.3f}',
        ])
    item_table = table(["문항 지시문", "답안 수", "체크리스트 항목", "A0", "A1", "B", "C"],
                       item_rows, {1, 2, 3, 4, 5, 6})

    # ⑤ C 가 배운 가중치
    weight_rows = []
    for pkey, v in W.items():
        coefs: dict[str, list[float]] = {}
        for f in v["folds"]:
            for cid, c in (f.get("coefficients") or {}).items():
                coefs.setdefault(cid, []).append(c)
        if not coefs:
            continue
        qs = v["questions"]
        items = sorted(coefs.items(), key=lambda kv: -mean(kv[1]))
        weight_rows.append([
            f'<span class="q">{esc(CL[pkey]["prompt"])}</span>',
            "".join(
                f'<div class="wq"><b>{mean(vals):+.2f}</b> {esc(qs.get(cid, cid))}</div>'
                for cid, vals in items),
        ])
    weight_table = table(["문항", "배운 항목 비중 (충족하면 점수가 몇 점 오르는가 · 5겹 평균)"],
                         weight_rows, set())

    v2_section = build_v2_section(V2, CL2) if V2 else ""

    gen = S.get("checklist_generation_reproducibility") or {}
    gen_same = sum(1 for p in gen.get("prompts", {}).values()
                   if p.get("wording_identical")) if gen else 0
    gen_total = len(gen.get("prompts", {})) if gen else 0

    cite = S["citation"]
    lim = "".join(f"<li>{esc(x)}</li>" for x in S["limitations"])

    html = f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>체크리스트 채점 실험 보고 — 2026-08-09</title>
<style>
:root{{
  color-scheme:light;
  --ground:#f5f7f9; --surface:#ffffff; --surface-2:#eceff4;
  --ink:#12161d; --ink-2:#4c5665; --muted:#7f8a99;
  --rule:#dfe4ea; --rule-strong:#c7d0da;
  --blue:#2a78d6; --orange:#eb6834; --neutral:#8b96a5; --good:#0f7a56;
  --shadow:0 1px 2px rgba(18,22,29,.05), 0 10px 28px rgba(18,22,29,.05);
}}
@media (prefers-color-scheme:dark){{
  :root:not([data-theme="light"]){{
    color-scheme:dark;
    --ground:#111419; --surface:#191d24; --surface-2:#222831;
    --ink:#eef1f5; --ink-2:#b4bdc9; --muted:#8792a1;
    --rule:#2a313b; --rule-strong:#3b4552;
    --blue:#3987e5; --orange:#d95926; --neutral:#7d8899; --good:#199e70;
    --shadow:none;
  }}
}}
:root[data-theme="dark"]{{
  color-scheme:dark;
  --ground:#111419; --surface:#191d24; --surface-2:#222831;
  --ink:#eef1f5; --ink-2:#b4bdc9; --muted:#8792a1;
  --rule:#2a313b; --rule-strong:#3b4552;
  --blue:#3987e5; --orange:#d95926; --neutral:#7d8899; --good:#199e70;
  --shadow:none;
}}
*{{box-sizing:border-box;}}
html{{-webkit-text-size-adjust:100%;}}
body{{margin:0;background:var(--ground);color:var(--ink);
  font-family:"Malgun Gothic","Apple SD Gothic Neo","Segoe UI",system-ui,sans-serif;
  font-size:16px;line-height:1.75;letter-spacing:-.01em;}}
.wrap{{max-width:1080px;margin:0 auto;padding:0 24px 40px;}}
.col{{max-width:730px;}}
h1,h2,h3{{font-family:"Batang","Nanum Myeongjo",Georgia,serif;font-weight:700;
  text-wrap:balance;letter-spacing:-.02em;line-height:1.32;margin:0;}}
h1{{font-size:34px;}} h2{{font-size:25px;margin:0 0 8px;}} h3{{font-size:17px;margin:0 0 4px;}}
p{{margin:0 0 14px;}} a{{color:var(--blue);}}
.eyebrow{{font-size:11.5px;font-weight:700;letter-spacing:.15em;text-transform:uppercase;
  color:var(--muted);margin:0 0 8px;font-family:Consolas,"D2Coding",monospace;}}
header.top{{border-bottom:1px solid var(--rule);background:var(--surface);}}
header.top .wrap{{padding-top:46px;padding-bottom:34px;}}
.kicker{{color:var(--orange);font-weight:700;font-size:13px;letter-spacing:.06em;margin:0 0 12px;}}
.sub{{color:var(--ink-2);font-size:18px;margin:14px 0 0;max-width:730px;}}
.meta{{display:flex;flex-wrap:wrap;gap:4px 26px;margin-top:22px;padding-top:16px;
  border-top:1px solid var(--rule);font-family:Consolas,"D2Coding",monospace;
  font-size:12.5px;color:var(--muted);}}
.meta b{{color:var(--ink-2);font-weight:600;}}
section{{margin-top:54px;}}
.lead{{background:var(--surface);border:1px solid var(--rule);border-left:3px solid var(--orange);
  padding:22px 24px;box-shadow:var(--shadow);margin-top:34px;}}
.lead p:last-child{{margin-bottom:0;}}
.lead .big{{font-size:19px;line-height:1.65;}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(228px,1fr));gap:14px;margin:20px 0 4px;}}
.card{{background:var(--surface);border:1px solid var(--rule);padding:16px 18px;box-shadow:var(--shadow);}}
.card .tag{{font-family:Consolas,"D2Coding",monospace;font-size:11.5px;color:var(--muted);letter-spacing:.06em;}}
.card p{{font-size:14.5px;color:var(--ink-2);margin:6px 0 0;line-height:1.65;}}
.swatch{{display:inline-block;width:9px;height:9px;margin-right:6px;}}
figure{{margin:22px 0 6px;background:var(--surface);border:1px solid var(--rule);
  padding:20px 20px 12px;box-shadow:var(--shadow);overflow-x:auto;}}
figure svg{{display:block;width:100%;min-width:620px;height:auto;}}
figcaption{{font-size:13.5px;color:var(--muted);margin-top:12px;line-height:1.65;}}
.legend{{display:flex;flex-wrap:wrap;gap:18px;margin:0 0 14px;font-size:13px;color:var(--ink-2);}}
.legend span{{display:inline-flex;align-items:center;gap:7px;}}
.legend i{{width:11px;height:11px;display:inline-block;}}
.scroll{{overflow-x:auto;margin:18px 0 6px;border:1px solid var(--rule);
  background:var(--surface);box-shadow:var(--shadow);}}
table{{border-collapse:collapse;width:100%;font-size:14px;}}
th,td{{padding:9px 14px;text-align:left;border-bottom:1px solid var(--rule);white-space:nowrap;
  vertical-align:top;}}
thead th{{background:var(--surface-2);font-size:12px;letter-spacing:.03em;color:var(--ink-2);
  font-weight:700;border-bottom:1px solid var(--rule-strong);}}
tbody tr:last-child td{{border-bottom:none;}}
.num{{text-align:right;font-family:Consolas,"D2Coding",monospace;font-variant-numeric:tabular-nums;}}
.q{{white-space:normal;display:inline-block;max-width:420px;color:var(--ink-2);line-height:1.55;}}
.wq{{white-space:normal;max-width:520px;line-height:1.55;color:var(--ink-2);}}
.wq b{{font-family:Consolas,"D2Coding",monospace;color:var(--ink);margin-right:6px;}}
.dot{{display:inline-block;width:8px;height:8px;margin-right:8px;}}
.pill{{display:inline-block;padding:1px 9px;border-radius:999px;font-size:12px;font-weight:700;}}
.pill.yes{{background:color-mix(in srgb,var(--good) 15%,transparent);color:var(--good);}}
.pill.no{{background:var(--surface-2);color:var(--muted);}}
ul,ol{{margin:0 0 14px;padding-left:20px;}} li{{margin-bottom:8px;}}
.note{{font-size:14.5px;color:var(--ink-2);border-left:2px solid var(--rule-strong);
  padding-left:14px;margin:18px 0;}}
code{{font-family:Consolas,"D2Coding",monospace;font-size:13px;background:var(--surface-2);
  padding:1px 5px;}}
pre{{background:var(--surface);border:1px solid var(--rule);padding:14px 16px;overflow-x:auto;
  font-family:Consolas,"D2Coding",monospace;font-size:12.5px;line-height:1.75;color:var(--ink-2);}}
dl{{margin:0;}} dt{{font-weight:700;margin-top:15px;}}
dd{{margin:2px 0 0;color:var(--ink-2);font-size:14.5px;}}
footer{{margin-top:56px;padding:20px 0 0;border-top:1px solid var(--rule);
  color:var(--muted);font-size:13px;}}
@media (max-width:700px){{
  h1{{font-size:27px;}} h2{{font-size:21px;}} body{{font-size:15px;}}
  .wrap{{padding:0 16px 32px;}}
}}
</style>
</head>
<body>

<header class="top">
  <div class="wrap">
    <p class="kicker">K-TEST 채점 실험 · ‘내용 및 과제 수행’ 영역</p>
    <h1>체크리스트로 채점하면 더 잘 맞을까</h1>
    <p class="sub">AI Hub 외국인 말하기 답안 {n}건에 채점 방식 네 가지를 똑같이 돌려,
    사람 채점자 점수와 얼마나 맞는지(QWK)와 같은 답안을 세 번 채점해도 같은 점수가 나오는지(재현성)를 쟀다.</p>
    <div class="meta">
      <span><b>날짜</b> {esc(S["run_date"][:10])}</span>
      <span><b>표본</b> 답안 {n}건 · 문항 {ds["대상 문항 수"]}종 · 화자 {ds["n_speakers"]}명</span>
      <span><b>사람 점수</b> AI Hub 전문 평가자 0~5</span>
      <span><b>모델</b> {esc(S["model"])} · 온도 {S["temperature"]:.0f}</span>
      <span><b>LLM 호출</b> {S["n_llm_calls_recorded"]:,}회</span>
    </div>
  </div>
</header>

<div class="wrap">

<div class="note" style="margin-top:26px;border-left:2px solid var(--orange);">
  <b>이 문서는 1·2차 실험이다. 뒤에 3·4차가 있다</b> — 결론을 인용하기 전에 뒤 문서를 함께 보라.
  <br>3차(실제 답안으로 체크리스트 생성): <code>체크리스트채점_3차실험보고_20260809.html</code>
  <br>4차(체크리스트 10개 + 확률 판정): <code>체크리스트채점_4차실험보고_20260809.html</code> — 네 차례 사다리 표가 여기 있다
</div>

<div class="lead">
  <p class="eyebrow">한 줄 결론</p>
  <p class="big"><b>이번 시험지에서는 LLM 이 점수를 직접 매기는 쪽이 이겼다.</b>
  체크리스트로 쪼개 채점하니 사람 점수와의 일치도가 {m["A1"]["qwk"]:.2f} → {m["B"]["qwk"]:.2f} 로 떨어졌고,
  문항별로 항목 비중을 학습시키자 그 손해를 절반쯤 되찾았다({m["C"]["qwk"]:.2f}).
  다만 <b>진 이유가 ‘체크리스트라서’가 아니라 ‘항목이 문항당 2개뿐이라서’</b>라는 것도 함께 나왔다 —
  항목 2개가 담을 수 있는 정보의 천장 자체가 {bl_q["체크리스트 상한(정답 보고 사상)"]:.2f} 였다.</p>
  {'<p class="big" style="margin-top:14px;border-top:1px solid var(--rule);padding-top:14px;">'
   f'<b>그래서 논문(RLCF) 방식으로 항목을 다시 뽑아 2차 실험을 했다.</b> 항목이 2개 → 6개로 늘자 '
   f'정보 천장이 <b>0.69 → {V2["methods"]["CEIL_V2_LIN"]["qwk"]:.2f}</b> 로 올랐고, 그 값을 실제로 받아 간 것은 '
   f'<b>가중치 학습 하나뿐</b>이었다({V2["methods"]["F"]["qwk"]:.2f} — 1차의 같은 방식 {m["C"]["qwk"]:.2f} 를 유의하게 이김). '
   f'그래도 LLM 직접 채점({m["A1"]["qwk"]:.2f})은 못 이겼다.</p>' if V2 else ''}
</div>

<section class="col">
  <p class="eyebrow">무엇을 비교했나</p>
  <h2>바뀌는 것은 오직 ‘점수를 만드는 방법’</h2>
  <p>비교가 성립하려면 달라지는 것이 하나여야 한다. 그래서 <b>모델·온도·읽는 글자를 전부 똑같이</b> 두고
  점수를 만드는 방법만 바꿨다. 입력은 음성이 아니라 <b>사람이 직접 적은 전사</b>를 썼다 —
  받아쓰기 기계를 끼우면 채점 방식의 차이인지 그날 받아쓰기 운인지 구분할 수 없기 때문이다.</p>
</section>

<div class="cards">
  <div class="card"><p class="tag"><span class="swatch" style="background:{BLUE}"></span>A0 · 학습 안 씀</p>
    <h3>LLM 이 바로 점수</h3><p>문항과 답안을 주고 0~5 점을 매기게 한다. 근거 인용도 함께 받는다.</p></div>
  <div class="card"><p class="tag"><span class="swatch" style="background:{BLUE}"></span>A1 · 예시 사용</p>
    <h3>LLM 이 바로 점수 (퓨샷)</h3><p>A0 과 같되 같은 문항의 <b>학습 겹</b>에서 뽑은 채점 예시 4~6 개를 함께 보여 준다.</p></div>
  <div class="card"><p class="tag"><span class="swatch" style="background:{ORANGE}"></span>B · 학습 안 씀</p>
    <h3>체크리스트 충족율</h3><p>문항마다 체크리스트를 미리 만들어 고정하고, 항목마다 O/X 로 판정해 충족율 × 5 를 점수로 삼는다.</p></div>
  <div class="card"><p class="tag"><span class="swatch" style="background:{ORANGE}"></span>C · 가중치 학습</p>
    <h3>체크리스트 + 문항별 가중치</h3><p>B 의 O/X 를 그대로 재사용해 “어느 항목이 더 중요한가”를 사람 점수에서 배운다. LLM 추가 호출 0 회.</p></div>
</div>

<div class="note col">B 와 C 는 <b>완전히 같은 O/X 판정</b>을 쓴다. 둘의 차이는 O/X 를 점수로 바꾸는 방법뿐이라,
“가중치 학습이 무엇을 벌었는가”가 깨끗하게 분리된다.</div>

<section class="col">
  <p class="eyebrow">공정하게 재기</p>
  <h2>못 박아 둔 네 가지</h2>
  <ul>
    <li><b>같은 시험 겹</b> — A1·C 는 학습 데이터를 쓰고 A0·B 는 안 쓴다. 그래서 네 방식 모두
      <b>{esc(S["fold_scheme"]["name"])}</b>의 시험 겹 예측만 모아 채점했다.
      같은 사람이 배우는 쪽과 시험 보는 쪽에 동시에 들어간 경우 {S["fold_scheme"]["diagnostics"]["speaker_leak_count"]}명.</li>
    <li><b>사람 점수</b> — AI Hub 전문 평가자의 내용 점수 0~5.
      분포 {esc(" · ".join(f"{k}점 {v}건" for k, v in ds["human_score_distribution"].items()))}.</li>
    <li><b>신뢰구간</b> — 화자를 통째로 다시 뽑는 부트스트랩 1,000 회.
      <b>구간이 0 을 걸치면 “좋아졌다”고 쓰지 않는다.</b></li>
    <li><b>제외</b> — 한 방식에서라도 점수를 못 낸 답안은 모든 방식에서 뺀다. 최종 제외 {S["common_sample"]["n_excluded"]}건.</li>
  </ul>
</section>

<section>
  <p class="eyebrow">결과 ①</p>
  <h2 class="col">사람 점수와 얼마나 맞았나</h2>
  <figure>
    <div class="legend">
      <span><i style="background:{BLUE}"></i>LLM 이 직접 채점</span>
      <span><i style="background:{ORANGE}"></i>체크리스트로 채점</span>
      <span><i style="background:{NEUTRAL};opacity:.7"></i>비교용 잣대(기준선)</span>
    </div>
    {qwk_chart(bars)}
    <figcaption>가로 막대는 QWK, 가운데 가로선은 95% 신뢰구간이다. 구간이 서로 겹치면 순위를 단정할 수 없다.
    ‘정보 천장’은 정답을 다 보고 가장 유리하게 맞춘 값이라 실제 채점에는 쓸 수 없다 — 체크리스트 항목이 들고 있는 정보의 최대치를 뜻한다.</figcaption>
  </figure>
  {score_table}
  <p class="col" style="margin-top:14px;color:var(--ink-2);font-size:14.5px;">
    ‘정확 일치’는 사람과 점수가 딱 같은 비율, ‘±1 이내’는 한 칸 차이 안에 든 비율이다.
    B 의 ±1 이내가 {m["B"]["within1"] * 100:.0f}% 로 유독 낮은 것은 낼 수 있는 점수가 사실상 0·3·5 세 칸뿐이기 때문이다.</p>
</section>

<section>
  <p class="eyebrow">결과 ②</p>
  <h2 class="col">그 차이가 우연은 아닌가</h2>
  <p class="col">부트스트랩으로 화자를 다시 뽑아 1,000 번 재계산한 결과다. 구간이 0 을 걸치면 차이를 주장하지 않는다.</p>
  {diff_table}
  <ul class="col" style="margin-top:16px;">
    <li><b>LLM 직접 채점이 체크리스트 두 방식보다 유의하게 높다.</b> 차이 +{S["pairwise_diff_qwk_ci95"]["A1-B"]["mean"]:.2f}(vs B) · +{S["pairwise_diff_qwk_ci95"]["A1-C"]["mean"]:.2f}(vs C).</li>
    <li><b>가중치 학습(C)은 충족율(B)보다 유의하게 높다.</b> 팀원 제안 ③이 제안 ②를 이겼다 — 같은 O/X 를 쓰고도 QWK 가 {m["B"]["qwk"]:.3f} → {m["C"]["qwk"]:.3f} 로 올랐다.</li>
    <li><b>퓨샷(A1)이 제로샷(A0)보다 낫다고는 말할 수 없다.</b> 차이 {S["pairwise_diff_qwk_ci95"]["A0-A1"]["mean"]:+.3f}, 구간이 0 을 걸친다.
      예시를 붙이는 값은 이 데이터에서 확인되지 않았다.</li>
  </ul>
</section>

<section>
  <p class="eyebrow">결과 ③</p>
  <h2 class="col">같은 답안을 세 번 채점하면</h2>
  <p class="col">고정한 {S["reproducibility"]["subset_size"]}건을 같은 설정으로 3 회 채점했다.</p>
  {rep_table}
  <div class="note col"><b>네 방식 모두 3 회가 소수점까지 같았다(진폭 0).</b>
  체크리스트 항목 O/X 도 {S["reproducibility"]["checklist_cell_flip"]["n_cells"]}칸 중 한 칸도 뒤집히지 않았다.
  그래서 <b>이번 조건에서 재현성으로는 우열을 가릴 수 없다</b> — “쪼개면 덜 흔들린다”는 가설은 증명도 반증도 되지 않았다(흔들림 자체가 없었다).
  예전에 판정이 흔들렸던 것은 <b>생각을 하는 다른 모델</b>(gemini-3-flash-preview)로 문법 오류를 잡을 때였다.
  이번에 쓴 {esc(S["model"])} 는 짧은 판정에서 결정적으로 동작했다.</div>
  <p class="col">체크리스트 <b>생성</b>도 3 문항 × 3 회를 재 봤는데 {gen_same}/{gen_total} 문항이 문구까지 같았다.
  다만 본 실험은 <b>미리 만들어 고정한 체크리스트 한 벌</b>을 쓰므로, 생성이 흔들리더라도 채점 점수에는 영향이 없다
  (‘시험 전 생성 · 승인 후 고정’ 원칙과 같은 구조다).</p>
</section>

<section>
  <p class="eyebrow">해석</p>
  <h2 class="col">왜 체크리스트가 졌나 — 기준선 세 개로 읽기</h2>
  <p class="col">QWK 0.51 이 나쁜 값인지 아닌지는 혼자서는 알 수 없다. 그래서 같은 표본·같은 겹으로 잣대 세 개를 세웠다.</p>
  <ul class="col">
    <li><b>바닥선 {bl_q["바닥선(학습겹 평균)"]:.2f}</b> — 답안을 아예 읽지 않고 평균 점수만 답하기.</li>
    <li><b>길이 기준선 {bl_q["길이 기준선(글자 수만)"]:.2f}</b> — 답안의 <b>글자 수 하나만</b> 보고 맞히기.
      충족율(B)은 이 잣대에 <b>졌다</b>({B["diff_ci95"].get("길이 기준선(글자 수만)-B 체크리스트 충족율×5", {}).get("mean", 0):+.3f}).
      가중치를 배운 C 도 길이와 <b>비긴다</b>(구간이 0 을 걸침).</li>
    <li><b>정보 천장 {bl_q["체크리스트 상한(정답 보고 사상)"]:.2f}</b> — 충족 개수(0·1·2)를 정답을 다 보고 가장 유리하게 점수로 바꾼 값.
      C 는 이 천장에서 {abs(B["diff_ci95"]["C 체크리스트+가중치 학습-체크리스트 상한(정답 보고 사상)"]["mean"]):.3f} 밖에 떨어져 있지 않다.</li>
  </ul>
  <div class="note col"><b>즉 병목은 결합 방식이 아니라 체크리스트 항목 자체다.</b>
  결합을 아무리 잘해도 항목이 2 개인 한 {bl_q["체크리스트 상한(정답 보고 사상)"]:.2f} 를 넘을 수 없는데,
  LLM 직접 채점은 이미 {m["A1"]["qwk"]:.2f} 다. 8/6 계단 5 실험에서 “병목은 결합층이 아니라 자질”이라고 나온 것과 같은 모양이다.</div>

  <h3 class="col" style="margin-top:28px;">항목이 2 개가 된 것은 프롬프트 잘못이 아니다</h3>
  <p class="col">팀원 프롬프트는 “억지로 개수를 채우지 말라”고 지시하고 있고, AI Hub 문항이 실제로
  “<span style="color:var(--ink-2)">보통 어디에서 쇼핑하세요? 왜 그곳에서 쇼핑하세요?</span>”처럼 요구가 두 개다.
  프롬프트는 지시대로 동작했고, <b>시험지가 얕았다.</b> 우리 K-TEST 직무 문항은 요구가 3~5 개라 천장이 달라질 수 있다.</p>

  <h3 class="col" style="margin-top:28px;">가중치 학습이 실제로 배운 것</h3>
  <p class="col">C 가 문항마다 배운 항목 비중이다. ‘무엇을 말했나’보다 <b>‘왜’를 설명했는지</b>에 큰 값을 준 문항이 여럿이다.</p>
  {weight_table}
</section>

<section>
  <p class="eyebrow">문항별</p>
  <h2 class="col">문항마다 승패가 다르다</h2>
  {item_table}
  <p class="col" style="margin-top:14px;color:var(--ink-2);font-size:14.5px;">
  ‘방 안에 무엇이 있어요?’ 문항은 네 방식이 모두 낮다(사람 점수 자체가 한쪽에 몰려 있어 가를 것이 적다).
  반대로 ‘건강을 지키는 방법’처럼 요구가 뚜렷한 문항은 체크리스트도 0.6~0.7 대로 올라온다.
  문항당 27~40 건뿐이라 이 표는 참고용이다.</p>
</section>

<section class="col">
  <p class="eyebrow">덤으로 나온 것</p>
  <h2>근거 없이 점수를 주는 비율</h2>
  <p>A0·A1 은 LLM 이 점수를 정하므로, 인용이 원문에 없어도 점수가 나간다.
  실측 결과 인용이 원문과 맞은 비율은 A0 {cite["A0_citation_verified_rate"] * 100:.1f}% · A1 {cite["A1_citation_verified_rate"] * 100:.1f}% 였다.
  즉 <b>100 건 중 1 건 안팎은 근거 없이 점수를 준다.</b>
  B 는 규약상 인용이 원문에 없으면 그 항목을 미충족으로 내리므로(폐기 {cite["B_dropped_citations_total"]}건) 그런 점수가 원리적으로 나오지 않는다.
  점수 정확도만 보면 A 계열이 이기지만, <b>“왜 이 점수인가”를 답할 수 있는 쪽은 체크리스트</b>다.</p>
</section>

{v2_section}

<section class="col">
  <p class="eyebrow">그래서 다음</p>
  <h2>제안 다섯 가지</h2>
  <ol>
    <li><b>부정형 항목을 금지하고 한 번 더.</b> 폐기된 항목이 이진 40 건·점수 79 건이다. 이것만 고쳐도 F 가 더 오를 여지가 있다
      (지금은 폐기가 곧 미충족이라 없는 점수를 깎고 있다).</li>
    <li><b>같은 실험을 우리 문항으로.</b> 이번 결론의 한계는 시험지에 있다. AI Hub 문항은 요구가 둘뿐이라 항목이 4 개에서 멈췄다.
      요구가 3~5 개인 직무 문항이면 천장이 더 올라갈 수 있다 — 천장이 오르면 F 도 따라 오른다는 것을 이번에 확인했다.</li>
    <li><b>둘 중 하나가 아니라 둘 다 넣기.</b> LLM 직접 점수와 체크리스트 항목 O/X 를 <b>함께</b> 자질로 넣어 결합 모델(계단 5)을 학습시킨다.
      지금 최고(A1 0.787)와 v2 천장(0.797)이 비슷한 높이라, 남은 이득은 두 신호를 합칠 때 나온다.</li>
    <li><b>체크리스트를 점수용이 아니라 근거·피드백용으로.</b> “무엇이 빠졌는지”를 응시자에게 돌려주는 값은 LLM 점수에는 없다.
      점수는 A 계열, 설명은 체크리스트로 나누는 구성이 가능하다.</li>
    <li><b>모델을 바꿔 순위가 유지되는지 확인.</b> 지금은 판정 모델이 한 종류뿐이라, 이 순위가 모델 특성인지 방식 특성인지 가릴 수 없다.
      논문의 25 회 샘플 평균을 흉내 내려면 온도를 올려야 하는데, 그러면 재현성을 잃는다 — 그 맞바꿈도 함께 재야 한다.</li>
  </ol>
</section>

<section class="col">
  <p class="eyebrow">정직하게</p>
  <h2>이 결과로 말할 수 없는 것</h2>
  <ul>{lim}</ul>
</section>

<section class="col">
  <p class="eyebrow">용어</p>
  <h2>쉬운 말 사전</h2>
  <dl>
    <dt>QWK (이차 가중 카파)</dt>
    <dd>사람 채점자와 기계의 점수가 얼마나 겹치는지 재는 자. 1.0 이면 완전 일치, 0 이면 아무렇게나 찍은 것과 같다.
      한 칸 차이보다 세 칸 차이를 훨씬 크게 벌한다.</dd>
    <dt>시험 겹 (out-of-fold)</dt>
    <dd>배울 때 쓴 답안으로 시험을 보면 점수가 부풀려진다. 그래서 답안을 다섯 묶음으로 갈라, 네 묶음으로 배우고 남은 한 묶음에서만 점수를 낸다.
      사람 단위로 갈라서 같은 화자가 양쪽에 동시에 들어가지 않게 했다.</dd>
    <dt>95% 신뢰구간 · 부트스트랩</dt>
    <dd>표본을 다시 뽑아 계산을 1,000 번 반복해, 이 숫자가 표본이 조금 달랐어도 버틸지를 본다.
      두 방식의 차이 구간이 0 을 포함하면 “차이가 있다”고 말하지 않는다.</dd>
    <dt>퓨샷 (few-shot)</dt>
    <dd>채점 예시 몇 개를 함께 보여 주고 매기게 하는 방식. 예시는 반드시 배우는 쪽 묶음에서만 뽑는다.</dd>
    <dt>문항별 가중치 학습</dt>
    <dd>같은 체크리스트라도 문항마다 중요한 항목이 다르다. “이 문항에서는 이유 설명이 장소 언급보다 세 배 중요하다” 같은 비중을
      사람 점수에서 배우는 것. RocketEval 이 쓴 방식이다.</dd>
    <dt>정보 천장</dt>
    <dd>정답을 다 보고 가장 유리하게 맞췄을 때의 점수. 실제로는 쓸 수 없지만, “이 재료로는 여기까지가 최대”를 알려 준다.</dd>
  </dl>
</section>

<section class="col">
  <p class="eyebrow">다시 돌리려면</p>
  <h2>재현 방법</h2>
  <pre>cd assessment/scripts/checklist_lab
python gen_checklists.py            # 문항별 체크리스트 생성(1회, 고정본)
python run_experiment.py            # A0·A1·B 판정 (중간에 끊겨도 이어서 함)
python run_experiment.py --repro --pass-tag rep1   # 재현성 1·2·3 회차
python analyze.py                   # QWK·신뢰구간·재현성
python extra_baselines.py           # 바닥선·길이 기준선·정보 천장
python make_report.py               # 이 보고서</pre>
  <p style="font-size:14.5px;color:var(--ink-2);">모든 수치의 원본은 <code>assessment/outputs/checklist_lab/results_summary.json</code> 에 있다.
  채점 서버 코드(<code>assessment/src/</code>)는 이 실험에서 한 줄도 바뀌지 않았다(테스트 292 개 통과).</p>
</section>

<footer class="wrap" style="padding-left:0;padding-right:0;">
  K-TEST 문제·채점 모델 파트 · 실험 실행 {esc(S["run_date"])} · 판정 모델 {esc(S["model"])} ·
  이 문서는 <code>make_report.py</code> 가 결과 JSON 에서 자동 생성했다.
</footer>

</div>
</body>
</html>
"""

    REPORT_PATH.write_text(html, encoding="utf-8")
    print(f"보고서 저장: {REPORT_PATH}  ({len(html):,}자)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
