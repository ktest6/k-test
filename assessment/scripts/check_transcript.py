"""STT 전사 보정이 실제로 어떻게 동작하는지 눈으로 확인하는 스크립트.

전사 보정은 '점수를 얼마나 바꾸느냐'보다 '무엇을 고쳤다고 밝히느냐'가 중요하다.
그래서 이 스크립트는 통과/실패만 찍지 않고, 원문·보정본·바뀐 자리·신뢰도 표시를
사람이 읽을 수 있는 형태로 그대로 보여 준다.

확인하려는 것:
  1) 보정 구간 좌표가 '원본 전사 기준'으로 나오는가 (이 파트에서 제일 틀리기 쉬운 곳)
  2) 띄어쓰기만 다른 변경은 보정으로 세지 않는가
  3) 답안을 통째로 다시 써 온 과보정 응답을 물리는가
  4) 채점에서 문법은 원문, 내용은 보정본을 보는가
  5) 보정 구간과 겹치는 오류 지적에만 '신뢰도 낮음' 표시가 붙는가
  6) API 키가 없어도 죽지 않고 원문 그대로 채점되는가

3번까지는 LLM 없이 돈다. 마지막에 키가 있으면 실제 호출도 한 번 해 본다.

실행: .venv\\Scripts\\python.exe scripts\\check_transcript.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.features.checklist import SYSTEM_INSTRUCTION as CHECKLIST_SYSTEM  # noqa: E402
from src.features.errors import SYSTEM_INSTRUCTION as ERRORS_SYSTEM  # noqa: E402
from src.llm.client import GeminiClient  # noqa: E402
from src.llm.transcript import (  # noqa: E402
    SYSTEM_INSTRUCTION as TRANSCRIPT_SYSTEM,
    build_correction,
    correct_transcript,
    diff_transcript,
)
from src.scoring.pipeline import score_submission  # noqa: E402
from src.scoring.schema import (  # noqa: E402
    ChecklistItem,
    ItemInfo,
    Mode,
    ScoreRequest,
    TranscriptInput,
)

# STT가 '기계가'를 '기가'로, '차단하고'를 '차단하구'로 잘못 받아쓴 상황을 가정한 답안.
ORIGINAL = "어제 포장 기가 멈췄습니다. 저는 전원을 차단하구 반장님한테 보고했습니다."
CORRECTED = "어제 포장 기계가 멈췄습니다. 저는 전원을 차단하고 반장님한테 보고했습니다."


class FakeClient:
    """키 없이 파이프라인 전체를 돌려 보기 위한 가짜 Gemini 클라이언트.

    실제 클라이언트에서 파이프라인이 쓰는 것은 available·model_name·generate_json 뿐이라
    그 셋만 흉내 낸다. 어떤 글을 보고 판단했는지 확인할 수 있게 프롬프트를 모아 둔다.
    """

    def __init__(self):
        self.available = True
        self.model_name = "fake-model(검증용)"
        self.prompts: dict[str, list[str]] = {"transcript": [], "errors": [], "checklist": []}

    def generate_json(self, prompt, system_instruction="", response_schema=None):
        # 어떤 단계의 호출인지는 시스템 지시문으로 구별한다
        if system_instruction == TRANSCRIPT_SYSTEM:
            self.prompts["transcript"].append(prompt)
            return {
                "corrected_text": CORRECTED,
                "changes": [
                    {"original": "기가", "corrected": "기계가", "reason": "'기계가'가 짧게 들렸다"},
                    {"original": "차단하구", "corrected": "차단하고", "reason": "종결 발음이 흐려졌다"},
                ],
            }
        if system_instruction == ERRORS_SYSTEM:
            self.prompts["errors"].append(prompt)
            return {
                "errors": [
                    {
                        "type": "conjugation",
                        "quote": "차단하구",          # 보정이 일어난 자리
                        "correction": "차단하고",
                        "explanation": "연결어미를 잘못 썼다",
                    },
                    {
                        "type": "josa",
                        "quote": "반장님한테",        # 보정과 무관한 자리
                        "correction": "반장님께",
                        "explanation": "높임 대상에는 '께'를 쓴다",
                    },
                ]
            }
        self.prompts["checklist"].append(prompt)
        return {
            "results": [
                {"id": "c1", "met": 1, "quote": "멈췄습니다", "reason": "고장 사실을 말했다"},
                {"id": "c2", "met": 1, "quote": "보고했습니다", "reason": "보고 사실을 말했다"},
            ]
        }


def make_request(transcript: TranscriptInput | None) -> ScoreRequest:
    """검증용 채점 요청 하나."""
    return ScoreRequest(
        submission_id="check-transcript",
        mode=Mode.SPEAKING,
        answer_text=ORIGINAL,
        item=ItemInfo(
            item_id="item-001",
            prompt="작업 중 생긴 문제와 그 조치를 설명하시오.",
            checklist=[
                ChecklistItem(id="c1", description="문제 상황을 설명했는가"),
                ChecklistItem(id="c2", description="보고 여부를 밝혔는가"),
            ],
        ),
        transcript=transcript,
    )


def print_diff_table(original: str, corrected: str) -> None:
    """원문과 보정본을 대조한 결과를 표로 찍는다.

    좌표가 정말 원본을 가리키는지 눈으로 확인할 수 있도록,
    좌표로 원문을 다시 잘라낸 글자를 함께 보여 준다.
    """
    diffs, spans = diff_transcript(original, corrected)
    print(f"  원문   : {original}")
    print(f"  보정본 : {corrected}")
    if not diffs:
        print("  → 바뀐 곳 없음")
        return

    print(f"  {'종류':<8} {'원본 위치':<10} {'원문':<12} {'보정':<12} 좌표로 되짚은 원문")
    print(f"  {'-' * 74}")
    for d in diffs:
        # 좌표로 원문을 다시 잘라낸다. 이것이 원문과 다르면 좌표계가 틀린 것이다
        sliced = original[d.span_start : d.span_end]
        print(
            f"  {d.kind:<8} {f'{d.start}~{d.end}':<10} "
            f"{(d.original or '(없음)'):<12} {(d.corrected or '(없음)'):<12} "
            f"'{sliced}'"
        )
    print(f"  겹침 판정에 쓸 구간: {spans}")


def section_1_coordinates() -> list[tuple[str, bool]]:
    """바뀜·삽입·삭제·띄어쓰기 네 가지 경우의 좌표를 확인한다."""
    print("=" * 78)
    print("1. 보정 구간 좌표가 원본 전사 기준으로 나오는가")
    print("=" * 78)

    cases = [
        ("낱말이 바뀜", "저는 어제 회사에 가습니다", "저는 어제 회사에 갔습니다"),
        ("빠진 글자가 끼어듦", "안전모 착용했습니다", "안전모를 착용했습니다"),
        ("잘못 들어간 글자가 지워짐", "저는 어어 갔습니다", "저는 갔습니다"),
        ("띄어쓰기만 다름", "저는회사에 갔습니다", "저는 회사에 갔습니다"),
    ]
    for title, original, corrected in cases:
        print(f"\n[{title}]")
        print_diff_table(original, corrected)

    print()
    # 자동 확인: 좌표로 잘라낸 글자가 실제 원문 글자와 같아야 한다
    ok_coords = True
    for _, original, corrected in cases:
        for d in diff_transcript(original, corrected)[0]:
            if original[d.start : d.end] != d.original:
                ok_coords = False

    _, spacing_spans = diff_transcript("저는회사에 갔습니다", "저는 회사에 갔습니다")
    return [
        ("바뀐 자리의 좌표가 원문을 정확히 가리킨다", ok_coords),
        ("띄어쓰기만 다른 것은 보정 구간으로 세지 않는다", spacing_spans == []),
    ]


def section_2_over_correction() -> list[tuple[str, bool]]:
    """응시자의 실제 오류까지 고쳐 온 응답을 물리는지 확인한다."""
    print("=" * 78)
    print("2. 답안을 다시 써 온 과보정 응답을 물리는가")
    print("=" * 78)

    original = "기계 고장 났어요 그래서 반장 불렀어요"
    payload = {
        "corrected_text": "기계가 고장 나서 즉시 전원을 차단하고 반장님께 보고드렸습니다",
        "changes": [],
    }
    result = build_correction(original, payload)

    print(f"  원문        : {original}")
    print(f"  LLM 보정본  : {payload['corrected_text']}")
    print(f"  채택 여부   : {'적용' if result.correction_applied else '폐기(원문으로 채점)'}")
    for w in result.warnings:
        print(f"  경고        : {w}")
    print()

    return [
        ("과보정 응답을 받아들이지 않는다", result.correction_applied is False),
        ("폐기 사유가 경고로 남는다", any("과보정" in w for w in result.warnings)),
    ]


def section_3_pipeline() -> list[tuple[str, bool]]:
    """채점 파이프라인이 원문과 보정본을 영역별로 나눠 쓰는지 확인한다."""
    print("=" * 78)
    print("3. 채점에서 문법은 원문, 내용은 보정본을 보는가")
    print("=" * 78)

    client = FakeClient()
    res = score_submission(make_request(TranscriptInput(nationality="베트남")), client=client)

    print(f"  전사 원문   : {ORIGINAL}")
    print(f"  보정본      : {res.meta.transcript_corrected_text}")
    print(f"  보정 적용   : {res.meta.transcript_correction_applied} "
          f"({res.meta.transcript_change_count}군데)")
    print()

    print("  [보정 내역 — 이의 제기 시 이 목록으로 답한다]")
    for ev in res.meta.transcript_diff:
        print(f"    · {ev.comment}")
        print(f"      원문 {ev.start}~{ev.end} = '{ev.quote}'  (좌표 기준: "
              f"{ev.detail.get('coordinate_base')})")
    print()

    print("  [어느 글을 보고 채점했나]")
    errors_saw_original = ORIGINAL in client.prompts["errors"][0]
    errors_saw_corrected = CORRECTED in client.prompts["errors"][0]
    checklist_saw_corrected = CORRECTED in client.prompts["checklist"][0]
    print(f"    오류 자질(언어 사용)  : {'원문' if errors_saw_original else '원문 아님'}"
          f"{' + 보정본(문제!)' if errors_saw_corrected else ''}")
    print(f"    체크리스트(내용)      : {'보정본' if checklist_saw_corrected else '보정본 아님'}")

    features = {f.id: f for f in res.features}
    length = features["response_length"]
    diversity = features["lexical_diversity_mattr"]
    print(f"    응답 길이 자질        : {length.value}어절 "
          f"(글자 수 {int(length.components['char_count'])} = "
          f"{'보정본' if length.components['char_count'] == len(CORRECTED) else '원문'} 기준)")
    print(f"    어휘 다양도 자질      : {diversity.value} "
          f"({'보정본' if '보정본' in diversity.note else '원문'} 기준)")
    print()

    print("  [보정 구간과 겹치는 오류 지적의 신뢰도]")
    for fid in ("error_conjugation", "error_josa"):
        for ev in features[fid].evidence:
            if not ev.quote:
                continue
            mark = "신뢰도 낮음" if ev.detail.get("confidence") == "low" else "그대로 인정"
            print(f"    [{mark}] '{ev.quote}' — {ev.comment[:60]}")
    print(f"    신뢰도 낮음으로 표시된 지적: {res.meta.transcript_low_confidence_errors}건")
    print()

    print("  [채점 결과]")
    print(f"    종합 점수 {res.overall_score} / 등급 {res.overall_grade}")
    print("  [경고]")
    for w in res.warnings:
        print(f"    · {w}")
    print()

    conj = features["error_conjugation"]
    josa = features["error_josa"]
    return [
        ("오류 자질은 전사 원문만 본다",
         errors_saw_original and not errors_saw_corrected),
        ("체크리스트는 보정본을 본다", checklist_saw_corrected),
        ("응답 길이 자질은 보정본 기준으로 다시 계산된다",
         length.components["char_count"] == float(len(CORRECTED))),
        ("어휘 자질은 원문 기준 그대로다", "보정본" not in diversity.note),
        ("보정 구간과 겹치는 지적에 신뢰도 낮음이 붙는다",
         any(ev.detail.get("confidence") == "low" for ev in conj.evidence)),
        ("보정과 무관한 지적에는 붙지 않는다",
         all(ev.detail.get("confidence") != "low" for ev in josa.evidence)),
        ("보정 내역이 근거로 결과에 실린다", len(res.meta.transcript_diff) >= 1),
        ("근거의 인용이 전사 원문에 실제로 있다",
         all(ev.quote in ORIGINAL for ev in res.meta.transcript_diff)),
    ]


def section_4_no_key() -> list[tuple[str, bool]]:
    """LLM을 못 쓰는 상황에서도 채점이 끝나는지 확인한다."""
    print("=" * 78)
    print("4. LLM을 못 써도 죽지 않고 원문으로 채점되는가")
    print("=" * 78)

    class NoKeyClient(FakeClient):
        def __init__(self):
            super().__init__()
            self.available = False

    client = NoKeyClient()
    res = score_submission(make_request(TranscriptInput()), client=client)

    print(f"  LLM 호출 시도: {sum(len(v) for v in client.prompts.values())}회 (키가 없으면 0이어야 한다)")
    print(f"  보정 적용    : {res.meta.transcript_correction_applied}")
    print(f"  종합 점수    : {res.overall_score} / 등급 {res.overall_grade}")
    print("  [경고]")
    for w in res.warnings:
        print(f"    · {w}")
    print()

    return [
        ("키가 없으면 호출을 시도하지 않는다",
         sum(len(v) for v in client.prompts.values()) == 0),
        ("보정 없이도 채점이 끝난다", res.overall_score is not None),
        ("보정을 못 한 사실이 경고에 남는다",
         any("전사 보정" in w for w in res.warnings)),
    ]


def section_5_real_llm() -> None:
    """키가 있으면 실제 Gemini 로 한 번 보정해 본다.

    여기는 통과/실패로 세지 않는다. 네트워크와 사용량에 따라 결과가 달라지므로
    '실제로 무엇이 나왔는지'를 사람이 읽고 판단하라는 자리다.
    """
    print("=" * 78)
    print("5. 실제 LLM 보정 (키가 있을 때만)")
    print("=" * 78)

    client = GeminiClient()
    if not client.available:
        print("  GEMINI_API_KEY 가 없어 실제 호출은 건너뛴다.")
        print("  (이 상태에서도 위 1~4번은 전부 확인된다. 채점은 원문으로 진행된다)")
        print()
        return

    print(f"  모델: {client.model_name}")
    print(f"  원문: {ORIGINAL}")
    result = correct_transcript(
        ORIGINAL,
        nationality="베트남",
        item_prompt="작업 중 생긴 문제와 그 조치를 설명하시오.",
        client=client,
    )
    print(f"  보정본: {result.corrected_text}")
    print(f"  보정 적용: {result.correction_applied} ({result.change_count}군데)")
    for d in result.diffs:
        print(f"    · {d.describe()}" + (f" — {d.reason}" if d.reason else ""))
    for w in result.warnings:
        print(f"  경고: {w}")
    print()
    print("  ※ 실제 호출 결과는 모델 응답에 따라 달라진다. 위 diff 를 눈으로 보고")
    print("     응시자가 실제로 틀린 문법까지 고쳐 놓지 않았는지 확인하라.")
    print()


def main() -> None:
    checks: list[tuple[str, bool]] = []
    checks += section_1_coordinates()
    checks += section_2_over_correction()
    checks += section_3_pipeline()
    checks += section_4_no_key()

    # 실제 호출은 결과가 매번 달라질 수 있어 확인 항목에 넣지 않는다
    section_5_real_llm()

    print("-" * 78)
    print("확인 항목")
    print("-" * 78)
    failed = 0
    for desc, ok in checks:
        print(f"  [{'OK ' if ok else 'NG '}] {desc}")
        if not ok:
            failed += 1

    print()
    if failed:
        print(f"확인 실패 {failed}건 — 전사 보정 경로를 손봐야 한다.")
        sys.exit(1)
    print("전사 보정 확인 전부 통과.")


if __name__ == "__main__":
    main()
