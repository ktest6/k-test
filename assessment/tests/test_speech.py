"""말하기 음성 입력 회귀 테스트.

여기서 지키려는 것은 네 가지다.

  1. **음성과 글이 헷갈리지 않는다.**
     둘 다 오거나 쓰기에 음성이 붙으면 채점하지 않고 되돌려 보낸다.
     하나를 골라 쓰면 나머지가 조용히 버려지는데 응답만 봐서는 알 수 없다.
  2. **받아쓴 글이 결과에 남는다.**
     말하기 점수는 기계가 받아쓴 글에 매겨지므로, 그 글과 받아쓴 모델이
     남지 않으면 "왜 이 점수인가"에 답할 수 없다.
  3. **관문이 실제로 막는다.**
     크기·형식·주소 관문을 지나야 받아쓰기가 시작된다.
  4. **음성을 안 보내는 기존 요청은 하나도 안 바뀐다.**

이 테스트는 **네트워크를 한 번도 쓰지 않는다.**
받아쓰기는 미리 답을 정해 둔 가짜를 꽂고, 파일 내려받기는 httpx 의
가짜 통신로(MockTransport)를 쓴다. 그래서 언제 돌려도 같은 결과가 나온다.

실행: .venv\\Scripts\\python.exe -m pytest tests -q
"""

from __future__ import annotations

import io
import wave

import httpx
import pytest
from fastapi.testclient import TestClient

from src.api import app
from src.scoring.pipeline import score_submission
from src.scoring.schema import (
    AudioInput,
    ChecklistItem,
    ItemInfo,
    Mode,
    ScoreOptions,
    ScoreRequest,
)
from src.speech.audio import (
    MAX_AUDIO_BYTES,
    AudioRequestError,
    fetch_audio,
    load_local_audio,
    measure_wav_duration_ms,
    resolve_format,
)
from src.speech.intake import resolve_audio_answer
from src.speech.port import SttPort, SttUnavailable, Transcription

# ---------------------------------------------------------------------------
# 시험용 재료
# ---------------------------------------------------------------------------

# 응시자가 말할 법한 답안. 학습자 오류('안 돼습니다')를 일부러 넣었다 —
# 받아쓰기가 이것을 고치지 않고 그대로 넘기는지가 채점 정확도의 전제다.
SPOKEN_TEXT = (
    "반장님, 지금 삼번 라인 포장기가 갑자기 멈췄습니다. "
    "제가 전원 버튼을 다시 눌러 봤는데 안 돼습니다. "
    "전원을 차단하고 정비팀에 연락할까요?"
)

ITEM = ItemInfo(
    item_id="SPK-001",
    prompt="작업 중 기계가 멈췄습니다. 반장님에게 보고하고 어떻게 할지 물어보세요.",
    expected_register="formal",
    checklist=[
        ChecklistItem(id="c1", description="어떤 문제가 생겼는지 말했는가", weight=1.5),
        ChecklistItem(id="c2", description="자신이 시도한 조치를 말했는가", weight=1.0),
    ],
    reference_keywords=["기계", "멈추", "정비"],
)


def make_wav(seconds: float = 1.0, framerate: int = 24000) -> bytes:
    """길이를 아는 wav 파일을 만든다. 소리는 없어도 헤더 계산에는 지장이 없다."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(framerate)
        # 2바이트짜리 칸을 초당 framerate 개만큼 채운다
        handle.writeframes(b"\x00\x00" * int(framerate * seconds))
    return buffer.getvalue()


class FakeStt(SttPort):
    """미리 정해 둔 글을 돌려주는 가짜 받아쓰기. 네트워크를 쓰지 않는다."""

    provider_name = "fake"

    def __init__(self, text: str = SPOKEN_TEXT, duration_ms: int | None = 11400):
        self._text = text
        self._duration_ms = duration_ms
        # 무엇을 받아 갔는지 나중에 확인하려고 적어 둔다
        self.calls: list[tuple[str, str]] = []

    @property
    def model_name(self) -> str:
        return "fake-stt-v0"

    def transcribe(self, audio: AudioInput, item_prompt: str = "") -> Transcription:
        self.calls.append((audio.url, item_prompt))
        return Transcription(
            text=self._text,
            provider=self.provider_name,
            model=self.model_name,
            audio_duration_ms=self._duration_ms,
            audio_bytes=1234,
            audio_format="wav",
            elapsed_ms=12.5,
        )


class BrokenStt(FakeStt):
    """받아쓰기에 실패하는 가짜. 대체 경로가 없다는 것을 확인할 때 쓴다."""

    def transcribe(self, audio: AudioInput, item_prompt: str = "") -> Transcription:
        raise SttUnavailable("음성을 글자로 옮기지 못했다. 시험용 실패다.")


def speaking_request(**overrides) -> ScoreRequest:
    """말하기 + 음성 요청 하나를 만든다."""
    payload = {
        "submission_id": "sub-speech-1",
        "mode": Mode.SPEAKING,
        "answer_text": "",
        "item": ITEM,
        "audio": AudioInput(url="https://storage.example.com/answers/a1.wav"),
        # 실호출을 막는다. 이 테스트는 받아쓰기 배선만 본다
        "options": ScoreOptions(use_llm=False),
    }
    payload.update(overrides)
    return ScoreRequest(**payload)


def mock_http(handler) -> httpx.Client:
    """네트워크 대신 우리가 정한 답을 돌려주는 가짜 통신로를 만든다."""
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


# ---------------------------------------------------------------------------
# 1. 배선 규칙 네 가지
# ---------------------------------------------------------------------------


def test_말하기에_음성만_보내면_받아쓴_글로_채점한다():
    """새로 생긴 길. 음성 → 받아쓰기 → 기존 채점 파이프라인."""
    stt = FakeStt()
    result = score_submission(speaking_request(), stt=stt)

    # 받아쓰기가 실제로 불렸고, 문항 지시문도 함께 넘어갔다
    assert len(stt.calls) == 1
    assert stt.calls[0][0] == "https://storage.example.com/answers/a1.wav"
    assert "기계가 멈췄습니다" in stt.calls[0][1]

    # 받아쓴 글로 채점이 끝까지 갔다
    assert result.overall_score is not None
    assert result.meta.answer_valid is True


def test_글과_음성이_둘_다_오면_거절한다():
    """어느 쪽이 답안인지 알 수 없는 요청은 채점하지 않는다.

    하나를 골라 쓰면 나머지 하나가 조용히 버려지고,
    그 답안은 아무 말 없이 다른 글로 채점된다.
    """
    request = speaking_request(answer_text="제가 직접 친 글입니다.")
    with pytest.raises(AudioRequestError) as caught:
        score_submission(request, stt=FakeStt())
    assert "answer_text" in str(caught.value)


def test_쓰기_답안에_음성을_붙이면_거절한다():
    """쓰기는 응시자가 직접 친 글의 맞춤법까지 보는 채점이라 음성이 성립하지 않는다."""
    request = speaking_request(mode=Mode.WRITING)
    with pytest.raises(AudioRequestError) as caught:
        score_submission(request, stt=FakeStt())
    assert "쓰기" in str(caught.value)


def test_음성도_글도_없으면_기존_가드가_처리한다():
    """음성이 없으면 이 기능은 아무 일도 하지 않고 지금까지의 길로 간다."""
    request = speaking_request(audio=None, answer_text="")
    result = score_submission(request, stt=FakeStt())

    # 빈 답안은 예외가 아니라 '채점 무효'로 나간다(기존 동작)
    assert result.meta.answer_valid is False
    assert result.overall_score is None
    # 받아쓰기를 안 했으므로 관련 값은 전부 비어 있다
    assert result.meta.stt_provider is None


def test_받아쓰기에_실패하면_대체_경로_없이_예외가_올라간다():
    """못 알아들은 말을 지어내면 응시자가 하지 않은 말로 점수를 받는다."""
    with pytest.raises(SttUnavailable):
        score_submission(speaking_request(), stt=BrokenStt())


def test_빈_글을_받아쓰면_실패로_다룬다():
    """'말을 안 한 답안'과 '받아쓰기 실패'는 다른 상태다. 섞으면 안 된다."""
    with pytest.raises(SttUnavailable):
        resolve_audio_answer(speaking_request(), stt=FakeStt(text="   "))


# ---------------------------------------------------------------------------
# 2. 받아쓴 내력이 결과에 남는가
# ---------------------------------------------------------------------------


def test_받아쓴_글과_모델이_결과에_남는다():
    """점수만 남기고 근거를 버리면 이의 제기에 답할 수 없다."""
    result = score_submission(speaking_request(), stt=FakeStt())
    meta = result.meta

    assert meta.stt_provider == "fake"
    assert meta.stt_model == "fake-stt-v0"
    assert meta.audio_duration_ms == 11400
    # 채점 대상이 된 글이 그대로 남아 있어야 한다
    assert meta.stt_transcript == SPOKEN_TEXT
    # 걸린 시간도 남는다
    assert "stt_ms" in meta.timings_ms


def test_받아쓴_글로_채점했다는_사실이_경고에_남는다():
    """결과를 보는 사람이 '이 점수는 기계가 받아쓴 글에 매겨졌다'를 알아야 한다."""
    result = score_submission(speaking_request(), stt=FakeStt())
    assert any("받아쓴 글을 채점했다" in warning for warning in result.warnings)


def test_받아쓴_글이_가드에_걸려도_그_글이_남는다():
    """무효 판정이 나도 받아쓴 글은 남겨야 원인을 가릴 수 있다.

    이 글이 없으면 '응시자가 이상하게 말한 것'인지
    '받아쓰기가 실패한 것'인지 나중에 구별할 방법이 없다.
    """
    # 한국어가 아닌 글이 받아써진 경우 (기존 하드 가드에 걸린다)
    result = score_submission(
        speaking_request(), stt=FakeStt(text="hello this is not korean at all")
    )
    assert result.meta.answer_valid is False
    assert result.meta.stt_transcript == "hello this is not korean at all"
    assert result.meta.stt_provider == "fake"


def test_전사_보정_흐름을_그대로_탄다():
    """받아쓴 글은 기존 STT 보정 흐름으로 그대로 들어간다.

    보정을 켜면 보정본이 내용 채점에 쓰이고, 문법은 받아쓴 원문으로 채점한다.
    (여기서는 LLM 을 끄고 도는 길이라 보정은 일어나지 않지만,
     보정 단계를 지나갔다는 사실은 확인된다)
    """
    from src.scoring.schema import TranscriptInput

    result = score_submission(
        speaking_request(transcript=TranscriptInput(correct=True, nationality="베트남")),
        stt=FakeStt(),
    )
    # 받아쓴 글이 보정 단계까지 갔다(LLM 을 껐으므로 보정 자체는 일어나지 않는다)
    assert result.meta.stt_transcript == SPOKEN_TEXT
    assert result.meta.transcript_correction_applied is False


# ---------------------------------------------------------------------------
# 3. 기존 요청이 그대로인가
# ---------------------------------------------------------------------------


def test_음성을_안_보내는_기존_요청은_하나도_안_바뀐다():
    """추가 전용이라는 말이 맞는지 값으로 확인한다."""
    request = ScoreRequest(
        submission_id="sub-old",
        mode=Mode.WRITING,
        answer_text=(
            "오늘 삼번 라인에서 포장 작업을 하였습니다. 작업 전에 안전모를 착용했습니다. "
            "선반이 기울어져 있어서 반장님께 말씀드렸습니다."
        ),
        item=ITEM,
        options=ScoreOptions(use_llm=False),
    )
    result = score_submission(request)

    assert result.overall_score is not None
    # 받아쓰기 관련 값은 전부 비어 있다
    assert result.meta.stt_provider is None
    assert result.meta.stt_model is None
    assert result.meta.audio_duration_ms is None
    assert result.meta.stt_transcript is None
    assert "stt_ms" not in result.meta.timings_ms


def test_answer_text_기본값이_생겨도_기존_요청은_그대로다():
    """answer_text 를 안 보내는 것이 가능해졌지만, 보내면 그 글을 채점한다."""
    # 음성도 글도 없는 요청이 만들어지기는 한다(기존 가드가 무효로 처리한다)
    request = ScoreRequest(submission_id="s", mode=Mode.WRITING, item=ITEM)
    assert request.answer_text == ""
    assert request.audio is None


# ---------------------------------------------------------------------------
# 4. 파일 관문 (크기·형식·주소)
# ---------------------------------------------------------------------------


def test_형식은_요청_확장자_서버_순서로_정한다():
    """앞의 것이 있으면 뒤는 보지 않는다."""
    # 1) 요청이 직접 알려 준 형식이 가장 우선이다
    audio = AudioInput(url="https://x.test/a.wav", format="mp3")
    assert resolve_format(audio, "audio/wav") == "mp3"

    # 2) 요청에 없으면 주소 끝의 확장자를 본다(물음표 뒤는 뗀다)
    audio = AudioInput(url="https://x.test/a.m4a?token=abc123")
    assert resolve_format(audio) == "m4a"

    # 3) 확장자도 없으면 파일을 준 서버가 붙인 형식을 본다
    audio = AudioInput(url="https://x.test/download")
    assert resolve_format(audio, "audio/webm; codecs=opus") == "webm"


def test_모르는_형식은_찍어서_읽지_않고_막는다():
    """엉뚱한 형식으로 읽으면 받아쓴 글이 조용히 엉망이 되고 그것이 점수로 나타난다."""
    with pytest.raises(AudioRequestError) as caught:
        resolve_format(AudioInput(url="https://x.test/a.flac"))
    assert "형식" in str(caught.value)

    with pytest.raises(AudioRequestError):
        resolve_format(AudioInput(url="https://x.test/a", format="aiff"))


def test_http가_아닌_주소는_열지_않는다():
    """서버 안의 파일을 읽어 가는 통로가 되면 안 된다."""
    for url in ("file:///C:/Windows/win.ini", "ftp://x.test/a.wav"):
        with pytest.raises(AudioRequestError) as caught:
            fetch_audio(AudioInput(url=url))
        assert "http" in str(caught.value)


def test_너무_큰_파일은_받다가_끊는다():
    """서버가 크기를 안 알려 줘도 받으면서 세기 때문에 막힌다."""
    big = b"\x00" * (MAX_AUDIO_BYTES + 1024)

    def handler(request: httpx.Request) -> httpx.Response:
        # 일부러 크기를 안 알려 주는 서버를 흉내 낸다
        return httpx.Response(200, content=big, headers={"content-type": "audio/wav"})

    with mock_http(handler) as client:
        with pytest.raises(AudioRequestError) as caught:
            fetch_audio(AudioInput(url="https://x.test/big.wav"), http_client=client)
    assert "20MB" in str(caught.value)


def test_크기를_미리_알려_주면_받기_전에_막는다():
    """Content-Length 로 넘치는 것이 확인되면 내려받지 않는다."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"\x00" * 10,
            headers={
                "content-type": "audio/wav",
                "content-length": str(MAX_AUDIO_BYTES + 1),
            },
        )

    with mock_http(handler) as client:
        with pytest.raises(AudioRequestError) as caught:
            fetch_audio(AudioInput(url="https://x.test/big.wav"), http_client=client)
    assert "크다" in str(caught.value)


def test_파일이_없으면_사유를_한국어로_알려_준다():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    with mock_http(handler) as client:
        with pytest.raises(AudioRequestError) as caught:
            fetch_audio(AudioInput(url="https://x.test/none.wav"), http_client=client)
    assert "404" in str(caught.value)


def test_내려받기가_실패하면_받아쓰기_실패로_다룬다():
    """요청이 틀린 것이 아니라 잠시 뒤에는 될 수 있는 상황이라 400 이 아니다."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("시험용 시간 초과")

    with mock_http(handler) as client:
        with pytest.raises(SttUnavailable) as caught:
            fetch_audio(AudioInput(url="https://x.test/slow.wav"), http_client=client)
    assert "내려받지 못했다" in str(caught.value)


def test_빈_파일은_받아쓰기로_넘기지_않는다():
    """빈 소리를 넘기면 LLM 이 거기에 대고 문장을 지어낸다."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"", headers={"content-type": "audio/wav"})

    with mock_http(handler) as client:
        with pytest.raises(AudioRequestError) as caught:
            fetch_audio(AudioInput(url="https://x.test/empty.wav"), http_client=client)
    assert "비어 있다" in str(caught.value)


def test_정상_wav_는_형식과_길이가_함께_나온다():
    data = make_wav(seconds=2.0)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=data, headers={"content-type": "audio/wav"})

    with mock_http(handler) as client:
        fetched = fetch_audio(AudioInput(url="https://x.test/a.wav"), http_client=client)

    assert fetched.audio_format == "wav"
    assert fetched.mime_type == "audio/wav"
    assert fetched.duration_ms == 2000
    assert fetched.size_bytes == len(data)


def test_wav가_아니면_요청이_알려_준_길이를_쓴다():
    """압축 형식은 파일을 풀어 봐야 길이를 알 수 있어서 우리가 재지 않는다."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"fake-mp3-bytes",
                              headers={"content-type": "audio/mpeg"})

    with mock_http(handler) as client:
        # 길이를 알려 준 경우
        fetched = fetch_audio(
            AudioInput(url="https://x.test/a.mp3", duration_ms=9000), http_client=client
        )
        assert fetched.duration_ms == 9000

        # 안 알려 준 경우에는 없는 대로 두고 사람이 알 수 있게 남긴다
        fetched = fetch_audio(AudioInput(url="https://x.test/a.mp3"), http_client=client)
        assert fetched.duration_ms is None
        assert any("길이를 재지 못한다" in w for w in fetched.warnings)


def test_wav_길이는_파일에서_직접_잰다():
    assert measure_wav_duration_ms(make_wav(seconds=1.5)) == 1500
    # wav 가 아니면 못 재고, 그때 채점을 멈추지는 않는다
    assert measure_wav_duration_ms(b"not a wav at all") is None


def test_로컬_파일_읽기는_확인용_경로다(tmp_path):
    """스크립트 전용 통로. 채점 요청은 이 길로 오지 않는다."""
    path = tmp_path / "sample.wav"
    path.write_bytes(make_wav(seconds=0.5))

    fetched = load_local_audio(path)
    assert fetched.audio_format == "wav"
    assert fetched.duration_ms == 500

    with pytest.raises(AudioRequestError):
        load_local_audio(tmp_path / "없는파일.wav")


# ---------------------------------------------------------------------------
# 5. API 창구 (상태 코드가 계약대로 나가는가)
# ---------------------------------------------------------------------------


client = TestClient(app)


def base_payload(**overrides) -> dict:
    payload = {
        "submission_id": "sub-api-1",
        "mode": "speaking",
        "answer_text": "",
        "item": {"item_id": "SPK-001", "prompt": "기계가 멈췄습니다. 보고하세요."},
        "audio": {"url": "https://storage.example.com/a.wav"},
        "options": {"use_llm": False},
    }
    payload.update(overrides)
    return payload


def test_API_글과_음성이_둘_다_오면_400():
    response = client.post("/score", json=base_payload(answer_text="직접 친 글입니다."))
    assert response.status_code == 400
    assert "answer_text" in response.json()["detail"]


def test_API_쓰기에_음성을_붙이면_400():
    response = client.post("/score", json=base_payload(mode="writing"))
    assert response.status_code == 400
    assert "쓰기" in response.json()["detail"]


def test_API_받아쓰기에_실패하면_503(monkeypatch):
    """받아쓰기에는 대체 경로가 없다. 지어낸 글로 채점하지 않는다."""
    monkeypatch.setattr("src.speech.intake.build_default_stt", lambda: BrokenStt())
    response = client.post("/score", json=base_payload())
    assert response.status_code == 503
    assert "옮기지 못했다" in response.json()["detail"]


def test_API_음성으로_채점하면_받아쓴_글이_응답에_있다(monkeypatch):
    monkeypatch.setattr("src.speech.intake.build_default_stt", lambda: FakeStt())
    response = client.post("/score", json=base_payload())
    assert response.status_code == 200

    meta = response.json()["meta"]
    assert meta["stt_provider"] == "fake"
    assert meta["stt_model"] == "fake-stt-v0"
    assert meta["stt_transcript"] == SPOKEN_TEXT
    assert meta["audio_duration_ms"] == 11400


def test_API_음성_계약이_features_에_공개된다():
    """백엔드가 크기·형식 한도를 코드에 베껴 넣지 않게 열어 둔다."""
    payload = client.get("/features").json()["speech_input"]
    assert payload["request_field"] == "audio"
    assert set(payload["allowed_formats"]) == {"wav", "webm", "mp3", "m4a", "ogg"}
    assert payload["max_bytes"] == MAX_AUDIO_BYTES
    assert "stt_transcript" in payload["meta_fields"]


def test_API_health_가_받아쓰기_상태를_알려_준다():
    payload = client.get("/health").json()
    assert payload["stt_provider"] == "gemini"
    # Azure 가 아니라 임시 구현이라는 사실이 드러나야 한다
    assert payload["stt_provisional"] is True


# ---------------------------------------------------------------------------
# 6. 갈아 끼울 수 있는 구조인가
# ---------------------------------------------------------------------------


def test_받아쓰기_구현은_포트만_지키면_갈아_끼워진다():
    """Azure 가 나오면 이 자리에 AzureStt 가 꽂힌다.

    가짜 구현이 SttPort 만 지켰는데 채점이 끝까지 도는 것으로
    '구현을 바꿔도 채점은 안 바뀐다'가 말이 아니라 사실이 된다.
    """
    assert issubclass(FakeStt, SttPort)
    result = score_submission(speaking_request(), stt=FakeStt(text="안녕하세요. 기계가 멈췄습니다."))
    assert result.meta.stt_provider == "fake"


def test_채점_코드는_받아쓰기_모델을_직접_부르지_않는다():
    """단방향 의존을 코드로 못 박는다.

    채점(features/·llm/)이 speech 를 직접 부르기 시작하면
    '음성 기능을 붙였다고 채점이 달라지지 않는다'가 성립하지 않는다.
    배선은 scoring/pipeline.py 한 곳에만 있어야 한다.
    """
    from pathlib import Path

    src = Path(__file__).resolve().parent.parent / "src"
    offenders = []
    for folder in ("features", "llm"):
        for path in (src / folder).glob("**/*.py"):
            if "speech" in path.read_text(encoding="utf-8"):
                offenders.append(str(path))
    assert offenders == [], f"채점 자질 쪽 파일이 speech 를 참조한다: {offenders}"

    # scoring 쪽에서 speech 를 부르는 곳은 pipeline.py 하나뿐이어야 한다
    scoring_offenders = [
        path.name
        for path in (src / "scoring").glob("**/*.py")
        if "speech" in path.read_text(encoding="utf-8")
    ]
    assert scoring_offenders == ["pipeline.py"], (
        f"speech 배선이 pipeline.py 밖으로 번졌다: {scoring_offenders}"
    )
