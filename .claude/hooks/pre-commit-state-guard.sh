#!/bin/bash
# pre-commit-state-guard.sh - Prevent committing _state/*.json (auto-managed by collectors)
# Triggers on Bash tool invocations matching `git commit`.

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty')

# Only act on commits
if [[ "$COMMAND" != *"git commit"* ]]; then
  exit 0
fi

# Check if any _state/ files are staged
STAGED=$(git -C "$(git rev-parse --show-toplevel 2>/dev/null || pwd)" diff --cached --name-only 2>/dev/null | grep "^_state/" || true)
if [[ -n "$STAGED" ]]; then
  REASON="Cowardly refusing to commit _state/ files (auto-managed by collectors). Staged: $STAGED. Use 'git restore --staged _state/' first."
  echo "{\"hookSpecificOutput\":{\"hookEventName\":\"PreToolUse\",\"permissionDecision\":\"deny\",\"permissionDecisionReason\":\"$REASON\"}}" >&2
  exit 2
fi
exit 0
