"""Kiwi 규칙 자질이 실제로 값을 내는지, 값의 방향이 상식적인지 눈으로 확인하는 스크립트.

LLM API 키 없이도 돌아간다.
잘 쓴 답안과 못 쓴 답안을 나란히 넣어, 잘 쓴 쪽이 어휘 다양도·고급 어휘 비율에서
실제로 더 높게 나오는지 확인하는 것이 목적이다.
방향이 뒤집혀 있으면 자질 계산이 틀렸다는 뜻이다.

실행: .venv\\Scripts\\python.exe scripts\\check_kiwi_features.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.features.lexical import extract_lexical_features  # noqa: E402
from src.scoring.schema import FeatureStatus, Mode  # noqa: E402

# 같은 문항("작업 중 기계가 고장 났을 때 어떻게 했는지 말하시오")에 대한 세 가지 답안.
SAMPLES: list[tuple[str, str, Mode]] = [
    (
        "A. 잘 쓴 답안 (말하기)",
        "지난주 화요일 오전에 3번 라인 포장 기계가 갑자기 멈췄습니다. "
        "저는 먼저 전원을 차단하고 주변 동료들에게 접근하지 말라고 알렸습니다. "
        "그다음 반장님께 상황을 보고드렸고, 반장님이 오셔서 함께 원인을 파악했습니다. "
        "확인해 보니 벨트가 헐거워져서 생긴 문제였는데, 저희가 임의로 손대면 위험하기 때문에 "
        "정비팀에 수리를 요청했습니다. 수리가 끝난 뒤에는 재발을 막기 위해 "
        "매일 작업 시작 전에 벨트 상태를 점검하는 절차를 새로 만들었습니다.",
        Mode.SPEAKING,
    ),
    (
        "B. 못 쓴 답안 (말하기, 반말 혼입)",
        "기계가 고장 났어요. 그래서 기계를 봤어요. 기계가 안 돼요. "
        "그래서 사람을 불렀어요. 사람이 기계를 고쳤어. 그래서 기계가 됐어. "
        "기계가 좋아요. 나는 기계를 했어요.",
        Mode.SPEAKING,
    ),
    (
        "C. 쓰기 답안 (띄어쓰기 오류 포함)",
        "지난주에 포장기계가 고장났습니다. 저는즉시 전원을차단하고 반장님께 보고했습니다. "
        "정비팀이 점검한결과 벨트가 헐거워진 것이 원인이었으며, 재발방지를 위해 "
        "일일 점검 절차를 도입하였습니다.",
        Mode.WRITING,
    ),
]


def render_table(rows: list[tuple[str, ...]], headers: tuple[str, ...]) -> str:
    """표를 문자열로 그린다. 한글 폭을 대충 2칸으로 잡아 자릿수를 맞춘다."""

    def width(s: str) -> int:
        return sum(2 if ord(ch) > 0x1100 else 1 for ch in s)

    all_rows = [headers] + rows
    col_count = len(headers)
    widths = [max(width(r[i]) for r in all_rows) for i in range(col_count)]

    def line(row: tuple[str, ...]) -> str:
        cells = [row[i] + " " * (widths[i] - width(row[i])) for i in range(col_count)]
        return "| " + " | ".join(cells) + " |"

    sep = "|" + "|".join("-" * (w + 2) for w in widths) + "|"
    return "\n".join([line(headers), sep] + [line(r) for r in rows])


def main() -> None:
    results = []
    for label, text, mode in SAMPLES:
        features = extract_lexical_features(text, mode)
        results.append((label, mode, {f.id: f for f in features}))

    feature_ids = [f.id for f in extract_lexical_features(SAMPLES[0][1], SAMPLES[0][2])]

    print("=" * 78)
    print("Kiwi 규칙 자질 추출 결과 (LLM 키 불필요)")
    print("=" * 78)
    for label, mode, _ in results:
        print(f"  {label}  [mode={mode.value}]")
    print()

    rows = []
    for fid in feature_ids:
        name = results[0][2][fid].name
        cells = [f"{name} ({fid})"]
        for _, _, fmap in results:
            f = fmap[fid]
            if f.status != FeatureStatus.OK:
                cells.append(f"— ({f.status.value})")
            else:
                cells.append(f"{f.value}")
        rows.append(tuple(cells))

    print(render_table(rows, ("자질", "A 잘 쓴", "B 못 쓴", "C 쓰기")))
    print()

    # 값의 방향이 상식과 맞는지 자동으로 확인한다.
    print("-" * 78)
    print("방향성 점검 (A 잘 쓴 답안 vs B 못 쓴 답안)")
    print("-" * 78)
    a = results[0][2]
    b = results[1][2]
    checks = [
        ("어휘 다양도(MATTR)는 A가 더 높아야 함",
         a["lexical_diversity_mattr"].value > b["lexical_diversity_mattr"].value),
        ("고급 어휘 비율은 A가 더 높아야 함",
         a["advanced_vocab_ratio"].value > b["advanced_vocab_ratio"].value),
        ("어휘 밀도는 A가 더 높아야 함",
         a["lexical_density"].value > b["lexical_density"].value),
        ("문장당 어절 수는 A가 더 많아야 함",
         a["words_per_sentence"].value > b["words_per_sentence"].value),
        ("절 밀도는 A가 더 높아야 함",
         a["clause_density"].value > b["clause_density"].value),
        ("연결어미 다양성은 A가 더 높아야 함",
         a["connective_ending_diversity"].value >= b["connective_ending_diversity"].value),
        ("반말 혼입은 B에서만 잡혀야 함",
         a["formality"].components["banmal_count"] == 0
         and b["formality"].components["banmal_count"] > 0),
        ("주체 높임 '-시-'는 A에서 잡혀야 함",
         a["subject_honorific_si"].components["si_count"] > 0),
        ("띄어쓰기 자질은 말하기에서 계산하지 않아야 함",
         a["spacing_error_rate"].status == FeatureStatus.NOT_APPLICABLE),
        ("띄어쓰기 오류는 쓰기 답안 C에서 잡혀야 함",
         results[2][2]["spacing_error_rate"].components.get("error_count", 0) > 0),
    ]
    failed = 0
    for desc, ok in checks:
        print(f"  [{'OK ' if ok else 'NG '}] {desc}")
        if not ok:
            failed += 1
    print()

    # 근거가 실제로 원문 위치와 함께 붙는지 확인한다.
    print("-" * 78)
    print("근거 예시 (B 못 쓴 답안의 반말 혼입 / A 잘 쓴 답안의 고급 어휘)")
    print("-" * 78)
    for ev in b["formality"].evidence[:3]:
        print(f"  [{ev.start}:{ev.end}] '{ev.quote}' — {ev.comment}")
    for ev in a["advanced_vocab_ratio"].evidence[:3]:
        print(f"  [{ev.start}:{ev.end}] '{ev.quote}' — {ev.comment}")
    print()
    print("-" * 78)
    print("C 쓰기 답안의 띄어쓰기 오류 근거")
    print("-" * 78)
    for ev in results[2][2]["spacing_error_rate"].evidence[:5]:
        print(f"  [{ev.start}:{ev.end}] '{ev.quote}' — {ev.comment}")

    print()
    if failed:
        print(f"방향성 점검 실패 {failed}건 — 자질 계산을 확인해야 한다.")
        sys.exit(1)
    print("방향성 점검 전부 통과.")


if __name__ == "__main__":
    main()
