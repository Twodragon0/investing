"""Invariant guard for `close-stale-ci-failure-issues.yml`.

## Why this needs a guard at all

The workflow closes issues in bulk. Three of its properties are the difference
between "housekeeping" and "silent data loss", and none of them is visible from
the workflow's name:

1. **Pagination.** `listForRepo` caps at 30 without `github.paginate`. The
   backlog this workflow exists to drain was 363 issues on 2026-08-24 — an
   unpaginated version would look like it ran fine while touching only the
   newest 30, forever.
2. **Human-intervention opt-out.** An issue somebody commented on, or labelled
   `keep`, has been triaged. Closing it discards that work.
3. **No silent cap.** `max_close` bounds each run. If the deferred count is not
   reported, a partial sweep reads as a complete one — the next person believes
   the backlog is drained when it is not.

These are exactly the properties a well-meaning simplification deletes, because
each looks like defensive clutter in isolation. The assertions below are pinned
to the *mechanism*, not the wording, so a rewrite that keeps the behaviour still
passes.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "close-stale-ci-failure-issues.yml"


@pytest.fixture(scope="module")
def source() -> str:
    return _WORKFLOW.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def parsed() -> dict:
    return yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))


def _squash(text: str) -> str:
    """Collapse runs of whitespace so assertions survive reindentation."""
    return " ".join(text.split())


def _script(parsed: dict) -> str:
    """The github-script body — the only place the closing logic lives."""
    for step in parsed["jobs"]["close-stale"]["steps"]:
        script = (step.get("with") or {}).get("script")
        if script:
            return script
    pytest.fail("close-stale job has no github-script step")


class TestPagination:
    def test_issue_listing_paginates(self, parsed: dict) -> None:
        assert "github.paginate(github.rest.issues.listForRepo" in _script(parsed), (
            "must page through all open ci-failure issues; a bare `listForRepo` "
            "silently caps at 30 and the backlog (363 on 2026-08-24) never drains"
        )

    def test_requests_full_pages(self, parsed: dict) -> None:
        assert "per_page: 100" in _script(parsed)


class TestHumanOptOut:
    def test_keep_label_is_honoured(self, parsed: dict) -> None:
        assert "'keep'" in _script(parsed), "a `keep` label must exempt an issue from closing"

    def test_commented_issues_are_exempt(self, parsed: dict) -> None:
        """A comment means a human engaged — closing it discards triage."""
        script = _script(parsed)
        assert "(issue.comments || 0) > 0" in _squash(script), (
            "issues with comments must be exempt via an explicit gate; a mere "
            "mention of `issue.comments` in a log message is not the exemption. "
            "Without it, triaged issues get closed alongside untouched noise"
        )

    def test_age_threshold_is_applied(self, parsed: dict) -> None:
        """Closing must be gated on staleness, not run unconditionally.

        Asserted on the comparison itself: `updated_at` and `cutoff` also appear
        in log/summary strings, so their mere presence proves nothing.
        """
        squashed = _squash(_script(parsed))
        assert "const cutoff = new Date(Date.now() - ageDays" in squashed, (
            "the staleness cutoff must be derived from the age_days input"
        )
        assert "if (new Date(issue.updated_at) >= cutoff)" in squashed, (
            "recently-updated issues must be exempted by an explicit comparison "
            "against the cutoff — without it every open ci-failure issue is closed "
            "on the first run regardless of age"
        )


class TestNoSilentCap:
    def test_cap_exists(self, parsed: dict) -> None:
        assert "maxClose" in _script(parsed), "each run must bound how many issues it closes"

    def test_deferred_count_is_reported(self, parsed: dict) -> None:
        """A cap that is not reported turns a partial sweep into a false 'done'."""
        script = _script(parsed)
        squashed = _squash(script)
        assert "const deferred = candidates.length - target.length" in squashed, (
            "the count left behind by the cap must be computed"
        )
        assert "if (deferred > 0)" in squashed, (
            "the deferred count must be reported through an explicit branch — a "
            "silent cap reads as full coverage to the next person"
        )
        assert "이월" in script, "the deferred count must appear in the job summary text"

    def test_writes_a_job_summary(self, parsed: dict) -> None:
        assert "core.summary" in _script(parsed), "bulk issue closure must leave an auditable per-run record"


class TestFailureHandling:
    def test_per_issue_errors_do_not_abort_the_sweep(self, parsed: dict) -> None:
        script = _script(parsed)
        assert "catch" in script, "one unclosable issue must not strand the rest"

    def test_total_failure_is_surfaced(self, parsed: dict) -> None:
        """Catching every error without ever failing is a fail-open sweep."""
        assert "if (failed.length > 0 && closed.length === 0)" in _squash(_script(parsed)), (
            "if nothing could be closed the job must fail — otherwise a "
            "permissions or rate-limit outage looks like an empty backlog. "
            "The `core.setFailed` calls that validate inputs do not cover this."
        )


class TestWorkflowWiring:
    def test_permissions_are_least_privilege(self, parsed: dict) -> None:
        perms = parsed["permissions"]
        assert perms.get("issues") == "write"
        assert perms.get("contents") == "read", "this workflow must not need write access to the tree"

    def test_grants_actions_read_for_the_reusable_alert(self, parsed: dict) -> None:
        """A reusable workflow inherits the *caller's* permissions.

        `alert-consecutive-failures.yml` reads run history, so it declares
        `actions: read`. Omitting it here does not fail loudly at author time —
        `actionlint` passes, the YAML is valid — the alert job simply cannot run.
        Caught in CI by `scripts/tools/check_workflow_permissions.py`; asserted
        here so the reason lives next to the workflow it constrains.
        """
        assert parsed["permissions"].get("actions") == "read", (
            "the alert-consecutive-failures call needs `actions: read` from its "
            "caller; without it the failure alerting silently cannot run"
        )

    def test_concurrency_group_is_ref_scoped(self, parsed: dict) -> None:
        """A constant group cancels unrelated runs — measured on supply-chain-lock.yml.

        There, `group: supply-chain-lock` with `cancel-in-progress: true` meant
        16 of 25 recent runs were cancelled, so the gate mostly did not run.
        """
        group = parsed["concurrency"]["group"]
        assert "${{" in group, f"concurrency group must be ref/PR-scoped, got {group!r}"

    def test_dry_run_is_available(self, parsed: dict) -> None:
        """Bulk closure needs a preview mode before the first real sweep."""
        # PyYAML 1.1 은 bare `on:` 을 boolean True 로 읽는다 — 저장소 관례와 동일하게
        # 두 키를 모두 본다 (tests/test_workflow_alerting_coverage_guard.py:81).
        triggers = parsed.get("on", parsed.get(True))
        inputs = triggers["workflow_dispatch"]["inputs"]
        assert "dry_run" in inputs
        squashed = _squash(_script(parsed))
        assert "const dryRun = process.env.DRY_RUN === 'true'" in squashed, (
            "the dry_run input must be read into the script"
        )
        assert "if (dryRun)" in squashed, "the dry_run flag must actually gate the close calls, not merely exist"

    def test_has_failure_alerting(self, parsed: dict) -> None:
        """Enforced repo-wide by test_workflow_alerting_coverage_guard; asserted
        here too so the reason travels with this workflow: if this job dies
        quietly the tracker refills to the state that motivated it."""
        jobs = parsed["jobs"]
        assert "alert-consecutive-failures" in jobs
        assert jobs["alert-consecutive-failures"]["uses"] == ("./.github/workflows/alert-consecutive-failures.yml")
