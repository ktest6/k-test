"""원 모델이 붐벼서 못 받을 때 대체 모델로 갈아타는 동작의 회귀 방지 테스트.

**무엇을 막으려는 것인가 (2026-08-26 GCP 실측).**
오류 판정 모델(gemini-3-flash-preview)이 `503 UNAVAILABLE`("지금 사람이 몰렸다")를
내면서 한 건에 55~113초가 걸렸다. 정상일 때는 4~7초다. 그동안 응시자는 기다리기만
하다가 결국 '오류 자질 없음'으로 채점된다. 같은 순간 lite 모델은 멀쩡히 답했다.

그래서 503 일 때만 대체 모델로 한 번 갈아탄다. 여기서 못 박는 것은 네 가지다.
  (a) 503 이면 대체 모델로 다시 불러 성공하고, **누가 답했는지가 결과에 남는다**
  (b) 대체까지 503 이면 지금까지처럼 실패한다(원래 오류 코드 그대로)
  (c) 429(사용량 초과) 같은 다른 실패에는 갈아타지 않는다 — 바꿔 불러도 어차피 실패다
  (d) 갈아탈 곳이 없으면(설정 없음 · 원 모델과 같은 이름) 갈아타지 않는다

네트워크는 쓰지 않는다. 정해진 답을 돌려주는 가짜 서버를 붙여 '어느 모델로 몇 번
불렀는지'만 확인한다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.features.checklist import judge_checklist  # noqa: E402
from src.features.errors import extract_error_features  # noqa: E402
from src.llm.client import (  # noqa: E402
    DEFAULT_FALLBACK_MODEL,
    GeminiClient,
    GeminiConfig,
    LLMUnavailable,
)
from src.scoring.pipeline import score_submission  # noqa: E402
from src.scoring.schema import (  # noqa: E402
    ChecklistItem,
    ItemInfo,
    Mode,
    ScoreRequest,
)

# 실제로 받았던 503 응답을 줄여서 옮겨 둔 것. 로그에 찍힌 문구 그대로다.
REAL_503_BODY = (
    "503 UNAVAILABLE. {'error': {'code': 503, 'message': 'This model is currently "
    "experiencing high demand', 'status': 'UNAVAILABLE'}}"
)

# 사용량 초과. 이쪽은 모델을 바꿔도 소용이 없어서 갈아타면 안 되는 경우다.
REAL_429_BODY = (
    "429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': 'You exceeded your "
    "current quota', 'status': 'RESOURCE_EXHAUSTED'}}"
)

주모델 = "gemini-3-flash-preview"
대체모델 = "gemini-3.1-flash-lite"


class _FakeResponse:
    """서버가 준 응답 흉내. text 와 '왜 멈췄는지'만 있으면 된다."""

    def __init__(self, text: str, finish_reason: str = "STOP"):
        self.text = text
        self.candidates = [type("C", (), {"finish_reason": finish_reason})()]


class _FakeModels:
    """모델 이름에 따라 성공/실패를 미리 정해 둔 가짜 서버.

    `failing` 에 적힌 모델을 부르면 정해진 오류 문구로 터지고,
    나머지 모델은 정해진 JSON 을 돌려준다.
    어느 모델을 몇 번 불렀는지 `calls` 에 그대로 적어 둔다.
    """

    def __init__(self, failing: dict[str, str], payload: dict | None = None):
        self._failing = dict(failing)
        self._payload = payload if payload is not None else {"errors": []}
        self.calls: list[str] = []

    def generate_content(self, model, contents, config):
        self.calls.append(model)
        body = self._failing.get(model)
        if body is not None:
            # 진짜 SDK 가 던지는 것과 같은 모양(문구 안에 503/UNAVAILABLE 이 들어 있다)
            raise RuntimeError(body)
        return _FakeResponse(json.dumps(self._payload))


def _client(failing: dict[str, str], payload: dict | None = None, **config_kwargs):
    """가짜 서버를 붙인 클라이언트를 만든다(네트워크로 나가지 않는다)."""
    config_kwargs.setdefault("model", 주모델)
    config_kwargs.setdefault("fallback_model", 대체모델)
    client = GeminiClient(api_key="test-key", config=GeminiConfig(**config_kwargs))
    models = _FakeModels(failing, payload)
    # _ensure_client 는 접속 객체가 이미 있으면 그것을 그대로 쓴다. 그 자리에 가짜를 끼운다
    client._client = type("FakeGenai", (), {"models": models})()
    return client, models


# ---------------------------------------------------------------------------
# (a) 503 이면 대체 모델로 갈아탄다
# ---------------------------------------------------------------------------


def test_503_이면_대체_모델로_한_번_다시_불러_성공한다():
    """붐비는 모델 하나 때문에 채점이 통째로 비는 일이 없어야 한다."""
    client, models = _client({주모델: REAL_503_BODY})

    result = client.generate_json("아무 지시문")

    assert result == {"errors": []}
    # 원 모델 한 번, 대체 모델 한 번. 딱 두 번만 불렀다
    assert models.calls == [주모델, 대체모델]


def test_실제로_답한_모델_이름이_결과에_남는다():
    """부르려던 이름을 그대로 적으면 나중에 이 판정을 재현할 수 없다."""
    client, _ = _client({주모델: REAL_503_BODY})

    client.generate_json("아무 지시문")

    assert client.last_model_used == 대체모델
    assert client.last_fallback_from == 주모델
    # 부르려던 이름(model_name)은 그대로다. 두 값은 서로 다른 것을 뜻한다
    assert client.model_name == 주모델


def test_갈아타지_않은_평범한_호출은_대체_표시가_없다():
    """정상 호출까지 '대체했다'고 표시되면 경고가 의미를 잃는다."""
    client, models = _client({})

    client.generate_json("아무 지시문")

    assert client.last_model_used == 주모델
    assert client.last_fallback_from is None
    assert models.calls == [주모델]


def test_실패로_끝나면_지난_호출의_모델_이름이_남지_않는다():
    """옛날 기록이 남아 있으면 이번에 안 부른 모델이 결과에 실려 나간다."""
    client, _ = _client({})
    client.generate_json("첫 호출")           # 여기서 주모델로 성공
    assert client.last_model_used == 주모델

    # 두 번째 호출은 원 모델도 대체 모델도 전부 막힌 상황
    client._client.models._failing = {주모델: REAL_503_BODY, 대체모델: REAL_503_BODY}
    with pytest.raises(LLMUnavailable):
        client.generate_json("둘째 호출")

    assert client.last_model_used is None
    assert client.last_fallback_from is None


# ---------------------------------------------------------------------------
# (b) 대체까지 실패하면 지금까지처럼 실패한다
# ---------------------------------------------------------------------------


def test_대체도_503_이면_원래_오류_코드로_실패한다():
    """대체가 안 되는 상황을 새로운 오류로 포장하면 대처 방법이 달라 보인다."""
    client, models = _client({주모델: REAL_503_BODY, 대체모델: REAL_503_BODY})

    with pytest.raises(LLMUnavailable) as caught:
        client.generate_json("아무 지시문")

    # 채점 결과에 실릴 코드는 지금까지와 똑같은 '서버 일시 오류'다
    assert caught.value.code == "LLM_SERVER_ERROR"
    # 두 번 부르고 끝냈다(끝없이 매달리지 않는다)
    assert models.calls == [주모델, 대체모델]
    # 무엇을 더 시도했는지는 개발자용 detail 에만 남는다(응시자 문구에는 안 나간다)
    assert 대체모델 in caught.value.detail
    assert 대체모델 not in str(caught.value)


# ---------------------------------------------------------------------------
# (c) 갈아타도 소용없는 실패에는 갈아타지 않는다
# ---------------------------------------------------------------------------


def test_사용량_초과는_대체_모델을_부르지_않는다():
    """모델을 바꿔도 똑같이 막히는 실패다. 두 번 부르면 기다리는 시간만 는다."""
    client, models = _client({주모델: REAL_429_BODY})

    with pytest.raises(LLMUnavailable) as caught:
        client.generate_json("아무 지시문")

    assert caught.value.code == "LLM_QUOTA_EXHAUSTED"
    assert models.calls == [주모델]


# ---------------------------------------------------------------------------
# (d) 갈아탈 곳이 없으면 갈아타지 않는다
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fallback, 설명",
    [
        (None, "설정을 아예 비웠다"),
        ("", "빈 문자열을 넣었다"),
        (주모델, "원 모델과 같은 이름을 넣었다"),
    ],
)
def test_갈아탈_곳이_없으면_한_번만_부른다(fallback, 설명):
    """같은 모델을 또 부르거나 빈 이름으로 부르는 사고를 막는다."""
    client, models = _client({주모델: REAL_503_BODY}, fallback_model=fallback)

    with pytest.raises(LLMUnavailable) as caught:
        client.generate_json("아무 지시문")

    assert caught.value.code == "LLM_SERVER_ERROR", 설명
    assert models.calls == [주모델], 설명


def test_기본_대체_모델은_lite_다():
    """설정을 안 건드린 서버가 갈아탈 곳 없이 도는 일이 없어야 한다."""
    assert DEFAULT_FALLBACK_MODEL == "gemini-3.1-flash-lite"
    assert GeminiConfig().fallback_model == DEFAULT_FALLBACK_MODEL


def test_모델만_바꿔_만든_클라이언트도_대체_설정을_물려받는다():
    """오류 판정용 클라이언트는 for_model 로 만들어진다. 여기서 설정이 빠지면 소용없다."""
    base = GeminiClient(api_key="test-key", config=GeminiConfig(model=대체모델))
    갈아탄것 = base.for_model(주모델)

    assert 갈아탄것.model_name == 주모델
    assert 갈아탄것.fallback_model == DEFAULT_FALLBACK_MODEL


# ---------------------------------------------------------------------------
# 채점 결과까지 이어지는지
# ---------------------------------------------------------------------------


ITEM = ItemInfo(
    item_id="item-1",
    prompt="기계 고장을 반장님에게 보고하세요.",
    checklist=[
        ChecklistItem(id="c1", description="고장 사실을 말했는가"),
        ChecklistItem(id="c2", description="조치 방안을 물었는가"),
    ],
)

ANSWER = (
    "반장님 지금 삼번 라인 포장 기계가 갑자기 멈췄습니다. "
    "제가 전원을 차단하고 정비팀에 연락할까요?"
)


def test_오류_판정이_대체_모델로_돌면_결과에_모델과_경고가_남는다():
    """점수만 나오고 '누가 판정했는지'가 없으면 근거로 쓸 수 없다."""
    error_client, models = _client(
        {주모델: REAL_503_BODY}, payload={"errors": []}
    )

    result = extract_error_features(ANSWER, mode=Mode.SPEAKING, client=error_client)

    assert result.llm_used is True
    assert result.llm_model_used == 대체모델
    assert result.llm_fallback_from == 주모델
    assert models.calls == [주모델, 대체모델]


def test_체크리스트_판정도_실제로_답한_모델을_남긴다():
    """세 호출 중 어디서 갈아탔는지 구분되지 않으면 근거가 되지 않는다."""
    client, _ = _client(
        {주모델: REAL_503_BODY},
        payload={"judgements": [
            {"id": "c1", "met": True, "quote": "갑자기 멈췄습니다", "reason": "고장을 말함"},
        ]},
    )

    result = judge_checklist(ANSWER, ITEM, client=client)

    assert result.llm_used is True
    assert result.llm_model_used == 대체모델
    assert result.llm_fallback_from == 주모델


def test_채점_한_건의_meta_와_경고에_대체_사실이_실린다():
    """백엔드가 받는 자리(meta · warnings · notices)까지 실제로 도달해야 한다."""
    # 체크리스트·전사 보정용 기본 클라이언트는 정상, 오류 판정 모델만 붐비는 상황을 만든다.
    # (실제 운영과 같은 모양이다 — 갈아타는 것은 오류 판정 쪽뿐이다)
    base_client, _ = _client({}, model=대체모델, fallback_model=대체모델,
                             payload={"judgements": []})
    error_client, error_models = _client({주모델: REAL_503_BODY}, payload={"errors": []})

    # client_for_errors 는 진짜 GeminiClient 를 받으면 모델만 바꾼 새 클라이언트를
    # 만들어 버린다(그러면 가짜 서버가 떨어져 나간다). 그 자리에 우리 가짜를 그대로 꽂는다
    import src.scoring.pipeline as pipeline
    원래함수 = pipeline.client_for_errors
    pipeline.client_for_errors = lambda base: error_client
    try:
        response = score_submission(
            ScoreRequest(
                submission_id="sub-1",
                mode=Mode.SPEAKING,
                answer_text=ANSWER,
                item=ITEM,
            ),
            client=base_client,
        )
    finally:
        pipeline.client_for_errors = 원래함수

    # 문법을 판정한 것은 대체 모델이다. 그 이름이 그대로 결과에 적혀야 한다
    assert response.meta.llm_model_errors == 대체모델
    # 체크리스트는 갈아타지 않았으므로 기본 모델 그대로다
    assert response.meta.llm_model == 대체모델
    assert error_models.calls == [주모델, 대체모델]

    # 경고와 코드 목록 양쪽에 같은 내용이 한 줄씩 들어간다
    codes = [n.code for n in response.notices]
    assert "LLM_FALLBACK_MODEL_USED" in codes
    실린것 = response.notices[codes.index("LLM_FALLBACK_MODEL_USED")]
    assert 실린것.params == {"from": 주모델, "to": 대체모델, "stage": "errors"}
    # warnings 와 notices 는 길이도 차례도 항상 같아야 한다(백엔드가 짝을 짓는다)
    assert len(response.warnings) == len(response.notices)
    assert 실린것.message in response.warnings


def test_갈아타지_않은_평범한_채점에는_대체_경고가_없다():
    """정상 채점에 없는 경고가 붙으면 응시자가 무슨 문제가 있었다고 오해한다."""
    base_client, _ = _client({}, model=대체모델, fallback_model=대체모델,
                             payload={"judgements": []})
    error_client, _ = _client({}, payload={"errors": []})

    import src.scoring.pipeline as pipeline
    원래함수 = pipeline.client_for_errors
    pipeline.client_for_errors = lambda base: error_client
    try:
        response = score_submission(
            ScoreRequest(
                submission_id="sub-2",
                mode=Mode.SPEAKING,
                answer_text=ANSWER,
                item=ITEM,
            ),
            client=base_client,
        )
    finally:
        pipeline.client_for_errors = 원래함수

    assert "LLM_FALLBACK_MODEL_USED" not in [n.code for n in response.notices]
    assert response.meta.llm_model_errors == 주모델
