"""tests/test_fix_post_number_format.py — fix_post_number_format 단위 테스트.

유럽식 숫자 포맷(``BTC$71.018,21``)을 미국식(``BTC $71,018.21``)으로
치환하는 순수 로직(``_fix_content``)과 mtime 기반 스캔(``scan_posts``),
그리고 dry-run/apply CLI 경로(``main``)를 결정적으로 구동한다.
"""

import os
import time
from datetime import UTC, datetime

import fix_post_number_format as fpnf

# ---------------------------------------------------------------------------
# _fix_content
# ---------------------------------------------------------------------------


class TestFixContent:
    def test_prefixed_amount(self):
        out, n = fpnf._fix_content("가격 BTC$71.018,21 상승")
        assert out == "가격 BTC $71,018.21 상승"
        assert n == 1

    def test_bare_dollar_amount(self):
        out, n = fpnf._fix_content("무려 $71.018,21 도달")
        assert out == "무려 $71,018.21 도달"
        assert n == 1

    def test_no_double_substitution(self):
        # 패턴1 치환 결과가 패턴2에 다시 걸리지 않아야 한다(총 1건).
        out, n = fpnf._fix_content("ETH$3.456,78")
        assert out == "ETH $3,456.78"
        assert n == 1

    def test_already_us_format_untouched(self):
        text = "정상 $71,018.21 값"
        out, n = fpnf._fix_content(text)
        assert out == text
        assert n == 0

    def test_multiple_occurrences(self):
        out, n = fpnf._fix_content("$1.234,56 그리고 BTC$9.999,00")
        assert n == 2
        assert "$1,234.56" in out
        assert "BTC $9,999.00" in out


# ---------------------------------------------------------------------------
# _post_mtime / scan_posts
# ---------------------------------------------------------------------------


class TestScanPosts:
    def _write(self, directory, name, *, age_days=0):
        path = directory / name
        path.write_text("dummy", encoding="utf-8")
        if age_days:
            old = time.time() - age_days * 86400
            os.utime(path, (old, old))
        return path

    def test_post_mtime_is_utc(self, tmp_path):
        p = self._write(tmp_path, "2026-01-01-a.md")
        mt = fpnf._post_mtime(p)
        assert isinstance(mt, datetime)
        assert mt.tzinfo == UTC

    def test_filters_by_age(self, tmp_path):
        self._write(tmp_path, "2026-01-01-fresh.md", age_days=1)
        self._write(tmp_path, "2026-01-01-stale.md", age_days=90)
        found = fpnf.scan_posts(tmp_path, days=30)
        names = [p.name for p in found]
        assert "2026-01-01-fresh.md" in names
        assert "2026-01-01-stale.md" not in names

    def test_returns_sorted(self, tmp_path):
        self._write(tmp_path, "2026-01-03-c.md")
        self._write(tmp_path, "2026-01-01-a.md")
        self._write(tmp_path, "2026-01-02-b.md")
        found = fpnf.scan_posts(tmp_path, days=30)
        assert [p.name for p in found] == sorted(p.name for p in found)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


class TestMain:
    def _run(self, monkeypatch, argv):
        monkeypatch.setattr("sys.argv", ["fix_post_number_format.py", *argv])
        return fpnf.main()

    def test_missing_dir_returns_2(self, tmp_path, monkeypatch, capsys):
        missing = tmp_path / "nope"
        rc = self._run(monkeypatch, ["--posts-dir", str(missing)])
        assert rc == 2
        assert "찾을 수 없습니다" in capsys.readouterr().err

    def test_dry_run_does_not_write(self, tmp_path, monkeypatch, capsys):
        post = tmp_path / "2026-01-01-x.md"
        post.write_text("BTC$71.018,21", encoding="utf-8")
        rc = self._run(monkeypatch, ["--posts-dir", str(tmp_path)])
        assert rc == 0
        assert post.read_text(encoding="utf-8") == "BTC$71.018,21"
        out = capsys.readouterr().out
        assert "DRY-RUN" in out
        assert "예정" in out

    def test_apply_writes_changes(self, tmp_path, monkeypatch, capsys):
        post = tmp_path / "2026-01-01-x.md"
        post.write_text("BTC$71.018,21", encoding="utf-8")
        rc = self._run(monkeypatch, ["--posts-dir", str(tmp_path), "--apply"])
        assert rc == 0
        assert post.read_text(encoding="utf-8") == "BTC $71,018.21"
        assert "수정됨" in capsys.readouterr().out

    def test_apply_no_matches_is_noop(self, tmp_path, monkeypatch, capsys):
        post = tmp_path / "2026-01-01-clean.md"
        post.write_text("정상 텍스트 $1,234.56", encoding="utf-8")
        rc = self._run(monkeypatch, ["--posts-dir", str(tmp_path), "--apply"])
        assert rc == 0
        assert "0개 파일 수정" in capsys.readouterr().out
