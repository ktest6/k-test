"""음성 파일을 안전하게 손에 넣는 일만 하는 파일.

받아쓰기(STT)를 부르기 전에 반드시 지나야 하는 관문이다.
여기서 막지 않으면 채점 서버가 아무 파일이나 통째로 내려받는 창구가 된다.

관문 다섯 가지:
  1. 주소는 http/https 만       — 서버 안의 파일을 읽어 가는 것을 막는다
  2. 크기는 20MB 까지            — 큰 파일 하나로 서버 메모리를 채우는 것을 막는다
  3. 내려받기는 30초까지         — 응답 없는 서버를 하염없이 기다리지 않는다
  4. 형식은 5가지만              — 우리가 실제로 읽을 수 있는 형식만 받는다
  5. wav 가 아니면 wav 로 바꾼다 — 뒤쪽 전부가 wav 만 다루면 되게 한다

**5번이 이 파일의 최근(2026-08-30) 변경이다.**
백엔드가 저장소에 올리는 응시자 음성은 브라우저 녹음 결과인 **webm** 이다. 그런데
받아쓰기 서버도 발음 평가(Azure)도 소리 크기 재기도 wav 만 읽을 줄 알아서, 시연에서
말하기 채점이 전부 503(받아쓰기 서버 500)으로 떨어졌다. 그래서 **파일이 들어오는
이 자리에서 딱 한 번 16kHz 모노 wav 로 바꾼다.** 변환은 ffmpeg 가 하고(파이썬 꾸러미를
새로 들이지 않는다), 원래 형식은 `source_format` 과 경고 한 줄로 남긴다.
ffmpeg 가 없거나 변환이 실패하면 **조용히 넘기지 않고** 503 으로 알린다.

여기서는 소리 크기도 함께 재 둔다(wav 만 가능하다, loudness.py 참고).
위 5번 변환 덕분에 이제 webm·m4a 로 온 답안도 이 관문을 지나게 됐다
— 압축 형식은 무음 관문이 통째로 건너뛰어지던 구멍이 여기서 닫혔다.
재기만 하고 막지는 않는다 — 무음을 막는 판단은 받아쓰기 구현(gemini_stt.py)이
LLM 을 부르기 직전에 한다. 이 파일은 '파일을 손에 넣는 일'만 맡는다.

여기서 정한 값은 전부 **근거가 있는 값이 아니라 첫 기준값**이다.
실제 응시 녹음 길이가 정해지면 다시 잡아야 한다.
(참고: 11초짜리 24kHz wav 가 약 0.5MB 였다. 20MB 면 대략 7분 분량이다)

로컬 파일은 여기서 읽지 않는다.
서버가 받은 주소로 자기 디스크의 파일을 열어 주면 안 되기 때문이다.
확인용 스크립트가 로컬 wav 를 쓰고 싶을 때는 load_local_audio 를 따로 부른다.
"""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import wave
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import httpx

from ..scoring.messages import Notice, emit, notice
from ..scoring.schema import AudioInput
from .loudness import Loudness, measure_wav_loudness

#: 내려받을 수 있는 최대 크기. 이보다 크면 받다가 끊는다
MAX_AUDIO_BYTES = 20 * 1024 * 1024

#: 내려받기를 기다려 줄 시간(초)
DOWNLOAD_TIMEOUT_S = 30.0

#: 우리가 읽을 수 있는 형식과, Gemini 에게 알려 줄 형식 이름(MIME) 짝.
#: 형식을 늘리려면 여기 한 줄을 더한다. 다른 파일은 손대지 않아도 된다.
FORMAT_TO_MIME: dict[str, str] = {
    "wav": "audio/wav",
    "webm": "audio/webm",
    "mp3": "audio/mpeg",
    "m4a": "audio/mp4",
    "ogg": "audio/ogg",
}

#: 파일을 준 서버가 알려 주는 형식 이름을 우리 형식으로 되돌리는 표.
#: 같은 형식을 여러 이름으로 부르는 경우가 많아서 별도로 둔다.
MIME_TO_FORMAT: dict[str, str] = {
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/wave": "wav",
    "audio/vnd.wave": "wav",
    "audio/webm": "webm",
    "video/webm": "webm",       # 브라우저 녹음이 이 이름으로 오는 일이 있다
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/mp4": "m4a",
    "audio/x-m4a": "m4a",
    "audio/aac": "m4a",
    "audio/ogg": "ogg",
    "application/ogg": "ogg",
    "audio/opus": "ogg",
}


#: ffmpeg 실행파일 경로를 담는 환경변수 이름. 없으면 그냥 "ffmpeg" 로 부른다
#: (PATH 에 걸려 있으면 그것이 잡힌다). 윈도우처럼 경로가 제각각인 곳에서
#: 코드를 고치지 않고 자리만 알려 주려고 환경변수로 뺐다.
FFMPEG_ENV = "KTEST_FFMPEG"
DEFAULT_FFMPEG = "ffmpeg"

#: 변환을 기다려 줄 시간(초). 20MB 짜리 녹음도 몇 초면 끝나므로 60초면 넉넉하다.
#: 이 시간을 넘겼다는 것은 ffmpeg 가 무언가를 기다리며 멈춰 있다는 뜻이라 끊는 편이 낫다
TRANSCODE_TIMEOUT_S = 60

#: 바꿔 놓을 규격. 받아쓰기(Whisper)도 발음 평가(Azure)도 이 규격을 그대로 받는다
TARGET_SAMPLE_RATE = 16_000
TARGET_CHANNELS = 1

#: 파일 앞머리 몇 바이트만 보고 형식을 알아내는 표(매직바이트).
#: 여기 적힌 값은 각 형식이 파일 맨 앞에 반드시 찍어 두는 표식이다.
#:   wav  : 'RIFF' + 4바이트 크기 + 'WAVE'
#:   webm : EBML 표식 1A 45 DF A3 (mkv 도 같은 표식을 쓴다)
#:   m4a  : 앞 4바이트(크기) 다음에 'ftyp'
#:   ogg  : 'OggS'
#:   mp3  : 'ID3' 태그로 시작하거나, 프레임 시작 표식(11비트가 전부 1)


class AudioRequestError(ValueError):
    """음성 답안 요청 자체가 성립하지 않을 때 올리는 예외.

    형식이 우리가 못 읽는 것이거나, 크기가 한도를 넘거나, 주소가 http 가 아닌 경우다.
    이런 요청은 몇 번을 다시 보내도 같은 결과이므로 창구가 400 으로 돌려보낸다.
    (내려받기 자체가 실패한 경우는 다르다. 그쪽은 잠시 뒤 되는 일이라 503 으로 다룬다)

    메시지는 그대로 백엔드에 전달되므로 사람이 읽는 한 문장만 담는다.

    **문구 말고 코드도 함께 들고 다닌다.** 화면에는 영어가 떠야 하는데 우리가 만드는
    문장은 한국어라서, 백엔드가 영어 문장을 고를 열쇠(`code`)와 그 문장에 끼울
    값(`params`)을 예외에 같이 담아 창구(api.py)까지 보낸다.
    `code` 는 안 줘도 되게 해 두어서, 옛날 방식으로 부르던 자리도 그대로 돈다.
    """

    def __init__(self, message: str, code: str = "", params: dict | None = None):
        super().__init__(message)
        #: 백엔드가 영어 문구를 찾을 열쇠 (예: "AUDIO_FILE_TOO_LARGE")
        self.code = code
        #: 그 문구에 끼워 넣을 값 (예: {"actualMb": 25.3, "maxMb": 20})
        self.params = dict(params or {})

    @property
    def notice(self) -> Notice:
        """이 예외를 백엔드에 나갈 모양(코드 + 값 + 한국어 문장)으로 바꾼다."""
        return Notice(code=self.code, params=self.params, message=str(self))

    @classmethod
    def of(cls, code: str, **params) -> "AudioRequestError":
        """코드 하나로 예외를 만든다. 한국어 문장은 카탈로그가 만들어 준다."""
        made = notice(code, **params)
        return cls(made.message, code=made.code, params=made.params)


@dataclass
class FetchedAudio:
    """내려받은 음성 파일 한 개."""

    data: bytes
    #: 우리 형식 이름 (wav/webm/mp3/m4a/ogg).
    #: **입구에서 변환한 뒤라면 언제나 "wav" 다** (ensure_wav 참고)
    audio_format: str
    #: Gemini 에게 알려 줄 형식 이름
    mime_type: str
    #: 응시자가 실제로 보낸 원래 형식. 변환하지 않았으면 audio_format 과 같다.
    #: 브라우저 녹음은 webm 으로 들어오는데 우리가 wav 로 바꿔 채점하므로,
    #: "이 답안은 원래 무엇이었나"를 잃지 않으려고 따로 남긴다
    source_format: str = ""
    #: 파일 길이(밀리초). 잴 수 없으면 None
    duration_ms: int | None = None
    #: 사람이 알아야 할 것
    warnings: list[str] = None  # type: ignore[assignment]
    #: 위 warnings 와 같은 내용을 '코드 + 값' 으로 담은 것. 백엔드가 영어로 바꿔 쓴다
    notices: list[Notice] = None  # type: ignore[assignment]
    #: 소리 크기 측정값. wav 가 아니거나 압축돼 있으면 None(관문을 건너뛴다)
    loudness: Loudness | None = None

    def __post_init__(self) -> None:
        if self.warnings is None:
            self.warnings = []
        if self.notices is None:
            self.notices = []
        # 원래 형식을 안 알려 줬으면 '변환하지 않았다'는 뜻이므로 지금 형식과 같게 둔다
        if not self.source_format:
            self.source_format = self.audio_format

    @property
    def size_bytes(self) -> int:
        return len(self.data)


def resolve_format(audio: AudioInput, content_type: str = "") -> str:
    """이 파일을 어떤 형식으로 읽을지 정한다.

    순서대로 본다. 앞의 것이 있으면 뒤는 보지 않는다.
      1) 요청이 직접 알려 준 format   — 백엔드가 아는 것이 제일 정확하다
      2) 주소 끝의 확장자             — 보통 여기서 정해진다
      3) 파일을 준 서버가 붙인 형식    — 확장자가 없는 주소(서명 URL 등)를 위한 것

    셋 다 알 수 없거나 우리가 못 읽는 형식이면 **추측하지 않고 막는다.**
    엉뚱한 형식으로 읽으면 받아쓴 글이 조용히 엉망이 되는데, 그것은 점수로 나타난다.
    """
    allowed = ", ".join(sorted(FORMAT_TO_MIME))

    # 1) 요청이 직접 알려 준 형식. 점(.)이나 대문자로 와도 받아 준다
    if audio.format:
        declared = audio.format.strip().lower().lstrip(".")
        if declared not in FORMAT_TO_MIME:
            raise AudioRequestError.of(
                "AUDIO_FORMAT_UNSUPPORTED", format=audio.format, allowed=allowed
            )
        return declared

    # 2) 주소 끝의 확장자. 물음표 뒤의 값(?token=...)은 떼고 본다
    suffix = Path(urlparse(audio.url).path).suffix.lower().lstrip(".")
    if suffix in FORMAT_TO_MIME:
        return suffix

    # 3) 파일을 준 서버가 붙인 형식. 뒤에 붙는 부가 정보(; codecs=opus)는 떼고 본다
    base_type = content_type.split(";")[0].strip().lower()
    if base_type in MIME_TO_FORMAT:
        return MIME_TO_FORMAT[base_type]

    # 여기까지 왔으면 무엇인지 모른다. 찍어서 읽지 않는다
    raise AudioRequestError.of("AUDIO_FORMAT_UNKNOWN", allowed=allowed)


def measure_wav_duration_ms(data: bytes) -> int | None:
    """wav 파일의 길이를 파일 안의 정보로 직접 잰다.

    wav 만 재는 이유:
    wav 는 파일 앞머리에 '초당 몇 칸, 총 몇 칸'이 그대로 적혀 있어서 계산으로 나온다.
    mp3·webm 같은 압축 형식은 파일을 풀어 봐야 알 수 있고, 그러려면 별도 프로그램
    (ffmpeg)이 서버에 있어야 한다. 채점에 꼭 필요한 값이 아니므로 여기서는 재지 않고
    요청이 알려 준 값(audio.duration_ms)을 쓴다.
    """
    try:
        with wave.open(io.BytesIO(data), "rb") as handle:
            frames = handle.getnframes()
            rate = handle.getframerate()
    except Exception:
        # 헤더가 깨졌거나 wav 가 아니다. 길이는 부가 정보라 여기서 채점을 멈추지 않는다
        return None
    if not rate:
        return None
    return int(round(frames / rate * 1000))


def sniff_format(data: bytes) -> str | None:
    """파일 **알맹이 앞머리**를 보고 진짜 형식을 알아낸다. 모르겠으면 None.

    왜 필요한가 (2026-08-30 시연 장애):
    형식 이름은 거짓말을 한다. 백엔드는 브라우저가 녹음한 webm 을 저장소에 올리는데,
    주소 확장자나 요청의 format 은 `.wav` 로 적혀 오는 일이 있다. 그 말을 믿고
    wav 로 다루면 받아쓰기 서버가 파일을 못 열어 500 이 나고, 응시자에게는
    "채점 불가(503)"만 보인다. **선언은 참고만 하고 알맹이로 판단한다.**

    앞머리 몇 바이트만 본다. 여기서 하는 일은 형식을 가려내는 것뿐이고,
    실제로 소리를 읽는 것은 아니다.
    """
    # 12바이트도 안 되면 어떤 형식의 표식도 들어갈 수 없다
    if len(data) < 12:
        return None

    # wav: 'RIFF' 로 시작하고 8번째 자리부터 'WAVE' 가 온다
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "wav"
    # webm(과 mkv): EBML 표식으로 시작한다. 브라우저 녹음이 이것이다
    if data[:4] == b"\x1a\x45\xdf\xa3":
        return "webm"
    # m4a/mp4: 앞 4바이트는 상자 크기고 그다음이 'ftyp' 이다(그래서 offset 4)
    if data[4:8] == b"ftyp":
        return "m4a"
    # ogg: 'OggS'
    if data[:4] == b"OggS":
        return "ogg"
    # mp3: 앞에 ID3 태그가 붙어 있거나, 곧바로 프레임 시작 표식이 온다.
    # 프레임 표식은 '11비트가 전부 1' 이라 첫 바이트 FF, 둘째 바이트의 위 3비트가 1이다
    if data[:3] == b"ID3":
        return "mp3"
    if data[0] == 0xFF and (data[1] & 0xE0) == 0xE0:
        return "mp3"

    # 여기까지 오면 우리가 아는 표식이 아니다. 찍지 않고 모른다고 답한다
    return None


def ffmpeg_executable() -> str | None:
    """이 서버에서 부를 수 있는 ffmpeg 실행파일 경로. 없으면 None.

    환경변수(KTEST_FFMPEG)로 자리를 알려 줄 수 있고, 안 알려 주면 PATH 에서 찾는다.
    `shutil.which` 는 절대경로를 줘도 '그 자리에 실행 가능한 파일이 있는지'를
    확인해 주므로 두 경우를 한 줄로 처리할 수 있다.
    """
    configured = os.getenv(FFMPEG_ENV, "").strip() or DEFAULT_FFMPEG
    return shutil.which(configured)


def ffmpeg_available() -> bool:
    """지금 이 서버가 소리 형식을 바꿀 수 있는 상태인지.

    False 면 브라우저 녹음(webm)으로 오는 말하기 답안이 전부 503 이 된다.
    그래서 /health 에 그대로 실어 배포 직후 눈으로 확인할 수 있게 한다.
    """
    return ffmpeg_executable() is not None


def transcode_to_wav(data: bytes, source_format: str = "") -> bytes:
    """어떤 형식의 소리든 ffmpeg 로 **16kHz 모노 16비트 wav** 알맹이로 바꾼다.

    왜 이 규격인가:
    받아쓰기(Whisper)가 16kHz 모노로 학습됐고, Azure 발음 평가도 16비트 wav 만 받는다.
    입구에서 한 번 이 규격으로 맞춰 두면 뒤쪽 모듈이 형식 걱정을 하지 않아도 되고,
    소리 크기 관문(loudness.py)과 길이 재기도 그대로 걸린다(지금까지 압축 형식에서는
    그 관문들이 통째로 건너뛰어지고 있었다).

    파일을 디스크에 쓰지 않고 표준입출력(pipe)으로 주고받는다. 임시 파일을 만들면
    지우는 것을 잊었을 때 응시자 음성이 서버에 남는다.

    실패하면 SttUnavailable(503) 을 올린다. 여기서 조용히 원본을 돌려주면 뒤에서
    받아쓰기가 깨지고, 원인은 "LoRA 서버 500" 으로만 보여 찾기 어려워진다.
    """
    # 파일 맨 위에서 부르면 순환 참조가 되므로 여기서 불러 쓴다(port.py 주석 참고)
    from .port import SttUnavailable

    형식 = source_format or "unknown"

    # 1) 실행파일부터 찾는다. 없으면 무엇이 없는지 분명히 말한다
    ffmpeg = ffmpeg_executable()
    if ffmpeg is None:
        raise SttUnavailable.of(
            "STT_AUDIO_TRANSCODE_FAILED",
            format=형식,
            reason=f"ffmpeg 실행파일을 찾을 수 없다({FFMPEG_ENV} 또는 PATH 확인)",
        )

    # 2) 실제 변환. -i pipe:0 은 '입력을 표준입력으로 받는다',
    #    마지막 pipe:1 은 '결과를 표준출력으로 내보낸다'는 뜻이다
    try:
        done = subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                "pipe:0",
                "-f",
                "wav",
                "-ac",
                str(TARGET_CHANNELS),
                "-ar",
                str(TARGET_SAMPLE_RATE),
                "pipe:1",
            ],
            input=data,
            capture_output=True,
            timeout=TRANSCODE_TIMEOUT_S,
        )
    except FileNotFoundError as exc:
        # which 로는 찾았는데 막상 부를 때 없어진 경우(경로가 잘못 잡힌 때도 여기로 온다)
        raise SttUnavailable.of(
            "STT_AUDIO_TRANSCODE_FAILED",
            format=형식,
            reason=f"ffmpeg 를 실행하지 못했다: {str(exc)[:120]}",
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise SttUnavailable.of(
            "STT_AUDIO_TRANSCODE_FAILED",
            format=형식,
            reason=f"변환이 {TRANSCODE_TIMEOUT_S}초 안에 끝나지 않았다",
        ) from exc

    # 3) ffmpeg 가 실패를 알리면(0 이 아닌 종료값) 그 사유를 짧게 옮겨 담는다.
    #    통째로 실으면 응답에 진단 덤프가 들어가므로 뒤쪽 200자만 쓴다
    if done.returncode != 0:
        stderr = (done.stderr or b"").decode("utf-8", errors="replace").strip()
        raise SttUnavailable.of(
            "STT_AUDIO_TRANSCODE_FAILED",
            format=형식,
            reason=f"ffmpeg 가 실패했다(코드 {done.returncode}): {stderr[-200:] or '사유 없음'}",
        )

    # 4) 종료값은 0인데 결과가 없거나 wav 가 아닌 경우도 실패로 다룬다.
    #    빈 알맹이를 그대로 넘기면 '소리가 없는 답안'으로 둔갑한다
    wav_bytes = done.stdout or b""
    if sniff_format(wav_bytes) != "wav":
        raise SttUnavailable.of(
            "STT_AUDIO_TRANSCODE_FAILED",
            format=형식,
            reason=f"변환 결과가 wav 가 아니다({len(wav_bytes)}바이트)",
        )
    return wav_bytes


def ensure_wav(fetched: FetchedAudio) -> FetchedAudio:
    """손에 넣은 음성이 wav 가 아니면 **여기서 한 번만** wav 로 바꾼다.

    왜 한 곳에서 바꾸는가:
    받아쓰기(LoRA)·발음 평가(Azure)·소리 크기 재기가 저마다 형식을 다루면 같은 변환이
    세 벌 생기고, 한 곳만 고치면 나머지가 조용히 어긋난다. 파일이 들어오는 입구인
    이 자리에서 한 번 바꿔 두면 뒤쪽은 전부 'wav 만 온다'를 전제로 둘 수 있다.

    판단은 선언된 형식이 아니라 **알맹이 앞머리(매직바이트)** 로 한다. 확장자가
    `.wav` 라고 적혀 있어도 알맹이가 webm 이면 바꾼다.

    변환에 성공하면 알맹이·형식·길이·소리 크기를 새 wav 기준으로 다시 채우고,
    원래 형식은 source_format 과 경고 한 줄로 남긴다(무엇을 채점했는지 추적하려는 것).
    """
    # 알맹이가 이미 wav 면 손대지 않는다(지금 들어오는 대부분이 이 길이다)
    if sniff_format(fetched.data) == "wav":
        return fetched

    # 알맹이로 알아낸 형식을 우선 쓰고, 못 알아냈으면 선언된 형식을 적어 둔다.
    # 이 값은 실패 안내에도 실려서 "무엇을 바꾸려다 실패했나"를 말해 준다
    source = sniff_format(fetched.data) or fetched.audio_format

    wav_bytes = transcode_to_wav(fetched.data, source)

    # 새 wav 기준으로 전부 다시 채운다. 길이와 소리 크기는 바뀐 파일에서 재야 맞다
    fetched.source_format = source
    fetched.data = wav_bytes
    fetched.audio_format = "wav"
    fetched.mime_type = FORMAT_TO_MIME["wav"]
    fetched.duration_ms = measure_wav_duration_ms(wav_bytes)
    fetched.loudness = measure_wav_loudness(wav_bytes)

    # 무엇을 바꿔서 채점했는지 사람이 볼 수 있게 남긴다(운영자용 안내다)
    emit(fetched.warnings, fetched.notices, "AUDIO_TRANSCODED_TO_WAV", sourceFormat=source)
    return fetched


def fetch_audio(
    audio: AudioInput,
    *,
    http_client: httpx.Client | None = None,
) -> FetchedAudio:
    """음성 파일을 내려받아 형식과 길이까지 확인해서 돌려준다.

    http_client 를 넘기면 그것을 쓴다(테스트가 네트워크 없이 도는 자리).
    안 넘기면 여기서 만들어 쓰고 끝나면 닫는다.

    크기 확인을 두 번 하는 이유:
    서버가 알려 준 크기(Content-Length)를 먼저 보고 넘치면 **받기도 전에** 끊는다.
    그런데 그 값은 없을 수도 있고 거짓일 수도 있어서, 실제로 받으면서도 센다.
    앞의 확인만 두면 크기를 안 알려 주는 서버에는 관문이 없는 것과 같다.
    """
    # 관문 1: 주소 확인. http/https 가 아니면 아예 열지 않는다.
    # 이것을 열어 두면 'file:///C:/...' 같은 주소로 서버 안의 파일을 읽어 갈 수 있다
    parsed = urlparse(audio.url)
    if parsed.scheme not in ("http", "https"):
        raise AudioRequestError.of("AUDIO_URL_SCHEME_INVALID")

    # 클라이언트를 받아 왔으면 우리가 닫지 않는다(부르는 쪽이 계속 쓸 수 있어야 한다)
    owned = http_client is None
    client = http_client or httpx.Client(timeout=DOWNLOAD_TIMEOUT_S, follow_redirects=True)

    try:
        try:
            with client.stream("GET", audio.url) as response:
                # 파일이 없거나 권한이 없으면 여기서 걸린다
                if response.status_code >= 400:
                    raise AudioRequestError.of(
                        "AUDIO_FETCH_HTTP_ERROR", statusCode=response.status_code
                    )

                # 관문 2 (앞): 서버가 크기를 알려 줬고 그것이 이미 한도를 넘으면 받지 않는다
                declared = response.headers.get("content-length")
                if declared and declared.isdigit() and int(declared) > MAX_AUDIO_BYTES:
                    raise AudioRequestError.of(
                        "AUDIO_FILE_TOO_LARGE",
                        actualMb=round(int(declared) / 1024 / 1024, 1),
                        maxMb=MAX_AUDIO_BYTES // 1024 // 1024,
                    )

                # 관문 2 (실제): 받으면서 센다. 넘는 순간 끊는다
                chunks: list[bytes] = []
                received = 0
                for chunk in response.iter_bytes():
                    received += len(chunk)
                    if received > MAX_AUDIO_BYTES:
                        raise AudioRequestError.of(
                            "AUDIO_FILE_TOO_LARGE_STREAM",
                            maxMb=MAX_AUDIO_BYTES // 1024 // 1024,
                        )
                    chunks.append(chunk)

                content_type = response.headers.get("content-type", "")
        except httpx.HTTPError as exc:
            # 연결이 안 되거나 시간 안에 안 오는 경우다. 요청이 틀린 것이 아니라
            # 잠시 뒤에는 될 수 있는 상황이므로 400 이 아니라 '받아쓰기 실패'로 올린다.
            # (여기서 import 하는 이유: 파일 맨 위에서 서로를 부르면 순환 참조가 된다)
            from .port import SttUnavailable

            raise SttUnavailable.of(
                "AUDIO_DOWNLOAD_TIMEOUT",
                detail=str(exc),
                timeoutSec=round(DOWNLOAD_TIMEOUT_S),
            ) from exc
    finally:
        if owned:
            client.close()

    data = b"".join(chunks)
    # 빈 파일은 받아쓸 것이 없다. 여기서 막지 않으면 LLM 이 빈 소리에 대고 문장을 지어낸다
    if not data:
        raise AudioRequestError.of("AUDIO_FILE_EMPTY")

    # 관문 4: 형식 확인. 못 읽는 형식이면 여기서 막힌다
    audio_format = resolve_format(audio, content_type)

    warnings: list[str] = []
    notices: list[Notice] = []
    fetched = FetchedAudio(
        data=data,
        audio_format=audio_format,
        mime_type=FORMAT_TO_MIME[audio_format],
        warnings=warnings,
        notices=notices,
    )

    # 관문 5: 형식 통일. wav 가 아니면 여기서 wav 로 바꾼다.
    # 이 한 줄 덕분에 뒤쪽(받아쓰기·발음 평가·소리 크기)은 wav 만 다루면 된다.
    # 바꾸지 못하면 SttUnavailable(503) 이 올라가고 채점은 진행되지 않는다
    fetched = ensure_wav(fetched)

    # 길이는 wav 파일에서 직접 잰다(변환한 경우 ensure_wav 가 이미 채워 뒀다).
    # 그래도 못 재면 요청이 알려 준 값을 쓰고, 그것도 없으면 없는 대로 남긴다
    if fetched.duration_ms is None:
        fetched.duration_ms = measure_wav_duration_ms(fetched.data)
    if fetched.duration_ms is None:
        fetched.duration_ms = audio.duration_ms
        if fetched.duration_ms is None and fetched.audio_format != "wav":
            emit(warnings, notices, "AUDIO_DURATION_UNMEASURABLE", format=fetched.audio_format)

    # 소리 크기(무음 관문의 재료)도 wav 에서만 잴 수 있다.
    # 변환한 경우에는 ensure_wav 가 이미 재 뒀으므로 비어 있을 때만 잰다
    if fetched.loudness is None and fetched.audio_format == "wav":
        fetched.loudness = measure_wav_loudness(fetched.data)
    return fetched


def load_local_audio(path: str | Path, declared_format: str | None = None) -> FetchedAudio:
    """디스크에 있는 음성 파일을 읽는다. **확인용 스크립트 전용이다.**

    채점 요청(fetch_audio)은 이 길로 오지 않는다.
    백엔드가 준 주소로 서버 안의 파일을 읽어 주면, 주소만 바꿔서 서버의 아무 파일이나
    꺼내 가는 통로가 되기 때문이다. 여기는 사람이 직접 파일을 지정하는 경우만 쓴다.
    """
    file_path = Path(path)
    if not file_path.exists():
        # 스크립트 전용 경로라 사용자 대면 코드가 없다(응답으로 나가지 않는다)
        raise AudioRequestError(f"음성 파일을 찾을 수 없다: {file_path}")

    # 확장자로 형식을 정한다. 로컬 파일에는 알려 줄 서버가 없다
    audio_format = (declared_format or file_path.suffix).strip().lower().lstrip(".")
    if audio_format not in FORMAT_TO_MIME:
        raise AudioRequestError.of(
            "AUDIO_FORMAT_UNSUPPORTED",
            format=audio_format,
            allowed=", ".join(sorted(FORMAT_TO_MIME)),
        )

    data = file_path.read_bytes()
    if len(data) > MAX_AUDIO_BYTES:
        raise AudioRequestError.of(
            "AUDIO_FILE_TOO_LARGE_STREAM", maxMb=MAX_AUDIO_BYTES // 1024 // 1024
        )

    return FetchedAudio(
        data=data,
        audio_format=audio_format,
        mime_type=FORMAT_TO_MIME[audio_format],
        duration_ms=measure_wav_duration_ms(data) if audio_format == "wav" else None,
        loudness=measure_wav_loudness(data) if audio_format == "wav" else None,
    )
