"""Kiwi 규칙 자질 회귀 테스트.

채점 로직은 눈으로 훑어서 맞는지 알기 어렵다.
그래서 '값이 나오는가'뿐 아니라 '값의 방향이 상식적인가'까지 못 박아 둔다.
(잘 쓴 답안이 못 쓴 답안보다 어휘 다양도가 높아야 한다 같은 것)

실행: .venv\\Scripts\\python.exe -m pytest tests -q
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.features.lexical import (  # noqa: E402
    analyze,
    classify_register,
    compare_spacing,
    extract_lexical_features,
    get_kiwi,
)
from src.scoring.schema import FeatureStatus, Mode  # noqa: E402

GOOD = (
    "지난주 화요일 오전에 3번 라인 포장 기계가 갑자기 멈췄습니다. "
    "저는 먼저 전원을 차단하고 동료들에게 접근하지 말라고 알렸습니다. "
    "그다음 반장님께 보고드렸고, 반장님이 오셔서 함께 원인을 파악했습니다. "
    "재발을 막기 위해 매일 점검하는 절차를 새로 만들었습니다."
)

BAD = (
    "기계가 고장 났어요. 그래서 기계를 봤어요. 기계가 안 돼요. "
    "그래서 사람을 불렀어요. 사람이 기계를 고쳤어. 그래서 기계가 됐어."
)


def features_of(text: str, mode: Mode = Mode.SPEAKING) -> dict:
    return {f.id: f for f in extract_lexical_features(text, mode)}


def test_자질이_전부_계산되고_근거가_붙는다():
    features = extract_lexical_features(GOOD, Mode.SPEAKING)
    # 공통 9종 + 띄어쓰기 자리 1종
    assert len(features) == 10
    for f in features:
        if f.status == FeatureStatus.OK:
            assert f.value is not None
            # 근거 없는 자질은 만들지 않는다는 것이 이 프로젝트의 원칙이다
            assert f.evidence, f"{f.id} 에 근거가 없다"


def test_잘_쓴_답안이_어휘_다양도가_더_높다():
    good, bad = features_of(GOOD), features_of(BAD)
    assert good["lexical_diversity_mattr"].value > bad["lexical_diversity_mattr"].value


def test_잘_쓴_답안이_어휘_밀도와_절_밀도가_더_높다():
    good, bad = features_of(GOOD), features_of(BAD)
    assert good["lexical_density"].value > bad["lexical_density"].value
    assert good["clause_density"].value > bad["clause_density"].value


def test_고급_어휘는_잘_쓴_답안에서만_잡힌다():
    good, bad = features_of(GOOD), features_of(BAD)
    assert good["advanced_vocab_ratio"].value > 0
    assert bad["advanced_vocab_ratio"].value == 0


def test_반말_혼입이_잡히고_근거에_문장이_남는다():
    bad = features_of(BAD)["formality"]
    assert bad.components["banmal_count"] > 0
    # 반말로 지목한 문장이 원문에 실제로 있어야 한다
    quotes = [ev.quote for ev in bad.evidence if ev.quote]
    assert quotes
    assert all(q in BAD for q in quotes)

    good = features_of(GOOD)["formality"]
    assert good.components["banmal_count"] == 0


def test_주체높임_시가_잡힌다():
    good = features_of(GOOD)["subject_honorific_si"]
    assert good.components["si_count"] > 0


def test_말하기에서는_띄어쓰기를_채점하지_않는다():
    # STT가 정한 띄어쓰기로 응시자를 감점하면 안 된다
    f = features_of(GOOD, Mode.SPEAKING)["spacing_error_rate"]
    assert f.status == FeatureStatus.NOT_APPLICABLE
    assert f.value is None


def test_쓰기에서는_띄어쓰기_오류가_잡힌다():
    text = "저는즉시 전원을차단하고 반장님께 보고했습니다."
    f = features_of(text, Mode.WRITING)["spacing_error_rate"]
    assert f.status == FeatureStatus.OK
    assert f.components["error_count"] > 0


def test_띄어쓰기_대조는_글자가_바뀌면_포기한다():
    # 글자까지 달라지면 위치를 맞출 수 없으므로 None 을 돌려줘야 한다
    assert compare_spacing("기계가 멈췄다", "기계가 멈추었다") is None
    # 공백만 다르면 정상적으로 어긋난 자리를 찾아낸다
    diffs = compare_spacing("저는즉시 갔다", "저는 즉시 갔다")
    assert diffs is not None and len(diffs) == 1


def test_문장별_말투_판정():
    kiwi = get_kiwi()

    def register(sentence: str) -> str:
        return classify_register(list(kiwi.tokenize(sentence)))[0]

    assert register("저는 갔습니다.") == "formal"
    assert register("저는 가요.") == "polite"
    assert register("했는데요.") == "polite"
    assert register("밥 먹었어.") == "casual"
    assert register("그는 간다.") == "written"


def test_말하기와_쓰기의_문어체_처리가_다르다():
    text = "기계가 고장 났다. 나는 전원을 차단했다."
    # 쓰기에서는 '-다' 종결이 정상이다
    assert features_of(text, Mode.WRITING)["formality"].components["banmal_count"] == 0
    # 말하기에서는 반말로 들리므로 혼입으로 센다
    assert features_of(text, Mode.SPEAKING)["formality"].components["banmal_count"] > 0


def test_빈_답안이어도_터지지_않는다():
    features = extract_lexical_features("", Mode.SPEAKING)
    assert len(features) == 10
    # 값을 지어내지 않고 '못 구했음'으로 표시되어야 한다
    assert features_of("")["lexical_diversity_mattr"].status == FeatureStatus.UNAVAILABLE


def test_분석_결과가_문장과_어절을_제대로_센다():
    a = analyze("기계가 멈췄습니다. 저는 보고했습니다.")
    assert len(a.sentences) == 2
    assert a.eojeol_count == 4
