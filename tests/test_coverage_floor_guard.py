"""CI config regression guard: the global coverage floor must not be silently
lowered.

Two independent gates enforce the ``scripts`` coverage floor and both must stay
at or above :data:`_MIN_FLOOR`:

* ``pyproject.toml`` — ``addopts = "--cov=scripts --cov-fail-under=NN"`` runs on
  every ``pytest`` invocation (local and CI).
* ``.github/workflows/code-quality.yml`` — a dedicated
  ``coverage report --fail-under=NN`` step re-checks the same data in CI.

Total ``scripts`` coverage sits ~68% (2026-07); the floor was ratcheted
55 -> 65 (P3-1/P3-2) to lock the existing coverage as a regression baseline.
Without this guard the floor could be quietly dropped back — re-opening the gap
between "tests deleted" and "build still green".

Direction: floor is ``>=`` — ratcheting UP (65 -> 70 ...) stays green; only
removing a gate or lowering it below 65 trips this test. If the floor is lowered
intentionally, update ``_MIN_FLOOR`` here AND both ``--fail-under`` values
together.

The workflow gate that scopes coverage to ``summary_sections.py`` (a stricter
95% per-module floor) is intentionally excluded here — it is guarded separately
by ``test_summary_sections_coverage_floor.py``.

Text/regex scan only (no YAML parser, no import of the measured source) so the
guard cannot perturb the coverage gate it protects.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_PYPROJECT = _REPO_ROOT / "pyproject.toml"
_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "code-quality.yml"

# The global scripts coverage floor both gates must enforce.
_MIN_FLOOR = 65

_COV_FAIL_UNDER_RE = re.compile(r"--cov-fail-under=(\d+)")
_FAIL_UNDER_RE = re.compile(r"--fail-under=(\d+)")


def test_config_files_exist() -> None:
    """Canary: a moved/renamed config fails loudly instead of vacuously."""
    assert _PYPROJECT.is_file(), f"{_PYPROJECT} not found"
    assert _WORKFLOW.is_file(), f"{_WORKFLOW} not found"


def test_pyproject_coverage_floor_enforced() -> None:
    """pyproject.toml must gate scripts coverage at >= 65%."""
    text = _PYPROJECT.read_text(encoding="utf-8")

    floors = [int(m.group(1)) for m in _COV_FAIL_UNDER_RE.finditer(text)]
    assert floors, (
        "pyproject.toml no longer sets `--cov-fail-under=N`. The global "
        "coverage floor was removed — restore it or, if intentional, delete "
        "this guard with justification."
    )
    assert min(floors) >= _MIN_FLOOR, (
        f"pyproject.toml coverage floor lowered to {min(floors)} "
        f"(< {_MIN_FLOOR}). If intentional, update _MIN_FLOOR in this guard "
        f"and both --fail-under values (pyproject + code-quality.yml) together."
    )


def test_workflow_global_coverage_floor_enforced() -> None:
    """code-quality.yml must re-check the global coverage floor at >= 65%.

    Only the *global* ``coverage report --fail-under=N`` line counts — the
    ``--include="*/summary_sections.py"`` line is a separate per-module gate.
    """
    text = _WORKFLOW.read_text(encoding="utf-8")

    global_lines = [
        line
        for line in text.splitlines()
        if "coverage report" in line and "--fail-under=" in line and "--include=" not in line
    ]
    assert global_lines, (
        "code-quality.yml no longer runs a global "
        "`coverage report --fail-under=N` step (without --include). The global "
        "coverage gate was removed — restore it or, if intentional, delete this "
        "guard with justification."
    )

    floors = [int(m.group(1)) for line in global_lines if (m := _FAIL_UNDER_RE.search(line)) is not None]
    assert floors, "global coverage report step exists but has no --fail-under floor; the gate is a no-op."
    assert min(floors) >= _MIN_FLOOR, (
        f"code-quality.yml global coverage floor lowered to {min(floors)} "
        f"(< {_MIN_FLOOR}). If intentional, update _MIN_FLOOR in this guard "
        f"and both --fail-under values (pyproject + code-quality.yml) together."
    )
