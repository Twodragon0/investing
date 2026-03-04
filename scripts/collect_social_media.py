#!/usr/bin/env python3
"""Collect social media posts related to crypto/stocks and generate Jekyll posts.

Sources:
- Telegram public channels (HTML scraping t.me/s/channel)
- Twitter/X API v2 search (Bearer Token)
- Google News RSS fallback for social keywords
"""

import os
import re
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from typing import Any, Dict, List

import requests
from bs4 import BeautifulSoup

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
from common.markdown_utils import (
    html_reference_details,
    html_source_tag,
    markdown_link,
    markdown_table,
    smart_truncate,
)
from common.post_generator import PostGenerator
from common.rss_fetcher import fetch_rss_feeds_concurrent
from common.summarizer import ThemeSummarizer
from common.translator import get_display_title
from common.utils import (
    remove_sponsored_text,
    request_with_retry,
    sanitize_string,
    truncate_text,
)

try:
    from common.browser import BrowserSession, is_playwright_available
except ImportError:
    BrowserSession = None  # type: ignore[assignment,misc]

    def is_playwright_available() -> bool:  # type: ignore[misc]
        return False


logger = setup_logging("collect_social_media")

VERIFY_SSL = get_ssl_verify()


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

            text = remove_sponsored_text(text)
            if not text or len(text) < 20:
                continue

            title = truncate_text(text.split("\n")[0], 100)
            if len(title) < 10:
                title = truncate_text(text, 100)

            items.append(
                {
                    "title": f"[Telegram] {title}",
                    "description": text,
                    "link": link or "",
                    "published": date_str or "",
                    "source": f"Telegram @{channel}",
                    "tags": ["social-media", "telegram", channel],
                }
            )
        except (AttributeError, TypeError, IndexError) as e:
            logger.debug("Telegram RSS item parse error: %s", e)
            continue
    return items


def _fetch_telegram_browser(channels: List[str], limit: int = 10) -> Dict[str, List[Dict[str, Any]]]:
    """Fetch multiple Telegram channels in a single browser session."""
    results: Dict[str, List[Dict[str, Any]]] = {}
    if not is_playwright_available():
        return results
    if BrowserSession is None:
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
                    except Exception as e:
                        logger.debug("Telegram wait timeout for @%s: %s", channel, e)
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
            url,
            timeout=REQUEST_TIMEOUT,
            verify=VERIFY_SSL,
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
        resp = requests.get(
            url,
            headers=headers,
            params=params,
            timeout=REQUEST_TIMEOUT,
            verify=VERIFY_SSL,
        )
        resp.raise_for_status()
        data = resp.json()

        items = []
        for tweet in data.get("data", []):
            text = sanitize_string(tweet.get("text", ""), 500)
            if not text:
                continue

            tweet_id = tweet.get("id", "")
            title = truncate_text(text, 100)

            items.append(
                {
                    "title": f"[X/Twitter] {title}",
                    "description": text,
                    "link": f"https://twitter.com/i/web/status/{tweet_id}" if tweet_id else "",
                    "published": tweet.get("created_at", ""),
                    "source": "Twitter/X",
                    "tags": ["social-media", "twitter"],
                }
            )

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
                url,
                timeout=REQUEST_TIMEOUT,
                verify_ssl=VERIFY_SSL,
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
                all_items.append(
                    {
                        "title": f"[Reddit] {title}",
                        "description": truncate_text(pd.get("selftext", ""), 300),
                        "link": f"https://reddit.com{pd.get('permalink', '')}",
                        "published": "",
                        "source": display_name,
                        "tags": ["social-media", "reddit", sub],
                        "score": score,
                    }
                )
                sub_count += 1
            logger.info("Reddit %s: fetched %d posts", display_name, sub_count)
        except requests.exceptions.RequestException as e:
            logger.warning("Reddit %s fetch failed: %s", display_name, e)
            if hasattr(e, "response") and e.response is not None and e.response.status_code == 429:
                logger.warning("Reddit rate limited (429), stopping remaining subreddit fetches")
                break
        time.sleep(1)

    # Sort by score
    all_items.sort(key=lambda x: x.get("score", 0), reverse=True)
    return all_items[: limit * 2]


def fetch_google_news_social() -> List[Dict[str, Any]]:
    """Google News RSS fallback for social/crypto influencer content (concurrent)."""
    feeds = [
        (
            "https://news.google.com/rss/search?q=crypto+twitter+sentiment&hl=en-US&gl=US&ceid=US:en",
            "Google News Social EN",
            ["social-media", "sentiment"],
        ),
        (
            "https://news.google.com/rss/search?q=암호화폐+커뮤니티+SNS&hl=ko&gl=KR&ceid=KR:ko",
            "Google News Social KR",
            ["social-media", "korean"],
        ),
        (
            "https://news.google.com/rss/search?q=crypto+whale+alert+on-chain&hl=en-US&gl=US&ceid=US:en",
            "Whale & On-chain",
            ["social-media", "whale", "on-chain"],
        ),
    ]
    return fetch_rss_feeds_concurrent(feeds)


def fetch_political_economy_news() -> List[Dict[str, Any]]:
    """Fetch Trump and 이재명 related economy/crypto news (concurrent)."""
    feeds = [
        (
            "https://news.google.com/rss/search?q=Trump+crypto+policy&hl=en-US&gl=US&ceid=US:en",
            "Trump Crypto Policy",
            ["politics", "trump", "crypto"],
        ),
        (
            "https://news.google.com/rss/search?q=Trump+tariff+economy+stock&hl=en-US&gl=US&ceid=US:en",
            "Trump Economy",
            ["politics", "trump", "economy"],
        ),
        (
            "https://news.google.com/rss/search?q=트럼프+암호화폐+경제&hl=ko&gl=KR&ceid=KR:ko",
            "트럼프 경제정책 KR",
            ["politics", "trump", "korean"],
        ),
        (
            "https://news.google.com/rss/search?q=이재명+경제+정책&hl=ko&gl=KR&ceid=KR:ko",
            "이재명 경제정책",
            ["politics", "이재명", "economy"],
        ),
        (
            "https://news.google.com/rss/search?q=이재명+주식+암호화폐+코인&hl=ko&gl=KR&ceid=KR:ko",
            "이재명 암호화폐정책",
            ["politics", "이재명", "crypto"],
        ),
        (
            "https://news.google.com/rss/search?q=이재명+부동산+금리&hl=ko&gl=KR&ceid=KR:ko",
            "이재명 부동산·금리",
            ["politics", "이재명", "real-estate"],
        ),
        (
            "https://news.google.com/rss/search?q=Federal+Reserve+interest+rate+decision&hl=en-US&gl=US&ceid=US:en",
            "Fed Policy",
            ["politics", "fed", "macro"],
        ),
        (
            "https://news.google.com/rss/search?q=한국은행+금리+경제&hl=ko&gl=KR&ceid=KR:ko",
            "한국은행 금리정책",
            ["politics", "한국은행", "macro"],
        ),
        (
            "https://news.google.com/rss/search?q=코스피+외국인+기관+수급&hl=ko&gl=KR&ceid=KR:ko",
            "한국증시 수급",
            ["stock", "korean", "수급"],
        ),
    ]
    return fetch_rss_feeds_concurrent(feeds)


def main():
    """Main social media collection routine - consolidated post."""
    logger.info("=== Starting social media collection ===")
    started_at = time.monotonic()

    twitter_token = get_env("TWITTER_BEARER_TOKEN")

    dedup = DedupEngine("social_media_seen.json")
    gen = PostGenerator("crypto-news")  # Social posts go to crypto-news

    today = datetime.now(UTC).strftime("%Y-%m-%d")
    now = datetime.now(UTC)

    # Collect Telegram messages
    telegram_items = []
    channels = [
        "cryptonews",
        "crypto",
        "CoinDesk",
        "BitcoinMagazine",
        "WuBlockchain",
        "coinlounge",
        "whale_alert",
        "DefiLlama",
        "OKX_Announcements",
        "BybitOfficial",
        "BTCKorea",
        "upbitofficial",
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
        combined_items = telegram_items + social_items + reddit_items + political_items
        unique_count = len(
            {
                f"{item.get('title', '')}|{item.get('source', '')}|{item.get('link', '')}"
                for item in combined_items
                if item.get("title")
            }
        )
        source_count = len({item.get("source", "") for item in combined_items if item.get("source")})
        log_collection_summary(
            logger,
            collector="collect_social_media",
            source_count=source_count,
            unique_items=unique_count,
            post_created=0,
            started_at=started_at,
        )
        dedup.save()
        return

    # Combine all items for theme analysis
    all_theme_items = telegram_items + social_items + reddit_items + political_items

    # Create theme summarizer
    summarizer = ThemeSummarizer(all_theme_items)

    total_count = len(telegram_items) + len(social_items) + len(reddit_items) + len(political_items)

    if total_count == 0:
        logger.warning("No social media items collected, skipping post")
        log_collection_summary(
            logger,
            collector="collect_social_media",
            source_count=0,
            unique_items=0,
            post_created=0,
            started_at=started_at,
        )
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
    content_parts = [
        f"**{today}** 암호화폐·주식 커뮤니티 소셜 미디어 동향을 정리합니다. {sources_str}, 총 {total_count}건이 수집되었습니다.\n"
    ]

    # Collect all source links
    source_links = []

    # Executive summary (한눈에 보기)
    exec_summary = summarizer.generate_executive_summary(
        category_type="social",
        extra_data={"top_keywords": []},
    )
    if exec_summary:
        content_parts.append(exec_summary)

    summary_points = []
    if telegram_items or social_items or reddit_items or political_items:
        points = []
        if telegram_items:
            points.append(f"텔레그램 {len(telegram_items)}건")
        if social_items:
            points.append(f"소셜 {len(social_items)}건")
        if reddit_items:
            points.append(f"Reddit {len(reddit_items)}건")
        if political_items:
            points.append(f"정치·경제 {len(political_items)}건")
        if points:
            summary_points.append(", ".join(points))
    overall_summary = summarizer.generate_overall_summary_section(extra_data={"summary_points": summary_points})
    if overall_summary:
        content_parts.append(overall_summary)

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

    distribution_image_path = ""
    try:
        from common.image_generator import generate_source_distribution_card

        if source_dist:
            img = generate_source_distribution_card(source_dist, today)
            if img:
                fn = os.path.basename(img)
                distribution_image_path = f"/assets/images/generated/{fn}"
                web_path = "{{ '/assets/images/generated/" + fn + "' | relative_url }}"
                content_parts.append(f"\n![source-distribution]({web_path})\n")
                logger.info("Generated source distribution image")
    except ImportError as e:
        logger.debug("Optional dependency unavailable: %s", e)
    except Exception as e:
        logger.warning("Source distribution image failed: %s", e)

    # Telegram section with descriptions (only show if data exists)
    if telegram_items:
        content_parts.append("## 텔레그램 주요 소식\n")
        for i, item in enumerate(telegram_items[:8], 1):
            title = get_display_title(item).replace("[Telegram] ", "")
            source = item.get("source", "unknown")
            link = item.get("link", "")
            description = (item.get("description_ko") or item.get("description", "")).strip()

            # Collect links for references
            if link:
                source_links.append(item)
                content_parts.append(f"**{i}. [{title}]({link})**")
            else:
                content_parts.append(f"**{i}. {title}**")
            if description and description != title:
                desc_text = smart_truncate(description, 150)
                content_parts.append(f"{desc_text}")
            content_parts.append(f"{html_source_tag(source)}\n")

        content_parts.append("\n---\n")

    # Social media trends section with descriptions (only show if data exists)
    if social_items:
        content_parts.append("\n## 주요 소셜 미디어 트렌드\n")
        for i, item in enumerate(social_items[:8], 1):
            title = get_display_title(item)
            for prefix in ("[X/Twitter] ", "[Twitter] "):
                title = title.replace(prefix, "")
            source = item.get("source", "unknown")
            link = item.get("link", "")
            description = (item.get("description_ko") or item.get("description", "")).strip()

            if link:
                source_links.append(item)
                content_parts.append(f"**{i}. [{title}]({link})**")
            else:
                content_parts.append(f"**{i}. {title}**")
            if description and description != title:
                desc_text = smart_truncate(description, 150)
                content_parts.append(f"{desc_text}")
            content_parts.append(f"{html_source_tag(source)}\n")

        content_parts.append("\n---\n")

    # Reddit section (only show if data exists)
    if reddit_items:
        content_parts.append("\n## Reddit 커뮤니티 인기 글\n")
        reddit_rows = []
        for i, item in enumerate(reddit_items[:10], 1):
            title = get_display_title(item).replace("[Reddit] ", "")
            source = item.get("source", "unknown")
            link = item.get("link", "")
            score = item.get("score", 0)

            if link:
                source_links.append(item)
                title_cell = markdown_link(f"**{title}**", link)
            else:
                title_cell = f"**{title}**"
            reddit_rows.append((i, title_cell, f"{source} (↑{score})"))

        if reddit_rows:
            content_parts.append(markdown_table(["#", "제목", "커뮤니티"], reddit_rows))

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
            if description and description != title:
                desc_text = smart_truncate(description, 150)
                content_parts.append(f"{desc_text}")
            content_parts.append(f"{html_source_tag(source)}\n")

        content_parts.append("\n---\n")

    # Theme summary
    theme_summary = summarizer.generate_summary_section()
    if theme_summary:
        content_parts.append(theme_summary)

    content_parts.append("\n---\n")

    # Social trend analysis - data-driven narrative
    content_parts.append("\n## 소셜 동향 분석\n")
    trend_lines = []

    # Sentiment keyword detection across all items
    _BULLISH_KW = [
        "bullish",
        "강세",
        "상승",
        "rally",
        "moon",
        "breakout",
        "돌파",
        "pump",
        "ath",
        "신고가",
        "매수",
        "buy",
        "long",
    ]
    _BEARISH_KW = [
        "bearish",
        "약세",
        "하락",
        "crash",
        "dump",
        "폭락",
        "급락",
        "sell",
        "short",
        "매도",
        "correction",
        "조정",
        "fear",
    ]
    bullish_count = 0
    bearish_count = 0
    all_social_texts = " ".join(
        item.get("title", "").lower() + " " + item.get("description", "").lower() for item in all_theme_items
    )
    for kw in _BULLISH_KW:
        bullish_count += all_social_texts.count(kw)
    for kw in _BEARISH_KW:
        bearish_count += all_social_texts.count(kw)

    # Trending topic extraction from titles
    word_counter: Counter = Counter()
    _TREND_STOP = {
        "the",
        "and",
        "for",
        "are",
        "that",
        "this",
        "with",
        "from",
        "has",
        "was",
        "will",
        "its",
        "not",
        "but",
        "you",
        "all",
        "can",
        "had",
        "her",
        "one",
        "our",
        "out",
        "been",
        "have",
        "new",
        "now",
        "old",
        "see",
        "way",
        "who",
        "did",
        "get",
        "let",
        "say",
        "she",
        "too",
        "use",
        "how",
        "man",
        "day",
        "관련",
        "오늘",
        "최근",
        "현재",
        "시장",
        "뉴스",
        "이슈",
        "대한",
        "것으로",
        "있는",
        "것이",
        "하는",
        "했다",
        "위해",
    }
    for item in all_theme_items:
        words = re.findall(r"[a-zA-Z가-힣]{3,}", item.get("title", ""))
        for w in words:
            wl = w.lower()
            if wl not in _TREND_STOP and len(wl) >= 3:
                word_counter[wl] += 1

    trending_words = [(w, c) for w, c in word_counter.most_common(10) if c >= 3]

    # Theme-based opening with sentiment
    top_themes = summarizer.get_top_themes()
    if top_themes:
        theme_str = ", ".join(f"**{t[0]}**" for t in top_themes[:3])
        if bullish_count > bearish_count * 1.5:
            sentiment_note = "전반적으로 **낙관적** 분위기가 감지됩니다."
        elif bearish_count > bullish_count * 1.5:
            sentiment_note = "전반적으로 **경계** 분위기가 우세합니다."
        else:
            sentiment_note = "낙관·비관 의견이 혼재하는 **혼조** 분위기입니다."
        trend_lines.append(f"오늘 소셜 미디어에서는 {theme_str} 관련 논의가 가장 활발하며, {sentiment_note}")

    # Sentiment ratio detail
    total_sentiment = bullish_count + bearish_count
    if total_sentiment >= 5:
        bull_pct = bullish_count / total_sentiment * 100
        bear_pct = bearish_count / total_sentiment * 100
        trend_lines.append(
            f"\n**감성 분석**: 긍정 키워드 {bullish_count}회({bull_pct:.0f}%) vs "
            f"부정 키워드 {bearish_count}회({bear_pct:.0f}%). "
            f"{'매수 심리 우세' if bull_pct > 60 else '매도 심리 우세' if bear_pct > 60 else '심리 균형 상태'}입니다."
        )

    # Trending topics
    if trending_words:
        tw_str = ", ".join(f"**{w}**({c}회)" for w, c in trending_words[:5])
        trend_lines.append(f"\n**트렌딩 토픽**: {tw_str}")

    if telegram_items:
        # Channel activity analysis with content focus
        tg_channels = Counter(item.get("source", "") for item in telegram_items)
        top_channels = tg_channels.most_common(3)
        ch_str = ", ".join(f"{ch}({cnt}건)" for ch, cnt in top_channels)
        # Extract dominant channel topics
        top_ch_name = top_channels[0][0] if top_channels else ""
        top_ch_items = [item for item in telegram_items if item.get("source") == top_ch_name]
        ch_topic = ""
        if top_ch_items:
            ch_title = get_display_title(top_ch_items[0]).replace("[Telegram] ", "")
            if ch_title:
                ch_topic = f" 최신 메시지: *{ch_title[:80]}*"
        trend_lines.append(f"\n**텔레그램**: 활발한 채널 — {ch_str}. 총 {len(telegram_items)}건 포착.{ch_topic}")

    if political_items:
        pol_ratio = len(political_items) / max(total_count, 1) * 100
        # Identify dominant political topic
        pol_topics = Counter()
        for item in political_items:
            title = item.get("title", "").lower()
            if "trump" in title or "트럼프" in title:
                pol_topics["트럼프"] += 1
            elif "이재명" in title:
                pol_topics["이재명"] += 1
            elif "fed" in title or "금리" in title or "한국은행" in title:
                pol_topics["금리/통화정책"] += 1
            elif "관세" in title or "tariff" in title:
                pol_topics["관세/무역"] += 1
        top_pol = pol_topics.most_common(1)
        pol_focus = f" 핵심 화두는 **{top_pol[0][0]}**({top_pol[0][1]}건)." if top_pol else ""
        trend_lines.append(
            f"\n**정치·경제**: 전체의 **{pol_ratio:.0f}%**({len(political_items)}건).{pol_focus} "
            f"정책 이벤트는 시장 센티먼트에 즉각 반영되므로 관련 자산의 변동성에 유의하세요."
        )

    if reddit_items:
        # Reddit sentiment from scores
        avg_score = sum(item.get("score", 0) for item in reddit_items) / max(len(reddit_items), 1)
        top_reddit = reddit_items[0] if reddit_items else None
        reddit_highlight = ""
        if top_reddit:
            r_title = get_display_title(top_reddit).replace("[Reddit] ", "")
            r_score = top_reddit.get("score", 0)
            reddit_highlight = f" 최고 인기 글: *{r_title[:70]}* (↑{r_score})"
        trend_lines.append(f"\n**Reddit**: {len(reddit_items)}건 수집, 평균 스코어 {avg_score:.0f}.{reddit_highlight}")

    if not trend_lines:
        trend_lines.append("현재 수집된 소셜 데이터가 제한적입니다.")
    trend_lines.append("")
    trend_lines.append(
        "> *본 소셜 동향 분석은 자동 수집된 데이터를 기반으로 생성되었으며, "
        "투자 조언이 아닙니다. 모든 투자 결정은 개인의 판단과 책임 하에 이루어져야 합니다.*"
    )
    content_parts.extend(trend_lines)

    # References section (top 10 only) - collapsible
    if source_links:
        content_parts.append(
            html_reference_details(
                "참고 링크",
                source_links,
                limit=10,
                title_max_len=80,
            )
        )

    # Data collection timestamp footer
    content_parts.append(f"\n---\n**데이터 수집 시각**: {now.strftime('%Y-%m-%d %H:%M')} UTC")

    content = "\n".join(content_parts)

    filepath = gen.create_post(
        title=post_title,
        content=content,
        date=now,
        tags=[
            "social-media",
            "telegram",
            "twitter",
            "reddit",
            "politics",
            "trump",
            "이재명",
            "daily-digest",
        ],
        source="consolidated",
        lang="ko",
        image=distribution_image_path,
        slug="daily-social-media-digest",
    )
    if filepath:
        dedup.mark_seen(post_title, "consolidated", today)
        logger.info("Created consolidated social media post: %s", filepath)

    dedup.save()
    logger.info("=== Social media collection complete ===")
    combined_items = telegram_items + social_items + reddit_items + political_items
    unique_count = len(
        {
            f"{item.get('title', '')}|{item.get('source', '')}|{item.get('link', '')}"
            for item in combined_items
            if item.get("title")
        }
    )
    source_count = len({item.get("source", "") for item in combined_items if item.get("source")})
    log_collection_summary(
        logger,
        collector="collect_social_media",
        source_count=source_count,
        unique_items=unique_count,
        post_created=1 if filepath else 0,
        started_at=started_at,
    )


if __name__ == "__main__":
    main()
