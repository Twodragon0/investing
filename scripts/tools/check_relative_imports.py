#!/usr/bin/env python3
"""Pre-commit hook: block absolute ``scripts.*`` imports in ``scripts/common/``.

Regression guard for PR #773. The absolute form
``from scripts.common.config import setup_logging`` fails with
``ModuleNotFoundError: No module named 'scripts'`` when collectors are
executed directly (``python scripts/collect_regulatory.py``), because
``scripts/`` is not on ``sys.path`` as a package root in that invocation.

Uses AST parsing to avoid false positives from docstring examples.

Usage (pre-commit passes changed files as argv)::

    python scripts/tools/check_relative_imports.py scripts/common/foo.py ...
"""

from __future__ import annotations

import ast
import sys


def _check_file(path: str) -> list[str]:
    try:
        with open(path, encoding="utf-8") as f:
            source = f.read()
    except OSError as exc:
        return [f"{path}:0: could not read file: {exc}"]

    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError:
        # SyntaxError unrelated to imports — let ruff/python handle it.
        return []

    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module.startswith("scripts."):
                violations.append(
                    f"{path}:{node.lineno}: from {module} import ..."
                )
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("scripts."):
                    violations.append(
                        f"{path}:{node.lineno}: import {alias.name}"
                    )
    return violations


def main(argv: list[str]) -> int:
    violations: list[str] = []
    for path in argv[1:]:
        violations.extend(_check_file(path))

    if violations:
        print(
            "ERROR: absolute 'scripts.*' imports found in scripts/common/ "
            "(regression for PR #773):",
            file=sys.stderr,
        )
        for v in violations:
            print(f"  {v}", file=sys.stderr)
        print(
            "\nFix: use relative imports (from .X import Y) inside scripts/common/.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
