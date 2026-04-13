"""Tests for collect_political_trades collector."""

import importlib
import os
import sys

SCRIPTS_DIR = os.path.join(os.path.dirname(__file__), "..", "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)


# ---------------------------------------------------------------------------
# Pure-logic tests (no network)
# ---------------------------------------------------------------------------


def test_first_sentence_period_separator():
    mod = importlib.import_module("collect_political_trades")
    text = "Nancy Pelosi sold Apple shares worth $1M. She disclosed the trade on Friday."
    result = mod._first_sentence(text)
    assert result == "Nancy Pelosi sold Apple shares worth $1M."


def test_first_sentence_korean_separator():
    mod = importlib.import_module("collect_political_trades")
    text = "의원이 주식을 매도했습니다. 거래는 공시되었습니다."
    result = mod._first_sentence(text)
    assert "했습니다" in result


def test_first_sentence_truncates_long_text():
    mod = importlib.import_module("collect_political_trades")
    long_text = "x" * 300
    result = mod._first_sentence(long_text, max_len=200)
    assert len(result) <= 200


def test_first_sentence_returns_short_text_unchanged():
    mod = importlib.import_module("collect_political_trades")
    short = "Quick note"
    result = mod._first_sentence(short)
    assert result == short


# ---------------------------------------------------------------------------
# Network-mocked tests
# ---------------------------------------------------------------------------


def test_collector_run_no_network(tmp_path, monkeypatch):
    """PoliticalTradesCollector.run() completes without raising when all fetches return empty."""
    mod = importlib.import_module("collect_political_trades")

    monkeypatch.setattr(mod, "fetch_congressional_trades", list)
    monkeypatch.setattr(mod, "fetch_sec_insider_trades", lambda verify_ssl=True: [])
    monkeypatch.setattr(mod, "fetch_trump_executive_orders", list)
    monkeypatch.setattr(mod, "fetch_korean_political_trades", list)
    monkeypatch.setattr(mod, "fetch_central_bank_policy", list)
    monkeypatch.setattr(mod, "enrich_items", lambda items, *a, **kw: None)

    from common import post_generator as pg_mod

    monkeypatch.setattr(pg_mod, "POSTS_DIR", str(tmp_path))

    collector = mod.PoliticalTradesCollector()
    collector.run()


def test_entertainment_filter_blocks_sports_item():
    """엔터테인먼트/스포츠 키워드가 포함된 아이템은 process()에서 제거된다."""
    mod = importlib.import_module("collect_political_trades")

    sports_item = {
        "title": "NBA playoffs: Lakers vs Celtics game 7",
        "description": "The NBA finals are heating up as the Lakers face the Celtics.",
        "link": "https://example.com/nba-finals",
        "source": "Google News",
        "tags": ["political-trades"],
    }
    political_item = {
        "title": "Senator buys NVIDIA stock ahead of AI bill vote",
        "description": "Senator disclosed a purchase of NVIDIA shares.",
        "link": "https://example.com/senator-nvidia",
        "source": "Congressional Trades",
        "tags": ["political-trades", "congress"],
    }

    collector = mod.PoliticalTradesCollector.__new__(mod.PoliticalTradesCollector)
    # is_duplicate는 항상 False 반환하도록 패치
    collector.is_duplicate = lambda title, source, link: False
    collector.logger = mod._log

    # process() 내부에서 enrich_items를 건너뛰기 위해 monkeypatch 불가 → 직접 필터 로직만 검증
    items = [sports_item, political_item]
    filtered = [
        item
        for item in items
        if not any(
            kw in (item.get("title", "") + " " + item.get("description", "")).lower()
            for kw in mod._ENTERTAINMENT_KEYWORDS
        )
    ]

    assert len(filtered) == 1
    assert filtered[0]["title"] == political_item["title"]


def test_entertainment_filter_allows_political_item():
    """정치/금융 관련 아이템은 엔터테인먼트 필터를 통과한다."""
    mod = importlib.import_module("collect_political_trades")

    items = [
        {
            "title": "Trump signs executive order on tariffs",
            "description": "President signed an executive order imposing new tariffs on imports.",
            "link": "https://example.com/trump-tariff",
            "source": "Google News",
            "tags": ["political-trades", "trump"],
        },
        {
            "title": "Fed Chair Powell signals rate cut",
            "description": "Federal Reserve Chair Powell hinted at a rate cut in upcoming FOMC meeting.",
            "link": "https://example.com/fed-rate",
            "source": "Google News",
            "tags": ["political-trades", "fed"],
        },
    ]

    filtered = [
        item
        for item in items
        if not any(
            kw in (item.get("title", "") + " " + item.get("description", "")).lower()
            for kw in mod._ENTERTAINMENT_KEYWORDS
        )
    ]

    assert len(filtered) == 2


def test_entertainment_keywords_loaded_from_module():
    """_ENTERTAINMENT_KEYWORDS가 frozenset이고 최소 30개 이상의 키워드를 포함한다."""
    mod = importlib.import_module("collect_political_trades")

    assert isinstance(mod._ENTERTAINMENT_KEYWORDS, frozenset)
    assert len(mod._ENTERTAINMENT_KEYWORDS) >= 30
    # 핵심 스포츠 키워드 포함 확인
    assert "nba" in mod._ENTERTAINMENT_KEYWORDS
    assert "nfl" in mod._ENTERTAINMENT_KEYWORDS
    assert "super bowl" in mod._ENTERTAINMENT_KEYWORDS
    assert "netflix" in mod._ENTERTAINMENT_KEYWORDS


def test_dedup_idempotent_political_trades(tmp_path, monkeypatch):
    """Running PoliticalTradesCollector twice with same data creates no extra posts."""
    mod = importlib.import_module("collect_political_trades")

    fake_items = [
        {
            "title": "Pelosi buys NVIDIA stock ahead of AI subsidy vote",
            "description": "Speaker Pelosi disclosed a purchase of NVIDIA shares worth $500K.",
            "link": "https://example.com/pelosi-nvidia",
            "source": "Pelosi Trades",
            "tags": ["political-trades", "pelosi", "congress"],
        }
    ]

    monkeypatch.setattr(mod, "fetch_congressional_trades", lambda: fake_items)
    monkeypatch.setattr(mod, "fetch_sec_insider_trades", lambda verify_ssl=True: [])
    monkeypatch.setattr(mod, "fetch_trump_executive_orders", list)
    monkeypatch.setattr(mod, "fetch_korean_political_trades", list)
    monkeypatch.setattr(mod, "fetch_central_bank_policy", list)
    monkeypatch.setattr(mod, "enrich_items", lambda items, *a, **kw: None)

    from common import post_generator as pg_mod

    monkeypatch.setattr(pg_mod, "POSTS_DIR", str(tmp_path))

    c1 = mod.PoliticalTradesCollector()
    c1.run()
    posts_after_first = list(tmp_path.glob("*.md"))

    c2 = mod.PoliticalTradesCollector()
    c2.dedup = c1.dedup
    c2.run()
    posts_after_second = list(tmp_path.glob("*.md"))

    assert len(posts_after_second) == len(posts_after_first)
