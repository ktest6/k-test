"""Gemini 호출을 감싸는 얇은 래퍼.

채점 신뢰도를 위해 다음 세 가지를 이 파일에서 강제한다. 옵션이 아니라 기본값이다.
1) temperature = 0  : 같은 답안을 두 번 채점하면 같은 결과가 나와야 한다.
2) JSON 응답 강제    : 자유 문장 대신 정해진 구조로 받아야 자동 처리가 가능하다.
3) 인용 강제         : 프롬프트에서 원문 인용을 요구하고, 검증은 citation.py 가 맡는다.
4) 잘린 답 걸러내기  : 답이 길이 제한에 걸려 끊긴 것을 형식 오류와 구분해서 다룬다.
                      (아래 DEFAULT_MAX_OUTPUT_TOKENS 설명 참고 — 자질이 조용히 사라지는 사고를 막는다)

여기 기본값은 **채점 호출에만** 적용된다.
받아쓰기와 문항 만들기는 각자 자기 설정을 따로 들고 있으므로 이 값을 올려도 끌려오지 않는다
(각 모듈 파일 위쪽 설명 참고. 채점 쪽이 그 둘을 불러다 쓰지 않는 것은 테스트로 못 박혀 있다).

API 키는 환경변수 GEMINI_API_KEY 에서 읽는다. 코드에 키를 적지 않는다.
프로젝트 루트의 .env 파일도 읽는다(python-dotenv).
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, replace
from typing import Any

from dotenv import load_dotenv

# 실패한 호출의 자세한 내용은 화면이 아니라 로그로 보낸다.
# 채점 결과에 실리는 문구와 개발자가 볼 진단 정보를 분리하기 위해서다
logger = logging.getLogger(__name__)

# .env 파일이 있으면 환경변수로 올린다. 이미 설정된 환경변수는 덮어쓰지 않는다.
load_dotenv(override=False)

# 기본 모델. 체크리스트 판정과 자질 추출은 고난도 추론이 아니라서
# 비용과 응답 속도가 더 중요하다고 판단해 flash 계열 중에서도 lite 를 기본값으로 둔다.
#
# 무료 등급의 하루 호출 한도는 '모델마다 따로' 걸린다.
# 상위 모델일수록 그 한도가 작아서(3.5-flash 는 하루 20회) 개발 중에 금방 막힌다.
# lite 는 한도가 넉넉하고 단가도 10배 이상 싸다.
# 바꾸려면 코드가 아니라 .env 의 GEMINI_MODEL 을 고치면 된다.
DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")

# 오류 자질(조사·어미 활용·어휘 오용·높임법)만 이 모델로 돌린다.
#
# 왜 여기만 따로 두는가 (2026-07-30 실측):
# "어제 반장님이 말했습니다" 는 상급자를 안 높인 높임법 오류인데,
# lite 모델은 이것을 한 번도 잡지 못했고 상위 모델은 잡았다.
# 오류를 못 찾으면 그 답안은 '틀린 것이 없는 답안'이 되어 점수가 부풀려지므로,
# 문법 판정만큼은 비용보다 정확도를 앞에 둔다.
# 체크리스트 판정과 전사 보정은 지금까지대로 GEMINI_MODEL 을 쓴다.
#
# 모델 이름 주의: 'gemini-3-flash' 가 아니라 'gemini-3-flash-preview' 다.
# 이 키로 실제 호출이 되는 것을 확인한 이름이다.
DEFAULT_ERROR_MODEL = os.getenv("GEMINI_MODEL_ERRORS", "gemini-3-flash-preview")


class LLMUnavailable(RuntimeError):
    """API 키가 없거나 호출에 실패해서 LLM을 쓸 수 없을 때 올리는 예외.

    이 예외가 나면 파이프라인은 멈추지 않고, 규칙 자질만으로 채점하는
    임시 대체 경로로 넘어간다(그 사실은 응답의 warnings 에 남는다).

    이 예외의 메시지는 **채점 결과에 그대로 실린다.**
    warnings 와 영역별 note 는 백엔드가 받아 응시자에게 보여줄 수 있는 자리라서,
    여기에는 사람이 읽을 짧은 한 문장만 담는다.
    서버가 돌려준 원문(JSON 덩어리)은 detail 에 따로 담고 로그로만 내보낸다.
    """

    def __init__(self, message: str, detail: str = ""):
        super().__init__(message)
        # 개발자가 원인을 찾을 때 쓰는 자리. 채점 결과에는 실리지 않는다
        self.detail = detail


# 호출이 실패하는 이유는 여러 가지지만, 결과를 읽는 사람에게 필요한 것은
# "무슨 일이 있었고 내가 무엇을 하면 되는가" 한 줄이다.
# (서버 응답에서 찾을 표시, 사람이 읽을 문구) 짝으로 적어 둔다.
_FAILURE_PATTERNS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("RESOURCE_EXHAUSTED", "429", "quota"),
     "LLM 하루 호출 한도를 다 썼다(429). 한도가 풀리거나 결제를 활성화해야 한다."),
    (("NOT_FOUND", "404"),
     "요청한 LLM 모델을 쓸 수 없다(404). .env 의 GEMINI_MODEL 을 확인해야 한다."),
    (("PERMISSION_DENIED", "403", "API_KEY_INVALID", "API key not valid"),
     "LLM 접근이 거부됐다(403). API 키가 올바른지 확인해야 한다."),
    (("UNAUTHENTICATED", "401"),
     "LLM 인증에 실패했다(401). API 키를 확인해야 한다."),
    (("DEADLINE_EXCEEDED", "timeout", "Timeout", "timed out"),
     "LLM 응답이 제한 시간 안에 오지 않았다."),
    (("UNAVAILABLE", "503", "500", "INTERNAL"),
     "LLM 서버가 일시적으로 응답하지 않는다."),
    (("ConnectionError", "Connection", "getaddrinfo", "Network"),
     "LLM 서버에 연결하지 못했다. 네트워크를 확인해야 한다."),
)


def classify_failure(exc: Exception) -> str:
    """호출 실패의 원인을 사람이 읽을 한 문장으로 바꾼다.

    분류를 이 함수 한 곳에서만 하는 이유:
    같은 판별을 여러 파일에 흩어 놓으면 새로운 오류 유형이 생겼을 때
    어떤 곳은 고쳐지고 어떤 곳은 안 고쳐져서 문구가 제각각이 된다.
    """
    text = str(exc)
    for markers, message in _FAILURE_PATTERNS:
        if any(marker in text for marker in markers):
            return message
    # 어디에도 해당하지 않으면 예외 종류만 밝힌다.
    # 서버 응답 원문을 여기에 붙이면 안 된다(채점 결과에 그대로 실린다)
    return f"LLM 호출에 실패했다({type(exc).__name__})."


# 답변 길이 상한. **생각(thinking) 토큰이 이 예산에서 같이 깎인다.**
#
# 왜 16384 인가 (2026-08-06 사고 + 2026-08-07 실측):
# 문법 판정 모델(gemini-3-flash-preview)은 답하기 전에 혼자 생각을 하는데,
# 그 생각도 이 예산에서 나간다. 4096 으로 두었더니 생각에 3931, 답에 150 을 쓰고
# 문장 한가운데서 잘렸다(finish=MAX_TOKENS). 잘린 답은 JSON 으로 읽히지 않아
# **오류 자질 네 개가 통째로 사라지고 언어 사용 점수가 반쪽**이 된다.
# 사람 전사 15건 중 3건(전부 93자 이상)이 그랬다.
# 같은 답안을 16384 로 부르면 4번 모두 끝까지 답했다(finish=STOP, JSON 정상).
#
# 더 올리지 않는 이유: 생각의 양이 예산에 비례해 늘어난다(실측 — 생각 토큰이
# 늘 예산의 96% 언저리까지 찬다). 예산을 키운 만큼 대기 시간과 비용이 그대로 늘어난다.
#   4096 -> 생각 3931 / 21초(그러나 답이 잘림)
#   16384 -> 생각 15724 / 57~68초 (답 126~230 토큰, 정상)
#   32768 -> 생각 31455 / 115초 (더 안전하지만 두 배 느리고 두 배 비싸다)
# 그래서 평소에는 16384 로 돌리고, 그래도 잘리는 드문 답안만 아래 재시도로 건진다.
#
# '생각 예산만 따로 묶는' 방법을 안 쓴 이유 (2026-08-07 같은 답안으로 실측):
# 라이브러리에는 생각의 양을 지정하는 설정(ThinkingConfig)이 있지만 둘 다 못 믿는다.
#   - thinking_budget=1024 를 줘도 생각을 3931 토큰 했다. 지정이 무시된 것이다
#     (안 준 호출과 토큰 수가 같았다).
#   - thinking_level=LOW 는 첫 호출에서 884(먹히는 듯) → 같은 입력 재호출에서 15725.
#     같은 설정이 호출마다 다르게 동작하니 채점 기준으로 삼을 수 없다.
# 지켜지지 않는 설정에 기대는 것보다, 예산을 넉넉히 주고 잘림을 직접 확인하는 쪽이 안전하다.
DEFAULT_MAX_OUTPUT_TOKENS = 16_384

# 기다려 줄 시간.
#
# 왜 300초인가 (2026-08-06 실측):
# 생각하는 모델의 정상 응답이 55~68초 걸리는 일이 흔하다. 60초에서 끊고 있었더니
# 실패가 전부 56~62초 구간에 몰렸다 — 남의 서버 장애가 아니라 우리가 끊은 것이었다.
# 300초로 늘리자 3회 연속 실패하던 191자 답안이 첫 시도에 68.1초로 정상 판정됐다.
# 위 재시도(예산 2배)까지 겹치면 최악이 68+115=183초라 그 위로도 여유가 있어야 한다.
DEFAULT_TIMEOUT_MS = 300_000


@dataclass
class GeminiConfig:
    """호출 설정. temperature 는 0에서 바꾸지 않는 것을 전제로 한다.

    **다만 temperature 0 이 같은 답을 보장하지는 못했다(2026-08-07 실측).**
    같은 171자 답안을 같은 설정으로 세 번 판정했더니 오류를 4건·2건·2건으로 다르게 잡았고
    인용한 자리도 달랐다. 재현성은 규칙 자질 쪽에서 지켜지고 있으며,
    생각하는 모델의 판정은 아직 그렇지 않다. 이 흔들림을 얼마나 줄일 수 있는지는
    남은 과제이고, 여기 설정을 바꾼다고 해결되는 문제가 아니다.
    """

    model: str = DEFAULT_MODEL
    temperature: float = 0.0
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS
    timeout_ms: int = DEFAULT_TIMEOUT_MS
    # 답이 예산 안에서 끝나지 못하고 잘렸을 때, 예산을 몇 배로 키워 한 번만 다시 부를지.
    # 1 로 두면 다시 부르지 않고 그대로 실패로 처리한다.
    # 잘린 답을 그냥 버리면 그 응시자만 오류 자질 없이 채점되므로, 값을 못 얻는 것보다
    # 한 번 더 부르는 쪽이 낫다고 보고 기본값을 2로 둔다(실제로 부르는 일은 드물다).
    retry_budget_multiplier: int = 2


class GeminiClient:
    """Gemini 를 JSON 모드로만 호출하는 클라이언트."""

    def __init__(self, api_key: str | None = None, config: GeminiConfig | None = None):
        self.config = config or GeminiConfig()
        # 키는 직접 넘겨줄 수도 있지만, 평소에는 환경변수에서 읽는다
        # 코드 어디에도 키를 적어 두지 않기 위해서다
        self._api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        # 실제 접속 객체는 처음 쓸 때 만든다(키가 없으면 끝까지 안 만들어도 된다)
        self._client = None

    @property
    def available(self) -> bool:
        """키가 있어서 호출을 시도할 수 있는 상태인지."""
        return bool(self._api_key)

    @property
    def model_name(self) -> str:
        return self.config.model

    def for_model(self, model: str) -> "GeminiClient":
        """같은 키를 쓰면서 모델만 바꾼 클라이언트를 만든다.

        키를 다시 읽거나 설정을 복사해 붙이는 코드가 여기저기 생기지 않도록
        만드는 자리를 한 곳으로 모아 둔 것이다.
        temperature 0 · JSON 강제 같은 나머지 설정은 그대로 물려받는다.
        """
        # 이미 그 모델이면 새로 만들 것이 없다
        if model == self.config.model:
            return self
        return GeminiClient(
            api_key=self._api_key, config=replace(self.config, model=model)
        )

    def _ensure_client(self):
        """접속 객체를 준비한다. 키가 없으면 여기서 막는다."""
        # 키가 없으면 여기서 딱 잘라 막는다. 파이프라인은 이 예외를 받아 대체 경로로 넘어간다
        if not self._api_key:
            raise LLMUnavailable(
                "GEMINI_API_KEY 가 설정되어 있지 않습니다. "
                ".env 파일이나 환경변수에 키를 넣어 주세요."
            )

        # 접속 객체는 한 번만 만들어 두고 계속 쓴다(매번 만들면 느려진다)
        if self._client is None:
            try:
                # 패키지를 이 자리에서 불러오는 이유: 키가 없어 LLM을 안 쓰는 실행에서는
                # 무거운 라이브러리를 아예 읽지 않게 하려는 것이다
                from google import genai
            except ImportError as exc:  # pragma: no cover
                raise LLMUnavailable(f"google-genai 패키지를 불러올 수 없습니다: {exc}") from exc
            self._client = genai.Client(api_key=self._api_key)
        return self._client

    def _call_once(
        self,
        client,
        prompt: str,
        system_instruction: str,
        response_schema: Any | None,
        max_output_tokens: int,
    ):
        """실제로 한 번 부르는 자리. 예산만 바꿔 다시 부를 수 있도록 떼어 두었다."""
        from google.genai import types

        # 채점 신뢰도를 지키는 설정을 여기서 못 박는다
        config = types.GenerateContentConfig(
            temperature=self.config.temperature,   # 재현성을 위해 0 고정
            max_output_tokens=max_output_tokens,
            response_mime_type="application/json",  # 자유 문장이 아니라 JSON으로 받는다
            system_instruction=system_instruction or None,
            response_schema=response_schema,
            http_options=types.HttpOptions(timeout=self.config.timeout_ms),
        )

        try:
            return client.models.generate_content(
                model=self.config.model,
                contents=prompt,
                config=config,
            )
        except Exception as exc:
            # 네트워크 끊김, 키 오류, 사용량 초과 등 실패 이유는 여러 가지지만
            # 파이프라인 입장에서는 "LLM을 못 썼다"는 하나의 상황이므로 한 갈래로 모은다.
            # 서버가 준 원문은 로그로만 남기고, 채점 결과에는 짧은 사유만 올린다
            reason = classify_failure(exc)
            logger.warning("Gemini 호출 실패 [%s]: %s", self.config.model, exc)
            raise LLMUnavailable(reason, detail=str(exc)) from exc

    def generate_json(
        self,
        prompt: str,
        system_instruction: str = "",
        response_schema: Any | None = None,
    ) -> dict[str, Any]:
        """프롬프트를 보내고 JSON(dict)으로 받는다.

        response_schema 를 주면 Gemini 쪽에서 구조를 강제한다.
        그래도 모델이 형식을 깨는 경우가 있으므로 파싱 실패도 예외로 다룬다.

        답이 길이 제한에 걸려 잘린 경우를 **파싱 실패와 따로 구분한다.**
        둘 다 결과적으로는 'JSON 을 못 읽었다'지만 원인과 대처가 다르다.
        잘린 것은 예산을 키우면 살아나고, 형식이 깨진 것은 키워도 소용이 없다.
        구분하지 않았더니 8/6 사고에서 원인을 찾는 데 시간이 걸렸다.
        """
        # 접속 준비. 키가 없으면 여기서 LLMUnavailable 이 나고 호출은 시도조차 하지 않는다
        client = self._ensure_client()

        response = self._call_once(
            client, prompt, system_instruction, response_schema,
            self.config.max_output_tokens,
        )

        # 답이 끝까지 나오지 못하고 잘렸는지 본다.
        # 잘린 답은 거의 항상 JSON 이 깨져 있어서, 그대로 두면 자질이 통째로 사라진다
        if _is_truncated(response):
            multiplier = max(1, int(self.config.retry_budget_multiplier))
            bigger = self.config.max_output_tokens * multiplier
            if multiplier <= 1:
                # 다시 부르지 않기로 설정된 경우. 무슨 일이 있었는지는 분명히 남긴다
                raise LLMUnavailable(
                    "LLM 답이 길이 제한에 걸려 잘렸다(답변 예산이 모자랐다).",
                    detail=f"max_output_tokens={self.config.max_output_tokens}, 재시도 꺼짐",
                )
            logger.warning(
                "Gemini 답이 잘려 예산을 키워 다시 부른다 [%s]: %d -> %d",
                self.config.model, self.config.max_output_tokens, bigger,
            )
            response = self._call_once(
                client, prompt, system_instruction, response_schema, bigger
            )
            # 예산을 두 배로 줬는데도 잘렸다면 이 답안은 이 설정으로 감당이 안 되는 것이다.
            # 반쪽짜리 결과를 지어내지 않고 실패로 두고, 사유를 그대로 밝힌다
            if _is_truncated(response):
                raise LLMUnavailable(
                    "LLM 답이 길이 제한에 걸려 잘렸다(예산을 늘려 다시 불러도 마찬가지였다).",
                    detail=f"max_output_tokens={self.config.max_output_tokens} -> {bigger}",
                )

        # 안전 필터에 걸리거나 답을 못 만들면 빈 응답이 온다. 이것도 실패로 다룬다
        text = (response.text or "").strip()
        if not text:
            raise LLMUnavailable(
                "LLM이 빈 응답을 보냈다(안전 필터에 걸렸거나 답을 만들지 못했다)."
            )

        return _parse_json_object(text)


def _is_truncated(response: Any) -> bool:
    """응답이 '길이 제한에 걸려 잘린' 것인지 확인한다.

    서버는 답을 왜 멈췄는지 finish_reason 으로 알려 준다. 그 값이 MAX_TOKENS 면
    할 말이 남았는데 예산이 떨어져서 끊긴 것이다(정상 종료는 STOP).

    가짜 클라이언트로 시험할 때도 통하도록, 값을 정해진 종류로 비교하지 않고
    이름 글자에 MAX_TOKENS 가 들어 있는지로 본다.
    응답 모양이 예상과 다르면 '잘리지 않았다'로 보고 넘어간다 —
    여기서 잘못 판단해 멀쩡한 답을 버리는 일이 없어야 한다.
    """
    candidates = getattr(response, "candidates", None) or []
    for candidate in candidates:
        reason = getattr(candidate, "finish_reason", None)
        if reason is None:
            continue
        # enum 이면 name, 문자열이면 그 자체를 본다
        label = str(getattr(reason, "name", reason)).upper()
        if "MAX_TOKENS" in label:
            return True
    return False


def _parse_json_object(text: str) -> dict[str, Any]:
    """모델이 준 문자열을 dict 로 만든다.

    JSON 모드를 켜도 앞뒤에 군더더기가 붙는 일이 있다. 실제로 겪은 두 가지는
      - 앞뒤에 ```json 표시나 설명 문장이 붙는 경우
      - 뒤에 닫는 중괄호가 하나 더 붙는 경우 (`{...}` 다음에 `}` 가 또 옴)
    이다. 두 번째는 "첫 { 부터 마지막 } 까지"를 잘라내는 방식으로는 못 고친다.
    남는 괄호까지 함께 잘라 오기 때문이다.

    그래서 앞쪽부터 '완성된 JSON 하나'만 읽고 뒤에 남은 글자는 버린다.
    없는 값을 지어내지 않으므로, 이 방식으로도 못 읽으면 실패로 두는 것이 맞다.
    """
    # 대부분은 그대로 해석된다. 이 길로 끝나는 것이 정상이다
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        # 실패했다면 앞뒤 군더더기를 걷어내고 다시 시도한다
        first = text.find("{")
        if first == -1:
            # 중괄호조차 없으면 JSON이 아니다. 채점에 쓸 수 없으므로 실패로 처리한다
            raise LLMUnavailable(
                "LLM 응답을 JSON으로 해석하지 못했다.", detail=text[:500]
            )
        try:
            # raw_decode 는 앞에서부터 완성된 값 하나만 읽고 나머지는 그냥 둔다.
            # 뒤에 붙은 여분의 괄호나 설명이 여기서 자연히 떨어져 나간다
            parsed, _ = json.JSONDecoder().raw_decode(text[first:])
        except json.JSONDecodeError as exc:
            raise LLMUnavailable(
                "LLM 응답을 JSON으로 해석하지 못했다.", detail=f"{exc} | {text[:500]}"
            ) from exc

    # 목록(list)이나 숫자가 최상위로 오면 뒤쪽 처리가 전부 어긋나므로 미리 막는다
    if not isinstance(parsed, dict):
        raise LLMUnavailable(
            "LLM 응답의 최상위가 JSON 객체가 아니다.", detail=text[:500]
        )
    return parsed


def get_default_client() -> GeminiClient:
    """기본 설정으로 만든 클라이언트를 돌려준다. 키가 없어도 객체는 만들어진다."""
    return GeminiClient()


def client_for_errors(base: GeminiClient | None = None) -> GeminiClient:
    """오류 자질 추출에만 쓸 클라이언트를 고른다.

    기본 모델(lite)이 높임법 오류를 놓치는 것이 실측으로 확인돼서,
    문법 판정만 GEMINI_MODEL_ERRORS 모델로 돌린다.

    받은 클라이언트가 GeminiClient 가 **아니면 그대로 돌려준다.**
    테스트와 데모가 넘기는 가짜 클라이언트를 모델만 바꾼 진짜 클라이언트로
    갈아 끼우면, 정해진 답을 돌려주기로 한 약속이 깨지고 실제 네트워크로 호출이 나간다.
    (상속으로 만든 가짜도 있어서 isinstance 가 아니라 정확한 종류로 확인한다)
    """
    if base is None:
        return GeminiClient(config=GeminiConfig(model=DEFAULT_ERROR_MODEL))
    if type(base) is not GeminiClient:
        return base
    return base.for_model(DEFAULT_ERROR_MODEL)
