"""음성 파일을 안전하게 손에 넣는 일만 하는 파일.

받아쓰기(STT)를 부르기 전에 반드시 지나야 하는 관문이다.
여기서 막지 않으면 채점 서버가 아무 파일이나 통째로 내려받는 창구가 된다.

관문 네 가지:
  1. 주소는 http/https 만       — 서버 안의 파일을 읽어 가는 것을 막는다
  2. 크기는 20MB 까지            — 큰 파일 하나로 서버 메모리를 채우는 것을 막는다
  3. 내려받기는 30초까지         — 응답 없는 서버를 하염없이 기다리지 않는다
  4. 형식은 5가지만              — 우리가 실제로 읽을 수 있는 형식만 받는다

여기서는 소리 크기도 함께 재 둔다(wav 만 가능하다, loudness.py 참고).
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
import wave
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import httpx

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


class AudioRequestError(ValueError):
    """음성 답안 요청 자체가 성립하지 않을 때 올리는 예외.

    형식이 우리가 못 읽는 것이거나, 크기가 한도를 넘거나, 주소가 http 가 아닌 경우다.
    이런 요청은 몇 번을 다시 보내도 같은 결과이므로 창구가 400 으로 돌려보낸다.
    (내려받기 자체가 실패한 경우는 다르다. 그쪽은 잠시 뒤 되는 일이라 503 으로 다룬다)

    메시지는 그대로 백엔드에 전달되므로 사람이 읽는 한 문장만 담는다.
    """


@dataclass
class FetchedAudio:
    """내려받은 음성 파일 한 개."""

    data: bytes
    #: 우리 형식 이름 (wav/webm/mp3/m4a/ogg)
    audio_format: str
    #: Gemini 에게 알려 줄 형식 이름
    mime_type: str
    #: 파일 길이(밀리초). 잴 수 없으면 None
    duration_ms: int | None = None
    #: 사람이 알아야 할 것
    warnings: list[str] = None  # type: ignore[assignment]
    #: 소리 크기 측정값. wav 가 아니거나 압축돼 있으면 None(관문을 건너뛴다)
    loudness: Loudness | None = None

    def __post_init__(self) -> None:
        if self.warnings is None:
            self.warnings = []

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
            raise AudioRequestError(
                f"'{audio.format}' 형식은 받아쓸 수 없다(받는 형식: {allowed})."
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
    raise AudioRequestError(
        "음성 형식을 알 수 없다. audio.format 에 형식을 적어서 다시 보내야 한다"
        f"(받는 형식: {allowed})."
    )


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
        raise AudioRequestError(
            "음성 파일 주소는 http 또는 https 여야 한다(서버 안의 파일 경로는 받지 않는다)."
        )

    # 클라이언트를 받아 왔으면 우리가 닫지 않는다(부르는 쪽이 계속 쓸 수 있어야 한다)
    owned = http_client is None
    client = http_client or httpx.Client(timeout=DOWNLOAD_TIMEOUT_S, follow_redirects=True)

    try:
        try:
            with client.stream("GET", audio.url) as response:
                # 파일이 없거나 권한이 없으면 여기서 걸린다
                if response.status_code >= 400:
                    raise AudioRequestError(
                        f"음성 파일을 받지 못했다(주소가 {response.status_code} 로 응답했다). "
                        "파일 주소와 접근 권한을 확인해야 한다."
                    )

                # 관문 2 (앞): 서버가 크기를 알려 줬고 그것이 이미 한도를 넘으면 받지 않는다
                declared = response.headers.get("content-length")
                if declared and declared.isdigit() and int(declared) > MAX_AUDIO_BYTES:
                    raise AudioRequestError(
                        f"음성 파일이 {int(declared) / 1024 / 1024:.1f}MB 로 너무 크다"
                        f"(최대 {MAX_AUDIO_BYTES // 1024 // 1024}MB)."
                    )

                # 관문 2 (실제): 받으면서 센다. 넘는 순간 끊는다
                chunks: list[bytes] = []
                received = 0
                for chunk in response.iter_bytes():
                    received += len(chunk)
                    if received > MAX_AUDIO_BYTES:
                        raise AudioRequestError(
                            f"음성 파일이 최대 {MAX_AUDIO_BYTES // 1024 // 1024}MB 를 넘는다."
                        )
                    chunks.append(chunk)

                content_type = response.headers.get("content-type", "")
        except httpx.HTTPError as exc:
            # 연결이 안 되거나 시간 안에 안 오는 경우다. 요청이 틀린 것이 아니라
            # 잠시 뒤에는 될 수 있는 상황이므로 400 이 아니라 '받아쓰기 실패'로 올린다.
            # (여기서 import 하는 이유: 파일 맨 위에서 서로를 부르면 순환 참조가 된다)
            from .port import SttUnavailable

            raise SttUnavailable(
                f"음성 파일을 내려받지 못했다(제한 시간 {DOWNLOAD_TIMEOUT_S:.0f}초). "
                "저장소 주소가 살아 있는지 확인해야 한다.",
                detail=str(exc),
            ) from exc
    finally:
        if owned:
            client.close()

    data = b"".join(chunks)
    # 빈 파일은 받아쓸 것이 없다. 여기서 막지 않으면 LLM 이 빈 소리에 대고 문장을 지어낸다
    if not data:
        raise AudioRequestError("음성 파일이 비어 있다(0바이트).")

    # 관문 4: 형식 확인. 못 읽는 형식이면 여기서 막힌다
    audio_format = resolve_format(audio, content_type)

    # 길이는 wav 만 직접 재고, 나머지는 요청이 알려 준 값을 쓴다
    warnings: list[str] = []
    duration_ms = measure_wav_duration_ms(data) if audio_format == "wav" else None
    if duration_ms is None:
        duration_ms = audio.duration_ms
        if duration_ms is None and audio_format != "wav":
            warnings.append(
                f"{audio_format} 형식은 파일에서 길이를 재지 못한다. "
                "녹음 길이가 필요하면 audio.duration_ms 로 알려 줘야 한다."
            )

    # 소리 크기를 여기서 재 둔다. wav 가 아니면 None 이고, 그러면 무음 관문이 없다
    return FetchedAudio(
        data=data,
        audio_format=audio_format,
        mime_type=FORMAT_TO_MIME[audio_format],
        duration_ms=duration_ms,
        warnings=warnings,
        loudness=measure_wav_loudness(data) if audio_format == "wav" else None,
    )


def load_local_audio(path: str | Path, declared_format: str | None = None) -> FetchedAudio:
    """디스크에 있는 음성 파일을 읽는다. **확인용 스크립트 전용이다.**

    채점 요청(fetch_audio)은 이 길로 오지 않는다.
    백엔드가 준 주소로 서버 안의 파일을 읽어 주면, 주소만 바꿔서 서버의 아무 파일이나
    꺼내 가는 통로가 되기 때문이다. 여기는 사람이 직접 파일을 지정하는 경우만 쓴다.
    """
    file_path = Path(path)
    if not file_path.exists():
        raise AudioRequestError(f"음성 파일을 찾을 수 없다: {file_path}")

    # 확장자로 형식을 정한다. 로컬 파일에는 알려 줄 서버가 없다
    audio_format = (declared_format or file_path.suffix).strip().lower().lstrip(".")
    if audio_format not in FORMAT_TO_MIME:
        raise AudioRequestError(
            f"'{audio_format}' 형식은 받아쓸 수 없다"
            f"(받는 형식: {', '.join(sorted(FORMAT_TO_MIME))})."
        )

    data = file_path.read_bytes()
    if len(data) > MAX_AUDIO_BYTES:
        raise AudioRequestError(
            f"음성 파일이 최대 {MAX_AUDIO_BYTES // 1024 // 1024}MB 를 넘는다."
        )

    return FetchedAudio(
        data=data,
        audio_format=audio_format,
        mime_type=FORMAT_TO_MIME[audio_format],
        duration_ms=measure_wav_duration_ms(data) if audio_format == "wav" else None,
        loudness=measure_wav_loudness(data) if audio_format == "wav" else None,
    )
