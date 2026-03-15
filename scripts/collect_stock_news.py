#!/usr/bin/env python3
"""Collect stock market news from multiple sources and generate Jekyll posts.

Sources:
- NewsAPI (stock keywords: KOSPI, S&P 500, stock market)
- Yahoo Finance RSS / yfinance
- KRX news via Google News RSS (Korean stock keywords)
- Alpha Vantage (market data snapshots)
"""

import os
import sys
import time
from datetime import UTC, datetime
from typing import Any, Dict, List

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common.bettafish_analyzer import BettaFishAnalyzer
from common.collector_metrics import log_collection_summary
from common.config import REQUEST_TIMEOUT, get_env, get_kst_now, get_ssl_verify, setup_logging
from common.dedup import DedupEngine
from common.enrichment import _STOCK_SOURCE_CONTEXT, enrich_items
from common.markdown_utils import (
    html_reference_details,
)
from common.mindspider import MindSpider
from common.post_generator import PostGenerator, build_dated_permalink
from common.rss_fetcher import fetch_rss_feed, fetch_rss_feeds_concurrent
from common.signal_composer import SignalComposer
from common.summarizer import ThemeSummarizer
from common.utils import detect_language, request_with_retry

try:
    from common.browser import BrowserSession, is_playwright_available
except ImportError:
    BrowserSession = None  # type: ignore[assignment,misc]

    def is_playwright_available() -> bool:  # type: ignore[misc]
        return False


try:
    from common.browser import extract_google_news_links
except ImportError:
    extract_google_news_links = None

logger = setup_logging("collect_stock_news")

VERIFY_SSL = get_ssl_verify()


def fetch_google_news_browser_stocks(limit: int = 20) -> List[Dict[str, Any]]:
    """Fetch stock news via Google News browser scraping (replaces NewsAPI).

    Falls back to empty list if Playwright is unavailable.
    """
    if not is_playwright_available():
        logger.info("Playwright not available, skipping Google News browser scraping for stocks")
        return []

    if extract_google_news_links is None:
        logger.info("extract_google_news_links not available, skipping")
        return []
    if BrowserSession is None:
        return []

    search_configs = [
        (
            "https://news.google.com/search?q=stock+market+S%26P+500&hl=en-US&gl=US&ceid=US:en",
            ["stock", "market", "en"],
        ),
        (
            "https://news.google.com/search?q=%EC%A3%BC%EC%8B%9D+%EC%BD%94%EC%8A%A4%ED%94%BC+%EC%BD%94%EC%8A%A4%EB%8B%A5&hl=ko&gl=KR&ceid=KR:ko",
            ["stock", "market", "ko"],
        ),
    ]
    all_items: List[Dict[str, Any]] = []

    try:
        with BrowserSession(timeout=30_000) as session:
            for search_url, tags in search_configs:
                try:
                    session.navigate(search_url, wait_until="domcontentloaded", wait_ms=3000)
                    all_items.extend(extract_google_news_links(session, limit, tags))
                except Exception as e:
                    logger.warning("Google News browser scraping failed for %s: %s", tags, e)

        logger.info("Google News Browser stocks: fetched %d items", len(all_items))
    except Exception as e:
        logger.warning("Google News browser session failed: %s", e)

    return all_items


def fetch_financial_rss_feeds() -> List[Dict[str, Any]]:
    """Fetch news from major financial media RSS feeds (concurrent)."""
    feeds = [
        (
            "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114",
            "CNBC Top News",
            ["stock", "cnbc"],
        ),
        (
            "https://feeds.marketwatch.com/marketwatch/topstories/",
            "MarketWatch",
            ["stock", "marketwatch"],
        ),
        (
            "https://www.hankyung.com/feed/all-news",
            "한국경제",
            ["stock", "korean", "한경"],
        ),
        (
            "https://file.mk.co.kr/news/rss/rss_30000001.xml",
            "매일경제",
            ["stock", "korean", "매경"],
        ),
        (
            "https://news.google.com/rss/search?q=site:biz.chosun.com+%EC%A3%BC%EC%8B%9D&hl=ko&gl=KR&ceid=KR:ko",
            "조선비즈",
            ["stock", "korean", "조선비즈"],
        ),
        # Investing.com RSS
        (
            "https://www.investing.com/rss/news.rss",
            "Investing.com",
            ["stock", "investing.com"],
        ),
        # Seeking Alpha
        (
            "https://seekingalpha.com/market_currents.xml",
            "Seeking Alpha",
            ["stock", "seeking-alpha"],
        ),
        # Bloomberg (via Google News proxy)
        (
            "https://news.google.com/rss/search?q=site:bloomberg.com+markets+economy&hl=en-US&gl=US&ceid=US:en",
            "Bloomberg via Google",
            ["stock", "bloomberg"],
        ),
        # Financial Times (via Google News proxy)
        (
            "https://news.google.com/rss/search?q=site:ft.com+markets+economy&hl=en-US&gl=US&ceid=US:en",
            "FT via Google",
            ["stock", "ft"],
        ),
        # 서울경제
        (
            "https://www.sedaily.com/RSS/Economy",
            "서울경제",
            ["stock", "korean", "서울경제"],
        ),
        # 이데일리 증권
        (
            "https://rss.edaily.co.kr/edaily_stock.xml",
            "이데일리 증권",
            ["stock", "korean", "이데일리"],
        ),
    ]
    return fetch_rss_feeds_concurrent(feeds)


def fetch_sector_rotation_feeds() -> List[Dict[str, Any]]:
    """Fetch sector rotation and institutional flow news."""
    feeds = [
        (
            "https://news.google.com/rss/search?q=%22sector+rotation%22+OR+%22sector+performance%22+S%26P+500&hl=en-US&gl=US&ceid=US:en",
            "Sector Rotation",
            ["stock", "sector-rotation"],
        ),
        (
            "https://news.google.com/rss/search?q=%2213F+filing%22+OR+%22institutional+buying%22+OR+%22hedge+fund%22+portfolio&hl=en-US&gl=US&ceid=US:en",
            "Institutional Flow",
            ["stock", "institutional-flow", "13f"],
        ),
        (
            "https://news.google.com/rss/search?q=%22earnings+surprise%22+OR+%22earnings+beat%22+OR+%22revenue+beat%22&hl=en-US&gl=US&ceid=US:en",
            "Earnings Momentum",
            ["stock", "earnings", "momentum"],
        ),
        (
            "https://news.google.com/rss/search?q=IPO+%22initial+public+offering%22+2026&hl=en-US&gl=US&ceid=US:en",
            "IPO Watch",
            ["stock", "ipo"],
        ),
        (
            "https://news.google.com/rss/search?q=%22options+activity%22+OR+%22unusual+options%22+OR+%22put+call+ratio%22&hl=en-US&gl=US&ceid=US:en",
            "Options Activity",
            ["stock", "options"],
        ),
    ]
    return fetch_rss_feeds_concurrent(feeds)


def fetch_google_news_stocks() -> List[Dict[str, Any]]:
    """Fetch stock news from Google News RSS (concurrent)."""
    feeds = [
        (
            "https://news.google.com/rss/search?q=stock+market+S%26P+500&hl=en-US&gl=US&ceid=US:en",
            "Google News Stocks EN",
            ["stock", "market", "english"],
        ),
        (
            "https://news.google.com/rss/search?q=NASDAQ+tech+stocks+AI&hl=en-US&gl=US&ceid=US:en",
            "NASDAQ/Tech",
            ["stock", "nasdaq", "tech"],
        ),
        (
            "https://news.google.com/rss/search?q=Fed+interest+rate+bond+yield&hl=en-US&gl=US&ceid=US:en",
            "Fed/Bond",
            ["stock", "fed", "bond"],
        ),
        (
            "https://news.google.com/rss/search?q=주식+코스피+코스닥&hl=ko&gl=KR&ceid=KR:ko",
            "Google News Stocks KR",
            ["stock", "kospi", "korean"],
        ),
        (
            "https://news.google.com/rss/search?q=삼성전자+SK하이닉스+반도체+주가&hl=ko&gl=KR&ceid=KR:ko",
            "한국 반도체",
            ["stock", "semiconductor", "korean"],
        ),
        (
            "https://news.google.com/rss/search?q=외국인+기관+순매수+순매도&hl=ko&gl=KR&ceid=KR:ko",
            "한국 수급동향",
            ["stock", "flow", "korean"],
        ),
        (
            "https://news.google.com/rss/search?q=한국은행+금리+환율+원달러&hl=ko&gl=KR&ceid=KR:ko",
            "한국 금리/환율",
            ["stock", "rate", "korean"],
        ),
    ]
    return fetch_rss_feeds_concurrent(feeds)


def fetch_yahoo_finance_rss() -> List[Dict[str, Any]]:
    """Fetch from Yahoo Finance RSS feeds."""
    feeds = [
        (
            "https://finance.yahoo.com/news/rssindex",
            "Yahoo Finance",
            ["stock", "finance"],
        ),
    ]
    all_items = []
    for url, name, tags in feeds:
        all_items.extend(fetch_rss_feed(url, name, tags))
    return all_items


def fetch_alpha_vantage_snapshot(api_key: str) -> List[Dict[str, Any]]:
    """Fetch market data snapshot from Alpha Vantage for key indices."""
    if not api_key:
        logger.info("Alpha Vantage API key not set, skipping")
        return []

    symbols = {"SPY": "S&P 500 ETF", "QQQ": "NASDAQ 100 ETF", "DIA": "Dow Jones ETF"}
    items = []

    for symbol, name in symbols.items():
        try:
            url = "https://www.alphavantage.co/query"
            params = {
                "function": "GLOBAL_QUOTE",
                "symbol": symbol,
                "apikey": api_key,
            }
            resp = request_with_retry(url, params=params, timeout=REQUEST_TIMEOUT, verify_ssl=VERIFY_SSL)
            data = resp.json()
            quote = data.get("Global Quote", {})

            if quote:
                price = quote.get("05. price", "N/A")
                change = quote.get("09. change", "N/A")
                change_pct = quote.get("10. change percent", "N/A")

                items.append(
                    {
                        "title": f"{name} ({symbol}): ${price} ({change_pct})",
                        "description": f"{name} ({symbol}) - Price: ${price}, Change: {change} ({change_pct})",
                        "link": f"https://finance.yahoo.com/quote/{symbol}",
                        "published": datetime.now(UTC).isoformat(),
                        "source": "Alpha Vantage",
                        "tags": ["stock", "market-data", symbol.lower()],
                    }
                )
            time.sleep(1)  # Rate limit
        except requests.exceptions.RequestException as e:
            logger.warning("Alpha Vantage fetch failed for %s: %s", symbol, e)

    logger.info("Alpha Vantage: fetched %d snapshots", len(items))
    return items


def fetch_korean_market_data() -> dict:
    """Fetch Korean market data (KOSPI, KOSDAQ, USD/KRW) via yfinance."""
    results = {}
    try:
        import yfinance as yf

        symbols = {
            "^KS11": "KOSPI",
            "^KQ11": "KOSDAQ",
            "KRW=X": "USD/KRW",
        }
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
            except (ValueError, TypeError, AttributeError) as e:
                logger.warning("yfinance %s: %s", symbol, e)
    except ImportError:
        logger.warning("yfinance not installed, skipping Korean market data")
    return results


def main():
    """Main collection routine - consolidated post."""
    logger.info("=== Starting stock news collection ===")
    started_at = time.monotonic()

    alpha_vantage_key = get_env("ALPHA_VANTAGE_API_KEY")

    dedup = DedupEngine("stock_news_seen.json")
    gen = PostGenerator("stock-news")

    now = get_kst_now()
    today = now.strftime("%Y-%m-%d")

    # Collect from all sources
    browser_items = fetch_google_news_browser_stocks()
    google_items = fetch_google_news_stocks()
    yahoo_items = fetch_yahoo_finance_rss()
    alpha_items = fetch_alpha_vantage_snapshot(alpha_vantage_key)

    financial_rss_items = fetch_financial_rss_feeds()
    sector_items = fetch_sector_rotation_feeds()
    all_items = browser_items + google_items + yahoo_items + alpha_items + financial_rss_items + sector_items

    # Fetch Korean market data
    kr_market = fetch_korean_market_data()

    if not all_items:
        logger.warning("No news items collected, skipping stock news post")
        log_collection_summary(
            logger,
            collector="collect_stock_news",
            source_count=0,
            unique_items=0,
            post_created=0,
            started_at=started_at,
        )
        dedup.save()
        return

    # ── Consolidated stock news post ──
    post_title = f"주식 시장 뉴스 종합 - {today}"

    if dedup.is_duplicate_exact(post_title, "consolidated", today):
        logger.info("Consolidated stock post already exists, skipping")
        unique_count = len(
            {
                f"{item.get('title', '')}|{item.get('source', '')}|{item.get('link', '')}"
                for item in all_items
                if item.get("title")
            }
        )
        source_count = len({item.get("source", "") for item in all_items if item.get("source")})
        log_collection_summary(
            logger,
            collector="collect_stock_news",
            source_count=source_count,
            unique_items=unique_count,
            post_created=0,
            started_at=started_at,
        )
        dedup.save()
        return

    # Separate global vs Korean news using detect_language
    global_rows = []
    korean_rows = []
    alpha_vantage_rows = []
    source_links = []

    for item in all_items:
        title = item["title"]
        source = item.get("source", "unknown")
        link = item.get("link", "")

        if source == "Alpha Vantage":
            alpha_vantage_rows.append(item)
            continue

        # Collect links for references section
        if link:
            source_links.append({"title": title, "link": link, "source": source})

        lang = detect_language(title)
        if lang == "ko":
            if link:
                korean_rows.append(f"| {len(korean_rows) + 1} | [**{title}**]({link}) | {source} |")
            else:
                korean_rows.append(f"| {len(korean_rows) + 1} | **{title}** | {source} |")
        else:
            if link:
                global_rows.append(f"| {len(global_rows) + 1} | [**{title}**]({link}) | {source} |")
            else:
                global_rows.append(f"| {len(global_rows) + 1} | **{title}** | {source} |")

    global_count = len(global_rows)
    korean_count = len(korean_rows)

    # Limit to top items
    global_rows = global_rows[:15]
    korean_rows = korean_rows[:10]

    # Data-driven opening with Korean market summary
    opening_parts = [f"**{today}** 주식 시장에서 {len(all_items)}건의 뉴스를 분석했습니다."]
    kr_summary_parts = []
    for name, info in kr_market.items():
        kr_summary_parts.append(f"{name} {info['price']}({info['change_pct']})")
    if kr_summary_parts:
        opening_parts.append(f"한국 시장: {', '.join(kr_summary_parts)}.")
    content_parts = [" ".join(opening_parts) + "\n"]

    # Stat grid - market snapshot
    content_parts.append('<div class="stat-grid">')
    if kr_market:
        for name, info in list(kr_market.items())[:4]:
            content_parts.append(
                f'<div class="stat-item"><span class="stat-value">{info["price"]}</span>'
                f'<span class="stat-label">{name} ({info["change_pct"]})</span></div>'
            )
    else:
        content_parts.append(
            f'<div class="stat-item"><span class="stat-value">{len(all_items)}</span>'
            '<span class="stat-label">수집 뉴스</span></div>'
        )
        content_parts.append(
            f'<div class="stat-item"><span class="stat-value">{global_count}</span>'
            '<span class="stat-label">글로벌</span></div>'
        )
        content_parts.append(
            f'<div class="stat-item"><span class="stat-value">{korean_count}</span>'
            '<span class="stat-label">한국</span></div>'
        )
    content_parts.append("</div>\n")

    # Create summarizer
    summarizer = ThemeSummarizer(all_items)

    # Executive summary (한눈에 보기)
    exec_summary = summarizer.generate_executive_summary(
        category_type="stock",
        extra_data={"kr_market": kr_market},
    )
    if exec_summary:
        content_parts.append(exec_summary)

    summary_points = []
    if korean_count or global_count:
        summary_points.append(f"한국 기사 {korean_count}건, 글로벌 기사 {global_count}건 수집")
    if kr_summary_parts:
        summary_points.append(f"한국 지수: {', '.join(kr_summary_parts)}")
    overall_summary = summarizer.generate_overall_summary_section(extra_data={"summary_points": summary_points})
    if overall_summary:
        content_parts.append(overall_summary)

    # Theme distribution chart
    chart = summarizer.generate_distribution_chart()
    if chart:
        content_parts.append("\n" + chart)

    # Image — market snapshot card
    snapshot_items = []
    # US data from Alpha Vantage
    if not alpha_vantage_rows:
        try:
            import yfinance as yf

            _us_symbols = {"^GSPC": "S&P 500", "^IXIC": "NASDAQ", "^DJI": "다우존스", "^VIX": "VIX"}
            import pandas as pd

            _tickers = yf.download(list(_us_symbols.keys()), period="2d", progress=False, auto_adjust=True)
            _df = pd.DataFrame(_tickers)
            if "Close" not in _df.columns:
                raise KeyError("Close column missing")
            for sym, label in _us_symbols.items():
                try:
                    _hist = pd.Series(pd.to_numeric(_df["Close"][sym], errors="coerce")).dropna()
                    if len(_hist) >= 2:
                        _price = float(_hist.iloc[-1])
                        _prev = float(_hist.iloc[-2])
                        _chg_pct = (_price - _prev) / _prev * 100
                        _sign = "+" if _chg_pct >= 0 else ""
                        snapshot_items.append(
                            {
                                "name": label,
                                "price": f"{_price:,.2f}",
                                "change_pct": f"{_sign}{_chg_pct:.2f}%",
                                "section": "US Market",
                            }
                        )
                except (ValueError, TypeError, IndexError, KeyError) as exc:
                    logger.debug("yfinance symbol %s parse error: %s", sym, exc)
        except ImportError:
            logger.debug("yfinance not available for US market fallback")
        except Exception as e:
            logger.warning("yfinance US market fallback failed: %s", e)
    for item in alpha_vantage_rows:
        desc = item.get("description", "")
        # Parse "Name (SYM) - Price: $X, Change: Y (Z%)"
        try:
            price_part = desc.split("Price:")[1].split(",")[0].strip() if "Price:" in desc else "N/A"
            change_part = ""
            if "(" in desc and desc.endswith(")"):
                change_part = desc.rsplit("(", 1)[1].rstrip(")")
        except (IndexError, ValueError):
            price_part = "N/A"
            change_part = "N/A"
        snapshot_items.append(
            {
                "name": item["title"].split(":")[0].strip() if ":" in item["title"] else item["title"],
                "price": price_part,
                "change_pct": change_part or "N/A",
                "section": "US Market",
            }
        )
    # Korean data
    for name, info in kr_market.items():
        snapshot_items.append(
            {
                "name": name,
                "price": info["price"],
                "change_pct": info["change_pct"],
                "section": "Korean Market",
            }
        )

    snapshot_image_path = ""
    try:
        from common.image_generator import generate_market_snapshot_card

        if snapshot_items:
            img = generate_market_snapshot_card(snapshot_items, today)
            if img:
                fn = os.path.basename(img)
                snapshot_image_path = f"/assets/images/generated/{fn}"
                web_path = "{{ '/assets/images/generated/" + fn + "' | relative_url }}"
                content_parts.append(f"\n![market-snapshot]({web_path})\n")
                logger.info("Generated market snapshot image")
    except ImportError as e:
        logger.debug("Optional dependency unavailable: %s", e)
    except Exception as e:
        logger.warning("Market snapshot image failed: %s", e)

    # Enrich all items with descriptions before themed sections
    enrich_items(all_items, context_map=_STOCK_SOURCE_CONTEXT, max_fetch=40)

    # Themed news sections with description cards
    content_parts.append("\n---\n")
    themed = summarizer.generate_themed_news_sections()
    if themed:
        content_parts.append(themed)
        content_parts.append("\n---\n")

    # Market data snapshot table (improved with emoji direction + Korean data)
    content_parts.append("\n## 시장 데이터 스냅샷\n")
    has_market_data = alpha_vantage_rows or kr_market
    if has_market_data:
        content_parts.append("| 지수/ETF | 가격 | 변동률 |")
        content_parts.append("|----------|------|--------|")
        for item in alpha_vantage_rows:
            title_short = item["title"].split(":")[0].strip() if ":" in item["title"] else item["title"]
            desc = item.get("description", "")
            # Extract change_pct
            change_pct = "N/A"
            if "(" in desc and desc.endswith(")"):
                change_pct = desc.rsplit("(", 1)[1].rstrip(")")
            try:
                pval = float(change_pct.replace("%", "").replace("+", ""))
                icon = "🟢" if pval >= 0 else "🔴"
                change_display = f"{icon} {change_pct}"
            except (ValueError, AttributeError):
                change_display = change_pct
            price_str = "N/A"
            if "Price:" in desc:
                try:
                    price_str = desc.split("Price:")[1].split(",")[0].strip()
                except IndexError:
                    pass
            link = item.get("link", "")
            if link:
                content_parts.append(f"| [**{title_short}**]({link}) | {price_str} | {change_display} |")
                source_links.append(
                    {
                        "title": item["title"],
                        "link": link,
                        "source": item.get("source", ""),
                    }
                )
            else:
                content_parts.append(f"| **{title_short}** | {price_str} | {change_display} |")
        for name, info in kr_market.items():
            try:
                pval = float(info["change_pct"].replace("%", "").replace("+", ""))
                icon = "🟢" if pval >= 0 else "🔴"
            except (ValueError, AttributeError):
                icon = ""
            content_parts.append(f"| **{name}** | {info['price']} | {icon} {info['change_pct']} |")
    # Market insight - data-driven narrative
    content_parts.append("\n## 시장 인사이트\n")
    insight_lines = []
    kospi = kr_market.get("KOSPI")
    kosdaq = kr_market.get("KOSDAQ")
    usdkrw = kr_market.get("USD/KRW")

    # Korean market narrative with sector-level detail
    if kospi:
        try:
            pval = float(kospi["change_pct"].replace("%", "").replace("+", ""))
        except (ValueError, AttributeError):
            pval = 0.0

        if pval > 1.5:
            kr_mood = "강한 상승세로 매수 심리가 우세합니다. 외국인·기관 순매수 여부를 확인할 필요가 있습니다."
        elif pval > 0:
            kr_mood = "소폭 상승하며 안정적 흐름을 보이고 있습니다. 거래량 동반 여부가 추세 지속의 열쇠입니다."
        elif pval > -1.5:
            kr_mood = "소폭 조정 중이나 기술적 지지선 부근에서 반등 가능성이 있습니다."
        else:
            kr_mood = "뚜렷한 하락세로 리스크 관리가 필요한 구간입니다. 프로그램 매도 및 외국인 이탈 규모를 확인하세요."

        insight_lines.append(f"KOSPI **{kospi['price']}** ({kospi['change_pct']}): {kr_mood}")

    if kosdaq:
        try:
            kq_val = float(kosdaq["change_pct"].replace("%", "").replace("+", ""))
        except (ValueError, AttributeError):
            kq_val = 0.0
        kq_note = ""
        if kospi:
            try:
                kp_val = float(kospi["change_pct"].replace("%", "").replace("+", ""))
                gap = kq_val - kp_val
                if gap > 1.0:
                    kq_note = " KOSDAQ이 KOSPI 대비 강세로, 중소형주·성장주 선호 심리가 반영됩니다."
                elif gap < -1.0:
                    kq_note = " KOSDAQ이 KOSPI 대비 약세로, 대형주 중심의 안전 선호 흐름이 나타나고 있습니다."
            except (ValueError, AttributeError):
                pass
        insight_lines.append(f"KOSDAQ **{kosdaq['price']}** ({kosdaq['change_pct']}).{kq_note}")

    if usdkrw:
        try:
            usd_price = float(usdkrw["price"].replace(",", ""))
        except (ValueError, AttributeError):
            usd_price = 0
        if usd_price > 1400:
            fx_note = "1,400원 이상의 고환율 구간으로, 수입 원가 상승과 외국인 매도 압력이 우려됩니다."
        elif usd_price > 1350:
            fx_note = "1,350원대로, 수출 기업에 유리하나 환율 변동성이 커질 수 있습니다."
        elif usd_price > 1300:
            fx_note = "1,300원대로 비교적 안정적이며, 외국인 자금 유입에 긍정적 환경입니다."
        else:
            fx_note = "원화 강세 구간으로, 내수주에 유리하고 수출주는 환차손에 유의해야 합니다."
        insight_lines.append(f"\n**원달러 환율**: **{usdkrw['price']}**원 ({usdkrw['change_pct']}). {fx_note}")

    # US market narrative with direction analysis
    if alpha_vantage_rows:
        us_up = 0
        us_down = 0
        for item in alpha_vantage_rows:
            desc = item.get("description", "")
            if "(" in desc and desc.endswith(")"):
                try:
                    chg = desc.rsplit("(", 1)[1].rstrip(")")
                    chg_val = float(chg.replace("%", "").replace("+", ""))
                    if chg_val >= 0:
                        us_up += 1
                    else:
                        us_down += 1
                except (ValueError, IndexError):
                    pass
        if us_up > us_down:
            us_mood = "미국 주요 지수가 전반적 상승세로, 한국 증시 야간 선물에 긍정적 영향이 예상됩니다."
        elif us_down > us_up:
            us_mood = "미국 지수가 하락 흐름을 보여, 다음 거래일 아시아 시장 개장에 부담이 될 수 있습니다."
        else:
            us_mood = "미국 시장이 혼조세로, 섹터별 차별화된 흐름이 나타나고 있습니다."
        insight_lines.append(f"\n**미국 시장**: ETF {len(alpha_vantage_rows)}종 데이터 수집. {us_mood}")

    # Sector flow from news themes
    top_themes = summarizer.get_top_themes()
    if top_themes:
        _THEME_SECTOR_MAP = {
            "AI/기술": "반도체·IT 섹터",
            "매크로/금리": "금융·은행 섹터",
            "가격/시장": "시장 전반",
            "규제/정책": "금융·핀테크 섹터",
            "정치/정책": "방산·건설·에너지 섹터",
            "DeFi": "블록체인·크립토 관련주",
            "비트코인": "크립토 관련주",
            "이더리움": "블록체인 관련주",
            "에너지": "에너지·유틸리티 섹터",
        }
        sector_notes = []
        for t_name, _t_key, _t_emoji, t_count in top_themes[:3]:
            sector = _THEME_SECTOR_MAP.get(t_name)
            if sector:
                sector_notes.append(f"**{t_name}**({t_count}건) → {sector}")
        if sector_notes:
            insight_lines.append(
                f"\n**섹터별 흐름**: {'; '.join(sector_notes)}. "
                f"뉴스 테마와 연관된 섹터의 거래량·수급 변화를 확인하세요."
            )

    if not insight_lines:
        insight_lines.append("현재 시장 데이터를 충분히 수집하지 못했습니다. API 제한 또는 휴장일일 수 있습니다.")
    insight_lines.append("")
    insight_lines.append(
        "> *본 시장 리포트는 자동 수집된 데이터를 기반으로 생성되었으며, "
        "투자 조언이 아닙니다. 모든 투자 결정은 개인의 판단과 책임 하에 이루어져야 합니다.*"
    )
    content_parts.extend(insight_lines)

    # ── MiroFish-inspired Market Outlook ──
    try:
        signals: dict = {}

        # Momentum from Korean market and Alpha Vantage ETF data
        momentum: dict = {}
        if kospi:
            try:
                kospi_pct = float(kospi["change_pct"].replace("%", "").replace("+", ""))
                momentum["sp500_5d"] = kospi_pct  # use KOSPI as proxy for momentum signal
            except (ValueError, AttributeError):
                pass
        if alpha_vantage_rows:
            etf_pcts = []
            for _item in alpha_vantage_rows:
                _desc = _item.get("description", "")
                if "(" in _desc and _desc.endswith(")"):
                    try:
                        _chg = _desc.rsplit("(", 1)[1].rstrip(")")
                        etf_pcts.append(float(_chg.replace("%", "").replace("+", "")))
                    except (ValueError, IndexError):
                        pass
            if etf_pcts:
                import statistics

                momentum["sp500_5d"] = statistics.mean(etf_pcts)
        if momentum:
            signals["momentum"] = momentum

        # Sentiment from collected news titles
        if all_items:
            _bullish_kws = {"상승", "강세", "rally", "surge", "bull", "급등", "호재", "반등"}
            _bearish_kws = {"하락", "약세", "crash", "bear", "dump", "급락", "폭락", "위기"}
            _positive = sum(1 for _a in all_items if any(kw in _a.get("title", "").lower() for kw in _bullish_kws))
            _negative = sum(1 for _a in all_items if any(kw in _a.get("title", "").lower() for kw in _bearish_kws))
            _total = _positive + _negative
            _score = (_positive - _negative) / _total if _total > 0 else 0.0
            signals["sentiment"] = {"score": _score, "positive": _positive, "negative": _negative}

        if signals:
            composer = SignalComposer()
            result = composer.compose_signals(signals)
            stance = composer.analyze_stance(result)
            content_parts.append("\n" + composer.generate_prediction_markdown(result, stance))

            # MindSpider topic analysis
            if all_items:
                spider = MindSpider()
                news_items_for_spider = [
                    {
                        "title": _a.get("title", ""),
                        "description": _a.get("description", ""),
                        "source": _a.get("source", ""),
                        "category": "stock",
                        "date": now.strftime("%Y-%m-%d"),
                    }
                    for _a in all_items
                    if _a.get("title")
                ]
                if news_items_for_spider:
                    clusters = spider.cluster_topics(news_items_for_spider, max_topics=3)
                    topic_md = spider.generate_topic_summary(clusters)
                    if topic_md:
                        content_parts.append("\n" + topic_md)

                    # BettaFish brief outlook
                    extracted_keywords = spider.extract_keywords(news_items_for_spider, top_n=10)
                    analyzer = BettaFishAnalyzer()
                    bf_report = analyzer.analyze(
                        composite_result=result,
                        topic_clusters=clusters,
                        keywords=extracted_keywords,
                    )
                    brief = analyzer.generate_brief_outlook(bf_report)
                    if brief:
                        content_parts.append("\n### 멀티 관점 요약\n")
                        content_parts.append(brief)

                    # Entity analysis
                    news_items = news_items_for_spider
                    if news_items:
                        entities = spider.extract_entities(news_items)
                        if entities:
                            relations = spider.detect_relations(news_items, entities)
                            entity_report = spider.generate_entity_report(entities, relations)
                            if entity_report:
                                content_parts.append("\n" + entity_report)
    except Exception as exc:
        logger.warning("시장 전망 생성 실패: %s", exc)

    content_parts.append("\n---\n")

    # References section (collapsible)
    if source_links:
        content_parts.append(
            html_reference_details(
                "참고 링크",
                source_links,
                limit=15,
                title_max_len=80,
            )
        )

    # Data collection footer
    content_parts.append(
        '\n<div class="wm-footer-meta">'
        f"<span>수집 시각: {now.strftime('%Y-%m-%d %H:%M')} KST</span>"
        "<span>소스: NewsAPI, Yahoo Finance, Google News, Alpha Vantage</span>"
        "</div>"
    )

    content = "\n".join(content_parts)

    report_permalink = build_dated_permalink("stock-news", today, "daily-stock-news-digest")

    filepath = gen.create_post(
        title=post_title,
        content=content,
        date=now,
        logical_date=today,
        tags=["stock", "market", "daily-digest"],
        source="consolidated",
        lang="ko",
        image=snapshot_image_path,
        extra_frontmatter={"permalink": report_permalink},
        slug="daily-stock-news-digest",
    )
    if filepath:
        dedup.mark_seen(post_title, "consolidated", today)
        logger.info("Created consolidated stock news post: %s", filepath)

    dedup.save()
    logger.info("=== Stock news collection complete ===")
    unique_count = len(
        {
            f"{item.get('title', '')}|{item.get('source', '')}|{item.get('link', '')}"
            for item in all_items
            if item.get("title")
        }
    )
    source_count = len({item.get("source", "") for item in all_items if item.get("source")})
    log_collection_summary(
        logger,
        collector="collect_stock_news",
        source_count=source_count,
        unique_items=unique_count,
        post_created=1 if filepath else 0,
        started_at=started_at,
    )


if __name__ == "__main__":
    main()
