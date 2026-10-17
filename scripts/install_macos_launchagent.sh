#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLIST_NAME="com.twodragon.investing-morning-autopost.plist"
SOURCE_PLIST="$REPO_ROOT/scripts/launchd/$PLIST_NAME"
TARGET_DIR="$HOME/Library/LaunchAgents"
TARGET_PLIST="$TARGET_DIR/$PLIST_NAME"
LABEL="com.twodragon.investing-morning-autopost"
RUNTIME_DIR="$HOME/.investing-runtime"
LOG_FILE="$HOME/Library/Logs/investing-morning-autopost.log"

ARCHIVE_PLIST_NAME="com.twodragon.investing-archive-backfill.plist"
ARCHIVE_SOURCE_PLIST="$REPO_ROOT/scripts/launchd/$ARCHIVE_PLIST_NAME"
ARCHIVE_TARGET_PLIST="$TARGET_DIR/$ARCHIVE_PLIST_NAME"
ARCHIVE_LABEL="com.twodragon.investing-archive-backfill"
ARCHIVE_LOG_FILE="$HOME/Library/Logs/investing-archive-backfill.log"

MODE="${1:---install}"

case "$MODE" in
  --uninstall|uninstall)
    echo "[launchd] Unloading $LABEL..."
    launchctl bootout "gui/$UID/$LABEL" 2>/dev/null || launchctl unload "$TARGET_PLIST" 2>/dev/null || true
    rm -f "$TARGET_PLIST"
    echo "[launchd] Unloading $ARCHIVE_LABEL..."
    launchctl bootout "gui/$UID/$ARCHIVE_LABEL" 2>/dev/null || launchctl unload "$ARCHIVE_TARGET_PLIST" 2>/dev/null || true
    rm -f "$ARCHIVE_TARGET_PLIST"
    echo "[launchd] Successfully uninstalled $LABEL and $ARCHIVE_LABEL"
    ;;

  --status|status)
    echo "[launchd] Checking status for $LABEL:"
    launchctl list | grep "$LABEL" || echo "Service $LABEL is not loaded."
    if [[ -f "$LOG_FILE" ]]; then
      echo "=== Morning Autopost Log (tail -n 5) ==="
      tail -n 5 "$LOG_FILE"
    fi

    echo ""
    echo "[launchd] Checking status for $ARCHIVE_LABEL:"
    launchctl list | grep "$ARCHIVE_LABEL" || echo "Service $ARCHIVE_LABEL is not loaded."
    if [[ -f "$ARCHIVE_LOG_FILE" ]]; then
      echo "=== Archive Backfill Log (tail -n 5) ==="
      tail -n 5 "$ARCHIVE_LOG_FILE"
    fi
    ;;

  --run|run|--test|test)
    echo "[launchd] Running $LABEL immediately with arguments: ${2:---dry-run}..."
    /bin/bash "$REPO_ROOT/scripts/server_morning_autopost.sh" "${2:---dry-run}"
    ;;

  --dry-run|dry-run)
    echo "[launchd] Running $LABEL dry-run test..."
    /bin/bash "$REPO_ROOT/scripts/server_morning_autopost.sh" --dry-run
    ;;

  --run-archive|run-archive)
    echo "[launchd] Running $ARCHIVE_LABEL immediately with arguments: ${2:---dry-run}..."
    /bin/bash "$REPO_ROOT/scripts/archive_blurb_backfill.sh" "${2:---dry-run}"
    ;;

  --install|install)
    if [[ ! -f "$SOURCE_PLIST" || ! -f "$ARCHIVE_SOURCE_PLIST" ]]; then
      echo "ERROR: Source plists not found at $SOURCE_PLIST or $ARCHIVE_SOURCE_PLIST" >&2
      exit 1
    fi

    mkdir -p "$TARGET_DIR" "$REPO_ROOT/_state" "$RUNTIME_DIR/bin" "$RUNTIME_DIR/logs" "$RUNTIME_DIR/locks" "$HOME/Library/Logs"
    touch "$LOG_FILE" "$ARCHIVE_LOG_FILE"
    ln -sf "$LOG_FILE" "$RUNTIME_DIR/logs/server-morning-autopost.log"

    # Sync runner scripts to runtime directory
    cp "$REPO_ROOT/scripts/server_morning_autopost.sh" "$RUNTIME_DIR/bin/server_morning_autopost.sh"
    chmod 755 "$RUNTIME_DIR/bin/server_morning_autopost.sh"
    cp "$REPO_ROOT/scripts/archive_blurb_backfill.sh" "$RUNTIME_DIR/bin/archive_blurb_backfill.sh"
    chmod 755 "$RUNTIME_DIR/bin/archive_blurb_backfill.sh"
    echo "[launchd] Synced scripts to $RUNTIME_DIR/bin/"

    # Unload first if loaded
    launchctl bootout "gui/$UID/$LABEL" 2>/dev/null || launchctl unload "$TARGET_PLIST" 2>/dev/null || true
    launchctl bootout "gui/$UID/$ARCHIVE_LABEL" 2>/dev/null || launchctl unload "$ARCHIVE_TARGET_PLIST" 2>/dev/null || true

    # Copy plists
    cp "$SOURCE_PLIST" "$TARGET_PLIST"
    chmod 644 "$TARGET_PLIST"
    cp "$ARCHIVE_SOURCE_PLIST" "$ARCHIVE_TARGET_PLIST"
    chmod 644 "$ARCHIVE_TARGET_PLIST"

    # Load morning autopost
    if launchctl bootstrap "gui/$UID" "$TARGET_PLIST" 2>/dev/null; then
      echo "[launchd] Service loaded: $LABEL (09:10 KST)"
    else
      launchctl load -w "$TARGET_PLIST"
      echo "[launchd] Service loaded via legacy load: $LABEL (09:10 KST)"
    fi

    # Load archive backfill
    if launchctl bootstrap "gui/$UID" "$ARCHIVE_TARGET_PLIST" 2>/dev/null; then
      echo "[launchd] Service loaded: $ARCHIVE_LABEL (15:30 KST)"
    else
      launchctl load -w "$ARCHIVE_TARGET_PLIST"
      echo "[launchd] Service loaded via legacy load: $ARCHIVE_LABEL (15:30 KST)"
    fi

    echo "[launchd] Installation complete! 09:10 KST autopost & 15:30 KST archive backfill active."
    echo "[launchd] Status:"
    launchctl list | grep "com.twodragon" || true
    ;;

  *)
    echo "Usage: $0 [--install | --uninstall | --status | --dry-run | --run | --run-archive]" >&2
    exit 1
    ;;
esac
