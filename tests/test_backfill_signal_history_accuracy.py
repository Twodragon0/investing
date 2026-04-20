"""Tests for scripts/backfill_signal_history_accuracy.py.

Coverage (15+ cases):
- dry_run: detects missing accuracy entries, reports count and indices
- dry_run: does NOT write to file
- apply: inserts stub accuracy for every missing entry
- apply: does NOT touch entries that already have accuracy (idempotent)
- apply: idempotent — re-running apply produces same result
- apply: btc_price=null entries get stub inserted (nullable kept)
- stub structure: all required keys present
- stub structure: compatible with _SIGNAL_SCHEMA validate (0 errors)
- stub: backfilled_accuracy_stub flag set to True
- stub: predicted_verdict/predicted_score mirror entry fields
- file not found: graceful exit with code 0
- empty file: graceful exit with code 0
- no missing accuracy: early exit, file untouched
- stdout format: "누락된 accuracy: N건" in output
- stdout format: "DRY-RUN: no changes written" in dry-run output
- stdout format: "APPLIED:" in apply output
- find_missing_accuracy_indices: correct index list
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any
from unittest.mock import patch

import pytest

# Add scripts/ to sys.path so imports work
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import backfill_signal_history_accuracy as bfsa  # noqa: E402

from common.time_series_state import TimeSeriesStore  # noqa: E402

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_entry(
    date: str,
    verdict: str = "혼조",
    score: float = 50.0,
    btc_price: float | None = 70000.0,
    with_accuracy: bool = False,
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "date": date,
        "composite_score": score,
        "verdict": verdict,
        "confidence": "medium",
        "signal_scores": {"공포·탐욕 지수": 0.5},
        "btc_price": btc_price,
        "recorded_at": "2026-04-01T00:00:00Z",
    }
    if with_accuracy:
        entry["accuracy"] = {
            "predicted_verdict": verdict,
            "predicted_score": score,
            "actual_price_change_pct": 1.5,
            "actual_direction": "상승",
            "correct": True,
            "evaluated_at": "2026-04-02T00:00:00Z",
        }
    return entry


def _write_history(path, entries: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)


def _load_history(path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ── find_missing_accuracy_indices ─────────────────────────────────────────────


class TestFindMissingAccuracyIndices:
    def test_all_missing(self):
        entries = [_make_entry("2026-04-01"), _make_entry("2026-04-02")]
        result = bfsa.find_missing_accuracy_indices(entries)
        assert result == [0, 1]

    def test_none_missing(self):
        entries = [
            _make_entry("2026-04-01", with_accuracy=True),
            _make_entry("2026-04-02", with_accuracy=True),
        ]
        result = bfsa.find_missing_accuracy_indices(entries)
        assert result == []

    def test_mixed(self):
        entries = [
            _make_entry("2026-04-01", with_accuracy=True),
            _make_entry("2026-04-02"),
            _make_entry("2026-04-03", with_accuracy=True),
            _make_entry("2026-04-04"),
        ]
        result = bfsa.find_missing_accuracy_indices(entries)
        assert result == [1, 3]

    def test_empty_list(self):
        assert bfsa.find_missing_accuracy_indices([]) == []


# ── _make_accuracy_stub ───────────────────────────────────────────────────────


class TestMakeAccuracyStub:
    def test_has_all_required_keys(self):
        entry = _make_entry("2026-04-01", verdict="약세", score=35.0)
        stub = bfsa._make_accuracy_stub(entry)
        for key in (
            "predicted_verdict",
            "predicted_score",
            "actual_price_change_pct",
            "actual_direction",
            "correct",
            "evaluated_at",
        ):
            assert key in stub, f"Missing key: {key}"

    def test_mirrors_verdict(self):
        entry = _make_entry("2026-04-01", verdict="강세", score=75.0)
        stub = bfsa._make_accuracy_stub(entry)
        assert stub["predicted_verdict"] == "강세"
        assert stub["predicted_score"] == 75.0

    def test_nullable_price_fields(self):
        entry = _make_entry("2026-04-01")
        stub = bfsa._make_accuracy_stub(entry)
        assert stub["actual_price_change_pct"] is None
        assert stub["actual_direction"] is None
        assert stub["correct"] is None

    def test_backfilled_flag(self):
        entry = _make_entry("2026-04-01")
        stub = bfsa._make_accuracy_stub(entry)
        assert stub["backfilled_accuracy_stub"] is True

    def test_schema_compatible(self):
        """Stub inserted into a record must pass _SIGNAL_SCHEMA validate (0 errors)."""
        from pathlib import Path

        entry = _make_entry("2026-04-01", verdict="약세", score=30.0)
        entry["accuracy"] = bfsa._make_accuracy_stub(entry)

        store = TimeSeriesStore(Path("/dev/null"), bfsa._SIGNAL_SCHEMA, None)
        issues = store.validate([entry])
        errors = [iss for iss in issues if iss.severity == "error"]
        assert errors == [], f"Schema errors after stub insert: {errors}"


# ── backfill — file not found ─────────────────────────────────────────────────


class TestBackfillFileNotFound:
    def test_returns_0_on_missing_file(self, tmp_path):
        nonexistent = str(tmp_path / "no_such_file.json")
        result = bfsa.backfill(history_file=nonexistent, dry_run=True)
        assert result == 0

    def test_prints_file_not_found(self, tmp_path, capsys):
        nonexistent = str(tmp_path / "no_such_file.json")
        bfsa.backfill(history_file=nonexistent, dry_run=True)
        out = capsys.readouterr().out
        assert "not found" in out.lower() or "File not found" in out


# ── backfill — empty file ─────────────────────────────────────────────────────


class TestBackfillEmptyFile:
    def test_returns_0_on_empty(self, tmp_path):
        path = tmp_path / "signal_history.json"
        _write_history(str(path), [])
        result = bfsa.backfill(history_file=str(path), dry_run=True)
        assert result == 0

    def test_does_not_modify_empty_file(self, tmp_path):
        path = tmp_path / "signal_history.json"
        _write_history(str(path), [])
        bfsa.backfill(history_file=str(path), dry_run=True)
        # File was not rewritten (contents still [])
        assert _load_history(str(path)) == []


# ── backfill — no missing entries ─────────────────────────────────────────────


class TestBackfillNoMissing:
    def test_returns_0(self, tmp_path):
        path = tmp_path / "signal_history.json"
        entries = [
            _make_entry("2026-04-01", with_accuracy=True),
            _make_entry("2026-04-02", with_accuracy=True),
        ]
        _write_history(str(path), entries)
        result = bfsa.backfill(history_file=str(path), dry_run=True)
        assert result == 0

    def test_file_untouched(self, tmp_path):
        path = tmp_path / "signal_history.json"
        entries = [_make_entry("2026-04-01", with_accuracy=True)]
        _write_history(str(path), entries)
        bfsa.backfill(history_file=str(path), dry_run=False)
        # No missing entries → _write_atomic never called → file unchanged
        assert _load_history(str(path))[0].get("accuracy") is not None


# ── backfill — dry-run ────────────────────────────────────────────────────────


class TestBackfillDryRun:
    def test_reports_missing_count(self, tmp_path, capsys):
        path = tmp_path / "signal_history.json"
        entries = [
            _make_entry("2026-04-01"),
            _make_entry("2026-04-02", with_accuracy=True),
            _make_entry("2026-04-03"),
        ]
        _write_history(str(path), entries)
        bfsa.backfill(history_file=str(path), dry_run=True)
        out = capsys.readouterr().out
        assert "누락된 accuracy: 2건" in out

    def test_reports_indices(self, tmp_path, capsys):
        path = tmp_path / "signal_history.json"
        entries = [_make_entry("2026-04-01"), _make_entry("2026-04-02")]
        _write_history(str(path), entries)
        bfsa.backfill(history_file=str(path), dry_run=True)
        out = capsys.readouterr().out
        assert "[0, 1]" in out

    def test_does_not_write_file(self, tmp_path):
        path = tmp_path / "signal_history.json"
        entries = [_make_entry("2026-04-01"), _make_entry("2026-04-02")]
        _write_history(str(path), entries)
        bfsa.backfill(history_file=str(path), dry_run=True)
        # File must not have been modified (accuracy still missing)
        reloaded = _load_history(str(path))
        assert "accuracy" not in reloaded[0]
        assert "accuracy" not in reloaded[1]

    def test_dry_run_stdout_message(self, tmp_path, capsys):
        path = tmp_path / "signal_history.json"
        _write_history(str(path), [_make_entry("2026-04-01")])
        bfsa.backfill(history_file=str(path), dry_run=True)
        out = capsys.readouterr().out
        assert "DRY-RUN" in out

    def test_dry_run_shows_btc_price_null_note(self, tmp_path, capsys):
        path = tmp_path / "signal_history.json"
        entries = [_make_entry("2026-04-01", btc_price=None)]
        _write_history(str(path), entries)
        bfsa.backfill(history_file=str(path), dry_run=True)
        out = capsys.readouterr().out
        assert "null" in out.lower() or "nullable" in out.lower()


# ── backfill — apply ──────────────────────────────────────────────────────────


class TestBackfillApply:
    def test_inserts_stub_for_missing(self, tmp_path):
        path = tmp_path / "signal_history.json"
        entries = [_make_entry("2026-04-01"), _make_entry("2026-04-02")]
        _write_history(str(path), entries)
        bfsa.backfill(history_file=str(path), dry_run=False)
        reloaded = _load_history(str(path))
        assert "accuracy" in reloaded[0]
        assert "accuracy" in reloaded[1]

    def test_does_not_touch_existing_accuracy(self, tmp_path):
        path = tmp_path / "signal_history.json"
        original_accuracy = {
            "predicted_verdict": "강세",
            "predicted_score": 75.0,
            "actual_price_change_pct": 2.5,
            "actual_direction": "상승",
            "correct": True,
            "evaluated_at": "2026-04-02T00:00:00Z",
        }
        entry_with = _make_entry("2026-04-01", with_accuracy=True)
        entry_with["accuracy"] = original_accuracy
        entry_without = _make_entry("2026-04-02")
        _write_history(str(path), [entry_with, entry_without])
        bfsa.backfill(history_file=str(path), dry_run=False)
        reloaded = _load_history(str(path))
        # Original accuracy preserved exactly
        assert reloaded[0]["accuracy"] == original_accuracy

    def test_idempotent(self, tmp_path):
        path = tmp_path / "signal_history.json"
        entries = [_make_entry("2026-04-01"), _make_entry("2026-04-02")]
        _write_history(str(path), entries)
        bfsa.backfill(history_file=str(path), dry_run=False)
        after_first = _load_history(str(path))
        bfsa.backfill(history_file=str(path), dry_run=False)
        after_second = _load_history(str(path))
        assert after_first == after_second

    def test_btc_price_null_gets_stub(self, tmp_path):
        path = tmp_path / "signal_history.json"
        entries = [_make_entry("2026-04-13", btc_price=None)]
        _write_history(str(path), entries)
        bfsa.backfill(history_file=str(path), dry_run=False)
        reloaded = _load_history(str(path))
        assert "accuracy" in reloaded[0]
        # btc_price stays null
        assert reloaded[0]["btc_price"] is None

    def test_apply_stdout_message(self, tmp_path, capsys):
        path = tmp_path / "signal_history.json"
        _write_history(str(path), [_make_entry("2026-04-01")])
        bfsa.backfill(history_file=str(path), dry_run=False)
        out = capsys.readouterr().out
        assert "APPLIED" in out

    def test_apply_returns_0(self, tmp_path):
        path = tmp_path / "signal_history.json"
        _write_history(str(path), [_make_entry("2026-04-01")])
        result = bfsa.backfill(history_file=str(path), dry_run=False)
        assert result == 0

    def test_stub_passes_schema_validate_for_all_entries(self, tmp_path):
        """After apply, all entries must pass _SIGNAL_SCHEMA validate."""
        from pathlib import Path

        path = tmp_path / "signal_history.json"
        entries = [
            _make_entry("2026-04-01"),
            _make_entry("2026-04-02", with_accuracy=True),
            _make_entry("2026-04-03", btc_price=None),
        ]
        _write_history(str(path), entries)
        bfsa.backfill(history_file=str(path), dry_run=False)
        reloaded = _load_history(str(path))

        store = TimeSeriesStore(Path(str(path)), bfsa._SIGNAL_SCHEMA, None)
        issues = store.validate(reloaded)
        errors = [iss for iss in issues if iss.severity == "error"]
        assert errors == [], f"Schema errors after backfill: {errors}"

    def test_validation_zero_remaining_after_apply(self, tmp_path, capsys):
        path = tmp_path / "signal_history.json"
        entries = [_make_entry("2026-04-01"), _make_entry("2026-04-02")]
        _write_history(str(path), entries)
        bfsa.backfill(history_file=str(path), dry_run=False)
        out = capsys.readouterr().out
        assert "0 missing accuracy" in out


# ── main() integration ────────────────────────────────────────────────────────


class TestMain:
    def test_main_dry_run_default(self, tmp_path, capsys):
        path = tmp_path / "signal_history.json"
        _write_history(str(path), [_make_entry("2026-04-01")])
        with (
            patch("sys.argv", ["backfill_signal_history_accuracy.py", "--file", str(path)]),
            pytest.raises(SystemExit) as exc_info,
        ):
            bfsa.main()
        assert exc_info.value.code == 0
        out = capsys.readouterr().out
        assert "DRY-RUN" in out

    def test_main_apply_flag(self, tmp_path, capsys):
        path = tmp_path / "signal_history.json"
        _write_history(str(path), [_make_entry("2026-04-01")])
        with (
            patch("sys.argv", ["backfill_signal_history_accuracy.py", "--apply", "--file", str(path)]),
            pytest.raises(SystemExit) as exc_info,
        ):
            bfsa.main()
        assert exc_info.value.code == 0
        reloaded = _load_history(str(path))
        assert "accuracy" in reloaded[0]
