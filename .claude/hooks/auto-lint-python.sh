#!/bin/bash
# auto-lint-python.sh - Auto-run ruff after Python file edits

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

if [[ "$FILE_PATH" == *.py ]]; then
  if command -v ruff &> /dev/null; then
    ruff check --fix "$FILE_PATH" 2>/dev/null
  fi
fi

exit 0
