"""음성을 글자로 옮기는 일(STT)의 '꽂는 자리'를 정한 파일.

여기에는 계약만 있고 실제 구현은 없다.
지금 꽂혀 있는 것은 Gemini(gemini_stt.py)이고, Azure 계정이 나오면
같은 자리에 AzureStt 를 만들어 꽂는다. **그때 고칠 파일은 이 폴더 안뿐이다** —
채점 파이프라인도 백엔드가 보는 API 형식도 손대지 않는다.

그래서 이 파일이 정하는 것은 딱 두 가지다.
  1) 무엇을 받는가  : 음성 파일 위치(AudioInput)
  2) 무엇을 돌려주는가: 받아쓴 글 + 그 글이 어떻게 나왔는지(Transcription)

'어떻게 나왔는지'를 함께 돌려주는 이유:
말하기 점수는 응시자가 말한 소리가 아니라 기계가 받아쓴 글에 매겨진다.
어느 기계가 받아썼는지 남지 않으면 나중에 그 점수를 설명할 수 없다.
이 프로젝트에서 근거 없는 점수는 기능이 아니라 결함이다.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from ..scoring.schema import AudioInput


class SttUnavailable(RuntimeError):
    """음성을 글자로 옮기지 못했을 때 올리는 예외.

    **채점의 LLM 실패와 다르게 다룬다.**
    채점은 LLM을 못 써도 규칙 자질로 점수를 내지만, 받아쓰기는 대체 경로가 없다.
    못 알아들은 음성을 그럴듯한 문장으로 지어내면 응시자가 하지도 않은 말로
    점수를 받게 되므로, 실패하면 실패했다고 말한다(창구가 503 으로 바꿔 알린다).

    메시지는 그대로 백엔드에 전달되므로 사람이 읽는 한 문장만 담는다.
    """

    def __init__(self, message: str, detail: str = ""):
        super().__init__(message)
        # 개발자가 원인을 찾을 때 쓰는 자리. 응답에는 실리지 않는다
        self.detail = detail


@dataclass
class Transcription:
    """받아쓰기 한 번의 결과.

    text 말고 나머지가 전부 '이 글이 어떻게 나왔는지'를 남기는 값이다.
    """

    text: str
    #: 어느 회사 기계가 받아썼는지 (예: "gemini"). Azure 로 바꾸면 이 값이 바뀐다
    provider: str
    #: 실제로 쓴 모델 이름
    model: str
    #: 음성 길이(밀리초). 잴 수 없으면 None
    audio_duration_ms: int | None = None
    #: 내려받은 파일 크기(바이트). 비용과 한도를 확인할 때 쓴다
    audio_bytes: int = 0
    #: 이 형식으로 읽었다는 기록 (wav/webm/mp3/m4a/ogg)
    audio_format: str = ""
    #: 토큰 사용량. 제공자가 안 알려 주면 None 이다
    input_tokens: int | None = None
    output_tokens: int | None = None
    #: 걸린 시간(밀리초)
    elapsed_ms: float = 0.0
    #: 사람이 알아야 할 것(예: 길이를 재지 못했다)
    warnings: list[str] = field(default_factory=list)


class SttPort(ABC):
    """음성 → 글자 변환기가 지켜야 할 모양.

    구현체는 이 세 가지만 지키면 된다.
      - provider_name / model_name 을 밝힌다 (채점 결과에 남는다)
      - transcribe(audio) 로 Transcription 을 돌려준다
      - 실패하면 SttUnavailable 을 올린다. **빈 글자나 지어낸 글을 돌려주지 않는다**
    """

    #: 제공자 이름. 하위 클래스가 덮어쓴다
    provider_name: str = "unknown"

    @property
    @abstractmethod
    def model_name(self) -> str:
        """받아쓰기에 쓰는 모델 이름. 채점 결과에 그대로 남는다."""

    @abstractmethod
    def transcribe(self, audio: AudioInput, item_prompt: str = "") -> Transcription:
        """음성 파일 하나를 받아써서 글과 그 내력을 돌려준다.

        item_prompt 는 응시자가 받은 문항 지시문이다. 그 상황에서 나올 만한
        현장 용어를 알아듣는 데만 쓰는 참고 자료이며, 안 줘도 동작해야 한다.
        (기대하는 답안을 알려 주는 자리가 아니다. 안 들린 자리를 그 답으로
         메우면 응시자가 하지 않은 말로 점수를 받게 된다)

        실패하면 SttUnavailable 을 올린다. 빈 글이나 지어낸 글을 돌려주지 않는다.
        """
