"""CI config regression guard: the global coverage floor must not be silently
lowered.

Two independent gates enforce the ``scripts`` coverage floor and both must stay
at or above :data:`_MIN_FLOOR`:

* ``pyproject.toml`` — ``addopts = "--cov=scripts --cov-fail-under=NN"`` runs on
  every ``pytest`` invocation (local and CI).
* ``.github/workflows/code-quality.yml`` — a dedicated
  ``coverage report --fail-under=NN`` step re-checks the same data in CI.

The floor was ratcheted 55 -> 65 (P3-1/P3-2) -> 70 (P3-3) -> 73 -> 75 (both
2026-08-25) -> 77 (2026-08-26) -> 79 -> 80 -> 82 -> 83 (all 2026-08-27) to lock
existing coverage as a regression baseline. Without this guard the floor could be
quietly dropped back — re-opening the gap between "tests deleted" and "build still
green".

Every step is measured, not guessed. Actual total is **84.39%**
(20799/24645 statements), and the measurement is deterministic:

* local, same tree -> ``24645 3846 84%``
* CI noise baseline, 25 runs over 2026-08-18..08-25 -> spread **0.005pt**

The 83 step came from *deleting* dead code, not from new tests:
``enrich_existing_posts.py`` (133 stmts at 0%) had been a silent no-op for five
months — its card regex never followed a 2026-04 renderer change — so removing it
dropped 133 uncovered statements out of the denominator. Deleting **covered** code
does not help; it removes equal amounts from numerator and denominator.

So the headroom at 83 is orders of magnitude above the observed measurement
noise; this floor cannot go red from noise. What it *does* cost: a new
fully-untested script is allowed only up to ~466 statements before the gate trips
(``coverage`` rounds, so the effective threshold is 82.5%). For scale, scripts in
this repo run 43..824 statements.

The four largest low-coverage modules were all closed on 2026-08-27:
``backfill_post_summaries.py`` (831 stmts, 38% -> 99%),
``collect_geopolitical.py`` (490, 17% -> 99%),
``respond_ai_mentions.py`` (259, 20% -> 99%) and
``generate_weekly_report.py`` (216, 0% -> 99%). Re-derive the current worst
offenders before citing any list here — run
``pytest tests/ -m "not i18n_e2e" --cov-report=term-missing`` and sort by missed
statements. That is the intended ratchet — past that point, write tests or lower
the floor deliberately.

Why 83 and not 84: the tightest previously accepted headroom was the 73 step's
1.36pt / 462 statements. 83 gives **466** statements — four above that bar. 84
gives 220, far tighter than any step anyone has signed up for. The rule is: never
ratchet to a floor whose headroom is below the tightest headroom already accepted.

That bar is doing real work, not acting as a formality: earlier the same day the
80 step rejected 81 at **460** — two statements short — and 83 now clears it by
only four. Re-measure before assuming the next step is available; a small
regression elsewhere can make this floor the binding constraint.

An earlier note claimed a ~1.3pt run-to-run swing (2026-07-27, when the total was
~71%). That is no longer reproducible; the hermetic-test hardening since then
removed it. Re-measure before citing it again.

Direction: floor is ``>=`` — ratcheting UP (77 -> 78 ...) stays green; only
removing a gate or lowering it below 77 trips this test. If the floor is lowered
intentionally, update ``_MIN_FLOOR`` here AND both ``--fail-under`` values
together. The falsifiability harness derives its mutation anchors from the current
value (``guard_falsifiability._current_coverage_floor``), so ratcheting needs no
edit there.

The workflow gate that scopes coverage to ``summary_sections.py`` (a stricter
95% per-module floor) is intentionally excluded here — it is guarded separately
by ``test_summary_sections_coverage_floor.py``.

## A floor number is not a gate

A number alone proves nothing: four edits leave ``--fail-under=NN`` untouched
while making the gate meaningless, so each is asserted separately below.

* **Measurement scope** — narrowing ``--cov=scripts`` to a single well-tested
  module keeps the floor number intact while measuring almost nothing.
* **Omission** — ``coverage report --omit=...``, or an ``omit`` key under
  ``[tool.coverage.run]`` / ``[tool.coverage.report]``, silently drops the
  weakest modules out of the denominator.
* **continue-on-error** — a red gate that does not fail the job is not a gate.

Config parsing only (``tomllib`` for TOML, text scan for YAML; no import of the
measured source) so the guard cannot perturb the coverage gate it protects.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_PYPROJECT = _REPO_ROOT / "pyproject.toml"
_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "code-quality.yml"

# The global scripts coverage floor both gates must enforce.
_MIN_FLOOR = 83

# The measurement scope the floor is meaningful against. `--cov=scripts` in
# pyproject addopts applies to every pytest run; the CI step additionally names
# `scripts/common`. Anything narrower measures a hand-picked subset.
_REQUIRED_COV_SCOPE = "scripts"
_ALLOWED_COV_SCOPES = frozenset({"scripts", "scripts/common"})

# `--cov=X` only — `--cov-fail-under=N` has a `-`, not `=`, after `--cov`.
_COV_SCOPE_RE = re.compile(r"--cov=(\S+)")
_COV_FAIL_UNDER_RE = re.compile(r"--cov-fail-under=(\d+)")
_FAIL_UNDER_RE = re.compile(r"--fail-under=(\d+)")
_CONTINUE_ON_ERROR_RE = re.compile(r"continue-on-error:\s*(\S+)")
_STEP_START_RE = re.compile(r"^ *- name: ", re.M)


def _pyproject() -> dict:
    """Parsed pyproject.toml (parsing config is not importing measured source)."""
    return tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))


def _pytest_addopts() -> str:
    return _pyproject()["tool"]["pytest"]["ini_options"]["addopts"]


def _workflow_steps() -> list[str]:
    """The workflow split into per-step text blocks (`- name:` delimited)."""
    text = _WORKFLOW.read_text(encoding="utf-8")
    starts = [m.start() for m in _STEP_START_RE.finditer(text)]
    return [text[s:e] for s, e in zip(starts, [*starts[1:], len(text)], strict=True)]


def _global_coverage_report_lines() -> list[str]:
    """`coverage report --fail-under=N` lines that are NOT the per-module gate.

    The ``--include="*/summary_sections.py"`` line is a separate 95% gate owned
    by ``test_summary_sections_coverage_floor.py``.
    """
    text = _WORKFLOW.read_text(encoding="utf-8")
    return [
        line
        for line in text.splitlines()
        if "coverage report" in line and "--fail-under=" in line and "--include=" not in line
    ]


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
    global_lines = _global_coverage_report_lines()
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


# ---------------------------------------------------------------------------
# Gate *validity*: the four edits that keep `--fail-under=NN` intact while
# making it prove nothing. A floor is only as strong as what it measures.
# ---------------------------------------------------------------------------


def test_pyproject_coverage_scope_not_narrowed() -> None:
    """pytest addopts must measure the whole ``scripts`` tree.

    Narrowing to ``--cov=scripts/common/summary_sections.py`` leaves the floor
    number intact while measuring one already-well-tested module — every other
    script could lose its tests and the gate would stay green.
    """
    addopts = _pytest_addopts()
    scopes = _COV_SCOPE_RE.findall(addopts)
    assert scopes, f"pyproject addopts no longer sets `--cov=...`; the floor measures nothing. Got: {addopts!r}"
    assert _REQUIRED_COV_SCOPE in scopes, (
        f"pyproject coverage scope narrowed to {scopes} — must include "
        f"`--cov={_REQUIRED_COV_SCOPE}` so the floor covers the whole tree."
    )


def test_workflow_coverage_scope_not_narrowed() -> None:
    """The CI test step must not measure a subset narrower than ``scripts/common``."""
    text = _WORKFLOW.read_text(encoding="utf-8")
    scopes = set(_COV_SCOPE_RE.findall(text))
    assert scopes, "code-quality.yml no longer passes `--cov=...` to pytest; CI measures nothing."

    narrowed = sorted(s for s in scopes if s not in _ALLOWED_COV_SCOPES)
    assert not narrowed, (
        f"code-quality.yml measures narrowed coverage scope(s) {narrowed}. "
        f"Allowed: {sorted(_ALLOWED_COV_SCOPES)}. A narrower scope inflates the "
        f"percentage without changing the floor."
    )


def test_workflow_coverage_gate_steps_are_blocking() -> None:
    """The coverage gate steps must fail the job — no ``continue-on-error``.

    Checked at both step and job level: either one turns a red gate into an
    annotation. ``continue-on-error: false`` is explicit and allowed.
    """
    gate_steps = [s for s in _workflow_steps() if "coverage report" in s and "--fail-under=" in s]
    assert gate_steps, "no `coverage report --fail-under=N` step found in code-quality.yml — the gate is gone."

    soft: list[str] = []
    for step in gate_steps:
        match = _CONTINUE_ON_ERROR_RE.search(step)
        if match and match.group(1).lower() != "false":
            soft.append(f"{step.splitlines()[0].strip()} -> continue-on-error: {match.group(1)}")

    text = _WORKFLOW.read_text(encoding="utf-8")
    job_header = text.split("steps:", 1)[0]
    job_match = _CONTINUE_ON_ERROR_RE.search(job_header)
    if job_match and job_match.group(1).lower() != "false":
        soft.append(f"job-level -> continue-on-error: {job_match.group(1)}")

    assert not soft, "coverage gate is non-blocking (failures would not fail the job):\n" + "\n".join(
        f"  - {s}" for s in soft
    )


def test_workflow_coverage_gate_omits_nothing() -> None:
    """The global ``coverage report`` gate must not ``--omit`` modules.

    ``--omit="*/collect_*.py"`` drops the weakest files out of the denominator;
    the reported percentage climbs and the floor never notices.
    """
    offenders = [line.strip() for line in _global_coverage_report_lines() if "--omit" in line]
    assert not offenders, (
        "global coverage gate omits modules from measurement:\n"
        + "\n".join(f"  - {line}" for line in offenders)
        + "\n\nOmitting files inflates the percentage without changing --fail-under."
    )


def test_pyproject_coverage_config_omits_nothing() -> None:
    """``[tool.coverage.*]`` must not omit/narrow what is measured.

    ``--cov-config=pyproject.toml`` means an ``omit`` key here silently applies
    to *both* gates at once — the quietest way to lift the number.
    """
    coverage_cfg = _pyproject().get("tool", {}).get("coverage", {})
    offenders = [
        f"[tool.coverage.{section}] {key} = {coverage_cfg[section][key]!r}"
        for section in ("run", "report")
        for key in ("omit", "include")
        if key in coverage_cfg.get(section, {})
    ]
    assert not offenders, (
        "coverage config narrows what is measured, inflating the percentage the "
        "floor is checked against:\n" + "\n".join(f"  - {o}" for o in offenders)
    )
