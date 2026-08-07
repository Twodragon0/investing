"""tests/test_indexnow_submit.py — indexnow_submit 단위 테스트.

IndexNow URL 제출 도구. 실제 네트워크 호출(``_submit_batch``)과 git 서브
프로세스(``urls_from_changed_posts``)는 항상 모킹한다. sitemap 파싱은
로컬 파일 경로 분기만 검증하고, https 스킴 분기(실 urllib 경로)는
의도적으로 건드리지 않는다.
"""

import subprocess
import sys

import indexnow_submit as idx

_HOST = idx.HOST


def _clean_env(monkeypatch):
    monkeypatch.delenv("INDEXNOW_KEY", raising=False)


class _Namespace:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


# ---------------------------------------------------------------------------
# _get_key
# ---------------------------------------------------------------------------


class TestGetKey:
    def test_cli_flag_wins(self, monkeypatch):
        _clean_env(monkeypatch)
        monkeypatch.setenv("INDEXNOW_KEY", "envkey")
        args = _Namespace(key="clikey")
        assert idx._get_key(args) == "clikey"

    def test_env_var_fallback(self, monkeypatch):
        monkeypatch.setenv("INDEXNOW_KEY", "envkey")
        args = _Namespace(key="")
        assert idx._get_key(args) == "envkey"

    def test_default_key(self, monkeypatch):
        _clean_env(monkeypatch)
        args = _Namespace(key="")
        assert idx._get_key(args) == idx._DEFAULT_KEY


# ---------------------------------------------------------------------------
# _validate_url
# ---------------------------------------------------------------------------


class TestValidateUrl:
    def test_https_host_ok(self):
        assert idx._validate_url(f"https://{_HOST}/foo/") is True

    def test_http_host_ok(self):
        assert idx._validate_url(f"http://{_HOST}/foo/") is True

    def test_other_host_rejected(self):
        assert idx._validate_url("https://example.com/foo/") is False

    def test_host_substring_not_prefix_rejected(self):
        assert idx._validate_url(f"https://evil-{_HOST}/foo/") is False


# ---------------------------------------------------------------------------
# _batch
# ---------------------------------------------------------------------------


class TestBatch:
    def test_exact_multiple(self):
        chunks = list(idx._batch([1, 2, 3, 4], 2))
        assert chunks == [[1, 2], [3, 4]]

    def test_remainder(self):
        chunks = list(idx._batch([1, 2, 3], 2))
        assert chunks == [[1, 2], [3]]

    def test_empty(self):
        assert list(idx._batch([], 2)) == []


# ---------------------------------------------------------------------------
# _permalink_from_post
# ---------------------------------------------------------------------------


class TestPermalinkFromPost:
    def test_explicit_permalink(self, tmp_path):
        p = tmp_path / "2026-07-27-daily-social-media-digest.md"
        p.write_text(
            '---\ntitle: "test"\npermalink: "/social-media/2026/07/27/daily-social-media-digest/"\n---\nbody',
            encoding="utf-8",
        )
        assert idx._permalink_from_post(p) == f"https://{_HOST}/social-media/2026/07/27/daily-social-media-digest/"

    def test_explicit_permalink_normalizes_trailing_slash(self, tmp_path):
        p = tmp_path / "2026-07-27-foo.md"
        p.write_text('---\npermalink: "/foo/bar"\n---\nbody', encoding="utf-8")
        assert idx._permalink_from_post(p) == f"https://{_HOST}/foo/bar/"

    def test_category_fallback(self, tmp_path):
        p = tmp_path / "2026-07-27-crypto-roundup.md"
        p.write_text("---\ncategories: [crypto-news]\n---\nbody", encoding="utf-8")
        assert idx._permalink_from_post(p) == f"https://{_HOST}/crypto-news/2026/07/27/crypto-roundup/"

    def test_no_categories_defaults_to_news(self, tmp_path):
        p = tmp_path / "2026-07-27-plain-post.md"
        p.write_text("---\ntitle: no categories here\n---\nbody", encoding="utf-8")
        assert idx._permalink_from_post(p) == f"https://{_HOST}/news/2026/07/27/plain-post/"

    def test_no_front_matter_falls_back_to_filename(self, tmp_path):
        p = tmp_path / "2026-07-27-no-frontmatter.md"
        p.write_text("just a body, no front matter", encoding="utf-8")
        assert idx._permalink_from_post(p) == f"https://{_HOST}/news/2026/07/27/no-frontmatter/"

    def test_malformed_filename_returns_none(self, tmp_path):
        p = tmp_path / "not-a-dated-post.md"
        p.write_text("---\ntitle: x\n---\nbody", encoding="utf-8")
        assert idx._permalink_from_post(p) is None

    def test_unreadable_file_returns_none(self, tmp_path):
        missing = tmp_path / "2026-07-27-gone.md"
        assert idx._permalink_from_post(missing) is None


# ---------------------------------------------------------------------------
# urls_from_recent_posts
# ---------------------------------------------------------------------------


class TestUrlsFromRecentPosts:
    def test_returns_newest_n_sorted_desc(self, tmp_path):
        for name in [
            "2026-07-25-a.md",
            "2026-07-26-b.md",
            "2026-07-27-c.md",
        ]:
            (tmp_path / name).write_text("---\ncategories: [news]\n---\nbody", encoding="utf-8")
        urls = idx.urls_from_recent_posts(2, tmp_path)
        assert urls == [
            f"https://{_HOST}/news/2026/07/27/c/",
            f"https://{_HOST}/news/2026/07/26/b/",
        ]

    def test_empty_dir_returns_empty(self, tmp_path):
        assert idx.urls_from_recent_posts(5, tmp_path) == []

    def test_skips_undecodable_posts(self, tmp_path):
        (tmp_path / "not-dated.md").write_text("---\n---\nbody", encoding="utf-8")
        assert idx.urls_from_recent_posts(5, tmp_path) == []


# ---------------------------------------------------------------------------
# urls_from_sitemap — LOCAL FILE branch only
# ---------------------------------------------------------------------------


class TestUrlsFromSitemapLocal:
    def test_namespaced_locs(self, tmp_path):
        sm = tmp_path / "sitemap.xml"
        sm.write_text(
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            f"<url><loc>https://{_HOST}/a/</loc></url>"
            f"<url><loc>https://{_HOST}/b/</loc></url>"
            "</urlset>",
            encoding="utf-8",
        )
        urls = idx.urls_from_sitemap(str(sm))
        assert urls == [f"https://{_HOST}/a/", f"https://{_HOST}/b/"]

    def test_non_namespaced_locs(self, tmp_path):
        sm = tmp_path / "sitemap.xml"
        sm.write_text(f"<urlset><url><loc>https://{_HOST}/c/</loc></url></urlset>", encoding="utf-8")
        assert idx.urls_from_sitemap(str(sm)) == [f"https://{_HOST}/c/"]

    def test_malformed_xml_returns_empty(self, tmp_path):
        sm = tmp_path / "sitemap.xml"
        sm.write_text("<urlset><url><loc>not closed", encoding="utf-8")
        assert idx.urls_from_sitemap(str(sm)) == []

    def test_missing_file_returns_empty(self, tmp_path):
        assert idx.urls_from_sitemap(str(tmp_path / "gone.xml")) == []


# ---------------------------------------------------------------------------
# urls_from_changed_posts — subprocess.run mocked, git never invoked
# ---------------------------------------------------------------------------


class _FakeCompletedProcess:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class TestUrlsFromChangedPosts:
    def test_normal_diff(self, tmp_path, monkeypatch):
        posts_dir = tmp_path / "_posts"
        posts_dir.mkdir()
        post = posts_dir / "2026-07-27-changed.md"
        post.write_text("---\ncategories: [news]\n---\nbody", encoding="utf-8")

        def _fake_run(cmd, capture_output, text, timeout):
            assert cmd[:2] == ["git", "diff"]
            return _FakeCompletedProcess(returncode=0, stdout="_posts/2026-07-27-changed.md\n")

        monkeypatch.setattr(subprocess, "run", _fake_run)
        urls = idx.urls_from_changed_posts("HEAD~1", posts_dir)
        assert urls == [f"https://{_HOST}/news/2026/07/27/changed/"]

    def test_non_md_lines_skipped(self, tmp_path, monkeypatch):
        posts_dir = tmp_path / "_posts"
        posts_dir.mkdir()

        def _fake_run(cmd, capture_output, text, timeout):
            return _FakeCompletedProcess(returncode=0, stdout="README.md\n_posts/not-there.txt\n")

        monkeypatch.setattr(subprocess, "run", _fake_run)
        # README.md doesn't exist under posts_dir.parent/README.md's actual
        # location won't matter since _permalink_from_post will fail to read
        # it and log+return None (posts_dir.parent may not contain it).
        urls = idx.urls_from_changed_posts("HEAD~1", posts_dir)
        assert urls == []

    def test_nonzero_returncode_returns_empty(self, tmp_path, monkeypatch):
        posts_dir = tmp_path / "_posts"
        posts_dir.mkdir()

        def _fake_run(cmd, capture_output, text, timeout):
            return _FakeCompletedProcess(returncode=1, stderr="fatal: bad revision")

        monkeypatch.setattr(subprocess, "run", _fake_run)
        assert idx.urls_from_changed_posts("bad-ref", posts_dir) == []

    def test_timeout_returns_empty(self, tmp_path, monkeypatch):
        posts_dir = tmp_path / "_posts"
        posts_dir.mkdir()

        def _fake_run(cmd, capture_output, text, timeout):
            raise subprocess.TimeoutExpired(cmd=cmd, timeout=timeout)

        monkeypatch.setattr(subprocess, "run", _fake_run)
        assert idx.urls_from_changed_posts("HEAD~1", posts_dir) == []

    def test_git_not_found_returns_empty(self, tmp_path, monkeypatch):
        posts_dir = tmp_path / "_posts"
        posts_dir.mkdir()

        def _fake_run(cmd, capture_output, text, timeout):
            raise FileNotFoundError("git not installed")

        monkeypatch.setattr(subprocess, "run", _fake_run)
        assert idx.urls_from_changed_posts("HEAD~1", posts_dir) == []


# ---------------------------------------------------------------------------
# submit_urls — with _submit_batch stubbed (no real urllib access)
# ---------------------------------------------------------------------------


class TestSubmitUrls:
    def test_invalid_host_filtered_out(self, monkeypatch):
        calls = []
        monkeypatch.setattr(idx, "_submit_batch", lambda urls, key: calls.append(urls) or True)
        ok = idx.submit_urls([f"https://{_HOST}/ok/", "https://example.com/bad/"], "key")
        assert ok is True
        assert calls == [[f"https://{_HOST}/ok/"]]

    def test_dedup_preserves_order(self, monkeypatch):
        calls = []
        monkeypatch.setattr(idx, "_submit_batch", lambda urls, key: calls.append(urls) or True)
        urls_in = [f"https://{_HOST}/a/", f"https://{_HOST}/b/", f"https://{_HOST}/a/"]
        idx.submit_urls(urls_in, "key")
        assert calls == [[f"https://{_HOST}/a/", f"https://{_HOST}/b/"]]

    def test_empty_after_filtering_returns_true(self, monkeypatch):
        monkeypatch.setattr(
            idx, "_submit_batch", lambda urls, key: (_ for _ in ()).throw(AssertionError("should not be called"))
        )
        assert idx.submit_urls(["https://example.com/only-invalid/"], "key") is True

    def test_multi_batch_chunking(self, monkeypatch):
        monkeypatch.setattr(idx, "MAX_URLS_PER_BATCH", 2)
        calls = []
        monkeypatch.setattr(idx, "_submit_batch", lambda urls, key: calls.append(list(urls)) or True)
        urls_in = [f"https://{_HOST}/{i}/" for i in range(5)]
        ok = idx.submit_urls(urls_in, "key")
        assert ok is True
        assert calls == [
            [f"https://{_HOST}/0/", f"https://{_HOST}/1/"],
            [f"https://{_HOST}/2/", f"https://{_HOST}/3/"],
            [f"https://{_HOST}/4/"],
        ]

    def test_partial_failure_returns_false(self, monkeypatch):
        monkeypatch.setattr(idx, "MAX_URLS_PER_BATCH", 1)
        results = iter([True, False])
        monkeypatch.setattr(idx, "_submit_batch", lambda urls, key: next(results))
        urls_in = [f"https://{_HOST}/a/", f"https://{_HOST}/b/"]
        assert idx.submit_urls(urls_in, "key") is False


# ---------------------------------------------------------------------------
# parser / main wiring
# ---------------------------------------------------------------------------


class TestParserAndMain:
    def test_mutually_exclusive_group_rejects_two_sources(self):
        parser = idx._build_parser()
        import pytest

        with pytest.raises(SystemExit):
            parser.parse_args(["--urls", "https://x/", "--from-recent-posts", "5"])

    def test_main_urls_source(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["indexnow_submit.py", "--urls", f"https://{_HOST}/a/"])
        captured = {}
        monkeypatch.setattr(idx, "submit_urls", lambda urls, key: captured.setdefault("urls", urls) or True)
        rc = idx.main(["--urls", f"https://{_HOST}/a/"])
        assert rc == 0
        assert captured["urls"] == [f"https://{_HOST}/a/"]

    def test_main_from_recent_posts_source(self, monkeypatch):
        monkeypatch.setattr(
            idx,
            "urls_from_recent_posts",
            lambda n, posts_dir: [f"https://{_HOST}/recent/{n}/"],
        )
        monkeypatch.setattr(idx, "submit_urls", lambda urls, key: True)
        rc = idx.main(["--from-recent-posts", "3"])
        assert rc == 0

    def test_main_from_sitemap_source_explicit(self, monkeypatch, tmp_path):
        called = {}
        monkeypatch.setattr(idx, "urls_from_sitemap", lambda source: called.setdefault("source", source) or [])
        monkeypatch.setattr(idx, "submit_urls", lambda urls, key: True)
        custom = str(tmp_path / "custom-sitemap.xml")
        rc = idx.main(["--from-sitemap", custom])
        assert rc == 0
        assert called["source"] == custom

    def test_main_from_changed_posts_source(self, monkeypatch):
        called = {}
        monkeypatch.setattr(
            idx,
            "urls_from_changed_posts",
            lambda base_ref, posts_dir: called.setdefault("base_ref", base_ref) or [],
        )
        monkeypatch.setattr(idx, "submit_urls", lambda urls, key: True)
        rc = idx.main(["--from-changed-posts", "HEAD~1"])
        assert rc == 0
        assert called["base_ref"] == "HEAD~1"

    def test_main_returns_1_on_submit_failure(self, monkeypatch):
        monkeypatch.setattr(idx, "submit_urls", lambda urls, key: False)
        rc = idx.main(["--urls", f"https://{_HOST}/a/"])
        assert rc == 1
