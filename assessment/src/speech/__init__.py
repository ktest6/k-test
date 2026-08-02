"""응시자의 음성 답안을 글자로 옮기는 모듈.

이 패키지는 **글자로 옮기기만 하고 점수는 내지 않는다.**
채점은 src/scoring/ 이 하고, 여기서 나온 글이 그쪽의 answer_text 자리로 들어간다.
그래서 채점 규칙은 음성이 붙든 안 붙든 똑같이 돈다.

Azure 로 갈아 끼울 자리:
    port.py       꽂는 자리(계약). 여기는 안 바뀐다
    gemini_stt.py 지금 꽂혀 있는 임시 구현 (Azure 계정이 없어서 넣은 것)
    intake.py     build_default_stt() — 갈아 끼울 때 고치는 곳은 이 함수다

**받아쓰기는 채점의 전제이지 대체 가능한 부품이 아니다.**
못 알아들은 음성을 그럴듯한 문장으로 지어내면 응시자가 하지도 않은 말로
점수를 받는다. 그래서 이 패키지는 실패하면 실패했다고 말한다(대체 경로가 없다).
"""

from __future__ import annotations

from .audio import (
    DOWNLOAD_TIMEOUT_S,
    FORMAT_TO_MIME,
    MAX_AUDIO_BYTES,
    AudioRequestError,
    fetch_audio,
    load_local_audio,
)
from .gemini_stt import DEFAULT_STT_MODEL, GeminiStt
from .intake import AudioResolution, build_default_stt, resolve_audio_answer
from .port import SttPort, SttUnavailable, Transcription

__all__ = [
    "DEFAULT_STT_MODEL",
    "DOWNLOAD_TIMEOUT_S",
    "FORMAT_TO_MIME",
    "MAX_AUDIO_BYTES",
    "AudioRequestError",
    "AudioResolution",
    "GeminiStt",
    "SttPort",
    "SttUnavailable",
    "Transcription",
    "build_default_stt",
    "fetch_audio",
    "load_local_audio",
    "resolve_audio_answer",
]
