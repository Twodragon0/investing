"""Invariant guard for `backfill-url-summaries.yml`.

## Why this needs a guard

The job exists because the Google News redirect resolver is rate-limited and
**failed requests are not free — they extend the block**. Reference incident
(recorded in the workflow's own header): on 2026-08-06 consecutive runs saw
refetch yield collapse ``523 -> 71 -> 0``, with every link empty on the third
pass, while direct publisher URLs kept working. The ceiling is the resolver, not
the tool.

Four properties keep that from recurring, and each looks like removable caution
in isolation:

1. **`--skip-synthetic` is fixed.** Measured 2026-08-06 and again 2026-09-07:
   the synthetic fallback writes output that reads *worse* than the text it
   replaces (`"... 주요 키워드: 포트폴리오, 싶으신가요, 고려해야."`), and
   `improve_existing_posts` strips that very clause as a defect. Dropping the
   flag re-enables it silently — the run still reports success.
2. **`--limit` is present and bounded.** The budget is per-day, not per-run. An
   unbounded sweep spends it in one pass and the next day yields 0.
3. **At most one scheduled run per day.** A cron with `*` in the minute or hour
   field turns the daily budget into an hourly one.
4. **Yield 0 must not fail the job.** "The resolver is blocked today" is not a
   regression; making it red buries real failures in daily noise. Equally, the
   commit step must stay gated on a non-zero yield so an empty run cannot push.

A fifth is asserted for a reason from 2026-09-07: `--direct-only` skips every
Google News URL, which is 88.6% of the flagged population (2342 of 2643). It is
a legitimate *manual* lever while throttled, but on the schedule it would
silently narrow the job to ~11% of its target set while still reporting success.

Two more were added 2026-09-09, after measuring *why* the backlog never moved:

6. **`--order least-recently-tried` is fixed.** The default `newest` leaves a
   permanently unfixable blurb at the top of the window forever. Measured: the
   newest-200 window spanned 2026-08-06..09-09, so 2,403 flagged blurbs were
   unreachable *at any yield*, and the 2026-09-07 run failed 173 of its 200
   while 150 of the current window were those same August posts. Dropping the
   flag restores the stall silently — the run still reports success.
7. **The attempt log is cached across runs, and saved even on a failed run.**
   The log is what makes the window advance, and CI checkouts are fresh. It is
   deliberately *not* committed (the push step stages `_posts/` only), so
   `actions/cache` is the only carrier. The save step must be `if: always()`:
   the commit step is skipped on a zero-yield day, which is precisely the day
   whose "all 200 failed" record matters most.

The assertions read the step's `run:` script with **shell comments stripped**.
The header and inline commentary in this workflow name every flag asserted
below, so matching raw text would make the guard pass on its own documentation
after the flag itself was deleted.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "backfill-url-summaries.yml"

# Raising this ceiling is the change that spends a day's budget in one run.
_MAX_DEFAULT_LIMIT = 400

# The non-vacuity harness swaps `_WORKFLOW` for a temp copy (kept under the real
# basename) rather than passing a path in: pytest forbids default arguments on
# test functions, and a fixture parameter would not let a probe drive them.


def _strip_shell_comments(script: str) -> str:
    """Drop whole-line ``#`` comments from a shell script.

    Only whole-line comments: a trailing-``#`` rule would have to know about
    quoting, and this workflow's commentary is all full-line. Without this the
    guard matches the very comment that explains the flag — the header line
    ``# --skip-synthetic 고정: ...`` keeps a `--skip-synthetic` assertion green
    after the argument is gone.
    """
    return "\n".join(line for line in script.splitlines() if not line.lstrip().startswith("#"))


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _backfill_run_script(path: Path) -> str:
    """The `run:` body of the step whose id is ``backfill``, comments stripped."""
    doc = _load(path)
    for job in (doc.get("jobs") or {}).values():
        for step in job.get("steps") or []:
            if step.get("id") == "backfill":
                return _strip_shell_comments(step.get("run", ""))
    raise AssertionError("no step with id 'backfill' — the guard's anchor moved")


def _steps(path: Path) -> list[dict]:
    doc = _load(path)
    for job in (doc.get("jobs") or {}).values():
        steps = job.get("steps")
        if steps:
            return steps
    raise AssertionError("workflow has no steps")


def test_workflow_exists() -> None:
    """Canary: a rename must fail here rather than making everything vacuous."""
    assert _WORKFLOW.is_file(), f"{_WORKFLOW} not found"


def test_skip_synthetic_is_fixed() -> None:
    body = _backfill_run_script(_WORKFLOW)
    assert "--skip-synthetic" in body, (
        "--skip-synthetic was removed from the backfill args. The synthetic "
        "fallback writes output worse than the text it replaces and "
        "improve_existing_posts strips it as a defect. If re-enabling is "
        "intentional, fix korean_keywords quality first and update this guard."
    )


def test_limit_is_present_and_bounded() -> None:
    target = _WORKFLOW
    body = _backfill_run_script(target)
    assert "--limit" in body, (
        "--limit was removed. The resolver budget is per-day: an unbounded "
        "sweep spends it in one pass and the next run yields 0."
    )
    raw = target.read_text(encoding="utf-8")
    defaults = re.findall(r"inputs\.limit\s*\|\|\s*'(\d+)'", raw)
    assert defaults, "could not read the scheduled --limit default; the guard's anchor moved"
    worst = max(int(d) for d in defaults)
    assert worst <= _MAX_DEFAULT_LIMIT, (
        f"scheduled --limit default is {worst}, above the {_MAX_DEFAULT_LIMIT} ceiling. "
        "Raising it spends the daily resolver budget in one run — raise "
        "GNEWS_DECODE_INTERVAL_SEC instead, and update this ceiling only with a "
        "measured yield to justify it."
    )


def test_schedule_is_at_most_daily() -> None:
    doc = _load(_WORKFLOW)
    # `on` parses as the boolean True under YAML 1.1, so accept either key.
    triggers = doc.get("on", doc.get(True)) or {}
    crons = [entry["cron"] for entry in (triggers.get("schedule") or [])]
    assert len(crons) == 1, f"expected exactly one scheduled run per day, found {crons}"
    minute, hour = crons[0].split()[0], crons[0].split()[1]
    assert minute.isdigit() and hour.isdigit(), (
        f"cron {crons[0]!r} does not pin a single minute and hour. A wildcard "
        "there turns the daily resolver budget into an hourly one."
    )


def test_zero_yield_does_not_fail_the_job() -> None:
    target = _WORKFLOW
    steps = _steps(target)
    zero_yield = [s for s in steps if "== '0'" in str(s.get("if", ""))]
    assert zero_yield, (
        "no step is gated on a zero yield. 'the resolver is blocked today' must "
        "stay reportable without turning the job red."
    )
    for step in zero_yield:
        body = _strip_shell_comments(step.get("run", "") or "")
        assert "exit 1" not in body, (
            f"step {step.get('name')!r} fails the job on a zero yield. Daily "
            "throttling would then bury real regressions in alert noise."
        )
    pushes = [s for s in steps if "git push" in _strip_shell_comments(s.get("run", "") or "")]
    assert pushes, "no push step found — the guard's anchor moved"
    for step in pushes:
        assert "!= '0'" in str(step.get("if", "")), (
            f"push step {step.get('name')!r} is not gated on a non-zero yield; an empty run could push."
        )


_ATTEMPT_LOG_PATH = "_state/url_summary_attempts.json"


def test_order_is_least_recently_tried() -> None:
    body = _backfill_run_script(_WORKFLOW)
    assert "--order least-recently-tried" in body, (
        "--order least-recently-tried was removed from the backfill args. The "
        "default `newest` pins permanently unfixable blurbs at the top of the "
        "window: measured 2026-09-09, the newest-200 window covered only "
        "2026-08-06..09-09, leaving 2,403 flagged blurbs unreachable at any "
        "yield. The run still reports success with the stall restored."
    )


def test_attempt_log_is_carried_across_runs() -> None:
    """Restore *and* save, on the same path and key prefix, save unconditional.

    Asserting only that a cache step exists is not enough — a restore without a
    save reads an empty log every run, which degrades to `newest` and silently
    undoes property 6. The path is asserted on both sides because a mismatch
    between them fails the same way while both steps look present.
    """
    steps = _steps(_WORKFLOW)
    restores = [s for s in steps if "actions/cache/restore@" in str(s.get("uses", ""))]
    saves = [s for s in steps if "actions/cache/save@" in str(s.get("uses", ""))]

    def _for_log(candidates: list[dict]) -> list[dict]:
        return [s for s in candidates if (s.get("with") or {}).get("path") == _ATTEMPT_LOG_PATH]

    restores = _for_log(restores)
    saves = _for_log(saves)
    assert restores, f"no actions/cache/restore step for {_ATTEMPT_LOG_PATH}; the window cannot advance across runs"
    assert saves, (
        f"no actions/cache/save step for {_ATTEMPT_LOG_PATH}. A restore without "
        "a save reads an empty log every run, which orders exactly like `newest`."
    )
    for step in saves:
        assert str(step.get("if", "")).strip() == "always()", (
            f"save step {step.get('name')!r} is conditional ({step.get('if')!r}). "
            "The commit step is skipped on a zero-yield day, and that is the day "
            "whose 'all 200 failed' record matters most."
        )
    keys = {str((s.get("with") or {}).get("key", "")) for s in restores + saves}
    prefixes = {k.split("${{")[0] for k in keys}
    assert len(prefixes) == 1, f"restore and save use different cache key prefixes: {prefixes}"


def test_attempt_log_is_not_committed() -> None:
    """The log must not enter git — the push step stages ``_posts/`` only.

    Committing it would reverse a deliberate decision recorded in the push
    step's own comment and put a per-run state file into the retry loop's
    rebase path, on top of `pre-commit-state-guard` blocking `_state/` commits.
    """
    steps = _steps(_WORKFLOW)
    pushes = [s for s in steps if "git push" in _strip_shell_comments(s.get("run", "") or "")]
    assert pushes, "no push step found — the guard's anchor moved"
    for step in pushes:
        body = _strip_shell_comments(step.get("run", "") or "")
        # The whole rest of the line, then split: `git add (\S+)` captures only
        # the first pathspec, so `git add _posts/ _state/x.json` would read as
        # clean. Verified by mutation — that form passed the narrower pattern.
        staged = [arg for line in re.findall(r"git add ([^\n]+)", body) for arg in line.split()]
        assert staged, f"push step {step.get('name')!r} stages nothing explicitly; the guard's anchor moved"
        assert not any("_state" in path for path in staged), (
            f"push step {step.get('name')!r} stages {staged}, which includes _state. "
            "The attempt log is carried by actions/cache on purpose."
        )


def test_scheduled_run_does_not_skip_google_news() -> None:
    body = _backfill_run_script(_WORKFLOW)
    assert "--direct-only" not in body, (
        "--direct-only skips every news.google.com URL, which was 88.6% of the "
        "flagged population on 2026-09-07 (2342 of 2643). It is a manual lever "
        "while throttled, not a scheduled default: the job would report success "
        "while addressing ~11% of its targets."
    )
