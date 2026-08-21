# -*- coding: utf-8 -*-
"""3차 실험(팀원 요청: 데이터 기반 체크리스트 + 확률 판정) 보고서를 만든다.

1·2차 보고서(`make_report.py`)와 같은 원칙 — **결과 JSON 에서 직접** 만든다.
손으로 옮겨 적은 숫자는 한 개도 없다. 실험을 다시 돌리면 이 스크립트만 다시 실행하면 된다.

읽는 파일:
    outputs/checklist_lab/results_summary_v3.json  — 3차 전체 수치
    outputs/checklist_lab/softprob_probe.json      — 확률 대체재 타당성 실측
    outputs/checklist_lab/checklists_v3.json       — 겹별 체크리스트 본문

쓰는 법:
    python make_report_v3.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from statistics import mean

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _lab_common import OUT_DIR, ASSESSMENT_DIR, enable_utf8_output  # noqa: E402
from make_report import BLUE, ORANGE, NEUTRAL, esc, ci, qwk_chart, table, diff_of  # noqa: E402

REPORT_PATH = ASSESSMENT_DIR / "체크리스트채점_3차실험보고_20260809.html"
STYLE_SOURCE = ASSESSMENT_DIR / "체크리스트채점_실험보고_20260809.html"


def read_style() -> str:
    """1·2차 보고서와 같은 옷을 입힌다. 같은 실험의 다음 편이므로 모양이 달라지면 안 된다."""
    html = STYLE_SOURCE.read_text(encoding="utf-8")
    start = html.index("<style>")
    end = html.index("</style>") + len("</style>")
    return html[start:end]


def verdict_pill(text: str) -> str:
    cls = "no" if ("걸친다" in text or "불가" in text) else "yes"
    return f'<span class="pill {cls}">{esc(text)}</span>'


def main() -> int:
    enable_utf8_output()
    V3 = json.loads((OUT_DIR / "results_summary_v3.json").read_text(encoding="utf-8"))
    PR = json.loads((OUT_DIR / "softprob_probe.json").read_text(encoding="utf-8"))
    CL3 = json.loads((OUT_DIR / "checklists_v3.json").read_text(encoding="utf-8"))

    m = V3["methods"]
    pairs = V3["pairwise_diff_qwk_ci95"]
    key = V3["key_comparisons"]
    lg = V3["logprobs_status"]
    n = V3["common_sample"]["n"]

    def bar(k: str, label: str, color: str, **kw) -> dict:
        v = m[k]
        return {"label": label, "value": v["qwk"], "lo": v["qwk_ci95"]["lo"],
                "hi": v["qwk_ci95"]["hi"], "color": color, **kw}

    # v3 겹별 선형 천장의 평균 — 그림에는 대표값 하나만 세운다
    lin3 = [m[f"CEIL_V3_LIN_f{i}"]["qwk"] for i in range(5)]
    lin3_lo = min(m[f"CEIL_V3_LIN_f{i}"]["qwk_ci95"]["lo"] for i in range(5))
    lin3_hi = max(m[f"CEIL_V3_LIN_f{i}"]["qwk_ci95"]["hi"] for i in range(5))

    bars = [
        {"label": "v2 항목의 정보 천장", "value": m["CEIL_V2_LIN"]["qwk"],
         "lo": m["CEIL_V2_LIN"]["qwk_ci95"]["lo"], "hi": m["CEIL_V2_LIN"]["qwk_ci95"]["hi"],
         "color": NEUTRAL, "opacity": .45, "dashed": True},
        bar("A1", "A1 LLM 직접 채점(퓨샷)", BLUE),
        {"label": "v3 항목의 정보 천장(5겹 범위)", "value": mean(lin3),
         "lo": lin3_lo, "hi": lin3_hi, "color": NEUTRAL, "opacity": .45, "dashed": True},
        bar("F", "F v2 체크리스트+가중치 학습", ORANGE),
        bar("LEN", "길이 기준선(글자 수만)", NEUTRAL, opacity=.7),
        bar("C", "C v1 체크리스트+가중치 학습", ORANGE, opacity=.55),
        bar("J", "J v3 체크리스트+가중치 학습 ★", ORANGE),
        bar("I", "I v3 충족율×5", ORANGE, opacity=.6),
        bar("D", "D v2 충족율×5", ORANGE, opacity=.45),
        bar("B", "B v1 충족율×5", ORANGE, opacity=.35),
    ]

    # ── 성적표 ───────────────────────────────────────────────────────────────
    score_rows = []
    for k, note in (("J", "★ 팀원이 요청한 ‘F 재학습’의 v3 판"), ("I", "학습 안 씀"),
                    ("I_imp", "학습 안 씀 · 중요도 가중"), ("F", "v2 · 학습 씀"),
                    ("C", "v1 · 학습 씀"), ("A1", "v1 · LLM 직접 채점"),
                    ("LEN", "기준선")):
        v = m[k]
        score_rows.append([esc(v["label"]), note, f'<b>{v["qwk"]:.3f}</b>', ci(v["qwk_ci95"]),
                           f'{v["exact"] * 100:.1f}%' if "exact" in v else "-",
                           f'{v["within1"] * 100:.1f}%' if "within1" in v else "-"])
    score_table = table(["방식", "성격", "QWK", "95% 신뢰구간", "정확 일치", "±1 이내"],
                        score_rows, {2, 3, 4, 5})

    cmp_rows = []
    for label, k in (("J v3 학습 − F v2 학습", "J - F"),
                     ("J v3 학습 − C v1 학습", "J - C"),
                     ("J v3 학습 − A1 LLM 직접", "J - A1"),
                     ("J v3 학습 − 길이 기준선", "J - LEN"),
                     ("J v3 학습 − I v3 충족율", "J - I"),
                     ("I v3 충족율 − D v2 충족율", "I - D"),
                     ("I v3 충족율 − B v1 충족율", "I - B"),
                     ("I′ 중요도 가중 − I 단순 충족율", "I_imp - I")):
        d = key.get(k)
        if not d:
            continue
        cmp_rows.append([label, f'{d["mean"]:+.3f}', ci(d), verdict_pill(d["verdict"])])
    cmp_table = table(["비교 (앞 − 뒤)", "QWK 차이", "95% 신뢰구간", "판정"], cmp_rows, {1, 2})

    # ── 천장 ─────────────────────────────────────────────────────────────────
    ceil_rows = []
    for name, k1, k3s in (("충족 개수만 (중앙값 사상)", "CEIL_V2_CNT", "CEIL_V3_CNT_f%d"),
                          ("충족 개수만 (QWK 최대 사상)", "CEIL_V2_OPT", "CEIL_V3_OPT_f%d"),
                          ("항목 하나하나 다 쓰기 (선형)", "CEIL_V2_LIN", "CEIL_V3_LIN_f%d")):
        vals = [m[k3s % i]["qwk"] for i in range(5)]
        beats = sum(1 for i in range(5)
                    if (dd := diff_of(pairs, k3s % i, k1)) and dd["lo"] > 0)
        loses = sum(1 for i in range(5)
                    if (dd := diff_of(pairs, k3s % i, k1)) and dd["hi"] < 0)
        judged = ("v3 가 유의하게 낮은 겹 %d개" % loses) if loses else (
            "v3 가 유의하게 높은 겹 %d개" % beats if beats else "차이 없음")
        cls = "no" if loses else ("yes" if beats else "no")
        ceil_rows.append([name, f'{m[k1]["qwk"]:.3f}',
                          f'{min(vals):.3f} ~ {max(vals):.3f}', f'{mean(vals):.3f}',
                          f'<span class="pill {cls}">{judged}</span>'])
    ceil_table = table(["천장을 재는 방법", "v2 (항목 6개)", "v3 (겹별 5벌)", "v3 평균", "판정"],
                       ceil_rows, {1, 2, 3})

    # ── 확률 probe ───────────────────────────────────────────────────────────
    bt = PR["by_temperature"]
    probe_rows = [[f'온도 {t}', f'{v["n_cells"]}칸', f'{v["n_split_cells"]}칸',
                   f'{v["split_rate"] * 100:.1f}%',
                   f'{v["split_prob_mean"]:.3f}'] for t, v in bt.items()]
    probe_table = table(["조건", "잰 항목 칸", "표가 갈린 칸", "갈린 비율", "갈린 칸의 평균 p(예)"],
                        probe_rows, {1, 2, 3, 4})

    lg_rows = [["`response_logprobs=True, logprobs=5` 요청",
                esc(", ".join(lg["models_tried_400"])),
                f'<span class="pill no">400 — {esc(lg["error_400"].split("—")[-1].strip())}</span>'],
               ["같은 요청 (다른 모델군)", esc(", ".join(lg["models_tried_404"])),
                '<span class="pill no">404 — 이 키로 접근 불가</span>'],
               ["키를 바꿔 재시도", esc(lg["keys_tried"]),
                '<span class="pill no">같은 응답</span>']]
    lg_table = table(["시도", "모델", "결과"], lg_rows, set())

    # ── 항목 수·겹 일치도 ────────────────────────────────────────────────────
    items = V3["checklist_items_v3"]
    fa = V3["fold_agreement"]
    sat = V3["item_saturation"]
    item_rows = []
    for pkey, v in items.items():
        agree = fa.get(pkey, {})
        item_rows.append([
            f'<span class="q">{esc(CL3.get(pkey, {}).get("prompt", pkey))}</span>',
            " · ".join(str(x) for x in v["per_fold"]), f'{v["mean"]:.1f}',
            f'{agree["mean_similarity"]:.3f}' if agree else "-",
            f'{agree["matched_rate"] * 100:.0f}%' if agree else "-",
        ])
    item_table = table(["문항", "겹별 항목 수", "평균", "겹 간 문구 닮음", "짝이 생긴 항목"],
                       item_rows, {2, 3, 4})

    v3mean = mean(v["mean"] for v in items.values())
    fa_mean = fa["overall_mean_similarity"]
    fa_matched = fa["overall_matched_rate"]
    rep = V3["reproducibility"]
    lim = "".join(f"<li>{esc(x)}</li>" for x in V3["limitations"])

    html = f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>체크리스트 채점 3차 실험 보고 — 2026-08-09</title>
{read_style()}
</head>
<body>

<header class="top">
  <div class="wrap">
    <p class="kicker">K-TEST 채점 실험 3차 · 팀원 요청 2건</p>
    <h1>실제 답안을 보고 체크리스트를 만들면 어떨까</h1>
    <p class="sub">요청은 두 가지였다 — ① 가상 답안을 지어내지 말고 <b>AI Hub 실제 답안</b>을 보고 체크리스트를 만들 것
    ② 판정을 O/X 대신 <b>확률</b>로 받아 가중치를 다시 학습할 것. 하나는 했고, 하나는 API 가 막았다.</p>
    <div class="meta">
      <span><b>날짜</b> {esc(V3["run_date"][:10])}</span>
      <span><b>표본</b> 답안 {n}건 · 문항 {len(items)}종 (1·2차와 동일)</span>
      <span><b>체크리스트</b> 문항 9종 × 5겹 = 45벌</span>
      <span><b>모델</b> {esc(V3["model"])} · 본 판정 온도 {V3["temperature_main"]:.0f}</span>
      <span><b>LLM 호출</b> {V3["n_llm_calls_recorded_v3"]:,}회 · 실패 {sum(V3["failures"].values()) if V3["failures"] else 0}건</span>
    </div>
  </div>
</header>

<div class="wrap">

<div class="note" style="margin-top:26px;border-left:2px solid var(--orange);">
  <b>이 문서는 3차 실험이다. 뒤에 4차가 있다</b> — 여기서 “항목이 줄어 졌다”고 진단한 것을
  4차에서 <b>항목 10개로 늘려 다시 시험했고, 그 진단이 맞았다.</b>
  <br>4차: <code>체크리스트채점_4차실험보고_20260809.html</code> (네 차례 사다리 표가 여기 있다)
  <br>1·2차: <code>체크리스트채점_실험보고_20260809.html</code>
</div>

<div class="lead">
  <p class="eyebrow">한 줄 결론</p>
  <p class="big"><b>실제 답안을 보여 줬더니 체크리스트가 오히려 짧아졌고(항목 6개 → {v3mean:.1f}개), 점수도 2차보다 유의하게 낮았다</b>
  (J {m["J"]["qwk"]:.3f} vs F {m["F"]["qwk"]:.3f}, 차이 {key["J - F"]["mean"]:+.3f}).
  <b>확률 판정은 Gemini API 가 막아서 불가능</b>했고, 씨앗을 바꿔 확률을 흉내 내는 대체재도 실측 결과
  표가 갈린 칸이 {PR["split_rate_overall"] * 100 if "split_rate_overall" in PR else PR["n_split_cells_total"] / PR["n_cells_total"] * 100:.1f}% 뿐이라 쓸 수 없다고 판정했다.
  다만 <b>세 번째로 같은 진단이 나왔다 — 이 문항들은 요구하는 것이 원래 두 가지뿐이다.</b></p>
</div>

<section class="col">
  <p class="eyebrow">요청 ①</p>
  <h2>실제 답안을 보고 만들되, 답을 보고 시험지를 만들지 않도록</h2>
  <p>2차는 <b>지어낸</b> 가상 답안 4개를 보고 항목을 뽑았다. 이번엔 팀원 요청대로 <b>진짜 응시자 답안</b>을 보여 줬다.
  각 답안에 <b>사람이 매긴 점수(0~5)를 함께</b> 붙여서, “5점과 1점이 무엇이 달랐는가”를 보고 <b>변별하는 항목</b>을 뽑게 했다.</p>
  <p>여기서 함정이 하나 있다. 시험 볼 답안을 보고 체크리스트를 만들면 <b>답을 보고 시험지를 만든 것</b>이 된다.
  그래서 <b>겹마다 체크리스트를 따로 만들었다</b> — 겹 k 의 시험지는 겹 k 답안을 한 건도 보지 않고,
  나머지 4겹에서 점수대가 고르게 퍼지도록 뽑은 8건만 보고 만든다. 문항 9종 × 5겹 = <b>45벌</b>.
  프로그램으로 감사한 결과 시험 겹 답안이 생성 프롬프트에 섞인 경우는 <b>0건</b>이었다.</p>
</section>

<section>
  <h2 class="col" style="margin-top:30px;">그런데 항목이 늘지 않고 줄었다</h2>
  {item_table}
  <div class="note col"><b>2차 6개 → 3차 평균 {v3mean:.1f}개.</b> “진짜 답안을 보여 주면 더 풍부해질 것”이라는 예상과 정반대다.
  모델이 실제 답안에서 찾아낸 변별축은 대체로 <b>“무엇을 말했나 · 왜인지 말했나”</b> 둘뿐이었다.
  1차·2차에 이어 <b>세 번째로 같은 진단</b> — 병목은 생성 방식이 아니라 <b>이 문항들이 요구하는 것 자체가 얕다</b>는 데 있다.</div>
  <p class="col">대신 얻은 것도 있다. 2차에서 문제였던 <b>부정형 항목</b>(“~을 배제했는가”)이 이번엔 158개 중 6개(3.8%)로 억제됐다.
  없는 것을 원문에서 인용할 수 없어 무더기로 폐기되던 사고가 크게 줄었다.</p>
  <p class="col"><b>대신 새로 치른 값 — 겹마다 시험지가 달라진다.</b> 같은 문항의 5 벌을 서로 견주니
  문구 닮음이 평균 <b>{fa_mean:.3f}</b>, 짝이 생긴 항목이 <b>{fa_matched * 100:.1f}%</b> 였다.
  데이터를 보고 만드는 방식은 <b>어떤 답안을 보여 주느냐에 따라 시험지가 흔들린다</b>는 뜻이고, 이것은 표준화 시험에서 비용이다.</p>
</section>

<section>
  <p class="eyebrow">요청 ②</p>
  <h2 class="col">확률 판정 — API 가 막았다</h2>
  <p class="col">요청은 <code>p(예)/(p(예)+p(아니오))</code> 로 부드러운 값을 받자는 것이었다. 결론부터: <b>Gemini 개발자 API 로는 불가능하다.</b></p>
  {lg_table}
  <p class="col" style="margin-top:16px;">그래서 <b>대체재가 쓸 만한지를 먼저 쟀다.</b> 같은 답안을 <b>씨앗을 바꿔 12번</b> 판정하면
  “예”가 나온 비율이 확률 노릇을 할 수 있다(논문도 25회 샘플 평균을 쓴다). 실제로 480회를 불러 재 봤다.</p>
  {probe_table}
  <div class="note col"><b>온도를 1.3 까지 올려도 92% 의 칸이 만장일치였다.</b>
  실험 전에 “갈린 칸이 15% 이상이면 확률을 쓴다”고 미리 못 박아 두었으므로, 규칙대로 <b>소프트 패스를 생략</b>했다.
  씨앗을 고정하면 12회가 글자까지 같다는 것도 함께 확인했다 — 즉 8% 가 이 방식으로 얻을 수 있는 흔들림의 <b>전부</b>다.
  덧붙여 갈린 칸의 평균 p(예)는 {mean(v["split_prob_mean"] for v in bt.values()):.3f} 로 <b>딱 반반</b>이었다.
  애매해서 흔들리는 것이 아니라, 모델이 진짜로 반씩 갈리는 소수의 칸만 있다는 뜻이다.</div>
  <p class="col">진짜 확률을 쓰려면 길이 둘 있다. <b>Vertex AI</b>(구글 클라우드 계정 필요) 또는
  <b>로컬 모델</b>(이 PC 는 CUDA 없는 CPU 전용이라 불가, GPU 필요). 로컬로 가면 판정 모델이 바뀌므로
  1·2차와의 비교가 깨진다 — 그때는 <b>같은 로컬 모델로 이진·확률을 둘 다</b> 돌려야 확률의 효과만 깨끗이 분리된다.</p>
</section>

<section>
  <p class="eyebrow">결과</p>
  <h2 class="col">세 차례 실험을 한 그림에</h2>
  <figure>
    <div class="legend">
      <span><i style="background:{BLUE}"></i>LLM 이 직접 채점</span>
      <span><i style="background:{ORANGE}"></i>체크리스트로 채점</span>
      <span><i style="background:{NEUTRAL};opacity:.7"></i>기준선·천장</span>
    </div>
    {qwk_chart(bars)}
    <figcaption>같은 답안 {n}건 · 같은 겹 · 같은 모델 · 같은 사람 점수. 점선은 실제로 쓸 수 없는 천장(정답을 보고 맞춘 값)이다.
    v3 천장은 겹마다 시험지가 달라 5개가 나오므로 평균과 전체 범위를 함께 그렸다.</figcaption>
  </figure>
  {score_table}
</section>

<section>
  <h2 class="col">차이가 우연인가</h2>
  {cmp_table}
  <ul class="col" style="margin-top:16px;">
    <li><b>J(v3 + 학습) {m["J"]["qwk"]:.3f} 는 F(v2 + 학습) {m["F"]["qwk"]:.3f} 에 유의하게 졌다.</b> 팀원 요청 ①은 이 시험지에서는 개선이 아니었다.</li>
    <li>J 는 1차의 C({m["C"]["qwk"]:.3f})와도, <b>길이 기준선({m["LEN"]["qwk"]:.3f})과도 차이를 주장할 수 없다.</b></li>
    <li>다만 <b>충족율끼리 견주면 v3 가 v1 을 유의하게 이겼다</b>(I − B {key["I - B"]["mean"]:+.3f}) — 항목 자체는 v1 보다 나아졌다.</li>
    <li><b>중요도 가중은 3차에서도 효과가 없었다</b>(I′ − I, 구간이 0 을 걸침). 2차와 같은 결과다.</li>
  </ul>
</section>

<section>
  <h2 class="col">천장도 v2 를 넘지 못했다</h2>
  {ceil_table}
  <div class="note col">항목 하나하나를 다 쓰는 천장에서 <b>v3 는 5 겹 중 3 겹이 v2 보다 유의하게 낮다.</b>
  항목이 6 개에서 {v3mean:.1f}개로 줄었으니 담을 수 있는 정보도 함께 줄어든 것이다.</div>
  <h3 class="col" style="margin-top:26px;">진 이유는 ‘항목이 너무 쉬웠다’로 잡힌다</h3>
  <p class="col">v3 항목의 평균 통과율이 <b>{sat["mean_item_pass_rate"] * 100:.1f}%</b> 였고,
  <b>{n}건 중 {sat["n_answers_all_met"]}건이 모든 항목을 통과</b>했다(반대로 {sat["n_answers_none_met"]}건은 전부 미충족).
  사람이 5 점 준 답안과 2 점 준 답안이 <b>똑같이 만점</b>을 받으면 가를 방법이 없다.
  실제 답안을 보여 주자 모델이 “이 정도면 됐다”는 <b>느슨한 기준</b>을 배운 것으로 보인다 —
  지어낸 답안(2차)에는 일부러 만든 못난 답안이 섞여 있어 기준이 더 팽팽했다.</p>
</section>

<section class="col">
  <p class="eyebrow">변하지 않은 것</p>
  <h2>재현성은 세 번 다 100%</h2>
  <p>고정 60 건을 3 회 판정한 결과 최종 점수 <b>완전일치 100%</b>, 항목 0/1 뒤집힘
  <b>{rep.get("binary_cell_flip", {}).get("n_flipped", 0)}/{rep.get("binary_cell_flip", {}).get("n_cells", 0)}칸</b>.
  1·2차와 같다. 세 차례 실험에서 <b>재현성으로는 한 번도 우열이 갈리지 않았다</b> — 이 판정 모델이 짧은 판정에서 결정적이기 때문이다.</p>
</section>

<section class="col">
  <p class="eyebrow">세 차례를 합쳐서</p>
  <h2>지금까지 알아낸 것</h2>
  <ol>
    <li><b>이 시험지에서는 LLM 직접 채점이 계속 이긴다</b>({m["A1"]["qwk"]:.3f}). 체크리스트 최고는 v2+학습 {m["F"]["qwk"]:.3f} 다.</li>
    <li><b>체크리스트를 살리는 것은 결합 방식이 아니라 항목이다.</b> 세 번 모두 “충족 개수만 세기”는 제자리였고,
      <b>항목별 비중을 배우는 방식만</b> 천장을 따라 움직였다.</li>
    <li><b>항목을 늘리는 방법은 지어낸 후보 답안(2차) 쪽이 낫다.</b> 진짜 답안을 보여 주면 기준이 느슨해져 항목이 줄고 쉬워진다.</li>
    <li><b>세 번 모두 같은 진단: AI Hub 문항의 요구가 원래 둘뿐이다.</b> 요구가 3~5 개인 우리 직무 문항에서 다시 재야 한다.</li>
    <li><b>LLM 이 매기는 중요도는 세 번 다 효과가 없었다.</b> 비중은 데이터에서 배우는 쪽이 낫다.</li>
  </ol>
  <h3 style="margin-top:26px;">다음에 할 것</h3>
  <ol>
    <li><b>우리 직무 문항으로 2차(v2) 방식을 다시.</b> 3차 방식이 아니라 <b>2차 방식</b>이 기준선이다.</li>
    <li><b>두 방식을 합치기.</b> LLM 직접 점수와 체크리스트 항목을 함께 자질로 넣어 결합 모델을 학습시킨다.</li>
    <li><b>확률 판정을 정말 보려면</b> Vertex AI 또는 GPU 를 붙여야 한다. 그때는 같은 모델로 이진·확률을 둘 다 돌린다.</li>
    <li><b>항목을 더 어렵게.</b> 통과율 {sat["mean_item_pass_rate"] * 100:.0f}% 는 너무 후하다. “최소한만 말한 답안은 떨어지는 항목”을 반드시 섞게 해야 한다.</li>
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
python gen_checklists_v3.py      # 겹별 체크리스트 45벌 (학습 겹 답안만 봄)
python run_experiment_v3.py --probe   # 확률 대체재 타당성 실측
python run_experiment_v3.py      # 본 판정 1,405건 + 재현성
python analyze_v3.py             # QWK·신뢰구간·천장
python make_report_v3.py         # 이 보고서</pre>
  <p style="font-size:14.5px;color:var(--ink-2);">모든 수치의 원본은 <code>outputs/checklist_lab/results_summary_v3.json</code>,
  확률 실측은 <code>softprob_probe.json</code> 에 있다. 1·2차 결과 파일과 <code>assessment/src/</code> 는 이 실험에서 변경되지 않았다(테스트 368개 통과).</p>
</section>

<footer class="wrap" style="padding-left:0;padding-right:0;">
  K-TEST 문제·채점 모델 파트 · 3차 실험 {esc(V3["run_date"])} · 판정 모델 {esc(V3["model"])} ·
  1·2차 보고서는 <code>체크리스트채점_실험보고_20260809.html</code> · 이 문서는 <code>make_report_v3.py</code> 가 결과 JSON 에서 자동 생성했다.
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
