#!/usr/bin/env bash
# ============================================================================
# 시연 서버 두 대가 진짜 살아 있는지 확인한다.
#
# 왜 필요한가
#   `systemctl status` 는 "프로그램이 켜져 있다"까지만 알려 준다. 우리에게 중요한 건
#   **채점이 실제로 되는 상태인가**다. 특히 받아쓰기는 채점 서버가 주소만 알지
#   그 서버가 답하는지는 모른다 — 그래서 채점 서버 /health 의 `stt_available` 을
#   본다. 이 값이 false 면 말하기 채점이 전부 503 이 된다.
#
# 쓰는 법
#   bash healthcheck.sh                    (VM 안에서, 기본 주소로)
#   bash healthcheck.sh http://34.x.x.x:8001
#                                          (내 노트북에서 바깥 주소로 — 이때
#                                           8100 은 안 열려 있으므로 건너뛴다)
#
# 끝나고 나오는 값
#   0 = 다 정상 / 1 = 어딘가 문제 (다른 스크립트가 이 값으로 판단할 수 있게)
# ============================================================================

set -uo pipefail   # -e 는 일부러 안 쓴다: 한 군데 실패해도 나머지를 마저 확인해야 한다

API_URL="${1:-http://127.0.0.1:8001}"
STT_URL="${2:-http://127.0.0.1:8100}"

# 문제가 하나라도 있었는지 기억해 두는 표시
PROBLEM=0

# JSON 에서 값 하나를 꺼낸다. 파이썬 없이 grep 만으로 한다
# (VM 마다 jq 가 있을지 없을지 모르므로 있는 것만 쓴다).
field() {
  local json="$1" key="$2"
  printf '%s' "$json" \
    | grep -oE "\"$key\"[[:space:]]*:[[:space:]]*(\"[^\"]*\"|true|false|null|[0-9.]+)" \
    | head -1 \
    | sed -E "s/\"$key\"[[:space:]]*:[[:space:]]*//; s/^\"//; s/\"$//"
}

echo "=================================================="
echo " K-TEST 시연 서버 상태 확인"
echo " 채점 서버 : $API_URL"
echo " 받아쓰기  : $STT_URL"
echo "=================================================="

# ── 1) 받아쓰기 서버(8100) ──────────────────────────────────────────────────
# 먼저 확인하는 까닭: 채점 서버의 stt_available 이 false 로 나왔을 때
# "여기가 원인이었다"를 바로 알 수 있게 순서를 맞춘 것이다.
echo
echo "[1] 받아쓰기 서버 (8100)"
# -f: 4xx·5xx 도 실패로 친다   -m 5: 5초 안에 답 없으면 포기
STT_JSON="$(curl -fsS -m 5 "$STT_URL/health" 2>/dev/null || true)"
if [ -z "$STT_JSON" ]; then
  echo "  X 답이 없다. 꺼져 있거나 아직 모델을 불러오는 중이다."
  echo "    확인:  sudo systemctl status ktest-stt"
  echo "           journalctl -u ktest-stt -n 50"
  echo "    (바깥 주소로 돌렸다면 정상이다 — 8100 은 일부러 안 열어 두었다)"
  PROBLEM=1
else
  echo "  응답: $STT_JSON"
  echo "  model_loaded = $(field "$STT_JSON" model_loaded)"
  echo "  device       = $(field "$STT_JSON" device)"
  # device 가 cpu 면 그래픽카드를 못 쓰고 있다는 뜻이다. 돌기는 하지만 몇 배 느리다
  if [ "$(field "$STT_JSON" device)" = "cpu" ]; then
    echo "  [주의] GPU 가 아니라 CPU 로 돌고 있다. 받아쓰기가 몇 배 느려진다."
    echo "         확인:  nvidia-smi  /  venv-stt 의 torch 가 cuda 판인지"
    PROBLEM=1
  fi
fi

# ── 1-2) 소리 형식 변환기(ffmpeg) ───────────────────────────────────────────
# 왜 보나: 응시자 음성은 브라우저 녹음(webm)으로 들어오는데 받아쓰기·발음 평가는
# wav 만 읽는다. 채점 서버가 입구에서 ffmpeg 로 바꾸므로, 이게 없으면
# 말하기 채점이 전부 503 이 된다(쓰기는 영향 없다).
echo
echo "[1-2] 소리 형식 변환기 (ffmpeg)"
if ffmpeg -version >/dev/null 2>&1; then
  echo "  $(ffmpeg -version 2>/dev/null | head -1)"
else
  echo "  X ffmpeg 이 없다 -> webm 녹음은 말하기 채점이 전부 503 이 된다."
  echo "    고치기:  sudo apt-get install -y ffmpeg"
  PROBLEM=1
fi

# ── 2) 채점 서버(8001) ──────────────────────────────────────────────────────
echo
echo "[2] 채점 서버 (8001)"
API_JSON="$(curl -fsS -m 10 "$API_URL/health" 2>/dev/null || true)"
if [ -z "$API_JSON" ]; then
  echo "  X 답이 없다."
  echo "    확인:  sudo systemctl status ktest-api"
  echo "           journalctl -u ktest-api -n 50"
  PROBLEM=1
else
  echo "  scoring_version = $(field "$API_JSON" scoring_version)"
  echo "  llm_available   = $(field "$API_JSON" llm_available)   (false 면 Gemini 열쇠 문제)"
  echo "  stt_provider    = $(field "$API_JSON" stt_provider)"
  echo "  stt_available   = $(field "$API_JSON" stt_available)"
  echo "  stt_detail      = $(field "$API_JSON" stt_detail)   (정상이면 null)"
  echo "  ffmpeg_available = $(field "$API_JSON" ffmpeg_available)   (false 면 webm 답안이 전부 503)"
  echo "  auth_enabled    = $(field "$API_JSON" auth_enabled)   (true 면 X-API-Key 필요)"

  # 여기가 이 스크립트의 핵심이다. 이 값이 false 면 말하기 채점이 전부 503 이다
  if [ "$(field "$API_JSON" stt_available)" != "true" ]; then
    echo
    echo "  [문제] 받아쓰기를 못 쓴다 -> 말하기 채점이 전부 503 이 된다."
    echo "         (쓰기 채점은 영향 없다)"
    echo "         이유는 위의 stt_detail 에 한 문장으로 적혀 있다."
    PROBLEM=1
  fi
  if [ "$(field "$API_JSON" llm_available)" != "true" ]; then
    echo
    echo "  [문제] Gemini 를 못 쓴다 -> 체크리스트·오류 자질이 안 나와 채점이 껍데기가 된다."
    echo "         ktest.env 의 GEMINI_API_KEY 를 확인한다."
    PROBLEM=1
  fi
fi

# ── 마무리 ──────────────────────────────────────────────────────────────────
echo
echo "=================================================="
if [ "$PROBLEM" -eq 0 ]; then
  echo " 다 정상. 백엔드에 줄 주소: $API_URL"
else
  echo " 문제가 있다. 위의 [문제]·[주의] 줄을 보라."
fi
echo "=================================================="
exit "$PROBLEM"
