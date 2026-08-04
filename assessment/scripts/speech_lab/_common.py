# -*- coding: utf-8 -*-
"""speech_lab 의 다섯 스크립트가 함께 쓰는 도구 상자.

여기에는 **실험 도구만** 둔다. 채점에 실제로 쓰이는 코드는 `assessment/src/` 에 있고
이 폴더는 그것을 읽기만 한다(한 줄도 고치지 않는다).

왜 따로 뺐나:
글자 비교 규칙(공백·문장부호를 떼고 본다)이 스크립트마다 조금씩 달라지면
어제 잰 숫자와 오늘 잰 숫자를 나란히 놓을 수 없게 된다. 그래서 '재는 자'는
한 곳에만 두고 다섯 스크립트가 같은 자를 쓴다.
"""

from __future__ import annotations

import difflib
import http.server
import io
import json
import re
import socket
import sys
import threading
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

# ── 폴더 위치 ────────────────────────────────────────────────────────────────
#: 이 파일 = assessment/scripts/speech_lab/_common.py 이므로 세 칸 위가 assessment
ASSESSMENT_DIR = Path(__file__).resolve().parents[2]
#: 저장소 최상위 (C:\해커톤)
REPO_ROOT = ASSESSMENT_DIR.parent
#: 실험 데이터가 사는 곳. git 에 올리지 않는다(용량이 수 GB)
DATA_ROOT = REPO_ROOT / "data"


def enable_utf8_output() -> None:
    """윈도우 콘솔에서 한글이 깨지지 않게 출력 형식을 UTF-8 로 맞춘다.

    각 스크립트 맨 처음에 한 번 부른다. 이걸 안 하면 명령창 기본 설정(cp949)에서
    일부 글자가 출력되다 말고 오류로 끝나는 일이 생긴다.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            # 출력이 파일로 넘어가 있는 등 바꿀 수 없는 경우는 그냥 넘어간다
            pass


# ── 원본 데이터가 어디에 있는지 ──────────────────────────────────────────────
#: 세 가지 원본. 번호는 AI Hub 의 데이터셋 번호를 그대로 쓴다.
#:   71469 = 영어권 학습자 / 71479 = 아시아어권 학습자 / 505 = 외국인 한국어 발화
#: 앞의 둘은 zip 을 풀지 않고 안에서 바로 꺼내 쓴다(합쳐서 6GB 라 푸는 것이 손해).
SOURCES = {
    "71469": {"kind": "aihub_zip", "path": DATA_ROOT / "Sample.zip", "label": "영어권"},
    "71479": {"kind": "aihub_zip", "path": DATA_ROOT / "Sample (1).zip", "label": "아시아어권"},
    "505": {"kind": "aihub_dir", "path": DATA_ROOT / "New_Sample", "label": "외국인 한국어 발화"},
}


# ── 글자를 재는 자 ───────────────────────────────────────────────────────────
#: 비교할 때 떼어낼 것들: 공백·문장부호, 그리고 505 데이터가 '말이 끊겼다'는
#: 표시로 쓰는 '+' 기호. 이것들이 다르다고 오류로 세면 숫자가 부풀려진다.
_STRIP = re.compile(r"[\s.,?!…'\"·:;()~+\-]")


def norm_text(s: str) -> str:
    """두 글을 견주기 전에 사소한 차이를 걷어낸다.

    공백과 문장부호를 떼는 이유: 받아쓰기 모델마다 쉼표를 찍는 버릇이 달라서,
    그대로 두면 '말을 잘못했다'가 아니라 '쉼표를 안 찍었다'가 오류로 잡힌다.
    """
    return _STRIP.sub("", s or "")


def cer(ref: str, hyp: str) -> float:
    """정답 글과 받아쓴 글의 **글자 오류율**(CER)을 잰다. 0에 가까울수록 좋다.

    글자 하나를 고치거나 넣거나 빼는 횟수를 세어 정답 글자 수로 나눈 값이다.
    (같은 규칙을 8/2 첫 실측부터 써 왔다. 여기서 규칙을 바꾸면 예전 숫자와
     비교할 수 없게 되므로 손대지 않는다.)
    """
    r, h = norm_text(ref), norm_text(hyp)
    # 정답이 비어 있으면 나눌 수가 없다. 받아쓴 것도 비었으면 완벽, 아니면 전부 오류로 본다
    if not r:
        return 0.0 if not h else 1.0

    # 표를 한 줄씩만 들고 가며 채우는 방식(글이 길어도 메모리가 늘지 않는다)
    prev = list(range(len(h) + 1))
    for i, rc in enumerate(r, 1):
        cur = [i]
        for j, hc in enumerate(h, 1):
            # 넣기 / 빼기 / 바꾸기 중 가장 싼 길을 고른다
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (rc != hc)))
        prev = cur
    return prev[-1] / len(r)


def diff_pairs(prompt: str, ref: str) -> list[tuple[str, str]]:
    """낭독 과제에서 **학습자가 실제로 틀린 자리**를 (표준형, 발화형) 짝으로 뽑는다.

    낭독(LAR)은 읽을 문장(prompt)이 정해져 있고, 사람 전사(ref)는 응시자가
    실제로 어떻게 읽었는지를 오류까지 살려 적어 둔 것이다. 둘이 갈리는 어절이
    곧 오류 목록이다 — 사람이 귀로 확인해 만든 목록이라 이번 실험의 기준이 된다.

    돌려주는 짝의 뜻:
      ("동물을", "돈물을") 잘못 읽음   ("집에", "") 빼먹음   ("", "어") 없는 말을 넣음
    """
    pw, ow = (prompt or "").split(), (ref or "").split()
    out: list[tuple[str, str]] = []

    # 두 어절 목록을 나란히 맞춰 보고 어긋난 구간만 꺼낸다
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, pw, ow).get_opcodes():
        if tag == "replace":
            for a, b in zip(pw[i1:i2], ow[j1:j2]):
                # 문장부호만 다른 것은 오류가 아니므로 자를 대 보고 넣는다
                if norm_text(a) != norm_text(b):
                    out.append((a, b))
        elif tag == "delete":
            for a in pw[i1:i2]:
                out.append((a, ""))
        elif tag == "insert":
            for b in ow[j1:j2]:
                out.append(("", b))
    return out


# ── 목록 파일(JSONL) 읽고 쓰기 ───────────────────────────────────────────────
def write_manifest(rows: list[dict], out_path: Path) -> None:
    """추출한 (음성, 전사) 쌍 목록을 한 줄에 하나씩 적는다.

    JSONL(한 줄 = JSON 하나)로 두는 이유: 수만 줄이 돼도 앞에서부터 조금씩
    읽을 수 있고, HuggingFace 학습 코드가 이 형식을 그대로 받아 준다.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_manifest(path: Path) -> list[dict]:
    """목록 파일을 읽어 들인다. 빈 줄은 건너뛴다."""
    rows = []
    with Path(path).open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


# ── 음성 파일 꺼내 오기 ──────────────────────────────────────────────────────
#: 열어 둔 zip 을 재사용하기 위한 보관함. zip 을 열 때마다 목록을 다시 읽으면
#: (2만 개가 넘는다) 한 건 꺼낼 때마다 몇 초씩 손해다.
_ZIP_CACHE: dict[str, zipfile.ZipFile] = {}


def _get_zip(path: str) -> zipfile.ZipFile:
    """같은 zip 은 한 번만 연다."""
    if path not in _ZIP_CACHE:
        _ZIP_CACHE[path] = zipfile.ZipFile(path)
    return _ZIP_CACHE[path]


def load_audio_bytes(row: dict) -> bytes:
    """목록의 한 줄이 가리키는 wav 파일 내용을 통째로 읽어 온다.

    파일이 두 군데 중 하나에 있다.
      - 이미 풀어 놓은 wav (`audio` 가 가리키는 자리) — 있으면 이쪽을 먼저 쓴다
      - 아직 zip 안 (`zip_path` + `zip_member`) — 필요할 때만 꺼낸다
    이렇게 해 두면 `--extract-audio` 를 안 걸고 목록만 만들어 둔 상태에서도
    감사 킷이나 평가기가 그대로 돌아간다.
    """
    audio_rel = row.get("audio")
    if audio_rel:
        p = DATA_ROOT / audio_rel
        if p.exists():
            return p.read_bytes()

    zip_path, member = row.get("zip_path"), row.get("zip_member")
    if zip_path and member:
        return _get_zip(zip_path).read(member)

    raise FileNotFoundError(f"음성을 찾지 못했다: {row.get('id') or row.get('audio')}")


def measure_rms(wav_bytes: bytes) -> float | None:
    """녹음의 평균 소리 크기를 잰다(0~32767 눈금). wav 가 아니면 None.

    채점 쪽에 이미 있는 계산기(`src/speech/loudness.py`)를 그대로 빌려 쓴다.
    같은 자를 쓰기 위해서지, 이 폴더에서 새로 만들지 않는다.
    """
    if str(ASSESSMENT_DIR) not in sys.path:
        sys.path.insert(0, str(ASSESSMENT_DIR))
    from src.speech.loudness import measure_wav_loudness  # 읽기 전용으로 빌려 쓴다

    result = measure_wav_loudness(wav_bytes)
    return None if result is None else result.overall_rms


def wav_duration_sec(wav_bytes: bytes) -> float | None:
    """wav 의 길이를 초로 잰다. 라벨에 적힌 길이를 못 믿을 때 쓴다."""
    import wave

    try:
        with wave.open(io.BytesIO(wav_bytes)) as w:
            return w.getnframes() / float(w.getframerate())
    except Exception:
        return None


# ── Gemini 에게 음성을 보여 주기 위한 임시 서버 ──────────────────────────────
class _WavHandler(http.server.BaseHTTPRequestHandler):
    """wav 한 개만 내려주는 아주 작은 웹서버. 로그는 찍지 않는다."""

    data = b""

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "audio/wav")
        self.send_header("Content-Length", str(len(self.data)))
        self.end_headers()
        self.wfile.write(self.data)

    def log_message(self, *args):
        pass


@contextmanager
def serve_wav(wav_bytes: bytes):
    """wav 를 잠깐 인터넷 주소처럼 만들어 주고, 끝나면 곧바로 닫는다.

    왜 이런 짓을 하나: 채점 코드(`src/speech/gemini_stt.py`)는 백엔드가 넘겨주는
    **주소(URL)** 로 음성을 받도록 만들어져 있다. 실험하려고 그 코드를 고치면
    실제 채점 경로와 달라지므로, 대신 여기서 주소를 만들어 준다.
    주소는 내 컴퓨터 안(127.0.0.1)에서만 열리고 바깥에서는 보이지 않는다.
    """
    handler = type("_H", (_WavHandler,), {"data": wav_bytes})

    # 비어 있는 포트 번호를 운영체제에게 하나 받아 온다
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    server = http.server.HTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{port}/a.wav"
    finally:
        # 실험이 수백 건 돌아가므로 반드시 닫아 준다. 안 닫으면 포트가 쌓인다
        server.shutdown()
        server.server_close()


# ── 표 그리기 ────────────────────────────────────────────────────────────────
def print_table(headers: list[str], rows: list[list[str]]) -> None:
    """터미널에 표를 그린다. 한글은 두 칸을 차지하므로 그만큼 넓혀 맞춘다."""
    import unicodedata

    def width(text: str) -> int:
        # 'W'(넓음)·'F'(전각) 글자는 화면에서 두 칸을 먹는다
        return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)

    all_rows = [headers] + rows
    widths = [max(width(r[i]) for r in all_rows) for i in range(len(headers))]

    def line(cells: list[str]) -> str:
        return " | ".join(c + " " * (widths[i] - width(c)) for i, c in enumerate(cells))

    print(line(headers))
    print("-+-".join("-" * w for w in widths))
    for r in rows:
        print(line(r))


@dataclass
class Pair:
    """(음성 하나, 사람 전사 하나) 짝. 목록 파일의 한 줄이 이 모양이다."""

    id: str
    audio: str
    ref: str
    prompt: str
    task: str
    source: str
    speaker_id: str
    nationality: str
    topik_level: str
    duration_sec: float | None
    evals: dict
    zip_path: str | None = None
    zip_member: str | None = None

    def to_dict(self) -> dict:
        from dataclasses import asdict

        return asdict(self)
