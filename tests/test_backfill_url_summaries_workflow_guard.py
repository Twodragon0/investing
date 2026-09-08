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


def test_scheduled_run_does_not_skip_google_news() -> None:
    body = _backfill_run_script(_WORKFLOW)
    assert "--direct-only" not in body, (
        "--direct-only skips every news.google.com URL, which was 88.6% of the "
        "flagged population on 2026-09-07 (2342 of 2643). It is a manual lever "
        "while throttled, not a scheduled default: the job would report success "
        "while addressing ~11% of its targets."
    )
