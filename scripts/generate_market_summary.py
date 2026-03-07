#!/usr/bin/env python3
"""Generate daily market summary with high-quality analysis and auto-generated images.

Enhanced version with:
- CoinGecko/CoinMarketCap top coins, trending, global data
- Alpha Vantage US market data
- yfinance Korean market data
- FRED macro indicators
- Fear & Greed Index
- Auto-generated market visualization images (heatmap, gauge, top coins card)
- High-quality Korean market analysis summary
"""

import os
import re
import sys
import time
from collections import OrderedDict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common.config import (
    REQUEST_TIMEOUT,
    get_env,
    get_kst_timezone,
    get_ssl_verify,
    setup_logging,
)
from common.crypto_api import (
    fetch_coingecko_global,
    fetch_coingecko_top_coins,
    fetch_coingecko_trending,
    fetch_fear_greed_index,
)
from common.dedup import DedupEngine
from common.formatters import fmt_number as _fmt
from common.formatters import fmt_percent as _pct
from common.markdown_utils import markdown_link, markdown_table
from common.post_generator import PostGenerator
from common.utils import request_with_retry

logger = setup_logging("generate_market_summary")

VERIFY_SSL = get_ssl_verify()

STABLECOIN_SYMBOLS = {
    "usdt",
    "usdc",
    "dai",
    "busd",
    "tusd",
    "usdp",
    "gusd",
    "frax",
    "lusd",
    "usdd",
    "fdusd",
    "pyusd",
    "usds",
    "usde",
    "eusd",
    "crvusd",
    "gho",
    "susd",
    "eurs",
    "xaut",
    "paxg",
    "usd1",
}


def fetch_us_market_data(api_key: str) -> Dict[str, Dict[str, str]]:
    """Fetch US market data from Alpha Vantage + yfinance."""
    # Alpha Vantage: major indices only (3 calls to conserve daily quota)
    symbols_av = {
        "SPY": "S&P 500 ETF",
        "QQQ": "NASDAQ 100 ETF",
        "DIA": "다우존스 ETF",
    }
    # yfinance: crypto-related stocks (no API quota cost)
    symbols_yf = {
        "COIN": "Coinbase",
        "MSTR": "MicroStrategy",
        "IBIT": "BlackRock Bitcoin ETF",
    }
    results = {}

    # Alpha Vantage for major indices
    if api_key:
        for symbol, name in symbols_av.items():
            try:
                url = "https://www.alphavantage.co/query"
                params = {
                    "function": "GLOBAL_QUOTE",
                    "symbol": symbol,
                    "apikey": api_key,
                }
                resp = requests.get(url, params=params, timeout=REQUEST_TIMEOUT, verify=VERIFY_SSL)
                resp.raise_for_status()
                quote = resp.json().get("Global Quote", {})
                if quote and quote.get("05. price"):
                    results[symbol] = {
                        "name": name,
                        "price": quote.get("05. price", "N/A"),
                        "change": quote.get("09. change", "N/A"),
                        "change_pct": quote.get("10. change percent", "N/A"),
                        "volume": quote.get("06. volume", "N/A"),
                    }
                time.sleep(1)
            except requests.exceptions.RequestException as e:
                logger.warning("Alpha Vantage %s: %s", symbol, e)

    # yfinance fallback for AV symbols only
    if len(results) < len(symbols_av):
        logger.info(
            "Alpha Vantage incomplete (%d/%d), trying yfinance fallback",
            len(results),
            len(symbols_av),
        )
        try:
            import yfinance as yf

            yf_fallback = {
                "^GSPC": ("SPY", "S&P 500"),
                "^IXIC": ("QQQ", "NASDAQ"),
                "^DJI": ("DIA", "다우존스"),
                "^VIX": ("VIX", "VIX 변동성"),
            }
            for yf_sym, (key, name) in yf_fallback.items():
                if key in results:
                    continue
                try:
                    info = yf.Ticker(yf_sym).fast_info
                    price = getattr(info, "last_price", None)
                    prev = getattr(info, "previous_close", None)
                    if price and prev:
                        change = price - prev
                        change_pct = (change / prev) * 100
                        results[key] = {
                            "name": name,
                            "price": f"{price:,.2f}",
                            "change": f"{change:+,.2f}",
                            "change_pct": f"{change_pct:+.2f}%",
                            "volume": "N/A",
                        }
                except Exception as e:
                    logger.warning("yfinance US %s: %s", yf_sym, e)
        except ImportError:
            logger.warning("yfinance not installed for US market fallback")

    # yfinance for crypto-related stocks (always)
    try:
        import yfinance as yf

        for symbol, name in symbols_yf.items():
            try:
                info = yf.Ticker(symbol).fast_info
                price = getattr(info, "last_price", None)
                prev = getattr(info, "previous_close", None)
                if price and prev:
                    change = price - prev
                    change_pct = (change / prev) * 100
                    results[symbol] = {
                        "name": name,
                        "price": f"{price:,.2f}",
                        "change": f"{change:+,.2f}",
                        "change_pct": f"{change_pct:+.2f}%",
                        "volume": "N/A",
                    }
            except Exception as e:
                logger.warning("yfinance %s: %s", symbol, e)
    except ImportError:
        logger.warning("yfinance not installed for crypto stocks")

    return results


def fetch_korean_market() -> Dict[str, Dict[str, str]]:
    """Fetch Korean market data using yfinance (expanded)."""
    results = {}
    try:
        import yfinance as yf

        symbols = {
            "^KS11": "KOSPI",
            "^KQ11": "KOSDAQ",
            "KRW=X": "USD/KRW 환율",
        }
        for symbol, name in symbols.items():
            try:
                info = yf.Ticker(symbol).fast_info
                price = getattr(info, "last_price", None)
                prev = getattr(info, "previous_close", None)
                if price and prev:
                    change = price - prev
                    results[name] = {
                        "price": f"{price:,.2f}",
                        "change": f"{change:+,.2f}",
                        "change_pct": f"{(change / prev) * 100:+.2f}%",
                    }
            except Exception as e:
                logger.warning("yfinance %s: %s", symbol, e)
    except ImportError:
        logger.warning("yfinance not installed")
    return results


def fetch_commodity_data() -> Dict[str, Dict[str, str]]:
    """Fetch commodity and dollar index data using yfinance."""
    results = {}
    symbols = {
        "GC=F": "금 (Gold)",
        "CL=F": "원유 (WTI)",
        "NG=F": "천연가스",
        "DX-Y.NYB": "달러 인덱스 (DXY)",
    }
    try:
        import yfinance as yf

        for symbol, name in symbols.items():
            try:
                info = yf.Ticker(symbol).fast_info
                price = getattr(info, "last_price", None)
                prev = getattr(info, "previous_close", None)
                if price and prev:
                    change = price - prev
                    change_pct = (change / prev) * 100
                    results[name] = {
                        "price": f"{price:,.2f}",
                        "change": f"{change:+,.2f}",
                        "change_pct": f"{change_pct:+.2f}%",
                    }
            except Exception as e:
                logger.warning("yfinance commodity %s: %s", symbol, e)
    except ImportError:
        logger.warning("yfinance not installed for commodity data")
    return results


def format_commodity_data(data: Dict) -> str:
    """Format commodity/dollar index data as a markdown table."""
    if not data:
        return (
            "> 원자재/환율 데이터를 일시적으로 가져올 수 없습니다.\n\n"
            "**참고 링크:**\n"
            "- [Investing.com - 원자재](https://kr.investing.com/commodities/)\n"
            "- [Investing.com - 달러 인덱스](https://kr.investing.com/indices/usdollar)"
        )
    lines = [
        "| 원자재/지수 | 가격 | 변동 | 변동률 |",
        "|-------------|------|------|--------|",
    ]
    for name, info in data.items():
        try:
            pct = float(info["change_pct"].replace("%", "").replace("+", ""))
            icon = "🟢" if pct >= 0 else "🔴"
        except (ValueError, KeyError):
            icon = ""
        lines.append(f"| {name} | {info['price']} | {info['change']} | {icon} {info['change_pct']} |")
    return "\n".join(lines)


def fetch_fred_indicators(api_key: str) -> Dict[str, Dict[str, Any]]:
    """Fetch key macro indicators from FRED."""
    if not api_key:
        return {}

    indicators = {
        "FED_RATE": ("FEDFUNDS", "연방기금금리"),
        "10Y_YIELD": ("DGS10", "10년 국채 수익률"),
        "2Y_YIELD": ("DGS2", "2년 국채 수익률"),
        "VIX": ("VIXCLS", "VIX 변동성 지수"),
        "CPI": ("CPIAUCSL", "소비자물가지수"),
    }
    results = {}

    now = datetime.now(get_kst_timezone())

    for key, (series_id, label) in indicators.items():
        try:
            params = {
                "series_id": series_id,
                "api_key": api_key,
                "observation_start": (now - timedelta(days=60)).strftime("%Y-%m-%d"),
                "observation_end": now.strftime("%Y-%m-%d"),
                "file_type": "json",
                "sort_order": "desc",
                "limit": "2",
            }
            resp = request_with_retry(
                "https://api.stlouisfed.org/fred/series/observations",
                params=params,
                timeout=REQUEST_TIMEOUT,
                verify_ssl=VERIFY_SSL,
            )
            obs = resp.json().get("observations", [])
            if obs and obs[0].get("value", ".") != ".":
                current = float(obs[0]["value"])
                previous = float(obs[1]["value"]) if len(obs) > 1 and obs[1].get("value", ".") != "." else None
                results[key] = {
                    "label": label,
                    "value": current,
                    "date": obs[0]["date"],
                    "change": (current - previous) if previous else None,
                }
        except Exception as e:
            logger.warning("FRED %s: %s", key, e)

    return results


def calculate_yield_spread(fred_data: Dict) -> Dict[str, Any]:
    """Calculate 2Y-10Y yield spread from FRED data.

    Returns dict with spread value and inversion status.
    """
    result = {}
    y10 = fred_data.get("10Y_YIELD", {})
    y2 = fred_data.get("2Y_YIELD", {})
    if y10.get("value") is not None and y2.get("value") is not None:
        spread = y10["value"] - y2["value"]
        result = {
            "spread": spread,
            "y10": y10["value"],
            "y2": y2["value"],
            "inverted": spread < 0,
            "date": y10.get("date", ""),
        }
    return result


def fetch_sector_performance() -> Dict[str, Dict[str, Any]]:
    """Fetch S&P 500 sector ETF performance via yfinance."""
    sectors = {
        "XLK": "기술 (Technology)",
        "XLF": "금융 (Financials)",
        "XLE": "에너지 (Energy)",
        "XLV": "헬스케어 (Healthcare)",
        "XLI": "산업재 (Industrials)",
        "XLC": "통신 (Communication)",
        "XLP": "필수소비재 (Staples)",
        "XLY": "임의소비재 (Discretionary)",
        "XLU": "유틸리티 (Utilities)",
        "XLRE": "부동산 (Real Estate)",
        "XLB": "소재 (Materials)",
    }
    results = {}
    try:
        import yfinance as yf

        for symbol, name in sectors.items():
            try:
                info = yf.Ticker(symbol).fast_info
                price = getattr(info, "last_price", None)
                prev = getattr(info, "previous_close", None)
                if price and prev:
                    change = price - prev
                    change_pct = (change / prev) * 100
                    results[symbol] = {
                        "name": name,
                        "price": f"{price:,.2f}",
                        "change": f"{change:+,.2f}",
                        "change_pct": change_pct,
                    }
            except Exception as e:
                logger.warning("yfinance sector %s: %s", symbol, e)
    except ImportError:
        logger.warning("yfinance not installed for sector data")
    return results


def fetch_btc_etf_data() -> Dict[str, Any]:
    """Fetch Bitcoin ETF data (IBIT, FBTC, GBTC) + Google News."""
    etf_data = {}

    # Price data via yfinance
    etfs = {
        "IBIT": "BlackRock iShares Bitcoin Trust",
        "FBTC": "Fidelity Wise Origin Bitcoin Fund",
        "GBTC": "Grayscale Bitcoin Trust",
    }
    try:
        import yfinance as yf

        for symbol, name in etfs.items():
            try:
                info = yf.Ticker(symbol).fast_info
                price = getattr(info, "last_price", None)
                prev = getattr(info, "previous_close", None)
                if price and prev:
                    change = price - prev
                    change_pct = (change / prev) * 100
                    etf_data[symbol] = {
                        "name": name,
                        "price": f"{price:,.2f}",
                        "change": f"{change:+,.2f}",
                        "change_pct": f"{change_pct:+.2f}%",
                    }
            except Exception as e:
                logger.warning("yfinance BTC ETF %s: %s", symbol, e)
    except ImportError:
        logger.warning("yfinance not installed for BTC ETF data")

    # News via Google News RSS
    from common.rss_fetcher import fetch_rss_feeds_concurrent

    feeds = [
        (
            "https://news.google.com/rss/search?q=bitcoin+ETF+IBIT+FBTC+inflow+outflow&hl=en-US&gl=US&ceid=US:en",
            "BTC ETF News",
            ["btc-etf"],
            5,
        ),
        (
            "https://news.google.com/rss/search?q=비트코인+ETF+자금+유입+유출&hl=ko&gl=KR&ceid=KR:ko",
            "비트코인 ETF KR",
            ["btc-etf", "korean"],
            5,
        ),
    ]
    news_items = fetch_rss_feeds_concurrent(feeds)

    return {"etfs": etf_data, "news": news_items}


def fetch_whale_trades() -> list:
    """Fetch whale/large transfer news via Google News RSS."""
    from common.rss_fetcher import fetch_rss_feeds_concurrent

    feeds = [
        (
            "https://news.google.com/rss/search?q=whale+alert+bitcoin+transfer+large&hl=en-US&gl=US&ceid=US:en",
            "Whale Alert EN",
            ["whale", "bitcoin"],
            10,
        ),
        (
            "https://news.google.com/rss/search?q=비트코인+고래+대량+이체&hl=ko&gl=KR&ceid=KR:ko",
            "고래 이체 KR",
            ["whale", "korean"],
            5,
        ),
        (
            "https://news.google.com/rss/search?q=crypto+whale+large+transaction&hl=en-US&gl=US&ceid=US:en",
            "Crypto Whale",
            ["whale", "crypto"],
            5,
        ),
    ]
    return fetch_rss_feeds_concurrent(feeds)


def format_yield_spread(spread_data: Dict) -> str:
    """Format yield spread section."""
    if not spread_data:
        return "> 국채 수익률 스프레드 데이터를 가져올 수 없습니다."

    spread = spread_data["spread"]
    y10 = spread_data["y10"]
    y2 = spread_data["y2"]
    inverted = spread_data["inverted"]

    warning = ""
    if inverted:
        warning = "\n\n> **경고**: 수익률 곡선이 역전되었습니다. 역사적으로 이는 경기 침체의 선행 지표로 해석됩니다."

    table = markdown_table(
        ["지표", "값"],
        [
            ["10년 국채 수익률", f"{y10:.2f}%"],
            ["2년 국채 수익률", f"{y2:.2f}%"],
            [
                "**스프레드 (10Y-2Y)**",
                f"**{spread:+.2f}%** {'🔴 역전' if inverted else '🟢 정상'}",
            ],
        ],
    )
    return f"{table}{warning}"


def format_sector_performance(data: Dict) -> str:
    """Format sector performance as a table sorted by change."""
    if not data:
        return (
            "> 섹터 퍼포먼스 데이터를 일시적으로 가져올 수 없습니다.\n\n"
            "**참고 링크:**\n"
            "- [Finviz - S&P 500 Sectors](https://finviz.com/groups.ashx)"
        )

    sorted_sectors = sorted(data.items(), key=lambda x: x[1].get("change_pct", 0), reverse=True)

    rows = []
    for symbol, info in sorted_sectors:
        pct = info.get("change_pct", 0)
        icon = "🟢" if pct >= 0 else "🔴"
        rows.append(
            [
                info["name"],
                symbol,
                f"${info['price']}",
                info["change"],
                f"{icon} {pct:+.2f}%",
            ]
        )

    return markdown_table(["섹터", "ETF", "가격", "변동", "변동률"], rows)


def format_btc_etf(data: Dict) -> str:
    """Format Bitcoin ETF section."""
    etfs = data.get("etfs", {})
    news = data.get("news", [])

    parts = []
    if etfs:
        rows = []
        for symbol, info in etfs.items():
            try:
                pct = float(info["change_pct"].replace("%", "").replace("+", ""))
                icon = "🟢" if pct >= 0 else "🔴"
            except (ValueError, KeyError):
                icon = ""
            rows.append(
                [
                    f"**{info['name']}** ({symbol})",
                    f"${info['price']}",
                    info["change"],
                    f"{icon} {info['change_pct']}",
                ]
            )
        parts.append(markdown_table(["ETF", "가격", "변동", "변동률"], rows))
    else:
        parts.append("> 비트코인 ETF 데이터를 가져올 수 없습니다.")

    if news:
        parts.append("\n**주요 ETF 뉴스:**\n")
        for i, item in enumerate(news[:5], 1):
            title = item.get("title", "")
            link = item.get("link", "")
            if link:
                parts.append(f"{i}. [{title}]({link})")
            else:
                parts.append(f"{i}. {title}")

    return "\n".join(parts) if parts else "> 비트코인 ETF 데이터를 가져올 수 없습니다."


def format_whale_trades(items: list) -> str:
    """Format whale trades news section."""
    if not items:
        return "> 고래 거래 데이터를 가져올 수 없습니다.\n\n**참고 링크:**\n- [Whale Alert](https://whale-alert.io/)"

    # URL 기반 중복 제거
    seen_urls = set()
    unique_items = []
    for item in items:
        url = item.get("link", "")
        if url and url in seen_urls:
            continue
        if url:
            seen_urls.add(url)
        unique_items.append(item)

    rows = []
    for i, item in enumerate(unique_items[:10], 1):
        title = item.get("title", "")
        source = item.get("source", "unknown")
        link = item.get("link", "")
        if link:
            rows.append([i, markdown_link(title, link), source])
        else:
            rows.append([i, title, source])

    return markdown_table(["#", "제목", "출처"], rows)


def format_global_overview(global_data: Dict, fear_greed: Dict) -> str:
    """Format global market overview section."""
    parts = []

    if global_data:
        total_mcap = global_data.get("total_market_cap", {}).get("usd", 0)
        total_vol = global_data.get("total_volume", {}).get("usd", 0)
        btc_dom = global_data.get("market_cap_percentage", {}).get("btc", 0)
        eth_dom = global_data.get("market_cap_percentage", {}).get("eth", 0)
        mcap_change = global_data.get("market_cap_change_percentage_24h_usd", 0)
        active = global_data.get("active_cryptocurrencies", 0)

        parts.append(
            markdown_table(
                ["지표", "값"],
                [
                    ["총 시가총액", f"{_fmt(total_mcap)} ({_pct(mcap_change)})"],
                    ["24시간 거래량", _fmt(total_vol)],
                    ["BTC 도미넌스", f"{btc_dom:.1f}%"],
                    ["ETH 도미넌스", f"{eth_dom:.1f}%"],
                    ["활성 코인 수", f"{active:,}개"],
                ],
            )
        )

    if fear_greed:
        val = fear_greed["value"]
        cls = fear_greed["classification"]
        bar = "█" * (val // 5) + "░" * (20 - val // 5)
        prev_val = fear_greed.get("prev_value")
        prev_str = f" (전일: {prev_val})" if prev_val else ""
        parts.append(f"\n**공포/탐욕 지수: {val}/100** — {cls}{prev_str}")
        parts.append(f"`[{bar}]`")

    return (
        "\n".join(parts)
        if parts
        else (
            "> 글로벌 암호화폐 시장 데이터를 일시적으로 가져올 수 없습니다.\n\n"
            "**참고 링크:**\n"
            "- [CoinGecko - 글로벌 시장](https://www.coingecko.com/)\n"
            "- [CoinMarketCap - 시장 현황](https://coinmarketcap.com/)"
        )
    )


def format_top_coins(coins: List[Dict]) -> str:
    """Format top coins table."""
    if not coins:
        return (
            "> 코인 데이터를 일시적으로 가져올 수 없습니다.\n\n"
            "**참고 링크:**\n"
            "- [CoinGecko - Top 100](https://www.coingecko.com/)\n"
            "- [CoinMarketCap - Rankings](https://coinmarketcap.com/)"
        )

    rows = []
    for i, c in enumerate(coins[:20], 1):
        sym = c.get("symbol", "").upper()
        name = c.get("name", "")
        price = c.get("current_price", 0) or 0
        ch24 = c.get("price_change_percentage_24h", 0) or 0
        ch7d = c.get("price_change_percentage_7d_in_currency", 0) or 0
        mcap = c.get("market_cap", 0) or 0

        p = f"${price:,.2f}" if price >= 1 else f"${price:,.6f}"
        rows.append([i, f"**{name}** ({sym})", p, _pct(ch24), _pct(ch7d), _fmt(mcap)])

    return markdown_table(["#", "코인", "가격 (USD)", "24h", "7d", "시가총액"], rows)


def format_trending(coins: List[Dict]) -> str:
    """Format trending coins."""
    if not coins:
        return "*트렌딩 데이터를 가져올 수 없습니다.*"

    lines = ["**실시간 트렌딩 코인:**\n"]
    for i, cd in enumerate(coins[:7], 1):
        item = cd.get("item", {})
        name = item.get("name", "")
        sym = item.get("symbol", "")
        rank = item.get("market_cap_rank", "N/A")
        lines.append(f"{i}. **{name}** ({sym}) — 시총 순위 #{rank}")
    return "\n".join(lines)


def format_gainers_losers(coins: List[Dict]) -> str:
    """Format gainers and losers from top coins."""
    if not coins:
        return "*데이터를 가져올 수 없습니다.*"

    # Filter out stablecoins for meaningful rankings
    non_stable = [c for c in coins if c.get("symbol", "").lower() not in STABLECOIN_SYMBOLS]

    by_change = sorted(
        non_stable,
        key=lambda c: c.get("price_change_percentage_24h") or 0,
        reverse=True,
    )

    lines = ["### 🚀 Top 5 상승\n"]
    gainer_rows = []
    for c in by_change[:5]:
        sym = c.get("symbol", "").upper()
        p = c.get("current_price", 0) or 0
        ch = c.get("price_change_percentage_24h", 0) or 0
        p_str = f"${p:,.2f}" if p >= 1 else f"${p:,.6f}"
        gainer_rows.append([f"**{c.get('name', '')}** ({sym})", p_str, _pct(ch)])

    lines.append(markdown_table(["코인", "가격", "24h 변동"], gainer_rows))

    lines.append("\n### 📉 Top 5 하락\n")
    loser_rows = []
    for c in by_change[-5:]:
        sym = c.get("symbol", "").upper()
        p = c.get("current_price", 0) or 0
        ch = c.get("price_change_percentage_24h", 0) or 0
        p_str = f"${p:,.2f}" if p >= 1 else f"${p:,.6f}"
        loser_rows.append([f"**{c.get('name', '')}** ({sym})", p_str, _pct(ch)])

    lines.append(markdown_table(["코인", "가격", "24h 변동"], loser_rows))

    return "\n".join(lines)


def format_us_market(data: Dict) -> str:
    if not data:
        return (
            "> 미국 주식 시장 데이터를 일시적으로 가져올 수 없습니다. "
            "API 제한 또는 휴장일일 수 있습니다.\n\n"
            "**참고 링크:**\n"
            "- [Yahoo Finance - S&P 500](https://finance.yahoo.com/quote/%5EGSPC/)\n"
            "- [Yahoo Finance - NASDAQ](https://finance.yahoo.com/quote/%5EIXIC/)\n"
            "- [Yahoo Finance - Dow Jones](https://finance.yahoo.com/quote/%5EDJI/)"
        )
    rows = []
    for sym, info in data.items():
        rows.append(
            [
                f"{info['name']} ({sym})",
                f"${info['price']}",
                info["change"],
                info["change_pct"],
                info.get("volume", "N/A"),
            ]
        )
    return markdown_table(["종목", "가격", "변동", "변동률", "거래량"], rows)


def format_korean_market(data: Dict) -> str:
    if not data:
        return (
            "> 한국 주식 시장 데이터를 일시적으로 가져올 수 없습니다. "
            "휴장일이거나 데이터 소스 문제일 수 있습니다.\n\n"
            "**참고 링크:**\n"
            "- [네이버 금융 - KOSPI](https://finance.naver.com/sise/sise_index.naver?code=KOSPI)\n"
            "- [네이버 금융 - KOSDAQ](https://finance.naver.com/sise/sise_index.naver?code=KOSDAQ)"
        )
    rows = []
    for name, info in data.items():
        # Add emoji for direction
        try:
            pct = float(info["change_pct"].replace("%", "").replace("+", ""))
            icon = "🟢" if pct >= 0 else "🔴"
        except (ValueError, KeyError):
            icon = ""
        rows.append([name, info["price"], info["change"], f"{icon} {info['change_pct']}"])
    return markdown_table(["지수", "가격", "변동", "변동률"], rows)


def format_macro(data: Dict, has_api_key: bool = True) -> str:
    if not data:
        if not has_api_key:
            reason = (
                "`FRED_API_KEY` 환경변수가 설정되지 않아 매크로 경제 지표를 가져올 수 없습니다. "
                "FRED API 키를 발급받아 `FRED_API_KEY` 환경변수로 설정하면 이 섹션이 활성화됩니다."
            )
        else:
            reason = (
                "FRED API에서 매크로 경제 지표를 가져오지 못했습니다. "
                "API 키(`FRED_API_KEY`)가 유효한지 확인하거나, "
                "잠시 후 다시 시도해 주세요."
            )
        return (
            f"> {reason}\n\n"
            "**참고 링크:**\n"
            "- [FRED - Federal Funds Rate](https://fred.stlouisfed.org/series/FEDFUNDS)\n"
            "- [FRED - 10-Year Treasury](https://fred.stlouisfed.org/series/DGS10)\n"
            "- [FRED - Consumer Price Index](https://fred.stlouisfed.org/series/CPIAUCSL)\n"
            "- [FRED - VIX](https://fred.stlouisfed.org/series/VIXCLS)"
        )
    rows = []
    for d in data.values():
        val = f"{d['value']:.2f}"
        ch = f"{d['change']:+.2f}" if d.get("change") is not None else "N/A"
        rows.append([d["label"], val, ch])
    return markdown_table(["지표", "현재 값", "변동"], rows)


def generate_key_highlights(
    global_data: Dict,
    top_coins: List,
    fear_greed: Dict,
    kr_market: Dict,
    commodity_data: Optional[Dict] = None,
) -> str:
    """Generate concise bullet-point key highlights."""
    bullets = []

    # Fear & Greed
    if fear_greed:
        fg = fear_greed["value"]
        fg_cls = fear_greed["classification"]
        if fg_cls == "Extreme Fear":
            bullets.append(
                f"- **극도의 공포 장세**: 공포/탐욕 지수 {fg}으로 {fg_cls} 구간 진입. "
                "역사적으로 이 수준은 6~12개월 내 강력한 반등의 선행 지표였으며, "
                "장기 투자자에게 분할 매수 기회로 평가됩니다."
            )
        elif fg_cls == "Fear":
            bullets.append(
                f"- **공포 장세 지속**: 공포/탐욕 지수 {fg}으로 공포 구간. 보수적인 포지션 운영이 권장됩니다."
            )
        elif fg_cls == "Greed" or fg_cls == "Extreme Greed":
            bullets.append(
                f"- **탐욕 장세 주의**: 공포/탐욕 지수 {fg}으로 과열 구간. 차익 실현과 리스크 관리가 필요합니다."
            )

    # BTC price and market cap
    if top_coins:
        btc = next((c for c in top_coins if c.get("symbol", "").lower() == "btc"), None)
        if btc:
            price = btc.get("current_price", 0)
            ch24 = btc.get("price_change_percentage_24h", 0) or 0
            ch7d = btc.get("price_change_percentage_7d_in_currency", 0) or 0
            direction = "상승" if ch24 >= 0 else "하락"
            bullets.append(
                f"- **비트코인 ${price:,.0f} {direction}**: "
                f"24h 기준 {ch24:+.2f}% 변동, "
                f"주간 {ch7d:+.2f}% {'상승' if ch7d >= 0 else '하락'}."
            )

    # Global market cap
    if global_data:
        total_mcap = global_data.get("total_market_cap", {}).get("usd", 0)
        mcap_change = global_data.get("market_cap_change_percentage_24h_usd", 0)
        btc_dom = global_data.get("market_cap_percentage", {}).get("btc", 0)
        direction = "회복" if mcap_change >= 0 else "하락"
        bullets.append(
            f"- **시가총액 {_fmt(total_mcap)}으로 {direction}**: "
            f"전일 대비 {mcap_change:+.2f}%. "
            f"BTC 도미넌스 {btc_dom:.1f}%로 "
            f"비트코인 중심 자금 흐름 {'지속' if btc_dom > 50 else '약화'}."
        )

    # Korean market
    if kr_market:
        for name, info in kr_market.items():
            pct = info.get("change_pct", "")
            bullets.append(f"- **{name}**: {info['price']} ({info['change']}, {pct})")

    # Commodities (gold, oil)
    if commodity_data:
        gold = commodity_data.get("금 (Gold)")
        oil = commodity_data.get("원유 (WTI)")
        if gold:
            bullets.append(f"- **금**: ${gold['price']} ({gold['change']}, {gold['change_pct']})")
        if oil:
            bullets.append(f"- **원유(WTI)**: ${oil['price']} ({oil['change']}, {oil['change_pct']})")

    # Top movers
    if top_coins:
        sorted_coins = sorted(
            top_coins[:20],
            key=lambda c: c.get("price_change_percentage_24h") or 0,
            reverse=True,
        )
        gainers = [c for c in sorted_coins if (c.get("price_change_percentage_24h") or 0) > 0]
        losers = [c for c in sorted_coins if (c.get("price_change_percentage_24h") or 0) < 0]
        if gainers and losers:
            best = gainers[0]
            worst = losers[-1]
            best_ch = best.get("price_change_percentage_24h", 0) or 0
            worst_ch = worst.get("price_change_percentage_24h", 0) or 0
            bullets.append(
                f"- **주목할 코인**: {best.get('name', '')} "
                f"{best_ch:+.2f}% 급등, "
                f"{worst.get('name', '')} {worst_ch:+.2f}% 하락."
            )

    return "\n".join(bullets) if bullets else ""


def generate_insight(
    global_data: Dict,
    top_coins: List,
    fear_greed: Dict,
    us_market: Dict,
    kr_market: Dict,
) -> str:
    """Generate comprehensive Korean market insight."""
    parts = []

    # Crypto market sentiment
    mcap_change = global_data.get("market_cap_change_percentage_24h_usd", 0) if global_data else 0
    btc_dom = global_data.get("market_cap_percentage", {}).get("btc", 0) if global_data else 0

    if mcap_change > 5:
        parts.append(
            "암호화폐 시장이 **강한 상승세**를 보이고 있습니다. "
            "전체 시가총액이 대폭 증가하며 매수 심리가 확산되고 있습니다."
        )
    elif mcap_change > 1:
        parts.append(
            "암호화폐 시장이 **소폭 상승세**를 이어가고 있습니다. 안정적인 흐름 속에서 점진적 회복이 진행 중입니다."
        )
    elif mcap_change > -1:
        parts.append("암호화폐 시장이 **보합세**를 보이고 있습니다. 뚜렷한 방향성 없이 횡보 구간이 이어지고 있습니다.")
    elif mcap_change > -5:
        parts.append(
            "암호화폐 시장이 **하락세**를 보이고 있습니다. 단기 조정 가능성을 염두에 두고 리스크 관리가 필요합니다."
        )
    else:
        parts.append(
            "암호화폐 시장이 **급격한 하락세**를 보이고 있습니다. 패닉셀 가능성이 있으며, 신중한 접근이 필요합니다."
        )

    # BTC dominance
    if btc_dom > 55:
        parts.append(
            f"\nBTC 도미넌스가 **{btc_dom:.1f}%**로 높은 수준입니다. "
            "비트코인 중심의 자금 흐름이 지속되고 있어, "
            "알트코인 투자 시 주의가 필요합니다."
        )
    elif btc_dom < 45:
        parts.append(
            f"\nBTC 도미넌스가 **{btc_dom:.1f}%**로 낮은 편입니다. "
            "알트코인으로의 자금 이동이 활발한 '알트 시즌' 가능성이 있습니다."
        )

    # Fear & Greed
    if fear_greed:
        fg = fear_greed["value"]
        fg_cls = fear_greed["classification"]
        fg_map = {
            "Extreme Fear": "극도의 공포 상태입니다. 역사적으로 이 구간은 장기 투자자에게 매수 기회가 되어 왔습니다.",
            "Fear": "공포 상태입니다. 보수적인 포지션 운영이 권장되며, 분할 매수 전략을 고려해 볼 수 있습니다.",
            "Neutral": "중립 상태입니다. 시장 방향성을 주시하며 관망하는 것이 좋습니다.",
            "Greed": "탐욕 상태입니다. 차익 실현 타이밍을 고려하고, 추가 매수 시 신중할 필요가 있습니다.",
            "Extreme Greed": "극도의 탐욕 상태입니다. 시장 과열 경고 구간으로, 포트폴리오 리밸런싱을 고려하세요.",
        }
        parts.append(
            f"\n공포/탐욕 지수는 **{fg}** ({fg_cls})으로, {fg_map.get(fg_cls, '시장 심리를 주시해야 합니다.')}"
        )

    # Top movers
    if top_coins:
        best = max(top_coins[:20], key=lambda c: c.get("price_change_percentage_24h") or -999)
        worst = min(top_coins[:20], key=lambda c: c.get("price_change_percentage_24h") or 999)
        best_ch = best.get("price_change_percentage_24h", 0) or 0
        worst_ch = worst.get("price_change_percentage_24h", 0) or 0
        parts.append(
            f"\nTop 20 중 가장 큰 상승은 **{best.get('name', '')}** "
            f"({best_ch:+.2f}%), "
            f"가장 큰 하락은 **{worst.get('name', '')}** "
            f"({worst_ch:+.2f}%)입니다."
        )

    # US market insight
    if us_market:
        spy = us_market.get("SPY") or us_market.get("^GSPC")
        if spy:
            pct_str = spy.get("change_pct", "N/A")
            parts.append(f"\n미국 시장에서 S&P 500은 **{pct_str}** 변동을 보였습니다.")
            # Check for significant moves
            try:
                pct_val = float(pct_str.replace("%", "").replace("+", ""))
                if abs(pct_val) > 2:
                    parts.append("미국 증시의 대폭 변동은 글로벌 위험자산 심리에 직접적 영향을 미칩니다.")
            except (ValueError, AttributeError):
                pass

    # Korean market insight
    if kr_market:
        kospi = kr_market.get("KOSPI")
        usdkrw = kr_market.get("USD/KRW 환율")
        if kospi:
            parts.append(f"\n한국 증시는 KOSPI **{kospi['price']}** ({kospi['change_pct']})으로 마감했습니다.")
        if usdkrw:
            parts.append(
                f"원달러 환율은 **{usdkrw['price']}**원으로, 환율 변동이 외국인 투자 심리에 영향을 줄 수 있습니다."
            )

    parts.append(
        "\n> *본 리포트는 자동 수집된 데이터를 기반으로 생성되었으며, "
        "투자 조언이 아닙니다. 모든 투자 결정은 개인의 판단과 책임 하에 이루어져야 합니다.*"
    )

    return "\n".join(parts)


def generate_quant_signals(top_coins: List, global_data: Dict, fear_greed: Dict) -> str:
    lines = []
    btc = next((c for c in top_coins if c.get("symbol", "").upper() == "BTC"), None)
    eth = next((c for c in top_coins if c.get("symbol", "").upper() == "ETH"), None)

    def _trend(ch24: float, ch7d: float) -> str:
        if ch24 >= 0 and ch7d >= 0:
            return "상승 추세"
        if ch24 < 0 and ch7d < 0:
            return "하락 추세"
        return "혼조"

    if btc:
        ch24 = btc.get("price_change_percentage_24h", 0) or 0
        ch7d = btc.get("price_change_percentage_7d_in_currency", 0) or 0
        lines.append(f"- BTC 모멘텀: 24h {ch24:+.2f}%, 7d {ch7d:+.2f}% ({_trend(ch24, ch7d)})")
    if eth:
        ch24 = eth.get("price_change_percentage_24h", 0) or 0
        ch7d = eth.get("price_change_percentage_7d_in_currency", 0) or 0
        lines.append(f"- ETH 모멘텀: 24h {ch24:+.2f}%, 7d {ch7d:+.2f}% ({_trend(ch24, ch7d)})")

    if global_data:
        mcap_change = global_data.get("market_cap_change_percentage_24h_usd", 0) or 0
        btc_dom = global_data.get("market_cap_percentage", {}).get("btc", 0) or 0
        if mcap_change > 1 and btc_dom < 50:
            regime = "리스크온(알트 확장)"
        elif mcap_change < -1 and btc_dom > 50:
            regime = "리스크오프(방어적)"
        else:
            regime = "중립/대기"
        lines.append(f"- 시장 레짐: {regime} | 시총 24h {mcap_change:+.2f}%, BTC 도미넌스 {btc_dom:.1f}%")

    if fear_greed:
        fg = fear_greed.get("value", "N/A")
        fg_cls = fear_greed.get("classification", "N/A")
        lines.append(f"- 심리 지표: 공포/탐욕 {fg} ({fg_cls})")

    return "\n".join(lines)


# ══════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════


def main():
    """Generate comprehensive daily market summary with images."""
    logger.info("=== Generating enhanced daily market summary ===")

    alpha_vantage_key = get_env("ALPHA_VANTAGE_API_KEY")
    fred_key = get_env("FRED_API_KEY")
    kst = get_kst_timezone()
    now = datetime.now(kst)
    today = now.strftime("%Y-%m-%d")

    dedup = DedupEngine("market_summary_seen.json")

    # Fetch all data with rate limiting
    top_coins = fetch_coingecko_top_coins(30)
    time.sleep(2)
    global_data = fetch_coingecko_global()
    time.sleep(2)
    trending = fetch_coingecko_trending()
    time.sleep(1)
    fear_greed = fetch_fear_greed_index(history_days=7)
    us_market = fetch_us_market_data(alpha_vantage_key)
    kr_market = fetch_korean_market()
    commodity_data = fetch_commodity_data()
    fred_data = fetch_fred_indicators(fred_key)
    sector_data = fetch_sector_performance()
    btc_etf_data = fetch_btc_etf_data()
    whale_items = fetch_whale_trades()
    yield_spread = calculate_yield_spread(fred_data)

    # ── Generate images ──
    # Filter stablecoins for image generation
    non_stable_coins = [c for c in top_coins if c.get("symbol", "").lower() not in STABLECOIN_SYMBOLS]

    image_refs = []
    try:
        from common.image_generator import (
            generate_fear_greed_gauge,
            generate_market_heatmap,
            generate_sector_heatmap,
            generate_top_coins_card,
        )

        img = generate_market_heatmap(non_stable_coins, today)
        if img:
            image_refs.append(("market-heatmap", img))

        img = generate_top_coins_card(non_stable_coins, today)
        if img:
            image_refs.append(("top-coins", img))

        if fear_greed:
            img = generate_fear_greed_gauge(fear_greed["value"], fear_greed["classification"], today)
            if img:
                image_refs.append(("fear-greed", img))

        if sector_data:
            img = generate_sector_heatmap(sector_data, today)
            if img:
                image_refs.append(("sector-heatmap", img))

        logger.info("Generated %d images", len(image_refs))
    except ImportError:
        logger.warning("Image generator not available (matplotlib/Pillow missing)")
    except Exception as e:
        logger.warning("Image generation failed: %s", e)

    # ── Build post content ──
    sections = OrderedDict()

    # Images at the top
    if image_refs:
        img_lines = []
        for label, path in image_refs:
            # Convert absolute path to site-relative URL with baseurl
            filename = os.path.basename(path)
            web_path = "{{ '/assets/images/generated/" + filename + "' | relative_url }}"
            img_lines.append(f"![{label}]({web_path})")
        sections["시장 시각화"] = "\n\n".join(img_lines)

    # Key highlights bullet points at the very top
    highlights = generate_key_highlights(global_data, top_coins, fear_greed, kr_market, commodity_data)
    if highlights:
        sections["오늘의 핵심"] = highlights

    # Executive summary (한눈에 보기) — stat-grid + alert-box HTML
    stat_items = []
    alert_lines = []

    if fear_greed:
        fg_val = fear_greed.get("value", "N/A")
        fg_class = fear_greed.get("classification", "N/A")
        stat_items.append(
            f'<div class="stat-item"><div class="stat-value">{fg_val}</div>'
            f'<div class="stat-label">공포/탐욕 ({fg_class})</div></div>'
        )

    if global_data:
        mcap = global_data.get("total_market_cap", {}).get("usd")
        if mcap:
            stat_items.append(
                f'<div class="stat-item"><div class="stat-value">${mcap / 1e12:.2f}T</div>'
                f'<div class="stat-label">글로벌 시총</div></div>'
            )
        btc_dom = global_data.get("market_cap_percentage", {}).get("btc")
        if btc_dom:
            stat_items.append(
                f'<div class="stat-item"><div class="stat-value">{btc_dom:.1f}%</div>'
                f'<div class="stat-label">BTC 도미넌스</div></div>'
            )
        mcap_ch = global_data.get("market_cap_change_percentage_24h_usd", 0)
        stat_items.append(
            f'<div class="stat-item"><div class="stat-value">{mcap_ch:+.2f}%</div>'
            f'<div class="stat-label">시총 24h 변동</div></div>'
        )

    if top_coins:
        btc = next((c for c in top_coins if c.get("symbol", "").upper() == "BTC"), None)
        eth = next((c for c in top_coins if c.get("symbol", "").upper() == "ETH"), None)
        if btc:
            btc_price = btc.get("current_price", 0)
            btc_ch = btc.get("price_change_percentage_24h", 0) or 0
            alert_lines.append(f"<li><strong>BTC</strong>: ${btc_price:,.0f} ({btc_ch:+.2f}%)</li>")
        if eth:
            eth_price = eth.get("current_price", 0)
            eth_ch = eth.get("price_change_percentage_24h", 0) or 0
            alert_lines.append(f"<li><strong>ETH</strong>: ${eth_price:,.0f} ({eth_ch:+.2f}%)</li>")

    if kr_market:
        for name, info in kr_market.items():
            alert_lines.append(f"<li><strong>{name}</strong>: {info['price']} ({info['change_pct']})</li>")

    if commodity_data:
        gold = commodity_data.get("금 (Gold)")
        oil = commodity_data.get("원유 (WTI)")
        if gold:
            alert_lines.append(f"<li><strong>금</strong>: ${gold['price']} ({gold['change_pct']})</li>")
        if oil:
            alert_lines.append(f"<li><strong>원유</strong>: ${oil['price']} ({oil['change_pct']})</li>")

    exec_parts = []
    if stat_items:
        exec_parts.append(f'<div class="stat-grid">{"".join(stat_items)}</div>')
    if alert_lines:
        exec_parts.append(
            f'<div class="alert-box alert-info"><strong>주요 자산 현황</strong><ul>{"".join(alert_lines)}</ul></div>'
        )
    if exec_parts:
        sections["한눈에 보기"] = "\n\n".join(exec_parts)

    quant_signals = generate_quant_signals(top_coins, global_data, fear_greed)
    if quant_signals:
        sections["퀀트 시그널 요약"] = quant_signals

    # Market insight
    insight = generate_insight(global_data, top_coins, fear_greed, us_market, kr_market)
    if insight:
        sections["오늘의 시장 인사이트"] = insight

    # Global overview + Fear & Greed
    sections["글로벌 암호화폐 시장"] = format_global_overview(global_data, fear_greed)

    # Top 20 coins
    sections["시가총액 Top 20"] = format_top_coins(top_coins)

    # Trending
    sections["트렌딩 코인"] = format_trending(trending)

    # Gainers / Losers
    sections["급등/급락 코인"] = format_gainers_losers(top_coins)

    # US Market
    sections["미국 주식 시장"] = format_us_market(us_market)

    # Korean Market
    sections["한국 주식 시장"] = format_korean_market(kr_market)

    # Commodities / Dollar Index
    sections["원자재/환율"] = format_commodity_data(commodity_data)

    # Sector Performance
    sections["S&P 500 섹터 퍼포먼스"] = format_sector_performance(sector_data)

    # Bitcoin ETF
    sections["비트코인 ETF"] = format_btc_etf(btc_etf_data)

    # Whale Trades
    sections["고래 거래 동향"] = format_whale_trades(whale_items)

    # Macro
    sections["매크로 경제 지표"] = format_macro(fred_data, has_api_key=bool(fred_key))

    # Yield Spread
    if yield_spread:
        sections["국채 수익률 스프레드 (2Y-10Y)"] = format_yield_spread(yield_spread)

    # References
    sections["참고 자료"] = (
        "- [CoinGecko - 암호화폐 시가총액](https://www.coingecko.com/) - 글로벌 암호화폐 데이터\n"
        "- [Alternative.me - 공포/탐욕 지수](https://alternative.me/crypto/fear-and-greed-index/) - 시장 심리 지표\n"
        "- [Investing.com - KOSPI](https://kr.investing.com/indices/kospi) - 한국 주식 시장 데이터\n"
        "- [Yahoo Finance - 미국 시장](https://finance.yahoo.com/) - 미국 주식 시장 데이터\n"
        "- [FRED - 경제 지표](https://fred.stlouisfed.org/) - 미국 연방준비은행 경제 데이터\n\n"
        "> *본 리포트는 자동 수집된 데이터를 기반으로 생성되었으며, "
        "투자 조언이 아닙니다. "
        "모든 투자 결정은 개인의 판단과 책임 하에 이루어져야 합니다.*"
    )

    # Generate post
    gen = PostGenerator("market-analysis")
    title = f"일일 시장 종합 리포트 - {today}"

    if dedup.is_duplicate_exact(title, "auto-generated", today):
        logger.info("Market summary already exists for today, skipping")
        dedup.save()
        return

    content = "\n\n".join(f"## {k}\n\n{v}" for k, v in sections.items())
    # 연속 빈줄을 최대 2줄로 정리
    content = re.sub(r"\n{3,}", "\n\n", content)

    filepath = gen.create_post(
        title=title,
        content=content,
        date=now,
        tags=[
            "market-summary",
            "daily",
            "crypto",
            "stock",
            "macro",
            "top-coins",
            "quant",
            "trading",
        ],
        source="auto-generated",
        lang="ko",
        image=f"/assets/images/generated/market-heatmap-{today}.png",
        slug="daily-market-report",
    )

    if filepath:
        dedup.mark_seen(title, "auto-generated", today)
        logger.info("Created enhanced market summary: %s", filepath)
    else:
        logger.warning("Failed to create market summary")

    dedup.save()

    logger.info("=== Enhanced market summary generation complete ===")


if __name__ == "__main__":
    main()
