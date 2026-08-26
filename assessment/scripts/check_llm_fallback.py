"""원 모델이 붐빌 때(503) 대체 모델로 갈아타는 동작을 눈으로 확인하는 스크립트.

LLM API 키 없이 돌아간다. 진짜 Gemini 대신 '정해진 대로 실패하는 가짜 서버'를 붙여서
어느 모델을 몇 번 불렀고, 결과에 누가 답했다고 적히는지를 그대로 찍어 본다.

확인하려는 것:
  1) 503(지금 사람이 몰렸다)이면 대체 모델로 한 번 더 부르는가
  2) 429(사용량 초과)처럼 모델을 바꿔도 소용없는 실패에는 안 갈아타는가
  3) 갈아탄 사실이 채점 결과(meta.llm_model_errors · warnings · notices)까지 도달하는가

실행: .venv\\Scripts\\python.exe scripts\\check_llm_fallback.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import src.scoring.pipeline as pipeline  # noqa: E402
from src.llm.client import GeminiClient, GeminiConfig, LLMUnavailable  # noqa: E402
from src.scoring.schema import ChecklistItem, ItemInfo, Mode, ScoreRequest  # noqa: E402

주모델 = "gemini-3-flash-preview"
대체모델 = "gemini-3.1-flash-lite"

# GCP 로그에 실제로 찍혔던 문구를 줄여서 옮긴 것
BODY_503 = (
    "503 UNAVAILABLE. {'error': {'code': 503, "
    "'message': 'This model is currently experiencing high demand', "
    "'status': 'UNAVAILABLE'}}"
)
BODY_429 = (
    "429 RESOURCE_EXHAUSTED. {'error': {'code': 429, "
    "'message': 'You exceeded your current quota', 'status': 'RESOURCE_EXHAUSTED'}}"
)


class 가짜서버:
    """정해 둔 모델만 실패시키고 나머지는 정해진 JSON 을 돌려주는 가짜 Gemini."""

    def __init__(self, 실패시킬모델: dict[str, str], 답: dict):
        self._실패 = 실패시킬모델
        self._답 = 답
        self.calls: list[str] = []

    def generate_content(self, model, contents, config):
        # 어느 모델을 불렀는지 순서대로 적어 둔다(아래에서 이 목록을 찍는다)
        self.calls.append(model)
        body = self._실패.get(model)
        if body is not None:
            raise RuntimeError(body)
        return type(
            "R", (), {"text": json.dumps(self._답), "candidates": []}
        )()


def 클라이언트(실패시킬모델: dict[str, str], 답: dict, model: str = 주모델):
    """가짜 서버를 끼운 클라이언트를 만든다(네트워크로 나가지 않는다)."""
    client = GeminiClient(
        api_key="dummy",
        config=GeminiConfig(model=model, fallback_model=대체모델),
    )
    서버 = 가짜서버(실패시킬모델, 답)
    client._client = type("FakeGenai", (), {"models": 서버})()
    return client, 서버


def 한줄(제목: str) -> None:
    print()
    print("=" * 70)
    print(제목)
    print("=" * 70)


# ---------------------------------------------------------------------------
# 1) 503 이면 갈아탄다 / 429 면 안 갈아탄다
# ---------------------------------------------------------------------------

한줄("1. 실패 종류에 따라 갈아타는지")

for 설명, body in [("503 (지금 못 받는다)", BODY_503), ("429 (사용량 초과)", BODY_429)]:
    client, 서버 = 클라이언트({주모델: body}, {"errors": []})
    try:
        client.generate_json("아무 지시문")
        결과 = "성공"
    except LLMUnavailable as exc:
        결과 = f"실패({exc.code})"
    print(f"  {설명:22s} -> {결과:28s} 부른 모델: {서버.calls}")
    print(f"  {'':22s}    실제로 답한 모델: {client.last_model_used} "
          f"/ 갈아타기 전: {client.last_fallback_from}")

# ---------------------------------------------------------------------------
# 2) 대체까지 실패하면 원래 오류 코드로 끝난다
# ---------------------------------------------------------------------------

한줄("2. 대체 모델까지 못 받을 때")

client, 서버 = 클라이언트({주모델: BODY_503, 대체모델: BODY_503}, {"errors": []})
try:
    client.generate_json("아무 지시문")
except LLMUnavailable as exc:
    print(f"  코드            : {exc.code}")
    print(f"  응시자에게 갈 문구: {exc}")
    print(f"  개발자용 detail : {exc.detail[:120]}...")
    print(f"  부른 모델       : {서버.calls}")

# ---------------------------------------------------------------------------
# 3) 채점 결과까지 도달하는지
# ---------------------------------------------------------------------------

한줄("3. 채점 한 건에 갈아탄 사실이 남는지")

기본, _ = 클라이언트({}, {"judgements": []}, model=대체모델)
오류판정, 오류서버 = 클라이언트({주모델: BODY_503}, {"errors": []})

# client_for_errors 는 진짜 클라이언트를 받으면 모델만 바꾼 새것을 만들어 버린다.
# 그러면 가짜 서버가 떨어져 나가므로, 이 확인 동안만 우리 가짜를 그대로 쓰게 한다
원래함수 = pipeline.client_for_errors
pipeline.client_for_errors = lambda base: 오류판정
try:
    응답 = pipeline.score_submission(
        ScoreRequest(
            submission_id="check-1",
            mode=Mode.SPEAKING,
            answer_text=(
                "반장님 지금 삼번 라인 포장 기계가 갑자기 멈췄습니다. "
                "제가 전원을 차단하고 정비팀에 연락할까요?"
            ),
            item=ItemInfo(
                item_id="item-1",
                prompt="기계 고장을 반장님에게 보고하세요.",
                checklist=[ChecklistItem(id="c1", description="고장 사실을 말했는가")],
            ),
        ),
        client=기본,
    )
finally:
    pipeline.client_for_errors = 원래함수

print(f"  오류 판정이 부른 모델   : {오류서버.calls}")
print(f"  meta.llm_model          : {응답.meta.llm_model}")
print(f"  meta.llm_model_errors   : {응답.meta.llm_model_errors}  <- 실제로 답한 모델")
print(f"  warnings/notices 길이   : {len(응답.warnings)} / {len(응답.notices)} (같아야 한다)")
for w, n in zip(응답.warnings, 응답.notices):
    if n.code == "LLM_FALLBACK_MODEL_USED":
        print(f"  대체 안내 코드          : {n.code}")
        print(f"  대체 안내 params        : {n.params}")
        print(f"  대체 안내 한국어 문장   : {w}")

print()
print("확인 끝. 위 값이 설명과 다르면 대체 경로가 깨진 것이다.")
