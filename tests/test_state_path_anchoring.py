"""Regression guard: _state paths must be repo-root-anchored, never cwd-relative.

A bare-relative literal like ``Path("_state/foo.json")`` or argparse
``default="_state/foo.json"`` resolves against the caller's cwd, so running a
script from ``scripts/`` (or anywhere but the repo root) silently creates a
stray ``<cwd>/_state/`` directory instead of writing to the real repo
``_state/``. The fix everywhere is to compose the path from a ``__file__``
anchor (``_REPO_ROOT / "_state" / "..."``), so anchored code only ever embeds
``"_state"`` as a *single* path component — never ``"_state/<file>"`` as one
literal.

This test pins that invariant by AST-scanning every script for string literals
that begin with ``_state/`` (AST ignores comments and docstrings-as-comments,
so the explanatory comment in image_rejection_metrics.py is not flagged).
"""

from __future__ import annotations

import ast
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"


def _py_files() -> list[Path]:
    return [p for p in SCRIPTS_DIR.rglob("*.py") if "__pycache__" not in p.parts]


def test_no_bare_relative_state_path_literals() -> None:
    """No script may embed a cwd-relative ``_state/...`` path as a string literal."""
    offenders: list[str] = []
    for path in _py_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                value = node.value
                if value.startswith("_state/") or value.startswith("_state\\"):
                    rel = path.relative_to(SCRIPTS_DIR.parent)
                    offenders.append(f"{rel}:{node.lineno} -> {value!r}")

    assert not offenders, (
        "Bare cwd-relative '_state/...' path literal(s) found. Anchor to the repo "
        "root instead (e.g. `_REPO_ROOT / '_state' / '...'`) to avoid creating a "
        "stray <cwd>/_state/ directory:\n" + "\n".join(offenders)
    )


def _module_level_assignments(source: str) -> dict[str, ast.expr]:
    """Map module-level ``Name = <expr>`` targets to their RHS expression nodes."""
    tree = ast.parse(source)
    assigns: dict[str, ast.expr] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    assigns[target.id] = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
            assigns[node.target.id] = node.value
    return assigns


def test_image_rejection_metrics_anchors_state_to_repo_root() -> None:
    """The canonical at-import (atexit-flushed) module must derive its state paths
    from a ``__file__`` anchor, not a bare literal.

    Source-checked via AST so the conftest tmp-dir redirect of the *runtime*
    ``_STATE_PATH`` global cannot mask a regression in the committed default.
    """
    source = (SCRIPTS_DIR / "common" / "image_rejection_metrics.py").read_text(encoding="utf-8")
    assigns = _module_level_assignments(source)

    assert "_REPO_ROOT" in assigns, "_REPO_ROOT anchor is missing"
    assert "__file__" in ast.unparse(assigns["_REPO_ROOT"]), "_REPO_ROOT must be derived from __file__: " + ast.unparse(
        assigns["_REPO_ROOT"]
    )
    for name in ("_STATE_PATH", "_ARCHIVE_DIR"):
        assert name in assigns, f"{name} assignment is missing"
        rhs = ast.unparse(assigns[name])
        assert "_REPO_ROOT" in rhs, f"{name} must be anchored to _REPO_ROOT, got: {rhs}"
