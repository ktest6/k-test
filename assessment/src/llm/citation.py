"""LLM이 내놓은 인용이 답안 원문에 실제로 있는지 확인하고, 없으면 버리는 모듈.

왜 필요한가:
LLM은 그럴듯한 문장을 지어낼 수 있다. "'저는 어제 지각했습니다'라고 했으므로 충족"
이라고 답했는데 답안에 그런 문장이 없으면, 그 판정은 환각이다.
그런 판정을 점수에 넣으면 채점 근거 전체를 믿을 수 없게 된다.
그래서 인용을 원문과 대조해 통과한 것만 근거로 삼는다.

대조는 '적당히 느슨하게' 한다. 띄어쓰기나 문장부호가 조금 다른 것까지 버리면
멀쩡한 근거를 다 버리게 되므로, 공백과 문장부호는 무시하고 비교한다.
대신 글자 자체가 다르면 통과시키지 않는다.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

# 비교할 때 무시할 문자들: 공백류와 흔한 문장부호·따옴표.
_IGNORED_CHARS = set(" \t\r\n ​.,!?~…·:;\"'“”‘’()[]{}<>「」『』-–—/\\")

# 이보다 짧은 인용은 "우연히 겹칠" 수 있어 근거로 인정하지 않는다.
MIN_QUOTE_LENGTH = 2


def normalize_for_match(text: str) -> tuple[str, list[int]]:
    """비교용으로 다듬은 문자열과, 그 글자들이 원문 몇 번째 자리에서 왔는지 목록을 함께 돌려준다.

    자리 목록을 같이 만드는 이유는, 인용을 찾은 뒤 "원문 12~30번째 글자"처럼
    정확한 위치를 근거에 남기기 위해서다.
    """
    # 다듬은 글자들을 모을 통과, 각 글자가 원문 몇 번째에서 왔는지를 적을 통을 나란히 준비한다
    normalized_chars: list[str] = []
    positions: list[int] = []

    # 원문을 한 글자씩 훑으면서 '비교에 쓸 글자'만 골라낸다
    for index, char in enumerate(text):
        # 공백과 문장부호는 비교 대상에서 아예 뺀다
        # (응시자가 쉼표를 하나 더 찍었다고 근거를 버리면 안 되기 때문)
        if char in _IGNORED_CHARS:
            continue

        # NFKC 정규화: 전각 문자(ａ)와 반각 문자(a)처럼 겉모습만 다른 글자를 하나로 맞춘다
        # 정규화하면 글자 하나가 여러 글자로 풀리는 경우가 있어 결과를 다시 훑는다
        folded = unicodedata.normalize("NFKC", char)
        for sub_char in folded:
            # 정규화 결과로 새로 생긴 공백·기호도 똑같이 걸러낸다
            if sub_char in _IGNORED_CHARS:
                continue
            # 영문 대소문자 차이로 근거를 놓치지 않도록 소문자로 맞춰 둔다
            normalized_chars.append(sub_char.lower())
            # 한 글자가 여러 글자로 풀려도 원문 위치는 같은 자리를 가리키게 둔다
            # (나중에 "원문 12번째 글자부터" 라고 정확히 짚기 위한 지도다)
            positions.append(index)

    return "".join(normalized_chars), positions


@dataclass
class CitationCheck:
    """인용 하나를 대조한 결과."""

    quote: str
    ok: bool
    start: int | None = None   # 원문에서 인용이 시작하는 글자 위치
    end: int | None = None     # 원문에서 인용이 끝나는 글자 위치(파이썬 슬라이스 기준)
    matched_text: str = ""     # 원문에서 실제로 찾아낸 구간 (LLM이 적은 문자열이 아니라)
    reason: str = ""           # 통과하지 못했다면 그 이유


def verify_citation(
    source_text: str,
    quote: str,
    min_length: int = MIN_QUOTE_LENGTH,
) -> CitationCheck:
    """인용 하나가 원문에 있는지 확인한다.

    통과하면 원문에서의 위치(start, end)까지 채워서 돌려준다.
    """
    # 빈 인용은 볼 것도 없이 탈락이다. LLM이 근거를 안 대고 판정만 한 경우가 여기 걸린다
    if quote is None or not str(quote).strip():
        return CitationCheck(quote=quote or "", ok=False, reason="인용이 비어 있음")

    # 원문과 인용을 둘 다 '비교용 형태'로 바꾼다
    # (띄어쓰기·문장부호를 떼어내서 사소한 차이는 무시하려는 것)
    quote = str(quote)
    norm_source, source_positions = normalize_for_match(source_text)
    norm_quote, _ = normalize_for_match(quote)

    # 너무 짧은 인용은 우연히 겹칠 수 있어 근거로 인정하지 않는다
    # ('요' 한 글자가 답안 어딘가에 있다고 근거가 될 수는 없다)
    if len(norm_quote) < min_length:
        return CitationCheck(
            quote=quote,
            ok=False,
            reason=f"인용이 너무 짧아 근거로 인정하지 않음(최소 {min_length}자)",
        )

    # 다듬은 원문 안에서 다듬은 인용을 찾는다. 못 찾으면 지어낸 인용이므로 폐기한다
    found = norm_source.find(norm_quote)
    if found == -1:
        return CitationCheck(
            quote=quote,
            ok=False,
            reason="답안 원문에서 찾을 수 없는 인용(폐기)",
        )

    # 찾은 자리를 아까 만들어 둔 위치 지도로 되짚어 '원문에서의 위치'로 바꾼다
    # 끝 위치는 마지막 글자의 자리에 1을 더해, 잘라내기가 그 글자까지 포함하게 한다
    start = source_positions[found]
    end = source_positions[found + len(norm_quote) - 1] + 1

    # 근거로는 LLM이 적어 준 문자열이 아니라 원문에서 실제로 잘라낸 구간을 돌려준다
    # (응시자에게 보여 줄 때 답안에 없는 글자가 섞이면 안 되기 때문)
    return CitationCheck(
        quote=quote,
        ok=True,
        start=start,
        end=end,
        matched_text=source_text[start:end],
    )


@dataclass
class CitationFilterResult:
    """여러 개의 LLM 결과 항목을 한꺼번에 거른 결과."""

    kept: list[dict[str, Any]] = field(default_factory=list)
    dropped: list[dict[str, Any]] = field(default_factory=list)

    @property
    def dropped_count(self) -> int:
        return len(self.dropped)

    @property
    def drop_messages(self) -> list[str]:
        """보고용 경고 문구. 무엇이 왜 버려졌는지 사람이 읽을 수 있게 만든다."""
        messages = []
        # 버려진 항목마다 "무엇을 왜 버렸는지" 한 줄로 만든다
        # 인용이 길면 앞부분만 잘라 보여 준다(경고 문구가 답안 전문으로 뒤덮이지 않게)
        for item in self.dropped:
            quote = str(item.get("quote", ""))[:40]
            reason = item.get("_citation_reason", "사유 불명")
            messages.append(f"인용 폐기: '{quote}' — {reason}")
        return messages


def filter_by_citation(
    source_text: str,
    items: Iterable[dict[str, Any]],
    quote_keys: Sequence[str] = ("quote",),
    min_length: int = MIN_QUOTE_LENGTH,
) -> CitationFilterResult:
    """LLM이 돌려준 항목 목록에서, 인용이 원문에 있는 것만 남긴다.

    남은 항목에는 원문에서의 위치(_citation_start/_citation_end)를 붙여준다.
    quote_keys 에 여러 키를 주면 그 중 하나라도 통과하는 인용을 쓴다.
    (예: 오류 자질은 'quote'만, 체크리스트는 'quote' 또는 'evidence' 필드를 쓸 수 있다)
    """
    result = CitationFilterResult()

    # LLM이 준 항목을 하나씩 꺼내 인용을 대조한다
    for item in items:
        # 모델이 형식을 깨서 사전(dict)이 아닌 값을 섞어 보낼 때가 있다. 그런 항목은 그냥 버린다
        if not isinstance(item, dict):
            result.dropped.append(
                {"quote": str(item), "_citation_reason": "형식이 올바르지 않은 항목"}
            )
            continue

        # 인용이 들어 있을 만한 필드를 차례로 시도해서, 하나라도 통과하면 그것을 쓴다
        check: CitationCheck | None = None
        for key in quote_keys:
            if item.get(key):
                candidate = verify_citation(source_text, str(item[key]), min_length)
                if candidate.ok:
                    check = candidate
                    break
                # 통과하지 못한 이유는 마지막 것을 남겨 보고에 쓴다
                check = candidate

        # 원본을 그대로 두고 복사본에 검증 결과를 덧붙인다(부르는 쪽 자료를 건드리지 않기 위해)
        enriched = dict(item)

        # 인용 필드 자체가 아예 없었던 경우
        if check is None:
            enriched["_citation_reason"] = "인용 필드가 없음"
            result.dropped.append(enriched)
            continue

        if check.ok:
            # 통과한 항목에는 원문에서의 위치와 실제로 잘라낸 구간을 붙여 준다
            # 뒤에서 근거(Evidence)를 만들 때 이 값을 그대로 쓴다
            enriched["_citation_start"] = check.start
            enriched["_citation_end"] = check.end
            enriched["_citation_matched"] = check.matched_text
            result.kept.append(enriched)
        else:
            # 통과 못 한 항목은 사유를 붙여 버림 목록으로 보낸다(점수에 반영되지 않는다)
            enriched["_citation_reason"] = check.reason
            result.dropped.append(enriched)

    return result
