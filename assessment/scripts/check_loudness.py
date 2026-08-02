"""무음 관문이 실제로 어떤 값을 재고 어떻게 판정하는지 눈으로 보는 스크립트.

**네트워크도 API 키도 쓰지 않는다.** 파일 안의 숫자만 계산하는 관문이라
언제 돌려도 같은 값이 나온다 — 그것이 이 관문을 둔 이유이기도 하다.

왜 이 스크립트가 있는가:
2026-08-02 에 소리가 전혀 없는 wav 로 78.07점 B 가 발급되는 것이 확인됐다.
받아쓰기 모델이 문항 지시문을 힌트 삼아 모범답안을 지어냈기 때문이다.
그래서 LLM 에게 물어보기 전에 소리 크기를 직접 재는 관문을 세웠는데,
기준값이 맞는지는 눈으로 값을 봐야 알 수 있다. 이 스크립트가 그 자리다.

보는 법:
  '가장 큰 0.1초' 칸이 판정 기준이다. 이 값이
      15 미만  -> 무음. 받아쓰기 모델을 부르지도 않는다
      60 미만  -> 너무 조용함. 글이 나와도 버린다
      그 이상  -> 정상. 받아쓰기로 넘어간다

실행:
    .venv\\Scripts\\python.exe scripts\\check_loudness.py
    .venv\\Scripts\\python.exe scripts\\check_loudness.py 녹음.wav 다른녹음.wav
"""

from __future__ import annotations

import io
import math
import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.speech.loudness import (  # noqa: E402
    SILENCE_RMS,
    SPEECH_FLOOR_RMS,
    is_silent,
    is_too_quiet_for_speech,
    measure_wav_loudness,
)


def make_wav(amplitude: int, seconds: float = 1.0,
             silent_head_s: float = 0.0, framerate: int = 24000) -> bytes:
    """소리 크기를 정해서 시험용 wav 를 만든다.

    사람 목소리 대신 단순한 '삐-' 소리를 쓴다.
    관문이 보는 것은 낱말이 아니라 소리의 크기뿐이라 이것으로 충분하다.
    """
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(framerate)
        # 앞에 조용한 구간을 붙일 수 있다(긴 침묵 끝에 한마디 한 답안을 흉내 낸다)
        frames = bytearray(b"\x00\x00" * int(framerate * silent_head_s))
        for index in range(int(framerate * seconds)):
            value = int(amplitude * math.sin(2 * math.pi * 440 * index / framerate))
            frames += int(value).to_bytes(2, "little", signed=True)
        handle.writeframes(bytes(frames))
    return buffer.getvalue()


def verdict(loudness) -> str:
    """이 소리 크기로 채점이 어떻게 되는지 한 마디로."""
    if loudness is None:
        return "잴 수 없음 -> 관문 건너뜀 (압축 형식이라 소리를 볼 수 없다)"
    if is_silent(loudness):
        return "무음      -> 받아쓰기 모델을 부르지 않고 503 (그 문항 미채점)"
    if is_too_quiet_for_speech(loudness):
        return "너무 조용 -> 글이 나와도 버리고 503 (지어낸 글로 본다)"
    return "정상      -> 받아쓰기로 넘어간다"


def show(label: str, payload: bytes) -> None:
    """한 줄로 잰 값과 판정을 보여 준다."""
    loudness = measure_wav_loudness(payload)
    if loudness is None:
        print(f"  {label:28s} {'-':>12s} {'-':>12s}  {verdict(None)}")
        return
    print(f"  {label:28s} {loudness.peak_window_rms:12,.1f} "
          f"{loudness.overall_rms:12,.1f}  {verdict(loudness)}")


def main() -> None:
    print("무음 관문 기준값")
    print(f"  무음으로 보는 값        : {SILENCE_RMS} 미만 (LLM 을 부르지 않는다)")
    print(f"  말이 있다고 보는 바닥값 : {SPEECH_FLOOR_RMS} 이상")
    print("  ※ 2026-08-02 실측: 정상 TTS 발화의 '가장 큰 0.1초'는 8,519~13,318 이었다")

    print(f"\n  {'시험한 녹음':28s} {'가장 큰 0.1초':>12s} {'전체 평균':>12s}  판정")
    print("  " + "-" * 96)

    # 1) 만들어 낸 소리로 관문의 경계를 확인한다
    show("무음 4초 (공격에 쓴 것)", make_wav(amplitude=0, seconds=4.0))
    show("아주 작은 잡음 (크기 10)", make_wav(amplitude=10))
    show("관문 사이 구간 (크기 40)", make_wav(amplitude=40))
    show("바닥값 부근 (크기 120)", make_wav(amplitude=120))
    show("보통 발화 크기 (크기 8000)", make_wav(amplitude=8000))
    show("30초 침묵 뒤 1초 발화", make_wav(amplitude=8000, seconds=1.0, silent_head_s=30.0))
    show("wav 가 아닌 파일", b"not a wav at all")

    # 2) 사람이 넘긴 실제 파일이 있으면 그것도 잰다
    paths = [Path(argument) for argument in sys.argv[1:]]
    if paths:
        print("\n  넘겨받은 파일")
        print("  " + "-" * 96)
        for path in paths:
            if not path.exists():
                print(f"  {path.name:28s} 파일을 찾을 수 없다")
                continue
            show(path.name, path.read_bytes())

    print("\n  읽는 법: '가장 큰 0.1초' 를 보고 판정한다.")
    print("  전체 평균만 보면 긴 침묵 끝에 한마디 한 답안이 무음으로 몰린다"
          " (위 30초 줄을 비교해 보면 된다).")


if __name__ == "__main__":
    main()
