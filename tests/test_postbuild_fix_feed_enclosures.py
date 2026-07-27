"""tests/test_postbuild_fix_feed_enclosures.py — postbuild_fix_feed_enclosures 단위 테스트.

jekyll-feed가 항상 ``length="0"`` 으로 내보내는 RSS enclosure를 실제
바이트 크기로 다시 쓰는 postbuild 픽서. 경로 매핑(``_resolve_local_path``,
path-traversal 방어 포함), 실제 재작성(``fix_feed``), CLI(``main``)의
없음/성공/누락 경로를 결정적으로 구동한다.
"""

import postbuild_fix_feed_enclosures as pfe


def _enclosure(url, type_="audio/mpeg", length="0") -> str:
    return f'<enclosure url="{url}" type="{type_}" length="{length}"/>'


def _feed(directory, *tags) -> "object":
    path = directory / "feed.xml"
    path.write_text(f"<rss><channel>{''.join(tags)}</channel></rss>", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# _resolve_local_path
# ---------------------------------------------------------------------------


class TestResolveLocalPath:
    def test_maps_relative_url_to_file(self, tmp_path):
        (tmp_path / "assets").mkdir()
        f = tmp_path / "assets" / "a.mp3"
        f.write_bytes(b"xyz")
        got = pfe._resolve_local_path(tmp_path, "/assets/a.mp3")
        assert got == f.resolve()

    def test_empty_path_returns_none(self, tmp_path):
        assert pfe._resolve_local_path(tmp_path, "https://x.com/") is None

    def test_missing_file_returns_none(self, tmp_path):
        assert pfe._resolve_local_path(tmp_path, "/assets/missing.mp3") is None

    def test_path_traversal_blocked(self, tmp_path):
        # site_dir 밖을 가리키는 ../ 경로는 relative_to 검증에서 차단돼 None.
        site = tmp_path / "site"
        site.mkdir()
        assert pfe._resolve_local_path(site, "/../secret.txt") is None


# ---------------------------------------------------------------------------
# fix_feed
# ---------------------------------------------------------------------------


class TestFixFeed:
    def test_rewrites_length(self, tmp_path):
        (tmp_path / "a.mp3").write_bytes(b"12345")  # 5 bytes
        feed = _feed(tmp_path, _enclosure("/a.mp3", length="0"))
        total, fixed, missing = pfe.fix_feed(feed, tmp_path)
        assert (total, fixed, missing) == (1, 1, 0)
        assert 'length="5"' in feed.read_text(encoding="utf-8")

    def test_unchanged_when_already_correct(self, tmp_path):
        (tmp_path / "a.mp3").write_bytes(b"1234")  # 4 bytes
        feed = _feed(tmp_path, _enclosure("/a.mp3", length="4"))
        total, fixed, missing = pfe.fix_feed(feed, tmp_path)
        assert (total, fixed, missing) == (1, 0, 0)

    def test_missing_file_counted(self, tmp_path):
        feed = _feed(tmp_path, _enclosure("/gone.mp3", length="0"))
        total, fixed, missing = pfe.fix_feed(feed, tmp_path)
        assert (total, fixed, missing) == (1, 0, 1)
        assert 'length="0"' in feed.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# _emit
# ---------------------------------------------------------------------------


def test_emit_writes_line(capsys):
    pfe._emit("hello")
    assert capsys.readouterr().out == "hello\n"


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


class TestMain:
    def test_feed_not_found_returns_0(self, tmp_path):
        assert pfe.main(["--site", str(tmp_path)]) == 0

    def test_success_reports_counts(self, tmp_path, capsys):
        (tmp_path / "a.mp3").write_bytes(b"12345")
        _feed(tmp_path, _enclosure("/a.mp3", length="0"))
        rc = pfe.main(["--site", str(tmp_path)])
        assert rc == 0
        assert "total=1 fixed=1" in capsys.readouterr().out

    def test_missing_enclosure_warns(self, tmp_path, capsys):
        _feed(tmp_path, _enclosure("/gone.mp3", length="0"))
        rc = pfe.main(["--site", str(tmp_path)])
        assert rc == 0
        assert "missing=1" in capsys.readouterr().out

    def test_explicit_feed_arg(self, tmp_path, capsys):
        (tmp_path / "a.mp3").write_bytes(b"12345")
        custom = tmp_path / "rss.xml"
        custom.write_text(
            f"<rss><channel>{_enclosure('/a.mp3', length='0')}</channel></rss>",
            encoding="utf-8",
        )
        rc = pfe.main(["--site", str(tmp_path), "--feed", str(custom)])
        assert rc == 0
        assert 'length="5"' in custom.read_text(encoding="utf-8")
