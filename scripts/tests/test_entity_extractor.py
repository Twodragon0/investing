"""Unit tests for common.entity_extractor module."""

import os
import sys

_SCRIPTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)


# ---------------------------------------------------------------------------
# extract_entities
# ---------------------------------------------------------------------------


class TestExtractEntities:
    def test_returns_all_categories(self):
        from common.entity_extractor import extract_entities

        result = extract_entities("no mentions here")
        assert set(result.keys()) == {"crypto", "stock", "index", "person", "org", "theme"}

    def test_empty_text_returns_empty_lists(self):
        from common.entity_extractor import extract_entities

        result = extract_entities("")
        for v in result.values():
            assert v == []

    # --- crypto ---

    def test_detects_bitcoin_by_ticker(self):
        from common.entity_extractor import extract_entities

        result = extract_entities("BTC price surges to new high")
        assert "bitcoin" in result["crypto"]

    def test_detects_bitcoin_by_korean(self):
        from common.entity_extractor import extract_entities

        result = extract_entities("비트코인 가격 급등")
        assert "bitcoin" in result["crypto"]

    def test_detects_ethereum(self):
        from common.entity_extractor import extract_entities

        result = extract_entities("Ethereum ETH upgrade complete")
        assert "ethereum" in result["crypto"]

    def test_detects_solana(self):
        from common.entity_extractor import extract_entities

        result = extract_entities("Solana network outage")
        assert "solana" in result["crypto"]

    def test_no_duplicate_crypto_entity(self):
        from common.entity_extractor import extract_entities

        result = extract_entities("Bitcoin BTC 비트코인 all in one title")
        assert result["crypto"].count("bitcoin") == 1

    def test_multiple_crypto_detected(self):
        from common.entity_extractor import extract_entities

        result = extract_entities("BTC and ETH both rally today")
        assert "bitcoin" in result["crypto"]
        assert "ethereum" in result["crypto"]

    # --- stock ---

    def test_detects_nvidia_by_ticker(self):
        from common.entity_extractor import extract_entities

        result = extract_entities("NVDA earnings beat expectations")
        assert "nvidia" in result["stock"]

    def test_detects_tesla_by_name(self):
        from common.entity_extractor import extract_entities

        result = extract_entities("Tesla cuts prices again")
        assert "tesla" in result["stock"]

    def test_detects_samsung_korean(self):
        from common.entity_extractor import extract_entities

        result = extract_entities("삼성전자 반도체 실적 발표")
        assert "samsung" in result["stock"]

    def test_no_duplicate_stock_entity(self):
        from common.entity_extractor import extract_entities

        result = extract_entities("Apple AAPL 애플 all mentioned")
        assert result["stock"].count("apple") == 1

    # --- index ---

    def test_detects_sp500(self):
        from common.entity_extractor import extract_entities

        result = extract_entities("S&P 500 drops on Fed concerns")
        assert "sp500" in result["index"]

    def test_detects_nasdaq(self):
        from common.entity_extractor import extract_entities

        result = extract_entities("NASDAQ hits record high")
        assert "nasdaq" in result["index"]

    def test_detects_kospi_korean(self):
        from common.entity_extractor import extract_entities

        result = extract_entities("코스피 2600선 회복")
        assert "kospi" in result["index"]

    def test_detects_vix(self):
        from common.entity_extractor import extract_entities

        result = extract_entities("VIX spikes above 30")
        assert "vix" in result["index"]

    # --- person ---

    def test_detects_trump(self):
        from common.entity_extractor import extract_entities

        result = extract_entities("Trump signs crypto executive order")
        assert "trump" in result["person"]

    def test_detects_powell(self):
        from common.entity_extractor import extract_entities

        result = extract_entities("Fed Chair Powell signals rate pause")
        assert "powell" in result["person"]

    def test_detects_musk(self):
        from common.entity_extractor import extract_entities

        result = extract_entities("Elon tweets about Dogecoin again")
        assert "musk" in result["person"]

    def test_detects_trump_korean(self):
        from common.entity_extractor import extract_entities

        result = extract_entities("트럼프 관세 정책 발표")
        assert "trump" in result["person"]

    # --- org ---

    def test_detects_fed(self):
        from common.entity_extractor import extract_entities

        result = extract_entities("Federal Reserve holds rates steady")
        assert "fed" in result["org"]

    def test_detects_sec(self):
        from common.entity_extractor import extract_entities

        result = extract_entities("SEC investigates crypto exchange")
        assert "sec" in result["org"]

    def test_detects_binance(self):
        from common.entity_extractor import extract_entities

        result = extract_entities("Binance launches new product")
        assert "binance" in result["org"]

    def test_detects_fed_korean(self):
        from common.entity_extractor import extract_entities

        result = extract_entities("연준 금리 동결 결정")
        assert "fed" in result["org"]

    # --- theme ---

    def test_detects_rate_theme(self):
        from common.entity_extractor import extract_entities

        result = extract_entities("rate cut expected next meeting")
        assert "금리" in result["theme"]

    def test_detects_inflation_theme(self):
        from common.entity_extractor import extract_entities

        result = extract_entities("CPI data shows rising inflation")
        assert "인플레이션" in result["theme"]

    def test_detects_ai_theme(self):
        from common.entity_extractor import extract_entities

        result = extract_entities("AI chip demand drives Nvidia growth")
        assert "AI" in result["theme"]

    def test_detects_hack_theme(self):
        from common.entity_extractor import extract_entities

        result = extract_entities("DeFi protocol suffers hack exploit")
        assert "해킹" in result["theme"]

    def test_detects_tariff_theme_korean(self):
        from common.entity_extractor import extract_entities

        result = extract_entities("트럼프 관세 부과 발표")
        assert "무역전쟁" in result["theme"]

    def test_no_false_positive_on_random_text(self):
        from common.entity_extractor import extract_entities

        result = extract_entities("weather forecast for tomorrow is sunny")
        assert result["crypto"] == []
        assert result["stock"] == []
        assert result["person"] == []

    def test_case_insensitive_ticker(self):
        from common.entity_extractor import extract_entities

        result = extract_entities("btc hits 100k")
        assert "bitcoin" in result["crypto"]


# ---------------------------------------------------------------------------
# extract_market_signals
# ---------------------------------------------------------------------------


class TestExtractMarketSignals:
    def _make_items(self, titles):
        return [{"title": t} for t in titles]

    def test_total_items_count(self):
        from common.entity_extractor import extract_market_signals

        items = self._make_items(["BTC rallies", "ETH drops", "NASDAQ gains"])
        result = extract_market_signals(items)
        assert result["total_items"] == 3

    def test_empty_items(self):
        from common.entity_extractor import extract_market_signals

        result = extract_market_signals([])
        assert result["total_items"] == 0
        assert result["dominant_themes"] == []
        assert result["theme_coverage"] == 0

    def test_entity_frequencies_structure(self):
        from common.entity_extractor import extract_market_signals

        items = self._make_items(["BTC up", "BTC down", "ETH up"])
        result = extract_market_signals(items)
        freq = result["entity_frequencies"]
        assert "crypto" in freq
        assert freq["crypto"]["bitcoin"] == 2
        assert freq["crypto"]["ethereum"] == 1

    def test_dominant_themes_sorted_by_count(self):
        from common.entity_extractor import extract_market_signals

        items = self._make_items(
            [
                "rate cut expected",
                "rate hike fears",
                "inflation CPI data",
                "Fed rate decision",
            ]
        )
        result = extract_market_signals(items)
        themes = result["dominant_themes"]
        assert len(themes) > 0
        # 금리 theme appears in 3 items; 인플레이션 in 1
        theme_names = [t[0] for t in themes]
        assert "금리" in theme_names
        # first entry should be the most frequent
        assert themes[0][1] >= themes[-1][1]

    def test_dominant_themes_capped_at_five(self):
        from common.entity_extractor import extract_market_signals

        items = self._make_items(
            [
                "rate cut inflation AI chip semiconductor ETF",
                "IPO earnings hack regulation tariff",
                "BTC ETH rate cut inflation AI",
            ]
        )
        result = extract_market_signals(items)
        assert len(result["dominant_themes"]) <= 5

    def test_theme_coverage_reflects_unique_themes(self):
        from common.entity_extractor import extract_market_signals

        items = self._make_items(["rate cut", "inflation CPI", "AI chip"])
        result = extract_market_signals(items)
        assert result["theme_coverage"] >= 3

    def test_custom_title_key(self):
        from common.entity_extractor import extract_market_signals

        items = [{"headline": "BTC surges"}, {"headline": "ETH drops"}]
        result = extract_market_signals(items, title_key="headline")
        assert result["total_items"] == 2
        assert "bitcoin" in result["entity_frequencies"].get("crypto", {})

    def test_description_field_also_searched(self):
        from common.entity_extractor import extract_market_signals

        items = [{"title": "market update", "description": "Bitcoin hits new high"}]
        result = extract_market_signals(items)
        assert "bitcoin" in result["entity_frequencies"].get("crypto", {})

    def test_stock_frequencies(self):
        from common.entity_extractor import extract_market_signals

        items = self._make_items(["Tesla TSLA earnings beat", "Tesla recall announced", "Apple AAPL report"])
        result = extract_market_signals(items)
        freq = result["entity_frequencies"]
        assert freq["stock"]["tesla"] == 2
        assert freq["stock"]["apple"] == 1


# ---------------------------------------------------------------------------
# group_related_items
# ---------------------------------------------------------------------------


class TestGroupRelatedItems:
    def _make_items(self, titles):
        return [{"title": t} for t in titles]

    def test_empty_input_returns_empty(self):
        from common.entity_extractor import group_related_items

        result = group_related_items([])
        assert result == {}

    def test_unrelated_items_go_to_ungrouped(self):
        from common.entity_extractor import group_related_items

        items = self._make_items(["weather sunny", "sports result"])
        result = group_related_items(items)
        assert "기타 뉴스" in result
        assert len(result["기타 뉴스"]) == 2

    def test_bitcoin_items_grouped_together(self):
        from common.entity_extractor import group_related_items

        items = self._make_items(
            [
                "Bitcoin BTC price hits 100k",
                "BTC whale moves coins",
                "Ethereum drops today",
            ]
        )
        result = group_related_items(items)
        # The two BTC items should share a group
        btc_group = None
        for _label, group_items in result.items():
            titles = [i["title"] for i in group_items]
            if any("BTC" in t for t in titles):
                btc_group = group_items
                break
        assert btc_group is not None
        assert len(btc_group) >= 2

    def test_group_label_bitcoin_korean(self):
        from common.entity_extractor import group_related_items

        items = self._make_items(
            [
                "Bitcoin rallies above 90k",
                "BTC ETF approved by SEC",
            ]
        )
        result = group_related_items(items)
        assert "비트코인(BTC)" in result

    def test_group_label_nvidia_korean(self):
        from common.entity_extractor import group_related_items

        items = self._make_items(
            [
                "Nvidia NVDA beats earnings",
                "NVDA stock hits new high",
            ]
        )
        result = group_related_items(items)
        assert "엔비디아(NVDA)" in result

    def test_single_item_not_grouped(self):
        from common.entity_extractor import group_related_items

        items = self._make_items(["Solana network update"])
        result = group_related_items(items)
        # Only one item so no entity-based group; goes to ungrouped
        assert "기타 뉴스" in result

    def test_entities_attached_to_items(self):
        from common.entity_extractor import group_related_items

        items = [{"title": "Bitcoin BTC rally"}]
        group_related_items(items)
        # group_related_items sets _entities on each item as a side-effect
        assert "_entities" in items[0]
        assert "bitcoin" in items[0]["_entities"]["crypto"]

    def test_custom_title_key(self):
        from common.entity_extractor import group_related_items

        items = [
            {"headline": "Bitcoin BTC surges"},
            {"headline": "BTC whale alert"},
        ]
        result = group_related_items(items, title_key="headline")
        assert "비트코인(BTC)" in result

    def test_all_items_accounted_for(self):
        from common.entity_extractor import group_related_items

        items = self._make_items(
            [
                "BTC rally",
                "BTC correction",
                "ETH upgrade",
                "weather news",
            ]
        )
        result = group_related_items(items)
        total = sum(len(v) for v in result.values())
        assert total == len(items)

    def test_no_item_in_multiple_groups(self):
        from common.entity_extractor import group_related_items

        items = self._make_items(
            [
                "BTC Bitcoin rally",
                "BTC price drop",
                "ETH Ethereum upgrade",
                "ETH staking reward",
            ]
        )
        result = group_related_items(items)
        # Collect all item objects across groups
        all_seen = []
        for group_items in result.values():
            for item in group_items:
                all_seen.append(id(item))
        # No duplicates
        assert len(all_seen) == len(set(all_seen))


# ---------------------------------------------------------------------------
# _format_group_label (private helper, but accessible)
# ---------------------------------------------------------------------------


class TestFormatGroupLabel:
    def test_known_crypto_label(self):
        from common.entity_extractor import _format_group_label

        assert _format_group_label("crypto", "bitcoin") == "비트코인(BTC)"

    def test_known_stock_label(self):
        from common.entity_extractor import _format_group_label

        assert _format_group_label("stock", "nvidia") == "엔비디아(NVDA)"

    def test_known_index_label(self):
        from common.entity_extractor import _format_group_label

        assert _format_group_label("index", "sp500") == "S&P 500"

    def test_known_person_label(self):
        from common.entity_extractor import _format_group_label

        assert _format_group_label("person", "trump") == "트럼프"

    def test_known_org_label(self):
        from common.entity_extractor import _format_group_label

        assert _format_group_label("org", "fed") == "연준(Fed)"

    def test_unknown_name_returns_name_itself(self):
        from common.entity_extractor import _format_group_label

        assert _format_group_label("crypto", "unknown_coin") == "unknown_coin"

    def test_unknown_category_returns_name(self):
        from common.entity_extractor import _format_group_label

        assert _format_group_label("nonexistent", "something") == "something"

    def test_theme_category_returns_name(self):
        from common.entity_extractor import _format_group_label

        assert _format_group_label("theme", "금리") == "금리"
