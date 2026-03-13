import importlib

import pytest

fmp_api = importlib.import_module("common.fmp_api")


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def test_fetch_economic_calendar_filters_high_medium(monkeypatch):
    payload = [
        {"event": "CPI", "country": "US", "date": "2026-03-10", "impact": "High", "estimate": "3.0%"},
        {"event": "PMI", "country": "US", "date": "2026-03-11", "impact": "Low", "estimate": "50"},
        {"event": "GDP", "country": "US", "date": "2026-03-12", "impact": "Medium", "estimate": "2.0%"},
    ]

    monkeypatch.setattr(fmp_api, "get_env", lambda key: "dummy-key")
    monkeypatch.setattr(fmp_api, "request_with_retry", lambda *args, **kwargs: _FakeResponse(payload))

    events = fmp_api.fetch_economic_calendar()
    assert len(events) == 2
    assert [e["event"] for e in events] == ["CPI", "GDP"]


def test_fetch_earnings_calendar_filters_small_caps(monkeypatch):
    payload = [
        {
            "symbol": "AAA",
            "date": "2026-03-10",
            "epsEstimated": 1.0,
            "revenueEstimated": 1000000000,
            "time": "bmo",
            "marketCap": 3000000000,
        },
        {
            "symbol": "BBB",
            "date": "2026-03-10",
            "epsEstimated": 0.2,
            "revenueEstimated": 10000000,
            "time": "amc",
            "marketCap": 1000000000,
        },
    ]

    monkeypatch.setattr(fmp_api, "get_env", lambda key: "dummy-key")
    monkeypatch.setattr(fmp_api, "request_with_retry", lambda *args, **kwargs: _FakeResponse(payload))

    earnings = fmp_api.fetch_earnings_calendar()
    assert len(earnings) == 1
    assert earnings[0]["symbol"] == "AAA"


def test_fetch_market_index_data_restricted_returns_empty(monkeypatch):
    monkeypatch.setattr(fmp_api, "get_env", lambda key: "dummy-key")
    monkeypatch.setattr(
        fmp_api,
        "request_with_retry",
        lambda *args, **kwargs: _FakeResponse("Restricted: upgrade your plan"),
    )

    quote = fmp_api.fetch_market_index_data("SPY")
    assert quote == {}


def test_fetch_sector_performance_sorted_desc(monkeypatch):
    payload = [
        {"sector": "Energy", "changesPercentage": "-1.20%"},
        {"sector": "Technology", "changesPercentage": "2.35%"},
        {"sector": "Utilities", "changesPercentage": "0.10%"},
    ]

    monkeypatch.setattr(fmp_api, "get_env", lambda key: "dummy-key")
    monkeypatch.setattr(fmp_api, "request_with_retry", lambda *args, **kwargs: _FakeResponse(payload))

    sectors = fmp_api.fetch_sector_performance()
    assert [s["sector"] for s in sectors] == ["Technology", "Utilities", "Energy"]


def test_fetch_sector_performance_uses_fallback_without_key(monkeypatch):
    fallback = [{"sector": "Technology", "change_pct": "1.10%"}]

    monkeypatch.setattr(fmp_api, "get_env", lambda key: "")
    monkeypatch.setattr(fmp_api, "_fetch_sector_etf_fallback", lambda: fallback)

    sectors = fmp_api.fetch_sector_performance()
    assert sectors == fallback


def test_fetch_economic_calendar_no_key_uses_forex_fallback(monkeypatch):
    fallback = [{"event": "Fed Meeting", "country": "US", "impact": "High"}]
    monkeypatch.setattr(fmp_api, "get_env", lambda key: "")
    monkeypatch.setattr(fmp_api, "_fetch_forex_factory_calendar", lambda: fallback)

    events = fmp_api.fetch_economic_calendar()
    assert events == fallback


def test_fetch_economic_calendar_request_exception_uses_fallback(monkeypatch):
    import requests as req_mod
    fallback = [{"event": "CPI", "country": "US", "impact": "High"}]
    monkeypatch.setattr(fmp_api, "get_env", lambda key: "dummy-key")
    monkeypatch.setattr(
        fmp_api, "request_with_retry", lambda *args, **kwargs: (_ for _ in ()).throw(req_mod.exceptions.ConnectionError("refused"))
    )
    monkeypatch.setattr(fmp_api, "_fetch_forex_factory_calendar", lambda: fallback)
    events = fmp_api.fetch_economic_calendar()
    assert events == fallback


def test_fetch_earnings_calendar_no_key_uses_fallback(monkeypatch):
    fallback = [{"symbol": "", "date": "2026-03-10", "title": "Company beats estimates"}]
    monkeypatch.setattr(fmp_api, "get_env", lambda key: "")
    monkeypatch.setattr(fmp_api, "_fetch_earnings_news_fallback", lambda: fallback)
    earnings = fmp_api.fetch_earnings_calendar()
    assert earnings == fallback


def test_fetch_market_index_data_no_key_returns_empty(monkeypatch):
    monkeypatch.setattr(fmp_api, "get_env", lambda key: "")
    result = fmp_api.fetch_market_index_data("SPY")
    assert result == {}


def test_fetch_market_index_data_valid_quote(monkeypatch):
    payload = [{
        "symbol": "SPY",
        "name": "SPDR S&P 500",
        "price": 500.0,
        "change": 5.0,
        "changePercentage": 1.01,
        "dayHigh": 502.0,
        "dayLow": 498.0,
        "volume": 10000000,
        "yearHigh": 520.0,
        "yearLow": 400.0,
        "marketCap": 500000000000,
        "priceAvg50": 490.0,
        "priceAvg200": 480.0,
    }]
    monkeypatch.setattr(fmp_api, "get_env", lambda key: "dummy-key")
    monkeypatch.setattr(fmp_api, "request_with_retry", lambda *args, **kwargs: _FakeResponse(payload))
    result = fmp_api.fetch_market_index_data("SPY")
    assert result["symbol"] == "SPY"
    assert result["price"] == 500.0
    assert result["change"] == 5.0


def test_fetch_market_index_data_empty_list_returns_empty(monkeypatch):
    monkeypatch.setattr(fmp_api, "get_env", lambda key: "dummy-key")
    monkeypatch.setattr(fmp_api, "request_with_retry", lambda *args, **kwargs: _FakeResponse([]))
    result = fmp_api.fetch_market_index_data("SPY")
    assert result == {}


def test_fetch_institutional_flows_no_key_returns_empty(monkeypatch):
    monkeypatch.setattr(fmp_api, "get_env", lambda key: "")
    result = fmp_api.fetch_institutional_flows("AAPL")
    assert result == []


def test_fetch_institutional_flows_valid_response(monkeypatch):
    payload = [
        {"holder": "Vanguard", "shares": 1000000, "dateReported": "2026-01-01", "change": 50000, "changeInSharesNumberPercentage": 5.0},
        {"holder": "BlackRock", "shares": 800000, "dateReported": "2026-01-01", "change": -20000, "changeInSharesNumberPercentage": -2.4},
    ]
    monkeypatch.setattr(fmp_api, "get_env", lambda key: "dummy-key")
    monkeypatch.setattr(fmp_api, "request_with_retry", lambda *args, **kwargs: _FakeResponse(payload))
    result = fmp_api.fetch_institutional_flows("AAPL")
    assert len(result) == 2
    assert result[0]["holder"] == "Vanguard"
    assert result[0]["shares"] == 1000000


def test_fetch_institutional_flows_non_list_returns_empty(monkeypatch):
    monkeypatch.setattr(fmp_api, "get_env", lambda key: "dummy-key")
    monkeypatch.setattr(fmp_api, "request_with_retry", lambda *args, **kwargs: _FakeResponse("error"))
    result = fmp_api.fetch_institutional_flows("AAPL")
    assert result == []


def test_fetch_treasury_rates_no_key_uses_fallback(monkeypatch):
    fallback = [{"maturity": "10년", "rate": 4.5, "change": None, "change_pct": None}]
    monkeypatch.setattr(fmp_api, "get_env", lambda key: "")
    monkeypatch.setattr(fmp_api, "_fetch_treasury_yfinance_fallback", lambda: fallback)
    result = fmp_api.fetch_treasury_rates()
    assert result == fallback


def test_fetch_treasury_rates_valid_response(monkeypatch):
    payload = [{"month3": 5.1, "year2": 4.8, "year5": 4.5, "year10": 4.3, "year30": 4.1}]
    monkeypatch.setattr(fmp_api, "get_env", lambda key: "dummy-key")
    monkeypatch.setattr(fmp_api, "request_with_retry", lambda *args, **kwargs: _FakeResponse(payload))
    result = fmp_api.fetch_treasury_rates()
    assert len(result) > 0
    maturities = [r["maturity"] for r in result]
    assert "10년" in maturities


def test_fetch_sector_performance_empty_list_uses_fallback(monkeypatch):
    fallback = [{"sector": "Technology", "change_pct": "1.10%"}]
    monkeypatch.setattr(fmp_api, "get_env", lambda key: "dummy-key")
    monkeypatch.setattr(fmp_api, "request_with_retry", lambda *args, **kwargs: _FakeResponse([]))
    monkeypatch.setattr(fmp_api, "_fetch_sector_etf_fallback", lambda: fallback)
    result = fmp_api.fetch_sector_performance()
    assert result == fallback
