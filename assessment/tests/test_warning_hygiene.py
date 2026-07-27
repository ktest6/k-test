"""채점 결과에 실리는 경고 문구가 짧고 읽을 만한지 지키는 회귀 테스트.

왜 이걸 테스트로 고정하는가:
`warnings` 와 `subscores[].note` 는 schema.py 에 적힌 백엔드와의 계약 필드이고,
프론트가 응시자에게 그대로 보여줄 수 있는 자리다.
예전에는 Gemini가 429를 내면 서버가 준 JSON 응답이 통째로 이 자리에 들어갔고,
같은 덩어리가 자질 개수만큼 복사돼서 한 문항 경고가 4,000자를 넘었다.

사람이 눈으로 확인하는 것만으로는 이런 것이 조용히 되돌아온다.
그래서 '글자 수'라는 기계가 셀 수 있는 기준으로 못 박아 둔다.
"""

from __future__ import annotations

import pytest

from src.llm.client import GeminiClient, LLMUnavailable, classify_failure
from src.scoring.pipeline import score_submission
from src.scoring.schema import (
    ChecklistItem,
    ItemInfo,
    Mode,
    ScoreRequest,
    TranscriptInput,
)

# 실제로 받았던 429 응답을 줄여서 옮겨 둔 것. 진짜 응답은 이보다 더 길다.
REAL_429_BODY = (
    "429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': 'You exceeded your "
    "current quota, please check your plan and billing details. For more information "
    "on this error, head to: https://ai.google.dev/gemini-api/docs/rate-limits.', "
    "'status': 'RESOURCE_EXHAUSTED', 'details': [{'@type': "
    "'type.googleapis.com/google.rpc.QuotaFailure', 'violations': [{'quotaMetric': "
    "'generativelanguage.googleapis.com/generate_content_free_tier_requests', "
    "'quotaId': 'GenerateRequestsPerDayPerProjectPerModel-FreeTier', "
    "'quotaDimensions': {'location': 'global', 'model': 'gemini-3.5-flash'}, "
    "'quotaValue': '20'}]}]}}"
)

REAL_404_BODY = (
    "404 NOT_FOUND. {'error': {'code': 404, 'message': 'This model "
    "models/gemini-2.5-flash-lite is no longer available to new users.', "
    "'status': 'NOT_FOUND'}}"
)

# 한 문장이 이보다 길어지면 사람이 읽는 문구가 아니라 진단 덤프로 봐야 한다.
MAX_WARNING_CHARS = 300


class _FailingClient(GeminiClient):
    """키는 있는 척하면서 호출하면 반드시 실패하는 가짜 클라이언트.

    네트워크 없이 '호출은 됐는데 서버가 거절한' 상황을 재현한다.
    """

    def __init__(self, body: str):
        super().__init__(api_key="dummy-key-for-test")
        self._body = body

    @property
    def available(self) -> bool:
        return True

    def generate_json(self, *args, **kwargs):
        # 진짜 client 가 하는 것과 똑같이 분류해서 던진다
        raise LLMUnavailable(classify_failure(Exception(self._body)), detail=self._body)


def _sample_request() -> ScoreRequest:
    return ScoreRequest(
        submission_id="sub-1",
        mode=Mode.SPEAKING,
        answer_text=(
            "반장님 지금 삼번 라인 포장 기가 갑자기 멈췄습니다 "
            "제가 전원을 차단하구 정비팀에 연락할까요"
        ),
        item=ItemInfo(
            item_id="item-1",
            prompt="기계 고장을 반장님에게 보고하세요.",
            checklist=[
                ChecklistItem(id="c1", description="어떤 문제가 생겼는지 말했는가"),
                ChecklistItem(id="c2", description="지시를 요청했는가"),
            ],
            reference_keywords=["기계", "정비"],
        ),
        transcript=TranscriptInput(correct=True, nationality="베트남"),
    )


# ---------------------------------------------------------------------------
# 실패 원인 분류
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "body, expected_marker",
    [
        (REAL_429_BODY, "429"),
        (REAL_404_BODY, "404"),
        ("403 PERMISSION_DENIED: API key not valid", "403"),
        ("DEADLINE_EXCEEDED: request timed out", "제한 시간"),
        ("503 UNAVAILABLE: server overloaded", "일시적"),
    ],
)
def test_실패_원인이_짧은_한_문장으로_분류된다(body, expected_marker):
    reason = classify_failure(Exception(body))

    assert expected_marker in reason
    # 서버 응답 원문이 그대로 새어 나오면 안 된다
    assert "quotaMetric" not in reason
    assert "@type" not in reason
    assert len(reason) <= 120


def test_분류되지_않는_오류도_원문을_흘리지_않는다():
    reason = classify_failure(ValueError("무언가 " + "x" * 5000))

    assert "xxxx" not in reason
    assert len(reason) <= 120


# ---------------------------------------------------------------------------
# 계약 필드 오염
# ---------------------------------------------------------------------------


def test_429일_때_경고에_서버_응답_원문이_실리지_않는다():
    resp = score_submission(_sample_request(), client=_FailingClient(REAL_429_BODY))

    joined = " ".join(resp.warnings) + " ".join(s.note for s in resp.subscores)

    # 서버 JSON 을 알아볼 수 있는 표시들이 하나도 없어야 한다
    for leak in ("quotaMetric", "quotaValue", "@type", "generativelanguage", "'status':"):
        assert leak not in joined, f"경고에 서버 응답 원문이 새어 나왔다: {leak}"


def test_경고와_note_가_사람이_읽을_길이를_넘지_않는다():
    resp = score_submission(_sample_request(), client=_FailingClient(REAL_429_BODY))

    for w in resp.warnings:
        assert len(w) <= MAX_WARNING_CHARS, f"경고가 너무 길다({len(w)}자): {w[:120]}"

    for s in resp.subscores:
        assert len(s.note) <= MAX_WARNING_CHARS, (
            f"'{s.label}' note 가 너무 길다({len(s.note)}자)"
        )


def test_같은_사유가_자질_개수만큼_반복되지_않는다():
    """LLM 한 번 실패로 자질 네 개가 빠져도 사유는 한 번만 적혀야 한다."""
    resp = score_submission(_sample_request(), client=_FailingClient(REAL_429_BODY))

    language = next(s for s in resp.subscores if s.label == "언어 사용")

    # 사유 문구가 두 번 이상 등장하면 자질마다 복사되고 있다는 뜻이다
    assert language.note.count("한도를 다 썼다") <= 1

    # 대신 어떤 자질들이 빠졌는지는 그대로 알 수 있어야 한다
    for fid in ("error_josa", "error_conjugation", "error_word_choice", "error_honorific"):
        assert fid in language.note


def test_실패해도_점수는_나오고_상태로_드러난다():
    """경고를 짧게 만드는 과정에서 '반쪽 채점' 표시가 사라지면 안 된다."""
    resp = score_submission(_sample_request(), client=_FailingClient(REAL_429_BODY))

    assert resp.overall_score is not None
    assert resp.meta.llm_used is False
    # 어느 영역이 온전하지 않은지는 status 로 여전히 구별된다
    language = next(s for s in resp.subscores if s.label == "언어 사용")
    assert language.status.value == "partial"


def test_진단_정보는_예외의_detail_에_남는다():
    """짧게 만들되 원인 추적을 못 하게 만들지는 않았는지 확인한다."""
    exc = LLMUnavailable(classify_failure(Exception(REAL_429_BODY)), detail=REAL_429_BODY)

    assert "quotaMetric" not in str(exc)      # 결과에 실리는 쪽은 깨끗하고
    assert "quotaMetric" in exc.detail        # 개발자가 볼 쪽에는 남아 있다
