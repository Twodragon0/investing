#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_SCRIPT="$REPO_ROOT/scripts/server_morning_autopost.sh"
LOG_FILE="$REPO_ROOT/_state/server-morning-autopost.log"

if [[ ! -f "$RUN_SCRIPT" ]]; then
  echo "Missing runner script: $RUN_SCRIPT" >&2
  exit 1
fi

mkdir -p "$REPO_ROOT/_state"

CRON_BEGIN="# BEGIN investing-morning-0910"
CRON_END="# END investing-morning-0910"
CRON_LINE="10 9 * * * TZ=Asia/Seoul /bin/bash \"$RUN_SCRIPT\" >> \"$LOG_FILE\" 2>&1"

EXISTING="$(crontab -l 2>/dev/null || true)"

FILTERED="$(printf "%s\n" "$EXISTING" | awk -v b="$CRON_BEGIN" -v e="$CRON_END" '
  $0==b {skip=1; next}
  $0==e {skip=0; next}
  !skip {print}
')"

NEW_CRON="$FILTERED
$CRON_BEGIN
$CRON_LINE
$CRON_END"

printf "%s\n" "$NEW_CRON" | sed '/^[[:space:]]*$/N;/^\n$/D' | crontab -

echo "Installed cron schedule:"
echo "$CRON_LINE"
echo "Current crontab:"
crontab -l
