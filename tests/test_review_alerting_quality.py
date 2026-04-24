"""Tests for scripts/tools/review_alerting_quality.py."""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

_ROOT = Path(__file__).parent.parent
_TOOLS = _ROOT / "scripts" / "tools"
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))
if str(_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(_ROOT / "scripts"))

import review_alerting_quality as raq  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 4, 23, 10, 0, 0, tzinfo=UTC)
_WINDOW_START = _NOW - timedelta(hours=2)


def _make_run(
    run_id: int,
    workflow: str,
    conclusion: str,
    offset_minutes: int = 30,
    url: str = "https://github.com/example/runs/1",
) -> dict:
    """Build a minimal gh run list JSON entry."""
    created = _NOW - timedelta(minutes=offset_minutes)
    return {
        "databaseId": run_id,
        "conclusion": conclusion,
        "createdAt": created.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "url": url,
        "name": workflow,
    }


# ---------------------------------------------------------------------------
# Test 1: precision / recall with synthetic startup_failure data
# ---------------------------------------------------------------------------


def test_precision_recall_with_startup_failure():
    """One alert sent + one startup_failure → precision=1.0, recall=1.0."""
    alerts = [
        raq.WatchdogAlert(
            run_id=1,
            created_at=_NOW - timedelta(minutes=30),
            alert_sent=True,
            html_url="https://github.com/example/runs/1",
        )
    ]
    startup_failures = [
        raq.RunRecord(
            run_id=99,
            workflow="collect-crypto-news.yml",
            conclusion="startup_failure",
            created_at=_NOW - timedelta(minutes=25),
            html_url="https://github.com/example/runs/99",
        )
    ]

    precision, tp, n_sent = raq.compute_watchdog_precision(alerts, startup_failures)
    recall, detected, n_total = raq.compute_watchdog_recall(alerts, startup_failures)

    assert precision == 1.0
    assert tp == 1
    assert n_sent == 1
    assert recall == 1.0
    assert detected == 1
    assert n_total == 1


def test_precision_zero_when_alert_sent_but_no_failures():
    """Alert sent with no startup_failures → precision=0 (false positive)."""
    alerts = [
        raq.WatchdogAlert(
            run_id=2,
            created_at=_NOW - timedelta(minutes=10),
            alert_sent=True,
            html_url="https://github.com/example/runs/2",
        )
    ]
    startup_failures: list[raq.RunRecord] = []

    precision, tp, n_sent = raq.compute_watchdog_precision(alerts, startup_failures)

    assert precision == 0.0
    assert tp == 0
    assert n_sent == 1


def test_recall_none_when_no_startup_failures():
    """No startup_failures in window → recall is None (undefined)."""
    alerts = [
        raq.WatchdogAlert(
            run_id=3,
            created_at=_NOW - timedelta(minutes=5),
            alert_sent=False,
            html_url="",
        )
    ]
    _, _, n_total = raq.compute_watchdog_recall(alerts, [])
    recall, _, _ = raq.compute_watchdog_recall(alerts, [])

    assert recall is None
    assert n_total == 0


# ---------------------------------------------------------------------------
# Test 2: filter_by_window
# ---------------------------------------------------------------------------


def test_filter_by_window_excludes_old_runs():
    """Runs older than window_start must be excluded."""
    runs = [
        _make_run(1, "collect-crypto-news.yml", "success", offset_minutes=30),  # inside 2h
        _make_run(2, "collect-crypto-news.yml", "success", offset_minutes=180),  # outside 2h
    ]
    inside = raq._filter(runs, _WINDOW_START)
    assert len(inside) == 1
    assert inside[0]["databaseId"] == 1


# ---------------------------------------------------------------------------
# Test 3: generate_report shows "No data" message on empty ReviewResult
# ---------------------------------------------------------------------------


def test_generate_report_no_data_message():
    """Empty ReviewResult → report contains no-data message."""
    result = raq.ReviewResult(
        window_hours=2,
        window_start=_WINDOW_START,
        window_end=_NOW,
        watchdog_runs=[],
        startup_failure_runs=[],
        heartbeat_records=[],
        collector_stats=[],
    )
    report = raq.generate_report(result)
    assert "No data available" in report
    assert "Re-run after 24h" in report


# ---------------------------------------------------------------------------
# Test 4: heartbeat timeliness
# ---------------------------------------------------------------------------


def test_heartbeat_on_time():
    """Run at exactly 00:10 UTC must be classified as on-time."""
    ts = datetime(2026, 4, 23, 0, 10, 0, tzinfo=UTC)
    rec = raq.HeartbeatRecord(run_id=5, created_at=ts, conclusion="success", html_url="")
    assert rec.is_on_time is True
    assert rec.delay_minutes == 0.0


def test_heartbeat_late():
    """Run at 00:20 UTC (10 min late) must NOT be on-time (tolerance=5 min)."""
    ts = datetime(2026, 4, 23, 0, 20, 0, tzinfo=UTC)
    rec = raq.HeartbeatRecord(run_id=6, created_at=ts, conclusion="success", html_url="")
    assert rec.is_on_time is False
    assert rec.delay_minutes == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# Test 5: generate_report includes collector stats when data present
# ---------------------------------------------------------------------------


def test_generate_report_includes_collector_table():
    """ReviewResult with collector data → report contains collector table."""
    stats = raq.CollectorStats(
        workflow="collect-crypto-news.yml",
        total=3,
        successes=2,
        failures=1,
        startup_failures=0,
    )
    result = raq.ReviewResult(
        window_hours=2,
        window_start=_WINDOW_START,
        window_end=_NOW,
        watchdog_runs=[],
        startup_failure_runs=[],
        heartbeat_records=[],
        collector_stats=[stats],
    )
    report = raq.generate_report(result)
    assert "collect-crypto-news" in report
    # Should not show no-data message since collector has runs
    assert "No data available" not in report
