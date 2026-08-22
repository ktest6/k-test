"""발음 채점(발화 전달력) 회귀 테스트.

여기서 지키려는 것은 다섯 가지다.

  1. **발음 점수가 있으면 발화 전달력이 채점된다.**
     그동안 비워 두었던 영역이 실제로 점수와 비중을 갖는지 못 박는다.
  2. **점수에는 근거가 따라온다.**
     어느 낱말이 몇 점이었는지가 남지 않으면 이 프로젝트에서는 결함이다.
  3. **발음 점수가 없으면 예전 그대로다.**
     발화 전달력은 not_evaluated·비중 0 이고, 종합 점수는 예전 비율
     (내용 0.45 : 언어 0.55)로 계산된다. 백엔드와 그렇게 약속돼 있다.
  4. **쓰기 답안은 아무 영향도 받지 않는다.**
  5. **어느 받아쓰기를 쓸지 고르는 규칙이 지켜진다.**
     열쇠가 없는 곳에서 azure 를 고르면 채점이 통째로 실패한다.

이 테스트는 **네트워크를 한 번도 쓰지 않는다.**
Azure 를 부르는 자리에는 미리 만들어 둔 가짜 응답(JSON)을 꽂고,
파일 내려받기는 httpx 의 가짜 통신로(MockTransport)를 쓴다.

실행: .venv\\Scripts\\python.exe -m pytest tests -q
"""

from __future__ import annotations

import io
import math
import wave

import httpx
import pytest

from src.features.pronunciation import extract_pronunciation_features
from src.scoring.combine import DEFAULT_WEIGHTS, combine
from src.scoring.pipeline import score_submission
from src.scoring.schema import (
    AreaStatus,
    AudioInput,
    ChecklistItem,
    FeatureSource,
    FeatureStatus,
    ItemInfo,
    Mode,
    PronouncedWord,
    PronunciationAssessment,
    ScoreArea,
    ScoreOptions,
    ScoreRequest,
)
from src.speech.azure_stt import AzureStt, is_read_aloud
from src.speech.intake import STT_PROVIDER_ENV, choose_stt_provider
from src.speech.port import SttPort, SttUnavailable, Transcription

# ---------------------------------------------------------------------------
# 시험용 재료
# ---------------------------------------------------------------------------

SPOKEN_TEXT = (
    "반장님, 지금 삼번 라인 포장기가 갑자기 멈췄습니다. "
    "제가 전원 버튼을 다시 눌러 봤는데 안 됩니다. "
    "전원을 차단하고 정비팀에 연락할까요?"
)

ITEM = ItemInfo(
    item_id="SPK-PRON-1",
    prompt="작업 중 기계가 멈췄습니다. 반장님에게 보고하고 어떻게 할지 물어보세요.",
    item_type="incident_report",
    expected_register="formal",
    checklist=[
        ChecklistItem(id="c1", description="어떤 문제가 생겼는지 말했는가", weight=1.5),
        ChecklistItem(id="c2", description="다음 지시를 요청했는가", weight=1.5),
    ],
    reference_keywords=["기계", "멈추", "정비"],
)


def sample_assessment(scripted: bool = False) -> PronunciationAssessment:
    """Azure 가 줄 법한 발음 평가 결과 하나.

    실제 응시자 녹음에서 나온 값의 모양을 그대로 본떴다
    (낱말 대부분이 잘못 발음으로 표시되고 점수가 40~60점대에 몰린다).
    """
    return PronunciationAssessment(
        accuracy=72.0,
        fluency=88.0,
        completeness=90.0,
        overall=76.5,
        prosody=None,          # 한국어는 억양 점수가 오지 않는다(실측)
        scripted=scripted,
        reference_text=ITEM.prompt if scripted else "",
        provider="azure",
        words=[
            PronouncedWord(word="반장님", accuracy=95.0, error_type="None"),
            PronouncedWord(word="포장기가", accuracy=41.0, error_type="Mispronunciation"),
            PronouncedWord(word="멈췄습니다", accuracy=55.0, error_type="Mispronunciation"),
            PronouncedWord(word="정비팀에", accuracy=88.0, error_type="None"),
        ],
    )


class PronouncingStt(SttPort):
    """받아쓰기와 함께 발음 점수를 주는 가짜. Azure 자리에 꽂는다."""

    provider_name = "fake-azure"

    def __init__(self, assessment: PronunciationAssessment | None = None, text: str = SPOKEN_TEXT):
        self._assessment = assessment
        self._text = text
        # 문항 유형이 실제로 넘어왔는지 확인하려고 적어 둔다
        self.seen_item_types: list[str] = []

    @property
    def model_name(self) -> str:
        return "fake-azure-v0"

    def transcribe(
        self, audio: AudioInput, item_prompt: str = "", item_type: str = ""
    ) -> Transcription:
        self.seen_item_types.append(item_type)
        return Transcription(
            text=self._text,
            provider=self.provider_name,
            model=self.model_name,
            audio_duration_ms=11400,
            audio_bytes=1234,
            audio_format="wav",
            elapsed_ms=12.5,
            pronunciation=self._assessment,
        )


class SilentAboutPronunciationStt(PronouncingStt):
    """발음을 재지 못하는 가짜(지금의 Gemini 자리)."""

    provider_name = "fake-gemini"

    def __init__(self, text: str = SPOKEN_TEXT):
        super().__init__(assessment=None, text=text)


def speaking_request(**overrides) -> ScoreRequest:
    """말하기 + 음성 요청 하나를 만든다."""
    payload = {
        "submission_id": "sub-pron-1",
        "mode": Mode.SPEAKING,
        "answer_text": "",
        "item": ITEM,
        "audio": AudioInput(url="https://storage.example.com/answers/a1.wav"),
        # 실호출을 막는다. 이 테스트는 발음 점수 배선만 본다
        "options": ScoreOptions(use_llm=False),
    }
    payload.update(overrides)
    return ScoreRequest(**payload)


def find_area(response, area: ScoreArea):
    """응답에서 영역 하나를 꺼낸다."""
    return next(s for s in response.subscores if s.area == area)


# ---------------------------------------------------------------------------
# 1. 어느 받아쓰기를 쓸지 고르는 규칙
# ---------------------------------------------------------------------------


def test_환경변수가_있으면_그것을_따른다(monkeypatch):
    """운영자가 직접 정한 값이 언제나 우선이다."""
    monkeypatch.setenv(STT_PROVIDER_ENV, "gemini")
    monkeypatch.setenv("AZURE_SPEECH_KEY", "있는척")
    monkeypatch.setenv("AZURE_SPEECH_REGION", "koreacentral")
    # 열쇠가 있어도 gemini 라고 적어 두었으면 gemini 다
    assert choose_stt_provider() == "gemini"

    monkeypatch.setenv(STT_PROVIDER_ENV, "AZURE")  # 대문자로 적어도 알아본다
    assert choose_stt_provider() == "azure"


def test_환경변수가_없으면_열쇠_유무로_정한다(monkeypatch):
    """열쇠가 없는 곳에서도 예전처럼 돌아야 한다.

    열쇠가 없는데 azure 를 고르면 말하기 채점이 통째로 실패한다.
    """
    monkeypatch.delenv(STT_PROVIDER_ENV, raising=False)
    monkeypatch.setenv("AZURE_SPEECH_KEY", "있는척")
    monkeypatch.setenv("AZURE_SPEECH_REGION", "koreacentral")
    assert choose_stt_provider() == "azure"

    monkeypatch.delenv("AZURE_SPEECH_KEY", raising=False)
    assert choose_stt_provider() == "gemini"

    # 열쇠는 있는데 지역이 없으면 부를 수 없다. 그때도 예전 길로 간다
    monkeypatch.setenv("AZURE_SPEECH_KEY", "있는척")
    monkeypatch.delenv("AZURE_SPEECH_REGION", raising=False)
    assert choose_stt_provider() == "gemini"


def test_알_수_없는_이름은_무시한다(monkeypatch):
    """오타가 난 이름 때문에 채점이 멈추지 않게 한다."""
    monkeypatch.setenv(STT_PROVIDER_ENV, "azur")  # 오타
    monkeypatch.delenv("AZURE_SPEECH_KEY", raising=False)
    assert choose_stt_provider() == "gemini"


def test_열쇠가_없으면_Azure_는_분명히_실패한다():
    """빈 글이나 지어낸 글이 아니라 실패를 돌려준다."""
    stt = AzureStt(key="", region="")
    assert stt.available is False
    with pytest.raises(SttUnavailable) as caught:
        stt.transcribe(AudioInput(url="https://example.com/a.wav"))
    assert "AZURE_SPEECH_KEY" in str(caught.value)


def test_낭독형_문항만_제시문을_정답지로_준다():
    """자유 발화에 정답지를 주면 그 글을 안 읽었다는 이유로 점수가 깎인다."""
    assert is_read_aloud("read_aloud") is True
    assert is_read_aloud("낭독") is True
    # 지금 쓰는 말하기 문항 유형은 전부 자유 발화다
    for item_type in (
        "incident_report", "hazard_warning", "instruction_restate",
        "completion_report", "help_request", "", "free_response",
    ):
        assert is_read_aloud(item_type) is False


def test_문항_유형이_받아쓰기까지_전달된다():
    """낭독형인지 아닌지를 받아쓰기 쪽이 알아야 정답지를 줄지 정할 수 있다."""
    stt = PronouncingStt(sample_assessment())
    score_submission(speaking_request(), stt=stt)
    assert stt.seen_item_types == ["incident_report"]


# ---------------------------------------------------------------------------
# 2. 발음 점수 -> 자질 (근거가 붙는가)
# ---------------------------------------------------------------------------


def test_발음_점수가_자질로_옮겨진다():
    features = {f.id: f for f in extract_pronunciation_features(sample_assessment(), SPOKEN_TEXT)}

    assert features["pron_accuracy"].value == 72.0
    assert features["pron_accuracy"].source == FeatureSource.AZURE
    assert features["pron_fluency"].value == 88.0
    # 억양은 값이 오지 않았다. 0으로 때우지 않고 '못 구했다'로 남는다
    assert features["pron_prosody"].status == FeatureStatus.UNAVAILABLE
    assert features["pron_prosody"].value is None


def test_점수가_낮은_낱말이_근거로_남는다():
    """**이 프로젝트에서 근거 없는 점수는 결함이다.**

    "발음 72점"만으로는 응시자가 무엇을 고쳐야 할지 알 수 없다.
    """
    features = {f.id: f for f in extract_pronunciation_features(sample_assessment(), SPOKEN_TEXT)}
    quotes = [ev.quote for ev in features["pron_accuracy"].evidence if ev.quote]

    # 기준(60점)보다 낮은 낱말만 들어오고, 낮은 것이 앞에 온다
    assert quotes[0] == "포장기가"
    assert "멈췄습니다" in quotes
    assert "반장님" not in quotes  # 95점짜리는 근거로 적지 않는다

    # 인용은 받아쓴 글에 실제로 있는 말이어야 하고, 그 위치가 남아야 한다
    first = next(ev for ev in features["pron_accuracy"].evidence if ev.quote == "포장기가")
    assert SPOKEN_TEXT[first.start:first.end] == "포장기가"
    assert first.detail["accuracy"] == 41.0


def test_자유_발화에서는_완전성을_채점에_쓰지_않는다():
    """읽어야 할 원문이 없으면 '얼마나 말했는가'의 기준이 없다."""
    free = extract_pronunciation_features(sample_assessment(scripted=False), SPOKEN_TEXT)
    scripted = extract_pronunciation_features(sample_assessment(scripted=True), SPOKEN_TEXT)

    free_completeness = next(f for f in free if f.id == "pron_completeness")
    scripted_completeness = next(f for f in scripted if f.id == "pron_completeness")

    assert free_completeness.status == FeatureStatus.NOT_APPLICABLE
    assert scripted_completeness.status == FeatureStatus.OK


def test_발음_평가가_없으면_자질을_만들지_않는다():
    """값을 지어내지 않는다. 빈 목록이면 발화 전달력이 채점되지 않는다."""
    assert extract_pronunciation_features(None, SPOKEN_TEXT) == []


# ---------------------------------------------------------------------------
# 3. 발화 전달력 영역 점수
# ---------------------------------------------------------------------------


def test_발음_점수가_있으면_발화_전달력이_채점된다():
    response = score_submission(
        speaking_request(), stt=PronouncingStt(sample_assessment())
    )
    delivery = find_area(response, ScoreArea.DELIVERY)

    assert delivery.status == AreaStatus.SCORED
    assert delivery.score is not None
    # 종합 점수에서 실제로 비중을 갖는다(임시값 0.2)
    assert delivery.weight == pytest.approx(0.2)
    # 어느 낱말 때문에 깎였는지가 영역 근거에 올라온다
    assert any(ev.quote == "포장기가" for ev in delivery.evidence)
    assert all(ev.source == FeatureSource.AZURE for ev in delivery.evidence)


def test_발화_전달력이_붙어도_나머지_두_영역의_비율은_그대로다():
    """delivery 0.2 를 빼고 남은 0.8 을 예전 비율(0.45:0.55)로 나눈다."""
    response = score_submission(
        speaking_request(), stt=PronouncingStt(sample_assessment())
    )
    content = find_area(response, ScoreArea.CONTENT_TASK)
    language = find_area(response, ScoreArea.LANGUAGE_USE)

    assert content.weight == pytest.approx(0.36)
    assert language.weight == pytest.approx(0.44)
    # 세 영역 비중을 다 더하면 1이 된다
    assert content.weight + language.weight + 0.2 == pytest.approx(1.0)


def test_발화_전달력_점수는_자질에서_나온_것을_설명한다():
    """점수만 주지 않고 어떤 자질이 몇 점을 보탰는지 함께 낸다."""
    response = score_submission(
        speaking_request(), stt=PronouncingStt(sample_assessment())
    )
    delivery = find_area(response, ScoreArea.DELIVERY)
    contributed = {c.feature_id for c in delivery.contributions}

    # 자유 발화라 완전성은 빠지고, 정확도와 유창성이 다시 100%가 되게 나뉜다
    assert contributed == {"pron_accuracy", "pron_fluency"}
    total = sum(c.weight for c in delivery.contributions)
    assert total == pytest.approx(1.0)
    # 내역의 점수를 더하면 영역 점수가 된다(검산이 되는 값이어야 한다)
    assert sum(c.points for c in delivery.contributions) == pytest.approx(
        delivery.score, abs=0.05
    )


def test_발음_종합값은_점수_계산에_쓰지_않는다():
    """Azure 가 합쳐 준 값을 함께 넣으면 같은 것을 두 번 세게 된다."""
    response = score_submission(
        speaking_request(), stt=PronouncingStt(sample_assessment())
    )
    delivery = find_area(response, ScoreArea.DELIVERY)
    assert "pron_overall" not in {c.feature_id for c in delivery.contributions}
    # 다만 결과에는 남아 있어야 한다(우리 계산과 대조하는 값이다)
    assert any(f.id == "pron_overall" for f in response.features)


# ---------------------------------------------------------------------------
# 4. 발음 점수가 없을 때 — 예전과 똑같아야 한다
# ---------------------------------------------------------------------------


def test_발음_점수가_없으면_발화_전달력은_예전처럼_비어_있다():
    response = score_submission(
        speaking_request(), stt=SilentAboutPronunciationStt()
    )
    delivery = find_area(response, ScoreArea.DELIVERY)

    assert delivery.status == AreaStatus.NOT_EVALUATED
    assert delivery.score is None
    assert delivery.weight == 0.0
    # 채점하지 않은 영역을 경고로 떠들지 않는다(처음부터 그렇게 약속돼 있다)
    assert not any("발화 전달력" in w and "채점하지 못했다" in w for w in response.warnings)


def test_발음_점수가_없으면_예전_비율_그대로_계산된다():
    """0.45 : 0.55. 백엔드가 지금 보고 있는 값이 바뀌면 안 된다."""
    response = score_submission(
        speaking_request(), stt=SilentAboutPronunciationStt()
    )
    assert find_area(response, ScoreArea.CONTENT_TASK).weight == pytest.approx(0.45)
    assert find_area(response, ScoreArea.LANGUAGE_USE).weight == pytest.approx(0.55)


def test_음성을_안_보낸_요청도_예전_그대로다():
    """글로만 보내는 기존 호출은 하나도 안 바뀐다."""
    response = score_submission(
        ScoreRequest(
            submission_id="sub-text-1",
            mode=Mode.SPEAKING,
            answer_text=SPOKEN_TEXT,
            item=ITEM,
            options=ScoreOptions(use_llm=False),
        )
    )
    delivery = find_area(response, ScoreArea.DELIVERY)
    assert delivery.status == AreaStatus.NOT_EVALUATED
    assert find_area(response, ScoreArea.CONTENT_TASK).weight == pytest.approx(0.45)
    assert find_area(response, ScoreArea.LANGUAGE_USE).weight == pytest.approx(0.55)


def test_쓰기_답안은_아무_영향도_받지_않는다():
    """쓰기에는 소리가 없으므로 발화 전달력을 채점할 방법이 없다."""
    response = score_submission(
        ScoreRequest(
            submission_id="sub-write-1",
            mode=Mode.WRITING,
            answer_text="오늘 3번 라인에서 포장기가 멈췄습니다. 전원을 차단하고 정비팀에 연락했습니다.",
            item=ITEM,
            options=ScoreOptions(use_llm=False),
        )
    )
    delivery = find_area(response, ScoreArea.DELIVERY)
    assert delivery.status == AreaStatus.NOT_EVALUATED
    assert delivery.weight == 0.0
    assert find_area(response, ScoreArea.CONTENT_TASK).weight == pytest.approx(0.45)
    assert find_area(response, ScoreArea.LANGUAGE_USE).weight == pytest.approx(0.55)
    # 발음 자질이 결과에 섞여 들어가지 않는다
    assert not any(f.id.startswith("pron_") for f in response.features)


def test_발음_자질만_따로_넣어도_결합이_돈다():
    """결합 단계 하나만 떼어 확인한다(파이프라인 없이)."""
    features = extract_pronunciation_features(sample_assessment(), SPOKEN_TEXT)
    result = combine(features=features, checklist_results=[], mode=Mode.SPEAKING,
                     weights=DEFAULT_WEIGHTS)
    delivery = next(s for s in result.subscores if s.area == ScoreArea.DELIVERY)
    assert delivery.status == AreaStatus.SCORED
    assert delivery.score is not None


# ---------------------------------------------------------------------------
# 5. Azure 응답을 우리 값으로 바꾸는 규칙 (가짜 JSON, 네트워크 없음)
# ---------------------------------------------------------------------------


def azure_segment(
    display: str,
    accuracy: float,
    fluency: float,
    completeness: float,
    pron: float,
    words: list[tuple[str, float, str]],
    duration_ticks: int = 25_400_000,
) -> dict:
    """Azure 가 문장 하나를 인식했을 때 주는 JSON 모양을 그대로 흉내 낸다."""
    return {
        "Duration": duration_ticks,
        "DisplayText": display,
        "NBest": [
            {
                "Display": display,
                "PronunciationAssessment": {
                    "AccuracyScore": accuracy,
                    "FluencyScore": fluency,
                    "CompletenessScore": completeness,
                    "PronScore": pron,
                },
                "Words": [
                    {
                        "Word": word,
                        "Offset": 10_000,
                        "Duration": 20_000,
                        "PronunciationAssessment": {
                            "AccuracyScore": score,
                            "ErrorType": error_type,
                        },
                    }
                    for word, score, error_type in words
                ],
            }
        ],
    }


def test_인식_조각_하나를_그대로_옮긴다():
    segment = azure_segment(
        "기계가 멈췄습니다.", 57.0, 100.0, 20.0, 43.4,
        [("기계가", 43.0, "Mispronunciation"), ("멈췄습니다", 71.0, "None")],
    )
    text, assessment = AzureStt._merge_segments([segment], scripted=True, reference_text="기계가 멈췄습니다.")

    assert text == "기계가 멈췄습니다."
    assert assessment.accuracy == 57.0
    assert assessment.fluency == 100.0
    assert assessment.completeness == 20.0
    assert assessment.overall == 43.4
    assert [w.word for w in assessment.words] == ["기계가", "멈췄습니다"]
    # 100나노초 단위가 밀리초로 바뀌어 들어온다
    assert assessment.words[0].offset_ms == 1
    assert assessment.words[0].duration_ms == 2


def test_긴_녹음이_여러_조각으로_와도_하나로_합쳐진다():
    """정확도는 낱말 수로, 유창성은 길이로 무게를 준다(임시 규칙)."""
    first = azure_segment(
        "첫 문장입니다.", 90.0, 50.0, 100.0, 80.0,
        [("첫", 90.0, "None")],                      # 낱말 1개
        duration_ticks=10_000_000,                   # 1000ms
    )
    second = azure_segment(
        "둘째 문장입니다.", 50.0, 100.0, 100.0, 40.0,
        [("둘", 50.0, "None"), ("째", 50.0, "None"), ("문장", 50.0, "None")],  # 낱말 3개
        duration_ticks=30_000_000,                   # 3000ms
    )
    text, assessment = AzureStt._merge_segments([first, second], scripted=False, reference_text="")

    assert text == "첫 문장입니다. 둘째 문장입니다."
    # 정확도: (90*1 + 50*3) / 4 = 60
    assert assessment.accuracy == pytest.approx(60.0)
    # 유창성: (50*1000 + 100*3000) / 4000 = 87.5
    assert assessment.fluency == pytest.approx(87.5)
    assert len(assessment.words) == 4


def test_점수가_하나도_없으면_발음_평가를_만들지_않는다():
    """0점으로 때우면 못 잰 답안이 발음 0점을 받는다."""
    bare = {"NBest": [{"Display": "안녕하세요.", "Words": []}]}
    text, assessment = AzureStt._merge_segments([bare], scripted=False, reference_text="")
    assert text == "안녕하세요."
    assert assessment is None


def test_한국어는_억양_점수가_없다고_알린다():
    segment = azure_segment("기계가 멈췄습니다.", 70.0, 80.0, 100.0, 75.0, [("기계가", 70.0, "None")])
    _, assessment = AzureStt._merge_segments([segment], scripted=False, reference_text="")
    assert assessment.prosody is None
    assert any("억양" in w for w in assessment.warnings)
    assert any("완전성" in w for w in assessment.warnings)


# ---------------------------------------------------------------------------
# 6. Azure 구현 전체 — 가짜 응답을 꽂고 네트워크 없이 끝까지 돌린다
# ---------------------------------------------------------------------------


def make_tone_wav(amplitude: int = 8000, seconds: float = 1.0, framerate: int = 48000) -> bytes:
    """소리가 들어 있는 wav 를 만든다. 무음 관문을 통과시키기 위한 재료다.

    48kHz 로 만드는 이유: Azure 가 그대로는 받지 않는 규격이라
    우리가 16kHz 로 바꿔서 보내는지를 여기서 확인할 수 있다.
    """
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(framerate)
        frames = bytearray()
        for index in range(int(framerate * seconds)):
            value = int(amplitude * math.sin(2 * math.pi * 440 * index / framerate))
            frames += int(value).to_bytes(2, "little", signed=True)
        handle.writeframes(bytes(frames))
    return buffer.getvalue()


def mock_http(data: bytes) -> httpx.Client:
    """네트워크 대신 우리가 정한 wav 를 돌려주는 가짜 통신로."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=data, headers={"Content-Type": "audio/wav"})

    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


def test_Azure_구현이_받아쓰기와_발음_점수를_함께_돌려준다():
    captured: dict = {}

    def fake_recognize(pcm: bytes, reference_text: str, timeout_s: float) -> list[dict]:
        # 우리가 16kHz 로 바꿔서 보냈는지 확인한다.
        # 48kHz 1초짜리를 넣었으므로 16000칸 * 2바이트 = 32000바이트가 되어야 한다
        captured["pcm_bytes"] = len(pcm)
        captured["reference_text"] = reference_text
        return [
            azure_segment(
                "기계가 멈췄습니다.", 66.0, 90.0, 100.0, 72.0,
                [("기계가", 43.0, "Mispronunciation"), ("멈췄습니다", 88.0, "None")],
            )
        ]

    stt = AzureStt(
        key="시험용",
        region="koreacentral",
        http_client=mock_http(make_tone_wav()),
        recognize=fake_recognize,
    )
    result = stt.transcribe(
        AudioInput(url="https://storage.example.com/a.wav", format="wav"),
        item_prompt=ITEM.prompt,
        item_type="incident_report",
    )

    assert captured["pcm_bytes"] == 32_000
    # 자유 발화라 정답지를 주지 않았다
    assert captured["reference_text"] == ""
    assert result.provider == "azure"
    assert result.text == "기계가 멈췄습니다."
    assert result.pronunciation.accuracy == 66.0
    assert result.pronunciation.scripted is False


def test_낭독형이면_제시문을_정답지로_넘긴다():
    captured: dict = {}

    def fake_recognize(pcm: bytes, reference_text: str, timeout_s: float) -> list[dict]:
        captured["reference_text"] = reference_text
        return [azure_segment("나는 집 내부 공사를 끝냈다.", 57.0, 100.0, 20.0, 43.4,
                              [("집", 43.0, "Mispronunciation")])]

    stt = AzureStt(
        key="시험용", region="koreacentral",
        http_client=mock_http(make_tone_wav()), recognize=fake_recognize,
    )
    result = stt.transcribe(
        AudioInput(url="https://storage.example.com/a.wav", format="wav"),
        item_prompt="나는 집 내부 공사를 끝냈다.",
        item_type="read_aloud",
    )

    assert captured["reference_text"] == "나는 집 내부 공사를 끝냈다."
    assert result.pronunciation.scripted is True
    # 정답지에 맞춰 인식된 글이라는 사실을 반드시 알린다
    assert any("정답지" in w for w in result.warnings)


def test_wav_가_아니면_분명히_거절한다():
    """압축 형식을 풀 도구가 없다. 추측해서 읽지 않는다."""
    stt = AzureStt(key="시험용", region="koreacentral", http_client=mock_http(b"\x00" * 100),
                   recognize=lambda **kwargs: [])
    with pytest.raises(SttUnavailable) as caught:
        stt.transcribe(AudioInput(url="https://storage.example.com/a.m4a", format="m4a"))
    assert "wav" in str(caught.value)


def test_무음_녹음은_Azure_를_부르지도_않는다():
    """소리가 없는 녹음으로 점수가 나오면 안 된다(2026-08-02 사고와 같은 관문)."""
    called: list[int] = []

    def fake_recognize(**kwargs):
        called.append(1)
        return []

    stt = AzureStt(
        key="시험용", region="koreacentral",
        http_client=mock_http(make_tone_wav(amplitude=0)),   # 소리가 전혀 없는 wav
        recognize=fake_recognize,
    )
    with pytest.raises(SttUnavailable):
        stt.transcribe(AudioInput(url="https://storage.example.com/a.wav", format="wav"))
    assert called == []
