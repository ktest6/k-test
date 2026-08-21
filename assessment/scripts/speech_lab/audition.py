# -*- coding: utf-8 -*-
"""⑥ 세탁 탐지기 '증인단' 오디션 — 받아쓰기 모델 여러 종을 같은 시험지로 뽑는다.

무엇을 뽑는 자리인가:
세탁 탐지기(PLAN.md 8/6 채택)는 학습쌍 1만 개를 전수 검사해서 "사람 라벨이
학습자의 실수를 몰래 고쳐 놓은(=세탁한) 줄"을 찾아낸다. 판정 방식은 다수결이다.
여러 받아쓰기 모델(=증인)에게 같은 녹음을 들려주고, **증인들이 입을 모아 틀린
형태로 적었는데 사람 라벨만 표준형이면** 그 라벨을 세탁 의심으로 본다.

그래서 증인은 아무나 쓰면 안 된다. 두 가지 자격이 필요하다.

  ① 세탁하지 않는다 — 학습자가 틀린 자리를 조용히 고쳐 적는 모델은
     "다들 표준형으로 적었다"는 잘못된 증언을 만든다 (Gemini 가 여기서 탈락했다)
  ② 귀가 밝다 — 아무렇게나 받아쓰는 모델은 없는 오류를 만들어 낸다

두 자격은 서로 반대 방향으로 당긴다. 그래서 셋을 함께 재고 함께 본다.

  · CER(글자 오류율) 낮을수록 좋다 — 기본기
  · 오류 보존율 높을수록 좋다      — ①번 자격
  · 대조군 오탐율 낮을수록 좋다    — ②번 자격 (바르게 읽은 녹음에 없는 오류를 만드나)

**지표 계산은 이 파일에서 새로 만들지 않는다.** eval_ab.py 가 이미 쓰는 그 함수를
그대로 불러다 쓴다(evaluate·classify_preservation·is_measurable_error). 자를 새로
만들면 8/2 파일럿·8/5 실측과 오늘 숫자를 나란히 놓을 수 없게 되기 때문이다.

쓰는 법:
    set HF_HOME=D:\\해커톤데이터\\hf_cache
    python audition.py                          # 후보 전부
    python audition.py --only fw-small,qwen3    # 일부만
    python audition.py --max-n 10               # 빨리 훑어보기
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import (  # noqa: E402
    cer,
    diff_pairs,
    enable_utf8_output,
    load_audio_bytes,
    print_table,
    read_manifest,
)
# 지표 계산(evaluate)과 모델 로딩(BaseWhisper·AdapterWhisper)은 전부 여기서 빌려 쓴다.
# eval_ab.py 는 읽기만 하고 고치지 않는다 — 고치면 8/2·8/5 실측과 비교가 깨진다
from eval_ab import AdapterWhisper, BaseWhisper, evaluate  # noqa: E402

# ── 어디에 무엇을 두는가 ─────────────────────────────────────────────────────
#: 오디션 시험지. eval_ab.py 와 같은 것을 쓴다. 이 파일의 `ref` 는 8/4 사람 귀 감사로
#: 만든 **교정본**이라, 감사시트_교정.csv 와 100줄 전부 같다(대조 확인 완료).
DEFAULT_MANIFEST = Path(r"C:\해커톤\data\manifests\gold_100.jsonl")
#: 결과가 쌓이는 곳. C 드라이브 여유가 적어 실험 산출물은 D 로 뺀다.
OUT_DIR = Path(r"D:\해커톤데이터")
RESULT_JSON = OUT_DIR / "audition_results.json"
TRANSCRIPT_JSONL = OUT_DIR / "audition_transcripts.jsonl"
#: 후보 한 명이 끝날 때마다 그 성적을 곧바로 넣어 두는 서랍.
#: 왜 필요한가: CPU 로 큰 모델을 돌리면 후보 하나에 40분이 넘게 걸린다. 뒤에 선
#: 후보에서 한 번 넘어지면(실제로 8/7 에 메모리 부족으로 프로그램이 통째로 죽었다)
#: 앞서 몇 시간을 들여 받아쓴 것까지 전부 날아간다. 그래서 끝나는 대로 저장하고,
#: 다시 돌릴 때는 이미 끝낸 후보를 건너뛴다.
CACHE_DIR = OUT_DIR / "audition_cache"
#: 모델 내려받는 자리도 D 로 고정한다. C 에 받으면 남은 공간이 바닥난다.
HF_CACHE = OUT_DIR / "hf_cache"


def _pin_hf_cache() -> None:
    """모델 다운로드 폴더를 D 드라이브로 못 박는다.

    이 줄이 없으면 HuggingFace 는 C:\\Users\\...\\.cache 로 받는다. 후보 모델을
    다 받으면 10GB 가 넘는데 C 여유가 그만큼 없다. 그래서 파이썬이 관련 라이브러리를
    불러오기 **전에** 환경변수를 먼저 세워 둔다(라이브러리는 불러올 때 이 값을 읽는다).
    """
    HF_CACHE.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("HF_HOME", str(HF_CACHE))
    # 옛 이름을 보는 라이브러리(funasr 등)도 있어서 같이 세워 준다
    os.environ.setdefault("HUGGINGFACE_HUB_CACHE", str(HF_CACHE / "hub"))
    os.environ.setdefault("MODELSCOPE_CACHE", str(HF_CACHE / "modelscope"))


# ── 후보 선수들 ──────────────────────────────────────────────────────────────
# 공통 규칙: `.name` 과 `__call__(wav_bytes) -> 전사문자열` 만 있으면 eval_ab.evaluate 가
# 그대로 돌려 준다. 그래서 후보마다 이 두 가지만 맞춰 준다.


class FasterWhisperCandidate(BaseWhisper):
    """faster-whisper (Whisper 를 CPU 에서 빠르게 돌리는 판).

    eval_ab.BaseWhisper 를 그대로 물려받는다 = **심판 설정도 그대로 물려받는다.**
    (beam_size=1 · temperature=0.0 · condition_on_previous_text=False)
    8/5 에 이 설정을 못 박은 이유가 있다. 설정 없이 부르면 품질 검사에 걸릴 때
    온도를 올려 가며 다시 굴려서 같은 파일도 실행마다 답이 달라진다. 증인이
    실행마다 말을 바꾸면 다수결이 성립하지 않으므로 여기서도 같은 설정을 쓴다.
    """

    def __init__(self, size: str):
        super().__init__(size)
        self.name = f"fw({size})"


class Qwen3AsrCandidate:
    """Qwen3-ASR-1.7B — 말을 이해하며 받아쓰는 '문맥형' 후보.

    문맥형이란: 앞말을 보고 다음 글자를 지어내는 방식(자기회귀). 문장이 매끄럽게
    나오는 대신, 학습자가 틀리게 말하면 "그럴 리 없다"며 표준형으로 고쳐 적는
    버릇(=세탁)이 생기기 쉽다. 그 버릇이 실제로 얼마나 심한지 재려고 부른다.

    결정 설정: do_sample=False (주사위를 굴리지 않는 그리디 탐색) + num_beams=1.
    """

    #: transformers 형식으로 올라온 판. 원본 `Qwen/Qwen3-ASR-1.7B` 는 별도 패키지가
    #: 필요한데, 그 패키지가 transformers 4.57 을 못 박아서 이 컴퓨터의 5.x 와 충돌한다.
    REPO = "Qwen/Qwen3-ASR-1.7B-hf"

    def __init__(self):
        import torch
        from transformers import AutoProcessor, Qwen3ASRForConditionalGeneration

        self.torch = torch
        self.processor = AutoProcessor.from_pretrained(self.REPO)

        # 저장된 그대로의 정밀도(bfloat16)로 불러온다.
        # 왜 float32 로 올리지 않나: 이 모델 파일은 이미 bfloat16(숫자 하나에 2바이트)로
        # 저장돼 있어서, float32(4바이트)로 부풀리면 메모리가 4GB → 8GB 로 두 배가 된다.
        # 이 컴퓨터는 24GB 인데 다른 프로그램이 쓰고 남은 여유가 그만큼 안 돼서,
        # 실제로 8/7 에 가중치를 82% 까지 읽다가 프로그램이 통째로 죽었다.
        # 정밀도를 낮추는 것이 아니라 **저장된 정밀도를 그대로 쓰는 것**이라 손해도 없다.
        self.model = Qwen3ASRForConditionalGeneration.from_pretrained(
            self.REPO, dtype=torch.bfloat16, low_cpu_mem_usage=True
        ).eval()
        self.name = "qwen3-asr-1.7b"

    def __call__(self, wav_bytes: bytes) -> str:
        wave = _read_wave_16k(wav_bytes)

        # 이 모델은 '대화'로 지시를 받는다. 음성 한 덩이를 넣고 받아쓰라고 시킨다.
        #
        # 알려진 한계(8/7 실측): 다른 후보들에게는 "한국어다"라고 못 박아 주는데
        # (faster-whisper language="ko" · SenseVoice language="ko" · OWSM <kor>)
        # 이 모델은 transformers 경로에 그 칸이 없어서 스스로 알아맞히게 둔다.
        # 그 결과 100건 중 4건을 중국어·광둥어로 알아듣고 한자로 받아썼다.
        # 즉 아래 성적은 **다른 후보보다 불리한 조건에서 나온 것**이라, 고치면
        # 나빠질 일은 없고 좋아질 여지만 남아 있다.
        # → 고치는 길: 시스템 말머리에 한국어라는 힌트를 넣거나, Qwen 이 따로 내놓은
        #   `qwen_asr` 꾸러미의 language="ko" 를 쓴다(그 꾸러미는 transformers 판을
        #   4.57 로 못 박아서 이 컴퓨터에는 못 깐다 — requirements-lab.txt 참고).
        conversation = [
            {"role": "user", "content": [{"type": "audio", "audio": wave}]},
        ]
        text = self.processor.apply_chat_template(
            conversation, add_generation_prompt=True, tokenize=False
        )
        inputs = self.processor(text=text, audio=[wave], sampling_rate=16_000,
                                return_tensors="pt")

        # 소리에서 뽑은 특징은 float32 로 나오는데 모델은 bfloat16 이다.
        # 둘의 숫자 형식이 다르면 계산이 시작도 못 하고 멈추므로 모델 쪽에 맞춘다.
        # (글자 번호처럼 정수인 것은 그대로 둔다 — 형식을 바꾸면 뜻이 망가진다)
        inputs = {
            k: (v.to(self.torch.bfloat16) if hasattr(v, "dtype") and v.is_floating_point()
                else v)
            for k, v in inputs.items()
        }

        with self.torch.no_grad():
            out = self.model.generate(
                **inputs, max_new_tokens=256,
                do_sample=False, num_beams=1,   # 결정 설정: 같은 소리면 같은 답
            )
        # 지시문까지 같이 돌려주므로, 새로 지어낸 부분만 잘라 낸다
        new_ids = out[:, inputs["input_ids"].shape[1]:]
        text = self.processor.batch_decode(new_ids, skip_special_tokens=True)[0]

        # 이 모델은 받아쓴 글 앞에 "language Korean<asr_text>" 처럼 무슨 말인지
        # 알아맞힌 결과를 붙여 준다. 채점에는 방해라 표시 뒤쪽만 남긴다
        if "<asr_text>" in text:
            text = text.split("<asr_text>", 1)[1]
        return text.strip()


class SenseVoiceCandidate:
    """SenseVoice-Small — 소리를 곧바로 받아쓰는 '직청형' 후보.

    직청형이란: 앞말을 참고하지 않고 소리 조각마다 글자를 붙이는 방식
    (비자기회귀). 문장을 지어내지 않으니 세탁을 덜 한다고 기대되는 쪽이다.
    증인단에 이런 성격이 최소 하나는 들어가야 한다 — 문맥형끼리만 모으면
    다 같은 버릇으로 같이 틀려서 다수결이 '다수의 착각'이 된다.
    """

    REPO = "FunAudioLLM/SenseVoiceSmall"

    def __init__(self):
        from funasr import AutoModel

        # device="cpu": 그래픽카드가 없는 컴퓨터에서 돌린다
        self.model = AutoModel(model=self.REPO, device="cpu", disable_update=True,
                               hub="hf")
        self.name = "sensevoice-small"

    def __call__(self, wav_bytes: bytes) -> str:
        wave = _read_wave_16k(wav_bytes)
        res = self.model.generate(input=wave, language="ko", use_itn=True,
                                  batch_size_s=0)
        raw = res[0]["text"] if res else ""

        # 이 모델은 <|ko|><|NEUTRAL|> 같은 표시를 앞에 붙여 준다. 채점에는 방해라 뗀다
        from funasr.utils.postprocess_utils import rich_transcription_postprocess

        return rich_transcription_postprocess(raw).strip()


class Wav2Vec2CtcCandidate:
    """wav2vec2 한국어 CTC — 직청형 예비 후보(원래 6종 목록에 없던 **대체 경로**).

    왜 넣었나: 원래 직청형 자리는 SenseVoice·OWSM 이 맡기로 했는데, 둘 다 설치가
    막히면 증인단이 문맥형만 남는다. 그러면 "성격이 다른 귀를 섞는다"는 규칙이
    깨진다. 그 상황에 대비한 보험이다. CTC 는 소리 조각마다 글자를 하나씩
    붙이는 가장 단순한 방식이라, 문장을 지어낼 여지가 원리적으로 없다.

    임시성 표시: 이 후보는 팀이 합의한 6종 목록 밖이다. 채용되더라도
    '대체로 채운 자리'라는 것을 성적표에 남긴다.
    """

    REPO = "kresnik/wav2vec2-large-xlsr-korean"

    def __init__(self):
        import torch
        from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor

        self.torch = torch
        self.processor = Wav2Vec2Processor.from_pretrained(self.REPO)
        self.model = Wav2Vec2ForCTC.from_pretrained(self.REPO).eval()
        self.name = "w2v2-ko-ctc"

    def __call__(self, wav_bytes: bytes) -> str:
        wave = _read_wave_16k(wav_bytes)
        inputs = self.processor(wave, sampling_rate=16_000, return_tensors="pt")

        with self.torch.no_grad():
            logits = self.model(inputs.input_values).logits
        # CTC 는 시각마다 가장 점수 높은 글자를 고르는 것이 곧 그리디 = 항상 결정적이다
        ids = self.torch.argmax(logits, dim=-1)
        return self.processor.batch_decode(ids)[0].strip()


class OwsmCtcCandidate:
    """OWSM v4 CTC — 직청형 후보. espnet 설치가 필요하다.

    설치가 무겁다는 것을 알고 시도한다. 실제로 한 번 막혔다(아래 '설치 메모').
    30분 안에 길이 안 나면 탈락시키고 사유를 남길 작정이었고, 우회로가 나와서 살렸다.

    설치 메모(임시 조치라는 것을 분명히 남긴다):
      espnet 은 sentencepiece 를 **0.2.0 딱 그 판**으로 못 박아 두었는데,
      그 판에는 파이썬 3.13 · 윈도우용 미리 만들어진 설치본이 없다. 그래서 pip 가
      소스에서 직접 빌드하려 들고, 빌드 도구(cmake)가 없어 실패한다.
      우회: `pip install --no-deps espnet espnet_model_zoo` 로 못 박은 판 목록을
      건너뛰고, 필요한 다른 꾸러미만 손으로 채웠다. 이 컴퓨터에는 sentencepiece
      0.2.2 가 이미 있고 우리가 쓰는 기능(받아쓰기 추론)은 그대로 돌았다.
      → 리눅스나 파이썬 3.12 환경에서는 이 우회가 필요 없다.
    """

    REPO = "espnet/owsm_ctc_v4_1B"
    #: OWSM 은 30초짜리 통을 채워서 넣게 만들어져 있다(짧으면 뒤를 무음으로 채운다).
    #: 이 규칙을 안 지키면 소리를 반쯤 삼킨 채로 받아쓴다.
    FIXED_SEC = 30

    def __init__(self):
        import soundfile  # noqa: F401  (espnet 이 요구한다)
        from espnet2.bin.s2t_inference_ctc import Speech2TextGreedySearch
        from espnet_model_zoo.downloader import ModelDownloader

        # espnet 은 HF_HOME 을 보지 않고 **자기 설치 폴더 안**에 모델을 받는다.
        # 그러면 4GB 가 C 드라이브로 들어가는데 C 여유가 그만큼 없다.
        # 그래서 from_pretrained 를 그냥 부르지 않고, 받는 자리를 손으로 지정한다.
        downloader = ModelDownloader(str(HF_CACHE / "espnet"))
        parts = downloader.download_and_unpack(self.REPO)

        self.model = Speech2TextGreedySearch(
            **parts, device="cpu", use_flash_attn=False,
            lang_sym="<kor>", task_sym="<asr>",
        )
        self.name = "owsm-ctc-v4"

    def __call__(self, wav_bytes: bytes) -> str:
        import numpy as np

        wave = _read_wave_16k(wav_bytes)
        need = 16_000 * self.FIXED_SEC

        # 30초를 넘는 녹음은 앞부분만 쓰면 뒷말이 통째로 사라져 CER 이 억울하게 나빠진다.
        # (이 시험지 100건 중 11건이 30초를 넘는다 — 전부 자유발화 문항)
        # 그래서 30초씩 잘라 각각 받아쓰고 이어 붙인다.
        # 한계: 자른 자리에서 낱말이 반 토막 날 수 있다. OWSM 이 제공하는 정식
        # 장문 처리(앞뒤를 겹쳐 읽는 방식)보다 거칠지만, 무엇이 일어나는지가
        # 눈에 보이는 방식이라 오디션 단계에서는 이쪽을 쓴다.
        chunks = [wave[i:i + need] for i in range(0, max(len(wave), 1), need)]

        pieces = []
        for chunk in chunks:
            # 짧은 조각은 뒤를 0(무음)으로 채워 30초 통을 맞춘다. OWSM 이 그렇게 만들어져 있다
            if len(chunk) < need:
                chunk = np.pad(chunk, (0, need - len(chunk)))
            # 돌려주는 값은 (받아쓴 글, 낱말들, 번호들, …) 묶음의 목록. 첫 묶음의 첫 칸이 글이다
            text = self.model(chunk)[0][0]

            # 글 앞에 "<kor><asr>" 처럼 무슨 말·무슨 일인지 적은 표시가 붙어 나온다. 떼어 낸다
            while text.startswith("<") and ">" in text:
                text = text.split(">", 1)[1]
            pieces.append(text.strip())

        return " ".join(p for p in pieces if p).strip()


class CohereTranscribeCandidate:
    """Cohere Transcribe — 문맥형 후보. 라이선스와 접근 권한을 먼저 확인해야 한다.

    라이선스는 Apache 2.0 으로 상업 이용에 걸림돌이 없다(모델 카드 확인).
    다만 저장소가 '연락처 동의' 관문(gated)에 걸려 있어서 HuggingFace 로그인
    토큰이 없으면 파일을 받을 수 없다. 토큰이 없는 환경이면 탈락 처리한다.
    """

    REPO = "CohereLabs/cohere-transcribe-03-2026"

    def __init__(self):
        import torch
        from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor

        self.torch = torch
        self.processor = AutoProcessor.from_pretrained(self.REPO)
        self.model = AutoModelForSpeechSeq2Seq.from_pretrained(
            self.REPO, dtype=torch.float32
        ).eval()
        self.name = "cohere-transcribe"

    def __call__(self, wav_bytes: bytes) -> str:
        wave = _read_wave_16k(wav_bytes)
        inputs = self.processor(audio=wave, sampling_rate=16_000, return_tensors="pt")
        with self.torch.no_grad():
            out = self.model.generate(**inputs, do_sample=False, num_beams=1,
                                      max_new_tokens=256)
        return self.processor.batch_decode(out, skip_special_tokens=True)[0].strip()


class LoraV1Candidate(AdapterWhisper):
    """우리가 8/5 에 학습한 LoRA v1 — 집안 후보. 문맥형(Whisper 계열)이다.

    왜 오디션에 넣나: v1 은 '학습자가 틀리게 말한 것을 고쳐 적지 말라'고
    가르친 모델이다. 증인단이 요구하는 ①번 자격(세탁하지 않는다)을 겨냥해
    만든 것이므로, 밖에서 데려온 후보들과 같은 시험지로 나란히 세워 봐야
    실제로 그 자격을 갖췄는지 알 수 있다.

    **모델을 불러오고 받아쓰는 코드는 한 줄도 새로 쓰지 않는다.**
    eval_ab.AdapterWhisper 를 그대로 물려받는다 = 8/5 결정 모드 평가에서
    v1 의 CER 16.6% 를 잰 바로 그 코드·그 설정이다. 여기서 디코딩 설정을
    조금이라도 손대면 오늘 숫자와 8/5 숫자를 나란히 놓을 수 없게 된다.
    (물려받은 설정: 주사위 없는 그리디 · language="korean" · task="transcribe")

    바꾸는 것은 이름표 하나뿐이다. 성적표에서 다른 후보와 구분되게 하려는 것이다.
    """

    #: 8/5 학습 산출물. 원본 Whisper small 위에 덧씌우는 어댑터(7MB)만 들어 있다
    ADAPTER_DIR = r"D:\해커톤데이터\adapters\v1"

    def __init__(self):
        # 어댑터 경로만 못 박아 부모에게 넘긴다. 로딩·디코딩은 전부 부모 것이다
        super().__init__(self.ADAPTER_DIR)
        # 부모가 붙이는 이름은 "lora(v1)" 인데, 성적표에서 집안 후보임이 바로
        # 보이도록 바꿔 단다(다른 후보와 섞어 놓고 볼 표라서)
        self.name = "lora-v1(우리)"


#: 오디션 참가자 명단.
#:   유형 — 문맥형(앞말을 보고 지어냄) / 직청형(소리만 듣고 붙임)
#:   출처 — 팀이 8/6 에 정한 6종인지, 자리를 메우려고 넣은 대체 후보인지
CANDIDATES = {
    "fw-small":     {"만들기": lambda: FasterWhisperCandidate("small"),
                     "유형": "문맥형", "출처": "8/6 목록", "비고": "기준 증인"},
    "fw-medium":    {"만들기": lambda: FasterWhisperCandidate("medium"),
                     "유형": "문맥형", "출처": "크기 사다리(8/9)",
                     "비고": "small↔large 사이"},
    "fw-large-v3":  {"만들기": lambda: FasterWhisperCandidate("large-v3"),
                     "유형": "문맥형", "출처": "8/6 목록", "비고": ""},
    "qwen3-asr":    {"만들기": Qwen3AsrCandidate,
                     "유형": "문맥형", "출처": "8/6 목록", "비고": ""},
    "sensevoice":   {"만들기": SenseVoiceCandidate,
                     "유형": "직청형", "출처": "8/6 목록", "비고": ""},
    "owsm-v4":      {"만들기": OwsmCtcCandidate,
                     "유형": "직청형", "출처": "8/6 목록", "비고": "espnet 필요"},
    "cohere":       {"만들기": CohereTranscribeCandidate,
                     "유형": "문맥형", "출처": "8/6 목록", "비고": "gated 저장소"},
    "w2v2-ko":      {"만들기": Wav2Vec2CtcCandidate,
                     "유형": "직청형", "출처": "대체(목록 밖)",
                     "비고": "직청형 자리 보험"},
    "lora-v1":      {"만들기": LoraV1Candidate,
                     "유형": "문맥형", "출처": "자체 학습(8/5)",
                     "비고": "Whisper small + LoRA"},
}


# ── 소리 읽기 ────────────────────────────────────────────────────────────────
def _read_wave_16k(wav_bytes: bytes):
    """wav 한 개를 모델이 먹을 수 있는 형태(16kHz 한 채널 숫자열)로 바꾼다.

    faster-whisper 말고는 대부분 '파일'이 아니라 '숫자열'을 받는다. 촘촘함이
    16kHz 가 아니면 소리가 빨라지거나 느려져 엉뚱하게 들리므로 반드시 맞춘다.
    """
    import numpy as np
    import soundfile as sf

    wave, sr = sf.read(io.BytesIO(wav_bytes), dtype="float32")
    # 스테레오(두 채널)면 평균 내서 한 줄로 만든다
    if wave.ndim > 1:
        wave = wave.mean(axis=1)
    if sr != 16_000:
        import librosa

        wave = librosa.resample(wave, orig_sr=sr, target_sr=16_000)
    return np.asarray(wave, dtype="float32")


# ── 전사를 받아 적어 두는 껍데기 ─────────────────────────────────────────────
class _Recorder:
    """후보를 감싸서, 채점과 동시에 **어떤 파일을 뭐라고 적었는지**를 모아 둔다.

    왜 이런 껍데기가 필요한가: 지표 계산은 eval_ab.evaluate 에 맡기기로 했는데
    그 함수는 점수만 돌려주고 개별 전사는 버린다. 그런데 세탁 탐지기는 나중에
    이 전사들로 다수결을 해야 하므로 한 건도 버리면 안 된다. evaluate 를
    고치는 것은 금지(과거 숫자와의 비교가 깨진다)라, 대신 후보를 감쌌다.

    파일을 알아보는 방법은 소리 내용의 지문(해시)이다. evaluate 는 후보에게
    파일 이름을 알려 주지 않고 소리만 건네주기 때문이다.
    """

    def __init__(self, inner, id_by_hash: dict[str, str]):
        self.inner = inner
        self.name = inner.name
        self._id_by_hash = id_by_hash
        self.transcripts: dict[str, str] = {}

    def __call__(self, wav_bytes: bytes) -> str:
        text = self.inner(wav_bytes)
        # 소리 내용으로 지문을 떠서 어느 줄이었는지 되짚는다
        key = hashlib.sha1(wav_bytes).hexdigest()
        row_id = self._id_by_hash.get(key)
        if row_id:
            self.transcripts[row_id] = text
        return text


# ── 결정성(같은 소리에 같은 답을 하는가) 확인 ────────────────────────────────
def check_determinism(transcriber, rows: list[dict], recorded: dict[str, str],
                      n: int = 2) -> dict:
    """같은 파일 몇 건을 한 번 더 받아쓰게 해서 처음과 같은 답이 나오는지 본다.

    증인이 물을 때마다 다르게 증언하면 다수결의 근거가 무너진다. 실제로 8/5 에
    faster-whisper 가 설정 없이는 실행마다 CER 12.2~15.4% 로 흔들리는 것을
    실측했다. 그래서 채용 전에 반드시 이 검사를 통과해야 한다.
    """
    checked, same = [], 0
    for r in rows:
        if r["id"] not in recorded:
            continue
        try:
            again = transcriber(load_audio_bytes(r))
        except Exception as exc:
            checked.append({"id": r["id"], "일치": False, "사유": str(exc)[:60]})
            continue
        # 글자 하나까지 똑같아야 통과로 본다(공백만 앞뒤로 다듬어 비교)
        ok = again.strip() == recorded[r["id"]].strip()
        same += ok
        checked.append({"id": r["id"], "일치": ok,
                        "1차": recorded[r["id"]][:40], "2차": again[:40]})
        if len(checked) >= n:
            break

    return {"검사건수": len(checked), "일치건수": same,
            "결정적": bool(checked) and same == len(checked), "사례": checked}


# ── 후보 한 명 돌리기 ────────────────────────────────────────────────────────
def run_candidate(key: str, meta: dict, rows: list[dict],
                  id_by_hash: dict[str, str]) -> dict:
    """후보 하나를 시험지 전체에 돌려 성적 한 줄을 만든다.

    준비(모델 내려받기·불러오기)에서 넘어지는 후보가 반드시 나온다. 그때
    전체를 멈추지 않고 **탈락 사유를 적어 남기고 다음 후보로 넘어간다.**
    무엇이 왜 안 됐는지가 성적표의 일부다.
    """
    print(f"\n── [{key}] {meta['유형']} · {meta['출처']} — 준비 중", flush=True)
    t_load = time.perf_counter()

    try:
        inner = meta["만들기"]()
    except Exception as exc:
        # 준비 실패 = 탈락. 사유를 한 줄로 남긴다(원인 추적용 뒷부분도 함께)
        reason = f"{type(exc).__name__}: {str(exc)[:200]}"
        print(f"   탈락 — 준비 실패: {reason}", flush=True)
        return {"key": key, "이름": key, **_meta_fields(meta),
                "상태": "탈락", "탈락사유": f"준비 실패 — {reason}",
                "추적": traceback.format_exc()[-800:]}

    load_sec = time.perf_counter() - t_load
    print(f"   준비 완료 ({load_sec:.0f}초). {len(rows)}건 받아쓰는 중…", flush=True)

    rec = _Recorder(inner, id_by_hash)
    try:
        result = evaluate(rec, rows)          # ← 지표 계산은 전부 eval_ab 의 것
    except Exception as exc:
        reason = f"{type(exc).__name__}: {str(exc)[:200]}"
        print(f"   탈락 — 평가 도중 중단: {reason}", flush=True)
        return {"key": key, "이름": inner.name, **_meta_fields(meta),
                "상태": "탈락", "탈락사유": f"평가 중단 — {reason}",
                "추적": traceback.format_exc()[-800:]}

    # 다시 받아쓰게 할 때는 껍데기(rec) 말고 **원본 모델(inner)** 을 넘긴다.
    # 8/9 에 여기서 버그를 찾았다: 껍데기를 넘기면 다시 받아쓰는 순간 껍데기가
    # 자기 공책(rec.transcripts)에 새 답을 덮어쓰고, 그 다음에 '새 답 == 공책'을
    # 비교했다. 자기 자신과 견주는 셈이라 어떤 모델이든 무조건 '통과'가 나왔다.
    # 실제로 sensevoice 는 같은 파일을 다르게 적었는데도 '일치'로 기록됐다.
    det = check_determinism(inner, rows, rec.transcripts)

    # 이 후보의 모델을 메모리에서 내려놓는다.
    # 안 내려놓으면 후보가 하나씩 쌓여서(Whisper large 1.5GB + Qwen 4GB …) 결국
    # 메모리가 바닥나 프로그램이 통째로 죽는다. 8/7 에 실제로 그렇게 죽었다.
    _release_model(inner)

    # 아무 글자도 못 적고 넘어간 녹음을 따로 센다.
    # 왜 따로 세나: 빈 전사는 CER 을 1.0(전부 틀림)으로 만들어 성적을 크게 끌어내리는데,
    # 표에 CER 만 있으면 "귀가 나쁘다"로 오해된다. 실제로는 '말이 없다고 판단하고
    # 통째로 건너뛴 것'이라 성격이 다른 문제다. 증인으로서는 더 나쁘다 — 증언을
    # 아예 안 하는 증인이기 때문이다. 그래서 숫자를 눈에 보이게 남긴다.
    empty = sum(1 for t in rec.transcripts.values() if not t.strip())

    print(f"   끝: CER {_pct(result['cer'])} · 보존율 {_pct(result['보존율'])} · "
          f"오탐율 {_pct(result['오탐율'])} · 빈전사 {empty}건 · {result['초']:.0f}초 · "
          f"결정성 {'통과' if det['결정적'] else '불합격'}", flush=True)

    return {
        "key": key, "이름": inner.name, **_meta_fields(meta),
        "상태": "완주",
        "건수": result["n"], "실패건수": result["실패"],
        "CER": result["cer"], "보존율": result["보존율"],
        "보존": result["counts"]["보존"], "세탁": result["counts"]["세탁"],
        "기타": result["counts"]["기타"],
        "측정불가제외": result["측정불가제외"],
        "대조군": result["대조군"], "오탐율": result["오탐율"],
        "빈전사": empty,
        "처리초": result["초"], "준비초": load_sec,
        "건당초": result["초"] / result["n"] if result["n"] else None,
        "결정성": det,
        "판정사례": result["examples"],
        "전사": rec.transcripts,
    }


def add_robust_cer(result: dict, rows: list[dict]) -> dict:
    """평균 CER 옆에 **가운뎃값 CER** 과 '폭주' 건수를 덧붙인다.

    왜 필요한가 (8/7 실측에서 드러난 함정):
    faster-whisper small 의 평균 CER 은 56.7% 로 처참해 보였다. 그런데 100건을
    하나씩 뜯어 보니 가운뎃값은 7.7% 였다. 100건 중 4건에서 모델이 같은 말을
    끝없이 되풀이하는 '폭주'(예: "8 8 8 8 8 …" 444글자)를 일으켰고, 그 몇 건이
    평균을 통째로 끌어내린 것이다. 평균만 보면 "귀가 나쁜 모델"로 읽히지만
    실제 성격은 "평소엔 잘 듣는데 가끔 발작하는 모델"이라 대처법이 다르다.

    그래서 세 숫자를 함께 낸다:
      평균 CER   — 예전 실측(eval_ab)과 견주기 위해 그대로 둔다
      가운뎃값 CER — 보통 때 이 모델의 실력
      폭주 건수  — 정답보다 두 배 넘게 길게 쏟아 낸 건수 (CER > 100%)

    돌려주는 값은 세 숫자를 채워 넣은 성적 한 줄이다(원래 것을 고쳐서 돌려준다).
    """
    ref_by_id = {r["id"]: r["ref"] for r in rows}
    scores = [
        cer(ref_by_id[i], t) for i, t in result.get("전사", {}).items() if i in ref_by_id
    ]
    if not scores:
        result["중앙CER"], result["폭주"] = None, None
        return result

    scores.sort()
    # 가운뎃값 = 성적을 줄 세웠을 때 한가운데 있는 값. 몇 건이 튀어도 흔들리지 않는다
    result["중앙CER"] = scores[len(scores) // 2]
    # 받아쓴 글이 정답보다 두 배 넘게 길어진 경우를 '폭주'로 본다
    result["폭주"] = sum(1 for s in scores if s > 1.0)
    return result


def _release_model(inner) -> None:
    """후보 하나가 쓰던 모델을 메모리에서 치운다.

    파이썬은 '아무도 안 쓰는 것'만 알아서 치우는데, 후보 객체가 모델을 붙들고
    있으면 계속 쓰는 것으로 본다. 그래서 붙들고 있는 손을 하나씩 놓아 준 뒤
    청소를 시킨다(gc.collect).
    """
    import gc

    for attr in ("model", "processor", "stt", "s2t_model"):
        try:
            delattr(inner, attr)
        except Exception:
            # 그런 이름이 없거나 지울 수 없는 후보도 있다. 넘어가면 된다
            pass
    gc.collect()


def _cache_path(key: str) -> Path:
    """후보 하나의 성적을 넣어 둘 파일 자리."""
    return CACHE_DIR / f"{key}.json"


def _load_cached(key: str, manifest: Path, n_rows: int) -> dict | None:
    """이미 끝내 둔 성적이 있으면 꺼내 온다. 시험지가 다르면 쓰지 않는다.

    같은 후보라도 **다른 시험지·다른 건수**로 잰 숫자를 섞으면 표가 거짓말이 된다.
    그래서 저장할 때 시험지 이름과 건수를 함께 적어 두고, 여기서 대조한다.
    """
    p = _cache_path(key)
    if not p.exists():
        return None
    try:
        saved = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None

    if saved.get("_시험지") != str(manifest) or saved.get("_평가건수") != n_rows:
        print(f"   (서랍에 든 {key} 성적은 다른 시험지 것이라 버리고 다시 잰다)")
        return None
    return saved


def _save_cached(key: str, result: dict, manifest: Path, n_rows: int) -> None:
    """후보 하나가 끝나는 즉시 성적을 서랍에 넣는다. 뒤에서 죽어도 이건 남는다."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    payload = dict(result)
    payload["_시험지"] = str(manifest)
    payload["_평가건수"] = n_rows
    _cache_path(key).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _meta_fields(meta: dict) -> dict:
    """명단에 적어 둔 성격 정보(유형·출처·비고)를 성적 한 줄에 옮겨 붙인다."""
    return {"유형": meta["유형"], "출처": meta["출처"], "비고": meta["비고"]}


def _pct(v) -> str:
    """비율을 백분율 글자로 바꾼다. 잴 수 없었던 칸은 '측정불가'로 적는다."""
    if v is None or v != v:      # v != v 는 '숫자가 아님(NaN)' 을 가리킨다
        return "측정불가"
    return f"{v:.1%}"


# ── 채용 심사 ────────────────────────────────────────────────────────────────
def recommend(results: list[dict]) -> tuple[list[dict], list[str]]:
    """성적표를 보고 증인 3~4명을 고른다. 고른 이유도 함께 돌려준다.

    규칙(작업 지시서 그대로):
      ① 세탁을 가장 많이 한 급은 뺀다 — 증인단의 존재 이유가 세탁 탐지인데
         증인이 세탁하면 사람 라벨의 세탁을 잡아낼 수 없다
      ② CER 이 극단으로 나쁜 후보는 뺀다 — 귀가 어두우면 증언이 헛소리다
      ③ 문맥형 2 + 직청형 최소 1 을 채워 3~4명 — 성격이 같은 귀만 모으면
         같이 틀려서 다수결이 '다수의 착각'이 된다
    """
    ok = [r for r in results if r["상태"] == "완주"]
    notes: list[str] = []
    if not ok:
        return [], ["완주한 후보가 없어 채용 심사를 하지 못했다."]

    # ── ② CER 극단 탈락 ────────────────────────────────────────────────────
    # 귀가 밝은지는 **가운뎃값 CER** 로 본다. 평균이 아니다.
    # 까닭: 8/7 실측에서 faster-whisper small 의 평균 CER 은 56.7% 였지만
    # 가운뎃값은 7.7% 였다. 100건 중 4건의 '폭주'(같은 말 무한 반복)가 평균을
    # 통째로 끌어내린 것이다. 평균으로 자르면 평소 잘 듣는 모델이 몇 건 때문에
    # 통째로 잘려 나간다. 폭주는 폭주대로 아래에서 따로 심사한다.
    #
    # 상한 = 최고 성적의 2배, 또는 최고 성적 +15%p 중 **더 너그러운 쪽**.
    # 배수만 쓰면 1등이 아주 잘한 날(예: 5%) 상한이 10%로 좁아져서 10.1% 로
    # 멀쩡히 받아쓴 후보까지 잘린다. 우리가 빼려는 것은 '조금 처지는 후보'가
    # 아니라 '증언이 헛소리인 후보'라 절대 폭을 바닥으로 깔아 둔다.
    # (절대 기준 하나만 못 박지 않은 이유는 반대다 — 시험지가 어려워지면
    #  전체 CER 대가 통째로 올라가 아무도 못 넘는 선이 되기 때문이다.)
    def ear(r):
        """이 후보의 '평소 실력' CER. 가운뎃값이 없으면 평균으로 대신한다."""
        return r["중앙CER"] if r.get("중앙CER") is not None else r["CER"]

    best_cer = min(ear(r) for r in ok if ear(r) == ear(r))
    cer_limit = max(best_cer * 2, best_cer + 0.15)

    survivors = []
    for r in ok:
        # ②-1 귀 검사 (가운뎃값 기준)
        if ear(r) != ear(r) or ear(r) > cer_limit:
            notes.append(f"{r['이름']}: 중앙 CER {_pct(ear(r))} 가 상한 "
                         f"{_pct(cer_limit)}(최고 {_pct(best_cer)} 기준)을 넘어 제외 "
                         f"(평균 CER {_pct(r['CER'])})")
            continue

        # ②-2 폭주 검사 — 열 건에 한 건꼴로 발작하면 증언을 믿을 수 없다.
        # 폭주한 전사는 아무 말과도 안 맞아 '기타'로 빠지므로 세탁을 만들지는
        # 않는다. 다만 그 자리에서는 증인이 통째로 침묵한 것과 같아서,
        # 다수결에 참여하는 실제 인원이 조용히 줄어든다.
        runaway = r.get("폭주") or 0
        if r.get("건수") and runaway / r["건수"] > 0.10:
            notes.append(f"{r['이름']}: 폭주 {runaway}건/{r['건수']}건 "
                         f"(같은 말 무한 반복) — 열에 하나가 넘어 제외")
            continue

        if runaway:
            notes.append(f"참고: {r['이름']} 은 폭주 {runaway}건 "
                         f"({runaway / r['건수']:.0%}) — 그 자리에서는 증언이 빠진다")
        if r.get("빈전사"):
            notes.append(f"참고: {r['이름']} 은 빈 전사 {r['빈전사']}건 "
                         f"— 그 자리에서는 증언이 빠진다")
        survivors.append(r)

    # ── ① 세탁 최다급 탈락: 보존율이 가장 낮은 후보를 뺀다 ────────────────
    # 단, 남은 인원이 4명 이하로 빠듯하면 뺄 여유가 없으므로 경고만 남긴다
    scored = [r for r in survivors if r["보존율"] == r["보존율"]]
    if len(scored) >= 5:
        worst = min(scored, key=lambda r: r["보존율"])
        notes.append(f"{worst['이름']}: 보존율 {_pct(worst['보존율'])} 로 최하위 "
                     f"— 세탁 최다급이라 제외")
        survivors = [r for r in survivors if r is not worst]
    elif scored:
        worst = min(scored, key=lambda r: r["보존율"])
        notes.append(f"참고: 최하위 보존율은 {worst['이름']} {_pct(worst['보존율'])} "
                     f"— 완주자가 {len(scored)}명뿐이라 '최다급 탈락' 규칙은 적용하지 않았다")

    # ── 순위: 보존율이 높고 오탐율이 낮은 쪽이 좋은 증인이다 ──────────────
    # 오탐율을 못 잰 후보는 최악(1.0)으로 놓아 우연히 앞서지 않게 한다
    def merit(r):
        preserve = r["보존율"] if r["보존율"] == r["보존율"] else 0.0
        false_alarm = r["오탐율"] if r["오탐율"] == r["오탐율"] else 1.0
        return preserve - false_alarm

    survivors.sort(key=merit, reverse=True)

    # ── ③ 성격 섞기: 문맥형 2 + 직청형 1 을 먼저 채우고, 남으면 한 명 더 ──
    hired: list[dict] = []
    for kind, quota in (("문맥형", 2), ("직청형", 1)):
        pool = [r for r in survivors if r["유형"] == kind and r not in hired]
        if len(pool) < quota:
            notes.append(f"{kind} 자리 {quota}명이 필요한데 완주자가 {len(pool)}명뿐이다 "
                         f"— 증인단 성격이 한쪽으로 쏠린다(다수결 신뢰도 주의)")
        hired.extend(pool[:quota])

    # 세 명이 찼고 여유가 있으면 성적 순으로 한 명을 더 태워 4명으로 만든다.
    # 짝수(4)가 되면 2:2 로 갈리는 일이 생기는데, 그때는 '판정 보류'로 두면 된다
    for r in survivors:
        if len(hired) >= 4:
            break
        if r not in hired:
            hired.append(r)

    return hired, notes


# ── 성적표 출력 ──────────────────────────────────────────────────────────────
def print_report(results: list[dict], hired: list[dict], notes: list[str]) -> None:
    """사람이 눈으로 읽는 성적표를 찍는다. 숫자만이 아니라 근거 사례까지 낸다."""
    print("\n" + "=" * 78)
    print("=== 오디션 성적표 ===")
    print_table(
        ["후보", "유형", "건수", "평균CER", "중앙CER", "폭주", "보존율", "보존/세탁/기타",
         "대조군오탐율", "빈전사", "처리시간", "건당", "결정성", "상태"],
        [
            [
                r["이름"], r["유형"], str(r.get("건수", "-")),
                _pct(r.get("CER")), _pct(r.get("중앙CER")),
                (f"{r['폭주']}건" if r.get("폭주") is not None else "-"),
                _pct(r.get("보존율")),
                (f"{r['보존']}/{r['세탁']}/{r['기타']}" if r["상태"] == "완주" else "-"),
                _pct(r.get("오탐율")),
                (f"{r['빈전사']}건" if r["상태"] == "완주" else "-"),
                (f"{r['처리초']:.0f}초" if r["상태"] == "완주" else "-"),
                (f"{r['건당초']:.1f}초" if r.get("건당초") else "-"),
                ("통과" if r["상태"] == "완주" and r["결정성"]["결정적"]
                 else ("불합격" if r["상태"] == "완주" else "-")),
                r["상태"],
            ]
            for r in results
        ],
    )
    print("  CER 낮을수록 · 보존율 높을수록 · 오탐율 낮을수록 좋다.")

    # 탈락자는 왜 떨어졌는지 반드시 남긴다. 안 남기면 나중에 같은 시도를 반복한다
    dropped = [r for r in results if r["상태"] == "탈락"]
    if dropped:
        print("\n[탈락 사유]")
        for r in dropped:
            print(f"  · {r['key']} ({r['유형']}) — {r['탈락사유']}")

    # 숫자 뒤에 실제 사례를 붙인다. '보존/세탁' 판정이 말이 되는지는 사례로만 안다
    for r in results:
        if r["상태"] != "완주" or not r.get("판정사례"):
            continue
        print(f"\n[{r['이름']}] 판정 사례 (표준형 → 발화형을 이 모델이 어떻게 적었나)")
        print_table(
            ["파일", "표준형", "발화형", "판정", "전사(앞부분)"],
            [[e["id"][-18:], e["표준형"], e["발화형"] or "(빠뜨림)", e["판정"], e["전사"]]
             for e in r["판정사례"][:6]],
        )

    print("\n=== 채용 추천 ===")
    if hired:
        print_table(
            ["채용", "후보", "유형", "출처", "보존율", "오탐율", "CER", "근거"],
            [
                [f"{i}", r["이름"], r["유형"], r["출처"],
                 _pct(r["보존율"]), _pct(r["오탐율"]), _pct(r["CER"]),
                 _hire_reason(r, hired)]
                for i, r in enumerate(hired, 1)
            ],
        )
    else:
        print("  채용할 수 있는 후보가 없다.")

    if notes:
        print("\n[심사 메모]")
        for n in notes:
            print(f"  · {n}")


def _hire_reason(r: dict, hired: list[dict]) -> str:
    """왜 이 후보를 뽑았는지 한 마디로 적는다."""
    kind_mates = [x for x in hired if x["유형"] == r["유형"]]
    if r["유형"] == "직청형":
        base = "직청형 자리(성격 섞기)"
    else:
        base = "문맥형 자리"
    if len(kind_mates) > 1:
        base += f" {kind_mates.index(r) + 1}/{len(kind_mates)}"
    if r["출처"] != "8/6 목록":
        base += " · 대체 후보"
    return base


# ── 저장 ─────────────────────────────────────────────────────────────────────
def save_outputs(results: list[dict], hired: list[dict], notes: list[str],
                 manifest: Path, n_rows: int) -> None:
    """성적표와 전사본을 파일로 남긴다.

    전사본을 따로 빼 두는 이유: 세탁 탐지기(계단 ②)가 이 전사들로 다수결을 한다.
    같은 모델을 다시 돌리면 CPU 로 몇 시간이 또 걸리므로 한 번 받아쓴 것은 버리지 않는다.
    """
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # ① 성적표 — 전사 본문은 빼고(용량) 숫자와 사유만 남긴다
    slim = []
    for r in results:
        row = {k: v for k, v in r.items() if k != "전사"}
        row["전사건수"] = len(r.get("전사", {}))
        slim.append(row)

    RESULT_JSON.write_text(
        json.dumps(
            {
                "실행시각": time.strftime("%Y-%m-%d %H:%M:%S"),
                "시험지": str(manifest), "평가건수": n_rows,
                "지표계산": "eval_ab.evaluate (그대로 재사용)",
                "성적": slim,
                "채용추천": [{"이름": r["이름"], "유형": r["유형"], "출처": r["출처"],
                              "보존율": r["보존율"], "오탐율": r["오탐율"],
                              "CER": r["CER"]} for r in hired],
                "심사메모": notes,
            },
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )

    # ② 전사본 — 한 줄에 (후보, 파일, 받아쓴 글) 하나씩
    with TRANSCRIPT_JSONL.open("w", encoding="utf-8") as f:
        for r in results:
            for row_id, text in r.get("전사", {}).items():
                f.write(json.dumps({"model": r["이름"], "id": row_id, "hyp": text},
                                   ensure_ascii=False) + "\n")

    print(f"\n저장: {RESULT_JSON}")
    print(f"저장: {TRANSCRIPT_JSONL}")


# ── 실행 ─────────────────────────────────────────────────────────────────────
def main() -> int:
    enable_utf8_output()
    _pin_hf_cache()

    ap = argparse.ArgumentParser(description="세탁 탐지기 증인단 오디션")
    ap.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    ap.add_argument("--max-n", type=int, default=100, help="시험지에서 쓸 건수")
    ap.add_argument("--only", default="", help="쉼표로 후보 이름 지정 (기본: 전부)")
    ap.add_argument("--refresh", action="store_true",
                    help="이미 끝내 둔 성적을 무시하고 처음부터 다시 잰다")
    args = ap.parse_args()

    rows = read_manifest(Path(args.manifest))[: args.max_n]

    # 시험지 구성을 먼저 밝힌다. 오류 든 낭독이 없으면 보존율 자체가 안 나온다
    lar_err = sum(1 for r in rows
                  if r.get("task") == "LAR" and diff_pairs(r.get("prompt", ""), r["ref"]))
    lar_ctrl = sum(1 for r in rows
                   if r.get("task") == "LAR" and r.get("prompt")
                   and not diff_pairs(r["prompt"], r["ref"]))
    print(f"시험지 {Path(args.manifest).name} — {len(rows)}건 "
          f"(오류 든 낭독 {lar_err}건 · 대조군 {lar_ctrl}건)")
    print(f"모델 캐시: {os.environ.get('HF_HOME')}")

    # 소리 지문 → 파일 이름 대응표. _Recorder 가 이걸로 전사를 되짚는다
    id_by_hash = {}
    for r in rows:
        try:
            id_by_hash[hashlib.sha1(load_audio_bytes(r)).hexdigest()] = r["id"]
        except Exception as exc:
            print(f"  경고: 소리를 못 읽었다 {r['id']}: {exc}")

    picked = [k.strip() for k in args.only.split(",") if k.strip()] or list(CANDIDATES)
    unknown = [k for k in picked if k not in CANDIDATES]
    if unknown:
        print(f"모르는 후보: {unknown} (가능: {list(CANDIDATES)})")
        return 1

    results = []
    for k in picked:
        # 이미 끝내 둔 후보는 다시 돌리지 않는다(--refresh 를 주면 무시하고 새로 잰다).
        # CPU 로 큰 모델을 돌리면 후보 하나에 40분이 넘게 걸려서, 뒤에서 한 번
        # 넘어질 때마다 처음부터 다시 하는 것은 감당이 안 된다.
        cached = None if args.refresh else _load_cached(k, Path(args.manifest), len(rows))
        if cached is not None:
            print(f"\n── [{k}] 서랍에 든 성적을 그대로 쓴다 "
                  f"(다시 재려면 --refresh)", flush=True)
            results.append(cached)
            continue

        r = run_candidate(k, CANDIDATES[k], rows, id_by_hash)
        _save_cached(k, r, Path(args.manifest), len(rows))
        results.append(r)

    # 완주한 후보는 평균 CER 옆에 가운뎃값·폭주 건수를 채워 넣는다.
    # (서랍에서 꺼내 온 성적에도 똑같이 붙여 줘야 표가 한 벌로 읽힌다)
    for r in results:
        if r["상태"] == "완주":
            add_robust_cer(r, rows)

    hired, notes = recommend(results)
    print_report(results, hired, notes)
    save_outputs(results, hired, notes, Path(args.manifest), len(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
