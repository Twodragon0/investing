"""Regression guard: pip-audit ``--ignore-vuln`` lists must stay synchronized
across the two workflows that run pip-audit.

Incident (2026-06-22): ``code-quality.yml`` suppressed PYSEC-2022-252
(deep-translator, no upstream fix) via ``--ignore-vuln`` but the dedicated
``dependency-check.yml`` gate did NOT carry the same flag, so the weekly
security job failed every Monday (silent chronic red, last green 2026-05-25).

The documented decision (see the comment block in ``dependency-check.yml``)
is that the two workflows' ignore lists MUST be kept identical. This guard
enforces that invariant in two directions:

1. Cross-file: the SET of ignored vuln IDs in ``code-quality.yml`` equals the
   set in ``dependency-check.yml``.
2. Intra-file: every actual ``pip-audit`` command line in each file carries
   the file's full ignore set (so adding a second invocation that forgets a
   flag also trips the guard).

Direction: presence/equality — adding an ignore to ONE file without the other,
or dropping it from one, fails. If a divergence is intentional (e.g. a vuln
only reachable in one job), update BOTH this guard and the workflow comment.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_WORKFLOW_DIR = _REPO_ROOT / ".github" / "workflows"
_CODE_QUALITY = _WORKFLOW_DIR / "code-quality.yml"
_DEPENDENCY_CHECK = _WORKFLOW_DIR / "dependency-check.yml"

# Matches the actual CLI flag only (e.g. ``--ignore-vuln PYSEC-2022-252``);
# prose mentioning "ignore" or "pip-audit" in comments never matches.
_IGNORE_RE = re.compile(r"--ignore-vuln[ \t]+(\S+)")
# An actual pip-audit command line (after lstrip), not a comment line.
_AUDIT_CMD_RE = re.compile(r"^pip-audit(\s|$)")


def _ignore_ids(path: Path) -> set[str]:
    """Union of all vuln IDs ignored by any pip-audit invocation in the file."""
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    return set(_IGNORE_RE.findall(text))


def _audit_command_lines(path: Path) -> list[tuple[int, str]]:
    """Return (lineno, stripped_line) for each real ``pip-audit`` command line.

    Skips comment lines (``#``) so prose referencing pip-audit is ignored.
    """
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    out: list[tuple[int, str]] = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.lstrip(" \t")
        if stripped.startswith("#"):
            continue
        if _AUDIT_CMD_RE.match(stripped):
            out.append((lineno, stripped))
    return out


def test_target_workflows_exist() -> None:
    """Canary: both audited workflows exist so the guard is non-vacuous."""
    assert _CODE_QUALITY.is_file(), f"{_CODE_QUALITY} not found"
    assert _DEPENDENCY_CHECK.is_file(), f"{_DEPENDENCY_CHECK} not found"


def test_both_workflows_run_pip_audit() -> None:
    """Canary: each workflow has at least one real pip-audit command line."""
    assert _audit_command_lines(_CODE_QUALITY), (
        f"{_CODE_QUALITY.name}: no pip-audit command line found — guard would be vacuous"
    )
    assert _audit_command_lines(_DEPENDENCY_CHECK), (
        f"{_DEPENDENCY_CHECK.name}: no pip-audit command line found — guard would be vacuous"
    )


def test_ignore_lists_are_synchronized_across_workflows() -> None:
    """code-quality.yml and dependency-check.yml must ignore the same vuln IDs."""
    cq = _ignore_ids(_CODE_QUALITY)
    dc = _ignore_ids(_DEPENDENCY_CHECK)
    assert cq == dc, (
        "pip-audit --ignore-vuln lists have drifted between workflows.\n"
        f"  code-quality.yml:     {sorted(cq) or '(none)'}\n"
        f"  dependency-check.yml: {sorted(dc) or '(none)'}\n"
        f"  only in code-quality: {sorted(cq - dc) or '(none)'}\n"
        f"  only in dependency-check: {sorted(dc - cq) or '(none)'}\n"
        "Sync both workflows. If the divergence is intentional, update this "
        "guard and the comment block in dependency-check.yml."
    )


def test_every_pip_audit_invocation_carries_full_ignore_set() -> None:
    """Each pip-audit command must carry the file's complete ignore set.

    Guards against adding a second invocation that forgets a ``--ignore-vuln``
    flag — exactly the shape of the original incident (one blocking call
    lacked the suppression and went red).
    """
    offenders: list[str] = []
    for path in (_CODE_QUALITY, _DEPENDENCY_CHECK):
        expected = _ignore_ids(path)
        if not expected:
            continue
        for lineno, line in _audit_command_lines(path):
            present = set(_IGNORE_RE.findall(line))
            missing = expected - present
            if missing:
                offenders.append(f"{path.name}:L{lineno} missing {sorted(missing)} — {line[:90]}")
    assert not offenders, (
        "A pip-audit invocation is missing ignore flags its sibling calls carry "
        "(would re-trigger the chronic-red incident):\n  " + "\n  ".join(offenders)
    )
