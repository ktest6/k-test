# -*- coding: utf-8 -*-
"""쌓아 둔 판정 결과로 네 방식의 성적을 내고, 차이가 우연인지까지 따진다.

■ 여기서 하는 일 네 가지

  ① C 를 계산한다 — B 가 이미 낸 **똑같은 0/1 판정**을 재료로, 문항마다
     '어느 항목이 점수를 얼마나 좌우하는가'를 학습(릿지 회귀)해서 0~5 를 낸다.
     **LLM 을 새로 부르지 않는다.** 그래야 B 와 C 의 차이가 오직 결합 방식이 된다.
  ② 네 방식(A0·A1·B·C)의 QWK 를 **같은 교차검증 겹의 out-of-fold 예측으로만** 낸다.
     A1·C 는 학습 데이터를 쓰고 A0·B 는 안 쓰므로, 같은 잣대를 쓰지 않으면 비교가 기운다.
  ③ 화자 클러스터 부트스트랩 1000회로 95% 신뢰구간과 **방식 간 차이의 구간**을 낸다.
     차이 구간이 0을 걸치면 '개선'이라고 쓰지 않는다(프로젝트 정직 규칙).
  ④ 재현성 — 같은 60건을 3회 돌린 결과가 얼마나 흔들리는지 잰다.

■ 공정 규칙

한 방식에서라도 판정을 못 낸 답안은 **모든 방식에서 뺀다.** 방식마다 다른 답안
묶음으로 QWK 를 재면, 그 차이가 방식 때문인지 묶음이 달라서인지 알 수 없게 된다.

■ 쓰는 법

    python analyze.py                # 결과 요약 + results_summary.json 저장
    python analyze.py --self-test    # QWK·부트스트랩 계산기만 예시로 점검
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
    group_by_prompt,
    human_score,
    load_done,
    load_rows,
    print_table,
    prompt_key,
    qwk,
    select_repro_subset,
    verdict,
)
from gen_checklists import CHECKLIST_PATH, REPRO_PATH, load_checklists  # noqa: E402
from run_experiment import DEFAULT_OUT  # noqa: E402

#: 모든 수치를 기계가 읽을 수 있게 담아 두는 곳.
SUMMARY_PATH = OUT_DIR / "results_summary.json"
#: C 가 문항마다 배운 항목별 비중(=근거)을 남기는 곳.
C_WEIGHTS_PATH = OUT_DIR / "c_model_weights.json"

#: 릿지 회귀가 시험해 볼 규제 세기 후보.
#: 문항당 표본이 27~40건뿐이라 규제를 안 걸면 항목 5개를 그대로 외운다.
#: 실제 값은 학습 겹 안에서 하나 빼기(LOO) 검증으로 고른다 — 시험 볼 답안은 보지 않는다.
RIDGE_ALPHAS = tuple(float(a) for a in np.logspace(-1, 2, 10))

#: 방식 이름과 사람이 읽을 설명.
METHOD_LABELS = {
    "A0": "A0 LLM 직접 채점(제로샷)",
    "A1": "A1 LLM 직접 채점(퓨샷 앵커)",
    "B": "B 체크리스트 충족율×5",
    "C": "C 체크리스트+문항별 가중치 학습",
}


def round_half_up(x: float) -> int:
    """0~5 로 눌러 반올림한다. 0.5 는 위로 올린다(2.5 -> 3)."""
    return max(0, min(5, math.floor(float(x) + 0.5)))


# ── ① C 계산 — B 의 0/1 을 재료로 문항별 가중치를 배운다 ─────────────────────
def compute_method_c(records_b: dict[str, dict], rows_by_id: dict[str, dict],
                     fold_of: dict[str, int], checklists: dict):
    """B 가 낸 0/1 판정으로 문항마다 가중치를 배워 0~5 를 예측한다(RocketEval 방식).

    B 와 다른 점은 딱 하나다. B 는 '몇 개 충족했나'를 그대로 점수로 바꾸고,
    C 는 '이 문항에서는 2번 항목이 특히 중요하더라'를 사람 점수로부터 배운다.
    **LLM 호출은 0회다** — 재료가 B 의 판정 결과 그대로이기 때문이다.

    학습은 문항마다 따로, 그리고 **학습 겹에서만** 한다. 예측은 그 문항의
    시험 겹 답안에만 준다(out-of-fold). 규제 세기(alpha)도 학습 겹 안에서 고른다.

    돌려주는 값은 (답안 id -> 예측 점수, 문항별로 배운 것들)이다.
    배운 비중을 함께 돌려주는 이유: 점수만 있고 근거가 없으면 이 프로젝트에서는 결함이다.
    """
    preds: dict[str, int] = {}
    learned: dict[str, dict] = {}

    # 문항별로, 그 문항에서 B 판정이 성공한 답안만 모은다
    by_prompt: dict[str, list[str]] = defaultdict(list)
    for rid, rec in records_b.items():
        if rec.get("status") == "ok":
            by_prompt[rec["prompt_key"]].append(rid)

    for pkey, ids in sorted(by_prompt.items()):
        ids.sort()
        entry = checklists.get(pkey, {})
        # 항목 순서를 고정한다. 순서가 흔들리면 배운 비중을 항목에 짝지을 수 없다
        item_ids = [str(it["id"]) for it in entry.get("items", [])]
        if not item_ids:
            continue

        def vector(rid: str) -> list[float]:
            """한 답안의 0/1 판정을 항목 순서대로 늘어놓는다."""
            got = {i["cid"]: i["met"] for i in records_b[rid].get("items", [])}
            # 판정이 없는 항목은 미충족(0)으로 본다 — 채점 서버의 규약과 같다
            return [float(got.get(cid, 0)) for cid in item_ids]

        X_all = np.array([vector(r) for r in ids], dtype=float)
        y_all = np.array([human_score(rows_by_id[r]) for r in ids], dtype=float)
        folds = np.array([fold_of[r] for r in ids])

        fold_info = []
        for k in range(N_FOLDS):
            test_mask = folds == k
            train_mask = ~test_mask
            n_train = int(train_mask.sum())
            # 시험 볼 답안이 없으면 이 겹은 건너뛴다
            if test_mask.sum() == 0:
                continue
            # 배울 것이 너무 적거나 사람 점수가 전부 같으면 배울 수 없다.
            # 그럴 때는 **학습 겹의 평균 점수**로 답한다(가장 정직한 대체값)
            if n_train < 5 or float(np.std(y_all[train_mask])) < 1e-9:
                fallback = round_half_up(float(np.mean(y_all[train_mask]))) if n_train else 0
                for rid in np.array(ids)[test_mask]:
                    preds[str(rid)] = fallback
                fold_info.append({"fold": k, "n_train": n_train, "alpha": None,
                                  "note": "학습 표본이 모자라 학습 겹 평균으로 대체"})
                continue

            model = RidgeCV(alphas=RIDGE_ALPHAS)
            model.fit(X_all[train_mask], y_all[train_mask])
            raw = model.predict(X_all[test_mask])
            for rid, value in zip(np.array(ids)[test_mask], raw):
                preds[str(rid)] = round_half_up(float(value))

            fold_info.append({
                "fold": k,
                "n_train": n_train,
                "alpha": float(model.alpha_),
                "intercept": round(float(model.intercept_), 4),
                # 항목별로 배운 비중 = 이 항목을 충족하면 점수가 몇 점 오르는가
                "coefficients": {
                    cid: round(float(c), 4) for cid, c in zip(item_ids, model.coef_)
                },
            })

        learned[pkey] = {
            "item_ids": item_ids,
            "questions": {str(it["id"]): it["question"] for it in entry.get("items", [])},
            "n_rows": len(ids),
            "folds": fold_info,
        }

    return preds, learned


def freeze_c_models(records_b: dict[str, dict], rows_by_id: dict[str, dict],
                    fold_of: dict[str, int], checklists: dict) -> dict:
    """재현성 시험에 쓸 C 모델을 (문항, 겹)마다 굳혀 둔다.

    재현성 시험은 'LLM 판정이 흔들릴 때 최종 점수가 얼마나 흔들리나'를 보는 것이라,
    모델까지 매번 다시 배우면 무엇 때문에 흔들렸는지 알 수 없게 된다.
    그래서 **본실행에서 배운 모델을 그대로 고정**하고 입력(0/1)만 회차마다 바꾼다.
    """
    frozen: dict[tuple[str, int], tuple] = {}
    by_prompt: dict[str, list[str]] = defaultdict(list)
    for rid, rec in records_b.items():
        if rec.get("status") == "ok":
            by_prompt[rec["prompt_key"]].append(rid)

    for pkey, ids in by_prompt.items():
        ids.sort()
        entry = checklists.get(pkey, {})
        item_ids = [str(it["id"]) for it in entry.get("items", [])]
        if not item_ids:
            continue
        X_all, y_all, folds = [], [], []
        for rid in ids:
            got = {i["cid"]: i["met"] for i in records_b[rid].get("items", [])}
            X_all.append([float(got.get(cid, 0)) for cid in item_ids])
            y_all.append(float(human_score(rows_by_id[rid])))
            folds.append(fold_of[rid])
        X_all, y_all, folds = np.array(X_all), np.array(y_all), np.array(folds)

        for k in range(N_FOLDS):
            train_mask = folds != k
            if int(train_mask.sum()) < 5 or float(np.std(y_all[train_mask])) < 1e-9:
                mean = float(np.mean(y_all[train_mask])) if train_mask.sum() else 0.0
                frozen[(pkey, k)] = ("mean", item_ids, mean)
                continue
            model = RidgeCV(alphas=RIDGE_ALPHAS)
            model.fit(X_all[train_mask], y_all[train_mask])
            frozen[(pkey, k)] = ("ridge", item_ids, model)
    return frozen


def apply_frozen_c(frozen, pkey: str, fold: int, judged_items: list[dict]) -> int | None:
    """굳혀 둔 C 모델에 이번 회차의 0/1 판정을 넣어 점수를 낸다."""
    entry = frozen.get((pkey, fold))
    if entry is None:
        return None
    kind, item_ids, model = entry
    if kind == "mean":
        return round_half_up(model)
    got = {i["cid"]: i["met"] for i in judged_items}
    x = np.array([[float(got.get(cid, 0)) for cid in item_ids]], dtype=float)
    return round_half_up(float(model.predict(x)[0]))


# ── ② 공통 표본 고르기 ───────────────────────────────────────────────────────
def build_common_sample(records: dict, rows_by_id: dict, c_preds: dict):
    """네 방식이 모두 점수를 낸 답안만 남긴다(공정 규칙).

    돌려주는 값은 (쓸 답안 id 목록, 왜 뺐는지)다. 뺀 이유를 세어 두는 이유는
    "몇 건이 왜 빠졌는가"를 결과에 적기 위해서다 — 조용히 사라진 표본은 없어야 한다.
    """
    usable, dropped = [], defaultdict(list)
    for rid in sorted(rows_by_id):
        reasons = []
        for method in ("A0", "A1", "B"):
            rec = records.get((rid, method))
            if rec is None:
                reasons.append(f"{method}:미실행")
            elif rec.get("status") != "ok":
                reasons.append(f"{method}:{rec.get('status')}")
        if rid not in c_preds:
            reasons.append("C:예측없음")
        if reasons:
            dropped[" / ".join(reasons)].append(rid)
        else:
            usable.append(rid)
    return usable, dict(dropped)


# ── ④ 재현성 ─────────────────────────────────────────────────────────────────
def analyze_reproducibility(judgments: dict, repro_ids: list[str], frozen_c,
                            rows_by_id: dict, fold_of: dict) -> dict:
    """같은 답안을 3회 판정했을 때 결과가 얼마나 흔들리는지 잰다.

    가설(검증 대상): **0~5 를 직접 매기는 것보다 0/1 로 쪼개면, 같은 LLM 흔들림에도
    최종 점수가 덜 흔들린다.** 항목 하나가 뒤집혀도 다른 항목들이 붙들어 주기 때문이다.
    결과가 반대로 나오면 반대로 적는다.

    재는 것:
      · 완전일치율 — 3회 점수가 전부 같은 답안의 비율
      · 평균 진폭  — 3회 중 가장 높은 점수와 낮은 점수의 차이(0이면 안 흔들린 것)
      · 표준편차   — 3회 점수의 퍼짐 평균
      · (B·C 만) 뒤집힘율 — 체크리스트 항목 하나하나의 0/1 이 3회 내내 같았는지
    """
    passes = ("rep1", "rep2", "rep3")
    out: dict = {"n_passes": len(passes), "subset_size": len(repro_ids), "methods": {}}

    def stability(preds_per_item: dict[str, list[int]]) -> dict:
        if not preds_per_item:
            return {"n": 0, "exact_agreement": float("nan"),
                    "mean_amplitude": float("nan"), "mean_stdev": float("nan")}
        amplitudes = [max(v) - min(v) for v in preds_per_item.values()]
        stdevs = [statistics.pstdev(v) for v in preds_per_item.values()]
        same = sum(1 for v in preds_per_item.values() if len(set(v)) == 1)
        return {
            "n": len(preds_per_item),
            "exact_agreement": same / len(preds_per_item),
            "mean_amplitude": sum(amplitudes) / len(amplitudes),
            "max_amplitude": max(amplitudes),
            "mean_stdev": sum(stdevs) / len(stdevs),
        }

    # A0 · A1 — LLM 이 매긴 0~5 를 그대로 비교한다
    for method in ("A0", "A1"):
        per_item: dict[str, list[int]] = {}
        for rid in repro_ids:
            values = []
            for p in passes:
                rec = judgments.get((rid, method, p))
                if rec and rec.get("status") == "ok":
                    values.append(int(rec["pred"]))
            # 3회가 다 있는 답안만 쓴다. 두 번만 성공한 것을 섞으면 흔들림이 작아 보인다
            if len(values) == len(passes):
                per_item[rid] = values
        out["methods"][method] = stability(per_item)

    # B — 항목 0/1 의 뒤집힘까지 함께 본다
    per_item_b: dict[str, list[int]] = {}
    per_item_c: dict[str, list[int]] = {}
    cell_total, cell_flipped = 0, 0
    for rid in repro_ids:
        recs = [judgments.get((rid, "B", p)) for p in passes]
        if any(r is None or r.get("status") != "ok" for r in recs):
            continue
        per_item_b[rid] = [int(r["pred"]) for r in recs]

        # 항목 하나하나가 3회 내내 같은 판정이었는지 센다
        cids = [i["cid"] for i in recs[0]["items"]]
        for cid in cids:
            values = set()
            for r in recs:
                got = {i["cid"]: i["met"] for i in r["items"]}
                values.add(got.get(cid))
            cell_total += 1
            if len(values) > 1:
                cell_flipped += 1

        # C 는 굳혀 둔 모델에 회차별 0/1 을 넣어 낸다(모델은 고정, 입력만 바뀐다)
        pkey = recs[0]["prompt_key"]
        fold = fold_of[rid]
        c_values = [apply_frozen_c(frozen_c, pkey, fold, r["items"]) for r in recs]
        if all(v is not None for v in c_values):
            per_item_c[rid] = [int(v) for v in c_values]

    out["methods"]["B"] = stability(per_item_b)
    out["methods"]["C"] = stability(per_item_c)
    out["checklist_cell_flip"] = {
        "n_cells": cell_total,
        "n_flipped": cell_flipped,
        "flip_rate": (cell_flipped / cell_total) if cell_total else float("nan"),
        "설명": "답안 하나의 체크리스트 항목 하나가 3회 판정에서 한 번이라도 달랐으면 뒤집힘 1건",
    }
    return out


# ── 자체 점검 ────────────────────────────────────────────────────────────────
def self_test() -> int:
    """계산기들이 맞게 도는지 답을 아는 예시로 확인한다.

    채점·통계 코드는 눈으로 훑어서는 맞는지 알 수 없다. 그래서 값을 아는 입력을
    넣어 결과를 직접 본다. 여기서 확인하는 것:
      · 완전히 같게 매기면 QWK 가 1.0 인가
      · 아무렇게나 찍으면 QWK 가 0 근처인가
      · 많이 빗나갈수록 더 크게 깎이는가(가중의 뜻)
      · 널리 쓰이는 구현(scikit-learn)과 같은 값이 나오는가
      · 부트스트랩 구간이 상식적인 자리에 놓이는가
    """
    import random as _random

    from sklearn.metrics import cohen_kappa_score

    ok = True
    print("=== 계산기 자체 점검 ===")
    rows = []

    def check(label, got, want, tol=1e-9):
        nonlocal ok
        passed = abs(got - want) < tol
        ok &= passed
        rows.append([label, f"{got:.6f}", f"{want:.6f}", "통과" if passed else "실패"])

    truth = [0, 1, 2, 3, 4, 5, 3, 2, 3, 4, 2, 3]
    # 1) 완전 일치 -> 1.0
    check("완전 일치", qwk(truth, truth), 1.0)
    # 2) 한 칸 차이 vs 세 칸 차이 — 많이 빗나갈수록 더 크게 깎여야 한다
    near = [min(5, t + 1) for t in truth]
    far = [min(5, t + 3) for t in truth]
    q_near, q_far = qwk(near, truth), qwk(far, truth)
    rows.append(["한 칸 어긋남", f"{q_near:.6f}", "세 칸보다 커야", "통과" if q_near > q_far else "실패"])
    ok &= q_near > q_far
    # 3) 무작위 예측 -> 0 근처 (3000건 평균)
    rng = _random.Random(1234)
    big_truth = [rng.randint(0, 5) for _ in range(3000)]
    big_pred = [rng.randint(0, 5) for _ in range(3000)]
    q_rand = qwk(big_pred, big_truth)
    rows.append(["무작위 3000건", f"{q_rand:+.6f}", "0 근처(|값|<0.06)",
                 "통과" if abs(q_rand) < 0.06 else "실패"])
    ok &= abs(q_rand) < 0.06
    # 4) 널리 쓰이는 구현과 같은 값이 나오는가
    mixed_pred = [1, 1, 2, 4, 4, 5, 2, 2, 3, 3, 3, 4]
    check("scikit-learn 과 대조",
          qwk(mixed_pred, truth),
          float(cohen_kappa_score(mixed_pred, truth, weights="quadratic",
                                  labels=list(SCORE_LABELS))), tol=1e-9)
    # 5) 완전히 반대로 매기면 음수
    reversed_pred = [5 - t for t in truth]
    q_rev = qwk(reversed_pred, truth)
    rows.append(["정반대로 매김", f"{q_rev:+.6f}", "음수여야", "통과" if q_rev < 0 else "실패"])
    ok &= q_rev < 0
    # 6) 반올림 규칙: 0.5 는 위로
    g = [round_half_up(v) for v in (-0.4, 0.5, 2.4, 2.5, 5.6)]
    rows.append(["0.5 는 위로 반올림", str(g), "[0, 1, 2, 3, 5]",
                 "통과" if g == [0, 1, 2, 3, 5] else "실패"])
    ok &= g == [0, 1, 2, 3, 5]

    print_table(["항목", "나온 값", "기대", "판정"], rows)

    # 7) 부트스트랩 구간이 상식적인 자리에 놓이는지
    speakers = [f"S{i:03d}" for i in range(len(truth))]
    cis, diffs = bootstrap_qwk_ci(
        {"완전": truth, "한칸": near}, truth, speakers, n_boot=200, seed=SEED)
    print(f"\n  부트스트랩 확인: '완전' QWK 구간 "
          f"[{cis['완전']['lo']:.3f}, {cis['완전']['hi']:.3f}] (1.0 을 포함해야 한다)")
    print(f"                  차이(완전-한칸) 구간 "
          f"[{diffs['완전-한칸']['lo']:+.3f}, {diffs['완전-한칸']['hi']:+.3f}] → "
          f"{verdict(diffs['완전-한칸'])}")
    ok &= cis["완전"]["lo"] <= 1.0 <= cis["완전"]["hi"] + 1e-9
    ok &= diffs["완전-한칸"]["lo"] > 0

    print("\n" + ("모두 통과" if ok else "실패한 항목이 있다"))
    return 0 if ok else 1


# ── 실행 ─────────────────────────────────────────────────────────────────────
def main() -> int:
    enable_utf8_output()
    ap = argparse.ArgumentParser(description="네 방식의 QWK·신뢰구간·재현성을 계산한다")
    ap.add_argument("--judgments", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--out", type=Path, default=SUMMARY_PATH)
    ap.add_argument("--bootstrap", type=int, default=N_BOOTSTRAP)
    ap.add_argument("--repro-n", type=int, default=60)
    ap.add_argument("--self-test", action="store_true",
                    help="계산기만 예시 입력으로 점검하고 끝낸다(파일도 LLM도 안 건드린다)")
    args = ap.parse_args()

    if args.self_test:
        return self_test()

    # ── 재료 읽기 ────────────────────────────────────────────────────────────
    rows, counts = load_rows()
    rows_by_id = {str(r["id"]): r for r in rows}
    fold_of, diag = assign_folds(rows, N_FOLDS)
    checklists = load_checklists()
    judgments = load_done(args.judgments)

    print("=== 표본 ===")
    print_table(["단계", "건수"], [[k, v] for k, v in counts.items()])
    print(f"화자 {len({str(r.get('speaker_id')) for r in rows})}명 · "
          f"겹 나누기: 화자 단위 {N_FOLDS}겹, 겹을 넘나든 화자 {diag['speaker_leak_count']}명, "
          f"빈 칸 {len(diag['prompts_with_empty_fold'])}개")

    # 본실행(main) 판정만 성적 계산에 쓴다. rep1~3 은 재현성 전용이다
    main_records = {(rid, m): rec for (rid, m, p), rec in judgments.items() if p == "main"}
    records_b = {rid: rec for (rid, m), rec in main_records.items() if m == "B"}

    # ── ① C 계산 ─────────────────────────────────────────────────────────────
    c_preds, c_learned = compute_method_c(records_b, rows_by_id, fold_of, checklists)
    Path(C_WEIGHTS_PATH).parent.mkdir(parents=True, exist_ok=True)
    Path(C_WEIGHTS_PATH).write_text(
        json.dumps(c_learned, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nC 가 문항 {len(c_learned)}종에서 항목별 비중을 배웠다 "
          f"(LLM 호출 0회 — B 의 0/1 판정을 그대로 다시 씀). 근거 저장: {C_WEIGHTS_PATH}")

    # ── ② 공통 표본 ──────────────────────────────────────────────────────────
    usable, dropped = build_common_sample(main_records, rows_by_id, c_preds)
    print(f"\n=== 공통 표본: {len(usable)}건 "
          f"(대상 {len(rows_by_id)}건 중 {len(rows_by_id) - len(usable)}건 제외) ===")
    if dropped:
        print("  제외 내역 (한 방식에서라도 점수를 못 낸 답안은 모든 방식에서 뺀다)")
        for reason, ids in sorted(dropped.items(), key=lambda kv: -len(kv[1])):
            sample = ", ".join(i[-16:] for i in ids[:3])
            more = f" 외 {len(ids) - 3}건" if len(ids) > 3 else ""
            print(f"    {len(ids):4d}건  {reason}  ({sample}{more})")

    if len(usable) < 10:
        print("\n[중단] 공통 표본이 10건 미만이라 성적을 계산하지 않는다. "
              "run_experiment.py 를 더 돌려야 한다.")
        return 1

    truth = [human_score(rows_by_id[rid]) for rid in usable]
    speakers = [str(rows_by_id[rid].get("speaker_id")) for rid in usable]
    preds = {
        "A0": [int(main_records[(rid, "A0")]["pred"]) for rid in usable],
        "A1": [int(main_records[(rid, "A1")]["pred"]) for rid in usable],
        "B": [int(main_records[(rid, "B")]["pred"]) for rid in usable],
        "C": [int(c_preds[rid]) for rid in usable],
    }

    # ── ③ 성적과 신뢰구간 ────────────────────────────────────────────────────
    metrics = {m: all_metrics(p, truth) for m, p in preds.items()}
    print(f"\n부트스트랩 {args.bootstrap}회 계산 중 (화자를 통째로 다시 뽑는다)...")
    cis, diff_cis = bootstrap_qwk_ci(preds, truth, speakers, args.bootstrap, SEED)

    print(f"\n{'=' * 78}")
    print("  ① 방식별 성적 — 같은 겹의 out-of-fold 예측만 썼다 (표본 "
          f"{len(usable)}건 · 화자 {len(set(speakers))}명)")
    print("=" * 78)
    print_table(
        ["방식", "QWK", "95% 신뢰구간", "피어슨", "스피어만", "정확일치", "±1 이내", "평균예측"],
        [[METHOD_LABELS[m],
          fmt(metrics[m]["qwk"]),
          f"[{fmt(cis[m]['lo'])}, {fmt(cis[m]['hi'])}]",
          fmt(metrics[m]["pearson"]),
          fmt(metrics[m]["spearman"]),
          f"{metrics[m]['exact']:.1%}",
          f"{metrics[m]['within1']:.1%}",
          f"{statistics.mean(preds[m]):.2f}"] for m in ("A0", "A1", "B", "C")]
    )
    print(f"  참고: 사람 점수 평균 {statistics.mean(truth):.2f} · "
          f"분포 {dict(sorted(Counter(truth).items()))}")

    print(f"\n{'=' * 78}")
    print(f"  ② 방식 간 차이가 우연인가 (화자 다시뽑기 {args.bootstrap}회, 95% 구간)")
    print("=" * 78)
    print_table(
        ["비교", "QWK 차이", "95% 신뢰구간", "판정"],
        [[name.replace("-", " − "), f"{d['mean']:+.3f}",
          f"[{d['lo']:+.3f}, {d['hi']:+.3f}]", verdict(d)]
         for name, d in diff_cis.items()]
    )
    print("  ※ 구간이 0을 걸치면 '개선했다'고 쓰지 않는다(프로젝트 정직 규칙).")

    # 문항별 QWK — 표본이 작아 흔들리지만, 방식이 문항을 가리는지 보려면 필요하다
    print(f"\n{'=' * 78}\n  ③ 문항별 QWK (문항당 표본이 작아 참고용)\n{'=' * 78}")
    per_prompt_rows = []
    per_prompt_json = {}
    by_prompt_ids = defaultdict(list)
    for i, rid in enumerate(usable):
        by_prompt_ids[prompt_key(rows_by_id[rid].get("prompt") or "")].append(i)
    for pkey, idxs in sorted(by_prompt_ids.items()):
        t = [truth[i] for i in idxs]
        entry = {m: qwk([preds[m][i] for i in idxs], t) for m in preds}
        per_prompt_json[pkey] = {"n": len(idxs), **{m: entry[m] for m in entry}}
        per_prompt_rows.append([
            pkey, len(idxs),
            (checklists.get(pkey, {}).get("prompt") or "")[:22],
            len(checklists.get(pkey, {}).get("items", [])),
            *[fmt(entry[m]) for m in ("A0", "A1", "B", "C")],
        ])
    print_table(["문항", "건수", "지시문", "항목수", "A0", "A1", "B", "C"], per_prompt_rows)

    # ── ④ 재현성 ─────────────────────────────────────────────────────────────
    repro_rows = select_repro_subset(rows, args.repro_n)
    repro_ids = [str(r["id"]) for r in repro_rows]
    frozen_c = freeze_c_models(records_b, rows_by_id, fold_of, checklists)
    repro = analyze_reproducibility(judgments, repro_ids, frozen_c, rows_by_id, fold_of)

    has_repro = any(repro["methods"][m]["n"] for m in repro["methods"])
    print(f"\n{'=' * 78}")
    print(f"  ④ 재현성 — 같은 답안을 같은 설정으로 3회 판정 (고정 부분표본 {len(repro_ids)}건)")
    print("=" * 78)
    if not has_repro:
        print("  아직 재현성 실행(rep1·rep2·rep3)이 없다. 이 항목은 '미측정'으로 남긴다.")
    else:
        print_table(
            ["방식", "3회 다 성공", "완전일치율", "평균 진폭", "최대 진폭", "평균 표준편차"],
            [[METHOD_LABELS[m], repro["methods"][m]["n"],
              fmt(repro["methods"][m]["exact_agreement"]),
              fmt(repro["methods"][m]["mean_amplitude"]),
              repro["methods"][m].get("max_amplitude", "-"),
              fmt(repro["methods"][m]["mean_stdev"])] for m in ("A0", "A1", "B", "C")]
        )
        flip = repro["checklist_cell_flip"]
        print(f"  체크리스트 항목 0/1 뒤집힘: {flip['n_flipped']}/{flip['n_cells']}칸 "
              f"({fmt(flip['flip_rate'])}) — 항목이 뒤집혀도 최종 점수는 덜 흔들리는지가 관전 포인트")

    # ── 저장 ─────────────────────────────────────────────────────────────────
    fail_counts = Counter()
    for (rid, m, p), rec in judgments.items():
        if rec.get("status") != "ok":
            fail_counts[f"{p}/{m}/{rec.get('status')}"] += 1

    gen_repro = json.loads(Path(REPRO_PATH).read_text(encoding="utf-8")) \
        if Path(REPRO_PATH).exists() else None

    summary = {
        "run_date": time.strftime("%Y-%m-%d %H:%M:%S"),
        "model": JUDGE_MODEL,
        "temperature": 0.0,
        "input_type": "사람이 직접 적은 전사(ref) — 받아쓰기 오차를 배제하고 채점 방식만 비교하기 위해",
        "score_labels": list(SCORE_LABELS),
        "human_label_field": "evals.content (내용 및 과제 수행, 0~5)",
        "dataset": {
            **{k: v for k, v in counts.items()},
            "n_speakers": len({str(r.get("speaker_id")) for r in rows}),
            "human_score_distribution": dict(sorted(
                Counter(human_score(r) for r in rows).items())),
        },
        "fold_scheme": {
            "name": f"화자(speaker_id) 단위 {N_FOLDS}겹",
            "loo_used": False,
            "diagnostics": {k: v for k, v in diag.items() if k != "per_prompt"},
            "per_prompt": diag["per_prompt"],
        },
        "common_sample": {
            "n": len(usable),
            "n_speakers": len(set(speakers)),
            "n_excluded": len(rows_by_id) - len(usable),
            "excluded_reasons": {k: len(v) for k, v in dropped.items()},
        },
        "methods": {
            m: {
                "label": METHOD_LABELS[m],
                "uses_training_data": m in ("A1", "C"),
                "llm_calls_per_answer": {"A0": 1, "A1": 1, "B": 1, "C": 0}[m],
                **metrics[m],
                "qwk_ci95": cis[m],
                "mean_pred": statistics.mean(preds[m]),
            } for m in ("A0", "A1", "B", "C")
        },
        "pairwise_diff_qwk_ci95": {
            name: {**d, "verdict": verdict(d)} for name, d in diff_cis.items()
        },
        "per_prompt_qwk": per_prompt_json,
        "citation": {
            "A0_citation_verified_rate": _citation_rate(main_records, "A0", usable),
            "A1_citation_verified_rate": _citation_rate(main_records, "A1", usable),
            "B_dropped_citations_total": sum(
                int(main_records[(rid, "B")].get("dropped_citations", 0)) for rid in usable),
            "설명": "A0·A1 은 점수를 LLM 이 정하므로 인용이 원문에 없어도 점수를 내린다. "
                    "그 비율이 곧 '근거 없는 점수'의 비율이다. "
                    "B 는 인용이 원문에 없으면 그 항목을 미충족으로 내린다(채점 서버와 같은 규약).",
        },
        "reproducibility": repro,
        "checklist_generation_reproducibility": gen_repro,
        "failures": dict(fail_counts),
        "n_llm_calls_recorded": len(judgments),
        "limitations": [
            f"문항당 답안이 27~40건뿐이다. C 는 문항마다 항목 "
            f"{_avg_items(checklists):.1f}개짜리 가중치를 이 표본으로 배운다 — "
            "표본이 작아 배운 비중 자체가 흔들릴 수 있다.",
            "겹 하나에 문항당 5~8건만 들어가므로 QWK 가 표본 구성에 민감하다. "
            "그래서 점 추정치보다 신뢰구간을 먼저 봐야 한다.",
            "AI Hub 데이터는 우리 시험(직무 한국어)과 과제 성격이 다르다. "
            "여기서 이긴 방식이 우리 문항에서도 이긴다는 보장은 없다.",
            "AI Hub 의 실제 채점 기준표는 공개돼 있지 않아 A0·A1 의 기준 설명은 우리가 썼다. "
            "세 방식이 같은 조건이라 비교는 성립하지만, 절대 점수의 높낮이는 기준 문구에 좌우된다.",
            "사람 점수 자체의 채점자 간 일치도(인간-인간 QWK)를 이 데이터로는 잴 수 없다"
            "(답안마다 평가자가 한 명이다). 그래서 '사람 수준에 도달했다'는 말은 할 수 없다.",
            f"판정 모델은 {JUDGE_MODEL} 하나뿐이다. 다른 모델에서도 같은 순위가 나올지는 안 쟀다.",
        ],
        "files": {
            "checklists": str(CHECKLIST_PATH),
            "judgments": str(args.judgments),
            "c_model_weights": str(C_WEIGHTS_PATH),
            "summary": str(args.out),
        },
    }

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(
        json.dumps(clean_nan(summary), ensure_ascii=False, indent=2,
                   default=_json_safe, allow_nan=False),
        encoding="utf-8")
    print(f"\n모든 수치 저장: {args.out}")
    if fail_counts:
        print(f"실패·미완료: {dict(fail_counts)}")
    return 0


def _citation_rate(main_records: dict, method: str, usable: list[str]) -> float:
    """A0·A1 이 낸 점수 중 근거 인용이 원문에서 확인된 비율."""
    values = [bool(main_records[(rid, method)].get("citation_ok")) for rid in usable]
    return sum(values) / len(values) if values else float("nan")


def _avg_items(checklists: dict) -> float:
    """문항당 체크리스트 항목 수 평균."""
    counts = [len(v.get("items", [])) for v in checklists.values() if v.get("status") == "ok"]
    return sum(counts) / len(counts) if counts else 0.0


def _json_safe(obj):
    """JSON 으로 못 적는 값(넘파이 숫자 등)을 적을 수 있는 모양으로 바꾼다."""
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    return str(obj)


def clean_nan(obj):
    """'계산할 수 없었던 값'(NaN)을 JSON 의 null 로 바꾼다.

    파이썬은 NaN 을 그대로 적어 주지만 그것은 표준 JSON 이 아니라서,
    다른 언어나 도구가 이 파일을 읽을 때 통째로 실패한다. 이 결과 파일은
    '기계가 읽는 요약'이 목적이므로 여기서 정리해 둔다.
    측정하지 못한 값을 0으로 바꾸지 않는 것이 중요하다 — 0은 '재 봤더니 0'이라는 뜻이라
    '못 쟀다'와 전혀 다른 말이 된다.
    """
    if isinstance(obj, dict):
        return {k: clean_nan(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean_nan(v) for v in obj]
    if isinstance(obj, (float, np.floating)):
        value = float(obj)
        return None if (math.isnan(value) or math.isinf(value)) else value
    if isinstance(obj, np.integer):
        return int(obj)
    return obj


if __name__ == "__main__":
    raise SystemExit(main())
