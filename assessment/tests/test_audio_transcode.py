"""브라우저 녹음(webm)을 입구에서 wav 로 바꾸는 관문의 회귀 테스트.

**왜 이것을 못 박는가 (2026-08-30 시연 장애).**
백엔드가 저장소에 올리는 응시자 음성은 브라우저가 녹음한 **webm** 이다. 그런데
받아쓰기 서버도 발음 평가(Azure)도 소리 크기 재기도 wav 만 읽을 줄 알아서,
말하기 답안이 전부 "받아쓰기 실패(503)"로 떨어졌다. 게다가 겉으로 보이는 것은
"LoRA 서버가 500 으로 답했다"뿐이라 진짜 원인(형식)이 보이지 않았다.

그래서 파일이 들어오는 자리(`fetch_audio`)에서 **딱 한 번** 16kHz 모노 wav 로
바꾸도록 고쳤다. 이 테스트가 지키는 것은 네 가지다.

  1. 형식은 **선언이 아니라 알맹이**로 판단한다 (확장자가 `.wav` 여도 속 내용을 본다)
  2. 바꾼 뒤에는 길이·소리 크기가 새 wav 기준으로 다시 채워진다
  3. 바꾸지 못하면 **조용히 넘기지 않고** 사유를 담아 503 으로 알린다
  4. 이미 wav 인 파일은 건드리지 않는다 (지금 도는 대부분의 답안이 이 길이다)

이 테스트는 **ffmpeg 가 깔려 있지 않아도 전부 돈다.** 변환기를 부르는 자리
(`subprocess.run`)를 미리 답을 정해 둔 가짜로 바꿔 끼우기 때문이다. 진짜 ffmpeg 로
왕복시켜 보는 시험은 맨 아래 하나뿐이고, 없는 PC 에서는 저절로 건너뛴다.

실행: (assessment 폴더에서) ..\\.venv\\Scripts\\python.exe -m pytest tests -q
"""

from __future__ import annotations

import io
import math
import shutil
import subprocess
import sys
import wave
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from src.api import app
from src.scoring.messages import MESSAGE_CATALOG
from src.scoring.schema import AudioInput
from src.speech import audio as audio_module
from src.speech.audio import (
    TARGET_CHANNELS,
    TARGET_SAMPLE_RATE,
    FetchedAudio,
    ensure_wav,
    fetch_audio,
    ffmpeg_available,
    ffmpeg_executable,
    sniff_format,
    transcode_to_wav,
)
from src.speech.port import SttUnavailable

# ---------------------------------------------------------------------------
# 시험용 재료
# ---------------------------------------------------------------------------


def make_tone_wav(
    seconds: float = 1.0,
    framerate: int = TARGET_SAMPLE_RATE,
    amplitude: int = 12000,
) -> bytes:
    """'삐-' 소리가 든 wav 를 만든다.

    무음이 아닌 소리를 쓰는 이유: 변환 뒤에 소리 크기(loudness)가 다시 채워지는지
    확인해야 하는데, 전부 0인 파일로는 '재긴 했는데 0'과 '못 쟀다'를 구별할 수 없다.
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


#: 브라우저 녹음 파일의 앞머리(EBML 표식)를 흉내 낸 알맹이.
#: 진짜 webm 은 아니지만, 우리 코드가 형식을 알아보는 근거는 이 표식뿐이라
#: 판별과 변환 호출을 시험하는 데는 이것으로 충분하다(변환기는 가짜로 바꿔 끼운다).
FAKE_WEBM = b"\x1a\x45\xdf\xa3" + b"\x00" * 200
FAKE_M4A = b"\x00\x00\x00\x20ftypM4A " + b"\x00" * 200
FAKE_OGG = b"OggS" + b"\x00" * 200
FAKE_MP3_ID3 = b"ID3\x04\x00\x00" + b"\x00" * 200
FAKE_MP3_SYNC = b"\xff\xfb\x90\x00" + b"\x00" * 200


def mock_http(content: bytes, content_type: str) -> httpx.Client:
    """네트워크 대신 우리가 정한 파일을 돌려주는 가짜 통신로."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=content, headers={"content-type": content_type})

    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


def 있는척(monkeypatch) -> None:
    """ffmpeg 가 '있는' 상태를 만든다.

    진짜 ffmpeg 를 깔지 않고도 '실행파일이 있다'를 만들려고, 이 PC 에 반드시 있는
    파이썬 실행파일의 자리를 KTEST_FFMPEG 로 알려 준다. 실제로 부르는 자리
    (subprocess.run)는 어차피 가짜로 바꿔 끼우므로 무엇을 가리켜도 상관없다.
    """
    monkeypatch.setenv("KTEST_FFMPEG", sys.executable)


def 없는척(monkeypatch) -> None:
    """ffmpeg 가 '없는' 상태를 만든다(어디에도 없는 이름을 가리킨다)."""
    monkeypatch.setenv("KTEST_FFMPEG", "이런-이름의-실행파일은-없다-ktest")


def 가짜변환기(monkeypatch, *, stdout=b"", stderr=b"", returncode=0, raises=None) -> list:
    """`subprocess.run` 을 가짜로 바꿔 끼우고, 넘어온 인자를 담아 둘 목록을 준다.

    돌려주는 목록에는 부를 때 쓴 인자가 그대로 쌓인다. 그래서 "16kHz 모노로
    불렀는가", "아예 부르지 않았는가"를 말이 아니라 사실로 확인할 수 있다.
    """
    호출기록: list = []

    def fake_run(argv, **kwargs):
        호출기록.append({"argv": argv, **kwargs})
        # 실행 실패·시간 초과를 흉내 내야 하는 시험에서는 여기서 예외를 던진다
        if raises is not None:
            raise raises
        return subprocess.CompletedProcess(argv, returncode, stdout=stdout, stderr=stderr)

    monkeypatch.setattr(audio_module.subprocess, "run", fake_run)
    return 호출기록


# ---------------------------------------------------------------------------
# 1. 매직바이트로 형식을 알아내는가
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "알맹이,기대",
    [
        (make_tone_wav(seconds=0.1), "wav"),
        (FAKE_WEBM, "webm"),
        (FAKE_M4A, "m4a"),
        (FAKE_OGG, "ogg"),
        (FAKE_MP3_ID3, "mp3"),
        (FAKE_MP3_SYNC, "mp3"),
    ],
)
def test_파일_앞머리만_보고_형식을_알아낸다(알맹이, 기대):
    """형식 이름은 거짓말을 하므로 알맹이의 표식으로 판단해야 한다."""
    assert sniff_format(알맹이) == 기대


def test_모르는_알맹이는_모른다고_답한다():
    """찍어서 형식을 정하면 엉뚱한 소리를 채점하게 된다. 모르면 모른다고 한다."""
    assert sniff_format("이건 소리가 아니라 그냥 글자다".encode("utf-8")) is None
    # 표식이 들어갈 만큼 길지도 않은 경우
    assert sniff_format(b"RIFF") is None
    assert sniff_format(b"") is None


def test_RIFF_로_시작해도_WAVE_가_아니면_wav_가_아니다():
    """RIFF 는 wav 말고 다른 형식(avi 등)도 쓰는 껍데기라 뒤까지 봐야 한다."""
    assert sniff_format(b"RIFF\x00\x00\x00\x00AVI " + b"\x00" * 20) is None


# ---------------------------------------------------------------------------
# 2. 변환 성공 경로
# ---------------------------------------------------------------------------


def test_16kHz_모노_wav_로_불러_변환한다(monkeypatch):
    """변환 규격이 어긋나면 받아쓰기 정확도가 조용히 떨어진다. 인자를 못 박는다."""
    있는척(monkeypatch)
    바뀐wav = make_tone_wav(seconds=0.5)
    기록 = 가짜변환기(monkeypatch, stdout=바뀐wav)

    결과 = transcode_to_wav(FAKE_WEBM, "webm")

    assert 결과 == 바뀐wav
    assert len(기록) == 1
    argv = 기록[0]["argv"]
    # 입력·출력을 파일이 아니라 파이프로 주고받는다(응시자 음성을 디스크에 남기지 않는다)
    assert "pipe:0" in argv and "pipe:1" in argv
    # 모노 · 16kHz · wav
    assert argv[argv.index("-ac") + 1] == str(TARGET_CHANNELS)
    assert argv[argv.index("-ar") + 1] == str(TARGET_SAMPLE_RATE)
    assert argv[argv.index("-f") + 1] == "wav"
    # 원본 알맹이를 그대로 밀어 넣는다
    assert 기록[0]["input"] == FAKE_WEBM


def test_webm_은_입구에서_wav_로_바뀌어_나온다(monkeypatch):
    """장애의 본줄기. 브라우저 녹음이 들어와도 뒤쪽에는 wav 만 넘어가야 한다."""
    있는척(monkeypatch)
    바뀐wav = make_tone_wav(seconds=2.0)
    가짜변환기(monkeypatch, stdout=바뀐wav)

    with mock_http(FAKE_WEBM, "audio/webm") as client:
        fetched = fetch_audio(
            AudioInput(url="https://x.test/answer.webm"), http_client=client
        )

    # 알맹이·형식·MIME 이 전부 새 wav 기준으로 바뀌어 있다
    assert fetched.audio_format == "wav"
    assert fetched.mime_type == "audio/wav"
    assert fetched.data == 바뀐wav
    # 원래 무엇이었는지는 잃지 않는다(채점 근거를 되짚을 때 필요하다)
    assert fetched.source_format == "webm"
    # 길이와 소리 크기도 새 wav 에서 다시 쟀다.
    # 예전에는 압축 형식이면 둘 다 비어서 무음 관문이 통째로 건너뛰어졌다
    assert fetched.duration_ms == 2000
    assert fetched.loudness is not None
    assert fetched.loudness.peak_window_rms > 0


def test_바꿨다는_사실이_경고와_코드에_함께_남는다(monkeypatch):
    """무엇을 채점했는지 추적할 수 없으면 근거 없는 점수가 된다."""
    있는척(monkeypatch)
    가짜변환기(monkeypatch, stdout=make_tone_wav(seconds=0.5))

    with mock_http(FAKE_M4A, "audio/mp4") as client:
        fetched = fetch_audio(AudioInput(url="https://x.test/a.m4a"), http_client=client)

    # 한국어 문장(예전 방식)과 코드(새 방식)가 짝을 이뤄 하나씩 쌓인다
    assert len(fetched.warnings) == len(fetched.notices) == 1
    assert "m4a" in fetched.warnings[0]
    assert fetched.notices[0].code == "AUDIO_TRANSCODED_TO_WAV"
    assert fetched.notices[0].params == {"sourceFormat": "m4a"}


def test_확장자가_wav_라고_적혀_있어도_알맹이가_webm_이면_바꾼다(monkeypatch):
    """실제 장애가 이 모양이었다. 선언을 믿으면 그대로 500 으로 이어진다."""
    있는척(monkeypatch)
    가짜변환기(monkeypatch, stdout=make_tone_wav(seconds=1.0))

    with mock_http(FAKE_WEBM, "audio/wav") as client:
        fetched = fetch_audio(
            AudioInput(url="https://x.test/answer.wav", format="wav"), http_client=client
        )

    assert fetched.audio_format == "wav"
    assert fetched.source_format == "webm"


def test_이미_wav_면_변환기를_부르지도_않는다(monkeypatch):
    """지금 도는 답안 대부분이 이 길이다. 공연히 한 번 더 거치면 소리만 상한다."""
    있는척(monkeypatch)

    def 부르면실패(*args, **kwargs):
        raise AssertionError("이미 wav 인데 변환기를 불렀다")

    monkeypatch.setattr(audio_module.subprocess, "run", 부르면실패)

    원본 = make_tone_wav(seconds=1.5)
    with mock_http(원본, "audio/wav") as client:
        fetched = fetch_audio(AudioInput(url="https://x.test/a.wav"), http_client=client)

    assert fetched.data == 원본
    assert fetched.audio_format == "wav"
    # 바꾸지 않았으므로 원래 형식도 wav 이고, 경고도 붙지 않는다
    assert fetched.source_format == "wav"
    assert fetched.warnings == []


# ---------------------------------------------------------------------------
# 3. 변환 실패 경로 — 조용히 넘어가지 않는다
# ---------------------------------------------------------------------------


def test_ffmpeg_가_없으면_사유를_담아_503_으로_막힌다(monkeypatch):
    """여기서 원본을 그대로 흘려보내면 뒤에서 깨지고 원인이 안 보인다."""
    없는척(monkeypatch)

    with mock_http(FAKE_WEBM, "audio/webm") as client:
        with pytest.raises(SttUnavailable) as caught:
            fetch_audio(AudioInput(url="https://x.test/a.webm"), http_client=client)

    made = caught.value.notice
    assert made.code == "STT_AUDIO_TRANSCODE_FAILED"
    assert made.params["format"] == "webm"
    assert "ffmpeg" in made.params["reason"]
    # 화면에 뜰 문장에도 무엇을 해야 하는지가 적혀 있어야 한다
    assert "ffmpeg" in made.message


def test_ffmpeg_가_실패하면_그_사유를_옮겨_담는다(monkeypatch):
    """'변환 실패' 한마디만 남으면 서버에서 원인을 다시 찾아야 한다."""
    있는척(monkeypatch)
    가짜변환기(
        monkeypatch,
        returncode=1,
        stderr="pipe:0: Invalid data found when processing input".encode("utf-8"),
    )

    with pytest.raises(SttUnavailable) as caught:
        transcode_to_wav(FAKE_WEBM, "webm")

    made = caught.value.notice
    assert made.code == "STT_AUDIO_TRANSCODE_FAILED"
    assert "Invalid data" in made.params["reason"]


def test_ffmpeg_사유가_길어도_한_줄_길이로_자른다(monkeypatch):
    """진단 덤프가 통째로 응답에 실리면 사람이 읽는 문구가 아니게 된다."""
    있는척(monkeypatch)
    가짜변환기(monkeypatch, returncode=1, stderr=b"x" * 5000)

    with pytest.raises(SttUnavailable) as caught:
        transcode_to_wav(FAKE_WEBM, "webm")

    assert len(caught.value.notice.params["reason"]) < 300


def test_변환이_시간을_넘기면_기다리지_않고_끊는다(monkeypatch):
    """멈춰 선 변환기를 하염없이 기다리면 채점 서버가 통째로 막힌다."""
    있는척(monkeypatch)
    가짜변환기(monkeypatch, raises=subprocess.TimeoutExpired(cmd="ffmpeg", timeout=60))

    with pytest.raises(SttUnavailable) as caught:
        transcode_to_wav(FAKE_WEBM, "webm")

    made = caught.value.notice
    assert made.code == "STT_AUDIO_TRANSCODE_FAILED"
    assert "60초" in made.params["reason"]


def test_실행파일이_사라진_경우도_같은_코드로_알린다(monkeypatch):
    """찾을 때는 있었는데 부를 때 없는 경우(경로가 잘못 잡힌 때)다."""
    있는척(monkeypatch)
    가짜변환기(monkeypatch, raises=FileNotFoundError("ffmpeg 없음"))

    with pytest.raises(SttUnavailable) as caught:
        transcode_to_wav(FAKE_WEBM, "webm")

    assert caught.value.notice.code == "STT_AUDIO_TRANSCODE_FAILED"


def test_변환_결과가_wav_가_아니면_성공으로_치지_않는다(monkeypatch):
    """빈 알맹이를 그대로 넘기면 '소리가 없는 답안'으로 둔갑한다."""
    있는척(monkeypatch)
    가짜변환기(monkeypatch, returncode=0, stdout=b"")

    with pytest.raises(SttUnavailable) as caught:
        transcode_to_wav(FAKE_WEBM, "webm")

    assert caught.value.notice.code == "STT_AUDIO_TRANSCODE_FAILED"
    assert "wav 가 아니다" in caught.value.notice.params["reason"]


def test_새_코드가_카탈로그에_등록돼_있다():
    """코드만 만들고 카탈로그에 안 넣으면 백엔드가 영어 문장을 못 찾는다."""
    for code in ("STT_AUDIO_TRANSCODE_FAILED", "AUDIO_TRANSCODED_TO_WAV"):
        assert code in MESSAGE_CATALOG


# ---------------------------------------------------------------------------
# 4. 서버 상태에 드러나는가
# ---------------------------------------------------------------------------


def test_health_가_형식_변환_가능_여부를_알려_준다():
    """이 값이 false 면 말하기 채점이 전부 503 이라는 뜻이라 배포 직후 봐야 한다."""
    client = TestClient(app)
    payload = client.get("/health").json()
    assert "ffmpeg_available" in payload
    assert isinstance(payload["ffmpeg_available"], bool)
    # 짐작이 아니라 실제로 실행파일을 찾아본 결과와 같아야 한다
    assert payload["ffmpeg_available"] == ffmpeg_available()


def test_환경변수로_실행파일_자리를_알려_줄_수_있다(monkeypatch):
    """윈도우처럼 자리가 제각각인 곳에서 코드를 고치지 않고 알려 주는 통로다."""
    monkeypatch.setenv("KTEST_FFMPEG", sys.executable)
    assert ffmpeg_executable() == shutil.which(sys.executable)
    assert ffmpeg_available() is True

    monkeypatch.setenv("KTEST_FFMPEG", "이런-이름의-실행파일은-없다-ktest")
    assert ffmpeg_executable() is None
    assert ffmpeg_available() is False


# ---------------------------------------------------------------------------
# 5. 진짜 ffmpeg 로 한 번 왕복시켜 보기 (없는 PC 에서는 건너뛴다)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None,
    reason="이 PC 에 ffmpeg 가 없다. 변환 경로는 위의 가짜 변환기 시험으로 확인한다",
)
def test_진짜_ffmpeg_로_wav_webm_wav_왕복이_된다(tmp_path: Path):
    """가짜가 아니라 실제 변환기로 한 번은 끝까지 돌려 본다.

    wav → webm(opus) → 우리 변환 경로 → wav 로 돌아왔을 때, 길이가 거의 그대로이고
    소리가 살아 있는지만 본다(소리가 얼마나 상했는지는 scripts/check_transcode.py 가 잰다).
    """
    원본 = make_tone_wav(seconds=2.0)
    webm_path = tmp_path / "answer.webm"

    # wav 를 브라우저 녹음과 같은 형식(webm/opus)으로 만든다
    done = subprocess.run(
        [shutil.which("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
         "-i", "pipe:0", "-c:a", "libopus", str(webm_path)],
        input=원본,
        capture_output=True,
        timeout=120,
    )
    if done.returncode != 0:
        pytest.skip(f"이 ffmpeg 로는 webm(opus) 을 만들 수 없다: {done.stderr[-200:]!r}")

    webm = webm_path.read_bytes()
    assert sniff_format(webm) == "webm"

    # 우리 변환 경로(fetch_audio 가 부르는 그 함수)를 그대로 태운다
    fetched = ensure_wav(
        FetchedAudio(data=webm, audio_format="webm", mime_type="audio/webm")
    )

    assert fetched.audio_format == "wav"
    assert fetched.source_format == "webm"
    # 길이가 크게 달라지면 뒷부분이 잘린 것이다(0.2초까지만 봐준다)
    assert abs((fetched.duration_ms or 0) - 2000) < 200
    # 소리가 살아 있어야 한다. 0 이면 변환이 소리를 날린 것이다
    assert fetched.loudness is not None and fetched.loudness.peak_window_rms > 100
