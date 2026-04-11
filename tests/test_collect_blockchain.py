"""Tests for collect_blockchain collector."""

import importlib
import os
import sys

SCRIPTS_DIR = os.path.join(os.path.dirname(__file__), "..", "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)


# ---------------------------------------------------------------------------
# Pure-logic helpers
# ---------------------------------------------------------------------------


def test_fmt_hash_rate_ehs():
    mod = importlib.import_module("collect_blockchain")
    assert mod._fmt_hash_rate(500.0) == "500.0 EH/s"


def test_fmt_hash_rate_zhs():
    mod = importlib.import_module("collect_blockchain")
    assert mod._fmt_hash_rate(1500.0) == "1.50 ZH/s"


def test_fmt_difficulty():
    mod = importlib.import_module("collect_blockchain")
    assert mod._fmt_difficulty(88_000_000_000_000) == "88.00T"


def test_fmt_number_int():
    mod = importlib.import_module("collect_blockchain")
    assert mod._fmt_number(1_234_567) == "1,234,567"


def test_fmt_number_float():
    mod = importlib.import_module("collect_blockchain")
    assert mod._fmt_number(1234.5) == "1,234.50"


def test_fmt_usd_billions():
    mod = importlib.import_module("collect_blockchain")
    assert mod._fmt_usd(2_500_000_000) == "$2.50B"


def test_fmt_usd_millions():
    mod = importlib.import_module("collect_blockchain")
    assert mod._fmt_usd(3_200_000) == "$3.20M"


def test_fmt_usd_small():
    mod = importlib.import_module("collect_blockchain")
    assert mod._fmt_usd(500) == "$500"


# ---------------------------------------------------------------------------
# build_report_content pure-logic tests
# ---------------------------------------------------------------------------


def test_build_report_content_btc_only_contains_key_sections():
    mod = importlib.import_module("collect_blockchain")
    btc = {
        "hash_rate_ehs": 600.0,
        "difficulty": 88_000_000_000_000,
        "n_tx": 350_000,
        "block_time_min": 10.0,
        "blocks_total": 840_000,
    }
    content, description, excerpt = mod.build_report_content(btc, {}, "2026-04-11")
    assert "Bitcoin 네트워크 현황" in content
    assert "600.0 EH/s" in content
    assert "BTC 해시레이트" in description
    assert isinstance(excerpt, str)


def test_build_report_content_fast_block_time_adds_insight():
    mod = importlib.import_module("collect_blockchain")
    btc = {
        "hash_rate_ehs": 700.0,
        "difficulty": 90_000_000_000_000,
        "n_tx": 400_000,
        "block_time_min": 8.0,
        "blocks_total": 850_000,
    }
    content, _desc, _exc = mod.build_report_content(btc, {}, "2026-04-11")
    # block_time < 9 should trigger the fast-block insight
    assert "8.0분" in content


def test_build_report_content_slow_block_time_adds_insight():
    mod = importlib.import_module("collect_blockchain")
    btc = {
        "hash_rate_ehs": 500.0,
        "difficulty": 80_000_000_000_000,
        "n_tx": 300_000,
        "block_time_min": 12.0,
        "blocks_total": 820_000,
    }
    content, _desc, _exc = mod.build_report_content(btc, {}, "2026-04-11")
    # block_time > 11 should trigger slow-block insight
    assert "12.0분" in content


def test_build_report_content_eth_gas_high_congestion_insight():
    mod = importlib.import_module("collect_blockchain")
    eth = {
        "gas_safe": "80",
        "gas_propose": "100",
        "gas_fast": "150",
        "eth_supply": 120_000_000,
        "eth_price_usd": 3_200.0,
    }
    content, _desc, _exc = mod.build_report_content({}, eth, "2026-04-11")
    assert "Ethereum 네트워크 현황" in content
    assert "혼잡" in content


def test_build_report_content_eth_gas_low_idle_insight():
    mod = importlib.import_module("collect_blockchain")
    eth = {
        "gas_safe": "3",
        "gas_propose": "5",
        "gas_fast": "7",
        "eth_supply": 120_000_000,
        "eth_price_usd": 3_200.0,
    }
    content, _desc, _exc = mod.build_report_content({}, eth, "2026-04-11")
    assert "한산" in content


def test_build_report_content_l2_section():
    mod = importlib.import_module("collect_blockchain")
    l2_projects = [
        {"name": "Arbitrum", "tvl": 5_000_000_000, "stage": "Stage 1"},
        {"name": "Optimism", "tvl": 3_000_000_000, "stage": "Stage 1"},
    ]
    content, _desc, _exc = mod.build_report_content({}, {}, "2026-04-11", l2_projects=l2_projects)
    assert "Layer 2 네트워크 활동" in content
    assert "Arbitrum" in content
    assert "Optimism" in content


def test_build_report_content_upgrade_news_section():
    mod = importlib.import_module("collect_blockchain")
    news = [
        {"title": "Ethereum Pectra upgrade", "link": "https://blog.ethereum.org/pectra", "source_name": "Ethereum Blog"},
    ]
    content, _desc, _exc = mod.build_report_content({}, {}, "2026-04-11", upgrade_news=news)
    assert "주요 네트워크 업데이트" in content
    assert "Ethereum Pectra upgrade" in content


def test_build_report_content_empty_data_returns_fallback():
    mod = importlib.import_module("collect_blockchain")
    content, description, excerpt = mod.build_report_content({}, {}, "2026-04-11")
    # Both sections should show unavailable messages
    assert "BTC 네트워크 데이터를 가져올 수 없습니다" in content
    assert "ETH 네트워크 데이터를 가져올 수 없습니다" in content
    assert description == "블록체인 네트워크 일일 리포트"


# ---------------------------------------------------------------------------
# Network-mocked: main() runs without exception
# ---------------------------------------------------------------------------


def _patch_bc_isolation(monkeypatch, tmp_path):
    """Patch POSTS_DIR and dedup STATE_DIR to tmp_path for full isolation."""
    from common import dedup as dedup_mod
    from common import post_generator as pg_mod

    monkeypatch.setattr(pg_mod, "POSTS_DIR", str(tmp_path))
    monkeypatch.setattr(dedup_mod, "STATE_DIR", str(tmp_path / "_state"))


def test_main_runs_with_mocked_network(tmp_path, monkeypatch):
    """BlockchainCollector.run() completes without raising when APIs return mocked data."""
    mod = importlib.import_module("collect_blockchain")

    fake_btc = {
        "hash_rate_ehs": 600.0,
        "difficulty": 88_000_000_000_000,
        "n_tx": 350_000,
        "block_time_min": 10.0,
        "blocks_total": 840_000,
    }
    fake_eth = {
        "gas_safe": "10",
        "gas_propose": "12",
        "gas_fast": "15",
        "eth_supply": 120_000_000,
        "eth_price_usd": 3_200.0,
    }

    # Patch blockchain_api functions in the collect_blockchain namespace
    monkeypatch.setattr(mod, "fetch_btc_stats", lambda: fake_btc)
    monkeypatch.setattr(mod, "fetch_eth_stats", lambda: fake_eth)
    monkeypatch.setattr(mod, "fetch_l2_summary", list)
    monkeypatch.setattr(mod, "fetch_upgrade_news", list)

    _patch_bc_isolation(monkeypatch, tmp_path)

    collector = mod.BlockchainCollector()
    collector.run()  # must not raise


# ---------------------------------------------------------------------------
# Dedup idempotency
# ---------------------------------------------------------------------------


def test_dedup_idempotent_blockchain(tmp_path, monkeypatch):
    """Running BlockchainCollector twice with identical data creates no extra posts."""
    mod = importlib.import_module("collect_blockchain")

    fake_btc = {
        "hash_rate_ehs": 600.0,
        "difficulty": 88_000_000_000_000,
        "n_tx": 350_000,
        "block_time_min": 10.0,
        "blocks_total": 840_000,
    }
    fake_eth = {
        "gas_safe": "10",
        "gas_propose": "12",
        "gas_fast": "15",
        "eth_supply": 120_000_000,
        "eth_price_usd": 3_200.0,
    }

    monkeypatch.setattr(mod, "fetch_btc_stats", lambda: fake_btc)
    monkeypatch.setattr(mod, "fetch_eth_stats", lambda: fake_eth)
    monkeypatch.setattr(mod, "fetch_l2_summary", list)
    monkeypatch.setattr(mod, "fetch_upgrade_news", list)

    _patch_bc_isolation(monkeypatch, tmp_path)

    c1 = mod.BlockchainCollector()
    c1.run()
    posts_after_first = list(tmp_path.glob("*.md"))

    c2 = mod.BlockchainCollector()
    c2.dedup = c1.dedup  # share dedup state — simulates same process re-run
    c2.run()
    posts_after_second = list(tmp_path.glob("*.md"))

    assert len(posts_after_second) == len(posts_after_first)
