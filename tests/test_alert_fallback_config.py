"""
Tests for alert-consecutive-failures fallback configuration.

Verifies that:
1. alert-consecutive-failures.yml has issues: write permission
2. The fallback step referencing steps.post-slack.outcome == 'failure' exists
3. All 13 caller workflows have issues: write in their top-level permissions
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

WORKFLOWS_DIR = Path(__file__).parent.parent / ".github" / "workflows"
ALERT_WORKFLOW = WORKFLOWS_DIR / "alert-consecutive-failures.yml"

CALLER_WORKFLOWS = [
    "collect-blockchain.yml",
    "collect-coinmarketcap.yml",
    "collect-crypto-news.yml",
    "collect-defi-llama.yml",
    "collect-defi-yields.yml",
    "collect-fmp-calendar.yml",
    "collect-geopolitical.yml",
    "collect-market-indicators.yml",
    "collect-political-trades.yml",
    "collect-regulatory.yml",
    "collect-social-media.yml",
    "collect-stock-news.yml",
    "collect-worldmonitor-news.yml",
]


def _load(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def test_alert_workflow_has_issues_write_permission():
    doc = _load(ALERT_WORKFLOW)
    perms = doc.get("permissions", {})
    assert isinstance(perms, dict), "permissions block must be a mapping"
    assert perms.get("issues") == "write", f"alert-consecutive-failures.yml must have 'issues: write', got: {perms}"


def test_alert_workflow_has_fallback_step_on_slack_failure():
    """A step must exist whose `if:` condition references steps.post-slack.outcome == 'failure'."""
    doc = _load(ALERT_WORKFLOW)
    jobs = doc.get("jobs", {})
    found = False
    for job in jobs.values():
        if not isinstance(job, dict):
            continue
        for step in job.get("steps", []):
            if not isinstance(step, dict):
                continue
            condition = str(step.get("if", ""))
            if "steps.post-slack.outcome == 'failure'" in condition:
                found = True
                break
        if found:
            break
    assert found, (
        "No step found with if: condition referencing "
        "steps.post-slack.outcome == 'failure' in alert-consecutive-failures.yml"
    )


def test_alert_workflow_post_slack_step_has_id():
    """The Slack posting step must have id: post-slack so its outcome can be referenced."""
    doc = _load(ALERT_WORKFLOW)
    jobs = doc.get("jobs", {})
    found = False
    for job in jobs.values():
        if not isinstance(job, dict):
            continue
        for step in job.get("steps", []):
            if not isinstance(step, dict):
                continue
            if step.get("id") == "post-slack":
                found = True
                break
        if found:
            break
    assert found, "No step with id: post-slack found in alert-consecutive-failures.yml"


@pytest.mark.parametrize("workflow_file", CALLER_WORKFLOWS)
def test_caller_workflow_has_issues_write(workflow_file: str):
    path = WORKFLOWS_DIR / workflow_file
    assert path.exists(), f"Caller workflow not found: {path}"
    doc = _load(path)
    perms = doc.get("permissions", {})
    assert isinstance(perms, dict), f"{workflow_file}: permissions block must be a mapping"
    assert perms.get("issues") == "write", (
        f"{workflow_file} must have 'issues: write' in top-level permissions, got: {perms}"
    )
