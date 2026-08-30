"""파이프라인 전체를 실제 답안으로 한 번 돌려서 결과를 눈으로 보는 스크립트.

/score 4문항(말하기 3 + 쓰기 1) -> /finalize 까지 실제 경로를 그대로 탄다.
"""

import json
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
# 말하기 문항은 실제 문항 파일(items/speaking_v1.json)에서 그대로 읽어 온다.
# 시연 대본·백엔드 DB·이 데모가 모두 같은 문항을 쓰게 하려는 것이다.
# (쓰기 문항은 아직 파일로 정리하지 않아 아래에 직접 적어 둔다)
# ---------------------------------------------------------------------------

ITEMS_PATH = pathlib.Path(__file__).resolve().parent.parent / "items" / "speaking_v1.json"


def load_speaking_item(item_id):
    """말하기 문항 파일에서 문항 하나를 찾아 채점용 ItemInfo 로 만든다."""
    # 문항 파일 전체를 읽는다 (items 목록 안에 문항 객체들이 들어 있다)
    data = json.loads(ITEMS_PATH.read_text(encoding="utf-8"))

    # 번호가 같은 문항을 찾으면 그대로 ItemInfo 에 넣는다.
    # 파일의 칸 이름(prompt, checklist, scene_description ...)을 채점 스키마와
    # 똑같이 맞춰 두었기 때문에 변환 없이 통째로 넘길 수 있다.
    for item in data.get("items", []):
        if item.get("item_id") == item_id:
            return ItemInfo(**item)

    # 문항 번호가 바뀌었는데 이 스크립트만 옛날 것이면 조용히 틀린 채점을 하지 말고
    # 여기서 바로 멈춘다
    raise SystemExit(f"{ITEMS_PATH.name} 에 {item_id} 문항이 없습니다")


# ---------------------------------------------------------------------------
# 답안 4개. 실제 현장 상황을 가정한, 체크리스트를 대체로 만족하는 좋은 답안이다.
# 다만 외국인 노동자의 실제 답안처럼 보이도록 띄어쓰기 흔들림("표지 입니다")과
# 맞춤법 오류("여덜시")를 일부러 조금씩 남겨 두었다 — 오류 자질이 실제로
# 잡히는지도 이 스크립트로 같이 확인하려는 것이다.
# 말하기 세 문항은 음성이 아니라 전사 텍스트(answer_text)를 직접 넣는 경로라
# 받아쓰기(LoRA) 서버가 꺼져 있어도 이 스크립트는 끝까지 돈다.
# ---------------------------------------------------------------------------

# SPK-101 · 비상대피로 표지의 뜻을 설명하는 문항
ITEM1 = load_speaking_item("SPK-101")
ANSWER1 = (
    "이거는 비상대피로 표지 입니다 "
    "초록색 바탕에 빨간 동그라미가 있고 그 안에 화살표가 있습니다 "
    "화살표는 위쪽을 가리키고 있습니다 "
    "불이 나거나 지진이 나면 이 화살표를 따라서 밖으로 나가라는 뜻입니다 "
    "위험할 때 나가는 길을 알려주는 표지 입니다"
)

# SPK-104 · 안전모 없이 사다리를 든 동료에게 위험을 알리는 문항
# (시연 대본 장면 2에서 시연자가 마이크에 말하는 문장과 같은 발화다)
ITEM2 = load_speaking_item("SPK-104")
ANSWER2 = (
    "저기요 잠깐만요 "
    "안전모 안 썼어요 그렇게 하면 위험해요 "
    "그렇게 사다리 올라가면 떨어져서 머리 다쳐요 "
    "안전모 먼저 쓰세요 "
    "제가 사다리 잡아 줄게요"
)

# SPK-105 · 질문 음성("왜 늦으셨나요?")을 듣고 대답하는 문항
# 이미지가 아니라 소리를 듣는 문항이라 화면에 띄울 것은 audio 칸(SPK-105.wav)에 있다.
# 그 소리 파일은 아직 없지만 질문 문장이 prompt 에 글로 들어 있어서 채점은 지금도 된다.
ITEM_Q = load_speaking_item("SPK-105")
ANSWER_Q = (
    "죄송합니다 오늘 늦었습니다 "
    "아침에 알람이 안 울려서 늦게 일어났습니다 "
    "그리고 정류장에서 버스가 안 와서 삼십분쯤 기다렸습니다 "
    "그래서 회사에 늦게 도착했습니다 "
    "다음부터는 일찍 나오겠습니다 정말 죄송합니다"
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


# 채점에 넣을 3건. 앞의 값은 제출 번호인데, 화면에서 알아보기 쉽게 문항 번호를 그대로 쓴다.
CASES = [
    (ITEM1.item_id, Mode.SPEAKING, ANSWER1, ITEM1, TranscriptInput(correct=True, nationality="베트남")),
    (ITEM2.item_id, Mode.SPEAKING, ANSWER2, ITEM2, TranscriptInput(correct=True, nationality="베트남")),
    (ITEM_Q.item_id, Mode.SPEAKING, ANSWER_Q, ITEM_Q, TranscriptInput(correct=True, nationality="베트남")),
    (ITEM3.item_id, Mode.WRITING, ANSWER3, ITEM3, None),
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
            # 인용이 있는 판정(LLM)은 원문 그대로를 보여 준다.
            # [보너스] 항목처럼 코드가 계산한 판정은 인용이 없고 설명이 근거라서,
            # 그것까지 안 찍으면 화면에서는 근거가 없는 것처럼 보인다
            if ev.quote:
                print(f"        인용: \u201c{ev.quote}\u201d")
            elif ev.comment:
                print(f"        근거: {ev.comment}")

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
    print(f"  채점 {len(CASES)}문항 총 소요시간: {total_ms}ms")


if __name__ == "__main__":
    main()
