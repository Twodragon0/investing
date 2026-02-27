#!/bin/bash
# protect-files.sh - Block edits to sensitive files in the investing project

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

PROTECTED_PATTERNS=(".env" "_state/" "package-lock.json" ".git/" ".ssh" "credentials" "secrets")

for pattern in "${PROTECTED_PATTERNS[@]}"; do
  if [[ "$FILE_PATH" == *"$pattern"* ]]; then
    echo "Blocked: $FILE_PATH matches protected pattern '$pattern'. These files should not be modified directly." >&2
    exit 2
  fi
done

exit 0
