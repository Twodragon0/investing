#!/usr/bin/env bash
set -euo pipefail

# Ensure robust PATH for macOS
export PATH="$HOME/.rbenv/shims:/opt/homebrew/bin:/opt/homebrew/sbin:$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
export TZ="Asia/Seoul"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

# Load local environment variables
for env_file in "$HOME/Desktop/.env" "$HOME/.env" "$REPO_ROOT/.env"; do
  if [[ -f "$env_file" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$env_file" 2>/dev/null || true
    set +a
  fi
done

run_py() {
  if [[ -x ".venv/bin/python" ]]; then
    .venv/bin/python "$@"
  else
    python3 "$@"
  fi
}

send_slack_alert() {
  local title="$1"
  local message="$2"
  local status="${3:-warning}"

  run_py - <<PY 2>/dev/null || true
import os, json, urllib.request, urllib.parse

title = """$title"""
message = """$message"""
status = """$status"""

token = os.environ.get("SLACK_BOT_TOKEN")
channel = os.environ.get("INVESTING_SLACK_CHANNEL") or os.environ.get("SLACK_CHANNEL_ID") or os.environ.get("SLACK_CHANNEL")
webhook = os.environ.get("SLACK_WEBHOOK_URL")

icon = "⚠️" if status == "warning" else ("🚨" if status == "error" else "ℹ️")
color = "#ecb22e" if status == "warning" else ("#e01e5a" if status == "error" else "#2eb886")
full_text = f"{icon} *{title}*\n{message}"

if webhook:
    payload = json.dumps({"text": full_text}).encode("utf-8")
    req = urllib.request.Request(webhook, data=payload, headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=10)
elif token and channel:
    payload = urllib.parse.urlencode({"channel": channel, "text": full_text}).encode("utf-8")
    req = urllib.request.Request(
        "https://slack.com/api/chat.postMessage",
        data=payload,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/x-www-form-urlencoded"}
    )
    urllib.request.urlopen(req, timeout=10)
PY
}

echo "=================================================="
echo " [Investing] Disk & Log Health Check"
echo " Time: $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo "=================================================="

# 1. Check Disk Usage
DISK_INFO="$(df -h "$REPO_ROOT" | awk 'NR==2 {print $5, $4, $2}')"
DISK_USAGE_PCT="$(echo "$DISK_INFO" | awk '{print $1}' | tr -d '%')"
DISK_AVAIL="$(echo "$DISK_INFO" | awk '{print $2}')"
DISK_TOTAL="$(echo "$DISK_INFO" | awk '{print $3}')"

echo "• Disk Usage: ${DISK_USAGE_PCT}% (Free: ${DISK_AVAIL} / Total: ${DISK_TOTAL})"

if [[ "$DISK_USAGE_PCT" -ge 85 ]]; then
  echo "  [WARNING] Disk usage exceeds 85%!"
  send_slack_alert "[Investing] 맥미니 디스크 용량 경고 (${DISK_USAGE_PCT}%)" "• 사용량: ${DISK_USAGE_PCT}% (여유: ${DISK_AVAIL} / 전체: ${DISK_TOTAL})\n• 확인 및 정리 필요: $REPO_ROOT" "warning"
fi

# 2. Check and Rotate Log Files in _state
LOG_DIR="$REPO_ROOT/_state"
ROTATED_COUNT=0

if [[ -d "$LOG_DIR" ]]; then
  for log_file in "$LOG_DIR"/*.log; do
    if [[ -f "$log_file" ]]; then
      LOG_SIZE=$(wc -c < "$log_file" 2>/dev/null || echo 0)
      # Rotate if > 10MB
      if [[ "$LOG_SIZE" -gt 10485760 ]]; then
        mv "$log_file" "${log_file}.1"
        echo "• Rotated oversized log: $(basename "$log_file") (${LOG_SIZE} bytes)"
        ROTATED_COUNT=$((ROTATED_COUNT + 1))
      fi
    fi
  done
fi
echo "• Log rotation check complete (Rotated: $ROTATED_COUNT files)"

# 3. Check Generated Images Directory
IMG_DIR="$REPO_ROOT/assets/images/generated"
if [[ -d "$IMG_DIR" ]]; then
  IMG_COUNT=$(find "$IMG_DIR" -type f | wc -l | tr -d ' ')
  IMG_SIZE=$(du -sh "$IMG_DIR" | awk '{print $1}')
  echo "• Generated Images: $IMG_COUNT files ($IMG_SIZE)"
else
  echo "• Generated Images directory not found: $IMG_DIR"
fi

# 4. Check LaunchAgent Status
LABEL="com.twodragon.investing-morning-autopost"
LAUNCHD_STATUS="$(launchctl list | grep "$LABEL" || true)"
if [[ -n "$LAUNCHD_STATUS" ]]; then
  echo "• LaunchAgent ($LABEL): Active (Status: $LAUNCHD_STATUS)"
else
  echo "• LaunchAgent ($LABEL): [WARNING] Not currently loaded in launchctl!"
  send_slack_alert "[Investing] 맥미니 LaunchAgent 비활성화 알림" "• 서비스: $LABEL\n• launchctl에 로드되어 있지 않습니다. 확인이 필요합니다." "error"
fi

# 5. Check for orphaned atomic-write temp files in _state
# 원자적 쓰기(`mkstemp` → `os.replace`)의 temp 는 밀리초만 존재한다. 남아 있으면
# rename 전에 프로세스가 죽은 것이다 — 2026-09-07 에 translator 캐시 저장이 ~900KB
# 4개를 흘렸다(#1284 에서 finally 정리 추가). 원인은 닫혔지만, 다음 writer 가 정리
# 없는 early-return 을 만들면 같은 방식으로 새고 아무도 보지 않는다.
#
# exit 1 은 "고아 발견" 이라 `set -e` 에 걸린다. 헬스체크는 발견을 보고하고 계속
# 진행해야 하므로 종료 코드를 명시적으로 받는다. 도구는 삭제하지 않는다 — 페이로드가
# 다른 프로세스가 아직 들고 있을 수 있는 상태 파일의 부분 사본이다.
#
# 종료 코드는 별도 문장으로 받는다. `cmd && a=0 || b=$?` 는 `$?` 가 실패한 대입의
# 상태를 가리켜 값이 모호해진다.
set +e
ORPHAN_REPORT="$(run_py scripts/tools/check_state_orphans.py 2>/dev/null)"
ORPHAN_RC=$?
set -e
echo "$ORPHAN_REPORT"
if [[ "$ORPHAN_RC" -ne 0 ]]; then
  send_slack_alert "[Investing] _state 고아 temp 파일 감지" "$ORPHAN_REPORT" "warning"
fi

echo "=================================================="
echo " Health check completed successfully."
echo "=================================================="
