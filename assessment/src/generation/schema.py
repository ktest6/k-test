"""문서 → 문항 생성 API 의 데이터 형식(계약)을 정의한 파일.

여기 있는 모델이 곧 `POST /generate-items` 와 `POST /verify-items` 의 스키마다.

**채점 계약(scoring/schema.py)과 일부러 파일을 나눴다.**
그쪽은 "여기를 바꾸면 백엔드가 깨진다"고 못 박은 채점 전용 계약 파일이라,
생성용 필드를 섞으면 백엔드가 채점 스키마를 볼 때마다 생성 필드를 함께 읽게 된다.
대신 문항 모델은 채점 쪽 `ItemInfo` 를 **상속**해서 만든다.
그래야 여기서 만든 문항을 백엔드가 그대로 채점 요청에 넣을 수 있다.

핵심 원칙(채점 쪽과 같다): 생성물은 언제나 '근거(Citation)'와 함께 나간다.
근거를 대지 못한 문항은 응답에 실리지 않고 폐기 수로만 보고된다.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

from ..scoring.schema import ChecklistItem, ItemInfo, Mode

# 생성 모듈 버전. 관문이나 조립 방식이 바뀌면 올린다.
GENERATION_VERSION = "0.1.0"

# 문서 길이의 아래·위 한계.
# 아래: 이보다 짧으면 문항을 만들 만한 내용이 없다.
# 위: 이보다 길면 통째로 거절한다. **조용히 잘라내지 않는다** —
#     자르면 관리자가 보낸 문서와 문항이 나온 문서가 달라지는데 응답만 보고는 알 수 없다.
# 둘 다 근거가 있는 값이 아니라 첫 기준값이다.
MIN_DOCUMENT_CHARS = 500
MAX_DOCUMENT_CHARS = 30_000


class GeneratedItemType(str, Enum):
    """만들 수 있는 쓰기 문항의 다섯 가지 유형.

    전부 '현장에서 실제로 쓰는 글'이다.
    지식을 외웠는지가 아니라 상황을 한국어로 전달할 수 있는지를 재기 위해서다.
    """

    WORK_LOG = "work_log"                  # 작업일지: 오늘 한 작업을 기록한다
    MESSENGER_REPORT = "messenger_report"  # 메신저 보고: 윗사람에게 상황을 알린다
    HAZARD_REPORT = "hazard_report"        # 위험 보고: 위험한 것을 안전 담당자에게 알린다
    HANDOVER_MEMO = "handover_memo"        # 인수인계 메모: 다음 근무자에게 남긴다
    SUPPLY_REQUEST = "supply_request"      # 물품 요청: 필요한 것을 사무실에 요청한다


class DropReason(str, Enum):
    """문항을 버린 까닭을 나타내는 코드값.

    백엔드와 프론트는 **문구가 아니라 이 값으로 분기한다.**
    문구는 다듬을 수 있지만 이 값은 바뀌지 않는다(채점 쪽 validity_flags 와 같은 원칙).
    """

    SCHEMA_INVALID = "schema_invalid"                    # 필드가 없거나 값 범위가 틀렸다
    UNKNOWN_ITEM_TYPE = "unknown_item_type"              # 다섯 유형에 없는 유형을 만들었다
    PROMPT_FORMAT_INVALID = "prompt_format_invalid"      # 지시문 형식 규칙 위반
    PROMPT_NOT_A_WRITING_TASK = "prompt_not_a_writing_task"  # 쓰기를 시키지 않는 지시문
    CITATION_MISSING = "citation_missing"                # 근거 인용을 안 달았다
    CITATION_STITCHED = "citation_stitched"              # 여러 구절을 이어붙였거나 길이 위반
    CITATION_CROSSES_CUT = "citation_crosses_cut"        # 전처리로 잘라낸 자리를 가로지른다
    CITATION_NOT_FOUND = "citation_not_found"            # 문서에 없는 인용(지어냈다)
    PROMPT_LEAKS_ANSWER = "prompt_leaks_answer"          # 지시문에 답이 들어 있다
    NOT_SCOREABLE = "not_scoreable"                      # 채점 API 형식으로 바뀌지 않는다
    DUPLICATE_ITEM = "duplicate_item"                    # 앞 문항과 사실상 같다


# ---------------------------------------------------------------------------
# 요청
# ---------------------------------------------------------------------------


class GenerateOptions(BaseModel):
    """생성을 조절하는 값들."""

    item_count: int = Field(
        default=3, ge=1, le=10,
        description="만들 문항 수. 폐기가 있으면 이보다 적게 나올 수 있다",
    )
    item_types: list[GeneratedItemType] = Field(
        default_factory=list,
        description="쓸 문항 유형을 좁히고 싶을 때 지정한다. 비우면 다섯 유형 전부 허용",
    )
    item_id_prefix: str = Field(
        default="GEN", max_length=8,
        description="문항 id 앞에 붙일 글자. 기본 세트(WRT-)와 구별하려는 것",
    )
    workplace_name: str = Field(
        default="", max_length=40,
        description="사업장 이름. 지시문에 그대로 쓸 수 있게 넘긴다(예: (주)K-테스트 식품공장)",
    )


class GenerateItemsRequest(BaseModel):
    """백엔드 -> 생성 모듈 입력. (고정 계약)

    무상태다. 문서 텍스트를 요청에 담아 받고 우리는 아무것도 저장하지 않는다.
    파일 저장과 PDF → 텍스트 추출은 파일을 가진 백엔드의 몫이고, 우리는 텍스트만 받는다.
    """

    document_id: str = Field(
        description="백엔드가 발급한 문서 식별자. 우리는 응답에 되돌려주기만 한다",
    )
    document_text: str = Field(
        description="문서 전문 텍스트. PDF 추출 결과를 그대로 보내면 된다",
    )
    document_title: str = Field(default="", description="문서 제목. 프롬프트에 참고로 넣는다")
    mode: Mode = Field(default=Mode.WRITING, description="지금은 writing 만 받는다")
    options: GenerateOptions = Field(default_factory=GenerateOptions)


# ---------------------------------------------------------------------------
# 근거와 문항
# ---------------------------------------------------------------------------


class Citation(BaseModel):
    """생성물 한 조각의 근거.

    채점 쪽 Evidence 와 같은 생각인데, 대조 대상이 '응시자 답안'이 아니라 '안전 문서'다.

    화면에 보여 줄 것은 모델이 적어 낸 quote 가 아니라 **문서에서 실제로 잘라낸
    matched_text** 다. 원문에 없는 글자가 근거로 나가면 안 되기 때문이다.
    """

    quote: str = Field(description="모델이 적어 낸 인용. 나중에 문제를 추적할 때 쓰려고 보관한다")
    matched_text: str = Field(description="문서에서 실제로 잘라낸 구간. 화면에 보여 줄 것은 이쪽이다")
    start: int = Field(description="source_text 기준 시작 글자 위치")
    end: int = Field(description="source_text 기준 끝 글자 위치(파이썬 슬라이스 기준)")


class GeneratedChecklistItem(ChecklistItem):
    """체크리스트 항목 하나 + 그 항목이 나온 문서 구절.

    채점 쪽 ChecklistItem(id, description, weight)을 그대로 물려받고 근거만 얹는다.
    """

    citation: Citation


class GeneratedItem(ItemInfo):
    """생성된 문항 하나.

    채점 쪽 ItemInfo 를 상속한다. 그래서 이 문항을 그대로 `ScoreRequest.item` 에 넣으면
    채점이 돈다(pydantic 은 모르는 필드를 조용히 버리므로 citation·status·document_id 는
    채점에 전달되지 않는다). 이것을 코드로 확인하는 것이 관문 G5 다.
    """

    checklist: list[GeneratedChecklistItem] = Field(
        default_factory=list,
        description="내용·과제 수행 판정 항목. 항목마다 근거 인용이 붙어 있다",
    )
    citation: Citation = Field(description="이 문항 전체의 근거가 된 문서 구절")
    status: Literal["draft"] = Field(
        default="draft",
        description=(
            "언제나 draft(초안)다. 기계 관문은 통과했지만 사람이 아직 보지 않았다는 뜻이며, "
            "시험에 낼 수 있는 상태로 바꾸는 것은 백엔드(관리자 승인)의 몫이다"
        ),
    )
    document_id: str = Field(description="어느 문서에서 나온 문항인지")


# ---------------------------------------------------------------------------
# 폐기 보고와 집계
# ---------------------------------------------------------------------------


class DroppedItem(BaseModel):
    """폐기 보고 한 줄.

    이것은 문항이 아니다. **문항으로 쓸 수 있는 형태로 담지 않는다.**
    지시문 앞부분만 잘라 두는 이유는 관리자가 "무엇이 걸렸나"만 알아보면 되기 때문이다.
    """

    index: int = Field(description="모델 응답에서 몇 번째 문항이었는지(0부터)")
    reason: DropReason = Field(description="폐기 사유 코드. 화면 분기는 이 값으로 한다")
    detail: str = Field(description="사람이 읽는 한 문장")
    rejected_preview: str = Field(default="", description="지시문 앞 40자")
    quote_preview: str = Field(default="", description="문제가 된 인용 앞 40자")


class GenerationCounts(BaseModel):
    """몇 개를 만들어 몇 개가 살아남았는지."""

    requested: int = Field(description="관리자가 요청한 문항 수")
    returned_by_model: int = Field(description="모델이 실제로 내놓은 문항 수")
    kept: int = Field(description="관문을 전부 통과해 응답에 실린 수")
    dropped: int = Field(description="폐기된 수")
    truncated: int = Field(
        default=0,
        description="요청보다 많이 만들어 잘라낸 수. 폐기가 아니므로 폐기율에 섞지 않는다",
    )
    drop_rate: float = Field(
        description="dropped / returned_by_model. 모델이 0개를 냈으면 0.0",
    )


class GenerationMeta(BaseModel):
    """이 생성이 어떤 조건에서 이뤄졌는지 남기는 자리."""

    generation_version: str = GENERATION_VERSION
    prompt_version: str = Field(description="어떤 프롬프트로 만든 문항인지 추적하는 값")
    llm_model: str
    temperature: float = Field(default=0.0, description="0.0 고정")
    document_id: str
    source_text_sha256: str = Field(
        description="정제 텍스트의 해시. 나중에 재검증할 때 같은 문서인지 확인한다",
    )
    document_chars_raw: int = Field(description="받은 문서의 글자 수")
    document_chars_clean: int = Field(description="정제 후 글자 수")
    preprocess_notes: list[str] = Field(
        default_factory=list, description="문서에서 무엇을 지웠는지 사람이 읽는 목록",
    )
    elapsed_ms: float = Field(default=0.0, description="생성 한 번에 걸린 시간(밀리초)")
    requires_human_approval: bool = Field(
        default=True,
        description="언제나 True. AI 초안이므로 사람이 승인하기 전에는 시험에 낼 수 없다",
    )
    wording_reproducible: bool = Field(
        default=False,
        description=(
            "언제나 False. temperature 0 이어도 같은 문서로 두 번 생성하면 "
            "주제와 근거는 같지만 문구가 달라지는 것이 실측됐다. "
            "그래서 생성은 한 번만 하고, 확정은 사람의 승인이 한다. "
            "재현되어야 하는 것은 생성이 아니라 채점이며 채점은 재현성 100%가 실측돼 있다"
        ),
    )


class GenerateItemsResponse(BaseModel):
    """생성 모듈 -> 백엔드 출력. (고정 계약)

    문항 + 폐기 보고 + 집계가 항상 함께 나간다.
    "AI 가 3개 중 1개를 스스로 버렸다"가 화면에 보여야 이 기능이 설명되기 때문이다.
    """

    document_id: str
    status: Literal["draft"] = Field(
        default="draft", description="이 응답에 실린 문항 전체의 상태. 언제나 draft 다",
    )
    mode: Mode
    items: list[GeneratedItem] = Field(
        default_factory=list, description="관문을 전부 통과한 문항. 근거 없는 문항은 여기 없다",
    )
    dropped: list[DroppedItem] = Field(default_factory=list, description="버린 문항의 사유 목록")
    counts: GenerationCounts
    source_text: str = Field(
        description=(
            "정제된 문서 전문. 인용 위치(start/end)의 기준이 되는 글이다. "
            "우리는 무상태라 저장하지 않으므로 백엔드가 draft 와 함께 보관해야 한다"
        ),
    )
    warnings: list[str] = Field(
        default_factory=list, description="폐기는 아니지만 사람이 알아야 할 사항",
    )
    meta: GenerationMeta


# ---------------------------------------------------------------------------
# 재검증 (관리자가 문항을 고쳤을 때)
# ---------------------------------------------------------------------------


class VerifyItemsRequest(BaseModel):
    """백엔드 -> 생성 모듈 입력. 관리자가 손댄 문항을 다시 검증한다. (고정 계약)

    **LLM 을 부르지 않는다.** 관문은 전부 규칙 계산이라 같은 입력에 언제나 같은 판정이 나온다.
    승인 화면에서 관리자가 문구를 고치면 인용 근거가 깨질 수 있는데,
    재검증할 자리가 없으면 "승인자가 손대는 순간 근거 보장이 사라진다"는 말이 맞아 버린다.
    """

    source_text: str = Field(description="/generate-items 가 돌려준 정제 텍스트 그대로")
    source_text_sha256: str = Field(
        default="", description="있으면 대조한다. 다르면 경고를 붙인다(검증 자체는 계속한다)",
    )
    items: list[GeneratedItem] = Field(default_factory=list)


class ItemVerification(BaseModel):
    """문항 하나의 재검증 결과."""

    item_id: str
    ok: bool = Field(description="관문을 전부 통과했는지")
    failures: list[DroppedItem] = Field(
        default_factory=list, description="어느 관문에 왜 걸렸는지",
    )


class VerifyItemsResponse(BaseModel):
    """생성 모듈 -> 백엔드 출력. (고정 계약)

    백엔드 사용 규칙: ok 가 false 인 문항은 시험에 낼 수 있는 상태로 바꾸지 않는다.
    """

    all_ok: bool
    results: list[ItemVerification] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
