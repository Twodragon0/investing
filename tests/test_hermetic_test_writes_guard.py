"""Regression guard: tests must not import a production real-tree root constant.

## Incident this guards against

On 2026-06-30 several tests in ``test_post_generator.py`` imported the production
``REPO_ROOT`` from ``common.post_generator`` and wrote real files under
``REPO_ROOT/assets/images/generated/`` (cleaned up in ``finally``). On abnormal
termination those untracked artifacts leaked into the working tree — the exact
filesystem-state-divergence class that made the ``TestGoldenMasterSummarySections``
SHA256 golden master pass locally (images present) but fail in CI (images absent).

## The invariant

A test that needs to exercise code resolving paths against a module-level
real-tree root (``REPO_ROOT``; or its derivatives ``POSTS_DIR =
REPO_ROOT/_posts``, ``SITE_DIR``) MUST redirect that constant to a per-test tmp
dir:

    monkeypatch.setattr("common.post_generator.REPO_ROOT", str(tmp_path))

— a string-target ``setattr`` that does NOT import the symbol. Conversely,
``from common.<mod> import REPO_ROOT`` (including ``... import REPO_ROOT as RR``)
binds the *real* repo root into the test namespace, whose only use is composing
real-tree paths; that is the precise signal of a non-hermetic real-tree write and
is banned here, for each name in ``_BANNED_NAMES``.

Test-file-local anchors (``REPO_ROOT = Path(__file__).resolve().parent.parent``)
used by read-only config guards are assignments, not imports, so they are NOT
flagged. This guard AST-scans (ignoring comments/strings), so the docstrings and
``monkeypatch.setattr("...REPO_ROOT...")`` string literals above never trip it.

## Scope

This guard flags four shapes of production real-tree-root access in tests:

  1. Direct import — ``from <prod> import REPO_ROOT`` (incl. ``... as RR``).
     The canonical vector the 2026-06-30 incident used.
  2. Module-alias attribute access — reading the root off a production module
     bound to a local name:
       - ``import common.post_generator as pg; pg.REPO_ROOT``
       - ``from common import post_generator; post_generator.REPO_ROOT``
       - ``import common.post_generator; common.post_generator.REPO_ROOT``
     These leak the *real* repo root into the test just as surely as form 1.
  3. Dynamic attribute access — ``getattr(pg, "REPO_ROOT")``. The name lives in
     a *string*, so forms 1-2 (which match an ``Attribute`` node or an import
     alias) never see it, yet the value returned is the same real repo root.
  4. Inline-import attribute access —
     ``importlib.import_module("common.post_generator").REPO_ROOT``. The
     attribute base is a ``Call``, not a ``Name``/dotted chain, so the form-2
     scan bails out. Combined with form 3 this also covers
     ``getattr(import_module("common.post_generator"), "REPO_ROOT")``.

Intentionally NOT flagged — the legitimate redirect: the object-form
``monkeypatch.setattr(pg, "REPO_ROOT", str(tmp_path))`` (or the string-target
``monkeypatch.setattr("common.post_generator.REPO_ROOT", ...)``). Neither
produces a ``mod.REPO_ROOT`` *attribute-read* node — the module is passed as an
argument and the name is a string literal — so the AST attribute scan never
sees them. That asymmetry (read-attribute is banned, setattr object/string form
is allowed) is what makes closing the alias gap safe. Form 3 preserves it by
matching only ``getattr`` — ``setattr(pg, "REPO_ROOT", ...)`` writes the
redirect rather than leaking the root, and stays allowed.

Attribute access to *non-root* module attributes (``dedup.STATE_DIR``,
``signal_tracker._HISTORY_FILE``, ``image_generator.IMAGES_DIR``) is untouched —
only names in ``_BANNED_NAMES`` trip the scan.

Direction: presence check — any banned production root read trips. If a future
test legitimately needs to *read* a repo file, derive a local ``__file__`` anchor
instead of importing/aliasing the production constant.
"""

from __future__ import annotations

import ast
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent

# Modules whose roots are the *production* working tree (resolve to the real
# checkout). ``PYTHONPATH=scripts`` means tests import as ``common.*``; the
# ``scripts.*`` spellings are covered for completeness.
_PROD_PREFIXES = ("common", "scripts.common", "scripts")
# Production real-tree root constants. ``POSTS_DIR``/``SITE_DIR`` are
# ``REPO_ROOT``-derived (e.g. ``post_generator.POSTS_DIR = REPO_ROOT/_posts``) and
# share the identical leak risk, so importing any of them into a test is banned.
_BANNED_NAMES = ("REPO_ROOT", "POSTS_DIR", "SITE_DIR")


def _is_production_module(module: str | None) -> bool:
    if not module:
        return False
    return module in _PROD_PREFIXES or any(module.startswith(p + ".") for p in _PROD_PREFIXES)


def _py_files() -> list[Path]:
    return [p for p in TESTS_DIR.rglob("*.py") if "__pycache__" not in p.parts]


def _dotted_name(node: ast.expr) -> str | None:
    """Return the dotted path for a ``Name``/``Attribute`` chain (``a.b.c``), else None."""
    parts: list[str] = []
    cur: ast.expr = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
        return ".".join(reversed(parts))
    return None


def _call_name(call: ast.Call) -> str:
    """Bare callee name for ``f(...)`` / ``a.b.f(...)``, else ``""``."""
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


def _is_prod_module_expr(expr: ast.expr, aliases: set[str]) -> bool:
    """True if ``expr`` evaluates to a production module object.

    Covers the three ways a test can name one: a local alias bound by an import
    (``pg``), a dotted no-alias chain (``common.post_generator``), and an inline
    ``importlib.import_module("common.post_generator")`` call (form 4).
    """
    if isinstance(expr, ast.Name) and expr.id in aliases:
        return True
    if isinstance(expr, ast.Call) and _call_name(expr) == "import_module":
        return _is_production_module(_first_arg_str(expr))
    dotted = _dotted_name(expr)
    return dotted is not None and _is_production_module(dotted)


def _collect_prod_module_aliases(tree: ast.AST) -> set[str]:
    """Local names bound to a *production module* (for alias-attribute detection).

    Records the module-binding import forms:
      - ``import common.post_generator as pg``       → ``{"pg"}``
      - ``from common import post_generator``        → ``{"post_generator"}``
      - ``from common import post_generator as pg``  → ``{"pg"}``

    ``import common.post_generator`` (no ``as``) binds the top package ``common``
    and is instead matched by the dotted-chain check in ``_scan_tree``, so it is
    not recorded here. ``from <prod> import <ROOT>`` (a banned root name, not a
    module) is the direct-import form and is skipped here — the ``ImportFrom``
    branch in ``_scan_tree`` handles it.
    """
    aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.asname and _is_production_module(a.name):
                    aliases.add(a.asname)
        elif isinstance(node, ast.ImportFrom) and _is_production_module(node.module):
            for a in node.names:
                if a.name in _BANNED_NAMES:
                    continue  # direct root import — handled separately
                aliases.add(a.asname or a.name)
    return aliases


def _scan_tree(tree: ast.AST, label: str) -> list[str]:
    """Return ``label:line`` offenders for a single parsed module."""
    offenders: list[str] = []
    aliases = _collect_prod_module_aliases(tree)
    for node in ast.walk(tree):
        # Form 1 — direct ``from <prod> import REPO_ROOT``.
        if isinstance(node, ast.ImportFrom) and _is_production_module(node.module):
            if any(alias.name in _BANNED_NAMES for alias in node.names):
                offenders.append(f"{label}:{node.lineno}")
        # Forms 2 and 4 — attribute *read* ``<prod-module-expr>.REPO_ROOT``,
        # where the base is an alias (2a), a dotted no-alias chain (2b), or an
        # inline ``import_module(...)`` call (4). The
        # ``monkeypatch.setattr(mod, "REPO_ROOT", ...)`` object form has no such
        # attribute node (module is an arg, name is a string), so it is not hit.
        elif isinstance(node, ast.Attribute) and node.attr in _BANNED_NAMES:
            if _is_prod_module_expr(node.value, aliases):
                offenders.append(f"{label}:{node.lineno}")
        # Form 3 — dynamic read ``getattr(<prod-module-expr>, "REPO_ROOT")``.
        # Matched on ``getattr`` only: ``setattr`` is the sanctioned redirect.
        elif isinstance(node, ast.Call) and _call_name(node) == "getattr" and len(node.args) >= 2:
            attr = node.args[1]
            if (
                isinstance(attr, ast.Constant)
                and attr.value in _BANNED_NAMES
                and _is_prod_module_expr(node.args[0], aliases)
            ):
                offenders.append(f"{label}:{node.lineno}")
    return offenders


def _scan() -> tuple[list[str], list[str]]:
    """Return (offenders, unparseable) — both as ``path:line`` / ``path`` strings."""
    offenders: list[str] = []
    unparseable: list[str] = []
    for path in _py_files():
        rel = str(path.relative_to(TESTS_DIR.parent))
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            unparseable.append(rel)
            continue
        offenders.extend(_scan_tree(tree, rel))
    return offenders, unparseable


def test_tests_dir_scanned_nonvacuous():
    """Canary: a broken glob or unparseable file must fail loudly, not pass vacuously."""
    files = _py_files()
    assert len(files) >= 50, f"expected to scan the test suite, only found {len(files)} files"
    _, unparseable = _scan()
    assert not unparseable, (
        "스캔 불가 테스트 파일이 있어 가드가 해당 파일의 위반을 놓칠 수 있습니다 (vacuous):\n"
        + "\n".join(f"  - {p}" for p in unparseable)
    )


def test_no_test_imports_production_repo_root():
    offenders, _ = _scan()
    assert not offenders, (
        "테스트가 production 실제-트리 루트 상수를 import/별칭-접근 했습니다 (비-격리 실제-트리 쓰기 위험):\n"
        + "\n".join(f"  - {o}" for o in offenders)
        + "\n\n실제 repo 트리에 쓰지 말고, 대상 모듈의 루트 상수를 tmp 로 monkeypatch 하세요:\n"
        '    monkeypatch.setattr("common.post_generator.REPO_ROOT", str(tmp_path))\n'
        f"금지 상수: {_BANNED_NAMES}. 의도된 변경이면 이 가드의 docstring/_BANNED_NAMES 를 함께 갱신하세요."
    )


def _offenders_in(source: str) -> list[str]:
    """Run the detector against an inline snippet (detector unit-test helper)."""
    return _scan_tree(ast.parse(source), "<snippet>")


def test_detector_flags_all_banned_forms():
    """The detector must flag every real-tree-root access shape, direct and aliased."""
    bad = (
        # Form 1 — direct import (incl. `as`).
        "from common.post_generator import REPO_ROOT\n",
        "from common.post_generator import REPO_ROOT as RR\n",
        # Form 2a — aliased module attribute read.
        "import common.post_generator as pg\nx = pg.REPO_ROOT\n",
        "from common import post_generator\nx = post_generator.POSTS_DIR\n",
        "from common import post_generator as pg\nx = pg.SITE_DIR\n",
        "from scripts.common import post_generator\nx = post_generator.REPO_ROOT\n",
        # Form 2b — dotted no-alias chain.
        "import common.post_generator\nx = common.post_generator.REPO_ROOT\n",
        # Form 3 — dynamic getattr with the name in a string.
        'import common.post_generator as pg\nx = getattr(pg, "REPO_ROOT")\n',
        'from common import post_generator\nx = getattr(post_generator, "POSTS_DIR")\n',
        'import common.post_generator\nx = getattr(common.post_generator, "SITE_DIR")\n',
        'x = getattr(import_module("common.post_generator"), "REPO_ROOT")\n',
        # Form 4 — attribute read straight off an inline import_module call.
        'x = importlib.import_module("common.post_generator").REPO_ROOT\n',
        'x = import_module("scripts.common.post_generator").POSTS_DIR\n',
    )
    for snippet in bad:
        assert _offenders_in(snippet), f"detector missed: {snippet!r}"


def test_detector_spares_legitimate_forms():
    """The detector must NOT flag the sanctioned redirect / non-root forms."""
    good = (
        # Object-form setattr — module is an arg, name is a string. No attr-read node.
        'import common.post_generator as pg\nmonkeypatch.setattr(pg, "REPO_ROOT", str(tmp_path))\n',
        # String-target setattr/patch — a literal, not an attribute access.
        'monkeypatch.setattr("common.post_generator.REPO_ROOT", str(tmp_path))\n',
        'patch("common.post_generator.POSTS_DIR", str(tmp_path))\n',
        # Non-root attribute on a prod-module alias — out of scope.
        "import common.dedup as dedup\nx = dedup.STATE_DIR\n",
        "import common.signal_tracker as st\nx = st._HISTORY_FILE\n",
        # Local __file__ anchor (the sanctioned pattern) — an assignment, not import/alias.
        "_REPO_ROOT = Path(__file__).resolve().parent.parent\nx = _REPO_ROOT / '_state'\n",
        # Banned name as an attribute on a NON-production module.
        "import os\nx = os.REPO_ROOT\n",
        # setattr is the redirect, not a leak — form 3 must not swallow it.
        'import common.post_generator as pg\nsetattr(pg, "REPO_ROOT", str(tmp_path))\n',
        # getattr of a NON-banned attribute, and off a non-production module.
        'import common.dedup as dedup\nx = getattr(dedup, "STATE_DIR")\n',
        'import os\nx = getattr(os, "REPO_ROOT")\n',
        # Inline import of a non-production module.
        'x = importlib.import_module("json").REPO_ROOT\n',
    )
    for snippet in good:
        assert not _offenders_in(snippet), f"detector false-positive: {snippet!r}"
