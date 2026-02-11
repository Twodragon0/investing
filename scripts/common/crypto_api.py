"""Shared CoinGecko and Fear & Greed Index API helpers."""

import logging
import requests
from typing import Dict, Any, List
from .config import get_ssl_verify

logger = logging.getLogger(__name__)

VERIFY_SSL = get_ssl_verify()
REQUEST_TIMEOUT = 20
USER_AGENT = "Mozilla/5.0 (compatible; InvestingDragon/1.0)"


def fetch_coingecko_top_coins(limit: int = 30) -> List[Dict[str, Any]]:
    """Fetch top coins by market cap from CoinGecko."""
    try:
        url = "https://api.coingecko.com/api/v3/coins/markets"
        params = {
            "vs_currency": "usd",
            "order": "market_cap_desc",
            "per_page": limit,
            "page": 1,
            "sparkline": "false",
            "price_change_percentage": "1h,24h,7d",
        }
        resp = requests.get(
            url, params=params, timeout=REQUEST_TIMEOUT, verify=VERIFY_SSL,
            headers={"User-Agent": USER_AGENT},
        )
        resp.raise_for_status()
        data = resp.json()
        logger.info("CoinGecko: fetched %d top coins", len(data))
        return data
    except requests.exceptions.RequestException as e:
        logger.warning("CoinGecko top coins fetch failed: %s", e)
        return []


def fetch_coingecko_trending() -> List[Dict[str, Any]]:
    """Fetch trending coins from CoinGecko."""
    try:
        url = "https://api.coingecko.com/api/v3/search/trending"
        resp = requests.get(
            url, timeout=REQUEST_TIMEOUT, verify=VERIFY_SSL,
            headers={"User-Agent": USER_AGENT},
        )
        resp.raise_for_status()
        coins = resp.json().get("coins", [])
        logger.info("CoinGecko: fetched %d trending coins", len(coins))
        return coins
    except requests.exceptions.RequestException as e:
        logger.warning("CoinGecko trending fetch failed: %s", e)
        return []


def fetch_coingecko_global() -> Dict[str, Any]:
    """Fetch global crypto market data."""
    try:
        url = "https://api.coingecko.com/api/v3/global"
        resp = requests.get(
            url, timeout=REQUEST_TIMEOUT, verify=VERIFY_SSL,
            headers={"User-Agent": USER_AGENT},
        )
        resp.raise_for_status()
        data = resp.json().get("data", {})
        logger.info("CoinGecko: fetched global market data")
        return data
    except requests.exceptions.RequestException as e:
        logger.warning("CoinGecko global fetch failed: %s", e)
        return {}


def fetch_fear_greed_index(history_days: int = 1) -> Dict[str, Any]:
    """Fetch Crypto Fear & Greed Index.

    Args:
        history_days: Number of days of history to fetch (1 for current only,
                      7 for weekly trend including previous day comparison).
    """
    try:
        url = f"https://api.alternative.me/fng/?limit={history_days}&format=json"
        resp = requests.get(url, timeout=REQUEST_TIMEOUT, verify=VERIFY_SSL)
        resp.raise_for_status()
        data = resp.json()
        entries = data.get("data", [])
        if entries:
            current = entries[0]
            prev = entries[1] if len(entries) > 1 else {}
            result = {
                "value": int(current.get("value", 0)),
                "classification": current.get("value_classification", "N/A"),
            }
            if prev:
                result["prev_value"] = int(prev.get("value", 0))
                result["prev_classification"] = prev.get("value_classification", "")
            return result
        return {}
    except requests.exceptions.RequestException as e:
        logger.warning("Fear & Greed index fetch failed: %s", e)
        return {}
