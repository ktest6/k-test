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
from typing import TYPE_CHECKING

# 발음 평가 결과의 모양은 채점 쪽과 함께 쓰는 파일(scoring/schema.py)에 있다.
# 발음 자질을 만드는 features/pronunciation.py 도 같은 것을 읽으므로,
# 두 폴더가 서로를 직접 부르지 않고도 같은 값을 주고받을 수 있다.
from ..scoring.schema import AudioInput, PronouncedWord, PronunciationAssessment

if TYPE_CHECKING:
    # 내려받은 음성 파일의 모양(FetchedAudio)은 audio.py 에 있다.
    # 그런데 audio.py 는 실패를 알릴 때 이 파일(port.py)을 불러 쓴다. 두 파일이
    # 맨 위에서 서로를 부르면 파이썬이 둘 다 못 읽으므로(순환 참조),
    # **글자로만 필요한 이 자리에서는 진짜로 불러오지 않는다.**
    # 이름표를 붙이는 데만 쓰고, 프로그램이 돌 때는 이 줄이 실행되지 않는다.
    from .audio import FetchedAudio

__all__ = [
    "PronouncedWord",
    "PronunciationAssessment",
    "PronouncerPort",
    "SttHealth",
    "SttPort",
    "SttUnavailable",
    "Transcription",
]


@dataclass(frozen=True)
class SttHealth:
    """받아쓰기·발음 기계가 **지금 정말 쓸 수 있는 상태인지** 물어본 결과.

    available 이 '설정이 적혀 있다'(서버 주소·열쇠)만 보는 것과 달리,
    이것은 실제로 한 번 두드려 본(ping) 결과다. 설정만 보고 정상이라고
    보고했다가 죽은 서버·틀린 열쇠를 못 알아챈 일이 있어서(2026-08-23 QA),
    LoRA 와 Azure 가 같은 모양으로 이 답을 돌려준다.

    alive 만 있으면 '왜 안 되는지'를 사람이 알 수 없어 사유를 함께 담는다.
    """

    #: 지금 이 기계에 일을 맡길 수 있는 상태인가
    alive: bool
    #: 안 되는 이유(사람이 읽는 한 문장). 정상이면 None
    detail: str | None = None


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
    #: 발음 평가 결과. 발음을 잴 수 있는 제공자(Azure)만 채우고,
    #: 못 재는 제공자(Gemini)는 None 으로 둔다. None 이면 발화 전달력은 채점되지 않는다
    pronunciation: PronunciationAssessment | None = None
    #: 받아쓰기가 **이미 내려받아 둔 음성 파일 그 자체.**
    #:
    #: 왜 여기에 두는가 (2026-08-24):
    #: 받아쓰기(LoRA)와 발음 평가(Azure)를 갈라 놓았더니, 한 답안을 채점하는 동안
    #: **같은 음성 파일을 두 번 내려받고 있었다.** 느리고 데이터도 두 배로 쓰는 데다,
    #: 두 번째 내려받기가 실패하면 이미 성공한 받아쓰기까지 헛일이 된다.
    #: 그래서 받아쓰기가 손에 넣은 파일을 여기에 담아 발음 평가 쪽으로 건네준다.
    #:
    #: **이 값은 채점 결과(API 응답)로 나가지 않는다.** 채점에 넘길 값을 만드는
    #: AudioResolution(intake.py)이 이 칸을 옮겨 담지 않기 때문에, 음성 알맹이가
    #: 백엔드로 새어 나갈 길이 없다. 여기는 speech 폴더 안에서만 쓰는 통로다.
    fetched_audio: "FetchedAudio | None" = None


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


class PronouncerPort(ABC):
    """발음(발화 전달력)만 재는 기계가 지켜야 할 모양.

    **왜 받아쓰기(SttPort)와 따로 두는가.**
    2026-08-22 까지는 Azure 하나가 받아쓰기와 발음을 한 번에 했다. 그런데 우리가
    학습한 LoRA 받아쓰기가 더 정확해지면서, 글은 LoRA 가 받아쓰고 발음만 Azure 가
    재도록 둘을 갈랐다(scoring-design: 발화 전달력은 음성 원본을 본다). 이 자리가
    바로 그 '발음만 재는 쪽'의 계약이다. 받아쓰기를 누가 했든 이쪽은 음성 원본을
    직접 들어 발음 점수만 돌려준다.

    구현체(지금은 AzureStt)가 지킬 것은 둘뿐이다.
      - available 로 부를 수 있는 상태인지 밝힌다(열쇠가 있는지)
      - assess_pronunciation 으로 PronunciationAssessment 를 돌려준다.
        발음을 못 재면 None 을 돌려준다(값을 지어내지 않는다). 이때 delivery 는
        지금까지처럼 채점되지 않고 자리만 남는다. **어떤 이유로든 예외를 올려서는
        안 된다** — 받아쓰기는 이미 끝났는데 발음 때문에 채점 전체가 죽으면 안 된다.
    """

    #: 발음 평가 제공자 이름. 하위 클래스가 덮어쓴다
    provider_name: str = "unknown"

    @property
    @abstractmethod
    def available(self) -> bool:
        """열쇠가 있어서 발음 평가를 시도할 수 있는 상태인지."""

    @abstractmethod
    def assess_pronunciation(
        self,
        audio: AudioInput,
        item_prompt: str = "",
        item_type: str = "",
        fetched: "FetchedAudio | None" = None,
    ) -> PronunciationAssessment | None:
        """음성 원본을 직접 들어 발음 점수만 낸다(받아쓴 글은 쓰지 않는다).

        item_type 이 낭독형이면 item_prompt(제시문)를 정답지로 준다. 받아쓴 글을
        정답지로 넣으면 안 된다 — 발음 평가는 응시자가 실제로 낸 소리를 기준으로
        해야 하는데, 받아쓴 글을 기준으로 삼으면 자기 발음을 자기 글에 맞춰 채점하는
        꼴이 된다.

        fetched 는 **받아쓰기가 이미 내려받아 둔 음성 파일**이다. 주면 그것을 그대로
        쓰고 다시 내려받지 않는다(같은 파일을 두 번 받지 않으려는 것). 안 주면
        지금까지처럼 audio 의 주소로 직접 내려받는다. 이 인자는 나중에 더한 것이라
        받지 않는 구현도 그대로 돌아간다(부르는 쪽이 확인하고 넘긴다).

        발음을 재지 못하면(무음·형식 불가·값 없음·파일을 못 받음) None 을 돌려준다.
        """
