"""우리가 학습한 LoRA 받아쓰기(Whisper-small + v2 어댑터)를 부르는 구현.

**여기(채점 서버)에는 무거운 것이 하나도 없다.**
LoRA 모델은 그래픽카드가 있어야 도는데 채점 PC 에는 그래픽카드가 없다. 그래서
모델은 RunPod 의 그래픽카드 서버(scripts/speech_lab/lora_stt_server.py)에 띄워 두고,
이 파일은 거기에 **음성을 보내고 받아쓴 글만 받아 오는 심부름꾼**이다. 그래서 이 파일이
쓰는 것은 http 요청 라이브러리(httpx)뿐이고 torch·transformers 는 필요 없다.

배선상의 자리:
    provider=lora 로 서버를 돌리면(KTEST_STT_PROVIDER=lora + LORA_STT_URL 설정)
    받아쓰기를 이 구현이 맡는다. Gemini·Azure 와 똑같이 SttPort 자리에 꽂히므로
    채점 파이프라인도 백엔드가 보는 API 형식도 이것 때문에 바뀌지 않는다.

**발음(발화 전달력)은 이 구현이 하지 않는다.**
LoRA 는 글자만 받아쓴다. 발음 점수는 음성을 직접 들은 기계(Azure)만 낼 수 있어서,
글은 LoRA 가·발음은 Azure 가 나눠 맡는다(scoring-design). 그 갈라 붙이는 일은
intake.py 가 하고, 여기서는 pronunciation 을 None 으로 둔다.

──────────────────────────────────────────────────────────────────────
정직하게 남기는 한계 (2026-08-22)
──────────────────────────────────────────────────────────────────────
- **v2 어댑터는 아직 골든셋으로 검증되지 않았다.** 학습은 끝났지만 "운영에 넣어도
  될 만큼 정확한가"를 사람이 정한 정답지(골든셋)로 확인한 적이 없다. 지금 이 배선을
  붙이는 목적은 **데모와 파이프라인 연결**이지, 이 받아쓰기의 품질을 보증하는 것이
  아니다. 운영 투입 근거는 골든셋 검증 뒤에 생긴다.
- RunPod 서버가 아직 떠 있지 않다. 실제 LoRA 호출 스모크는 배포 후에 한다
  (배포 절차는 lora_stt_server.py 상단 주석과 README 참고).
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass

from ..scoring.schema import AudioInput
from .audio import fetch_audio
from .loudness import is_silent, is_too_quiet_for_speech, silence_message, too_quiet_message
from .port import SttPort, SttUnavailable, Transcription

#: RunPod 추론 서버 주소를 담는 환경변수 이름.
#: 예: https<...>.proxy.runpod.net (재시작마다 바뀌므로 .env 에 새로 넣는다)
LORA_STT_URL_ENV = "LORA_STT_URL"

#: 서버가 자기 모델 이름을 안 알려 줄 때 대신 적어 둘 이름.
#: 실제로는 서버가 준 값(예: "whisper-small-lora-v2")으로 덮어쓴다.
DEFAULT_LORA_MODEL = "whisper-small-lora-v2"

#: 기다려 줄 시간(초). 그래픽카드 추론은 음성 길이에 비례해 걸리고, 첫 요청은
#: 모델이 깨어나느라 더 걸릴 수 있어 넉넉히 둔다. **실측이 아니라 추정값이다** —
#: 긴 녹음에서 시간 초과가 나면 올린다.
LORA_TIMEOUT_S = 120.0

#: '살아 있느냐'만 물어볼 때 기다려 줄 시간(초).
#: 받아쓰기(위의 120초)와 달리 이쪽은 상태 확인용이라 짧아야 한다. 채점 서버의
#: /health 가 이 값을 그대로 쓰기 때문에, 길게 잡으면 서버가 꺼져 있을 때
#: 상태 확인 한 번에 그만큼 멈춰 서 있게 된다.
LORA_PING_TIMEOUT_S = 2.0


@dataclass(frozen=True)
class LoraHealth:
    """LoRA 추론 서버가 지금 살아 있는지 물어본 결과.

    alive 만 있으면 '왜 안 되는지'를 사람이 알 수 없어서 사유를 함께 담는다.
    detail 은 살아 있을 때 None 이고, 죽었을 때만 한 문장으로 채워진다.
    """

    #: 지금 이 서버로 받아쓰기를 부탁할 수 있는 상태인가
    alive: bool
    #: 안 되는 이유(사람이 읽는 한 문장). 정상이면 None
    detail: str | None = None


class LoraStt(SttPort):
    """RunPod 에 띄운 우리 LoRA 받아쓰기 서버를 부르는 심부름꾼.

    받은 것을 그대로 믿지 않는 자리는 다른 구현과 같다.
      - 무음이면 서버를 부르지도 않는다(그래픽카드 비용을 아끼고, 지어낸 글을 막는다)
      - 빈 글이 오면 실패로 다룬다
      - 실패(주소 없음·연결 끊김·시간 초과·서버 5xx)는 삼키지 않고 SttUnavailable 로
        올린다. 그래야 창구가 503 으로 바꿔 알리고, 못 알아들은 음성을 지어낸 글로
        채점하는 일이 없다
    """

    provider_name = "lora"

    def __init__(self, url: str | None = None, http_client=None, timeout_s: float = LORA_TIMEOUT_S):
        """추론 서버 주소와 통신로를 준비한다.

        url 을 안 넘기면 .env 의 LORA_STT_URL 을 쓴다(주소가 재시작마다 바뀌므로
        코드가 아니라 환경변수로 둔다). http_client 를 넘기면 그것으로 통신한다
        (테스트가 네트워크 없이 도는 자리).
        """
        self._url = (url if url is not None else os.getenv(LORA_STT_URL_ENV, "")).strip()
        self._http_client = http_client
        self._timeout_s = timeout_s
        # 서버가 실제로 쓴 모델 이름. 받아쓰기가 끝나면 서버가 준 값으로 덮어쓴다.
        # 채점 결과에 남는 값이라 짐작이 아니라 서버가 밝힌 것을 적어야 한다
        self._model = DEFAULT_LORA_MODEL

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def available(self) -> bool:
        """주소가 설정돼 있어서 **부를 수는 있는** 상태인지.

        여기서 보는 것은 주소 문자열이 있느냐 하나뿐이다. 주소가 적혀 있어도
        그 서버가 꺼져 있을 수 있으므로, 이 값은 '살아 있다'는 뜻이 아니다.
        transcribe 앞에서 '주소도 없이 부르는 일'만 막는 관문으로 쓴다.
        실제로 떠 있는지 알아야 하면 ping() 을 쓴다.
        """
        return bool(self._url)

    def ping(self, timeout_s: float = LORA_PING_TIMEOUT_S) -> LoraHealth:
        """추론 서버의 /health 를 실제로 한 번 두드려 살아 있는지 확인한다.

        왜 필요한가:
        available 은 주소가 적혀 있는지만 본다. 그래서 8100 서버가 꺼져 있어도
        참이 되고, 채점 서버의 /health 가 그것을 그대로 내보내면 **말하기 채점이
        전부 503 인 상태를 '정상'이라고 보고하게 된다.** 이 함수는 그 거짓 보고를
        없애려고, 짐작 대신 서버에 직접 물어본다.

        실패는 예외로 올리지 않는다. 상태를 알려 주는 자리에서 쓰는 함수라
        '죽었다'는 것도 정상적인 대답이기 때문이다. 대신 왜 안 되는지를
        주소 미설정·연결 실패·시간 초과·서버 오류로 나눠 한 문장씩 남긴다.
        """
        import httpx

        # 주소가 아예 없으면 물어볼 곳이 없다. 네트워크를 건드리지 않고 바로 답한다
        if not self._url:
            return LoraHealth(
                False,
                f"LoRA 받아쓰기 서버 주소({LORA_STT_URL_ENV})가 설정돼 있지 않다.",
            )

        # 통신로를 받아 왔으면 우리가 닫지 않는다(테스트가 계속 쓸 수 있어야 한다).
        # 이 규칙은 _call_server 와 똑같이 맞춰 둔다
        owned = self._http_client is None
        client = self._http_client or httpx.Client(timeout=timeout_s, follow_redirects=True)

        endpoint = self._url.rstrip("/") + "/health"
        try:
            try:
                response = client.get(endpoint, timeout=timeout_s)
            except httpx.TimeoutException:
                # 답이 없는 경우. 방화벽이 조용히 막으면 '연결 거부' 대신 여기로 오므로
                # (이 PC 의 127.0.0.1:8100 이 실제로 그랬다) 꺼져 있을 가능성도 같이 적는다
                return LoraHealth(
                    False,
                    f"LoRA 받아쓰기 서버({endpoint})가 {timeout_s:.0f}초 안에 답하지 않았다"
                    "(서버가 꺼져 있거나 모델을 불러오는 중일 수 있다).",
                )
            except httpx.HTTPError as exc:
                # 연결 거부·주소를 못 찾음 등. 8100 이 꺼져 있으면 대개 여기로 온다
                return LoraHealth(
                    False,
                    f"LoRA 받아쓰기 서버({endpoint})에 닿지 못했다. 서버가 꺼져 있거나 "
                    f"주소가 틀렸다(원인: {str(exc)[:120]}).",
                )

            # 서버가 오류로 답하면 떠 있어도 쓸 수 없는 상태로 본다
            if response.status_code >= 400:
                return LoraHealth(
                    False,
                    f"LoRA 받아쓰기 서버({endpoint})가 {response.status_code} 로 응답했다.",
                )

            # 200 이어도 모델을 아직 불러오는 중일 수 있다(서버가 status=loading 으로 답한다).
            # 그때 받아쓰기를 부르면 실패하므로 '살아 있음'으로 세지 않는다
            try:
                payload = response.json()
            except ValueError:
                payload = {}
            if isinstance(payload, dict) and payload.get("model_loaded") is False:
                return LoraHealth(
                    False,
                    f"LoRA 받아쓰기 서버({endpoint})는 떠 있지만 모델을 아직 불러오는 중이다.",
                )

            # 여기까지 왔으면 지금 받아쓰기를 부탁할 수 있는 상태다
            return LoraHealth(True, None)
        finally:
            if owned:
                client.close()

    def transcribe(self, audio: AudioInput, item_prompt: str = "") -> Transcription:
        """음성 하나를 RunPod 서버로 보내 받아쓴 글을 받아 온다.

        item_prompt 는 지금 쓰지 않는다. LoRA 는 문항 지시문 없이 소리만 보고
        받아쓰도록 학습했고, 지시문을 함께 주면 오히려 안 들린 자리를 그 지시문으로
        메울 위험이 생긴다(gemini_stt.py 의 무음 사고 참고). 그래서 규약은 맞추되
        값은 서버로 넘기지 않는다.
        """
        started = time.perf_counter()

        # 주소가 없으면 부를 수 없다. 여기서 분명히 알린다(빈 글을 지어내지 않는다)
        if not self.available:
            raise SttUnavailable(
                "음성을 글자로 옮길 수 없다. LoRA 받아쓰기 서버 주소"
                f"({LORA_STT_URL_ENV})가 설정돼 있지 않다."
            )

        # 1) 파일을 손에 넣는다(크기·형식·주소 관문을 여기서 지난다).
        #    무음 관문을 채점 PC 쪽에서 미리 걸어 두면 그래픽카드 호출을 아끼고,
        #    무음에 대고 서버가 무언가 지어내는 길도 애초에 막힌다
        fetched = fetch_audio(audio, http_client=self._http_client)

        # 2) 무음 관문 — 소리가 없는 녹음은 서버를 부르지 않는다(wav 만 잴 수 있다)
        if is_silent(fetched.loudness):
            raise SttUnavailable(silence_message(fetched.loudness))

        # 3) 서버로 음성을 보내 받아쓴 글을 받아 온다
        text, model, server_duration_ms = self._call_server(fetched)

        # 4) 빈 글이 오면 실패로 다룬다. '말을 안 한 답안'과 '받아쓰기 실패'를
        #    뒤섞지 않기 위해서다
        if not text.strip():
            raise SttUnavailable(
                "음성에서 말을 하나도 옮겨 적지 못했다. "
                "녹음이 비어 있거나 소리가 너무 작은지 확인해야 한다."
            )

        # 5) 거의 무음 관문 — 글은 나왔는데 소리가 사람 말이라기에 너무 작았던 경우
        if is_too_quiet_for_speech(fetched.loudness):
            raise SttUnavailable(too_quiet_message(fetched.loudness, text))

        # 서버가 모델 이름을 알려 줬으면 그것으로 덮어쓴다(채점 결과에 남는다)
        if model:
            self._model = model

        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        return Transcription(
            text=text.strip(),
            provider=self.provider_name,
            model=self._model,
            # 길이는 우리가 잰 값(wav)을 먼저 쓰고, 없으면 서버가 알려 준 값을 쓴다
            audio_duration_ms=fetched.duration_ms or server_duration_ms,
            audio_bytes=fetched.size_bytes,
            audio_format=fetched.audio_format,
            # LoRA 는 토큰이라는 단위를 쓰지 않는다
            input_tokens=None,
            output_tokens=None,
            elapsed_ms=elapsed_ms,
            warnings=list(fetched.warnings),
            # 발음은 이 구현이 내지 않는다. Azure 가 따로 붙인다(intake.py)
            pronunciation=None,
            # 대신 **방금 내려받은 파일을 그대로 딸려 보낸다.** 그래야 뒤이어 도는
            # Azure 발음 평가가 같은 음성을 또 내려받지 않는다(port.py 참고).
            # 이 값은 채점 결과로 나가지 않는다
            fetched_audio=fetched,
        )

    def _call_server(self, fetched) -> tuple[str, str, int | None]:
        """음성 알맹이를 서버로 보내고 (받아쓴 글, 모델 이름, 길이)를 꺼낸다.

        실패는 전부 SttUnavailable 로 바꿔 올린다. 종류를 나눠 사람이 읽을 수 있는
        한 문장으로 남긴다(주소 오타·서버 꺼짐·시간 초과·서버 오류).
        """
        import httpx

        # 통신로를 받아 왔으면 우리가 닫지 않는다(테스트가 계속 쓸 수 있어야 한다)
        owned = self._http_client is None
        client = self._http_client or httpx.Client(timeout=self._timeout_s, follow_redirects=True)

        endpoint = self._url.rstrip("/") + "/transcribe"
        try:
            try:
                response = client.post(
                    endpoint,
                    content=fetched.data,
                    headers={"Content-Type": fetched.mime_type},
                    timeout=self._timeout_s,
                )
            except httpx.TimeoutException as exc:
                raise SttUnavailable(
                    f"음성을 글자로 옮기지 못했다. LoRA 서버가 제한 시간"
                    f"({self._timeout_s:.0f}초) 안에 답하지 않았다.",
                    detail=str(exc),
                ) from exc
            except httpx.HTTPError as exc:
                raise SttUnavailable(
                    "음성을 글자로 옮기지 못했다. LoRA 받아쓰기 서버에 닿지 못했다"
                    "(주소가 맞는지, 서버가 떠 있는지 확인해야 한다).",
                    detail=str(exc),
                ) from exc

            # 서버가 오류(4xx·5xx)로 답하면 받아쓰기 실패로 다룬다
            if response.status_code >= 400:
                raise SttUnavailable(
                    f"음성을 글자로 옮기지 못했다. LoRA 서버가 {response.status_code} 로 응답했다.",
                    detail=response.text[:500],
                )

            try:
                payload = response.json()
            except ValueError as exc:
                raise SttUnavailable(
                    "LoRA 서버의 응답을 읽지 못했다(JSON 이 아니다).",
                    detail=response.text[:500],
                ) from exc
        finally:
            if owned:
                client.close()

        text = str(payload.get("text", "") or "")
        model = str(payload.get("model", "") or "")
        duration = payload.get("duration_ms")
        try:
            server_duration_ms = int(duration) if duration is not None else None
        except (TypeError, ValueError):
            server_duration_ms = None
        return text, model, server_duration_ms
