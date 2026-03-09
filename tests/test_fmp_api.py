import importlib

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
