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
