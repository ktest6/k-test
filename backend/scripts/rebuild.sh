#!/usr/bin/env bash
set -euo pipefail

# 재빌드하면 컨테이너가 새로 만들어지면서 이전 컨테이너의 로그 파일이 통째로
# 사라진다(docker compose down/up이나 build 후 up 시 컨테이너 자체가 교체됨).
# 그래서 재빌드 직전에 지금 떠 있는 컨테이너의 로그를 파일로 스냅샷 떠 둔다.
#
# 사용법: backend 디렉토리(또는 이 스크립트가 있는 scripts/)에서
#   ./scripts/rebuild.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

LOG_DIR="logs"
mkdir -p "$LOG_DIR"

TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
LOG_FILE="$LOG_DIR/backup-$TIMESTAMP.log"

echo "[1/4] 재빌드 전 현재 컨테이너 로그 백업 -> $LOG_FILE"
docker compose logs --no-color --timestamps > "$LOG_FILE" 2>&1 || \
  echo "  경고: 로그 백업 실패(컨테이너가 아직 없을 수 있음) — 계속 진행합니다."

echo "[2/4] git pull"
git pull

echo "[3/4] 이미지 재빌드"
docker compose build

echo "[4/4] 컨테이너 재기동"
docker compose up -d

echo "완료. 백업된 이전 로그: $LOG_FILE"
