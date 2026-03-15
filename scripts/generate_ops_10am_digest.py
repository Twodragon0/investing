#!/usr/bin/env python3

import argparse
import json
import os
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Tuple

from common.config import get_kst_timezone

GITHUB_API_BASE = "https://api.github.com"
SLACK_API_BASE = "https://slack.com/api"


@dataclass
class GitHubSummary:
    failure_count_24h: int
    latest_failure_links: List[str]


@dataclass
class VercelSummary:
    production_state: str
    error_logs_found: str
    recent3_failure_rate: str
    recent_deploy_link: str


@dataclass
class OpenClawSummary:
    runtime: str
    rpc_probe: str
    fallback_total: int
    fallback_degraded_or_missing: int
    auth_issue_count: int
    models_line: str


@dataclass
class SlackHealth:
    status: str
    detail: str


def run_cmd(command: List[str]) -> Tuple[bool, str]:
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
        )
        output = (completed.stdout + "\n" + completed.stderr).strip()
        return completed.returncode == 0, output
    except OSError as exc:
        return False, str(exc)


def github_api(repo: str, token: str) -> Dict[str, Any]:
    url = f"{GITHUB_API_BASE}/repos/{repo}/actions/runs?per_page=100"
    req = urllib.request.Request(url)
    req.add_header("Accept", "application/vnd.github+json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=20) as response:  # nosec B310 - HTTPS-only hardcoded URL
        return json.loads(response.read().decode("utf-8"))


def collect_github_summary(repo: str, token: str) -> GitHubSummary:
    try:
        payload = github_api(repo, token)
    except (urllib.error.URLError, json.JSONDecodeError):
        return GitHubSummary(failure_count_24h=-1, latest_failure_links=[])

    now_kst = datetime.now(get_kst_timezone())
    cutoff = now_kst - timedelta(hours=24)
    failures: List[Dict[str, Any]] = []

    for run in payload.get("workflow_runs", []):
        created_at_raw = run.get("created_at")
        conclusion = (run.get("conclusion") or "").lower()
        if not created_at_raw or conclusion != "failure":
            continue
        try:
            created_at = datetime.fromisoformat(created_at_raw.replace("Z", "+00:00"))
        except ValueError:
            continue
        if created_at >= cutoff:
            failures.append(run)

    failures.sort(key=lambda item: item.get("created_at", ""), reverse=True)
    links = [run.get("html_url", "") for run in failures[:2] if run.get("html_url")]
    return GitHubSummary(failure_count_24h=len(failures), latest_failure_links=links)


def parse_vercel_deployments(raw: str) -> List[Dict[str, Any]]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []

    if isinstance(parsed, dict) and isinstance(parsed.get("deployments"), list):
        return parsed["deployments"]
    if isinstance(parsed, list):
        return parsed
    return []


def collect_vercel_summary() -> VercelSummary:
    has_vercel, _ = run_cmd(["vercel", "--version"])
    if not has_vercel:
        return VercelSummary(
            production_state="UNAVAILABLE",
            error_logs_found="UNAVAILABLE",
            recent3_failure_rate="UNAVAILABLE",
            recent_deploy_link="",
        )

    token = os.getenv("VERCEL_TOKEN", "")
    list_cmd = ["vercel", "list", "--yes", "--format", "json"]
    if token:
        list_cmd.extend(["--token", token])
    ok, out = run_cmd(list_cmd)
    if not ok:
        return VercelSummary(
            production_state="UNKNOWN",
            error_logs_found="UNKNOWN",
            recent3_failure_rate="UNKNOWN",
            recent_deploy_link="",
        )

    deployments = parse_vercel_deployments(out)
    if not deployments:
        return VercelSummary(
            production_state="UNKNOWN",
            error_logs_found="UNKNOWN",
            recent3_failure_rate="UNKNOWN",
            recent_deploy_link="",
        )

    def state_of(item: Dict[str, Any]) -> str:
        return str(item.get("state") or item.get("readyState") or "").upper()

    prod_candidates = [d for d in deployments if str(d.get("target") or "").lower() == "production"]
    primary = prod_candidates[0] if prod_candidates else deployments[0]
    primary_state = state_of(primary) or "UNKNOWN"

    recent3 = deployments[:3]
    failed_recent3 = sum(1 for dep in recent3 if state_of(dep) in {"ERROR", "FAILED"})
    failure_rate = f"{failed_recent3}/3"

    deploy_ref = str(primary.get("url") or primary.get("uid") or "")
    if deploy_ref and not deploy_ref.startswith("http"):
        deploy_ref = f"https://{deploy_ref}"

    logs_cmd = ["vercel", "logs", "--limit", "50"]
    if deploy_ref:
        logs_cmd.extend(["--deployment", deploy_ref])
    if token:
        logs_cmd.extend(["--token", token])
    logs_ok, logs_out = run_cmd(logs_cmd)

    if not logs_ok:
        logs_state = "UNKNOWN"
    else:
        logs_state = "YES" if re.search(r"error|exception|failed|fatal", logs_out, re.IGNORECASE) else "NO"

    return VercelSummary(
        production_state=primary_state,
        error_logs_found=logs_state,
        recent3_failure_rate=failure_rate,
        recent_deploy_link=deploy_ref,
    )


def collect_openclaw_summary() -> OpenClawSummary:
    gateway_ok, gateway_out = run_cmd(["openclaw", "gateway", "status"])
    models_ok, models_out = run_cmd(["openclaw", "models", "status"])

    runtime = "UNAVAILABLE"
    rpc_probe = "UNAVAILABLE"
    fallback_total = 0
    degraded_or_missing = 0
    auth_issues = 0
    models_line = "UNAVAILABLE"

    if gateway_ok:
        runtime_match = re.search(r"Runtime:\s*([^\n]+)", gateway_out)
        rpc_match = re.search(r"RPC probe:\s*([^\n]+)", gateway_out)
        if runtime_match:
            runtime = runtime_match.group(1).strip()
        if rpc_match:
            rpc_probe = rpc_match.group(1).strip()

    if models_ok:
        fallback_match = re.search(r"Fallbacks\s*\((\d+)\)", models_out)
        if fallback_match:
            fallback_total = int(fallback_match.group(1))

        for raw_line in models_out.splitlines():
            line = raw_line.strip().lower()
            if line.startswith("fallbacks"):
                models_line = raw_line.strip()
            if any(keyword in line for keyword in ["expired", "missing", "failed", "error", "unusable"]):
                degraded_or_missing += 1
                auth_issues += 1
            elif "expires in 0m" in line:
                degraded_or_missing += 1

    return OpenClawSummary(
        runtime=runtime,
        rpc_probe=rpc_probe,
        fallback_total=fallback_total,
        fallback_degraded_or_missing=degraded_or_missing,
        auth_issue_count=auth_issues,
        models_line=models_line,
    )


def slack_api(method: str, token: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    data = urllib.parse.urlencode(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{SLACK_API_BASE}/{method}",
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as response:  # nosec B310 - HTTPS-only hardcoded URL
        return json.loads(response.read().decode("utf-8"))


def collect_slack_health(token: str, channel: str) -> SlackHealth:
    if not token or not channel:
        return SlackHealth(status="UNRESOLVED", detail="token/channel missing")
    try:
        auth = slack_api("auth.test", token, {})
    except urllib.error.URLError:
        return SlackHealth(status="UNRESOLVED", detail="auth.test request failed")
    if not auth.get("ok"):
        return SlackHealth(status="UNRESOLVED", detail=f"auth.test={auth.get('error', 'unknown')}")
    return SlackHealth(status="READY", detail="auth.test ok")


def should_post_today(token: str, channel: str, marker: str) -> bool:
    if not token or not channel:
        return True
    cursor = ""
    for _ in range(5):
        payload: Dict[str, Any] = {"channel": channel, "limit": "200"}
        if cursor:
            payload["cursor"] = cursor
        try:
            history = slack_api("conversations.history", token, payload)
        except urllib.error.URLError:
            return True
        if not history.get("ok"):
            return True
        for message in history.get("messages", []):
            if marker in str(message.get("text", "")):
                return False
        cursor = str(history.get("response_metadata", {}).get("next_cursor", "")).strip()
        if not cursor:
            break
    return True


def read_state(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def write_state(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def build_actions(gh: GitHubSummary, vercel: VercelSummary, oc: OpenClawSummary, slack: SlackHealth) -> List[str]:
    actions: List[str] = []
    if gh.failure_count_24h > 0:
        actions.append("@ops | 10:30 | GitHub 실패 워크플로우 원인 확인")
    if vercel.recent3_failure_rate != "UNAVAILABLE" and vercel.recent3_failure_rate != "0/3":
        actions.append("@ops | 10:30 | Vercel 최근 배포/로그 점검")
    if oc.fallback_degraded_or_missing > 0 or oc.auth_issue_count > 0:
        actions.append("@ai | 11:00 | OpenClaw fallback provider auth 재검증")
    if slack.status != "READY":
        actions.append("@ops | 10:20 | Slack 토큰/채널 해석 상태 점검")
    if not actions:
        actions.append("@ops | 10:30 | 현재 즉시 조치 필요 항목 없음")
    return actions


def format_digest(
    marker: str,
    gh: GitHubSummary,
    vercel: VercelSummary,
    oc: OpenClawSummary,
    slack: SlackHealth,
    actions: List[str],
    prev_state: Dict[str, Any],
    links: List[str],
) -> str:
    gh_count = "N/A" if gh.failure_count_24h < 0 else str(gh.failure_count_24h)
    p0_line = (
        f"P0: GH 실패 {gh_count}건 | Vercel {vercel.production_state}"
        f" (errors:{vercel.error_logs_found}) | OpenClaw Runtime {oc.runtime}, RPC {oc.rpc_probe}"
        f" | Slack {slack.status}"
    )

    fallback_state = (
        f"{oc.fallback_degraded_or_missing}/{oc.fallback_total} degraded_or_missing" if oc.fallback_total > 0 else "0/0"
    )
    p1_line = f"P1: 모델 라우팅 내구성 {fallback_state} | 최근 배포 실패율 {vercel.recent3_failure_rate}"

    prev_gh = prev_state.get("gh_failure_count_24h")
    prev_deg = prev_state.get("fallback_degraded_or_missing")
    gh_delta = "N/A" if prev_gh is None or gh.failure_count_24h < 0 else f"{gh.failure_count_24h - int(prev_gh):+d}"
    deg_delta = "N/A" if prev_deg is None else f"{oc.fallback_degraded_or_missing - int(prev_deg):+d}"
    p2_line = f"P2: 전일 대비 GH 실패 {gh_delta}, 모델 가용성 이슈 {deg_delta}"

    action_line = " / ".join(actions[:2])
    if len(actions) > 2:
        action_line += " / ..."

    unique_links = [link for link in links if link][:3]
    links_line = " | ".join(unique_links) if unique_links else "N/A"

    lines = [
        "10:00 Ops Digest (KST)",
        p0_line,
        p1_line,
        p2_line,
        f"Action: {action_line}",
        f"Links: {links_line}",
        marker,
    ]
    return "\n".join(lines)


def write_github_outputs(payload: Dict[str, str]) -> None:
    output_path = os.getenv("GITHUB_OUTPUT", "")
    if not output_path:
        return
    with open(output_path, "a", encoding="utf-8") as file:
        for key, value in payload.items():
            if "\n" in value:
                file.write(f"{key}<<EOF\n{value}\nEOF\n")
            else:
                file.write(f"{key}={value}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate 10AM ops Slack digest")
    parser.add_argument("--repo", default=os.getenv("GITHUB_REPOSITORY", "Twodragon0/investing"))
    parser.add_argument("--github-token", default=os.getenv("GITHUB_TOKEN", ""))
    parser.add_argument("--slack-channel", default=os.getenv("SLACK_CHANNEL_ID", ""))
    parser.add_argument("--state-file", default="_state/ops-10am-digest-state.json")
    args = parser.parse_args()

    slack_token = os.getenv("SLACK_BOT_TOKEN", "")

    now = datetime.now(get_kst_timezone())
    marker = f"[ops-10am-digest:{now.strftime('%Y-%m-%d')}]"

    gh = collect_github_summary(args.repo, args.github_token)
    vercel = collect_vercel_summary()
    oc = collect_openclaw_summary()
    slack = collect_slack_health(slack_token, args.slack_channel)

    state_path = Path(args.state_file)
    prev_state = read_state(state_path)

    links: List[str] = []
    links.extend(gh.latest_failure_links)
    if vercel.recent_deploy_link:
        links.append(vercel.recent_deploy_link)
    links.append("https://docs.openclaw.ai/cli/models")

    actions = build_actions(gh, vercel, oc, slack)
    message = format_digest(marker, gh, vercel, oc, slack, actions, prev_state, links)
    post_ok = should_post_today(slack_token, args.slack_channel, marker)

    current_state = {
        "timestamp": now.isoformat(),
        "gh_failure_count_24h": gh.failure_count_24h,
        "fallback_degraded_or_missing": oc.fallback_degraded_or_missing,
    }
    write_state(state_path, current_state)

    write_github_outputs(
        {
            "message": message,
            "should_post": "true" if post_ok else "false",
            "marker": marker,
            "slack_health": slack.status,
        }
    )

    print(message)
    print(f"should_post={str(post_ok).lower()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
