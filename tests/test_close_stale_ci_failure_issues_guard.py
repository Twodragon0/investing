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

## 두 층으로 본다 (2026-09-15)

`TestBehaviour` 는 스크립트 본문을 **실제로 실행**하고 무엇이 닫혔는지 본다.
나머지 클래스는 소스 텍스트를 단언한다. 둘 다 두는 이유는 서로 다른 것을 잡기
때문이다.

텍스트 단언만 있을 때의 맹점을 2026-09-13 에 실측했다: 코멘트 게이트의
`continue;` **한 줄만** 지우면 사람이 트리아지한 이슈가 요약에 "kept" 로
기록되면서 **동시에 닫힌다** — 감사 기록이 거짓말을 하는 형태다. 그런데 가드
15건이 전부 통과했다. 단언이 `"(issue.comments || 0) > 0"` 문자열만 보므로
제어 흐름을 볼 수 없기 때문이다.

반대로 텍스트 단언은 실행 관측이 닿지 않는 것을 잡는다 — 예컨대
`per_page: 100` 이 빠져도 목(mock)은 여전히 모든 이슈를 돌려주므로 행동으로는
구별되지 않는다. 실제 API 의 30건 상한은 목에 없다.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import UTC, datetime, timedelta
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


# ---------------------------------------------------------------------------
# 행동 관측 — github-script 본문을 실제로 실행한다
# ---------------------------------------------------------------------------

_RUNNER = Path(__file__).resolve().parent / "_github_script_runner.js"


def _node() -> str:
    """Node 인터프리터 경로.

    CI 에서는 **skip 하지 않는다.** 로컬에 node 가 없어 skip 하는 것은 괜찮지만,
    CI 에서 조용히 skip 되면 이 층 전체가 green 으로 위장한다 — 2026-09-13 에
    다른 가드에서 겪은 함정이다(제한 PATH 로 7건 skip 되자 rc=0 이 나왔다).
    GitHub 호스티드 러너에는 node 가 기본 포함된다.
    """
    node = shutil.which("node")
    if node:
        return node
    if os.environ.get("CI"):
        pytest.fail("CI 에 node 가 없다 — 이 층을 skip 하면 행동 검증이 통째로 사라진다")
    pytest.skip("로컬에 node 가 없다 (CI 에서는 실행된다)")


def _issue(number: int, *, days_old: int, comments: int = 0, labels: tuple[str, ...] = ()) -> dict:
    updated = datetime.now(tz=UTC) - timedelta(days=days_old)
    return {
        "number": number,
        "updated_at": updated.isoformat().replace("+00:00", "Z"),
        "comments": comments,
        "labels": [{"name": n} for n in labels],
    }


def _run(
    script: str,
    issues: list[dict],
    *,
    age_days: int = 30,
    max_close: int = 10,
    dry_run: bool = False,
    fail_on: tuple[int, ...] = (),
) -> dict:
    payload = {
        "script": script,
        "issues": issues,
        "failOnIssueNumbers": list(fail_on),
        "env": {"AGE_DAYS": age_days, "MAX_CLOSE": max_close, "DRY_RUN": "true" if dry_run else "false"},
    }
    proc = subprocess.run(
        [_node(), str(_RUNNER)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, f"러너 실패: {proc.stderr}"
    return json.loads(proc.stdout)


class TestBehaviour:
    """무엇이 **실제로 닫혔는가**를 묻는다.

    요약 텍스트가 아니라 `issues.update({state: 'closed'})` 호출을 관측한다.
    둘이 어긋나는 것이 이 층이 잡는 회귀다.
    """

    def test_stale_untouched_issue_is_closed(self, parsed: dict) -> None:
        """기준선 — 이게 없으면 아래 '닫히지 않는다' 단언들이 전부 vacuous 하다."""
        out = _run(_script(parsed), [_issue(1, days_old=90)])

        assert out["closed"] == [1], f"stale 이슈를 닫지 않았다: {out}"

    def test_commented_issue_is_never_closed(self, parsed: dict) -> None:
        """사람이 코멘트로 트리아지한 이슈는 닫히면 안 된다.

        2026-09-13 실측: 코멘트 게이트의 `continue;` 한 줄을 지우면 이 이슈가
        요약에 "kept" 로 기록되면서 **동시에 닫힌다**. 텍스트 단언 15건이 전부
        통과했다 — 이 테스트가 그 맹점을 덮는다.
        """
        out = _run(_script(parsed), [_issue(1, days_old=90, comments=3)])

        assert out["closed"] == [], f"사람이 트리아지한 이슈가 닫혔다: {out['closed']}"
        assert "코멘트" in out["summary"], "kept 사유가 요약에 남아야 한다"

    def test_keep_labelled_issue_is_never_closed(self, parsed: dict) -> None:
        out = _run(_script(parsed), [_issue(1, days_old=90, labels=("ci-failure", "keep"))])

        assert out["closed"] == [], f"keep 라벨 이슈가 닫혔다: {out['closed']}"

    def test_recently_updated_issue_is_never_closed(self, parsed: dict) -> None:
        out = _run(_script(parsed), [_issue(1, days_old=1)], age_days=30)

        assert out["closed"] == [], f"최근 갱신 이슈가 닫혔다: {out['closed']}"

    def test_cap_limits_closures_and_defers_the_rest(self, parsed: dict) -> None:
        """상한이 실제로 닫는 건수를 제한하고, 남은 수가 보고되어야 한다."""
        issues = [_issue(n, days_old=90 + n) for n in range(1, 6)]

        out = _run(_script(parsed), issues, max_close=2)

        assert len(out["closed"]) == 2, f"상한 2인데 {len(out['closed'])}건 닫았다"
        assert "이월" in out["summary"], "이월 건수가 요약에 없다"
        assert any("3" in n for n in out["notices"]), f"이월 3건이 notice 에 없다: {out['notices']}"

    def test_oldest_are_closed_first(self, parsed: dict) -> None:
        """상한에 걸릴 때 가장 오래된 것부터 닫아야 한다 — 정렬이 뒤집히면
        최신 것만 반복해 닫고 오래된 backlog 는 영원히 남는다."""
        issues = [_issue(1, days_old=40), _issue(2, days_old=400), _issue(3, days_old=200)]

        out = _run(_script(parsed), issues, max_close=1)

        assert out["closed"] == [2], f"가장 오래된 #2 가 아니라 {out['closed']} 를 닫았다"

    def test_dry_run_closes_nothing(self, parsed: dict) -> None:
        out = _run(_script(parsed), [_issue(1, days_old=90)], dry_run=True)

        assert out["closed"] == [], f"dry-run 이 실제로 닫았다: {out['closed']}"
        assert out["commented"] == [], "dry-run 이 코멘트를 달았다"
        assert "DRY RUN" in out["summary"]

    def test_one_failure_does_not_abort_the_sweep(self, parsed: dict) -> None:
        """한 건이 실패해도 나머지는 닫히고, 실패는 집계에 남아야 한다."""
        issues = [_issue(n, days_old=100 + n) for n in (1, 2, 3)]

        out = _run(_script(parsed), issues, fail_on=(2,))

        assert 2 not in out["closed"], "실패한 이슈가 닫힌 것으로 집계됐다"
        assert sorted(out["closed"]) == [1, 3], f"실패 한 건이 스윕을 중단시켰다: {out['closed']}"
        assert any("#2" in w for w in out["warnings"]), f"실패가 보고되지 않았다: {out['warnings']}"

    def test_pagination_is_used_for_listing(self, parsed: dict) -> None:
        """`paginate` 를 거치지 않으면 실제 API 는 30건에서 잘린다."""
        out = _run(_script(parsed), [_issue(1, days_old=90)])

        assert out["paginateUsed"], "listForRepo 를 github.paginate 로 감싸지 않았다"
        assert out["listArgs"]["labels"] == "ci-failure"
        assert out["listArgs"]["state"] == "open"
