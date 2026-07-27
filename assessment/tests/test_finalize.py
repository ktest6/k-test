"""시험 전체 최종 등급(/finalize)과 서버 예열 회귀 테스트.

여기서 지키려는 것:
- 마지막 문항이 아직 채점 중이어도 결과가 나와야 한다(응시자가 결과를 못 받으면 안 된다)
- 채점된 문항이 너무 적으면 등급을 확정하지 않아야 한다(부족한 결과에 등급을 붙이면 그대로 통보된다)
- 말하기·쓰기 급차이는 '신호'로만 남아야 한다(부정행위 판정은 우리 파트가 아니다)

실행: .venv\\Scripts\\python.exe -m pytest tests -q
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from src.api import app  # noqa: E402
from src.scoring.finalize import finalize_session, to_percentile  # noqa: E402
from src.scoring.schema import (  # noqa: E402
    AreaStatus,
    ExpectedItem,
    FinalizeItem,
    FinalizeOptions,
    FinalizeRequest,
    FinalizeStatus,
    ItemScoreStatus,
    Mode,
    ScoreArea,
    SubScore,
)

EXPECTED = [
    ExpectedItem(item_id="s1", mode=Mode.SPEAKING),
    ExpectedItem(item_id="s2", mode=Mode.SPEAKING),
    ExpectedItem(item_id="s3", mode=Mode.SPEAKING),
    ExpectedItem(item_id="w1", mode=Mode.WRITING),
    ExpectedItem(item_id="w2", mode=Mode.WRITING),
]


def item(item_id: str, mode: Mode, content: float, language: float, **kwargs) -> FinalizeItem:
    """문항 하나의 채점 결과를 흉내 낸다."""
    return FinalizeItem(
        item_id=item_id,
        mode=mode,
        overall_score=round(content * 0.45 + language * 0.55, 2),
        subscores=[
            SubScore(area=ScoreArea.CONTENT_TASK, label="내용 및 과제 수행",
                     score=content, weight=0.45, status=AreaStatus.SCORED),
            SubScore(area=ScoreArea.LANGUAGE_USE, label="언어 사용",
                     score=language, weight=0.55, status=AreaStatus.SCORED),
            SubScore(area=ScoreArea.DELIVERY, label="발화 전달력",
                     score=None, weight=0.0, status=AreaStatus.NOT_EVALUATED),
        ],
        **kwargs,
    )


ALL_ITEMS = [
    item("s1", Mode.SPEAKING, 82, 78),
    item("s2", Mode.SPEAKING, 76, 80),
    item("s3", Mode.SPEAKING, 88, 74),
    item("w1", Mode.WRITING, 79, 83),
    item("w2", Mode.WRITING, 85, 77),
]


def test_전_문항_채점시_등급과_백분위가_나온다():
    r = finalize_session(
        FinalizeRequest(session_id="s", items=ALL_ITEMS, expected_items=EXPECTED)
    )
    assert r.status == FinalizeStatus.COMPLETE
    assert r.overall_score is not None
    assert r.overall_grade is not None
    assert r.percentile is not None


def test_최종_점수에도_근거가_붙는다():
    """점수만 돌려주면 이 프로젝트에서는 결함이다. 문항별 기여 내역이 있어야 한다."""
    r = finalize_session(
        FinalizeRequest(session_id="s", items=ALL_ITEMS, expected_items=EXPECTED)
    )
    for s in r.subscores:
        if s.score is None:
            continue
        assert s.contributions, f"{s.area} 에 기여 내역이 없다"
        # 기여 내역의 비중 합은 항상 1이어야 한다
        assert abs(sum(c.weight for c in s.contributions) - 1.0) < 1e-6


def test_채점중인_문항이_있어도_결과가_나오고_재정규화된다():
    items = ALL_ITEMS[:4] + [
        item("w2", Mode.WRITING, 0, 0, status=ItemScoreStatus.PENDING)
    ]
    r = finalize_session(
        FinalizeRequest(session_id="s", items=items, expected_items=EXPECTED)
    )
    assert r.status == FinalizeStatus.PARTIAL
    assert r.overall_grade is not None
    assert "w2" in r.item_coverage.pending_item_ids
    assert any("채점이 끝나지 않은 문항" in w for w in r.warnings)
    # 빠진 문항을 뺀 4개로 비중이 다시 나뉘어야 한다
    content = next(s for s in r.subscores if s.area == ScoreArea.CONTENT_TASK)
    assert len(content.contributions) == 4
    assert all(abs(c.weight - 0.25) < 1e-6 for c in content.contributions)


def test_결과가_안_넘어온_문항도_기록에_남는다():
    r = finalize_session(
        FinalizeRequest(session_id="s", items=ALL_ITEMS[:4], expected_items=EXPECTED)
    )
    assert r.item_coverage.missing_item_ids == ["w2"]
    assert any("결과가 넘어오지 않은" in w for w in r.warnings)


def test_채점_문항이_부족하면_등급을_확정하지_않는다():
    r = finalize_session(
        FinalizeRequest(session_id="s", items=ALL_ITEMS[:2], expected_items=EXPECTED)
    )
    assert r.status == FinalizeStatus.INSUFFICIENT
    # 부족한 결과에 등급을 붙이면 그대로 통보되므로 아예 비워 둔다
    assert r.overall_grade is None
    assert r.overall_score is None
    assert r.percentile is None
    # 어떤 기준으로 부족하다고 봤는지도 함께 알려야 한다
    assert r.item_coverage.min_scored_ratio == 0.7
    assert r.item_coverage.min_scored_items == 3


def test_유효_기준은_주입할_수_있다():
    # 기준을 낮추면 같은 자료로도 등급이 나온다
    r = finalize_session(
        FinalizeRequest(
            session_id="s", items=ALL_ITEMS[:2], expected_items=EXPECTED,
            options=FinalizeOptions(min_scored_ratio=0.3, min_scored_items=2),
        )
    )
    assert r.status == FinalizeStatus.PARTIAL
    assert r.overall_grade is not None


def test_문항이_적은_짧은_시험도_통과한다():
    """원래 문항 수가 기준보다 적으면 개수 기준을 그대로 들이대면 안 된다."""
    short = [ExpectedItem(item_id="s1", mode=Mode.SPEAKING),
             ExpectedItem(item_id="s2", mode=Mode.SPEAKING)]
    r = finalize_session(
        FinalizeRequest(session_id="s", items=ALL_ITEMS[:2], expected_items=short)
    )
    assert r.status == FinalizeStatus.COMPLETE
    assert r.overall_grade is not None


def test_말하기_쓰기_급차이가_크면_신호가_뜬다():
    items = [
        item("s1", Mode.SPEAKING, 95, 93),
        item("s2", Mode.SPEAKING, 92, 96),
        item("s3", Mode.SPEAKING, 94, 90),
        item("w1", Mode.WRITING, 22, 18),
        item("w2", Mode.WRITING, 25, 20),
    ]
    r = finalize_session(
        FinalizeRequest(session_id="s", items=items, expected_items=EXPECTED)
    )
    check = r.cross_mode_check
    assert check.comparable is True
    assert check.speaking_grade == "A"
    assert check.writing_grade == "E"
    assert check.grade_gap == 4
    assert check.flagged is True
    # 신호일 뿐 판정이 아니라는 것을 반드시 문구로 남긴다
    assert "판정이 아니다" in check.note


def test_급차이가_작으면_신호가_안_뜬다():
    r = finalize_session(
        FinalizeRequest(session_id="s", items=ALL_ITEMS, expected_items=EXPECTED)
    )
    assert r.cross_mode_check.flagged is False


def test_교차검증_임계값을_주입할_수_있다():
    items = [
        item("s1", Mode.SPEAKING, 95, 93),
        item("s2", Mode.SPEAKING, 92, 96),
        item("s3", Mode.SPEAKING, 94, 90),
        item("w1", Mode.WRITING, 70, 68),
        item("w2", Mode.WRITING, 72, 70),
    ]
    loose = finalize_session(FinalizeRequest(
        session_id="s", items=items, expected_items=EXPECTED,
        options=FinalizeOptions(cross_mode_gap_threshold=3)))
    strict = finalize_session(FinalizeRequest(
        session_id="s", items=items, expected_items=EXPECTED,
        options=FinalizeOptions(cross_mode_gap_threshold=1)))
    assert loose.cross_mode_check.flagged is False
    assert strict.cross_mode_check.flagged is True


def test_한쪽_모드만_있으면_교차검증을_하지_않는다():
    r = finalize_session(
        FinalizeRequest(
            session_id="s", items=ALL_ITEMS[:3],
            expected_items=EXPECTED[:3],
        )
    )
    assert r.cross_mode_check.comparable is False
    assert r.cross_mode_check.flagged is False


def test_문항_가중치가_반영된다():
    r = finalize_session(
        FinalizeRequest(
            session_id="s",
            items=[
                item("s1", Mode.SPEAKING, 90, 90, item_weight=3.0),
                item("s2", Mode.SPEAKING, 40, 40, item_weight=1.0),
            ],
            expected_items=[
                ExpectedItem(item_id="s1", mode=Mode.SPEAKING, weight=3.0),
                ExpectedItem(item_id="s2", mode=Mode.SPEAKING, weight=1.0),
            ],
            options=FinalizeOptions(min_scored_items=2),
        )
    )
    # 3:1 이면 (90*3 + 40*1) / 4 = 77.5
    assert abs(r.overall_score - 77.5) < 0.01


def test_임시값_표시가_항상_실린다():
    r = finalize_session(
        FinalizeRequest(session_id="s", items=ALL_ITEMS, expected_items=EXPECTED)
    )
    assert r.meta.weights_provisional is True
    assert r.meta.cutoffs_from_anchor_answers is False
    assert r.meta.percentile_provisional is True
    assert any("임시" in w for w in r.warnings)


def test_백분위는_점수가_오르면_같이_오른다():
    assert to_percentile(0) <= to_percentile(40) < to_percentile(65)
    assert to_percentile(65) < to_percentile(90) <= to_percentile(100)
    # 표 범위를 벗어나도 0~100 안에 머물러야 한다
    assert to_percentile(-10) == 0.0
    assert to_percentile(150) == 100.0


def test_문항이_하나도_없어도_터지지_않는다():
    r = finalize_session(FinalizeRequest(session_id="s", items=[]))
    assert r.status == FinalizeStatus.INSUFFICIENT
    assert r.overall_grade is None


def test_score_응답을_그대로_넣어도_파싱된다():
    """백엔드가 /score 응답을 손대지 않고 그대로 모아 보낼 수 있어야 한다."""
    with TestClient(app) as client:
        scored = client.post("/score", json={
            "submission_id": "sub-1",
            "mode": "speaking",
            "answer_text": "기계가 멈춰서 전원을 차단하고 반장님께 보고드렸습니다.",
            "item": {"item_id": "s1", "prompt": "상황을 설명하십시오.",
                     "checklist": [{"id": "c1", "description": "상황을 설명했는가"}]},
        }).json()

        # /score 응답 전체를 그대로 items 에 넣는다(모르는 필드는 무시된다)
        r = client.post("/finalize", json={
            "session_id": "sess-1",
            "items": [scored],
            "options": {"min_scored_items": 1, "min_scored_ratio": 1.0},
        })
    assert r.status_code == 200
    body = r.json()
    assert body["overall_grade"] is not None
    assert body["meta"]["weights_provisional"] is True


def test_예열이_기동시에_걸린다():
    """예열이 안 걸리면 그날 첫 응시자만 2초 넘게 기다리게 된다."""
    with TestClient(app) as client:
        health = client.get("/health").json()
    assert health["warmed_up"] is True
    assert health["warmup_ms"] is not None
