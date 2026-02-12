#!/usr/bin/env python3
"""Collect cryptocurrency news from multiple sources and generate Jekyll posts.

Sources:
- CryptoPanic API (hot news)
- NewsAPI (crypto keywords)
- Google News RSS (Korean/English crypto)
- Exchange announcements (OKX, Binance, Bybit public APIs)
- Rekt News (security incidents -> security-alerts category)
"""

import sys
import os
import re
import time
import requests
from collections import Counter
from datetime import datetime, timezone
from typing import List, Dict, Any

# Add scripts directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common.config import get_env, setup_logging, get_ssl_verify
from common.dedup import DedupEngine
from common.post_generator import PostGenerator
from common.utils import sanitize_string, request_with_retry
from common.rss_fetcher import fetch_rss_feed
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

logger = setup_logging("collect_crypto_news")

VERIFY_SSL = get_ssl_verify()
REQUEST_TIMEOUT = 15
USER_AGENT = "Mozilla/5.0 (compatible; InvestingDragon/1.0)"


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
            items.append({
                "title": sanitize_string(r.get("title", ""), 300),
                "description": sanitize_string(r.get("metadata", {}).get("description", r.get("title", "")), 500),
                "link": r.get("url", ""),
                "published": r.get("published_at", ""),
                "source": "CryptoPanic",
                "tags": ["crypto", "hot-news"],
            })
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
    """Fetch news from major crypto media RSS feeds."""
    feeds = [
        ("https://www.coindesk.com/arc/outboundfeeds/rss", "CoinDesk", ["crypto", "coindesk"]),
        ("https://cointelegraph.com/rss", "Cointelegraph", ["crypto", "cointelegraph"]),
        ("https://decrypt.co/feed", "Decrypt", ["crypto", "decrypt"]),
        ("https://bitcoinmagazine.com/.rss/full/", "Bitcoin Magazine", ["crypto", "bitcoin"]),
    ]
    all_items = []
    for url, name, tags in feeds:
        all_items.extend(fetch_rss_feed(url, name, tags))
    # The Block — may block requests, wrap with extra try/except
    try:
        all_items.extend(fetch_rss_feed(
            "https://www.theblock.co/rss", "The Block", ["crypto", "theblock"],
        ))
    except Exception as e:
        logger.warning("The Block RSS failed: %s", e)
    return all_items


def fetch_google_news_crypto() -> List[Dict[str, Any]]:
    """Fetch crypto news from Google News RSS (English + Korean)."""
    feeds = [
        ("https://news.google.com/rss/search?q=cryptocurrency&hl=en-US&gl=US&ceid=US:en", "Google News EN", ["crypto", "english"]),
        ("https://news.google.com/rss/search?q=암호화폐+비트코인&hl=ko&gl=KR&ceid=KR:ko", "Google News KR", ["crypto", "korean", "비트코인"]),
    ]
    all_items = []
    for url, name, tags in feeds:
        all_items.extend(fetch_rss_feed(url, name, tags))
    return all_items


def fetch_google_news_security() -> List[Dict[str, Any]]:
    """Fetch blockchain security news from Google News RSS."""
    feeds = [
        ("https://news.google.com/rss/search?q=blockchain+hack+exploit+security&hl=en-US&gl=US&ceid=US:en",
         "Blockchain Security EN", ["security", "hack", "english"]),
        ("https://news.google.com/rss/search?q=crypto+hack+DeFi+exploit&hl=en-US&gl=US&ceid=US:en",
         "DeFi Security EN", ["security", "defi", "exploit"]),
        ("https://news.google.com/rss/search?q=블록체인+해킹+보안+취약점&hl=ko&gl=KR&ceid=KR:ko",
         "블록체인 보안 KR", ["security", "hack", "korean"]),
    ]
    all_items = []
    for url, name, tags in feeds:
        items = fetch_rss_feed(url, name, tags)
        for item in items:
            item["category_override"] = "security-alerts"
        all_items.extend(items)
    return all_items


def _fetch_binance_browser() -> List[Dict[str, Any]]:
    """Scrape Binance announcements page with Playwright."""
    if not is_playwright_available():
        return []

    items: List[Dict[str, Any]] = []
    seen_titles: set = set()
    try:
        with BrowserSession(timeout=30_000) as session:
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
                    title = sanitize_string(link_el.inner_text().strip(), 300)
                    href = link_el.get_attribute("href") or ""
                    if not title or len(title) < 5:
                        continue
                    # Skip navigation/category links (short generic text)
                    if title in seen_titles:
                        continue
                    seen_titles.add(title)
                    if href and not href.startswith("http"):
                        href = "https://www.binance.com" + href
                    # Only include detail pages, not list pages
                    if "/detail/" not in href and "/list/" not in href:
                        continue
                    items.append({
                        "title": title,
                        "description": title,
                        "link": href,
                        "published": "",
                        "source": "Binance",
                        "tags": ["crypto", "exchange", "binance"],
                    })
                except Exception:
                    continue
        logger.info("Binance Browser: fetched %d announcements", len(items))
    except Exception as e:
        logger.warning("Binance browser scraping failed: %s", e)
    return items


def _fetch_binance_bapi() -> List[Dict[str, Any]]:
    """Fetch Binance announcements via BAPI (legacy fallback)."""
    items: List[Dict[str, Any]] = []
    try:
        url = "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query"
        params = {"type": 1, "pageNo": 1, "pageSize": 10}
        resp = requests.get(url, params=params, timeout=REQUEST_TIMEOUT, verify=VERIFY_SSL,
                           headers={"User-Agent": USER_AGENT})
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
                            date_str = datetime.fromtimestamp(release_date / 1000, tz=timezone.utc).isoformat()
                        except (ValueError, OSError):
                            pass
                    items.append({
                        "title": title,
                        "description": title,
                        "link": "https://www.binance.com/en/support/announcement",
                        "published": date_str,
                        "source": "Binance",
                        "tags": ["crypto", "exchange", "binance"],
                    })
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
            "https://rekt.news/rss/feed.xml", "Rekt News",
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

    try:
        with BrowserSession(timeout=30_000) as session:
            # Google News
            try:
                session.navigate(
                    "https://news.google.com/search?q=cryptocurrency+bitcoin&hl=en-US&gl=US&ceid=US:en",
                    wait_until="domcontentloaded", wait_ms=3000,
                )
                google_items = extract_google_news_links(session, 20, ["crypto", "news"])
                logger.info("Google News Browser: fetched %d items", len(google_items))
            except Exception as e:
                logger.warning("Google News browser scraping failed: %s", e)

            # Binance announcements
            try:
                session.navigate(
                    "https://www.binance.com/en/support/announcement",
                    wait_until="domcontentloaded", wait_ms=5000,
                )
                seen_titles: set = set()
                links = session.extract_elements("a[href*='/support/announcement/']")
                for link_el in links:
                    if len(binance_items) >= 15:
                        break
                    try:
                        title = sanitize_string(link_el.inner_text().strip(), 300)
                        href = link_el.get_attribute("href") or ""
                        if not title or len(title) < 5 or title in seen_titles:
                            continue
                        seen_titles.add(title)
                        if href and not href.startswith("http"):
                            href = "https://www.binance.com" + href
                        if "/detail/" not in href and "/list/" not in href:
                            continue
                        binance_items.append({
                            "title": title, "description": title, "link": href,
                            "published": "", "source": "Binance",
                            "tags": ["crypto", "exchange", "binance"],
                        })
                    except Exception:
                        continue
                logger.info("Binance Browser: fetched %d announcements", len(binance_items))
            except Exception as e:
                logger.warning("Binance browser scraping failed: %s", e)
    except Exception as e:
        logger.warning("Browser session failed: %s", e)

    return google_items, binance_items


def main():
    """Main collection routine - consolidated posts."""
    logger.info("=== Starting crypto news collection ===")

    cryptopanic_key = get_env("CRYPTOPANIC_API_KEY")

    dedup = DedupEngine("crypto_news_seen.json")
    crypto_gen = PostGenerator("crypto-news")
    security_gen = PostGenerator("security-alerts")

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    now = datetime.now(timezone.utc)

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
    all_items.extend(exchange_items)

    # Security news from multiple sources -> security-alerts category
    rekt_items = fetch_rekt_news()
    google_security_items = fetch_google_news_security()

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
                if link:
                    exchange_rows.append(f"| {len(exchange_rows) + 1} | [**{title}**]({link}) | {source} |")
                else:
                    exchange_rows.append(f"| {len(exchange_rows) + 1} | **{title}** | {source} |")
            else:
                if link:
                    news_rows.append(f"| {len(news_rows) + 1} | [**{title}**]({link}) | {source} |")
                else:
                    news_rows.append(f"| {len(news_rows) + 1} | **{title}** | {source} |")

        # Limit to top items
        news_rows = news_rows[:15]
        exchange_rows = exchange_rows[:10]

        # Keyword frequency analysis
        keyword_targets = ["bitcoin", "ethereum", "regulation", "etf", "defi", "nft", "ai"]
        all_titles_lower = " ".join(item["title"].lower() for item in all_items)
        keyword_hits = {kw: len(re.findall(r'\b' + kw + r'\b', all_titles_lower, re.IGNORECASE))
                        for kw in keyword_targets}
        top_keywords = [(kw, cnt) for kw, cnt in sorted(keyword_hits.items(), key=lambda x: -x[1]) if cnt > 0]

        # Create theme summarizer for reuse (before opening)
        summarizer = ThemeSummarizer(all_items)

        # Get top themes for opening
        top_themes = summarizer.get_top_themes()
        theme_names = [t[0] for t in top_themes] if top_themes else []
        if theme_names:
            themes_str = ", ".join(theme_names[:3])
            content_parts = [f"**{today}** 암호화폐 시장에서 {len(all_items)}건의 뉴스를 분석했습니다. 오늘은 **{themes_str}** 관련 소식이 주목됩니다.\n"]
        else:
            content_parts = [f"**{today}** 암호화폐 시장에서 {len(all_items)}건의 뉴스를 분석했습니다.\n"]

        # Distribution chart
        dist_chart = summarizer.generate_distribution_chart()
        if dist_chart:
            content_parts.append("---\n")
            content_parts.append(dist_chart)
            content_parts.append("\n---\n")

        # Key summary
        content_parts.append("## 핵심 요약\n")
        content_parts.append(f"- **총 뉴스 건수**: {len(all_items)}건")
        top_source = source_counter.most_common(1)
        if top_source:
            content_parts.append(f"- **주요 출처**: {top_source[0][0]} ({top_source[0][1]}건)")
        content_parts.append(f"- **수집 출처 수**: {len(source_counter)}개")
        if top_keywords:
            kw_str = ", ".join(f"{kw}({cnt})" for kw, cnt in top_keywords[:5])
            content_parts.append(f"- **주요 키워드**: {kw_str}")

        # 오늘의 핵심 bullet points
        content_parts.append("\n## 오늘의 핵심\n")
        highlights = []
        if top_keywords:
            highlights.append(f"- 가장 많이 언급된 키워드는 **{top_keywords[0][0]}**({top_keywords[0][1]}회)으로, 시장의 핵심 관심사입니다.")
        if top_source:
            highlights.append(f"- **{top_source[0][0]}**에서 가장 많은 뉴스({top_source[0][1]}건)가 수집되었습니다.")
        if len(all_items) >= 15:
            highlights.append(f"- 총 {len(all_items)}건의 뉴스가 수집되어 시장 관심이 높은 상황입니다.")
        elif len(all_items) < 5:
            highlights.append(f"- 총 {len(all_items)}건으로 뉴스 수집량이 적어, 시장이 비교적 조용한 상태입니다.")
        if theme_names:
            for theme in theme_names[:2]:
                highlights.append(f"- **{theme}** 관련 뉴스에 주목할 필요가 있습니다.")
        if highlights:
            content_parts.extend(highlights)
        else:
            content_parts.append("- 오늘의 특이 사항이 없습니다.")

        # Image — news source distribution bar chart
        try:
            from common.image_generator import generate_news_summary_card
            categories = [{"name": name, "count": count} for name, count in source_counter.most_common(8)]
            img = generate_news_summary_card(categories, today)
            if img:
                fn = os.path.basename(img)
                web_path = "{{ '/assets/images/generated/" + fn + "' | relative_url }}"
                content_parts.append(f"\n![news-summary]({web_path})\n")
                logger.info("Generated news summary image")
        except ImportError:
            pass
        except Exception as e:
            logger.warning("News summary image failed: %s", e)

        # Main news - theme-based sections
        themed_sections = summarizer.generate_themed_news_sections()
        if themed_sections:
            content_parts.append(themed_sections)
        else:
            # Fallback to flat table if themed sections are empty
            content_parts.append("## 주요 뉴스\n")
            if news_rows:
                content_parts.append("| # | 제목 | 출처 |")
                content_parts.append("|---|------|------|")
                content_parts.extend(news_rows)
            else:
                content_parts.append("*수집된 뉴스가 없습니다.*")

        # Exchange announcements table (only show if data exists)
        if exchange_rows:
            content_parts.append("\n## 거래소 공지사항\n")
            content_parts.append("| # | 제목 | 거래소 |")
            content_parts.append("|---|------|--------|")
            content_parts.extend(exchange_rows)

        # Insight section - theme-based analysis
        content_parts.append("\n## 오늘의 인사이트\n")
        insight_lines = []

        # Top 2 themes cross-analysis
        if top_themes and len(top_themes) >= 2:
            t1, t2 = top_themes[0][0], top_themes[1][0]
            insight_lines.append(f"오늘 가장 주목할 테마는 **{t1}**와 **{t2}**입니다. 두 테마의 동시 부각은 시장의 방향성을 가늠하는 데 중요한 신호가 될 수 있습니다.")
        elif top_themes:
            insight_lines.append(f"오늘 가장 주목할 테마는 **{top_themes[0][0]}**입니다.")
        else:
            if len(all_items) >= 10:
                insight_lines.append(f"오늘 총 {len(all_items)}건의 뉴스가 {len(source_counter)}개 출처에서 수집되었습니다.")
            else:
                insight_lines.append(f"오늘 뉴스 수집량이 {len(all_items)}건으로 비교적 적은 편입니다.")

        # Keyword monitoring suggestion
        if top_keywords:
            monitoring_kws = ", ".join(f"**{kw}**" for kw, _ in top_keywords[:3])
            insight_lines.append(f"\n향후 모니터링이 필요한 키워드: {monitoring_kws}")

        # Exchange activity connection
        if exchange_rows:
            insight_lines.append(f"\n거래소 공지사항 {len(exchange_rows)}건이 수집되었습니다. 새로운 상장, 이벤트, 정책 변경 등 거래소 동향이 시장 가격에 직접적 영향을 미칠 수 있어 주의가 필요합니다.")

        insight_lines.append("")
        insight_lines.append("> *본 뉴스 브리핑은 자동 수집된 데이터를 기반으로 생성되었으며, 투자 조언이 아닙니다. 모든 투자 결정은 개인의 판단과 책임 하에 이루어져야 합니다.*")
        content_parts.extend(insight_lines)

        # References section
        if source_links:
            content_parts.append("\n---\n")
            content_parts.append("## 참고 링크\n")
            seen_links = set()
            ref_count = 1
            for ref in source_links[:20]:
                if ref["link"] not in seen_links:
                    seen_links.add(ref["link"])
                    content_parts.append(f"{ref_count}. [{ref['title'][:80]}]({ref['link']}) - {ref['source']}")
                    ref_count += 1

        # Data collection footer
        content_parts.append("\n---\n")
        content_parts.append(f"**데이터 수집 시각**: {now.strftime('%Y-%m-%d %H:%M')} UTC")
        top_sources_str = ', '.join(f'{name} ({count}건)' for name, count in source_counter.most_common(5))
        content_parts.append(f"**수집 출처**: {top_sources_str}")

        content = "\n".join(content_parts)

        filepath = crypto_gen.create_post(
            title=post_a_title,
            content=content,
            date=now,
            tags=["crypto", "news", "daily-digest"],
            source="consolidated",
            lang="ko",
            slug="daily-crypto-news-digest",
        )
        if filepath:
            dedup.mark_seen(post_a_title, "consolidated", today)
            created_count += 1
            logger.info("Created consolidated crypto news post: %s", filepath)

    # ── Post B: security report (Rekt News + Google Security News) ──
    all_security_items = rekt_items + google_security_items
    if all_security_items:
        post_b_title = f"블록체인 보안 리포트 - {today}"

        if not dedup.is_duplicate_exact(post_b_title, "consolidated", today):
            content_parts = [f"블록체인 보안 관련 뉴스 {len(all_security_items)}건을 정리합니다.\n"]
            security_links = []

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

            # Rekt News section (structured incidents)
            if rekt_items:
                content_parts.append("\n## 보안 사고 현황\n")
                content_parts.append("| 프로젝트 | 피해 규모 | 공격 유형 |")
                content_parts.append("|----------|----------|----------|")

                technique_counter = Counter()
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

                    if link:
                        content_parts.append(f"| [{project}]({link}) | {funds_lost} | {technique} |")
                        security_links.append({"title": item["title"], "link": link, "source": item.get("source", "")})
                    else:
                        content_parts.append(f"| {project} | {funds_lost} | {technique} |")

            # Google Security News section
            if google_security_items:
                content_parts.append("\n## 보안 관련 뉴스\n")
                content_parts.append("| # | 제목 | 출처 |")
                content_parts.append("|---|------|------|")
                for i, item in enumerate(google_security_items[:15], 1):
                    title = item["title"]
                    link = item.get("link", "")
                    source = item.get("source", "")
                    if link:
                        content_parts.append(f"| {i} | [**{title}**]({link}) | {source} |")
                        security_links.append({"title": title, "link": link, "source": source})
                    else:
                        content_parts.append(f"| {i} | **{title}** | {source} |")

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
                sec_insight_lines.append(f"블록체인 보안 관련 뉴스 {len(google_security_items)}건이 수집되어 업계 보안 이슈에 대한 관심이 높은 상태입니다.")
            if not sec_insight_lines:
                sec_insight_lines.append("현재 특이할 만한 보안 사고가 보고되지 않았습니다.")
            sec_insight_lines.append("")
            sec_insight_lines.append("> *본 보안 리포트는 자동 수집된 데이터를 기반으로 생성되었으며, 투자 조언이 아닙니다. 모든 투자 결정은 개인의 판단과 책임 하에 이루어져야 합니다.*")
            content_parts.extend(sec_insight_lines)

            # References
            if security_links:
                content_parts.append("\n## 참고 링크\n")
                seen_links = set()
                ref_count = 1
                for ref in security_links[:20]:
                    if ref["link"] not in seen_links:
                        seen_links.add(ref["link"])
                        content_parts.append(f"{ref_count}. [{ref['title'][:80]}]({ref['link']}) - {ref['source']}")
                        ref_count += 1

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


if __name__ == "__main__":
    main()
