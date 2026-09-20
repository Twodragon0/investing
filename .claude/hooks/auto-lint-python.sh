#!/bin/bash
# auto-lint-python.sh - Auto-run ruff after Python file edits
#
# `check --fix` 와 `format` 을 **둘 다** 돌린다. 오래 `check --fix` 만 돌렸는데,
# 그 사이 로컬에는 포맷 계층이 **한 층도 없었다** (2026-09-19 조사):
#
#   - pre-commit 의 `ruff-format` 훅 -> `pre-commit install` 미실행이라 안 돔
#   - 이 훅 -> `check --fix` 만
#   - 수동 -> 사람이 기억해야 함
#
# `CLAUDE.md` 의 "format 누락이 흔한 CI red 원인" 이 정확히 이 구조다. CI 의
# `ruff format --check` 는 잡아 주지만 그때는 이미 red 다.
#
# 순서가 중요하다 — `check --fix` 가 임포트 정렬 같은 것을 고치면서 포맷을 깰 수
# 있으므로 `format` 이 뒤에 온다. pre-commit config 의 순서(:38 ruff -> :44
# ruff-format)와 같다.
#
# 실패해도 편집을 막지 않는다(`exit 0`). 이건 게이트가 아니라 편의 계층이고,
# 진짜 게이트는 CI 의 `ruff format --check` 다.
#
# 가드: tests/test_auto_lint_hook_guard.py

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

if [[ "$FILE_PATH" == *.py ]]; then
  if command -v ruff &> /dev/null; then
    ruff check --fix "$FILE_PATH" 2>/dev/null
    ruff format "$FILE_PATH" 2>/dev/null
  fi
fi

exit 0
