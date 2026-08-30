"""[보너스] 체크리스트 항목을 코드가 계산하는 규칙(`ChecklistItem.requires`)의 회귀 테스트.

왜 이 규칙이 생겼는가:
"세 요소를 모두 포함했는가" 같은 보너스 항목은 근거가 답안 여기저기에 흩어져 있다.
LLM 은 그걸 충족이라고 판정하면서 인용을 조각조각 이어 붙여 내는데, 그렇게 만든 문장은
원문에 그대로 있지 않으니 인용 검증에서 폐기되고 항목이 0점이 됐다(SPK-105 c10 실측).
그래서 그런 항목은 아예 LLM 에게 묻지 않고 앞 항목들의 판정 결과로 코드가 계산한다.

여기서 못 박는 것 다섯:
  ① 프롬프트  — requires 가 있는 항목은 LLM 에게 안 물어본다
  ② 계산      — 바깥 리스트는 '그리고', 안쪽 리스트는 '또는'
  ③ 차례      — 계산한 결과가 문항에 적힌 자리에 그대로 들어간다
  ④ 잘못된 id — 문항에 없는 항목을 가리키면 조용히 넘어가지 않고 경고와 함께 미충족
  ⑤ 신뢰도    — 보너스를 코드가 계산했다고 채점 신뢰도가 떨어지면 안 된다

**네트워크를 쓰지 않는다.** LLM 자리에는 답을 정해 둔 가짜 응답을 넣는다.

실행: .venv\\Scripts\\python.exe -m pytest tests/test_checklist.py -q
"""

from __future__ import annotations

from src.features.checklist import (
    build_prompt,
    evaluate_requires,
    judge_checklist,
    llm_judged_items,
    results_from_llm_payload,
)
from src.llm.client import GeminiClient
from src.scoring.pipeline import score_submission
from src.scoring.schema import (
    ChecklistItem,
    FeatureSource,
    ItemInfo,
    Mode,
    Reliability,
    ScoreRequest,
)

# 시험에 쓸 답안 하나. 아래 체크리스트 c1~c3 의 근거가 이 안에 다 들어 있다.
ANSWER = (
    "죄송합니다 오늘 늦었습니다 "
    "아침에 알람이 안 울려서 늦게 일어났습니다 "
    "다음부터는 일찍 나오겠습니다"
)


def _item(requires: list[list[str]]) -> ItemInfo:
    """앞 항목 셋 + 마지막 보너스 하나로 된 시험용 문항을 만든다."""
    return ItemInfo(
        item_id="T-001",
        prompt="왜 늦었는지 말하세요.",
        checklist=[
            ChecklistItem(id="c1", description="늦은 사실을 말했는가", weight=1.0),
            ChecklistItem(id="c2", description="늦은 이유를 말했는가", weight=1.5),
            ChecklistItem(id="c3", description="사과했는가", weight=1.0),
            ChecklistItem(
                id="c4",
                description="[보너스] 사실 + 이유 + 사과를 모두 포함했는가",
                description_en="Say all three things.",
                weight=0.5,
                requires=requires,
            ),
        ],
        reference_keywords=["늦", "죄송"],
    )


def _payload(c1: int, c2: int, c3: int) -> dict:
    """LLM 이 c1~c3 을 이렇게 판정해서 보내왔다고 치는 가짜 응답.

    충족(1)으로 둔 항목에는 답안에 실제로 있는 문장을 인용으로 넣는다.
    (없는 문장을 넣으면 인용 검증에서 폐기되어 이 테스트가 보려는 것과 달라진다)
    """
    quotes = {
        "c1": "오늘 늦었습니다",
        "c2": "알람이 안 울려서",
        "c3": "죄송합니다",
    }
    return {
        "results": [
            {
                "id": cid,
                "met": met,
                "quote": quotes[cid] if met else "",
                "reason": "판정 이유",
            }
            for cid, met in (("c1", c1), ("c2", c2), ("c3", c3))
        ]
    }


# ---------------------------------------------------------------------------
# ① requires 가 있는 항목은 LLM 에게 묻지 않는다
# ---------------------------------------------------------------------------


def test_보너스_항목은_프롬프트에서_빠진다():
    item = _item([["c1"], ["c2"], ["c3"]])
    prompt = build_prompt(ANSWER, item)

    # 앞 항목 셋은 그대로 물어본다
    for cid in ("id=c1", "id=c2", "id=c3"):
        assert cid in prompt

    # 보너스만 빠져 있다. 물어보면 LLM 이 다시 인용을 지어내다 폐기당한다
    assert "id=c4" not in prompt
    assert "[보너스]" not in prompt


def test_requires_가_없으면_지금까지처럼_전부_물어본다():
    """새 칸을 안 쓴 기존 문항의 프롬프트가 바뀌지 않아야 한다."""
    item = _item([])
    prompt = build_prompt(ANSWER, item)

    assert "id=c4" in prompt
    assert len(llm_judged_items(item.checklist)) == 4


# ---------------------------------------------------------------------------
# ② AND / OR 계산
# ---------------------------------------------------------------------------


def test_바깥은_그리고_안쪽은_또는이다():
    known = {"c1", "c2", "c3"}

    # c1 그리고 (c2 또는 c3)
    조건 = [["c1"], ["c2", "c3"]]

    # 셋 다 충족이면 당연히 충족
    met, _, _ = evaluate_requires(조건, {"c1": 1, "c2": 1, "c3": 1}, known)
    assert met == 1

    # '또는' 묶음은 하나만 충족돼도 통과한다
    met, _, _ = evaluate_requires(조건, {"c1": 1, "c2": 0, "c3": 1}, known)
    assert met == 1

    # '또는' 묶음이 둘 다 미충족이면 그 묶음이 막힌다
    met, _, _ = evaluate_requires(조건, {"c1": 1, "c2": 0, "c3": 0}, known)
    assert met == 0

    # '그리고'로 묶인 것은 하나만 빠져도 전체가 미충족이다
    met, _, _ = evaluate_requires(조건, {"c1": 0, "c2": 1, "c3": 1}, known)
    assert met == 0


def test_조건이_비어_있으면_공짜_점수를_주지_않는다():
    """requires 를 실수로 빈 채 넣은 문항이 전원 충족을 주면 안 된다."""
    met, parts, _ = evaluate_requires([], {"c1": 1}, {"c1"})

    assert met == 0
    assert parts, "왜 미충족인지 근거가 비어 있으면 안 된다"


def test_보너스_판정이_점수와_근거로_이어진다():
    item = _item([["c1"], ["c2"], ["c3"]])

    # 앞 셋을 모두 충족한 경우 -> 보너스도 충족
    results, warnings, _, _ = results_from_llm_payload(
        ANSWER, item.checklist, _payload(1, 1, 1)
    )
    bonus = results[-1]
    assert bonus.met == 1
    assert not warnings

    # 근거가 반드시 함께 나온다. 인용이 아니라 '무엇이 충족돼서 이렇게 됐는지'다
    assert bonus.source == FeatureSource.RULE
    assert bonus.evidence, "근거 없는 점수는 이 프로젝트에서 결함이다"
    assert "c1" in bonus.evidence[0].comment
    assert bonus.evidence[0].detail["referenced_met"] == {"c1": 1, "c2": 1, "c3": 1}
    # 규칙으로 계산한 값이라 인용 검증 대상이 아니라는 표시가 남는다
    assert bonus.note

    # 하나만 빠져도 보너스는 미충족이고, 어느 것이 빠졌는지가 근거에 남는다
    results, _, _, _ = results_from_llm_payload(
        ANSWER, item.checklist, _payload(1, 1, 0)
    )
    bonus = results[-1]
    assert bonus.met == 0
    assert "c3 미충족" in bonus.evidence[0].comment


def test_인용이_폐기돼도_보너스는_앞_판정을_따른다():
    """이 규칙을 만든 이유 그 자체를 못 박는다.

    예전에는 보너스도 LLM 이 판정했고, 그 인용이 이어 붙인 문장이라 폐기되면
    실제로는 다 말한 답안이 0점이 됐다. 이제 보너스는 인용을 쓰지 않으므로
    앞 항목이 다 충족이면 보너스도 충족이어야 한다.
    """
    item = _item([["c1"], ["c2"], ["c3"]])
    payload = _payload(1, 1, 1)
    # 답안에 없는 문장을 이어 붙여 보낸 옛날 방식의 보너스 판정을 함께 실어 본다
    payload["results"].append(
        {
            "id": "c4",
            "met": 1,
            "quote": "오늘 늦었습니다 알람이 안 울려서 죄송합니다",
            "reason": "세 요소를 모두 말했다",
        }
    )

    results, _, _, dropped = results_from_llm_payload(ANSWER, item.checklist, payload)

    # LLM 이 보낸 c4 판정은 아예 쳐다보지 않는다 -> 폐기 건수도 늘지 않는다
    assert dropped == 0
    assert results[-1].met == 1


# ---------------------------------------------------------------------------
# ③ 차례가 유지되는가
# ---------------------------------------------------------------------------


def test_결과_차례는_문항에_적힌_그대로다():
    """보너스가 가운데 있는 문항이어도 자리를 지켜야 한다.

    프론트가 이 차례대로 화면에 뿌리기 때문에, 계산해서 뒤에 붙이면
    응시자 화면에서 항목 순서가 뒤바뀐다.
    """
    item = ItemInfo(
        item_id="T-002",
        prompt="왜 늦었는지 말하세요.",
        checklist=[
            ChecklistItem(id="c1", description="늦은 사실을 말했는가"),
            ChecklistItem(
                id="c9", description="[보너스] 사실 + 이유", requires=[["c1"], ["c2"]]
            ),
            ChecklistItem(id="c2", description="늦은 이유를 말했는가"),
            ChecklistItem(id="c3", description="사과했는가"),
        ],
    )

    results, warnings, notices, _ = results_from_llm_payload(
        ANSWER, item.checklist, _payload(1, 1, 1)
    )

    assert [r.id for r in results] == ["c1", "c9", "c2", "c3"]
    # c9 는 아직 판정 전인 c2 를 가리켰다. 그건 계산할 수 없으므로 경고가 떠야 한다
    assert results[1].met == 0
    assert any("c2" in w for w in warnings)
    assert len(warnings) == len(notices)


# ---------------------------------------------------------------------------
# ④ 문항에 없는 id 를 가리킨 경우
# ---------------------------------------------------------------------------


def test_없는_항목을_가리키면_경고와_함께_미충족이다():
    item = _item([["c1"], ["c99"]])

    results, warnings, notices, _ = results_from_llm_payload(
        ANSWER, item.checklist, _payload(1, 1, 1)
    )
    bonus = results[-1]

    # 조용히 넘어가면 '왜 항상 0점이지'로만 나타나서 원인을 못 찾는다
    assert bonus.met == 0
    assert warnings and "c99" in warnings[0]
    # 경고 문구와 코드 목록은 언제나 짝을 이룬다(백엔드가 영어로 바꿔 쓰는 자리)
    assert len(warnings) == len(notices)
    assert notices[0].message == warnings[0]
    assert notices[0].code


# ---------------------------------------------------------------------------
# LLM 을 못 쓰는 경우
# ---------------------------------------------------------------------------


def test_대체_경로에서는_보너스를_주지_않는다():
    """핵심어 일치로 때운 판정 위에 보너스를 또 얹으면 점수가 두 번 부풀려진다."""
    item = _item([["c1"], ["c2"], ["c3"]])

    out = judge_checklist(ANSWER, item, use_llm=False)

    bonus = out.results[-1]
    assert bonus.met == 0
    # 대체 경로로 돌았다는 표시(KIWI)가 남아 있어야 신뢰도 판정이 이 채점을 걸러낸다
    assert bonus.source == FeatureSource.KIWI
    assert all(r.source == FeatureSource.KIWI for r in out.results)


def test_물어볼_항목이_없으면_LLM_을_부르지_않는다():
    """체크리스트가 전부 규칙 계산 항목이면 호출할 이유가 없다."""

    class _터지는클라이언트(GeminiClient):
        def __init__(self):
            super().__init__(api_key="dummy-key-for-test")

        @property
        def available(self) -> bool:
            return True

        def generate_json(self, *args, **kwargs):
            raise AssertionError("부르면 안 되는 호출이다")

    item = ItemInfo(
        item_id="T-003",
        prompt="왜 늦었는지 말하세요.",
        checklist=[
            ChecklistItem(id="c9", description="[보너스]", requires=[["c1"]]),
        ],
    )

    out = judge_checklist(ANSWER, item, client=_터지는클라이언트())

    assert out.llm_used is False
    assert out.results[0].met == 0


# ---------------------------------------------------------------------------
# ⑤ 신뢰도가 떨어지지 않는가 (채점 전 구간)
# ---------------------------------------------------------------------------


class _정해진답클라이언트(GeminiClient):
    """네트워크 없이 정해진 답만 돌려주는 가짜 클라이언트.

    체크리스트 판정과 오류 자질 추출이 같은 클라이언트로 들어오므로,
    받은 지시문을 보고 어느 쪽에 답할지 고른다.
    """

    def __init__(self):
        super().__init__(api_key="dummy-key-for-test")

    @property
    def available(self) -> bool:
        return True

    def generate_json(self, prompt, *args, **kwargs):
        # 체크리스트 지시문에만 있는 말로 구분한다
        if "[확인할 항목]" in prompt:
            return _payload(1, 1, 1)
        # 오류 자질 쪽은 '오류 없음'으로 답한다
        return {"errors": []}


def test_보너스를_코드가_계산해도_신뢰도는_full_이다():
    """규칙 계산은 대체 경로가 아니라 원래 그렇게 하기로 한 정상 경로다.

    여기가 깨지면 보너스 항목 하나 때문에 멀쩡한 채점이 통째로
    '믿을 수 없는 점수'로 표시된다.
    """
    request = ScoreRequest(
        submission_id="sub-1",
        mode=Mode.WRITING,
        answer_text=ANSWER,
        item=_item([["c1"], ["c2"], ["c3"]]),
    )

    resp = score_submission(request, client=_정해진답클라이언트())

    bonus = resp.checklist_results[-1]
    assert bonus.met == 1
    assert bonus.source == FeatureSource.RULE
    assert resp.meta.reliability == Reliability.FULL
    assert resp.meta.safe_to_show_candidate is True


# ---------------------------------------------------------------------------
# 실제 문항 파일이 쓸 수 있는 조건을 적어 두었는가
# ---------------------------------------------------------------------------


def test_문항_파일의_requires_가_앞_항목만_가리킨다():
    """`items/speaking_v1.json` 에 적어 둔 조건이 실제로 계산 가능한지 본다.

    오타 하나로 보너스가 영영 0점이 되는데, 그건 채점 결과만 봐서는
    '응시자가 못 한 것'과 구별되지 않는다. 그래서 문항 파일 자체를 검사한다.
    """
    import json
    from pathlib import Path

    path = Path(__file__).resolve().parent.parent / "items" / "speaking_v1.json"
    data = json.loads(path.read_text(encoding="utf-8"))

    본_것 = 0
    for item in data["items"]:
        ids = [c["id"] for c in item["checklist"]]
        for 자리, c in enumerate(item["checklist"]):
            requires = c.get("requires") or []
            if not requires:
                continue
            본_것 += 1
            앞선_것 = set(ids[:자리])
            for group in requires:
                for ref in group:
                    assert ref in ids, f"{item['item_id']} {c['id']}: 없는 id {ref}"
                    assert ref in 앞선_것, (
                        f"{item['item_id']} {c['id']}: {ref} 는 자기보다 뒤에 있어 "
                        f"판정 전이라 쓸 수 없다"
                    )

    # 문항 6개가 모두 보너스 항목을 하나씩 갖고 있다
    assert 본_것 == 6, f"requires 를 적은 항목이 {본_것}개다"
