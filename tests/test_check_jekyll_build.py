import check_jekyll_build as cjb


def test_main_returns_zero_when_log_has_no_conflicts(tmp_path, monkeypatch, capsys):
    build_log = tmp_path / "build.log"
    build_log.write_text("Build completed successfully.\n", encoding="utf-8")
    monkeypatch.setattr(cjb.sys, "argv", ["check_jekyll_build.py", str(build_log)])

    assert cjb.main() == 0
    assert "free of destination conflict warnings" in capsys.readouterr().out


def test_main_returns_one_and_prints_conflicts(tmp_path, monkeypatch, capsys):
    build_log = tmp_path / "build.log"
    build_log.write_text(
        "Info line\nConflict: The following destination is shared\n  Conflict: another one\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(cjb.sys, "argv", ["check_jekyll_build.py", str(build_log)])

    assert cjb.main() == 1
    stderr = capsys.readouterr().err
    assert "Jekyll build reported destination conflicts:" in stderr
    assert "Conflict: The following destination is shared" in stderr
