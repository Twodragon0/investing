"""Tests for collect_defi_yields collector.

Coverage focus:
- Pure-logic helpers (``_format_tvl``, ``_filter_pools``, ``categorize_pools``)
- ``build_post_content`` integration (sections, alert-box, dedup)
- Network-mocked ``fetch_pools`` covering API envelope + error paths
"""

import importlib
import os
import sys
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

SCRIPTS_DIR = os.path.join(os.path.dirname(__file__), "..", "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)


# ---------------------------------------------------------------------------
# Pure-logic tests
# ---------------------------------------------------------------------------


def test_format_tvl_billions():
    mod = importlib.import_module("collect_defi_yields")
    assert mod._format_tvl(2_500_000_000) == "$2.50B"


def test_format_tvl_millions():
    mod = importlib.import_module("collect_defi_yields")
    assert mod._format_tvl(123_456_789) == "$123.5M"


def test_format_tvl_thousands():
    mod = importlib.import_module("collect_defi_yields")
    assert mod._format_tvl(9_500) == "$9.5K"


def test_format_tvl_sub_thousand():
    mod = importlib.import_module("collect_defi_yields")
    assert mod._format_tvl(500) == "$500"


def test_filter_pools_drops_low_tvl_and_apy():
    mod = importlib.import_module("collect_defi_yields")
    pools = [
        {"tvlUsd": 5_000_000, "apy": 4.5, "symbol": "USDC", "project": "Aave"},
        {"tvlUsd": 100, "apy": 50.0, "symbol": "RUG", "project": "Rug"},  # low TVL
        {"tvlUsd": 10_000_000, "apy": 0.0, "symbol": "DEAD", "project": "Dead"},  # zero APY
        {"tvlUsd": 2_000_000, "apy": 8.0, "symbol": "WETH", "project": "Lido"},
        {"tvlUsd": None, "apy": None, "symbol": "X", "project": "Y"},  # None values
        "not-a-dict",  # type guard
    ]
    result = mod._filter_pools(pools)
    assert len(result) == 2
    projects = {p["project"] for p in result}
    assert projects == {"Aave", "Lido"}


def test_categorize_pools_separates_buckets_and_sorts():
    mod = importlib.import_module("collect_defi_yields")
    pools = [
        {"tvlUsd": 20_000_000, "apy": 5.5, "symbol": "USDC", "project": "Aave",  "stablecoin": True},
        {"tvlUsd": 30_000_000, "apy": 4.0, "symbol": "DAI",  "project": "Maker", "stablecoin": True},
        {"tvlUsd": 25_000_000, "apy": 3.5, "symbol": "WETH", "project": "Lido",  "stablecoin": False},
        {"tvlUsd": 15_000_000, "apy": 7.0, "symbol": "ETH",  "project": "Rocket","stablecoin": False},
        {"tvlUsd": 10_000_000, "apy": 2.0, "symbol": "WBTC", "project": "Babylon","stablecoin": False},
    ]
    cats = mod.categorize_pools(pools)

    # Stablecoin bucket sorted by APY desc
    assert [p["project"] for p in cats["stablecoin"]] == ["Aave", "Maker"]

    # ETH bucket sorted by APY desc
    assert [p["project"] for p in cats["eth"]] == ["Rocket", "Lido"]

    # BTC bucket
    assert [p["project"] for p in cats["btc"]] == ["Babylon"]

    # Overall sorted by TVL desc
    assert [p["project"] for p in cats["overall"]][:2] == ["Maker", "Lido"]


def test_categorize_pools_respects_limits():
    mod = importlib.import_module("collect_defi_yields")
    # Build 30 stablecoin pools and verify TOP_STABLECOIN_LIMIT (default 10) applies
    pools = [
        {"tvlUsd": 1_000_000 * (i + 1), "apy": float(i + 1),
         "symbol": "USDC", "project": f"P{i}", "stablecoin": True}
        for i in range(30)
    ]
    cats = mod.categorize_pools(pools)
    assert len(cats["stablecoin"]) == mod.TOP_STABLECOIN_LIMIT
    # Top entry should be the highest APY (i=29, apy=30.0)
    assert cats["stablecoin"][0]["project"] == "P29"


# ---------------------------------------------------------------------------
# build_post_content integration
# ---------------------------------------------------------------------------


def _sample_categories() -> dict:
    """Reusable sample with non-empty stablecoin/eth/btc/overall buckets."""
    return {
        "stablecoin": [
            {"project": "Aave",  "chain": "Ethereum", "symbol": "USDC",
             "apy": 5.5, "tvlUsd": 50_000_000, "stablecoin": True},
        ],
        "eth": [
            {"project": "Lido",  "chain": "Ethereum", "symbol": "WETH",
             "apy": 3.5, "tvlUsd": 30_000_000},
        ],
        "btc": [
            {"project": "Babylon", "chain": "Bitcoin", "symbol": "WBTC",
             "apy": 2.0, "tvlUsd": 10_000_000},
        ],
        "overall": [
            {"project": "Aave", "chain": "Ethereum", "symbol": "USDC",
             "apy": 5.5, "tvlUsd": 50_000_000},
            {"project": "Lido", "chain": "Ethereum", "symbol": "WETH",
             "apy": 3.5, "tvlUsd": 30_000_000},
        ],
    }


def test_build_post_content_renders_all_sections():
    mod = importlib.import_module("collect_defi_yields")
    cats = _sample_categories()
    all_pools = cats["overall"]
    now = datetime(2026, 5, 26, 9, 10, tzinfo=UTC)

    content = mod.build_post_content(cats, all_pools, "2026-05-26", now)

    # All 4 section headings present
    assert "## 스테이블코인 수익률 TOP" in content
    assert "## ETH 수익률 TOP" in content
    assert "## BTC 수익률 TOP" in content
    assert "## 전체 TOP" in content

    # Alert-box callout (post_html.alert_box) emitted exactly once
    assert content.count('class="alert-box alert-info"') == 1
    assert "DeFi 수익률 요약" in content

    # Footer + disclaimer
    assert 'class="wm-footer-meta"' in content
    assert "투자 조언이 아닙니다" in content


def test_build_post_content_lead_includes_headline_and_count():
    """post-summary regression: first paragraph must include count + top APY project.

    Synced with check_post_summary.py — empty/pure-count leads would fail CI.
    """
    mod = importlib.import_module("collect_defi_yields")
    cats = _sample_categories()
    all_pools = cats["overall"]
    now = datetime(2026, 5, 26, 9, 10, tzinfo=UTC)

    content = mod.build_post_content(cats, all_pools, "2026-05-26", now)
    lead = content.split("\n", 1)[0]

    assert "2026-05-26" in lead
    assert "Aave" in lead  # top APY project surfaced in lead
    assert "%" in lead


def test_build_post_content_briefing_items_unique():
    """Briefing alert-box must not contain duplicate bullet entries."""
    mod = importlib.import_module("collect_defi_yields")
    cats = _sample_categories()
    all_pools = cats["overall"]
    now = datetime(2026, 5, 26, 9, 10, tzinfo=UTC)

    content = mod.build_post_content(cats, all_pools, "2026-05-26", now)

    # Extract the alert-box block
    start = content.find('class="alert-box alert-info"')
    end = content.find("</div>", start)
    block = content[start:end]

    # Each label must appear exactly once in the briefing
    for label in ("총 풀 수", "평균 APY", "최고 APY 프로토콜", "스테이블코인 TOP"):
        assert block.count(label) == 1, f"label '{label}' duplicated in briefing"


def test_build_post_content_handles_empty_categories():
    mod = importlib.import_module("collect_defi_yields")
    empty_cats = {"stablecoin": [], "eth": [], "btc": [], "overall": []}
    now = datetime(2026, 5, 26, 9, 10, tzinfo=UTC)

    content = mod.build_post_content(empty_cats, [], "2026-05-26", now)

    # Empty buckets emit fallback text, not crash
    assert "스테이블코인 풀 데이터를 불러오지 못했습니다" in content
    assert "ETH 풀 데이터를 불러오지 못했습니다" in content
    assert "BTC 풀 데이터를 불러오지 못했습니다" in content
    # No alert-box when there are no briefing stats? Actually alert_box still
    # emits the 3 fixed bullets (count=0, avg=0, max=Unknown) — verify single
    # callout still renders (covers `total_pools > 0` zero-division guard).
    assert content.count('class="alert-box') == 1


def test_build_post_content_skips_stablecoin_bullet_when_empty():
    """When stablecoin bucket is empty, briefing must omit the stablecoin bullet."""
    mod = importlib.import_module("collect_defi_yields")
    cats = _sample_categories()
    cats["stablecoin"] = []
    now = datetime(2026, 5, 26, 9, 10, tzinfo=UTC)

    content = mod.build_post_content(cats, cats["overall"], "2026-05-26", now)

    # Briefing should NOT include the stablecoin-specific bullet
    start = content.find('class="alert-box alert-info"')
    end = content.find("</div>", start)
    block = content[start:end]
    assert "스테이블코인 TOP" not in block


def test_build_pool_table_returns_markdown_table():
    mod = importlib.import_module("collect_defi_yields")
    pools = [
        {"project": "Aave", "chain": "Ethereum", "symbol": "USDC",
         "apy": 5.5, "tvlUsd": 50_000_000},
    ]
    table = mod._build_pool_table(pools)
    assert "Aave" in table
    assert "Ethereum" in table
    assert "USDC" in table
    assert "5.50%" in table
    # Project link to DeFi Llama
    assert "defillama.com/yields?project=aave" in table


# ---------------------------------------------------------------------------
# Network-mocked tests
# ---------------------------------------------------------------------------


def test_fetch_pools_envelope_dict_with_data_key():
    mod = importlib.import_module("collect_defi_yields")
    payload = {
        "status": "success",
        "data": [
            {"pool": "p1", "tvlUsd": 1e7, "apy": 5.0},
            {"pool": "p2", "tvlUsd": 2e7, "apy": 3.0},
        ],
    }
    mock_resp = MagicMock()
    mock_resp.json.return_value = payload

    with patch("collect_defi_yields.request_with_retry", return_value=mock_resp):
        result = mod.fetch_pools()

    assert len(result) == 2
    assert {p["pool"] for p in result} == {"p1", "p2"}


def test_fetch_pools_envelope_bare_list():
    mod = importlib.import_module("collect_defi_yields")
    payload = [{"pool": "p1", "tvlUsd": 1e7, "apy": 5.0}]
    mock_resp = MagicMock()
    mock_resp.json.return_value = payload

    with patch("collect_defi_yields.request_with_retry", return_value=mock_resp):
        result = mod.fetch_pools()

    assert result == payload


def test_fetch_pools_envelope_unexpected_shape():
    mod = importlib.import_module("collect_defi_yields")
    mock_resp = MagicMock()
    mock_resp.json.return_value = "not-a-dict-or-list"

    with patch("collect_defi_yields.request_with_retry", return_value=mock_resp):
        result = mod.fetch_pools()

    assert result == []


def test_fetch_pools_returns_empty_on_request_error():
    mod = importlib.import_module("collect_defi_yields")
    import requests

    with patch(
        "collect_defi_yields.request_with_retry",
        side_effect=requests.exceptions.ConnectionError("offline"),
    ):
        result = mod.fetch_pools()
    assert result == []


def test_fetch_pools_returns_empty_on_parse_error():
    mod = importlib.import_module("collect_defi_yields")
    mock_resp = MagicMock()
    mock_resp.json.side_effect = ValueError("bad json")

    with patch("collect_defi_yields.request_with_retry", return_value=mock_resp):
        result = mod.fetch_pools()
    assert result == []
