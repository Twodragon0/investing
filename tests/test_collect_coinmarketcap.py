"""Tests for collect_coinmarketcap collector."""

import importlib
import os
import sys

SCRIPTS_DIR = os.path.join(os.path.dirname(__file__), "..", "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)


# ---------------------------------------------------------------------------
# Pure-logic tests (no network)
# ---------------------------------------------------------------------------


def test_format_global_market_empty():
    mod = importlib.import_module("collect_coinmarketcap")
    result = mod.format_global_market({})
    assert result == ""


def test_format_global_market_has_key_fields():
    mod = importlib.import_module("collect_coinmarketcap")
    data = {
        "total_market_cap": {"usd": 2_500_000_000_000},
        "total_volume": {"usd": 100_000_000_000},
        "market_cap_percentage": {"btc": 52.3, "eth": 17.1},
        "market_cap_change_percentage_24h_usd": 1.5,
        "active_cryptocurrencies": 12000,
    }
    result = mod.format_global_market(data)
    assert "BTC" in result
    assert "52.3" in result
    assert "12,000" in result


def test_format_top_coins_table_empty():
    mod = importlib.import_module("collect_coinmarketcap")
    result = mod.format_top_coins_table([])
    assert result == ""


def test_format_top_coins_table_coingecko():
    mod = importlib.import_module("collect_coinmarketcap")
    coins = [
        {
            "name": "Bitcoin",
            "symbol": "btc",
            "current_price": 85000,
            "price_change_percentage_24h": 2.5,
            "price_change_percentage_7d_in_currency": 5.0,
            "market_cap": 1_700_000_000_000,
        }
    ]
    result = mod.format_top_coins_table(coins, source="coingecko")
    assert "Bitcoin" in result
    assert "BTC" in result
    assert "85,000" in result


def test_normalize_cmc_to_coingecko_skips_zero_price():
    mod = importlib.import_module("collect_coinmarketcap")
    coins = [
        {"name": "ZeroCoin", "symbol": "ZRC", "quote": {"USD": {"price": 0, "percent_change_24h": 0}}},
        {"name": "Bitcoin", "symbol": "BTC", "quote": {"USD": {"price": 85000, "percent_change_24h": 1.5}}},
    ]
    result = mod.normalize_cmc_to_coingecko(coins)
    names = [c["name"] for c in result]
    assert "Bitcoin" in names
    assert "ZeroCoin" not in names


def test_derive_gainers_losers_from_top():
    mod = importlib.import_module("collect_coinmarketcap")
    coins = [
        {"name": "CoinA", "symbol": "ca", "current_price": 10, "price_change_percentage_24h": 15.0, "market_cap": 1e9},
        {"name": "CoinB", "symbol": "cb", "current_price": 5, "price_change_percentage_24h": -8.0, "market_cap": 5e8},
        {"name": "CoinC", "symbol": "cc", "current_price": 1, "price_change_percentage_24h": 2.0, "market_cap": 1e8},
    ]
    gainers_table, losers_table = mod.derive_gainers_losers_from_top(coins)
    assert "CoinA" in gainers_table
    assert "CoinB" in losers_table


def test_generate_market_insight_returns_string():
    mod = importlib.import_module("collect_coinmarketcap")
    global_data = {
        "total_market_cap": {"usd": 2e12},
        "total_volume": {"usd": 1e11},
        "market_cap_percentage": {"btc": 55.0, "eth": 16.0},
        "market_cap_change_percentage_24h_usd": 1.2,
    }
    coins = [
        {
            "name": "Bitcoin",
            "symbol": "btc",
            "current_price": 85000,
            "price_change_percentage_24h": 1.2,
            "price_change_percentage_7d_in_currency": 3.0,
            "market_cap": 1.7e12,
        },
    ]
    fear_greed = {"value": 45, "classification": "Fear"}
    result = mod.generate_market_insight(global_data, coins, fear_greed)
    assert isinstance(result, str)
    assert len(result) > 0


# ---------------------------------------------------------------------------
# Network-mocked tests
# ---------------------------------------------------------------------------


def test_fetch_cmc_top_coins_returns_empty_when_no_key():
    mod = importlib.import_module("collect_coinmarketcap")
    result = mod.fetch_cmc_top_coins("")
    assert result == []


def test_fetch_cmc_trending_returns_empty_when_no_key():
    mod = importlib.import_module("collect_coinmarketcap")
    result = mod.fetch_cmc_trending("")
    assert result == []


def test_fetch_cmc_gainers_losers_returns_empty_when_no_key():
    mod = importlib.import_module("collect_coinmarketcap")
    gainers, losers = mod.fetch_cmc_gainers_losers("")
    assert gainers == []
    assert losers == []


def test_collector_run_no_network(tmp_path, monkeypatch):
    """CoinMarketCapCollector.run() completes without raising when APIs return empty."""
    mod = importlib.import_module("collect_coinmarketcap")

    monkeypatch.setattr(mod, "fetch_coingecko_global", dict)
    monkeypatch.setattr(mod, "fetch_coingecko_top_coins", lambda n: [])
    monkeypatch.setattr(mod, "fetch_coingecko_trending", list)
    monkeypatch.setattr(mod, "fetch_fear_greed_index", lambda *a, **kw: {})
    monkeypatch.setattr(mod, "fetch_cmc_top_coins", lambda key, n=30: [])
    monkeypatch.setattr(mod, "fetch_cmc_trending", lambda key: [])
    monkeypatch.setattr(mod, "fetch_cmc_gainers_losers", lambda key: ([], []))
    monkeypatch.setattr(mod, "fetch_cmc_browser_fallback", lambda n=20: [])

    # Suppress image generation
    try:
        import common.image_generator as ig

        monkeypatch.setattr(ig, "generate_top_coins_card", lambda *a, **kw: None)
        monkeypatch.setattr(ig, "generate_market_heatmap", lambda *a, **kw: None)
        monkeypatch.setattr(ig, "generate_news_briefing_card", lambda *a, **kw: None)
    except (ImportError, AttributeError):
        pass

    from common import post_generator as pg_mod

    monkeypatch.setattr(pg_mod, "POSTS_DIR", str(tmp_path))

    collector = mod.CoinMarketCapCollector()
    collector.run()


# ---------------------------------------------------------------------------
# _build_title_suffix tests
# ---------------------------------------------------------------------------


def test_title_uses_fear_greed_when_extreme_fear():
    mod = importlib.import_module("collect_coinmarketcap")
    result = mod._build_title_suffix(74000, -1.0, 20, 2.6e12, -0.5)
    assert "Fear 20" in result
    assert "BTC" not in result
    assert "시총" not in result


def test_title_uses_extreme_greed_label():
    mod = importlib.import_module("collect_coinmarketcap")
    result = mod._build_title_suffix(80000, 1.0, 80, 2.6e12, 0.5)
    assert "Extreme Greed 80" in result
    assert "BTC" not in result


def test_title_uses_btc_when_big_move():
    mod = importlib.import_module("collect_coinmarketcap")
    # fear_greed=50 (neutral), BTC -5% (big move)
    result = mod._build_title_suffix(74929, -5.0, 50, 2.6e12, -1.0)
    assert "BTC $" in result
    assert "-5.0" in result
    assert "시총" not in result


def test_title_uses_market_cap_fallback():
    mod = importlib.import_module("collect_coinmarketcap")
    # fear_greed=50, BTC -1% (small move) → falls through to market cap
    result = mod._build_title_suffix(74929, -1.0, 50, 2.61e12, -1.0)
    assert "시총" in result
    assert "BTC $" not in result


def test_title_excludes_individual_altcoin():
    """Title suffix must not contain individual altcoin symbols."""
    mod = importlib.import_module("collect_coinmarketcap")
    # Scenarios that previously produced altcoin symbols
    for fg, btc_ch in [(50, -1.0), (50, 2.0), (60, 0.5)]:
        result = mod._build_title_suffix(74929, btc_ch, fg, 2.6e12, btc_ch)
        for symbol in ("HYPE", "ZEC", "SOL", "XRP", "DOGE", "PEPE"):
            assert symbol not in result, f"Unexpected altcoin {symbol} in title suffix: {result!r}"


def test_dedup_idempotent_coinmarketcap(tmp_path, monkeypatch):
    """Running CoinMarketCapCollector twice with same data creates no extra posts."""
    mod = importlib.import_module("collect_coinmarketcap")

    fake_coin = {
        "name": "Bitcoin",
        "symbol": "btc",
        "current_price": 85000,
        "price_change_percentage_24h": 1.5,
        "price_change_percentage_7d_in_currency": 3.0,
        "market_cap": 1_700_000_000_000,
    }

    monkeypatch.setattr(mod, "fetch_coingecko_global", dict)
    monkeypatch.setattr(mod, "fetch_coingecko_top_coins", lambda n: [fake_coin])
    monkeypatch.setattr(mod, "fetch_coingecko_trending", list)
    monkeypatch.setattr(mod, "fetch_fear_greed_index", lambda *a, **kw: {"value": 50, "classification": "Neutral"})
    monkeypatch.setattr(mod, "fetch_cmc_top_coins", lambda key, n=30: [])
    monkeypatch.setattr(mod, "fetch_cmc_trending", lambda key: [])
    monkeypatch.setattr(mod, "fetch_cmc_gainers_losers", lambda key: ([], []))
    monkeypatch.setattr(mod, "fetch_cmc_browser_fallback", lambda n=20: [])

    try:
        import common.image_generator as ig

        monkeypatch.setattr(ig, "generate_top_coins_card", lambda *a, **kw: None)
        monkeypatch.setattr(ig, "generate_market_heatmap", lambda *a, **kw: None)
        monkeypatch.setattr(ig, "generate_news_briefing_card", lambda *a, **kw: None)
    except (ImportError, AttributeError):
        pass

    from common import post_generator as pg_mod

    monkeypatch.setattr(pg_mod, "POSTS_DIR", str(tmp_path))

    c1 = mod.CoinMarketCapCollector()
    c1.run()
    posts_after_first = list(tmp_path.glob("*.md"))

    c2 = mod.CoinMarketCapCollector()
    c2.dedup = c1.dedup
    c2.run()
    posts_after_second = list(tmp_path.glob("*.md"))

    assert len(posts_after_second) == len(posts_after_first)
