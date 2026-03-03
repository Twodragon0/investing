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


def fetch_page_description(url: str, timeout: int = 8) -> str:
    """Try to fetch meta description from a URL page (best-effort).

    Checks ``<meta name="description">``, ``og:description``, and
    falls back to the first ``<p>`` with more than 50 characters.
    Returns an empty string on failure.
    """
    if not url or "news.google.com/rss/" in url:
        return ""

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

        for attr_key, attr_val in [
            ("name", "description"),
            ("property", "og:description"),
        ]:
            meta = soup.find("meta", attrs={attr_key: attr_val})
            if meta and meta.get("content", "").strip() and len(meta["content"].strip()) > 20:
                return meta["content"].strip()[:300]

        for p in soup.find_all("p"):
            text = p.get_text(strip=True)
            if len(text) > 50:
                return text[:300]
    except Exception as e:  # noqa: BLE001
        logger.debug("Failed to fetch description from %s: %s", url, e)
    return ""


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


def _get_source_label(source: str, context_map: Dict[str, str]) -> str:
    """Get a Korean label for a source name."""
    return context_map.get(source, source)


def generate_synthetic_description(
    title: str,
    source: str,
    context_map: Optional[Dict[str, str]] = None,
) -> str:
    """Generate a contextual description when RSS provides none.

    Uses title keywords to produce a relevant Korean summary sentence.
    """
    label = _get_source_label(source, context_map or {})
    title_lower = title.lower()

    # Crypto-specific patterns
    if any(kw in title_lower for kw in ["bitcoin", "btc", "비트코인"]):
        return f"{label}에서 보도한 비트코인 관련 시장 동향입니다."
    if any(kw in title_lower for kw in ["ethereum", "eth", "이더리움"]):
        return f"{label}에서 보도한 이더리움 관련 소식입니다."
    if any(kw in title_lower for kw in ["defi", "디파이", "tvl"]):
        return f"{label}에서 보도한 DeFi 생태계 동향입니다."
    if any(kw in title_lower for kw in ["nft", "metaverse", "메타버스"]):
        return f"{label}에서 보도한 NFT·메타버스 관련 소식입니다."
    if any(kw in title_lower for kw in ["hack", "exploit", "breach", "해킹", "보안"]):
        return f"{label}에서 보도한 보안 사건 관련 보도입니다."

    # Stock-specific patterns
    if any(kw in title_lower for kw in ["earnings", "revenue", "실적", "매출"]):
        return f"{label}에서 보도한 기업 실적 관련 뉴스입니다."
    if any(kw in title_lower for kw in ["fed", "fomc", "금리", "rate", "interest"]):
        return f"{label}에서 보도한 금리·통화정책 관련 뉴스입니다."
    if any(kw in title_lower for kw in ["ipo", "상장"]):
        return f"{label}에서 보도한 IPO·상장 관련 뉴스입니다."
    if any(kw in title_lower for kw in ["tariff", "관세", "trade war", "무역"]):
        return f"{label}에서 보도한 관세·무역 정책 관련 뉴스입니다."

    # Political-specific patterns
    if any(kw in title_lower for kw in ["executive order", "행정명령"]):
        return f"{label}에서 보도한 행정명령 관련 뉴스입니다."
    if any(kw in title_lower for kw in ["congress", "의회", "senate", "상원"]):
        return f"{label}에서 보도한 의회 동향 관련 뉴스입니다."
    if any(kw in title_lower for kw in ["insider", "내부자", "form 4"]):
        return f"{label}에서 보도한 내부자 거래 관련 공시입니다."

    # Regulatory patterns
    if any(kw in title_lower for kw in ["regulation", "규제", "compliance"]):
        return f"{label}에서 보도한 규제 관련 뉴스입니다."
    if any(kw in title_lower for kw in ["sec", "cftc", "금융위"]):
        return f"{label}에서 보도한 금융 당국 관련 소식입니다."

    # World news patterns
    if any(kw in title_lower for kw in ["war", "전쟁", "conflict", "분쟁"]):
        return f"{label}에서 보도한 분쟁·안보 관련 뉴스입니다."
    if any(kw in title_lower for kw in ["election", "선거", "vote", "투표"]):
        return f"{label}에서 보도한 선거·정치 관련 뉴스입니다."
    if any(kw in title_lower for kw in ["climate", "기후", "환경"]):
        return f"{label}에서 보도한 기후·환경 관련 뉴스입니다."

    # Exchange-specific fallback
    if any(kw in source.lower() for kw in ["binance", "bybit", "okx", "upbit"]):
        return f"{label} 공지사항입니다."

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

    if desc and desc != title and len(desc) > 20:
        return  # already has a good description

    # Try fetching from URL (skip Google News proxy links)
    if fetch_url and link and "news.google.com" not in link:
        counter = _fetch_counter or [0]
        if counter[0] < max_fetch:
            counter[0] += 1
            fetched = fetch_page_description(link)
            if fetched and fetched != title and len(fetched) > 20:
                # Clean HTML entities
                fetched = re.sub(r"&[a-z]+;", " ", fetched).strip()
                item["description"] = fetched
                return

    # Generate synthetic description
    item["description"] = generate_synthetic_description(title, source, context_map)


def enrich_items(
    items: list,
    context_map: Optional[Dict[str, str]] = None,
    fetch_url: bool = True,
    max_fetch: int = 10,
) -> None:
    """Enrich a list of items in-place."""
    counter = [0]
    for item in items:
        enrich_item(
            item,
            context_map=context_map,
            fetch_url=fetch_url,
            max_fetch=max_fetch,
            _fetch_counter=counter,
        )
