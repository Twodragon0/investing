"""Blockchain network metrics API client.

Fetches on-chain data from Blockchain.com (BTC) and Etherscan V2 (ETH).
Used exclusively by ``collect_blockchain.py``.

Environment variables:
    ETHERSCAN_API_KEY: Optional Etherscan free-tier API key.
"""

import logging
import time
from typing import Any, Dict, List

from common.config import REQUEST_TIMEOUT, get_env, get_verify_ssl
from common.utils import request_with_retry

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# BTC — Blockchain.com Public API (no auth required)
# ---------------------------------------------------------------------------

_BTC_STATS_URL = "https://api.blockchain.info/stats"
_BTC_MEMPOOL_URL = "https://api.blockchain.info/charts/mempool-count?timespan=1days&format=json"


def fetch_btc_stats() -> Dict[str, Any]:
    """Fetch Bitcoin network statistics from Blockchain.com.

    Returns dict with keys: hash_rate, difficulty, n_tx, block_time,
    blocks_total, mempool_size. Empty dict on failure.
    """
    try:
        resp = request_with_retry(
            _BTC_STATS_URL,
            timeout=REQUEST_TIMEOUT,
            verify_ssl=get_verify_ssl(),
        )
        data = resp.json()

        # Hash rate: Blockchain.com returns GH/s -> convert to EH/s
        hash_rate_ghs = data.get("hash_rate", 0)
        hash_rate_ehs = hash_rate_ghs / 1e9 if hash_rate_ghs else 0

        result = {
            "hash_rate_ehs": round(hash_rate_ehs, 1),
            "difficulty": data.get("difficulty", 0),
            "n_tx": data.get("n_tx", 0),
            "block_time_min": round(data.get("minutes_between_blocks", 0), 1),
            "blocks_total": data.get("n_blocks_total", 0),
            "market_price_usd": data.get("market_price_usd", 0),
            "trade_volume_usd": data.get("trade_volume_usd", 0),
        }

        # Try mempool size
        try:
            mempool_resp = request_with_retry(
                _BTC_MEMPOOL_URL,
                timeout=REQUEST_TIMEOUT,
            )
            mempool_data = mempool_resp.json()
            values = mempool_data.get("values", [])
            if values:
                result["mempool_size"] = int(values[-1].get("y", 0))
        except Exception:
            result["mempool_size"] = 0

        logger.info(
            "BTC stats: hash_rate=%.1f EH/s, difficulty=%s, tx=%d",
            result["hash_rate_ehs"],
            f"{result['difficulty']:.2e}",
            result["n_tx"],
        )
        return result

    except Exception as e:
        logger.warning("BTC stats fetch failed: %s", e)
        return {}


# ---------------------------------------------------------------------------
# ETH — Etherscan V2 API (optional API key)
# ---------------------------------------------------------------------------

_ETHERSCAN_V2_BASE = "https://api.etherscan.io/v2/api"


def _etherscan_get(module: str, action: str, **params: Any) -> Dict[str, Any]:
    """Make Etherscan V2 API call with optional API key."""
    api_key = get_env("ETHERSCAN_API_KEY")
    query: Dict[str, Any] = {
        "chainid": 1,
        "module": module,
        "action": action,
    }
    if api_key:
        query["apikey"] = api_key
    query.update(params)

    resp = request_with_retry(
        _ETHERSCAN_V2_BASE,
        params=query,
        timeout=REQUEST_TIMEOUT,
    )
    data = resp.json()
    if data.get("status") != "1":
        logger.debug("Etherscan API error: %s", data.get("message", "unknown"))
        return {}
    return data


def fetch_eth_stats() -> Dict[str, Any]:
    """Fetch Ethereum network statistics from Etherscan V2.

    Returns dict with keys: gas_safe, gas_propose, gas_fast,
    eth_supply, eth_price. Empty dict on failure.
    """
    result: Dict[str, Any] = {}

    try:
        # Gas prices
        gas_data = _etherscan_get("gastracker", "gasoracle")
        if gas_data:
            gas_result = gas_data.get("result", {})
            result["gas_safe"] = gas_result.get("SafeGasPrice", "0")
            result["gas_propose"] = gas_result.get("ProposeGasPrice", "0")
            result["gas_fast"] = gas_result.get("FastGasPrice", "0")

        time.sleep(0.3)  # Rate limit respect

        # ETH supply
        supply_data = _etherscan_get("stats", "ethsupply")
        if supply_data:
            supply_wei = int(supply_data.get("result", "0"))
            result["eth_supply"] = round(supply_wei / 1e18, 2) if supply_wei else 0

        time.sleep(0.3)

        # ETH price
        price_data = _etherscan_get("stats", "ethprice")
        if price_data:
            price_result = price_data.get("result", {})
            result["eth_price_usd"] = float(price_result.get("ethusd", "0"))
            result["eth_price_btc"] = float(price_result.get("ethbtc", "0"))

        if result:
            logger.info(
                "ETH stats: gas=%s/%s/%s Gwei, supply=%.0fM ETH",
                result.get("gas_safe", "?"),
                result.get("gas_propose", "?"),
                result.get("gas_fast", "?"),
                result.get("eth_supply", 0) / 1e6,
            )

        return result

    except Exception as e:
        logger.warning("ETH stats fetch failed: %s", e)
        return {}


# ---------------------------------------------------------------------------
# L2 — L2Beat Public API (no auth, Phase 2)
# ---------------------------------------------------------------------------

_L2BEAT_TVL_URL = "https://l2beat.com/api/scaling/summary"


def fetch_l2_summary() -> List[Dict[str, Any]]:
    """Fetch L2 scaling summary from L2Beat.

    Returns list of top L2 projects with TVL and stage info.
    Empty list on failure. (Phase 2 - basic implementation)
    """
    try:
        resp = request_with_retry(
            _L2BEAT_TVL_URL,
            timeout=REQUEST_TIMEOUT,
            verify_ssl=get_verify_ssl(),
        )
        data = resp.json()

        projects = data.get("data", {}).get("projects", [])
        if not projects:
            logger.info("L2Beat: no project data available")
            return []

        # Extract top 10 by TVL
        results = []
        for proj in projects[:10]:
            results.append(
                {
                    "name": proj.get("name", ""),
                    "slug": proj.get("slug", ""),
                    "tvl": proj.get("tvl", {}).get("value", 0),
                    "stage": proj.get("stage", ""),
                }
            )

        logger.info("L2Beat: fetched %d L2 projects", len(results))
        return results

    except Exception as e:
        logger.warning("L2Beat fetch failed: %s", e)
        return []


# ---------------------------------------------------------------------------
# Network Upgrade News — RSS feeds (Phase 3)
# ---------------------------------------------------------------------------

_UPGRADE_RSS_FEEDS: List[Dict[str, str]] = [
    {
        "url": "https://blog.ethereum.org/feed.xml",
        "name": "Ethereum Blog",
        "tags": "ethereum,upgrade",
    },
    {
        "url": "https://github.com/bitcoin/bitcoin/releases.atom",
        "name": "Bitcoin Core Releases",
        "tags": "bitcoin,upgrade",
    },
]


def fetch_upgrade_news() -> List[Dict[str, Any]]:
    """Fetch blockchain network upgrade news from RSS feeds.

    Returns list of news items with title, link, source, published date.
    Empty list on failure.
    """
    try:
        from common.rss_fetcher import fetch_rss_feeds_concurrent

        items = fetch_rss_feeds_concurrent(_UPGRADE_RSS_FEEDS)
        # Keep only recent items (title must exist)
        filtered = [item for item in items if item.get("title", "").strip()]
        logger.info("Upgrade news: fetched %d items from %d feeds", len(filtered), len(_UPGRADE_RSS_FEEDS))
        return filtered[:10]  # Limit to 10 most recent
    except Exception as e:
        logger.warning("Upgrade news fetch failed: %s", e)
        return []
