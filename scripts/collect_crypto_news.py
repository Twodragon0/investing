#!/usr/bin/env python3
"""Collect cryptocurrency news from multiple sources and generate Jekyll posts.

Sources:
- CryptoPanic API (hot news)
- Google News browser scraping (Korean/English crypto)
- Exchange announcements (OKX, Binance, Bybit public APIs)
- Rekt News (security incidents -> security-alerts category)
"""

import os
import re
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import requests

# Add scripts directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import post_html
from common.base_collector import BaseCollector
from common.collector_config import get_collector_config, get_limit, get_url
from common.config import (
    REQUEST_TIMEOUT,
    USER_AGENT,
    get_env,
    get_verify_ssl,
    setup_logging,
)
from common.dedup import deduplicate_by_url
from common.enrichment import _CRYPTO_SOURCE_CONTEXT, enrich_items
from common.markdown_utils import (
    html_reference_details,
    html_source_tag,
    markdown_link,
    markdown_table,
    smart_truncate,
)
from common.post_generator import PostGenerator, build_dated_permalink
from common.rss_fetcher import fetch_rss_feed, fetch_rss_feeds_concurrent
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


try:
    from common.browser import extract_google_news_links
except ImportError:
    extract_google_news_links = None

logger = setup_logging("collect_crypto_news")

VERIFY_SSL = get_verify_ssl()
# collectors.yml에서 설정 로드
_crypto_cfg = get_collector_config("crypto_news")


def fetch_cryptopanic(api_key: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """Fetch hot news from CryptoPanic API."""
    if not api_key:
        logger.info("CryptoPanic API key not set, skipping")
        return []

    # limit 기본값: collectors.yml > 하드코딩 기본값(20)
    if limit is None:
        limit = get_limit("crypto_news", "cryptopanic_items", 20)
    url = get_url("crypto_news", "cryptopanic", "https://cryptopanic.com/api/v1/posts/")
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
            metadata = r.get("metadata", {})
            item_data = {
                "title": sanitize_string(r.get("title", ""), 300),
                "description": sanitize_string(
                    metadata.get("description") or "",
                    500,
                ),
                "link": r.get("url", ""),
                "published": r.get("published_at", ""),
                "source": "CryptoPanic",
                "tags": ["crypto", "hot-news"],
            }
            # Extract image from CryptoPanic metadata
            img = metadata.get("image") or metadata.get("og_image", "")
            if img:
                item_data["image"] = img
            items.append(item_data)
        logger.info("CryptoPanic: fetched %d items", len(items))
        return items
    except requests.exceptions.RequestException as e:
        logger.warning("CryptoPanic fetch failed: %s", e)
        return []


def fetch_google_news_browser(limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """Fetch crypto news via Google News browser scraping.

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

    # limit 기본값: collectors.yml > 하드코딩 기본값(20)
    if limit is None:
        limit = get_limit("crypto_news", "google_news_browser_items", 20)
    search_url = get_url(
        "crypto_news",
        "google_news_browser",
        "https://news.google.com/search?q=cryptocurrency+bitcoin&hl=en-US&gl=US&ceid=US:en",
    )
    items: List[Dict[str, Any]] = []

    try:
        with BrowserSession() as session:
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
            get_url("crypto_news", "rss_coindesk", "https://www.coindesk.com/arc/outboundfeeds/rss"),
            "CoinDesk",
            ["crypto", "coindesk"],
        ),
        (
            get_url("crypto_news", "rss_cointelegraph", "https://cointelegraph.com/rss"),
            "Cointelegraph",
            ["crypto", "cointelegraph"],
        ),
        (get_url("crypto_news", "rss_decrypt", "https://decrypt.co/feed"), "Decrypt", ["crypto", "decrypt"]),
        (
            get_url("crypto_news", "rss_bitcoin_magazine", "https://bitcoinmagazine.com/.rss/full/"),
            "Bitcoin Magazine",
            ["crypto", "bitcoin"],
        ),
    ]
    all_items = fetch_rss_feeds_concurrent(feeds)
    # The Block — may block requests, wrap with extra try/except
    try:
        all_items.extend(
            fetch_rss_feed(
                get_url("crypto_news", "rss_theblock", "https://www.theblock.co/rss"),
                "The Block",
                ["crypto", "theblock"],
            )
        )
    except Exception as e:
        logger.warning("The Block RSS failed: %s", e)
    return all_items


def fetch_google_news_crypto() -> tuple:
    """Fetch crypto news from Google News RSS (English + Korean, concurrent).

    Returns:
        (items, entertainment_removed) 튜플
    """
    feeds = [
        (
            get_url(
                "crypto_news",
                "google_news_crypto_en",
                "https://news.google.com/rss/search?q=cryptocurrency&hl=en-US&gl=US&ceid=US:en",
            ),
            "Google News EN",
            ["crypto", "english"],
        ),
        (
            get_url(
                "crypto_news",
                "google_news_crypto_kr",
                "https://news.google.com/rss/search?q=암호화폐+비트코인&hl=ko&gl=KR&ceid=KR:ko",
            ),
            "Google News KR",
            ["crypto", "korean", "비트코인"],
        ),
    ]
    items = fetch_rss_feeds_concurrent(feeds)
    before = len(items)
    items = [item for item in items if not _is_entertainment_item(item)]
    filtered = before - len(items)
    if filtered:
        logger.info("Google News: 엔터테인먼트/스포츠 아이템 %d개 필터링됨", filtered)
    return items, filtered


def fetch_google_news_security() -> List[Dict[str, Any]]:
    """Fetch blockchain security news from Google News RSS (concurrent)."""
    # 보안 카테고리 오버라이드 값을 설정 파일에서 로드
    security_category = _crypto_cfg.get("categories", {}).get("security", "security-alerts")
    feeds = [
        (
            get_url(
                "crypto_news",
                "google_news_security_en",
                "https://news.google.com/rss/search?q=blockchain+hack+exploit+security&hl=en-US&gl=US&ceid=US:en",
            ),
            "Blockchain Security EN",
            ["security", "hack", "english"],
        ),
        (
            get_url(
                "crypto_news",
                "google_news_defi_security",
                "https://news.google.com/rss/search?q=crypto+hack+DeFi+exploit&hl=en-US&gl=US&ceid=US:en",
            ),
            "DeFi Security EN",
            ["security", "defi", "exploit"],
        ),
        (
            get_url(
                "crypto_news",
                "google_news_security_kr",
                "https://news.google.com/rss/search?q=블록체인+해킹+보안+취약점&hl=ko&gl=KR&ceid=KR:ko",
            ),
            "블록체인 보안 KR",
            ["security", "hack", "korean"],
        ),
    ]
    all_items = fetch_rss_feeds_concurrent(feeds)
    for item in all_items:
        item["category_override"] = security_category
    return all_items


def _binance_desc_from_title(title: str) -> str:
    """Generate a brief Korean description from a Binance announcement title."""
    title_lower = title.lower()
    if any(kw in title_lower for kw in ["list", "상장"]):
        return "신규 토큰 상장 관련 공지"
    if any(kw in title_lower for kw in ["delist", "상장폐지", "removal"]):
        return "토큰 상장폐지 관련 공지"
    if any(kw in title_lower for kw in ["maintenance", "upgrade", "업그레이드"]):
        return "시스템 점검 및 업그레이드 공지"
    if any(kw in title_lower for kw in ["airdrop", "에어드롭"]):
        return "에어드롭 이벤트 공지"
    if any(kw in title_lower for kw in ["margin", "leverage", "레버리지"]):
        return "마진/레버리지 거래 관련 공지"
    if any(kw in title_lower for kw in ["deposit", "withdraw", "입금", "출금"]):
        return "입출금 관련 공지"
    if any(kw in title_lower for kw in ["fee", "수수료"]):
        return "수수료 변경 공지"
    if any(kw in title_lower for kw in ["trading pair", "거래쌍"]):
        return "거래쌍 변경 공지"
    return "Binance 거래소 공지사항"


_PROMO_TITLE_KEYWORDS = [
    "price alert",
    "가격 알림",
    "share rewards",
    "보상을 공유",
    "reward",
    "에어드롭",
    "airdrop",
    "vip loan",
    "vip 대출",
    "apr",
    "yield arena",
    "수익 창출 아레나",
    "challenge season",
    "상품 에디션",
    "가입하고",
    "earn",
    "적립하세요",
    "perpetual contract",
    "무기한 계약 출시",
]


def _clean_exchange_title(title: str) -> str:
    title = remove_sponsored_text(title or "")
    title = re.sub(r"\s+-\s+(?:Binance|Bitget|Bybit|OKX)\s*$", "", title, flags=re.I)
    title = re.sub(r"\s+\(\d{4}-\d{2}-\d{2}\)$", "", title)
    return sanitize_string(title, 300)


def _is_exchange_promo_item(item: Dict[str, Any]) -> bool:
    title = _clean_exchange_title(item.get("title", ""))
    lowered = title.lower()
    if any(keyword in lowered for keyword in _PROMO_TITLE_KEYWORDS):
        return True
    if title.count("!") >= 2:
        return True
    if re.search(r"\b\d+(?:,\d{3})*(?:\.\d+)?\s*(?:usdt|btc|eth|apr|%)\b", lowered):
        return True
    return False


def _scrape_binance_page(session) -> List[Dict[str, Any]]:
    """Scrape Binance announcements from an open browser session."""
    items: List[Dict[str, Any]] = []
    seen_titles: set = set()
    session.navigate(
        get_url("crypto_news", "binance_announcement", "https://www.binance.com/en/support/announcement"),
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
                href = get_url("crypto_news", "binance_base", "https://www.binance.com") + href
            if "/detail/" not in href:
                continue
            items.append(
                {
                    "title": title,
                    "description": _binance_desc_from_title(title),
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
        with BrowserSession() as session:
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
        url = get_url(
            "crypto_news", "binance_api", "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query"
        )
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
                    _binance_base = get_url("crypto_news", "binance_base", "https://www.binance.com")
                    link = (
                        f"{_binance_base}/en/support/announcement/detail/{code}"
                        if code
                        else get_url(
                            "crypto_news", "binance_announcement", "https://www.binance.com/en/support/announcement"
                        )
                    )
                    items.append(
                        {
                            "title": title,
                            "description": _binance_desc_from_title(title),
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
    """Fetch security incidents via RSS feed (CoinTelegraph hacks tag).

    Historically sourced from Rekt News; the URL/key retain the ``rekt`` name
    for backward compatibility after Rekt stopped publishing incident RSS.
    """
    items: List[Dict[str, Any]] = []

    try:
        rss_items = fetch_rss_feed(
            get_url("crypto_news", "rss_rekt_news", "https://cointelegraph.com/rss/tag/hacks"),
            "CoinTelegraph Hacks",
            ["security", "hack", "exploit", "rekt"],
        )
        for item in rss_items[:limit]:
            item["title"] = f"[Security] {item['title']}"
            item["category_override"] = "security-alerts"
            items.append(item)
        logger.info("CoinTelegraph Hacks RSS: fetched %d incidents", len(items))
    except Exception as e:
        logger.warning("CoinTelegraph Hacks RSS failed: %s", e)

    return items


def fetch_defillama_hacks(limit: int = 8, days: int = 30) -> List[Dict[str, Any]]:
    """Fetch recent DeFi exploit incidents from the DeFiLlama hacks API.

    Provides a second, structured incident source alongside the CoinTelegraph
    RSS feed so the daily security report no longer depends on a single feed.
    Items are shaped like Rekt incidents (``[Security]`` title prefix +
    ``Funds Lost:`` metadata) so they flow through the existing security report
    builders (funds summing, description, content) unchanged.
    """
    items: List[Dict[str, Any]] = []
    url = get_url("crypto_news", "defillama_hacks", "https://api.llama.fi/hacks")

    try:
        resp = request_with_retry(url, timeout=REQUEST_TIMEOUT, verify_ssl=get_verify_ssl())
        data = resp.json()
    except Exception as e:
        logger.warning("DeFiLlama hacks API failed: %s", e)
        return items

    if not isinstance(data, list):
        logger.warning("DeFiLlama hacks API: unexpected payload type %s", type(data).__name__)
        return items

    cutoff = time.time() - days * 86400
    recent = [
        h for h in data if isinstance(h, dict) and isinstance(h.get("date"), (int, float)) and h["date"] >= cutoff
    ]
    recent.sort(key=lambda h: h.get("date", 0), reverse=True)

    for hack in recent[:limit]:
        name = sanitize_string(str(hack.get("name") or "")).strip()
        if not name:
            continue
        technique = sanitize_string(str(hack.get("technique") or "")).strip()
        classification = sanitize_string(str(hack.get("classification") or "")).strip()
        amount = hack.get("amount")
        chains = hack.get("chain") or []
        if isinstance(chains, str):
            chains = [chains]
        chain_str = ", ".join(str(c) for c in chains if c) or "N/A"

        bridge_hack = bool(hack.get("bridgeHack"))
        target_type = sanitize_string(str(hack.get("targetType") or "")).strip()

        title = f"[Security] {name} exploit"
        if technique:
            title += f": {technique}"

        desc_parts: List[str] = []
        if isinstance(amount, (int, float)) and amount > 0:
            desc_parts.append(f"Funds Lost: ${amount:,.0f}")
        if classification:
            desc_parts.append(f"Classification: {classification}")
        if technique:
            desc_parts.append(f"Technique: {technique}")
        desc_parts.append(f"Chain: {chain_str}")

        # Prefer the incident's own source link; when absent, use a per-incident
        # anchor on the DeFiLlama hacks page so distinct incidents keep distinct
        # links (avoids collapsing every empty-source hack to one generic URL).
        link = str(hack.get("source") or "").strip() or f"https://defillama.com/hacks#{quote(name)}"

        items.append(
            {
                "title": title,
                "link": link,
                "description": " | ".join(desc_parts),
                "source": "DeFiLlama",
                "category_override": "security-alerts",
                "bridge_hack": bridge_hack,
                "target_type": target_type,
            }
        )

    logger.info("DeFiLlama hacks API: fetched %d recent incidents (last %dd)", len(items), days)
    return items


def _score_security_severity(title: str, description: str = "") -> str:
    """Score security incident severity based on keywords."""
    text = (title + " " + description).lower()
    # Critical / High: large amounts, major attack verbs, bridge exploits
    if any(kw in text for kw in ["billion", "exploit", "hack", "drain", "bridge", "10억", "해킹", "유출", "탈취"]):
        amount_match = re.search(r"\$?([\d,.]+)\s*(?:million|billion|백만|억)", text)
        if amount_match:
            return "🔴 CRITICAL"
        return "🟠 HIGH"
    if any(kw in text for kw in ["vulnerability", "bug", "patch", "취약점", "버그", "패치"]):
        return "🟡 MEDIUM"
    return "🟢 LOW"


# ── Security relevance filter keywords ──
_SECURITY_RELEVANCE_KW = [
    "hack",
    "exploit",
    "vulnerability",
    "breach",
    "stolen",
    "attack",
    "scam",
    "phishing",
    "rug pull",
    "malware",
    "ransomware",
    "drain",
    "compromise",
    "fraud",
    "theft",
    "heist",
    "bug bounty",
    "patch",
    "해킹",
    "취약점",
    "탈취",
    "피해",
    "사기",
    "피싱",
    "악용",
    "유출",
    "공격",
    "보안",
    "익스플로잇",
    "러그풀",
]

# ── Entertainment / sports filter keywords (Google News RSS 전용) ──
# crypto-gaming(NFT game, play-to-earn 등)은 포함하지 않음 — 순수 엔터/스포츠만 필터
_ENTERTAINMENT_KEYWORDS: frozenset = frozenset()  # 모듈 로드 시 _load_entertainment_keywords()로 교체


def _load_entertainment_keywords() -> frozenset:
    """collectors.yml의 crypto_news.keywords.entertainment_keywords에서 키워드를 로드합니다.

    누락 또는 로드 실패 시 하드코딩 기본값으로 fallback합니다.
    """
    _DEFAULT = frozenset(
        {
            # 미국 프로스포츠 리그
            "nba",
            "nfl",
            "mlb",
            "nhl",
            "mls",
            "ufc",
            # 국제 스포츠
            "fifa",
            "premier league",
            "champions league",
            "la liga",
            "bundesliga",
            "serie a",
            "ligue 1",
            "world cup soccer",
            "wimbledon",
            "grand prix",
            "formula 1",
            " f1 ",
            "olympics",
            "paralympics",
            # 주요 스포츠 이벤트
            "super bowl",
            "world series",
            "stanley cup",
            "nba finals",
            "masters tournament",
            "us open tennis",
            "french open",
            "australian open",
            # NBA 팀명 (순수 스포츠 문맥)
            "lakers",
            "celtics",
            "knicks",
            "warriors",
            "bulls",
            "heat",
            # 시상식 / 엔터테인먼트 행사
            "oscar",
            "grammy",
            "emmy",
            "golden globe",
            "bafta",
            "cannes",
            # 미디어 / 팝컬처
            "box office",
            "movie release",
            "album release",
            "billboard chart",
            "netflix show",
            "reality tv",
            "celebrity gossip",
            "celebrity drama",
            "taylor swift concert",
            "met gala",
            # 게임 (crypto-gaming 제외 — 순수 게임 출시/이슈)
            "gta vi",
            "gta 6",
            "game release",
            "season finale",
        }
    )
    kw_cfg = _crypto_cfg.get("keywords", {})
    if not isinstance(kw_cfg, dict):
        logger.debug("collectors.yml: crypto_news.keywords 섹션 없음, 기본값 사용")
        return _DEFAULT
    raw = kw_cfg.get("entertainment_keywords")
    if isinstance(raw, list) and raw:
        logger.debug("collectors.yml에서 entertainment_keywords %d개 로드", len(raw))
        return frozenset(raw)
    logger.debug("collectors.yml: entertainment_keywords 누락, 기본값 사용")
    return _DEFAULT


_ENTERTAINMENT_KEYWORDS = _load_entertainment_keywords()


def _is_entertainment_item(item: Dict[str, Any]) -> bool:
    """Google News RSS 아이템이 순수 엔터테인먼트/스포츠 콘텐츠인지 판별합니다.

    crypto-gaming, NFT game, play-to-earn 등 크립토 맥락이 있으면 False 반환.
    """
    title = item.get("title", "").lower()
    desc = (item.get("description_ko") or item.get("description", "")).lower()
    text = title + " " + desc

    # 크립토 맥락이 있으면 필터 제외 (crypto-gaming 등 보존)
    _CRYPTO_CONTEXT_KW = (
        "crypto",
        "bitcoin",
        "btc",
        "ethereum",
        "eth",
        "nft",
        "defi",
        "blockchain",
        "web3",
        "token",
        "coin",
        "wallet",
        "dex",
    )
    if any(kw in text for kw in _CRYPTO_CONTEXT_KW):
        return False

    return any(kw in text for kw in _ENTERTAINMENT_KEYWORDS)


def _is_security_relevant(item: Dict[str, Any]) -> bool:
    """기사가 보안과 관련 있는지 키워드 기반으로 판별합니다."""
    title = item.get("title", "").lower()
    desc = (item.get("description_ko") or item.get("description", "")).lower()
    text = title + " " + desc
    return any(kw in text for kw in _SECURITY_RELEVANCE_KW)


def _extract_security_summary_from_title(title: str) -> str:
    """title에서 보안 관련 핵심 정보를 요약문으로 변환합니다."""
    if not title:
        return ""
    # 제목 자체가 충분히 설명적이면 그대로 사용
    summary = title.strip()
    # 출처 태그 제거 (e.g., "- CoinDesk", "| The Block")
    summary = re.sub(r"\s*[-|]\s*[A-Z][\w\s.]+$", "", summary).strip()
    if len(summary) > 10:
        return summary
    return ""


def _build_security_description(
    rekt_items: List[Dict[str, Any]],
    google_security_items: List[Dict[str, Any]],
) -> str:
    """보안 포스트의 동적 description_ko를 생성합니다.

    Rekt 항목은 ``Funds Lost:`` 메타데이터가 있는 실제 해킹 사건일 때만 대표
    문구로 사용합니다. 메타데이터가 없는 항목(일반 분석/오피니언 아티클 등)은
    제목을 그대로 description에 노출하면 영문 헤드라인이 한국어 description을
    오염시켜 검색/UX 품질이 떨어지므로, Google 보안 뉴스 fallback으로 위임합니다.
    """
    parts: List[str] = []

    # Rekt 사고: Funds Lost 메타데이터가 있는 실제 해킹만 노출.
    if rekt_items:
        top = rekt_items[0]
        project = top["title"].replace("[Security] ", "")
        desc = top.get("description", "")
        funds = ""
        if "Funds Lost:" in desc:
            try:
                funds = desc.split("Funds Lost:")[1].split("|")[0].strip()
            except IndexError:
                pass
        if funds:
            parts.append(f"{project} {funds} 피해 발생")
        # No else: rekt 항목에 funds 메타데이터가 없으면 일반 기사일 수 있어
        # 제목(종종 영문)을 그대로 노출하지 않고 Google fallback으로 넘어간다.

    # Google 보안 뉴스 대표 사건 — rekt에 실제 사건이 없을 때만 fallback.
    if google_security_items and not parts:
        top_title = get_display_title(google_security_items[0])
        parts.append(smart_truncate(top_title, 60))

    total = len(rekt_items) + len(google_security_items)
    parts.append(f"블록체인 보안 뉴스 {total}건 분석")

    return ". ".join(parts) + "."


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
        with BrowserSession() as session:
            # Google News
            try:
                session.navigate(
                    get_url(
                        "crypto_news",
                        "google_news_browser",
                        "https://news.google.com/search?q=cryptocurrency+bitcoin&hl=en-US&gl=US&ceid=US:en",
                    ),
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


class CryptoNewsCollector(BaseCollector):
    """암호화폐 뉴스 수집기.

    CryptoPanic, Google News, RSS 피드, 거래소 공지, Rekt News 등
    다양한 소스에서 뉴스를 수집하고 두 개의 포스트를 생성합니다:
    - 암호화폐 뉴스 브리핑 (crypto-news)
    - 블록체인 보안 리포트 (security-alerts)
    """

    name = "crypto_news"
    category = "crypto-news"
    state_file = "crypto_news_seen.json"

    def __init__(self) -> None:
        super().__init__()
        self.security_gen = PostGenerator("security-alerts")

    def fetch(self) -> List[Dict[str, Any]]:
        """모든 소스에서 뉴스 항목을 수집합니다."""
        cryptopanic_key = get_env("CRYPTOPANIC_API_KEY")
        all_items: List[Dict[str, Any]] = []

        all_items.extend(fetch_cryptopanic(cryptopanic_key))

        browser_google, browser_binance = _fetch_browser_sources()
        all_items.extend(browser_google)

        google_news_items, _ent_removed = fetch_google_news_crypto()
        all_items.extend(google_news_items)
        self.record_entertainment_filtered(_ent_removed)
        all_items.extend(fetch_crypto_rss_feeds())

        exchange_items = browser_binance if browser_binance else _fetch_binance_bapi()
        enrich_items(exchange_items, _CRYPTO_SOURCE_CONTEXT, fetch_url=True, max_fetch=30)
        all_items.extend(exchange_items)

        enrich_items(all_items, _CRYPTO_SOURCE_CONTEXT, fetch_url=True, max_fetch=30)
        return all_items

    def fetch_security(self) -> tuple:
        """보안 관련 뉴스를 별도로 수집합니다."""
        rekt_items = fetch_rekt_news()
        # Merge DeFiLlama hacks as a second incident source to reduce single-feed
        # dependency. Shaped like Rekt incidents (Funds Lost: metadata), so the
        # combined stream flows through the existing security builders unchanged.
        defillama_hacks = fetch_defillama_hacks()
        if defillama_hacks:
            rekt_items.extend(defillama_hacks)
            self.logger.info(
                "Security incident sources merged: cointelegraph+defillama -> %d total",
                len(rekt_items),
            )
        google_security_items = fetch_google_news_security()
        enrich_items(rekt_items, _CRYPTO_SOURCE_CONTEXT, fetch_url=False)
        enrich_items(google_security_items, _CRYPTO_SOURCE_CONTEXT, fetch_url=True, max_fetch=15)
        google_security_items = deduplicate_by_url(google_security_items)

        rekt_items = [
            item
            for item in rekt_items
            if not self.is_duplicate(item["title"], item.get("source", "rekt"), item.get("link", ""))
        ]
        google_security_items = [
            item
            for item in google_security_items
            if not self.is_duplicate(item["title"], item.get("source", "google"), item.get("link", ""))
        ]

        # 보안 무관 기사 필터링 (Google Security News만 — Rekt News는 이미 보안 전문)
        pre_filter = len(google_security_items)
        google_security_items = [item for item in google_security_items if _is_security_relevant(item)]
        if pre_filter != len(google_security_items):
            self.logger.info(
                "Security relevance filter: %d -> %d (removed %d irrelevant)",
                pre_filter,
                len(google_security_items),
                pre_filter - len(google_security_items),
            )

        self.logger.info(
            "Security items after dedup: rekt=%d, google=%d",
            len(rekt_items),
            len(google_security_items),
        )
        return rekt_items, google_security_items

    def process(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """URL 기반 중복 제거."""
        return deduplicate_by_url(items)

    def build_content(self, items: List[Dict[str, Any]]) -> str:
        """암호화폐 뉴스 브리핑 포스트 본문을 생성합니다."""
        content, _image = self._build_crypto_content(items)
        return content

    def run(self) -> None:
        """메인 실행 파이프라인 — 크립토 뉴스 + 보안 리포트 두 개 포스트 생성."""
        self.logger.info("=== Starting crypto news collection ===")
        self._started_at = time.monotonic()

        all_items = self.fetch()
        all_items = self.process(all_items)

        rekt_items, google_security_items = self.fetch_security()

        # ── Post A: consolidated crypto news briefing ──
        post_a_title = f"암호화폐 뉴스 브리핑 - {self.today}"

        if not all_items:
            self.logger.warning("No news items collected, skipping crypto news post")
        if all_items and not self.is_duplicate_exact(post_a_title, "consolidated"):
            content, briefing_image = self._build_crypto_content(all_items)

            _top_crypto_sources = [
                name for name, _ in Counter(item.get("source", "unknown") for item in all_items).most_common(3)
            ]
            # Lead with the headline so excerpt is concrete (mirrors body lead).
            _top_headline = (get_display_title(all_items[0]) if all_items else "").strip()
            if _top_headline:
                _top_headline = _top_headline[:80].rsplit(" ", 1)[0] if len(_top_headline) > 80 else _top_headline
                _desc_ko_a = f"{_top_headline}. 크립토 뉴스 {len(all_items)}건 분석"
                if _top_crypto_sources:
                    _desc_ko_a += f" ({', '.join(_top_crypto_sources[:2])})"
                _desc_ko_a += "."
            else:
                _desc_ko_a = f"크립토 뉴스 {len(all_items)}건 수집"
                if _top_crypto_sources:
                    _desc_ko_a += f". 주요 출처: {', '.join(_top_crypto_sources)}"
                _desc_ko_a += "."
            _desc_ko_a = _desc_ko_a[:160]

            filepath = self.create_post(
                title=post_a_title,
                content=content,
                tags=["crypto", "news", "daily-digest"],
                source="consolidated",
                image=briefing_image or "",
                extra_frontmatter={
                    "permalink": build_dated_permalink("crypto-news", self.today, "daily-crypto-news-digest"),
                    "description_ko": _desc_ko_a,
                },
                slug="daily-crypto-news-digest",
            )
            if filepath:
                self.mark_seen(post_a_title, "consolidated")
                self.logger.info("Created consolidated crypto news post: %s", filepath)

        # ── Post B: security report (Rekt News + Google Security News) ──
        all_security_items = rekt_items + google_security_items
        if len(all_security_items) < 1:
            self.logger.info(
                "보안 뉴스가 %d건으로 최소 기준(1건) 미달, 포스트 생성 스킵",
                len(all_security_items),
            )
        else:
            post_b_title = f"블록체인 보안 리포트 - {self.today}"

            if not self.is_duplicate_exact(post_b_title, "consolidated"):
                content = self._build_security_content(all_security_items, rekt_items, google_security_items)
                _desc_ko_b = _build_security_description(rekt_items, google_security_items)

                filepath = self.create_post(
                    title=post_b_title,
                    content=content,
                    tags=["security", "hack", "blockchain", "daily-digest"],
                    source="consolidated",
                    extra_frontmatter={
                        "permalink": build_dated_permalink("security-alerts", self.today, "daily-security-report"),
                        "description_ko": _desc_ko_b,
                    },
                    slug="daily-security-report",
                    post_gen=self.security_gen,
                )
                if filepath:
                    self.mark_seen(post_b_title, "consolidated")
                    self.logger.info("Created security report post: %s", filepath)

        # Save dedup state
        self.save_state()

        self.logger.info(
            "=== Crypto news collection complete: %d posts created ===",
            self._created_count,
        )
        all_collected_items = all_items + all_security_items
        self.log_summary(all_collected_items)

    def _build_crypto_content(self, all_items: List[Dict[str, Any]]) -> tuple:
        """암호화폐 뉴스 브리핑 본문을 생성합니다.

        Returns:
            (content, briefing_image) 튜플.
        """
        today = self.today
        now = self.now

        # Separate market-moving news from exchange notices/promotions
        news_rows: List[Dict[str, Any]] = []
        exchange_rows: List[Dict[str, Any]] = []
        exchange_promo_rows: List[Dict[str, Any]] = []
        source_counter: Counter = Counter()
        source_links: List[Dict[str, Any]] = []
        summary_items: List[Dict[str, Any]] = []

        for item in all_items:
            source = item.get("source", "unknown")
            link = item.get("link", "")
            source_counter[source] += 1

            # Collect links for references section
            if link:
                source_links.append(item)

            if source in ("Binance", "OKX", "Bybit"):
                cleaned_title = _clean_exchange_title(item.get("title", ""))
                item["title"] = cleaned_title
                if _is_exchange_promo_item(item):
                    exchange_promo_rows.append(item)
                    continue
                exchange_rows.append(item)
                summary_items.append(item)
            else:
                news_rows.append(item)
                summary_items.append(item)

        all_items = summary_items

        # Limit to top items
        news_rows = news_rows[:15]
        exchange_rows = exchange_rows[:8]
        exchange_promo_rows = exchange_promo_rows[:6]

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
        themes_str = ", ".join(theme_names[:3]) if theme_names else ""

        # Lead with the top news headline so the summary excerpt is concrete
        # (avoid vague "...관련 소식이 주목됩니다" filler).
        _top_headline = ""
        if all_items:
            _candidate = (
                all_items[0].get("title_ko") or all_items[0].get("title_translated") or all_items[0].get("title", "")
            )
            _top_headline = _candidate.strip()[:80]

        _detail = (
            f"총 {len(all_items)}건 분석, 핵심 테마는 **{themes_str}**입니다"
            if themes_str
            else f"총 {len(all_items)}건의 시장 동향을 정리합니다"
        )
        if _top_headline:
            content_parts = [post_html.summary_intro(today, "암호화폐 핵심 뉴스", _top_headline, detail=_detail)]
        elif themes_str:
            content_parts = [
                post_html.summary_intro(
                    today, f"암호화폐 시장 {len(all_items)}건 분석", None, detail=f"핵심 테마: **{themes_str}**"
                )
            ]
        else:
            content_parts = [
                post_html.summary_intro(
                    today, "암호화폐 시장", None, detail=f"{len(all_items)}건의 뉴스를 분석했습니다"
                )
            ]

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
            summary_points.append(f"시장 영향 가능 거래소 공지 {len(exchange_rows)}건 포함")
        if exchange_promo_rows:
            summary_points.append(f"프로모션성 거래소 공지 {len(exchange_promo_rows)}건 제외")
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
                t_articles = summarizer.get_articles_for_theme(t_key)
                t_keywords = []
                for art in t_articles[:5]:
                    words = re.findall(r"[a-zA-Z가-힣]{4,}", art.get("title", ""))
                    t_keywords.extend(words[:2])
                # Deduplicate
                seen_kw: set = set()
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
            p0_alerts = [get_display_title(item) for item in priority_items.get("P0", [])[:2]]

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
                self.logger.info("Generated news briefing card")
        except ImportError as e:
            self.logger.debug("Optional dependency unavailable: %s", e)
        except Exception as e:
            self.logger.warning("News briefing card failed: %s", e)

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
                    self.logger.info("Generated news summary card")
            except ImportError as e:
                self.logger.debug("Optional dependency unavailable: %s", e)
            except Exception as e:
                self.logger.warning("News summary card failed: %s", e)

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
                    display = get_display_title(row)
                    title_cell = f"**{display}**"
                    if row["link"]:
                        title_cell = markdown_link(title_cell, row["link"])
                    table_rows.append((i, title_cell, row["source"]))
                content_parts.append(markdown_table(["#", "제목", "출처"], table_rows))
            else:
                pass

        # Exchange announcements with descriptions
        if exchange_rows:
            content_parts.append("\n## 거래소 공지사항\n")
            shown_exchange = 0
            for item in exchange_rows:
                title = get_display_title(item)
                link = item.get("link", "")
                source = item.get("source", "")
                description = (item.get("description_ko") or item.get("description", "")).strip()
                if link:
                    content_parts.append(f"**{shown_exchange + 1}. {markdown_link(title, link)}**")
                else:
                    content_parts.append(f"**{shown_exchange + 1}. {title}**")
                if description and description != title:
                    desc_text = description[:120]
                    if len(description) > 120:
                        desc_text += "..."
                    content_parts.append(f"{desc_text}")
                else:
                    content_parts.append(f"{source} 거래소 공지사항입니다.")
                content_parts.append(f"{html_source_tag(source)}\n")
                shown_exchange += 1
                if shown_exchange >= 8:
                    break

        if exchange_promo_rows:
            content_parts.append("\n## 제외된 거래소 프로모션/이벤트\n")
            content_parts.append("시장 정보 가치가 낮은 거래소 홍보성 공지는 아래처럼 별도 분리했습니다.\n")
            for item in exchange_promo_rows[:5]:
                title = get_display_title(item)
                source = item.get("source", "")
                link = item.get("link", "")
                if link:
                    content_parts.append(f"- {markdown_link(title, link)} ({source})")
                else:
                    content_parts.append(f"- {title} ({source})")

        # Insight section - data-driven cross-analysis
        content_parts.append("\n## 오늘의 인사이트\n")
        insight_lines = self._build_insight_lines(
            all_items, top_themes, top_keywords, summarizer, source_counter, exchange_rows
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

        # Data collection footer (동적 소스 — 실제 수집된 소스만 표기)
        top_sources = source_counter.most_common(5)
        if top_sources:
            top_sources_str = ", ".join(f"{name} ({count}건)" for name, count in top_sources)
            active_source_names = ", ".join(name for name, _ in top_sources)
            content_parts.append(
                '\n<div class="wm-footer-meta">'
                f"<span>수집 시각: {now.strftime('%Y-%m-%d %H:%M')} KST</span>"
                f"<span>소스: {active_source_names}</span>"
                "</div>"
            )
            content_parts.append(f"**수집 출처**: {top_sources_str}")
        else:
            content_parts.append(
                f'\n<div class="wm-footer-meta"><span>수집 시각: {now.strftime("%Y-%m-%d %H:%M")} KST</span></div>'
            )

        content = "\n".join(content_parts)
        return content, briefing_image

    def _build_insight_lines(
        self,
        all_items: List[Dict[str, Any]],
        top_themes: list,
        top_keywords: list,
        summarizer: ThemeSummarizer,
        source_counter: Counter,
        exchange_rows: List[Dict[str, Any]],
    ) -> List[str]:
        """인사이트 섹션 라인을 생성합니다."""
        insight_lines: List[str] = []

        # Extract price mentions from titles for concrete analysis
        price_mentions: List[str] = []
        listing_mentions: List[str] = []
        delisting_mentions: List[str] = []
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
                "비트코인 관련 뉴스와 시장 가격 움직임이 함께 부각되어, "
                "단기 변동성 확대 구간에 진입한 것으로 보입니다.",
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
                "정치적 이벤트와 금리·매크로 지표가 동시에 움직여, "
                "글로벌 유동성 변화에 따른 자산 재배치 가능성이 있습니다.",
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
                articles = summarizer.get_articles_for_theme(theme_key)
                for art in articles:
                    top_title = get_display_title(art)
                    orig_title = art.get("title", "")
                    if orig_title and orig_title not in seen_insight_titles:
                        seen_insight_titles.add(orig_title)
                        insight_lines.append(f"- 주요 기사: *{truncate_text(top_title, 100)}*")
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
            "> *본 뉴스 브리핑은 자동 수집된 데이터를 기반으로 생성되었으며, 투자 조언이 아닙니다. "
            "모든 투자 결정은 개인의 판단과 책임 하에 이루어져야 합니다.*"
        )
        return insight_lines

    def _build_security_content(
        self,
        all_security_items: List[Dict[str, Any]],
        rekt_items: List[Dict[str, Any]],
        google_security_items: List[Dict[str, Any]],
    ) -> str:
        """블록체인 보안 리포트 본문을 생성합니다."""
        _top_rekt = rekt_items[0].get("title", "")[:60] if rekt_items else ""
        _top_news = ""
        if google_security_items:
            _candidate = google_security_items[0].get("title_ko") or google_security_items[0].get("title", "")
            _top_news = _candidate.strip()[:60]
        if _top_rekt:
            # Rekt 사건이 있으면 1순위 헤드라인으로 노출
            content_parts = [
                f"블록체인 보안 {len(all_security_items)}건 분석. "
                f"주목 사건: **{_top_rekt}**" + (f" / 보안 뉴스 헤드라인: {_top_news}." if _top_news else ".") + "\n"
            ]
        elif _top_news:
            # Rekt 없을 때라도 보안 뉴스 헤드라인이라도 노출 (generic count만 회피)
            content_parts = [
                f"블록체인 보안 뉴스 {len(all_security_items)}건 분석. 오늘의 헤드라인: **{_top_news}**.\n"
            ]
        else:
            content_parts = [
                f"블록체인 보안 뉴스 {len(all_security_items)}건 수집 (보안 사건 {len(rekt_items)}건 포함).\n"
            ]
        security_links: List[Dict[str, Any]] = []

        security_summarizer = ThemeSummarizer(all_security_items)
        summary_points = []
        if rekt_items or google_security_items:
            summary_points.append(f"보안 사건 {len(rekt_items)}건, 보안 뉴스 {len(google_security_items)}건")
        overall_summary = security_summarizer.generate_overall_summary_section(
            extra_data={"summary_points": summary_points}
        )
        if overall_summary:
            content_parts.append(overall_summary)

        # Sum up funds lost where parseable (hoisted for insight section)
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

        # Key summary for security
        content_parts.append("## 핵심 요약\n")
        content_parts.append(f"- **보안 사고/뉴스**: 총 {len(all_security_items)}건")
        if rekt_items:
            content_parts.append(f"- **보안 사건**: {len(rekt_items)}건")
            if total_funds > 0:
                content_parts.append(f"- **총 피해 규모 (추정)**: ${total_funds:,.0f}")
        if google_security_items:
            content_parts.append(f"- **보안 관련 뉴스**: {len(google_security_items)}건")

        technique_counter: Counter = Counter()

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
                        technique = desc.split("Technique:")[1].split("|")[0].strip()
                    except IndexError:
                        pass

                if technique != "N/A":
                    technique_counter[technique] += 1

                severity = _score_security_severity(item["title"], desc)
                project_cell = markdown_link(project, link) if link else project
                incident_rows.append((f"{severity} {project_cell}", funds_lost, technique))
                if link:
                    security_links.append(
                        {
                            "title": item["title"],
                            "link": link,
                            "source": item.get("source", ""),
                        }
                    )

            if incident_rows:
                content_parts.append(markdown_table(["심각도 / 프로젝트", "피해 규모", "공격 유형"], incident_rows))

        # Google Security News section with descriptions
        if google_security_items:
            content_parts.append("\n## 보안 관련 뉴스\n")
            for i, item in enumerate(google_security_items[:10], 1):
                title = get_display_title(item)
                link = item.get("link", "")
                source = item.get("source", "")
                description = (item.get("description_ko") or item.get("description", "")).strip()
                severity = _score_security_severity(title, description)

                # description이 generic/boilerplate이면 title에서 핵심 정보 추출
                if not description or description == title or len(description) < 20:
                    description = _extract_security_summary_from_title(title)

                if link:
                    content_parts.append(f"**{i}. [{severity}] {markdown_link(title, link)}**")
                    security_links.append(item)
                else:
                    content_parts.append(f"**{i}. [{severity}] {title}**")
                if description and description != title:
                    desc_text = smart_truncate(description, 150)
                    content_parts.append(f"> {desc_text}")
                content_parts.append(f"{html_source_tag(source)}\n")

        # Security insight — 패턴 분석 기반
        content_parts.append("\n## 보안 인사이트\n")
        sec_insight_lines = []

        # 심각도 분류 통계
        severity_counts: Counter = Counter()
        for item in all_security_items:
            title = item.get("title", "")
            desc = (item.get("description_ko") or item.get("description", "")).strip()
            sev = _score_security_severity(title, desc)
            if "CRITICAL" in sev:
                severity_counts["CRITICAL"] += 1
            elif "HIGH" in sev:
                severity_counts["HIGH"] += 1
            elif "MEDIUM" in sev:
                severity_counts["MEDIUM"] += 1
            else:
                severity_counts["LOW"] += 1

        if severity_counts:
            sev_parts = []
            for level in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]:
                if severity_counts[level] > 0:
                    sev_parts.append(f"{level} {severity_counts[level]}건")
            sec_insight_lines.append(f"**심각도 분류**: {', '.join(sev_parts)}")

        if rekt_items:
            sec_insight_lines.append(f"\n최근 보안 사고 {len(rekt_items)}건이 보고되었습니다.")
            if technique_counter:
                top_tech = technique_counter.most_common(3)
                tech_str = ", ".join(f"{t}({c}건)" for t, c in top_tech)
                sec_insight_lines.append(f"주요 공격 유형: {tech_str}.")
            if total_funds > 0:
                sec_insight_lines.append(f"총 피해 규모는 **${total_funds:,.0f}**으로 추정됩니다.")

            # DeFiLlama 정형 분류 (bridgeHack / targetType) — 해당 메타데이터가
            # 있는 사건(DeFiLlama 출처)만 집계. RSS/뉴스 항목에는 키가 없어 자연 제외.
            classified = [it for it in rekt_items if "bridge_hack" in it]
            if classified:
                bridge_n = sum(1 for it in classified if it.get("bridge_hack"))
                if bridge_n:
                    sec_insight_lines.append(
                        f"이 중 **브리지 공격 {bridge_n}건**이 포함되어, "
                        "크로스체인 브리지의 자금 집중 리스크에 주의가 필요합니다."
                    )
                target_counter: Counter = Counter(it.get("target_type") for it in classified if it.get("target_type"))
                if target_counter:
                    target_str = ", ".join(f"{t}({c}건)" for t, c in target_counter.most_common(3))
                    sec_insight_lines.append(f"공격 대상 유형: {target_str}.")

        if google_security_items:
            sec_insight_lines.append(f"\n블록체인 보안 관련 뉴스 {len(google_security_items)}건이 수집되었습니다.")
            # 대표 뉴스 하이라이트
            top_google = google_security_items[0]
            top_title = get_display_title(top_google)
            sec_insight_lines.append(f"주요 이슈: {smart_truncate(top_title, 80)}.")

        if not sec_insight_lines:
            sec_insight_lines.append("현재 특이할 만한 보안 사고가 보고되지 않았습니다.")
        sec_insight_lines.append("")
        sec_insight_lines.append(
            "> *본 보안 리포트는 자동 수집된 데이터를 기반으로 생성되었으며, 투자 조언이 아닙니다. "
            "모든 투자 결정은 개인의 판단과 책임 하에 이루어져야 합니다.*"
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

        return "\n".join(content_parts)


def main():
    """Main entry point — backward compatible."""
    collector = CryptoNewsCollector()
    collector.run()


if __name__ == "__main__":
    main()
