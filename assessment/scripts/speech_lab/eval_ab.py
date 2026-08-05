# -*- coding: utf-8 -*-
"""⑤ before/after 자동 평가기 — 받아쓰기 모델 둘 이상을 같은 문제로 겨루게 한다.

우리가 던지는 질문은 "누가 더 정확한가"가 아니다. 정확함만 재면 상용 서비스를
이길 수 없고, 이기려는 곳도 거기가 아니다. 진짜 질문은 이것이다.

    **학습자가 틀리게 말한 자리를, 그 모델이 살려서 적는가 아니면 조용히 고쳐 놓는가.**

고쳐 놓으면 채점기가 볼 오류가 사라진다. 응시자는 틀렸는데 점수는 안 깎인다.
그래서 세 가지를 함께 잰다.

  ① CER (글자 오류율)      — 낮을수록 정확. 기본기 확인용
  ② 오류 보존율            — 학습자 오류 중 살아남은 비율. **이게 우리 승부처다**
  ③ 대조군 오탐율          — 옳게 말한 사람에게 없는 오류를 만들어 내는 비율.
                             ②만 재면 "다 틀리게 적는 모델"이 1등이 되므로 짝으로 본다

지표 ②는 우리가 처음 만든 것이 아니다. ACL 2024 "Error-preserving ASR of Young
English Learners"(Michot et al., ZHAW)가 WEPR(Word Error Preservation Rate)로
먼저 정의했고, 우리는 그 정의를 한국어 어절 단위로 옮겨 쓴다. 우리 몫은
'한국어 L2 + 이 전사로 채점하면 사람 점수와 더 맞는가'까지 가는 것이다.

쓰는 법:
    python eval_ab.py --manifest ../../../data/manifests/71479_lar.jsonl \\
        --model base --model gemini --max-n 10
    (학습한 어댑터를 넣으려면 --model ../../../adapters/flagship-v1)
"""

from __future__ import annotations

import argparse
import io
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (  # noqa: E402
    ASSESSMENT_DIR,
    cer,
    diff_pairs,
    enable_utf8_output,
    load_audio_bytes,
    norm_text,
    print_table,
    read_manifest,
    serve_wav,
)


# ── 구인 경계: 애초에 잴 수 없는 오류는 분모에서 뺀다 ────────────────────────
def is_measurable_error(std: str, err: str) -> tuple[bool, str]:
    """이 오류가 **소리로 구별 가능한** 것인지 판정한다.

    왜 이 관문이 필요한가:
    '삼번'과 '3번'은 소리가 완전히 같다. 어느 쪽 철자로 쓰려 했는지는 소리만
    들어서는 원리상 알 수 없다. 그런데도 이것을 '보존해야 할 오류'로 세면
    모델에게 맞힐 수 없는 문제를 내고, 보존율이라는 숫자도 뜻을 잃는다.
    그래서 이런 부류는 **말하기에서 측정 불가한 오류 클래스**로 선언하고
    분자에서도 분모에서도 뺀다.

    v0 에 들어 있는 규칙은 하나뿐이다(숫자 표기 차이). 나머지 동음이표기
    (여덟/여덜, 돼/됐 …)는 발음 변환기가 있어야 판정할 수 있어서 아직 못 뺀다.
    → TODO: g2p 가 붙는 대로 "두 어절이 같은 소리로 읽히면 제외"를 여기에 넣는다.
       그때까지 보존율 숫자에는 이만큼의 거품이 남아 있다고 보고 읽어야 한다.

    돌려주는 값은 (잴 수 있는가, 못 잰다면 그 이유)다.
    """
    # 한쪽에만 숫자가 들어 있으면 '삼번 vs 3번' 부류로 본다
    std_has_digit = any(ch.isdigit() for ch in std)
    err_has_digit = any(ch.isdigit() for ch in err)
    if std_has_digit != err_has_digit:
        return False, "숫자표기차(소리 같음)"

    return True, ""


def classify_preservation(std: str, err: str, hyp_norm: str) -> str:
    """오류 한 자리를 모델이 어떻게 적었는지 세 갈래로 가른다.

    (pilot_preservation.py 로 8/2 에 처음 재 본 판정 규칙을 그대로 옮겨 정식화한 것이다.
     그때 Gemini 가 72.5% 로 나왔고, ACL 2024 논문의 Whisper-Large 67.3% 와 같은 급이었다.)

      보존 — 학습자가 낸 틀린 형태가 전사에 그대로 살아 있다  (우리가 원하는 것)
      세탁 — 틀린 형태가 사라지고 표준형으로 고쳐져 있다      (막으려는 것)
      기타 — 둘 다 아님. 아예 다르게 알아들은 경우

    std=표준형(읽어야 했던 말), err=발화형(실제로 낸 말), hyp_norm=모델 전사(비교용 형태)
    """
    sn, en = norm_text(std), norm_text(err)

    # 학습자가 말을 빼먹은 자리 — 전사에도 없어야 '보존'이다
    if not en:
        return "세탁" if sn and sn in hyp_norm else "보존"

    # ── 한쪽이 다른 쪽을 통째로 품고 있는 경우 ──────────────────────────────
    # 예: 표준형 "방" / 발화형 "방청소를" — '방청소를' 안에 '방'이 들어 있다.
    # 아래 일반 규칙은 "둘 다 전사에 보인다"고 읽어 '기타'로 흘려보내는데,
    # 실제로는 긴 쪽이 전사에 있으면 그쪽으로 말한 것이 분명하다.
    # (8/2 파일럿에는 이 갈래가 없어서 이런 자리가 전부 '기타'로 빠졌다.
    #  그래서 그때 잰 72.5% 와 지금 숫자를 그대로 견주면 안 된다.)
    if sn and (sn in en or en in sn):
        longer, shorter = (en, sn) if len(en) > len(sn) else (sn, en)
        long_verdict = "보존" if longer == en else "세탁"
        if longer in hyp_norm:
            return long_verdict
        if shorter in hyp_norm:
            return "세탁" if long_verdict == "보존" else "보존"
        return "기타"

    # 틀린 형태가 있고 표준형은 없다 -> 그대로 살렸다
    if en in hyp_norm and (not sn or sn not in hyp_norm):
        return "보존"

    # 표준형이 있고 틀린 형태는 없다 -> 고쳐 버렸다
    if sn and sn in hyp_norm and en not in hyp_norm:
        return "세탁"

    return "기타"


# ── 받아쓰기 모델들 ──────────────────────────────────────────────────────────
class BaseWhisper:
    """학습 전 기본 Whisper. 우리 LoRA 가 얼마나 달라졌는지 재는 출발선이다.

    faster-whisper(같은 모델을 빠르게 돌리는 판)를 쓴다. 이미 이 컴퓨터에
    받아져 있어서 인터넷 없이도 돈다.
    """

    def __init__(self, size: str = "small"):
        from faster_whisper import WhisperModel

        # int8 = 숫자를 거칠게 다뤄 CPU 에서도 돌아가게 하는 설정
        self.model = WhisperModel(size, device="cpu", compute_type="int8")
        self.name = f"base({size})"

    def __call__(self, wav_bytes: bytes) -> str:
        # 한국어라고 못 박는다. 안 그러면 짧은 발화에서 언어를 잘못 짚는다
        # 심판 고정(8/5): 설정 없이 부르면 품질 검사 실패 시 온도를 올려 주사위를
        # 굴리며 재시도해서(기본 온도 사다리 0→1.0) 실행마다 결과가 달라진다.
        # 같은 gold 100건에서 CER 12.2~15.4% 요동을 실측하고 아래로 고정했다.
        segments, _ = self.model.transcribe(
            io.BytesIO(wav_bytes), language="ko",
            beam_size=1, temperature=0.0, condition_on_previous_text=False,
        )
        return " ".join(s.text.strip() for s in segments).strip()


class GeminiTranscriber:
    """상용 대표 선수. 채점 서버가 지금 실제로 쓰는 그 경로 그대로 부른다.

    `src/speech/gemini_stt.py` 를 **읽기만 하고 고치지 않는다.** 실험 때문에
    실제 채점 코드를 손대면, 여기서 잰 숫자가 서비스의 숫자가 아니게 된다.
    """

    def __init__(self):
        if str(ASSESSMENT_DIR) not in sys.path:
            sys.path.insert(0, str(ASSESSMENT_DIR))
        from src.scoring.schema import AudioInput
        from src.speech.gemini_stt import GeminiStt

        self._AudioInput = AudioInput
        self.stt = GeminiStt()
        self.name = f"gemini({self.stt.model_name})"

    def __call__(self, wav_bytes: bytes) -> str:
        # 채점 코드는 '주소'로 음성을 받게 돼 있어서, 내 컴퓨터 안에 잠깐 주소를 연다
        with serve_wav(wav_bytes) as url:
            return self.stt.transcribe(self._AudioInput(url=url)).text


class AdapterWhisper:
    """우리가 학습한 LoRA 어댑터를 끼운 Whisper.

    원래 모델은 그대로 두고 어댑터(수십 MB)만 덧씌워 부른다.
    GPU 가 있으면 GPU 로, 없으면 CPU 로 돈다(CPU 는 느리지만 소량 확인은 된다).
    """

    def __init__(self, adapter_dir: str):
        import torch
        from peft import PeftModel
        from transformers import WhisperForConditionalGeneration, WhisperProcessor

        self.torch = torch
        self.processor = WhisperProcessor.from_pretrained(
            adapter_dir, language="korean", task="transcribe"
        )

        # 어댑터 폴더에 '어떤 모델 위에 덧댄 것인지'가 적혀 있다. 그것을 읽어 온다
        from peft import PeftConfig

        base_name = PeftConfig.from_pretrained(adapter_dir).base_model_name_or_path
        base = WhisperForConditionalGeneration.from_pretrained(base_name)
        self.model = PeftModel.from_pretrained(base, adapter_dir).eval()
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model.to(self.device)
        self.name = f"lora({Path(adapter_dir).name})"

    def __call__(self, wav_bytes: bytes) -> str:
        import numpy as np
        import soundfile as sf

        wave, sr = sf.read(io.BytesIO(wav_bytes), dtype="float32")
        if wave.ndim > 1:
            wave = wave.mean(axis=1)
        if sr != 16_000:
            import librosa

            wave = librosa.resample(wave, orig_sr=sr, target_sr=16_000)

        feats = self.processor.feature_extractor(
            np.asarray(wave, dtype="float32"), sampling_rate=16_000, return_tensors="pt"
        ).input_features.to(self.device)

        with self.torch.no_grad():
            ids = self.model.generate(input_features=feats, language="korean", task="transcribe")
        return self.processor.batch_decode(ids, skip_special_tokens=True)[0].strip()


def build_transcriber(spec: str):
    """`--model` 에 적힌 이름을 실제 받아쓰기 도구로 바꾼다."""
    if spec == "base":
        return BaseWhisper()
    if spec.startswith("base:"):          # base:medium 처럼 크기를 지정할 수 있다
        return BaseWhisper(spec.split(":", 1)[1])
    if spec == "gemini":
        return GeminiTranscriber()
    if Path(spec).exists():
        return AdapterWhisper(spec)
    raise ValueError(f"모르는 모델 지정: {spec} (base | gemini | 어댑터 폴더 경로)")


# ── 평가 ─────────────────────────────────────────────────────────────────────
def evaluate(transcriber, rows: list[dict]) -> dict:
    """모델 하나를 목록 전체에 돌려 세 지표를 낸다.

    낭독(LAR)만 오류 보존율을 잴 수 있다. 읽어야 했던 문장(prompt)이 있어야
    '어디서 틀렸는지'를 알 수 있는데, 자유발화에는 그 기준 문장이 없기 때문이다.
    """
    cers, counts = [], {"보존": 0, "세탁": 0, "기타": 0}
    excluded = 0                    # 구인 경계로 뺀 오류 자리 수
    ctrl_total, ctrl_false = 0, 0   # 대조군: 옳게 읽은 녹음 / 그중 가짜 오류가 난 것
    examples, failures = [], 0
    t0 = time.perf_counter()

    for i, r in enumerate(rows, 1):
        try:
            hyp = transcriber(load_audio_bytes(r))
        except Exception as exc:
            # 한 건이 실패해도 전체를 멈추지 않는다. 대신 몇 건 실패했는지 보고한다
            failures += 1
            print(f"    [{i:02d}] 실패: {type(exc).__name__}: {str(exc)[:70]}")
            continue

        cers.append(cer(r["ref"], hyp))
        hyp_norm = norm_text(hyp)

        if r.get("task") == "LAR" and r.get("prompt"):
            pairs = diff_pairs(r["prompt"], r["ref"])

            if not pairs:
                # 제시문 그대로 읽은 녹음 = 대조군.
                # 여기서 전사가 제시문과 다르면 없는 오류를 만들어 낸 것이다
                ctrl_total += 1
                if norm_text(r["prompt"]) != hyp_norm:
                    ctrl_false += 1
            else:
                for std, err in pairs:
                    ok, reason = is_measurable_error(std, err)
                    if not ok:
                        excluded += 1
                        continue
                    verdict = classify_preservation(std, err, hyp_norm)
                    counts[verdict] += 1
                    # 근거로 쓸 실제 사례를 남긴다. 숫자만 있으면 나중에 못 따진다
                    if len(examples) < 8:
                        examples.append(
                            {"id": r["id"], "표준형": std, "발화형": err,
                             "판정": verdict, "전사": hyp[:40]}
                        )

    judged = counts["보존"] + counts["세탁"]
    return {
        "name": transcriber.name,
        "n": len(cers),
        "실패": failures,
        "cer": sum(cers) / len(cers) if cers else float("nan"),
        "보존율": counts["보존"] / judged if judged else float("nan"),
        "counts": counts,
        "측정불가제외": excluded,
        "대조군": ctrl_total,
        "오탐율": ctrl_false / ctrl_total if ctrl_total else float("nan"),
        "초": time.perf_counter() - t0,
        "examples": examples,
    }


def main() -> int:
    enable_utf8_output()
    ap = argparse.ArgumentParser(description="받아쓰기 모델 A/B 비교")
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--model", action="append", required=True,
                    help="base | gemini | 어댑터 폴더 경로 (두 번 이상 지정)")
    ap.add_argument("--max-n", type=int, default=20, help="평가에 쓸 건수")
    args = ap.parse_args()

    if len(args.model) < 2:
        print("--model 을 두 개 이상 지정해야 비교가 된다.")
        return 1

    rows = read_manifest(Path(args.manifest))[: args.max_n]

    # 오류가 든 낭독이 몇 건인지 먼저 보여 준다. 이게 0이면 보존율이 안 나온다
    lar_err = sum(
        1 for r in rows
        if r.get("task") == "LAR" and diff_pairs(r.get("prompt", ""), r["ref"])
    )
    lar_ctrl = sum(
        1 for r in rows
        if r.get("task") == "LAR" and r.get("prompt")
        and not diff_pairs(r["prompt"], r["ref"])
    )
    print(f"평가 대상 {len(rows)}건 (오류 든 낭독 {lar_err}건 · 대조군 {lar_ctrl}건)")

    # 알고도 안 고친 것을 조용히 넘기지 않는다.
    # 505 전사에는 군말 표시 '/' 가 들어 있는데, CER 계산 규칙(norm_text)은 8/2 실측과
    # 맞추려고 그대로 두고 있다. 그래서 그만큼 CER 이 실제보다 조금 높게 나온다.
    slash_rows = sum(1 for r in rows if "/" in (r.get("ref") or ""))
    if slash_rows:
        print(f"  참고: 전사에 군말 표시 '/' 가 든 줄 {slash_rows}건 — "
              f"CER 규칙상 이 기호도 글자로 세므로 CER 이 조금 높게 나온다.")
    print()

    results = []
    for spec in args.model:
        print(f"── {spec} 돌리는 중")
        try:
            results.append(evaluate(build_transcriber(spec), rows))
        except Exception as exc:
            print(f"   준비 실패: {type(exc).__name__}: {str(exc)[:120]}")

    if not results:
        return 1

    def pct(v):
        return "측정불가" if v != v else f"{v:.1%}"  # v != v 는 '숫자가 아님' 판정

    print("\n=== A/B 비교표 ===")
    print_table(
        ["모델", "건수", "CER", "오류보존율", "보존/세탁/기타", "대조군오탐율", "걸린시간"],
        [
            [
                r["name"], f"{r['n']}", pct(r["cer"]), pct(r["보존율"]),
                f"{r['counts']['보존']}/{r['counts']['세탁']}/{r['counts']['기타']}",
                pct(r["오탐율"]), f"{r['초']:.0f}초",
            ]
            for r in results
        ],
    )
    print("\n  CER 은 낮을수록, 오류보존율은 높을수록, 대조군오탐율은 낮을수록 좋다.")
    if results[0]["측정불가제외"]:
        print(f"  구인 경계로 제외한 오류 자리: {results[0]['측정불가제외']}개 "
              f"(소리로 구별 안 되는 표기차 — 분모에서 뺐다)")

    # 숫자만 내놓지 않는다. 어떤 자리를 어떻게 판정했는지 실제 사례를 함께 보인다
    for r in results:
        if not r["examples"]:
            continue
        print(f"\n[{r['name']}] 판정 사례")
        print_table(
            ["파일", "표준형", "발화형", "판정", "전사(앞부분)"],
            [[e["id"][-18:], e["표준형"], e["발화형"] or "(빠뜨림)", e["판정"], e["전사"]]
             for e in r["examples"]],
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
