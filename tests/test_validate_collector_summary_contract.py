import ast
from pathlib import Path

import validate_collector_summary_contract as vcsc


def _write_python(path: Path, source: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def test_find_calls_detects_name_and_attribute_invocations():
    tree = ast.parse(
        """
log_collection_summary(collector="a", source_count=1, unique_items=1, post_created=1, started_at="x")
collector.log_collection_summary(collector="b")
self.log_summary()
"""
    )

    calls = vcsc._find_calls(tree)

    assert len(calls) == 3


def test_validate_file_reports_missing_call(tmp_path):
    file_path = tmp_path / "collector.py"
    _write_python(file_path, "def run():\n    return 1\n")

    assert vcsc._validate_file(file_path) == [f"missing-call:{file_path}"]


def test_validate_file_reports_missing_required_kwargs(tmp_path):
    file_path = tmp_path / "collector.py"
    _write_python(file_path, 'log_collection_summary(collector="demo")\n')

    assert vcsc._validate_file(file_path) == [f"missing-required-kwargs:{file_path}"]


def test_validate_file_accepts_log_summary_method(tmp_path):
    file_path = tmp_path / "collector.py"
    _write_python(file_path, "self.log_summary()\n")

    assert vcsc._validate_file(file_path) == []


def test_validate_file_accepts_required_kwargs(tmp_path):
    file_path = tmp_path / "collector.py"
    _write_python(
        file_path,
        """
log_collection_summary(
    collector="demo",
    source_count=1,
    unique_items=1,
    post_created=True,
    started_at="2026-04-17T00:00:00Z",
)
""",
    )

    assert vcsc._validate_file(file_path) == []


def test_main_reports_missing_and_invalid_collectors(tmp_path, monkeypatch, capsys):
    scripts_dir = tmp_path / "scripts"
    invalid = scripts_dir / "invalid.py"
    valid = scripts_dir / "valid.py"

    _write_python(invalid, 'log_collection_summary(collector="demo")\n')
    _write_python(valid, "self.log_summary()\n")

    monkeypatch.setattr(vcsc, "SCRIPTS_DIR", scripts_dir)
    monkeypatch.setattr(vcsc, "TARGET_COLLECTORS", ["invalid.py", "valid.py", "missing.py"])

    assert vcsc.main() == 1

    output = capsys.readouterr().out
    assert "Collector summary contract failures:" in output
    assert f"missing-required-kwargs:{invalid}" in output
    assert f"missing-file:{scripts_dir / 'missing.py'}" in output


def test_main_passes_when_all_collectors_are_valid(tmp_path, monkeypatch, capsys):
    scripts_dir = tmp_path / "scripts"
    first = scripts_dir / "first.py"
    second = scripts_dir / "second.py"

    _write_python(first, "self.log_summary()\n")
    _write_python(
        second,
        """
log_collection_summary(
    collector="demo",
    source_count=2,
    unique_items=2,
    post_created=False,
    started_at="2026-04-17T00:00:00Z",
)
""",
    )

    monkeypatch.setattr(vcsc, "SCRIPTS_DIR", scripts_dir)
    monkeypatch.setattr(vcsc, "TARGET_COLLECTORS", ["first.py", "second.py"])

    assert vcsc.main() == 0
    assert "Collector summary contract passed for 2 collector(s)." in capsys.readouterr().out
