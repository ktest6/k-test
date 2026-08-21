# -*- coding: utf-8 -*-
"""v1 네 방식과 v2 새 방식들을 **한 표에** 놓고 견준다.

■ 이번 실험의 질문 하나

8/9 실험에서 체크리스트 채점이 LLM 직접 채점에 크게 졌고, 원인은 결합 방식이 아니라
**항목 자체**였다 — 9문항 전부 항목 2개, 그 항목들이 들고 있는 정보의 천장이 QWK 0.693.
그래서 논문(RLCF, arXiv 2507.18624v2)의 후보 기반 생성으로 항목을 다시 뽑았다.

    → **그 천장이 실제로 올라갔는가?** 이것이 이번 분석의 핵심 질문이다.
      천장이 그대로면 항목을 늘려도 소용이 없다는 뜻이고, 올라갔는데 방식이 못 따라가면
      이번엔 결합 방식이 병목이라는 뜻이다. 둘은 완전히 다른 다음 걸음으로 이어진다.

■ 여기서 계산하는 것

  v1 (앞 실험 결과를 그대로 다시 읽는다. 다시 판정하지 않는다)
    A0 LLM 직접 채점(제로샷) · A1 퓨샷 · B v1 충족율×5 · C v1 이진+가중치 학습

  v2 이진 패스에서
    D  충족율 × 5                              (학습 없음)
    E  **중요도 가중** 충족율 × 5              (학습 없음) ← 논문 방식
    F  문항별 가중치 학습(릿지, out-of-fold)   ← v1 의 C 를 v2 항목으로

  v2 점수 패스에서
    G  항목 0~100 의 중요도 가중 평균 × 5      (학습 없음) ← 논문 방식
    H  0~100 벡터로 문항별 가중치 학습         (LLM 추가 호출 0회)

  덧붙임
    · ablation — D·E·F 를 **보편 항목 2개를 빼고** 다시 계산(보편 항목이 도움인가 잡음인가)
    · 천장   — v1·v2 각각 '충족 개수 기반 최적 사상'과 '정답을 보고 맞춘 선형' 두 가지
    · 기준선 — 학습 겹 평균(바닥), 글자 수만 보는 길이 기준선

■ 공정 규칙 (앞 실험과 똑같이 유지한다)

  · 한 방식에서라도 점수를 못 낸 답안은 **모든 방식에서 뺀다**
  · 학습을 쓰는 방식(A1·C·F·H)은 **out-of-fold 예측만** 쓴다
  · QWK + 화자 클러스터 부트스트랩 1000회 95% 신뢰구간 + 방식 간 차이 구간
  · **차이 구간이 0을 걸치면 개선이라고 쓰지 않는다**

■ 쓰는 법

    python analyze_v2.py             # 결과 요약 + results_summary_v2.json 저장
    python analyze_v2.py --self-test # 계산기만 예시 입력으로 점검(파일도 LLM도 안 건드림)
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from sklearn.linear_model import RidgeCV

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _lab_common import (  # noqa: E402
    JUDGE_MODEL,
    N_BOOTSTRAP,
    N_FOLDS,
    OUT_DIR,
    SCORE_LABELS,
    SEED,
    all_metrics,
    assign_folds,
    bootstrap_qwk_ci,
    enable_utf8_output,
    fmt,
    human_score,
    load_done,
    load_rows,
    print_table,
    prompt_key,
    qwk,
    select_repro_subset,
    verdict,
)
from analyze import (  # noqa: E402
    RIDGE_ALPHAS,
    clean_nan,
    compute_method_c,
    round_half_up,
)
from extra_baselines import baseline_length, baseline_mean  # noqa: E402
from gen_checklists import load_checklists  # noqa: E402
from gen_checklists_v2 import CHECKLIST_V2_PATH, load_checklists_v2  # noqa: E402
from run_experiment import DEFAULT_OUT  # noqa: E402
from run_experiment_v2 import DEFAULT_OUT_V2, ratio_to_score  # noqa: E402

#: 모든 수치를 기계가 읽을 수 있게 담아 두는 곳.
SUMMARY_V2_PATH = OUT_DIR / "results_summary_v2.json"
#: F·H 가 문항마다 배운 항목별 비중(=근거)을 남기는 곳.
FH_WEIGHTS_PATH = OUT_DIR / "fh_model_weights.json"

#: 방식 이름과 사람이 읽을 설명.
#: **이름에 하이픈을 쓰지 않는다** — 부트스트랩이 방식 쌍 이름을 "A-B" 로 만들어
#: 나중에 하이픈으로 다시 가르기 때문에, 이름 안에 하이픈이 있으면 짝을 잃는다.
METHOD_LABELS = {
    "A0": "A0 LLM 직접 채점(제로샷) [v1]",
    "A1": "A1 LLM 직접 채점(퓨샷 앵커) [v1]",
    "B": "B v1 체크리스트 충족율×5",
    "C": "C v1 체크리스트+가중치 학습",
    "D": "D v2 충족율×5",
    "E": "E v2 중요도 가중 충족율×5 (논문)",
    "F": "F v2 이진+문항별 가중치 학습",
    "G": "G v2 항목 0~100 중요도 가중평균×5 (논문)",
    "H": "H v2 0~100 벡터+가중치 학습",
    "D_noU": "D′ v2 충족율×5 (보편항목 제외)",
    "E_noU": "E′ v2 중요도 가중 (보편항목 제외)",
    "F_noU": "F′ v2 가중치 학습 (보편항목 제외)",
    "MEAN": "바닥선(학습겹 평균, 답안을 안 읽음)",
    "LEN": "길이 기준선(글자 수만)",
    "CEIL_V1_CNT": "천장 v1 이진(충족 개수·중앙값 사상 = 앞 실험 0.693)",
    "CEIL_V1_OPT": "천장 v1 이진(충족 개수·QWK 최대 사상)",
    "CEIL_V1_LIN": "천장 v1 이진(정답 보고 선형 적합)",
    "CEIL_V2_CNT": "천장 v2 이진(충족 개수·중앙값 사상)",
    "CEIL_V2_OPT": "천장 v2 이진(충족 개수·QWK 최대 사상)",
    "CEIL_V2_LIN": "천장 v2 이진(정답 보고 선형 적합)",
    "CEIL_V2_SCR": "천장 v2 0~100(정답 보고 선형 적합)",
}

#: 결과 JSON 에 반드시 함께 적는 '논문과 우리 조건의 차이'.
#: 이것을 빼면 우리 숫자가 논문 숫자와 같은 조건에서 나온 것처럼 읽힌다.
DIFFERENCES_FROM_PAPER = [
    "논문의 flexible scoring 은 항목마다 25회 샘플링해 평균을 쓴다. "
    "우리는 온도 0 · 1회 호출이라 '한 번 뽑은 값'이며, 25회 평균이 주는 "
    "부드러운 점수의 이점은 여기서 재현되지 않는다.",
    "논문의 체크리스트 생성 모델은 Qwen2.5-72B 급이고, 우리는 판정과 같은 "
    "gemini-3.1-flash-lite 다(생성과 판정에 같은 모델을 쓰는 것도 논문과 다르다).",
    "논문은 영어 지시-따르기 과제이고, 우리는 한국어 말하기 시험 문항 9종이다. "
    "우리 문항은 요구 사항이 대체로 둘(정보 + 이유·묘사)이라 애초에 항목이 적게 나온다.",
    "논문은 후보 응답으로 실제 모델 출력을 쓴다. 우리는 시험지 오염을 막으려고 "
    "실제 응시자 답안을 절대 쓰지 않고 지시문만 보고 지어낸 가상 답안 4개를 쓴다.",
    "논문의 보편 항목 2개는 중요도 합 100 이고 그 배분은 생성 모델이 정한다. "
    "우리는 문항마다 값이 달라지지 않도록 50/50 으로 고정했다.",
    "논문의 목적은 강화학습 보상 신호이고, 우리 목적은 사람 채점과의 등급 일치(QWK)다. "
    "같은 체크리스트라도 재는 자가 다르다.",
]


# ── 항목 벡터 만들기 ─────────────────────────────────────────────────────────
def included_items(entry: dict, exclude_universal: bool) -> list[dict]:
    """이 문항에서 점수 계산에 넣을 항목만 고른다.

    `exclude_universal=True` 면 보편 항목 2개를 뺀다. 보편 항목이 점수에 도움이 되는지
    잡음인지 확인하는 비교(ablation)를 위한 것이라, 표시(`universal`)만 보고 가른다.
    """
    items = entry.get("items", [])
    if exclude_universal:
        return [it for it in items if not it.get("universal")]
    return list(items)


def binary_vector(rec: dict, items: list[dict]) -> list[float]:
    """이진 판정 한 건을 항목 순서대로 0/1 로 늘어놓는다.

    판정이 없는 항목은 미충족(0)으로 본다 — 채점 서버의 규약과 같다.
    항목 순서를 체크리스트 파일 기준으로 고정하는 이유: 순서가 흔들리면
    배운 비중을 어느 항목의 것인지 짝지을 수 없게 된다.
    """
    got = {i["cid"]: i["met"] for i in rec.get("items", [])}
    return [float(got.get(str(it["id"]), 0)) for it in items]


def score_vector(rec: dict, items: list[dict]) -> list[float]:
    """점수 판정 한 건을 항목 순서대로 0~1 로 늘어놓는다(0~100 을 100 으로 나눈 값).

    0~1 로 줄여 두는 이유는 릿지 회귀의 규제가 값의 크기에 좌우되기 때문이다.
    0~100 을 그대로 넣으면 같은 규제 세기가 사실상 100배 약해진다.
    """
    got = {i["cid"]: i["score"] for i in rec.get("items", [])}
    return [float(got.get(str(it["id"]), 0)) / 100.0 for it in items]


def weighted_ratio(values: list[float], items: list[dict], use_importance: bool) -> float:
    """항목 값들(0~1)을 하나의 비율로 합친다.

    `use_importance=True` 면 LLM 이 매긴 중요도로 가중 평균한다(논문 방식),
    아니면 단순 평균이다. 중요도 합이 0이면 나눌 수 없어 단순 평균으로 물러난다.
    """
    if not values:
        return 0.0
    if not use_importance:
        return sum(values) / len(values)
    weights = [float(it.get("importance", 50)) for it in items]
    total = sum(weights)
    if total <= 0:
        return sum(values) / len(values)
    return sum(w * v for w, v in zip(weights, values)) / total


# ── 학습을 쓰는 방식 (F·H) ───────────────────────────────────────────────────
def learn_per_prompt(vec_by_id: dict[str, list[float]], prompt_of: dict[str, str],
                     rows_by_id: dict, fold_of: dict[str, int],
                     feature_names: dict[str, list[str]], label: str):
    """문항마다 항목별 가중치를 배워 0~5 를 예측한다(out-of-fold).

    v1 의 C(`analyze.compute_method_c`)와 **같은 절차**다. 다른 것은 재료뿐이다 —
    C 는 v1 항목의 0/1, F 는 v2 항목의 0/1, H 는 v2 항목의 0~100 을 쓴다.
    절차를 하나로 맞춰 두어야 "재료가 좋아졌는가"만 남는다.

    학습은 문항마다 따로, **학습 겹에서만** 한다. 규제 세기(alpha)도 학습 겹 안에서
    고른다. 배울 것이 너무 적거나 사람 점수가 전부 같으면 학습 겹의 평균으로 답한다.

    돌려주는 값은 (답안 id -> 예측 점수, 문항별로 배운 것)이다.
    배운 비중을 함께 돌려주는 이유: 점수만 있고 근거가 없으면 이 프로젝트에서는 결함이다.
    """
    preds: dict[str, int] = {}
    learned: dict[str, dict] = {}

    by_prompt: dict[str, list[str]] = defaultdict(list)
    for rid in vec_by_id:
        by_prompt[prompt_of[rid]].append(rid)

    for pkey, ids in sorted(by_prompt.items()):
        ids.sort()
        names = feature_names.get(pkey, [])
        if not names:
            continue
        X_all = np.array([vec_by_id[r] for r in ids], dtype=float)
        y_all = np.array([human_score(rows_by_id[r]) for r in ids], dtype=float)
        folds = np.array([fold_of[r] for r in ids])

        fold_info = []
        for k in range(N_FOLDS):
            test_mask = folds == k
            train_mask = ~test_mask
            n_train = int(train_mask.sum())
            if test_mask.sum() == 0:
                continue
            if n_train < 5 or float(np.std(y_all[train_mask])) < 1e-9:
                fallback = round_half_up(float(np.mean(y_all[train_mask]))) if n_train else 0
                for rid in np.array(ids)[test_mask]:
                    preds[str(rid)] = fallback
                fold_info.append({"fold": k, "n_train": n_train, "alpha": None,
                                  "note": "학습 표본이 모자라 학습 겹 평균으로 대체"})
                continue

            model = RidgeCV(alphas=RIDGE_ALPHAS)
            model.fit(X_all[train_mask], y_all[train_mask])
            for rid, value in zip(np.array(ids)[test_mask], model.predict(X_all[test_mask])):
                preds[str(rid)] = round_half_up(float(value))

            fold_info.append({
                "fold": k,
                "n_train": n_train,
                "alpha": float(model.alpha_),
                "intercept": round(float(model.intercept_), 4),
                # 항목별로 배운 비중 = 이 항목을 충족하면 점수가 몇 점 오르는가
                "coefficients": {cid: round(float(c), 4)
                                 for cid, c in zip(names, model.coef_)},
            })

        learned[pkey] = {"method": label, "item_ids": names,
                         "n_rows": len(ids), "folds": fold_info}
    return preds, learned


# ── 천장 (실제 채점에 쓸 수 없는 낙관적 상한) ────────────────────────────────
def _met_cells(ids: list[str], vec_by_id: dict[str, list[float]],
               prompt_of: dict[str, str]) -> dict[str, tuple[str, int]]:
    """답안마다 '어느 문항의 충족 개수 몇 칸에 속하는가'를 정한다.

    충족 개수 기반 천장은 이 칸마다 점수를 하나씩 정하는 문제로 바뀐다.
    (점수 패스처럼 값이 0~1 인 경우에는 반올림한 합이 칸 번호가 된다)
    """
    return {rid: (prompt_of[rid], int(round(sum(vec_by_id[rid])))) for rid in ids}


def ceiling_by_met_count(ids: list[str], rows_by_id: dict,
                         vec_by_id: dict[str, list[float]],
                         prompt_of: dict[str, str]) -> dict[str, int]:
    """충족 **개수**를 문항별 중앙값으로 점수에 사상한다(v1 과 같은 계산).

    같은 충족 개수를 받은 무리의 사람 점수 중 중앙값을 그 칸의 답으로 삼는다.
    v1(`extra_baselines.py`)이 "체크리스트 상한"이라고 부른 값이 바로 이것이라,
    앞 실험의 0.693 과 직접 이어 붙이려면 이 계산이 그대로 필요하다.

    다만 **중앙값은 QWK 를 최대로 만드는 답이 아니다.** 중앙값은 '빗나간 칸 수'를
    최소로 만드는 값이고 QWK 는 '빗나간 칸 수의 제곱'을 벌하므로 서로 다르다.
    실제로 자체 점검에서 이 사상이 단순 충족율보다 낮은 QWK 를 내는 경우가 나왔다.
    그래서 진짜 천장은 아래 `ceiling_by_met_count_optimized` 로 따로 낸다.
    """
    preds: dict[str, int] = {}
    cells = _met_cells(ids, vec_by_id, prompt_of)
    bucket: dict[tuple[str, int], list[int]] = defaultdict(list)
    for rid in ids:
        bucket[cells[rid]].append(human_score(rows_by_id[rid]))
    table = {cell: round_half_up(float(np.median(scores)))
             for cell, scores in bucket.items()}
    for rid in ids:
        preds[rid] = table[cells[rid]]
    return preds


def ceiling_by_met_count_optimized(ids: list[str], rows_by_id: dict,
                                   vec_by_id: dict[str, list[float]],
                                   prompt_of: dict[str, str],
                                   n_items_of: dict[str, int],
                                   max_rounds: int = 30) -> dict[str, int]:
    """충족 개수 → 점수 사상을 **QWK 가 가장 높아지도록** 직접 찾는다(진짜 천장).

    왜 필요한가: 중앙값 사상은 QWK 기준으로 최적이 아니라서, 그것을 '천장'이라 부르면
    실제 방식이 천장을 넘어서는 이상한 일이 생긴다(자체 점검에서 실제로 났다).

    찾는 방법(한 칸씩 고쳐 가기):
      ① 출발점 두 개를 준비한다 — 중앙값 사상과, 그냥 충족율×5 사상.
         충족율×5 도 '개수만 쓰는 사상'이라 이 공간 안에 있다. 두 곳에서 출발해
         더 좋은 쪽을 택하면 **천장이 실제 방식보다 낮아지는 일**이 없다.
      ② 칸(문항 × 충족 개수)을 하나씩 돌며 0~5 를 다 넣어 보고 전체 QWK 가
         가장 높아지는 값으로 바꾼다. 한 바퀴 돌아 아무것도 안 바뀌면 멈춘다.

    무작위를 쓰지 않으므로 몇 번을 돌려도 같은 답이 나온다.
    정답을 다 보고 고르는 값이라 실제 채점에는 쓸 수 없다(낙관적 상한).
    """
    cells = _met_cells(ids, vec_by_id, prompt_of)
    truth = [human_score(rows_by_id[rid]) for rid in ids]
    cell_list = sorted({cells[rid] for rid in ids})

    def score_of(table: dict) -> float:
        return qwk([table[cells[rid]] for rid in ids], truth)

    # ① 출발점 두 개
    median_table = {}
    bucket: dict[tuple[str, int], list[int]] = defaultdict(list)
    for rid in ids:
        bucket[cells[rid]].append(human_score(rows_by_id[rid]))
    for cell, scores in bucket.items():
        median_table[cell] = round_half_up(float(np.median(scores)))
    ratio_table = {cell: ratio_to_score(cell[1] / max(1, n_items_of.get(cell[0], 1)))
                   for cell in cell_list}

    best_table, best_value = None, -2.0
    for start in (median_table, ratio_table):
        table = dict(start)
        value = score_of(table)
        # ② 한 칸씩 고쳐 가기. 좋아지지 않으면 그 자리를 지킨다
        for _ in range(max_rounds):
            improved = False
            for cell in cell_list:
                current = table[cell]
                for candidate in SCORE_LABELS:
                    if candidate == current:
                        continue
                    table[cell] = candidate
                    trial = score_of(table)
                    if trial > value + 1e-12:
                        value, current, improved = trial, candidate, True
                    table[cell] = current
            if not improved:
                break
        if value > best_value:
            best_table, best_value = dict(table), value

    return {rid: best_table[cells[rid]] for rid in ids}


def ceiling_by_linear_fit(ids: list[str], rows_by_id: dict,
                          vec_by_id: dict[str, list[float]],
                          prompt_of: dict[str, str]) -> dict[str, int]:
    """항목 벡터 **전체**를 정답을 보고 가장 잘 맞게 선형으로 적합한다(낙관적 상한).

    개수 기반 천장과 다른 점: 개수 천장은 "몇 개 충족했나"만 쓰고, 이쪽은 "어느 항목을
    충족했나"까지 다 쓴다. 그래서 항목이 들고 있는 정보의 상한에 더 가깝다.

    **주의해서 읽을 것**: 항목이 많아질수록 이 값은 저절로 올라간다(맞출 손잡이가
    늘어나므로). v2 항목이 v1 보다 많으니 v1·v2 천장을 나란히 볼 때 이 점을 감안해야 한다.
    그래서 개수 기반 천장(손잡이 하나)도 함께 낸다.

    적합에는 최소제곱(lstsq)을 쓴다. 항목끼리 겹쳐서 해가 하나로 정해지지 않을 때도
    lstsq 는 가장 작은 해를 골라 주므로 계산이 터지지 않는다.
    """
    preds: dict[str, int] = {}
    by_prompt: dict[str, list[str]] = defaultdict(list)
    for rid in ids:
        by_prompt[prompt_of[rid]].append(rid)

    for _, group in by_prompt.items():
        group = sorted(group)
        X = np.array([vec_by_id[r] for r in group], dtype=float)
        # 절편(모두 1인 칸)을 붙인다. 없으면 직선이 원점을 지나야 해서 손해를 본다
        X = np.hstack([X, np.ones((len(group), 1))])
        y = np.array([human_score(rows_by_id[r]) for r in group], dtype=float)
        beta, *_ = np.linalg.lstsq(X, y, rcond=None)
        for rid, value in zip(group, X @ beta):
            preds[rid] = round_half_up(float(value))
    return preds


# ── 재현성 ───────────────────────────────────────────────────────────────────
def analyze_repro_v2(judgments: dict, repro_ids: list[str], checklists_v2: dict,
                     rows_by_id: dict) -> dict:
    """같은 60건을 3회 판정했을 때 두 패스가 각각 얼마나 흔들리는지 잰다.

    관전 포인트: **0~100 점 패스가 이진 패스보다 흔들릴 가능성이 크다.**
    이진은 답이 두 개뿐이라 어지간해서는 같은 쪽으로 떨어지지만, 0~100 은 답이 101개라
    조금만 달라져도 값이 달라진다. 그 차이가 최종 점수까지 번지는지가 이번 측정의 요점이다.

    재는 것:
      · 완전일치율 — 3회 최종 점수(0~5)가 전부 같은 답안의 비율
      · 평균 진폭  — 3회 중 최고와 최저의 차이
      · 항목 뒤집힘율 — 항목 하나의 판정이 3회 내내 같았는지
        (이진은 0/1 이 달라진 비율, 점수는 0~100 값이 달라진 비율과 평균 진폭)
    """
    passes = ("rep1", "rep2", "rep3")
    out: dict = {"n_passes": len(passes), "subset_size": len(repro_ids), "methods": {}}

    def stability(per_item: dict[str, list[int]]) -> dict:
        if not per_item:
            return {"n": 0, "exact_agreement": float("nan"),
                    "mean_amplitude": float("nan"), "mean_stdev": float("nan")}
        amplitudes = [max(v) - min(v) for v in per_item.values()]
        stdevs = [statistics.pstdev(v) for v in per_item.values()]
        same = sum(1 for v in per_item.values() if len(set(v)) == 1)
        return {"n": len(per_item),
                "exact_agreement": same / len(per_item),
                "mean_amplitude": sum(amplitudes) / len(amplitudes),
                "max_amplitude": max(amplitudes),
                "mean_stdev": sum(stdevs) / len(stdevs)}

    # ── 이진 패스: D(단순 충족율)와 E(중요도 가중) 둘 다 본다 ─────────────
    per_d: dict[str, list[int]] = {}
    per_e: dict[str, list[int]] = {}
    cell_total, cell_flipped = 0, 0
    for rid in repro_ids:
        recs = [judgments.get((rid, "B2", p)) for p in passes]
        if any(r is None or r.get("status") != "ok" for r in recs):
            continue
        entry = checklists_v2.get(prompt_key(rows_by_id[rid].get("prompt") or ""), {})
        items = included_items(entry, exclude_universal=False)
        vectors = [binary_vector(r, items) for r in recs]
        per_d[rid] = [ratio_to_score(weighted_ratio(v, items, False)) for v in vectors]
        per_e[rid] = [ratio_to_score(weighted_ratio(v, items, True)) for v in vectors]
        # 항목 한 칸이 3회 내내 같은 판정이었는지 센다
        for pos in range(len(items)):
            cell_total += 1
            if len({v[pos] for v in vectors}) > 1:
                cell_flipped += 1

    out["methods"]["D"] = stability(per_d)
    out["methods"]["E"] = stability(per_e)
    out["binary_cell_flip"] = {
        "n_cells": cell_total, "n_flipped": cell_flipped,
        "flip_rate": (cell_flipped / cell_total) if cell_total else float("nan"),
        "설명": "이진 패스에서 항목 한 칸의 0/1 이 3회 중 한 번이라도 달랐으면 뒤집힘 1건",
    }

    # ── 점수 패스: G(중요도 가중 평균) ───────────────────────────────────
    per_g: dict[str, list[int]] = {}
    s_cell_total, s_cell_changed = 0, 0
    s_amplitudes: list[float] = []
    for rid in repro_ids:
        recs = [judgments.get((rid, "S2", p)) for p in passes]
        if any(r is None or r.get("status") != "ok" for r in recs):
            continue
        entry = checklists_v2.get(prompt_key(rows_by_id[rid].get("prompt") or ""), {})
        items = included_items(entry, exclude_universal=False)
        vectors = [score_vector(r, items) for r in recs]
        per_g[rid] = [ratio_to_score(weighted_ratio(v, items, True)) for v in vectors]
        for pos in range(len(items)):
            s_cell_total += 1
            values = [v[pos] * 100.0 for v in vectors]
            s_amplitudes.append(max(values) - min(values))
            if len(set(values)) > 1:
                s_cell_changed += 1

    out["methods"]["G"] = stability(per_g)
    out["score_cell_flip"] = {
        "n_cells": s_cell_total, "n_changed": s_cell_changed,
        "change_rate": (s_cell_changed / s_cell_total) if s_cell_total else float("nan"),
        "mean_amplitude_0to100": (sum(s_amplitudes) / len(s_amplitudes))
                                 if s_amplitudes else float("nan"),
        "설명": "점수 패스에서 항목 한 칸의 0~100 값이 3회 중 한 번이라도 달랐으면 변동 1건",
    }
    return out


# ── 자체 점검 ────────────────────────────────────────────────────────────────
def self_test() -> int:
    """계산기들이 맞게 도는지 답을 아는 예시로 확인한다.

    채점 코드는 눈으로 훑어서는 맞는지 알 수 없다. 그래서 값을 아는 입력을 넣어
    결과를 직접 본다(네트워크도 파일도 건드리지 않는다).
    """
    ok = True
    rows = []

    def check(label, got, want, tol=1e-9):
        nonlocal ok
        passed = abs(float(got) - float(want)) < tol
        ok &= passed
        rows.append([label, f"{got}", f"{want}", "통과" if passed else "실패"])

    print("=== 계산기 자체 점검 (analyze_v2) ===")

    items = [
        {"id": "1", "question": "가", "importance": 90, "universal": False},
        {"id": "2", "question": "나", "importance": 10, "universal": False},
        {"id": "U1", "question": "보편1", "importance": 50, "universal": True},
        {"id": "U2", "question": "보편2", "importance": 50, "universal": True},
    ]
    entry = {"items": items}

    # ① 보편 항목 빼기
    check("보편 제외 시 항목 수", len(included_items(entry, True)), 2)
    check("보편 포함 시 항목 수", len(included_items(entry, False)), 4)

    # ② 이진 벡터 — 판정이 없는 항목은 0으로 본다
    rec = {"items": [{"cid": "1", "met": 1}, {"cid": "U1", "met": 1}]}
    check("이진 벡터 합(4항목 중 2개 충족)", sum(binary_vector(rec, items)), 2.0)

    # ③ 중요도 가중 — 중요한 항목만 맞힌 쪽이 더 높아야 한다
    only_important = weighted_ratio([1.0, 0.0], items[:2], True)     # 90/(90+10)
    only_trivial = weighted_ratio([0.0, 1.0], items[:2], True)       # 10/100
    check("중요도 가중(중요 항목만 충족)", only_important, 0.9)
    check("중요도 가중(사소 항목만 충족)", only_trivial, 0.1)
    check("단순 평균은 둘이 같다", weighted_ratio([1.0, 0.0], items[:2], False),
          weighted_ratio([0.0, 1.0], items[:2], False))

    # ④ 0~100 벡터는 100 으로 나눠 0~1 로 들어온다
    srec = {"items": [{"cid": "1", "score": 80}, {"cid": "2", "score": 40}]}
    check("점수 벡터 첫 칸", score_vector(srec, items[:2])[0], 0.8)

    # ⑤ 비율 → 0~5 (0.5 는 위로)
    got = [ratio_to_score(v) for v in (0.0, 0.1, 0.5, 0.9, 1.0)]
    rows.append(["비율→점수 [0, .1, .5, .9, 1]", str(got), "[0, 1, 3, 5, 5]",
                 "통과" if got == [0, 1, 3, 5, 5] else "실패"])
    ok &= got == [0, 1, 3, 5, 5]

    # ⑥ 천장은 실제 방식보다 낮을 수 없다(정답을 보고 맞추므로)
    ids = [f"R{i:03d}" for i in range(40)]
    rows_by_id = {rid: {"id": rid, "evals": {"content": i % 6}}
                  for i, rid in enumerate(ids)}
    prompt_of = {rid: "P" for rid in ids}
    vec = {rid: [1.0 if (i % 6) >= 3 else 0.0, float(i % 2)] for i, rid in enumerate(ids)}
    truth = [rows_by_id[r]["evals"]["content"] for r in ids]
    ceil_opt = ceiling_by_met_count_optimized(ids, rows_by_id, vec, prompt_of, {"P": 2})
    ceil_med = ceiling_by_met_count(ids, rows_by_id, vec, prompt_of)
    ceil_lin = ceiling_by_linear_fit(ids, rows_by_id, vec, prompt_of)
    plain = [ratio_to_score(sum(vec[r]) / 2) for r in ids]
    q_plain = qwk(plain, truth)
    q_med = qwk([ceil_med[r] for r in ids], truth)
    q_opt = qwk([ceil_opt[r] for r in ids], truth)
    q_lin = qwk([ceil_lin[r] for r in ids], truth)
    # 진짜 천장은 '개수만 쓰는 어떤 방식'보다도 낮을 수 없어야 한다
    rows.append(["천장(개수·QWK최대) ≥ 그냥 충족율", f"{q_opt:.3f} vs {q_plain:.3f}",
                 "천장이 크거나 같다", "통과" if q_opt >= q_plain - 1e-9 else "실패"])
    ok &= q_opt >= q_plain - 1e-9
    rows.append(["천장(개수·QWK최대) ≥ 천장(개수·중앙값)", f"{q_opt:.3f} vs {q_med:.3f}",
                 "최적화한 쪽이 크거나 같다", "통과" if q_opt >= q_med - 1e-9 else "실패"])
    ok &= q_opt >= q_med - 1e-9
    rows.append(["천장(선형) ≥ 천장(개수·중앙값)", f"{q_lin:.3f} vs {q_med:.3f}",
                 "선형이 크거나 같다(정보를 더 씀)",
                 "통과" if q_lin >= q_med - 1e-9 else "실패"])
    ok &= q_lin >= q_med - 1e-9

    print_table(["항목", "나온 값", "기대", "판정"], rows)
    print("\n" + ("모두 통과" if ok else "실패한 항목이 있다"))
    return 0 if ok else 1


# ── 실행 ─────────────────────────────────────────────────────────────────────
def main() -> int:  # noqa: C901  (표를 여러 개 그리느라 길다)
    enable_utf8_output()
    ap = argparse.ArgumentParser(description="v1 네 방식과 v2 새 방식들을 한 표에서 견준다")
    ap.add_argument("--judgments-v1", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--judgments-v2", type=Path, default=DEFAULT_OUT_V2)
    ap.add_argument("--out", type=Path, default=SUMMARY_V2_PATH)
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
    checklists_v1 = load_checklists()
    checklists_v2 = load_checklists_v2()
    j1 = load_done(args.judgments_v1)
    j2 = load_done(args.judgments_v2)
    prompt_of = {rid: prompt_key(r.get("prompt") or "") for rid, r in rows_by_id.items()}

    print("=== 표본 ===")
    print_table(["단계", "건수"], [[k, v] for k, v in counts.items()])
    print(f"화자 {len({str(r.get('speaker_id')) for r in rows})}명 · "
          f"겹: 화자 단위 {N_FOLDS}겹 · 겹을 넘나든 화자 {diag['speaker_leak_count']}명")

    # 체크리스트 항목 수 비교 — 이번 실험의 출발점
    print("\n=== 체크리스트 항목 수 v1 vs v2 ===")
    item_rows = []
    for pkey in sorted(checklists_v2):
        e1, e2 = checklists_v1.get(pkey, {}), checklists_v2[pkey]
        task = [it for it in e2.get("items", []) if not it.get("universal")]
        univ = [it for it in e2.get("items", []) if it.get("universal")]
        imps = [it["importance"] for it in task]
        item_rows.append([pkey, (e2.get("prompt") or "")[:24], len(e1.get("items", [])),
                          len(task), len(univ), len(task) + len(univ),
                          f"{min(imps)}~{max(imps)}" if imps else "-"])
    print_table(["문항", "지시문", "v1", "v2 과제", "v2 보편", "v2 합계", "중요도 폭"], item_rows)

    # ── v1 방식 (앞 실험 결과를 그대로 읽는다) ───────────────────────────────
    main1 = {(rid, m): rec for (rid, m, p), rec in j1.items() if p == "main"}
    records_b1 = {rid: rec for (rid, m), rec in main1.items() if m == "B"}
    c_preds, _ = compute_method_c(records_b1, rows_by_id, fold_of, checklists_v1)

    # ── v2 판정 읽기 ─────────────────────────────────────────────────────────
    main2 = {(rid, m): rec for (rid, m, p), rec in j2.items() if p == "main"}
    rec_b2 = {rid: rec for (rid, m), rec in main2.items()
              if m == "B2" and rec.get("status") == "ok"}
    rec_s2 = {rid: rec for (rid, m), rec in main2.items()
              if m == "S2" and rec.get("status") == "ok"}
    print(f"\nv2 판정: 이진 {len(rec_b2)}건 · 점수 {len(rec_s2)}건")

    # 문항별 항목 목록(보편 포함/제외 두 벌)을 미리 만들어 둔다
    items_full = {p: included_items(e, False) for p, e in checklists_v2.items()}
    items_nou = {p: included_items(e, True) for p, e in checklists_v2.items()}

    # 학습을 쓰는 방식(F·H)은 **v2 판정이 성공한 전체**에서 배우고 out-of-fold 로만 답한다
    vec_bin = {rid: binary_vector(rec, items_full[prompt_of[rid]])
               for rid, rec in rec_b2.items() if prompt_of[rid] in items_full}
    vec_bin_nou = {rid: binary_vector(rec, items_nou[prompt_of[rid]])
                   for rid, rec in rec_b2.items() if prompt_of[rid] in items_nou}
    vec_scr = {rid: score_vector(rec, items_full[prompt_of[rid]])
               for rid, rec in rec_s2.items() if prompt_of[rid] in items_full}

    names_full = {p: [str(it["id"]) for it in v] for p, v in items_full.items()}
    names_nou = {p: [str(it["id"]) for it in v] for p, v in items_nou.items()}

    f_preds, f_learned = learn_per_prompt(vec_bin, prompt_of, rows_by_id, fold_of,
                                          names_full, "F")
    f_nou_preds, _ = learn_per_prompt(vec_bin_nou, prompt_of, rows_by_id, fold_of,
                                      names_nou, "F_noU")
    h_preds, h_learned = learn_per_prompt(vec_scr, prompt_of, rows_by_id, fold_of,
                                          names_full, "H")
    Path(FH_WEIGHTS_PATH).parent.mkdir(parents=True, exist_ok=True)
    Path(FH_WEIGHTS_PATH).write_text(
        json.dumps({"F": f_learned, "H": h_learned}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    print(f"F·H 가 문항별 항목 비중을 배웠다(LLM 호출 0회). 근거 저장: {FH_WEIGHTS_PATH}")

    # ── 공통 표본 ────────────────────────────────────────────────────────────
    usable, dropped = [], defaultdict(list)
    for rid in sorted(rows_by_id):
        reasons = []
        for method in ("A0", "A1", "B"):
            rec = main1.get((rid, method))
            if rec is None:
                reasons.append(f"{method}:미실행")
            elif rec.get("status") != "ok":
                reasons.append(f"{method}:{rec.get('status')}")
        if rid not in c_preds:
            reasons.append("C:예측없음")
        for name, store in (("B2", rec_b2), ("S2", rec_s2)):
            if rid not in store:
                rec = main2.get((rid, name))
                reasons.append(f"{name}:{'미실행' if rec is None else rec.get('status')}")
        if rid not in f_preds:
            reasons.append("F:예측없음")
        if rid not in h_preds:
            reasons.append("H:예측없음")
        if reasons:
            dropped[" / ".join(reasons)].append(rid)
        else:
            usable.append(rid)

    print(f"\n=== 공통 표본: {len(usable)}건 "
          f"(대상 {len(rows_by_id)}건 중 {len(rows_by_id) - len(usable)}건 제외) ===")
    if dropped:
        print("  제외 내역 (한 방식에서라도 점수를 못 낸 답안은 모든 방식에서 뺀다)")
        for reason, ids in sorted(dropped.items(), key=lambda kv: -len(kv[1])):
            print(f"    {len(ids):4d}건  {reason}  ({', '.join(i[-16:] for i in ids[:3])})")
    if len(usable) < 10:
        print("\n[중단] 공통 표본이 10건 미만이라 성적을 계산하지 않는다.")
        return 1

    truth = [human_score(rows_by_id[rid]) for rid in usable]
    speakers = [str(rows_by_id[rid].get("speaker_id")) for rid in usable]

    # ── 점수 만들기 ──────────────────────────────────────────────────────────
    def combine(rid: str, vectors: dict, item_map: dict, use_importance: bool) -> int:
        """한 답안의 항목 값들을 하나의 0~5 점으로 합친다."""
        items = item_map[prompt_of[rid]]
        return ratio_to_score(weighted_ratio(vectors[rid], items, use_importance))

    preds = {
        "A0": [int(main1[(rid, "A0")]["pred"]) for rid in usable],
        "A1": [int(main1[(rid, "A1")]["pred"]) for rid in usable],
        "B": [int(main1[(rid, "B")]["pred"]) for rid in usable],
        "C": [int(c_preds[rid]) for rid in usable],
        "D": [combine(rid, vec_bin, items_full, False) for rid in usable],
        "E": [combine(rid, vec_bin, items_full, True) for rid in usable],
        "F": [int(f_preds[rid]) for rid in usable],
        "G": [combine(rid, vec_scr, items_full, True) for rid in usable],
        "H": [int(h_preds[rid]) for rid in usable],
        # ablation — 보편 항목 2개를 빼고 다시
        "D_noU": [combine(rid, vec_bin_nou, items_nou, False) for rid in usable],
        "E_noU": [combine(rid, vec_bin_nou, items_nou, True) for rid in usable],
        "F_noU": [int(f_nou_preds[rid]) for rid in usable],
    }

    # 기준선 — 같은 표본·같은 겹에서 잰다
    mean_p = baseline_mean(usable, rows_by_id, fold_of)
    len_p = baseline_length(usable, rows_by_id, fold_of)
    preds["MEAN"] = [mean_p[rid] for rid in usable]
    preds["LEN"] = [len_p[rid] for rid in usable]

    # 천장 — v1·v2 를 **같은 계산기**로 잰다(그래야 0.693 과 나란히 놓을 수 있다)
    vec_bin_v1 = {}
    v1_items = {p: e.get("items", []) for p, e in checklists_v1.items()}
    for rid in usable:
        rec = records_b1[rid]
        got = {i["cid"]: i["met"] for i in rec.get("items", [])}
        vec_bin_v1[rid] = [float(got.get(str(it["id"]), 0))
                           for it in v1_items[prompt_of[rid]]]
    n_items_v1 = {p: len(v) for p, v in v1_items.items()}
    n_items_v2 = {p: len(v) for p, v in items_full.items()}
    ceilings = {
        "CEIL_V1_CNT": ceiling_by_met_count(usable, rows_by_id, vec_bin_v1, prompt_of),
        "CEIL_V1_OPT": ceiling_by_met_count_optimized(usable, rows_by_id, vec_bin_v1,
                                                      prompt_of, n_items_v1),
        "CEIL_V1_LIN": ceiling_by_linear_fit(usable, rows_by_id, vec_bin_v1, prompt_of),
        "CEIL_V2_CNT": ceiling_by_met_count(usable, rows_by_id, vec_bin, prompt_of),
        "CEIL_V2_OPT": ceiling_by_met_count_optimized(usable, rows_by_id, vec_bin,
                                                      prompt_of, n_items_v2),
        "CEIL_V2_LIN": ceiling_by_linear_fit(usable, rows_by_id, vec_bin, prompt_of),
        "CEIL_V2_SCR": ceiling_by_linear_fit(usable, rows_by_id, vec_scr, prompt_of),
    }
    for name, table in ceilings.items():
        preds[name] = [table[rid] for rid in usable]

    # ── 성적과 신뢰구간 ──────────────────────────────────────────────────────
    metrics = {m: all_metrics(p, truth) for m, p in preds.items()}
    print(f"\n부트스트랩 {args.bootstrap}회 계산 중 (화자를 통째로 다시 뽑는다)...")
    cis, diff_cis = bootstrap_qwk_ci(preds, truth, speakers, args.bootstrap, SEED)

    def row_for(m: str) -> list:
        return [METHOD_LABELS[m], fmt(metrics[m]["qwk"]),
                f"[{fmt(cis[m]['lo'])}, {fmt(cis[m]['hi'])}]",
                fmt(metrics[m]["spearman"]),
                f"{metrics[m]['exact']:.1%}", f"{metrics[m]['within1']:.1%}",
                f"{statistics.mean(preds[m]):.2f}"]

    headers = ["방식", "QWK", "95% 신뢰구간", "스피어만", "정확일치", "±1 이내", "평균예측"]
    print(f"\n{'=' * 86}")
    print(f"  ① 방식별 성적 — 같은 겹의 out-of-fold 예측만 (표본 {len(usable)}건 · "
          f"화자 {len(set(speakers))}명)")
    print("=" * 86)
    print_table(headers, [row_for(m) for m in
                          ("A0", "A1", "B", "C", "D", "E", "F", "G", "H")])
    print(f"  참고: 사람 점수 평균 {statistics.mean(truth):.2f} · "
          f"분포 {dict(sorted(Counter(truth).items()))}")

    print(f"\n{'=' * 86}\n  ② 보편 항목을 빼면 (ablation)\n{'=' * 86}")
    print_table(headers, [row_for(m) for m in ("D", "D_noU", "E", "E_noU", "F", "F_noU")])
    for a, b in (("D", "D_noU"), ("E", "E_noU"), ("F", "F_noU")):
        d = diff_cis.get(f"{a}-{b}") or diff_cis.get(f"{b}-{a}")
        print(f"    {a} − {b}: {d['mean']:+.3f} [{d['lo']:+.3f}, {d['hi']:+.3f}] → {verdict(d)}")

    print(f"\n{'=' * 86}\n  ③ 기준선과 천장 — 이번 실험의 핵심 질문\n{'=' * 86}")
    print_table(headers, [row_for(m) for m in
                          ("MEAN", "LEN", "CEIL_V1_CNT", "CEIL_V1_OPT", "CEIL_V1_LIN",
                           "CEIL_V2_CNT", "CEIL_V2_OPT", "CEIL_V2_LIN", "CEIL_V2_SCR")])
    print("  ※ 천장은 정답을 보고 맞춘 값이라 실제 채점에 쓸 수 없다. "
          "항목이 많을수록 저절로 올라가므로 v1·v2 를 견줄 때 감안해야 한다.")
    print("  ※ '중앙값 사상'은 앞 실험(0.693)과 이어 붙이려고 남긴 v1 계산이고, "
          "QWK 기준의 진짜 천장은 'QWK 최대 사상'이다.")

    # 꼭 봐야 할 비교 — v1 최고(A1)와 v1 천장 대비
    print(f"\n{'=' * 86}\n  ④ 방식 간 차이가 우연인가 (화자 다시뽑기 "
          f"{args.bootstrap}회, 95% 구간)\n{'=' * 86}")
    key_pairs = [
        ("D", "B"), ("E", "B"), ("E", "D"), ("F", "C"), ("G", "E"), ("H", "F"),
        ("G", "A1"), ("H", "A1"), ("F", "A1"), ("E", "LEN"), ("G", "LEN"),
        ("CEIL_V2_CNT", "CEIL_V1_CNT"), ("CEIL_V2_OPT", "CEIL_V1_OPT"),
        ("CEIL_V2_LIN", "CEIL_V1_LIN"),
    ]
    table = []
    for a, b in key_pairs:
        d = diff_cis.get(f"{a}-{b}") or diff_cis.get(f"{b}-{a}")
        # 저장된 쌍의 방향이 반대면 부호를 뒤집어 "앞 − 뒤"로 맞춘다
        flip = f"{a}-{b}" not in diff_cis
        mean, lo, hi = ((-d["mean"], -d["hi"], -d["lo"]) if flip
                        else (d["mean"], d["lo"], d["hi"]))
        v = ("앞쪽이 유의하게 높다" if lo > 0 else
             "뒤쪽이 유의하게 높다" if hi < 0 else "0을 걸친다 → 차이를 주장할 수 없다")
        table.append([f"{a} − {b}", f"{mean:+.3f}", f"[{lo:+.3f}, {hi:+.3f}]", v])
    print_table(["비교(앞 − 뒤)", "QWK 차이", "95% 신뢰구간", "판정"], table)
    print("  ※ 구간이 0을 걸치면 '개선했다'고 쓰지 않는다(프로젝트 정직 규칙).")

    # ── 문항별 QWK ───────────────────────────────────────────────────────────
    print(f"\n{'=' * 86}\n  ⑤ 문항별 QWK (문항당 표본이 작아 참고용)\n{'=' * 86}")
    by_prompt_idx = defaultdict(list)
    for i, rid in enumerate(usable):
        by_prompt_idx[prompt_of[rid]].append(i)
    per_prompt_json, per_prompt_rows = {}, []
    for pkey, idxs in sorted(by_prompt_idx.items()):
        t = [truth[i] for i in idxs]
        entry = {m: qwk([preds[m][i] for i in idxs], t)
                 for m in ("A1", "B", "C", "D", "E", "F", "G", "H")}
        per_prompt_json[pkey] = {"n": len(idxs),
                                 "n_items_v1": len(v1_items.get(pkey, [])),
                                 "n_items_v2": len(items_full.get(pkey, [])), **entry}
        per_prompt_rows.append([pkey, len(idxs),
                                len(v1_items.get(pkey, [])), len(items_full.get(pkey, [])),
                                *[fmt(entry[m]) for m in
                                  ("A1", "B", "C", "D", "E", "F", "G", "H")]])
    print_table(["문항", "건수", "v1항목", "v2항목", "A1", "B", "C", "D", "E", "F", "G", "H"],
                per_prompt_rows)

    # ── 재현성 ───────────────────────────────────────────────────────────────
    repro_rows = select_repro_subset(rows, args.repro_n)
    repro_ids = [str(r["id"]) for r in repro_rows]
    repro = analyze_repro_v2(j2, repro_ids, checklists_v2, rows_by_id)
    print(f"\n{'=' * 86}\n  ⑥ 재현성 — 같은 답안을 같은 설정으로 3회 판정 "
          f"(고정 부분표본 {len(repro_ids)}건, v1 과 같은 60건)\n{'=' * 86}")
    if not any(repro["methods"][m]["n"] for m in repro["methods"]):
        print("  아직 재현성 실행(rep1·rep2·rep3)이 없다. 이 항목은 '미측정'으로 남긴다.")
    else:
        print_table(["방식", "3회 다 성공", "완전일치율", "평균 진폭", "최대 진폭", "평균 표준편차"],
                    [[METHOD_LABELS[m], repro["methods"][m]["n"],
                      fmt(repro["methods"][m]["exact_agreement"]),
                      fmt(repro["methods"][m]["mean_amplitude"]),
                      repro["methods"][m].get("max_amplitude", "-"),
                      fmt(repro["methods"][m]["mean_stdev"])] for m in ("D", "E", "G")])
        bf, sf = repro["binary_cell_flip"], repro["score_cell_flip"]
        print(f"  이진 패스 항목 0/1 뒤집힘: {bf['n_flipped']}/{bf['n_cells']}칸 "
              f"({fmt(bf['flip_rate'])})")
        print(f"  점수 패스 항목 0~100 변동: {sf['n_changed']}/{sf['n_cells']}칸 "
              f"({fmt(sf['change_rate'])}) · 평균 진폭 "
              f"{fmt(sf['mean_amplitude_0to100'], 1)}점(0~100 기준)")

    # ── 저장 ─────────────────────────────────────────────────────────────────
    fail_counts = Counter()
    for (rid, m, p), rec in j2.items():
        if rec.get("status") != "ok":
            fail_counts[f"{p}/{m}/{rec.get('status')}"] += 1
    elapsed_total = sum(float(rec.get("elapsed_sec") or 0.0) for rec in j2.values())

    summary = {
        "run_date": time.strftime("%Y-%m-%d %H:%M:%S"),
        "experiment": "체크리스트 v2 — RLCF(arXiv 2507.18624v2) 후보 기반 생성 이식",
        "model": JUDGE_MODEL,
        "temperature": 0.0,
        "input_type": "사람이 직접 적은 전사(ref)",
        "human_label_field": "evals.content (내용 및 과제 수행, 0~5)",
        "score_labels": list(SCORE_LABELS),
        "differences_from_paper": DIFFERENCES_FROM_PAPER,
        "dataset": {**counts,
                    "n_speakers": len({str(r.get("speaker_id")) for r in rows})},
        "checklist_items": {
            pkey: {
                "prompt": checklists_v2[pkey].get("prompt"),
                "n_items_v1": len(v1_items.get(pkey, [])),
                "n_task_items_v2": len([it for it in items_full[pkey]
                                        if not it.get("universal")]),
                "n_universal_items_v2": len([it for it in items_full[pkey]
                                             if it.get("universal")]),
                "importances": {str(it["id"]): it.get("importance")
                                for it in items_full[pkey]},
            } for pkey in sorted(checklists_v2)
        },
        "common_sample": {
            "n": len(usable), "n_speakers": len(set(speakers)),
            "n_excluded": len(rows_by_id) - len(usable),
            "excluded_reasons": {k: len(v) for k, v in dropped.items()},
        },
        "methods": {
            m: {"label": METHOD_LABELS[m],
                "uses_training_data": m in ("A1", "C", "F", "H", "F_noU", "LEN", "MEAN"),
                "is_ceiling": m.startswith("CEIL"),
                **metrics[m], "qwk_ci95": cis[m],
                "mean_pred": statistics.mean(preds[m])}
            for m in preds
        },
        "pairwise_diff_qwk_ci95": {name: {**d, "verdict": verdict(d)}
                                   for name, d in diff_cis.items()},
        "per_prompt_qwk": per_prompt_json,
        "reproducibility": repro,
        "citation_protocol": {
            "B2_dropped_citations_total": sum(int(rec_b2[rid].get("dropped_citations", 0))
                                              for rid in usable),
            "S2_dropped_citations_total": sum(int(rec_s2[rid].get("dropped_citations", 0))
                                              for rid in usable),
            "설명": "이진은 '충족인데 인용이 원문에 없음'을 미충족으로 내리고, "
                    "점수는 '1점 이상인데 인용이 원문에 없음'을 0점으로 내린다. "
                    "두 패스가 같은 규약을 쓴다.",
        },
        "failures": dict(fail_counts),
        "n_llm_calls_recorded_v2": len(j2),
        "llm_seconds_recorded_v2": round(elapsed_total, 1),
        "limitations": [
            "문항당 답안이 27~40건뿐이다. F·H 는 문항마다 항목 수만큼의 가중치를 "
            "이 표본으로 배우므로, v2 에서 항목이 늘어난 만큼 배울 것도 늘어 과적합 위험이 커진다.",
            "천장(선형 적합)은 항목이 많을수록 저절로 올라간다. v1·v2 천장을 견줄 때는 "
            "손잡이 하나뿐인 '충족 개수 천장'을 함께 봐야 한다.",
            "점수 패스는 온도 0 · 1회 호출이라 논문의 25회 평균과 다르다.",
            "AI Hub 데이터는 우리 시험(직무 한국어)과 과제 성격이 다르다.",
            f"판정 모델은 {JUDGE_MODEL} 하나뿐이다. 다른 모델에서도 같은 순위가 나올지는 안 쟀다.",
        ],
        "files": {
            "checklists_v1": str(OUT_DIR / "checklists.json"),
            "checklists_v2": str(CHECKLIST_V2_PATH),
            "judgments_v1": str(args.judgments_v1),
            "judgments_v2": str(args.judgments_v2),
            "fh_model_weights": str(FH_WEIGHTS_PATH),
            "summary_v1": str(OUT_DIR / "results_summary.json"),
            "summary_v2": str(args.out),
        },
    }

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(
        json.dumps(clean_nan(summary), ensure_ascii=False, indent=2,
                   default=_json_safe, allow_nan=False), encoding="utf-8")
    print(f"\n모든 수치 저장: {args.out}")
    if fail_counts:
        print(f"실패·미완료: {dict(fail_counts)}")
    return 0


def _json_safe(obj):
    """JSON 으로 못 적는 값(넘파이 숫자 등)을 적을 수 있는 모양으로 바꾼다."""
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return float(obj)
    return str(obj)


if __name__ == "__main__":
    raise SystemExit(main())
