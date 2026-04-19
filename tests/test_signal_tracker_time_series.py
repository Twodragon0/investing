"""Phase 3 회귀 테스트 — signal_tracker + TimeSeriesStore 통합.

검증 항목:
- btc_price=None 허용 (MISSING_FIELD 에러 없음)
- btc_price=12345.6 정상값 기록
- max_entries=365 적용 확인
- 동일 date 중복 시 나중 우선 (last-in wins)
- accuracy 중첩 필드 존재 시 통과 (extra_fields_allowed=True)
- backfill_signal_history_btc_price.py 가 기대하는 shape 유지
"""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from scripts.common.signal_composer import CompositeResult, SignalResult
from scripts.common.signal_tracker import (
    _SIGNAL_SCHEMA,
    _SIGNAL_STORE,
    SignalTracker,
)
from scripts.common.time_series_state import TimeSeriesStore

# ── Fixtures ──────────────────────────────────────────────────────────────────


def make_composite_result(score: float = 60.0, verdict: str = "강세") -> CompositeResult:
    sr = SignalResult(
        name="공포탐욕",
        raw_display="60 (탐욕)",
        normalized=0.60,
        verdict=verdict,
        weight=0.25,
    )
    return CompositeResult(
        score=score,
        verdict=verdict,
        confidence="medium",
        confidence_label="보통",
        signal_results=[sr],
        scenarios=[],
        agreement_count=1,
        total_signals=1,
    )


@pytest.fixture
def tracker(tmp_path):
    history_file = str(tmp_path / "signal_history.json")
    return SignalTracker(history_path=history_file)


@pytest.fixture
def store(tmp_path):
    path = tmp_path / "signal_history.json"
    return TimeSeriesStore(path, _SIGNAL_SCHEMA, None)


# ── btc_price nullable 허용 테스트 ────────────────────────────────────────────


class TestBtcPriceNullable:
    def test_btc_price_none_no_validation_error(self, store, tmp_path):
        """btc_price=None 레코드가 MISSING_FIELD 에러를 발생시키지 않아야 한다."""
        record = {
            "date": "2026-04-01",
            "composite_score": 55.0,
            "verdict": "중립",
            "confidence": "low",
            "btc_price": None,
        }
        issues = store.validate([record])
        errors = [iss for iss in issues if iss.severity == "error"]
        assert errors == [], f"btc_price=None 레코드에 에러 발생: {errors}"

    def test_btc_price_none_appends_successfully(self, store):
        """btc_price=None 레코드가 append() 성공해야 한다."""
        record = {
            "date": "2026-04-01",
            "composite_score": 55.0,
            "verdict": "중립",
            "confidence": "low",
            "btc_price": None,
        }
        result = store.append(record)
        assert result.ok, f"append 실패: {result.reason}"

    def test_btc_price_none_persisted_and_reloaded(self, store):
        """btc_price=None 로 저장 후 재로드해도 None이어야 한다."""
        record = {
            "date": "2026-04-01",
            "composite_score": 55.0,
            "verdict": "중립",
            "confidence": "low",
            "btc_price": None,
        }
        store.append(record)
        loaded = store.load(validate=False)
        assert len(loaded) == 1
        assert loaded[0]["btc_price"] is None

    def test_btc_price_numeric_value_recorded(self, store):
        """btc_price=12345.6 정상값 기록 후 재로드 확인."""
        record = {
            "date": "2026-04-02",
            "composite_score": 70.0,
            "verdict": "강세",
            "confidence": "high",
            "btc_price": 12345.6,
        }
        store.append(record)
        loaded = store.load(validate=False)
        assert len(loaded) == 1
        assert loaded[0]["btc_price"] == 12345.6

    def test_tracker_record_without_btc_price_no_error(self, tracker):
        """SignalTracker.record() btc_price 없이 정상 동작."""
        result = make_composite_result()
        snapshot = tracker.record(result, btc_price=None, date="2026-04-01")
        assert snapshot.btc_price is None
        assert snapshot.date == "2026-04-01"

    def test_tracker_record_with_btc_price(self, tracker):
        """SignalTracker.record() btc_price=12345.6 정상 기록."""
        result = make_composite_result()
        snapshot = tracker.record(result, btc_price=12345.6, date="2026-04-01")
        assert snapshot.btc_price == 12345.6
        # 파일에서 재로드하여 확인
        tracker2 = SignalTracker(history_path=tracker._path)
        assert tracker2._entries[0]["btc_price"] == 12345.6


# ── max_entries=365 적용 확인 ─────────────────────────────────────────────────


class TestMaxEntries:
    def test_max_entries_trims_oldest(self, tmp_path):
        """max_entries=365 초과 시 가장 오래된 항목이 제거된다."""
        path = tmp_path / "signal_history.json"
        store = TimeSeriesStore(path, _SIGNAL_SCHEMA, None)

        # 366개 항목 추가 (날짜 순서대로)
        base = datetime(2024, 1, 1, tzinfo=UTC)
        for i in range(366):
            d = (base + timedelta(days=i)).strftime("%Y-%m-%d")
            store.append({"date": d, "composite_score": float(i), "btc_price": None})

        loaded = store.load(validate=False)
        assert len(loaded) == 365
        # 가장 오래된 항목(2024-01-01)은 제거되어야 한다
        dates = [r["date"] for r in loaded]
        assert "2024-01-01" not in dates
        assert "2024-01-02" in dates

    def test_schema_max_entries_is_365(self):
        """_SIGNAL_SCHEMA.max_entries가 365로 설정되어 있어야 한다."""
        assert _SIGNAL_SCHEMA.max_entries == 365


# ── 동일 date 중복 시 나중 우선 ───────────────────────────────────────────────


class TestDuplicateDateLastInWins:
    def test_duplicate_date_last_in_wins(self, store):
        """동일 날짜 레코드를 두 번 append 시 나중 값이 유지된다."""
        record1 = {"date": "2026-04-01", "composite_score": 50.0, "btc_price": None}
        record2 = {"date": "2026-04-01", "composite_score": 75.0, "btc_price": 90000.0}
        store.append(record1)
        store.append(record2)
        loaded = store.load(validate=False)
        assert len(loaded) == 1
        assert loaded[0]["composite_score"] == 75.0
        assert loaded[0]["btc_price"] == 90000.0

    def test_tracker_record_same_date_overwrites(self, tracker):
        """SignalTracker.record() 동일 날짜 두 번 호출 시 나중 값 유지."""
        tracker.record(make_composite_result(score=40.0, verdict="약세"), date="2026-04-01")
        tracker.record(make_composite_result(score=80.0, verdict="강세"), date="2026-04-01")
        assert len(tracker._entries) == 1
        assert tracker._entries[0]["composite_score"] == 80.0
        assert tracker._entries[0]["verdict"] == "강세"


# ── accuracy 중첩 필드 허용 (extra_fields_allowed=True) ─────────────────────


class TestExtraFieldsAllowed:
    def test_accuracy_nested_field_no_error(self, store):
        """accuracy 중첩 필드가 포함된 레코드가 에러 없이 통과해야 한다."""
        record = {
            "date": "2026-04-01",
            "composite_score": 65.0,
            "verdict": "강세",
            "confidence": "medium",
            "btc_price": 85000.0,
            "accuracy": {
                "predicted_verdict": "강세",
                "predicted_score": 65.0,
                "actual_price_change_pct": 2.5,
                "actual_direction": "상승",
                "correct": True,
                "evaluated_at": "2026-04-02T00:00:00Z",
            },
        }
        issues = store.validate([record])
        errors = [iss for iss in issues if iss.severity == "error"]
        assert errors == [], f"accuracy 필드에 에러 발생: {errors}"

    def test_schema_extra_fields_allowed_true(self):
        """_SIGNAL_SCHEMA.extra_fields_allowed가 True이어야 한다."""
        assert _SIGNAL_SCHEMA.extra_fields_allowed is True

    def test_signal_scores_nested_field_no_error(self, store):
        """signal_scores 중첩 필드도 에러 없이 통과해야 한다."""
        record = {
            "date": "2026-04-01",
            "composite_score": 55.0,
            "verdict": "중립",
            "confidence": "low",
            "btc_price": None,
            "signal_scores": {"공포탐욕": 0.5, "VIX": 0.3},
            "recorded_at": "2026-04-01T10:00:00Z",
        }
        issues = store.validate([record])
        errors = [iss for iss in issues if iss.severity == "error"]
        assert errors == [], f"signal_scores 필드에 에러 발생: {errors}"


# ── backfill_signal_history_btc_price.py 호환성 ────────────────────────────────


class TestBackfillCompatibility:
    """backfill_signal_history_btc_price.py가 기대하는 파일 shape 확인.

    backfill 스크립트는:
    - json.load()로 list[dict] 읽기
    - e["date"], e.get("btc_price"), e.get("verdict"), e.get("composite_score") 접근
    - entries[idx]["btc_price"] = price 직접 수정 후 json.dump()로 저장
    """

    def test_file_is_list_of_dicts(self, tracker, tmp_path):
        """저장된 파일이 list[dict] 형식이어야 한다."""
        tracker.record(make_composite_result(), btc_price=None, date="2026-04-01")
        with open(tracker._path, encoding="utf-8") as f:
            data = json.load(f)
        assert isinstance(data, list)
        assert all(isinstance(item, dict) for item in data)

    def test_required_fields_present(self, tracker):
        """backfill이 접근하는 필수 필드들이 존재해야 한다."""
        tracker.record(make_composite_result(score=60.0, verdict="강세"), btc_price=None, date="2026-04-01")
        with open(tracker._path, encoding="utf-8") as f:
            data = json.load(f)
        entry = data[0]
        assert "date" in entry
        assert "btc_price" in entry
        assert "verdict" in entry
        assert "composite_score" in entry

    def test_btc_price_null_in_file(self, tracker):
        """btc_price=None이 JSON에서 null로 저장되어야 한다."""
        tracker.record(make_composite_result(), btc_price=None, date="2026-04-01")
        with open(tracker._path, encoding="utf-8") as f:
            raw = f.read()
        assert '"btc_price": null' in raw

    def test_direct_write_by_backfill_script_pattern(self, tracker, tmp_path):
        """backfill 스크립트 패턴(load → modify → json.dump)이 파일을 손상시키지 않음."""
        # SignalTracker로 초기 데이터 저장
        tracker.record(make_composite_result(), btc_price=None, date="2026-04-01")

        # backfill 스크립트 패턴 시뮬레이션
        with open(tracker._path, encoding="utf-8") as f:
            entries = json.load(f)

        # btc_price 직접 수정 (backfill 스크립트 방식)
        entries[0]["btc_price"] = 85000.0
        entries[0]["backfilled_at"] = "2026-04-17T00:00:00Z"

        tmp_path_file = tracker._path + ".tmp"
        with open(tmp_path_file, "w", encoding="utf-8") as f:
            json.dump(entries, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path_file, tracker._path)

        # 수정 후 SignalTracker로 재로드하여 구조 확인
        tracker2 = SignalTracker(history_path=tracker._path)
        assert len(tracker2._entries) == 1
        assert tracker2._entries[0]["btc_price"] == 85000.0
        assert tracker2._entries[0]["date"] == "2026-04-01"
        assert tracker2._entries[0]["backfilled_at"] == "2026-04-17T00:00:00Z"

    def test_accuracy_block_shape_preserved(self, tracker):
        """accuracy 블록이 backfill 스크립트의 기대 shape을 유지해야 한다."""
        # 전날 기록 (강세 예측, BTC 100000)
        tracker.record(make_composite_result(verdict="강세"), btc_price=100000.0, date="2026-04-01")
        # 오늘 기록 (BTC 상승 → 전날 accuracy 업데이트)
        tracker.record(make_composite_result(), btc_price=102000.0, date="2026-04-02")

        with open(tracker._path, encoding="utf-8") as f:
            data = json.load(f)

        prev = next(e for e in data if e["date"] == "2026-04-01")
        assert "accuracy" in prev
        acc = prev["accuracy"]
        # backfill 스크립트가 기대하는 필드들
        assert "predicted_verdict" in acc
        assert "predicted_score" in acc
        assert "actual_price_change_pct" in acc
        assert "actual_direction" in acc
        assert "correct" in acc


# ── _SIGNAL_STORE 모듈 상수 확인 ──────────────────────────────────────────────


class TestSignalStoreModuleConstant:
    def test_signal_store_is_time_series_store_instance(self):
        """_SIGNAL_STORE가 TimeSeriesStore 인스턴스이어야 한다."""
        assert isinstance(_SIGNAL_STORE, TimeSeriesStore)

    def test_signal_schema_allow_null_fields(self):
        """_SIGNAL_SCHEMA.allow_null_fields에 btc_price가 포함되어야 한다."""
        assert "btc_price" in _SIGNAL_SCHEMA.allow_null_fields

    def test_signal_schema_date_required(self):
        """_SIGNAL_SCHEMA.required_fields에 date가 포함되어야 한다."""
        assert "date" in _SIGNAL_SCHEMA.required_fields

    def test_signal_schema_btc_price_not_required(self):
        """_SIGNAL_SCHEMA.required_fields에 btc_price가 없어야 한다."""
        assert "btc_price" not in _SIGNAL_SCHEMA.required_fields
