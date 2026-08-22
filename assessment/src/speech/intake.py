"""음성 답안을 받아 글로 바꿔 채점 앞에 세워 주는 자리.

채점 파이프라인은 언제나 '글'을 채점한다. 그 규칙을 음성 때문에 바꾸지 않으려고,
음성을 글로 바꾸는 일을 채점보다 앞에서 끝내고 answer_text 자리에 넣어 준다.
그래서 채점 쪽에서 달라지는 것은 '채점할 글이 어디서 왔는가'뿐이다.

여기서 정하는 규칙 네 가지 (섞이면 무엇을 채점했는지 설명할 수 없게 된다):

    음성 없음                          -> 지금까지 그대로. 이 파일은 아무것도 하지 않는다
    말하기 + 음성 + 글 비어 있음        -> 받아쓴 글로 채점한다  (여기가 새 길이다)
    말하기 + 음성 + 글도 있음           -> 거절한다. 어느 쪽이 답안인지 알 수 없다
    쓰기 + 음성                        -> 거절한다. 쓰기는 응시자가 직접 친 글을 본다

'둘 다 오면 거절'을 고른 이유:
하나를 골라 쓰면(예: 글이 있으면 글을 쓴다) 백엔드가 실수로 둘 다 보냈을 때
아무 말 없이 한쪽이 버려진다. 음성이 버려진 사실은 응답만 봐서는 알 수 없고,
그 답안은 조용히 다른 글로 채점된다. 애매한 요청은 채점하지 않고 되돌려 보낸다.
"""

from __future__ import annotations

import inspect
import os
from dataclasses import dataclass, field

from ..scoring.schema import Mode, ScoreRequest
from .audio import AudioRequestError
from .port import (
    PronouncerPort,
    PronunciationAssessment,
    SttPort,
    SttUnavailable,
    Transcription,
)

#: 어느 받아쓰기를 쓸지 정하는 환경변수 이름.
#: 값은 "lora" · "azure" · "gemini". 안 정해 두면 Azure 열쇠가 있으면 azure, 없으면 gemini 다.
#: (열쇠가 없는 곳에서도 지금까지처럼 돌아야 하므로 이렇게 정했다)
STT_PROVIDER_ENV = "KTEST_STT_PROVIDER"

#: LoRA 받아쓰기 서버 주소를 담는 환경변수 이름.
#: provider=lora 는 이 주소가 있어야만 고를 수 있다(주소 없이 고르면 채점이 통째로 실패한다).
LORA_STT_URL_ENV = "LORA_STT_URL"

#: 발음(발화 전달력) 평가에 필요한 열쇠 이름들.
#: **전사를 누가 했든** 이 열쇠가 있으면 말하기 답안의 발음은 Azure 로 따로 잰다.
AZURE_KEY_ENV = "AZURE_SPEECH_KEY"
AZURE_REGION_ENV = "AZURE_SPEECH_REGION"

#: '발음 평가기를 넘기지 않았다'와 '일부러 없다고 넘겼다(None)'를 구별하는 표식.
#: resolve_audio_answer 에서, 아무 말이 없으면 서버 기본값을 만들고, 명시적으로
#: None 을 주면(테스트가 발음 없음을 시험할 때) 만들지 않는다.
_UNSET = object()


@dataclass
class AudioResolution:
    """음성을 글로 바꾼 결과. 채점에 넘길 글과, 그 글이 어떻게 나왔는지."""

    #: 채점 대상이 될 글. answer_text 자리에 들어간다
    text: str
    provider: str
    model: str
    audio_duration_ms: int | None = None
    elapsed_ms: float = 0.0
    warnings: list[str] = field(default_factory=list)
    #: 발음 평가 결과. 발음을 잴 수 있는 제공자(Azure)만 채운다.
    #: 이 값이 있으면 발화 전달력(delivery) 영역이 채점되고, 없으면 지금까지처럼 비워 둔다
    pronunciation: PronunciationAssessment | None = None

    @classmethod
    def from_transcription(cls, result: Transcription) -> "AudioResolution":
        """받아쓰기 결과를 채점에 넘길 모양으로 옮긴다."""
        # 사람이 알아야 할 것을 여기서 한 문장 더 붙인다.
        # 이 문구가 있어야 결과를 보는 사람이 '이 점수는 기계가 받아쓴 글에 매겨졌다'는
        # 사실을 알게 된다. 받아쓰기가 틀리면 점수도 틀리기 때문이다
        warnings = list(result.warnings)
        warnings.append(
            f"음성을 {result.provider}({result.model})로 받아쓴 글을 채점했다. "
            "받아쓰기가 응시자의 말과 다를 수 있으므로 이의가 있으면 "
            "meta.stt_transcript 와 원본 녹음을 함께 확인해야 한다."
        )
        return cls(
            text=result.text,
            provider=result.provider,
            model=result.model,
            audio_duration_ms=result.audio_duration_ms,
            elapsed_ms=result.elapsed_ms,
            warnings=warnings,
            # 발음 점수를 여기서 채점 쪽으로 넘긴다. 없으면 None 이고,
            # 그러면 발화 전달력은 지금까지처럼 채점되지 않는다
            pronunciation=result.pronunciation,
        )


def azure_pronunciation_available() -> bool:
    """발음(발화 전달력)을 Azure 로 잴 수 있는 상태인지.

    **전사를 누가 하든** 이 값이 참이면 말하기 답안의 발음은 Azure 로 따로 잰다.
    그래서 provider=lora 로 받아쓰더라도 열쇠만 있으면 delivery 가 채점된다.
    """
    return bool(os.getenv(AZURE_KEY_ENV) and os.getenv(AZURE_REGION_ENV))


def choose_stt_provider() -> str:
    """이번 서버에서 어느 받아쓰기를 쓸지 이름으로 정한다.

    정하는 순서는 둘이다.
      1) 환경변수 KTEST_STT_PROVIDER 에 적힌 이름 ("lora" · "azure" · "gemini")
         단, "lora" 는 서버 주소(LORA_STT_URL)가 함께 있어야만 고른다.
         주소 없이 lora 를 고르면 말하기 채점이 통째로 실패하기 때문이다.
      2) 안 적혀 있으면 — Azure 열쇠가 있으면 azure, 없으면 gemini
         (기본값으로는 lora 를 고르지 않는다. lora 는 아직 검증 전이라
          운영자가 이름을 대고 명시적으로 골랐을 때만 쓴다)

    2번을 이렇게 둔 이유:
    열쇠가 없는 곳(다른 팀원의 PC, 자동 검사 환경)에서도 지금까지와 똑같이
    돌아야 한다. 열쇠가 없는데 azure 를 고르면 채점이 통째로 실패한다.
    """
    declared = os.getenv(STT_PROVIDER_ENV, "").strip().lower()
    # lora 는 주소가 있어야만 고른다. 주소가 없으면 아래 기본 규칙으로 흘려보낸다
    if declared == "lora" and os.getenv(LORA_STT_URL_ENV, "").strip():
        return "lora"
    if declared in ("azure", "gemini"):
        return declared
    # 열쇠와 지역이 둘 다 있어야 Azure 를 부를 수 있다
    if azure_pronunciation_available():
        return "azure"
    return "gemini"


def build_default_stt() -> SttPort:
    """지금 꽂혀 있는 받아쓰기 구현을 만든다.

    **받아쓰기를 갈아 끼우는 곳이 여기 한 곳이다.**
    부르는 쪽(채점 파이프라인)은 SttPort 라는 모양만 알고 있으므로,
    이 함수가 다른 것을 돌려주면 그날부터 그것으로 받아쓴다.

    - lora   : 우리가 학습한 Whisper LoRA. 글자만 받아쓴다(발음은 Azure 가 따로 잰다).
    - azure  : 받아쓰기와 발음을 한 번에 한다.
    - gemini : 글자만 준다.

    발음(delivery)은 이 선택과 별개다. 어느 것으로 받아쓰든, Azure 열쇠가 있으면
    말하기 답안의 발음은 Azure 로 따로 채점한다(resolve_audio_answer 참고).
    """
    provider = choose_stt_provider()
    if provider == "lora":
        from .lora_stt import LoraStt

        return LoraStt()
    if provider == "azure":
        from .azure_stt import AzureStt

        return AzureStt()

    from .gemini_stt import GeminiStt

    return GeminiStt()


def build_default_pronouncer() -> PronouncerPort | None:
    """말하기 답안의 발음을 잴 기계를 만든다. 열쇠가 없으면 None.

    **전사 제공자와 독립이다.** 여기가 그 분리의 핵심이다 — 받아쓰기를 LoRA 가
    하든 Gemini 가 하든, Azure 열쇠만 있으면 발음은 Azure 가 잰다. 열쇠가 없으면
    None 을 돌려주고, 그러면 delivery 는 지금까지처럼 비어 있게 둔다.
    """
    if not azure_pronunciation_available():
        return None
    from .azure_stt import AzureStt

    return AzureStt()


def _transcribe_kwargs(engine: SttPort, request: ScoreRequest) -> dict:
    """받아쓰기 구현에 넘길 참고 값을 고른다.

    문항 유형(item_type)은 나중에 더한 값이다. Azure 구현은 이것을 보고
    낭독형인지(제시문을 정답지로 줄지) 정하지만, 예전 구현은 이 값을 받지 않는다.
    받지 않는 구현에 억지로 넘기면 그 자리에서 오류가 나므로,
    **받을 수 있는 구현에만 넘긴다.**
    """
    kwargs = {"item_prompt": request.item.prompt}
    try:
        parameters = inspect.signature(engine.transcribe).parameters
    except (TypeError, ValueError):
        # 서명을 읽을 수 없는 구현이면 예전 방식대로만 부른다
        return kwargs
    accepts_any = any(p.kind == p.VAR_KEYWORD for p in parameters.values())
    if "item_type" in parameters or accepts_any:
        kwargs["item_type"] = request.item.item_type
    return kwargs


def _resolve_pronunciation(
    request: ScoreRequest,
    result: Transcription,
    stt: SttPort | None,
    pronouncer,
) -> tuple[PronunciationAssessment | None, list[str]]:
    """이 답안의 발음(발화 전달력) 점수를 어디서 얻을지 정해 돌려준다.

    세 갈래다.
      1) 받아쓰기가 이미 발음까지 준 경우(provider=azure) → 그것을 그대로 쓴다.
         한 음성을 두 번 인식하지 않으려는 것이다.
      2) 아직 발음이 없고(예: LoRA·Gemini 로 받아씀) 발음 평가기가 있는 경우 →
         **음성 원본을 Azure 로 따로 들어** 발음만 잰다. 여기가 '전사는 LoRA·
         발음은 Azure' 분리가 실제로 일어나는 자리다.
      3) 발음 평가기가 없으면(열쇠 없음) → None. delivery 는 비워 둔다.

    발음 평가기 인자(pronouncer)의 규칙:
      - _UNSET  : 아무 말 없음. 서버 기본값을 만들되, **테스트가 가짜 stt 를 꽂은
                  경우(stt 가 주어짐)에는 만들지 않는다.** 그래야 네트워크 없는
                  테스트가 실수로 진짜 Azure 를 부르지 않는다.
      - None    : 일부러 없다고 지정. 발음을 재지 않는다(발음 없음을 시험하는 자리).
      - 그 밖    : 그 평가기로 잰다(테스트가 가짜 Azure 를 꽂는 자리).
    """
    warnings: list[str] = []

    # 1) 받아쓰기가 발음까지 준 경우: 그대로 쓴다(두 번 인식하지 않는다)
    if result.pronunciation is not None:
        return result.pronunciation, warnings

    # 발음 평가기를 정한다(위 규칙대로)
    if pronouncer is _UNSET:
        pronouncer = build_default_pronouncer() if stt is None else None
    if pronouncer is None:
        return None, warnings

    # 열쇠가 없는 평가기면 부르지 않는다(available 로 미리 거른다)
    if not getattr(pronouncer, "available", False):
        return None, warnings

    # 2) 음성 원본을 Azure 로 따로 들어 발음만 잰다.
    #    받아쓴 글을 정답지로 넘기지 않는다(발음은 원음 기준이어야 한다).
    #    낭독형이면 제시문(item_prompt)을 정답지로 주는 판단은 평가기 안에서 한다
    assessment = pronouncer.assess_pronunciation(
        request.audio,
        item_prompt=request.item.prompt,
        item_type=request.item.item_type,
    )
    if assessment is None:
        # 발음만 못 잰 것이다. 전사는 살아 있으므로 채점은 이어 가고,
        # delivery 만 비워 둔다는 사실을 사람이 알 수 있게 남긴다
        warnings.append(
            f"발음 평가를 하지 못해 발화 전달력(delivery)은 채점하지 않았다"
            f"(전사는 {result.provider} 로 정상 처리됨)."
        )
        return None, warnings

    # 전사와 발음을 서로 다른 기계가 맡았다는 사실을 결과에 남긴다.
    # 근거 없는 점수는 결함이므로, 발음 점수가 어디서 왔는지가 보여야 한다
    provider = getattr(pronouncer, "provider_name", "azure")
    if provider != result.provider:
        warnings.append(
            f"발화 전달력(delivery)은 {provider} 발음평가로 따로 채점했다"
            f"(받아쓰기는 {result.provider})."
        )
    return assessment, warnings


def resolve_audio_answer(
    request: ScoreRequest,
    stt: SttPort | None = None,
    pronouncer=_UNSET,
) -> AudioResolution | None:
    """요청에 음성이 붙어 있으면 받아써서 채점할 글을 만든다.

    음성이 없으면 None 을 돌려주고, 그러면 채점은 지금까지와 똑같이 진행된다.

    stt 를 넘기면 그것으로 받아쓴다(테스트가 네트워크 없이 도는 자리).
    안 넘기면 지금 꽂혀 있는 구현을 쓴다.

    pronouncer 는 발음(발화 전달력)을 잴 기계다. 받아쓰기와 **따로** 정한다 —
    전사를 LoRA 가 해도 발음은 Azure 가 잴 수 있어야 하기 때문이다.
    (인자 규칙은 _resolve_pronunciation 주석 참고)

    실패는 두 갈래로 나간다. 백엔드가 다르게 대응해야 하기 때문이다.
      AudioRequestError : 요청이 틀렸다. 다시 보내도 같은 결과다  -> 400
      SttUnavailable    : 받아쓰지 못했다. 잠시 뒤에는 될 수 있다  -> 503
    """
    audio = request.audio
    # 음성이 없으면 이 파일은 아무 일도 하지 않는다. 기존 요청은 여기서 끝난다
    if audio is None:
        return None

    # 규칙 1: 쓰기 답안에는 음성을 붙일 수 없다.
    # 쓰기는 응시자가 직접 친 글의 맞춤법·띄어쓰기까지 보는 채점이라
    # 받아쓴 글로는 그 영역을 채점하는 의미가 없어진다
    if request.mode != Mode.SPEAKING:
        raise AudioRequestError(
            "쓰기 답안에는 음성 파일을 붙일 수 없다. "
            "음성 채점은 mode 를 speaking 으로 보내야 한다."
        )

    # 규칙 2: 글과 음성이 둘 다 오면 채점하지 않고 되돌려 보낸다.
    # 하나를 골라 쓰면 나머지 하나가 조용히 버려지는데 응답만 봐서는 알 수 없다
    if request.answer_text.strip():
        raise AudioRequestError(
            "answer_text 와 audio 가 함께 왔다. 어느 것을 채점해야 할지 알 수 없다. "
            "음성으로 채점하려면 answer_text 를 비워서 보내야 한다."
        )

    # 규칙 3: 여기서부터가 새 길이다. 받아쓴 뒤 그 글로 채점한다
    engine = stt or build_default_stt()
    result = engine.transcribe(audio, **_transcribe_kwargs(engine, request))

    # 구현체가 규칙을 어기고 빈 글을 돌려준 경우를 여기서 한 번 더 막는다.
    # 빈 글이 채점으로 흘러가면 '말을 안 한 답안'과 '받아쓰기 실패'가 뒤섞인다
    if not result.text.strip():
        raise SttUnavailable(
            "음성에서 말을 하나도 옮겨 적지 못했다. 녹음 상태를 확인해야 한다."
        )

    # 발음(발화 전달력)을 전사와 따로 정한다. 받아쓰기가 이미 준 경우가 아니면
    # 음성 원본을 Azure 로 따로 들어 발음만 잰다
    pronunciation, pron_warnings = _resolve_pronunciation(request, result, stt, pronouncer)

    resolution = AudioResolution.from_transcription(result)
    # 따로 잰 발음을 채점 쪽으로 넘기고, 그 과정에서 생긴 안내문을 덧붙인다
    resolution.pronunciation = pronunciation
    resolution.warnings.extend(pron_warnings)
    return resolution
