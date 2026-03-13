"""Tests for entity_extractor module (scripts/common/entity_extractor.py)."""

from common.entity_extractor import (
    _format_group_label,
    extract_entities,
    extract_market_signals,
    group_related_items,
)


class TestExtractEntitiesCrypto:
    """Tests for crypto entity detection in extract_entities()."""

    def test_bitcoin_by_ticker(self):
        result = extract_entities("BTC surges past $100K")
        assert "bitcoin" in result["crypto"]

    def test_bitcoin_by_english_name(self):
        result = extract_entities("Bitcoin price hits all-time high")
        assert "bitcoin" in result["crypto"]

    def test_bitcoin_by_korean_name(self):
        result = extract_entities("비트코인 가격이 급등했습니다")
        assert "bitcoin" in result["crypto"]

    def test_ethereum_by_ticker(self):
        result = extract_entities("ETH network upgrade complete")
        assert "ethereum" in result["crypto"]

    def test_ethereum_by_korean(self):
        result = extract_entities("이더리움 가격 변동")
        assert "ethereum" in result["crypto"]

    def test_xrp_detected(self):
        result = extract_entities("XRP gains 20% in a week")
        assert "xrp" in result["crypto"]

    def test_solana_by_ticker(self):
        result = extract_entities("SOL reaches new monthly high")
        assert "solana" in result["crypto"]

    def test_multiple_crypto_detected(self):
        result = extract_entities("BTC and ETH both rise today")
        assert "bitcoin" in result["crypto"]
        assert "ethereum" in result["crypto"]

    def test_no_crypto_in_irrelevant_text(self):
        result = extract_entities("The stock market opened higher today")
        assert result["crypto"] == []

    def test_no_duplicate_crypto(self):
        result = extract_entities("Bitcoin BTC 비트코인 all mentioned")
        assert result["crypto"].count("bitcoin") == 1


class TestExtractEntitiesStock:
    """Tests for stock entity detection in extract_entities()."""

    def test_apple_by_ticker(self):
        result = extract_entities("AAPL earnings beat expectations")
        assert "apple" in result["stock"]

    def test_nvidia_by_name(self):
        result = extract_entities("Nvidia GPU demand continues to surge")
        assert "nvidia" in result["stock"]

    def test_nvidia_by_korean(self):
        result = extract_entities("엔비디아 주가 최고치 경신")
        assert "nvidia" in result["stock"]

    def test_tesla_by_ticker(self):
        result = extract_entities("TSLA drops 5% after delivery miss")
        assert "tesla" in result["stock"]

    def test_samsung_by_korean(self):
        result = extract_entities("삼성전자 반도체 실적 발표")
        assert "samsung" in result["stock"]

    def test_google_by_ticker(self):
        result = extract_entities("GOOG reports record revenue")
        assert "google" in result["stock"]

    def test_multiple_stocks(self):
        result = extract_entities("AAPL and MSFT both hit new highs")
        assert "apple" in result["stock"]
        assert "microsoft" in result["stock"]

    def test_no_duplicate_stock(self):
        result = extract_entities("Apple AAPL 애플 earnings")
        assert result["stock"].count("apple") == 1


class TestExtractEntitiesIndex:
    """Tests for index entity detection in extract_entities()."""

    def test_sp500_detected(self):
        result = extract_entities("S&P 500 closes at record high")
        assert "sp500" in result["index"]

    def test_nasdaq_by_korean(self):
        result = extract_entities("나스닥 지수 2% 상승")
        assert "nasdaq" in result["index"]

    def test_kospi_detected(self):
        result = extract_entities("코스피 2,600 돌파")
        assert "kospi" in result["index"]

    def test_vix_detected(self):
        result = extract_entities("VIX spikes to 30 amid market turmoil")
        assert "vix" in result["index"]

    def test_dow_detected(self):
        result = extract_entities("Dow Jones Industrial Average falls 300 points")
        assert "dow" in result["index"]


class TestExtractEntitiesPerson:
    """Tests for person entity detection in extract_entities()."""

    def test_trump_by_english(self):
        result = extract_entities("Trump signs executive order on crypto")
        assert "trump" in result["person"]

    def test_trump_by_korean(self):
        result = extract_entities("트럼프 관세 정책 발표")
        assert "trump" in result["person"]

    def test_powell_detected(self):
        result = extract_entities("Powell signals rate cut in September")
        assert "powell" in result["person"]

    def test_musk_detected(self):
        result = extract_entities("Elon Musk tweets about Dogecoin")
        assert "musk" in result["person"]

    def test_buffett_detected(self):
        result = extract_entities("Berkshire Hathaway reports earnings")
        assert "buffett" in result["person"]

    def test_no_person_in_generic_text(self):
        result = extract_entities("The market moved higher on strong data")
        assert result["person"] == []


class TestExtractEntitiesOrg:
    """Tests for organization entity detection in extract_entities()."""

    def test_fed_by_english(self):
        result = extract_entities("Federal Reserve holds rates steady")
        assert "fed" in result["org"]

    def test_fed_by_korean(self):
        result = extract_entities("연준 금리 동결 결정")
        assert "fed" in result["org"]

    def test_sec_detected(self):
        result = extract_entities("SEC approves spot Bitcoin ETF")
        assert "sec" in result["org"]

    def test_binance_by_korean(self):
        result = extract_entities("바이낸스 거래량 급감")
        assert "binance" in result["org"]

    def test_coinbase_detected(self):
        result = extract_entities("Coinbase quarterly earnings disappoint")
        assert "coinbase" in result["org"]

    def test_bok_detected(self):
        result = extract_entities("한국은행 기준금리 결정")
        assert "bok" in result["org"]


class TestExtractEntitiesTheme:
    """Tests for theme detection in extract_entities()."""

    def test_rate_theme_english(self):
        result = extract_entities("Fed considers rate cut amid inflation concerns")
        assert "금리" in result["theme"]

    def test_inflation_theme(self):
        result = extract_entities("CPI data shows inflation cooling")
        assert "인플레이션" in result["theme"]

    def test_etf_theme(self):
        result = extract_entities("Bitcoin ETF sees record inflows")
        assert "ETF" in result["theme"]

    def test_regulation_theme(self):
        result = extract_entities("New regulation targets crypto exchanges")
        assert "규제" in result["theme"]

    def test_hacking_theme(self):
        result = extract_entities("Exchange suffers major hack exploit")
        assert "해킹" in result["theme"]

    def test_ipo_theme_korean(self):
        result = extract_entities("카카오 IPO 공모 일정 발표")
        assert "IPO" in result["theme"]

    def test_earnings_theme(self):
        result = extract_entities("Strong earnings revenue beat expectations")
        assert "실적" in result["theme"]

    def test_trade_war_theme_korean(self):
        result = extract_entities("미국 관세 부과로 무역 갈등 심화")
        assert "무역전쟁" in result["theme"]

    def test_ai_theme(self):
        result = extract_entities("AI investment boom drives tech stocks")
        assert "AI" in result["theme"]

    def test_semiconductor_theme_korean(self):
        result = extract_entities("반도체 chip 수요 급증")
        assert "반도체" in result["theme"]

    def test_multiple_themes_detected(self):
        result = extract_entities("Fed rate cut fuels ETF buying amid inflation fears")
        # Multiple themes should be detected
        assert len(result["theme"]) >= 2


class TestExtractEntitiesEmpty:
    """Edge cases for extract_entities()."""

    def test_empty_string(self):
        result = extract_entities("")
        assert result["crypto"] == []
        assert result["stock"] == []
        assert result["index"] == []
        assert result["person"] == []
        assert result["org"] == []
        assert result["theme"] == []

    def test_returns_all_six_keys(self):
        result = extract_entities("some text")
        assert set(result.keys()) == {"crypto", "stock", "index", "person", "org", "theme"}

    def test_unrelated_text(self):
        result = extract_entities("The weather is nice today in Seoul")
        assert result["crypto"] == []
        assert result["stock"] == []

    def test_case_insensitive_ticker(self):
        # "btc" lowercase should still match
        result = extract_entities("The btc price is rising")
        assert "bitcoin" in result["crypto"]


class TestGroupRelatedItems:
    """Tests for group_related_items()."""

    def test_empty_list_returns_empty(self):
        result = group_related_items([])
        assert result == {}

    def test_single_item_goes_to_other(self):
        items = [{"title": "Bitcoin rises 5%", "description": ""}]
        result = group_related_items(items)
        # Single item can't form a group of 2+; goes to "기타 뉴스"
        assert "기타 뉴스" in result

    def test_two_bitcoin_items_grouped(self):
        items = [
            {"title": "Bitcoin BTC price surges", "description": ""},
            {"title": "BTC reaches new all-time high", "description": ""},
        ]
        result = group_related_items(items)
        # Should have a bitcoin group
        all_items_in_groups = sum(len(v) for v in result.values())
        assert all_items_in_groups == 2

    def test_ungrouped_items_go_to_other(self):
        items = [
            {"title": "Bitcoin BTC price surges", "description": ""},
            {"title": "BTC reaches new all-time high", "description": ""},
            {"title": "Some unrelated topic XYZ", "description": ""},
        ]
        result = group_related_items(items)
        # Unrelated item should be in "기타 뉴스"
        assert "기타 뉴스" in result
        assert len(result["기타 뉴스"]) == 1

    def test_groups_by_shared_entity(self):
        items = [
            {"title": "Fed raises interest rates", "description": ""},
            {"title": "Federal Reserve policy update", "description": ""},
            {"title": "Bitcoin market update", "description": ""},
        ]
        result = group_related_items(items)
        # Fed items should be grouped
        total = sum(len(v) for v in result.values())
        assert total == 3

    def test_entities_attached_to_items(self):
        items = [{"title": "Bitcoin rises", "description": ""}]
        group_related_items(items)
        assert "_entities" in items[0]

    def test_custom_title_key(self):
        items = [
            {"headline": "BTC price up", "description": ""},
            {"headline": "Bitcoin surges", "description": ""},
        ]
        result = group_related_items(items, title_key="headline")
        total = sum(len(v) for v in result.values())
        assert total == 2


class TestExtractMarketSignals:
    """Tests for extract_market_signals()."""

    def test_empty_list(self):
        result = extract_market_signals([])
        assert result["total_items"] == 0
        assert result["dominant_themes"] == []
        assert result["theme_coverage"] == 0

    def test_total_items_count(self):
        items = [
            {"title": "Bitcoin news", "description": ""},
            {"title": "Stock market update", "description": ""},
            {"title": "Fed rate decision", "description": ""},
        ]
        result = extract_market_signals(items)
        assert result["total_items"] == 3

    def test_dominant_themes_limited_to_five(self):
        # Create items with multiple different themes
        items = [
            {"title": "ETF rate cut inflation", "description": ""},
            {"title": "regulation hacking IPO", "description": ""},
            {"title": "AI semiconductor earnings tariff", "description": ""},
            {"title": "Federal Reserve rate hike", "description": ""},
            {"title": "CPI inflation ETF fund", "description": ""},
            {"title": "SEC regulation crypto bill", "description": ""},
        ]
        result = extract_market_signals(items)
        assert len(result["dominant_themes"]) <= 5

    def test_entity_frequencies_structure(self):
        items = [
            {"title": "Bitcoin BTC rises", "description": ""},
            {"title": "Bitcoin price up", "description": ""},
        ]
        result = extract_market_signals(items)
        assert "entity_frequencies" in result
        assert "crypto" in result["entity_frequencies"]
        assert result["entity_frequencies"]["crypto"].get("bitcoin", 0) == 2

    def test_theme_coverage_count(self):
        items = [
            {"title": "ETF rate inflation regulation", "description": ""},
        ]
        result = extract_market_signals(items)
        assert result["theme_coverage"] >= 2

    def test_returns_required_keys(self):
        result = extract_market_signals([])
        assert "entity_frequencies" in result
        assert "dominant_themes" in result
        assert "total_items" in result
        assert "theme_coverage" in result

    def test_custom_title_key(self):
        items = [
            {"headline": "BTC rises", "description": ""},
            {"headline": "Bitcoin surges", "description": ""},
        ]
        result = extract_market_signals(items, title_key="headline")
        assert result["total_items"] == 2


class TestFormatGroupLabel:
    """Tests for _format_group_label()."""

    def test_bitcoin_label(self):
        assert _format_group_label("crypto", "bitcoin") == "비트코인(BTC)"

    def test_ethereum_label(self):
        assert _format_group_label("crypto", "ethereum") == "이더리움(ETH)"

    def test_sp500_label(self):
        assert _format_group_label("index", "sp500") == "S&P 500"

    def test_nasdaq_label(self):
        assert _format_group_label("index", "nasdaq") == "나스닥"

    def test_nvidia_label(self):
        assert _format_group_label("stock", "nvidia") == "엔비디아(NVDA)"

    def test_trump_label(self):
        assert _format_group_label("person", "trump") == "트럼프"

    def test_fed_label(self):
        assert _format_group_label("org", "fed") == "연준(Fed)"

    def test_unknown_name_returns_name(self):
        assert _format_group_label("crypto", "unknowncoin") == "unknowncoin"

    def test_unknown_category_returns_name(self):
        assert _format_group_label("unknown_category", "somename") == "somename"

    def test_xrp_label(self):
        assert _format_group_label("crypto", "xrp") == "XRP"
