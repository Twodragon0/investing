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
import logging
import requests
import certifi
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common.config import get_env, setup_logging
from common.dedup import DedupEngine
from common.post_generator import PostGenerator
from common.utils import sanitize_string, validate_url, parse_date, detect_language, truncate_text

logger = setup_logging("collect_stock_news")

VERIFY_SSL = certifi.where()
REQUEST_TIMEOUT = 15
USER_AGENT = "Mozilla/5.0 (compatible; InvestingDragon/1.0)"


def fetch_newsapi_stocks(api_key: str, limit: int = 20) -> List[Dict[str, Any]]:
    """Fetch stock news from NewsAPI."""
    if not api_key:
        logger.info("NewsAPI key not set, skipping")
        return []

    queries = [
        ("stock market OR S&P 500 OR NASDAQ", "en"),
        ("KOSPI OR KOSDAQ OR 주식시장", "ko"),
    ]
    all_items = []

    for query, lang in queries:
        params = {
            "q": query,
            "language": lang if lang == "en" else "ko",
            "sortBy": "publishedAt",
            "pageSize": limit,
            "apiKey": api_key,
        }
        try:
            resp = requests.get(
                "https://newsapi.org/v2/everything",
                params=params, timeout=REQUEST_TIMEOUT, verify=VERIFY_SSL,
            )
            resp.raise_for_status()
            data = resp.json()
            for a in data.get("articles", []):
                title = sanitize_string(a.get("title", ""), 300)
                if not title or title == "[Removed]":
                    continue
                all_items.append({
                    "title": title,
                    "description": sanitize_string(a.get("description", ""), 500),
                    "link": a.get("url", ""),
                    "published": a.get("publishedAt", ""),
                    "source": "NewsAPI",
                    "tags": ["stock", "market", lang],
                })
            time.sleep(0.5)
        except requests.exceptions.RequestException as e:
            logger.warning("NewsAPI stocks fetch failed for '%s': %s", query, e)

    logger.info("NewsAPI stocks: fetched %d items", len(all_items))
    return all_items


def fetch_rss_feed(url: str, source_name: str, tags: List[str], limit: int = 15) -> List[Dict[str, Any]]:
    """Fetch news from an RSS feed."""
    try:
        resp = requests.get(
            url, timeout=REQUEST_TIMEOUT, verify=VERIFY_SSL,
            headers={"User-Agent": USER_AGENT},
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "xml")

        items = []
        for item in soup.find_all("item")[:limit]:
            title_el = item.find("title")
            desc_el = item.find("description")
            link_el = item.find("link")
            date_el = item.find("pubDate")

            title = sanitize_string(title_el.get_text(strip=True), 300) if title_el else ""
            if not title:
                continue

            description = ""
            if desc_el:
                raw_desc = desc_el.get_text(strip=True)
                description = sanitize_string(
                    BeautifulSoup(raw_desc, "html.parser").get_text(" ", strip=True), 500
                )

            items.append({
                "title": title,
                "description": description,
                "link": link_el.get_text(strip=True) if link_el else "",
                "published": date_el.get_text(strip=True) if date_el else "",
                "source": source_name,
                "tags": tags,
            })
        logger.info("RSS %s: fetched %d items", source_name, len(items))
        return items
    except requests.exceptions.RequestException as e:
        logger.warning("RSS %s fetch failed: %s", source_name, e)
        return []


def fetch_google_news_stocks() -> List[Dict[str, Any]]:
    """Fetch stock news from Google News RSS."""
    feeds = [
        ("https://news.google.com/rss/search?q=stock+market+S%26P+500&hl=en-US&gl=US&ceid=US:en",
         "Google News Stocks EN", ["stock", "market", "english"]),
        ("https://news.google.com/rss/search?q=주식+코스피+코스닥&hl=ko&gl=KR&ceid=KR:ko",
         "Google News Stocks KR", ["stock", "kospi", "korean"]),
    ]
    all_items = []
    for url, name, tags in feeds:
        all_items.extend(fetch_rss_feed(url, name, tags))
        time.sleep(1)
    return all_items


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
            resp = requests.get(url, params=params, timeout=REQUEST_TIMEOUT, verify=VERIFY_SSL)
            resp.raise_for_status()
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


def main():
    """Main collection routine - consolidated post."""
    logger.info("=== Starting stock news collection ===")

    newsapi_key = get_env("NEWSAPI_API_KEY")
    alpha_vantage_key = get_env("ALPHA_VANTAGE_API_KEY")

    dedup = DedupEngine("stock_news_seen.json")
    gen = PostGenerator("stock-news")

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    now = datetime.now(timezone.utc)

    # Collect from all sources
    newsapi_items = fetch_newsapi_stocks(newsapi_key)
    google_items = fetch_google_news_stocks()
    yahoo_items = fetch_yahoo_finance_rss()
    alpha_items = fetch_alpha_vantage_snapshot(alpha_vantage_key)

    all_items = newsapi_items + google_items + yahoo_items + alpha_items

    # ── Consolidated stock news post ──
    post_title = f"주식 시장 뉴스 종합 - {today}"

    if dedup.is_duplicate(post_title, "consolidated", today):
        logger.info("Consolidated stock post already exists, skipping")
        dedup.save()
        return

    # Separate global vs Korean news using detect_language
    global_rows = []
    korean_rows = []
    alpha_vantage_rows = []

    for item in all_items:
        title = item["title"]
        source = item.get("source", "unknown")

        if source == "Alpha Vantage":
            alpha_vantage_rows.append(item)
            continue

        lang = detect_language(title)
        if lang == "ko":
            korean_rows.append(f"| {len(korean_rows) + 1} | **{title}** | {source} |")
        else:
            global_rows.append(f"| {len(global_rows) + 1} | **{title}** | {source} |")

    content_parts = ["오늘의 주식 시장 뉴스를 종합 정리합니다.\n"]

    # Global stock news
    content_parts.append("## 글로벌 주식 뉴스\n")
    if global_rows:
        content_parts.append("| # | 제목 | 출처 |")
        content_parts.append("|---|------|------|")
        content_parts.extend(global_rows)
    else:
        content_parts.append("*수집된 글로벌 뉴스가 없습니다.*")

    # Korean stock news
    content_parts.append("\n## 한국 주식 뉴스\n")
    if korean_rows:
        content_parts.append("| # | 제목 | 출처 |")
        content_parts.append("|---|------|------|")
        content_parts.extend(korean_rows)
    else:
        content_parts.append("*수집된 한국 주식 뉴스가 없습니다.*")

    # Market data snapshot
    content_parts.append("\n## 시장 데이터 스냅샷\n")
    if alpha_vantage_rows:
        content_parts.append("| 지수/ETF | 가격 | 변동 |")
        content_parts.append("|----------|------|------|")
        for item in alpha_vantage_rows:
            content_parts.append(f"| **{item['title']}** | {item.get('description', '')} | - |")
    else:
        content_parts.append("*Alpha Vantage 데이터를 가져올 수 없습니다.*")

    # Summary
    content_parts.append("\n## 뉴스 요약")
    content_parts.append(f"- 총 수집 뉴스: {len(all_items)}건")

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
