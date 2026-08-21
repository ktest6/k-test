"""Gemini 로 음성을 받아쓰는 구현. **v0 이고 임시다.**

원래 계획은 Azure 음성 서비스였다. 계정이 아직 없어서 그 자리에 Gemini 를 꽂았다.
Azure 계정이 나오면 이 파일과 같은 모양의 AzureStt 를 만들어 갈아 끼운다.
그때 고칠 곳은 speech 폴더 안뿐이고, 채점도 백엔드 API 형식도 바뀌지 않는다.

무엇을 못 하는지 (Azure 와 다른 점):
Azure 는 발음 평가(정확도·유창성 점수)를 함께 주지만 Gemini 는 글자만 준다.
그래서 '발화 전달력(delivery)' 영역은 지금도 채점하지 않는다(비중 0).
받아쓰기는 되지만 발음 채점은 아직 없다는 뜻이다.

──────────────────────────────────────────────────────────────────────
실측으로 확인한 한계 (2026-08-02, gemini-3.1-flash-lite)
──────────────────────────────────────────────────────────────────────
11.8초짜리 한국어 음성으로 두 번 확인했다(scripts/check_speech.py).

  잘 되는 것
    - 글자 일치율 95.8%. 내용 채점에 쓰기에 충분하다
    - 같은 음성을 두 번 받아쓰면 **글자 하나까지 같았다**(2/2). 재현성은 지켜진다
    - 받아쓰기 1회 2.6~3.7초, 입력 885 토큰 / 출력 55 토큰 (11.8초 음성 기준)

  안 되는 것 — 지시로도 못 막았다
    말한 것: "안 돼습니다"  ->  받아쓴 것: "안 됐습니다"   (학습자 오류가 지워짐)
    말한 것: "삼번"        ->  받아쓴 것: "3번"          (표기가 바뀜)

    "고치지 말라"는 지시에 더해 prompt.py 에 이 두 가지를 그대로 보기(few-shot)로
    넣어 두었는데도 **둘 다 그대로 고쳐졌다.** 프롬프트를 더 손봐서 될 일이 아니다.

그 이유와, 그래서 무엇을 조심해야 하는가:
두 경우 모두 **소리로는 구별되지 않는 자리다.** '삼번'과 '3번'은 소리가 완전히 같고,
'안 돼습니다'와 '안 됐습니다'도 말소리로는 거의 같다. 소리만 듣고 어느 쪽 철자로
쓰려 했는지 알아낼 방법은 원리상 없다. 즉 이것은 Gemini 를 잘못 골라서 생긴 일이
아니라 **음성에서 글자를 얻는 일 자체의 한계**이고, Azure 로 바꿔도 남을 가능성이 크다.

채점에 뜻하는 것:
소리로 구별되지 않는 표기·어미 오류는 말하기 답안에서 **감점되지 않는다.**
즉 말하기의 문법 점수는 실제 실력보다 높게 나올 수 있다. 응시자에게 불리한
방향은 아니지만 변별력이 그만큼 무뎌진다.
=> '말하기에서 표기 수준의 오류를 채점 대상으로 삼는 것이 맞는가'는
   프롬프트가 아니라 채점 설계에서 답할 문제다(scoring-design 스킬 참고).
   Azure 로 바꿀 때 이 항목을 가장 먼저 다시 재야 한다.

──────────────────────────────────────────────────────────────────────
무음에 대고 모범답안을 지어낸 사고와 그 수리 (2026-08-02)
──────────────────────────────────────────────────────────────────────
소리가 전혀 없는 wav(4초, 전부 0)를 말하기 답안으로 넣었더니
받아쓰기가 문항 지시문을 힌트 삼아 이런 글을 지어냈다.

    "어... 반장님 저기 기계가 갑자기 멈추었어요. 그래서 제가 전원 버튼을
     다시 눌러 봤는데 그래도 안 움직여요. 이제 어떻게 하면 좋을까요?"

이 글이 채점을 그대로 통과해 **78.07점 B** 가 나왔다.
아무 말도 하지 않은 응시자가 B를 받는 길이었다.

그래서 세 겹으로 막는다. 이 순서대로 지나야 점수가 나온다.

  1겹 (LLM 무관) 소리 크기를 직접 잰다. 무음이면 **부르지도 않는다**
                 -> loudness.py / 아래 transcribe() 의 관문 1
  2겹 (지시)     "말이 없으면 has_speech=false" 를 받아 온다
                 -> prompt.py + RESPONSE_SCHEMA
  3겹 (교차검증) 글이 나왔는데 소리가 너무 작았으면 그 글을 버린다
                 -> 아래 transcribe() 의 관문 3

**셋 중 무음을 실제로 막는 것은 1겹뿐이다.** 이것을 실측으로 확인해 두었다.
지시를 강하게 고쳐 쓴 뒤에도 같은 무음 wav 에 대해 모델은 이렇게 답했다.
    {"has_speech": true, "transcript": "어... 반장님 저기 기계가 갑자기 멈추었어요"}
소리가 없는데 '말이 있었다'고 답하고 답안까지 지어낸 것이다.
그러므로 2겹(지시)은 무음 방어로 믿으면 안 되고, 1겹이 작동하지 않는 경우
(= 소리를 잴 수 없는 압축 형식)에만 남는 보조로 봐야 한다.
3겹은 1겹의 기준값을 아슬아슬하게 넘긴 '거의 무음'을 위한 것이다.

여기서 나오는 결론 하나: **압축 형식(mp3·m4a·webm·ogg)의 무음은 아직 막히지 않는다.**
소리를 재려면 파일을 풀어야 하고 그러려면 ffmpeg 가 필요하다.
지금 응시 녹음이 wav 로 들어오므로 급하지 않지만, 형식이 바뀌면 먼저 닫아야 할 구멍이다.
"""

from __future__ import annotations

import os
import time

from ..llm.client import GeminiClient, LLMUnavailable, classify_failure
from ..scoring.schema import AudioInput
from .audio import FetchedAudio, fetch_audio
from .loudness import (
    is_silent,
    is_too_quiet_for_speech,
    silence_message,
    too_quiet_message,
)
from .port import SttPort, SttUnavailable, Transcription

#: 받아쓰기에 쓰는 모델. 채점·생성과 따로 둔다.
#: 모델을 바꿀 때 고칠 곳은 .env 의 GEMINI_MODEL_STT 하나다.
#: 실제 음성으로 받아쓰기가 되는 것을 확인한 모델이다.
DEFAULT_STT_MODEL = os.getenv("GEMINI_MODEL_STT", "gemini-3.1-flash-lite")

#: 기다려 줄 시간. 받아쓰기는 **일부러 채점(300초)보다 짧게 둔다.**
#: 받아쓰기가 늦어지면 뒤의 채점이 통째로 밀리는 데다, 실측 소요가 3초 안팎이라
#: 90초를 넘겼다면 정상 응답을 기다리는 중이 아니라 무언가 잘못된 것으로 보는 편이 맞다.
#: (채점 쪽이 300초인 것은 '생각하는 모델'이 55~68초를 쓰기 때문이며 여기와는 사정이 다르다)
#: **실측으로 정한 값이 아니라 추정값이다.** 긴 녹음에서 시간 초과가 나면 올린다.
STT_TIMEOUT_MS = 90_000

#: 받아쓴 글의 길이 상한. 넉넉하다 — 1분 발화가 대략 300자 안팎이다.
STT_MAX_OUTPUT_TOKENS = 4096

#: 받아쓴 결과를 담는 형식. 자유 문장이 아니라 이 모양으로만 받는다.
#: has_speech 를 함께 받는 이유: 빈 문자열만으로는 '말이 없었다'와
#: '받아쓰기가 실패했다'를 구별할 수 없어서, 모델이 스스로 밝히게 한다.
RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "has_speech": {"type": "BOOLEAN"},
        "transcript": {"type": "STRING"},
    },
    "required": ["has_speech", "transcript"],
}


class GeminiStt(SttPort):
    """Gemini 에 음성 파일을 보내 글로 받아 오는 구현체.

    받은 것을 그대로 믿지 않는 자리가 두 군데 있다.
      - 빈 글이 오면 실패로 다룬다 (뒤 단계가 '말을 안 한 답안'으로 채점하지 않게)
      - 지어낸 글을 걸러낼 방법은 없다. 그래서 위 설명에 한계를 적어 두었다
    """

    provider_name = "gemini"

    def __init__(
        self,
        client: GeminiClient | None = None,
        model: str | None = None,
        http_client=None,
    ):
        """받아쓰기용 클라이언트를 준비한다.

        client 를 넘기면 그 키를 그대로 쓴다(채점이 쓰던 것을 물려받는 자리).
        http_client 는 음성 파일을 내려받을 때 쓴다(테스트가 네트워크를 끊는 자리).
        """
        self._model = model or DEFAULT_STT_MODEL
        # 키를 읽고 실패 사유를 한국어로 정리하는 일은 채점 쪽 클라이언트가 이미 한다.
        # 같은 일을 여기에 다시 쓰지 않고 그것을 빌려 쓴다(기존 파일은 고치지 않는다)
        self._client = client or GeminiClient()
        self._http_client = http_client

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def available(self) -> bool:
        """키가 있어서 받아쓰기를 시도할 수 있는 상태인지."""
        return bool(getattr(self._client, "available", False))

    def transcribe(self, audio: AudioInput, item_prompt: str = "") -> Transcription:
        """음성 파일 하나를 받아써서 글과 그 내력을 돌려준다.

        순서는 다섯이고, 그중 셋이 '지어낸 글을 막는' 관문이다.
          1) 내려받는다 (크기·형식 관문을 여기서 지난다. 소리 크기도 여기서 재진다)
          2) **관문 1** 무음이면 Gemini 를 부르지 않고 여기서 끝낸다
          3) Gemini 에 음성과 지시문을 함께 보낸다
          4) **관문 2** 모델이 '말이 없었다'고 하거나 빈 글이면 실패로 다룬다
          5) **관문 3** 글이 나왔어도 소리가 너무 작았으면 그 글을 버린다
        """
        started = time.perf_counter()

        # 1) 파일을 손에 넣는다. 못 읽는 형식이나 너무 큰 파일은 여기서 막힌다
        fetched = fetch_audio(audio, http_client=self._http_client)

        # 2) 관문 1 — 소리가 없는 녹음은 LLM 에게 물어보지도 않는다.
        #    물어보면 모델이 문항 지시문을 힌트 삼아 모범답안을 지어낸다(실측).
        #    여기는 파일 안의 숫자만 보는 계산이라 모델이 무엇을 하든 결과가 같다.
        #    (wav 만 잴 수 있다. 압축 형식은 loudness 가 None 이라 그냥 지나간다)
        if is_silent(fetched.loudness):
            raise SttUnavailable(silence_message(fetched.loudness))

        # 3) 받아쓴다
        text, has_speech, usage = self._call_gemini(fetched, item_prompt)

        # 4) 관문 2 — 모델이 스스로 '말소리가 없었다'고 답한 경우와, 빈 글이 온 경우.
        #    빈 글을 그대로 넘기면 뒤 단계가 '아무 말도 안 한 답안'으로 채점해 버리는데,
        #    그것은 응시자가 말을 안 한 것과 받아쓰기가 실패한 것을 뒤섞는 일이다
        if not has_speech or not text.strip():
            raise SttUnavailable(
                "음성에서 말을 하나도 옮겨 적지 못했다. "
                "녹음이 비어 있거나 소리가 너무 작은지 확인해야 한다."
            )

        # 5) 관문 3 — 글은 나왔는데 소리는 사람 말이라기에 너무 작았던 경우.
        #    관문 1을 아슬아슬하게 넘긴 '거의 무음'에서 모범답안이 나오는 길을 막는다.
        #    소리와 글이 서로 어긋나면 글이 아니라 소리를 믿는다
        if is_too_quiet_for_speech(fetched.loudness):
            raise SttUnavailable(too_quiet_message(fetched.loudness, text))

        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        return Transcription(
            text=text.strip(),
            provider=self.provider_name,
            model=self._model,
            audio_duration_ms=fetched.duration_ms,
            audio_bytes=fetched.size_bytes,
            audio_format=fetched.audio_format,
            input_tokens=usage.get("input"),
            output_tokens=usage.get("output"),
            elapsed_ms=elapsed_ms,
            warnings=list(fetched.warnings),
        )

    def _call_gemini(
        self, fetched: FetchedAudio, item_prompt: str
    ) -> tuple[str, bool, dict[str, int | None]]:
        """음성을 실제로 보내고 (받아쓴 글, 말이 있었는지, 토큰 사용량)을 꺼낸다.

        채점 쪽 클라이언트의 generate_json 을 쓰지 않고 여기서 직접 부르는 이유:
        그 함수는 '글'만 보내도록 만들어져 있어서 음성 조각을 실을 자리가 없다.
        기존 채점 코드를 고치지 않기로 했으므로, 음성이 필요한 이 호출만 여기서 만든다.
        대신 temperature 0 · JSON 응답 같은 우리 규칙은 아래에서 똑같이 지킨다.
        """
        # 접속 객체와 키 확인은 채점 쪽 클라이언트에 맡긴다.
        # 키가 없으면 여기서 LLMUnavailable 이 나고 아래에서 받아쓰기 실패로 바꾼다
        try:
            raw_client = self._client._ensure_client()
        except LLMUnavailable as exc:
            raise SttUnavailable(
                f"음성을 글자로 옮길 수 없다. {exc}", detail=getattr(exc, "detail", "")
            ) from exc

        from google.genai import types

        from .prompt import SYSTEM_INSTRUCTION, build_transcription_prompt

        config = types.GenerateContentConfig(
            temperature=0.0,                        # 같은 음성은 같게 받아써야 한다
            max_output_tokens=STT_MAX_OUTPUT_TOKENS,
            response_mime_type="application/json",  # 자유 문장이 아니라 정해진 모양으로 받는다
            response_schema=RESPONSE_SCHEMA,
            system_instruction=SYSTEM_INSTRUCTION,
            http_options=types.HttpOptions(timeout=STT_TIMEOUT_MS),
        )

        try:
            response = raw_client.models.generate_content(
                model=self._model,
                # 음성 파일과 지시문을 함께 보낸다. 파일을 어디 올려 두지 않고
                # 요청에 바로 실어 보내는 방식이라 남는 것이 없다
                contents=[
                    types.Part.from_bytes(
                        data=fetched.data, mime_type=fetched.mime_type
                    ),
                    build_transcription_prompt(item_prompt),
                ],
                config=config,
            )
        except Exception as exc:
            # 실패 사유를 한국어 한 문장으로 바꾸는 일은 채점 쪽에 이미 있다. 그것을 쓴다
            raise SttUnavailable(
                f"음성을 글자로 옮기지 못했다. {classify_failure(exc)}", detail=str(exc)
            ) from exc

        text, has_speech = self._read_transcript(response)
        return text, has_speech, self._read_usage(response)

    @staticmethod
    def _read_transcript(response) -> tuple[str, bool]:
        """응답에서 받아쓴 글과 '말이 있었는지'를 꺼낸다.

        JSON 으로 받기로 했지만 형식이 깨져 오는 일이 실제로 있다.
        그때 통째로 버리면 멀쩡히 받아쓴 글까지 잃으므로,
        JSON 으로 안 읽히면 온 글을 그대로 받아쓴 글로 본다.
        (없는 값을 지어내는 것이 아니라, 모델이 준 글에서 껍데기만 벗기는 일이다)

        has_speech 를 못 읽었을 때는 True 로 본다.
        '모델이 안 알려 줬다'를 '말이 없었다'로 바꿔 읽으면 멀쩡한 답안이
        버려지기 때문이다. 무음을 막는 진짜 관문은 소리 크기 쪽(loudness.py)이라
        이 값은 보조로만 쓴다.
        """
        import json

        text = (getattr(response, "text", "") or "").strip()
        if not text:
            return "", True

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            # 앞뒤에 ```json 같은 군더더기가 붙은 경우를 한 번 더 시도한다
            first = text.find("{")
            if first == -1:
                return text, True
            try:
                parsed, _ = json.JSONDecoder().raw_decode(text[first:])
            except json.JSONDecodeError:
                return text, True

        if isinstance(parsed, dict):
            transcript = str(parsed.get("transcript", "") or "")
            # 값이 아예 없으면 True(모름)로 두고, 있으면 그대로 참/거짓으로 읽는다
            raw_flag = parsed.get("has_speech", True)
            has_speech = bool(raw_flag) if raw_flag is not None else True
            return transcript, has_speech
        return text, True

    @staticmethod
    def _read_usage(response) -> dict[str, int | None]:
        """토큰을 얼마나 썼는지 꺼낸다. 안 알려 주면 None 으로 둔다.

        비용을 나중에 계산할 수 있게 남기는 값이며 채점에는 쓰이지 않는다.
        """
        usage = getattr(response, "usage_metadata", None)
        if usage is None:
            return {"input": None, "output": None}
        return {
            "input": getattr(usage, "prompt_token_count", None),
            "output": getattr(usage, "candidates_token_count", None),
        }
