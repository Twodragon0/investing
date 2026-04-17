from pathlib import Path

import verify_rendered_fixtures as vrf


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_validate_target_reports_expected_failures(tmp_path):
    fixture = tmp_path / "fixture.html"
    html = "plain text only"
    target = {
        "must_table": True,
        "must_details": True,
        "forbid": [r"plain text"],
        "required_patterns": [r"required-marker"],
    }

    failures = vrf._validate_target(target, str(fixture), html)

    assert f"missing-table:{fixture}" in failures
    assert f"missing-details:{fixture}" in failures
    assert f"forbidden-pattern:plain text:{fixture}" in failures
    assert f"missing-required-pattern:required-marker:{fixture}" in failures


def test_main_passes_with_positive_and_negative_fixtures(tmp_path, monkeypatch, capsys):
    fixture_dir = tmp_path / "fixtures"
    positive = fixture_dir / "positive.html"
    broken = fixture_dir / "broken.html"

    _write_text(positive, "<table>ok</table><details>ok</details><div>required-marker</div>")
    _write_text(broken, "| # | 이슈 |")

    monkeypatch.setattr(vrf, "FIXTURE_DIR", str(fixture_dir))
    monkeypatch.setattr(
        vrf,
        "TARGETS",
        [
            {
                "file": "positive.html",
                "must_table": True,
                "must_details": True,
                "forbid": [r"forbidden"],
                "required_patterns": [r"required-marker"],
            }
        ],
    )
    monkeypatch.setattr(
        vrf,
        "NEGATIVE_TARGETS",
        [
            {
                "file": "broken.html",
                "must_table": True,
                "must_details": False,
                "forbid": [r"\|\s*#\s*\|\s*이슈\s*\|"],
                "expected_error_prefixes": ["missing-table", "forbidden-pattern"],
            }
        ],
    )

    assert vrf.main() == 0
    assert "Rendered fixture smoke tests passed for 1 positive and 1 negative fixture(s)." in capsys.readouterr().out


def test_main_reports_missing_fixtures_and_negative_check_misses(tmp_path, monkeypatch, capsys):
    fixture_dir = tmp_path / "fixtures"
    negative = fixture_dir / "negative.html"
    _write_text(negative, "<table>ok</table>")

    monkeypatch.setattr(vrf, "FIXTURE_DIR", str(fixture_dir))
    monkeypatch.setattr(
        vrf,
        "TARGETS",
        [{"file": "missing.html", "must_table": True, "must_details": False, "forbid": []}],
    )
    monkeypatch.setattr(
        vrf,
        "NEGATIVE_TARGETS",
        [
            {
                "file": "negative.html",
                "must_table": True,
                "must_details": False,
                "forbid": [],
                "expected_error_prefixes": ["missing-table"],
            }
        ],
    )

    assert vrf.main() == 1
    output = capsys.readouterr().out
    assert "Rendered fixture smoke test failures:" in output
    assert f"missing-fixture:{fixture_dir / 'missing.html'}" in output
    assert f"negative-check-missed:missing-table:{negative}" in output
