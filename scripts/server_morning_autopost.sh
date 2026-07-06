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
  exit 0
fi

git add _posts/ assets/images/ _state/zero-byte-images.txt _state/recent-url-quality.txt _state/translation_cache.json

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

echo "$LOG_PREFIX done $(date -u +%Y-%m-%dT%H:%M:%SZ)"
