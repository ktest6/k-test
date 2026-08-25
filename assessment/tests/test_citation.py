"""인용 검증·폐기 로직 회귀 테스트.

이 로직이 조용히 망가지면 LLM이 지어낸 문장이 채점 근거로 들어간다.
채점 신뢰도의 마지막 방어선이라 테스트로 못 박아 둔다.

실행: .venv\\Scripts\\python.exe -m pytest tests -q
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.features.checklist import results_from_llm_payload  # noqa: E402
from src.llm.citation import (  # noqa: E402
    filter_by_citation,
    normalize_for_match,
    verify_citation,
)
from src.scoring.schema import ChecklistItem  # noqa: E402

SOURCE = (
    "지난주 화요일에 3번 라인 기계가 멈췄습니다. "
    "저는 전원을 차단하고 반장님께 보고드렸습니다."
)


def test_원문에_있는_인용은_통과하고_위치를_알려준다():
    check = verify_citation(SOURCE, "반장님께 보고드렸습니다")
    assert check.ok
    # 돌려준 위치로 원문을 잘라 보면 인용과 같아야 한다
    assert SOURCE[check.start : check.end] == "반장님께 보고드렸습니다"


def test_원문에_없는_인용은_폐기된다():
    check = verify_citation(SOURCE, "저는 즉시 119에 신고했습니다")
    assert not check.ok
    assert "찾을 수 없는" in check.reason


def test_띄어쓰기와_문장부호_차이는_통과시킨다():
    # 사소한 표기 차이로 멀쩡한 근거를 버리면 근거가 남아나지 않는다
    assert verify_citation(SOURCE, "반장님께보고드렸습니다").ok
    assert verify_citation(SOURCE, "'전원을 차단하고,'").ok


def test_낱말_순서를_바꾸면_폐기된다():
    # 글자만 겹치면 통과하는 느슨한 대조가 아니어야 한다
    assert not verify_citation(SOURCE, "보고드렸습니다 반장님께").ok


def test_너무_짧은_인용은_인정하지_않는다():
    assert not verify_citation(SOURCE, "저").ok
    assert not verify_citation(SOURCE, "").ok
    assert not verify_citation(SOURCE, "   ").ok


def test_정규화가_원문_위치를_잃지_않는다():
    normalized, positions = normalize_for_match(SOURCE)
    # 다듬은 글자 수와 위치 목록의 길이가 같아야 위치를 되짚을 수 있다
    assert len(normalized) == len(positions)
    # 위치는 원문 범위 안이어야 한다
    assert max(positions) < len(SOURCE)


def test_목록_필터가_통과분과_폐기분을_갈라낸다():
    items = [
        {"type": "josa", "quote": "3번 라인 기계가 멈췄습니다"},   # 있음
        {"type": "honorific", "quote": "반장님이 오셨습니다"},      # 없음
        {"type": "josa"},                                        # 인용 필드 자체가 없음
        "형식이 깨진 항목",                                        # 사전이 아님
    ]
    result = filter_by_citation(SOURCE, items)
    assert len(result.kept) == 1
    assert result.dropped_count == 3
    # 통과한 항목에는 원문 위치가 붙어야 한다
    kept = result.kept[0]
    assert SOURCE[kept["_citation_start"] : kept["_citation_end"]] == "3번 라인 기계가 멈췄습니다"


def test_근거를_지어낸_충족판정은_0으로_내려간다():
    """LLM이 충족(1)이라 해도 인용이 원문에 없으면 미충족으로 내려야 한다."""
    checklist = [
        ChecklistItem(id="c1", description="조치를 말했는가"),
        ChecklistItem(id="c2", description="교육을 받았는가"),
    ]
    payload = {
        "results": [
            {"id": "c1", "met": 1, "quote": "전원을 차단하고", "reason": "조치를 말함"},
            {"id": "c2", "met": 1, "quote": "안전 교육을 이수했습니다", "reason": "지어낸 근거"},
        ]
    }
    results, warnings, _notices, dropped = results_from_llm_payload(SOURCE, checklist, payload)

    by_id = {r.id: r for r in results}
    assert by_id["c1"].met == 1          # 진짜 근거가 있는 항목은 유지
    assert by_id["c2"].met == 0          # 지어낸 근거는 미충족으로 내려간다
    assert dropped == 1
    assert any("폐기" in w for w in warnings)


def test_LLM이_빠뜨린_항목은_미충족으로_처리된다():
    checklist = [ChecklistItem(id="c1", description="조치를 말했는가")]
    results, warnings, _notices, _ = results_from_llm_payload(SOURCE, checklist, {"results": []})
    assert results[0].met == 0
    assert any("판정이 없어" in w for w in warnings)
