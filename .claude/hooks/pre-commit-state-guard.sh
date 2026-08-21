#!/bin/bash
# pre-commit-state-guard.sh - Prevent committing _state/*.json (auto-managed by collectors)
# Triggers on Bash tool invocations that actually run `git commit`.
#
# 2026-08-12: 매칭과 출력 두 곳을 고쳤다. 근거·실측은
# tests/test_state_guard_command_matching.py 의 docstring.
#
# - 매칭: `*"git commit"*` 부분문자열은 오탐과 미탐을 함께 냈다. 문자열 안의 언급
#   (`echo "실행: git commit …"`, `git log --grep="git commit"`)을 막았고, 반대로
#   `git -C /repo commit` 은 리터럴이 없어서 **놓쳤다**.
# - 출력: 이유를 셸 보간으로 JSON 에 넣었는데 staged 목록은 개행 구분이라
#   `_state` 파일이 2개 이상이면 원시 개행이 들어가 invalid JSON 이 됐다.
#   1개일 때만 우연히 유효해서 눈에 띄지 않았다.

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty')

# `git commit` 을 **명령 위치**에서만 인정한다 — 줄/세그먼트 시작, 또는 `;`/`&&`/`||`/`|`
# 뒤. `component-counts-drift-guard.sh` 와 같은 규칙이다.
#
# 남는 한계: `git --git-dir=… commit` 같은 다른 전역 플래그 조합은 안 잡는다. 완전히
# 풀려면 셸 파싱이 필요하다. 못 잡으면 `_state` 가 커밋될 수 있으므로, 그 형태를 쓸
# 일이 생기면 이 패턴에 추가할 것.
COMMIT_RE='(^|[;&|])[[:space:]]*git([[:space:]]+-C[[:space:]]+[^[:space:]]+)?[[:space:]]+commit([[:space:]]|$)'
if ! printf '%s' "$COMMAND" | grep -Eq "$COMMIT_RE"; then
  exit 0
fi

ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
STAGED=$(git -C "$ROOT" diff --cached --name-only 2>/dev/null | grep "^_state/" || true)

if [[ -n "$STAGED" ]]; then
  REASON="Cowardly refusing to commit _state/ files (auto-managed by collectors).

Staged:
$STAGED

Use 'git restore --staged _state/' first."
  # jq 로 만든다 — staged 목록의 개행이 셸 보간에서는 invalid JSON 이 된다.
  jq -nc --arg reason "$REASON" \
    '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$reason}}' >&2
  exit 2
fi
exit 0
