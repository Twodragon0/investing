"""CI config regression guard: the required-check aggregator covers every job.

## Why an aggregator exists at all

A branch ruleset's *required status check* is matched by check name. If the
workflow that produces that check has a workflow-level `paths:` filter, then on a
PR that touches none of those paths the workflow never runs, the check is never
created, and the PR waits forever. The fix is to drop the `paths:` filter, gate
the expensive job with a job-level `if:`, and add an aggregator job that runs
unconditionally (`if: always()`) and reports one stable check name.

Two properties make that aggregator load-bearing, and both fail silently:

* **`needs:` completeness.** A new job added to the workflow but not wired into
  `needs:` is invisible to the gate: it can fail while the required check stays
  green. That is the same class of hole as a coverage gate that omits a module.
* **`if: always()`.** Without it the gate is skipped whenever an upstream job is
  skipped — which is the common case — and a skipped job that never *ran* is not
  the same as one GitHub reports as skipped. Drop it and the required check goes
  missing exactly on the PRs the aggregator was introduced to serve.

## Why the shard matrix is not required directly

`guard-falsifiability` fans out over 8 shards and names each check
`falsifiability (3/8)`. Registering those as required contexts couples branch
protection to the matrix size: change the shard count and every registered name
stops existing, so every PR waits forever. The aggregator's name is fixed.

Direction: presence (`needs:` must equal the full job set, `if: always()` must be
there). Text scan only, no PyYAML, per `docs/devsecops/ci-regression-guards.md`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_WORKFLOWS_DIR = _REPO_ROOT / ".github" / "workflows"

# workflow file -> aggregator job id that branch protection should require.
_AGGREGATORS: dict[str, str] = {
    "guard-falsifiability.yml": "gate",
}

# A job id at the canonical two-space indent under `jobs:`. Anchored so that
# nested mapping keys (`with:`, `env:`, matrix entries) cannot be mistaken for
# job ids.
_JOB_ID_RE = re.compile(r"^  (?P<job>[A-Za-z_][A-Za-z0-9_-]*):\s*$", re.M)


def _text(workflow: str) -> str:
    return (_WORKFLOWS_DIR / workflow).read_text(encoding="utf-8")


def _job_ids(text: str) -> list[str]:
    """Every job id in the workflow, in file order."""
    jobs_start = re.search(r"^jobs:\s*$", text, re.M)
    assert jobs_start, "no top-level `jobs:` mapping found"
    return [m.group("job") for m in _JOB_ID_RE.finditer(text[jobs_start.end() :])]


def _job_block(text: str, job_id: str) -> str:
    """The lines belonging to one job: from its id to the next id or EOF."""
    start = re.search(rf"^  {re.escape(job_id)}:\s*$", text, re.M)
    assert start, f"job `{job_id}` not found"
    rest = text[start.end() :]
    following = _JOB_ID_RE.search(rest)
    return rest[: following.start()] if following else rest


def _needs_of(block: str) -> set[str]:
    """`needs:` entries, accepting both inline `[a, b]` and block-list form."""
    inline = re.search(r"^\s{4}needs:\s*\[(?P<items>[^\]]*)\]\s*$", block, re.M)
    if inline:
        return {item.strip().strip("'\"") for item in inline.group("items").split(",") if item.strip()}

    scalar = re.search(r"^\s{4}needs:\s*(?P<one>[A-Za-z_][A-Za-z0-9_-]*)\s*$", block, re.M)
    if scalar:
        return {scalar.group("one")}

    header = re.search(r"^\s{4}needs:\s*$", block, re.M)
    if not header:
        return set()
    items: set[str] = set()
    # `\s*$` stops before the newline, so the remainder starts mid-line; without
    # lstrip the first splitlines() element is "" and the loop breaks at once.
    for line in block[header.end() :].lstrip("\n").splitlines():
        entry = re.match(r"^\s{6}-\s*(?P<item>[A-Za-z_][A-Za-z0-9_-]*)\s*$", line)
        if not entry:
            break
        items.add(entry.group("item"))
    return items


@pytest.mark.parametrize("workflow", sorted(_AGGREGATORS))
def test_workflow_and_aggregator_job_exist(workflow: str) -> None:
    """Canary: a renamed workflow or job fails loudly, not vacuously."""
    path = _WORKFLOWS_DIR / workflow
    assert path.is_file(), f"{path} not found"
    assert _AGGREGATORS[workflow] in _job_ids(_text(workflow)), (
        f"aggregator job `{_AGGREGATORS[workflow]}` missing from {workflow}. If it was "
        "renamed, update _AGGREGATORS *and* the required status check in the branch ruleset."
    )


@pytest.mark.parametrize("workflow", sorted(_AGGREGATORS))
def test_aggregator_needs_every_other_job(workflow: str) -> None:
    """A job outside `needs:` can fail while the required check stays green."""
    text = _text(workflow)
    aggregator = _AGGREGATORS[workflow]
    expected = set(_job_ids(text)) - {aggregator}
    actual = _needs_of(_job_block(text, aggregator))

    missing = sorted(expected - actual)
    assert not missing, (
        f"{workflow}: job(s) {missing} are not in `{aggregator}.needs`. They can fail "
        f"while the `{aggregator}` required check reports success. Add them to `needs:` "
        "and handle their result in the gate step."
    )
    unknown = sorted(actual - expected)
    assert not unknown, f"{workflow}: `{aggregator}.needs` names non-existent job(s) {unknown}"


@pytest.mark.parametrize("workflow", sorted(_AGGREGATORS))
def test_aggregator_runs_unconditionally(workflow: str) -> None:
    """Without `if: always()` the gate vanishes whenever an upstream job skips."""
    block = _job_block(_text(workflow), _AGGREGATORS[workflow])
    assert re.search(r"^\s{4}if:\s*always\(\)\s*$", block, re.M), (
        f"{workflow}: aggregator `{_AGGREGATORS[workflow]}` must declare `if: always()`. "
        "Otherwise it is skipped when an upstream job is skipped, the required check is "
        "never reported, and every such PR blocks."
    )


@pytest.mark.parametrize("workflow", sorted(_AGGREGATORS))
def test_aggregated_workflow_has_no_pull_request_path_filter(workflow: str) -> None:
    """A `paths:` filter on the PR trigger defeats the whole arrangement.

    With one, the workflow does not run on unrelated PRs, so the aggregator's
    check is never created — the exact failure the aggregator exists to avoid.
    """
    text = _text(workflow)
    pr_trigger = re.search(r"^  pull_request:\s*$", text, re.M)
    assert pr_trigger, f"{workflow}: no `pull_request:` trigger — it cannot gate PRs at all"

    for line in text[pr_trigger.end() :].splitlines():
        if re.match(r"^  \S", line):  # next top-level trigger
            break
        assert not re.match(r"^\s{4}paths(-ignore)?:\s*$", line), (
            f"{workflow}: the `pull_request` trigger has a `paths:` filter. The aggregator "
            f"check `{_AGGREGATORS[workflow]}` then goes missing on PRs that touch none of "
            "those paths, blocking them forever. Gate the expensive job with a job-level "
            "`if:` instead."
        )


def test_job_id_scanner_rejects_nested_keys() -> None:
    """The scanner must not mistake nested mapping keys for job ids.

    If `_JOB_ID_RE` loosened to any `key:` line, `_job_ids` would return `with`,
    `env`, `steps`... and `test_aggregator_needs_every_other_job` would demand
    they appear in `needs:` — failing for the wrong reason, or, if the comparison
    were inverted, passing vacuously.
    """
    sample = "jobs:\n  build:\n    steps:\n      - uses: x\n        with:\n          k: v\n  gate:\n    if: always()\n"
    assert _job_ids(sample) == ["build", "gate"]

    assert _needs_of("    needs: [a, b]\n") == {"a", "b"}
    assert _needs_of("    needs: solo\n") == {"solo"}
    assert _needs_of("    needs:\n      - a\n      - b\n") == {"a", "b"}
    assert _needs_of("    runs-on: ubuntu-latest\n") == set()
