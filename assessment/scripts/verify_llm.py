"""GEMINI_API_KEY 가 들어오면 바로 돌려서 LLM 연동을 확인하는 스크립트.

※ 지금은 키가 없어 아직 한 번도 실행해 보지 못한 상태다. ※
키를 넣은 뒤 이 스크립트를 돌려서 아래 네 가지가 되는지 확인해야 한다.

  1) Gemini 에 연결되고 JSON 으로 답이 오는가
  2) 오류 자질 4종(쓰기는 맞춤법 포함)이 실제로 추출되는가
  3) 체크리스트 0/1 판정이 되는가
  4) 일부러 넣은 '원문에 없는 답안'에 대해 인용이 폐기되는가

준비:
  1) .env.example 을 복사해 .env 를 만들고 GEMINI_API_KEY 를 채운다
  2) .venv\\Scripts\\python.exe scripts\\verify_llm.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.features.checklist import judge_checklist  # noqa: E402
from src.features.errors import extract_error_features  # noqa: E402
from src.llm.client import GeminiClient, LLMUnavailable  # noqa: E402
from src.scoring.pipeline import score_submission  # noqa: E402
from src.scoring.schema import (  # noqa: E402
    ChecklistItem,
    ItemInfo,
    Mode,
    ScoreOptions,
    ScoreRequest,
)

# 일부러 오류를 여러 개 심어 둔 답안이다.
# LLM이 이 오류들을 찾아내는지, 그리고 없는 말을 지어내지는 않는지 함께 본다.
ANSWER_WITH_ERRORS = (
    "저는 어제 회사를 갔습니다. "          # 조사 오류: '회사를' -> '회사에'
    "기계가 고장 나서 반장님이 말했습니다. "  # 높임법 오류: '반장님이 말했습니다' -> '반장님께서 말씀하셨습니다'
    "저는 기계를 고칠 수 있으요. "          # 어미 활용 오류: '있으요' -> '있어요'
    "그래서 정비팀에게 전화를 때렸습니다."     # 어휘 오용: '전화를 때리다' -> '전화를 걸다'
)

ITEM = ItemInfo(
    item_id="spk-verify-001",
    prompt="작업 중 기계가 고장 났을 때 어떻게 대처했는지 말하십시오.",
    checklist=[
        ChecklistItem(id="c1", description="고장이 난 상황을 설명했는가"),
        ChecklistItem(id="c2", description="본인이 취한 조치를 말했는가"),
        ChecklistItem(id="c3", description="사고 예방 교육을 받은 경험을 말했는가"),  # 답안에 없음 -> 0이어야 함
    ],
    reference_keywords=["고장", "조치", "예방"],
)


def section(title: str) -> None:
    print()
    print("=" * 78)
    print(title)
    print("=" * 78)


def main() -> None:
    client = GeminiClient()

    section("0. 키 확인")
    if not client.available:
        print("  GEMINI_API_KEY 가 없습니다.")
        print("  .env.example 을 복사해 .env 를 만들고 키를 채운 뒤 다시 실행하세요.")
        print("  (키 없이 도는 나머지 검증은 scripts\\check_*.py 로 확인할 수 있습니다)")
        sys.exit(2)
    print(f"  키 확인됨. 모델: {client.model_name}, temperature={client.config.temperature}")

    section("1. Gemini 연결과 JSON 응답")
    try:
        probe = client.generate_json(
            '다음 JSON 형식으로만 답하라. {"ok": true, "language": "korean"}',
            system_instruction="너는 JSON만 반환하는 도구다.",
        )
        print(f"  응답: {json.dumps(probe, ensure_ascii=False)}")
    except LLMUnavailable as exc:
        print(f"  실패: {exc}")
        sys.exit(1)

    section("2. 오류 자질 추출 (조사/어미활용/어휘오용/높임법)")
    print(f"  답안: {ANSWER_WITH_ERRORS}")
    result = extract_error_features(
        ANSWER_WITH_ERRORS, mode=Mode.SPEAKING, client=client, item_prompt=ITEM.prompt
    )
    print(f"  llm_used={result.llm_used}  버린 인용={result.dropped_citations}건")
    for f in result.features:
        if f.value is None:
            print(f"    {f.name:14s} — ({f.status.value}) {f.note}")
            continue
        print(f"    {f.name:14s} {f.value:6.2f} (100어절당)  "
              f"실제 {int(f.components.get('error_count', 0))}건")
        for ev in f.evidence:
            if ev.quote:
                print(f"        [{ev.start}:{ev.end}] '{ev.quote}' — {ev.comment[:70]}")
    for w in result.warnings:
        print(f"    경고: {w}")

    section("3. 체크리스트 0/1 판정")
    judged = judge_checklist(ANSWER_WITH_ERRORS, ITEM, client=client)
    print(f"  llm_used={judged.llm_used}  인용 폐기로 0으로 내린 항목={judged.dropped_citations}건")
    for c in judged.results:
        print(f"    [{c.met}] {c.description}")
        for ev in c.evidence:
            location = f"[{ev.start}:{ev.end}]" if ev.start is not None else "[근거 없음]"
            print(f"        {location} '{ev.quote}' — {ev.comment[:70]}")
    for w in judged.warnings:
        print(f"    경고: {w}")

    print()
    print("  * c3(사고 예방 교육)은 답안에 없는 내용이므로 0이어야 정상이다.")
    print("    1로 나왔다면 LLM이 근거를 지어냈거나 인용 검증이 새고 있다는 뜻이다.")

    section("4. 파이프라인 전체 (LLM 포함 실제 채점)")
    request = ScoreRequest(
        submission_id="verify-001",
        mode=Mode.SPEAKING,
        answer_text=ANSWER_WITH_ERRORS,
        item=ITEM,
        options=ScoreOptions(use_llm=True),
    )
    response = score_submission(request, client=client)
    print(f"  종합 점수 {response.overall_score} / 등급 {response.overall_grade}")
    for s in response.subscores:
        score_text = "채점 안 함" if s.score is None else f"{s.score:.2f}"
        print(f"    {s.label:12s} {score_text:>10s}  상태 {s.status.value}")
    print(f"  meta: llm_used={response.meta.llm_used} "
          f"model={response.meta.llm_model} "
          f"버린 인용={response.meta.dropped_citations}건 "
          f"소요={response.meta.timings_ms}")

    section("확인 결과")
    checks = [
        ("Gemini 연결 및 JSON 응답", True),
        ("오류 자질이 LLM으로 계산됨", result.llm_used),
        ("체크리스트가 LLM으로 판정됨", judged.llm_used),
        ("답안에 없는 항목(c3)이 미충족으로 나옴",
         any(c.id == "c3" and c.met == 0 for c in judged.results)),
        ("파이프라인 종합 점수 산출", response.overall_score is not None),
    ]
    failed = 0
    for desc, ok in checks:
        print(f"  [{'OK ' if ok else 'NG '}] {desc}")
        if not ok:
            failed += 1
    print()
    if failed:
        print(f"확인 실패 {failed}건.")
        sys.exit(1)
    print("LLM 연동 확인 전부 통과.")


if __name__ == "__main__":
    main()
