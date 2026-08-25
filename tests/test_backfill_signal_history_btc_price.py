"""Tests for scripts/backfill_signal_history_btc_price.py.

핵심 검증 대상:
- fetch_btc_price 3단 폴백 체인(CoinGecko → Blockchain.com → yfinance)의 순서와
  실제로 응답한 공급자 라벨(provider) 일치 여부
- 각 개별 fetcher(_fetch_coingecko/_fetch_blockchain_com/_fetch_yfinance)의
  파싱/예외 처리
- 정확도 계산(_verdict_to_direction/_price_direction/_compute_accuracy_block)
- backfill()의 dry-run/apply 분기, predecessor accuracy 삽입, 원자적 저장
- main()의 --apply 플래그 라우팅
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

import backfill_signal_history_btc_price as bfp

# ── 테스트 헬퍼 ─────────────────────────────────────────────────────────────


class _FakeResponse:
    """request_with_retry가 반환하는 requests.Response를 대신하는 더미."""

    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def json(self) -> dict:
        return self._payload


class _FakeCloseSeries:
    """yfinance DataFrame의 ``hist["Close"]`` 컬럼 대체 더미."""

    def __init__(self, value: float | None) -> None:
        self._value = value

    @property
    def iloc(self) -> list:
        return [self._value]


class _FakeHistFrame:
    """yfinance ``ticker.history(...)`` 반환값 대체 더미."""

    def __init__(self, empty: bool, close: float | None = None) -> None:
        self.empty = empty
        self._close = close

    def __getitem__(self, key: str) -> _FakeCloseSeries:
        assert key == "Close"
        return _FakeCloseSeries(self._close)


def _make_yf_stub(hist_frame: _FakeHistFrame | None = None, raise_on_history: bool = False):
    """yfinance 모듈 대체 스텁 (하우스 스타일: test_generate_market_summary.py 참고)."""

    def _history(start=None, end=None):
        if raise_on_history:
            raise RuntimeError("yfinance boom")
        return hist_frame

    ticker = type("T", (), {"history": staticmethod(_history)})()
    return type("yf", (), {"Ticker": staticmethod(lambda sym: ticker)})()


def _make_entry(
    date: str,
    verdict: str = "혼조",
    score: float = 50.0,
    btc_price: float | None = 60000.0,
) -> dict[str, Any]:
    return {
        "date": date,
        "composite_score": score,
        "verdict": verdict,
        "btc_price": btc_price,
    }


def _write_history(path, entries: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)


def _load_history(path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ── _fetch_coingecko ─────────────────────────────────────────────────────────


class TestFetchCoingecko:
    def test_success_returns_price(self, monkeypatch):
        payload = {"market_data": {"current_price": {"usd": 65000.5}}}
        monkeypatch.setattr(bfp, "request_with_retry", lambda *a, **kw: _FakeResponse(payload))
        price = bfp._fetch_coingecko("2026-04-15")
        assert price == 65000.5
        assert isinstance(price, float)

    def test_missing_price_returns_none(self, monkeypatch):
        payload = {"market_data": {"current_price": {}}}
        monkeypatch.setattr(bfp, "request_with_retry", lambda *a, **kw: _FakeResponse(payload))
        assert bfp._fetch_coingecko("2026-04-15") is None

    def test_missing_market_data_returns_none(self, monkeypatch):
        monkeypatch.setattr(bfp, "request_with_retry", lambda *a, **kw: _FakeResponse({}))
        assert bfp._fetch_coingecko("2026-04-15") is None

    def test_request_exception_returns_none(self, monkeypatch):
        def _raise(*a, **kw):
            raise ConnectionError("network down")

        monkeypatch.setattr(bfp, "request_with_retry", _raise)
        assert bfp._fetch_coingecko("2026-04-15") is None

    def test_uses_dd_mm_yyyy_date_format_in_url(self, monkeypatch):
        captured = {}

        def _capture(url, **kw):
            captured["url"] = url
            return _FakeResponse({"market_data": {"current_price": {"usd": 1.0}}})

        monkeypatch.setattr(bfp, "request_with_retry", _capture)
        bfp._fetch_coingecko("2026-04-15")
        assert "date=15-04-2026" in captured["url"]


# ── _fetch_blockchain_com ─────────────────────────────────────────────────────


class TestFetchBlockchainCom:
    def test_exact_date_match_returns_price(self, monkeypatch):
        target_dt = datetime(2026, 4, 15, 12, 0, tzinfo=UTC)
        payload = {"values": [{"x": int(target_dt.timestamp()), "y": 65000.0}]}
        monkeypatch.setattr(bfp, "request_with_retry", lambda *a, **kw: _FakeResponse(payload))
        price = bfp._fetch_blockchain_com("2026-04-15")
        assert price == 65000.0

    def test_no_exact_match_falls_back_to_last_value(self, monkeypatch):
        other_dt = datetime(2026, 4, 13, 12, 0, tzinfo=UTC)
        payload = {
            "values": [
                {"x": int(other_dt.timestamp()), "y": 60000.0},
                {"x": int(other_dt.timestamp()) + 3600, "y": 61000.0},
            ]
        }
        monkeypatch.setattr(bfp, "request_with_retry", lambda *a, **kw: _FakeResponse(payload))
        price = bfp._fetch_blockchain_com("2026-04-15")
        # 정확히 일치하는 날짜가 없으면 범위 내 마지막 값을 사용
        assert price == 61000.0

    def test_empty_values_returns_none(self, monkeypatch):
        monkeypatch.setattr(bfp, "request_with_retry", lambda *a, **kw: _FakeResponse({"values": []}))
        assert bfp._fetch_blockchain_com("2026-04-15") is None

    def test_missing_values_key_returns_none(self, monkeypatch):
        monkeypatch.setattr(bfp, "request_with_retry", lambda *a, **kw: _FakeResponse({}))
        assert bfp._fetch_blockchain_com("2026-04-15") is None

    def test_request_exception_returns_none(self, monkeypatch):
        def _raise(*a, **kw):
            raise TimeoutError("timed out")

        monkeypatch.setattr(bfp, "request_with_retry", _raise)
        assert bfp._fetch_blockchain_com("2026-04-15") is None


# ── _fetch_yfinance ────────────────────────────────────────────────────────────


class TestFetchYfinance:
    def test_import_unavailable_returns_none(self, monkeypatch):
        # sys.modules에 None을 넣으면 실제 설치 여부와 무관하게 ImportError 강제 발생
        monkeypatch.setitem(sys.modules, "yfinance", None)
        assert bfp._fetch_yfinance("2026-04-15") is None

    def test_success_returns_close_price(self, monkeypatch):
        stub = _make_yf_stub(_FakeHistFrame(empty=False, close=64500.25))
        monkeypatch.setitem(sys.modules, "yfinance", stub)
        price = bfp._fetch_yfinance("2026-04-15")
        assert price == 64500.25
        assert isinstance(price, float)

    def test_empty_history_returns_none(self, monkeypatch):
        stub = _make_yf_stub(_FakeHistFrame(empty=True))
        monkeypatch.setitem(sys.modules, "yfinance", stub)
        assert bfp._fetch_yfinance("2026-04-15") is None

    def test_ticker_history_raises_returns_none(self, monkeypatch):
        stub = _make_yf_stub(raise_on_history=True)
        monkeypatch.setitem(sys.modules, "yfinance", stub)
        assert bfp._fetch_yfinance("2026-04-15") is None


# ── fetch_btc_price — 3단 폴백 체인 ────────────────────────────────────────────


class TestFetchBtcPriceFallbackChain:
    def test_coingecko_success_short_circuits_rest_of_chain(self, monkeypatch):
        blockchain_mock = MagicMock()
        yfinance_mock = MagicMock()
        monkeypatch.setattr(bfp, "_fetch_coingecko", lambda d: 65000.0)
        monkeypatch.setattr(bfp, "_fetch_blockchain_com", blockchain_mock)
        monkeypatch.setattr(bfp, "_fetch_yfinance", yfinance_mock)

        price, source = bfp.fetch_btc_price("2026-04-15")

        assert price == 65000.0
        assert source == "CoinGecko"
        blockchain_mock.assert_not_called()
        yfinance_mock.assert_not_called()

    def test_falls_through_to_blockchain_when_coingecko_fails(self, monkeypatch):
        yfinance_mock = MagicMock()
        monkeypatch.setattr(bfp, "_fetch_coingecko", lambda d: None)
        monkeypatch.setattr(bfp, "_fetch_blockchain_com", lambda d: 52000.0)
        monkeypatch.setattr(bfp, "_fetch_yfinance", yfinance_mock)

        price, source = bfp.fetch_btc_price("2026-04-15")

        assert price == 52000.0
        assert source == "Blockchain.com"
        yfinance_mock.assert_not_called()

    def test_falls_through_to_yfinance_when_first_two_fail(self, monkeypatch):
        monkeypatch.setattr(bfp, "_fetch_coingecko", lambda d: None)
        monkeypatch.setattr(bfp, "_fetch_blockchain_com", lambda d: None)
        monkeypatch.setattr(bfp, "_fetch_yfinance", lambda d: 71234.5)

        price, source = bfp.fetch_btc_price("2026-04-15")

        assert price == 71234.5
        assert source == "yfinance"

    def test_all_providers_fail_returns_none_and_none_source(self, monkeypatch):
        monkeypatch.setattr(bfp, "_fetch_coingecko", lambda d: None)
        monkeypatch.setattr(bfp, "_fetch_blockchain_com", lambda d: None)
        monkeypatch.setattr(bfp, "_fetch_yfinance", lambda d: None)

        price, source = bfp.fetch_btc_price("2026-04-15")

        assert price is None
        assert source == "none"

    def test_source_label_matches_provider_that_actually_answered(self, monkeypatch):
        """세 값이 모두 다를 때 반환된 price가 실제로 응답한 provider의 값과 일치해야 한다."""
        monkeypatch.setattr(bfp, "_fetch_coingecko", lambda d: None)
        monkeypatch.setattr(bfp, "_fetch_blockchain_com", lambda d: 11111.0)
        monkeypatch.setattr(bfp, "_fetch_yfinance", lambda d: 99999.0)

        price, source = bfp.fetch_btc_price("2026-04-15")

        # yfinance 값(99999.0)이 아니라 실제로 응답한 Blockchain.com 값이어야 함
        assert price == 11111.0
        assert source == "Blockchain.com"


# ── _verdict_to_direction ─────────────────────────────────────────────────────


class TestVerdictToDirection:
    def test_bullish_maps_to_up(self):
        assert bfp._verdict_to_direction("강세") == "상승"

    def test_bearish_maps_to_down(self):
        assert bfp._verdict_to_direction("약세") == "하락"

    def test_mixed_maps_to_none(self):
        assert bfp._verdict_to_direction("혼조") is None

    def test_neutral_maps_to_none(self):
        assert bfp._verdict_to_direction("중립") is None

    def test_empty_string_maps_to_none(self):
        assert bfp._verdict_to_direction("") is None


# ── _price_direction ──────────────────────────────────────────────────────────


class TestPriceDirection:
    def test_above_positive_threshold_is_up(self):
        assert bfp._price_direction(1.5) == "상승"

    def test_below_negative_threshold_is_down(self):
        assert bfp._price_direction(-1.5) == "하락"

    def test_exactly_positive_threshold_is_flat(self):
        assert bfp._price_direction(1.0) == "보합"

    def test_exactly_negative_threshold_is_flat(self):
        assert bfp._price_direction(-1.0) == "보합"

    def test_zero_is_flat(self):
        assert bfp._price_direction(0.0) == "보합"


# ── _compute_accuracy_block ────────────────────────────────────────────────────


class TestComputeAccuracyBlock:
    def test_bullish_prediction_correct_when_price_rises(self):
        prev_entry = {"btc_price": 60000.0, "verdict": "강세", "composite_score": 70.0}
        block = bfp._compute_accuracy_block(prev_entry, today_btc_price=65000.0)

        assert block["predicted_verdict"] == "강세"
        assert block["predicted_score"] == 70.0
        assert block["actual_direction"] == "상승"
        assert block["correct"] is True

    def test_bearish_prediction_correct_when_price_falls(self):
        prev_entry = {"btc_price": 60000.0, "verdict": "약세", "composite_score": 30.0}
        block = bfp._compute_accuracy_block(prev_entry, today_btc_price=55000.0)

        assert block["actual_direction"] == "하락"
        assert block["correct"] is True

    def test_bullish_prediction_incorrect_when_price_falls(self):
        prev_entry = {"btc_price": 60000.0, "verdict": "강세", "composite_score": 70.0}
        block = bfp._compute_accuracy_block(prev_entry, today_btc_price=55000.0)

        assert block["actual_direction"] == "하락"
        assert block["correct"] is False

    def test_mixed_verdict_yields_none_correct(self):
        prev_entry = {"btc_price": 60000.0, "verdict": "혼조", "composite_score": 50.0}
        block = bfp._compute_accuracy_block(prev_entry, today_btc_price=65000.0)

        assert block["correct"] is None

    def test_change_pct_rounded_to_4_decimals(self):
        prev_entry = {"btc_price": 60000.0, "verdict": "혼조"}
        block = bfp._compute_accuracy_block(prev_entry, today_btc_price=65000.0)
        # (65000 - 60000) / 60000 * 100 = 8.33333...
        assert block["actual_price_change_pct"] == round((65000.0 - 60000.0) / 60000.0 * 100, 4)

    def test_missing_composite_score_defaults_to_zero(self):
        prev_entry = {"btc_price": 60000.0, "verdict": "혼조"}
        block = bfp._compute_accuracy_block(prev_entry, today_btc_price=61000.0)
        assert block["predicted_score"] == 0.0

    def test_evaluated_at_matches_module_now_utc(self):
        prev_entry = {"btc_price": 60000.0, "verdict": "혼조"}
        block = bfp._compute_accuracy_block(prev_entry, today_btc_price=61000.0)
        assert block["evaluated_at"] == bfp._NOW_UTC


# ── load_history / save_history ───────────────────────────────────────────────


class TestLoadSaveHistory:
    def test_round_trip(self, tmp_path):
        entries = [_make_entry("2026-04-15", verdict="강세", btc_price=61000.0)]
        target = str(tmp_path / "history.json")
        bfp.save_history(target, entries)
        assert bfp.load_history(target) == entries

    def test_save_is_atomic_no_leftover_tmp_file(self, tmp_path):
        target = tmp_path / "history.json"
        bfp.save_history(str(target), [_make_entry("2026-04-15")])
        assert target.exists()
        assert not (tmp_path / "history.json.tmp").exists()

    def test_save_preserves_korean_text(self, tmp_path):
        target = str(tmp_path / "history.json")
        entries = [_make_entry("2026-04-15", verdict="강세")]
        bfp.save_history(target, entries)
        raw = (tmp_path / "history.json").read_text(encoding="utf-8")
        assert "강세" in raw  # ensure_ascii=False


# ── backfill — 상태 없음/조기 반환 ─────────────────────────────────────────────


class TestBackfillNoNullEntries:
    def test_prints_nothing_to_backfill(self, tmp_path, monkeypatch, capsys):
        path = tmp_path / "signal_history.json"
        entries = [_make_entry("2026-04-14", btc_price=60000.0)]
        _write_history(path, entries)
        monkeypatch.setattr(bfp, "_HISTORY_FILE", str(path))

        bfp.backfill(dry_run=True)

        out = capsys.readouterr().out
        assert "Nothing to backfill" in out

    def test_apply_does_not_touch_file(self, tmp_path, monkeypatch):
        path = tmp_path / "signal_history.json"
        entries = [_make_entry("2026-04-14", btc_price=60000.0)]
        _write_history(path, entries)
        monkeypatch.setattr(bfp, "_HISTORY_FILE", str(path))

        bfp.backfill(dry_run=False)

        assert _load_history(path) == entries


# ── backfill — dry-run ────────────────────────────────────────────────────────


class TestBackfillDryRun:
    def test_reports_found_null_dates_and_does_not_write(self, tmp_path, monkeypatch, capsys):
        path = tmp_path / "signal_history.json"
        entries = [
            _make_entry("2026-04-14", btc_price=60000.0),
            _make_entry("2026-04-15", btc_price=None),
        ]
        _write_history(path, entries)
        monkeypatch.setattr(bfp, "_HISTORY_FILE", str(path))
        monkeypatch.setattr(bfp, "fetch_btc_price", lambda d: (65000.0, "CoinGecko"))

        bfp.backfill(dry_run=True)

        out = capsys.readouterr().out
        assert "Found 1 null btc_price entries" in out
        assert "2026-04-15" in out
        assert "DRY-RUN: no changes written" in out
        # dry-run이므로 파일은 변경되지 않아야 함
        assert _load_history(path) == entries

    def test_dry_run_shows_predecessor_accuracy_preview(self, tmp_path, monkeypatch, capsys):
        path = tmp_path / "signal_history.json"
        entries = [
            _make_entry("2026-04-14", verdict="강세", score=70.0, btc_price=60000.0),
            _make_entry("2026-04-15", btc_price=None),
        ]
        _write_history(path, entries)
        monkeypatch.setattr(bfp, "_HISTORY_FILE", str(path))
        monkeypatch.setattr(bfp, "fetch_btc_price", lambda d: (65000.0, "CoinGecko"))

        bfp.backfill(dry_run=True)

        out = capsys.readouterr().out
        assert "BACKFILL 2026-04-15" in out
        assert "predecessor 2026-04-14 accuracy" in out


# ── backfill — apply ──────────────────────────────────────────────────────────


class TestBackfillApply:
    def test_applies_price_and_predecessor_accuracy(self, tmp_path, monkeypatch):
        path = tmp_path / "signal_history.json"
        entries = [
            _make_entry("2026-04-14", verdict="강세", score=70.0, btc_price=60000.0),
            _make_entry("2026-04-15", verdict="약세", score=20.0, btc_price=None),
        ]
        _write_history(path, entries)
        monkeypatch.setattr(bfp, "_HISTORY_FILE", str(path))
        monkeypatch.setattr(bfp, "fetch_btc_price", lambda d: (65000.0, "CoinGecko"))

        bfp.backfill(dry_run=False)

        reloaded = _load_history(path)
        assert reloaded[1]["btc_price"] == 65000.0
        assert reloaded[1]["backfilled_at"] == bfp._NOW_UTC

        acc = reloaded[0]["accuracy"]
        assert acc["predicted_verdict"] == "강세"
        assert acc["predicted_score"] == 70.0
        assert acc["actual_direction"] == "상승"
        assert acc["correct"] is True
        assert acc["backfilled_at"] == bfp._NOW_UTC

    def test_predecessor_without_btc_price_skips_accuracy(self, tmp_path, monkeypatch):
        path = tmp_path / "signal_history.json"
        entries = [
            _make_entry("2026-04-14", btc_price=None),
            _make_entry("2026-04-15", btc_price=None),
        ]
        _write_history(path, entries)
        monkeypatch.setattr(bfp, "_HISTORY_FILE", str(path))
        monkeypatch.setattr(bfp, "fetch_btc_price", lambda d: (65000.0, "CoinGecko"))

        bfp.backfill(dry_run=False)

        reloaded = _load_history(path)
        assert "accuracy" not in reloaded[0]
        assert reloaded[1]["btc_price"] == 65000.0

    def test_no_predecessor_entry_still_backfills_price(self, tmp_path, monkeypatch):
        path = tmp_path / "signal_history.json"
        entries = [_make_entry("2026-04-20", btc_price=None)]
        _write_history(path, entries)
        monkeypatch.setattr(bfp, "_HISTORY_FILE", str(path))
        monkeypatch.setattr(bfp, "fetch_btc_price", lambda d: (72000.0, "Blockchain.com"))

        bfp.backfill(dry_run=False)

        reloaded = _load_history(path)
        assert reloaded[0]["btc_price"] == 72000.0

    def test_all_providers_fail_leaves_btc_price_null(self, tmp_path, monkeypatch, capsys):
        path = tmp_path / "signal_history.json"
        entries = [_make_entry("2026-04-15", btc_price=None)]
        _write_history(path, entries)
        monkeypatch.setattr(bfp, "_HISTORY_FILE", str(path))
        monkeypatch.setattr(bfp, "fetch_btc_price", lambda d: (None, "none"))

        bfp.backfill(dry_run=False)

        out = capsys.readouterr().out
        assert "SKIP 2026-04-15" in out
        reloaded = _load_history(path)
        assert reloaded[0]["btc_price"] is None
        assert "WARNING" in out
        assert "1 null btc_price entries remain" in out

    def test_validation_reports_zero_remaining_after_full_success(self, tmp_path, monkeypatch, capsys):
        path = tmp_path / "signal_history.json"
        entries = [_make_entry("2026-04-15", btc_price=None)]
        _write_history(path, entries)
        monkeypatch.setattr(bfp, "_HISTORY_FILE", str(path))
        monkeypatch.setattr(bfp, "fetch_btc_price", lambda d: (65000.0, "CoinGecko"))

        bfp.backfill(dry_run=False)

        out = capsys.readouterr().out
        assert "VALIDATION: 0 null btc_price entries remain." in out

    def test_prints_applied_count(self, tmp_path, monkeypatch, capsys):
        path = tmp_path / "signal_history.json"
        entries = [
            _make_entry("2026-04-14", btc_price=None),
            _make_entry("2026-04-15", btc_price=None),
        ]
        _write_history(path, entries)
        monkeypatch.setattr(bfp, "_HISTORY_FILE", str(path))
        monkeypatch.setattr(bfp, "fetch_btc_price", lambda d: (65000.0, "CoinGecko"))

        bfp.backfill(dry_run=False)

        out = capsys.readouterr().out
        assert "APPLIED: 2 entries backfilled" in out

    def test_mixed_success_and_failure_across_multiple_null_entries(self, tmp_path, monkeypatch, capsys):
        path = tmp_path / "signal_history.json"
        entries = [
            _make_entry("2026-04-14", verdict="강세", score=70.0, btc_price=None),
            _make_entry("2026-04-15", verdict="약세", score=20.0, btc_price=None),
        ]
        _write_history(path, entries)
        monkeypatch.setattr(bfp, "_HISTORY_FILE", str(path))

        fetch_map = {
            "2026-04-14": (58000.0, "CoinGecko"),
            "2026-04-15": (None, "none"),
        }
        monkeypatch.setattr(bfp, "fetch_btc_price", lambda d: fetch_map[d])

        bfp.backfill(dry_run=False)

        reloaded = _load_history(path)
        assert reloaded[0]["btc_price"] == 58000.0
        assert reloaded[1]["btc_price"] is None

        out = capsys.readouterr().out
        assert "SKIP 2026-04-15" in out
        assert "WARNING: 1 null btc_price entries remain" in out


# ── main() ────────────────────────────────────────────────────────────────────


class TestMain:
    def test_default_invokes_dry_run(self, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv", ["backfill_signal_history_btc_price.py"])
        calls = {}
        monkeypatch.setattr(bfp, "backfill", lambda dry_run: calls.setdefault("dry_run", dry_run))

        bfp.main()

        assert calls["dry_run"] is True
        out = capsys.readouterr().out
        assert "Mode: DRY-RUN" in out

    def test_apply_flag_invokes_apply_mode(self, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv", ["backfill_signal_history_btc_price.py", "--apply"])
        calls = {}
        monkeypatch.setattr(bfp, "backfill", lambda dry_run: calls.setdefault("dry_run", dry_run))

        bfp.main()

        assert calls["dry_run"] is False
        out = capsys.readouterr().out
        assert "Mode: APPLY" in out

    def test_end_to_end_apply_writes_real_history_file(self, tmp_path, monkeypatch):
        """main() → backfill() → fetch_btc_price() → save_history() 전체 경로 통합 검증."""
        path = tmp_path / "signal_history.json"
        entries = [_make_entry("2026-04-15", verdict="강세", score=80.0, btc_price=None)]
        _write_history(path, entries)
        monkeypatch.setattr(bfp, "_HISTORY_FILE", str(path))
        monkeypatch.setattr(bfp, "fetch_btc_price", lambda d: (66000.0, "CoinGecko"))
        monkeypatch.setattr(sys, "argv", ["backfill_signal_history_btc_price.py", "--apply"])

        bfp.main()

        reloaded = _load_history(path)
        assert reloaded[0]["btc_price"] == 66000.0
        assert reloaded[0]["backfilled_at"] == bfp._NOW_UTC
