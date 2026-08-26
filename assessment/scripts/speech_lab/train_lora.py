# -*- coding: utf-8 -*-
"""④ LoRA 학습 스크립트 — Whisper 에게 "오류를 고치지 말고 들린 대로 적어라"를 가르친다.

**이 컴퓨터에서는 학습을 돌리지 않는다.** 그래픽카드가 필요하고, 여기서는
`--dry-run` 으로 '데이터가 잘 읽히는가 / 모델이 잘 조립되는가 / 한 걸음 계산이
되는가'만 확인한다. 실제 학습은 Colab 이나 RunPod 에 이 파일을 올려서 돌린다.

LoRA 가 무엇인가 (한 문단):
Whisper 는 수억 개의 숫자로 이뤄져 있고 그걸 다 새로 가르치려면 큰 GPU 와 긴 시간이
든다. LoRA 는 원래 숫자는 얼려 두고 **옆에 아주 작은 판을 덧대어 그것만 배우게**
하는 방법이다. 배운 결과물(어댑터)이 수십 MB 밖에 안 돼서 국적별로 여러 장을
만들어 갈아 끼울 수 있다 — 우리가 노리는 'L1(모어)별 어댑터'가 이래서 가능하다.

쓰는 법:
    (여기서 확인만)  python train_lora.py --data ../../../data/labels/flagship.jsonl --dry-run
    (GPU 서버에서)   pip install -r requirements-lab.txt
                     python train_lora.py --data labels/flagship.jsonl --out adapters/flagship-v1
    (2단 마무리)     python train_lora.py --data extra/team2000_train_stage2.jsonl --init-adapter adapters/v2 --lr 3e-6 --epochs 1 --out adapters/v3-stage2

'2단 마무리'가 무엇인가:
이미 대량 데이터로 배운 판(v2 어댑터)을 그대로 얹고, 그 위에 사람이 직접 검수한
소량의 고품질 데이터를 **아주 낮은 학습률로** 조금만 더 배우게 하는 것이다.
많이 배운 것을 지우지 않으면서 마지막 다듬기만 하려는 것이라, `--lr` 을 1단보다
훨씬 작게(예: 1e-5 → 3e-6) 주고 `--epochs` 도 1 정도로 짧게 준다.

────────────────────────────────────────────────────────────────────────────
GPU 서버에서 돌릴 때 (RunPod 기준) — 학습이 끝나면 반드시 서버를 꺼야 한다
────────────────────────────────────────────────────────────────────────────
빌린 GPU 는 켜져 있는 시간만큼 돈이 나간다. 학습이 새벽에 끝나고 아침까지
켜져 있으면 학습비보다 대기비가 더 나온다. 그래서 아래처럼 이어 붙여 실행한다.

    python train_lora.py --data labels/flagship.jsonl --out adapters/v1 && runpodctl stop pod $RUNPOD_POD_ID

  - `&&` 는 '앞이 성공하면 뒤를 실행하라'는 뜻이다. 학습이 실패하면 서버가 살아
    있어서 로그를 볼 수 있다(실패했는데 꺼져 버리면 원인을 못 본다).
  - 어댑터는 수십 MB 이므로 끄기 전에 먼저 내려받거나 HuggingFace 에 올린다.
    **서버를 끄면 디스크가 사라진다.**
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import enable_utf8_output  # noqa: E402

#: 같은 조건으로 다시 돌리면 같은 결과가 나오게 고정한다.
#: 실험을 여러 번 비교할 것이라 이 값이 흔들리면 '무엇 때문에 좋아졌는지'를 알 수 없다.
SEED = 42

#: Whisper 가 알아듣는 소리의 촘촘함(1초를 16,000 조각으로 나눈다). 바꿀 수 없다.
SAMPLE_RATE = 16_000

#: LoRA 를 덧댈 자리. 'q_proj·v_proj' 는 모델이 '어디에 주목할지' 정하는 부분으로,
#: 여기만 손대도 말투·표기 습관이 바뀐다는 것이 여러 연구에서 확인된 관행이다.
LORA_TARGETS = ["q_proj", "v_proj"]

#: 정답 전사(사람이 정한 '이렇게 들린다'는 문장)가 들어 있을 수 있는 칸 이름들.
#: make_labels.py 가 만든 파일은 `text`, 감사 회수본에서 만든 학습용 목록은 `ref` 를 쓴다.
#: 앞에 있는 이름부터 찾아서 먼저 걸리는 것을 정답으로 삼는다.
TEXT_KEYS = ("text", "ref")


def load_rows(path: Path, max_n: int = 0) -> list[dict]:
    """라벨 파일을 읽고, 학습에 바로 쓸 수 있는 줄만 (소리, 정답) 짝으로 남긴다.

    학습 도중에 파일이 없다고 멈추면 GPU 시간을 그냥 버리게 된다.
    그래서 시작 전에 전부 확인하고, 없는 줄은 이유와 함께 세어서 보고한다.

    파일마다 칸 이름과 개수가 다르다(`text` 냐 `ref` 냐, `grade`·`auditor` 같은
    학습에 안 쓰는 칸이 붙어 있느냐). 그런 차이는 **여기서 전부 흡수해서**
    audio·text 두 칸만 남긴 채 내보낸다. 뒤쪽 코드가 칸 이름을 신경 쓰지 않아도
    되고, 줄마다 칸 구성이 달라서 생기는 사고도 여기서 막힌다.
    """
    rows, missing, no_text = [], 0, 0
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)

            # 소리 파일이 실제로 있어야 학습에 쓸 수 있다
            if not Path(r["audio"]).exists():
                missing += 1
                continue

            # 정답 전사를 찾는다. 이름이 무엇이든(text/ref) 먼저 걸리는 것을 쓴다
            text = next((str(r[k]) for k in TEXT_KEYS if r.get(k)), "").strip()
            if not text:
                no_text += 1
                continue

            # 여분 칸(id·grade·auditor 등)은 버리고 학습에 쓰는 두 칸만 남긴다
            rows.append({"audio": r["audio"], "text": text})
            if max_n and len(rows) >= max_n:
                break

    if missing:
        print(f"  주의: 소리 파일이 없어 뺀 줄 {missing}개")
    if no_text:
        print(f"  주의: 정답 전사({'/'.join(TEXT_KEYS)})가 비어서 뺀 줄 {no_text}개")
    return rows


def read_audio(path: str):
    """wav 를 모델이 먹는 형태(16kHz 한 줄짜리 숫자 배열)로 읽는다."""
    import numpy as np
    import soundfile as sf

    wave, sr = sf.read(path, dtype="float32")

    # 두 귀로 녹음된 파일이면 한 줄로 합친다(Whisper 는 한 줄만 받는다)
    if wave.ndim > 1:
        wave = wave.mean(axis=1)

    # 촘촘함이 다르면 16kHz 로 맞춘다. AI Hub 파일은 대부분 이미 16kHz 라 건너뛴다
    if sr != SAMPLE_RATE:
        import librosa

        wave = librosa.resample(wave, orig_sr=sr, target_sr=SAMPLE_RATE)
    return np.asarray(wave, dtype="float32")


@dataclass
class WhisperCollator:
    """여러 개의 (소리, 문장) 짝을 한 묶음(batch)으로 포갠다.

    소리와 글은 길이가 제각각인데 계산은 네모난 표로만 할 수 있다.
    그래서 짧은 것 뒤에 빈칸을 채워 길이를 맞추는데, **그 빈칸을 정답으로 세면
    안 되므로** -100 이라는 표시를 넣어 '여기는 채점하지 말라'고 알린다.
    """

    processor: object

    def __call__(self, features: list[dict]) -> dict:
        import torch

        # ① 소리 쪽: Whisper 는 모든 소리를 30초 그림으로 만들어 쓰므로 길이가 이미 같다
        batch = self.processor.feature_extractor.pad(
            [{"input_features": f["input_features"]} for f in features],
            return_tensors="pt",
        )

        # ② 글 쪽: 가장 긴 문장에 맞춰 빈칸을 채운다
        labels_batch = self.processor.tokenizer.pad(
            [{"input_ids": f["labels"]} for f in features], return_tensors="pt"
        )
        labels = labels_batch["input_ids"].masked_fill(
            labels_batch["attention_mask"].ne(1), -100  # 빈칸은 채점 제외
        )

        # ③ 맨 앞의 시작 표시는 모델이 알아서 붙이므로 정답에서는 떼어 낸다.
        #    안 떼면 같은 표시가 두 번 들어가 학습이 어긋난다
        if (labels[:, 0] == self.processor.tokenizer.bos_token_id).all().cpu().item():
            labels = labels[:, 1:]

        batch["labels"] = labels
        return batch


def build_dataset(rows: list[dict], processor):
    """라벨 목록을 모델이 바로 먹을 수 있는 형태로 바꿔 둔다.

    한 줄이 두 가지로 바뀐다.
      input_features — 소리를 '그림'(멜 스펙트로그램)으로 바꾼 것
      labels         — 정답 문장을 숫자 토막으로 바꾼 것
    """
    from datasets import Dataset

    ds = Dataset.from_list(rows)

    def prepare(example):
        audio = read_audio(example["audio"])
        example["input_features"] = processor.feature_extractor(
            audio, sampling_rate=SAMPLE_RATE
        ).input_features[0]
        example["labels"] = processor.tokenizer(example["text"]).input_ids
        return example

    # 원래 칸(국적·과제 등)은 학습에 쓰지 않으므로 여기서 떼어 낸다
    return ds.map(prepare, remove_columns=ds.column_names)


def attach_existing_adapter(model, adapter_dir: str, lora_r: int):
    """이미 배운 어댑터를 얹고, **그 판을 계속 학습할 수 있게** 열어 둔다.

    `is_trainable=True` 가 핵심이다. 이 값을 빼면 어댑터가 '읽기 전용'으로 얹혀서,
    학습이 도는 것처럼 보이는데 실제로는 아무것도 배우지 않는다(손실값만 찍히고
    어댑터는 그대로다). 2단 마무리 학습에서 제일 조용하게 시간을 버리는 사고라
    여기서 못 박아 둔다.
    """
    from peft import PeftModel

    adapter_path = Path(adapter_dir)
    if not adapter_path.exists():
        # 없는 폴더를 주면 새 판으로 조용히 넘어가지 않고 여기서 멈춘다.
        # (v2 위에 얹은 줄 알았는데 맨바닥부터 배운 결과가 나오는 것을 막으려는 것)
        raise SystemExit(f"이어서 배울 어댑터 폴더를 찾지 못했다: {adapter_path}")

    # 어댑터가 어떤 설정으로 만들어졌는지 먼저 확인한다. 판 크기(r)와 덧댄 자리
    # (target_modules)는 어댑터 파일에 이미 박혀 있어서 지금 와서 바꿀 수 없다
    config_file = adapter_path / "adapter_config.json"
    saved = json.loads(config_file.read_text(encoding="utf-8")) if config_file.exists() else {}
    saved_r, saved_targets = saved.get("r"), saved.get("target_modules")

    # 명령줄 값과 다르면 따르는 쪽은 언제나 어댑터다. 다만 사용자가 --lora-r 을
    # 잘못 준 채로 '내 설정대로 돌았겠지' 하고 넘어가지 않도록 한 줄 알린다
    if saved_r is not None and saved_r != lora_r:
        print(f"  경고: 어댑터의 판 크기는 r={saved_r} 인데 --lora-r {lora_r} 로 주었다 "
              f"→ 어댑터 설정(r={saved_r})을 따른다")
    if saved_targets and sorted(saved_targets) != sorted(LORA_TARGETS):
        print(f"  경고: 어댑터가 덧댄 자리는 {sorted(saved_targets)} 인데 이 스크립트 "
              f"기본값은 {sorted(LORA_TARGETS)} 이다 → 어댑터 설정을 따른다")

    print(f"  이어서 배울 어댑터 얹는 중: {adapter_path}")
    return PeftModel.from_pretrained(model, str(adapter_path), is_trainable=True)


def build_model(model_name: str, lora_r: int, init_adapter: str | None = None):
    """Whisper 를 불러와 LoRA 판을 덧댄다.

    `init_adapter` 를 주면 **새 판을 만들지 않고 이미 배운 판을 얹어** 그 위에
    이어서 배운다(2단 마무리 학습). 안 주면 지금까지처럼 빈 판을 새로 덧댄다.
    """
    from peft import LoraConfig, get_peft_model
    from transformers import WhisperForConditionalGeneration, WhisperProcessor

    print(f"  모델 불러오는 중: {model_name}")
    processor = WhisperProcessor.from_pretrained(
        model_name, language="korean", task="transcribe"
    )
    model = WhisperForConditionalGeneration.from_pretrained(model_name)

    # 한국어를 받아쓰라고 못 박아 둔다. 안 그러면 모델이 언어를 스스로 짐작하다가
    # 영어로 번역해 버리는 일이 생긴다
    model.generation_config.language = "korean"
    model.generation_config.task = "transcribe"
    model.generation_config.forced_decoder_ids = None

    if init_adapter:
        # 이미 배운 판을 얹어 그 위에 이어서 배운다
        model = attach_existing_adapter(model, init_adapter, lora_r)
    else:
        # 빈 판을 새로 덧댄다 (지금까지의 기본 동작)
        config = LoraConfig(
            r=lora_r,                 # 덧대는 판의 크기. 클수록 많이 배우지만 무거워진다
            lora_alpha=lora_r * 2,    # 배운 것을 얼마나 세게 반영할지 (관행상 r 의 2배)
            target_modules=LORA_TARGETS,
            lora_dropout=0.05,        # 일부러 조금 흘려 외워 버리는 것을 막는다
            bias="none",
        )
        model = get_peft_model(model, config)

    # 실제로 몇 개만 배우는지 눈으로 확인하는 자리 (보통 전체의 1% 아래로 나온다)
    model.print_trainable_parameters()
    return model, processor


def dry_run(args) -> int:
    """GPU 없이 **한 걸음만** 굴려 보고 파이프라인이 성립하는지 확인한다.

    확인하는 것 넷: 데이터가 읽히는가 / 모델이 조립되는가 / 묶음이 만들어지는가 /
    계산이 끝까지 가서 손실값(loss)이 나오는가. 손실값이 숫자로 나오면
    GPU 에서도 같은 코드가 돈다고 볼 수 있다.
    """
    import torch

    print("=== 헛돌리기(dry-run): 실제 학습은 하지 않는다 ===")

    rows = load_rows(Path(args.data), max_n=args.dry_n)
    if not rows:
        print("읽을 수 있는 라벨이 없다. make_labels.py 를 먼저 돌려라.")
        return 1
    print(f"① 데이터 {len(rows)}건 읽음 · 예시 정답: {rows[0]['text'][:50]}")

    model, processor = build_model(args.model, args.lora_r, args.init_adapter)
    # 어느 판 위에서 도는지 눈으로 확인시켜 준다 (2단인데 새 판으로 도는 사고 방지)
    base_note = f"{args.init_adapter} 위에 이어서" if args.init_adapter else "새 LoRA 판"
    print(f"② 모델 조립 완료 ({base_note})")

    ds = build_dataset(rows, processor)
    collator = WhisperCollator(processor)
    batch = collator([ds[i] for i in range(min(2, len(ds)))])
    print(f"③ 묶음 만듦 · 소리 {tuple(batch['input_features'].shape)} "
          f"· 정답 {tuple(batch['labels'].shape)}")

    # 한 걸음만 앞으로 굴린다(배우지는 않는다). 여기서 숫자가 나오면 성공
    model.eval()
    with torch.no_grad():
        out = model(**batch)
    print(f"④ 한 걸음 계산 성공 · 손실값 {out.loss.item():.4f}")
    print("\ndry-run 통과. 이대로 GPU 서버에 올려도 된다.")
    return 0


def train(args) -> int:
    """진짜 학습. GPU 가 있는 곳에서만 부른다."""
    import torch
    from transformers import Seq2SeqTrainer, Seq2SeqTrainingArguments, set_seed

    set_seed(SEED)
    has_gpu = torch.cuda.is_available()
    if not has_gpu:
        # 막고 싶은 사고: CPU 로 시작되면 며칠이 걸리는데 처음엔 도는 것처럼 보인다
        print("경고: GPU 를 찾지 못했다. CPU 로는 며칠이 걸린다. "
              "확인만 하려면 --dry-run 을 써라.")
        return 1

    rows = load_rows(Path(args.data))
    print(f"학습 데이터 {len(rows)}건")
    if args.init_adapter:
        # 2단 마무리는 '적은 데이터 · 낮은 학습률'이 전제다. 무엇 위에서 도는지 남긴다
        print(f"2단 마무리 학습: {args.init_adapter} 위에 이어서 배운다 "
              f"(학습률 {args.lr} · {args.epochs} 바퀴)")

    model, processor = build_model(args.model, args.lora_r, args.init_adapter)

    ds = build_dataset(rows, processor)
    # 학습 중에 성적을 보기 위해 10%를 떼어 둔다. 씨앗값을 고정해 매번 같게 나눈다
    split = ds.train_test_split(test_size=0.1, seed=SEED)

    targs = Seq2SeqTrainingArguments(
        output_dir=args.out,
        per_device_train_batch_size=args.batch,
        per_device_eval_batch_size=args.batch,
        learning_rate=args.lr,
        num_train_epochs=args.epochs,
        warmup_steps=args.warmup,
        fp16=True,                  # 숫자를 절반 크기로 다뤄 GPU 메모리를 아낀다
        seed=SEED,
        eval_strategy="epoch",
        save_strategy="epoch",
        logging_steps=20,
        report_to=[],               # 외부 기록 서비스로 내보내지 않는다
        remove_unused_columns=False,  # LoRA 는 이 값을 꺼야 칸이 안 사라진다
        label_names=["labels"],
    )

    trainer = Seq2SeqTrainer(
        model=model,
        args=targs,
        train_dataset=split["train"],
        eval_dataset=split["test"],
        data_collator=WhisperCollator(processor),
    )
    trainer.train()

    # **어댑터만** 저장한다(수십 MB). 원래 모델은 그대로이므로 다시 저장할 이유가 없다
    out_dir = Path(args.out)
    model.save_pretrained(out_dir)
    processor.save_pretrained(out_dir)
    print(f"\n어댑터 저장 완료 → {out_dir}")
    print("서버를 끄기 전에 이 폴더를 반드시 내려받아라. 끄면 디스크가 사라진다.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """명령줄 옵션표. 테스트에서 학습을 돌리지 않고 이것만 따로 확인할 수 있게 떼어 뒀다."""
    ap = argparse.ArgumentParser(description="Whisper 오류 보존 LoRA 학습")
    ap.add_argument("--data", required=True, help="make_labels 가 만든 라벨(.jsonl)")
    ap.add_argument("--model", default="openai/whisper-small",
                    help="openai/whisper-small 또는 openai/whisper-medium")
    ap.add_argument("--out", default="adapters/flagship-v1", help="어댑터를 저장할 폴더")
    ap.add_argument("--epochs", type=float, default=5)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--lr", type=float, default=1e-5)
    ap.add_argument("--warmup", type=int, default=50)
    ap.add_argument("--lora-r", type=int, default=16)
    ap.add_argument("--init-adapter", default=None,
                    help="이미 배운 어댑터 폴더. 주면 새 판을 만들지 않고 그 판 위에 "
                         "이어서 배운다(2단 고품질 마무리). 어댑터에 박힌 r·덧댄 자리가 "
                         "--lora-r 과 다르면 어댑터 쪽을 따른다")
    ap.add_argument("--dry-run", action="store_true",
                    help="학습하지 않고 한 걸음만 굴려 파이프라인을 확인한다")
    ap.add_argument("--dry-n", type=int, default=4, help="dry-run 에 쓸 건수")
    return ap


def main() -> int:
    enable_utf8_output()
    args = build_parser().parse_args()

    return dry_run(args) if args.dry_run else train(args)


if __name__ == "__main__":
    raise SystemExit(main())
