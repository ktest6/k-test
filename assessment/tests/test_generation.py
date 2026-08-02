"""문서 → 문항 생성 모듈 회귀 테스트.

여기서 지키려는 것은 세 가지다.

  1. **근거 없는 문항은 응답에 실리지 않는다.**
     실제 실험에서 인용 규칙이 없을 때 모델은 여러 구절을 '...' 으로 이어붙였고
     검증기가 전부 걸러내 폐기율 100% 가 나왔다. 그 걸러내기가 계속 작동하는지 못 박는다.
  2. **채점 파이프라인은 이 기능 때문에 달라지지 않는다.**
     생성 문항이 채점기를 그대로 통과하는지, 그리고 채점 쪽이 생성 쪽을
     불러다 쓰지는 않는지를 코드로 확인한다.
  3. **생성은 재현되지 않지만 검증은 재현된다.**
     같은 생성 결과를 두 번 검증하면 언제나 같은 판정이 나와야 한다.

이 테스트는 **LLM 을 한 번도 부르지 않는다.** 미리 적어 둔 답을 돌려주는
가짜 클라이언트를 쓰기 때문에 네트워크 없이 돌고, 언제 돌려도 같은 결과가 나온다.

실행: .venv\\Scripts\\python.exe -m pytest tests -q
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api import app
from src.generation.generate import GenerationRequestError, generate_items, verify_items
from src.generation.preprocess import CUT_MARKER, preprocess_document
from src.generation.schema import (
    DropReason,
    GenerateItemsRequest,
    GenerateOptions,
    VerifyItemsRequest,
)
from src.llm.client import LLMUnavailable
from src.scoring.pipeline import score_submission
from src.scoring.schema import ItemInfo, Mode, ScoreOptions, ScoreRequest

# ---------------------------------------------------------------------------
# 시험용 안전 문서 (가상 공장). 실제 문서 대신 쓰는 짧은 표본이다.
# 인용 대조가 진짜로 도는지 보려면 '문서에 있는 구절'과 '없는 구절'이 둘 다 필요하다.
# ---------------------------------------------------------------------------

DOCUMENT = """\
(주)K-테스트 식품공장 안전수칙

1. 작업 시작 전 점검
작업을 시작하기 전에 안전모와 안전화를 착용한다.
기계의 비상정지 버튼이 잘 눌리는지 확인한다.
바닥에 기름이나 물이 있으면 즉시 닦아 낸다.
점검한 내용은 작업일지에 기록한다.

2. 지게차 운행
지게차가 지나가는 통로에서는 보행자가 노란 선 안쪽으로 걷는다.
지게차 운전자는 후진할 때 반드시 경적을 울린다.
적재 높이는 1.8미터를 넘기지 않는다.
지게차 열쇠는 작업이 끝나면 사무실에 반납한다.

3. 위험을 발견했을 때
선반이 기울어져 있으면 물건을 내리기 전에 안전관리자에게 알린다.
전선이 벗겨진 곳을 보면 손대지 말고 전기 담당자에게 연락한다.
소화기는 한 달에 한 번 압력계 바늘이 초록색 칸에 있는지 확인한다.

4. 교대 근무
근무를 마칠 때에는 다음 근무자에게 남은 작업을 알려 준다.
고장 난 설비가 있으면 어디가 어떻게 고장 났는지 적어 둔다.
청소용 세제는 창고 2층 선반에 보관하고 다 쓰면 사무실에 요청한다.
"""

# 문서에 실제로 있는 구절들 (인용으로 쓸 것)
QUOTE_HELMET = "작업을 시작하기 전에 안전모와 안전화를 착용한다"
QUOTE_HORN = "지게차 운전자는 후진할 때 반드시 경적을 울린다"
QUOTE_SHELF = "선반이 기울어져 있으면 물건을 내리기 전에 안전관리자에게 알린다"
QUOTE_HANDOVER = "근무를 마칠 때에는 다음 근무자에게 남은 작업을 알려 준다"
QUOTE_WALKWAY = "지게차가 지나가는 통로에서는 보행자가 노란 선 안쪽으로 걷는다"

# 문서에 없는 구절 (지어낸 근거)
QUOTE_FAKE = "황화수소 농도를 매일 세 번 측정하여 기록한다"

PROMPT_WORK_LOG = (
    "오늘 포장 라인에서 한 일을 작업일지에 쓰세요. "
    "① 어떤 작업을 했는지 ② 무슨 문제가 있었는지 ③ 어떻게 처리했는지 쓰세요."
)


# ---------------------------------------------------------------------------
# 가짜 LLM 클라이언트
# ---------------------------------------------------------------------------


class FakeClient:
    """미리 적어 둔 JSON 을 돌려주는 가짜 클라이언트.

    생성 모듈이 실제 클라이언트에서 쓰는 것은 model_name 과 generate_json 뿐이다.
    이 객체는 GeminiClient 가 아니므로 client_for_generation 이 진짜 클라이언트로
    갈아 끼우지 않는다(그래야 네트워크로 호출이 나가지 않는다).
    """

    def __init__(self, payload: dict | Exception):
        self.payload = payload
        self.model_name = "fake-generation-model"
        self.calls = 0
        self.prompts: list[str] = []

    def generate_json(self, prompt, system_instruction="", response_schema=None):
        self.calls += 1
        self.prompts.append(prompt)
        # 호출 실패를 흉내 낼 때는 예외를 그대로 올린다
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


def raw_item(**overrides) -> dict:
    """관문을 전부 통과하는 정상 문항 하나를 만든다. 필요한 곳만 바꿔 쓴다."""
    item = {
        "item_id": "GEN-001",
        "item_type": "work_log",
        "prompt": PROMPT_WORK_LOG,
        "expected_register": "formal",
        "checklist": [
            {"id": "c1", "description": "한 작업을 적었는가", "weight": 1.0, "quote": QUOTE_HELMET},
            {"id": "c2", "description": "발견한 문제를 적었는가", "weight": 1.5, "quote": QUOTE_SHELF},
        ],
        "reference_keywords": ["안전모", "작업일지"],
        "source_quote": QUOTE_HELMET,
    }
    item.update(overrides)
    return item


def run(items: list[dict], **option_overrides):
    """가짜 응답으로 생성 한 번을 돌린다."""
    options = GenerateOptions(**option_overrides)
    request = GenerateItemsRequest(
        document_id="doc-001",
        document_text=DOCUMENT,
        document_title="K-테스트 식품공장 안전수칙",
        options=options,
    )
    client = FakeClient({"items": items})
    return generate_items(request, client=client)


def only_drop_reason(response) -> DropReason:
    """폐기가 정확히 하나 있고 문항은 하나도 없다는 것을 확인하고 사유를 돌려준다."""
    assert response.items == [], "근거를 대지 못한 문항이 응답에 실렸다"
    assert len(response.dropped) == 1
    return response.dropped[0].reason


# ---------------------------------------------------------------------------
# 폐기가 되어야 하는 것 (설계 문서 경계 사례 1~12)
# ---------------------------------------------------------------------------


def test_지어낸_인용은_폐기된다():
    """문서에 없는 구절을 근거로 단 문항은 응답에 실리지 않는다."""
    response = run([raw_item(source_quote=QUOTE_FAKE)])
    assert only_drop_reason(response) == DropReason.CITATION_NOT_FOUND
    assert response.counts.drop_rate == 1.0


def test_여러_구절을_이어붙인_인용은_폐기된다():
    """실제 실험에서 모델이 한 짓이 이것이다. 프롬프트로 막고 코드로 한 번 더 막는다."""
    stitched = f"{QUOTE_HELMET}...{QUOTE_HORN}"
    response = run([raw_item(source_quote=stitched)])
    assert only_drop_reason(response) == DropReason.CITATION_STITCHED


def test_잘라낸_자리를_가로지르는_인용은_폐기된다():
    """전처리로 머리글을 지운 자리를 넘어선 인용은 실제 문서에는 없는 문장이다."""
    response = run([raw_item(source_quote=f"안전모와 안전화{CUT_MARKER}지게차 운전자는")])
    assert only_drop_reason(response) == DropReason.CITATION_CROSSES_CUT


def test_너무_짧은_인용은_폐기된다():
    """세 글자짜리 인용은 우연히 겹칠 수 있어 근거로 인정하지 않는다."""
    response = run([raw_item(source_quote="안전모")])
    assert only_drop_reason(response) == DropReason.CITATION_STITCHED


def test_체크리스트_인용이_하나만_틀려도_문항_전체가_폐기된다():
    """부분 통과는 없다. 항목 하나의 근거가 가짜면 그 문항 점수의 일부가 근거 없이 매겨진다."""
    checklist = [
        {"id": "c1", "description": "한 작업을 적었는가", "weight": 1.0, "quote": QUOTE_HELMET},
        {"id": "c2", "description": "위험을 알렸는가", "weight": 1.0, "quote": QUOTE_SHELF},
        {"id": "c3", "description": "인수인계를 했는가", "weight": 1.0, "quote": QUOTE_HANDOVER},
        {"id": "c4", "description": "농도를 적었는가", "weight": 1.0, "quote": QUOTE_FAKE},
    ]
    response = run([raw_item(checklist=checklist)])
    assert only_drop_reason(response) == DropReason.CITATION_NOT_FOUND


def test_없는_문항_유형은_폐기된다():
    response = run([raw_item(item_type="essay")])
    assert only_drop_reason(response) == DropReason.UNKNOWN_ITEM_TYPE


def test_범위를_벗어난_가중치는_조용히_고치지_않고_폐기한다():
    """weight 는 점수에 직접 들어가는 값이다. 몰래 고치면 승인한 문항과 채점한 문항이 달라진다."""
    checklist = [
        {"id": "c1", "description": "한 작업을 적었는가", "weight": 2.5, "quote": QUOTE_HELMET},
        {"id": "c2", "description": "위험을 알렸는가", "weight": 1.0, "quote": QUOTE_SHELF},
    ]
    response = run([raw_item(checklist=checklist)])
    assert only_drop_reason(response) == DropReason.SCHEMA_INVALID


def test_번호_기호가_없는_지시문은_폐기된다():
    response = run([raw_item(prompt="오늘 포장 라인에서 한 일을 작업일지에 자세히 적어서 쓰세요.")])
    assert only_drop_reason(response) == DropReason.PROMPT_FORMAT_INVALID


def test_띄어쓰기가_붙어_있는_지시문은_폐기된다():
    """PDF 에서 띄어쓰기가 사라진 문구가 지시문에 새어 나온 경우다."""
    prompt = "작업을시작하기전에안전모와안전화를착용한다 ① 무엇을 ② 어디서 ③ 어떻게 했는지 쓰세요."
    response = run([raw_item(prompt=prompt)])
    assert only_drop_reason(response) == DropReason.PROMPT_FORMAT_INVALID


def test_암기_문제는_폐기된다():
    """'쓰기를 시키는 말이 있는가'라는 통과 조건으로 뒤집어 막는다."""
    prompt = "황화수소의 허용농도는 몇 ppm입니까? ① 숫자 ② 단위 ③ 근거를 적으시오."
    response = run([raw_item(prompt=prompt)])
    assert only_drop_reason(response) == DropReason.PROMPT_NOT_A_WRITING_TASK


def test_지시문이_문서_문장을_그대로_옮기면_폐기된다():
    """답이 문제에 들어 있고, 그 표현을 따라 쓴 성실한 응시자가 채점 가드에 걸린다."""
    prompt = f"{QUOTE_WALKWAY}. ① 무엇을 ② 어디서 ③ 어떻게 쓰세요."
    response = run([raw_item(prompt=prompt, source_quote=QUOTE_WALKWAY)])
    assert only_drop_reason(response) == DropReason.PROMPT_LEAKS_ANSWER


def test_사실상_같은_문항은_뒤엣것이_폐기된다():
    response = run(
        [raw_item(), raw_item(source_quote=QUOTE_SHELF)],
        item_count=2,
    )
    assert len(response.items) == 1
    assert response.dropped[0].reason == DropReason.DUPLICATE_ITEM


# ---------------------------------------------------------------------------
# 통과·동작이 되어야 하는 것 (설계 문서 경계 사례 13~21)
# ---------------------------------------------------------------------------


def test_정상_문항_세_개가_초안으로_나온다():
    items = [
        raw_item(),
        raw_item(
            item_type="hazard_report",
            prompt=(
                "창고 선반이 한쪽으로 기울어져 있습니다. 안전 담당자에게 알리세요. "
                "① 무엇이 위험한지 ② 어디에 있는지 ③ 어떤 조치가 필요한지 쓰세요."
            ),
            source_quote=QUOTE_SHELF,
            checklist=[
                {"id": "c1", "description": "위험한 것을 알렸는가", "weight": 1.5, "quote": QUOTE_SHELF},
                {"id": "c2", "description": "위치를 알렸는가", "weight": 1.0, "quote": QUOTE_SHELF},
            ],
        ),
        raw_item(
            item_type="handover_memo",
            prompt=(
                "오늘 근무가 끝났습니다. 다음 근무자에게 남길 메모를 작성하세요. "
                "① 무엇이 남았는지 ② 고장 난 것이 있는지 ③ 무엇을 조심해야 하는지 쓰세요."
            ),
            source_quote=QUOTE_HANDOVER,
            checklist=[
                {"id": "c1", "description": "남은 작업을 알렸는가", "weight": 1.0, "quote": QUOTE_HANDOVER},
                {"id": "c2", "description": "고장을 알렸는가", "weight": 1.5, "quote": QUOTE_HANDOVER},
            ],
        ),
    ]
    response = run(items, item_count=3)

    assert response.counts.kept == 3
    assert response.counts.dropped == 0
    assert response.counts.drop_rate == 0.0
    # 문항은 언제나 초안이다. 사람이 승인하기 전에는 시험에 낼 수 없다
    assert all(item.status == "draft" for item in response.items)
    assert response.status == "draft"
    assert response.meta.requires_human_approval is True
    # 생성 문구는 재현되지 않는다는 사실을 응답에 밝혀 둔다
    assert response.meta.wording_reproducible is False
    # id 는 우리가 다시 붙인다. 같은 문서에서 나온 문항은 가운데 글자가 같다
    doc6 = response.meta.source_text_sha256[:6].upper()
    assert [item.item_id for item in response.items] == [
        f"GEN-{doc6}-001", f"GEN-{doc6}-002", f"GEN-{doc6}-003",
    ]


def test_근거는_문서에서_잘라낸_구간으로_나간다():
    """화면에 보여 줄 것은 모델이 적어 낸 글자가 아니라 문서에서 실제로 잘라낸 구간이다."""
    response = run([raw_item()])
    citation = response.items[0].citation
    assert response.source_text[citation.start:citation.end] == citation.matched_text
    assert citation.matched_text in DOCUMENT


def test_생성_문항은_채점_계약으로_그대로_바뀐다():
    """관문 G5. 이 확인이 '채점기가 이 문항을 받을 수 있다'를 코드로 증명한다."""
    response = run([raw_item()])
    for item in response.items:
        converted = ItemInfo.model_validate(item.model_dump())
        assert converted.item_id == item.item_id
        assert len(converted.checklist) == len(item.checklist)


def test_생성_문항으로_채점이_끝까지_돈다():
    """생성 문항을 채점기에 그대로 넣어 본다. 채점 파이프라인이 손대지 않았다는 증거다."""
    generated = run([raw_item()]).items[0]

    class ScoringFake:
        """채점 쪽 LLM 호출에 정해진 답을 돌려주는 가짜."""

        available = True
        model_name = "fake-scoring-model"

        def generate_json(self, prompt, system_instruction="", response_schema=None):
            return {
                "errors": [],
                "results": [
                    {"id": entry.id, "met": 1, "reason": "적혀 있다", "quote": "안전모를 착용하고"}
                    for entry in generated.checklist
                ],
            }

    result = score_submission(
        ScoreRequest(
            submission_id="sub-gen-1",
            mode=Mode.WRITING,
            answer_text=(
                "오늘 삼번 포장 라인에서 상자 포장 작업을 하였습니다. "
                "작업 전에 안전모를 착용하고 비상정지 버튼을 확인했습니다. "
                "작업 중에 선반이 조금 기울어져 있어서 반장님께 보고하였습니다."
            ),
            item=ItemInfo.model_validate(generated.model_dump()),
        ),
        client=ScoringFake(),
    )
    assert result.overall_score is not None
    assert result.meta.answer_valid is True


def test_같은_응답을_두_번_처리하면_결과가_같다():
    """생성은 재현되지 않아도 검증과 조립은 재현된다. 그것이 이 모듈의 신뢰 근거다."""
    first = run([raw_item()])
    second = run([raw_item()])
    # 걸린 시간만 다르므로 그 값만 빼고 비교한다
    assert first.model_dump(exclude={"meta": {"elapsed_ms"}}) == second.model_dump(
        exclude={"meta": {"elapsed_ms"}}
    )


def test_요청보다_많이_만들면_잘라내고_폐기율은_오염되지_않는다():
    # 서로 다른 상황을 묻는 문항이어야 한다. 비슷하면 앞의 문항 간 관문에 걸린다
    prompts = [
        "오늘 포장 라인에서 한 일을 작업일지에 쓰세요. "
        "① 어떤 작업을 했는지 ② 무슨 문제가 있었는지 ③ 어떻게 처리했는지 쓰세요.",
        "창고 선반이 기울어져 있습니다. 안전 담당자에게 알리세요. "
        "① 무엇이 위험한지 ② 어디에 있는지 ③ 어떤 조치가 필요한지 쓰세요.",
        "근무가 끝났습니다. 다음 사람에게 남길 메모를 작성하세요. "
        "① 남은 일이 무엇인지 ② 고장 난 것이 있는지 ③ 조심할 점을 쓰세요.",
        "청소용 세제가 다 떨어졌습니다. 사무실에 요청하세요. "
        "① 필요한 물건 ② 필요한 수량 ③ 언제까지 필요한지 쓰세요.",
        "지게차 열쇠를 반납하지 않은 사람이 있습니다. 반장에게 보고하세요. "
        "① 누가 ② 언제 ③ 어떻게 해야 하는지 쓰세요.",
    ]
    response = run([raw_item(prompt=text) for text in prompts], item_count=3)
    assert response.counts.kept == 3
    assert response.counts.truncated == 2
    # 잘라 낸 것은 폐기가 아니다
    assert response.counts.dropped == 0
    assert response.counts.drop_rate == 0.0


def test_문항이_하나도_안_나와도_오류가_아니다():
    """관리자가 문서를 바꿔 다시 시도할 수 있게 200 으로 돌려준다."""
    response = run([])
    assert response.items == []
    assert response.counts.returned_by_model == 0
    assert response.warnings, "문항이 없으면 그 사실을 경고로 알려야 한다"


def test_전부_폐기돼도_오류가_아니고_사유가_남는다():
    response = run([raw_item(source_quote=QUOTE_FAKE)])
    assert response.items == []
    assert response.counts.drop_rate == 1.0
    assert any("폐기" in warning for warning in response.warnings)


def test_문서에_없는_핵심어는_빠지고_문항은_살아남는다():
    """핵심어는 LLM 을 못 쓸 때의 대체 채점에 쓰이는 값이라 지어낸 낱말이 섞이면 안 된다."""
    response = run([raw_item(reference_keywords=["안전모", "황화수소", "작업일지"])])
    assert len(response.items) == 1
    assert response.items[0].reference_keywords == ["안전모", "작업일지"]
    assert any("황화수소" in warning for warning in response.warnings)


def test_원문에_있는_절단_기호는_공백으로_바뀐다():
    """우리가 남길 '잘라낸 자리 표시'와 문서 쪽 기호가 헷갈리지 않게 미리 치운다."""
    result = preprocess_document(f"앞 문장이다.{CUT_MARKER}뒤 문장이다.")
    assert CUT_MARKER not in result.text
    assert any("공백으로 바꿨다" in note for note in result.notes)


def test_쪽마다_반복되는_줄은_지워지고_기록이_남는다():
    body = "\n".join(f"{n}번 통로의 안전 점검 결과를 기록한다." for n in range(1, 9))
    document = "\n".join(["KOSHA GUIDE C-2-2025", body, "- 12 -"] * 4)
    result = preprocess_document(document)

    assert "KOSHA GUIDE C-2-2025" not in result.text
    # 지운 자리에는 표시가 남아야 한다. 그래야 이음매를 가로지른 인용을 잡을 수 있다
    assert CUT_MARKER in result.text
    assert any("반복되는 줄" in note for note in result.notes)


# ---------------------------------------------------------------------------
# 거부되어야 하는 것 (설계 문서 경계 사례 22~26)
# ---------------------------------------------------------------------------


client = TestClient(app)


def post_generate(**overrides) -> tuple[int, dict]:
    """엔드포인트를 실제로 불러 상태 코드와 본문을 돌려준다."""
    body = {
        "document_id": "doc-001",
        "document_text": DOCUMENT,
        "options": {"item_count": 3},
    }
    body.update(overrides)
    response = client.post("/generate-items", json=body)
    return response.status_code, response.json()


def test_너무_짧은_문서는_거부된다():
    status, body = post_generate(document_text="안전모를 씁니다. " * 5)
    assert status == 400
    assert "짧" in body["detail"]


def test_너무_긴_문서는_자르지_않고_거부된다():
    """조용히 자르면 관리자가 보낸 문서와 문항이 나온 문서가 달라진다."""
    status, body = post_generate(document_text="지게차는 통로에서 천천히 운행한다. " * 3000)
    assert status == 400
    assert "길" in body["detail"]


def test_말하기_문항_생성은_거부된다():
    status, body = post_generate(mode="speaking")
    assert status == 400
    assert "쓰기" in body["detail"]


def test_LLM_키가_없으면_503_이고_대체_경로로_넘어가지_않는다(monkeypatch):
    """채점과 다른 점이다. 규칙만으로 문항을 지어낼 수는 없으므로 죽으면 죽었다고 말한다."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    status, body = post_generate()
    assert status == 503
    assert "detail" in body


def test_응답_JSON이_깨지면_예외가_그대로_올라온다():
    """창구가 이 예외를 503 으로 바꾼다. 반쯤 만들어진 문항을 내놓지 않는다."""
    request = GenerateItemsRequest(document_id="doc-001", document_text=DOCUMENT)
    broken = FakeClient(LLMUnavailable("LLM 응답을 JSON으로 해석하지 못했다."))
    with pytest.raises(LLMUnavailable):
        generate_items(request, client=broken)


def test_문서_길이_검증은_전처리_뒤에_잰다():
    """머리글만 잔뜩 있는 문서가 길이만 채우는 일을 막는다."""
    request = GenerateItemsRequest(
        document_id="doc-001",
        document_text="\n".join(["KOSHA GUIDE C-2-2025"] * 60),
    )
    with pytest.raises(GenerationRequestError):
        generate_items(request, client=FakeClient({"items": []}))


# ---------------------------------------------------------------------------
# 재검증 (POST /verify-items)
# ---------------------------------------------------------------------------


def test_고치지_않은_문항은_재검증을_통과한다():
    generated = run([raw_item()])
    result = verify_items(
        VerifyItemsRequest(
            source_text=generated.source_text,
            source_text_sha256=generated.meta.source_text_sha256,
            items=generated.items,
        )
    )
    assert result.all_ok is True
    assert result.warnings == []


def test_관리자가_지시문을_망가뜨리면_재검증이_막는다():
    generated = run([raw_item()])
    broken = generated.items[0].model_copy(update={"prompt": "작업일지 쓰세요"})
    result = verify_items(
        VerifyItemsRequest(source_text=generated.source_text, items=[broken])
    )
    assert result.all_ok is False
    assert result.results[0].failures[0].reason == DropReason.PROMPT_FORMAT_INVALID


def test_다른_문서를_보내면_경고가_붙는다():
    generated = run([raw_item()])
    result = verify_items(
        VerifyItemsRequest(
            source_text=generated.source_text,
            source_text_sha256="0" * 64,
            items=generated.items,
        )
    )
    assert any("다르다" in warning for warning in result.warnings)


def test_재검증은_LLM을_부르지_않는다(monkeypatch):
    """키를 아예 지워도 그대로 돌아야 한다. 관문이 전부 규칙 계산이라는 뜻이다."""
    generated = run([raw_item()])
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    result = verify_items(
        VerifyItemsRequest(source_text=generated.source_text, items=generated.items)
    )
    assert result.all_ok is True


def test_재검증은_두_번_돌려도_같은_답을_준다():
    generated = run([raw_item()])
    request = VerifyItemsRequest(source_text=generated.source_text, items=generated.items)
    assert verify_items(request).model_dump() == verify_items(request).model_dump()


# ---------------------------------------------------------------------------
# 구조를 지키는 테스트 (설계 문서 27·28)
# ---------------------------------------------------------------------------

SRC = Path(__file__).resolve().parents[1] / "src"


def test_채점_코드는_생성_모듈을_불러다_쓰지_않는다():
    """단방향 의존을 코드로 못 박는다.

    이 방향이 지켜져야 '문항 생성 기능을 붙였다고 채점이 달라지지 않는다'가
    말이 아니라 검사 가능한 사실이 된다.
    """
    offenders = []
    for folder in ("scoring", "features", "llm"):
        for path in (SRC / folder).glob("**/*.py"):
            text = path.read_text(encoding="utf-8")
            if "generation" in text:
                offenders.append(str(path))
    assert offenders == [], f"채점 쪽 파일이 생성 모듈을 참조한다: {offenders}"


def test_생성_코드에는_승인_완료_상태값이_없다():
    """승인 상태로 바꾸는 것은 백엔드(사람의 행위)이지 우리가 아니다.

    우리 코드가 그 값을 만들 수 있으면 '사람 승인 필수' 원칙이 언제든 무너진다.
    """
    approved_state = "conf" + "irmed"
    offenders = [
        str(path)
        for path in (SRC / "generation").glob("**/*.py")
        if approved_state in path.read_text(encoding="utf-8")
    ]
    assert offenders == [], f"생성 코드에 승인 완료 상태값이 들어 있다: {offenders}"


def test_생성_모듈에는_인용_검증을_끄는_옵션이_없다():
    """옵션이 되는 순간 그 제약은 제약이 아니라 기본값이 되고, 급할 때 꺼진다."""
    fields = set(GenerateOptions.model_fields)
    for name in fields:
        assert "citation" not in name and "verify" not in name, (
            f"인용 검증을 조절하는 옵션이 생겼다: {name}"
        )


def test_규칙만으로_채점하는_경로에서도_생성_문항이_돈다():
    """LLM 없이 규칙 자질만으로 채점해도 생성 문항이 끝까지 간다."""
    generated = run([raw_item()]).items[0]
    result = score_submission(
        ScoreRequest(
            submission_id="sub-gen-2",
            mode=Mode.WRITING,
            answer_text=(
                "오늘 이번 라인에서 포장 작업을 하였습니다. 작업 전에 안전모를 착용했습니다. "
                "선반이 기울어져 있어서 반장님께 말씀드렸습니다."
            ),
            item=ItemInfo.model_validate(generated.model_dump()),
            options=ScoreOptions(use_llm=False),
        )
    )
    assert result.overall_score is not None
