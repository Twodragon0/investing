#!/usr/bin/env python3
"""Collect social media posts related to crypto/stocks and generate Jekyll posts.

Sources:
- Telegram public channels (HTML scraping t.me/s/channel)
- Twitter/X API v2 search (Bearer Token)
- Google News RSS fallback for social keywords
"""

import sys
import os
import time
import requests
from datetime import datetime, timezone
from typing import List, Dict, Any
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common.config import get_env, setup_logging, get_ssl_verify
from common.dedup import DedupEngine
from common.post_generator import PostGenerator
from common.utils import sanitize_string, truncate_text

logger = setup_logging("collect_social_media")

VERIFY_SSL = get_ssl_verify()
REQUEST_TIMEOUT = 15
USER_AGENT = "Mozilla/5.0 (compatible; InvestingDragon/1.0)"


def fetch_telegram_channel(channel: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Scrape public Telegram channel messages via t.me/s/ preview."""
    url = f"https://t.me/s/{channel}"
    try:
        resp = requests.get(
            url, timeout=REQUEST_TIMEOUT, verify=VERIFY_SSL,
            headers={"User-Agent": USER_AGENT},
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        items = []
        messages = soup.find_all("div", class_="tgme_widget_message_wrap")

        for msg in messages[-limit:]:
            text_div = msg.find("div", class_="tgme_widget_message_text")
            if not text_div:
                continue

            text = sanitize_string(text_div.get_text(" ", strip=True), 500)
            if not text or len(text) < 20:
                continue

            # Get message date
            date_el = msg.find("time")
            date_str = date_el.get("datetime", "") if date_el else ""

            # Get message link
            link_el = msg.find("a", class_="tgme_widget_message_date")
            link = link_el.get("href", "") if link_el else ""

            # Use first line or first 80 chars as title
            title = text.split("\n")[0][:100]
            if len(title) < 10:
                title = truncate_text(text, 100)

            items.append({
                "title": f"[Telegram] {title}",
                "description": text,
                "link": link,
                "published": date_str,
                "source": f"Telegram @{channel}",
                "tags": ["social-media", "telegram", channel],
            })

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


def fetch_rss_feed(url: str, source_name: str, tags: List[str], limit: int = 10) -> List[Dict[str, Any]]:
    """Fetch from RSS feed as fallback."""
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
                raw = desc_el.get_text(strip=True)
                description = sanitize_string(
                    BeautifulSoup(raw, "html.parser").get_text(" ", strip=True), 500
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


def fetch_reddit_crypto(limit: int = 10) -> List[Dict[str, Any]]:
    """Fetch top posts from crypto-related Reddit subreddits via RSS."""
    subreddits = [
        ("cryptocurrency", "r/CryptoCurrency"),
        ("bitcoin", "r/Bitcoin"),
        ("ethtrader", "r/EthTrader"),
    ]
    all_items = []
    for sub, display_name in subreddits:
        url = f"https://www.reddit.com/r/{sub}/hot.json?limit={limit}"
        try:
            resp = requests.get(
                url, timeout=REQUEST_TIMEOUT, verify=VERIFY_SSL,
                headers={"User-Agent": USER_AGENT},
            )
            resp.raise_for_status()
            data = resp.json()
            for post in data.get("data", {}).get("children", [])[:limit]:
                pd = post.get("data", {})
                title = sanitize_string(pd.get("title", ""), 300)
                if not title or pd.get("stickied"):
                    continue
                score = pd.get("score", 0)
                if score < 50:
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
            logger.info("Reddit %s: fetched %d posts", display_name, len(all_items))
        except requests.exceptions.RequestException as e:
            logger.warning("Reddit %s fetch failed: %s", display_name, e)
        time.sleep(1)

    # Sort by score
    all_items.sort(key=lambda x: x.get("score", 0), reverse=True)
    return all_items[:limit]


def fetch_google_news_social() -> List[Dict[str, Any]]:
    """Google News RSS fallback for social/crypto influencer content."""
    feeds = [
        ("https://news.google.com/rss/search?q=crypto+twitter+sentiment&hl=en-US&gl=US&ceid=US:en",
         "Google News Social EN", ["social-media", "sentiment"]),
        ("https://news.google.com/rss/search?q=암호화폐+커뮤니티+SNS&hl=ko&gl=KR&ceid=KR:ko",
         "Google News Social KR", ["social-media", "korean"]),
        ("https://news.google.com/rss/search?q=crypto+whale+alert+on-chain&hl=en-US&gl=US&ceid=US:en",
         "Whale & On-chain", ["social-media", "whale", "on-chain"]),
    ]
    all_items = []
    for url, name, tags in feeds:
        all_items.extend(fetch_rss_feed(url, name, tags))
        time.sleep(1)
    return all_items


def fetch_political_economy_news() -> List[Dict[str, Any]]:
    """Fetch Trump and 이재명 related economy/crypto news from Google News RSS."""
    feeds = [
        # Trump crypto/economy policy
        ("https://news.google.com/rss/search?q=Trump+crypto+policy&hl=en-US&gl=US&ceid=US:en",
         "Trump Crypto Policy", ["politics", "trump", "crypto"]),
        ("https://news.google.com/rss/search?q=Trump+tariff+economy+stock&hl=en-US&gl=US&ceid=US:en",
         "Trump Economy", ["politics", "trump", "economy"]),
        ("https://news.google.com/rss/search?q=트럼프+암호화폐+경제&hl=ko&gl=KR&ceid=KR:ko",
         "트럼프 경제정책 KR", ["politics", "trump", "korean"]),
        # 이재명 economy/stock policy
        ("https://news.google.com/rss/search?q=이재명+경제+정책&hl=ko&gl=KR&ceid=KR:ko",
         "이재명 경제정책", ["politics", "이재명", "economy"]),
        ("https://news.google.com/rss/search?q=이재명+주식+암호화폐+코인&hl=ko&gl=KR&ceid=KR:ko",
         "이재명 암호화폐정책", ["politics", "이재명", "crypto"]),
        ("https://news.google.com/rss/search?q=이재명+부동산+금리&hl=ko&gl=KR&ceid=KR:ko",
         "이재명 부동산·금리", ["politics", "이재명", "real-estate"]),
        # US Fed / macro
        ("https://news.google.com/rss/search?q=Federal+Reserve+interest+rate+decision&hl=en-US&gl=US&ceid=US:en",
         "Fed Policy", ["politics", "fed", "macro"]),
        # Korea economy/policy
        ("https://news.google.com/rss/search?q=한국은행+금리+경제&hl=ko&gl=KR&ceid=KR:ko",
         "한국은행 금리정책", ["politics", "한국은행", "macro"]),
        ("https://news.google.com/rss/search?q=코스피+외국인+기관+수급&hl=ko&gl=KR&ceid=KR:ko",
         "한국증시 수급", ["stock", "korean", "수급"]),
    ]
    all_items = []
    for url, name, tags in feeds:
        all_items.extend(fetch_rss_feed(url, name, tags))
        time.sleep(1)
    return all_items


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
    channels = ["cryptonews", "crypto", "CoinDesk", "BitcoinMagazine", "WuBlockchain", "coinlounge"]
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
        ]
        for q in queries:
            social_items.extend(fetch_twitter_search(twitter_token, q))
            time.sleep(1)

    social_items.extend(fetch_google_news_social())

    # Collect Reddit posts
    reddit_items = fetch_reddit_crypto()

    # Collect political/economy news (Trump, 이재명, Fed, 한국은행)
    political_items = fetch_political_economy_news()

    # ── Consolidated social media post ──
    post_title = f"소셜 미디어 동향 - {today}"

    if dedup.is_duplicate_exact(post_title, "consolidated", today):
        logger.info("Consolidated social media post already exists, skipping")
        dedup.save()
        return

    total_count = len(telegram_items) + len(social_items) + len(reddit_items) + len(political_items)
    content_parts = [f"오늘의 암호화폐·주식 커뮤니티 소셜 미디어 동향을 정리합니다. 텔레그램 {len(telegram_items)}건, 소셜 미디어 {len(social_items)}건, Reddit {len(reddit_items)}건, 정치·경제 {len(political_items)}건 총 {total_count}건이 수집되었습니다.\n"]

    # Collect all source links
    source_links = []

    # Telegram section (limit to top 10)
    content_parts.append("## 텔레그램 주요 소식\n")
    if telegram_items:
        content_parts.append("| # | 내용 | 채널 |")
        content_parts.append("|---|------|------|")
        for i, item in enumerate(telegram_items[:10], 1):
            title = item["title"].replace("[Telegram] ", "")
            source = item.get("source", "unknown")
            link = item.get("link", "")

            # Collect links for references
            if link:
                source_links.append({"title": item["title"], "link": link, "source": source})
                content_parts.append(f"| {i} | [**{title}**]({link}) | {source} |")
            else:
                content_parts.append(f"| {i} | **{title}** | {source} |")
    else:
        content_parts.append("*수집된 텔레그램 소식이 없습니다.*")

    # Social media trends section (Twitter + Google News social, limit to top 10)
    content_parts.append("\n## 주요 소셜 미디어 트렌드\n")
    if social_items:
        content_parts.append("| # | 제목 | 출처 |")
        content_parts.append("|---|------|------|")
        for i, item in enumerate(social_items[:10], 1):
            title = item["title"]
            # Strip prefix tags for cleaner display
            for prefix in ("[X/Twitter] ", "[Twitter] "):
                title = title.replace(prefix, "")
            source = item.get("source", "unknown")
            link = item.get("link", "")

            # Collect links for references
            if link:
                source_links.append({"title": item["title"], "link": link, "source": source})
                content_parts.append(f"| {i} | [**{title}**]({link}) | {source} |")
            else:
                content_parts.append(f"| {i} | **{title}** | {source} |")
    else:
        content_parts.append("*수집된 소셜 미디어 트렌드가 없습니다.*")

    # Reddit section
    content_parts.append("\n## Reddit 커뮤니티 인기 글\n")
    if reddit_items:
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
    else:
        content_parts.append("*수집된 Reddit 글이 없습니다.*")

    # Political/Economy trends section
    content_parts.append("\n## 정치·경제 동향\n")
    if political_items:
        content_parts.append("| # | 제목 | 출처 |")
        content_parts.append("|---|------|------|")
        for i, item in enumerate(political_items[:15], 1):
            title = item["title"]
            source = item.get("source", "unknown")
            link = item.get("link", "")

            # Collect links for references
            if link:
                source_links.append({"title": title, "link": link, "source": source})
                content_parts.append(f"| {i} | [**{title}**]({link}) | {source} |")
            else:
                content_parts.append(f"| {i} | **{title}** | {source} |")
    else:
        content_parts.append("*수집된 정치·경제 동향이 없습니다.*")

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

    filepath = gen.create_post(
        title=post_title,
        content=content,
        date=now,
        tags=["social-media", "telegram", "twitter", "reddit", "politics", "trump", "이재명", "daily-digest"],
        source="consolidated",
        lang="ko",
        slug="daily-social-media-digest",
    )
    if filepath:
        dedup.mark_seen(post_title, "consolidated", today)
        logger.info("Created consolidated social media post: %s", filepath)

    dedup.save()
    logger.info("=== Social media collection complete ===")


if __name__ == "__main__":
    main()
