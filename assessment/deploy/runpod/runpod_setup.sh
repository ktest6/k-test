#!/usr/bin/env bash
# ============================================================================
# RunPod 팟 안에서 한 번 돌리는 차림 스크립트.
#
# 무엇을 하나
#   ① 올려 둔 작업 꾸러미(tar.gz)를 푼다
#   ② 모델을 받아 둘 자리(HF_HOME)를 못 박는다
#   ③ 실험실 라이브러리를 깐다 (torch 는 팟에 이미 깔린 것을 그대로 쓴다)
#   ④ 그래픽카드가 실제로 보이는지 확인한다
#
# 왜 HF_HOME 을 못 박나
#   안 박아 두면 모델(수 GB)을 홈 폴더로 받는데, RunPod 은 홈이 작은 디스크에
#   붙어 있어서 받다가 꽉 찬다. /workspace 는 큰 디스크라 여기로 돌려 놓는다.
#   (`사용법.md` 의 오디션 절에도 같은 이유가 적혀 있다.)
#
# 쓰는 법 (팟의 터미널에서)
#   bash runpod_setup.sh --tar /workspace/workbench.tar.gz
#   bash runpod_setup.sh --tar /workspace/workbench.tar.gz --light
#       (--light = 학습에 필요한 것만. 증인 받아쓰기용 espnet·funasr 을 건너뛴다)
#
# 이 스크립트는 꾸러미 안에도 들어 있지 않다. 팟에 따로 올려서 쓴다:
#   runpodctl send deploy/runpod/runpod_setup.sh
#
# 끝난 뒤 무슨 명령을 치는지는 같은 폴더의 `작업_순서.md` 를 보라.
# ============================================================================

set -euo pipefail

# ── 자리 정하기 ─────────────────────────────────────────────────────────────
WORK_ROOT="${WORK_ROOT:-/workspace}"          # 큰 디스크가 붙어 있는 자리
TARBALL=""                                    # 풀 꾸러미 (--tar 로 준다)
LIGHT="no"                                    # --light 를 주면 무거운 것을 건너뛴다

# 꾸러미를 풀면 생기는 폴더. pack_workbench.py 의 --prefix 와 같아야 한다.
PREFIX="${KTEST_PREFIX:-ktest_workbench}"
LAB_DIR="$WORK_ROOT/$PREFIX/assessment/scripts/speech_lab"

say()  { printf '\n=== %s ===\n' "$*"; }
info() { printf '  - %s\n' "$*"; }
warn() { printf '  [주의] %s\n' "$*" >&2; }
die()  { printf '\n[멈춤] %s\n' "$*" >&2; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --tar)   TARBALL="${2:-}"; shift 2 ;;
    --root)  WORK_ROOT="${2:-}"; LAB_DIR="$WORK_ROOT/$PREFIX/assessment/scripts/speech_lab"; shift 2 ;;
    --light) LIGHT="yes"; shift ;;
    -h|--help)
      printf '%s\n' \
        '쓰는 법: bash runpod_setup.sh --tar /workspace/workbench.tar.gz [--light]' \
        '  --tar    올려 둔 작업 꾸러미(tar.gz)' \
        '  --root   풀 자리 (기본 /workspace)' \
        '  --light  학습에 필요한 것만 깐다(증인 받아쓰기용 espnet·funasr 제외)'
      exit 0 ;;
    *) die "모르는 옵션: $1" ;;
  esac
done

# ── 1) 모델 받을 자리 못 박기 ───────────────────────────────────────────────
# 라이브러리를 불러오기 **전에** 세워야 한다. 불러올 때 이 값을 읽기 때문이다.
say "1) 모델 캐시 자리"
export HF_HOME="$WORK_ROOT/hf_cache"
export HUGGINGFACE_HUB_CACHE="$HF_HOME/hub"
export MODELSCOPE_CACHE="$HF_HOME/modelscope"
mkdir -p "$HF_HOME"
info "HF_HOME=$HF_HOME"
# 팟을 다시 켰을 때도 저절로 잡히게 해 둔다(터미널을 새로 열어도 유지된다)
if ! grep -q "HF_HOME=$HF_HOME" ~/.bashrc 2>/dev/null; then
  {
    echo "export HF_HOME=$HF_HOME"
    echo "export HUGGINGFACE_HUB_CACHE=$HF_HOME/hub"
    echo "export MODELSCOPE_CACHE=$HF_HOME/modelscope"
  } >> ~/.bashrc
  info "~/.bashrc 에도 적어 두었다(새 터미널에서도 유지)"
fi

# ── 2) 꾸러미 풀기 ──────────────────────────────────────────────────────────
say "2) 작업 꾸러미 풀기"
if [ -n "$TARBALL" ]; then
  [ -f "$TARBALL" ] || die "꾸러미가 없다: $TARBALL"
  mkdir -p "$WORK_ROOT"
  tar -xzf "$TARBALL" -C "$WORK_ROOT"
  info "풀었다: $TARBALL -> $WORK_ROOT/$PREFIX"
elif [ -d "$LAB_DIR" ]; then
  info "이미 풀려 있다: $WORK_ROOT/$PREFIX (다시 풀지 않는다)"
else
  die "--tar 로 꾸러미를 주거나, 미리 $WORK_ROOT/$PREFIX 에 풀어 두어야 한다"
fi
[ -d "$LAB_DIR" ] || die "실험실 폴더가 안 보인다: $LAB_DIR"

# ── 3) 라이브러리 ───────────────────────────────────────────────────────────
# torch 는 여기서 건드리지 않는다. RunPod 팟에는 그 그래픽카드에 맞는 torch 가
# 이미 깔려 있고, 다시 깔면 오히려 판이 어긋나 GPU 를 못 쓰게 된다.
say "3) 라이브러리 설치"
REQ="$LAB_DIR/requirements-lab.txt"
[ -f "$REQ" ] || die "목록 파일이 없다: $REQ"

python -m pip install --quiet --upgrade pip

if [ "$LIGHT" = "yes" ]; then
  # 학습(train_lora.py)과 평가(eval_ab.py)에만 필요한 것들.
  # 증인 받아쓰기용(espnet·funasr·torchaudio)은 설치가 오래 걸리고 잘 깨져서 뺀다.
  info "--light: 학습·평가에 필요한 것만 깐다"
  python -m pip install --quiet \
    "transformers>=4.44" "peft>=0.11" "datasets>=2.20" "accelerate>=0.33" \
    "soundfile>=0.12" "librosa>=0.10" "jiwer>=3.0" "faster-whisper"
else
  info "requirements-lab.txt 전부 깐다 (증인 받아쓰기 포함 · 몇 분 걸린다)"
  python -m pip install --quiet -r "$REQ"
fi
info "설치 끝"

# ── 4) 그래픽카드 확인 ──────────────────────────────────────────────────────
# 여기서 cuda 가 안 잡히면 뒤의 작업이 전부 CPU 로 돌아 몇십 배 느려진다.
# 그 사실을 몇 시간 뒤에 알게 되는 것이 제일 나쁘므로 지금 확인한다.
say "4) 그래픽카드 확인"
python - <<'PY'
import torch
print(f"  - torch {torch.__version__}")
print(f"  - cuda 쓸 수 있나? {torch.cuda.is_available()}")
if torch.cuda.is_available():
    print(f"  - 카드: {torch.cuda.get_device_name(0)}")
    total = torch.cuda.get_device_properties(0).total_memory / 1024**3
    print(f"  - 메모리: {total:.1f}GB")
else:
    print("  [주의] GPU 를 못 쓴다. 이대로 돌리면 몇십 배 느리다.")
PY

# ── 5) 다음에 할 일 ─────────────────────────────────────────────────────────
say "차림 끝"
printf '%s\n' \
  "  작업 폴더로 가서 시작한다:" \
  "    cd $LAB_DIR" \
  "" \
  "  무슨 명령을 치는지는 작업_순서.md 를 보라. 세 가지다:" \
  "    ① 증인 4종 받아쓰기 (launder_transcribe.py)" \
  "    ② v3 학습          (train_lora.py)" \
  "    ③ 평가             (eval_ab.py)" \
  "" \
  "  **끝나면 결과 파일을 먼저 내려받고 팟을 끈다. 팟을 끄면 디스크가 사라진다.**" \
  "    runpodctl send <결과파일>" \
  "    runpodctl stop pod \$RUNPOD_POD_ID"
