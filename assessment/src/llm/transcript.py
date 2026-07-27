"""STT(음성을 글자로 옮기는 기계)가 받아쓴 전사본을 Gemini로 다듬는 모듈.

왜 필요한가:
말하기 답안은 응시자가 직접 쓴 글이 아니라 기계가 옮겨 적은 글이다.
외국인 발화는 기계가 잘못 알아듣는 비율이 원어민보다 훨씬 높아서,
잘못 적힌 글자가 그대로 '문법 오류'로 잡히는 일이 생긴다.
그러면 발음이 나쁜 응시자가 언어 사용 영역에서도 한 번 더 깎인다.

그렇다고 보정을 세게 걸면 반대 문제가 생긴다.
응시자가 실제로 틀린 조사·어미까지 고쳐지면 점수가 실제 실력보다 높게 나온다.

그래서 이 모듈은 다음 세 가지를 지킨다.

1) 원본을 지우지 않는다.
   보정본은 '내용·과제 수행'에만 쓰이고, 문법·어휘 채점은 계속 원본으로 한다.
   어느 영역이 무엇을 쓰는지는 scoring/pipeline.py 가 정한다.

2) 무엇이 무엇으로 바뀌었는지 전부 남긴다.
   응시자가 "나는 그렇게 말하지 않았다"고 이의를 제기하면
   어느 글자가 어떻게 바뀌었는지 짚어 줄 수 있어야 한다. diff 는 선택이 아니다.

3) 바뀐 자리의 좌표는 LLM에게 묻지 않고 코드가 직접 센다.
   보정 구간 좌표는 '원본 전사 기준'이어야 한다.
   채점 파이프라인이 이 좌표를 오류 지적 위치와 맞대 보고
   "이 지적은 전사 오류일 수 있다"는 꼬리표를 달기 때문이다.
   좌표계를 틀리면 엉뚱한 지적에 꼬리표가 붙으므로 difflib 으로 직접 계산한다.

LLM을 못 쓰는 상황(키 없음·호출 실패)에서도 예외를 던지지 않는다.
그때는 '보정하지 않은 원문'을 그대로 돌려주고 경고만 남긴다.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

from ..scoring.schema import Evidence, FeatureSource
from .citation import verify_citation
from .client import GeminiClient, LLMUnavailable

# 보정이 원문을 이 비율보다 많이 바꾸면 보정 전체를 물린다.
# 몇 글자를 고치는 것이 아니라 답안을 통째로 다시 써 버린 경우인데,
# 그런 보정본으로 내용을 채점하면 응시자가 하지 않은 말로 점수를 주게 된다.
MAX_CHANGE_RATIO = 0.3

# 삽입(원본에는 없던 글자가 생긴 곳)은 원본에서 폭이 0이라 겹침 판정에 걸리지 않는다.
# 그 자리 앞뒤로 이만큼 넓혀서 '이 근처가 잘못 들린 자리'로 표시한다.
INSERT_PAD = 1


SYSTEM_INSTRUCTION = """\
당신은 음성 인식(STT) 결과를 다듬는 전사 교정 도구다.
당신은 채점자가 아니다. 점수를 매기거나 평가하지 않는다.

반드시 지킬 규칙:
1. 고칠 수 있는 것은 '기계가 잘못 알아들은 것'뿐이다.
   발음이 비슷해서 엉뚱한 낱말로 적힌 곳, 문맥상 뜻이 통하지 않는 낱말이 대상이다.
2. 화자가 실제로 틀린 것은 절대 고치지 않는다.
   조사(은/는/이/가/을/를)를 잘못 골랐거나, 어미 활용이 어색하거나,
   높임법이 틀렸거나, 낱말을 잘못 골라 쓴 것은 그대로 둔다.
   그것이 바로 채점 대상이므로, 고쳐 버리면 응시자 점수가 실제 실력보다 높아진다.
3. 문장을 다시 쓰거나 요약하거나 더 자연스럽게 다듬지 않는다.
   말버릇("음", "그", "저기")도 지우지 않는다.
4. 고칠 곳이 없으면 원문을 한 글자도 바꾸지 말고 그대로 돌려준다.
   억지로 고칠 곳을 찾아내지 마라.
5. 반드시 지정된 JSON 형식으로만 답한다.
"""

USER_PROMPT_TEMPLATE = """\
아래는 한국어 시험 응시자의 말하기 답안을 음성 인식기가 받아쓴 결과다.
기계가 잘못 알아들은 곳만 골라 고쳐라.

[문항 지시문]
{item_prompt}

[응시자 국적]
{nationality}

[전사 원문]
```
{original_text}
```

국적 정보는 '어떤 소리를 기계가 헷갈렸을까'를 짐작하는 데만 쓴다.
해당 언어권 화자에게 흔한 발음 특성 때문에 잘못 받아써졌을 가능성을 고려하되,
그 사람의 한국어 문법 실력을 짐작해서 문장을 고치는 데 쓰지 마라.

다음 JSON 형식으로만 답하라.
{{
  "corrected_text": "고친 전체 문장. 고칠 곳이 없으면 원문 그대로",
  "changes": [
    {{
      "original": "전사 원문에서 그대로 복사한, 잘못 받아써진 부분",
      "corrected": "고친 형태",
      "reason": "왜 전사 오류로 보는지 한 문장"
    }}
  ]
}}

고칠 곳이 없으면 "changes": [] 로 답하고 corrected_text 에는 원문을 그대로 넣어라.
"""

# 응답 구조를 Gemini 쪽에서 강제하기 위한 형식표.
# 이것을 안 붙였더니 실제 호출에서 모델이 닫는 괄호를 하나 더 붙여 보내
# JSON 해석이 통째로 실패하는 일이 있었다(2026-07-26, gemini-3.5-flash).
# 보정이 실패해도 채점은 원문으로 계속되지만, 그때마다 보정을 못 하게 되므로 못 박아 둔다.
RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "corrected_text": {"type": "string"},
        "changes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "original": {"type": "string"},
                    "corrected": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["original", "corrected", "reason"],
            },
        },
    },
    "required": ["corrected_text", "changes"],
}


@dataclass
class TranscriptDiff:
    """원문 한 군데가 어떻게 바뀌었는지 적은 기록 한 줄.

    start/end 는 '원본 전사 기준' 글자 위치다.
    보정본 기준이 아니라는 점이 중요하다. 채점 쪽에서 이 좌표로
    오류 지적 위치와 겹치는지를 따지기 때문이다.
    """

    kind: str            # replace(바뀜) / delete(지워짐) / insert(끼어듦)
    original: str        # 원본에 있던 글자
    corrected: str       # 보정본에서의 글자
    start: int           # 원본에서 이 변경이 시작하는 자리
    end: int             # 원본에서 이 변경이 끝나는 자리(삽입이면 start 와 같다)
    span_start: int      # 겹침 판정에 쓸 구간(삽입은 앞뒤로 넓힌다)
    span_end: int
    reason: str = ""     # LLM이 밝힌 사유(검증을 통과한 것만 붙는다)

    def describe(self) -> str:
        """사람이 읽는 한 줄 설명. 이의 제기 대응과 검증 스크립트에서 쓴다."""
        # 지워지거나 끼어든 경우에는 '(없음)'으로 적어야 무슨 일이 있었는지 읽힌다
        before = self.original if self.original else "(없음)"
        after = self.corrected if self.corrected else "(없음)"
        return f"원문 {self.start}~{self.end}: '{before}' → '{after}'"


@dataclass
class TranscriptCorrection:
    """전사 보정의 결과 전체.

    보정을 못 했거나 안 한 경우에도 이 객체는 만들어진다.
    그때는 corrected_text 가 원문과 같고 correction_applied 가 False 다.
    호출하는 쪽이 '보정 실패'를 따로 처리하지 않아도 되게 하려는 것이다.
    """

    original_text: str
    corrected_text: str
    diffs: list[TranscriptDiff] = field(default_factory=list)
    corrected_spans: list[tuple[int, int]] = field(default_factory=list)
    correction_applied: bool = False
    nationality: str | None = None
    llm_used: bool = False
    warnings: list[str] = field(default_factory=list)
    dropped_citations: int = 0

    @property
    def change_count(self) -> int:
        """몇 군데를 고쳤는지."""
        return len(self.diffs)

    def to_evidence(self) -> list[Evidence]:
        """보정 내역을 채점 결과에 실을 근거(Evidence) 형태로 바꾼다.

        근거 형식을 따로 만들지 않고 기존 Evidence 를 그대로 쓰는 이유는,
        백엔드와 프론트가 이미 근거를 읽는 방법을 알고 있기 때문이다.
        quote 는 반드시 원본에 실제로 있는 글자여야 하므로,
        LLM이 적어 준 문자열이 아니라 원본에서 잘라낸 구간을 넣는다.
        """
        evidence: list[Evidence] = []
        for d in self.diffs:
            # 삽입은 원본에서 폭이 0이라 인용할 글자가 없다.
            # 그래서 앞뒤를 한 글자씩 넓힌 구간을 인용으로 삼아 자리를 보여 준다
            quote = self.original_text[d.span_start : d.span_end]
            evidence.append(
                Evidence(
                    source=FeatureSource.LLM,
                    quote=quote,
                    start=d.span_start,
                    end=d.span_end,
                    comment=(
                        f"STT 전사 보정: {d.describe()}"
                        + (f" — {d.reason}" if d.reason else "")
                    ),
                    detail={
                        "kind": d.kind,
                        "original": d.original,
                        "corrected": d.corrected,
                        "coordinate_base": "original_transcript",
                    },
                )
            )
        return evidence


def _strip_spaces(text: str) -> str:
    """공백을 모두 뗀 형태. 띄어쓰기만 다른 변경을 걸러낼 때 쓴다."""
    return re.sub(r"\s+", "", text)


def _merge_spans(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """겹치거나 맞닿은 구간들을 하나로 합친다.

    붙어 있는 구간을 따로 두면 같은 자리를 여러 번 세게 되고,
    겹침 판정도 쓸데없이 여러 번 돌게 된다.
    """
    if not spans:
        return []

    # 시작 위치 순으로 세워 놓고 앞에서부터 이어 붙인다
    ordered = sorted(spans)
    merged = [ordered[0]]
    for start, end in ordered[1:]:
        last_start, last_end = merged[-1]
        # 앞 구간의 끝과 이번 구간의 시작이 겹치거나 맞닿으면 하나로 늘린다
        if start <= last_end:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged


def diff_transcript(
    original_text: str,
    corrected_text: str,
    insert_pad: int = INSERT_PAD,
) -> tuple[list[TranscriptDiff], list[tuple[int, int]]]:
    """원문과 보정본을 글자 단위로 대조해서 바뀐 자리를 찾아낸다.

    이 함수가 이 모듈에서 가장 중요한 부분이다.
    돌려주는 좌표는 전부 '원본 전사 기준'이며, 채점 쪽에서 이 좌표로
    오류 지적과 보정 구간이 겹치는지를 따진다.

    LLM에게 "몇 번째 글자를 고쳤냐"고 묻지 않는 이유는 간단하다.
    모델은 글자를 세는 일을 자주 틀리고, 좌표가 틀리면 엉뚱한 지적에
    '신뢰도 낮음' 표시가 붙어 채점 근거가 오히려 어지러워진다.
    """
    # autojunk 를 끄는 이유: 긴 글에서 흔한 글자를 자동으로 '무시해도 되는 것'으로
    # 취급해 버리면 실제로 바뀐 자리를 놓친다. 채점 근거를 만드는 일이라 정확도가 먼저다
    matcher = difflib.SequenceMatcher(None, original_text, corrected_text, autojunk=False)

    diffs: list[TranscriptDiff] = []
    spans: list[tuple[int, int]] = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        # 그대로인 구간은 볼 것이 없다
        if tag == "equal":
            continue

        before = original_text[i1:i2]
        after = corrected_text[j1:j2]

        # 띄어쓰기만 달라진 것은 보정으로 세지 않는다.
        # STT가 정한 띄어쓰기는 응시자의 잘못이 아니라서 말하기에서 채점하지 않으며,
        # 이것까지 보정 구간에 넣으면 멀쩡한 오류 지적에까지 신뢰도 표시가 붙는다
        if _strip_spaces(before) == _strip_spaces(after):
            continue

        # 겹침 판정에 쓸 구간을 정한다.
        # 바뀜·지워짐은 원본에 자리가 있으니 그대로 쓰고,
        # 삽입은 원본에서 폭이 0이라 앞뒤로 조금 넓혀야 그 근처의 지적을 잡을 수 있다
        if i1 == i2:
            span_start = max(0, i1 - insert_pad)
            span_end = min(len(original_text), i1 + insert_pad)
        else:
            span_start, span_end = i1, i2

        diffs.append(
            TranscriptDiff(
                kind=tag,
                original=before,
                corrected=after,
                start=i1,
                end=i2,
                span_start=span_start,
                span_end=span_end,
            )
        )
        # 폭이 0인 구간(원문 맨 끝에 붙은 삽입 등)은 겹침 판정에 쓸모가 없어 뺀다
        if span_end > span_start:
            spans.append((span_start, span_end))

    return diffs, _merge_spans(spans)


def _change_ratio(diffs: list[TranscriptDiff], original_text: str) -> float:
    """원문의 몇 할이 바뀌었는지 대략 계산한다. 과보정을 걸러내는 데 쓴다."""
    if not original_text:
        return 0.0
    # 바뀜은 '고치기 전'과 '고친 뒤' 중 긴 쪽을 센다.
    # 짧은 말을 긴 문장으로 부풀린 경우를 놓치지 않기 위해서다
    changed = sum(max(len(d.original), len(d.corrected)) for d in diffs)
    return changed / len(original_text)


def _collect_reasons(
    original_text: str,
    raw_changes: object,
) -> tuple[dict[str, str], int, list[str]]:
    """LLM이 밝힌 수정 사유를 모은다. 원문에 없는 것은 버린다.

    LLM이 "'회사'를 고쳤다"고 했는데 원문에 '회사'가 없으면 그 설명은 지어낸 것이다.
    사유는 점수에 직접 영향을 주지 않지만, 지어낸 설명을 근거에 실으면
    채점 근거 전체의 신뢰가 떨어지므로 다른 모듈과 똑같이 인용 검증을 거친다.
    """
    reasons: dict[str, str] = {}
    dropped = 0
    warnings: list[str] = []

    # 형식이 깨진 응답이 와도 넘어갈 수 있게, 목록이 아니면 없는 것으로 본다
    if not isinstance(raw_changes, list):
        return reasons, dropped, warnings

    for change in raw_changes:
        if not isinstance(change, dict):
            continue
        claimed = str(change.get("original", "")).strip()
        reason = str(change.get("reason", "")).strip()
        if not claimed:
            continue

        # 고쳤다고 주장한 부분이 원문에 실제로 있는지 확인한다
        check = verify_citation(original_text, claimed)
        if not check.ok:
            dropped += 1
            warnings.append(
                f"전사 보정 사유 폐기: '{claimed[:40]}' — {check.reason}"
            )
            continue

        # 띄어쓰기가 조금 달라도 찾을 수 있도록 공백을 뗀 형태를 열쇠로 쓴다
        reasons[_strip_spaces(claimed)] = reason

    return reasons, dropped, warnings


def _attach_reasons(diffs: list[TranscriptDiff], reasons: dict[str, str]) -> None:
    """코드가 찾아낸 변경마다 LLM이 밝힌 사유를 짝지어 붙인다.

    LLM이 말한 범위와 실제로 바뀐 범위가 딱 맞아떨어지지 않는 일이 흔해서,
    한쪽이 다른 쪽을 품고 있으면 같은 자리로 본다.
    """
    for d in diffs:
        key = _strip_spaces(d.original)
        # 글자가 똑같으면 바로 붙인다
        if key and key in reasons:
            d.reason = reasons[key]
            continue
        # 범위가 어긋난 경우: 서로 품고 있는 관계면 같은 자리로 본다
        for claimed, reason in reasons.items():
            if key and claimed and (key in claimed or claimed in key):
                d.reason = reason
                break


def build_correction(
    original_text: str,
    payload: dict,
    nationality: str | None = None,
) -> TranscriptCorrection:
    """LLM이 준 응답을 검증해서 보정 결과로 바꾼다.

    LLM 호출과 떼어 놓은 이유는, 가짜 응답을 넣어 좌표 계산과 과보정 차단이
    제대로 도는지 네트워크 없이 확인할 수 있게 하기 위해서다.
    """
    result = TranscriptCorrection(
        original_text=original_text,
        corrected_text=original_text,   # 아래에서 통과했을 때만 갈아 끼운다
        nationality=nationality,
        llm_used=True,
    )

    corrected_text = payload.get("corrected_text")

    # 보정본이 아예 안 왔거나 빈 문자열이면 보정을 하지 않은 것으로 본다.
    # 빈 값을 그대로 받아 쓰면 내용 채점이 '아무 말도 안 한 답안'을 보게 된다
    if not isinstance(corrected_text, str) or not corrected_text.strip():
        result.warnings.append(
            "전사 보정 응답에 corrected_text 가 없어 원문을 그대로 쓴다."
        )
        return result

    corrected_text = corrected_text.strip()

    # LLM이 밝힌 사유를 먼저 모아 둔다(원문에 없는 주장은 여기서 버려진다)
    reasons, dropped, reason_warnings = _collect_reasons(
        original_text, payload.get("changes")
    )
    result.dropped_citations = dropped
    result.warnings.extend(reason_warnings)

    # 좌표는 LLM 말이 아니라 여기서 직접 센다
    diffs, spans = diff_transcript(original_text, corrected_text)

    # 고친 곳이 없으면 보정하지 않은 것과 같다(띄어쓰기만 바뀐 경우도 여기로 온다)
    if not diffs:
        result.corrected_text = original_text
        result.warnings.append("전사 보정에서 고칠 곳을 찾지 못해 원문을 그대로 쓴다.")
        return result

    # 과보정 차단: 원문을 통째로 다시 써 온 응답은 통으로 물린다.
    # 이것을 받아들이면 응시자가 하지 않은 말로 내용 점수를 주게 된다
    ratio = _change_ratio(diffs, original_text)
    if ratio > MAX_CHANGE_RATIO:
        result.warnings.append(
            f"※ 전사 보정 폐기 ※ 원문의 {ratio:.0%}가 바뀌어 과보정으로 판단했다"
            f"(허용 한도 {MAX_CHANGE_RATIO:.0%}). 보정 없이 원문으로 채점한다."
        )
        return result

    # 여기까지 왔으면 보정을 받아들인다
    _attach_reasons(diffs, reasons)
    result.corrected_text = corrected_text
    result.diffs = diffs
    result.corrected_spans = spans
    result.correction_applied = True
    return result


def build_prompt(
    original_text: str,
    nationality: str | None = None,
    item_prompt: str = "",
) -> str:
    """LLM에 보낼 지시문을 만든다. 테스트에서 내용 확인이 가능하도록 분리해 둔다."""
    return USER_PROMPT_TEMPLATE.format(
        item_prompt=item_prompt or "(지시문 없음)",
        # 국적을 모르면 모른다고 적는다. 빈칸으로 두면 모델이 멋대로 지어내기 쉽다
        nationality=nationality or "(알 수 없음 — 국적 정보 없이 판단하라)",
        original_text=original_text,
    )


def correct_transcript(
    original_text: str,
    nationality: str | None = None,
    item_prompt: str = "",
    client: GeminiClient | None = None,
    use_llm: bool = True,
) -> TranscriptCorrection:
    """STT 전사 원문을 보정해서 원문·보정본·diff 를 함께 돌려준다.

    LLM을 못 쓰는 상황에서도 예외를 던지지 않는다.
    그때는 보정하지 않은 원문을 그대로 돌려주고 경고만 남긴다.
    채점 자체는 원본으로도 돌아가야 하기 때문이다.
    """
    # 어떤 길로 빠지든 '원문 그대로' 상태는 항상 만들어 둔다
    no_correction = TranscriptCorrection(
        original_text=original_text,
        corrected_text=original_text,
        nationality=nationality,
    )

    # 빈 답안은 보정할 것이 없다. 호출을 아껴서 그냥 돌려준다
    if not original_text.strip():
        no_correction.warnings.append("전사 원문이 비어 있어 보정하지 않았다.")
        return no_correction

    # 호출하는 쪽이 LLM을 껐다면 시도하지 않는다
    if not use_llm:
        no_correction.warnings.append(
            "LLM 사용이 꺼져 있어 STT 전사 보정을 하지 않았다. "
            "내용·과제 수행도 전사 원문 그대로 채점된다."
        )
        return no_correction

    # 키가 없으면 호출을 시도조차 하지 않고 원문으로 넘어간다(멈추지 않는다)
    client = client or GeminiClient()
    if not client.available:
        no_correction.warnings.append(
            "GEMINI_API_KEY 가 없어 STT 전사 보정을 하지 못했다. "
            "내용·과제 수행이 전사 오류의 영향을 그대로 받는다."
        )
        return no_correction

    prompt = build_prompt(original_text, nationality, item_prompt)
    try:
        payload = client.generate_json(
            prompt,
            system_instruction=SYSTEM_INSTRUCTION,
            response_schema=RESPONSE_SCHEMA,
        )
    except LLMUnavailable as exc:
        # 네트워크가 끊기거나 사용량을 넘겨도 채점 전체를 멈추지 않는다
        no_correction.warnings.append(f"STT 전사 보정 실패(원문으로 채점 진행): {exc}")
        return no_correction

    # 받은 답을 그대로 믿지 않고 좌표 계산과 과보정 검사를 거친다
    return build_correction(original_text, payload, nationality)
