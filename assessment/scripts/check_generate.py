"""안전문서로 실제 문항을 만들어 사람이 눈으로 확인하는 스크립트.

**이 스크립트는 진짜 LLM 을 부른다.** (.env 의 GEMINI_API_KEY 가 필요하다)

확인하려는 것 네 가지:
  1. 실제 안전문서에서 우리 형식의 쓰기 문항이 나오는가
  2. 근거를 대지 못한 문항이 정말로 버려지는가 (폐기율)
  3. 같은 문서로 여러 번 만들면 무엇이 같고 무엇이 다른가
     — 문구는 달라도 **관문 통과 여부와 폐기율**은 봐야 할 값이다
  4. 한 번 만드는 데 시간과 토큰이 얼마나 드는가

실행:
    .venv\\Scripts\\python.exe scripts\\check_generate.py --pdf 문서.pdf --pages 4-16
    .venv\\Scripts\\python.exe scripts\\check_generate.py --file 문서.txt --runs 3
    .venv\\Scripts\\python.exe scripts\\check_generate.py          (붙어 있는 표본 문서로 실행)
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.generation.generate import GenerationRequestError, generate_items  # noqa: E402
from src.generation.llm import DEFAULT_GENERATION_MODEL, generation_config  # noqa: E402
from src.generation.preprocess import preprocess_document  # noqa: E402
from src.generation.prompt import (  # noqa: E402
    PROMPT_VERSION,
    RESPONSE_SCHEMA,
    SYSTEM_INSTRUCTION,
    build_user_prompt,
)
from src.generation.schema import GenerateItemsRequest, GenerateOptions  # noqa: E402
from src.llm.client import LLMUnavailable  # noqa: E402

# 문서를 따로 주지 않았을 때 쓰는 표본. 실제 KOSHA 자료를 바탕으로 만든 가상 공장 문서다.
# 가상 공장이라 기밀·저작권 걱정 없이 시연에 쓸 수 있다.
SAMPLE_DOCUMENT = """\
(주)K-테스트 식품공장 안전보건 수칙 (2026년 개정판)

제1장 총칙
이 수칙은 식품 제조 공정에서 일하는 모든 근로자의 안전과 건강을 지키기 위한 것이다.
사업장 안에서 일하는 사람은 국적과 고용 형태에 관계없이 이 수칙을 지켜야 한다.

제2장 작업 시작 전 점검
작업을 시작하기 전에 안전모와 안전화를 반드시 착용한다.
회전하는 기계 옆에서는 장갑이 말려 들어갈 수 있으므로 면장갑을 끼지 않는다.
기계의 비상정지 버튼이 눌리는지 매일 아침 확인하고 점검표에 적는다.
바닥에 기름이나 물이 흘러 있으면 미끄러질 수 있으므로 즉시 닦아 낸다.
점검 중에 이상을 발견하면 기계를 켜지 말고 정비 담당자에게 먼저 연락한다.

제3장 지게차와 통로
지게차가 다니는 통로에서는 보행자가 바닥의 노란 선 안쪽으로 걷는다.
지게차 운전자는 후진할 때 반드시 경적을 울리고 뒤를 확인한다.
짐을 쌓는 높이는 1.8미터를 넘기지 않으며 시야를 가리면 안 된다.
작업이 끝나면 지게차 열쇠를 빼서 사무실에 반납한다.

제4장 위험을 발견했을 때
선반이 한쪽으로 기울어져 있으면 물건을 내리기 전에 안전관리자에게 알린다.
전선의 피복이 벗겨진 곳을 보면 손대지 말고 전기 담당자에게 연락한다.
소화기는 한 달에 한 번 압력계 바늘이 초록색 칸에 있는지 확인한다.
화재가 나면 먼저 큰 소리로 알리고 비상구를 통해 밖으로 대피한다.
다친 사람이 있으면 무리하게 옮기지 말고 즉시 구급차를 부른다.

제5장 화학물질 취급
세척용 약품은 반드시 원래 용기에 담아 이름표를 붙여 보관한다.
약품을 다룰 때에는 보호 장갑과 보안경을 착용하고 환기를 시킨다.
약품이 피부에 닿으면 흐르는 물로 15분 이상 씻어 내고 보건 담당자에게 알린다.
서로 다른 약품을 섞으면 유독 가스가 생길 수 있으므로 절대 섞지 않는다.

제6장 교대 근무와 인수인계
근무를 마칠 때에는 다음 근무자에게 남은 작업과 주의할 점을 알려 준다.
고장 난 설비가 있으면 어디가 어떻게 고장 났는지 인수인계 노트에 적어 둔다.
청소용 세제와 소모품은 창고 2층 선반에 보관하고 다 쓰면 사무실에 요청한다.
작업 중에 일어난 일은 그날 안에 작업일지에 기록한다.
"""


def load_document(args) -> tuple[str, str]:
    """어떤 문서로 시험해 볼지 정한다. (문서 글, 제목)을 돌려준다."""
    # PDF 를 주면 폴백 추출기로 글자를 뽑는다
    if args.pdf:
        from extract_pdf import extract

        path = Path(args.pdf)
        if not path.exists():
            raise SystemExit(f"파일을 찾을 수 없습니다: {path}")
        return extract(path, args.pages), path.stem

    # 텍스트 파일을 주면 그대로 읽는다
    if args.file:
        path = Path(args.file)
        if not path.exists():
            raise SystemExit(f"파일을 찾을 수 없습니다: {path}")
        return path.read_text(encoding="utf-8"), path.stem

    # 아무것도 안 주면 붙어 있는 표본으로 돈다
    print("※ 문서를 지정하지 않아 붙어 있는 표본 문서(가상 공장)로 실행합니다.")
    return SAMPLE_DOCUMENT, "(주)K-테스트 식품공장 안전보건 수칙"


def measure_tokens(document: str, item_count: int, title: str) -> dict | None:
    """토큰이 얼마나 드는지 재려고 한 번 더 부른다.

    채점 쪽 클라이언트는 사용량 정보를 돌려주지 않게 만들어져 있어서
    (채점 결과에 필요 없는 값이라 버린다) 여기서만 원래 라이브러리를 직접 부른다.
    **비용을 재기 위한 별도 호출이며 문항 생성에는 쓰이지 않는다.**
    """
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        return None
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        return None

    config = generation_config(item_count)
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=config.model,
        contents=build_user_prompt(
            document=document, item_count=item_count, document_title=title
        ),
        config=types.GenerateContentConfig(
            temperature=config.temperature,
            max_output_tokens=config.max_output_tokens,
            response_mime_type="application/json",
            system_instruction=SYSTEM_INSTRUCTION,
            response_schema=RESPONSE_SCHEMA,
            http_options=types.HttpOptions(timeout=config.timeout_ms),
        ),
    )
    usage = response.usage_metadata
    # 생각 토큰(thoughts)을 따로 뽑는 이유:
    # 이 모델은 답을 내기 전에 속으로 생각한 만큼도 요금을 매긴다.
    # 입력+출력만 보면 합계가 맞지 않아 비용을 잘못 계산하게 된다
    return {
        "input": getattr(usage, "prompt_token_count", 0) or 0,
        "output": getattr(usage, "candidates_token_count", 0) or 0,
        "thoughts": getattr(usage, "thoughts_token_count", 0) or 0,
        "total": getattr(usage, "total_token_count", 0) or 0,
    }


def print_response(response, run_number: int) -> None:
    """생성 결과 하나를 사람이 읽을 수 있게 펼쳐 보여 준다."""
    counts = response.counts
    print(f"\n{'=' * 74}")
    print(
        f"{run_number}회차  모델이 낸 {counts.returned_by_model}개 → "
        f"통과 {counts.kept} / 폐기 {counts.dropped} / 잘라냄 {counts.truncated}  "
        f"| 폐기율 {counts.drop_rate:.0%} | {response.meta.elapsed_ms:,.0f}ms"
    )
    print("=" * 74)

    # 통과한 문항: 지시문과 체크리스트를 근거와 함께 보여 준다
    for item in response.items:
        print(f"\n[{item.item_id}] {item.item_type} / {item.expected_register} / {item.status}")
        print(f"  지시문: {item.prompt}")
        print(f"  문항 근거: \"{item.citation.matched_text}\" "
              f"(문서 {item.citation.start}~{item.citation.end}자)")
        for entry in item.checklist:
            print(f"    ({entry.id}, w={entry.weight}) {entry.description}")
            print(f"        근거: \"{entry.citation.matched_text}\"")
        print(f"  핵심어: {', '.join(item.reference_keywords) or '(없음)'}")

    # 버린 문항: 무엇을 왜 버렸는지. 이 목록이 보여야 이 기능이 설명된다
    for drop in response.dropped:
        print(f"\n[폐기 #{drop.index}] {drop.reason.value}")
        print(f"  사유: {drop.detail}")
        print(f"  지시문 앞부분: {drop.rejected_preview}")
        if drop.quote_preview:
            print(f"  문제된 인용: {drop.quote_preview}")

    for warning in response.warnings:
        print(f"\n  경고: {warning}")


def main() -> None:
    parser = argparse.ArgumentParser(description="안전문서로 문항을 만들어 눈으로 확인한다")
    parser.add_argument("--pdf", default="", help="PDF 문서 경로")
    parser.add_argument("--pages", default="", help="PDF 에서 읽을 쪽 범위(예: 4-16)")
    parser.add_argument("--file", default="", help="텍스트 문서 경로")
    parser.add_argument("--items", type=int, default=3, help="만들 문항 수 (기본 3)")
    parser.add_argument("--runs", type=int, default=3, help="같은 문서로 몇 번 만들어 볼지 (기본 3)")
    parser.add_argument("--workplace", default="(주)K-테스트 식품공장", help="사업장 이름")
    parser.add_argument("--no-tokens", action="store_true", help="토큰 측정용 추가 호출을 하지 않는다")
    args = parser.parse_args()

    document, title = load_document(args)

    # 전처리 결과를 먼저 보여 준다. 무엇을 지웠는지 사람이 알아야 하기 때문이다
    pre = preprocess_document(document)
    print(f"\n문서: {title}")
    print(f"  원문 {pre.raw_chars:,}자 → 정제 후 {pre.clean_chars:,}자 (지문 {pre.sha256[:12]})")
    for note in pre.notes:
        print(f"  전처리: {note}")
    if not pre.notes:
        print("  전처리: 지운 것 없음")
    print(f"  생성 모델: {DEFAULT_GENERATION_MODEL} / 프롬프트 판 {PROMPT_VERSION}")

    request = GenerateItemsRequest(
        document_id="check-doc-001",
        document_text=document,
        document_title=title,
        options=GenerateOptions(item_count=args.items, workplace_name=args.workplace),
    )

    # ---- 같은 문서로 여러 번 만들어 본다 ----
    runs = []
    for number in range(1, args.runs + 1):
        started = time.perf_counter()
        try:
            response = generate_items(request)
        except GenerationRequestError as exc:
            raise SystemExit(f"요청이 거절됐습니다: {exc}")
        except LLMUnavailable as exc:
            raise SystemExit(f"LLM 을 쓸 수 없습니다: {exc}\n(생성에는 대체 경로가 없습니다)")
        elapsed = (time.perf_counter() - started) * 1000
        runs.append((response, elapsed))
        print_response(response, number)

    # ---- 회차 비교표 ----
    # 재현성 주장은 문구가 아니라 검증 결과로 한다.
    # 문구는 달라도 관문 통과 여부와 폐기율이 흔들리지 않아야 믿을 수 있는 기능이다
    print(f"\n{'=' * 74}")
    print("회차 비교 — 문구는 달라도 통과 여부와 폐기율은 봐야 할 값이다")
    print("=" * 74)
    print(f"{'회차':<6}{'통과':<6}{'폐기':<6}{'폐기율':<10}{'걸린 시간':<12}{'지시문 첫 문항'}")
    for number, (response, elapsed) in enumerate(runs, start=1):
        first_prompt = response.items[0].prompt[:28] if response.items else "(없음)"
        print(
            f"{number:<6}{response.counts.kept:<6}{response.counts.dropped:<6}"
            f"{response.counts.drop_rate:<10.0%}{elapsed:>8,.0f}ms   {first_prompt}"
        )

    # 한 번만 돌렸으면 견줄 것이 없다. 비교했다고 말하지 않는다
    if len(runs) >= 2:
        wordings = {tuple(item.prompt for item in response.items) for response, _ in runs}
        print(f"\n  문구가 회차마다 같은가: {'같다' if len(wordings) == 1 else '다르다'}")
        print(f"  통과 문항 수가 같은가: "
              f"{'같다' if len({r.counts.kept for r, _ in runs}) == 1 else '다르다'}")
        print(f"  폐기율이 같은가: "
              f"{'같다' if len({r.counts.drop_rate for r, _ in runs}) == 1 else '다르다'}")
        print(
            "\n  ※ 문구가 달라도 문제가 아니다. 생성은 한 번만 하고 사람이 승인한 문항을 시험에 쓴다."
            "\n     재현되어야 하는 것은 채점이며, 채점 재현성은 따로 100% 로 확인돼 있다."
            "\n  ※ 한 번의 실행 안에서 문구가 같아도 '문구가 재현된다'고 말하면 안 된다."
            "\n     실행을 나눠서 부르면 문구가 달라지는 것이 실측됐다."
        )
    else:
        print("\n  (회차가 하나뿐이라 회차 간 비교는 하지 않는다. --runs 3 으로 견줘 볼 수 있다)")

    average_ms = sum(elapsed for _, elapsed in runs) / len(runs)
    print(f"\n  생성 1회 평균 시간: {average_ms:,.0f}ms ({average_ms / 1000:.1f}초)")

    # ---- 토큰 실측 ----
    if not args.no_tokens:
        print("\n토큰 측정용으로 한 번 더 부릅니다(문항 생성에는 쓰이지 않습니다)...")
        usage = measure_tokens(pre.text, args.items, title)
        if usage is None:
            print("  API 키가 없어 토큰을 재지 못했습니다.")
        else:
            print(f"  입력 {usage['input']:,} 토큰 / 출력 {usage['output']:,} 토큰 "
                  f"/ 생각 {usage['thoughts']:,} 토큰 / 합계 {usage['total']:,} 토큰")
            print(f"  (문항 {args.items}개 기준, 문서 {pre.clean_chars:,}자)")
            print("  ※ '생각' 토큰은 모델이 답을 내기 전에 속으로 쓴 몫이며 요금에 포함된다.")


if __name__ == "__main__":
    main()
