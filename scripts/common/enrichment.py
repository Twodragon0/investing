"""Shared URL content enrichment for news collectors.

Provides functions to fetch meta descriptions from URLs and generate
synthetic descriptions when actual content is unavailable.
"""

import logging
import re
from typing import Any, Dict, Optional

import requests

from .config import get_ssl_verify

logger = logging.getLogger(__name__)

VERIFY_SSL = get_ssl_verify()

_USER_AGENT = "Mozilla/5.0 (compatible; InvestingBot/1.0)"


# Patterns that indicate the description is noise, not real content
_NOISE_DESC_PATTERNS = [
    re.compile(r"please enable javascript", re.I),
    re.compile(r"enable cookies", re.I),
    re.compile(r"your browser.{0,20}(not supported|outdated|javascript)", re.I),
    re.compile(r"^access denied", re.I),
    re.compile(r"^403 forbidden", re.I),
    re.compile(r"^page not found", re.I),
    re.compile(r"^404\b", re.I),
    re.compile(r"^we use cookies", re.I),
    re.compile(r"^this site requires", re.I),
    re.compile(r"^you need to enable", re.I),
    re.compile(r"^AMENDMENT NO\.", re.I),
    re.compile(r"^FORM\s+\d", re.I),
]


def _clean_description(text: str) -> str:
    """Clean extracted description text for quality."""
    text = text.strip()
    # Remove common site-wide boilerplate prefixes
    for noise in [
        "Sign up for ",
        "Subscribe to ",
        "Get the latest ",
        "Read more about ",
        "Click here ",
        "Share this ",
        "Follow us ",
    ]:
        if text.startswith(noise):
            return ""
    # Reject noise patterns (JS required, 403, etc.)
    for pattern in _NOISE_DESC_PATTERNS:
        if pattern.search(text):
            return ""
    # Remove trailing "Read more..." / "Continue reading..."
    text = re.sub(r"\s*(Read more|Continue reading|더 보기|자세히 보기)\.{0,3}\s*$", "", text)
    # Remove trailing source name appended to RSS titles (e.g. "Title Text - SourceName")
    # English sources (short, capitalized)
    text = re.sub(r"\s+[-–—]\s+[A-Z][A-Za-z\s]{2,25}$", "", text)
    # Korean sources (e.g. "...내용 디지털투데이", "...내용 연합인포맥스")
    text = re.sub(
        r"\s+[-–—]?\s*(?:디지털투데이|연합인포맥스|펜앤마이크|네이트|복지TV\S*"
        r"|ER\s*이코노믹리뷰|v\.daum\.net|매일경제|한국경제|조선일보|중앙일보"
        r"|경향신문|한겨레|BBS불교방송|이데일리|뉴시스|아시아경제)\s*$",
        "",
        text,
    )
    # Generic trailing domain-like source (e.g. "...text simplywall.st")
    text = re.sub(r"\s+[a-z][a-z0-9-]*\.[a-z]{2,6}$", "", text)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


def fetch_page_metadata(url: str, timeout: int = 8) -> Dict[str, str]:
    """Fetch meta description and og:image from a URL page (best-effort).

    Returns a dict with keys ``description`` and ``image`` (empty strings on failure).
    """
    result: Dict[str, str] = {"description": "", "image": ""}
    if not url or "news.google.com/rss/" in url:
        return result

    try:
        from bs4 import BeautifulSoup as BS4

        resp = requests.get(
            url,
            timeout=timeout,
            headers={"User-Agent": _USER_AGENT},
            verify=VERIFY_SSL,
        )
        resp.raise_for_status()
        soup = BS4(resp.text, "html.parser")

        # Extract og:image / twitter:image
        for img_attr_key, img_attr_val in [
            ("property", "og:image"),
            ("name", "twitter:image"),
        ]:
            meta = soup.find("meta", attrs={img_attr_key: img_attr_val})
            if meta:
                img_url = str(meta.get("content", "")).strip()
                if img_url and img_url.startswith("http"):
                    result["image"] = img_url
                    break

        # 1-3: Meta description tags
        for attr_key, attr_val in [
            ("name", "description"),
            ("property", "og:description"),
            ("name", "twitter:description"),
        ]:
            meta = soup.find("meta", attrs={attr_key: attr_val})
            content = str(meta.get("content", "")) if meta else ""
            cleaned = _clean_description(content)
            if cleaned and len(cleaned) > 20:
                result["description"] = cleaned[:500]
                return result

        # 4: Article body paragraphs (more reliable than random <p>)
        article = soup.find("article") or soup.find(class_=re.compile(r"article|post|entry|content"))
        if article:
            paragraphs = []
            for p in article.find_all("p"):
                text = _clean_description(p.get_text(strip=True))
                if len(text) > 50:
                    paragraphs.append(text)
                if len(paragraphs) >= 2:
                    break
            if paragraphs:
                combined = " ".join(paragraphs)
                result["description"] = combined[:500]
                return result

        # 5: Fallback to any <p>
        for p in soup.find_all("p"):
            text = _clean_description(p.get_text(strip=True))
            if len(text) > 50:
                result["description"] = text[:500]
                return result
    except Exception as e:  # noqa: BLE001
        logger.debug("Failed to fetch metadata from %s: %s", url, e)
    return result


def fetch_page_description(url: str, timeout: int = 8) -> str:
    """Try to fetch meta description from a URL page (best-effort).

    Wrapper around :func:`fetch_page_metadata` for backward compatibility.
    """
    return fetch_page_metadata(url, timeout).get("description", "")


# ---------------------------------------------------------------------------
# Source context maps for synthetic descriptions
# ---------------------------------------------------------------------------

_CRYPTO_SOURCE_CONTEXT: Dict[str, str] = {
    "CryptoPanic": "암호화폐 뉴스 플랫폼",
    "CoinDesk RSS": "코인데스크",
    "CoinTelegraph RSS": "코인텔레그래프",
    "The Block RSS": "더블록",
    "Decrypt RSS": "디크립트",
    "Bitcoin Magazine": "비트코인 매거진",
    "Binance": "바이낸스 거래소",
    "Google News": "구글 뉴스",
    "Rekt News": "보안사고 전문 매체",
    "DeFiLlama": "디파이 분석 플랫폼",
}

_STOCK_SOURCE_CONTEXT: Dict[str, str] = {
    "CNBC Top News": "CNBC",
    "MarketWatch": "마켓워치",
    "한국경제": "한국경제신문",
    "매일경제": "매일경제신문",
    "조선비즈": "조선비즈",
    "Google News Stocks EN": "구글 뉴스 주식",
    "Google News Stocks KR": "구글 뉴스 한국주식",
    "Yahoo Finance": "야후 파이낸스",
    "Reuters": "로이터",
    "Bloomberg": "블룸버그",
    "Google News": "구글 뉴스",
}

_POLITICAL_SOURCE_CONTEXT: Dict[str, str] = {
    "Capitol Trades": "미국 의회 거래",
    "Capitol Trades Korean": "미국 의회 거래",
    "SEC Insider Trading": "SEC 내부자 거래",
    "SEC Insider Activity": "SEC 내부자 활동",
    "SEC 내부자거래 KR": "SEC 내부자 거래",
    "Trump EO Economy": "트럼프 경제 정책",
    "Trump Tariff Policy": "트럼프 관세 정책",
    "Trump Crypto Policy": "트럼프 암호화폐 정책",
    "SEC EDGAR": "SEC 공시 시스템",
    "Google News": "구글 뉴스",
}

_WORLDMONITOR_SOURCE_CONTEXT: Dict[str, str] = {
    "BBC World": "BBC 월드 뉴스",
    "Reuters World": "로이터 세계 뉴스",
    "Guardian World": "가디언 세계 뉴스",
    "Al Jazeera": "알자지라",
    "AP News World": "AP 통신",
    "France24": "프랑스24",
    "DW News": "도이체벨레",
    "NHK World": "NHK 월드",
    "WorldMonitor": "월드모니터",
    "Google News": "구글 뉴스",
}

_SOCIAL_SOURCE_CONTEXT: Dict[str, str] = {
    "Twitter/X": "트위터/X",
    "Google News Social EN": "구글 뉴스 소셜",
    "Google News Social KR": "구글 뉴스 소셜",
    "Whale & On-chain": "고래·온체인 분석",
    "Trump Crypto Policy": "트럼프 암호화폐 정책",
    "Trump Economy": "트럼프 경제 정책",
    "트럼프 경제정책 KR": "트럼프 경제정책",
    "이재명 경제정책": "이재명 경제정책",
    "이재명 암호화폐정책": "이재명 암호화폐정책",
    "이재명 부동산·금리": "이재명 부동산·금리",
    "Fed Policy": "연준 통화정책",
    "한국은행 금리정책": "한국은행 금리정책",
    "한국증시 수급": "한국증시 수급",
    "r/CryptoCurrency": "Reddit 암호화폐",
    "r/Bitcoin": "Reddit 비트코인",
    "r/EthTrader": "Reddit 이더리움",
    "r/WallStreetBets": "Reddit 월스트리트벳",
    "r/Stocks": "Reddit 주식",
    "r/Investing": "Reddit 투자",
    "r/DeFi": "Reddit 디파이",
    "Google News": "구글 뉴스",
}


def _get_source_label(source: str, context_map: Dict[str, str]) -> str:
    """Get a Korean label for a source name."""
    return context_map.get(source, source)


def _extract_title_entities(title: str) -> list:
    """Extract meaningful entities (names, tickers, numbers) from title."""
    entities = []
    # Tickers and crypto symbols (e.g., BTC, ETH, AAPL)
    tickers = re.findall(r"\b[A-Z]{2,5}\b", title)
    # Price/percentage values (e.g., $90K, 5.3%, $100B)
    values = re.findall(r"\$[\d,.]+[KkMmBbTt]?|\d+(?:\.\d+)?%", title)
    # Korean entities (2+ chars)
    kr_entities = re.findall(r"[가-힣]{2,}", title)
    # Proper nouns (capitalized words, not common English)
    _COMMON = {"The", "And", "For", "With", "Has", "Are", "Its", "But", "How", "Why", "What", "New", "All", "Can"}
    proper = [w for w in re.findall(r"\b[A-Z][a-z]{2,}\b", title) if w not in _COMMON]

    entities.extend(values)
    entities.extend(tickers[:2])
    entities.extend(proper[:2])
    entities.extend(kr_entities[:3])
    return entities


def generate_synthetic_description(
    title: str,
    source: str,
    context_map: Optional[Dict[str, str]] = None,
) -> str:
    """Generate a contextual description when RSS provides none.

    Creates a meaningful summary by extracting key entities from the title
    and combining them with topic context. Produces specific, informative
    sentences rather than generic boilerplate.
    """
    label = _get_source_label(source, context_map or {})
    title_lower = title.lower()
    entities = _extract_title_entities(title)
    entity_str = ", ".join(entities[:3]) if entities else ""

    # --- Topic-specific patterns with entity insertion ---

    # Crypto patterns
    if any(kw in title_lower for kw in ["bitcoin", "btc", "비트코인"]):
        if entity_str:
            return f"비트코인 관련 주요 소식입니다. {entity_str} 등 핵심 내용을 {label}에서 보도했습니다."
        return f"{label}에서 비트코인 시장 동향을 보도했습니다."
    if any(kw in title_lower for kw in ["ethereum", "eth", "이더리움"]):
        if entity_str:
            return f"이더리움 관련 소식입니다. {entity_str} 등이 언급되었습니다. ({label})"
        return f"{label}에서 이더리움 관련 소식을 전했습니다."
    if any(kw in title_lower for kw in ["solana", "sol", "솔라나"]):
        return f"{label}에서 솔라나 생태계 관련 소식을 보도했습니다." + (f" ({entity_str})" if entity_str else "")
    if any(kw in title_lower for kw in ["xrp", "ripple", "리플"]):
        return f"{label}에서 XRP·리플 관련 소식을 전했습니다." + (f" ({entity_str})" if entity_str else "")
    if any(kw in title_lower for kw in ["defi", "디파이", "tvl"]):
        return "DeFi 생태계 동향입니다." + (
            f" {entity_str} 관련 변화가 보고되었습니다." if entity_str else f" ({label})"
        )
    if any(kw in title_lower for kw in ["nft", "metaverse", "메타버스"]):
        return "NFT·메타버스 관련 소식입니다." + (f" ({entity_str})" if entity_str else f" ({label})")
    if any(kw in title_lower for kw in ["hack", "exploit", "breach", "해킹", "보안"]):
        return "보안 사건이 보고되었습니다." + (
            f" {entity_str} 관련 내용을 확인하세요." if entity_str else f" ({label})"
        )
    if any(kw in title_lower for kw in ["stablecoin", "스테이블코인", "usdt", "usdc"]):
        return "스테이블코인 관련 소식입니다." + (f" {entity_str} ({label})" if entity_str else f" ({label})")
    if any(kw in title_lower for kw in ["whale", "고래", "large transfer"]):
        return "대규모 자금 이동이 감지되었습니다." + (f" {entity_str} ({label})" if entity_str else f" ({label})")
    if any(kw in title_lower for kw in ["etf", "spot etf"]):
        return "ETF 관련 소식입니다." + (f" {entity_str} 흐름이 주목됩니다." if entity_str else f" ({label})")
    if any(kw in title_lower for kw in ["mining", "채굴", "hashrate", "해시레이트"]):
        return "채굴·해시레이트 관련 소식입니다." + (f" ({entity_str})" if entity_str else f" ({label})")

    # Stock-specific patterns
    if any(kw in title_lower for kw in ["earnings", "revenue", "실적", "매출"]):
        return "기업 실적 관련 뉴스입니다." + (f" {entity_str} 실적이 주목됩니다." if entity_str else f" ({label})")
    if any(kw in title_lower for kw in ["fed", "fomc", "금리", "rate", "interest"]):
        return "금리·통화정책 관련 뉴스입니다." + (
            f" {entity_str} 변동이 시장에 영향을 줄 수 있습니다." if entity_str else f" ({label})"
        )
    if any(kw in title_lower for kw in ["ipo", "상장"]):
        return "IPO·상장 관련 뉴스입니다." + (f" {entity_str} ({label})" if entity_str else f" ({label})")
    if any(kw in title_lower for kw in ["tariff", "관세", "trade war", "무역"]):
        return "관세·무역 정책 관련 뉴스입니다." + (
            f" {entity_str} 이슈가 부각되고 있습니다." if entity_str else f" ({label})"
        )
    if any(kw in title_lower for kw in ["nasdaq", "s&p", "dow", "나스닥", "다우"]):
        return "미국 증시 관련 소식입니다." + (f" {entity_str} ({label})" if entity_str else f" ({label})")
    if any(kw in title_lower for kw in ["kospi", "kosdaq", "코스피", "코스닥"]):
        return "한국 증시 관련 소식입니다." + (f" {entity_str} ({label})" if entity_str else f" ({label})")

    # Political-specific patterns
    if any(kw in title_lower for kw in ["executive order", "행정명령"]):
        return "행정명령 관련 뉴스입니다." + (f" {entity_str} ({label})" if entity_str else f" ({label})")
    if any(kw in title_lower for kw in ["congress", "의회", "senate", "상원"]):
        return "의회 동향 관련 뉴스입니다." + (f" {entity_str} ({label})" if entity_str else f" ({label})")
    if any(kw in title_lower for kw in ["insider", "내부자", "form 4"]):
        return "내부자 거래 관련 공시입니다." + (f" {entity_str} ({label})" if entity_str else f" ({label})")
    if any(kw in title_lower for kw in ["trump", "트럼프"]):
        return "트럼프 관련 정책 소식입니다." + (f" {entity_str} ({label})" if entity_str else f" ({label})")

    # Regulatory patterns
    if any(kw in title_lower for kw in ["regulation", "규제", "compliance"]):
        return "규제 관련 뉴스입니다." + (f" {entity_str} ({label})" if entity_str else f" ({label})")
    if any(kw in title_lower for kw in ["sec", "cftc", "금융위"]):
        return "금융 당국 관련 소식입니다." + (f" {entity_str} ({label})" if entity_str else f" ({label})")

    # World news patterns
    if any(kw in title_lower for kw in ["war", "전쟁", "conflict", "분쟁"]):
        return "분쟁·안보 관련 뉴스입니다." + (f" {entity_str} ({label})" if entity_str else f" ({label})")
    if any(kw in title_lower for kw in ["election", "선거", "vote", "투표"]):
        return "선거·정치 관련 뉴스입니다." + (f" {entity_str} ({label})" if entity_str else f" ({label})")
    if any(kw in title_lower for kw in ["climate", "기후", "환경"]):
        return "기후·환경 관련 뉴스입니다." + (f" {entity_str} ({label})" if entity_str else f" ({label})")

    # Exchange-specific fallback
    if any(kw in source.lower() for kw in ["binance", "bybit", "okx", "upbit"]):
        return f"{label} 공지사항입니다." + (f" ({entity_str})" if entity_str else "")

    # Generic fallback: use title entities for specificity
    if entity_str:
        return f"{label}에서 {entity_str} 관련 소식을 보도했습니다."
    return f"{label}에서 보도한 뉴스입니다."


def enrich_item(
    item: Dict[str, Any],
    context_map: Optional[Dict[str, str]] = None,
    fetch_url: bool = True,
    max_fetch: int = 10,
    _fetch_counter: Optional[list] = None,
) -> None:
    """Enrich an item with a description if missing or duplicate of title.

    Parameters
    ----------
    item : dict
        News item with at least ``title``, ``description``, ``source``, ``link``.
    context_map : dict, optional
        Mapping of source names to Korean labels.
    fetch_url : bool
        Whether to attempt fetching the URL for a description.
    max_fetch : int
        Maximum number of URL fetches per call batch (rate limiting).
    _fetch_counter : list, optional
        Mutable counter ``[count]`` to track fetches across calls.
    """
    title = item.get("title", "")
    desc = item.get("description", "").strip()
    source = item.get("source", "")
    link = item.get("link", "")

    # Check if existing description is actually good
    if desc and len(desc) > 20:
        # Reject if desc is just title with source appended (RSS artifact)
        # e.g. "Article Title Here sourcename.com"
        if desc == title:
            pass  # fall through to enrichment
        elif title and desc.startswith(title[:30]):
            pass  # description is title prefix + noise
        elif any(p.search(desc) for p in _NOISE_DESC_PATTERNS):
            pass  # noise content (JS required, etc.)
        else:
            return  # already has a good description

    # Try fetching from URL (skip Google News proxy links)
    if fetch_url and link and "news.google.com" not in link:
        counter = _fetch_counter or [0]
        if counter[0] < max_fetch:
            counter[0] += 1
            metadata = fetch_page_metadata(link)
            fetched = metadata.get("description", "")
            if fetched and fetched != title and len(fetched) > 20:
                # Clean HTML entities and normalize whitespace
                fetched = re.sub(r"&[a-z]+;", " ", fetched)
                fetched = re.sub(r"\s+", " ", fetched).strip()
                item["description"] = fetched
            # Extract og:image if not already set from RSS
            if not item.get("image") and metadata.get("image"):
                item["image"] = metadata["image"]
            if item.get("description") and len(item["description"]) > 20:
                return

    # Generate synthetic description
    item["description"] = generate_synthetic_description(title, source, context_map)


def enrich_items(
    items: list,
    context_map: Optional[Dict[str, str]] = None,
    fetch_url: bool = True,
    max_fetch: int = 10,
) -> None:
    """Enrich a list of items in-place.

    After standard enrichment, translates English titles and
    descriptions to Korean (stored as ``title_ko`` / ``description_ko``).
    Original fields are never modified to preserve dedup safety.
    """
    counter = [0]
    for item in items:
        enrich_item(
            item,
            context_map=context_map,
            fetch_url=fetch_url,
            max_fetch=max_fetch,
            _fetch_counter=counter,
        )

    # --- Translation pass (after all enrichment is done) ---
    from .translator import (
        TRANSLATION_ENABLED,
        save_translation_cache,
        translate_to_korean,
    )
    from .utils import detect_language

    if not TRANSLATION_ENABLED:
        return

    for item in items:
        title = item.get("title", "")
        if title and detect_language(title) == "en":
            item["title_original"] = title
            ko = translate_to_korean(title)
            if ko != title:
                item["title_ko"] = ko

        desc = item.get("description", "")
        if desc and detect_language(desc) == "en" and not desc.startswith(("구글 뉴스", "에서 보도")):
            ko_desc = translate_to_korean(desc)
            if ko_desc != desc:
                item["description_ko"] = ko_desc

    save_translation_cache()
