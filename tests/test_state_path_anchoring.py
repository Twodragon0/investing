"""Regression guard: _state paths must be repo-root-anchored, never cwd-relative.

A bare-relative path such as ``Path("_state")``, ``Path("_state/foo.json")``,
``os.path.join("_state", ...)`` or argparse ``default="_state/foo.json"``
resolves against the *caller's* cwd. Running a script from ``scripts/`` (or
anywhere but the repo root) then silently creates a stray ``<cwd>/_state/``
directory instead of writing to the real repo ``_state/``.

The fix everywhere is to compose the path from a ``__file__`` anchor
(``_REPO_ROOT / "_state" / "..."``). Anchored code therefore only ever uses
``"_state"`` as a *non-leading* path component (right operand of ``/`` or a
non-first ``os.path.join`` arg) — never as the leading element of a path.

This guard AST-scans every script (AST ignores comments/strings-in-comments) and
fails on two forms:
  A. any string literal that starts with ``_state/`` or ``_state\\`` — these are
     bare-relative regardless of how they are used; and
  B. an exact ``"_state"`` literal handed to ``Path(...)`` or ``*.join(...)`` as
     the first argument — the no-slash single-component bare-root that form A
     cannot see (slash-rooted forms in any context are already caught by A).
"""

from __future__ import annotations

import ast
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"

_BARE_ROOT = "_state"


def _py_files() -> list[Path]:
    return [p for p in SCRIPTS_DIR.rglob("*.py") if "__pycache__" not in p.parts]


def _is_slash_rooted(value: str) -> bool:
    """Form A: a literal that *starts a path* with the _state segment."""
    return value.startswith(_BARE_ROOT + "/") or value.startswith(_BARE_ROOT + "\\")


def _call_name(call: ast.Call) -> str:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _first_arg_str(call: ast.Call) -> str | None:
    if call.args and isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str):
        return call.args[0].value
    return None


def _collect_offenders(source: str, label: str) -> list[str]:
    """Return ``"<label>:<lineno> -> <reason>"`` for every cwd-relative _state use."""
    offenders: list[str] = []
    tree = ast.parse(source, filename=label)
    for node in ast.walk(tree):
        # Form A — any string literal that roots a path at _state/.
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and _is_slash_rooted(node.value):
            offenders.append(f"{label}:{node.lineno} -> literal {node.value!r}")
        # Form B — leading "_state" as the first arg to Path(...) / *.join(...).
        elif isinstance(node, ast.Call) and _call_name(node) in {"Path", "join"}:
            first = _first_arg_str(node)
            if first is not None and first == _BARE_ROOT:
                offenders.append(f"{label}:{node.lineno} -> {_call_name(node)}({first!r}) leading bare-root")
    return offenders


def test_no_cwd_relative_state_paths_in_scripts() -> None:
    """No script may root a filesystem path at a cwd-relative ``_state`` segment."""
    offenders: list[str] = []
    for path in _py_files():
        offenders.extend(
            _collect_offenders(path.read_text(encoding="utf-8"), str(path.relative_to(SCRIPTS_DIR.parent)))
        )
    assert not offenders, (
        "cwd-relative _state path(s) found. Anchor to the repo root instead "
        "(e.g. `_REPO_ROOT / '_state' / '...'`) to avoid a stray <cwd>/_state/ dir:\n" + "\n".join(offenders)
    )


def test_guard_detects_known_antipatterns() -> None:
    """The detector must flag every bare-relative form and spare anchored ones."""
    bad = (
        'x = Path("_state")',
        'x = Path("_state/foo.json")',
        'x = os.path.join("_state", "foo.json")',
        'parser.add_argument("--f", default="_state/foo.txt")',
        "p = Path('_state') / 'foo.json'",
    )
    for snippet in bad:
        assert _collect_offenders(snippet, "<bad>"), f"detector missed: {snippet}"

    good = (
        'x = _REPO_ROOT / "_state" / "foo.json"',
        'x = os.path.join(REPO_ROOT, "_state")',
        'x = os.path.join(REPO_ROOT, "_state", "foo.json")',
        'x = Path(__file__).resolve().parent.parent / "_state"',
        'name = "_state"  # bare component used elsewhere, anchored at call site',
    )
    for snippet in good:
        assert not _collect_offenders(snippet, "<good>"), f"detector false-positive: {snippet}"


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
