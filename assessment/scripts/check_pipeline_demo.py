"""파이프라인 전체를 실제 답안으로 한 번 돌려서 결과를 눈으로 보는 스크립트.

/score 3문항(말하기 2 + 쓰기 1) -> /finalize 까지 실제 경로를 그대로 탄다.
"""

import os
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from src.llm.client import GeminiClient
from src.scoring.finalize import finalize_session
from src.scoring.pipeline import score_submission
from src.scoring.schema import (
    ChecklistItem,
    ExpectedItem,
    FinalizeItem,
    FinalizeRequest,
    ItemInfo,
    Mode,
    ScoreOptions,
    ScoreRequest,
    TranscriptInput,
)

W = 78


def short(text, n=160):
    """경고 문구에 429 JSON 통째로 박혀 나오는 것을 화면에서만 줄인다."""
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[:n] + f" …(+{len(text) - n}자)"


def rule(title=""):
    if title:
        print("\n" + "=" * W)
        print(f"  {title}")
        print("=" * W)
    else:
        print("-" * W)


# ---------------------------------------------------------------------------
# 답안 3개. 실제 제조업 현장 상황을 가정했다.
# 학습자의 진짜 오류(안 돼습니다 / -에서 오용)와 STT가 잘못 받아쓸 만한 것
# (차단하구, 포장 기가)을 일부러 섞어 두었다.
# ---------------------------------------------------------------------------

ITEM1 = ItemInfo(
    item_id="SPK-001",
    prompt="작업 중 기계가 갑자기 멈췄습니다. 반장님에게 상황을 보고하고 어떻게 해야 할지 물어보세요.",
    item_type="free_response",
    expected_register="formal",
    checklist=[
        ChecklistItem(id="c1", description="어떤 문제가 생겼는지 구체적으로 말했는가", weight=1.5),
        ChecklistItem(id="c2", description="자신이 이미 시도한 조치를 말했는가", weight=1.0),
        ChecklistItem(id="c3", description="다음에 어떻게 할지 지시를 요청했는가", weight=1.5),
        ChecklistItem(id="c4", description="상급자에게 맞는 높임 표현을 사용했는가", weight=1.0),
    ],
    reference_keywords=["기계", "멈추", "반장", "정비"],
)
ANSWER1 = (
    "반장님 지금 삼번 라인 포장 기가 갑자기 멈췄습니다 "
    "빨간 불이 계속 깜박깜박 합니다 "
    "제가 전원 버튼을 다시 눌러 봤는데 안 돼습니다 "
    "기계 안에 종이가 끼여 있는 것 같습니다 "
    "제가 지금 전원을 차단하구 정비팀에 연락할까요 "
    "아니면 반장님 오실 때까지 기다릴까요"
)

ITEM2 = ItemInfo(
    item_id="SPK-002",
    prompt="동료가 안전모를 쓰지 않고 작업하고 있습니다. 동료에게 주의를 주고 이유를 설명하세요.",
    item_type="free_response",
    expected_register="polite",
    checklist=[
        ChecklistItem(id="c1", description="안전모를 써야 한다고 지적했는가", weight=1.5),
        ChecklistItem(id="c2", description="왜 위험한지 이유를 설명했는가", weight=1.5),
        ChecklistItem(id="c3", description="상대를 존중하는 표현을 썼는가", weight=1.0),
    ],
    reference_keywords=["안전모", "위험", "다치"],
)
ANSWER2 = (
    "저기요 잠깐만요 안전모 안 쓰고 있어요 "
    "여기 위에서 물건이 떨어질 수 있어서 위험해요 "
    "지난달에도 이번 공장에서 사람이 머리 다쳤어요 "
    "제가 하나 가져다 드릴까요 같이 조심합시다"
)

ITEM3 = ItemInfo(
    item_id="WRT-001",
    prompt="오늘 작업한 내용을 작업일지에 기록하세요. 작업 내용, 발생한 문제, 처리 결과를 포함하세요.",
    item_type="free_response",
    expected_register="formal",
    checklist=[
        ChecklistItem(id="c1", description="작업 내용을 기록했는가", weight=1.0),
        ChecklistItem(id="c2", description="발생한 문제를 기록했는가", weight=1.5),
        ChecklistItem(id="c3", description="처리 결과를 기록했는가", weight=1.5),
    ],
    reference_keywords=["작업", "문제", "처리"],
)
ANSWER3 = (
    "오늘 오전 여덜시부터 삼번 라인에서 포장 작업을 하였습니다. "
    "오전 열시쯤에 포장기가 멈추는 문제가 발생했습니다. "
    "확인해 보니 기계 안에 종이가 끼여 있었습니다. "
    "반장님께 보고를 드리고 정비팀이 와서 종이를 제거하였습니다. "
    "삼십분 후에 작업을 다시 시작했고 오후에는 문제가 없었습니다."
)


CASES = [
    ("SPK-001", Mode.SPEAKING, ANSWER1, ITEM1, TranscriptInput(correct=True, nationality="베트남")),
    ("SPK-002", Mode.SPEAKING, ANSWER2, ITEM2, TranscriptInput(correct=True, nationality="베트남")),
    ("WRT-001", Mode.WRITING, ANSWER3, ITEM3, None),
]


def show_response(resp, answer):
    print(f"\n[종합] {resp.overall_score}점  등급 {resp.overall_grade}")

    print("\n[영역별]")
    for s in resp.subscores:
        score = "채점 안 함" if s.score is None else f"{s.score:>5.1f}점"
        print(f"  {s.label:<14} {score}  (비중 {s.weight:.2f}, {s.status.value})")
        if s.note:
            print(f"       └ {short(s.note)}")

    print("\n[영역 점수의 출처 — 자질별 기여]")
    for s in resp.subscores:
        if not s.contributions:
            continue
        print(f"  · {s.label}")
        for c in sorted(s.contributions, key=lambda x: -x.points)[:6]:
            raw = "—" if c.raw_value is None else f"{c.raw_value:g}"
            print(
                f"      {c.feature_name:<22} raw={raw:>7}  "
                f"norm={c.normalized:.2f} × w={c.weight:.2f} → {c.points:>5.1f}점"
            )

    print("\n[체크리스트 판정]")
    for r in resp.checklist_results:
        mark = "O" if r.met else "X"
        print(f"  [{mark}] {r.description}  (w={r.weight}, {r.source.value})")
        for ev in r.evidence[:2]:
            print(f"        인용: \u201c{ev.quote}\u201d")

    m = resp.meta
    print("\n[STT 전사 보정]")
    if not m.transcript_correction_applied:
        print("  적용 안 됨")
    else:
        print(f"  보정 {m.transcript_change_count}건 / 신뢰도 낮음 표시 {m.transcript_low_confidence_errors}건")
        print(f"  원문 : {answer}")
        print(f"  보정 : {m.transcript_corrected_text}")
        for ev in m.transcript_diff:
            print(f"    - 원문 {ev.start}~{ev.end} \u201c{ev.quote}\u201d : {ev.comment}")

    print("\n[신뢰도]")
    mark = "OK" if m.safe_to_show_candidate else "화면에 띄우면 안 됨"
    print(f"  {m.reliability.value}  ({mark})")
    if m.reliability_reason:
        print(f"    └ {m.reliability_reason}")

    print("\n[메타]")
    print(f"  LLM 사용 {m.llm_used} / 모델 {m.llm_model} / 버려진 인용 {m.dropped_citations}")
    print(f"  소요시간 {m.timings_ms}")

    if resp.warnings:
        print("\n[경고]")
        for w in resp.warnings:
            print(f"  ! {short(w)}")


def main():
    model = os.getenv("GEMINI_MODEL", "(기본값)")
    client = GeminiClient()
    rule("실행 조건")
    print(f"  모델        : {client.model_name}  (env GEMINI_MODEL={model})")
    print(f"  LLM 사용가능: {client.available}")

    responses = []
    total_started = time.perf_counter()

    for sid, mode, answer, item, transcript in CASES:
        rule(f"{sid} [{mode.value}] {item.prompt[:40]}...")
        print(f"\n답안: {answer}")
        req = ScoreRequest(
            submission_id=sid,
            mode=mode,
            answer_text=answer,
            item=item,
            options=ScoreOptions(use_llm=True),
            transcript=transcript,
        )
        resp = score_submission(req, client=client)
        responses.append((resp, item, mode))
        show_response(resp, answer)

    total_ms = round((time.perf_counter() - total_started) * 1000)

    # ------------------------------------------------------------------
    # 시험 전체 최종 등급
    # ------------------------------------------------------------------
    rule("FINALIZE — 시험 전체 최종 결과")
    freq = FinalizeRequest(
        session_id="demo-session-001",
        candidate_id="cand-0042",
        items=[
            FinalizeItem(
                item_id=r.item_id,
                mode=r.mode,
                overall_score=r.overall_score,
                subscores=r.subscores,
                # meta 를 함께 넘겨야 문항별 신뢰도가 최종 결과까지 따라온다
                meta=r.meta,
                status="scored",
            )
            for r, _, _ in responses
        ],
        expected_items=[
            ExpectedItem(item_id=i.item_id, mode=m) for _, i, m in responses
        ],
    )
    fin = finalize_session(freq)

    print(f"\n  상태     : {fin.status.value}")
    print(f"  최종점수 : {fin.overall_score}점")
    print(f"  최종등급 : {fin.overall_grade}")
    print(f"  백분위   : {fin.percentile}")
    fm = fin.meta
    mark = "OK" if fm.safe_to_show_candidate else "화면에 띄우면 안 됨"
    print(f"  신뢰도   : {fm.reliability.value}  ({mark})")
    if fm.unreliable_item_ids:
        print(f"    └ 다시 채점할 문항: {', '.join(fm.unreliable_item_ids)}")

    print("\n  [영역별 최종]")
    for s in fin.subscores:
        score = "채점 안 함" if s.score is None else f"{s.score:>5.1f}점"
        print(f"    {s.label:<14} {score}  (비중 {s.weight:.2f})")

    if getattr(fin, "mode_results", None):
        print("\n  [말하기/쓰기 비교]")
        for mr in fin.mode_results:
            print(
                f"    {mr.mode.value:<10} {mr.score}점  등급 {mr.grade}  "
                f"문항 {mr.scored_item_count}/{mr.expected_item_count}"
            )

    if getattr(fin, "cross_mode_check", None):
        c = fin.cross_mode_check
        print(
            f"\n  [교차검증 신호] 비교가능={c.comparable} "
            f"말하기={c.speaking_grade} 쓰기={c.writing_grade} 등급차={c.grade_gap}칸"
        )

    if fin.warnings:
        print("\n  [경고]")
        for w in fin.warnings:
            print(f"    ! {short(w)}")

    rule("합계")
    print(f"  채점 3문항 총 소요시간: {total_ms}ms")


if __name__ == "__main__":
    main()
