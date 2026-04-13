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
        data = {
            "KOSPI": {"price": "2500.00", "change": "+20.00", "change_pct": "+0.81%"}
        }
        result = gms.format_korean_market(data)
        assert "KOSPI" in result
        assert "2500.00" in result

    def test_positive_change_shows_green_icon(self):
        data = {
            "KOSPI": {"price": "2500.00", "change": "+20.00", "change_pct": "+0.81%"}
        }
        result = gms.format_korean_market(data)
        assert "🟢" in result

    def test_negative_change_shows_red_icon(self):
        data = {
            "KOSDAQ": {"price": "800.00", "change": "-5.00", "change_pct": "-0.62%"}
        }
        result = gms.format_korean_market(data)
        assert "🔴" in result

    def test_invalid_change_pct_no_crash(self):
        data = {
            "KOSPI": {"price": "N/A", "change": "N/A", "change_pct": "N/A"}
        }
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
        coins = [
            {"item": {"name": f"Coin{i}", "symbol": f"C{i}", "market_cap_rank": i}}
            for i in range(1, 15)
        ]
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
        kr_market = {
            "KOSPI": {"price": "2500.00", "change": "+10.00", "change_pct": "+0.40%"}
        }
        result = gms.generate_key_highlights({}, [], {}, kr_market)
        assert "KOSPI" in result

    def test_commodity_gold_bullet_present(self):
        commodity = {
            "금 (Gold)": {"price": "1950.00", "change": "+10.00", "change_pct": "+0.52%"}
        }
        result = gms.generate_key_highlights({}, [], {}, {}, commodity_data=commodity)
        assert "금" in result

    def test_commodity_oil_bullet_present(self):
        commodity = {
            "원유 (WTI)": {"price": "78.00", "change": "-0.50", "change_pct": "-0.64%"}
        }
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
        kr_market = {
            "KOSPI": {"price": "2500.00", "change": "+10.00", "change_pct": "+0.40%"}
        }
        result = gms.generate_insight(self._global(0.0, 50), [], {}, {}, kr_market)
        assert "KOSPI" in result

    def test_usdkrw_included_when_present(self):
        kr_market = {
            "USD/KRW 환율": {"price": "1320.00", "change": "+2.00", "change_pct": "+0.15%"}
        }
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
