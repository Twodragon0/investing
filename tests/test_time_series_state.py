"""tests/test_time_series_state.py — TimeSeriesStore / TimeSeriesSchema unit tests (Layer 1)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from common.time_series_state import (
    Bounds,
    TimeSeriesSchema,
    TimeSeriesStore,
    main,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

TVL_SCHEMA = TimeSeriesSchema(
    required_fields=["date", "total_tvl"],
    numeric_fields={"total_tvl": Bounds(min_exclusive=0)},
    date_field="date",
    max_entries=None,
)


def make_store(tmp_path: Path, schema: TimeSeriesSchema = TVL_SCHEMA) -> TimeSeriesStore:
    path = tmp_path / "history.json"
    return TimeSeriesStore(path, schema)


def write_records(path: Path, records: list[dict]) -> None:
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Bounds
# ---------------------------------------------------------------------------


class TestBounds:
    def test_min_exclusive_rejects_equal(self):
        b = Bounds(min_exclusive=0)
        assert b.check(0) is False
        assert b.check(0.001) is True

    def test_min_exclusive_rejects_below(self):
        b = Bounds(min_exclusive=10)
        assert b.check(9.99) is False
        assert b.check(10.01) is True

    def test_max_exclusive_rejects_equal(self):
        b = Bounds(max_exclusive=100)
        assert b.check(100) is False
        assert b.check(99.99) is True

    def test_min_inclusive_accepts_equal(self):
        b = Bounds(min_inclusive=5)
        assert b.check(5) is True
        assert b.check(4.99) is False

    def test_max_inclusive_accepts_equal(self):
        b = Bounds(max_inclusive=200)
        assert b.check(200) is True
        assert b.check(200.01) is False

    def test_combined_bounds(self):
        b = Bounds(min_exclusive=0, max_inclusive=100)
        assert b.check(0) is False
        assert b.check(1) is True
        assert b.check(100) is True
        assert b.check(101) is False

    def test_no_bounds_accepts_all(self):
        b = Bounds()
        assert b.check(-999) is True
        assert b.check(0) is True
        assert b.check(999999) is True


# ---------------------------------------------------------------------------
# validate — one test per issue code
# ---------------------------------------------------------------------------


class TestValidate:
    def test_zero_value(self):
        store = TimeSeriesStore(Path("/dev/null"), TVL_SCHEMA)
        issues = store.validate([{"date": "2026-04-11", "total_tvl": 0}])
        codes = [iss.code for iss in issues]
        assert "ZERO_VALUE" in codes

    def test_missing_field(self):
        store = TimeSeriesStore(Path("/dev/null"), TVL_SCHEMA)
        issues = store.validate([{"date": "2026-04-11"}])  # missing total_tvl
        codes = [iss.code for iss in issues]
        assert "MISSING_FIELD" in codes

    def test_invalid_date_format(self):
        store = TimeSeriesStore(Path("/dev/null"), TVL_SCHEMA)
        issues = store.validate([{"date": "11-04-2026", "total_tvl": 100.0}])
        codes = [iss.code for iss in issues]
        assert "INVALID_DATE" in codes

    def test_unsorted(self):
        store = TimeSeriesStore(Path("/dev/null"), TVL_SCHEMA)
        records = [
            {"date": "2026-04-12", "total_tvl": 200.0},
            {"date": "2026-04-11", "total_tvl": 100.0},  # earlier date after later
        ]
        issues = store.validate(records)
        codes = [iss.code for iss in issues]
        assert "UNSORTED" in codes

    def test_duplicate_date(self):
        store = TimeSeriesStore(Path("/dev/null"), TVL_SCHEMA)
        records = [
            {"date": "2026-04-11", "total_tvl": 100.0},
            {"date": "2026-04-11", "total_tvl": 150.0},
        ]
        issues = store.validate(records)
        codes = [iss.code for iss in issues]
        assert "DUPLICATE_DATE" in codes

    def test_bound_violation(self):
        schema = TimeSeriesSchema(
            required_fields=["date", "val"],
            numeric_fields={"val": Bounds(max_exclusive=1000)},
        )
        store = TimeSeriesStore(Path("/dev/null"), schema)
        issues = store.validate([{"date": "2026-04-11", "val": 9999.0}])
        codes = [iss.code for iss in issues]
        assert "BOUND_VIOLATION" in codes

    def test_multiple_issues_in_one_call(self):
        store = TimeSeriesStore(Path("/dev/null"), TVL_SCHEMA)
        records = [
            {"date": "2026-04-12", "total_tvl": 100.0},
            {"date": "2026-04-11", "total_tvl": 0},  # ZERO_VALUE + UNSORTED
        ]
        issues = store.validate(records)
        codes = {iss.code for iss in issues}
        assert "ZERO_VALUE" in codes
        assert "UNSORTED" in codes

    def test_clean_record_has_no_issues(self):
        store = TimeSeriesStore(Path("/dev/null"), TVL_SCHEMA)
        issues = store.validate([{"date": "2026-04-11", "total_tvl": 100.0}])
        assert issues == []

    def test_negative_value_triggers_bound_violation(self):
        store = TimeSeriesStore(Path("/dev/null"), TVL_SCHEMA)
        issues = store.validate([{"date": "2026-04-11", "total_tvl": -5.0}])
        codes = [iss.code for iss in issues]
        assert "BOUND_VIOLATION" in codes

    def test_allow_null_fields_skips_error(self):
        schema = TimeSeriesSchema(
            required_fields=["date", "val"],
            numeric_fields={"val": Bounds(min_exclusive=0)},
            allow_null_fields=["val"],
        )
        store = TimeSeriesStore(Path("/dev/null"), schema)
        issues = store.validate([{"date": "2026-04-11", "val": None}])
        assert issues == []

    def test_null_field_not_in_allow_null_is_error(self):
        store = TimeSeriesStore(Path("/dev/null"), TVL_SCHEMA)
        issues = store.validate([{"date": "2026-04-11", "total_tvl": None}])
        codes = [iss.code for iss in issues]
        assert "MISSING_FIELD" in codes

    def test_none_date_is_error(self):
        store = TimeSeriesStore(Path("/dev/null"), TVL_SCHEMA)
        issues = store.validate([{"date": None, "total_tvl": 100}])
        codes = [iss.code for iss in issues]
        assert "MISSING_FIELD" in codes
        errors = [iss for iss in issues if iss.severity == "error"]
        assert len(errors) >= 1

    def test_append_none_date_returns_skip_without_file_write(self, tmp_path):
        path = tmp_path / "history.json"
        write_records(path, [{"date": "2026-04-10", "total_tvl": 100.0}])
        original = path.read_text(encoding="utf-8")
        store = TimeSeriesStore(path, TVL_SCHEMA)
        result = store.append({"date": None, "total_tvl": 100}, on_invalid="skip")
        assert result.ok is False
        assert path.read_text(encoding="utf-8") == original

    def test_append_none_date_raises_when_on_invalid_raise(self, tmp_path):
        store = make_store(tmp_path)
        with pytest.raises(ValueError, match="null"):
            store.append({"date": None, "total_tvl": 100}, on_invalid="raise")


# ---------------------------------------------------------------------------
# load
# ---------------------------------------------------------------------------


class TestLoad:
    def test_missing_file_returns_empty(self, tmp_path):
        store = make_store(tmp_path)
        assert store.load() == []

    def test_load_raw_without_validate(self, tmp_path):
        """validate=False returns records including invalid ones."""
        path = tmp_path / "history.json"
        records = [
            {"date": "2026-04-12", "total_tvl": 200.0},
            {"date": "2026-04-11", "total_tvl": 0},  # invalid
        ]
        write_records(path, records)
        store = TimeSeriesStore(path, TVL_SCHEMA)
        loaded = store.load(validate=False)
        assert len(loaded) == 2  # raw — no filtering

    def test_load_with_validate_filters_errors(self, tmp_path):
        """validate=True filters out error-level records."""
        path = tmp_path / "history.json"
        records = [
            {"date": "2026-04-10", "total_tvl": 100.0},
            {"date": "2026-04-11", "total_tvl": 0},  # ZERO_VALUE error
        ]
        write_records(path, records)
        store = TimeSeriesStore(path, TVL_SCHEMA)
        loaded = store.load(validate=True)
        assert len(loaded) == 1
        assert loaded[0]["date"] == "2026-04-10"

    def test_load_does_not_modify_file(self, tmp_path):
        """load(validate=True) must not alter the file."""
        path = tmp_path / "history.json"
        records = [{"date": "2026-04-11", "total_tvl": 0}]
        write_records(path, records)
        original = path.read_text(encoding="utf-8")
        store = TimeSeriesStore(path, TVL_SCHEMA)
        store.load(validate=True)
        assert path.read_text(encoding="utf-8") == original


# ---------------------------------------------------------------------------
# append
# ---------------------------------------------------------------------------


class TestAppend:
    def test_append_to_nonexistent_file_creates_it(self, tmp_path):
        store = make_store(tmp_path)
        result = store.append({"date": "2026-04-10", "total_tvl": 100.0})
        assert result.ok is True
        path = tmp_path / "history.json"
        assert path.exists()
        data = json.loads(path.read_text())
        assert len(data) == 1

    def test_append_to_existing_file(self, tmp_path):
        path = tmp_path / "history.json"
        write_records(path, [{"date": "2026-04-10", "total_tvl": 100.0}])
        store = TimeSeriesStore(path, TVL_SCHEMA)
        result = store.append({"date": "2026-04-11", "total_tvl": 200.0})
        assert result.ok is True
        data = json.loads(path.read_text())
        assert len(data) == 2

    def test_append_invalid_skip_does_not_modify_file(self, tmp_path):
        path = tmp_path / "history.json"
        write_records(path, [{"date": "2026-04-10", "total_tvl": 100.0}])
        original = path.read_text(encoding="utf-8")
        store = TimeSeriesStore(path, TVL_SCHEMA)
        result = store.append({"date": "2026-04-11", "total_tvl": 0}, on_invalid="skip")
        assert result.ok is False
        assert result.reason is not None
        assert path.read_text(encoding="utf-8") == original

    def test_append_invalid_raise_raises_value_error(self, tmp_path):
        store = make_store(tmp_path)
        with pytest.raises(ValueError, match="0"):
            store.append({"date": "2026-04-11", "total_tvl": 0}, on_invalid="raise")

    def test_append_duplicate_date_last_wins(self, tmp_path):
        """Duplicate date — the new record replaces the old one."""
        path = tmp_path / "history.json"
        write_records(path, [{"date": "2026-04-11", "total_tvl": 50.0}])
        store = TimeSeriesStore(path, TVL_SCHEMA)
        result = store.append({"date": "2026-04-11", "total_tvl": 150.0})
        assert result.ok is True
        data = json.loads(path.read_text())
        assert len(data) == 1
        assert data[0]["total_tvl"] == 150.0

    def test_append_max_entries_trims_oldest(self, tmp_path):
        schema = TimeSeriesSchema(
            required_fields=["date", "total_tvl"],
            numeric_fields={"total_tvl": Bounds(min_exclusive=0)},
            max_entries=3,
        )
        path = tmp_path / "history.json"
        records = [
            {"date": "2026-04-08", "total_tvl": 1.0},
            {"date": "2026-04-09", "total_tvl": 2.0},
            {"date": "2026-04-10", "total_tvl": 3.0},
        ]
        write_records(path, records)
        store = TimeSeriesStore(path, schema)
        store.append({"date": "2026-04-11", "total_tvl": 4.0})
        data = json.loads(path.read_text())
        assert len(data) == 3
        dates = [r["date"] for r in data]
        assert "2026-04-08" not in dates
        assert "2026-04-11" in dates

    def test_append_writes_atomically(self, tmp_path):
        """Result file should be valid JSON after append."""
        store = make_store(tmp_path)
        store.append({"date": "2026-04-10", "total_tvl": 100.0})
        path = tmp_path / "history.json"
        data = json.loads(path.read_text())
        assert isinstance(data, list)

    def test_append_sorts_result(self, tmp_path):
        """Records in file should be sorted by date after append."""
        path = tmp_path / "history.json"
        write_records(path, [{"date": "2026-04-12", "total_tvl": 200.0}])
        store = TimeSeriesStore(path, TVL_SCHEMA)
        store.append({"date": "2026-04-10", "total_tvl": 100.0})
        data = json.loads(path.read_text())
        dates = [r["date"] for r in data]
        assert dates == sorted(dates)


# ---------------------------------------------------------------------------
# compact
# ---------------------------------------------------------------------------


class TestCompact:
    def test_compact_nonexistent_file(self, tmp_path):
        store = make_store(tmp_path)
        report = store.compact()
        assert report.final_count == 0
        assert report.removed_invalid == 0
        assert report.removed_duplicates == 0

    def test_compact_removes_zero_values(self, tmp_path):
        path = tmp_path / "history.json"
        write_records(
            path,
            [
                {"date": "2026-04-10", "total_tvl": 100.0},
                {"date": "2026-04-11", "total_tvl": 0},
            ],
        )
        store = TimeSeriesStore(path, TVL_SCHEMA)
        report = store.compact()
        assert report.removed_invalid == 1
        assert report.final_count == 1
        data = json.loads(path.read_text())
        assert all(r["total_tvl"] > 0 for r in data)

    def test_compact_removes_duplicates_last_wins(self, tmp_path):
        """Duplicate date: last record wins, matching fix_defi_tvl_history contract."""
        path = tmp_path / "history.json"
        write_records(
            path,
            [
                {"date": "2026-04-11", "total_tvl": 50.0},
                {"date": "2026-04-11", "total_tvl": 150.0},
            ],
        )
        store = TimeSeriesStore(path, TVL_SCHEMA)
        report = store.compact()
        assert report.removed_duplicates == 1
        data = json.loads(path.read_text())
        assert len(data) == 1
        assert data[0]["total_tvl"] == 150.0

    def test_compact_resorts(self, tmp_path):
        path = tmp_path / "history.json"
        write_records(
            path,
            [
                {"date": "2026-04-15", "total_tvl": 300.0},
                {"date": "2026-04-10", "total_tvl": 100.0},
                {"date": "2026-04-12", "total_tvl": 200.0},
            ],
        )
        store = TimeSeriesStore(path, TVL_SCHEMA)
        report = store.compact()
        assert report.resorted is True
        data = json.loads(path.read_text())
        dates = [r["date"] for r in data]
        assert dates == sorted(dates)

    def test_compact_idempotent(self, tmp_path):
        """Calling compact twice produces identical results."""
        path = tmp_path / "history.json"
        write_records(
            path,
            [
                {"date": "2026-04-15", "total_tvl": 300.0},
                {"date": "2026-04-10", "total_tvl": 100.0},
                {"date": "2026-04-11", "total_tvl": 0},
                {"date": "2026-04-12", "total_tvl": 200.0},
                {"date": "2026-04-12", "total_tvl": 250.0},
            ],
        )
        store = TimeSeriesStore(path, TVL_SCHEMA)
        store.compact()
        first_text = path.read_text(encoding="utf-8")
        store.compact()
        second_text = path.read_text(encoding="utf-8")
        assert first_text == second_text

    def test_compact_clean_file_no_changes(self, tmp_path):
        path = tmp_path / "history.json"
        records = [
            {"date": "2026-04-10", "total_tvl": 100.0},
            {"date": "2026-04-11", "total_tvl": 200.0},
        ]
        write_records(path, records)
        store = TimeSeriesStore(path, TVL_SCHEMA)
        report = store.compact()
        assert report.removed_invalid == 0
        assert report.removed_duplicates == 0
        assert report.final_count == 2


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


class TestCLI:
    def test_check_clean_file_exit_0(self, tmp_path, monkeypatch):
        path = tmp_path / "history.json"
        write_records(path, [{"date": "2026-04-10", "total_tvl": 100.0}])
        monkeypatch.setattr(sys, "argv", ["time_series_state", "--check", str(path)])
        assert main() == 0

    def test_check_invalid_file_exit_1(self, tmp_path, monkeypatch):
        path = tmp_path / "history.json"
        write_records(path, [{"date": "2026-04-11", "total_tvl": 0}])
        monkeypatch.setattr(sys, "argv", ["time_series_state", "--check", str(path)])
        assert main() == 1

    def test_check_missing_file_exit_1(self, tmp_path, monkeypatch):
        path = tmp_path / "nonexistent.json"
        monkeypatch.setattr(sys, "argv", ["time_series_state", "--check", str(path)])
        assert main() == 1

    def test_fix_dry_run_does_not_modify_file(self, tmp_path, monkeypatch):
        path = tmp_path / "history.json"
        records = [
            {"date": "2026-04-11", "total_tvl": 0},
            {"date": "2026-04-10", "total_tvl": 100.0},
        ]
        write_records(path, records)
        original = path.read_text(encoding="utf-8")
        monkeypatch.setattr(sys, "argv", ["time_series_state", "--fix", str(path)])
        result = main()
        assert result == 0
        assert path.read_text(encoding="utf-8") == original  # unchanged

    def test_fix_apply_modifies_file(self, tmp_path, monkeypatch):
        path = tmp_path / "history.json"
        records = [
            {"date": "2026-04-11", "total_tvl": 0},
            {"date": "2026-04-10", "total_tvl": 100.0},
        ]
        write_records(path, records)
        monkeypatch.setattr(
            sys, "argv", ["time_series_state", "--fix", str(path), "--apply"]
        )
        result = main()
        assert result == 0
        data = json.loads(path.read_text())
        assert all(r["total_tvl"] > 0 for r in data)
        dates = [r["date"] for r in data]
        assert dates == sorted(dates)

    def test_fix_dry_run_clean_file_no_changes_message(self, tmp_path, monkeypatch, caplog):
        import logging

        path = tmp_path / "history.json"
        write_records(path, [{"date": "2026-04-10", "total_tvl": 100.0}])
        monkeypatch.setattr(sys, "argv", ["time_series_state", "--fix", str(path)])
        with caplog.at_level(logging.INFO):
            result = main()
        assert result == 0
        assert any("no changes" in r.message.lower() or "변경 사항 없음" in r.message for r in caplog.records)

    def test_cli_fix_dry_run_shows_resorted_false_when_already_sorted(self, tmp_path, monkeypatch, caplog):
        """Duplicate entries but already sorted — resorted must be False."""
        import logging

        path = tmp_path / "history.json"
        write_records(
            path,
            [
                {"date": "2026-04-10", "total_tvl": 100.0},
                {"date": "2026-04-10", "total_tvl": 150.0},  # duplicate, same date
                {"date": "2026-04-11", "total_tvl": 200.0},
            ],
        )
        monkeypatch.setattr(sys, "argv", ["time_series_state", "--fix", str(path)])
        with caplog.at_level(logging.INFO):
            result = main()
        assert result == 0
        # resorted must be False — after dedup, remaining dates are already in order
        log_text = " ".join(r.message for r in caplog.records)
        assert "재정렬: False" in log_text or "변경 사항 없음" in log_text

    def test_cli_fix_dry_run_shows_resorted_true_when_unsorted(self, tmp_path, monkeypatch, caplog):
        """Records in reverse order — resorted must be True."""
        import logging

        path = tmp_path / "history.json"
        write_records(
            path,
            [
                {"date": "2026-04-12", "total_tvl": 300.0},
                {"date": "2026-04-11", "total_tvl": 200.0},
                {"date": "2026-04-10", "total_tvl": 100.0},
            ],
        )
        monkeypatch.setattr(sys, "argv", ["time_series_state", "--fix", str(path)])
        with caplog.at_level(logging.INFO):
            result = main()
        assert result == 0
        log_text = " ".join(r.message for r in caplog.records)
        assert "재정렬: True" in log_text


# ---------------------------------------------------------------------------
# TimeSeriesSchema / TimeSeriesStore init guard
# ---------------------------------------------------------------------------


class TestSchemaInitGuard:
    def test_schema_without_date_field_in_required_fails_init(self):
        """date_field not in required_fields must raise ValueError at init."""
        schema = TimeSeriesSchema(
            required_fields=["total_tvl"],  # "date" deliberately omitted
            numeric_fields={"total_tvl": Bounds(min_exclusive=0)},
            date_field="date",
        )
        with pytest.raises(ValueError, match="date_field"):
            TimeSeriesStore(Path("/dev/null"), schema)
