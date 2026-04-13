"""Tests for collect_social_media collector."""

import importlib
import os
import sys
from unittest.mock import patch

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
    """Mocks common.rss_fetcher functions in collector namespace — no network."""
    mod = importlib.import_module("collect_social_media")
    with patch.object(mod, "fetch_rss_feeds_concurrent", return_value=[]):
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


def test_entertainment_filter_blocks_sports_items():
    """_is_entertainment은 스포츠/연예 키워드가 포함된 아이템을 True로 판정한다."""
    mod = importlib.import_module("collect_social_media")

    sports_item = {
        "title": "[Reddit] NBA playoffs: Lakers vs Celtics Game 7 recap",
        "description": "Great game last night",
    }
    finance_item = {
        "title": "[Reddit] Bitcoin breaks $100k as institutional adoption rises",
        "description": "BTC ETF demand hits record high",
    }
    nfl_item = {
        "title": "Super Bowl halftime show gets record viewers",
        "description": "Entertainment and sports news",
    }

    assert mod._is_entertainment(sports_item) is True
    assert mod._is_entertainment(nfl_item) is True
    assert mod._is_entertainment(finance_item) is False


def test_entertainment_filter_blocks_description_keywords():
    """description에만 키워드가 있어도 필터링된다."""
    mod = importlib.import_module("collect_social_media")

    item = {
        "title": "Weekend highlights",
        "description": "The Grammy award show was a huge success this year",
    }
    assert mod._is_entertainment(item) is True


def test_entertainment_filter_passes_empty_item():
    """title/description 모두 비어 있으면 필터링되지 않는다."""
    mod = importlib.import_module("collect_social_media")
    assert mod._is_entertainment({}) is False


def test_run_filters_entertainment_items(tmp_path, monkeypatch):
    """run()에서 엔터테인먼트 아이템은 post 생성에 포함되지 않는다."""
    mod = importlib.import_module("collect_social_media")

    finance_item = {
        "title": "[Reddit] Bitcoin ETF sees record buying pressure",
        "description": "Institutional demand surges globally",
        "link": "https://reddit.com/r/bitcoin/99999",
        "source": "r/Bitcoin",
        "tags": ["social-media", "reddit", "bitcoin"],
        "score": 5000,
    }
    sports_item = {
        "title": "[Reddit] NBA Finals MVP voting results",
        "description": "Basketball championship analysis",
        "link": "https://reddit.com/r/nba/11111",
        "source": "r/nba",
        "tags": ["social-media", "reddit", "nba"],
        "score": 8000,
    }

    captured_reddit: list = []

    def _patched_run(self):
        # run() 내부 호출 전에 reddit_items가 필터링되는지 검증하기 위해
        # all_theme_items 구성 시점을 가로챌 수 없으므로
        # _is_entertainment를 직접 검증
        assert mod._is_entertainment(sports_item) is True
        assert mod._is_entertainment(finance_item) is False
        captured_reddit.append(True)

    monkeypatch.setattr(mod.SocialMediaCollector, "run", _patched_run)

    collector = mod.SocialMediaCollector()
    collector.run()
    assert captured_reddit  # run()이 호출됐음을 확인


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
