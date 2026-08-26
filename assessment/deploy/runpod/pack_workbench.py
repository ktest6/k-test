"""RunPod(빌려 쓰는 그래픽카드 서버)에 올릴 '작업 꾸러미'를 만든다.

무엇을 하는 것인가
------------------
v3 학습·증인 받아쓰기·평가는 그래픽카드가 있어야 하는데, 내 PC 의 RTX 4060 으로는
2,000건 전수 받아쓰기가 26시간 걸린다(8/25 실측). 그래서 그때그때 RunPod 을 빌려
돌리고 끄는데, 그러려면 **필요한 파일만 골라 한 덩이로 묶어 올려야 한다.**
그 묶는 일을 하는 것이 이 스크립트다.

무엇을 담나
-----------
    ktest_workbench/
      assessment/scripts/speech_lab/   실험실 스크립트 전부 (requirements-lab.txt 포함)
      assessment/src/                  채점 코드 (읽기 전용으로 빌려 쓰는 자리가 있다)
      data/manifests/*.jsonl           받아쓸 목록·정답지
      data/audit2000/wav/              음성 (--audio 를 줄 때만. 2,000건이면 1.9GB)

**왜 저장소와 같은 폴더 모양으로 담나**
    speech_lab 의 `_common.py` 는 자기 위치에서 두 칸 올라간 곳을 assessment 폴더로,
    세 칸 올라간 곳의 `data/` 를 데이터 폴더로 친다. 모양을 바꿔 담으면 스크립트가
    데이터를 못 찾는다. 그래서 저장소 모양을 그대로 옮긴다 — 그러면 `사용법.md` 에
    적힌 명령을 글자 하나 안 고치고 서버에서도 쓸 수 있다.

**목록 파일의 음성 경로는 고쳐서 담는다** (이 스크립트가 하는 유일한 '수정')
    목록 파일에는 `"audio": "D:/해커톤데이터/audit2000/wav/xxx.wav"` 처럼 내 윈도우
    PC 의 자리가 적혀 있다. 리눅스 서버에는 D 드라이브가 없으니 그대로 두면 한 건도
    못 읽는다. 그래서 `"audit2000/wav/xxx.wav"` 라는 **data 폴더 기준 상대 경로**로
    바꿔 담는다. 상대 경로라 꾸러미를 어디에 풀든 그대로 맞는다.
    (원본 목록 파일은 건드리지 않는다. 꾸러미 안에 들어가는 사본만 바뀐다.)

    이미 `pairs/71479/A.wav` 처럼 data 폴더 기준 상대 경로로 적힌 줄은 손대지 않는다.

    **꾸러미 하나에는 wav 폴더 하나만 담는다.** 윈도우 자리를 가리키던 줄은 전부
    `--audio-subdir` 한 곳으로 몰아 적히기 때문이다. 그래서 audit2000 wav 를 담은
    꾸러미로는 audit2000 목록만 쓰고, 다른 목록(gold_100 등)을 쓰려면 그 wav 폴더로
    꾸러미를 따로 만든다. 안 그러면 서버에서 "음성을 찾지 못했다" 가 뜬다.

쓰는 법
-------
    # ① 무엇이 담기는지 먼저 눈으로 본다 (tar 를 만들지 않는다)
    python deploy/runpod/pack_workbench.py --dry-run

    # ② 음성 없이 스크립트·목록만 묶는다 (몇 MB — 학습·평가용)
    python deploy/runpod/pack_workbench.py --out D:/해커톤데이터/workbench.tar.gz

    # ③ 음성까지 묶는다 (1.9GB — 증인 받아쓰기용. 시간이 꽤 걸린다)
    python deploy/runpod/pack_workbench.py --out D:/해커톤데이터/workbench_audio.tar.gz \
        --audio D:/해커톤데이터/audit2000/wav

    # ④ 경로 고치는 규칙이 맞는지 예시로 확인한다
    python deploy/runpod/pack_workbench.py --selftest

올린 다음은 `deploy/runpod/runpod_setup.sh` 와 `작업_순서.md` 를 따른다.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import tarfile
import time
from pathlib import Path

# ── 어디에 무엇이 있는지 ─────────────────────────────────────────────────────
# 이 파일은 assessment/deploy/runpod/ 에 있다. 두 칸 올라가면 assessment,
# 세 칸 올라가면 저장소 맨 위다.
ASSESSMENT_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = ASSESSMENT_DIR.parent

#: 꾸러미를 풀었을 때 생기는 맨 위 폴더 이름.
DEFAULT_PREFIX = "ktest_workbench"

#: 음성을 담을 자리. data 폴더 기준 상대 경로이며, 목록 파일의 `audio` 도 이 값으로 고친다.
#: 내 PC 의 `D:/해커톤데이터/audit2000/wav` 와 같은 이름을 써서 헷갈리지 않게 했다.
DEFAULT_AUDIO_SUBDIR = "audit2000/wav"

#: 담지 않을 것들. 파이썬이 만든 찌꺼기와 편집기 임시 파일이다.
SKIP_DIR_NAMES = {"__pycache__", ".pytest_cache", ".ipynb_checkpoints", ".git"}
SKIP_SUFFIXES = {".pyc", ".pyo", ".swp"}


def _should_skip(path: Path) -> bool:
    """담지 말아야 할 파일·폴더인지 본다."""
    # 경로 어디엔가 __pycache__ 같은 폴더가 끼어 있으면 통째로 건너뛴다
    if any(part in SKIP_DIR_NAMES for part in path.parts):
        return True
    return path.suffix.lower() in SKIP_SUFFIXES


def is_windows_path(audio: str) -> bool:
    """내 윈도우 PC 자리를 가리키는 경로인지 본다.

    두 가지 중 하나면 윈도우 자리로 친다.
      · `D:/…` `C:\\…` 처럼 드라이브 글자로 시작한다
      · 역슬래시(`\\`)가 들어 있다 — 리눅스 경로에는 안 쓰는 글자다
    """
    a = audio.strip()
    if "\\" in a:
        return True
    # 두 번째 글자가 ':' 이고 첫 글자가 영문이면 드라이브 글자다 (예: D:/…)
    return len(a) >= 2 and a[1] == ":" and a[0].isalpha()


def rewrite_audio_path(row: dict, audio_subdir: str, drop_zip: bool) -> tuple[dict, str]:
    """목록 한 줄의 음성 경로를 '리눅스 서버에서 맞는 상대 경로'로 고친다.

    입력이 무엇이고 출력이 무엇인지가 분명한 함수라, `--selftest` 로 예시를 넣어
    눈으로 값을 확인할 수 있게 따로 떼어 두었다(채점 자질 추출기와 같은 규칙).

    **윈도우 자리를 가리키는 줄만 고친다.** 파일 이름은 그대로 두고 앞의 폴더 자리만
    바꾼다. 즉 `D:/해커톤데이터/audit2000/wav/A.wav` → `audit2000/wav/A.wav`.

    이미 `pairs/71479/A.wav` 처럼 data 폴더 기준 상대 경로로 적힌 줄은 **손대지
    않는다.** 그런 줄까지 한 폴더로 몰아 버리면 원래 맞던 자리를 망가뜨린다
    (`--selftest` 를 처음 돌렸을 때 실제로 이 실수가 잡혀서 규칙을 이렇게 좁혔다).

    drop_zip 이 참이면 `zip_path`·`zip_member` 를 비운다. 왜냐하면 그 둘은 내 PC 의
    zip 파일을 가리키는데 서버에는 그 zip 이 없다. 값을 남겨 두면 wav 를 못 찾았을 때
    "zip 을 열다 실패" 라는 엉뚱한 오류가 나서 진짜 원인(wav 를 안 올렸다)이 가려진다.

    돌려주는 것: (고친 줄, 무엇을 했는지 표시)
      표시는 "" (그대로) · "audio" (경로만 고침) · "zip" (zip 칸만 비움) ·
      "audio+zip" (둘 다) 넷 중 하나다.
    """
    audio = row.get("audio")
    did: list[str] = []

    # 음성 칸이 아예 없는 목록(team2500 처럼 zip 만 가리키는 것)은 손댈 것이 없다
    if isinstance(audio, str) and audio.strip() and is_windows_path(audio):
        # 역슬래시와 슬래시를 함께 쪼갠다. 둘이 섞인 줄도 있다
        name = audio.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
        if name:
            row = dict(row)          # 원본 줄을 그대로 두려고 사본을 만든다
            row["audio"] = f"{audio_subdir.strip('/')}/{name}"
            did.append("audio")

    if drop_zip and (row.get("zip_path") or row.get("zip_member")):
        row = dict(row) if not did else row
        row["zip_path"] = None
        row["zip_member"] = None
        did.append("zip")

    return row, "+".join(did)


def build_manifest_bytes(path: Path, audio_subdir: str,
                         drop_zip: bool) -> tuple[bytes, int, int, int]:
    """목록 파일 하나를 읽어, 경로를 고친 사본을 바이트로 만든다.

    돌려주는 것: (파일 내용, 전체 줄 수, 음성 경로를 고친 줄 수, zip 칸을 비운 줄 수)
    """
    out_lines: list[str] = []
    total = 0
    audio_fixed = 0
    zip_dropped = 0

    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            total += 1
            row = json.loads(line)
            row, did = rewrite_audio_path(row, audio_subdir, drop_zip)
            if "audio" in did:
                audio_fixed += 1
            if "zip" in did:
                zip_dropped += 1
            # ensure_ascii=False 로 한글을 그대로 둔다(사람이 열어 볼 수 있게)
            out_lines.append(json.dumps(row, ensure_ascii=False))

    data = ("\n".join(out_lines) + "\n").encode("utf-8")
    return data, total, audio_fixed, zip_dropped


# ── 담을 목록 만들기 ─────────────────────────────────────────────────────────
class Entry:
    """꾸러미에 들어갈 것 하나.

    두 가지가 있다.
      · 그냥 담는 파일   — `source` 에 원본 자리가 있다
      · 고쳐서 담는 파일 — `data` 에 만들어 낸 내용이 들어 있다 (목록 파일)
    """

    def __init__(self, arcname: str, source: Path | None = None,
                 data: bytes | None = None, note: str = ""):
        self.arcname = arcname                                  # 꾸러미 안에서의 자리
        self.source = source                                    # 원본 파일 (있으면)
        self.data = data                                        # 만들어 낸 내용 (있으면)
        self.note = note                                        # 사람에게 보여 줄 한마디
        self.size = len(data) if data is not None else (source.stat().st_size if source else 0)


def collect_entries(args) -> tuple[list[Entry], list[str]]:
    """꾸러미에 담을 것을 전부 모은다.

    돌려주는 것: (담을 것 목록, 사람에게 알릴 말 목록)
    """
    entries: list[Entry] = []
    notes: list[str] = []
    prefix = args.prefix

    # ① 실험실 스크립트 전부 (requirements-lab.txt 도 이 안에 있다)
    lab_dir = ASSESSMENT_DIR / "scripts" / "speech_lab"
    if not lab_dir.is_dir():
        raise SystemExit(f"speech_lab 폴더를 못 찾았다: {lab_dir}")
    for p in sorted(lab_dir.rglob("*")):
        if p.is_file() and not _should_skip(p):
            rel = p.relative_to(REPO_ROOT).as_posix()
            entries.append(Entry(f"{prefix}/{rel}", source=p))

    # ② 채점 코드. eval_ab 의 `--model gemini` 갈래와 소리 크기 재기가 이것을 빌려 쓴다.
    #    무겁지 않고(1MB 남짓), 없으면 그 두 기능만 조용히 죽으므로 기본으로 담는다.
    if not args.no_src:
        src_dir = ASSESSMENT_DIR / "src"
        for p in sorted(src_dir.rglob("*")):
            if p.is_file() and not _should_skip(p):
                rel = p.relative_to(REPO_ROOT).as_posix()
                entries.append(Entry(f"{prefix}/{rel}", source=p))

    # ③ 목록 파일. 여기만 내용을 고쳐서 담는다
    man_dir = REPO_ROOT / "data" / "manifests"
    if not man_dir.is_dir():
        raise SystemExit(f"목록 폴더를 못 찾았다: {man_dir}")
    total_fixed = 0
    total_zip = 0
    for p in sorted(man_dir.glob("*.jsonl")):
        data, rows, fixed, zipped = build_manifest_bytes(
            p, args.audio_subdir, not args.keep_zip_paths)
        total_fixed += fixed
        total_zip += zipped
        rel = p.relative_to(REPO_ROOT).as_posix()
        entries.append(Entry(f"{prefix}/{rel}", data=data,
                             note=f"{rows}줄 · 경로 고침 {fixed} · zip 칸 비움 {zipped}"))
    notes.append(f"목록 파일의 음성 경로 {total_fixed}줄을 '{args.audio_subdir}/…' 로 고쳤다 "
                 f"(윈도우 자리를 가리키던 줄만). zip 칸을 비운 줄 {total_zip}")

    # ④ 음성 (옵션). 이것이 꾸러미 크기의 거의 전부를 차지한다
    if args.audio:
        audio_dir = Path(args.audio)
        if not audio_dir.is_dir():
            raise SystemExit(f"음성 폴더를 못 찾았다: {audio_dir}")
        wavs = sorted(audio_dir.glob("*.wav"))
        if not wavs:
            notes.append(f"[주의] {audio_dir} 안에 wav 가 하나도 없다")
        for p in wavs:
            entries.append(Entry(f"{prefix}/data/{args.audio_subdir}/{p.name}", source=p))
        notes.append(f"음성 {len(wavs)}개를 data/{args.audio_subdir}/ 에 담는다")
    else:
        notes.append("음성은 담지 않았다(--audio 를 안 줬다). "
                     "받아쓰기를 돌리려면 음성이 서버에 따로 있어야 한다")

    # ⑤ 덤으로 넣고 싶은 것 (v3 학습용 라벨 파일 등)
    for extra in args.extra:
        p = Path(extra)
        if not p.exists():
            raise SystemExit(f"--extra 로 준 것이 없다: {p}")
        if p.is_file():
            entries.append(Entry(f"{prefix}/extra/{p.name}", source=p, note="--extra"))
        else:
            for q in sorted(p.rglob("*")):
                if q.is_file() and not _should_skip(q):
                    entries.append(Entry(f"{prefix}/extra/{p.name}/{q.relative_to(p).as_posix()}",
                                         source=q, note="--extra"))

    return entries, notes


# ── 사람에게 보여 주기 ───────────────────────────────────────────────────────
def human(n: int) -> str:
    """바이트 수를 읽기 쉬운 말로 바꾼다."""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f}{unit}" if unit != "B" else f"{n}B"
        n /= 1024.0
    return f"{n:.1f}GB"


def report(entries: list[Entry], notes: list[str], show_all: bool) -> None:
    """무엇이 얼마나 담기는지 표로 찍는다.

    묶기 전에 이걸 먼저 보게 하는 까닭: 실수로 1.9GB 짜리 음성을 넣거나
    반대로 꼭 필요한 목록을 빠뜨린 채 서버에 올리면 시간을 통째로 날린다.
    """
    # 맨 위 두 칸(예: ktest_workbench/data/manifests)으로 묶어서 센다
    groups: dict[str, list[Entry]] = {}
    for e in entries:
        parts = e.arcname.split("/")
        key = "/".join(parts[1:3]) if len(parts) > 2 else "/".join(parts[1:])
        groups.setdefault(key, []).append(e)

    print("=" * 70)
    print(" 꾸러미에 담길 것")
    print("=" * 70)
    for key in sorted(groups):
        items = groups[key]
        size = sum(i.size for i in items)
        print(f"  {key:<32} {len(items):>6}개  {human(size):>9}")

    total_size = sum(e.size for e in entries)
    print("-" * 70)
    print(f"  {'합계':<32} {len(entries):>6}개  {human(total_size):>9}")

    # 목록 파일은 내용을 고쳐 담으므로 몇 줄을 고쳤는지 하나씩 보여 준다
    fixed_notes = [e for e in entries if e.note and "줄 ·" in e.note]
    if fixed_notes:
        print()
        print(" 목록 파일(경로를 고쳐서 담는 것):")
        for e in fixed_notes:
            print(f"  - {e.arcname.split('/')[-1]:<28} {e.note}")

    # 큰 것 몇 개를 보여 준다. 뜻밖에 큰 파일이 끼어 있으면 여기서 눈에 띈다
    biggest = sorted(entries, key=lambda e: e.size, reverse=True)[:5]
    print()
    print(" 큰 파일 5개:")
    for e in biggest:
        print(f"  - {human(e.size):>9}  {e.arcname}")

    if show_all:
        print()
        print(" 전체 목록:")
        for e in entries:
            print(f"  {human(e.size):>9}  {e.arcname}")

    if notes:
        print()
        for n in notes:
            print(f" * {n}")


def write_tar(entries: list[Entry], out_path: Path) -> None:
    """실제로 tar.gz 를 만든다."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()

    with tarfile.open(out_path, "w:gz") as tar:
        for i, e in enumerate(entries, 1):
            if e.data is not None:
                # 고쳐서 만든 내용은 파일이 없으므로 정보를 직접 만들어 넣는다
                info = tarfile.TarInfo(name=e.arcname)
                info.size = len(e.data)
                info.mtime = int(time.time())
                tar.addfile(info, io.BytesIO(e.data))
            else:
                tar.add(e.source, arcname=e.arcname)
            # 음성까지 담으면 수천 개라 진행 상황을 보여 준다
            if i % 500 == 0:
                print(f"  … {i}/{len(entries)}개 담음")

    elapsed = time.perf_counter() - started
    made = out_path.stat().st_size
    print()
    print(f" 만들었다: {out_path}")
    print(f" 크기 {human(made)} · {elapsed:.1f}초 걸림")
    print()
    print(" 서버로 올리는 법(둘 중 편한 쪽):")
    print(f"   runpodctl send {out_path}")
    print(f"   scp -P <포트> {out_path} root@<주소>:/workspace/")


def selftest(audio_subdir: str) -> int:
    """경로 고치는 규칙을 예시로 확인한다. 서버에 올리기 전에 눈으로 보는 자리다."""
    cases = [
        ("윈도우 D드라이브 절대경로 (audit2000)",
         {"id": "A", "audio": "D:/해커톤데이터/audit2000/wav/A.wav",
          "zip_path": "C:\\해커톤\\data\\Sample.zip", "zip_member": "Sample/…/A."},
         f"{audio_subdir}/A.wav"),
        ("윈도우 역슬래시 경로 (gold_100)",
         {"id": "B", "audio": "C:\\해커톤\\data\\audit\\wav\\B.wav",
          "zip_path": None, "zip_member": None},
         f"{audio_subdir}/B.wav"),
        ("이미 data 기준 상대경로인 것 (gold_present) — 손대면 안 된다",
         {"id": "C", "audio": "pairs/71479/C.wav", "zip_path": None, "zip_member": None},
         "pairs/71479/C.wav"),
        ("음성 칸이 아예 없는 줄 (team2500 — zip 만 가리킴)",
         {"id": "D", "zip_path": "C:\\해커톤\\data\\Sample.zip", "zip_member": "Sample/…/D."},
         None),
    ]

    print("=" * 70)
    print(" 경로 고치기 규칙 확인 (drop_zip=True)")
    print("=" * 70)
    ok = True
    for label, row, expected in cases:
        # 원본 줄이 바뀌지 않는지도 함께 보려고 미리 적어 둔다
        before_audio = row.get("audio")
        fixed, did = rewrite_audio_path(row, audio_subdir, drop_zip=True)
        got = fixed.get("audio")

        print(f"\n [{label}]")
        print(f"   전: audio={before_audio!r}  zip_path={row.get('zip_path')!r}")
        print(f"   후: audio={got!r}  zip_path={fixed.get('zip_path')!r}")
        print(f"   한 일: {did or '(그대로)'}")
        print(f"   기대값: {expected!r}  ->  {'맞음' if got == expected else '**틀림**'}")

        if got != expected:
            ok = False
        # zip 칸은 어느 경우든 비어 있어야 한다(서버에 그 zip 이 없으므로)
        if fixed.get("zip_path") is not None:
            print("   **틀림** zip_path 가 안 비워졌다")
            ok = False
        # 사본만 고치는 규칙이 지켜졌는지 — 원본 줄은 그대로여야 한다
        if row.get("audio") != before_audio:
            print("   **틀림** 원본 줄이 바뀌었다")
            ok = False

    print()
    if ok:
        print(" 확인 끝 — 4가지 다 통과. 원본 줄도 안 바뀌었다.")
        return 0
    print(" 확인 실패 — 위의 **틀림** 줄을 보라.")
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(
        description="RunPod 에 올릴 작업 꾸러미를 만든다",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--out", help="만들 tar.gz 자리. 안 주면 목록만 보여 준다")
    ap.add_argument("--dry-run", action="store_true",
                    help="담길 것을 보여 주기만 하고 tar 는 만들지 않는다")
    ap.add_argument("--audio", default="",
                    help="담을 wav 폴더 (예: D:/해커톤데이터/audit2000/wav). "
                         "안 주면 음성은 안 담는다")
    ap.add_argument("--audio-subdir", default=DEFAULT_AUDIO_SUBDIR,
                    help=f"꾸러미 안에서 음성이 놓일 자리 (기본 {DEFAULT_AUDIO_SUBDIR})")
    ap.add_argument("--prefix", default=DEFAULT_PREFIX,
                    help=f"꾸러미를 풀면 생기는 맨 위 폴더 이름 (기본 {DEFAULT_PREFIX})")
    ap.add_argument("--extra", action="append", default=[],
                    help="덤으로 담을 파일·폴더 (v3 학습 라벨 등). 여러 번 줄 수 있다")
    ap.add_argument("--no-src", action="store_true",
                    help="채점 코드(assessment/src)를 빼고 담는다")
    ap.add_argument("--keep-zip-paths", action="store_true",
                    help="목록의 zip_path 를 지우지 않는다(내 PC 에서 다시 쓸 때만)")
    ap.add_argument("--list-all", action="store_true", help="담길 파일을 전부 찍는다")
    ap.add_argument("--selftest", action="store_true",
                    help="경로 고치는 규칙을 예시 입력으로 확인한다")
    args = ap.parse_args()

    # 윈도우 콘솔에서 한글이 깨지지 않게 한다
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    if args.selftest:
        return selftest(args.audio_subdir.strip("/"))

    entries, notes = collect_entries(args)
    report(entries, notes, args.list_all)

    if args.dry_run or not args.out:
        print()
        if not args.out:
            print(" (--out 을 안 줘서 만들지 않았다. 실제로 묶으려면 --out 을 준다)")
        else:
            print(" (--dry-run 이라 만들지 않았다)")
        return 0

    print()
    print(" 묶는 중…")
    write_tar(entries, Path(args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
