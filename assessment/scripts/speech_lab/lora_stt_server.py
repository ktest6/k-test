"""RunPod(그래픽카드 서버)에 띄우는 LoRA 받아쓰기 추론 서버.

채점 서버(내 PC)에는 그래픽카드가 없어서 우리가 학습한 Whisper LoRA 를 돌릴 수 없다.
그래서 이 서버를 RunPod 의 그래픽카드 위에 따로 띄워 두고, 채점 서버의
src/speech/lora_stt.py(LoraStt)가 여기로 음성을 보내 받아쓴 글만 받아 간다.

**이 파일은 speech_lab 환경(torch·transformers·peft 가 깔린 그래픽카드 서버)에서 돈다.**
채점 서버의 가벼운 venv 가 아니다. 채점 서버에는 이 무거운 것들을 올리지 않는다.

받아쓰기 방식은 scripts/speech_lab/eval_ab.py 의 AdapterWhisper 와 **글자 하나까지 똑같이**
맞췄다(베이스 모델 id·어댑터 로드법·generate 인자). 그래야 v2 어댑터가 학습·평가된
조건과 어긋나지 않는다. 조건이 어긋나면 여기서 나온 글이 우리가 실측해 둔 성능과 달라진다.

**발음(발화 전달력)은 이 서버가 하지 않는다.** 글자만 받아쓴다. 발음 점수는 음성을
직접 들은 Azure 가 채점 서버 쪽에서 따로 낸다(scoring-design: 전사는 LoRA, 발음은 Azure).

──────────────────────────────────────────────────────────────────────
RunPod 배포 순서 (이 순서대로 하면 채점 서버가 이 서버를 부를 수 있게 된다)
──────────────────────────────────────────────────────────────────────
1) 어댑터 올리기
   학습이 끝나 내려받아 둔 v2_adapter.tar.gz 를 RunPod 파드에 올리고 푼다.
       tar -xzf v2_adapter.tar.gz -C /workspace/adapters/v2
   푼 폴더 안에 adapter_config.json 과 adapter_model.safetensors,
   그리고 processor 파일(tokenizer·preprocessor)이 함께 있어야 한다
   (train_lora.py 가 model.save_pretrained + processor.save_pretrained 로 함께 저장한다).

2) 라이브러리 준비 (torch 는 파드에 이미 깔린 그래픽카드용을 그대로 쓴다)
       pip install -r scripts/speech_lab/requirements-lab.txt
       pip install fastapi uvicorn soundfile librosa httpx

3) 서버 실행 (어댑터 폴더를 환경변수로 가리킨다)
       export LORA_ADAPTER_DIR=/workspace/adapters/v2
       python scripts/speech_lab/lora_stt_server.py --port 8000
   시작할 때 모델을 한 번 불러 두므로(예열) 첫 요청이 느려지지 않는다.
   로그에 "모델 준비 완료" 가 뜨면 된다.

4) 포트 노출 / 터널
   RunPod 대시보드에서 8000 포트를 HTTP 로 노출하거나, cloudflared·runpodctl 로 터널을
   연다. 그러면 https<...>.proxy.runpod.net 같은 바깥 주소가 나온다.

5) 채점 서버에 주소 알려 주기
   나온 주소를 채점 서버의 .env 에 넣는다.
       LORA_STT_URL=https<...>.proxy.runpod.net
       KTEST_STT_PROVIDER=lora
   채점 서버를 다시 켜면 받아쓰기를 이 서버가 맡는다.
   (주소는 파드를 다시 켤 때마다 바뀌므로 그때마다 .env 를 갱신한다.)

6) 배포 뒤 스모크 (실제 호출 확인)
   - curl https<...>.proxy.runpod.net/health  → {"status":"ok", "model_loaded":true ...}
   - 짧은 한국어 wav 를 /transcribe 로 보내 글이 나오는지 확인
       curl -X POST --data-binary @sample.wav \
            -H "Content-Type: audio/wav" https<...>.proxy.runpod.net/transcribe
   - 채점 서버 /health 의 stt_provider 가 "lora" 로 보이는지 확인

──────────────────────────────────────────────────────────────────────
정직하게 남기는 것
──────────────────────────────────────────────────────────────────────
- **v2 어댑터는 아직 골든셋으로 검증되지 않았다.** 이 서버를 붙이는 목적은 데모와
  파이프라인 연결이지 받아쓰기 품질 보증이 아니다.
- 지금(2026-08-22)은 RunPod 파드가 떠 있지 않아 실제 호출 스모크를 하지 못했다.
  이 파일은 문법·임포트만 확인해 두었고, 실제 받아쓰기 확인은 위 6) 를 배포 후에 한다.
"""

from __future__ import annotations

import argparse
import io
import os
import time

# FastAPI 는 서버 뼈대. 어댑터를 담아 둘 전역 자리를 함께 만든다.
from fastapi import FastAPI, HTTPException, Request

#: 어댑터(학습해 둔 LoRA 판)를 푼 폴더. RunPod 에서 환경변수로 가리킨다.
ADAPTER_DIR_ENV = "LORA_ADAPTER_DIR"
#: 받아쓸 언어. 이 시험은 한국어만 본다(Whisper 표기로는 "korean").
LANGUAGE = os.getenv("LORA_LANGUAGE", "korean")

app = FastAPI(title="K-TEST LoRA STT", summary="Whisper LoRA 받아쓰기 추론 서버")

#: 불러 둔 모델을 담아 두는 자리. 시작할 때 한 번 채우고 요청마다 재사용한다.
_engine: "AdapterWhisper | None" = None


class AdapterWhisper:
    """우리가 학습한 LoRA 어댑터를 끼운 Whisper. 받아쓰기만 한다.

    받아쓰기 방식은 scripts/speech_lab/eval_ab.py 의 같은 이름 클래스와 똑같이 맞췄다
    (베이스 모델 id·어댑터 로드·generate 인자). 조건을 어기면 v2 가 학습·평가된
    상태와 달라지므로, 이 세 가지는 임의로 바꾸지 않는다.
    """

    def __init__(self, adapter_dir: str, device: str | None = None):
        import torch
        from peft import PeftConfig, PeftModel
        from transformers import WhisperForConditionalGeneration, WhisperProcessor

        self.torch = torch
        # 처리기(소리를 숫자로 바꾸는 도구 + 글자 사전). 어댑터 폴더에 함께 저장돼 있다
        self.processor = WhisperProcessor.from_pretrained(
            adapter_dir, language=LANGUAGE, task="transcribe"
        )

        # 어댑터 폴더에 '어떤 모델 위에 덧댄 것인지'가 적혀 있다. 그것을 읽어 베이스를 부른다
        base_name = PeftConfig.from_pretrained(adapter_dir).base_model_name_or_path
        base = WhisperForConditionalGeneration.from_pretrained(base_name)
        # 베이스 모델 위에 우리 어댑터(수십 MB)를 덧씌운다
        self.model = PeftModel.from_pretrained(base, adapter_dir).eval()

        # 그래픽카드가 있으면 그리로, 없으면 CPU 로(CPU 는 느리지만 확인은 된다)
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.model.to(self.device)

        # 채점 결과에 남길 모델 이름. 어댑터 폴더 이름을 붙여 어느 판인지 알 수 있게 한다
        self.model_name = f"whisper-small-lora-{os.path.basename(adapter_dir.rstrip('/')) or 'v2'}"

    def transcribe(self, wav_bytes: bytes) -> tuple[str, int]:
        """wav 알맹이를 받아써서 (받아쓴 글, 음성 길이 ms)를 돌려준다."""
        import librosa
        import numpy as np
        import soundfile as sf

        # 소리를 숫자 배열로 읽는다. 스테레오면 평균 내어 모노로 만든다
        wave, sr = sf.read(io.BytesIO(wav_bytes), dtype="float32")
        if wave.ndim > 1:
            wave = wave.mean(axis=1)
        # 음성 길이를 밀리초로 잰다(리샘플 전에 원래 촘촘함으로 계산한다)
        duration_ms = int(round(len(wave) / float(sr) * 1000)) if sr else 0
        # Whisper 는 16kHz 로 학습됐다. 촘촘함이 다르면 맞춘다
        if sr != 16_000:
            wave = librosa.resample(wave, orig_sr=sr, target_sr=16_000)

        # 소리를 모델이 먹는 형태(멜 스펙트로그램)로 바꾼다
        feats = self.processor.feature_extractor(
            np.asarray(wave, dtype="float32"), sampling_rate=16_000, return_tensors="pt"
        ).input_features.to(self.device)

        # 받아쓴다. 한국어·전사로 못 박아 영어 번역으로 새는 것을 막는다
        with self.torch.no_grad():
            ids = self.model.generate(
                input_features=feats, language=LANGUAGE, task="transcribe"
            )
        text = self.processor.batch_decode(ids, skip_special_tokens=True)[0].strip()
        return text, duration_ms


def _load_engine() -> AdapterWhisper:
    """어댑터를 불러 전역 자리에 담는다. 없으면 무엇이 빠졌는지 분명히 알린다."""
    adapter_dir = os.getenv(ADAPTER_DIR_ENV, "").strip()
    if not adapter_dir:
        raise RuntimeError(
            f"{ADAPTER_DIR_ENV} 가 설정돼 있지 않다. "
            "어댑터를 푼 폴더를 이 환경변수로 가리켜야 한다(파일 상단 배포 순서 1~3 참고)."
        )
    if not os.path.isdir(adapter_dir):
        raise RuntimeError(f"어댑터 폴더를 찾지 못했다: {adapter_dir}")
    print(f"모델 불러오는 중… (어댑터: {adapter_dir})")
    engine = AdapterWhisper(adapter_dir)
    print(f"모델 준비 완료 · {engine.model_name} · device={engine.device}")
    return engine


@app.on_event("startup")
def _startup() -> None:
    """서버가 켜질 때 모델을 미리 불러 둔다(첫 요청이 느려지지 않게 예열)."""
    global _engine
    _engine = _load_engine()


@app.get("/health", summary="서버와 모델 준비 상태 확인")
def health() -> dict:
    """서버가 살아 있는지, 모델이 올라와 있는지 알려 준다(배포 스모크에 쓴다)."""
    ready = _engine is not None
    return {
        "status": "ok" if ready else "loading",
        "model_loaded": ready,
        "model": _engine.model_name if ready else None,
        "device": _engine.device if ready else None,
        "language": LANGUAGE,
    }


@app.post("/transcribe", summary="음성을 받아써서 글을 돌려준다")
async def transcribe(request: Request) -> dict:
    """음성을 받아 받아쓴 글을 돌려준다.

    두 가지 방식으로 음성을 받는다.
      - wav 알맹이를 요청 본문(body)에 그대로 담아 보내는 방식 (LoraStt 가 쓰는 길)
      - {"url": "..."} JSON 으로 음성 주소를 보내면 서버가 내려받는 방식 (보조)

    돌려주는 것: {"text": 받아쓴 글, "model": 모델 이름, "duration_ms": 음성 길이}.
    """
    if _engine is None:
        # 예열이 아직 안 끝났다. 잠시 뒤 다시 부르라는 뜻으로 503 을 준다
        raise HTTPException(status_code=503, detail="모델이 아직 준비되지 않았다.")

    content_type = request.headers.get("content-type", "")

    # 방식 A: JSON 으로 주소를 받으면 서버가 내려받는다
    if content_type.startswith("application/json"):
        payload = await request.json()
        url = (payload or {}).get("url", "").strip()
        if not url:
            raise HTTPException(status_code=400, detail="url 이 비어 있다.")
        wav_bytes = _download(url)
    else:
        # 방식 B: 본문에 담긴 wav 알맹이를 그대로 쓴다
        wav_bytes = await request.body()

    if not wav_bytes:
        raise HTTPException(status_code=400, detail="음성 데이터가 비어 있다.")

    started = time.perf_counter()
    try:
        text, duration_ms = _engine.transcribe(wav_bytes)
    except Exception as exc:  # noqa: BLE001 - 어떤 실패든 원인을 담아 올린다
        raise HTTPException(status_code=500, detail=f"받아쓰기 실패: {exc}") from exc
    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)

    return {
        "text": text,
        "model": _engine.model_name,
        "duration_ms": duration_ms,
        "elapsed_ms": elapsed_ms,
    }


def _download(url: str) -> bytes:
    """음성 주소에서 파일을 내려받는다(JSON 방식일 때만 쓴다)."""
    import httpx

    try:
        response = httpx.get(url, timeout=60.0, follow_redirects=True)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=400, detail=f"음성을 내려받지 못했다: {exc}") from exc
    return response.content


def main() -> int:
    ap = argparse.ArgumentParser(description="K-TEST LoRA 받아쓰기 추론 서버")
    ap.add_argument("--host", default="0.0.0.0", help="들을 주소(RunPod 은 0.0.0.0)")
    ap.add_argument("--port", type=int, default=8000, help="들을 포트")
    args = ap.parse_args()

    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
