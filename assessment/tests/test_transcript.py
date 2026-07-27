"""STT 전사 보정 모듈 회귀 테스트.

여기서 가장 중요한 것은 **보정 구간 좌표**다.
좌표는 반드시 '원본 전사 기준'이어야 한다. 이것이 틀리면
채점 쪽에서 엉뚱한 오류 지적에 '신뢰도 낮음' 표시가 붙는다.
값이 나오는지가 아니라 '어느 자리를 가리키는지'까지 못 박아 둔다.

LLM은 부르지 않는다. 가짜 응답을 넣어 계산만 확인한다.

실행: .venv\\Scripts\\python.exe -m pytest tests -q
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.llm.transcript import (  # noqa: E402
    MAX_CHANGE_RATIO,
    build_correction,
    build_prompt,
    correct_transcript,
    diff_transcript,
)


class FakeClient:
    """키 없이 도는 가짜 Gemini 클라이언트.

    실제 클라이언트에서 이 모듈이 쓰는 것은 available 과 generate_json 뿐이라
    그 둘만 흉내 낸다. 어떤 프롬프트를 받았는지는 확인용으로 모아 둔다.
    """

    def __init__(self, payload: dict, fail: Exception | None = None):
        self.payload = payload
        self.fail = fail
        self.prompts: list[str] = []
        self.available = True
        self.model_name = "fake-model"

    def generate_json(self, prompt, system_instruction="", response_schema=None):
        self.prompts.append(prompt)
        if self.fail:
            raise self.fail
        return self.payload


# ---------------------------------------------------------------------------
# 좌표 계산 (이 모듈에서 제일 틀리기 쉬운 곳)
# ---------------------------------------------------------------------------


def test_바뀐_자리의_좌표가_원본_기준이다():
    original = "저는 어제 회사에 가습니다"
    corrected = "저는 어제 회사에 갔습니다"

    diffs, spans = diff_transcript(original, corrected)

    assert len(diffs) == 1
    d = diffs[0]
    # 좌표로 원본을 잘라내면 실제로 바뀐 글자가 나와야 한다
    assert original[d.start : d.end] == d.original
    assert d.original == "가" and d.corrected == "갔"
    assert spans == [(d.start, d.end)]


def test_삽입은_원본에서_폭이_0이라_앞뒤로_넓힌다():
    original = "안전모 착용했습니다"
    corrected = "안전모를 착용했습니다"

    diffs, spans = diff_transcript(original, corrected)

    assert len(diffs) == 1
    d = diffs[0]
    # 삽입이므로 원본에서는 지워지거나 바뀐 글자가 없다
    assert d.original == "" and d.corrected == "를"
    assert d.start == d.end
    # 겹침 판정에 쓸 구간은 그 자리 앞뒤로 한 글자씩 넓어져 있어야 한다
    assert spans and spans[0][0] < spans[0][1]
    assert spans[0][0] <= d.start <= spans[0][1]


def test_지워진_자리도_원본_좌표로_남는다():
    original = "저는 어어 갔습니다"
    corrected = "저는 갔습니다"

    diffs, spans = diff_transcript(original, corrected)

    assert diffs
    # 지워진 글자가 원본의 어느 자리에 있었는지 되짚을 수 있어야 한다
    joined = "".join(original[d.start : d.end] for d in diffs)
    assert "어" in joined


def test_띄어쓰기만_다른_것은_보정으로_세지_않는다():
    # STT가 정한 띄어쓰기는 응시자 잘못이 아니라서 말하기에서 채점하지 않는다.
    # 이것까지 보정 구간으로 잡으면 멀쩡한 오류 지적에 신뢰도 표시가 붙는다
    diffs, spans = diff_transcript("저는회사에 갔습니다", "저는 회사에 갔습니다")
    assert diffs == []
    assert spans == []


def test_붙어_있는_구간은_하나로_합쳐진다():
    original = "가나다라마바사"
    corrected = "가XY다라마바사"  # '나' 바로 옆이 연달아 바뀌는 경우

    _, spans = diff_transcript(original, corrected)
    # 겹치거나 맞닿은 구간이 여러 개로 쪼개져 남아 있으면 안 된다
    for (s1, e1), (s2, _) in zip(spans, spans[1:]):
        assert e1 < s2


def test_여러_군데_보정도_각각_제자리를_가리킨다():
    original = "저는 어제 회사에 가습니다 그리고 반장님한테 보고했습니다"
    corrected = "저는 어제 회사에 갔습니다 그리고 반장님한테 보고했습니다"

    diffs, _ = diff_transcript(original, corrected)
    for d in diffs:
        assert original[d.start : d.end] == d.original


# ---------------------------------------------------------------------------
# LLM 응답을 결과로 바꾸는 부분
# ---------------------------------------------------------------------------


def test_보정_결과에_diff와_근거가_함께_나온다():
    original = "저는 어제 회사에 가습니다"
    payload = {
        "corrected_text": "저는 어제 회사에 갔습니다",
        "changes": [
            {"original": "가습니다", "corrected": "갔습니다", "reason": "받침이 누락돼 들렸다"}
        ],
    }

    result = build_correction(original, payload, nationality="베트남")

    assert result.correction_applied is True
    assert result.change_count == 1
    # 사유가 원문 대조를 통과했으므로 근거에 붙어 있어야 한다
    assert "받침" in result.diffs[0].reason

    evidence = result.to_evidence()
    assert len(evidence) == 1
    ev = evidence[0]
    # 근거의 인용은 반드시 원문에 실제로 있는 글자여야 한다
    assert ev.quote and ev.quote in original
    assert original[ev.start : ev.end] == ev.quote
    assert ev.detail["coordinate_base"] == "original_transcript"


def test_원문에_없는_수정_사유는_폐기된다():
    original = "저는 어제 회사에 가습니다"
    payload = {
        "corrected_text": "저는 어제 회사에 갔습니다",
        # 원문에 '공장에 갔어요' 라는 말은 없다. 지어낸 설명이다
        "changes": [
            {"original": "공장에 갔어요", "corrected": "공장에 갔습니다", "reason": "지어낸 설명"}
        ],
    }

    result = build_correction(original, payload)

    # 보정 자체는 살아 있되(글자 대조는 코드가 직접 했다) 지어낸 설명은 버려진다
    assert result.correction_applied is True
    assert result.dropped_citations == 1
    assert result.diffs[0].reason == ""
    assert any("폐기" in w for w in result.warnings)


def test_과보정은_통째로_물린다():
    # 응시자가 실제로 틀린 문법까지 고쳐 오면 점수가 부풀려진다.
    # 원문을 다시 써 온 응답은 받아들이지 않는다
    original = "기계 고장 났어요 그래서 반장 불렀어요"
    payload = {
        "corrected_text": (
            "기계가 고장 나서 즉시 전원을 차단하고 반장님께 보고드렸습니다"
        ),
        "changes": [],
    }

    result = build_correction(original, payload)

    assert result.correction_applied is False
    assert result.corrected_text == original      # 원문 그대로 채점한다
    assert result.corrected_spans == []
    assert any("과보정" in w for w in result.warnings)
    assert any(f"{MAX_CHANGE_RATIO:.0%}" in w for w in result.warnings)


def test_고칠_곳이_없으면_보정하지_않은_것으로_본다():
    original = "저는 어제 회사에 갔습니다"
    result = build_correction(original, {"corrected_text": original, "changes": []})

    assert result.correction_applied is False
    assert result.corrected_spans == []


def test_보정본이_비어_있으면_원문을_쓴다():
    # 빈 값을 그대로 받으면 내용 채점이 '아무 말도 안 한 답안'을 보게 된다
    original = "저는 어제 회사에 갔습니다"
    result = build_correction(original, {"corrected_text": "   "})

    assert result.correction_applied is False
    assert result.corrected_text == original
    assert result.warnings


# ---------------------------------------------------------------------------
# LLM을 못 쓰는 상황
# ---------------------------------------------------------------------------


def test_LLM을_끄면_예외_없이_원문이_나온다():
    original = "저는 어제 회사에 가습니다"
    result = correct_transcript(original, use_llm=False)

    assert result.correction_applied is False
    assert result.corrected_text == original
    assert result.llm_used is False
    assert result.warnings


def test_호출이_실패해도_예외를_던지지_않는다():
    from src.llm.client import LLMUnavailable

    original = "저는 어제 회사에 가습니다"
    client = FakeClient(payload={}, fail=LLMUnavailable("네트워크 끊김"))

    result = correct_transcript(original, client=client)

    assert result.correction_applied is False
    assert result.corrected_text == original
    assert any("네트워크 끊김" in w for w in result.warnings)


def test_빈_답안은_호출하지_않는다():
    client = FakeClient(payload={"corrected_text": "무엇이든"})
    result = correct_transcript("   ", client=client)

    assert client.prompts == []          # 호출 자체를 하지 않아야 한다
    assert result.correction_applied is False


def test_가짜_클라이언트로_전체_경로가_돈다():
    original = "저는 어제 회사에 가습니다"
    client = FakeClient(
        payload={
            "corrected_text": "저는 어제 회사에 갔습니다",
            "changes": [{"original": "가습니다", "corrected": "갔습니다", "reason": "전사 오류"}],
        }
    )

    result = correct_transcript(original, nationality="네팔", client=client)

    assert result.correction_applied is True
    assert result.llm_used is True
    # 국적이 프롬프트에 실제로 들어갔는지 확인한다
    assert "네팔" in client.prompts[0]


# ---------------------------------------------------------------------------
# 프롬프트
# ---------------------------------------------------------------------------


def test_국적이_없어도_프롬프트가_만들어진다():
    prompt = build_prompt("저는 갔습니다", nationality=None)
    assert "알 수 없음" in prompt
    assert "저는 갔습니다" in prompt


def test_프롬프트가_과보정을_막는_지시를_담는다():
    from src.llm.transcript import SYSTEM_INSTRUCTION

    # 이 지시가 빠지면 응시자의 실제 문법 오류까지 고쳐져 점수가 부풀려진다
    assert "고치지 않는다" in SYSTEM_INSTRUCTION
    assert "조사" in SYSTEM_INSTRUCTION
