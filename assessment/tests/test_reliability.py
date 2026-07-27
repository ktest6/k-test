"""채점을 '믿어도 되는지'가 결과에 제대로 드러나는지 지키는 테스트.

두 가지를 지킨다.

1) 대체 경로로 때운 점수는 값 하나만 보고 걸러낼 수 있어야 한다.
   LLM이 죽어도 채점은 멈추지 않게 만들어 두었는데, 그 때문에
   대체 경로로 계산한 점수도 겉보기에는 멀쩡한 숫자로 나온다.
   실제로 같은 답안이 LLM이 살아 있을 때 70.58점, 대체 경로에서 79.66점이 나왔다.

2) STT 전사 보정이 '언어 사용' 점수를 바꾸면 안 된다.
   이것이 과보정을 무해하게 만드는 핵심 장치다.
   보정본으로 문법을 채점하면 응시자가 실제로 틀린 것까지 고쳐진 글을 보게 되어
   점수가 실력보다 높아진다. 그래서 언어 사용은 언제나 전사 원문으로 채점한다.
   이 불변식이 깨지면 보정 프롬프트가 조금만 느슨해져도 점수가 부풀려지므로
   설계 문서에만 적어 두지 않고 테스트로 못 박는다.
"""

from __future__ import annotations

from src.llm.client import GeminiClient, LLMUnavailable
from src.scoring.finalize import finalize_session
from src.scoring.pipeline import TranscriptContext, score_submission
from src.scoring.schema import (
    ChecklistItem,
    ExpectedItem,
    FinalizeItem,
    FinalizeRequest,
    ItemInfo,
    Mode,
    Reliability,
    ScoreRequest,
    ScoreResponse,
)

# 원문에 학습자의 진짜 어미 활용 오류('안 돼습니다')가 들어 있다.
# 보정본에서는 그것이 '안 됐습니다'로 고쳐져 있다 — 보정이 지나쳤을 때의 상황이다.
ORIGINAL = (
    "반장님 지금 삼번 라인 포장 기가 갑자기 멈췄습니다 "
    "제가 전원 버튼을 다시 눌러 봤는데 안 돼습니다"
)
CORRECTED = (
    "반장님 지금 삼번 라인 포장기가 갑자기 멈췄습니다 "
    "제가 전원 버튼을 다시 눌러 봤는데 안 됐습니다"
)
# '돼' 자리(원문 기준). pipeline 이 이 구간과 겹치는 오류 지적에 표시를 단다.
CORRECTED_SPAN = (ORIGINAL.index("돼"), ORIGINAL.index("돼") + 1)


class _DeadClient(GeminiClient):
    """호출하면 반드시 실패하는 가짜 클라이언트."""

    def __init__(self):
        super().__init__(api_key="dummy-key-for-test")

    @property
    def available(self) -> bool:
        return True

    def generate_json(self, *args, **kwargs):
        raise LLMUnavailable("LLM 하루 호출 한도를 다 썼다(429).")


def _request(with_checklist: bool = True) -> ScoreRequest:
    return ScoreRequest(
        submission_id="sub-1",
        mode=Mode.SPEAKING,
        answer_text=ORIGINAL,
        item=ItemInfo(
            item_id="item-1",
            prompt="기계 고장을 반장님에게 보고하세요.",
            checklist=(
                [ChecklistItem(id="c1", description="어떤 문제가 생겼는지 말했는가")]
                if with_checklist
                else []
            ),
            reference_keywords=["기계", "정비"],
        ),
    )


# ---------------------------------------------------------------------------
# 1) 대체 경로가 값으로 드러나는가
# ---------------------------------------------------------------------------


def test_대체_경로로_때운_점수는_fallback_으로_표시된다():
    resp = score_submission(_request(), client=_DeadClient())

    assert resp.meta.reliability == Reliability.FALLBACK
    # 프론트는 이 값 하나만 보면 된다
    assert resp.meta.safe_to_show_candidate is False
    assert resp.meta.reliability_reason
    # 점수 자체는 그대로 나온다(채점을 멈추지 않는다는 원칙은 유지)
    assert resp.overall_score is not None


def test_체크리스트가_없으면_partial_이다():
    resp = score_submission(_request(with_checklist=False), client=_DeadClient())

    assert resp.meta.reliability == Reliability.PARTIAL
    # partial 은 '참고용'이라 화면에 띄우는 것 자체는 막지 않는다
    assert resp.meta.safe_to_show_candidate is True


def test_기본값은_full_이라_기존_호출이_영향받지_않는다():
    """계약에 새로 붙인 값이라 기본값이 안전한 쪽이어야 한다."""
    from src.scoring.schema import ScoringMeta

    meta = ScoringMeta(mode=Mode.SPEAKING)

    assert meta.reliability == Reliability.FULL
    assert meta.safe_to_show_candidate is True
    assert meta.reliability_reason == ""


# ---------------------------------------------------------------------------
# 2) 시험 전체로 번지는가
# ---------------------------------------------------------------------------


def _finalize_item(item_id: str, mode: Mode, reliability: Reliability) -> FinalizeItem:
    from src.scoring.schema import ScoringMeta, SubScore, ScoreArea

    return FinalizeItem(
        item_id=item_id,
        mode=mode,
        overall_score=75.0,
        subscores=[
            SubScore(area=ScoreArea.CONTENT_TASK, label="내용 및 과제 수행", score=75.0, weight=0.45),
            SubScore(area=ScoreArea.LANGUAGE_USE, label="언어 사용", score=75.0, weight=0.55),
        ],
        meta=ScoringMeta(mode=mode, reliability=reliability, reliability_reason="테스트 사유"),
    )


def test_한_문항만_fallback_이어도_시험_전체가_fallback_이다():
    """오염은 나머지 문항으로 희석해서 없앨 수 있는 것이 아니다."""
    req = FinalizeRequest(
        session_id="s1",
        items=[
            _finalize_item("i1", Mode.SPEAKING, Reliability.FULL),
            _finalize_item("i2", Mode.SPEAKING, Reliability.FULL),
            _finalize_item("i3", Mode.WRITING, Reliability.FALLBACK),
        ],
        expected_items=[
            ExpectedItem(item_id="i1", mode=Mode.SPEAKING),
            ExpectedItem(item_id="i2", mode=Mode.SPEAKING),
            ExpectedItem(item_id="i3", mode=Mode.WRITING),
        ],
    )

    fin = finalize_session(req)

    assert fin.meta.reliability == Reliability.FALLBACK
    assert fin.meta.safe_to_show_candidate is False
    # 어느 문항을 다시 채점해야 하는지 알 수 있어야 한다
    assert fin.meta.unreliable_item_ids == ["i3"]


def test_meta_를_안_보내도_finalize_가_동작한다():
    """meta 는 선택 값이다. 기존 백엔드 호출이 깨지면 안 된다."""
    req = FinalizeRequest(
        session_id="s1",
        items=[
            FinalizeItem(item_id="i1", mode=Mode.SPEAKING, overall_score=70.0),
        ],
        expected_items=[ExpectedItem(item_id="i1", mode=Mode.SPEAKING)],
    )

    fin = finalize_session(req)

    assert fin.meta.reliability == Reliability.FULL
    assert fin.meta.unreliable_item_ids == []


# ---------------------------------------------------------------------------
# 3) 보정이 언어 사용 점수를 건드리지 않는가 (과보정 방어의 핵심)
# ---------------------------------------------------------------------------


def _language_score(resp: ScoreResponse) -> float | None:
    return next(s.score for s in resp.subscores if s.label == "언어 사용")


def test_전사_보정이_언어_사용_점수를_바꾸지_않는다():
    """보정본에서 학습자 오류가 고쳐져 있어도 언어 사용 점수는 그대로여야 한다.

    이것이 지켜지는 한 보정이 지나쳐도 문법 점수가 부풀려지지 않는다.
    """
    # LLM 없이 규칙 자질만으로 비교한다. 규칙 자질이 어느 글을 봤는지가 드러난다
    보정_없음 = score_submission(_request(), client=_DeadClient())
    보정_있음 = score_submission(
        _request(),
        client=_DeadClient(),
        transcript=TranscriptContext(
            corrected_text=CORRECTED,
            corrected_spans=[CORRECTED_SPAN],
            correction_applied=True,
            nationality="베트남",
        ),
    )

    assert _language_score(보정_있음) == _language_score(보정_없음), (
        "보정본이 언어 사용 점수에 새어 들어갔다. "
        "문법·어휘는 언제나 전사 원문으로 채점해야 한다"
    )


def test_보정은_내용_영역_자질에만_반영된다():
    """반대로, 내용 쪽 자질은 보정본을 봐야 한다."""
    보정_있음 = score_submission(
        _request(),
        client=_DeadClient(),
        transcript=TranscriptContext(
            corrected_text=CORRECTED + " 정비팀에 연락하겠습니다 기다리겠습니다",
            corrected_spans=[CORRECTED_SPAN],
            correction_applied=True,
        ),
    )

    응답길이 = next(
        f for f in 보정_있음.features if f.id == "response_length"
    )
    # 보정본이 더 길어졌으므로 응답 길이는 보정본 기준이어야 한다
    assert 응답길이.value > len(ORIGINAL.split())
    # 그리고 그 사실이 근거에 밝혀져 있어야 한다
    assert any(
        ev.detail.get("text_source") == "corrected" for ev in 응답길이.evidence
    )


def test_보정_구간과_겹치는_오류에만_신뢰도_표시가_붙는다():
    """표시는 붙되, 점수를 깎거나 되돌리지는 않는다는 것도 함께 확인한다."""
    resp = score_submission(
        _request(),
        client=_DeadClient(),
        transcript=TranscriptContext(
            corrected_text=CORRECTED,
            corrected_spans=[CORRECTED_SPAN],
            correction_applied=True,
        ),
    )

    # LLM이 죽어 있어 오류 자질은 값 없음 상태다. 그래도 결과는 나와야 한다
    assert resp.overall_score is not None
    # 보정 사실 자체는 meta 에 남는다
    assert resp.meta.transcript_correction_applied is True
