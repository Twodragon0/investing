#!/usr/bin/env python3
"""Collect cryptocurrency news from multiple sources and generate Jekyll posts.

Sources:
- CryptoPanic API (hot news)
- NewsAPI (crypto keywords)
- Google News RSS (Korean/English crypto)
- Exchange announcements (OKX, Binance, Bybit public APIs)
- Rekt News (security incidents -> security-alerts category)
"""

import os
import re
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from typing import Any, Dict, List

import requests

# Add scripts directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common.collector_metrics import log_collection_summary
from common.config import (
    REQUEST_TIMEOUT,
    USER_AGENT,
    get_env,
    get_ssl_verify,
    setup_logging,
)
from common.dedup import DedupEngine
from common.enrichment import _CRYPTO_SOURCE_CONTEXT, enrich_items
from common.markdown_utils import (
    html_reference_details,
    html_source_tag,
    markdown_link,
    markdown_table,
    smart_truncate,
)
from common.post_generator import PostGenerator
from common.rss_fetcher import fetch_rss_feed, fetch_rss_feeds_concurrent
from common.summarizer import ThemeSummarizer
from common.utils import sanitize_string

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

logger = setup_logging("collect_crypto_news")

VERIFY_SSL = get_ssl_verify()


def fetch_cryptopanic(api_key: str, limit: int = 20) -> List[Dict[str, Any]]:
    """Fetch hot news from CryptoPanic API."""
    if not api_key:
        logger.info("CryptoPanic API key not set, skipping")
        return []

    url = "https://cryptopanic.com/api/v1/posts/"
    params = {"auth_token": api_key, "public": "true", "filter": "hot", "kind": "news"}

    try:
        resp = requests.get(url, params=params, timeout=REQUEST_TIMEOUT, verify=VERIFY_SSL)
        resp.raise_for_status()
        data = resp.json()
        results = data.get("results", [])
        if not isinstance(results, list):
            return []

        items = []
        for r in results[:limit]:
            items.append(
                {
                    "title": sanitize_string(r.get("title", ""), 300),
                    "description": sanitize_string(
                        r.get("metadata", {}).get("description", r.get("title", "")),
                        500,
                    ),
                    "link": r.get("url", ""),
                    "published": r.get("published_at", ""),
                    "source": "CryptoPanic",
                    "tags": ["crypto", "hot-news"],
                }
            )
        logger.info("CryptoPanic: fetched %d items", len(items))
        return items
    except requests.exceptions.RequestException as e:
        logger.warning("CryptoPanic fetch failed: %s", e)
        return []


def fetch_google_news_browser(limit: int = 20) -> List[Dict[str, Any]]:
    """Fetch crypto news via Google News browser scraping (replaces NewsAPI).

    Falls back to empty list if Playwright is unavailable.
    """
    if extract_google_news_links is None:
        logger.info("extract_google_news_links not available, skipping")
        return []
    if not is_playwright_available():
        logger.info("Playwright not available, skipping Google News browser scraping")
        return []
    if BrowserSession is None:
        return []

    search_url = "https://news.google.com/search?q=cryptocurrency+bitcoin&hl=en-US&gl=US&ceid=US:en"
    items: List[Dict[str, Any]] = []

    try:
        with BrowserSession(timeout=30_000) as session:
            session.navigate(search_url, wait_until="domcontentloaded", wait_ms=3000)
            items = extract_google_news_links(session, limit, ["crypto", "news"])

        logger.info("Google News Browser: fetched %d items", len(items))
    except Exception as e:
        logger.warning("Google News browser scraping failed: %s", e)

    return items


def fetch_crypto_rss_feeds() -> List[Dict[str, Any]]:
    """Fetch news from major crypto media RSS feeds (concurrent)."""
    feeds = [
        (
            "https://www.coindesk.com/arc/outboundfeeds/rss",
            "CoinDesk",
            ["crypto", "coindesk"],
        ),
        ("https://cointelegraph.com/rss", "Cointelegraph", ["crypto", "cointelegraph"]),
        ("https://decrypt.co/feed", "Decrypt", ["crypto", "decrypt"]),
        (
            "https://bitcoinmagazine.com/.rss/full/",
            "Bitcoin Magazine",
            ["crypto", "bitcoin"],
        ),
    ]
    all_items = fetch_rss_feeds_concurrent(feeds)
    # The Block — may block requests, wrap with extra try/except
    try:
        all_items.extend(
            fetch_rss_feed(
                "https://www.theblock.co/rss",
                "The Block",
                ["crypto", "theblock"],
            )
        )
    except Exception as e:
        logger.warning("The Block RSS failed: %s", e)
    return all_items


def fetch_google_news_crypto() -> List[Dict[str, Any]]:
    """Fetch crypto news from Google News RSS (English + Korean, concurrent)."""
    feeds = [
        (
            "https://news.google.com/rss/search?q=cryptocurrency&hl=en-US&gl=US&ceid=US:en",
            "Google News EN",
            ["crypto", "english"],
        ),
        (
            "https://news.google.com/rss/search?q=암호화폐+비트코인&hl=ko&gl=KR&ceid=KR:ko",
            "Google News KR",
            ["crypto", "korean", "비트코인"],
        ),
    ]
    return fetch_rss_feeds_concurrent(feeds)


def fetch_google_news_security() -> List[Dict[str, Any]]:
    """Fetch blockchain security news from Google News RSS (concurrent)."""
    feeds = [
        (
            "https://news.google.com/rss/search?q=blockchain+hack+exploit+security&hl=en-US&gl=US&ceid=US:en",
            "Blockchain Security EN",
            ["security", "hack", "english"],
        ),
        (
            "https://news.google.com/rss/search?q=crypto+hack+DeFi+exploit&hl=en-US&gl=US&ceid=US:en",
            "DeFi Security EN",
            ["security", "defi", "exploit"],
        ),
        (
            "https://news.google.com/rss/search?q=블록체인+해킹+보안+취약점&hl=ko&gl=KR&ceid=KR:ko",
            "블록체인 보안 KR",
            ["security", "hack", "korean"],
        ),
    ]
    all_items = fetch_rss_feeds_concurrent(feeds)
    for item in all_items:
        item["category_override"] = "security-alerts"
    return all_items


def _scrape_binance_page(session) -> List[Dict[str, Any]]:
    """Scrape Binance announcements from an open browser session."""
    items: List[Dict[str, Any]] = []
    seen_titles: set = set()
    session.navigate(
        "https://www.binance.com/en/support/announcement",
        wait_until="domcontentloaded",
        wait_ms=5000,
    )
    links = session.extract_elements("a[href*='/support/announcement/']")
    for link_el in links:
        if len(items) >= 15:
            break
        try:
            raw_text = link_el.inner_text().strip()
            # Binance link elements concatenate heading and description text;
            # take only the first non-empty line as the title.
            first_line = next(
                (line.strip() for line in raw_text.splitlines() if line.strip()),
                raw_text,
            )
            title = sanitize_string(first_line, 300)
            href = link_el.get_attribute("href") or ""
            if not title or len(title) < 5 or title in seen_titles:
                continue
            seen_titles.add(title)
            if href and not href.startswith("http"):
                href = "https://www.binance.com" + href
            if "/detail/" not in href:
                continue
            items.append(
                {
                    "title": title,
                    "description": "",
                    "link": href,
                    "published": "",
                    "source": "Binance",
                    "tags": ["crypto", "exchange", "binance"],
                }
            )
        except (AttributeError, TypeError) as e:
            logger.debug("Binance link parse error: %s", e)
            continue
    return items


def _fetch_binance_browser() -> List[Dict[str, Any]]:
    """Scrape Binance announcements page with Playwright."""
    if not is_playwright_available():
        return []
    if BrowserSession is None:
        return []

    try:
        with BrowserSession(timeout=30_000) as session:
            items = _scrape_binance_page(session)
        logger.info("Binance Browser: fetched %d announcements", len(items))
    except Exception as e:
        logger.warning("Binance browser scraping failed: %s", e)
        items = []
    return items


def _fetch_binance_bapi() -> List[Dict[str, Any]]:
    """Fetch Binance announcements via BAPI (legacy fallback)."""
    items: List[Dict[str, Any]] = []
    try:
        url = "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query"
        params = {"type": 1, "pageNo": 1, "pageSize": 10}
        resp = requests.get(
            url,
            params=params,
            timeout=REQUEST_TIMEOUT,
            verify=VERIFY_SSL,
            headers={"User-Agent": USER_AGENT},
        )
        resp.raise_for_status()
        data = resp.json()
        catalogs = data.get("data", {}).get("catalogs", [])
        for catalog in catalogs:
            for article in catalog.get("articles", [])[:5]:
                title = sanitize_string(article.get("title", ""), 300)
                if title:
                    release_date = article.get("releaseDate")
                    date_str = ""
                    if release_date:
                        try:
                            date_str = datetime.fromtimestamp(release_date / 1000, tz=UTC).isoformat()
                        except (ValueError, OSError):
                            pass
                    code = article.get("code", "")
                    link = (
                        f"https://www.binance.com/en/support/announcement/detail/{code}"
                        if code
                        else "https://www.binance.com/en/support/announcement"
                    )
                    items.append(
                        {
                            "title": title,
                            "description": "",
                            "link": link,
                            "published": date_str,
                            "source": "Binance",
                            "tags": ["crypto", "exchange", "binance"],
                        }
                    )
        logger.info("Binance BAPI: fetched %d announcements", len(items))
    except requests.exceptions.RequestException as e:
        logger.warning("Binance BAPI fetch failed: %s", e)
    return items


def fetch_exchange_announcements() -> List[Dict[str, Any]]:
    """Fetch announcements from major exchanges.

    Tries Playwright browser scraping first, falls back to BAPI.
    """
    items = _fetch_binance_browser()
    if not items:
        items = _fetch_binance_bapi()
    return items


def fetch_rekt_news(limit: int = 10) -> List[Dict[str, Any]]:
    """Fetch security incidents from Rekt News via RSS feed."""
    items: List[Dict[str, Any]] = []

    try:
        rss_items = fetch_rss_feed(
            "https://rekt.news/rss/feed.xml",
            "Rekt News",
            ["security", "hack", "rekt"],
        )
        for item in rss_items[:limit]:
            item["title"] = f"[Security] {item['title']}"
            item["category_override"] = "security-alerts"
            items.append(item)
        logger.info("Rekt News RSS: fetched %d incidents", len(items))
    except Exception as e:
        logger.warning("Rekt News RSS failed: %s", e)

    return items


def _fetch_browser_sources() -> tuple:
    """Fetch Google News and Binance in a single browser session."""
    google_items: List[Dict[str, Any]] = []
    binance_items: List[Dict[str, Any]] = []

    if not is_playwright_available():
        return google_items, binance_items
    if extract_google_news_links is None:
        return google_items, binance_items
    if BrowserSession is None:
        return google_items, binance_items

    try:
        with BrowserSession(timeout=30_000) as session:
            # Google News
            try:
                session.navigate(
                    "https://news.google.com/search?q=cryptocurrency+bitcoin&hl=en-US&gl=US&ceid=US:en",
                    wait_until="domcontentloaded",
                    wait_ms=3000,
                )
                google_items = extract_google_news_links(session, 20, ["crypto", "news"])
                logger.info("Google News Browser: fetched %d items", len(google_items))
            except Exception as e:
                logger.warning("Google News browser scraping failed: %s", e)

            # Binance announcements (공유 세션 재사용)
            try:
                binance_items = _scrape_binance_page(session)
                logger.info("Binance Browser: fetched %d announcements", len(binance_items))
            except Exception as e:
                logger.warning("Binance browser scraping failed: %s", e)
    except Exception as e:
        logger.warning("Browser session failed: %s", e)

    return google_items, binance_items


def main():
    """Main collection routine - consolidated posts."""
    logger.info("=== Starting crypto news collection ===")
    started_at = time.monotonic()

    cryptopanic_key = get_env("CRYPTOPANIC_API_KEY")

    dedup = DedupEngine("crypto_news_seen.json")
    crypto_gen = PostGenerator("crypto-news")
    security_gen = PostGenerator("security-alerts")

    today = datetime.now(UTC).strftime("%Y-%m-%d")
    now = datetime.now(UTC)

    all_items = []

    # Collect from all sources
    all_items.extend(fetch_cryptopanic(cryptopanic_key))

    # Use combined browser session for Google News and Binance
    browser_google, browser_binance = _fetch_browser_sources()
    all_items.extend(browser_google)

    all_items.extend(fetch_google_news_crypto())
    all_items.extend(fetch_crypto_rss_feeds())

    # Exchange: browser items first, BAPI fallback
    exchange_items = browser_binance if browser_binance else _fetch_binance_bapi()
    enrich_items(exchange_items, _CRYPTO_SOURCE_CONTEXT, fetch_url=True, max_fetch=10)
    all_items.extend(exchange_items)

    # Enrich remaining items (RSS, CryptoPanic, Google News browser)
    enrich_items(all_items, _CRYPTO_SOURCE_CONTEXT, fetch_url=True, max_fetch=10)

    # Security news from multiple sources -> security-alerts category
    rekt_items = fetch_rekt_news()
    google_security_items = fetch_google_news_security()
    enrich_items(rekt_items, _CRYPTO_SOURCE_CONTEXT, fetch_url=False)
    enrich_items(google_security_items, _CRYPTO_SOURCE_CONTEXT, fetch_url=True, max_fetch=5)

    created_count = 0

    # ── Post A: consolidated crypto news briefing ──
    post_a_title = f"암호화폐 뉴스 브리핑 - {today}"

    if not all_items:
        logger.warning("No news items collected, skipping crypto news post")
    if all_items and not dedup.is_duplicate_exact(post_a_title, "consolidated", today):
        # Separate news items from exchange announcements
        news_rows = []
        exchange_rows = []
        source_counter = Counter()
        source_links = []

        for item in all_items:
            title = item["title"]
            source = item.get("source", "unknown")
            link = item.get("link", "")
            source_counter[source] += 1

            # Collect links for references section
            if link:
                source_links.append({"title": title, "link": link, "source": source})

            if source in ("Binance", "OKX", "Bybit"):
                exchange_rows.append({"title": title, "source": source, "link": link})
            else:
                news_rows.append({"title": title, "source": source, "link": link})

        # Limit to top items
        news_rows = news_rows[:15]
        exchange_rows = exchange_rows[:10]

        # Keyword frequency analysis
        keyword_targets = [
            "bitcoin",
            "ethereum",
            "regulation",
            "etf",
            "defi",
            "nft",
            "ai",
        ]
        all_titles_lower = " ".join(item["title"].lower() for item in all_items)
        keyword_hits = {
            kw: len(re.findall(r"\b" + kw + r"\b", all_titles_lower, re.IGNORECASE)) for kw in keyword_targets
        }
        top_keywords = [(kw, cnt) for kw, cnt in sorted(keyword_hits.items(), key=lambda x: -x[1]) if cnt > 0]

        # Create theme summarizer for reuse (before opening)
        summarizer = ThemeSummarizer(all_items)

        # Get top themes for opening
        top_themes = summarizer.get_top_themes()
        theme_names = [t[0] for t in top_themes] if top_themes else []
        if theme_names:
            themes_str = ", ".join(theme_names[:3])
            content_parts = [
                f"**{today}** 암호화폐 시장에서 {len(all_items)}건의 뉴스를 분석했습니다. 오늘은 **{themes_str}** 관련 소식이 주목됩니다.\n"
            ]
        else:
            content_parts = [f"**{today}** 암호화폐 시장에서 {len(all_items)}건의 뉴스를 분석했습니다.\n"]

        # Distribution chart
        dist_chart = summarizer.generate_distribution_chart()
        if dist_chart:
            content_parts.append("---\n")
            content_parts.append(dist_chart)
            content_parts.append("\n---\n")

        # Executive summary (한눈에 보기)
        exec_summary = summarizer.generate_executive_summary(
            category_type="crypto",
            extra_data={"top_keywords": top_keywords},
        )
        if exec_summary:
            content_parts.append(exec_summary)

        summary_points = []
        if exchange_rows:
            summary_points.append(f"거래소 공지 {len(exchange_rows)}건 포함")
        overall_summary = summarizer.generate_overall_summary_section(
            extra_data={
                "top_keywords": top_keywords,
                "source_counter": source_counter,
                "summary_points": summary_points,
            }
        )
        if overall_summary:
            content_parts.append(overall_summary)

        # Image — news briefing card (replaces simple bar chart)
        briefing_image = None
        try:
            from common.image_generator import generate_news_briefing_card

            # Build theme data for the card
            card_themes = []
            for t_name, t_key, t_emoji, t_count in top_themes[:5]:
                # Extract keywords from theme articles
                t_articles = summarizer._theme_articles.get(t_key, [])
                t_keywords = []
                for art in t_articles[:5]:
                    words = re.findall(r"[a-zA-Z가-힣]{4,}", art.get("title", ""))
                    t_keywords.extend(words[:2])
                # Deduplicate
                seen_kw = set()
                unique_kw = []
                for kw in t_keywords:
                    if kw.lower() not in seen_kw:
                        seen_kw.add(kw.lower())
                        unique_kw.append(kw)
                card_themes.append(
                    {
                        "name": t_name,
                        "emoji": t_emoji,
                        "count": t_count,
                        "keywords": unique_kw[:4],
                    }
                )

            # Check for P0 alerts
            priority_items = summarizer.classify_priority()
            p0_alerts = [item.get("title", "") for item in priority_items.get("P0", [])[:2]]

            img = generate_news_briefing_card(
                card_themes,
                today,
                category="Crypto News Briefing",
                total_count=len(all_items),
                urgent_alerts=p0_alerts if p0_alerts else None,
                filename=f"news-briefing-crypto-{today}.png",
            )
            if img:
                briefing_image = img
                fn = os.path.basename(img)
                web_path = "{{ '/assets/images/generated/" + fn + "' | relative_url }}"
                content_parts.append(f"\n![news-briefing]({web_path})\n")
                logger.info("Generated news briefing card")
        except ImportError as e:
            logger.debug("Optional dependency unavailable: %s", e)
        except Exception as e:
            logger.warning("News briefing card failed: %s", e)

        if not briefing_image:
            try:
                from common.image_generator import generate_news_summary_card

                source_rows = [{"name": name, "count": count} for name, count in source_counter.most_common(8)]
                summary_img = generate_news_summary_card(source_rows, today)
                if summary_img:
                    briefing_image = summary_img
                    fn = os.path.basename(summary_img)
                    web_path = "{{ '/assets/images/generated/" + fn + "' | relative_url }}"
                    content_parts.append(f"\n![news-summary]({web_path})\n")
                    logger.info("Generated news summary card")
            except ImportError as e:
                logger.debug("Optional dependency unavailable: %s", e)
            except Exception as e:
                logger.warning("News summary card failed: %s", e)

        # Main news - theme-based sections with description cards
        themed_sections = summarizer.generate_themed_news_sections()
        if themed_sections:
            content_parts.append(themed_sections)
        else:
            # Fallback to flat table if themed sections are empty
            content_parts.append("## 주요 뉴스\n")
            if news_rows:
                table_rows = []
                for i, row in enumerate(news_rows, 1):
                    title_cell = f"**{row['title']}**"
                    if row["link"]:
                        title_cell = markdown_link(title_cell, row["link"])
                    table_rows.append((i, title_cell, row["source"]))
                content_parts.append(markdown_table(["#", "제목", "출처"], table_rows))
            else:
                content_parts.append("*수집된 뉴스가 없습니다.*")

        # Exchange announcements with descriptions
        if exchange_rows:
            content_parts.append("\n## 거래소 공지사항\n")
            shown_exchange = 0
            for item in all_items:
                if item.get("source") not in ("Binance", "OKX", "Bybit"):
                    continue
                title = item["title"]
                link = item.get("link", "")
                source = item.get("source", "")
                description = item.get("description", "").strip()
                if link:
                    content_parts.append(f"**{shown_exchange + 1}. [{title}]({link})**")
                else:
                    content_parts.append(f"**{shown_exchange + 1}. {title}**")
                if description and description != title:
                    desc_text = description[:120]
                    if len(description) > 120:
                        desc_text += "..."
                    content_parts.append(f"{desc_text}")
                else:
                    content_parts.append(f"{source} 거래소 공지사항입니다.")
                content_parts.append(f"`거래소: {source}`\n")
                shown_exchange += 1
                if shown_exchange >= 10:
                    break

        # Insight section - data-driven cross-analysis
        content_parts.append("\n## 오늘의 인사이트\n")
        insight_lines = []

        # Extract price mentions from titles for concrete analysis
        price_mentions = []
        listing_mentions = []
        delisting_mentions = []
        for item in all_items:
            title_lower = item.get("title", "").lower()
            # Extract BTC/ETH price references
            price_match = re.findall(r"\$[\d,]+(?:\.\d+)?[kKmMbB]?", item.get("title", ""))
            if price_match:
                price_mentions.extend(price_match)
            # Detect listing/delisting announcements
            if any(kw in title_lower for kw in ["listing", "상장", "list"]):
                if "delist" not in title_lower and "상장폐지" not in title_lower:
                    listing_mentions.append(item.get("title", "")[:80])
            if any(kw in title_lower for kw in ["delist", "상장폐지"]):
                delisting_mentions.append(item.get("title", "")[:80])

        # Theme cross-analysis with diverse templates
        _CROSS_TEMPLATES = [
            (
                "규제/정책",
                "비트코인",
                "규제 논의와 비트코인 움직임이 동시에 포착되어, 정책 방향에 따른 가격 변동 가능성이 높습니다.",
            ),
            (
                "비트코인",
                "가격/시장",
                "비트코인 관련 뉴스와 시장 가격 움직임이 함께 부각되어, 단기 변동성 확대 구간에 진입한 것으로 보입니다.",
            ),
            (
                "DeFi",
                "이더리움",
                "DeFi 프로토콜과 이더리움 생태계가 동시에 주목받고 있어, L2 확장 및 TVL 변동에 유의해야 합니다.",
            ),
            (
                "거래소",
                "가격/시장",
                "거래소 관련 소식과 시장 가격 변동이 맞물려 있어, 상장·이벤트에 따른 거래량 변화를 주시해야 합니다.",
            ),
            (
                "보안/해킹",
                "DeFi",
                "보안 사고와 DeFi 프로토콜 이슈가 함께 보고되어, 스마트 컨트랙트 리스크 점검이 필요한 시점입니다.",
            ),
            (
                "AI/기술",
                "비트코인",
                "AI·기술 혁신과 비트코인이 함께 부각되어, 기술 기반 시장 내러티브가 형성되고 있습니다.",
            ),
            (
                "정치/정책",
                "매크로/금리",
                "정치적 이벤트와 금리·매크로 지표가 동시에 움직여, 글로벌 유동성 변화에 따른 자산 재배치 가능성이 있습니다.",
            ),
            (
                "NFT/Web3",
                "이더리움",
                "NFT/Web3 활동과 이더리움 생태계 소식이 겹치며, 가스비 변동과 신규 프로젝트 론칭에 주목해야 합니다.",
            ),
        ]

        if top_themes and len(top_themes) >= 2:
            t1_name, t1_key, t1_emoji, t1_count = top_themes[0]
            t2_name, t2_key, t2_emoji, t2_count = top_themes[1]

            # Find matching cross-analysis template
            cross_text = None
            for tpl_a, tpl_b, tpl_text in _CROSS_TEMPLATES:
                if (t1_name == tpl_a and t2_name == tpl_b) or (t1_name == tpl_b and t2_name == tpl_a):
                    cross_text = tpl_text
                    break

            if not cross_text:
                # Concentration-based analysis
                total_themed = t1_count + t2_count
                concentration = total_themed / max(len(all_items), 1) * 100
                if concentration > 60:
                    cross_text = (
                        f"전체 뉴스의 {concentration:.0f}%가 이 두 테마에 집중되어 있어, "
                        f"시장 참여자들의 관심이 뚜렷하게 쏠리고 있습니다."
                    )
                elif concentration > 40:
                    cross_text = (
                        f"두 테마가 전체의 {concentration:.0f}%를 차지하며 오늘 시장의 주요 서사를 형성하고 있습니다."
                    )
                else:
                    cross_text = (
                        "다양한 테마가 분산되어 있지만, "
                        "이 두 테마의 교차점에서 투자 기회나 리스크 신호가 나타날 수 있습니다."
                    )

            insight_lines.append(
                f"**{t1_emoji} {t1_name}**({t1_count}건)과 "
                f"**{t2_emoji} {t2_name}**({t2_count}건)이 오늘의 핵심 테마입니다. "
                f"{cross_text}"
            )
            # Add distinct top articles (avoid repeating same title)
            seen_insight_titles: set = set()
            for theme_key in [t1_key, t2_key]:
                articles = summarizer._theme_articles.get(theme_key, [])
                for art in articles:
                    top_title = art.get("title", "")
                    if top_title and top_title not in seen_insight_titles:
                        seen_insight_titles.add(top_title)
                        insight_lines.append(f"- 주요 기사: *{top_title[:100]}*")
                        break
        elif top_themes:
            t = top_themes[0]
            ratio = t[3] / max(len(all_items), 1) * 100
            insight_lines.append(
                f"**{t[2]} {t[0]}** 테마가 {t[3]}건(전체의 {ratio:.0f}%)으로 오늘 시장 논의를 주도하고 있습니다."
            )
        else:
            insight_lines.append(
                f"오늘 {len(source_counter)}개 출처에서 {len(all_items)}건의 뉴스가 "
                f"수집되었으나 뚜렷한 테마 집중은 관찰되지 않았습니다."
            )

        # Price mentions analysis
        if price_mentions:
            insight_lines.append(
                f"\n**가격 언급**: 뉴스 제목에서 {len(price_mentions)}건의 가격 데이터가 포착되었습니다"
                f" ({', '.join(price_mentions[:5])}). 구체적 가격대가 언급되는 것은 "
                f"시장의 가격 민감도가 높다는 신호입니다."
            )

        # Keyword monitoring with trend context
        if top_keywords:
            monitoring_kws = ", ".join(f"**{kw}**({cnt}회)" for kw, cnt in top_keywords[:3])
            top_kw = top_keywords[0][0]
            kw_context_map = {
                "bitcoin": "BTC 가격 및 네트워크 활동이 시장의 중심 화두",
                "ethereum": "이더리움 생태계 변화에 대한 관심 집중",
                "regulation": "규제 환경 변화에 대한 경계감 상승",
                "etf": "ETF 관련 자금 유입/유출이 가격에 직접 영향",
                "defi": "DeFi 프로토콜 TVL 및 수익률 변동 주시 필요",
                "ai": "AI 관련 토큰 및 프로젝트에 대한 투자 관심 확대",
                "nft": "NFT 시장 거래량 변화 모니터링 권장",
            }
            kw_context = kw_context_map.get(top_kw, f"'{top_kw}' 키워드가 다수 등장하여 관련 자산 변동에 유의")
            insight_lines.append(f"\n**모니터링 키워드**: {monitoring_kws} — {kw_context}입니다.")

        # Listing/delisting highlights
        if listing_mentions:
            insight_lines.append(
                f"\n**신규 상장**: {len(listing_mentions)}건의 상장 관련 소식이 포착되었습니다. "
                f"신규 상장은 단기 거래량 급증과 가격 변동성을 동반하는 경우가 많습니다."
            )
        if delisting_mentions:
            insight_lines.append(
                f"\n**상장폐지 주의**: {len(delisting_mentions)}건의 상장폐지 관련 소식이 있습니다. "
                f"보유 자산 점검이 필요합니다."
            )

        # Exchange activity with specific analysis
        if exchange_rows:
            exchange_sources = Counter(row.get("source", "") for row in exchange_rows)
            top_exchange = exchange_sources.most_common(1)
            ex_detail = f" (가장 활발: {top_exchange[0][0]} {top_exchange[0][1]}건)" if top_exchange else ""
            insight_lines.append(
                f"\n**거래소 동향**: 공지사항 {len(exchange_rows)}건{ex_detail}. "
                f"거래소별 정책 변경, 신규 서비스, 수수료 조정 등은 "
                f"트레이딩 전략에 직접적 영향을 미칩니다."
            )

        insight_lines.append("")
        insight_lines.append(
            "> *본 뉴스 브리핑은 자동 수집된 데이터를 기반으로 생성되었으며, 투자 조언이 아닙니다. 모든 투자 결정은 개인의 판단과 책임 하에 이루어져야 합니다.*"
        )
        content_parts.extend(insight_lines)

        # References section (top 10 only) - collapsible
        if source_links:
            content_parts.append("\n---\n")
            content_parts.append(
                html_reference_details(
                    "참고 링크",
                    source_links,
                    limit=10,
                    title_max_len=80,
                )
            )

        # Data collection footer
        content_parts.append("\n---\n")
        content_parts.append(f"**데이터 수집 시각**: {now.strftime('%Y-%m-%d %H:%M')} UTC")
        top_sources_str = ", ".join(f"{name} ({count}건)" for name, count in source_counter.most_common(5))
        content_parts.append(f"**수집 출처**: {top_sources_str}")

        content = "\n".join(content_parts)

        filepath = crypto_gen.create_post(
            title=post_a_title,
            content=content,
            date=now,
            tags=["crypto", "news", "daily-digest"],
            source="consolidated",
            lang="ko",
            image=briefing_image or "",
            slug="daily-crypto-news-digest",
        )
        if filepath:
            dedup.mark_seen(post_a_title, "consolidated", today)
            created_count += 1
            logger.info("Created consolidated crypto news post: %s", filepath)

    # ── Post B: security report (Rekt News + Google Security News) ──
    all_security_items = rekt_items + google_security_items
    if len(all_security_items) < 2:
        logger.info(
            "보안 뉴스가 %d건으로 최소 기준(2건) 미달, 포스트 생성 스킵",
            len(all_security_items),
        )
    else:
        post_b_title = f"블록체인 보안 리포트 - {today}"

        if not dedup.is_duplicate_exact(post_b_title, "consolidated", today):
            content_parts = [f"블록체인 보안 관련 뉴스 {len(all_security_items)}건을 정리합니다.\n"]
            security_links = []

            security_summarizer = ThemeSummarizer(all_security_items)
            summary_points = []
            if rekt_items or google_security_items:
                summary_points.append(f"Rekt News {len(rekt_items)}건, 보안 뉴스 {len(google_security_items)}건")
            overall_summary = security_summarizer.generate_overall_summary_section(
                extra_data={"summary_points": summary_points}
            )
            if overall_summary:
                content_parts.append(overall_summary)

            # Key summary for security
            content_parts.append("## 핵심 요약\n")
            content_parts.append(f"- **보안 사고/뉴스**: 총 {len(all_security_items)}건")
            if rekt_items:
                content_parts.append(f"- **Rekt News 사고**: {len(rekt_items)}건")
                # Sum up funds lost where parseable
                total_funds = 0
                for item in rekt_items:
                    desc = item.get("description", "")
                    if "Funds Lost:" in desc:
                        try:
                            raw = desc.split("Funds Lost:")[1].split("|")[0].strip()
                            raw = raw.replace("$", "").replace(",", "").strip()
                            total_funds += float(raw)
                        except (IndexError, ValueError):
                            pass
                if total_funds > 0:
                    content_parts.append(f"- **총 피해 규모 (추정)**: ${total_funds:,.0f}")
            if google_security_items:
                content_parts.append(f"- **보안 관련 뉴스**: {len(google_security_items)}건")

            technique_counter = Counter()

            # Rekt News section (structured incidents)
            if rekt_items:
                content_parts.append("\n## 보안 사고 현황\n")
                incident_rows = []
                for item in rekt_items:
                    desc = item.get("description", "")
                    project = item["title"].replace("[Security] ", "")
                    link = item.get("link", "")
                    funds_lost = "N/A"
                    technique = "N/A"

                    if "Funds Lost:" in desc:
                        try:
                            funds_lost = desc.split("Funds Lost:")[1].split("|")[0].strip()
                        except IndexError:
                            pass
                    if "Technique:" in desc:
                        try:
                            technique = desc.split("Technique:")[1].strip()
                        except IndexError:
                            pass

                    if technique != "N/A":
                        technique_counter[technique] += 1

                    project_cell = markdown_link(project, link) if link else project
                    incident_rows.append((project_cell, funds_lost, technique))
                    if link:
                        security_links.append(
                            {
                                "title": item["title"],
                                "link": link,
                                "source": item.get("source", ""),
                            }
                        )

                if incident_rows:
                    content_parts.append(markdown_table(["프로젝트", "피해 규모", "공격 유형"], incident_rows))

            # Google Security News section with descriptions
            if google_security_items:
                content_parts.append("\n## 보안 관련 뉴스\n")
                for i, item in enumerate(google_security_items[:10], 1):
                    title = item["title"]
                    link = item.get("link", "")
                    source = item.get("source", "")
                    description = item.get("description", "").strip()
                    if link:
                        content_parts.append(f"**{i}. [{title}]({link})**")
                        security_links.append({"title": title, "link": link, "source": source})
                    else:
                        content_parts.append(f"**{i}. {title}**")
                    if description and description != title:
                        desc_text = smart_truncate(description, 150)
                        content_parts.append(f"{desc_text}")
                    content_parts.append(f"{html_source_tag(source)}\n")

            # Security insight
            content_parts.append("\n## 보안 인사이트\n")
            sec_insight_lines = []
            if rekt_items:
                sec_insight_lines.append(f"최근 보안 사고 {len(rekt_items)}건이 보고되었습니다.")
                if technique_counter:
                    top_tech = technique_counter.most_common(3)
                    tech_str = ", ".join(f"{t}({c}건)" for t, c in top_tech)
                    sec_insight_lines.append(f"주요 공격 유형: {tech_str}.")
            if google_security_items:
                sec_insight_lines.append(
                    f"블록체인 보안 관련 뉴스 {len(google_security_items)}건이 수집되어 업계 보안 이슈에 대한 관심이 높은 상태입니다."
                )
            if not sec_insight_lines:
                sec_insight_lines.append("현재 특이할 만한 보안 사고가 보고되지 않았습니다.")
            sec_insight_lines.append("")
            sec_insight_lines.append(
                "> *본 보안 리포트는 자동 수집된 데이터를 기반으로 생성되었으며, 투자 조언이 아닙니다. 모든 투자 결정은 개인의 판단과 책임 하에 이루어져야 합니다.*"
            )
            content_parts.extend(sec_insight_lines)

            # References
            if security_links:
                content_parts.append("\n## 참고 링크\n")
                content_parts.append(
                    html_reference_details(
                        "참고 링크",
                        security_links,
                        limit=20,
                        title_max_len=80,
                    )
                )

            content = "\n".join(content_parts)

            filepath = security_gen.create_post(
                title=post_b_title,
                content=content,
                date=now,
                tags=["security", "hack", "blockchain", "daily-digest"],
                source="consolidated",
                lang="ko",
                slug="daily-security-report",
            )
            if filepath:
                dedup.mark_seen(post_b_title, "consolidated", today)
                created_count += 1
                logger.info("Created security report post: %s", filepath)

    # Save dedup state
    dedup.save()

    logger.info("=== Crypto news collection complete: %d posts created ===", created_count)
    all_collected_items = all_items + all_security_items
    unique_items = len(
        {
            f"{item.get('title', '')}|{item.get('source', '')}|{item.get('link', '')}"
            for item in all_collected_items
            if item.get("title")
        }
    )
    source_count = len({item.get("source", "") for item in all_collected_items if item.get("source")})
    log_collection_summary(
        logger,
        collector="collect_crypto_news",
        source_count=source_count,
        unique_items=unique_items,
        post_created=created_count,
        started_at=started_at,
    )


if __name__ == "__main__":
    main()
