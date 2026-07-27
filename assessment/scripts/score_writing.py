"""쓰기 답안 하나를 직접 넣어 보고 점수를 눈으로 확인하는 도구.

터미널에서 글을 바로 넣어 채점해 볼 수 있게 만든 것이다.
정해진 답안으로만 도는 check_pipeline_demo.py 와 달리,
문항과 답안을 그때그때 바꿔 가며 감을 잡는 용도다.

쓰는 법:
    python scripts/score_writing.py "오늘 삼번 라인에서 포장 작업을 하였습니다."

    python scripts/score_writing.py --file answer.txt

    python scripts/score_writing.py --speaking "반장님 기계가 멈췄습니다"

    # 문항과 체크리스트도 바꿀 수 있다
    python scripts/score_writing.py "..." ^
        --prompt "오늘 작업 내용을 작업일지에 기록하세요." ^
        --check "작업 내용을 기록했는가" --check "발생한 문제를 기록했는가"
"""

from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from src.llm.client import GeminiClient
from src.scoring.pipeline import score_submission
from src.scoring.schema import (
    ChecklistItem,
    ItemInfo,
    Mode,
    ScoreOptions,
    ScoreRequest,
    TranscriptInput,
)

# 문항을 따로 안 주면 쓰는 기본 문항. 작업일지 쓰기다.
DEFAULT_PROMPT = "오늘 작업한 내용을 작업일지에 기록하세요. 작업 내용, 발생한 문제, 처리 결과를 포함하세요."
DEFAULT_CHECKS = [
    "작업 내용을 기록했는가",
    "발생한 문제를 기록했는가",
    "처리 결과를 기록했는가",
]

W = 74


def rule(title: str = "") -> None:
    if title:
        print("\n" + "=" * W)
        print(f"  {title}")
        print("=" * W)
    else:
        print("-" * W)


def short(text: str, n: int = 150) -> str:
    """긴 경고 문구를 화면에서만 줄인다."""
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[:n] + f" …(+{len(text) - n}자)"


def build_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="답안 하나를 채점해서 점수와 근거를 보여준다.",
    )
    p.add_argument("answer", nargs="?", default=None, help="채점할 답안 (따옴표로 감싼다)")
    p.add_argument("--file", help="답안을 파일에서 읽는다 (UTF-8)")
    p.add_argument("--speaking", action="store_true", help="말하기 모드로 채점한다")
    p.add_argument("--prompt", default=DEFAULT_PROMPT, help="문항 지시문")
    p.add_argument(
        "--check", action="append", default=None,
        help="체크리스트 항목. 여러 번 쓸 수 있다",
    )
    p.add_argument(
        "--no-llm", action="store_true",
        help="LLM 없이 규칙 자질만으로 채점한다(공짜·즉시). 대체 경로 확인용",
    )
    return p.parse_args()


def read_answer(args: argparse.Namespace) -> str:
    """답안을 인자·파일·표준입력 중 어디서든 받아 준다."""
    if args.file:
        return pathlib.Path(args.file).read_text(encoding="utf-8").strip()
    if args.answer:
        return args.answer.strip()
    # 아무것도 안 주면 붙여넣기를 기다린다(여러 줄 입력 후 Ctrl+Z, Enter)
    print("답안을 입력하세요. 다 쓰면 Ctrl+Z 후 Enter (Windows):")
    return sys.stdin.read().strip()


def main() -> int:
    args = build_args()
    answer = read_answer(args)
    if not answer:
        print("답안이 비어 있습니다.")
        return 1

    mode = Mode.SPEAKING if args.speaking else Mode.WRITING
    checks = args.check or DEFAULT_CHECKS

    item = ItemInfo(
        item_id="adhoc-1",
        prompt=args.prompt,
        expected_register="formal",
        checklist=[
            ChecklistItem(id=f"c{i + 1}", description=text)
            for i, text in enumerate(checks)
        ],
        # LLM을 못 쓸 때 쓰는 임시 대체 판정용 핵심어
        reference_keywords=[],
    )

    request = ScoreRequest(
        submission_id="adhoc",
        mode=mode,
        answer_text=answer,
        item=item,
        options=ScoreOptions(use_llm=not args.no_llm),
        # 말하기일 때만 전사 보정을 켠다(쓰기는 응시자가 직접 친 글이라 보정하지 않는다)
        transcript=TranscriptInput(correct=True) if mode == Mode.SPEAKING else None,
    )

    client = GeminiClient()
    rule("입력")
    print(f"  모드   : {mode.value}")
    print(f"  모델   : {client.model_name} (사용가능 {client.available})")
    print(f"  문항   : {args.prompt}")
    print(f"\n  답안   : {answer}")

    response = score_submission(request, client=client)

    rule("결과")
    print(f"\n  종합 {response.overall_score}점   등급 {response.overall_grade}")

    print("\n  [영역별]")
    for s in response.subscores:
        score = "채점 안 함" if s.score is None else f"{s.score:>5.1f}점"
        print(f"    {s.label:<14} {score}  (비중 {s.weight:.2f}, {s.status.value})")

    print("\n  [점수가 어디서 왔나]")
    for s in response.subscores:
        if not s.contributions:
            continue
        print(f"    · {s.label}")
        for c in sorted(s.contributions, key=lambda x: -x.points):
            raw = "—" if c.raw_value is None else f"{c.raw_value:g}"
            print(
                f"        {c.feature_name:<20} raw={raw:>7}  "
                f"norm={c.normalized:.2f} × w={c.weight:.2f} → {c.points:>5.1f}점"
            )

    print("\n  [체크리스트]")
    for r in response.checklist_results:
        mark = "O" if r.met else "X"
        print(f"    [{mark}] {r.description}  ({r.source.value})")
        for ev in r.evidence[:1]:
            if ev.quote:
                print(f"          인용: “{ev.quote}”")
            elif ev.comment:
                print(f"          사유: {short(ev.comment, 80)}")

    # 오류 자질은 몇 건 잡혔는지가 궁금한 부분이라 따로 뽑아 준다
    errors = [f for f in response.features if f.id.startswith("error_") and f.value is not None]
    if errors:
        print("\n  [문법 오류]")
        for f in errors:
            count = int(f.components.get("error_count", 0))
            mark = f"{count}건" if count else "없음"
            print(f"    {f.name:<14} {mark}")
            for ev in f.evidence[:3]:
                if ev.quote:
                    print(f"        “{ev.quote}” — {short(ev.comment, 70)}")

    m = response.meta
    print("\n  [신뢰도]")
    mark = "화면에 띄워도 됨" if m.safe_to_show_candidate else "띄우면 안 됨"
    print(f"    {m.reliability.value}  ({mark})")
    if m.reliability_reason:
        print(f"      └ {m.reliability_reason}")

    print(f"\n  [소요시간] {m.timings_ms}")

    if response.warnings:
        print("\n  [경고]")
        for w in response.warnings:
            print(f"    ! {short(w)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
