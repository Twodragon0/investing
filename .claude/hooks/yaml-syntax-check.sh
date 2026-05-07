#!/bin/bash
# yaml-syntax-check.sh - Validate YAML syntax after Edit/Write

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

if [[ "$FILE_PATH" == *.yml || "$FILE_PATH" == *.yaml ]]; then
  if [[ -f "$FILE_PATH" ]]; then
    if ! python3 -c "import yaml,sys; yaml.safe_load(open('$FILE_PATH'))" 2>/dev/null; then
      echo "[yaml-syntax-check] WARNING: $FILE_PATH has YAML syntax errors. Verify with: python3 -c \"import yaml; yaml.safe_load(open('$FILE_PATH'))\"" >&2
    fi
  fi
fi
exit 0
