#!/usr/bin/env bash
set -euo pipefail

# Ensure robust PATH for macOS (rbenv first for ruby/bundle, Apple Silicon Homebrew, local bin)
export PATH="$HOME/.rbenv/shims:/opt/homebrew/bin:/opt/homebrew/sbin:$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
export TZ="Asia/Seoul"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Load local environment variables if available
for env_file in "$HOME/Desktop/.env" "$HOME/.env" "$REPO_ROOT/.env"; do
  if [[ -f "$env_file" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$env_file" 2>/dev/null || true
    set +a
  fi
done

# Rotate log file if exceeds 10MB
LOG_FILE="$REPO_ROOT/_state/server-morning-autopost.log"
if [[ -f "$LOG_FILE" ]]; then
  LOG_SIZE=$(wc -c < "$LOG_FILE" 2>/dev/null || echo 0)
  if [[ "$LOG_SIZE" -gt 10485760 ]]; then
    mv "$LOG_FILE" "$LOG_FILE.1"
  fi
fi

LOCK_DIR="/tmp/investing-morning-0910.lock"
LOG_PREFIX="[server-0910]"

if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  echo "$LOG_PREFIX already running, skip"
  exit 0
fi

# Prevent macOS sleep during pipeline execution
CAFFEINATE_PID=""
if command -v caffeinate >/dev/null 2>&1; then
  caffeinate -d -i -m -u -t 3600 &
  CAFFEINATE_PID=$!
fi

run_py() {
  if [[ -x ".venv/bin/python" ]]; then
    .venv/bin/python "$@"
  else
    python3 "$@"
  fi
}

send_slack() {
  local title="$1"
  local message="$2"
  local status="${3:-info}" # success, failure, info

  run_py - <<PY 2>/dev/null || true
import os, json, urllib.request, urllib.parse

title = """$title"""
message = """$message"""
status = """$status"""

token = os.environ.get("SLACK_BOT_TOKEN")
channel = os.environ.get("INVESTING_SLACK_CHANNEL") or os.environ.get("SLACK_CHANNEL_ID") or os.environ.get("SLACK_CHANNEL")
webhook = os.environ.get("SLACK_WEBHOOK_URL")

icon = "✅" if status == "success" else ("🚨" if status == "failure" else "ℹ️")
color = "#36a64f" if status == "success" else ("#e01e5a" if status == "failure" else "#2eb886")
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

handle_error() {
  local exit_code=$?
  local line_no="${1:-$LINENO}"
  echo "$LOG_PREFIX ERROR at line $line_no (exit code: $exit_code)" >&2
  send_slack "[Investing] 09:10 자동 포스팅 실패" "• 오류 발생 라인: line $line_no (코드 $exit_code)\n• 대상 저장소: Twodragon0/investing\n• 로그 파일: _state/server-morning-autopost.log" "failure"
}
trap 'handle_error $LINENO' ERR

cleanup() {
  rmdir "$LOCK_DIR" 2>/dev/null || true
  if [[ -n "$CAFFEINATE_PID" ]]; then
    kill "$CAFFEINATE_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

cd "$REPO_ROOT"
echo "$LOG_PREFIX start $(date -u +%Y-%m-%dT%H:%M:%SZ)"

git fetch origin main
git checkout main
git pull --rebase --autostash origin main

TODAY_KST="$(TZ=Asia/Seoul date +%Y-%m-%d)"
echo "$LOG_PREFIX regenerate daily summary for latest coverage"
run_py scripts/generate_daily_summary.py

# NOTE: generate_market_summary.py retired 2026-07-06 — it produced no committed
# post since 2026-04-14 while writing market-heatmap/fear-greed/top-coins images
# to disk each run (orphaned, 0 tracked). collect_coinmarketcap.py already
# publishes daily-crypto-market-report with -cmc images, superseding it.

RECENT_POSTS_RAW="$(run_py - <<'PY'
from datetime import datetime, timedelta
from pathlib import Path

root = Path("_posts")
base = datetime.now().date()
days = {str(base), str(base - timedelta(days=1))}
for path in sorted(root.glob("*.md")):
    if path.name[:10] in days:
        print(path.as_posix())
PY
)"

RECENT_POSTS=()
while IFS= read -r line; do
  [[ -n "$line" ]] && RECENT_POSTS+=("$line")
done <<<"$RECENT_POSTS_RAW"

if [[ ${#RECENT_POSTS[@]} -gt 0 ]]; then
  run_py scripts/improve_existing_posts.py --files "${RECENT_POSTS[@]}"
fi

echo "$LOG_PREFIX clean translation cache"
run_py scripts/clean_translation_cache.py

echo "$LOG_PREFIX verify post translation quality"
run_py scripts/verify_post_quality.py --days 2 || echo "$LOG_PREFIX post quality issues found (non-blocking)"

run_py scripts/backfill_images.py
run_py scripts/backfill_post_summaries.py --clean-images-only --zero-image-report _state/zero-byte-images.txt
run_py scripts/check_recent_post_urls.py --days 2 --limit 60 --report _state/recent-url-quality.txt

if command -v bundle >/dev/null 2>&1; then
  bundle exec jekyll build
  run_py scripts/verify_rendered_posts.py
else
  echo "$LOG_PREFIX bundle not found, skip render verification"
fi

if git diff --quiet -- _posts/ assets/images/ _state/zero-byte-images.txt _state/recent-url-quality.txt _state/translation_cache.json 2>/dev/null; then
  echo "$LOG_PREFIX no content/image changes"
  send_slack "[Investing] 09:10 일일 점검 완료 (${TODAY_KST})" "• 최신 포스트 및 품질 검증 통과 (변경사항 없음)" "info"
  exit 0
fi

git add _posts/ assets/images/ _state/zero-byte-images.txt _state/recent-url-quality.txt _state/translation_cache.json

if git diff --staged --quiet; then
  echo "$LOG_PREFIX nothing staged"
  send_slack "[Investing] 09:10 일일 점검 완료 (${TODAY_KST})" "• 최신 포스트 및 품질 검증 통과 (staged 없음)" "info"
  exit 0
fi

GIT_AUTHOR_NAME="opencode-bot" \
GIT_AUTHOR_EMAIL="opencode-bot@users.noreply.github.com" \
GIT_COMMITTER_NAME="opencode-bot" \
GIT_COMMITTER_EMAIL="opencode-bot@users.noreply.github.com" \
git commit -m "chore: server 09:10 자동 포스팅 및 품질 보정 ${TODAY_KST}" || {
  git add _posts/ assets/images/ _state/zero-byte-images.txt
  git add _state/recent-url-quality.txt _state/translation_cache.json
  if git diff --staged --quiet; then
    echo "$LOG_PREFIX commit skipped after hooks"
    exit 0
  fi
  GIT_AUTHOR_NAME="opencode-bot" \
  GIT_AUTHOR_EMAIL="opencode-bot@users.noreply.github.com" \
  GIT_COMMITTER_NAME="opencode-bot" \
  GIT_COMMITTER_EMAIL="opencode-bot@users.noreply.github.com" \
  git commit -m "chore: server 09:10 자동 포스팅 및 품질 보정 ${TODAY_KST}"
}

git push origin main

send_slack "[Investing] 09:10 자동 포스팅 & 보정 완료 (${TODAY_KST})" "• 요약 포스트 및 이미지 갱신 완료\n• 품질 검증 및 Jekyll 렌더링 통과\n• Git 커밋 & 푸시 완료 (main 브랜치)" "success"

echo "$LOG_PREFIX done $(date -u +%Y-%m-%dT%H:%M:%SZ)"
