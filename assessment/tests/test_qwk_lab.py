"""QWK 실험 스크립트(scripts/speech_lab/qwk_lab.py)의 계산기 부분 회귀 테스트.

여기서 확인하는 것은 '자'가 제대로 도는가 하나다. 네트워크도, 파일도 건드리지 않는다.
채점 결과를 믿으려면 자부터 믿을 수 있어야 하므로, 값을 알고 있는 인공 자료를 넣어
기대한 답이 나오는지 본다.

실행:
    python -m pytest tests/test_qwk_lab.py -q
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 스크립트는 패키지가 아니라 실행 파일이라 경로로 직접 불러온다
_spec = importlib.util.spec_from_file_location(
    "qwk_lab", ROOT / "scripts" / "speech_lab" / "qwk_lab.py"
)
qwk_lab = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(qwk_lab)


# ── to_grade: 아무 숫자나 0~5 등급으로 ──────────────────────────────────────

def test_to_grade_는_0에서_5_사이로_자른다():
    """범위를 벗어난 값이 등급 밖으로 새어 나가면 QWK 계산 자체가 깨진다."""
    grades = qwk_lab.to_grade([-3.0, 0.4, 2.6, 5.4, 99.0])
    assert grades.tolist() == [0, 0, 3, 5, 5]


def test_to_grade_는_0에서_100_점수를_20으로_나눠_등급으로_만든다():
    """순진법(그냥 20으로 나누기)이 뜻대로 도는지 확인한다.

    50점은 2.5로 딱 가운데인데 numpy 는 이럴 때 짝수 쪽(2)으로 붙인다.
    이 성질을 모르고 보면 '반올림이 틀렸다'고 오해하므로 여기에 못을 박아 둔다.
    """
    grades = qwk_lab.to_grade(np.array([0.0, 19.0, 50.0, 60.0, 99.0]) / 20.0)
    assert grades.tolist() == [0, 1, 2, 3, 5]


# ── qwk: 등급 일치율 ─────────────────────────────────────────────────────────

def test_완전히_같게_매기면_QWK가_1이다():
    truth = [0, 1, 2, 3, 4, 5, 3, 2, 4, 1]
    assert qwk_lab.qwk(truth, truth) == pytest.approx(1.0)


def test_아무_관계_없이_매기면_QWK가_0_근처다():
    """무작위로 뒤섞은 예측은 '찍은 것'과 같아야 한다(0 근처)."""
    rng = np.random.default_rng(7)
    truth = rng.integers(0, 6, size=400)
    shuffled = truth.copy()
    rng.shuffle(shuffled)
    assert abs(qwk_lab.qwk(shuffled, truth)) < 0.15


def test_많이_빗나갈수록_더_크게_깎인다():
    """이차 가중의 핵심 성질 — 1칸 어긋난 것보다 4칸 어긋난 것이 훨씬 나쁘다."""
    truth = [1, 1, 1, 4, 4, 4, 2, 3, 5, 0]
    near = [2, 1, 1, 3, 4, 4, 2, 3, 5, 0]   # 몇 건만 1칸씩 어긋남
    far = [5, 1, 1, 0, 4, 4, 2, 3, 5, 0]    # 같은 건수가 4칸씩 어긋남
    assert qwk_lab.qwk(near, truth) > qwk_lab.qwk(far, truth)


# ── fit_linear_map / calibrated_grades: 눈금 맞추기 ──────────────────────────

def test_눈금맵은_y_equals_x_자료에서_기울기1_절편0을_찾는다():
    x = np.linspace(0.0, 5.0, 40)
    slope, intercept = qwk_lab.fit_linear_map(x, x)
    assert slope == pytest.approx(1.0, abs=1e-6)
    assert intercept == pytest.approx(0.0, abs=1e-6)


def test_눈금맵은_0에서_100_점수를_0에서_5로_옮긴다():
    """100점 만점 점수와 5점 만점 정답이 정확히 20배 관계일 때 기울기가 1/20 이어야 한다."""
    truth = np.array([0, 1, 2, 3, 4, 5] * 5, dtype=float)
    raw100 = truth * 20.0
    slope, intercept = qwk_lab.fit_linear_map(raw100, truth)
    assert slope == pytest.approx(0.05, abs=1e-9)
    assert intercept == pytest.approx(0.0, abs=1e-9)


def test_예측값이_전부_같으면_평균으로_민다():
    """기울기를 구할 수 없는 자료에서 계산이 터지지 않고 평균으로 물러나는지 본다."""
    slope, intercept = qwk_lab.fit_linear_map([3.0] * 10, [1, 2, 3, 4, 5] * 2)
    assert slope == 0.0
    assert intercept == pytest.approx(3.0)


def test_눈금만_어긋난_완벽한_예측은_눈금맵을_거치면_QWK가_1이다():
    """'자 문제'와 '실력 문제'를 가르는 자리.

    사람 점수가 정확히 우리 점수/20 인 인공 자료라면 순서는 완벽하다.
    순진법이든 눈금맵이든 1.0 이 나와야 하고, 그래야 실제 자료에서 두 값이
    벌어졌을 때 '눈금이 어긋난 것'이라고 읽을 수 있다.
    """
    rng = np.random.default_rng(3)
    truth = rng.integers(0, 6, size=120)
    raw100 = truth * 20.0
    groups = np.array([f"S{i // 3}" for i in range(120)])
    grades, params = qwk_lab.calibrated_grades(raw100, truth, groups)
    assert qwk_lab.qwk(grades, truth) == pytest.approx(1.0)
    assert len(params) == qwk_lab.FOLDS


def test_눈금맵은_화자를_배우는쪽과_시험쪽에_동시에_넣지_않는다():
    """같은 사람 답안이 양쪽에 들어가면 성능이 실제보다 좋게 나온다 — 겹 나누기 확인."""
    groups = np.array([f"S{i // 4}" for i in range(80)])
    for train_idx, test_idx in qwk_lab.make_folds(groups, folds=5, seed=42):
        assert not (set(groups[train_idx]) & set(groups[test_idx]))


# ── 신뢰구간·엇갈림 표 ───────────────────────────────────────────────────────

def test_부트스트랩_구간이_실제_QWK를_감싼다():
    rng = np.random.default_rng(11)
    truth = rng.integers(0, 6, size=150)
    # 정답에 잡음을 살짝 섞은 예측(완벽하지도, 무작위도 아닌 상태)
    pred = qwk_lab.to_grade(truth + rng.normal(0, 0.7, size=150))
    groups = np.array([f"S{i // 3}" for i in range(150)])
    point = qwk_lab.qwk(pred, truth)
    ci = qwk_lab.bootstrap_qwk_ci(pred, truth, groups, n_boot=200, seed=42)
    assert ci["lo"] <= point <= ci["hi"]
    assert ci["n_boot"] > 0


def test_엇갈림표의_합이_전체_건수와_같다():
    """한 건도 흘리지 않고 6×6 칸에 담기는지 — 표를 믿으려면 먼저 확인할 것."""
    pred = [0, 1, 2, 3, 4, 5, 5, 0]
    truth = [0, 2, 2, 3, 5, 5, 1, 0]
    m = qwk_lab.confusion_matrix_6x6(pred, truth)
    assert sum(sum(row) for row in m) == len(truth)
    assert m[0][0] == 2   # 0점을 0점으로 본 것이 2건


def test_evaluate_predictor가_순진법과_눈금맵을_둘_다_돌려준다():
    """보고서 표가 기대하는 칸이 실제로 채워지는지 본다(빈 칸이면 표가 거짓말을 한다)."""
    rng = np.random.default_rng(5)
    truth = rng.integers(0, 6, size=100)
    raw = truth * 20.0 + rng.normal(0, 5, size=100)
    groups = np.array([f"S{i // 2}" for i in range(100)])
    out = qwk_lab.evaluate_predictor("시험용", raw, truth, groups, n_boot=50)
    assert out["n"] == 100
    for block in ("naive", "calibrated"):
        assert set(out[block]) >= {"qwk", "qwk_ci95", "exact", "within1", "confusion"}
    # 순진법을 끄면 그 칸이 아예 생기지 않아야 한다(길이 기준선이 쓰는 길)
    out2 = qwk_lab.evaluate_predictor("길이", raw, truth, groups,
                                      naive_divisor=None, n_boot=50)
    assert "naive" not in out2
    assert "calibrated" in out2
