"""Regression guard: tests must not import a production ``REPO_ROOT`` constant.

## Incident this guards against

On 2026-06-30 several tests in ``test_post_generator.py`` imported the production
``REPO_ROOT`` from ``common.post_generator`` and wrote real files under
``REPO_ROOT/assets/images/generated/`` (cleaned up in ``finally``). On abnormal
termination those untracked artifacts leaked into the working tree — the exact
filesystem-state-divergence class that made the ``TestGoldenMasterSummarySections``
SHA256 golden master pass locally (images present) but fail in CI (images absent).

## The invariant

A test that needs to exercise code resolving paths against a module-level
``REPO_ROOT`` (e.g. ``common.post_generator._resolve_post_image``,
``common.image_generator``, ``check_post_images``) MUST redirect that constant to
a per-test tmp dir:

    monkeypatch.setattr("common.post_generator.REPO_ROOT", str(tmp_path))

— a string-target ``setattr`` that does NOT import the symbol. Conversely,
``from common.<mod> import REPO_ROOT`` (or ``import ... as``) pulls the *real*
repo root into the test namespace, whose only use is composing real-tree paths;
that is the precise signal of a non-hermetic real-tree write and is banned here.

Test-file-local anchors (``REPO_ROOT = Path(__file__).resolve().parent.parent``)
used by read-only config guards are assignments, not imports, so they are NOT
flagged. This guard AST-scans (ignoring comments/strings), so the docstrings and
``monkeypatch.setattr("...REPO_ROOT...")`` string literals above never trip it.

Direction: presence check — any production ``REPO_ROOT`` import trips. If a future
test legitimately needs to *read* a repo file, derive a local ``__file__`` anchor
instead of importing the production constant.
"""

from __future__ import annotations

import ast
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent

# Modules whose ``REPO_ROOT`` is the *production* repo root (resolves to the real
# working tree). ``PYTHONPATH=scripts`` means tests import as ``common.*``; the
# ``scripts.*`` spellings are covered for completeness.
_PROD_PREFIXES = ("common", "scripts.common", "scripts")
_BANNED_NAME = "REPO_ROOT"


def _is_production_module(module: str | None) -> bool:
    if not module:
        return False
    return module in _PROD_PREFIXES or any(module.startswith(p + ".") for p in _PROD_PREFIXES)


def _py_files() -> list[Path]:
    return [p for p in TESTS_DIR.rglob("*.py") if "__pycache__" not in p.parts]


def _offenders() -> list[str]:
    offenders: list[str] = []
    for path in _py_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):  # pragma: no cover - unparsable file
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and _is_production_module(node.module):
                if any(alias.name == _BANNED_NAME for alias in node.names):
                    offenders.append(f"{path.relative_to(TESTS_DIR.parent)}:{node.lineno}")
    return offenders


def test_tests_dir_scanned_nonvacuous():
    """Canary: a broken glob must fail loudly, not pass vacuously."""
    files = _py_files()
    assert len(files) >= 50, f"expected to scan the test suite, only found {len(files)} files"


def test_no_test_imports_production_repo_root():
    offenders = _offenders()
    assert not offenders, (
        "테스트가 production REPO_ROOT 를 import 했습니다 (비-격리 실제-트리 쓰기 위험):\n"
        + "\n".join(f"  - {o}" for o in offenders)
        + "\n\n실제 repo 트리에 쓰지 말고, 대상 모듈의 REPO_ROOT 를 tmp 로 monkeypatch 하세요:\n"
        '    monkeypatch.setattr("common.post_generator.REPO_ROOT", str(tmp_path))\n'
        "의도된 변경이면 이 가드의 docstring/_PROD_PREFIXES 를 함께 갱신하세요."
    )
