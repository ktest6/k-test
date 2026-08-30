"""백엔드와 주고받는 데이터 형식(계약)을 정의한 파일.

여기 있는 모델이 곧 REST API의 스키마다.
채점 모델 내부(자질 계산 방식, 가중치, LLM 종류)를 바꿔도
이 파일의 필드 이름과 구조는 바뀌지 않도록 설계했다.

핵심 원칙: 점수는 언제나 '근거(Evidence)'와 함께 나간다.
근거 없는 점수는 이 프로젝트에서 기능이 아니라 결함으로 본다.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field

from .messages import Notice

# 채점기 버전. 결합 가중치나 자질 정의가 바뀌면 올린다.
SCORING_VERSION = "0.1.0"


# ---------------------------------------------------------------------------
# 공통 열거형
# ---------------------------------------------------------------------------


class Mode(str, Enum):
    """말하기 답안인지 쓰기 답안인지.

    말하기는 STT(음성을 글자로 옮긴 결과) 전사 텍스트가 들어온다.
    쓰기는 응시자가 직접 친 글이 들어오며, 맞춤법·띄어쓰기 자질이 추가로 켜진다.
    """

    SPEAKING = "speaking"
    WRITING = "writing"


class FeatureSource(str, Enum):
    """이 자질을 누가 계산했는지.

    kiwi = 규칙(형태소 분석)으로 셈, llm = 모델이 판단, azure = 발음평가(이번 범위 밖).
    """

    KIWI = "kiwi"
    LLM = "llm"
    AZURE = "azure"


class FeatureStatus(str, Enum):
    """자질 값이 실제로 계산됐는지 여부."""

    OK = "ok"                      # 정상 계산됨
    UNAVAILABLE = "unavailable"    # 계산에 필요한 외부 자원(LLM 키 등)이 없어서 못 구함
    NOT_APPLICABLE = "not_applicable"  # 이 모드에서는 쓰지 않는 자질 (예: 말하기의 맞춤법)


class ScoreArea(str, Enum):
    """채점 영역. TOPIK 말하기·쓰기의 영역 구분을 그대로 따른다."""

    CONTENT_TASK = "content_task"    # 내용 및 과제 수행
    LANGUAGE_USE = "language_use"    # 언어 사용
    DELIVERY = "delivery"            # 발화 전달력 (Azure 발음평가 필요, 이번 범위 밖)


class AreaStatus(str, Enum):
    """영역 점수가 실제로 산출됐는지 여부."""

    SCORED = "scored"
    PARTIAL = "partial"            # 일부 자질이 빠진 채로 계산됨 (근거에 이유가 남는다)
    NOT_EVALUATED = "not_evaluated"  # 아예 채점하지 않음 (종합 점수에서 제외)


class Reliability(str, Enum):
    """이번 채점을 얼마나 믿을 수 있는지.

    왜 이것이 따로 필요한가:
    LLM을 못 쓰면 채점은 대체 경로로 넘어가는데, 그때도 **점수는 멀쩡한 숫자로 나온다.**
    실제로 같은 답안이 LLM이 살아 있을 때 70.6점, 대체 경로에서 79.7점이 나왔다.
    경고는 달리지만 숫자만 보면 구별이 안 되므로, 화면에 띄우기 전에
    기계가 한 값만 보고 걸러낼 수 있는 표시가 있어야 한다.

    warnings 를 읽어서 판단하게 두면 안 된다. 문구는 바뀌지만 이 값은 안 바뀐다.
    """

    FULL = "full"          # 모든 자질을 계획대로 계산했다
    PARTIAL = "partial"    # 일부 자질을 못 구한 채로 계산했다 (점수는 참고용)
    FALLBACK = "fallback"  # 핵심 판정을 대체 경로로 때웠다 (점수를 응시자에게 보여주면 안 된다)


# ---------------------------------------------------------------------------
# 근거(Evidence)
# ---------------------------------------------------------------------------


class Evidence(BaseModel):
    """점수나 자질 값이 왜 그렇게 나왔는지 보여주는 근거 한 조각.

    quote 는 반드시 답안 원문에 실제로 존재하는 문자열이어야 한다.
    LLM이 만들어낸 인용은 citation.py 의 검증을 통과하지 못하면 여기까지 오지 못한다.
    """

    source: FeatureSource = Field(description="이 근거를 만든 주체")
    quote: str = Field(default="", description="답안 원문에서 그대로 따온 부분")
    start: int | None = Field(default=None, description="원문에서 인용이 시작하는 글자 위치")
    end: int | None = Field(default=None, description="원문에서 인용이 끝나는 글자 위치")
    comment: str = Field(default="", description="이 부분이 왜 근거가 되는지에 대한 설명")
    notice: Notice | None = Field(
        default=None,
        description=(
            "위 comment 와 같은 내용을 '코드 + 값' 으로 담은 것. 백엔드가 영어로 바꿔 쓴다. "
            "LLM 이 그때그때 지어낸 설명이라 고정 문구가 없으면 code 가 LLM_FREE_TEXT 다"
        ),
    )
    detail: dict[str, Any] = Field(
        default_factory=dict,
        description="숫자 자질의 계산 내역처럼 추가로 남길 값",
    )


# ---------------------------------------------------------------------------
# 자질(Feature)
# ---------------------------------------------------------------------------


class FeatureValue(BaseModel):
    """자질 하나의 계산 결과.

    value 는 원래 단위의 값(비율, 개수, 100어절당 개수 등)이고
    normalized 는 결합 모델이 쓰기 좋게 0~1로 편 값이다.
    """

    id: str = Field(description="자질 식별자. 결합 모델과 API가 이 이름으로 자질을 찾는다")
    name: str = Field(description="사람이 읽는 자질 이름")
    source: FeatureSource
    value: float | None = Field(default=None, description="원래 단위의 자질 값")
    unit: str = Field(default="", description="값의 단위 설명")
    status: FeatureStatus = FeatureStatus.OK
    components: dict[str, float] = Field(
        default_factory=dict,
        description="값을 만든 하위 수치(분자·분모 등). 검산할 때 쓴다",
    )
    evidence: list[Evidence] = Field(
        default_factory=list,
        description="이 값이 원문 어디에서 나왔는지",
    )
    note: str = Field(default="", description="임시 구현 등 알아둘 점")
    notice: Notice | None = Field(
        default=None, description="위 note 를 '코드 + 값' 으로 담은 것",
    )


# ---------------------------------------------------------------------------
# 체크리스트
# ---------------------------------------------------------------------------


class ChecklistItem(BaseModel):
    """문항이 답안에 요구하는 내용 하나. 문항 정보와 함께 백엔드가 넘겨준다."""

    id: str
    description: str = Field(description="예: '지각한 이유를 말했는가'")
    description_en: str = Field(
        default="",
        description=(
            "같은 항목을 응시자에게 보여 줄 영어 한 문장 (예: 'Tell him to wear a safety "
            "helmet.'). 리포트 화면의 'Required Points' 칸에 그대로 뜬다. "
            "**채점에는 쓰지 않는다** — LLM 이 읽는 채점 기준은 위 description(한국어)이다. "
            "선택 필드라서 백엔드가 안 보내도 채점은 그대로 돈다"
        ),
    )
    weight: float = Field(default=1.0, ge=0.0, description="항목별 비중")


class ChecklistResult(BaseModel):
    """체크리스트 항목 하나에 대한 0/1 판정 결과."""

    id: str
    description: str
    #: 요청에 실려 온 영어 문장을 그대로 되돌려준다. 안 보냈으면 빈 문자열이다
    description_en: str = ""
    met: int = Field(ge=0, le=1, description="충족했으면 1, 아니면 0")
    weight: float = 1.0
    source: FeatureSource = FeatureSource.LLM
    evidence: list[Evidence] = Field(default_factory=list)
    note: str = ""
    notice: Notice | None = Field(
        default=None, description="위 note 를 '코드 + 값' 으로 담은 것",
    )


# ---------------------------------------------------------------------------
# 점수
# ---------------------------------------------------------------------------


class ScoreContribution(BaseModel):
    """영역 점수가 어떤 자질에서 몇 점씩 왔는지 보여주는 내역 한 줄.

    "언어 사용 61점"만 주면 응시자도 운영자도 납득할 수 없기 때문에
    항상 이 내역을 함께 낸다.
    """

    feature_id: str
    feature_name: str
    raw_value: float | None = None
    normalized: float = Field(ge=0.0, le=1.0, description="0~1로 편 값")
    weight: float = Field(description="이 영역 안에서의 비중(재정규화 후)")
    points: float = Field(description="이 자질이 영역 점수에 실제로 보탠 점수")


class SubScore(BaseModel):
    """영역별 점수."""

    area: ScoreArea
    label: str
    score: float | None = Field(default=None, description="0~100")
    max_score: float = 100.0
    weight: float = Field(description="종합 점수에서 이 영역이 차지하는 비중(재정규화 후)")
    status: AreaStatus = AreaStatus.SCORED
    contributions: list[ScoreContribution] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    note: str = ""
    notice: Notice | None = Field(
        default=None, description="위 note 를 '코드 + 값' 으로 담은 것",
    )


class ScoringMeta(BaseModel):
    """이 채점이 어떤 조건에서 이뤄졌는지 남기는 자리."""

    scoring_version: str = SCORING_VERSION
    mode: Mode
    weights_provisional: bool = Field(
        default=True,
        description="True 면 가중치가 학습된 값이 아니라 임시로 정한 값이라는 뜻",
    )
    weights_profile: str = "provisional_v0"
    llm_used: bool = False
    llm_model: str | None = None
    # 오류 자질(조사·어미·어휘·높임법)만 다른 모델로 돌린다. 나중에 추가한 값이라 기본값이 있다.
    # 상위 모델이라야 잡히는 오류가 있어서(높임법 오류가 실측으로 확인됐다) 갈라 두었고,
    # 어떤 모델이 문법을 판정했는지가 남아야 채점 결과를 나중에 재현할 수 있다.
    llm_model_errors: str | None = Field(
        default=None,
        description=(
            "오류 자질 추출에 실제로 쓴 모델 이름. llm_model 과 다를 수 있다. "
            "LLM을 쓰지 않았으면 null 이다"
        ),
    )
    dropped_citations: int = Field(
        default=0, description="원문에 없어서 버린 LLM 인용 개수",
    )
    timings_ms: dict[str, float] = Field(default_factory=dict)

    # --- 이 점수를 믿어도 되는지 (나중에 추가한 값이고 기본값이 있다) ---
    reliability: Reliability = Field(
        default=Reliability.FULL,
        description=(
            "이번 채점의 신뢰 수준. full=계획대로 계산함, "
            "partial=일부 자질을 못 구함, fallback=핵심 판정을 대체 경로로 때움"
        ),
    )
    reliability_reason: str = Field(
        default="",
        description="full 이 아닐 때 그 이유. 사람이 읽는 한 문장이다",
    )
    safe_to_show_candidate: bool = Field(
        default=True,
        description=(
            "채점이 정상적으로 이뤄져서 이 숫자를 화면에 띄워도 되는지. "
            "False 면 점수를 보여주지 말고 '채점 중' 또는 재채점으로 처리해야 한다. "
            "warnings 를 읽어서 판단하지 말고 이 값 하나만 보면 된다. "
            "등급을 확정 통보해도 되는지는 다른 문제이며 weights_provisional 로 따로 본다"
        ),
    )

    # --- 답안 유효성 가드 (전부 나중에 추가한 값이고 기본값이 있다) ---
    # 가드를 안 태우면 지금까지와 똑같이 answer_valid=True 인 채로 나간다.
    #
    # 왜 이 값이 필요한가:
    # 한국어를 한 글자도 안 쓴 답안이 문법 오류가 0건이라는 이유로 B등급을 받았다(실측).
    # 그래서 채점 전에 '이 글이 채점 대상이 되는 답안인가'를 규칙으로 먼저 확인한다.
    # 무효 판정이 나면 overall_score 와 overall_grade 가 null 로 나가므로,
    # 백엔드는 점수를 읽기 전에 이 값을 봐야 한다.
    answer_valid: bool = Field(
        default=True,
        description=(
            "답안이 채점 대상으로 성립하는지. False 면 overall_score 와 overall_grade 가 "
            "null 이고 safe_to_show_candidate 도 False 다. 사유는 validity_reason 에 있다"
        ),
    )
    validity_flags: list[str] = Field(
        default_factory=list,
        description=(
            "걸린 가드의 표시 이름 목록. 문구가 아니라 이 값으로 분기한다. "
            "not_korean(한국어가 아님) / prompt_copy(지시문 베끼기) 는 채점 무효, "
            "too_short(너무 짧음) / not_sentences(문장이 아님) 는 경고만인 경우가 있다"
        ),
    )
    validity_reason: str = Field(
        default="",
        description="가드에 걸렸을 때 그 사유. 사람이 읽는 한 문장이다",
    )

    # --- STT 전사 보정 관련 (전부 나중에 추가한 값이고 기본값이 있다) ---
    # 보정을 안 하면 지금까지와 똑같이 transcript_correction_applied=False 인 채로 나간다.
    transcript_correction_applied: bool = Field(
        default=False,
        description="STT 전사 보정을 실제로 적용했는지. False 면 전사 원문 그대로 채점했다는 뜻",
    )
    transcript_change_count: int = Field(
        default=0, description="전사 보정으로 고쳐진 자리의 개수",
    )
    transcript_low_confidence_errors: int = Field(
        default=0,
        description=(
            "보정 구간과 겹쳐 '신뢰도 낮음'으로 표시된 오류 지적 건수. "
            "응시자의 문법 오류가 아니라 전사 오류일 수 있는 지적의 수다"
        ),
    )
    transcript_corrected_text: str | None = Field(
        default=None,
        description=(
            "보정본 전문. 내용·과제 수행 채점에만 쓰인 글이다. "
            "보정을 안 했으면 null 이다"
        ),
    )
    transcript_diff: list[Evidence] = Field(
        default_factory=list,
        description=(
            "무엇이 무엇으로 바뀌었는지에 대한 근거 목록. "
            "start/end 는 '전사 원문(answer_text) 기준' 글자 위치다. "
            "응시자가 '그렇게 말하지 않았다'고 이의를 제기할 때 쓰는 추적 자료다"
        ),
    )

    # --- 음성 파일을 받아썼을 때만 채우는 값 (전부 나중에 추가했고 기본값이 있다) ---
    # 음성을 안 보내면 전부 null 이라 지금까지의 응답과 똑같다.
    #
    # 왜 남기는가:
    # 말하기 점수는 '응시자가 말한 것'이 아니라 '기계가 받아쓴 글'에 매겨진다.
    # 어느 기계가 받아썼는지와 그 글이 무엇이었는지가 남지 않으면
    # 응시자가 "나는 그렇게 말하지 않았다"고 할 때 짚어 줄 것이 없다.
    stt_provider: str | None = Field(
        default=None,
        description=(
            "음성을 글자로 옮긴 제공자 이름(예: 'gemini'). "
            "음성을 안 보냈으면 null 이다. 나중에 Azure 로 바뀌면 이 값이 바뀐다"
        ),
    )
    stt_model: str | None = Field(
        default=None,
        description="받아쓰기에 실제로 쓴 모델 이름. 같은 음성을 다시 채점할 때 대조하는 값이다",
    )
    audio_duration_ms: int | None = Field(
        default=None,
        description=(
            "받아쓴 음성의 길이(밀리초). wav 는 파일에서 직접 잰 값이고, "
            "다른 형식은 요청이 알려 준 값이다. 알 수 없으면 null 이다"
        ),
    )
    stt_transcript: str | None = Field(
        default=None,
        description=(
            "받아쓴 글 전문. 이 글이 곧 채점 대상이 된 answer_text 다. "
            "음성으로 채점한 결과를 설명하려면 이 값이 반드시 보관돼야 한다"
        ),
    )


# ---------------------------------------------------------------------------
# 발음 평가 결과 (나중에 추가한 모델)
#
# 여기 두는 이유:
# 이 값은 음성을 직접 들은 기계(Azure 발음평가)가 만들고, 발음 자질을 만드는
# features/pronunciation.py 가 받아 쓴다. 두 쪽이 서로를 직접 부르지 않도록
# **양쪽이 다 아는 이 파일**에 모양만 정해 둔다(AudioInput 과 같은 이유다).
#
# 이 모델은 /score 응답에 그대로 실리지 않는다. 발음 점수는 자질(FeatureValue)과
# 영역 점수(SubScore)로 바뀌어 나가므로 백엔드가 받는 형식은 바뀌지 않는다.
# ---------------------------------------------------------------------------


class PronouncedWord(BaseModel):
    """발음 평가가 낱말 하나에 매긴 결과.

    낱말 단위로 남기는 이유:
    "발음 62점"만 주면 응시자는 무엇을 고쳐야 할지 알 수 없다.
    어느 낱말이 몇 점이었는지가 있어야 점수를 설명할 수 있고,
    그 낱말을 채점 근거(Evidence)의 인용으로 그대로 쓸 수 있다.
    """

    word: str = ""
    accuracy: float | None = Field(default=None, description="이 낱말의 발음 정확도(0~100)")
    error_type: str = Field(
        default="",
        description=(
            "평가가 붙인 표시. None(정상) / Mispronunciation(잘못 발음) / "
            "Omission(빠뜨림) / Insertion(없는 말을 넣음)"
        ),
    )
    offset_ms: int | None = Field(default=None, description="녹음에서 이 낱말이 나온 자리(밀리초)")
    duration_ms: int | None = Field(default=None, description="이 낱말을 말한 길이(밀리초)")


class PronunciationAssessment(BaseModel):
    """발음 평가 한 번의 결과. **음성을 직접 들은 기계만 만들 수 있는 값이다.**

    받아쓴 '글'로는 발음을 알 수 없어서 이 값은 받아쓰기와 같은 호출에서 함께 받아 온다
    (scoring-design: 발화 전달력은 음성 원본을 본다).
    발음을 못 재는 제공자(Gemini)는 이 값을 만들지 않고 None 으로 둔다.
    그러면 발화 전달력 영역은 지금까지처럼 채점하지 않고 자리만 남는다.

    네 점수의 뜻 (전부 0~100):
      accuracy     소리를 얼마나 정확히 냈는가
      fluency      끊김·머뭇거림 없이 이어 말했는가
      completeness 읽어야 할 말 중 얼마나 말했는가 (제시문을 주고 읽힐 때만 뜻이 있다)
      overall      위 셋을 제공자가 자기 방식으로 합친 종합값
    """

    accuracy: float | None = None
    fluency: float | None = None
    completeness: float | None = None
    overall: float | None = None
    prosody: float | None = Field(
        default=None,
        description=(
            "억양·강세 점수. 제공자가 그 언어에 대해 주지 않으면 null 이다"
            "(한국어는 2026-08-22 실측에서 값이 오지 않았다)"
        ),
    )
    scripted: bool = Field(
        default=False,
        description=(
            "낭독형 문항이라 제시문을 정답지로 주고 평가했는지. "
            "자유 발화(false)에서는 completeness 를 점수로 쓰지 않는다 — "
            "읽어야 할 원문이 없어서 '얼마나 말했는가'의 기준이 없기 때문이다"
        ),
    )
    reference_text: str = Field(default="", description="정답지로 준 제시문. 자유 발화면 빈 문자열")
    words: list[PronouncedWord] = Field(
        default_factory=list, description="낱말별 결과. 낮은 점수 낱말이 채점 근거의 인용이 된다",
    )
    provider: str = Field(default="", description="어느 회사 기계가 발음을 쟀는지")
    warnings: list[str] = Field(default_factory=list, description="사람이 알아야 할 것")
    notices: list[Notice] = Field(
        default_factory=list,
        description="위 warnings 와 같은 내용을 '코드 + 값' 으로 담은 것",
    )


class ScoreRequest(BaseModel):
    """백엔드 -> 채점 모델 입력. (고정 계약)"""

    submission_id: str = Field(description="답안 식별자")
    mode: Mode
    # 기본값이 "" 인 이유:
    # 음성 파일(audio)만 보내는 호출이 생겼기 때문이다. 그때는 우리가 전사해서 이 자리를 채운다.
    # 값을 넣어 보내면 지금까지와 똑같이 그 글을 채점한다(기존 호출은 하나도 안 바뀐다).
    answer_text: str = Field(
        default="",
        description=(
            "채점할 답안 텍스트. 말하기는 STT 전사 결과. "
            "audio 를 보내는 경우에는 비워 두고, 그러면 전사 결과가 이 자리에 들어간다"
        ),
    )
    item: "ItemInfo"
    options: "ScoreOptions" = Field(default_factory=lambda: ScoreOptions())
    transcript: "TranscriptInput | None" = Field(
        default=None,
        description=(
            "말하기 답안의 STT 전사 보정 설정. 안 보내면 보정을 하지 않고 "
            "지금까지와 똑같이 answer_text 하나로만 채점한다(기존 호출은 그대로 동작한다)"
        ),
    )
    audio: "AudioInput | None" = Field(
        default=None,
        description=(
            "말하기 답안의 음성 파일 위치. 보내면 우리가 받아써서 채점한다. "
            "안 보내면 지금까지와 똑같이 answer_text 로만 채점한다(기존 호출은 그대로 동작한다)"
        ),
    )


class ItemInfo(BaseModel):
    """문항 정보."""

    item_id: str
    prompt: str = Field(description="응시자에게 제시된 지시문")
    item_type: str = Field(default="free_response", description="문항 유형")
    checklist: list[ChecklistItem] = Field(
        default_factory=list, description="내용·과제 수행 판정에 쓸 항목들",
    )
    expected_register: Literal["formal", "polite", "any"] = Field(
        default="formal",
        description="이 문항이 요구하는 말투. formal=합쇼체 중심, polite=해요체 허용",
    )
    reference_keywords: list[str] = Field(
        default_factory=list,
        description="LLM을 못 쓸 때 쓰는 임시 대체 판정용 핵심어",
    )
    image: str = Field(
        default="",
        description=(
            "이미지 제시형 문항에서 응시자에게 보여 줄 그림 파일 이름 (예: 'SPK-101.png'). "
            "화면에 무엇을 띄울지 고르는 값일 뿐이고 채점에는 쓰지 않는다. "
            "선택 필드라서 백엔드가 안 보내도 채점은 그대로 돈다"
        ),
    )
    audio: str = Field(
        default="",
        description=(
            "음성 질문형 문항에서 응시자에게 들려 줄 질문 소리 파일 이름 (예: 'SPK-105.wav'). "
            "image 와 똑같이 화면(스피커)에 무엇을 틀지 고르는 값일 뿐이고 채점에는 쓰지 않는다. "
            "채점 LLM 은 소리를 듣지 못하므로 질문 문장 자체는 prompt 에 글로 적어 둔다. "
            "선택 필드라서 백엔드가 안 보내도 채점은 그대로 돈다"
        ),
    )
    scene_description: str = Field(
        default="",
        description=(
            "위 image 에 무엇이 있는지 글로 적어 둔 것 (예: '초록 바탕 표지에 위쪽 화살표와 "
            "비상대피로 글자'). 채점하는 LLM 은 그림을 보지 못하므로, "
            "'시각 요소를 말했는가' 같은 항목을 판정하려면 그림 내용을 글로 받아야 한다. "
            "선택 필드라서 없으면 예전처럼 지시문과 답안만 보고 판정한다"
        ),
    )


class ScoreOptions(BaseModel):
    """호출할 때 조절할 수 있는 항목."""

    use_llm: bool = Field(default=True, description="False 면 규칙 자질만으로 채점한다")
    weights_profile: str = Field(default="provisional_v0", description="쓸 가중치 묶음 이름")


class TranscriptInput(BaseModel):
    """말하기 답안의 STT 전사 보정을 켤 때 백엔드가 함께 보내는 값.

    전사 원문은 따로 보내지 않는다. 이미 ScoreRequest.answer_text 가 그 글이다.
    이 모델은 '그 글을 보정할지, 보정할 때 무엇을 참고할지'만 정한다.

    왜 보정을 하나:
    말하기 답안은 기계가 받아쓴 글이라 잘못 적힌 곳이 있고,
    그것을 그대로 두면 응시자가 하지 않은 실수로 내용 점수가 깎인다.
    다만 보정본은 '내용·과제 수행' 채점에만 쓰이고,
    문법·어휘 채점은 언제나 보정 전 원문으로 한다(그래야 실제 오류가 지워지지 않는다).
    """

    correct: bool = Field(
        default=True,
        description=(
            "True 면 LLM으로 전사 보정을 시도한다. False 면 원문 그대로 채점한다. "
            "쓰기(writing) 답안은 응시자가 직접 친 글이라 보정하지 않는다"
        ),
    )
    nationality: str | None = Field(
        default=None,
        description=(
            "응시자 국적(예: '베트남', '네팔'). 어떤 소리를 음성 인식기가 "
            "헷갈렸을지 짐작하는 데만 쓴다. 없으면 없는 대로 보정한다"
        ),
    )


class AudioInput(BaseModel):
    """말하기 답안의 음성 파일이 어디 있는지 알려 주는 값. (나중에 추가한 필드)

    파일 자체를 요청에 담지 않고 주소만 받는다.
    음성 파일은 백엔드가 Object Storage 에 저장하고, 우리는 그것을 내려받아 읽기만 한다.
    (우리는 아무것도 저장하지 않는다)

    이 값을 보내면 answer_text 는 비워 둔다. 우리가 받아쓴 글이 그 자리에 들어간다.
    둘 다 보내면 어느 쪽을 채점해야 할지 알 수 없으므로 거절한다.
    """

    url: str = Field(
        description="음성 파일 주소. http/https 만 받는다(서버 안의 파일 경로는 받지 않는다)",
    )
    format: str | None = Field(
        default=None,
        description=(
            "음성 형식(wav/webm/mp3/m4a/ogg). 안 보내면 주소 끝의 확장자와 "
            "서버가 알려 준 형식으로 우리가 알아낸다"
        ),
    )
    duration_ms: int | None = Field(
        default=None,
        description=(
            "녹음 길이(밀리초). 아는 값이 있으면 보낸다. "
            "wav 는 우리가 파일에서 직접 재므로 안 보내도 된다"
        ),
    )


class ScoreResponse(BaseModel):
    """채점 모델 -> 백엔드 출력. (고정 계약)

    종합 점수 + 영역별 서브스코어 + 근거. 이 세 가지가 항상 함께 나간다.
    """

    submission_id: str
    item_id: str
    mode: Mode
    overall_score: float | None = Field(description="0~100 종합 점수")
    overall_grade: str | None = Field(description="임시 커트라인으로 매긴 등급")
    subscores: list[SubScore]
    features: list[FeatureValue]
    checklist_results: list[ChecklistResult] = Field(default_factory=list)
    warnings: list[str] = Field(
        default_factory=list,
        description="임시 대체 경로를 탔거나 인용을 버린 경우 등 알아야 할 사항",
    )
    notices: list[Notice] = Field(
        default_factory=list,
        description=(
            "위 warnings 와 같은 내용을 '코드 + 값' 으로 담은 것. 백엔드는 이 코드로 "
            "영어 문구를 골라 화면에 띄운다. 두 목록의 길이와 차례는 언제나 같다"
        ),
    )
    meta: ScoringMeta


# ---------------------------------------------------------------------------
# 시험 전체 최종 등급 (POST /finalize)
#
# 채점은 문항 단위로 그때그때 이뤄지고(POST /score),
# 시험이 끝나면 그 결과들을 모아 하나의 최종 등급을 낸다(POST /finalize).
#
# 아래 모델은 전부 새로 추가한 것이다.
# 위쪽의 ScoreRequest / ScoreResponse 는 이미 백엔드와 주고받기로 한 계약이라
# 한 글자도 건드리지 않았다.
# ---------------------------------------------------------------------------


class ItemScoreStatus(str, Enum):
    """문항 하나의 채점이 어떤 상태인지."""

    SCORED = "scored"    # 채점 끝남
    PENDING = "pending"  # 아직 채점 중 (시험이 먼저 끝난 경우)
    FAILED = "failed"    # 채점하다 실패함


class FinalizeStatus(str, Enum):
    """시험 전체 결과를 얼마나 믿을 수 있는지."""

    COMPLETE = "complete"          # 모든 문항이 채점됨
    PARTIAL = "partial"            # 일부 문항이 빠졌지만 등급을 낼 만큼은 채점됨
    INSUFFICIENT = "insufficient"  # 채점된 문항이 너무 적어 등급을 확정하지 않음


class ExpectedItem(BaseModel):
    """이 시험에 원래 몇 문항이 있었는지 알려 주는 목록의 한 줄.

    이것이 있어야 '아직 채점이 안 끝난 문항'을 알아챌 수 있다.
    없으면 넘어온 결과만으로 시험 전체라고 가정한다.
    """

    item_id: str
    mode: Mode
    weight: float = Field(default=1.0, ge=0.0, description="이 문항의 비중")


class FinalizeItem(BaseModel):
    """문항 하나의 채점 결과.

    필드 이름을 ScoreResponse 와 똑같이 맞춰 두었기 때문에
    백엔드는 /score 응답을 그대로 담아 보내면 된다(모르는 필드는 무시된다).
    item_weight 와 status 만 이 모델에서 새로 쓰는 값이고 둘 다 기본값이 있다.
    """

    item_id: str
    mode: Mode
    overall_score: float | None = None
    overall_grade: str | None = None
    subscores: list[SubScore] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    # /score 응답을 그대로 담아 보내는 자리라, 새로 붙은 notices 도 받아 줘야
    # '모르는 필드'로 조용히 버려지지 않는다
    notices: list[Notice] = Field(default_factory=list)

    # /score 응답을 통째로 담아 보내면 여기에 그대로 들어온다.
    # 문항별 신뢰도를 최종 결과까지 끌고 가기 위해 받는다(안 보내도 동작한다).
    meta: ScoringMeta | None = Field(
        default=None,
        description=(
            "그 문항 /score 응답의 meta. 함께 보내면 문항별 신뢰도가 최종 결과에 반영된다. "
            "안 보내면 신뢰도를 알 수 없는 것으로 보고 넘어간다"
        ),
    )

    item_weight: float = Field(
        default=1.0, ge=0.0, description="이 문항이 최종 점수에서 차지하는 비중",
    )
    status: ItemScoreStatus = ItemScoreStatus.SCORED


class FinalizeOptions(BaseModel):
    """최종 등급 산출을 조절하는 값들. 모두 임시 기본값이 들어 있다."""

    weights_profile: str = "provisional_v0"
    min_scored_ratio: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="채점된 문항 비중이 이보다 낮으면 등급을 확정하지 않는다(임시값)",
    )
    min_scored_items: int = Field(
        default=3,
        ge=1,
        description="등급을 내려면 최소한 이만큼의 문항이 채점돼 있어야 한다(임시값)",
    )
    cross_mode_gap_threshold: int = Field(
        default=3,
        ge=1,
        description="말하기와 쓰기 등급이 이만큼 벌어지면 검토 신호를 띄운다(임시값)",
    )


class ModeResult(BaseModel):
    """말하기 / 쓰기 각각의 결과.

    두 모드를 따로 남기는 이유는 최종 등급 산출뿐 아니라
    말하기·쓰기 등급 차이를 부정행위 교차검증 신호로 쓸 수 있게 하기 위해서다.
    """

    mode: Mode
    score: float | None = None
    grade: str | None = None
    scored_item_count: int = 0
    expected_item_count: int = 0


class CrossModeCheck(BaseModel):
    """말하기와 쓰기 등급을 견줘 본 결과.

    ※ 이것은 신호일 뿐 판정이 아니다. ※
    부정행위 여부를 정하는 것은 이 파트의 일이 아니므로 결론을 내지 않는다.
    """

    comparable: bool = Field(description="두 모드가 다 채점돼 비교가 가능했는지")
    speaking_grade: str | None = None
    writing_grade: str | None = None
    grade_gap: int | None = Field(
        default=None, description="두 등급이 몇 칸 떨어져 있는지",
    )
    threshold: int = Field(description="이 값 이상 벌어지면 신호를 띄운다(임시값)")
    flagged: bool = Field(default=False, description="검토 권장 신호가 떴는지")
    note: str = ""
    notice: Notice | None = Field(
        default=None, description="위 note 를 '코드 + 값' 으로 담은 것",
    )


class ItemCoverage(BaseModel):
    """몇 문항 중 몇 문항이 실제로 채점됐는지."""

    expected_count: int
    scored_count: int
    missing_item_ids: list[str] = Field(default_factory=list)
    pending_item_ids: list[str] = Field(default_factory=list)
    failed_item_ids: list[str] = Field(default_factory=list)
    scored_ratio: float = Field(description="채점된 문항의 비중(개수가 아니라 가중치 기준)")
    min_scored_ratio: float = Field(description="유효 판정에 쓴 기준값(임시값)")
    min_scored_items: int = Field(description="유효 판정에 쓴 최소 문항 수(임시값)")


class FinalizeMeta(BaseModel):
    """최종 등급이 어떤 조건에서 나왔는지 남기는 자리."""

    scoring_version: str = SCORING_VERSION
    weights_profile: str = "provisional_v0"
    weights_provisional: bool = Field(
        default=True, description="True 면 결합 가중치가 학습된 값이 아니라는 뜻",
    )
    cutoffs_from_anchor_answers: bool = Field(
        default=False,
        description="False 면 등급 커트라인이 전문가가 확정한 앵커 답안이 아니라 임시값이라는 뜻",
    )
    percentile_provisional: bool = Field(
        default=True,
        description="True 면 백분위가 실제 응시자 분포가 아니라 임시 환산표에서 나왔다는 뜻",
    )
    grade_cutoffs: dict[str, float] = Field(
        default_factory=dict, description="이번 산출에 쓴 등급 커트라인",
    )

    # --- 시험 전체의 신뢰 수준 (문항 중 가장 나쁜 것을 따른다) ---
    # 한 문항이라도 대체 경로로 때워졌으면 최종 점수도 그만큼 오염돼 있다.
    # 평균을 내면 그 사실이 묻히므로 '가장 나쁜 문항'을 기준으로 삼는다.
    reliability: Reliability = Field(
        default=Reliability.FULL,
        description="문항들 중 가장 낮은 신뢰 수준. 하나라도 fallback 이면 fallback 이다",
    )
    reliability_reason: str = Field(
        default="", description="full 이 아닐 때 그 이유. 사람이 읽는 한 문장이다",
    )
    safe_to_show_candidate: bool = Field(
        default=True,
        description=(
            "최종 점수를 화면에 띄워도 되는지. False 면 재채점이 필요하다. "
            "등급 확정 통보 가능 여부는 weights_provisional 로 따로 본다"
        ),
    )
    unreliable_item_ids: list[str] = Field(
        default_factory=list,
        description="신뢰 수준이 full 이 아니었던 문항 id 목록. 어느 문항을 다시 채점할지 알려 준다",
    )


class FinalizeRequest(BaseModel):
    """백엔드 -> 채점 모델 입력. 시험 하나의 문항별 결과를 모아 보낸다. (고정 계약)"""

    session_id: str = Field(description="시험 응시 세션 식별자")
    candidate_id: str | None = Field(default=None, description="응시자 식별자")
    items: list[FinalizeItem] = Field(
        default_factory=list, description="문항별 채점 결과. /score 응답을 그대로 담아도 된다",
    )
    expected_items: list[ExpectedItem] = Field(
        default_factory=list,
        description="이 시험의 전체 문항 목록. 비워 두면 items 가 전부라고 본다",
    )
    options: FinalizeOptions = Field(default_factory=FinalizeOptions)


class FinalizeResponse(BaseModel):
    """채점 모델 -> 백엔드 출력. 시험 하나의 최종 결과. (고정 계약)

    백엔드가 가중치나 등급 커트라인을 알 필요가 없도록
    등급과 백분위까지 여기서 다 계산해서 보낸다.
    """

    session_id: str
    candidate_id: str | None = None
    status: FinalizeStatus
    overall_score: float | None = Field(description="0~100 최종 종합 점수")
    overall_grade: str | None = Field(description="임시 커트라인으로 매긴 최종 등급")
    percentile: float | None = Field(
        default=None, description="임시 환산표로 구한 백분위(0~100, 높을수록 상위)",
    )
    subscores: list[SubScore] = Field(description="영역별 최종 점수와 문항별 기여 내역")
    mode_results: list[ModeResult] = Field(default_factory=list)
    cross_mode_check: CrossModeCheck
    item_coverage: ItemCoverage
    warnings: list[str] = Field(default_factory=list)
    notices: list[Notice] = Field(
        default_factory=list,
        description=(
            "위 warnings 와 같은 내용을 '코드 + 값' 으로 담은 것. "
            "두 목록의 길이와 차례는 언제나 같다"
        ),
    )
    meta: FinalizeMeta


# pydantic 이 문자열로 적어둔 타입(ItemInfo 등)을 실제 클래스와 연결하도록 마무리한다.
ScoreRequest.model_rebuild()
