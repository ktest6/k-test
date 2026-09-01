"""우리 채점 3영역이 AI Hub 사람 점수와 얼마나 맞는지 QWK 로 재는 실험 스크립트.

**이 스크립트가 대답하려는 질문 하나**
  우리가 매긴 점수(내용·언어사용·전달력)를 0~5 등급으로 바꿔 놓고 보면,
  AI Hub 라벨을 매긴 사람과 얼마나 같은 등급을 주는가?

세 영역을 각각 다른 방식으로 다룬다. 재료가 다르기 때문이다.
  ① 언어사용 — 이미 돌려 둔 채점 결과(downstream_results.jsonl)를 읽어 지금 계산한다
  ② 내용     — 여기서 다시 돌리지 않는다. 체크리스트 실험(v3·v4)의 숫자를 그대로 인용한다
  ③ 전달력   — Azure 발음평가를 실제로 다시 호출해서 계산한다(건별 결과는 캐시에 남긴다)

결과는 팀 내부용 HTML 보고서와 JSON 으로 남는다(심사용 아님).

실행 (assessment 폴더에서):
    python scripts/speech_lab/qwk_lab.py            # 전부 (Azure 호출 포함, 캐시된 건은 건너뜀)
    python scripts/speech_lab/qwk_lab.py --no-azure # Azure 를 부르지 않고 캐시에 있는 것만
    python scripts/speech_lab/qwk_lab.py --selftest # 계산기가 제대로 도는지만 확인
"""

from __future__ import annotations

import argparse
import glob
import html
import json
import math
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import numpy as np
from scipy import stats
from sklearn.metrics import cohen_kappa_score
from sklearn.model_selection import GroupKFold

# assessment/ 를 import 경로에 넣어야 src.* 를 불러올 수 있다
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ── 설정값 ───────────────────────────────────────────────────────────────────

#: 사람 점수가 가질 수 있는 등급. QWK 는 이 6칸 안에서만 계산한다
SCORE_LABELS = (0, 1, 2, 3, 4, 5)

SEED = 42          # 겹 나누기·부트스트랩에 쓰는 고정 씨앗(같은 결과가 다시 나오게)
FOLDS = 5          # 교차검증 겹 수
N_BOOT = 1000      # 신뢰구간을 구할 때 다시 뽑는 횟수

DATA_ROOT = Path(r"C:\해커톤\data")
MANIFEST_DIR = DATA_ROOT / "manifests"
GOLD_PRESENT = MANIFEST_DIR / "gold_present.jsonl"
DOWNSTREAM = Path(r"D:\해커톤데이터\downstream_results.jsonl")
GOLD499 = Path(r"D:\해커톤데이터\gold_499_eval.jsonl")
AZURE_CACHE = Path(r"D:\해커톤데이터\azure_delivery_110.jsonl")

V3_SUMMARY = ROOT / "outputs" / "checklist_lab" / "results_summary_v3.json"
V4_SUMMARY = ROOT / "outputs" / "checklist_lab" / "results_summary_v4.json"

OUT_HTML = ROOT / "outputs" / "qwk_3영역_20260831.html"
OUT_JSON = ROOT / "outputs" / "qwk_3영역_20260831.json"


# ══════════════════════════════════════════════════════════════════════════════
# 1) 점수를 재는 자 — QWK 와 그 주변 도구
# ══════════════════════════════════════════════════════════════════════════════

def to_grade(pred) -> np.ndarray:
    """아무 숫자나 0~5 등급으로 반올림하고 범위 밖은 잘라낸다.

    QWK 는 '몇 등급을 줬는가'끼리 비교하는 자라서, 우리 점수를 먼저 등급으로
    바꿔 놓아야 계산할 수 있다.
    """
    return np.clip(np.rint(np.asarray(pred, dtype=float)), 0, 5).astype(int)


def qwk(pred_grades, truth_grades) -> float:
    """QWK(이차 가중 카파) — 두 채점자가 등급을 얼마나 같게 매기는가.

    1.0 이면 완전히 같게 매긴 것, 0 이면 아무렇게나 찍은 것과 다를 바 없는 것,
    음수면 오히려 반대로 매긴 것이다. '이차 가중'은 **많이 빗나갈수록 더 크게 깎는다**는
    뜻으로, 3점을 4점으로 본 것과 3점을 0점으로 본 것을 똑같이 세지 않는다.
    """
    p = np.asarray(pred_grades, dtype=int)
    t = np.asarray(truth_grades, dtype=int)
    # 한쪽이 전부 같은 값이면(부트스트랩에서 가끔 생긴다) 카파를 정의할 수 없다
    if len(t) == 0:
        return float("nan")
    return float(cohen_kappa_score(p, t, weights="quadratic", labels=list(SCORE_LABELS)))


def fit_linear_map(x, y) -> tuple[float, float]:
    """0~100 점수를 0~5 눈금으로 옮기는 직선(기울기·절편)을 찾는다.

    왜 필요한가: 우리 점수는 0~100이고 사람 점수는 0~5다. 그냥 20으로 나누면
    '눈금이 안 맞아서' QWK 가 낮게 나올 수 있는데 그건 채점의 문제가 아니라 자의 문제다.
    단, 이 직선은 **배우는 겹에서만** 찾고 시험 겹에 적용한다(답을 미리 보지 않으려고).
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    # 예측값이 전부 같으면 기울기를 구할 수 없으니 평균으로 밀어 둔다
    if len(x) < 2 or np.std(x) < 1e-12:
        return 0.0, float(np.mean(y)) if len(y) else 0.0
    slope, intercept = np.polyfit(x, y, 1)
    return float(slope), float(intercept)


def make_folds(groups, folds: int, seed: int):
    """화자를 통째로 갈라 교차검증 겹을 만든다.

    같은 사람의 발화는 서로 닮아서, 한 사람의 답안이 배우는 쪽과 시험 쪽에
    동시에 들어가면 점수가 실제보다 좋게 나온다. 그래서 사람 단위로 가른다.
    """
    groups = np.asarray(groups)
    n_groups = len(set(groups.tolist()))
    n_splits = min(folds, n_groups)
    gkf = GroupKFold(n_splits=n_splits, shuffle=True, random_state=seed)
    dummy = np.zeros(len(groups))
    return list(gkf.split(dummy, dummy, groups))


def calibrated_grades(raw, truth, groups, folds: int = FOLDS, seed: int = SEED):
    """눈금 맵 방식으로 등급을 매긴다 — 겹마다 직선을 새로 배워서 시험 겹에 적용.

    돌려주는 것은 (모든 답안의 등급, 겹별로 찾은 직선 목록)이다.
    등급은 전부 '그 답안을 한 번도 안 본 상태에서' 매겨진 값이다.
    """
    raw = np.asarray(raw, dtype=float)
    truth = np.asarray(truth, dtype=float)
    mapped = np.full(len(raw), np.nan)
    params = []

    for k, (tr, te) in enumerate(make_folds(groups, folds, seed), start=1):
        # 배우는 겹에서만 '0~100 → 0~5' 직선을 찾는다
        slope, intercept = fit_linear_map(raw[tr], truth[tr])
        # 그 직선을 시험 겹에 적용한다
        mapped[te] = slope * raw[te] + intercept
        params.append({"fold": k, "n_train": int(len(tr)), "n_test": int(len(te)),
                       "slope": slope, "intercept": intercept})

    return to_grade(mapped), params


def bootstrap_qwk_ci(pred_grades, truth, groups, n_boot: int = N_BOOT, seed: int = SEED):
    """QWK 의 95% 신뢰구간을 화자 단위로 다시 뽑아서 구한다.

    표본이 100건 남짓이라 QWK 하나만 보면 '운이 좋아 나온 값'인지 알 수 없다.
    화자를 통째로 1000번 다시 뽑아 매번 QWK 를 재고, 그 값들의 가운데 95%를 구간으로 쓴다.
    (발화 하나하나를 따로 뽑으면 같은 사람 것이 여러 번 들어가 표본이 실제보다 많은 척한다)
    """
    pred_grades = np.asarray(pred_grades, dtype=int)
    truth = np.asarray(truth, dtype=int)
    groups = np.asarray(groups)
    if len(truth) == 0:
        return {"mean": float("nan"), "lo": float("nan"), "hi": float("nan"), "n_boot": 0}

    rng = np.random.default_rng(seed)
    uniq = np.unique(groups)
    by_speaker = {g: np.where(groups == g)[0] for g in uniq}

    vals = []
    for _ in range(n_boot):
        picked = rng.choice(uniq, size=len(uniq), replace=True)
        idx = np.concatenate([by_speaker[g] for g in picked])
        v = qwk(pred_grades[idx], truth[idx])
        # 뽑힌 표본에서 등급이 한 종류뿐이면 카파가 nan 이 된다 — 그 회차는 버린다
        if not math.isnan(v):
            vals.append(v)

    if not vals:
        return {"mean": float("nan"), "lo": float("nan"), "hi": float("nan"), "n_boot": 0}
    arr = np.array(vals)
    return {"mean": float(arr.mean()), "lo": float(np.percentile(arr, 2.5)),
            "hi": float(np.percentile(arr, 97.5)), "n_boot": len(vals)}


def confusion_matrix_6x6(pred_grades, truth) -> list[list[int]]:
    """6×6 엇갈림 표. 세로가 우리 등급, 가로가 사람 등급이다."""
    m = [[0] * 6 for _ in range(6)]
    for p, t in zip(np.asarray(pred_grades, dtype=int), np.asarray(truth, dtype=int)):
        if 0 <= p <= 5 and 0 <= t <= 5:
            m[p][t] += 1
    return m


def grade_block(pred_grades, truth, groups, n_boot: int, seed: int) -> dict:
    """등급 한 벌에 대한 성적표 — QWK·신뢰구간·정확일치·±1일치·엇갈림 표."""
    pred_grades = np.asarray(pred_grades, dtype=int)
    truth = np.asarray(truth, dtype=int)
    diff = np.abs(pred_grades - truth)
    return {
        "qwk": qwk(pred_grades, truth),
        "qwk_ci95": bootstrap_qwk_ci(pred_grades, truth, groups, n_boot, seed),
        "exact": float(np.mean(diff == 0)) if len(truth) else float("nan"),
        "within1": float(np.mean(diff <= 1)) if len(truth) else float("nan"),
        "mean_pred_grade": float(np.mean(pred_grades)) if len(truth) else float("nan"),
        "confusion": confusion_matrix_6x6(pred_grades, truth),
    }


def evaluate_predictor(label, raw, truth, groups, *, naive_divisor: float | None = 20.0,
                       n_boot: int = N_BOOT, seed: int = SEED, folds: int = FOLDS,
                       note: str = "") -> dict:
    """예측값 한 줄기를 두 가지 방법으로 채점한다 — 순진법과 눈금 맵.

    naive_divisor 가 None 이면 순진법을 계산하지 않는다(길이 기준선처럼
    0~100 점수가 아니어서 20으로 나누는 것이 뜻이 없는 경우).
    피어슨·스피어만은 등급이 아니라 원래 값으로 재는데, 이 둘은 눈금을 바꿔도
    값이 변하지 않아서 반올림으로 정보를 버릴 이유가 없기 때문이다.
    """
    raw = np.asarray(raw, dtype=float)
    truth = np.asarray(truth, dtype=int)
    groups = np.asarray(groups)

    out = {
        "label": label,
        "note": note,
        "n": int(len(truth)),
        "n_speakers": int(len(set(groups.tolist()))),
        "pred_raw_mean": float(np.mean(raw)) if len(raw) else float("nan"),
        "pred_raw_std": float(np.std(raw)) if len(raw) else float("nan"),
    }

    # 값이 전부 같으면 상관을 정의할 수 없다
    if len(raw) > 1 and np.std(raw) > 1e-12 and np.std(truth) > 1e-12:
        out["pearson"] = float(stats.pearsonr(raw, truth)[0])
        out["spearman"] = float(stats.spearmanr(raw, truth)[0])
    else:
        out["pearson"] = float("nan")
        out["spearman"] = float("nan")

    # ① 순진법 — 그냥 20으로 나누고 반올림
    if naive_divisor:
        out["naive"] = grade_block(to_grade(raw / naive_divisor), truth, groups, n_boot, seed)

    # ② 눈금 맵 — 겹마다 직선을 배워서 옮긴다
    cal_grades, fold_params = calibrated_grades(raw, truth, groups, folds, seed)
    out["calibrated"] = grade_block(cal_grades, truth, groups, n_boot, seed)
    out["fold_params"] = fold_params

    return out


# ══════════════════════════════════════════════════════════════════════════════
# 2) 사람 점수(라벨) 읽기와 살펴보기
# ══════════════════════════════════════════════════════════════════════════════

def _parse_evals(value):
    """evals 칸을 사전으로 되돌린다. 파일에 따라 사전이거나 파이썬 문자열이다."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip().startswith("{"):
        try:
            # 목록 파일 일부가 파이썬 사전을 그대로 문자열로 적어 두었다
            return json.loads(value.replace("'", '"'))
        except Exception:
            return None
    return None


def load_label_pool() -> dict:
    """목록 파일 전체를 읽어 '세 점수가 다 있는 자유발화(ATQ)' 답안을 모은다.

    같은 답안이 여러 목록 파일에 겹쳐 들어 있으므로 id 로 중복을 없앤다.
    돌려주는 것: 답안 목록, 세 점수의 분포표, 세 점수 서로의 상관.
    """
    seen: dict[str, dict] = {}
    for path in sorted(glob.glob(str(MANIFEST_DIR / "*.jsonl"))):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                rid = row.get("id")
                if not rid:
                    continue
                # 먼저 본 것을 쓰되, 점수가 비어 있던 것은 점수 있는 쪽으로 바꿔 준다
                if rid not in seen:
                    seen[rid] = row
                elif not _parse_evals(seen[rid].get("evals")) and _parse_evals(row.get("evals")):
                    seen[rid] = row

    pool = []
    for rid, row in seen.items():
        if row.get("task") != "ATQ":
            continue
        ev = _parse_evals(row.get("evals"))
        if not ev:
            continue
        vals = [ev.get("delivery"), ev.get("language_use"), ev.get("content")]
        # 세 점수가 모두 정수인 것만 쓴다(하나라도 비면 영역 비교를 못 한다)
        if not all(isinstance(v, int) for v in vals):
            continue
        pool.append({
            "id": rid,
            "speaker_id": row.get("speaker_id") or rid[:5],
            "prompt": row.get("prompt", ""),
            "delivery": ev["delivery"],
            "language_use": ev["language_use"],
            "content": ev["content"],
        })

    # 분포표 — 0~5 가 각각 몇 건인지
    dist = {}
    for area in ("content", "language_use", "delivery"):
        c = Counter(r[area] for r in pool)
        dist[area] = {str(g): int(c.get(g, 0)) for g in SCORE_LABELS}

    # 상호상관 — 세 점수가 서로 얼마나 같이 움직이는지
    corr = {}
    pairs = [("language_use", "content"), ("language_use", "delivery"), ("content", "delivery")]
    for a, b in pairs:
        xa = np.array([r[a] for r in pool], dtype=float)
        xb = np.array([r[b] for r in pool], dtype=float)
        corr[f"{a}~{b}"] = float(stats.pearsonr(xa, xb)[0])

    return {
        "n": len(pool),
        "n_speakers": len(set(r["speaker_id"] for r in pool)),
        "n_prompts": len(set(r["prompt"] for r in pool)),
        "n_unique_ids_scanned": len(seen),
        "distribution": dist,
        "cross_correlation_pearson": corr,
        "rows": pool,
    }


def find_noise_example() -> dict:
    """라벨 잡음 예시 한 건을 원본에서 직접 꺼내 온다(보고서에 실으려고).

    낭독 문항인데 지문을 거의 그대로 읽고도 언어사용 0점, 내용 5점이 붙은 건이다.
    '사람 점수도 흔들린다'는 것을 말로만 하지 않고 실물로 보이기 위한 자리다.
    """
    target = "00067-F-91-VI-A-LAR010-0004411"
    for path in [GOLD499, GOLD_PRESENT]:
        if not Path(path).exists():
            continue
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                if row.get("id") == target:
                    return {
                        "id": target,
                        "source_file": str(path),
                        "prompt": row.get("prompt", ""),
                        "ref": row.get("ref", ""),
                        "task": row.get("task", ""),
                        "evals": _parse_evals(row.get("evals")) or {},
                    }
    return {"id": target, "source_file": "찾지 못함", "evals": {}}


# ══════════════════════════════════════════════════════════════════════════════
# 3) ① 언어사용 — 이미 돌려 둔 채점 결과를 읽어 지금 계산한다
# ══════════════════════════════════════════════════════════════════════════════

def load_language_rows() -> dict:
    """downstream_results.jsonl 에서 '사람 전사로 채점한' 언어사용 점수를 꺼낸다.

    arm=="ref" 는 STT 를 거치지 않고 사람이 적은 전사를 그대로 채점한 줄이다.
    (STT 오류가 섞이지 않은 조건이라 언어사용 자질을 재기에 가장 깨끗하다)
    language_score 가 없는 줄은 채점이 아예 안 된 것이라 뺀다 — 그 수도 세어서 보고한다.
    """
    rows = []
    status_counter = Counter()
    with open(DOWNSTREAM, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if row.get("arm") != "ref":
                continue
            status_counter[row.get("status")] += 1
            score = row.get("language_score")
            if score is None or score == "":
                continue
            rows.append(row)

    # 정답 대조: gold_499_eval.jsonl 의 evals.language_use 와 같은지 확인한다
    gold = {}
    if GOLD499.exists():
        with open(GOLD499, encoding="utf-8") as f:
            for line in f:
                try:
                    g = json.loads(line)
                except Exception:
                    continue
                ev = _parse_evals(g.get("evals"))
                if ev and isinstance(ev.get("language_use"), int):
                    gold[g["id"]] = ev["language_use"]

    mismatches = []
    not_in_gold = 0
    data = []
    for row in rows:
        rid = row["id"]
        human = int(float(row["human_score"]))
        g = gold.get(rid)
        if g is None:
            not_in_gold += 1
        elif g != human:
            # 다르면 원본(gold) 쪽을 정답으로 쓰고, 어긋난 건은 따로 적어 둔다
            mismatches.append({"id": rid, "downstream": human, "gold": g})
            human = g
        transcript = row.get("transcript") or row.get("ref") or ""
        data.append({
            "id": rid,
            "speaker_id": rid[:5],
            "pred": float(row["language_score"]),
            "truth": human,
            "transcript": transcript,
            "eojeol": len(transcript.split()),   # 어절 수 = 띄어쓰기로 나눈 덩어리 수
            "prompt": row.get("prompt", ""),
        })

    return {
        "rows": data,
        "n_ref_rows": int(sum(status_counter.values())),
        "status_counter": {str(k): int(v) for k, v in status_counter.items()},
        "n_dropped": int(sum(status_counter.values()) - len(data)),
        "gold_join": {
            "n_checked": len(data),
            "n_not_in_gold": not_in_gold,
            "n_mismatch": len(mismatches),
            "mismatches": mismatches[:10],
        },
    }


# ══════════════════════════════════════════════════════════════════════════════
# 4) ③ 전달력 — Azure 발음평가를 실제로 부른다 (건별 결과는 캐시에 남긴다)
# ══════════════════════════════════════════════════════════════════════════════

def load_delivery_targets() -> list[dict]:
    """전달력 점수가 붙은 자유발화(ATQ) 답안과 그 음성 파일 경로를 모은다."""
    targets = []
    with open(GOLD_PRESENT, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if row.get("task") != "ATQ":
                continue
            ev = _parse_evals(row.get("evals")) or {}
            if not isinstance(ev.get("delivery"), int):
                continue
            targets.append({
                "id": row["id"],
                "speaker_id": row.get("speaker_id") or row["id"][:5],
                "wav": str(DATA_ROOT / row["audio"]),
                "prompt": row.get("prompt", ""),
                "evals": {k: ev.get(k) for k in ("delivery", "language_use", "content")},
            })
    return targets


def read_azure_cache() -> dict[str, dict]:
    """지난 실행에서 남긴 건별 결과를 읽는다. 있으면 Azure 를 다시 부르지 않는다."""
    cache: dict[str, dict] = {}
    if not AZURE_CACHE.exists():
        return cache
    with open(AZURE_CACHE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            if row.get("id"):
                cache[row["id"]] = row
    return cache


def run_azure_delivery(targets: list[dict], *, use_azure: bool = True,
                       limit: int | None = None) -> dict:
    """녹음 하나하나를 Azure 발음평가에 넣고 결과를 캐시 파일에 한 줄씩 적는다.

    **건별로 바로 적는 이유**: 지난번에는 요약만 남기고 건별 값을 버려서
    오늘 같은 재분석을 하려면 처음부터 다시 돌려야 했다. 같은 실수를 반복하지 않으려고
    한 건 끝날 때마다 파일에 이어 붙인다(중간에 끊겨도 거기까지는 남는다).
    """
    cache = read_azure_cache()
    todo = [t for t in targets if t["id"] not in cache]
    if limit is not None:
        todo = todo[:limit]

    called, failed = 0, 0
    if todo and use_azure:
        # 무거운 import 는 실제로 부를 때만 한다(--no-azure 로 돌 때는 필요 없다)
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env", override=False)
        from src.scoring.schema import AudioInput
        from src.speech.azure_stt import AzureStt
        from scripts.speech_lab._common import serve_wav

        stt = AzureStt()
        if not stt.available:
            print("  ! Azure 열쇠가 없다(.env 의 AZURE_SPEECH_KEY/REGION). 캐시에 있는 것만 쓴다.")
            todo = []

        AZURE_CACHE.parent.mkdir(parents=True, exist_ok=True)
        for i, t in enumerate(todo, start=1):
            record = {"id": t["id"], "speaker_id": t["speaker_id"], "evals": t["evals"],
                      "accuracy": None, "fluency": None, "completeness": None,
                      "overall": None, "prosody": None, "transcript": "", "error": None}
            try:
                wav = Path(t["wav"]).read_bytes()
                # 채점 코드는 '주소'로 음성을 받으므로 잠깐 로컬 주소를 만들어 준다
                with serve_wav(wav) as url:
                    tr = stt.transcribe(AudioInput(url=url, format="wav"),
                                        item_prompt=t["prompt"], item_type="free")
                record["transcript"] = tr.text or ""
                pa = tr.pronunciation
                if pa is None:
                    record["error"] = "발음 점수가 오지 않음"
                else:
                    for k in ("accuracy", "fluency", "completeness", "overall", "prosody"):
                        record[k] = getattr(pa, k, None)
            except Exception as exc:  # 한 건이 실패해도 나머지는 계속 돈다
                record["error"] = f"{type(exc).__name__}: {exc}"

            if record["error"]:
                failed += 1
            called += 1
            with open(AZURE_CACHE, "a", encoding="utf-8") as out:
                out.write(json.dumps(record, ensure_ascii=False) + "\n")
            cache[t["id"]] = record

            if i % 10 == 0 or i == len(todo):
                print(f"    Azure {i}/{len(todo)} 건 (실패 {failed})")
            time.sleep(0.05)  # 연달아 두드리지 않도록 아주 살짝 쉰다

    # 캐시에서 쓸 수 있는 것만 골라 낸다(발음 점수가 하나도 없는 건은 뺀다)
    usable, broken = [], []
    for t in targets:
        row = cache.get(t["id"])
        if row is None:
            broken.append({"id": t["id"], "error": "아직 안 돌림"})
            continue
        if row.get("overall") is None and row.get("accuracy") is None:
            broken.append({"id": t["id"], "error": row.get("error") or "발음 점수 없음"})
            continue
        transcript = row.get("transcript") or ""
        usable.append({
            "id": t["id"],
            "speaker_id": t["speaker_id"],
            "truth": t["evals"]["delivery"],
            "accuracy": row.get("accuracy"),
            "fluency": row.get("fluency"),
            "completeness": row.get("completeness"),
            "overall": row.get("overall"),
            "prosody": row.get("prosody"),
            "transcript": transcript,
            "eojeol": len(transcript.split()),
        })

    return {
        "rows": usable,
        "n_targets": len(targets),
        "n_usable": len(usable),
        "n_broken": len(broken),
        "broken": broken[:20],
        "n_called_this_run": called,
        "n_failed_this_run": failed,
        "cache_path": str(AZURE_CACHE),
        "azure_called": use_azure,
    }


# ══════════════════════════════════════════════════════════════════════════════
# 5) ② 내용 — 다시 돌리지 않고 체크리스트 실험 결과를 인용한다
# ══════════════════════════════════════════════════════════════════════════════

def load_content_reference() -> dict:
    """체크리스트 실험(v3·v4)에서 내용 영역 QWK 를 골라 인용한다.

    여기서 다시 계산하지 않는 이유: 그 실험은 겹마다 체크리스트를 새로 만들고
    LLM 판정을 수천 번 돌린 것이라 재현에 시간과 비용이 크다. 대신 그 파일이
    어떤 조건에서 나온 숫자인지를 보고서에 그대로 옮겨 적는다.
    """
    out = {"v3": {"methods": {}}, "v4": {"methods": {}}}

    if V3_SUMMARY.exists():
        v3 = json.load(open(V3_SUMMARY, encoding="utf-8"))
        for key in ("A1", "F", "J", "I", "D", "LEN"):
            m = v3.get("methods", {}).get(key)
            if m:
                out["v3"]["methods"][key] = {
                    "label": m.get("label"), "n": m.get("n"), "qwk": m.get("qwk"),
                    "qwk_ci95": m.get("qwk_ci95"), "pearson": m.get("pearson"),
                    "spearman": m.get("spearman"), "exact": m.get("exact"),
                    "within1": m.get("within1"),
                    "uses_training_data": m.get("uses_training_data"),
                }
        out["v3"]["model"] = v3.get("model")
        out["v3"]["input_type"] = v3.get("input_type")
        out["v3"]["human_label_field"] = v3.get("human_label_field")
        out["v3"]["dataset"] = v3.get("dataset")
        out["v3"]["run_date"] = v3.get("run_date")
        out["v3"]["file"] = str(V3_SUMMARY)

    if V4_SUMMARY.exists():
        v4 = json.load(open(V4_SUMMARY, encoding="utf-8"))
        for key in ("P", "Q"):
            m = v4.get("methods", {}).get(key)
            if m:
                out["v4"]["methods"][key] = {
                    "label": m.get("label"), "n": m.get("n"), "qwk": m.get("qwk"),
                    "qwk_ci95": m.get("qwk_ci95"), "pearson": m.get("pearson"),
                    "spearman": m.get("spearman"), "exact": m.get("exact"),
                    "within1": m.get("within1"),
                    "uses_training_data": m.get("uses_training_data"),
                }
        out["v4"]["judge_model"] = v4.get("judge_model")
        out["v4"]["comparability"] = v4.get("comparability", {})
        out["v4"]["run_date"] = v4.get("run_date")
        out["v4"]["file"] = str(V4_SUMMARY)

    # 운영 파이프라인의 내용 점수 구성(src/scoring/combine.py 실측값)
    out["operational_recipe"] = {
        "체크리스트 가중 충족율": 0.75,
        "응답 길이": 0.15,
        "문장당 어절 수": 0.10,
        "출처": "src/scoring/combine.py (content_checklist_weight=0.75, response_length=0.15, words_per_sentence=0.10)",
    }
    return out


# ══════════════════════════════════════════════════════════════════════════════
# 6) 보고서 만들기
# ══════════════════════════════════════════════════════════════════════════════

def _f(v, nd=3) -> str:
    """숫자를 표에 넣을 글자로 바꾼다. 값이 없으면 '—'."""
    if v is None:
        return "—"
    try:
        x = float(v)
    except (TypeError, ValueError):
        return html.escape(str(v))
    if math.isnan(x):
        return "—"
    return f"{x:.{nd}f}"


def _pct(v) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—"
    return f"{float(v) * 100:.1f}%"


def _ci(block) -> str:
    """신뢰구간을 '[아래, 위]' 모양으로 적는다."""
    c = (block or {}).get("qwk_ci95") or {}
    return f"[{_f(c.get('lo'))}, {_f(c.get('hi'))}]"


def render_confusion(matrix, title: str) -> str:
    """6×6 엇갈림 표를 HTML 로 그린다. 대각선(딱 맞은 칸)에 색을 준다."""
    total = sum(sum(r) for r in matrix)
    rows = []
    for i, row in enumerate(matrix):
        cells = []
        for j, v in enumerate(row):
            style = "background:#e8f0e8;font-weight:600;" if i == j else ("color:#bbb;" if v == 0 else "")
            cells.append(f'<td style="text-align:center;{style}">{v}</td>')
        rows.append(f'<tr><th style="text-align:center;">{i}</th>{"".join(cells)}<th style="text-align:center;color:#777;">{sum(row)}</th></tr>')
    col_tot = [sum(matrix[i][j] for i in range(6)) for j in range(6)]
    foot = "".join(f'<th style="text-align:center;color:#777;">{v}</th>' for v in col_tot)
    return f"""
<div style="margin:10px 0 18px;">
  <div style="font-weight:600;margin-bottom:4px;">{html.escape(title)} (총 {total}건)</div>
  <table>
    <tr><th rowspan="2" style="vertical-align:bottom;">우리<br>등급</th><th colspan="6" style="text-align:center;">사람 등급</th><th rowspan="2">합</th></tr>
    <tr>{''.join(f'<th style="text-align:center;">{g}</th>' for g in SCORE_LABELS)}</tr>
    {''.join(rows)}
    <tr><th>합</th>{foot}<th></th></tr>
  </table>
</div>"""


def render_predictor_rows(results: list[dict]) -> str:
    """예측 줄기별 결과를 한 표의 여러 행으로 그린다."""
    out = []
    for r in results:
        naive = r.get("naive")
        cal = r.get("calibrated")
        out.append(f"""<tr>
  <td>{html.escape(r['label'])}</td>
  <td style="text-align:right;">{r['n']}</td>
  <td style="text-align:right;">{r['n_speakers']}</td>
  <td style="text-align:right;">{_f(naive.get('qwk')) if naive else '—'}</td>
  <td style="text-align:right;color:#666;">{_ci(naive) if naive else '—'}</td>
  <td style="text-align:right;font-weight:600;">{_f(cal.get('qwk')) if cal else '—'}</td>
  <td style="text-align:right;color:#666;">{_ci(cal) if cal else '—'}</td>
  <td style="text-align:right;">{_f(r.get('pearson'))}</td>
  <td style="text-align:right;">{_f(r.get('spearman'))}</td>
  <td style="text-align:right;">{_pct(cal.get('exact')) if cal else '—'}</td>
  <td style="text-align:right;">{_pct(cal.get('within1')) if cal else '—'}</td>
</tr>""")
    return "".join(out)


PREDICTOR_TABLE_HEAD = """<table>
<tr>
  <th>예측 줄기</th><th>n</th><th>화자</th>
  <th>QWK<br>순진법</th><th>95% 구간</th>
  <th>QWK<br>눈금맵</th><th>95% 구간</th>
  <th>피어슨</th><th>스피어만</th><th>정확일치</th><th>±1 이내</th>
</tr>"""


def build_html(report: dict) -> str:
    """팀이 읽을 HTML 보고서를 만든다. 바깥 자료를 하나도 안 부르는 한 장짜리 파일이다."""
    pool = report["label_pool"]
    lang = report["language_use"]
    deli = report["delivery"]
    cont = report["content"]
    noise = report["label_noise_example"]

    # ── 사람 점수 분포표
    dist_rows = []
    for area, ko in (("content", "내용"), ("language_use", "언어사용"), ("delivery", "전달력")):
        d = pool["distribution"][area]
        cells = "".join(f'<td style="text-align:right;">{d[str(g)]}</td>' for g in SCORE_LABELS)
        mean = sum(int(g) * d[str(g)] for g in SCORE_LABELS) / max(1, pool["n"])
        dist_rows.append(f"<tr><th>{ko}</th>{cells}<td style='text-align:right;'>{pool['n']}</td>"
                         f"<td style='text-align:right;'>{mean:.2f}</td></tr>")

    corr = pool["cross_correlation_pearson"]
    corr_rows = "".join(
        f"<tr><th>{html.escape(k.replace('language_use', '언어사용').replace('content', '내용').replace('delivery', '전달력').replace('~', ' ↔ '))}</th>"
        f"<td style='text-align:right;font-weight:600;'>{_f(v)}</td></tr>"
        for k, v in corr.items()
    )

    # ── 영역별 결과
    lang_tbl = PREDICTOR_TABLE_HEAD + render_predictor_rows(lang["results"]) + "</table>"
    deli_tbl = PREDICTOR_TABLE_HEAD + render_predictor_rows(deli["results"]) + "</table>"

    # ── 내용(인용)
    def cite_rows(methods, src):
        rows = []
        for key, m in methods.items():
            ci = m.get("qwk_ci95") or {}
            rows.append(f"""<tr>
  <td>{html.escape(str(key))}</td><td>{html.escape(str(m.get('label')))}</td>
  <td style="text-align:right;">{m.get('n')}</td>
  <td style="text-align:right;font-weight:600;">{_f(m.get('qwk'))}</td>
  <td style="text-align:right;color:#666;">[{_f(ci.get('lo'))}, {_f(ci.get('hi'))}]</td>
  <td style="text-align:right;">{_f(m.get('pearson'))}</td>
  <td style="text-align:right;">{_pct(m.get('exact'))}</td>
  <td style="text-align:right;">{_pct(m.get('within1'))}</td>
  <td>{'정답 봄' if m.get('uses_training_data') else '안 봄'}</td>
  <td style="color:#777;">{html.escape(src)}</td>
</tr>""")
        return "".join(rows)

    content_tbl = ("<table><tr><th>기호</th><th>방법</th><th>n</th><th>QWK</th><th>95% 구간</th>"
                   "<th>피어슨</th><th>정확일치</th><th>±1 이내</th><th>학습 여부</th><th>출처</th></tr>"
                   + cite_rows(cont["v3"]["methods"], "v3")
                   + cite_rows(cont["v4"]["methods"], "v4")
                   + "</table>")

    # ── 요약 숫자 뽑기(맨 위 3줄용)
    def best(results, key="calibrated"):
        cand = [r for r in results if r.get(key) and not math.isnan(r[key]["qwk"])]
        return max(cand, key=lambda r: r[key]["qwk"]) if cand else None

    lang_main = next((r for r in lang["results"] if r["label"].startswith("언어사용 점수")), None)
    lang_len = next((r for r in lang["results"] if "길이" in r["label"]), None)
    deli_best = best([r for r in deli["results"] if "길이" not in r["label"]])
    deli_len = next((r for r in deli["results"] if "길이" in r["label"]), None)

    v3m = cont["v3"]["methods"]

    summary_bits = []
    if lang_main:
        summary_bits.append(
            f"<b>언어사용</b> QWK {_f(lang_main['calibrated']['qwk'])} "
            f"(눈금맵, {_ci(lang_main['calibrated'])}, n={lang_main['n']})")
    # 내용은 '운영에 가장 가까운 방법(I: 충족율×5)'을 먼저 적는다.
    # 표에서 가장 높은 A1 은 운영에서 쓰지 않는 방식이라 그것을 우리 성능으로 부르면 안 된다
    if "I" in v3m:
        extra = f", 표 최고는 A1 {_f(v3m['A1']['qwk'])}이지만 운영에서 안 쓰는 방식" if "A1" in v3m else ""
        summary_bits.append(
            f"<b>내용</b> QWK {_f(v3m['I']['qwk'])} "
            f"(운영에 가장 가까운 I 충족율×5, n={v3m['I']['n']}){extra}")
    if deli_best:
        summary_bits.append(
            f"<b>전달력</b> QWK {_f(deli_best['calibrated']['qwk'])} "
            f"({deli_best['label']}, {_ci(deli_best['calibrated'])}, n={deli_best['n']})")

    # 길이 기준선과 겹치는지 판정 문구
    def overlap_text(main, base):
        if not main or not base:
            return "길이 기준선과 비교하지 못했다."
        a, b = main["calibrated"]["qwk_ci95"], base["calibrated"]["qwk_ci95"]
        qa, qb = main["calibrated"]["qwk"], base["calibrated"]["qwk"]
        head = (f"우리 점수 QWK {_f(qa)} [{_f(a['lo'])}, {_f(a['hi'])}] vs "
                f"길이 기준선 QWK {_f(qb)} [{_f(b['lo'])}, {_f(b['hi'])}] — ")
        overlapped = not (a["lo"] > b["hi"] or b["lo"] > a["hi"])
        if overlapped:
            direction = ("게다가 점수만 보면 길이 기준선이 더 높다. " if qb > qa else "")
            return (head + "두 구간이 겹친다 → <b>길이 이상의 무언가를 재고 있다고 말할 수 없다.</b> "
                    + direction + "지금 표본에서는 '어절 수만 세는 자'와 구별되지 않는다.")
        if qa > qb:
            return head + "두 구간이 겹치지 않고 우리 점수가 위다 → <b>길이 이상을 재고 있다고 말할 수 있다.</b>"
        return (head + "두 구간이 겹치지 않고 길이 기준선이 위다 → "
                "<b>지금 점수는 어절 수만 세는 것보다 못하다.</b> 결합식을 손봐야 한다는 신호다.")

    lang_len_verdict = overlap_text(lang_main, lang_len)
    deli_len_verdict = overlap_text(deli_best, deli_len)

    # 맨 위 '한 줄 결론'을 실제 숫자에서 만든다(고정 문구를 박아 두면 다음 실행 때 거짓말이 된다)
    parts = []
    if lang_main and lang_len:
        if lang_len["calibrated"]["qwk"] >= lang_main["calibrated"]["qwk"]:
            parts.append("<b>언어사용 점수는 어절 수만 세는 길이 기준선을 넘지 못했다</b>"
                         "(결합식이 길이 신호를 제대로 못 쓰고 있다는 뜻)")
        else:
            parts.append("언어사용 점수는 길이 기준선보다 위다")
    if deli_best:
        parts.append(f"전달력은 Azure 발음 점수와 사람 라벨의 상관이 {_f(deli_best['pearson'])} 로 "
                     "낮아 <b>애초에 같은 것을 재고 있는지부터 의심스럽다</b>")
    # 신뢰구간이 실제로 얼마나 넓은지 — 말로 "넓다"고만 쓰지 않고 폭을 세어 적는다
    widths = []
    for r in lang["results"] + deli.get("results", []):
        c = r["calibrated"]["qwk_ci95"]
        if not math.isnan(c["lo"]) and not math.isnan(c["hi"]):
            widths.append(c["hi"] - c["lo"])
    ci_width_text = (f"{min(widths):.2f}~{max(widths):.2f}" if widths else "—")

    # 8/24 에 "Azure 발음 자질 ↔ delivery 상관 최고 0.15" 라고 적었던 것을 오늘 값으로 확인한다
    if deli["results"]:
        peaks = [r["pearson"] for r in deli["results"]
                 if "길이" not in r["label"] and not math.isnan(r["pearson"])]
        if peaks:
            top = max(peaks, key=abs)
            same = abs(top) < 0.30
            delivery_recheck = (
                f"<b>8/24 재확인</b> — 그때 Azure 발음 자질과 delivery 의 상관은 최고 0.15 였고, 그래서 "
                f'"delivery 는 AI Hub 일치를 포기하고 Azure 를 그대로 쓴다"는 방향이 검토됐다. '
                f"오늘 다시 재니 Azure 발음 점수 셋 중 가장 높은 피어슨이 <b>{_f(top)}</b> 다 — "
                + ("<b>8/24 결론이 재확인됐다.</b>" if same
                   else "8/24 때보다 눈에 띄게 올랐으므로 그 결론을 다시 검토해야 한다."))
        else:
            delivery_recheck = "<b>8/24 재확인</b> — 오늘 값을 계산하지 못했다."
    else:
        delivery_recheck = "<b>8/24 재확인</b> — 전달력 결과가 비어 있어 확인하지 못했다."

    conclusion = ("; ".join(parts) if parts else "계산된 값이 부족해 결론을 적지 못했다") + \
        f". 오늘 계산한 두 영역은 표본이 {lang['n']}건·{deli['n_usable']}건뿐이라 모든 숫자는 신뢰구간과 함께 읽어야 하고, " \
        "사람 점수 셋이 서로 0.75~0.85 로 붙어 있어 '영역별로 맞혔다'는 주장은 이 데이터로 할 수 없다."

    css = """
body{font-family:'Malgun Gothic','맑은 고딕',sans-serif;line-height:1.7;color:#222;
     max-width:1080px;margin:0 auto;padding:28px 22px 80px;background:#fff;}
h1{font-size:24px;border-bottom:3px solid #35506b;padding-bottom:8px;margin-bottom:6px;}
h2{font-size:19px;margin-top:38px;border-left:5px solid #35506b;padding-left:10px;}
h3{font-size:16px;margin-top:24px;color:#35506b;}
table{border-collapse:collapse;margin:10px 0 16px;font-size:13px;width:100%;}
th,td{border:1px solid #ccd3da;padding:5px 8px;}
th{background:#eef2f6;font-weight:600;}
.box{background:#f7f9fb;border:1px solid #d8e0e8;border-radius:6px;padding:14px 18px;margin:14px 0;}
.warn{background:#fdf6f0;border:1px solid #e6cdb4;}
.summary{background:#eef4ee;border:1px solid #c3d8c3;border-radius:6px;padding:16px 20px;font-size:15px;}
.meta{color:#777;font-size:13px;}
code{background:#f0f2f4;padding:1px 5px;border-radius:3px;font-size:12px;}
ul{margin:6px 0 6px 0;padding-left:22px;}
li{margin:4px 0;}
.q{font-weight:600;color:#8a4b2a;}
"""

    concerns = f"""
<h3>1) 사람 점수 세 개가 서로 너무 닮았다</h3>
<div class="box warn">
<b>무엇이 문제</b> — 세 점수의 상관이 {_f(corr.get('language_use~content'))}(언어사용↔내용),
{_f(corr.get('language_use~delivery'))}(언어사용↔전달력), {_f(corr.get('content~delivery'))}(내용↔전달력) 이다.<br>
<b>왜</b> — 한 사람이 한 번 듣고 받은 인상으로 세 칸을 함께 채운 흔적으로 보인다.
정말 서로 다른 능력을 따로 쟀다면 이렇게까지 붙어 있기 어렵다.<br>
<b>주장할 수 있는 것</b> — "우리 점수가 사람 점수와 비슷하게 움직인다"까지.<br>
<b>주장할 수 없는 것</b> — "우리가 <u>영역별로</u> 사람과 일치한다". 라벨 자체가 영역을 가르지 못하고 있으므로,
언어사용 QWK 가 높아도 그것이 '언어사용을 잘 잰 것'인지 '전반 인상을 잘 맞춘 것'인지 이 데이터로는 구별할 수 없다.
</div>

<h3>2) 채점자 수·루브릭·채점자 간 일치율을 모른다</h3>
<div class="box warn">
<b>무엇이 문제</b> — 로컬 자료 어디에도 몇 명이 매겼는지, 어떤 기준표를 썼는지, 채점자끼리 얼마나 맞았는지가 없다.<br>
<b>왜</b> — 원본 라벨 JSON 에는 점수 세 개만 들어 있고 채점 절차 문서가 함께 오지 않았다.<br>
<b>결과</b> — <b>천장을 모른다.</b> 사람끼리의 일치율이 0.7 인 라벨이라면 기계가 0.7 을 넘는 것은 오히려 이상한 일이고,
0.9 라면 우리 숫자는 한참 낮은 것이다. 지금 QWK 를 "좋다/나쁘다"로 부를 기준선이 없다.<br>
<b>실물 증거</b> — 낭독 문항 <code>{html.escape(noise.get('id', ''))}</code> 는
지문 "{html.escape(noise.get('prompt', ''))}" 를 "{html.escape(noise.get('ref', ''))}" 로 거의 그대로 읽었는데
<b>언어사용 {noise.get('evals', {}).get('language_use')}점, 내용 {noise.get('evals', {}).get('content')}점</b>이 붙어 있다.
이런 값이 섞인 라벨을 정답으로 놓고 재는 중이다.
</div>

<h3>3) 표본이 작다 — 구간이 넓다</h3>
<div class="box warn">
<b>무엇이 문제</b> — 언어사용 n={lang['n']}, 전달력 n={deli['n_usable']}, 내용 n={cont['v3']['methods'].get('A1', {}).get('n', '—')} 이다.
오늘 계산한 항목들의 95% 구간 폭은 <b>{ci_width_text}</b> 다(QWK 는 0~1 사이 값이므로 이 폭은 매우 넓다).<br>
<b>왜</b> — 라벨이 붙은 자유발화 자체가 442건뿐이고, 영역마다 쓸 수 있는 조건(사람 전사·음성 존재·문항당 25건 이상)이 달라 더 줄어든다.<br>
<b>추가 위험</b> — 언어사용은 ref 126건 중 {lang['n_dropped']}건(status invalid·llm_failed)이 빠진 {lang['n']}건이다.
빠진 것이 '어려운 답안'에 몰려 있으면 남은 표본이 실제보다 쉬워져 점수가 올라간다(선택 편향).
빠진 건의 특성을 확인하지 않았으므로 <b>편향이 없다고 말할 수 없다.</b><br>
<b>주장할 수 있는 것</b> — 구간을 반드시 함께 적은 값. 소수점 둘째 자리 비교는 하지 않는다.
</div>

<h3>4) 눈금 맵은 정답을 조금 보고 배운 것이다</h3>
<div class="box warn">
<b>무엇이 문제</b> — '눈금맵' 열은 화자를 갈라 교차검증한 값이지만, 그래도 배우는 겹에서 사람 점수를 보고
"우리 70점은 대략 3점" 같은 직선을 맞춘 결과다.<br>
<b>왜 그렇게 했나</b> — 우리 점수는 0~100, 사람 점수는 0~5라 그냥 20으로 나누면 눈금이 안 맞아서
채점 능력과 무관하게 QWK 가 깎인다. 자 문제와 실력 문제를 섞지 않으려고 둘 다 실었다.<br>
<b>그래서</b> — 라벨 한 장 없이 바로 투입했을 때의 성능은 <b>순진법 쪽에 가깝다.</b>
두 값이 크게 벌어지는 영역은 "점수의 순서는 맞는데 눈금이 어긋나 있다"는 뜻이다.
</div>

<h3>5) 길이 함정</h3>
<div class="box warn">
<b>무엇이 문제</b> — 답을 길게 하면 조사 종류도 어미 종류도 자동으로 늘어난다.
그래서 "말을 잘한다"가 아니라 "말을 많이 했다"를 재고 있을 수 있다(8/24 자질 상관 조사에서 이미 지적된 함정).<br>
<b>어떻게 쟀나</b> — 전사의 어절 수 하나만으로 똑같은 눈금 맵 절차를 돌린 <b>길이 기준선(LEN)</b>을 나란히 놓았다.<br>
<b>언어사용</b> — {lang_len_verdict}<br>
<b>전달력</b> — {deli_len_verdict}
</div>

<h3>6) 내용 영역의 숫자는 조건이 다르다</h3>
<div class="box warn">
<b>무엇이 문제</b> — 내용 QWK 는 오늘 다시 계산한 값이 아니라 8/9 체크리스트 실험에서 인용한 값이다. 조건이 세 가지 다르다.<br>
<b>① 체크리스트가 다르다</b> — 실험은 LLM 이 겹마다 생성한 체크리스트를 썼고, 운영은 문항 저자가 손으로 쓴 체크리스트를 쓴다.<br>
<b>② 판정 모델이 다르다</b> — v3 는 gemini-3.1-flash-lite, v4(P·Q)는 qwen3-30b 다.
v4 파일에 적힌 그대로: "{html.escape(str(cont['v4'].get('comparability', {}).get('vs_v1_v2_v3', '')))} —
{html.escape(str(cont['v4'].get('comparability', {}).get('reason', ''))[:200])}"<br>
<b>③ 입력이 다르다</b> — 실험은 사람이 적은 전사를 넣었다. 실제 시험은 STT 를 거치므로 전사 오류가 섞인다.
따라서 이 값들은 실제 음성 경로보다 <b>후한 값</b>이다.<br>
<b>④ 결합식이 다르다</b> — 운영 내용 점수는 체크리스트 충족율 0.75 + 응답 길이 0.15 + 문장당 어절 0.10 이다.
실험 방법 중 이에 가장 가까운 것은 <b>충족율×5 계열(D·I)</b>이고, A1(LLM 직접 채점)은 운영에서 쓰지 않는 방식이다.
표에서 가장 높은 A1 을 우리 성능이라고 말하면 안 된다.
</div>

<h3>7) 전달력 — 무엇을 재는지부터 서로 다르다</h3>
<div class="box warn">
<b>무엇이 문제</b> — AI Hub 의 '전달력'이 무엇을 뜻하는지 정의 문서가 없다. Azure 발음평가는 명확히
<u>소리</u>(음소 정확도·끊김 없이 이어 말함)만 본다.<br>
<b>왜</b> — 사람 채점자가 '전달력'에 내용 전달의 명료함이나 자신감까지 넣었다면 Azure 가 맞출 길이 없다.<br>
{delivery_recheck}<br>
<b>그래서</b> — 전달력 QWK 가 낮은 것을 "우리 발음 평가가 나쁘다"로 읽으면 안 된다.
"AI Hub 라벨과 겨냥하는 과녁이 다르다"가 먼저 검토돼야 한다. 운영에서 delivery 비중이 0.20 임시값인 것도 이 때문이다.
</div>

<h3>8) 0.801(쌍둥이 논문)과 직접 비교하지 말 것</h3>
<div class="box warn">
<b>무엇이 문제</b> — 우리가 과녁 삼아 온 0.801 은 다른 데이터·다른 과제(TOPIK 급 예측)에서 나온 숫자다.<br>
<b>왜 비교가 안 되나</b> — 등급 칸 수, 라벨을 만든 사람, 문항 유형, 표본 크기가 전부 다르다.
QWK 는 라벨의 분포에 따라 값이 크게 움직이는 지표라 조건이 다르면 크기 비교가 성립하지 않는다.<br>
<b>이 보고서 숫자의 용도</b> — 남과의 우열이 아니라 <b>우리 자신의 현재 위치 측정</b>이다.
같은 절차를 다음에 다시 돌려 이 표와 비교하는 것이 정당한 사용법이다.
</div>
"""

    return f"""<meta charset="utf-8">
<title>3영역 QWK 측정 보고 (2026-08-31)</title>
<style>{css}</style>

<h1>우리 채점 3영역 vs AI Hub 사람 점수 — QWK 측정</h1>
<p class="meta">2026-08-31 · 팀 내부 보고서(심사용 아님) · 생성: <code>scripts/speech_lab/qwk_lab.py</code>
· 실행 시각 {html.escape(report['run_date'])}</p>

<div class="summary">
<b>쉬운 요약</b>
<ol style="margin:8px 0 0;padding-left:22px;">
<li><b>무엇을 쟀나</b> — 우리가 매긴 점수를 0~5 등급으로 바꿔서, AI Hub 라벨을 매긴 사람과 같은 등급을 주는지 QWK 로 쟀다.</li>
<li><b>핵심 숫자</b> — {' · '.join(summary_bits) if summary_bits else '계산된 값 없음'}</li>
<li><b>한 줄 결론</b> — {conclusion}</li>
</ol>
</div>

<h2>1. 사람 점수가 무엇인가</h2>
<div class="box">
<b>출처</b> — AI Hub 「교육용 아시아어(중·일어 제외) 사용자의 한국어 음성 데이터」(데이터 번호 71479).
원본 라벨 JSON(<code>Sample/02.라벨링데이터/Speech/lab/*.json</code>)의 <code>EvaluationMetadata</code> 안에
<code>DeliveryEval</code>(전달력) · <code>LanguageUseEval</code>(언어사용) · <code>ContentEval</code>(내용) 세 정수(0~5)가
녹음 1건마다 <b>각각 1개씩</b> 붙어 있다. 우리 목록 파일에서는 <code>evals.delivery / language_use / content</code> 다.<br><br>
<b>모르는 것 (반드시 명시)</b>
<ul>
<li>채점자 수 — <b>알 수 없음</b> (로컬 자료에 없음)</li>
<li>채점 기준표(루브릭) 본문 — <b>알 수 없음</b></li>
<li>채점자 간 일치율 — <b>알 수 없음</b></li>
</ul>
8/24 에 우리가 "전달력은 CER 기반인 듯"이라고 적은 것은 <b>가설이지 확인된 사실이 아니다.</b>
</div>

<h3>라벨 풀</h3>
<p>목록 파일 <code>C:\\해커톤\\data\\manifests\\*.jsonl</code> 전체를 id 로 중복 제거하면 {pool['n_unique_ids_scanned']}건이고,
그중 자유발화(task=ATQ)이면서 세 점수가 모두 정수인 것은 <b>{pool['n']}건</b>이다
(화자 {pool['n_speakers']}명, 질문 {pool['n_prompts']}종).</p>

<h3>세 점수의 분포 (0~5, 건수)</h3>
<table>
<tr><th>영역</th>{''.join(f'<th style="text-align:right;">{g}점</th>' for g in SCORE_LABELS)}<th style="text-align:right;">합</th><th style="text-align:right;">평균</th></tr>
{''.join(dist_rows)}
</table>

<h3>세 점수 서로의 상관 (피어슨, n={pool['n']})</h3>
<table><tr><th>짝</th><th style="text-align:right;">상관</th></tr>{corr_rows}</table>
<p class="meta">셋 다 0.7 을 훌쩍 넘는다. 이 숫자가 아래 '우려점 1'의 근거다.
이 값은 이 스크립트가 위 {pool['n']}건 풀에서 <b>이번 실행에 직접 계산</b>한 것이다
(이전 메모에 조금 다른 값이 적혀 있다면 풀을 고르는 조건이 달랐던 것이고, 재현 가능한 쪽은 이 표다).</p>

<h3>라벨 잡음 예시 (실물)</h3>
<div class="box warn">
<code>{html.escape(noise.get('id', ''))}</code> — 낭독(LAR) 문항<br>
읽어야 할 지문: <b>{html.escape(noise.get('prompt', ''))}</b><br>
실제로 읽은 것: <b>{html.escape(noise.get('ref', ''))}</b><br>
붙은 점수: 전달력 {noise.get('evals', {}).get('delivery')} · <b>언어사용 {noise.get('evals', {}).get('language_use')}</b> · 내용 {noise.get('evals', {}).get('content')}<br>
<span class="meta">거의 그대로 읽었는데 언어사용이 0점이고 내용은 5점이다. 이런 값이 정답 쪽에 섞여 있다는 사실 자체를 기록해 둔다.
(출처: {html.escape(noise.get('source_file', ''))})</span>
</div>

<h2>2. QWK 가 무엇인가 (5줄 풀이)</h2>
<div class="box">
<ol style="padding-left:22px;">
<li><b>QWK(이차 가중 카파)</b> — 두 채점자가 <u>같은 등급</u>을 주는 정도. 0~1 사이이고 1이면 완전일치,
0이면 아무렇게나 찍은 것과 다를 바 없음. 음수면 반대로 매긴 것.</li>
<li><b>'이차 가중'</b> — 많이 빗나갈수록 더 크게 깎는다. 3점을 4점으로 본 것과 3점을 0점으로 본 것을 똑같이 세지 않는다(빗나간 칸 수의 제곱으로 벌점).</li>
<li><b>눈금 맵</b> — 우리 점수는 0~100, 사람 점수는 0~5다. 그냥 20으로 나누는 것이 '순진법'이고,
사람 점수를 보고 "우리 70점은 대략 3점" 같은 직선을 맞춰 옮기는 것이 '눈금 맵'이다.</li>
<li><b>교차검증</b> — 눈금 맵의 직선은 답을 보고 배우는 것이라, 화자를 5조각으로 갈라
네 조각에서 직선을 배우고 남은 한 조각에만 적용한다. 같은 사람 답안이 배우는 쪽·시험 쪽에 동시에 들어가지 않게 한다.</li>
<li><b>부트스트랩 / 신뢰구간</b> — 표본이 100건 남짓이라 QWK 하나만 보면 운인지 실력인지 모른다.
화자를 통째로 {N_BOOT}번 다시 뽑아 매번 QWK 를 재고, 그 값들의 가운데 95%를 '95% 신뢰구간'으로 적는다.
<b>구간이 겹치는 두 값은 서로 다르다고 말하지 않는다.</b></li>
</ol>
</div>

<h2>3. 영역별 결과</h2>

<h3>① 언어사용 — 오늘 계산</h3>
<p>재료: <code>{html.escape(str(DOWNSTREAM))}</code> 의 <code>arm=="ref"</code>(사람이 적은 전사를 그대로 채점한 줄)
{lang['n_ref_rows']}건 중 언어사용 점수가 나온 <b>{lang['n']}건</b>.
빠진 {lang['n_dropped']}건의 내역: {', '.join(f'{k} {v}건' for k, v in lang['status_counter'].items() if k != 'ok')}.
예측 = <code>language_score</code>(0~100, 운영 손가중치 provisional_v0), 정답 = <code>evals.language_use</code>.</p>
<p class="meta">정답 대조: <code>gold_499_eval.jsonl</code> 과 id 로 맞춰 본 결과 —
대조한 {lang['gold_join']['n_checked']}건 중 gold 에 없던 것 {lang['gold_join']['n_not_in_gold']}건,
값이 어긋난 것 {lang['gold_join']['n_mismatch']}건{'(어긋난 건은 gold 값을 정답으로 썼다)' if lang['gold_join']['n_mismatch'] else ''}.</p>
{lang_tbl}
{''.join(render_confusion(r['calibrated']['confusion'], f"엇갈림 표 — {r['label']} (눈금맵)")
         for r in lang['results'] if '길이' not in r['label'])}

<h3>② 내용 — 다시 돌리지 않고 인용</h3>
<p>출처: <code>outputs/checklist_lab/results_summary_v3.json</code>({html.escape(str(cont['v3'].get('run_date', '')))},
판정 모델 {html.escape(str(cont['v3'].get('model', '')))}) 와
<code>results_summary_v4.json</code>({html.escape(str(cont['v4'].get('run_date', '')))},
판정 모델 {html.escape(str(cont['v4'].get('judge_model', '')))}).
n=281(질문 9종, 화자 270명), 입력은 {html.escape(str(cont['v3'].get('input_type', '')))},
정답은 {html.escape(str(cont['v3'].get('human_label_field', '')))}.</p>
{content_tbl}
<div class="box warn">
<b>v4(P·Q) 는 v1~v3 와 직접 비교 금지.</b> 파일에 적힌 문구 그대로:<br>
"{html.escape(str(cont['v4'].get('comparability', {}).get('vs_v1_v2_v3', '')))} —
{html.escape(str(cont['v4'].get('comparability', {}).get('reason', '')))}"
</div>
<p><b>운영 파이프라인의 내용 점수</b>는 체크리스트 가중 충족율 <b>0.75</b> + 응답 길이 <b>0.15</b> + 문장당 어절 수 <b>0.10</b> 이다
(<code>src/scoring/combine.py</code> 실측). 위 실험 방법 중 이에 가장 가까운 것은 <b>충족율×5 계열(D·I)</b>이며,
A1·F·J 는 운영에서 쓰지 않는 방식이다. 또한 실험 체크리스트는 <b>LLM 이 겹별로 생성</b>한 것이라
운영(문항 저자가 직접 작성)과 항목 자체가 다르다.</p>

<h3>③ 전달력 — Azure 를 다시 돌려서 계산</h3>
<p>재료: <code>gold_present.jsonl</code> 의 자유발화(ATQ) 중 전달력 점수가 있는 <b>{deli['n_targets']}건</b>.
그중 발음 점수를 받은 것 <b>{deli['n_usable']}건</b>, 실패·미수집 <b>{deli['n_broken']}건</b>.
이번 실행에서 Azure 를 부른 건수 {deli['n_called_this_run']}건(그중 실패 {deli['n_failed_this_run']}건).
건별 결과는 <code>{html.escape(deli['cache_path'])}</code> 에 한 줄씩 남겼다.</p>
<p class="meta">지난번에는 요약 txt 만 남기고 건별 값을 버려서 오늘 다시 돌려야 했다. 그래서 이번에는 한 건 끝날 때마다 캐시에 적는다.<br>
예측 후보에서 뺀 두 가지: <b>완전성(Completeness)</b>은 '읽어야 할 지문 중 얼마나 읽었나'라서 정답지가 없는 자유발화에서는 늘 100이 나와 쓸모가 없고,
<b>억양(Prosody)</b>은 Azure 가 한국어에 대해 값을 주지 않는다(캐시에 전부 null).</p>
{deli_tbl}
{render_confusion(deli_best['calibrated']['confusion'], f"엇갈림 표 — {deli_best['label']} (눈금맵, 셋 중 QWK 가 가장 높은 것)") if deli_best else '<p class="meta">엇갈림 표를 그릴 값이 없다.</p>'}

<h2>4. 우려점 — 이 숫자로 무엇을 말할 수 있고 없는가</h2>
{concerns}

<h2>5. 파일 위치와 재현 방법</h2>
<table>
<tr><th>무엇</th><th>어디</th></tr>
<tr><td>이 보고서</td><td><code>{html.escape(str(OUT_HTML))}</code></td></tr>
<tr><td>같은 내용의 JSON</td><td><code>{html.escape(str(OUT_JSON))}</code></td></tr>
<tr><td>스크립트</td><td><code>{html.escape(str(ROOT / 'scripts' / 'speech_lab' / 'qwk_lab.py'))}</code></td></tr>
<tr><td>단위 테스트</td><td><code>{html.escape(str(ROOT / 'tests' / 'test_qwk_lab.py'))}</code></td></tr>
<tr><td>Azure 건별 캐시</td><td><code>{html.escape(deli['cache_path'])}</code></td></tr>
<tr><td>언어사용 재료</td><td><code>{html.escape(str(DOWNSTREAM))}</code></td></tr>
<tr><td>라벨 풀</td><td><code>{html.escape(str(MANIFEST_DIR))}\\*.jsonl</code></td></tr>
<tr><td>내용 인용 원본</td><td><code>outputs/checklist_lab/results_summary_v3.json</code>, <code>…_v4.json</code></td></tr>
</table>
<p><b>재현 명령</b> (assessment 폴더에서):</p>
<pre style="background:#f0f2f4;padding:10px;border-radius:4px;font-size:12px;">python scripts/speech_lab/qwk_lab.py            # 전체 (캐시된 Azure 건은 건너뜀)
python scripts/speech_lab/qwk_lab.py --no-azure # Azure 호출 없이 캐시만으로
python scripts/speech_lab/qwk_lab.py --selftest # 계산기 자체 점검
python -m pytest tests/test_qwk_lab.py -q       # 네트워크 없이 도는 단위 테스트</pre>
<p class="meta">고정값: 씨앗 {SEED} · 겹 {FOLDS} · 부트스트랩 {N_BOOT}회(화자 단위 재추출).</p>
"""


# ══════════════════════════════════════════════════════════════════════════════
# 7) 자체 점검 — 계산기가 제대로 도는지 확인
# ══════════════════════════════════════════════════════════════════════════════

def selftest() -> int:
    """네트워크 없이 계산기만 확인한다. 실패하면 0이 아닌 값을 돌려준다."""
    fails = []
    rng = np.random.default_rng(0)

    # ① 똑같은 예측 → QWK 가 1.0 이어야 한다
    truth = rng.integers(0, 6, size=300)
    v = qwk(truth, truth)
    print(f"  ① 같은 예측 QWK = {v:.4f} (기대 1.0)")
    if abs(v - 1.0) > 1e-9:
        fails.append("같은 예측인데 QWK 가 1.0 이 아니다")

    # ② 무작위로 뒤섞으면 0 근처여야 한다
    shuffled = truth.copy()
    rng.shuffle(shuffled)
    v = qwk(shuffled, truth)
    print(f"  ② 무작위 뒤섞기 QWK = {v:.4f} (기대 0 근처, |값| < 0.15)")
    if abs(v) > 0.15:
        fails.append("무작위인데 QWK 가 0 에서 너무 멀다")

    # ③ y=x 자료에서 눈금 맵의 직선이 기울기 1, 절편 0 이어야 한다
    x = np.linspace(0, 5, 50)
    slope, intercept = fit_linear_map(x, x)
    print(f"  ③ y=x 직선 맞추기 → 기울기 {slope:.6f} (기대 1) · 절편 {intercept:.6f} (기대 0)")
    if abs(slope - 1.0) > 1e-6 or abs(intercept) > 1e-6:
        fails.append("y=x 인데 직선이 y=x 로 안 나온다")

    # ④ 0~100 점수를 20으로 나누면 0~5 등급이 되어야 한다(순진법).
    #    50점은 2.5라서 딱 가운데인데, numpy 는 이럴 때 짝수 쪽으로 붙인다(2.5→2, 3.5→4).
    #    train_score_model.py 도 같은 반올림을 쓰므로 여기서도 맞춰 둔다.
    g = to_grade(np.array([0.0, 19.0, 50.0, 60.0, 99.0, 120.0, -5.0]) / 20.0)
    print(f"  ④ 순진법 등급 변환 = {g.tolist()} (기대 [0, 1, 2, 3, 5, 5, 0]; 50점은 2.5→짝수쪽 2)")
    if g.tolist() != [0, 1, 2, 3, 5, 5, 0]:
        fails.append("순진법 등급 변환이 기대와 다르다")

    # ⑤ 0~100 점수를 눈금 맵으로 옮기면 완전일치가 나와야 한다
    #    (사람 점수 = 우리 점수/20 인 인공 자료 — 자 문제만 있고 실력 문제는 없는 상황)
    truth5 = rng.integers(0, 6, size=200)
    raw100 = truth5 * 20.0
    groups = np.array([f"S{i // 2}" for i in range(200)])
    grades, params = calibrated_grades(raw100, truth5, groups)
    v = qwk(grades, truth5)
    print(f"  ⑤ 눈금만 다른 완벽한 예측 QWK = {v:.4f} (기대 1.0)")
    if abs(v - 1.0) > 1e-9:
        fails.append("눈금만 다른 완벽한 예측인데 QWK 가 1.0 이 아니다")

    # ⑥ 부트스트랩 구간이 QWK 값을 감싸야 한다
    ci = bootstrap_qwk_ci(grades, truth5, groups, n_boot=200, seed=SEED)
    print(f"  ⑥ 부트스트랩 95% 구간 = [{ci['lo']:.4f}, {ci['hi']:.4f}] (기대: 1.0 을 포함)")
    if not (ci["lo"] <= 1.0 <= ci["hi"] + 1e-9):
        fails.append("부트스트랩 구간이 실제 값을 감싸지 못한다")

    print()
    if fails:
        for f in fails:
            print(f"  X {f}")
        return 1
    print("  전부 통과")
    return 0


# ══════════════════════════════════════════════════════════════════════════════
# 8) 실행
# ══════════════════════════════════════════════════════════════════════════════

def main() -> int:
    parser = argparse.ArgumentParser(description="3영역 QWK 측정 실험")
    parser.add_argument("--selftest", action="store_true", help="계산기 자체 점검만 하고 끝낸다")
    parser.add_argument("--no-azure", action="store_true", help="Azure 를 부르지 않고 캐시만 쓴다")
    parser.add_argument("--limit-azure", type=int, default=None, help="이번 실행에서 부를 Azure 건수 제한")
    parser.add_argument("--n-boot", type=int, default=N_BOOT, help="부트스트랩 횟수")
    args = parser.parse_args()

    if args.selftest:
        print("자체 점검")
        return selftest()

    n_boot = args.n_boot
    report = {"run_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
              "seed": SEED, "folds": FOLDS, "n_boot": n_boot}

    # ── 사람 점수 살펴보기
    print("[1/4] 사람 점수(라벨) 읽는 중 …")
    pool = load_label_pool()
    report["label_pool"] = {k: v for k, v in pool.items() if k != "rows"}
    report["label_noise_example"] = find_noise_example()
    print(f"  자유발화 세 점수 모두 있는 답안 {pool['n']}건 "
          f"(화자 {pool['n_speakers']}명, 질문 {pool['n_prompts']}종)")
    for k, v in pool["cross_correlation_pearson"].items():
        print(f"  상관 {k} = {v:.3f}")

    # ── ① 언어사용
    print("\n[2/4] 언어사용 QWK 계산 중 …")
    lang = load_language_rows()
    rows = lang["rows"]
    truth = [r["truth"] for r in rows]
    groups = [r["speaker_id"] for r in rows]
    lang_results = [
        evaluate_predictor("언어사용 점수(운영 손가중치 provisional_v0)",
                           [r["pred"] for r in rows], truth, groups,
                           naive_divisor=20.0, n_boot=n_boot,
                           note="0~100 점수. arm=ref(사람 전사) 입력"),
        evaluate_predictor("길이 기준선(어절 수만)",
                           [r["eojeol"] for r in rows], truth, groups,
                           naive_divisor=None, n_boot=n_boot,
                           note="전사의 어절 수 하나만으로 같은 눈금 맵 절차"),
    ]
    report["language_use"] = {
        "n": len(rows), "n_speakers": len(set(groups)),
        "n_ref_rows": lang["n_ref_rows"], "n_dropped": lang["n_dropped"],
        "status_counter": lang["status_counter"], "gold_join": lang["gold_join"],
        "source": str(DOWNSTREAM), "results": lang_results,
    }
    for r in lang_results:
        nq = r.get("naive", {}).get("qwk")
        print(f"  {r['label']}: n={r['n']} 화자={r['n_speakers']} "
              f"QWK(순진)={_f(nq)} QWK(눈금맵)={_f(r['calibrated']['qwk'])} "
              f"{_ci(r['calibrated'])} 피어슨={_f(r['pearson'])}")

    # ── ③ 전달력
    print("\n[3/4] 전달력 — Azure 발음평가 …")
    targets = load_delivery_targets()
    print(f"  대상 {len(targets)}건, 캐시에 이미 {len(read_azure_cache())}건")
    deli = run_azure_delivery(targets, use_azure=not args.no_azure, limit=args.limit_azure)
    drows = deli["rows"]
    if drows:
        dtruth = [r["truth"] for r in drows]
        dgroups = [r["speaker_id"] for r in drows]
        deli_results = []
        for key, ko in (("overall", "종합(PronScore)"), ("accuracy", "정확도(Accuracy)"),
                        ("fluency", "유창성(Fluency)")):
            sub = [r for r in drows if r.get(key) is not None]
            if len(sub) < 10:
                print(f"  ! {ko}: 값이 있는 건이 {len(sub)}건뿐이라 건너뛴다")
                continue
            deli_results.append(evaluate_predictor(
                f"Azure {ko}", [r[key] for r in sub],
                [r["truth"] for r in sub], [r["speaker_id"] for r in sub],
                naive_divisor=20.0, n_boot=n_boot, note="Azure 발음평가 0~100"))
        deli_results.append(evaluate_predictor(
            "길이 기준선(Azure 전사 어절 수)", [r["eojeol"] for r in drows], dtruth, dgroups,
            naive_divisor=None, n_boot=n_boot, note="Azure 가 받아쓴 글의 어절 수"))
        deli["results"] = deli_results
        for r in deli_results:
            nq = r.get("naive", {}).get("qwk")
            print(f"  {r['label']}: n={r['n']} 화자={r['n_speakers']} "
                  f"QWK(순진)={_f(nq)} QWK(눈금맵)={_f(r['calibrated']['qwk'])} "
                  f"{_ci(r['calibrated'])} 피어슨={_f(r['pearson'])}")
    else:
        deli["results"] = []
        print("  ! 쓸 수 있는 발음 점수가 하나도 없다. 전달력 표는 비게 된다.")
    deli.pop("rows", None)
    report["delivery"] = deli

    # ── ② 내용
    print("\n[4/4] 내용 — 기존 실험 결과 인용 …")
    cont = load_content_reference()
    report["content"] = cont
    for src in ("v3", "v4"):
        for key, m in cont[src]["methods"].items():
            ci = m.get("qwk_ci95") or {}
            print(f"  [{src}] {key} {m['label']}: n={m['n']} QWK={_f(m['qwk'])} "
                  f"[{_f(ci.get('lo'))}, {_f(ci.get('hi'))}]")

    # ── 저장
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_HTML.write_text(build_html(report), encoding="utf-8")
    print(f"\n저장:\n  {OUT_HTML}\n  {OUT_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
