"""체크리스트 항목의 영어 문장(`description_en`) 회귀 테스트.

리포트 화면의 'Required Points' 칸에는 체크리스트 항목이 **영어로** 떠야 한다.
그런데 문항 JSON 의 `description` 은 LLM 이 읽는 채점 기준이라 손댈 수 없다.
그래서 한국어는 그대로 두고 영어 문장을 옆에 하나 더 붙이는 방식으로 풀었다.

여기서 못 박는 것은 네 가지다.

  1. **영어를 안 보내도 채점이 돈다.** 선택 필드이고 기본값은 빈 문자열이다.
     백엔드가 예전 형식으로 요청해도 500 이 나면 안 된다.
  2. **보내면 그대로 응답에 실린다.** LLM 판정 경로와 대체(핵심어) 경로 둘 다.
  3. **문항 세트 두 개는 전부 영어를 갖고 있다.** 시연에서 빈 칸이 뜨지 않게 한다.
  4. **영어는 채점 기준이 아니다.** LLM 프롬프트에는 한국어만 들어간다.

이 테스트는 **LLM 을 한 번도 부르지 않는다.** 가짜 판정 결과를 직접 넣거나
`use_llm=False` 로 돌리므로 네트워크 없이 언제나 같은 결과가 나온다.

실행: .venv\\Scripts\\python.exe -m pytest tests -q
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api import app
from src.auth import API_KEY_ENV
from src.features.checklist import build_prompt, results_from_llm_payload
from src.scoring.pipeline import score_submission
from src.scoring.schema import (
    ChecklistItem,
    ItemInfo,
    Mode,
    ScoreOptions,
    ScoreRequest,
)

ITEMS_DIR = Path(__file__).resolve().parent.parent / "items"

# 답안과 문항 한 벌. 대체 경로가 '안전모'를 찾아 충족 판정을 내도록 낱말을 맞춰 두었다.
ANSWER = (
    "반장님, 2층 창고에서 동료가 안전모를 쓰지 않고 사다리 위에서 일하고 있습니다. "
    "떨어지면 크게 다칠 수 있어서 위험합니다. 안전모를 쓰라고 말씀해 주시기 바랍니다."
)


def _item(with_english: bool) -> ItemInfo:
    """체크리스트 두 개짜리 문항 하나를 만든다.

    with_english 를 끄면 백엔드가 예전 형식(영어 없이)으로 보낸 상황이 된다.
    """
    english = {
        "c1": "Point out that he is not wearing a safety helmet.",
        "c2": "Tell him to wear a safety helmet.",
    }
    return ItemInfo(
        item_id="SPK-002",
        prompt="동료가 안전모를 쓰지 않고 높은 곳에서 일하고 있습니다. 동료에게 말로 알려 주세요.",
        checklist=[
            ChecklistItem(
                id="c1",
                description="안전모를 쓰지 않은 것을 지적했는가",
                weight=1.5,
                # 영어를 안 보내는 경우에는 이 인자를 아예 넘기지 않는다
                **({"description_en": english["c1"]} if with_english else {}),
            ),
            ChecklistItem(
                id="c2",
                description="구체적인 행동(안전모 착용 등)을 권했는가",
                weight=1.0,
                **({"description_en": english["c2"]} if with_english else {}),
            ),
        ],
        reference_keywords=["안전모", "위험"],
    )


def _score(with_english: bool):
    """LLM 없이 채점 한 번을 돌린다(대체 판정 경로)."""
    request = ScoreRequest(
        submission_id="sub-en",
        mode=Mode.WRITING,
        answer_text=ANSWER,
        item=_item(with_english),
        options=ScoreOptions(use_llm=False),
    )
    return score_submission(request)


# ---------------------------------------------------------------------------
# 1) 안 보내도 깨지지 않는다 (선택 필드)
# ---------------------------------------------------------------------------


def test_영어가_없는_요청도_그대로_채점된다():
    """백엔드가 예전 형식으로 보내도 채점이 끝까지 돌아야 한다."""
    response = _score(with_english=False)

    assert len(response.checklist_results) == 2
    # 자리는 항상 있고, 값만 비어 있다. 백엔드가 분기 없이 읽을 수 있게 하려는 것이다
    assert all(result.description_en == "" for result in response.checklist_results)
    # 한국어 채점 기준은 손대지 않았다
    assert response.checklist_results[0].description == "안전모를 쓰지 않은 것을 지적했는가"


def test_HTTP_요청에_영어_칸이_없어도_200_이_나온다(monkeypatch):
    """계약 확인. 요청 본문에 description_en 키가 아예 없는 경우다."""
    # 인증 키가 심겨 있으면 401 이 나므로 개발 모드로 맞춰 놓고 본다
    monkeypatch.delenv(API_KEY_ENV, raising=False)
    body = {
        "submission_id": "sub-en-http",
        "mode": "writing",
        "answer_text": ANSWER,
        "item": {
            "item_id": "SPK-002",
            "prompt": "동료에게 위험을 알려 주세요.",
            "checklist": [
                {"id": "c1", "description": "안전모를 쓰지 않은 것을 지적했는가", "weight": 1.5},
            ],
        },
        "options": {"use_llm": False},
    }
    response = TestClient(app).post("/score", json=body)

    assert response.status_code == 200, response.text
    results = response.json()["checklist_results"]
    assert len(results) == 1
    assert results[0]["description_en"] == ""


# ---------------------------------------------------------------------------
# 2) 보내면 그대로 실린다
# ---------------------------------------------------------------------------


def test_영어를_보내면_대체_경로에서도_그대로_실린다():
    """LLM 을 못 쓰는 상황에서도 화면에 띄울 문장은 사라지면 안 된다."""
    response = _score(with_english=True)

    by_id = {result.id: result for result in response.checklist_results}
    assert by_id["c1"].description_en == "Point out that he is not wearing a safety helmet."
    assert by_id["c2"].description_en == "Tell him to wear a safety helmet."


@pytest.mark.parametrize(
    "payload",
    [
        # 충족 판정 (근거 인용이 원문에 있는 경우)
        {"results": [{"id": "c1", "met": 1, "quote": "안전모를 쓰지 않고", "reason": "지적함"}]},
        # 미충족 판정
        {"results": [{"id": "c1", "met": 0, "quote": "", "reason": "근거 없음"}]},
        # 지어낸 인용이라 폐기된 경우
        {"results": [{"id": "c1", "met": 1, "quote": "문서에 없는 말", "reason": "지어냄"}]},
        # 모델이 그 항목을 아예 판정하지 않은 경우
        {"results": []},
    ],
    ids=["충족", "미충족", "인용폐기", "판정없음"],
)
def test_LLM_판정_결과의_어느_갈래에서도_영어가_남는다(payload):
    """판정이 어떻게 갈리든 화면에 띄울 문장은 그대로 따라가야 한다."""
    checklist = _item(with_english=True).checklist[:1]

    results, _warnings, _notices, _dropped = results_from_llm_payload(
        ANSWER, checklist, payload
    )

    assert len(results) == 1
    assert results[0].description_en == "Point out that he is not wearing a safety helmet."


def test_영어는_LLM_프롬프트에_들어가지_않는다():
    """채점 기준은 한국어 그대로다. 영어가 프롬프트에 새면 판정 기준이 바뀐다."""
    prompt = build_prompt(ANSWER, _item(with_english=True))

    assert "안전모를 쓰지 않은 것을 지적했는가" in prompt
    assert "safety helmet" not in prompt
    assert "description_en" not in prompt


# ---------------------------------------------------------------------------
# 3) 문항 세트 두 개는 전부 영어를 갖고 있다
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("filename", ["speaking_v0.json", "writing_v0.json"])
def test_문항_세트의_모든_체크리스트에_영어_문장이_있다(filename):
    """빈 칸이 하나라도 있으면 리포트 화면의 'Required Points' 가 비어 보인다."""
    items = json.loads((ITEMS_DIR / filename).read_text(encoding="utf-8"))["items"]

    # 문항이 실제로 있는지부터 본다. 빈 파일이면 아래 검사가 조용히 통과해 버린다
    assert items, f"{filename} 에 문항이 없다"

    total = 0
    for item in items:
        for entry in item["checklist"]:
            where = f"{filename} {item['item_id']} {entry['id']}"
            english = entry.get("description_en", "")
            assert english.strip(), f"{where} 에 영어 문장이 없다"
            # 판정문("…했는가")이 아니라 응시자에게 시키는 말이어야 한다.
            # 한글이 섞여 있으면 한국어를 그대로 복사한 것이다
            assert not any("가" <= ch <= "힣" for ch in english), f"{where} 에 한글이 섞여 있다"
            # 문장 부호와 대문자는 파일 전체가 같은 모양이어야 한다
            assert english[0].isupper(), f"{where} 가 대문자로 시작하지 않는다"
            assert english.endswith("."), f"{where} 가 마침표로 끝나지 않는다"
            total += 1

    # 문항 5개 × 항목 3~4개 = 16개. 항목이 줄어들면 알아차리게 개수도 못 박는다
    assert total == 16, f"{filename} 의 체크리스트 항목이 {total}개다"


@pytest.mark.parametrize("filename", ["speaking_v0.json", "writing_v0.json"])
def test_문항_세트가_채점_계약으로_그대로_들어간다(filename):
    """items JSON 의 문항 객체는 ScoreRequest.item 에 그대로 넣을 수 있어야 한다."""
    items = json.loads((ITEMS_DIR / filename).read_text(encoding="utf-8"))["items"]

    for raw in items:
        converted = ItemInfo.model_validate(raw)
        # 영어가 변환 과정에서 떨어져 나가지 않는지 확인한다
        for entry, source in zip(converted.checklist, raw["checklist"]):
            assert entry.description_en == source["description_en"]
