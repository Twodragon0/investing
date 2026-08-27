"""`scripts/respond_ai_mentions.py` 의 Slack API·본문 조립·main 루프 테스트.

`tests/test_respond_ai_mentions.py` 는 `should_reply` 게이팅만 덮는다. 이 파일은
나머지를 덮는다 — `env_first`, `slack_api` 재시도, 포스트 조회·본문 조립,
`channel_id_for_alias` 폴백 사슬, `main()` 루프.

## 이 모듈에 특별히 필요한 격리

`tests/conftest.py` 의 네트워크 차단은 **`requests` 의 `HTTPAdapter.send`** 를 막는다.
이 모듈은 `requests` 를 쓰지 않고 **`urllib.request.urlopen`** 을 직접 쓰므로 그 차단에
걸리지 않는다. 남은 안전망은 `socket.getaddrinfo` 스텁뿐인데, 그건 연결을 고정 IP 로
보낼 뿐 "호출되지 않음" 을 보장하지 않는다.

동시에 `main()` 은 `os.getenv` 로 토큰을 찾는다. 개발자 셸에 실제 `SLACK_BOT_TOKEN` 이
있으면 테스트가 **실제 Slack 워크스페이스로 요청을 보낼 수 있다.**

그래서 이 파일은 autouse 로 두 겹을 깐다:

1. Slack 관련 env 를 전부 지운다 (실제 토큰 유입 차단)
2. `urlopen` 을 "호출되면 실패" 스텁으로 바꾼다 (조용한 외부 호출 불가)

토큰 값은 전부 명백한 더미(`xoxb-dummy-...`)이며 로그에 찍지 않는다.

## 덮지 않은 2줄

| 줄 | 내용 | 근거 |
|---|---|---|
| 67 | `slack_api` 끝의 `return {"ok": False, "error": "unknown_api_error"}` | 방어적 코드. 3회 루프의 모든 경로가 return / continue / raise 로 끝난다 — 429 는 `attempt < max_attempts` 일 때만 continue 하고 마지막 시도에서는 raise, `URLError` 도 동일. 따라서 루프를 다 돌고 이 줄에 닿을 수 없다 |
| 487 | `raise SystemExit(main())` | `__main__` 가드 본문 |

## 범위 밖 — 보고만

`intent_keywords` · `fallback_help_text` 는 **저장소 전체에서 호출처가 0건**이다
(2026-08-27 실측: `scripts/` `.github/` `tests/` `docs/` 전수 grep). 죽은 코드지만
삭제는 이 PR 범위 밖이라 `TestUnusedHelpers` 로 현재 동작만 고정했다.
"""

from __future__ import annotations

import importlib.util
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List

import pytest

_MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "respond_ai_mentions.py"
_spec = importlib.util.spec_from_file_location("respond_ai_mentions_pipeline", _MODULE_PATH)
assert _spec is not None and _spec.loader is not None
respond = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(respond)

_DUMMY_TOKEN = "xoxb-dummy-token"  # noqa: S105 -- 명백한 더미. 실제 자격증명이 아니다
_DUMMY_CHANNEL = "C0DUMMY000"

# `env_first` 가 훑는 모든 접두사. 실제 셸 값이 새어 들어오면 안 된다.
_ENV_PREFIXES = ("SLACK_", "OPENCLAW_SLACK_", "AI_SLACK_")


@pytest.fixture(autouse=True)
def _no_real_slack(monkeypatch):
    """실제 토큰 유입과 실제 urlopen 호출을 둘 다 막는다."""
    import os

    for key in list(os.environ):
        if key.startswith(_ENV_PREFIXES):
            monkeypatch.delenv(key, raising=False)

    def _blocked(*_args, **_kwargs):
        raise AssertionError(
            "urlopen 이 호출됐다 — 이 테스트는 slack_api 또는 urlopen 을 대체해야 한다. "
            "conftest 의 requests 차단은 urllib 을 막지 못한다."
        )

    monkeypatch.setattr(urllib.request, "urlopen", _blocked)


@pytest.fixture
def posts_dir(tmp_path, monkeypatch):
    """`POSTS_DIR` 을 tmp 로 돌린다 — 실제 `_posts/` 를 읽으면 결과가 날짜에 따라 흔들린다."""
    posts = tmp_path / "_posts"
    posts.mkdir()
    monkeypatch.setattr(respond, "POSTS_DIR", posts)
    return posts


class _FakeHTTPResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _FakeHTTPResponse:
        return self

    def __exit__(self, *_exc) -> None:
        return None


# ---------------------------------------------------------------------------
# env_first
# ---------------------------------------------------------------------------


class TestEnvFirst:
    def test_returns_first_non_empty(self, monkeypatch) -> None:
        monkeypatch.setenv("SLACK_A", "")
        monkeypatch.setenv("SLACK_B", "  값  ")
        monkeypatch.setenv("SLACK_C", "다른값")
        assert respond.env_first("SLACK_A", "SLACK_B", "SLACK_C") == "값"

    def test_whitespace_only_is_treated_as_empty(self, monkeypatch) -> None:
        monkeypatch.setenv("SLACK_A", "   ")
        monkeypatch.setenv("SLACK_B", "실제값")
        assert respond.env_first("SLACK_A", "SLACK_B") == "실제값"

    def test_all_missing_returns_empty_string(self) -> None:
        assert respond.env_first("SLACK_NOPE_1", "SLACK_NOPE_2") == ""

    def test_no_keys_returns_empty_string(self) -> None:
        assert respond.env_first() == ""


# ---------------------------------------------------------------------------
# slack_api
# ---------------------------------------------------------------------------


class TestSlackApi:
    def test_posts_form_encoded_body_with_bearer_token(self, monkeypatch) -> None:
        captured: Dict[str, Any] = {}

        def fake_urlopen(req, timeout=None):
            captured["url"] = req.full_url
            captured["method"] = req.get_method()
            captured["data"] = req.data
            captured["headers"] = dict(req.header_items())
            captured["timeout"] = timeout
            return _FakeHTTPResponse(b'{"ok": true}')

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

        result = respond.slack_api("auth.test", _DUMMY_TOKEN, {"channel": _DUMMY_CHANNEL})

        assert result == {"ok": True}
        assert captured["url"] == f"{respond.SLACK_API_BASE}/auth.test"
        assert captured["url"].startswith("https://"), "평문 HTTP 로 토큰을 보낸다"
        assert captured["method"] == "POST"
        assert captured["data"] == b"channel=C0DUMMY000"
        assert captured["timeout"] == 20
        headers = {k.lower(): v for k, v in captured["headers"].items()}
        assert headers["Authorization".lower()] == f"Bearer {_DUMMY_TOKEN}"
        assert headers["Content-type".lower()] == "application/x-www-form-urlencoded"

    def test_rate_limit_retries_after_sleeping(self, monkeypatch) -> None:
        """429 는 `Retry-After` 만큼 기다린 뒤 재시도한다."""
        sleeps: List[float] = []
        monkeypatch.setattr(respond.time, "sleep", sleeps.append)

        calls = {"n": 0}

        def fake_urlopen(req, timeout=None):
            calls["n"] += 1
            if calls["n"] == 1:
                raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", {"Retry-After": "7"}, None)
            return _FakeHTTPResponse(b'{"ok": true}')

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

        assert respond.slack_api("chat.postMessage", _DUMMY_TOKEN, {}) == {"ok": True}
        assert calls["n"] == 2
        assert sleeps == [7], sleeps

    def test_rate_limit_defaults_retry_after_to_one_second(self, monkeypatch) -> None:
        sleeps: List[float] = []
        monkeypatch.setattr(respond.time, "sleep", sleeps.append)
        calls = {"n": 0}

        def fake_urlopen(req, timeout=None):
            calls["n"] += 1
            if calls["n"] == 1:
                raise urllib.error.HTTPError(req.full_url, 429, "rate", {}, None)
            return _FakeHTTPResponse(b'{"ok": true}')

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        respond.slack_api("chat.postMessage", _DUMMY_TOKEN, {})
        assert sleeps == [1]

    def test_rate_limit_raises_after_exhausting_attempts(self, monkeypatch) -> None:
        """무한 재시도하지 않는다 — 3회 시도 후 올린다."""
        monkeypatch.setattr(respond.time, "sleep", lambda _s: None)
        calls = {"n": 0}

        def always_429(req, timeout=None):
            calls["n"] += 1
            raise urllib.error.HTTPError(req.full_url, 429, "rate", {"Retry-After": "1"}, None)

        monkeypatch.setattr(urllib.request, "urlopen", always_429)
        with pytest.raises(urllib.error.HTTPError):
            respond.slack_api("chat.postMessage", _DUMMY_TOKEN, {})
        assert calls["n"] == 3

    def test_non_429_http_error_is_raised_immediately(self, monkeypatch) -> None:
        calls = {"n": 0}

        def http_500(req, timeout=None):
            calls["n"] += 1
            raise urllib.error.HTTPError(req.full_url, 500, "server error", {}, None)

        monkeypatch.setattr(urllib.request, "urlopen", http_500)
        with pytest.raises(urllib.error.HTTPError):
            respond.slack_api("auth.test", _DUMMY_TOKEN, {})
        assert calls["n"] == 1, "500 을 재시도했다 — 429 만 재시도 대상이다"

    def test_url_error_is_retried_then_raised(self, monkeypatch) -> None:
        monkeypatch.setattr(respond.time, "sleep", lambda _s: None)
        calls = {"n": 0}

        def url_error(req, timeout=None):
            calls["n"] += 1
            raise urllib.error.URLError("연결 실패")

        monkeypatch.setattr(urllib.request, "urlopen", url_error)
        with pytest.raises(urllib.error.URLError):
            respond.slack_api("auth.test", _DUMMY_TOKEN, {})
        assert calls["n"] == 3

    def test_url_error_recovers_on_retry(self, monkeypatch) -> None:
        monkeypatch.setattr(respond.time, "sleep", lambda _s: None)
        calls = {"n": 0}

        def flaky(req, timeout=None):
            calls["n"] += 1
            if calls["n"] < 3:
                raise urllib.error.URLError("일시 장애")
            return _FakeHTTPResponse(b'{"ok": true, "user_id": "U1"}')

        monkeypatch.setattr(urllib.request, "urlopen", flaky)
        assert respond.slack_api("auth.test", _DUMMY_TOKEN, {})["user_id"] == "U1"


# ---------------------------------------------------------------------------
# read_frontmatter_value / latest_post
# ---------------------------------------------------------------------------


class TestReadFrontmatterValue:
    def test_reads_quoted_value(self, tmp_path) -> None:
        f = tmp_path / "a.md"
        f.write_text('---\ntitle: "제목입니다"\nexcerpt: "요약"\n---\n본문\n', encoding="utf-8")
        assert respond.read_frontmatter_value(f, "title") == "제목입니다"
        assert respond.read_frontmatter_value(f, "excerpt") == "요약"

    def test_missing_key_returns_empty(self, tmp_path) -> None:
        f = tmp_path / "a.md"
        f.write_text("---\ntitle: T\n---\n", encoding="utf-8")
        assert respond.read_frontmatter_value(f, "description") == ""

    def test_unreadable_file_returns_empty(self, tmp_path) -> None:
        assert respond.read_frontmatter_value(tmp_path / "없는파일.md", "title") == ""

    def test_only_line_start_matches(self, tmp_path) -> None:
        """들여쓰기된 같은 키는 매칭하지 않는다 — 최상위 front matter 만 본다."""
        f = tmp_path / "a.md"
        f.write_text("---\nnested:\n  title: 내부제목\n---\n", encoding="utf-8")
        assert respond.read_frontmatter_value(f, "title") == ""


class TestLatestPost:
    def test_returns_lexicographically_last_match(self, posts_dir) -> None:
        for name in ("2026-01-01-daily-news-summary.md", "2026-08-27-daily-news-summary.md"):
            (posts_dir / name).write_text("x", encoding="utf-8")
        result = respond.latest_post("*daily-news-summary*.md")
        assert result is not None
        assert result.name == "2026-08-27-daily-news-summary.md"

    def test_no_match_returns_none(self, posts_dir) -> None:
        assert respond.latest_post("*없는패턴*.md") is None


# ---------------------------------------------------------------------------
# 본문 조립
# ---------------------------------------------------------------------------


class TestBuildSummaryText:
    def test_no_posts_message(self, posts_dir) -> None:
        assert respond.build_summary_text() == "📌 오늘 투자 요약 데이터를 찾지 못했습니다."

    def test_summary_post_renders_title_excerpt_and_link(self, posts_dir) -> None:
        (posts_dir / "2026-08-27-daily-news-summary.md").write_text(
            '---\ntitle: "일일 뉴스 요약 2026-08-27"\nexcerpt: "핵심 요약 문장입니다."\n---\n',
            encoding="utf-8",
        )
        text = respond.build_summary_text()
        assert "- 뉴스 요약: 일일 뉴스 요약 2026-08-27" in text
        assert "- 핵심: 핵심 요약 문장입니다." in text
        assert f"- 요약 링크: {respond.SITE_URL}/market-analysis/2026/08/27/daily-news-summary/" in text

    def test_excerpt_is_truncated_to_180_chars(self, posts_dir) -> None:
        (posts_dir / "2026-08-27-daily-news-summary.md").write_text(
            f'---\ntitle: "T"\nexcerpt: "{"가" * 300}"\n---\n', encoding="utf-8"
        )
        core = next(ln for ln in respond.build_summary_text().splitlines() if ln.startswith("- 핵심: "))
        assert len(core[len("- 핵심: ") :]) == 180

    def test_missing_excerpt_omits_the_line(self, posts_dir) -> None:
        (posts_dir / "2026-08-27-daily-news-summary.md").write_text('---\ntitle: "T"\n---\n', encoding="utf-8")
        assert "- 핵심:" not in respond.build_summary_text()

    def test_missing_title_falls_back(self, posts_dir) -> None:
        (posts_dir / "2026-08-27-daily-news-summary.md").write_text("---\n---\n", encoding="utf-8")
        assert "- 뉴스 요약: 일일 뉴스 요약" in respond.build_summary_text()

    def test_market_report_section(self, posts_dir) -> None:
        (posts_dir / "2026-08-27-daily-market-report.md").write_text(
            '---\ntitle: "시장 리포트"\n---\n', encoding="utf-8"
        )
        text = respond.build_summary_text()
        assert "- 시장 리포트: 시장 리포트" in text
        assert f"- 리포트 링크: {respond.SITE_URL}/market-analysis/2026/08/27/daily-market-report/" in text

    def test_market_report_missing_title_falls_back(self, posts_dir) -> None:
        (posts_dir / "2026-08-27-daily-market-report.md").write_text("---\n---\n", encoding="utf-8")
        assert "- 시장 리포트: 일일 시장 리포트" in respond.build_summary_text()

    def test_unparseable_slug_falls_back_to_site_root(self, posts_dir) -> None:
        """슬러그가 `YYYY-MM-DD-title` 4조각이 아니면 사이트 루트로 보낸다."""
        (posts_dir / "daily-news-summary.md").write_text('---\ntitle: "T"\n---\n', encoding="utf-8")
        assert f"- 요약 링크: {respond.SITE_URL}/" in respond.build_summary_text()

    def test_both_posts_present(self, posts_dir) -> None:
        (posts_dir / "2026-08-27-daily-news-summary.md").write_text('---\ntitle: "N"\n---\n', encoding="utf-8")
        (posts_dir / "2026-08-27-daily-market-report.md").write_text('---\ntitle: "M"\n---\n', encoding="utf-8")
        text = respond.build_summary_text()
        assert "- 뉴스 요약: N" in text and "- 시장 리포트: M" in text


class TestBuildDevStatusText:
    def test_uses_git_branch_and_commit(self, monkeypatch) -> None:
        calls: List[List[str]] = []

        def fake_check_output(cmd, cwd=None, text=None):
            calls.append(cmd)
            if "log" in cmd:
                return "abc1234 fix: 무언가\n"
            return "feature/x\n"

        monkeypatch.setattr(respond.subprocess, "check_output", fake_check_output)
        text = respond.build_dev_status_text()
        assert "- branch: feature/x" in text
        assert "- latest commit: abc1234 fix: 무언가" in text
        assert len(calls) == 2

    @pytest.mark.parametrize(
        "exc",
        [
            FileNotFoundError("git 없음"),
            OSError("실행 실패"),
        ],
    )
    def test_git_failure_falls_back(self, monkeypatch, exc) -> None:
        def boom(*_a, **_kw):
            raise exc

        monkeypatch.setattr(respond.subprocess, "check_output", boom)
        text = respond.build_dev_status_text()
        assert "- branch: main" in text
        assert "- latest commit: unknown" in text

    def test_called_process_error_falls_back(self, monkeypatch) -> None:
        import subprocess as sp

        def boom(*_a, **_kw):
            raise sp.CalledProcessError(1, "git")

        monkeypatch.setattr(respond.subprocess, "check_output", boom)
        assert "- latest commit: unknown" in respond.build_dev_status_text()


class TestBuildStatusTexts:
    def test_ops_status_names_latest_summary_file(self, posts_dir) -> None:
        (posts_dir / "2026-08-27-daily-news-summary.md").write_text("x", encoding="utf-8")
        text = respond.build_ops_status_text()
        assert "- latest summary file: 2026-08-27-daily-news-summary.md" in text
        assert f"- site: {respond.SITE_URL}/" in text

    def test_ops_status_without_summary(self, posts_dir) -> None:
        assert "- latest summary file: none" in respond.build_ops_status_text()

    def test_security_status_names_latest_report(self, posts_dir) -> None:
        (posts_dir / "2026-08-27-daily-security-report.md").write_text("x", encoding="utf-8")
        text = respond.build_security_status_text()
        assert "- latest security report file: 2026-08-27-daily-security-report.md" in text
        assert f"{respond.SITE_URL}/security-alerts/" in text

    def test_security_status_without_report(self, posts_dir) -> None:
        assert "- latest security report file: none" in respond.build_security_status_text()


class TestBuildCoinMonitoringText:
    def test_links_to_latest_market_report(self, posts_dir) -> None:
        (posts_dir / "2026-08-27-daily-market-report.md").write_text("x", encoding="utf-8")
        text = respond.build_coin_monitoring_text()
        assert f"{respond.SITE_URL}/market-analysis/2026/08/27/daily-market-report/" in text
        assert "CoinGecko" in text and "CoinMarketCap" in text

    def test_falls_back_to_site_root_without_report(self, posts_dir) -> None:
        assert f"- 최신 시장 리포트: {respond.SITE_URL}/" in respond.build_coin_monitoring_text()

    def test_unparseable_slug_falls_back(self, posts_dir) -> None:
        (posts_dir / "daily-market-report.md").write_text("x", encoding="utf-8")
        assert f"- 최신 시장 리포트: {respond.SITE_URL}/" in respond.build_coin_monitoring_text()


class TestBuildWorldmonitorText:
    def test_links_to_latest_briefing(self, posts_dir) -> None:
        (posts_dir / "2026-08-27-daily-worldmonitor-briefing.md").write_text("x", encoding="utf-8")
        text = respond.build_worldmonitor_text()
        assert f"{respond.SITE_URL}/market-analysis/2026/08/27/daily-worldmonitor-briefing/" in text
        assert "worldmonitor.app" in text

    def test_falls_back_to_site_root(self, posts_dir) -> None:
        assert f"- 최신 브리핑: {respond.SITE_URL}/" in respond.build_worldmonitor_text()

    def test_unparseable_slug_falls_back(self, posts_dir) -> None:
        (posts_dir / "daily-worldmonitor-briefing.md").write_text("x", encoding="utf-8")
        assert f"- 최신 브리핑: {respond.SITE_URL}/" in respond.build_worldmonitor_text()


# ---------------------------------------------------------------------------
# 라우팅
# ---------------------------------------------------------------------------


class TestWantsCoinMonitoring:
    @pytest.mark.parametrize(
        "text",
        ["실시간 알려줘", "realtime please", "MONITOR now", "모니터링 해줘", "코인 시세", "crypto 어때", "price 확인"],
    )
    def test_positive(self, text: str) -> None:
        assert respond.wants_coin_monitoring(text) is True

    @pytest.mark.parametrize("text", ["오늘 날씨", "배포 상태", ""])
    def test_negative(self, text: str) -> None:
        assert respond.wants_coin_monitoring(text) is False


class TestBuildReplyText:
    def test_ops_alias_ignores_text(self, posts_dir) -> None:
        assert respond.build_reply_text("ops", "코인 실시간") == respond.build_ops_status_text()

    def test_dev_alias(self, monkeypatch) -> None:
        monkeypatch.setattr(respond, "build_dev_status_text", lambda: "DEV")
        assert respond.build_reply_text("dev", "무엇이든") == "DEV"

    def test_security_alias(self, posts_dir) -> None:
        assert respond.build_reply_text("security", "무엇이든") == respond.build_security_status_text()

    @pytest.mark.parametrize(
        "text",
        ["worldmonitor 브리핑", "world monitor 확인", "worldmonitor.app 연동", "지정학 리스크", "global risk 요약"],
    )
    def test_worldmonitor_routing_wins_over_coin(self, posts_dir, text: str) -> None:
        assert respond.build_reply_text("investing", text) == respond.build_worldmonitor_text()

    def test_worldmonitor_beats_coin_when_both_present(self, posts_dir) -> None:
        """지정학 키워드가 코인 키워드보다 먼저 판정된다."""
        result = respond.build_reply_text("investing", "지정학 실시간 코인 모니터링")
        assert result == respond.build_worldmonitor_text()

    def test_coin_routing(self, posts_dir) -> None:
        assert respond.build_reply_text("investing", "실시간 코인") == respond.build_coin_monitoring_text()

    def test_default_routing_is_summary(self, posts_dir) -> None:
        assert respond.build_reply_text("investing", "안녕") == respond.build_summary_text()


class TestChannelIdForAlias:
    def test_openclaw_prefers_specific_env(self, monkeypatch) -> None:
        monkeypatch.setenv("SLACK_CHANNEL_ID_OPENCLAW", "C_OPENCLAW")
        monkeypatch.setenv("SLACK_CHANNEL_ID", "C_GENERIC")
        assert respond.channel_id_for_alias("openclaw") == "C_OPENCLAW"

    def test_openclaw_falls_back_through_ai_names(self, monkeypatch) -> None:
        monkeypatch.setenv("SLACK_CHANNEL_ID_AI", "C_AI")
        assert respond.channel_id_for_alias("openclaw") == "C_AI"

    def test_openclaw_falls_back_to_generic(self, monkeypatch) -> None:
        monkeypatch.setenv("SLACK_CHANNEL", "C_LAST")
        assert respond.channel_id_for_alias("openclaw") == "C_LAST"

    def test_investing_prefers_specific_env(self, monkeypatch) -> None:
        monkeypatch.setenv("SLACK_CHANNEL_ID_INVESTING", "C_INV")
        monkeypatch.setenv("SLACK_CHANNEL_ID", "C_GENERIC")
        assert respond.channel_id_for_alias("investing") == "C_INV"

    def test_investing_falls_back_to_generic(self, monkeypatch) -> None:
        monkeypatch.setenv("AI_SLACK_CHANNEL_ID", "C_AI_GENERIC")
        assert respond.channel_id_for_alias("investing") == "C_AI_GENERIC"

    @pytest.mark.parametrize("alias", ["ops", "dev", "security"])
    def test_generic_alias_uses_uppercased_name(self, monkeypatch, alias: str) -> None:
        monkeypatch.setenv(f"SLACK_CHANNEL_ID_{alias.upper()}", f"C_{alias}")
        assert respond.channel_id_for_alias(alias) == f"C_{alias}"

    def test_generic_alias_falls_back_to_shared_env(self, monkeypatch) -> None:
        monkeypatch.setenv("SLACK_CHANNEL", "C_SHARED")
        assert respond.channel_id_for_alias("ops") == "C_SHARED"

    def test_nothing_configured_returns_empty(self) -> None:
        assert respond.channel_id_for_alias("ops") == ""


class TestUnusedHelpers:
    """저장소 어디에서도 호출되지 않는 두 헬퍼 (2026-08-27 실측 호출처 0건).

    죽은 코드지만 이 PR 은 커버리지 목적이라 삭제하지 않고 보고만 한다. 삭제가
    결정되면 이 클래스도 함께 지우면 된다.
    """

    @pytest.mark.parametrize(
        ("alias", "expected_first"),
        [("ops", "ops"), ("dev", "dev"), ("security", "security"), ("investing", "투자")],
    )
    def test_intent_keywords_first_entry(self, alias: str, expected_first: str) -> None:
        assert respond.intent_keywords(alias)[0] == expected_first

    def test_intent_keywords_default_covers_worldmonitor(self) -> None:
        assert "worldmonitor" in respond.intent_keywords("investing")

    @pytest.mark.parametrize("alias", ["openclaw", "investing"])
    def test_fallback_help_for_investing_aliases(self, alias: str) -> None:
        assert "실시간 코인 모니터링" in respond.fallback_help_text(alias)

    def test_fallback_help_for_ops(self) -> None:
        assert "운영 상태" in respond.fallback_help_text("ops")

    def test_fallback_help_for_security(self) -> None:
        assert "보안 이슈" in respond.fallback_help_text("security")

    def test_fallback_help_default_is_dev(self) -> None:
        assert "dev 상태" in respond.fallback_help_text("dev")


# ---------------------------------------------------------------------------
# has_bot_reply
# ---------------------------------------------------------------------------


class TestHasBotReply:
    def _patch_api(self, monkeypatch, payload: Dict[str, Any], calls: List[Any] | None = None):
        def fake(method, token, data):
            if calls is not None:
                calls.append((method, data))
            return payload

        monkeypatch.setattr(respond, "slack_api", fake)

    def test_true_when_bot_replied_in_thread(self, monkeypatch) -> None:
        self._patch_api(
            monkeypatch,
            {"ok": True, "messages": [{"user": "U_HUMAN", "ts": "1"}, {"user": "U_BOT", "ts": "2"}]},
        )
        assert respond.has_bot_reply(_DUMMY_TOKEN, _DUMMY_CHANNEL, "1", "U_BOT") is True

    def test_thread_parent_by_bot_does_not_count(self, monkeypatch) -> None:
        """부모 메시지가 봇 자신이어도 '이미 답장함' 은 아니다."""
        self._patch_api(monkeypatch, {"ok": True, "messages": [{"user": "U_BOT", "ts": "1"}]})
        assert respond.has_bot_reply(_DUMMY_TOKEN, _DUMMY_CHANNEL, "1", "U_BOT") is False

    def test_false_when_api_not_ok(self, monkeypatch) -> None:
        self._patch_api(monkeypatch, {"ok": False, "error": "channel_not_found"})
        assert respond.has_bot_reply(_DUMMY_TOKEN, _DUMMY_CHANNEL, "1", "U_BOT") is False

    def test_false_when_no_messages(self, monkeypatch) -> None:
        self._patch_api(monkeypatch, {"ok": True})
        assert respond.has_bot_reply(_DUMMY_TOKEN, _DUMMY_CHANNEL, "1", "U_BOT") is False

    def test_request_shape(self, monkeypatch) -> None:
        calls: List[Any] = []
        self._patch_api(monkeypatch, {"ok": True, "messages": []}, calls)
        respond.has_bot_reply(_DUMMY_TOKEN, _DUMMY_CHANNEL, "1700000000.1", "U_BOT")
        (method, data) = calls[0]
        assert method == "conversations.replies"
        assert data["channel"] == _DUMMY_CHANNEL
        assert data["ts"] == "1700000000.1"
        assert data["limit"] == 50


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


class _SlackStub:
    """`slack_api` 대역 — 메서드별 응답을 미리 정하고 호출을 기록한다."""

    def __init__(self, **responses: Any) -> None:
        self.responses: Dict[str, Any] = {
            "auth.test": {"ok": True, "user_id": "U_BOT"},
            "conversations.history": {"ok": True, "messages": []},
            "conversations.replies": {"ok": True, "messages": []},
            "chat.postMessage": {"ok": True},
        }
        self.responses.update(responses)
        self.calls: List[tuple] = []

    def __call__(self, method: str, token: str, data: Dict[str, Any]) -> Dict[str, Any]:
        self.calls.append((method, data))
        value = self.responses[method]
        if isinstance(value, Exception):
            raise value
        if callable(value):
            return value(data)
        return value

    def posted(self) -> List[Dict[str, Any]]:
        return [data for method, data in self.calls if method == "chat.postMessage"]


def _msg(text: str, *, ts: str = "100.1", user: str = "U_HUMAN", **extra: Any) -> Dict[str, Any]:
    base = {"text": text, "ts": ts, "user": user}
    base.update(extra)
    return base


@pytest.fixture
def configured(monkeypatch, posts_dir):
    """토큰·채널이 갖춰진 상태 (더미 값)."""
    monkeypatch.setenv("SLACK_BOT_TOKEN", _DUMMY_TOKEN)
    monkeypatch.setenv("SLACK_CHANNEL_ID", _DUMMY_CHANNEL)
    monkeypatch.setenv("TARGET_CHANNEL_ALIAS", "investing")


class TestMainGuards:
    def test_unsupported_alias_returns_1(self, monkeypatch, caplog) -> None:
        monkeypatch.setenv("TARGET_CHANNEL_ALIAS", "존재하지않는별칭")
        with caplog.at_level("WARNING"):
            assert respond.main() == 1
        assert any("Unsupported alias" in r.message for r in caplog.records)

    def test_alias_is_normalized(self, monkeypatch, posts_dir) -> None:
        """대소문자·공백은 정규화된다 — 워크플로우 입력 오타로 죽지 않는다."""
        monkeypatch.setenv("TARGET_CHANNEL_ALIAS", "  OPS  ")
        assert respond.main() == 0, "정규화 실패 (미설정 토큰으로 0 을 반환해야 한다)"

    def test_missing_token_skips_quietly(self, monkeypatch, posts_dir, caplog) -> None:
        monkeypatch.setenv("TARGET_CHANNEL_ALIAS", "investing")
        monkeypatch.setenv("SLACK_CHANNEL_ID", _DUMMY_CHANNEL)
        with caplog.at_level("INFO"):
            assert respond.main() == 0
        assert any("Missing Slack token or channel" in r.message for r in caplog.records)

    def test_missing_channel_skips_quietly(self, monkeypatch, posts_dir) -> None:
        monkeypatch.setenv("TARGET_CHANNEL_ALIAS", "investing")
        monkeypatch.setenv("SLACK_BOT_TOKEN", _DUMMY_TOKEN)
        assert respond.main() == 0

    def test_default_alias_is_investing(self, monkeypatch, posts_dir) -> None:
        assert respond.main() == 0  # alias 미설정 → investing, 토큰 없음 → 0


class TestMainAuth:
    def test_auth_request_failure_returns_1(self, monkeypatch, configured, caplog) -> None:
        monkeypatch.setattr(respond, "slack_api", _SlackStub(**{"auth.test": OSError("연결 실패")}))
        with caplog.at_level("ERROR"):
            assert respond.main() == 1
        assert any("auth.test request failed" in r.message for r in caplog.records)

    def test_auth_not_ok_returns_1(self, monkeypatch, configured, caplog) -> None:
        monkeypatch.setattr(respond, "slack_api", _SlackStub(**{"auth.test": {"ok": False, "error": "invalid_auth"}}))
        with caplog.at_level("ERROR"):
            assert respond.main() == 1
        assert any("auth.test failed" in r.message for r in caplog.records)

    def test_auth_without_user_id_returns_1(self, monkeypatch, configured, caplog) -> None:
        monkeypatch.setattr(respond, "slack_api", _SlackStub(**{"auth.test": {"ok": True}}))
        with caplog.at_level("ERROR"):
            assert respond.main() == 1
        assert any("no user_id" in r.message for r in caplog.records)


class TestMainHistory:
    def test_history_request_failure_returns_1(self, monkeypatch, configured, caplog) -> None:
        stub = _SlackStub(**{"conversations.history": OSError("타임아웃")})
        monkeypatch.setattr(respond, "slack_api", stub)
        with caplog.at_level("ERROR"):
            assert respond.main() == 1
        assert any("conversations.history request failed" in r.message for r in caplog.records)

    def test_history_not_ok_returns_1(self, monkeypatch, configured, caplog) -> None:
        stub = _SlackStub(**{"conversations.history": {"ok": False, "error": "not_in_channel"}})
        monkeypatch.setattr(respond, "slack_api", stub)
        with caplog.at_level("ERROR"):
            assert respond.main() == 1
        assert any("conversations.history failed" in r.message for r in caplog.records)

    def test_history_window_is_thirty_minutes(self, monkeypatch, configured) -> None:
        stub = _SlackStub()
        monkeypatch.setattr(respond, "slack_api", stub)
        respond.main()
        (_method, data) = next(c for c in stub.calls if c[0] == "conversations.history")
        assert data["channel"] == _DUMMY_CHANNEL
        assert data["limit"] == 30

        from datetime import UTC, datetime

        oldest = float(data["oldest"])
        elapsed = datetime.now(UTC).timestamp() - oldest
        assert 1750 < elapsed < 1850, f"30분 창이 아니다: {elapsed:.0f}s"


class TestMainReplyLoop:
    def test_replies_to_mention(self, monkeypatch, configured) -> None:
        stub = _SlackStub(**{"conversations.history": {"ok": True, "messages": [_msg("<@U_BOT> 오늘 요약 알려줘")]}})
        monkeypatch.setattr(respond, "slack_api", stub)
        assert respond.main() == 0

        (posted,) = stub.posted()
        assert posted["channel"] == _DUMMY_CHANNEL
        assert posted["thread_ts"] == "100.1"
        assert posted["text"].startswith("📌")

    def test_messages_are_processed_oldest_first(self, monkeypatch, configured) -> None:
        history = {
            "ok": True,
            "messages": [
                _msg("<@U_BOT> 나중 메시지", ts="300.0"),
                _msg("<@U_BOT> 먼저 메시지", ts="100.0"),
            ],
        }
        stub = _SlackStub(**{"conversations.history": history})
        monkeypatch.setattr(respond, "slack_api", stub)
        respond.main()
        assert [p["thread_ts"] for p in stub.posted()] == ["100.0", "300.0"]

    def test_reply_cap_is_enforced(self, monkeypatch, configured, caplog) -> None:
        history = {
            "ok": True,
            "messages": [_msg("<@U_BOT> 요약", ts=f"{100 + i}.0") for i in range(6)],
        }
        stub = _SlackStub(**{"conversations.history": history})
        monkeypatch.setattr(respond, "slack_api", stub)
        with caplog.at_level("INFO"):
            respond.main()
        assert len(stub.posted()) == respond.MAX_REPLIES_PER_RUN
        assert any("Reply cap reached" in r.message for r in caplog.records)

    @pytest.mark.parametrize(
        ("message", "why"),
        [
            (_msg("<@U_BOT> 요약", subtype="channel_join"), "subtype 메시지(입장/봇 알림)"),
            (_msg("<@U_BOT> 요약", user="U_BOT"), "봇 자신의 메시지"),
            (_msg(""), "빈 텍스트"),
            (_msg("멘션 없는 잡담"), "멘션 게이트 미통과"),
        ],
    )
    def test_messages_that_must_not_get_a_reply(self, monkeypatch, configured, message, why) -> None:
        stub = _SlackStub(**{"conversations.history": {"ok": True, "messages": [message]}})
        monkeypatch.setattr(respond, "slack_api", stub)
        respond.main()
        assert stub.posted() == [], f"{why} 에 답장했다"

    def test_message_without_ts_is_skipped(self, monkeypatch, configured) -> None:
        stub = _SlackStub(
            **{"conversations.history": {"ok": True, "messages": [{"text": "<@U_BOT> 요약", "user": "U_H"}]}}
        )
        monkeypatch.setattr(respond, "slack_api", stub)
        respond.main()
        assert stub.posted() == []

    def test_thread_ts_is_preferred_over_ts(self, monkeypatch, configured) -> None:
        """스레드 안의 멘션은 부모 스레드에 답장한다 — 새 스레드를 만들지 않는다."""
        stub = _SlackStub(
            **{
                "conversations.history": {
                    "ok": True,
                    "messages": [_msg("<@U_BOT> 요약", ts="200.0", thread_ts="100.0")],
                }
            }
        )
        monkeypatch.setattr(respond, "slack_api", stub)
        respond.main()
        assert stub.posted()[0]["thread_ts"] == "100.0"

    def test_already_replied_thread_is_skipped(self, monkeypatch, configured) -> None:
        stub = _SlackStub(
            **{
                "conversations.history": {"ok": True, "messages": [_msg("<@U_BOT> 요약")]},
                "conversations.replies": {
                    "ok": True,
                    "messages": [_msg("<@U_BOT> 요약"), _msg("이미 답장", ts="100.2", user="U_BOT")],
                },
            }
        )
        monkeypatch.setattr(respond, "slack_api", stub)
        respond.main()
        assert stub.posted() == [], "중복 답장을 보냈다"

    def test_replies_lookup_failure_skips_the_message(self, monkeypatch, configured, caplog) -> None:
        stub = _SlackStub(
            **{
                "conversations.history": {"ok": True, "messages": [_msg("<@U_BOT> 요약")]},
                "conversations.replies": OSError("타임아웃"),
            }
        )
        monkeypatch.setattr(respond, "slack_api", stub)
        with caplog.at_level("WARNING"):
            assert respond.main() == 0
        assert stub.posted() == []
        assert any("conversations.replies request failed" in r.message for r in caplog.records)

    def test_post_failure_does_not_abort_the_run(self, monkeypatch, configured, caplog) -> None:
        stub = _SlackStub(
            **{
                "conversations.history": {
                    "ok": True,
                    "messages": [_msg("<@U_BOT> 요약", ts="100.0"), _msg("<@U_BOT> 요약", ts="200.0")],
                },
                "chat.postMessage": OSError("전송 실패"),
            }
        )
        monkeypatch.setattr(respond, "slack_api", stub)
        with caplog.at_level("WARNING"):
            assert respond.main() == 0
        assert len(stub.calls) >= 2
        assert any("chat.postMessage request failed" in r.message for r in caplog.records)

    def test_post_not_ok_is_logged_and_not_counted(self, monkeypatch, configured, caplog) -> None:
        stub = _SlackStub(
            **{
                "conversations.history": {
                    "ok": True,
                    "messages": [_msg("<@U_BOT> 요약", ts=f"{100 + i}.0") for i in range(5)],
                },
                "chat.postMessage": {"ok": False, "error": "channel_not_found"},
            }
        )
        monkeypatch.setattr(respond, "slack_api", stub)
        with caplog.at_level("WARNING"):
            respond.main()
        # 실패는 카운트되지 않으므로 상한에 걸리지 않고 5건 전부 시도한다.
        assert len(stub.posted()) == 5
        assert any("chat.postMessage failed" in r.message for r in caplog.records)

    def test_alias_routes_the_reply_body(self, monkeypatch, posts_dir) -> None:
        monkeypatch.setenv("SLACK_BOT_TOKEN", _DUMMY_TOKEN)
        monkeypatch.setenv("SLACK_CHANNEL_ID", _DUMMY_CHANNEL)
        monkeypatch.setenv("TARGET_CHANNEL_ALIAS", "security")
        stub = _SlackStub(**{"conversations.history": {"ok": True, "messages": [_msg("<@U_BOT> 확인")]}})
        monkeypatch.setattr(respond, "slack_api", stub)
        respond.main()
        assert stub.posted()[0]["text"].startswith("🛡️")

    def test_empty_reply_text_falls_back_to_default(self, monkeypatch, configured) -> None:
        """`build_reply_text` 가 빈 문자열을 내면 기본 본문으로 대체한다."""
        monkeypatch.setattr(respond, "build_reply_text", lambda alias, text: "" if text else "기본본문")
        stub = _SlackStub(**{"conversations.history": {"ok": True, "messages": [_msg("<@U_BOT> 요약")]}})
        monkeypatch.setattr(respond, "slack_api", stub)
        respond.main()
        assert stub.posted()[0]["text"] == "기본본문"

    def test_completion_is_logged_with_counts(self, monkeypatch, configured, caplog) -> None:
        stub = _SlackStub(**{"conversations.history": {"ok": True, "messages": [_msg("<@U_BOT> 요약")]}})
        monkeypatch.setattr(respond, "slack_api", stub)
        with caplog.at_level("INFO"):
            respond.main()
        assert any("alias=investing replies=1" in r.message for r in caplog.records)


class TestBuildSummaryTextMarketReportSlugFallback:
    def test_unparseable_market_report_slug_falls_back(self, posts_dir) -> None:
        """뉴스 요약과 시장 리포트는 슬러그 폴백을 각자 갖는다 — 둘 다 확인한다."""
        (posts_dir / "2026-08-27-daily-news-summary.md").write_text('---\ntitle: "N"\n---\n', encoding="utf-8")
        (posts_dir / "daily-market-report.md").write_text('---\ntitle: "M"\n---\n', encoding="utf-8")
        text = respond.build_summary_text()
        assert f"- 요약 링크: {respond.SITE_URL}/market-analysis/2026/08/27/daily-news-summary/" in text
        assert f"- 리포트 링크: {respond.SITE_URL}/" in text
