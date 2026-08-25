"""발음 자질을 만드는 파일. **음성을 직접 들은 기계(Azure)가 준 값만 옮긴다.**

이 파일이 하는 일은 계산이 아니라 '옮겨 적기'다.
발음 점수는 우리가 만들 수 없다 — 소리를 들어야 나오는 값이고, 그것을 하는 것은
Azure 발음 평가다(음성 모듈의 AzureStt). 여기서는 그 결과를 채점기가 쓰는
모양(FeatureValue)으로 바꾸고, **어느 낱말 때문에 점수가 깎였는지 근거를 붙인다.**

왜 features/ 안의 별도 파일인가:
자질을 만드는 곳은 셋으로 나뉘어 있다 — 규칙(lexical.py), LLM 판단(errors.py),
그리고 발음(이 파일)이다. 이 경계가 재현성을 만든다(scoring-design 참고).
규칙 자질과 섞으면 "이 값을 누가 만들었나"를 나중에 알 수 없게 된다.

만드는 자질 다섯 (전부 source=azure):

    pron_accuracy      발음 정확도      소리를 얼마나 정확히 냈는가
    pron_fluency       발화 유창성      끊김 없이 이어 말했는가
    pron_completeness  발화 완전성      읽어야 할 말 중 얼마나 말했는가
    pron_prosody       억양·강세        (한국어는 값이 오지 않는다 — 기록만 남긴다)
    pron_overall       발음 종합        위 셋을 Azure 가 자기 방식으로 합친 값

**pron_overall 은 점수 계산에 쓰지 않는다.** 나머지 셋을 합친 값이라 함께 넣으면
같은 것을 두 번 세게 된다. 대신 Azure 가 매긴 값이 얼마였는지 대조할 수 있도록
결과에는 남긴다(우리 계산이 Azure 와 얼마나 다른지 확인하는 자리다).

**pron_completeness 는 낭독형 문항에서만 채점에 쓴다.** 자유 발화에는 '읽어야 할
원문'이 없어서 '얼마나 말했는가'의 기준이 없기 때문이다. 그때는 값이 와도
not_applicable 로 두어 점수에서 조용히 빠지게 한다.
"""

from __future__ import annotations

# 발음 평가 결과의 모양도 여기(scoring/schema.py)에 있다.
# 음성 모듈을 직접 부르지 않는 이유:
# 채점 자질 쪽이 받아쓰기 모듈을 붙잡으면 '음성 기능을 붙였다고 채점이 달라지지
# 않는다'가 성립하지 않는다. 두 쪽이 다 아는 파일 하나만 읽는다.
from ..scoring.schema import (
    Evidence,
    FeatureSource,
    FeatureStatus,
    FeatureValue,
    PronouncedWord,
    PronunciationAssessment,
)

#: 근거로 남길 '못 알아들은 낱말'의 기준 점수. 이보다 낮은 낱말만 근거에 적는다.
#: ※ 임시값 ※ 실제 응시자 분포를 보고 다시 잡아야 한다.
LOW_WORD_ACCURACY = 60.0

#: 근거로 남길 낱말의 최대 개수. 전부 적으면 응답이 길어지기만 한다
MAX_LOW_WORD_EVIDENCE = 8

#: Azure 가 낱말에 붙이는 표시를 사람이 읽는 말로 바꾸는 표
ERROR_TYPE_LABELS = {
    "None": "정상",
    "Mispronunciation": "잘못 발음함",
    "Omission": "빠뜨림",
    "Insertion": "제시문에 없는 말을 넣음",
    "UnexpectedBreak": "끊어 읽지 말아야 할 자리에서 끊음",
    "MissingBreak": "끊어 읽어야 할 자리에서 안 끊음",
    "Monotone": "억양 변화가 거의 없음",
}


def find_quote_span(text: str, quote: str) -> tuple[int | None, int | None]:
    """받아쓴 글에서 이 낱말이 어디 있는지 찾는다.

    근거(Evidence)에는 인용만이 아니라 원문에서의 위치도 남긴다.
    그래야 화면에서 그 자리를 짚어 보여 줄 수 있다.
    못 찾으면 위치를 지어내지 않고 None 을 돌려준다
    (낭독형은 받아쓴 글과 낱말 표기가 어긋날 수 있어서 못 찾는 경우가 있다).
    """
    if not quote:
        return None, None
    start = text.find(quote)
    if start < 0:
        return None, None
    return start, start + len(quote)


def _low_word_evidence(
    words: list[PronouncedWord], transcript: str
) -> list[Evidence]:
    """점수가 낮은 낱말들을 근거로 만든다.

    **여기가 이 파일의 핵심이다.** "발음 57점"만 주면 응시자는 무엇을 고쳐야 할지
    알 수 없다. 어느 낱말이 몇 점이었는지가 있어야 점수를 설명할 수 있다.

    낮은 것부터 늘어놓아 가장 문제가 된 낱말이 앞에 오게 한다.
    """
    # 기준보다 낮은 낱말과, 아예 빠뜨리거나 없는 말을 넣은 낱말을 모은다.
    # 빠뜨린 낱말은 점수가 없을 수 있어서 표시(ErrorType)로도 걸러 낸다
    flagged = [
        w
        for w in words
        if (w.accuracy is not None and w.accuracy < LOW_WORD_ACCURACY)
        or w.error_type in ("Omission", "Insertion")
    ]
    # 점수가 없는 낱말은 맨 뒤로 보낸다(정렬 기준이 없으므로 임의로 앞에 오면 안 된다)
    flagged.sort(key=lambda w: w.accuracy if w.accuracy is not None else 999.0)

    evidence: list[Evidence] = []
    for word in flagged[:MAX_LOW_WORD_EVIDENCE]:
        start, end = find_quote_span(transcript, word.word)
        label = ERROR_TYPE_LABELS.get(word.error_type, word.error_type or "표시 없음")
        score_text = f"{word.accuracy:.0f}점" if word.accuracy is not None else "점수 없음"
        evidence.append(
            Evidence(
                source=FeatureSource.AZURE,
                quote=word.word,
                start=start,
                end=end,
                comment=f"'{word.word}' 발음 정확도 {score_text} ({label})",
                detail={
                    "accuracy": word.accuracy,
                    "error_type": word.error_type,
                    "offset_ms": word.offset_ms,
                    "duration_ms": word.duration_ms,
                },
            )
        )
    return evidence


def _summary_evidence(
    assessment: PronunciationAssessment, feature_label: str
) -> Evidence:
    """이 점수가 무엇을 잰 값인지 한 줄로 남기는 근거.

    낱말 인용이 아니라 '계산에 쓴 값이 어디서 왔는지'를 남기는 자리다.
    규칙 자질도 같은 방식으로 계산 내역을 남긴다(근거 없는 점수를 만들지 않는다).
    """
    mode_text = "낭독형(제시문을 정답지로 줌)" if assessment.scripted else "자유 발화(정답지 없음)"
    return Evidence(
        source=FeatureSource.AZURE,
        quote="",
        comment=f"{feature_label}: {assessment.provider or 'azure'} 발음 평가가 {mode_text}로 매긴 값이다.",
        detail={
            "provider": assessment.provider,
            "scripted": assessment.scripted,
            "reference_text": assessment.reference_text,
            "word_count": float(len(assessment.words)),
        },
    )


def _score_feature(
    feature_id: str,
    name: str,
    value: float | None,
    assessment: PronunciationAssessment,
    *,
    applicable: bool = True,
    unavailable_note: str = "",
    extra_evidence: list[Evidence] | None = None,
) -> FeatureValue:
    """발음 점수 하나를 자질로 만든다.

    값이 없을 때 0점으로 때우지 않는 것이 중요하다.
    0점은 '발음이 아주 나빴다'는 뜻이고, 값 없음은 '재지 못했다'는 뜻이라
    서로 다른 상태다. 0으로 때우면 못 잰 답안이 발음 0점을 받는다.
    """
    # 이 모드에서 애초에 쓰지 않는 자질(자유 발화의 완전성)은 '부족'이 아니다.
    # not_applicable 로 두면 점수 계산에서 조용히 빠지고 영역 상태도 안 낮아진다
    if not applicable:
        return FeatureValue(
            id=feature_id,
            name=name,
            source=FeatureSource.AZURE,
            value=value,
            unit="0~100",
            status=FeatureStatus.NOT_APPLICABLE,
            note=unavailable_note,
        )
    if value is None:
        return FeatureValue(
            id=feature_id,
            name=name,
            source=FeatureSource.AZURE,
            value=None,
            unit="0~100",
            status=FeatureStatus.UNAVAILABLE,
            note=unavailable_note or "발음 평가가 이 점수를 주지 않았다.",
        )

    evidence = [_summary_evidence(assessment, name)]
    evidence.extend(extra_evidence or [])
    return FeatureValue(
        id=feature_id,
        name=name,
        source=FeatureSource.AZURE,
        value=round(float(value), 2),
        unit="0~100",
        status=FeatureStatus.OK,
        components={"word_count": float(len(assessment.words))},
        evidence=evidence,
    )


def extract_pronunciation_features(
    assessment: PronunciationAssessment | None,
    transcript: str = "",
) -> list[FeatureValue]:
    """발음 평가 결과를 채점기가 쓰는 자질 목록으로 옮긴다.

    발음 평가가 없으면(Gemini 로 받아썼거나 평가에 실패했으면) **빈 목록**을 준다.
    그러면 발화 전달력 영역은 지금까지처럼 채점되지 않고 자리만 남는다.
    이것이 백엔드와 약속된 동작이다.

    transcript 는 받아쓴 글이다. 낱말 근거에 '원문 몇 번째 글자'인지를 적기 위해
    받는다. 안 줘도 동작하며, 그때는 위치 없이 낱말만 근거에 남는다.
    """
    # 발음을 재지 못했으면 자질을 만들지 않는다. 값을 지어내지 않는 것이 원칙이다
    if assessment is None:
        return []

    # 낱말 근거는 정확도 자질에 붙인다. 정확도가 곧 낱말별 점수의 합이기 때문이다
    low_words = _low_word_evidence(assessment.words, transcript)

    features = [
        _score_feature(
            "pron_accuracy",
            "발음 정확도",
            assessment.accuracy,
            assessment,
            extra_evidence=low_words,
        ),
        _score_feature(
            "pron_fluency",
            "발화 유창성",
            assessment.fluency,
            assessment,
        ),
        _score_feature(
            "pron_completeness",
            "발화 완전성",
            assessment.completeness,
            assessment,
            # 자유 발화에는 읽어야 할 원문이 없어서 이 값에 기준이 없다
            applicable=assessment.scripted,
            unavailable_note=(
                ""
                if assessment.scripted
                else "자유 발화라서 읽을 원문이 없다. 이 값은 채점에 쓰지 않는다."
            ),
        ),
        _score_feature(
            "pron_prosody",
            "억양·강세",
            assessment.prosody,
            assessment,
            unavailable_note=(
                "발음 평가가 한국어 억양 점수를 주지 않았다(2026-08-22 실측). "
                "억양은 채점에 쓰지 않는다."
            ),
        ),
        _score_feature(
            "pron_overall",
            "발음 종합(제공자 산출)",
            assessment.overall,
            assessment,
        ),
    ]

    # 종합값은 나머지 셋을 합친 값이라 점수 계산에 넣지 않는다.
    # 결과에는 남겨서 우리 계산과 Azure 의 계산을 대조할 수 있게 한다
    for feature in features:
        if feature.id == "pron_overall":
            feature.note = (
                "Azure 가 자기 방식으로 합친 값이다. 정확도·유창성과 겹치므로 "
                "점수 계산에는 쓰지 않고 대조용으로만 남긴다."
            )
    return features
