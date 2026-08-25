"""녹음에 소리가 들어 있는지 **파일만 보고** 판단하는 자리.

왜 필요한가 (2026-08-02 실측으로 확인된 사고):
소리가 하나도 없는 wav(4초, 전부 0)를 말하기 답안으로 보냈더니,
받아쓰기 모델이 문항 지시문을 힌트 삼아 모범답안을 지어냈다.
    받아쓴 글: "어... 반장님 저기 기계가 갑자기 멈추었어요. ... 이제 어떻게 하면 좋을까요?"
    결과: 78.07점 B
**아무 말도 하지 않은 응시자가 B를 받는 길이었다.**

지시문을 참고로 주는 것은 현장 용어(반장님·지게차)를 알아듣게 하려는 것인데,
들을 소리가 없으면 그 참고 자료가 그대로 지어내기의 재료가 된다.
이것은 우리 모델만의 문제가 아니라 받아쓰기 모델 전반에 알려진 현상이라
"프롬프트를 더 손보면 된다"로 끝낼 일이 아니다.

그래서 이 파일이 하는 일은 하나다.
**LLM 에게 물어보기 전에, 파일 안의 숫자만으로 소리의 크기를 직접 잰다.**
모델이 무엇을 답하든 상관없이 같은 결과가 나오는 관문이라, 여기서 막힌 것은
받아쓰기 모델을 Azure 로 바꿔도 똑같이 막힌다.

wav 만 재는 이유 (정직하게 적어 둔다):
wav 는 소리의 크기가 파일 안에 숫자로 그대로 들어 있어서 계산으로 나온다.
mp3·m4a·webm·ogg 는 압축돼 있어서 풀어 봐야 소리를 볼 수 있고, 그러려면
별도 프로그램(ffmpeg)이 서버에 있어야 한다. 새 의존성을 들이지 않기로 했으므로
**압축 형식은 이 관문을 지나치지 않고 건너뛴다.** 즉 지금 무음 공격이 확실히
막히는 것은 wav 뿐이고, 압축 형식은 아래 2번(모델이 말 없음을 밝히는 것)에만
기댄다. 이것은 남아 있는 구멍이며 ffmpeg 를 들이는 날 닫아야 한다.
"""

from __future__ import annotations

import array
import io
import math
import wave
from dataclasses import dataclass

from ..scoring.messages import Notice, notice

#: 소리 크기를 재는 눈금. 16비트 녹음의 최대값이며, 다른 비트수의 파일도
#: 이 눈금으로 환산해서 비교한다(그래야 기준값 하나로 다 볼 수 있다).
FULL_SCALE = 32767.0

#: 소리 크기를 재는 구간 길이(밀리초).
#: 파일 전체 평균만 보면 안 되는 이유: 1분짜리 녹음의 맨 끝에서 2초만 말한 답안은
#: 전체 평균이 확 낮아져서 무음처럼 보인다. 그래서 **가장 시끄러웠던 0.1초**를 본다.
#: 0.1초는 한국어 한 음절이 들어가는 정도의 길이다.
WINDOW_MS = 100

#: ── 기준값의 실측 근거 (2026-08-02, 전부 24kHz 16비트 wav 로 직접 잼) ──────────
#:                              가장 큰 0.1초   전체 평균
#:   무음 wav (공격에 쓴 것)            0            0
#:   한국어 TTS 발화              13,318        6,299
#:   베트남어 TTS 발화            11,084        6,316
#:   한 마디만 한 TTS 발화          9,757        4,443
#:   영어 TTS 발화                 8,519        4,287
#: 관문 판정은 '가장 큰 0.1초' 쪽으로 한다(전체 평균은 긴 침묵에 희석된다).
#: 즉 실제로 말이 든 녹음은 이 눈금에서 **8,500 이상**이 나왔다.

#: 관문 1: 이보다 조용하면 **소리가 없는 것으로 본다**(LLM 을 부르지 않는다).
#: 15 는 위 표에서 가장 조용했던 발화(8,519)의 **1/570** 이고,
#: 소리 세기로 치면 -67dB 로 사람 귀에 들리지 않는 수준이다.
#: 마이크 잡음조차 보통 이보다 크다. 정상 발화가 여기 걸릴 일은 없다.
SILENCE_RMS = 15.0

#: 관문 3: 여기에 못 미치는데 받아쓴 글이 나왔다면 **지어낸 글로 본다**.
#: 60 은 관문 1(15)과 실측 발화(8,519 이상) 사이에서 보수적으로 잡은 값으로,
#: 가장 조용했던 발화의 1/140, 소리 세기로 -54dB 다. 사람이 말한 소리라기엔 너무 작다.
#: 15~60 구간에서는 LLM 을 불러 보기는 하지만 글이 나와도 채점하지 않는다.
#: (사람 녹음은 TTS 보다 조용하므로, 실제 응시 녹음이 모이면 이 값을 다시 재야 한다.
#:  낮춰야 할 일은 있어도 올릴 일은 없다 — 올리면 조용한 응시자가 0점이 된다)
SPEECH_FLOOR_RMS = 60.0


@dataclass
class Loudness:
    """녹음 하나의 소리 크기. 채점 거부의 근거로 그대로 쓰인다."""

    #: 파일 전체의 평균 소리 크기 (0~32767 눈금)
    overall_rms: float
    #: 가장 시끄러웠던 0.1초 구간의 소리 크기. 관문 판정은 이 값으로 한다
    peak_window_rms: float
    #: 가장 큰 순간값. 딸깍 소리 하나만 있는 파일을 구별할 때 참고한다
    peak_sample: int
    #: 몇 개의 소리 알갱이를 재서 나온 값인지
    sample_count: int

    def describe(self) -> str:
        """사람이 읽는 한 줄 근거. 예외 메시지에 그대로 들어간다."""
        return self.describe_notice().message

    def describe_notice(self) -> Notice:
        """위 한 줄을 '코드 + 잰 값' 으로도 담아 둔다.

        백엔드가 이 줄까지 영어로 바꿔야 하는데, 숫자가 끼어 있어서 문장을 통째로
        번역할 수가 없다. 그래서 잰 값을 따로 떼어 코드와 함께 넘긴다.
        """
        return notice(
            "AUDIO_LOUDNESS_DESCRIBE",
            peak=round(self.peak_window_rms, 1),
            mean=round(self.overall_rms, 1),
            scaleMax=int(FULL_SCALE),
        )


def _samples_to_int_array(raw: bytes, sample_width: int) -> array.array | None:
    """파일에 든 소리 알갱이를 계산할 수 있는 숫자 목록으로 바꾼다.

    녹음 형식마다 한 알갱이를 몇 바이트로 적는지가 달라서(8·16·24·32비트),
    전부 16비트 눈금(-32768~32767)으로 맞춰 놓는다.
    그래야 기준값(SILENCE_RMS 등) 하나로 모든 파일을 볼 수 있다.
    """
    if sample_width == 1:
        # 8비트 wav 는 0~255 로 적고 128 이 '소리 없음'이다. 그것을 0 중심으로 옮긴 뒤
        # 16비트 눈금에 맞춰 키운다(1비트 차이는 256배)
        raw_values = array.array("B")
        raw_values.frombytes(raw)
        return array.array("i", [(value - 128) * 256 for value in raw_values])

    if sample_width == 2:
        # 가장 흔한 형식. 그대로 쓰면 된다
        values = array.array("h")
        values.frombytes(raw[: len(raw) // 2 * 2])
        return values

    if sample_width == 3:
        # 24비트. 표준 배열 형식이 없어서 3바이트씩 직접 읽고 16비트로 줄인다
        values = array.array("i")
        for offset in range(0, len(raw) - 2, 3):
            value = int.from_bytes(raw[offset : offset + 3], "little", signed=True)
            values.append(value >> 8)
        return values

    if sample_width == 4:
        values = array.array("i")
        values.frombytes(raw[: len(raw) // 4 * 4])
        # 32비트를 16비트 눈금으로 줄인다
        return array.array("i", [value >> 16 for value in values])

    # 처음 보는 형식이다. 찍어서 재지 않는다(잘못 재면 정상 답안을 막게 된다)
    return None


def measure_wav_loudness(data: bytes) -> Loudness | None:
    """wav 파일의 소리 크기를 직접 잰다. 잴 수 없으면 None 을 돌려준다.

    None 이 나오는 경우(전부 '이 관문을 건너뛴다'는 뜻이다):
      - wav 가 아니거나 헤더가 깨졌다
      - wav 껍데기 안에 압축된 소리가 들어 있다(우리가 풀 수 없다)
      - 처음 보는 비트수다

    여기서 채점을 멈추지 않는 이유: 못 재는 것과 소리가 없는 것은 다르다.
    못 재는 파일을 무음으로 몰면 멀쩡히 말한 응시자가 0점을 받는다.
    """
    try:
        with wave.open(io.BytesIO(data), "rb") as handle:
            channels = handle.getnchannels()
            sample_width = handle.getsampwidth()
            frame_rate = handle.getframerate()
            compression = handle.getcomptype()
            raw = handle.readframes(handle.getnframes())
    except Exception:
        # 헤더가 깨졌거나 wav 가 아니다. 형식 관문(audio.py)이 따로 보고 있다
        return None

    # 압축된 소리(a-law 등)는 숫자가 소리 크기를 그대로 뜻하지 않는다. 재지 않는다
    if compression != "NONE" or not frame_rate:
        return None

    samples = _samples_to_int_array(raw, sample_width)
    if samples is None or not samples:
        return None

    # 여러 갈래(스테레오)로 녹음된 경우, 갈래를 구별하지 않고 한 줄로 이어서 본다.
    # 소리가 있는지 없는지만 보는 일이라 갈래를 나눌 필요가 없다
    total_squares = sum(value * value for value in samples)
    overall_rms = math.sqrt(total_squares / len(samples))
    peak_sample = max(abs(value) for value in samples)

    # 0.1초에 해당하는 알갱이 개수. 갈래 수만큼 곱해야 실제 0.1초가 된다
    window_size = max(1, int(frame_rate * channels * WINDOW_MS / 1000))

    # 구간별로 나눠서 가장 시끄러웠던 곳을 찾는다.
    # (전체 평균만 보면 '거의 무음인 긴 녹음 끝에 한마디'가 무음으로 보인다)
    peak_window_rms = 0.0
    for start in range(0, len(samples), window_size):
        chunk = samples[start : start + window_size]
        # 마지막 토막이 너무 짧으면 값이 튀므로 앞 구간들로만 판단한다
        if len(chunk) < window_size and peak_window_rms > 0:
            break
        window_rms = math.sqrt(sum(value * value for value in chunk) / len(chunk))
        peak_window_rms = max(peak_window_rms, window_rms)

    return Loudness(
        overall_rms=overall_rms,
        peak_window_rms=peak_window_rms,
        peak_sample=peak_sample,
        sample_count=len(samples),
    )


def is_silent(loudness: Loudness | None) -> bool:
    """소리가 아예 없는 녹음인가 (관문 1). 못 잰 파일은 False 로 본다."""
    if loudness is None:
        return False
    return loudness.peak_window_rms < SILENCE_RMS


def is_too_quiet_for_speech(loudness: Loudness | None) -> bool:
    """사람이 말한 소리가 들어 있다기에는 너무 조용한가 (관문 3)."""
    if loudness is None:
        return False
    return loudness.peak_window_rms < SPEECH_FLOOR_RMS


def silence_message(loudness: Loudness) -> str:
    """무음으로 막을 때 백엔드에 그대로 전달할 한 문장.

    잰 값을 문장 안에 넣는 이유: 이 프로젝트에서 근거 없는 판정은 결함이다.
    나중에 "왜 내 답안이 채점되지 않았나"에 이 숫자로 답할 수 있어야 한다.
    """
    return silence_notice(loudness).message


def silence_notice(loudness: Loudness) -> Notice:
    """위 한 문장을 '코드 + 값' 으로 담은 것.

    잰 값 부분(measurements)은 그 자체가 또 하나의 문장이라, 안쪽 Notice 를 통째로
    넣어 백엔드가 겉과 속을 둘 다 영어로 바꿀 수 있게 했다.
    """
    inner = loudness.describe_notice()
    return notice("STT_SILENT_AUDIO", loudness=inner.message, loudnessNotice=inner)


def too_quiet_message(loudness: Loudness, transcript: str) -> str:
    """받아쓴 글이 나왔지만 소리가 너무 작아 지어낸 글로 볼 때의 한 문장."""
    return too_quiet_notice(loudness, transcript).message


def too_quiet_notice(loudness: Loudness, transcript: str) -> Notice:
    """위 한 문장을 '코드 + 값' 으로 담은 것.

    **`preview` 는 번역하지 않는다.** 응시자가 실제로 한국어로 말한 것을 받아쓴
    조각이라서, 영어로 바꿔 보여 주면 "나는 그렇게 말하지 않았다"는 이의를 확인할
    길이 사라진다. 백엔드는 이 값을 그대로 문장에 끼워야 한다.
    """
    preview = transcript.strip()[:40]
    inner = loudness.describe_notice()
    return notice(
        "STT_TOO_QUIET",
        loudness=inner.message,
        preview=preview,
        loudnessNotice=inner,
    )
