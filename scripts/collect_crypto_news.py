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
from common.utils import sanitize_string
from common.rss_fetcher import fetch_rss_feed
from common.summarizer import ThemeSummarizer

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
        time.sleep(1)
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
        time.sleep(1)
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
    all_items.extend(fetch_crypto_rss_feeds())

    # Exchange announcements collected separately for their own section
    exchange_items = fetch_exchange_announcements()
    all_items.extend(exchange_items)

    # Security news from multiple sources -> security-alerts category
    rekt_items = fetch_rekt_news()
    google_security_items = fetch_google_news_security()

    created_count = 0

    # ── Post A: consolidated crypto news briefing ──
    post_a_title = f"암호화폐 뉴스 브리핑 - {today}"

    if not dedup.is_duplicate_exact(post_a_title, "consolidated", today):
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

        content_parts = [f"오늘 총 {len(all_items)}건의 암호화폐 관련 뉴스가 수집되었습니다. 주요 내용을 정리합니다.\n"]

        # Create theme summarizer for reuse
        summarizer = ThemeSummarizer(all_items)

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

        # Exchange announcements table
        content_parts.append("\n## 거래소 공지사항\n")
        if exchange_rows:
            content_parts.append("| # | 제목 | 거래소 |")
            content_parts.append("|---|------|--------|")
            content_parts.extend(exchange_rows)
        else:
            content_parts.append("*수집된 거래소 공지사항이 없습니다.*")

        # Insight section
        content_parts.append("\n## 오늘의 인사이트\n")
        insight_lines = []
        if len(all_items) >= 10:
            insight_lines.append(f"오늘 총 {len(all_items)}건의 뉴스가 {len(source_counter)}개 출처에서 수집되었습니다.")
        else:
            insight_lines.append(f"오늘 뉴스 수집량이 {len(all_items)}건으로 비교적 적은 편입니다.")
        if top_keywords:
            insight_lines.append(f"가장 많이 언급된 키워드는 **{top_keywords[0][0]}**({top_keywords[0][1]}회)입니다.")
        if exchange_rows:
            insight_lines.append(f"거래소 공지사항 {len(exchange_rows)}건이 수집되어, 거래소 동향 확인이 필요합니다.")
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
