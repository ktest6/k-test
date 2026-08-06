# -*- coding: utf-8 -*-
"""손으로 정한 가중치 대신, 사람 점수로 배운 모델(XGBoost)이 더 잘 맞는지 재는 실험.

■ 무엇을 확인하려는 실험인가

지금 채점기는 자질 12개(어휘 다양도, 조사 오류 횟수 ...)를 뽑은 뒤,
사람이 손으로 정한 비중(예: 조사 오류 12%, 어휘 다양도 12% ...)을 곱해 더한다.
그런데 하류 평가에서 **받아쓰기가 완벽한 조건(사람이 직접 쓴 전사)** 에서도
그 점수와 전문 평가자 점수의 상관이 +0.31 밖에 되지 않았다.
즉 병목은 '자질을 잘못 뽑아서'가 아니라 '자질을 더하는 방식'일 가능성이 크다.

이 스크립트는 그 더하는 층만 갈아끼운다.
    자질 12개 → (손 가중치 합산)      → 점수      … 지금 방식, 기준선
    자질 12개 → (사람 점수로 배운 모델) → 점수      … 이번 실험
성공 판정은 하나다: **같은 데이터·같은 검증 절차에서 상관이 0.31보다 유의하게 오르는가.**

■ 왜 end-to-end 모델이 아니라 여기만 바꾸나

`scoring-design` 스킬의 첫 줄이 "정확도가 아니라 설명 가능성"이다.
음성을 넣으면 점수가 튀어나오는 모델은 잘 맞아도 이 시험에서는 쓸 수 없다.
그래서 입력은 여전히 **뜻이 분명한 자질 12개**로 고정하고, 결합만 학습한다.
게다가 XGBoost 는 항목마다 "이 점수에서 조사 오류가 몇 점을 깎았는지"(SHAP)를
정확히 계산해 줄 수 있어서, 예측마다 근거표가 함께 나온다.
이 스크립트가 저장하는 예측 파일에는 항목마다 그 근거표가 들어 있다.

■ 숫자를 정직하게 재기 위해 지킨 것 (심사에서 가장 많이 찔릴 대목)

1. **화자 단위로 갈랐다.** 같은 사람의 발화가 배우는 쪽과 시험 보는 쪽에
   나뉘어 들어가면, 모델이 '한국어 실력'이 아니라 '그 사람의 말버릇'을 외워서
   점수가 부풀려진다. 그래서 화자 번호로 묶어서 통째로 갈랐다(GroupKFold).
2. **기준선도 똑같은 시험지로 채점했다.** 손 가중치 점수를 전체 107건에서 재고
   학습 모델은 검증 겹에서 재면 비교가 되지 않는다. 둘 다 '한 번도 안 본 항목'
   에서만 잰다.
3. **차이가 우연인지 따로 쟀다.** 표본이 107건뿐이라 상관 0.31 -> 0.4 정도는
   운으로도 흔들린다. 화자를 다시 뽑는 방식으로 1000번 되풀이해서
   "두 상관의 차이"가 0을 넘는 구간에 있는지 본다. 0을 걸치면 '올랐다'고 말하지 않는다.
4. **나무 개수 고르기도 검증 겹 안에서만 했다.** 시험 볼 항목을 보고 개수를 고르면
   그건 답을 보고 시험 치는 것이다.
5. 씨앗값 42 고정. 같은 명령을 두 번 돌리면 같은 숫자가 나온다.

■ 쓰는 법

    C:\\해커톤\\.venv\\Scripts\\python.exe assessment/scripts/speech_lab/train_score_model.py
    ... --data D:\\해커톤데이터\\downstream_results.jsonl --folds 5 --seed 42

    # 계산 함수들이 제대로 도는지 예시 입력으로 확인만 하고 끝내기
    ... --selftest
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
from scipy import stats
from sklearn.metrics import cohen_kappa_score
from sklearn.model_selection import GroupKFold

try:
    import xgboost as xgb
except ImportError:  # pragma: no cover - 설치 안내만 하고 끝낸다
    raise SystemExit(
        "xgboost 가 없다. 다음을 먼저 실행하라:\n"
        "  C:\\해커톤\\.venv\\Scripts\\python.exe -m pip install xgboost"
    )

# ── 이 스크립트가 쓰는 고정값 ────────────────────────────────────────────────

#: 입력으로 쓰는 자질 12개. 순서를 바꾸면 저장된 모델과 어긋나므로 고정이다.
#: (앞 8개 = Kiwi 규칙 자질 / 뒤 4개 = LLM 이 근거 인용과 함께 뽑은 오류 자질)
FEATURE_IDS = [
    "lexical_diversity_mattr",       # 어휘 다양도 — 같은 단어를 얼마나 안 되풀이하나
    "advanced_vocab_ratio",          # 고급 어휘 비율 — 국립국어원 등급 목록 기준
    "lexical_density",               # 어휘 밀도 — 내용어(명사·동사 등)가 차지하는 비율
    "clause_density",                # 절 밀도 — 문장 하나에 절이 몇 개나 들어가나
    "connective_ending_diversity",   # 연결어미 다양성 — '-고'만 쓰는지, 여러 개 쓰는지
    "formality",                     # 격식체 비율 — '-습니다/-어요' 를 지켰나
    "banmal_penalty",                # 반말 혼입 횟수 — 직무 상황에서 특히 중요한 축
    "subject_honorific_si",          # 주체 높임 '-시-' 빈도
    "error_josa",                    # 조사 오류 건수 (LLM 판정)
    "error_conjugation",             # 어미 활용 오류 건수 (LLM 판정)
    "error_word_choice",             # 어휘 오용 건수 (LLM 판정)
    "error_honorific",               # 높임법 오류 건수 (LLM 판정)
]

#: 사람 점수가 가질 수 있는 값. QWK(등급 일치도)를 잴 때 등급 목록으로 쓴다.
SCORE_LABELS = [0, 1, 2, 3, 4, 5]

#: 나무 모델 설정. 107건짜리 작은 표본이라 일부러 얕고 느리게 배우도록 잡았다.
#: 깊이 2 = 자질 두 개를 조합하는 데까지만 허용(더 깊으면 107건을 통째로 외운다).
XGB_PARAMS = dict(
    max_depth=2,
    learning_rate=0.03,
    subsample=0.8,
    colsample_bytree=0.8,
    min_child_weight=5.0,
    reg_lambda=2.0,
    objective="reg:squarederror",
    tree_method="hist",
    n_jobs=1,          # 실 하나로만 계산한다 — 같은 실행이면 같은 숫자가 나오게 하려고
)

#: 나무를 최대 몇 그루까지 늘려 보고 멈출지. 실제 개수는 검증 겹 안에서 고른다.
MAX_TREES = 600
EARLY_STOPPING_ROUNDS = 40


# ── 1) 데이터 읽기 ───────────────────────────────────────────────────────────

def load_dataset(path: Path):
    """하류 평가 결과 파일에서 학습 재료를 꺼낸다.

    쓰는 줄은 `arm == "ref"`(사람이 직접 쓴 전사) 이면서 `status == "ok"` 인 것뿐이다.
    받아쓰기 오류가 섞이면 '결합층이 문제인가'라는 이번 질문에 답할 수 없어서,
    받아쓰기가 완벽한 조건만 남긴 것이다.

    돌려주는 것:
        X        자질 값 표 (건수 × 12). 없는 자질은 NaN 으로 둔다
        y        사람 점수 0~5
        groups   화자 번호 (겹을 가를 때 이 번호로 묶는다)
        base     손 가중치 점수 0~100 (이미 계산돼 있는 것을 그대로 읽는다)
        meta     항목 식별용 정보(예측 파일에 같이 저장한다)
        hand_w   자질별 손 가중치 — 나중에 '손 비중 vs 배운 비중' 표를 만들 때 쓴다
    """
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            # 사람 전사 + 정상 처리된 줄만 쓴다
            if r.get("arm") == "ref" and r.get("status") == "ok":
                rows.append(r)

    if not rows:
        raise SystemExit(f"쓸 수 있는 줄이 하나도 없다: {path}")

    X = np.full((len(rows), len(FEATURE_IDS)), np.nan, dtype=float)
    y = np.zeros(len(rows), dtype=float)
    groups, base, meta = [], [], []
    hand_w: dict[str, float] = {}

    for i, r in enumerate(rows):
        # 자질 값은 contributions 안에 자질별로 들어 있다.
        # 행마다 뽑힌 자질이 조금씩 달라서, 있는 것만 제자리에 채우고 나머지는 NaN 으로 남긴다
        for c in r.get("contributions", []):
            fid = c.get("feature_id")
            if fid in FEATURE_IDS:
                X[i, FEATURE_IDS.index(fid)] = float(c.get("raw_value"))
                hand_w.setdefault(fid, float(c.get("weight", 0.0)))

        y[i] = float(r["human_score"])
        base.append(float(r["language_score"]))
        # 항목 번호 앞자리가 화자 번호다 (예: "00131-F-99-ID-B-..." → 화자 00131).
        # data/manifests/71479_all.jsonl 의 speaker_id 와 같은 값이다
        groups.append(r["id"].split("-")[0])
        meta.append({
            "id": r["id"],
            "speaker_id": r["id"].split("-")[0],
            "nationality": r.get("nationality"),
            "topik_level": r.get("topik_level"),
            "language_status": r.get("language_status"),
        })

    return X, y, np.array(groups), np.array(base, dtype=float), meta, hand_w


def describe_missing(X: np.ndarray) -> str:
    """자질별로 값이 빠진 건수를 한 줄 요약으로 만든다.

    '없음 표시 컬럼'을 따로 넣을지 판단하려고 먼저 세어 보는 함수다.
    결론(실측 후): 빠진 것이 107건 중 1건(격식체·반말 2개)뿐이라 표시 컬럼을 넣지 않았다.
    거의 전부가 같은 값인 컬럼은 배울 것이 없고, 오히려 그 한 건을 외우는 통로가 된다.
    XGBoost 는 값이 빠진 항목을 어느 가지로 보낼지 스스로 정하므로 NaN 그대로 맡긴다.
    """
    parts = []
    for j, fid in enumerate(FEATURE_IDS):
        n = int(np.isnan(X[:, j]).sum())
        if n:
            parts.append(f"{fid} {n}건")
    return ", ".join(parts) if parts else "없음"


# ── 2) 점수를 재는 자 ────────────────────────────────────────────────────────

def to_grade(pred: np.ndarray) -> np.ndarray:
    """예측값을 0~5 등급으로 반올림하고 범위 밖은 잘라낸다(QWK 계산용)."""
    return np.clip(np.rint(pred), 0, 5).astype(int)


def score_metrics(pred: np.ndarray, truth: np.ndarray) -> dict:
    """예측과 사람 점수가 얼마나 닮았는지 세 가지 자로 잰다.

    - 피어슨: 값이 나란히 커지고 작아지는 정도(직선 관계)
    - 스피어만: 순위가 얼마나 같은지 — 점수 간격이 고르지 않아도 흔들리지 않는다
    - QWK: 등급이 얼마나 일치하는지. 많이 빗나갈수록 더 크게 깎는 계산이라
           시험 채점 일치율을 말할 때 쓰는 표준 지표다
    """
    # 값이 전부 같으면 상관을 정의할 수 없다(부트스트랩에서 가끔 생긴다)
    if np.std(pred) < 1e-12 or np.std(truth) < 1e-12:
        return {"pearson": float("nan"), "spearman": float("nan"), "qwk": float("nan")}
    return {
        "pearson": float(stats.pearsonr(pred, truth)[0]),
        "spearman": float(stats.spearmanr(pred, truth)[0]),
        "qwk": float(cohen_kappa_score(to_grade(pred), truth.astype(int),
                                       weights="quadratic", labels=SCORE_LABELS)),
    }


def baseline_metrics(base_raw: np.ndarray, base_cal: np.ndarray, truth: np.ndarray) -> dict:
    """손 가중치 기준선의 성적을 잰다. 지표마다 다른 값을 쓰는 이유가 있다.

    - 피어슨·스피어만은 **0~100 원점수 그대로** 잰다. 이 두 지표는 눈금을 바꿔도
      값이 변하지 않으므로 옮길 이유가 없고, 겹마다 다른 직선으로 옮긴 값을
      한데 모아 재면 오히려 겹 사이 눈금 차이 때문에 상관이 실제보다 깎인다
      (실측: 0.308 → 0.277). 기준선을 낮게 보이게 만드는 것은 정직하지 않다.
    - QWK 는 0~5 등급으로 반올림해야 잴 수 있으므로 눈금을 옮긴 값을 쓴다.
      그 직선은 배우는 겹에서만 찾았다.
    """
    m_raw = score_metrics(base_raw, truth)
    m_cal = score_metrics(base_cal, truth)
    return {"pearson": m_raw["pearson"], "spearman": m_raw["spearman"], "qwk": m_cal["qwk"]}


def fit_linear_map(x: np.ndarray, y: np.ndarray):
    """0~100 점수를 0~5 눈금으로 옮기는 직선(기울기·절편)을 배우는 쪽에서만 찾는다.

    왜 필요한가: 손 가중치 점수는 0~100이고 사람 점수는 0~5라서, 그냥 20으로 나누면
    "눈금이 안 맞아서" QWK 가 낮게 나온다. 그건 결합 방식의 문제가 아니라 자 문제다.
    학습 모델은 눈금을 배우는 쪽에서 알아서 맞추므로, 기준선에도 같은 기회를 준다.
    단, 직선은 **배우는 겹에서만** 찾고 시험 겹에 적용한다(답을 보지 않으려고).
    """
    if np.std(x) < 1e-12:
        return 0.0, float(np.mean(y))
    slope, intercept = np.polyfit(x, y, 1)
    return float(slope), float(intercept)


# ── 3) 나무 개수 고르기 (검증 겹 안에서만) ───────────────────────────────────

def choose_n_trees(X: np.ndarray, y: np.ndarray, groups: np.ndarray, seed: int) -> int:
    """배우는 겹만 다시 넷으로 쪼개서, 나무를 몇 그루 심는 게 좋은지 정한다.

    시험 겹은 여기서 한 번도 보지 않는다. 안쪽에서 네 번 재 본 뒤 가운뎃값을 쓰는데,
    한 번만 재면 그 21건이 어떤 항목이냐에 따라 개수가 크게 널뛰기 때문이다.
    """
    inner = GroupKFold(n_splits=4)
    picks = []
    for tr, va in inner.split(X, y, groups):
        model = xgb.XGBRegressor(
            n_estimators=MAX_TREES,
            early_stopping_rounds=EARLY_STOPPING_ROUNDS,
            random_state=seed,
            **XGB_PARAMS,
        )
        # 검증용 21건에서 오차가 더 이상 줄지 않으면 거기서 멈춘다
        model.fit(X[tr], y[tr], eval_set=[(X[va], y[va])], verbose=False)
        picks.append(int(model.best_iteration) + 1)
    # 가운뎃값. 너무 적으면 아무것도 못 배우므로 최소 20그루는 심는다
    return max(20, int(np.median(picks)))


# ── 4) 화자 단위 교차검증 ────────────────────────────────────────────────────

def run_cv(X, y, groups, base, folds: int, seed: int):
    """화자를 통째로 갈라 가며, 한 번도 안 본 항목에서만 두 방식을 채점한다.

    돌려주는 것:
        oof_xgb   학습 모델이 '안 본 상태로' 매긴 점수 (0~5)
        oof_base  손 가중치 점수를 0~5 눈금으로 옮긴 것 (직선은 배우는 겹에서만 찾음)
        fold_idx  각 항목이 몇 번째 겹에서 시험을 봤는지
        oof_shap  항목마다 자질별 기여도 — '이 점수가 왜 이 점수인지'의 근거표
        fold_rows 겹별 상세 표(출력용)
    """
    gkf = GroupKFold(n_splits=folds)
    n = len(y)
    oof_xgb = np.full(n, np.nan)
    oof_base = np.full(n, np.nan)
    fold_idx = np.full(n, -1, dtype=int)
    oof_shap = np.zeros((n, len(FEATURE_IDS)))
    oof_bias = np.zeros(n)
    fold_rows = []
    gain_per_fold = []

    for k, (tr, te) in enumerate(gkf.split(X, y, groups), start=1):
        # ① 나무 개수를 배우는 겹 안에서만 고른다
        n_trees = choose_n_trees(X[tr], y[tr], groups[tr], seed)

        # ② 그 개수로 배우는 겹 전체를 다시 배운다
        model = xgb.XGBRegressor(n_estimators=n_trees, random_state=seed, **XGB_PARAMS)
        model.fit(X[tr], y[tr], verbose=False)
        oof_xgb[te] = model.predict(X[te])

        # ③ 예측마다 '어느 자질이 몇 점 올리고 내렸는지'를 함께 계산한다.
        #    pred_contribs 는 나무 구조에서 정확히 계산한 SHAP 값이고,
        #    마지막 칸은 출발점(평균)이라 따로 뗀다. 자질 기여 합 + 출발점 = 예측값이다
        contribs = model.get_booster().predict(
            xgb.DMatrix(X[te], feature_names=FEATURE_IDS), pred_contribs=True
        )
        oof_shap[te] = contribs[:, :-1]
        oof_bias[te] = contribs[:, -1]

        # ④ 기준선도 같은 겹에서 같은 조건으로 채점한다
        slope, intercept = fit_linear_map(base[tr], y[tr])
        oof_base[te] = slope * base[te] + intercept

        fold_idx[te] = k
        gain_per_fold.append(model.get_booster().get_score(importance_type="gain"))

        m_x = score_metrics(oof_xgb[te], y[te])
        m_b = baseline_metrics(base[te], oof_base[te], y[te])
        fold_rows.append({
            "fold": k, "n_test": len(te), "n_speakers": len(set(groups[te])),
            "n_trees": n_trees, "xgb": m_x, "base": m_b,
        })

    return oof_xgb, oof_base, fold_idx, oof_shap, oof_bias, fold_rows, gain_per_fold


# ── 5) 차이가 우연인지 재기 ──────────────────────────────────────────────────

def bootstrap_diff(pred_a, pred_b, truth, groups, n_boot: int, seed: int):
    """'학습 모델 상관 − 손 가중치 상관'이 우연히 나온 차이인지 1000번 다시 뽑아 본다.

    화자를 통째로 다시 뽑는다(같은 화자의 발화는 서로 닮아서, 발화 하나하나를
    따로 뽑으면 표본이 실제보다 많은 척하게 된다).
    돌려주는 구간이 0을 포함하면 "올랐다"고 말하지 않는다.
    """
    rng = np.random.default_rng(seed)
    uniq = np.unique(groups)
    # 화자별로 어느 줄들이 그 사람 것인지 미리 묶어 둔다
    by_speaker = {g: np.where(groups == g)[0] for g in uniq}

    d_pearson, d_spearman = [], []
    for _ in range(n_boot):
        picked = rng.choice(uniq, size=len(uniq), replace=True)
        idx = np.concatenate([by_speaker[g] for g in picked])
        ma = score_metrics(pred_a[idx], truth[idx])
        mb = score_metrics(pred_b[idx], truth[idx])
        if not math.isnan(ma["pearson"]) and not math.isnan(mb["pearson"]):
            d_pearson.append(ma["pearson"] - mb["pearson"])
            d_spearman.append(ma["spearman"] - mb["spearman"])

    def interval(vals):
        v = np.array(vals)
        return float(np.mean(v)), float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))

    return interval(d_pearson), interval(d_spearman)


# ── 6) 출력 ──────────────────────────────────────────────────────────────────

def print_report(n, n_speakers, missing_desc, fold_rows, m_base, m_xgb,
                 boot_p, boot_s, importance_rows, folds, seed, n_boot):
    """사람이 눈으로 보고 판단할 요약표를 찍는다."""
    line = "=" * 74
    print(f"\n{line}\n  점수 결합층 실험 — 손 가중치 vs 사람 점수로 배운 모델(XGBoost)\n{line}")
    print(f"  표본 {n}건 / 화자 {n_speakers}명 / {folds}겹 화자단위 교차검증 / 씨앗 {seed}")
    print(f"  값이 빠진 자질: {missing_desc}")
    print("  ※ 두 방식 모두 '한 번도 안 본 항목'에서만 채점했다.")

    print(f"\n{line}\n  ① 전체 성적 (검증 겹 예측을 다 모아서 한 번에)\n{line}")
    print(f"  {'방식':<28}{'피어슨':>10}{'스피어만':>12}{'QWK':>10}")
    print(f"  {'-' * 58}")
    print(f"  {'손 가중치 (지금 채점기)':<24}{m_base['pearson']:>10.3f}"
          f"{m_base['spearman']:>12.3f}{m_base['qwk']:>10.3f}")
    print(f"  {'XGBoost (배운 결합층)':<25}{m_xgb['pearson']:>10.3f}"
          f"{m_xgb['spearman']:>12.3f}{m_xgb['qwk']:>10.3f}")
    print(f"  {'차이':<27}{m_xgb['pearson'] - m_base['pearson']:>+10.3f}"
          f"{m_xgb['spearman'] - m_base['spearman']:>+12.3f}"
          f"{m_xgb['qwk'] - m_base['qwk']:>+10.3f}")

    print(f"\n{line}\n  ② 차이가 우연인가 (화자 다시뽑기 {n_boot}회, 95% 구간)\n{line}")
    for name, (mean, lo, hi) in (("피어슨", boot_p), ("스피어만", boot_s)):
        verdict = "유의하게 올랐다" if lo > 0 else (
            "유의하게 떨어졌다" if hi < 0 else "0을 걸친다 → 올랐다고 말할 수 없다")
        print(f"  {name} 차이 평균 {mean:>+.3f}   95% 구간 [{lo:>+.3f}, {hi:>+.3f}]   → {verdict}")

    print(f"\n{line}\n  ③ 겹별 상세\n{line}")
    print(f"  {'겹':<4}{'건수':>6}{'화자':>6}{'나무':>6}"
          f"{'손_피어슨':>12}{'XGB_피어슨':>12}{'손_QWK':>10}{'XGB_QWK':>10}")
    print(f"  {'-' * 66}")
    for r in fold_rows:
        print(f"  {r['fold']:<4}{r['n_test']:>6}{r['n_speakers']:>6}{r['n_trees']:>6}"
              f"{r['base']['pearson']:>12.3f}{r['xgb']['pearson']:>12.3f}"
              f"{r['base']['qwk']:>10.3f}{r['xgb']['qwk']:>10.3f}")

    print(f"\n{line}\n  ④ 자질 중요도 — 배운 모델이 실제로 어디를 보고 있나\n{line}")
    print("  (배운 비중 = 검증 예측에서 그 자질이 점수를 움직인 크기의 평균, 합계 100%)")
    print(f"  {'자질':<32}{'배운 비중':>11}{'손 비중':>10}{'평균 밀고당김':>14}")
    print(f"  {'-' * 66}")
    for r in importance_rows:
        print(f"  {r['feature_id']:<32}{r['learned_pct']:>10.1f}%{r['hand_pct']:>9.1f}%"
              f"{r['mean_signed']:>+14.3f}")


def build_importance(oof_shap: np.ndarray, hand_w: dict) -> list:
    """자질별 비중표를 만든다.

    '배운 비중' = 검증 예측 전체에서 그 자질이 점수를 위아래로 움직인 크기(|SHAP|)의
    평균을 백분율로 고친 것. 손 가중치표와 나란히 놓으면
    "사람이 12% 라고 정한 자질을 모델은 몇 % 로 보는가"를 바로 읽을 수 있다.
    """
    mean_abs = np.abs(oof_shap).mean(axis=0)
    total = mean_abs.sum()
    hand_total = sum(hand_w.values()) or 1.0
    rows = []
    for j, fid in enumerate(FEATURE_IDS):
        rows.append({
            "feature_id": fid,
            "learned_pct": float(mean_abs[j] / total * 100) if total > 0 else 0.0,
            "hand_pct": float(hand_w.get(fid, 0.0) / hand_total * 100),
            # 부호가 있는 평균 — 이 자질이 대체로 점수를 올리는 쪽인지 내리는 쪽인지
            "mean_signed": float(oof_shap[:, j].mean()),
        })
    rows.sort(key=lambda r: r["learned_pct"], reverse=True)
    return rows


# ── 7) 계산 함수가 제대로 도는지 예시로 확인 ─────────────────────────────────

def selftest() -> int:
    """채점에 쓰는 계산 함수들을 값이 뻔한 예시에 넣어 보고 결과를 눈으로 확인한다.

    채점 로직은 훑어봐서는 맞는지 알 수 없다. 여기서 확인하는 것:
      - 완전히 같은 예측이면 상관 1.0 · QWK 1.0 이 나오는가
      - 0~100 점수를 0~5 로 옮기는 직선을 제대로 찾아내는가
      - 화자 단위 분할이 정말로 화자를 갈라 놓는가(새는 데가 없는가)
    """
    ok = True
    print("── 계산 함수 확인 ──────────────────────────────────────────")

    # (1) 예측 = 정답이면 세 지표가 모두 최고점이어야 한다
    truth = np.array([0., 1., 2., 3., 4., 5., 3., 2.])
    m = score_metrics(truth.copy(), truth)
    print(f"  똑같은 예측 → 피어슨 {m['pearson']:.3f} 스피어만 {m['spearman']:.3f} QWK {m['qwk']:.3f}  (기대 1.000)")
    ok &= abs(m["pearson"] - 1) < 1e-9 and abs(m["qwk"] - 1) < 1e-9

    # (2) 정확히 뒤집힌 예측이면 피어슨이 -1 이어야 한다
    m2 = score_metrics(5 - truth, truth)
    print(f"  뒤집힌 예측 → 피어슨 {m2['pearson']:.3f}  (기대 -1.000)")
    ok &= abs(m2["pearson"] + 1) < 1e-9

    # (3) 반올림·자르기: -0.4 는 0 으로, 5.6 은 5 로 눌려야 한다
    g = to_grade(np.array([-0.4, 0.5, 2.4, 2.6, 5.6]))
    print(f"  0~5 등급 변환 [-0.4, 0.5, 2.4, 2.6, 5.6] → {g.tolist()}  (기대 [0, 0, 2, 3, 5])")
    ok &= g.tolist() == [0, 0, 2, 3, 5]   # 0.5 는 짝수 쪽(0)으로 붙는 numpy 규칙

    # (4) 0~100 → 0~5 직선 찾기: y = x/20 인 자료를 넣으면 기울기 0.05 가 나와야 한다
    x = np.array([20., 40., 60., 80., 100.])
    slope, intercept = fit_linear_map(x, x / 20)
    print(f"  눈금 맞추기 직선 → 기울기 {slope:.4f} 절편 {intercept:+.4f}  (기대 0.0500 / +0.0000)")
    ok &= abs(slope - 0.05) < 1e-9 and abs(intercept) < 1e-9

    # (5) 화자가 학습/검증에 겹쳐 들어가지 않는지 실제로 갈라 보고 확인한다
    groups = np.array([f"S{i//3:02d}" for i in range(30)])
    Xd, yd = np.zeros((30, 2)), np.arange(30, dtype=float)
    leaked = 0
    for tr, te in GroupKFold(n_splits=5).split(Xd, yd, groups):
        leaked += len(set(groups[tr]) & set(groups[te]))
    print(f"  화자 단위 분할 → 학습·검증에 겹친 화자 {leaked}명  (기대 0명)")
    ok &= leaked == 0

    print("── 결과: " + ("전부 통과" if ok else "실패한 항목 있음") + " ──")
    return 0 if ok else 1


# ── 8) 실행 ──────────────────────────────────────────────────────────────────

def main() -> int:
    for stream in (__import__("sys").stdout, __import__("sys").stderr):
        try:
            stream.reconfigure(encoding="utf-8")   # 윈도우 명령창에서 한글이 깨지지 않게
        except Exception:
            pass

    ap = argparse.ArgumentParser(
        description="점수 결합층을 사람 점수로 학습해 손 가중치와 비교한다")
    ap.add_argument("--data", default=r"D:\해커톤데이터\downstream_results.jsonl",
                    help="하류 평가 결과 JSONL (읽기만 한다)")
    ap.add_argument("--folds", type=int, default=5, help="교차검증 겹 수 (기본 5)")
    ap.add_argument("--seed", type=int, default=42, help="씨앗값 (기본 42)")
    ap.add_argument("--bootstrap", type=int, default=1000, help="다시뽑기 횟수 (기본 1000)")
    ap.add_argument("--out-pred", default=r"D:\해커톤데이터\xgb_predictions.jsonl",
                    help="항목별 예측·근거 저장 위치")
    ap.add_argument("--out-model", default=r"D:\해커톤데이터\xgb_language_v0.json",
                    help="전체 데이터로 다시 배운 최종 모델 저장 위치")
    ap.add_argument("--selftest", action="store_true",
                    help="계산 함수만 예시 입력으로 확인하고 끝낸다")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    # ── 재료 준비 ────────────────────────────────────────────────────────────
    X, y, groups, base, meta, hand_w = load_dataset(Path(args.data))
    n_speakers = len(set(groups))
    print(f"읽은 항목 {len(y)}건 (사람 전사·정상 처리) / 화자 {n_speakers}명")

    # ── 교차검증 ─────────────────────────────────────────────────────────────
    oof_xgb, oof_base, fold_idx, oof_shap, oof_bias, fold_rows, _ = run_cv(
        X, y, groups, base, args.folds, args.seed)

    m_xgb = score_metrics(oof_xgb, y)
    m_base = baseline_metrics(base, oof_base, y)
    # 상관 차이의 다시뽑기에는 기준선 원점수를 쓴다(눈금을 옮겨도 상관은 그대로다)
    boot_p, boot_s = bootstrap_diff(oof_xgb, base, y, groups, args.bootstrap, args.seed)
    importance_rows = build_importance(oof_shap, hand_w)

    print_report(len(y), n_speakers, describe_missing(X), fold_rows, m_base, m_xgb,
                 boot_p, boot_s, importance_rows, args.folds, args.seed, args.bootstrap)

    # ── 항목별 예측 저장 ─────────────────────────────────────────────────────
    # 점수만 저장하지 않는다. 이 프로젝트에서 근거 없는 점수는 결함이므로,
    # 항목마다 '어느 자질이 몇 점 밀고 당겼는지'(SHAP)를 자질 값과 함께 남긴다
    out_pred = Path(args.out_pred)
    out_pred.parent.mkdir(parents=True, exist_ok=True)
    with out_pred.open("w", encoding="utf-8") as f:
        for i, mi in enumerate(meta):
            evidence = [
                {"feature_id": fid,
                 "raw_value": None if np.isnan(X[i, j]) else round(float(X[i, j]), 4),
                 "shap": round(float(oof_shap[i, j]), 4)}
                for j, fid in enumerate(FEATURE_IDS)
            ]
            # 밀고 당긴 크기가 큰 자질이 위로 오게 정렬한다(사람이 읽는 순서)
            evidence.sort(key=lambda e: abs(e["shap"]), reverse=True)
            f.write(json.dumps({
                **mi,
                "fold": int(fold_idx[i]),
                "human_score": float(y[i]),
                "hand_score_100": float(base[i]),        # 지금 채점기의 0~100 점수
                "hand_pred_0_5": round(float(oof_base[i]), 4),  # 눈금만 0~5 로 옮긴 것
                "xgb_pred_0_5": round(float(oof_xgb[i]), 4),
                "xgb_grade": int(to_grade(np.array([oof_xgb[i]]))[0]),
                "xgb_baseline_value": round(float(oof_bias[i]), 4),  # 출발점(전체 평균)
                "evidence": evidence,
            }, ensure_ascii=False) + "\n")
    print(f"\n항목별 예측·근거 저장: {out_pred}  ({len(meta)}줄)")

    # ── 최종 모델 저장 ───────────────────────────────────────────────────────
    # 위 표의 숫자는 '안 본 항목에서 잰 성적'이고, 실제로 쓸 모델은 자료를 다 보고 배운다.
    # 나무 개수는 겹별로 고른 값의 가운뎃값을 그대로 쓴다(여기서 새로 고르면 답을 보게 된다)
    n_trees_final = int(np.median([r["n_trees"] for r in fold_rows]))
    final = xgb.XGBRegressor(n_estimators=n_trees_final, random_state=args.seed, **XGB_PARAMS)
    final.fit(X, y, verbose=False)
    final.get_booster().feature_names = FEATURE_IDS
    out_model = Path(args.out_model)
    out_model.parent.mkdir(parents=True, exist_ok=True)
    final.save_model(str(out_model))
    print(f"최종 모델 저장: {out_model}  (나무 {n_trees_final}그루, 깊이 {XGB_PARAMS['max_depth']})")

    # ── 판정 ─────────────────────────────────────────────────────────────────
    lo = boot_p[1]
    if lo > 0:
        print(f"\n판정: 배운 결합층이 손 가중치보다 유의하게 낫다 "
              f"(피어슨 {m_base['pearson']:.3f} → {m_xgb['pearson']:.3f}).")
    else:
        print(f"\n판정: 이 데이터로는 '더 낫다'고 말할 수 없다 "
              f"(피어슨 {m_base['pearson']:.3f} → {m_xgb['pearson']:.3f}, "
              f"차이 95% 구간이 0을 걸침).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
