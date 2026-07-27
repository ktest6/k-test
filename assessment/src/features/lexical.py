"""Kiwi 형태소 분석으로 "셀 수 있는" 자질을 계산하는 모듈.

여기서 다루는 자질은 사람이 세어도 같은 값이 나오는 것들이다.
맥락 판단이 필요한 오류(조사가 틀렸는지 등)는 여기서 하지 않고 errors.py 가 맡는다.
이 경계를 지켜야 같은 답안을 두 번 채점해도 같은 값이 나온다.

형태소(形態素)란 뜻을 가진 가장 작은 말의 단위다.
'먹었습니다'는 '먹 + 었 + 습니다' 세 조각으로 쪼개진다.
Kiwi 는 이 조각내기를 해 주는 한국어 분석기이고, 각 조각에 품사 표시를 붙여 준다.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from kiwipiepy import Kiwi

from ..scoring.schema import Evidence, FeatureSource, FeatureStatus, FeatureValue, Mode

# ---------------------------------------------------------------------------
# 품사 표시(태그) 묶음
# ---------------------------------------------------------------------------

# 실질적인 뜻을 가진 말(내용어). 명사·동사·형용사·부사 등.
# '어휘 밀도'는 전체 말조각 중 이런 내용어가 얼마나 되는지를 본다.
CONTENT_TAGS = {
    "NNG",  # 일반 명사
    "NNP",  # 고유 명사
    "NR",   # 수사
    "VV",   # 동사
    "VA",   # 형용사
    "MAG",  # 일반 부사
    "MM",   # 관형사
    "XR",   # 어근
    "VV-I", "VV-R", "VA-I", "VA-R",  # 불규칙 활용 표시가 붙은 형태
}

# 문장부호·기호. 자질 계산에서 제외한다.
PUNCT_TAGS = {"SF", "SP", "SS", "SE", "SO", "SW", "SB", "SSO", "SSC"}

# 연결어미(EC): 문장을 이어 주는 어미. '-고', '-지만', '-아서' 등.
# 종류가 다양할수록 문장을 다채롭게 잇는다는 뜻으로 본다.
CONNECTIVE_ENDING_TAG = "EC"

# 절(節)을 만드는 어미들. 절이란 '주어+서술어'를 갖춘 덩어리다.
# 문장 하나에 절이 여러 개면 복잡한 문장을 쓴다는 신호다.
CLAUSE_TAGS = {"EC", "ETM", "ETN"}

# 종결어미(EF): 문장을 끝맺는 어미. 말투 판정의 핵심이다.
FINAL_ENDING_TAG = "EF"


# ---------------------------------------------------------------------------
# Kiwi 인스턴스와 어휘 등급 목록 (한 번만 만들어 재사용)
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def get_kiwi() -> Kiwi:
    """Kiwi 분석기를 만든다. 만드는 데 시간이 걸려서 한 번만 만들고 계속 쓴다."""
    return Kiwi()


# ※ 임시(TEMP) ※
# 국립국어원 '한국어 학습용 어휘 목록' 정식 데이터를 아직 확보하지 못했다.
# 지금은 직무 소통 맥락 어휘를 손으로 추린 씨앗 목록을 쓴다.
# 환경변수 KTEST_VOCAB_LEVELS 에 정식 목록 경로를 넣으면 그쪽을 읽는다.
_DEFAULT_VOCAB_PATH = Path(__file__).resolve().parent.parent / "resources" / "vocab_levels_ko.tsv"


@lru_cache(maxsize=4)
def load_vocab_levels(path: str | None = None) -> dict[str, str]:
    """어휘 등급 목록을 읽어 {표제어: 등급} 사전으로 만든다."""
    # 정식 목록 경로가 지정돼 있으면 그것을, 없으면 임시 씨앗 목록을 쓴다
    target = Path(path or os.getenv("KTEST_VOCAB_LEVELS") or _DEFAULT_VOCAB_PATH)
    levels: dict[str, str] = {}

    # 목록 파일이 아예 없어도 채점은 멈추지 않는다(고급 어휘 비율이 0으로 나올 뿐)
    if not target.exists():
        return levels

    for line in target.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        # 빈 줄과 '#'으로 시작하는 설명 줄은 건너뛴다
        if not line or line.startswith("#"):
            continue
        # 한 줄은 '낱말<탭>등급' 형태다. 형태가 깨진 줄은 조용히 넘긴다
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        levels[parts[0].strip()] = parts[1].strip().lower()
    return levels


def is_default_vocab_list() -> bool:
    """지금 쓰는 어휘 목록이 임시 씨앗 목록인지 알려준다(경고 문구용)."""
    return not os.getenv("KTEST_VOCAB_LEVELS")


# ---------------------------------------------------------------------------
# 분석 결과를 담는 중간 자료구조
# ---------------------------------------------------------------------------


@dataclass
class SentenceInfo:
    """문장 하나에 대한 분석 결과."""

    text: str
    start: int
    end: int
    tokens: list  # kiwipiepy.Token 목록
    register: str = "unknown"   # formal(합쇼체) / polite(해요체) / written(문어체 -다) / casual(반말)
    final_form: str = ""        # 판정 근거가 된 종결어미 모양


@dataclass
class Analysis:
    """답안 전체 분석 결과. 여러 자질이 이 값을 나눠 쓴다."""

    text: str
    tokens: list
    sentences: list[SentenceInfo]
    eojeols: list[str]          # 어절 = 띄어쓰기로 나뉜 덩어리

    @property
    def sentence_count(self) -> int:
        return max(1, len(self.sentences))

    @property
    def eojeol_count(self) -> int:
        return len(self.eojeols)


def analyze(text: str, kiwi: Kiwi | None = None) -> Analysis:
    """답안 텍스트를 한 번만 분석해서 여러 자질이 함께 쓸 결과를 만든다."""
    kiwi = kiwi or get_kiwi()

    # 답안을 말조각(형태소)으로 쪼갠다. 각 조각은 원문 몇 번째 글자에서 왔는지도 함께 알려준다
    tokens = list(kiwi.tokenize(text))
    # 어절 = 띄어쓰기로 나뉜 덩어리. '응답 길이'와 각종 비율의 분모로 쓴다
    eojeols = [w for w in re.split(r"\s+", text.strip()) if w]

    # 말투 판정과 '문장당 어절 수'를 내려면 문장 경계를 알아야 한다
    sentences: list[SentenceInfo] = []
    try:
        raw_sents = kiwi.split_into_sents(text)
    except Exception:
        # 문장 분리가 실패해도 채점을 멈추지 않는다. 아래에서 전체를 한 문장으로 처리한다
        raw_sents = []

    if raw_sents:
        for sent in raw_sents:
            # 전체 말조각 중 이 문장 범위 안에 들어가는 것만 골라 문장에 붙여 준다
            sent_tokens = [t for t in tokens if sent.start <= t.start < sent.end]
            info = SentenceInfo(
                text=sent.text, start=sent.start, end=sent.end, tokens=sent_tokens
            )
            # 문장마다 말투(합쇼체/해요체/반말)를 미리 가려 둔다
            info.register, info.final_form = classify_register(sent_tokens)
            sentences.append(info)
    elif text.strip():
        # 문장 분리가 실패하면 전체를 한 문장으로 본다
        # (문장 수가 0이 되면 나눗셈이 망가져서 자질 값이 통째로 죽는다)
        info = SentenceInfo(text=text, start=0, end=len(text), tokens=tokens)
        info.register, info.final_form = classify_register(tokens)
        sentences.append(info)

    return Analysis(text=text, tokens=tokens, sentences=sentences, eojeols=eojeols)


# ---------------------------------------------------------------------------
# 말투(문체) 판정
# ---------------------------------------------------------------------------

# 합쇼체: 가장 격식 있는 높임. '-습니다', '-ㅂ니까', '-십시오'.
_FORMAL_MARKERS = ("습니", "ᆸ니", "십시오", "ᆸ시다", "읍시다")
# 문어체 평서형: '-ㄴ다/-는다/-다'. 글에서는 정상이지만 말하기에서는 반말로 들린다.
_WRITTEN_PLAIN = {"ᆫ다", "는다", "다", "ᆫ다고", "란다"}


def classify_register(tokens: list) -> tuple[str, str]:
    """문장 하나의 말투를 가려낸다.

    문장 맨 끝의 말조각을 보고 판정한다.
    - formal  : 합쇼체 ('갔습니다')
    - polite  : 해요체 ('가요', '하세요', '그렇죠', '했는데요')
    - written : 문어체 평서형 ('간다') — 쓰기에서는 정상, 말하기에서는 반말로 센다
    - casual  : 반말 ('먹었어', '가자')
    """
    # 마침표·물음표는 말투와 상관없으므로 빼고 본다
    meaningful = [t for t in tokens if t.tag not in PUNCT_TAGS]
    if not meaningful:
        return "unknown", ""

    # 말투는 문장 끝에서 결정된다. 맨 마지막 말조각만 보면 된다
    last = meaningful[-1]

    # '했는데요'처럼 어미 뒤에 '요'가 덧붙어 높임이 되는 경우
    # 이때 마지막 조각은 종결어미가 아니라 조사(J로 시작)로 잡힌다
    if last.tag.startswith("J") and last.form == "요":
        return "polite", "요"

    # 종결어미 없이 끊긴 문장은 말하기에서 흔하다(중간에 말을 멈춘 경우 등)
    # 이런 문장에 반말이라고 벌점을 주면 억울하므로 판정을 보류한다
    if last.tag != FINAL_ENDING_TAG:
        return "unknown", last.form

    # 종결어미의 생김새로 말투를 가른다. 위에서부터 격식이 높은 순서다
    form = last.form
    if any(marker in form for marker in _FORMAL_MARKERS):
        return "formal", form
    if form.endswith("요") or form.endswith("죠"):
        return "polite", form
    if form in _WRITTEN_PLAIN:
        return "written", form

    # 위 어디에도 안 걸리면 '먹었어', '가자' 같은 반말이다
    return "casual", form


# ---------------------------------------------------------------------------
# 근거 만들기 도우미
# ---------------------------------------------------------------------------


def _ev(
    text: str,
    start: int | None,
    end: int | None,
    comment: str,
    detail: dict | None = None,
) -> Evidence:
    """원문 위치를 잘라서 근거 한 조각을 만든다."""
    # 위치가 이상하면(범위 밖이거나 뒤집혔으면) 인용은 비워 두고 설명만 남긴다
    # 근거랍시고 엉뚱한 글자를 보여 주는 것보다 낫다
    quote = ""
    if start is not None and end is not None and 0 <= start < end <= len(text):
        quote = text[start:end]
    return Evidence(
        source=FeatureSource.KIWI,
        quote=quote,
        start=start,
        end=end,
        comment=comment,
        detail=detail or {},
    )


def _snippet_span(text: str, center: int, width: int = 12) -> tuple[int, int]:
    """어떤 위치 주변을 조금 넓게 잘라 보여주기 위한 범위를 만든다."""
    return max(0, center - width), min(len(text), center + width)


# ---------------------------------------------------------------------------
# 개별 자질 계산
# ---------------------------------------------------------------------------


def _feature_response_length(a: Analysis) -> FeatureValue:
    """자질 1) 응답 길이 — 답안이 몇 어절인지.

    말을 충분히 했는지 자체가 과제 수행의 기본 조건이라 따로 센다.
    """
    count = a.eojeol_count
    # 근거로는 답안 앞 40자만 보여 준다(전문을 그대로 싣지 않기 위해)
    end = min(len(a.text), 40)
    return FeatureValue(
        id="response_length",
        name="응답 길이",
        source=FeatureSource.KIWI,
        value=float(count),
        unit="어절",
        components={
            "eojeol_count": float(count),
            "char_count": float(len(a.text)),
            "sentence_count": float(len(a.sentences)),
            "morpheme_count": float(len(a.tokens)),
        },
        evidence=[
            _ev(
                a.text,
                0,
                end,
                f"답안 전체 {count}어절, {len(a.sentences)}문장 (앞부분 표시)",
                {"eojeol_count": count},
            )
        ],
    )


def _feature_words_per_sentence(a: Analysis) -> FeatureValue:
    """자질 2) 문장당 어절 수 — 한 문장을 얼마나 길게 쓰는지."""
    value = a.eojeol_count / a.sentence_count

    # 평균값만 주면 "왜 이 숫자인가"를 알 수 없으므로
    # 가장 긴 문장과 가장 짧은 문장을 원문 위치와 함께 근거로 보여 준다
    evidence: list[Evidence] = []
    if a.sentences:
        lengths = [(len([w for w in re.split(r"\s+", s.text.strip()) if w]), s) for s in a.sentences]
        longest = max(lengths, key=lambda x: x[0])
        shortest = min(lengths, key=lambda x: x[0])
        evidence.append(
            _ev(a.text, longest[1].start, longest[1].end,
                f"가장 긴 문장 ({longest[0]}어절)", {"eojeols": longest[0]})
        )
        # 문장이 하나뿐이면 가장 긴 문장과 짧은 문장이 같아지므로 중복해서 넣지 않는다
        if shortest[1] is not longest[1]:
            evidence.append(
                _ev(a.text, shortest[1].start, shortest[1].end,
                    f"가장 짧은 문장 ({shortest[0]}어절)", {"eojeols": shortest[0]})
            )

    return FeatureValue(
        id="words_per_sentence",
        name="문장당 어절 수",
        source=FeatureSource.KIWI,
        value=round(value, 3),
        unit="어절/문장",
        components={
            "eojeol_count": float(a.eojeol_count),
            "sentence_count": float(a.sentence_count),
        },
        evidence=evidence,
    )


def _feature_mattr(a: Analysis, window: int = 25) -> FeatureValue:
    """자질 3) 어휘 다양도 (MATTR).

    같은 단어를 반복하지 않고 여러 단어를 쓰는지를 본다.
    TTR(서로 다른 단어 수 ÷ 전체 단어 수)은 글이 길어질수록 낮아지는 성질이 있어서
    답안 길이에 따라 점수가 흔들린다. 그래서 일정 크기의 '창'을 한 칸씩 밀며
    구간마다 TTR을 재고 평균 내는 MATTR을 쓴다(길이 영향이 작다).
    """
    # 문장부호는 어휘가 아니므로 세는 대상에서 뺀다
    # 같은 글자라도 품사가 다르면 다른 낱말로 보기 위해 (모양, 품사) 짝으로 다룬다
    items = [(t.form, t.tag, t.start, t.len) for t in a.tokens if t.tag not in PUNCT_TAGS]
    n = len(items)

    # 셀 것이 하나도 없으면 값을 지어내지 않고 '못 구했음'으로 표시한다
    if n == 0:
        return FeatureValue(
            id="lexical_diversity_mattr",
            name="어휘 다양도(MATTR)",
            source=FeatureSource.KIWI,
            value=None,
            unit="0~1",
            status=FeatureStatus.UNAVAILABLE,
            note="분석할 말조각이 없어 계산하지 못했다.",
        )

    # 답안이 창 크기보다 짧으면 창을 답안 길이에 맞춰 줄인다(그래야 계산이 성립한다)
    effective_window = min(window, n)

    # 창을 한 칸씩 오른쪽으로 밀면서, 창 안에 서로 다른 낱말이 몇 종류인지 매번 잰다
    ratios: list[float] = []
    for i in range(0, n - effective_window + 1):
        chunk = items[i : i + effective_window]
        types = {(f, tag) for f, tag, _, _ in chunk}
        ratios.append(len(types) / effective_window)
    # 구간마다 잰 값을 평균 내면 답안 길이의 영향이 거의 사라진다
    value = sum(ratios) / len(ratios)

    # 여기부터는 근거 만들기다.
    # "다양도가 낮다"고만 하면 응시자가 납득할 수 없으니
    # 실제로 되풀이된 낱말이 원문 어디에 나오는지 짚어 준다
    counts: dict[tuple[str, str], list[int]] = {}
    for form, tag, start, length in items:
        counts.setdefault((form, tag), []).append(start)
    # 두 번 이상 나온 낱말 중 많이 나온 순으로 세 개만 고른다
    repeated = sorted(
        (kv for kv in counts.items() if len(kv[1]) >= 2),
        key=lambda kv: -len(kv[1]),
    )[:3]

    evidence: list[Evidence] = []
    for (form, tag), positions in repeated:
        # 낱말 하나만 보여 주면 맥락을 알 수 없어 주변까지 조금 넓게 잘라 준다
        s, e = _snippet_span(a.text, positions[0])
        evidence.append(
            _ev(a.text, s, e,
                f"'{form}'({tag})가 {len(positions)}번 되풀이됨",
                {"repeat_count": len(positions), "positions": positions[:8]})
        )
    if not evidence:
        evidence.append(
            _ev(a.text, 0, min(len(a.text), 40), "되풀이된 말조각 없음", {})
        )

    return FeatureValue(
        id="lexical_diversity_mattr",
        name="어휘 다양도(MATTR)",
        source=FeatureSource.KIWI,
        value=round(value, 4),
        unit="0~1 (높을수록 다양)",
        components={
            "window": float(effective_window),
            "token_count": float(n),
            "type_count": float(len(counts)),
            "plain_ttr": round(len(counts) / n, 4),
        },
        evidence=evidence,
    )


def _feature_advanced_vocab(a: Analysis) -> FeatureValue:
    """자질 4) 국립국어원 등급별 고급 어휘 비율.

    쉬운 말만 쓰는지, 격이 높은 말도 쓰는지를 본다.
    """
    levels = load_vocab_levels()
    # 조사나 어미는 등급을 매길 대상이 아니므로 뜻을 가진 낱말만 분모로 삼는다
    content_tokens = [t for t in a.tokens if t.tag in CONTENT_TAGS]
    denom = len(content_tokens)

    # 내용어가 하나도 없으면 비율을 낼 수 없다. 0으로 때우지 않고 '못 구했음'으로 둔다
    if denom == 0:
        return FeatureValue(
            id="advanced_vocab_ratio",
            name="고급 어휘 비율",
            source=FeatureSource.KIWI,
            value=None,
            unit="0~1",
            status=FeatureStatus.UNAVAILABLE,
            note="내용어가 없어 계산하지 못했다.",
        )

    # 등급별로 몇 개씩 나왔는지 세면서, 고급 어휘는 위치까지 따로 챙겨 둔다
    per_level = {"beginner": 0, "intermediate": 0, "advanced": 0, "unlisted": 0}
    advanced_hits: list[tuple[str, int, int]] = []
    for t in content_tokens:
        # 목록에는 동사·형용사가 '먹다', '좋다'처럼 '-다' 꼴로 실려 있는데
        # Kiwi가 준 조각은 '먹', '좋' 이라서 '다'를 붙인 형태도 함께 찾아본다
        candidates = [t.form]
        if t.tag.startswith("VV") or t.tag.startswith("VA"):
            candidates.append(t.form + "다")

        level = None
        for cand in candidates:
            if cand in levels:
                level = levels[cand]
                break

        # 목록에 없는 낱말은 '등급 미상'으로 따로 센다(분모에는 포함된다)
        if level in per_level:
            per_level[level] += 1
        else:
            per_level["unlisted"] += 1

        if level == "advanced":
            advanced_hits.append((t.form, t.start, t.start + t.len))

    value = per_level["advanced"] / denom

    evidence = [
        _ev(a.text, *_snippet_span(a.text, start), f"고급 어휘 '{form}' 사용", {"lemma": form})
        for form, start, _ in advanced_hits[:5]
    ]
    if not evidence:
        evidence.append(
            _ev(a.text, 0, min(len(a.text), 40),
                "목록에 등재된 고급 어휘가 발견되지 않음",
                {"content_token_count": denom})
        )

    # 임시 목록을 쓰는 중이라면 그 사실을 값과 함께 실어 보낸다
    # 보고서에 이 숫자가 절대 기준처럼 실리는 것을 막기 위해서다
    note = ""
    if is_default_vocab_list():
        note = (
            "※ 임시 ※ 국립국어원 정식 어휘 등급 목록 대신 씨앗 목록을 쓰고 있어 "
            "절대값은 신뢰할 수 없다. 답안 사이 비교 용도로만 쓸 것."
        )

    return FeatureValue(
        id="advanced_vocab_ratio",
        name="고급 어휘 비율",
        source=FeatureSource.KIWI,
        value=round(value, 4),
        unit="0~1 (내용어 중 고급 어휘 비중)",
        components={
            "advanced": float(per_level["advanced"]),
            "intermediate": float(per_level["intermediate"]),
            "beginner": float(per_level["beginner"]),
            "unlisted": float(per_level["unlisted"]),
            "content_token_count": float(denom),
        },
        evidence=evidence,
        note=note,
    )


def _feature_lexical_density(a: Analysis) -> FeatureValue:
    """자질 5) 어휘 밀도 — 전체 말조각 중 뜻을 가진 말(내용어)의 비중.

    '그거 좀 그렇게 해 주세요'처럼 내용 없는 말로 채우면 이 값이 낮아진다.
    """
    # 전체 말조각(문장부호 제외) 중에서 뜻을 가진 것이 몇 개인지 비율을 낸다
    total = [t for t in a.tokens if t.tag not in PUNCT_TAGS]
    content = [t for t in total if t.tag in CONTENT_TAGS]
    if not total:
        return FeatureValue(
            id="lexical_density",
            name="어휘 밀도",
            source=FeatureSource.KIWI,
            value=None,
            unit="0~1",
            status=FeatureStatus.UNAVAILABLE,
            note="분석할 말조각이 없어 계산하지 못했다.",
        )

    value = len(content) / len(total)
    # 근거로는 실제로 내용어로 잡힌 낱말 몇 개를 원문 위치와 함께 보여 준다
    evidence = [
        _ev(a.text, t.start, t.start + t.len, f"내용어 '{t.form}'({t.tag})")
        for t in content[:4]
    ]
    if not evidence:
        evidence.append(_ev(a.text, 0, min(len(a.text), 40), "내용어가 발견되지 않음"))

    return FeatureValue(
        id="lexical_density",
        name="어휘 밀도",
        source=FeatureSource.KIWI,
        value=round(value, 4),
        unit="0~1 (높을수록 내용어 비중이 큼)",
        components={
            "content_token_count": float(len(content)),
            "total_token_count": float(len(total)),
        },
        evidence=evidence,
    )


def _feature_clause_density(a: Analysis) -> FeatureValue:
    """자질 6) 절 밀도 — 문장 하나에 절이 몇 개 들어 있는지.

    절이란 '주어+서술어'를 갖춘 덩어리다.
    '비가 와서 늦었습니다'는 절이 둘이고, '늦었습니다'는 절이 하나다.
    절을 여러 개 엮을수록 복잡한 문장을 만들 수 있다는 뜻으로 본다.
    """
    # 절을 만드는 어미(잇는 어미, 꾸미는 어미, 명사로 만드는 어미)를 모두 찾는다
    clause_markers = [t for t in a.tokens if t.tag in CLAUSE_TAGS]
    # 문장마다 중심이 되는 절이 하나씩 있으므로 문장 수를 더해야 실제 절 개수가 된다
    clause_count = len(clause_markers) + len(a.sentences)
    value = clause_count / a.sentence_count

    # 어떤 어미 때문에 절이 늘었는지 원문 위치와 함께 보여 준다
    evidence = [
        _ev(a.text, *_snippet_span(a.text, t.start, 10),
            f"절을 만드는 어미 '{t.form}'({t.tag})")
        for t in clause_markers[:4]
    ]
    if not evidence:
        evidence.append(
            _ev(a.text, 0, min(len(a.text), 40),
                "절을 잇는 어미가 없어 홑문장으로만 이루어짐")
        )

    return FeatureValue(
        id="clause_density",
        name="절 밀도",
        source=FeatureSource.KIWI,
        value=round(value, 3),
        unit="절/문장",
        components={
            "clause_marker_count": float(len(clause_markers)),
            "sentence_count": float(a.sentence_count),
            "clause_count": float(clause_count),
        },
        evidence=evidence,
    )


def _feature_connective_diversity(a: Analysis) -> FeatureValue:
    """자질 7) 연결어미 다양성.

    '-고'만 되풀이해서 문장을 잇는지, '-지만·-아서·-는데'처럼 여러 방식으로 잇는지를 본다.
    """
    ecs = [t for t in a.tokens if t.tag == CONNECTIVE_ENDING_TAG]
    # 연결어미가 아예 없으면 나눗셈이 불가능하다.
    # 이 경우는 '잇는 방식이 하나도 없는' 상태이므로 0으로 두는 것이 뜻에 맞는다
    if not ecs:
        return FeatureValue(
            id="connective_ending_diversity",
            name="연결어미 다양성",
            source=FeatureSource.KIWI,
            value=0.0,
            unit="0~1 (서로 다른 연결어미 비율)",
            components={"connective_count": 0.0, "unique_connective_count": 0.0},
            evidence=[
                _ev(a.text, 0, min(len(a.text), 40),
                    "연결어미가 하나도 쓰이지 않아 0으로 둔다")
            ],
            note="연결어미가 없으면 다양성도 0으로 본다.",
        )

    # 서로 다른 연결어미가 전체 연결어미 중 몇 %인지를 본다
    # '-고'만 열 번 쓰면 0.1, 열 번 다 다르게 쓰면 1.0 이 된다
    unique = {t.form for t in ecs}
    value = len(unique) / len(ecs)

    # 근거로는 '어떤 종류를 썼는지'가 중요하므로 같은 어미는 한 번만 보여 준다
    seen: set[str] = set()
    evidence: list[Evidence] = []
    for t in ecs:
        if t.form in seen:
            continue
        seen.add(t.form)
        evidence.append(
            _ev(a.text, *_snippet_span(a.text, t.start, 10), f"연결어미 '{t.form}'")
        )
        if len(evidence) >= 5:
            break

    return FeatureValue(
        id="connective_ending_diversity",
        name="연결어미 다양성",
        source=FeatureSource.KIWI,
        value=round(value, 4),
        unit="0~1 (서로 다른 연결어미 비율)",
        components={
            "connective_count": float(len(ecs)),
            "unique_connective_count": float(len(unique)),
        },
        evidence=evidence,
    )


def _feature_formality(a: Analysis, mode: Mode) -> FeatureValue:
    """자질 8) 격식체 비율 · 반말 혼입 횟수.

    직무 현장에서 상사·고객에게 반말이 섞이면 그 자체가 큰 감점 사유다.
    영어권 시험에는 없는, 이 시험만의 평가 항목이라 축소하지 않는다.

    value 는 '높임 종결(합쇼체+해요체) 비율'이고,
    반말 혼입 횟수는 components 의 banmal_count 에 함께 담는다.
    """
    # 문장마다 미리 매겨 둔 말투를 종류별로 센다
    counts = {"formal": 0, "polite": 0, "written": 0, "casual": 0, "unknown": 0}
    for s in a.sentences:
        counts[s.register] = counts.get(s.register, 0) + 1

    # 말하기에서 '-ㄴ다/-는다'로 끝내면 반말로 들린다.
    # 쓰기에서는 문어체 평서형이라 정상이다. 그래서 mode 에 따라 다르게 센다
    if mode == Mode.SPEAKING:
        banmal_count = counts["casual"] + counts["written"]
    else:
        banmal_count = counts["casual"]

    # 말투를 판정하지 못한 문장(unknown)은 분모에서 뺀다.
    # 말을 하다 만 문장 때문에 격식체 비율이 낮아지면 억울하기 때문이다
    judged = counts["formal"] + counts["polite"] + counts["written"] + counts["casual"]
    value = (counts["formal"] + counts["polite"]) / judged if judged else None

    # 근거는 반말이 섞인 문장을 우선해서 보여 준다. 감점 사유를 먼저 알려야 하기 때문이다
    evidence: list[Evidence] = []
    for s in a.sentences:
        is_banmal = s.register == "casual" or (
            mode == Mode.SPEAKING and s.register == "written"
        )
        if is_banmal:
            evidence.append(
                _ev(a.text, s.start, s.end,
                    f"반말 혼입: 종결어미 '{s.final_form}' ({s.register})",
                    {"register": s.register, "final_ending": s.final_form})
            )
        if len(evidence) >= 5:
            break
    # 반말이 하나도 없다면 대신 '높임을 잘 지킨 문장'을 근거로 보여 준다
    # 근거가 비어 있는 자질을 만들지 않기 위해서다
    if not evidence:
        formal_sents = [s for s in a.sentences if s.register in ("formal", "polite")]
        if formal_sents:
            s = formal_sents[0]
            evidence.append(
                _ev(a.text, s.start, s.end,
                    f"높임 종결 유지: '{s.final_form}' ({s.register})",
                    {"register": s.register})
            )
        else:
            evidence.append(
                _ev(a.text, 0, min(len(a.text), 40), "종결어미를 판정할 수 없는 답안")
            )

    status = FeatureStatus.OK if judged else FeatureStatus.UNAVAILABLE
    return FeatureValue(
        id="formality",
        name="격식체 비율·반말 혼입",
        source=FeatureSource.KIWI,
        value=round(value, 4) if value is not None else None,
        unit="0~1 (높임 종결 비율)",
        status=status,
        components={
            "formal_count": float(counts["formal"]),
            "polite_count": float(counts["polite"]),
            "written_plain_count": float(counts["written"]),
            "casual_count": float(counts["casual"]),
            "unknown_count": float(counts["unknown"]),
            "banmal_count": float(banmal_count),
            "judged_sentence_count": float(judged),
        },
        evidence=evidence,
        note="말하기에서는 '-ㄴ다/-는다' 종결도 반말 혼입으로 센다(쓰기에서는 문어체로 인정).",
    )


def _feature_subject_honorific(a: Analysis) -> FeatureValue:
    """자질 9) 주체 높임 '-시-' 빈도.

    '사장님이 오셨습니다'의 '-시-'처럼, 문장의 주인공을 높이는 표시를 얼마나 쓰는지 본다.
    답안 길이에 흔들리지 않도록 100어절당 횟수로 환산한다.
    """
    # '-시-'는 선어말어미(EP)로 잡힌다. '오셨습니다'의 '시'가 여기 해당한다
    si_tokens = [t for t in a.tokens if t.tag.startswith("EP") and t.form in ("시", "으시")]
    # 긴 답안일수록 횟수가 많아지는 것은 당연하므로, 길이로 나눠 100어절 기준으로 맞춘다
    per_100 = (len(si_tokens) / a.eojeol_count * 100) if a.eojeol_count else 0.0

    evidence = [
        _ev(a.text, *_snippet_span(a.text, t.start, 10), "주체 높임 '-시-' 사용")
        for t in si_tokens[:4]
    ]
    if not evidence:
        evidence.append(
            _ev(a.text, 0, min(len(a.text), 40), "주체 높임 '-시-'가 한 번도 쓰이지 않음")
        )

    return FeatureValue(
        id="subject_honorific_si",
        name="주체 높임 '-시-' 빈도",
        source=FeatureSource.KIWI,
        value=round(per_100, 3),
        unit="100어절당 횟수",
        components={
            "si_count": float(len(si_tokens)),
            "eojeol_count": float(a.eojeol_count),
        },
        evidence=evidence,
    )


# ---------------------------------------------------------------------------
# 띄어쓰기 대조 (쓰기 전용 자질)
# ---------------------------------------------------------------------------


@dataclass
class SpacingDiff:
    """띄어쓰기가 어긋난 자리 하나."""

    kind: str        # "붙여야 함" 또는 "띄어야 함"
    position: int    # 원문에서의 위치


def compare_spacing(original: str, corrected: str) -> list[SpacingDiff] | None:
    """원문과 Kiwi 가 교정한 문장을 나란히 훑어 띄어쓰기가 다른 자리를 찾는다.

    공백을 뺀 글자열이 서로 다르면(=Kiwi 가 글자까지 바꿨으면) 위치를 맞출 수 없으므로
    None 을 돌려주고 이 자질은 계산하지 않는다.
    """
    # 공백을 모두 뺀 글자열이 서로 달라졌다면 교정기가 글자까지 손댄 것이다.
    # 그러면 어느 자리가 어긋났는지 짚을 수 없으므로 이 자질은 포기한다
    if re.sub(r"\s+", "", original) != re.sub(r"\s+", "", corrected):
        return None

    # 원문과 교정문을 각각 손가락으로 짚어 가며 나란히 훑는다
    diffs: list[SpacingDiff] = []
    oi = ci = 0
    while oi < len(original) and ci < len(corrected):
        o_space = original[oi].isspace()
        c_space = corrected[ci].isspace()

        if o_space and c_space:
            # 양쪽 다 공백이면 맞게 띄어 쓴 자리다. 둘 다 다음으로 넘어간다
            oi += 1
            ci += 1
        elif o_space and not c_space:
            # 원문에만 공백이 있다 = 붙여 써야 할 자리를 띄었다
            # 원문 쪽 손가락만 넘겨서 글자 짝이 계속 맞도록 한다
            diffs.append(SpacingDiff("붙여야 함", oi))
            oi += 1
        elif c_space and not o_space:
            # 교정문에만 공백이 있다 = 띄어 써야 할 자리를 붙였다
            diffs.append(SpacingDiff("띄어야 함", oi))
            ci += 1
        else:
            # 양쪽 다 글자면 같은 글자이므로(위에서 확인했다) 그냥 함께 넘어간다
            oi += 1
            ci += 1
    return diffs


def _feature_spacing(a: Analysis, kiwi: Kiwi) -> FeatureValue:
    """자질 14) 띄어쓰기 오류 (쓰기 전용).

    Kiwi 의 띄어쓰기 교정 결과와 응시자가 쓴 원문을 대조해 어긋난 자리를 센다.
    맞춤법과 달리 기계적으로 셀 수 있어 LLM에 맡기지 않는다.
    """
    # Kiwi에게 "네가 보기에 올바른 띄어쓰기로 다시 써 봐라"라고 시킨다
    try:
        corrected = kiwi.space(a.text)
    except Exception as exc:  # pragma: no cover
        return FeatureValue(
            id="spacing_error_rate",
            name="띄어쓰기 오류율",
            source=FeatureSource.KIWI,
            value=None,
            status=FeatureStatus.UNAVAILABLE,
            note=f"띄어쓰기 교정에 실패했다: {exc}",
        )

    diffs = compare_spacing(a.text, corrected)
    if diffs is None:
        return FeatureValue(
            id="spacing_error_rate",
            name="띄어쓰기 오류율",
            source=FeatureSource.KIWI,
            value=None,
            status=FeatureStatus.UNAVAILABLE,
            note="교정 결과가 원문의 글자까지 바꿔서 위치를 맞출 수 없었다.",
        )

    # 긴 글일수록 오류가 많아지는 것은 당연하므로 어절 수로 나눠 비율로 만든다
    denom = max(1, a.eojeol_count)
    value = len(diffs) / denom

    # 오류가 많아도 근거는 앞의 다섯 개만 보여 준다(응답이 지나치게 길어지지 않게)
    evidence: list[Evidence] = []
    for d in diffs[:5]:
        s, e = _snippet_span(a.text, d.position, 8)
        evidence.append(
            _ev(a.text, s, e, f"띄어쓰기 오류({d.kind})", {"kind": d.kind, "position": d.position})
        )
    if not evidence:
        evidence.append(
            _ev(a.text, 0, min(len(a.text), 40), "띄어쓰기 오류가 발견되지 않음")
        )

    return FeatureValue(
        id="spacing_error_rate",
        name="띄어쓰기 오류율",
        source=FeatureSource.KIWI,
        value=round(value, 4),
        unit="어절당 오류 수",
        components={
            "error_count": float(len(diffs)),
            "eojeol_count": float(a.eojeol_count),
        },
        evidence=evidence,
    )


# ---------------------------------------------------------------------------
# 바깥에서 부르는 진입점
# ---------------------------------------------------------------------------

#: 이 모듈이 만드는 규칙 자질의 식별자 목록(순서 고정).
KIWI_FEATURE_IDS = [
    "lexical_diversity_mattr",
    "advanced_vocab_ratio",
    "lexical_density",
    "response_length",
    "words_per_sentence",
    "clause_density",
    "connective_ending_diversity",
    "formality",
    "subject_honorific_si",
]
WRITING_ONLY_KIWI_FEATURE_IDS = ["spacing_error_rate"]


def extract_lexical_features(
    text: str,
    mode: Mode = Mode.SPEAKING,
    kiwi: Kiwi | None = None,
) -> list[FeatureValue]:
    """답안 텍스트에서 규칙 자질을 모두 뽑아낸다.

    쓰기(mode=writing)일 때만 띄어쓰기 자질이 하나 더 붙는다.
    """
    # 형태소 분석은 한 번만 하고 그 결과를 모든 자질이 나눠 쓴다(같은 일을 열 번 하지 않기 위해)
    kiwi = kiwi or get_kiwi()
    a = analyze(text, kiwi)

    # 자질 순서는 scoring-design 스킬에 적힌 목록 순서를 그대로 따른다
    features = [
        _feature_mattr(a),
        _feature_advanced_vocab(a),
        _feature_lexical_density(a),
        _feature_response_length(a),
        _feature_words_per_sentence(a),
        _feature_clause_density(a),
        _feature_connective_diversity(a),
        _feature_formality(a, mode),
        _feature_subject_honorific(a),
    ]

    if mode == Mode.WRITING:
        features.append(_feature_spacing(a, kiwi))
    else:
        # 말하기는 STT(음성을 글자로 옮기는 기계)가 띄어쓰기를 정하므로
        # 여기서 감점하면 응시자가 하지 않은 잘못을 채점하게 된다.
        # 값을 빼지 않고 '해당 없음'으로 남겨야 응답 구조가 모드에 따라 흔들리지 않는다
        features.append(
            FeatureValue(
                id="spacing_error_rate",
                name="띄어쓰기 오류율",
                source=FeatureSource.KIWI,
                value=None,
                status=FeatureStatus.NOT_APPLICABLE,
                note="말하기 답안은 STT 전사 결과이므로 띄어쓰기를 채점하지 않는다.",
            )
        )

    return features
