#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_SCRIPT="$REPO_ROOT/scripts/server_morning_autopost.sh"
LOG_FILE="$REPO_ROOT/_state/server-morning-autopost.log"

CRON_BEGIN="# BEGIN investing-morning-0910"
CRON_END="# END investing-morning-0910"
CRON_PATH="/opt/homebrew/bin:/opt/homebrew/sbin:/Users/namyongkim/.rbenv/shims:/Users/namyongkim/.local/bin:/usr/local/bin:/usr/bin:/bin"
CRON_LINE="10 9 * * * PATH=$CRON_PATH TZ=Asia/Seoul /bin/bash \"$RUN_SCRIPT\" >> \"$LOG_FILE\" 2>&1"

MODE="${1:-install}"

case "$MODE" in
  --uninstall|uninstall)
    EXISTING="$(crontab -l 2>/dev/null || true)"
    FILTERED="$(printf "%s\n" "$EXISTING" | awk -v b="$CRON_BEGIN" -v e="$CRON_END" '
      $0==b {skip=1; next}
      $0==e {skip=0; next}
      !skip {print}
    ')"
    printf "%s\n" "$FILTERED" | sed '/^[[:space:]]*$/N;/^\n$/D' | crontab -
    echo "[investing-cron] Uninstalled investing morning 09:10 cron schedule."
    exit 0
    ;;
  --status|status)
    echo "[investing-cron] Current cron status:"
    crontab -l 2>/dev/null | grep -A 2 "$CRON_BEGIN" || echo "Not currently installed in crontab."
    exit 0
    ;;
  --install|install)
    if [[ ! -f "$RUN_SCRIPT" ]]; then
      echo "Missing runner script: $RUN_SCRIPT" >&2
      exit 1
    fi

    mkdir -p "$REPO_ROOT/_state"

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

    echo "[investing-cron] Installed cron schedule (09:10 KST):"
    echo "$CRON_LINE"
    ;;
  *)
    echo "Usage: $0 [--install | --uninstall | --status]" >&2
    exit 1
    ;;
esac
