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

## Scope / known residual gap

This guard inspects ``ast.ImportFrom`` only. It deliberately does NOT flag
module-alias attribute access (``import common.post_generator as pg; pg.REPO_ROOT``
or ``from common import post_generator; post_generator.REPO_ROOT``). No current
test uses that form, and catching it would require resolving alias bindings at
the risk of false-positives on the legitimate ``monkeypatch.setattr(mod,
"REPO_ROOT", ...)`` object form. The direct ``from <prod> import <root>`` form is
the canonical real-tree-write vector and the one the incident used.

Direction: presence check — any banned production root import trips. If a future
test legitimately needs to *read* a repo file, derive a local ``__file__`` anchor
instead of importing the production constant.
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


def _scan() -> tuple[list[str], list[str]]:
    """Return (offenders, unparseable) — both as ``path:line`` / ``path`` strings."""
    offenders: list[str] = []
    unparseable: list[str] = []
    for path in _py_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            unparseable.append(str(path.relative_to(TESTS_DIR.parent)))
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and _is_production_module(node.module):
                if any(alias.name in _BANNED_NAMES for alias in node.names):
                    offenders.append(f"{path.relative_to(TESTS_DIR.parent)}:{node.lineno}")
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
        "테스트가 production 실제-트리 루트 상수를 import 했습니다 (비-격리 실제-트리 쓰기 위험):\n"
        + "\n".join(f"  - {o}" for o in offenders)
        + "\n\n실제 repo 트리에 쓰지 말고, 대상 모듈의 루트 상수를 tmp 로 monkeypatch 하세요:\n"
        '    monkeypatch.setattr("common.post_generator.REPO_ROOT", str(tmp_path))\n'
        f"금지 상수: {_BANNED_NAMES}. 의도된 변경이면 이 가드의 docstring/_BANNED_NAMES 를 함께 갱신하세요."
    )
