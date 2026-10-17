#!/usr/bin/env bash
set -euo pipefail

# Ensure robust HOME and PATH for macOS (launchd, cron, terminal)
export HOME="${HOME:-/Users/namyongkim}"
export PATH="$HOME/.rbenv/shims:/opt/homebrew/bin:/opt/homebrew/sbin:$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
export TZ="Asia/Seoul"

DRY_RUN=false
LIMIT=50
DAYS=365

for arg in "$@"; do
  case "$arg" in
    --dry-run|-n)
      DRY_RUN=true
      ;;
    --limit=*)
      LIMIT="${arg#*=}"
      ;;
    --days=*)
      DAYS="${arg#*=}"
      ;;
  esac
done

# Resolve repository root
if [[ -n "${INVESTING_REPO_ROOT:-}" && -d "${INVESTING_REPO_ROOT}/.git" ]]; then
  REPO_ROOT="$INVESTING_REPO_ROOT"
elif [[ -d "$HOME/investing/.git" ]]; then
  REPO_ROOT="$HOME/investing"
elif [[ -d "$HOME/Desktop/investing/.git" ]]; then
  REPO_ROOT="$HOME/Desktop/investing"
else
  REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fi

# Load local environment variables if available
for env_file in "$HOME/Desktop/.env" "$HOME/.env" "$REPO_ROOT/.env" "$HOME/.investing-runtime/.env"; do
  if [[ -f "$env_file" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$env_file" 2>/dev/null || true
    set +a
  fi
done

LOCK_DIR="${INVESTING_ARCHIVE_LOCK_DIR:-/tmp/investing-archive-backfill.lock}"
LOG_PREFIX="[archive-backfill]"

if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  echo "$LOG_PREFIX already running, skip"
  exit 0
fi

cleanup() {
  rmdir "$LOCK_DIR" 2>/dev/null || true
}
trap cleanup EXIT

run_py() {
  if [[ -x "$REPO_ROOT/.venv/bin/python" ]]; then
    "$REPO_ROOT/.venv/bin/python" "$@"
  elif [[ -x ".venv/bin/python" ]]; then
    .venv/bin/python "$@"
  else
    python3 "$@"
  fi
}

send_slack() {
  local title="$1"
  local message="$2"
  local status="${3:-info}"

  run_py - <<PY 2>/dev/null || true
import os, json, urllib.request, urllib.parse

title = """$title"""
message = """$message"""
status = """$status"""

token = os.environ.get("SLACK_BOT_TOKEN")
channel = os.environ.get("INVESTING_SLACK_CHANNEL") or os.environ.get("SLACK_CHANNEL_ID") or os.environ.get("SLACK_CHANNEL")
webhook = os.environ.get("SLACK_WEBHOOK_URL")

icon = "✅" if status == "success" else ("🚨" if status == "failure" else "ℹ️")
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
  send_slack "[Investing] 과거 아카이브 블러브 백필 실패" "• 오류 발생 라인: line $line_no (코드 $exit_code)\n• 대상 저장소: Twodragon0/investing" "failure"
}
trap 'handle_error $LINENO' ERR

cd "$REPO_ROOT"
echo "$LOG_PREFIX start $(date -u +%Y-%m-%dT%H:%M:%SZ)"

# Pull latest commits cleanly
git rebase --abort 2>/dev/null || true
git merge --abort 2>/dev/null || true
git fetch origin main
git pull --rebase --autostash origin main

echo "$LOG_PREFIX executing fix_post_url_summaries --days $DAYS --limit $LIMIT"
if [[ "$DRY_RUN" == "true" ]]; then
  run_py scripts/fix_post_url_summaries.py --days "$DAYS" --limit "$LIMIT"
  echo "$LOG_PREFIX [DRY-RUN] completed without applying changes"
  exit 0
fi

OUTPUT=$(run_py scripts/fix_post_url_summaries.py --days "$DAYS" --limit "$LIMIT" --apply)
echo "$OUTPUT"

if git diff --quiet -- _posts/ _state/translation_cache.json 2>/dev/null; then
  echo "$LOG_PREFIX no blurb changes"
  exit 0
fi

git add _posts/ _state/translation_cache.json

if git diff --staged --quiet; then
  echo "$LOG_PREFIX nothing staged"
  exit 0
fi

TODAY_KST="$(TZ=Asia/Seoul date +%Y-%m-%d)"
GIT_AUTHOR_NAME="opencode-bot" \
GIT_AUTHOR_EMAIL="opencode-bot@users.noreply.github.com" \
GIT_COMMITTER_NAME="opencode-bot" \
GIT_COMMITTER_EMAIL="opencode-bot@users.noreply.github.com" \
git commit -m "chore: archive blurb backfill ${DAYS}d (limit ${LIMIT}) ${TODAY_KST}"

MAX_RETRIES=5
for i in $(seq 1 $MAX_RETRIES); do
  echo "$LOG_PREFIX push attempt $i/$MAX_RETRIES"
  if git push origin main 2>&1; then
    echo "$LOG_PREFIX push succeeded"
    break
  fi
  if [[ "$i" -eq "$MAX_RETRIES" ]]; then
    echo "$LOG_PREFIX push failed after $MAX_RETRIES attempts" >&2
    exit 1
  fi
  sleep $((i * 3))
  git fetch origin main
  git rebase origin main || {
    git checkout --ours _state/*.json 2>/dev/null || true
    git add _state/*.json 2>/dev/null || true
    git rebase --continue 2>/dev/null || { git rebase --abort; exit 1; }
  }
done

send_slack "[Investing] 과거 아카이브 블러브 백필 완료 (${TODAY_KST})" "• 과거 ${DAYS}일 포스트 블러브 정밀 개선 (배치 한도: ${LIMIT}건)\n• Git 커밋 & 푸시 완료 (main 브랜치)" "success"
echo "$LOG_PREFIX done $(date -u +%Y-%m-%dT%H:%M:%SZ)"
