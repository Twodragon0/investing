#!/usr/bin/env bash
set -euo pipefail

# Patch oh-my-opencode cached plugin to allow selected local tools after upgrades.
# Targets:
#   - ~/.cache/opencode/node_modules/oh-my-opencode/dist/index.js
#   - ~/.bun/install/cache/oh-my-opencode@*/dist/index.js
#
# Usage:
#   scripts/patch-oh-my-opencode.sh

HOME_DIR="${HOME}"
BACKUP_ROOT="$HOME_DIR/.cache/opencode/patch-backups/oh-my-opencode"

candidates=()
primary="$HOME_DIR/.cache/opencode/node_modules/oh-my-opencode/dist/index.js"
if [[ -f "$primary" ]]; then
	candidates+=("$primary")
fi

bun_candidates=()
for f in "$HOME_DIR"/.bun/install/cache/oh-my-opencode@*/dist/index.js; do
	if [[ -f "$f" ]]; then
		bun_candidates+=("$f")
	fi
done

if [[ ${#bun_candidates[@]} -gt 0 ]]; then
	latest_bun_target="$({ printf '%s\n' "${bun_candidates[@]}"; } | sort -V | tail -n 1)"
	if [[ -n "$latest_bun_target" ]]; then
		candidates+=("$latest_bun_target")
	fi
fi

if [[ ${#candidates[@]} -eq 0 ]]; then
	echo "No oh-my-opencode cache files found to patch." >&2
	exit 1
fi

mkdir -p "$BACKUP_ROOT"

patched=0
already_ok=0
failed=0

for target in "${candidates[@]}"; do
	# Use python to do safe, idempotent patching.
	if result=$(
		PATCH_BACKUP_ROOT="$BACKUP_ROOT" python3 - "$target" <<'PY'
import sys
from pathlib import Path
import re
import os

path = Path(sys.argv[1])
text = path.read_text()
orig = text

required_anchors = [
    'function applyToolConfig(params)',
    '"grep_app_*":',
    'LspHover:',
    'LspCodeActions:',
    'LspCodeActionResolve:',
    'teammate:',
    'task:',
]

if not all(anchor in text for anchor in required_anchors):
    print('UNSUPPORTED_LAYOUT')
    sys.exit(3)

replacements = {
    '"grep_app_*": false': '"grep_app_*": true',
    'LspHover: false': 'LspHover: true',
    'LspCodeActions: false': 'LspCodeActions: true',
    'LspCodeActionResolve: false': 'LspCodeActionResolve: true',
    'teammate: false': 'teammate: true',
    'todowrite: false': 'todowrite: true',
    'todoread: false': 'todoread: true',
}

enable_task_tools = os.environ.get('ENABLE_OPENCODE_TASK_TOOLS') == '1'

if enable_task_tools:
    replacements['"task_*": false'] = '"task_*": true'
    replacements['task: "deny"'] = 'task: "allow"'

for a, b in replacements.items():
    text = text.replace(a, b)

# Best-effort: if task was changed to allow inside the permission block, also allow task_* there.
if enable_task_tools and 'task: "allow"' in text and '"task_*": "allow"' not in text:
    text = re.sub(
        r'(params\.config\.permission\s*=\s*\{[\s\S]{0,400}?task:\s*"allow")',
        r'\1,\n    "task_*": "allow"',
        text,
        count=1,
    )

expected_present = [
    '"grep_app_*": true',
    'LspHover: true',
    'LspCodeActions: true',
    'LspCodeActionResolve: true',
    'teammate: true',
]

if enable_task_tools:
    expected_present.extend([
        '"task_*": true',
        'task: "allow"',
    ])

if not all(item in text for item in expected_present):
    print('VERIFY_FAILED')
    sys.exit(4)

if text == orig:
    print("NO_CHANGE_VERIFIED")
    sys.exit(0)

backup_root = Path(os.environ['PATCH_BACKUP_ROOT'])
backup_root.mkdir(parents=True, exist_ok=True)
target_name = path.parent.parent.name.replace('@', '_at_').replace('/', '_')
backup_path = backup_root / f"{target_name}-index.js.bak"
if not backup_path.exists():
    backup_path.write_text(orig)

path.write_text(text)
print("PATCHED")
PY
	); then
		python_status=0
	else
		python_status=$?
	fi

	case "$result" in
	PATCHED)
		echo "patched: $target"
		patched=$((patched + 1))
		;;
	NO_CHANGE_VERIFIED)
		echo "no_change: $target"
		already_ok=$((already_ok + 1))
		;;
	UNSUPPORTED_LAYOUT)
		echo "unsupported_layout: $target" >&2
		failed=$((failed + 1))
		;;
	VERIFY_FAILED)
		echo "verify_failed: $target" >&2
		failed=$((failed + 1))
		;;
	*)
		echo "failed: $target (python_status=${python_status:-unknown}, result=${result:-empty})" >&2
		failed=$((failed + 1))
		;;
	esac

done

if [[ $failed -gt 0 ]]; then
	exit 2
fi

if [[ $patched -eq 0 && $already_ok -gt 0 ]]; then
	echo "All targets already patched."
fi
