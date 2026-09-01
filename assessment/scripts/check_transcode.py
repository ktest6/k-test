"""브라우저 녹음(webm)을 wav 로 바꿔도 소리가 상하지 않는지 **숫자로 확인**하는 스크립트.

**왜 이걸 만들었나.**
2026-08-30 부터 채점 서버는 응시자 음성이 wav 가 아니면 입구에서 wav 로 바꾼다
(`src/speech/audio.py` 의 `ensure_wav`). 브라우저 녹음이 webm 이라 안 바꾸면 받아쓰기가
아예 안 되기 때문이다. 그런데 형식을 바꾸는 것은 **소리를 건드리는 일**이라, 심사에서
"그 변환 때문에 점수가 달라지는 것 아니냐"는 질문이 반드시 나온다.
"안 달라집니다"라고 말로 답하지 않기 위해, 원본과 변환본의 차이를 재서 표로 내놓는다.

**무엇을 하나.**
    원본 소리 → (ffmpeg) webm/opus 로 압축 → 우리 채점 서버의 변환 경로 → wav 복원
    복원한 wav 를 원본 wav 와 견줘 본다.

재는 것 네 가지 + 하나
    길이 차이(ms)   : 앞뒤가 잘리지 않았는가
    SNR(dB)         : 원본 대비 얼마나 잡음이 섞였는가. 클수록 좋다
    상관계수         : 파형이 원본과 얼마나 같은 모양인가(1에 가까울수록 같다)
    RMS 차이(%)     : 소리 크기가 얼마나 달라졌는가 (무음 관문이 이 값을 본다)
    CER 차이         : **점수에 실제로 닿는 값.** 원본과 복원본을 각각 받아쓰게 해서
                      글자 오류율이 얼마나 달라지는지 본다. 위 네 가지가 조금 나빠져도
                      받아쓴 글이 같으면 채점 결과는 같다.

받아쓰기는 우리 LoRA 가 아니라 **로컬 faster-whisper small** 로 한다. LoRA 서버는
켜져 있어야 하고 그래픽카드도 필요해서 이 확인 하나 하려고 띄우기 번거롭고,
여기서 보려는 것은 "우리 모델이 얼마나 잘 받아쓰나"가 아니라 "변환 전후가 같은가"라
받아쓰는 기계가 무엇이든 상관없기 때문이다.

**쓰는 법**
    python scripts/check_transcode.py                      (기본 파일로)
    python scripts/check_transcode.py 어떤소리.m4a
    python scripts/check_transcode.py --no-stt             (받아쓰기 비교는 건너뛴다)
    python scripts/check_transcode.py --selftest           (ffmpeg 없이 계산식만 확인)

**이 PC 에서는 못 돌린다(2026-08-30).** 여기에는 ffmpeg 가 깔려 있지 않다.
그 경우 이 스크립트는 무엇이 없는지 알려 주고 그냥 끝난다 — 없는 값을 지어내지 않는다.
계산식이 맞는지만이라도 보고 싶으면 `--selftest` 를 쓴다(ffmpeg 없이 돈다).
"""

from __future__ import annotations

import argparse
import array
import io
import json
import math
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

# 이 스크립트를 어디서 돌려도 assessment 폴더를 찾을 수 있게 경로를 잡아 둔다
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.speech.audio import (  # noqa: E402
    FFMPEG_ENV,
    FetchedAudio,
    ensure_wav,
    ffmpeg_executable,
    sniff_format,
)
from src.speech.port import SttUnavailable  # noqa: E402

#: 입력을 안 주면 이 차례로 찾아 쓴다. 앞의 것이 있으면 뒤는 보지 않는다.
DEFAULT_INPUTS = [
    ROOT / "내목소리.m4a",
    Path("D:/해커톤데이터/audit2000/wav"),
]

#: 받아쓰기 비교에 쓸 파이썬. faster-whisper 가 깔려 있는 별도 가상환경이다
#: (채점 서버 쪽에는 안 깐다 — 확인용 도구를 운영 의존성으로 들이지 않으려는 것).
WITNESS_PYTHON = Path("D:/해커톤데이터/witness-venv/Scripts/python.exe")

#: 비교에 쓸 받아쓰기 모델 크기. small 이면 이 확인에는 충분하고 CPU 로도 돈다
WITNESS_MODEL = "small"


# ---------------------------------------------------------------------------
# 소리를 숫자로 읽고 견주는 부분 (여기가 계산의 알맹이다)
# ---------------------------------------------------------------------------


def read_wav_samples(data: bytes) -> tuple[list[float], int]:
    """wav 알맹이를 (-1 ~ 1 사이의 숫자 목록, 초당 칸 수)로 읽는다.

    16비트 모노만 다룬다. 우리 변환 경로가 언제나 16kHz 모노 16비트로 내놓으므로
    여기서 다른 경우를 다룰 일이 없고, 다루려 들면 오히려 조용히 틀릴 여지가 생긴다.
    """
    with wave.open(io.BytesIO(data), "rb") as handle:
        channels = handle.getnchannels()
        width = handle.getsampwidth()
        rate = handle.getframerate()
        raw = handle.readframes(handle.getnframes())

    if width != 2:
        raise ValueError(f"16비트 wav 만 다룬다(이 파일은 {width * 8}비트).")

    # 2바이트 정수 배열로 읽어 -1~1 사이로 눈금을 맞춘다(파일마다 크기가 달라도 견줄 수 있게)
    values = array.array("h")
    values.frombytes(raw)
    if channels > 1:
        # 스테레오면 채널을 평균 내어 모노로 만든다
        mono = [
            sum(values[i : i + channels]) / channels
            for i in range(0, len(values) - channels + 1, channels)
        ]
    else:
        mono = list(values)
    return [v / 32768.0 for v in mono], rate


def rms(values: list[float]) -> float:
    """소리 크기(제곱평균제곱근). 무음 관문이 보는 것과 같은 종류의 값이다."""
    if not values:
        return 0.0
    return math.sqrt(sum(v * v for v in values) / len(values))


def best_lag(a: list[float], b: list[float], max_lag: int = 1600) -> int:
    """두 소리가 몇 칸 밀려 있는지 찾는다.

    왜 필요한가: opus 로 압축하면 소리가 아주 조금(수 ms) 뒤로 밀린다. 밀린 채로
    빼기를 하면 실제로는 똑같은 소리인데도 "완전히 다르다"는 값이 나온다.
    그래서 가장 잘 겹치는 자리를 먼저 찾고 나서 견준다.

    max_lag 는 16kHz 기준 0.1초. opus 의 밀림은 이보다 훨씬 작아서 넉넉하다.
    """
    # 앞머리 일부만 봐도 밀림은 찾을 수 있다(전체를 다 보면 느리기만 하다)
    window = min(len(a), len(b), 16_000 * 3)
    if window <= 0:
        return 0

    최고점수 = None
    최고밀림 = 0
    for lag in range(-max_lag, max_lag + 1):
        # lag 만큼 밀어서 겹치는 구간만 곱해 더한다. 값이 클수록 잘 겹친 것이다
        if lag >= 0:
            길이 = min(window, len(b) - lag, len(a))
            if 길이 <= 0:
                continue
            점수 = sum(a[i] * b[i + lag] for i in range(0, 길이, 4))
        else:
            길이 = min(window, len(a) + lag, len(b))
            if 길이 <= 0:
                continue
            점수 = sum(a[i - lag] * b[i] for i in range(0, 길이, 4))
        if 최고점수 is None or 점수 > 최고점수:
            최고점수 = 점수
            최고밀림 = lag
    return 최고밀림


def compare_pcm(원본: list[float], 복원: list[float]) -> dict:
    """두 소리를 견줘서 숫자 네 개를 낸다.

    - lag_samples : 몇 칸 밀려 있었는지(정렬에 쓴 값)
    - snr_db      : 원본 대비 얼마나 잡음이 섞였는가. 20dB 면 잡음이 원본의 1/10 크기
    - correlation : 파형 모양이 얼마나 같은가 (1이면 완전히 같은 모양)
    - rms_diff_pct: 소리 크기가 몇 % 달라졌는가

    이 함수는 ffmpeg 없이도 돌아간다(--selftest 가 여기만 확인한다).
    """
    밀림 = best_lag(원본, 복원)

    # 밀림을 없앤 뒤 겹치는 구간만 남긴다
    if 밀림 >= 0:
        a = 원본
        b = 복원[밀림:]
    else:
        a = 원본[-밀림:]
        b = 복원
    n = min(len(a), len(b))
    a, b = a[:n], b[:n]
    if n == 0:
        return {"lag_samples": 밀림, "snr_db": float("nan"),
                "correlation": float("nan"), "rms_diff_pct": float("nan")}

    # SNR: 원본의 힘 대비 '원본과 복원의 차이'의 힘. 차이가 작을수록 값이 커진다
    신호 = sum(x * x for x in a)
    잡음 = sum((x - y) ** 2 for x, y in zip(a, b))
    snr = 10 * math.log10(신호 / 잡음) if 잡음 > 0 and 신호 > 0 else float("inf")

    # 상관계수: 두 파형이 같은 모양으로 오르내리는가
    평균a = sum(a) / n
    평균b = sum(b) / n
    분자 = sum((x - 평균a) * (y - 평균b) for x, y in zip(a, b))
    분모 = math.sqrt(sum((x - 평균a) ** 2 for x in a) * sum((y - 평균b) ** 2 for y in b))
    상관 = 분자 / 분모 if 분모 > 0 else float("nan")

    # 소리 크기 차이(%). 무음 관문이 보는 값이 얼마나 흔들리는지다
    rms_a, rms_b = rms(a), rms(b)
    크기차 = abs(rms_b - rms_a) / rms_a * 100 if rms_a > 0 else float("nan")

    return {
        "lag_samples": 밀림,
        "snr_db": snr,
        "correlation": 상관,
        "rms_diff_pct": 크기차,
    }


def cer(정답: str, 비교: str) -> float:
    """글자 오류율(CER). 두 글이 몇 글자나 다른지를 정답 길이로 나눈 값이다.

    0 이면 완전히 같고, 0.1 이면 열 글자에 한 글자 꼴로 다르다는 뜻이다.
    띄어쓰기는 빼고 센다(형식 변환이 띄어쓰기를 흔드는 것은 우리 관심사가 아니다).
    """
    a = "".join(정답.split())
    b = "".join(비교.split())
    if not a:
        return 0.0 if not b else 1.0

    # 편집 거리(한 글자씩 고쳐서 같게 만드는 데 드는 최소 횟수)를 한 줄씩 채워 구한다
    앞줄 = list(range(len(b) + 1))
    for i, 글자a in enumerate(a, start=1):
        현재줄 = [i]
        for j, 글자b in enumerate(b, start=1):
            현재줄.append(min(
                앞줄[j] + 1,                              # 지우기
                현재줄[j - 1] + 1,                        # 넣기
                앞줄[j - 1] + (0 if 글자a == 글자b else 1),  # 바꾸기
            ))
        앞줄 = 현재줄
    return 앞줄[-1] / len(a)


# ---------------------------------------------------------------------------
# ffmpeg 로 webm 만들기
# ---------------------------------------------------------------------------


def encode_webm(wav_bytes: bytes, ffmpeg: str) -> bytes:
    """wav 를 브라우저 녹음과 같은 형식(webm/opus)으로 만든다.

    비트레이트를 지정하지 않는다. 브라우저 MediaRecorder 의 기본값에 가까운
    ffmpeg 기본값 그대로 눌러야 '실제로 들어오는 답안'과 같은 조건이 되기 때문이다.

    결과를 임시 파일로 받는 이유: webm(마트료시카) 껍데기는 다 쓰고 나서 앞머리를
    고쳐 쓰는 자리가 있어서 표준출력으로 흘려보내면 ffmpeg 판에 따라 실패한다.
    """
    with tempfile.TemporaryDirectory() as 임시방:
        out = Path(임시방) / "encoded.webm"
        done = subprocess.run(
            [ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
             "-i", "pipe:0", "-c:a", "libopus", str(out)],
            input=wav_bytes,
            capture_output=True,
            timeout=300,
        )
        if done.returncode != 0 or not out.exists():
            사유 = (done.stderr or b"").decode("utf-8", errors="replace")[-400:]
            raise RuntimeError(f"webm 으로 누르지 못했다(코드 {done.returncode}): {사유}")
        return out.read_bytes()


def load_as_wav(path: Path) -> bytes:
    """어떤 형식이든 우리 변환 경로를 태워 16kHz 모노 wav 로 만든다.

    채점 서버가 응시자 음성에 하는 일과 **똑같은 함수**(ensure_wav)를 쓴다.
    여기서만 따로 변환하면 "확인은 됐는데 서버에서는 다르다"가 된다.
    """
    data = path.read_bytes()
    형식 = sniff_format(data) or path.suffix.lstrip(".").lower() or "unknown"
    fetched = FetchedAudio(data=data, audio_format=형식, mime_type="application/octet-stream")
    return ensure_wav(fetched).data


# ---------------------------------------------------------------------------
# 받아쓰기 비교 (faster-whisper). 없으면 건너뛴다
# ---------------------------------------------------------------------------


WITNESS_SCRIPT = '''
import json, sys
from faster_whisper import WhisperModel

model = WhisperModel(sys.argv[1], device="cpu", compute_type="int8")
결과 = {}
for 이름, 경로 in (("original", sys.argv[2]), ("restored", sys.argv[3])):
    segments, _ = model.transcribe(경로, language="ko", beam_size=1)
    결과[이름] = "".join(s.text for s in segments).strip()
print(json.dumps(결과, ensure_ascii=False))
'''


def transcribe_pair(원본wav: bytes, 복원wav: bytes) -> tuple[dict | None, str]:
    """원본과 복원본을 각각 받아쓴다. 못 하면 (None, 왜 못 했는지)를 돌려준다.

    받아쓰기 도구가 없다고 해서 이 스크립트 전체를 실패로 만들지 않는다.
    소리 자체의 비교(SNR·상관)는 이미 나와 있고, 받아쓰기 비교는 거기에 더하는 값이다.
    """
    if not WITNESS_PYTHON.exists():
        return None, f"받아쓰기용 파이썬이 없다: {WITNESS_PYTHON}"

    with tempfile.TemporaryDirectory() as 임시방:
        원본경로 = Path(임시방) / "original.wav"
        복원경로 = Path(임시방) / "restored.wav"
        원본경로.write_bytes(원본wav)
        복원경로.write_bytes(복원wav)
        스크립트 = Path(임시방) / "run_whisper.py"
        스크립트.write_text(WITNESS_SCRIPT, encoding="utf-8")

        try:
            done = subprocess.run(
                [str(WITNESS_PYTHON), str(스크립트), WITNESS_MODEL,
                 str(원본경로), str(복원경로)],
                capture_output=True,
                timeout=1800,
            )
        except Exception as exc:  # noqa: BLE001 - 못 돌렸다는 사실만 알면 된다
            return None, f"받아쓰기를 돌리지 못했다: {exc}"

        if done.returncode != 0:
            사유 = (done.stderr or b"").decode("utf-8", errors="replace").strip()
            # faster-whisper 가 안 깔려 있으면 여기로 온다
            return None, f"받아쓰기가 실패했다: {사유[-300:]}"
        try:
            return json.loads((done.stdout or b"").decode("utf-8")), ""
        except ValueError:
            return None, "받아쓰기 결과를 읽지 못했다(JSON 이 아니다)."


# ---------------------------------------------------------------------------
# 입력 고르기 · 표 그리기
# ---------------------------------------------------------------------------


def pick_input(주어진것: str | None) -> Path | None:
    """확인에 쓸 소리 파일 하나를 고른다. 없으면 None."""
    # 사람이 지정했으면 그것만 본다(없으면 조용히 다른 파일로 바꿔치기하지 않는다)
    if 주어진것:
        후보 = Path(주어진것)
        return 후보 if 후보.is_file() else None

    for 후보 in DEFAULT_INPUTS:
        if 후보.is_file():
            return 후보
        # 폴더를 적어 뒀으면 그 안의 wav 아무거나 하나 쓴다
        if 후보.is_dir():
            wavs = sorted(후보.glob("*.wav"))
            if wavs:
                return wavs[0]
    return None


def print_table(줄들: list[tuple[str, str, str]]) -> None:
    """표 한 장을 그린다(항목 · 값 · 이게 무슨 뜻인지)."""
    머리 = ("항목", "값", "무슨 뜻인가")
    폭 = [max(_width(행[i]) for 행 in [머리, *줄들]) for i in range(3)]

    def 한줄(행):
        return "  ".join(칸 + " " * (폭[i] - _width(칸)) for i, 칸 in enumerate(행))

    print(한줄(머리))
    print("  ".join("-" * 폭[i] for i in range(3)))
    for 행 in 줄들:
        print(한줄(행))


def _width(글: str) -> int:
    """한글은 두 칸을 차지하므로 표를 맞추려면 따로 세어야 한다."""
    return sum(2 if ord(글자) > 0x2E80 else 1 for 글자 in 글)


def selftest() -> int:
    """ffmpeg 없이 **계산식만** 확인한다.

    일부러 만든 신호 두 쌍을 넣어 값이 상식과 맞는지 본다.
      - 똑같은 소리끼리 → SNR 은 무한대, 상관 1, 크기 차이 0
      - 조금 밀리고 잡음이 낀 소리 → 밀림을 찾아내고 SNR 이 유한한 값으로 나온다
    채점 로직은 눈으로 훑어서 맞는지 알기 어려우므로, 입력·출력이 분명한 이 함수만은
    값을 직접 찍어 확인할 수 있게 해 둔다.
    """
    import random

    random.seed(20260830)
    원본 = [math.sin(2 * math.pi * 440 * i / 16000) * 0.5 for i in range(16000)]

    같음 = compare_pcm(원본, list(원본))
    print("[1] 똑같은 소리끼리 견주기")
    print(f"    밀림={같음['lag_samples']}칸  SNR={같음['snr_db']}  "
          f"상관={같음['correlation']:.6f}  크기차={같음['rms_diff_pct']:.4f}%")
    assert 같음["lag_samples"] == 0
    assert 같음["snr_db"] == float("inf")
    assert abs(같음["correlation"] - 1.0) < 1e-9

    # 30칸 밀리고 아주 작은 잡음이 낀 소리
    밀린것 = [0.0] * 30 + [v + random.uniform(-0.005, 0.005) for v in 원본]
    다름 = compare_pcm(원본, 밀린것)
    print("[2] 30칸 밀리고 잡음이 조금 낀 소리")
    print(f"    밀림={다름['lag_samples']}칸  SNR={다름['snr_db']:.1f}dB  "
          f"상관={다름['correlation']:.6f}  크기차={다름['rms_diff_pct']:.3f}%")
    assert 다름["lag_samples"] == 30, "밀린 칸 수를 못 찾았다"
    assert 30 < 다름["snr_db"] < 60, "SNR 이 상식 밖이다"
    assert 다름["correlation"] > 0.99

    print("[3] 글자 오류율(CER)")
    print(f"    같은 글: {cer('기계가 멈췄습니다', '기계가 멈췄습니다'):.3f}")
    print(f"    한 글자 다름: {cer('기계가 멈췄습니다', '기계가 멈쳤습니다'):.3f}")
    assert cer("기계가 멈췄습니다", "기계가 멈췄습니다") == 0.0
    assert 0 < cer("기계가 멈췄습니다", "기계가 멈쳤습니다") < 0.2

    print("\n계산식 확인 통과. (소리 비교 자체는 ffmpeg 이 있어야 돌릴 수 있다)")
    return 0


# ---------------------------------------------------------------------------
# 본체
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="webm 변환 전후로 소리와 받아쓴 글이 얼마나 달라지는지 잰다."
    )
    parser.add_argument("audio", nargs="?", default=None,
                        help="확인할 소리 파일. 안 주면 기본 파일을 찾아 쓴다")
    parser.add_argument("--no-stt", action="store_true",
                        help="받아쓰기 비교를 건너뛴다(소리 비교만 한다)")
    parser.add_argument("--selftest", action="store_true",
                        help="ffmpeg 없이 계산식만 확인한다")
    args = parser.parse_args()

    if args.selftest:
        return selftest()

    # ── 0) ffmpeg 이 있어야 시작이라도 한다 ────────────────────────────────
    ffmpeg = ffmpeg_executable()
    if ffmpeg is None:
        print("=" * 70)
        print(" ffmpeg 이 없어서 이 확인은 할 수 없다.")
        print("=" * 70)
        print(" 이 스크립트는 소리를 webm 으로 눌렀다가 다시 펴 보는 일을 한다.")
        print(" 그 일을 하는 프로그램이 ffmpeg 인데, 이 컴퓨터에는 깔려 있지 않다.")
        print()
        print(" 깔고 나서 다시 돌리면 된다.")
        print("   윈도우 : winget install Gyan.FFmpeg   (또는 ffmpeg.org 에서 받아 압축 해제)")
        print("   우분투 : sudo apt-get install -y ffmpeg")
        print(f"   깔았는데도 못 찾으면 {FFMPEG_ENV} 환경변수로 ffmpeg.exe 자리를 알려 준다.")
        print()
        print(" 계산식이 맞는지만 보려면:  python scripts/check_transcode.py --selftest")
        return 1

    # ── 1) 확인에 쓸 소리 고르기 ──────────────────────────────────────────
    입력 = pick_input(args.audio)
    if 입력 is None:
        print("확인에 쓸 소리 파일을 찾지 못했다. 파일 하나를 인자로 넘겨 달라.")
        print("찾아본 자리:")
        for 후보 in DEFAULT_INPUTS:
            print(f"  - {후보}")
        return 1

    print(f"입력 파일 : {입력}  ({입력.stat().st_size / 1024:.0f} KB)")
    print(f"ffmpeg    : {ffmpeg}")
    print()

    # ── 2) 원본을 우리 규격(16kHz 모노 wav)으로 맞춘다 ─────────────────────
    #    이것을 '원본'으로 삼는다. 채점 서버가 실제로 채점하는 것이 이 모양이기 때문이다
    try:
        원본wav = load_as_wav(입력)
    except SttUnavailable as exc:
        print(f"원본을 wav 로 바꾸지 못했다: {exc}")
        return 1

    # ── 3) 브라우저 녹음과 같은 형식으로 눌렀다가 다시 편다 ────────────────
    try:
        webm = encode_webm(원본wav, ffmpeg)
    except Exception as exc:  # noqa: BLE001
        print(f"webm 으로 누르지 못했다: {exc}")
        return 1

    복원 = ensure_wav(
        FetchedAudio(data=webm, audio_format="webm", mime_type="audio/webm")
    )
    복원wav = 복원.data

    # ── 4) 견주기 ─────────────────────────────────────────────────────────
    원본샘플, 원본rate = read_wav_samples(원본wav)
    복원샘플, 복원rate = read_wav_samples(복원wav)
    결과 = compare_pcm(원본샘플, 복원샘플)

    원본길이 = round(len(원본샘플) / 원본rate * 1000)
    복원길이 = round(len(복원샘플) / 복원rate * 1000)

    줄들 = [
        ("원본 크기", f"{len(원본wav) / 1024:.0f} KB",
         f"{원본rate}Hz 모노 wav"),
        ("webm 크기", f"{len(webm) / 1024:.0f} KB",
         f"원본의 {len(webm) / len(원본wav) * 100:.0f}% (opus 기본 비트레이트)"),
        ("길이 차이", f"{복원길이 - 원본길이:+d} ms",
         f"원본 {원본길이}ms → 복원 {복원길이}ms"),
        ("밀림", f"{결과['lag_samples']}칸",
         f"약 {결과['lag_samples'] / 원본rate * 1000:.1f}ms (opus 특유의 지연, 정렬해서 뺐다)"),
        ("SNR", f"{결과['snr_db']:.1f} dB",
         "클수록 원본에 가깝다. 20dB 면 잡음이 원본의 1/10 크기"),
        ("상관계수", f"{결과['correlation']:.4f}",
         "1에 가까울수록 파형 모양이 같다"),
        ("RMS 차이", f"{결과['rms_diff_pct']:.2f} %",
         "소리 크기 변화. 무음 관문이 보는 값이다"),
    ]

    # ── 5) 받아쓰기까지 견준다(점수에 실제로 닿는 값) ──────────────────────
    받아쓴것 = None
    건너뛴이유 = ""
    if args.no_stt:
        건너뛴이유 = "--no-stt 로 건너뛰었다"
    else:
        print("받아쓰기 비교 중… (faster-whisper small, 처음이면 모델을 내려받느라 오래 걸린다)")
        받아쓴것, 건너뛴이유 = transcribe_pair(원본wav, 복원wav)

    if 받아쓴것:
        오류율 = cer(받아쓴것["original"], 받아쓴것["restored"])
        줄들.append(("받아쓴 글 차이(CER)", f"{오류율 * 100:.2f} %",
                     "0% 면 원본과 복원본을 똑같이 받아썼다는 뜻"))
    else:
        줄들.append(("받아쓴 글 차이(CER)", "확인 못 함", 건너뛴이유))

    print()
    print("=" * 70)
    print(" webm 변환 전후 비교")
    print("=" * 70)
    print_table(줄들)

    if 받아쓴것:
        print()
        print(" 원본을 받아쓴 글 : " + (받아쓴것["original"] or "(빈 글)"))
        print(" 복원본을 받아쓴 글: " + (받아쓴것["restored"] or "(빈 글)"))

    # ── 6) 초등학생도 읽을 수 있는 한 줄 ──────────────────────────────────
    print()
    print(한줄요약(결과, 복원길이 - 원본길이, 받아쓴것))
    return 0


def 한줄요약(결과: dict, 길이차: int, 받아쓴것: dict | None) -> str:
    """표를 못 읽는 사람에게 결론만 한 문장으로 말해 준다.

    좋게만 말하지 않는다. 값이 나쁘면 나쁘다고 적는다 — 이 스크립트는 자랑이 아니라
    확인이 목적이고, 나쁜 값을 좋게 적으면 확인한 의미가 없어진다.
    """
    snr = 결과["snr_db"]
    상관 = 결과["correlation"]
    # 차이가 아예 0이면 SNR 이 무한대로 나온다. 그대로 적으면 'infdB' 라고 찍히므로 말로 바꾼다
    snr글 = "무한대(차이가 전혀 없다)" if math.isinf(snr) else f"{snr:.0f}dB"

    # 받아쓴 글이 같으면 그것이 가장 강한 증거다. 점수는 받아쓴 글에서 나오기 때문이다
    if 받아쓴것 is not None:
        오류율 = cer(받아쓴것["original"], 받아쓴것["restored"])
        if 오류율 == 0:
            return ("한 줄로: 소리를 webm 으로 눌렀다 폈는데 **받아쓴 글이 한 글자도 안 달라졌다.** "
                    f"파형은 {snr글} 만큼 원본과 닮아 있고 길이는 {abs(길이차)}ms 차이라, "
                    "사람 귀로도 채점으로도 구분이 안 되는 수준이다.")
        if 오류율 < 0.05:
            return (f"한 줄로: 받아쓴 글이 {오류율 * 100:.1f}%(백 글자에 {오류율 * 100:.0f}글자 꼴)만 "
                    "달라졌다. 사람 귀로 구분 못 하는 수준이고 채점에도 거의 영향이 없다.")
        return (f"한 줄로: 받아쓴 글이 {오류율 * 100:.1f}% 달라졌다. **이건 그냥 넘길 수치가 아니다** "
                "— 비트레이트를 올리거나 변환 규격을 다시 봐야 한다.")

    # 받아쓰기를 못 했으면 소리 값만으로 말한다(과장하지 않는다)
    if snr >= 20 and 상관 >= 0.99:
        return (f"한 줄로: 소리를 webm 으로 눌렀다 폈는데 원본과 {상관:.3f} 만큼 같은 모양이고 "
                f"잡음은 {snr글} 아래로 작다. 사람 귀로 구분 못 하는 수준이다. "
                "(다만 받아쓴 글까지는 이번에 확인하지 못했다)")
    return (f"한 줄로: 변환 뒤 파형이 원본과 {상관:.3f} 만큼 닮았고 SNR 은 {snr:.1f}dB 다. "
            "**기대보다 낮으니 그대로 믿지 말고 원인을 봐야 한다.**")


if __name__ == "__main__":
    raise SystemExit(main())
