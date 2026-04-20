"""tests/test_fix_defi_tvl_history.py — fix_defi_tvl_history 단위 테스트."""

import json
import sys

import fix_defi_tvl_history as fdh

# ---------------------------------------------------------------------------
# clean_history
# ---------------------------------------------------------------------------


class TestCleanHistory:
    def test_removes_zero_tvl(self):
        records = [
            {"date": "2026-04-10", "total_tvl": 100.0},
            {"date": "2026-04-11", "total_tvl": 0},
        ]
        cleaned, removed_zero, removed_dup = fdh.clean_history(records)
        assert removed_zero == 1
        assert len(cleaned) == 1
        assert cleaned[0]["date"] == "2026-04-10"

    def test_removes_negative_tvl(self):
        records = [
            {"date": "2026-04-10", "total_tvl": -5.0},
            {"date": "2026-04-12", "total_tvl": 200.0},
        ]
        cleaned, removed_zero, _ = fdh.clean_history(records)
        assert removed_zero == 1
        assert cleaned[0]["total_tvl"] == 200.0

    def test_sorts_by_date_ascending(self):
        records = [
            {"date": "2026-04-15", "total_tvl": 300.0},
            {"date": "2026-04-10", "total_tvl": 100.0},
            {"date": "2026-04-12", "total_tvl": 200.0},
        ]
        cleaned, _, _ = fdh.clean_history(records)
        dates = [r["date"] for r in cleaned]
        assert dates == sorted(dates)

    def test_deduplicates_same_date_keeps_last(self):
        # 같은 날짜가 두 번 나올 때 나중 레코드(리스트 후위)를 유지
        records = [
            {"date": "2026-04-11", "total_tvl": 50.0},
            {"date": "2026-04-11", "total_tvl": 150.0},
        ]
        cleaned, _, removed_dup = fdh.clean_history(records)
        assert removed_dup == 1
        assert len(cleaned) == 1
        assert cleaned[0]["total_tvl"] == 150.0

    def test_deduplicates_zero_and_nonzero_same_date(self):
        # zero가 먼저, 비-0이 나중이면 비-0 유지
        records = [
            {"date": "2026-04-11", "total_tvl": 0},
            {"date": "2026-04-11", "total_tvl": 99.0},
        ]
        cleaned, removed_zero, removed_dup = fdh.clean_history(records)
        # zero는 필터에서 먼저 제거됨, 중복도 없음
        assert removed_zero == 1
        assert removed_dup == 0
        assert cleaned[0]["total_tvl"] == 99.0

    def test_no_changes_when_clean(self):
        records = [
            {"date": "2026-04-10", "total_tvl": 100.0},
            {"date": "2026-04-11", "total_tvl": 200.0},
        ]
        cleaned, removed_zero, removed_dup = fdh.clean_history(records)
        assert removed_zero == 0
        assert removed_dup == 0
        assert len(cleaned) == 2

    def test_empty_list(self):
        cleaned, removed_zero, removed_dup = fdh.clean_history([])
        assert cleaned == []
        assert removed_zero == 0
        assert removed_dup == 0


# ---------------------------------------------------------------------------
# load_history / save_history
# ---------------------------------------------------------------------------


class TestLoadSaveHistory:
    def test_round_trip(self, tmp_path):
        records = [{"date": "2026-04-10", "total_tvl": 123.45}]
        target = tmp_path / "history.json"
        fdh.save_history(target, records)
        loaded = fdh.load_history(target)
        assert loaded == records

    def test_save_produces_trailing_newline(self, tmp_path):
        target = tmp_path / "history.json"
        fdh.save_history(target, [{"date": "2026-04-10", "total_tvl": 1.0}])
        assert target.read_text(encoding="utf-8").endswith("\n")

    def test_save_valid_json(self, tmp_path):
        target = tmp_path / "history.json"
        fdh.save_history(target, [{"date": "2026-04-10", "total_tvl": 1.0}])
        # json.load가 예외 없이 파싱되어야 함
        with target.open(encoding="utf-8") as fh:
            data = json.load(fh)
        assert isinstance(data, list)


# ---------------------------------------------------------------------------
# main — dry-run / apply 분기
# ---------------------------------------------------------------------------


class TestMain:
    def _make_dirty_file(self, tmp_path) -> object:
        """zero 항목 포함된 테스트 파일 생성."""
        records = [
            {"date": "2026-04-17", "total_tvl": 247985919043.14},
            {"date": "2026-04-11", "total_tvl": 0},
        ]
        path = tmp_path / "defi_tvl_history.json"
        path.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
        return path

    def test_dry_run_does_not_modify_file(self, tmp_path, monkeypatch):
        path = self._make_dirty_file(tmp_path)
        original = path.read_text(encoding="utf-8")
        monkeypatch.setattr(sys, "argv", ["fix_defi_tvl_history.py", "--path", str(path)])
        result = fdh.main()
        assert result == 0
        assert path.read_text(encoding="utf-8") == original

    def test_apply_removes_zero_and_sorts(self, tmp_path, monkeypatch):
        path = self._make_dirty_file(tmp_path)
        monkeypatch.setattr(sys, "argv", ["fix_defi_tvl_history.py", "--apply", "--path", str(path)])
        result = fdh.main()
        assert result == 0
        data = json.loads(path.read_text(encoding="utf-8"))
        assert all(r["total_tvl"] > 0 for r in data)
        dates = [r["date"] for r in data]
        assert dates == sorted(dates)

    def test_returns_one_for_missing_file(self, tmp_path, monkeypatch):
        missing = tmp_path / "nonexistent.json"
        monkeypatch.setattr(sys, "argv", ["fix_defi_tvl_history.py", "--path", str(missing)])
        result = fdh.main()
        assert result == 1

    def test_returns_zero_when_already_clean(self, tmp_path, monkeypatch):
        records = [{"date": "2026-04-10", "total_tvl": 100.0}]
        path = tmp_path / "history.json"
        path.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
        monkeypatch.setattr(sys, "argv", ["fix_defi_tvl_history.py", "--path", str(path)])
        result = fdh.main()
        assert result == 0
