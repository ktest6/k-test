"""자질을 영역별 점수로, 영역별 점수를 종합 점수로 묶는 모듈.

※ 중요 ※ 여기 있는 가중치와 기준선은 전부 **임시값**이다.
아직 라벨링 데이터가 없어서 학습된 모델이 아니라, 사람이 손으로 정한 숫자다.
2단계에서 쌍대 비교 라벨을 모아 순위 학습 -> Ridge/XGBoost 로 계수를 구하면
이 파일의 숫자만 갈아 끼우면 되도록 구조를 잡았다(입출력 형태는 그대로다).

설계 원칙:
- 점수만 돌려주지 않는다. 어떤 자질이 몇 점을 보탰는지(ScoreContribution)를 항상 함께 낸다.
- 계산에 못 쓴 자질이 있으면 0점으로 때우지 않고, 그 자질을 빼고 남은 가중치를 다시 나눈다.
  (값을 지어내면 못 쓴 답안이 좋은 점수를 받는다)
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .schema import (
    AreaStatus,
    ChecklistResult,
    Evidence,
    FeatureSource,
    FeatureStatus,
    FeatureValue,
    Mode,
    ScoreArea,
    ScoreContribution,
    SubScore,
)

# ---------------------------------------------------------------------------
# 자질 값을 0~1로 펴는 기준선 (전부 임시값)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Normalizer:
    """자질의 원래 값을 0~1로 펴는 기준.

    low 이하면 0, high 이상이면 1로 본다(higher_is_better 가 False 면 반대).
    사이는 직선으로 이어서 계산한다.

    ※ 임시 ※ 이 low/high 는 실제 응시자 분포를 본 적 없이 정한 값이다.
    데이터가 모이면 백분위 기반으로 다시 잡아야 한다.
    """

    low: float
    high: float
    higher_is_better: bool = True
    label: str = ""

    def normalize(self, value: float) -> float:
        # 기준선을 잘못 넣어 위아래가 같으면 나눗셈이 불가능하므로 0으로 막는다
        if self.high == self.low:
            return 0.0
        # 값이 low~high 사이에서 어느 지점인지를 0~1 사이 비율로 바꾼다
        ratio = (value - self.low) / (self.high - self.low)
        # 기준선 밖으로 나간 값은 0이나 1에서 멈춘다(아주 긴 답안이 점수를 무한정 끌어올리지 않게)
        ratio = max(0.0, min(1.0, ratio))
        # 오류 자질처럼 '적을수록 좋은' 값은 방향을 뒤집는다
        return ratio if self.higher_is_better else 1.0 - ratio


# 자질 id -> 정규화 기준. ※ 전부 임시값 ※
FEATURE_NORMALIZERS: dict[str, Normalizer] = {
    # 언어 사용 (규칙 자질)
    "lexical_diversity_mattr": Normalizer(0.55, 0.90, True, "어휘 다양도"),
    "advanced_vocab_ratio": Normalizer(0.0, 0.12, True, "고급 어휘 비율"),
    "lexical_density": Normalizer(0.30, 0.55, True, "어휘 밀도"),
    "clause_density": Normalizer(1.0, 4.0, True, "절 밀도"),
    "connective_ending_diversity": Normalizer(0.0, 0.8, True, "연결어미 다양성"),
    "formality": Normalizer(0.3, 1.0, True, "격식체 비율"),
    "subject_honorific_si": Normalizer(0.0, 2.0, True, "주체 높임 '-시-' 빈도"),
    # 언어 사용 (LLM 오류 자질) — 오류는 적을수록 좋으므로 방향이 반대다.
    "error_josa": Normalizer(0.0, 8.0, False, "조사 오류"),
    "error_conjugation": Normalizer(0.0, 8.0, False, "어미 활용 오류"),
    "error_word_choice": Normalizer(0.0, 6.0, False, "어휘 오용"),
    "error_honorific": Normalizer(0.0, 5.0, False, "높임법 오류"),
    "error_spelling": Normalizer(0.0, 8.0, False, "맞춤법 오류"),
    "spacing_error_rate": Normalizer(0.0, 0.35, False, "띄어쓰기 오류율"),
    # 내용·과제 수행
    "response_length": Normalizer(15.0, 70.0, True, "응답 길이"),
    "words_per_sentence": Normalizer(4.0, 13.0, True, "문장당 어절 수"),
    # 발화 전달력 (Azure 발음평가). 원래 값이 0~100 이라 그대로 쓰지 않고 다시 편다.
    # ※ 임시값 ※ 100점을 만점으로 그대로 쓰면 안 되는 이유:
    # 비원어민 학습자에게 90점대는 거의 나오지 않는다. 실측 예에서 실제 응시자
    # 낭독의 정확도가 57점이었다. 0~100을 그대로 점수로 쓰면 전원이 낮게 깔린다.
    # 실제 응시자 분포가 모이면 백분위로 다시 잡아야 한다.
    "pron_accuracy": Normalizer(40.0, 95.0, True, "발음 정확도"),
    "pron_fluency": Normalizer(30.0, 95.0, True, "발화 유창성"),
    "pron_completeness": Normalizer(50.0, 100.0, True, "발화 완전성"),
}

# '반말 혼입 횟수'는 formality 자질의 components 에 들어 있는 값이라
# 따로 기준선을 둔다. 말투 축을 축소하지 말라는 설계 요구에 따라 별도 감점으로 반영한다.
BANMAL_NORMALIZER = Normalizer(0.0, 3.0, False, "반말 혼입 횟수")


# ---------------------------------------------------------------------------
# 가중치 (전부 임시값, 주입 가능)
# ---------------------------------------------------------------------------


@dataclass
class ScoringWeights:
    """점수 결합에 쓰는 가중치 묶음.

    학습된 계수가 생기면 이 객체만 바꿔 끼우면 되고,
    API 스키마나 호출 방식은 건드릴 필요가 없다.
    """

    profile: str = "provisional_v0"
    provisional: bool = True  # True = 아직 학습된 값이 아님

    # 영역 가중치. ※ 전부 임시값 ※
    #
    # delivery(발화 전달력) 0.20 은 Azure 발음평가가 붙으면서 새로 생긴 값이다.
    # 나머지 0.80 을 예전 비율(내용 0.45 : 언어 0.55)로 나눠서 0.36 : 0.44 로 두었다.
    #
    # **이렇게 두면 발음 점수가 없을 때 예전과 완전히 같은 점수가 나온다.**
    # 점수를 못 낸 영역은 빠지고 남은 영역끼리 다시 100%가 되게 나누므로(combine 참고),
    # delivery 가 빠지면 0.36/0.80 = 0.45, 0.44/0.80 = 0.55 로 되돌아간다.
    # 쓰기 답안과 Gemini 로 받아쓴 말하기 답안이 여기에 해당한다.
    area_weights: dict[ScoreArea, float] = field(
        default_factory=lambda: {
            ScoreArea.CONTENT_TASK: 0.36,
            ScoreArea.LANGUAGE_USE: 0.44,
            ScoreArea.DELIVERY: 0.20,
        }
    )

    # 내용·과제 수행 영역 안에서의 비중.
    # 체크리스트 충족률이 중심이고, 길이는 "말을 충분히 했는가"의 보조 지표다.
    content_checklist_weight: float = 0.75
    content_feature_weights: dict[str, float] = field(
        default_factory=lambda: {
            "response_length": 0.15,
            "words_per_sentence": 0.10,
        }
    )

    # 언어 사용 영역 안에서의 자질 비중.
    language_feature_weights: dict[str, float] = field(
        default_factory=lambda: {
            "lexical_diversity_mattr": 0.12,
            "advanced_vocab_ratio": 0.08,
            "lexical_density": 0.08,
            "clause_density": 0.08,
            "connective_ending_diversity": 0.06,
            "formality": 0.10,
            "banmal_penalty": 0.08,          # formality.components 의 반말 혼입 횟수
            "subject_honorific_si": 0.04,
            "error_josa": 0.12,
            "error_conjugation": 0.10,
            "error_word_choice": 0.06,
            "error_honorific": 0.08,
            # 쓰기에서만 켜지는 자질 (말하기에서는 자동으로 빠지고 나머지가 재정규화된다)
            "error_spelling": 0.06,
            "spacing_error_rate": 0.06,
        }
    )

    # 발화 전달력 영역 안에서의 자질 비중. ※ 임시값 ※
    #
    # 발음 종합(pron_overall)을 넣지 않은 이유:
    # 그것은 Azure 가 아래 셋을 자기 방식으로 합친 값이라, 함께 넣으면
    # 같은 것을 두 번 세게 된다. 결과에는 남기되 계산에는 안 쓴다.
    #
    # 완전성(pron_completeness)은 낭독형 문항에서만 값이 살아 있다.
    # 자유 발화에서는 자질이 not_applicable 로 와서 조용히 빠지고,
    # 정확도·유창성이 다시 100%가 되게 나뉜다.
    delivery_feature_weights: dict[str, float] = field(
        default_factory=lambda: {
            "pron_accuracy": 0.50,
            "pron_fluency": 0.30,
            "pron_completeness": 0.20,
        }
    )

    # ※ 임시 ※ 등급 커트라인. 전문가가 등급을 확정한 앵커 답안이 생기면 교체한다.
    grade_cutoffs: list[tuple[float, str]] = field(
        default_factory=lambda: [
            (85.0, "A"),
            (70.0, "B"),
            (55.0, "C"),
            (40.0, "D"),
            (0.0, "E"),
        ]
    )


DEFAULT_WEIGHTS = ScoringWeights()

#: 프로필 이름으로 가중치를 고를 수 있게 해 두는 자리.
#: 나중에 학습된 프로필("ridge_v1" 등)을 여기에 등록하면 API 는 그대로 두고 교체할 수 있다.
WEIGHT_PROFILES: dict[str, ScoringWeights] = {"provisional_v0": DEFAULT_WEIGHTS}


def get_weights(profile: str = "provisional_v0") -> ScoringWeights:
    """이름으로 가중치 묶음을 가져온다. 없는 이름이면 기본값을 준다."""
    return WEIGHT_PROFILES.get(profile, DEFAULT_WEIGHTS)


# ---------------------------------------------------------------------------
# 결합 계산
# ---------------------------------------------------------------------------


@dataclass
class CombineResult:
    """결합 결과 묶음."""

    overall_score: float | None
    overall_grade: str | None
    subscores: list[SubScore]
    warnings: list[str] = field(default_factory=list)


def _usable(f: FeatureValue | None) -> bool:
    """이 자질을 점수 계산에 쓸 수 있는지."""
    return f is not None and f.status == FeatureStatus.OK and f.value is not None


def _weighted_average(
    parts: list[tuple[str, str, float | None, float, float]],
) -> tuple[float | None, list[ScoreContribution], list[str]]:
    """(자질id, 이름, 원래값, 0~1값, 가중치) 목록을 받아 가중 평균 점수를 낸다.

    빠진 자질이 있으면 남은 것들의 가중치 합으로 다시 나눠(재정규화) 계산한다.
    이렇게 해야 자질 하나가 없다는 이유로 점수가 통째로 낮아지는 일이 없다.
    """
    # 실제로 쓸 수 있었던 자질들의 가중치만 더한다. 이것이 재정규화의 기준이 된다
    total_weight = sum(w for *_, w in parts)
    notes: list[str] = []

    # 쓸 자질이 하나도 없으면 점수를 지어내지 않고 '없음'을 돌려준다
    if total_weight <= 0:
        return None, [], ["점수를 낼 수 있는 자질이 하나도 없다."]

    contributions: list[ScoreContribution] = []
    score = 0.0
    for fid, name, raw, normalized, weight in parts:
        # 원래 가중치를 '남은 것들의 합'으로 나눠서 다시 100%가 되게 맞춘다.
        # 이렇게 해야 자질 하나가 빠졌다는 이유로 점수가 통째로 깎이지 않는다
        renormalized = weight / total_weight
        points = normalized * renormalized * 100.0
        score += points
        # 점수만이 아니라 "이 자질이 몇 점을 보탰는지"를 함께 남긴다.
        # 이 내역이 있어야 응시자에게 점수를 설명할 수 있다
        contributions.append(
            ScoreContribution(
                feature_id=fid,
                feature_name=name,
                raw_value=raw,
                normalized=round(normalized, 4),
                weight=round(renormalized, 4),
                points=round(points, 2),
            )
        )
    return round(score, 2), contributions, notes


def _content_task_subscore(
    features: dict[str, FeatureValue],
    checklist_results: list[ChecklistResult],
    weights: ScoringWeights,
) -> SubScore:
    """내용 및 과제 수행 점수.

    체크리스트 충족률이 중심이다. 문항이 요구한 것을 실제로 말했는지가 이 영역의 본질이다.
    """
    parts: list[tuple[str, str, float | None, float, float]] = []
    evidence: list[Evidence] = []
    notes: list[str] = []
    partial = False

    if checklist_results:
        # 항목마다 중요도가 다를 수 있어 개수가 아니라 비중으로 충족률을 낸다
        weight_sum = sum(c.weight for c in checklist_results) or 1.0
        met_sum = sum(c.weight for c in checklist_results if c.met == 1)
        ratio = met_sum / weight_sum
        parts.append(
            (
                "checklist_completion",
                "체크리스트 충족률",
                round(ratio, 4),
                ratio,
                weights.content_checklist_weight,
            )
        )
        # 항목별 충족·미충족 근거를 영역 근거로 끌어올린다.
        # 백엔드가 체크리스트를 따로 뒤지지 않아도 "왜 이 점수인지"를 바로 보여 줄 수 있게 하려는 것
        for c in checklist_results:
            mark = "충족" if c.met == 1 else "미충족"
            for ev in c.evidence[:1]:
                evidence.append(
                    Evidence(
                        source=ev.source,
                        quote=ev.quote,
                        start=ev.start,
                        end=ev.end,
                        comment=f"[{mark}] {c.description} — {ev.comment}",
                        detail={"checklist_id": c.id, "met": c.met},
                    )
                )
        # 임시 판정으로 매겨진 결과라면 영역 상태를 '일부만 계산됨'으로 낮춘다
        if any(c.note.startswith("※ 임시") for c in checklist_results):
            partial = True
            notes.append("체크리스트가 임시 대체 판정(핵심어 일치)으로 매겨졌다.")
    else:
        partial = True
        notes.append("체크리스트가 없어 충족률을 반영하지 못했다.")

    # 충족률 외에 '말을 충분히 했는가'를 보는 보조 자질을 더한다
    for fid, w in weights.content_feature_weights.items():
        f = features.get(fid)
        # 값을 못 구한 자질은 0점으로 때우지 않고 아예 빼고 간다(위에서 가중치가 재정규화된다)
        if not _usable(f):
            partial = True
            notes.append(f"자질 '{fid}' 를 쓸 수 없어 가중치를 다시 나눴다.")
            continue
        normalizer = FEATURE_NORMALIZERS[fid]
        parts.append((fid, f.name, f.value, normalizer.normalize(f.value), w))
        evidence.extend(f.evidence[:1])

    score, contributions, calc_notes = _weighted_average(parts)
    notes.extend(calc_notes)

    # 결과를 읽는 쪽이 '온전한 점수'와 '반쪽 점수'를 구별할 수 있게 상태를 붙인다
    status = AreaStatus.SCORED
    if score is None:
        status = AreaStatus.NOT_EVALUATED
    elif partial:
        status = AreaStatus.PARTIAL

    return SubScore(
        area=ScoreArea.CONTENT_TASK,
        label="내용 및 과제 수행",
        score=score,
        weight=0.0,  # 종합 계산 단계에서 채운다
        status=status,
        contributions=contributions,
        evidence=evidence[:12],
        note=" / ".join(notes),
    )


def _language_use_subscore(
    features: dict[str, FeatureValue],
    weights: ScoringWeights,
) -> SubScore:
    """언어 사용 점수. 어휘·문법 자질과 LLM 오류 자질을 함께 본다."""
    parts: list[tuple[str, str, float | None, float, float]] = []
    evidence: list[Evidence] = []
    notes: list[str] = []
    partial = False
    # 빠진 자질을 '사유별로' 모아 둔다.
    # LLM이 한 번 실패하면 그것이 걸린 자질 네 개가 한꺼번에 빠지는데,
    # 자질마다 같은 사유를 한 번씩 적으면 같은 문장이 네 번 반복된다
    excluded_by_reason: dict[str, list[str]] = {}

    for fid, w in weights.language_feature_weights.items():
        # 반말 혼입은 독립된 자질이 아니라 formality 자질 안에 들어 있는 수치다.
        # 말투 축을 축소하지 말라는 설계 요구가 있어 별도 감점 항목으로 따로 반영한다
        if fid == "banmal_penalty":
            f = features.get("formality")
            if not _usable(f) or "banmal_count" not in f.components:
                partial = True
                notes.append("반말 혼입 횟수를 확인할 수 없어 가중치를 다시 나눴다.")
                continue
            count = f.components["banmal_count"]
            parts.append(
                ("banmal_penalty", "반말 혼입 횟수", count, BANMAL_NORMALIZER.normalize(count), w)
            )
            # 감점 사유를 설명하려면 실제로 반말이 나온 문장을 보여 줘야 한다
            for ev in f.evidence[:2]:
                if "반말" in ev.comment:
                    evidence.append(ev)
            continue

        f = features.get(fid)
        if not _usable(f):
            # 말하기의 맞춤법처럼 이 모드에서 애초에 안 쓰는 자질은 '부족'이 아니다.
            # 조용히 빼기만 하고 영역 상태를 낮추지 않는다
            if f is not None and f.status == FeatureStatus.NOT_APPLICABLE:
                continue
            # 반면 LLM 키가 없어서 못 구한 자질은 '반쪽 채점'이므로 표시를 남긴다
            partial = True
            reason = f.note if f is not None and f.note else "자질 값이 없음"
            excluded_by_reason.setdefault(reason, []).append(fid)
            continue

        normalizer = FEATURE_NORMALIZERS[fid]
        parts.append((fid, f.name, f.value, normalizer.normalize(f.value), w))
        evidence.extend(f.evidence[:1])

    # 같은 사유로 빠진 자질들을 한 줄로 묶는다.
    # "자질 4개(...)를 제외했다: <사유 한 번>" 형태가 되어 문구가 짧아진다
    for reason, fids in excluded_by_reason.items():
        notes.append(f"자질 {len(fids)}개({', '.join(fids)}) 제외 — {reason}")

    score, contributions, calc_notes = _weighted_average(parts)
    notes.extend(calc_notes)

    status = AreaStatus.SCORED
    if score is None:
        status = AreaStatus.NOT_EVALUATED
    elif partial:
        status = AreaStatus.PARTIAL

    return SubScore(
        area=ScoreArea.LANGUAGE_USE,
        label="언어 사용",
        score=score,
        weight=0.0,
        status=status,
        contributions=contributions,
        evidence=evidence[:12],
        note=" / ".join(notes),
    )


def _delivery_subscore(
    features: dict[str, FeatureValue],
    weights: ScoringWeights,
) -> SubScore:
    """발화 전달력 점수. 발음 평가(Azure)가 준 값으로만 계산한다.

    이 영역만 유일하게 '글'이 아니라 '소리'를 본 값으로 매겨진다.
    받아쓴 글로는 발음을 알 수 없기 때문이다(scoring-design 참고).

    발음 자질이 하나도 없으면 — 쓰기 답안이거나, 발음을 못 재는 제공자(Gemini)로
    받아썼거나, 발음 평가가 실패한 경우다 — 예전과 똑같이 채점하지 않고 자리만 남긴다.
    이때 종합 점수는 내용·언어 두 영역만으로 예전 비율 그대로 계산된다.
    """
    parts: list[tuple[str, str, float | None, float, float]] = []
    evidence: list[Evidence] = []
    notes: list[str] = []
    partial = False

    for fid, w in weights.delivery_feature_weights.items():
        f = features.get(fid)
        if not _usable(f):
            # 이 문항에서 애초에 쓰지 않는 자질(자유 발화의 완전성)은 '부족'이 아니다.
            # 조용히 빼기만 하고 영역 상태를 낮추지 않는다
            if f is not None and f.status == FeatureStatus.NOT_APPLICABLE:
                continue
            # 자질이 아예 없으면 발음 평가 자체가 없었던 것이다.
            # 그 경우는 아래에서 '채점 안 함'으로 빠지므로 여기서는 표시만 남긴다
            if f is not None:
                partial = True
                notes.append(f"자질 '{fid}' 를 쓸 수 없어 가중치를 다시 나눴다.")
            continue

        normalizer = FEATURE_NORMALIZERS[fid]
        parts.append((fid, f.name, f.value, normalizer.normalize(f.value), w))
        # 어느 낱말 때문에 깎였는지를 영역 근거로 끌어올린다.
        # 이것이 없으면 응시자에게 "발음 몇 점"이라는 숫자밖에 줄 것이 없다
        evidence.extend(f.evidence[:6])

    # 발음 평가가 아예 없었던 경우. 예전과 똑같은 모양으로 자리만 남긴다
    if not parts:
        return SubScore(
            area=ScoreArea.DELIVERY,
            label="발화 전달력",
            score=None,
            weight=0.0,
            status=AreaStatus.NOT_EVALUATED,
            contributions=[],
            evidence=[],
            note=(
                "발음 평가 결과가 없어 채점하지 않았다(종합 점수에서 제외). "
                "쓰기 답안이거나, 발음을 재지 못하는 받아쓰기로 채점한 경우다."
            ),
        )

    score, contributions, calc_notes = _weighted_average(parts)
    notes.extend(calc_notes)

    status = AreaStatus.SCORED
    if score is None:
        status = AreaStatus.NOT_EVALUATED
    elif partial:
        status = AreaStatus.PARTIAL

    return SubScore(
        area=ScoreArea.DELIVERY,
        label="발화 전달력",
        score=score,
        weight=0.0,  # 종합 계산 단계에서 채운다
        status=status,
        contributions=contributions,
        evidence=evidence[:12],
        note=" / ".join(notes),
    )


def to_grade(score: float, weights: ScoringWeights | None = None) -> str:
    """점수를 등급으로 바꾼다. ※ 커트라인은 임시값 ※

    문항별 채점과 시험 전체 최종 등급이 같은 잣대를 쓰도록 여기 한 곳에만 둔다.
    """
    weights = weights or DEFAULT_WEIGHTS
    # 커트라인은 높은 등급부터 늘어놓았으므로, 처음 걸리는 등급이 답이다
    for cutoff, grade in weights.grade_cutoffs:
        if score >= cutoff:
            return grade
    # 어디에도 안 걸리는 경우(커트라인 설정이 잘못된 경우)는 가장 낮은 등급으로 둔다
    return weights.grade_cutoffs[-1][1]


def grade_order(weights: ScoringWeights | None = None) -> list[str]:
    """등급을 높은 것부터 늘어놓은 목록. 등급 사이의 '칸 수'를 셀 때 쓴다."""
    weights = weights or DEFAULT_WEIGHTS
    return [grade for _, grade in weights.grade_cutoffs]


def grade_rank(grade: str, weights: ScoringWeights | None = None) -> int | None:
    """등급이 위에서 몇 번째인지 알려준다(A=0, B=1 ...).

    말하기 등급과 쓰기 등급이 몇 칸 벌어졌는지 재는 데 쓴다.
    """
    order = grade_order(weights)
    # 모르는 등급이 들어오면 순서를 지어내지 않고 '알 수 없음'을 돌려준다
    return order.index(grade) if grade in order else None


# 이름을 바꾸기 전 이름으로 부르던 곳이 있어 옛 이름도 남겨 둔다.
_to_grade = to_grade


def combine(
    features: list[FeatureValue],
    checklist_results: list[ChecklistResult],
    mode: Mode = Mode.SPEAKING,
    weights: ScoringWeights | None = None,
) -> CombineResult:
    """자질과 체크리스트 판정을 받아 영역별 점수와 종합 점수를 만든다."""
    weights = weights or DEFAULT_WEIGHTS
    # 자질을 id로 바로 찾을 수 있게 정리해 둔다
    fmap = {f.id: f for f in features}
    warnings: list[str] = []

    # 영역별 점수를 각각 계산한다. delivery 는 Azure 도입 전이라 자리만 만든다
    subscores = [
        _content_task_subscore(fmap, checklist_results, weights),
        _language_use_subscore(fmap, weights),
        # 발음 자질이 있으면 채점되고, 없으면 예전처럼 자리만 남는다
        _delivery_subscore(fmap, weights),
    ]

    # 실제로 점수가 나온 영역만 종합에 넣는다.
    # 채점하지 못한 영역을 0점으로 넣으면 종합 점수가 부당하게 낮아진다
    scored = [
        s for s in subscores
        if s.score is not None and weights.area_weights.get(s.area, 0.0) > 0
    ]
    total_area_weight = sum(weights.area_weights[s.area] for s in scored)

    overall: float | None = None
    if total_area_weight > 0:
        overall = 0.0
        for s in subscores:
            base = weights.area_weights.get(s.area, 0.0)
            if s in scored:
                # 남은 영역들끼리 다시 100%가 되도록 비중을 나눈다
                s.weight = round(base / total_area_weight, 4)
                overall += s.score * s.weight
            else:
                # 종합에서 빠진 영역은 비중 0으로 표시해, 응답만 봐도 제외된 것이 보이게 한다
                s.weight = 0.0
        overall = round(overall, 2)
    else:
        warnings.append("점수를 낼 수 있는 영역이 없어 종합 점수를 내지 못했다.")

    # 반쪽으로 계산됐거나 아예 못 낸 영역을 경고로 끌어올린다.
    # delivery 는 처음부터 범위 밖이라고 정한 것이라 경고 대상이 아니다
    for s in subscores:
        if s.status == AreaStatus.PARTIAL:
            warnings.append(f"'{s.label}' 영역이 일부 자질 없이 계산되었다: {s.note}")
        if s.status == AreaStatus.NOT_EVALUATED and s.area != ScoreArea.DELIVERY:
            warnings.append(f"'{s.label}' 영역을 채점하지 못했다: {s.note}")

    grade = _to_grade(overall, weights) if overall is not None else None

    # 임시 가중치로 계산했다는 사실을 결과에 반드시 실어 보낸다.
    # 이 경고가 없으면 임시 점수가 확정 등급처럼 쓰일 위험이 있다
    if weights.provisional:
        warnings.append(
            "※ 임시 ※ 결합 가중치와 등급 커트라인은 학습된 값이 아니라 손으로 정한 임시값이다. "
            "절대 등급으로 쓰지 말고 답안 사이 비교에만 쓸 것."
        )

    return CombineResult(
        overall_score=overall,
        overall_grade=grade,
        subscores=subscores,
        warnings=warnings,
    )
