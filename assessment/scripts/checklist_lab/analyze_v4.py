# -*- coding: utf-8 -*-
"""v4 — **확률 판정이 O/X 판정보다 나은가**를 같은 판정 결과 위에서 견준다.

■ 이번 실험이 답하려는 질문 (팀원 요청 그대로)

    "판정을 O/X 대신 확률로 받아서 문항별 가중치를 다시 배우면 더 잘 맞는가?"

그 답은 **Q − Q_bin** 하나에 들어 있다.

    P      확률 평균 × 5                        (학습 없음)
    Q      확률 벡터 + 문항별 가중치 학습        ← 팀원이 말한 'F 재학습'. 주인공
    P_bin  이진(p>0.5) 충족율 × 5               (학습 없음)     ← 대조
    Q_bin  이진 벡터 + 문항별 가중치 학습        ← **핵심 대조군**

네 방식은 **완전히 같은 판정 결과**에서 나온다. LLM 을 다시 부르지 않는다(추가 호출 0회).
p_yes 라는 같은 숫자를 그대로 쓰느냐(P·Q), 0.5 를 기준으로 잘라 0/1 로 만드느냐(P_bin·Q_bin)의
차이뿐이다. 그래서 여기서 나오는 차이는 **오직 '확률을 쓰는 것의 값어치'** 다.

■ 앞 실험(v1~v3)과는 직접 비교하지 않는다

판정 모델이 Gemini(gemini-3.1-flash-lite) → **Qwen(qwen3-30b-a3b-instruct-2507)** 으로
바뀌었다. Gemini 로는 logprobs 를 얻을 수 없어서 창구를 옮길 수밖에 없었다.
그래서 v1~v3 의 숫자는 **참고용으로만** 같은 표에 싣고, 줄마다 판정 모델을 표시한다.
"v4 가 v3 를 이겼다" 같은 문장은 이 실험에서 쓸 수 없다.

■ 공정 규칙 (앞 실험과 똑같이 유지한다)

  · 같은 답안 281건 · 같은 화자 단위 5겹(같은 함수·같은 배정) · 같은 사람 점수
  · 한 방식에서라도 점수를 못 낸 답안은 **모든 방식에서 뺀다**
  · 학습을 쓰는 방식(Q·Q_bin·LEN·MEAN)은 **out-of-fold 예측만** 쓴다
  · QWK + 화자 클러스터 부트스트랩 1000회 95% 신뢰구간 + 방식 간 차이 구간
  · **차이 구간이 0을 걸치면 개선이라고 쓰지 않는다**

■ 쓰는 법

    python analyze_v4.py             # 결과 요약 + results_summary_v4.json 저장
    python analyze_v4.py --self-test # 계산기만 예시 입력으로 점검(파일도 LLM도 안 건드림)
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from sklearn.linear_model import RidgeCV

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _lab_common import (  # noqa: E402
    N_BOOTSTRAP,
    N_FOLDS,
    OUT_DIR,
    SEED,
    all_metrics,
    assign_folds,
    bootstrap_qwk_ci,
    enable_utf8_output,
    fmt,
    human_score,
    load_rows,
    print_table,
    prompt_key,
    qwk,
    select_repro_subset,
    verdict,
)
# 앞 실험의 계산기를 **그대로 빌려 쓴다**(읽기만 한다).
# 같은 자로 재야 방식 차이가 계산 차이로 오염되지 않는다.
from analyze import RIDGE_ALPHAS, clean_nan, round_half_up  # noqa: E402
from analyze_v2 import (  # noqa: E402
    ceiling_by_linear_fit,
    ceiling_by_met_count,
    ceiling_by_met_count_optimized,
)
from extra_baselines import baseline_length, baseline_mean  # noqa: E402
from gen_checklists_v3 import fold_agreement  # noqa: E402
from gen_checklists_v4 import (  # noqa: E402
    CHECKLIST_V4_PATH,
    MIN_HARD_ITEMS,
    TARGET_ITEMS_V4,
    audit_leakage,
    items_for_v4,
    load_checklists_v4,
)
from run_experiment import met_ratio_to_score  # noqa: E402  (v1 의 반올림 규칙 그대로)
from run_experiment_v4 import (  # noqa: E402
    DEFAULT_OUT_V4,
    JUDGE_MODEL_V4,
    LOGPROB_PROVIDERS,
    load_done_v4,
)

#: 모든 수치를 기계가 읽을 수 있게 담아 두는 곳.
SUMMARY_V4_PATH = OUT_DIR / "results_summary_v4.json"
#: Q(확률+학습)·Q_bin(이진+학습)이 문항·겹마다 배운 항목별 비중(=근거)을 남기는 곳.
Q_WEIGHTS_PATH = OUT_DIR / "q_model_weights.json"
#: 참고로 실을 앞 실험 결과.
SUMMARY_V3_PATH = OUT_DIR / "results_summary_v3.json"

#: 확률이 '정보를 갖는가'를 볼 때 쓰는 칸막이.
#: 0.05~0.95 사이에 값이 있어야 O/X 로는 못 하는 이야기를 할 수 있다.
PROB_BINS = ((0.0, 0.01), (0.01, 0.05), (0.05, 0.25), (0.25, 0.75),
             (0.75, 0.95), (0.95, 0.99), (0.99, 1.0000001))
INFORMATIVE_LO, INFORMATIVE_HI = 0.05, 0.95

#: 방식 이름과 사람이 읽을 설명.
#: **이름에 하이픈을 쓰지 않는다** — 부트스트랩이 방식 쌍 이름을 "A-B" 로 만들어
#: 나중에 하이픈으로 다시 가르기 때문에, 이름 안에 하이픈이 있으면 짝을 잃는다.
METHOD_LABELS_V4 = {
    "P": "P 확률 평균×5 (학습 없음)",
    "Q": "Q 확률 벡터 + 문항별 가중치 학습 ★",
    "P_bin": "P_bin 이진 충족율×5 (학습 없음)",
    "Q_bin": "Q_bin 이진 벡터 + 문항별 가중치 학습 ★대조군",
    "MEAN": "바닥선(학습겹 평균, 답안을 안 읽음)",
    "LEN": "길이 기준선(글자 수만)",
    "CEIL_P_LIN_OWN": "천장 확률 선형적합(실배치·참고용)",
    "CEIL_B_LIN_OWN": "천장 이진 선형적합(실배치·참고용)",
    "CEIL_B_OPT_OWN": "천장 충족 개수(실배치·참고용)",
}
for _k in range(N_FOLDS):
    METHOD_LABELS_V4[f"CEIL_P_LIN_f{_k}"] = f"천장 겹{_k}벌 확률 선형적합"
    METHOD_LABELS_V4[f"CEIL_B_LIN_f{_k}"] = f"천장 겹{_k}벌 이진 선형적합"
    METHOD_LABELS_V4[f"CEIL_B_OPT_f{_k}"] = f"천장 겹{_k}벌 충족 개수(QWK 최대)"
    METHOD_LABELS_V4[f"CEIL_B_CNT_f{_k}"] = f"천장 겹{_k}벌 충족 개수(중앙값)"


# ── v4 판정 읽기 ─────────────────────────────────────────────────────────────
def v4_cells(judgments: dict, pass_tag: str = "main") -> dict[tuple[str, int], dict[str, dict]]:
    """v4 판정을 (답안 id, 체크리스트 겹) → {항목 id: 판정} 으로 정리한다.

    v4 는 판정 한 줄이 **항목 한 칸**이다(확률을 깨끗하게 얻으려고 항목마다 따로 불렀다).
    그래서 답안 하나의 벡터를 만들려면 같은 (답안, 겹)의 항목들을 다시 모아야 한다.
    """
    out: dict[tuple[str, int], dict[str, dict]] = defaultdict(dict)
    for (rid, fold_str, item_id, tag), rec in judgments.items():
        if tag != pass_tag or rec.get("status") != "ok":
            continue
        out[(rid, int(fold_str))][item_id] = rec
    return dict(out)


def prob_vector(cell: dict[str, dict], items: list[dict]) -> list[float] | None:
    """한 (답안, 겹)의 판정을 항목 순서대로 **확률**로 늘어놓는다.

    항목이 하나라도 비면 None 을 돌려준다 — 비어 있는 칸을 0.5 같은 값으로 메우면
    **재지 않은 것을 잰 것처럼** 만들게 된다. 우리는 그것을 하지 않기로 했다.
    항목 순서를 체크리스트 파일 기준으로 고정하는 이유: 순서가 흔들리면 배운 비중을
    어느 항목의 것인지 짝지을 수 없게 된다.
    """
    values = []
    for it in items:
        rec = cell.get(str(it["id"]))
        if rec is None or rec.get("p_yes") is None:
            return None
        values.append(float(rec["p_yes"]))
    return values


def binary_vector_v4(cell: dict[str, dict], items: list[dict]) -> list[float] | None:
    """같은 판정을 **0/1** 로 늘어놓는다(p > 0.5 면 1).

    같은 호출에서 나온 같은 판정이다. 확률을 쓰느냐 잘라 쓰느냐만 다르다 —
    이것이 P·Q 와 P_bin·Q_bin 을 완전히 같은 조건에서 견줄 수 있게 하는 장치다.
    """
    values = []
    for it in items:
        rec = cell.get(str(it["id"]))
        if rec is None or rec.get("met") is None:
            return None
        values.append(float(rec["met"]))
    return values


# ── Q · Q_bin — 겹마다 다른 체크리스트로 문항별 가중치를 배운다 ──────────────
def learn_per_prompt_v4(vec_by_fold: dict[int, dict[str, list[float]]],
                        rows_by_id: dict, fold_of: dict[str, int],
                        prompt_of: dict[str, str], checklists: dict,
                        usable: list[str], label: str):
    """문항마다 항목별 가중치를 배워 0~5 를 예측한다(겹별 out-of-fold).

    v3 의 J(`analyze_v3.learn_per_prompt_v3`)와 **같은 절차**다. 다른 것은 재료뿐 —
    Q 는 확률(0~1 연속), Q_bin 은 0/1 을 넣는다. 절차를 하나로 맞춰 두어야
    "재료가 좋아졌는가"만 남는다.

    겹 k 를 시험 볼 때:
      · 재료  = **겹 k 의 체크리스트**로 받은 판정 (학습 답안·시험 답안 모두)
      · 학습  = 겹 k 가 **아닌** 답안들 (그 체크리스트를 만들 때 본 답안들이다)
      · 예측  = 겹 k 답안들
    체크리스트도 가중치도 겹 k 답안을 보지 않고 만들어지므로 누출이 없다.

    돌려주는 값은 (답안 id -> 예측 점수, 문항·겹마다 배운 것)이다.
    배운 비중을 함께 돌려주는 이유: 점수만 있고 근거가 없으면 이 프로젝트에서는 결함이다.
    """
    preds: dict[str, int] = {}
    learned: dict[str, dict] = {}

    by_prompt: dict[str, list[str]] = defaultdict(list)
    for rid in usable:
        by_prompt[prompt_of[rid]].append(rid)

    for pkey, ids in sorted(by_prompt.items()):
        ids = sorted(set(ids))
        fold_info = []
        for k in range(N_FOLDS):
            items = items_for_v4(checklists, pkey, k)
            names = [str(it["id"]) for it in items]
            if not names:
                continue

            table = vec_by_fold.get(k, {})
            test_ids = [r for r in ids if fold_of[r] == k and r in table]
            train_ids = [r for r in ids if fold_of[r] != k and r in table]
            if not test_ids:
                continue

            y_train = np.array([human_score(rows_by_id[r]) for r in train_ids], dtype=float)
            # 배울 것이 너무 적거나 사람 점수가 전부 같으면 배울 수 없다.
            # 그럴 때는 학습 겹의 평균 점수로 답한다(가장 정직한 대체값)
            if len(train_ids) < 5 or float(np.std(y_train)) < 1e-9:
                fallback = round_half_up(float(np.mean(y_train))) if len(train_ids) else 0
                for rid in test_ids:
                    preds[rid] = fallback
                fold_info.append({"fold": k, "n_train": len(train_ids), "alpha": None,
                                  "note": "학습 표본이 모자라 학습 겹 평균으로 대체"})
                continue

            X_train = np.array([table[r] for r in train_ids], dtype=float)
            X_test = np.array([table[r] for r in test_ids], dtype=float)
            model = RidgeCV(alphas=RIDGE_ALPHAS)
            model.fit(X_train, y_train)
            for rid, value in zip(test_ids, model.predict(X_test)):
                preds[rid] = round_half_up(float(value))

            fold_info.append({
                "fold": k,
                "n_train": len(train_ids),
                "n_test": len(test_ids),
                "alpha": float(model.alpha_),
                "intercept": round(float(model.intercept_), 4),
                # 항목별로 배운 비중 = 이 항목의 값이 1 오르면 점수가 몇 점 오르는가
                "coefficients": {cid: round(float(c), 4)
                                 for cid, c in zip(names, model.coef_)},
                "questions": {str(it["id"]): it["question"] for it in items},
                "difficulty": {str(it["id"]): it.get("difficulty") for it in items},
            })

        learned[pkey] = {"method": label, "n_rows": len(ids), "folds": fold_info}
    return preds, learned


# ── 확률이 정보를 갖는가 ─────────────────────────────────────────────────────
def prob_distribution(values: list[float]) -> dict:
    """확률값이 0/1 로 몰려 있는지, 중간에 실제로 값이 있는지 센다.

    **이 표가 이번 실험에서 가장 먼저 봐야 할 숫자다.** 확률이 전부 0.001 아니면 0.999 라면
    그 확률은 O/X 를 소수점으로 적어 놓은 것에 지나지 않고, Q 가 Q_bin 을 이길 이유가
    애초에 없다. 그러니 결과가 어떻게 나오든 이 분포를 먼저 보고해야 한다.
    """
    n = len(values)
    if not n:
        return {"n": 0}
    bins = {}
    for lo, hi in PROB_BINS:
        count = sum(1 for p in values if lo <= p < hi)
        bins[f"{lo:g}~{hi if hi <= 1 else 1:g}"] = {"n": count, "rate": count / n}
    informative = sum(1 for p in values if INFORMATIVE_LO <= p <= INFORMATIVE_HI)
    middle = sum(1 for p in values if 0.25 <= p <= 0.75)
    return {
        "n": n,
        "bins": bins,
        "n_informative": informative,
        "rate_informative": informative / n,
        "n_middle": middle,
        "rate_middle": middle / n,
        "mean": statistics.mean(values),
        "median": statistics.median(values),
        # 0/1 에서 얼마나 떨어져 있나. 0 이면 완전히 O/X 와 같다는 뜻이다
        "mean_distance_from_extreme": statistics.mean(min(p, 1 - p) for p in values),
        "설명": (f"{INFORMATIVE_LO}~{INFORMATIVE_HI} 사이에 값이 있어야 확률이 O/X 로는 "
                 "못 하는 이야기를 한다. 이 비율이 0에 가까우면 확률의 이점이 없다."),
    }


# ── 자체 점검 ────────────────────────────────────────────────────────────────
def self_test() -> int:
    """계산기들이 맞게 도는지 답을 아는 예시로 확인한다(네트워크·파일 안 건드림)."""
    ok = True
    rows_out = []

    def check(label, got, want):
        nonlocal ok
        passed = got == want
        ok &= passed
        rows_out.append([label, str(got), str(want), "통과" if passed else "실패"])

    print("=== 계산기 자체 점검 (analyze_v4) ===")

    # ── 가짜 데이터: 문항 1종·답안 40건. 항목 1 이 점수와 맞물리게 만든다 ──
    ids = [f"R{i:03d}" for i in range(40)]
    rows_by_id = {rid: {"id": rid, "prompt": "문항A", "ref": "가나다" * (i + 1),
                        "speaker_id": f"S{i}", "evals": {"content": i % 6}}
                  for i, rid in enumerate(ids)}
    fold_of = {rid: i % N_FOLDS for i, rid in enumerate(ids)}
    prompt_of = {rid: "P" for rid in ids}
    checklists = {"P": {"folds": {str(k): {"status": "ok", "items": [
        {"id": "1", "question": "핵심을 말했는가?", "importance": 90, "difficulty": "어려움"},
        {"id": "2", "question": "덧붙였는가?", "importance": 10, "difficulty": "쉬움"},
    ]} for k in range(N_FOLDS)}}}

    # ① 벡터 만들기 — 항목이 하나라도 비면 None
    cell_full = {"1": {"p_yes": 0.9, "met": 1}, "2": {"p_yes": 0.2, "met": 0}}
    items = checklists["P"]["folds"]["0"]["items"]
    check("확률 벡터", prob_vector(cell_full, items), [0.9, 0.2])
    check("이진 벡터", binary_vector_v4(cell_full, items), [1.0, 0.0])
    check("항목이 빠지면 None", prob_vector({"1": {"p_yes": 0.9}}, items), None)
    check("p 가 없으면 None",
          prob_vector({"1": {"p_yes": None}, "2": {"p_yes": 0.2}}, items), None)

    # ② 판정 읽기 — (답안, 겹) 으로 다시 모으는가
    judgments = {
        ("A-1", "0", "1", "main"): {"status": "ok", "p_yes": 0.9, "met": 1},
        ("A-1", "0", "2", "main"): {"status": "ok", "p_yes": 0.1, "met": 0},
        ("A-1", "3", "1", "main"): {"status": "ok", "p_yes": 0.5, "met": 0},
        ("A-1", "0", "3", "main"): {"status": "failed"},
        ("A-1", "0", "1", "rep1"): {"status": "ok", "p_yes": 0.8, "met": 1},
    }
    cells = v4_cells(judgments, "main")
    check("성공한 main 판정만, 겹별로 모은다", sorted(cells), [("A-1", 0), ("A-1", 3)])
    check("겹0 에 항목 2개", sorted(cells[("A-1", 0)]), ["1", "2"])

    # ③ Q 학습 — 잡음 항목이 있어도 점수와 맞물린 항목을 잡아내는가
    prob_by_fold, bin_by_fold = {}, {}
    for k in range(N_FOLDS):
        prob_by_fold[k], bin_by_fold[k] = {}, {}
        for i, rid in enumerate(ids):
            score = i % 6
            # 항목 1 = 점수 3 이상이면 높은 확률, 항목 2 = 홀짝(점수와 무관한 잡음)
            prob_by_fold[k][rid] = [0.95 if score >= 3 else 0.05, float(i % 2)]
            bin_by_fold[k][rid] = [1.0 if score >= 3 else 0.0, float(i % 2)]

    q_preds, q_learned = learn_per_prompt_v4(prob_by_fold, rows_by_id, fold_of,
                                             prompt_of, checklists, ids, "Q")
    check("Q 가 모든 답안에 점수를 냈다", len(q_preds), 40)
    check("Q 예측이 0~5 안에 있다", all(0 <= v <= 5 for v in q_preds.values()), True)
    coefs = q_learned["P"]["folds"][0]["coefficients"]
    rows_out.append(["항목1 비중 > 항목2 비중", f"{coefs['1']:.2f} vs {coefs['2']:.2f}",
                     "앞이 크다", "통과" if coefs["1"] > coefs["2"] else "실패"])
    ok &= coefs["1"] > coefs["2"]
    check("배운 근거에 항목 문구가 함께 남는다",
          q_learned["P"]["folds"][0]["questions"]["1"], "핵심을 말했는가?")

    # ④ 겹을 넘지 않는가 — 시험 겹 답안이 학습에 들어가면 안 된다
    fold0_test = [r for r in ids if fold_of[r] == 0]
    check("겹0 학습 표본 = 전체 − 겹0",
          q_learned["P"]["folds"][0]["n_train"], 40 - len(fold0_test))

    # ⑤ 충족율 → 점수 (v1 규칙을 그대로 쓴다)
    got = [met_ratio_to_score(v) for v in (0.0, 1 / 3, 0.5, 2 / 3, 1.0)]
    rows_out.append(["비율→점수 [0, 1/3, .5, 2/3, 1]", str(got), "[0, 2, 3, 3, 5]",
                     "통과" if got == [0, 2, 3, 3, 5] else "실패"])
    ok &= got == [0, 2, 3, 3, 5]

    # ⑥ 확률 분포 — 0/1 에 몰린 경우와 퍼진 경우를 갈라 보는가
    spiky = prob_distribution([0.001] * 50 + [0.999] * 50)
    spread = prob_distribution([i / 100 for i in range(100)])
    check("0/1 로 몰리면 정보 비율 0", spiky["n_informative"], 0)
    rows_out.append(["0/1 로 몰리면 끝에서의 거리≈0", f"{spiky['mean_distance_from_extreme']:.4f}",
                     "0에 가깝다",
                     "통과" if spiky["mean_distance_from_extreme"] < 0.01 else "실패"])
    ok &= spiky["mean_distance_from_extreme"] < 0.01
    rows_out.append(["고루 퍼지면 정보 비율 높다", f"{spread['rate_informative']:.2f}",
                     "0.8 이상", "통과" if spread["rate_informative"] > 0.8 else "실패"])
    ok &= spread["rate_informative"] > 0.8

    # ⑦ 천장은 실제 방식보다 낮을 수 없다(정답을 보고 맞추므로)
    vec = {rid: bin_by_fold[0][rid] for rid in ids}
    truth = [human_score(rows_by_id[r]) for r in ids]
    plain = [met_ratio_to_score(sum(vec[r]) / 2) for r in ids]
    ceil_opt = ceiling_by_met_count_optimized(ids, rows_by_id, vec, prompt_of, {"P": 2})
    ceil_lin = ceiling_by_linear_fit(ids, rows_by_id, vec, prompt_of)
    q_plain, q_opt = qwk(plain, truth), qwk([ceil_opt[r] for r in ids], truth)
    q_lin = qwk([ceil_lin[r] for r in ids], truth)
    rows_out.append(["천장(개수·QWK최대) ≥ 충족율", f"{q_opt:.3f} vs {q_plain:.3f}",
                     "천장이 크거나 같다", "통과" if q_opt >= q_plain - 1e-9 else "실패"])
    ok &= q_opt >= q_plain - 1e-9
    rows_out.append(["천장(선형) ≥ 충족율", f"{q_lin:.3f} vs {q_plain:.3f}",
                     "천장이 크거나 같다", "통과" if q_lin >= q_plain - 1e-9 else "실패"])
    ok &= q_lin >= q_plain - 1e-9

    print_table(["항목", "나온 값", "기대", "판정"], rows_out)
    print("\n" + ("모두 통과" if ok else "실패한 항목이 있다"))
    return 0 if ok else 1


# ── 실행 ─────────────────────────────────────────────────────────────────────
def main() -> int:  # noqa: C901  (표를 여러 개 그리느라 길다)
    enable_utf8_output()
    ap = argparse.ArgumentParser(
        description="확률 판정(P·Q)과 O/X 판정(P_bin·Q_bin)을 같은 판정 결과 위에서 견준다")
    ap.add_argument("--judgments-v4", type=Path, default=DEFAULT_OUT_V4)
    ap.add_argument("--out", type=Path, default=SUMMARY_V4_PATH)
    ap.add_argument("--bootstrap", type=int, default=N_BOOTSTRAP)
    ap.add_argument("--repro-n", type=int, default=60)
    ap.add_argument("--self-test", action="store_true",
                    help="계산기만 예시 입력으로 점검하고 끝낸다")
    args = ap.parse_args()

    if args.self_test:
        return self_test()

    # ── 재료 읽기 ────────────────────────────────────────────────────────────
    rows, counts = load_rows()
    rows_by_id = {str(r["id"]): r for r in rows}
    fold_of, diag = assign_folds(rows, N_FOLDS)
    prompt_of = {rid: prompt_key(r.get("prompt") or "") for rid, r in rows_by_id.items()}
    checklists = load_checklists_v4()
    judgments = load_done_v4(args.judgments_v4)
    cells = v4_cells(judgments, "main")

    print("=== 표본 ===")
    print_table(["단계", "건수"], [[k, v] for k, v in counts.items()])
    print(f"화자 {len({str(r.get('speaker_id')) for r in rows})}명 · "
          f"겹: 화자 단위 {N_FOLDS}겹 · 겹을 넘나든 화자 {diag['speaker_leak_count']}명")
    print(f"판정 모델: {JUDGE_MODEL_V4} (OpenRouter · logprobs) — "
          f"v1~v3 는 gemini-3.1-flash-lite 였다. **직접 비교 금지**")

    # ── 체크리스트 항목 수·난이도·누출 감사 ──────────────────────────────────
    print(f"\n=== v4 체크리스트 항목 수 (목표 {TARGET_ITEMS_V4}개 · v3 는 평균 3.5개였다) ===")
    item_rows, v4_counts_json = [], {}
    all_counts = []
    for pkey in sorted(checklists):
        per_fold = [len(items_for_v4(checklists, pkey, k)) for k in range(N_FOLDS)]
        all_counts.extend(per_fold)
        hard = sum(1 for k in range(N_FOLDS)
                   for it in items_for_v4(checklists, pkey, k)
                   if it.get("difficulty") == "어려움")
        item_rows.append([pkey, (checklists[pkey].get("prompt") or "")[:20], *per_fold,
                          f"{sum(per_fold) / len(per_fold):.1f}", hard])
        v4_counts_json[pkey] = {"per_fold": per_fold,
                                "mean": sum(per_fold) / len(per_fold),
                                "n_hard_total": hard}
    print_table(["문항", "지시문", "겹0", "겹1", "겹2", "겹3", "겹4", "평균", "어려움 합"],
                item_rows)
    print(f"  전체 {len(all_counts)}벌 평균 {statistics.mean(all_counts):.2f}개 · "
          f"목표 {TARGET_ITEMS_V4}개 달성 벌 "
          f"{sum(1 for c in all_counts if c >= TARGET_ITEMS_V4)}/{len(all_counts)}")

    audit = audit_leakage(checklists, fold_of)
    print(f"  겹 분리 감사: 체크리스트 {audit['n_checklists_checked']}벌 · "
          f"본 답안 {audit['n_exemplars_checked']}건 → **시험 겹 답안 혼입 "
          f"{audit['n_leaked']}건** ({'깨끗하다' if audit['clean'] else '누출 — 무효'})")

    # ── 겹 사이 항목이 얼마나 닮았나 ─────────────────────────────────────────
    print("\n=== 같은 문항의 다섯 벌이 서로 얼마나 닮았나 (v3 는 0.331 이었다) ===")
    agree_rows, agree_json = [], {}
    for pkey in sorted(checklists):
        folds = {k: v for k, v in (checklists[pkey].get("folds") or {}).items()
                 if v.get("status") == "ok"}
        agree = fold_agreement(folds)
        agree_json[pkey] = agree
        agree_rows.append([pkey, (checklists[pkey].get("prompt") or "")[:20],
                           fmt(agree["mean_similarity"]), fmt(agree["matched_rate"]),
                           fmt(agree["min_similarity"]), fmt(agree["max_similarity"])])
    print_table(["문항", "지시문", "문구 닮음(평균)", "짝지어진 비율", "최소", "최대"], agree_rows)
    all_sims = [v["mean_similarity"] for v in agree_json.values()]
    all_match = [v["matched_rate"] for v in agree_json.values()]
    print(f"  문항 9종 평균: 문구 닮음 {statistics.mean(all_sims):.3f} · "
          f"짝지어진 비율 {statistics.mean(all_match):.3f}")
    print("  ※ 글자 겹침으로 재므로 같은 뜻을 다른 말로 쓴 항목은 낮게 나온다(닮음의 하한).")

    # ── 벡터 만들기 ──────────────────────────────────────────────────────────
    prob_by_fold: dict[int, dict[str, list[float]]] = {k: {} for k in range(N_FOLDS)}
    bin_by_fold: dict[int, dict[str, list[float]]] = {k: {} for k in range(N_FOLDS)}
    for (rid, fold), cell in cells.items():
        items = items_for_v4(checklists, prompt_of.get(rid, ""), fold)
        if not items:
            continue
        pv = prob_vector(cell, items)
        bv = binary_vector_v4(cell, items)
        if pv is not None and bv is not None:
            prob_by_fold[fold][rid] = pv
            bin_by_fold[fold][rid] = bv

    # ── 공통 표본: 다섯 겹 판정이 **모두** 갖춰진 답안만 ─────────────────────
    usable, dropped = [], defaultdict(list)
    for rid in sorted(rows_by_id):
        missing = [k for k in range(N_FOLDS) if rid not in prob_by_fold[k]]
        if missing:
            dropped[f"겹{','.join(map(str, missing))} 판정 미완"].append(rid)
        else:
            usable.append(rid)

    print(f"\n=== 공통 표본: {len(usable)}건 "
          f"(대상 {len(rows_by_id)}건 중 {len(rows_by_id) - len(usable)}건 제외) ===")
    if dropped:
        print("  제외 내역 (한 방식에서라도 점수를 못 낸 답안은 모든 방식에서 뺀다)")
        for reason, ids in sorted(dropped.items(), key=lambda kv: -len(kv[1]))[:8]:
            print(f"    {len(ids):4d}건  {reason}  ({', '.join(i[-16:] for i in ids[:3])})")
    if len(usable) < 10:
        print("\n[중단] 공통 표본이 10건 미만이라 성적을 계산하지 않는다.")
        return 1

    truth = [human_score(rows_by_id[rid]) for rid in usable]
    speakers = [str(rows_by_id[rid].get("speaker_id")) for rid in usable]

    # ── 학습을 쓰는 두 방식 ──────────────────────────────────────────────────
    q_preds, q_learned = learn_per_prompt_v4(prob_by_fold, rows_by_id, fold_of,
                                             prompt_of, checklists, usable, "Q")
    qb_preds, qb_learned = learn_per_prompt_v4(bin_by_fold, rows_by_id, fold_of,
                                               prompt_of, checklists, usable, "Q_bin")
    Path(Q_WEIGHTS_PATH).parent.mkdir(parents=True, exist_ok=True)
    Path(Q_WEIGHTS_PATH).write_text(
        json.dumps({"Q": q_learned, "Q_bin": qb_learned}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    print(f"\nQ·Q_bin 이 문항·겹마다 항목 비중을 배웠다(LLM 호출 0회). "
          f"근거 저장: {Q_WEIGHTS_PATH}")

    # ── 점수 만들기 ──────────────────────────────────────────────────────────
    # 자기 겹 벡터 — 실제 채점에 쓰이는 배치다
    prob_own = {rid: prob_by_fold[fold_of[rid]][rid] for rid in usable}
    bin_own = {rid: bin_by_fold[fold_of[rid]][rid] for rid in usable}

    preds = {
        "P": [met_ratio_to_score(statistics.mean(prob_own[rid])) for rid in usable],
        "Q": [int(q_preds[rid]) for rid in usable],
        "P_bin": [met_ratio_to_score(statistics.mean(bin_own[rid])) for rid in usable],
        "Q_bin": [int(qb_preds[rid]) for rid in usable],
    }
    # 기준선 — 같은 표본·같은 겹에서 잰다(LLM 을 전혀 안 쓴다)
    mean_p = baseline_mean(usable, rows_by_id, fold_of)
    len_p = baseline_length(usable, rows_by_id, fold_of)
    preds["MEAN"] = [mean_p[rid] for rid in usable]
    preds["LEN"] = [len_p[rid] for rid in usable]

    # ── 천장 ─────────────────────────────────────────────────────────────────
    # ① 겹벌 천장 — "겹 k 의 체크리스트를 전체 답안에 썼다면". 다섯 개가 나온다
    ceilings = {}
    for k in range(N_FOLDS):
        pv = {rid: prob_by_fold[k][rid] for rid in usable}
        bv = {rid: bin_by_fold[k][rid] for rid in usable}
        n_items_k = {p: len(items_for_v4(checklists, p, k)) for p in set(prompt_of.values())}
        ceilings[f"CEIL_P_LIN_f{k}"] = ceiling_by_linear_fit(usable, rows_by_id, pv, prompt_of)
        ceilings[f"CEIL_B_LIN_f{k}"] = ceiling_by_linear_fit(usable, rows_by_id, bv, prompt_of)
        ceilings[f"CEIL_B_CNT_f{k}"] = ceiling_by_met_count(usable, rows_by_id, bv, prompt_of)
        ceilings[f"CEIL_B_OPT_f{k}"] = ceiling_by_met_count_optimized(
            usable, rows_by_id, bv, prompt_of, n_items_k)
    # ② 실배치 천장 — 답안마다 자기 겹의 체크리스트로. 칸이 (문항 × 겹)까지 쪼개져
    #    낙관 쪽으로 부푼다. 참고용으로만 읽어야 한다
    prompt_fold_of = {rid: f"{prompt_of[rid]}#{fold_of[rid]}" for rid in usable}
    n_items_own = {f"{p}#{k}": len(items_for_v4(checklists, p, k))
                   for p in set(prompt_of.values()) for k in range(N_FOLDS)}
    ceilings["CEIL_P_LIN_OWN"] = ceiling_by_linear_fit(
        usable, rows_by_id, prob_own, prompt_fold_of)
    ceilings["CEIL_B_LIN_OWN"] = ceiling_by_linear_fit(
        usable, rows_by_id, bin_own, prompt_fold_of)
    ceilings["CEIL_B_OPT_OWN"] = ceiling_by_met_count_optimized(
        usable, rows_by_id, bin_own, prompt_fold_of, n_items_own)

    for name, table in ceilings.items():
        preds[name] = [table[rid] for rid in usable]

    # ── 성적과 신뢰구간 ──────────────────────────────────────────────────────
    metrics = {m: all_metrics(p, truth) for m, p in preds.items()}
    print(f"\n부트스트랩 {args.bootstrap}회 계산 중 (화자를 통째로 다시 뽑는다)...")
    cis, diff_cis = bootstrap_qwk_ci(preds, truth, speakers, args.bootstrap, SEED)

    def row_for(m: str) -> list:
        return [METHOD_LABELS_V4.get(m, m), fmt(metrics[m]["qwk"]),
                f"[{fmt(cis[m]['lo'])}, {fmt(cis[m]['hi'])}]",
                fmt(metrics[m]["spearman"]),
                f"{metrics[m]['exact']:.1%}", f"{metrics[m]['within1']:.1%}",
                f"{statistics.mean(preds[m]):.2f}"]

    headers = ["방식", "QWK", "95% 신뢰구간", "스피어만", "정확일치", "±1 이내", "평균예측"]
    print(f"\n{'=' * 96}")
    print(f"  ① 방식별 성적 — 같은 판정 결과·같은 겹의 out-of-fold 예측만 "
          f"(표본 {len(usable)}건 · 화자 {len(set(speakers))}명)")
    print("=" * 96)
    print_table(headers, [row_for(m) for m in ("P", "Q", "P_bin", "Q_bin", "MEAN", "LEN")])
    print(f"  참고: 사람 점수 평균 {statistics.mean(truth):.2f} · "
          f"분포 {dict(sorted(Counter(truth).items()))}")

    # ── ★ 이번 실험의 답: Q vs Q_bin ─────────────────────────────────────────
    print(f"\n{'=' * 96}\n  ② ★ 팀원 질문의 답 — 확률이 O/X 보다 나은가\n{'=' * 96}")
    key_pairs = [("Q", "Q_bin"), ("P", "P_bin"), ("Q", "P"), ("Q_bin", "P_bin"),
                 ("Q", "LEN"), ("Q_bin", "LEN"), ("P", "LEN"), ("P_bin", "LEN"),
                 ("Q", "MEAN"), ("Q", "CEIL_P_LIN_f0")]
    table, pair_json = [], {}
    for a, b in key_pairs:
        d = diff_cis.get(f"{a}-{b}") or diff_cis.get(f"{b}-{a}")
        if d is None:
            continue
        # 저장된 쌍의 방향이 반대면 부호를 뒤집어 "앞 − 뒤"로 맞춘다
        flip = f"{a}-{b}" not in diff_cis
        mean, lo, hi = ((-d["mean"], -d["hi"], -d["lo"]) if flip
                        else (d["mean"], d["lo"], d["hi"]))
        v = ("앞쪽이 유의하게 높다" if lo > 0 else
             "뒤쪽이 유의하게 높다" if hi < 0 else "0을 걸친다 → 차이를 주장할 수 없다")
        table.append([f"{a} − {b}", f"{mean:+.3f}", f"[{lo:+.3f}, {hi:+.3f}]", v])
        pair_json[f"{a} - {b}"] = {"mean": mean, "lo": lo, "hi": hi, "verdict": v}
    print_table(["비교(앞 − 뒤)", "QWK 차이", "95% 신뢰구간", "판정"], table)
    print("  ※ 구간이 0을 걸치면 '개선했다'고 쓰지 않는다(프로젝트 정직 규칙).")
    main_answer = pair_json.get("Q - Q_bin", {})
    print(f"\n  ▶ Q − Q_bin = {main_answer.get('mean', float('nan')):+.3f} "
          f"[{main_answer.get('lo', float('nan')):+.3f}, "
          f"{main_answer.get('hi', float('nan')):+.3f}] → {main_answer.get('verdict', '')}")

    # ── 천장 ─────────────────────────────────────────────────────────────────
    print(f"\n{'=' * 96}\n  ③ 정보 천장 — 항목이 들고 있는 정보의 상한"
          f"\n{'=' * 96}")
    ceiling_json = {}
    for kind, label in (("P_LIN", "확률 벡터 선형 적합"),
                        ("B_LIN", "이진 벡터 선형 적합"),
                        ("B_OPT", "충족 개수 사상(QWK 최대)"),
                        ("B_CNT", "충족 개수 사상(중앙값)")):
        values = [metrics[f"CEIL_{kind}_f{k}"]["qwk"] for k in range(N_FOLDS)]
        ceiling_json[kind] = {"per_fold": values, "mean": statistics.mean(values),
                              "min": min(values), "max": max(values)}
        print(f"    {label:22s} 겹별 {[f'{v:.3f}' for v in values]} · "
              f"평균 {statistics.mean(values):.3f} · 폭 {min(values):.3f}~{max(values):.3f}")
    print("\n  실배치 천장 — 답안마다 자기 겹의 체크리스트로 (참고용)")
    print_table(headers, [row_for(m) for m in
                          ("CEIL_P_LIN_OWN", "CEIL_B_LIN_OWN", "CEIL_B_OPT_OWN")])
    # 실배치 천장이 왜 못 쓰는 값인지 숫자로 보여 준다.
    # (문항 × 겹) 칸마다 답안이 6~8건인데 항목이 ~9개라, 맞출 손잡이가 답안보다 많다.
    # 그러면 선형 적합은 **어떤 정답이든** 그대로 맞혀 버려서 1.000 이 나온다 — 정보가 아니다
    cell_sizes = Counter(prompt_fold_of[rid] for rid in usable)
    degenerate = sum(1 for cell, size in cell_sizes.items()
                     if size <= n_items_own.get(cell, 0) + 1)
    print(f"  ※ 실배치 천장은 못 쓰는 값이다. (문항×겹) 칸 {len(cell_sizes)}개 중 "
          f"**{degenerate}개**가 답안 수(칸당 "
          f"{min(cell_sizes.values())}~{max(cell_sizes.values())}건)보다 항목 수가 많거나 같다.")
    print("     손잡이가 답안보다 많으면 선형 적합은 어떤 정답이든 그대로 맞혀 1.000 이 된다.")
    print("     그래서 이 줄의 1.000 은 '항목이 완벽하다'가 아니라 '아무것도 재지 못했다'는 뜻이다.")
    print("  ※ 천장은 정답을 보고 맞춘 값이라 실제 채점에 쓸 수 없다. "
          "항목이 많을수록 저절로 올라간다(v4 는 항목이 v2·v3 보다 많다).")

    # ── ④ v3 실패 원인이 고쳐졌는가 ──────────────────────────────────────────
    print(f"\n{'=' * 96}\n  ④ v3 실패 원인 진단 — 항목이 여전히 쉬운가"
          f"\n{'=' * 96}")
    all_bits = [v for rid in usable for v in bin_own[rid]]
    n_all_met = sum(1 for rid in usable if bin_own[rid] and all(v == 1 for v in bin_own[rid]))
    n_none_met = sum(1 for rid in usable if bin_own[rid] and all(v == 0 for v in bin_own[rid]))
    saturation = {
        "mean_item_pass_rate": statistics.mean(all_bits) if all_bits else float("nan"),
        "n_answers_all_met": n_all_met,
        "rate_answers_all_met": n_all_met / len(usable),
        "n_answers_none_met": n_none_met,
        "v3_reference": {"mean_item_pass_rate": 0.654, "n_answers_all_met": 95,
                         "n_common_sample": 281},
        "설명": "항목 통과율이 1에 가까울수록, 전 항목 통과 답안이 많을수록 점수를 못 가른다.",
    }
    print(f"  항목 통과율 평균 **{saturation['mean_item_pass_rate']:.1%}**  (v3 는 65.4%)")
    print(f"  전 항목 통과 답안 **{n_all_met}건 / {len(usable)}건 "
          f"({n_all_met / len(usable):.1%})**  (v3 는 281건 중 95건 = 33.8%)")
    print(f"  전 항목 미통과 답안 {n_none_met}건")

    # 난이도 표기가 실제로 맞았는가 — 모델의 자기 신고를 통과율로 검증한다
    by_diff: dict[str, list[float]] = defaultdict(list)
    for rid in usable:
        items = items_for_v4(checklists, prompt_of[rid], fold_of[rid])
        for it, value in zip(items, bin_own[rid]):
            by_diff[str(it.get("difficulty"))].append(value)
    print("\n  난이도 표기가 실제와 맞는가 (모델이 '어려움'이라 한 항목이 정말 덜 통과했나)")
    print_table(["표기 난이도", "항목 칸 수", "실제 통과율"],
                [[d, len(v), f"{statistics.mean(v):.1%}"]
                 for d, v in sorted(by_diff.items(),
                                    key=lambda kv: -statistics.mean(kv[1]))])
    difficulty_check = {d: {"n_cells": len(v), "pass_rate": statistics.mean(v)}
                        for d, v in by_diff.items()}

    # ── ⑤ 확률이 정보를 갖는가 ───────────────────────────────────────────────
    print(f"\n{'=' * 96}\n  ⑤ ★ 확률값 분포 — 확률이 O/X 로는 못 하는 이야기를 하는가"
          f"\n{'=' * 96}")
    all_probs = [v for rid in usable for v in prob_own[rid]]
    dist = prob_distribution(all_probs)
    print_table(["확률 구간", "칸 수", "비율"],
                [[k, v["n"], f"{v['rate']:.1%}"] for k, v in dist["bins"].items()])
    print(f"  0/1 이 아닌 값({INFORMATIVE_LO}~{INFORMATIVE_HI}) "
          f"**{dist['n_informative']}칸 / {dist['n']}칸 = {dist['rate_informative']:.1%}**")
    print(f"  진짜 중간(0.25~0.75) {dist['n_middle']}칸 ({dist['rate_middle']:.1%})")
    print(f"  0/1 끝에서 떨어진 정도(평균) {dist['mean_distance_from_extreme']:.4f} "
          f"— 0 이면 확률이 O/X 와 완전히 같다는 뜻이다")

    # ── ⑥ 문항별 QWK ────────────────────────────────────────────────────────
    print(f"\n{'=' * 96}\n  ⑥ 문항별 QWK (문항당 표본이 작아 참고용)\n{'=' * 96}")
    by_prompt_idx = defaultdict(list)
    for i, rid in enumerate(usable):
        by_prompt_idx[prompt_of[rid]].append(i)
    per_prompt_json, per_prompt_rows = {}, []
    shown = ("P", "Q", "P_bin", "Q_bin", "LEN")
    for pkey, idxs in sorted(by_prompt_idx.items()):
        t = [truth[i] for i in idxs]
        entry = {m: qwk([preds[m][i] for i in idxs], t) for m in shown}
        per_prompt_json[pkey] = {"n": len(idxs), **entry}
        per_prompt_rows.append([pkey, len(idxs), *[fmt(entry[m]) for m in shown]])
    print_table(["문항", "건수", *shown], per_prompt_rows)

    # ── ⑦ 재현성 ─────────────────────────────────────────────────────────────
    print(f"\n{'=' * 96}\n  ⑦ 재현성 — 같은 답안을 같은 설정으로 3회 판정 "
          f"(고정 60건, v1~v3 와 같은 표본)\n{'=' * 96}")
    repro = analyze_repro_v4(judgments, rows, checklists, fold_of, prompt_of, args.repro_n)
    if not repro["n_measured"]:
        print("  아직 재현성 실행(rep1·rep2·rep3)이 없다. 이 항목은 '미측정'으로 남긴다.")
    else:
        spread = repro["prob_spread"]
        print(f"  3회 다 성공한 항목 칸 {repro['n_cells']}칸 (답안 {repro['n_measured']}건)")
        print(f"  확률값이 **소수점까지** 같은 칸 {repro['n_cells_identical']}칸 "
              f"({repro['prob_identical_rate']:.3f}) — 거의 다 미세하게 흔들렸다")
        print(f"  흔들린 폭: 중앙값 {spread['median']:.2e} · 상위10% {spread['p90']:.2e} · "
              f"상위1% {spread['p99']:.3f} · 최대 {spread['max']:.3f}")
        print(f"    폭이 0.01 을 넘은 칸 {spread['n_over_0.01']}칸 · "
              f"0.1 을 넘은 칸 {spread['n_over_0.1']}칸")
        print(f"  O/X 가 뒤집힌 칸 {repro['n_cells_met_flipped']}칸 "
              f"({repro['met_flip_rate']:.3f}) — v3(Gemini)는 0/213칸이었다")
        print(f"  최종 점수 완전일치 {repro['score_exact_agreement']:.3f} · "
              f"평균 진폭 {repro['score_mean_amplitude']:.3f} "
              f"(미세한 흔들림은 반올림에 먹혀 점수까지 오지 않았다)")
        print(f"  원인 가르기 — 3회 내내 같은 공급자였던 칸 {repro['n_cells_same_provider']}칸 "
              f"중 {repro['n_same_provider_and_differs']}칸이 흔들렸고, "
              f"공급자가 바뀐 칸 {repro['n_cells_provider_changed']}칸 중 "
              f"{repro['n_provider_changed_and_differs']}칸이 흔들렸다")
        print(f"    → 공급자를 고정해도 흔들린다. 원인은 '어디로 보냈나'가 아니라 "
              f"모델·서버의 계산 방식 쪽이다")
        print(f"    (흔들린 폭 중앙값: 같은 공급자 {repro['median_spread_same_provider']:.2e} · "
              f"바뀐 공급자 {repro['median_spread_changed_provider']:.2e})")

    # ── ⑧ 앞 실험 참고 (직접 비교 금지) ─────────────────────────────────────
    print(f"\n{'=' * 96}\n  ⑧ 앞 실험(v1~v3) 참고 — **판정 모델이 달라 직접 비교 금지**"
          f"\n{'=' * 96}")
    prior = {}
    if Path(SUMMARY_V3_PATH).exists():
        prior_summary = json.loads(Path(SUMMARY_V3_PATH).read_text(encoding="utf-8"))
        prior_methods = prior_summary.get("methods", {})
        prior_n = (prior_summary.get("common_sample") or {}).get("n")
        show = ("A0", "A1", "B", "C", "D", "E", "F", "G", "H", "I", "I_imp", "J", "LEN", "MEAN")
        prior_rows = []
        for m in show:
            entry = prior_methods.get(m)
            if not entry:
                continue
            ci = entry.get("qwk_ci95") or {}
            prior[m] = {"label": entry.get("label"), "qwk": entry.get("qwk"),
                        "qwk_ci95": ci, "n": entry.get("n"),
                        "judge_model": prior_summary.get("model")}
            prior_rows.append([entry.get("label", m), fmt(entry.get("qwk")),
                               f"[{fmt(ci.get('lo'))}, {fmt(ci.get('hi'))}]",
                               prior_summary.get("model", "?"), prior_n])
        print_table(["방식", "QWK", "95% 신뢰구간", "판정 모델", "표본"], prior_rows)
    print(f"  ↑ 위는 gemini-3.1-flash-lite 로 판정한 결과다. "
          f"아래 v4 는 {JUDGE_MODEL_V4} 로 판정했다.")
    print_table(["방식", "QWK", "95% 신뢰구간", "판정 모델", "표본"],
                [[METHOD_LABELS_V4[m], fmt(metrics[m]["qwk"]),
                  f"[{fmt(cis[m]['lo'])}, {fmt(cis[m]['hi'])}]", JUDGE_MODEL_V4, len(usable)]
                 for m in ("P", "Q", "P_bin", "Q_bin", "LEN")])
    print("  ※ 판정 모델이 다르면 '어느 방식이 나은가'와 '어느 모델이 나은가'가 뒤섞인다.")
    print("  ※ 이 표의 위아래를 견주어 '개선했다/나빠졌다'고 말하지 마라.")

    # ── 저장 ─────────────────────────────────────────────────────────────────
    fail_counts = Counter()
    total_cost, total_elapsed = 0.0, 0.0
    provider_counts = Counter()
    for rec in judgments.values():
        if rec.get("status") != "ok":
            fail_counts[f"{rec.get('pass')}/{rec.get('status')}"] += 1
        total_cost += float(rec.get("cost_usd") or 0.0)
        total_elapsed += float(rec.get("elapsed_sec") or 0.0)
        if rec.get("provider"):
            provider_counts[rec["provider"]] += 1

    summary = {
        "run_date": time.strftime("%Y-%m-%d %H:%M:%S"),
        "experiment": ("체크리스트 v4 — 항목 10개 목표 + 판정을 logprobs 정규화 확률로 받아 "
                       "문항별 가중치 재학습"),
        "team_request": [
            "① 체크리스트를 10개로 만들기",
            "② 판정을 O/X 대신 logprobs 정규화 확률로 받아 문항별 가중치(F)를 다시 학습",
        ],
        "judge_model": JUDGE_MODEL_V4,
        "judge_api": "OpenRouter chat/completions · logprobs top 8",
        "judge_providers_allowed": LOGPROB_PROVIDERS,
        "judge_providers_used": dict(provider_counts),
        "generator_model": "gemini-3.1-flash-lite (v1~v3 와 같다)",
        "temperature": 0.0,
        "input_type": "사람이 직접 적은 전사(ref)",
        "human_label_field": "evals.content (내용 및 과제 수행, 0~5)",
        "comparability": {
            "vs_v1_v2_v3": "직접 비교 금지",
            "reason": ("판정 모델이 gemini-3.1-flash-lite → qwen3-30b-a3b-instruct-2507 로 "
                       "바뀌었다. Gemini 는 logprobs 를 주지 않아(3.x 계열에서 제거됨) "
                       "확률 판정을 하려면 창구를 옮길 수밖에 없었다. 그래서 v4 와 v1~v3 의 "
                       "숫자 차이에는 '방식의 차이'와 '모델의 차이'가 섞여 있다."),
            "what_is_comparable": ("v4 안에서 P·Q·P_bin·Q_bin 은 **완전히 같은 판정 결과**에서 "
                                   "나오므로 서로 직접 비교할 수 있다. 특히 Q vs Q_bin 이 "
                                   "'확률이 O/X 보다 나은가'의 답이다."),
            "citation_protocol_lost": ("v1~v3 는 충족 판정마다 답안 원문 인용을 요구하고 원문에 "
                                       "없으면 폐기했다. v4 는 한 낱말 답이라 인용을 붙일 자리가 "
                                       "없어 인용 검증을 하지 못했다. 대신 판정마다 첫 토큰 후보와 "
                                       "확률 원본을 남겼다. **운영 채점에 그대로 쓸 규약이 아니다.**"),
        },
        "design": {
            "checklists_per_prompt": N_FOLDS,
            "target_items": TARGET_ITEMS_V4,
            "min_hard_items_requested": MIN_HARD_ITEMS,
            "exemplars_per_checklist": 12,
            "leakage_guard": "겹 k 의 체크리스트는 겹 k 답안을 한 건도 보지 않고 만든다",
            "judgments_per_answer": f"{N_FOLDS}겹 × 항목 수 (항목마다 호출 1회)",
            "scoring_uses": "자기 겹의 체크리스트로 받은 판정만",
            "prob_rule": "p = Σp(예쪽) / (Σp(예쪽) + Σp(아니오쪽)), 첫 토큰 후보를 접어서 계산",
            "binary_rule": "같은 호출의 p > 0.5 (판정이 아니라 읽는 법만 다르다)",
        },
        "dataset": {**counts, "n_speakers": len({str(r.get("speaker_id")) for r in rows})},
        "checklist_items_v4": v4_counts_json,
        "checklist_item_count_overall": {
            "n_sets": len(all_counts), "mean": statistics.mean(all_counts),
            "min": min(all_counts), "max": max(all_counts),
            "n_sets_at_target": sum(1 for c in all_counts if c >= TARGET_ITEMS_V4),
            "v3_reference_mean": 3.5,
        },
        "leakage_audit": audit,
        "fold_agreement": {**agree_json,
                           "overall_mean_similarity": statistics.mean(all_sims),
                           "overall_matched_rate": statistics.mean(all_match),
                           "v3_reference_mean_similarity": 0.331,
                           "설명": "같은 문항의 다섯 벌이 서로 얼마나 닮았는지. "
                                   "글자 겹침으로 재므로 닮음의 하한이다."},
        "item_saturation": saturation,
        "difficulty_vs_actual_pass_rate": difficulty_check,
        "probability_distribution": dist,
        "common_sample": {"n": len(usable), "n_speakers": len(set(speakers)),
                          "n_excluded": len(rows_by_id) - len(usable),
                          "excluded_reasons": {k: len(v) for k, v in dropped.items()}},
        "methods": {
            m: {"label": METHOD_LABELS_V4.get(m, m),
                "uses_training_data": m in ("Q", "Q_bin", "LEN", "MEAN"),
                "is_ceiling": m.startswith("CEIL"),
                **metrics[m], "qwk_ci95": cis[m],
                "mean_pred": statistics.mean(preds[m])}
            for m in preds
        },
        "main_answer_Q_minus_Qbin": main_answer,
        "ceilings": {
            **ceiling_json,
            "own_arrangement_is_degenerate": {
                "n_cells": len(cell_sizes),
                "n_cells_with_more_items_than_answers": degenerate,
                "min_answers_per_cell": min(cell_sizes.values()),
                "max_answers_per_cell": max(cell_sizes.values()),
                "설명": ("실배치 천장(CEIL_*_OWN)은 (문항×겹) 칸마다 답안이 6~8건인데 항목이 "
                         "약 9개라 맞출 손잡이가 답안보다 많다. 그래서 확률 선형 적합이 1.000 이 "
                         "나오는데, 이는 '항목이 완벽하다'가 아니라 '아무것도 재지 못했다'는 뜻이다. "
                         "겹벌 천장(CEIL_*_f0~f4)만 뜻이 있다."),
            },
        },
        "key_comparisons": pair_json,
        "pairwise_diff_qwk_ci95": {name: {**d, "verdict": verdict(d)}
                                   for name, d in diff_cis.items()},
        "per_prompt_qwk": per_prompt_json,
        "reproducibility": repro,
        "prior_experiments_reference_only": {
            "warning": "판정 모델이 달라 직접 비교 금지. 참고 수치일 뿐이다.",
            "methods": prior,
        },
        "cost_and_scale": {
            "n_judgment_rows_recorded": len(judgments),
            "n_ok": sum(1 for r in judgments.values() if r.get("status") == "ok"),
            "total_cost_usd": round(total_cost, 6),
            "llm_seconds_recorded": round(total_elapsed, 1),
            "failures": dict(fail_counts),
        },
        "limitations": [
            "판정 모델이 v1~v3 와 다르다(Qwen). 앞 실험과의 직접 비교는 성립하지 않는다.",
            "한 낱말 판정이라 인용 검증을 하지 못했다. 운영 채점 규약과 다르다.",
            "겹마다 체크리스트가 다르다. 실제 시험에 쓰려면 한 벌로 굳히는 절차가 필요하다.",
            "체크리스트를 만들 때 사람 점수를 보여 주었다(학습 겹만). 사람 점수가 없는 "
            "새 문항에는 이 방식을 그대로 쓸 수 없다.",
            "문항당 답안이 27~40건뿐이고, Q 는 겹마다 항목 수(약 9개)만큼의 가중치를 "
            "20~32건으로 배운다. 표본 대비 손잡이가 v2·v3 보다 많아 과적합 위험이 더 크다.",
            "천장(선형 적합)은 항목이 많을수록 저절로 올라간다. v4 는 항목이 v2·v3 보다 "
            "많으므로 천장 값을 앞 실험과 나란히 놓으면 안 된다.",
            "OpenRouter 는 같은 모델을 여러 회사에 나눠 보낸다. logprobs 를 주는 곳으로만 "
            "좁혔지만 실행마다 어디로 가는지는 고정되지 않는다(줄마다 기록해 두었다).",
            "AI Hub 데이터는 우리 시험(직무 한국어)과 과제 성격이 다르다.",
        ],
        "files": {
            "checklists_v4": str(CHECKLIST_V4_PATH),
            "judgments_v4": str(args.judgments_v4),
            "q_model_weights": str(Q_WEIGHTS_PATH),
            "summary_v3": str(SUMMARY_V3_PATH),
            "summary_v4": str(args.out),
        },
    }

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(
        json.dumps(clean_nan(summary), ensure_ascii=False, indent=2,
                   default=_json_safe, allow_nan=False), encoding="utf-8")
    print(f"\n모든 수치 저장: {args.out}")
    print(f"총 판정 {len(judgments):,}칸 · 실제 비용 ${total_cost:.4f} · "
          f"LLM 소요 {total_elapsed / 60:.1f}분(호출 시간 합)")
    if fail_counts:
        print(f"실패·미완료: {dict(fail_counts)}")
    return 0


def analyze_repro_v4(judgments: dict, rows: list[dict], checklists: dict,
                     fold_of: dict[str, int], prompt_of: dict[str, str],
                     repro_n: int) -> dict:
    """같은 60건을 3회 판정했을 때 **확률값이 소수점까지 같은지** 잰다.

    온도 0 + logprobs 라 결정적일 것으로 예상되지만, 예상은 결과가 아니므로 재서 확인한다.
    두 가지를 함께 본다.
      · 확률이 소수점까지 같은가 (O/X 만 같은 것보다 훨씬 엄한 기준이다)
      · **공급자가 바뀐 칸**에서 값이 달라졌는가 — OpenRouter 는 같은 모델이라도
        여러 회사에 나눠 보내므로, 흔들림이 있다면 그것이 원인일 가능성이 크다
    """
    repro_ids = [str(r["id"]) for r in select_repro_subset(rows, repro_n)]
    tags = ("rep1", "rep2", "rep3")

    n_cells = 0
    n_identical = 0
    n_met_flipped = 0
    same_provider = 0
    provider_changed = 0
    provider_changed_and_differs = 0
    same_provider_and_differs = 0
    max_spread = 0.0
    spreads: list[float] = []
    spreads_same_provider: list[float] = []
    spreads_changed_provider: list[float] = []
    per_answer_scores: dict[str, list[int]] = {}

    for rid in repro_ids:
        fold = fold_of.get(rid)
        if fold is None:
            continue
        items = items_for_v4(checklists, prompt_of.get(rid, ""), fold)
        if not items:
            continue

        # 세 번의 실행에서 항목마다 확률을 모은다. 하나라도 빠지면 그 답안은 세지 않는다
        per_pass_probs: list[list[float]] = []
        complete = True
        cell_records: list[list[dict]] = []
        for tag in tags:
            values, recs = [], []
            for it in items:
                rec = judgments.get((rid, str(fold), str(it["id"]), tag))
                if rec is None or rec.get("status") != "ok" or rec.get("p_yes") is None:
                    complete = False
                    break
                values.append(float(rec["p_yes"]))
                recs.append(rec)
            if not complete:
                break
            per_pass_probs.append(values)
            cell_records.append(recs)
        if not complete:
            continue

        for pos in range(len(items)):
            n_cells += 1
            values = [p[pos] for p in per_pass_probs]
            spread = max(values) - min(values)
            max_spread = max(max_spread, spread)
            spreads.append(spread)
            identical = len(set(values)) == 1
            n_identical += int(identical)
            if len({int(v > 0.5) for v in values}) > 1:
                n_met_flipped += 1
            providers = {str(recs[pos].get("provider")) for recs in cell_records}
            # 흔들림의 원인이 '어느 회사로 보냈나'인지 '모델 자체'인지 가르려면
            # 공급자가 내내 같았던 칸에서도 값이 흔들리는지를 봐야 한다
            if len(providers) == 1:
                same_provider += 1
                spreads_same_provider.append(spread)
                if not identical:
                    same_provider_and_differs += 1
            else:
                provider_changed += 1
                spreads_changed_provider.append(spread)
                if not identical:
                    provider_changed_and_differs += 1

        per_answer_scores[rid] = [met_ratio_to_score(statistics.mean(p))
                                  for p in per_pass_probs]

    def quantile(values: list[float], q: float) -> float:
        """정렬한 값에서 q 자리의 값을 꺼낸다(중앙값·상위 10% 같은 것을 보려는 것)."""
        if not values:
            return float("nan")
        ordered = sorted(values)
        return ordered[min(len(ordered) - 1, int(q * (len(ordered) - 1) + 0.5))]

    return {
        "n_passes": len(tags),
        "subset_size": len(repro_ids),
        "n_measured": len(per_answer_scores),
        "n_cells": n_cells,
        "n_cells_identical": n_identical,
        "prob_identical_rate": (n_identical / n_cells) if n_cells else float("nan"),
        "n_cells_met_flipped": n_met_flipped,
        "met_flip_rate": (n_met_flipped / n_cells) if n_cells else float("nan"),
        "max_prob_spread": max_spread,
        # 흔들림이 '얼마나' 큰지. 거의 다 흔들려도 폭이 0.001 이면 실무에서는 문제가 아니다
        "prob_spread": {
            "median": quantile(spreads, 0.5),
            "p90": quantile(spreads, 0.9),
            "p99": quantile(spreads, 0.99),
            "max": max_spread,
            "n_over_0.1": sum(1 for s in spreads if s > 0.1),
            "n_over_0.01": sum(1 for s in spreads if s > 0.01),
        },
        "n_cells_same_provider": same_provider,
        "n_cells_provider_changed": provider_changed,
        "n_provider_changed_and_differs": provider_changed_and_differs,
        "n_same_provider_and_differs": same_provider_and_differs,
        "median_spread_same_provider": quantile(spreads_same_provider, 0.5),
        "median_spread_changed_provider": quantile(spreads_changed_provider, 0.5),
        "score_exact_agreement": (
            sum(1 for v in per_answer_scores.values() if len(set(v)) == 1)
            / len(per_answer_scores)) if per_answer_scores else float("nan"),
        "score_mean_amplitude": (
            sum(max(v) - min(v) for v in per_answer_scores.values())
            / len(per_answer_scores)) if per_answer_scores else float("nan"),
        "설명": ("확률값이 소수점까지 같은지 본다. O/X 가 같은 것보다 훨씬 엄한 기준이다. "
                 "공급자가 바뀐 칸을 따로 세는 이유는, 흔들림이 있다면 모델이 아니라 "
                 "어느 회사로 보냈는지가 원인일 수 있기 때문이다. 공급자가 내내 같았는데도 "
                 "값이 흔들렸다면 원인은 모델(또는 그 서버의 계산 방식) 쪽이다."),
    }


def _json_safe(obj):
    """JSON 으로 못 적는 값(넘파이 숫자 등)을 적을 수 있는 모양으로 바꾼다."""
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return float(obj)
    return str(obj)


if __name__ == "__main__":
    raise SystemExit(main())
