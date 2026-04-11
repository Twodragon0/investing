"""Tests for ops 10am digest summaries."""

from scripts.generate_ops_10am_digest import (
    GitHubSummary,
    OpenClawSummary,
    SentrySummary,
    SlackHealth,
    VercelSummary,
    build_actions,
    collect_sentry_summary,
    format_digest,
)


class TestCollectSentrySummary:
    def test_missing_credentials_returns_unavailable(self):
        summary = collect_sentry_summary("", "", "")
        assert summary.status == "UNAVAILABLE"
        assert summary.unresolved_count == -1

    def test_open_issues_return_open(self, monkeypatch):
        monkeypatch.setattr(
            "scripts.generate_ops_10am_digest.sentry_api",
            lambda path, token: [{"id": "1"}, {"id": "2"}],
        )
        summary = collect_sentry_summary("dragon-org", "investing", "token")
        assert summary.status == "OPEN"
        assert summary.unresolved_count == 2
        assert "sentry.io" in summary.issue_link

    def test_empty_issue_list_returns_clear(self, monkeypatch):
        monkeypatch.setattr("scripts.generate_ops_10am_digest.sentry_api", lambda path, token: [])
        summary = collect_sentry_summary("dragon-org", "investing", "token")
        assert summary.status == "CLEAR"
        assert summary.unresolved_count == 0


class TestBuildActions:
    def test_includes_sentry_action_when_open(self):
        gh = GitHubSummary(failure_count_24h=0, latest_failure_links=[])
        vercel = VercelSummary(
            production_state="READY",
            error_logs_found="NO",
            recent3_failure_rate="0/3",
            recent_deploy_link="",
        )
        sentry = SentrySummary(status="OPEN", unresolved_count=3, issue_link="https://sentry.io/example")
        oc = OpenClawSummary(
            runtime="READY",
            rpc_probe="OK",
            fallback_total=0,
            fallback_degraded_or_missing=0,
            auth_issue_count=0,
            models_line="0/0",
        )
        slack = SlackHealth(status="READY", detail="auth.test ok")

        actions = build_actions(gh, vercel, sentry, oc, slack)
        assert any("Sentry" in action for action in actions)


class TestFormatDigest:
    def test_includes_sentry_line(self):
        gh = GitHubSummary(failure_count_24h=1, latest_failure_links=["https://github.com/example"])
        vercel = VercelSummary(
            production_state="READY",
            error_logs_found="NO",
            recent3_failure_rate="0/3",
            recent_deploy_link="https://vercel.com/example",
        )
        sentry = SentrySummary(status="OPEN", unresolved_count=2, issue_link="https://sentry.io/example")
        oc = OpenClawSummary(
            runtime="READY",
            rpc_probe="OK",
            fallback_total=1,
            fallback_degraded_or_missing=0,
            auth_issue_count=0,
            models_line="Fallbacks (1)",
        )
        slack = SlackHealth(status="READY", detail="auth.test ok")

        digest = format_digest(
            "[ops-10am-digest:2026-04-11]",
            gh,
            vercel,
            sentry,
            oc,
            slack,
            ["@security | 10:40 | Sentry 미해결 이슈 우선 분류"],
            {"gh_failure_count_24h": 0, "fallback_degraded_or_missing": 0},
            ["https://github.com/example", "https://sentry.io/example"],
        )

        assert "Sentry OPEN (unresolved:2)" in digest
