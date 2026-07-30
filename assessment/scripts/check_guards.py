"""답안 유효성 가드가 실제로 악성 답안을 막는지 눈으로 확인하는 스크립트.

2026-07-30 실측에서 확정 문항 WRT-003(위험 신고)에 악성 답안을 넣었더니
아래처럼 나왔다. 이 표를 다시 만들어 가드 적용 뒤 어떻게 바뀌는지 보여 준다.

    답안            종합      등급   문제
    정상 답안       80.58     B      (기준선 — 가드에 걸리면 안 된다)
    영어 답안       77.48     B      한국어 시험인데 영어가 B
    단어 반복 스팸  57.03     C      체크리스트 2/3 통과
    지시문 베끼기   57.68     C      지시문에 위험 설명이 있어 1/3 통과
    초단답          35.36     E      종합은 막혔지만 언어 사용이 64점

'가드 적용 전' 칸은 가드를 붙이기 전의 채점 경로(규칙 자질 + LLM 자질 + 결합)를
그대로 다시 돌려서 얻는다. 무효로 막힌 답안만 두 경로를 다 돌리며,
가드를 통과한 답안은 계산 경로가 이전과 같으므로 한 번만 돌린다.

실행:
    .venv\\Scripts\\python.exe scripts\\check_guards.py
    .venv\\Scripts\\python.exe scripts\\check_guards.py --no-llm   (LLM 없이 가드만)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.features.checklist import judge_checklist  # noqa: E402
from src.features.errors import extract_error_features  # noqa: E402
from src.features.lexical import extract_lexical_features  # noqa: E402
from src.llm.client import GeminiClient, client_for_errors  # noqa: E402
from src.scoring.combine import combine, get_weights  # noqa: E402
from src.scoring.pipeline import score_submission  # noqa: E402
from src.scoring.schema import (  # noqa: E402
    AreaStatus,
    ChecklistItem,
    ItemInfo,
    Mode,
    ScoreArea,
    ScoreOptions,
    ScoreRequest,
)

W = 96

# 확정 문항 WRT-003 (items/writing_v0.json)
PROMPT = (
    "창고 선반이 한쪽으로 기울어져 있습니다. 물건이 떨어질 수 있습니다. "
    "안전 관리자에게 알리는 글을 쓰세요. "
    "① 무엇이 위험한지 ② 어디에 있는지 ③ 어떤 조치가 필요한지 쓰세요."
)
CHECKLIST = [
    ChecklistItem(id="c1", description="무엇이 어떻게 위험한지 구체적으로 알렸는가", weight=1.5),
    ChecklistItem(id="c2", description="위험한 곳이 어디인지 위치를 알렸는가", weight=1.5),
    ChecklistItem(id="c3", description="필요한 조치를 요청했는가", weight=1.0),
]

# (이름, 답안, 실측 종합점수, 실측 등급)
CASES: list[tuple[str, str, float, str]] = [
    (
        "정상 답안",
        "안전 관리자님, 2층 창고 A구역 선반이 오른쪽으로 기울어져 있습니다. "
        "위쪽에 무거운 상자가 쌓여 있어서 사람이 지나갈 때 떨어질 위험이 큽니다. "
        "오늘 오전에 확인했고 지금은 주변에 접근하지 못하도록 표시해 두었습니다. "
        "선반 고정 작업과 상자 재배치를 빨리 해 주시기 바랍니다.",
        80.58,
        "B",
    ),
    (
        "영어 답안",
        "The shelf in the warehouse is leaning to one side. Boxes may fall down and "
        "hurt someone. Please send a technician to fix the shelf as soon as possible. "
        "It is located in the second floor storage area near the entrance.",
        77.48,
        "B",
    ),
    ("단어 반복 스팸", "창고 위험 선반 수리 " * 12, 57.03, "C"),
    (
        "지시문 베끼기",
        "창고 선반이 한쪽으로 기울어져 있습니다. 물건이 떨어질 수 있습니다. "
        "안전 관리자에게 알리는 글을 쓰세요. "
        "무엇이 위험한지 어디에 있는지 어떤 조치가 필요한지 쓰세요.",
        57.68,
        "C",
    ),
    ("초단답", "네 알겠습니다.", 35.36, "E"),
]

# 오류 자질 전용 상위 모델이 실제로 무엇을 더 잡는지 보기 위한 답안.
# '반장님이 말했습니다'는 상급자를 안 높인 높임법 오류다('말씀하셨습니다'가 맞다).
HONORIFIC_CASE = (
    "어제 반장님이 말했습니다. 오늘까지 창고 정리를 끝내라고 했습니다. "
    "그래서 저는 오전에 창고에 가서 상자를 옮겼습니다. 사장님도 창고에 왔습니다."
)


def rule(title: str = "") -> None:
    if title:
        print("\n" + "=" * W)
        print(f"  {title}")
        print("=" * W)
    else:
        print("-" * W)


def short(text: str, n: int = 90) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: n - 1] + "…"


def make_request(answer: str, use_llm: bool) -> ScoreRequest:
    """WRT-003 문항에 답안 하나를 넣은 채점 요청을 만든다."""
    return ScoreRequest(
        submission_id="guard-check",
        mode=Mode.WRITING,
        answer_text=answer,
        item=ItemInfo(
            item_id="WRT-003",
            prompt=PROMPT,
            expected_register="formal",
            checklist=CHECKLIST,
            reference_keywords=["선반", "창고", "기울", "위험", "떨어지"],
        ),
        options=ScoreOptions(use_llm=use_llm),
    )


def score_without_guards(request: ScoreRequest, client: GeminiClient):
    """가드를 붙이기 전의 채점 경로를 그대로 재현한다.

    규칙 자질 -> LLM 오류 자질 -> 체크리스트 판정 -> 결합.
    파이프라인에서 가드만 빼면 이 순서였다.
    '가드 적용 전' 점수를 비교용으로 보여 주기 위한 것이며 운영 경로가 아니다.
    """
    use_llm = request.options.use_llm
    features = extract_lexical_features(request.answer_text, request.mode)
    error_result = extract_error_features(
        request.answer_text,
        mode=request.mode,
        client=client_for_errors(client),
        item_prompt=request.item.prompt,
        use_llm=use_llm,
    )
    checklist_result = judge_checklist(
        request.answer_text, request.item, client=client, use_llm=use_llm
    )
    features.extend(error_result.features)
    return combine(
        features=features,
        checklist_results=checklist_result.results,
        mode=request.mode,
        weights=get_weights(request.options.weights_profile),
    ), checklist_result


def area_score(subscores, area: ScoreArea):
    for s in subscores:
        if s.area == area:
            return s
    return None


def run_case(name: str, answer: str, use_llm: bool, client: GeminiClient) -> dict:
    """한 답안에 대해 가드 적용 전/후를 함께 구한다."""
    request = make_request(answer, use_llm)

    # 가드 적용 후 = 지금의 운영 경로
    after = score_submission(request, client=client)

    # 가드가 막은 답안만 '적용 전' 경로를 따로 돌린다.
    # 통과한 답안은 계산 경로가 이전과 같아서 두 번 돌릴 이유가 없다(LLM 호출도 아낀다)
    if after.meta.answer_valid:
        before_score, before_grade = after.overall_score, after.overall_grade
        before_language = area_score(after.subscores, ScoreArea.LANGUAGE_USE)
        before_checklist = after.checklist_results
    else:
        before, checklist_result = score_without_guards(request, client)
        before_score, before_grade = before.overall_score, before.overall_grade
        before_language = area_score(before.subscores, ScoreArea.LANGUAGE_USE)
        before_checklist = checklist_result.results

    return {
        "name": name,
        "after": after,
        "before_score": before_score,
        "before_grade": before_grade,
        "before_language": before_language,
        "before_checklist": before_checklist,
    }


def print_case(result: dict, measured: tuple[float, str]) -> None:
    """한 답안의 전/후를 사람이 읽게 찍어 준다."""
    after = result["after"]
    meta = after.meta
    rule()
    print(f"  ● {result['name']}")

    met = sum(1 for c in result["before_checklist"] if c.met == 1)
    total = len(result["before_checklist"])
    lang = result["before_language"]
    lang_text = "—" if lang is None or lang.score is None else f"{lang.score:.2f}"
    before_score = "—" if result["before_score"] is None else f"{result['before_score']:.2f}"

    print(
        f"      가드 적용 전 : 종합 {before_score:>6} / 등급 {str(result['before_grade']):<4} "
        f"언어사용 {lang_text:>6}  체크리스트 {met}/{total}"
        f"   (실측 기록 {measured[0]:.2f} / {measured[1]})"
    )

    after_score = "무효" if after.overall_score is None else f"{after.overall_score:.2f}"
    after_grade = "없음" if after.overall_grade is None else after.overall_grade
    after_lang = area_score(after.subscores, ScoreArea.LANGUAGE_USE)
    after_lang_text = (
        "채점 안 함" if after_lang is None or after_lang.score is None
        else f"{after_lang.score:.2f} ({after_lang.status.value})"
    )
    print(
        f"      가드 적용 후 : 종합 {after_score:>6} / 등급 {after_grade:<4} "
        f"언어사용 {after_lang_text}"
    )
    print(
        f"      판정        : answer_valid={meta.answer_valid}  "
        f"flags={meta.validity_flags or '없음'}  "
        f"화면표시={'가능' if meta.safe_to_show_candidate else '불가'}"
    )
    if meta.validity_reason:
        print(f"      사유        : {short(meta.validity_reason)}")

    # 근거가 실제로 붙는지 본다. 근거 없는 판정은 이 프로젝트에서 결함이다
    quotes = [ev for s in after.subscores for ev in s.evidence if ev.quote]
    for ev in quotes[:2]:
        print(f"      근거        : “{short(ev.quote, 50)}” ({ev.start}~{ev.end}) — {short(ev.comment, 40)}")


def check_error_model(client: GeminiClient, use_llm: bool) -> None:
    """오류 자질 전용 모델이 높임법 오류를 잡는지 확인한다."""
    rule("오류 자질 전용 모델 확인 (높임법)")
    base_model = client.model_name
    error_model = client_for_errors(client).model_name
    print(f"  기본 모델(체크리스트·전사 보정) : {base_model}")
    print(f"  오류 자질 모델                  : {error_model}")
    print(f"\n  답안: {HONORIFIC_CASE}")
    print("  기대: '반장님이 말했습니다' 를 높임법 오류로 잡아야 한다(말씀하셨습니다).")

    response = score_submission(make_request(HONORIFIC_CASE, use_llm), client=client)
    print(f"\n  실제 쓴 오류 자질 모델: {response.meta.llm_model_errors}")
    found = False
    for feature in response.features:
        if not feature.id.startswith("error_") or not feature.components.get("error_count"):
            continue
        count = int(feature.components["error_count"])
        print(f"    {feature.name:<14} {count}건")
        for ev in feature.evidence[:3]:
            if ev.quote:
                print(f"        “{ev.quote}” — {short(ev.comment, 60)}")
        if feature.id == "error_honorific":
            found = True
    if not found:
        print("    (높임법 오류가 잡히지 않았다)")
    for warning in response.warnings:
        if "LLM" in warning or "실패" in warning:
            print(f"    ! {short(warning)}")


def main() -> int:
    parser = argparse.ArgumentParser(description="답안 유효성 가드를 눈으로 확인한다.")
    parser.add_argument(
        "--no-llm", action="store_true",
        help="LLM 없이 가드 동작만 확인한다(공짜·즉시)",
    )
    args = parser.parse_args()
    use_llm = not args.no_llm

    client = GeminiClient()
    rule("입력")
    print(f"  문항   : WRT-003 (위험 신고)")
    print(f"  모델   : {client.model_name} / 오류 자질 {client_for_errors(client).model_name}")
    print(f"  LLM    : {'사용' if use_llm and client.available else '미사용'}")
    if use_llm and not client.available:
        print("  ! GEMINI_API_KEY 가 없어 규칙 자질만으로 돈다. 점수는 참고용이다.")

    rule("악성 답안 5종 — 가드 적용 전/후")
    # 실측 기록은 오류 자질을 lite 모델로 돌리던 때의 값이다.
    # 지금은 오류 자질만 상위 모델로 보므로 '가드 적용 전' 숫자도 그때와 조금 다르게 나온다.
    # 여기서 봐야 할 것은 실측값과의 일치가 아니라 '가드 전 -> 가드 후'의 변화다
    print("  ※ '실측 기록'은 오류 자질을 lite 모델로 돌리던 때의 값이라 '가드 적용 전'과 조금 다르다.")
    print("     여기서 볼 것은 실측값과의 일치가 아니라 전/후의 변화다.\n")
    results = []
    for name, answer, measured_score, measured_grade in CASES:
        result = run_case(name, answer, use_llm, client)
        print_case(result, (measured_score, measured_grade))
        results.append(result)

    by_name = {r["name"]: r for r in results}

    check_error_model(client, use_llm)

    rule("확인 항목")
    normal = by_name["정상 답안"]["after"]
    english = by_name["영어 답안"]["after"]
    spam = by_name["단어 반복 스팸"]["after"]
    copied = by_name["지시문 베끼기"]["after"]
    tiny = by_name["초단답"]["after"]
    tiny_language = area_score(tiny.subscores, ScoreArea.LANGUAGE_USE)

    checks = [
        ("정상 답안은 가드에 걸리지 않는다",
         normal.meta.answer_valid and not normal.meta.validity_flags),
        ("정상 답안은 종합 점수와 등급이 그대로 나온다",
         normal.overall_score is not None and normal.overall_grade is not None),
        ("영어 답안은 채점 무효다", english.overall_score is None),
        ("영어 답안에 등급이 매겨지지 않는다", english.overall_grade is None),
        ("단어 반복 스팸은 채점 무효다", spam.overall_score is None),
        ("지시문 베끼기는 채점 무효다", copied.overall_score is None),
        ("무효 답안은 화면 표시 불가로 표시된다",
         not any(r.meta.safe_to_show_candidate for r in (english, spam, copied))),
        ("무효 사유가 사람이 읽는 문장으로 남는다",
         all(r.meta.validity_reason for r in (english, spam, copied))),
        ("무효 판정에 원문 근거가 붙는다",
         all(any(ev.quote for s in r.subscores for ev in s.evidence)
             for r in (english, copied))),
        ("초단답은 채점은 되되 언어 사용이 partial 로 내려간다",
         tiny.overall_score is not None
         and tiny_language is not None
         and tiny_language.status == AreaStatus.PARTIAL),
    ]

    failed = 0
    for description, ok in checks:
        print(f"  [{'OK ' if ok else 'NG '}] {description}")
        if not ok:
            failed += 1

    print()
    if failed:
        print(f"확인 실패 {failed}건 — 가드를 손봐야 한다.")
        return 1
    print("가드 확인 전부 통과.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
