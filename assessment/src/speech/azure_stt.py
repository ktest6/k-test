"""Azure 음성 서비스로 받아쓰기와 **발음 평가**를 한 번에 하는 구현.

원래 계획이 이것이었다. 계정이 없어서 그동안 Gemini(gemini_stt.py)를 임시로 꽂아
두었고, 2026-08-22 에 Azure Speech 리소스(koreacentral)가 나와서 이 파일이 생겼다.

**Gemini 와 결정적으로 다른 점은 발음 점수를 함께 준다는 것이다.**
받아쓴 '글'만으로는 발음을 알 수 없어서 발화 전달력(delivery) 영역은 지금까지
채점하지 못하고 자리만 비워 두었는데, 이 구현을 쓰면 그 영역이 채워진다.
발음 평가는 음성을 직접 들은 기계만 할 수 있으므로 받아쓰기와 같은 호출에서
함께 받아 온다(scoring-design: 발화 전달력은 음성 원본을 본다).

──────────────────────────────────────────────────────────────────────
낭독형과 자유 발화를 다르게 부른다
──────────────────────────────────────────────────────────────────────
Azure 발음 평가에는 '정답지(reference text)'를 주는 방식과 안 주는 방식이 있다.

  낭독형 문항 (제시문을 그대로 읽는 유형)  -> 제시문을 정답지로 준다  (scripted)
  그 밖의 자유 발화                        -> 정답지 없이 평가한다     (unscripted)

정답지를 주면 '읽어야 할 말 중 얼마나 말했는가(completeness)'를 잴 수 있지만,
자유 발화에 아무 글이나 정답지로 주면 응시자가 그 글을 읽지 않았다는 이유로
점수가 깎인다. 그래서 **문항 유형이 낭독형일 때만** 정답지를 준다.
지금 말하기 문항 다섯 유형(incident_report / hazard_warning / instruction_restate /
completion_report / help_request)에는 낭독형이 없으므로 전부 자유 발화로 간다.
('instruction_restate'는 지시를 자기 말로 복창하는 것이지 글자 그대로 읽는 것이
 아니라서 낭독형에 넣지 않았다)

──────────────────────────────────────────────────────────────────────
실측으로 확인한 것 (2026-08-22, koreacentral, SDK 1.51.2)
──────────────────────────────────────────────────────────────────────
1) **48kHz wav 는 그대로 보내면 거절당한다.**
   "Invalid audio channel configuration" 으로 연결이 끊긴다(오류 코드 1007).
   그래서 이 파일은 보내기 전에 항상 **16kHz·모노·16비트로 바꾼다**(_to_pcm16k).
   응시 녹음이 어떤 설정으로 오든 여기서 한 번 맞춰 주므로 부르는 쪽은 몰라도 된다.

2) **한국어에는 억양 점수(ProsodyScore)가 오지 않는다.**
   enable_prosody_assessment() 를 켜도 응답에 그 값이 없었다.
   그래서 억양은 채점에 쓰지 않고 '못 받았다'고만 남긴다(값을 지어내지 않는다).

3) **음절·음소 이름이 빈 문자열로 온다.**
   점수는 오지만 어떤 음소였는지는 안 알려 준다. 그래서 근거로 쓸 수 있는 가장
   작은 단위는 '낱말'이다. g2pk 로 음운변화 위치를 겹쳐 보는 계획(scoring-design)은
   음소 이름이 있어야 하므로 아직 못 한다.

4) 실제 응시자 녹음(베트남 출신, 낭독형) 예:
   "나는 집 내부 공사를 끝냈다." 를 읽힌 결과
   정확도 57 / 유창성 100 / 완전성 20 / 종합 43.4,
   낱말별로 '집' 43, '내부' 50, '공사를' 54, '끝냈다' 52 (전부 Mispronunciation).

──────────────────────────────────────────────────────────────────────
아직 못 하는 것 (정직하게 남긴다)
──────────────────────────────────────────────────────────────────────
- **wav 만 처리한다.** mp3·m4a·webm·ogg 는 풀어 줄 도구(GStreamer 등)가 서버에
  있어야 해서 지금은 받지 않고 실패로 알린다. 응시 녹음이 wav 로 들어오고 있어
  급하지는 않지만, 형식이 바뀌면 먼저 닫아야 할 구멍이다.
- 여러 문장으로 나뉘어 인식된 경우의 점수 합치는 방법은 **임시 규칙**이다
  (아래 _merge_segments 참고). 실제 응시 녹음 분포를 보고 다시 정해야 한다.
"""

from __future__ import annotations

import io
import json
import os
import threading
import time
import wave

from ..scoring.schema import AudioInput
from .audio import AudioRequestError, FetchedAudio, fetch_audio
from .loudness import (
    is_silent,
    is_too_quiet_for_speech,
    silence_message,
    too_quiet_message,
)
from .port import (
    PronouncedWord,
    PronouncerPort,
    PronunciationAssessment,
    SttPort,
    SttUnavailable,
    Transcription,
)

#: 받아쓸 언어. 이 시험은 한국어만 본다
SPEECH_LANGUAGE = "ko-KR"

#: Azure 에 보내는 음성 규격. 이 값으로 맞춰서 보내면 거절당하지 않는 것을 실측했다
TARGET_SAMPLE_RATE = 16_000
TARGET_SAMPLE_WIDTH = 2   # 16비트
TARGET_CHANNELS = 1       # 모노

#: 낭독형(제시문을 글자 그대로 읽는) 문항 유형 이름들.
#: 여기 있는 유형만 제시문을 정답지로 주고 평가한다.
#: 새 낭독형 문항 유형을 만들면 이 목록에 이름을 더한다 — 고칠 곳은 여기 한 줄이다.
READ_ALOUD_ITEM_TYPES = frozenset(
    {"read_aloud", "reading_aloud", "read_sentence", "sentence_reading", "lar", "낭독"}
)

#: 인식을 기다려 줄 시간을 정하는 값(초).
#: 녹음 길이의 세 배에 여유 30초를 더하되, 최소 60초 최대 180초 사이로 둔다.
#: 90초짜리 녹음까지 처리해야 하는데 실시간보다 빨리 끝나는 것이 보통이라
#: 세 배면 충분하고, 그보다 오래 걸리면 정상 응답을 기다리는 중이 아니라고 본다.
#: **실측으로 정한 값이 아니라 추정값이다.**
RECOGNITION_TIMEOUT_MIN_S = 60.0
RECOGNITION_TIMEOUT_MAX_S = 180.0


def is_read_aloud(item_type: str) -> bool:
    """이 문항이 '제시문을 그대로 읽는' 유형인지.

    낭독형이면 제시문을 정답지로 줘서 평가하고, 아니면 정답지 없이 평가한다.
    (자유 발화에 정답지를 주면 그 글을 안 읽었다는 이유로 점수가 깎인다)
    """
    return (item_type or "").strip().lower() in READ_ALOUD_ITEM_TYPES


def _to_pcm16k(data: bytes) -> bytes:
    """wav 파일을 Azure 가 받아 주는 규격(16kHz·모노·16비트 PCM)의 알맹이로 바꾼다.

    껍데기(wav 헤더) 없이 소리 값만 돌려준다. 그대로 Azure 에 흘려보낼 것이라
    헤더가 필요 없기 때문이다.

    왜 이 일이 필요한가:
    48kHz 로 녹음된 파일을 그대로 보냈더니 Azure 가 연결을 끊었다(실측).
    응시 녹음이 어떤 설정으로 올지 우리가 정할 수 없으므로 여기서 한 번 맞춘다.
    """
    # numpy 는 이 변환에만 쓴다. 음성을 안 쓰는 채점에서는 읽을 일이 없도록 여기서 부른다
    import numpy as np

    try:
        with wave.open(io.BytesIO(data), "rb") as handle:
            channels = handle.getnchannels()
            width = handle.getsampwidth()
            rate = handle.getframerate()
            frames = handle.readframes(handle.getnframes())
    except Exception as exc:
        raise SttUnavailable(
            "음성 파일을 열지 못했다. wav 파일이 맞는지 확인해야 한다.",
            detail=str(exc),
        ) from exc

    # 16비트가 아닌 wav 는 아직 다루지 않는다. 잘못 읽으면 소리가 조용히 망가지고
    # 그 결과가 발음 점수로 나타나므로, 추측해서 읽지 않고 실패로 알린다
    if width != 2:
        raise SttUnavailable(
            f"이 음성은 {width * 8}비트 wav 라서 발음 평가로 보낼 수 없다"
            "(16비트 wav 로 녹음해야 한다)."
        )

    # 소리 값을 숫자 배열로 편다. 스테레오면 칸이 채널 수만큼 번갈아 들어 있다
    samples = np.frombuffer(frames, dtype="<i2").astype(np.float32)
    if channels > 1:
        # 채널을 평균 내서 모노로 만든다(한쪽만 쓰면 반대쪽 소리를 버리게 된다)
        usable = len(samples) - (len(samples) % channels)
        samples = samples[:usable].reshape(-1, channels).mean(axis=1)

    # 초당 칸 수를 16000 으로 맞춘다. 값 사이를 직선으로 이어 새 칸을 만든다
    if rate != TARGET_SAMPLE_RATE and len(samples):
        new_length = int(round(len(samples) * TARGET_SAMPLE_RATE / rate))
        positions = np.linspace(0, len(samples) - 1, max(new_length, 1))
        samples = np.interp(positions, np.arange(len(samples)), samples)

    # 다시 16비트 정수로 되돌린다. 범위를 벗어난 값은 끝에서 멈춘다(소리가 튀지 않게)
    return np.clip(samples, -32768, 32767).astype("<i2").tobytes()


class AzureStt(SttPort, PronouncerPort):
    """Azure 음성 서비스로 받아쓰고 발음까지 재는 구현체.

    두 자리에 동시에 꽂힌다.
      - SttPort        : 받아쓰기(전사). provider=azure 로 서버를 돌릴 때 쓴다
      - PronouncerPort : 발음(발화 전달력)만 재기. **전사를 누가 했든** 이 자리로
                         불려서 발음 점수만 낸다. LoRA 로 받아쓰는 서버에서도
                         발음은 이 자리로 Azure 가 잰다(2026-08-22 분리).

    받아쓰기와 발음은 같은 인식 한 번(_recognize_core)에서 함께 나온다. transcribe 는
    글과 발음을 둘 다 담아 돌려주고, assess_pronunciation 은 그중 발음만 꺼내 돌려준다
    (받아쓴 글은 버린다).
    """

    provider_name = "azure"

    def __init__(
        self,
        key: str | None = None,
        region: str | None = None,
        http_client=None,
        recognize=None,
    ):
        """열쇠와 지역을 준비한다.

        키를 안 넘기면 .env 의 AZURE_SPEECH_KEY / AZURE_SPEECH_REGION 을 쓴다.
        (.env 읽기는 채점 쪽 llm/client.py 가 이미 하고 있어서 여기서는 환경변수만 본다)

        http_client 는 음성 파일을 내려받을 때 쓴다(테스트가 네트워크를 끊는 자리).
        recognize 는 '실제로 Azure 를 부르는 함수'를 바꿔 끼우는 자리다.
        테스트는 여기에 가짜 응답을 주는 함수를 넣어서 네트워크 없이 돈다.
        """
        self._key = key if key is not None else os.getenv("AZURE_SPEECH_KEY", "")
        self._region = region if region is not None else os.getenv("AZURE_SPEECH_REGION", "")
        self._http_client = http_client
        # 안 넘기면 진짜 Azure 를 부르는 함수를 쓴다
        self._recognize = recognize or self._recognize_with_sdk

    @property
    def model_name(self) -> str:
        """어떤 기능을 썼는지가 결과에 남아야 하므로 지역까지 붙여 적는다."""
        region = self._region or "unknown-region"
        return f"azure-speech-{SPEECH_LANGUAGE}-pronunciation@{region}"

    @property
    def available(self) -> bool:
        """열쇠가 있어서 부를 수 있는 상태인지."""
        return bool(self._key and self._region)

    def transcribe(
        self, audio: AudioInput, item_prompt: str = "", item_type: str = ""
    ) -> Transcription:
        """음성 하나를 받아쓰고 발음까지 재서 돌려준다.

        순서는 다섯이다.
          1) 내려받는다 (크기·형식·주소 관문을 여기서 지난다)
          2) **무음 관문** 소리가 없으면 Azure 를 부르지 않고 끝낸다
          3) Azure 가 받아 주는 규격으로 소리를 맞춘다 (16kHz 모노)
          4) 받아쓰기와 발음 평가를 한 번에 받아 온다
          5) **거의 무음 관문** 글은 나왔는데 소리가 너무 작았으면 그 글을 버린다

        item_type 이 낭독형이면 item_prompt 를 정답지로 줘서 평가한다.
        (이 매개변수는 나중에 더한 것이라 안 줘도 동작한다 — 그때는 자유 발화로 본다)
        """
        started = time.perf_counter()

        # 받아쓰기와 발음 평가를 한 번에 받아 온다(관문·규격 맞추기는 _recognize_core 안에서).
        text, assessment, warnings, fetched = self._recognize_core(
            audio, item_prompt, item_type
        )

        # 받아쓴 것이 없으면 실패로 다룬다. 빈 글을 넘기면 뒤 단계가
        # '말을 안 한 답안'으로 채점해 버려서 받아쓰기 실패와 뒤섞인다
        if not text.strip():
            raise SttUnavailable(
                "음성에서 말을 하나도 옮겨 적지 못했다. "
                "녹음이 비어 있거나 소리가 너무 작은지 확인해야 한다."
            )

        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        return Transcription(
            text=text.strip(),
            provider=self.provider_name,
            model=self.model_name,
            audio_duration_ms=fetched.duration_ms,
            audio_bytes=fetched.size_bytes,
            audio_format=fetched.audio_format,
            # Azure 는 토큰이라는 단위를 쓰지 않는다
            input_tokens=None,
            output_tokens=None,
            elapsed_ms=elapsed_ms,
            warnings=warnings,
            pronunciation=assessment,
            # 내려받은 파일을 그대로 딸려 보낸다. 발음 평가가 뒤에서 또 부를 때
            # 같은 파일을 두 번 내려받지 않게 하려는 통로다(port.py 참고)
            fetched_audio=fetched,
        )

    def assess_pronunciation(
        self,
        audio: AudioInput,
        item_prompt: str = "",
        item_type: str = "",
        fetched: FetchedAudio | None = None,
    ) -> PronunciationAssessment | None:
        """음성 원본을 직접 들어 **발음 점수만** 낸다(받아쓴 글은 버린다).

        LoRA 로 받아쓰는 서버에서 발화 전달력(delivery)만 Azure 로 채점할 때
        불리는 자리다. transcribe 와 같은 인식(_recognize_core)을 쓰지만,
        여기서는 그중 발음(PronunciationAssessment)만 꺼내 돌려준다.

        fetched 를 주면 **그 파일을 그대로 쓰고 다시 내려받지 않는다.** 받아쓰기가
        이미 손에 넣은 파일을 건네받는 자리다(같은 음성을 두 번 받지 않으려는 것).

        **이쪽은 실패해도 예외를 올리지 않고 None 을 돌려준다.**
        받아쓰기는 이미 다른 기계(LoRA)가 끝냈으므로, 발음을 못 재는 것은
        채점 전체를 세울 이유가 되지 않는다. 발음을 못 재면 delivery 영역만
        지금까지처럼 비어 있게 두는 것이 맞다(백엔드 약속: not_evaluated·weight 0).
        열쇠가 없거나(available False) 무음·형식 불가·값 없음이면 None 이다.
        """
        # 열쇠가 없으면 부를 수 없다. 조용히 None 을 돌려줘 delivery 를 비워 둔다
        if not self.available:
            return None
        try:
            _text, assessment, _warnings, _fetched = self._recognize_core(
                audio, item_prompt, item_type, fetched=fetched
            )
        except (SttUnavailable, AudioRequestError):
            # 두 갈래 다 여기서 삼킨다. 발음만 못 잰 것이지 전사는 살아 있기 때문이다.
            #   SttUnavailable    : 무음·wav 아님·Azure 가 거절함
            #   AudioRequestError : 음성 파일을 못 받아 옴(주소 404·형식·크기 위반 등)
            #
            # 2026-08-24 수리: 예전에는 SttUnavailable 만 잡았다. 그래서 파일을
            # 내려받다가 난 AudioRequestError 가 그대로 창구까지 올라가 **받아쓰기는
            # 이미 성공했는데 채점 전체가 400 으로 죽는** 사고가 났다.
            # 이 함수의 약속은 '실패해도 None' 이므로 두 갈래를 똑같이 다룬다
            return None
        return assessment

    # -- 안쪽 일 ------------------------------------------------------------

    def _recognize_core(
        self,
        audio: AudioInput,
        item_prompt: str,
        item_type: str,
        fetched: FetchedAudio | None = None,
    ) -> tuple[str, PronunciationAssessment | None, list[str], FetchedAudio]:
        """받아쓰기와 발음 평가를 함께 얻는 공통 심장부.

        transcribe(전사+발음)와 assess_pronunciation(발음만)이 둘 다 이 함수를 쓴다.
        한 곳에 모아 둔 이유: 규격 맞추기(16kHz)와 세 겹 무음 관문이 두 경로에서
        똑같이 걸려야 하는데, 복사해 두면 한쪽만 고쳐져 어긋난다.

        순서는 다섯이다.
          1) 파일을 손에 넣는다 (크기·형식·주소 관문을 여기서 지난다)
             **이미 받아 둔 파일(fetched)을 건네받았으면 내려받지 않고 그것을 쓴다.**
          2) **무음 관문** 소리가 없으면 Azure 를 부르지 않고 끝낸다
          3) Azure 가 받아 주는 규격으로 소리를 맞춘다 (16kHz 모노)
          4) 받아쓰기와 발음 평가를 한 번에 받아 온다
          5) **거의 무음 관문** 글은 나왔는데 소리가 너무 작았으면 그 글을 버린다

        1번만 건너뛰고 **나머지 관문(형식·무음·거의 무음)은 그대로 지난다.**
        건네받은 파일이라고 해서 검사를 면제하면, 무음 녹음이 발음 점수를 받는
        구멍이 생긴다.

        돌려주는 것: (받아쓴 글, 발음 평가 또는 None, 사람이 알아야 할 것, 쓴 파일).
        빈 글은 여기서 막지 않는다 — 전사는 실패로 보고 발음은 살려도 되는 경우가
        있어서, '빈 글을 어떻게 다룰지'는 부르는 쪽이 정한다.
        """
        # 열쇠가 없으면 부를 수 없다. 여기서 분명히 알린다
        if not self.available:
            raise SttUnavailable(
                "음성을 글자로 옮길 수 없다. Azure 음성 서비스 열쇠"
                "(AZURE_SPEECH_KEY / AZURE_SPEECH_REGION)가 설정돼 있지 않다."
            )

        # 1) 파일을 손에 넣는다.
        #    받아쓰기가 이미 받아 둔 것을 건네줬으면 그것을 쓴다 — 한 답안을 채점하면서
        #    같은 음성을 두 번 내려받지 않기 위해서다(2026-08-24)
        if fetched is None:
            fetched = fetch_audio(audio, http_client=self._http_client)

        # 지금은 wav 만 Azure 로 보낼 수 있다. 압축 형식을 풀어 줄 도구가 서버에 없다.
        # 잘못 읽어서 엉뚱한 발음 점수를 내느니 못 한다고 말하는 편이 맞다
        if fetched.audio_format != "wav":
            raise SttUnavailable(
                f"'{fetched.audio_format}' 형식은 Azure 발음 평가로 보낼 수 없다"
                "(지금은 wav 만 처리한다)."
            )

        # 2) 무음 관문 — 소리가 없는 녹음은 부르지 않는다.
        #    Gemini 와 같은 관문을 그대로 쓴다. 이 판단은 파일 안의 숫자만 보므로
        #    어느 회사 기계를 쓰든 결과가 같다
        if is_silent(fetched.loudness):
            raise SttUnavailable(silence_message(fetched.loudness))

        # 3) Azure 가 받아 주는 규격으로 맞춘다
        pcm = _to_pcm16k(fetched.data)

        # 4) 받아쓰기 + 발음 평가를 한 번에 받아 온다.
        #    낭독형이면 제시문을 정답지로 준다(그래야 '얼마나 읽었는가'를 잴 수 있다)
        scripted = is_read_aloud(item_type)
        reference_text = item_prompt.strip() if scripted else ""
        segments = self._recognize(
            pcm=pcm,
            reference_text=reference_text,
            timeout_s=self._timeout_for(fetched),
        )

        text, assessment = self._merge_segments(segments, scripted, reference_text)

        # 5) 거의 무음 관문 — 글은 나왔는데 소리가 사람 말이라기에 너무 작았던 경우.
        #    소리와 글이 어긋나면 글이 아니라 소리를 믿는다
        if text.strip() and is_too_quiet_for_speech(fetched.loudness):
            raise SttUnavailable(too_quiet_message(fetched.loudness, text))

        warnings = list(fetched.warnings)
        if scripted:
            # 낭독형은 정답지에 맞춰 인식되므로, 받아쓴 글이 응시자가 실제로 낸 소리보다
            # 제시문 쪽으로 당겨져 있을 수 있다. 문법 채점에서 이 점을 알아야 한다
            warnings.append(
                "낭독형 문항이라 제시문을 정답지로 주고 발음을 평가했다. "
                "받아쓴 글이 제시문 쪽으로 맞춰졌을 수 있으므로 문법 채점의 근거로 쓸 때 확인이 필요하다."
            )
        warnings.extend(assessment.warnings if assessment else [])

        return text, assessment, warnings, fetched

    # -- 이하 옛 안쪽 일 -----------------------------------------------------

    @staticmethod
    def _timeout_for(fetched: FetchedAudio) -> float:
        """이 녹음을 얼마나 기다려 줄지 정한다.

        길이를 아는 녹음은 그 세 배에 여유를 더하고, 모르면 최소값을 쓴다.
        """
        if not fetched.duration_ms:
            return RECOGNITION_TIMEOUT_MIN_S
        estimate = fetched.duration_ms / 1000.0 * 3 + 30.0
        return min(max(estimate, RECOGNITION_TIMEOUT_MIN_S), RECOGNITION_TIMEOUT_MAX_S)

    def _recognize_with_sdk(
        self, pcm: bytes, reference_text: str, timeout_s: float
    ) -> list[dict]:
        """실제로 Azure 를 불러서 인식 결과 조각들을 그대로 돌려준다.

        '이어서 인식(continuous recognition)'을 쓰는 이유:
        한 번에 끝내는 방식은 짧은 음성(60초 안쪽)만 되는데 이 시험은 90초까지
        받아야 한다. 이어서 인식은 긴 녹음을 문장 단위로 나눠 인식해 준다.

        임시 파일을 만들지 않고 소리를 직접 흘려보낸다(push stream).
        응시자 음성을 서버 디스크에 남기지 않기 위해서다.

        돌려주는 것은 Azure 가 준 JSON 을 파이썬 사전으로 바꾼 목록이다.
        점수를 합치는 판단은 여기서 하지 않고 _merge_segments 가 한다
        (그래야 테스트가 가짜 JSON 만으로 합치는 규칙을 확인할 수 있다).
        """
        try:
            import azure.cognitiveservices.speech as speechsdk
        except ImportError as exc:
            raise SttUnavailable(
                "발음 평가에 필요한 Azure 음성 SDK 가 설치돼 있지 않다"
                "(pip install azure-cognitiveservices-speech).",
                detail=str(exc),
            ) from exc

        speech_config = speechsdk.SpeechConfig(subscription=self._key, region=self._region)
        speech_config.speech_recognition_language = SPEECH_LANGUAGE

        # 소리를 흘려보낼 통로를 만든다. 우리가 맞춰 둔 규격을 그대로 알려 준다
        stream_format = speechsdk.audio.AudioStreamFormat(
            samples_per_second=TARGET_SAMPLE_RATE,
            bits_per_sample=TARGET_SAMPLE_WIDTH * 8,
            channels=TARGET_CHANNELS,
        )
        push_stream = speechsdk.audio.PushAudioInputStream(stream_format)
        recognizer = speechsdk.SpeechRecognizer(
            speech_config=speech_config,
            audio_config=speechsdk.audio.AudioConfig(stream=push_stream),
        )

        # 발음 평가를 켠다. 낭독형이면 정답지가 들어가고, 자유 발화면 빈 문자열이다.
        # enable_miscue 는 '정답지에 있는데 안 읽은 말'을 잡아내는 기능이라
        # 정답지가 있을 때만 뜻이 있다
        pron_config = speechsdk.PronunciationAssessmentConfig(
            reference_text=reference_text,
            grading_system=speechsdk.PronunciationAssessmentGradingSystem.HundredMark,
            granularity=speechsdk.PronunciationAssessmentGranularity.Phoneme,
            enable_miscue=bool(reference_text),
        )
        try:
            # 억양 점수를 켠다. 한국어에는 값이 안 오는 것을 실측했지만,
            # 나중에 지원되면 그대로 들어오도록 켜 둔다
            pron_config.enable_prosody_assessment()
        except Exception:
            # 이 SDK 판에 없는 기능이면 그냥 넘어간다. 억양은 채점에 안 쓴다
            pass
        pron_config.apply_to(recognizer)

        segments: list[dict] = []
        finished = threading.Event()
        failure: dict[str, str] = {}

        def on_recognized(evt) -> None:
            # 문장 하나가 인식될 때마다 Azure 가 준 JSON 을 그대로 모아 둔다
            raw = evt.result.properties.get(
                speechsdk.PropertyId.SpeechServiceResponse_JsonResult
            )
            if raw:
                try:
                    segments.append(json.loads(raw))
                except json.JSONDecodeError:
                    # 조각 하나가 깨져도 나머지는 살린다. 깨진 조각은 없는 셈 친다
                    pass

        def on_canceled(evt) -> None:
            # 연결이 끊기거나 열쇠가 거절당한 경우다. 사유를 적어 두고 기다림을 끝낸다
            failure["reason"] = f"{evt.reason}: {getattr(evt, 'error_details', '')}"
            finished.set()

        recognizer.recognized.connect(on_recognized)
        recognizer.session_stopped.connect(lambda evt: finished.set())
        recognizer.canceled.connect(on_canceled)

        try:
            recognizer.start_continuous_recognition()
            # 소리를 한 번에 밀어 넣고 통로를 닫는다. 닫아야 Azure 가 '끝'을 안다
            push_stream.write(pcm)
            push_stream.close()
            completed = finished.wait(timeout_s)
        except Exception as exc:
            raise SttUnavailable(
                "음성을 글자로 옮기지 못했다. Azure 음성 서비스 호출이 실패했다.",
                detail=str(exc),
            ) from exc
        finally:
            try:
                recognizer.stop_continuous_recognition()
            except Exception:
                pass

        # 시간 안에 안 끝났으면 실패다. 반쪽 결과로 발음 점수를 내면
        # 뒷부분을 말하지 않은 것처럼 보여서 응시자가 손해를 본다
        if not completed:
            raise SttUnavailable(
                f"발음 평가가 제한 시간({timeout_s:.0f}초) 안에 끝나지 않았다."
            )
        if failure and not segments:
            raise SttUnavailable(
                "음성을 글자로 옮기지 못했다. Azure 음성 서비스가 요청을 거절했다.",
                detail=failure.get("reason", ""),
            )
        return segments

    @staticmethod
    def _merge_segments(
        segments: list[dict], scripted: bool, reference_text: str
    ) -> tuple[str, PronunciationAssessment | None]:
        """인식 조각 여러 개를 받아쓴 글 하나와 발음 점수 하나로 합친다.

        긴 녹음은 문장 단위로 나뉘어 오기 때문에 합치는 규칙이 필요하다.
        ※ 임시 규칙 ※ 실제 응시 녹음 분포를 보고 다시 정해야 한다.

          정확도·완전성·종합 : 조각의 **낱말 수**로 무게를 준 평균
                               (말을 많이 한 조각이 점수를 더 좌우해야 한다)
          유창성             : 조각의 **길이**로 무게를 준 평균
                               (유창성은 시간에 대한 값이라 낱말 수가 아니라 길이로 잰다)

        점수를 하나도 못 받았으면 발음 평가 결과를 만들지 않고 None 을 돌려준다.
        0점으로 때우면 발음을 못 잰 답안이 발음 0점을 받는 일이 생긴다.
        """
        texts: list[str] = []
        words: list[PronouncedWord] = []
        warnings: list[str] = []

        # (점수, 무게) 짝을 모아 둔다. 마지막에 무게 평균을 낸다
        by_words: dict[str, list[tuple[float, float]]] = {
            "accuracy": [], "completeness": [], "overall": [], "prosody": []
        }
        by_duration: list[tuple[float, float]] = []

        for segment in segments:
            best_list = segment.get("NBest") or []
            if not best_list:
                continue
            best = best_list[0]
            display = (best.get("Display") or segment.get("DisplayText") or "").strip()
            if display:
                texts.append(display)

            scores = best.get("PronunciationAssessment") or {}
            segment_words = best.get("Words") or []
            # 무게는 낱말 수다. 낱말이 하나도 없으면 조각 하나로 센다
            word_weight = float(len(segment_words)) or 1.0
            # Azure 가 주는 길이 단위는 100나노초라 밀리초로 바꿔 쓴다
            duration_weight = float(segment.get("Duration") or 0) / 10_000.0 or 1.0

            for key, name in (
                ("accuracy", "AccuracyScore"),
                ("completeness", "CompletenessScore"),
                ("overall", "PronScore"),
                ("prosody", "ProsodyScore"),
            ):
                value = scores.get(name)
                if value is not None:
                    by_words[key].append((float(value), word_weight))
            fluency = scores.get("FluencyScore")
            if fluency is not None:
                by_duration.append((float(fluency), duration_weight))

            # 낱말별 결과를 그대로 옮긴다. 이것이 나중에 점수의 근거가 된다
            for raw_word in segment_words:
                word_scores = raw_word.get("PronunciationAssessment") or {}
                accuracy = word_scores.get("AccuracyScore")
                words.append(
                    PronouncedWord(
                        word=str(raw_word.get("Word") or ""),
                        accuracy=float(accuracy) if accuracy is not None else None,
                        error_type=str(word_scores.get("ErrorType") or ""),
                        offset_ms=_ticks_to_ms(raw_word.get("Offset")),
                        duration_ms=_ticks_to_ms(raw_word.get("Duration")),
                    )
                )

        text = " ".join(texts).strip()

        def weighted(pairs: list[tuple[float, float]]) -> float | None:
            # 무게 평균. 잴 값이 없으면 지어내지 않고 None 을 돌려준다
            total = sum(weight for _, weight in pairs)
            if total <= 0:
                return None
            return round(sum(value * weight for value, weight in pairs) / total, 2)

        accuracy = weighted(by_words["accuracy"])
        fluency = weighted(by_duration)
        completeness = weighted(by_words["completeness"])
        overall = weighted(by_words["overall"])
        prosody = weighted(by_words["prosody"])

        # 네 점수 중 하나도 못 받았으면 발음 평가가 없었던 것으로 본다
        if accuracy is None and fluency is None and completeness is None and overall is None:
            return text, None

        if prosody is None:
            # 한국어는 억양 점수가 오지 않는다(실측). 못 받았다는 사실만 남긴다
            warnings.append(
                "억양·강세 점수(ProsodyScore)를 받지 못해 발화 전달력에서 억양은 채점하지 않았다."
            )
        if not scripted:
            # 정답지가 없으면 '얼마나 읽었는가'의 기준이 없다.
            # 값이 와도 점수로 쓰지 않는다는 사실을 여기서 밝힌다
            warnings.append(
                "자유 발화라서 읽을 원문이 없다. 발화 완전성(completeness)은 채점에 쓰지 않았다."
            )

        return text, PronunciationAssessment(
            accuracy=accuracy,
            fluency=fluency,
            completeness=completeness,
            overall=overall,
            prosody=prosody,
            scripted=scripted,
            reference_text=reference_text,
            words=words,
            provider="azure",
            warnings=warnings,
        )


def _ticks_to_ms(ticks) -> int | None:
    """Azure 가 쓰는 시간 단위(100나노초)를 밀리초로 바꾼다. 없으면 None."""
    if ticks is None:
        return None
    try:
        return int(round(float(ticks) / 10_000.0))
    except (TypeError, ValueError):
        return None
