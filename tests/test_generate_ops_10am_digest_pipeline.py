"""`scripts/generate_ops_10am_digest.py` 의 수집·조립·상태·`main()` 경로 테스트.

기존 `tests/test_generate_ops_10am_digest.py` 는 Sentry 요약과 조립 함수 일부(32%)만
덮는다. 이 파일은 나머지를 덮는다 — 서브프로세스 래퍼, GitHub/Slack/Sentry HTTP 경계,
Vercel/OpenClaw 출력 파싱, Slack 중복 게시 방지, 상태 파일 입출력, GitHub Actions
출력 기록, 그리고 `main()` 배선.

## 이 모듈이 조용히 틀릴 수 있는 지점

이 다이제스트는 매일 10시 크론이 만들어 Slack 에 던진다. 아래가 깨져도 워크플로우는
성공으로 끝나고, 사람이 보는 건 "이상 없음"처럼 생긴 문자열이다:

- **fail-soft 값** — 네트워크가 죽으면 `-1`/`UNAVAILABLE` 을 낸다. 이 값이 실제
  "실패 0건"과 같은 문자열로 렌더링되면 장애가 정상으로 위장된다 (`N/A` 분기)
- **24시간 창** — `created_at` 파싱이나 cutoff 가 밀리면 어제 실패가 오늘로 새거나
  오늘 실패가 통째로 사라진다
- **CLI 출력 정규식** — `vercel` / `openclaw` 의 출력 포맷이 바뀌면 조용히 0건이 되고
  P1 라인이 영원히 `0/0` 으로 굳는다
- **중복 게시 방지** — `should_post_today` 가 항상 True 를 내면 매 실행마다 중복 게시,
  항상 False 를 내면 다이제스트가 영원히 안 올라간다. 둘 다 알람이 없다
- **delta 계산** — 이전 상태를 못 읽으면 `N/A` 여야 하는데 `0` 으로 렌더링되면
  "전일 대비 변화 없음"이라는 거짓 신호가 된다

## 격리

이 모듈은 `subprocess.run` 으로 외부 CLI 를, `urllib.request.urlopen` 으로 외부 API 를
때리고, `--state-file` 로 지정된 경로에 **파일을 쓴다.** 세 경계를 모두 모듈 자신의
네임스페이스에서 대역으로 바꾸고, 상태 경로는 항상 `tmp_path` 로 주입한다
(기본값은 레포 루트의 `_state/` 라 워킹 트리를 더럽힌다). 시각은 고정하지 않고
**현재 기준 상대 시각으로 입력을 생성**해 결정성을 얻는다.
"""

from __future__ import annotations

import importlib
import json
import sys
import urllib.error
from datetime import UTC, datetime, timedelta
from typing import Any, Dict, List

import pytest

od = importlib.import_module("generate_ops_10am_digest")


class _FakeResponse:
    """`urlopen` 이 반환하는 컨텍스트 매니저 대역."""

    def __init__(self, payload: Any) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *_exc: object) -> bool:
        return False

    def read(self) -> bytes:
        return self._body


def _patch_urlopen(monkeypatch, payload: Any) -> List[Any]:
    """`urlopen` 을 대역으로 바꾸고 전달된 Request 를 수집한다."""
    seen: List[Any] = []

    def _fake(req, timeout=None):
        seen.append(req)
        return _FakeResponse(payload)

    monkeypatch.setattr(od.urllib.request, "urlopen", _fake)
    return seen


def _iso_hours_ago(hours: float) -> str:
    """현재 기준 상대 시각을 GitHub 스타일 `Z` ISO 문자열로 만든다."""
    return (datetime.now(UTC) - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _run(html_url: str = "https://gh/1", *, hours_ago: float = 1.0, conclusion: str = "failure") -> Dict[str, Any]:
    return {"created_at": _iso_hours_ago(hours_ago), "conclusion": conclusion, "html_url": html_url}


# ---------------------------------------------------------------------------
# run_cmd
# ---------------------------------------------------------------------------


class _Completed:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class TestRunCmd:
    def test_success_merges_stdout_and_stderr(self, monkeypatch) -> None:
        calls: List[Any] = []

        def _fake(command, **kwargs):
            calls.append((command, kwargs))
            return _Completed(0, stdout="out", stderr="err")

        monkeypatch.setattr(od.subprocess, "run", _fake)
        ok, output = od.run_cmd(["vercel", "--version"])

        assert calls, "subprocess 경계가 호출되지 않았다"
        assert calls[0][0] == ["vercel", "--version"]
        assert calls[0][1]["check"] is False, "check=True 면 실패 CLI 가 예외로 크론을 죽인다"
        assert calls[0][1]["capture_output"] is True
        assert ok is True
        assert output == "out\nerr"

    def test_nonzero_returncode_is_not_ok_but_keeps_output(self, monkeypatch) -> None:
        monkeypatch.setattr(od.subprocess, "run", lambda command, **kw: _Completed(2, stderr="boom"))
        ok, output = od.run_cmd(["openclaw", "gateway", "status"])
        assert ok is False
        assert "boom" in output

    def test_missing_binary_is_reported_as_failure(self, monkeypatch) -> None:
        """CLI 가 없는 머신에서 예외 대신 (False, 메시지) 로 fail-soft 해야 한다."""

        def _boom(command, **kwargs):
            raise OSError("No such file or directory: 'vercel'")

        monkeypatch.setattr(od.subprocess, "run", _boom)
        ok, output = od.run_cmd(["vercel"])
        assert ok is False
        assert "vercel" in output

    def test_output_is_stripped(self, monkeypatch) -> None:
        monkeypatch.setattr(od.subprocess, "run", lambda command, **kw: _Completed(0, stdout="  x  \n"))
        assert od.run_cmd(["x"])[1] == "x"


# ---------------------------------------------------------------------------
# github_api / sentry_api / slack_api  (HTTP 경계)
# ---------------------------------------------------------------------------


class TestGithubApi:
    def test_requests_runs_endpoint_with_bearer_token(self, monkeypatch) -> None:
        seen = _patch_urlopen(monkeypatch, {"workflow_runs": []})
        result = od.github_api("owner/repo", "tok")

        assert seen, "urlopen 이 호출되지 않았다 — 배선이 끊겼다"
        (req,) = seen
        assert req.full_url == f"{od.GITHUB_API_BASE}/repos/owner/repo/actions/runs?per_page=100"
        assert req.get_header("Accept") == "application/vnd.github+json"
        assert req.get_header("Authorization") == "Bearer tok"
        assert result == {"workflow_runs": []}

    def test_token_header_is_omitted_when_absent(self, monkeypatch) -> None:
        """빈 토큰으로 `Bearer ` 를 보내면 GitHub 이 401 로 끊는다."""
        seen = _patch_urlopen(monkeypatch, {})
        od.github_api("owner/repo", "")
        assert seen[0].get_header("Authorization") is None


class TestSentryApi:
    def test_path_is_appended_to_base_with_auth(self, monkeypatch) -> None:
        seen = _patch_urlopen(monkeypatch, [{"id": "1"}])
        result = od.sentry_api("/projects/o/p/issues/", "sentry-tok")

        assert seen, "urlopen 이 호출되지 않았다"
        (req,) = seen
        assert req.full_url == f"{od.SENTRY_API_BASE}/projects/o/p/issues/"
        assert req.get_header("Authorization") == "Bearer sentry-tok"
        assert result == [{"id": "1"}]


class TestCollectSentrySummaryFailSoft:
    """자격증명이 있는데 조회가 실패한 경로 — `UNAVAILABLE` 과 구분되어야 한다."""

    def test_network_error_is_unknown_with_a_usable_link(self, monkeypatch) -> None:
        def _boom(path, token):
            raise urllib.error.URLError("dns")

        monkeypatch.setattr(od, "sentry_api", _boom)
        summary = od.collect_sentry_summary("org", "proj", "tok")
        assert summary.status == "UNKNOWN", "토큰이 있는데 UNAVAILABLE 로 보고하면 원인을 오도한다"
        assert summary.unresolved_count == -1
        assert "org" in summary.issue_link, "조회가 실패해도 사람이 눌러볼 링크는 남아야 한다"

    def test_malformed_json_is_unknown(self, monkeypatch) -> None:
        def _boom(path, token):
            raise json.JSONDecodeError("bad", "[", 0)

        monkeypatch.setattr(od, "sentry_api", _boom)
        assert od.collect_sentry_summary("org", "proj", "tok").status == "UNKNOWN"

    def test_error_object_response_is_unknown_not_counted(self, monkeypatch) -> None:
        """Sentry 가 목록 대신 `{"detail": ...}` 를 주면 len() 이 아니라 UNKNOWN 이다."""
        monkeypatch.setattr(od, "sentry_api", lambda path, token: {"detail": "permission denied"})
        summary = od.collect_sentry_summary("org", "proj", "tok")
        assert summary.status == "UNKNOWN"
        assert summary.unresolved_count == -1

    def test_org_and_project_are_url_quoted_in_the_request_path(self, monkeypatch) -> None:
        seen: List[str] = []

        def _fake(path, token):
            seen.append(path)
            return []

        monkeypatch.setattr(od, "sentry_api", _fake)
        summary = od.collect_sentry_summary("my org", "my proj", "tok")
        assert seen and seen[0].startswith("/projects/my%20org/my%20proj/issues/")
        assert "my%20org" in summary.issue_link


class TestSlackApi:
    def test_posts_form_encoded_payload(self, monkeypatch) -> None:
        seen = _patch_urlopen(monkeypatch, {"ok": True})
        result = od.slack_api("conversations.history", "xoxb-tok", {"channel": "C1", "limit": "200"})

        assert seen, "urlopen 이 호출되지 않았다"
        (req,) = seen
        assert req.full_url == f"{od.SLACK_API_BASE}/conversations.history"
        assert req.get_method() == "POST"
        assert req.get_header("Authorization") == "Bearer xoxb-tok"
        assert req.get_header("Content-type") == "application/x-www-form-urlencoded"
        assert b"channel=C1" in req.data
        assert b"limit=200" in req.data
        assert result == {"ok": True}


# ---------------------------------------------------------------------------
# collect_github_summary
# ---------------------------------------------------------------------------


class TestCollectGithubSummary:
    def _patch_api(self, monkeypatch, payload: Any) -> List[Any]:
        seen: List[Any] = []

        def _fake(repo, token):
            seen.append((repo, token))
            return payload

        monkeypatch.setattr(od, "github_api", _fake)
        return seen

    def test_arguments_reach_the_api_boundary(self, monkeypatch) -> None:
        seen = self._patch_api(monkeypatch, {"workflow_runs": []})
        od.collect_github_summary("owner/repo", "tok")
        assert seen == [("owner/repo", "tok")]

    def test_network_error_yields_sentinel_not_zero(self, monkeypatch) -> None:
        """`-1` 이어야 한다 — `0` 이면 '실패 없음'과 구분되지 않는다."""

        def _boom(repo, token):
            raise urllib.error.URLError("dns")

        monkeypatch.setattr(od, "github_api", _boom)
        summary = od.collect_github_summary("owner/repo", "tok")
        assert summary.failure_count_24h == -1
        assert summary.latest_failure_links == []

    def test_malformed_json_yields_sentinel(self, monkeypatch) -> None:
        def _boom(repo, token):
            raise json.JSONDecodeError("bad", "{", 0)

        monkeypatch.setattr(od, "github_api", _boom)
        assert od.collect_github_summary("owner/repo", "tok").failure_count_24h == -1

    def test_only_failed_runs_are_counted(self, monkeypatch) -> None:
        self._patch_api(
            monkeypatch,
            {
                "workflow_runs": [
                    _run("https://gh/ok", conclusion="success"),
                    _run("https://gh/cancel", conclusion="cancelled"),
                    _run("https://gh/bad", conclusion="failure"),
                ]
            },
        )
        summary = od.collect_github_summary("owner/repo", "tok")
        assert summary.failure_count_24h == 1
        assert summary.latest_failure_links == ["https://gh/bad"]

    def test_conclusion_matching_is_case_insensitive(self, monkeypatch) -> None:
        self._patch_api(monkeypatch, {"workflow_runs": [_run(conclusion="FAILURE")]})
        assert od.collect_github_summary("owner/repo", "tok").failure_count_24h == 1

    def test_runs_older_than_24h_are_excluded(self, monkeypatch) -> None:
        """창 경계 — 23시간 전은 포함, 25시간 전은 제외."""
        self._patch_api(
            monkeypatch,
            {"workflow_runs": [_run("https://gh/in", hours_ago=23), _run("https://gh/out", hours_ago=25)]},
        )
        summary = od.collect_github_summary("owner/repo", "tok")
        assert summary.failure_count_24h == 1
        assert summary.latest_failure_links == ["https://gh/in"]

    def test_runs_without_created_at_are_skipped(self, monkeypatch) -> None:
        self._patch_api(monkeypatch, {"workflow_runs": [{"conclusion": "failure", "html_url": "https://gh/x"}]})
        assert od.collect_github_summary("owner/repo", "tok").failure_count_24h == 0

    def test_unparseable_timestamp_is_skipped_not_raised(self, monkeypatch) -> None:
        self._patch_api(
            monkeypatch,
            {"workflow_runs": [{"created_at": "어제", "conclusion": "failure", "html_url": "https://gh/x"}]},
        )
        assert od.collect_github_summary("owner/repo", "tok").failure_count_24h == 0

    def test_links_are_newest_first_and_capped_at_two(self, monkeypatch) -> None:
        self._patch_api(
            monkeypatch,
            {
                "workflow_runs": [
                    _run("https://gh/old", hours_ago=10),
                    _run("https://gh/new", hours_ago=1),
                    _run("https://gh/mid", hours_ago=5),
                ]
            },
        )
        summary = od.collect_github_summary("owner/repo", "tok")
        assert summary.failure_count_24h == 3
        assert summary.latest_failure_links == ["https://gh/new", "https://gh/mid"]

    def test_missing_html_url_is_dropped_from_links_but_still_counted(self, monkeypatch) -> None:
        self._patch_api(
            monkeypatch,
            {"workflow_runs": [{"created_at": _iso_hours_ago(1), "conclusion": "failure"}, _run("https://gh/ok")]},
        )
        summary = od.collect_github_summary("owner/repo", "tok")
        assert summary.failure_count_24h == 2
        assert summary.latest_failure_links == ["https://gh/ok"]

    def test_empty_payload_yields_zero_not_sentinel(self, monkeypatch) -> None:
        self._patch_api(monkeypatch, {})
        assert od.collect_github_summary("owner/repo", "tok").failure_count_24h == 0


# ---------------------------------------------------------------------------
# parse_vercel_deployments
# ---------------------------------------------------------------------------


class TestParseVercelDeployments:
    def test_wrapped_object_form(self) -> None:
        assert od.parse_vercel_deployments('{"deployments": [{"uid": "a"}]}') == [{"uid": "a"}]

    def test_bare_list_form(self) -> None:
        assert od.parse_vercel_deployments('[{"uid": "a"}]') == [{"uid": "a"}]

    def test_invalid_json_yields_empty_list(self) -> None:
        """`vercel` 이 사람용 텍스트를 뱉어도 예외 없이 빈 목록이어야 한다."""
        assert od.parse_vercel_deployments("Vercel CLI 32.0\nNo deployments") == []

    def test_unexpected_shape_yields_empty_list(self) -> None:
        assert od.parse_vercel_deployments('{"deployments": "nope"}') == []
        assert od.parse_vercel_deployments('"just-a-string"') == []


# ---------------------------------------------------------------------------
# collect_vercel_summary
# ---------------------------------------------------------------------------


class _CmdStub:
    """`run_cmd` 대역 — 커맨드의 첫 두 토큰으로 응답을 고른다."""

    def __init__(self, responses: Dict[str, Any]) -> None:
        self._responses = responses
        self.commands: List[List[str]] = []

    def __call__(self, command: List[str]):
        self.commands.append(list(command))
        for key, value in self._responses.items():
            if command[: len(key.split())] == key.split():
                return value
        return (False, "")

    def find(self, prefix: str) -> List[str]:
        """`prefix` 로 시작하는 첫 커맨드를 돌려준다 (없으면 빈 목록)."""
        tokens = prefix.split()
        for command in self.commands:
            if command[: len(tokens)] == tokens:
                return command
        return []


@pytest.fixture
def vercel_cmd(monkeypatch):
    def _install(responses: Dict[str, Any]) -> _CmdStub:
        stub = _CmdStub(responses)
        monkeypatch.setattr(od, "run_cmd", stub)
        return stub

    return _install


_DEPLOY_JSON = json.dumps(
    [
        {"target": "preview", "state": "ERROR", "url": "preview.example.app"},
        {"target": "production", "readyState": "ready", "url": "prod.example.app"},
        {"target": "preview", "state": "READY", "uid": "dpl_3"},
    ]
)


class TestCollectVercelSummary:
    def test_missing_cli_short_circuits_to_unavailable(self, vercel_cmd) -> None:
        """CLI 자체가 없으면 배포 목록을 부르지 않고 UNAVAILABLE 이어야 한다."""
        stub = vercel_cmd({"vercel --version": (False, "not found")})
        summary = od.collect_vercel_summary()
        assert summary.production_state == "UNAVAILABLE"
        assert summary.error_logs_found == "UNAVAILABLE"
        assert summary.recent3_failure_rate == "UNAVAILABLE"
        assert summary.recent_deploy_link == ""
        assert stub.find("vercel list") == [], "CLI 가 없는데 list 를 시도했다"

    def test_list_failure_yields_unknown(self, vercel_cmd) -> None:
        """UNAVAILABLE(CLI 없음)과 UNKNOWN(호출 실패)은 구분되어야 한다."""
        vercel_cmd({"vercel --version": (True, "32.0"), "vercel list": (False, "auth error")})
        assert od.collect_vercel_summary().production_state == "UNKNOWN"

    def test_empty_deployment_list_yields_unknown(self, vercel_cmd) -> None:
        vercel_cmd({"vercel --version": (True, "32.0"), "vercel list": (True, "[]")})
        summary = od.collect_vercel_summary()
        assert summary.production_state == "UNKNOWN"
        assert summary.recent_deploy_link == ""

    def test_production_deployment_wins_over_first_entry(self, vercel_cmd) -> None:
        """목록 첫 항목은 preview/ERROR 다 — production 을 골라야 한다."""
        vercel_cmd(
            {
                "vercel --version": (True, "32.0"),
                "vercel list": (True, _DEPLOY_JSON),
                "vercel logs": (True, "all good"),
            }
        )
        summary = od.collect_vercel_summary()
        assert summary.production_state == "READY", "readyState 를 대문자로 정규화하지 못했다"
        assert summary.recent_deploy_link == "https://prod.example.app"

    def test_falls_back_to_first_deployment_without_production_target(self, vercel_cmd) -> None:
        payload = json.dumps([{"state": "BUILDING", "uid": "dpl_1"}])
        vercel_cmd({"vercel --version": (True, "32.0"), "vercel list": (True, payload), "vercel logs": (True, "ok")})
        summary = od.collect_vercel_summary()
        assert summary.production_state == "BUILDING"
        assert summary.recent_deploy_link == "https://dpl_1", "url 이 없으면 uid 로 폴백해야 한다"

    def test_state_missing_entirely_is_unknown(self, vercel_cmd) -> None:
        vercel_cmd(
            {
                "vercel --version": (True, "32.0"),
                "vercel list": (True, json.dumps([{"uid": "dpl_1"}])),
                "vercel logs": (True, "ok"),
            }
        )
        assert od.collect_vercel_summary().production_state == "UNKNOWN"

    def test_recent3_failure_rate_counts_error_and_failed(self, vercel_cmd) -> None:
        payload = json.dumps(
            [
                {"state": "ERROR", "uid": "a"},
                {"state": "FAILED", "uid": "b"},
                {"state": "READY", "uid": "c"},
                {"state": "ERROR", "uid": "d"},
            ]
        )
        vercel_cmd({"vercel --version": (True, "32.0"), "vercel list": (True, payload), "vercel logs": (True, "ok")})
        rate = od.collect_vercel_summary().recent3_failure_rate
        assert rate == "2/3", "최근 3건만 봐야 하는데 4번째 ERROR 까지 셌다"

    def test_absolute_url_is_not_double_prefixed(self, vercel_cmd) -> None:
        payload = json.dumps([{"state": "READY", "url": "https://already.example.app"}])
        vercel_cmd({"vercel --version": (True, "32.0"), "vercel list": (True, payload), "vercel logs": (True, "ok")})
        assert od.collect_vercel_summary().recent_deploy_link == "https://already.example.app"

    def test_token_is_forwarded_to_list_and_logs(self, vercel_cmd, monkeypatch) -> None:
        monkeypatch.setenv("VERCEL_TOKEN", "vtok")
        stub = vercel_cmd(
            {"vercel --version": (True, "32.0"), "vercel list": (True, _DEPLOY_JSON), "vercel logs": (True, "ok")}
        )
        od.collect_vercel_summary()
        assert stub.find("vercel list")[-2:] == ["--token", "vtok"]
        logs_cmd = stub.find("vercel logs")
        assert "--deployment" in logs_cmd
        assert logs_cmd[logs_cmd.index("--deployment") + 1] == "https://prod.example.app"
        assert logs_cmd[-2:] == ["--token", "vtok"]

    def test_no_token_means_no_token_flag(self, vercel_cmd, monkeypatch) -> None:
        monkeypatch.delenv("VERCEL_TOKEN", raising=False)
        stub = vercel_cmd(
            {"vercel --version": (True, "32.0"), "vercel list": (True, _DEPLOY_JSON), "vercel logs": (True, "ok")}
        )
        od.collect_vercel_summary()
        assert "--token" not in stub.find("vercel list")

    def test_deployment_flag_is_omitted_without_a_reference(self, vercel_cmd) -> None:
        payload = json.dumps([{"state": "READY"}])
        vercel_cmd({"vercel --version": (True, "32.0"), "vercel list": (True, payload), "vercel logs": (True, "ok")})
        summary = od.collect_vercel_summary()
        assert summary.recent_deploy_link == ""

    @pytest.mark.parametrize("noise", ["Error: build failed", "Unhandled EXCEPTION", "fatal: oom", "task FAILED"])
    def test_error_keywords_in_logs_flip_the_flag(self, vercel_cmd, noise: str) -> None:
        vercel_cmd(
            {
                "vercel --version": (True, "32.0"),
                "vercel list": (True, _DEPLOY_JSON),
                "vercel logs": (True, f"GET /  200\n{noise}\n"),
            }
        )
        assert od.collect_vercel_summary().error_logs_found == "YES"

    def test_clean_logs_report_no(self, vercel_cmd) -> None:
        vercel_cmd(
            {
                "vercel --version": (True, "32.0"),
                "vercel list": (True, _DEPLOY_JSON),
                "vercel logs": (True, "GET / 200\nGET /about 200\n"),
            }
        )
        assert od.collect_vercel_summary().error_logs_found == "NO"

    def test_log_command_failure_is_unknown_not_no(self, vercel_cmd) -> None:
        """로그를 못 읽은 것과 '에러 없음'을 같은 값으로 쓰면 장애를 놓친다."""
        vercel_cmd(
            {
                "vercel --version": (True, "32.0"),
                "vercel list": (True, _DEPLOY_JSON),
                "vercel logs": (False, "permission denied"),
            }
        )
        summary = od.collect_vercel_summary()
        assert summary.error_logs_found == "UNKNOWN"
        assert summary.production_state == "READY", "로그 실패가 배포 상태까지 망가뜨리면 안 된다"


# ---------------------------------------------------------------------------
# collect_openclaw_summary
# ---------------------------------------------------------------------------


class TestCollectOpenClawSummary:
    def _install(self, monkeypatch, gateway, models) -> _CmdStub:
        stub = _CmdStub({"openclaw gateway": gateway, "openclaw models": models})
        monkeypatch.setattr(od, "run_cmd", stub)
        return stub

    def test_both_commands_failing_yield_unavailable(self, monkeypatch) -> None:
        self._install(monkeypatch, (False, ""), (False, ""))
        oc = od.collect_openclaw_summary()
        assert oc.runtime == "UNAVAILABLE"
        assert oc.rpc_probe == "UNAVAILABLE"
        assert oc.models_line == "UNAVAILABLE"
        assert oc.fallback_total == 0
        assert oc.fallback_degraded_or_missing == 0
        assert oc.auth_issue_count == 0

    def test_gateway_fields_are_parsed(self, monkeypatch) -> None:
        gateway_out = "OpenClaw Gateway\nRuntime: bun 1.1.30\nRPC probe: ok (12ms)\n"
        self._install(monkeypatch, (True, gateway_out), (False, ""))
        oc = od.collect_openclaw_summary()
        assert oc.runtime == "bun 1.1.30"
        assert oc.rpc_probe == "ok (12ms)"

    def test_gateway_ok_but_unparseable_keeps_unavailable(self, monkeypatch) -> None:
        """출력 포맷이 바뀌면 이전 값이 아니라 UNAVAILABLE 로 남아야 한다."""
        self._install(monkeypatch, (True, "runtime is fine"), (False, ""))
        oc = od.collect_openclaw_summary()
        assert oc.runtime == "UNAVAILABLE"
        assert oc.rpc_probe == "UNAVAILABLE"

    def test_fallback_total_and_models_line_are_captured(self, monkeypatch) -> None:
        models_out = "Providers (2)\nFallbacks (4)\n  anthropic ok\n  openai ok\n"
        self._install(monkeypatch, (False, ""), (True, models_out))
        oc = od.collect_openclaw_summary()
        assert oc.fallback_total == 4
        assert oc.models_line == "Fallbacks (4)"
        assert oc.fallback_degraded_or_missing == 0

    def test_degraded_keywords_raise_both_counters(self, monkeypatch) -> None:
        models_out = "Fallbacks (3)\n  anthropic ok\n  openai token expired\n  groq key missing\n"
        self._install(monkeypatch, (False, ""), (True, models_out))
        oc = od.collect_openclaw_summary()
        assert oc.fallback_degraded_or_missing == 2
        assert oc.auth_issue_count == 2

    def test_imminent_expiry_counts_as_degraded_but_not_auth_issue(self, monkeypatch) -> None:
        """만료 임박은 아직 인증 실패가 아니다 — 두 카운터가 갈라져야 한다."""
        models_out = "Fallbacks (2)\n  anthropic ok\n  openai expires in 0m\n"
        self._install(monkeypatch, (False, ""), (True, models_out))
        oc = od.collect_openclaw_summary()
        assert oc.fallback_degraded_or_missing == 1
        assert oc.auth_issue_count == 0

    def test_keyword_matching_is_case_insensitive(self, monkeypatch) -> None:
        self._install(monkeypatch, (False, ""), (True, "Fallbacks (1)\n  openai AUTH FAILED\n"))
        assert od.collect_openclaw_summary().auth_issue_count == 1

    def test_missing_fallback_header_keeps_total_zero(self, monkeypatch) -> None:
        self._install(monkeypatch, (False, ""), (True, "  anthropic ok\n"))
        oc = od.collect_openclaw_summary()
        assert oc.fallback_total == 0
        assert oc.models_line == "UNAVAILABLE"

    def test_both_commands_are_invoked(self, monkeypatch) -> None:
        stub = self._install(monkeypatch, (True, "Runtime: bun\n"), (True, "Fallbacks (1)\n"))
        od.collect_openclaw_summary()
        assert stub.find("openclaw gateway status")
        assert stub.find("openclaw models status")


# ---------------------------------------------------------------------------
# collect_slack_health
# ---------------------------------------------------------------------------


class TestCollectSlackHealth:
    def _patch(self, monkeypatch, result) -> List[Any]:
        seen: List[Any] = []

        def _fake(method, token, payload):
            seen.append((method, token, payload))
            if isinstance(result, Exception):
                raise result
            return result

        monkeypatch.setattr(od, "slack_api", _fake)
        return seen

    @pytest.mark.parametrize(("token", "channel"), [("", "C1"), ("tok", ""), ("", "")])
    def test_missing_credentials_skip_the_api_call(self, monkeypatch, token: str, channel: str) -> None:
        seen = self._patch(monkeypatch, {"ok": True})
        health = od.collect_slack_health(token, channel)
        assert health.status == "UNRESOLVED"
        assert "missing" in health.detail
        assert seen == [], "자격증명이 없는데 Slack 을 호출했다"

    def test_successful_auth_test_is_ready(self, monkeypatch) -> None:
        seen = self._patch(monkeypatch, {"ok": True, "user": "bot"})
        health = od.collect_slack_health("tok", "C1")
        assert health.status == "READY"
        assert seen == [("auth.test", "tok", {})]

    def test_api_error_is_surfaced_in_detail(self, monkeypatch) -> None:
        """`invalid_auth` 가 detail 에 남아야 사람이 원인을 안다."""
        self._patch(monkeypatch, {"ok": False, "error": "invalid_auth"})
        health = od.collect_slack_health("tok", "C1")
        assert health.status == "UNRESOLVED"
        assert health.detail == "auth.test=invalid_auth"

    def test_error_field_absent_falls_back_to_unknown(self, monkeypatch) -> None:
        self._patch(monkeypatch, {"ok": False})
        assert od.collect_slack_health("tok", "C1").detail == "auth.test=unknown"

    def test_network_error_is_unresolved_not_raised(self, monkeypatch) -> None:
        self._patch(monkeypatch, urllib.error.URLError("dns"))
        health = od.collect_slack_health("tok", "C1")
        assert health.status == "UNRESOLVED"
        assert health.detail == "auth.test request failed"


# ---------------------------------------------------------------------------
# should_post_today
# ---------------------------------------------------------------------------


MARKER = "[ops-10am-digest:2026-08-28]"


class TestShouldPostToday:
    def _patch(self, monkeypatch, pages) -> List[Dict[str, Any]]:
        """`pages` 를 순서대로 반환하는 `slack_api` 대역. 예외면 raise 한다."""
        calls: List[Dict[str, Any]] = []
        queue = list(pages)

        def _fake(method, token, payload):
            calls.append(dict(payload))
            item = queue.pop(0) if queue else {"ok": True, "messages": []}
            if isinstance(item, Exception):
                raise item
            return item

        monkeypatch.setattr(od, "slack_api", _fake)
        return calls

    @pytest.mark.parametrize(("token", "channel"), [("", "C1"), ("tok", "")])
    def test_missing_credentials_default_to_posting(self, monkeypatch, token: str, channel: str) -> None:
        calls = self._patch(monkeypatch, [])
        assert od.should_post_today(token, channel, MARKER) is True
        assert calls == [], "자격증명이 없는데 히스토리를 조회했다"

    def test_marker_already_present_blocks_the_post(self, monkeypatch) -> None:
        self._patch(monkeypatch, [{"ok": True, "messages": [{"text": f"어쩌구 {MARKER}"}]}])
        assert od.should_post_today("tok", "C1", MARKER) is False

    def test_unrelated_messages_allow_the_post(self, monkeypatch) -> None:
        self._patch(monkeypatch, [{"ok": True, "messages": [{"text": "[ops-10am-digest:2026-08-27]"}]}])
        assert od.should_post_today("tok", "C1", MARKER) is True

    def test_first_page_requests_channel_and_limit_without_cursor(self, monkeypatch) -> None:
        calls = self._patch(monkeypatch, [{"ok": True, "messages": []}])
        od.should_post_today("tok", "C1", MARKER)
        assert calls == [{"channel": "C1", "limit": "200"}]

    def test_pagination_follows_the_cursor_until_the_marker(self, monkeypatch) -> None:
        calls = self._patch(
            monkeypatch,
            [
                {"ok": True, "messages": [{"text": "잡담"}], "response_metadata": {"next_cursor": "c1"}},
                {"ok": True, "messages": [{"text": MARKER}], "response_metadata": {"next_cursor": "c2"}},
            ],
        )
        assert od.should_post_today("tok", "C1", MARKER) is False
        assert [c.get("cursor") for c in calls] == [None, "c1"]

    def test_blank_cursor_stops_pagination(self, monkeypatch) -> None:
        calls = self._patch(
            monkeypatch,
            [{"ok": True, "messages": [], "response_metadata": {"next_cursor": "   "}}],
        )
        assert od.should_post_today("tok", "C1", MARKER) is True
        assert len(calls) == 1, "빈 커서인데 다음 페이지를 요청했다"

    def test_pagination_is_capped_at_five_pages(self, monkeypatch) -> None:
        """커서가 무한히 이어져도 5페이지에서 멈춰야 한다."""
        calls = self._patch(
            monkeypatch,
            [{"ok": True, "messages": [], "response_metadata": {"next_cursor": "c"}} for _ in range(10)],
        )
        assert od.should_post_today("tok", "C1", MARKER) is True
        assert len(calls) == 5

    def test_api_failure_defaults_to_posting(self, monkeypatch) -> None:
        """조회 실패 시 '이미 올렸다'로 오판해 침묵하는 것보다 중복이 낫다."""
        self._patch(monkeypatch, [{"ok": False, "error": "channel_not_found"}])
        assert od.should_post_today("tok", "C1", MARKER) is True

    def test_network_error_defaults_to_posting(self, monkeypatch) -> None:
        self._patch(monkeypatch, [urllib.error.URLError("dns")])
        assert od.should_post_today("tok", "C1", MARKER) is True

    def test_non_string_message_text_does_not_raise(self, monkeypatch) -> None:
        self._patch(monkeypatch, [{"ok": True, "messages": [{"text": None}, {}]}])
        assert od.should_post_today("tok", "C1", MARKER) is True


# ---------------------------------------------------------------------------
# read_state / write_state
# ---------------------------------------------------------------------------


class TestStateIO:
    def test_round_trip_preserves_payload(self, tmp_path) -> None:
        path = tmp_path / "nested" / "state.json"
        od.write_state(path, {"gh_failure_count_24h": 3, "메모": "한글"})
        assert od.read_state(path) == {"gh_failure_count_24h": 3, "메모": "한글"}

    def test_write_creates_parent_directories(self, tmp_path) -> None:
        path = tmp_path / "a" / "b" / "state.json"
        od.write_state(path, {"x": 1})
        assert path.exists()

    def test_korean_is_not_escaped(self, tmp_path) -> None:
        path = tmp_path / "state.json"
        od.write_state(path, {"메모": "한글"})
        assert "한글" in path.read_text(encoding="utf-8")

    def test_temp_file_is_not_left_behind(self, tmp_path) -> None:
        """`.tmp` 잔재가 남으면 다음 실행이 부분 기록을 읽을 수 있다."""
        path = tmp_path / "state.json"
        od.write_state(path, {"x": 1})
        assert list(tmp_path.iterdir()) == [path]

    def test_write_replaces_previous_content(self, tmp_path) -> None:
        path = tmp_path / "state.json"
        od.write_state(path, {"x": 1})
        od.write_state(path, {"y": 2})
        assert od.read_state(path) == {"y": 2}

    def test_missing_file_reads_as_empty_dict(self, tmp_path) -> None:
        assert od.read_state(tmp_path / "없음.json") == {}

    def test_corrupt_json_reads_as_empty_dict(self, tmp_path) -> None:
        """손상된 상태 파일이 크론을 죽이면 안 된다 — delta 만 N/A 가 된다."""
        path = tmp_path / "state.json"
        path.write_text("{절반만", encoding="utf-8")
        assert od.read_state(path) == {}


# ---------------------------------------------------------------------------
# build_actions
# ---------------------------------------------------------------------------


def _gh(count: int = 0, links: List[str] | None = None) -> od.GitHubSummary:
    return od.GitHubSummary(failure_count_24h=count, latest_failure_links=list(links or []))


def _vercel(rate: str = "0/3", *, state: str = "READY", logs: str = "NO", link: str = "") -> od.VercelSummary:
    return od.VercelSummary(
        production_state=state,
        error_logs_found=logs,
        recent3_failure_rate=rate,
        recent_deploy_link=link,
    )


def _sentry(status: str = "CLEAR", count: int = 0, link: str = "") -> od.SentrySummary:
    return od.SentrySummary(status=status, unresolved_count=count, issue_link=link)


def _oc(*, total: int = 0, degraded: int = 0, auth: int = 0, runtime: str = "bun") -> od.OpenClawSummary:
    return od.OpenClawSummary(
        runtime=runtime,
        rpc_probe="ok",
        fallback_total=total,
        fallback_degraded_or_missing=degraded,
        auth_issue_count=auth,
        models_line="Fallbacks (0)",
    )


def _slack(status: str = "READY") -> od.SlackHealth:
    return od.SlackHealth(status=status, detail="auth.test ok")


class TestBuildActions:
    def test_all_clear_yields_the_no_action_placeholder(self) -> None:
        actions = od.build_actions(_gh(), _vercel(), _sentry(), _oc(), _slack())
        assert actions == ["@ops | 10:30 | 현재 즉시 조치 필요 항목 없음"]

    def test_github_failures_add_an_ops_action(self) -> None:
        actions = od.build_actions(_gh(2), _vercel(), _sentry(), _oc(), _slack())
        assert any("GitHub" in a for a in actions)

    def test_github_sentinel_does_not_add_an_action(self) -> None:
        """`-1`(조회 실패)은 실패 건수가 아니다 — 가짜 액션을 만들면 안 된다."""
        actions = od.build_actions(_gh(-1), _vercel(), _sentry(), _oc(), _slack())
        assert not any("GitHub" in a for a in actions)

    def test_vercel_failures_add_an_action(self) -> None:
        actions = od.build_actions(_gh(), _vercel("1/3"), _sentry(), _oc(), _slack())
        assert any("Vercel" in a for a in actions)

    def test_vercel_unavailable_does_not_add_an_action(self) -> None:
        """CLI 가 없는 로컬 실행에서 매일 가짜 Vercel 액션이 뜨면 안 된다."""
        actions = od.build_actions(_gh(), _vercel("UNAVAILABLE"), _sentry(), _oc(), _slack())
        assert not any("Vercel" in a for a in actions)

    def test_openclaw_degraded_adds_an_ai_action(self) -> None:
        actions = od.build_actions(_gh(), _vercel(), _sentry(), _oc(degraded=1), _slack())
        assert any("OpenClaw" in a for a in actions)

    def test_openclaw_auth_issue_alone_adds_an_ai_action(self) -> None:
        actions = od.build_actions(_gh(), _vercel(), _sentry(), _oc(auth=1), _slack())
        assert any("OpenClaw" in a for a in actions)

    def test_slack_not_ready_adds_an_action(self) -> None:
        actions = od.build_actions(_gh(), _vercel(), _sentry(), _oc(), _slack("UNRESOLVED"))
        assert any("Slack" in a for a in actions)

    def test_multiple_signals_accumulate_in_priority_order(self) -> None:
        actions = od.build_actions(
            _gh(2), _vercel("2/3"), _sentry("OPEN", 4), _oc(degraded=1, auth=1), _slack("UNRESOLVED")
        )
        assert len(actions) == 5
        assert not any("없음" in a for a in actions), "실제 이슈가 있는데 placeholder 가 섞였다"
        assert [a.split("|")[0].strip() for a in actions] == ["@ops", "@ops", "@security", "@ai", "@ops"]


# ---------------------------------------------------------------------------
# format_digest
# ---------------------------------------------------------------------------


def _digest(**over: Any) -> str:
    kwargs: Dict[str, Any] = {
        "marker": MARKER,
        "gh": _gh(1, ["https://gh/1"]),
        "vercel": _vercel(link="https://prod.example.app"),
        "sentry": _sentry("OPEN", 2, "https://sentry.io/x"),
        "oc": _oc(total=4, degraded=1),
        "slack": _slack(),
        "actions": ["A", "B"],
        "prev_state": {"gh_failure_count_24h": 0, "fallback_degraded_or_missing": 0},
        "links": ["https://gh/1"],
    }
    kwargs.update(over)
    return od.format_digest(
        kwargs["marker"],
        kwargs["gh"],
        kwargs["vercel"],
        kwargs["sentry"],
        kwargs["oc"],
        kwargs["slack"],
        kwargs["actions"],
        kwargs["prev_state"],
        kwargs["links"],
    )


class TestFormatDigest:
    def test_line_order_and_marker_placement(self) -> None:
        """Slack 에서 마커로 중복을 판정하므로 마지막 줄에 그대로 있어야 한다."""
        lines = _digest().split("\n")
        assert lines[0] == "10:00 Ops Digest (KST)"
        assert lines[1].startswith("P0:")
        assert lines[2].startswith("P1:")
        assert lines[3].startswith("P2:")
        assert lines[4].startswith("Action:")
        assert lines[5].startswith("Links:")
        assert lines[6] == MARKER

    def test_p0_carries_every_subsystem_status(self) -> None:
        p0 = _digest().split("\n")[1]
        assert "GH 실패 1건" in p0
        assert "Vercel READY (errors:NO)" in p0
        assert "Sentry OPEN (unresolved:2)" in p0
        assert "OpenClaw Runtime bun, RPC ok" in p0
        assert "Slack READY" in p0

    def test_sentinel_counts_render_as_na(self) -> None:
        """`-1` 이 그대로 렌더링되면 사람이 '-1건 실패'를 읽게 된다."""
        p0 = _digest(gh=_gh(-1), sentry=_sentry("UNKNOWN", -1)).split("\n")[1]
        assert "GH 실패 N/A건" in p0
        assert "(unresolved:N/A)" in p0

    def test_fallback_state_uses_the_total_when_known(self) -> None:
        assert "1/4 degraded_or_missing" in _digest().split("\n")[2]

    def test_fallback_state_collapses_to_zero_zero_without_a_total(self) -> None:
        assert "내구성 0/0 |" in _digest(oc=_oc(total=0, degraded=0)).split("\n")[2]

    def test_deltas_are_signed_against_previous_state(self) -> None:
        p2 = _digest(
            gh=_gh(5),
            oc=_oc(total=4, degraded=1),
            prev_state={"gh_failure_count_24h": 2, "fallback_degraded_or_missing": 3},
        ).split("\n")[3]
        assert "GH 실패 +3" in p2
        assert "모델 가용성 이슈 -2" in p2

    def test_missing_previous_state_renders_na_not_zero(self) -> None:
        """이전 상태가 없을 때 `+0` 을 쓰면 '변화 없음'이라는 거짓 신호가 된다."""
        p2 = _digest(prev_state={}).split("\n")[3]
        assert "GH 실패 N/A" in p2
        assert "모델 가용성 이슈 N/A" in p2

    def test_github_sentinel_suppresses_its_delta_only(self) -> None:
        p2 = _digest(gh=_gh(-1)).split("\n")[3]
        assert "GH 실패 N/A" in p2
        assert "모델 가용성 이슈 +1" in p2

    def test_action_line_shows_two_and_elides_the_rest(self) -> None:
        action = _digest(actions=["A", "B", "C", "D"]).split("\n")[4]
        assert action == "Action: A / B / ..."

    def test_action_line_without_elision(self) -> None:
        assert _digest(actions=["A", "B"]).split("\n")[4] == "Action: A / B"

    def test_links_are_capped_at_three_and_blanks_dropped(self) -> None:
        links = _digest(links=["a", "", "b", "c", "d"]).split("\n")[5]
        assert links == "Links: a | b | c"

    def test_no_links_render_na(self) -> None:
        assert _digest(links=["", ""]).split("\n")[5] == "Links: N/A"


# ---------------------------------------------------------------------------
# write_github_outputs
# ---------------------------------------------------------------------------


class TestWriteGithubOutputs:
    def test_no_env_is_a_noop(self, monkeypatch, tmp_path) -> None:
        """로컬 실행(액션 밖)에서 아무 파일도 만들면 안 된다."""
        monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
        monkeypatch.chdir(tmp_path)
        od.write_github_outputs({"a": "b"})
        assert list(tmp_path.iterdir()) == []

    def test_single_line_values_use_key_equals_value(self, monkeypatch, tmp_path) -> None:
        out = tmp_path / "gh_output"
        monkeypatch.setenv("GITHUB_OUTPUT", str(out))
        od.write_github_outputs({"should_post": "true", "marker": MARKER})
        assert out.read_text(encoding="utf-8") == f"should_post=true\nmarker={MARKER}\n"

    def test_multiline_values_use_heredoc(self, monkeypatch, tmp_path) -> None:
        """다이제스트는 여러 줄이라 `key=value` 로 쓰면 액션 출력이 깨진다."""
        out = tmp_path / "gh_output"
        monkeypatch.setenv("GITHUB_OUTPUT", str(out))
        od.write_github_outputs({"message": "첫 줄\n둘째 줄"})
        assert out.read_text(encoding="utf-8") == "message<<EOF\n첫 줄\n둘째 줄\nEOF\n"

    def test_writes_are_appended_not_truncated(self, monkeypatch, tmp_path) -> None:
        out = tmp_path / "gh_output"
        out.write_text("existing=1\n", encoding="utf-8")
        monkeypatch.setenv("GITHUB_OUTPUT", str(out))
        od.write_github_outputs({"a": "b"})
        assert out.read_text(encoding="utf-8") == "existing=1\na=b\n"


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


@pytest.fixture
def main_env(monkeypatch, tmp_path):
    """`main()` 의 모든 외부 경계를 대역으로 바꾸고 호출 인자를 수집한다."""
    calls: Dict[str, Any] = {}

    def _fake_github(repo, token):
        calls["gh"] = (repo, token)
        return _gh(2, ["https://gh/1", "https://gh/2"])

    def _fake_sentry(org, project, token):
        calls["sentry"] = (org, project, token)
        return _sentry("OPEN", 3, "https://sentry.io/x")

    def _fake_slack(token, channel):
        calls["slack"] = (token, channel)
        return _slack()

    def _fake_should_post(token, channel, marker):
        calls["post"] = (token, channel, marker)
        return True

    monkeypatch.setattr(od, "collect_github_summary", _fake_github)
    monkeypatch.setattr(od, "collect_vercel_summary", lambda: _vercel("1/3", link="https://prod.example.app"))
    monkeypatch.setattr(od, "collect_sentry_summary", _fake_sentry)
    monkeypatch.setattr(od, "collect_openclaw_summary", lambda: _oc(total=4, degraded=1, auth=1))
    monkeypatch.setattr(od, "collect_slack_health", _fake_slack)
    monkeypatch.setattr(od, "should_post_today", _fake_should_post)

    state_file = tmp_path / "_state" / "ops-10am-digest-state.json"
    gh_output = tmp_path / "gh_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(gh_output))
    for name in ("GITHUB_TOKEN", "SLACK_BOT_TOKEN", "SENTRY_AUTH_TOKEN", "SENTRY_ORG", "SENTRY_PROJECT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(sys, "argv", ["prog", "--state-file", str(state_file)])

    calls["state_file"] = state_file
    calls["gh_output"] = gh_output
    return calls


class TestMain:
    def test_returns_zero_and_prints_the_digest(self, main_env, capsys) -> None:
        assert od.main() == 0
        out = capsys.readouterr().out
        assert "10:00 Ops Digest (KST)" in out
        assert "should_post=true" in out

    def test_marker_uses_todays_kst_date(self, main_env, capsys) -> None:
        od.main()
        expected = datetime.now(od.get_kst_timezone()).strftime("%Y-%m-%d")
        assert f"[ops-10am-digest:{expected}]" in capsys.readouterr().out

    def test_credentials_and_args_reach_each_collector(self, main_env, monkeypatch) -> None:
        monkeypatch.setenv("GITHUB_TOKEN", "ghtok")
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb")
        monkeypatch.setenv("SENTRY_AUTH_TOKEN", "sentrytok")
        monkeypatch.setenv("SENTRY_ORG", "org")
        monkeypatch.setenv("SENTRY_PROJECT", "proj")
        monkeypatch.setattr(
            sys,
            "argv",
            ["prog", "--repo", "o/r", "--slack-channel", "C9", "--state-file", str(main_env["state_file"])],
        )
        od.main()
        assert main_env["gh"] == ("o/r", "ghtok")
        assert main_env["sentry"] == ("org", "proj", "sentrytok")
        assert main_env["slack"] == ("xoxb", "C9")
        assert main_env["post"][:2] == ("xoxb", "C9")

    def test_repo_and_channel_default_to_environment(self, main_env, monkeypatch) -> None:
        """워크플로우는 인자 없이 부르고 `GITHUB_REPOSITORY` 로만 대상을 알린다."""
        monkeypatch.setenv("GITHUB_REPOSITORY", "env/repo")
        monkeypatch.setenv("SLACK_CHANNEL_ID", "C-env")
        od.main()
        assert main_env["gh"][0] == "env/repo"
        assert main_env["slack"][1] == "C-env"

    def test_repo_falls_back_to_the_hardcoded_default(self, main_env, monkeypatch) -> None:
        monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
        monkeypatch.delenv("SLACK_CHANNEL_ID", raising=False)
        od.main()
        assert main_env["gh"][0] == "Twodragon0/investing"
        assert main_env["slack"][1] == ""

    def test_state_is_persisted_for_the_next_run(self, main_env) -> None:
        od.main()
        state = json.loads(main_env["state_file"].read_text(encoding="utf-8"))
        assert state["gh_failure_count_24h"] == 2
        assert state["fallback_degraded_or_missing"] == 1
        assert state["timestamp"].startswith(datetime.now(od.get_kst_timezone()).strftime("%Y-%m-%d"))

    def test_previous_state_drives_the_delta_line(self, main_env, capsys) -> None:
        main_env["state_file"].parent.mkdir(parents=True, exist_ok=True)
        main_env["state_file"].write_text(
            json.dumps({"gh_failure_count_24h": 5, "fallback_degraded_or_missing": 0}), encoding="utf-8"
        )
        od.main()
        out = capsys.readouterr().out
        assert "GH 실패 -3" in out
        assert "모델 가용성 이슈 +1" in out

    def test_action_outputs_are_written(self, main_env) -> None:
        od.main()
        content = main_env["gh_output"].read_text(encoding="utf-8")
        assert "message<<EOF\n10:00 Ops Digest (KST)" in content
        assert "should_post=true" in content
        assert "slack_health=READY" in content
        assert f"marker=[ops-10am-digest:{datetime.now(od.get_kst_timezone()).strftime('%Y-%m-%d')}]" in content

    def test_links_combine_every_source(self, main_env, capsys) -> None:
        """GH 링크 2건이 앞자리를 차지하고 상한 3에서 잘린다."""
        od.main()
        links_line = [ln for ln in capsys.readouterr().out.split("\n") if ln.startswith("Links:")][0]
        assert links_line == "Links: https://gh/1 | https://gh/2 | https://prod.example.app"

    def test_docs_link_is_appended_when_nothing_else_exists(self, main_env, monkeypatch, capsys) -> None:
        monkeypatch.setattr(od, "collect_github_summary", lambda repo, token: _gh())
        monkeypatch.setattr(od, "collect_vercel_summary", lambda: _vercel(link=""))
        monkeypatch.setattr(od, "collect_sentry_summary", lambda o, p, t: _sentry(link=""))
        od.main()
        links_line = [ln for ln in capsys.readouterr().out.split("\n") if ln.startswith("Links:")][0]
        assert links_line == "Links: https://docs.openclaw.ai/cli/models"

    def test_duplicate_marker_blocks_posting(self, main_env, monkeypatch, capsys) -> None:
        monkeypatch.setattr(od, "should_post_today", lambda token, channel, marker: False)
        assert od.main() == 0
        assert "should_post=false" in capsys.readouterr().out
        assert "should_post=false" in main_env["gh_output"].read_text(encoding="utf-8")
