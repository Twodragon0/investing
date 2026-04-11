"""Tests for collect_social_media collector."""

import importlib
import os
import sys
from unittest.mock import MagicMock, patch

SCRIPTS_DIR = os.path.join(os.path.dirname(__file__), "..", "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)


# ---------------------------------------------------------------------------
# Pure-logic tests (no network)
# ---------------------------------------------------------------------------


def test_parse_telegram_items_bs4_path():
    """_parse_telegram_items handles mock objects that simulate the BS4 branch.

    BS4 Tag objects expose a `query_selector` attribute in recent versions,
    which routes them into the Playwright branch and fails silently.
    We use a plain namespace object without `query_selector` to exercise
    the BS4 dict-style branch directly.
    """
    mod = importlib.import_module("collect_social_media")

    class _FakeTextDiv:
        def get_text(self, sep=" ", strip=True):
            return "Bitcoin just broke $90k support! Very important news today."

    class _FakeTime:
        def get(self, attr, default=""):
            return "2026-04-11T10:00:00Z" if attr == "datetime" else default

    class _FakeLink:
        def get(self, attr, default=""):
            return "https://t.me/cryptonews/12345" if attr == "href" else default

    class _FakeMsg:
        """Mimics BS4 Tag without `query_selector` so the BS4 branch is taken."""

        def find(self, tag, class_=None):
            if tag == "div":
                return _FakeTextDiv()
            if tag == "time":
                return _FakeTime()
            if tag == "a":
                return _FakeLink()
            return None

    items = mod._parse_telegram_items("cryptonews", [_FakeMsg()], limit=5)
    assert len(items) == 1
    assert "Telegram" in items[0]["title"]
    assert items[0]["link"] == "https://t.me/cryptonews/12345"


def test_parse_telegram_items_skips_short_text():
    mod = importlib.import_module("collect_social_media")
    from bs4 import BeautifulSoup

    html = """
    <div class="tgme_widget_message_wrap">
      <div class="tgme_widget_message_text">Hi</div>
    </div>
    """
    soup = BeautifulSoup(html, "html.parser")
    messages = soup.find_all("div", class_="tgme_widget_message_wrap")
    items = mod._parse_telegram_items("testchannel", messages, limit=5)
    assert items == []


def test_fetch_twitter_search_skips_when_no_token():
    mod = importlib.import_module("collect_social_media")
    result = mod.fetch_twitter_search("", "bitcoin", 10)
    assert result == []


def test_fetch_telegram_channel_handles_request_error():
    mod = importlib.import_module("collect_social_media")
    import requests
    with patch("requests.get", side_effect=requests.exceptions.ConnectionError("offline")):
        result = mod.fetch_telegram_channel("cryptonews")
    assert result == []


# ---------------------------------------------------------------------------
# Network-mocked tests
# ---------------------------------------------------------------------------


def test_fetch_google_news_social_returns_list():
    mod = importlib.import_module("collect_social_media")
    entry = MagicMock()
    entry.title = "Crypto twitter sentiment bullish"
    entry.link = "https://example.com/social"
    entry.published = ""
    entry.summary = "desc"
    entry.get = lambda k, d="": d

    feed = MagicMock()
    feed.bozo = False
    feed.entries = [entry]
    feed.feed = MagicMock()
    feed.feed.get = lambda k, d="": d

    with patch("feedparser.parse", return_value=feed):
        result = mod.fetch_google_news_social()
    assert isinstance(result, list)


def test_collector_run_no_network(tmp_path, monkeypatch):
    """SocialMediaCollector.run() completes without raising when all fetches return empty."""
    mod = importlib.import_module("collect_social_media")

    # Patch Playwright check so browser path is skipped
    monkeypatch.setattr(mod, "is_playwright_available", lambda: False)
    monkeypatch.setattr(mod, "fetch_telegram_channel", lambda ch, limit=10: [])
    monkeypatch.setattr(mod, "fetch_twitter_search", lambda token, q, limit=10: [])
    monkeypatch.setattr(mod, "fetch_google_news_social", list)
    monkeypatch.setattr(mod, "fetch_reddit_posts", lambda limit=10: [])
    monkeypatch.setattr(mod, "fetch_political_economy_news", list)
    monkeypatch.setattr(mod, "enrich_items", lambda items, *a, **kw: None)

    from common import post_generator as pg_mod
    monkeypatch.setattr(pg_mod, "POSTS_DIR", str(tmp_path))

    collector = mod.SocialMediaCollector()
    collector.run()


def test_dedup_idempotent_social(tmp_path, monkeypatch):
    """Running SocialMediaCollector twice with same social data creates no extra posts."""
    mod = importlib.import_module("collect_social_media")

    fake_social = [
        {
            "title": "[Reddit] Bitcoin discussion thread hits 10k upvotes",
            "description": "Community very bullish",
            "link": "https://reddit.com/r/bitcoin/12345",
            "source": "r/Bitcoin",
            "tags": ["social-media", "reddit", "bitcoin"],
            "score": 10000,
        }
    ]

    monkeypatch.setattr(mod, "is_playwright_available", lambda: False)
    monkeypatch.setattr(mod, "fetch_telegram_channel", lambda ch, limit=10: [])
    monkeypatch.setattr(mod, "fetch_twitter_search", lambda token, q, limit=10: [])
    monkeypatch.setattr(mod, "fetch_google_news_social", list)
    monkeypatch.setattr(mod, "fetch_reddit_posts", lambda limit=10: fake_social)
    monkeypatch.setattr(mod, "fetch_political_economy_news", list)
    monkeypatch.setattr(mod, "enrich_items", lambda items, *a, **kw: None)

    from common import post_generator as pg_mod
    monkeypatch.setattr(pg_mod, "POSTS_DIR", str(tmp_path))

    c1 = mod.SocialMediaCollector()
    c1.run()
    posts_after_first = list(tmp_path.glob("*.md"))

    c2 = mod.SocialMediaCollector()
    c2.dedup = c1.dedup
    c2.run()
    posts_after_second = list(tmp_path.glob("*.md"))

    assert len(posts_after_second) == len(posts_after_first)
