"""Alerting quality review: watchdog-zero-job-runs + collector-heartbeat.

Usage:
    python3 scripts/tools/review_alerting_quality.py [--window-hours 24] \
        [--repo owner/name] [--output report.md]

NOTE: "Slack alert sent" is approximated by checking whether the
'Post alert to Slack' step ran (not skipped) in each watchdog run.
Actual delivery cannot be verified without a Slack API token.
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

_ROOT = Path(__file__).parent.parent.parent
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from common.config import setup_logging  # noqa: E402

setup_logging()
logger = logging.getLogger(__name__)

WATCHDOG_WORKFLOW = "watchdog-zero-job-runs.yml"
HEARTBEAT_WORKFLOW = "collector-heartbeat.yml"
HEARTBEAT_EXPECTED_HOUR, HEARTBEAT_EXPECTED_MINUTE, HEARTBEAT_TOLERANCE_MIN = 0, 10, 5
COLLECT_WORKFLOWS = [
    "collect-blockchain.yml", "collect-coinmarketcap.yml", "collect-crypto-news.yml",
    "collect-defi-llama.yml", "collect-defi-yields.yml", "collect-fmp-calendar.yml",
    "collect-geopolitical.yml", "collect-market-indicators.yml",
    "collect-political-trades.yml", "collect-regulatory.yml",
    "collect-social-media.yml", "collect-stock-news.yml", "collect-worldmonitor-news.yml",
]


@dataclass
class RunRecord:
    run_id: int; workflow: str; conclusion: str | None; created_at: datetime; html_url: str  # noqa: E702


@dataclass
class WatchdogAlert:
    run_id: int; created_at: datetime; alert_sent: bool; html_url: str  # noqa: E702


@dataclass
class HeartbeatRecord:
    run_id: int; created_at: datetime; conclusion: str | None; html_url: str  # noqa: E702
    @property
    def delay_minutes(self) -> float:
        exp = self.created_at.replace(hour=HEARTBEAT_EXPECTED_HOUR,
            minute=HEARTBEAT_EXPECTED_MINUTE, second=0, microsecond=0)
        return abs((self.created_at - exp).total_seconds()) / 60.0
    @property
    def is_on_time(self) -> bool:
        return self.delay_minutes <= HEARTBEAT_TOLERANCE_MIN


@dataclass
class CollectorStats:
    workflow: str; total: int = 0; successes: int = 0; failures: int = 0; startup_failures: int = 0  # noqa: E702


@dataclass
class ReviewResult:
    window_hours: int; window_start: datetime; window_end: datetime  # noqa: E702
    watchdog_runs: list[WatchdogAlert] = field(default_factory=list)
    startup_failure_runs: list[RunRecord] = field(default_factory=list)
    heartbeat_records: list[HeartbeatRecord] = field(default_factory=list)
    collector_stats: list[CollectorStats] = field(default_factory=list)


def _gh(args: list[str]) -> list[dict]:
    try:
        r = subprocess.run(["gh"] + args, capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            logger.warning("gh failed (rc=%d): %s", r.returncode, r.stderr[:200])
            return []
        data = json.loads(r.stdout.strip() or "[]")
        return data if isinstance(data, list) else [data]
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError) as e:
        logger.warning("gh error: %s", e)
        return []

def _dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None

def fetch_runs(workflow: str, repo: str, limit: int = 50) -> list[dict]:
    return _gh(["run", "list", "--workflow", workflow, "--repo", repo,
                "--limit", str(limit), "--json", "databaseId,conclusion,createdAt,url"])

def fetch_steps(run_id: int, repo: str) -> list[dict]:
    jobs = _gh(["api", f"/repos/{repo}/actions/runs/{run_id}/jobs"])
    return [s for j in jobs for s in j.get("steps", [])]

def _filter(runs: list[dict], since: datetime) -> list[dict]:
    return [r for r in runs if (t := _dt(r.get("createdAt"))) is not None and t >= since]


def analyse_watchdog(raw: list[dict], since: datetime, repo: str) -> list[WatchdogAlert]:
    out: list[WatchdogAlert] = []
    for r in _filter(raw, since):
        run_id, created, url = r.get("databaseId", 0), _dt(r.get("createdAt")), r.get("url", "")
        if created is None:
            continue
        alert_sent = False
        for step in fetch_steps(run_id, repo):
            if "post alert" in step.get("name", "").lower():
                outcome = step.get("conclusion") or step.get("status", "")
                alert_sent = outcome not in ("skipped", "not_run", None, "")
                break
        out.append(WatchdogAlert(run_id=run_id, created_at=created, alert_sent=alert_sent, html_url=url))
    return out


def analyse_collectors(repo: str, since: datetime) -> tuple[list[RunRecord], list[CollectorStats]]:
    failures: list[RunRecord] = []
    stats_list: list[CollectorStats] = []
    for wf in COLLECT_WORKFLOWS:
        s = CollectorStats(workflow=wf)
        for r in _filter(fetch_runs(wf, repo, 50), since):
            s.total += 1
            c = r.get("conclusion") or ""
            if c == "success":
                s.successes += 1
            elif c == "startup_failure":
                s.startup_failures += 1
                s.failures += 1
                if (t := _dt(r.get("createdAt"))):
                    failures.append(RunRecord(r.get("databaseId", 0), wf, c, t, r.get("url", "")))
            elif c in ("failure", "cancelled", "timed_out"):
                s.failures += 1
        stats_list.append(s)
    return failures, stats_list

def analyse_heartbeat(raw: list[dict], since: datetime) -> list[HeartbeatRecord]:
    out: list[HeartbeatRecord] = []
    for r in _filter(raw, since):
        if (t := _dt(r.get("createdAt"))):
            out.append(HeartbeatRecord(r.get("databaseId", 0), t, r.get("conclusion"), r.get("url", "")))
    return out

def compute_watchdog_precision(
    alerts: list[WatchdogAlert], startup_failures: list[RunRecord]
) -> tuple[float | None, int, int]:
    """(precision, tp, n_sent). Window-level approximation: any failure → all sent alerts are TP."""
    sent = sum(1 for a in alerts if a.alert_sent)
    if sent == 0:
        return None, 0, 0
    tp = sent if startup_failures else 0
    return tp / sent, tp, sent

def compute_watchdog_recall(
    alerts: list[WatchdogAlert], startup_failures: list[RunRecord]
) -> tuple[float | None, int, int]:
    """(recall, detected, total_failures). Approximation: min(sent, failures) detected."""
    n = len(startup_failures)
    if n == 0:
        return None, 0, 0
    detected = min(sum(1 for a in alerts if a.alert_sent), n)
    return detected / n, detected, n

def generate_report(result: ReviewResult) -> str:
    now = datetime.now(UTC)
    L: list[str] = [
        "# Alerting Quality Review Report", "",
        f"**Generated**: {now.strftime('%Y-%m-%d %H:%M UTC')}",
        f"**Window**: {result.window_start.strftime('%Y-%m-%d %H:%M UTC')} → "
        f"{result.window_end.strftime('%Y-%m-%d %H:%M UTC')} ({result.window_hours}h)", "",
        "> **Note on 'Slack alert sent' approximation**: This script cannot query the Slack API.",
        "> Delivery is *approximated* by whether the 'Post alert to Slack' step was not skipped.",
        "> Actual delivery may differ if the step ran but the Slack API call failed.", "",
    ]
    total = len(result.watchdog_runs) + len(result.heartbeat_records) + sum(s.total for s in result.collector_stats)
    if total == 0:
        L += ["## Result", "", "**No data available** — no runs found in the analysis window.",
              "Re-run after 24h of operation for meaningful metrics.", ""]
        return "\n".join(L)

    # Watchdog section
    n_wd = len(result.watchdog_runs)
    n_sent = sum(1 for a in result.watchdog_runs if a.alert_sent)
    prec, tp, ps = compute_watchdog_precision(result.watchdog_runs, result.startup_failure_runs)
    rec, det, nf = compute_watchdog_recall(result.watchdog_runs, result.startup_failure_runs)
    prec_s = f"{prec:.0%}" if prec is not None else "N/A (no alerts sent)"
    rec_s = f"{rec:.0%}" if rec is not None else "N/A (no startup_failures found)"
    L += [
        "## 1. Watchdog (`watchdog-zero-job-runs.yml`)", "",
        f"- Watchdog executions in window: **{n_wd}**",
        f"- Alerts sent (approx): **{n_sent}** / {n_wd}",
        f"- `startup_failure` runs in collect-*.yml: **{len(result.startup_failure_runs)}**", "",
        "| Metric | Value | Notes |", "|--------|-------|-------|",
        f"| Precision (approx) | {prec_s} | TP={tp}, alerts_sent={ps} |",
        f"| Recall (approx) | {rec_s} | detected={det}, total_failures={nf} |", "",
    ]
    if result.startup_failure_runs:
        L += ["**startup_failure runs detected:**", ""]
        for r in result.startup_failure_runs:
            L.append(f"- `{r.workflow}` run {r.run_id} at {r.created_at.strftime('%Y-%m-%d %H:%M UTC')} — {r.html_url}")
        L.append("")
    if result.watchdog_runs:
        L += ["**Watchdog run details:**", ""]
        for a in result.watchdog_runs:
            label = "ALERT SENT (approx)" if a.alert_sent else "no alert"
            L.append(f"- Run {a.run_id} at {a.created_at.strftime('%Y-%m-%d %H:%M UTC')}: {label} — {a.html_url}")
        L.append("")

    # Heartbeat section
    L += ["## 2. Heartbeat (`collector-heartbeat.yml`)", ""]
    if not result.heartbeat_records:
        L += ["No heartbeat runs in window (expected daily at 00:10 UTC).", ""]
    else:
        on_time = sum(1 for h in result.heartbeat_records if h.is_on_time)
        L += [f"- Runs: **{len(result.heartbeat_records)}**, on-time (±{HEARTBEAT_TOLERANCE_MIN} min): **{on_time}**", "",
              "| Run ID | Time (UTC) | Delay (min) | On-time | Conclusion |",
              "|--------|------------|-------------|---------|------------|"]
        for h in result.heartbeat_records:
            L.append(f"| {h.run_id} | {h.created_at.strftime('%H:%M')} | "
                     f"{h.delay_minutes:.1f} | {'✓' if h.is_on_time else '✗'} | {h.conclusion or 'unknown'} |")
        L.append("")

    # Collector stats section
    L += ["## 3. Collector Health (ground truth from `gh run list`)", ""]
    active = [s for s in result.collector_stats if s.total > 0]
    if not active:
        L += ["No collect-*.yml runs in window.", ""]
    else:
        L += ["| Workflow | Runs | OK | Fail | startup_failure |",
              "|----------|------|-----|------|-----------------|"]
        for s in active:
            L.append(f"| `{s.workflow.removesuffix('.yml')}` | {s.total} | {s.successes} | "
                     f"{s.failures} | {s.startup_failures} |")
        L.append("")

    L += ["---", "", "*Report generated by `scripts/tools/review_alerting_quality.py`.*", ""]
    return "\n".join(L)

def run_review(window_hours: int, repo: str) -> ReviewResult:
    now, since = datetime.now(UTC), datetime.now(UTC) - timedelta(hours=window_hours)
    result = ReviewResult(window_hours=window_hours, window_start=since, window_end=now)
    logger.info("Fetching watchdog runs...")
    result.watchdog_runs = analyse_watchdog(fetch_runs(WATCHDOG_WORKFLOW, repo, 100), since, repo)
    logger.info("Fetching collector runs...")
    result.startup_failure_runs, result.collector_stats = analyse_collectors(repo, since)
    logger.info("Fetching heartbeat runs...")
    result.heartbeat_records = analyse_heartbeat(fetch_runs(HEARTBEAT_WORKFLOW, repo, 20), since)
    return result

def detect_repo() -> str:
    try:
        out = subprocess.run(["git", "remote", "get-url", "origin"],
                             capture_output=True, text=True, timeout=10)
        url = out.stdout.strip().replace("git@github.com:", "https://github.com/").removesuffix(".git")
        if "github.com" in url:
            parts = url.rstrip("/").split("/")
            return f"{parts[-2]}/{parts[-1]}"
    except Exception as exc:  # noqa: BLE001
        logger.debug("detect_repo failed: %s", exc)
    return ""

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Measure alerting signal quality over a time window.")
    p.add_argument("--window-hours", type=int, default=24, help="Hours of history to analyse (default: 24)")
    p.add_argument("--repo", default="", help="GitHub repo slug owner/name (auto-detect if omitted)")
    p.add_argument("--output", default="", help="Write markdown report to this file (optional)")
    return p.parse_args(argv)

def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo = args.repo or detect_repo()
    if not repo:
        logger.error("Could not detect repo. Pass --repo owner/name.")
        return 2
    logger.info("repo=%s window=%dh", repo, args.window_hours)
    result = run_review(args.window_hours, repo)
    report = generate_report(result)
    print(report)
    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report, encoding="utf-8")
        logger.info("Report written to %s", out)
    return 0

if __name__ == "__main__":
    sys.exit(main())
