"""Integration tests for StockNewsCollector, CoinMarketCapCollector, WorldMonitorCollector.

All external network calls are mocked — zero real HTTP requests are made.
"""

from __future__ import annotations

import os
import re
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


# ===========================================================================
# CryptoNewsCollector
# ===========================================================================


class TestCryptoNewsCollectorIntegration:
    """Integration-style coverage for the dual-post crypto collector."""

    def _sample_crypto_items(self, count: int = 3, source: str = "CryptoPanic") -> List[Dict[str, Any]]:
        return [
            {
                "title": f"Bitcoin market update {i}",
                "link": f"https://example.com/crypto/{source.lower()}/{i}",
                "source": source,
                "published": "2026-03-29",
                "description": f"Crypto market description {i}",
                "tags": ["crypto", "market"],
            }
            for i in range(count)
        ]

    def _sample_security_items(self, count: int = 2, source: str = "Rekt News") -> List[Dict[str, Any]]:
        return [
            {
                "title": f"[Security] Protocol exploit {i}",
                "link": f"https://example.com/security/{source.lower().replace(' ', '-')}/{i}",
                "source": source,
                "published": "2026-03-29",
                "description": f"Funds Lost: ${i + 1}M | Incident summary {i}",
                "tags": ["security", "hack"],
            }
            for i in range(count)
        ]

    def _make_collector(
        self,
        *,
        dedup: MagicMock | None = None,
        post_gen: MagicMock | None = None,
        security_post_gen: MagicMock | None = None,
    ):
        dedup = dedup or _make_mock_dedup_engine()
        post_gen = post_gen or _make_mock_post_generator("_posts/2026-03-29-crypto.md")
        security_post_gen = security_post_gen or _make_mock_post_generator("_posts/2026-03-29-security.md")

        with _base_collector_patches(dedup=dedup, post_gen=post_gen):
            import collect_crypto_news

            with patch.object(collect_crypto_news, "PostGenerator", return_value=security_post_gen):
                collector = collect_crypto_news.CryptoNewsCollector()

        return collector, dedup, post_gen, security_post_gen

    def test_fetch_uses_binance_api_fallback_when_browser_announcements_missing(self):
        collector, _dedup, _post_gen, _security_post_gen = self._make_collector()
        cryptopanic_items = self._sample_crypto_items(1, "CryptoPanic")
        browser_google_items = self._sample_crypto_items(1, "Google Browser")
        google_rss_items = self._sample_crypto_items(1, "Google RSS")
        rss_items = self._sample_crypto_items(1, "CoinDesk")
        binance_api_items = self._sample_crypto_items(2, "Binance")

        with (
            patch("collect_crypto_news.get_env", return_value="cryptopanic-key"),
            patch("collect_crypto_news.fetch_cryptopanic", return_value=cryptopanic_items),
            patch("collect_crypto_news._fetch_browser_sources", return_value=(browser_google_items, [])),
            patch("collect_crypto_news.fetch_google_news_crypto", return_value=(google_rss_items, 0)),
            patch("collect_crypto_news.fetch_crypto_rss_feeds", return_value=rss_items),
            patch("collect_crypto_news._fetch_binance_bapi", return_value=binance_api_items) as mock_binance_api,
            patch("collect_crypto_news.enrich_items") as mock_enrich,
        ):
            items = collector.fetch()

        assert len(items) == 6
        assert any(item["source"] == "Binance" for item in items)
        mock_binance_api.assert_called_once()
        assert mock_enrich.call_count == 2

    def test_run_creates_both_crypto_and_security_posts_from_mocked_sources(self):
        collector, dedup, post_gen, security_post_gen = self._make_collector()
        cryptopanic_items = self._sample_crypto_items(1, "CryptoPanic")
        browser_google_items = self._sample_crypto_items(1, "Google Browser")
        google_rss_items = self._sample_crypto_items(1, "Google RSS")
        rss_items = self._sample_crypto_items(1, "CoinDesk")
        browser_binance_items = self._sample_crypto_items(1, "Binance")
        rekt_items = self._sample_security_items(1, "Rekt News")
        google_security_items = self._sample_security_items(1, "Google Security")

        with (
            patch("collect_crypto_news.get_env", return_value="cryptopanic-key"),
            patch("collect_crypto_news.fetch_cryptopanic", return_value=cryptopanic_items),
            patch(
                "collect_crypto_news._fetch_browser_sources",
                return_value=(browser_google_items, browser_binance_items),
            ),
            patch("collect_crypto_news.fetch_google_news_crypto", return_value=(google_rss_items, 0)),
            patch("collect_crypto_news.fetch_crypto_rss_feeds", return_value=rss_items),
            patch("collect_crypto_news.fetch_rekt_news", return_value=rekt_items),
            patch("collect_crypto_news.fetch_defillama_hacks", return_value=[]),
            patch("collect_crypto_news.fetch_google_news_security", return_value=google_security_items),
            patch("collect_crypto_news.enrich_items"),
            patch("collect_crypto_news.deduplicate_by_url", side_effect=lambda items: items),
            patch("collect_crypto_news._is_security_relevant", return_value=True),
            patch.object(collector, "_build_crypto_content", return_value=("crypto content", "crypto.png")),
            patch.object(collector, "_build_security_content", return_value="security content"),
        ):
            collector.run()

        assert post_gen.create_post.call_count == 1
        assert security_post_gen.create_post.call_count == 1
        assert dedup.mark_seen.call_count == 2
        dedup.save.assert_called_once()
        assert post_gen.create_post.call_args.kwargs["slug"] == "daily-crypto-news-digest"
        assert security_post_gen.create_post.call_args.kwargs["slug"] == "daily-security-report"

    def test_run_creates_only_security_post_when_market_sources_are_empty(self):
        collector, dedup, post_gen, security_post_gen = self._make_collector()
        rekt_items = self._sample_security_items(1, "Rekt News")

        with (
            patch("collect_crypto_news.get_env", return_value="cryptopanic-key"),
            patch("collect_crypto_news.fetch_cryptopanic", return_value=[]),
            patch("collect_crypto_news._fetch_browser_sources", return_value=([], [])),
            patch("collect_crypto_news.fetch_google_news_crypto", return_value=([], 0)),
            patch("collect_crypto_news.fetch_crypto_rss_feeds", return_value=[]),
            patch("collect_crypto_news._fetch_binance_bapi", return_value=[]),
            patch("collect_crypto_news.fetch_rekt_news", return_value=rekt_items),
            patch("collect_crypto_news.fetch_defillama_hacks", return_value=[]),
            patch("collect_crypto_news.fetch_google_news_security", return_value=[]),
            patch("collect_crypto_news.enrich_items"),
            patch("collect_crypto_news.deduplicate_by_url", side_effect=lambda items: items),
            patch.object(collector, "_build_security_content", return_value="security content"),
        ):
            collector.run()

        post_gen.create_post.assert_not_called()
        security_post_gen.create_post.assert_called_once()
        dedup.save.assert_called_once()

    def test_run_skips_security_post_when_security_sources_are_empty(self):
        collector, dedup, post_gen, security_post_gen = self._make_collector()
        market_items = self._sample_crypto_items(2, "CryptoPanic")

        with (
            patch("collect_crypto_news.get_env", return_value="cryptopanic-key"),
            patch("collect_crypto_news.fetch_cryptopanic", return_value=market_items),
            patch("collect_crypto_news._fetch_browser_sources", return_value=([], [])),
            patch("collect_crypto_news.fetch_google_news_crypto", return_value=([], 0)),
            patch("collect_crypto_news.fetch_crypto_rss_feeds", return_value=[]),
            patch("collect_crypto_news._fetch_binance_bapi", return_value=[]),
            patch("collect_crypto_news.fetch_rekt_news", return_value=[]),
            patch("collect_crypto_news.fetch_defillama_hacks", return_value=[]),
            patch("collect_crypto_news.fetch_google_news_security", return_value=[]),
            patch("collect_crypto_news.enrich_items"),
            patch("collect_crypto_news.deduplicate_by_url", side_effect=lambda items: items),
            patch.object(collector, "_build_crypto_content", return_value=("crypto content", "crypto.png")),
        ):
            collector.run()

        post_gen.create_post.assert_called_once()
        security_post_gen.create_post.assert_not_called()
        dedup.save.assert_called_once()


class TestCollectorContentAndImages:
    """Exercise real content assembly and generated-image embedding paths."""

    @staticmethod
    def _make_theme_summarizer_for_content() -> MagicMock:
        instance = MagicMock()
        instance.generate_executive_summary.return_value = "## 한눈에 보기\n요약"
        instance.generate_overall_summary_section.return_value = "## 전체 요약\n개요"
        instance.generate_distribution_chart.return_value = "## 분포 차트\n차트"
        instance.generate_themed_news_sections.return_value = "## 주요 뉴스\n테마 섹션"
        instance.generate_topic_summary.return_value = "## 토픽 요약\n토픽"
        instance.generate_prediction_markdown.return_value = "## 전망\n중립"
        instance.generate_trend_analysis.return_value = "## 추세 분석\n안정"
        instance.generate_theme_sections.return_value = "## 테마 섹션\n내용"
        instance.get_top_themes.return_value = [("비트코인", "bitcoin", "BTC", 2), ("규제/정책", "reg", "REG", 1)]
        instance.classify_priority.return_value = {"P0": [], "P1": [], "P2": []}
        instance._theme_articles = {
            "bitcoin": [{"title": "Bitcoin rallies above $90,000"}],
            "reg": [{"title": "ETF approval optimism grows"}],
        }
        return MagicMock(return_value=instance)

    def test_stock_run_embeds_market_snapshot_image_in_created_content(self):
        items = [
            {
                "title": "S&P 500 rallies after Fed comments",
                "link": "https://example.com/stock/1",
                "source": "Reuters",
                "published": "2026-03-29",
                "description": "Stocks moved higher after rate comments.",
                "tags": ["stock", "market"],
            },
            {
                "title": "삼성전자 실적 기대감 확대",
                "link": "https://example.com/stock/2",
                "source": "한국경제",
                "published": "2026-03-29",
                "description": "반도체 업황 기대가 반영됐다.",
                "tags": ["stock", "korea"],
            },
            {
                "title": "S&P 500: Daily Snapshot",
                "link": "https://example.com/stock/3",
                "source": "Alpha Vantage",
                "published": "2026-03-29",
                "description": "Price: $5,100.00, Change: +50.00 (+0.99%)",
                "tags": ["stock", "market"],
            },
        ]
        kr_market = {
            "KOSPI": {"price": "2,750.10", "change_pct": "+1.23%"},
            "KOSDAQ": {"price": "890.12", "change_pct": "-0.12%"},
        }
        dedup = _make_mock_dedup_engine()
        post_gen = _make_mock_post_generator()
        fake_img_module = MagicMock()
        fake_img_module.generate_market_snapshot_card.return_value = (
            "/Users/yong/Desktop/personal/investing/assets/images/generated/stock-snapshot.png"
        )

        with _base_collector_patches(dedup=dedup, post_gen=post_gen):
            import collect_stock_news

            collector = collect_stock_news.StockNewsCollector()

        with (
            patch("collect_stock_news.fetch_google_news_browser_stocks", return_value=items),
            patch("collect_stock_news.fetch_google_news_stocks", return_value=[]),
            patch("collect_stock_news.fetch_yahoo_finance_rss", return_value=[]),
            patch("collect_stock_news.fetch_alpha_vantage_snapshot", return_value=[]),
            patch("collect_stock_news.fetch_financial_rss_feeds", return_value=[]),
            patch("collect_stock_news.fetch_sector_rotation_feeds", return_value=[]),
            patch("collect_stock_news.fetch_korean_market_data", return_value=kr_market),
            patch("collect_stock_news.ThemeSummarizer", self._make_theme_summarizer_for_content()),
            patch("collect_stock_news.detect_language", side_effect=["en", "ko", "en"]),
            patch("collect_stock_news.enrich_items"),
            patch("collect_stock_news.deduplicate_by_url", side_effect=lambda rows: rows),
            patch.dict(sys.modules, {"common.image_generator": fake_img_module}),
        ):
            collector.run()

        created_content = post_gen.create_post.call_args.kwargs["content"]
        created_image = post_gen.create_post.call_args.kwargs["image"]
        assert "![market-snapshot]" in created_content
        assert "stock-snapshot.png" in created_content
        assert created_image.endswith("stock-snapshot.png")

    def test_coinmarketcap_run_embeds_generated_images_and_frontmatter_image(self):
        coins = [
            {
                "id": "bitcoin",
                "symbol": "btc",
                "name": "Bitcoin",
                "current_price": 90000,
                "market_cap": 1_800_000_000_000,
                "price_change_percentage_24h": 4.2,
                "price_change_percentage_7d_in_currency": 8.1,
                "total_volume": 50_000_000_000,
            },
            {
                "id": "ethereum",
                "symbol": "eth",
                "name": "Ethereum",
                "current_price": 4500,
                "market_cap": 540_000_000_000,
                "price_change_percentage_24h": -1.1,
                "price_change_percentage_7d_in_currency": 2.2,
                "total_volume": 20_000_000_000,
            },
        ]
        global_data = {
            "total_market_cap": {"usd": 3_100_000_000_000},
            "total_volume": {"usd": 150_000_000_000},
            "market_cap_percentage": {"btc": 58.2, "eth": 17.1},
            "market_cap_change_percentage_24h_usd": 1.5,
            "active_cryptocurrencies": 12000,
        }
        fear_greed = {"value": 72, "classification": "Greed"}
        dedup = _make_mock_dedup_engine()
        post_gen = _make_mock_post_generator()

        with _base_collector_patches(dedup=dedup, post_gen=post_gen):
            import collect_coinmarketcap

            collector = collect_coinmarketcap.CoinMarketCapCollector()

        fake_img_module = MagicMock()
        fake_img_module.generate_top_coins_card.return_value = (
            "/Users/yong/Desktop/personal/investing/assets/images/generated/top-coins-cmc-2026-03-29.png"
        )
        fake_img_module.generate_market_heatmap.return_value = (
            "/Users/yong/Desktop/personal/investing/assets/images/generated/market-heatmap-cmc-2026-03-29.png"
        )
        fake_img_module.generate_news_briefing_card.return_value = (
            "/Users/yong/Desktop/personal/investing/assets/images/generated/news-briefing-cmc-2026-03-29.png"
        )

        with (
            patch("collect_coinmarketcap.get_env", return_value=""),
            patch("collect_coinmarketcap.fetch_coingecko_global", return_value=global_data),
            patch("collect_coinmarketcap.fetch_coingecko_top_coins", return_value=coins),
            patch("collect_coinmarketcap.fetch_coingecko_trending", return_value=[]),
            patch("collect_coinmarketcap.fetch_fear_greed_index", return_value=fear_greed),
            patch("collect_coinmarketcap.fetch_cmc_browser_fallback", return_value=[]),
            patch("collect_coinmarketcap.generate_market_insight", return_value="시장 인사이트"),
            patch("collect_coinmarketcap.time.sleep"),
            patch.dict(sys.modules, {"common.image_generator": fake_img_module}),
        ):
            collector.run()

        kwargs = post_gen.create_post.call_args.kwargs
        assert "news-briefing-cmc-2026-03-29.png" in kwargs["content"]
        assert "market-heatmap-cmc-2026-03-29.png" in kwargs["content"]
        assert kwargs["image"].endswith("news-briefing-cmc-2026-03-29.png")

    def test_crypto_build_content_embeds_briefing_image(self):
        dedup = _make_mock_dedup_engine()
        post_gen = _make_mock_post_generator("_posts/2026-03-29-crypto.md")
        security_post_gen = _make_mock_post_generator("_posts/2026-03-29-security.md")
        items = [
            {
                "title": "Bitcoin rallies above $90,000",
                "link": "https://example.com/crypto/1",
                "source": "CryptoPanic",
                "published": "2026-03-29",
                "description": "Bitcoin surged as ETF inflows accelerated.",
                "tags": ["crypto", "market"],
            },
            {
                "title": "Ethereum listing update on Binance",
                "link": "https://example.com/crypto/2",
                "source": "Binance",
                "published": "2026-03-29",
                "description": "New listing notice for a major pair.",
                "tags": ["crypto", "exchange"],
            },
        ]

        with _base_collector_patches(dedup=dedup, post_gen=post_gen):
            import collect_crypto_news

            with patch.object(collect_crypto_news, "PostGenerator", return_value=security_post_gen):
                collector = collect_crypto_news.CryptoNewsCollector()

        fake_img_module = MagicMock()
        fake_img_module.generate_news_briefing_card.return_value = (
            "/Users/yong/Desktop/personal/investing/assets/images/generated/news-briefing-crypto-2026-03-29.png"
        )

        with (
            patch("collect_crypto_news.ThemeSummarizer", self._make_theme_summarizer_for_content()),
            patch("collect_crypto_news.get_display_title", side_effect=lambda item: item.get("title", "")),
            patch("collect_crypto_news.html_reference_details", return_value="<details>refs</details>"),
            patch.dict(sys.modules, {"common.image_generator": fake_img_module}),
        ):
            content, image = collector._build_crypto_content(items)

        assert "![news-briefing]" in content
        assert "news-briefing-crypto-2026-03-29.png" in content
        assert image.endswith("news-briefing-crypto-2026-03-29.png")


class TestRegulatoryCollectorIntegration:
    """Add integration coverage for a fifth key collector."""

    @staticmethod
    def _sample_regulatory_items(region: str, count: int = 1) -> List[Dict[str, Any]]:
        tag_map = {
            "미국": ["regulation", "sec", "us"],
            "한국": ["regulation", "fsc", "korea"],
            "아시아": ["regulation", "japan", "fsa"],
            "유럽": ["regulation", "eu", "mica"],
        }
        return [
            {
                "title": f"{region} regulatory update {i}",
                "link": f"https://example.com/regulatory/{region}/{i}",
                "source": f"{region} Source",
                "published": "2026-03-29",
                "description": f"{region} policy change {i}",
                "region": region,
                "tags": tag_map.get(region, ["regulation"]),
            }
            for i in range(count)
        ]

    def test_run_creates_regulatory_post_from_all_regions(self):
        dedup = _make_mock_dedup_engine()
        post_gen = _make_mock_post_generator("_posts/2026-03-29-regulatory.md")
        fetch_batches = [
            self._sample_regulatory_items("미국", 2),
            self._sample_regulatory_items("한국", 1),
            self._sample_regulatory_items("아시아", 1),
            self._sample_regulatory_items("유럽", 1),
        ]
        summarizer_cls = TestCollectorContentAndImages._make_theme_summarizer_for_content()

        with _base_collector_patches(dedup=dedup, post_gen=post_gen):
            from collect_regulatory import RegulatoryCollector

            collector = RegulatoryCollector()

        with (
            patch("collect_regulatory.fetch_region_feeds", side_effect=fetch_batches),
            patch("collect_regulatory.enrich_items"),
            patch("collect_regulatory.deduplicate_by_url", side_effect=lambda rows: rows),
            patch("collect_regulatory.ThemeSummarizer", summarizer_cls),
            patch(
                "collect_regulatory.build_region_section",
                side_effect=lambda items, title, links: [f"## {title}", f"{len(items)}건"],
            ),
            patch("collect_regulatory._build_regulatory_theme_analysis", return_value="## 규제 테마 분석\n내용"),
        ):
            collector.run()

        kwargs = post_gen.create_post.call_args.kwargs
        assert kwargs["title"] == "글로벌 규제 동향 리포트 - 2026-03-29"
        # Region sections are auto-numbered ("## 1. 미국 규제 동향", ...) since the
        # 2026-05-22 Designer audit.
        assert "미국 규제 동향" in kwargs["content"]
        assert re.search(r"## \d+\. 미국 규제 동향", kwargs["content"])
        assert "## 규제 테마 분석" in kwargs["content"]
        dedup.save.assert_called_once()


class TestPoliticalTradesCollectorIntegration:
    """Integration coverage for the political trades collector."""

    @staticmethod
    def _sample_political_item(title: str, source: str, tags: List[str], index: int) -> Dict[str, Any]:
        return {
            "title": title,
            "link": f"https://example.com/political/{index}",
            "source": source,
            "published": "2026-03-29",
            "description": f"{title} 관련 세부 설명입니다.",
            "tags": tags,
        }

    def test_run_creates_post_with_briefing_image_and_sectioned_content(self):
        dedup = _make_mock_dedup_engine()
        post_gen = _make_mock_post_generator("_posts/2026-03-29-political.md")
        congress = [
            self._sample_political_item(
                "Congressional disclosure points to $NVDA buy",
                "Capitol Trades",
                ["congress", "pelosi"],
                1,
            )
        ]
        sec = [self._sample_political_item("SEC Form 4 reveals insider sale", "SEC EDGAR", ["sec"], 2)]
        trump = [self._sample_political_item("Trump executive order signals tariff review", "Reuters", ["trump"], 3)]
        korea = [self._sample_political_item("이재명 재산 공개 업데이트", "연합뉴스", ["korea"], 4)]
        central_bank = [
            self._sample_political_item(
                "Federal Reserve rate decision due this week", "Federal Reserve", ["central-bank"], 5
            )
        ]

        with _base_collector_patches(dedup=dedup, post_gen=post_gen):
            from collect_political_trades import PoliticalTradesCollector

            collector = PoliticalTradesCollector()

        fake_img_module = MagicMock()
        fake_img_module.generate_news_briefing_card.return_value = (
            "/Users/yong/Desktop/personal/investing/assets/images/generated/news-briefing-political-2026-03-29.png"
        )

        with (
            patch("collect_political_trades.fetch_congressional_trades", return_value=congress),
            patch("collect_political_trades.fetch_sec_insider_trades", return_value=sec),
            patch("collect_political_trades.fetch_trump_executive_orders", return_value=trump),
            patch("collect_political_trades.fetch_korean_political_trades", return_value=korea),
            patch("collect_political_trades.fetch_central_bank_policy", return_value=central_bank),
            patch("collect_political_trades.deduplicate_by_url", side_effect=lambda rows: rows),
            patch("collect_political_trades.enrich_items"),
            patch.dict(sys.modules, {"common.image_generator": fake_img_module}),
        ):
            collector.run()

        kwargs = post_gen.create_post.call_args.kwargs
        assert kwargs["slug"] == "daily-political-trades-report"
        assert kwargs["image"].endswith("news-briefing-political-2026-03-29.png")
        assert "![news-briefing-political]" in kwargs["content"]
        # Section headings are auto-numbered ("## N. 미국 의회 거래 동향").
        assert re.search(r"## \d+\. 미국 의회 거래 동향", kwargs["content"])
        assert re.search(r"## \d+\. 정책 영향 분석", kwargs["content"])
        assert dedup.mark_seen.call_count == 6
        dedup.save.assert_called_once()


class TestMarketIndicatorsCollectorIntegration:
    """Integration coverage for market indicators orchestration."""

    @staticmethod
    def _sample_indicator_news(title: str, source: str, index: int) -> Dict[str, Any]:
        return {
            "title": title,
            "link": f"https://example.com/indicator/{index}",
            "source": source,
            "published": "2026-03-29",
            "description": f"{title} 설명",
            "tags": ["market-analysis"],
        }

    def test_run_creates_market_indicators_post_with_signal_tracking_and_briefing_image(self):
        dedup = _make_mock_dedup_engine()
        post_gen = _make_mock_post_generator("_posts/2026-03-29-indicators.md")
        cnn_fg = {"score": 24.0, "rating": "Fear", "change": -3.0}
        market_data = {
            "VIX": {"price": 22.5, "price_fmt": "22.50", "change_pct": 1.2, "change_pct_fmt": "+1.20%"},
            "DXY": {"price": 104.1, "price_fmt": "104.10", "change_pct": 0.3, "change_pct_fmt": "+0.30%"},
            "Gold": {"price": 2345.6, "price_fmt": "2345.60", "change_pct": -0.2, "change_pct_fmt": "-0.20%"},
        }
        fred_data = {
            "GS10": {"label": "10Y Treasury", "value": 4.2, "change": 0.10, "date": "2026-03-29"},
            "DGS10": {"label": "10Y Treasury", "value": 4.2, "change": 0.10, "date": "2026-03-29"},
            "FEDFUNDS": {"label": "Fed Funds", "value": 5.25, "change": 0.00, "date": "2026-03-29"},
        }
        treasury_news = [self._sample_indicator_news("Treasury yields rise as dollar firms", "Google News", 1)]
        put_call_news = [self._sample_indicator_news("Put/call ratio spikes above trend", "Google News", 2)]
        breadth_news = [self._sample_indicator_news("Breadth weakens despite index gains", "Google News", 3)]
        margin_news = [self._sample_indicator_news("Margin debt remains elevated", "Google News", 4)]

        with _base_collector_patches(dedup=dedup, post_gen=post_gen):
            from collect_market_indicators import MarketIndicatorsCollector

            collector = MarketIndicatorsCollector()

        composer = MagicMock()
        composer.compose_signals.return_value = MagicMock(score=61.2, verdict="bullish")
        composer.analyze_stance.return_value = "risk-on"
        composer.generate_prediction_markdown.return_value = "## 시장 전망\n위험 선호"
        tracker = MagicMock()
        tracker.format_accuracy_summary.return_value = "## 신호 정확도\n최근 30일 요약"
        analyst = MagicMock()
        analyst.analyze.return_value = {"stance": "risk-on"}
        analyst.generate_brief_outlook.return_value = "멀티 관점 요약"
        fake_img_module = MagicMock()
        fake_img_module.generate_news_briefing_card.return_value = (
            "/Users/yong/Desktop/personal/investing/assets/images/generated/news-briefing-indicators-2026-03-29.png"
        )

        with (
            patch("collect_market_indicators.get_env", return_value="fred-key"),
            patch("collect_market_indicators.fetch_cnn_fear_greed", return_value=cnn_fg),
            patch("collect_market_indicators.fetch_yfinance_market_data", return_value=market_data),
            patch("collect_market_indicators.fetch_fred_indicators", return_value=fred_data),
            patch("collect_market_indicators.fetch_treasury_yield_news", return_value=(treasury_news, 0)),
            patch("collect_market_indicators.fetch_put_call_ratio_news", return_value=(put_call_news, 0)),
            patch("collect_market_indicators.fetch_market_breadth_news", return_value=(breadth_news, 0)),
            patch("collect_market_indicators.fetch_margin_debt_news", return_value=(margin_news, 0)),
            patch("collect_market_indicators.fetch_btc_price", return_value=88000.0),
            patch("collect_market_indicators.SignalComposer", return_value=composer),
            patch("collect_market_indicators.SignalTracker", return_value=tracker),
            patch("collect_market_indicators.BettaFishAnalyzer", return_value=analyst),
            patch.dict(sys.modules, {"common.image_generator": fake_img_module}),
        ):
            collector.run()

        kwargs = post_gen.create_post.call_args.kwargs
        assert kwargs["slug"] == "daily-market-indicators"
        assert kwargs["image"].endswith("news-briefing-indicators-2026-03-29.png")
        assert "시장 심리 지표" in kwargs["content"]
        assert "## 신호 정확도" in kwargs["content"]
        tracker.record.assert_called_once()
        dedup.mark_seen.assert_called_once()
        dedup.save.assert_called_once()
