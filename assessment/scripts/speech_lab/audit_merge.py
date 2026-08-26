# -*- coding: utf-8 -*-
"""⑧ 감사 회수본 병합 — 팀원 4명이 귀로 고친 시트를 한 덩이로 모은다.

**무엇을 하려는 것인가**

AI Hub 음성에는 사람이 적어 둔 '정답지'(사람 전사)가 딸려 온다. 그런데 그 정답지가
실제 발화와 다른 줄이 섞여 있어(⑦ 세탁 탐지기 참고), 팀원 4명이 각 500건씩 **귀로
듣고 고친 시트**를 돌려줬다. 그런데 사람마다 고친 비율이 18~52% 로 크게 갈렸다.

고친 비율이 높다고 꼼꼼한 것이 아니고, 낮다고 대충 한 것도 아니다. 어느 쪽이 맞는지
가리려면 제3자가 필요하다. 그래서 **증인 4명(받아쓰기 모델)에게 같은 음성을 들려주고**
"원본 정답지 쪽인가, 감사자가 고친 쪽인가"를 표로 물어 **감사자별 정밀도**를 낸다.

이 파일은 그 앞단, 즉 **회수본 4개를 하나의 목록 파일로 만드는 일**만 한다.
받아쓰기는 launder_transcribe.py 가, 판정은 launder_detect.py --mode gold 가 한다.

    (이 파일) 회수본 4개 → audit2000.jsonl / audit2000_gold.jsonl
        → launder_transcribe.py  증인 4명이 받아쓴다
        → launder_detect.py --mode gold  건별 판정
        → (이 파일) --score-gold  감사자별 정밀도 표

**왜 '같은 발음 필터'가 필요한가**

감사자가 "돼요 → 되요" 처럼 고친 자리가 있다. 소리는 똑같고 표기만 다르다.
이런 자리는 감사자가 뭘 잘못 들은 것이 아니라 **맞춤법 습관**의 문제라, 정밀도를
깎는 데 쓰면 억울한 감점이 된다. 그래서 고친 어절의 **발음이 원본과 같으면 원본으로
되돌리고**, 되돌린 자리를 근거로 남긴다(`reverted`). 발음 변환기(g2pkk)가 없는
환경에서는 이 필터만 건너뛰고 병합은 그대로 돌아간다.

쓰는 법:
    # 병합 + wav 추출 (g2pkk 가 있는 환경 — D:/해커톤데이터/lora-venv)
    python audit_merge.py --extract-audio

    # 판정 결과가 나온 뒤 감사자별 정밀도
    python audit_merge.py --score-gold D:/해커톤데이터/audit2000_gold_summary.json \\
        --summary D:/해커톤데이터/audit2000_auditor_precision.json
"""

from __future__ import annotations

import argparse
import csv
import difflib
import io
import json
import re
import sys
import unicodedata
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import DATA_ROOT, enable_utf8_output, print_table, read_manifest  # noqa: E402


# ── 어디에 무엇이 있는지 ─────────────────────────────────────────────────────
#: 팀원이 채워 돌려준 시트가 모여 있는 폴더 (구글 드라이브에서 내려받은 그대로)
DEFAULT_RETURN_DIR = ("D:/해커톤데이터/해커톤_오디오데이터_2500-20260825T071508Z-1-001"
                      "/해커톤_오디오데이터_2500")

#: 감사자 이름 → 회수본 파일 이름.
#: 파일 이름이 제각각인 이유는 사람마다 구글 시트에서 내려받은 방식이 달라서다
#: (한효주는 '효주'로, 김도영은 시트 이름이 파일명에 붙어 나왔다).
RETURN_FILES = {
    "김도영": "감사시트_교정_김도영 - 감사시트_교정.csv",
    "백예나": "감사시트_교정_백예나.csv",
    "황인홍": "감사시트_교정_황인홍.csv",
    "한효주": "감사시트_교정_효주.csv",
}

#: 감사자 이름 → 배포할 때 준 꾸러미(zip). 안에 원본 시트와 wav 500개가 들어 있다
PACKAGE_ZIPS = {name: f"{name}_500건.zip" for name in RETURN_FILES}

#: 배포 목록. 어느 파일이 누구에게 갔고 갈래(task)·출처(source)가 무엇인지가 여기 있다
DEFAULT_MANIFEST = DATA_ROOT / "manifests" / "team2500.jsonl"

#: 꺼낸 wav 를 둘 자리. 저장소(C:)가 아니라 데이터 디스크(D:)에 둔다 — 1.4GB 다
DEFAULT_AUDIO_ROOT = "D:/해커톤데이터/audit2000/wav"


# ── 글자를 재는 자 ───────────────────────────────────────────────────────────
#: 두 전사를 견줄 때 무시할 것 — 띄어쓰기와 문장부호.
#: 감사자마다 쉼표 찍는 버릇이 다른데 그것까지 '고쳤다'로 세면 교정률이 부풀려진다.
#: `+`(505 데이터의 말끊김 표시)와 `/`(군말 표시)는 **일부러 남긴다** —
#: 학습 라벨을 만들 때 make_labels.py 가 떼는 것이 그쪽 일이기 때문이다.
_CMP_STRIP = re.compile(r"[\s,.?!·…]+")

#: 어절 단위로 견줄 때만 떼는 문장부호(띄어쓰기는 어절을 가르는 기준이라 남긴다)
_PUNCT_ONLY = re.compile(r"[,.?!·…]")

#: 한글 낱자모(ㄱ~ㅎ, ㅏ~ㅣ). 글자가 덜 조합된 채로 남은 것이라 지운다
_STRAY_JAMO = re.compile(r"[ㄱ-ㅎㅏ-ㅣ]")


def nfc(text: str) -> str:
    """한글 표기를 한 가지 모양으로 통일한다.

    맥에서 만든 파일은 '한'을 'ㅎ+ㅏ+ㄴ' 으로 쪼개 저장한다(NFD). 눈으로는 같아
    보이는데 컴퓨터는 다른 글자로 세므로, 견주기 전에 반드시 합쳐진 모양(NFC)으로
    맞춰 둔다. 이걸 빼먹으면 맥 사용자의 교정률만 100% 로 나온다.
    """
    return unicodedata.normalize("NFC", text or "")


def norm_cmp(text: str) -> str:
    """'실제로 고쳤는가'를 판단하기 위한 비교용 형태로 바꾼다."""
    return _CMP_STRIP.sub("", nfc(text))


# ── 회수본 읽기 ──────────────────────────────────────────────────────────────
def read_sheet(raw: bytes) -> tuple[list[str], list[list[str]]]:
    """감사 시트 한 장을 읽어 (머리글, 내용 줄들) 로 돌려준다.

    시트마다 첫 줄이 다르다 — 백예나 시트는 첫 줄이 제목("감사시트_교정")이고
    둘째 줄이 머리글이다. 그래서 줄 번호로 찍지 않고 **첫 칸이 '번호'인 줄**을
    찾아 그것을 머리글로 삼는다. 앞으로 시트가 하나 더 늘어도 이 방식이면 통한다.
    """
    # utf-8-sig 로 읽으면 윈도우 엑셀이 붙이는 보이지 않는 표식(BOM)이 함께 벗겨진다
    text = raw.decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(text)))

    header_at = next((i for i, r in enumerate(rows) if r and r[0].strip() == "번호"), None)
    if header_at is None:
        raise ValueError("시트에서 '번호' 머리글 줄을 찾지 못했다")

    header = [c.strip() for c in rows[header_at]]
    # 완전히 빈 줄(엑셀이 끝에 붙이는 것)은 내용으로 세지 않는다
    body = [r for r in rows[header_at + 1:] if any(c.strip() for c in r)]
    return header, body


def clean_cell(raw_cell: str) -> tuple[str, list[str], bool]:
    """감사자가 적은 칸 하나를 정리한다.

    돌려주는 것: (정리된 전사, 표시 목록, 이 칸을 교정으로 인정할지)

    감사자들이 남긴 약속된 표시가 세 가지다.
      · 빈칸 또는 `?` 한 글자 — "무슨 말인지 못 알아듣겠다". 교정으로 세지 않고
        원본을 그대로 둔다. 안 그러면 '못 알아들었다'가 '원본이 틀렸다'로 둔갑한다
      · `(?)` 가 섞인 칸 — "이렇게 들리는 것 같은데 자신은 없다". 교정은 인정하되
        나중에 사람이 다시 볼 수 있게 표시만 남긴다
      · 낱자모가 남은 칸 — 타자 치다 만 흔적(`잃어ㅃ려서`). 교정은 인정하되
        조합이 덜 된 글자는 지운다. 받아쓰기 모델은 낱자모를 절대 내지 않으므로
        그대로 두면 그 어절이 무조건 '증인과 다름'으로 잡힌다
    """
    cell = nfc(raw_cell).strip()
    flags: list[str] = []

    # ① 못 알아들은 칸 — 원본 유지
    if not cell or cell == "?":
        return "", ["unclear"], False

    # ② 자신 없는 칸 — 표시만 떼고 내용은 살린다
    if "(?)" in cell:
        flags.append("uncertain")
        cell = cell.replace("(?)", "")

    # ③ 덜 조합된 낱자모 — 지운다
    if _STRAY_JAMO.search(cell):
        flags.append("stray_jamo")
        cell = _STRAY_JAMO.sub("", cell)

    # 표시를 떼고 나면 공백이 겹칠 수 있어 한 번 정리한다
    cell = re.sub(r"[ \t]{2,}", " ", cell).strip()

    # 표시만 있고 내용이 남지 않았다면 결국 못 알아들은 칸과 같다
    if not cell:
        return "", flags + ["unclear"], False
    return cell, flags, True


def read_note(row: list[str]) -> tuple[str, list[str]]:
    """시트의 네 번째 칸(김도영 시트의 '진행도')을 읽는다.

    대부분은 '여기까지 했다'는 뜻의 `ㅇ` 하나라 버린다. 그것 말고 적힌 말은
    감사자가 남긴 메모이므로 `note` 로 보존한다. 메모에 '소리 x'(소리가 안 난다)가
    있으면 그 건은 받아쓰기 자체가 무의미하므로 표시를 붙여 둔다.
    """
    memo = " ".join(c.strip() for c in row[3:] if c.strip() and c.strip() != "ㅇ").strip()
    if not memo:
        return "", []
    return memo, ["silent"] if "소리 x" in memo or "소리x" in memo else []


# ── 같은 발음 필터 ───────────────────────────────────────────────────────────
class SamePronunciation:
    """어절 두 개가 **소리로는 같은지** 판단한다.

    "되요/돼요", "안 되요/안돼요" 처럼 표기만 다르고 소리는 같은 자리를 걸러내는 데
    쓴다. 감사자가 그렇게 고친 것은 '잘못 들었다'가 아니라 '맞춤법 습관'이므로,
    증인(받아쓰기 모델)에게 물어 정밀도를 매길 대상이 아니다.

    **윈도우 땜질 안내** — 발음 변환기 g2pkk 는 원래 형태소 분석기로 mecab 을
    쓰는데 mecab 은 윈도우에서 설치가 안 된다(빌드 실패). 그래서 g2pkk 가
    mecab 에게 물어보는 두 자리를 Kiwi 로 바꿔 끼운다. 둘 다 "문장을 주면
    (낱말, 품사) 목록을 준다"는 점이 같아서 이 바꿔 끼우기가 통한다.
    """

    #: 된소리(ㄲㄸㅃㅆㅉ) → 예사소리. '경음화만 다른 자리'를 따로 세는 데 쓴다
    _TENSE = str.maketrans("ㄲㄸㅃㅆㅉ", "ㄱㄷㅂㅅㅈ")

    def __init__(self):
        import g2pkk.g2pkk as g2pkk_module
        from kiwipiepy import Kiwi

        kiwi = Kiwi()

        class _KiwiAsMecab:
            """g2pkk 가 mecab 인 줄 알고 부르는 껍데기. pos() 하나만 있으면 된다."""

            def pos(self, text):
                return [(t.form, t.tag) for t in kiwi.tokenize(text)]

        # g2pkk 가 mecab 을 찾는 검사와 부르는 자리를 Kiwi 로 바꿔 끼운다
        g2pkk_module.G2p.check_mecab = lambda self: None
        g2pkk_module.G2p.get_mecab = lambda self: _KiwiAsMecab()

        from g2pkk import G2p

        self._g2p = G2p()
        # 같은 어절이 수천 번 나오므로 한 번 바꾼 것은 외워 둔다(안 하면 몇 분 걸린다)
        self._cache: dict[str, str] = {}

    def pron(self, word: str) -> str:
        """어절 하나를 소리 나는 대로 바꾼다. `국물` → `궁물`"""
        word = nfc(word)
        if word not in self._cache:
            self._cache[word] = self._g2p(word).replace(" ", "")
        return self._cache[word]

    def same(self, a: str, b: str) -> bool:
        """두 어절의 소리가 완전히 같은가."""
        return self.pron(a) == self.pron(b)

    def tense_only(self, a: str, b: str) -> bool:
        """된소리 여부만 다른가 (`갈께/갈게`). 되돌리지는 않고 세기만 한다.

        된소리는 실제로 사람이 다르게 발음하는 일이 있어(강조·방언) 같은 소리라고
        단정할 수 없다. 그래서 '애매한 자리'로 따로 세어 두고 판단은 미룬다.
        """
        from jamo import h2j, j2hcj

        def flat(text: str) -> str:
            return j2hcj(h2j(text)).translate(self._TENSE)

        return flat(self.pron(a)) == flat(self.pron(b))


def revert_same_pronunciation(label_orig: str, label_fix: str, judge: SamePronunciation
                              ) -> tuple[str, list[dict], int]:
    """교정본에서 **소리가 같은 어절만** 원본으로 되돌린다.

    돌려주는 것: (되돌린 뒤의 교정본, 되돌린 자리 목록, 된소리만 달랐던 어절 수)

    어떻게 하나:
      ① 원본과 교정본을 어절 목록으로 만들고 difflib 으로 나란히 맞춘다
      ② 서로 바뀐(replace) 자리 중 **개수가 같은 구간**만 하나씩 짝지어 본다
         (한 어절이 둘로 쪼개진 자리는 짝이 애매해 손대지 않는다)
      ③ 짝의 소리가 같으면 교정본 자리에 원본 어절을 도로 넣는다

    비교는 문장부호를 뗀 형태로 하지만, 되돌릴 때는 **원본 어절을 통째로** 넣는다.
    """
    raw_orig, raw_fix = nfc(label_orig).split(), nfc(label_fix).split()
    # 견주기용 형태(문장부호를 뗀 것). 자리 번호는 원래 어절과 그대로 맞춰 둔다
    key_orig = [_PUNCT_ONLY.sub("", w) for w in raw_orig]
    key_fix = [_PUNCT_ONLY.sub("", w) for w in raw_fix]

    new_fix = list(raw_fix)
    reverted: list[dict] = []
    tense_only = 0

    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, key_orig, key_fix).get_opcodes():
        # 어절이 통째로 바뀐 자리만 본다. 넣거나 뺀 자리는 소리 비교가 성립하지 않는다
        if tag != "replace" or (i2 - i1) != (j2 - j1):
            continue
        for k in range(i2 - i1):
            a, b = key_orig[i1 + k], key_fix[j1 + k]
            if not a or not b:
                continue
            try:
                if judge.same(a, b):
                    # 소리가 같다 — 감사자가 표기만 바꾼 것이므로 원본으로 되돌린다
                    new_fix[j1 + k] = raw_orig[i1 + k]
                    reverted.append({"자리": j1 + k, "원본": raw_orig[i1 + k],
                                     "교정": raw_fix[j1 + k], "발음": judge.pron(a)})
                elif judge.tense_only(a, b):
                    tense_only += 1
            except Exception:
                # 발음 변환이 안 되는 글자(외국어·기호)는 손대지 않고 그냥 둔다
                continue

    return " ".join(new_fix), reverted, tense_only


def build_pronunciation_judge(enabled: bool):
    """발음 판정기를 준비한다. 없으면 없는 대로 알리고 필터만 건너뛴다.

    g2pkk 는 lora-venv 에만 깔려 있다. 메인 .venv 에서도 병합은 돌아가야 하므로
    여기서 멈추지 않고 경고만 찍는다 — 대신 '필터를 건너뛰었다'가 표에 남는다.
    """
    if not enabled:
        print("같은 발음 필터를 끄고 돌린다 (--no-g2p)")
        return None
    try:
        judge = SamePronunciation()
        judge.pron("확인")   # 실제로 한 번 돌려 봐야 땜질이 통하는지 알 수 있다
        print("같은 발음 필터: g2pkk + Kiwi 땜질로 켰다")
        return judge
    except Exception as exc:
        print(f"경고: 발음 변환기를 못 불러왔다 ({type(exc).__name__}: {str(exc)[:80]}) "
              f"— 같은 발음 필터를 건너뛴다. g2pkk 가 있는 환경(D:/해커톤데이터/lora-venv)"
              f"에서 다시 돌리면 켜진다")
        return None


# ── 병합 ─────────────────────────────────────────────────────────────────────
def read_original_sheet(zip_path: Path, auditor: str) -> dict[str, dict]:
    """배포 꾸러미(zip) 안의 **원본 시트**를 읽어 {파일명: 줄} 로 만든다.

    원본 라벨을 배포 목록(team2500.jsonl)이 아니라 꾸러미 안 시트에서 가져오는
    이유: 감사자가 실제로 눈으로 본 글이 이것이기 때문이다. 목록과 시트가 어쩌다
    어긋나 있으면 감사자를 탓할 수 없다 (어긋난 줄은 아래에서 따로 센다).
    """
    with zipfile.ZipFile(zip_path) as z:
        member = next(n for n in z.namelist() if n.endswith("감사시트_교정.csv"))
        raw = z.read(member)

    _, body = read_sheet(raw)
    table: dict[str, dict] = {}
    for row in body:
        if len(row) < 3:
            continue
        table[nfc(row[1].strip())] = {"번호": row[0].strip(), "ref": nfc(row[2])}
    return table


def merge_auditor(auditor: str, return_dir: Path, manifest: dict[str, dict],
                  judge) -> tuple[list[dict], dict]:
    """감사자 한 명의 회수본을 원본과 대조해 건별 줄을 만든다.

    한 건이 이렇게 생겼다:
        {id, auditor, task, source, label_orig, label_fix, changed, flags, note, reverted}
    """
    returned_raw = (return_dir / RETURN_FILES[auditor]).read_bytes()
    _, body = read_sheet(returned_raw)
    original = read_original_sheet(return_dir / PACKAGE_ZIPS[auditor], auditor)

    rows: list[dict] = []
    stats = {"건수": 0, "실질교정": 0, "되돌림어절": 0, "필터후교정": 0,
             "된소리만": 0, "flags": {}, "문제": []}
    seen: set[str] = set()

    for row in body:
        if len(row) < 2:
            continue
        file_name = nfc(row[1].strip())
        cell = row[2] if len(row) > 2 else ""

        # 같은 파일이 두 번 나오면(복사 실수) 뒤엣것은 버린다 — 어느 쪽이 최종인지 알 수 없다
        if file_name in seen:
            stats["문제"].append(f"중복 파일명: {file_name}")
            continue
        seen.add(file_name)

        if file_name not in original:
            stats["문제"].append(f"원본 시트에 없는 파일명: {file_name}")
            continue

        pair_id = file_name[:-4] if file_name.endswith(".wav") else file_name
        label_orig = original[file_name]["ref"]

        # 칸을 정리하고, 못 알아들은 칸은 원본을 그대로 쓴다
        cleaned, flags, accept = clean_cell(cell)
        label_fix = cleaned if accept else label_orig

        note, note_flags = read_note(row)
        flags = flags + note_flags

        # 배포 목록에서 갈래·출처·음성 위치를 가져온다
        meta = manifest.get(pair_id)
        if meta is None:
            stats["문제"].append(f"배포 목록에 없는 id: {pair_id}")
            meta = {}
        elif meta.get("auditor") and meta["auditor"] != auditor:
            stats["문제"].append(f"배정이 다르다: {pair_id} → {meta['auditor']}")
        # 배포 목록의 전사와 꾸러미 시트의 전사가 어긋난 줄도 세어 둔다
        if meta.get("ref") and norm_cmp(meta["ref"]) != norm_cmp(label_orig):
            stats["문제"].append(f"목록·시트 원본 불일치: {pair_id}")

        changed = norm_cmp(label_fix) != norm_cmp(label_orig)
        if changed:
            stats["실질교정"] += 1

        # 같은 발음 필터 — 실제로 고친 줄에만 건다
        reverted: list[dict] = []
        if changed and judge is not None:
            label_fix, reverted, tense_only = revert_same_pronunciation(
                label_orig, label_fix, judge)
            stats["되돌림어절"] += len(reverted)
            stats["된소리만"] += tense_only
            # 되돌리고 나서 원본과 같아졌으면 그 줄은 교정이 아니었던 것이다
            changed = norm_cmp(label_fix) != norm_cmp(label_orig)
            if reverted:
                flags = flags + ["same_pron_reverted"]

        if changed:
            stats["필터후교정"] += 1
        for f in flags:
            stats["flags"][f] = stats["flags"].get(f, 0) + 1
        stats["건수"] += 1

        rows.append({
            "id": pair_id,
            "auditor": auditor,
            "task": meta.get("task", ""),
            "source": meta.get("source", ""),
            "label_orig": label_orig,
            "label_fix": label_fix,
            "changed": changed,
            "flags": flags,
            "note": note,
            "reverted": reverted,
            "번호": row[0].strip(),
            "duration": meta.get("duration"),
            "prompt": meta.get("prompt", ""),
            "zip_path": meta.get("zip_path"),
            "zip_member": meta.get("zip_member"),
        })

    # 배포했는데 회수본에 없는 줄 (빠뜨리고 안 낸 것)
    for missing in sorted(set(original) - seen):
        stats["문제"].append(f"회수본에 빠진 파일: {missing}")
    return rows, stats


# ── wav 꺼내기 ───────────────────────────────────────────────────────────────
def extract_wavs(return_dir: Path, audio_root: Path) -> dict:
    """배포 꾸러미 4개에서 wav 를 꺼내 한 폴더에 모은다. 이미 있는 것은 건너뛴다.

    받아쓰기(launder_transcribe.py)는 음성을 zip 안에서 바로 꺼내 쓸 수도 있지만,
    2,000건을 증인 4명이 각각 읽으면 같은 zip 을 8,000번 뒤지게 된다.
    한 번 풀어 두는 편이 훨씬 빠르다.
    """
    audio_root.mkdir(parents=True, exist_ok=True)
    report = {"꺼냄": 0, "이미있음": 0, "실패": []}

    for auditor, zip_name in PACKAGE_ZIPS.items():
        zip_path = return_dir / zip_name
        if not zip_path.exists():
            report["실패"].append(f"꾸러미 없음: {zip_path}")
            continue

        with zipfile.ZipFile(zip_path) as z:
            for info in z.infolist():
                # zip 안 이름이 cp949 로 적힌 옛날 압축기도 있어 두 경우를 다 받는다.
                # 0x800 표시가 켜져 있으면 이미 UTF-8 로 제대로 읽힌 것이다
                name = info.filename
                if not info.flag_bits & 0x800:
                    try:
                        name = name.encode("cp437").decode("cp949")
                    except Exception:
                        pass
                if not name.lower().endswith(".wav"):
                    continue

                target = audio_root / Path(name).name
                if target.exists() and target.stat().st_size > 0:
                    report["이미있음"] += 1
                    continue
                try:
                    target.write_bytes(z.read(info))
                    report["꺼냄"] += 1
                except Exception as exc:
                    report["실패"].append(f"{name}: {type(exc).__name__}")

        print(f"  · {auditor}: 누적 꺼냄 {report['꺼냄']}건 · "
              f"이미 있던 것 {report['이미있음']}건", flush=True)
    return report


# ── 목록 파일 쓰기 ───────────────────────────────────────────────────────────
def write_manifests(rows: list[dict], audio_root: Path, out_dir: Path) -> tuple[Path, Path]:
    """두 가지 목록 파일을 쓴다. 읽는 쪽이 달라서 모양도 다르다.

    ① audit2000.jsonl      — launder_transcribe.py 가 읽는다.
       `id` 와 음성 위치가 필요하다. 음성 위치는 두 벌로 적어 둔다:
       풀어 놓은 wav(`audio`)를 먼저 보고, 없으면 원본 AI Hub zip 에서 꺼낸다.
       그래서 wav 를 안 풀어도 받아쓰기가 돌아간다.
    ② audit2000_gold.jsonl — launder_detect.py --mode gold 가 읽는다.
       그쪽 코드(load_gold)는 `file`·`label_orig`·`gold` 세 이름만 본다.
       나머지(감사자 등)는 우리가 나중에 조인해 쓰려고 얹어 두는 것이다.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    main_path = out_dir / "audit2000.jsonl"
    gold_path = out_dir / "audit2000_gold.jsonl"

    with main_path.open("w", encoding="utf-8") as f:
        for r in rows:
            out = {
                "id": r["id"],
                # 풀어 놓은 wav 의 자리(절대 경로). _common.load_audio_bytes 는
                # 이 자리에 파일이 있으면 그것을 먼저 쓴다
                "audio": str((audio_root / f"{r['id']}.wav").as_posix()),
                "zip_path": r.get("zip_path"),
                "zip_member": r.get("zip_member"),
                # `ref` 는 '지금 우리가 믿는 정답' 이므로 교정본을 넣는다
                "ref": r["label_fix"],
                "label_orig": r["label_orig"],
                "label_fix": r["label_fix"],
                "changed": r["changed"],
                "flags": r["flags"],
                "note": r["note"],
                "reverted": r["reverted"],
                "auditor": r["auditor"],
                "task": r["task"],
                "source": r["source"],
                "duration": r["duration"],
                "prompt": r["prompt"],
            }
            f.write(json.dumps(out, ensure_ascii=False) + "\n")

    with gold_path.open("w", encoding="utf-8") as f:
        for r in rows:
            out = {
                "file": f"{r['id']}.wav",     # load_gold 가 보는 이름
                "id": r["id"],
                "label_orig": r["label_orig"],   # 원본 정답지
                "gold": r["label_fix"],          # 감사자가 고친 것
                "auditor": r["auditor"],
                "task": r["task"],
                "source": r["source"],
                "changed": r["changed"],
                "flags": r["flags"],
            }
            f.write(json.dumps(out, ensure_ascii=False) + "\n")

    return main_path, gold_path


# ── 화면에 찍는 표 ───────────────────────────────────────────────────────────
def print_merge_report(per_auditor: dict[str, dict], judge_on: bool) -> None:
    """감사자별로 몇 건을 어떻게 고쳤는지 표로 보여 준다.

    '실질 교정' 과 '필터 후 교정' 을 나란히 두는 이유: 소리가 같은 자리를 되돌리고
    나면 실제로 얼마나 남는지가 감사자마다 다르기 때문이다. 한 사람은 되돌림이
    50어절인데 다른 사람은 2어절이면, 그 차이 자체가 감사 습관의 차이다.
    """
    print("\n=== 감사자별 병합 결과 ===")
    if not judge_on:
        print("  (같은 발음 필터가 꺼져 있어 '되돌림'·'필터 후'는 실질 교정과 같다)")

    all_flags = sorted({f for s in per_auditor.values() for f in s["flags"]})
    headers = ["감사자", "건수", "실질 교정", "교정률", "같은발음 되돌림(어절)",
               "된소리만(어절)", "필터 후 교정"] + all_flags
    table = []
    for auditor, s in per_auditor.items():
        rate = s["실질교정"] / s["건수"] if s["건수"] else 0
        table.append([auditor, str(s["건수"]), str(s["실질교정"]), f"{rate:.1%}",
                      str(s["되돌림어절"]), str(s["된소리만"]), str(s["필터후교정"])]
                     + [str(s["flags"].get(f, 0)) for f in all_flags])

    total = {k: sum(s[k] for s in per_auditor.values())
             for k in ("건수", "실질교정", "되돌림어절", "된소리만", "필터후교정")}
    table.append(["합계", str(total["건수"]), str(total["실질교정"]),
                  f"{total['실질교정'] / max(total['건수'], 1):.1%}",
                  str(total["되돌림어절"]), str(total["된소리만"]),
                  str(total["필터후교정"])]
                 + [str(sum(s["flags"].get(f, 0) for s in per_auditor.values()))
                    for f in all_flags])
    print_table(headers, table)

    print("\n  표시(flags) 뜻: unclear=못 알아들어 원본 유지 · uncertain=(?) 자신 없음 · "
          "stray_jamo=낱자모 지움 · silent=소리 없음 메모 · "
          "same_pron_reverted=발음 같아 되돌린 어절이 있음")

    # 문제가 있었으면 몇 건인지와 앞부분을 반드시 보여 준다 — 조용히 넘어가면 안 된다
    for auditor, s in per_auditor.items():
        if s["문제"]:
            print(f"\n  [{auditor}] 대조 중 걸린 것 {len(s['문제'])}건")
            for line in s["문제"][:5]:
                print(f"      - {line}")
            if len(s["문제"]) > 5:
                print(f"      … 외 {len(s['문제']) - 5}건")


# ── 감사자별 정밀도 ──────────────────────────────────────────────────────────
def load_verdicts(path: Path) -> list[dict]:
    """launder_detect --mode gold 가 낸 건별 판정을 읽는다.

    gold 모드는 `--summary` 로 요약 json 하나만 쓰는데, 그 안의 `줄별` 칸에
    건별 판정이 들어 있다. 나중에 jsonl 로 바뀌더라도 읽히도록 두 모양을 다 받는다.
    """
    p = Path(path)
    if p.suffix.lower() == ".json":
        data = json.loads(p.read_text(encoding="utf-8"))
        rows = data.get("줄별") or data.get("per_row") or []
        if not rows:
            raise SystemExit(f"{p} 에 건별 판정(`줄별`)이 없다. "
                             f"launder_detect.py --mode gold --summary 로 낸 파일인지 확인해라")
        return rows
    return read_manifest(p)


def score_auditors(verdicts: list[dict], gold_rows: list[dict]) -> dict:
    """감사자별 정밀도를 낸다 — 감사자가 고친 자리를 증인들이 편들어 주는가.

    **셈법.** 감사자가 실제로 고친 줄(`changed`)만 본다. 그 줄의 원본 라벨을
    증인 4명에게 물었을 때,
      · suspect — "원본 라벨이 실제 발화와 다르다" → 감사자 편 (**지지**)
      · keep    — "원본 라벨이 맞다"               → 감사자 반대 (**반대**)
      · hold    — 2:2 등 표가 갈림                 → **보류**, 어느 쪽으로도 안 센다
    정밀도 = 지지 / (지지 + 반대). 보류를 분모에 넣지 않는 이유는 그것이
    감사자의 잘잘못이 아니라 **증인들이 판단을 못 한 것**이기 때문이다.

    함께 내는 '놓침 의심'은 반대 방향이다 — 감사자가 안 고치고 넘어간 줄인데
    증인들은 원본이 이상하다고 한 자리다. 정밀도와 짝이 되는 재현율 쪽 신호다.
    """
    # 판정 결과에 감사자가 안 적혀 있으면 id 로 gold 목록과 짝지어 붙인다
    by_id = {r["id"]: r for r in gold_rows}

    per: dict[str, dict] = {}
    unmatched = 0
    for v in verdicts:
        pair_id = v.get("id")
        verdict = v.get("판정") or v.get("verdict")
        info = by_id.get(pair_id)
        auditor = v.get("auditor") or (info or {}).get("auditor")
        if info is None or not auditor:
            unmatched += 1
            continue

        cell = per.setdefault(auditor, {"평가대상": 0, "지지": 0, "반대": 0, "보류": 0,
                                        "무교정": 0, "놓침의심": 0})
        if info.get("changed"):
            cell["평가대상"] += 1
            if verdict == "suspect":
                cell["지지"] += 1
            elif verdict == "keep":
                cell["반대"] += 1
            else:
                cell["보류"] += 1
        else:
            cell["무교정"] += 1
            if verdict == "suspect":
                cell["놓침의심"] += 1

    for cell in per.values():
        decided = cell["지지"] + cell["반대"]
        cell["정밀도"] = cell["지지"] / decided if decided else float("nan")
        cell["판정된비율"] = decided / cell["평가대상"] if cell["평가대상"] else float("nan")

    return {"감사자별": per, "짝을 못 찾은 판정": unmatched,
            "정의": ("정밀도 = 지지/(지지+반대). 감사자가 고친 줄만 대상으로 하고, "
                     "증인들이 판단을 못 한 보류는 분모에서 뺀다.")}


def print_auditor_scores(report: dict) -> None:
    """감사자별 정밀도 표를 찍는다. 판정된 비율을 함께 내야 숫자를 믿을 수 있다."""
    print("\n=== 감사자별 정밀도 (증인 4명의 표) ===")
    print(f"{report['정의']}\n")

    def pct(v):
        return "측정불가" if v != v else f"{v:.1%}"

    rows = []
    for auditor, c in sorted(report["감사자별"].items()):
        rows.append([auditor, str(c["평가대상"]), str(c["지지"]), str(c["반대"]),
                     str(c["보류"]), pct(c["정밀도"]), pct(c["판정된비율"]),
                     str(c["무교정"]), str(c["놓침의심"])])
    print_table(["감사자", "고친 줄", "지지", "반대", "보류", "정밀도",
                 "판정된 비율", "안 고친 줄", "놓침 의심"], rows)

    if report["짝을 못 찾은 판정"]:
        print(f"\n  경고: gold 목록에서 짝을 못 찾은 판정 {report['짝을 못 찾은 판정']}건")
    print("\n  읽는 법: '판정된 비율'이 낮으면 증인들이 대부분 보류한 것이라 "
          "정밀도 숫자를 그대로 믿으면 안 된다.")


# ── 실행 ─────────────────────────────────────────────────────────────────────
def main() -> int:
    enable_utf8_output()

    ap = argparse.ArgumentParser(description="⑧ 감사 회수본 4개를 병합하고 감사자별 정밀도를 낸다")
    ap.add_argument("--return-dir", default=DEFAULT_RETURN_DIR,
                    help="회수본 csv 와 배포 꾸러미 zip 이 있는 폴더")
    ap.add_argument("--manifest", default=str(DEFAULT_MANIFEST),
                    help="배포 목록 jsonl (누구에게 무엇이 갔는지)")
    ap.add_argument("--out-dir", default=str(DATA_ROOT / "manifests"),
                    help="만들어진 목록 파일을 둘 폴더")
    ap.add_argument("--audio-root", default=DEFAULT_AUDIO_ROOT,
                    help="wav 를 풀어 둘 폴더")
    ap.add_argument("--extract-audio", action="store_true",
                    help="배포 꾸러미에서 wav 를 꺼낸다 (이미 있으면 건너뜀)")
    ap.add_argument("--g2p", action=argparse.BooleanOptionalAction, default=True,
                    help="같은 발음 필터 (기본 켬. --no-g2p 로 끈다)")
    ap.add_argument("--score-gold", help="launder_detect --mode gold 결과로 감사자별 정밀도를 낸다")
    ap.add_argument("--summary", help="요약 json 저장 위치")
    args = ap.parse_args()

    return_dir = Path(args.return_dir)
    audio_root = Path(args.audio_root)
    out_dir = Path(args.out_dir)

    # 배포 목록을 읽어 둔다 — 갈래·출처·원본 음성 자리가 여기 있다
    manifest = {r["id"]: r for r in read_manifest(Path(args.manifest))}
    print(f"배포 목록 {len(manifest)}건: {args.manifest}")

    judge = build_pronunciation_judge(args.g2p)

    # ① 감사자 넷을 차례로 병합한다
    all_rows: list[dict] = []
    per_auditor: dict[str, dict] = {}
    for auditor in RETURN_FILES:
        rows, stats = merge_auditor(auditor, return_dir, manifest, judge)
        all_rows.extend(rows)
        per_auditor[auditor] = stats

    print_merge_report(per_auditor, judge is not None)

    # ② wav 꺼내기 (원할 때만)
    audio_report = None
    if args.extract_audio:
        print(f"\n=== wav 꺼내기 → {audio_root} ===")
        audio_report = extract_wavs(return_dir, audio_root)
        print(f"  끝: 꺼낸 것 {audio_report['꺼냄']}건 · "
              f"이미 있던 것 {audio_report['이미있음']}건 · "
              f"실패 {len(audio_report['실패'])}건")
        for line in audio_report["실패"][:5]:
            print(f"      - {line}")

    # ③ 목록 파일 두 개 쓰기
    main_path, gold_path = write_manifests(all_rows, audio_root, out_dir)
    print(f"\n저장: {main_path} ({len(all_rows)}행) — 받아쓰기용")
    print(f"저장: {gold_path} ({len(all_rows)}행) — 판정용(--mode gold)")

    summary = {
        "총건수": len(all_rows),
        "감사자별": {a: {k: v for k, v in s.items() if k != "문제"}
                     for a, s in per_auditor.items()},
        "문제": {a: s["문제"] for a, s in per_auditor.items() if s["문제"]},
        "같은발음필터": judge is not None,
        "wav": audio_report,
        "파일": {"받아쓰기용": str(main_path), "판정용": str(gold_path)},
    }

    # ④ 판정 결과가 있으면 감사자별 정밀도까지
    if args.score_gold:
        verdicts = load_verdicts(Path(args.score_gold))
        gold_rows = [{"id": r["id"], "auditor": r["auditor"], "changed": r["changed"]}
                     for r in all_rows]
        score = score_auditors(verdicts, gold_rows)
        print_auditor_scores(score)
        summary["감사자별정밀도"] = score

    if args.summary:
        Path(args.summary).parent.mkdir(parents=True, exist_ok=True)
        Path(args.summary).write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                                      encoding="utf-8")
        print(f"\n저장: {args.summary}")

    if not args.score_gold:
        print("\n다음: launder_transcribe.py 로 증인 4명에게 받아쓰게 한 뒤 "
              "launder_detect.py --mode gold 로 판정하고, "
              "그 결과를 이 파일의 --score-gold 에 넣어라")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
