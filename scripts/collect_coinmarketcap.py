#!/usr/bin/env python3
"""Collect top cryptocurrency data from CoinMarketCap and CoinGecko.

Sources:
- CoinMarketCap API (top coins, trending, gainers/losers)
- CoinGecko API (free fallback - top coins, trending, market data)
- Global market cap data

Generates high-quality Korean summary posts with market analysis.
"""

import sys
import os
import time
from datetime import datetime, timezone
from collections import OrderedDict
from typing import List, Dict, Any, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common.config import get_env, setup_logging, get_ssl_verify
from common.dedup import DedupEngine
from common.post_generator import PostGenerator
from common.crypto_api import (
    fetch_coingecko_top_coins,
    fetch_coingecko_trending,
    fetch_coingecko_global,
    fetch_fear_greed_index,
)
from common.formatters import fmt_number as _fmt_num, fmt_percent as _fmt_pct
from common.utils import request_with_retry
from common.collector_metrics import log_collection_summary

try:
    from common.browser import BrowserSession, is_playwright_available
except ImportError:
    BrowserSession = None  # type: ignore[assignment,misc]

    def is_playwright_available() -> bool:  # type: ignore[misc]
        return False


logger = setup_logging("collect_coinmarketcap")

VERIFY_SSL = get_ssl_verify()
REQUEST_TIMEOUT = 20  # CMC/CoinGecko API는 응답이 느려 기본값(15)보다 길게 설정


# ──────────────────────────────────────────────
# CoinMarketCap (API key optional, enhanced data)
# ──────────────────────────────────────────────


def fetch_cmc_top_coins(api_key: str, limit: int = 30) -> List[Dict[str, Any]]:
    """Fetch top coins from CoinMarketCap API."""
    if not api_key:
        return []

    try:
        url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest"
        headers = {"X-CMC_PRO_API_KEY": api_key, "Accept": "application/json"}
        params = {
            "start": "1",
            "limit": str(limit),
            "convert": "USD",
            "sort": "market_cap",
        }
        resp = request_with_retry(
            url,
            params=params,
            timeout=REQUEST_TIMEOUT,
            verify_ssl=VERIFY_SSL,
            headers={**headers},
        )
        data = resp.json()
        coins = data.get("data", [])
        logger.info("CMC: fetched %d top coins", len(coins))
        return coins
    except Exception as e:
        logger.warning("CMC top coins fetch failed: %s", e)
        return []


def fetch_cmc_trending(api_key: str) -> List[Dict[str, Any]]:
    """Fetch trending coins from CoinMarketCap."""
    if not api_key:
        return []

    try:
        url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/trending/latest"
        headers = {"X-CMC_PRO_API_KEY": api_key, "Accept": "application/json"}
        params = {"limit": "10", "convert": "USD"}
        resp = request_with_retry(
            url,
            params=params,
            timeout=REQUEST_TIMEOUT,
            verify_ssl=VERIFY_SSL,
            headers={**headers},
        )
        data = resp.json()
        coins = data.get("data", [])
        logger.info("CMC: fetched %d trending coins", len(coins))
        return coins
    except Exception as e:
        logger.warning("CMC trending fetch failed: %s", e)
        return []


def fetch_cmc_gainers_losers(api_key: str) -> Tuple[List[Dict], List[Dict]]:
    """Fetch biggest gainers and losers from CoinMarketCap."""
    if not api_key:
        return [], []

    try:
        url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/trending/gainers-losers"
        headers = {"X-CMC_PRO_API_KEY": api_key, "Accept": "application/json"}
        params = {"limit": "10", "convert": "USD", "time_period": "24h"}
        resp = request_with_retry(
            url,
            params=params,
            timeout=REQUEST_TIMEOUT,
            verify_ssl=VERIFY_SSL,
            headers={**headers},
        )
        data = resp.json().get("data", {})
        gainers = data.get("gainers", [])
        losers = data.get("losers", [])
        logger.info("CMC: fetched %d gainers, %d losers", len(gainers), len(losers))
        return gainers, losers
    except Exception as e:
        logger.warning("CMC gainers/losers fetch failed: %s", e)
        return [], []


def format_global_market(data: Dict[str, Any]) -> str:
    """Format global market overview."""
    if not data:
        return "*글로벌 시장 데이터를 가져올 수 없습니다.*"

    total_mcap = data.get("total_market_cap", {}).get("usd", 0)
    total_vol = data.get("total_volume", {}).get("usd", 0)
    btc_dom = data.get("market_cap_percentage", {}).get("btc", 0)
    eth_dom = data.get("market_cap_percentage", {}).get("eth", 0)
    mcap_change = data.get("market_cap_change_percentage_24h_usd", 0)
    active_coins = data.get("active_cryptocurrencies", 0)

    lines = [
        f"**총 시가총액**: {_fmt_num(total_mcap)} ({_fmt_pct(mcap_change)})",
        f"**24시간 거래량**: {_fmt_num(total_vol)}",
        f"**BTC 도미넌스**: {btc_dom:.1f}% | **ETH 도미넌스**: {eth_dom:.1f}%",
        f"**활성 코인 수**: {active_coins:,}개",
    ]
    return "\n\n".join(lines)


def format_top_coins_table(coins: List[Dict], source: str = "coingecko") -> str:
    """Format top coins as a markdown table."""
    if not coins:
        return "*데이터를 가져올 수 없습니다.*"

    lines = [
        "| # | 코인 | 가격 (USD) | 24h 변동 | 7d 변동 | 시가총액 |",
        "|---|------|-----------|---------|--------|---------|",
    ]

    for i, coin in enumerate(coins[:20], 1):
        if source == "coingecko":
            name = coin.get("name", "")
            symbol = coin.get("symbol", "").upper()
            price = coin.get("current_price", 0)
            change_24h = coin.get("price_change_percentage_24h", 0)
            change_7d = coin.get("price_change_percentage_7d_in_currency", 0)
            mcap = coin.get("market_cap", 0)
        else:  # CMC
            name = coin.get("name", "")
            symbol = coin.get("symbol", "")
            quote = coin.get("quote", {}).get("USD", {})
            price = quote.get("price", 0)
            change_24h = quote.get("percent_change_24h", 0)
            change_7d = quote.get("percent_change_7d", 0)
            mcap = quote.get("market_cap", 0)

        price_str = (
            f"${price:,.2f}"
            if price and price >= 1
            else f"${price:,.6f}"
            if price
            else "N/A"
        )
        lines.append(
            f"| {i} | **{name}** ({symbol}) | {price_str} | {_fmt_pct(change_24h)} | {_fmt_pct(change_7d)} | {_fmt_num(mcap)} |"
        )

    return "\n".join(lines)


def format_trending_coins(coins: List[Dict], source: str = "coingecko") -> str:
    """Format trending coins."""
    if not coins:
        return "*트렌딩 데이터를 가져올 수 없습니다.*"

    lines = ["**현재 가장 주목받는 코인들:**\n"]

    for i, coin_data in enumerate(coins[:10], 1):
        if source == "coingecko":
            item = coin_data.get("item", {})
            name = item.get("name", "")
            symbol = item.get("symbol", "")
            rank = item.get("market_cap_rank", "N/A")
            _score = item.get("score", 0)
            lines.append(f"{i}. **{name}** ({symbol}) — 시가총액 순위 #{rank}")
        else:  # CMC
            name = coin_data.get("name", "")
            symbol = coin_data.get("symbol", "")
            quote = coin_data.get("quote", {}).get("USD", {})
            change = quote.get("percent_change_24h", 0)
            lines.append(f"{i}. **{name}** ({symbol}) — 24h: {_fmt_pct(change)}")

    return "\n".join(lines)


def format_gainers_losers(gainers: List[Dict], losers: List[Dict]) -> str:
    """Format biggest gainers and losers."""
    lines = []

    if gainers:
        lines.append("### 🚀 24시간 최대 상승\n")
        lines.append("| 코인 | 가격 | 24h 변동 |")
        lines.append("|------|------|---------|")
        for coin in gainers[:5]:
            name = coin.get("name", "")
            symbol = coin.get("symbol", "")
            quote = coin.get("quote", {}).get("USD", {})
            price = quote.get("price", 0)
            change = quote.get("percent_change_24h", 0)
            lines.append(
                f"| **{name}** ({symbol}) | ${price:,.4f} | {_fmt_pct(change)} |"
            )

    if losers:
        lines.append("\n### 📉 24시간 최대 하락\n")
        lines.append("| 코인 | 가격 | 24h 변동 |")
        lines.append("|------|------|---------|")
        for coin in losers[:5]:
            name = coin.get("name", "")
            symbol = coin.get("symbol", "")
            quote = coin.get("quote", {}).get("USD", {})
            price = quote.get("price", 0)
            change = quote.get("percent_change_24h", 0)
            lines.append(
                f"| **{name}** ({symbol}) | ${price:,.4f} | {_fmt_pct(change)} |"
            )

    return "\n".join(lines) if lines else "*급등/급락 데이터를 가져올 수 없습니다.*"


def derive_gainers_losers_from_top(coins: List[Dict]) -> Tuple[str, str]:
    """Derive gainers and losers from top coins list (CoinGecko fallback)."""
    if not coins:
        return "*데이터 없음*", "*데이터 없음*"

    sorted_by_change = sorted(
        coins, key=lambda c: c.get("price_change_percentage_24h") or 0, reverse=True
    )

    # Top 5 gainers
    g_lines = ["| 코인 | 가격 | 24h 변동 |", "|------|------|---------|"]
    for coin in sorted_by_change[:5]:
        name = coin.get("name", "")
        symbol = coin.get("symbol", "").upper()
        price = coin.get("current_price", 0)
        change = coin.get("price_change_percentage_24h", 0)
        price_str = (
            f"${price:,.2f}"
            if price and price >= 1
            else f"${price:,.6f}"
            if price
            else "N/A"
        )
        g_lines.append(f"| **{name}** ({symbol}) | {price_str} | {_fmt_pct(change)} |")

    # Top 5 losers
    l_lines = ["| 코인 | 가격 | 24h 변동 |", "|------|------|---------|"]
    for coin in sorted_by_change[-5:]:
        name = coin.get("name", "")
        symbol = coin.get("symbol", "").upper()
        price = coin.get("current_price", 0)
        change = coin.get("price_change_percentage_24h", 0)
        price_str = (
            f"${price:,.2f}"
            if price and price >= 1
            else f"${price:,.6f}"
            if price
            else "N/A"
        )
        l_lines.append(f"| **{name}** ({symbol}) | {price_str} | {_fmt_pct(change)} |")

    return "\n".join(g_lines), "\n".join(l_lines)


def generate_market_insight(
    global_data: Dict, top_coins: List[Dict], fear_greed: Dict
) -> str:
    """Generate Korean market insight summary."""
    if not global_data and not top_coins:
        return ""

    mcap_change = (
        global_data.get("market_cap_change_percentage_24h_usd", 0) if global_data else 0
    )
    btc_dom = (
        global_data.get("market_cap_percentage", {}).get("btc", 0) if global_data else 0
    )
    fg_value = fear_greed.get("value", 50) if fear_greed else 50
    fg_class = fear_greed.get("classification", "Neutral") if fear_greed else "Neutral"

    # Determine market sentiment
    if mcap_change > 3:
        market_mood = (
            "강세장이 이어지고 있습니다. 시장 전체 시가총액이 큰 폭으로 상승했습니다."
        )
    elif mcap_change > 0:
        market_mood = (
            "소폭 상승세를 보이고 있습니다. 시장은 안정적인 흐름을 유지하고 있습니다."
        )
    elif mcap_change > -3:
        market_mood = "소폭 하락세를 보이고 있습니다. 단기 조정 구간으로 판단됩니다."
    else:
        market_mood = "큰 하락세를 보이고 있습니다. 리스크 관리에 주의가 필요합니다."

    # BTC dominance insight
    if btc_dom > 55:
        btc_insight = f"BTC 도미넌스가 {btc_dom:.1f}%로 높은 수준이며, 비트코인 중심의 시장 흐름이 지속되고 있습니다."
    elif btc_dom > 45:
        btc_insight = f"BTC 도미넌스 {btc_dom:.1f}%로 알트코인과 비트코인이 균형을 이루고 있습니다."
    else:
        btc_insight = f"BTC 도미넌스가 {btc_dom:.1f}%로 낮아 알트코인 시즌이 진행 중일 수 있습니다."

    # Fear & Greed insight
    fg_map = {
        "Extreme Fear": "극도의 공포 상태로, 역발상 매수 기회가 될 수 있습니다.",
        "Fear": "공포 상태이며, 보수적인 투자 접근이 권장됩니다.",
        "Neutral": "중립적 상태로, 시장 방향성을 주시해야 합니다.",
        "Greed": "탐욕 상태이며, 차익 실현을 고려해 볼 시점입니다.",
        "Extreme Greed": "극도의 탐욕 상태로, 과열 주의가 필요합니다.",
    }
    fg_insight = fg_map.get(fg_class, "시장 심리를 확인할 수 없습니다.")

    lines = [
        "**오늘의 시장 인사이트:**\n",
        f"암호화폐 시장은 현재 {market_mood}",
        "",
        f"{btc_insight}",
        "",
        f"공포/탐욕 지수는 **{fg_value}** ({fg_class})으로, {fg_insight}",
        "",
        "> *본 분석은 자동 수집된 데이터를 기반으로 생성되었으며, 투자 조언이 아닙니다. 투자 결정은 개인의 판단과 책임 하에 이루어져야 합니다.*",
    ]
    return "\n".join(lines)


def fetch_cmc_browser_fallback(limit: int = 20) -> List[Dict[str, Any]]:
    """Scrape CoinMarketCap homepage table as fallback when APIs fail.

    Returns a list of dicts compatible with CoinGecko format for reuse in
    ``format_top_coins_table(coins, source="coingecko")``.
    """
    if not is_playwright_available():
        return []
    if BrowserSession is None:
        return []

    items: List[Dict[str, Any]] = []
    try:
        with BrowserSession(timeout=30_000) as session:
            session.navigate(
                "https://coinmarketcap.com/",
                wait_until="domcontentloaded",
                wait_ms=5000,
            )
            rows = session.extract_elements("table tbody tr")

            for row in rows[:limit]:
                try:
                    cells = row.query_selector_all("td")
                    if len(cells) < 8:
                        continue

                    # CMC table: 0=star, 1=#, 2=name+symbol, 3=price, 4=1h%, 5=24h%, 6=7d%, 7+=mcap...
                    name_cell = cells[2].inner_text().strip()
                    # Skip index products (e.g. "CoinMarketCap 20 Index DTF")
                    if "Index" in name_cell or "DTF" in name_cell:
                        continue
                    # name_cell may be "Bitcoin\nBTC" or "Bitcoin BTC"
                    parts = name_cell.replace("\n", " ").split()
                    symbol = parts[-1] if parts else ""
                    name = (
                        " ".join(parts[:-1])
                        if len(parts) > 1
                        else parts[0]
                        if parts
                        else ""
                    )

                    price_text = (
                        cells[3].inner_text().strip().replace("$", "").replace(",", "")
                    )
                    change_24h_text = (
                        cells[5].inner_text().strip().replace("%", "").replace(",", "")
                    )
                    change_7d_text = (
                        cells[6].inner_text().strip().replace("%", "").replace(",", "")
                    )
                    # Market cap is typically at cell 7 or later
                    mcap_text = (
                        cells[7].inner_text().strip().replace("$", "").replace(",", "")
                        if len(cells) > 7
                        else "0"
                    )

                    def _parse_num(s: str) -> float:
                        s = s.strip()
                        if not s or s == "N/A":
                            return 0.0
                        # Handle B/M/K suffixes
                        multiplier = 1
                        if s.endswith("B"):
                            multiplier = 1_000_000_000
                            s = s[:-1]
                        elif s.endswith("M"):
                            multiplier = 1_000_000
                            s = s[:-1]
                        elif s.endswith("K"):
                            multiplier = 1_000
                            s = s[:-1]
                        try:
                            return float(s) * multiplier
                        except ValueError:
                            return 0.0

                    items.append(
                        {
                            "name": name,
                            "symbol": symbol.lower(),
                            "current_price": _parse_num(price_text),
                            "price_change_percentage_24h": _parse_num(change_24h_text),
                            "price_change_percentage_7d_in_currency": _parse_num(
                                change_7d_text
                            ),
                            "market_cap": _parse_num(mcap_text),
                        }
                    )
                except Exception as e:
                    logger.debug("CMC coin parse error: %s", e)
                    continue

        logger.info("CMC Browser: fetched %d coins", len(items))
    except Exception as e:
        logger.warning("CMC browser scraping failed: %s", e)

    return items


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────


def main():
    """Main collection routine."""
    logger.info("=== Starting CoinMarketCap/CoinGecko collection ===")
    started_at = time.monotonic()

    cmc_key = get_env("CMC_API_KEY")

    # Skip entirely if no CMC key — CoinGecko fallback duplicates generate_market_summary.py
    if not cmc_key:
        logger.info("CMC API key not set, skipping to avoid duplicate CoinGecko report")
        log_collection_summary(
            logger,
            collector="collect_coinmarketcap",
            source_count=0,
            unique_items=0,
            post_created=0,
            started_at=started_at,
            extras={"status": "no_api_key"},
        )
        return

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    now = datetime.now(timezone.utc)

    dedup = DedupEngine("crypto_news_seen.json")
    gen_analysis = PostGenerator("market-analysis")

    # ── Fetch data ──
    global_data = fetch_coingecko_global()
    time.sleep(2)

    # Try CMC first, fallback to CoinGecko, then browser scraping
    if cmc_key:
        top_coins = fetch_cmc_top_coins(cmc_key, 30)
        source_name = "CoinMarketCap"
        cmc_source = "cmc"
        time.sleep(1)
        trending = fetch_cmc_trending(cmc_key)
        time.sleep(1)
        gainers, losers = fetch_cmc_gainers_losers(cmc_key)
    else:
        top_coins = fetch_coingecko_top_coins(30)
        source_name = "CoinGecko"
        cmc_source = "coingecko"
        time.sleep(2)
        trending = fetch_coingecko_trending()
        gainers, losers = [], []

    # Browser fallback: if API fetch returned no coins, try scraping CMC page
    if not top_coins:
        logger.info("API fetch returned no coins, trying CMC browser fallback")
        top_coins = fetch_cmc_browser_fallback(30)
        if top_coins:
            source_name = "CoinMarketCap (Browser)"
            cmc_source = "coingecko"  # same dict format

    # Fear & Greed
    time.sleep(1)
    fear_greed = fetch_fear_greed_index(history_days=1)

    # ── Generate high-quality summary post ──
    title = f"암호화폐 시장 종합 리포트 - {today}"
    filepath = None

    if not dedup.is_duplicate_exact(title, source_name, today):
        sections = OrderedDict()

        # 0. Generate images
        image_refs = []
        try:
            from common.image_generator import (
                generate_top_coins_card,
                generate_market_heatmap,
            )

            img = generate_top_coins_card(
                top_coins,
                today,
                source=cmc_source,
                filename=f"top-coins-cmc-{today}.png",
            )
            if img:
                image_refs.append(("top-coins-cmc", img))

            img = generate_market_heatmap(
                top_coins,
                today,
                source=cmc_source,
                filename=f"market-heatmap-cmc-{today}.png",
            )
            if img:
                image_refs.append(("market-heatmap-cmc", img))

            logger.info("Generated %d images for CMC post", len(image_refs))
        except ImportError:
            logger.warning("Image generator not available")
        except Exception as e:
            logger.warning("Image generation failed: %s", e)

        if image_refs:
            img_lines = []
            for label, path in image_refs:
                fn = os.path.basename(path)
                web_path = "{{ '/assets/images/generated/" + fn + "' | relative_url }}"
                img_lines.append(f"![{label}]({web_path})")
            sections["시장 시각화"] = "\n\n".join(img_lines)

        # 0-b. News briefing card image
        try:
            from common.image_generator import generate_news_briefing_card

            card_themes = []
            # Build themes from top coin movers
            gainers_for_card = sorted(
                top_coins[:20],
                key=lambda c: abs(
                    c.get("price_change_percentage_24h")
                    or c.get("quote", {}).get("USD", {}).get("percent_change_24h", 0)
                    or 0
                ),
                reverse=True,
            )[:3]
            for coin in gainers_for_card:
                if cmc_source == "coingecko":
                    name = coin.get("name", "")
                    symbol = coin.get("symbol", "").upper()
                    change = coin.get("price_change_percentage_24h", 0) or 0
                else:
                    name = coin.get("name", "")
                    symbol = coin.get("symbol", "")
                    change = (
                        coin.get("quote", {})
                        .get("USD", {})
                        .get("percent_change_24h", 0)
                        or 0
                    )
                emoji = "🟢" if change >= 0 else "🔴"
                card_themes.append(
                    {
                        "name": f"{name} ({symbol})",
                        "emoji": emoji,
                        "count": 1,
                        "keywords": [f"{change:+.2f}%"],
                    }
                )
            # Add market overview themes
            if global_data:
                btc_dom = global_data.get("market_cap_percentage", {}).get("btc", 0)
                card_themes.append(
                    {
                        "name": "BTC 도미넌스",
                        "emoji": "🟠",
                        "count": 1,
                        "keywords": [f"{btc_dom:.1f}%"],
                    }
                )
            if fear_greed:
                fg_val = fear_greed.get("value", 0)
                fg_cls = fear_greed.get("classification", "N/A")
                card_themes.append(
                    {
                        "name": "공포/탐욕",
                        "emoji": "📊",
                        "count": 1,
                        "keywords": [f"{fg_val} ({fg_cls})"],
                    }
                )

            briefing_img = generate_news_briefing_card(
                card_themes,
                today,
                category="Crypto Market Report",
                total_count=len(top_coins),
                filename=f"news-briefing-cmc-{today}.png",
            )
            if briefing_img:
                fn = os.path.basename(briefing_img)
                web_path = "{{ '/assets/images/generated/" + fn + "' | relative_url }}"
                sections["오늘의 브리핑"] = f"![market-briefing]({web_path})"
        except ImportError:
            pass
        except Exception as e:
            logger.warning("Briefing card generation failed: %s", e)

        # 1. 한눈에 보기 — stat-grid + alert-box
        stat_items = []
        alert_lines = []

        btc = next(
            (c for c in top_coins if (c.get("symbol") or "").lower() in ("btc",)),
            None,
        )
        if btc:
            if cmc_source == "coingecko":
                btc_price = btc.get("current_price", 0)
                btc_ch24 = btc.get("price_change_percentage_24h", 0) or 0
            else:
                btc_q = btc.get("quote", {}).get("USD", {})
                btc_price = btc_q.get("price", 0) or 0
                btc_ch24 = btc_q.get("percent_change_24h", 0) or 0
            stat_items.append(
                f'<div class="stat-item"><div class="stat-value">${btc_price:,.0f}</div>'
                f'<div class="stat-label">BTC ({btc_ch24:+.1f}%)</div></div>'
            )

        if fear_greed:
            fg_val = fear_greed.get("value", 0)
            fg_cls = fear_greed.get("classification", "N/A")
            stat_items.append(
                f'<div class="stat-item"><div class="stat-value">{fg_val}</div>'
                f'<div class="stat-label">공포/탐욕 ({fg_cls})</div></div>'
            )

        if global_data:
            total_mcap = global_data.get("total_market_cap", {}).get("usd", 0)
            mcap_ch = global_data.get("market_cap_change_percentage_24h_usd", 0)
            btc_dom = global_data.get("market_cap_percentage", {}).get("btc", 0)
            if total_mcap:
                stat_items.append(
                    f'<div class="stat-item"><div class="stat-value">{_fmt_num(total_mcap)}</div>'
                    f'<div class="stat-label">총 시가총액</div></div>'
                )
            stat_items.append(
                f'<div class="stat-item"><div class="stat-value">{btc_dom:.1f}%</div>'
                f'<div class="stat-label">BTC 도미넌스</div></div>'
            )

        # Alert box: top 3 movers
        sorted_movers_brief = sorted(
            top_coins[:20],
            key=lambda c: abs(
                c.get("price_change_percentage_24h")
                or c.get("quote", {}).get("USD", {}).get("percent_change_24h", 0)
                or 0
            ),
            reverse=True,
        )
        for coin in sorted_movers_brief[:3]:
            if cmc_source == "coingecko":
                mn = coin.get("name", "")
                ms = coin.get("symbol", "").upper()
                mch = coin.get("price_change_percentage_24h", 0) or 0
            else:
                mn = coin.get("name", "")
                ms = coin.get("symbol", "")
                mch = coin.get("quote", {}).get("USD", {}).get("percent_change_24h", 0) or 0
            emoji = "🟢" if mch >= 0 else "🔴"
            alert_lines.append(f"<li>{emoji} <strong>{mn}</strong> ({ms}): {mch:+.2f}%</li>")

        overview_parts = []
        if stat_items:
            overview_parts.append(f'<div class="stat-grid">{"".join(stat_items)}</div>')
        if alert_lines:
            overview_parts.append(
                '<div class="alert-box alert-info">'
                "<strong>24시간 주요 변동</strong>"
                f'<ul>{"".join(alert_lines)}</ul>'
                "</div>"
            )
        if overview_parts:
            sections["한눈에 보기"] = "\n\n".join(overview_parts)

        # Narrative summary
        summary_parts = []
        coin_count = len(top_coins)
        summary_parts.append(
            f"오늘 시가총액 상위 **{coin_count}개** 코인을 기준으로 시장을 분석했습니다."
        )
        if btc:
            direction = "상승하며 투자 심리 회복을 견인" if btc_ch24 >= 0 else "하락하며 시장에 조정 신호를 보내"
            summary_parts.append(
                f"비트코인은 **${btc_price:,.0f}**에서 24시간 {btc_ch24:+.2f}% {direction}고 있습니다."
            )
        if global_data and total_mcap:
            summary_parts.append(
                f"전체 시가총액은 **{_fmt_num(total_mcap)}**으로 전일 대비 {mcap_ch:+.2f}% 변동했으며, "
                f"BTC 도미넌스 {btc_dom:.1f}%로 {'비트코인 중심 자금 흐름이 지속' if btc_dom > 50 else '알트코인으로의 자금 이동이 활발한 상황'}입니다."
            )
        if fear_greed:
            fg_map = {
                "Extreme Fear": "극도의 공포 상태로, 역발상 매수 기회를 모색할 시점",
                "Fear": "공포 구간으로, 보수적 접근이 권장되는 시점",
                "Neutral": "중립 상태로, 시장 방향성 관망이 필요한 시점",
                "Greed": "탐욕 구간으로, 차익 실현을 고려할 시점",
                "Extreme Greed": "극도의 탐욕 상태로, 과열 주의가 필요한 시점",
            }
            summary_parts.append(
                f"공포/탐욕 지수는 **{fg_val}** ({fg_cls})으로, {fg_map.get(fg_cls, '시장 심리 주시가 필요')}입니다."
            )
        sections["전체 뉴스 요약"] = " ".join(summary_parts)

        # 2. Market Insight (Korean analysis)
        insight = generate_market_insight(global_data, top_coins, fear_greed)
        if insight:
            sections["시장 인사이트"] = insight

        # 3. Global market overview
        sections["글로벌 암호화폐 시장 현황"] = format_global_market(global_data)

        # 4. Fear & Greed
        if fear_greed:
            value = fear_greed.get("value", 0)
            classification = fear_greed.get("classification", "N/A")
            bar = "█" * (value // 5) + "░" * (20 - value // 5)
            sections["공포/탐욕 지수"] = (
                f"**{value}/100** — {classification}\n\n`[{bar}]`"
            )

        # 5. Top movers briefing (description card style for top 5)
        if top_coins:
            mover_lines = []
            sorted_movers = sorted(
                top_coins[:20],
                key=lambda c: abs(
                    c.get("price_change_percentage_24h")
                    or c.get("quote", {}).get("USD", {}).get("percent_change_24h", 0)
                    or 0
                ),
                reverse=True,
            )
            for i, coin in enumerate(sorted_movers[:5], 1):
                if cmc_source == "coingecko":
                    name = coin.get("name", "")
                    symbol = coin.get("symbol", "").upper()
                    price = coin.get("current_price", 0)
                    ch24 = coin.get("price_change_percentage_24h", 0) or 0
                    ch7d = coin.get("price_change_percentage_7d_in_currency", 0) or 0
                    mcap = coin.get("market_cap", 0) or 0
                else:
                    name = coin.get("name", "")
                    symbol = coin.get("symbol", "")
                    quote = coin.get("quote", {}).get("USD", {})
                    price = quote.get("price", 0) or 0
                    ch24 = quote.get("percent_change_24h", 0) or 0
                    ch7d = quote.get("percent_change_7d", 0) or 0
                    mcap = quote.get("market_cap", 0) or 0
                direction = "상승" if ch24 >= 0 else "하락"
                price_str = f"${price:,.2f}" if price >= 1 else f"${price:,.6f}"
                mover_lines.append(f"**{i}. {name} ({symbol})**")
                mover_lines.append(
                    f"현재가 {price_str}, 24시간 {ch24:+.2f}% {direction}, 7일 {ch7d:+.2f}%. 시가총액 {_fmt_num(mcap)}"
                )
                mover_lines.append(f"`24h 변동률 기준 Top {i}`\n")
            sections["주요 변동 코인"] = "\n".join(mover_lines)

        # 6. Top 20 coins table
        sections["시가총액 Top 20"] = format_top_coins_table(top_coins, cmc_source)

        # 7. Trending coins
        sections["트렌딩 코인"] = format_trending_coins(trending, cmc_source)

        # 8. Gainers/Losers
        if gainers or losers:
            sections["급등/급락 코인"] = format_gainers_losers(gainers, losers)
        elif top_coins and cmc_source == "coingecko":
            g_table, l_table = derive_gainers_losers_from_top(top_coins)
            sections["24시간 최대 상승 (Top 20 기준)"] = g_table
            sections["24시간 최대 하락 (Top 20 기준)"] = l_table

        filepath = gen_analysis.create_post(
            title=title,
            content="\n\n".join(f"## {k}\n\n{v}" for k, v in sections.items()),
            date=now,
            tags=["market-report", "crypto", "top-coins", "trending", "daily"],
            source=source_name,
            source_url="https://www.coingecko.com/"
            if cmc_source == "coingecko"
            else "https://coinmarketcap.com/",
            lang="ko",
            slug="daily-crypto-market-report",
        )
        if filepath:
            dedup.mark_seen(title, source_name, today)
            logger.info("Created market report: %s", filepath)

    dedup.save()
    logger.info("=== CoinMarketCap/CoinGecko collection complete ===")
    unique_count = len(
        {
            f"{coin.get('name', '')}|{coin.get('symbol', '')}"
            for coin in top_coins
            if coin.get("name")
        }
    )
    source_count = 1 if top_coins else 0
    log_collection_summary(
        logger,
        collector="collect_coinmarketcap",
        source_count=source_count,
        unique_items=unique_count,
        post_created=1 if filepath else 0,
        started_at=started_at,
        extras={"source": source_name},
    )


if __name__ == "__main__":
    main()
