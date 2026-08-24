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
from fastapi.testclient import TestClient

from src import api
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
from src.speech.audio import FetchedAudio
from src.speech.azure_stt import AzureStt
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
from src.speech.loudness import measure_wav_loudness
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


# ---------------------------------------------------------------------------
# 6. ping — 추론 서버가 정말 살아 있는지 물어본다
#
# 여기서 막으려는 사고 하나:
#   available 은 '주소가 적혀 있다'만 본다. 그래서 8100 서버가 꺼져 있어도 참이고,
#   그 값을 /health 가 그대로 내보내면 **말하기 채점이 전부 503 인 서버를
#   '정상'이라고 보고한다.** 아래 테스트들이 그 거짓 보고를 막는 자리다.
# ---------------------------------------------------------------------------


def ping_http(responder) -> httpx.Client:
    """/health 요청에 원하는 대로 답하는(또는 터지는) 가짜 통신로."""

    def handler(request: httpx.Request) -> httpx.Response:
        # ping 은 /health 만 부른다. 다른 곳을 부르면 그 자체가 잘못이다
        assert request.url.path.endswith("/health"), f"엉뚱한 곳을 불렀다: {request.url}"
        return responder(request)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_ping_은_서버가_살아_있으면_살았다고_한다():
    """모델까지 올라온 서버는 사유 없이 '살아 있음'만 돌려준다."""
    body = {"status": "ok", "model_loaded": True, "model": "whisper-small-lora-v2"}
    with ping_http(lambda req: httpx.Response(200, json=body)) as client:
        health = LoraStt(url="https://x.proxy.runpod.net", http_client=client).ping()

    assert health.alive is True
    # 정상일 때 사유를 붙이면 백엔드가 '무슨 문제가 있나' 하고 읽게 된다
    assert health.detail is None


def test_ping_은_서버가_꺼져_있으면_사유와_함께_죽었다고_한다():
    """8100 이 꺼진 지금 상태. available 은 참이어도 ping 은 거짓이어야 한다."""

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("연결이 거부되었습니다", request=request)

    stt_url = "http://127.0.0.1:8100"
    with ping_http(refuse) as client:
        stt = LoraStt(url=stt_url, http_client=client)
        # 주소는 적혀 있으므로 available 은 여전히 참이다(관문 용도라 그대로 둔다)
        assert stt.available is True
        health = stt.ping()

    assert health.alive is False
    # 사람이 읽고 무엇을 해야 할지 알 수 있는 문장인지
    assert health.detail and "닿지 못했다" in health.detail
    assert stt_url in health.detail


def test_ping_은_시간_초과와_서버_오류를_다른_사유로_구분한다():
    """무엇이 문제인지에 따라 손볼 곳이 다르므로 사유를 뭉뚱그리지 않는다."""

    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("느리다", request=request)

    with ping_http(timeout) as client:
        slow = LoraStt(url="https://x.proxy.runpod.net", http_client=client).ping()
    assert slow.alive is False
    assert "답하지 않았다" in slow.detail

    with ping_http(lambda req: httpx.Response(500, text="boom")) as client:
        broken = LoraStt(url="https://x.proxy.runpod.net", http_client=client).ping()
    assert broken.alive is False
    assert "500" in broken.detail


def test_ping_은_모델을_아직_불러오는_중이면_살았다고_하지_않는다():
    """서버는 떴는데 모델이 없으면 받아쓰기는 실패한다. 그것도 '못 쓰는 상태'다."""
    body = {"status": "loading", "model_loaded": False, "model": None}
    with ping_http(lambda req: httpx.Response(200, json=body)) as client:
        health = LoraStt(url="https://x.proxy.runpod.net", http_client=client).ping()

    assert health.alive is False
    assert "불러오는 중" in health.detail


def test_ping_은_주소가_없으면_네트워크를_건드리지_않는다():
    """물어볼 곳이 없는데 통신을 시도하면 그냥 시간만 버린다."""

    def explode(request: httpx.Request) -> httpx.Response:
        raise AssertionError("주소가 없는데 서버를 불렀다")

    with httpx.Client(transport=httpx.MockTransport(explode)) as client:
        health = LoraStt(url="", http_client=client).ping()

    assert health.alive is False
    assert LORA_STT_URL_ENV in health.detail


# ---------------------------------------------------------------------------
# 7. GET /health 가 그 결과를 정직하게 내보내는지
# ---------------------------------------------------------------------------


def health_body(monkeypatch, responder) -> dict:
    """가짜 LoRA 서버를 꽂은 채로 채점 서버의 /health 를 한 번 부른다."""
    client = ping_http(responder)
    # 이 서버에 꽂혀 있는 받아쓰기 자리를 통째로 가짜로 바꾼다.
    # 이렇게 해야 진짜 8100 을 부르지 않고도 lora 경로를 확인할 수 있다
    monkeypatch.setattr(
        api, "_active_stt", lambda: LoraStt(url="http://127.0.0.1:8100", http_client=client)
    )
    try:
        return TestClient(api.app).get("/health").json()
    finally:
        client.close()


def test_health_는_LoRA_서버가_꺼져_있으면_정상이라고_하지_않는다(monkeypatch):
    """이 테스트가 지키는 것: 죽은 서버를 '정상'이라고 보고하지 않는다."""

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("연결이 거부되었습니다", request=request)

    body = health_body(monkeypatch, refuse)

    assert body["stt_provider"] == "lora"
    assert body["stt_available"] is False
    # 왜 안 되는지가 함께 나와야 운영자가 8100 을 켤 수 있다
    assert body["stt_detail"] and "닿지 못했다" in body["stt_detail"]
    # 서버 자체는 살아 있다(쓰기 채점은 LoRA 없이도 된다)
    assert body["status"] == "ok"


def test_health_는_LoRA_서버가_살아_있으면_사유_없이_참이다(monkeypatch):
    """정상일 때 stt_detail 은 null 이다(백엔드가 있고 없음으로 분기할 수 있게)."""
    ok_body = {"status": "ok", "model_loaded": True, "model": "whisper-small-lora-v2"}
    body = health_body(monkeypatch, lambda req: httpx.Response(200, json=ok_body))

    assert body["stt_available"] is True
    assert body["stt_detail"] is None


def test_health_는_기존_필드를_하나도_잃지_않는다(monkeypatch):
    """백엔드가 보고 있는 응답이라 필드는 '추가'만 허용된다."""

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("연결이 거부되었습니다", request=request)

    body = health_body(monkeypatch, refuse)

    for key in (
        "status", "scoring_version", "llm_available", "llm_model", "llm_model_errors",
        "weights_profile", "weights_provisional", "vocab_list_provisional",
        "generation_version", "llm_model_generation",
        "stt_provider", "stt_model", "stt_available", "stt_provisional",
        "pronunciation_scoring", "pronunciation_provider",
        "auth_enabled", "auth_header", "warmed_up", "warmup_ms",
    ):
        assert key in body, f"기존 필드 {key} 가 사라졌다"


def test_health_는_ping_이_없는_제공자에서는_예전_그대로다(monkeypatch):
    """ping 이 없는 구현(gemini 등)은 열쇠 유무로 판정하던 방식 그대로다.
    (azure 는 2026-08-24 부터 ping 을 갖게 돼 lora 와 같은 실검사 길을 탄다)"""
    monkeypatch.setattr(api, "_active_stt", lambda: FakeLoraStt())
    # FakeLoraStt 는 provider_name 이 lora 지만 ping 이 없다.
    # ping 이 없는 구현에서도 /health 가 터지지 않아야 한다(다른 제공자와 같은 길)
    body = TestClient(api.app).get("/health").json()
    assert body["stt_available"] is False  # available 속성이 없으면 예전처럼 False
    assert body["stt_detail"] is None


# ---------------------------------------------------------------------------
# 7. 발음 채점이 넘어져도 채점 전체는 살아남는다 (2026-08-24 수리)
#
# 막으려는 사고:
#   받아쓰기(LoRA)는 이미 성공했는데, 그 뒤에 도는 발음 채점이 음성 파일을
#   내려받다가 실패하면 그 실패가 창구까지 그대로 올라가 **채점 전체가 400** 이
#   됐다. 응시자는 말을 제대로 했고 글자도 다 옮겨졌는데 점수가 하나도 안 나온다.
#   발음을 못 재는 것은 delivery 한 영역만 비울 일이지 채점을 세울 일이 아니다.
# ---------------------------------------------------------------------------


def failing_http(status: int = 404, content: bytes = b"") -> httpx.Client:
    """음성 파일 내려받기가 실패하는 가짜 통신로.

    404 로 답하게 하면 '주소가 죽었다', 200 + 빈 내용으로 답하게 하면
    '0바이트 파일이 왔다' 가 된다. 둘 다 AudioRequestError 로 이어지는 길이다.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, content=content, headers={"Content-Type": "audio/wav"})

    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


def exploding_http() -> httpx.Client:
    """쓰이는 순간 터지는 가짜 통신로.

    '이미 받아 둔 파일이 있으면 다시 내려받지 않는다'를 말이 아니라 사실로
    확인하는 장치다. 한 번이라도 내려받으면 여기서 시험이 실패한다.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"이미 받아 둔 파일이 있는데 또 내려받았다: {request.url}")

    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


def azure_segment(display: str = SPOKEN_TEXT) -> dict:
    """Azure 가 문장 하나를 인식했을 때 주는 JSON 모양을 흉내 낸다."""
    return {
        "Duration": 25_400_000,
        "DisplayText": display,
        "NBest": [
            {
                "Display": display,
                "PronunciationAssessment": {
                    "AccuracyScore": 66.0,
                    "FluencyScore": 90.0,
                    "CompletenessScore": 100.0,
                    "PronScore": 72.0,
                },
                "Words": [
                    {
                        "Word": "포장기가",
                        "Offset": 10_000,
                        "Duration": 20_000,
                        "PronunciationAssessment": {
                            "AccuracyScore": 43.0,
                            "ErrorType": "Mispronunciation",
                        },
                    }
                ],
            }
        ],
    }


def test_발음_평가기는_파일을_못_받아도_예외_대신_None_을_준다():
    """PronouncerPort 의 약속: 어떤 이유로 실패하든 예외를 올리지 않는다.

    예전에는 '못 알아들었다(SttUnavailable)'만 삼키고 '파일을 못 받았다
    (AudioRequestError)'는 그대로 올려서 채점 전체를 죽였다.
    """
    audio = AudioInput(url="https://storage.example.com/answers/a1.wav", format="wav")

    # 주소가 죽은 경우(404)
    with failing_http(404) as client:
        stt = AzureStt(key="시험용", region="koreacentral", http_client=client,
                       recognize=lambda **kwargs: [])
        assert stt.assess_pronunciation(audio) is None

    # 0바이트 파일이 온 경우(형식·크기 위반과 같은 갈래다)
    with failing_http(200, content=b"") as client:
        stt = AzureStt(key="시험용", region="koreacentral", http_client=client,
                       recognize=lambda **kwargs: [])
        assert stt.assess_pronunciation(audio) is None


def test_발음_평가가_음성을_못_받아도_채점_전체는_살아남는다():
    """받아쓰기는 이미 끝났다. delivery 한 영역만 비우고 점수는 나와야 한다."""
    with failing_http(404) as client:
        pronouncer = AzureStt(
            key="시험용", region="koreacentral",
            http_client=client, recognize=lambda **kwargs: [],
        )
        response = score_submission(
            speaking_request(), stt=FakeLoraStt(), pronouncer=pronouncer
        )

    # 받아쓴 글과 그 내력은 그대로 살아 있다
    assert response.meta.stt_provider == "lora"
    assert response.meta.stt_transcript == SPOKEN_TEXT
    assert response.overall_score is not None

    # 발음만 못 잰 것이므로 delivery 만 비어 있고, 그 사유가 사람 말로 남는다
    delivery = find_area(response, ScoreArea.DELIVERY)
    assert delivery.status == AreaStatus.NOT_EVALUATED
    assert delivery.weight == 0.0
    assert any("발음 평가를 하지 못해" in w for w in response.warnings)

    # 나머지 두 영역은 발음이 없을 때의 예전 비율 그대로다
    assert find_area(response, ScoreArea.CONTENT_TASK).weight == pytest.approx(0.45)
    assert find_area(response, ScoreArea.LANGUAGE_USE).weight == pytest.approx(0.55)


def test_API_발음_평가가_음성을_못_받아도_400_이_아니다(monkeypatch):
    """창구까지 올라오는지를 확인한다. 예전에는 여기서 400 이 나갔다."""
    monkeypatch.setattr("src.speech.intake.build_default_stt", lambda: FakeLoraStt())
    monkeypatch.setattr(
        "src.speech.intake.build_default_pronouncer",
        lambda: AzureStt(
            key="시험용", region="koreacentral",
            http_client=failing_http(404), recognize=lambda **kwargs: [],
        ),
    )

    payload = {
        "submission_id": "sub-lora-api-1",
        "mode": "speaking",
        "answer_text": "",
        "item": ITEM.model_dump(mode="json"),
        "audio": {"url": "https://storage.example.com/answers/a1.wav"},
        "options": {"use_llm": False},
    }
    response = TestClient(api.app).post("/score", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["stt_transcript"] == SPOKEN_TEXT
    # 음성 알맹이는 응답으로 나가지 않는다(speech 폴더 안에서만 쓰는 값이다)
    assert "fetched_audio" not in response.text


# ---------------------------------------------------------------------------
# 8. 같은 음성을 두 번 내려받지 않는다 (2026-08-24 수리)
#
# 막으려는 낭비:
#   받아쓰기(LoRA)가 음성을 내려받고, 발음 채점(Azure)이 **같은 음성을 또**
#   내려받고 있었다. 한 답안에 다운로드 두 번은 느리고 데이터도 두 배인 데다,
#   두 번째가 실패하면 위 7번의 사고로 이어진다.
# ---------------------------------------------------------------------------


def test_받아쓰기와_발음_채점이_음성을_한_번만_내려받는다():
    """진짜 LoraStt + 진짜 AzureStt 를 한 통신로에 물려 다운로드 횟수를 센다."""
    wav = make_tone_wav()
    downloads: list[str] = []
    recognized: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/transcribe"):
            # LoRA 추론 서버가 줄 법한 응답(이쪽은 음성 다운로드가 아니다)
            return httpx.Response(
                200,
                json={"text": SPOKEN_TEXT, "model": "whisper-small-lora-v2",
                      "duration_ms": 1000},
            )
        # 그 밖은 전부 음성 파일 내려받기다. 여기가 몇 번 불리는지가 이 시험의 전부다
        downloads.append(str(request.url))
        return httpx.Response(200, content=wav, headers={"Content-Type": "audio/wav"})

    def fake_recognize(pcm: bytes, reference_text: str, timeout_s: float) -> list[dict]:
        # 발음 평가가 실제로 돌았다는 것과, 넘겨받은 파일이 규격까지 제대로
        # 맞춰졌다는 것을 함께 확인한다(16000칸 * 2바이트 = 32000바이트)
        recognized.append(len(pcm))
        return [azure_segment()]

    with httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True) as client:
        response = score_submission(
            speaking_request(),
            stt=LoraStt(url="https://x.proxy.runpod.net", http_client=client),
            pronouncer=AzureStt(
                key="시험용", region="koreacentral",
                http_client=client, recognize=fake_recognize,
            ),
        )

    # 핵심: 받아쓰기 한 번 + 발음 채점 한 번인데 다운로드는 딱 한 번이다
    assert len(downloads) == 1, f"음성을 {len(downloads)}번 내려받았다: {downloads}"

    # 그러면서도 두 가지 일이 모두 제대로 끝났다
    assert recognized == [32_000]
    assert response.meta.stt_provider == "lora"
    assert response.meta.stt_transcript == SPOKEN_TEXT
    delivery = find_area(response, ScoreArea.DELIVERY)
    assert delivery.status == AreaStatus.SCORED
    assert any(ev.quote == "포장기가" for ev in delivery.evidence)


def test_받아쓰기가_준_파일이_있으면_다시_내려받지_않는다():
    """통로 자체를 좁게 확인한다. 파일을 건네주면 통신로를 건드리지도 않는다."""
    wav = make_tone_wav()
    fetched = FetchedAudio(
        data=wav, audio_format="wav", mime_type="audio/wav",
        duration_ms=1000, loudness=measure_wav_loudness(wav),
    )
    recognized: list[int] = []

    def fake_recognize(pcm: bytes, reference_text: str, timeout_s: float) -> list[dict]:
        recognized.append(len(pcm))
        return [azure_segment()]

    # 통신로는 쓰이는 순간 터지는 것을 꽂는다
    with exploding_http() as client:
        stt = AzureStt(key="시험용", region="koreacentral",
                       http_client=client, recognize=fake_recognize)
        assessment = stt.assess_pronunciation(
            AudioInput(url="https://storage.example.com/answers/a1.wav", format="wav"),
            item_prompt=ITEM.prompt,
            item_type="incident_report",
            fetched=fetched,
        )

    assert recognized == [32_000]
    assert assessment is not None
    assert assessment.accuracy == 66.0


def test_건네받은_파일도_무음_관문을_그대로_지난다():
    """1번(내려받기)만 건너뛴다. 소리를 검사하는 관문까지 면제하면 안 된다.

    면제하면 아무 말도 안 한 녹음이 발음 점수를 받는 구멍이 생긴다.
    """
    silent = make_tone_wav(amplitude=0)
    fetched = FetchedAudio(
        data=silent, audio_format="wav", mime_type="audio/wav",
        duration_ms=1000, loudness=measure_wav_loudness(silent),
    )
    called: list[int] = []

    def fake_recognize(**kwargs) -> list[dict]:
        called.append(1)
        return [azure_segment()]

    with exploding_http() as client:
        stt = AzureStt(key="시험용", region="koreacentral",
                       http_client=client, recognize=fake_recognize)
        assessment = stt.assess_pronunciation(
            AudioInput(url="https://storage.example.com/answers/a1.wav", format="wav"),
            fetched=fetched,
        )

    # 무음 관문에 걸려 Azure 를 부르지도 않았고, 발음 점수도 만들지 않았다
    assert called == []
    assert assessment is None


def test_받아쓰기_결과가_내려받은_파일을_실어_나른다():
    """LoraStt 가 파일을 담아 주지 않으면 위의 절약이 성립하지 않는다."""
    with lora_http(make_tone_wav()) as client:
        stt = LoraStt(url="https://x.proxy.runpod.net", http_client=client)
        result = stt.transcribe(AudioInput(url="https://storage.example.com/a.wav"))

    assert result.fetched_audio is not None
    assert result.fetched_audio.audio_format == "wav"
    assert result.fetched_audio.size_bytes == result.audio_bytes


def test_파일을_못_받는_옛_발음평가기도_그대로_돈다():
    """fetched 인자를 안 받는 구현에 억지로 넘기지 않는다(갈아 끼우기 보장)."""
    pronouncer = FakeAzurePronouncer(sample_assessment())

    class FetchingLoraStt(FakeLoraStt):
        """파일까지 담아 주는 받아쓰기(요즘 구현)."""

        def transcribe(self, audio, item_prompt=""):
            result = super().transcribe(audio, item_prompt)
            wav = make_tone_wav()
            result.fetched_audio = FetchedAudio(
                data=wav, audio_format="wav", mime_type="audio/wav",
                duration_ms=1000, loudness=measure_wav_loudness(wav),
            )
            return result

    # FakeAzurePronouncer 의 assess_pronunciation 은 fetched 를 받지 않는다.
    # 그래도 오류 없이 발음 채점이 끝나야 한다
    response = score_submission(
        speaking_request(), stt=FetchingLoraStt(), pronouncer=pronouncer
    )
    assert find_area(response, ScoreArea.DELIVERY).status == AreaStatus.SCORED


# ---------------------------------------------------------------------------
# 9. Azure ping — 열쇠가 '정말' 유효한지 (lora 와 같은 거짓 보고 방지)
#
# 여기서 막으려는 사고:
#   AzureStt.available 도 열쇠가 '적혀 있다'만 본다. 틀린 열쇠·정지된 구독이면
#   /health 가 정상이라고 보고한 채 발음 채점만 조용히 실패한다. lora 에서
#   고친 것과 같은 계열의 거짓 보고를 azure 에서도 막는다(2026-08-24 QA #3).
# ---------------------------------------------------------------------------


def token_http(responder) -> httpx.Client:
    """Azure 접속표(토큰) 발급 요청에 원하는 대로 답하는(또는 터지는) 가짜 통신로."""

    def handler(request: httpx.Request) -> httpx.Response:
        # azure 의 ping 은 접속표 창구만 부른다. 다른 곳을 부르면 그 자체가 잘못이다
        assert request.url.path.endswith("/sts/v1.0/issueToken"), (
            f"엉뚱한 곳을 불렀다: {request.url}"
        )
        return responder(request)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_azure_ping_은_열쇠가_유효하면_사유_없이_살았다고_한다():
    """유효한 열쇠는 접속표(200)를 받아 온다. 정상일 때 사유는 없어야 한다."""
    with token_http(lambda req: httpx.Response(200, text="token")) as client:
        health = AzureStt(key="k", region="koreacentral", http_client=client).ping()

    assert health.alive is True
    assert health.detail is None


def test_azure_ping_은_틀린_열쇠를_거절_사유와_함께_알린다():
    """열쇠가 적혀만 있는 상태. available 은 참이어도 ping 은 거짓이어야 한다."""
    with token_http(lambda req: httpx.Response(401, text="denied")) as client:
        stt = AzureStt(key="wrong", region="koreacentral", http_client=client)
        # 열쇠 문자열은 있으므로 available 은 참(관문 용도라 그대로 둔다)
        assert stt.available is True
        health = stt.ping()

    assert health.alive is False
    # 사람이 읽고 무엇을 확인해야 할지 알 수 있는 문장인지
    assert health.detail and "거절" in health.detail


def test_azure_ping_은_연결_실패를_열쇠_거절과_다른_사유로_알린다():
    """지역 오타·네트워크 차단은 열쇠 문제와 손볼 곳이 다르므로 뭉뚱그리지 않는다."""

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("연결이 거부되었습니다", request=request)

    with token_http(refuse) as client:
        health = AzureStt(key="k", region="nowhere", http_client=client).ping()

    assert health.alive is False
    assert "닿지 못했다" in health.detail


def test_azure_ping_은_열쇠가_없으면_네트워크를_건드리지_않는다():
    """물어볼 자격조차 없는데 통신을 시도하면 그냥 시간만 버린다."""

    def explode(request: httpx.Request) -> httpx.Response:
        raise AssertionError("열쇠가 없는데 Azure 를 불렀다")

    with httpx.Client(transport=httpx.MockTransport(explode)) as client:
        health = AzureStt(key="", region="", http_client=client).ping()

    assert health.alive is False
    assert "AZURE_SPEECH_KEY" in health.detail


def test_health_는_azure_제공자에서도_ping_실결과를_쓴다(monkeypatch):
    """죽은 열쇠를 꽂은 azure 서버도 이제 거짓 정상 보고를 하지 않는다."""
    client = token_http(lambda req: httpx.Response(401, text="denied"))
    monkeypatch.setattr(
        api,
        "_active_stt",
        lambda: AzureStt(key="wrong", region="koreacentral", http_client=client),
    )
    try:
        body = TestClient(api.app).get("/health").json()
    finally:
        client.close()

    assert body["stt_provider"] == "azure"
    assert body["stt_available"] is False
    assert body["stt_detail"] and "거절" in body["stt_detail"]
