"""
tests/test_external_watchdog.py — pytest wrapper for external_watchdog.sh

Approach: subprocess invocation of the bash script with:
- Required env vars supplied programmatically
- curl replaced by a stub script on PATH (no real network calls)
- jq must be available on the test host (standard on macOS/Ubuntu)

Run:
    python3 -m pytest tests/test_external_watchdog.py --no-cov -v
"""

import json
import os
import stat
import subprocess
import tempfile
import textwrap
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
WATCHDOG_SCRIPT = REPO_ROOT / "scripts" / "ops" / "external_watchdog.sh"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_stub_curl(tmp_dir: Path, response_body: str, http_status: str = "200") -> Path:
    """Create a fake `curl` executable that returns canned JSON."""
    stub = tmp_dir / "curl"
    # The real script calls curl with -o /dev/null -w "%{http_code}" for the
    # Slack POST, and with -sf for the API GET. We detect by looking at args.
    stub.write_text(textwrap.dedent(f"""\
        #!/usr/bin/env bash
        # Stub curl — returns canned response
        for arg in "$@"; do
            if [ "$arg" = "-w" ]; then
                # Slack webhook call — print HTTP status to stdout
                echo "{http_status}"
                exit 0
            fi
        done
        # API call — print body
        printf '%s' '{response_body}'
    """))
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return tmp_dir


def _make_api_response(runs: list[dict]) -> str:
    """Build a minimal GitHub API workflow runs payload."""
    return json.dumps({"workflow_runs": runs})


def _recent_run(conclusion: str, minutes_ago: int = 2) -> dict:
    ts = time.strftime(
        "%Y-%m-%dT%H:%M:%SZ",
        time.gmtime(time.time() - minutes_ago * 60),
    )
    return {"conclusion": conclusion, "created_at": ts}


def _run_watchdog(env: dict, tmp_dir: Path) -> subprocess.CompletedProcess:
    """Run the watchdog script with the given env, using the stub PATH."""
    full_env = {
        **os.environ,
        "PATH": f"{tmp_dir}:{os.environ.get('PATH', '/usr/bin:/bin')}",
        "DEDUP_FILE": str(tmp_dir / "last_alert.txt"),
        **env,
    }
    return subprocess.run(
        ["bash", str(WATCHDOG_SCRIPT)],
        capture_output=True,
        text=True,
        env=full_env,
    )


# ---------------------------------------------------------------------------
# Test 1: Missing required env var → exit 1
# ---------------------------------------------------------------------------

def test_missing_github_token_exits_nonzero():
    """Script must exit 1 and print an error when GITHUB_TOKEN is absent."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        _make_stub_curl(tmp_dir, "{}")

        result = _run_watchdog(
            {
                "GITHUB_TOKEN": "",
                "GITHUB_REPO": "owner/repo",
                "SLACK_WEBHOOK_URL": "https://hooks.slack.com/services/T/B/X",
            },
            tmp_dir,
        )
    assert result.returncode == 1
    assert "GITHUB_TOKEN" in result.stdout or "GITHUB_TOKEN" in result.stderr


def test_missing_slack_webhook_exits_nonzero():
    """Script must exit 1 when SLACK_WEBHOOK_URL is absent."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        _make_stub_curl(tmp_dir, "{}")

        result = _run_watchdog(
            {
                "GITHUB_TOKEN": "ghp_fake",
                "GITHUB_REPO": "owner/repo",
                "SLACK_WEBHOOK_URL": "",
            },
            tmp_dir,
        )
    assert result.returncode == 1
    assert "SLACK_WEBHOOK_URL" in result.stdout or "SLACK_WEBHOOK_URL" in result.stderr


# ---------------------------------------------------------------------------
# Test 2: Healthy watchdog → exit 0, no alert
# ---------------------------------------------------------------------------

def test_healthy_watchdog_exits_zero_no_alert():
    """When last success is recent, script exits 0 and does NOT post to Slack."""
    runs = [_recent_run("success", minutes_ago=2)] + [
        _recent_run("success", minutes_ago=4),
        _recent_run("success", minutes_ago=6),
    ]
    api_body = _make_api_response(runs)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        _make_stub_curl(tmp_dir, api_body)

        result = _run_watchdog(
            {
                "GITHUB_TOKEN": "ghp_fake",
                "GITHUB_REPO": "owner/repo",
                "SLACK_WEBHOOK_URL": "https://hooks.slack.com/services/T/B/X",
                "ALERT_THRESHOLD_MINUTES": "15",
            },
            tmp_dir,
        )

    assert result.returncode == 0
    assert "OK" in result.stdout
    # Dedup file should NOT have been written (no alert fired)
    assert not (tmp_dir / "last_alert.txt").exists()


# ---------------------------------------------------------------------------
# Test 3: Last success too old → alert fires
# ---------------------------------------------------------------------------

def test_last_success_too_old_triggers_alert():
    """Alert fires when last success is older than ALERT_THRESHOLD_MINUTES."""
    runs = [_recent_run("success", minutes_ago=60)] + [
        _recent_run("startup_failure", minutes_ago=5),
        _recent_run("startup_failure", minutes_ago=10),
    ]
    api_body = _make_api_response(runs)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        _make_stub_curl(tmp_dir, api_body, http_status="200")

        result = _run_watchdog(
            {
                "GITHUB_TOKEN": "ghp_fake",
                "GITHUB_REPO": "owner/repo",
                "SLACK_WEBHOOK_URL": "https://hooks.slack.com/services/T/B/X",
                "ALERT_THRESHOLD_MINUTES": "15",
            },
            tmp_dir,
        )

        assert result.returncode == 0
        assert "ALERT" in result.stdout
        # Dedup file must be written after alert
        assert (tmp_dir / "last_alert.txt").exists()


# ---------------------------------------------------------------------------
# Test 4: 3 consecutive startup_failure → alert fires
# ---------------------------------------------------------------------------

def test_three_consecutive_startup_failures_triggers_alert():
    """Alert fires when the last 3 runs are all startup_failure."""
    runs = [_recent_run("startup_failure", minutes_ago=i * 5 + 1) for i in range(5)]
    api_body = _make_api_response(runs)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        _make_stub_curl(tmp_dir, api_body, http_status="200")

        result = _run_watchdog(
            {
                "GITHUB_TOKEN": "ghp_fake",
                "GITHUB_REPO": "owner/repo",
                "SLACK_WEBHOOK_URL": "https://hooks.slack.com/services/T/B/X",
                "ALERT_THRESHOLD_MINUTES": "15",
            },
            tmp_dir,
        )

    assert result.returncode == 0
    assert "ALERT" in result.stdout


# ---------------------------------------------------------------------------
# Test 5: Dedup suppresses second alert within cooldown
# ---------------------------------------------------------------------------

def test_dedup_suppresses_repeat_alert():
    """A second alert within the cooldown window is skipped (dedup)."""
    runs = [_recent_run("startup_failure", minutes_ago=i * 5 + 1) for i in range(5)]
    api_body = _make_api_response(runs)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        _make_stub_curl(tmp_dir, api_body, http_status="200")

        base_env = {
            "GITHUB_TOKEN": "ghp_fake",
            "GITHUB_REPO": "owner/repo",
            "SLACK_WEBHOOK_URL": "https://hooks.slack.com/services/T/B/X",
            "ALERT_THRESHOLD_MINUTES": "15",
            "DEDUP_COOLDOWN_SECONDS": "3600",
        }

        # First run — should alert
        result1 = _run_watchdog(base_env, tmp_dir)
        assert result1.returncode == 0
        assert "ALERT" in result1.stdout

        # Second run immediately after — dedup should suppress
        result2 = _run_watchdog(base_env, tmp_dir)
        assert result2.returncode == 0
        assert "DEDUP" in result2.stdout


# ---------------------------------------------------------------------------
# Test 6: Dedup file expired → alert fires again
# ---------------------------------------------------------------------------

def test_dedup_expired_allows_new_alert():
    """Alert fires again once the dedup cooldown has expired."""
    runs = [_recent_run("startup_failure", minutes_ago=i * 5 + 1) for i in range(5)]
    api_body = _make_api_response(runs)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        _make_stub_curl(tmp_dir, api_body, http_status="200")

        # Write an expired dedup timestamp (2 hours ago)
        dedup_file = tmp_dir / "last_alert.txt"
        dedup_file.write_text(str(int(time.time()) - 7200))

        result = _run_watchdog(
            {
                "GITHUB_TOKEN": "ghp_fake",
                "GITHUB_REPO": "owner/repo",
                "SLACK_WEBHOOK_URL": "https://hooks.slack.com/services/T/B/X",
                "ALERT_THRESHOLD_MINUTES": "15",
                "DEDUP_COOLDOWN_SECONDS": "3600",
            },
            tmp_dir,
        )

    assert result.returncode == 0
    assert "ALERT" in result.stdout
