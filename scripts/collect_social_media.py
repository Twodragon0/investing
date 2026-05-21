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
from typing import Any, Dict, List

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common.base_collector import BaseCollector
from common.collector_config import get_collector_config, get_url
from common.config import (
    REQUEST_TIMEOUT,
    USER_AGENT,
    get_env,
    get_verify_ssl,
    setup_logging,
)
from common.dedup import deduplicate_by_url
from common.enrichment import _SOCIAL_SOURCE_CONTEXT, enrich_items
from common.markdown_utils import (
    html_reference_details,
    html_source_tag,
    markdown_link,
    markdown_table,
    smart_truncate,
)
from common.post_generator import build_dated_permalink
from common.rss_fetcher import fetch_rss_feeds_concurrent
from common.summarizer import ThemeSummarizer
from common.translator import get_display_title, translate_to_korean
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

VERIFY_SSL = get_verify_ssl()
# collectors.yml에서 설정 로드
_social_cfg = get_collector_config("social_media")


# ---------------------------------------------------------------------------
# 엔터테인먼트/스포츠 필터 (금융·투자와 무관한 콘텐츠 제외)
# ---------------------------------------------------------------------------

_ENTERTAINMENT_KEYWORDS_DEFAULT = frozenset(
    {
        # 북미 스포츠 리그
        "nba",
        "nhl",
        "nfl",
        "mlb",
        "mls",
        "ufc",
        # 국제 스포츠
        "fifa",
        "premier league",
        "champions league",
        "la liga",
        "serie a",
        "bundesliga",
        "world cup soccer",
        "olympics",
        "wimbledon",
        "grand prix",
        "formula 1",
        " f1 ",
        # 개별 이벤트/시즌
        "stanley cup",
        "super bowl",
        "world series",
        "nba finals",
        "nhl finals",
        "championship",
        "playoffs",
        "playoff",
        "mvp",
        "ballon d'or",
        # NBA 팀명
        "lakers",
        "celtics",
        "knicks",
        "warriors",
        "spurs",
        "clippers",
        "heat",
        "bulls",
        "nets",
        "pacers",
        "cavaliers",
        "nuggets",
        "timberwolves",
        "thunder",
        "suns",
        "mavericks",
        "rockets",
        "grizzlies",
        "pelicans",
        "hawks",
        "hornets",
        "magic",
        "wizards",
        "bucks",
        "raptors",
        "sixers",
        "pistons",
        # 연예·미디어
        "oscar",
        "grammy",
        "emmy",
        "golden globe",
        "netflix",
        "spotify",
        "disney+",
        "hulu",
        "hbo",
        "celebrity",
        "movie",
        "album",
        "box office",
        "billboard",
        "reality tv",
        "tv show",
        "season finale",
        "bachelor",
        "bachelorette",
        "survivor",
        # 게임
        "gta vi",
        "gta 6",
        "esport",
        "e-sport",
        "video game",
        "game release",
    }
)


def _load_entertainment_filter() -> frozenset:
    """collectors.yml의 social_media.keywords.entertainment_keywords를 로드합니다.

    로드 실패 또는 섹션 누락 시 하드코딩 기본값으로 fallback합니다.
    """
    kw_cfg = _social_cfg.get("keywords", {})
    if not isinstance(kw_cfg, dict):
        logger.debug("collectors.yml: social_media.keywords 섹션 없음, 기본값 사용")
        return _ENTERTAINMENT_KEYWORDS_DEFAULT

    ent_raw = kw_cfg.get("entertainment_keywords")
    if isinstance(ent_raw, list) and ent_raw:
        logger.debug("collectors.yml에서 entertainment_keywords %d개 로드", len(ent_raw))
        return frozenset(ent_raw)

    logger.debug("collectors.yml: social_media.entertainment_keywords 누락, 기본값 사용")
    return _ENTERTAINMENT_KEYWORDS_DEFAULT


# 모듈 import 시 1회 로드
_ENTERTAINMENT_KEYWORDS = _load_entertainment_filter()


def _is_entertainment(item: Dict[str, Any]) -> bool:
    """title + description에 엔터테인먼트/스포츠 키워드가 포함되면 True."""
    text = (item.get("title", "") + " " + item.get("description", "")).lower()
    return any(kw in text for kw in _ENTERTAINMENT_KEYWORDS)


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
        with BrowserSession() as session:
            for channel in channels:
                try:
                    session.navigate(
                        get_url("social_media", "telegram_channel", "https://t.me/s/{channel}").format(channel=channel),
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
    url = get_url("social_media", "telegram_channel", "https://t.me/s/{channel}").format(channel=channel)
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

    url = get_url("social_media", "twitter_search", "https://api.twitter.com/2/tweets/search/recent")
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
    _reddit_hot_tpl = get_url(
        "social_media", "reddit_hot", "https://www.reddit.com/r/{subreddit}/hot.json?limit={limit}"
    )
    for sub, display_name, min_score in subreddits:
        url = _reddit_hot_tpl.format(subreddit=sub, limit=limit)
        try:
            resp = request_with_retry(
                url,
                timeout=REQUEST_TIMEOUT,
                verify_ssl=VERIFY_SSL,
                headers={"User-Agent": USER_AGENT},
            )
            data = resp.json()
            sub_count = 0
            for post in (data.get("data") or {}).get("children", [])[:limit]:
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
            get_url(
                "social_media",
                "google_news_crypto_twitter",
                "https://news.google.com/rss/search?q=crypto+twitter+sentiment&hl=en-US&gl=US&ceid=US:en",
            ),
            "Google News Social EN",
            ["social-media", "sentiment"],
        ),
        (
            get_url(
                "social_media",
                "google_news_crypto_social_kr",
                "https://news.google.com/rss/search?q=암호화폐+커뮤니티+SNS&hl=ko&gl=KR&ceid=KR:ko",
            ),
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


class SocialMediaCollector(BaseCollector):
    """소셜 미디어 뉴스 수집기.

    텔레그램, Twitter/X, Reddit, Google News 등
    다양한 소셜 미디어 소스에서 뉴스를 수집하고 종합 포스트를 생성합니다.
    """

    name = "social_media"
    category = "social-media"
    state_file = "social_media_seen.json"

    def fetch(self) -> List[Dict[str, Any]]:
        """모든 소스에서 뉴스 항목을 수집합니다."""
        # run()에서 소스별로 개별 수집하므로 여기서는 빈 리스트 반환
        return []

    def process(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """URL 기반 중복 제거."""
        return deduplicate_by_url(items)

    def build_content(self, items: List[Dict[str, Any]]) -> str:
        """소셜 미디어 포스트 본문을 생성합니다."""
        # run()에서 직접 처리하므로 여기서는 빈 문자열 반환
        return ""

    def run(self) -> None:
        """메인 실행 파이프라인 — 종합 소셜 미디어 포스트 생성."""
        self.logger.info("=== Starting social media collection ===")
        self._started_at = time.monotonic()

        today = self.today
        now = self.now

        twitter_token = get_env("TWITTER_BEARER_TOKEN")

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

        # ── Enrich items (URL descriptions + Korean translation) ──
        # Telegram items already have descriptions (full message text),
        # but need translation. Political/social items need both enrichment and translation.
        enrich_items(telegram_items, context_map=_SOCIAL_SOURCE_CONTEXT, fetch_url=False)
        enrich_items(social_items, context_map=_SOCIAL_SOURCE_CONTEXT, fetch_url=True, max_fetch=25)
        enrich_items(reddit_items, context_map=_SOCIAL_SOURCE_CONTEXT, fetch_url=False)
        enrich_items(political_items, context_map=_SOCIAL_SOURCE_CONTEXT, fetch_url=True, max_fetch=25)
        # URL dedup across all sources
        social_items = deduplicate_by_url(social_items)
        political_items = deduplicate_by_url(political_items)
        self.logger.info(
            "Enrichment complete: telegram=%d, social=%d, reddit=%d, political=%d",
            len(telegram_items),
            len(social_items),
            len(reddit_items),
            len(political_items),
        )

        # ── 엔터테인먼트/스포츠 필터 — post 생성 전 적용 ──
        before_counts = (len(telegram_items), len(social_items), len(reddit_items), len(political_items))
        telegram_items = [i for i in telegram_items if not _is_entertainment(i)]
        social_items = [i for i in social_items if not _is_entertainment(i)]
        reddit_items = [i for i in reddit_items if not _is_entertainment(i)]
        political_items = [i for i in political_items if not _is_entertainment(i)]
        after_counts = (len(telegram_items), len(social_items), len(reddit_items), len(political_items))
        filtered_total = sum(b - a for b, a in zip(before_counts, after_counts, strict=False))
        if filtered_total:
            self.logger.info(
                "Entertainment filter removed %d items: telegram=%d, social=%d, reddit=%d, political=%d",
                filtered_total,
                *after_counts,
            )
            self.record_entertainment_filtered(filtered_total)

        # ── Consolidated social media post ──
        post_title = f"소셜 미디어 동향 - {today}"

        if self.is_duplicate_exact(post_title, "consolidated"):
            self.logger.info("Consolidated social media post already exists, skipping")
            combined_items = telegram_items + social_items + reddit_items + political_items
            self.save_state()
            self.log_summary(combined_items)
            return

        # Combine all items for theme analysis
        all_theme_items = telegram_items + social_items + reddit_items + political_items

        # Create theme summarizer
        summarizer = ThemeSummarizer(all_theme_items)

        total_count = len(telegram_items) + len(social_items) + len(reddit_items) + len(political_items)

        if total_count == 0:
            self.logger.warning("No social media items collected, skipping post")
            self.save_state()
            self.log_summary([])
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
        _top_title_words = [w for item in all_theme_items for w in (item.get("title") or "").split() if len(w) > 1]
        _topic_counts = Counter(_top_title_words)
        _stopwords = {
            "the",
            "a",
            "an",
            "of",
            "in",
            "on",
            "at",
            "to",
            "is",
            "are",
            "and",
            "for",
            "by",
            "with",
            "from",
            "this",
            "that",
            "it",
            "be",
            "was",
            "이",
            "의",
            "에",
            "을",
            "를",
            "은",
            "는",
            "가",
            "와",
            "과",
            "도",
            "로",
            "에서",
            "하는",
            "한",
            "합니다",
            "됩니다",
        }
        _top_kws = [w for w, _ in _topic_counts.most_common(20) if w.lower() not in _stopwords][:2]
        if _top_kws:
            _opening = f"**{today}** 소셜 미디어에서 가장 많이 언급된 주제: {', '.join(_top_kws)}. {sources_str}, 총 {total_count}건이 수집되었습니다.\n"
        else:
            _opening = f"**{today}** {sources_str}에서 총 {total_count}건의 소셜 미디어 동향이 수집되었습니다.\n"
        content_parts = [_opening]

        # Stat grid - source breakdown
        content_parts.append('<div class="stat-grid">')
        if telegram_items:
            content_parts.append(
                f'<div class="stat-item"><span class="stat-value">{len(telegram_items)}</span>'
                '<span class="stat-label">Telegram</span></div>'
            )
        if social_items:
            content_parts.append(
                f'<div class="stat-item"><span class="stat-value">{len(social_items)}</span>'
                '<span class="stat-label">소셜 미디어</span></div>'
            )
        if reddit_items:
            content_parts.append(
                f'<div class="stat-item"><span class="stat-value">{len(reddit_items)}</span>'
                '<span class="stat-label">Reddit</span></div>'
            )
        if political_items:
            content_parts.append(
                f'<div class="stat-item"><span class="stat-value">{len(political_items)}</span>'
                '<span class="stat-label">정치·경제</span></div>'
            )
        content_parts.append("</div>\n")

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

        top_themes = summarizer.get_top_themes()
        priority_items = summarizer.classify_priority()

        # Theme distribution chart
        dist = summarizer.generate_distribution_chart()
        if dist:
            content_parts.append("\n" + dist)

        content_parts.append("\n---\n")

        briefing_image_path = ""
        try:
            from common.image_generator import generate_news_briefing_card

            card_themes = []
            for t_name, t_key, t_emoji, t_count in top_themes[:4]:
                t_articles = summarizer.get_articles_for_theme(t_key)
                t_keywords = []
                for art in t_articles[:4]:
                    words = re.findall(r"[a-zA-Z가-힣]{4,}", art.get("title", ""))
                    t_keywords.extend(words[:2])

                seen_kw = set()
                unique_kw = []
                for kw in t_keywords:
                    lowered = kw.lower()
                    if lowered in seen_kw:
                        continue
                    seen_kw.add(lowered)
                    unique_kw.append(kw)

                card_themes.append(
                    {
                        "name": t_name,
                        "emoji": t_emoji,
                        "count": t_count,
                        "keywords": unique_kw[:3],
                    }
                )

            if card_themes:
                p0_alerts = [get_display_title(item) for item in priority_items.get("P0", [])[:2]]
                img = generate_news_briefing_card(
                    card_themes,
                    today,
                    category="Social Market Briefing",
                    total_count=total_count,
                    urgent_alerts=p0_alerts if p0_alerts else None,
                    filename=f"news-briefing-social-{today}.png",
                )
                if img:
                    fn = os.path.basename(img)
                    briefing_image_path = f"/assets/images/generated/{fn}"
                    web_path = "{{ '/assets/images/generated/" + fn + "' | relative_url }}"
                    content_parts.append(f"\n![news-briefing]({web_path})\n")
                    self.logger.info("Generated social briefing image")
        except ImportError as e:
            self.logger.debug("Optional dependency unavailable: %s", e)
        except Exception as e:
            self.logger.warning("Social briefing image failed: %s", e)

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
                    content_parts.append(f"**{i}. {markdown_link(title, link)}**")
                else:
                    content_parts.append(f"**{i}. {title}**")
                # Show description only if it adds info beyond title
                # (Telegram descriptions are full message text — skip if title is just truncated version)
                if description and description != title and not title.startswith(description[:30]):
                    # Check if description is merely a longer version of the title
                    title_clean = title.replace("[Telegram] ", "").strip()
                    if not description.startswith(title_clean):
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
                    content_parts.append(f"**{i}. {markdown_link(title, link)}**")
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
                title = get_display_title(item)
                source = item.get("source", "unknown")
                link = item.get("link", "")
                description = (item.get("description_ko") or item.get("description", "")).strip()

                if link:
                    source_links.append(item)
                    content_parts.append(f"**{i}. {markdown_link(title, link)}**")
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
            trend_lines.append(
                f"\n**Reddit**: {len(reddit_items)}건 수집, 평균 스코어 {avg_score:.0f}.{reddit_highlight}"
            )

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
        content_parts.append(
            '\n<div class="wm-footer-meta">'
            f"<span>수집 시각: {now.strftime('%Y-%m-%d %H:%M')} KST</span>"
            "<span>소스: Telegram, Reddit, Google News, 소셜 미디어</span>"
            "</div>"
        )

        content = "\n".join(content_parts)

        _top_social_themes = [t[0] for t in top_themes[:3]] if top_themes else []
        _desc_ko = f"소셜 미디어 동향 {total_count}건 수집. "
        if _top_social_themes:
            _desc_ko += f"주요 테마: {', '.join(_top_social_themes)}. "
        _social_raw = (
            all_theme_items[0].get("title_ko") or all_theme_items[0].get("title", "") if all_theme_items else ""
        ).strip()
        _social_top_title = translate_to_korean(_social_raw) if _social_raw else ""
        if not _social_top_title:
            _social_top_title = _social_raw
        if _social_top_title:
            _social_top_title = (
                _social_top_title[:70].rsplit(" ", 1)[0] if len(_social_top_title) > 70 else _social_top_title
            )
            _desc_ko += f"화제: {_social_top_title}"
        else:
            _desc_ko += (
                f"{len({item.get('source', '') for item in all_theme_items if item.get('source')})}개 소스에서 종합"
            )
        _desc_ko = _desc_ko[:160]

        filepath = self.create_post(
            title=post_title,
            content=content,
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
            image=briefing_image_path,
            extra_frontmatter={
                "permalink": build_dated_permalink("social-media", today, "daily-social-media-digest"),
                "description_ko": _desc_ko,
            },
            slug="daily-social-media-digest",
        )
        if filepath:
            self.mark_seen(post_title, "consolidated")
            self.logger.info("Created consolidated social media post: %s", filepath)

        self.save_state()
        self.logger.info(
            "=== Social media collection complete: %d posts created ===",
            self._created_count,
        )
        combined_items = telegram_items + social_items + reddit_items + political_items
        self.log_summary(combined_items)


def main():
    """Main social media collection routine - consolidated post."""
    SocialMediaCollector().run()


if __name__ == "__main__":
    main()
