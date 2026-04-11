"""Tests for collect_crypto_news collector."""

import importlib
import os
import sys
from unittest.mock import MagicMock, patch

# Ensure scripts/ is on path (conftest does this, but be explicit)
SCRIPTS_DIR = os.path.join(os.path.dirname(__file__), "..", "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rss_xml(title: str, link: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Feed</title>
    <item>
      <title>{title}</title>
      <link>{link}</link>
      <pubDate>Mon, 11 Apr 2026 06:00:00 +0000</pubDate>
      <description>Test description for {title}.</description>
    </item>
  </channel>
</rss>"""


def _mock_feedparser_result(title: str = "BTC news", link: str = "https://example.com/btc"):
    entry = MagicMock()
    entry.title = title
    entry.link = link
    entry.get = lambda k, d="": {"published": "", "summary": "desc"}.get(k, d)
    entry.published = ""
    entry.summary = "Test description"

    feed = MagicMock()
    feed.bozo = False
    feed.entries = [entry]
    feed.feed = MagicMock()
    feed.feed.get = lambda k, d="": d
    return feed


# ---------------------------------------------------------------------------
# Pure-logic tests (no network)
# ---------------------------------------------------------------------------


def test_binance_desc_from_title_listing():
    mod = importlib.import_module("collect_crypto_news")
    result = mod._binance_desc_from_title("New Token Listing Announcement")
    assert "상장" in result


def test_binance_desc_from_title_delist():
    mod = importlib.import_module("collect_crypto_news")
    # "Delist" contains "list" which matches the first branch; use a title
    # with only the delist keyword to test that branch explicitly.
    result = mod._binance_desc_from_title("Removal Notice for Token")
    assert "상장폐지" in result


def test_is_exchange_promo_item_detects_promo():
    mod = importlib.import_module("collect_crypto_news")
    item = {"title": "Earn 200 USDT APR yield arena event"}
    assert mod._is_exchange_promo_item(item) is True


def test_is_exchange_promo_item_passes_legit():
    mod = importlib.import_module("collect_crypto_news")
    item = {"title": "Bitcoin Network Upgrade Scheduled for Q2"}
    assert mod._is_exchange_promo_item(item) is False


def test_score_security_severity_critical():
    mod = importlib.import_module("collect_crypto_news")
    sev = mod._score_security_severity("Bridge exploit drains $1.2 billion from protocol", "")
    assert "CRITICAL" in sev or "HIGH" in sev


def test_score_security_severity_low():
    mod = importlib.import_module("collect_crypto_news")
    sev = mod._score_security_severity("Bitcoin price analysis weekly roundup", "")
    assert "LOW" in sev


# ---------------------------------------------------------------------------
# Network-mocked tests
# ---------------------------------------------------------------------------


def test_fetch_cryptopanic_returns_empty_when_no_key():
    mod = importlib.import_module("collect_crypto_news")
    result = mod.fetch_cryptopanic("")
    assert result == []


def test_fetch_cryptopanic_handles_request_error():
    mod = importlib.import_module("collect_crypto_news")
    import requests
    with patch("requests.get", side_effect=requests.exceptions.ConnectionError("offline")):
        result = mod.fetch_cryptopanic("fake-key")
    assert result == []


def test_fetch_crypto_rss_feeds_returns_list(tmp_path):
    """fetch_crypto_rss_feeds mocks feedparser to avoid network calls."""
    mod = importlib.import_module("collect_crypto_news")
    mock_feed = _mock_feedparser_result("Bitcoin ETF approved", "https://coindesk.com/btc-etf")
    with patch("feedparser.parse", return_value=mock_feed):
        result = mod.fetch_crypto_rss_feeds()
    assert isinstance(result, list)


def test_collector_run_no_network(tmp_path, monkeypatch):
    """CryptoNewsCollector.run() should not raise even when all fetches return empty."""
    mod = importlib.import_module("collect_crypto_news")

    # Patch all network-touching methods on the collector class
    monkeypatch.setattr(mod, "fetch_cryptopanic", lambda *a, **kw: [])
    monkeypatch.setattr(mod, "_fetch_browser_sources", lambda: ([], []))
    monkeypatch.setattr(mod, "fetch_google_news_crypto", list)
    monkeypatch.setattr(mod, "fetch_crypto_rss_feeds", list)
    monkeypatch.setattr(mod, "_fetch_binance_bapi", list)
    monkeypatch.setattr(mod, "fetch_rekt_news", lambda *a, **kw: [])
    monkeypatch.setattr(mod, "fetch_google_news_security", list)

    monkeypatch.setattr(mod, "enrich_items", lambda items, *a, **kw: None)

    # Redirect _posts/ writes to tmp_path
    from common import post_generator as pg_mod
    monkeypatch.setattr(pg_mod, "POSTS_DIR", str(tmp_path))

    collector = mod.CryptoNewsCollector()
    collector.run()  # must not raise


def test_dedup_idempotent_crypto(tmp_path, monkeypatch):
    """Running CryptoNewsCollector twice with same data must not create two posts."""
    mod = importlib.import_module("collect_crypto_news")

    fake_item = {
        "title": "Crypto News Test Item",
        "description": "Some description",
        "link": "https://example.com/crypto-1",
        "source": "TestSource",
        "tags": ["crypto"],
    }

    monkeypatch.setattr(mod, "fetch_cryptopanic", lambda *a, **kw: [fake_item])
    monkeypatch.setattr(mod, "_fetch_browser_sources", lambda: ([], []))
    monkeypatch.setattr(mod, "fetch_google_news_crypto", list)
    monkeypatch.setattr(mod, "fetch_crypto_rss_feeds", list)
    monkeypatch.setattr(mod, "_fetch_binance_bapi", list)
    monkeypatch.setattr(mod, "fetch_rekt_news", lambda *a, **kw: [])
    monkeypatch.setattr(mod, "fetch_google_news_security", list)
    monkeypatch.setattr(mod, "enrich_items", lambda items, *a, **kw: None)

    from common import post_generator as pg_mod
    monkeypatch.setattr(pg_mod, "POSTS_DIR", str(tmp_path))

    # First run — may create a post
    c1 = mod.CryptoNewsCollector()
    c1.run()
    posts_after_first = list(tmp_path.glob("*.md"))

    # Second run with shared state (same dedup engine state dir)
    c2 = mod.CryptoNewsCollector()
    # Share the same dedup state so second run sees first run's state
    c2.dedup = c1.dedup
    c2.run()
    posts_after_second = list(tmp_path.glob("*.md"))

    assert len(posts_after_second) == len(posts_after_first), (
        "Second run should not create additional posts for same content"
    )
