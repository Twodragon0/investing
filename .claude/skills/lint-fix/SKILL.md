---
name: lint-fix
description: Python 린트 오류 자동 수정. Use when ruff check fails or code quality issues found.
disable-model-invocation: true
allowed-tools: Bash, Read, Edit
---

# Lint Fix Workflow

1. Run `python3 -m ruff check scripts/ --output-format=json` to get all issues
2. Run `python3 -m ruff check scripts/ --fix` to auto-fix safe issues
3. Report remaining issues that need manual fixes with file:line references
4. Fix remaining issues manually
5. Run `python3 -m ruff check scripts/` again to verify clean
6. Run `python3 -m ruff format scripts/` to format code
