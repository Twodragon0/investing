#!/bin/bash
# component-counts-drift-guard.sh — git push 전에 docs/component-counts.md 드리프트를 막는다.
#
# 왜 필요한가: 2026-08-11 PR #1157·#1158 순차 머지에서 실제로 당했다. 두 브랜치가 각각
# 테스트 파일 1개를 더해 카운트를 141→142 로 바꿨고, 리베이스의 3-way 머지가 두 번째
# 브랜치의 142→143 을 main 의 142 에 적용해 **143** 을 만들었다. 실제 값은 144.
# 충돌 마커도 에러도 없이 조용히 틀린 값이 남았다.
#
# CI 의 `tests/test_component_counts.py::test_generated_doc_in_sync` 가 최종 방어선이고
# 이 훅은 그 앞의 빠른 피드백이다 — 푸시하고 5분 기다려 red 를 보는 대신 즉시 막는다.
#
# fail-open 하는 곳: python3 가 없으면 조용히 통과한다. 이 훅은 보안 게이트가 아니라
# 로컬 편의이고, 권위 있는 판정은 CI 에 있다. python3 가 있는데 검사가 실패하면
# 드리프트든 도구 오류든 막고 실제 출력을 보여준다 — 에러를 통과로 위장시키지 않는다.

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty')

# `git push` 를 **명령 위치**에서만 인정한다. 단순 부분문자열(`*"git push"*`)로 보면
# 문자열 안의 언급까지 걸린다 — `git commit -m "docs: git push 훅 추가"` 가 막히고,
# 실제로 이 훅을 만들면서 `echo '{"command":"git push"}'` 가 차단됐다.
#
# 인정하는 형태: 줄/세그먼트 시작의 `git push`, `git -C <path> push`, `&& git push -u …`.
# 남는 한계: `git --git-dir=… push` 같은 다른 전역 플래그 조합은 안 잡는다. 완전히
# 풀려면 셸 파싱이 필요하고, 못 잡으면 CI 의 드리프트 테스트가 최종 방어선이다.
PUSH_RE='(^|[;&|])[[:space:]]*git([[:space:]]+-C[[:space:]]+[^[:space:]]+)?[[:space:]]+push([[:space:]]|$)'
if ! printf '%s' "$COMMAND" | grep -Eq "$PUSH_RE"; then
  exit 0
fi

command -v python3 >/dev/null 2>&1 || exit 0

ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
[[ -f "$ROOT/scripts/tools/component_counts.py" ]] || exit 0

# 파이프에 넣지 말 것 — `cmd | tail` 은 tail 의 rc 를 보므로 거부가 통과로 뒤집힌다.
OUT=$(cd "$ROOT" && python3 scripts/tools/component_counts.py --check 2>&1)
RC=$?

if [[ $RC -ne 0 ]]; then
  REASON=$(printf '%s\n\n%s' \
    "component-counts 드리프트로 푸시를 막았습니다 (exit $RC):" \
    "$OUT

해결: python3 scripts/tools/component_counts.py --write
그 뒤 변경된 docs/component-counts.md 를 커밋에 포함하세요.
(리베이스 후 특히 자주 발생합니다 — 3-way 머지가 카운트를 조용히 잘못 합칩니다.)")
  jq -nc --arg reason "$REASON" \
    '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$reason}}' >&2
  exit 2
fi

exit 0
