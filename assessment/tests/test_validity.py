"""답안 유효성 가드 회귀 테스트.

왜 이걸 테스트로 못 박는가 (2026-07-30 실측):
확정 문항 WRT-003 에 악성 답안을 넣었더니 아래처럼 나왔다.

    영어로만 쓴 답안       77.48점 (B)   <- 한국어 시험인데 영어가 B
    단어 반복 스팸         57.03점 (C)
    지시문 베끼기          57.68점 (C)
    초단답                 35.36점 (E)  그런데 언어 사용은 64점

오류 자질이 '틀린 것이 없으면 만점'이라서, 한국어를 안 쓰면 만점이 되는 구멍이다.
사람이 눈으로 훑는 것만으로는 이런 구멍이 조용히 되돌아오므로 값으로 고정한다.

이 테스트는 **LLM을 한 번도 부르지 않는다.**
가드가 규칙만으로 판단하는지, 그리고 무효 답안에 LLM 호출이 나가지 않는지를
함께 확인해야 하기 때문이다.

실행: .venv\\Scripts\\python.exe -m pytest tests -q
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.llm.client import DEFAULT_ERROR_MODEL, GeminiClient, client_for_errors
from src.scoring.pipeline import score_submission
from src.scoring.schema import (
    AreaStatus,
    ChecklistItem,
    ItemInfo,
    Mode,
    ScoreArea,
    ScoreOptions,
    ScoreRequest,
    ScoringMeta,
)
from src.scoring.validity import (
    FLAG_NOT_KOREAN,
    FLAG_NOT_SENTENCES,
    FLAG_PROMPT_COPY,
    FLAG_TOO_SHORT,
    check_answer_validity,
    hangul_ratio,
    prompt_overlap,
)

# 실측에 쓴 확정 문항 WRT-003(위험 신고)의 지시문이다.
PROMPT_WRT003 = (
    "창고 선반이 한쪽으로 기울어져 있습니다. 물건이 떨어질 수 있습니다. "
    "안전 관리자에게 알리는 글을 쓰세요. "
    "① 무엇이 위험한지 ② 어디에 있는지 ③ 어떤 조치가 필요한지 쓰세요."
)

# 악성 답안 5종. 표의 다섯 줄을 그대로 옮긴 것이다.
ANSWER_NORMAL = (
    "안전 관리자님, 2층 창고 A구역 선반이 오른쪽으로 기울어져 있습니다. "
    "위쪽에 무거운 상자가 쌓여 있어서 사람이 지나갈 때 떨어질 위험이 큽니다. "
    "오늘 오전에 확인했고 지금은 주변에 접근하지 못하도록 표시해 두었습니다. "
    "선반 고정 작업과 상자 재배치를 빨리 해 주시기 바랍니다."
)
ANSWER_ENGLISH = (
    "The shelf in the warehouse is leaning to one side. Boxes may fall down and "
    "hurt someone. Please send a technician to fix the shelf as soon as possible. "
    "It is located in the second floor storage area near the entrance."
)
ANSWER_SPAM = "창고 위험 선반 수리 " * 12
ANSWER_COPY = (
    "창고 선반이 한쪽으로 기울어져 있습니다. 물건이 떨어질 수 있습니다. "
    "안전 관리자에게 알리는 글을 쓰세요. "
    "무엇이 위험한지 어디에 있는지 어떤 조치가 필요한지 쓰세요."
)
ANSWER_TOO_SHORT = "네 알겠습니다."


class _CountingClient:
    """부르면 호출 횟수만 세는 가짜 클라이언트.

    무효 답안에 LLM 호출이 나가지 않는지 확인하는 데 쓴다.
    실제 클라이언트에서 파이프라인이 쓰는 것은 이 세 가지뿐이다.
    """

    def __init__(self):
        self.available = True
        self.model_name = "fake-model"
        self.calls = 0

    def generate_json(self, prompt, system_instruction="", response_schema=None):
        self.calls += 1
        # 어떤 호출이든 형식만 맞는 빈 결과를 준다(가드 검증에는 내용이 필요 없다)
        return {"errors": [], "results": []}


def _request(answer: str, use_llm: bool = False) -> ScoreRequest:
    """WRT-003 문항에 답안 하나를 넣은 채점 요청을 만든다."""
    return ScoreRequest(
        submission_id="sub-guard",
        mode=Mode.WRITING,
        answer_text=answer,
        item=ItemInfo(
            item_id="WRT-003",
            prompt=PROMPT_WRT003,
            checklist=[
                ChecklistItem(id="c1", description="무엇이 어떻게 위험한지 알렸는가", weight=1.5),
                ChecklistItem(id="c2", description="위험한 곳이 어디인지 알렸는가", weight=1.5),
                ChecklistItem(id="c3", description="필요한 조치를 요청했는가", weight=1.0),
            ],
            reference_keywords=["선반", "창고", "위험"],
        ),
        options=ScoreOptions(use_llm=use_llm),
    )


def _area(response, area: ScoreArea):
    return next(s for s in response.subscores if s.area == area)


# ---------------------------------------------------------------------------
# 1) 악성 답안 5종이 각각 의도대로 처리되는가
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "answer, expected_flag",
    [
        (ANSWER_ENGLISH, FLAG_NOT_KOREAN),
        (ANSWER_SPAM, FLAG_NOT_SENTENCES),
        (ANSWER_COPY, FLAG_PROMPT_COPY),
    ],
)
def test_악성_답안은_채점_무효가_된다(answer, expected_flag):
    response = score_submission(_request(answer), client=_CountingClient())

    # 점수를 아예 내지 않는다. 0점으로 때우면 '한국어로 답했지만 다 틀렸다'와 구별되지 않는다
    assert response.overall_score is None
    assert response.overall_grade is None
    assert response.meta.answer_valid is False
    assert expected_flag in response.meta.validity_flags
    # 사유는 사람이 읽을 수 있어야 한다
    assert response.meta.validity_reason
    assert any("채점 무효" in w for w in response.warnings)


def test_영어_답안이_더_이상_등급을_받지_못한다():
    """실측에서 77.48점 B였던 그 답안이다."""
    response = score_submission(_request(ANSWER_ENGLISH), client=_CountingClient())

    assert response.overall_grade is None
    assert FLAG_NOT_KOREAN in response.meta.validity_flags
    # 어디가 한국어가 아닌지 원문 인용으로 짚어 줘야 한다
    quotes = [ev.quote for s in response.subscores for ev in s.evidence if ev.quote]
    assert quotes
    assert all(q in ANSWER_ENGLISH for q in quotes)


def test_초단답은_무효가_아니라_언어_사용을_낮춘다():
    """짧은 답안은 채점을 막지 않는다. '오류 0건'을 못 믿는다는 표시만 남긴다."""
    response = score_submission(_request(ANSWER_TOO_SHORT), client=_CountingClient())

    # 채점은 계속된다
    assert response.overall_score is not None
    assert response.meta.answer_valid is True
    assert FLAG_TOO_SHORT in response.meta.validity_flags

    # 다만 언어 사용 영역은 온전한 점수가 아니라고 표시된다
    language = _area(response, ScoreArea.LANGUAGE_USE)
    assert language.status == AreaStatus.PARTIAL
    assert "짧아" in language.note
    assert any("답안 유효성" in w for w in response.warnings)


def test_정상_답안은_가드에_걸리지_않는다():
    """기준선 답안(실측 80.58점 B)이 가드 때문에 막히면 안 된다."""
    response = score_submission(_request(ANSWER_NORMAL), client=_CountingClient())

    assert response.meta.answer_valid is True
    assert response.meta.validity_flags == []
    assert response.meta.validity_reason == ""
    assert response.overall_score is not None


@pytest.mark.parametrize(
    "item_id, answer",
    [
        (
            "WRT-001",
            "오늘 3번 라인에서 포장 작업을 했습니다. 오후에 포장 기계가 두 번 멈추는 문제가 "
            "있었습니다. 반장님께 보고하고 정비팀에 연락해서 벨트를 교체했습니다.",
        ),
        (
            "WRT-002",
            "반장님, 죄송합니다. 어제부터 열이 나고 몸이 많이 아파서 내일 출근하지 못할 것 "
            "같습니다. 병원에서 이틀 정도 쉬라고 했고, 모레는 나갈 수 있을 것 같습니다.",
        ),
        (
            "WRT-003",
            "안전 관리자님, 2층 창고 A구역 선반이 오른쪽으로 기울어져 있습니다. 위에 있는 "
            "상자가 떨어질 위험이 큽니다. 선반 고정 작업을 빨리 해 주시기 바랍니다.",
        ),
        (
            "WRT-004",
            "오늘 인수인계 드립니다. 1번 라인 포장은 모두 끝냈습니다. 2번 라인 검사 작업은 "
            "절반만 끝나서 나머지는 부탁드립니다. 검사기 화면이 가끔 멈추니까 조심해 주세요.",
        ),
        (
            "WRT-005",
            "작업용 장갑이 거의 다 떨어졌습니다. 지금 다섯 켤레만 남았습니다. 한 상자 50켤레 "
            "정도 필요합니다. 다음 주 월요일까지 받을 수 있으면 좋겠습니다.",
        ),
    ],
)
def test_확정_문항_다섯_개의_상식적_답안이_전부_통과한다(item_id, answer):
    """가드가 잡아야 할 것보다 많이 잡으면 그것이 더 큰 사고다.

    특히 지시문 겹침 가드는 '선반이 기울어져 있습니다'처럼 지시문의 표현을
    자연스럽게 다시 쓰는 정상 답안을 막으면 안 된다.
    """
    items = json.loads(
        (Path(__file__).resolve().parent.parent / "items" / "writing_v0.json")
        .read_text(encoding="utf-8")
    )["items"]
    prompt = next(i["prompt"] for i in items if i["item_id"] == item_id)

    report = check_answer_validity(answer, prompt)

    assert report.valid, f"{item_id} 정상 답안이 가드에 걸렸다: {report.reason}"
    assert report.flags == []


# ---------------------------------------------------------------------------
# 2) 무효 응답의 계약 형태 (백엔드가 받는 모양)
# ---------------------------------------------------------------------------


def test_무효여도_예외_없이_평소와_같은_응답_구조로_돌아온다():
    response = score_submission(_request(ANSWER_ENGLISH), client=_CountingClient())

    # 백엔드가 분기 없이 읽을 수 있도록 자리는 그대로 있어야 한다
    assert response.submission_id == "sub-guard"
    assert response.item_id == "WRT-003"
    assert len(response.subscores) == 3
    assert all(s.score is None for s in response.subscores)
    assert all(s.status == AreaStatus.NOT_EVALUATED for s in response.subscores)
    assert all(s.weight == 0.0 for s in response.subscores)
    # 어떤 답안이었는지 확인할 수 있도록 규칙 자질은 남긴다
    assert response.features
    # 판정하지 않았으므로 체크리스트 결과는 비어 있다
    assert response.checklist_results == []


def test_무효_응답은_화면에_띄우지_말라고_표시된다():
    meta = score_submission(_request(ANSWER_COPY), client=_CountingClient()).meta

    # 프론트는 이 값 하나만 보면 된다
    assert meta.safe_to_show_candidate is False
    assert meta.answer_valid is False
    assert meta.validity_flags
    assert meta.validity_reason


def test_무효_답안에는_LLM_호출이_한_번도_나가지_않는다():
    """하드 게이트가 LLM보다 앞에 서 있는지 확인한다(전사 보정도 LLM 호출이다)."""
    client = _CountingClient()
    score_submission(_request(ANSWER_ENGLISH, use_llm=True), client=client)

    assert client.calls == 0


def test_무효_문항은_최종_등급에서_채점된_것으로_세지_않는다():
    """무효 답안 하나가 조용히 '이수한 문항'으로 세어지면 안 된다."""
    from src.scoring.finalize import finalize_session
    from src.scoring.schema import ExpectedItem, FinalizeItem, FinalizeRequest

    invalid = score_submission(_request(ANSWER_ENGLISH), client=_CountingClient())
    request = FinalizeRequest(
        session_id="s-guard",
        items=[
            FinalizeItem(
                item_id="WRT-003",
                mode=Mode.WRITING,
                overall_score=invalid.overall_score,
                subscores=invalid.subscores,
                meta=invalid.meta,
            )
        ],
        expected_items=[ExpectedItem(item_id="WRT-003", mode=Mode.WRITING)],
    )

    result = finalize_session(request)

    assert "WRT-003" in result.item_coverage.failed_item_ids
    assert result.item_coverage.scored_count == 0


# ---------------------------------------------------------------------------
# 3) 기본값 — 가드를 안 태우던 기존 요청이 그대로 동작하는가
# ---------------------------------------------------------------------------


def test_새로_붙인_계약_필드의_기본값이_안전한_쪽이다():
    """백엔드가 이 필드를 안 보고 있어도 지금까지와 똑같이 동작해야 한다."""
    meta = ScoringMeta(mode=Mode.WRITING)

    assert meta.answer_valid is True
    assert meta.validity_flags == []
    assert meta.validity_reason == ""
    assert meta.llm_model_errors is None


def test_가드를_통과한_답안의_meta_는_예전과_같은_값을_유지한다():
    response = score_submission(_request(ANSWER_NORMAL), client=_CountingClient())
    meta = response.meta

    # 유효한 답안에서는 새 필드가 '아무 일도 없었다'는 값으로 나간다
    assert meta.answer_valid is True
    assert meta.validity_flags == []
    # 기존 필드도 그대로다
    assert meta.mode == Mode.WRITING
    assert meta.scoring_version
    assert meta.transcript_correction_applied is False


# ---------------------------------------------------------------------------
# 4) 가드 하나하나의 계산 (입력을 넣고 값을 확인한다)
# ---------------------------------------------------------------------------


def test_한글_비율은_숫자와_문장부호를_분모에서_뺀다():
    """'3번 라인', '20켤레' 같은 정상 답안이 숫자 때문에 걸리면 안 된다."""
    ratio, hangul, total = hangul_ratio("3번 라인에서 20개 포장했습니다.")

    # 숫자 3, 2, 0 과 공백·마침표는 세지 않는다
    assert hangul == total
    assert ratio == 1.0

    # 영어 답안은 한글이 하나도 없다
    ratio_en, hangul_en, total_en = hangul_ratio("The shelf is leaning.")
    assert hangul_en == 0
    assert total_en > 0
    assert ratio_en == 0.0

    # 숫자만 적은 답안은 셀 글자가 없으므로 한국어가 없는 것으로 본다
    assert hangul_ratio("123 456")[0] == 0.0


def test_지시문_낱말을_자연스럽게_다시_쓴_답안은_겹침이_낮다():
    normal_ratio, _ = prompt_overlap(ANSWER_NORMAL, PROMPT_WRT003)
    copy_ratio, spans = prompt_overlap(ANSWER_COPY, PROMPT_WRT003)

    # 정상 답안도 '선반이 기울어져 있습니다'는 그대로 쓰지만 답안 전체로 보면 일부다
    assert normal_ratio < 0.5
    # 베낀 답안은 거의 전부가 지시문이다
    assert copy_ratio > 0.9
    # 어디가 겹쳤는지 원문 위치로 짚어 줘야 한다
    assert spans
    start, end = spans[0]
    assert ANSWER_COPY[start:end].strip()


def test_낱말만_나열한_답안은_문장으로_인정되지_않는다():
    spam = check_answer_validity(ANSWER_SPAM, PROMPT_WRT003)
    normal = check_answer_validity(ANSWER_NORMAL, PROMPT_WRT003)

    spam_check = next(c for c in spam.checks if c.flag == FLAG_NOT_SENTENCES)
    normal_check = next(c for c in normal.checks if c.flag == FLAG_NOT_SENTENCES)

    assert spam_check.passed is False
    assert spam_check.hard is True          # 어미가 아예 없으면 채점 무효다
    assert normal_check.passed is True


def test_모든_가드_판정에_근거가_붙는다():
    """근거 없는 판정은 이 프로젝트에서 결함이다."""
    for answer in (ANSWER_ENGLISH, ANSWER_SPAM, ANSWER_COPY, ANSWER_TOO_SHORT):
        report = check_answer_validity(answer, PROMPT_WRT003)
        for check in report.failures:
            assert check.reason, f"{check.flag} 에 사유가 없다"
            assert check.evidence, f"{check.flag} 에 근거가 없다"
            for ev in check.evidence:
                # 인용은 지어낸 글이 아니라 원문에서 잘라낸 것이어야 한다
                assert answer[ev.start : ev.end] == ev.quote


# ---------------------------------------------------------------------------
# 5) 오류 자질 전용 상위 모델 배선
# ---------------------------------------------------------------------------


def test_오류_자질만_다른_모델을_쓴다():
    base = GeminiClient(api_key="dummy-key-for-test")
    errors = client_for_errors(base)

    # 기본 클라이언트는 그대로 두고 새 클라이언트만 모델이 다르다
    assert errors.model_name == DEFAULT_ERROR_MODEL
    assert base.model_name != DEFAULT_ERROR_MODEL or errors is base
    # 키는 같이 쓰므로 한쪽만 못 쓰게 되는 일이 없다
    assert errors.available is base.available


def test_가짜_클라이언트는_바꿔치기하지_않는다():
    """테스트·데모가 넘긴 클라이언트를 바꾸면 실제 네트워크로 호출이 나간다."""
    fake = _CountingClient()

    assert client_for_errors(fake) is fake


def test_오류_자질에_쓴_모델이_결과에_남는다():
    client = _CountingClient()
    response = score_submission(_request(ANSWER_NORMAL, use_llm=True), client=client)

    # LLM을 실제로 썼으면 어떤 모델이 문법을 판정했는지 남아야 한다
    assert response.meta.llm_model_errors == "fake-model"


def test_LLM을_끄면_오류_모델도_기록되지_않는다():
    response = score_submission(_request(ANSWER_NORMAL, use_llm=False), client=_CountingClient())

    assert response.meta.llm_model_errors is None
