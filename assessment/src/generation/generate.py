"""문서 한 편을 받아 문항 초안을 만들어 내는 전체 흐름.

    [0] 요청 검증      말하기 요청인지, 문서 길이가 되는지
    [1] 전처리         머리글·쪽번호를 지우고 잘라낸 자리를 표시한다
    [2] 생성 1회       LLM 을 딱 한 번 부른다
    [3] 문항별 관문     하나라도 걸리면 그 문항만 버리고 나머지는 계속 간다
    [4] 문항 간 관문    사실상 같은 문항을 걸러낸다
    [5] 조립           id 를 다시 붙이고 집계와 경고를 만든다

**재시도 루프를 만들지 않는다.** 폐기가 생겨 문항이 모자라도 자동으로 다시 부르지 않는다.
자동 재시도는 ① 폐기율 수치를 우리 손으로 지우고 ② 관리자가 실제로 몇 문항을 받았는지
보이지 않게 만든다. 모자라면 관리자가 문항 수를 올려 다시 요청한다.

**인용 검증을 끄는 옵션을 만들지 않는다.** 옵션이 되는 순간 그 제약은 제약이 아니라
기본값이 되고, 급할 때 꺼진다. 근거 없는 문항은 응답에 실리지 않는다.
"""

from __future__ import annotations

import time
from collections import Counter

from ..scoring.schema import Mode
from .llm import client_for_generation
from .preprocess import preprocess_document, sha256_of
from .prompt import PROMPT_VERSION, RESPONSE_SCHEMA, SYSTEM_INSTRUCTION, build_user_prompt
from .schema import (
    GENERATION_VERSION,
    MAX_DOCUMENT_CHARS,
    MIN_DOCUMENT_CHARS,
    DroppedItem,
    DropReason,
    GeneratedItem,
    GeneratedItemType,
    GenerateItemsRequest,
    GenerateItemsResponse,
    GenerationCounts,
    GenerationMeta,
    ItemVerification,
    VerifyItemsRequest,
    VerifyItemsResponse,
)
from .validate import (
    ItemValidation,
    filter_reference_keywords,
    find_duplicate,
    validate_item,
)

#: 한 문항 유형이 이만큼 이상 몰리면 경고를 띄운다(폐기는 아니다).
#: 유형 편중은 품질 문제이지 검증 실패가 아니므로 사람이 판단할 몫이다.
TYPE_CONCENTRATION_WARN = 3


class GenerationRequestError(ValueError):
    """요청 자체가 문항을 만들 수 없는 상태일 때 올리는 예외.

    이 예외가 나면 문항을 하나도 만들지 않고 즉시 막는다(HTTP 400).
    메시지는 그대로 관리자에게 보이므로 사람이 읽는 한 문장만 담는다.
    """


def _model_name(client: object) -> str:
    """어떤 모델로 만들었는지 이름을 꺼낸다. 가짜 클라이언트면 이름이 없을 수 있다."""
    return str(getattr(client, "model_name", "unknown"))


def _temperature(client: object) -> float:
    """호출에 쓴 temperature. 우리 클라이언트는 언제나 0 이다."""
    config = getattr(client, "config", None)
    return float(getattr(config, "temperature", 0.0))


def generate_items(
    request: GenerateItemsRequest, client: object | None = None
) -> GenerateItemsResponse:
    """안전 문서에서 쓰기 문항 초안을 만든다.

    client 를 넘기면 그것을 쓴다(테스트가 가짜 클라이언트를 넣는 자리).
    안 넘기면 생성 전용 설정으로 만든 진짜 클라이언트를 쓴다.
    """
    started = time.perf_counter()
    options = request.options

    # ---------------- [0] 요청 검증 ----------------
    # 말하기 문항 생성은 아직 만들지 않았다. 조용히 쓰기로 바꿔 처리하면
    # 관리자는 말하기 문항을 받았다고 생각하게 되므로 분명히 막는다
    if request.mode != Mode.WRITING:
        raise GenerationRequestError("지금은 쓰기 문항만 만든다. 말하기 문항 생성은 아직 없다.")

    # ---------------- [1] 전처리 ----------------
    pre = preprocess_document(request.document_text)

    # 길이는 정제한 뒤에 잰다. 머리글만 잔뜩 있는 문서가 길이만 채우는 일을 막기 위해서다.
    # 길이를 넘겼을 때 **조용히 잘라내지 않는다** — 자르면 관리자가 보낸 문서와
    # 문항이 나온 문서가 달라지는데 응답만 보고는 알 수 없다
    if pre.clean_chars < MIN_DOCUMENT_CHARS:
        raise GenerationRequestError(
            f"문서가 {pre.clean_chars}자로 너무 짧아 문항을 만들 수 없다"
            f"(최소 {MIN_DOCUMENT_CHARS}자)."
        )
    if pre.clean_chars > MAX_DOCUMENT_CHARS:
        raise GenerationRequestError(
            f"문서가 {pre.clean_chars}자로 너무 길다(최대 {MAX_DOCUMENT_CHARS}자). "
            "장·절 단위로 나눠서 보내야 한다."
        )

    source_text = pre.text

    # ---------------- [2] 생성 1회 ----------------
    # 여기서 LLM 을 못 쓰면 대체 경로가 없다. 규칙만으로 문항을 지어낼 수는 없기 때문에
    # 예외를 그대로 위로 올려 보내고, 창구가 503 으로 바꿔 알린다
    llm = client_for_generation(client, options.item_count)
    user_prompt = build_user_prompt(
        document=source_text,
        item_count=options.item_count,
        allowed_types=options.item_types,
        document_title=request.document_title,
        workplace_name=options.workplace_name,
    )
    payload = llm.generate_json(
        user_prompt,
        system_instruction=SYSTEM_INSTRUCTION,
        response_schema=RESPONSE_SCHEMA,
    )

    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        raw_items = []

    # ---------------- [3] 문항별 관문 ----------------
    allowed_types = list(options.item_types) if options.item_types else list(GeneratedItemType)
    doc6 = pre.sha256[:6].upper()

    passed: list[tuple[str, ItemValidation]] = []   # (임시 id, 통과한 문항)
    dropped: list[DroppedItem] = []
    warnings: list[str] = []

    for index, raw in enumerate(raw_items):
        provisional_id = f"{options.item_id_prefix}-{doc6}-임시{index + 1}"
        result = validate_item(
            index=index,
            raw=raw,
            source_text=source_text,
            document_id=request.document_id,
            allowed_types=allowed_types,
            provisional_item_id=provisional_id,
        )
        if result.drop is not None:
            dropped.append(result.drop)
            continue
        passed.append((provisional_id, result))

    # ---------------- [4] 문항 간 관문 ----------------
    unique: list[tuple[str, ItemValidation]] = []
    for provisional_id, result in passed:
        assert result.item is not None
        twin = find_duplicate(result.item, [r.item for _, r in unique if r.item])
        if twin is not None:
            dropped.append(
                DroppedItem(
                    index=len(unique) + len(dropped),
                    reason=DropReason.DUPLICATE_ITEM,
                    detail="앞 문항과 지시문이 대부분 겹쳐 사실상 같은 문항이다.",
                    rejected_preview=result.item.prompt[:40],
                    quote_preview=twin.prompt[:40],
                )
            )
            continue
        unique.append((provisional_id, result))

    # ---------------- [5] 조립 ----------------
    # 요청한 수보다 많이 통과했으면 앞에서부터 잘라 낸다.
    # **잘라 낸 것은 폐기가 아니다.** 폐기율 수치에 섞지 않는다
    truncated = max(0, len(unique) - options.item_count)
    selected = unique[: options.item_count]

    items: list[GeneratedItem] = []
    for order, (provisional_id, result) in enumerate(selected, start=1):
        assert result.item is not None
        # 문항 id 를 다시 붙인다. 문서가 같으면 가운데 글자가 같아 추적하기 쉽고,
        # 문서가 다르면 서로 겹치지 않는다(예: GEN-3F9A2C-001)
        final_id = f"{options.item_id_prefix}-{doc6}-{order:03d}"

        # 핵심어 중 문서에 없는 낱말을 걸러 낸다. 문항 자체는 살린다
        kept_keywords, removed_keywords = filter_reference_keywords(
            source_text, result.item.reference_keywords
        )
        if removed_keywords:
            warnings.append(
                f"[{final_id}] 문서에 없는 핵심어 {', '.join(removed_keywords)} 를 뺐다"
                "(LLM 을 못 쓸 때의 대체 채점이 엉뚱하게 돌지 않게 하려는 것)."
            )

        items.append(result.item.model_copy(update={
            "item_id": final_id,
            "reference_keywords": kept_keywords,
        }))

        # 관문에서 남긴 경고의 임시 id 를 최종 id 로 바꿔 담는다
        warnings.extend(note.replace(provisional_id, final_id) for note in result.warnings)

    returned_by_model = len(raw_items)
    counts = GenerationCounts(
        requested=options.item_count,
        returned_by_model=returned_by_model,
        kept=len(items),
        dropped=len(dropped),
        truncated=truncated,
        # 폐기율은 '모델이 낸 것 중 몇 개를 버렸나'다. 잘라 낸 것은 여기 들어가지 않는다
        drop_rate=round(len(dropped) / returned_by_model, 4) if returned_by_model else 0.0,
    )

    # --- 사람이 알아야 할 것들 ---
    if returned_by_model == 0:
        warnings.append("모델이 문항을 하나도 만들지 않았다. 문서 내용을 확인하고 다시 시도해야 한다.")
    elif not items:
        warnings.append(
            f"만들어진 문항 {returned_by_model}개가 모두 검증 관문에서 폐기됐다. "
            "근거를 댈 수 없는 문항은 내보내지 않는다. 문서를 바꿔 다시 시도해야 한다."
        )
    elif len(items) < options.item_count:
        warnings.append(
            f"요청한 {options.item_count}개 중 {len(items)}개만 관문을 통과했다. "
            "더 필요하면 문항 수를 늘려 다시 요청해야 한다."
        )

    # 유형이 한쪽으로 몰리면 알려만 준다(폐기 아님)
    for item_type, count in Counter(item.item_type for item in items).items():
        if count >= TYPE_CONCENTRATION_WARN:
            warnings.append(
                f"'{item_type}' 유형 문항이 {count}개로 몰려 있다. "
                "시험이 한 가지 상황만 묻게 되지 않는지 확인해야 한다."
            )

    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)

    return GenerateItemsResponse(
        document_id=request.document_id,
        mode=request.mode,
        items=items,
        dropped=dropped,
        counts=counts,
        source_text=source_text,
        warnings=warnings,
        meta=GenerationMeta(
            generation_version=GENERATION_VERSION,
            prompt_version=PROMPT_VERSION,
            llm_model=_model_name(llm),
            temperature=_temperature(llm),
            document_id=request.document_id,
            source_text_sha256=pre.sha256,
            document_chars_raw=pre.raw_chars,
            document_chars_clean=pre.clean_chars,
            preprocess_notes=pre.notes,
            elapsed_ms=elapsed_ms,
        ),
    )


# ---------------------------------------------------------------------------
# 재검증 — 관리자가 고친 문항을 다시 관문에 태운다
# ---------------------------------------------------------------------------


def _item_to_raw(item: GeneratedItem) -> dict:
    """이미 만들어진 문항을 '모델이 방금 내놓은 모양'으로 되돌린다.

    같은 검증 함수를 쓰기 위해서다. 검증 규칙이 생성 때와 재검증 때 달라지면
    "승인 화면을 지난 문항은 검증된 문항"이라는 말이 성립하지 않는다.
    """
    return {
        "item_type": item.item_type,
        "prompt": item.prompt,
        "expected_register": item.expected_register,
        "reference_keywords": list(item.reference_keywords),
        # 근거는 모델이 적어 낸 글자를 그대로 다시 대조한다
        "source_quote": item.citation.quote or item.citation.matched_text,
        "checklist": [
            {
                "id": entry.id,
                "description": entry.description,
                "weight": entry.weight,
                "quote": entry.citation.quote or entry.citation.matched_text,
            }
            for entry in item.checklist
        ],
    }


def verify_items(request: VerifyItemsRequest) -> VerifyItemsResponse:
    """관리자가 손댄 문항을 같은 관문에 다시 태운다.

    **LLM 을 부르지 않는다.** 그래서 같은 입력에는 언제나 같은 판정이 나오고,
    승인 화면에서 몇 번을 눌러도 결과가 흔들리지 않는다.
    """
    warnings: list[str] = []

    # 보내온 문서가 그때 그 문서가 맞는지 지문을 대조한다.
    # 달라도 검증은 계속한다 — 우리가 할 수 있는 말은 "인용이 이 글에 있다/없다"까지이고,
    # 어느 문서가 맞는지는 문서를 보관한 백엔드가 판단할 일이다
    actual_sha = sha256_of(request.source_text)
    if request.source_text_sha256 and request.source_text_sha256 != actual_sha:
        warnings.append(
            "보내온 문서가 문항을 만들 때 쓴 문서와 다르다. "
            "인용 위치가 어긋날 수 있으니 문서를 다시 확인해야 한다."
        )

    results: list[ItemVerification] = []
    verified_ok: list[GeneratedItem] = []

    for index, item in enumerate(request.items):
        failures: list[DroppedItem] = []

        # 생성 때와 똑같은 관문에 태운다
        outcome = validate_item(
            index=index,
            raw=_item_to_raw(item),
            source_text=request.source_text,
            document_id=item.document_id,
            allowed_types=list(GeneratedItemType),
            provisional_item_id=item.item_id,
        )
        if outcome.drop is not None:
            failures.append(outcome.drop)
        elif outcome.item is not None:
            # 통과한 문항끼리 서로 같아지지는 않았는지도 본다
            twin = find_duplicate(outcome.item, verified_ok)
            if twin is not None:
                failures.append(
                    DroppedItem(
                        index=index,
                        reason=DropReason.DUPLICATE_ITEM,
                        detail=f"'{twin.item_id}' 문항과 지시문이 대부분 겹쳐 사실상 같은 문항이 됐다.",
                        rejected_preview=outcome.item.prompt[:40],
                        quote_preview=twin.prompt[:40],
                    )
                )
            else:
                verified_ok.append(outcome.item)

        results.append(
            ItemVerification(item_id=item.item_id, ok=not failures, failures=failures)
        )
        warnings.extend(outcome.warnings)

    return VerifyItemsResponse(
        all_ok=all(result.ok for result in results),
        results=results,
        warnings=warnings,
    )
