# -*- coding: utf-8 -*-
"""v1·v2·v3 의 모든 방식을 **한 표에** 놓고 견준다.

■ 이번 실험의 질문

  1차(v1) — 지시문만 보고 항목을 뽑았다. 항목 2개, 정보 천장 0.689~0.711.
  2차(v2) — 지어낸 후보 답안이 실패하는 방식으로 뽑았다. 항목 6개, 천장 0.797.
            그 천장을 받아 간 것은 가중치 학습(F 0.698) 하나뿐이었다.
  3차(v3) — **진짜 응시자 답안과 사람 점수를 보고** 뽑았다(시험 겹은 절대 안 봤다).

    → **천장이 v2 의 0.797 을 넘는가?** 그리고 가중치 학습(J)이 v2 의 F(0.698)를
      넘는가? 이 둘이 이번 분석의 핵심 질문이다.

■ 겹마다 체크리스트가 다르다 — 그래서 천장을 두 가지로 낸다

v3 는 문항 하나에 체크리스트가 다섯 벌이라, 답안마다 재는 자가 다르다.
그래서 천장을 이렇게 나눠 낸다.

  ① **겹벌 천장** — "겹 k 의 체크리스트를 281건 전부에 썼다면" 을 겹마다 따로 잰다.
     v2 는 체크리스트 한 벌을 281건에 썼으므로, **v2 의 0.797 과 나란히 놓을 수 있는
     것은 이쪽이다.** 다섯 개가 나오므로 평균과 폭을 함께 본다.
  ② **실배치 천장** — 답안마다 자기 겹의 체크리스트로 잰다(실제 채점과 같은 배치).
     이쪽은 (문항 × 겹) 마다 답안이 6~8건뿐이라 칸이 잘게 쪼개져 낙관 쪽으로 부푼다.
     참고용으로만 읽어야 한다.

■ 여기서 계산하는 것

  v1·v2 (앞 실험 결과를 그대로 다시 읽는다. 다시 판정하지 않는다)
    A0 · A1 · B · C · D · E · F · G · H

  v3 에서
    I  v3 충족율 × 5 (학습 없음, 자기 겹 체크리스트)
    J  v3 + **문항별 가중치 학습**(릿지, 겹별 out-of-fold) ← 이번 실험의 주인공
    K  소프트 패스 확률 벡터 + 학습 ← **예비조사가 통과했을 때만.** 이번엔 안 돌았다

  기준선 — 학습 겹 평균(바닥), 글자 수만 보는 길이 기준선

■ 공정 규칙 (앞 실험과 똑같이 유지한다)

  · 한 방식에서라도 점수를 못 낸 답안은 **모든 방식에서 뺀다**
  · 학습을 쓰는 방식(A1·C·F·H·J)은 **out-of-fold 예측만** 쓴다
  · QWK + 화자 클러스터 부트스트랩 1000회 95% 신뢰구간 + 방식 간 차이 구간
  · **차이 구간이 0을 걸치면 개선이라고 쓰지 않는다**

■ 쓰는 법

    python analyze_v3.py             # 결과 요약 + results_summary_v3.json 저장
    python analyze_v3.py --self-test # 계산기만 예시 입력으로 점검(파일도 LLM도 안 건드림)
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
from analyze_v2 import (  # noqa: E402
    binary_vector,
    ceiling_by_linear_fit,
    ceiling_by_met_count,
    ceiling_by_met_count_optimized,
    included_items,
    learn_per_prompt,
    score_vector,
    weighted_ratio,
)
from extra_baselines import baseline_length, baseline_mean  # noqa: E402
from gen_checklists import load_checklists  # noqa: E402
from gen_checklists_v2 import load_checklists_v2  # noqa: E402
from gen_checklists_v3 import (  # noqa: E402
    CHECKLIST_V3_PATH,
    fold_agreement,
    items_for,
    load_checklists_v3,
)
from run_experiment import DEFAULT_OUT  # noqa: E402
from run_experiment_v2 import DEFAULT_OUT_V2, ratio_to_score  # noqa: E402
from run_experiment_v3 import DEFAULT_OUT_V3, PROBE_PATH  # noqa: E402

#: 모든 수치를 기계가 읽을 수 있게 담아 두는 곳.
SUMMARY_V3_PATH = OUT_DIR / "results_summary_v3.json"
#: J 가 문항·겹마다 배운 항목별 비중(=근거)을 남기는 곳.
J_WEIGHTS_PATH = OUT_DIR / "j_model_weights.json"

#: 방식 이름과 사람이 읽을 설명.
#: **이름에 하이픈을 쓰지 않는다** — 부트스트랩이 방식 쌍 이름을 "A-B" 로 만들어
#: 나중에 하이픈으로 다시 가르기 때문에, 이름 안에 하이픈이 있으면 짝을 잃는다.
METHOD_LABELS = {
    "A0": "A0 LLM 직접 채점(제로샷) [v1]",
    "A1": "A1 LLM 직접 채점(퓨샷 앵커) [v1]",
    "B": "B v1 충족율×5",
    "C": "C v1 이진+가중치 학습",
    "D": "D v2 충족율×5",
    "E": "E v2 중요도 가중 충족율×5",
    "F": "F v2 이진+가중치 학습",
    "G": "G v2 항목 0~100 가중평균×5",
    "H": "H v2 0~100 벡터+가중치 학습",
    "I": "I v3 충족율×5 (자기 겹 체크리스트)",
    "J": "J v3 이진+문항별 가중치 학습 ★",
    "I_imp": "I′ v3 중요도 가중 충족율×5",
    "MEAN": "바닥선(학습겹 평균, 답안을 안 읽음)",
    "LEN": "길이 기준선(글자 수만)",
    "CEIL_V1_CNT": "천장 v1(충족 개수·중앙값 사상)",
    "CEIL_V1_OPT": "천장 v1(충족 개수·QWK 최대 사상)",
    "CEIL_V1_LIN": "천장 v1(정답 보고 선형 적합)",
    "CEIL_V2_CNT": "천장 v2(충족 개수·중앙값 사상)",
    "CEIL_V2_OPT": "천장 v2(충족 개수·QWK 최대 사상)",
    "CEIL_V2_LIN": "천장 v2(정답 보고 선형 적합)",
    "CEIL_V3_CNT_OWN": "천장 v3 실배치(충족 개수·중앙값·칸이 잘게 쪼개짐)",
    "CEIL_V3_OPT_OWN": "천장 v3 실배치(충족 개수·QWK 최대·칸이 잘게 쪼개짐)",
}
# 겹벌 천장(겹 k 의 체크리스트를 281건 전부에 썼다면)은 겹마다 세 개씩 생긴다
for _k in range(N_FOLDS):
    METHOD_LABELS[f"CEIL_V3_CNT_f{_k}"] = f"천장 v3 겹{_k}벌(충족 개수·중앙값)"
    METHOD_LABELS[f"CEIL_V3_OPT_f{_k}"] = f"천장 v3 겹{_k}벌(충족 개수·QWK 최대)"
    METHOD_LABELS[f"CEIL_V3_LIN_f{_k}"] = f"천장 v3 겹{_k}벌(정답 보고 선형 적합)"


# ── v3 판정 읽기 ─────────────────────────────────────────────────────────────
def v3_records(judgments: dict, pass_tag: str = "main") -> dict[tuple[str, int], dict]:
    """v3 판정을 (답안 id, 체크리스트 겹) 열쇠로 정리한다.

    v3 는 답안 하나를 다섯 벌로 판정하므로, 어느 벌로 받은 판정인지가 붙어 있어야
    "자기 겹 판정"과 "학습용 판정"을 가를 수 있다. 방식 이름이 `B3f0`~`B3f4` 라서
    끝의 숫자가 곧 체크리스트 겹 번호다.
    """
    out: dict[tuple[str, int], dict] = {}
    for (rid, method, tag), rec in judgments.items():
        if tag != pass_tag or not method.startswith("B3f"):
            continue
        if rec.get("status") != "ok":
            continue
        out[(rid, int(method[3:]))] = rec
    return out


# ── J — 겹마다 다른 체크리스트로 문항별 가중치를 배운다 ──────────────────────
def learn_per_prompt_v3(recs: dict[tuple[str, int], dict], rows_by_id: dict,
                        fold_of: dict[str, int], prompt_of: dict[str, str],
                        checklists: dict):
    """문항마다 항목별 가중치를 배워 0~5 를 예측한다(겹별 out-of-fold).

    v2 의 F(`analyze_v2.learn_per_prompt`)와 **같은 절차**다. 다른 것은 하나뿐 —
    v2 는 문항마다 체크리스트가 한 벌이라 재료 표가 하나였지만, v3 는 겹마다 달라서
    **겹마다 재료 표를 새로 만든다.**

    겹 k 를 시험 볼 때:
      · 재료  = 겹 k 의 체크리스트로 받은 판정 (학습 답안·시험 답안 모두)
      · 학습  = 겹 k 가 **아닌** 답안들 (그 체크리스트를 만들 때 본 답안들이다)
      · 예측  = 겹 k 답안들
    체크리스트도 가중치도 겹 k 답안을 보지 않고 만들어지므로 누출이 없다.

    돌려주는 값은 (답안 id -> 예측 점수, 문항·겹마다 배운 것)이다.
    배운 비중을 함께 돌려주는 이유: 점수만 있고 근거가 없으면 이 프로젝트에서는 결함이다.
    """
    preds: dict[str, int] = {}
    learned: dict[str, dict] = {}

    by_prompt: dict[str, list[str]] = defaultdict(list)
    for (rid, _fold) in recs:
        if rid not in by_prompt[prompt_of[rid]]:
            by_prompt[prompt_of[rid]].append(rid)

    for pkey, ids in sorted(by_prompt.items()):
        ids = sorted(set(ids))
        fold_info = []
        for k in range(N_FOLDS):
            items = items_for(checklists, pkey, k)
            names = [str(it["id"]) for it in items]
            if not names:
                continue

            test_ids = [r for r in ids if fold_of[r] == k and (r, k) in recs]
            train_ids = [r for r in ids if fold_of[r] != k and (r, k) in recs]
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

            X_train = np.array([binary_vector(recs[(r, k)], items) for r in train_ids],
                               dtype=float)
            X_test = np.array([binary_vector(recs[(r, k)], items) for r in test_ids],
                              dtype=float)
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
                # 항목별로 배운 비중 = 이 항목을 충족하면 점수가 몇 점 오르는가
                "coefficients": {cid: round(float(c), 4)
                                 for cid, c in zip(names, model.coef_)},
                "questions": {str(it["id"]): it["question"] for it in items},
            })

        learned[pkey] = {"method": "J", "n_rows": len(ids), "folds": fold_info}
    return preds, learned


# ── 자체 점검 ────────────────────────────────────────────────────────────────
def self_test() -> int:
    """계산기들이 맞게 도는지 답을 아는 예시로 확인한다(네트워크·파일 안 건드림)."""
    ok = True
    rows_out = []

    def check_eq(label, got, want):
        nonlocal ok
        passed = got == want
        ok &= passed
        rows_out.append([label, str(got), str(want), "통과" if passed else "실패"])

    print("=== 계산기 자체 점검 (analyze_v3) ===")

    # ── 가짜 데이터: 문항 1종·답안 40건. 항목 1 이 점수와 딱 맞물리게 만든다 ──
    ids = [f"R{i:03d}" for i in range(40)]
    rows_by_id = {rid: {"id": rid, "prompt": "문항A", "ref": "가나다",
                        "speaker_id": f"S{i}", "evals": {"content": i % 6}}
                  for i, rid in enumerate(ids)}
    fold_of = {rid: i % N_FOLDS for i, rid in enumerate(ids)}
    prompt_of = {rid: "P" for rid in ids}
    checklists = {"P": {"folds": {str(k): {"status": "ok", "items": [
        {"id": "1", "question": "핵심을 말했는가?", "importance": 90},
        {"id": "2", "question": "덧붙였는가?", "importance": 10},
    ]} for k in range(N_FOLDS)}}}

    # 항목 1 = 점수 3 이상이면 충족, 항목 2 = 홀짝(점수와 무관한 잡음)
    recs = {}
    for i, rid in enumerate(ids):
        score = i % 6
        for k in range(N_FOLDS):
            recs[(rid, k)] = {"items": [{"cid": "1", "met": 1 if score >= 3 else 0},
                                        {"cid": "2", "met": i % 2}]}

    # ① J 학습 — 잡음 항목이 있어도 점수와 맞물린 항목을 잡아내는가
    preds, learned = learn_per_prompt_v3(recs, rows_by_id, fold_of, prompt_of, checklists)
    check_eq("J 가 모든 답안에 점수를 냈다", len(preds), 40)
    check_eq("J 예측이 0~5 안에 있다",
             all(0 <= v <= 5 for v in preds.values()), True)
    # 항목 1(점수와 맞물림)의 비중이 항목 2(잡음)보다 커야 한다
    coefs = learned["P"]["folds"][0]["coefficients"]
    rows_out.append(["항목1 비중 > 항목2 비중", f"{coefs['1']:.2f} vs {coefs['2']:.2f}",
                     "앞이 크다", "통과" if coefs["1"] > coefs["2"] else "실패"])
    ok &= coefs["1"] > coefs["2"]

    # ② 겹을 넘지 않는가 — 시험 겹 답안이 학습에 들어가면 안 된다
    fold0_test = [r for r in ids if fold_of[r] == 0]
    n_train0 = learned["P"]["folds"][0]["n_train"]
    check_eq("겹0 학습 표본 = 전체 − 겹0", n_train0, 40 - len(fold0_test))

    # ③ 판정 읽기 — 방식 이름 끝 숫자를 겹 번호로 읽는가
    judgments = {("A-1", "B3f0", "main"): {"status": "ok", "items": []},
                 ("A-1", "B3f3", "main"): {"status": "ok", "items": []},
                 ("A-1", "B3f1", "main"): {"status": "failed", "items": []},
                 ("A-1", "B3f2", "rep1"): {"status": "ok", "items": []}}
    parsed = v3_records(judgments, "main")
    check_eq("성공한 main 판정만, 겹 번호와 함께", sorted(parsed), [("A-1", 0), ("A-1", 3)])

    # ④ 충족율 → 점수 (v1 규칙을 그대로 쓴다)
    got = [ratio_to_score(v) for v in (0.0, 1 / 3, 0.5, 2 / 3, 1.0)]
    rows_out.append(["충족율→점수 [0, 1/3, .5, 2/3, 1]", str(got), "[0, 2, 3, 3, 5]",
                     "통과" if got == [0, 2, 3, 3, 5] else "실패"])
    ok &= got == [0, 2, 3, 3, 5]

    # ⑤ 천장은 실제 방식보다 낮을 수 없다(정답을 보고 맞추므로)
    vec = {rid: [float(recs[(rid, 0)]["items"][0]["met"]),
                 float(recs[(rid, 0)]["items"][1]["met"])] for rid in ids}
    truth = [human_score(rows_by_id[r]) for r in ids]
    plain = [ratio_to_score(sum(vec[r]) / 2) for r in ids]
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
    ap = argparse.ArgumentParser(description="v1·v2·v3 의 모든 방식을 한 표에서 견준다")
    ap.add_argument("--judgments-v1", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--judgments-v2", type=Path, default=DEFAULT_OUT_V2)
    ap.add_argument("--judgments-v3", type=Path, default=DEFAULT_OUT_V3)
    ap.add_argument("--out", type=Path, default=SUMMARY_V3_PATH)
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
    checklists_v1 = load_checklists()
    checklists_v2 = load_checklists_v2()
    checklists_v3 = load_checklists_v3()
    j1, j2, j3 = (load_done(args.judgments_v1), load_done(args.judgments_v2),
                  load_done(args.judgments_v3))

    print("=== 표본 ===")
    print_table(["단계", "건수"], [[k, v] for k, v in counts.items()])
    print(f"화자 {len({str(r.get('speaker_id')) for r in rows})}명 · "
          f"겹: 화자 단위 {N_FOLDS}겹 · 겹을 넘나든 화자 {diag['speaker_leak_count']}명")

    # ── 체크리스트 항목 수: v1 vs v2 vs v3 ───────────────────────────────────
    print("\n=== 체크리스트 항목 수 (v3 는 겹마다 다르다) ===")
    item_rows, v3_counts_json = [], {}
    for pkey in sorted(checklists_v3):
        per_fold = [len(items_for(checklists_v3, pkey, k)) for k in range(N_FOLDS)]
        v2_items = checklists_v2.get(pkey, {}).get("items", [])
        item_rows.append([
            pkey, (checklists_v3[pkey].get("prompt") or "")[:20],
            len(checklists_v1.get(pkey, {}).get("items", [])), len(v2_items),
            *per_fold, f"{sum(per_fold) / len(per_fold):.1f}",
        ])
        v3_counts_json[pkey] = {"per_fold": per_fold,
                                "mean": sum(per_fold) / len(per_fold)}
    print_table(["문항", "지시문", "v1", "v2", "v3 겹0", "겹1", "겹2", "겹3", "겹4", "v3 평균"],
                item_rows)

    # ── 겹 사이 항목이 얼마나 닮았나 (이 방식이 치르는 값) ───────────────────
    print("\n=== v3 의 비용: 같은 문항의 다섯 벌이 서로 얼마나 닮았나 ===")
    agree_rows, agree_json = [], {}
    for pkey in sorted(checklists_v3):
        folds = {k: v for k, v in (checklists_v3[pkey].get("folds") or {}).items()
                 if v.get("status") == "ok"}
        agree = fold_agreement(folds)
        agree_json[pkey] = agree
        agree_rows.append([pkey, (checklists_v3[pkey].get("prompt") or "")[:20],
                           fmt(agree["mean_similarity"]), fmt(agree["matched_rate"]),
                           fmt(agree["min_similarity"]), fmt(agree["max_similarity"])])
    print_table(["문항", "지시문", "문구 닮음(평균)", "짝지어진 비율", "최소", "최대"], agree_rows)
    all_sims = [v["mean_similarity"] for v in agree_json.values()]
    all_match = [v["matched_rate"] for v in agree_json.values()]
    print(f"  문항 9종 평균: 문구 닮음 {statistics.mean(all_sims):.3f} · "
          f"짝지어진 비율 {statistics.mean(all_match):.3f}")
    print("  ※ 글자 겹침으로 재므로 같은 뜻을 다른 말로 쓴 항목은 낮게 나온다(닮음의 하한).")

    # ── v1·v2 방식 (앞 실험 결과를 그대로 읽는다) ────────────────────────────
    main1 = {(rid, m): rec for (rid, m, p), rec in j1.items() if p == "main"}
    records_b1 = {rid: rec for (rid, m), rec in main1.items() if m == "B"}
    c_preds, _ = compute_method_c(records_b1, rows_by_id, fold_of, checklists_v1)

    main2 = {(rid, m): rec for (rid, m, p), rec in j2.items() if p == "main"}
    rec_b2 = {rid: rec for (rid, m), rec in main2.items()
              if m == "B2" and rec.get("status") == "ok"}
    rec_s2 = {rid: rec for (rid, m), rec in main2.items()
              if m == "S2" and rec.get("status") == "ok"}
    items_v2 = {p: included_items(e, False) for p, e in checklists_v2.items()}
    names_v2 = {p: [str(it["id"]) for it in v] for p, v in items_v2.items()}
    vec_bin_v2 = {rid: binary_vector(rec, items_v2[prompt_of[rid]])
                  for rid, rec in rec_b2.items() if prompt_of[rid] in items_v2}
    vec_scr_v2 = {rid: score_vector(rec, items_v2[prompt_of[rid]])
                  for rid, rec in rec_s2.items() if prompt_of[rid] in items_v2}
    f_preds, _ = learn_per_prompt(vec_bin_v2, prompt_of, rows_by_id, fold_of, names_v2, "F")
    h_preds, _ = learn_per_prompt(vec_scr_v2, prompt_of, rows_by_id, fold_of, names_v2, "H")

    # ── v3 판정 읽기 ─────────────────────────────────────────────────────────
    rec_v3 = v3_records(j3, "main")
    print(f"\nv3 판정: {len(rec_v3)}건 성공 "
          f"(기대 {len(rows_by_id)}건 × {N_FOLDS}겹 = {len(rows_by_id) * N_FOLDS}건)")

    j_preds, j_learned = learn_per_prompt_v3(rec_v3, rows_by_id, fold_of,
                                             prompt_of, checklists_v3)
    Path(J_WEIGHTS_PATH).parent.mkdir(parents=True, exist_ok=True)
    Path(J_WEIGHTS_PATH).write_text(
        json.dumps({"J": j_learned}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"J 가 문항·겹마다 항목 비중을 배웠다(LLM 호출 0회). 근거 저장: {J_WEIGHTS_PATH}")

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
                reasons.append(f"{name}:{'미실행' if main2.get((rid, name)) is None else '실패'}")
        if rid not in f_preds:
            reasons.append("F:예측없음")
        if rid not in h_preds:
            reasons.append("H:예측없음")
        # v3 는 **다섯 벌 판정이 모두** 있어야 학습과 천장 계산이 성립한다
        missing_folds = [k for k in range(N_FOLDS) if (rid, k) not in rec_v3]
        if missing_folds:
            reasons.append(f"v3:겹{','.join(map(str, missing_folds))} 판정없음")
        if rid not in j_preds:
            reasons.append("J:예측없음")
        (dropped[" / ".join(reasons)] if reasons else usable).append(rid)

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
    # v3 자기 겹 벡터 — 실제 채점에 쓰이는 배치다
    vec_v3_own = {rid: binary_vector(rec_v3[(rid, fold_of[rid])],
                                     items_for(checklists_v3, prompt_of[rid], fold_of[rid]))
                  for rid in usable}
    items_own = {rid: items_for(checklists_v3, prompt_of[rid], fold_of[rid])
                 for rid in usable}
    # 겹벌 벡터 — "겹 k 의 체크리스트를 281건 전부에 썼다면"
    vec_v3_by_fold = {
        k: {rid: binary_vector(rec_v3[(rid, k)], items_for(checklists_v3, prompt_of[rid], k))
            for rid in usable}
        for k in range(N_FOLDS)
    }

    preds = {
        "A0": [int(main1[(rid, "A0")]["pred"]) for rid in usable],
        "A1": [int(main1[(rid, "A1")]["pred"]) for rid in usable],
        "B": [int(main1[(rid, "B")]["pred"]) for rid in usable],
        "C": [int(c_preds[rid]) for rid in usable],
        "D": [ratio_to_score(weighted_ratio(vec_bin_v2[rid], items_v2[prompt_of[rid]], False))
              for rid in usable],
        "E": [ratio_to_score(weighted_ratio(vec_bin_v2[rid], items_v2[prompt_of[rid]], True))
              for rid in usable],
        "F": [int(f_preds[rid]) for rid in usable],
        "G": [ratio_to_score(weighted_ratio(vec_scr_v2[rid], items_v2[prompt_of[rid]], True))
              for rid in usable],
        "H": [int(h_preds[rid]) for rid in usable],
        "I": [ratio_to_score(weighted_ratio(vec_v3_own[rid], items_own[rid], False))
              for rid in usable],
        "I_imp": [ratio_to_score(weighted_ratio(vec_v3_own[rid], items_own[rid], True))
                  for rid in usable],
        "J": [int(j_preds[rid]) for rid in usable],
    }

    # 기준선 — 같은 표본·같은 겹에서 잰다
    mean_p = baseline_mean(usable, rows_by_id, fold_of)
    len_p = baseline_length(usable, rows_by_id, fold_of)
    preds["MEAN"] = [mean_p[rid] for rid in usable]
    preds["LEN"] = [len_p[rid] for rid in usable]

    # ── 천장 ─────────────────────────────────────────────────────────────────
    v1_items = {p: e.get("items", []) for p, e in checklists_v1.items()}
    vec_bin_v1 = {}
    for rid in usable:
        got = {i["cid"]: i["met"] for i in records_b1[rid].get("items", [])}
        vec_bin_v1[rid] = [float(got.get(str(it["id"]), 0))
                           for it in v1_items[prompt_of[rid]]]
    n_items_v1 = {p: len(v) for p, v in v1_items.items()}
    n_items_v2 = {p: len(v) for p, v in items_v2.items()}

    ceilings = {
        "CEIL_V1_CNT": ceiling_by_met_count(usable, rows_by_id, vec_bin_v1, prompt_of),
        "CEIL_V1_OPT": ceiling_by_met_count_optimized(usable, rows_by_id, vec_bin_v1,
                                                      prompt_of, n_items_v1),
        "CEIL_V1_LIN": ceiling_by_linear_fit(usable, rows_by_id, vec_bin_v1, prompt_of),
        "CEIL_V2_CNT": ceiling_by_met_count(usable, rows_by_id, vec_bin_v2, prompt_of),
        "CEIL_V2_OPT": ceiling_by_met_count_optimized(usable, rows_by_id, vec_bin_v2,
                                                      prompt_of, n_items_v2),
        "CEIL_V2_LIN": ceiling_by_linear_fit(usable, rows_by_id, vec_bin_v2, prompt_of),
    }
    # ① 겹벌 천장 — v2 의 천장과 나란히 놓을 수 있는 것은 이쪽이다
    for k in range(N_FOLDS):
        n_items_v3k = {p: len(items_for(checklists_v3, p, k)) for p in set(prompt_of.values())}
        ceilings[f"CEIL_V3_CNT_f{k}"] = ceiling_by_met_count(
            usable, rows_by_id, vec_v3_by_fold[k], prompt_of)
        ceilings[f"CEIL_V3_OPT_f{k}"] = ceiling_by_met_count_optimized(
            usable, rows_by_id, vec_v3_by_fold[k], prompt_of, n_items_v3k)
        ceilings[f"CEIL_V3_LIN_f{k}"] = ceiling_by_linear_fit(
            usable, rows_by_id, vec_v3_by_fold[k], prompt_of)

    # ② 실배치 천장 — 답안마다 자기 겹의 체크리스트로. 칸을 (문항, 겹)까지 갈라야 하므로
    #    `prompt_of` 자리에 "문항#겹" 을 넣어 준다(칸이 잘게 쪼개져 낙관 쪽으로 부푼다)
    prompt_fold_of = {rid: f"{prompt_of[rid]}#{fold_of[rid]}" for rid in usable}
    n_items_own = {f"{p}#{k}": len(items_for(checklists_v3, p, k))
                   for p in set(prompt_of.values()) for k in range(N_FOLDS)}
    ceilings["CEIL_V3_CNT_OWN"] = ceiling_by_met_count(
        usable, rows_by_id, vec_v3_own, prompt_fold_of)
    ceilings["CEIL_V3_OPT_OWN"] = ceiling_by_met_count_optimized(
        usable, rows_by_id, vec_v3_own, prompt_fold_of, n_items_own)

    for name, table in ceilings.items():
        preds[name] = [table[rid] for rid in usable]

    # ── 성적과 신뢰구간 ──────────────────────────────────────────────────────
    metrics = {m: all_metrics(p, truth) for m, p in preds.items()}
    print(f"\n부트스트랩 {args.bootstrap}회 계산 중 (화자를 통째로 다시 뽑는다)...")
    cis, diff_cis = bootstrap_qwk_ci(preds, truth, speakers, args.bootstrap, SEED)

    def row_for(m: str) -> list:
        return [METHOD_LABELS.get(m, m), fmt(metrics[m]["qwk"]),
                f"[{fmt(cis[m]['lo'])}, {fmt(cis[m]['hi'])}]",
                fmt(metrics[m]["spearman"]),
                f"{metrics[m]['exact']:.1%}", f"{metrics[m]['within1']:.1%}",
                f"{statistics.mean(preds[m]):.2f}"]

    headers = ["방식", "QWK", "95% 신뢰구간", "스피어만", "정확일치", "±1 이내", "평균예측"]
    print(f"\n{'=' * 92}")
    print(f"  ① 방식별 성적 — 같은 겹의 out-of-fold 예측만 (표본 {len(usable)}건 · "
          f"화자 {len(set(speakers))}명)")
    print("=" * 92)
    print_table(headers, [row_for(m) for m in
                          ("A0", "A1", "B", "C", "D", "E", "F", "G", "H",
                           "I", "I_imp", "J", "MEAN", "LEN")])
    print(f"  참고: 사람 점수 평균 {statistics.mean(truth):.2f} · "
          f"분포 {dict(sorted(Counter(truth).items()))}")
    print("  ※ K(소프트 패스 확률 + 학습)는 없다 — 2단계 예비조사가 "
          "'확률 대체재를 쓸 수 없다'로 나와 소프트 패스를 돌리지 않았다.")

    # ── 천장 표 ──────────────────────────────────────────────────────────────
    print(f"\n{'=' * 92}\n  ② 정보 천장 — 이번 실험의 핵심 질문 "
          f"(v2 의 선형 천장 0.797 을 넘는가)\n{'=' * 92}")
    print_table(headers, [row_for(m) for m in
                          ("CEIL_V1_CNT", "CEIL_V1_OPT", "CEIL_V1_LIN",
                           "CEIL_V2_CNT", "CEIL_V2_OPT", "CEIL_V2_LIN")])
    print("\n  v3 겹벌 천장 — '겹 k 의 체크리스트를 281건 전부에 썼다면' (v2 와 같은 조건)")
    v3_ceiling_json = {}
    for kind, label in (("CNT", "충족 개수·중앙값 사상"),
                        ("OPT", "충족 개수·QWK 최대 사상"),
                        ("LIN", "정답 보고 선형 적합")):
        values = [metrics[f"CEIL_V3_{kind}_f{k}"]["qwk"] for k in range(N_FOLDS)]
        v3_ceiling_json[kind] = {
            "per_fold": values, "mean": statistics.mean(values),
            "min": min(values), "max": max(values),
            "v2_same_kind": metrics[f"CEIL_V2_{kind}"]["qwk"],
        }
        print(f"    {label:24s} 겹별 {[f'{v:.3f}' for v in values]} · "
              f"평균 {statistics.mean(values):.3f} · 폭 {min(values):.3f}~{max(values):.3f} "
              f"(v2 같은 계산: {metrics[f'CEIL_V2_{kind}']['qwk']:.3f})")
    print("\n  v3 실배치 천장 — 답안마다 자기 겹의 체크리스트로 (참고용)")
    print_table(headers, [row_for(m) for m in ("CEIL_V3_CNT_OWN", "CEIL_V3_OPT_OWN")])
    print("  ※ 실배치 천장은 칸이 (문항 × 겹)까지 쪼개져 답안 6~8건마다 점수를 따로 고르는 셈이라"
          " 낙관 쪽으로 부푼다. v2 와 견주지 말 것.")
    print("  ※ 천장은 정답을 보고 맞춘 값이라 실제 채점에 쓸 수 없다. "
          "항목이 많을수록 저절로 올라간다.")

    # ── 방식 간 차이 ─────────────────────────────────────────────────────────
    print(f"\n{'=' * 92}\n  ③ 방식 간 차이가 우연인가 (화자 다시뽑기 "
          f"{args.bootstrap}회, 95% 구간)\n{'=' * 92}")
    key_pairs = [
        ("J", "F"), ("J", "C"), ("J", "A1"), ("J", "LEN"), ("J", "I"),
        ("I", "D"), ("I", "B"), ("I", "LEN"), ("I_imp", "I"),
        ("J", "CEIL_V3_LIN_f0"),
    ]
    key_pairs += [(f"CEIL_V3_LIN_f{k}", "CEIL_V2_LIN") for k in range(N_FOLDS)]
    key_pairs += [(f"CEIL_V3_OPT_f{k}", "CEIL_V2_OPT") for k in range(N_FOLDS)]
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

    # ── 문항별 QWK ───────────────────────────────────────────────────────────
    print(f"\n{'=' * 92}\n  ④ 문항별 QWK (문항당 표본이 작아 참고용)\n{'=' * 92}")
    by_prompt_idx = defaultdict(list)
    for i, rid in enumerate(usable):
        by_prompt_idx[prompt_of[rid]].append(i)
    per_prompt_json, per_prompt_rows = {}, []
    shown = ("A1", "C", "F", "I", "J")
    for pkey, idxs in sorted(by_prompt_idx.items()):
        t = [truth[i] for i in idxs]
        entry = {m: qwk([preds[m][i] for i in idxs], t) for m in shown}
        per_prompt_json[pkey] = {"n": len(idxs), **entry}
        per_prompt_rows.append([pkey, len(idxs), *[fmt(entry[m]) for m in shown]])
    print_table(["문항", "건수", *shown], per_prompt_rows)

    # ── 재현성 ───────────────────────────────────────────────────────────────
    print(f"\n{'=' * 92}\n  ⑤ 재현성 — 같은 답안을 같은 설정으로 3회 판정 "
          f"(고정 부분표본, v1·v2 와 같은 60건)\n{'=' * 92}")
    repro_ids = [str(r["id"]) for r in select_repro_subset(rows, args.repro_n)]
    per_score: dict[str, list[int]] = {}
    cell_total, cell_flipped = 0, 0
    for rid in repro_ids:
        fold = fold_of[rid]
        recs = [j3.get((rid, f"B3f{fold}", tag)) for tag in ("rep1", "rep2", "rep3")]
        if any(r is None or r.get("status") != "ok" for r in recs):
            continue
        items = items_for(checklists_v3, prompt_of[rid], fold)
        vectors = [binary_vector(r, items) for r in recs]
        per_score[rid] = [ratio_to_score(weighted_ratio(v, items, False)) for v in vectors]
        # 항목 한 칸이 3회 내내 같은 판정이었는지 센다
        for pos in range(len(items)):
            cell_total += 1
            if len({v[pos] for v in vectors}) > 1:
                cell_flipped += 1
    repro = {
        "n_passes": 3, "subset_size": len(repro_ids), "n_measured": len(per_score),
        "exact_agreement": (sum(1 for v in per_score.values() if len(set(v)) == 1)
                            / len(per_score)) if per_score else float("nan"),
        "mean_amplitude": (sum(max(v) - min(v) for v in per_score.values())
                           / len(per_score)) if per_score else float("nan"),
        "item_cells": cell_total, "item_cells_flipped": cell_flipped,
        "item_flip_rate": (cell_flipped / cell_total) if cell_total else float("nan"),
    }
    if not per_score:
        print("  아직 재현성 실행(rep1·rep2·rep3)이 없다. 이 항목은 '미측정'으로 남긴다.")
    else:
        print(f"  3회 다 성공한 답안 {repro['n_measured']}건 · "
              f"최종 점수 완전일치율 {repro['exact_agreement']:.3f} · "
              f"평균 진폭 {repro['mean_amplitude']:.3f}")
        print(f"  항목 0/1 뒤집힘: {cell_flipped}/{cell_total}칸 "
              f"({repro['item_flip_rate']:.3f})")

    # ── 예비조사 결과 싣기 ───────────────────────────────────────────────────
    probe = json.loads(Path(PROBE_PATH).read_text(encoding="utf-8")) \
        if Path(PROBE_PATH).exists() else {}
    if probe:
        print(f"\n{'=' * 92}\n  ⑥ 확률 판정(logprobs 대체재) 예비조사\n{'=' * 92}")
        print_table(["온도", "잰 칸", "갈린 칸", "갈린 비율", "갈린 칸 확률 평균"],
                    [[t, v["n_cells"], v["n_split_cells"], f"{v['split_rate']:.1%}",
                      f"{v['split_prob_mean']:.3f}" if v["split_prob_mean"] is not None else "-"]
                     for t, v in probe.get("by_temperature", {}).items()])
        print(f"  → {probe.get('verdict', '')}")

    # ── 저장 ─────────────────────────────────────────────────────────────────
    fail_counts = Counter()
    for (rid, m, p), rec in j3.items():
        if rec.get("status") != "ok":
            fail_counts[f"{p}/{m}/{rec.get('status')}"] += 1
    elapsed_total = sum(float(rec.get("elapsed_sec") or 0.0) for rec in j3.values())

    # 항목이 얼마나 골고루 갈렸는지 — 모두 통과하는 항목은 정보를 못 준다
    item_pass_rate = []
    for rid in usable:
        item_pass_rate.extend(vec_v3_own[rid])
    saturation = {
        "mean_item_pass_rate": statistics.mean(item_pass_rate) if item_pass_rate else float("nan"),
        "n_answers_all_met": sum(1 for rid in usable
                                 if vec_v3_own[rid] and all(v == 1 for v in vec_v3_own[rid])),
        "n_answers_none_met": sum(1 for rid in usable
                                  if vec_v3_own[rid] and all(v == 0 for v in vec_v3_own[rid])),
        "설명": "항목 통과율이 1에 가까울수록 '모두 통과'라 점수를 가르지 못한다.",
    }

    summary = {
        "run_date": time.strftime("%Y-%m-%d %H:%M:%S"),
        "experiment": "체크리스트 v3 — 실제 학습 겹 답안 + 사람 점수를 보고 겹마다 따로 생성",
        "model": JUDGE_MODEL,
        "temperature_main": 0.0,
        "input_type": "사람이 직접 적은 전사(ref)",
        "human_label_field": "evals.content (내용 및 과제 수행, 0~5)",
        "design": {
            "checklists_per_prompt": N_FOLDS,
            "leakage_guard": "겹 k 의 체크리스트는 겹 k 답안을 한 건도 보지 않고 만든다",
            "exemplars_per_checklist": 8,
            "exemplar_selection": "학습 겹에서 점수 층화(높음2·낮음2·중간2·고정씨앗 무작위2)",
            "judgments_per_answer": N_FOLDS,
            "scoring_uses": "자기 겹의 체크리스트로 받은 판정만",
        },
        "logprobs_status": {
            **(probe.get("logprobs_status") or {}),
            "probe_result": {
                "n_cells": probe.get("n_cells_total"),
                "n_split_cells": probe.get("n_split_cells_total"),
                "split_rate": probe.get("split_rate_overall"),
                "threshold": probe.get("threshold"),
                "by_temperature": probe.get("by_temperature"),
                "verdict": probe.get("verdict"),
            },
            "seed_determinism": probe.get("seed_determinism"),
            "soft_pass_run": bool(probe.get("soft_pass_enabled")),
            "method_K": "예비조사가 기준에 못 미쳐 소프트 패스를 돌리지 않았다. K 는 없다.",
        },
        "dataset": {**counts, "n_speakers": len({str(r.get("speaker_id")) for r in rows})},
        "checklist_items_v3": v3_counts_json,
        "fold_agreement": {**agree_json,
                           "overall_mean_similarity": statistics.mean(all_sims),
                           "overall_matched_rate": statistics.mean(all_match),
                           "설명": "같은 문항의 다섯 벌이 서로 얼마나 닮았는지. "
                                   "글자 겹침으로 재므로 닮음의 하한이다."},
        "item_saturation": saturation,
        "common_sample": {"n": len(usable), "n_speakers": len(set(speakers)),
                          "n_excluded": len(rows_by_id) - len(usable),
                          "excluded_reasons": {k: len(v) for k, v in dropped.items()}},
        "methods": {
            m: {"label": METHOD_LABELS.get(m, m),
                "uses_training_data": m in ("A1", "C", "F", "H", "J", "LEN", "MEAN"),
                "is_ceiling": m.startswith("CEIL"),
                **metrics[m], "qwk_ci95": cis[m],
                "mean_pred": statistics.mean(preds[m])}
            for m in preds
        },
        "v3_ceilings": v3_ceiling_json,
        "key_comparisons": pair_json,
        "pairwise_diff_qwk_ci95": {name: {**d, "verdict": verdict(d)}
                                   for name, d in diff_cis.items()},
        "per_prompt_qwk": per_prompt_json,
        "reproducibility": repro,
        "citation_protocol": {
            "v3_dropped_citations_total": sum(int(rec.get("dropped_citations", 0))
                                              for rec in rec_v3.values()),
            "설명": "충족(1)이라고 했는데 근거 인용이 답안 원문에 없으면 폐기하고 "
                    "미충족(0)으로 내린다. v1·v2 와 같은 규약이다.",
        },
        "failures": dict(fail_counts),
        "n_llm_calls_recorded_v3": len(j3),
        "llm_seconds_recorded_v3": round(elapsed_total, 1),
        "limitations": [
            "겹마다 체크리스트가 다르다. 같은 문항인데 응시자마다 다른 시험지로 채점되는 "
            "셈이라, 실제 시험에 쓰려면 한 벌로 굳히는 절차가 따로 필요하다.",
            "체크리스트를 만들 때 사람 점수를 보여 주었다. 학습 겹 점수만 보았으므로 "
            "시험 겹 누출은 없지만, 사람 점수가 없는 새 문항에는 이 방식을 그대로 쓸 수 없다.",
            "문항당 답안이 27~40건뿐이고, J 는 겹마다 항목 수만큼의 가중치를 "
            "20~32건으로 배운다. 과적합 위험이 v2 보다 크지는 않지만 표본이 작다.",
            "천장(선형 적합)은 항목이 많을수록 저절로 올라간다. 겹벌 천장으로만 v2 와 견줘야 한다.",
            "AI Hub 데이터는 우리 시험(직무 한국어)과 과제 성격이 다르다.",
            f"판정 모델은 {JUDGE_MODEL} 하나뿐이다. 다른 모델에서도 같은 순위가 나올지는 안 쟀다.",
        ],
        "files": {
            "checklists_v1": str(OUT_DIR / "checklists.json"),
            "checklists_v2": str(OUT_DIR / "checklists_v2.json"),
            "checklists_v3": str(CHECKLIST_V3_PATH),
            "judgments_v1": str(args.judgments_v1),
            "judgments_v2": str(args.judgments_v2),
            "judgments_v3": str(args.judgments_v3),
            "probe": str(PROBE_PATH),
            "j_model_weights": str(J_WEIGHTS_PATH),
            "summary_v1": str(OUT_DIR / "results_summary.json"),
            "summary_v2": str(OUT_DIR / "results_summary_v2.json"),
            "summary_v3": str(args.out),
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
