"""tests/test_fix_scenario_na_placeholders.py — fix_scenario_na_placeholders 단위 테스트.

시나리오 문장에 남은 ``(N/A)`` 아티팩트(``VIX(N/A)`` 등)를 제거하는
순수 치환 로직(``_patch``)과 dry-run/apply CLI 경로(``main``)를 검증한다.
"""

import fix_scenario_na_placeholders as fix

# ---------------------------------------------------------------------------
# _patch
# ---------------------------------------------------------------------------


class TestPatch:
    def test_strips_vix(self):
        out, n = fix._patch("리스크는 VIX(N/A) 로 판단")
        assert out == "리스크는 VIX 로 판단"
        assert n == 1

    def test_strips_momentum(self):
        out, n = fix._patch("모멘텀(N/A) 우위")
        assert out == "모멘텀 우위"
        assert n == 1

    def test_longer_greed_index_form(self):
        out, n = fix._patch("공포·탐욕 지수(N/A) 기준")
        assert out == "공포·탐욕 지수 기준"
        assert n == 1

    def test_bare_greed_form(self):
        out, n = fix._patch("공포·탐욕(N/A) 지표")
        assert out == "공포·탐욕 지표"
        assert n == 1

    def test_no_placeholder_untouched(self):
        text = "VIX 는 안정적"
        out, n = fix._patch(text)
        assert out == text
        assert n == 0

    def test_counts_all_replacements(self):
        out, n = fix._patch("VIX(N/A) / 모멘텀(N/A)")
        assert n == 2
        assert "(N/A)" not in out


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


class TestMain:
    def _run(self, monkeypatch, argv):
        monkeypatch.setattr("sys.argv", ["fix_scenario_na_placeholders.py", *argv])
        return fix.main()

    def test_missing_dir_returns_2(self, tmp_path, monkeypatch, capsys):
        rc = self._run(monkeypatch, ["--posts-dir", str(tmp_path / "nope")])
        assert rc == 2
        assert "not found" in capsys.readouterr().err

    def test_dry_run_does_not_write(self, tmp_path, monkeypatch, capsys):
        post = tmp_path / "2026-01-01-x.md"
        post.write_text("리스크는 VIX(N/A)", encoding="utf-8")
        rc = self._run(monkeypatch, ["--posts-dir", str(tmp_path)])
        assert rc == 0
        assert post.read_text(encoding="utf-8") == "리스크는 VIX(N/A)"
        out = capsys.readouterr().out
        assert "would fix" in out
        assert "re-run with --apply" in out

    def test_apply_writes_changes(self, tmp_path, monkeypatch, capsys):
        post = tmp_path / "2026-01-01-x.md"
        post.write_text("리스크는 VIX(N/A)", encoding="utf-8")
        rc = self._run(monkeypatch, ["--posts-dir", str(tmp_path), "--apply"])
        assert rc == 0
        assert post.read_text(encoding="utf-8") == "리스크는 VIX"
        out = capsys.readouterr().out
        assert "fixed" in out
        assert "applied" in out

    def test_apply_no_matches_is_noop(self, tmp_path, monkeypatch, capsys):
        post = tmp_path / "2026-01-01-clean.md"
        post.write_text("깨끗한 본문", encoding="utf-8")
        rc = self._run(monkeypatch, ["--posts-dir", str(tmp_path), "--apply"])
        assert rc == 0
        assert "files=0" in capsys.readouterr().out
