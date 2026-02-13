#!/usr/bin/env python3
"""Collect stock market news from multiple sources and generate Jekyll posts.

Sources:
- NewsAPI (stock keywords: KOSPI, S&P 500, stock market)
- Yahoo Finance RSS / yfinance
- KRX news via Google News RSS (Korean stock keywords)
- Alpha Vantage (market data snapshots)
"""

import sys
import os
import time
import requests
from datetime import datetime, timezone
from typing import List, Dict, Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common.config import get_env, setup_logging, get_ssl_verify
from common.dedup import DedupEngine
from common.post_generator import PostGenerator
from common.utils import sanitize_string, detect_language, request_with_retry
from common.rss_fetcher import fetch_rss_feed, fetch_rss_feeds_concurrent
from common.summarizer import ThemeSummarizer

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
REQUEST_TIMEOUT = 15
USER_AGENT = "Mozilla/5.0 (compatible; InvestingDragon/1.0)"


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

    search_configs = [
        ("https://news.google.com/search?q=stock+market+S%26P+500&hl=en-US&gl=US&ceid=US:en",
         ["stock", "market", "en"]),
        ("https://news.google.com/search?q=%EC%A3%BC%EC%8B%9D+%EC%BD%94%EC%8A%A4%ED%94%BC+%EC%BD%94%EC%8A%A4%EB%8B%A5&hl=ko&gl=KR&ceid=KR:ko",
         ["stock", "market", "ko"]),
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
        ("https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114",
         "CNBC Top News", ["stock", "cnbc"]),
        ("https://feeds.marketwatch.com/marketwatch/topstories/",
         "MarketWatch", ["stock", "marketwatch"]),
        ("https://www.hankyung.com/feed/all-news",
         "한국경제", ["stock", "korean", "한경"]),
        ("http://file.mk.co.kr/news/rss/rss_30000001.xml",
         "매일경제", ["stock", "korean", "매경"]),
        ("https://news.google.com/rss/search?q=site:biz.chosun.com+%EC%A3%BC%EC%8B%9D&hl=ko&gl=KR&ceid=KR:ko",
         "조선비즈", ["stock", "korean", "조선비즈"]),
    ]
    return fetch_rss_feeds_concurrent(feeds)


def fetch_google_news_stocks() -> List[Dict[str, Any]]:
    """Fetch stock news from Google News RSS (concurrent)."""
    feeds = [
        ("https://news.google.com/rss/search?q=stock+market+S%26P+500&hl=en-US&gl=US&ceid=US:en",
         "Google News Stocks EN", ["stock", "market", "english"]),
        ("https://news.google.com/rss/search?q=NASDAQ+tech+stocks+AI&hl=en-US&gl=US&ceid=US:en",
         "NASDAQ/Tech", ["stock", "nasdaq", "tech"]),
        ("https://news.google.com/rss/search?q=Fed+interest+rate+bond+yield&hl=en-US&gl=US&ceid=US:en",
         "Fed/Bond", ["stock", "fed", "bond"]),
        ("https://news.google.com/rss/search?q=주식+코스피+코스닥&hl=ko&gl=KR&ceid=KR:ko",
         "Google News Stocks KR", ["stock", "kospi", "korean"]),
        ("https://news.google.com/rss/search?q=삼성전자+SK하이닉스+반도체+주가&hl=ko&gl=KR&ceid=KR:ko",
         "한국 반도체", ["stock", "semiconductor", "korean"]),
        ("https://news.google.com/rss/search?q=외국인+기관+순매수+순매도&hl=ko&gl=KR&ceid=KR:ko",
         "한국 수급동향", ["stock", "flow", "korean"]),
        ("https://news.google.com/rss/search?q=한국은행+금리+환율+원달러&hl=ko&gl=KR&ceid=KR:ko",
         "한국 금리/환율", ["stock", "rate", "korean"]),
    ]
    return fetch_rss_feeds_concurrent(feeds)


def fetch_yahoo_finance_rss() -> List[Dict[str, Any]]:
    """Fetch from Yahoo Finance RSS feeds."""
    feeds = [
        ("https://finance.yahoo.com/news/rssindex", "Yahoo Finance", ["stock", "finance"]),
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

                items.append({
                    "title": f"{name} ({symbol}): ${price} ({change_pct})",
                    "description": f"{name} ({symbol}) - Price: ${price}, Change: {change} ({change_pct})",
                    "link": f"https://finance.yahoo.com/quote/{symbol}",
                    "published": datetime.now(timezone.utc).isoformat(),
                    "source": "Alpha Vantage",
                    "tags": ["stock", "market-data", symbol.lower()],
                })
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
            except Exception as e:
                logger.warning("yfinance %s: %s", symbol, e)
    except ImportError:
        logger.warning("yfinance not installed, skipping Korean market data")
    return results


def main():
    """Main collection routine - consolidated post."""
    logger.info("=== Starting stock news collection ===")

    alpha_vantage_key = get_env("ALPHA_VANTAGE_API_KEY")

    dedup = DedupEngine("stock_news_seen.json")
    gen = PostGenerator("stock-news")

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    now = datetime.now(timezone.utc)

    # Collect from all sources
    browser_items = fetch_google_news_browser_stocks()
    google_items = fetch_google_news_stocks()
    yahoo_items = fetch_yahoo_finance_rss()
    alpha_items = fetch_alpha_vantage_snapshot(alpha_vantage_key)

    financial_rss_items = fetch_financial_rss_feeds()
    all_items = browser_items + google_items + yahoo_items + alpha_items + financial_rss_items

    # Fetch Korean market data
    kr_market = fetch_korean_market_data()

    if not all_items:
        logger.warning("No news items collected, skipping stock news post")
        dedup.save()
        return

    # ── Consolidated stock news post ──
    post_title = f"주식 시장 뉴스 종합 - {today}"

    if dedup.is_duplicate_exact(post_title, "consolidated", today):
        logger.info("Consolidated stock post already exists, skipping")
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

    # Create summarizer
    summarizer = ThemeSummarizer(all_items)

    # Executive summary (한눈에 보기)
    exec_summary = summarizer.generate_executive_summary(
        category_type="stock",
        extra_data={"kr_market": kr_market},
    )
    if exec_summary:
        content_parts.append(exec_summary)

    # Key summary
    content_parts.append("## 핵심 요약\n")
    content_parts.append(f"- **총 뉴스 건수**: {len(all_items)}건")
    for name, info in kr_market.items():
        icon = "🟢" if not info["change_pct"].startswith("-") else "🔴"
        content_parts.append(f"- **{name}**: {info['price']} ({icon} {info['change_pct']})")

    # 오늘의 핵심 bullet points
    content_parts.append("\n## 오늘의 핵심\n")
    highlights = []
    for name, info in kr_market.items():
        try:
            pval = float(info["change_pct"].replace("%", "").replace("+", ""))
            direction = "상승" if pval >= 0 else "하락"
            highlights.append(f"- **{name}** {info['price']}으로 전일 대비 {info['change_pct']} {direction}")
        except (ValueError, KeyError):
            pass
    # Add theme-based highlights
    top_themes = summarizer.get_top_themes()
    if top_themes:
        for name, key, emoji, count in top_themes[:3]:
            highlights.append(f"- **{name}** 관련 뉴스에 주목할 필요가 있습니다.")
    if not highlights:
        highlights.append(f"- 총 {len(all_items)}건의 뉴스가 수집되었습니다.")
    content_parts.extend(highlights)

    # Theme distribution chart
    chart = summarizer.generate_distribution_chart()
    if chart:
        content_parts.append("\n" + chart)

    # Image — market snapshot card
    snapshot_items = []
    # US data from Alpha Vantage
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
        snapshot_items.append({
            "name": item["title"].split(":")[0].strip() if ":" in item["title"] else item["title"],
            "price": price_part,
            "change_pct": change_part or "N/A",
            "section": "US Market",
        })
    # Korean data
    for name, info in kr_market.items():
        snapshot_items.append({
            "name": name,
            "price": info["price"],
            "change_pct": info["change_pct"],
            "section": "Korean Market",
        })

    try:
        from common.image_generator import generate_market_snapshot_card
        if snapshot_items:
            img = generate_market_snapshot_card(snapshot_items, today)
            if img:
                fn = os.path.basename(img)
                web_path = "{{ '/assets/images/generated/" + fn + "' | relative_url }}"
                content_parts.append(f"\n![market-snapshot]({web_path})\n")
                logger.info("Generated market snapshot image")
    except ImportError:
        pass
    except Exception as e:
        logger.warning("Market snapshot image failed: %s", e)

    # Themed news sections
    content_parts.append("\n---\n")
    themed = summarizer.generate_themed_news_sections()
    if themed:
        content_parts.append(themed)
        content_parts.append("\n---\n")

    # Global stock news (only show if data exists)
    if global_rows:
        content_parts.append("## 글로벌 주식 뉴스\n")
        content_parts.append("| # | 제목 | 출처 |")
        content_parts.append("|---|------|------|")
        content_parts.extend(global_rows)

    # Korean stock news (only show if data exists)
    if korean_rows:
        content_parts.append("\n## 한국 주식 뉴스\n")
        content_parts.append("| # | 제목 | 출처 |")
        content_parts.append("|---|------|------|")
        content_parts.extend(korean_rows)

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
                source_links.append({"title": item["title"], "link": link, "source": item.get("source", "")})
            else:
                content_parts.append(f"| **{title_short}** | {price_str} | {change_display} |")
        for name, info in kr_market.items():
            try:
                pval = float(info["change_pct"].replace("%", "").replace("+", ""))
                icon = "🟢" if pval >= 0 else "🔴"
            except (ValueError, AttributeError):
                icon = ""
            content_parts.append(f"| **{name}** | {info['price']} | {icon} {info['change_pct']} |")
    else:
        content_parts.append("> 시장 데이터를 일시적으로 가져올 수 없습니다. 아래 링크에서 직접 확인하세요.\n")
        content_parts.append("- [Yahoo Finance - S&P 500](https://finance.yahoo.com/quote/%5EGSPC/)")
        content_parts.append("- [네이버 금융 - KOSPI](https://finance.naver.com/sise/sise_index.naver?code=KOSPI)")

    # Market insight
    content_parts.append("\n## 시장 인사이트\n")
    insight_lines = []
    kospi = kr_market.get("KOSPI")
    usdkrw = kr_market.get("USD/KRW")
    if kospi:
        insight_lines.append(f"한국 증시는 KOSPI **{kospi['price']}** ({kospi['change_pct']})으로 마감했습니다.")
    if usdkrw:
        insight_lines.append(f"원달러 환율은 **{usdkrw['price']}**원으로, 환율 변동이 외국인 투자 심리에 영향을 줄 수 있습니다.")
    if alpha_vantage_rows:
        insight_lines.append(f"미국 시장에서 주요 ETF {len(alpha_vantage_rows)}종의 데이터가 수집되었습니다.")
    if not insight_lines:
        insight_lines.append("현재 시장 데이터를 충분히 수집하지 못했습니다. API 제한 또는 휴장일일 수 있습니다.")
    insight_lines.append("")
    insight_lines.append("> *본 시장 리포트는 자동 수집된 데이터를 기반으로 생성되었으며, 투자 조언이 아닙니다. 모든 투자 결정은 개인의 판단과 책임 하에 이루어져야 합니다.*")
    content_parts.extend(insight_lines)

    content_parts.append("\n---\n")

    # References section
    if source_links:
        content_parts.append("\n## 참고 링크\n")
        seen_links = set()
        ref_count = 1
        for ref in source_links[:20]:
            if ref["link"] not in seen_links:
                seen_links.add(ref["link"])
                content_parts.append(f"{ref_count}. [{ref['title'][:80]}]({ref['link']}) - {ref['source']}")
                ref_count += 1

    # Data collection footer
    content_parts.append(f"\n---\n**데이터 수집 시각**: {now.strftime('%Y-%m-%d %H:%M')} UTC")

    content = "\n".join(content_parts)

    filepath = gen.create_post(
        title=post_title,
        content=content,
        date=now,
        tags=["stock", "market", "daily-digest"],
        source="consolidated",
        lang="ko",
        slug="daily-stock-news-digest",
    )
    if filepath:
        dedup.mark_seen(post_title, "consolidated", today)
        logger.info("Created consolidated stock news post: %s", filepath)

    dedup.save()
    logger.info("=== Stock news collection complete ===")


if __name__ == "__main__":
    main()
