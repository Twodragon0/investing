#!/usr/bin/env python3

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List


ROOT = Path(__file__).resolve().parents[1]
POSTS_DIR = ROOT / "_posts"
WORKFLOWS_DIR = ROOT / ".github" / "workflows"


@dataclass
class PriorityItem:
    stage: str
    priority: str
    title: str
    detail: str


def count_recent_posts(days: int = 2) -> int:
    now = datetime.now(timezone.utc)
    count = 0
    for path in POSTS_DIR.glob("*.md"):
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        if (now - mtime).days <= days:
            count += 1
    return count


def count_workflows() -> int:
    return len(list(WORKFLOWS_DIR.glob("*.yml")))


def build_priorities() -> List[PriorityItem]:
    recent_posts = count_recent_posts()
    workflow_count = count_workflows()

    return [
        PriorityItem(
            stage="ULTRAWORKER_SCAN",
            priority="P0",
            title="Collector reliability baseline",
            detail="Enforce collection-summary fields in all collectors and detect missing fields in CI.",
        ),
        PriorityItem(
            stage="ULTRAWORKER_SCAN",
            priority="P0",
            title="Failure classifier evidence quality",
            detail="Track issue evidence snippet quality and expand pattern coverage for root-cause speed.",
        ),
        PriorityItem(
            stage="SISYPHUS_EXECUTE",
            priority="P1",
            title="Rendered fixture expansion",
            detail="Add edge fixtures for long links, empty refs, and mixed source tags on every content format change.",
        ),
        PriorityItem(
            stage="SISYPHUS_EXECUTE",
            priority="P1",
            title="Workflow observability",
            detail="Keep actionlint annotations + PR report synchronized and monitor drift across workflows.",
        ),
        PriorityItem(
            stage="LOOP_VERIFY",
            priority="P2",
            title="Weekly loop health review",
            detail=f"Recent posts (48h): {recent_posts}, workflow files: {workflow_count}. Review loop signal quality weekly.",
        ),
    ]


def render_report(items: List[PriorityItem]) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# Continuous Improvement Loop Report",
        "",
        f"- generated_at: {now}",
        "- model_flow: ultraworker -> sisyphus -> loop_verify",
        "- coordination_targets: opencode, openclaw, slack",
        "",
        "## Priorities",
    ]

    for item in items:
        lines.append(f"- [{item.priority}] {item.stage} | {item.title} - {item.detail}")

    lines.extend(
        [
            "",
            "## Execution Rules",
            "- Keep each loop bounded to a single run; never use infinite runtime loops.",
            "- Publish next actionable P0/P1 items to Slack at each scheduled run.",
            "- Verify with py_compile + fixture smoke + rendered smoke before merge.",
        ]
    )
    return "\n".join(lines) + "\n"


def render_slack_message(items: List[PriorityItem]) -> str:
    head = "[ultrawork-loop] OpenCode/OpenClaw continuous improvement cycle"
    body = []
    for item in items[:4]:
        body.append(f"- {item.priority} {item.title}")
    body.append("- next_step: execute highest P0 in current run and report evidence")
    return "\n".join([head, *body])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--report-path",
        default=str(ROOT / "_state" / "continuous-improvement-loop.md"),
    )
    parser.add_argument(
        "--slack-path",
        default=str(ROOT / "_state" / "continuous-improvement-loop-slack.txt"),
    )
    args = parser.parse_args()

    items = build_priorities()
    report = render_report(items)
    slack = render_slack_message(items)

    report_path = Path(args.report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")

    slack_path = Path(args.slack_path)
    slack_path.parent.mkdir(parents=True, exist_ok=True)
    slack_path.write_text(slack, encoding="utf-8")

    print(f"Wrote loop report: {report_path}")
    print(f"Wrote slack summary: {slack_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
