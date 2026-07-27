"""문항별 채점 결과를 모아 시험 하나의 최종 등급을 내는 모듈.

채점은 문항이 끝날 때마다 백그라운드로 이뤄지고(POST /score),
시험이 끝나면 그 결과들을 여기서 하나로 합친다(POST /finalize).

여기서 책임지는 것:
- 영역별 최종 점수와 종합 점수
- 등급과 백분위 (백엔드가 커트라인을 알 필요가 없게 우리가 다 계산해서 준다)
- 말하기·쓰기 등급 차이라는 교차검증 '신호' (판정은 하지 않는다)
- 마지막 문항이 아직 채점 중이어도 오류 없이 결과를 내는 것

※ 임시값 안내 ※
등급 커트라인은 전문가가 확정한 앵커 답안에서 나온 것이 아니고,
백분위는 실제 응시자 분포가 아니라 손으로 만든 환산표에서 나온다.
둘 다 응답 meta 에 임시임을 표시해서 내보낸다.
"""

from __future__ import annotations

from dataclasses import dataclass

from .combine import DEFAULT_WEIGHTS, ScoringWeights, get_weights, grade_rank, to_grade
from .schema import (
    SCORING_VERSION,
    AreaStatus,
    CrossModeCheck,
    Evidence,
    ExpectedItem,
    FeatureSource,
    FinalizeItem,
    FinalizeMeta,
    FinalizeOptions,
    FinalizeRequest,
    FinalizeResponse,
    FinalizeStatus,
    ItemCoverage,
    ItemScoreStatus,
    Mode,
    ModeResult,
    Reliability,
    ScoreArea,
    ScoreContribution,
    SubScore,
)

# 영역 이름을 사람이 읽는 말로 바꾸는 표.
AREA_LABELS: dict[ScoreArea, str] = {
    ScoreArea.CONTENT_TASK: "내용 및 과제 수행",
    ScoreArea.LANGUAGE_USE: "언어 사용",
    ScoreArea.DELIVERY: "발화 전달력",
}


def _worst_reliability(
    items: list[FinalizeItem],
) -> tuple[Reliability, str, list[str]]:
    """문항들 중 가장 낮은 신뢰 수준을 시험 전체의 신뢰 수준으로 삼는다.

    왜 평균이 아니라 '가장 나쁜 것'인가:
    열 문항 중 한 문항이 대체 경로로 때워졌다면, 그 문항 점수는 근거가 없는 값이다.
    평균을 내면 나머지 아홉 문항에 묻혀서 최종 점수가 멀쩡해 보이지만,
    실제로는 그 한 문항만큼 오염된 점수다. 오염은 희석해서 없앨 수 있는 것이 아니다.

    meta 를 안 보낸 문항은 신뢰도를 알 수 없다. 이때는 '문제 없음'으로 치지 않고
    조용히 넘긴다(계약상 meta 는 선택 값이라 없다고 해서 실패로 볼 수는 없다).
    """
    # 나쁜 순서. 앞쪽이 더 나쁘다
    severity = {Reliability.FALLBACK: 2, Reliability.PARTIAL: 1, Reliability.FULL: 0}

    worst = Reliability.FULL
    worst_reason = ""
    unreliable_ids: list[str] = []

    for item in items:
        if item.meta is None:
            continue
        level = item.meta.reliability
        if level != Reliability.FULL:
            unreliable_ids.append(item.item_id)
        if severity[level] > severity[worst]:
            worst = level
            worst_reason = item.meta.reliability_reason

    if worst == Reliability.FULL:
        return worst, "", unreliable_ids

    # 어느 문항 때문인지 밝힌다. 그래야 어느 문항을 다시 채점할지 알 수 있다
    ids = ", ".join(unreliable_ids)
    reason = f"문항 {len(unreliable_ids)}개({ids})의 채점이 온전하지 않다"
    if worst_reason:
        reason += f" — {worst_reason}"
    return worst, reason, unreliable_ids


# ---------------------------------------------------------------------------
# 백분위 환산 (임시값)
# ---------------------------------------------------------------------------

# ※ 임시(TEMP) ※
# 점수를 백분위로 바꾸는 표. (점수, 백분위) 짝을 낮은 점수부터 늘어놓았다.
# 실제 응시자 분포를 한 번도 본 적이 없이 정한 값이라,
# "이 점수면 대략 상위 몇 %쯤"이라는 감을 주는 용도 이상으로 쓰면 안 된다.
# 2단계에서 응시 데이터가 쌓이면 실제 분포의 누적 백분위로 갈아 끼운다.
PERCENTILE_ANCHORS: list[tuple[float, float]] = [
    (0.0, 0.0),
    (30.0, 5.0),
    (40.0, 12.0),
    (55.0, 30.0),
    (65.0, 50.0),
    (75.0, 70.0),
    (85.0, 88.0),
    (92.0, 96.0),
    (100.0, 100.0),
]


def to_percentile(score: float) -> float:
    """점수를 백분위로 바꾼다. ※ 환산표가 임시값이다 ※

    표에 없는 점수는 앞뒤 두 지점을 직선으로 이어서 사이값을 구한다.
    """
    # 표 범위를 벗어나면 양 끝 값으로 잘라 준다
    if score <= PERCENTILE_ANCHORS[0][0]:
        return PERCENTILE_ANCHORS[0][1]
    if score >= PERCENTILE_ANCHORS[-1][0]:
        return PERCENTILE_ANCHORS[-1][1]

    # 점수가 어느 두 지점 사이에 있는지 찾아서 그 구간을 직선으로 잇는다
    for (low_score, low_pct), (high_score, high_pct) in zip(
        PERCENTILE_ANCHORS, PERCENTILE_ANCHORS[1:]
    ):
        if low_score <= score <= high_score:
            span = high_score - low_score
            ratio = (score - low_score) / span if span else 0.0
            return round(low_pct + ratio * (high_pct - low_pct), 1)
    return 0.0


# ---------------------------------------------------------------------------
# 문항 목록 정리
# ---------------------------------------------------------------------------


@dataclass
class _Coverage:
    """어떤 문항이 채점됐고 어떤 문항이 빠졌는지 정리한 결과."""

    usable: list[FinalizeItem]
    expected_weight: float
    scored_weight: float
    missing_ids: list[str]
    pending_ids: list[str]
    failed_ids: list[str]
    expected_count: int
    expected_by_mode: dict[Mode, int]


def _collect_coverage(
    items: list[FinalizeItem],
    expected_items: list[ExpectedItem],
) -> _Coverage:
    """넘어온 문항 결과를 훑어 '쓸 수 있는 것'과 '빠진 것'을 갈라낸다.

    시험 종료 시점에 마지막 한두 문항은 아직 채점 중일 수 있다.
    그 상황에서 오류를 내면 응시자가 결과를 아예 못 받으므로,
    빠진 문항을 기록만 해 두고 남은 것으로 계산을 이어간다.
    """
    by_id = {item.item_id: item for item in items}

    # 시험 전체 문항 목록을 백엔드가 알려줬으면 그것을 기준으로 삼는다.
    # 안 알려줬으면 넘어온 결과가 시험 전부라고 볼 수밖에 없다
    if expected_items:
        expected = expected_items
    else:
        expected = [
            ExpectedItem(item_id=i.item_id, mode=i.mode, weight=i.item_weight)
            for i in items
        ]

    usable: list[FinalizeItem] = []
    missing_ids: list[str] = []
    pending_ids: list[str] = []
    failed_ids: list[str] = []
    expected_weight = 0.0
    scored_weight = 0.0
    expected_by_mode: dict[Mode, int] = {}

    for exp in expected:
        expected_weight += exp.weight
        expected_by_mode[exp.mode] = expected_by_mode.get(exp.mode, 0) + 1

        item = by_id.get(exp.item_id)

        # 결과 자체가 안 넘어온 문항 (채점 요청이 아직 안 끝났거나 유실된 경우)
        if item is None:
            missing_ids.append(exp.item_id)
            continue

        # 채점 중이라고 표시된 문항
        if item.status == ItemScoreStatus.PENDING:
            pending_ids.append(exp.item_id)
            continue

        # 채점하다 실패한 문항
        if item.status == ItemScoreStatus.FAILED:
            failed_ids.append(exp.item_id)
            continue

        # 상태는 정상인데 점수가 비어 있으면 쓸 수 없다. 0점으로 오해하면 안 되므로 뺀다
        if item.overall_score is None and not item.subscores:
            failed_ids.append(exp.item_id)
            continue

        usable.append(item)
        scored_weight += item.item_weight

    return _Coverage(
        usable=usable,
        expected_weight=expected_weight,
        scored_weight=scored_weight,
        missing_ids=missing_ids,
        pending_ids=pending_ids,
        failed_ids=failed_ids,
        expected_count=len(expected),
        expected_by_mode=expected_by_mode,
    )


# ---------------------------------------------------------------------------
# 영역별 최종 점수
# ---------------------------------------------------------------------------


def _aggregate_area(area: ScoreArea, items: list[FinalizeItem]) -> SubScore:
    """한 영역의 점수를 문항들에 걸쳐 평균 낸다(문항 비중 반영).

    어떤 문항이 몇 점을 보탰는지를 contributions 에 남긴다.
    최종 등급도 근거 없이 나가면 안 되기 때문이다.
    """
    contributions: list[ScoreContribution] = []
    evidence: list[Evidence] = []
    total_weight = 0.0
    partial_seen = False

    # 문항마다 이 영역의 점수를 꺼내 모은다
    for item in items:
        area_score = next(
            (s for s in item.subscores if s.area == area and s.score is not None), None
        )
        # 이 문항에 해당 영역 점수가 없으면(예: 발화 전달력) 조용히 건너뛴다
        if area_score is None:
            continue
        if area_score.status == AreaStatus.PARTIAL:
            partial_seen = True

        total_weight += item.item_weight
        contributions.append(
            ScoreContribution(
                feature_id=item.item_id,
                feature_name=f"문항 {item.item_id} ({item.mode.value})",
                raw_value=area_score.score,
                # 문항 점수는 0~100이라 100으로 나누면 그대로 0~1이 된다
                normalized=round(min(1.0, max(0.0, area_score.score / 100.0)), 4),
                weight=item.item_weight,  # 아래에서 재정규화한 값으로 덮어쓴다
                points=0.0,
            )
        )
        # 문항별 근거를 하나씩만 끌어올린다(최종 결과가 근거로 뒤덮이지 않게)
        for ev in area_score.evidence[:1]:
            evidence.append(
                Evidence(
                    source=ev.source,
                    quote=ev.quote,
                    start=ev.start,
                    end=ev.end,
                    comment=f"[문항 {item.item_id}] {ev.comment}",
                    detail={"item_id": item.item_id},
                )
            )

    # 이 영역을 채점한 문항이 하나도 없으면 점수를 지어내지 않는다
    if total_weight <= 0:
        note = (
            "Azure 발음평가 미도입으로 이번 범위에서 채점하지 않는다(종합 점수에서 제외)."
            if area == ScoreArea.DELIVERY
            else "이 영역을 채점한 문항이 없어 최종 점수를 내지 못했다."
        )
        return SubScore(
            area=area,
            label=AREA_LABELS[area],
            score=None,
            weight=0.0,
            status=AreaStatus.NOT_EVALUATED,
            note=note,
        )

    # 문항 비중을 다시 나눠 합이 1이 되게 맞추고, 각 문항이 보탠 점수를 채운다
    score = 0.0
    for c in contributions:
        renormalized = c.weight / total_weight
        c.weight = round(renormalized, 4)
        c.points = round(c.raw_value * renormalized, 2)
        score += c.raw_value * renormalized

    return SubScore(
        area=area,
        label=AREA_LABELS[area],
        score=round(score, 2),
        weight=0.0,  # 종합 계산 단계에서 채운다
        # 문항 채점 자체가 반쪽이었으면 최종 영역 점수도 반쪽으로 표시한다
        status=AreaStatus.PARTIAL if partial_seen else AreaStatus.SCORED,
        contributions=contributions,
        evidence=evidence[:10],
        note="문항별 채점 결과를 문항 비중으로 평균했다." if not partial_seen else
             "일부 문항이 자질 누락 상태로 채점되어 최종 점수도 부분 결과다.",
    )


def _mode_result(
    mode: Mode,
    items: list[FinalizeItem],
    expected_count: int,
    weights: ScoringWeights,
) -> ModeResult:
    """말하기 또는 쓰기 한쪽의 점수와 등급을 낸다.

    최종 등급 산출뿐 아니라, 두 모드를 견줘 보는 교차검증에 쓰인다.
    """
    mode_items = [i for i in items if i.mode == mode and i.overall_score is not None]
    if not mode_items:
        return ModeResult(
            mode=mode, score=None, grade=None,
            scored_item_count=0, expected_item_count=expected_count,
        )

    # 문항 비중을 반영해 평균 낸다
    total_weight = sum(i.item_weight for i in mode_items) or 1.0
    score = sum(i.overall_score * i.item_weight for i in mode_items) / total_weight
    score = round(score, 2)

    return ModeResult(
        mode=mode,
        score=score,
        grade=to_grade(score, weights),
        scored_item_count=len(mode_items),
        expected_item_count=expected_count,
    )


def _cross_mode_check(
    mode_results: list[ModeResult],
    threshold: int,
    weights: ScoringWeights,
) -> CrossModeCheck:
    """말하기 등급과 쓰기 등급이 얼마나 벌어졌는지 본다.

    말하기는 잘하는데 쓰기가 유난히 좋거나(대필) 그 반대인 경우처럼
    두 등급이 크게 어긋나면 사람이 한 번 들여다볼 만한 신호가 된다.

    ※ 여기서는 신호만 낸다. 부정행위인지 아닌지는 이 파트가 정할 일이 아니다. ※
    """
    speaking = next((m for m in mode_results if m.mode == Mode.SPEAKING), None)
    writing = next((m for m in mode_results if m.mode == Mode.WRITING), None)

    # 한쪽이라도 채점되지 않았으면 비교 자체가 성립하지 않는다
    if not speaking or not writing or speaking.grade is None or writing.grade is None:
        return CrossModeCheck(
            comparable=False,
            speaking_grade=speaking.grade if speaking else None,
            writing_grade=writing.grade if writing else None,
            threshold=threshold,
            flagged=False,
            note="말하기와 쓰기 중 한쪽이 채점되지 않아 교차검증을 할 수 없었다.",
        )

    # 등급이 위에서 몇 번째인지로 바꿔 칸 수를 센다
    speaking_rank = grade_rank(speaking.grade, weights)
    writing_rank = grade_rank(writing.grade, weights)
    if speaking_rank is None or writing_rank is None:
        return CrossModeCheck(
            comparable=False,
            speaking_grade=speaking.grade,
            writing_grade=writing.grade,
            threshold=threshold,
            flagged=False,
            note="등급 표에 없는 값이 들어와 교차검증을 할 수 없었다.",
        )

    gap = abs(speaking_rank - writing_rank)
    flagged = gap >= threshold

    if flagged:
        higher = "쓰기" if writing_rank < speaking_rank else "말하기"
        note = (
            f"말하기 {speaking.grade} / 쓰기 {writing.grade} 로 {gap}등급 차이가 난다"
            f"({higher} 쪽이 높음). 사람이 한 번 확인해 볼 것을 권한다. "
            "※ 이것은 검토 권장 신호일 뿐이며 부정행위 판정이 아니다. "
            f"기준값 {threshold}등급은 임시값이다."
        )
    else:
        note = (
            f"말하기 {speaking.grade} / 쓰기 {writing.grade}, {gap}등급 차이로 "
            f"기준값({threshold}등급) 안에 있다."
        )

    return CrossModeCheck(
        comparable=True,
        speaking_grade=speaking.grade,
        writing_grade=writing.grade,
        grade_gap=gap,
        threshold=threshold,
        flagged=flagged,
        note=note,
    )


# ---------------------------------------------------------------------------
# 바깥에서 부르는 진입점
# ---------------------------------------------------------------------------


def finalize_session(request: FinalizeRequest) -> FinalizeResponse:
    """문항별 채점 결과를 모아 시험 하나의 최종 결과를 만든다.

    문항이 빠져 있어도 예외를 던지지 않는다.
    빠진 문항은 기록에 남기고 남은 문항으로 다시 비중을 나눠 계산한다.
    다만 너무 많이 빠지면 등급을 확정하지 않고 insufficient 로 돌려준다.
    """
    options: FinalizeOptions = request.options
    weights = get_weights(options.weights_profile)
    warnings: list[str] = []

    # 1단계: 어떤 문항이 쓸 수 있고 어떤 문항이 빠졌는지 정리한다
    coverage = _collect_coverage(request.items, request.expected_items)
    scored_ratio = (
        coverage.scored_weight / coverage.expected_weight
        if coverage.expected_weight > 0
        else 0.0
    )

    # 빠진 문항이 있으면 무엇이 왜 빠졌는지 남긴다
    if coverage.pending_ids:
        warnings.append(
            f"채점이 끝나지 않은 문항 {len(coverage.pending_ids)}개를 빼고 계산했다: "
            f"{', '.join(coverage.pending_ids)}"
        )
    if coverage.missing_ids:
        warnings.append(
            f"결과가 넘어오지 않은 문항 {len(coverage.missing_ids)}개를 빼고 계산했다: "
            f"{', '.join(coverage.missing_ids)}"
        )
    if coverage.failed_ids:
        warnings.append(
            f"채점에 실패한 문항 {len(coverage.failed_ids)}개를 빼고 계산했다: "
            f"{', '.join(coverage.failed_ids)}"
        )

    item_coverage = ItemCoverage(
        expected_count=coverage.expected_count,
        scored_count=len(coverage.usable),
        missing_item_ids=coverage.missing_ids,
        pending_item_ids=coverage.pending_ids,
        failed_item_ids=coverage.failed_ids,
        scored_ratio=round(scored_ratio, 4),
        min_scored_ratio=options.min_scored_ratio,
        min_scored_items=options.min_scored_items,
    )

    # 2단계: 등급을 낼 만큼 채점됐는지 판단한다.
    # 기준이 두 개인 이유: 비중만 보면 문항이 2개뿐인 시험도 통과해 버리고,
    # 개수만 보면 비중이 큰 문항이 통째로 빠진 경우를 놓친다
    enough_items = len(coverage.usable) >= options.min_scored_items
    enough_ratio = scored_ratio >= options.min_scored_ratio
    # 원래 문항 수 자체가 기준보다 적은 짧은 시험이면 개수 기준은 적용하지 않는다
    if coverage.expected_count < options.min_scored_items:
        enough_items = len(coverage.usable) == coverage.expected_count

    # 문항별 신뢰도를 모아 시험 전체의 신뢰도를 정한다.
    # 평균이 아니라 '가장 나쁜 문항'을 따르는 이유는 아래 함수 설명에 적어 두었다
    reliability, reliability_reason, unreliable_ids = _worst_reliability(request.items)
    if reliability != Reliability.FULL and reliability_reason:
        warnings.append(f"[신뢰도 {reliability.value}] {reliability_reason}")

    meta = FinalizeMeta(
        scoring_version=SCORING_VERSION,
        weights_profile=weights.profile,
        weights_provisional=weights.provisional,
        cutoffs_from_anchor_answers=False,
        percentile_provisional=True,
        grade_cutoffs={grade: cutoff for cutoff, grade in weights.grade_cutoffs},
        reliability=reliability,
        reliability_reason=reliability_reason,
        safe_to_show_candidate=(reliability != Reliability.FALLBACK),
        unreliable_item_ids=unreliable_ids,
    )

    if not coverage.usable or not (enough_items and enough_ratio):
        # 등급을 확정하지 않는다. 부족한 결과에 등급을 붙이면 그대로 통보되기 때문이다
        warnings.append(
            f"채점된 문항이 부족해 최종 등급을 확정하지 않았다 "
            f"(채점 {len(coverage.usable)}/{coverage.expected_count}문항, "
            f"비중 {scored_ratio:.0%}). "
            f"기준: 최소 {options.min_scored_items}문항 이상이며 비중 "
            f"{options.min_scored_ratio:.0%} 이상. ※ 이 기준값은 임시값이다."
        )
        return FinalizeResponse(
            session_id=request.session_id,
            candidate_id=request.candidate_id,
            status=FinalizeStatus.INSUFFICIENT,
            overall_score=None,
            overall_grade=None,
            percentile=None,
            subscores=[
                _aggregate_area(area, coverage.usable)
                for area in (ScoreArea.CONTENT_TASK, ScoreArea.LANGUAGE_USE, ScoreArea.DELIVERY)
            ],
            mode_results=[
                _mode_result(m, coverage.usable, coverage.expected_by_mode.get(m, 0), weights)
                for m in (Mode.SPEAKING, Mode.WRITING)
            ],
            cross_mode_check=CrossModeCheck(
                comparable=False,
                threshold=options.cross_mode_gap_threshold,
                flagged=False,
                note="채점된 문항이 부족해 교차검증을 하지 않았다.",
            ),
            item_coverage=item_coverage,
            warnings=warnings,
            meta=meta,
        )

    # 3단계: 영역별 최종 점수를 낸다
    subscores = [
        _aggregate_area(area, coverage.usable)
        for area in (ScoreArea.CONTENT_TASK, ScoreArea.LANGUAGE_USE, ScoreArea.DELIVERY)
    ]

    # 4단계: 영역 점수를 종합 점수로 묶는다.
    # 문항 채점 때와 똑같은 영역 가중치를 쓰고, 채점 못 한 영역은 빼고 재정규화한다
    scored_areas = [
        s for s in subscores
        if s.score is not None and weights.area_weights.get(s.area, 0.0) > 0
    ]
    total_area_weight = sum(weights.area_weights[s.area] for s in scored_areas)

    overall: float | None = None
    if total_area_weight > 0:
        overall = 0.0
        for s in subscores:
            if s in scored_areas:
                s.weight = round(weights.area_weights[s.area] / total_area_weight, 4)
                overall += s.score * s.weight
            else:
                s.weight = 0.0
        overall = round(overall, 2)

    # 5단계: 등급과 백분위. 백엔드가 커트라인을 몰라도 되도록 여기서 다 계산한다
    grade = to_grade(overall, weights) if overall is not None else None
    percentile = to_percentile(overall) if overall is not None else None

    # 6단계: 말하기·쓰기 각각의 결과와 두 등급의 차이(교차검증 신호)
    mode_results = [
        _mode_result(m, coverage.usable, coverage.expected_by_mode.get(m, 0), weights)
        for m in (Mode.SPEAKING, Mode.WRITING)
    ]
    cross = _cross_mode_check(mode_results, options.cross_mode_gap_threshold, weights)
    if cross.flagged:
        warnings.append(f"교차검증 신호: {cross.note}")

    # 빠진 문항이 하나라도 있으면 '부분 결과'로 표시한다
    status = (
        FinalizeStatus.COMPLETE
        if not (coverage.missing_ids or coverage.pending_ids or coverage.failed_ids)
        else FinalizeStatus.PARTIAL
    )

    # 임시값이라는 사실은 등급이 나올 때마다 반드시 함께 나간다
    if weights.provisional:
        warnings.append(
            "※ 임시 ※ 결합 가중치는 학습된 값이 아니고, 등급 커트라인도 전문가가 확정한 "
            "앵커 답안에서 나온 값이 아니다. 백분위 역시 실제 응시자 분포가 아니라 "
            "임시 환산표에서 나온 값이다. 확정 등급으로 통보하지 말 것."
        )

    return FinalizeResponse(
        session_id=request.session_id,
        candidate_id=request.candidate_id,
        status=status,
        overall_score=overall,
        overall_grade=grade,
        percentile=percentile,
        subscores=subscores,
        mode_results=mode_results,
        cross_mode_check=cross,
        item_coverage=item_coverage,
        warnings=warnings,
        meta=meta,
    )
