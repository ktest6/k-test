"""사용자에게 보여줄 문구를 '코드 + 값'으로 바꿔 주는 곳.

**왜 이 파일이 필요한가.**
이 시험은 외국인 노동자가 본다. 그런데 우리 채점 API가 내보내는 오류·상태·근거
문구는 전부 한국어다. 화면에는 영어로 떠야 하는데, 우리가 영어 문장까지 만들어
보내면 문구를 하나 고칠 때마다 채점 서버를 다시 배포해야 한다.

그래서 팀에서 정한 방식은 이렇다. **우리는 문장 대신 '코드'와 '값'을 보낸다.**

    {"code": "AUDIO_FILE_TOO_LARGE", "params": {"actualMb": 25.3, "maxMb": 20}}

백엔드가 이 코드를 자기 쪽 영어 문장에 끼워 화면에 띄운다. 문구를 바꾸고 싶으면
백엔드만 고치면 되고, 나중에 베트남어·네팔어가 늘어도 우리 코드는 그대로다.

**기존 필드는 하나도 바꾸지 않는다.** 지금까지 나가던 한국어 문장(`warnings`,
`note`, `comment`)은 그 자리에 그대로 두고, 그 옆에 `notices`(코드 목록)를 더한다.
백엔드가 새 방식으로 다 갈아탈 때까지 두 가지가 함께 나가야 연동이 끊기지 않는다.

**이 파일에 담기는 것은 '코드가 만드는 고정 문구'뿐이다.**
LLM이 그때그때 지어내는 판정 이유(reason)는 문구가 정해져 있지 않으므로 코드가
없다. 그런 문구는 `LLM_FREE_TEXT` 코드에 원문을 담아 보내거나 코드를 비워 둔다.

쓰는 법은 두 가지다.

    notice("AUDIO_FILE_EMPTY")                 # Notice 하나 만들기
    emit(warnings, notices, "AUDIO_FILE_EMPTY")  # 한국어 문장과 Notice 를 동시에 쌓기

`emit` 을 쓰는 이유: 예전 방식(`warnings`)과 새 방식(`notices`)에 같은 내용을
따로따로 넣게 두면 한쪽만 넣고 빠뜨리는 자리가 반드시 생긴다. 한 번 부르면 둘 다
채워지게 만들어서 어긋날 길을 막았다.
"""

from __future__ import annotations

import string
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

__all__ = [
    "MESSAGE_CATALOG",
    "MessageSpec",
    "Notice",
    "emit",
    "notice",
    "notice_or_free_text",
]


# ---------------------------------------------------------------------------
# 백엔드에 나가는 모양
# ---------------------------------------------------------------------------


class Notice(BaseModel):
    """사용자에게 보여줄 안내 한 줄을 '코드 + 값 + 한국어 원문'으로 담은 것.

    - `code`   : 백엔드가 영어 문장을 고를 때 쓰는 열쇠 (예: `AUDIO_FILE_TOO_LARGE`)
    - `params` : 문장 안에 끼워 넣을 값들 (예: `{"actualMb": 25.3, "maxMb": 20}`)
    - `message`: 지금까지 `warnings` 에 나가던 한국어 문장 그대로

    `message` 를 함께 보내는 이유: 백엔드가 아직 영어 문장을 안 만든 코드가 있어도
    화면이 비지 않게 하려는 것이다(한국어라도 뜨는 편이 아무것도 안 뜨는 것보다 낫다).
    """

    code: str = Field(description="영어 문구를 고르는 열쇠. 대문자 스네이크")
    params: dict[str, Any] = Field(
        default_factory=dict,
        description="문장에 끼워 넣을 값. 키 이름은 camelCase",
    )
    message: str = Field(default="", description="한국어 원문(지금까지 나가던 그 문장)")


# ---------------------------------------------------------------------------
# 카탈로그 한 줄의 모양
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MessageSpec:
    """코드 하나에 대한 설명서.

    템플릿만 있으면 한국어 문장은 만들 수 있지만, 백엔드에게 넘길 문서(어떤 값이
    어떤 타입으로 오는지)를 손으로 또 쓰게 된다. 그러면 코드와 문서가 어긋난다.
    그래서 타입·예시·영어 초안까지 여기 한 곳에 모아 두고 문서는 뽑아 쓴다
    (`scripts/export_message_codes.py`).
    """

    #: 한국어 문장 틀. `{키}` 자리에 params 값이 들어간다
    template: str
    #: 백엔드가 쓸 영어 문장 초안. 같은 `{키}` 를 쓴다
    english: str
    #: params 키 -> 값의 타입. "notice" 는 그 안에 또 다른 Notice 가 들어간다는 뜻
    params: dict[str, str] = field(default_factory=dict)
    #: 문서에 실을 예시값. params 의 모든 키를 채워야 한다
    examples: dict[str, Any] = field(default_factory=dict)
    #: 이 문구가 응답의 어느 자리로 나가는지 (HTTP detail / warnings / note ...)
    where: str = "warnings"
    #: 어느 엔드포인트에서 나오는지
    endpoint: str = "/score"
    #: 사람이 읽을 상황 설명
    situation: str = ""
    #: True 면 응시자가 아니라 운영자에게 주는 안내라 영어화가 필요 없다
    internal: bool = False


def _spec(
    template: str,
    english: str,
    *,
    params: dict[str, str] | None = None,
    examples: dict[str, Any] | None = None,
    where: str = "warnings",
    endpoint: str = "/score",
    situation: str = "",
    internal: bool = False,
) -> MessageSpec:
    """카탈로그를 짧게 적기 위한 도우미."""
    return MessageSpec(
        template=template,
        english=english,
        params=params or {},
        examples=examples or {},
        where=where,
        endpoint=endpoint,
        situation=situation,
        internal=internal,
    )


# 중첩 Notice 를 담는 값의 타입 이름. 백엔드는 이 자리에 들어온 코드도 한 번 더
# 영어로 바꿔서 바깥 문장에 끼워 넣어야 한다.
NESTED = "notice"


# ---------------------------------------------------------------------------
# 코드 카탈로그
# ---------------------------------------------------------------------------
#
# 규칙
#  - 코드 이름: 대문자 스네이크. 앞머리가 영역을 뜻한다
#      AUTH_(인증) AUDIO_(음성 파일) STT_(받아쓰기) LLM_(모델 호출)
#      VALIDITY_(답안 유효성 가드) RELIABILITY_(채점 신뢰도) TRANSCRIPT_(전사 보정)
#      CHECKLIST_(체크리스트 판정) CITATION_(인용 검증) SUBSCORE_(영역 점수)
#      FINALIZE_(최종 등급) GEN_(문항 생성) VERIFY_(문항 재검증) DROP_(문항 폐기 사유)
#  - params 키 이름: camelCase. 백엔드(자바)가 쓰는 이름 규칙에 맞췄다
#  - 같은 문장이 여러 파일에서 나오면 코드는 하나로 합치고 provider 같은 값으로 구분한다
#
# ★ 한국어를 그대로 두는 자리 ★
#   `STT_TOO_QUIET` 의 `preview` 는 응시자가 실제로 한국어로 말한 것을 받아쓴
#   조각이다. **번역하지 말고 그대로 화면에 끼워 넣어야 한다.** 응시자의 말을
#   영어로 바꿔 보여 주면 "내가 그렇게 말하지 않았다"는 이의를 확인할 수가 없다.
#   같은 이유로 `meta.stt_transcript` 도 번역 대상이 아니다.

MESSAGE_CATALOG: dict[str, MessageSpec] = {
    # -----------------------------------------------------------------
    # 0. 인증 (모든 POST 공통)
    # -----------------------------------------------------------------
    "AUTH_API_KEY_MISSING": _spec(
        "{header} 헤더가 없습니다. 발급받은 채점 API 키를 헤더에 넣어 주세요.",
        "The {header} header is missing. Put your scoring API key in this header.",
        params={"header": "str"},
        examples={"header": "X-API-Key"},
        where="HTTP 401 detail",
        endpoint="공통(모든 POST)",
        situation="X-API-Key 헤더를 아예 안 보냄",
    ),
    "AUTH_API_KEY_INVALID": _spec(
        "{header} 헤더의 값이 올바르지 않습니다.",
        "The value of the {header} header is not valid.",
        params={"header": "str"},
        examples={"header": "X-API-Key"},
        where="HTTP 401 detail",
        endpoint="공통(모든 POST)",
        situation="X-API-Key 값이 틀림",
    ),
    # -----------------------------------------------------------------
    # 1-A. 음성 요청 자체가 틀림 (400)
    # -----------------------------------------------------------------
    "AUDIO_FORMAT_UNSUPPORTED": _spec(
        "'{format}' 형식은 받아쓸 수 없다(받는 형식: {allowed}).",
        "Audio format '{format}' cannot be transcribed (accepted: {allowed}).",
        params={"format": "str", "allowed": "str"},
        examples={"format": "flac", "allowed": "wav, webm, mp3, m4a, ogg"},
        where="HTTP 400 detail",
        situation="못 읽는 형식을 format 으로 지정",
    ),
    "AUDIO_FORMAT_UNKNOWN": _spec(
        "음성 형식을 알 수 없다. audio.format 에 형식을 적어서 다시 보내야 한다(받는 형식: {allowed}).",
        "The audio format could not be determined. Send it again with audio.format set "
        "(accepted: {allowed}).",
        params={"allowed": "str"},
        examples={"allowed": "wav, webm, mp3, m4a, ogg"},
        where="HTTP 400 detail",
        situation="형식을 전혀 알 수 없음",
    ),
    "AUDIO_URL_SCHEME_INVALID": _spec(
        "음성 파일 주소는 http 또는 https 여야 한다(서버 안의 파일 경로는 받지 않는다).",
        "The audio file URL must use http or https (server-local file paths are not accepted).",
        where="HTTP 400 detail",
        situation="주소가 http/https 가 아님",
    ),
    "AUDIO_FETCH_HTTP_ERROR": _spec(
        "음성 파일을 받지 못했다(주소가 {statusCode} 로 응답했다). 파일 주소와 접근 권한을 확인해야 한다.",
        "The audio file could not be downloaded (the URL answered with {statusCode}). "
        "Check the URL and its access permissions.",
        params={"statusCode": "int"},
        examples={"statusCode": 403},
        where="HTTP 400 detail",
        situation="파일 주소가 4xx/5xx 응답",
    ),
    "AUDIO_FILE_TOO_LARGE": _spec(
        "음성 파일이 {actualMb}MB 로 너무 크다(최대 {maxMb}MB).",
        "The audio file is {actualMb}MB, which is too large (maximum {maxMb}MB).",
        params={"actualMb": "float", "maxMb": "int"},
        examples={"actualMb": 25.3, "maxMb": 20},
        where="HTTP 400 detail",
        situation="서버가 알려 준 크기가 한도 초과",
    ),
    "AUDIO_FILE_TOO_LARGE_STREAM": _spec(
        "음성 파일이 최대 {maxMb}MB 를 넘는다.",
        "The audio file exceeds the maximum of {maxMb}MB.",
        params={"maxMb": "int"},
        examples={"maxMb": 20},
        where="HTTP 400 detail",
        situation="받는 도중 크기 한도 초과",
    ),
    "AUDIO_FILE_EMPTY": _spec(
        "음성 파일이 비어 있다(0바이트).",
        "The audio file is empty (0 bytes).",
        where="HTTP 400 detail",
        situation="빈 파일",
    ),
    "AUDIO_NOT_ALLOWED_FOR_WRITING": _spec(
        "쓰기 답안에는 음성 파일을 붙일 수 없다. 음성 채점은 mode 를 speaking 으로 보내야 한다.",
        "A writing answer cannot carry an audio file. Send mode=speaking to have audio scored.",
        where="HTTP 400 detail",
        situation="쓰기 답안에 음성을 붙임",
    ),
    "AUDIO_TEXT_AND_AUDIO_BOTH": _spec(
        "answer_text 와 audio 가 함께 왔다. 어느 것을 채점해야 할지 알 수 없다. "
        "음성으로 채점하려면 answer_text 를 비워서 보내야 한다.",
        "Both answer_text and audio were sent, so it is unclear which one to score. "
        "Leave answer_text empty to have the audio scored.",
        where="HTTP 400 detail",
        situation="글과 음성을 함께 보냄",
    ),
    # -----------------------------------------------------------------
    # 1-A. 받아쓰기 실패 (503) — 공통
    # -----------------------------------------------------------------
    "AUDIO_DOWNLOAD_TIMEOUT": _spec(
        "음성 파일을 내려받지 못했다(제한 시간 {timeoutSec}초). 저장소 주소가 살아 있는지 확인해야 한다.",
        "The audio file could not be downloaded within {timeoutSec} seconds. "
        "Check that the storage URL is reachable.",
        params={"timeoutSec": "int(초)"},
        examples={"timeoutSec": 30},
        where="HTTP 503 detail",
        situation="내려받기 시간 초과",
    ),
    "STT_EMPTY_TRANSCRIPT_FINAL": _spec(
        "음성에서 말을 하나도 옮겨 적지 못했다. 녹음 상태를 확인해야 한다.",
        "No speech at all could be transcribed from the audio. Check the recording.",
        where="HTTP 503 detail",
        situation="받아쓴 글이 빈 글(파이프라인 최종 가드)",
    ),
    "STT_EMPTY_TRANSCRIPT": _spec(
        "음성에서 말을 하나도 옮겨 적지 못했다. 녹음이 비어 있거나 소리가 너무 작은지 확인해야 한다.",
        "No speech at all could be transcribed from the audio. Check whether the recording "
        "is empty or too quiet.",
        params={"provider": "str"},
        examples={"provider": "lora"},
        where="HTTP 503 detail",
        situation="받아쓰기가 빈 글을 돌려줌(제공자별 공통 문구, provider 로 구분)",
    ),
    "STT_SILENT_AUDIO": _spec(
        "음성에서 소리를 찾지 못했다(녹음이 무음이다). 마이크가 꺼져 있었거나 녹음이 실패했는지 "
        "확인해야 한다. 측정값: {loudness}",
        "No sound was found in the audio (the recording is silent). Check whether the "
        "microphone was off or the recording failed. Measurements: {loudness}",
        params={"loudness": "str", "loudnessNotice": NESTED},
        examples={
            "loudness": "가장 큰 0.1초 구간 12.0, 전체 평균 3.4 (0~32767 눈금, 실측한 사람 발화는 8,500 이상)",
            "loudnessNotice": {"code": "AUDIO_LOUDNESS_DESCRIBE"},
        },
        where="HTTP 503 detail",
        situation="무음(소리 없음)",
    ),
    "STT_TOO_QUIET": _spec(
        "받아쓴 글이 나왔지만 녹음의 소리가 사람이 말한 것이라기에는 너무 작아서 채점하지 않는다"
        "(받아쓰기가 지어낸 글일 수 있다). 측정값: {loudness} / 받아쓴 글 앞부분: \"{preview}\"",
        "A transcript was produced, but the recording is too quiet to be human speech, so it "
        "is not scored (the transcript may be fabricated). Measurements: {loudness} / "
        "Transcript preview: \"{preview}\"",
        # ★ preview 는 응시자가 한국어로 말한 것을 받아쓴 조각이다. 번역하지 말고 그대로 끼운다 ★
        params={"loudness": "str", "preview": "str(한국어 그대로)", "loudnessNotice": NESTED},
        examples={
            "loudness": "가장 큰 0.1초 구간 210.5, 전체 평균 40.2 (0~32767 눈금, 실측한 사람 발화는 8,500 이상)",
            "preview": "안녕하세요 저는 오늘 지각을 했습니다",
            "loudnessNotice": {"code": "AUDIO_LOUDNESS_DESCRIBE"},
        },
        where="HTTP 503 detail",
        situation="소리가 너무 작음(지어낸 글 의심). preview 는 한국어 유지",
    ),
    "AUDIO_LOUDNESS_DESCRIBE": _spec(
        "가장 큰 0.1초 구간 {peak}, 전체 평균 {mean} (0~{scaleMax} 눈금, 실측한 사람 발화는 8,500 이상)",
        "Loudest 0.1s window {peak}, overall average {mean} (scale 0-{scaleMax}; measured human "
        "speech is above 8,500)",
        params={"peak": "float", "mean": "float", "scaleMax": "int"},
        examples={"peak": 210.5, "mean": 40.2, "scaleMax": 32767},
        where="위 두 무음 문구 안에 끼는 측정값",
        situation="소리 크기 측정값 조립",
    ),
    # -----------------------------------------------------------------
    # 1-A. 받아쓰기 실패 (503) — 제공자별
    # -----------------------------------------------------------------
    "STT_CLIENT_UNAVAILABLE": _spec(
        "음성을 글자로 옮길 수 없다. {reason}",
        "The audio cannot be transcribed. {reason}",
        params={"provider": "str", "reason": "str", "reasonNotice": NESTED},
        examples={
            "provider": "gemini",
            "reason": "GEMINI_API_KEY 가 설정되어 있지 않습니다. .env 파일이나 환경변수에 키를 넣어 주세요.",
            "reasonNotice": {"code": "LLM_API_KEY_MISSING"},
        },
        where="HTTP 503 detail",
        situation="받아쓰기 클라이언트를 준비하지 못함(키 없음 등)",
    ),
    "STT_CALL_FAILED": _spec(
        "음성을 글자로 옮기지 못했다. {reason}",
        "The audio could not be transcribed. {reason}",
        params={"provider": "str", "reason": "str", "reasonNotice": NESTED},
        examples={
            "provider": "gemini",
            "reason": "LLM 하루 호출 한도를 다 썼다(429). 한도가 풀리거나 결제를 활성화해야 한다.",
            "reasonNotice": {"code": "LLM_QUOTA_EXHAUSTED"},
        },
        where="HTTP 503 detail",
        situation="받아쓰기 호출 자체가 실패",
    ),
    "STT_LORA_URL_NOT_SET": _spec(
        "음성을 글자로 옮길 수 없다. LoRA 받아쓰기 서버 주소({envVar})가 설정돼 있지 않다.",
        "The audio cannot be transcribed. The LoRA transcription server URL ({envVar}) is not set.",
        params={"envVar": "str"},
        examples={"envVar": "LORA_STT_URL"},
        where="HTTP 503 detail",
        situation="LoRA 서버 주소 미설정",
    ),
    "STT_LORA_TIMEOUT": _spec(
        "음성을 글자로 옮기지 못했다. LoRA 서버가 제한 시간({timeoutSec}초) 안에 답하지 않았다.",
        "The audio could not be transcribed. The LoRA server did not answer within "
        "{timeoutSec} seconds.",
        params={"timeoutSec": "int(초)"},
        examples={"timeoutSec": 120},
        where="HTTP 503 detail",
        situation="LoRA 서버 시간 초과",
    ),
    "STT_LORA_UNREACHABLE": _spec(
        "음성을 글자로 옮기지 못했다. LoRA 받아쓰기 서버에 닿지 못했다"
        "(주소가 맞는지, 서버가 떠 있는지 확인해야 한다).",
        "The audio could not be transcribed. The LoRA transcription server could not be "
        "reached (check the URL and whether the server is running).",
        where="HTTP 503 detail",
        situation="LoRA 서버에 못 닿음",
    ),
    "STT_LORA_HTTP_ERROR": _spec(
        "음성을 글자로 옮기지 못했다. LoRA 서버가 {statusCode} 로 응답했다.",
        "The audio could not be transcribed. The LoRA server answered with {statusCode}.",
        params={"statusCode": "int"},
        examples={"statusCode": 500},
        where="HTTP 503 detail",
        situation="LoRA 서버 4xx/5xx",
    ),
    "STT_LORA_BAD_JSON": _spec(
        "LoRA 서버의 응답을 읽지 못했다(JSON 이 아니다).",
        "The LoRA server response could not be read (it is not JSON).",
        where="HTTP 503 detail",
        situation="LoRA 응답이 JSON 이 아님",
    ),
    "STT_AZURE_WAV_OPEN_FAILED": _spec(
        "음성 파일을 열지 못했다. wav 파일이 맞는지 확인해야 한다.",
        "The audio file could not be opened. Check that it really is a wav file.",
        where="HTTP 503 detail",
        situation="Azure: wav 열기 실패",
    ),
    "STT_AZURE_WAV_NOT_16BIT": _spec(
        "이 음성은 {bits}비트 wav 라서 발음 평가로 보낼 수 없다(16비트 wav 로 녹음해야 한다).",
        "This audio is {bits}-bit wav and cannot be sent for pronunciation assessment "
        "(record it as 16-bit wav).",
        params={"bits": "int"},
        examples={"bits": 32},
        where="HTTP 503 detail",
        situation="Azure: 16비트 wav 아님",
    ),
    "STT_AZURE_KEY_NOT_SET": _spec(
        "음성을 글자로 옮길 수 없다. Azure 음성 서비스 열쇠"
        "(AZURE_SPEECH_KEY / AZURE_SPEECH_REGION)가 설정돼 있지 않다.",
        "The audio cannot be transcribed. The Azure Speech credentials "
        "(AZURE_SPEECH_KEY / AZURE_SPEECH_REGION) are not set.",
        where="HTTP 503 detail",
        situation="Azure: 열쇠 미설정",
    ),
    "STT_AZURE_FORMAT_NOT_WAV": _spec(
        "'{format}' 형식은 Azure 발음 평가로 보낼 수 없다(지금은 wav 만 처리한다).",
        "Format '{format}' cannot be sent to Azure pronunciation assessment (only wav is "
        "supported for now).",
        params={"format": "str"},
        examples={"format": "webm"},
        where="HTTP 503 detail",
        situation="Azure: wav 아닌 형식",
    ),
    "STT_AZURE_SDK_MISSING": _spec(
        "발음 평가에 필요한 Azure 음성 SDK 가 설치돼 있지 않다"
        "(pip install azure-cognitiveservices-speech).",
        "The Azure Speech SDK required for pronunciation assessment is not installed "
        "(pip install azure-cognitiveservices-speech).",
        where="HTTP 503 detail",
        situation="Azure: SDK 미설치",
    ),
    "STT_AZURE_CALL_FAILED": _spec(
        "음성을 글자로 옮기지 못했다. Azure 음성 서비스 호출이 실패했다.",
        "The audio could not be transcribed. The call to the Azure Speech service failed.",
        where="HTTP 503 detail",
        situation="Azure: 호출 실패",
    ),
    "STT_AZURE_TIMEOUT": _spec(
        "발음 평가가 제한 시간({timeoutSec}초) 안에 끝나지 않았다.",
        "Pronunciation assessment did not finish within {timeoutSec} seconds.",
        params={"timeoutSec": "int(초)"},
        examples={"timeoutSec": 60},
        where="HTTP 503 detail",
        situation="Azure: 인식 시간 초과",
    ),
    "STT_AZURE_REQUEST_CANCELED": _spec(
        "음성을 글자로 옮기지 못했다. Azure 음성 서비스가 요청을 거절했다.",
        "The audio could not be transcribed. The Azure Speech service rejected the request.",
        where="HTTP 503 detail",
        situation="Azure: 요청 거절됨",
    ),
    # -----------------------------------------------------------------
    # LLM 실패 사유 (503 detail 로도 나가고, /score 에서는 warnings 안에 끼기도 한다)
    # -----------------------------------------------------------------
    "LLM_QUOTA_EXHAUSTED": _spec(
        "LLM 하루 호출 한도를 다 썼다(429). 한도가 풀리거나 결제를 활성화해야 한다.",
        "The daily LLM request quota is used up (429). Wait for the quota to reset or enable "
        "billing.",
        where="HTTP 503 detail / warnings 안에 끼는 사유",
        endpoint="/score, /generate-items",
        situation="하루 호출 한도 초과",
    ),
    "LLM_MODEL_NOT_FOUND": _spec(
        "요청한 LLM 모델을 쓸 수 없다(404). .env 의 GEMINI_MODEL 을 확인해야 한다.",
        "The requested LLM model is not available (404). Check GEMINI_MODEL in .env.",
        where="HTTP 503 detail / warnings 안에 끼는 사유",
        endpoint="/score, /generate-items",
        situation="모델 없음",
    ),
    "LLM_PERMISSION_DENIED": _spec(
        "LLM 접근이 거부됐다(403). API 키가 올바른지 확인해야 한다.",
        "Access to the LLM was denied (403). Check that the API key is correct.",
        where="HTTP 503 detail / warnings 안에 끼는 사유",
        endpoint="/score, /generate-items",
        situation="접근 거부",
    ),
    "LLM_UNAUTHENTICATED": _spec(
        "LLM 인증에 실패했다(401). API 키를 확인해야 한다.",
        "LLM authentication failed (401). Check the API key.",
        where="HTTP 503 detail / warnings 안에 끼는 사유",
        endpoint="/score, /generate-items",
        situation="인증 실패",
    ),
    "LLM_TIMEOUT": _spec(
        "LLM 응답이 제한 시간 안에 오지 않았다.",
        "The LLM did not answer within the time limit.",
        where="HTTP 503 detail / warnings 안에 끼는 사유",
        endpoint="/score, /generate-items",
        situation="응답 시간 초과",
    ),
    "LLM_SERVER_ERROR": _spec(
        "LLM 서버가 일시적으로 응답하지 않는다.",
        "The LLM server is temporarily not responding.",
        where="HTTP 503 detail / warnings 안에 끼는 사유",
        endpoint="/score, /generate-items",
        situation="서버 일시 오류",
    ),
    # 원 모델이 붐벼서 못 받을 때, 대신 다른 모델이 답한 경우.
    # 실패가 아니라 '이 판정은 평소와 다른 모델이 했다'는 알림이다.
    # 채점 결과를 나중에 다시 볼 때 값이 왜 달라졌는지 설명하려면 이 사실이 남아야 한다.
    "LLM_FALLBACK_MODEL_USED": _spec(
        "{stage} 단계에서 모델 {from} 이(가) 응답하지 못해 대체 모델 {to} 로 판정했습니다.",
        "Stage {stage}: model {from} did not respond, so the fallback model {to} was used.",
        params={
            "from": "str(원래 부르려던 모델)",
            "to": "str(실제로 답한 대체 모델)",
            "stage": "str(errors | checklist | transcript)",
        },
        examples={
            "from": "gemini-3-flash-preview",
            "to": "gemini-3.1-flash-lite",
            "stage": "errors",
        },
        endpoint="/score",
        situation="원 모델이 503(일시적으로 못 받음)이라 대체 모델로 갈아탄 경우",
    ),
    "LLM_CONNECTION_FAILED": _spec(
        "LLM 서버에 연결하지 못했다. 네트워크를 확인해야 한다.",
        "Could not connect to the LLM server. Check the network.",
        where="HTTP 503 detail / warnings 안에 끼는 사유",
        endpoint="/score, /generate-items",
        situation="연결 실패",
    ),
    "LLM_CALL_FAILED": _spec(
        "LLM 호출에 실패했다({excType}).",
        "The LLM call failed ({excType}).",
        params={"excType": "str"},
        examples={"excType": "ValueError"},
        where="HTTP 503 detail / warnings 안에 끼는 사유",
        endpoint="/score, /generate-items",
        situation="그 밖의 실패",
    ),
    "LLM_API_KEY_MISSING": _spec(
        "GEMINI_API_KEY 가 설정되어 있지 않습니다. .env 파일이나 환경변수에 키를 넣어 주세요.",
        "GEMINI_API_KEY is not set. Put the key in the .env file or an environment variable.",
        where="HTTP 503 detail / warnings 안에 끼는 사유",
        endpoint="/score, /generate-items",
        situation="키 미설정",
    ),
    "LLM_RESPONSE_TRUNCATED": _spec(
        "LLM 답이 길이 제한에 걸려 잘렸다(답변 예산이 모자랐다).",
        "The LLM answer was cut off by the length limit (the answer budget was too small).",
        where="HTTP 503 detail / warnings 안에 끼는 사유",
        endpoint="/score, /generate-items",
        situation="답이 잘림(재시도 꺼짐)",
    ),
    "LLM_RESPONSE_TRUNCATED_RETRIED": _spec(
        "LLM 답이 길이 제한에 걸려 잘렸다(예산을 늘려 다시 불러도 마찬가지였다).",
        "The LLM answer was cut off by the length limit (it was still cut off after retrying "
        "with a larger budget).",
        where="HTTP 503 detail / warnings 안에 끼는 사유",
        endpoint="/score, /generate-items",
        situation="답이 잘림(재시도해도)",
    ),
    "LLM_EMPTY_RESPONSE": _spec(
        "LLM이 빈 응답을 보냈다(안전 필터에 걸렸거나 답을 만들지 못했다).",
        "The LLM returned an empty response (it was blocked by a safety filter or produced "
        "no answer).",
        where="HTTP 503 detail / warnings 안에 끼는 사유",
        endpoint="/score, /generate-items",
        situation="빈 응답",
    ),
    "LLM_JSON_PARSE_FAILED": _spec(
        "LLM 응답을 JSON으로 해석하지 못했다.",
        "The LLM response could not be parsed as JSON.",
        where="HTTP 503 detail / warnings 안에 끼는 사유",
        endpoint="/score, /generate-items",
        situation="JSON 해석 실패",
    ),
    "LLM_JSON_NOT_OBJECT": _spec(
        "LLM 응답의 최상위가 JSON 객체가 아니다.",
        "The top level of the LLM response is not a JSON object.",
        where="HTTP 503 detail / warnings 안에 끼는 사유",
        endpoint="/score, /generate-items",
        situation="최상위가 객체 아님",
    ),
    # ★ LLM 이 그때그때 지어낸 문장 ★
    # 판정 이유(reason)처럼 문구가 정해져 있지 않은 자리에 쓴다. 백엔드는 이 코드를 만나면
    # 번역할 고정 문장이 없으므로 `text` 를 그대로 보여 주거나 스스로 번역해야 한다.
    "LLM_FREE_TEXT": _spec(
        "{text}",
        "{text}",
        params={"text": "str(LLM 자유 생성, 고정 문구 아님)"},
        examples={"text": "답안에서 지각한 이유를 밝혔다."},
        where="evidence comment 등",
        situation="LLM 이 자유 생성한 문장(고정 템플릿 없음)",
    ),
    # -----------------------------------------------------------------
    # 1-B. 답안 유효성 가드
    # -----------------------------------------------------------------
    "VALIDITY_INVALID_WRAP": _spec(
        "[채점 무효] {reason}",
        "[Not scored] {reason}",
        params={"reason": "str", "reasonNotice": NESTED},
        examples={
            "reason": "답안의 한글 비율이 12%로 기준(50%)에 못 미쳐 …",
            "reasonNotice": {"code": "VALIDITY_HANGUL_RATIO"},
        },
        situation="하드 가드에 걸려 채점 무효(안쪽 사유를 감싸는 겉 문구)",
    ),
    "VALIDITY_SOFT_WRAP": _spec(
        "[답안 유효성] {reason}",
        "[Answer validity] {reason}",
        params={"reason": "str", "reasonNotice": NESTED},
        examples={
            "reason": "어미가 붙은 문장이 1/5에 그쳐 온전한 문장으로 보기 어렵다.",
            "reasonNotice": {"code": "VALIDITY_NO_SENTENCE_SOFT"},
        },
        situation="소프트 가드(점수는 나가되 표시만 남김)",
    ),
    "VALIDITY_NOT_SCORED_NOTE": _spec(
        "답안 유효성 가드에 걸려 채점하지 않았다: {reason}",
        "Not scored because the answer failed a validity guard: {reason}",
        params={"reason": "str", "reasonNotice": NESTED},
        examples={
            "reason": "답안의 한글 비율이 12%로 기준(50%)에 못 미쳐 …",
            "reasonNotice": {"code": "VALIDITY_HANGUL_RATIO"},
        },
        where="subscore note",
        situation="무효 응답의 영역 note",
    ),
    "VALIDITY_HANGUL_RATIO": _spec(
        "답안의 한글 비율이 {ratio}로 기준({threshold})에 못 미쳐 한국어 답안으로 볼 수 없다. "
        "채점을 무효로 처리했다.",
        "The Korean-script ratio of the answer is {ratio}, below the threshold of {threshold}, "
        "so it cannot be treated as a Korean answer. Scoring was voided.",
        params={"ratio": "str", "threshold": "str"},
        examples={"ratio": "12%", "threshold": "50%"},
        situation="가드A 한글 비율",
    ),
    "VALIDITY_TOO_SHORT": _spec(
        "답안이 {words}어절로 기준({minWords}어절)보다 짧아 오류 자질을 신뢰할 수 없다. "
        "틀릴 기회 자체가 적어 '오류 0건'이 실력의 근거가 되지 못한다.",
        "The answer is {words} words long, shorter than the minimum of {minWords}, so the error "
        "features cannot be trusted. With so few chances to make a mistake, 'zero errors' is "
        "not evidence of ability.",
        params={"words": "int", "minWords": "int"},
        examples={"words": 4, "minWords": 10},
        situation="가드B 최소 길이",
    ),
    "VALIDITY_PROMPT_OVERLAP": _spec(
        "답안 글자의 {ratio}가 지시문과 그대로 겹쳐(기준 {threshold}) 응시자가 직접 쓴 글로 볼 수 없다. "
        "채점을 무효로 처리했다.",
        "{ratio} of the answer's characters are copied verbatim from the prompt (threshold "
        "{threshold}), so it cannot be treated as the test taker's own writing. Scoring was voided.",
        params={"ratio": "str", "threshold": "str"},
        examples={"ratio": "82%", "threshold": "60%"},
        situation="가드C 지시문 겹침",
    ),
    "VALIDITY_NO_SENTENCE_HARD": _spec(
        "어미가 붙은 문장이 {sentences}/{total}뿐이라 낱말을 나열한 글로 보인다. "
        "채점할 문장이 없어 무효로 처리했다.",
        "Only {sentences} of {total} segments carry a sentence ending, so the answer reads as a "
        "list of words. There is no sentence to score, so it was voided.",
        params={"sentences": "int", "total": "int"},
        examples={"sentences": 0, "total": 6},
        situation="가드D 문장 성립(하드)",
    ),
    "VALIDITY_NO_SENTENCE_SOFT": _spec(
        "어미가 붙은 문장이 {sentences}/{total}에 그쳐 온전한 문장으로 보기 어렵다.",
        "Only {sentences} of {total} segments carry a sentence ending, so the answer is hard to "
        "read as complete sentences.",
        params={"sentences": "int", "total": "int"},
        examples={"sentences": 1, "total": 5},
        situation="가드D 문장 성립(소프트)",
    ),
    # -----------------------------------------------------------------
    # 1-B. 신뢰도·점수 결합
    # -----------------------------------------------------------------
    "RELIABILITY_WRAP": _spec(
        "[신뢰도 {level}] {reason}",
        "[Reliability: {level}] {reason}",
        params={"level": "str", "reason": "str", "reasonNotice": NESTED},
        examples={
            "level": "low",
            "reason": "LLM을 쓰지 못해 내용·과제 수행을 핵심어 일치로만 판정했다. …",
            "reasonNotice": {"code": "RELIABILITY_CONTENT_KEYWORD_FALLBACK"},
        },
        endpoint="/score, /finalize",
        situation="채점 신뢰도 표시(안쪽 사유를 감싸는 겉 문구)",
    ),
    "RELIABILITY_CONTENT_KEYWORD_FALLBACK": _spec(
        "LLM을 쓰지 못해 내용·과제 수행을 핵심어 일치로만 판정했다. "
        "이 점수는 내용 판정의 결과가 아니므로 응시자에게 보여주면 안 된다.",
        "The LLM was unavailable, so content/task fulfilment was judged by keyword matching only. "
        "This score is not the result of a content judgement and must not be shown to the test taker.",
        situation="대체 경로(핵심어)로 내용 판정",
    ),
    "RELIABILITY_NO_CHECKLIST": _spec(
        "문항에 체크리스트가 없어 내용·과제 수행을 판정하지 못했다.",
        "The item has no checklist, so content/task fulfilment could not be judged.",
        situation="체크리스트 없음(신뢰도 사유)",
    ),
    "SUBSCORE_PARTIAL_AREAS": _spec(
        "{areas} 영역을 일부 자질 없이 계산했다.",
        "The {areas} area(s) were computed with some features missing.",
        params={"areas": "str"},
        examples={"areas": "언어 사용"},
        situation="자질 일부 누락",
    ),
    "SUBSCORE_NO_FEATURES": _spec(
        "점수를 낼 수 있는 자질이 하나도 없다.",
        "There is not a single feature available to compute a score from.",
        situation="자질이 하나도 없음",
    ),
    "SUBSCORE_NO_SCORABLE_AREA": _spec(
        "점수를 낼 수 있는 영역이 없어 종합 점수를 내지 못했다.",
        "No area could be scored, so no overall score was produced.",
        situation="채점 가능한 영역 없음",
    ),
    "SUBSCORE_AREA_PARTIAL": _spec(
        "'{label}' 영역이 일부 자질 없이 계산되었다: {note}",
        "The '{label}' area was computed with some features missing: {note}",
        params={"label": "str", "note": "str", "noteNotice": NESTED},
        examples={
            "label": "언어 사용",
            "note": "자질 3개(...) 제외 — LLM 사용 불가",
            "noteNotice": {"code": "SUBSCORE_FEATURES_EXCLUDED_GROUP"},
        },
        situation="영역 부분 계산",
    ),
    "SUBSCORE_AREA_FAILED": _spec(
        "'{label}' 영역을 채점하지 못했다: {note}",
        "The '{label}' area could not be scored: {note}",
        params={"label": "str", "note": "str", "noteNotice": NESTED},
        examples={
            "label": "발화 전달력",
            "note": "발음 평가 결과가 없어 채점하지 않았다(종합 점수에서 제외). …",
            "noteNotice": {"code": "SUBSCORE_DELIVERY_NO_PRONUNCIATION"},
        },
        situation="영역 채점 실패",
    ),
    # -----------------------------------------------------------------
    # 1-C. 영역 note
    # -----------------------------------------------------------------
    # 한 영역에 알릴 것이 여러 개면 " / " 로 이어 붙인 한 줄이 note 로 나간다.
    # 그 한 줄을 담을 코드가 아래 것이다. 안쪽 코드 목록(items)을 함께 주므로
    # 백엔드는 각각을 영어로 바꾼 뒤 같은 방식으로 이어 붙이면 된다.
    "SUBSCORE_NOTE_LIST": _spec(
        "{notes}",
        "{notes}",
        params={"notes": "str", "items": "list[notice]"},
        examples={
            "notes": "체크리스트가 없어 충족률을 반영하지 못했다. / 자질 'response_length' 를 쓸 수 없어 가중치를 다시 나눴다.",
            "items": [
                {"code": "SUBSCORE_CHECKLIST_MISSING"},
                {"code": "SUBSCORE_FEATURE_EXCLUDED"},
            ],
        },
        where="subscore note",
        situation="한 영역에 알릴 것이 둘 이상일 때 ' / ' 로 이어 붙인 묶음",
    ),
    "SUBSCORE_DELIVERY_NO_PRONUNCIATION": _spec(
        "발음 평가 결과가 없어 채점하지 않았다(종합 점수에서 제외). "
        "쓰기 답안이거나, 발음을 재지 못하는 받아쓰기로 채점한 경우다.",
        "No pronunciation assessment result, so this area was not scored (excluded from the "
        "overall score). This happens for writing answers, or when transcription was done by a "
        "provider that cannot measure pronunciation.",
        where="subscore note",
        situation="발음 평가 없음(delivery)",
    ),
    "SUBSCORE_CHECKLIST_FALLBACK": _spec(
        "체크리스트가 임시 대체 판정(핵심어 일치)으로 매겨졌다.",
        "The checklist was judged by the provisional fallback (keyword matching).",
        where="subscore note",
        situation="체크리스트 임시 판정",
    ),
    "SUBSCORE_CHECKLIST_MISSING": _spec(
        "체크리스트가 없어 충족률을 반영하지 못했다.",
        "There is no checklist, so the fulfilment rate could not be reflected.",
        where="subscore note",
        situation="체크리스트 없음(영역)",
    ),
    "SUBSCORE_FEATURE_EXCLUDED": _spec(
        "자질 '{featureId}' 를 쓸 수 없어 가중치를 다시 나눴다.",
        "Feature '{featureId}' is unavailable, so the weights were redistributed.",
        params={"featureId": "str"},
        examples={"featureId": "pron_accuracy"},
        where="subscore note",
        situation="자질 제외(내용·발음 영역 공통)",
    ),
    "SUBSCORE_BANMAL_UNAVAILABLE": _spec(
        "반말 혼입 횟수를 확인할 수 없어 가중치를 다시 나눴다.",
        "The count of casual-speech intrusions could not be determined, so the weights were "
        "redistributed.",
        where="subscore note",
        situation="반말 확인 불가",
    ),
    "SUBSCORE_FEATURES_EXCLUDED_GROUP": _spec(
        "자질 {count}개({featureIds}) 제외 — {reason}",
        "{count} feature(s) excluded ({featureIds}) - {reason}",
        params={"count": "int", "featureIds": "str", "reason": "str", "reasonNotice": NESTED},
        examples={
            "count": 4,
            "featureIds": "err_particle, err_ending, err_lexical, err_honorific",
            "reason": "LLM 사용 불가",
            "reasonNotice": {"code": "LLM_FREE_TEXT"},
        },
        where="subscore note",
        situation="자질 묶음 제외(언어 사용)",
    ),
    # -----------------------------------------------------------------
    # 1-B. 전사 보정 / 오류 자질 / STT 안내
    # -----------------------------------------------------------------
    "TRANSCRIPT_SKIPPED_FOR_WRITING": _spec(
        "쓰기 답안에는 STT 전사 보정을 적용하지 않는다. 응시자가 직접 입력한 글이므로 "
        "보정하면 실제 오류가 지워진다.",
        "STT transcript correction is not applied to writing answers. The text was typed by the "
        "test taker, so correcting it would erase real errors.",
        situation="쓰기에 보정 요청",
    ),
    "TRANSCRIPT_APPLIED": _spec(
        "STT 전사 보정을 {count}군데 적용했다. 보정본은 내용·과제 수행에만 쓰이고, "
        "문법·어휘는 전사 원문으로 채점했다.",
        "STT transcript correction was applied in {count} place(s). The corrected text is used "
        "only for content/task fulfilment; grammar and vocabulary were scored on the raw transcript.",
        params={"count": "int"},
        examples={"count": 3},
        situation="보정 적용됨",
    ),
    "ERRORS_UNEXPECTED_FAILURE": _spec(
        "오류 자질 추출이 예기치 않게 실패했다: {reason}",
        "Error-feature extraction failed unexpectedly: {reason}",
        params={"reason": "str"},
        examples={"reason": "KeyError('errors')"},
        situation="오류 자질 예외(방어)",
    ),
    "CHECKLIST_UNEXPECTED_FAILURE": _spec(
        "체크리스트 판정이 예기치 않게 실패했다: {reason}",
        "Checklist judging failed unexpectedly: {reason}",
        params={"reason": "str"},
        examples={"reason": "TimeoutError()"},
        situation="체크리스트 예외(방어)",
    ),
    "TRANSCRIPT_LOW_CONFIDENCE_OVERLAP": _spec(
        "오류 지적 {count}건이 STT 보정 구간과 겹쳐 신뢰도 낮음으로 표시됐다. "
        "전사 오류를 문법 오류로 잘못 센 것일 수 있으니 감점 근거로 쓸 때 확인이 필요하다.",
        "{count} error finding(s) overlap a corrected region of the transcript and were marked "
        "low-confidence. They may be transcription errors miscounted as grammar errors, so check "
        "them before using them to deduct points.",
        params={"count": "int"},
        examples={"count": 2},
        situation="보정 구간과 오류 지적이 겹침",
    ),
    "STT_SCORED_FROM_TRANSCRIPT": _spec(
        "음성을 {provider}({model})로 받아쓴 글을 채점했다. 받아쓰기가 응시자의 말과 다를 수 있으므로 "
        "이의가 있으면 meta.stt_transcript 와 원본 녹음을 함께 확인해야 한다.",
        "The audio was transcribed by {provider} ({model}) and that text was scored. The "
        "transcript may differ from what the test taker actually said, so check "
        "meta.stt_transcript together with the original recording if it is disputed.",
        params={"provider": "str", "model": "str"},
        examples={"provider": "lora", "model": "whisper-large-v3-ko-lora"},
        situation="받아쓴 글로 채점함",
    ),
    "STT_PRONUNCIATION_UNAVAILABLE": _spec(
        "발음 평가를 하지 못해 발화 전달력(delivery)은 채점하지 않았다(전사는 {provider} 로 정상 처리됨).",
        "Pronunciation could not be assessed, so delivery was not scored (transcription by "
        "{provider} succeeded).",
        params={"provider": "str"},
        examples={"provider": "lora"},
        situation="발음 못 잼",
    ),
    "STT_PRONUNCIATION_SEPARATE": _spec(
        "발화 전달력(delivery)은 {pronouncer} 발음평가로 따로 채점했다(받아쓰기는 {sttProvider}).",
        "Delivery was scored separately by {pronouncer} pronunciation assessment "
        "(transcription was done by {sttProvider}).",
        params={"pronouncer": "str", "sttProvider": "str"},
        examples={"pronouncer": "azure", "sttProvider": "lora"},
        situation="발음 따로 채점",
    ),
    "AUDIO_DURATION_UNMEASURABLE": _spec(
        "{format} 형식은 파일에서 길이를 재지 못한다. 녹음 길이가 필요하면 "
        "audio.duration_ms 로 알려 줘야 한다.",
        "The duration of a {format} file cannot be measured from the file itself. If the "
        "recording length is needed, send it as audio.duration_ms.",
        params={"format": "str"},
        examples={"format": "webm"},
        situation="압축 형식이라 길이를 못 잼",
    ),
    "AZURE_READALOUD_REFERENCE_USED": _spec(
        "낭독형 문항이라 제시문을 정답지로 주고 발음을 평가했다. 받아쓴 글이 제시문 쪽으로 "
        "맞춰졌을 수 있으므로 문법 채점의 근거로 쓸 때 확인이 필요하다.",
        "This is a read-aloud item, so the given passage was used as the reference text for "
        "pronunciation assessment. The transcript may have been pulled toward that passage, so "
        "check it before using it as evidence for grammar scoring.",
        situation="낭독형 정답지 사용",
    ),
    "AZURE_NO_PROSODY_SCORE": _spec(
        "억양·강세 점수(ProsodyScore)를 받지 못해 발화 전달력에서 억양은 채점하지 않았다.",
        "No ProsodyScore was returned, so intonation was not scored within delivery.",
        situation="억양 점수 없음",
    ),
    "AZURE_COMPLETENESS_UNUSED": _spec(
        "자유 발화라서 읽을 원문이 없다. 발화 완전성(completeness)은 채점에 쓰지 않았다.",
        "This is free speech, so there is no reference text to read. Completeness was not used "
        "in scoring.",
        situation="자유 발화 완전성 미사용",
    ),
    # -----------------------------------------------------------------
    # 1-B. 오류 자질(errors.py)
    # -----------------------------------------------------------------
    "ERRORS_LLM_DISABLED": _spec(
        "LLM 사용이 꺼져 있어 오류 자질(조사·어미·어휘·높임법)을 계산하지 못했다.",
        "LLM use is turned off, so the error features (particles, endings, word choice, honorifics) "
        "could not be computed.",
        situation="LLM 껐음(오류 자질)",
    ),
    "ERRORS_API_KEY_MISSING": _spec(
        "GEMINI_API_KEY 가 없어 오류 자질을 계산하지 못했다. "
        "언어 사용 점수는 규칙 자질만으로 계산된 임시 결과다.",
        "GEMINI_API_KEY is missing, so the error features could not be computed. The language-use "
        "score is a provisional result computed from rule-based features only.",
        situation="키 없음(오류 자질)",
    ),
    "ERRORS_EXTRACTION_FAILED": _spec(
        "LLM 오류 자질 추출 실패(규칙 자질만으로 진행): {reason}",
        "LLM error-feature extraction failed (continuing with rule-based features only): {reason}",
        params={"reason": "str", "reasonNotice": NESTED},
        examples={
            "reason": "LLM 하루 호출 한도를 다 썼다(429). …",
            "reasonNotice": {"code": "LLM_QUOTA_EXHAUSTED"},
        },
        situation="오류 자질 추출 실패",
    ),
    "ERRORS_NO_ERRORS_LIST": _spec(
        "LLM 응답에 errors 목록이 없어 오류를 0건으로 처리했다.",
        "The LLM response has no 'errors' list, so the error count was treated as zero.",
        situation="errors 목록 없음",
    ),
    # -----------------------------------------------------------------
    # 1-B. 인용 검증(citation.py)
    # -----------------------------------------------------------------
    "CITATION_DISCARDED_WRAP": _spec(
        "인용 폐기: '{quote}' — {reason}",
        "Citation discarded: '{quote}' - {reason}",
        params={"quote": "str(한국어 그대로)", "reason": "str", "reasonNotice": NESTED},
        examples={
            "quote": "저는 늦었습니다",
            "reason": "답안 원문에서 찾을 수 없는 인용(폐기)",
            "reasonNotice": {"code": "CITATION_NOT_FOUND"},
        },
        situation="인용 폐기(안쪽 사유를 감싸는 겉 문구). quote 는 응시자 답안 조각이라 한국어 유지",
    ),
    "CITATION_EMPTY": _spec(
        "인용이 비어 있음",
        "The citation is empty",
        situation="폐기 사유: 빈 인용",
    ),
    "CITATION_TOO_SHORT": _spec(
        "인용이 너무 짧아 근거로 인정하지 않음(최소 {minLength}자)",
        "The citation is too short to count as evidence (minimum {minLength} characters)",
        params={"minLength": "int"},
        examples={"minLength": 2},
        situation="폐기 사유: 너무 짧음",
    ),
    "CITATION_ITEM_MALFORMED": _spec(
        "형식이 올바르지 않은 항목",
        "The item is not in a valid format",
        situation="폐기 사유: LLM 이 사전(dict) 이 아닌 값을 섞어 보냄",
    ),
    "CITATION_FIELD_MISSING": _spec(
        "인용 필드가 없음",
        "The citation field is missing",
        situation="폐기 사유: 인용을 담을 자리가 아예 없음",
    ),
    "CITATION_NOT_FOUND": _spec(
        "답안 원문에서 찾을 수 없는 인용(폐기)",
        "The citation cannot be found in the original answer (discarded)",
        situation="폐기 사유: 원문에 없음",
    ),
    # -----------------------------------------------------------------
    # 1-B. 전사 보정(transcript.py)
    # -----------------------------------------------------------------
    "TRANSCRIPT_REASON_DISCARDED": _spec(
        "전사 보정 사유 폐기: '{claimed}' — {reason}",
        "Transcript correction reason discarded: '{claimed}' - {reason}",
        params={"claimed": "str(한국어 그대로)", "reason": "str", "reasonNotice": NESTED},
        examples={
            "claimed": "안녕하십니까",
            "reason": "답안 원문에서 찾을 수 없는 인용(폐기)",
            "reasonNotice": {"code": "CITATION_NOT_FOUND"},
        },
        situation="보정 사유의 인용이 원문에 없어 폐기",
    ),
    "TRANSCRIPT_NO_CORRECTED_TEXT": _spec(
        "전사 보정 응답에 corrected_text 가 없어 원문을 그대로 쓴다.",
        "The correction response has no corrected_text, so the raw transcript is used as is.",
        situation="보정본 없음",
    ),
    "TRANSCRIPT_NOTHING_TO_FIX": _spec(
        "전사 보정에서 고칠 곳을 찾지 못해 원문을 그대로 쓴다.",
        "The correction found nothing to fix, so the raw transcript is used as is.",
        situation="고칠 곳 없음",
    ),
    "TRANSCRIPT_OVERCORRECTION_DISCARDED": _spec(
        "※ 전사 보정 폐기 ※ 원문의 {changedRatio}가 바뀌어 과보정으로 판단했다"
        "(허용 한도 {maxRatio}). 보정 없이 원문으로 채점한다.",
        "*** Correction discarded *** {changedRatio} of the transcript was changed, which counts "
        "as over-correction (limit {maxRatio}). Scoring proceeds on the raw transcript.",
        params={"changedRatio": "str", "maxRatio": "str"},
        examples={"changedRatio": "38%", "maxRatio": "25%"},
        situation="과보정 폐기",
    ),
    "TRANSCRIPT_SOURCE_EMPTY": _spec(
        "전사 원문이 비어 있어 보정하지 않았다.",
        "The raw transcript is empty, so no correction was made.",
        situation="원문 비어 있음",
    ),
    "TRANSCRIPT_LLM_DISABLED": _spec(
        "LLM 사용이 꺼져 있어 STT 전사 보정을 하지 않았다. 내용·과제 수행도 전사 원문 그대로 채점된다.",
        "LLM use is turned off, so no STT transcript correction was made. Content/task fulfilment "
        "is also scored on the raw transcript.",
        situation="LLM 껐음(보정)",
    ),
    "TRANSCRIPT_API_KEY_MISSING": _spec(
        "GEMINI_API_KEY 가 없어 STT 전사 보정을 하지 못했다. 내용·과제 수행이 전사 오류의 영향을 "
        "그대로 받는다.",
        "GEMINI_API_KEY is missing, so no STT transcript correction could be made. Content/task "
        "fulfilment is fully exposed to transcription errors.",
        situation="키 없음(보정)",
    ),
    "TRANSCRIPT_FAILED": _spec(
        "STT 전사 보정 실패(원문으로 채점 진행): {reason}",
        "STT transcript correction failed (scoring proceeds on the raw transcript): {reason}",
        params={"reason": "str", "reasonNotice": NESTED},
        examples={
            "reason": "LLM 서버가 일시적으로 응답하지 않는다.",
            "reasonNotice": {"code": "LLM_SERVER_ERROR"},
        },
        situation="보정 실패",
    ),
    # -----------------------------------------------------------------
    # 1-B. 체크리스트 판정(checklist.py) warnings
    # -----------------------------------------------------------------
    "CHECKLIST_NO_RESULTS_LIST": _spec(
        "LLM 응답에 results 목록이 없어 전 항목을 미충족으로 처리했다.",
        "The LLM response has no 'results' list, so every checklist item was treated as unmet.",
        situation="results 목록 없음",
    ),
    "CHECKLIST_ITEM_MISSING_VERDICT": _spec(
        "체크리스트 '{itemId}' 에 대한 LLM 판정이 없어 0으로 처리했다.",
        "There is no LLM verdict for checklist item '{itemId}', so it was scored 0.",
        params={"itemId": "str"},
        examples={"itemId": "c1"},
        situation="항목 판정 누락",
    ),
    "CHECKLIST_CITATION_DISCARDED": _spec(
        "체크리스트 '{itemId}': 충족 판정의 근거 인용이 원문에 없어 폐기하고 미충족(0)으로 내렸다 — {reason}",
        "Checklist item '{itemId}': the citation backing the 'met' verdict is not in the original "
        "answer, so it was discarded and the item was lowered to unmet (0) - {reason}",
        params={"itemId": "str", "reason": "str", "reasonNotice": NESTED},
        examples={
            "itemId": "c2",
            "reason": "답안 원문에서 찾을 수 없는 인용(폐기)",
            "reasonNotice": {"code": "CITATION_NOT_FOUND"},
        },
        situation="근거 인용 폐기",
    ),
    "CHECKLIST_FALLBACK_USED": _spec(
        "※ 임시 ※ LLM을 쓸 수 없어 체크리스트를 핵심어 일치로만 판정했다. "
        "이 결과는 내용 판정이 아니라 대체값이며 운영 채점에 쓸 수 없다.",
        "*** Provisional *** The LLM was unavailable, so the checklist was judged by keyword "
        "matching only. This is a fallback value, not a content judgement, and must not be used "
        "for operational scoring.",
        situation="임시 대체 판정 안내",
    ),
    "CHECKLIST_NONE": _spec(
        "문항에 체크리스트가 없어 내용·과제 수행을 판정할 수 없다.",
        "The item has no checklist, so content/task fulfilment cannot be judged.",
        situation="체크리스트 없음",
    ),
    "CHECKLIST_LLM_UNUSED_WRAP": _spec(
        "LLM 미사용 사유: {reason}",
        "Reason the LLM was not used: {reason}",
        params={"reason": "str", "reasonNotice": NESTED},
        examples={
            "reason": "GEMINI_API_KEY 없음",
            "reasonNotice": {"code": "CHECKLIST_API_KEY_MISSING"},
        },
        situation="LLM 미사용 사유(안쪽 사유를 감싸는 겉 문구)",
    ),
    "CHECKLIST_LLM_DISABLED_OPTION": _spec(
        "옵션에서 LLM 사용을 껐다",
        "LLM use was turned off in the options",
        situation="LLM 미사용 사유 값",
    ),
    "CHECKLIST_API_KEY_MISSING": _spec(
        "GEMINI_API_KEY 없음",
        "GEMINI_API_KEY is missing",
        situation="LLM 미사용 사유 값",
    ),
    "CHECKLIST_JUDGE_FAILED": _spec(
        "LLM 체크리스트 판정 실패: {reason}",
        "LLM checklist judging failed: {reason}",
        params={"reason": "str", "reasonNotice": NESTED},
        examples={
            "reason": "LLM 응답을 JSON으로 해석하지 못했다.",
            "reasonNotice": {"code": "LLM_JSON_PARSE_FAILED"},
        },
        situation="체크리스트 판정 실패",
    ),
    # -----------------------------------------------------------------
    # 5. 체크리스트 채점 근거 (evidence comment / note)
    # -----------------------------------------------------------------
    "CHECKLIST_COMMENT_NO_VERDICT": _spec(
        "LLM이 이 항목을 판정하지 않아 미충족으로 처리했다.",
        "The LLM did not judge this item, so it was treated as unmet.",
        where="evidence comment",
        situation="판정 누락",
    ),
    "CHECKLIST_NOTE_NO_VERDICT": _spec(
        "LLM 응답 누락",
        "LLM response missing",
        where="checklist note",
        situation="판정 누락",
    ),
    "CHECKLIST_COMMENT_UNMET_FALLBACK": _spec(
        "답안에서 해당 내용을 찾지 못했다.",
        "This content was not found in the answer.",
        where="evidence comment",
        situation="미충족 기본 문구(LLM 이 reason 을 비웠을 때)",
    ),
    "CHECKLIST_COMMENT_CITATION_DISCARDED": _spec(
        "LLM은 충족이라고 했으나 근거 인용이 답안 원문에 없어 폐기했다. ({reason})",
        "The LLM judged this met, but the supporting citation is not in the original answer, so "
        "it was discarded. ({reason})",
        params={"reason": "str", "reasonNotice": NESTED},
        examples={
            "reason": "답안 원문에서 찾을 수 없는 인용(폐기)",
            "reasonNotice": {"code": "CITATION_NOT_FOUND"},
        },
        where="evidence comment",
        situation="인용 폐기",
    ),
    "CHECKLIST_NOTE_CITATION_DISCARDED": _spec(
        "근거 인용 폐기로 미충족 처리",
        "Marked unmet because the supporting citation was discarded",
        where="checklist note",
        situation="인용 폐기",
    ),
    "CHECKLIST_COMMENT_MET_FALLBACK": _spec(
        "답안에서 해당 내용을 확인했다.",
        "This content was confirmed in the answer.",
        where="evidence comment",
        situation="충족 기본 문구(LLM 이 reason 을 비웠을 때)",
    ),
    "CHECKLIST_COMMENT_FALLBACK_MET": _spec(
        "※ 임시 판정 ※ 핵심어 '{keyword}' 가 답안에 나타남",
        "*** Provisional verdict *** the keyword '{keyword}' appears in the answer",
        params={"keyword": "str(한국어 그대로)"},
        examples={"keyword": "지각"},
        where="evidence comment",
        situation="임시 대체 판정(충족). keyword 는 한국어 핵심어라 그대로 유지",
    ),
    "CHECKLIST_NOTE_FALLBACK": _spec(
        "※ 임시 ※ 핵심어 일치 기반 대체 판정(LLM 미사용)",
        "*** Provisional *** fallback verdict based on keyword matching (LLM not used)",
        where="checklist note",
        situation="임시 판정",
    ),
    "CHECKLIST_COMMENT_FALLBACK_UNMET": _spec(
        "※ 임시 판정 ※ 관련 핵심어가 답안에서 발견되지 않음",
        "*** Provisional verdict *** no related keyword was found in the answer",
        where="evidence comment",
        situation="임시 대체 판정(미충족)",
    ),
    "CHECKLIST_MET": _spec(
        "충족",
        "Met",
        where="evidence comment 안의 마크",
        situation="체크리스트 충족 표시",
    ),
    "CHECKLIST_UNMET": _spec(
        "미충족",
        "Unmet",
        where="evidence comment 안의 마크",
        situation="체크리스트 미충족 표시",
    ),
    "CHECKLIST_EVIDENCE_WRAP": _spec(
        "[{mark}] {description} — {comment}",
        "[{mark}] {description} - {comment}",
        params={
            "mark": "str",
            "markNotice": NESTED,
            "description": "str(문항 데이터, 한국어 그대로)",
            "comment": "str",
            "commentNotice": NESTED,
        },
        examples={
            "mark": "충족",
            "markNotice": {"code": "CHECKLIST_MET"},
            "description": "지각한 이유를 말했는가",
            "comment": "답안에서 해당 내용을 확인했다.",
            "commentNotice": {"code": "CHECKLIST_COMMENT_MET_FALLBACK"},
        },
        where="subscore evidence comment",
        situation="체크리스트 근거를 영역 근거로 올릴 때의 겉 문구. description 은 문항 원문이라 번역 대상 아님",
    ),
    "FINALIZE_EVIDENCE_WRAP": _spec(
        "[문항 {itemId}] {comment}",
        "[Item {itemId}] {comment}",
        params={"itemId": "str", "comment": "str", "commentNotice": NESTED},
        examples={
            "itemId": "W-001",
            "comment": "[충족] 지각한 이유를 말했는가 — 답안에서 해당 내용을 확인했다.",
            "commentNotice": {"code": "CHECKLIST_EVIDENCE_WRAP"},
        },
        where="subscore evidence comment",
        endpoint="/finalize",
        situation="최종 등급의 영역 근거 겉 문구",
    ),
    # -----------------------------------------------------------------
    # 참고: 유효성 가드 · 전사 보정 근거 comment
    # -----------------------------------------------------------------
    "VALIDITY_EVIDENCE_NON_HANGUL_RUN": _spec(
        "한국어가 아닌 글자가 이어지는 구간",
        "A run of non-Korean characters",
        where="evidence comment",
        situation="가드A 근거",
    ),
    "VALIDITY_EVIDENCE_HEAD": _spec(
        "답안 앞부분 (한글 {hangul}자 / 센 글자 {counted}자)",
        "Beginning of the answer ({hangul} Korean characters out of {counted} counted)",
        params={"hangul": "int", "counted": "int"},
        examples={"hangul": 12, "counted": 100},
        where="evidence comment",
        situation="가드A 근거",
    ),
    "VALIDITY_EVIDENCE_WORD_COUNT": _spec(
        "답안 전체 {words}어절",
        "{words} words in the whole answer",
        params={"words": "int"},
        examples={"words": 4},
        where="evidence comment",
        situation="가드B 근거",
    ),
    "VALIDITY_EVIDENCE_PROMPT_COPY": _spec(
        "지시문에 그대로 있는 구간",
        "A run copied verbatim from the prompt",
        where="evidence comment",
        situation="가드C 근거",
    ),
    "VALIDITY_EVIDENCE_NO_ENDING": _spec(
        "어미(서술어)가 없어 문장으로 보기 어려운 조각",
        "A fragment with no predicate ending, hard to read as a sentence",
        where="evidence comment",
        situation="가드D 근거",
    ),
    "TRANSCRIPT_EVIDENCE_WRAP": _spec(
        "STT 전사 보정: {change} — {reason}",
        "STT transcript correction: {change} - {reason}",
        params={"change": "str(한국어 그대로)", "reason": "str(LLM 자유 생성)"},
        examples={"change": "'안년하세요' → '안녕하세요'", "reason": "발음이 비슷한 오전사"},
        where="evidence comment",
        situation="전사 보정 근거. change 는 응시자 발화 조각이라 한국어 유지",
    ),
    "TRANSCRIPT_EVIDENCE_NO_REASON": _spec(
        "STT 전사 보정: {change}",
        "STT transcript correction: {change}",
        params={"change": "str(한국어 그대로)"},
        examples={"change": "'안년하세요' → '안녕하세요'"},
        where="evidence comment",
        situation="전사 보정 근거(LLM 이 사유를 안 준 경우)",
    ),
    "RELIABILITY_LOW_EVIDENCE_WRAP": _spec(
        "[신뢰도 낮음] {comment}",
        "[Low confidence] {comment}",
        params={"comment": "str", "commentNotice": NESTED},
        examples={
            "comment": "조사 '을' 자리에 '를' 을 썼다",
            "commentNotice": {"code": "LLM_FREE_TEXT"},
        },
        where="evidence comment",
        situation="보정 구간에서 나온 오류 지적을 감싸는 겉 문구",
    ),
    "RELIABILITY_LOW_EVIDENCE_DETAIL": _spec(
        "이 구간은 STT 전사 보정이 일어난 자리다. 응시자의 문법 오류가 아니라 전사 오류일 수 있다.",
        "This span is where the STT transcript was corrected. It may be a transcription error "
        "rather than a grammar error by the test taker.",
        where="evidence detail",
        situation="저신뢰 사유",
    ),
    "RELIABILITY_LOW_NOTE": _spec(
        "이 중 {count}건은 STT 보정 구간에서 나온 지적이라 신뢰도가 낮다(전사 오류일 가능성).",
        "{count} of these findings come from a corrected span of the transcript and are therefore "
        "low-confidence (they may be transcription errors).",
        params={"count": "int"},
        examples={"count": 2},
        where="feature note",
        situation="저신뢰 note",
    ),
    "TRANSCRIPT_CORRECTED_FEATURE_NOTE": _spec(
        "내용·과제 수행 영역에 쓰이는 자질이라 보정본 기준으로 계산했다. "
        "근거의 글자 위치도 보정본 기준이다.",
        "This feature feeds the content/task area, so it was computed on the corrected transcript. "
        "The character offsets in the evidence also refer to the corrected transcript.",
        where="feature note",
        situation="보정본 기준 자질 note",
    ),
    # -----------------------------------------------------------------
    # 2. /finalize
    # -----------------------------------------------------------------
    "FINALIZE_EXCLUDED_PENDING": _spec(
        "채점이 끝나지 않은 문항 {count}개를 빼고 계산했다: {itemIds}",
        "{count} item(s) whose scoring has not finished were excluded: {itemIds}",
        params={"count": "int", "itemIds": "str"},
        examples={"count": 2, "itemIds": "W-003, S-002"},
        endpoint="/finalize",
        situation="채점 안 끝난 문항 제외",
    ),
    "FINALIZE_EXCLUDED_MISSING": _spec(
        "결과가 넘어오지 않은 문항 {count}개를 빼고 계산했다: {itemIds}",
        "{count} item(s) whose results never arrived were excluded: {itemIds}",
        params={"count": "int", "itemIds": "str"},
        examples={"count": 1, "itemIds": "S-004"},
        endpoint="/finalize",
        situation="결과 안 온 문항 제외",
    ),
    "FINALIZE_EXCLUDED_FAILED": _spec(
        "채점에 실패한 문항 {count}개를 빼고 계산했다: {itemIds}",
        "{count} item(s) that failed scoring were excluded: {itemIds}",
        params={"count": "int", "itemIds": "str"},
        examples={"count": 1, "itemIds": "S-001"},
        endpoint="/finalize",
        situation="실패 문항 제외",
    ),
    "FINALIZE_RELIABILITY_REASON": _spec(
        "문항 {count}개({itemIds})의 채점이 온전하지 않다 — {worstReason}",
        "The scoring of {count} item(s) ({itemIds}) is not intact - {worstReason}",
        params={"count": "int", "itemIds": "str", "worstReason": "str"},
        examples={
            "count": 2,
            "itemIds": "W-001, W-002",
            "worstReason": "LLM을 쓰지 못해 내용·과제 수행을 핵심어 일치로만 판정했다. …",
        },
        endpoint="/finalize",
        situation="신뢰도 사유",
    ),
    "FINALIZE_RELIABILITY_REASON_PLAIN": _spec(
        "문항 {count}개({itemIds})의 채점이 온전하지 않다",
        "The scoring of {count} item(s) ({itemIds}) is not intact",
        params={"count": "int", "itemIds": "str"},
        examples={"count": 1, "itemIds": "W-003"},
        endpoint="/finalize",
        situation="신뢰도 사유(문항별 사유가 비어 있을 때)",
    ),
    "FINALIZE_GRADE_WITHHELD": _spec(
        "채점된 문항이 부족해 최종 등급을 확정하지 않았다 (채점 {scored}/{total}문항, 비중 {weight}). "
        "기준: 최소 {minItems}문항 이상이며 비중 {minWeight} 이상. ※ 이 기준값은 임시값이다.",
        "The final grade was withheld because too few items were scored ({scored}/{total} items, "
        "weight {weight}). Requirement: at least {minItems} items and weight {minWeight} or more. "
        "*** These thresholds are provisional. ***",
        params={
            "scored": "int",
            "total": "int",
            "weight": "str",
            "minItems": "int",
            "minWeight": "str",
        },
        examples={"scored": 2, "total": 8, "weight": "25%", "minItems": 4, "minWeight": "50%"},
        endpoint="/finalize",
        situation="문항 부족(등급 미확정)",
    ),
    "FINALIZE_CROSS_CHECK_WRAP": _spec(
        "교차검증 신호: {note}",
        "Cross-check signal: {note}",
        params={"note": "str", "noteNotice": NESTED},
        examples={
            "note": "말하기 3급 / 쓰기 6급 로 3등급 차이가 난다(쓰기 쪽이 높음). …",
            "noteNotice": {"code": "FINALIZE_CROSS_CHECK_GAP"},
        },
        endpoint="/finalize",
        situation="교차검증 신호(안쪽 사유를 감싸는 겉 문구)",
    ),
    "FINALIZE_CROSS_CHECK_GAP": _spec(
        "말하기 {speaking} / 쓰기 {writing} 로 {gap}등급 차이가 난다({higher} 쪽이 높음). "
        "사람이 한 번 확인해 볼 것을 권한다. ※ 이것은 검토 권장 신호일 뿐이며 부정행위 판정이 아니다. "
        "기준값 {threshold}등급은 임시값이다.",
        "Speaking {speaking} / writing {writing} - a gap of {gap} grade(s) ({higher} is higher). "
        "A human review is recommended. *** This is only a review hint, not a cheating verdict. "
        "The threshold of {threshold} grade(s) is provisional. ***",
        params={
            "speaking": "str",
            "writing": "str",
            "gap": "int",
            "higher": "str",
            "threshold": "int",
        },
        examples={
            "speaking": "3급",
            "writing": "6급",
            "gap": 3,
            "higher": "쓰기",
            "threshold": 2,
        },
        endpoint="/finalize",
        situation="교차검증 걸림",
    ),
    "FINALIZE_CROSS_CHECK_OK": _spec(
        "말하기 {speaking} / 쓰기 {writing}, {gap}등급 차이로 기준값({threshold}등급) 안에 있다.",
        "Speaking {speaking} / writing {writing}, a gap of {gap} grade(s), within the threshold of "
        "{threshold} grade(s).",
        params={"speaking": "str", "writing": "str", "gap": "int", "threshold": "int"},
        examples={"speaking": "4급", "writing": "5급", "gap": 1, "threshold": 2},
        endpoint="/finalize",
        situation="교차검증 정상",
    ),
    "FINALIZE_CROSS_CHECK_ONE_MODE_MISSING": _spec(
        "말하기와 쓰기 중 한쪽이 채점되지 않아 교차검증을 할 수 없었다.",
        "One of speaking and writing was not scored, so the cross-check could not be done.",
        endpoint="/finalize",
        situation="교차검증 불가(한쪽 미채점)",
    ),
    "FINALIZE_CROSS_CHECK_UNKNOWN_GRADE": _spec(
        "등급 표에 없는 값이 들어와 교차검증을 할 수 없었다.",
        "A value outside the grade table arrived, so the cross-check could not be done.",
        endpoint="/finalize",
        situation="교차검증 불가(등급 표 밖)",
    ),
    "FINALIZE_CROSS_CHECK_TOO_FEW_ITEMS": _spec(
        "채점된 문항이 부족해 교차검증을 하지 않았다.",
        "Too few items were scored, so the cross-check was not done.",
        endpoint="/finalize",
        situation="교차검증 불가(문항 부족)",
    ),
    "FINALIZE_AREA_DELIVERY_NOT_INTRODUCED": _spec(
        "Azure 발음평가 미도입으로 이번 범위에서 채점하지 않는다(종합 점수에서 제외).",
        "Azure pronunciation assessment is not in place yet, so this area is out of scope and not "
        "scored (excluded from the overall score).",
        where="subscore note",
        endpoint="/finalize",
        situation="영역 note: 발음 미도입",
    ),
    "FINALIZE_AREA_NO_ITEMS": _spec(
        "이 영역을 채점한 문항이 없어 최종 점수를 내지 못했다.",
        "No item scored this area, so no final score could be produced.",
        where="subscore note",
        endpoint="/finalize",
        situation="영역 note: 채점 문항 없음",
    ),
    "FINALIZE_AREA_WEIGHTED_MEAN": _spec(
        "문항별 채점 결과를 문항 비중으로 평균했다.",
        "The per-item scores were averaged using the item weights.",
        where="subscore note",
        endpoint="/finalize",
        situation="영역 note: 정상 평균",
    ),
    "FINALIZE_AREA_PARTIAL": _spec(
        "일부 문항이 자질 누락 상태로 채점되어 최종 점수도 부분 결과다.",
        "Some items were scored with features missing, so the final score is a partial result too.",
        where="subscore note",
        endpoint="/finalize",
        situation="영역 note: 부분 결과",
    ),
    # -----------------------------------------------------------------
    # 3. /generate-items
    # -----------------------------------------------------------------
    "GEN_SPEAKING_NOT_SUPPORTED": _spec(
        "지금은 쓰기 문항만 만든다. 말하기 문항 생성은 아직 없다.",
        "Only writing items can be generated for now. Speaking item generation does not exist yet.",
        where="HTTP 400 detail",
        endpoint="/generate-items",
        situation="말하기 문항 요청",
    ),
    "GEN_DOCUMENT_TOO_SHORT": _spec(
        "문서가 {chars}자로 너무 짧아 문항을 만들 수 없다(최소 {minChars}자).",
        "The document is {chars} characters long, too short to generate items from (minimum "
        "{minChars}).",
        params={"chars": "int", "minChars": "int"},
        examples={"chars": 120, "minChars": 300},
        where="HTTP 400 detail",
        endpoint="/generate-items",
        situation="문서가 너무 짧음",
    ),
    "GEN_DOCUMENT_TOO_LONG": _spec(
        "문서가 {chars}자로 너무 길다(최대 {maxChars}자). 장·절 단위로 나눠서 보내야 한다.",
        "The document is {chars} characters long, too long (maximum {maxChars}). Split it into "
        "chapters or sections and send them separately.",
        params={"chars": "int", "maxChars": "int"},
        examples={"chars": 42000, "maxChars": 20000},
        where="HTTP 400 detail",
        endpoint="/generate-items",
        situation="문서가 너무 김",
    ),
    "GEN_KEYWORD_REMOVED": _spec(
        "[{itemId}] 문서에 없는 핵심어 {keywords} 를 뺐다"
        "(LLM 을 못 쓸 때의 대체 채점이 엉뚱하게 돌지 않게 하려는 것).",
        "[{itemId}] Removed the keyword(s) {keywords} that do not appear in the document (so the "
        "fallback scoring used when the LLM is unavailable does not misfire).",
        params={"itemId": "str", "keywords": "str(한국어 그대로)"},
        examples={"itemId": "GEN-W-001", "keywords": "'보호구', '점검표'"},
        endpoint="/generate-items",
        situation="문서에 없는 핵심어 제거",
    ),
    "GEN_NO_ITEMS_PRODUCED": _spec(
        "모델이 문항을 하나도 만들지 않았다. 문서 내용을 확인하고 다시 시도해야 한다.",
        "The model produced no items at all. Check the document content and try again.",
        endpoint="/generate-items",
        situation="모델이 0개 생성",
    ),
    "GEN_ALL_DROPPED": _spec(
        "만들어진 문항 {count}개가 모두 검증 관문에서 폐기됐다. 근거를 댈 수 없는 문항은 "
        "내보내지 않는다. 문서를 바꿔 다시 시도해야 한다.",
        "All {count} generated item(s) were dropped at the validation gates. Items without "
        "traceable evidence are never released. Try again with a different document.",
        params={"count": "int"},
        examples={"count": 5},
        endpoint="/generate-items",
        situation="전부 폐기됨",
    ),
    "GEN_FEWER_THAN_REQUESTED": _spec(
        "요청한 {requested}개 중 {passed}개만 관문을 통과했다. 더 필요하면 문항 수를 늘려 다시 "
        "요청해야 한다.",
        "Only {passed} of the {requested} requested items passed the gates. Ask again with a "
        "larger item count if you need more.",
        params={"requested": "int", "passed": "int"},
        examples={"requested": 5, "passed": 3},
        endpoint="/generate-items",
        situation="요청보다 적게 통과",
    ),
    "GEN_TYPE_SKEWED": _spec(
        "'{itemType}' 유형 문항이 {count}개로 몰려 있다. 시험이 한 가지 상황만 묻게 되지 않는지 "
        "확인해야 한다.",
        "{count} items are concentrated in the '{itemType}' type. Check that the test is not asking "
        "about only one situation.",
        params={"itemType": "str", "count": "int"},
        examples={"itemType": "report", "count": 4},
        endpoint="/generate-items",
        situation="유형 편중",
    ),
    "GEN_MEMORIZATION_SUSPECT": _spec(
        "[{itemId}] 지시문에 '{marker}' 가 있어 암기 문제로 보일 수 있다. 승인 전에 사람이 확인해야 한다.",
        "[{itemId}] The prompt contains '{marker}', which may make it look like a memorization "
        "question. A human should check it before approval.",
        params={"itemId": "str", "marker": "str(한국어 그대로)"},
        examples={"itemId": "GEN-W-002", "marker": "몇 조"},
        endpoint="/generate-items, /verify-items",
        situation="암기 문제 의심(검증 관문)",
    ),
    "GEN_DUPLICATE_ITEM": _spec(
        "앞 문항과 지시문이 대부분 겹쳐 사실상 같은 문항이다.",
        "The prompt largely overlaps the previous item, so it is effectively the same item.",
        endpoint="/generate-items",
        situation="문항 중복(조립)",
    ),
    "VERIFY_DOCUMENT_MISMATCH": _spec(
        "보내온 문서가 문항을 만들 때 쓴 문서와 다르다. 인용 위치가 어긋날 수 있으니 문서를 다시 "
        "확인해야 한다.",
        "The document sent differs from the one the items were generated from. Citation offsets may "
        "not line up, so check the document again.",
        endpoint="/verify-items",
        situation="문서 지문 불일치",
    ),
    "VERIFY_DUPLICATE_ITEM": _spec(
        "'{itemId}' 문항과 지시문이 대부분 겹쳐 사실상 같은 문항이 됐다.",
        "The prompt largely overlaps item '{itemId}', so it has become effectively the same item.",
        params={"itemId": "str"},
        examples={"itemId": "GEN-W-001"},
        endpoint="/verify-items",
        situation="재검증 중 문항 중복",
    ),
    # -----------------------------------------------------------------
    # 3-C. 폐기 사유 상세 (dropped[].detail / results[].failures[].detail)
    # -----------------------------------------------------------------
    "DROP_NOT_OBJECT": _spec(
        "문항이 JSON 객체 모양이 아니다.",
        "The item is not shaped like a JSON object.",
        where="dropped detail",
        endpoint="/generate-items, /verify-items",
        situation="G1 형식",
    ),
    "DROP_REQUIRED_FIELD_MISSING": _spec(
        "필수 항목 '{key}' 이(가) 비었거나 글자가 아니다.",
        "The required field '{key}' is empty or is not a string.",
        params={"key": "str"},
        examples={"key": "prompt"},
        where="dropped detail",
        endpoint="/generate-items, /verify-items",
        situation="G1 형식",
    ),
    "DROP_CHECKLIST_NOT_LIST": _spec(
        "checklist 가 목록이 아니다.",
        "'checklist' is not a list.",
        where="dropped detail",
        endpoint="/generate-items, /verify-items",
        situation="G1 형식",
    ),
    "DROP_ITEM_TYPE_INVALID": _spec(
        "문항 유형 '{itemType}' 은(는) 쓸 수 있는 유형이 아니다(허용: {allowed}).",
        "Item type '{itemType}' is not a usable type (allowed: {allowed}).",
        params={"itemType": "str", "allowed": "str"},
        examples={"itemType": "quiz", "allowed": "report, request, notice"},
        where="dropped detail",
        endpoint="/generate-items, /verify-items",
        situation="G1 형식",
    ),
    "DROP_REGISTER_INVALID": _spec(
        "말투 '{register}' 는 formal 또는 polite 가 아니다.",
        "Register '{register}' is neither formal nor polite.",
        params={"register": "str"},
        examples={"register": "casual"},
        where="dropped detail",
        endpoint="/generate-items, /verify-items",
        situation="G1 형식",
    ),
    "DROP_CHECKLIST_COUNT": _spec(
        "체크리스트가 {count}개다(허용 {min}~{max}개).",
        "The checklist has {count} entries (allowed {min}-{max}).",
        params={"count": "int", "min": "int", "max": "int"},
        examples={"count": 1, "min": 2, "max": 5},
        where="dropped detail",
        endpoint="/generate-items, /verify-items",
        situation="G1 형식",
    ),
    "DROP_CHECKLIST_ENTRY_NOT_OBJECT": _spec(
        "체크리스트 {index}번이 객체가 아니다.",
        "Checklist entry #{index} is not an object.",
        params={"index": "int"},
        examples={"index": 2},
        where="dropped detail",
        endpoint="/generate-items, /verify-items",
        situation="G1 형식",
    ),
    "DROP_CHECKLIST_ENTRY_NO_DESCRIPTION": _spec(
        "체크리스트 {index}번에 설명이 없다.",
        "Checklist entry #{index} has no description.",
        params={"index": "int"},
        examples={"index": 3},
        where="dropped detail",
        endpoint="/generate-items, /verify-items",
        situation="G1 형식",
    ),
    "DROP_CHECKLIST_WEIGHT_NOT_NUMBER": _spec(
        "체크리스트 {index}번의 weight 가 숫자가 아니다.",
        "The weight of checklist entry #{index} is not a number.",
        params={"index": "int"},
        examples={"index": 1},
        where="dropped detail",
        endpoint="/generate-items, /verify-items",
        situation="G1 형식",
    ),
    "DROP_CHECKLIST_WEIGHT_OUT_OF_RANGE": _spec(
        "체크리스트 {index}번의 weight 가 {weight} 로 허용 범위({min}~{max})를 벗어났다.",
        "The weight of checklist entry #{index} is {weight}, outside the allowed range "
        "({min}-{max}).",
        params={"index": "int", "weight": "float", "min": "float", "max": "float"},
        examples={"index": 2, "weight": 4.0, "min": 0.5, "max": 2.0},
        where="dropped detail",
        endpoint="/generate-items, /verify-items",
        situation="G1 형식",
    ),
    "DROP_PROMPT_LENGTH": _spec(
        "지시문이 {chars}자다(허용 {min}~{max}자).",
        "The prompt is {chars} characters long (allowed {min}-{max}).",
        params={"chars": "int", "min": "int", "max": "int"},
        examples={"chars": 40, "min": 80, "max": 400},
        where="dropped detail",
        endpoint="/generate-items, /verify-items",
        situation="G1 형식",
    ),
    "DROP_PROMPT_NO_NUMBERING": _spec(
        "지시문에 번호 기호 {markers} 가 없어 무엇을 써야 하는지 나뉘어 있지 않다.",
        "The prompt has none of the numbering markers {markers}, so what to write is not broken "
        "out into parts.",
        params={"markers": "str"},
        examples={"markers": "①, ②, 1), 2)"},
        where="dropped detail",
        endpoint="/generate-items, /verify-items",
        situation="G1 형식",
    ),
    "DROP_PROMPT_RUNON": _spec(
        "지시문에 띄어쓰기 없이 {chars}자가 이어지는 곳이 있다(허용 {maxChars}자). "
        "문서에서 띄어쓰기가 사라진 문구가 그대로 새어 나온 것으로 보인다.",
        "The prompt has a run of {chars} characters with no space (limit {maxChars}). It looks like "
        "text that lost its spacing in the document leaked through.",
        params={"chars": "int", "maxChars": "int"},
        examples={"chars": 34, "maxChars": 25},
        where="dropped detail",
        endpoint="/generate-items, /verify-items",
        situation="G1 형식",
    ),
    "DROP_PROMPT_NO_WRITING_VERB": _spec(
        "지시문에 쓰기를 시키는 말(쓰세요·작성하세요·알리세요 등)이 없다. "
        "글을 쓰게 하는 문항이 아니라 지식을 묻는 문항으로 보인다.",
        "The prompt contains no instruction to write (write, fill in, notify, ...). It reads as a "
        "knowledge question rather than a writing task.",
        where="dropped detail",
        endpoint="/generate-items, /verify-items",
        situation="G1 형식",
    ),
    "DROP_EVIDENCE_EMPTY": _spec(
        "근거 인용이 비어 있다.",
        "The supporting citation is empty.",
        where="dropped detail",
        endpoint="/generate-items, /verify-items",
        situation="G2 인용",
    ),
    "DROP_EVIDENCE_CROSSES_CHUNK": _spec(
        "인용이 문서에서 잘라낸 자리를 가로지른다. 실제 문서에는 이어져 있지 않은 문장이다.",
        "The citation crosses a boundary where the document was split. These sentences are not "
        "contiguous in the real document.",
        where="dropped detail",
        endpoint="/generate-items, /verify-items",
        situation="G2 인용",
    ),
    "DROP_EVIDENCE_JOINER": _spec(
        "인용에 이음표 '{marker}' 가 있어 여러 구절을 합친 것으로 보인다.",
        "The citation contains the joiner '{marker}', so it looks like several passages stitched "
        "together.",
        params={"marker": "str"},
        examples={"marker": "…"},
        where="dropped detail",
        endpoint="/generate-items, /verify-items",
        situation="G2 인용",
    ),
    "DROP_EVIDENCE_TOO_SHORT": _spec(
        "인용이 {chars}자로 너무 짧아 근거로 인정하지 않는다(최소 {minChars}자).",
        "The citation is {chars} characters long, too short to count as evidence (minimum "
        "{minChars}).",
        params={"chars": "int", "minChars": "int"},
        examples={"chars": 4, "minChars": 10},
        where="dropped detail",
        endpoint="/generate-items, /verify-items",
        situation="G2 인용",
    ),
    "DROP_EVIDENCE_TOO_LONG": _spec(
        "인용이 {chars}자로 너무 길다(최대 {maxChars}자). 짧은 한 구절만 인용해야 어디를 근거로 "
        "삼았는지 사람이 확인할 수 있다.",
        "The citation is {chars} characters long, too long (maximum {maxChars}). Only a short "
        "passage should be cited so a human can check what it was based on.",
        params={"chars": "int", "maxChars": "int"},
        examples={"chars": 320, "maxChars": 200},
        where="dropped detail",
        endpoint="/generate-items, /verify-items",
        situation="G2 인용",
    ),
    "DROP_EVIDENCE_WRAP": _spec(
        "{label}: {detail}",
        "{label}: {detail}",
        params={
            "label": "str",
            "labelNotice": NESTED,
            "detail": "str",
            "detailNotice": NESTED,
        },
        examples={
            "label": "문항 근거",
            "labelNotice": {"code": "DROP_LABEL_ITEM_EVIDENCE"},
            "detail": "근거 인용이 비어 있다.",
            "detailNotice": {"code": "DROP_EVIDENCE_EMPTY"},
        },
        where="dropped detail",
        endpoint="/generate-items, /verify-items",
        situation="G2/G3 겉 문구",
    ),
    "DROP_LABEL_ITEM_EVIDENCE": _spec(
        "문항 근거",
        "Item evidence",
        where="dropped detail 안의 라벨",
        endpoint="/generate-items, /verify-items",
        situation="겉 문구의 라벨 값",
    ),
    "DROP_LABEL_CHECKLIST_EVIDENCE": _spec(
        "체크리스트 {index}번 근거",
        "Checklist #{index} evidence",
        # 체크리스트에 id 가 있으면 그 id 가, 없으면 몇 번째인지가 들어온다
        params={"index": "int|str"},
        examples={"index": "c2"},
        where="dropped detail 안의 라벨",
        endpoint="/generate-items, /verify-items",
        situation="겉 문구의 라벨 값",
    ),
    "DROP_EVIDENCE_NOT_FOUND": _spec(
        "{label}: 문서에서 찾을 수 없는 인용이다(지어낸 근거로 보고 폐기했다).",
        "{label}: this citation cannot be found in the document (treated as fabricated evidence "
        "and dropped).",
        params={"label": "str", "labelNotice": NESTED},
        examples={
            "label": "문항 근거",
            "labelNotice": {"code": "DROP_LABEL_ITEM_EVIDENCE"},
        },
        where="dropped detail",
        endpoint="/generate-items, /verify-items",
        situation="G3 인용이 문서에 없음",
    ),
    "DROP_ANSWER_IN_PROMPT": _spec(
        "지시문 글자의 {ratio}가 근거 구절과 그대로 겹친다(기준 {threshold}). 답이 문제 안에 들어 있다.",
        "{ratio} of the prompt's characters overlap the evidence passage verbatim (threshold "
        "{threshold}). The answer is inside the question.",
        params={"ratio": "str", "threshold": "str"},
        examples={"ratio": "71%", "threshold": "50%"},
        where="dropped detail",
        endpoint="/generate-items, /verify-items",
        situation="G4 답이 문제 안에",
    ),
    "DROP_TRIPS_COPY_GUARD": _spec(
        "근거 구절을 그대로 옮겨 쓴 답안이 채점기의 '지시문 베끼기' 가드에 걸린다. "
        "성실한 응시자가 무효 0점을 받을 수 있는 문항이다.",
        "An answer that copies the evidence passage verbatim would trip the scorer's "
        "'prompt copying' guard. An honest test taker could be voided to zero on this item.",
        where="dropped detail",
        endpoint="/generate-items, /verify-items",
        situation="G4 베끼기 가드 충돌",
    ),
    "DROP_CONVERT_FAILED": _spec(
        "채점 API 형식으로 바꾸지 못했다({type}).",
        "The item could not be converted into the scoring API format ({type}).",
        params={"type": "str"},
        examples={"type": "ValidationError"},
        where="dropped detail",
        endpoint="/generate-items, /verify-items",
        situation="G5 변환 실패",
    ),
    # -----------------------------------------------------------------
    # 7. 내부용 — 운영자에게 주는 안내라 영어화 대상이 아니다
    #    (그래도 코드를 붙인다: warnings 와 notices 의 길이가 어긋나면 안 되기 때문)
    # -----------------------------------------------------------------
    "SCORE_PROVISIONAL_WEIGHTS": _spec(
        "※ 임시 ※ 결합 가중치와 등급 커트라인은 학습된 값이 아니라 손으로 정한 임시값이다. "
        "절대 등급으로 쓰지 말고 답안 사이 비교에만 쓸 것.",
        "*** Provisional *** The combination weights and grade cutoffs are hand-set values, not "
        "learned ones. Do not use them as absolute grades; use them only to compare answers.",
        situation="운영자 대상 임시값 경고(내부용)",
        internal=True,
    ),
    "FINALIZE_PROVISIONAL_WEIGHTS": _spec(
        "※ 임시 ※ 결합 가중치는 학습된 값이 아니고, 등급 커트라인도 전문가가 확정한 "
        "앵커 답안에서 나온 값이 아니다. 백분위 역시 실제 응시자 분포가 아니라 "
        "임시 환산표에서 나온 값이다. 확정 등급으로 통보하지 말 것.",
        "*** Provisional *** The combination weights are not learned, the grade cutoffs do not "
        "come from expert-confirmed anchor answers, and the percentile comes from a provisional "
        "conversion table rather than a real test-taker distribution. Do not report this as a "
        "confirmed grade.",
        endpoint="/finalize",
        situation="운영자 대상 임시값 경고(내부용)",
        internal=True,
    ),
}


# ---------------------------------------------------------------------------
# 만들고 쌓는 함수
# ---------------------------------------------------------------------------


def _fill(code: str, template: str, params: dict[str, Any]) -> str:
    """템플릿의 `{키}` 자리에 값을 끼워 한국어 문장을 만든다.

    값이 하나 빠져도 문장이 통째로 사라지면 안 되므로, 못 채운 자리는 `{키}` 그대로
    남겨 두고 넘어간다. 조용히 빈 문장을 내보내는 것보다 어디가 비었는지 보이는 편이
    고치기 쉽다.
    """
    try:
        return template.format(**params)
    except (KeyError, IndexError, ValueError):
        # 값이 모자라면 있는 것만 채운다 (string.Formatter 를 직접 돌린다)
        return string.Formatter().vformat(template, (), _Missing(params))


class _Missing(dict):
    """없는 키를 물어보면 `{키}` 라는 글자를 돌려주는 사전."""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def notice(code: str, **params: Any) -> Notice:
    """코드 하나로 Notice(코드 + 값 + 한국어 문장)를 만든다.

    카탈로그에 없는 코드는 조용히 넘기지 않고 바로 알린다. 오타 난 코드가 응답에
    실려 나가면 백엔드는 영어 문장을 못 찾고 화면이 비어 버리기 때문이다.
    """
    spec = MESSAGE_CATALOG.get(code)
    if spec is None:
        raise KeyError(f"카탈로그에 없는 메시지 코드: {code}")

    # 중첩 Notice(안쪽 사유)는 dict 로 바꿔 담는다. 그래야 JSON 으로 그대로 나간다
    cleaned: dict[str, Any] = {}
    for key, value in params.items():
        cleaned[key] = value.model_dump() if isinstance(value, Notice) else value

    return Notice(code=code, params=cleaned, message=_fill(code, spec.template, cleaned))


def notice_or_free_text(code: str | None, text: str) -> Notice:
    """코드가 있으면 그 코드로, 없으면 LLM 자유 생성 문구로 Notice 를 만든다.

    LLM 이 그때그때 지어낸 판정 이유에는 고정 코드가 없다. 그렇다고 빈손으로 두면
    백엔드가 그 자리에 무엇을 넣을지 알 수 없으므로, `LLM_FREE_TEXT` 라는 코드를
    붙여 "이건 번역할 고정 문구가 없는 자유문이다"라고 알려 준다.
    """
    if code:
        return notice(code)
    return notice("LLM_FREE_TEXT", text=text)


def join_notices(items: list[Notice], separator: str = " / ") -> Notice | None:
    """여러 안내를 한 줄로 이어 붙여 하나의 Notice 로 만든다.

    영역 note(`SubScore.note`)는 자리가 하나뿐인데 알릴 것이 여러 개일 수 있다.
    그럴 때 문장은 " / " 로 이어 붙이고, **안쪽 코드 목록은 그대로 남겨서** 백엔드가
    각각을 영어로 바꾼 뒤 같은 방식으로 이어 붙일 수 있게 한다.

    하나뿐이면 굳이 감싸지 않고 그것을 그대로 돌려준다(백엔드가 다루기 쉽다).
    """
    if not items:
        return None
    if len(items) == 1:
        return items[0]
    return notice(
        "SUBSCORE_NOTE_LIST",
        notes=separator.join(one.message for one in items),
        items=[one.model_dump() for one in items],
    )


def emit(
    warnings: list[str],
    notices: list[Notice],
    code: str,
    **params: Any,
) -> Notice:
    """한국어 문장은 `warnings` 에, 코드는 `notices` 에 **한 번에** 쌓는다.

    두 목록을 따로 채우게 두면 한쪽만 넣는 자리가 반드시 생기고, 그러면 백엔드가
    받는 두 목록의 길이가 달라져 어느 코드가 어느 문장인지 짝을 지을 수 없게 된다.
    그래서 쌓는 입구를 이 함수 하나로 좁혔다.
    """
    made = notice(code, **params)
    warnings.append(made.message)
    notices.append(made)
    return made
