#!/usr/bin/env python3
"""Collect social media posts related to crypto/stocks and generate Jekyll posts.

Sources:
- Telegram public channels (HTML scraping t.me/s/channel)
- Twitter/X API v2 search (Bearer Token)
- Google News RSS fallback for social keywords
"""

import sys
import os
import re
import time
import requests
from collections import Counter
from datetime import datetime, timezone
from typing import List, Dict, Any
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common.config import get_env, setup_logging, get_ssl_verify
from common.dedup import DedupEngine
from common.post_generator import PostGenerator
from common.utils import sanitize_string, truncate_text, request_with_retry
from common.rss_fetcher import fetch_rss_feeds_concurrent
from common.summarizer import ThemeSummarizer

try:
    from common.browser import BrowserSession, is_playwright_available
except ImportError:
    BrowserSession = None  # type: ignore[assignment,misc]

    def is_playwright_available() -> bool:  # type: ignore[misc]
        return False

logger = setup_logging("collect_social_media")

VERIFY_SSL = get_ssl_verify()
REQUEST_TIMEOUT = 15
USER_AGENT = "Mozilla/5.0 (compatible; InvestingDragon/1.0)"


def _parse_telegram_items(channel: str, messages, limit: int) -> List[Dict[str, Any]]:
    """Parse Telegram message elements (shared between Playwright and BS4 paths)."""
    items: List[Dict[str, Any]] = []
    for msg in messages[-limit:]:
        try:
            # Works for both BS4 Tag and Playwright ElementHandle
            if hasattr(msg, "query_selector"):
                # Playwright ElementHandle
                text_div = msg.query_selector(".tgme_widget_message_text")
                if not text_div:
                    continue
                text = sanitize_string(text_div.inner_text(), 500)
                date_el = msg.query_selector("time")
                date_str = date_el.get_attribute("datetime") if date_el else ""
                link_el = msg.query_selector("a.tgme_widget_message_date")
                link = link_el.get_attribute("href") if link_el else ""
            else:
                # BS4 Tag
                text_div = msg.find("div", class_="tgme_widget_message_text")
                if not text_div:
                    continue
                text = sanitize_string(text_div.get_text(" ", strip=True), 500)
                date_el = msg.find("time")
                date_str = date_el.get("datetime", "") if date_el else ""
                link_el = msg.find("a", class_="tgme_widget_message_date")
                link = link_el.get("href", "") if link_el else ""

            if not text or len(text) < 20:
                continue

            title = text.split("\n")[0][:100]
            if len(title) < 10:
                title = truncate_text(text, 100)

            items.append({
                "title": f"[Telegram] {title}",
                "description": text,
                "link": link or "",
                "published": date_str or "",
                "source": f"Telegram @{channel}",
                "tags": ["social-media", "telegram", channel],
            })
        except Exception:
            continue
    return items


def _fetch_telegram_browser(channels: List[str], limit: int = 10) -> Dict[str, List[Dict[str, Any]]]:
    """Fetch multiple Telegram channels in a single browser session."""
    results: Dict[str, List[Dict[str, Any]]] = {}
    if not is_playwright_available():
        return results

    try:
        with BrowserSession(timeout=30_000) as session:
            for channel in channels:
                try:
                    session.navigate(
                        f"https://t.me/s/{channel}",
                        wait_until="domcontentloaded",
                        wait_ms=2000,
                    )
                    # Wait for message elements to render
                    try:
                        session.wait_for(".tgme_widget_message_wrap", timeout=5000)
                    except Exception:
                        pass  # Some channels may be empty or have no messages
                    messages = session.extract_elements(".tgme_widget_message_wrap")
                    items = _parse_telegram_items(channel, messages, limit)
                    results[channel] = items
                    logger.info("Telegram Browser @%s: fetched %d messages", channel, len(items))
                except Exception as e:
                    logger.warning("Telegram Browser @%s failed: %s", channel, e)
                    results[channel] = []
    except Exception as e:
        logger.warning("Telegram browser session failed: %s", e)
    return results


def fetch_telegram_channel(channel: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Scrape public Telegram channel messages via t.me/s/ preview (requests fallback)."""
    url = f"https://t.me/s/{channel}"
    try:
        resp = requests.get(
            url, timeout=REQUEST_TIMEOUT, verify=VERIFY_SSL,
            headers={"User-Agent": USER_AGENT},
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        messages = soup.find_all("div", class_="tgme_widget_message_wrap")
        items = _parse_telegram_items(channel, messages, limit)
        logger.info("Telegram @%s: fetched %d messages", channel, len(items))
        return items
    except requests.exceptions.RequestException as e:
        logger.warning("Telegram @%s fetch failed: %s", channel, e)
        return []


def fetch_twitter_search(bearer_token: str, query: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Search Twitter/X using API v2."""
    if not bearer_token:
        logger.info("Twitter Bearer Token not set, skipping")
        return []

    url = "https://api.twitter.com/2/tweets/search/recent"
    headers = {"Authorization": f"Bearer {bearer_token}"}
    params = {
        "query": query,
        "max_results": min(limit, 100),
        "tweet.fields": "created_at,author_id,text",
    }

    try:
        resp = requests.get(url, headers=headers, params=params,
                           timeout=REQUEST_TIMEOUT, verify=VERIFY_SSL)
        resp.raise_for_status()
        data = resp.json()

        items = []
        for tweet in data.get("data", []):
            text = sanitize_string(tweet.get("text", ""), 500)
            if not text:
                continue

            tweet_id = tweet.get("id", "")
            title = truncate_text(text, 100)

            items.append({
                "title": f"[X/Twitter] {title}",
                "description": text,
                "link": f"https://twitter.com/i/web/status/{tweet_id}" if tweet_id else "",
                "published": tweet.get("created_at", ""),
                "source": "Twitter/X",
                "tags": ["social-media", "twitter"],
            })

        logger.info("Twitter search '%s': fetched %d tweets", query[:30], len(items))
        return items
    except requests.exceptions.RequestException as e:
        logger.warning("Twitter search failed: %s", e)
        return []


def fetch_reddit_posts(limit: int = 10) -> List[Dict[str, Any]]:
    """Fetch top posts from crypto/stock-related Reddit subreddits via JSON API."""
    subreddits = [
        ("cryptocurrency", "r/CryptoCurrency", 50),
        ("bitcoin", "r/Bitcoin", 50),
        ("ethtrader", "r/EthTrader", 50),
        ("wallstreetbets", "r/WallStreetBets", 100),
        ("stocks", "r/Stocks", 50),
        ("investing", "r/Investing", 50),
        ("defi", "r/DeFi", 20),
    ]
    all_items = []
    for sub, display_name, min_score in subreddits:
        url = f"https://www.reddit.com/r/{sub}/hot.json?limit={limit}"
        try:
            resp = request_with_retry(
                url, timeout=REQUEST_TIMEOUT, verify_ssl=VERIFY_SSL,
                headers={"User-Agent": USER_AGENT},
            )
            data = resp.json()
            sub_count = 0
            for post in data.get("data", {}).get("children", [])[:limit]:
                pd = post.get("data", {})
                title = sanitize_string(pd.get("title", ""), 300)
                if not title or pd.get("stickied"):
                    continue
                score = pd.get("score", 0)
                if score < min_score:
                    continue
                all_items.append({
                    "title": f"[Reddit] {title}",
                    "description": truncate_text(pd.get("selftext", title), 300),
                    "link": f"https://reddit.com{pd.get('permalink', '')}",
                    "published": "",
                    "source": display_name,
                    "tags": ["social-media", "reddit", sub],
                    "score": score,
                })
                sub_count += 1
            logger.info("Reddit %s: fetched %d posts", display_name, sub_count)
        except requests.exceptions.RequestException as e:
            logger.warning("Reddit %s fetch failed: %s", display_name, e)
        time.sleep(1)

    # Sort by score
    all_items.sort(key=lambda x: x.get("score", 0), reverse=True)
    return all_items[:limit * 2]


def fetch_google_news_social() -> List[Dict[str, Any]]:
    """Google News RSS fallback for social/crypto influencer content (concurrent)."""
    feeds = [
        ("https://news.google.com/rss/search?q=crypto+twitter+sentiment&hl=en-US&gl=US&ceid=US:en",
         "Google News Social EN", ["social-media", "sentiment"]),
        ("https://news.google.com/rss/search?q=암호화폐+커뮤니티+SNS&hl=ko&gl=KR&ceid=KR:ko",
         "Google News Social KR", ["social-media", "korean"]),
        ("https://news.google.com/rss/search?q=crypto+whale+alert+on-chain&hl=en-US&gl=US&ceid=US:en",
         "Whale & On-chain", ["social-media", "whale", "on-chain"]),
    ]
    return fetch_rss_feeds_concurrent(feeds)


def fetch_political_economy_news() -> List[Dict[str, Any]]:
    """Fetch Trump and 이재명 related economy/crypto news (concurrent)."""
    feeds = [
        ("https://news.google.com/rss/search?q=Trump+crypto+policy&hl=en-US&gl=US&ceid=US:en",
         "Trump Crypto Policy", ["politics", "trump", "crypto"]),
        ("https://news.google.com/rss/search?q=Trump+tariff+economy+stock&hl=en-US&gl=US&ceid=US:en",
         "Trump Economy", ["politics", "trump", "economy"]),
        ("https://news.google.com/rss/search?q=트럼프+암호화폐+경제&hl=ko&gl=KR&ceid=KR:ko",
         "트럼프 경제정책 KR", ["politics", "trump", "korean"]),
        ("https://news.google.com/rss/search?q=이재명+경제+정책&hl=ko&gl=KR&ceid=KR:ko",
         "이재명 경제정책", ["politics", "이재명", "economy"]),
        ("https://news.google.com/rss/search?q=이재명+주식+암호화폐+코인&hl=ko&gl=KR&ceid=KR:ko",
         "이재명 암호화폐정책", ["politics", "이재명", "crypto"]),
        ("https://news.google.com/rss/search?q=이재명+부동산+금리&hl=ko&gl=KR&ceid=KR:ko",
         "이재명 부동산·금리", ["politics", "이재명", "real-estate"]),
        ("https://news.google.com/rss/search?q=Federal+Reserve+interest+rate+decision&hl=en-US&gl=US&ceid=US:en",
         "Fed Policy", ["politics", "fed", "macro"]),
        ("https://news.google.com/rss/search?q=한국은행+금리+경제&hl=ko&gl=KR&ceid=KR:ko",
         "한국은행 금리정책", ["politics", "한국은행", "macro"]),
        ("https://news.google.com/rss/search?q=코스피+외국인+기관+수급&hl=ko&gl=KR&ceid=KR:ko",
         "한국증시 수급", ["stock", "korean", "수급"]),
    ]
    return fetch_rss_feeds_concurrent(feeds)


def main():
    """Main social media collection routine - consolidated post."""
    logger.info("=== Starting social media collection ===")

    twitter_token = get_env("TWITTER_BEARER_TOKEN")

    dedup = DedupEngine("social_media_seen.json")
    gen = PostGenerator("crypto-news")  # Social posts go to crypto-news

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    now = datetime.now(timezone.utc)

    # Collect Telegram messages
    telegram_items = []
    channels = [
        "cryptonews", "crypto", "CoinDesk", "BitcoinMagazine", "WuBlockchain", "coinlounge",
        "whale_alert", "DefiLlama", "OKX_Announcements", "BybitOfficial", "BTCKorea", "upbitofficial",
    ]

    # Try browser session for all channels (single session, reuse connection)
    if is_playwright_available():
        browser_results = _fetch_telegram_browser(channels)
        for ch in channels:
            telegram_items.extend(browser_results.get(ch, []))
        # Fallback: fetch remaining channels that failed via requests
        failed_channels = [ch for ch in channels if ch not in browser_results or not browser_results[ch]]
        for ch in failed_channels:
            telegram_items.extend(fetch_telegram_channel(ch))
            time.sleep(2)
    else:
        for ch in channels:
            telegram_items.extend(fetch_telegram_channel(ch))
            time.sleep(2)

    # Collect Twitter/X and Google News social items
    social_items = []
    if twitter_token:
        queries = [
            "bitcoin OR ethereum min_faves:100",
            "crypto market lang:en min_faves:50",
            "Trump crypto OR bitcoin min_faves:50",
            "이재명 경제 OR 주식 OR 암호화폐 lang:ko min_faves:20",
            "코스피 OR 코스닥 주식 lang:ko min_faves:20",
            "비트코인 OR 이더리움 lang:ko min_faves:30",
        ]
        for q in queries:
            social_items.extend(fetch_twitter_search(twitter_token, q))
            time.sleep(1)

    social_items.extend(fetch_google_news_social())

    # Collect Reddit posts
    reddit_items = fetch_reddit_posts()

    # Collect political/economy news (Trump, 이재명, Fed, 한국은행)
    political_items = fetch_political_economy_news()

    # ── Consolidated social media post ──
    post_title = f"소셜 미디어 동향 - {today}"

    if dedup.is_duplicate_exact(post_title, "consolidated", today):
        logger.info("Consolidated social media post already exists, skipping")
        dedup.save()
        return

    # Combine all items for theme analysis
    all_theme_items = telegram_items + social_items + reddit_items + political_items

    # Create theme summarizer
    summarizer = ThemeSummarizer(all_theme_items)

    total_count = len(telegram_items) + len(social_items) + len(reddit_items) + len(political_items)

    if total_count == 0:
        logger.warning("No social media items collected, skipping post")
        dedup.save()
        return

    # Data-driven opening (only mention sources with data)
    source_parts = []
    if telegram_items:
        source_parts.append(f"텔레그램 {len(telegram_items)}건")
    if social_items:
        source_parts.append(f"소셜 미디어 {len(social_items)}건")
    if reddit_items:
        source_parts.append(f"Reddit {len(reddit_items)}건")
    if political_items:
        source_parts.append(f"정치·경제 {len(political_items)}건")
    sources_str = ", ".join(source_parts) if source_parts else "데이터 없음"
    content_parts = [f"**{today}** 암호화폐·주식 커뮤니티 소셜 미디어 동향을 정리합니다. {sources_str}, 총 {total_count}건이 수집되었습니다.\n"]

    # Collect all source links
    source_links = []

    # Key summary
    content_parts.append("## 핵심 요약\n")
    content_parts.append(f"- **총 수집 건수**: {total_count}건")
    content_parts.append(f"- **텔레그램**: {len(telegram_items)}건")
    content_parts.append(f"- **소셜 미디어/뉴스**: {len(social_items)}건")
    content_parts.append(f"- **Reddit**: {len(reddit_items)}건")
    content_parts.append(f"- **정치·경제**: {len(political_items)}건")

    # Keyword analysis across all items
    all_texts = " ".join(
        item.get("title", "") + " " + item.get("description", "")
        for item in telegram_items + social_items + reddit_items + political_items
    ).lower()
    keyword_targets = ["bitcoin", "ethereum", "trump", "이재명", "kospi", "fed", "regulation", "ai"]
    keyword_hits = {kw: len(re.findall(re.escape(kw), all_texts, re.IGNORECASE))
                    for kw in keyword_targets}
    top_keywords = [(kw, cnt) for kw, cnt in sorted(keyword_hits.items(), key=lambda x: -x[1]) if cnt > 0]
    if top_keywords:
        kw_str = ", ".join(f"{kw}({cnt})" for kw, cnt in top_keywords[:5])
        content_parts.append(f"- **주요 키워드**: {kw_str}")

    # 오늘의 핵심 bullet points
    content_parts.append("\n## 오늘의 핵심\n")
    highlights = []
    if top_keywords:
        highlights.append(f"- 가장 많이 언급된 키워드는 **{top_keywords[0][0]}**({top_keywords[0][1]}회)입니다.")
    active_sources = []
    if telegram_items:
        active_sources.append(f"텔레그램({len(telegram_items)}건)")
    if reddit_items:
        active_sources.append(f"Reddit({len(reddit_items)}건)")
    if social_items:
        active_sources.append(f"소셜 미디어({len(social_items)}건)")
    if political_items:
        active_sources.append(f"정치·경제({len(political_items)}건)")
    if active_sources:
        highlights.append(f"- 가장 활발한 채널: {', '.join(active_sources[:3])}")
    if total_count >= 30:
        highlights.append(f"- 총 {total_count}건의 소셜 데이터가 수집되어 커뮤니티 관심이 높은 상황입니다.")
    if not highlights:
        highlights.append(f"- 총 {total_count}건의 소셜 데이터가 수집되었습니다.")
    content_parts.extend(highlights)

    # Executive summary (한눈에 보기)
    exec_summary = summarizer.generate_executive_summary(
        category_type="social",
        extra_data={"top_keywords": top_keywords},
    )
    if exec_summary:
        content_parts.append(exec_summary)

    # Theme distribution chart
    dist = summarizer.generate_distribution_chart()
    if dist:
        content_parts.append("\n" + dist)

    content_parts.append("\n---\n")

    # Source distribution image
    source_dist = []
    if telegram_items:
        source_dist.append({"name": "Telegram", "count": len(telegram_items)})
    if social_items:
        # Break down social items by source
        social_counter = Counter(item.get("source", "Other") for item in social_items)
        for src, cnt in social_counter.most_common():
            source_dist.append({"name": src, "count": cnt})
    if reddit_items:
        source_dist.append({"name": "Reddit", "count": len(reddit_items)})
    if political_items:
        source_dist.append({"name": "Politics/Economy", "count": len(political_items)})

    try:
        from common.image_generator import generate_source_distribution_card
        if source_dist:
            img = generate_source_distribution_card(source_dist, today)
            if img:
                fn = os.path.basename(img)
                web_path = "{{ '/assets/images/generated/" + fn + "' | relative_url }}"
                content_parts.append(f"\n![source-distribution]({web_path})\n")
                logger.info("Generated source distribution image")
    except ImportError:
        pass
    except Exception as e:
        logger.warning("Source distribution image failed: %s", e)

    # Theme briefing section
    theme_briefing = summarizer.generate_theme_briefing()
    if theme_briefing:
        content_parts.append(theme_briefing)

    # Telegram section with descriptions (only show if data exists)
    if telegram_items:
        content_parts.append("## 텔레그램 주요 소식\n")
        for i, item in enumerate(telegram_items[:8], 1):
            title = item["title"].replace("[Telegram] ", "")
            source = item.get("source", "unknown")
            link = item.get("link", "")
            description = item.get("description", "").strip()

            # Collect links for references
            if link:
                source_links.append({"title": item["title"], "link": link, "source": source})
                content_parts.append(f"**{i}. [{title}]({link})**")
            else:
                content_parts.append(f"**{i}. {title}**")
            if description and description != title and i <= 5:
                desc_text = description[:150]
                if len(description) > 150:
                    desc_text += "..."
                content_parts.append(f"{desc_text}")
            content_parts.append(f"`채널: {source}`\n")

        content_parts.append("\n---\n")

    # Social media trends section with descriptions (only show if data exists)
    if social_items:
        content_parts.append("\n## 주요 소셜 미디어 트렌드\n")
        for i, item in enumerate(social_items[:8], 1):
            title = item["title"]
            for prefix in ("[X/Twitter] ", "[Twitter] "):
                title = title.replace(prefix, "")
            source = item.get("source", "unknown")
            link = item.get("link", "")
            description = item.get("description", "").strip()

            if link:
                source_links.append({"title": item["title"], "link": link, "source": source})
                content_parts.append(f"**{i}. [{title}]({link})**")
            else:
                content_parts.append(f"**{i}. {title}**")
            if description and description != title and i <= 5:
                desc_text = description[:150]
                if len(description) > 150:
                    desc_text += "..."
                content_parts.append(f"{desc_text}")
            content_parts.append(f"`출처: {source}`\n")

        content_parts.append("\n---\n")

    # Reddit section (only show if data exists)
    if reddit_items:
        content_parts.append("\n## Reddit 커뮤니티 인기 글\n")
        content_parts.append("| # | 제목 | 커뮤니티 |")
        content_parts.append("|---|------|----------|")
        for i, item in enumerate(reddit_items[:10], 1):
            title = item["title"].replace("[Reddit] ", "")
            source = item.get("source", "unknown")
            link = item.get("link", "")
            score = item.get("score", 0)

            if link:
                source_links.append({"title": item["title"], "link": link, "source": source})
                content_parts.append(f"| {i} | [**{title}**]({link}) | {source} (↑{score}) |")
            else:
                content_parts.append(f"| {i} | **{title}** | {source} (↑{score}) |")

        content_parts.append("\n---\n")

    # Political/Economy trends section with descriptions (only show if data exists)
    if political_items:
        content_parts.append("\n## 정치·경제 동향\n")
        for i, item in enumerate(political_items[:10], 1):
            title = item["title"]
            source = item.get("source", "unknown")
            link = item.get("link", "")
            description = item.get("description", "").strip()

            if link:
                source_links.append({"title": title, "link": link, "source": source})
                content_parts.append(f"**{i}. [{title}]({link})**")
            else:
                content_parts.append(f"**{i}. {title}**")
            if description and description != title and i <= 5:
                desc_text = description[:150]
                if len(description) > 150:
                    desc_text += "..."
                content_parts.append(f"{desc_text}")
            content_parts.append(f"`출처: {source}`\n")

        content_parts.append("\n---\n")

    # Theme summary
    theme_summary = summarizer.generate_summary_section()
    if theme_summary:
        content_parts.append(theme_summary)

    content_parts.append("\n---\n")

    # Social trend analysis
    content_parts.append("\n## 소셜 동향 분석\n")
    trend_lines = []
    if telegram_items:
        # Channel activity analysis
        tg_channels = Counter(item.get("source", "") for item in telegram_items)
        top_channels = tg_channels.most_common(3)
        ch_str = ", ".join(f"{ch}({cnt}건)" for ch, cnt in top_channels)
        trend_lines.append(f"텔레그램에서 가장 활발한 채널은 {ch_str}입니다.")
    if political_items:
        pol_ratio = len(political_items) / max(total_count, 1) * 100
        trend_lines.append(f"정치·경제 관련 뉴스가 전체의 **{pol_ratio:.0f}%**를 차지하고 있어, 정치적 이슈가 시장에 미치는 영향이 큰 상황입니다.")
    if reddit_items:
        trend_lines.append(f"Reddit에서 {len(reddit_items)}건의 인기 글이 수집되었으며, 커뮤니티 관심이 활발합니다.")
    if not trend_lines:
        trend_lines.append("현재 수집된 소셜 데이터가 제한적입니다.")
    trend_lines.append("")
    trend_lines.append("> *본 소셜 동향 분석은 자동 수집된 데이터를 기반으로 생성되었으며, 투자 조언이 아닙니다. 모든 투자 결정은 개인의 판단과 책임 하에 이루어져야 합니다.*")
    content_parts.extend(trend_lines)

    # References section (top 10 only)
    if source_links:
        content_parts.append("\n## 참고 링크\n")
        seen_links = set()
        ref_count = 1
        for ref in source_links[:10]:
            if ref["link"] not in seen_links:
                seen_links.add(ref["link"])
                content_parts.append(f"{ref_count}. [{ref['title'][:80]}]({ref['link']}) - {ref['source']}")
                ref_count += 1

    # Data collection timestamp footer
    content_parts.append(f"\n---\n**데이터 수집 시각**: {now.strftime('%Y-%m-%d %H:%M')} UTC")

    content = "\n".join(content_parts)

    filepath = gen.create_post(
        title=post_title,
        content=content,
        date=now,
        tags=["social-media", "telegram", "twitter", "reddit", "politics", "trump", "이재명", "daily-digest"],
        source="consolidated",
        lang="ko",
        image=f"/assets/images/generated/source-distribution-{today}.png",
        slug="daily-social-media-digest",
    )
    if filepath:
        dedup.mark_seen(post_title, "consolidated", today)
        logger.info("Created consolidated social media post: %s", filepath)

    dedup.save()
    logger.info("=== Social media collection complete ===")


if __name__ == "__main__":
    main()
