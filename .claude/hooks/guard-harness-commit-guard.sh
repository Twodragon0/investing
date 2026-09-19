#!/bin/bash
# guard-harness-commit-guard.sh — falsifiability 하네스가 도는 동안 커밋을 막는다.
#
# ## 왜 있나
#
# `scripts/tools/guard_falsifiability.py` 는 워킹트리의 워크플로우·스크립트를
# **제자리에서 덮어썼다 복원한다.** 그 사이에 `git add`/`commit` 을 하면 뮤테이션이
# 그대로 커밋에 들어간다.
#
# 2026-09-18 실측: `.github/workflows/dependabot-auto-merge.yml` 의
# `if [ -n "$failed" ]; then` → `if false; then`(실패 체크 abort 무력화, fail-open)이
# 커밋됐다. **조용한 사고다** —
#
#   - 커밋 직후 워킹트리는 하네스가 복원하므로 `git status` 가 깨끗하다
#   - 그 상태로 돌린 풀 스위트도 7577 passed 로 통과한다
#   - 즉 테스트도 트리도 정상인데 **커밋 내용만** fail-open 이다
#
# 하네스는 반대 방향(더러운 트리에서 시작)은 이미 막고 있었다. 이 훅이 나머지
# 방향을 막는다.
#
# ## 왜 pre-commit 훅이 아닌가
#
# 이 클론의 `.git/hooks/` 에는 샘플만 있다 — `pre-commit install` 이 안 돼 있어
# `.pre-commit-config.yaml` 훅은 로컬에서 돌지 않는다(2026-09-18 실측). 실제로
# 발동하는 자리는 Claude 훅이고, `pre-commit-state-guard.sh` 가 같은 선례다.
#
# ## stale 락을 막는 쪽이 더 중요하다
#
# 하네스는 SIGKILL 로 죽을 수 있다(같은 날 메모리 압박으로 두 번). 그때 락이
# 남는데, 살아있음을 확인하지 않으면 남은 락이 **이후 모든 커밋을 영영 막는다** —
# 막으려던 사고보다 나쁜 고장이다. 판정은 `read_active_lock()` 에 위임하고,
# 그 함수가 죽은 홀더의 락을 지운다.
#
# 가드: tests/test_harness_commit_guard.py

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty')

# `git commit` 을 **명령 위치**에서만 인정한다. `pre-commit-state-guard.sh` 와 같은
# 규칙이다 — 부분문자열 매칭은 문자열 안의 언급을 막고 `git -C /repo commit` 은 놓친다.
COMMIT_RE='(^|[;&|])[[:space:]]*git([[:space:]]+-C[[:space:]]+[^[:space:]]+)?[[:space:]]+commit([[:space:]]|$)'
if ! printf '%s' "$COMMAND" | grep -Eq "$COMMIT_RE"; then
  exit 0
fi

ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)

# 판정은 하네스 자신의 함수로 한다. 락 형식을 여기에 베껴 두면 한쪽만 바뀌었을 때
# 훅이 조용히 아무것도 막지 않는다.
HOLDER=$(cd "$ROOT" && python3 -c '
import json, sys
sys.path.insert(0, "scripts/tools")
try:
    import guard_falsifiability as g
except Exception:
    sys.exit(0)
lock = g.read_active_lock()
if lock:
    print(json.dumps(lock))
' 2>/dev/null)

if [[ -n "$HOLDER" ]]; then
  REASON="Cowardly refusing to commit while the falsifiability harness is running.

The harness overwrites workflow/script files in place and restores them afterwards.
Committing now can capture a mutation — measured 2026-09-18: a fail-open
(\`if false; then\` in dependabot-auto-merge.yml) landed in a commit while the
working tree and the full suite both looked clean.

Holder: $HOLDER

Wait for it to finish (\`ps aux | grep guard_falsifiability\`), then commit.
If the harness already died, the lock clears itself on the next check."
  jq -nc --arg reason "$REASON" \
    '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$reason}}' >&2
  exit 2
fi
exit 0
