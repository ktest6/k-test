"""세탁 탐지기 판정 규칙 회귀 테스트.

세탁 탐지기는 "사람 라벨이 학습자의 실수를 몰래 고쳐 놓았는가"를 가려낸다.
판정이 한 칸만 어긋나도 **좋은 라벨(오류를 그대로 적은 줄)을 버리는 사고**가 나므로,
가짜 받아쓰기 데이터를 넣어 규칙 하나하나를 못 박아 둔다.

여기서 확인하는 것 넷:
  ① 표 세기      — 증인 2명 이상이 같은 대안을 적고 라벨 지지보다 많아야 의심
  ② 2:2 보류     — 반반으로 갈리면 판정하지 않고 남긴다
  ③ 방향 판정    — 라벨이 오류를 살린 자리는 절대 세탁으로 표시하지 않는다
  ④ 띄어쓰기 정규화 — 띄어쓰기·문장부호만 다른 자리는 불일치로 세지 않는다

네트워크도 GPU도 쓰지 않는다. Kiwi 자리에는 답을 아는 가짜 판정기를 끼운다.

실행: .venv\\Scripts\\python.exe -m pytest tests -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "speech_lab"))

from launder_detect import (  # noqa: E402
    count_votes,
    emit_selection,
    form_over,
    is_filler,
    item_code,
    judge_direction,
    judge_pair,
    load_witness_transcripts,
    merge_sites,
    summarize,
    tokenize,
    witness_records,
)


# ── 가짜 표준형 판정기 ───────────────────────────────────────────────────────
class FakeScorer:
    """Kiwi 대신 끼우는 가짜 판정기. '어느 글이 더 표준 한국어다운가'를 답으로 준다.

    미리 적어 둔 표에서 점수를 찾고, 표에 없는 글은 0점으로 본다.
    Kiwi 를 실제로 부르면 테스트가 형태소 사전 판올림에 흔들리므로 여기서는 끼워 넣는다.
    """

    def __init__(self, table: dict[str, float]):
        self.table = table

    def score(self, sentence: str) -> float:
        for key, value in self.table.items():
            if key in sentence:
                return value
        return 0.0


def transcripts(**kwargs) -> dict[str, str]:
    """증인 이름 → 받아쓴 글. 테스트에서 읽기 쉬우라고 만든 도우미."""
    return dict(kwargs)


# ── ④ 띄어쓰기·문장부호 정규화 ──────────────────────────────────────────────
def test_어절_쪼개기는_문장부호를_떼어_낸다():
    assert tokenize("집들은 참 좋은데, 너무 비쌌다.") == ["집들은", "참", "좋은데", "너무", "비쌌다"]


def test_띄어쓰기만_다르면_불일치로_세지_않는다():
    label = tokenize("관련 있는 책을 골라요")
    hyp = tokenize("관련있는 책을 골라요")
    # '관련 있는' 과 '관련있는' 은 어절 수가 달라 difflib 은 어긋났다고 보지만,
    # 붙여 놓으면 같은 글자라 기록으로 남기지 않아야 한다
    assert witness_records(label, hyp, "w1") == []


def test_문장부호만_다르면_불일치로_세지_않는다():
    label = tokenize("네, 그렇습니다.")
    hyp = tokenize("네 그렇습니다")
    assert witness_records(label, hyp, "w1") == []


def test_진짜_다른_말은_불일치로_잡는다():
    label = tokenize("자신의 관심사와 요구를")
    hyp = tokenize("자신의 과심사와 요구를")
    recs = witness_records(label, hyp, "w1")
    assert len(recs) == 1
    assert (recs[0].label_form, recs[0].witness_form) == ("관심사와", "과심사와")


# ── 자리 묶기 ────────────────────────────────────────────────────────────────
def test_겹치는_불일치는_한_자리로_묶인다():
    label = tokenize("가 나 다 라 마")
    # 증인1 은 '다'만, 증인2 는 '다 라' 를 통째로 다르게 적었다 → 같은 자리다
    recs = (witness_records(label, tokenize("가 나 더 라 마"), "w1")
            + witness_records(label, tokenize("가 나 더 러 마"), "w2"))
    groups = merge_sites(recs)
    assert len(groups) == 1
    start, end, bag = groups[0]
    assert (start, end) == (2, 4)
    assert len(bag) == 2


def test_떨어진_불일치는_따로_센다():
    label = tokenize("가 나 다 라 마")
    recs = witness_records(label, tokenize("거 나 다 라 머"), "w1")
    groups = merge_sites(recs)
    assert len(groups) == 2


def test_자리에서_손대지_않은_어절은_라벨_것으로_채운다():
    """증인이 자리의 일부만 다르게 적었어도, 자리 전체를 같은 눈금으로 견줘야 한다."""
    label = tokenize("가 나 다 라 마")
    recs = witness_records(label, tokenize("가 나 더 라 마"), "w1")
    # 자리는 2~4번 어절인데 이 증인은 2번만 바꿨다 → '더' + 라벨의 '라'
    assert form_over(recs, label, 2, 4) == "더라"


# ── ① 표 세기 ────────────────────────────────────────────────────────────────
def test_표_세기는_같은_형태끼리_모은다():
    vote = count_votes("관심사와", {"a": "과심사와", "b": "과심사와", "c": "관심사와"})
    assert vote.alt_form == "과심사와"
    assert vote.alt_voters == ["a", "b"]
    assert vote.label_voters == ["c"]


def test_모두_라벨과_같으면_볼_것이_없다():
    assert count_votes("관심사와", {"a": "관심사와", "b": "관심사와"}) is None


def test_대안이_여럿이면_표가_많은_쪽이_대표가_된다():
    vote = count_votes("가", {"a": "나", "b": "나", "c": "다"})
    assert vote.alt_form == "나" and len(vote.alt_voters) == 2


def test_한_명만_다르게_적으면_세탁이_아니다():
    """증인 하나의 잘못 들음으로 좋은 라벨을 버리면 안 된다."""
    v = judge_pair(
        "t1", "자신의 관심사와 요구를",
        transcripts(a="자신의 과심사와 요구를", b="자신의 관심사와 요구를",
                    c="자신의 관심사와 요구를", d="자신의 관심사와 요구를"),
        scorer=FakeScorer({"과심사와": -50.0, "관심사와": -10.0}),
    )
    assert v.verdict == "keep"
    assert v.sites[0]["자리판정"] == "약함"


def test_증인_다수가_같은_대안이면_세탁으로_본다():
    v = judge_pair(
        "t2", "자신의 관심사와 요구를",
        transcripts(a="자신의 과심사와 요구를", b="자신의 과심사와 요구를",
                    c="자신의 과심사와 요구를", d="자신의 관심사와 요구를"),
        scorer=FakeScorer({"과심사와": -50.0, "관심사와": -10.0}),
    )
    assert v.verdict == "suspect"
    site = v.sites[0]
    assert (site["증인표"], site["라벨표"]) == (3, 1)
    assert site["라벨형태"] == "관심사와" and site["증인형태"] == "과심사와"
    # 근거 없는 판정은 만들지 않는다 — 누가 무엇을 지지했는지가 남아야 한다
    assert site["증인들"] == ["a", "b", "c"] and site["라벨지지"] == ["d"]


# ── ② 2:2 동점 보류 ──────────────────────────────────────────────────────────
def test_반반으로_갈리면_보류하고_남긴다():
    v = judge_pair(
        "t3", "자신의 관심사와 요구를",
        transcripts(a="자신의 과심사와 요구를", b="자신의 과심사와 요구를",
                    c="자신의 관심사와 요구를", d="자신의 관심사와 요구를"),
        scorer=FakeScorer({"과심사와": -50.0, "관심사와": -10.0}),
    )
    assert v.verdict == "hold"
    assert v.sites[0]["자리판정"] == "보류"
    assert "2:2" in v.sites[0]["사유"]


# ── ③ 방향 판정 ──────────────────────────────────────────────────────────────
def test_라벨이_오류를_살린_자리는_세탁이_아니다():
    """라벨 '채위'(학습자가 실제 낸 오류) vs 증인들 '책이'(증인이 고쳐 적음).

    이건 라벨이 잘한 것이다. 여기서 세탁이라고 하면 좋은 라벨을 버리게 된다.
    """
    v = judge_pair(
        "t4", "채위 책상 지휘했다",
        transcripts(a="책이 책상 지휘했다", b="책이 책상 지휘했다",
                    c="책이 책상 지휘했다", d="채위 책상 지휘했다"),
        scorer=FakeScorer({"채위": -60.0, "책이": -15.0}),
    )
    assert v.verdict == "keep"
    assert v.sites[0]["자리판정"] == "역방향"


def test_제시문만으로는_라벨을_버리지_않는다():
    """제시문이 라벨 편이어도 Kiwi 확인을 못 받으면 보류한다.

    8/8 gold 100건 실측에서 '라벨=제시문인데 증인들이 다르게 적음'으로 잡은 낭독
    4건이 전부 헛detection 이었다. 낭독은 대개 제대로 읽으므로, 그런 자리의 흔한
    원인은 세탁이 아니라 **증인들이 잘못 들은 것**이기 때문이다.
    """
    v = judge_pair(
        "t5", "집들은 참 좋은데 너무 비싸다",
        transcripts(a="집들은 참 좋은데 너무 비쌌다", b="집들은 참 좋은데 너무 비쌌다",
                    c="집들은 참 좋은데 너무 비쌌다", d="집들은 참 좋은데 너무 비싸다"),
        prompt="집들은 참 좋은데 너무 비싸다.",
        scorer=None,
    )
    assert v.verdict == "hold"
    assert "제시문은 라벨 편" in v.sites[0]["사유"]


def test_제시문과_Kiwi_가_함께_가리키면_세탁이다():
    v = judge_pair(
        "t5b", "집들은 참 좋은데 너무 비싸다",
        transcripts(a="집들은 참 좋은데 너무 비쌌다", b="집들은 참 좋은데 너무 비쌌다",
                    c="집들은 참 좋은데 너무 비쌌다", d="집들은 참 좋은데 너무 비싸다"),
        prompt="집들은 참 좋은데 너무 비싸다.",
        scorer=FakeScorer({"비쌌다": -60.0, "비싸다": -10.0}),
    )
    assert v.verdict == "suspect"
    assert "제시문도 라벨 편" in v.sites[0]["사유"]


def test_라벨이_제시문과_이미_다르면_오류를_살린_자리다():
    """제시문에도 없고 증인 형태도 아닌 라벨 = 라벨이 이미 오류를 적어 둔 것이다."""
    v = judge_pair(
        "t5c", "집들은 참 좋은데 너무 비쌌다",
        transcripts(a="집들은 참 좋은데 너무 비싼다", b="집들은 참 좋은데 너무 비싼다",
                    c="집들은 참 좋은데 너무 비싼다", d="집들은 참 좋은데 너무 비쌌다"),
        prompt="집들은 참 좋은데 너무 비싸다.",
        # Kiwi 가 라벨 편을 들어도 제시문 거부권이 먼저다
        scorer=FakeScorer({"비싼다": -60.0, "비쌌다": -10.0}),
    )
    assert v.verdict == "keep"
    assert v.sites[0]["자리판정"] == "역방향"
    assert "이미 다르다" in v.sites[0]["사유"]


def test_제시문이_증인_편이면_라벨이_오류를_살린_것이다():
    v = judge_pair(
        "t6", "집들은 참 좋은데 너무 비쌌다",
        transcripts(a="집들은 참 좋은데 너무 비싸다", b="집들은 참 좋은데 너무 비싸다",
                    c="집들은 참 좋은데 너무 비싸다", d="집들은 참 좋은데 너무 비쌌다"),
        prompt="집들은 참 좋은데 너무 비싸다.",
        scorer=None,
    )
    assert v.verdict == "keep"
    assert v.sites[0]["자리판정"] == "역방향"


def test_라벨이_군말을_지운_것은_세탁이다():
    """사람 라벨러가 '어'·'음' 을 빼고 적는 일이 실제로 있었다(8/4 감사 실측)."""
    v = judge_pair(
        "t7", "그래서 저는 학교에 갔어요",
        transcripts(a="그래서 어 저는 학교에 갔어요", b="그래서 어 저는 학교에 갔어요",
                    c="그래서 어 저는 학교에 갔어요", d="그래서 저는 학교에 갔어요"),
        scorer=None,   # Kiwi 없이도 군말만으로 판정돼야 한다
    )
    assert v.verdict == "suspect"
    assert "군말" in v.sites[0]["사유"]


def test_라벨에만_군말이_있으면_라벨이_살린_것이다():
    v = judge_pair(
        "t8", "그래서 어 저는 학교에 갔어요",
        transcripts(a="그래서 저는 학교에 갔어요", b="그래서 저는 학교에 갔어요",
                    c="그래서 저는 학교에 갔어요", d="그래서 어 저는 학교에 갔어요"),
        scorer=None,
    )
    assert v.verdict == "keep"
    assert v.sites[0]["자리판정"] == "역방향"


def test_근거가_없으면_보류한다():
    """제시문도 없고 군말도 아니고 Kiwi 도 없으면 판정하지 않고 남긴다."""
    v = judge_pair(
        "t9", "가나다 마바사",
        transcripts(a="가나다 마바자", b="가나다 마바자", c="가나다 마바자",
                    d="가나다 마바사"),
        scorer=None,
    )
    assert v.verdict == "hold"
    assert v.sites[0]["자리판정"] == "보류"


def test_점수_차가_작으면_보류한다():
    """둘 다 멀쩡한 한국어일 때는 Kiwi 로 가릴 수 없다 — 보수적으로 남긴다."""
    direction, why = judge_direction(
        tokenize("나는 고기 요리만 시키고"), 2, 3, "요리만", "요리를",
        prompt_norm=None, scorer=FakeScorer({"요리만": -35.0, "요리를": -34.0}),
        margin=1.0,
    )
    assert direction == "불명"
    assert "보류" in why


def test_군말_판정():
    assert is_filler("어") and is_filler("음") and is_filler("어어")
    assert not is_filler("어제") and not is_filler("") and not is_filler("그거")


# ── 증언할 수 없는 증인 빼기 ────────────────────────────────────────────────
def test_빈_전사를_낸_증인은_표에서_뺀다():
    """아무 말도 못 적은 증인을 라벨 편으로 세면 세탁이 조용히 묻힌다."""
    v = judge_pair(
        "t10", "자신의 관심사와 요구를",
        transcripts(a="자신의 과심사와 요구를", b="자신의 과심사와 요구를",
                    c="", d="자신의 관심사와 요구를"),
        scorer=FakeScorer({"과심사와": -50.0, "관심사와": -10.0}),
    )
    assert v.skipped == {"c": "빈 전사"}
    assert v.verdict == "suspect"          # 2:1 이므로 의심
    assert v.sites[0]["증인표"] == 2 and v.sites[0]["라벨표"] == 1


def test_폭주한_증인은_표에서_뺀다():
    """같은 말을 끝없이 되풀이한 증인은 자리 하나를 통째로 삼켜 판정을 막는다."""
    runaway = " ".join(["8"] * 100)
    v = judge_pair(
        "t11", "자신의 관심사와 요구를",
        transcripts(a="자신의 과심사와 요구를", b="자신의 과심사와 요구를",
                    c=runaway, d="자신의 관심사와 요구를"),
        scorer=FakeScorer({"과심사와": -50.0, "관심사와": -10.0}),
    )
    assert "폭주" in v.skipped["c"]
    assert v.verdict == "suspect"


def test_증언할_증인이_모자라면_보류한다():
    v = judge_pair("t12", "가나다", transcripts(a="가나자", b="", c="", d=""),
                   scorer=None)
    assert v.verdict == "hold"


def test_전원이_같게_적으면_남긴다():
    v = judge_pair(
        "t13", "자신의 관심사와 요구를",
        transcripts(a="자신의 관심사와 요구를", b="자신의 관심사와 요구를",
                    c="자신의 관심사와, 요구를", d="자신의 관심사와 요구를"),
        scorer=None,
    )
    assert v.verdict == "keep" and v.sites == []


# ── 같은 입력이면 같은 답 ────────────────────────────────────────────────────
def test_같은_입력이면_같은_판정이_나온다():
    """채점 신뢰도의 전제다. 증인 이름 순서가 바뀌어도 답이 흔들리면 안 된다."""
    args = ("t14", "자신의 관심사와 요구를")
    heard = {"d": "자신의 관심사와 요구를", "b": "자신의 과심사와 요구를",
             "a": "자신의 과심사와 요구를", "c": "자신의 과심사와 요구를"}
    scorer = FakeScorer({"과심사와": -50.0, "관심사와": -10.0})
    first = judge_pair(*args, dict(heard), scorer=scorer).to_dict()
    second = judge_pair(*args, dict(reversed(list(heard.items()))), scorer=scorer).to_dict()
    assert first == second


# ── 파일 읽기·쓰기 ───────────────────────────────────────────────────────────
def test_두_가지_전사_파일_형식을_모두_읽는다(tmp_path):
    """launder_transcribe 는 `text`, audition 은 `hyp` 로 적는다. 둘 다 받아야 한다."""
    p = tmp_path / "w.jsonl"
    p.write_text(
        json.dumps({"id": "x1", "model": "fw(small)", "text": "가나"}, ensure_ascii=False)
        + "\n"
        + json.dumps({"id": "x1", "model": "owsm-ctc-v4", "hyp": "가다"}, ensure_ascii=False)
        + "\n"
        + json.dumps({"id": "x1", "model": "탈락자", "hyp": "무시"}, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    got = load_witness_transcripts([str(p)], keep={"fw(small)", "owsm-ctc-v4"})
    assert got == {"x1": {"fw(small)": "가나", "owsm-ctc-v4": "가다"}}


def test_문항_코드_뽑기():
    assert item_code("00067-F-91-VI-A-LAR010-0004411") == "LAR010"
    assert item_code("00131-F-99-ID-B-ATQ027-0033354") == "ATQ027"
    assert item_code("이상한이름") == ""


def test_정제_목록은_세탁_의심만_뺀다(tmp_path):
    """보류(hold)와 이상 없음(keep)은 반드시 남는다 — 이 도구의 존재 이유다."""
    src = tmp_path / "v1.json"
    src.write_text(json.dumps({"LAR": [["a", "가"], ["b", "나"]], "ATQ": [["c", "다"]]},
                              ensure_ascii=False), encoding="utf-8")
    verdicts = [
        judge_pair("a", "가", transcripts(x="가", y="가")),      # keep
        judge_pair("b", "나", transcripts(x="", y="")),          # hold (증인 부족)
    ]
    verdicts[0].verdict = "suspect"                              # a 만 세탁이라 치자
    out = tmp_path / "v2.json"
    info = emit_selection(str(src), verdicts, str(out))

    kept = json.loads(out.read_text(encoding="utf-8"))
    assert kept == {"LAR": [["b", "나"]], "ATQ": [["c", "다"]]}
    assert info["제외"] == {"LAR": 1, "ATQ": 0}
    assert info["제외비율"]["LAR"] == 0.5


def test_요약_숫자가_맞는다():
    verdicts = [judge_pair("a", "가", transcripts(x="가", y="가")) for _ in range(3)]
    verdicts[0].verdict = "suspect"
    stats = summarize(verdicts)
    assert stats["총쌍수"] == 3
    assert stats["판정"] == {"suspect": 1, "hold": 0, "keep": 2}


# ── 진짜 Kiwi 로도 방향이 맞는가 ─────────────────────────────────────────────
def test_실제_Kiwi_로도_표준형을_가려낸다():
    """가짜 판정기가 아니라 실제 Kiwi 를 끼워도 같은 방향이 나오는지 본다."""
    pytest.importorskip("kiwipiepy")
    from launder_detect import KiwiStandardness

    scorer = KiwiStandardness()
    # 라벨 '관심사와'(표준) vs 증인 '과심사와'(오류) → 라벨이 고쳐 적은 것
    direction, _ = judge_direction(
        tokenize("자신의 관심사와 지적 요구를 고려하는 것"), 1, 2, "관심사와", "과심사와",
        prompt_norm=None, scorer=scorer, margin=1.0,
    )
    assert direction == "세탁방향"

    # 반대로 라벨이 오류형이면 역방향이어야 한다 — 이 줄은 절대 버리면 안 된다
    direction, _ = judge_direction(
        tokenize("자신의 과심사와 지적 요구를 고려하는 것"), 1, 2, "과심사와", "관심사와",
        prompt_norm=None, scorer=scorer, margin=1.0,
    )
    assert direction == "역방향"
