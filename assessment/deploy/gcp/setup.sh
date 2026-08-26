#!/usr/bin/env bash
# ============================================================================
# K-TEST 시연용 서버 한 번에 차리기 (GCP GPU VM · Ubuntu 22.04)
#
# 무엇을 하는 스크립트인가
#   9/2 시연장에서는 재완이 PC 를 못 쓴다. 그래서 지금 내 PC 에서 돌던 서버 둘을
#   GCP 의 그래픽카드 VM 으로 옮겨 **24시간 켜 두는 것**이 목적이다.
#     · 채점 서버(FastAPI)   8001 포트 — 백엔드가 부르는 곳. 바깥에 열어 준다.
#     · LoRA 받아쓰기 서버    8100 포트 — 채점 서버만 부른다. 바깥에 안 연다.
#   이 스크립트 하나를 VM 에서 돌리면 저장소·파이썬 환경·서비스 등록까지 끝난다.
#
# 어떻게 쓰나 (VM 안에서)
#   sudo bash /opt/ktest/repo/assessment/deploy/gcp/setup.sh
#   자세한 순서는 같은 폴더의 `콘솔_클릭_순서.md` 를 보라.
#
# 두 번 돌려도 안전하다(멱등).
#   이미 있는 폴더·파이썬 환경·서비스는 다시 만들지 않고 그대로 쓴다. 중간에
#   실패해서 다시 돌려야 할 때 처음부터 지우고 시작할 필요가 없게 한 것이다.
#
# 안 하는 것
#   · 열쇠(API 키) 값을 넣어 주지 않는다. `/opt/ktest/env/ktest.env` 를 사람이 채운다.
#   · 어댑터(v2_adapter.tar.gz)를 대신 받아 오지 않는다. 사람이 올려 둔다.
#   두 가지 다 비밀이라 스크립트에 적으면 저장소에 새어 나가기 때문이다.
#
# 먼저 있던 것과의 관계
#   `scripts/speech_lab/gcp/setup_lora_vm.sh` 는 8/25 에 급히 만든 것으로,
#   **받아쓰기 서버 하나만** 홈 폴더에서 nohup 으로 띄운다. 창을 닫거나 VM 을
#   다시 켜면 서버가 안 뜬다. 이 스크립트는 그것을 대신하는 정식판이다 —
#   **서버 둘 다** systemd 에 올려 재부팅해도 저절로 살아나게 한다.
#   라이브러리 판은 그쪽과 똑같이 맞춰 두었다(requirements-stt.txt 참고).
# ============================================================================

# -e: 한 줄이라도 실패하면 즉시 멈춘다(반쯤 차려진 서버가 남는 것이 제일 나쁘다)
# -u: 안 정한 변수를 쓰면 멈춘다   -o pipefail: 파이프 중간 실패도 잡는다
set -euo pipefail

# ── 자리(경로) 정하기 ────────────────────────────────────────────────────────
# 여기 적힌 경로가 systemd 서비스 파일(ktest-api.service·ktest-stt.service)에
# 적힌 경로와 **글자까지 같아야 한다.** 한쪽만 바꾸면 서비스가 안 뜬다.
KTEST_ROOT="${KTEST_ROOT:-/opt/ktest}"
REPO_DIR="$KTEST_ROOT/repo"                 # 저장소를 받아 둘 자리
ASSESS_DIR="$REPO_DIR/assessment"           # 우리 파트 폴더(서버 둘 다 여기서 돈다)
VENV_API="$KTEST_ROOT/venv-api"             # 채점 서버용 파이썬 환경(가볍다)
VENV_STT="$KTEST_ROOT/venv-stt"             # 받아쓰기 서버용 파이썬 환경(torch·무겁다)
ADAPTER_DIR="$KTEST_ROOT/adapters/v2"       # 학습해 둔 LoRA v2 어댑터를 푸는 자리
ENV_DIR="$KTEST_ROOT/env"                   # 열쇠를 담아 두는 자리
ENV_FILE="$ENV_DIR/ktest.env"               # systemd 가 읽는 환경변수 파일
HF_CACHE="$KTEST_ROOT/hf_cache"             # 허깅페이스가 베이스 모델을 받아 둘 자리
# 서버를 돌릴 전용 계정(root 로 안 돌린다).
# 이 이름을 바꾸려면 ktest-api.service · ktest-stt.service 의 User·Group 도 같이 고쳐야 한다.
SERVICE_USER="${SERVICE_USER:-ktest}"

# 저장소 주소·가지. 바꿔서 돌리고 싶으면 환경변수로 준다.
REPO_URL="${KTEST_REPO_URL:-https://github.com/ktest6/k-test.git}"
REPO_BRANCH="${KTEST_REPO_BRANCH:-main}"

# torch 를 받아 올 자리. GCP Deep Learning VM 은 CUDA 12.x 라 cu124 판을 쓴다.
# (8/22 에 내 PC RTX 4060 에서 v2 어댑터가 실제로 돌아간 것이 torch 2.6.0+cu124 다.
#  같은 조합을 그대로 옮겨야 그때 확인한 동작이 그대로 재현된다.)
TORCH_INDEX="${KTEST_TORCH_INDEX:-https://download.pytorch.org/whl/cu124}"
TORCH_SPEC="${KTEST_TORCH_SPEC:-torch==2.6.0}"

# 이 스크립트가 놓인 자리. 여기서 서비스 파일·환경 템플릿을 가져다 쓴다.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 저장소를 tar 로 올려서 쓸 때 그 파일 자리. --from-tar 로 준다.
FROM_TAR=""
# --update 를 주면 이미 받아 둔 저장소를 최신으로 당겨 온다(안 주면 손대지 않는다).
DO_UPDATE="no"

# ── 화면에 보기 좋게 찍기 ────────────────────────────────────────────────────
say()  { printf '\n=== %s ===\n' "$*"; }
info() { printf '  - %s\n' "$*"; }
warn() { printf '  [주의] %s\n' "$*" >&2; }
die()  { printf '\n[멈춤] %s\n' "$*" >&2; exit 1; }

usage() {
  printf '%s\n' \
    '쓰는 법:' \
    '  sudo bash setup.sh                 저장소를 git 으로 받아서 차린다' \
    '  sudo bash setup.sh --from-tar k-test.tar.gz' \
    '                                     인터넷 대신 올려 둔 tar 로 차린다' \
    '                                     (tar 안에 assessment/ 가 맨 위에 있어야 한다)' \
    '  sudo bash setup.sh --update        이미 받아 둔 저장소를 최신으로 당긴다' \
    '' \
    '끝난 뒤 할 일:' \
    '  1) /opt/ktest/env/ktest.env 에 열쇠를 채운다 (env.template 이 복사돼 있다)' \
    '  2) v2_adapter.tar.gz 를 /opt/ktest/adapters/v2 에 푼다' \
    '  3) sudo systemctl restart ktest-stt ktest-api' \
    '  4) bash deploy/gcp/healthcheck.sh 로 확인한다'
}

# ── 들어온 옵션 읽기 ─────────────────────────────────────────────────────────
while [ $# -gt 0 ]; do
  case "$1" in
    --from-tar) FROM_TAR="${2:-}"; shift 2 ;;
    --update)   DO_UPDATE="yes"; shift ;;
    -h|--help)  usage; exit 0 ;;
    *) die "모르는 옵션: $1  (--help 를 보라)" ;;
  esac
done

# root 여야 apt 설치와 systemd 등록이 된다
[ "$(id -u)" = "0" ] || die "sudo 로 돌려야 한다:  sudo bash $0"

# ── 1) 밑바탕 꾸러미 ─────────────────────────────────────────────────────────
# soundfile 이 wav 를 읽으려면 libsndfile1 이 있어야 한다(파이썬 꾸러미만으로는 안 된다).
# ffmpeg 는 wav 가 아닌 소리가 섞여 들어올 때를 대비한 보험이다.
install_base_packages() {
  say "1) 밑바탕 꾸러미 확인"
  # 이미 다 깔려 있으면 apt 를 부르지 않는다(두 번째 실행이 빨라진다)
  local missing=""
  for pkg in git curl tar libsndfile1 ffmpeg; do
    dpkg -s "$pkg" >/dev/null 2>&1 || missing="$missing $pkg"
  done
  if [ -z "$missing" ]; then
    info "이미 다 있다 — 건너뛴다"
    return
  fi
  info "설치할 것:$missing"
  apt-get update -qq
  # shellcheck disable=SC2086
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq $missing
}

# ── 2) 쓸 파이썬 고르기 ──────────────────────────────────────────────────────
# 왜 3.11 이상을 찾나:
#   채점 서버가 쓰는 requirements.txt 에 numpy 2.4 처럼 **파이썬 3.11 부터만
#   설치본이 나오는 꾸러미**가 들어 있다. Ubuntu 22.04 의 기본 파이썬은 3.10 이라
#   그대로 쓰면 pip 이 소스에서 빌드하려다 실패한다. 그래서 먼저 3.11+ 를 찾고,
#   없으면 deadsnakes 라는 공개 저장소에서 3.11 을 받아 온다.
PYBIN=""
pick_python() {
  say "2) 파이썬 고르기"
  local cand
  for cand in python3.13 python3.12 python3.11; do
    if command -v "$cand" >/dev/null 2>&1; then
      PYBIN="$(command -v "$cand")"
      info "찾음: $PYBIN ($("$PYBIN" -V 2>&1))"
      return
    fi
  done

  warn "3.11 이상이 없다. deadsnakes 에서 python3.11 을 설치한다."
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq software-properties-common
  add-apt-repository -y ppa:deadsnakes/ppa >/dev/null
  apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3.11 python3.11-venv python3.11-dev
  command -v python3.11 >/dev/null 2>&1 || die "python3.11 설치에 실패했다"
  PYBIN="$(command -v python3.11)"
  info "설치함: $PYBIN ($("$PYBIN" -V 2>&1))"
}

# venv 를 만들려면 그 파이썬의 venv 모듈이 있어야 한다. 없으면 깔아 준다.
ensure_venv_module() {
  if "$PYBIN" -c "import venv" >/dev/null 2>&1; then
    return
  fi
  local ver
  ver="$("$PYBIN" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
  warn "python$ver 에 venv 모듈이 없다 — python$ver-venv 를 설치한다"
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "python$ver-venv"
}

# ── 3) 계정과 폴더 ───────────────────────────────────────────────────────────
# 서버를 root 로 돌리지 않는 까닭: 채점 서버는 바깥(백엔드)에서 오는 요청을 받는다.
# 만에 하나 뚫려도 이 계정이 할 수 있는 일만 할 수 있게 미리 좁혀 둔다.
make_user_and_dirs() {
  say "3) 계정·폴더 만들기"
  if id -u "$SERVICE_USER" >/dev/null 2>&1; then
    info "계정 $SERVICE_USER 이미 있음"
  else
    # --system: 사람이 로그인하는 계정이 아니라 서비스 전용 계정
    # --user-group: 같은 이름의 그룹도 함께 만든다(서비스 파일이 Group=ktest 를 쓴다)
    useradd --system --user-group --create-home --home-dir "$KTEST_ROOT/home" \
            --shell /usr/sbin/nologin "$SERVICE_USER"
    info "계정 $SERVICE_USER 만듦"
  fi
  mkdir -p "$KTEST_ROOT" "$ENV_DIR" "$ADAPTER_DIR" "$HF_CACHE" "$KTEST_ROOT/home"
  info "폴더 준비: $KTEST_ROOT"
}

# ── 4) 저장소 가져오기 ───────────────────────────────────────────────────────
fetch_repo() {
  say "4) 저장소 준비"
  if [ -n "$FROM_TAR" ]; then
    # 인터넷으로 git 을 못 쓸 때(사내망 등) 쓰는 길. tar 를 풀어 넣는다.
    [ -f "$FROM_TAR" ] || die "tar 파일이 없다: $FROM_TAR"
    mkdir -p "$REPO_DIR"
    tar -xzf "$FROM_TAR" -C "$REPO_DIR"
    info "tar 를 풀었다: $FROM_TAR -> $REPO_DIR"
  elif [ -d "$REPO_DIR/.git" ]; then
    info "이미 받아 둔 저장소가 있다: $REPO_DIR"
    if [ "$DO_UPDATE" = "yes" ]; then
      # --update 를 준 경우에만 최신으로 당긴다. 안 주면 손대지 않는다 —
      # 시연 전날 모르는 새 코드가 딸려 들어오는 것이 제일 위험하기 때문이다.
      git -C "$REPO_DIR" fetch --depth 1 origin "$REPO_BRANCH"
      git -C "$REPO_DIR" checkout -B "$REPO_BRANCH" "origin/$REPO_BRANCH"
      info "최신으로 당겼다 ($REPO_BRANCH)"
    else
      info "--update 를 안 줬으므로 그대로 둔다"
    fi
  else
    # git 저장소도 아닌데 폴더에 뭔가 들어 있으면, 덮어쓰지 말고 사람에게 묻는다.
    # (앞서 tar 로 잘못 풀어 둔 경우 등 — 조용히 지우면 복구할 길이 없다)
    if [ -d "$REPO_DIR" ] && [ -n "$(ls -A "$REPO_DIR" 2>/dev/null)" ]; then
      die "$REPO_DIR 에 뭔가 들어 있는데 git 저장소가 아니다.
     비우고 다시 하거나(rm -rf $REPO_DIR), --from-tar 로 다시 풀어라."
    fi
    git clone --depth 1 --branch "$REPO_BRANCH" "$REPO_URL" "$REPO_DIR"
    info "새로 받았다: $REPO_URL ($REPO_BRANCH)"
  fi

  # 이 두 파일이 없으면 아래 단계가 전부 무의미하므로 여기서 확인하고 멈춘다
  [ -f "$ASSESS_DIR/requirements.txt" ] \
    || die "채점 서버 목록이 없다: $ASSESS_DIR/requirements.txt"
  [ -f "$ASSESS_DIR/scripts/speech_lab/lora_stt_server.py" ] \
    || die "받아쓰기 서버 파일이 없다: $ASSESS_DIR/scripts/speech_lab/lora_stt_server.py"
}

# ── 5) 파이썬 환경 둘 ────────────────────────────────────────────────────────
# 왜 하나로 안 합치나:
#   채점 서버는 torch 가 없어도 돌고(수백 MB), 받아쓰기 서버는 torch 가 있어야
#   돈다(수 GB). 한 환경에 섞으면 채점 서버를 다시 깔 때마다 torch 까지 건드리게
#   되고, 라이브러리 판이 어긋나면 둘이 같이 죽는다. 그래서 갈라 둔다.
make_venv_api() {
  say "5-1) 채점 서버 파이썬 환경"
  if [ ! -x "$VENV_API/bin/python" ]; then
    "$PYBIN" -m venv "$VENV_API"
    info "새로 만들었다: $VENV_API"
  else
    info "이미 있다: $VENV_API"
  fi
  "$VENV_API/bin/pip" install --quiet --upgrade pip
  "$VENV_API/bin/pip" install --quiet -r "$ASSESS_DIR/requirements.txt"
  info "설치 완료 (requirements.txt)"
}

make_venv_stt() {
  say "5-2) 받아쓰기 서버 파이썬 환경 (torch·GPU)"
  if [ ! -x "$VENV_STT/bin/python" ]; then
    "$PYBIN" -m venv "$VENV_STT"
    info "새로 만들었다: $VENV_STT"
  else
    info "이미 있다: $VENV_STT"
  fi
  "$VENV_STT/bin/pip" install --quiet --upgrade pip

  # torch 는 그래픽카드 판을 따로 받아야 한다(기본 저장소 것은 CPU 판이라 GPU 를 못 쓴다).
  # 이미 깔려 있고 cuda 가 붙어 있으면 다시 받지 않는다 — 2.5GB 를 아낀다.
  if "$VENV_STT/bin/python" -c "import torch, sys; sys.exit(0 if torch.version.cuda else 1)" >/dev/null 2>&1; then
    info "torch(cuda) 이미 있음: $("$VENV_STT/bin/python" -c 'import torch; print(torch.__version__)')"
  else
    info "torch 받는 중… ($TORCH_SPEC / $TORCH_INDEX) — 몇 분 걸린다"
    "$VENV_STT/bin/pip" install --quiet --index-url "$TORCH_INDEX" "$TORCH_SPEC"
  fi

  # 추론에 필요한 것만 적어 둔 목록. 학습용(datasets·accelerate)과 오디션용
  # (espnet·funasr)은 일부러 뺐다 — 시연 서버에는 학습을 올리지 않는다.
  "$VENV_STT/bin/pip" install --quiet -r "$SCRIPT_DIR/requirements-stt.txt"
  info "설치 완료 (requirements-stt.txt)"
}

# ── 6) 환경변수 파일 ─────────────────────────────────────────────────────────
# 왜 .env 가 아니라 systemd 환경변수 파일인가:
#   채점 서버 코드는 `load_dotenv(override=False)` 를 쓴다 — 즉 **이미 정해진
#   환경변수가 있으면 그것을 우선**한다. systemd 가 여기 적힌 값을 세워 주면
#   저장소 안에 열쇠가 든 .env 를 둘 필요가 없다. 열쇠와 코드를 떼어 놓는 것이다.
install_env_file() {
  say "6) 환경변수 파일"
  if [ -f "$ENV_FILE" ]; then
    # 사람이 채워 넣은 열쇠를 덮어쓰면 큰일이므로 절대 건드리지 않는다
    info "이미 있다 — 손대지 않는다: $ENV_FILE"
  else
    cp "$SCRIPT_DIR/env.template" "$ENV_FILE"
    warn "빈 템플릿을 복사했다. 열쇠를 채워야 서버가 제대로 돈다: $ENV_FILE"
  fi
  # 열쇠 파일은 이 계정만 읽게 잠근다
  chown "$SERVICE_USER:$SERVICE_USER" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
}

# ── 7) systemd 서비스 둘 ─────────────────────────────────────────────────────
# systemd 에 맡기는 까닭: 재부팅해도 알아서 켜지고, 죽으면 알아서 다시 뜬다.
# 시연 당일 아침에 사람이 창을 두 개 띄우는 지금 방식은 창을 닫으면 끝난다.
install_services() {
  say "7) 서비스 등록"
  install -m 644 "$SCRIPT_DIR/ktest-stt.service" /etc/systemd/system/ktest-stt.service
  install -m 644 "$SCRIPT_DIR/ktest-api.service" /etc/systemd/system/ktest-api.service
  systemctl daemon-reload
  systemctl enable ktest-stt.service ktest-api.service >/dev/null
  info "등록·자동시작 켬: ktest-stt(8100) · ktest-api(8001)"
}

# ── 8) 주인 바꾸기 ───────────────────────────────────────────────────────────
# 서비스 계정이 로그를 쓰고 모델을 캐시에 받아야 하므로 폴더 주인을 넘겨 준다.
fix_ownership() {
  say "8) 폴더 주인 정리"
  chown -R "$SERVICE_USER:$SERVICE_USER" "$KTEST_ROOT"
  info "$KTEST_ROOT 전체를 $SERVICE_USER 소유로"
}

# ── 9) 지금 상태 알려 주기 ───────────────────────────────────────────────────
# 여기서 서비스를 자동으로 켜지 않는 까닭: 열쇠와 어댑터가 아직 없을 수 있다.
# 그 상태로 켜면 서비스가 죽고 다시 뜨기를 반복해 로그만 지저분해진다.
report_next_steps() {
  say "차림 끝 — 다음에 할 일"

  # 어댑터가 제대로 풀렸는지는 이 파일 하나로 판단한다(peft 가 이것을 읽는다)
  local adapter_ready="아니오"
  if [ -f "$ADAPTER_DIR/adapter_config.json" ]; then
    adapter_ready="예"
  fi

  # 값이 비어 있지 않은 GEMINI_API_KEY 줄이 있는지만 본다(값 자체는 절대 안 찍는다)
  local key_ready="아니오"
  if grep -Eq '^GEMINI_API_KEY=.+' "$ENV_FILE" 2>/dev/null; then
    key_ready="예"
  fi

  printf '%s\n' \
    "  어댑터 준비됨? $adapter_ready   ($ADAPTER_DIR/adapter_config.json)" \
    "  열쇠 채워짐?   $key_ready   ($ENV_FILE)" \
    "" \
    "  아직 '아니오' 가 있으면 먼저 채운다:" \
    "    1) 어댑터:  tar -xzf ~/v2_adapter.tar.gz -C $ADAPTER_DIR" \
    "                푼 뒤 adapter_config.json 이 $ADAPTER_DIR 바로 밑에 보여야 한다." \
    "                (v2_adapter.tar.gz 는 안에 폴더가 한 겹 더 있을 수 있다 — 8/22 에" \
    "                 내 PC 에서 실제로 그랬다. 그러면 그 안쪽 폴더의 내용을 위로 옮긴다.)" \
    "                sudo chown -R $SERVICE_USER:$SERVICE_USER $KTEST_ROOT/adapters" \
    "    2) 열쇠:    sudo nano $ENV_FILE" \
    "" \
    "  둘 다 됐으면 켠다:" \
    "    sudo systemctl restart ktest-stt ktest-api" \
    "    bash $SCRIPT_DIR/healthcheck.sh" \
    "" \
    "  로그 보는 법:" \
    "    journalctl -u ktest-stt -f" \
    "    journalctl -u ktest-api -f"
}

main() {
  install_base_packages
  pick_python
  ensure_venv_module
  make_user_and_dirs
  fetch_repo
  make_venv_api
  make_venv_stt
  install_env_file
  install_services
  fix_ownership
  report_next_steps
}

main "$@"
