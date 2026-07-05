"""CI config regression guard: the dedicated ``summary_sections`` coverage
floor must not be silently removed or lowered.

``scripts/common/summary_sections.py`` renders the daily-summary output and
carries heavy test investment (~98% at time of writing). The global
``--cov-fail-under=55`` (pyproject) and ``coverage report --fail-under=65``
(code-quality.yml) floors are far too low to catch a silent per-module
regression — deleting the module's tests would still leave the global build
green. ``code-quality.yml`` therefore runs a dedicated

    coverage report --include="*/summary_sections.py" --fail-under=95

step. This guard asserts that step still exists and that the floor is not
weakened below 95.

Direction: floor is ``>=`` — ratcheting the floor UP (95 -> 96 ...) stays
green; only removing the step or lowering it below 95 trips this test. If the
floor is lowered intentionally, update ``_MIN_FLOOR`` here AND the
``--fail-under`` value in the workflow together.

Text/regex scan of the workflow YAML (no YAML parser, no import of the
measured source) so the guard itself cannot perturb the coverage gate.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "code-quality.yml"

# The floor the workflow must enforce for summary_sections.py.
_MIN_FLOOR = 95

# Match: coverage report --include="*/summary_sections.py" ... --fail-under=NN
# Order-independent on the two flags; tolerant of surrounding args/quoting.
_INCLUDE_RE = re.compile(r"--include=[\"']?\*?/?summary_sections\.py[\"']?")
_FAIL_UNDER_RE = re.compile(r"--fail-under=(\d+)")


def test_workflow_exists() -> None:
    """Canary: a moved/renamed workflow fails loudly instead of vacuously."""
    assert _WORKFLOW.is_file(), f"{_WORKFLOW} not found"


def test_summary_sections_coverage_floor_enforced() -> None:
    """A coverage step must gate summary_sections.py at >= 95%."""
    text = _WORKFLOW.read_text(encoding="utf-8")

    # Find the physical line that scopes coverage to summary_sections.py.
    target_lines = [line for line in text.splitlines() if _INCLUDE_RE.search(line) and "coverage report" in line]
    assert target_lines, (
        "code-quality.yml no longer runs "
        '`coverage report --include="*/summary_sections.py" --fail-under=N`. '
        "The dedicated per-module coverage floor was removed — restore it or, "
        "if intentional, delete this guard with justification."
    )

    floors = [int(m.group(1)) for line in target_lines if (m := _FAIL_UNDER_RE.search(line)) is not None]
    assert floors, (
        "summary_sections coverage step exists but has no --fail-under floor; the gate is a no-op. Add --fail-under=95."
    )
    assert min(floors) >= _MIN_FLOOR, (
        f"summary_sections coverage floor lowered to {min(floors)} "
        f"(< {_MIN_FLOOR}). If intentional, update _MIN_FLOOR in this guard "
        f"and the --fail-under value in code-quality.yml together."
    )
