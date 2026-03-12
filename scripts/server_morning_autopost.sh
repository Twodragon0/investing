#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCK_DIR="/tmp/investing-morning-0910.lock"
LOG_PREFIX="[server-0910]"

if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  echo "$LOG_PREFIX already running, skip"
  exit 0
fi
trap 'rmdir "$LOCK_DIR" 2>/dev/null || true' EXIT

cd "$REPO_ROOT"

echo "$LOG_PREFIX start $(date -u +%Y-%m-%dT%H:%M:%SZ)"

run_py() {
  if [[ -x ".venv/bin/python" ]]; then
    .venv/bin/python "$@"
  else
    python3 "$@"
  fi
}

git fetch origin main
git checkout main
git pull --rebase --autostash origin main

TODAY_KST="$(TZ=Asia/Seoul date +%Y-%m-%d)"
SUMMARY_POST="_posts/${TODAY_KST}-daily-news-summary.md"
MARKET_POST="_posts/${TODAY_KST}-daily-market-report.md"

if [[ ! -f "$SUMMARY_POST" ]]; then
  echo "$LOG_PREFIX daily summary missing, generate"
  run_py scripts/generate_daily_summary.py
else
  echo "$LOG_PREFIX daily summary exists, skip generation"
fi

if [[ ! -f "$MARKET_POST" ]]; then
  echo "$LOG_PREFIX market summary missing, generate"
  run_py scripts/generate_market_summary.py
else
  echo "$LOG_PREFIX market summary exists, skip generation"
fi

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

run_py scripts/backfill_images.py
run_py scripts/backfill_post_summaries.py --clean-images-only --zero-image-report _state/zero-byte-images.txt

if command -v bundle >/dev/null 2>&1; then
  bundle exec jekyll build
  run_py scripts/verify_rendered_posts.py
else
  echo "$LOG_PREFIX bundle not found, skip render verification"
fi

if git diff --quiet -- _posts/ assets/images/ _state/zero-byte-images.txt 2>/dev/null; then
  echo "$LOG_PREFIX no content/image changes"
  exit 0
fi

git add _posts/ assets/images/ _state/zero-byte-images.txt

if git diff --staged --quiet; then
  echo "$LOG_PREFIX nothing staged"
  exit 0
fi

GIT_AUTHOR_NAME="opencode-bot" \
GIT_AUTHOR_EMAIL="opencode-bot@users.noreply.github.com" \
GIT_COMMITTER_NAME="opencode-bot" \
GIT_COMMITTER_EMAIL="opencode-bot@users.noreply.github.com" \
git commit -m "chore: server 09:10 자동 포스팅 및 품질 보정 ${TODAY_KST}" || {
  git add _posts/ assets/images/ _state/zero-byte-images.txt
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

echo "$LOG_PREFIX done $(date -u +%Y-%m-%dT%H:%M:%SZ)"
