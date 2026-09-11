"""CI config regression guard: the reusable-workflow permission lint stays wired.

`scripts/tools/check_workflow_permissions.py` exists because of the 2026-04-23
collector outage: `alert-consecutive-failures.yml` required `actions: read` but
all 13 `collect-*.yml` callers declared only `contents: write`, so every alert
path failed silently (postmortem: `docs/postmortem-2026-04-collector-outages.md`).

`tests/test_workflow_permission_lint.py` proves the *tool* detects that
mismatch, but it exercises the tool against synthetic `tmp_path` fixtures. It
would keep passing if CI stopped running the tool over the real workflow tree —
and then the outage class is unprotected again with a green suite. This guard
covers the wiring the unit tests cannot see.

## The three ways the wiring dies quietly

* **Step removed** — the tool still exists and its unit tests still pass; the
  real `.github/workflows` tree is simply never scanned.
* **Scope redirected** — `--workflows-dir` pointed at a fixture directory or an
  empty path keeps the step green while checking nothing.
* **Non-blocking** — `continue-on-error: true` or a `|| true` turns the lint
  into an annotation.

Direction: presence — extra permission checks stay green; only removing,
redirecting, or softening this one trips the test.

Text scan only (no PyYAML, and the checked tool is not imported so the guard
cannot move the coverage gate) per the guard conventions in
`docs/devsecops/ci-regression-guards.md`.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests import _workflow_scan as ws

_REPO_ROOT = Path(__file__).resolve().parent.parent
_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "code-quality.yml"
_LINT_TOOL = _REPO_ROOT / "scripts" / "tools" / "check_workflow_permissions.py"

# The lint is only meaningful against the live workflow tree.
_REQUIRED_SCOPE = ".github/workflows"

_TOOL_NAME = "check_workflow_permissions.py"
_STEP_START_RE = re.compile(r"^ *- name: ", re.M)
_CONTINUE_ON_ERROR_RE = re.compile(r"continue-on-error:\s*(\S+)")
_SWALLOW_RE = re.compile(r"(\|\||;)\s*(true|:)(?=\s|$)")
_WORKFLOWS_DIR_ARG_RE = re.compile(r"--workflows-dir[= ]+(\S+)")


def _lint_steps() -> list[dict]:
    """The `code-quality.yml` steps that invoke the permission lint.

    파싱된 step 매핑을 준다. 원문을 `- name:` 으로 잘라 훑던 방식은 스텝 안의
    주석에 매칭됐다 — 2026-09-11 실측: 스텝마다
    `# continue-on-error: true 는 여기서 쓰지 않는다` 를 넣으면 이 가드가 red 가
    됐다. 금지를 적은 주석이 그 금지를 강제하는 가드를 넘어뜨린 것이다.
    """
    return [step for step in ws.steps(_WORKFLOW) if _TOOL_NAME in ws.step_text(step)]


def test_gate_files_exist() -> None:
    """Canary: a moved/renamed tool or workflow fails loudly, not vacuously."""
    assert _WORKFLOW.is_file(), f"{_WORKFLOW} not found"
    assert _LINT_TOOL.is_file(), (
        f"{_LINT_TOOL} not found — the reusable-workflow permission lint was "
        f"deleted. See docs/postmortem-2026-04-collector-outages.md before "
        f"removing this guard."
    )


def test_permission_lint_runs_in_ci() -> None:
    """code-quality.yml must invoke the permission lint."""
    assert _lint_steps(), (
        f"code-quality.yml no longer runs `{_TOOL_NAME}`. The tool's unit tests "
        f"still pass against tmp_path fixtures, so nothing else notices that the "
        f"real workflow tree stopped being checked — this is exactly the 2026-04-23 "
        f"outage class. Restore the step, or delete this guard with justification."
    )


def test_permission_lint_scans_the_real_workflow_tree() -> None:
    """`--workflows-dir` must point at `.github/workflows`.

    Redirected at a fixture directory the step exits 0 forever while the live
    callers drift out of compliance.
    """
    scopes = [scope for step in _lint_steps() for scope in _WORKFLOWS_DIR_ARG_RE.findall(ws.step_text(step))]
    assert scopes, (
        f"`{_TOOL_NAME}` is invoked without an explicit `--workflows-dir`; the "
        f"scanned scope is implicit and can drift. Pass `--workflows-dir {_REQUIRED_SCOPE}`."
    )

    wrong = [scope for scope in scopes if scope.strip("'\"").rstrip("/") != _REQUIRED_SCOPE]
    assert not wrong, (
        f"the permission lint scans {wrong} instead of `{_REQUIRED_SCOPE}` — "
        f"it passes without checking the workflows that actually run."
    )


def test_permission_lint_step_is_blocking() -> None:
    """A permission mismatch must fail the job.

    Checked at job level, step level, and in the shell command — any one of the
    three downgrades the gate to an annotation.
    """
    soft: list[str] = []

    doc = ws.load(_WORKFLOW)
    for job_id, job in (doc.get("jobs") or {}).items():
        if not isinstance(job, dict):
            continue
        value = job.get("continue-on-error")
        if value is not None and str(value).lower() != "false":
            soft.append(f"job `{job_id}` -> continue-on-error: {value}")

    for step in _lint_steps():
        value = step.get("continue-on-error")
        if value is not None and str(value).lower() != "false":
            soft.append(f"{step.get('name', '<unnamed step>')} -> continue-on-error: {value}")
        run = step.get("run")
        if isinstance(run, str):
            for line in ws.strip_shell_comments(run).splitlines():
                if _TOOL_NAME in line and _SWALLOW_RE.search(line):
                    soft.append(f"exit code swallowed by shell: {line.strip()}")

    assert not soft, "the permission lint is non-blocking (violations would not fail the job):\n" + "\n".join(
        f"  - {s}" for s in soft
    )
