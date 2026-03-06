#!/bin/bash
# protect-files.sh - Block edits to sensitive files with proper JSON output
INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')
PROTECTED=(".env" "_state/" "package-lock.json" ".git/" ".ssh" "credentials" "secrets")

for p in "${PROTECTED[@]}"; do
  if [[ "$FILE_PATH" == *"$p"* ]]; then
    echo "{\"hookSpecificOutput\":{\"hookEventName\":\"PreToolUse\",\"permissionDecision\":\"deny\",\"permissionDecisionReason\":\"Protected pattern '$p' matched in $FILE_PATH\"}}" >&2
    exit 2
  fi
done
exit 0
