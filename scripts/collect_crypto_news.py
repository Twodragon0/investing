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
import time
import requests
import certifi
from datetime import datetime, timezone
from typing import List, Dict, Any
from bs4 import BeautifulSoup

# Add scripts directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common.config import get_env, setup_logging
from common.dedup import DedupEngine
from common.post_generator import PostGenerator
from common.utils import sanitize_string

logger = setup_logging("collect_crypto_news")

VERIFY_SSL = certifi.where()
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
                "description": sanitize_string(r.get("title", ""), 500),
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


def fetch_newsapi(api_key: str, limit: int = 20) -> List[Dict[str, Any]]:
    """Fetch crypto news from NewsAPI."""
    if not api_key:
        logger.info("NewsAPI key not set, skipping")
        return []

    url = "https://newsapi.org/v2/everything"
    params = {
        "q": "cryptocurrency OR bitcoin OR ethereum",
        "language": "en",
        "sortBy": "publishedAt",
        "pageSize": limit,
        "apiKey": api_key,
    }

    try:
        resp = requests.get(url, params=params, timeout=REQUEST_TIMEOUT, verify=VERIFY_SSL)
        resp.raise_for_status()
        data = resp.json()
        articles = data.get("articles", [])

        items = []
        for a in articles:
            title = sanitize_string(a.get("title", ""), 300)
            if not title or title == "[Removed]":
                continue
            items.append({
                "title": title,
                "description": sanitize_string(a.get("description", ""), 500),
                "link": a.get("url", ""),
                "published": a.get("publishedAt", ""),
                "source": "NewsAPI",
                "tags": ["crypto", "news"],
            })
        logger.info("NewsAPI: fetched %d items", len(items))
        return items
    except requests.exceptions.RequestException as e:
        logger.warning("NewsAPI fetch failed: %s", e)
        return []


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

            link = link_el.get_text(strip=True) if link_el else ""
            published = date_el.get_text(strip=True) if date_el else ""

            items.append({
                "title": title,
                "description": description,
                "link": link,
                "published": published,
                "source": source_name,
                "tags": tags,
            })
        logger.info("RSS %s: fetched %d items", source_name, len(items))
        return items
    except requests.exceptions.RequestException as e:
        logger.warning("RSS %s fetch failed: %s", source_name, e)
        return []


def fetch_google_news_crypto() -> List[Dict[str, Any]]:
    """Fetch crypto news from Google News RSS (English + Korean)."""
    feeds = [
        ("https://news.google.com/rss/search?q=cryptocurrency&hl=en-US&gl=US&ceid=US:en", "Google News EN", ["crypto", "english"]),
        ("https://news.google.com/rss/search?q=암호화폐+비트코인&hl=ko&gl=KR&ceid=KR:ko", "Google News KR", ["crypto", "korean", "비트코인"]),
    ]
    all_items = []
    for url, name, tags in feeds:
        all_items.extend(fetch_rss_feed(url, name, tags))
        time.sleep(1)
    return all_items


def fetch_exchange_announcements() -> List[Dict[str, Any]]:
    """Fetch announcements from major exchanges (public APIs only)."""
    items = []

    # Binance announcements
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
        logger.info("Binance: fetched %d announcements", len(items))
    except requests.exceptions.RequestException as e:
        logger.warning("Binance announcements fetch failed: %s", e)

    return items


def fetch_rekt_news(limit: int = 10) -> List[Dict[str, Any]]:
    """Fetch security incidents from Rekt News."""
    try:
        url = "https://rekt.news/api/incidents"
        resp = requests.get(
            url, timeout=REQUEST_TIMEOUT, verify=VERIFY_SSL,
            headers={"User-Agent": USER_AGENT},
        )
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, list):
            return []

        data_sorted = sorted(data, key=lambda x: x.get("date", ""), reverse=True)
        items = []
        for incident in data_sorted[:limit]:
            title = sanitize_string(incident.get("title", incident.get("project_name", "")), 300)
            if not title:
                continue

            funds_lost = incident.get("funds_lost", "")
            description = f"Project: {title}"
            if funds_lost:
                description += f" | Funds Lost: ${funds_lost}"
            technique = incident.get("technique", "")
            if technique:
                description += f" | Technique: {technique}"

            items.append({
                "title": f"[Security] {title}",
                "description": sanitize_string(description, 500),
                "link": incident.get("url", ""),
                "published": incident.get("date", ""),
                "source": "Rekt News",
                "tags": ["security", "hack", "rekt"],
                "category_override": "security-alerts",
            })
        logger.info("Rekt News: fetched %d incidents", len(items))
        return items
    except requests.exceptions.RequestException as e:
        logger.warning("Rekt News fetch failed: %s", e)
        return []


def main():
    """Main collection routine - consolidated posts."""
    logger.info("=== Starting crypto news collection ===")

    cryptopanic_key = get_env("CRYPTOPANIC_API_KEY")
    newsapi_key = get_env("NEWSAPI_API_KEY")

    dedup = DedupEngine("crypto_news_seen.json")
    crypto_gen = PostGenerator("crypto-news")
    security_gen = PostGenerator("security-alerts")

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    now = datetime.now(timezone.utc)

    all_items = []

    # Collect from all sources
    all_items.extend(fetch_cryptopanic(cryptopanic_key))
    all_items.extend(fetch_newsapi(newsapi_key))
    all_items.extend(fetch_google_news_crypto())

    # Exchange announcements collected separately for their own section
    exchange_items = fetch_exchange_announcements()
    all_items.extend(exchange_items)

    # Rekt News -> security-alerts category
    rekt_items = fetch_rekt_news()

    created_count = 0

    # ── Post A: consolidated crypto news briefing ──
    post_a_title = f"암호화폐 뉴스 브리핑 - {today}"

    if not dedup.is_duplicate(post_a_title, "consolidated", today):
        # Separate news items from exchange announcements
        news_rows = []
        exchange_rows = []
        sources_seen = set()
        source_links = []

        for item in all_items:
            title = item["title"]
            source = item.get("source", "unknown")
            link = item.get("link", "")
            sources_seen.add(source)

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

        content_parts = [f"오늘 총 {len(all_items)}건의 암호화폐 관련 뉴스가 수집되었습니다. 주요 내용을 정리합니다.\n"]

        # Main news table
        content_parts.append("## 주요 뉴스\n")
        if news_rows:
            content_parts.append("| # | 제목 | 출처 |")
            content_parts.append("|---|------|------|")
            content_parts.extend(news_rows)
        else:
            content_parts.append("*수집된 뉴스가 없습니다.*")

        # Exchange announcements table
        content_parts.append("\n## 거래소 공지사항\n")
        if exchange_rows:
            content_parts.append("| # | 제목 | 거래소 |")
            content_parts.append("|---|------|--------|")
            content_parts.extend(exchange_rows)
        else:
            content_parts.append("*수집된 거래소 공지사항이 없습니다.*")

        # Summary
        content_parts.append("\n## 뉴스 요약")
        content_parts.append(f"- 총 수집된 뉴스: {len(all_items)}건")
        content_parts.append(f"- 주요 출처: {', '.join(sorted(sources_seen))}")

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

    # ── Post B: security report (only if rekt_items exist) ──
    if rekt_items:
        post_b_title = f"블록체인 보안 리포트 - {today}"

        if not dedup.is_duplicate(post_b_title, "consolidated", today):
            content_parts = ["최근 블록체인 보안 사고를 정리합니다.\n"]
            content_parts.append("## 보안 사고 현황\n")
            content_parts.append("| 프로젝트 | 피해 규모 | 공격 유형 |")
            content_parts.append("|----------|----------|----------|")

            security_links = []

            for item in rekt_items:
                # Parse description for structured data
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

                if link:
                    content_parts.append(f"| [{project}]({link}) | {funds_lost} | {technique} |")
                    security_links.append({"title": item["title"], "link": link, "source": item.get("source", "")})
                else:
                    content_parts.append(f"| {project} | {funds_lost} | {technique} |")

            # References section for security report
            if security_links:
                content_parts.append("\n## 참고 링크\n")
                for i, ref in enumerate(security_links[:20], 1):
                    content_parts.append(f"{i}. [{ref['title'][:80]}]({ref['link']}) - {ref['source']}")

            content = "\n".join(content_parts)

            filepath = security_gen.create_post(
                title=post_b_title,
                content=content,
                date=now,
                tags=["security", "hack", "rekt", "daily-digest"],
                source="Rekt News",
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
