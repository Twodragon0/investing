"""Lightweight golden-file helper for snapshot-style regression tests.

Usage:
    from tests._golden import assert_golden
    assert_golden("category/case", actual_str)

The first time a golden is missing, run with `UPDATE_GOLDEN=1` env var to
record. Subsequent runs compare strict-equal. Diff on failure uses unified
diff for readability.
"""

from __future__ import annotations

import difflib
import os
from pathlib import Path

_SNAPSHOT_ROOT = Path(__file__).parent / "snapshots"


def _normalize(text: str) -> str:
    """Normalize line endings and trailing whitespace for diff stability."""
    text = text.replace("\r\n", "\n")
    return "\n".join(line.rstrip() for line in text.split("\n"))


def _resolve(name: str) -> Path:
    """Resolve snapshot path. `name` may contain `/` to nest directories."""
    return _SNAPSHOT_ROOT / f"{name}.txt"


def assert_golden(name: str, actual: str) -> None:
    """Compare *actual* against the recorded golden for *name*.

    If `UPDATE_GOLDEN=1` is set in the environment, the golden is written
    (overwriting any existing file). The golden file is normalized before
    storage and comparison.
    """
    path = _resolve(name)
    actual_norm = _normalize(actual)

    if os.environ.get("UPDATE_GOLDEN") == "1":
        # Regeneration is a local operation. If this ever ran in CI — a repo-level
        # env var, a copy-pasted step — every snapshot would rewrite itself and
        # pass, so the whole golden suite would prove nothing while staying
        # green. That is the failure mode goldens exist to prevent, so refuse
        # loudly rather than silently rewrite.
        if os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"):
            raise AssertionError(
                "UPDATE_GOLDEN=1 is set in CI. Regenerating snapshots there makes "
                "every golden test vacuous — it would rewrite the expected output "
                "and pass. Regenerate locally, review the diff, and commit it."
            )
        # The runtime tree-write detector refuses writes into the committed
        # tree, which is what a snapshot *is*. Regenerating a golden is the one
        # deliberate exception: the operator asked for it by name via the env
        # var, so suspend the guard for exactly this write rather than
        # exempting `tests/snapshots/` wholesale (which would also let an
        # accidental write through).
        # Imported bare, matching how `conftest.py` loads it. `tests.` -prefixed
        # and bare imports resolve to *different module objects* with separate
        # `_INSTALLED` registries, so the prefixed one would suspend a guard
        # nobody installed.
        from _tree_write_guard import suspended

        with suspended():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(actual_norm, encoding="utf-8")
        return

    if not path.exists():
        raise AssertionError(
            f"Golden missing: {path}. Run with UPDATE_GOLDEN=1 to create it after reviewing the output."
        )

    expected_norm = _normalize(path.read_text(encoding="utf-8"))
    if actual_norm == expected_norm:
        return

    diff = "\n".join(
        difflib.unified_diff(
            expected_norm.splitlines(),
            actual_norm.splitlines(),
            fromfile=f"golden:{name}",
            tofile="actual",
            lineterm="",
        )
    )
    raise AssertionError(f"Golden mismatch for {name}:\n{diff}")
