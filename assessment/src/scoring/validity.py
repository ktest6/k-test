"""답안이 '채점할 수 있는 글'인지 먼저 확인하는 가드(문지기) 모듈.

왜 필요한가 (2026-07-30 실측):
확정 문항 WRT-003 에 악성 답안을 넣어 보니 아래 구멍이 드러났다.

    영어로만 쓴 답안        종합 77.48점 (B)   <- 한국어 시험인데 영어가 B
    단어만 반복한 스팸       종합 57.03점 (C)
    지시문을 그대로 베낀 글   종합 57.68점 (C)

원인은 오류 자질이 '틀린 것이 없으면 만점'이라는 데 있다.
한국어를 아예 쓰지 않으면 틀릴 것도 없어서 문법 점수가 만점이 된다.
즉 **답안이 한국어인지, 문장인지 확인하는 자리가 없었다.**

그래서 채점을 시작하기 전에 네 가지를 확인한다.

    가드 A  한글 비율      (하드) 한국어가 아니면 채점 자체가 성립하지 않는다
    가드 B  최소 길이      (소프트) 너무 짧으면 '오류 0건'이 표본 부족이라 의미가 없다
    가드 C  지시문 겹침    (하드) 지시문을 베낀 글은 응시자가 쓴 글이 아니다
    가드 D  문장 성립      (하드/소프트) 낱말만 나열한 것은 문장이 아니다

이 가드는 **전부 규칙(문자 세기·Kiwi 형태소 분석)으로만 판단하고 LLM을 쓰지 않는다.**
scoring-design 스킬의 '규칙이 먼저, LLM은 마지막' 경계에 따른 것이다.
같은 답안을 두 번 넣으면 언제나 같은 판정이 나와야 하고,
무효 답안에 LLM 호출을 낭비하지 않으려면 LLM보다 앞에 서 있어야 한다.

여기서도 원칙은 같다. **판정에는 반드시 근거가 붙는다.**
어떤 값을 어떤 기준과 비교했는지(components)와 원문 어디를 보고 그렇게 판단했는지
(Evidence 의 인용·글자 위치)를 함께 남긴다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..features.lexical import Analysis, analyze
from ..llm.citation import normalize_for_match
from .schema import Evidence, FeatureSource, ScoreArea

# ---------------------------------------------------------------------------
# 기준값 (전부 임시값이므로 상수로 빼 둔다)
#
# 아래 숫자는 실측 표(정상 답안 1개 + 악성 답안 4종)를 기준으로 정한 출발점이다.
# 라벨링 데이터가 모이면 오탐(정상 답안을 막는 일)이 몇 건인지 세어 다시 잡아야 한다.
# ---------------------------------------------------------------------------

#: 가드 A. 공백·문장부호·숫자를 뺀 글자 중 한글이 이 비율 미만이면 채점 무효.
#: 숫자를 분모에서 빼는 이유는 '3번 라인', '장갑 20켤레' 같은 정상 답안 때문이다.
#: 영문 고유명사('OO회사'의 알파벳)는 분모에 남지만, 답안 전체에서 차지하는 몫이
#: 작아서 0.5 라는 넉넉한 기준이면 걸리지 않는다.
MIN_HANGUL_RATIO = 0.5

#: 가드 B. 이보다 짧으면 오류 자질을 믿을 수 없다고 보고 언어 사용 영역을 낮춘다.
#: '오류 0건 = 만점'이 성립하려면 틀릴 기회가 어느 정도는 있어야 한다.
#: 10어절이면 대체로 두 문장 분량이다.
MIN_EOJEOL_COUNT = 10

#: 가드 C. 답안 글자 중 이 비율 이상이 지시문에도 그대로 있으면 베낀 것으로 본다.
MAX_PROMPT_OVERLAP = 0.70

#: 가드 C 의 비교 단위. 지시문과 답안을 '연속된 N글자 덩어리'로 견준다.
#: 3글자면 '선반이', '위험합' 같은 흔한 조각이 우연히 겹쳐 정상 답안이 걸린다.
#: 7글자면 조사만 바꿔 베낀 글을 놓친다. 그 사이인 5글자를 쓴다.
PROMPT_NGRAM_SIZE = 5

#: 가드 D. 어미가 붙은 '문장다운 조각'의 비율.
#: 이 값 미만이면 낱말 나열로 보고 채점 무효(하드), 그 위 SOFT 미만이면 경고만 남긴다.
MIN_SENTENCE_RATIO_HARD = 0.20
MIN_SENTENCE_RATIO_SOFT = 0.60

#: 문장이 '서술어를 갖췄다'고 볼 근거가 되는 어미 품사표시.
#: EF=종결어미('-습니다'), EC=연결어미('-고'), ETM=관형사형('-는'), ETN=명사형('-기').
SENTENCE_ENDING_TAGS = {"EF", "EC", "ETM", "ETN"}

#: 가드가 붙이는 표시(flag) 이름. 백엔드가 문구가 아니라 이 값으로 분기한다.
FLAG_NOT_KOREAN = "not_korean"
FLAG_TOO_SHORT = "too_short"
FLAG_PROMPT_COPY = "prompt_copy"
FLAG_NOT_SENTENCES = "not_sentences"

#: 한글 음절과 낱자(ㄱ, ㅏ 등). 낱자만 있는 답안도 한국어 시도로는 인정한다.
_HANGUL_RE = re.compile(r"[가-힣ㄱ-ㅎㅏ-ㅣ]")
#: 한글 비율의 분모에서 뺄 글자: 공백류, 숫자, 문장부호·기호.
_SKIP_IN_RATIO_RE = re.compile(r"[\s\d]|[^\w]", re.UNICODE)
#: 연속된 로마자 덩어리. 영어 답안일 때 '어디가 영어인지'를 근거로 짚어 주는 데 쓴다.
_LATIN_RUN_RE = re.compile(r"[A-Za-z][A-Za-z\s',.\-]{3,}")


# ---------------------------------------------------------------------------
# 판정 결과를 담는 자료구조
# ---------------------------------------------------------------------------


@dataclass
class ValidityCheck:
    """가드 하나의 판정 결과.

    hard=True 인 가드가 걸리면 채점 자체가 무효가 되고,
    hard=False(소프트)면 채점은 계속하되 해당 영역의 상태를 낮춘다.
    """

    flag: str                       # 위의 FLAG_* 중 하나
    label: str                      # 사람이 읽는 가드 이름
    passed: bool                    # 통과했는지
    hard: bool                      # 걸렸을 때 채점을 무효로 할 것인지
    value: float | None = None      # 실제로 잰 값
    threshold: float | None = None  # 비교한 기준값
    reason: str = ""                # 걸렸다면 그 사유(사람이 읽는 한 문장)
    #: 소프트 가드가 걸렸을 때 상태를 낮출 채점 영역. 하드 가드는 None.
    affected_area: ScoreArea | None = None
    components: dict[str, float] = field(default_factory=dict)
    evidence: list[Evidence] = field(default_factory=list)


@dataclass
class ValidityReport:
    """가드 네 개를 모두 돌린 결과 묶음."""

    checks: list[ValidityCheck] = field(default_factory=list)

    @property
    def failures(self) -> list[ValidityCheck]:
        """걸린 가드만 모아 준다."""
        return [c for c in self.checks if not c.passed]

    @property
    def hard_failures(self) -> list[ValidityCheck]:
        """채점을 무효로 만드는 가드들."""
        return [c for c in self.failures if c.hard]

    @property
    def soft_failures(self) -> list[ValidityCheck]:
        """채점은 계속하되 영역 상태를 낮추는 가드들."""
        return [c for c in self.failures if not c.hard]

    @property
    def valid(self) -> bool:
        """이 답안을 채점해도 되는지. 하드 가드가 하나라도 걸리면 False."""
        return not self.hard_failures

    @property
    def flags(self) -> list[str]:
        """걸린 가드의 표시 이름 목록. 백엔드는 이 값으로 분기한다."""
        return [c.flag for c in self.failures]

    @property
    def reason(self) -> str:
        """무효 사유를 사람이 읽을 한 문장으로 합친다.

        하드 가드가 있으면 그것만 쓴다. 무효가 된 까닭이 먼저 보여야 하기 때문이다.
        """
        picked = self.hard_failures or self.soft_failures
        return " / ".join(c.reason for c in picked)

    @property
    def evidence(self) -> list[Evidence]:
        """걸린 가드들이 남긴 근거를 한 줄로 모은다."""
        return [ev for c in self.failures for ev in c.evidence]


def _ev(text: str, start: int, end: int, comment: str, detail: dict | None = None) -> Evidence:
    """원문의 한 구간을 잘라 근거 한 조각을 만든다.

    가드는 규칙 계산이므로 근거의 출처는 언제나 kiwi(규칙)다.
    """
    # 위치가 원문 범위를 벗어나면 엉뚱한 글자를 인용하게 되므로 안쪽으로 당긴다
    start = max(0, min(start, len(text)))
    end = max(start, min(end, len(text)))
    return Evidence(
        source=FeatureSource.KIWI,
        quote=text[start:end],
        start=start,
        end=end,
        comment=comment,
        detail=detail or {},
    )


# ---------------------------------------------------------------------------
# 가드 A — 한글 비율 (하드 게이트)
# ---------------------------------------------------------------------------


def hangul_ratio(text: str) -> tuple[float, int, int]:
    """한글 비율과 그 분자·분모를 함께 돌려준다.

    분모에서 공백·문장부호·숫자를 뺀다.
    '3번 라인에 20개 필요합니다' 같은 정상 답안이 숫자 때문에 걸리면 안 되기 때문이다.
    돌려주는 값은 (비율, 한글 글자 수, 센 글자 수)다.
    """
    # 셀 대상만 남긴다. 공백·숫자·문장부호는 한국어인지 아닌지를 가르는 근거가 못 된다
    counted = [ch for ch in text if not _SKIP_IN_RATIO_RE.match(ch)]
    denominator = len(counted)
    # 셀 글자가 하나도 없으면(빈 답안, 숫자만 적은 답안) 한국어가 없는 것으로 본다
    if denominator == 0:
        return 0.0, 0, 0

    hangul = sum(1 for ch in counted if _HANGUL_RE.match(ch))
    return hangul / denominator, hangul, denominator


def check_korean_ratio(text: str, threshold: float = MIN_HANGUL_RATIO) -> ValidityCheck:
    """가드 A) 답안이 한국어로 쓰였는지 본다. 기준 미달이면 채점 무효.

    한국어 시험이므로 이것은 채점의 전제 조건이다.
    영어로 쓴 답안은 '문법 오류가 없는 답안'이 아니라 '채점할 수 없는 답안'이다.
    """
    ratio, hangul_count, total = hangul_ratio(text)
    passed = ratio >= threshold

    check = ValidityCheck(
        flag=FLAG_NOT_KOREAN,
        label="한글 비율",
        passed=passed,
        hard=True,
        value=round(ratio, 4),
        threshold=threshold,
        components={
            "hangul_char_count": float(hangul_count),
            "counted_char_count": float(total),
        },
    )
    if passed:
        return check

    check.reason = (
        f"답안의 한글 비율이 {ratio:.0%}로 기준({threshold:.0%})에 못 미쳐 "
        "한국어 답안으로 볼 수 없다. 채점을 무효로 처리했다."
    )

    # 근거: 어디가 한국어가 아닌지 실제 구간을 짚어 준다.
    # 로마자가 길게 이어지는 자리가 있으면 그곳을, 없으면 답안 앞부분을 보여 준다
    latin = _LATIN_RUN_RE.search(text)
    if latin:
        check.evidence.append(
            _ev(text, latin.start(), min(latin.end(), latin.start() + 60),
                "한국어가 아닌 글자가 이어지는 구간",
                {"guard": FLAG_NOT_KOREAN})
        )
    check.evidence.append(
        _ev(text, 0, min(len(text), 60),
            f"답안 앞부분 (한글 {hangul_count}자 / 센 글자 {total}자)",
            {"guard": FLAG_NOT_KOREAN, "hangul_ratio": round(ratio, 4)})
    )
    return check


# ---------------------------------------------------------------------------
# 가드 B — 최소 길이 (소프트)
# ---------------------------------------------------------------------------


def check_min_length(
    analysis: Analysis, threshold: int = MIN_EOJEOL_COUNT
) -> ValidityCheck:
    """가드 B) 답안이 오류 자질을 믿을 만큼 길기는 한지 본다.

    짧다고 해서 채점을 막지는 않는다. 짧은 답안은 그 자체로 낮은 점수를 받는다.
    문제는 다른 데 있다. **오류 자질은 '틀린 것이 없으면 만점'이라서,
    한 문장짜리 답안은 틀릴 기회가 없어 언어 사용이 높게 나온다.**
    실측에서 "네 알겠습니다."가 언어 사용 64점을 받았다.
    그래서 점수는 그대로 두되 '이 영역은 표본이 부족하다'는 표시를 남긴다.
    """
    count = analysis.eojeol_count
    passed = count >= threshold

    check = ValidityCheck(
        flag=FLAG_TOO_SHORT,
        label="최소 길이",
        passed=passed,
        hard=False,
        value=float(count),
        threshold=float(threshold),
        # 걸리면 언어 사용 영역의 상태를 낮춘다(내용 점수는 길이로 이미 반영된다)
        affected_area=ScoreArea.LANGUAGE_USE,
        components={"eojeol_count": float(count)},
    )
    if passed:
        return check

    check.reason = (
        f"답안이 {count}어절로 기준({threshold}어절)보다 짧아 오류 자질을 신뢰할 수 없다. "
        "틀릴 기회 자체가 적어 '오류 0건'이 실력의 근거가 되지 못한다."
    )
    check.evidence.append(
        _ev(analysis.text, 0, min(len(analysis.text), 60),
            f"답안 전체 {count}어절",
            {"guard": FLAG_TOO_SHORT, "eojeol_count": count})
    )
    return check


# ---------------------------------------------------------------------------
# 가드 C — 지시문 겹침 (하드 게이트)
# ---------------------------------------------------------------------------


def prompt_overlap(
    answer_text: str, prompt: str, ngram: int = PROMPT_NGRAM_SIZE
) -> tuple[float, list[tuple[int, int]]]:
    """답안 글자 중 몇 %가 지시문에서 그대로 온 것인지 재고, 겹친 구간도 함께 돌려준다.

    재는 방법 (왜 이렇게 했는지):
    낱말 단위로 세면 '선반', '위험' 같은 낱말을 자연스럽게 다시 쓴 정상 답안까지
    베낀 것으로 몰린다. 반대로 문장 전체가 같은지만 보면 조사만 바꿔 베낀 글을 놓친다.
    그래서 **연속된 5글자 덩어리**가 지시문에 그대로 있는지를 보고,
    그런 덩어리에 속한 글자가 답안에서 몇 %인지를 센다.
    다섯 글자가 통째로 같은 자리가 답안의 대부분이라면 그것은 베낀 글이다.

    비교 전에 공백·문장부호를 떼어 낸다(인용 검증과 같은 방식).
    "선반이 기울어져" 와 "선반이기울어져" 를 다른 글로 보면 안 되기 때문이다.
    """
    # 공백·문장부호를 뗀 형태로 맞추고, 각 글자가 원문 몇 번째에서 왔는지도 함께 받는다
    norm_answer, positions = normalize_for_match(answer_text)
    norm_prompt, _ = normalize_for_match(prompt or "")

    if not norm_answer or not norm_prompt:
        return 0.0, []

    # 답안이 덩어리 크기보다도 짧으면 덩어리를 만들 수 없다.
    # 이때는 답안 전체가 지시문 안에 들어 있는지만 본다
    if len(norm_answer) < ngram:
        if norm_answer in norm_prompt:
            return 1.0, [(positions[0], positions[-1] + 1)]
        return 0.0, []

    # 지시문에 있는 5글자 덩어리를 모두 모아 둔다(찾아보기 쉽게 집합으로)
    prompt_chunks = {norm_prompt[i : i + ngram] for i in range(len(norm_prompt) - ngram + 1)}

    # 답안을 5글자씩 훑으면서, 지시문에도 있는 덩어리에 속한 글자를 표시한다
    covered = [False] * len(norm_answer)
    for i in range(len(norm_answer) - ngram + 1):
        if norm_answer[i : i + ngram] in prompt_chunks:
            for j in range(i, i + ngram):
                covered[j] = True

    ratio = sum(covered) / len(covered)

    # 표시된 글자들을 이어 붙여 '겹친 구간'으로 만든다(원문 글자 위치 기준).
    # 이것이 "어디를 베꼈는지" 짚어 주는 근거가 된다
    spans: list[tuple[int, int]] = []
    run_start: int | None = None
    for index, is_covered in enumerate(covered):
        if is_covered and run_start is None:
            run_start = index
        elif not is_covered and run_start is not None:
            spans.append((positions[run_start], positions[index - 1] + 1))
            run_start = None
    if run_start is not None:
        spans.append((positions[run_start], positions[-1] + 1))

    # 긴 구간이 먼저 오게 정렬한다. 근거로 보여 줄 때 제일 많이 겹친 곳부터 보여 주기 위해서다
    spans.sort(key=lambda s: s[0] - s[1])
    return ratio, spans


def check_prompt_overlap(
    answer_text: str, prompt: str, threshold: float = MAX_PROMPT_OVERLAP
) -> ValidityCheck:
    """가드 C) 답안이 지시문을 베낀 것인지 본다. 대부분이 지시문이면 채점 무효.

    실측에서 지시문을 그대로 옮겨 적은 답안이 체크리스트 1/3을 통과해 C등급을 받았다.
    지시문에 이미 위험 상황 설명이 들어 있으니 당연한 결과지만,
    그것은 응시자가 쓴 글이 아니므로 채점의 대상이 아니다.
    """
    ratio, spans = prompt_overlap(answer_text, prompt)
    passed = ratio < threshold

    check = ValidityCheck(
        flag=FLAG_PROMPT_COPY,
        label="지시문 겹침",
        passed=passed,
        hard=True,
        value=round(ratio, 4),
        threshold=threshold,
        components={
            "overlap_ratio": round(ratio, 4),
            "ngram_size": float(PROMPT_NGRAM_SIZE),
            "overlap_span_count": float(len(spans)),
        },
    )
    if passed:
        return check

    check.reason = (
        f"답안 글자의 {ratio:.0%}가 지시문과 그대로 겹쳐(기준 {threshold:.0%}) "
        "응시자가 직접 쓴 글로 볼 수 없다. 채점을 무효로 처리했다."
    )
    # 근거: 지시문과 똑같이 겹친 구간을 긴 것부터 세 곳만 보여 준다
    for start, end in spans[:3]:
        check.evidence.append(
            _ev(answer_text, start, end,
                "지시문에 그대로 있는 구간",
                {"guard": FLAG_PROMPT_COPY})
        )
    return check


# ---------------------------------------------------------------------------
# 가드 D — 문장 성립 (소프트 -> 하드)
# ---------------------------------------------------------------------------


def sentence_like_ratio(analysis: Analysis) -> tuple[float, int, int]:
    """어미가 붙어 '문장다운' 조각이 전체 문장 중 몇 %인지 잰다.

    한국어 문장은 서술어로 끝나고, 서술어에는 어미가 붙는다.
    '창고 위험 선반 수리'처럼 낱말만 늘어놓으면 어미가 하나도 없다.
    그래서 어미가 있는지를 '문장이 성립했는지'의 잣대로 쓴다.
    돌려주는 값은 (비율, 문장다운 조각 수, 전체 문장 수)다.
    """
    if not analysis.sentences:
        return 0.0, 0, 0

    # 문장마다 어미(종결·연결·관형사형·명사형)가 하나라도 있는지 본다
    sentence_like = 0
    for sentence in analysis.sentences:
        has_ending = any(
            token.tag in SENTENCE_ENDING_TAGS for token in sentence.tokens
        )
        # '했는데요'처럼 어미 뒤에 '요'가 붙어 끝나는 말도 문장으로 인정한다
        # (이 경우 마지막 조각이 어미가 아니라 조사로 잡힌다)
        if not has_ending:
            has_ending = any(
                token.tag.startswith("J") and token.form == "요"
                for token in sentence.tokens
            )
        if has_ending:
            sentence_like += 1

    total = len(analysis.sentences)
    return sentence_like / total, sentence_like, total


def check_sentence_formation(
    analysis: Analysis,
    hard_threshold: float = MIN_SENTENCE_RATIO_HARD,
    soft_threshold: float = MIN_SENTENCE_RATIO_SOFT,
) -> ValidityCheck:
    """가드 D) 답안이 문장으로 되어 있는지 본다.

    두 단계로 나눈 이유:
    어미가 아예 없으면(낱말 나열, 검색어 같은 답안) 채점할 문장이 없는 것이므로 무효다.
    반쯤 있으면 말을 하다 만 것일 수도 있어 무효까지 가지 않고,
    내용·과제 수행 영역에 '온전한 문장이 아니다'라는 표시만 남긴다.
    """
    ratio, sentence_like, total = sentence_like_ratio(analysis)

    # 기준을 크게 밑돌면 무효(하드), 어중간하면 경고만(소프트)
    is_hard_fail = ratio < hard_threshold
    passed = ratio >= soft_threshold

    check = ValidityCheck(
        flag=FLAG_NOT_SENTENCES,
        label="문장 성립",
        passed=passed,
        hard=is_hard_fail,
        value=round(ratio, 4),
        threshold=hard_threshold if is_hard_fail else soft_threshold,
        # 소프트로 걸렸을 때는 '무슨 말을 했는지'를 보는 영역의 상태를 낮춘다
        affected_area=None if is_hard_fail else ScoreArea.CONTENT_TASK,
        components={
            "sentence_like_count": float(sentence_like),
            "sentence_count": float(total),
            "hard_threshold": hard_threshold,
            "soft_threshold": soft_threshold,
        },
    )
    if passed:
        return check

    if is_hard_fail:
        check.reason = (
            f"어미가 붙은 문장이 {sentence_like}/{total}뿐이라 "
            "낱말을 나열한 글로 보인다. 채점할 문장이 없어 무효로 처리했다."
        )
    else:
        check.reason = (
            f"어미가 붙은 문장이 {sentence_like}/{total}에 그쳐 "
            "온전한 문장으로 보기 어렵다."
        )

    # 근거: 어미가 없는 문장을 최대 세 개까지 원문 위치와 함께 보여 준다
    shown = 0
    for sentence in analysis.sentences:
        has_ending = any(token.tag in SENTENCE_ENDING_TAGS for token in sentence.tokens)
        if has_ending:
            continue
        check.evidence.append(
            _ev(analysis.text, sentence.start, min(sentence.end, sentence.start + 60),
                "어미(서술어)가 없어 문장으로 보기 어려운 조각",
                {"guard": FLAG_NOT_SENTENCES})
        )
        shown += 1
        if shown >= 3:
            break
    return check


# ---------------------------------------------------------------------------
# 바깥에서 부르는 진입점
# ---------------------------------------------------------------------------


def check_answer_validity(
    answer_text: str,
    item_prompt: str = "",
    analysis: Analysis | None = None,
) -> ValidityReport:
    """가드 네 개를 모두 돌려 답안이 채점 대상인지 판정한다.

    LLM은 한 번도 부르지 않는다. 그래서 무효 답안에 호출 비용을 쓰지 않고,
    같은 답안에는 언제나 같은 판정이 나온다.

    analysis 를 넘기면 형태소 분석을 다시 하지 않는다
    (파이프라인은 이미 분석해 둔 결과를 재사용한다).
    """
    # 가드 B, D 는 형태소 분석 결과가 필요하다. 한 번만 분석해 두 가드가 나눠 쓴다
    analysis = analysis or analyze(answer_text)

    return ValidityReport(
        checks=[
            check_korean_ratio(answer_text),
            check_min_length(analysis),
            check_prompt_overlap(answer_text, item_prompt),
            check_sentence_formation(analysis),
        ]
    )
