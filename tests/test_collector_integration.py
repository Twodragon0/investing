"""Integration tests for StockNewsCollector, CoinMarketCapCollector, WorldMonitorCollector.

All external network calls are mocked — zero real HTTP requests are made.
"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Ensure scripts/ is on sys.path (conftest.py also does this, belt-and-suspenders)
# ---------------------------------------------------------------------------
_SCRIPTS_DIR = os.path.join(os.path.dirname(__file__), "..", "scripts")
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)


# ---------------------------------------------------------------------------
# Shared fixture helpers
# ---------------------------------------------------------------------------


def _make_mock_dedup_engine(is_dup: bool = False, is_dup_exact: bool = False) -> MagicMock:
    engine = MagicMock()
    engine.is_duplicate.return_value = is_dup
    engine.is_duplicate_exact.return_value = is_dup_exact
    return engine


def _make_mock_post_generator(path: str = "_posts/2026-03-29-test.md") -> MagicMock:
    gen = MagicMock()
    gen.create_post.return_value = path
    return gen


def _sample_news_items(count: int = 3) -> List[Dict[str, Any]]:
    return [
        {
            "title": f"Sample news title {i}",
            "link": f"https://example.com/news/{i}",
            "source": "TestSource",
            "published": "2026-03-29",
            "description": f"News description {i}",
            "tags": ["stock", "market"],
        }
        for i in range(count)
    ]


def _base_collector_patches(dedup=None, post_gen=None):
    """Return a context manager that patches BaseCollector's collaborators."""
    import contextlib
    from datetime import UTC, datetime

    @contextlib.contextmanager
    def _ctx():
        _dedup = dedup or _make_mock_dedup_engine()
        _pg = post_gen or _make_mock_post_generator()
        with (
            patch("common.base_collector.setup_logging", return_value=MagicMock()),
            patch("common.base_collector.get_verify_ssl", return_value=True),
            patch("common.base_collector.get_collector_config", return_value={}),
            patch("common.base_collector.DedupEngine", return_value=_dedup),
            patch("common.base_collector.PostGenerator", return_value=_pg),
            patch("common.base_collector.get_kst_now") as mock_now,
        ):
            mock_now.return_value = datetime(2026, 3, 29, 9, 0, 0, tzinfo=UTC)
            yield _dedup, _pg

    return _ctx()


# ---------------------------------------------------------------------------
# Collector module-level patch targets
# ---------------------------------------------------------------------------

_STOCK_MODULE = "collect_stock_news"
_CMC_MODULE = "collect_coinmarketcap"
_WM_MODULE = "collect_worldmonitor_news"


# ===========================================================================
# StockNewsCollector
# ===========================================================================


class TestStockNewsCollectorAttributes:
    """Class-level attribute values are correct."""

    def test_name_is_stock_news(self):
        with _base_collector_patches():
            from collect_stock_news import StockNewsCollector

            c = StockNewsCollector()
        assert c.name == "stock_news"

    def test_category_is_stock_news(self):
        with _base_collector_patches():
            from collect_stock_news import StockNewsCollector

            c = StockNewsCollector()
        assert c.category == "stock-news"

    def test_state_file_is_stock_news_seen(self):
        with _base_collector_patches():
            from collect_stock_news import StockNewsCollector

            c = StockNewsCollector()
        assert c.state_file == "stock_news_seen.json"


class TestStockNewsCollectorInheritance:
    """StockNewsCollector is a proper BaseCollector subclass."""

    def test_isinstance_base_collector(self):
        from common.base_collector import BaseCollector

        with _base_collector_patches():
            from collect_stock_news import StockNewsCollector

            c = StockNewsCollector()
        assert isinstance(c, BaseCollector)


class TestStockNewsCollectorAbstractMethods:
    """All abstract methods are implemented."""

    def test_fetch_is_callable(self):
        with _base_collector_patches():
            from collect_stock_news import StockNewsCollector

            c = StockNewsCollector()
        assert callable(c.fetch)

    def test_process_is_callable(self):
        with _base_collector_patches():
            from collect_stock_news import StockNewsCollector

            c = StockNewsCollector()
        assert callable(c.process)

    def test_build_content_is_callable(self):
        with _base_collector_patches():
            from collect_stock_news import StockNewsCollector

            c = StockNewsCollector()
        assert callable(c.build_content)


class TestStockNewsCollectorRun:
    """run() completes without error when external calls are mocked."""

    @staticmethod
    def _make_theme_summarizer_mock() -> MagicMock:
        """Return a MagicMock whose methods return empty strings (safe for str.join)."""
        instance = MagicMock()
        # All methods that append their return value to content_parts must return str
        instance.generate_executive_summary.return_value = ""
        instance.generate_overall_summary_section.return_value = ""
        instance.generate_distribution_chart.return_value = ""
        instance.generate_theme_sections.return_value = ""
        instance.generate_trend_analysis.return_value = ""
        instance.generate_themed_news_sections.return_value = ""
        instance.generate_prediction_markdown.return_value = ""
        instance.generate_topic_summary.return_value = ""
        cls_mock = MagicMock(return_value=instance)
        return cls_mock

    def _run_with_items(self, items: List[Dict[str, Any]], is_dup_exact: bool = False):
        dedup = _make_mock_dedup_engine(is_dup_exact=is_dup_exact)
        pg = _make_mock_post_generator()
        summarizer_cls = self._make_theme_summarizer_mock()

        with _base_collector_patches(dedup=dedup, post_gen=pg):
            from collect_stock_news import StockNewsCollector

            c = StockNewsCollector()

        with (
            patch(f"{_STOCK_MODULE}.fetch_google_news_browser_stocks", return_value=items),
            patch(f"{_STOCK_MODULE}.fetch_google_news_stocks", return_value=[]),
            patch(f"{_STOCK_MODULE}.fetch_yahoo_finance_rss", return_value=[]),
            patch(f"{_STOCK_MODULE}.fetch_alpha_vantage_snapshot", return_value=[]),
            patch(f"{_STOCK_MODULE}.fetch_financial_rss_feeds", return_value=[]),
            patch(f"{_STOCK_MODULE}.fetch_sector_rotation_feeds", return_value=[]),
            patch(f"{_STOCK_MODULE}.fetch_korean_market_data", return_value={}),
            patch(f"{_STOCK_MODULE}.ThemeSummarizer", summarizer_cls),
            patch("common.base_collector.PostGenerator", return_value=pg),
        ):
            c.run()

        return c, dedup, pg

    def test_run_completes_without_exception_when_items_present(self):
        items = _sample_news_items(3)
        self._run_with_items(items)  # must not raise

    def test_run_completes_without_exception_when_no_items(self):
        self._run_with_items([])  # must not raise

    def test_run_saves_state_after_empty_fetch(self):
        _c, dedup, _pg = self._run_with_items([])
        dedup.save.assert_called()

    def test_run_skips_post_creation_when_duplicate_title(self):
        items = _sample_news_items(2)
        _c, _dedup, pg = self._run_with_items(items, is_dup_exact=True)
        pg.create_post.assert_not_called()


class TestStockNewsCollectorEmptyResponse:
    """Graceful handling when all sources return nothing."""

    def test_run_does_not_raise_on_empty_sources(self):
        dedup = _make_mock_dedup_engine()
        pg = _make_mock_post_generator()

        with _base_collector_patches(dedup=dedup, post_gen=pg):
            from collect_stock_news import StockNewsCollector

            c = StockNewsCollector()

        with (
            patch(f"{_STOCK_MODULE}.fetch_google_news_browser_stocks", return_value=[]),
            patch(f"{_STOCK_MODULE}.fetch_google_news_stocks", return_value=[]),
            patch(f"{_STOCK_MODULE}.fetch_yahoo_finance_rss", return_value=[]),
            patch(f"{_STOCK_MODULE}.fetch_alpha_vantage_snapshot", return_value=[]),
            patch(f"{_STOCK_MODULE}.fetch_financial_rss_feeds", return_value=[]),
            patch(f"{_STOCK_MODULE}.fetch_sector_rotation_feeds", return_value=[]),
            patch(f"{_STOCK_MODULE}.fetch_korean_market_data", return_value={}),
        ):
            c.run()  # must not raise

    def test_state_saved_on_empty_fetch(self):
        dedup = _make_mock_dedup_engine()
        pg = _make_mock_post_generator()

        with _base_collector_patches(dedup=dedup, post_gen=pg):
            from collect_stock_news import StockNewsCollector

            c = StockNewsCollector()

        with (
            patch(f"{_STOCK_MODULE}.fetch_google_news_browser_stocks", return_value=[]),
            patch(f"{_STOCK_MODULE}.fetch_google_news_stocks", return_value=[]),
            patch(f"{_STOCK_MODULE}.fetch_yahoo_finance_rss", return_value=[]),
            patch(f"{_STOCK_MODULE}.fetch_alpha_vantage_snapshot", return_value=[]),
            patch(f"{_STOCK_MODULE}.fetch_financial_rss_feeds", return_value=[]),
            patch(f"{_STOCK_MODULE}.fetch_sector_rotation_feeds", return_value=[]),
            patch(f"{_STOCK_MODULE}.fetch_korean_market_data", return_value={}),
        ):
            c.run()

        dedup.save.assert_called()


class TestStockNewsCollectorMainFunction:
    """main() function exists and is callable."""

    def test_main_is_callable(self):
        import collect_stock_news

        assert callable(collect_stock_news.main)

    def test_main_invokes_collector_run(self):
        dedup = _make_mock_dedup_engine()
        pg = _make_mock_post_generator()

        with _base_collector_patches(dedup=dedup, post_gen=pg):
            from collect_stock_news import StockNewsCollector

            mock_collector = MagicMock(spec=StockNewsCollector)

        with (
            patch(f"{_STOCK_MODULE}.StockNewsCollector", return_value=mock_collector),
            patch("common.base_collector.setup_logging", return_value=MagicMock()),
            patch("common.base_collector.get_verify_ssl", return_value=True),
            patch("common.base_collector.get_collector_config", return_value={}),
        ):
            import collect_stock_news

            collect_stock_news.main()

        mock_collector.run.assert_called_once()


# ===========================================================================
# CoinMarketCapCollector
# ===========================================================================


class TestCoinMarketCapCollectorAttributes:
    """Class-level attribute values are correct."""

    def test_name_is_coinmarketcap(self):
        with _base_collector_patches():
            from collect_coinmarketcap import CoinMarketCapCollector

            c = CoinMarketCapCollector()
        assert c.name == "coinmarketcap"

    def test_category_is_market_analysis(self):
        with _base_collector_patches():
            from collect_coinmarketcap import CoinMarketCapCollector

            c = CoinMarketCapCollector()
        assert c.category == "market-analysis"

    def test_state_file_is_crypto_news_seen(self):
        with _base_collector_patches():
            from collect_coinmarketcap import CoinMarketCapCollector

            c = CoinMarketCapCollector()
        assert c.state_file == "crypto_news_seen.json"


class TestCoinMarketCapCollectorInheritance:
    """CoinMarketCapCollector is a proper BaseCollector subclass."""

    def test_isinstance_base_collector(self):
        from common.base_collector import BaseCollector

        with _base_collector_patches():
            from collect_coinmarketcap import CoinMarketCapCollector

            c = CoinMarketCapCollector()
        assert isinstance(c, BaseCollector)


class TestCoinMarketCapCollectorAbstractMethods:
    """All abstract methods are implemented."""

    def test_fetch_returns_empty_list(self):
        """CoinMarketCapCollector.fetch() delegates to run() — returns [] by design."""
        with _base_collector_patches():
            from collect_coinmarketcap import CoinMarketCapCollector

            c = CoinMarketCapCollector()
        result = c.fetch()
        assert result == []

    def test_process_is_callable(self):
        with _base_collector_patches():
            from collect_coinmarketcap import CoinMarketCapCollector

            c = CoinMarketCapCollector()
        assert callable(c.process)

    def test_build_content_returns_empty_string(self):
        """CoinMarketCapCollector.build_content() returns '' — run() owns content."""
        with _base_collector_patches():
            from collect_coinmarketcap import CoinMarketCapCollector

            c = CoinMarketCapCollector()
        assert c.build_content([]) == ""


class TestCoinMarketCapCollectorRun:
    """run() completes without error when external API calls are mocked."""

    def _make_fake_coins(self, count: int = 3) -> List[Dict[str, Any]]:
        return [
            {
                "id": f"coin-{i}",
                "symbol": f"C{i}",
                "name": f"Coin {i}",
                "current_price": 1000 * (i + 1),
                "market_cap": 1_000_000 * (i + 1),
                "price_change_percentage_24h": (i - 1) * 2.5,
                "total_volume": 100_000,
            }
            for i in range(count)
        ]

    def test_run_completes_without_exception_with_coin_data(self):
        import sys
        import types

        coins = self._make_fake_coins(3)
        dedup = _make_mock_dedup_engine(is_dup_exact=False)
        pg = _make_mock_post_generator()

        with _base_collector_patches(dedup=dedup, post_gen=pg):
            from collect_coinmarketcap import CoinMarketCapCollector

            c = CoinMarketCapCollector()

        # Stub out common.image_generator so the lazy `from common.image_generator import ...`
        # inside run() resolves to no-op functions instead of raising ImportError.
        fake_img_module = types.ModuleType("common.image_generator")
        fake_img_module.generate_top_coins_card = MagicMock(return_value=None)  # type: ignore[attr-defined]
        fake_img_module.generate_market_heatmap = MagicMock(return_value=None)  # type: ignore[attr-defined]
        fake_img_module.generate_news_briefing_card = MagicMock(return_value=None)  # type: ignore[attr-defined]

        with (
            patch(f"{_CMC_MODULE}.get_env", return_value=""),
            patch(f"{_CMC_MODULE}.fetch_coingecko_global", return_value={}),
            patch(f"{_CMC_MODULE}.fetch_coingecko_top_coins", return_value=coins),
            patch(f"{_CMC_MODULE}.fetch_coingecko_trending", return_value=[]),
            patch(f"{_CMC_MODULE}.fetch_fear_greed_index", return_value={"value": 55, "classification": "Neutral"}),
            patch(f"{_CMC_MODULE}.fetch_cmc_browser_fallback", return_value=[]),
            patch.dict(sys.modules, {"common.image_generator": fake_img_module}),
            patch("time.sleep"),
            patch("common.base_collector.PostGenerator", return_value=pg),
        ):
            c.run()  # must not raise

    def test_run_completes_when_all_api_sources_return_empty(self):
        dedup = _make_mock_dedup_engine(is_dup_exact=False)
        pg = _make_mock_post_generator()

        with _base_collector_patches(dedup=dedup, post_gen=pg):
            from collect_coinmarketcap import CoinMarketCapCollector

            c = CoinMarketCapCollector()

        with (
            patch(f"{_CMC_MODULE}.get_env", return_value=""),
            patch(f"{_CMC_MODULE}.fetch_coingecko_global", return_value={}),
            patch(f"{_CMC_MODULE}.fetch_coingecko_top_coins", return_value=[]),
            patch(f"{_CMC_MODULE}.fetch_coingecko_trending", return_value=[]),
            patch(f"{_CMC_MODULE}.fetch_fear_greed_index", return_value={}),
            patch(f"{_CMC_MODULE}.fetch_cmc_browser_fallback", return_value=[]),
            patch("time.sleep"),
            patch("common.base_collector.PostGenerator", return_value=pg),
        ):
            c.run()  # must not raise

    def test_run_skips_post_creation_when_duplicate_title(self):
        coins = self._make_fake_coins(2)
        dedup = _make_mock_dedup_engine(is_dup_exact=True)
        pg = _make_mock_post_generator()

        with _base_collector_patches(dedup=dedup, post_gen=pg):
            from collect_coinmarketcap import CoinMarketCapCollector

            c = CoinMarketCapCollector()

        with (
            patch(f"{_CMC_MODULE}.get_env", return_value=""),
            patch(f"{_CMC_MODULE}.fetch_coingecko_global", return_value={}),
            patch(f"{_CMC_MODULE}.fetch_coingecko_top_coins", return_value=coins),
            patch(f"{_CMC_MODULE}.fetch_coingecko_trending", return_value=[]),
            patch(f"{_CMC_MODULE}.fetch_fear_greed_index", return_value={}),
            patch(f"{_CMC_MODULE}.fetch_cmc_browser_fallback", return_value=[]),
            patch("time.sleep"),
            patch("common.base_collector.PostGenerator", return_value=pg),
        ):
            c.run()

        pg.create_post.assert_not_called()


class TestCoinMarketCapCollectorEmptyResponse:
    """Graceful handling when API returns empty data."""

    def test_run_does_not_raise_when_top_coins_empty_and_browser_fallback_empty(self):
        dedup = _make_mock_dedup_engine()
        pg = _make_mock_post_generator()

        with _base_collector_patches(dedup=dedup, post_gen=pg):
            from collect_coinmarketcap import CoinMarketCapCollector

            c = CoinMarketCapCollector()

        with (
            patch(f"{_CMC_MODULE}.get_env", return_value=""),
            patch(f"{_CMC_MODULE}.fetch_coingecko_global", return_value={}),
            patch(f"{_CMC_MODULE}.fetch_coingecko_top_coins", return_value=[]),
            patch(f"{_CMC_MODULE}.fetch_coingecko_trending", return_value=[]),
            patch(f"{_CMC_MODULE}.fetch_fear_greed_index", return_value={}),
            patch(f"{_CMC_MODULE}.fetch_cmc_browser_fallback", return_value=[]),
            patch("time.sleep"),
        ):
            c.run()  # must not raise


class TestCoinMarketCapCollectorMainFunction:
    """main() function exists and is callable."""

    def test_main_is_callable(self):
        import collect_coinmarketcap

        assert callable(collect_coinmarketcap.main)

    def test_main_invokes_collector_run(self):
        dedup = _make_mock_dedup_engine()
        pg = _make_mock_post_generator()

        with _base_collector_patches(dedup=dedup, post_gen=pg):
            from collect_coinmarketcap import CoinMarketCapCollector

            mock_collector = MagicMock(spec=CoinMarketCapCollector)

        with (
            patch(f"{_CMC_MODULE}.CoinMarketCapCollector", return_value=mock_collector),
            patch("common.base_collector.setup_logging", return_value=MagicMock()),
            patch("common.base_collector.get_verify_ssl", return_value=True),
            patch("common.base_collector.get_collector_config", return_value={}),
        ):
            import collect_coinmarketcap

            collect_coinmarketcap.main()

        mock_collector.run.assert_called_once()


# ===========================================================================
# WorldMonitorCollector
# ===========================================================================


class TestWorldMonitorCollectorAttributes:
    """Class-level attribute values are correct."""

    def test_name_is_worldmonitor_news(self):
        with _base_collector_patches():
            from collect_worldmonitor_news import WorldMonitorCollector

            c = WorldMonitorCollector()
        assert c.name == "worldmonitor_news"

    def test_category_is_market_analysis(self):
        with _base_collector_patches():
            from collect_worldmonitor_news import WorldMonitorCollector

            c = WorldMonitorCollector()
        assert c.category == "market-analysis"

    def test_state_file_is_worldmonitor_news_seen(self):
        with _base_collector_patches():
            from collect_worldmonitor_news import WorldMonitorCollector

            c = WorldMonitorCollector()
        assert c.state_file == "worldmonitor_news_seen.json"


class TestWorldMonitorCollectorInheritance:
    """WorldMonitorCollector is a proper BaseCollector subclass."""

    def test_isinstance_base_collector(self):
        from common.base_collector import BaseCollector

        with _base_collector_patches():
            from collect_worldmonitor_news import WorldMonitorCollector

            c = WorldMonitorCollector()
        assert isinstance(c, BaseCollector)


class TestWorldMonitorCollectorAbstractMethods:
    """All abstract methods are implemented."""

    def test_fetch_is_callable(self):
        with _base_collector_patches():
            from collect_worldmonitor_news import WorldMonitorCollector

            c = WorldMonitorCollector()
        assert callable(c.fetch)

    def test_process_is_callable(self):
        with _base_collector_patches():
            from collect_worldmonitor_news import WorldMonitorCollector

            c = WorldMonitorCollector()
        assert callable(c.process)

    def test_build_content_returns_empty_string(self):
        """WorldMonitorCollector.build_content() returns '' — run() owns content."""
        with _base_collector_patches():
            from collect_worldmonitor_news import WorldMonitorCollector

            c = WorldMonitorCollector()
        assert c.build_content([]) == ""


class TestWorldMonitorCollectorRun:
    """run() completes without error when external calls are mocked."""

    def _sample_wm_items(self, count: int = 3) -> List[Dict[str, Any]]:
        return [
            {
                "title": f"Iran sanctions update {i}",
                "link": f"https://worldmonitor.app/news/{i}",
                "source": "WorldMonitor",
                "published": "2026-03-29",
                "description": f"Geopolitical event {i}",
                "tags": ["geopolitics"],
            }
            for i in range(count)
        ]

    def test_run_completes_without_exception_with_items(self):
        items = self._sample_wm_items(3)
        dedup = _make_mock_dedup_engine(is_dup_exact=False)
        pg = _make_mock_post_generator()

        with _base_collector_patches(dedup=dedup, post_gen=pg):
            from collect_worldmonitor_news import WorldMonitorCollector

            c = WorldMonitorCollector()

        with (
            patch(f"{_WM_MODULE}.fetch_worldmonitor_feeds", return_value=items),
            patch(f"{_WM_MODULE}.enrich_items"),
            patch(f"{_WM_MODULE}.deduplicate_by_url", return_value=items),
            patch(f"{_WM_MODULE}.fetch_worldmonitor_map_snapshot", return_value={}),
            patch("common.base_collector.PostGenerator", return_value=pg),
        ):
            c.run()  # must not raise

    def test_run_completes_without_exception_when_no_items(self):
        dedup = _make_mock_dedup_engine()
        pg = _make_mock_post_generator()

        with _base_collector_patches(dedup=dedup, post_gen=pg):
            from collect_worldmonitor_news import WorldMonitorCollector

            c = WorldMonitorCollector()

        with (
            patch(f"{_WM_MODULE}.fetch_worldmonitor_feeds", return_value=[]),
        ):
            c.run()  # must not raise

    def test_run_saves_state_on_empty_fetch(self):
        dedup = _make_mock_dedup_engine()
        pg = _make_mock_post_generator()

        with _base_collector_patches(dedup=dedup, post_gen=pg):
            from collect_worldmonitor_news import WorldMonitorCollector

            c = WorldMonitorCollector()

        with (
            patch(f"{_WM_MODULE}.fetch_worldmonitor_feeds", return_value=[]),
        ):
            c.run()

        dedup.save.assert_called()

    def test_run_skips_post_creation_when_duplicate_title(self):
        dedup = _make_mock_dedup_engine(is_dup_exact=True)
        pg = _make_mock_post_generator()

        with _base_collector_patches(dedup=dedup, post_gen=pg):
            from collect_worldmonitor_news import WorldMonitorCollector

            c = WorldMonitorCollector()

        with (
            patch(f"{_WM_MODULE}.fetch_worldmonitor_feeds", return_value=[]),
        ):
            c.run()

        pg.create_post.assert_not_called()


class TestWorldMonitorCollectorEmptyResponse:
    """Graceful handling when RSS feeds return nothing."""

    def test_run_does_not_raise_when_feeds_return_empty(self):
        dedup = _make_mock_dedup_engine()
        pg = _make_mock_post_generator()

        with _base_collector_patches(dedup=dedup, post_gen=pg):
            from collect_worldmonitor_news import WorldMonitorCollector

            c = WorldMonitorCollector()

        with (
            patch(f"{_WM_MODULE}.fetch_worldmonitor_feeds", return_value=[]),
        ):
            c.run()  # must not raise

    def test_run_does_not_create_post_when_feeds_return_empty(self):
        dedup = _make_mock_dedup_engine()
        pg = _make_mock_post_generator()

        with _base_collector_patches(dedup=dedup, post_gen=pg):
            from collect_worldmonitor_news import WorldMonitorCollector

            c = WorldMonitorCollector()

        with (
            patch(f"{_WM_MODULE}.fetch_worldmonitor_feeds", return_value=[]),
        ):
            c.run()

        pg.create_post.assert_not_called()


class TestWorldMonitorCollectorMainFunction:
    """main() function exists and is callable."""

    def test_main_is_callable(self):
        import collect_worldmonitor_news

        assert callable(collect_worldmonitor_news.main)

    def test_main_invokes_collector_run(self):
        dedup = _make_mock_dedup_engine()
        pg = _make_mock_post_generator()

        with _base_collector_patches(dedup=dedup, post_gen=pg):
            from collect_worldmonitor_news import WorldMonitorCollector

            mock_collector = MagicMock(spec=WorldMonitorCollector)

        with (
            patch(f"{_WM_MODULE}.WorldMonitorCollector", return_value=mock_collector),
            patch("common.base_collector.setup_logging", return_value=MagicMock()),
            patch("common.base_collector.get_verify_ssl", return_value=True),
            patch("common.base_collector.get_collector_config", return_value={}),
        ):
            import collect_worldmonitor_news

            collect_worldmonitor_news.main()

        mock_collector.run.assert_called_once()
