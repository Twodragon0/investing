#!/usr/bin/env bash
# install_external_watchdog.sh — installs external_watchdog.sh on an external server
# and sets up a crontab entry for every-5-minute execution.
#
# Usage:
#   bash install_external_watchdog.sh [INSTALL_DIR]          # install (default: /usr/local/bin)
#   bash install_external_watchdog.sh [INSTALL_DIR] --uninstall  # remove
#
# INSTALL_DIR can also be set via the first positional arg, e.g.:
#   bash install_external_watchdog.sh ~/bin

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_SCRIPT="$SCRIPT_DIR/external_watchdog.sh"

INSTALL_DIR="${1:-/usr/local/bin}"
UNINSTALL=false
if [ "${2:-}" = "--uninstall" ] || [ "${1:-}" = "--uninstall" ]; then
  UNINSTALL=true
  # If first arg is --uninstall, reset install dir to default
  if [ "${1:-}" = "--uninstall" ]; then
    INSTALL_DIR="/usr/local/bin"
  fi
fi

INSTALLED_SCRIPT="$INSTALL_DIR/external_watchdog.sh"
CONFIG_FILE="/etc/default/external_watchdog"
LOG_FILE="/var/log/external_watchdog.log"
CRON_MARK="# external-watchdog-layer4"

log() {
  printf "[install_external_watchdog] %s\n" "$*"
}

# ---------------------------------------------------------------------------
# Uninstall mode
# ---------------------------------------------------------------------------
if [ "$UNINSTALL" = "true" ]; then
  log "Uninstalling external_watchdog..."

  if [ -f "$INSTALLED_SCRIPT" ]; then
    rm -f "$INSTALLED_SCRIPT"
    log "Removed $INSTALLED_SCRIPT"
  else
    log "Script not found at $INSTALLED_SCRIPT (already removed?)"
  fi

  # Remove crontab entry
  EXISTING_CRON="$(crontab -l 2>/dev/null || true)"
  FILTERED_CRON="$(printf "%s\n" "$EXISTING_CRON" | grep -v "$CRON_MARK" | grep -v "external_watchdog.sh" || true)"
  printf "%s\n" "$FILTERED_CRON" | crontab -
  log "Removed crontab entry"

  log "Uninstall complete."
  log "Config file at $CONFIG_FILE was NOT removed — remove manually if desired."
  exit 0
fi

# ---------------------------------------------------------------------------
# Install mode
# ---------------------------------------------------------------------------
if [ ! -f "$SOURCE_SCRIPT" ]; then
  log "ERROR: source script not found: $SOURCE_SCRIPT"
  exit 1
fi

# Create install dir if needed
if [ ! -d "$INSTALL_DIR" ]; then
  mkdir -p "$INSTALL_DIR"
  log "Created directory: $INSTALL_DIR"
fi

# Copy and make executable
cp "$SOURCE_SCRIPT" "$INSTALLED_SCRIPT"
chmod 755 "$INSTALLED_SCRIPT"
log "Installed: $INSTALLED_SCRIPT"

# ---------------------------------------------------------------------------
# Create config file template if absent
# ---------------------------------------------------------------------------
if [ ! -f "$CONFIG_FILE" ]; then
  # Only attempt to write to /etc if we have permission
  if touch "$CONFIG_FILE" 2>/dev/null; then
    cat > "$CONFIG_FILE" <<'EOF'
# /etc/default/external_watchdog — sourced by external_watchdog.sh
# Protect this file: sudo chmod 600 /etc/default/external_watchdog
#                    sudo chown root:root /etc/default/external_watchdog

# Required
GITHUB_TOKEN="ghp_xxxxxxxxxxxxxxxxxxxx"
GITHUB_REPO="Twodragon0/investing"
SLACK_WEBHOOK_URL="https://hooks.slack.com/services/XXX/YYY/ZZZ"

# Optional (defaults shown)
WATCHDOG_WORKFLOW_FILE="watchdog-zero-job-runs.yml"
ALERT_THRESHOLD_MINUTES="15"
DEDUP_FILE="/var/log/external_watchdog_last_alert.txt"
DEDUP_COOLDOWN_SECONDS="3600"
EOF
    chmod 600 "$CONFIG_FILE"
    log "Created config template: $CONFIG_FILE (chmod 600)"
  else
    log "WARN: cannot write to $CONFIG_FILE (run as root to create it)"
    log "      Creating local fallback template instead at ./external_watchdog.env"
    cat > "./external_watchdog.env" <<'EOF'
GITHUB_TOKEN="ghp_xxxxxxxxxxxxxxxxxxxx"
GITHUB_REPO="Twodragon0/investing"
SLACK_WEBHOOK_URL="https://hooks.slack.com/services/XXX/YYY/ZZZ"
WATCHDOG_WORKFLOW_FILE="watchdog-zero-job-runs.yml"
ALERT_THRESHOLD_MINUTES="15"
EOF
    log "      Edit ./external_watchdog.env, then move to $CONFIG_FILE as root."
  fi
else
  log "Config file already exists: $CONFIG_FILE (not overwritten)"
fi

# ---------------------------------------------------------------------------
# Idempotent crontab install
# ---------------------------------------------------------------------------
CRON_LINE="*/5 * * * * $INSTALLED_SCRIPT >> $LOG_FILE 2>&1 $CRON_MARK"

EXISTING_CRON="$(crontab -l 2>/dev/null || true)"

# Remove any previous entry for this script
FILTERED_CRON="$(printf "%s\n" "$EXISTING_CRON" | grep -v "$CRON_MARK" | grep -v "external_watchdog.sh" || true)"

# Append new entry
NEW_CRON="${FILTERED_CRON}
${CRON_LINE}"

printf "%s\n" "$NEW_CRON" | sed '/^[[:space:]]*$/N;/^\n$/d' | crontab -

log "Crontab entry installed:"
log "  $CRON_LINE"

# ---------------------------------------------------------------------------
# Final instructions
# ---------------------------------------------------------------------------
cat <<INSTRUCTIONS

======================================================================
 external_watchdog (Layer 4) 설치 완료
======================================================================

1. 환경 변수 설정 (root 권한 필요):
   sudo nano $CONFIG_FILE

   필수 항목:
     GITHUB_TOKEN       — actions:read 권한을 가진 read-only PAT
     GITHUB_REPO        — 예: Twodragon0/investing
     SLACK_WEBHOOK_URL  — 인커밍 웹훅 URL (Slack 앱에서 생성)

2. 파일 권한 확인:
   sudo chown root:root $CONFIG_FILE
   sudo chmod 600 $CONFIG_FILE

3. 동작 확인:
   $INSTALLED_SCRIPT
   tail -f $LOG_FILE

4. 크론탭 확인:
   crontab -l | grep watchdog

5. 제거:
   bash $(basename "${BASH_SOURCE[0]}") --uninstall
======================================================================
INSTRUCTIONS
