#!/usr/bin/env python3

import argparse
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parents[1]
POSTS_DIR = ROOT / "_posts"
WORKFLOWS_DIR = ROOT / ".github" / "workflows"


@dataclass
class PriorityItem:
    stage: str
    priority: str
    title: str
    detail: str


@dataclass
class RolePrompt:
    role: str
    focus: str
    prompts: List[str]


def count_recent_posts(days: int = 2) -> int:
    now = datetime.now(UTC)
    count = 0
    for path in POSTS_DIR.glob("*.md"):
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
        if (now - mtime).days <= days:
            count += 1
    return count


def count_workflows() -> int:
    return len(list(WORKFLOWS_DIR.glob("*.yml")))


def build_priorities(recent_posts: int, workflow_count: int) -> List[PriorityItem]:
    return [
        PriorityItem(
            stage="ULTRAWORKER_SCAN",
            priority="P0",
            title="Ralph post quality sweep",
            detail="Run improve_existing_posts.py on schedule and keep duplicate/insight/SEO cleanup continuously applied.",
        ),
        PriorityItem(
            stage="ULTRAWORKER_SCAN",
            priority="P0",
            title="Ultrawork image backfill",
            detail="Run backfill_images.py on schedule so missing or placeholder post images are regenerated and front matter is updated.",
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
            stage="SISYPHUS_EXECUTE",
            priority="P1",
            title="Performance and optimization guardrails",
            detail="Track runtime/cost regressions across collectors and optimize cache-first workflows and API usage.",
        ),
        PriorityItem(
            stage="SISYPHUS_EXECUTE",
            priority="P1",
            title="Quality triage sweep",
            detail="Review code quality, content quality, UI/UX, and design signals and publish concrete remediation tasks.",
        ),
        PriorityItem(
            stage="LOOP_VERIFY",
            priority="P2",
            title="Weekly loop health review",
            detail=(
                f"Recent posts (48h): {recent_posts}, "
                f"workflow files: {workflow_count}. "
                "Review loop signal quality weekly."
            ),
        ),
    ]


def build_role_prompts(recent_posts: int, workflow_count: int) -> List[RolePrompt]:
    return [
        RolePrompt(
            role="ops",
            focus="CI/CD health, Vercel/Sentry GitHub App integration, GitHub Actions status",
            prompts=[
                "Verify GitHub App integrations (Vercel/Sentry) are installed and connected to this repo.",
                "Confirm deploy-pages and site-health-check are green for the last 24h.",
                "Review workflow retry/escalation behavior for recent failures.",
            ],
        ),
        RolePrompt(
            role="security",
            focus="Dependencies, secrets hygiene, Sentry GitHub App alerts",
            prompts=[
                "Review dependency-check findings and track remediation issues.",
                "Triage Sentry GitHub App alerts/unresolved issues and map them to owners.",
                "Validate GitHub App permissions and webhook activity for integrations.",
            ],
        ),
        RolePrompt(
            role="uiux",
            focus="Content rendering, layout drift, mobile experience",
            prompts=[
                "Review recent posts for long-link rendering and source-tag layout regressions.",
                "Sample category pages on mobile for typography and spacing issues.",
                f"Check content freshness: recent_posts_48h={recent_posts}, workflows={workflow_count}.",
            ],
        ),
        RolePrompt(
            role="monitoring",
            focus="Observability and incident response readiness",
            prompts=[
                "Review recurring workflow failures and escalation paths; confirm owner assignment.",
                "Verify health checks and alert routing for site/data pipeline degradation.",
                "Track 7-day trend for failed jobs and list top 3 repeat causes.",
            ],
        ),
        RolePrompt(
            role="performance",
            focus="Runtime efficiency, caching, and API cost control",
            prompts=[
                "Measure slowest collector/generator jobs and propose top 3 speedups.",
                "Audit cache hit opportunities before external API calls.",
                "Flag quota-heavy sources and define fallback/data-thinning plan.",
            ],
        ),
        RolePrompt(
            role="code-quality",
            focus="Lint/type/test hygiene and maintainability",
            prompts=[
                "Review new lint/type warnings and identify owners with deadlines.",
                "Expand regression coverage for recently changed scripts/workflows.",
                "Prioritize small refactors that reduce duplication in scripts/common.",
            ],
        ),
        RolePrompt(
            role="content-quality",
            focus="Post quality, source credibility, and editorial consistency",
            prompts=[
                "Sample recent posts for source quality, duplication, and factual consistency.",
                "Run title/summary clarity checks and list weak posts to refresh.",
                "Track category imbalance and propose next-day editorial rebalance.",
            ],
        ),
        RolePrompt(
            role="design",
            focus="Visual consistency, readability, and mobile-first presentation",
            prompts=[
                "Review generated images and identify style drift across categories.",
                "Check contrast/readability of key pages on desktop and mobile.",
                "Propose one low-risk design polish task for this cycle.",
            ],
        ),
    ]


def render_report(items: List[PriorityItem], roles: List[RolePrompt]) -> str:
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# Continuous Improvement Loop Report",
        "",
        f"- generated_at: {now}",
        "- model_flow: ultraworker -> sisyphus -> loop_verify",
        "- coordination_targets: opencode, openclaw, slack",
        "- multi_agent_forum: ops, security, monitoring, performance, code-quality, content-quality, uiux, design",
        "",
        "## Priorities",
    ]

    for item in items:
        lines.append(f"- [{item.priority}] {item.stage} | {item.title} - {item.detail}")

    lines.extend(
        [
            "",
            "## Multi-Agent Forum",
        ]
    )

    for role in roles:
        lines.append(f"- role={role.role} focus={role.focus}")
        for prompt in role.prompts:
            lines.append(f"  - {prompt}")

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


def render_slack_message(items: List[PriorityItem], roles: List[RolePrompt]) -> str:
    head = "[ultrawork-loop] OpenCode/OpenClaw continuous improvement cycle"
    body = []
    for item in items[:4]:
        body.append(f"- {item.priority} {item.title}")
    if roles:
        role_list = ", ".join(role.role for role in roles)
        body.append(f"- role_threads: {role_list}")
    body.append("- next_step: execute highest P0 in current run and report evidence")
    return "\n".join([head, *body])


def render_role_slack_messages(
    roles: List[RolePrompt],
    recent_posts: int,
    workflow_count: int,
) -> Dict[str, str]:
    messages: Dict[str, str] = {}
    for role in roles:
        header = f"[multi-agent-forum] {role.role.upper()} forum"
        lines = [
            header,
            f"- focus: {role.focus}",
            f"- signals: recent_posts_48h={recent_posts}, workflows={workflow_count}",
            "- prompts:",
        ]
        lines.extend([f"- {prompt}" for prompt in role.prompts])
        lines.append("- reply_with: findings + concrete next actions")
        messages[role.role] = "\n".join(lines)
    return messages


def write_role_messages(directory: Path, messages: Dict[str, str]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for role, message in messages.items():
        path = directory / f"continuous-improvement-loop-{role}.txt"
        path.write_text(message, encoding="utf-8")


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
    parser.add_argument(
        "--role-slack-dir",
        default="",
        help="Optional directory to emit role-specific Slack messages.",
    )
    args = parser.parse_args()

    recent_posts = count_recent_posts()
    workflow_count = count_workflows()
    items = build_priorities(recent_posts, workflow_count)
    roles = build_role_prompts(recent_posts, workflow_count)
    report = render_report(items, roles)
    slack = render_slack_message(items, roles)

    report_path = Path(args.report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")

    slack_path = Path(args.slack_path)
    slack_path.parent.mkdir(parents=True, exist_ok=True)
    slack_path.write_text(slack, encoding="utf-8")

    if args.role_slack_dir:
        role_dir = Path(args.role_slack_dir)
        role_messages = render_role_slack_messages(roles, recent_posts, workflow_count)
        write_role_messages(role_dir, role_messages)

    print(f"Wrote loop report: {report_path}")
    print(f"Wrote slack summary: {slack_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
