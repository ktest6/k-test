# -*- coding: utf-8 -*-
"""⑦-1 세탁 탐지기 — 증인 4명에게 학습쌍을 전부 받아쓰게 한다 (받아쓰기 단계).

**왜 받아쓰기와 판정을 두 파일로 나눴나**
받아쓰기는 GPU 가 있어야 하고 1만 건에 몇 시간이 걸린다. 판정 규칙(표 세기·방향
판정)은 손볼 일이 많은데, 한 덩이로 묶어 두면 규칙을 한 줄 고칠 때마다 GPU 로
몇 시간을 다시 태워야 한다. 그래서 **받아쓴 글을 파일로 남기고**, 판정은
launder_detect.py 가 그 파일만 읽어 CPU 에서 돌린다.

**증인 4명** (8/7 오디션에서 채용 — audition.py 참고)
    qwen3-asr-1.7b    문맥형 (앞말을 보고 지어내는 방식)
    fw(small)         문맥형
    owsm-ctc-v4       직청형 (소리 조각마다 글자를 붙이는 방식)
    sensevoice-small  직청형
문맥형·직청형을 섞은 이유는 성격이 같은 귀만 모으면 같이 틀려서 다수결이
'다수의 착각'이 되기 때문이다.

**모델을 불러오고 받아쓰는 코드는 여기서 새로 쓰지 않는다.** audition.py 의
후보 클래스를 그대로 가져다 쓴다. 그래야 오디션 때 잰 성적(보존율·오탐율)이
지금 나오는 받아쓰기의 성적이 된다. 결정 설정(같은 소리 → 같은 글)도 그대로
딸려 온다: beam_size=1 · temperature=0.0 · condition_on_previous_text=False,
do_sample=False, 그리디 CTC.

**두 가지 사고 대비** (8/7 오디션에서 실제로 겪은 것)
  · 메모리 — 모델을 한 번에 하나만 올리고, 한 명이 끝나면 반드시 내려놓는다
  · 중단   — 한 건 받아쓸 때마다 곧바로 파일에 적고, 다시 돌리면 이미 한 건은 건너뛴다

쓰는 법:
    # 로컬 소량 확인 (윈도우, CPU)
    python launder_transcribe.py --package D:/해커톤데이터/v1_package \\
        --only fw-small --limit 2 --out D:/해커톤데이터/launder_smoke

    # 서버 전수 (리눅스 GPU)
    python launder_transcribe.py --package /workspace/v1_package \\
        --selection /workspace/v1_selection.json --device cuda \\
        --hf-cache /workspace/hf_cache --out /workspace/launder
"""

from __future__ import annotations

import argparse
import gc
import json
import os
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import audition  # noqa: E402  (HF_CACHE 를 바꿔 끼우려고 모듈째로 부른다)
from _common import enable_utf8_output, load_audio_bytes, read_manifest  # noqa: E402
from audition import (  # noqa: E402
    OwsmCtcCandidate,
    Qwen3AsrCandidate,
    SenseVoiceCandidate,
    _release_model,
)
from eval_ab import BaseWhisper  # noqa: E402


# ── GPU 로 옮겨 주는 얇은 껍데기들 ───────────────────────────────────────────
# audition.py 의 후보들은 전부 CPU 로 못 박혀 있다(오디션을 CPU 노트북에서 돌렸다).
# 1만 건을 받아쓰려면 GPU 가 있어야 하는데, 그렇다고 audition.py 를 고치면 8/7 에 잰
# 오디션 성적과 지금 받아쓰기가 같은 코드에서 나온 것이 아니게 된다.
# 그래서 **audition.py 는 한 줄도 건드리지 않고**, '어디서 계산하나'만 바꾼 판을
# 여기에 따로 둔다. 받아쓰는 방법(__call__)은 전부 물려받으므로 결정 설정도 그대로다.
#
# ⚠ 이 컴퓨터에는 GPU 가 없어 --device cuda 경로는 **아직 실제로 돌려 보지 못했다.**
#   서버에서 처음 돌릴 때는 반드시 --limit 2 로 먼저 확인하고 전수로 넘어가라.


class _ToDeviceProcessor:
    """소리에서 뽑은 숫자 뭉치를 GPU 로 옮겨 주는 껍데기.

    Qwen 후보의 받아쓰기 코드는 "처리기에게 소리를 주면 숫자 뭉치가 나온다"고
    돼 있는데, 모델만 GPU 에 올리면 숫자는 CPU 에 남아 계산이 시작도 못 한다.
    그 코드를 베껴 고치는 대신, 처리기를 감싸서 **나오는 숫자만 GPU 로 옮긴다.**
    나머지 기능(대화 형식 만들기·글자 되돌리기)은 원래 처리기에게 그대로 넘긴다.
    """

    def __init__(self, inner, device: str):
        self._inner, self._device = inner, device

    def __call__(self, *args, **kwargs):
        return self._inner(*args, **kwargs).to(self._device)

    def __getattr__(self, name):
        return getattr(self._inner, name)


class GpuFasterWhisper(BaseWhisper):
    """faster-whisper small 을 GPU 에서 돌리는 판. 받아쓰는 방법은 물려받는다."""

    def __init__(self, device: str):
        from faster_whisper import WhisperModel

        # 부모의 준비 과정을 부르지 않는 이유는 하나뿐이다 — 부모는 CPU 로 못 박혀 있다.
        # 받아쓰기 설정이 든 곳(__call__)은 손대지 않으므로 결정성은 그대로다.
        compute = "float16" if device.startswith("cuda") else "int8"
        self.model = WhisperModel("small", device=device, compute_type=compute)
        self.name = "fw(small)"


class GpuQwen3Asr(Qwen3AsrCandidate):
    """Qwen3-ASR 을 GPU 에서 돌리는 판."""

    def __init__(self, device: str):
        super().__init__()            # 불러오기는 부모 것을 그대로 쓴다
        self.model.to(device)
        self.processor = _ToDeviceProcessor(self.processor, device)


class GpuSenseVoice(SenseVoiceCandidate):
    """SenseVoice-Small 을 GPU 에서 돌리는 판."""

    def __init__(self, device: str):
        from funasr import AutoModel

        self.model = AutoModel(model=SenseVoiceCandidate.REPO, device=device,
                               disable_update=True, hub="hf")
        self.name = "sensevoice-small"


class GpuOwsmCtc(OwsmCtcCandidate):
    """OWSM-CTC v4 를 GPU 에서 돌리는 판. 30초씩 잘라 넣는 규칙은 물려받는다."""

    def __init__(self, device: str):
        import soundfile  # noqa: F401  (espnet 이 요구한다)
        from espnet2.bin.s2t_inference_ctc import Speech2TextGreedySearch
        from espnet_model_zoo.downloader import ModelDownloader

        downloader = ModelDownloader(str(audition.HF_CACHE / "espnet"))
        parts = downloader.download_and_unpack(self.REPO)
        self.model = Speech2TextGreedySearch(
            **parts, device=device, use_flash_attn=False,
            lang_sym="<kor>", task_sym="<asr>",
        )
        self.name = "owsm-ctc-v4"


#: 채용된 증인 4명. `cpu` 칸은 audition.py 의 후보를 **그대로** 부른다
#: (그래야 오디션 때 받아쓴 gold 100건과 이어 붙여 쓸 수 있다).
#: `gpu` 칸은 위에서 만든 '자리만 옮긴 판'이다.
WITNESSES = {
    "qwen3-asr": {"cpu": Qwen3AsrCandidate, "gpu": GpuQwen3Asr,
                  "이름": "qwen3-asr-1.7b", "유형": "문맥형"},
    "fw-small": {"cpu": lambda: BaseWhisper("small"), "gpu": GpuFasterWhisper,
                 "이름": "fw(small)", "유형": "문맥형"},
    "owsm-v4": {"cpu": OwsmCtcCandidate, "gpu": GpuOwsmCtc,
                "이름": "owsm-ctc-v4", "유형": "직청형"},
    "sensevoice": {"cpu": SenseVoiceCandidate, "gpu": GpuSenseVoice,
                   "이름": "sensevoice-small", "유형": "직청형"},
}


# ── 준비 ─────────────────────────────────────────────────────────────────────
def pin_cache(path: str) -> None:
    """모델 내려받는 자리를 못 박는다. 리눅스 서버와 윈도우 노트북 둘 다에서 쓴다.

    안 박아 두면 홈 폴더로 받는데, 서버에서는 홈이 작은 디스크에 붙어 있어
    4GB 짜리 모델을 받다가 꽉 찬다. 라이브러리를 불러오기 **전에** 세워야
    한다(라이브러리는 불러올 때 이 값을 읽는다).
    """
    cache = Path(path)
    cache.mkdir(parents=True, exist_ok=True)
    os.environ["HF_HOME"] = str(cache)
    # 옛 이름을 보는 라이브러리(funasr 등)도 있어서 같이 세워 준다
    os.environ["HUGGINGFACE_HUB_CACHE"] = str(cache / "hub")
    os.environ["MODELSCOPE_CACHE"] = str(cache / "modelscope")
    # OWSM 은 espnet 이 따로 내려받는데, 그 자리는 audition.py 안의 값을 본다.
    # audition.py 를 고치는 대신 값만 바꿔 끼운다
    audition.HF_CACHE = cache


def pick_device(spec: str) -> str:
    """어디서 계산할지 정한다. `auto` 면 GPU 가 있을 때만 GPU 를 쓴다."""
    if spec != "auto":
        return spec
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def build_rows(args) -> list[dict]:
    """받아쓸 목록을 만든다. 세 가지 입력 방식을 받는다.

      ① --manifest  목록 jsonl (gold_100.jsonl 처럼 id·음성 위치가 든 것)
      ② --package + --selection  학습꾸러미 + 선별 목록 (여기가 본진 1만 건)
      ③ --package 만  꾸러미의 train.jsonl 전부

    돌려주는 줄마다 `id`(파일 이름)와 `wav`(음성 파일 자리)가 들어 있다.
    ①은 음성이 zip 안에 있을 수도 있어 원래 줄(`row`)도 함께 들고 간다.
    """
    if args.manifest:
        rows = read_manifest(Path(args.manifest))
        return [{"id": r["id"], "wav": None, "row": r} for r in rows]

    if not args.package:
        raise SystemExit("--manifest 또는 --package 중 하나는 있어야 한다")

    package = Path(args.package)
    audio_dir = Path(args.audio_root) if args.audio_root else package / "audio"

    if args.selection:
        data = json.loads(Path(args.selection).read_text(encoding="utf-8"))
        ids = [pair_id for pairs in data.values() for pair_id, _ in pairs]
    else:
        ids = [Path(r["audio"]).stem
               for r in read_manifest(package / "train.jsonl")]

    return [{"id": i, "wav": str(audio_dir / f"{i}.wav"), "row": None} for i in ids]


def read_wav(row: dict) -> bytes:
    """줄 하나가 가리키는 음성 파일을 통째로 읽는다.

    꾸러미에서 온 줄은 wav 자리가 정해져 있고, 목록 파일에서 온 줄은 zip 안에
    들어 있을 수도 있어 _common 의 읽기 함수에 맡긴다.
    """
    if row.get("wav"):
        return Path(row["wav"]).read_bytes()
    return load_audio_bytes(row["row"])


# ── 증인 한 명 돌리기 ────────────────────────────────────────────────────────
def load_done(out_path: Path) -> set[str]:
    """이미 받아쓴 파일 이름을 모은다. 다시 돌릴 때 그만큼 건너뛰려는 것이다.

    깨진 줄(쓰다가 멈춘 마지막 줄)은 조용히 버린다 — 그 건은 다시 받아쓰면 된다.
    """
    done: set[str] = set()
    if not out_path.exists():
        return done
    with out_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                done.add(json.loads(line)["id"])
            except Exception:
                pass
    return done


def run_witness(key: str, meta: dict, rows: list[dict], out_dir: Path,
                device: str) -> dict:
    """증인 한 명에게 목록 전체를 받아쓰게 하고, 한 건씩 곧바로 파일에 적는다."""
    name = meta["이름"]
    out_path = out_dir / f"{key}.jsonl"
    done = load_done(out_path)
    todo = [r for r in rows if r["id"] not in done]

    print(f"\n── [{name}] {meta['유형']} · {device} — "
          f"할 일 {len(todo)}건 (이미 끝낸 것 {len(done)}건)", flush=True)
    if not todo:
        print("   이미 다 받아썼다. 건너뛴다.", flush=True)
        return {"증인": name, "상태": "이미완료", "건수": len(done)}

    # 모델 준비. 여기서 넘어지면 그 증인만 빼고 다음 증인으로 간다
    t_load = time.perf_counter()
    try:
        model = meta["cpu"]() if device == "cpu" else meta["gpu"](device)
    except Exception as exc:
        reason = f"{type(exc).__name__}: {str(exc)[:200]}"
        print(f"   실패 — 준비 못 함: {reason}", flush=True)
        print(traceback.format_exc()[-600:])
        return {"증인": name, "상태": "실패", "사유": reason}
    print(f"   준비 완료 ({time.perf_counter() - t_load:.0f}초)", flush=True)

    ok = fail = 0
    t0 = time.perf_counter()
    # 'a'(이어 쓰기)로 연다 — 앞서 받아쓴 것을 지우지 않기 위해서다
    with out_path.open("a", encoding="utf-8") as f:
        for i, row in enumerate(todo, 1):
            try:
                text = model(read_wav(row))
                ok += 1
            except Exception as exc:
                # 한 건이 안 돼도 멈추지 않는다. 무엇이 왜 안 됐는지는 남긴다
                fail += 1
                text = ""
                print(f"   [{i}] 실패 {row['id']}: {type(exc).__name__}: {str(exc)[:70]}",
                      flush=True)

            f.write(json.dumps({"id": row["id"], "model": name, "text": text},
                               ensure_ascii=False) + "\n")
            f.flush()   # 중간에 죽어도 여기까지는 남는다

            if i % 20 == 0 or i == len(todo):
                spent = time.perf_counter() - t0
                left = spent / i * (len(todo) - i)
                print(f"   {i}/{len(todo)}건 · {spent / i:.1f}초/건 · "
                      f"남은 시간 약 {left / 60:.0f}분", flush=True)

    # 다음 증인을 올리기 전에 이 증인을 반드시 내려놓는다.
    # 안 내려놓으면 모델이 쌓여서(Qwen 4GB + Whisper 1.5GB …) 메모리가 바닥난다
    _release_model(model)
    del model
    gc.collect()

    spent = time.perf_counter() - t0
    print(f"   끝: 성공 {ok}건 · 실패 {fail}건 · {spent / 60:.1f}분", flush=True)
    return {"증인": name, "상태": "완료", "성공": ok, "실패": fail,
            "초": round(spent, 1), "파일": str(out_path)}


# ── 실행 ─────────────────────────────────────────────────────────────────────
def main() -> int:
    enable_utf8_output()

    ap = argparse.ArgumentParser(description="세탁 탐지기 증인단 전수 받아쓰기")
    ap.add_argument("--manifest", help="받아쓸 목록 jsonl (id + 음성 위치)")
    ap.add_argument("--package", help="학습꾸러미 폴더 (audio/ + train.jsonl)")
    ap.add_argument("--selection", help="선별 목록 json (v1_selection.json 형식)")
    ap.add_argument("--audio-root", help="wav 폴더를 따로 지정할 때")
    ap.add_argument("--out", required=True, help="받아쓴 글을 모을 폴더")
    ap.add_argument("--only", default="", help=f"증인 지정 (쉼표). 가능: {list(WITNESSES)}")
    ap.add_argument("--limit", type=int, default=0, help="앞에서 몇 건만 (확인용)")
    ap.add_argument("--device", default="auto", help="auto | cpu | cuda")
    ap.add_argument("--hf-cache", default="", help="모델 내려받을 폴더")
    args = ap.parse_args()

    # 모델 캐시 자리를 라이브러리 부르기 전에 못 박는다
    if args.hf_cache:
        pin_cache(args.hf_cache)
    device = pick_device(args.device)

    rows = build_rows(args)
    if args.limit:
        rows = rows[: args.limit]

    picked = [k.strip() for k in args.only.split(",") if k.strip()] or list(WITNESSES)
    unknown = [k for k in picked if k not in WITNESSES]
    if unknown:
        print(f"모르는 증인: {unknown} (가능: {list(WITNESSES)})")
        return 1

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"받아쓸 것 {len(rows)}건 · 증인 {len(picked)}명 · 계산 자리 {device}")
    print(f"모델 캐시: {os.environ.get('HF_HOME', '(기본 위치)')}")
    print(f"저장 폴더: {out_dir}")

    # 증인은 **한 명씩** 올렸다 내린다. 한꺼번에 올리면 메모리가 바닥난다
    reports = []
    for key in picked:
        reports.append(run_witness(key, WITNESSES[key], rows, out_dir, device))

    # 이 받아쓰기가 어떤 조건에서 나온 것인지 함께 남긴다.
    # 계산 자리(cpu/cuda)가 다르면 글자가 조금 달라질 수 있어서, 나중에
    # 다른 판과 섞어 쓰기 전에 확인할 수 있어야 한다
    (out_dir / "_meta.json").write_text(
        json.dumps({
            "실행시각": time.strftime("%Y-%m-%d %H:%M:%S"),
            "건수": len(rows), "계산자리": device,
            "입력": {"manifest": args.manifest, "package": args.package,
                     "selection": args.selection},
            "결정설정": "audition.py 후보를 그대로 사용 (beam=1 · temperature=0 · "
                        "do_sample=False · 그리디 CTC)",
            "증인": reports,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("\n=== 받아쓰기 요약 ===")
    for r in reports:
        print(f"  · {r['증인']}: {r['상태']}"
              + (f" 성공 {r['성공']}건 · 실패 {r['실패']}건" if r["상태"] == "완료" else "")
              + (f" — {r['사유']}" if r["상태"] == "실패" else ""))
    print(f"\n저장: {out_dir}")
    print("다음: launder_detect.py 로 판정한다 "
          f"(--witness {out_dir}/<증인>.jsonl 을 4개 다 넣는다)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
