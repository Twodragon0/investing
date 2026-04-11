"""Tests for scripts/common/signal_tracker.py.

Coverage:
- SignalTracker.record(): 저장, 덮어쓰기, btc_price 없는 경우
- SignalTracker.accuracy_report(): 승률, 버딕트별 통계
- SignalTracker._update_previous_accuracy(): 전날 정확도 역산
- SignalTracker.get_history(): 날짜 범위 필터링
- SignalTracker.format_accuracy_summary(): 마크다운 생성
- 가지치기(prune): 365일 이상 항목 제거
- 원자적 쓰기: tmp 파일 → os.replace 패턴
- 엣지 케이스: 빈 히스토리, 첫날, 데이터 누락
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from scripts.common.signal_composer import CompositeResult, SignalResult
from scripts.common.signal_tracker import (
    AccuracyReport,
    SignalSnapshot,
    SignalTracker,
    _load_history,
    _price_direction,
    _prune_old_entries,
    _save_history,
    _verdict_to_direction,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────


def make_composite_result(score: float = 65.0, verdict: str = "강세") -> CompositeResult:
    """테스트용 CompositeResult 생성 헬퍼."""
    sr = SignalResult(
        name="공포탐욕",
        raw_display="65 (탐욕)",
        normalized=0.65,
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
    """tmp_path에 히스토리 파일을 사용하는 SignalTracker."""
    history_file = str(tmp_path / "signal_history.json")
    return SignalTracker(history_path=history_file)


# ── 헬퍼 함수 테스트 ─────────────────────────────────────────────────────────


class TestHelpers:
    def test_verdict_to_direction_bullish(self):
        assert _verdict_to_direction("강세") == "상승"

    def test_verdict_to_direction_bearish(self):
        assert _verdict_to_direction("약세") == "하락"

    def test_verdict_to_direction_neutral_none(self):
        assert _verdict_to_direction("중립") is None

    def test_verdict_to_direction_mixed_none(self):
        assert _verdict_to_direction("혼조") is None

    def test_price_direction_up(self):
        assert _price_direction(2.5) == "상승"

    def test_price_direction_down(self):
        assert _price_direction(-2.5) == "하락"

    def test_price_direction_flat(self):
        assert _price_direction(0.5) == "보합"

    def test_price_direction_boundary_up(self):
        # 정확히 1.0은 보합 (> 1.0 이어야 상승)
        assert _price_direction(1.0) == "보합"

    def test_price_direction_boundary_down(self):
        assert _price_direction(-1.0) == "보합"

    def test_prune_old_entries_removes_old(self):
        entries = [
            {"date": "2020-01-01"},  # 오래된 항목
            {"date": "2099-12-31"},  # 미래 항목 (확실히 남아야 함)
        ]
        result = _prune_old_entries(entries, max_age_days=365)
        assert len(result) == 1
        assert result[0]["date"] == "2099-12-31"

    def test_prune_keeps_recent(self):
        from datetime import UTC, datetime

        today = datetime.now(UTC).strftime("%Y-%m-%d")
        entries = [{"date": today}]
        result = _prune_old_entries(entries, max_age_days=365)
        assert len(result) == 1

    def test_load_history_nonexistent(self, tmp_path):
        result = _load_history(str(tmp_path / "nonexistent.json"))
        assert result == []

    def test_load_history_corrupt(self, tmp_path):
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("NOT JSON", encoding="utf-8")
        result = _load_history(str(bad_file))
        assert result == []

    def test_load_history_wrong_type(self, tmp_path):
        bad_file = tmp_path / "bad.json"
        bad_file.write_text('{"not": "a list"}', encoding="utf-8")
        result = _load_history(str(bad_file))
        assert result == []

    def test_save_history_atomic(self, tmp_path):
        """os.replace 패턴 사용 확인: .tmp 파일이 남지 않아야 한다."""
        path = str(tmp_path / "test.json")
        _save_history(path, [{"date": "2026-03-27"}])
        assert os.path.exists(path)
        assert not os.path.exists(path + ".tmp")
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        assert len(data) == 1
        assert data[0]["date"] == "2026-03-27"

    def test_save_history_overwrites(self, tmp_path):
        path = str(tmp_path / "test.json")
        _save_history(path, [{"date": "2026-03-01"}])
        _save_history(path, [{"date": "2026-03-27"}, {"date": "2026-03-26"}])
        data = _load_history(path)
        assert len(data) == 2


# ── SignalTracker.record() 테스트 ─────────────────────────────────────────────


class TestRecord:
    def test_record_creates_entry(self, tracker):
        result = make_composite_result()
        snapshot = tracker.record(result, date="2026-03-27")
        assert snapshot.date == "2026-03-27"
        assert snapshot.composite_score == 65.0
        assert snapshot.verdict == "강세"
        assert "공포탐욕" in snapshot.signal_scores

    def test_record_persists_to_file(self, tracker):
        result = make_composite_result()
        tracker.record(result, date="2026-03-27")
        # 새 인스턴스로 로드하여 영속성 확인
        tracker2 = SignalTracker(history_path=tracker._path)
        assert len(tracker2._entries) == 1
        assert tracker2._entries[0]["date"] == "2026-03-27"

    def test_record_overwrites_same_date(self, tracker):
        tracker.record(make_composite_result(score=60.0, verdict="강세"), date="2026-03-27")
        tracker.record(make_composite_result(score=35.0, verdict="약세"), date="2026-03-27")
        assert len(tracker._entries) == 1
        assert tracker._entries[0]["composite_score"] == 35.0
        assert tracker._entries[0]["verdict"] == "약세"

    def test_record_without_btc_price(self, tracker):
        result = make_composite_result()
        snapshot = tracker.record(result, date="2026-03-27")
        assert snapshot.btc_price is None

    def test_record_with_btc_price(self, tracker):
        result = make_composite_result()
        snapshot = tracker.record(result, btc_price=95000.0, date="2026-03-27")
        assert snapshot.btc_price == 95000.0

    def test_record_returns_snapshot(self, tracker):
        result = make_composite_result()
        snapshot = tracker.record(result, date="2026-03-27")
        assert isinstance(snapshot, SignalSnapshot)
        assert snapshot.recorded_at != ""

    def test_record_multiple_days(self, tracker):
        for i, date in enumerate(["2026-03-25", "2026-03-26", "2026-03-27"]):
            tracker.record(make_composite_result(score=50.0 + i), date=date)
        assert len(tracker._entries) == 3

    def test_record_prunes_old_entries(self, tracker):
        """365일 이상 오래된 항목이 자동 제거되어야 한다."""
        # 이미 오래된 항목을 수동으로 삽입
        old_entry = {"date": "2000-01-01", "composite_score": 50.0, "verdict": "중립", "confidence": "low"}
        tracker._entries.append(old_entry)
        # record() 호출 시 prune 실행
        tracker.record(make_composite_result(), date="2026-03-27")
        dates = [e["date"] for e in tracker._entries]
        assert "2000-01-01" not in dates


# ── 정확도 업데이트 테스트 ────────────────────────────────────────────────────


class TestAccuracyUpdate:
    def test_accuracy_correct_bullish(self, tracker):
        """강세 예측 + 실제 상승 → correct=True."""
        # 전날 저장 (강세 예측, BTC 100000)
        tracker.record(make_composite_result(verdict="강세"), btc_price=100000.0, date="2026-03-26")
        # 오늘 저장 (BTC 상승)
        tracker.record(make_composite_result(), btc_price=102000.0, date="2026-03-27")
        # 전날 항목 accuracy 확인
        prev = next(e for e in tracker._entries if e["date"] == "2026-03-26")
        assert prev["accuracy"]["correct"] is True
        assert prev["accuracy"]["actual_direction"] == "상승"

    def test_accuracy_incorrect_bullish(self, tracker):
        """강세 예측 + 실제 하락 → correct=False."""
        tracker.record(make_composite_result(verdict="강세"), btc_price=100000.0, date="2026-03-26")
        tracker.record(make_composite_result(), btc_price=97000.0, date="2026-03-27")
        prev = next(e for e in tracker._entries if e["date"] == "2026-03-26")
        assert prev["accuracy"]["correct"] is False
        assert prev["accuracy"]["actual_direction"] == "하락"

    def test_accuracy_neutral_not_evaluated(self, tracker):
        """중립/혼조 예측은 정확도 평가 불가 → correct=None."""
        tracker.record(make_composite_result(verdict="중립"), btc_price=100000.0, date="2026-03-26")
        tracker.record(make_composite_result(), btc_price=105000.0, date="2026-03-27")
        prev = next(e for e in tracker._entries if e["date"] == "2026-03-26")
        assert prev["accuracy"]["correct"] is None

    def test_accuracy_no_previous_entry(self, tracker):
        """전날 항목 없으면 오늘 기록만 저장하고 오류 없이 동작해야 한다."""
        result = make_composite_result()
        # 오류 없이 완료되어야 한다
        snapshot = tracker.record(result, btc_price=90000.0, date="2026-03-27")
        assert snapshot.date == "2026-03-27"

    def test_accuracy_no_prev_btc_price(self, tracker):
        """전날 BTC 가격 없으면 정확도 평가 생략."""
        # btc_price 없이 전날 기록
        tracker.record(make_composite_result(verdict="강세"), btc_price=None, date="2026-03-26")
        tracker.record(make_composite_result(), btc_price=102000.0, date="2026-03-27")
        prev = next(e for e in tracker._entries if e["date"] == "2026-03-26")
        # accuracy 필드가 없거나 없어야 한다
        assert "accuracy" not in prev

    def test_accuracy_change_pct_stored(self, tracker):
        """가격 변동률이 저장되어야 한다."""
        tracker.record(make_composite_result(verdict="강세"), btc_price=100000.0, date="2026-03-26")
        tracker.record(make_composite_result(), btc_price=102000.0, date="2026-03-27")
        prev = next(e for e in tracker._entries if e["date"] == "2026-03-26")
        assert abs(prev["accuracy"]["actual_price_change_pct"] - 2.0) < 0.01

    def test_accuracy_flat_movement(self, tracker):
        """보합 (변동 1% 이하)은 '보합'으로 기록된다."""
        tracker.record(make_composite_result(verdict="강세"), btc_price=100000.0, date="2026-03-26")
        tracker.record(make_composite_result(), btc_price=100500.0, date="2026-03-27")  # +0.5%
        prev = next(e for e in tracker._entries if e["date"] == "2026-03-26")
        assert prev["accuracy"]["actual_direction"] == "보합"
        # 강세 예측인데 보합이면 correct=False (상승이 아니므로)
        assert prev["accuracy"]["correct"] is False


# ── AccuracyReport 테스트 ─────────────────────────────────────────────────────


class TestAccuracyReport:
    def test_empty_history_returns_zero(self, tracker):
        report = tracker.accuracy_report()
        assert isinstance(report, AccuracyReport)
        assert report.total_predictions == 0
        assert report.win_rate == 0.0

    def test_win_rate_calculation(self, tracker):
        """3예측 중 2정확: 승률 2/3."""
        # 3일치 데이터 삽입
        entries = [
            {
                "date": "2026-03-25",
                "composite_score": 70.0,
                "verdict": "강세",
                "accuracy": {"predicted_verdict": "강세", "predicted_score": 70.0, "correct": True},
            },
            {
                "date": "2026-03-26",
                "composite_score": 65.0,
                "verdict": "강세",
                "accuracy": {"predicted_verdict": "강세", "predicted_score": 65.0, "correct": True},
            },
            {
                "date": "2026-03-27",
                "composite_score": 60.0,
                "verdict": "강세",
                "accuracy": {"predicted_verdict": "강세", "predicted_score": 60.0, "correct": False},
            },
        ]
        tracker._entries = entries
        report = tracker.accuracy_report()
        assert report.total_predictions == 3
        assert report.correct_predictions == 2
        assert abs(report.win_rate - 2 / 3) < 0.001

    def test_by_verdict_breakdown(self, tracker):
        """버딕트별 통계가 올바르게 집계되어야 한다."""
        entries = [
            {
                "date": "2026-03-25",
                "composite_score": 70.0,
                "verdict": "강세",
                "accuracy": {"predicted_verdict": "강세", "predicted_score": 70.0, "correct": True},
            },
            {
                "date": "2026-03-26",
                "composite_score": 35.0,
                "verdict": "약세",
                "accuracy": {"predicted_verdict": "약세", "predicted_score": 35.0, "correct": False},
            },
        ]
        tracker._entries = entries
        report = tracker.accuracy_report()
        assert "강세" in report.by_verdict
        assert report.by_verdict["강세"]["win_rate"] == 1.0
        assert report.by_verdict["약세"]["win_rate"] == 0.0

    def test_none_correct_not_counted(self, tracker):
        """correct=None 항목은 평가 불가로 집계에서 제외된다."""
        entries = [
            {
                "date": "2026-03-27",
                "composite_score": 50.0,
                "verdict": "중립",
                "accuracy": {"predicted_verdict": "중립", "predicted_score": 50.0, "correct": None},
            },
        ]
        tracker._entries = entries
        report = tracker.accuracy_report()
        assert report.total_predictions == 0

    def test_lookback_days_filter(self, tracker):
        """lookback_days 이전 항목은 집계에서 제외된다."""
        entries = [
            {
                "date": "2000-01-01",  # 매우 오래된 날짜
                "composite_score": 70.0,
                "verdict": "강세",
                "accuracy": {"predicted_verdict": "강세", "predicted_score": 70.0, "correct": True},
            },
        ]
        tracker._entries = entries
        report = tracker.accuracy_report(lookback_days=30)
        assert report.total_predictions == 0


# ── get_history() 테스트 ──────────────────────────────────────────────────────


class TestGetHistory:
    def test_empty_history(self, tracker):
        assert tracker.get_history() == []

    def test_returns_snapshots(self, tracker):
        tracker.record(make_composite_result(), date="2026-03-27")
        history = tracker.get_history(days=30)
        assert len(history) == 1
        assert isinstance(history[0], SignalSnapshot)

    def test_sorted_descending(self, tracker):
        for date in ["2026-03-25", "2026-03-27", "2026-03-26"]:
            tracker.record(make_composite_result(), date=date)
        history = tracker.get_history(days=30)
        dates = [s.date for s in history]
        assert dates == sorted(dates, reverse=True)

    def test_days_filter(self, tracker):
        """days 파라미터 범위 밖 항목은 반환하지 않는다."""
        tracker._entries = [
            {"date": "2000-01-01", "composite_score": 50.0, "verdict": "중립", "confidence": "low"},
        ]
        history = tracker.get_history(days=30)
        assert len(history) == 0


# ── format_accuracy_summary() 테스트 ─────────────────────────────────────────


class TestFormatAccuracySummary:
    def test_empty_history_returns_empty_string(self, tracker):
        summary = tracker.format_accuracy_summary()
        assert summary == ""

    def test_returns_markdown_string(self, tracker):
        tracker._entries = [
            {
                "date": "2026-03-27",
                "composite_score": 70.0,
                "verdict": "강세",
                "accuracy": {
                    "predicted_verdict": "강세",
                    "predicted_score": 70.0,
                    "correct": True,
                    "actual_direction": "상승",
                    "actual_price_change_pct": 2.5,
                },
            },
        ]
        summary = tracker.format_accuracy_summary()
        assert "신호 예측 정확도" in summary
        assert "승률" in summary
        assert "강세" in summary

    def test_includes_table_when_records_exist(self, tracker):
        tracker._entries = [
            {
                "date": "2026-03-27",
                "composite_score": 65.0,
                "verdict": "강세",
                "accuracy": {
                    "predicted_verdict": "강세",
                    "predicted_score": 65.0,
                    "correct": True,
                    "actual_direction": "상승",
                    "actual_price_change_pct": 3.0,
                },
            },
        ]
        summary = tracker.format_accuracy_summary()
        # 마크다운 테이블 헤더 포함 여부
        assert "|" in summary
