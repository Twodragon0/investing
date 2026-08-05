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
fails on three forms:
  A. any string literal that starts with ``_state/`` or ``_state\\`` — these are
     bare-relative regardless of how they are used; and
  B. an exact ``"_state"`` literal handed to ``Path(...)`` or ``*.join(...)`` as
     the first argument — the no-slash single-component bare-root that form A
     cannot see (slash-rooted forms in any context are already caught by A); and
  C. the two shapes that wear a disguise A/B cannot see through:
     C1. an explicit-cwd prefix — ``"./_state/foo.json"`` resolves against cwd
         exactly like ``"_state/foo.json"`` but does not *start with* the bare
         root, so form A's ``startswith`` misses it. Both A and B therefore
         strip leading ``./`` / ``.\\`` before testing.
     C2. an f-string rooted at the bare root — ``Path(f"_state/{name}.json")``
         is an ``ast.JoinedStr``, not an ``ast.Constant``, so neither A nor B
         ever sees it. Its leading literal chunk is tested with the same rules.
"""

from __future__ import annotations

import ast
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"

_BARE_ROOT = "_state"


def _py_files() -> list[Path]:
    return [p for p in SCRIPTS_DIR.rglob("*.py") if "__pycache__" not in p.parts]


# Form C1: an explicit-cwd prefix is semantically identical to no prefix at all
# (``./_state/x`` == ``_state/x``), so it must be stripped before the root tests.
_CWD_PREFIXES = ("./", ".\\")


def _strip_cwd_prefix(value: str) -> str:
    """Drop leading explicit-cwd markers (``./``, ``.\\``), however many."""
    while value.startswith(_CWD_PREFIXES):
        value = value[2:]
    return value


def _is_slash_rooted(value: str) -> bool:
    """Form A: a literal that *starts a path* with the _state segment."""
    bare = _strip_cwd_prefix(value)
    return bare.startswith(_BARE_ROOT + "/") or bare.startswith(_BARE_ROOT + "\\")


def _is_bare_root(value: str) -> bool:
    """Form B: the exact single-component bare root (cwd prefix tolerated)."""
    return _strip_cwd_prefix(value) == _BARE_ROOT


def _fstring_prefix(node: ast.JoinedStr) -> str | None:
    """Form C2: the leading *literal* chunk of an f-string, if it has one.

    ``f"_state/{name}"`` -> ``"_state/"``; ``f"{root}/_state/x"`` -> None
    (an interpolation leads, so the path is anchored at whatever ``root`` is).
    """
    if node.values and isinstance(node.values[0], ast.Constant) and isinstance(node.values[0].value, str):
        return node.values[0].value
    return None


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
        # Form A (+C1) — any string literal that roots a path at _state/.
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and _is_slash_rooted(node.value):
            offenders.append(f"{label}:{node.lineno} -> literal {node.value!r}")
        # Form C2 — f-string whose leading literal chunk roots the path at _state.
        # An f-string with no interpolation compiles to a Constant, so a bare
        # ``_state`` prefix here is always followed by an interpolated segment.
        elif isinstance(node, ast.JoinedStr):
            prefix = _fstring_prefix(node)
            if prefix is not None and (_is_slash_rooted(prefix) or _is_bare_root(prefix)):
                offenders.append(f"{label}:{node.lineno} -> f-string rooted at {prefix!r}")
        # Form B (+C1) — leading "_state" as the first arg to Path(...) / *.join(...).
        elif isinstance(node, ast.Call) and _call_name(node) in {"Path", "join"}:
            first = _first_arg_str(node)
            if first is not None and _is_bare_root(first):
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
        # Form C1 — explicit-cwd prefix resolves against cwd just the same.
        'x = Path("./_state/foo.json")',
        'x = open("./_state/foo.json")',
        'x = Path("./_state")',
        'x = os.path.join("./_state", "foo.json")',
        # Form C2 — f-string rooted at the bare root (invisible to A and B).
        'x = Path(f"_state/{name}.json")',
        'x = Path(f"./_state/{name}.json")',
        'x = open(f"_state/{name}.json")',
        'x = Path(f"_state{sep}foo.json")',
    )
    for snippet in bad:
        assert _collect_offenders(snippet, "<bad>"), f"detector missed: {snippet}"

    good = (
        'x = _REPO_ROOT / "_state" / "foo.json"',
        'x = os.path.join(REPO_ROOT, "_state")',
        'x = os.path.join(REPO_ROOT, "_state", "foo.json")',
        'x = Path(__file__).resolve().parent.parent / "_state"',
        'name = "_state"  # bare component used elsewhere, anchored at call site',
        # Anchored f-strings: an interpolation leads, so the root is whatever
        # the anchored variable holds — not cwd.
        'x = Path(f"{_REPO_ROOT}/_state/{name}.json")',
        'x = f"{REPO_ROOT}/_state"',
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


def _is_file_anchored(var: str, assigns: dict[str, ast.expr]) -> bool:
    """Return True if ``var`` is ultimately derived from ``__file__``.

    Handles both direct anchors (``_REPO_ROOT = Path(__file__).resolve()...``)
    and two-step patterns where an intermediate variable like ``_SCRIPTS_DIR``
    holds the ``__file__`` reference and ``_REPO_ROOT`` is built from that
    intermediate (``_REPO_ROOT = os.path.abspath(os.path.join(_SCRIPTS_DIR, '..'))``).
    """
    if var not in assigns:
        return False
    rhs = ast.unparse(assigns[var])
    if "__file__" in rhs:
        return True
    # Chase one level of indirection: find any Name in the RHS that itself
    # references __file__ at module scope.
    for node in ast.walk(assigns[var]):
        if isinstance(node, ast.Name) and node.id != var and node.id in assigns:
            indirect_rhs = ast.unparse(assigns[node.id])
            if "__file__" in indirect_rhs:
                return True
    return False


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


# ---------------------------------------------------------------------------
# REPO_ROOT anchor verification for remaining module-level _state writers
# Each test mirrors test_image_rejection_metrics_anchors_state_to_repo_root:
# it reads the source via AST (so conftest/monkeypatch cannot mask a regression)
# and asserts that the root anchor variable is itself derived from __file__.
# ---------------------------------------------------------------------------

# (rel_path, root_var, state_vars) — state_vars may be empty when the file
# uses __file__ inline without an intermediate root variable.
_MODULE_LEVEL_WRITERS: list[tuple[str, str, list[str]]] = [
    ("common/dedup.py", "REPO_ROOT", ["STATE_DIR"]),
    ("common/signal_tracker.py", "_REPO_ROOT", ["_STATE_DIR"]),
    ("common/translator.py", "_REPO_ROOT", ["_CACHE_PATH"]),
    ("collect_defi_llama.py", "_REPO_ROOT", ["_TVL_HISTORY_PATH"]),
    ("backfill_signal_history_accuracy.py", "_REPO_ROOT", ["_HISTORY_FILE"]),
    ("backfill_signal_history_btc_price.py", "_REPO_ROOT", ["_HISTORY_FILE"]),
    ("continuous_improvement_loop.py", "ROOT", []),  # argparse defaults reference ROOT inline
    ("check_recent_post_urls.py", "_REPO_ROOT", []),  # argparse default; path built inline
    ("generate_ops_10am_digest.py", "_REPO_ROOT", []),  # argparse default; path built inline
]


import pytest  # noqa: E402 — pytest already on path; placed here to avoid reordering imports above


@pytest.mark.parametrize(
    ("rel_path", "root_var", "state_vars"), _MODULE_LEVEL_WRITERS, ids=[t[0] for t in _MODULE_LEVEL_WRITERS]
)
def test_module_level_state_paths_anchored_to_repo_root(rel_path: str, root_var: str, state_vars: list[str]) -> None:
    """Every module-level _state writer must derive its root anchor from __file__.

    Checks two things via AST (immune to monkeypatch):
    1. The ``root_var`` variable is defined at module scope.
    2. The root_var RHS contains ``__file__`` (i.e. is a __file__-anchored expression).
    3. Each ``state_var`` listed in ``state_vars`` references ``root_var`` in its RHS.
    """
    source = (SCRIPTS_DIR / rel_path).read_text(encoding="utf-8")
    assigns = _module_level_assignments(source)

    assert root_var in assigns, f"{rel_path}: module-level {root_var!r} anchor variable is missing"
    assert _is_file_anchored(root_var, assigns), (
        f"{rel_path}: {root_var} must be derived from __file__ (directly or via one intermediate variable)."
        f" Got: {ast.unparse(assigns[root_var])!r}"
    )

    for name in state_vars:
        assert name in assigns, f"{rel_path}: module-level state variable {name!r} is missing"
        rhs = ast.unparse(assigns[name])
        assert root_var in rhs, f"{rel_path}: {name} must reference {root_var!r} (got: {rhs!r})"


# Module-level _state writers verified by a *dedicated* test rather than by the
# `_MODULE_LEVEL_WRITERS` table above. Listed here so the drift check below
# counts them as covered.
_DEDICATED_ANCHOR_TESTS: frozenset[str] = frozenset(
    {
        "common/image_rejection_metrics.py",  # test_image_rejection_metrics_anchors_state_to_repo_root
        "fix_defi_tvl_history.py",  # test_fix_defi_tvl_history_state_path_uses_file_anchor
    }
)


def _builds_state_path(expr: ast.expr) -> bool:
    """True if ``expr`` composes a filesystem path containing a ``_state`` segment.

    Two conditions must both hold, which is what keeps the scan from firing on
    prose: (1) a string constant that *is* the bare root or roots a path at it,
    and (2) an actual path-construction node — a ``Path()``/``join()``/
    ``abspath()`` call or a ``/`` operator. A module that merely mentions
    ``_state`` inside a message or a table of test fixtures satisfies neither.
    """
    if not any(
        isinstance(n, ast.Constant)
        and isinstance(n.value, str)
        and (_is_bare_root(n.value) or _is_slash_rooted(n.value))
        for n in ast.walk(expr)
    ):
        return False
    for node in ast.walk(expr):
        if isinstance(node, ast.Call) and _call_name(node) in {"Path", "join", "abspath"}:
            return True
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            return True
    return False


def _discover_module_level_state_writers() -> set[str]:
    """Every script that assigns a ``_state`` path at module scope."""
    writers: set[str] = set()
    for path in _py_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            value = node.value if isinstance(node, (ast.Assign, ast.AnnAssign)) else None
            if value is not None and _builds_state_path(value):
                writers.add(str(path.relative_to(SCRIPTS_DIR)))
    return writers


def test_module_level_writers_table_has_no_drift() -> None:
    """Every module-level ``_state`` writer must be covered by an anchor test.

    ``_MODULE_LEVEL_WRITERS`` is hand-maintained, so a newly added writer is
    silently unguarded — the parametrized test above simply never runs for it
    and the suite stays green. This closes that hole by discovering writers from
    the source tree and requiring each one to be registered.

    Adding a new module-level ``_state`` writer? Append ``(rel_path, root_var,
    state_vars)`` to ``_MODULE_LEVEL_WRITERS`` (or write a dedicated test and
    list the file in ``_DEDICATED_ANCHOR_TESTS``).
    """
    discovered = _discover_module_level_state_writers()
    assert discovered, "no module-level _state writers discovered — the scan is broken (vacuous)"

    covered = {rel for rel, _, _ in _MODULE_LEVEL_WRITERS} | _DEDICATED_ANCHOR_TESTS
    unregistered = sorted(discovered - covered)
    assert not unregistered, (
        "module-level _state writer(s) not covered by any repo-root anchor test:\n"
        + "\n".join(f"  - {p}" for p in unregistered)
        + "\n\nRegister each in _MODULE_LEVEL_WRITERS in this file so its __file__ anchor is verified."
    )


def test_module_level_writers_table_entries_still_exist() -> None:
    """Canary: a renamed/deleted entry must fail loudly, not skip silently."""
    missing = [rel for rel, _, _ in _MODULE_LEVEL_WRITERS if not (SCRIPTS_DIR / rel).is_file()]
    missing += [rel for rel in sorted(_DEDICATED_ANCHOR_TESTS) if not (SCRIPTS_DIR / rel).is_file()]
    assert not missing, f"registered _state writer(s) no longer exist: {missing}"


def test_fix_defi_tvl_history_state_path_uses_file_anchor() -> None:
    """fix_defi_tvl_history.py uses __file__ inline (no root variable) — verify directly."""
    source = (SCRIPTS_DIR / "fix_defi_tvl_history.py").read_text(encoding="utf-8")
    assigns = _module_level_assignments(source)

    assert "HISTORY_PATH" in assigns, "fix_defi_tvl_history.py: HISTORY_PATH assignment missing"
    rhs = ast.unparse(assigns["HISTORY_PATH"])
    assert "__file__" in rhs, f"HISTORY_PATH must be __file__-anchored (got: {rhs!r})"
    # Confirm it is NOT a bare relative Path("_state/...")
    assert not _is_slash_rooted(rhs.lstrip("Path(").rstrip(")")), (
        "HISTORY_PATH appears to be slash-rooted (cwd-relative)"
    )


# ---------------------------------------------------------------------------
# Runtime absoluteness guard: verify that module-level state path constants
# resolve to absolute paths that live under the repo root — not under cwd.
# These tests complement the AST guards by checking the *computed* value at
# import time, not just the source structure.
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize(
    ("import_path", "attr"),
    [
        ("common.dedup", "STATE_DIR"),
        ("common.signal_tracker", "_STATE_DIR"),
        ("common.translator", "_CACHE_PATH"),
    ],
    ids=["dedup.STATE_DIR", "signal_tracker._STATE_DIR", "translator._CACHE_PATH"],
)
@pytest.mark.no_state_isolation
def test_module_state_path_is_absolute_and_under_repo_root(import_path: str, attr: str) -> None:
    """The computed module-level state path must be absolute and under the repo root.

    This is a *runtime* guard: it imports the already-cached module and reads
    the path attribute to confirm the value is rooted at the repo root, not at
    the test process cwd.  A stray ``<cwd>/_state/`` would produce a path that
    does NOT start with ``_REPO_ROOT``.

    Marked ``no_state_isolation`` because the autouse dedup/signal ``_state``
    redirect fixtures would otherwise repoint ``STATE_DIR`` at a tmp dir and
    defeat this repo-anchoring assertion.
    """
    import importlib

    mod = importlib.import_module(import_path)
    raw = getattr(mod, attr)
    p = Path(raw) if not isinstance(raw, Path) else raw

    assert p.is_absolute(), f"{import_path}.{attr} = {p!r} is not absolute — cwd-relative path detected"
    assert str(p).startswith(str(_REPO_ROOT)), (
        f"{import_path}.{attr} = {p!r} does not start with repo root {_REPO_ROOT!r}. Stray cwd-relative _state/ path?"
    )
