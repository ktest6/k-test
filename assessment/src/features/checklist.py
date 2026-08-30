"""문항이 요구한 내용을 답안이 담았는지 항목별로 0/1 판정하는 모듈.

'내용 및 과제 수행' 영역의 핵심이다.
예를 들어 "지각한 이유를 설명하고 사과하라"는 문항이면 체크리스트는
  1) 지각한 이유를 말했는가
  2) 사과를 했는가
가 되고, 각각 충족(1) / 미충족(0) 으로 판정한다.

LLM은 여기서도 점수를 매기지 않는다. 0/1 판정과 그 근거 인용만 한다.
그리고 **근거 인용이 원문에 없으면 충족으로 인정하지 않는다.**
"근거는 못 대지만 아마 했을 것"은 채점 결과가 될 수 없다.

항목 하나가 예외다. "세 요소를 모두 포함했는가" 같은 **[보너스] 항목**은 근거가 답안
여기저기에 흩어져 있어서, LLM 이 충족이라고 판정하면서 인용을 조각조각 이어 붙여 낸다.
그렇게 만든 인용은 원문에 그대로 있지 않으니 위 검증에서 폐기되고, 실제로는 다 말한
답안이 억울하게 0점이 됐다(SPK-105 c10 실측). 그래서 그런 항목은 아예 LLM 에게 묻지 않고,
문항에 적어 둔 조건(`ChecklistItem.requires`)대로 **앞 항목들의 판정 결과를 코드가
조합해서** 계산한다. 근거는 인용이 아니라 "어느 항목이 충족돼서 이렇게 됐는지"가 된다.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

from ..llm.citation import filter_by_citation, verify_citation
from ..llm.client import GeminiClient, LLMUnavailable, answered_model
from ..scoring.messages import Notice, emit, notice, notice_or_free_text
from ..scoring.schema import (
    ChecklistItem,
    ChecklistResult,
    Evidence,
    FeatureSource,
    ItemInfo,
)

logger = logging.getLogger(__name__)

# 값이 끼지 않는 고정 근거 문구는 한 번만 만들어 두고 돌려 쓴다.
# 같은 문장을 자리마다 다시 적으면 한쪽만 고쳐져서 문구가 어긋나기 때문이다.
_NO_VERDICT_COMMENT = notice("CHECKLIST_COMMENT_NO_VERDICT")
_NO_VERDICT_NOTE = notice("CHECKLIST_NOTE_NO_VERDICT")
_UNMET_FALLBACK = notice("CHECKLIST_COMMENT_UNMET_FALLBACK")
_MET_FALLBACK = notice("CHECKLIST_COMMENT_MET_FALLBACK")
_CITATION_DISCARDED_NOTE = notice("CHECKLIST_NOTE_CITATION_DISCARDED")
_FALLBACK_NOTE = notice("CHECKLIST_NOTE_FALLBACK")
_FALLBACK_UNMET = notice("CHECKLIST_COMMENT_FALLBACK_UNMET")

# ※ 임시 ※ 아래 규칙 계산용 문구들은 아직 messages.py 의 코드 목록(카탈로그)에 등록돼 있지
# 않다. messages.py 를 다른 작업이 잡고 있어서 코드를 못 넣었기 때문이다. 그동안은
# "번역할 고정 문구가 없는 자유문"(LLM_FREE_TEXT)으로 내보내 백엔드가 문장을 그대로
# 쓰게 한다. 그 파일이 풀리면 CHECKLIST_RULE_* 코드를 만들어 바꿔 달아야 한다.
_RULE_NOTE_TEXT = (
    "이 항목은 LLM 판정이 아니라 앞 항목들의 결과로 코드가 계산했다(인용 검증 대상 아님)."
)
_RULE_FALLBACK_TEXT = (
    "앞 항목 판정이 대체 경로(핵심어 일치)라 이 보너스 항목은 계산하지 않고 미충족으로 둔다."
)


def _group_label(group: list[str]) -> str:
    """조건 한 묶음을 사람이 읽는 말로 바꾼다.

    ["c5"] -> "c5" / ["c5", "c6"] -> "(c5 또는 c6)"
    """
    # 하나뿐이면 괄호를 씌우지 않는 편이 근거 문장이 짧고 읽기 쉽다
    if len(group) == 1:
        return group[0]
    return "(" + " 또는 ".join(group) + ")"


def evaluate_requires(
    requires: list[list[str]],
    met_by_id: dict[str, int],
    known_ids: set[str],
) -> tuple[int, list[str], list[str]]:
    """`requires` 조건을 앞 항목들의 판정 결과로 계산한다.

    바깥 리스트는 '그리고(AND)', 안쪽 리스트는 '또는(OR)' 이다.
    예: [["c4"], ["c3"], ["c5", "c6"]] = c4 충족 그리고 c3 충족 그리고 (c5 또는 c6) 충족.

    돌려주는 것 셋:
      1) 충족이면 1, 아니면 0
      2) 근거로 적을 설명 조각들 (예: ["c4 충족", "(c5 또는 c6) 미충족"])
      3) 쓸 수 없는 id 와 그 이유 (문항에 없는 id, 아직 판정 전인 id)
    """
    parts: list[str] = []
    unusable: list[str] = []
    all_ok = True

    for group in requires:
        # 안쪽 묶음은 '또는' 이라서 하나라도 충족이면 이 묶음은 통과다
        group_ok = False
        for ref in group:
            if ref not in known_ids:
                # 문항에 아예 없는 항목을 가리키고 있다 — 문항 파일이 잘못된 것이다
                unusable.append(f"{ref}(문항에 없는 항목)")
                continue
            if ref not in met_by_id:
                # 있긴 한데 아직 판정 전이다. 보너스보다 뒤에 있는 항목을 가리킨 경우다
                unusable.append(f"{ref}(아직 판정 전인 항목)")
                continue
            if met_by_id[ref] == 1:
                group_ok = True

        parts.append(f"{_group_label(group)} {'충족' if group_ok else '미충족'}")
        if not group_ok:
            all_ok = False

    # 조건이 비어 있으면 계산할 근거가 없다. '조건이 없으니 통과'로 두면
    # 실수로 requires 를 빈 채 넣은 문항이 공짜 점수를 주게 된다
    if not requires:
        return 0, ["조건이 비어 있음"], unusable

    return (1 if all_ok else 0), parts, unusable


def _result_from_requires(
    item: ChecklistItem,
    met_by_id: dict[str, int],
    known_ids: set[str],
) -> tuple[ChecklistResult, list[str], list[Notice]]:
    """'앞 항목들을 다 했는가'를 묻는 보너스 항목 하나를 코드가 계산해 결과로 만든다."""
    warnings: list[str] = []
    notices: list[Notice] = []

    met, parts, unusable = evaluate_requires(item.requires, met_by_id, known_ids)

    # 쓸 수 없는 id 를 가리키고 있으면 조용히 미충족으로 넘기지 않고 소리를 낸다.
    # 문항 파일의 오타는 조용히 두면 '왜 항상 0점이지'로만 나타나기 때문이다
    if unusable:
        text = (
            f"체크리스트 {item.id} 의 requires 가 쓸 수 없는 항목을 가리킨다: "
            + ", ".join(unusable)
        )
        logger.warning(text)
        made = notice_or_free_text(None, text)
        warnings.append(made.message)
        notices.append(made)

    # 근거 문장. 인용이 아니라 '무엇이 충족돼서 이렇게 됐는지'를 적는다
    comment = "규칙 계산 — " + " · ".join(parts) + (" → 충족" if met else " → 미충족")

    # 계산에 실제로 쓴 항목들의 값만 남긴다(검산용). 전체를 담으면 근거가 지저분해진다
    referenced = {
        ref: met_by_id.get(ref) for group in item.requires for ref in group
    }

    result = ChecklistResult(
        id=item.id,
        description=item.description,
        description_en=item.description_en,
        met=met,
        weight=item.weight,
        source=FeatureSource.RULE,
        evidence=[
            Evidence(
                source=FeatureSource.RULE,
                comment=comment,
                notice=notice_or_free_text(None, comment),
                detail={"requires": item.requires, "referenced_met": referenced},
            )
        ],
        note=_RULE_NOTE_TEXT,
        notice=notice_or_free_text(None, _RULE_NOTE_TEXT),
    )
    return result, warnings, notices


def llm_judged_items(checklist: list[ChecklistItem]) -> list[ChecklistItem]:
    """LLM 에게 물어볼 항목만 골라낸다.

    `requires` 가 적힌 항목은 코드가 계산하므로 프롬프트에 넣지 않는다.
    넣어 두면 LLM 이 굳이 인용을 지어내다가 폐기당하는, 고치려던 그 문제가 그대로 남는다.
    """
    return [c for c in checklist if not c.requires]


SYSTEM_INSTRUCTION = """\
당신은 한국어 시험 답안이 문항의 요구 사항을 충족했는지 확인하는 판정 도구다.
점수를 매기지 않는다. 각 항목에 대해 충족(1) / 미충족(0) 만 판정한다.

반드시 지킬 규칙:
1. 충족(1)이라고 판정하면 quote 필드에 답안 원문의 해당 부분을 그대로 복사해 넣는다.
   한 글자도 바꾸지 않는다. 원문에 없는 문장을 지어내면 그 판정은 폐기되어 미충족 처리된다.
2. 답안에 근거가 없으면 주저 없이 0으로 판정한다. 너그럽게 봐주지 않는다.
3. 문법이 틀렸어도 내용을 전달했으면 충족으로 본다. 문법은 다른 곳에서 따로 채점한다.
4. 반드시 지정된 JSON 형식으로만 답한다.
"""

USER_PROMPT_TEMPLATE = """\
[문항 지시문]
{item_prompt}
{scene_block}
[답안 원문]
```
{answer_text}
```

[확인할 항목]
{checklist_text}

다음 JSON 형식으로만 답하라. 항목은 하나도 빠뜨리지 마라.
{{
  "results": [
    {{
      "id": "항목 id",
      "met": 0 또는 1,
      "quote": "충족이라면 답안 원문에서 그대로 복사한 근거 부분, 미충족이면 빈 문자열",
      "reason": "그렇게 판정한 이유 한 문장"
    }}
  ]
}}
"""


# 응답 구조를 Gemini 쪽에서 강제하기 위한 형식표.
# 이것을 안 붙였더니 실제 호출에서 모델이 닫는 괄호를 하나 더 붙여 보내
# 응답 해석이 통째로 실패하는 일이 있었다(2026-07-26 실측).
# 형식이 깨지면 내용·과제 수행이 핵심어 일치라는 엉성한 대체 판정으로 넘어가므로 못 박아 둔다.
RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    # 0 또는 1만 받는다. 모델이 true/false 로 답하는 것을 막는다
                    "met": {"type": "integer"},
                    "quote": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["id", "met", "quote", "reason"],
            },
        },
    },
    "required": ["results"],
}


@dataclass
class ChecklistJudgeResult:
    """체크리스트 판정 결과 묶음."""

    results: list[ChecklistResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    #: 위 warnings 와 같은 내용을 '코드 + 값' 으로 담은 것. 백엔드가 영어로 바꿔 쓴다
    notices: list[Notice] = field(default_factory=list)
    dropped_citations: int = 0
    llm_used: bool = False
    #: 이 판정에 **실제로 답한 모델** 이름. 부르려던 모델과 다를 수 있다
    #: (원 모델이 붐벼서 못 받으면 대체 모델로 갈아타기 때문이다). 호출을 안 했으면 None
    llm_model_used: str | None = None
    #: 대체 모델로 갈아탄 경우 원래 부르려던 모델 이름. 안 갈아탔으면 None
    llm_fallback_from: str | None = None


def build_prompt(answer_text: str, item: ItemInfo) -> str:
    """LLM에 보낼 지시문을 만든다."""
    # 항목마다 id 를 붙여서 보낸다. 그래야 돌아온 판정을 어느 항목의 것인지 짝지을 수 있다.
    # requires 가 적힌 [보너스] 항목은 여기서 뺀다 — 그건 코드가 계산한다
    checklist_text = "\n".join(
        f"- id={c.id}: {c.description}" for c in llm_judged_items(item.checklist)
    )

    # 그림을 보고 답하는 문항이면 그림에 무엇이 있는지도 알려 준다.
    # 채점하는 LLM 은 그림을 보지 못해서, 이것이 없으면
    # '화살표를 말했는가' 같은 항목을 판정할 근거 자체가 없다.
    # 그림 설명이 없는 문항(쓰기 등)은 예전과 똑같은 지시문이 만들어진다
    scene = (item.scene_description or "").strip()
    scene_block = f"\n[제시된 이미지 내용]\n{scene}\n" if scene else ""

    return USER_PROMPT_TEMPLATE.format(
        item_prompt=item.prompt or "(지시문 없음)",
        scene_block=scene_block,
        answer_text=answer_text,
        checklist_text=checklist_text or "(항목 없음)",
    )


def results_from_llm_payload(
    answer_text: str,
    checklist: list[ChecklistItem],
    payload: dict,
) -> tuple[list[ChecklistResult], list[str], list[Notice], int]:
    """LLM이 준 판정 결과를 검증해서 최종 판정으로 바꾼다.

    LLM 호출과 분리해 두어서, 가짜 응답을 넣어 폐기 동작을 검증할 수 있다.
    핵심 규칙: 충족(1)인데 근거 인용이 원문에 없으면 0으로 내린다.

    `requires` 가 적힌 [보너스] 항목은 LLM 에게 묻지 않았으므로 여기서 코드가 계산한다.
    문항에 적힌 차례대로 돌면서 앞 항목 판정을 쌓아 가기 때문에, 보너스는 자기보다
    **앞에 있는** 항목만 가리킬 수 있다(뒤를 가리키면 아래에서 경고가 뜬다).
    """
    warnings: list[str] = []
    notices: list[Notice] = []
    dropped = 0

    # 보너스 계산이 참조할 값들. 문항에 있는 항목 id 전체와, 지금까지 나온 0/1 판정이다
    known_ids = {c.id for c in checklist}
    met_by_id: dict[str, int] = {}

    # 형식이 깨졌으면 빈 목록으로 두고 아래에서 전 항목을 미충족 처리한다
    raw_results = payload.get("results")
    if not isinstance(raw_results, list):
        raw_results = []
        emit(warnings, notices, "CHECKLIST_NO_RESULTS_LIST")

    # LLM이 항목 순서를 바꿔 보낼 수 있으므로 id로 찾아 쓸 수 있게 정리해 둔다
    by_id = {str(r.get("id")): r for r in raw_results if isinstance(r, dict)}

    # 문항이 정한 체크리스트를 기준으로 돈다.
    # LLM이 보낸 것을 기준으로 돌면 모델이 빠뜨린 항목이 결과에서 사라져 버린다
    final: list[ChecklistResult] = []

    def remember(result: ChecklistResult) -> None:
        """판정 하나를 결과 목록에 넣고, 뒤에 오는 보너스가 참조할 수 있게 값을 기억한다."""
        final.append(result)
        met_by_id[result.id] = result.met

    for item in checklist:
        # requires 가 있는 항목은 LLM 에게 묻지 않았다. 앞 항목 결과로 여기서 계산한다
        if item.requires:
            rule_result, rule_warnings, rule_notices = _result_from_requires(
                item, met_by_id, known_ids
            )
            remember(rule_result)
            warnings.extend(rule_warnings)
            notices.extend(rule_notices)
            continue

        raw = by_id.get(item.id)

        # LLM이 아예 판정하지 않은 항목은 '모르니까 충족'이 아니라 미충족으로 본다
        if raw is None:
            remember(
                ChecklistResult(
                    id=item.id,
                    description=item.description,
                    description_en=item.description_en,
                    met=0,
                    weight=item.weight,
                    evidence=[
                        Evidence(
                            source=FeatureSource.LLM,
                            comment=_NO_VERDICT_COMMENT.message,
                            notice=_NO_VERDICT_COMMENT,
                        )
                    ],
                    note=_NO_VERDICT_NOTE.message,
                    notice=_NO_VERDICT_NOTE,
                )
            )
            emit(warnings, notices, "CHECKLIST_ITEM_MISSING_VERDICT", itemId=item.id)
            continue

        # 모델이 1, "1", true 등 여러 모양으로 답할 수 있어 넉넉하게 받아 준다
        met = 1 if str(raw.get("met", "0")).strip() in ("1", "true", "True") else 0
        reason = str(raw.get("reason", "")).strip()
        quote = str(raw.get("quote", "")).strip()

        # 미충족 판정은 인용이 필요 없다. 없는 것을 인용할 수는 없기 때문이다
        if met == 0:
            remember(
                ChecklistResult(
                    id=item.id,
                    description=item.description,
                    description_en=item.description_en,
                    met=0,
                    weight=item.weight,
                    evidence=[
                        Evidence(
                            source=FeatureSource.LLM,
                            comment=reason or _UNMET_FALLBACK.message,
                            # LLM 이 직접 쓴 이유에는 정해진 문구가 없다.
                            # 그래서 '번역할 고정 문장이 없는 자유문' 이라는 표시를 붙인다
                            notice=(
                                notice_or_free_text(None, reason)
                                if reason
                                else _UNMET_FALLBACK
                            ),
                        )
                    ],
                )
            )
            continue

        # 여기부터가 이 함수의 핵심이다.
        # 충족(1) 판정은 반드시 원문 인용으로 뒷받침되어야 하고,
        # 인용이 원문에 없으면 그 판정은 지어낸 것이므로 0으로 되돌린다
        check = verify_citation(answer_text, quote)
        if not check.ok:
            dropped += 1
            emit(
                warnings,
                notices,
                "CHECKLIST_CITATION_DISCARDED",
                itemId=item.id,
                reason=check.reason,
                reasonNotice=check.notice,
            )
            discarded = notice(
                "CHECKLIST_COMMENT_CITATION_DISCARDED",
                reason=check.reason,
                reasonNotice=check.notice,
            )
            remember(
                ChecklistResult(
                    id=item.id,
                    description=item.description,
                    description_en=item.description_en,
                    met=0,
                    weight=item.weight,
                    evidence=[
                        Evidence(
                            source=FeatureSource.LLM,
                            comment=discarded.message,
                            notice=discarded,
                            detail={"discarded_quote": quote},
                        )
                    ],
                    note=_CITATION_DISCARDED_NOTE.message,
                    notice=_CITATION_DISCARDED_NOTE,
                )
            )
            continue

        # 검증을 통과한 충족 판정. 근거에는 LLM이 적어 준 문자열이 아니라
        # 원문에서 실제로 잘라낸 구간과 그 위치를 담는다
        remember(
            ChecklistResult(
                id=item.id,
                description=item.description,
                description_en=item.description_en,
                met=1,
                weight=item.weight,
                evidence=[
                    Evidence(
                        source=FeatureSource.LLM,
                        quote=check.matched_text,
                        start=check.start,
                        end=check.end,
                        comment=reason or _MET_FALLBACK.message,
                        # LLM 이 직접 쓴 이유에는 정해진 문구가 없다(자유문 표시를 붙인다)
                        notice=(
                            notice_or_free_text(None, reason) if reason else _MET_FALLBACK
                        ),
                    )
                ],
            )
        )

    return final, warnings, notices, dropped


def _keyword_fallback(
    answer_text: str,
    item: ItemInfo,
) -> tuple[list[ChecklistResult], list[str], list[Notice]]:
    """※ 임시 대체 경로 ※ LLM을 못 쓸 때 핵심어가 답안에 있는지로만 0/1을 매긴다.

    이것은 진짜 내용 판정이 아니다. 말만 겹치고 뜻이 달라도 충족으로 잡히고,
    다른 표현으로 잘 말해도 미충족으로 잡힌다.
    운영 채점에 쓰면 안 되고, 키가 들어오면 반드시 LLM 판정으로 돌아가야 한다.
    """
    warnings: list[str] = []
    notices: list[Notice] = []
    emit(warnings, notices, "CHECKLIST_FALLBACK_USED")
    # 응시자가 띄어쓰기를 다르게 했어도 찾을 수 있도록 공백을 뗀 형태로 비교한다
    normalized_answer = re.sub(r"\s+", "", answer_text)

    results: list[ChecklistResult] = []
    for c in item.checklist:
        # requires 가 있는 [보너스] 항목은 '앞 항목들을 다 했는가'를 묻는 것이다.
        # 그런데 여기서는 앞 항목 판정 자체가 핵심어 일치로 때운 가짜라서,
        # 그것을 근거로 보너스를 주면 부풀린 점수 위에 또 점수를 얹는 꼴이 된다.
        # 그래서 대체 경로에서는 보너스를 계산하지 않고 미충족으로 둔다
        if c.requires:
            results.append(
                ChecklistResult(
                    id=c.id,
                    description=c.description,
                    description_en=c.description_en,
                    met=0,
                    weight=c.weight,
                    # 여기서도 source 는 KIWI 다. 대체 경로로 돈 채점이라는 표시가
                    # 남아 있어야 신뢰도 판정이 이 채점을 fallback 으로 잡는다
                    source=FeatureSource.KIWI,
                    evidence=[
                        Evidence(
                            source=FeatureSource.KIWI,
                            comment=_RULE_FALLBACK_TEXT,
                            notice=notice_or_free_text(None, _RULE_FALLBACK_TEXT),
                        )
                    ],
                    note=_FALLBACK_NOTE.message,
                    notice=_FALLBACK_NOTE,
                )
            )
            continue

        # 항목 설명에 들어 있는 두 글자 이상 한글 낱말과, 문항이 지정한 핵심어를 후보로 삼는다
        candidates = set(item.reference_keywords)
        candidates.update(re.findall(r"[가-힣]{2,}", c.description))

        # 후보 중 하나라도 답안에 나타나면 거기서 멈춘다(어차피 임시 판정이라 정밀도를 따지지 않는다)
        hit_word = None
        for word in candidates:
            if normalized_answer.find(re.sub(r"\s+", "", word)) != -1:
                hit_word = word
                break

        if hit_word:
            # 임시 판정이라도 근거 위치는 남긴다. 근거 없는 점수를 만들지 않는다는 원칙은 같다
            check = verify_citation(answer_text, hit_word)
            hit_comment = notice("CHECKLIST_COMMENT_FALLBACK_MET", keyword=hit_word)
            evidence = [
                Evidence(
                    source=FeatureSource.KIWI,
                    quote=check.matched_text if check.ok else hit_word,
                    start=check.start,
                    end=check.end,
                    comment=hit_comment.message,
                    notice=hit_comment,
                    detail={"matched_keyword": hit_word},
                )
            ]
            results.append(
                ChecklistResult(
                    id=c.id,
                    description=c.description,
                    description_en=c.description_en,
                    met=1,
                    weight=c.weight,
                    source=FeatureSource.KIWI,
                    evidence=evidence,
                    note=_FALLBACK_NOTE.message,
                    notice=_FALLBACK_NOTE,
                )
            )
        else:
            results.append(
                ChecklistResult(
                    id=c.id,
                    description=c.description,
                    description_en=c.description_en,
                    met=0,
                    weight=c.weight,
                    source=FeatureSource.KIWI,
                    evidence=[
                        Evidence(
                            source=FeatureSource.KIWI,
                            comment=_FALLBACK_UNMET.message,
                            notice=_FALLBACK_UNMET,
                        )
                    ],
                    note=_FALLBACK_NOTE.message,
                    notice=_FALLBACK_NOTE,
                )
            )
    return results, warnings, notices


def judge_checklist(
    answer_text: str,
    item: ItemInfo,
    client: GeminiClient | None = None,
    use_llm: bool = True,
) -> ChecklistJudgeResult:
    """체크리스트 항목들을 0/1로 판정한다."""
    out = ChecklistJudgeResult()

    # 문항이 체크리스트를 안 넘겨줬다면 판정할 것 자체가 없다
    if not item.checklist:
        emit(out.warnings, out.notices, "CHECKLIST_NONE")
        return out

    # 물어볼 항목이 하나도 없고 전부 규칙 계산 항목이면 LLM 을 부를 이유가 없다.
    # (앞 항목이 없으니 보너스는 모두 미충족으로 계산된다)
    if not llm_judged_items(item.checklist):
        results, warnings, notices, _ = results_from_llm_payload(
            answer_text, item.checklist, {"results": []}
        )
        out.results = results
        out.warnings = warnings
        out.notices = notices
        return out

    # 키가 없거나 LLM을 껐으면 임시 대체 판정으로 넘어간다(채점을 멈추지 않는다)
    client = client or GeminiClient()
    if not use_llm or not client.available:
        inner = notice(
            "CHECKLIST_LLM_DISABLED_OPTION" if not use_llm else "CHECKLIST_API_KEY_MISSING"
        )
        results, warnings, notices = _keyword_fallback(answer_text, item)
        out.results = results
        # 겉 문구(LLM 미사용 사유)와 안쪽 사유를 둘 다 코드로 담아 맨 앞에 세운다.
        # 그래야 백엔드가 겉과 속을 각각 영어로 바꿔 조립할 수 있다
        head = notice(
            "CHECKLIST_LLM_UNUSED_WRAP", reason=inner.message, reasonNotice=inner
        )
        out.warnings = [head.message] + warnings
        out.notices = [head] + notices
        return out

    prompt = build_prompt(answer_text, item)
    try:
        payload = client.generate_json(
            prompt,
            system_instruction=SYSTEM_INSTRUCTION,
            response_schema=RESPONSE_SCHEMA,
        )
    except LLMUnavailable as exc:
        # 호출은 시도했지만 실패한 경우에도 같은 임시 경로로 빠진다
        results, warnings, notices = _keyword_fallback(answer_text, item)
        out.results = results
        head = notice(
            "CHECKLIST_JUDGE_FAILED", reason=str(exc), reasonNotice=exc.notice
        )
        out.warnings = [head.message] + warnings
        out.notices = [head] + notices
        return out

    # 받은 답을 그대로 믿지 않고 인용 검증을 거쳐 최종 판정으로 바꾼다
    results, warnings, notices, dropped = results_from_llm_payload(
        answer_text, item.checklist, payload
    )
    out.results = results
    out.warnings = warnings
    out.notices = notices
    out.dropped_citations = dropped
    out.llm_used = True
    # 누가 답했는지를 남긴다(붐비는 모델 대신 대체 모델이 답했을 수 있다)
    out.llm_model_used, out.llm_fallback_from = answered_model(client)
    return out


def dump_prompt_for_review(answer_text: str, item: ItemInfo) -> str:
    """만들어진 프롬프트를 사람이 눈으로 확인할 때 쓰는 도우미."""
    return json.dumps(
        {"system": SYSTEM_INSTRUCTION, "user": build_prompt(answer_text, item)},
        ensure_ascii=False,
        indent=2,
    )
