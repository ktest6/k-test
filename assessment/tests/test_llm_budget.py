"""답변 예산·대기 시간과 '잘린 답' 처리에 대한 회귀 방지 테스트.

2026-08-06 에 실제로 겪은 사고 두 가지를 다시 겪지 않기 위한 것이다.
  1) 대기 시간 60초 — 생각하는 모델의 정상 응답(55~68초)을 우리가 끊고 있었다
  2) 답변 예산 4096 — 생각 토큰이 답할 자리를 먹어 치워 답이 잘리고,
     잘린 답이 JSON 으로 안 읽혀 오류 자질 네 개가 통째로 사라졌다

여기서는 네트워크를 쓰지 않는다. 정해진 답을 돌려주는 가짜 서버를 붙여
'무엇을 보내는지'와 '잘렸을 때 어떻게 하는지'만 확인한다.
실제 호출로 값을 확인하는 것은 scripts/check_llm_budget.py 가 맡는다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.llm.client import (  # noqa: E402
    DEFAULT_MAX_OUTPUT_TOKENS,
    DEFAULT_TIMEOUT_MS,
    GeminiClient,
    GeminiConfig,
    LLMUnavailable,
)


class _FakeResponse:
    """서버가 준 응답 흉내. text 와 '왜 멈췄는지'만 있으면 된다."""

    def __init__(self, text: str, finish_reason: str = "STOP"):
        self.text = text
        # 진짜 라이브러리는 후보 목록 안에 finish_reason 을 넣어 준다. 그 모양을 그대로 흉내 낸다
        self.candidates = [type("C", (), {"finish_reason": finish_reason})()]


class _FakeModels:
    """호출을 받아 적어 두고, 미리 정해 둔 응답을 순서대로 돌려주는 가짜."""

    def __init__(self, responses: list[_FakeResponse]):
        self._responses = list(responses)
        self.calls: list[dict] = []

    def generate_content(self, model, contents, config):
        # 이번 호출이 어떤 예산·대기 시간으로 나갔는지 남겨 둔다(테스트가 볼 자리)
        self.calls.append(
            {
                "model": model,
                "max_output_tokens": config.max_output_tokens,
                "timeout": config.http_options.timeout,
            }
        )
        # 응답을 다 써 버렸으면 마지막 것을 계속 돌려준다
        if len(self._responses) > 1:
            return self._responses.pop(0)
        return self._responses[0]


def _client_with(responses: list[_FakeResponse], **config_kwargs) -> tuple[GeminiClient, _FakeModels]:
    """가짜 서버를 붙인 클라이언트를 만든다(네트워크로 나가지 않는다)."""
    client = GeminiClient(api_key="test-key", config=GeminiConfig(**config_kwargs))
    fake_models = _FakeModels(responses)
    # _ensure_client 는 접속 객체가 이미 있으면 그것을 그대로 쓴다. 그 자리에 가짜를 끼운다
    client._client = type("FakeGenai", (), {"models": fake_models})()
    return client, fake_models


def test_기본값이_실측으로_정한_값에서_내려가지_않았다():
    """8/6 사고를 되돌리는 수정(예산·대기 시간 축소)을 막는 잠금장치."""
    config = GeminiConfig()
    # 60초는 정상 응답(55~68초)을 끊는 값이었다. 다시 그 아래로 내려가면 안 된다
    assert config.timeout_ms == DEFAULT_TIMEOUT_MS == 300_000
    # 4096 은 생각 토큰(3931)이 답할 자리를 남기지 않던 값이다
    assert config.max_output_tokens == DEFAULT_MAX_OUTPUT_TOKENS == 16_384


def test_정한_예산과_대기시간이_실제_호출에_실린다():
    """설정만 바꿔 놓고 호출에는 안 실리는 일이 없도록 확인한다."""
    payload = json.dumps({"errors": []})
    client, models = _client_with([_FakeResponse(payload)])

    result = client.generate_json("아무 지시문")

    assert result == {"errors": []}
    assert models.calls[0]["max_output_tokens"] == 16_384
    assert models.calls[0]["timeout"] == 300_000


def test_답이_잘리면_예산을_키워_한_번_더_부른다():
    """잘린 답을 그냥 버리면 그 답안만 오류 자질 없이 채점된다. 한 번은 더 시도한다."""
    잘린_답 = _FakeResponse('{"errors": [{"type": "josa", "quo', finish_reason="MAX_TOKENS")
    성한_답 = _FakeResponse(json.dumps({"errors": [{"type": "josa"}]}))
    client, models = _client_with([잘린_답, 성한_답])

    result = client.generate_json("아무 지시문")

    # 두 번째 호출의 결과가 살아 나왔고
    assert result["errors"][0]["type"] == "josa"
    # 두 번째는 예산만 두 배로 키워 다시 나갔다
    assert [c["max_output_tokens"] for c in models.calls] == [16_384, 32_768]


def test_두_번째도_잘리면_지어내지_않고_사유를_밝히며_실패한다():
    """반쪽짜리 결과를 채점에 흘려보내지 않는다. 대신 무엇이 문제였는지 말한다."""
    잘린_답 = _FakeResponse('{"errors": [{"type": "jo', finish_reason="MAX_TOKENS")
    client, models = _client_with([잘린_답])

    with pytest.raises(LLMUnavailable) as caught:
        client.generate_json("아무 지시문")

    # 채점 결과에 실릴 문구는 '형식이 깨졌다'가 아니라 '잘렸다'여야 한다.
    # 원인이 다르면 대처도 다르기 때문이다(잘림은 예산 문제, 형식은 프롬프트 문제)
    assert "잘렸다" in str(caught.value)
    assert len(models.calls) == 2


def test_재시도를_끄면_바로_실패하고_한_번만_부른다():
    """비용이 걱정될 때 재시도를 끌 수 있어야 한다. 껐다면 두 번 부르지 않는다."""
    잘린_답 = _FakeResponse('{"errors": [', finish_reason="MAX_TOKENS")
    client, models = _client_with([잘린_답], retry_budget_multiplier=1)

    with pytest.raises(LLMUnavailable, match="잘렸다"):
        client.generate_json("아무 지시문")

    assert len(models.calls) == 1


def test_정상_종료는_잘림으로_오해하지_않는다():
    """멀쩡한 답을 잘렸다고 판단해 버리는 일이 없어야 한다(응답 모양이 낯설 때 포함)."""
    payload = json.dumps({"ok": True})
    # 정상 종료(STOP)
    client, models = _client_with([_FakeResponse(payload)])
    assert client.generate_json("지시문") == {"ok": True}
    assert len(models.calls) == 1

    # finish_reason 을 아예 안 주는 응답도 '잘리지 않았다'로 본다
    민숭한_응답 = _FakeResponse(payload)
    민숭한_응답.candidates = []
    client, models = _client_with([민숭한_응답])
    assert client.generate_json("지시문") == {"ok": True}
    assert len(models.calls) == 1


def test_받아쓰기와_문항생성은_각자_설정을_따로_쓴다():
    """채점 기본값을 올린 것이 받아쓰기·생성까지 끌고 가지 않는지 확인한다.

    받아쓰기는 무음 관문 뒤에 있어서 오래 기다리면 응시 흐름이 그대로 밀린다.
    그래서 채점(300초)과 같이 움직이면 안 되고, 자기 값(90초)을 지켜야 한다.
    """
    from src.generation.llm import GENERATION_TIMEOUT_MS, generation_config
    from src.speech.gemini_stt import STT_MAX_OUTPUT_TOKENS, STT_TIMEOUT_MS

    # 받아쓰기는 GeminiConfig 를 아예 쓰지 않고 자기 상수로 호출한다
    assert STT_TIMEOUT_MS == 90_000
    assert STT_MAX_OUTPUT_TOKENS == 4096
    assert STT_TIMEOUT_MS < DEFAULT_TIMEOUT_MS

    # 생성은 GeminiConfig 를 쓰되 예산·대기 시간을 스스로 지정한다
    gen = generation_config(item_count=3)
    assert gen.timeout_ms == GENERATION_TIMEOUT_MS == 120_000
    assert gen.max_output_tokens == 4096 + 2048 * 3
    # 다만 '잘리면 한 번 더' 는 생성에서도 그대로 쓴다(문항이 반쪽으로 나오는 것을 막는다)
    assert gen.retry_budget_multiplier == 2
