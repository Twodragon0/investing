#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLIST_NAME="com.twodragon.investing-morning-autopost.plist"
SOURCE_PLIST="$REPO_ROOT/scripts/launchd/$PLIST_NAME"
TARGET_DIR="$HOME/Library/LaunchAgents"
TARGET_PLIST="$TARGET_DIR/$PLIST_NAME"
LABEL="com.twodragon.investing-morning-autopost"
LOG_FILE="$REPO_ROOT/_state/server-morning-autopost.log"

MODE="${1:---install}"

case "$MODE" in
  --uninstall|uninstall)
    echo "[launchd] Unloading $LABEL..."
    launchctl bootout "gui/$UID/$LABEL" 2>/dev/null || launchctl unload "$TARGET_PLIST" 2>/dev/null || true
    if [[ -f "$TARGET_PLIST" ]]; then
      rm -f "$TARGET_PLIST"
      echo "[launchd] Removed $TARGET_PLIST"
    fi
    echo "[launchd] Successfully uninstalled $LABEL"
    ;;

  --status|status)
    echo "[launchd] Checking status for $LABEL:"
    launchctl list | grep "$LABEL" || echo "Service $LABEL is not loaded."
    if [[ -f "$TARGET_PLIST" ]]; then
      echo "[launchd] Plist exists at: $TARGET_PLIST"
    else
      echo "[launchd] Plist not found in $TARGET_DIR"
    fi
    if [[ -f "$LOG_FILE" ]]; then
      echo "=== Recent Log (tail -n 10) ==="
      tail -n 10 "$LOG_FILE"
    fi
    ;;

  --run|run|--test|test)
    echo "[launchd] Running $LABEL immediately for testing..."
    /bin/bash "$REPO_ROOT/scripts/server_morning_autopost.sh"
    ;;

  --install|install)
    if [[ ! -f "$SOURCE_PLIST" ]]; then
      echo "ERROR: Source plist not found at $SOURCE_PLIST" >&2
      exit 1
    fi

    mkdir -p "$TARGET_DIR" "$REPO_ROOT/_state"

    # Unload first if loaded
    launchctl bootout "gui/$UID/$LABEL" 2>/dev/null || launchctl unload "$TARGET_PLIST" 2>/dev/null || true

    # Copy plist
    cp "$SOURCE_PLIST" "$TARGET_PLIST"
    chmod 644 "$TARGET_PLIST"

    # Load service
    if launchctl bootstrap "gui/$UID" "$TARGET_PLIST" 2>/dev/null; then
      echo "[launchd] Service loaded via bootstrap: $LABEL"
    else
      launchctl load -w "$TARGET_PLIST"
      echo "[launchd] Service loaded via legacy load: $LABEL"
    fi

    echo "[launchd] Installation complete! Scheduled daily at 09:10 KST."
    echo "[launchd] Status:"
    launchctl list | grep "$LABEL" || true
    ;;

  *)
    echo "Usage: $0 [--install | --uninstall | --status | --run]" >&2
    exit 1
    ;;
esac
