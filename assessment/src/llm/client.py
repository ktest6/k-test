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
import threading
from dataclasses import dataclass, replace
from typing import Any

from dotenv import load_dotenv

from ..scoring.messages import Notice, notice

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

# 원래 쓰려던 모델이 "지금 사람이 몰려서 못 받는다"(503 UNAVAILABLE)고 할 때
# 대신 물어볼 모델.
#
# 왜 필요한가 (2026-08-26 GCP 실측):
# 오류 판정 모델(gemini-3-flash-preview)이 503 을 내면서 한 건에 55~113초가 걸렸다.
# 정상일 때는 4~7초다. 응시자는 그동안 아무 답도 못 받고 기다리다가 결국
# '오류 자질 없음'으로 채점된다. 같은 순간에도 lite 모델은 멀쩡히 답했다.
# 그래서 붐비는 모델 하나 때문에 채점이 통째로 비는 일이 없도록 갈아탈 자리를 둔다.
#
# **google-genai SDK 는 이 상황에서 스스로 재시도하지 않는다** (2026-08-26 확인).
# SDK 2.14.0 의 `_api_client.retry_args()` 는 `HttpOptions.retry_options` 가
# 비어 있으면 `stop_after_attempt(1)`, 즉 '한 번 부르고 끝'을 쓴다.
# 우리는 retry_options 를 준 적이 없으므로 55~113초는 SDK 가 여러 번 부른 시간이 아니라
# **한 번의 호출이 그만큼 오래 매달려 있던 시간**이다.
# (retry_options 를 켜면 기본 5회·1초부터 배로 늘어나는 대기가 붙어서 오히려 더 오래 걸린다.
#  그래서 SDK 재시도는 계속 끈 채로 두고, 우리가 모델을 갈아타는 쪽을 택했다.)
#
# 바꾸려면 코드가 아니라 .env 의 GEMINI_MODEL_FALLBACK 을 고친다.
# 원래 모델과 같은 이름을 적으면 갈아탈 곳이 없으므로 대체하지 않는다.
DEFAULT_FALLBACK_MODEL = os.getenv("GEMINI_MODEL_FALLBACK", "gemini-3.1-flash-lite")

# 어떤 실패일 때 대체 모델로 갈아탈지. '남의 서버가 지금 못 받는다'는 경우 하나뿐이다.
# 사용량 초과(429)나 키 오류(403)는 모델을 바꿔도 똑같이 실패하므로 갈아타지 않는다
# (429 는 모델마다 한도가 따로지만, 바꿔 부르면 그쪽 한도까지 태워 버리게 되므로 뺐다).
FALLBACK_TRIGGER_CODES: frozenset[str] = frozenset({"LLM_SERVER_ERROR"})


class LLMUnavailable(RuntimeError):
    """API 키가 없거나 호출에 실패해서 LLM을 쓸 수 없을 때 올리는 예외.

    이 예외가 나면 파이프라인은 멈추지 않고, 규칙 자질만으로 채점하는
    임시 대체 경로로 넘어간다(그 사실은 응답의 warnings 에 남는다).

    이 예외의 메시지는 **채점 결과에 그대로 실린다.**
    warnings 와 영역별 note 는 백엔드가 받아 응시자에게 보여줄 수 있는 자리라서,
    여기에는 사람이 읽을 짧은 한 문장만 담는다.
    서버가 돌려준 원문(JSON 덩어리)은 detail 에 따로 담고 로그로만 내보낸다.

    **문구 말고 코드도 함께 들고 다닌다.** 응시자 화면에는 영어가 떠야 하는데 우리가
    만드는 문장은 한국어라서, 백엔드가 영어 문장을 고를 열쇠(`code`)와 그 문장에 끼울
    값(`params`)을 예외에 같이 담는다.
    `code` 는 안 줘도 되게 해 두어서, 옛날 방식으로 부르던 자리도 그대로 돈다.
    """

    def __init__(
        self,
        message: str,
        detail: str = "",
        code: str = "",
        params: dict | None = None,
    ):
        super().__init__(message)
        # 개발자가 원인을 찾을 때 쓰는 자리. 채점 결과에는 실리지 않는다
        self.detail = detail
        #: 백엔드가 영어 문구를 찾을 열쇠 (예: "LLM_QUOTA_EXHAUSTED")
        self.code = code
        #: 그 문구에 끼워 넣을 값
        self.params = dict(params or {})

    @property
    def notice(self) -> Notice:
        """이 예외를 백엔드에 나갈 모양(코드 + 값 + 한국어 문장)으로 바꾼다."""
        return Notice(code=self.code, params=self.params, message=str(self))

    @classmethod
    def of(cls, code: str, *, detail: str = "", **params) -> "LLMUnavailable":
        """코드 하나로 예외를 만든다. 한국어 문장은 카탈로그가 만들어 준다."""
        made = notice(code, **params)
        return cls(made.message, detail=detail, code=made.code, params=made.params)


# 호출이 실패하는 이유는 여러 가지지만, 결과를 읽는 사람에게 필요한 것은
# "무슨 일이 있었고 내가 무엇을 하면 되는가" 한 줄이다.
# (서버 응답에서 찾을 표시, 사람이 읽을 문구) 짝으로 적어 둔다.
_FAILURE_PATTERNS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("RESOURCE_EXHAUSTED", "429", "quota"), "LLM_QUOTA_EXHAUSTED"),
    (("NOT_FOUND", "404"), "LLM_MODEL_NOT_FOUND"),
    (("PERMISSION_DENIED", "403", "API_KEY_INVALID", "API key not valid"),
     "LLM_PERMISSION_DENIED"),
    (("UNAUTHENTICATED", "401"), "LLM_UNAUTHENTICATED"),
    (("DEADLINE_EXCEEDED", "timeout", "Timeout", "timed out"), "LLM_TIMEOUT"),
    (("UNAVAILABLE", "503", "500", "INTERNAL"), "LLM_SERVER_ERROR"),
    (("ConnectionError", "Connection", "getaddrinfo", "Network"), "LLM_CONNECTION_FAILED"),
)


def classify_failure_notice(exc: Exception) -> Notice:
    """호출 실패의 원인을 '코드 + 한국어 한 문장' 으로 바꾼다.

    분류를 이 함수 한 곳에서만 하는 이유:
    같은 판별을 여러 파일에 흩어 놓으면 새로운 오류 유형이 생겼을 때
    어떤 곳은 고쳐지고 어떤 곳은 안 고쳐져서 문구가 제각각이 된다.
    """
    text = str(exc)
    # 서버 응답에서 알아볼 만한 표시를 찾아 미리 정해 둔 코드로 바꾼다
    for markers, code in _FAILURE_PATTERNS:
        if any(marker in text for marker in markers):
            return notice(code)
    # 어디에도 해당하지 않으면 예외 종류만 밝힌다.
    # 서버 응답 원문을 여기에 붙이면 안 된다(채점 결과에 그대로 실린다)
    return notice("LLM_CALL_FAILED", excType=type(exc).__name__)


def classify_failure(exc: Exception) -> str:
    """호출 실패의 원인을 사람이 읽을 한 문장으로 바꾼다(코드는 버리고 문장만)."""
    return classify_failure_notice(exc).message


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
    # 원 모델이 503(지금 못 받는다)을 낼 때 대신 물어볼 모델.
    # None 이거나 위 model 과 같은 이름이면 갈아타지 않고 지금까지처럼 그대로 실패한다.
    fallback_model: str | None = DEFAULT_FALLBACK_MODEL


@dataclass
class _CallState:
    """generate_json 한 번이 도는 동안 '지금 어느 모델로 부르고 있는지'를 들고 다니는 쪽지.

    호출 한 번 안에서 모델이 바뀔 수 있어서(503 이면 대체 모델로 갈아탄다) 필요하다.
    클라이언트 자체에 적어 두지 않는 이유: 같은 클라이언트를 여러 스레드가 동시에 쓰므로
    호출별로 따로 들고 다니는 쪽지여야 서로 값을 덮어쓰지 않는다.
    """

    #: 지금 부르고 있는 모델
    model: str
    #: 갈아탄 것이라면 원래 부르려던 모델(안 갈아탔으면 None)
    fallback_from: str | None = None
    #: 이번 호출에서 이미 갈아탔는지(두 번은 갈아타지 않는다)
    fallback_used: bool = False


class GeminiClient:
    """Gemini 를 JSON 모드로만 호출하는 클라이언트."""

    def __init__(self, api_key: str | None = None, config: GeminiConfig | None = None):
        self.config = config or GeminiConfig()
        # 키는 직접 넘겨줄 수도 있지만, 평소에는 환경변수에서 읽는다
        # 코드 어디에도 키를 적어 두지 않기 위해서다
        self._api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        # 실제 접속 객체는 처음 쓸 때 만든다(키가 없으면 끝까지 안 만들어도 된다)
        self._client = None
        # 마지막 호출에서 '실제로 답한 모델'을 적어 두는 자리.
        # 스레드마다 따로 적는 이유: 채점은 오류 판정과 체크리스트 판정을 동시에 보내는데,
        # 한 곳에 적으면 나중에 끝난 쪽이 앞쪽 기록을 덮어써서 엉뚱한 모델 이름이 결과에 실린다
        self._last_call = threading.local()

    @property
    def available(self) -> bool:
        """키가 있어서 호출을 시도할 수 있는 상태인지."""
        return bool(self._api_key)

    @property
    def model_name(self) -> str:
        """부르려고 정해 둔 모델 이름(실제로 답한 모델이 아니다)."""
        return self.config.model

    @property
    def fallback_model(self) -> str | None:
        """원 모델이 못 받을 때 대신 부르기로 설정해 둔 모델 이름.

        설정값을 그대로 돌려준다(상태 확인용). 이 이름이 지금 모델과 같으면
        갈아탈 곳이 없다는 뜻이고, 그때 실제로 쓰이는 값은 None 이다
        (실제로 갈아탈 이름을 고르는 것은 `_effective_fallback`).
        """
        return self.config.fallback_model

    @property
    def last_model_used(self) -> str | None:
        """이 스레드에서 **마지막으로 성공한 호출에 실제로 답한 모델** 이름.

        채점 결과에 "어떤 모델이 이 판정을 했는가"를 적으려면 부르려던 이름이 아니라
        답한 이름이 필요하다. 503 때문에 대체 모델로 갈아탔는데 결과에는 원 모델이
        적혀 있으면, 나중에 같은 답안을 다시 채점했을 때 값이 왜 다른지 설명할 수 없다.

        호출이 실패했거나 아직 한 번도 안 불렀으면 None 이다.
        """
        return getattr(self._last_call, "model", None)

    @property
    def last_fallback_from(self) -> str | None:
        """마지막 성공한 호출이 대체 모델로 갈아탄 것이라면, 원래 부르려던 모델 이름.

        갈아타지 않았으면 None 이다. 호출한 쪽은 이 값이 있는지만 보고
        "대체가 실제로 쓰였다"를 판단하면 된다.
        """
        return getattr(self._last_call, "fallback_from", None)

    def _effective_fallback(self) -> str | None:
        """이번 설정에서 실제로 갈아탈 수 있는 모델 이름을 고른다.

        설정이 비었거나 원 모델과 같은 이름이면 갈아탈 곳이 없는 것이라 None 이다.
        """
        candidate = (self.config.fallback_model or "").strip()
        if not candidate or candidate == self.config.model:
            return None
        return candidate

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
            raise LLMUnavailable.of("LLM_API_KEY_MISSING")

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
        model: str | None = None,
    ):
        """실제로 한 번 부르는 자리. 예산·모델만 바꿔 다시 부를 수 있도록 떼어 두었다."""
        from google.genai import types

        # 부를 모델. 따로 지정하지 않으면 설정에 적힌 기본 모델이다
        # (대체 모델로 갈아탈 때만 다른 이름이 들어온다)
        called_model = model or self.config.model

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
                model=called_model,
                contents=prompt,
                config=config,
            )
        except Exception as exc:
            # 네트워크 끊김, 키 오류, 사용량 초과 등 실패 이유는 여러 가지지만
            # 파이프라인 입장에서는 "LLM을 못 썼다"는 하나의 상황이므로 한 갈래로 모은다.
            # 서버가 준 원문은 로그로만 남기고, 채점 결과에는 짧은 사유만 올린다.
            # 사유는 문장뿐 아니라 코드(LLM_SERVER_ERROR 등)까지 함께 들려 보낸다 —
            # 위쪽에서 "이 실패는 모델을 갈아타면 될 실패인가"를 그 코드로 판단한다
            made = classify_failure_notice(exc)
            logger.warning("Gemini 호출 실패 [%s]: %s", called_model, exc)
            raise LLMUnavailable(
                made.message, detail=str(exc), code=made.code, params=made.params
            ) from exc

    def _call_with_fallback(
        self,
        client,
        state: "_CallState",
        prompt: str,
        system_instruction: str,
        response_schema: Any | None,
        max_output_tokens: int,
    ):
        """한 번 부르고, 503(지금 못 받는다)이면 대체 모델로 **딱 한 번만** 다시 부른다.

        갈아타는 조건을 좁게 잡은 이유:
        사용량 초과나 키 오류는 모델을 바꿔도 똑같이 실패하므로 두 번 부르는 만큼
        응시자를 더 기다리게 할 뿐이다. '남의 서버가 지금 붐빈다'일 때만 갈아탄다.

        한 번만 갈아타는 이유:
        대체 모델까지 못 받는 상황이면 더 부르는 것은 시간 낭비이고, 그때는
        규칙 자질만으로 채점하는 기존 대체 경로로 넘어가는 편이 응시자에게 빠르다.
        """
        try:
            return self._call_once(
                client, prompt, system_instruction, response_schema,
                max_output_tokens, model=state.model,
            )
        except LLMUnavailable as first_failure:
            fallback = self._effective_fallback()
            # 갈아탈 곳이 없거나(설정 없음·같은 모델), 갈아타도 소용없는 실패거나,
            # 이번 호출에서 이미 한 번 갈아탔으면 그대로 실패를 올린다
            if (
                fallback is None
                or state.fallback_used
                or first_failure.code not in FALLBACK_TRIGGER_CODES
            ):
                raise

            logger.warning(
                "Gemini 가 응답하지 못해 대체 모델로 다시 부른다: %s -> %s (%s)",
                state.model, fallback, first_failure.code,
            )
            original_model = state.model
            state.model = fallback
            state.fallback_from = original_model
            state.fallback_used = True

            try:
                return self._call_once(
                    client, prompt, system_instruction, response_schema,
                    max_output_tokens, model=fallback,
                )
            except LLMUnavailable as second_failure:
                # 대체까지 실패하면 지금까지와 똑같이 실패로 끝낸다.
                # 이때 결과에 실리는 사유는 **원래 실패의 코드와 문장** 그대로다.
                # 채점 결과를 읽는 사람에게 필요한 것은 '무엇이 안 됐나'이지
                # 우리가 몇 번 시도했는가가 아니기 때문이다(시도 내역은 detail 과 로그로 남긴다)
                raise LLMUnavailable(
                    str(first_failure),
                    detail=(
                        f"{first_failure.detail} | 대체 모델({fallback}) 도 실패: "
                        f"{second_failure.detail or second_failure}"
                    ),
                    code=first_failure.code,
                    params=first_failure.params,
                ) from second_failure

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

        원 모델이 503(지금 붐벼서 못 받는다)을 내면 대체 모델로 한 번 갈아탄다.
        실제로 답한 모델 이름은 `last_model_used` 에서 확인할 수 있다.
        """
        # 접속 준비. 키가 없으면 여기서 LLMUnavailable 이 나고 호출은 시도조차 하지 않는다
        client = self._ensure_client()

        # 지난 호출의 기록이 남아 있으면, 이번에 실패했을 때 옛날 모델 이름이
        # 이번 결과에 실려 나간다. 시작할 때 지워 둔다
        self._forget_last_call()

        # 이번 호출 동안 어느 모델로 부르고 있는지 들고 다닐 쪽지
        state = _CallState(model=self.config.model)

        response = self._call_with_fallback(
            client, state, prompt, system_instruction, response_schema,
            self.config.max_output_tokens,
        )

        # 답이 끝까지 나오지 못하고 잘렸는지 본다.
        # 잘린 답은 거의 항상 JSON 이 깨져 있어서, 그대로 두면 자질이 통째로 사라진다
        if _is_truncated(response):
            multiplier = max(1, int(self.config.retry_budget_multiplier))
            bigger = self.config.max_output_tokens * multiplier
            if multiplier <= 1:
                # 다시 부르지 않기로 설정된 경우. 무슨 일이 있었는지는 분명히 남긴다
                raise LLMUnavailable.of(
                    "LLM_RESPONSE_TRUNCATED",
                    detail=f"max_output_tokens={self.config.max_output_tokens}, 재시도 꺼짐",
                )
            logger.warning(
                "Gemini 답이 잘려 예산을 키워 다시 부른다 [%s]: %d -> %d",
                state.model, self.config.max_output_tokens, bigger,
            )
            response = self._call_with_fallback(
                client, state, prompt, system_instruction, response_schema, bigger
            )
            # 예산을 두 배로 줬는데도 잘렸다면 이 답안은 이 설정으로 감당이 안 되는 것이다.
            # 반쪽짜리 결과를 지어내지 않고 실패로 두고, 사유를 그대로 밝힌다
            if _is_truncated(response):
                raise LLMUnavailable.of(
                    "LLM_RESPONSE_TRUNCATED_RETRIED",
                    detail=f"max_output_tokens={self.config.max_output_tokens} -> {bigger}",
                )

        # 안전 필터에 걸리거나 답을 못 만들면 빈 응답이 온다. 이것도 실패로 다룬다
        text = (response.text or "").strip()
        if not text:
            raise LLMUnavailable.of("LLM_EMPTY_RESPONSE")

        parsed = _parse_json_object(text)

        # 여기까지 왔으면 답을 제대로 받아 읽은 것이다.
        # 이 자리에서만 '누가 답했는지'를 적어 둔다(실패한 호출은 남기지 않는다)
        self._remember_last_call(state)
        return parsed

    def _remember_last_call(self, state: "_CallState") -> None:
        """방금 성공한 호출에 실제로 답한 모델을 이 스레드의 기록에 적는다."""
        self._last_call.model = state.model
        self._last_call.fallback_from = state.fallback_from

    def _forget_last_call(self) -> None:
        """이 스레드의 지난 호출 기록을 지운다(호출을 시작할 때 부른다)."""
        self._last_call.model = None
        self._last_call.fallback_from = None


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
            raise LLMUnavailable.of("LLM_JSON_PARSE_FAILED", detail=text[:500])
        try:
            # raw_decode 는 앞에서부터 완성된 값 하나만 읽고 나머지는 그냥 둔다.
            # 뒤에 붙은 여분의 괄호나 설명이 여기서 자연히 떨어져 나간다
            parsed, _ = json.JSONDecoder().raw_decode(text[first:])
        except json.JSONDecodeError as exc:
            raise LLMUnavailable.of(
                "LLM_JSON_PARSE_FAILED", detail=f"{exc} | {text[:500]}"
            ) from exc

    # 목록(list)이나 숫자가 최상위로 오면 뒤쪽 처리가 전부 어긋나므로 미리 막는다
    if not isinstance(parsed, dict):
        raise LLMUnavailable.of("LLM_JSON_NOT_OBJECT", detail=text[:500])
    return parsed


def answered_model(client: Any) -> tuple[str | None, str | None]:
    """방금 그 클라이언트에 **실제로 답한 모델**과, 갈아탄 것이라면 원래 모델을 돌려준다.

    돌려주는 값은 (실제로 답한 모델, 갈아타기 전 모델) 두 개다.
    갈아타지 않았으면 두 번째가 None 이다.

    왜 함수로 빼는가:
    이 값을 읽는 자리가 세 군데(오류 판정·체크리스트 판정·전사 보정)인데,
    테스트와 데모가 넘기는 **가짜 클라이언트에는 이 기록이 아예 없다.**
    그래서 "없으면 부르려던 이름을 쓴다"는 규칙이 필요한데, 그것을 세 군데에
    각각 적어 두면 한 곳만 고쳐지는 일이 생긴다. 한 곳으로 모아 둔다.
    """
    # 기록이 있으면 그것이 정답이다. 없으면(가짜 클라이언트) 부르려던 이름으로 대신한다
    used = getattr(client, "last_model_used", None) or getattr(client, "model_name", None)
    return used, getattr(client, "last_fallback_from", None)


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
