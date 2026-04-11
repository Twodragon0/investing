"""Tests for collect_stock_news collector."""

import importlib
import os
import sys
from unittest.mock import MagicMock, patch

SCRIPTS_DIR = os.path.join(os.path.dirname(__file__), "..", "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_feedparser_result(title: str = "S&P 500 hits record", link: str = "https://example.com/sp500"):
    entry = MagicMock()
    entry.title = title
    entry.link = link
    entry.published = ""
    entry.summary = "Test description"
    entry.get = lambda k, d="": {"published": "", "summary": "desc"}.get(k, d)

    feed = MagicMock()
    feed.bozo = False
    feed.entries = [entry]
    feed.feed = MagicMock()
    feed.feed.get = lambda k, d="": d
    return feed


# ---------------------------------------------------------------------------
# Pure-logic tests
# ---------------------------------------------------------------------------


def test_fetch_alpha_vantage_returns_empty_when_no_key():
    mod = importlib.import_module("collect_stock_news")
    result = mod.fetch_alpha_vantage_snapshot("")
    assert result == []


def test_fetch_google_news_browser_stocks_skips_when_playwright_unavailable():
    mod = importlib.import_module("collect_stock_news")
    with patch.object(mod, "is_playwright_available", return_value=False):
        result = mod.fetch_google_news_browser_stocks()
    assert result == []


# ---------------------------------------------------------------------------
# Network-mocked tests
# ---------------------------------------------------------------------------


def test_fetch_financial_rss_feeds_returns_list():
    mod = importlib.import_module("collect_stock_news")
    mock_feed = _mock_feedparser_result("CNBC Market Top Story", "https://cnbc.com/story")
    with patch("feedparser.parse", return_value=mock_feed):
        result = mod.fetch_financial_rss_feeds()
    assert isinstance(result, list)


def test_fetch_yahoo_finance_rss_returns_list():
    mod = importlib.import_module("collect_stock_news")
    mock_feed = _mock_feedparser_result("Yahoo Finance Market News", "https://finance.yahoo.com/news/item")
    with patch("feedparser.parse", return_value=mock_feed):
        result = mod.fetch_yahoo_finance_rss()
    assert isinstance(result, list)


def test_collector_run_no_network(tmp_path, monkeypatch):
    """StockNewsCollector.run() completes without raising when all fetches return empty."""
    mod = importlib.import_module("collect_stock_news")

    monkeypatch.setattr(mod, "fetch_google_news_browser_stocks", list)
    monkeypatch.setattr(mod, "fetch_google_news_stocks", list)
    monkeypatch.setattr(mod, "fetch_yahoo_finance_rss", list)
    monkeypatch.setattr(mod, "fetch_alpha_vantage_snapshot", lambda key: [])
    monkeypatch.setattr(mod, "fetch_financial_rss_feeds", list)
    monkeypatch.setattr(mod, "fetch_sector_rotation_feeds", list)
    monkeypatch.setattr(mod, "fetch_korean_market_data", dict)
    monkeypatch.setattr(mod, "enrich_items", lambda items, *a, **kw: None)

    from common import post_generator as pg_mod
    monkeypatch.setattr(pg_mod, "POSTS_DIR", str(tmp_path))

    collector = mod.StockNewsCollector()
    collector.run()  # must not raise


def test_dedup_idempotent_stock(tmp_path, monkeypatch):
    """Running StockNewsCollector twice with identical data creates no extra posts."""
    mod = importlib.import_module("collect_stock_news")

    fake_items = [
        {
            "title": "KOSPI rises on foreign buying",
            "description": "Markets up today",
            "link": "https://example.com/kospi-1",
            "source": "Google News KR",
            "tags": ["stock", "kospi"],
        }
    ]

    monkeypatch.setattr(mod, "fetch_google_news_browser_stocks", lambda: fake_items)
    monkeypatch.setattr(mod, "fetch_google_news_stocks", list)
    monkeypatch.setattr(mod, "fetch_yahoo_finance_rss", list)
    monkeypatch.setattr(mod, "fetch_alpha_vantage_snapshot", lambda key: [])
    monkeypatch.setattr(mod, "fetch_financial_rss_feeds", list)
    monkeypatch.setattr(mod, "fetch_sector_rotation_feeds", list)
    monkeypatch.setattr(mod, "fetch_korean_market_data", dict)
    monkeypatch.setattr(mod, "enrich_items", lambda items, *a, **kw: None)

    from common import post_generator as pg_mod
    monkeypatch.setattr(pg_mod, "POSTS_DIR", str(tmp_path))

    c1 = mod.StockNewsCollector()
    c1.run()
    posts_after_first = list(tmp_path.glob("*.md"))

    c2 = mod.StockNewsCollector()
    c2.dedup = c1.dedup
    c2.run()
    posts_after_second = list(tmp_path.glob("*.md"))

    assert len(posts_after_second) == len(posts_after_first)
