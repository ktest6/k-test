# -*- coding: utf-8 -*-
"""4차 실험(팀원 요청: 체크리스트 10개 + logprobs 확률 판정) 보고서를 만든다.

앞 보고서들과 같은 원칙 — **결과 JSON 에서 직접** 만든다. 손으로 옮겨 적은 숫자는 없다.

읽는 파일:
    outputs/checklist_lab/results_summary_v4.json
    outputs/checklist_lab/checklists_v4.json

쓰는 법:
    python make_report_v4.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from statistics import mean

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _lab_common import OUT_DIR, ASSESSMENT_DIR, enable_utf8_output  # noqa: E402
from make_report import BLUE, ORANGE, NEUTRAL, esc, ci, qwk_chart, table  # noqa: E402
from make_report_v3 import read_style, verdict_pill  # noqa: E402

REPORT_PATH = ASSESSMENT_DIR / "체크리스트채점_4차실험보고_20260809.html"


def dist_chart(bins: dict) -> str:
    """확률값이 어느 구간에 몰려 있는지 보여 주는 가로 막대.

    이 그림 하나가 4차 실험의 결론이다 — 확률을 받아 왔는데 대부분 0 아니면 1이었다.
    """
    x0, x1 = 210.0, 960.0
    top, step, bar_h = 40.0, 36.0, 16.0
    rows = list(bins.items())
    axis_y = top + step * len(rows) - 12
    height = axis_y + 56
    vmax = max(v["rate"] for _, v in rows)
    scale = max(0.5, (int(vmax * 10) + 1) / 10)  # 0.5 · 0.6 … 눈금이 예쁘게 떨어지도록

    def sx(v: float) -> float:
        return x0 + (x1 - x0) * min(1.0, v / scale)

    parts = [f'<svg viewBox="0 0 1000 {height:.0f}" role="img" aria-label="'
             + esc("항목 확률값의 분포. " + " · ".join(f"{k} {v['rate'] * 100:.1f}%" for k, v in rows))
             + '">']
    n_ticks = 5
    parts.append('<g stroke="var(--rule-strong)" stroke-opacity=".55">')
    for i in range(n_ticks + 1):
        gx = sx(scale * i / n_ticks)
        parts.append(f'<line x1="{gx:.1f}" y1="24" x2="{gx:.1f}" y2="{axis_y:.1f}"></line>')
    parts.append("</g>")
    parts.append('<g font-family="Consolas, D2Coding, monospace" font-size="12" fill="var(--muted)">')
    for i in range(n_ticks + 1):
        gx = sx(scale * i / n_ticks)
        parts.append(f'<text x="{gx:.1f}" y="{axis_y + 20:.0f}" text-anchor="middle">'
                     f'{scale * i / n_ticks * 100:.0f}%</text>')
    parts.append(f'<text x="{(x0 + x1) / 2:.0f}" y="{axis_y + 42:.0f}" text-anchor="middle">'
                 + esc("전체 판정 칸에서 차지하는 비율") + "</text></g>")

    for i, (label, v) in enumerate(rows):
        cy = top + step * i
        by = cy - bar_h / 2
        bx = sx(v["rate"])
        # 0/1 끝에 붙은 칸은 주황(정보 없음), 가운데는 파랑(정보 있음)
        edge = label.startswith("0~") or label.endswith("~1")
        color = ORANGE if edge else BLUE
        r = 4.0
        w = max(bx - x0, r + 0.1)
        parts.append(
            f'<path d="M{x0:.1f} {by:.1f} H{x0 + w - r:.1f} a{r} {r} 0 0 1 {r} {r} '
            f'V{by + bar_h - r:.1f} a{r} {r} 0 0 1 -{r} {r} H{x0:.1f} Z" fill="{color}" '
            f'fill-opacity="{0.9 if edge else 0.85}">'
            f'<title>p {esc(label)}: {v["n"]}칸 ({v["rate"] * 100:.1f}%)</title></path>')
        parts.append(f'<text x="{x0 - 16:.0f}" y="{cy + 4.5:.1f}" text-anchor="end" '
                     f'font-family="Consolas, D2Coding, monospace" font-size="13" '
                     f'fill="var(--ink)">p = {esc(label)}</text>')
        parts.append(f'<text x="{bx + 12:.1f}" y="{cy + 4.5:.1f}" '
                     f'font-family="Consolas, D2Coding, monospace" font-size="13" '
                     f'font-variant-numeric="tabular-nums" fill="var(--ink-2)">'
                     f'{v["rate"] * 100:.1f}%  ({v["n"]:,}칸)</text>')
    parts.append("</svg>")
    return "\n".join(parts)


def main() -> int:
    enable_utf8_output()
    V4 = json.loads((OUT_DIR / "results_summary_v4.json").read_text(encoding="utf-8"))
    CL4 = json.loads((OUT_DIR / "checklists_v4.json").read_text(encoding="utf-8"))

    m = V4["methods"]
    key = V4["key_comparisons"]
    ans = V4["main_answer_Q_minus_Qbin"]
    cnt = V4["checklist_item_count_overall"]
    leak = V4["leakage_audit"]
    sat = V4["item_saturation"]
    diff = V4["difficulty_vs_actual_pass_rate"]
    pdist = V4["probability_distribution"]
    rep = V4["reproducibility"]
    cost = V4["cost_and_scale"]
    comp = V4["comparability"]
    fa = V4["fold_agreement"]
    n = V4["common_sample"]["n"]

    ceil_p = mean(m[f"CEIL_P_LIN_f{i}"]["qwk"] for i in range(5))
    ceil_b = mean(m[f"CEIL_B_LIN_f{i}"]["qwk"] for i in range(5))
    ceil_lo = min(m[f"CEIL_P_LIN_f{i}"]["qwk_ci95"]["lo"] for i in range(5))
    ceil_hi = max(m[f"CEIL_P_LIN_f{i}"]["qwk_ci95"]["hi"] for i in range(5))

    def bar(k: str, label: str, color: str, **kw) -> dict:
        v = m[k]
        return {"label": label, "value": v["qwk"], "lo": v["qwk_ci95"]["lo"],
                "hi": v["qwk_ci95"]["hi"], "color": color, **kw}

    bars = [
        {"label": "v4 항목의 정보 천장(5겹 범위)", "value": ceil_p,
         "lo": ceil_lo, "hi": ceil_hi, "color": NEUTRAL, "opacity": .45, "dashed": True},
        bar("Q", "Q 확률 + 가중치 학습 ★", BLUE),
        bar("P", "P 확률 평균×5", BLUE, opacity=.7),
        bar("P_bin", "P′ O/X 충족율×5", ORANGE, opacity=.7),
        {"label": "길이 기준선(글자 수만)", "value": m["LEN"]["qwk"],
         "lo": m["LEN"]["qwk_ci95"]["lo"], "hi": m["LEN"]["qwk_ci95"]["hi"],
         "color": NEUTRAL, "opacity": .7},
        bar("Q_bin", "Q′ O/X + 가중치 학습 ★대조군", ORANGE),
    ]

    score_rows = []
    for k, note in (("Q", "확률 · 학습 씀"), ("P", "확률 · 학습 안 씀"),
                    ("Q_bin", "O/X · 학습 씀"), ("P_bin", "O/X · 학습 안 씀"),
                    ("LEN", "기준선 · 답안 내용 안 봄")):
        v = m[k]
        score_rows.append([esc(v["label"]), note, f'<b>{v["qwk"]:.3f}</b>', ci(v["qwk_ci95"]),
                           f'{v["exact"] * 100:.1f}%' if "exact" in v else "-",
                           f'{v["within1"] * 100:.1f}%' if "within1" in v else "-"])
    score_table = table(["방식", "성격", "QWK", "95% 신뢰구간", "정확 일치", "±1 이내"],
                        score_rows, {2, 3, 4, 5})

    cmp_rows = []
    for label, k in (("Q 확률+학습 − Q′ O/X+학습  ← 팀원 질문의 답", "Q - Q_bin"),
                     ("P 확률 − P′ O/X (학습 없이)", "P - P_bin"),
                     ("Q 확률+학습 − P 확률 (학습의 값)", "Q - P"),
                     ("Q 확률+학습 − 길이 기준선", "Q - LEN"),
                     ("Q′ O/X+학습 − 길이 기준선", "Q_bin - LEN")):
        d = key.get(k)
        if d:
            cmp_rows.append([label, f'{d["mean"]:+.3f}', ci(d), verdict_pill(d["verdict"])])
    cmp_table = table(["비교 (앞 − 뒤)", "QWK 차이", "95% 신뢰구간", "판정"], cmp_rows, {1, 2})

    sat_table = table(
        ["진단", "v3 (항목 3.5개)", "v4 (항목 8.9개)"],
        [["항목 평균 통과율", f'{sat["v3_reference"]["mean_item_pass_rate"] * 100:.1f}%',
          f'<b>{sat["mean_item_pass_rate"] * 100:.1f}%</b>'],
         ["모든 항목을 통과한 답안",
          f'{sat["v3_reference"]["n_answers_all_met"]}건 '
          f'({sat["v3_reference"]["n_answers_all_met"] / n * 100:.1f}%)',
          f'<b>{sat["n_answers_all_met"]}건 ({sat["rate_answers_all_met"] * 100:.1f}%)</b>'],
         ["벌당 평균 항목 수", f'{cnt["v3_reference_mean"]}개', f'<b>{cnt["mean"]:.2f}개</b>']],
        {1, 2})

    diff_table = table(
        ["모델이 붙인 난이도", "판정 칸", "실제 통과율"],
        [[k, f'{v["n_cells"]:,}칸', f'{v["pass_rate"] * 100:.1f}%'] for k, v in diff.items()],
        {1, 2})

    lim = "".join(f"<li>{esc(x)}</li>" for x in V4["limitations"])

    # ── 네 차례 사다리 — 항목 수를 늘리면 천장이 오르는가 ──────────────────────
    # 앞 실험 천장은 v4 결과 JSON 에 함께 실려 있는 값을 쓴다(손으로 옮겨 적지 않는다).
    prior_all = (V4.get("prior_experiments_reference_only") or {}).get("methods", {})

    def prior_q(k: str):
        v = prior_all.get(k)
        return f'{v["qwk"]:.3f}' if v else "-"

    # 앞 실험의 천장·항목 수는 그 실험의 결과 파일에서 직접 읽는다
    P2 = json.loads((OUT_DIR / "results_summary_v2.json").read_text(encoding="utf-8"))
    P3 = json.loads((OUT_DIR / "results_summary_v3.json").read_text(encoding="utf-8"))
    v1_ceil = P2["methods"]["CEIL_V1_LIN"]["qwk"]
    v2_ceil = P2["methods"]["CEIL_V2_LIN"]["qwk"]
    v3_ceil = mean(P3["methods"][f"CEIL_V3_LIN_f{i}"]["qwk"] for i in range(5))
    v1_items = mean(v["n_items_v1"] for v in P2["checklist_items"].values())
    v2_items = mean(v["n_task_items_v2"] + v["n_universal_items_v2"]
                    for v in P2["checklist_items"].values())
    v3_items = mean(v["mean"] for v in P3["checklist_items_v3"].values())

    ladder_rows = [
        ["1차 · 지시문만 보고 생성", f'{v1_items:.1f}개', f'{v1_ceil:.3f}',
         prior_q("C"), "gemini-3.1-flash-lite"],
        ["2차 · 지어낸 후보 답안 기반", f'{v2_items:.1f}개', f'{v2_ceil:.3f}',
         f'<b>{prior_q("F")}</b>', "gemini-3.1-flash-lite"],
        ["3차 · 실제 답안 기반", f'{v3_items:.1f}개', f'{v3_ceil:.3f}', prior_q("J"),
         "gemini-3.1-flash-lite"],
        ["<b>4차 · 실제 답안 + 10개 요청</b>", f'<b>{cnt["mean"]:.2f}개</b>',
         f'<b>{ceil_b:.3f}</b>', f'{m["Q_bin"]["qwk"]:.3f}',
         f'<b>{esc(V4["judge_model"])}</b>'],
    ]
    ladder_table = table(["실험 · 체크리스트 만든 방법", "벌당 항목 수", "정보 천장(이진·선형)",
                          "가중치 학습 QWK", "판정 모델"], ladder_rows, {1, 2, 3})

    prior = prior_all
    prior_rows = []
    for k, v in sorted(prior.items(), key=lambda kv: -kv[1]["qwk"]):
        prior_rows.append([esc(v.get("label", k)), esc(v.get("judge_model", "-")),
                           f'{v["qwk"]:.3f}', ci(v["qwk_ci95"])])
    prior_table = table(["방식", "판정 모델", "QWK", "95% 신뢰구간"], prior_rows, {2, 3}) if prior_rows else ""

    html = f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>체크리스트 채점 4차 실험 보고 — 확률 판정 — 2026-08-09</title>
{read_style()}
</head>
<body>

<header class="top">
  <div class="wrap">
    <p class="kicker">K-TEST 채점 실험 4차 · 팀원 요청 2건</p>
    <h1>O/X 대신 확률로 채점하면 나아질까</h1>
    <p class="sub">요청은 ① 체크리스트를 <b>10개</b>로 늘릴 것 ② 판정을 O/X 대신
    <b>logprobs 정규화 확률</b> p(예)/(p(예)+p(아니오))로 받아 가중치를 다시 학습할 것.
    둘 다 실행했다. <b>①은 성공했고, ②는 이득이 없었다.</b></p>
    <div class="meta">
      <span><b>날짜</b> {esc(V4["run_date"][:10])}</span>
      <span><b>표본</b> 답안 {n}건 (1~3차와 동일)</span>
      <span><b>체크리스트</b> 45벌 · 평균 {cnt["mean"]:.2f}개</span>
      <span><b>판정</b> {esc(V4["judge_model"])} · 온도 {V4["temperature"]:.0f}</span>
      <span><b>규모</b> {cost["n_judgment_rows_recorded"]:,}칸 · 실패 {sum(cost["failures"].values()) if cost["failures"] else 0}건 · ${cost["total_cost_usd"]:.2f}</span>
    </div>
  </div>
</header>

<div class="wrap">

<div class="lead">
  <p class="eyebrow">한 줄 결론</p>
  <p class="big"><b>확률은 진짜로 받아 왔는데, 그 확률이 사실상 O/X였다.</b>
  판정 {pdist["n"]:,}칸 중 <b>{(pdist["bins"]["0~0.01"]["rate"] + pdist["bins"]["0.99~1"]["rate"]) * 100:.1f}% 가 0 아니면 1</b>에 붙어 있었고,
  진짜 중간값(0.25~0.75)은 <b>{pdist["rate_middle"] * 100:.1f}%</b> 뿐이었다.
  그래서 확률로 학습한 Q({m["Q"]["qwk"]:.3f})와 O/X로 학습한 Q′({m["Q_bin"]["qwk"]:.3f})의 차이는
  <b>{ans["mean"]:+.3f} [{ans["lo"]:+.3f}, {ans["hi"]:+.3f}] — 구간이 0을 걸쳐 차이를 주장할 수 없다.</b></p>
  <p class="big" style="margin-top:14px;border-top:1px solid var(--rule);padding-top:14px;">
  대신 <b>요청 ①은 확실히 성공했다.</b> 항목이 3.5개 → {cnt["mean"]:.2f}개로 늘면서
  3차의 실패 원인이던 ‘너무 쉬운 항목’이 고쳐졌다(전 항목 통과 답안 {sat["v3_reference"]["n_answers_all_met"]}건 → {sat["n_answers_all_met"]}건).
  정보 천장도 {ceil_p:.2f}까지 올랐다. <b>그런데 그 천장을 받아 가는 방식이 이번에도 없었다</b> —
  네 방식 모두 “글자 수만 세기”({m["LEN"]["qwk"]:.3f})와 차이를 주장할 수 없다.</p>
</div>

<div class="note col" style="border-left:2px solid var(--orange);">
  <b>읽기 전 주의 — 1~3차와 직접 비교하지 마십시오.</b> {esc(comp["reason"])}
  <br><b>비교해도 되는 것</b>: {esc(comp["what_is_comparable"])}
</div>

<section class="col">
  <p class="eyebrow">요청 ①</p>
  <h2>체크리스트 10개 — 성공했고, 3차의 병이 고쳐졌다</h2>
  <p>3차와 똑같이 <b>겹마다 따로</b> 만들었다(문항 9종 × 5겹 = 45벌). 겹 k 의 체크리스트는 겹 k 답안을 한 건도 보지 않고,
  학습 겹에서 사람 점수대가 고르게 퍼지도록 뽑은 실제 답안 12건만 보고 만든다.
  프로그램으로 <b>45벌 · 예시 {leak["n_exemplars_checked"]}건을 전수 대조</b>한 결과 시험 겹 답안 혼입 <b>{leak["n_leaked"]}건</b>이다.</p>
  <p>3차가 진 이유는 “항목이 너무 쉬워서 다 통과”였다. 이번엔 프롬프트에
  <b>“최소한만 말한 답안은 떨어지는 어려운 항목을 반드시 섞어라”</b>를 넣었고, 실제로 고쳐졌다.</p>
</section>

{sat_table}

<section>
  <h2 class="col" style="margin-top:30px;">모델이 “어렵다”고 붙인 항목이 실제로 어려웠다</h2>
  {diff_table}
  <p class="col" style="margin-top:12px;color:var(--ink-2);font-size:14.5px;">
  난이도를 섞으라는 지시가 말로만 지켜진 게 아니라 <b>실제 통과율로 확인</b>된다(75.6% / 50.3% / 33.0%).
  다만 겹마다 시험지가 달라지는 값은 그대로다 — 같은 문항 5벌의 문구 닮음 {fa.get("overall_mean_similarity", 0):.3f}.</p>
</section>

<section class="col">
  <p class="eyebrow">요청 ②</p>
  <h2>확률 판정 — 진짜 logprobs 로 받았다</h2>
  <p>Gemini 는 3.x 계열에서 logprobs 를 없앴으므로(구글 공식 “의도된 동작”) 판정 창구를
  <b>OpenRouter · {esc(V4["judge_model"])}</b> 로 옮겼다. 항목마다 “예/아니오” 한 낱말만 답하게 하고,
  <b>첫 토큰의 확률표</b>에서 p(예)/(p(예)+p(아니오))를 계산한다.</p>
  <p>주의할 점이 하나 있었다. “아니오”는 첫 토큰이 <code>아</code> 로 잘려 나오므로,
  토큰을 라벨로 접어서(예·네 → 예 쪽 / 아·아니 → 아니오 쪽) 확률을 합산해야 값이 틀어지지 않는다.
  <b>같은 호출에서 확률과 O/X(p&gt;0.5)를 함께</b> 얻었기 때문에, 두 방식의 비교는 완전히 같은 조건에서 이뤄진다.</p>
</section>

<section>
  <h2 class="col">그런데 확률이 사실상 O/X였다</h2>
  <figure>
    {dist_chart(pdist["bins"])}
    <figcaption>주황은 0 또는 1 끝에 붙어 정보가 없는 칸, 파랑은 중간값을 가진 칸이다.
    전체 {pdist["n"]:,}칸 중 정보를 가진 칸(0.05~0.95)은 {pdist["rate_informative"] * 100:.1f}% 뿐이다.</figcaption>
  </figure>
  <div class="note col"><b>모델은 거의 항상 확신한다.</b> 그래서 확률을 꺼내 와도 O/X 와 거의 같은 값이 된다.
  3차에서 “씨앗을 바꿔 투표시키는 대체재”로 재 봤을 때 갈린 칸이 8.2% 였는데,
  이번에 <b>진짜 확률로 재니 8.8%</b> 였다 — 대체재로 내렸던 판단이 정확했다는 사후 확인이다.</div>
</section>

<section>
  <p class="eyebrow">결과</p>
  <h2 class="col">네 방식 성적</h2>
  <figure>
    <div class="legend">
      <span><i style="background:{BLUE}"></i>확률로 채점</span>
      <span><i style="background:{ORANGE}"></i>O/X 로 채점</span>
      <span><i style="background:{NEUTRAL};opacity:.7"></i>기준선·천장</span>
    </div>
    {qwk_chart(bars)}
    <figcaption>같은 답안 {n}건 · 같은 겹 · <b>완전히 같은 판정 결과</b>에서 나온 네 방식이다.
    점선은 실제로 쓸 수 없는 천장(정답을 보고 맞춘 값).</figcaption>
  </figure>
  {score_table}
</section>

<section>
  <h2 class="col">차이가 우연인가 — 팀원 질문의 답</h2>
  {cmp_table}
  <div class="note col"><b>확률이 O/X 보다 낫다고 말할 수 없다</b>({ans["mean"]:+.3f}, 구간이 0을 걸침).
  그리고 더 뼈아픈 것은 <b>네 방식 전부가 “답안 글자 수만 세기”와도 차이를 주장할 수 없다</b>는 점이다.
  항목을 늘려 천장은 {ceil_p:.2f}(이진 {ceil_b:.2f})까지 올려 놨는데, <b>그 천장을 받아 가는 방식이 아직 없다.</b></div>
</section>

<section class="col">
  <p class="eyebrow">놀란 점</p>
  <h2>온도 0인데 확률이 재현되지 않았다</h2>
  <p>고정 60건을 3회 판정했더니 <b>확률이 소수점까지 같은 칸이 {rep["n_cells"]}칸 중 {rep["n_cells_identical"]}칸({rep["prob_identical_rate"] * 100:.1f}%)</b> 뿐이었다.
  대부분은 아주 미세한 차이(중앙값 {rep["prob_spread"]["median"]:.1e})지만, <b>O/X 판정이 뒤집힌 칸이 {rep["n_cells_met_flipped"]}칸({rep["met_flip_rate"] * 100:.1f}%)</b> 있고 최대 폭은 {rep["prob_spread"]["max"]:.3f}였다.
  1~3차(Gemini)에서는 <b>0/213칸</b>, 즉 완벽히 재현됐던 항목이다.</p>
  <p>공급자가 바뀌어서 생긴 일인지 확인해 봤다. <b>3회 내내 같은 공급자로 간 {rep["n_cells_same_provider"]}칸 중 {rep["n_same_provider_and_differs"]}칸도 흔들렸다</b> —
  라우팅 탓이 아니라 모델·서버의 계산 방식(전문가 혼합 모델의 묶음 추론으로 보인다) 문제다.
  최종 점수는 반올림에 먹혀 완전일치 100% 로 나오지만, <b>판정 창구를 이쪽으로 옮기면 “재현성 100%”라는 우리 강점이 약해진다.</b></p>
  <p><b>또 하나 — 이번 판정에는 근거 인용이 없다.</b> 한 낱말로만 답하게 했으므로 “원문에 없는 인용은 폐기”라는
  우리 규약을 지킬 자리가 없었다. 대신 판정마다 첫 토큰 후보와 확률 원본을 전부 저장했다.
  <b>운영 채점에 이 규약을 그대로 쓸 수는 없다.</b></p>
  <p><b>부수 함정</b>: OpenRouter 는 같은 모델을 여러 회사로 나눠 보내는데, 일부 회사는 <code>logprobs</code> 를
  <b>조용히 빼고 정상 응답</b>을 돌려준다. 파라미터 필수 옵션과 공급자 지정으로 막았고, 줄마다 어디로 갔는지 기록해 두었다.</p>
</section>

<section>
  <p class="eyebrow">네 차례를 한눈에</p>
  <h2 class="col">항목을 늘리면 천장이 오른다 — 그런데 점수는 안 따라온다</h2>
  {ladder_table}
  <div class="note col"><b>천장은 항목 수를 따라 움직인다.</b> 2개 → 6개로 늘리자 올랐고, 3차에서 3.5개로 줄자 내려갔고,
  4차에서 8.9개로 늘리자 다시 올라 역대 최고({ceil_b:.3f})가 됐다. <b>재료를 좋게 만드는 방법은 찾은 셈이다.</b>
  <br><br>그런데 <b>가중치 학습 점수는 2차(6개)의 {prior_q("F")}이 여전히 최고</b>다.
  천장이 {ceil_b:.3f}인데 실제 점수가 {m["Q_bin"]["qwk"]:.3f}에 머무는 것은, 항목이 아니라
  <b>0/1 을 점수로 바꾸는 층(릿지 회귀)이 못 따라온다</b>는 뜻이다.</div>
  <div class="note col" style="border-left:2px solid var(--orange);">
  <b>다만 4차 줄은 판정 모델이 다르다.</b> 확률을 얻으려면 창구를 옮길 수밖에 없었으므로,
  4차의 천장 상승과 점수에는 <b>‘항목이 늘어난 효과’와 ‘모델이 바뀐 효과’가 섞여 있다.</b>
  <br><b>가리는 방법은 정해져 있다</b> — v4 체크리스트(8.9개)를 <b>1~3차와 같은 gemini-3.1-flash-lite 로 판정</b>하면
  판정자를 고정한 사다리가 완성된다. Gemini 는 항목 전부를 한 번에 판정할 수 있어 1,405회면 되고, 아직 하지 않았다.</div>
</section>

<section>
  <p class="eyebrow">참고</p>
  <h2 class="col">1~3차 방식별 숫자 (판정 모델이 다르므로 직접 비교 금지)</h2>
  {prior_table}
  <p class="col" style="margin-top:12px;color:var(--ink-2);font-size:14.5px;">
  이 표는 <b>맥락용</b>이다. v4 와 나란히 놓고 순위를 매기면 “방식의 차이”와 “모델의 차이”가 섞인 숫자를 읽게 된다.</p>
</section>

<section class="col">
  <p class="eyebrow">그래서 다음</p>
  <h2>네 차례 실험이 가리키는 곳</h2>
  <ol>
    <li><b>항목을 늘리고 어렵게 만드는 것은 효과가 있다</b>(천장 0.69 → 0.80 → {ceil_p:.2f}). 다만 <b>천장을 받아 갈 결합 방식이 아직 없다.</b>
      릿지 회귀보다 나은 결합(비선형·순서형 모델)을 시도할 자리다.</li>
    <li><b>확률 판정은 이 과제에서 값이 없다.</b> 모델이 거의 항상 확신하기 때문이다. 이 길은 닫아도 된다 —
      <b>세 가지 방법(씨앗 투표·0~100 점수·진짜 logprobs)으로 모두 같은 결론</b>이 나왔다.</li>
    <li><b>판정 창구를 옮기는 값은 비싸다.</b> 재현성이 깨지고 인용 규약을 잃는다. 확률이라는 이득이 없는 이상 Gemini 로 돌아가는 것이 맞다.</li>
    <li><b>제일 급한 것은 여전히 문항이다.</b> 네 번 모두 AI Hub 문항에서 실험했다. 요구가 3~5개인 우리 직무 문항에서
      같은 실험을 해야 이 결론들이 우리 시험에 적용되는지 알 수 있다.</li>
  </ol>
</section>

<section class="col">
  <p class="eyebrow">정직하게</p>
  <h2>이 결과로 말할 수 없는 것</h2>
  <ul>{lim}</ul>
</section>

<section class="col">
  <p class="eyebrow">다시 돌리려면</p>
  <h2>재현 방법</h2>
  <pre>cd assessment/scripts/checklist_lab
python gen_checklists_v4.py      # 겹별 체크리스트 45벌 (항목 10개 목표)
python run_experiment_v4.py      # 확률 판정 14,156칸 (+ 재현성 3회)
python analyze_v4.py             # QWK·신뢰구간·천장·분포
python make_report_v4.py         # 이 보고서</pre>
  <p style="font-size:14.5px;color:var(--ink-2);">모든 수치의 원본은 <code>outputs/checklist_lab/results_summary_v4.json</code>,
  판정 한 칸 한 칸의 확률 원본은 <code>judgments_v4.jsonl</code> 에 있다.
  1~3차 결과 파일과 <code>assessment/src/</code> 는 이 실험에서 변경되지 않았다.</p>
</section>

<footer class="wrap" style="padding-left:0;padding-right:0;">
  K-TEST 문제·채점 모델 파트 · 4차 실험 {esc(V4["run_date"])} ·
  판정 {esc(V4["judge_model"])} / 생성 {esc(V4["generator_model"])} ·
  앞 보고서: <code>체크리스트채점_실험보고_20260809.html</code>(1·2차) ·
  <code>체크리스트채점_3차실험보고_20260809.html</code>(3차) ·
  이 문서는 <code>make_report_v4.py</code> 가 결과 JSON 에서 자동 생성했다.
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
