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
    """fetch_crypto_rss_feeds returns a list when RSS fetchers are mocked empty.

    Patches common.rss_fetcher entry points at the collector's module
    namespace (where they're imported into) so no real network calls.
    """
    mod = importlib.import_module("collect_crypto_news")
    with (
        patch.object(mod, "fetch_rss_feeds_concurrent", return_value=[]),
        patch.object(mod, "fetch_rss_feed", return_value=[]),
    ):
        result = mod.fetch_crypto_rss_feeds()
    assert isinstance(result, list)


def test_collector_run_no_network(tmp_path, monkeypatch):
    """CryptoNewsCollector.run() should not raise even when all fetches return empty."""
    mod = importlib.import_module("collect_crypto_news")

    # Patch all network-touching methods on the collector class
    monkeypatch.setattr(mod, "fetch_cryptopanic", lambda *a, **kw: [])
    monkeypatch.setattr(mod, "_fetch_browser_sources", lambda: ([], []))
    monkeypatch.setattr(mod, "fetch_google_news_crypto", lambda: ([], 0))
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
    monkeypatch.setattr(mod, "fetch_google_news_crypto", lambda: ([], 0))
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


# ---------------------------------------------------------------------------
# Entertainment filter tests
# ---------------------------------------------------------------------------


def test_is_entertainment_item_blocks_pure_sports():
    """순수 스포츠 기사는 필터링되어야 합니다."""
    mod = importlib.import_module("collect_crypto_news")
    item = {"title": "NBA Finals: Lakers vs Celtics Game 7 Preview", "description": ""}
    assert mod._is_entertainment_item(item) is True


def test_is_entertainment_item_blocks_pure_entertainment():
    """순수 엔터테인먼트 기사는 필터링되어야 합니다."""
    mod = importlib.import_module("collect_crypto_news")
    item = {"title": "Grammy Awards 2026: Best Album nominees revealed", "description": ""}
    assert mod._is_entertainment_item(item) is True


def test_is_entertainment_item_passes_crypto_gaming():
    """NFT game 등 크립토 맥락이 있으면 필터링하지 않습니다."""
    mod = importlib.import_module("collect_crypto_news")
    item = {
        "title": "Axie Infinity NFT game token surges 30%",
        "description": "Play-to-earn blockchain game",
    }
    assert mod._is_entertainment_item(item) is False


def test_is_entertainment_item_passes_crypto_news():
    """일반 크립토 뉴스는 필터링하지 않습니다."""
    mod = importlib.import_module("collect_crypto_news")
    item = {"title": "Bitcoin ETF sees record inflows as BTC hits new high", "description": ""}
    assert mod._is_entertainment_item(item) is False


def test_is_entertainment_item_passes_non_entertainment():
    """엔터/스포츠 키워드 없는 일반 기사는 필터링하지 않습니다."""
    mod = importlib.import_module("collect_crypto_news")
    item = {"title": "Federal Reserve signals rate cuts ahead", "description": ""}
    assert mod._is_entertainment_item(item) is False


def test_fetch_google_news_crypto_filters_entertainment(monkeypatch):
    """fetch_google_news_crypto가 엔터테인먼트 아이템을 필터링합니다."""
    mod = importlib.import_module("collect_crypto_news")

    fake_items = [
        {"title": "Bitcoin price analysis weekly roundup", "description": "", "source": "Google News EN"},
        {"title": "Super Bowl halftime show performances ranked", "description": "", "source": "Google News EN"},
    ]
    monkeypatch.setattr(mod, "fetch_rss_feeds_concurrent", lambda feeds: fake_items)

    result, _removed = mod.fetch_google_news_crypto()
    titles = [item["title"] for item in result]
    assert "Bitcoin price analysis weekly roundup" in titles
    assert "Super Bowl halftime show performances ranked" not in titles


# ---------------------------------------------------------------------------
# DeFiLlama hacks (security incident 2차 소스)
# ---------------------------------------------------------------------------


def _defillama_response(payload):
    resp = MagicMock()
    resp.json.return_value = payload
    return resp


def test_fetch_defillama_hacks_maps_incidents_and_filters_old():
    """최근 hack은 rekt-style 항목으로 매핑하고 오래된 항목은 제외합니다."""
    import time

    mod = importlib.import_module("collect_crypto_news")
    now = time.time()
    payload = [
        {
            "name": "Acme Bridge",
            "technique": "Flashloan Price Manipulation",
            "classification": "Protocol Logic",
            "amount": 1_500_000,
            "chain": ["Ethereum"],
            "source": "https://example.com/acme-incident",
            "date": now - 2 * 86400,
        },
        {
            "name": "Ancient Hack",
            "technique": "Reentrancy",
            "amount": 9_000,
            "chain": ["BSC"],
            "source": "",
            "date": now - 999 * 86400,  # 윈도우 밖 → 제외
        },
    ]
    with patch.object(mod, "request_with_retry", return_value=_defillama_response(payload)):
        items = mod.fetch_defillama_hacks(limit=8, days=30)

    assert len(items) == 1
    item = items[0]
    assert item["title"].startswith("[Security] Acme Bridge exploit")
    assert "Flashloan Price Manipulation" in item["title"]
    assert "Funds Lost: $1,500,000" in item["description"]
    assert "Technique: Flashloan Price Manipulation" in item["description"]
    assert "Chain: Ethereum" in item["description"]
    assert item["link"] == "https://example.com/acme-incident"
    assert item["source"] == "DeFiLlama"
    assert item["category_override"] == "security-alerts"


def test_fetch_defillama_hacks_empty_source_uses_per_incident_anchor():
    """source가 비면 사건별 앵커 링크로 폴백해 사건 간 링크가 구분됩니다."""
    import time

    mod = importlib.import_module("collect_crypto_news")
    now = time.time()
    payload = [
        {"name": "Proj One", "technique": "Exploit A", "amount": None, "chain": "Ethereum", "source": "", "date": now},
        {"name": "Proj Two", "technique": "Exploit B", "amount": 0, "chain": ["BSC"], "source": "", "date": now},
    ]
    with patch.object(mod, "request_with_retry", return_value=_defillama_response(payload)):
        items = mod.fetch_defillama_hacks(limit=8, days=30)

    links = [it["link"] for it in items]
    assert len(set(links)) == len(links) == 2  # 사건별로 구분된 링크
    assert all(link.startswith("https://defillama.com/hacks#") for link in links)
    # amount가 null/0이면 Funds Lost 메타데이터를 생략 (다운스트림 게이트와 일관)
    assert all("Funds Lost:" not in it["description"] for it in items)


def test_fetch_defillama_hacks_returns_empty_on_error():
    """API 오류 시 graceful degradation으로 빈 리스트를 반환합니다."""
    mod = importlib.import_module("collect_crypto_news")
    with patch.object(mod, "request_with_retry", side_effect=RuntimeError("offline")):
        assert mod.fetch_defillama_hacks() == []


def test_fetch_defillama_hacks_handles_non_list_payload():
    """예상치 못한 페이로드 타입은 빈 리스트로 처리합니다."""
    mod = importlib.import_module("collect_crypto_news")
    with patch.object(mod, "request_with_retry", return_value=_defillama_response({"error": "nope"})):
        assert mod.fetch_defillama_hacks() == []
