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

from dataclasses import dataclass, field

from ..scoring.schema import Mode, ScoreRequest
from .audio import AudioRequestError
from .port import SttPort, SttUnavailable, Transcription


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
        )


def build_default_stt() -> SttPort:
    """지금 꽂혀 있는 받아쓰기 구현을 만든다.

    **Azure 로 갈아 끼울 때 고치는 곳이 여기 한 줄이다.**
    부르는 쪽(채점 파이프라인)은 SttPort 라는 모양만 알고 있으므로,
    이 함수가 다른 것을 돌려주면 그날부터 그것으로 받아쓴다.
    """
    from .gemini_stt import GeminiStt

    return GeminiStt()


def resolve_audio_answer(
    request: ScoreRequest, stt: SttPort | None = None
) -> AudioResolution | None:
    """요청에 음성이 붙어 있으면 받아써서 채점할 글을 만든다.

    음성이 없으면 None 을 돌려주고, 그러면 채점은 지금까지와 똑같이 진행된다.

    stt 를 넘기면 그것으로 받아쓴다(테스트가 네트워크 없이 도는 자리).
    안 넘기면 지금 꽂혀 있는 구현을 쓴다.

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
    result = engine.transcribe(audio, item_prompt=request.item.prompt)

    # 구현체가 규칙을 어기고 빈 글을 돌려준 경우를 여기서 한 번 더 막는다.
    # 빈 글이 채점으로 흘러가면 '말을 안 한 답안'과 '받아쓰기 실패'가 뒤섞인다
    if not result.text.strip():
        raise SttUnavailable(
            "음성에서 말을 하나도 옮겨 적지 못했다. 녹음 상태를 확인해야 한다."
        )

    return AudioResolution.from_transcription(result)
