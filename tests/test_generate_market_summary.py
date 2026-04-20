"""Tests for generate_market_summary.py — pure formatting/calculation functions."""

import os
import re as _re
import sys
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

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
        items = [{"title": f"거래 {i}", "source": "WA", "link": f"https://example{i}.com"} for i in range(20)]
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


# ---------------------------------------------------------------------------
# format_us_market
# ---------------------------------------------------------------------------


class TestFormatUsMarket:
    def test_empty_data_returns_fallback(self):
        result = gms.format_us_market({})
        assert "가져올 수 없습니다" in result
        assert "S&P 500" in result

    def test_formats_single_symbol(self):
        data = {
            "SPY": {
                "name": "S&P 500 ETF",
                "price": "500.00",
                "change": "+5.00",
                "change_pct": "+1.01%",
                "volume": "100000",
            }
        }
        result = gms.format_us_market(data)
        assert "S&P 500 ETF" in result
        assert "500.00" in result
        assert "+1.01%" in result

    def test_formats_multiple_symbols(self):
        data = {
            "SPY": {
                "name": "S&P 500 ETF",
                "price": "500.00",
                "change": "+5.00",
                "change_pct": "+1.01%",
                "volume": "100000",
            },
            "QQQ": {
                "name": "NASDAQ 100 ETF",
                "price": "420.00",
                "change": "-2.00",
                "change_pct": "-0.47%",
                "volume": "80000",
            },
        }
        result = gms.format_us_market(data)
        assert "S&P 500 ETF" in result
        assert "NASDAQ 100 ETF" in result

    def test_includes_volume_column(self):
        data = {
            "SPY": {
                "name": "S&P 500 ETF",
                "price": "500.00",
                "change": "+5.00",
                "change_pct": "+1.01%",
                "volume": "99999",
            }
        }
        result = gms.format_us_market(data)
        assert "99999" in result

    def test_volume_missing_falls_back_to_na(self):
        # volume key absent — dict.get("volume", "N/A") should handle it
        data = {
            "COIN": {
                "name": "Coinbase",
                "price": "200.00",
                "change": "+1.00",
                "change_pct": "+0.50%",
            }
        }
        result = gms.format_us_market(data)
        assert "Coinbase" in result


# ---------------------------------------------------------------------------
# format_korean_market
# ---------------------------------------------------------------------------


class TestFormatKoreanMarket:
    def test_empty_data_returns_fallback(self):
        result = gms.format_korean_market({})
        assert "가져올 수 없습니다" in result
        assert "KOSPI" in result

    def test_formats_kospi(self):
        data = {"KOSPI": {"price": "2500.00", "change": "+20.00", "change_pct": "+0.81%"}}
        result = gms.format_korean_market(data)
        assert "KOSPI" in result
        assert "2500.00" in result

    def test_positive_change_shows_green_icon(self):
        data = {"KOSPI": {"price": "2500.00", "change": "+20.00", "change_pct": "+0.81%"}}
        result = gms.format_korean_market(data)
        assert "🟢" in result

    def test_negative_change_shows_red_icon(self):
        data = {"KOSDAQ": {"price": "800.00", "change": "-5.00", "change_pct": "-0.62%"}}
        result = gms.format_korean_market(data)
        assert "🔴" in result

    def test_invalid_change_pct_no_crash(self):
        data = {"KOSPI": {"price": "N/A", "change": "N/A", "change_pct": "N/A"}}
        result = gms.format_korean_market(data)
        assert "KOSPI" in result

    def test_formats_multiple_indices(self):
        data = {
            "KOSPI": {"price": "2500.00", "change": "+10.00", "change_pct": "+0.40%"},
            "KOSDAQ": {"price": "820.00", "change": "-3.00", "change_pct": "-0.36%"},
            "USD/KRW 환율": {"price": "1320.00", "change": "+2.00", "change_pct": "+0.15%"},
        }
        result = gms.format_korean_market(data)
        assert "KOSPI" in result
        assert "KOSDAQ" in result
        assert "USD/KRW" in result


# ---------------------------------------------------------------------------
# format_macro
# ---------------------------------------------------------------------------


class TestFormatMacro:
    def test_empty_no_api_key_explains_missing_key(self):
        result = gms.format_macro({}, has_api_key=False)
        assert "FRED_API_KEY" in result

    def test_empty_with_api_key_suggests_validity(self):
        result = gms.format_macro({}, has_api_key=True)
        assert "API" in result or "유효" in result or "가져오지 못했습니다" in result

    def test_formats_fed_rate_in_금리_group(self):
        data = {
            "FED_RATE": {"label": "연방기금금리", "value": 5.25, "date": "2024-01-01", "change": 0.0},
        }
        result = gms.format_macro(data)
        assert "금리" in result
        assert "연방기금금리" in result
        assert "5.25%" in result

    def test_formats_m2_with_billions_suffix(self):
        data = {
            "M2": {"label": "M2 통화공급", "value": 20800.5, "date": "2024-01-01", "change": None},
        }
        result = gms.format_macro(data)
        assert "20,800.5B" in result or "20800.5B" in result

    def test_t10y2y_negative_gets_red_label(self):
        data = {
            "T10Y2Y": {"label": "장단기 금리 스프레드", "value": -0.4, "date": "2024-01-01", "change": -0.1},
        }
        result = gms.format_macro(data)
        assert "🔴" in result

    def test_t10y2y_positive_no_red_label(self):
        data = {
            "T10Y2Y": {"label": "장단기 금리 스프레드", "value": 0.5, "date": "2024-01-01", "change": 0.1},
        }
        result = gms.format_macro(data)
        # Positive spread should not show red warning on the label
        label_line = [line for line in result.split("\n") if "장단기" in line]
        assert all("🔴" not in line for line in label_line)

    def test_change_none_shows_na(self):
        data = {
            "FED_RATE": {"label": "연방기금금리", "value": 5.0, "date": "2024-01-01", "change": None},
        }
        result = gms.format_macro(data)
        assert "N/A" in result

    def test_unemployment_in_경제지표_group(self):
        data = {
            "UNEMPLOYMENT": {"label": "실업률", "value": 3.9, "date": "2024-01-01", "change": 0.1},
        }
        result = gms.format_macro(data)
        assert "경제 지표" in result
        assert "실업률" in result

    def test_vix_in_유동성_group(self):
        data = {
            "VIX": {"label": "VIX 변동성 지수", "value": 18.5, "date": "2024-01-01", "change": -1.2},
        }
        result = gms.format_macro(data)
        assert "유동성" in result
        assert "VIX" in result

    def test_unknown_key_goes_to_기타_group(self):
        data = {
            "UNKNOWN_KEY": {"label": "미분류 지표", "value": 1.23, "date": "2024-01-01", "change": 0.01},
        }
        result = gms.format_macro(data)
        assert "기타" in result or "미분류" in result

    def test_multiple_groups_all_present(self):
        data = {
            "FED_RATE": {"label": "연방기금금리", "value": 5.25, "date": "2024-01-01", "change": 0.0},
            "UNEMPLOYMENT": {"label": "실업률", "value": 3.9, "date": "2024-01-01", "change": 0.0},
            "VIX": {"label": "VIX 변동성 지수", "value": 18.5, "date": "2024-01-01", "change": 0.0},
        }
        result = gms.format_macro(data)
        assert "금리" in result
        assert "경제 지표" in result
        assert "유동성" in result


# ---------------------------------------------------------------------------
# format_gainers_losers
# ---------------------------------------------------------------------------


class TestFormatGainersLosers:
    def _make_coin(self, symbol, name, price, ch24):
        return {
            "symbol": symbol,
            "name": name,
            "current_price": price,
            "price_change_percentage_24h": ch24,
        }

    def test_empty_returns_fallback(self):
        result = gms.format_gainers_losers([])
        assert "데이터를 가져올 수 없습니다" in result

    def test_stablecoins_excluded_from_rankings(self):
        coins = [
            self._make_coin("usdt", "Tether", 1.0, 0.01),
            self._make_coin("btc", "Bitcoin", 50000, 3.5),
            self._make_coin("eth", "Ethereum", 3000, -1.2),
        ]
        result = gms.format_gainers_losers(coins)
        # USDT is a stablecoin — its name should not appear in the ranking
        assert "Tether" not in result

    def test_top_gainers_section_present(self):
        coins = [self._make_coin(f"coin{i}", f"Coin{i}", float(i * 10), float(i)) for i in range(1, 11)]
        result = gms.format_gainers_losers(coins)
        assert "상승" in result

    def test_top_losers_section_present(self):
        coins = [self._make_coin(f"coin{i}", f"Coin{i}", float(i * 10), float(i - 5)) for i in range(1, 11)]
        result = gms.format_gainers_losers(coins)
        assert "하락" in result

    def test_price_below_1_uses_6_decimal_format(self):
        coins = [
            self._make_coin("pepe", "Pepe", 0.000012, 15.0),
            self._make_coin("btc", "Bitcoin", 50000, -2.0),
        ]
        result = gms.format_gainers_losers(coins)
        # Sub-cent price should use 6 decimal places
        assert "0.000012" in result

    def test_gainers_sorted_descending(self):
        coins = [
            self._make_coin("bnb", "BNB", 300, 1.0),
            self._make_coin("sol", "Solana", 100, 8.5),
            self._make_coin("btc", "Bitcoin", 50000, 3.0),
        ]
        result = gms.format_gainers_losers(coins)
        # Solana (+8.5%) should appear before BNB (+1.0%) in the gainers table
        assert result.index("Solana") < result.index("BNB")


# ---------------------------------------------------------------------------
# format_trending (content, not just isinstance)
# ---------------------------------------------------------------------------


class TestFormatTrendingContent:
    def test_empty_returns_no_data_message(self):
        result = gms.format_trending([])
        assert "트렌딩" in result or "데이터" in result

    def test_shows_coin_name_and_symbol(self):
        coins = [{"item": {"name": "Dogecoin", "symbol": "DOGE", "market_cap_rank": 10}}]
        result = gms.format_trending(coins)
        assert "Dogecoin" in result
        assert "DOGE" in result

    def test_shows_market_cap_rank(self):
        coins = [{"item": {"name": "Solana", "symbol": "SOL", "market_cap_rank": 5}}]
        result = gms.format_trending(coins)
        assert "#5" in result

    def test_max_7_coins_shown(self):
        coins = [{"item": {"name": f"Coin{i}", "symbol": f"C{i}", "market_cap_rank": i}} for i in range(1, 15)]
        result = gms.format_trending(coins)
        # Coin8 through Coin14 should not appear (only top 7 shown)
        assert "Coin8" not in result
        assert "Coin7" in result

    def test_rank_na_when_missing(self):
        coins = [{"item": {"name": "Unknown", "symbol": "UNK"}}]
        result = gms.format_trending(coins)
        assert "N/A" in result


# ---------------------------------------------------------------------------
# generate_quant_signals (content verification)
# ---------------------------------------------------------------------------


class TestGenerateQuantSignalsContent:
    def _btc(self, ch24, ch7d):
        return {
            "symbol": "BTC",
            "current_price": 50000,
            "price_change_percentage_24h": ch24,
            "price_change_percentage_7d_in_currency": ch7d,
        }

    def _eth(self, ch24, ch7d):
        return {
            "symbol": "ETH",
            "current_price": 3000,
            "price_change_percentage_24h": ch24,
            "price_change_percentage_7d_in_currency": ch7d,
        }

    def test_btc_uptrend_label(self):
        result = gms.generate_quant_signals([self._btc(2.0, 5.0)], {}, {})
        assert "상승 추세" in result

    def test_btc_downtrend_label(self):
        result = gms.generate_quant_signals([self._btc(-3.0, -5.0)], {}, {})
        assert "하락 추세" in result

    def test_btc_mixed_trend_label(self):
        # ch24 positive, ch7d negative → 혼조
        result = gms.generate_quant_signals([self._btc(1.0, -2.0)], {}, {})
        assert "혼조" in result

    def test_eth_momentum_included(self):
        result = gms.generate_quant_signals([self._btc(1.0, 1.0), self._eth(0.5, -1.0)], {}, {})
        assert "ETH" in result

    def test_risk_on_regime_when_mcap_up_btc_dom_low(self):
        global_data = {
            "market_cap_change_percentage_24h_usd": 3.0,
            "market_cap_percentage": {"btc": 45.0},
        }
        result = gms.generate_quant_signals([], global_data, {})
        assert "리스크온" in result

    def test_risk_off_regime_when_mcap_down_btc_dom_high(self):
        global_data = {
            "market_cap_change_percentage_24h_usd": -3.0,
            "market_cap_percentage": {"btc": 55.0},
        }
        result = gms.generate_quant_signals([], global_data, {})
        assert "리스크오프" in result

    def test_neutral_regime_when_changes_small(self):
        global_data = {
            "market_cap_change_percentage_24h_usd": 0.5,
            "market_cap_percentage": {"btc": 50.0},
        }
        result = gms.generate_quant_signals([], global_data, {})
        assert "중립" in result

    def test_fear_greed_line_included(self):
        result = gms.generate_quant_signals([], {}, {"value": 22, "classification": "Extreme Fear"})
        assert "Extreme Fear" in result
        assert "22" in result


# ---------------------------------------------------------------------------
# generate_key_highlights
# ---------------------------------------------------------------------------


class TestGenerateKeyHighlights:
    def _btc_coin(self, price, ch24, ch7d):
        return {
            "symbol": "btc",
            "name": "Bitcoin",
            "current_price": price,
            "price_change_percentage_24h": ch24,
            "price_change_percentage_7d_in_currency": ch7d,
        }

    def test_empty_all_returns_empty_string(self):
        result = gms.generate_key_highlights({}, [], {}, {})
        assert result == ""

    def test_extreme_fear_bullet_present(self):
        fg = {"value": 12, "classification": "Extreme Fear"}
        result = gms.generate_key_highlights({}, [], fg, {})
        assert "극도의 공포" in result

    def test_fear_bullet_present(self):
        fg = {"value": 28, "classification": "Fear"}
        result = gms.generate_key_highlights({}, [], fg, {})
        assert "공포 장세" in result

    def test_greed_bullet_present(self):
        fg = {"value": 72, "classification": "Greed"}
        result = gms.generate_key_highlights({}, [], fg, {})
        assert "탐욕 장세" in result

    def test_extreme_greed_bullet_present(self):
        fg = {"value": 88, "classification": "Extreme Greed"}
        result = gms.generate_key_highlights({}, [], fg, {})
        assert "탐욕 장세" in result

    def test_btc_price_bullet_present(self):
        coins = [self._btc_coin(60000, 2.5, 5.0)]
        result = gms.generate_key_highlights({}, coins, {}, {})
        assert "비트코인" in result
        assert "60,000" in result

    def test_btc_price_shows_하락_when_negative(self):
        coins = [self._btc_coin(40000, -3.0, -7.0)]
        result = gms.generate_key_highlights({}, coins, {}, {})
        assert "하락" in result

    def test_global_market_cap_bullet(self):
        global_data = {
            "total_market_cap": {"usd": 2_500_000_000_000},
            "market_cap_change_percentage_24h_usd": 1.8,
            "market_cap_percentage": {"btc": 52.0},
        }
        result = gms.generate_key_highlights(global_data, [], {}, {})
        assert "시가총액" in result

    def test_btc_dominance_over_50_shows_지속(self):
        global_data = {
            "total_market_cap": {"usd": 2_000_000_000_000},
            "market_cap_change_percentage_24h_usd": 0.5,
            "market_cap_percentage": {"btc": 55.0},
        }
        result = gms.generate_key_highlights(global_data, [], {}, {})
        assert "지속" in result

    def test_btc_dominance_under_50_shows_약화(self):
        global_data = {
            "total_market_cap": {"usd": 2_000_000_000_000},
            "market_cap_change_percentage_24h_usd": 0.5,
            "market_cap_percentage": {"btc": 44.0},
        }
        result = gms.generate_key_highlights(global_data, [], {}, {})
        assert "약화" in result

    def test_korean_market_bullet_present(self):
        kr_market = {"KOSPI": {"price": "2500.00", "change": "+10.00", "change_pct": "+0.40%"}}
        result = gms.generate_key_highlights({}, [], {}, kr_market)
        assert "KOSPI" in result

    def test_commodity_gold_bullet_present(self):
        commodity = {"금 (Gold)": {"price": "1950.00", "change": "+10.00", "change_pct": "+0.52%"}}
        result = gms.generate_key_highlights({}, [], {}, {}, commodity_data=commodity)
        assert "금" in result

    def test_commodity_oil_bullet_present(self):
        commodity = {"원유 (WTI)": {"price": "78.00", "change": "-0.50", "change_pct": "-0.64%"}}
        result = gms.generate_key_highlights({}, [], {}, {}, commodity_data=commodity)
        assert "원유" in result

    def test_top_mover_bullet_only_when_both_gainers_and_losers(self):
        # All positive — no losers, so mover bullet should not appear
        coins = [
            {"symbol": "bnb", "name": "BNB", "current_price": 300, "price_change_percentage_24h": 1.0},
            {"symbol": "sol", "name": "Solana", "current_price": 100, "price_change_percentage_24h": 2.0},
        ]
        result = gms.generate_key_highlights({}, coins, {}, {})
        assert "주목할 코인" not in result

    def test_top_mover_bullet_with_mixed_changes(self):
        coins = [
            {"symbol": "sol", "name": "Solana", "current_price": 100, "price_change_percentage_24h": 8.0},
            {"symbol": "link", "name": "Chainlink", "current_price": 15, "price_change_percentage_24h": -4.0},
        ]
        result = gms.generate_key_highlights({}, coins, {}, {})
        assert "주목할 코인" in result
        assert "Solana" in result
        assert "Chainlink" in result


# ---------------------------------------------------------------------------
# generate_insight
# ---------------------------------------------------------------------------


class TestGenerateInsight:
    def _global(self, mcap_change, btc_dom):
        return {
            "market_cap_change_percentage_24h_usd": mcap_change,
            "market_cap_percentage": {"btc": btc_dom},
        }

    def test_strong_rise_message_when_mcap_over_5(self):
        result = gms.generate_insight(self._global(6.0, 50), [], {}, {}, {})
        assert "강한 상승세" in result

    def test_moderate_rise_when_mcap_1_to_5(self):
        result = gms.generate_insight(self._global(2.0, 50), [], {}, {}, {})
        assert "소폭 상승세" in result

    def test_sideways_when_mcap_near_zero(self):
        result = gms.generate_insight(self._global(0.0, 50), [], {}, {}, {})
        assert "보합세" in result

    def test_decline_when_mcap_minus1_to_minus5(self):
        result = gms.generate_insight(self._global(-2.0, 50), [], {}, {}, {})
        assert "하락세" in result

    def test_sharp_decline_when_mcap_under_minus5(self):
        result = gms.generate_insight(self._global(-6.0, 50), [], {}, {}, {})
        assert "급격한 하락세" in result

    def test_high_btc_dom_warns_altcoin_caution(self):
        result = gms.generate_insight(self._global(0.0, 60), [], {}, {}, {})
        assert "알트코인" in result or "비트코인 중심" in result

    def test_low_btc_dom_suggests_alt_season(self):
        result = gms.generate_insight(self._global(0.0, 40), [], {}, {}, {})
        assert "알트 시즌" in result

    def test_extreme_fear_insight_included(self):
        fg = {"value": 10, "classification": "Extreme Fear"}
        result = gms.generate_insight(self._global(0.0, 50), [], fg, {}, {})
        assert "Extreme Fear" in result or "극도의 공포" in result

    def test_neutral_fear_greed_included(self):
        fg = {"value": 50, "classification": "Neutral"}
        result = gms.generate_insight(self._global(0.0, 50), [], fg, {}, {})
        assert "중립" in result

    def test_top_coin_movers_included(self):
        coins = [
            {"symbol": "btc", "name": "Bitcoin", "current_price": 50000, "price_change_percentage_24h": 4.0},
            {"symbol": "eth", "name": "Ethereum", "current_price": 3000, "price_change_percentage_24h": -2.0},
        ]
        result = gms.generate_insight(self._global(1.0, 50), coins, {}, {}, {})
        assert "Bitcoin" in result or "Ethereum" in result

    def test_spy_change_included_when_us_market_present(self):
        us_market = {
            "SPY": {
                "name": "S&P 500 ETF",
                "price": "500.00",
                "change": "+5.00",
                "change_pct": "+1.01%",
                "volume": "100000",
            }
        }
        result = gms.generate_insight(self._global(0.0, 50), [], {}, us_market, {})
        assert "S&P 500" in result
        assert "+1.01%" in result

    def test_large_spy_move_triggers_additional_commentary(self):
        us_market = {
            "SPY": {
                "name": "S&P 500 ETF",
                "price": "500.00",
                "change": "+15.00",
                "change_pct": "+3.05%",
                "volume": "100000",
            }
        }
        result = gms.generate_insight(self._global(0.0, 50), [], {}, us_market, {})
        assert "글로벌" in result or "대폭 변동" in result

    def test_kospi_included_when_kr_market_present(self):
        kr_market = {"KOSPI": {"price": "2500.00", "change": "+10.00", "change_pct": "+0.40%"}}
        result = gms.generate_insight(self._global(0.0, 50), [], {}, {}, kr_market)
        assert "KOSPI" in result

    def test_usdkrw_included_when_present(self):
        kr_market = {"USD/KRW 환율": {"price": "1320.00", "change": "+2.00", "change_pct": "+0.15%"}}
        result = gms.generate_insight(self._global(0.0, 50), [], {}, {}, kr_market)
        assert "1320.00" in result or "환율" in result

    def test_disclaimer_always_present(self):
        result = gms.generate_insight({}, [], {}, {}, {})
        assert "투자 조언이 아닙니다" in result

    def test_empty_all_inputs_still_returns_disclaimer(self):
        result = gms.generate_insight({}, [], {}, {}, {})
        assert isinstance(result, str)
        assert len(result) > 0


# ---------------------------------------------------------------------------
# format_top_coins (additional coverage)
# ---------------------------------------------------------------------------


class TestFormatTopCoinsExtra:
    def _coin(self, symbol, name, price, ch24=0.0, ch7d=0.0, mcap=1_000_000_000):
        return {
            "symbol": symbol,
            "name": name,
            "current_price": price,
            "price_change_percentage_24h": ch24,
            "price_change_percentage_7d_in_currency": ch7d,
            "market_cap": mcap,
        }

    def test_low_price_uses_6_decimal_format(self):
        coins = [self._coin("shib", "Shiba Inu", 0.000008, ch24=1.5)]
        result = gms.format_top_coins(coins)
        assert "0.000008" in result

    def test_high_price_uses_2_decimal_format(self):
        coins = [self._coin("btc", "Bitcoin", 65000.50, ch24=2.0)]
        result = gms.format_top_coins(coins)
        assert "65,000.50" in result

    def test_none_price_treated_as_zero(self):
        # current_price=None should not crash (falls back to 0)
        coins = [self._coin("xyz", "XYZ", None, ch24=None)]
        result = gms.format_top_coins(coins)
        assert "XYZ" in result

    def test_only_first_20_coins_shown(self):
        coins = [self._coin(f"c{i}", f"Coin{i}", float(i * 100)) for i in range(1, 26)]
        result = gms.format_top_coins(coins)
        assert "Coin20" in result
        assert "Coin21" not in result

    def test_symbol_uppercased(self):
        coins = [self._coin("eth", "Ethereum", 3000)]
        result = gms.format_top_coins(coins)
        assert "ETH" in result


# ---------------------------------------------------------------------------
# calculate_yield_spread (edge cases)
# ---------------------------------------------------------------------------


class TestCalculateYieldSpreadEdgeCases:
    def test_only_10y_yield_no_2y_returns_empty(self):
        # Manual fallback requires both yields; only one present → empty dict
        fred_data = {"10Y_YIELD": {"value": 4.5, "date": "2024-01-01"}}
        result = gms.calculate_yield_spread(fred_data)
        assert result == {}

    def test_t10y2y_value_none_falls_through_to_manual(self):
        # T10Y2Y present but value is None → manual calculation used
        fred_data = {
            "T10Y2Y": {"value": None, "date": "2024-01-01"},
            "10Y_YIELD": {"value": 4.2, "date": "2024-01-01"},
            "2Y_YIELD": {"value": 4.0},
        }
        result = gms.calculate_yield_spread(fred_data)
        assert abs(result["spread"] - 0.2) < 0.001

    def test_manual_inverted_spread(self):
        fred_data = {
            "10Y_YIELD": {"value": 3.8, "date": "2024-01-01"},
            "2Y_YIELD": {"value": 4.5},
        }
        result = gms.calculate_yield_spread(fred_data)
        assert result["inverted"] is True
        assert result["spread"] < 0


# ---------------------------------------------------------------------------
# fetch_us_market_data — Alpha Vantage path (mocked HTTP)
# ---------------------------------------------------------------------------


class TestFetchUsMarketDataAlphaVantage:
    """Tests for the Alpha Vantage branch of fetch_us_market_data."""

    def _av_response(self, symbol, price, change, change_pct, volume):
        return {
            "Global Quote": {
                "01. symbol": symbol,
                "05. price": price,
                "06. volume": volume,
                "09. change": change,
                "10. change percent": change_pct,
            }
        }

    def test_parses_spy_quote_from_alpha_vantage(self, monkeypatch):
        import requests as _requests

        mock_resp = type(
            "R",
            (),
            {
                "raise_for_status": lambda self: None,
                "json": lambda self: self._data,
                "_data": self._av_response("SPY", "500.00", "+5.00", "+1.01%", "50000000"),
            },
        )()

        monkeypatch.setattr(_requests, "get", lambda *a, **kw: mock_resp)

        # Also stub yfinance so the fallback/crypto branch doesn't try the network
        import sys

        yf_stub = type(
            "yf",
            (),
            {
                "Ticker": lambda sym: type(
                    "T", (), {"fast_info": type("FI", (), {"last_price": None, "previous_close": None})()}
                )()
            },
        )()
        monkeypatch.setitem(sys.modules, "yfinance", yf_stub)

        result = gms.fetch_us_market_data("FAKE_KEY")
        assert "SPY" in result
        assert result["SPY"]["price"] == "500.00"
        assert result["SPY"]["change"] == "+5.00"
        assert result["SPY"]["volume"] == "50000000"

    def test_missing_price_field_skips_symbol(self, monkeypatch):
        import requests as _requests

        # Global Quote present but no '05. price'
        mock_resp = type(
            "R",
            (),
            {
                "raise_for_status": lambda self: None,
                "json": lambda self: {"Global Quote": {}},
            },
        )()
        monkeypatch.setattr(_requests, "get", lambda *a, **kw: mock_resp)

        import sys

        yf_stub = type(
            "yf",
            (),
            {
                "Ticker": lambda sym: type(
                    "T", (), {"fast_info": type("FI", (), {"last_price": None, "previous_close": None})()}
                )()
            },
        )()
        monkeypatch.setitem(sys.modules, "yfinance", yf_stub)

        result = gms.fetch_us_market_data("FAKE_KEY")
        assert "SPY" not in result

    def test_network_error_skips_symbol_and_continues(self, monkeypatch):
        import requests as _requests

        call_count = {"n": 0}

        def fake_get(*a, **kw):
            call_count["n"] += 1
            raise _requests.exceptions.ConnectionError("timeout")

        monkeypatch.setattr(_requests, "get", fake_get)

        import sys

        yf_stub = type(
            "yf",
            (),
            {
                "Ticker": lambda sym: type(
                    "T", (), {"fast_info": type("FI", (), {"last_price": None, "previous_close": None})()}
                )()
            },
        )()
        monkeypatch.setitem(sys.modules, "yfinance", yf_stub)

        # Should not raise; returns partial (possibly empty) dict
        result = gms.fetch_us_market_data("FAKE_KEY")
        assert isinstance(result, dict)

    def test_no_api_key_skips_alpha_vantage_calls(self, monkeypatch):
        import requests as _requests

        called = {"n": 0}

        def fake_get(*a, **kw):
            called["n"] += 1
            return type(
                "R",
                (),
                {
                    "raise_for_status": lambda self: None,
                    "json": lambda self: {},
                },
            )()

        monkeypatch.setattr(_requests, "get", fake_get)

        import sys

        yf_stub = type(
            "yf",
            (),
            {
                "Ticker": lambda sym: type(
                    "T", (), {"fast_info": type("FI", (), {"last_price": None, "previous_close": None})()}
                )()
            },
        )()
        monkeypatch.setitem(sys.modules, "yfinance", yf_stub)

        gms.fetch_us_market_data("")
        assert called["n"] == 0


# ---------------------------------------------------------------------------
# fetch_us_market_data — yfinance crypto-related stocks branch
# ---------------------------------------------------------------------------


class TestFetchUsMarketDataYfinance:
    """Tests for yfinance-based crypto stock fetching (COIN, MSTR, IBIT)."""

    def _make_yf_stub(self, price, prev_close):
        fast_info = type(
            "FI",
            (),
            {
                "last_price": price,
                "previous_close": prev_close,
            },
        )()
        ticker = type("T", (), {"fast_info": fast_info})()
        return type("yf", (), {"Ticker": staticmethod(lambda sym: ticker)})()

    def test_parses_coin_stock_data(self, monkeypatch):
        import sys

        import requests as _requests

        # No API key → skip AV; patch yfinance
        monkeypatch.setattr(_requests, "get", lambda *a, **kw: (_ for _ in ()).throw(Exception("no-call")))
        monkeypatch.setitem(sys.modules, "yfinance", self._make_yf_stub(230.50, 225.00))

        result = gms.fetch_us_market_data("")
        # COIN, MSTR, IBIT all use same price/prev — all should be present
        assert "COIN" in result
        assert result["COIN"]["price"] == "230.50"
        # change = 230.50 - 225.00 = +5.50
        assert "+5.50" in result["COIN"]["change"]

    def test_change_pct_calculated_correctly(self, monkeypatch):
        import sys

        import requests as _requests

        monkeypatch.setattr(_requests, "get", lambda *a, **kw: (_ for _ in ()).throw(Exception("no-call")))
        monkeypatch.setitem(sys.modules, "yfinance", self._make_yf_stub(110.0, 100.0))

        result = gms.fetch_us_market_data("")
        assert "COIN" in result
        # (110 - 100) / 100 * 100 = +10.00%
        assert "+10.00%" in result["COIN"]["change_pct"]

    def test_none_price_skips_symbol(self, monkeypatch):
        import sys

        import requests as _requests

        monkeypatch.setattr(_requests, "get", lambda *a, **kw: (_ for _ in ()).throw(Exception("no-call")))
        monkeypatch.setitem(sys.modules, "yfinance", self._make_yf_stub(None, 100.0))

        result = gms.fetch_us_market_data("")
        # Neither COIN, MSTR, nor IBIT should be in results when price is None
        assert "COIN" not in result
        assert "MSTR" not in result
        assert "IBIT" not in result

    def test_yfinance_import_error_returns_empty(self, monkeypatch):
        import sys

        import requests as _requests

        monkeypatch.setattr(_requests, "get", lambda *a, **kw: (_ for _ in ()).throw(Exception("no-call")))
        # Remove yfinance entirely
        monkeypatch.setitem(sys.modules, "yfinance", None)

        result = gms.fetch_us_market_data("")
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# fetch_korean_market — yfinance branch
# ---------------------------------------------------------------------------


class TestFetchKoreanMarket:
    def _make_yf_stub(self, price, prev):
        fi = type("FI", (), {"last_price": price, "previous_close": prev})()
        ticker = type("T", (), {"fast_info": fi})()
        return type("yf", (), {"Ticker": staticmethod(lambda sym: ticker)})()

    def test_parses_kospi_data(self, monkeypatch):
        import sys

        monkeypatch.setitem(sys.modules, "yfinance", self._make_yf_stub(2500.0, 2450.0))

        result = gms.fetch_korean_market()
        assert "KOSPI" in result
        assert result["KOSPI"]["price"] == "2,500.00"

    def test_change_and_pct_calculated(self, monkeypatch):
        import sys

        monkeypatch.setitem(sys.modules, "yfinance", self._make_yf_stub(2500.0, 2450.0))

        result = gms.fetch_korean_market()
        # change = 2500 - 2450 = +50
        assert "+50.00" in result["KOSPI"]["change"]
        # pct = 50/2450 * 100 ≈ +2.04%
        assert "+" in result["KOSPI"]["change_pct"]

    def test_returns_all_three_symbols(self, monkeypatch):
        import sys

        monkeypatch.setitem(sys.modules, "yfinance", self._make_yf_stub(1000.0, 990.0))

        result = gms.fetch_korean_market()
        # ^KS11 → KOSPI, ^KQ11 → KOSDAQ, KRW=X → USD/KRW 환율
        assert "KOSPI" in result
        assert "KOSDAQ" in result
        assert "USD/KRW 환율" in result

    def test_none_price_skips_symbol(self, monkeypatch):
        import sys

        monkeypatch.setitem(sys.modules, "yfinance", self._make_yf_stub(None, 1000.0))

        result = gms.fetch_korean_market()
        assert result == {}

    def test_yfinance_import_error_returns_empty(self, monkeypatch):
        import sys

        monkeypatch.setitem(sys.modules, "yfinance", None)

        result = gms.fetch_korean_market()
        assert result == {}

    def test_ticker_exception_skips_and_continues(self, monkeypatch):
        import sys

        class BrokenFI:
            @property
            def last_price(self):
                raise RuntimeError("yf error")

            previous_close = 1000.0

        class BrokenTicker:
            fast_info = BrokenFI()

        yf_stub = type("yf", (), {"Ticker": staticmethod(lambda sym: BrokenTicker())})()
        monkeypatch.setitem(sys.modules, "yfinance", yf_stub)

        result = gms.fetch_korean_market()
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# fetch_commodity_data — yfinance branch
# ---------------------------------------------------------------------------


class TestFetchCommodityData:
    def _make_yf_stub(self, price, prev):
        fi = type("FI", (), {"last_price": price, "previous_close": prev})()
        ticker = type("T", (), {"fast_info": fi})()
        return type("yf", (), {"Ticker": staticmethod(lambda sym: ticker)})()

    def test_parses_gold_data(self, monkeypatch):
        import sys

        monkeypatch.setitem(sys.modules, "yfinance", self._make_yf_stub(1950.0, 1940.0))

        result = gms.fetch_commodity_data()
        assert "금 (Gold)" in result
        assert result["금 (Gold)"]["price"] == "1,950.00"

    def test_returns_all_four_commodities(self, monkeypatch):
        import sys

        monkeypatch.setitem(sys.modules, "yfinance", self._make_yf_stub(100.0, 98.0))

        result = gms.fetch_commodity_data()
        assert "금 (Gold)" in result
        assert "원유 (WTI)" in result
        assert "천연가스" in result
        assert "달러 인덱스 (DXY)" in result

    def test_change_pct_sign_positive(self, monkeypatch):
        import sys

        monkeypatch.setitem(sys.modules, "yfinance", self._make_yf_stub(100.0, 98.0))

        result = gms.fetch_commodity_data()
        # (100 - 98) / 98 * 100 ≈ +2.04%
        assert "+" in result["금 (Gold)"]["change_pct"]

    def test_change_pct_sign_negative(self, monkeypatch):
        import sys

        monkeypatch.setitem(sys.modules, "yfinance", self._make_yf_stub(95.0, 100.0))

        result = gms.fetch_commodity_data()
        assert "-" in result["금 (Gold)"]["change_pct"]

    def test_none_price_skips_commodity(self, monkeypatch):
        import sys

        monkeypatch.setitem(sys.modules, "yfinance", self._make_yf_stub(None, 100.0))

        result = gms.fetch_commodity_data()
        assert result == {}

    def test_yfinance_import_error_returns_empty(self, monkeypatch):
        import sys

        monkeypatch.setitem(sys.modules, "yfinance", None)

        result = gms.fetch_commodity_data()
        assert result == {}


# ---------------------------------------------------------------------------
# fetch_fred_indicators — mocked HTTP via request_with_retry
# ---------------------------------------------------------------------------


class TestFetchFredIndicators:
    def _obs(self, value, date="2024-01-15", prev_value="4.50", prev_date="2023-12-15"):
        return {
            "observations": [
                {"value": str(value), "date": date},
                {"value": prev_value, "date": prev_date},
            ]
        }

    def test_no_api_key_returns_empty(self):
        result = gms.fetch_fred_indicators("")
        assert result == {}

    def test_parses_fed_rate_observation(self, monkeypatch):
        mock_resp = type("R", (), {"json": lambda self: self._data})()
        mock_resp._data = self._obs("5.25", prev_value="5.00")

        import scripts.generate_market_summary as _gms

        monkeypatch.setattr(_gms, "request_with_retry", lambda *a, **kw: mock_resp)

        result = gms.fetch_fred_indicators("FAKE_KEY")
        assert "FED_RATE" in result
        assert result["FED_RATE"]["value"] == 5.25
        assert result["FED_RATE"]["label"] == "연방기금금리"

    def test_change_calculated_from_two_observations(self, monkeypatch):
        mock_resp = type("R", (), {"json": lambda self: self._data})()
        mock_resp._data = self._obs("5.25", prev_value="5.00")

        import scripts.generate_market_summary as _gms

        monkeypatch.setattr(_gms, "request_with_retry", lambda *a, **kw: mock_resp)

        result = gms.fetch_fred_indicators("FAKE_KEY")
        assert abs(result["FED_RATE"]["change"] - 0.25) < 0.001

    def test_dot_value_skips_observation(self, monkeypatch):
        # FRED returns "." for missing data
        mock_resp = type("R", (), {"json": lambda self: self._data})()
        mock_resp._data = {"observations": [{"value": ".", "date": "2024-01-15"}]}

        import scripts.generate_market_summary as _gms

        monkeypatch.setattr(_gms, "request_with_retry", lambda *a, **kw: mock_resp)

        result = gms.fetch_fred_indicators("FAKE_KEY")
        assert "FED_RATE" not in result

    def test_single_observation_change_is_none(self, monkeypatch):
        mock_resp = type("R", (), {"json": lambda self: self._data})()
        mock_resp._data = {"observations": [{"value": "5.25", "date": "2024-01-15"}]}

        import scripts.generate_market_summary as _gms

        monkeypatch.setattr(_gms, "request_with_retry", lambda *a, **kw: mock_resp)

        result = gms.fetch_fred_indicators("FAKE_KEY")
        assert result["FED_RATE"]["change"] is None

    def test_exception_skips_indicator_and_continues(self, monkeypatch):
        import scripts.generate_market_summary as _gms

        call_count = {"n": 0}

        def failing_retry(*a, **kw):
            call_count["n"] += 1
            raise RuntimeError("network error")

        monkeypatch.setattr(_gms, "request_with_retry", failing_retry)

        result = gms.fetch_fred_indicators("FAKE_KEY")
        assert isinstance(result, dict)
        # Should have attempted all 11 indicators
        assert call_count["n"] == 11

    def test_date_stored_from_observation(self, monkeypatch):
        mock_resp = type("R", (), {"json": lambda self: self._data})()
        mock_resp._data = self._obs("4.00", date="2024-03-01")

        import scripts.generate_market_summary as _gms

        monkeypatch.setattr(_gms, "request_with_retry", lambda *a, **kw: mock_resp)

        result = gms.fetch_fred_indicators("FAKE_KEY")
        assert result["FED_RATE"]["date"] == "2024-03-01"

    def test_prev_dot_value_change_is_none(self, monkeypatch):
        mock_resp = type("R", (), {"json": lambda self: self._data})()
        mock_resp._data = {
            "observations": [
                {"value": "5.25", "date": "2024-01-15"},
                {"value": ".", "date": "2023-12-15"},
            ]
        }

        import scripts.generate_market_summary as _gms

        monkeypatch.setattr(_gms, "request_with_retry", lambda *a, **kw: mock_resp)

        result = gms.fetch_fred_indicators("FAKE_KEY")
        assert result["FED_RATE"]["change"] is None


# ---------------------------------------------------------------------------
# fetch_sector_performance — yfinance branch
# ---------------------------------------------------------------------------


class TestFetchSectorPerformance:
    def _make_yf_stub(self, price, prev):
        fi = type("FI", (), {"last_price": price, "previous_close": prev})()
        ticker = type("T", (), {"fast_info": fi})()
        return type("yf", (), {"Ticker": staticmethod(lambda sym: ticker)})()

    def test_returns_sector_data_with_name(self, monkeypatch):
        import sys

        monkeypatch.setitem(sys.modules, "yfinance", self._make_yf_stub(200.0, 195.0))

        result = gms.fetch_sector_performance()
        assert "XLK" in result
        assert result["XLK"]["name"] == "기술 (Technology)"

    def test_returns_all_11_sectors(self, monkeypatch):
        import sys

        monkeypatch.setitem(sys.modules, "yfinance", self._make_yf_stub(100.0, 99.0))

        result = gms.fetch_sector_performance()
        expected = {"XLK", "XLF", "XLE", "XLV", "XLI", "XLC", "XLP", "XLY", "XLU", "XLRE", "XLB"}
        assert expected == set(result.keys())

    def test_change_pct_is_float(self, monkeypatch):
        import sys

        monkeypatch.setitem(sys.modules, "yfinance", self._make_yf_stub(110.0, 100.0))

        result = gms.fetch_sector_performance()
        assert isinstance(result["XLK"]["change_pct"], float)
        assert abs(result["XLK"]["change_pct"] - 10.0) < 0.01

    def test_price_formatted_as_string(self, monkeypatch):
        import sys

        monkeypatch.setitem(sys.modules, "yfinance", self._make_yf_stub(199.50, 198.0))

        result = gms.fetch_sector_performance()
        assert result["XLK"]["price"] == "199.50"

    def test_none_price_skips_sector(self, monkeypatch):
        import sys

        monkeypatch.setitem(sys.modules, "yfinance", self._make_yf_stub(None, 100.0))

        result = gms.fetch_sector_performance()
        assert result == {}

    def test_yfinance_import_error_returns_empty(self, monkeypatch):
        import sys

        monkeypatch.setitem(sys.modules, "yfinance", None)

        result = gms.fetch_sector_performance()
        assert result == {}


# ---------------------------------------------------------------------------
# fetch_btc_etf_data — yfinance + rss_fetcher branch
# ---------------------------------------------------------------------------


def _patch_rss_fetcher(monkeypatch, return_value):
    """Patch fetch_rss_feeds_concurrent on the module that gms resolves at call time.

    gms inserts scripts/ onto sys.path then does:
        from common.rss_fetcher import fetch_rss_feeds_concurrent
    so the live module is sys.modules["common.rss_fetcher"].
    """
    _rss = sys.modules["common.rss_fetcher"]
    monkeypatch.setattr(_rss, "fetch_rss_feeds_concurrent", lambda feeds: return_value)


def _patch_rss_fetcher_capture(monkeypatch):
    """Patch and return a capture dict that records the feeds argument."""
    _rss = sys.modules["common.rss_fetcher"]
    captured = {}

    def fake_rss(feeds):
        captured["feeds"] = feeds
        return []

    monkeypatch.setattr(_rss, "fetch_rss_feeds_concurrent", fake_rss)
    return captured


class TestFetchBtcEtfData:
    def _make_yf_stub(self, price, prev):
        fi = type("FI", (), {"last_price": price, "previous_close": prev})()
        ticker = type("T", (), {"fast_info": fi})()
        return type("yf", (), {"Ticker": staticmethod(lambda sym: ticker)})()

    def _patch_rss(self, monkeypatch, return_value):
        _patch_rss_fetcher(monkeypatch, return_value)

    def test_returns_etfs_and_news_keys(self, monkeypatch):
        import sys

        monkeypatch.setitem(sys.modules, "yfinance", self._make_yf_stub(35.0, 34.0))
        self._patch_rss(monkeypatch, [])

        result = gms.fetch_btc_etf_data()
        assert "etfs" in result
        assert "news" in result

    def test_parses_ibit_price(self, monkeypatch):
        import sys

        monkeypatch.setitem(sys.modules, "yfinance", self._make_yf_stub(35.50, 34.00))
        self._patch_rss(monkeypatch, [])

        result = gms.fetch_btc_etf_data()
        assert "IBIT" in result["etfs"]
        assert result["etfs"]["IBIT"]["price"] == "35.50"

    def test_parses_all_three_etfs(self, monkeypatch):
        import sys

        monkeypatch.setitem(sys.modules, "yfinance", self._make_yf_stub(30.0, 29.0))
        self._patch_rss(monkeypatch, [])

        result = gms.fetch_btc_etf_data()
        assert "IBIT" in result["etfs"]
        assert "FBTC" in result["etfs"]
        assert "GBTC" in result["etfs"]

    def test_change_pct_formatted_with_sign(self, monkeypatch):
        import sys

        monkeypatch.setitem(sys.modules, "yfinance", self._make_yf_stub(110.0, 100.0))
        self._patch_rss(monkeypatch, [])

        result = gms.fetch_btc_etf_data()
        assert result["etfs"]["IBIT"]["change_pct"] == "+10.00%"

    def test_news_items_from_rss_included(self, monkeypatch):
        import sys

        news = [{"title": "Bitcoin ETF 자금 유입", "link": "https://example.com"}]
        monkeypatch.setitem(sys.modules, "yfinance", self._make_yf_stub(None, 30.0))
        self._patch_rss(monkeypatch, news)

        result = gms.fetch_btc_etf_data()
        assert result["news"] == news

    def test_none_price_skips_etf(self, monkeypatch):
        import sys

        monkeypatch.setitem(sys.modules, "yfinance", self._make_yf_stub(None, 30.0))
        self._patch_rss(monkeypatch, [])

        result = gms.fetch_btc_etf_data()
        assert result["etfs"] == {}

    def test_yfinance_import_error_etfs_empty(self, monkeypatch):
        import sys

        monkeypatch.setitem(sys.modules, "yfinance", None)
        self._patch_rss(monkeypatch, [])

        result = gms.fetch_btc_etf_data()
        assert result["etfs"] == {}


# ---------------------------------------------------------------------------
# fetch_whale_trades — rss_fetcher branch
# ---------------------------------------------------------------------------


class TestFetchWhaleTrades:
    def test_returns_list(self, monkeypatch):
        _patch_rss_fetcher(monkeypatch, [])
        result = gms.fetch_whale_trades()
        assert isinstance(result, list)

    def test_passes_three_feeds_to_rss(self, monkeypatch):
        captured = _patch_rss_fetcher_capture(monkeypatch)
        gms.fetch_whale_trades()
        assert len(captured["feeds"]) == 3

    def test_returns_news_items_from_rss(self, monkeypatch):
        items = [
            {"title": "1000 BTC moved", "link": "https://whale-alert.io/1"},
            {"title": "500 ETH moved", "link": "https://whale-alert.io/2"},
        ]
        _patch_rss_fetcher(monkeypatch, items)
        result = gms.fetch_whale_trades()
        assert result == items

    def test_feeds_contain_whale_alert_url(self, monkeypatch):
        captured = _patch_rss_fetcher_capture(monkeypatch)
        gms.fetch_whale_trades()
        all_urls = [f[0] for f in captured["feeds"]]
        assert any("whale" in url.lower() for url in all_urls)

    def test_feeds_include_korean_language_feed(self, monkeypatch):
        captured = _patch_rss_fetcher_capture(monkeypatch)
        gms.fetch_whale_trades()
        tags_lists = [f[2] for f in captured["feeds"]]
        assert any("korean" in tags for tags in tags_lists)


# ---------------------------------------------------------------------------
# fetch_us_market_data — yfinance fallback for AV symbols (^GSPC etc.)
# ---------------------------------------------------------------------------


class TestFetchUsMarketDataYfinanceFallback:
    """Covers the yfinance fallback path for AV symbols when AV returns < 3 results."""

    def test_yfinance_fallback_fills_spy_when_av_incomplete(self, monkeypatch):
        import sys

        import requests as _requests

        # AV returns empty Global Quote → no SPY from AV
        empty_resp = type(
            "R",
            (),
            {
                "raise_for_status": lambda self: None,
                "json": lambda self: {"Global Quote": {}},
            },
        )()
        monkeypatch.setattr(_requests, "get", lambda *a, **kw: empty_resp)

        # yfinance returns valid data for ^GSPC → should fill SPY
        call_log = []

        def ticker_factory(sym):
            call_log.append(sym)
            if sym in ("^GSPC", "^IXIC", "^DJI", "^VIX"):
                fi = type("FI", (), {"last_price": 5000.0, "previous_close": 4950.0})()
            else:
                fi = type("FI", (), {"last_price": 100.0, "previous_close": 99.0})()
            return type("T", (), {"fast_info": fi})()

        yf_stub = type("yf", (), {"Ticker": staticmethod(ticker_factory)})()
        monkeypatch.setitem(sys.modules, "yfinance", yf_stub)

        result = gms.fetch_us_market_data("FAKE_KEY")
        assert "SPY" in result
        assert result["SPY"]["price"] == "5,000.00"

    def test_fallback_skips_already_fetched_symbols(self, monkeypatch):
        """If SPY was already fetched from AV, yfinance fallback should not overwrite it."""
        import sys

        import requests as _requests

        # AV returns valid SPY only
        call_count = {"n": 0}

        def fake_get(url, params=None, **kw):
            sym = (params or {}).get("symbol", "")
            call_count["n"] += 1
            if sym == "SPY":
                return type(
                    "R",
                    (),
                    {
                        "raise_for_status": lambda self: None,
                        "json": lambda self: {
                            "Global Quote": {
                                "05. price": "499.00",
                                "09. change": "+1.00",
                                "10. change percent": "+0.20%",
                                "06. volume": "1000",
                            }
                        },
                    },
                )()
            return type(
                "R",
                (),
                {
                    "raise_for_status": lambda self: None,
                    "json": lambda self: {"Global Quote": {}},
                },
            )()

        monkeypatch.setattr(_requests, "get", fake_get)

        yf_ticker_calls = []

        def ticker_factory(sym):
            yf_ticker_calls.append(sym)
            fi = type("FI", (), {"last_price": 9999.0, "previous_close": 1.0})()
            return type("T", (), {"fast_info": fi})()

        yf_stub = type("yf", (), {"Ticker": staticmethod(ticker_factory)})()
        monkeypatch.setitem(sys.modules, "yfinance", yf_stub)

        result = gms.fetch_us_market_data("FAKE_KEY")
        # SPY came from AV; yfinance fallback must not overwrite it
        assert result.get("SPY", {}).get("price") == "499.00"


# ---------------------------------------------------------------------------
# main() integration smoke tests
# ---------------------------------------------------------------------------

_GMS = "scripts.generate_market_summary"

# Fetch functions that live directly on the gms module (not sub-attributes)
_FETCH_PATCHES = {
    f"{_GMS}.fetch_coingecko_top_coins": [
        {
            "symbol": "BTC",
            "current_price": 95000,
            "price_change_percentage_24h": 1.5,
            "market_cap": 1_800_000_000_000,
        },
        {
            "symbol": "ETH",
            "current_price": 3500,
            "price_change_percentage_24h": -0.5,
            "market_cap": 420_000_000_000,
        },
    ],
    f"{_GMS}.fetch_coingecko_global": {
        "total_market_cap": {"usd": 2_500_000_000_000},
        "market_cap_percentage": {"btc": 55.0},
        "market_cap_change_percentage_24h_usd": 1.2,
    },
    f"{_GMS}.fetch_coingecko_trending": [],
    f"{_GMS}.fetch_fear_greed_index": {"value": 65, "classification": "Greed"},
    f"{_GMS}.fetch_us_market_data": {},
    f"{_GMS}.fetch_korean_market": {"KOSPI": {"price": "2500.00", "change": "+25.00", "change_pct": "+1.00%"}},
    f"{_GMS}.fetch_commodity_data": {},
    f"{_GMS}.fetch_fred_indicators": {},
    f"{_GMS}.fetch_sector_performance": {},
    f"{_GMS}.fetch_btc_etf_data": {},
    f"{_GMS}.fetch_whale_trades": [],
    # time.sleep lives on the imported `time` module; patch via stdlib
    "time.sleep": None,
}

_EMPTY_FETCH_PATCHES = {k: ([] if any(x in k for x in ("coins", "whale", "trending")) else {}) for k in _FETCH_PATCHES}
_EMPTY_FETCH_PATCHES["time.sleep"] = None


@contextmanager
def _apply_fetch_patches(overrides=None):
    """Start all fetch patches, yield, then stop them."""
    targets = dict(_FETCH_PATCHES)
    if overrides:
        targets.update(overrides)
    active = []
    try:
        for target, retval in targets.items():
            p = patch(target, return_value=retval)
            p.start()
            active.append(p)
        yield
    finally:
        for p in active:
            p.stop()


class TestMainIntegration:
    """Integration smoke tests for main() — all network I/O is mocked."""

    def _mock_gen(self, tmp_path, filename="post.md"):
        m = MagicMock()
        m.create_post.return_value = str(tmp_path / filename)
        return m

    def _mock_dedup(self, is_dup=False):
        m = MagicMock()
        m.is_duplicate_exact.return_value = is_dup
        return m

    def test_create_post_is_called_with_title_and_tags(self, tmp_path):
        """main() calls PostGenerator.create_post with title and tags arguments."""
        mock_gen = self._mock_gen(tmp_path)
        mock_dedup = self._mock_dedup()

        with (
            _apply_fetch_patches(),
            patch(f"{_GMS}.PostGenerator", return_value=mock_gen),
            patch(f"{_GMS}.DedupEngine", return_value=mock_dedup),
        ):
            gms.main()

        mock_gen.create_post.assert_called_once()
        kw = mock_gen.create_post.call_args.kwargs
        assert "title" in kw, "create_post must receive a 'title' kwarg"
        assert "tags" in kw, "create_post must receive a 'tags' kwarg"
        assert isinstance(kw["tags"], list)

    def test_dedup_engine_checked_before_writing(self, tmp_path):
        """main() calls is_duplicate_exact and save on DedupEngine."""
        mock_gen = self._mock_gen(tmp_path)
        mock_dedup = self._mock_dedup()

        with (
            _apply_fetch_patches(),
            patch(f"{_GMS}.PostGenerator", return_value=mock_gen),
            patch(f"{_GMS}.DedupEngine", return_value=mock_dedup),
        ):
            gms.main()

        mock_dedup.is_duplicate_exact.assert_called_once()
        mock_dedup.save.assert_called()

    def test_duplicate_detected_skips_post_creation(self, tmp_path):
        """main() skips PostGenerator.create_post when DedupEngine reports a duplicate."""
        mock_gen = self._mock_gen(tmp_path)
        mock_dedup = self._mock_dedup(is_dup=True)

        with (
            _apply_fetch_patches(),
            patch(f"{_GMS}.PostGenerator", return_value=mock_gen),
            patch(f"{_GMS}.DedupEngine", return_value=mock_dedup),
        ):
            gms.main()

        mock_gen.create_post.assert_not_called()
        mock_dedup.save.assert_called()

    def test_empty_data_sources_completes_without_error(self, tmp_path):
        """main() does not raise when all fetch functions return empty collections."""
        mock_gen = self._mock_gen(tmp_path)
        mock_dedup = self._mock_dedup()

        with (
            _apply_fetch_patches(overrides=_EMPTY_FETCH_PATCHES),
            patch(f"{_GMS}.PostGenerator", return_value=mock_gen),
            patch(f"{_GMS}.DedupEngine", return_value=mock_dedup),
        ):
            gms.main()  # must not raise

    def test_post_description_contains_date(self, tmp_path):
        """The extra_frontmatter description passed to create_post contains a date string."""
        mock_gen = self._mock_gen(tmp_path)
        mock_dedup = self._mock_dedup()

        with (
            _apply_fetch_patches(),
            patch(f"{_GMS}.PostGenerator", return_value=mock_gen),
            patch(f"{_GMS}.DedupEngine", return_value=mock_dedup),
        ):
            gms.main()

        mock_gen.create_post.assert_called_once()
        extra_fm = mock_gen.create_post.call_args.kwargs.get("extra_frontmatter", {})
        desc = extra_fm.get("description", "")
        assert _re.search(r"\d{4}-\d{2}-\d{2}", desc), f"description must contain a YYYY-MM-DD date, got: {desc!r}"


# ---------------------------------------------------------------------------
# 시간 프레임 라벨 검증 (time-frame label regression tests)
# ---------------------------------------------------------------------------


class TestMomentumPeriodLabel:
    """모멘텀 raw_display에 기간 라벨이 포함되는지 검증."""

    def test_momentum_7d_label_in_raw_display(self):
        """btc_7d/eth_7d 입력 시 raw_display에 '7d' 라벨이 포함돼야 한다."""
        from scripts.common.signal_composer import SignalComposer

        composer = SignalComposer()
        result = composer.compose_signals(
            {
                "momentum": {
                    "btc_7d": 5.3,
                    "eth_7d": 4.2,
                }
            }
        )
        momentum_sr = next(sr for sr in result.signal_results if sr.name == "모멘텀")
        assert "7d" in momentum_sr.raw_display, f"raw_display should contain '7d', got: {momentum_sr.raw_display!r}"

    def test_momentum_24h_label_in_raw_display(self):
        """btc_24h/eth_24h 입력 시 raw_display에 '24h' 라벨이 포함돼야 한다."""
        from scripts.common.signal_composer import SignalComposer

        composer = SignalComposer()
        result = composer.compose_signals(
            {
                "momentum": {
                    "btc_24h": -1.0,
                    "eth_24h": -2.0,
                }
            }
        )
        momentum_sr = next(sr for sr in result.signal_results if sr.name == "모멘텀")
        assert "24h" in momentum_sr.raw_display, f"raw_display should contain '24h', got: {momentum_sr.raw_display!r}"


class TestSignalTablePeriodColumn:
    """generate_outlook_markdown / generate_prediction_markdown 테이블에 '기간' 컬럼 존재 검증."""

    def _make_result(self):
        from scripts.common.signal_composer import SignalComposer

        composer = SignalComposer()
        return composer.compose_signals(
            {
                "fear_greed": {"value": 27, "label": "Fear"},
                "momentum": {"btc_7d": 5.3, "eth_7d": 4.2},
            }
        )

    def test_outlook_markdown_has_period_column_header(self):
        from scripts.common.signal_composer import SignalComposer

        result = self._make_result()
        md = SignalComposer().generate_outlook_markdown(result)
        assert "| 기간 |" in md, f"'| 기간 |' header not found in:\n{md}"

    def test_prediction_markdown_has_period_column_header(self):
        from scripts.common.signal_composer import SignalComposer, analyze_stance

        result = self._make_result()
        stance = analyze_stance(result)
        md = SignalComposer().generate_prediction_markdown(result, stance)
        assert "| 기간 |" in md, f"'| 기간 |' header not found in:\n{md}"
