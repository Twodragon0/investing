import importlib
import sys
import types
import unittest.mock as mock

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
        fmp_api,
        "request_with_retry",
        lambda *args, **kwargs: (_ for _ in ()).throw(req_mod.exceptions.ConnectionError("refused")),
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
    payload = [
        {
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
        }
    ]
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
        {
            "holder": "Vanguard",
            "shares": 1000000,
            "dateReported": "2026-01-01",
            "change": 50000,
            "changeInSharesNumberPercentage": 5.0,
        },
        {
            "holder": "BlackRock",
            "shares": 800000,
            "dateReported": "2026-01-01",
            "change": -20000,
            "changeInSharesNumberPercentage": -2.4,
        },
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


# ---------------------------------------------------------------------------
# Additional tests for coverage: lines 78-110, 140-141, 155-156, 164-188,
# 230-232, 280-282, 317-318, 323-324, 332-365, 405-406, 417-418, 426-464,
# 475-513, 518-544
# ---------------------------------------------------------------------------

# _fetch_forex_factory_calendar (lines 78-110)


def test_fetch_forex_factory_calendar_filters_high_medium(monkeypatch):
    payload = [
        {
            "title": "NFP",
            "country": "US",
            "date": "2026-03-07",
            "impact": "High",
            "forecast": "200K",
            "previous": "190K",
            "actual": "210K",
        },
        {
            "title": "PMI Flash",
            "country": "EU",
            "date": "2026-03-07",
            "impact": "Low",
            "forecast": "",
            "previous": "",
            "actual": "",
        },
        {
            "title": "CPI",
            "country": "EU",
            "date": "2026-03-08",
            "impact": "Medium",
            "forecast": "2.1",
            "previous": "2.0",
            "actual": "",
        },
    ]
    monkeypatch.setattr(fmp_api, "request_with_retry", lambda *args, **kwargs: _FakeResponse(payload))
    result = fmp_api._fetch_forex_factory_calendar()
    assert len(result) == 2
    assert result[0]["event"] == "NFP"
    assert result[1]["event"] == "CPI"
    assert result[0]["forecast"] == "200K"


def test_fetch_forex_factory_calendar_non_list_returns_empty(monkeypatch):
    monkeypatch.setattr(fmp_api, "request_with_retry", lambda *args, **kwargs: _FakeResponse({"error": "bad"}))
    result = fmp_api._fetch_forex_factory_calendar()
    assert result == []


def test_fetch_forex_factory_calendar_request_exception_returns_empty(monkeypatch):
    import requests as req_mod

    def raise_exc(*args, **kwargs):
        raise req_mod.exceptions.ConnectionError("timeout")

    monkeypatch.setattr(fmp_api, "request_with_retry", raise_exc)
    result = fmp_api._fetch_forex_factory_calendar()
    assert result == []


def test_fetch_forex_factory_calendar_empty_list(monkeypatch):
    monkeypatch.setattr(fmp_api, "request_with_retry", lambda *args, **kwargs: _FakeResponse([]))
    result = fmp_api._fetch_forex_factory_calendar()
    assert result == []


# fetch_earnings_calendar - invalid marketCap (lines 140-141)


def test_fetch_earnings_calendar_invalid_market_cap_string(monkeypatch):
    payload = [
        {
            "symbol": "XYZ",
            "date": "2026-03-10",
            "epsEstimated": 1.0,
            "revenueEstimated": 500000000,
            "time": "bmo",
            "marketCap": "not-a-number",
        }
    ]
    monkeypatch.setattr(fmp_api, "get_env", lambda key: "dummy-key")
    monkeypatch.setattr(fmp_api, "request_with_retry", lambda *args, **kwargs: _FakeResponse(payload))
    result = fmp_api.fetch_earnings_calendar()
    assert result == []


def test_fetch_earnings_calendar_none_market_cap(monkeypatch):
    payload = [
        {
            "symbol": "XYZ",
            "date": "2026-03-10",
            "epsEstimated": 1.0,
            "revenueEstimated": 500000000,
            "time": "bmo",
            "marketCap": None,
        }
    ]
    monkeypatch.setattr(fmp_api, "get_env", lambda key: "dummy-key")
    monkeypatch.setattr(fmp_api, "request_with_retry", lambda *args, **kwargs: _FakeResponse(payload))
    result = fmp_api.fetch_earnings_calendar()
    assert result == []


# fetch_earnings_calendar - RequestException fallback (lines 155-156)


def test_fetch_earnings_calendar_request_exception_uses_fallback(monkeypatch):
    import requests as req_mod

    fallback = [{"symbol": "", "date": "2026-03-10", "title": "AAPL beats estimates", "is_news_fallback": True}]

    def raise_exc(*args, **kwargs):
        raise req_mod.exceptions.Timeout("timeout")

    monkeypatch.setattr(fmp_api, "get_env", lambda key: "dummy-key")
    monkeypatch.setattr(fmp_api, "request_with_retry", raise_exc)
    monkeypatch.setattr(fmp_api, "_fetch_earnings_news_fallback", lambda: fallback)
    result = fmp_api.fetch_earnings_calendar()
    assert result == fallback


# _fetch_earnings_news_fallback (lines 164-188)


def test_fetch_earnings_news_fallback_returns_news_items(monkeypatch):
    mock_items = [
        {"title": "AAPL Q1 beats estimates", "published": "2026-03-10", "link": "https://example.com/1"},
        {"title": "MSFT revenue surge", "published": "2026-03-11", "link": "https://example.com/2"},
    ]

    def mock_fetch_rss(url, source_name, tags, limit, max_age_hours):
        return mock_items

    mock_rss_mod = types.ModuleType("common.rss_fetcher")
    mock_rss_mod.fetch_rss_feed = mock_fetch_rss
    monkeypatch.setitem(sys.modules, "common.rss_fetcher", mock_rss_mod)

    result = fmp_api._fetch_earnings_news_fallback()
    assert len(result) == 2
    assert result[0]["title"] == "AAPL Q1 beats estimates"
    assert result[0]["is_news_fallback"] is True
    assert result[0]["symbol"] == ""
    assert result[0]["eps_estimated"] == ""


def test_fetch_earnings_news_fallback_empty(monkeypatch):
    def mock_fetch_rss(url, source_name, tags, limit, max_age_hours):
        return []

    mock_rss_mod = types.ModuleType("common.rss_fetcher")
    mock_rss_mod.fetch_rss_feed = mock_fetch_rss
    monkeypatch.setitem(sys.modules, "common.rss_fetcher", mock_rss_mod)

    result = fmp_api._fetch_earnings_news_fallback()
    assert result == []


# fetch_institutional_flows - RequestException (lines 230-232)


def test_fetch_institutional_flows_request_exception_returns_empty(monkeypatch):
    import requests as req_mod

    def raise_exc(*args, **kwargs):
        raise req_mod.exceptions.ConnectionError("refused")

    monkeypatch.setattr(fmp_api, "get_env", lambda key: "dummy-key")
    monkeypatch.setattr(fmp_api, "request_with_retry", raise_exc)
    result = fmp_api.fetch_institutional_flows("AAPL")
    assert result == []


# fetch_market_index_data - RequestException (lines 280-282)


def test_fetch_market_index_data_request_exception_returns_empty(monkeypatch):
    import requests as req_mod

    def raise_exc(*args, **kwargs):
        raise req_mod.exceptions.Timeout("timed out")

    monkeypatch.setattr(fmp_api, "get_env", lambda key: "dummy-key")
    monkeypatch.setattr(fmp_api, "request_with_retry", raise_exc)
    result = fmp_api.fetch_market_index_data("SPY")
    assert result == {}


# fetch_sector_performance - _parse_change invalid value (lines 317-318)


def test_fetch_sector_performance_invalid_change_pct(monkeypatch):
    payload = [
        {"sector": "Technology", "changesPercentage": "N/A"},
        {"sector": "Energy", "changesPercentage": "2.50%"},
        {"sector": "Utilities", "changesPercentage": "invalid"},
    ]
    monkeypatch.setattr(fmp_api, "get_env", lambda key: "dummy-key")
    monkeypatch.setattr(fmp_api, "request_with_retry", lambda *args, **kwargs: _FakeResponse(payload))
    result = fmp_api.fetch_sector_performance()
    assert result[0]["sector"] == "Energy"


# fetch_sector_performance - RequestException fallback (lines 323-324)


def test_fetch_sector_performance_request_exception_uses_fallback(monkeypatch):
    import requests as req_mod

    fallback = [{"sector": "Technology", "change_pct": "1.10%"}]

    def raise_exc(*args, **kwargs):
        raise req_mod.exceptions.ConnectionError("refused")

    monkeypatch.setattr(fmp_api, "get_env", lambda key: "dummy-key")
    monkeypatch.setattr(fmp_api, "request_with_retry", raise_exc)
    monkeypatch.setattr(fmp_api, "_fetch_sector_etf_fallback", lambda: fallback)
    result = fmp_api.fetch_sector_performance()
    assert result == fallback


# _fetch_sector_etf_fallback (lines 332-365)


def test_fetch_sector_etf_fallback_no_yfinance(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name == "yfinance":
            raise ImportError("No module named 'yfinance'")
        return real_import(name, *args, **kwargs)

    with mock.patch("builtins.__import__", side_effect=mock_import):
        result = fmp_api._fetch_sector_etf_fallback()
    assert result == []


def test_fetch_sector_etf_fallback_with_yfinance(monkeypatch):
    class FakeFastInfo:
        def __init__(self, price, prev):
            self.last_price = price
            self.previous_close = prev

    class FakeTicker:
        def __init__(self, symbol):
            self._symbol = symbol
            self.fast_info = FakeFastInfo(100.0, 98.0)

    fake_yf = types.ModuleType("yfinance")
    fake_yf.Ticker = FakeTicker
    monkeypatch.setitem(sys.modules, "yfinance", fake_yf)

    result = fmp_api._fetch_sector_etf_fallback()
    assert len(result) == 11
    for item in result:
        assert "%" in item["change_pct"]
        assert item["sector"] != ""


def test_fetch_sector_etf_fallback_yfinance_exception(monkeypatch):
    class FakeTicker:
        def __init__(self, symbol):
            raise AttributeError("no data")

    fake_yf = types.ModuleType("yfinance")
    fake_yf.Ticker = FakeTicker
    monkeypatch.setitem(sys.modules, "yfinance", fake_yf)

    result = fmp_api._fetch_sector_etf_fallback()
    assert result == []


def test_fetch_sector_etf_fallback_yfinance_no_price(monkeypatch):
    class FakeFastInfo:
        last_price = None
        previous_close = 98.0

    class FakeTicker:
        def __init__(self, symbol):
            self.fast_info = FakeFastInfo()

    fake_yf = types.ModuleType("yfinance")
    fake_yf.Ticker = FakeTicker
    monkeypatch.setitem(sys.modules, "yfinance", fake_yf)

    result = fmp_api._fetch_sector_etf_fallback()
    assert result == []


# fetch_treasury_rates - invalid rate values (lines 405-406)


def test_fetch_treasury_rates_invalid_rate_value_skipped(monkeypatch):
    payload = [{"month3": "N/A", "year2": 4.8, "year5": None, "year10": 4.3, "year30": 4.1}]
    monkeypatch.setattr(fmp_api, "get_env", lambda key: "dummy-key")
    monkeypatch.setattr(fmp_api, "request_with_retry", lambda *args, **kwargs: _FakeResponse(payload))
    result = fmp_api.fetch_treasury_rates()
    maturities = [r["maturity"] for r in result]
    assert "3개월" not in maturities
    assert "5년" not in maturities
    assert "2년" in maturities
    assert "10년" in maturities


# fetch_treasury_rates - RequestException fallback (lines 417-418)


def test_fetch_treasury_rates_request_exception_uses_fallback(monkeypatch):
    import requests as req_mod

    fallback = [{"maturity": "10년", "rate": 4.5, "change": None, "change_pct": None}]

    def raise_exc(*args, **kwargs):
        raise req_mod.exceptions.ConnectionError("refused")

    monkeypatch.setattr(fmp_api, "get_env", lambda key: "dummy-key")
    monkeypatch.setattr(fmp_api, "request_with_retry", raise_exc)
    monkeypatch.setattr(fmp_api, "_fetch_treasury_yfinance_fallback", lambda: fallback)
    result = fmp_api.fetch_treasury_rates()
    assert result == fallback


def test_fetch_treasury_rates_empty_data_uses_fallback(monkeypatch):
    fallback = [{"maturity": "10년", "rate": 4.5, "change": None, "change_pct": None}]
    monkeypatch.setattr(fmp_api, "get_env", lambda key: "dummy-key")
    monkeypatch.setattr(fmp_api, "request_with_retry", lambda *args, **kwargs: _FakeResponse([]))
    monkeypatch.setattr(fmp_api, "_fetch_treasury_yfinance_fallback", lambda: fallback)
    result = fmp_api.fetch_treasury_rates()
    assert result == fallback


# _fetch_treasury_yfinance_fallback (lines 426-464)


def test_fetch_treasury_yfinance_fallback_no_yfinance(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name == "yfinance":
            raise ImportError("No module named 'yfinance'")
        return real_import(name, *args, **kwargs)

    with mock.patch("builtins.__import__", side_effect=mock_import):
        result = fmp_api._fetch_treasury_yfinance_fallback()
    assert result == []


def test_fetch_treasury_yfinance_fallback_with_data(monkeypatch):
    class FakeFastInfo:
        def __init__(self):
            self.last_price = 4.5
            self.previous_close = 4.4

    class FakeTicker:
        def __init__(self, symbol):
            self.fast_info = FakeFastInfo()

    fake_yf = types.ModuleType("yfinance")
    fake_yf.Ticker = FakeTicker
    monkeypatch.setitem(sys.modules, "yfinance", fake_yf)

    result = fmp_api._fetch_treasury_yfinance_fallback()
    assert len(result) == 4
    maturities = [r["maturity"] for r in result]
    assert "3개월" in maturities
    assert "10년" in maturities
    for r in result:
        assert r["change"] is not None
        assert r["change_pct"] is not None


def test_fetch_treasury_yfinance_fallback_no_prev_close(monkeypatch):
    class FakeFastInfo:
        def __init__(self):
            self.last_price = 4.5
            self.previous_close = None

    class FakeTicker:
        def __init__(self, symbol):
            self.fast_info = FakeFastInfo()

    fake_yf = types.ModuleType("yfinance")
    fake_yf.Ticker = FakeTicker
    monkeypatch.setitem(sys.modules, "yfinance", fake_yf)

    result = fmp_api._fetch_treasury_yfinance_fallback()
    assert len(result) == 4
    for r in result:
        assert r["change"] is None
        assert r["change_pct"] is None


def test_fetch_treasury_yfinance_fallback_no_price(monkeypatch):
    class FakeFastInfo:
        def __init__(self):
            self.last_price = None
            self.previous_close = 4.4

    class FakeTicker:
        def __init__(self, symbol):
            self.fast_info = FakeFastInfo()

    fake_yf = types.ModuleType("yfinance")
    fake_yf.Ticker = FakeTicker
    monkeypatch.setitem(sys.modules, "yfinance", fake_yf)

    result = fmp_api._fetch_treasury_yfinance_fallback()
    assert result == []


def test_fetch_treasury_yfinance_fallback_exception(monkeypatch):
    class FakeTicker:
        def __init__(self, symbol):
            raise AttributeError("no data")

    fake_yf = types.ModuleType("yfinance")
    fake_yf.Ticker = FakeTicker
    monkeypatch.setitem(sys.modules, "yfinance", fake_yf)

    result = fmp_api._fetch_treasury_yfinance_fallback()
    assert result == []


def test_fetch_treasury_yfinance_fallback_sorted_by_maturity(monkeypatch):
    calls = []

    class FakeFastInfo:
        def __init__(self, price):
            self.last_price = price
            self.previous_close = price - 0.1

    class FakeTicker:
        def __init__(self, symbol):
            calls.append(symbol)
            self.fast_info = FakeFastInfo(4.0 + len(calls) * 0.1)

    fake_yf = types.ModuleType("yfinance")
    fake_yf.Ticker = FakeTicker
    monkeypatch.setitem(sys.modules, "yfinance", fake_yf)

    result = fmp_api._fetch_treasury_yfinance_fallback()
    maturities = [r["maturity"] for r in result]
    order = {"3개월": 0, "5년": 2, "10년": 3, "30년": 4}
    indices = [order[m] for m in maturities]
    assert indices == sorted(indices)


# fetch_ipo_calendar (lines 475-513)


def test_fetch_ipo_calendar_no_key_uses_fallback(monkeypatch):
    fallback = [{"date": "2026-04-01", "company": "AcmeCorp", "symbol": "ACME", "is_news_fallback": True}]
    monkeypatch.setattr(fmp_api, "get_env", lambda key: "")
    monkeypatch.setattr(fmp_api, "_fetch_ipo_news_fallback", lambda: fallback)
    result = fmp_api.fetch_ipo_calendar()
    assert result == fallback


def test_fetch_ipo_calendar_valid_response(monkeypatch):
    payload = [
        {
            "date": "2026-04-15",
            "company": "TechCorp",
            "symbol": "TECH",
            "exchange": "NASDAQ",
            "shares": 10000000,
            "priceRange": "$10-$12",
            "marketCap": 120000000,
        },
        {
            "date": "2026-04-10",
            "company": "BioInc",
            "symbol": "BIO",
            "exchange": "NYSE",
            "shares": 5000000,
            "priceRange": "$8-$10",
            "marketCap": 50000000,
        },
    ]
    monkeypatch.setattr(fmp_api, "get_env", lambda key: "dummy-key")
    monkeypatch.setattr(fmp_api, "request_with_retry", lambda *args, **kwargs: _FakeResponse(payload))
    result = fmp_api.fetch_ipo_calendar()
    assert result[0]["date"] == "2026-04-10"
    assert result[1]["company"] == "TechCorp"
    assert result[0]["is_news_fallback"] is False
    assert len(result) == 2


def test_fetch_ipo_calendar_empty_list_uses_fallback(monkeypatch):
    fallback = [{"date": "2026-04-01", "title": "IPO news", "is_news_fallback": True}]
    monkeypatch.setattr(fmp_api, "get_env", lambda key: "dummy-key")
    monkeypatch.setattr(fmp_api, "request_with_retry", lambda *args, **kwargs: _FakeResponse([]))
    monkeypatch.setattr(fmp_api, "_fetch_ipo_news_fallback", lambda: fallback)
    result = fmp_api.fetch_ipo_calendar()
    assert result == fallback


def test_fetch_ipo_calendar_request_exception_uses_fallback(monkeypatch):
    import requests as req_mod

    fallback = [{"date": "2026-04-01", "title": "IPO news", "is_news_fallback": True}]

    def raise_exc(*args, **kwargs):
        raise req_mod.exceptions.ConnectionError("refused")

    monkeypatch.setattr(fmp_api, "get_env", lambda key: "dummy-key")
    monkeypatch.setattr(fmp_api, "request_with_retry", raise_exc)
    monkeypatch.setattr(fmp_api, "_fetch_ipo_news_fallback", lambda: fallback)
    result = fmp_api.fetch_ipo_calendar()
    assert result == fallback


# _fetch_ipo_news_fallback (lines 518-544)


def test_fetch_ipo_news_fallback_returns_items(monkeypatch):
    mock_items = [
        {"title": "AcmeCorp IPO set for April", "published": "2026-03-10", "link": "https://example.com/1"},
        {"title": "BioInc raises $50M in IPO", "published": "2026-03-11", "link": "https://example.com/2"},
    ]

    def mock_fetch_rss(url, source_name, tags, limit, max_age_hours):
        return mock_items

    mock_rss_mod = types.ModuleType("common.rss_fetcher")
    mock_rss_mod.fetch_rss_feed = mock_fetch_rss
    monkeypatch.setitem(sys.modules, "common.rss_fetcher", mock_rss_mod)

    result = fmp_api._fetch_ipo_news_fallback()
    assert len(result) == 2
    assert result[0]["title"] == "AcmeCorp IPO set for April"
    assert result[0]["is_news_fallback"] is True
    assert result[0]["company"] == ""
    assert result[0]["symbol"] == ""
    assert result[0]["exchange"] == ""
    assert result[0]["shares_offered"] == ""
    assert result[0]["price_range"] == ""
    assert result[0]["market_value"] == ""


def test_fetch_ipo_news_fallback_empty(monkeypatch):
    def mock_fetch_rss(url, source_name, tags, limit, max_age_hours):
        return []

    mock_rss_mod = types.ModuleType("common.rss_fetcher")
    mock_rss_mod.fetch_rss_feed = mock_fetch_rss
    monkeypatch.setitem(sys.modules, "common.rss_fetcher", mock_rss_mod)

    result = fmp_api._fetch_ipo_news_fallback()
    assert result == []
