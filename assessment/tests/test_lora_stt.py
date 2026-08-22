"""LoRA 받아쓰기 + 발음 분리를 네트워크 없이 확인하는 회귀 테스트.

여기서 못 박는 것 (2026-08-22 구조 변경):
    받아쓰기는 우리 LoRA 가, 발음(delivery)만 Azure 가 한다.
    두 기계가 같은 음성을 각자 처리하며, 어느 쪽이 실패해도 다른 쪽은 살아야 한다.

전부 가짜 http·가짜 발음평가로 돈다. 진짜 RunPod 서버나 진짜 Azure 는 부르지 않는다.
"""

from __future__ import annotations

import io
import json
import math
import wave

import httpx
import pytest

from src.scoring.pipeline import score_submission
from src.scoring.schema import (
    AreaStatus,
    AudioInput,
    ChecklistItem,
    ItemInfo,
    Mode,
    PronouncedWord,
    PronunciationAssessment,
    ScoreArea,
    ScoreOptions,
    ScoreRequest,
)
from src.speech.intake import (
    LORA_STT_URL_ENV,
    STT_PROVIDER_ENV,
    azure_pronunciation_available,
    build_default_pronouncer,
    build_default_stt,
    choose_stt_provider,
    resolve_audio_answer,
)
from src.speech.lora_stt import DEFAULT_LORA_MODEL, LoraStt
from src.speech.port import PronouncerPort, SttPort, SttUnavailable, Transcription

# LoRA 가 받아쓸 법한 글. 채점까지 끝까지 가도록 한국어 문장으로 둔다
SPOKEN_TEXT = "오늘 3번 라인에서 포장기가 멈췄습니다. 전원을 차단하고 정비팀에 연락할까요?"

ITEM = ItemInfo(
    item_id="SPK-LORA-1",
    prompt="작업 중 기계가 멈췄습니다. 반장님에게 보고하고 어떻게 할지 물어보세요.",
    item_type="incident_report",
    expected_register="formal",
    checklist=[
        ChecklistItem(id="c1", description="어떤 문제가 생겼는지 말했는가", weight=1.5),
        ChecklistItem(id="c2", description="다음 지시를 요청했는가", weight=1.5),
    ],
    reference_keywords=["기계", "멈추", "정비"],
)


# ---------------------------------------------------------------------------
# 재료: 소리가 든 wav, 가짜 통신로, 가짜 구현들
# ---------------------------------------------------------------------------


def make_tone_wav(amplitude: int = 8000, seconds: float = 1.0, framerate: int = 16000) -> bytes:
    """소리가 들어 있는 wav 를 만든다(무음 관문을 통과시키는 재료)."""
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


def lora_http(wav: bytes, *, transcript: str = SPOKEN_TEXT, model: str = "whisper-small-lora-v2",
              status: int = 200, body: str | None = None) -> httpx.Client:
    """가짜 통신로 하나로 두 곳을 대신한다.

      - 음성 주소(GET)  -> 우리가 정한 wav 를 내려준다
      - /transcribe(POST) -> LoRA 서버가 줄 법한 JSON 을 돌려준다
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/transcribe"):
            if body is not None:
                return httpx.Response(status, content=body.encode("utf-8"))
            payload = {"text": transcript, "model": model, "duration_ms": 1000}
            return httpx.Response(status, json=payload)
        # 그 밖은 음성 파일 요청으로 본다
        return httpx.Response(200, content=wav, headers={"Content-Type": "audio/wav"})

    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


class FakeLoraStt(SttPort):
    """LoRA 로 받아쓴 결과만 돌려주는 가짜(발음은 주지 않는다)."""

    provider_name = "lora"

    def __init__(self, text: str = SPOKEN_TEXT):
        self._text = text

    @property
    def model_name(self) -> str:
        return "whisper-small-lora-v2"

    def transcribe(self, audio: AudioInput, item_prompt: str = "") -> Transcription:
        return Transcription(
            text=self._text,
            provider=self.provider_name,
            model=self.model_name,
            audio_duration_ms=11400,
            audio_bytes=1234,
            audio_format="wav",
            elapsed_ms=12.5,
            pronunciation=None,  # LoRA 는 발음을 내지 않는다
        )


def sample_assessment() -> PronunciationAssessment:
    """Azure 가 발음만 따로 재서 줄 법한 결과."""
    return PronunciationAssessment(
        accuracy=72.0,
        fluency=88.0,
        completeness=90.0,
        overall=76.5,
        prosody=None,
        scripted=False,
        reference_text="",
        provider="azure",
        words=[
            PronouncedWord(word="포장기가", accuracy=41.0, error_type="Mispronunciation"),
            PronouncedWord(word="멈췄습니다", accuracy=55.0, error_type="Mispronunciation"),
        ],
    )


class FakeAzurePronouncer(PronouncerPort):
    """발음만 재는 가짜 Azure. 받아쓰기와 분리됐는지 확인하는 자리."""

    provider_name = "azure"

    def __init__(self, assessment: PronunciationAssessment | None = None, available: bool = True):
        self._assessment = assessment if assessment is not None else sample_assessment()
        self._available = available
        # 발음 평가가 받은 값을 확인하려고 적어 둔다
        self.calls: list[tuple[str, str]] = []

    @property
    def available(self) -> bool:
        return self._available

    def assess_pronunciation(self, audio, item_prompt="", item_type=""):
        self.calls.append((item_prompt, item_type))
        return self._assessment


class ExplodingPronouncer(PronouncerPort):
    """부르면 터지는 발음평가. '두 번 인식하지 않는다'를 사실로 확인하는 장치."""

    provider_name = "azure"

    @property
    def available(self) -> bool:
        return True

    def assess_pronunciation(self, audio, item_prompt="", item_type=""):
        raise AssertionError("받아쓰기가 이미 발음을 줬는데 발음평가를 또 불렀다")


def speaking_request(**overrides) -> ScoreRequest:
    payload = {
        "submission_id": "sub-lora-1",
        "mode": Mode.SPEAKING,
        "answer_text": "",
        "item": ITEM,
        "audio": AudioInput(url="https://storage.example.com/answers/a1.wav"),
        "options": ScoreOptions(use_llm=False),
    }
    payload.update(overrides)
    return ScoreRequest(**payload)


def find_area(response, area: ScoreArea):
    return next(s for s in response.subscores if s.area == area)


# ---------------------------------------------------------------------------
# 1. 어느 받아쓰기를 쓸지 고르는 규칙 (lora 추가)
# ---------------------------------------------------------------------------


def test_lora_는_주소가_있어야_고른다(monkeypatch):
    """주소 없이 lora 를 고르면 말하기 채점이 통째로 실패하므로 막는다."""
    monkeypatch.setenv(STT_PROVIDER_ENV, "lora")
    monkeypatch.delenv(LORA_STT_URL_ENV, raising=False)
    monkeypatch.delenv("AZURE_SPEECH_KEY", raising=False)
    # 주소가 없으면 기본 규칙(열쇠 없으니 gemini)으로 흘러간다
    assert choose_stt_provider() == "gemini"

    monkeypatch.setenv(LORA_STT_URL_ENV, "https://x.proxy.runpod.net")
    assert choose_stt_provider() == "lora"


def test_lora_를_고르면_LoraStt_가_꽂힌다(monkeypatch):
    monkeypatch.setenv(STT_PROVIDER_ENV, "lora")
    monkeypatch.setenv(LORA_STT_URL_ENV, "https://x.proxy.runpod.net")
    engine = build_default_stt()
    assert isinstance(engine, LoraStt)
    assert engine.provider_name == "lora"


def test_발음_평가기는_전사와_별개로_열쇠로_정해진다(monkeypatch):
    """전사 제공자가 무엇이든, Azure 열쇠가 있으면 발음 평가기가 만들어진다."""
    monkeypatch.setenv("AZURE_SPEECH_KEY", "있는척")
    monkeypatch.setenv("AZURE_SPEECH_REGION", "koreacentral")
    assert azure_pronunciation_available() is True
    assert build_default_pronouncer() is not None

    monkeypatch.delenv("AZURE_SPEECH_KEY", raising=False)
    assert azure_pronunciation_available() is False
    assert build_default_pronouncer() is None


# ---------------------------------------------------------------------------
# 2. LoraStt 클라이언트 — 진짜 구현을 가짜 http 로 끝까지 돌린다
# ---------------------------------------------------------------------------


def test_LoraStt_가_서버로_보내_전사를_받아_온다():
    """provider=lora 일 때 전사가 만들어지고 그 내력이 남는지."""
    with lora_http(make_tone_wav(), transcript="반장님 기계가 멈췄습니다.") as client:
        stt = LoraStt(url="https://x.proxy.runpod.net", http_client=client)
        result = stt.transcribe(AudioInput(url="https://storage.example.com/a.wav"))

    assert result.provider == "lora"
    assert result.text == "반장님 기계가 멈췄습니다."
    assert result.model == "whisper-small-lora-v2"
    # 발음은 이 구현이 내지 않는다(Azure 가 따로 붙인다)
    assert result.pronunciation is None


def test_주소가_없으면_분명히_실패한다():
    """빈 글이나 지어낸 글이 아니라 실패를 돌려준다."""
    stt = LoraStt(url="")
    assert stt.available is False
    with pytest.raises(SttUnavailable) as caught:
        stt.transcribe(AudioInput(url="https://storage.example.com/a.wav"))
    assert LORA_STT_URL_ENV in str(caught.value)


def test_서버가_5xx면_받아쓰기_실패로_올린다():
    """실패를 삼키지 않고 SttUnavailable 로 올려 503 경로를 탄다."""
    with lora_http(make_tone_wav(), status=500, body="boom") as client:
        stt = LoraStt(url="https://x.proxy.runpod.net", http_client=client)
        with pytest.raises(SttUnavailable) as caught:
            stt.transcribe(AudioInput(url="https://storage.example.com/a.wav"))
    assert "500" in str(caught.value)


def test_서버가_빈_글을_주면_실패로_다룬다():
    """'말을 안 한 답안'과 '받아쓰기 실패'를 섞지 않는다."""
    with lora_http(make_tone_wav(), transcript="   ") as client:
        stt = LoraStt(url="https://x.proxy.runpod.net", http_client=client)
        with pytest.raises(SttUnavailable):
            stt.transcribe(AudioInput(url="https://storage.example.com/a.wav"))


def test_무음이면_서버를_부르지도_않는다():
    """소리가 없는 녹음으로 그래픽카드 호출을 낭비하지 않고, 지어낸 글도 막는다."""
    called: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/transcribe"):
            called.append(1)
            return httpx.Response(200, json={"text": "지어낸 글", "model": "x"})
        return httpx.Response(200, content=make_tone_wav(amplitude=0),
                              headers={"Content-Type": "audio/wav"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        stt = LoraStt(url="https://x.proxy.runpod.net", http_client=client)
        with pytest.raises(SttUnavailable):
            stt.transcribe(AudioInput(url="https://storage.example.com/a.wav"))
    assert called == []


# ---------------------------------------------------------------------------
# 3. 받아쓰기 LoRA + 발음 Azure 분리 (핵심)
# ---------------------------------------------------------------------------


def test_provider_lora_인데_발음은_Azure_가_따로_채점한다():
    """전사는 LoRA, 발음은 Azure. delivery 가 점수를 받고 근거가 남는지."""
    pronouncer = FakeAzurePronouncer(sample_assessment())
    response = score_submission(
        speaking_request(), stt=FakeLoraStt(), pronouncer=pronouncer
    )

    # 전사 제공자는 정확히 lora 로 남는다
    assert response.meta.stt_provider == "lora"
    assert response.meta.stt_transcript == SPOKEN_TEXT

    # delivery 가 채점됐고 비중을 갖는다
    delivery = find_area(response, ScoreArea.DELIVERY)
    assert delivery.status == AreaStatus.SCORED
    assert delivery.score is not None
    assert delivery.weight == pytest.approx(0.2)
    # 어느 낱말 때문에 깎였는지가 근거로 남는다(근거 없는 점수는 결함이다)
    assert any(ev.quote == "포장기가" for ev in delivery.evidence)

    # 발음평가가 실제로 불렸고, 문항 유형까지 전달됐다(낭독형 판단에 쓰인다)
    assert pronouncer.calls and pronouncer.calls[0][1] == "incident_report"

    # 전사와 발음을 서로 다른 기계가 맡았다는 사실이 남는다
    assert any("발음평가로 따로 채점" in w for w in response.warnings)


def test_provider_lora_인데_발음평가기가_없으면_delivery_는_비어_있다():
    """Azure 열쇠가 없으면(발음평가기 None) 전사는 정상, delivery 만 비운다."""
    response = score_submission(
        speaking_request(), stt=FakeLoraStt(), pronouncer=None
    )

    assert response.meta.stt_provider == "lora"
    assert response.meta.stt_transcript == SPOKEN_TEXT

    delivery = find_area(response, ScoreArea.DELIVERY)
    assert delivery.status == AreaStatus.NOT_EVALUATED
    assert delivery.weight == 0.0
    # 나머지 두 영역은 예전 비율 그대로다(백엔드가 보는 값이 바뀌면 안 된다)
    assert find_area(response, ScoreArea.CONTENT_TASK).weight == pytest.approx(0.45)
    assert find_area(response, ScoreArea.LANGUAGE_USE).weight == pytest.approx(0.55)


def test_발음평가가_실패해도_전사는_살고_delivery_만_비운다():
    """발음만 못 잰 것은 채점 전체를 세울 이유가 아니다."""
    pronouncer = FakeAzurePronouncer(available=True)
    # 발음평가가 None(못 잼)을 돌려주도록 바꾼다
    pronouncer._assessment = None
    response = score_submission(
        speaking_request(), stt=FakeLoraStt(), pronouncer=pronouncer
    )

    assert response.meta.stt_provider == "lora"
    delivery = find_area(response, ScoreArea.DELIVERY)
    assert delivery.status == AreaStatus.NOT_EVALUATED
    # 발음을 못 잰 사실이 사람이 읽을 수 있게 남는다
    assert any("발음 평가를 하지 못해" in w for w in response.warnings)


def test_받아쓰기가_이미_발음을_주면_발음평가를_또_부르지_않는다():
    """provider=azure 처럼 전사가 발음까지 준 경우, 한 음성을 두 번 인식하지 않는다."""

    class PronouncingStt(SttPort):
        provider_name = "azure"

        @property
        def model_name(self) -> str:
            return "azure-fake"

        def transcribe(self, audio, item_prompt="", item_type=""):
            return Transcription(
                text=SPOKEN_TEXT, provider="azure", model="azure-fake",
                audio_format="wav", pronunciation=sample_assessment(),
            )

    # 발음평가기를 넘겨도, 전사가 이미 발음을 줬으므로 불리지 않아야 한다
    response = score_submission(
        speaking_request(), stt=PronouncingStt(), pronouncer=ExplodingPronouncer()
    )
    delivery = find_area(response, ScoreArea.DELIVERY)
    assert delivery.status == AreaStatus.SCORED
    assert response.meta.stt_provider == "azure"


# ---------------------------------------------------------------------------
# 4. resolve_audio_answer 의 발음평가기 인자 규칙
# ---------------------------------------------------------------------------


def test_가짜_stt_를_꽂으면_기본_발음평가기를_만들지_않는다(monkeypatch):
    """테스트가 네트워크 없이 돌아야 하므로, stt 를 주입하면 진짜 Azure 를 안 만든다.

    열쇠가 환경에 있더라도(개발자의 .env) 가짜 stt 주입 경로에서는
    발음평가기를 자동으로 만들지 않는다.
    """
    monkeypatch.setenv("AZURE_SPEECH_KEY", "있는척")
    monkeypatch.setenv("AZURE_SPEECH_REGION", "koreacentral")
    # pronouncer 를 안 넘기고 stt 만 주입한다(=_UNSET, 그러나 stt 주입됨)
    resolution = resolve_audio_answer(speaking_request(), stt=FakeLoraStt())
    assert resolution is not None
    # 발음평가기를 자동으로 만들지 않았으므로 발음이 붙지 않는다
    assert resolution.pronunciation is None
    assert resolution.provider == "lora"


# ---------------------------------------------------------------------------
# 5. 쓰기·글 답안은 아무 영향도 받지 않는다
# ---------------------------------------------------------------------------


def test_쓰기_답안은_발음평가기를_넘겨도_영향이_없다():
    """쓰기에는 소리가 없으므로 발음을 잴 방법이 없다."""
    response = score_submission(
        ScoreRequest(
            submission_id="sub-write-1",
            mode=Mode.WRITING,
            answer_text="오늘 3번 라인에서 포장기가 멈췄습니다. 전원을 차단하고 정비팀에 연락했습니다.",
            item=ITEM,
            options=ScoreOptions(use_llm=False),
        ),
        pronouncer=FakeAzurePronouncer(),
    )
    delivery = find_area(response, ScoreArea.DELIVERY)
    assert delivery.status == AreaStatus.NOT_EVALUATED
    assert not any(f.id.startswith("pron_") for f in response.features)


def test_기본_모델_이름은_서버가_주기_전까지의_임시값이다():
    """서버가 모델 이름을 주면 그것으로 덮어쓰지만, 부르기 전엔 임시값을 쓴다."""
    stt = LoraStt(url="https://x.proxy.runpod.net")
    assert stt.model_name == DEFAULT_LORA_MODEL
