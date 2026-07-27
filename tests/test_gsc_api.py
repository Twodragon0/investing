"""tests/test_gsc_api.py — gsc_api 단위 테스트.

Google Search Console API CLI. ``_require_googleapi``의 ImportError 분기는
설치 여부에 의존하지 말고 ``sys.modules``에 ``None``을 심어 결정적으로
강제한다(설치 상태와 무관하게 재현 가능). 인증이 필요한 경로는
``_build_service``를 fake 서비스 객체로 교체해 네트워크 없이 검증한다.
"""

import json
import sys

import gsc_api as ga

_SITE = "https://investing.2twodragon.com"


class _Namespace:
    """argparse.Namespace 대용 — 필요한 속성만 최소로 구성."""

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def _clean_env(monkeypatch):
    monkeypatch.delenv("GSC_SITE_URL", raising=False)
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)


# ---------------------------------------------------------------------------
# _site_url
# ---------------------------------------------------------------------------


class TestSiteUrl:
    def test_explicit_site_arg(self, monkeypatch):
        _clean_env(monkeypatch)
        args = _Namespace(site=f"{_SITE}/foo")
        assert ga._site_url(args) == f"{_SITE}/foo/"

    def test_explicit_site_arg_trailing_slash_preserved(self, monkeypatch):
        _clean_env(monkeypatch)
        args = _Namespace(site=f"{_SITE}/")
        assert ga._site_url(args) == f"{_SITE}/"

    def test_env_var_fallback(self, monkeypatch):
        monkeypatch.setenv("GSC_SITE_URL", "https://example.com")
        args = _Namespace(site=None)
        assert ga._site_url(args) == "https://example.com/"

    def test_default_site(self, monkeypatch):
        _clean_env(monkeypatch)
        args = _Namespace(site=None)
        assert ga._site_url(args) == ga.DEFAULT_SITE_URL


# ---------------------------------------------------------------------------
# _emit
# ---------------------------------------------------------------------------


class TestEmit:
    def test_default_blank_line(self, capsys):
        ga._emit()
        assert capsys.readouterr().out == "\n"

    def test_writes_line_with_newline(self, capsys):
        ga._emit("hello")
        assert capsys.readouterr().out == "hello\n"


# ---------------------------------------------------------------------------
# _require_googleapi
# ---------------------------------------------------------------------------


class TestRequireGoogleapi:
    def test_missing_dependency_exits_2(self, monkeypatch):
        import pytest

        # Force the ImportError branch deterministically regardless of whether
        # google-api-python-client / google-auth happen to be installed in this
        # venv: a ``None`` entry in sys.modules makes the import machinery raise
        # ImportError even if the real package is importable.
        monkeypatch.setitem(sys.modules, "google.oauth2", None)
        monkeypatch.setitem(sys.modules, "googleapiclient.discovery", None)

        with pytest.raises(SystemExit) as exc_info:
            ga._require_googleapi()
        assert exc_info.value.code == 2


# ---------------------------------------------------------------------------
# _build_service — auth/env preconditions
# ---------------------------------------------------------------------------


class TestBuildService:
    def test_missing_env_exits_2(self, monkeypatch):
        _clean_env(monkeypatch)
        import pytest

        with pytest.raises(SystemExit) as exc_info:
            ga._build_service()
        assert exc_info.value.code == 2

    def test_missing_credentials_file_exits_2(self, monkeypatch, tmp_path):
        _clean_env(monkeypatch)
        monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(tmp_path / "gone.json"))
        import pytest

        with pytest.raises(SystemExit) as exc_info:
            ga._build_service()
        assert exc_info.value.code == 2


# ---------------------------------------------------------------------------
# cmd_submit_sitemap — --confirm gate (no _build_service mock needed for
# the without-confirm path since it returns before authenticating)
# ---------------------------------------------------------------------------


class TestCmdSubmitSitemap:
    def test_without_confirm_returns_1(self):
        args = _Namespace(confirm=False, feedpath=f"{_SITE}/sitemap.xml", site=None)
        assert ga.cmd_submit_sitemap(args) == 1

    def test_with_confirm_calls_service(self, monkeypatch):
        calls = {}

        class _FakeSubmitCall:
            def execute(self):
                calls["executed"] = True

        class _FakeSitemaps:
            def submit(self, siteUrl, feedpath):
                calls["siteUrl"] = siteUrl
                calls["feedpath"] = feedpath
                return _FakeSubmitCall()

        class _FakeService:
            def sitemaps(self):
                return _FakeSitemaps()

        monkeypatch.setattr(ga, "_build_service", lambda: _FakeService())
        _clean_env(monkeypatch)
        args = _Namespace(confirm=True, feedpath=f"{_SITE}/sitemap.xml", site=None)
        rc = ga.cmd_submit_sitemap(args)
        assert rc == 0
        assert calls["executed"] is True
        assert calls["feedpath"] == f"{_SITE}/sitemap.xml"


# ---------------------------------------------------------------------------
# cmd_sitemap_status
# ---------------------------------------------------------------------------


class _ExecuteWrapper:
    def __init__(self, payload):
        self._payload = payload

    def execute(self):
        return self._payload


class TestCmdSitemapStatus:
    def test_empty_sitemaps(self, monkeypatch, capsys):
        class _FakeSitemaps:
            def list(self, siteUrl):
                return _ExecuteWrapper({"sitemap": []})

        class _FakeService:
            def sitemaps(self):
                return _FakeSitemaps()

        monkeypatch.setattr(ga, "_build_service", lambda: _FakeService())
        _clean_env(monkeypatch)
        args = _Namespace(site=None)
        rc = ga.cmd_sitemap_status(args)
        assert rc == 0
        out = capsys.readouterr().out
        assert "No sitemaps registered" in out

    def test_populated_with_missing_keys(self, monkeypatch, capsys):
        payload = {
            "sitemap": [
                {
                    "path": f"{_SITE}/sitemap.xml",
                    "contents": [{"type": "web", "submitted": "10", "indexed": "8"}],
                },
                {
                    "path": f"{_SITE}/other.xml",
                    "type": "sitemap",
                    "lastSubmitted": "2026-01-01",
                    "isPending": False,
                    "errors": 0,
                    "warnings": 1,
                },
            ]
        }

        class _FakeSitemaps:
            def list(self, siteUrl):
                return _ExecuteWrapper(payload)

        class _FakeService:
            def sitemaps(self):
                return _FakeSitemaps()

        monkeypatch.setattr(ga, "_build_service", lambda: _FakeService())
        _clean_env(monkeypatch)
        args = _Namespace(site=None)
        rc = ga.cmd_sitemap_status(args)
        assert rc == 0
        out = capsys.readouterr().out
        assert "(unknown)" in out  # missing 'type' on first entry
        assert "(none)" in out  # missing 'lastSubmitted' on first entry
        assert "web: submitted=10 indexed=8" in out
        assert "2026-01-01" in out


# ---------------------------------------------------------------------------
# cmd_inspect
# ---------------------------------------------------------------------------


class TestCmdInspect:
    def test_emits_formatted_json(self, monkeypatch, capsys):
        resp = {"inspectionResult": {"indexStatusResult": {"verdict": "PASS"}}}

        class _FakeInspectCall:
            def execute(self):
                return resp

        class _FakeIndex:
            def inspect(self, body):
                assert body["inspectionUrl"] == f"{_SITE}/foo/"
                return _FakeInspectCall()

        class _FakeUrlInspection:
            def index(self):
                return _FakeIndex()

        class _FakeService:
            def urlInspection(self):
                return _FakeUrlInspection()

        monkeypatch.setattr(ga, "_build_service", lambda: _FakeService())
        _clean_env(monkeypatch)
        args = _Namespace(site=None, url=f"{_SITE}/foo/")
        rc = ga.cmd_inspect(args)
        assert rc == 0
        out = capsys.readouterr().out
        assert json.loads(out) == resp


# ---------------------------------------------------------------------------
# cmd_analytics
# ---------------------------------------------------------------------------


class TestCmdAnalytics:
    def test_no_rows(self, monkeypatch, capsys):
        class _FakeSearchAnalytics:
            def query(self, siteUrl, body):
                return _ExecuteWrapper({"rows": []})

        class _FakeService:
            def searchanalytics(self):
                return _FakeSearchAnalytics()

        monkeypatch.setattr(ga, "_build_service", lambda: _FakeService())
        _clean_env(monkeypatch)
        args = _Namespace(site=None, days=7, dimension="query", row_limit=25)
        rc = ga.cmd_analytics(args)
        assert rc == 0
        assert "No data for" in capsys.readouterr().out

    def test_populated_rows_formatting(self, monkeypatch, capsys):
        payload = {
            "rows": [
                {"keys": ["bitcoin news"], "clicks": 12, "impressions": 340, "ctr": 0.0353, "position": 4.2},
            ]
        }

        class _FakeSearchAnalytics:
            def query(self, siteUrl, body):
                return _ExecuteWrapper(payload)

        class _FakeService:
            def searchanalytics(self):
                return _FakeSearchAnalytics()

        monkeypatch.setattr(ga, "_build_service", lambda: _FakeService())
        _clean_env(monkeypatch)
        args = _Namespace(site=None, days=7, dimension="query", row_limit=25)
        rc = ga.cmd_analytics(args)
        assert rc == 0
        out = capsys.readouterr().out
        assert "Top 1 querys" in out
        assert "bitcoin news" in out
        assert "3.53%" in out


# ---------------------------------------------------------------------------
# main — dispatch wiring
# ---------------------------------------------------------------------------


class TestMain:
    def test_dispatches_sitemap_status(self, monkeypatch):
        called = {}

        def _fake(args):
            called["ok"] = "sitemap-status"
            return 0

        monkeypatch.setattr(ga, "cmd_sitemap_status", _fake)
        rc = ga.main(["sitemap-status"])
        assert rc == 0
        assert called["ok"] == "sitemap-status"

    def test_dispatches_inspect(self, monkeypatch):
        called = {}

        def _fake(args):
            called["url"] = args.url
            return 0

        monkeypatch.setattr(ga, "cmd_inspect", _fake)
        rc = ga.main(["inspect", f"{_SITE}/foo/"])
        assert rc == 0
        assert called["url"] == f"{_SITE}/foo/"

    def test_dispatches_analytics(self, monkeypatch):
        called = {}

        def _fake(args):
            called["days"] = args.days
            called["dimension"] = args.dimension
            called["row_limit"] = args.row_limit
            return 0

        monkeypatch.setattr(ga, "cmd_analytics", _fake)
        rc = ga.main(["analytics", "--days", "3", "--dimension", "page", "--row-limit", "10"])
        assert rc == 0
        assert called == {"days": 3, "dimension": "page", "row_limit": 10}

    def test_dispatches_submit_sitemap(self, monkeypatch):
        called = {}

        def _fake(args):
            called["feedpath"] = args.feedpath
            called["confirm"] = args.confirm
            return 0

        monkeypatch.setattr(ga, "cmd_submit_sitemap", _fake)
        rc = ga.main(["submit-sitemap", f"{_SITE}/sitemap.xml", "--confirm"])
        assert rc == 0
        assert called == {"feedpath": f"{_SITE}/sitemap.xml", "confirm": True}
