"""문항 생성에 쓸 LLM 클라이언트를 고르는 자리.

**왜 이 파일이 llm/client.py 가 아니라 여기 있는가 (설계와 다른 점).**
설계 문서는 이 함수를 `src/llm/client.py` 에 얹으라고 했지만,
이번 작업의 상위 제약은 "채점 파이프라인(src/scoring, src/features, src/llm)을
한 줄도 건드리지 않는다"였다. 그 제약이 지켜졌다는 것을 `git diff` 로 증명해야 해서
생성 전용 설정은 생성 패키지 안에 둔다.
기존 파일은 읽기만 하고 고치지 않으므로 채점 결과는 이 기능과 무관하게 그대로다.

모델을 갈아 끼울 때 고칠 곳은 이 파일 하나다(.env 의 GEMINI_MODEL_GENERATION).
"""

from __future__ import annotations

import os

from ..llm.client import GeminiClient, GeminiConfig

#: 생성에 쓰는 모델.
#: 실제 KOSHA 문서로 통과를 확인한 모델이다.
#: lite 계열은 생성에서 검증해 본 적이 없으므로 기본값으로 쓰지 않는다.
DEFAULT_GENERATION_MODEL = os.getenv("GEMINI_MODEL_GENERATION", "gemini-3-flash-preview")

#: 응답 길이 상한. 문항 수가 늘면 응답도 길어지므로 문항당 몫을 더한다.
#: **아직 실측으로 확인한 값이 아니라 추정값이다.** 응답이 잘리면 이 값을 올린다.
BASE_OUTPUT_TOKENS = 4096
OUTPUT_TOKENS_PER_ITEM = 2048

#: 기다려 줄 시간. 채점(60초)보다 길게 잡는다.
#: 문서 전문을 읽고 문항 여러 개를 쓰는 일이라 채점 한 건보다 오래 걸린다.
GENERATION_TIMEOUT_MS = 120_000


def generation_config(item_count: int = 3) -> GeminiConfig:
    """생성 호출에 쓸 설정을 만든다. temperature 는 0 그대로 둔다."""
    return GeminiConfig(
        model=DEFAULT_GENERATION_MODEL,
        temperature=0.0,
        max_output_tokens=BASE_OUTPUT_TOKENS + OUTPUT_TOKENS_PER_ITEM * item_count,
        timeout_ms=GENERATION_TIMEOUT_MS,
    )


def client_for_generation(
    base: GeminiClient | None = None, item_count: int = 3
) -> GeminiClient:
    """문항 생성에만 쓸 클라이언트를 고른다.

    받은 클라이언트가 GeminiClient 가 **아니면 그대로 돌려준다.**
    테스트와 데모가 넘기는 가짜 클라이언트를 진짜 클라이언트로 갈아 끼우면
    정해진 답을 돌려주기로 한 약속이 깨지고 실제 네트워크로 호출이 나간다.
    (상속으로 만든 가짜도 있어서 isinstance 가 아니라 정확한 종류로 확인한다 —
     채점 쪽 client_for_errors 와 같은 방식이다)
    """
    # 가짜 클라이언트는 손대지 않고 그대로 쓴다
    if base is not None and type(base) is not GeminiClient:
        return base
    # 진짜 클라이언트는 생성 전용 설정으로 새로 만든다(키는 환경변수에서 읽는다)
    return GeminiClient(config=generation_config(item_count))
