"""오류·상태 문구의 '코드' 체계를 지키는 회귀 테스트.

**왜 이것을 테스트로 못 박는가.**
이 시험은 외국인 노동자가 본다. 화면에는 영어가 떠야 하는데 우리가 만드는 문구는
전부 한국어라서, 백엔드가 영어 문장을 고를 수 있도록 문장 대신 **코드와 값**을
함께 보낸다(`src/scoring/messages.py`).

이 방식은 조용히 무너지기 쉽다.
  - 카탈로그의 틀에는 `{maxMb}` 라고 적어 놓고 값은 `max_mb` 로 넘기면,
    화면에 `{maxMb}` 라는 글자가 그대로 뜬다.
  - `warnings`(한국어 문장)에는 넣고 `notices`(코드)에는 안 넣으면, 두 목록의
    차례가 어긋나서 백엔드가 어느 코드가 어느 문장인지 짝지을 수 없다.
  - 문서에는 있는 문구인데 코드를 안 붙이면 그 문구만 영원히 한국어로 남는다.

사람이 눈으로 훑어서는 이런 것을 못 잡는다. 그래서 기계가 셀 수 있는 기준으로 건다.
"""

from __future__ import annotations

import string

import pytest
from fastapi.testclient import TestClient

from src.api import app
from src.scoring.messages import (
    MESSAGE_CATALOG,
    Notice,
    emit,
    join_notices,
    notice,
    notice_or_free_text,
)
from src.scoring.pipeline import score_submission
from src.scoring.schema import (
    ChecklistItem,
    ItemInfo,
    Mode,
    ScoreOptions,
    ScoreRequest,
)

client = TestClient(app)


def _placeholders(template: str) -> set[str]:
    """문장 틀 안의 `{키}` 이름만 뽑는다."""
    return {name for _, name, _, _ in string.Formatter().parse(template) if name}


# ---------------------------------------------------------------------------
# (a) 카탈로그 자체가 앞뒤가 맞는가
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("code", sorted(MESSAGE_CATALOG))
def test_틀에_쓴_이름이_전부_params_에_적혀_있다(code):
    """한국어 틀의 `{키}` 가 params 목록에 없으면 화면에 `{키}` 가 그대로 뜬다."""
    spec = MESSAGE_CATALOG[code]
    missing = _placeholders(spec.template) - set(spec.params)
    assert not missing, f"{code}: 한국어 틀의 {missing} 가 params 에 없다"


@pytest.mark.parametrize("code", sorted(MESSAGE_CATALOG))
def test_영어_초안도_같은_이름만_쓴다(code):
    """영어 초안이 한국어 틀에 없는 이름을 쓰면 백엔드가 그 값을 채울 수 없다."""
    spec = MESSAGE_CATALOG[code]
    missing = _placeholders(spec.english) - set(spec.params)
    assert not missing, f"{code}: 영어 초안의 {missing} 가 params 에 없다"


@pytest.mark.parametrize("code", sorted(MESSAGE_CATALOG))
def test_예시값이_params_와_정확히_짝을_이룬다(code):
    """예시값은 백엔드에 넘길 문서의 재료다. 하나라도 비면 문서가 반쪽이 된다."""
    spec = MESSAGE_CATALOG[code]
    assert set(spec.examples) == set(spec.params), (
        f"{code}: 예시값과 params 의 키가 다르다 "
        f"({set(spec.examples) ^ set(spec.params)})"
    )


@pytest.mark.parametrize("code", sorted(MESSAGE_CATALOG))
def test_예시값으로_문장이_실제로_만들어진다(code):
    """예시값을 끼워 봤을 때 `{키}` 가 남으면 그 코드는 화면에서 깨진다."""
    made = notice(code, **MESSAGE_CATALOG[code].examples)
    assert "{" not in made.message, f"{code}: 못 채운 자리가 남았다 -> {made.message}"


def test_코드_이름은_대문자_스네이크다():
    """코드는 백엔드가 그대로 상수 이름으로 쓴다. 모양이 섞이면 쓰기 어려워진다."""
    bad = [
        code for code in MESSAGE_CATALOG
        if not code.replace("_", "").isupper() or not code.replace("_", "").isalnum()
    ]
    assert bad == [], f"대문자 스네이크가 아닌 코드: {bad}"


def test_params_키는_camelCase다():
    """백엔드(자바)가 쓰는 이름 규칙이다. 밑줄이 섞이면 그쪽에서 다시 바꿔야 한다."""
    bad = []
    for code, spec in MESSAGE_CATALOG.items():
        for key in spec.params:
            if "_" in key or (key and key[0].isupper()):
                bad.append(f"{code}.{key}")
    assert bad == [], f"camelCase 가 아닌 params 키: {bad}"


def test_카탈로그에_없는_코드는_바로_막힌다():
    """오타 난 코드가 응답에 실려 나가면 백엔드가 영어 문장을 못 찾아 화면이 빈다."""
    with pytest.raises(KeyError):
        notice("이런_코드는_없다")


# ---------------------------------------------------------------------------
# (b) HTTP 오류의 detail 이 약속한 모양인가
# ---------------------------------------------------------------------------


def _audio_request(mode: Mode = Mode.WRITING) -> dict:
    """음성을 붙인 요청 하나. 창구가 400 을 돌려주는지 보는 데 쓴다."""
    return {
        "submission_id": "S-400",
        "mode": mode.value,
        "item": {"item_id": "W-001", "prompt": "지각한 이유를 알리는 글을 쓰세요."},
        "answer_text": "",
        "audio": {"url": "https://example.com/a.wav", "format": "wav"},
    }


def test_score_400_의_detail_은_코드_묶음이다():
    """쓰기 답안에 음성을 붙이면 400 이 나가고, detail 은 글자가 아니라 묶음이다."""
    response = client.post("/score", json=_audio_request(Mode.WRITING))
    assert response.status_code == 400

    detail = response.json()["detail"]
    # 셋이 다 있어야 백엔드가 영어 문장을 고르고, 값을 끼우고, 못 고르면 한국어라도 띄운다
    assert set(detail) == {"code", "params", "message"}
    assert detail["code"] == "AUDIO_NOT_ALLOWED_FOR_WRITING"
    assert isinstance(detail["params"], dict)
    assert detail["message"] == MESSAGE_CATALOG[detail["code"]].template


def test_score_503_의_detail_도_같은_모양이다():
    """받아쓰기가 실패한 경우(503)도 400 과 모양이 같아야 화면 한 곳에서 다룰 수 있다."""
    from src.speech.port import SttPort, SttUnavailable

    class 언제나실패(SttPort):
        provider_name = "fake"

        @property
        def model_name(self) -> str:
            return "fake-1"

        def transcribe(self, audio, item_prompt: str = ""):
            raise SttUnavailable.of("STT_LORA_HTTP_ERROR", statusCode=500)

    from src.scoring.schema import AudioInput

    request = ScoreRequest(
        submission_id="S-503",
        mode=Mode.SPEAKING,
        item=ItemInfo(item_id="S-001", prompt="지각한 이유를 말하세요."),
        answer_text="",
        audio=AudioInput(url="https://example.com/a.wav", format="wav"),
    )
    with pytest.raises(SttUnavailable) as caught:
        score_submission(request, stt=언제나실패())

    made = caught.value.notice
    assert made.code == "STT_LORA_HTTP_ERROR"
    assert made.params == {"statusCode": 500}
    assert "500" in made.message


def test_인증_401_의_detail_도_같은_모양이다(monkeypatch):
    """인증 실패도 같은 묶음으로 나가야 프론트가 오류 화면을 하나로 만들 수 있다."""
    monkeypatch.setenv("KTEST_API_KEY", "테스트키는영문숫자로")
    monkeypatch.setenv("KTEST_API_KEY", "abc123")

    response = client.post("/score", json=_audio_request(Mode.WRITING))
    assert response.status_code == 401

    detail = response.json()["detail"]
    assert set(detail) == {"code", "params", "message"}
    assert detail["code"] == "AUTH_API_KEY_MISSING"
    assert detail["params"] == {"header": "X-API-Key"}


# ---------------------------------------------------------------------------
# (c) warnings 와 notices 가 짝을 이루는가
# ---------------------------------------------------------------------------


def _writing_request(**options) -> ScoreRequest:
    """쓰기 답안 하나. LLM 없이 대체 경로로 돌려 경고가 여러 줄 나오게 만든다."""
    return ScoreRequest(
        submission_id="S-1",
        mode=Mode.WRITING,
        item=ItemInfo(
            item_id="W-001",
            prompt="지각한 이유를 반장님께 알리는 글을 쓰세요.",
            checklist=[ChecklistItem(id="c1", description="지각한 이유를 말했는가")],
        ),
        answer_text=(
            "반장님 죄송합니다. 오늘 버스가 늦게 와서 회사에 늦었습니다. "
            "다음부터는 더 일찍 나오겠습니다."
        ),
        options=ScoreOptions(use_llm=False, **options),
    )


def _짝이_맞는지_본다(warnings, notices):
    """두 목록의 길이와 차례, 그리고 문장이 서로 같은지 확인한다."""
    assert len(warnings) == len(notices), (
        f"warnings {len(warnings)}줄 / notices {len(notices)}줄 — 짝이 안 맞는다. "
        f"emit() 을 안 쓰고 warnings 에만 넣은 자리가 있다"
    )
    for text, made in zip(warnings, notices):
        assert text == made.message, f"문장이 다르다: {text!r} != {made.message!r}"
        assert made.code, "코드가 비어 있다"


def test_score_의_warnings_와_notices_가_짝을_이룬다():
    """대체 경로로 도는 채점에서 두 목록이 어긋나지 않는지 본다."""
    result = score_submission(_writing_request())
    assert result.warnings, "이 경로에서는 경고가 나와야 한다"
    _짝이_맞는지_본다(result.warnings, result.notices)


def test_채점_무효_응답에서도_짝을_이룬다():
    """가드에 걸려 무효가 된 답안도 두 목록이 같아야 한다."""
    request = _writing_request()
    # 한국어가 아닌 답안은 가드 A 에 걸려 채점 무효가 된다
    request = request.model_copy(update={"answer_text": "hello world this is english only"})
    result = score_submission(request)

    assert result.overall_score is None, "무효 답안은 점수가 없어야 한다"
    _짝이_맞는지_본다(result.warnings, result.notices)
    # 무효 사유는 겉 문구 안에 안쪽 사유가 코드째로 들어 있어야 한다
    wrap = [n for n in result.notices if n.code == "VALIDITY_INVALID_WRAP"]
    assert wrap, "무효 사유의 겉 문구가 없다"
    assert wrap[0].params["reasonNotice"]["code"].startswith("VALIDITY_")


def test_finalize_의_warnings_와_notices_가_짝을_이룬다():
    """최종 등급 산출에서도 두 목록이 어긋나지 않는지 본다."""
    from src.scoring.finalize import finalize_session
    from src.scoring.schema import ExpectedItem, FinalizeRequest

    scored = score_submission(_writing_request())
    request = FinalizeRequest(
        session_id="E-1",
        expected_items=[
            ExpectedItem(item_id="W-001", mode=Mode.WRITING),
            ExpectedItem(item_id="W-002", mode=Mode.WRITING),
        ],
        items=[{
            "item_id": scored.item_id,
            "mode": scored.mode,
            "overall_score": scored.overall_score,
            "overall_grade": scored.overall_grade,
            "subscores": [s.model_dump() for s in scored.subscores],
            "warnings": scored.warnings,
            "notices": [n.model_dump() for n in scored.notices],
            "meta": scored.meta.model_dump(),
        }],
    )
    result = finalize_session(request)
    assert result.warnings, "문항이 빠졌으므로 경고가 나와야 한다"
    _짝이_맞는지_본다(result.warnings, result.notices)


def test_generate_items_의_warnings_와_notices_가_짝을_이룬다():
    """문항 생성 쪽도 같은 규칙을 지키는지 본다(LLM 없이 가짜 응답으로)."""
    from src.generation.generate import generate_items
    from src.generation.schema import GenerateItemsRequest

    class 가짜클라이언트:
        model_name = "fake-gen"

        def generate_json(self, *args, **kwargs):
            # 모델이 아무것도 못 만든 상황. 경고가 한 줄 나온다
            return {"items": []}

    request = GenerateItemsRequest(
        document_id="D-1",
        document_text="안전모는 반드시 착용해야 한다. " * 40,
    )
    result = generate_items(request, client=가짜클라이언트())
    assert result.warnings, "문항이 하나도 안 나왔으므로 경고가 있어야 한다"
    _짝이_맞는지_본다(result.warnings, result.notices)


def test_emit_은_두_목록에_한꺼번에_쌓는다():
    """입구를 하나로 좁혀 둔 덕분에 한쪽만 채워지는 일이 없다."""
    warnings: list[str] = []
    notices: list[Notice] = []
    emit(warnings, notices, "AUDIO_FILE_TOO_LARGE", actualMb=25.3, maxMb=20)

    assert len(warnings) == len(notices) == 1
    assert warnings[0] == notices[0].message
    assert notices[0].params == {"actualMb": 25.3, "maxMb": 20}


def test_여러_안내를_한_줄로_묶어도_안쪽_코드가_남는다():
    """영역 note 는 자리가 하나뿐이라 여러 안내를 이어 붙인다. 코드는 잃지 않아야 한다."""
    묶음 = join_notices([
        notice("SUBSCORE_CHECKLIST_MISSING"),
        notice("SUBSCORE_FEATURE_EXCLUDED", featureId="response_length"),
    ])
    assert 묶음.code == "SUBSCORE_NOTE_LIST"
    assert [one["code"] for one in 묶음.params["items"]] == [
        "SUBSCORE_CHECKLIST_MISSING",
        "SUBSCORE_FEATURE_EXCLUDED",
    ]
    # 하나뿐이면 굳이 감싸지 않는다(백엔드가 다루기 쉽게)
    하나 = join_notices([notice("SUBSCORE_CHECKLIST_MISSING")])
    assert 하나.code == "SUBSCORE_CHECKLIST_MISSING"
    assert join_notices([]) is None


def test_LLM_자유문에는_전용_코드가_붙는다():
    """LLM 이 그때그때 쓴 문장에는 번역할 고정 문구가 없다는 표시가 필요하다."""
    made = notice_or_free_text(None, "답안에서 지각한 이유를 밝혔다.")
    assert made.code == "LLM_FREE_TEXT"
    assert made.params["text"] == "답안에서 지각한 이유를 밝혔다."
    # 코드가 있으면 그것을 그대로 쓴다
    assert notice_or_free_text("CITATION_EMPTY", "무시됨").code == "CITATION_EMPTY"


# ---------------------------------------------------------------------------
# (d) 문서에 실린 문구가 전부 코드로 옮겨졌는가
# ---------------------------------------------------------------------------


def test_문서에_실린_사용자_대면_문구가_전부_코드로_있다():
    """`outputs/api_messages_ko.md` 는 백엔드에 넘긴 번역 대상 목록이다.

    거기 실린 문구인데 코드가 없으면, 그 문구만 화면에 영원히 한국어로 남는다.
    문서의 표에서 한국어 문구를 긁어 카탈로그와 대조한다.
    (7절 '내부용' 은 응시자가 아니라 운영자에게 주는 안내라 대조 대상이 아니다)
    """
    import re
    from pathlib import Path

    doc = Path(__file__).resolve().parent.parent / "outputs" / "api_messages_ko.md"
    if not doc.exists():
        pytest.skip("문구 목록 문서가 없다")

    text = doc.read_text(encoding="utf-8")
    # 7절(내부용)부터는 코드화 대상이 아니므로 잘라낸다
    cut = text.find("## 7. 내부용")
    if cut != -1:
        text = text[:cut]
    # 6절(/health·/features 라벨)도 이번 범위 밖이다
    cut = text.find("## 6. GET /health")
    if cut != -1:
        text = text[:cut]

    # 표 안에서 백틱으로 감싼 한국어 문구만 뽑는다
    quoted = re.findall(r"`([^`]+)`", text)
    문구들 = [
        q for q in quoted
        # 한글이 들어 있고, 파일 경로나 필드 이름이 아닌 것만 문구로 본다
        if re.search(r"[가-힣]", q)
        and ".py:" not in q
        and "\\" not in q
        and len(q) > 10
    ]
    assert 문구들, "문서에서 문구를 하나도 못 뽑았다(문서 형식이 바뀌었는지 확인할 것)"

    # 카탈로그의 한국어 틀을 '변수 자리를 지운 조각' 목록으로 만들어 둔다
    # 변수가 끼는 자리(`{…}`)는 문서와 코드가 적는 방식이 달라서 그대로 대조할 수 없다
    # (문서는 `{…}`, 코드는 `{maxMb}`). 그래서 변수 자리를 잘라내고 남은 **글자 조각**끼리
    # 견준다. 조각 하나라도 카탈로그 어딘가에 그대로 있으면 옮겨진 것으로 본다.
    최소조각 = 3
    조각들 = []
    for spec in MESSAGE_CATALOG.values():
        for piece in re.split(r"\{[^}]*\}", spec.template):
            piece = piece.strip()
            if len(piece) >= 최소조각:
                조각들.append(piece)

    def 카탈로그에_있나(문구: str) -> bool:
        """문구의 변수 자리를 지운 조각이 카탈로그 어딘가에 그대로 있는지."""
        for piece in re.split(r"\{[^}]*\}|…", 문구):
            piece = piece.strip()
            if len(piece) < 최소조각:
                continue
            if any(piece in 조각 for 조각 in 조각들):
                return True
        return False

    빠진것 = [문구 for 문구 in 문구들 if not 카탈로그에_있나(문구)]
    assert 빠진것 == [], (
        f"문서에는 있는데 코드가 없는 문구 {len(빠진것)}개: {빠진것[:5]}"
    )


def test_코드_개수가_문서의_집계보다_적지_않다():
    """문서 부록의 집계(약 118개 + 근거 문구 22개)보다 코드가 적으면 빠뜨린 것이다."""
    # 문서 집계: 오류/상태 약 118 + 체크리스트 근거 11 + 가드·보정 근거 11 = 140
    assert len(MESSAGE_CATALOG) >= 140, (
        f"코드가 {len(MESSAGE_CATALOG)}개뿐이다. 문서의 집계(140)보다 적다"
    )


# ---------------------------------------------------------------------------
# (e) 백엔드에 넘긴 문서가 코드와 어긋나지 않는가
# ---------------------------------------------------------------------------


def test_백엔드_문서가_지금_코드와_같다():
    """`outputs/api_message_codes.md` 는 카탈로그에서 뽑아 만든 문서다.

    코드를 고치고 문서를 다시 안 뽑으면, 백엔드는 옛날 문서를 보고 영어 문장을 만든다.
    그러면 화면에 엉뚱한 문구가 뜨는데 우리 쪽에서는 아무 일도 없어 보인다.
    그래서 '지금 뽑은 것'과 '파일에 있는 것'이 같은지 여기서 못 박는다.

    이 테스트가 깨지면 고칠 것은 문서가 아니라 명령 한 줄이다.

        python scripts/export_message_codes.py
    """
    import importlib.util
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    doc = root / "outputs" / "api_message_codes.md"
    assert doc.exists(), "백엔드 전달 문서가 없다. export_message_codes.py 를 돌릴 것"

    # 스크립트를 파일 경로로 직접 불러온다(scripts 는 패키지가 아니다)
    spec = importlib.util.spec_from_file_location(
        "_export_message_codes", root / "scripts" / "export_message_codes.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    지금 = module.build_markdown()
    파일 = doc.read_text(encoding="utf-8")
    assert 지금 == 파일, (
        "코드와 문서가 어긋났다. `python scripts/export_message_codes.py` 를 다시 돌릴 것"
    )


def test_문서에_모든_코드가_한_번씩_실려_있다():
    """엔드포인트 칸을 잘못 적어 표 어디에도 안 실린 코드가 없는지 본다."""
    from pathlib import Path

    doc = Path(__file__).resolve().parent.parent / "outputs" / "api_message_codes.md"
    text = doc.read_text(encoding="utf-8")

    빠진것 = [code for code in MESSAGE_CATALOG if f"| `{code}`" not in text]
    assert 빠진것 == [], f"문서 표에 안 실린 코드: {빠진것}"
