"""⑧ 감사 회수본 병합 규약 회귀 테스트.

팀원 4명이 귀로 듣고 고친 시트를 한 덩이로 모을 때, **무엇을 '진짜 교정'으로 셀지**의
규칙이 이 파일에 못 박혀 있다. 이 규칙이 한 칸만 흔들려도 감사자별 정밀도가
통째로 달라지므로(교정으로 세느냐 마느냐가 곧 분모다), 가짜 시트를 만들어 확인한다.

여기서 확인하는 것:
  ① 빈칸 / `?` 한 글자   — 못 알아들었다는 뜻이므로 원본 유지, 교정으로 세지 않는다
  ② `(?)` 표시           — 표시만 떼고 교정은 인정한다
  ③ 낱자모 잔존          — 낱자모는 지우고 교정은 인정한다
  ④ 메모 열              — `ㅇ` 은 버리고 나머지는 note 로 보존, '소리 x' 는 표시로
  ⑤ 시트 머리글 자동 찾기 — 첫 줄이 제목인 시트도 읽는다
  ⑥ 같은 발음 되돌림      — 소리가 같은 어절은 원본으로 되돌린다 (g2pkk 없으면 건너뜀)
  ⑦ 감사자별 정밀도 셈법  — 지지/(지지+반대), 보류는 분모에서 뺀다

네트워크도 GPU도 쓰지 않는다. ⑥만 g2pkk 가 있는 환경에서 돌고 없으면 skip 된다.

실행: .venv\\Scripts\\python.exe -m pytest tests/test_audit_merge.py -q
"""

from __future__ import annotations

import csv
import io
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "speech_lab"))

from audit_merge import (  # noqa: E402
    RETURN_FILES,
    build_pronunciation_judge,
    clean_cell,
    merge_auditor,
    norm_cmp,
    read_note,
    read_sheet,
    revert_same_pronunciation,
    score_auditors,
)


# ── 가짜 시트 만들기 ─────────────────────────────────────────────────────────
def make_csv(rows: list[list[str]], title: str = "") -> bytes:
    """감사 시트 모양의 CSV 를 만든다. `title` 을 주면 첫 줄이 제목인 시트가 된다.

    백예나 시트가 실제로 이 모양(첫 줄 제목 + 둘째 줄 머리글)이라 함께 확인한다.
    """
    buf = io.StringIO(newline="")
    w = csv.writer(buf, lineterminator="\n")
    if title:
        w.writerow([title])
    w.writerow(["번호", "파일명", "사람전사(실제 들리는 대로 고치세요)", "진행도"])
    for r in rows:
        w.writerow(r)
    return buf.getvalue().encode("utf-8")


@pytest.fixture
def fake_audit(tmp_path: Path):
    """가짜 감사 한 벌(원본 꾸러미 zip + 회수본 csv + 배포 목록)을 차려 놓는다.

    실제 폴더 구조를 그대로 흉내 낸다 — 원본 전사는 배포 꾸러미(zip) 안의 시트에
    들어 있고, 감사자가 고친 것은 따로 회수한 csv 다.
    """
    auditor = "김도영"          # RETURN_FILES 에 있는 이름이어야 파일명이 맞는다
    files = [f"T{i:03d}.wav" for i in range(1, 7)]

    # 원본 시트 — 감사자가 눈으로 본 '정답지'
    original = [
        ["1", files[0], "원본 전사 하나"],
        ["2", files[1], "원본 전사 둘"],
        ["3", files[2], "원본 전사 셋"],
        ["4", files[3], "원본 전사 넷"],
        ["5", files[4], "원본 전사 다섯"],
        ["6", files[5], "원본 전사 여섯"],
    ]
    zip_path = tmp_path / f"{auditor}_500건.zip"
    with zipfile.ZipFile(zip_path, "w") as z:
        z.writestr(f"{auditor}/감사시트_교정.csv", make_csv(original))
        for name in files:
            z.writestr(f"{auditor}/wav/{name}", b"RIFF____fake")

    # 회수본 — 감사자가 고쳐 돌려준 것
    returned = [
        ["1", files[0], "", "ㅇ"],                       # 빈칸 → 원본 유지
        ["2", files[1], "?", "ㅇ"],                      # ? 한 글자 → 원본 유지
        ["3", files[2], "원본(?) 전사 셋 고침", "ㅇ"],    # (?) → 표시만 떼고 교정 인정
        ["4", files[3], "원본 전사ㅁ 넷 고침", "ㅇ"],     # 낱자모 → 지우고 교정 인정
        ["5", files[4], "원본 전사 다섯", "소리 x"],      # 메모 → note 보존 + silent
        ["6", files[5], "원본 전사 여섯", "마지막 부분"],  # 메모만 있고 교정은 없음
    ]
    csv_path = tmp_path / RETURN_FILES[auditor]
    csv_path.write_bytes(make_csv(returned, title="감사시트_교정"))

    manifest = {name[:-4]: {"id": name[:-4], "task": "ATQ", "source": "505",
                            "auditor": auditor, "duration": 3.0}
                for name in files}
    return {"dir": tmp_path, "auditor": auditor, "manifest": manifest, "files": files}


# ── ① ② ③ 칸 정리 규약 ──────────────────────────────────────────────────────
def test_빈칸과_물음표는_교정으로_세지_않는다():
    """못 알아들었다는 표시를 '원본이 틀렸다'로 둔갑시키면 안 된다."""
    for cell in ("", "   ", "?"):
        text, flags, accept = clean_cell(cell)
        assert accept is False, f"{cell!r} 를 교정으로 인정해 버렸다"
        assert flags == ["unclear"]
        assert text == ""


def test_물음표괄호는_표시만_떼고_교정을_인정한다():
    """'이렇게 들리는데 자신 없다'는 자리 — 내용은 살리고 표시만 남긴다."""
    text, flags, accept = clean_cell("저는 학교(?)에 가요")
    assert accept is True
    assert "uncertain" in flags
    assert text == "저는 학교에 가요"


def test_낱자모는_지우고_교정을_인정한다():
    """타자 치다 만 흔적(ㅃ 같은 것)은 받아쓰기 모델이 절대 내지 않는 글자다."""
    text, flags, accept = clean_cell("잃어ㅃ려서 슬퍼요")
    assert accept is True
    assert "stray_jamo" in flags
    assert text == "잃어려서 슬퍼요"


def test_표시를_떼고_나면_비는_칸도_못_알아들은_것으로_본다():
    """`(?)` 만 덜렁 적힌 칸은 결국 '모르겠다'와 같다."""
    text, flags, accept = clean_cell("(?)")
    assert accept is False
    assert "unclear" in flags and "uncertain" in flags
    assert text == ""


# ── ④ 메모 열 ───────────────────────────────────────────────────────────────
def test_진행도_ㅇ은_버리고_메모는_보존한다():
    """`ㅇ` 은 '여기까지 했다'는 진행 표시일 뿐 내용이 아니다."""
    assert read_note(["1", "a.wav", "전사", "ㅇ"]) == ("", [])
    note, flags = read_note(["1", "a.wav", "전사", "마지막 부분"])
    assert note == "마지막 부분" and flags == []


def test_소리_x_메모는_표시를_남긴다():
    """소리가 안 나는 파일은 받아쓰기 자체가 무의미하므로 따로 표시해 둔다."""
    note, flags = read_note(["1", "a.wav", "전사", "소리 x"])
    assert note == "소리 x" and flags == ["silent"]


# ── ⑤ 시트 읽기 ─────────────────────────────────────────────────────────────
def test_첫줄이_제목인_시트도_읽는다():
    """머리글을 줄 번호로 찍지 않고 '번호' 칸을 찾아 잡는다."""
    raw = make_csv([["1", "a.wav", "전사"]], title="감사시트_교정")
    header, body = read_sheet(raw)
    assert header[0] == "번호"
    assert len(body) == 1 and body[0][1] == "a.wav"


def test_머리글이_없으면_소리내어_실패한다():
    """모양이 다른 파일을 조용히 빈 시트로 읽어 넘기면 교정률이 0% 로 나온다."""
    with pytest.raises(ValueError):
        read_sheet("아무 내용".encode("utf-8"))


# ── 병합 전체 ────────────────────────────────────────────────────────────────
def test_병합_결과가_규약대로_나온다(fake_audit):
    """가짜 감사 한 벌을 통째로 병합해 여섯 줄이 규약대로 갈리는지 본다."""
    rows, stats = merge_auditor(fake_audit["auditor"], fake_audit["dir"],
                                fake_audit["manifest"], judge=None)
    by_id = {r["id"]: r for r in rows}

    assert stats["건수"] == 6
    assert not stats["문제"], stats["문제"]

    # 빈칸·물음표 — 원본 그대로, 교정 아님
    for pair_id, orig in (("T001", "원본 전사 하나"), ("T002", "원본 전사 둘")):
        assert by_id[pair_id]["label_fix"] == orig
        assert by_id[pair_id]["changed"] is False
        assert "unclear" in by_id[pair_id]["flags"]

    # (?) 와 낱자모 — 표시를 떼고 교정으로 인정
    assert by_id["T003"]["label_fix"] == "원본 전사 셋 고침"
    assert by_id["T003"]["changed"] is True
    assert by_id["T004"]["label_fix"] == "원본 전사 넷 고침"
    assert by_id["T004"]["changed"] is True

    # 메모 — note 에 보존되고 소리 x 는 표시까지
    assert by_id["T005"]["note"] == "소리 x" and "silent" in by_id["T005"]["flags"]
    assert by_id["T006"]["note"] == "마지막 부분" and by_id["T006"]["changed"] is False

    # 실질 교정은 (?) 줄과 낱자모 줄 둘뿐이다
    assert stats["실질교정"] == 2
    # 배포 목록에서 갈래·출처가 제대로 붙었는가
    assert by_id["T001"]["task"] == "ATQ" and by_id["T001"]["source"] == "505"


def test_띄어쓰기와_문장부호만_바꾼_것은_교정이_아니다():
    """감사자마다 쉼표 버릇이 다르다. 그것까지 세면 교정률이 부풀려진다."""
    assert norm_cmp("저는 학교에 가요.") == norm_cmp("저는학교에 가요")
    assert norm_cmp("네, 맞아요!") == norm_cmp("네 맞아요")
    # 반대로 505 데이터의 말끊김 표시(+)와 군말 표시(/)는 일부러 살린다
    assert norm_cmp("가+ 갔어요") != norm_cmp("가 갔어요")


# ── ⑥ 같은 발음 되돌림 ──────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def judge():
    """발음 판정기. g2pkk 가 없는 환경(메인 .venv)에서는 이 묶음을 통째로 건너뛴다."""
    j = build_pronunciation_judge(True)
    if j is None:
        pytest.skip("g2pkk 가 없어 같은 발음 필터를 확인할 수 없다 "
                    "(D:/해커톤데이터/lora-venv 에서 돌리면 켜진다)")
    return j


def test_소리가_같은_어절은_원본으로_되돌린다(judge):
    """'많이 → 마니' 는 잘못 들은 것이 아니라 소리 나는 대로 적은 것이다.

    실제 회수본에서 한 감사자가 이런 자리를 50어절 만들었다. 이것을 '교정'으로
    세면 그 사람만 정밀도가 억울하게 깎인다 — 발음은 원본과 똑같기 때문이다.
    """
    fixed, reverted, _ = revert_same_pronunciation("밥을 많이 먹어요", "바블 마니 먹어요", judge)
    assert fixed == "밥을 많이 먹어요"
    assert {r["교정"] for r in reverted} == {"바블", "마니"}


def test_소리가_다른_어절은_그대로_둔다(judge):
    """진짜로 다르게 들은 자리는 손대지 않아야 감사자의 공이 남는다."""
    fixed, reverted, _ = revert_same_pronunciation("과심사가 있어요", "관심사가 있어요", judge)
    assert fixed == "관심사가 있어요"
    assert reverted == []


def test_되돌리고_나면_교정이_아니게_되는_줄도_있다(fake_audit, judge):
    """소리만 같은 자리를 되돌렸더니 원본과 똑같아지면 그 줄은 교정이 아니다."""
    fixed, reverted, _ = revert_same_pronunciation("같이 가요", "가치 가요", judge)
    assert reverted, "'같이/가치' 는 소리가 같아 되돌려야 한다"
    assert norm_cmp(fixed) == norm_cmp("같이 가요")


# ── ⑦ 감사자별 정밀도 셈법 ──────────────────────────────────────────────────
def test_정밀도는_지지와_반대만으로_센다():
    """보류(증인들이 판단 못 함)를 분모에 넣으면 감사자가 억울하게 깎인다."""
    gold_rows = [
        {"id": "A1", "auditor": "갑", "changed": True},
        {"id": "A2", "auditor": "갑", "changed": True},
        {"id": "A3", "auditor": "갑", "changed": True},
        {"id": "A4", "auditor": "갑", "changed": False},
        {"id": "B1", "auditor": "을", "changed": True},
    ]
    verdicts = [
        {"id": "A1", "판정": "suspect"},   # 증인이 감사자 편 → 지지
        {"id": "A2", "판정": "keep"},      # 증인이 원본 편   → 반대
        {"id": "A3", "판정": "hold"},      # 2:2 등           → 보류
        {"id": "A4", "판정": "suspect"},   # 안 고친 줄인데 의심 → 놓침 의심
        {"id": "B1", "판정": "suspect"},
    ]
    report = score_auditors(verdicts, gold_rows)
    갑 = report["감사자별"]["갑"]

    assert (갑["지지"], 갑["반대"], 갑["보류"]) == (1, 1, 1)
    assert 갑["정밀도"] == pytest.approx(0.5)      # 보류를 뺀 2건 중 1건
    assert 갑["판정된비율"] == pytest.approx(2 / 3)
    assert 갑["무교정"] == 1 and 갑["놓침의심"] == 1
    assert report["감사자별"]["을"]["정밀도"] == pytest.approx(1.0)


def test_판정에_감사자가_없으면_id로_짝지어_붙인다():
    """launder_detect 는 감사자를 모른다. 우리 gold 목록으로 이어 붙여야 한다."""
    report = score_auditors([{"id": "A1", "판정": "suspect"}, {"id": "없는id", "판정": "keep"}],
                            [{"id": "A1", "auditor": "갑", "changed": True}])
    assert report["감사자별"]["갑"]["지지"] == 1
    assert report["짝을 못 찾은 판정"] == 1
