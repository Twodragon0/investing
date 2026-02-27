#!/usr/bin/env bash
set -euo pipefail

# Patch oh-my-opencode cached plugin to allow task/tools after upgrades.
# Targets:
#   - ~/.cache/opencode/node_modules/oh-my-opencode/dist/index.js
#   - ~/.bun/install/cache/oh-my-opencode@*/dist/index.js
#
# Usage:
#   scripts/patch-oh-my-opencode.sh

HOME_DIR="${HOME}"

candidates=()
primary="$HOME_DIR/.cache/opencode/node_modules/oh-my-opencode/dist/index.js"
if [[ -f "$primary" ]]; then
  candidates+=("$primary")
fi

for f in "$HOME_DIR"/.bun/install/cache/oh-my-opencode@*/dist/index.js; do
  if [[ -f "$f" ]]; then
    candidates+=("$f")
  fi
done

if [[ ${#candidates[@]} -eq 0 ]]; then
  echo "No oh-my-opencode cache files found to patch." >&2
  exit 1
fi

patched=0
already_ok=0
failed=0

for target in "${candidates[@]}"; do
  # Use python to do safe, idempotent patching.
  result=$(python3 - "$target" <<'PY'
import sys
from pathlib import Path
import re

path = Path(sys.argv[1])
text = path.read_text()
orig = text

replacements = {
    '"grep_app_*": false': '"grep_app_*": true',
    'LspHover: false': 'LspHover: true',
    'LspCodeActions: false': 'LspCodeActions: true',
    'LspCodeActionResolve: false': 'LspCodeActionResolve: true',
    '"task_*": false': '"task_*": true',
    'teammate: false': 'teammate: true',
    'todowrite: false': 'todowrite: true',
    'todoread: false': 'todoread: true',
    'task: "deny"': 'task: "allow"',
}

for a, b in replacements.items():
    text = text.replace(a, b)

# Best-effort: if task was changed to allow inside the permission block, also allow task_* there.
if 'task: "allow"' in text and '"task_*": "allow"' not in text:
    text = re.sub(
        r'(params\.config\.permission\s*=\s*\{[\s\S]{0,400}?task:\s*"allow")',
        r'\1,\n    "task_*": "allow"',
        text,
        count=1,
    )

if text == orig:
    print("NO_CHANGE")
    sys.exit(0)

path.write_text(text)
print("PATCHED")
PY
  )

  case "$result" in
    PATCHED)
      echo "patched: $target"
      patched=$((patched+1))
      ;;
    NO_CHANGE)
      echo "no_change: $target"
      already_ok=$((already_ok+1))
      ;;
    *)
      echo "failed: $target" >&2
      failed=$((failed+1))
      ;;
  esac

done

if [[ $failed -gt 0 ]]; then
  exit 2
fi

if [[ $patched -eq 0 && $already_ok -gt 0 ]]; then
  echo "All targets already patched."
fi
