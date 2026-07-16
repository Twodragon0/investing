#!/bin/bash
# yaml-syntax-check.sh - Validate YAML syntax after Edit/Write

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

if [[ "$FILE_PATH" == *.yml || "$FILE_PATH" == *.yaml ]]; then
  if [[ -f "$FILE_PATH" ]]; then
    # Pass the path as argv, never interpolated into the -c program text, so a
    # crafted file name cannot break out and execute code (CWE-94 / OWASP
    # A03:2021 Injection).
    if ! python3 -c "import yaml,sys; yaml.safe_load(open(sys.argv[1]))" "$FILE_PATH" 2>/dev/null; then
      echo "[yaml-syntax-check] WARNING: $FILE_PATH has YAML syntax errors." >&2
    fi
  fi
fi
exit 0
