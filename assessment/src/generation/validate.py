"""생성된 문항이 시험에 쓸 수 있는 물건인지 확인하는 관문 다섯 개.

**여기서는 LLM 을 한 번도 부르지 않는다.** 전부 글자 세기와 대조로만 판단한다.
채점 쪽 유효성 가드(scoring/validity.py)와 같은 원칙이며, 그 이유는 이렇다.

    생성은 재현되지 않지만 검증은 재현된다.

같은 문서로 두 번 생성하면 문구가 달라진다(실측). 그것은 어쩔 수 없다.
대신 **같은 생성 결과를 두 번 검증하면 언제나 같은 판정이 나온다.**
이 구분이 이 모듈을 믿을 수 있게 만드는 근거다.

관문 다섯 개
    G1  스키마·형식      필드가 있는지, 지시문이 시험 문항의 모양인지
    G2  인용 형식        인용이 '이어진 한 구절'의 모양인지
    G3  인용 대조        그 구절이 문서에 진짜 있는지  ← 이 모듈의 심장
    G4  채점 가드 예행    이 문항으로 시험을 보면 성실한 답안이 무효 처리되지는 않는지
    G5  채점 계약 변환    채점기가 이 문항을 받을 수 있는지

하나라도 걸리면 그 문항은 **통째로** 폐기된다. 부분 통과를 인정하지 않는다.
체크리스트 항목 하나의 근거가 가짜면 그 문항 점수의 일부가 근거 없이 매겨지기 때문이다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..llm.citation import normalize_for_match, verify_citation
from ..scoring.messages import Notice, emit, notice
from ..scoring.schema import ItemInfo
from ..scoring.validity import FLAG_PROMPT_COPY, check_answer_validity, prompt_overlap
from .preprocess import CUT_MARKER
from .schema import (
    Citation,
    DropReason,
    DroppedItem,
    GeneratedChecklistItem,
    GeneratedItem,
    GeneratedItemType,
)

# ---------------------------------------------------------------------------
# 기준값 (전부 첫 기준값이므로 상수로 빼 둔다)
# ---------------------------------------------------------------------------

#: 지시문 길이. 너무 짧으면 상황 설명이 안 되고, 너무 길면 읽다가 지친다.
MIN_PROMPT_CHARS = 30
MAX_PROMPT_CHARS = 200

#: 지시문에 반드시 있어야 할 번호 기호. 써야 할 내용을 세 가지로 나눠 주기 위한 것이다.
REQUIRED_PROMPT_MARKS = ("①", "②", "③")

#: 지시문에서 공백 없이 이어져도 되는 글자 수의 상한.
#: PDF 에서 뽑은 문서는 띄어쓰기가 사라져 있는 곳이 많은데, 그 문구가 지시문에 그대로
#: 새어 나오면 응시자가 읽을 수 없는 문항이 된다. 그것을 이 검사로 막는다.
MAX_UNSPACED_RUN = 12

#: 쓰기를 시키는 말. 이 중 하나는 지시문에 있어야 한다.
#:
#: 왜 '금지어 목록'이 아니라 '통과 조건'인가:
#: 암기 문제를 금지어로 막으려 하면 우회가 너무 쉽다("~의 정의는?" 대신 "~를 설명하면?").
#: 그래서 조건을 뒤집었다. "황화수소의 허용농도는 몇 ppm입니까?"는 이 조건을 통과하지 못한다.
WRITING_TASK_VERBS = (
    "쓰세요", "쓰십시오", "써 주세요",
    "작성하세요", "작성하십시오",
    "알리세요", "알리십시오",
    "보고하세요", "보고하십시오",
    "남기세요", "남기십시오",
    "요청하세요", "요청하십시오",
)

#: 암기 문제로 의심되는 말. **폐기가 아니라 경고로만 쓴다.**
#: 폐기는 검증 실패에만 쓰고, 품질 의심은 사람에게 넘긴다.
#: 이 선을 흐리면 폐기율이라는 수치가 뜻을 잃는다.
MEMORIZATION_MARKERS = ("무엇입니까", "무엇인가", "몇 개입니까", "정의를 쓰", "고르시오")

#: 체크리스트 항목 수와 가중치의 허용 범위.
MIN_CHECKLIST_ITEMS = 2
MAX_CHECKLIST_ITEMS = 5
MIN_CHECKLIST_WEIGHT = 0.5
MAX_CHECKLIST_WEIGHT = 1.5

#: 인용 길이. 짧으면 우연히 겹칠 수 있고, 길면 문서를 통째로 베낀 것이다.
MIN_CITATION_CHARS = 8
MAX_CITATION_CHARS = 60

#: 여러 구절을 이어붙였다는 표시. 모델이 실제로 한 짓이 이것이었다.
STITCH_MARKERS = ("...", "…", "(중략)", "···", "~")

#: G4. 지시문 글자 중 이 비율 이상이 근거 구절에서 그대로 왔으면 '답이 문제에 들어 있다'로 본다.
#: **임시값이다.** 가상 공장 문서로 생성해 보고 오탐 건수를 세어 다시 잡아야 한다.
MAX_PROMPT_QUOTE_OVERLAP = 0.50

#: 문항끼리 이만큼 겹치면 뒤엣것을 같은 문항으로 보고 버린다.
MAX_ITEM_SIMILARITY = 0.80

#: 연속된 공백 없는 글자 덩어리를 찾는 정규식.
_UNSPACED_RUN_RE = re.compile(r"\S+")


# ---------------------------------------------------------------------------
# 결과를 담는 자료구조
# ---------------------------------------------------------------------------


@dataclass
class ItemValidation:
    """문항 하나를 관문에 태운 결과.

    item 과 drop 중 정확히 하나만 채워진다.
    통과했으면 문항이, 걸렸으면 폐기 보고가 들어 있다.
    """

    item: GeneratedItem | None = None
    drop: DroppedItem | None = None
    warnings: list[str] = field(default_factory=list)
    #: 위 warnings 와 같은 내용을 '코드 + 값' 으로 담은 것
    notices: list[Notice] = field(default_factory=list)


def _preview(text: object, limit: int = 40) -> str:
    """긴 글의 앞부분만 잘라 보고용으로 만든다.

    폐기 보고가 문서 전문으로 뒤덮이지 않게 하려는 것이다.
    """
    return str(text or "").strip().replace("\n", " ")[:limit]


def _drop(
    index: int,
    raw: object,
    reason: DropReason,
    detail: "str | Notice",
    quote: object = "",
) -> DroppedItem:
    """폐기 보고 한 줄을 만든다.

    detail 로 Notice 를 주면 한국어 문장과 코드를 둘 다 싣는다.
    글자만 주면 지금까지처럼 문장만 싣는다(코드 없이도 돌아가게 두려는 것).
    """
    # 사전이 아닌 값이 올 수도 있어(모델이 형식을 깨는 경우) 안전하게 꺼낸다
    prompt_text = raw.get("prompt", "") if isinstance(raw, dict) else raw
    made = detail if isinstance(detail, Notice) else None
    return DroppedItem(
        index=index,
        reason=reason,
        detail=made.message if made is not None else str(detail),
        notice=made,
        rejected_preview=_preview(prompt_text),
        quote_preview=_preview(quote),
    )


# ---------------------------------------------------------------------------
# G1 — 스키마·형식 관문
# ---------------------------------------------------------------------------


def longest_unspaced_run(text: str) -> int:
    """공백 없이 가장 길게 이어진 글자가 몇 자인지 센다."""
    # 공백으로 끊어 조각을 만든 뒤 가장 긴 조각의 길이를 돌려준다
    runs = _UNSPACED_RUN_RE.findall(text or "")
    return max((len(run) for run in runs), default=0)


def check_schema_and_format(
    index: int, raw: object, allowed_types: list[GeneratedItemType]
) -> DroppedItem | None:
    """G1) 필드가 갖춰졌는지, 지시문이 시험 문항의 모양인지 본다.

    걸리면 폐기 보고를, 통과하면 None 을 돌려준다.
    """
    # 애초에 사전 모양이 아니면 볼 것이 없다
    if not isinstance(raw, dict):
        return _drop(index, raw, DropReason.SCHEMA_INVALID, notice("DROP_NOT_OBJECT"))

    # --- 필수 필드가 있고 타입이 맞는지 ---
    for key in ("prompt", "item_type", "expected_register", "source_quote"):
        if not isinstance(raw.get(key), str) or not raw.get(key, "").strip():
            return _drop(
                index, raw, DropReason.SCHEMA_INVALID,
                notice("DROP_REQUIRED_FIELD_MISSING", key=key),
            )
    checklist = raw.get("checklist")
    if not isinstance(checklist, list):
        return _drop(index, raw, DropReason.SCHEMA_INVALID, notice("DROP_CHECKLIST_NOT_LIST"))

    # --- 문항 유형이 우리가 정한 다섯 가지 안에 있는지 ---
    allowed_values = {t.value for t in (allowed_types or list(GeneratedItemType))}
    item_type = raw["item_type"].strip()
    if item_type not in allowed_values:
        return _drop(
            index, raw, DropReason.UNKNOWN_ITEM_TYPE,
            notice(
                "DROP_ITEM_TYPE_INVALID",
                itemType=item_type,
                allowed=", ".join(sorted(allowed_values)),
            ),
        )

    # --- 말투 ---
    register = raw["expected_register"].strip()
    if register not in ("formal", "polite"):
        return _drop(
            index, raw, DropReason.SCHEMA_INVALID,
            notice("DROP_REGISTER_INVALID", register=register),
        )

    # --- 체크리스트 개수와 각 항목의 값 ---
    if not (MIN_CHECKLIST_ITEMS <= len(checklist) <= MAX_CHECKLIST_ITEMS):
        return _drop(
            index, raw, DropReason.SCHEMA_INVALID,
            notice(
                "DROP_CHECKLIST_COUNT",
                count=len(checklist),
                min=MIN_CHECKLIST_ITEMS,
                max=MAX_CHECKLIST_ITEMS,
            ),
        )
    for order, entry in enumerate(checklist):
        if not isinstance(entry, dict):
            return _drop(
                index, raw, DropReason.SCHEMA_INVALID,
                notice("DROP_CHECKLIST_ENTRY_NOT_OBJECT", index=order + 1),
            )
        if not isinstance(entry.get("description"), str) or not entry["description"].strip():
            return _drop(
                index, raw, DropReason.SCHEMA_INVALID,
                notice("DROP_CHECKLIST_ENTRY_NO_DESCRIPTION", index=order + 1),
            )
        weight = entry.get("weight")
        if not isinstance(weight, (int, float)) or isinstance(weight, bool):
            return _drop(
                index, raw, DropReason.SCHEMA_INVALID,
                notice("DROP_CHECKLIST_WEIGHT_NOT_NUMBER", index=order + 1),
            )
        # 범위를 벗어난 가중치를 조용히 깎지 않고 폐기한다.
        # weight 는 점수에 직접 들어가는 값이라, 우리가 몰래 고치면
        # 관리자가 승인한 문항과 채점에 쓰인 문항이 달라진다
        if not (MIN_CHECKLIST_WEIGHT <= float(weight) <= MAX_CHECKLIST_WEIGHT):
            return _drop(
                index, raw, DropReason.SCHEMA_INVALID,
                notice(
                    "DROP_CHECKLIST_WEIGHT_OUT_OF_RANGE",
                    index=order + 1,
                    weight=weight,
                    min=MIN_CHECKLIST_WEIGHT,
                    max=MAX_CHECKLIST_WEIGHT,
                ),
            )

    # --- 지시문의 모양 ---
    prompt_text = raw["prompt"].strip()
    if not (MIN_PROMPT_CHARS <= len(prompt_text) <= MAX_PROMPT_CHARS):
        return _drop(
            index, raw, DropReason.PROMPT_FORMAT_INVALID,
            notice(
                "DROP_PROMPT_LENGTH",
                chars=len(prompt_text), min=MIN_PROMPT_CHARS, max=MAX_PROMPT_CHARS,
            ),
        )
    missing_marks = [mark for mark in REQUIRED_PROMPT_MARKS if mark not in prompt_text]
    if missing_marks:
        return _drop(
            index, raw, DropReason.PROMPT_FORMAT_INVALID,
            notice("DROP_PROMPT_NO_NUMBERING", markers="".join(missing_marks)),
        )
    run = longest_unspaced_run(prompt_text)
    if run > MAX_UNSPACED_RUN:
        return _drop(
            index, raw, DropReason.PROMPT_FORMAT_INVALID,
            notice("DROP_PROMPT_RUNON", chars=run, maxChars=MAX_UNSPACED_RUN),
        )

    # --- 쓰기를 시키는 문항인지 ---
    if not any(verb in prompt_text for verb in WRITING_TASK_VERBS):
        return _drop(
            index, raw, DropReason.PROMPT_NOT_A_WRITING_TASK,
            notice("DROP_PROMPT_NO_WRITING_VERB"),
        )

    return None


# ---------------------------------------------------------------------------
# G2 — 인용 형식 관문
# ---------------------------------------------------------------------------


def check_citation_format(quote: object) -> tuple[DropReason, Notice] | None:
    """G2) 인용이 '이어진 한 구절'의 모양인지 본다. 문서와 대조하기 전 단계다.

    프롬프트로 이미 부탁한 규칙을 코드로 한 번 더 확인하는 이유:
    프롬프트는 부탁이고 코드는 강제다. 모델을 바꾸면 부탁은 다시 무시될 수 있다.
    """
    text = str(quote or "").strip()

    # 근거를 아예 안 단 경우
    if not text:
        return DropReason.CITATION_MISSING, notice("DROP_EVIDENCE_EMPTY")

    # 전처리로 잘라낸 자리를 가로지른 인용.
    # 정제 텍스트에는 있지만 실제 문서에는 없는 문장이므로 근거가 될 수 없다
    if CUT_MARKER in text:
        return DropReason.CITATION_CROSSES_CUT, notice("DROP_EVIDENCE_CROSSES_CHUNK")

    # 여러 곳의 구절을 이어붙인 인용
    for marker in STITCH_MARKERS:
        if marker in text:
            return (
                DropReason.CITATION_STITCHED,
                notice("DROP_EVIDENCE_JOINER", marker=marker),
            )

    # 길이 규칙
    if len(text) < MIN_CITATION_CHARS:
        return (
            DropReason.CITATION_STITCHED,
            notice("DROP_EVIDENCE_TOO_SHORT", chars=len(text), minChars=MIN_CITATION_CHARS),
        )
    if len(text) > MAX_CITATION_CHARS:
        return (
            DropReason.CITATION_STITCHED,
            notice("DROP_EVIDENCE_TOO_LONG", chars=len(text), maxChars=MAX_CITATION_CHARS),
        )

    return None


# ---------------------------------------------------------------------------
# G3 — 인용 대조 관문 (이 모듈의 심장)
# ---------------------------------------------------------------------------


def match_citation(source_text: str, quote: str) -> Citation | None:
    """G3) 인용이 문서에 진짜 있는지 대조하고, 있으면 그 위치까지 채워 돌려준다.

    채점에서 쓰던 대조 함수를 그대로 쓴다. 대조 대상만 '응시자 답안'에서 '안전 문서'로 바뀐 것이다.
    띄어쓰기와 문장부호는 무시하고 비교하므로, PDF 에서 띄어쓰기가 사라진 문서도 통과한다.
    """
    check = verify_citation(source_text, quote)
    # 문서에서 찾지 못했으면 지어낸 인용이다
    if not check.ok or check.start is None or check.end is None:
        return None
    # 화면에 보여 줄 것은 모델이 적어 낸 글자가 아니라 문서에서 실제로 잘라낸 구간이다
    return Citation(
        quote=quote,
        matched_text=check.matched_text,
        start=check.start,
        end=check.end,
    )


# ---------------------------------------------------------------------------
# G4 — 채점 가드 예행
# ---------------------------------------------------------------------------


def check_scoring_guards(
    item_prompt: str, matched_text: str
) -> tuple[DropReason, Notice] | None:
    """G4) 이 문항을 채점기의 유효성 가드에 미리 태워 본다.

    왜 이 검사가 필요한가:
    지시문이 문서 문장을 그대로 옮겨 적으면 두 가지가 동시에 망가진다.
      ① 답이 문제 안에 들어 있어 시험이 성립하지 않는다.
      ② 그 표현을 따라 쓴 성실한 응시자가 채점 가드의 '지시문 베끼기'에 걸려
         **무효 0점**을 받는다.
    둘 다 승인 화면에서 사람이 눈으로 알아채기 어렵다. 그래서 숫자로 미리 잰다.
    """
    # 지시문 글자 중 몇 %가 근거 구절에서 그대로 왔는지 잰다
    ratio, _ = prompt_overlap(answer_text=item_prompt, prompt=matched_text)
    if ratio >= MAX_PROMPT_QUOTE_OVERLAP:
        return (
            DropReason.PROMPT_LEAKS_ANSWER,
            notice(
                "DROP_ANSWER_IN_PROMPT",
                ratio=f"{ratio:.0%}",
                threshold=f"{MAX_PROMPT_QUOTE_OVERLAP:.0%}",
            ),
        )

    # 반대 방향도 본다. 문서 문장을 그대로 옮겨 쓴 응시자가 무효 처리되지 않는지,
    # 실제 채점 가드를 그대로 돌려서 확인한다
    report = check_answer_validity(answer_text=matched_text, item_prompt=item_prompt)
    if FLAG_PROMPT_COPY in report.flags:
        return DropReason.PROMPT_LEAKS_ANSWER, notice("DROP_TRIPS_COPY_GUARD")

    return None


# ---------------------------------------------------------------------------
# 문항 하나를 관문 전부에 태우는 진입점
# ---------------------------------------------------------------------------


def validate_item(
    index: int,
    raw: object,
    source_text: str,
    document_id: str,
    allowed_types: list[GeneratedItemType] | None = None,
    provisional_item_id: str = "GEN-000",
) -> ItemValidation:
    """문항 하나를 관문 다섯 개에 차례로 태운다.

    통과하면 문항을, 걸리면 폐기 보고를 담아 돌려준다.
    item_id 는 여기서 임시 값을 쓰고, 통과한 문항끼리 모아 조립할 때 다시 붙인다.
    """
    warnings: list[str] = []
    notices: list[Notice] = []

    # --- G1 스키마·형식 ---
    drop = check_schema_and_format(index, raw, allowed_types or list(GeneratedItemType))
    if drop is not None:
        return ItemValidation(drop=drop)

    # 여기까지 왔으면 raw 가 사전이고 필수 필드가 있는 것이 확인됐다
    assert isinstance(raw, dict)
    prompt_text = raw["prompt"].strip()
    checklist_raw = raw["checklist"]

    # --- G2·G3 인용: 문항 근거부터 ---
    # 확인할 인용을 한 줄로 모은다. (표시용 이름, 인용 글자)
    quotes: list[tuple[Notice, str]] = [
        (notice("DROP_LABEL_ITEM_EVIDENCE"), str(raw["source_quote"]))
    ]
    for order, entry in enumerate(checklist_raw):
        quotes.append((
            notice("DROP_LABEL_CHECKLIST_EVIDENCE", index=entry.get("id") or order + 1),
            str(entry.get("quote", "")),
        ))

    citations: list[Citation] = []
    for label, quote in quotes:
        # G2 형식 검사
        format_problem = check_citation_format(quote)
        if format_problem is not None:
            # 겉 문구(어느 근거인지)와 안쪽 사유를 둘 다 코드로 담는다
            reason, detail = format_problem
            return ItemValidation(drop=_drop(
                index, raw, reason,
                notice(
                    "DROP_EVIDENCE_WRAP",
                    label=label.message, labelNotice=label,
                    detail=detail.message, detailNotice=detail,
                ),
                quote,
            ))
        # G3 문서 대조
        citation = match_citation(source_text, quote)
        if citation is None:
            return ItemValidation(
                drop=_drop(
                    index, raw, DropReason.CITATION_NOT_FOUND,
                    notice(
                        "DROP_EVIDENCE_NOT_FOUND",
                        label=label.message, labelNotice=label,
                    ),
                    quote,
                )
            )
        citations.append(citation)

    # --- 문항 모양으로 조립 (근거는 전부 확인된 상태다) ---
    item_citation = citations[0]
    # description 은 LLM 이 읽을 채점 기준(한국어)이고,
    # description_en 은 응시자 결과 화면에 뜰 안내 문장(영어)이다.
    # 영어를 안 적어 냈어도 문항을 버리지 않는다 — 채점에 쓰이지 않는 표시용 값이라
    # 없다고 해서 점수가 달라지지 않기 때문이다. 빈 문자열로 두고 사람 검수에 맡긴다.
    checklist_items = [
        GeneratedChecklistItem(
            id=str(entry.get("id") or f"c{order + 1}"),
            description=str(entry["description"]).strip(),
            description_en=str(entry.get("description_en") or "").strip(),
            weight=float(entry["weight"]),
            citation=citations[order + 1],
        )
        for order, entry in enumerate(checklist_raw)
    ]

    keywords_raw = raw.get("reference_keywords") or []
    keywords = [str(k).strip() for k in keywords_raw if isinstance(k, (str, int, float)) and str(k).strip()]

    item = GeneratedItem(
        item_id=provisional_item_id,
        prompt=prompt_text,
        item_type=raw["item_type"].strip(),
        checklist=checklist_items,
        expected_register=raw["expected_register"].strip(),
        reference_keywords=keywords,
        citation=item_citation,
        document_id=document_id,
    )

    # --- G4 채점 가드 예행 ---
    guard_problem = check_scoring_guards(item.prompt, item_citation.matched_text)
    if guard_problem is not None:
        reason, detail = guard_problem
        return ItemValidation(drop=_drop(index, raw, reason, detail, item_citation.quote))

    # --- G5 채점 계약 변환 ---
    # 이 한 줄이 "생성한 문항을 채점기가 그대로 받을 수 있다"를 말이 아니라 코드로 증명한다
    try:
        ItemInfo.model_validate(item.model_dump())
    except Exception as exc:  # pragma: no cover - 위 관문을 통과하면 여기 걸릴 일이 거의 없다
        return ItemValidation(
            drop=_drop(
                index, raw, DropReason.NOT_SCOREABLE,
                notice("DROP_CONVERT_FAILED", type=type(exc).__name__),
            )
        )

    # --- 폐기는 아니지만 사람이 봐야 할 것 ---
    # 암기 문제처럼 보이는 말이 섞여 있으면 알려만 준다. 판단은 승인하는 사람이 한다
    for marker in MEMORIZATION_MARKERS:
        if marker in item.prompt:
            emit(
                warnings, notices, "GEN_MEMORIZATION_SUSPECT",
                itemId=provisional_item_id, marker=marker,
            )
            break

    return ItemValidation(item=item, warnings=warnings, notices=notices)


# ---------------------------------------------------------------------------
# 문항끼리 견주는 관문
# ---------------------------------------------------------------------------


def find_duplicate(item: GeneratedItem, earlier: list[GeneratedItem]) -> GeneratedItem | None:
    """앞서 통과한 문항 중에 사실상 같은 문항이 있는지 찾는다.

    지시문이 대부분 겹치면 같은 상황을 두 번 묻는 것이라 시험이 되지 않는다.
    """
    for previous in earlier:
        ratio, _ = prompt_overlap(answer_text=item.prompt, prompt=previous.prompt)
        if ratio >= MAX_ITEM_SIMILARITY:
            return previous
    return None


# ---------------------------------------------------------------------------
# 핵심어 걸러내기
# ---------------------------------------------------------------------------


def filter_reference_keywords(source_text: str, keywords: list[str]) -> tuple[list[str], list[str]]:
    """문서에 실제로 나오는 낱말만 남기고, 없는 낱말은 걸러 낸다.

    왜 걸러 내는가:
    이 값은 LLM 을 못 쓸 때의 대체 채점에 쓰인다.
    지어낸 낱말이 섞여 있으면 그때 채점이 엉뚱하게 돈다.
    낱말이 전부 걸러져도 문항 자체는 살린다(핵심어는 보조 수단이다).

    돌려주는 값은 (남긴 낱말, 걸러 낸 낱말)이다.
    """
    # 문서를 한 번만 비교용 형태로 바꿔 두고 낱말마다 재사용한다
    normalized_source, _ = normalize_for_match(source_text)

    kept: list[str] = []
    removed: list[str] = []
    for keyword in keywords:
        normalized_keyword, _ = normalize_for_match(keyword)
        # 띄어쓰기 차이로 멀쩡한 낱말이 걸러지지 않게 공백을 무시하고 비교한다
        if normalized_keyword and normalized_keyword in normalized_source:
            kept.append(keyword)
        else:
            removed.append(keyword)
    return kept, removed
