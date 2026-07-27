"""시험 전체 최종 등급(POST /finalize)과 서버 예열이 동작하는지 확인하는 스크립트.

LLM API 키 없이 돌아간다.
확인하려는 것:
  1) 전 문항이 채점된 정상 케이스에서 등급·백분위·근거가 나오는가
  2) 마지막 문항이 빠졌을 때 오류 없이 재정규화되고 warnings 에 남는가
  3) 채점된 문항이 너무 적으면 등급을 확정하지 않는가
  4) 말하기 A / 쓰기 E 처럼 급차이가 크면 교차검증 신호가 뜨는가
  5) 예열 뒤 첫 /score 호출이 실제로 빨라지는가

실행: .venv\\Scripts\\python.exe scripts\\check_finalize.py
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.scoring.finalize import finalize_session, to_percentile  # noqa: E402
from src.scoring.schema import (  # noqa: E402
    AreaStatus,
    Evidence,
    ExpectedItem,
    FeatureSource,
    FinalizeItem,
    FinalizeOptions,
    FinalizeRequest,
    FinalizeStatus,
    ItemScoreStatus,
    Mode,
    ScoreArea,
    SubScore,
)


def make_item(
    item_id: str,
    mode: Mode,
    content_score: float,
    language_score: float,
    status: ItemScoreStatus = ItemScoreStatus.SCORED,
    weight: float = 1.0,
) -> FinalizeItem:
    """문항 하나의 채점 결과를 흉내 낸다.

    /score 응답과 같은 모양이라, 백엔드는 실제 응답을 그대로 담아 보내면 된다.
    """
    # 문항 종합 점수는 채점 때와 같은 영역 가중치(0.45 / 0.55)로 계산한다
    overall = round(content_score * 0.45 + language_score * 0.55, 2)
    return FinalizeItem(
        item_id=item_id,
        mode=mode,
        overall_score=overall,
        subscores=[
            SubScore(
                area=ScoreArea.CONTENT_TASK,
                label="내용 및 과제 수행",
                score=content_score,
                weight=0.45,
                status=AreaStatus.SCORED,
                evidence=[
                    Evidence(
                        source=FeatureSource.LLM,
                        quote="전원을 차단했습니다",
                        start=10,
                        end=20,
                        comment="[충족] 조치를 말했는가",
                    )
                ],
            ),
            SubScore(
                area=ScoreArea.LANGUAGE_USE,
                label="언어 사용",
                score=language_score,
                weight=0.55,
                status=AreaStatus.SCORED,
                evidence=[
                    Evidence(
                        source=FeatureSource.KIWI,
                        quote="보고드렸습니다",
                        start=30,
                        end=38,
                        comment="높임 종결 유지",
                    )
                ],
            ),
            SubScore(
                area=ScoreArea.DELIVERY,
                label="발화 전달력",
                score=None,
                weight=0.0,
                status=AreaStatus.NOT_EVALUATED,
            ),
        ],
        item_weight=weight,
        status=status,
    )


def show(title: str, response) -> None:
    """최종 결과를 사람이 읽을 수 있게 찍어 준다."""
    print("=" * 78)
    print(title)
    print("=" * 78)
    print(f"  상태: {response.status.value}")
    print(f"  종합 점수: {response.overall_score}  등급: {response.overall_grade}  "
          f"백분위: {response.percentile}")
    print(f"  문항 커버리지: {response.item_coverage.scored_count}/"
          f"{response.item_coverage.expected_count}문항 "
          f"(비중 {response.item_coverage.scored_ratio:.0%}, "
          f"기준 {response.item_coverage.min_scored_ratio:.0%} 이상 & "
          f"{response.item_coverage.min_scored_items}문항 이상)")
    if response.item_coverage.pending_item_ids:
        print(f"    채점 중: {response.item_coverage.pending_item_ids}")
    if response.item_coverage.missing_item_ids:
        print(f"    결과 없음: {response.item_coverage.missing_item_ids}")
    print("  영역별 최종:")
    for s in response.subscores:
        score_text = "채점 안 함" if s.score is None else f"{s.score:6.2f}"
        print(f"    - {s.label:12s} {score_text}  비중 {s.weight}  상태 {s.status.value}")
        # 어느 문항이 몇 점을 보탰는지가 최종 등급의 근거다
        for c in s.contributions:
            print(f"        {c.feature_name:28s} {c.raw_value:6.2f}점 "
                  f"x 비중 {c.weight:.3f} = {c.points:5.2f}점")
    print("  모드별:")
    for m in response.mode_results:
        score_text = "-" if m.score is None else f"{m.score:.2f}"
        print(f"    - {m.mode.value:9s} {score_text:>7s}  등급 {m.grade}  "
              f"({m.scored_item_count}/{m.expected_item_count}문항)")
    c = response.cross_mode_check
    print(f"  교차검증: 비교가능={c.comparable} 차이={c.grade_gap} "
          f"기준={c.threshold} 플래그={c.flagged}")
    print(f"    {c.note[:110]}")
    print("  근거 예시(내용 및 과제 수행):")
    for s in response.subscores:
        if s.area == ScoreArea.CONTENT_TASK:
            for ev in s.evidence[:2]:
                print(f"    [{ev.start}:{ev.end}] '{ev.quote}' — {ev.comment[:60]}")
    print("  경고:")
    for w in response.warnings:
        print(f"    - {w[:115]}")
    print()


def check_warmup() -> bool:
    """예열이 실제로 효과가 있는지 별도 프로세스 두 개를 띄워 비교한다.

    같은 프로세스 안에서는 Kiwi 가 이미 올라와 있어 비교가 되지 않는다.
    그래서 '예열 없이 첫 채점'과 '예열 뒤 첫 채점'을 각각 새 프로세스에서 잰다.
    """
    measure_script = r'''
import sys, time
sys.path.insert(0, r"{root}")
from fastapi.testclient import TestClient
import src.api as api

WARM = {warm}

body = {{
    "submission_id": "warm-1", "mode": "speaking",
    "answer_text": "지난주에 기계가 멈춰서 전원을 차단하고 반장님께 보고드렸습니다.",
    "item": {{"item_id": "i1", "prompt": "상황을 설명하십시오.",
             "checklist": [{{"id": "c1", "description": "상황을 설명했는가"}}]}},
}}

if WARM:
    # lifespan 을 태워서 서버 기동 시 예열이 걸리게 한다
    with TestClient(api.app) as client:
        started = time.perf_counter()
        client.post("/score", json=body)
        print(round((time.perf_counter() - started) * 1000, 1))
else:
    # lifespan 없이 앱만 호출한다 = 예열이 걸리지 않은 상태
    client = TestClient(api.app)
    started = time.perf_counter()
    client.post("/score", json=body)
    print(round((time.perf_counter() - started) * 1000, 1))
'''

    def run(warm: bool) -> float:
        code = measure_script.format(root=str(ROOT), warm="True" if warm else "False")
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, cwd=str(ROOT),
        )
        lines = [ln for ln in result.stdout.strip().splitlines() if ln.strip()]
        return float(lines[-1])

    cold = run(warm=False)
    warm = run(warm=True)

    print("=" * 78)
    print("서버 예열 효과 측정 (각각 새 프로세스에서 첫 /score 호출 시간)")
    print("=" * 78)
    print(f"  예열 없음 -> 첫 채점 {cold:8.1f} ms")
    print(f"  예열 있음 -> 첫 채점 {warm:8.1f} ms")
    print(f"  차이: {cold - warm:.1f} ms 단축")
    ok = warm < cold * 0.5
    print(f"  [{'OK ' if ok else 'NG '}] 예열 뒤 첫 호출이 절반 이하로 줄었다")
    print()
    return ok


def main() -> None:
    failed = 0

    # ── 케이스 1: 전 문항 채점 완료 ─────────────────────────────
    expected = [
        ExpectedItem(item_id="s1", mode=Mode.SPEAKING),
        ExpectedItem(item_id="s2", mode=Mode.SPEAKING),
        ExpectedItem(item_id="s3", mode=Mode.SPEAKING),
        ExpectedItem(item_id="w1", mode=Mode.WRITING),
        ExpectedItem(item_id="w2", mode=Mode.WRITING),
    ]
    complete_items = [
        make_item("s1", Mode.SPEAKING, 82, 78),
        make_item("s2", Mode.SPEAKING, 76, 80),
        make_item("s3", Mode.SPEAKING, 88, 74),
        make_item("w1", Mode.WRITING, 79, 83),
        make_item("w2", Mode.WRITING, 85, 77),
    ]
    normal = finalize_session(
        FinalizeRequest(session_id="sess-001", candidate_id="cand-77",
                        items=complete_items, expected_items=expected)
    )
    show("① 정상 케이스 — 5문항 전부 채점 완료", normal)

    # ── 케이스 2: 마지막 문항이 아직 채점 중 ────────────────────
    partial_items = [
        make_item("s1", Mode.SPEAKING, 82, 78),
        make_item("s2", Mode.SPEAKING, 76, 80),
        make_item("s3", Mode.SPEAKING, 88, 74),
        make_item("w1", Mode.WRITING, 79, 83),
        # w2 는 아직 채점 중이라고 표시해서 보낸다
        make_item("w2", Mode.WRITING, 0, 0, status=ItemScoreStatus.PENDING),
    ]
    partial = finalize_session(
        FinalizeRequest(session_id="sess-002", candidate_id="cand-78",
                        items=partial_items, expected_items=expected)
    )
    show("② 마지막 문항이 아직 채점 중 — 재정규화되는지", partial)

    # ── 케이스 3: 결과가 아예 안 넘어온 문항이 있는 경우 ────────
    missing = finalize_session(
        FinalizeRequest(session_id="sess-003", items=complete_items[:4],
                        expected_items=expected)
    )
    show("③ 마지막 문항 결과가 아예 안 넘어옴", missing)

    # ── 케이스 4: 채점된 문항이 너무 적어 등급 확정 불가 ────────
    insufficient = finalize_session(
        FinalizeRequest(session_id="sess-004", items=complete_items[:2],
                        expected_items=expected)
    )
    show("④ 5문항 중 2문항만 채점 — 등급 확정하지 않아야 함", insufficient)

    # ── 케이스 5: 말하기 A / 쓰기 E 급차이 ──────────────────────
    gap_items = [
        make_item("s1", Mode.SPEAKING, 95, 93),
        make_item("s2", Mode.SPEAKING, 92, 96),
        make_item("s3", Mode.SPEAKING, 94, 90),
        make_item("w1", Mode.WRITING, 22, 18),
        make_item("w2", Mode.WRITING, 25, 20),
    ]
    gap = finalize_session(
        FinalizeRequest(session_id="sess-005", items=gap_items, expected_items=expected)
    )
    show("⑤ 말하기 최상위 / 쓰기 최하위 — 교차검증 신호가 떠야 함", gap)

    # ── 케이스 6: 문항 가중치를 다르게 주는 경우 ────────────────
    weighted = finalize_session(
        FinalizeRequest(
            session_id="sess-006",
            items=[
                make_item("s1", Mode.SPEAKING, 90, 90, weight=3.0),
                make_item("s2", Mode.SPEAKING, 40, 40, weight=1.0),
            ],
            expected_items=[
                ExpectedItem(item_id="s1", mode=Mode.SPEAKING, weight=3.0),
                ExpectedItem(item_id="s2", mode=Mode.SPEAKING, weight=1.0),
            ],
            options=FinalizeOptions(min_scored_items=2),
        )
    )
    show("⑥ 문항 가중치 3:1 — 비중이 큰 문항 쪽으로 끌리는지", weighted)

    # ── 예열 측정 ───────────────────────────────────────────────
    if not check_warmup():
        failed += 1

    # ── 확인 항목 ───────────────────────────────────────────────
    print("-" * 78)
    print("확인 항목")
    print("-" * 78)
    checks = [
        ("정상 케이스가 complete 상태로 나온다",
         normal.status == FinalizeStatus.COMPLETE),
        ("종합 점수·등급·백분위가 모두 나온다",
         normal.overall_score is not None and normal.overall_grade is not None
         and normal.percentile is not None),
        ("영역별 최종 점수에 문항별 기여 내역이 붙는다",
         all(s.contributions for s in normal.subscores if s.score is not None)),
        ("발화 전달력은 최종에서도 not_evaluated 로 남는다",
         any(s.area == ScoreArea.DELIVERY and s.status == AreaStatus.NOT_EVALUATED
             for s in normal.subscores)),
        ("채점 중인 문항이 있으면 partial 상태가 된다",
         partial.status == FinalizeStatus.PARTIAL),
        ("채점 중인 문항이 warnings 에 남는다",
         any("채점이 끝나지 않은 문항" in w for w in partial.warnings)),
        ("빠진 문항이 있어도 등급이 나온다",
         partial.overall_grade is not None),
        ("빠진 문항을 뺀 뒤 남은 문항 비중 합이 1이다",
         all(abs(sum(c.weight for c in s.contributions) - 1.0) < 1e-6
             for s in partial.subscores if s.contributions)),
        ("결과가 안 넘어온 문항도 warnings 에 남는다",
         any("결과가 넘어오지 않은 문항" in w for w in missing.warnings)),
        ("채점 문항이 부족하면 등급을 확정하지 않는다",
         insufficient.status == FinalizeStatus.INSUFFICIENT
         and insufficient.overall_grade is None),
        ("부족 판단 기준이 응답에 실린다",
         insufficient.item_coverage.min_scored_ratio == 0.7
         and insufficient.item_coverage.min_scored_items == 3),
        ("급차이가 크면 교차검증 플래그가 뜬다",
         gap.cross_mode_check.flagged is True),
        ("교차검증은 신호일 뿐 판정이 아니라고 명시한다",
         "판정이 아니다" in gap.cross_mode_check.note),
        ("정상 케이스에서는 교차검증 플래그가 안 뜬다",
         normal.cross_mode_check.flagged is False),
        ("문항 가중치가 반영된다(3:1 이면 90점 쪽으로 끌린다)",
         weighted.overall_score > 70),
        ("임시값 표시가 meta 에 실린다",
         weighted.meta.weights_provisional is True
         and weighted.meta.cutoffs_from_anchor_answers is False
         and weighted.meta.percentile_provisional is True),
        ("백분위 환산이 단조증가한다",
         to_percentile(40) < to_percentile(65) < to_percentile(90)),
    ]
    for desc, ok in checks:
        print(f"  [{'OK ' if ok else 'NG '}] {desc}")
        if not ok:
            failed += 1

    print()
    if failed:
        print(f"확인 실패 {failed}건.")
        sys.exit(1)
    print("최종 등급·예열 확인 전부 통과.")


if __name__ == "__main__":
    main()
