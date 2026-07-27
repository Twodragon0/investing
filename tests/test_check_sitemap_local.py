"""tests/test_check_sitemap_local.py — check_sitemap_local 단위 테스트.

빌드된 ``_site/sitemap.xml`` 의 각 ``<loc>`` URL이 디스크의 산출물과
매핑되는지 검증하는 로컬 진단 도구. 순수 파서(``extract_locs``),
URL→디스크 경로 변환(``url_to_disk_path``), 그리고 CLI(``main``)의
성공/누락/미발견 종료 코드를 결정적으로 구동한다.
"""

from pathlib import Path

import check_sitemap_local as csl

_BASE = "https://investing.2twodragon.com"


def _sitemap(directory, urls) -> Path:
    body = "".join(f"<loc>{u}</loc>" for u in urls)
    path = directory / "sitemap.xml"
    path.write_text(f"<urlset>{body}</urlset>", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# extract_locs
# ---------------------------------------------------------------------------


class TestExtractLocs:
    def test_extracts_all(self, tmp_path):
        sm = _sitemap(tmp_path, [f"{_BASE}/a/", f"{_BASE}/b/"])
        assert csl.extract_locs(sm) == [f"{_BASE}/a/", f"{_BASE}/b/"]

    def test_empty_sitemap(self, tmp_path):
        sm = _sitemap(tmp_path, [])
        assert csl.extract_locs(sm) == []


# ---------------------------------------------------------------------------
# url_to_disk_path
# ---------------------------------------------------------------------------


class TestUrlToDiskPath:
    def test_trailing_slash_maps_to_index(self, tmp_path):
        got = csl.url_to_disk_path(f"{_BASE}/foo/", _BASE, tmp_path)
        assert got == tmp_path / "foo" / "index.html"

    def test_file_path_direct(self, tmp_path):
        got = csl.url_to_disk_path(f"{_BASE}/assets/x.png", _BASE, tmp_path)
        assert got == tmp_path / "assets" / "x.png"

    def test_root_maps_to_index(self, tmp_path):
        got = csl.url_to_disk_path(_BASE, _BASE, tmp_path)
        assert got == tmp_path / "index.html"


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


class TestMain:
    def _run(self, monkeypatch, argv):
        monkeypatch.setattr("sys.argv", ["check_sitemap_local.py", *argv])
        return csl.main()

    def test_missing_sitemap_returns_2(self, tmp_path, monkeypatch):
        rc = self._run(monkeypatch, ["--site", str(tmp_path)])
        assert rc == 2

    def test_all_present_returns_0(self, tmp_path, monkeypatch):
        (tmp_path / "foo").mkdir()
        (tmp_path / "foo" / "index.html").write_text("ok", encoding="utf-8")
        _sitemap(tmp_path, [f"{_BASE}/foo/"])
        rc = self._run(monkeypatch, ["--site", str(tmp_path)])
        assert rc == 0

    def test_missing_file_returns_1(self, tmp_path, monkeypatch):
        _sitemap(tmp_path, [f"{_BASE}/gone/"])
        rc = self._run(monkeypatch, ["--site", str(tmp_path)])
        assert rc == 1

    def test_non_site_url_is_skipped(self, tmp_path, monkeypatch):
        # 외부 URL은 스킵되므로 누락으로 집계되지 않아 성공(0).
        _sitemap(tmp_path, ["https://example.com/other/"])
        rc = self._run(monkeypatch, ["--site", str(tmp_path)])
        assert rc == 0

    def test_explicit_sitemap_arg(self, tmp_path, monkeypatch):
        custom = _sitemap(tmp_path, [])
        renamed = tmp_path / "custom-sitemap.xml"
        custom.rename(renamed)
        rc = self._run(monkeypatch, ["--site", str(tmp_path), "--sitemap", str(renamed)])
        assert rc == 0
