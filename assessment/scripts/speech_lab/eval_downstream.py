# -*- coding: utf-8 -*-
"""⑥ 하류(下流) 평가기 — "받아쓰기가 좋아지면 채점도 좋아지는가"를 잰다.

앞의 평가기(eval_ab.py)는 받아쓴 글 자체를 봤다. 글자가 얼마나 맞는가(CER),
학습자가 틀린 자리를 살려 적는가(오류 보존율). 그런데 그것은 중간 단계의 성적표다.
우리가 파는 것은 받아쓰기가 아니라 **채점**이므로, 마지막 질문은 이것이다.

    **그 전사로 채점하면 사람 채점자와 더 잘 맞는가.**

그래서 같은 음성 114개를 네 가지 방식으로 받아쓰고, 네 전사 모두를
**우리 채점 서버가 쓰는 바로 그 파이프라인**에 그대로 태워 언어 사용 점수를 낸다.
그 점수를 AI Hub 전문 평가자가 매긴 사람 점수(0~5)와 견줘 상관을 본다.
상관이 높은 전사기가 '채점용으로 더 좋은 받아쓰기'다.

네 갈래(팔, arm):
  ref    — 사람이 귀로 듣고 적은 전사. 받아쓰기가 완벽할 때의 **상한선**이다.
           나머지 셋이 여기에 얼마나 가까운지가 곧 '채점 가능한 전사'의 척도다.
  gemini — 상용 대표 선수. 채점 서버가 지금 실제로 쓰는 경로 그대로 부른다.
  base   — 학습 전 faster-whisper small. 우리 LoRA 의 출발선.
  lora   — 우리가 학습한 v1 어댑터.

읽는 법(중요):
  이 실험이 재는 것은 '채점기가 얼마나 정확한가'가 아니다. 채점기는 네 팔에서
  똑같은 것을 쓴다. 바뀌는 것은 **입력으로 들어가는 글자뿐**이므로, 팔 사이의
  상관 차이는 전적으로 전사 품질에서 온 것이다.

쓰는 법:
    python eval_downstream.py --max-n 3            # 스모크 테스트(4팔 3건)
    python eval_downstream.py                      # 본실행(114건 × 4팔)
    python eval_downstream.py --arms ref,gemini    # 팔을 골라서
    python eval_downstream.py --self-test          # 상관 계산기 자체 점검

중간에 끊겨도 괜찮다. 항목 하나가 끝날 때마다 결과 파일에 바로 적고,
다시 실행하면 **성공한 줄만** 건너뛴다. 실패로 적힌 줄은 다시 해 보고,
성공하면 그 결과로 갈아 끼운다(나중 줄이 이긴다). 한 번의 장애 때문에
표본이 영영 줄어든 채로 남지 않게 하려는 것이다.
네 팔을 다 돈 뒤에는 남은 실패를 모아 한 번 더 채점하는 '막판 재소탕'이 돈다 —
한 건을 살리면 네 팔이 함께 살아나기 때문이다(공정 규칙 때문에 한 팔만 빠져도
그 항목은 전부 빠진다).

■ 재현성에 대해 — 미리 알고 봐야 할 한계 (8/6 실측)

우리가 고정할 수 있는 것은 다 고정했다. Whisper 두 팔(base·lora)은 같은 음성에서
늘 같은 글을 내놓는 것을 확인했고, 채점 계산도 값이 같으면 늘 같은 점수를 낸다.

**그런데 Gemini 는 temperature 0 으로 불러도 같은 답을 주지 않는다.**
같은 문장을 같은 설정으로 다섯 번 물었더니 오류를 2건 찾은 답이 세 번,
1건만 찾은 답이 두 번 나왔다. 그 차이로 언어 점수가 77.4 -> 75.1 로 움직였다.
Gemini 로 받아쓰는 팔도 마찬가지여서 같은 음성의 CER 이 15.4% ~ 19.2% 로 흔들렸다.

그래서 이 실험의 숫자는 **소수점 아래까지 재현되지 않는다.** 팔 사이의 차이를
읽을 때도 이 정도 흔들림보다 큰 차이인지를 먼저 따져야 한다. 다행히 흔들림은
네 팔에 똑같이 얹히므로(같은 채점기를 쓴다) 팔끼리의 순위 비교는 그나마 견딘다.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, nullcontext
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (  # noqa: E402
    ASSESSMENT_DIR,
    DATA_ROOT,
    cer,
    enable_utf8_output,
    load_audio_bytes,
    print_table,
    read_manifest,
    serve_wav,
)

# ── 실험 조건: 고정값 ────────────────────────────────────────────────────────
#: 표본을 뽑아 올 목록 파일. 71479 = 아시아어권 학습자 데이터.
DEFAULT_MANIFEST = Path(r"C:\해커톤\data\manifests\71479_all.jsonl")

#: v1 LoRA 학습에 쓴 파일 목록. 여기 있는 것으로 시험을 보면 '시험지 오염'이다
#: (학생이 미리 본 문제로 시험 보는 것과 같다). 그래서 표본에서 반드시 뺀다.
DEFAULT_SELECTION = Path(r"D:\해커톤데이터\v1_selection.json")

#: 우리가 학습한 어댑터가 있는 곳.
DEFAULT_ADAPTER = Path(r"D:\해커톤데이터\adapters\v1")

#: 항목별 결과를 쌓아 두는 곳. 한 줄에 (항목 하나 × 팔 하나)가 들어간다.
DEFAULT_OUT = Path(r"D:\해커톤데이터\downstream_results.jsonl")

#: 자유 발화 과제만 쓴다. 낭독(LAR)은 읽을 문장이 정해져 있어서
#: 언어 사용 능력이 아니라 '읽기 정확도'를 재게 된다.
TASK = "ATQ"

#: 사람 점수를 어느 칸에서 읽을지. AI Hub 전문 평가자가 매긴 0~5 점이다.
HUMAN_SCORE_KEY = "language_use"

#: 모든 팔이 공유하는 씨앗값. 같은 입력을 다시 돌리면 같은 결과가 나와야 한다.
SEED = 20260806

#: LLM 오류 판정이 실패했을 때 다시 시도할 횟수(첫 시도 포함).
#: 예전에 LLM 한 번 실패로 언어 점수가 10.7점 튄 사고가 있어서 그냥 넘기지 않는다.
LLM_MAX_ATTEMPTS = 6

#: 다시 시도하기 전에 쉬는 시간(초). 갈수록 오래 기다린다(지수 백오프).
#: 남의 서버가 잠깐 몸살일 때는 이렇게 물러서 주는 것이 맞다.
#: 다만 아래 '제한 시간' 설명에 적은 이유로, 이 실험에서 실제로 겪은 실패는
#: 기다린다고 풀리는 종류가 아니었다. 그래도 진짜 일시적 장애를 대비해 남겨 둔다.
LLM_RETRY_SLEEP_SEC = (5, 10, 20, 40, 80, 120)

#: ※ 임시 우회 ② ※ LLM 응답을 기다려 주는 제한 시간(밀리초).
#:
#: 왜 서버 기본값(60초)을 그대로 쓰지 않는가 — 8/6 본실행 사고 실측:
#: 본실행 ref 팔에서 504(DEADLINE_EXCEEDED)가 연발했다. 실패한 항목을 따로 재 보니
#: **실패는 늘 56~62초에 났다.** 60초 벽에 그대로 부딪힌 것이다.
#: 문법 판정 모델은 답하기 전에 '생각'을 하느라 한 번에 55~68초를 쓰는 일이 흔한데,
#: 기다려 주는 시간이 딱 60초라 아슬아슬하게 넘긴 것만 살아남고 나머지는 전부 죽었다.
#:
#: 결정적 확인: 60초에서 세 번 연속 실패하던 191자 답안을 제한 시간만 300초로 늘리자
#: 68.1초·59.8초에 **정상 판정(오류 3건)** 이 나왔다. 즉 이 실패는
#: **기다린다고 풀리는 일시적 장애가 아니라 우리가 너무 일찍 끊은 것**이었다.
#: 그래서 재시도 횟수를 6번으로 늘려도 이 실패는 6번 다 실패한다(275초를 헛되이 잔다).
#:
#: 제한 시간을 늘려도 **점수는 한 점도 바뀌지 않는다.** 응답이 오면 그 내용은 같고,
#: 안 오면 못 쓰는 것은 마찬가지다. 달라지는 것은 '오는 응답을 받느냐 마느냐'뿐이라
#: 이미 채점된 22건(전부 60초 안에 끝난 것들)과의 일관성도 깨지지 않는다.
#:
#: → 채점 서버도 같은 60초를 쓰므로 긴 답안에서 같은 일이 일어난다.
#:   src/llm/client.py 의 GeminiConfig.timeout_ms 대응이 필요하다(여기서는 못 고친다).
LLM_TIMEOUT_MS = 300_000

#: 서버가 지금 쓰고 있는 값(비교·기록용).
SERVER_DEFAULT_TIMEOUT_MS = 60_000

#: 채점 호출을 한 번에 몇 개까지 동시에 보낼지.
#:
#: 왜 병렬로 해도 되는가 — **항목끼리 서로를 보지 않기 때문이다.**
#: 채점은 답안 하나만 읽고 그 답안의 점수를 낸다. 옆 항목의 결과를 참고하지도,
#: 앞 항목이 남긴 것을 물려받지도 않는다. 그래서 몇 개를 동시에 보내든,
#: 순서를 어떻게 바꾸든 **같은 답안은 같은 점수**가 나온다.
#: (동시에 4개를 보내도 한 번에 하나씩 보낸 것과 결과가 같다는 뜻이다.
#:  Gemini 자체의 흔들림은 병렬과 무관하게 원래 있던 것이고, 맨 위에 적어 두었다.)
#:
#: 판정 한 번이 ~60초라 456회를 한 줄로 세우면 7시간이 넘는다. 대부분이
#: '남의 서버가 답할 때까지 그냥 기다리는' 시간이라 겹쳐 두면 그만큼 줄어든다.
DEFAULT_LLM_WORKERS = 4

#: 429(사용량 초과)가 이만큼 연달아 나오면 하루치가 바닥난 것으로 보고 정중히 멈춘다.
#: 중간에 워커를 절반씩 줄여 보는데도 계속 429 라면 속도 문제가 아니라 한도 문제다.
QUOTA_STOP_AFTER = 6

#: ※ 임시 우회 ※ 오류 판정 LLM이 한 번에 쓸 수 있는 글자 예산(토큰).
#:
#: 왜 서버 기본값(4096)을 그대로 쓰지 않는가 — 8/6 실측:
#: 문법 판정에 쓰는 gemini-3-flash-preview 는 답하기 전에 '생각'을 하는 모델인데,
#: 그 생각도 이 예산에서 함께 깎인다. 답안이 길면 생각에만 3930 토큰을 써 버리고
#: 정작 JSON 은 151 토큰만 쓰다가 문장 한가운데서 잘린다(finish_reason=MAX_TOKENS).
#: 잘린 JSON 은 해석에 실패하고, 그러면 오류 자질 네 개가 통째로 사라져
#: 언어 점수가 규칙 자질만으로 계산된 **반쪽 점수**가 된다.
#: 사람 전사 15건을 길이순으로 골라 재 보니 3건(20%)이 이렇게 잘렸고,
#: 잘리는 것은 전부 93자 이상의 긴 답안이었다.
#:
#: 이 실험에서 이것을 그대로 두면 긴 답안만 표본에서 빠져나가
#: '짧게 답한 사람들'만 남은 채로 상관을 재게 된다. 그래서 예산만 넉넉히 늘려 둔다.
#: 늘려도 채점 계산은 한 줄도 바뀌지 않는다(temperature 0·JSON 강제·인용 검증 그대로).
#: 서버와 똑같은 조건으로 재현하려면 --max-output-tokens 4096 으로 주면 된다.
#:
#: → 이것은 실험 쪽 우회일 뿐 근본 해결이 아니다. 채점 서버도 같은 이유로
#:   긴 답안에서 오류 자질을 통째로 잃고 있으므로 src/llm/client.py 쪽 대응이 필요하다.
LLM_MAX_OUTPUT_TOKENS = 16_384

#: 서버가 지금 쓰고 있는 값. 위 우회를 끄면 이 값이 된다(비교·기록용).
SERVER_DEFAULT_MAX_OUTPUT_TOKENS = 4_096

#: 말하기 채점에서 LLM이 반드시 채워 줘야 하는 오류 자질 네 개.
#: 이 중 하나라도 비면 언어 점수가 반쪽이 되므로 '실패'로 본다.
#: (맞춤법·띄어쓰기는 말하기에서 애초에 안 쓰는 자질이라 여기 없다)
REQUIRED_LLM_FEATURE_IDS = (
    "error_josa",
    "error_conjugation",
    "error_word_choice",
    "error_honorific",
)

ALL_ARMS = ("ref", "gemini", "base", "lora")


# ── 표본 고르기 ──────────────────────────────────────────────────────────────
def load_selected_ids(selection_path: Path) -> set[str]:
    """v1 학습에 쓴 파일 이름을 전부 모은다.

    파일 생김새는 {"LAR": [[아이디, 전사], ...], "ATQ": [[아이디, 전사], ...]} 라서
    두 목록에서 각 줄의 첫 칸(아이디)만 꺼내 한 덩어리로 만든다.
    """
    # 목록 파일이 없으면 '아무것도 안 뺀다'가 아니라 멈춰야 한다.
    # 조용히 넘어가면 학습에 쓴 파일로 시험을 보게 되고, 점수가 부풀려진다
    if not selection_path.exists():
        raise FileNotFoundError(
            f"학습 표본 목록을 찾지 못했다: {selection_path}\n"
            "이 파일이 없으면 시험지 오염을 막을 수 없어 실험을 진행하지 않는다."
        )

    data = json.loads(selection_path.read_text(encoding="utf-8"))
    return {str(entry[0]) for rows in data.values() for entry in rows}


def select_rows(
    manifest_path: Path,
    selection_path: Path,
    data_root: Path = DATA_ROOT,
) -> tuple[list[dict], dict[str, int]]:
    """실험에 쓸 표본을 조건 세 개로 걸러 낸다.

    조건은 순서대로 이렇다.
      1) 자유 발화(ATQ) 과제인가
      2) v1 학습에 쓰지 않은 파일인가 (시험지 오염 방지)
      3) 음성 파일이 실제로 컴퓨터에 있는가

    돌려주는 값은 (걸러 낸 목록, 단계별로 몇 건이 남았는지)다.
    숫자를 함께 내는 이유는 114건이 안 나왔을 때 어느 단계에서
    어긋났는지 바로 알 수 있게 하려는 것이다.
    """
    rows = read_manifest(manifest_path)
    trained_ids = load_selected_ids(selection_path)

    counts = {"전체": len(rows)}

    # 1) 자유 발화만
    rows = [r for r in rows if r.get("task") == TASK]
    counts[f"{TASK}만"] = len(rows)

    # 2) 학습에 쓴 파일 빼기
    rows = [r for r in rows if str(r.get("id")) not in trained_ids]
    counts["학습표본 제외 후"] = len(rows)

    # 3) 음성이 실제로 있는 것만. 목록에 적혀 있어도 파일이 없으면 받아쓸 수 없다
    rows = [r for r in rows if r.get("audio") and (data_root / r["audio"]).exists()]
    counts["음성 실재"] = len(rows)

    # 목록 파일의 줄 순서에 결과가 좌우되지 않도록 아이디로 줄을 세운다.
    # --max-n 3 으로 몇 번을 돌려도 늘 같은 세 건이 뽑힌다
    rows.sort(key=lambda r: str(r.get("id")))
    return rows, counts


# ── 전사 팔(arm) ─────────────────────────────────────────────────────────────
class RefTranscriber:
    """사람이 적어 준 전사를 그대로 쓰는 팔. **상한선**을 재는 자리다.

    받아쓰기 기계를 전혀 쓰지 않으므로 전사 오류가 0이다. 여기서 나온 상관이
    "받아쓰기가 완벽할 때 우리 채점기가 사람과 맞는 정도"이고,
    나머지 세 팔은 그 선에 얼마나 못 미치는지로 읽는다.
    """

    name = "ref(사람 전사)"
    needs_audio = False

    def __call__(self, row: dict) -> str:
        return (row.get("ref") or "").strip()


class GeminiArm:
    """상용 대표 선수. 채점 서버가 실제로 쓰는 경로를 그대로 부른다.

    `src/speech/gemini_stt.py` 는 **읽기만 하고 한 줄도 고치지 않는다.**
    실험 때문에 진짜 채점 코드를 손대면 여기서 잰 숫자가 서비스의 숫자가 아니게 된다.
    """

    needs_audio = True

    def __init__(self):
        if str(ASSESSMENT_DIR) not in sys.path:
            sys.path.insert(0, str(ASSESSMENT_DIR))
        from src.scoring.schema import AudioInput
        from src.speech.gemini_stt import GeminiStt

        self._AudioInput = AudioInput
        self.stt = GeminiStt()
        self.name = f"gemini({self.stt.model_name})"

    def __call__(self, row: dict) -> str:
        # 채점 코드는 음성을 '주소'로 받게 돼 있다. 파일이 내 컴퓨터에 있어도
        # 그 규칙을 우회하지 않고 내부에만 열리는 임시 주소를 만들어 넘긴다.
        # 이렇게 해야 무음 차단 같은 실제 서비스의 관문까지 똑같이 지나간다
        with serve_wav(load_audio_bytes(row)) as url:
            return self.stt.transcribe(self._AudioInput(url=url)).text


class BaseWhisperArm:
    """학습 전 기본 Whisper(small). 우리 LoRA 가 얼마나 달라졌는지 재는 출발선.

    설정 세 개를 못 박아 둔 이유(8/5 심판 고정 수술과 같은 설정):
    설정 없이 부르면 품질 검사에 걸릴 때마다 온도를 올려 가며 다시 굴려서
    같은 파일도 실행할 때마다 다르게 받아쓴다. 같은 gold 100건에서
    CER 12.2~15.4% 요동을 실측했다. 실험 결과가 주사위에 흔들리면 안 된다.
    """

    needs_audio = True

    def __init__(self, size: str = "small"):
        from faster_whisper import WhisperModel

        # int8 = 숫자를 거칠게 다뤄 CPU 에서도 돌아가게 하는 설정
        self.model = WhisperModel(size, device="cpu", compute_type="int8")
        self.name = f"base({size})"

    def __call__(self, row: dict) -> str:
        segments, _ = self.model.transcribe(
            io.BytesIO(load_audio_bytes(row)),
            language="ko",                      # 짧은 발화에서 언어를 잘못 짚는 것을 막는다
            beam_size=1,                        # 후보를 하나만 본다(주사위를 없앤다)
            temperature=0.0,                    # 무작위성 0
            condition_on_previous_text=False,   # 앞 문장에 끌려가지 않게
        )
        return " ".join(s.text.strip() for s in segments).strip()


class LoraWhisperArm:
    """우리가 학습한 LoRA 어댑터를 끼운 Whisper.

    원래 모델은 그대로 두고 어댑터(수십 MB)만 덧씌워 부른다.
    생성은 greedy(가장 그럴듯한 것 하나만 따라가기)라 같은 음성이면 늘 같은 글이 나온다.
    """

    needs_audio = True

    def __init__(self, adapter_dir: str | Path):
        import torch
        from peft import PeftConfig, PeftModel
        from transformers import WhisperForConditionalGeneration, WhisperProcessor

        adapter_dir = str(adapter_dir)
        self.torch = torch
        self.processor = WhisperProcessor.from_pretrained(
            adapter_dir, language="korean", task="transcribe"
        )

        # 어댑터 폴더에 '어떤 모델 위에 덧댄 것인지'가 적혀 있다. 그것을 읽어 온다
        base_name = PeftConfig.from_pretrained(adapter_dir).base_model_name_or_path
        base = WhisperForConditionalGeneration.from_pretrained(base_name)
        self.model = PeftModel.from_pretrained(base, adapter_dir).eval()
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model.to(self.device)
        self.name = f"lora({Path(adapter_dir).name})"

    def __call__(self, row: dict) -> str:
        import numpy as np
        import soundfile as sf

        wave, sr = sf.read(io.BytesIO(load_audio_bytes(row)), dtype="float32")
        # 스테레오(두 갈래 소리)면 평균을 내 한 갈래로 만든다
        if wave.ndim > 1:
            wave = wave.mean(axis=1)
        # Whisper 는 1초에 16000번 잰 소리만 받는다. 다르면 맞춰 준다
        if sr != 16_000:
            import librosa

            wave = librosa.resample(wave, orig_sr=sr, target_sr=16_000)

        feats = self.processor.feature_extractor(
            np.asarray(wave, dtype="float32"), sampling_rate=16_000, return_tensors="pt"
        ).input_features.to(self.device)

        with self.torch.no_grad():
            ids = self.model.generate(
                input_features=feats,
                language="korean",
                task="transcribe",
                do_sample=False,   # 주사위를 굴리지 않는다
                num_beams=1,       # 후보 하나만 따라간다(greedy)
            )
        return self.processor.batch_decode(ids, skip_special_tokens=True)[0].strip()


def build_arm(name: str, adapter_dir: Path):
    """팔 이름을 실제 전사 도구로 바꾼다."""
    if name == "ref":
        return RefTranscriber()
    if name == "gemini":
        return GeminiArm()
    if name == "base":
        return BaseWhisperArm()
    if name == "lora":
        return LoraWhisperArm(adapter_dir)
    raise ValueError(f"모르는 팔 이름: {name} (쓸 수 있는 것: {', '.join(ALL_ARMS)})")


# ── 동시 호출 조절기 ─────────────────────────────────────────────────────────
def _is_quota_error(reason: str) -> bool:
    """실패 사유가 '사용량을 다 썼다(429)'인지 가려낸다.

    사유 문구는 채점 쪽(`src/llm/client.py`)이 만들어 준 것을 그대로 읽는다.
    같은 판별을 여기서 새로 만들면 저쪽 문구가 바뀔 때 조용히 어긋난다.
    """
    return "429" in reason or "한도를 다 썼다" in reason


class CallThrottle:
    """채점 호출을 몇 개까지 동시에 보낼지 조절하고, 한도가 바닥나면 멈추게 한다.

    하는 일 두 가지.
      ① 동시에 나가는 호출 수를 제한한다. 429 를 만나면 **스스로 절반으로 줄인다**
         — 남의 서버가 "너무 빠르다"고 하면 물러서는 것이 맞다.
      ② 절반으로 줄여도 429 가 계속 이어지면 속도 문제가 아니라 하루치가 바닥난
         것이므로, 더 두드리지 않고 멈춤 표시를 세운다.

    멈출 때 결과를 버리지 않는다. 지금까지 된 것은 이미 파일에 적혀 있고,
    안 된 것은 아무것도 안 적혀 있어서 다음 실행이 그대로 이어서 한다.
    """

    def __init__(self, workers: int, stop_after: int = QUOTA_STOP_AFTER):
        # 자리 수를 바꿀 수 있어야 해서 세마포어 대신 조건 변수로 직접 센다
        self._cv = threading.Condition()
        self._limit = max(1, workers)
        self._in_use = 0
        self._consecutive_quota = 0
        self._stop_after = stop_after
        self.stop_reason = ""

    @contextmanager
    def slot(self):
        """자리 하나를 잡고 호출한다. 자리가 다 찼으면 빌 때까지 기다린다."""
        with self._cv:
            while self._in_use >= self._limit:
                self._cv.wait()
            self._in_use += 1
        try:
            yield
        finally:
            # 어떤 일이 있어도 자리는 돌려놔야 한다. 안 그러면 뒤가 영영 멈춘다
            with self._cv:
                self._in_use -= 1
                self._cv.notify()

    def note(self, quota_hit: bool) -> None:
        """호출 하나가 끝날 때마다 결과를 알려 준다(429 였는지 아닌지).

        429 가 아니었다면 연속 세기를 0으로 되돌린다.
        '연속'이 뜻을 가지려면 중간에 성공이 끼는 순간 끊겨야 하기 때문이다.
        """
        with self._cv:
            if not quota_hit:
                self._consecutive_quota = 0
                return

            self._consecutive_quota += 1
            if self._consecutive_quota >= self._stop_after:
                self.stop_reason = (
                    f"사용량 초과(429)가 {self._consecutive_quota}번 연달아 났다. "
                    "속도를 절반으로 줄여도 이어지는 것을 보아 하루치 한도를 다 쓴 것으로 본다."
                )
                self._cv.notify_all()
                return

            # 아직 한도가 남았을 수도 있으니 우선 속도를 절반으로 줄여 본다
            if self._limit > 1:
                self._limit = max(1, self._limit // 2)
                print(f"      [속도 조절] 429 를 만나 동시 호출을 {self._limit}개로 줄인다")

    @property
    def stopped(self) -> bool:
        return bool(self.stop_reason)

    @property
    def limit(self) -> int:
        with self._cv:
            return self._limit


# ── 채점: 기존 파이프라인을 그대로 태운다 ────────────────────────────────────
def _import_scoring():
    """채점 파이프라인을 불러온다. 여기서 만들지 않고 있는 것을 빌려 쓴다.

    왜 이 규칙이 중요한가:
    채점 계산을 이 스크립트 안에 베껴 두면, 실험이 재는 것과 채점 서버가
    실제로 하는 것이 서서히 갈라진다. 그러면 여기서 나온 결론이
    서비스에 대해 아무것도 말해 주지 못한다.
    """
    if str(ASSESSMENT_DIR) not in sys.path:
        sys.path.insert(0, str(ASSESSMENT_DIR))

    from src.llm.client import DEFAULT_MODEL, GeminiClient, GeminiConfig
    from src.scoring.pipeline import score_submission
    from src.scoring.schema import (
        FeatureStatus,
        ItemInfo,
        Mode,
        ScoreArea,
        ScoreOptions,
        ScoreRequest,
    )

    return {
        "GeminiClient": GeminiClient,
        "GeminiConfig": GeminiConfig,
        "DEFAULT_MODEL": DEFAULT_MODEL,
        "score_submission": score_submission,
        "FeatureStatus": FeatureStatus,
        "ItemInfo": ItemInfo,
        "Mode": Mode,
        "ScoreArea": ScoreArea,
        "ScoreOptions": ScoreOptions,
        "ScoreRequest": ScoreRequest,
    }


def _llm_features_ok(response, S) -> tuple[bool, str]:
    """이번 채점에서 LLM 오류 판정이 제대로 됐는지 확인한다.

    채점 파이프라인은 LLM이 죽어도 멈추지 않는다. 대신 오류 자질 네 개를
    '값 없음'으로 두고 나머지 가중치를 다시 나눠 **겉보기 멀쩡한 점수**를 낸다.
    실험에서는 이것을 성공으로 세면 안 된다. 오류 자질이 빠진 점수는
    다른 팔의 점수와 잣대가 달라지기 때문이다.

    돌려주는 값은 (괜찮은가, 아니라면 그 이유)다.
    """
    by_id = {f.id: f for f in response.features}
    for fid in REQUIRED_LLM_FEATURE_IDS:
        f = by_id.get(fid)
        if f is None:
            return False, f"오류 자질 '{fid}' 가 응답에 아예 없다"
        if f.status != S["FeatureStatus"].OK:
            # 파이프라인이 남긴 사유를 그대로 옮긴다(우리가 지어내지 않는다)
            return False, f"오류 자질 '{fid}' 를 못 구했다: {f.note or f.status.value}"
    return True, ""


def score_transcript(
    text: str, row: dict, arm: str, S, client, throttle: "CallThrottle | None" = None
) -> dict:
    """전사 하나를 채점 파이프라인에 태워 **언어 사용 점수와 그 근거**를 받아 온다.

    문항 맥락은 각 행의 지시문(prompt)을 그대로 쓴다. ATQ 에는 문항별 체크리스트가
    없으므로 빈 체크리스트로 부른다. 그러면 내용·과제 수행 영역은 '판정 못 함'이 되고
    언어 사용 영역만 온전히 계산된다 — 이 실험이 보려는 것이 바로 그 축이다.
    (파이프라인은 영역별 점수를 서로 독립으로 계산하므로, 내용 영역이 비어도
     언어 점수는 체크리스트가 있을 때와 똑같은 값이 나온다.)

    말하기 모드로 부르는 것도 의도한 것이다. 말하기에서는 띄어쓰기·맞춤법 자질이
    '해당 없음'으로 자동으로 빠진다. 그것들은 응시자가 아니라 받아쓰기 기계가
    정한 것이라, 넣으면 전사기의 표기 버릇을 응시자 점수로 매기게 된다.

    LLM 오류 판정이 실패하면 최대 세 번까지 다시 시도한다.
    """
    request = S["ScoreRequest"](
        submission_id=f"downstream::{row['id']}::{arm}",
        mode=S["Mode"].SPEAKING,
        answer_text=text,
        item=S["ItemInfo"](
            item_id=str(row.get("id")),
            prompt=row.get("prompt") or "",
            item_type="free_response",
            checklist=[],          # ATQ 에는 문항별 체크리스트가 없다
        ),
        options=S["ScoreOptions"](use_llm=True, weights_profile="provisional_v0"),
        # transcript 를 안 붙인다 = 전사 보정을 하지 않는다.
        # 이 실험은 '받아쓴 글 그대로'가 채점에 얼마나 먹히는지를 보는 것이라
        # 중간에 LLM이 글을 고쳐 주면 팔 사이의 차이가 지워진다
    )

    last_reason = ""
    for attempt in range(1, LLM_MAX_ATTEMPTS + 1):
        # 하루치가 바닥났다고 판단되면 더 두드리지 않는다.
        # 아무것도 적지 않고 물러나므로 다음 실행이 이 항목을 그대로 이어서 한다
        if throttle is not None and throttle.stopped:
            return {"status": "quota_stopped", "reason": throttle.stop_reason,
                    "attempts": attempt - 1}

        # 동시에 나가는 호출 수를 조절기에게 물어보고 자리를 하나 잡는다
        with (throttle.slot() if throttle is not None else nullcontext()):
            response = S["score_submission"](request, client=client)

        # 답안 유효성 가드에 걸린 경우. 다시 시도해도 결과가 같으므로 바로 끝낸다
        # (한국어가 아니거나 지시문을 그대로 옮겨 적은 답안 등)
        if not response.meta.answer_valid:
            return {
                "status": "invalid",
                "reason": f"답안 유효성 가드: {response.meta.validity_reason}",
                "attempts": attempt,
            }

        ok, reason = _llm_features_ok(response, S)
        # 429 를 몇 번 연달아 만났는지 조절기에게 알린다(속도를 줄일지 멈출지 그쪽이 정한다)
        if throttle is not None:
            throttle.note(quota_hit=not ok and _is_quota_error(reason))

        if ok:
            break
        last_reason = reason
        if attempt < LLM_MAX_ATTEMPTS:
            # 갈수록 오래 기다린다. 남의 서버가 몸살일 때 몰아치지 않기 위해서다
            wait = LLM_RETRY_SLEEP_SEC[min(attempt - 1, len(LLM_RETRY_SLEEP_SEC) - 1)]
            print(f"      LLM 판정 실패({attempt}/{LLM_MAX_ATTEMPTS}) — {reason[:60]}"
                  f" / {wait}초 쉬고 재시도")
            time.sleep(wait)
    else:
        # 세 번 다 실패. 점수를 남기지 않는다(반쪽 점수를 섞으면 비교가 망가진다)
        return {"status": "llm_failed", "reason": last_reason, "attempts": LLM_MAX_ATTEMPTS}

    language = next(
        s for s in response.subscores if s.area == S["ScoreArea"].LANGUAGE_USE
    )
    if language.score is None:
        return {
            "status": "no_language_score",
            "reason": language.note or "언어 사용 점수가 계산되지 않았다",
            "attempts": attempt,
        }

    return {
        "status": "ok",
        "attempts": attempt,
        "language_score": language.score,
        "language_status": language.status.value,
        # 상태가 partial 이면 자질 하나가 빠지고 남은 가중치를 다시 나눈 것이다.
        # 무엇이 왜 빠졌는지를 적어 두지 않으면 팔끼리 점수가 갈렸을 때
        # 전사 차이 때문인지 자질이 빠져서인지 가릴 수 없다.
        # (실제로 종결어미가 없는 전사에서는 격식체 자질이 통째로 빠진다)
        "language_note": language.note,
        # 실제로 점수 계산에 들어간 자질 목록. 팔끼리 이 목록이 다르면
        # 같은 잣대로 잰 것이 아니므로 결과를 읽을 때 반드시 확인해야 한다
        "used_feature_ids": [c.feature_id for c in language.contributions],
        # 점수만 남기지 않는다. 어떤 자질이 몇 점을 보탰는지를 함께 적어 두어야
        # 나중에 "왜 이 팔이 높게 나왔나"를 자질 단위로 따질 수 있다
        "contributions": [
            {
                "feature_id": c.feature_id,
                "raw_value": c.raw_value,
                "normalized": c.normalized,
                "weight": c.weight,
                "points": c.points,
            }
            for c in language.contributions
        ],
        # LLM이 실제로 지목한 오류 자리. 원문 인용이 검증을 통과한 것만 남아 있다
        "evidence": [
            {"quote": ev.quote, "start": ev.start, "end": ev.end, "comment": ev.comment}
            for ev in language.evidence[:6]
        ],
        "dropped_citations": response.meta.dropped_citations,
        "llm_model_errors": response.meta.llm_model_errors,
        "scoring_version": response.meta.scoring_version,
    }


# ── 상관 계산 (바깥 라이브러리 없이) ─────────────────────────────────────────
def pearson(xs: list[float], ys: list[float]) -> float:
    """두 값이 **직선으로** 같이 움직이는 정도. -1 ~ 1, 1이면 완전히 같은 방향.

    여기서는 '채점기 점수가 높은 사람은 사람 점수도 높은가'를 본다.
    """
    n = len(xs)
    # 두 점만으로는 늘 직선이 그어져 뜻이 없다. 세 건 미만이면 계산하지 않는다
    if n < 3:
        return float("nan")

    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    # 한쪽 값이 전부 똑같으면(퍼짐이 0) 같이 움직이는지 따질 수가 없다
    if sxx <= 0 or syy <= 0:
        return float("nan")
    return sxy / (sxx * syy) ** 0.5


def _ranks(values: list[float]) -> list[float]:
    """값들을 작은 것부터 순위로 바꾼다. 같은 값끼리는 순위를 나눠 갖는다(평균 순위).

    사람 점수는 0~5의 다섯 칸뿐이라 같은 점수가 잔뜩 나온다.
    같은 값에 임의로 다른 순위를 주면 상관이 우연에 흔들리므로 반드시 평균을 쓴다.
    """
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        # 값이 같은 구간을 한 덩어리로 묶는다
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        # 그 구간의 순위를 평균 내어 모두에게 똑같이 준다
        average = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = average
        i = j + 1
    return ranks


def spearman(xs: list[float], ys: list[float]) -> float:
    """**순서**가 같이 움직이는 정도. 값 자체가 아니라 등수만 본다.

    피어슨과 함께 보는 이유: 우리 점수는 0~100이고 사람 점수는 0~5라
    눈금이 다르다. 눈금을 버리고 '누가 누구보다 잘했나'만 비교하는 이 지표가
    시험 채점에서는 더 뜻이 통한다.
    """
    if len(xs) < 3:
        return float("nan")
    return pearson(_ranks(xs), _ranks(ys))


def self_test() -> int:
    """상관 계산기가 맞게 동작하는지 손으로 확인한 값과 맞춰 본다.

    채점·통계 코드는 눈으로 훑어서 맞는지 알 수 없다.
    그래서 답을 아는 예시를 넣어 값을 직접 확인한다.
    """
    checks: list[tuple[str, float, float]] = []

    # 1) 완전히 같은 방향 → 1.0
    checks.append(("완전 일치", pearson([1, 2, 3, 4], [2, 4, 6, 8]), 1.0))
    # 2) 완전히 반대 방향 → -1.0
    checks.append(("완전 반대", pearson([1, 2, 3, 4], [8, 6, 4, 2]), -1.0))
    # 3) 순서만 같고 간격은 다른 경우 → 피어슨은 1보다 작고 스피어만은 정확히 1
    curved_x, curved_y = [1, 2, 3, 4], [1, 2, 4, 100]
    checks.append(("휘어진 관계(스피어만)", spearman(curved_x, curved_y), 1.0))
    # 4) 같은 값이 섞인 경우(사람 점수 0~5처럼). 손계산 결과와 맞춘다
    #    x=[1,2,3,4], y=[3,3,3,4] -> y 순위 [2,2,2,4], x 순위 [1,2,3,4]
    #    피어슨(순위) = 0.7745966692...
    checks.append(("동점 처리", spearman([1, 2, 3, 4], [3, 3, 3, 4]), 0.7745966692414834))
    # 5) 한쪽이 전부 같은 값이면 계산 불가(nan)
    flat = pearson([1, 2, 3, 4], [5, 5, 5, 5])
    checks.append(("퍼짐 0 → 측정불가", 1.0 if flat != flat else 0.0, 1.0))

    print("=== 상관 계산기 자체 점검 ===")
    failed = 0
    rows = []
    for label, got, want in checks:
        passed = abs(got - want) < 1e-9
        failed += 0 if passed else 1
        rows.append([label, f"{got:.6f}", f"{want:.6f}", "통과" if passed else "실패"])
    print_table(["항목", "나온 값", "기대 값", "판정"], rows)

    # 동점 순위 자체도 눈으로 확인할 수 있게 보여 준다
    print(f"\n  동점 순위 예: [3,3,3,4] -> {_ranks([3, 3, 3, 4])}  (앞 셋이 평균 순위 2.0)")
    print("모두 통과" if failed == 0 else f"{failed}개 실패")
    return 0 if failed == 0 else 1


# ── 결과 파일 (중간에 끊겨도 이어서 하기) ────────────────────────────────────
def load_done(out_path: Path) -> dict[tuple[str, str], dict]:
    """이미 끝낸 (항목, 팔)을 읽어 온다. 다시 실행할 때 건너뛰기 위한 것이다.

    같은 짝이 여러 번 적혀 있으면 **나중 것이 이긴다.** 앞서 실패로 적힌 줄을
    나중에 성공으로 덮어쓸 수 있어야 재실행이 뜻을 가진다.
    """
    done: dict[tuple[str, str], dict] = {}
    if not out_path.exists():
        return done

    with out_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                # 실행 중에 끊겨 마지막 줄이 잘렸을 수 있다. 그 줄만 버리고 나머지는 쓴다
                continue
            done[(str(rec.get("id")), str(rec.get("arm")))] = rec
    return done


#: 결과 파일에 글을 쓰는 순번표. 여러 채점이 동시에 끝나도 한 번에 한 줄씩만 적는다.
#: 이것이 없으면 두 줄이 뒤엉켜 반 줄짜리 쓰레기 줄이 생기고, 그 줄은 다시 읽을 수 없다.
_WRITE_LOCK = threading.Lock()


def append_record(out_path: Path, record: dict) -> None:
    """결과 한 줄을 파일에 바로 적고 디스크까지 밀어 넣는다.

    한 건 끝날 때마다 적는 이유: 114건 × 4팔은 몇 시간이 걸리고
    Gemini 하루 사용량에 막혀 중간에 끊기는 일이 실제로 있다.
    끝까지 모아 뒀다가 한꺼번에 적으면 그때 전부 날아간다.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # 채점이 동시에 여러 개 돌아가므로, 파일에 적는 순간만은 한 줄씩 줄을 세운다
    with _WRITE_LOCK:
        with out_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())


def fix_seeds() -> None:
    """우리 컴퓨터 안에서 무작위가 끼어들 자리를 모두 같은 씨앗으로 고정한다.

    받아쓰기도 채점도 결정 설정으로 부르지만, 라이브러리 안쪽에서
    무작위를 쓰는 자리가 있을 수 있어 한 번 더 못을 박아 둔다.

    다만 이것으로 **Gemini 까지 고정되지는 않는다.** 남의 서버에서 도는 모델이라
    씨앗을 줄 방법이 없고, temperature 0 으로도 답이 흔들리는 것을 실측했다
    (맨 위 '재현성에 대해' 참고). base·lora 팔은 우리 컴퓨터에서 돌기 때문에
    여기서 고정되고, 실제로 두 번 돌려 같은 전사가 나오는 것을 확인했다.
    """
    random.seed(SEED)
    os.environ.setdefault("PYTHONHASHSEED", str(SEED))
    try:
        import numpy as np

        np.random.seed(SEED)
    except Exception:
        pass
    try:
        import torch

        torch.manual_seed(SEED)
        torch.use_deterministic_algorithms(False)  # CPU 추론에는 필요 없고 느려지기만 한다
    except Exception:
        pass


# ── 한 팔 돌리기 ─────────────────────────────────────────────────────────────
def run_arm(
    arm: str,
    rows: list[dict],
    out_path: Path,
    done: dict[tuple[str, str], dict],
    adapter_dir: Path,
    S,
    client,
    workers: int,
    throttle: CallThrottle,
) -> None:
    """팔 하나를 표본 전체에 돌려 결과를 한 줄씩 파일에 적는다.

    이미 끝난 항목은 건너뛴다. 건너뛸 게 아무것도 없으면 모델을 아예 안 불러온다
    (Whisper 를 메모리에 올리는 데만 수십 초가 걸린다).

    받아쓰기는 하나씩, 채점은 여러 개를 겹쳐서 한다. 이유는 아래 본문에 적었다.

    **병렬로 해도 결과는 달라지지 않는다** — 채점은 답안 하나만 보고 점수를 내며
    옆 항목이나 처리 순서를 전혀 참고하지 않는다(항목끼리 완전히 독립).
    """
    # **성공한 줄만 건너뛴다.** 실패로 적힌 줄은 다시 해 본다.
    # 504 처럼 그때 운이 나빴을 뿐인 실패를 영영 실패로 굳히면,
    # 한 번의 장애 때문에 표본이 계속 줄어든 채로 남는다.
    # 다시 해서 성공하면 새 줄이 뒤에 붙고, 결과를 읽을 때 나중 줄이 이긴다(load_done 참고).
    todo = [r for r in rows
            if (done.get((str(r["id"]), arm)) or {}).get("status") != "ok"]
    skipped = len(rows) - len(todo)

    print(f"\n── [{arm}] 할 일 {len(todo)}건 (이미 끝남 {skipped}건)")
    if not todo:
        return

    # 모델을 올리는 데 시간이 걸리므로 실제로 할 일이 있을 때만 만든다
    started = time.perf_counter()
    transcriber = build_arm(arm, adapter_dir)
    print(f"   모델 준비 완료: {transcriber.name} ({time.perf_counter() - started:.0f}초)")

    total = len(todo)

    def score_and_save(index: int, row: dict, record: dict) -> None:
        """채점 한 건을 끝내고 결과를 파일에 적는다. 이 함수가 여러 개 동시에 돈다."""
        row_id = str(row["id"])
        scored = score_transcript(record["transcript"], row, arm, S, client, throttle)

        # 한도가 바닥나 물러난 경우에는 **아무것도 적지 않는다.**
        # 실패로 적어 두면 그것도 결과처럼 보이는데, 사실은 시도조차 못 한 것이다.
        # 안 적어 두면 다음 실행이 이 항목을 처음부터 다시 한다
        if scored["status"] == "quota_stopped":
            print(f"   [{index:3d}/{total}] {row_id[-18:]} 한도 소진으로 보류(다음 실행에서 이어서 함)")
            return

        record.update(scored)
        append_record(out_path, record)
        done[(row_id, arm)] = record

        if scored["status"] == "ok":
            print(f"   [{index:3d}/{total}] {row_id[-18:]} "
                  f"언어 {scored['language_score']:5.1f} · 사람 {record['human_score']} "
                  f"· CER {record['cer']:.1%}")
        else:
            print(f"   [{index:3d}/{total}] {row_id[-18:]} "
                  f"제외({scored['status']}): {str(scored.get('reason'))[:60]}")

    # 받아쓰기는 **순서대로 하나씩** 한다(이 자리, 메인 스레드).
    # 우리 컴퓨터에서 도는 Whisper 를 여러 개 동시에 돌리면 메모리가 감당하지 못한다.
    # 반면 채점은 남의 서버가 답하기를 기다리는 일이라 겹쳐 두면 그만큼 빨라진다.
    # 그래서 받아쓴 것을 곧바로 채점 일꾼에게 넘기고, 메인은 다음 것을 받아쓰러 간다.
    scored_started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="ktest-score") as pool:
        futures = []
        for i, row in enumerate(todo, 1):
            # 한도가 바닥났으면 남은 것은 손도 대지 않는다(다음 실행이 이어서 한다)
            if throttle.stopped:
                print(f"   [{i:3d}/{total}] 이후 {total - i + 1}건은 손대지 않고 남긴다")
                break

            row_id = str(row["id"])
            record = {
                "id": row_id,
                "arm": arm,
                "arm_name": transcriber.name,
                "nationality": row.get("nationality"),
                "topik_level": row.get("topik_level"),
                "prompt": row.get("prompt"),
                "ref": row.get("ref"),
                "human_score": (row.get("evals") or {}).get(HUMAN_SCORE_KEY),
                # 어떤 조건에서 잰 줄인지 줄마다 남긴다. 결과 파일만 봐도 조건을 알 수 있어야
                # 나중에 다른 조건으로 돌린 줄과 섞였을 때 가려낼 수 있다
                "llm_max_output_tokens": client.config.max_output_tokens,
                "llm_timeout_ms": client.config.timeout_ms,
                "seed": SEED,
            }

            # 1) 받아쓴다. 여기가 실패하면 채점까지 갈 것이 없다
            try:
                text = transcriber(row)
            except Exception as exc:
                record.update({
                    "status": "stt_failed",
                    "reason": f"{type(exc).__name__}: {str(exc)[:200]}",
                })
                append_record(out_path, record)
                print(f"   [{i:3d}/{total}] {row_id[-18:]} 전사 실패: {str(exc)[:60]}")
                continue

            record["transcript"] = text
            # 사람 전사 대비 글자 오류율. ref 팔은 자기 자신과 비교하므로 0이 나온다
            record["cer"] = round(cer(row.get("ref") or "", text), 4)

            # 2) 채점은 일꾼에게 넘기고 곧바로 다음 것을 받아쓰러 간다
            futures.append(pool.submit(score_and_save, i, row, record))

        # 넘긴 것이 다 끝날 때까지 기다린다.
        # result() 를 부르는 이유는 일꾼 안에서 터진 예외를 여기서 드러내기 위해서다
        # (안 부르면 조용히 삼켜져서 왜 결과가 비었는지 알 수 없게 된다)
        for future in futures:
            try:
                future.result()
            except Exception as exc:
                print(f"   채점 일꾼에서 예외: {type(exc).__name__}: {str(exc)[:150]}")

    elapsed = time.perf_counter() - scored_started
    print(f"   [{arm}] {total}건 처리에 {elapsed:.0f}초 "
          f"(동시 {workers}개 · 건당 평균 {elapsed / max(1, total):.1f}초)")
    if throttle.stopped:
        print(f"\n   ※ {throttle.stop_reason}\n"
              "     여기까지 된 것은 이미 파일에 적혀 있다. **내일 다시 실행하면** 남은 것부터 이어서 한다.")


# ── 막판 재소탕 ──────────────────────────────────────────────────────────────
def final_sweep(
    rows: list[dict],
    arms: list[str],
    out_path: Path,
    done: dict[tuple[str, str], dict],
    S,
    client,
    workers: int,
    throttle: CallThrottle,
) -> int:
    """네 팔을 다 돌고 나서, 아직 실패로 남은 항목을 한 번 더 채점해 본다.

    왜 한 바퀴 더 도는가:
    실패한 항목은 한 팔에서만 빠져도 **모든 팔에서 빠진다**(공정 규칙).
    그러니 한 건을 살리면 네 줄이 함께 살아난다. 마지막에 한 번 더 두드릴 값어치가 있다.

    받아쓰기를 다시 하지 않는 것이 요령이다. 채점만 실패한 줄에는 전사가 이미
    적혀 있으므로 그 글을 그대로 다시 채점하면 된다. 덕분에 Whisper 를 메모리에
    다시 올릴 일도, Gemini 로 다시 받아쓸 일도 없다(같은 음성을 두 번 받아쓰면
    글이 달라져서 앞의 결과와 견줄 수 없게 되는 문제도 함께 피한다).

    받아쓰기 자체가 실패한 줄(stt_failed)은 전사가 없어 여기서는 손대지 못한다.
    그런 줄은 다음 실행에서 해당 팔이 다시 받아쓴다.
    """
    by_id = {str(r["id"]): r for r in rows}

    # 다시 해 볼 거리를 모은다. 전사가 남아 있는 실패만 대상이다
    targets: list[tuple[str, str, dict]] = []
    no_transcript = 0
    for row in rows:
        for arm in arms:
            rec = done.get((str(row["id"]), arm))
            if rec is None or rec.get("status") == "ok":
                continue
            # 유효성 가드에 걸린 것은 규칙으로 내린 판정이라 다시 해도 늘 같다
            if rec.get("status") == "invalid":
                continue
            if not rec.get("transcript"):
                no_transcript += 1
                continue
            targets.append((str(row["id"]), arm, rec))

    if not targets:
        print("\n=== 막판 재소탕: 다시 해 볼 항목이 없다 ===")
        return 0

    print(f"\n=== 막판 재소탕: {len(targets)}줄을 한 번 더 채점한다 ===")
    if no_transcript:
        print(f"  (전사가 없어 손대지 못하는 줄 {no_transcript}개는 다음 실행에서 다시 받아쓴다)")

    recovered = 0

    def resweep(index: int, row_id: str, arm: str, old: dict) -> bool:
        row = by_id[row_id]
        scored = score_transcript(old["transcript"], row, arm, S, client, throttle)

        # 한도가 바닥나 물러난 것은 결과가 아니다. 적지 않고 다음 실행에 넘긴다
        if scored["status"] == "quota_stopped":
            print(f"   [{index:3d}/{len(targets)}] {arm:6s} {row_id[-18:]} 한도 소진으로 보류")
            return False

        # 앞서 적힌 줄을 그대로 두고 새 줄을 뒤에 붙인다.
        # 결과를 읽을 때 나중 줄이 이기므로 이것으로 교체가 된다.
        # 앞 줄을 지우지 않는 이유는, 언제 무엇이 실패했는지가 기록으로 남아야
        # 나중에 "이 항목은 원래 몇 번 만에 됐나"를 따질 수 있기 때문이다
        record = dict(old)
        # 지난 실패의 흔적을 지우고 이번 결과로 덮어쓴다
        for key in ("reason", "language_score", "language_status", "language_note",
                    "used_feature_ids", "contributions", "evidence"):
            record.pop(key, None)
        record.update(scored)
        record["sweep"] = True
        append_record(out_path, record)
        done[(row_id, arm)] = record

        if scored["status"] == "ok":
            print(f"   [{index:3d}/{len(targets)}] {arm:6s} {row_id[-18:]} 살림 "
                  f"— 언어 {scored['language_score']:.1f}")
            return True

        print(f"   [{index:3d}/{len(targets)}] {arm:6s} {row_id[-18:]} 여전히 실패"
              f"({scored['status']})")
        return False

    # 재소탕도 겹쳐서 한다. 여기 오는 것은 전부 채점만 다시 하는 일이라
    # 받아쓰기 모델을 건드리지 않고, 그래서 그냥 동시에 보내면 된다
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="ktest-sweep") as pool:
        results = list(pool.map(
            lambda t: resweep(t[0], t[1], t[2], t[3]),
            [(i, rid, arm, rec) for i, (rid, arm, rec) in enumerate(targets, 1)],
        ))
    recovered = sum(1 for r in results if r)

    print(f"  재소탕 결과: {len(targets)}줄 중 {recovered}줄 살림")
    return recovered


# ── 요약 ─────────────────────────────────────────────────────────────────────
def summarize(rows: list[dict], arms: list[str], done: dict[tuple[str, str], dict]) -> None:
    """팔별 상관표를 만들어 화면에 그린다.

    **공정 규칙**: 한 팔에서라도 점수를 못 낸 항목은 모든 팔에서 뺀다.
    팔마다 다른 항목 묶음으로 상관을 재면, 그 차이가 전사 품질 때문인지
    묶음이 달라서인지 알 수 없게 된다. 실제로 LLM 한 번 실패로 언어 점수가
    10.7점 튄 사고가 있었고, 그런 항목이 한 팔에만 빠지면 비교가 기운다.
    """
    # 1) 어느 항목이 모든 팔에서 성공했는지 고른다
    usable_ids: list[str] = []
    dropped: dict[str, list[str]] = {}   # 뺀 이유 -> 항목 목록
    for row in rows:
        rid = str(row["id"])
        reasons = []
        for arm in arms:
            rec = done.get((rid, arm))
            if rec is None:
                reasons.append(f"{arm}:미실행")
            elif rec.get("status") != "ok":
                reasons.append(f"{arm}:{rec.get('status')}")
        # 사람 점수가 없으면 견줄 대상이 없다
        if (row.get("evals") or {}).get(HUMAN_SCORE_KEY) is None:
            reasons.append("사람점수없음")

        if reasons:
            dropped.setdefault(" / ".join(reasons), []).append(rid)
        else:
            usable_ids.append(rid)

    print(f"\n=== 공통 표본: {len(usable_ids)}건 "
          f"(전체 {len(rows)}건 중 {len(rows) - len(usable_ids)}건 제외) ===")
    if dropped:
        print("  제외 내역 (한 팔에서라도 점수를 못 낸 항목은 모든 팔에서 뺀다)")
        for reason, ids in sorted(dropped.items(), key=lambda kv: -len(kv[1])):
            sample = ", ".join(i[-18:] for i in ids[:3])
            more = f" 외 {len(ids) - 3}건" if len(ids) > 3 else ""
            print(f"    {len(ids):3d}건  {reason}  ({sample}{more})")

    if len(usable_ids) < 3:
        print("\n  공통 표본이 3건 미만이라 상관을 계산하지 않는다"
              "(두 점은 언제나 직선이 되어 숫자에 뜻이 없다).")

    # 2) 팔별로 점수를 모아 상관을 낸다
    table_rows = []
    for arm in arms:
        ours, humans, cers = [], [], []
        for rid in usable_ids:
            rec = done[(rid, arm)]
            ours.append(float(rec["language_score"]))
            humans.append(float(rec["human_score"]))
            cers.append(float(rec.get("cer", 0.0)))

        def fmt(v: float) -> str:
            return "측정불가" if v != v else f"{v:+.3f}"   # v != v 는 '숫자가 아님'

        mean_ours = sum(ours) / len(ours) if ours else float("nan")
        mean_cer = sum(cers) / len(cers) if cers else float("nan")
        arm_name = done[(usable_ids[0], arm)]["arm_name"] if usable_ids else arm

        table_rows.append([
            arm_name,
            f"{len(ours)}",
            fmt(pearson(ours, humans)),
            fmt(spearman(ours, humans)),
            f"{mean_ours:.1f}" if ours else "-",
            f"{mean_cer:.1%}" if cers else "-",
        ])

    print("\n=== 하류 평가표 — 전사별로 채점했을 때 사람 점수와 얼마나 맞는가 ===")
    print_table(
        ["전사기", "건수", "피어슨", "스피어만", "평균 언어점수", "평균 CER"],
        table_rows,
    )
    print("\n  피어슨·스피어만은 1에 가까울수록 사람 채점과 잘 맞는다. CER 은 낮을수록 좋다.")

    # 팔마다 실제로 쓴 자질이 달랐던 항목을 센다.
    # 예를 들어 종결어미가 통째로 사라진 전사에서는 격식체 자질이 빠지고
    # 남은 자질끼리 가중치를 다시 나눈다. 그러면 그 팔만 다른 잣대로 잰 셈이 된다.
    # 이것은 버그가 아니라 '나쁜 전사가 채점에 미치는 영향' 자체지만,
    # 숫자를 읽을 때 반드시 알고 봐야 하는 사실이라 따로 센다
    mismatched = sum(
        1 for rid in usable_ids
        if len({tuple(done[(rid, arm)].get("used_feature_ids") or []) for arm in arms}) > 1
    )
    if mismatched:
        print(f"  참고: {len(usable_ids)}건 중 {mismatched}건은 팔마다 쓴 자질 묶음이 달랐다"
              " — 전사가 종결어미를 지워 버리면 격식체 자질이 통째로 빠지기 때문이다.\n"
              "        (자질이 빠진 팔은 남은 자질끼리 가중치를 다시 나눈다."
              " 자세한 사유는 결과 파일의 language_note 에 있다)")
    print("  ref(사람 전사) 줄이 상한선이다 — 받아쓰기가 완벽할 때 우리 채점기가 낼 수 있는 최대치.")
    print("  ※ 언어 사용 점수는 임시 가중치로 계산된 값이라 절대 등급으로 쓰면 안 된다.")
    print("  ※ Gemini 는 temperature 0 으로도 답이 흔들린다(실측: 같은 문장 5회에 답 2가지,\n"
          "     언어 점수 77.4~75.1). 이 표의 숫자도 다시 돌리면 소수점 아래가 달라진다.\n"
          "     팔 사이의 차이를 읽을 때 이 흔들림보다 큰 차이인지 먼저 따져야 한다.")

    # 3) 근거를 남긴다. 숫자만 있으면 나중에 따질 수가 없다
    if usable_ids:
        print("\n[근거 예시] 첫 항목을 팔별로 어떻게 받아쓰고 어떻게 채점했는가")
        rid = usable_ids[0]
        sample_rows = []
        for arm in arms:
            rec = done[(rid, arm)]
            top = max(rec.get("contributions") or [],
                      key=lambda c: c["points"], default=None)
            sample_rows.append([
                arm,
                (rec.get("transcript") or "")[:34],
                f"{rec['language_score']:.1f}",
                f"{rec['cer']:.1%}",
                f"{top['feature_id']} {top['points']:.1f}점" if top else "-",
            ])
        print(f"  파일: {rid}  ·  사람 점수: {done[(rid, arms[0])]['human_score']}")
        print(f"  사람 전사: {done[(rid, arms[0])].get('ref', '')[:60]}")
        print_table(["팔", "전사(앞부분)", "언어점수", "CER", "가장 크게 보탠 자질"], sample_rows)


# ── 진입점 ───────────────────────────────────────────────────────────────────
def main() -> int:
    enable_utf8_output()
    ap = argparse.ArgumentParser(
        description="전사 품질이 채점 정확도로 이어지는가를 재는 하류 평가기",
    )
    ap.add_argument("--max-n", type=int, default=0,
                    help="쓸 표본 수. 0(기본)이면 조건에 맞는 전부(114건)")
    ap.add_argument("--arms", default=",".join(ALL_ARMS),
                    help=f"쉼표로 구분한 팔 이름. 기본 {','.join(ALL_ARMS)}")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT,
                    help=f"항목별 결과를 쌓을 파일. 기본 {DEFAULT_OUT}")
    ap.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    ap.add_argument("--selection", type=Path, default=DEFAULT_SELECTION,
                    help="v1 학습에 쓴 파일 목록(시험지 오염을 막기 위해 빼는 데 쓴다)")
    ap.add_argument("--adapter", type=Path, default=DEFAULT_ADAPTER)
    ap.add_argument("--expect-n", type=int, default=114,
                    help="조건에 맞는 표본 수가 이 값과 다르면 멈춘다. 0이면 확인하지 않는다")
    ap.add_argument("--max-output-tokens", type=int, default=LLM_MAX_OUTPUT_TOKENS,
                    help=(
                        f"오류 판정 LLM의 글자 예산. 기본 {LLM_MAX_OUTPUT_TOKENS}(임시 우회). "
                        f"서버 현재 설정 그대로 재현하려면 {SERVER_DEFAULT_MAX_OUTPUT_TOKENS}"
                    ))
    ap.add_argument("--llm-workers", type=int, default=DEFAULT_LLM_WORKERS,
                    help=(
                        f"채점 호출을 한 번에 몇 개까지 동시에 보낼지. 기본 {DEFAULT_LLM_WORKERS}. "
                        "1이면 예전처럼 하나씩 처리한다. 받아쓰기는 이 값과 무관하게 "
                        "언제나 하나씩 한다(우리 컴퓨터 메모리 때문)"
                    ))
    ap.add_argument("--llm-timeout-ms", type=int, default=LLM_TIMEOUT_MS,
                    help=(
                        f"LLM 응답을 기다려 주는 시간. 기본 {LLM_TIMEOUT_MS}(임시 우회). "
                        f"서버 현재 설정 그대로 재현하려면 {SERVER_DEFAULT_TIMEOUT_MS}. "
                        "점수 계산에는 영향이 없고 '오는 응답을 받느냐'만 달라진다"
                    ))
    ap.add_argument("--self-test", action="store_true",
                    help="상관 계산기만 점검하고 끝낸다(모델도 LLM도 부르지 않는다)")
    args = ap.parse_args()

    if args.self_test:
        return self_test()

    fix_seeds()

    arms = [a.strip() for a in args.arms.split(",") if a.strip()]
    unknown = [a for a in arms if a not in ALL_ARMS]
    if unknown:
        print(f"모르는 팔 이름: {', '.join(unknown)} (쓸 수 있는 것: {', '.join(ALL_ARMS)})")
        return 1

    # ── 표본 고르기 ──────────────────────────────────────────────────────────
    rows, counts = select_rows(args.manifest, args.selection)
    print("=== 표본 고르기 ===")
    print_table(["단계", "남은 건수"], [[k, str(v)] for k, v in counts.items()])

    # 검증된 조건이 그대로인지 확인한다. 숫자가 달라졌다면 데이터나 조건이
    # 바뀐 것이므로, 모르는 채로 몇 시간짜리 실행을 시작하지 않는다
    if args.expect_n and len(rows) != args.expect_n:
        print(f"\n[중단] 조건에 맞는 표본이 {len(rows)}건이다. {args.expect_n}건이 나와야 한다.\n"
              "  데이터나 조건이 바뀐 것이므로 확인이 필요하다. "
              "의도한 변경이면 --expect-n 을 새 값으로 주거나 0으로 끄면 된다.")
        return 1

    if args.max_n:
        rows = rows[: args.max_n]
    print(f"\n이번 실행에 쓸 표본: {len(rows)}건 · 팔: {', '.join(arms)}"
          f" · 채점 동시 {args.llm_workers}개(받아쓰기는 하나씩)")
    print(f"결과 파일: {args.out}")

    # ── 채점 준비 ────────────────────────────────────────────────────────────
    S = _import_scoring()
    # 채점 파이프라인이 쓸 LLM 클라이언트를 만든다.
    # 글자 예산만 우리가 정하고 나머지(모델·temperature 0·JSON 강제)는 서버 설정 그대로다.
    # 이 값은 오류 판정용 상위 모델 클라이언트에도 그대로 물려 내려간다
    client = S["GeminiClient"](
        config=S["GeminiConfig"](
            model=S["DEFAULT_MODEL"],
            max_output_tokens=args.max_output_tokens,
            timeout_ms=args.llm_timeout_ms,
        )
    )
    if not client.available:
        print("\n[중단] GEMINI_API_KEY 가 없어 LLM 오류 판정을 할 수 없다.\n"
              "  키 없이 돌리면 오류 자질 네 개가 통째로 빠진 반쪽 점수만 나오고,\n"
              "  그 숫자로는 전사기를 비교할 수 없다. assessment/.env 를 확인하라.")
        return 1
    print(f"채점 LLM: {client.model_name} (오류 판정은 상위 모델로 따로 나간다)")

    # 서버 기본값과 다른 조건으로 돌린다면 그 사실을 조용히 넘기지 않는다.
    # 결과를 나중에 읽는 사람이 "어떤 조건에서 잰 숫자인가"를 알아야 하기 때문이다
    if args.max_output_tokens != SERVER_DEFAULT_MAX_OUTPUT_TOKENS:
        print(
            f"\n  ※ 임시 우회 ※ LLM 글자 예산을 {SERVER_DEFAULT_MAX_OUTPUT_TOKENS}"
            f" -> {args.max_output_tokens} 로 늘려서 돌린다.\n"
            "    서버 기본값이면 긴 답안에서 응답이 잘려(생각 토큰이 예산을 다 씀)\n"
            "    오류 자질 네 개가 통째로 빠진다. 실측 15건 중 3건이 그랬고 전부 93자 이상이었다.\n"
            "    그대로 두면 긴 답안만 표본에서 빠져 비교가 기운다.\n"
            "    채점 계산 자체는 하나도 바뀌지 않는다(temperature 0·JSON 강제·인용 검증 그대로).\n"
            f"    서버와 똑같이 재현하려면 --max-output-tokens {SERVER_DEFAULT_MAX_OUTPUT_TOKENS}."
        )
    if args.llm_timeout_ms != SERVER_DEFAULT_TIMEOUT_MS:
        print(
            f"\n  ※ 임시 우회 ② ※ LLM 대기 시간을 {SERVER_DEFAULT_TIMEOUT_MS // 1000}초"
            f" -> {args.llm_timeout_ms // 1000}초로 늘려서 돌린다.\n"
            "    8/6 본실행의 504 연발은 남의 서버 장애가 아니라 우리가 60초에 끊은 것이었다\n"
            "    (실패가 늘 56~62초에 났고, 300초로 늘리자 같은 항목이 68.1초에 정상 판정).\n"
            "    점수는 한 점도 안 바뀐다 — 오는 응답을 받느냐 마느냐만 달라진다.\n"
            f"    서버와 똑같이 재현하려면 --llm-timeout-ms {SERVER_DEFAULT_TIMEOUT_MS}."
        )

    # ── 팔별로 돌린다 ────────────────────────────────────────────────────────
    done = load_done(args.out)
    if done:
        print(f"이미 저장된 결과 {len(done)}줄을 읽었다(끝난 것은 건너뛴다).")

    # 동시 호출 조절기는 팔이 바뀌어도 하나를 계속 쓴다.
    # 한도가 바닥난 것은 팔의 사정이 아니라 계정의 사정이라, ref 에서 바닥났으면
    # 다음 팔로 넘어가 봐야 똑같이 막힌다
    throttle = CallThrottle(args.llm_workers)

    for arm in arms:
        if throttle.stopped:
            print(f"\n── [{arm}] 한도 소진으로 시작하지 않는다(다음 실행에서 이어서 함)")
            continue
        try:
            run_arm(arm, rows, args.out, done, args.adapter, S, client,
                    args.llm_workers, throttle)
        except Exception as exc:
            # 한 팔이 통째로 실패해도(모델 준비 실패 등) 나머지 팔은 살린다
            print(f"   [{arm}] 팔 실행 실패: {type(exc).__name__}: {str(exc)[:200]}")

    # ── 막판 재소탕 ──────────────────────────────────────────────────────────
    # 한 건을 살리면 네 팔이 함께 살아나므로 마지막에 한 번 더 두드린다
    try:
        final_sweep(rows, arms, args.out, done, S, client, args.llm_workers, throttle)
    except Exception as exc:
        print(f"   재소탕 실패: {type(exc).__name__}: {str(exc)[:200]}")

    # 한도가 바닥나 멈춘 경우에는 요약표보다 이 안내가 먼저 보여야 한다
    if throttle.stopped:
        print(f"\n{'=' * 60}\n"
              f"  ※ 오늘은 여기까지다 — {throttle.stop_reason}\n"
              "  된 것은 전부 저장돼 있다. **내일 같은 명령을 그대로 다시 실행하면**\n"
              "  성공한 것은 건너뛰고 남은 것부터 이어서 한다.\n"
              f"{'=' * 60}")

    # ── 요약 ─────────────────────────────────────────────────────────────────
    summarize(rows, arms, load_done(args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
