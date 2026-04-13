"""Tests for generate_market_summary.py — pure formatting/calculation functions."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


import scripts.generate_market_summary as gms

# ---------------------------------------------------------------------------
# format_commodity_data
# ---------------------------------------------------------------------------

class TestFormatCommodityData:
    def test_empty_data_returns_fallback(self):
        result = gms.format_commodity_data({})
        assert "원자재" in result or "가져올 수 없습니다" in result

    def test_formats_single_item(self):
        data = {"금 (Gold)": {"price": "1900.00", "change": "+5.00", "change_pct": "+0.26%"}}
        result = gms.format_commodity_data(data)
        assert "금 (Gold)" in result
        assert "1900.00" in result

    def test_positive_change_green_icon(self):
        data = {"WTI 원유": {"price": "80.00", "change": "+1.00", "change_pct": "+1.25%"}}
        result = gms.format_commodity_data(data)
        assert "🟢" in result

    def test_negative_change_red_icon(self):
        data = {"WTI 원유": {"price": "80.00", "change": "-1.00", "change_pct": "-1.25%"}}
        result = gms.format_commodity_data(data)
        assert "🔴" in result

    def test_invalid_change_pct_no_crash(self):
        data = {"금": {"price": "N/A", "change": "N/A", "change_pct": "N/A"}}
        result = gms.format_commodity_data(data)
        assert "금" in result


# ---------------------------------------------------------------------------
# calculate_yield_spread
# ---------------------------------------------------------------------------

class TestCalculateYieldSpread:
    def test_uses_t10y2y_directly(self):
        fred_data = {
            "T10Y2Y": {"value": -0.5, "date": "2024-01-01"},
            "10Y_YIELD": {"value": 4.0},
            "2Y_YIELD": {"value": 4.5},
        }
        result = gms.calculate_yield_spread(fred_data)
        assert result["spread"] == -0.5
        assert result["inverted"] is True

    def test_fallback_manual_calculation(self):
        fred_data = {
            "10Y_YIELD": {"value": 4.5, "date": "2024-01-01"},
            "2Y_YIELD": {"value": 4.0},
        }
        result = gms.calculate_yield_spread(fred_data)
        assert abs(result["spread"] - 0.5) < 0.001
        assert result["inverted"] is False

    def test_empty_data_returns_empty_dict(self):
        assert gms.calculate_yield_spread({}) == {}

    def test_positive_spread_not_inverted(self):
        fred_data = {"T10Y2Y": {"value": 0.75, "date": "2024-01-01"}}
        result = gms.calculate_yield_spread(fred_data)
        assert result["inverted"] is False

    def test_zero_spread(self):
        fred_data = {"T10Y2Y": {"value": 0.0, "date": "2024-01-01"}}
        result = gms.calculate_yield_spread(fred_data)
        assert result["inverted"] is False


# ---------------------------------------------------------------------------
# format_yield_spread
# ---------------------------------------------------------------------------

class TestFormatYieldSpread:
    def test_empty_returns_fallback(self):
        result = gms.format_yield_spread({})
        assert "가져올 수 없습니다" in result

    def test_normal_spread(self):
        data = {"spread": 0.5, "y10": 4.5, "y2": 4.0, "inverted": False, "date": "2024-01-01"}
        result = gms.format_yield_spread(data)
        assert "4.50%" in result
        assert "4.00%" in result
        assert "경고" not in result

    def test_inverted_spread_shows_warning(self):
        data = {"spread": -0.5, "y10": 4.0, "y2": 4.5, "inverted": True, "date": "2024-01-01"}
        result = gms.format_yield_spread(data)
        assert "경고" in result
        assert "역전" in result


# ---------------------------------------------------------------------------
# format_sector_performance
# ---------------------------------------------------------------------------

class TestFormatSectorPerformance:
    def test_empty_returns_fallback(self):
        result = gms.format_sector_performance({})
        assert "가져올 수 없습니다" in result

    def test_formats_sectors(self):
        data = {
            "XLK": {"name": "기술", "price": "200.00", "change": "+2.00", "change_pct": 1.0},
            "XLE": {"name": "에너지", "price": "90.00", "change": "-1.00", "change_pct": -1.1},
        }
        result = gms.format_sector_performance(data)
        assert "기술" in result
        assert "에너지" in result

    def test_sorted_by_change(self):
        data = {
            "XLK": {"name": "기술", "price": "200", "change": "+2", "change_pct": 1.5},
            "XLE": {"name": "에너지", "price": "90", "change": "-1", "change_pct": -1.0},
            "XLF": {"name": "금융", "price": "40", "change": "+0.5", "change_pct": 0.5},
        }
        result = gms.format_sector_performance(data)
        # 기술(+1.5%) should appear before 에너지(-1%)
        assert result.index("기술") < result.index("에너지")


# ---------------------------------------------------------------------------
# format_btc_etf
# ---------------------------------------------------------------------------

class TestFormatBtcEtf:
    def test_no_data_returns_fallback(self):
        result = gms.format_btc_etf({})
        assert "가져올 수 없습니다" in result

    def test_formats_etf_data(self):
        data = {
            "etfs": {
                "IBIT": {"name": "iShares Bitcoin Trust", "price": "35.00", "change": "+0.50", "change_pct": "+1.45%"},
            },
            "news": [],
        }
        result = gms.format_btc_etf(data)
        assert "iShares Bitcoin Trust" in result or "IBIT" in result

    def test_includes_news_items(self):
        data = {
            "etfs": {},
            "news": [{"title": "IBIT 인기", "link": "https://example.com"}],
        }
        result = gms.format_btc_etf(data)
        assert "IBIT 인기" in result

    def test_news_without_link(self):
        data = {
            "etfs": {},
            "news": [{"title": "뉴스 제목", "link": ""}],
        }
        result = gms.format_btc_etf(data)
        assert "뉴스 제목" in result


# ---------------------------------------------------------------------------
# format_whale_trades
# ---------------------------------------------------------------------------

class TestFormatWhaleTrades:
    def test_empty_returns_fallback(self):
        result = gms.format_whale_trades([])
        assert "가져올 수 없습니다" in result

    def test_formats_trades(self):
        items = [
            {"title": "1000 BTC 이동", "source": "Whale Alert", "link": "https://example.com"},
            {"title": "500 ETH 이동", "source": "Whale Alert", "link": "https://example2.com"},
        ]
        result = gms.format_whale_trades(items)
        assert "1000 BTC" in result
        assert "500 ETH" in result

    def test_deduplicates_by_url(self):
        items = [
            {"title": "1000 BTC", "source": "Whale Alert", "link": "https://same.com"},
            {"title": "1000 BTC dup", "source": "Whale Alert", "link": "https://same.com"},
        ]
        result = gms.format_whale_trades(items)
        # Second duplicate item with same URL should be removed
        assert result.count("same.com") <= 1

    def test_max_10_items(self):
        items = [
            {"title": f"거래 {i}", "source": "WA", "link": f"https://example{i}.com"}
            for i in range(20)
        ]
        result = gms.format_whale_trades(items)
        # Table should have at most 10 data rows
        row_count = result.count("거래 ")
        assert row_count <= 10


# ---------------------------------------------------------------------------
# format_global_overview
# ---------------------------------------------------------------------------

class TestFormatGlobalOverview:
    def test_no_data_returns_fallback(self):
        result = gms.format_global_overview({}, {})
        assert "가져올 수 없습니다" in result

    def test_formats_global_data(self):
        global_data = {
            "total_market_cap": {"usd": 2_000_000_000_000},
            "total_volume": {"usd": 100_000_000_000},
            "market_cap_percentage": {"btc": 50.0, "eth": 18.0},
            "market_cap_change_percentage_24h_usd": 1.5,
            "active_cryptocurrencies": 10000,
        }
        result = gms.format_global_overview(global_data, {})
        assert "BTC" in result
        assert "ETH" in result

    def test_fear_greed_index(self):
        fear_greed = {"value": 75, "classification": "Greed", "prev_value": 70}
        result = gms.format_global_overview({}, fear_greed)
        assert "75" in result
        assert "Greed" in result

    def test_fear_greed_without_prev(self):
        fear_greed = {"value": 30, "classification": "Fear"}
        result = gms.format_global_overview({}, fear_greed)
        assert "30" in result


# ---------------------------------------------------------------------------
# format_top_coins
# ---------------------------------------------------------------------------

class TestFormatTopCoins:
    def test_empty_returns_fallback(self):
        result = gms.format_top_coins([])
        assert "가져올 수 없습니다" in result

    def test_formats_coins(self):
        coins = [
            {
                "id": "bitcoin",
                "symbol": "btc",
                "name": "Bitcoin",
                "current_price": 50000,
                "price_change_percentage_24h": 2.5,
                "market_cap": 1_000_000_000_000,
                "total_volume": 50_000_000_000,
                "market_cap_rank": 1,
            }
        ]
        result = gms.format_top_coins(coins)
        assert "Bitcoin" in result or "BTC" in result.upper()


# ---------------------------------------------------------------------------
# format_trending
# ---------------------------------------------------------------------------

class TestFormatTrending:
    def test_empty_returns_fallback(self):
        result = gms.format_trending([])
        assert isinstance(result, str)

    def test_formats_trending_coins(self):
        coins = [
            {"item": {"name": "Pepe", "symbol": "PEPE", "score": 1}},
        ]
        result = gms.format_trending(coins)
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# generate_quant_signals
# ---------------------------------------------------------------------------

class TestGenerateQuantSignals:
    def test_empty_inputs(self):
        result = gms.generate_quant_signals([], {}, {})
        assert isinstance(result, str)

    def test_with_fear_greed(self):
        coins = []
        global_data = {}
        fear_greed = {"value": 20, "classification": "Extreme Fear"}
        result = gms.generate_quant_signals(coins, global_data, fear_greed)
        assert isinstance(result, str)

    def test_with_btc_data(self):
        coins = [
            {
                "symbol": "btc",
                "current_price": 45000,
                "price_change_percentage_24h": -5.0,
                "market_cap": 900_000_000_000,
                "total_volume": 40_000_000_000,
            }
        ]
        result = gms.generate_quant_signals(coins, {}, {"value": 25, "classification": "Fear"})
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# STABLECOIN_SYMBOLS constant
# ---------------------------------------------------------------------------

class TestStablecoinSymbols:
    def test_usdt_in_set(self):
        assert "usdt" in gms.STABLECOIN_SYMBOLS

    def test_usdc_in_set(self):
        assert "usdc" in gms.STABLECOIN_SYMBOLS

    def test_btc_not_in_set(self):
        assert "btc" not in gms.STABLECOIN_SYMBOLS
