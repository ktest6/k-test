"""맥락 판단이 필요한 오류 자질을 LLM(Gemini)으로 뽑아내는 모듈.

여기서 다루는 오류는 규칙으로 세기 어려운 것들이다.
'회사를 갔습니다'의 '를'이 틀렸는지는 문장 전체를 이해해야 알 수 있다.

오류 4종 (말하기·쓰기 공통)
  - 조사 오류      : 은/는/이/가/을/를/에/에서 등을 잘못 씀
  - 어미 활용 오류 : '먹어요'를 '먹으요'처럼 잘못 활용
  - 어휘 오용      : 뜻이 맞지 않는 낱말을 씀
  - 높임법 오류    : 높여야 할 대상을 낮추거나, 사물을 높임('커피 나오셨습니다')
쓰기 전용 1종
  - 맞춤법 오류

중요: LLM이 지목한 오류는 반드시 답안 원문을 그대로 인용해야 하고,
원문에 없는 인용은 citation.py 가 걸러서 버린다. 버려진 항목은 점수에 반영되지 않는다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..llm.citation import filter_by_citation
from ..llm.client import GeminiClient, LLMUnavailable
from ..scoring.schema import Evidence, FeatureSource, FeatureStatus, FeatureValue, Mode

# 오류 종류 -> (자질 id, 사람이 읽는 이름)
ERROR_TYPES: dict[str, tuple[str, str]] = {
    "josa": ("error_josa", "조사 오류"),
    "conjugation": ("error_conjugation", "어미 활용 오류"),
    "word_choice": ("error_word_choice", "어휘 오용"),
    "honorific": ("error_honorific", "높임법 오류"),
    "spelling": ("error_spelling", "맞춤법 오류"),
}

# 말하기에서는 맞춤법을 채점하지 않는다(STT가 옮겨 적은 글자라 응시자 책임이 아니다).
COMMON_ERROR_TYPES = ["josa", "conjugation", "word_choice", "honorific"]
WRITING_ONLY_ERROR_TYPES = ["spelling"]


SYSTEM_INSTRUCTION = """\
당신은 한국어 학습자의 답안에서 문법 오류를 찾아내는 교정 도구다.
당신의 역할은 오류를 '찾는 것'뿐이며, 점수를 매기거나 등급을 평가하지 않는다.

반드시 지킬 규칙:
1. quote 필드에는 답안 원문에 있는 글자를 그대로 복사한다. 한 글자도 바꾸지 않는다.
   원문에 없는 문장을 지어내면 그 항목은 폐기되고 아무 효과도 없다.
2. 확실한 오류만 보고한다. 애매하거나 문체 취향의 문제는 보고하지 않는다.
3. 같은 자리의 오류를 여러 번 보고하지 않는다.
4. 반드시 지정된 JSON 형식으로만 답한다.
"""

USER_PROMPT_TEMPLATE = """\
아래는 한국어 시험 응시자의 답안이다. 이 답안에서 오류를 찾아라.

[문항 지시문]
{item_prompt}

[답안 원문]
```
{answer_text}
```

찾아야 할 오류 종류는 다음뿐이다. 이 밖의 것은 보고하지 마라.
{type_description}

다음 JSON 형식으로만 답하라.
{{
  "errors": [
    {{
      "type": "위 종류 중 하나의 영문 키",
      "quote": "답안 원문에서 그대로 복사한 오류 부분 (5~30자 권장)",
      "correction": "올바르게 고친 형태",
      "explanation": "왜 오류인지 한 문장으로"
    }}
  ]
}}

오류가 없으면 "errors": [] 로 답하라.
"""

# 응답 구조를 Gemini 쪽에서 강제하기 위한 형식표.
# 이것을 안 붙였더니 실제 호출에서 모델이 닫는 괄호를 하나 더 붙여 보내
# 응답 해석이 통째로 실패하는 일이 있었다(2026-07-26 실측).
# 형식이 깨지면 오류 자질 네 개가 한꺼번에 사라져 언어 사용 점수가 반쪽이 되므로 못 박아 둔다.
RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "errors": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string"},
                    "quote": {"type": "string"},
                    "correction": {"type": "string"},
                    "explanation": {"type": "string"},
                },
                "required": ["type", "quote", "correction", "explanation"],
            },
        },
    },
    "required": ["errors"],
}

TYPE_DESCRIPTIONS = {
    "josa": '- "josa": 조사 오류. 은/는/이/가/을/를/에/에서/으로 등을 잘못 골라 쓴 경우.',
    "conjugation": '- "conjugation": 어미 활용 오류. 동사·형용사의 어미를 잘못 붙인 경우.',
    "word_choice": '- "word_choice": 어휘 오용. 문맥에 맞지 않는 낱말을 쓴 경우.',
    "honorific": '- "honorific": 높임법 오류. 높일 대상을 낮추거나, 사물을 높인 경우(예: "커피 나오셨습니다").',
    "spelling": '- "spelling": 맞춤법 오류. 글자를 틀리게 적은 경우(띄어쓰기는 제외).',
}


@dataclass
class ErrorExtractionResult:
    """오류 자질 추출 결과 묶음."""

    features: list[FeatureValue] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    dropped_citations: int = 0
    llm_used: bool = False


def _eojeol_count(text: str) -> int:
    """어절(띄어쓰기로 나뉜 덩어리) 수를 센다. 오류 수를 길이로 나눌 때 쓴다."""
    # 답안이 비어 있어도 0으로 나누는 일이 없도록 최소 1을 보장한다
    return len([w for w in re.split(r"\s+", text.strip()) if w]) or 1


def build_prompt(answer_text: str, item_prompt: str, error_types: list[str]) -> str:
    """LLM에 보낼 지시문을 만든다. 테스트에서 내용 확인이 가능하도록 분리해 둔다."""
    # 이번에 찾을 오류 종류만 설명을 붙인다.
    # 말하기인데 맞춤법 설명을 넣으면 LLM이 STT 표기까지 오류라고 잡아내기 때문이다
    descriptions = "\n".join(TYPE_DESCRIPTIONS[t] for t in error_types)
    return USER_PROMPT_TEMPLATE.format(
        item_prompt=item_prompt or "(지시문 없음)",
        answer_text=answer_text,
        type_description=descriptions,
    )


def _unavailable_features(error_types: list[str], reason: str) -> list[FeatureValue]:
    """LLM을 쓸 수 없을 때, 값을 지어내지 않고 '못 구했음'으로 표시한 자질을 만든다.

    0으로 채우면 '오류가 없는 훌륭한 답안'으로 오해되어 점수가 부풀려진다.
    그래서 반드시 값 없음(UNAVAILABLE)으로 두고, 결합 단계에서 가중치를 다시 나눈다.
    """
    features = []
    # 자질을 목록에서 빼 버리지 않고 '값 없음' 상태로 남기는 이유는
    # 백엔드가 받는 자질 목록이 상황에 따라 들쭉날쭉해지지 않게 하기 위해서다
    for key in error_types:
        fid, name = ERROR_TYPES[key]
        features.append(
            FeatureValue(
                id=fid,
                name=name,
                source=FeatureSource.LLM,
                value=None,
                unit="100어절당 오류 수",
                status=FeatureStatus.UNAVAILABLE,
                note=f"LLM을 쓸 수 없어 계산하지 못했다: {reason}",
            )
        )
    return features


def _not_applicable_features(error_types: list[str], reason: str) -> list[FeatureValue]:
    """이 모드에서는 아예 채점하지 않는 자질을 표시한다."""
    features = []
    for key in error_types:
        fid, name = ERROR_TYPES[key]
        features.append(
            FeatureValue(
                id=fid,
                name=name,
                source=FeatureSource.LLM,
                value=None,
                unit="100어절당 오류 수",
                status=FeatureStatus.NOT_APPLICABLE,
                note=reason,
            )
        )
    return features


def features_from_error_items(
    answer_text: str,
    kept_items: list[dict],
    error_types: list[str],
) -> list[FeatureValue]:
    """인용 검증을 통과한 오류 목록을 자질 값으로 바꾼다.

    LLM 호출과 분리해 두어서, 가짜 응답을 넣어 계산을 검증할 수 있다.
    값은 답안 길이의 영향을 없애기 위해 '100어절당 오류 수'로 환산한다.
    """
    eojeols = _eojeol_count(answer_text)

    # 검증을 통과한 오류들을 종류별 서랍에 나눠 담는다.
    # 우리가 요청하지 않은 종류를 LLM이 만들어 보내면 여기서 자연히 버려진다
    by_type: dict[str, list[dict]] = {t: [] for t in error_types}
    for item in kept_items:
        t = str(item.get("type", "")).strip().lower()
        if t in by_type:
            by_type[t].append(item)

    features: list[FeatureValue] = []
    for key in error_types:
        fid, name = ERROR_TYPES[key]
        items = by_type[key]
        # 긴 답안일수록 오류 수가 많아지는 것은 당연하므로 100어절 기준으로 환산한다.
        # 그래야 짧게 답한 사람과 길게 답한 사람을 같은 잣대로 볼 수 있다
        per_100 = len(items) / eojeols * 100

        # 근거는 다섯 개까지만 싣는다. 위치는 인용 검증 단계에서 이미 구해 뒀다
        evidence = [
            Evidence(
                source=FeatureSource.LLM,
                quote=str(item.get("_citation_matched") or item.get("quote", "")),
                start=item.get("_citation_start"),
                end=item.get("_citation_end"),
                comment=(
                    f"{name}: {item.get('explanation', '')} "
                    f"(고친 형태: {item.get('correction', '-')})"
                ).strip(),
                detail={"correction": str(item.get("correction", ""))},
            )
            for item in items[:5]
        ]
        # 오류가 없어도 근거 자리를 비워 두지 않는다.
        # "왜 0점 감점인지"도 설명이 필요하기 때문이다
        if not evidence:
            evidence.append(
                Evidence(
                    source=FeatureSource.LLM,
                    quote="",
                    comment=f"{name}가 발견되지 않았다(검증을 통과한 지적 없음).",
                )
            )

        features.append(
            FeatureValue(
                id=fid,
                name=name,
                source=FeatureSource.LLM,
                value=round(per_100, 3),
                unit="100어절당 오류 수",
                components={
                    "error_count": float(len(items)),
                    "eojeol_count": float(eojeols),
                },
                evidence=evidence,
            )
        )
    return features


def extract_error_features(
    answer_text: str,
    mode: Mode = Mode.SPEAKING,
    client: GeminiClient | None = None,
    item_prompt: str = "",
    use_llm: bool = True,
) -> ErrorExtractionResult:
    """답안에서 LLM 오류 자질을 뽑는다.

    LLM을 못 쓰면 멈추지 않고, 해당 자질을 '값 없음'으로 두고 경고를 남긴 채 넘어간다.
    """
    result = ErrorExtractionResult()

    # 이번 답안에서 실제로 찾을 오류 종류를 정한다. 쓰기일 때만 맞춤법이 추가된다
    active_types = list(COMMON_ERROR_TYPES)
    if mode == Mode.WRITING:
        active_types += WRITING_ONLY_ERROR_TYPES

    # 말하기는 맞춤법 자질을 아예 쓰지 않는다는 사실을 응답에 남겨 둔다
    # (자질이 조용히 사라지면 백엔드가 누락인지 미적용인지 구별할 수 없다)
    if mode != Mode.WRITING:
        result.features.extend(
            _not_applicable_features(
                WRITING_ONLY_ERROR_TYPES,
                "말하기 답안은 STT가 옮겨 적은 글자이므로 맞춤법을 채점하지 않는다.",
            )
        )

    # 호출하는 쪽이 LLM을 끈 경우. 규칙 자질만으로 채점하는 빠른 모드다
    if not use_llm:
        result.features = _unavailable_features(active_types, "옵션에서 LLM 사용을 껐다") + result.features
        result.warnings.append("LLM 사용이 꺼져 있어 오류 자질(조사·어미·어휘·높임법)을 계산하지 못했다.")
        return result

    # 키가 없으면 호출을 시도조차 하지 않고 대체 경로로 넘어간다(멈추지 않는다)
    client = client or GeminiClient()
    if not client.available:
        result.features = _unavailable_features(active_types, "GEMINI_API_KEY 없음") + result.features
        result.warnings.append(
            "GEMINI_API_KEY 가 없어 오류 자질을 계산하지 못했다. "
            "언어 사용 점수는 규칙 자질만으로 계산된 임시 결과다."
        )
        return result

    prompt = build_prompt(answer_text, item_prompt, active_types)
    try:
        raw = client.generate_json(
            prompt,
            system_instruction=SYSTEM_INSTRUCTION,
            response_schema=RESPONSE_SCHEMA,
        )
    except LLMUnavailable as exc:
        # 네트워크가 끊기거나 사용량을 넘겨도 채점 전체를 실패시키지 않는다.
        # 대신 무엇을 못 했는지 경고에 남겨서 결과를 읽는 사람이 알 수 있게 한다
        result.features = _unavailable_features(active_types, str(exc)) + result.features
        result.warnings.append(f"LLM 오류 자질 추출 실패(규칙 자질만으로 진행): {exc}")
        return result

    # 형식이 깨진 응답이 와도 그대로 진행할 수 있게, 목록이 아니면 빈 목록으로 바꾼다
    raw_errors = raw.get("errors")
    if not isinstance(raw_errors, list):
        raw_errors = []
        result.warnings.append("LLM 응답에 errors 목록이 없어 오류를 0건으로 처리했다.")

    # 원문에 없는 인용은 여기서 버린다. 이 단계가 환각을 점수에서 막는 지점이다
    filtered = filter_by_citation(answer_text, raw_errors, quote_keys=("quote",))
    result.dropped_citations = filtered.dropped_count
    result.warnings.extend(filtered.drop_messages)

    result.features = features_from_error_items(answer_text, filtered.kept, active_types) + result.features
    result.llm_used = True
    return result
