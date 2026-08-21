# -*- coding: utf-8 -*-
"""네 방식의 점수를 '해석'하기 위한 기준선 세 개를 같은 시험지에서 잰다.

QWK 0.5 는 좋은 걸까 나쁜 걸까? 혼자 있는 숫자로는 알 수 없다.
그래서 아래·위를 막아 주는 기준선을 같은 표본·같은 겹으로 재서 옆에 세운다.

  ① 바닥선(mean)   — 답안을 **아예 읽지 않고** 학습 겹의 평균 점수만 답한다.
                     여기보다 못하면 그 방식은 정보를 하나도 못 쓴 것이다.
  ② 길이 기준선    — 답안의 **글자 수 하나만** 보고 점수를 맞힌다(문항별 릿지).
                     8/7 자질 실험에서 "이긴 자질이 전부 길이였다"는 함정을 봤으므로,
                     채점 방식이 길이보다 나은지를 매번 확인해야 한다.
  ③ 체크리스트 상한 — 충족 개수(0·1·2)를 **정답을 다 보고** 가장 유리하게 점수로
                     바꾼다(전체 데이터로 적합). 실제로는 쓸 수 없는 낙관적 값이라,
                     "체크리스트 2개가 들고 있는 정보의 최대치"를 뜻한다.
                     B·C 가 이 선에 붙어 있으면 결합 방식이 아니라 **항목 자체**가
                     병목이라는 뜻이다.

쓰는 법:
    python extra_baselines.py
"""

from __future__ import annotations

import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from sklearn.linear_model import RidgeCV

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _lab_common import (  # noqa: E402
    N_FOLDS,
    OUT_DIR,
    SCORE_LABELS,
    assign_folds,
    bootstrap_qwk_ci,
    enable_utf8_output,
    human_score,
    load_done,
    load_rows,
    print_table,
    qwk,
    verdict,
)
from analyze import (  # noqa: E402
    RIDGE_ALPHAS,
    build_common_sample,
    compute_method_c,
    round_half_up,
)
from gen_checklists import load_checklists  # noqa: E402
from run_experiment import DEFAULT_OUT  # noqa: E402

OUT_PATH = OUT_DIR / "extra_baselines.json"


def baseline_mean(ids, rows_by_id, fold_of):
    """학습 겹의 평균 점수만 답한다. 답안은 읽지 않는다."""
    preds = {}
    by_fold = defaultdict(list)
    for rid in ids:
        by_fold[fold_of[rid]].append(rid)
    for k in range(N_FOLDS):
        train = [r for r in ids if fold_of[r] != k]
        if not train:
            continue
        value = round_half_up(float(np.mean([human_score(rows_by_id[r]) for r in train])))
        for rid in by_fold[k]:
            preds[rid] = value
    return preds


def baseline_length(ids, rows_by_id, fold_of):
    """답안 글자 수 하나로 점수를 맞힌다. 문항별로 배우고 out-of-fold 로만 답한다."""
    preds = {}
    by_prompt = defaultdict(list)
    for rid in ids:
        by_prompt[rows_by_id[rid]["prompt"]].append(rid)

    for _, group in by_prompt.items():
        group.sort()
        # 글자 수는 값이 크고 들쭉날쭉해서 그대로 넣으면 규제가 한쪽만 누른다.
        # 로그를 씌워 '두 배 길어졌다'가 일정한 크기가 되게 한다
        X = np.array([[math.log1p(len(rows_by_id[r]["ref"]))] for r in group], dtype=float)
        y = np.array([human_score(rows_by_id[r]) for r in group], dtype=float)
        folds = np.array([fold_of[r] for r in group])
        for k in range(N_FOLDS):
            test = folds == k
            train = ~test
            if test.sum() == 0:
                continue
            if train.sum() < 5 or float(np.std(y[train])) < 1e-9:
                fill = round_half_up(float(np.mean(y[train]))) if train.sum() else 0
                for rid in np.array(group)[test]:
                    preds[str(rid)] = fill
                continue
            model = RidgeCV(alphas=RIDGE_ALPHAS)
            model.fit(X[train], y[train])
            for rid, value in zip(np.array(group)[test], model.predict(X[test])):
                preds[str(rid)] = round_half_up(float(value))
    return preds


def ceiling_checklist(ids, rows_by_id, records_b, checklists):
    """충족 개수를 문항별로 **가장 유리하게** 점수로 바꾼다(낙관적 상한).

    정답을 다 보고 고르므로 실제 채점에는 쓸 수 없다. 오직 "체크리스트가 들고 있는
    정보로 사람 점수를 어디까지 맞힐 수 있나"의 천장을 보여 주는 값이다.
    """
    preds = {}
    by_prompt = defaultdict(list)
    for rid in ids:
        by_prompt[records_b[rid]["prompt_key"]].append(rid)

    for pkey, group in by_prompt.items():
        n_items = len(checklists.get(pkey, {}).get("items", []))
        # 충족 개수별로 모아, 그 무리의 사람 점수 중앙값을 그 개수의 답으로 삼는다.
        # (제곱 가중 카파는 큰 어긋남을 크게 벌하므로 평균보다 중앙값이 유리하다)
        bucket = defaultdict(list)
        for rid in group:
            met = sum(int(i["met"]) for i in records_b[rid].get("items", []))
            bucket[met].append(human_score(rows_by_id[rid]))
        table = {}
        for met in range(n_items + 1):
            scores = bucket.get(met)
            table[met] = round_half_up(float(np.median(scores))) if scores else 0
        for rid in group:
            met = sum(int(i["met"]) for i in records_b[rid].get("items", []))
            preds[rid] = table[met]
    return preds


def main() -> int:
    enable_utf8_output()
    rows, _ = load_rows()
    rows_by_id = {str(r["id"]): r for r in rows}
    fold_of, _ = assign_folds(rows, N_FOLDS)
    checklists = load_checklists()
    judgments = load_done(DEFAULT_OUT)

    main_records = {(rid, m): rec for (rid, m, p), rec in judgments.items() if p == "main"}
    records_b = {rid: rec for (rid, m), rec in main_records.items() if m == "B"}
    c_preds, _ = compute_method_c(records_b, rows_by_id, fold_of, checklists)
    usable, _ = build_common_sample(main_records, rows_by_id, c_preds)

    truth = [human_score(rows_by_id[r]) for r in usable]
    speakers = [str(rows_by_id[r].get("speaker_id")) for r in usable]

    mean_p = baseline_mean(usable, rows_by_id, fold_of)
    len_p = baseline_length(usable, rows_by_id, fold_of)
    ceil_p = ceiling_checklist(usable, rows_by_id, records_b, checklists)

    preds = {
        "바닥선(학습겹 평균)": [mean_p[r] for r in usable],
        "길이 기준선(글자 수만)": [len_p[r] for r in usable],
        "B 체크리스트 충족율×5": [int(main_records[(r, "B")]["pred"]) for r in usable],
        "C 체크리스트+가중치 학습": [c_preds[r] for r in usable],
        "체크리스트 상한(정답 보고 사상)": [ceil_p[r] for r in usable],
        "A1 LLM 직접 채점(퓨샷)": [int(main_records[(r, "A1")]["pred"]) for r in usable],
    }
    cis, diffs = bootstrap_qwk_ci(preds, truth, speakers)

    print(f"\n=== 기준선과 나란히 보기 (표본 {len(usable)}건, 같은 겹·같은 사람 점수) ===")
    print_table(
        ["기준선/방식", "QWK", "95% 신뢰구간"],
        [[name, f"{qwk(p, truth):.3f}",
          f"[{cis[name]['lo']:.3f}, {cis[name]['hi']:.3f}]"] for name, p in preds.items()],
    )

    pairs = [
        ("길이 기준선(글자 수만)", "B 체크리스트 충족율×5"),
        ("길이 기준선(글자 수만)", "C 체크리스트+가중치 학습"),
        ("C 체크리스트+가중치 학습", "체크리스트 상한(정답 보고 사상)"),
    ]
    print("\n=== 꼭 봐야 할 비교 ===")
    table = []
    for a, b in pairs:
        key = f"{a}-{b}" if f"{a}-{b}" in diffs else f"{b}-{a}"
        d = diffs[key]
        table.append([key, f"{d['mean']:+.3f}", f"[{d['lo']:+.3f}, {d['hi']:+.3f}]", verdict(d)])
    print_table(["비교(앞 − 뒤)", "차이", "95% 신뢰구간", "판정"], table)

    OUT_PATH.write_text(json.dumps({
        "n": len(usable),
        "qwk": {k: qwk(v, truth) for k, v in preds.items()},
        "ci95": cis,
        "diff_ci95": diffs,
        "note": "상한선은 정답을 보고 사상을 골랐으므로 실제 채점에 쓸 수 없는 낙관적 값이다",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n저장: {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
