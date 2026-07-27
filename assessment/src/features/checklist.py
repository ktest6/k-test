"""문항이 요구한 내용을 답안이 담았는지 항목별로 0/1 판정하는 모듈.

'내용 및 과제 수행' 영역의 핵심이다.
예를 들어 "지각한 이유를 설명하고 사과하라"는 문항이면 체크리스트는
  1) 지각한 이유를 말했는가
  2) 사과를 했는가
가 되고, 각각 충족(1) / 미충족(0) 으로 판정한다.

LLM은 여기서도 점수를 매기지 않는다. 0/1 판정과 그 근거 인용만 한다.
그리고 **근거 인용이 원문에 없으면 충족으로 인정하지 않는다.**
"근거는 못 대지만 아마 했을 것"은 채점 결과가 될 수 없다.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from ..llm.citation import filter_by_citation, verify_citation
from ..llm.client import GeminiClient, LLMUnavailable
from ..scoring.schema import (
    ChecklistItem,
    ChecklistResult,
    Evidence,
    FeatureSource,
    ItemInfo,
)

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
    dropped_citations: int = 0
    llm_used: bool = False


def build_prompt(answer_text: str, item: ItemInfo) -> str:
    """LLM에 보낼 지시문을 만든다."""
    # 항목마다 id 를 붙여서 보낸다. 그래야 돌아온 판정을 어느 항목의 것인지 짝지을 수 있다
    checklist_text = "\n".join(
        f"- id={c.id}: {c.description}" for c in item.checklist
    )
    return USER_PROMPT_TEMPLATE.format(
        item_prompt=item.prompt or "(지시문 없음)",
        answer_text=answer_text,
        checklist_text=checklist_text or "(항목 없음)",
    )


def results_from_llm_payload(
    answer_text: str,
    checklist: list[ChecklistItem],
    payload: dict,
) -> tuple[list[ChecklistResult], list[str], int]:
    """LLM이 준 판정 결과를 검증해서 최종 판정으로 바꾼다.

    LLM 호출과 분리해 두어서, 가짜 응답을 넣어 폐기 동작을 검증할 수 있다.
    핵심 규칙: 충족(1)인데 근거 인용이 원문에 없으면 0으로 내린다.
    """
    warnings: list[str] = []
    dropped = 0

    # 형식이 깨졌으면 빈 목록으로 두고 아래에서 전 항목을 미충족 처리한다
    raw_results = payload.get("results")
    if not isinstance(raw_results, list):
        raw_results = []
        warnings.append("LLM 응답에 results 목록이 없어 전 항목을 미충족으로 처리했다.")

    # LLM이 항목 순서를 바꿔 보낼 수 있으므로 id로 찾아 쓸 수 있게 정리해 둔다
    by_id = {str(r.get("id")): r for r in raw_results if isinstance(r, dict)}

    # 문항이 정한 체크리스트를 기준으로 돈다.
    # LLM이 보낸 것을 기준으로 돌면 모델이 빠뜨린 항목이 결과에서 사라져 버린다
    final: list[ChecklistResult] = []
    for item in checklist:
        raw = by_id.get(item.id)

        # LLM이 아예 판정하지 않은 항목은 '모르니까 충족'이 아니라 미충족으로 본다
        if raw is None:
            final.append(
                ChecklistResult(
                    id=item.id,
                    description=item.description,
                    met=0,
                    weight=item.weight,
                    evidence=[
                        Evidence(
                            source=FeatureSource.LLM,
                            comment="LLM이 이 항목을 판정하지 않아 미충족으로 처리했다.",
                        )
                    ],
                    note="LLM 응답 누락",
                )
            )
            warnings.append(f"체크리스트 '{item.id}' 에 대한 LLM 판정이 없어 0으로 처리했다.")
            continue

        # 모델이 1, "1", true 등 여러 모양으로 답할 수 있어 넉넉하게 받아 준다
        met = 1 if str(raw.get("met", "0")).strip() in ("1", "true", "True") else 0
        reason = str(raw.get("reason", "")).strip()
        quote = str(raw.get("quote", "")).strip()

        # 미충족 판정은 인용이 필요 없다. 없는 것을 인용할 수는 없기 때문이다
        if met == 0:
            final.append(
                ChecklistResult(
                    id=item.id,
                    description=item.description,
                    met=0,
                    weight=item.weight,
                    evidence=[
                        Evidence(
                            source=FeatureSource.LLM,
                            comment=reason or "답안에서 해당 내용을 찾지 못했다.",
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
            warnings.append(
                f"체크리스트 '{item.id}': 충족 판정의 근거 인용이 원문에 없어 폐기하고 "
                f"미충족(0)으로 내렸다 — {check.reason}"
            )
            final.append(
                ChecklistResult(
                    id=item.id,
                    description=item.description,
                    met=0,
                    weight=item.weight,
                    evidence=[
                        Evidence(
                            source=FeatureSource.LLM,
                            comment=(
                                "LLM은 충족이라고 했으나 근거 인용이 답안 원문에 없어 폐기했다. "
                                f"({check.reason})"
                            ),
                            detail={"discarded_quote": quote},
                        )
                    ],
                    note="근거 인용 폐기로 미충족 처리",
                )
            )
            continue

        # 검증을 통과한 충족 판정. 근거에는 LLM이 적어 준 문자열이 아니라
        # 원문에서 실제로 잘라낸 구간과 그 위치를 담는다
        final.append(
            ChecklistResult(
                id=item.id,
                description=item.description,
                met=1,
                weight=item.weight,
                evidence=[
                    Evidence(
                        source=FeatureSource.LLM,
                        quote=check.matched_text,
                        start=check.start,
                        end=check.end,
                        comment=reason or "답안에서 해당 내용을 확인했다.",
                    )
                ],
            )
        )

    return final, warnings, dropped


def _keyword_fallback(
    answer_text: str,
    item: ItemInfo,
) -> tuple[list[ChecklistResult], list[str]]:
    """※ 임시 대체 경로 ※ LLM을 못 쓸 때 핵심어가 답안에 있는지로만 0/1을 매긴다.

    이것은 진짜 내용 판정이 아니다. 말만 겹치고 뜻이 달라도 충족으로 잡히고,
    다른 표현으로 잘 말해도 미충족으로 잡힌다.
    운영 채점에 쓰면 안 되고, 키가 들어오면 반드시 LLM 판정으로 돌아가야 한다.
    """
    warnings = [
        "※ 임시 ※ LLM을 쓸 수 없어 체크리스트를 핵심어 일치로만 판정했다. "
        "이 결과는 내용 판정이 아니라 대체값이며 운영 채점에 쓸 수 없다."
    ]
    # 응시자가 띄어쓰기를 다르게 했어도 찾을 수 있도록 공백을 뗀 형태로 비교한다
    normalized_answer = re.sub(r"\s+", "", answer_text)

    results: list[ChecklistResult] = []
    for c in item.checklist:
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
            evidence = [
                Evidence(
                    source=FeatureSource.KIWI,
                    quote=check.matched_text if check.ok else hit_word,
                    start=check.start,
                    end=check.end,
                    comment=f"※ 임시 판정 ※ 핵심어 '{hit_word}' 가 답안에 나타남",
                    detail={"matched_keyword": hit_word},
                )
            ]
            results.append(
                ChecklistResult(
                    id=c.id,
                    description=c.description,
                    met=1,
                    weight=c.weight,
                    source=FeatureSource.KIWI,
                    evidence=evidence,
                    note="※ 임시 ※ 핵심어 일치 기반 대체 판정(LLM 미사용)",
                )
            )
        else:
            results.append(
                ChecklistResult(
                    id=c.id,
                    description=c.description,
                    met=0,
                    weight=c.weight,
                    source=FeatureSource.KIWI,
                    evidence=[
                        Evidence(
                            source=FeatureSource.KIWI,
                            comment="※ 임시 판정 ※ 관련 핵심어가 답안에서 발견되지 않음",
                        )
                    ],
                    note="※ 임시 ※ 핵심어 일치 기반 대체 판정(LLM 미사용)",
                )
            )
    return results, warnings


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
        out.warnings.append("문항에 체크리스트가 없어 내용·과제 수행을 판정할 수 없다.")
        return out

    # 키가 없거나 LLM을 껐으면 임시 대체 판정으로 넘어간다(채점을 멈추지 않는다)
    client = client or GeminiClient()
    if not use_llm or not client.available:
        reason = "옵션에서 LLM 사용을 껐다" if not use_llm else "GEMINI_API_KEY 없음"
        results, warnings = _keyword_fallback(answer_text, item)
        out.results = results
        out.warnings = [f"LLM 미사용 사유: {reason}"] + warnings
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
        results, warnings = _keyword_fallback(answer_text, item)
        out.results = results
        out.warnings = [f"LLM 체크리스트 판정 실패: {exc}"] + warnings
        return out

    # 받은 답을 그대로 믿지 않고 인용 검증을 거쳐 최종 판정으로 바꾼다
    results, warnings, dropped = results_from_llm_payload(answer_text, item.checklist, payload)
    out.results = results
    out.warnings = warnings
    out.dropped_citations = dropped
    out.llm_used = True
    return out


def dump_prompt_for_review(answer_text: str, item: ItemInfo) -> str:
    """만들어진 프롬프트를 사람이 눈으로 확인할 때 쓰는 도우미."""
    return json.dumps(
        {"system": SYSTEM_INSTRUCTION, "user": build_prompt(answer_text, item)},
        ensure_ascii=False,
        indent=2,
    )
