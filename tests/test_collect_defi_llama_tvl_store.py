"""tests/test_collect_defi_llama_tvl_store.py — TVL staleness tracking 회귀 테스트.

Phase 2 요구사항:
- total_tvl=0 입력 시 파일 오염 차단
- TimeSeriesStore.append() 경유 쓰기 확인
- max_entries=30 슬라이싱
- staleness 경고 반환값이 기존 동작과 동일
"""

import importlib
import json
import os
import sys
from unittest.mock import patch

import pytest

SCRIPTS_DIR = os.path.join(os.path.dirname(__file__), "..", "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)


@pytest.fixture
def mod():
    return importlib.import_module("collect_defi_llama")


@pytest.fixture
def tvl_path(tmp_path):
    """Redirect _TVL_HISTORY_PATH to a temp file."""
    return tmp_path / "defi_tvl_history.json"


# ---------------------------------------------------------------------------
# C1: total_tvl=0 차단 — 파일 오염 재발 방지 핵심 회귀
# ---------------------------------------------------------------------------


class TestZeroTvlBlocked:
    def test_zero_tvl_does_not_create_file(self, mod, tvl_path, monkeypatch):
        """total_tvl=0 → store.append() 실패 → 파일 생성 안 됨."""
        monkeypatch.setattr(mod, "_TVL_HISTORY_PATH", str(tvl_path))
        result = mod._check_tvl_staleness([], "2026-04-17")
        assert result is None
        assert not tvl_path.exists(), "파일이 생성되면 안 됨 (total_tvl=0 오염)"

    def test_zero_tvl_does_not_overwrite_existing_file(self, mod, tvl_path, monkeypatch):
        """기존 파일에 total_tvl=0을 덮어쓰지 않아야 함."""
        existing = [{"date": "2026-04-16", "total_tvl": 100.0}]
        tvl_path.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
        monkeypatch.setattr(mod, "_TVL_HISTORY_PATH", str(tvl_path))

        mod._check_tvl_staleness([], "2026-04-17")

        data = json.loads(tvl_path.read_text(encoding="utf-8"))
        assert all(r["total_tvl"] > 0 for r in data), "0 값이 파일에 들어가면 안 됨"

    def test_negative_tvl_does_not_write(self, mod, tvl_path, monkeypatch):
        """음수 TVL 합산 결과 → 차단."""
        monkeypatch.setattr(mod, "_TVL_HISTORY_PATH", str(tvl_path))
        protocols = [{"tvl": -500_000_000}]
        result = mod._check_tvl_staleness(protocols, "2026-04-17")
        assert result is None
        assert not tvl_path.exists()

    def test_zero_tvl_logs_warning(self, mod, tvl_path, monkeypatch):
        """total_tvl=0 스킵 시 WARNING 로그가 발생해야 함."""
        monkeypatch.setattr(mod, "_TVL_HISTORY_PATH", str(tvl_path))
        with patch.object(mod.logger, "warning") as mock_warn:
            mod._check_tvl_staleness([], "2026-04-17")
        mock_warn.assert_called_once()
        assert "스킵" in mock_warn.call_args[0][0]


# ---------------------------------------------------------------------------
# 정상 값 → TimeSeriesStore.append() 경유 기록
# ---------------------------------------------------------------------------


class TestNormalAppend:
    def test_valid_tvl_creates_file(self, mod, tvl_path, monkeypatch):
        """정상 TVL 값 → 파일 생성 확인."""
        monkeypatch.setattr(mod, "_TVL_HISTORY_PATH", str(tvl_path))
        protocols = [{"tvl": 247_985_919_043.14}]
        mod._check_tvl_staleness(protocols, "2026-04-17")
        assert tvl_path.exists()

    def test_valid_tvl_is_recorded(self, mod, tvl_path, monkeypatch):
        """정상 TVL 값이 파일에 정확히 기록되어야 함."""
        monkeypatch.setattr(mod, "_TVL_HISTORY_PATH", str(tvl_path))
        protocols = [{"tvl": 1_000_000.0}, {"tvl": 2_000_000.0}]
        mod._check_tvl_staleness(protocols, "2026-04-17")
        data = json.loads(tvl_path.read_text(encoding="utf-8"))
        assert len(data) == 1
        assert data[0]["date"] == "2026-04-17"
        assert data[0]["total_tvl"] == pytest.approx(3_000_000.0, rel=1e-6)

    def test_same_date_overwritten(self, mod, tvl_path, monkeypatch):
        """동일 날짜 재실행 시 마지막 값으로 교체 (last-in wins)."""
        monkeypatch.setattr(mod, "_TVL_HISTORY_PATH", str(tvl_path))
        protocols_v1 = [{"tvl": 1_000_000.0}]
        protocols_v2 = [{"tvl": 2_000_000.0}]
        mod._check_tvl_staleness(protocols_v1, "2026-04-17")
        mod._check_tvl_staleness(protocols_v2, "2026-04-17")
        data = json.loads(tvl_path.read_text(encoding="utf-8"))
        assert len(data) == 1
        assert data[0]["total_tvl"] == pytest.approx(2_000_000.0)

    def test_multiple_dates_sorted(self, mod, tvl_path, monkeypatch):
        """여러 날짜가 오름차순으로 정렬되어 저장됨."""
        monkeypatch.setattr(mod, "_TVL_HISTORY_PATH", str(tvl_path))
        mod._check_tvl_staleness([{"tvl": 200_000.0}], "2026-04-15")
        mod._check_tvl_staleness([{"tvl": 300_000.0}], "2026-04-17")
        mod._check_tvl_staleness([{"tvl": 100_000.0}], "2026-04-13")
        data = json.loads(tvl_path.read_text(encoding="utf-8"))
        dates = [r["date"] for r in data]
        assert dates == sorted(dates)


# ---------------------------------------------------------------------------
# max_entries=30 슬라이싱
# ---------------------------------------------------------------------------


class TestMaxEntries:
    def test_31st_entry_drops_oldest(self, mod, tvl_path, monkeypatch):
        """31개 기록 시 가장 오래된 것이 제거되어 30개 유지."""
        monkeypatch.setattr(mod, "_TVL_HISTORY_PATH", str(tvl_path))
        # 30개 기존 항목
        existing = [
            {"date": f"2026-0{1 + i // 31:01d}-{(i % 28) + 1:02d}", "total_tvl": float(100 + i)} for i in range(30)
        ]
        # 날짜 겹침 없이 단순하게 구성
        existing = [{"date": f"2026-01-{i + 1:02d}", "total_tvl": float(100 + i)} for i in range(30)]
        tvl_path.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")

        # 31번째 추가
        mod._check_tvl_staleness([{"tvl": 999_000.0}], "2026-02-28")
        data = json.loads(tvl_path.read_text(encoding="utf-8"))
        assert len(data) == 30

    def test_31st_entry_oldest_removed(self, mod, tvl_path, monkeypatch):
        """30개 유지 시 제일 이른 날짜(가장 오래된)가 제거됨."""
        monkeypatch.setattr(mod, "_TVL_HISTORY_PATH", str(tvl_path))
        existing = [{"date": f"2026-01-{i + 1:02d}", "total_tvl": float(100 + i)} for i in range(30)]
        tvl_path.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")

        mod._check_tvl_staleness([{"tvl": 999_000.0}], "2026-02-28")
        data = json.loads(tvl_path.read_text(encoding="utf-8"))
        dates = [r["date"] for r in data]
        assert "2026-01-01" not in dates, "가장 오래된 항목이 제거되어야 함"
        assert "2026-02-28" in dates


# ---------------------------------------------------------------------------
# staleness 경고 반환값 — 기존 외부 행동 보존
# ---------------------------------------------------------------------------


class TestStalenessWarningBehavior:
    def _populate(self, mod, tvl_path, monkeypatch, dates_tvl):
        """주어진 (date, tvl) 목록으로 파일을 채우고 반환값을 수집."""
        monkeypatch.setattr(mod, "_TVL_HISTORY_PATH", str(tvl_path))
        result = None
        for date, tvl in dates_tvl:
            result = mod._check_tvl_staleness([{"tvl": tvl}], date)
        return result

    def test_returns_none_when_too_few_entries(self, mod, tvl_path, monkeypatch):
        """_TVL_STALE_DAYS보다 적은 기록 → None 반환."""
        monkeypatch.setattr(mod, "_TVL_HISTORY_PATH", str(tvl_path))
        monkeypatch.setattr(mod, "_TVL_STALE_DAYS", 3)
        result = mod._check_tvl_staleness([{"tvl": 100_000.0}], "2026-04-17")
        assert result is None

    def test_returns_none_when_values_differ(self, mod, tvl_path, monkeypatch):
        """최근 stale_days 항목의 TVL이 다르면 None 반환."""
        monkeypatch.setattr(mod, "_TVL_HISTORY_PATH", str(tvl_path))
        monkeypatch.setattr(mod, "_TVL_STALE_DAYS", 3)
        pairs = [
            ("2026-04-15", 100_000.0),
            ("2026-04-16", 200_000.0),
            ("2026-04-17", 300_000.0),
        ]
        result = self._populate(mod, tvl_path, monkeypatch, pairs)
        assert result is None

    def test_returns_warning_string_when_stale(self, mod, tvl_path, monkeypatch):
        """최근 stale_days 항목 TVL이 동일하면 경고 문자열 반환."""
        monkeypatch.setattr(mod, "_TVL_HISTORY_PATH", str(tvl_path))
        monkeypatch.setattr(mod, "_TVL_STALE_DAYS", 3)
        same_tvl = 247_985_919_043.14
        pairs = [
            ("2026-04-15", same_tvl),
            ("2026-04-16", same_tvl),
            ("2026-04-17", same_tvl),
        ]
        result = self._populate(mod, tvl_path, monkeypatch, pairs)
        assert result is not None
        assert "캐시 경고" in result
        assert "2026-04-15" in result
        assert "2026-04-17" in result

    def test_warning_contains_formatted_tvl(self, mod, tvl_path, monkeypatch):
        """경고 문자열에 포맷된 TVL 값 포함."""
        monkeypatch.setattr(mod, "_TVL_HISTORY_PATH", str(tvl_path))
        monkeypatch.setattr(mod, "_TVL_STALE_DAYS", 3)
        same_tvl = 247_985_919_043.14
        pairs = [
            ("2026-04-15", same_tvl),
            ("2026-04-16", same_tvl),
            ("2026-04-17", same_tvl),
        ]
        result = self._populate(mod, tvl_path, monkeypatch, pairs)
        # _format_tvl(247985919043.14) == "$248.0B" (approx)
        assert "$" in result

    def test_no_stale_warning_when_one_zero_blocked(self, mod, tvl_path, monkeypatch):
        """0 기록이 차단되어 stale_days에 못 미치면 경고 없음."""
        monkeypatch.setattr(mod, "_TVL_HISTORY_PATH", str(tvl_path))
        monkeypatch.setattr(mod, "_TVL_STALE_DAYS", 3)
        # 2일치 유효값 + 1일치 zero(차단) → 2개만 기록 → 경고 없음
        mod._check_tvl_staleness([{"tvl": 100_000.0}], "2026-04-15")
        mod._check_tvl_staleness([{"tvl": 100_000.0}], "2026-04-16")
        result = mod._check_tvl_staleness([], "2026-04-17")  # zero → 차단
        assert result is None
