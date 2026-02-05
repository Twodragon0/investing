#!/usr/bin/env python3
"""Generate daily market summary post combining crypto, stock, and macro data.

Sources:
- CoinGecko/Upbit public API (BTC, ETH prices)
- Alpha Vantage (SPY, QQQ, COIN, MSTR)
- yfinance (KOSPI, KOSDAQ)
- FRED (CPI, rates, treasury, VIX)
- Fear & Greed Index (alternative.me)
"""

import sys
import os
import logging
import requests
import certifi
from datetime import datetime, timezone
from typing import Dict, Any, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common.config import get_env, setup_logging
from common.post_generator import PostGenerator
from common.utils import sanitize_string

logger = setup_logging("generate_market_summary")

VERIFY_SSL = certifi.where()
REQUEST_TIMEOUT = 15


def fetch_crypto_prices() -> Dict[str, Any]:
    """Fetch major crypto prices from CoinGecko public API."""
    try:
        url = "https://api.coingecko.com/api/v3/simple/price"
        params = {
            "ids": "bitcoin,ethereum,solana,ripple,cardano",
            "vs_currencies": "usd,krw",
            "include_24hr_change": "true",
            "include_market_cap": "true",
        }
        resp = requests.get(url, params=params, timeout=REQUEST_TIMEOUT, verify=VERIFY_SSL)
        resp.raise_for_status()
        data = resp.json()
        logger.info("CoinGecko: fetched crypto prices")
        return data
    except requests.exceptions.RequestException as e:
        logger.warning("CoinGecko fetch failed: %s", e)
        return {}


def fetch_fear_greed_index() -> Dict[str, Any]:
    """Fetch Crypto Fear & Greed Index."""
    try:
        url = "https://api.alternative.me/fng/?limit=1&format=json"
        resp = requests.get(url, timeout=REQUEST_TIMEOUT, verify=VERIFY_SSL)
        resp.raise_for_status()
        data = resp.json()
        if "data" in data and data["data"]:
            entry = data["data"][0]
            return {
                "value": int(entry.get("value", 0)),
                "classification": entry.get("value_classification", "N/A"),
            }
        return {}
    except requests.exceptions.RequestException as e:
        logger.warning("Fear & Greed index fetch failed: %s", e)
        return {}


def fetch_us_market_data(api_key: str) -> Dict[str, Dict[str, str]]:
    """Fetch US market data from Alpha Vantage."""
    if not api_key:
        logger.info("Alpha Vantage API key not set, skipping")
        return {}

    symbols = {"SPY": "S&P 500 ETF", "QQQ": "NASDAQ 100 ETF", "COIN": "Coinbase", "MSTR": "MicroStrategy"}
    results = {}

    for symbol, name in symbols.items():
        try:
            url = "https://www.alphavantage.co/query"
            params = {"function": "GLOBAL_QUOTE", "symbol": symbol, "apikey": api_key}
            resp = requests.get(url, params=params, timeout=REQUEST_TIMEOUT, verify=VERIFY_SSL)
            resp.raise_for_status()
            data = resp.json()
            quote = data.get("Global Quote", {})
            if quote:
                results[symbol] = {
                    "name": name,
                    "price": quote.get("05. price", "N/A"),
                    "change": quote.get("09. change", "N/A"),
                    "change_pct": quote.get("10. change percent", "N/A"),
                    "volume": quote.get("06. volume", "N/A"),
                }
            import time
            time.sleep(1)
        except requests.exceptions.RequestException as e:
            logger.warning("Alpha Vantage %s fetch failed: %s", symbol, e)

    logger.info("Alpha Vantage: fetched %d quotes", len(results))
    return results


def fetch_korean_market() -> Dict[str, Dict[str, str]]:
    """Fetch Korean market data using yfinance."""
    results = {}
    try:
        import yfinance as yf

        indices = {"^KS11": "KOSPI", "^KQ11": "KOSDAQ"}
        for symbol, name in indices.items():
            try:
                ticker = yf.Ticker(symbol)
                info = ticker.fast_info
                price = getattr(info, "last_price", None)
                prev_close = getattr(info, "previous_close", None)

                if price and prev_close:
                    change = price - prev_close
                    change_pct = (change / prev_close) * 100
                    results[name] = {
                        "price": f"{price:,.2f}",
                        "change": f"{change:+,.2f}",
                        "change_pct": f"{change_pct:+.2f}%",
                    }
            except Exception as e:
                logger.warning("yfinance %s fetch failed: %s", symbol, e)

        logger.info("Korean market: fetched %d indices", len(results))
    except ImportError:
        logger.warning("yfinance not installed, skipping Korean market data")

    return results


def fetch_fred_indicators(api_key: str) -> Dict[str, Dict[str, Any]]:
    """Fetch key macro indicators from FRED."""
    if not api_key:
        logger.info("FRED API key not set, skipping")
        return {}

    indicators = {
        "FED_RATE": "FEDFUNDS",
        "10Y_YIELD": "DGS10",
        "2Y_YIELD": "DGS2",
        "VIX": "VIXCLS",
        "CPI": "CPIAUCSL",
    }
    results = {}

    from datetime import timedelta

    for name, series_id in indicators.items():
        try:
            params = {
                "series_id": series_id,
                "api_key": api_key,
                "observation_start": (datetime.now(timezone.utc) - timedelta(days=60)).strftime("%Y-%m-%d"),
                "observation_end": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "file_type": "json",
                "sort_order": "desc",
                "limit": "2",
            }
            resp = requests.get(
                "https://api.stlouisfed.org/fred/series/observations",
                params=params, timeout=REQUEST_TIMEOUT, verify=VERIFY_SSL,
            )
            resp.raise_for_status()
            data = resp.json()
            obs = data.get("observations", [])

            if obs and obs[0].get("value", ".") != ".":
                current = float(obs[0]["value"])
                previous = float(obs[1]["value"]) if len(obs) > 1 and obs[1].get("value", ".") != "." else None
                change = (current - previous) if previous else None
                results[name] = {
                    "value": current,
                    "date": obs[0]["date"],
                    "change": change,
                }
        except (requests.exceptions.RequestException, ValueError, KeyError) as e:
            logger.warning("FRED %s fetch failed: %s", name, e)

    logger.info("FRED: fetched %d indicators", len(results))
    return results


def format_crypto_section(prices: Dict[str, Any]) -> str:
    """Format crypto prices into markdown."""
    if not prices:
        return "*데이터를 가져올 수 없습니다.*"

    lines = ["| 코인 | USD 가격 | 24h 변동 | KRW 가격 |", "|------|---------|---------|---------|"]
    name_map = {"bitcoin": "BTC", "ethereum": "ETH", "solana": "SOL", "ripple": "XRP", "cardano": "ADA"}

    for coin_id, display in name_map.items():
        if coin_id in prices:
            d = prices[coin_id]
            usd = f"${d.get('usd', 0):,.2f}"
            change = d.get("usd_24h_change", 0)
            change_str = f"{change:+.2f}%" if change else "N/A"
            krw = f"₩{d.get('krw', 0):,.0f}"
            lines.append(f"| {display} | {usd} | {change_str} | {krw} |")

    return "\n".join(lines)


def format_fear_greed(data: Dict[str, Any]) -> str:
    """Format Fear & Greed index."""
    if not data:
        return "*데이터를 가져올 수 없습니다.*"

    value = data.get("value", 0)
    classification = data.get("classification", "N/A")
    bar = "█" * (value // 5) + "░" * (20 - value // 5)
    return f"**{value}/100** - {classification}\n\n`[{bar}]`"


def format_us_market(data: Dict[str, Dict[str, str]]) -> str:
    """Format US market data."""
    if not data:
        return "*데이터를 가져올 수 없습니다.*"

    lines = ["| 종목 | 가격 | 변동 | 변동률 |", "|------|------|------|--------|"]
    for symbol, info in data.items():
        lines.append(f"| {info['name']} ({symbol}) | ${info['price']} | {info['change']} | {info['change_pct']} |")
    return "\n".join(lines)


def format_korean_market(data: Dict[str, Dict[str, str]]) -> str:
    """Format Korean market data."""
    if not data:
        return "*데이터를 가져올 수 없습니다.*"

    lines = ["| 지수 | 가격 | 변동 | 변동률 |", "|------|------|------|--------|"]
    for name, info in data.items():
        lines.append(f"| {name} | {info['price']} | {info['change']} | {info['change_pct']} |")
    return "\n".join(lines)


def format_fred_section(data: Dict[str, Dict[str, Any]]) -> str:
    """Format FRED macro indicators."""
    if not data:
        return "*데이터를 가져올 수 없습니다.*"

    labels = {"FED_RATE": "연방기금금리", "10Y_YIELD": "10년 국채 수익률", "2Y_YIELD": "2년 국채 수익률", "VIX": "VIX 변동성 지수", "CPI": "소비자물가지수 (CPI)"}
    lines = ["| 지표 | 현재 값 | 변동 |", "|------|---------|------|"]

    for key, label in labels.items():
        if key in data:
            d = data[key]
            value = f"{d['value']:.2f}"
            change = f"{d['change']:+.2f}" if d.get("change") is not None else "N/A"
            lines.append(f"| {label} | {value} | {change} |")

    return "\n".join(lines)


def main():
    """Generate daily market summary."""
    logger.info("=== Generating daily market summary ===")

    alpha_vantage_key = get_env("ALPHA_VANTAGE_API_KEY")
    fred_key = get_env("FRED_API_KEY")

    # Fetch all data
    crypto_prices = fetch_crypto_prices()
    fear_greed = fetch_fear_greed_index()
    us_market = fetch_us_market_data(alpha_vantage_key)
    kr_market = fetch_korean_market()
    fred_data = fetch_fred_indicators(fred_key)

    # Build summary sections
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    sections = {}

    sections["암호화폐 시장"] = format_crypto_section(crypto_prices)
    sections["공포/탐욕 지수 (Crypto Fear & Greed)"] = format_fear_greed(fear_greed)
    sections["미국 주식 시장"] = format_us_market(us_market)
    sections["한국 주식 시장"] = format_korean_market(kr_market)
    sections["매크로 경제 지표"] = format_fred_section(fred_data)

    # Generate post
    gen = PostGenerator("market-analysis")
    filepath = gen.create_summary_post(
        title=f"일일 시장 요약 - {today}",
        sections=sections,
        tags=["market-summary", "daily", "crypto", "stock", "macro"],
    )

    if filepath:
        logger.info("Created market summary: %s", filepath)
    else:
        logger.warning("Failed to create market summary post")

    logger.info("=== Market summary generation complete ===")


if __name__ == "__main__":
    main()
