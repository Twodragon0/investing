"""tests/test_gsc_index_audit.py — gsc_index_audit 단위 테스트.

GSC URL Inspection API 결과를 버킷팅해 Markdown 리포트로 만드는 CLI.
``_require_googleapi``의 성공/실패 분기는 ``sys.modules`` 조작으로 설치 여부와
무관하게 결정적으로 강제하고, ``_inspect_urls``는 fake service 객체로
성공/429 백오프/연속 실패 컷오프/max-per-state 캡을 검증한다.
``LOCAL_SITEMAP``은 문자열 경로 기반 monkeypatch로 tmp_path 로 리다이렉트해
프로덕션 경로 상수를 테스트에 끌어들이지 않는다.
"""

import sys
import types
import urllib.request
import xml.etree.ElementTree as ET

import gsc_index_audit as gia
import pytest

_SITE = "https://investing.2twodragon.com"


def _resp(coverage_state: str, **overrides) -> dict:
    """URL Inspection API 응답 payload를 최소 형태로 생성."""
    isr = {
        "coverageState": coverage_state,
        "verdict": overrides.get("verdict", "NEUTRAL"),
        "lastCrawlTime": overrides.get("lastCrawlTime", ""),
        "googleCanonical": overrides.get("googleCanonical", ""),
        "robotsTxtState": overrides.get("robotsTxtState", ""),
        "indexingState": overrides.get("indexingState", ""),
    }
    return {"inspectionResult": {"indexStatusResult": isr}}


class _ScriptedService:
    """urlInspection().index().inspect(body=...).execute() 체인을 흉내내는 fake.

    ``script`` 에 순서대로 나열된 항목을 ``execute()`` 호출마다 하나씩 소비한다.
    ``dict`` 는 정상 응답으로 반환하고, ``Exception`` 인스턴스는 그대로 raise 한다.
    """

    def __init__(self, script: list):
        self._script = list(script)
        self.call_count = 0

    def urlInspection(self):
        return self

    def index(self):
        return self

    def inspect(self, body):
        assert "inspectionUrl" in body
        return self

    def execute(self):
        effect = self._script[self.call_count]
        self.call_count += 1
        if isinstance(effect, Exception):
            raise effect
        return effect


# ---------------------------------------------------------------------------
# 상수 고정 (회귀 감지용 pin)
# ---------------------------------------------------------------------------


class TestConstants:
    def test_bucket_order(self):
        assert gia._BUCKET_ORDER == [
            "NOT_FOUND_404",
            "DISCOVERED_NOT_INDEXED",
            "CRAWLED_NOT_INDEXED",
            "REDIRECT",
            "BLOCKED",
            "OTHER",
            "INDEXED",
        ]

    def test_bucket_labels_cover_every_order_entry(self):
        for bucket in gia._BUCKET_ORDER:
            assert bucket in gia._BUCKET_LABELS

    def test_max_consecutive_failures(self):
        assert gia._MAX_CONSECUTIVE_FAILURES == 50

    def test_quota_sleep(self):
        assert gia._QUOTA_SLEEP == 60.0


# ---------------------------------------------------------------------------
# _require_googleapi
# ---------------------------------------------------------------------------


class TestRequireGoogleapi:
    def test_missing_dependency_exits_2(self, monkeypatch):
        # 설치 여부와 무관하게 ImportError 분기를 강제: sys.modules 에 None 을
        # 심으면 import 머신이 실제 패키지 존재 여부와 상관없이 ImportError 를 낸다.
        monkeypatch.setitem(sys.modules, "google.oauth2", None)
        monkeypatch.setitem(sys.modules, "googleapiclient.discovery", None)

        with pytest.raises(SystemExit) as exc_info:
            gia._require_googleapi()
        assert exc_info.value.code == 2

    def test_present_returns_service_account_and_build(self, monkeypatch):
        fake_oauth2 = types.ModuleType("google.oauth2")
        fake_oauth2.service_account = object()
        fake_discovery = types.ModuleType("googleapiclient.discovery")
        fake_discovery.build = lambda *a, **kw: "sentinel-service"

        monkeypatch.setitem(sys.modules, "google.oauth2", fake_oauth2)
        monkeypatch.setitem(sys.modules, "googleapiclient.discovery", fake_discovery)

        service_account, build = gia._require_googleapi()
        assert service_account is fake_oauth2.service_account
        assert build is fake_discovery.build


# ---------------------------------------------------------------------------
# _build_service
# ---------------------------------------------------------------------------


class TestBuildService:
    def _clean_env(self, monkeypatch):
        monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)

    def test_missing_env_exits_2(self, monkeypatch):
        self._clean_env(monkeypatch)
        with pytest.raises(SystemExit) as exc_info:
            gia._build_service()
        assert exc_info.value.code == 2

    def test_missing_credentials_file_exits_2(self, monkeypatch, tmp_path):
        self._clean_env(monkeypatch)
        monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(tmp_path / "gone.json"))
        with pytest.raises(SystemExit) as exc_info:
            gia._build_service()
        assert exc_info.value.code == 2

    def test_success_builds_with_credentials_and_scopes(self, monkeypatch, tmp_path):
        self._clean_env(monkeypatch)
        cred_file = tmp_path / "creds.json"
        cred_file.write_text("{}", encoding="utf-8")
        monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(cred_file))

        calls = {}

        class _FakeCredentials:
            @staticmethod
            def from_service_account_file(path, scopes):
                calls["path"] = path
                calls["scopes"] = scopes
                return "creds-object"

        class _FakeServiceAccountModule:
            Credentials = _FakeCredentials

        def _fake_build(name, version, credentials, cache_discovery):
            calls["build_args"] = (name, version, credentials, cache_discovery)
            return "built-service"

        monkeypatch.setattr(gia, "_require_googleapi", lambda: (_FakeServiceAccountModule, _fake_build))

        result = gia._build_service()

        assert result == "built-service"
        assert calls["path"] == str(cred_file)
        assert calls["scopes"] == ["https://www.googleapis.com/auth/webmasters"]
        assert calls["build_args"] == ("searchconsole", "v1", "creds-object", False)


# ---------------------------------------------------------------------------
# _load_sitemap_urls
# ---------------------------------------------------------------------------


def _write_sitemap(path, urls, with_namespace=True):
    if with_namespace:
        body = "".join(f"<url><loc>{u}</loc></url>" for u in urls)
        xml = f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}</urlset>'
    else:
        body = "".join(f"<url><loc>{u}</loc></url>" for u in urls)
        xml = f"<urlset>{body}</urlset>"
    path.write_text(xml, encoding="utf-8")


class TestLoadSitemapUrls:
    def test_local_file_with_namespace(self, tmp_path, monkeypatch):
        local = tmp_path / "sitemap.xml"
        _write_sitemap(local, [f"{_SITE}/a/", f"{_SITE}/b/"], with_namespace=True)
        monkeypatch.setattr("gsc_index_audit.LOCAL_SITEMAP", local)

        urls = gia._load_sitemap_urls()
        assert urls == [f"{_SITE}/a/", f"{_SITE}/b/"]

    def test_local_file_without_namespace_falls_back_to_unqualified_loc(self, tmp_path, monkeypatch):
        local = tmp_path / "sitemap.xml"
        _write_sitemap(local, [f"{_SITE}/c/"], with_namespace=False)
        monkeypatch.setattr("gsc_index_audit.LOCAL_SITEMAP", local)

        urls = gia._load_sitemap_urls()
        assert urls == [f"{_SITE}/c/"]

    def test_local_file_empty_returns_empty_list(self, tmp_path, monkeypatch):
        local = tmp_path / "sitemap.xml"
        _write_sitemap(local, [], with_namespace=True)
        monkeypatch.setattr("gsc_index_audit.LOCAL_SITEMAP", local)

        assert gia._load_sitemap_urls() == []

    def test_missing_local_file_downloads_from_live_url(self, tmp_path, monkeypatch):
        missing = tmp_path / "no-such-sitemap.xml"
        monkeypatch.setattr("gsc_index_audit.LOCAL_SITEMAP", missing)

        root = ET.Element("urlset")
        loc = ET.SubElement(root, "loc")
        loc.text = f"{_SITE}/downloaded/"
        content = ET.tostring(root)

        class _FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self):
                return content

        def _fake_urlopen(url, timeout):
            assert url == gia.SITEMAP_URL
            return _FakeResponse()

        monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)

        urls = gia._load_sitemap_urls()
        assert urls == [f"{_SITE}/downloaded/"]

    def test_download_failure_exits_1(self, tmp_path, monkeypatch):
        missing = tmp_path / "no-such-sitemap.xml"
        monkeypatch.setattr("gsc_index_audit.LOCAL_SITEMAP", missing)

        def _fake_urlopen(url, timeout):
            raise OSError("network unreachable")

        monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)

        with pytest.raises(SystemExit) as exc_info:
            gia._load_sitemap_urls()
        assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# _extract_category
# ---------------------------------------------------------------------------


class TestExtractCategory:
    def test_root_url_with_trailing_slash(self):
        assert gia._extract_category(f"{_SITE}/") == "(root)"

    def test_root_url_without_trailing_slash(self):
        assert gia._extract_category(_SITE) == "(root)"

    def test_single_segment_category(self):
        assert gia._extract_category(f"{_SITE}/crypto-news/") == "crypto-news"

    def test_nested_path_uses_first_segment(self):
        assert gia._extract_category(f"{_SITE}/crypto-news/some-post/") == "crypto-news"

    def test_no_trailing_slash_still_extracts_first_segment(self):
        assert gia._extract_category(f"{_SITE}/about") == "about"


# ---------------------------------------------------------------------------
# _classify
# ---------------------------------------------------------------------------


class TestClassify:
    @pytest.mark.parametrize(
        ("coverage_state", "expected_bucket"),
        [
            ("Submitted and indexed", "INDEXED"),
            ("Indexed, not submitted in sitemap", "INDEXED"),
            ("Discovered - currently not indexed", "DISCOVERED_NOT_INDEXED"),
            ("Crawled - currently not indexed", "CRAWLED_NOT_INDEXED"),
            ("Not found (404)", "NOT_FOUND_404"),
            ("Page with redirect", "REDIRECT"),
            ("Blocked by robots.txt", "BLOCKED"),
            ("Blocked due to access forbidden (403)", "BLOCKED"),
        ],
    )
    def test_known_states(self, coverage_state, expected_bucket):
        assert gia._classify(coverage_state) == expected_bucket

    def test_unknown_state_maps_to_other(self):
        assert gia._classify("Some new state Google invented") == "OTHER"

    def test_empty_state_maps_to_other(self):
        assert gia._classify("") == "OTHER"


# ---------------------------------------------------------------------------
# _inspect_urls
# ---------------------------------------------------------------------------


class TestInspectUrls:
    def test_success_buckets_by_coverage_state(self):
        service = _ScriptedService([_resp("Submitted and indexed")])
        buckets = gia._inspect_urls(service, [f"{_SITE}/a/"], f"{_SITE}/", 0.0, 100)

        assert list(buckets.keys()) == ["INDEXED"]
        assert buckets["INDEXED"][0]["url"] == f"{_SITE}/a/"
        assert buckets["INDEXED"][0]["coverageState"] == "Submitted and indexed"

    def test_quota_hit_backs_off_and_retries_successfully(self, sleep_calls):
        service = _ScriptedService(
            [
                Exception("429 Too Many Requests"),
                _resp("Submitted and indexed"),
            ]
        )
        buckets = gia._inspect_urls(service, [f"{_SITE}/a/"], f"{_SITE}/", 0.0, 100)

        assert sleep_calls.calls == [60.0]
        assert buckets["INDEXED"][0]["url"] == f"{_SITE}/a/"
        assert service.call_count == 2

    def test_quota_hit_retry_also_fails_counts_as_one_failure(self, sleep_calls):
        service = _ScriptedService(
            [
                Exception("429 Too Many Requests"),
                Exception("still failing"),
            ]
        )
        buckets = gia._inspect_urls(service, [f"{_SITE}/a/"], f"{_SITE}/", 0.0, 100)

        assert sleep_calls.calls == [60.0]
        assert buckets == {}

    def test_non_quota_exception_continues_to_next_url(self):
        service = _ScriptedService(
            [
                Exception("boom"),
                _resp("Submitted and indexed"),
            ]
        )
        buckets = gia._inspect_urls(service, [f"{_SITE}/bad/", f"{_SITE}/good/"], f"{_SITE}/", 0.0, 100)

        assert buckets["INDEXED"][0]["url"] == f"{_SITE}/good/"
        assert sum(len(v) for v in buckets.values()) == 1

    def test_consecutive_failure_cutoff_breaks_before_exhausting_urls(self):
        # 정확히 50건의 실패만 소비되고 나머지 10개 URL은 손대지 않아야 한다.
        # 컷오프가 없다면 51번째 execute() 호출에서 스크립트 소진으로
        # IndexError 가 나 테스트가 실패하므로, 이 자체가 회귀 감지 장치다.
        script = [Exception("boom")] * 50
        urls = [f"{_SITE}/{i}/" for i in range(60)]
        service = _ScriptedService(script)

        buckets = gia._inspect_urls(service, urls, f"{_SITE}/", 0.0, 100)

        assert buckets == {}
        assert service.call_count == 50

    def test_max_per_state_cap_limits_stored_entries_but_inspects_all(self):
        script = [_resp("Submitted and indexed") for _ in range(5)]
        urls = [f"{_SITE}/{i}/" for i in range(5)]
        service = _ScriptedService(script)

        buckets = gia._inspect_urls(service, urls, f"{_SITE}/", 0.0, 2)

        assert len(buckets["INDEXED"]) == 2
        assert service.call_count == 5

    def test_max_per_state_zero_means_unlimited(self):
        script = [_resp("Submitted and indexed") for _ in range(5)]
        urls = [f"{_SITE}/{i}/" for i in range(5)]
        service = _ScriptedService(script)

        buckets = gia._inspect_urls(service, urls, f"{_SITE}/", 0.0, 0)

        assert len(buckets["INDEXED"]) == 5

    def test_unmapped_coverage_state_lands_in_other_bucket(self):
        service = _ScriptedService([_resp("A brand new coverage state")])
        buckets = gia._inspect_urls(service, [f"{_SITE}/a/"], f"{_SITE}/", 0.0, 100)

        assert buckets["OTHER"][0]["coverageState"] == "A brand new coverage state"


# ---------------------------------------------------------------------------
# _build_report
# ---------------------------------------------------------------------------


class TestBuildReport:
    def test_full_report_sections_and_cap_note(self):
        buckets = {
            "NOT_FOUND_404": [
                {
                    "url": f"{_SITE}/gone/",
                    "coverageState": "Not found (404)",
                    "verdict": "FAIL",
                    "lastCrawlTime": "",
                    "googleCanonical": "",
                    "robotsTxtState": "",
                    "indexingState": "",
                }
            ],
            "INDEXED": [
                {
                    "url": f"{_SITE}/crypto-news/a/",
                    "coverageState": "Submitted and indexed",
                    "verdict": "PASS",
                    "lastCrawlTime": "2026-08-01T00:00:00Z",
                    "googleCanonical": f"{_SITE}/crypto-news/a/",
                    "robotsTxtState": "ALLOWED",
                    "indexingState": "INDEXING_ALLOWED",
                },
                {
                    "url": f"{_SITE}/crypto-news/b/",
                    "coverageState": "Submitted and indexed",
                    "verdict": "PASS",
                    "lastCrawlTime": "2026-08-02T00:00:00Z",
                    "googleCanonical": "",
                    "robotsTxtState": "ALLOWED",
                    "indexingState": "INDEXING_ALLOWED",
                },
            ],
        }
        all_urls = [f"{_SITE}/gone/", f"{_SITE}/crypto-news/a/", f"{_SITE}/crypto-news/b/"]

        report = gia._build_report(
            buckets=buckets,
            all_urls=all_urls,
            inspected_count=3,
            max_per_state=2,
            audit_date="2026-08-25",
        )

        assert "# GSC Index Audit — 2026-08-25" in report
        assert "Inspected **3** of **3** sitemap URLs" in report
        assert "| 404 Not Found | 1 | 33.3% |" in report
        assert "| Indexed | 2+ | 66.7% |" in report
        assert "| **Total stored** | 3 | 100% |" in report
        assert "| crypto-news | 2 | 2 | 0 | 0 | 0 | 0 |" in report
        assert "| gone | 1 | 0 | 0 | 0 | 1 | 0 |" in report
        assert "## 404 URLs" in report
        assert f"`{_SITE}/gone/`" in report
        # INDEXED 는 detail_buckets 목록에 없으므로 상세 섹션이 없어야 한다.
        assert "## Indexed" not in report
        assert "**Fix 1 404s**" in report
        assert "Discovered-NI" not in report
        assert "Crawled-NI" not in report
        assert "Re-run this audit" in report

    def test_empty_buckets_avoids_zero_division_and_skips_detail_sections(self):
        report = gia._build_report(
            buckets={},
            all_urls=[],
            inspected_count=0,
            max_per_state=100,
            audit_date="2026-08-25",
        )

        assert "Inspected **0** of **0** sitemap URLs" in report
        assert "| 404 Not Found | 0 | 0.0% |" in report
        assert "| **Total stored** | 0 | 100% |" in report
        assert "## 404 URLs" not in report
        assert "**Fix" not in report
        assert "Re-run this audit" in report

    def test_canonical_note_only_shown_when_canonical_differs_from_url(self):
        buckets = {
            "REDIRECT": [
                {
                    "url": f"{_SITE}/old/",
                    "coverageState": "Page with redirect",
                    "verdict": "NEUTRAL",
                    "lastCrawlTime": "",
                    "googleCanonical": f"{_SITE}/new/",
                    "robotsTxtState": "",
                    "indexingState": "",
                }
            ]
        }
        report = gia._build_report(
            buckets=buckets,
            all_urls=[f"{_SITE}/old/"],
            inspected_count=1,
            max_per_state=100,
            audit_date="2026-08-25",
        )
        assert f"→ canonical: {_SITE}/new/" in report
        assert "never crawled" in report


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


class TestMain:
    def test_requires_source_group(self):
        with pytest.raises(SystemExit) as exc_info:
            gia.main([])
        assert exc_info.value.code == 2

    def test_from_sitemap_and_urls_are_mutually_exclusive(self):
        with pytest.raises(SystemExit) as exc_info:
            gia.main(["--from-sitemap", "--urls", f"{_SITE}/a/"])
        assert exc_info.value.code == 2

    def test_no_urls_returns_1(self, tmp_path, monkeypatch):
        monkeypatch.setattr(gia, "_load_sitemap_urls", list)
        rc = gia.main(["--from-sitemap", "--output", str(tmp_path / "out.md")])
        assert rc == 1

    def test_urls_mode_full_flow_writes_report(self, tmp_path, monkeypatch, capsys):
        monkeypatch.delenv("GSC_SITE_URL", raising=False)
        captured = {}

        monkeypatch.setattr(gia, "_build_service", lambda: "fake-service")

        def _fake_inspect_urls(service, urls, site_url, sleep_s, max_per_state):
            captured["service"] = service
            captured["urls"] = urls
            captured["site_url"] = site_url
            captured["sleep_s"] = sleep_s
            captured["max_per_state"] = max_per_state
            return {
                "INDEXED": [
                    {
                        "url": urls[0],
                        "coverageState": "Submitted and indexed",
                        "verdict": "PASS",
                        "lastCrawlTime": "",
                        "googleCanonical": "",
                        "robotsTxtState": "",
                        "indexingState": "",
                    }
                ]
            }

        monkeypatch.setattr(gia, "_inspect_urls", _fake_inspect_urls)

        output = tmp_path / "audit.md"
        rc = gia.main(
            [
                "--urls",
                f"{_SITE}/a/",
                f"{_SITE}/b/",
                "--output",
                str(output),
                "--site",
                _SITE,
                "--limit",
                "1",
                "--sleep",
                "0.0",
                "--max-per-state",
                "5",
            ]
        )

        assert rc == 0
        # --limit 1 이 URL 목록에 적용되어야 한다.
        assert captured["urls"] == [f"{_SITE}/a/"]
        # --site 에 슬래시가 없으면 자동으로 붙는다.
        assert captured["site_url"] == f"{_SITE}/"
        assert captured["sleep_s"] == 0.0
        assert captured["max_per_state"] == 5
        assert captured["service"] == "fake-service"

        assert output.exists()
        content = output.read_text(encoding="utf-8")
        assert "# GSC Index Audit" in content

        out = capsys.readouterr().out
        assert "Audit complete — 1 URLs inspected" in out
        assert f"Report: {output}" in out

    def test_default_site_used_when_no_site_arg_or_env(self, tmp_path, monkeypatch):
        monkeypatch.delenv("GSC_SITE_URL", raising=False)
        captured = {}

        monkeypatch.setattr(gia, "_build_service", lambda: "fake-service")

        def _fake_inspect_urls(service, urls, site_url, sleep_s, max_per_state):
            captured["site_url"] = site_url
            return {}

        monkeypatch.setattr(gia, "_inspect_urls", _fake_inspect_urls)

        output = tmp_path / "audit.md"
        rc = gia.main(["--urls", f"{_SITE}/a/", "--output", str(output)])

        assert rc == 0
        assert captured["site_url"] == gia.DEFAULT_SITE_URL

    def test_from_sitemap_wires_loaded_urls_into_inspection(self, tmp_path, monkeypatch):
        local = tmp_path / "sitemap.xml"
        _write_sitemap(local, [f"{_SITE}/x/", f"{_SITE}/y/"], with_namespace=True)
        monkeypatch.setattr("gsc_index_audit.LOCAL_SITEMAP", local)
        monkeypatch.setattr(gia, "_build_service", lambda: "fake-service")

        captured = {}

        def _fake_inspect_urls(service, urls, site_url, sleep_s, max_per_state):
            captured["urls"] = urls
            return {}

        monkeypatch.setattr(gia, "_inspect_urls", _fake_inspect_urls)

        output = tmp_path / "audit.md"
        rc = gia.main(["--from-sitemap", "--output", str(output)])

        assert rc == 0
        assert captured["urls"] == [f"{_SITE}/x/", f"{_SITE}/y/"]
