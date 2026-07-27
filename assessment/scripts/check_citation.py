"""인용 검증·폐기 로직이 실제로 동작하는지 확인하는 스크립트.

LLM API 키 없이 돌아간다.
확인하려는 것: 원문에 없는 인용이 진짜로 버려지는가, 그리고
띄어쓰기만 다른 멀쩡한 인용까지 억울하게 버려지지는 않는가.

실행: .venv\\Scripts\\python.exe scripts\\check_citation.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.llm.citation import filter_by_citation, verify_citation  # noqa: E402

# 채점 대상이 될 답안 원문. 아래 모든 인용은 이 글과 대조된다.
SOURCE = (
    "지난주 화요일에 3번 라인 기계가 멈췄습니다. "
    "저는 전원을 차단하고 반장님께 보고드렸습니다. "
    "정비팀이 벨트를 교체한 뒤 다시 작동했습니다."
)

# (설명, 인용, 통과해야 하는가)
CASES: list[tuple[str, str, bool]] = [
    ("원문에 그대로 있는 인용", "반장님께 보고드렸습니다", True),
    ("띄어쓰기가 다른 인용", "반장님께보고드렸습니다", True),
    ("문장부호가 덧붙은 인용", "'정비팀이 벨트를 교체한 뒤'", True),
    ("문장 전체 인용", "저는 전원을 차단하고 반장님께 보고드렸습니다.", True),
    ("LLM이 지어낸 문장", "저는 즉시 119에 신고했습니다", False),
    ("있을 법하지만 없는 말", "안전모를 착용했습니다", False),
    ("낱말 순서를 바꾼 인용", "보고드렸습니다 반장님께", False),
    ("한 글자짜리 인용", "저", False),
    ("빈 인용", "", False),
    ("공백뿐인 인용", "   ", False),
]


def main() -> None:
    print("=" * 78)
    print("인용 검증 확인 (LLM 키 불필요)")
    print("=" * 78)
    print(f"[답안 원문] {SOURCE}")
    print()

    failed = 0
    for desc, quote, should_pass in CASES:
        check = verify_citation(SOURCE, quote)
        ok = check.ok == should_pass
        if not ok:
            failed += 1

        mark = "OK " if ok else "NG "
        verdict = "통과" if check.ok else "폐기"
        print(f"  [{mark}] {desc}")
        print(f"        인용: '{quote}'")
        if check.ok:
            print(f"        -> {verdict} / 원문 위치 [{check.start}:{check.end}] "
                  f"실제 구간: '{check.matched_text}'")
        else:
            print(f"        -> {verdict} / 사유: {check.reason}")
    print()

    # 실제 사용 방식대로, LLM 응답 형태의 목록을 통째로 걸러 본다.
    print("-" * 78)
    print("LLM 응답 목록 일괄 필터 (오류 자질 추출에서 쓰는 방식 그대로)")
    print("-" * 78)
    llm_like_items = [
        {"type": "josa", "quote": "3번 라인 기계가 멈췄습니다",
         "correction": "3번 라인 기계가 멈췄습니다", "explanation": "정상"},
        {"type": "honorific", "quote": "반장님이 오셨습니다",
         "correction": "반장님께서 오셨습니다", "explanation": "원문에 없는 문장(지어냄)"},
        {"type": "word_choice", "quote": "벨트를 교체한",
         "correction": "벨트를 갈아 끼운", "explanation": "정상"},
        {"type": "josa", "explanation": "인용 필드를 아예 안 보냄"},
        "형식이 깨진 항목",
    ]
    result = filter_by_citation(SOURCE, llm_like_items)
    print(f"  들어온 항목 {len(llm_like_items)}개 -> 남김 {len(result.kept)}개 / "
          f"버림 {result.dropped_count}개")
    for item in result.kept:
        print(f"    남김: '{item['quote']}' "
              f"(원문 [{item['_citation_start']}:{item['_citation_end']}])")
    for message in result.drop_messages:
        print(f"    {message}")

    expected_kept, expected_dropped = 2, 3
    batch_ok = len(result.kept) == expected_kept and result.dropped_count == expected_dropped
    print(f"\n  [{'OK ' if batch_ok else 'NG '}] "
          f"기대값(남김 {expected_kept} / 버림 {expected_dropped})과 일치")
    if not batch_ok:
        failed += 1

    print()
    if failed:
        print(f"확인 실패 {failed}건 — 인용 검증 로직을 손봐야 한다.")
        sys.exit(1)
    print("인용 검증 확인 전부 통과.")


if __name__ == "__main__":
    main()
