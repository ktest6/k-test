"""응시자의 음성 답안을 글자로 옮기는 모듈.

이 패키지는 **글자로 옮기기만 하고 점수는 내지 않는다.**
채점은 src/scoring/ 이 하고, 여기서 나온 글이 그쪽의 answer_text 자리로 들어간다.
그래서 채점 규칙은 음성이 붙든 안 붙든 똑같이 돈다.

Azure 로 갈아 끼울 자리:
    port.py       꽂는 자리(계약). 여기는 안 바뀐다
    azure_stt.py  Azure 구현. 받아쓰기 + **발음 평가**를 한 번에 한다 (2026-08-22 합류)
    gemini_stt.py 예전 임시 구현. 글자만 주고 발음은 못 잰다
    intake.py     build_default_stt() — 어느 것을 쓸지 고르는 곳
                  (KTEST_STT_PROVIDER 환경변수, 안 정하면 Azure 열쇠가 있을 때 azure)
    loudness.py   무음 관문. **여기는 LLM 과 무관해서 Azure 로 바꿔도 그대로 쓴다**

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
    ensure_wav,
    fetch_audio,
    ffmpeg_available,
    load_local_audio,
    sniff_format,
    transcode_to_wav,
)
from .azure_stt import AzureStt, is_read_aloud
from .gemini_stt import DEFAULT_STT_MODEL, GeminiStt
from .intake import (
    LORA_STT_URL_ENV,
    STT_PROVIDER_ENV,
    AudioResolution,
    azure_pronunciation_available,
    build_default_pronouncer,
    build_default_stt,
    choose_stt_provider,
    resolve_audio_answer,
)
from .lora_stt import DEFAULT_LORA_MODEL, LoraStt
from .loudness import (
    SILENCE_RMS,
    SPEECH_FLOOR_RMS,
    Loudness,
    is_silent,
    is_too_quiet_for_speech,
    measure_wav_loudness,
)
from .port import (
    PronouncedWord,
    PronouncerPort,
    PronunciationAssessment,
    SttPort,
    SttUnavailable,
    Transcription,
)

__all__ = [
    "DEFAULT_LORA_MODEL",
    "DEFAULT_STT_MODEL",
    "DOWNLOAD_TIMEOUT_S",
    "FORMAT_TO_MIME",
    "LORA_STT_URL_ENV",
    "MAX_AUDIO_BYTES",
    "SILENCE_RMS",
    "SPEECH_FLOOR_RMS",
    "STT_PROVIDER_ENV",
    "AudioRequestError",
    "AudioResolution",
    "AzureStt",
    "GeminiStt",
    "LoraStt",
    "Loudness",
    "PronouncedWord",
    "PronouncerPort",
    "PronunciationAssessment",
    "SttPort",
    "SttUnavailable",
    "Transcription",
    "azure_pronunciation_available",
    "build_default_pronouncer",
    "build_default_stt",
    "choose_stt_provider",
    "ensure_wav",
    "fetch_audio",
    "ffmpeg_available",
    "is_read_aloud",
    "is_silent",
    "is_too_quiet_for_speech",
    "load_local_audio",
    "measure_wav_loudness",
    "resolve_audio_answer",
    "sniff_format",
    "transcode_to_wav",
]
