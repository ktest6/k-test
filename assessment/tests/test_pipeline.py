"""채점 파이프라인의 STT 전사 경로 회귀 테스트.

여기서 지키려는 규칙은 하나다.
**보정본은 '무슨 말을 했는가'에만 쓰고, 문법·어휘는 언제나 전사 원문으로 채점한다.**
이 경계가 무너지면 응시자가 실제로 틀린 문법이 보정으로 지워져 점수가 부풀려진다.

LLM은 부르지 않는다. 가짜 클라이언트가 정해진 답을 돌려준다.
(실제 키가 .env 에 있어도 네트워크로 나가지 않게 항상 가짜를 넘긴다)

실행: .venv\\Scripts\\python.exe -m pytest tests -q
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.features.checklist import SYSTEM_INSTRUCTION as CHECKLIST_SYSTEM  # noqa: E402
from src.features.errors import SYSTEM_INSTRUCTION as ERRORS_SYSTEM  # noqa: E402
from src.llm.transcript import SYSTEM_INSTRUCTION as TRANSCRIPT_SYSTEM  # noqa: E402
from src.scoring.pipeline import TranscriptContext, score_submission  # noqa: E402
from src.scoring.schema import (  # noqa: E402
    ChecklistItem,
    ItemInfo,
    Mode,
    ScoreOptions,
    ScoreRequest,
    TranscriptInput,
)

# STT가 '기계가'를 '기가'로 잘못 받아쓴 상황을 가정한 답안이다.
ORIGINAL = "어제 포장 기가 멈췄습니다. 그래서 반장님한테 보고했습니다."
CORRECTED = "어제 포장 기계가 멈췄습니다. 그래서 반장님한테 보고했습니다."


class FakeClient:
    """세 가지 LLM 호출을 지시문으로 구별해 정해진 답을 돌려주는 가짜 클라이언트.

    실제 클라이언트에서 파이프라인이 쓰는 것은 available·model_name·generate_json 뿐이다.
    어떤 글을 보고 판단했는지 확인해야 하므로 받은 프롬프트를 종류별로 모아 둔다.
    """

    def __init__(self, available: bool = True, correct: bool = True):
        self.available = available
        self.model_name = "fake-model"
        self.correct = correct
        self.prompts: dict[str, list[str]] = {"transcript": [], "errors": [], "checklist": []}

    def generate_json(self, prompt, system_instruction="", response_schema=None):
        # 전사 보정 호출
        if system_instruction == TRANSCRIPT_SYSTEM:
            self.prompts["transcript"].append(prompt)
            if not self.correct:
                return {"corrected_text": ORIGINAL, "changes": []}
            return {
                "corrected_text": CORRECTED,
                "changes": [
                    {
                        "original": "기가",
                        "corrected": "기계가",
                        "reason": "'기계가'가 '기가'로 짧게 받아써졌다",
                    }
                ],
            }

        # 오류 자질 추출 호출. 인용은 반드시 전사 원문에 있는 글자여야 한다
        if system_instruction == ERRORS_SYSTEM:
            self.prompts["errors"].append(prompt)
            return {
                "errors": [
                    {
                        "type": "josa",
                        "quote": "기가 멈췄습니다",       # 보정이 일어난 자리와 겹친다
                        "correction": "기계가 멈췄습니다",
                        "explanation": "주어 표시가 어색하다",
                    },
                    {
                        "type": "josa",
                        "quote": "반장님한테",            # 보정과 상관없는 자리다
                        "correction": "반장님께",
                        "explanation": "높임 대상에는 '께'를 쓴다",
                    },
                ]
            }

        # 체크리스트 판정 호출
        self.prompts["checklist"].append(prompt)
        return {
            "results": [
                {"id": "c1", "met": 1, "quote": "멈췄습니다", "reason": "고장 사실을 말했다"},
                {"id": "c2", "met": 1, "quote": "보고했습니다", "reason": "보고 사실을 말했다"},
            ]
        }


def make_request(
    mode: Mode = Mode.SPEAKING,
    transcript: TranscriptInput | None = None,
    use_llm: bool = True,
) -> ScoreRequest:
    """테스트용 채점 요청 하나를 만든다."""
    return ScoreRequest(
        submission_id="sub-001",
        mode=mode,
        answer_text=ORIGINAL,
        item=ItemInfo(
            item_id="item-001",
            prompt="작업 중 생긴 문제와 그 조치를 설명하시오.",
            checklist=[
                ChecklistItem(id="c1", description="문제 상황을 설명했는가"),
                ChecklistItem(id="c2", description="보고 여부를 밝혔는가"),
            ],
        ),
        options=ScoreOptions(use_llm=use_llm),
        transcript=transcript,
    )


def feature_map(response) -> dict:
    return {f.id: f for f in response.features}


# ---------------------------------------------------------------------------
# 전사 설정을 안 보낸 경우 (기존 호출)
# ---------------------------------------------------------------------------


def test_전사_설정을_안_보내면_지금까지와_똑같이_동작한다():
    client = FakeClient()
    res = score_submission(make_request(), client=client)

    # 보정 호출 자체가 없어야 한다
    assert client.prompts["transcript"] == []
    assert res.meta.transcript_correction_applied is False
    assert res.meta.transcript_change_count == 0
    assert res.meta.transcript_corrected_text is None
    assert res.meta.transcript_diff == []
    assert res.meta.transcript_low_confidence_errors == 0

    # 문법·내용 둘 다 전사 원문을 보고 채점한다
    assert ORIGINAL in client.prompts["errors"][0]
    assert ORIGINAL in client.prompts["checklist"][0]
    assert res.overall_score is not None


def test_보정을_꺼서_보내면_보정하지_않는다():
    client = FakeClient()
    res = score_submission(
        make_request(transcript=TranscriptInput(correct=False, nationality="베트남")),
        client=client,
    )

    assert client.prompts["transcript"] == []
    assert res.meta.transcript_correction_applied is False


# ---------------------------------------------------------------------------
# 보정본이 어느 영역에 쓰이는가
# ---------------------------------------------------------------------------


def test_문법은_원문으로_내용은_보정본으로_채점한다():
    client = FakeClient()
    res = score_submission(
        make_request(transcript=TranscriptInput(nationality="베트남")),
        client=client,
    )

    assert res.meta.transcript_correction_applied is True
    # 오류 자질은 전사 원문을 봐야 한다. 보정본을 보면 응시자의 실제 오류가 지워진다
    assert ORIGINAL in client.prompts["errors"][0]
    assert CORRECTED not in client.prompts["errors"][0]
    # 체크리스트(내용·과제 수행)는 보정본을 본다
    assert CORRECTED in client.prompts["checklist"][0]
    # 국적은 보정 프롬프트에만 들어간다
    assert "베트남" in client.prompts["transcript"][0]


def test_내용_영역_자질만_보정본_기준으로_바뀐다():
    client = FakeClient()
    res = score_submission(
        make_request(transcript=TranscriptInput()), client=client
    )
    features = feature_map(res)

    # 응답 길이는 '무슨 말을 얼마나 했는가'라서 보정본으로 센다
    length = features["response_length"]
    assert length.components["char_count"] == float(len(CORRECTED))
    assert "보정본" in length.note
    assert all(ev.detail.get("text_source") == "corrected" for ev in length.evidence)

    # 어휘 자질은 언어 사용 쪽이라 원문 기준 그대로여야 한다
    diversity = features["lexical_diversity_mattr"]
    assert "보정본" not in diversity.note
    assert all(ev.detail.get("text_source") != "corrected" for ev in diversity.evidence)


def test_보정_내역이_근거로_결과에_실린다():
    client = FakeClient()
    res = score_submission(make_request(transcript=TranscriptInput()), client=client)

    assert res.meta.transcript_change_count >= 1
    assert res.meta.transcript_corrected_text == CORRECTED

    diff = res.meta.transcript_diff
    assert diff
    for ev in diff:
        # 인용은 전사 원문에서 잘라낸 실제 글자여야 하고, 좌표도 원문 기준이어야 한다
        assert ev.quote in ORIGINAL
        assert ORIGINAL[ev.start : ev.end] == ev.quote
        assert ev.detail["coordinate_base"] == "original_transcript"
    # 무엇이 무엇으로 바뀌었는지 사람이 읽을 수 있어야 한다
    assert any("→" in ev.comment for ev in diff)


# ---------------------------------------------------------------------------
# 보정 구간과 겹치는 오류 지적의 신뢰도
# ---------------------------------------------------------------------------


def test_보정_구간과_겹치는_오류에만_신뢰도_낮음이_붙는다():
    client = FakeClient()
    res = score_submission(make_request(transcript=TranscriptInput()), client=client)

    josa = feature_map(res)["error_josa"]
    marked = [ev for ev in josa.evidence if ev.detail.get("confidence") == "low"]
    plain = [ev for ev in josa.evidence if ev.detail.get("confidence") != "low"]

    # 보정이 일어난 '기가' 자리의 지적에는 꼬리표가 붙는다
    assert len(marked) == 1
    assert "기가" in marked[0].quote
    assert marked[0].comment.startswith("[신뢰도 낮음]")

    # 보정과 상관없는 '반장님한테' 지적은 그대로 남는다
    assert len(plain) == 1
    assert "반장님한테" in plain[0].quote
    assert not plain[0].comment.startswith("[신뢰도 낮음]")

    # 자질과 메타에도 몇 건이 흔들리는 지적인지 남는다
    assert josa.components["low_confidence_error_count"] == 1.0
    assert res.meta.transcript_low_confidence_errors == 1
    assert any("신뢰도 낮음" in w for w in res.warnings)


def test_보정이_없으면_신뢰도_표시도_붙지_않는다():
    # 보정본이 원문과 같으면 흔들릴 자리가 없다
    client = FakeClient(correct=False)
    res = score_submission(make_request(transcript=TranscriptInput()), client=client)

    josa = feature_map(res)["error_josa"]
    assert all(ev.detail.get("confidence") != "low" for ev in josa.evidence)
    assert res.meta.transcript_low_confidence_errors == 0


def test_직접_넘긴_보정_결과가_우선한다():
    # 데모나 검증 스크립트가 보정 결과를 손으로 지정할 수 있어야 한다
    client = FakeClient()
    context = TranscriptContext(
        corrected_text=CORRECTED,
        corrected_spans=[(6, 8)],
        correction_applied=True,
    )
    res = score_submission(
        make_request(transcript=TranscriptInput()), client=client, transcript=context
    )

    # 직접 넘겼으므로 보정 호출을 다시 하지 않는다
    assert client.prompts["transcript"] == []
    assert res.meta.transcript_correction_applied is True
    assert res.meta.transcript_change_count == 1


# ---------------------------------------------------------------------------
# LLM을 못 쓰는 상황과 쓰기 답안
# ---------------------------------------------------------------------------


def test_LLM_키가_없어도_예외_없이_채점된다():
    client = FakeClient(available=False)
    res = score_submission(make_request(transcript=TranscriptInput()), client=client)

    assert client.prompts["transcript"] == []       # 호출을 시도조차 하지 않는다
    assert res.meta.transcript_correction_applied is False
    assert res.overall_score is not None            # 규칙 자질만으로도 점수는 나온다
    assert any("전사 보정" in w for w in res.warnings)


def test_LLM을_끄면_보정도_하지_않는다():
    client = FakeClient()
    res = score_submission(
        make_request(transcript=TranscriptInput(), use_llm=False), client=client
    )

    assert client.prompts["transcript"] == []
    assert res.meta.transcript_correction_applied is False
    assert res.overall_score is not None


def test_쓰기_답안에는_전사_보정을_적용하지_않는다():
    # 쓰기는 응시자가 직접 친 글이라 보정하면 실제 오류가 지워진다
    client = FakeClient()
    res = score_submission(
        make_request(mode=Mode.WRITING, transcript=TranscriptInput()), client=client
    )

    assert client.prompts["transcript"] == []
    assert res.meta.transcript_correction_applied is False
    assert any("쓰기 답안" in w for w in res.warnings)
