"""Shared URL content enrichment for news collectors.

Provides functions to fetch meta descriptions from URLs and generate
synthetic descriptions when actual content is unavailable.
"""

import logging
import re
from typing import Any, Dict, Optional

import requests

from .config import get_ssl_verify
from .markdown_utils import smart_truncate

logger = logging.getLogger(__name__)

VERIFY_SSL = get_ssl_verify()

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


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
        # Korean boilerplate
        "무단전재 및 재배포 금지",
        "저작권자 ©",
        "기사제보 및 보도자료",
        "네이버 뉴스스탠드에서",
        "카카오톡에서 받아보기",
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
        r"|경향신문|한겨레|BBS불교방송|이데일리|뉴시스|아시아경제"
        r"|서울경제|뉴스1|노컷뉴스|SBS뉴스|MBC뉴스|KBS뉴스|JTBC|채널A|TV조선|연합뉴스"
        r"|파이낸셜뉴스|헤럴드경제|머니투데이|더팩트|데일리안|뉴데일리|오마이뉴스"
        r"|프레시안|시사저널|주간조선|한겨레21|인사이트|위키트리|ZDNet\s*Korea"
        r"|핀포인트뉴스|공감신문|브레이크뉴스|한국글로벌뉴스|gukjenews\.com|ilyoseoul\.co\.kr"
        r")\s*$",
        "",
        text,
    )
    # Generic trailing domain-like source (e.g. "...text simplywall.st")
    text = re.sub(r"\s+[a-z][a-z0-9-]*\.[a-z]{2,6}$", "", text)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _decode_google_news_base64(url: str) -> str:
    """Try to extract the actual article URL from a Google News RSS URL.

    Google News RSS URLs like ``https://news.google.com/rss/articles/CBMi...``
    contain a base64-encoded payload that wraps the real article URL.
    """
    import base64
    import urllib.parse

    try:
        # Extract the base64 segment after /articles/
        match = re.search(r"/rss/articles/([A-Za-z0-9_-]+)", url)
        if not match:
            return ""
        encoded = match.group(1)
        # Add padding if needed
        padded = encoded + "=" * (4 - len(encoded) % 4) if len(encoded) % 4 else encoded
        # Try standard and URL-safe base64
        for decoder in [base64.urlsafe_b64decode, base64.b64decode]:
            try:
                raw = decoder(padded)
                decoded_str = raw.decode("utf-8", errors="ignore")
                # Find URLs embedded in the decoded bytes
                urls = re.findall(r"https?://[^\s\"'<>\x00-\x1f]+", decoded_str)
                for candidate in urls:
                    if "news.google.com" not in candidate and "google." not in candidate:
                        return urllib.parse.unquote(candidate).rstrip("\x00")
            except Exception:  # noqa: BLE001, S112
                continue
    except Exception:  # noqa: BLE001, S110
        pass
    return ""


def _resolve_google_news_url(url: str, timeout: int = 8) -> str:
    """Follow Google News redirect to get the real article URL.

    Strategy:
    1. Try base64 decoding of the RSS article path (fastest, no network).
    2. Follow HTTP redirects with ``requests.head`` then ``requests.get``.
    3. Parse HTML for canonical/og:url if still on Google domain.
    """
    if not url or "news.google.com" not in url:
        return url

    # 1. Try base64 decoding (no network call needed)
    decoded = _decode_google_news_base64(url)
    if decoded:
        logger.debug("Google News base64 decoded: %s -> %s", url[:60], decoded[:80])
        return decoded

    # 2. Follow HTTP redirects
    try:
        # Try HEAD first (lighter)
        head_resp = requests.head(
            url,
            timeout=timeout,
            allow_redirects=True,
            headers={"User-Agent": _BROWSER_UA},
            verify=VERIFY_SSL,
        )
        if head_resp.url and "news.google.com" not in head_resp.url:
            return head_resp.url
    except requests.exceptions.RequestException:
        pass

    # 3. Full GET and parse HTML for canonical/og:url
    try:
        resp = requests.get(
            url,
            timeout=timeout,
            allow_redirects=True,
            headers={"User-Agent": _BROWSER_UA},
            verify=VERIFY_SSL,
        )
        # Check if HTTP redirect resolved to real site
        if resp.url and "news.google.com" not in resp.url:
            return resp.url
        # Try to find canonical or data-url in HTML
        for pattern in [
            r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)',
            r'<meta[^>]+property=["\']og:url["\'][^>]+content=["\']([^"\']+)',
            r'data-url=["\']([^"\']+)',
            r'<a[^>]+data-redirect=["\']([^"\']+)',
        ]:
            m = re.search(pattern, resp.text[:20_000])
            if m:
                found = m.group(1)
                if found and "news.google.com" not in found:
                    return found
    except requests.exceptions.RequestException:
        pass
    return ""


_BROWSER_UA = _USER_AGENT


def _is_valid_image_url(url: str) -> bool:
    """Check if a URL is likely a valid, useful image (not a placeholder/tracking pixel)."""
    if not url or not url.startswith("http"):
        return False
    url_lower = url.lower()
    # Reject known tracking pixels and placeholder images
    _BAD_PATTERNS = [
        "1x1", "pixel", "tracker", "beacon", "spacer",
        "placeholder", "default-image", "no-image", "blank.",
        "gravatar.com/avatar", "wp-content/plugins",
    ]
    if any(p in url_lower for p in _BAD_PATTERNS):
        return False
    # Reject non-image extensions
    _BAD_EXTENSIONS = [".gif", ".svg", ".ico", ".webp"]
    # .gif is often a tracking pixel; .svg/.ico are usually logos
    if any(url_lower.endswith(ext) for ext in _BAD_EXTENSIONS):
        # Allow large webp/gif if they have meaningful paths
        if ".webp" in url_lower or len(url) > 80:
            return True
        return False
    return True


def _fetch_og_image(url: str, timeout: int = 8) -> str:
    """Fetch only og:image from a URL (lightweight, no description)."""
    if not url:
        return ""
    try:
        import re as _re

        resp = requests.get(
            url,
            timeout=timeout,
            headers={"User-Agent": _BROWSER_UA},
            verify=VERIFY_SSL,
        )
        resp.raise_for_status()
        # Search in first 30KB of HTML for og:image via regex (faster than BS4)
        head_html = resp.text[:30_000]
        for pattern in [
            r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)',
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image',
            r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)',
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']twitter:image',
        ]:
            match = _re.search(pattern, head_html, _re.IGNORECASE)
            if match:
                img_url = match.group(1).strip()
                if _is_valid_image_url(img_url):
                    return img_url
    except Exception as exc:
        logger.debug("og:image fetch failed for %s: %s", url, exc)
    return ""


def fetch_images_concurrent(
    items: list,
    max_workers: int = 8,
    max_items: int = 30,
) -> int:
    """Fetch og:image for items missing images, using concurrent threads.

    Resolves Google News redirect URLs first, then fetches og:image.
    Returns the number of images successfully fetched.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    targets = [(i, item) for i, item in enumerate(items) if not item.get("image") and item.get("link")][:max_items]

    if not targets:
        return 0

    fetched = 0

    def _fetch_one(idx: int, item: dict) -> tuple:
        link = item["link"]
        # Resolve Google News redirects
        if "news.google.com" in link:
            link = _resolve_google_news_url(link)
        if not link:
            return idx, ""
        return idx, _fetch_og_image(link)

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_fetch_one, idx, item): idx for idx, item in targets}
        for future in as_completed(futures):
            try:
                idx, img_url = future.result(timeout=15)
                if img_url:
                    items[idx]["image"] = img_url
                    fetched += 1
            except Exception as exc:
                logger.debug("Image fetch failed for item %d: %s", idx, exc)

    if fetched:
        logger.info("Fetched %d og:images for %d items", fetched, len(targets))
    return fetched


def fetch_descriptions_concurrent(
    items: list,
    max_workers: int = 6,
    max_items: int = 50,
) -> int:
    """Fetch descriptions for items with missing/synthetic descriptions using concurrent threads.

    Resolves Google News redirect URLs first, then fetches meta descriptions
    and article body text. Returns the number of descriptions successfully fetched.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    _SYNTHETIC_MARKERS = [
        "관련 소식입니다",
        "관련 시장 뉴스입니다",
        "원문에서 세부 내용을 확인하세요",
        "원문 기사의 세부 내용을 확인하세요",
        "투자 판단 시",
        "면밀히 분석해야 합니다",
        "함께 고려해야 합니다",
    ]

    def _needs_enrichment(item: dict) -> bool:
        desc = item.get("description", "").strip()
        if not desc or len(desc) < 30:
            return True
        if desc == item.get("title", ""):
            return True
        return any(marker in desc for marker in _SYNTHETIC_MARKERS)

    targets = [(i, item) for i, item in enumerate(items) if _needs_enrichment(item) and item.get("link")][:max_items]

    if not targets:
        return 0

    fetched = 0

    def _fetch_one(idx: int, item: dict) -> tuple:
        link = item.get("link", "")
        if "news.google.com" in link:
            link = _resolve_google_news_url(link)
        if not link:
            return idx, ""
        metadata = fetch_page_metadata(link)
        return idx, metadata.get("description", "")

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_fetch_one, idx, item): idx for idx, item in targets}
        for future in as_completed(futures):
            try:
                idx, desc = future.result(timeout=15)
                if desc and len(desc) > 30 and desc != items[idx].get("title", ""):
                    items[idx]["description"] = desc
                    fetched += 1
            except Exception as exc:
                logger.debug("Description fetch failed for item %d: %s", futures[future], exc)

    if fetched:
        logger.info("Concurrent description fetch: enriched %d/%d items", fetched, len(targets))
    return fetched


def fetch_page_metadata(url: str, timeout: int = 8) -> Dict[str, str]:
    """Fetch meta description and og:image from a URL page (best-effort).

    Returns a dict with keys ``description`` and ``image`` (empty strings on failure).
    """
    result: Dict[str, str] = {"description": "", "image": ""}
    if not url:
        return result
    # Resolve Google News redirects (any news.google.com URL)
    if "news.google.com" in url:
        resolved = _resolve_google_news_url(url)
        if not resolved:
            return result
        url = resolved

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
                result["description"] = smart_truncate(cleaned, 500)
                return result

        # 4a: Try readability-lxml for high-quality article extraction
        try:
            from readability import Document

            doc = Document(resp.text)
            summary_html = doc.summary()
            summary_soup = BS4(summary_html, "html.parser")
            paragraphs = []
            for p in summary_soup.find_all("p"):
                text = _clean_description(p.get_text(strip=True))
                if len(text) > 50:
                    paragraphs.append(text)
                if len(paragraphs) >= 5:
                    break
            if paragraphs:
                combined = " ".join(paragraphs)
                result["description"] = smart_truncate(combined, 500)
                return result
        except ImportError:
            pass  # readability-lxml not installed, fall through
        except Exception as exc:  # noqa: BLE001
            logger.debug("readability extraction failed for %s: %s", url, exc)

        # 4b: Article body paragraphs (BS4 fallback)
        # Exclude non-content containers (sidebars, ads, navigation, comments)
        _EXCLUDE_CLASS_RE = re.compile(
            r"sidebar|widget|nav|menu|footer|header|comment|social|share|promo|"
            r"ad-|ads-|advert|sponsor|related|recommend|popup|modal|cookie|banner",
            re.I,
        )
        article = soup.find("article")
        if not article:
            # More precise content container matching
            for tag in soup.find_all(class_=re.compile(r"article[-_]?(body|content|text)|post[-_]?(body|content|text)|entry[-_]?(body|content|text)")):
                if not _EXCLUDE_CLASS_RE.search(str(tag.get("class", ""))):
                    article = tag
                    break
        if not article:
            for tag in soup.find_all(class_=re.compile(r"^(article|post|entry|content)$")):
                if not _EXCLUDE_CLASS_RE.search(str(tag.get("class", ""))):
                    article = tag
                    break
        if article:
            # Remove nested non-content elements before extracting text
            for noise in article.find_all(class_=_EXCLUDE_CLASS_RE):
                noise.decompose()
            paragraphs = []
            for p in article.find_all("p"):
                text = _clean_description(p.get_text(strip=True))
                if len(text) > 50:
                    paragraphs.append(text)
                if len(paragraphs) >= 5:
                    break
            if paragraphs:
                combined = " ".join(paragraphs)
                result["description"] = smart_truncate(combined, 500)
                return result

        # 5: Fallback to any <p> (skip short ad-like text)
        for p in soup.find_all("p"):
            # Skip paragraphs inside non-content containers
            if p.find_parent(class_=_EXCLUDE_CLASS_RE):
                continue
            text = _clean_description(p.get_text(strip=True))
            if len(text) > 50:
                result["description"] = smart_truncate(text, 500)
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
    _COMMON = {
        "The",
        "And",
        "For",
        "With",
        "Has",
        "Are",
        "Its",
        "But",
        "How",
        "Why",
        "What",
        "New",
        "All",
        "Can",
        "Now",
        "Get",
        "Set",
        "May",
        "Not",
        "Other",
        "Others",
        "Another",
        "Being",
        "Having",
        "Doing",
        "Becomes",
        "Become",
        "Getting",
        "Going",
        "Coming",
        "Making",
        "Says",
        "Said",
        "Warns",
        "Faces",
        "Shows",
        "Finds",
        "Takes",
        "Gives",
        "Looks",
        "Tells",
        "Seems",
        "Turns",
        "Leads",
        "Holds",
        "Spikes",
        "Spike",
        "Surges",
        "Surge",
        "Drops",
        "Drop",
        "Falls",
        "First",
        "Last",
        "Next",
        "After",
        "Before",
        "During",
        "Under",
        "Over",
        "About",
        "Every",
        "Where",
        "Which",
        "While",
        "Their",
        "These",
        "Those",
        "Could",
        "Would",
        "Should",
        "Might",
        "Still",
        "Just",
        "Also",
        "More",
        "Most",
        "Some",
        "Much",
        "Many",
        "Each",
        "Only",
        "Even",
        "Very",
        "Here",
        "There",
        "Then",
        "Than",
        "Into",
        "From",
        "This",
        "That",
        "Been",
        "Were",
        "Will",
        "Your",
        "They",
        "Them",
        "Such",
        "Like",
        "Near",
        "Amid",
        "Ahead",
        "Along",
        "Among",
        "Above",
        "Below",
        "Behind",
        "Between",
        "Through",
        "Against",
        "Within",
        "Without",
        "Across",
        "Inside",
        "Global",
        "World",
        "Major",
        "Latest",
        "Breaking",
        "Live",
        "Watch",
        "Alert",
        "Update",
        "Report",
        "Check",
        "Shares",
        "Stock",
        "Stocks",
        "Market",
        "Markets",
        "Price",
        "Prices",
        "Trade",
        "Trades",
        "Trading",
        "Company",
        "Companies",
        "Industry",
        "Million",
        "Billion",
        "Trillion",
        "Today",
        "Yesterday",
        "Tomorrow",
        "Year",
        "Week",
        "Month",
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday",
        "Better",
        "Bigger",
        "Lower",
        "Higher",
        "Early",
        "Late",
        "Huge",
        "Massive",
        "Record",
        "Rising",
        "Falling",
        "Since",
        "Until",
        "Whether",
        "Biggest",
        "Worst",
        "Best",
        "Headed",
        "Heads",
        "Keep",
        "Keeps",
        "Stayed",
        "Stays",
        "Stay",
        "Worse",
        "Linked",
        "Issues",
        "Issue",
        "Based",
        "Using",
        "Asked",
        "Asking",
        "Called",
        "Calls",
        "Named",
        "Known",
        "Seen",
        "Taken",
        "Given",
        "Several",
        "Certain",
        "Entire",
        "Recent",
        "Little",
        "Large",
        "Small",
        "Long",
        "Short",
        "Full",
        "Half",
        "Wants",
        "Needs",
        "Tries",
        "Three",
        "Four",
        "Five",
    }
    _NOISE_TICKERS = {
        "CEO",
        "IPO",
        "SEC",
        "FED",
        "GDP",
        "CPI",
        "ETF",
        "AI",
        "US",
        "UK",
        "EU",
        "USD",
        "FOR",
        "THE",
        "ARE",
        "HAS",
        "NOT",
        "BUT",
        "ALL",
        "CAN",
        "NOW",
        "HOW",
        "NEW",
        "CBS",
        "FBI",
        "GOP",
        "DHS",
        "RFK",
        "ITS",
        "WAS",
        "HIS",
        "HER",
        "WHO",
        "MAY",
        "BIG",
        "TOP",
        "TWO",
        "OUR",
        "SAY",
        "ANY",
        "FEW",
        "RED",
    }
    tickers = [t for t in tickers if t not in _NOISE_TICKERS]
    proper = [w for w in re.findall(r"\b[A-Z][a-z]{2,}\b", title) if w not in _COMMON]

    entities.extend(values)
    entities.extend(tickers[:2])
    entities.extend(proper[:2])
    entities.extend(kr_entities[:3])
    # Deduplicate while preserving order
    seen = set()
    deduped = []
    for e in entities:
        if e.lower() not in seen:
            seen.add(e.lower())
            deduped.append(e)
    return deduped


def _analyze_title_content(title: str) -> str:
    """Generate an analytical Korean description from a news title.

    Instead of generic templates, this produces a title-derived summary
    that explains what the article is about and why it matters.
    """
    title_lower = title.lower()
    title_stripped = title.strip()

    # --- Korean title: extract meaning and add context ---
    kr_chars = len(re.findall(r"[가-힣]", title_stripped))
    if kr_chars > len(title_stripped) * 0.3:
        return _analyze_korean_title(title_stripped)

    # --- English title: translate key concepts and add analysis ---
    return _analyze_english_title(title_stripped, title_lower)


def _analyze_korean_title(title: str) -> str:
    """Analyze a Korean news title and generate contextual description."""
    # Circuit breaker / market crash
    if any(kw in title for kw in ["서킷브레이커", "사이드카"]):
        if "매수" in title:
            return (
                "급락 이후 반등 과정에서 매수 사이드카가 발동되었습니다. "
                "변동성 확대 장세에서 저점 매수세 유입 신호입니다."
            )
        return "급격한 하락으로 매매거래가 일시 중단되었습니다. 투자 심리 위축과 추가 하방 리스크에 유의해야 합니다."

    if any(kw in title for kw in ["폭락", "급락", "패닉"]):
        pct = re.search(r"(\d+(?:\.\d+)?)\s*%", title)
        pct_str = f" {pct.group(1)}% " if pct else " 큰 폭으로 "
        return (
            f"시장이{pct_str}급락하며 투매 양상이 나타났습니다. "
            "패닉 매도 시 비이성적 가격 형성 가능성에 주의가 필요합니다."
        )

    if any(kw in title for kw in ["급등", "폭등", "반등"]):
        return "시장 반등 움직임이 포착되었습니다. 기술적 반등인지 추세 전환인지 거래량과 수급 확인이 필요합니다."

    if any(kw in title for kw in ["전쟁", "분쟁", "군사", "이란", "중동"]):
        return "지정학적 리스크가 금융시장에 영향을 미치고 있습니다. 유가·환율·안전자산 흐름을 주시해야 합니다."

    if any(kw in title for kw in ["금리", "금통위", "한은", "한국은행"]):
        return "한국은행 통화정책 관련 소식입니다. 금리 결정은 채권·부동산·주식 시장 전반에 영향을 미칩니다."

    if any(kw in title for kw in ["환율", "원달러", "원화"]):
        return "환율 변동 소식입니다. 원화 약세는 수입 물가 상승과 외국인 매도 압력으로 이어질 수 있습니다."

    if any(kw in title for kw in ["삼성전자", "하이닉스", "반도체"]):
        if any(kw in title for kw in ["매수", "기회", "긍정"]):
            return (
                "반도체 섹터에 대한 매수 기회론이 제기되고 있습니다. "
                "업종 펀더멘탈과 글로벌 수요 동향 확인이 필요합니다."
            )
        if any(kw in title for kw in ["하락", "흔들", "약세"]):
            return (
                "반도체주가 외부 리스크로 약세를 보이고 있습니다. 섹터 하락이 일시적인지 구조적인지 판단이 중요합니다."
            )
        return "반도체 산업 관련 주요 소식입니다. 한국 증시에서 반도체는 시가총액 비중이 가장 높은 핵심 섹터입니다."

    if any(kw in title for kw in ["상장폐지", "주가조작", "불공정거래"]):
        return "불공정거래 적발 소식입니다. 투자 시 기업 실체와 거래 패턴 검증의 중요성을 재확인시킵니다."

    if any(kw in title for kw in ["거래시간", "제도", "규정"]):
        return "증시 제도 변경 관련 소식입니다. 거래 환경 변화에 따른 투자 전략 조정이 필요할 수 있습니다."

    if any(kw in title for kw in ["버블", "과열", "밸류에이션"]):
        return "시장 밸류에이션 논쟁이 이어지고 있습니다. 펀더멘탈 대비 가격 수준 점검이 필요한 시점입니다."

    if any(kw in title for kw in ["바이오", "제약"]):
        return "바이오·제약 섹터 관련 소식입니다. 임상 결과와 규제 승인 여부가 주가 변동의 핵심 변수입니다."

    if any(kw in title for kw in ["IPO", "공모", "상장"]):
        return "IPO·신규 상장 관련 소식입니다. 공모가 대비 시장 평가와 수급 동향을 주시하세요."

    if any(kw in title for kw in ["유가", "원유", "석유"]):
        return "유가 변동 소식입니다. 원유 가격은 인플레이션·교역조건·에너지 섹터에 직접적 영향을 미칩니다."

    if any(kw in title for kw in ["관세", "무역", "수출", "수입"]):
        return "통상·무역 정책 관련 소식입니다. 글로벌 공급망과 수출 기업 실적에 영향을 줄 수 있습니다."

    if any(kw in title for kw in ["배당", "주주환원", "자사주"]):
        return (
            "배당·주주환원 정책 관련 소식입니다. 배당 수익률과 자사주 매입 규모가 주가에 긍정적 영향을 줄 수 있습니다."
        )

    if any(kw in title for kw in ["부동산", "아파트", "전세", "분양"]):
        return "부동산 시장 관련 소식입니다. 금리·정책 변화에 따른 부동산 시장 흐름을 주시해야 합니다."

    if any(kw in title for kw in ["인수", "합병", "M&A"]):
        return "기업 인수·합병(M&A) 관련 소식입니다. 인수 프리미엄과 시너지 효과가 양사 주가에 영향을 줍니다."

    if any(kw in title for kw in ["비트코인", "이더리움", "알트코인", "리플"]):
        clean = re.sub(r"\s*[-–—|]\s*\S+$", "", title).strip()
        pct = re.search(r"(\d+(?:\.\d+)?)\s*%", title)
        if pct:
            return f"{clean[:120]}. {pct.group(1)}% 변동에 따른 시장 영향을 주시해야 합니다."
        return f"{clean[:120]}. 암호화폐 시장 동향과 투자 시사점을 확인하세요."

    if any(kw in title for kw in ["디파이", "디지털자산", "가상자산", "코인", "블록체인"]):
        clean = re.sub(r"\s*[-–—|]\s*\S+$", "", title).strip()
        return f"{clean[:120]}. 디지털 자산 시장의 최신 동향입니다."

    if any(kw in title for kw in ["AI", "인공지능", "챗봇", "생성형"]):
        clean = re.sub(r"\s*[-–—|]\s*\S+$", "", title).strip()
        return f"{clean[:120]}. AI 산업 성장에 따른 투자 기회를 점검해 보세요."

    if any(kw in title for kw in ["2차전지", "배터리", "전기차", "EV"]):
        clean = re.sub(r"\s*[-–—|]\s*\S+$", "", title).strip()
        return f"{clean[:120]}. 글로벌 전기차 수요와 배터리 기술 경쟁 동향입니다."

    if any(kw in title for kw in ["외국인", "기관", "순매수", "순매도", "수급"]):
        return "외국인·기관 수급 동향입니다. 대규모 순매수/순매도는 시장 방향성의 중요한 선행 지표입니다."

    if any(kw in title for kw in ["실적", "어닝", "매출", "영업이익"]):
        return "기업 실적 관련 소식입니다. 실적 서프라이즈 여부와 컨센서스 대비 결과가 주가 방향을 결정합니다."

    # Fallback: extract key nouns from title
    nouns = re.findall(r"[가-힣]{2,}", title)[:3]
    # Default: use title core as description
    clean = re.sub(r"\s*[-–—|]\s*\S+$", "", title).strip()
    if nouns:
        return f"{clean[:120]}. 주요 키워드: {', '.join(nouns[:3])}."
    return clean[:150] if len(clean) > 15 else title


def _analyze_english_title(title: str, title_lower: str) -> str:
    """Analyze an English news title and generate a specific Korean description."""
    _subj = _extract_title_entities(title)
    # Use only named entities (not raw numbers/prices) for the subject prefix
    _named = [e for e in _subj if not re.match(r"^[\d$,.%+\-]+$", e)]
    _subj_str = ", ".join(_named[:3]) if _named else ""

    # Extract numbers/percentages/prices from title for specificity
    pct_match = re.search(r"(\d[\d,.]*)\s*%", title)
    price_match = re.search(
        r"\$(\d[\d,.]*(?:\.\d+)?)\s*(billion|million|trillion|B|M|T)?",
        title,
        re.IGNORECASE,
    )
    points_match = re.search(r"(\d[\d,.]*)\s*(?:points?|pts?)", title, re.IGNORECASE)

    # Clean title: remove trailing source names for use as base description
    clean_title = re.sub(
        r"\s*[-–—|]\s*(?:Reuters|Bloomberg|CNBC|AP|MarketWatch|CoinDesk|Cointelegraph|TradingView|Yahoo Finance|The Motley Fool|Investopedia)\s*$",
        "",
        title,
        flags=re.IGNORECASE,
    ).strip()
    # Also remove generic trailing patterns (require a space before separator to avoid
    # matching hyphenated words like "All-Time")
    clean_title = re.sub(r"\s+[–—|]\s*[A-Z][\w\s]{2,20}$", "", clean_title).strip()

    # Build detail string from extracted numbers
    detail_parts = []
    if pct_match:
        detail_parts.append(f"{pct_match.group(1)}% 변동")
    if price_match:
        unit = price_match.group(2) or ""
        detail_parts.append(f"${price_match.group(1)}{unit}")
    if points_match:
        detail_parts.append(f"{points_match.group(1)}포인트")
    detail_str = ", ".join(detail_parts)

    # Determine event category and add specific context
    if any(kw in title_lower for kw in ["crash", "plunge", "tumble", "sink", "slump", "dive"]):
        base = clean_title[:120]
        extra = f" ({detail_str})" if detail_str else ""
        return f"{base}.{extra} 급락 배경과 반등 시점을 주시해야 합니다."

    if any(kw in title_lower for kw in ["rally", "surge", "soar", "jump", "climb", "gain"]):
        base = clean_title[:120]
        extra = f" ({detail_str})" if detail_str else ""
        return f"{base}.{extra} 상승 지속성을 확인해야 합니다."

    if any(kw in title_lower for kw in ["drop", "fall ", "decline", "down ", "lower", "slip"]):
        base = clean_title[:120]
        extra = f" ({detail_str})" if detail_str else ""
        return f"{base}.{extra}"

    if any(kw in title_lower for kw in ["rise", "up ", "higher", "advance"]):
        base = clean_title[:120]
        extra = f" ({detail_str})" if detail_str else ""
        return f"{base}.{extra}"

    if any(kw in title_lower for kw in ["oil", "crude", "brent", "wti"]):
        base = clean_title[:120]
        extra = f" ({detail_str})" if detail_str else ""
        return f"{base}.{extra} 유가 변동은 인플레이션과 에너지 섹터에 직접 영향을 미칩니다."

    if any(kw in title_lower for kw in ["iran", "war", "conflict", "military", "attack"]):
        return f"{clean_title[:120]}. 지정학적 리스크가 글로벌 시장 심리에 영향을 주고 있습니다."

    if any(kw in title_lower for kw in ["earning", "revenue", "profit", "guidance", "beat", "miss"]):
        return f"{clean_title[:120]}. 실적 결과가 향후 주가 방향을 결정합니다."

    if any(kw in title_lower for kw in ["fed", "fomc", "powell", "rate cut", "rate hike"]):
        return f"{clean_title[:120]}. 연준 정책은 글로벌 자산 배분의 핵심 변수입니다."

    if any(kw in title_lower for kw in ["trump", "white house", "executive order", "tariff"]):
        return f"{clean_title[:120]}. 정책 변화가 시장에 미치는 영향을 주시해야 합니다."

    if any(kw in title_lower for kw in ["bitcoin", "btc", "crypto", "ethereum", "altcoin"]):
        return f"{clean_title[:120]}."

    if any(kw in title_lower for kw in ["s&p", "nasdaq", "dow", "futures", "stock market"]):
        base = clean_title[:120]
        extra = f" ({detail_str})" if detail_str else ""
        return f"{base}.{extra}"

    if any(kw in title_lower for kw in ["ai ", "artificial intelligence", "nvidia", "semiconductor", "chip"]):
        return f"{clean_title[:120]}."

    if any(kw in title_lower for kw in ["gold", "silver", "precious"]):
        return f"{clean_title[:120]}."

    # Default: use cleaned title with contextual suffix
    _meaningful = [e for e in _named if len(e) > 2]
    if _meaningful:
        subj = ", ".join(_meaningful[:2])
        extra = f" ({detail_str})" if detail_str else ""
        return f"{clean_title[:120]}.{extra} {subj} 관련 시장 동향입니다."
    if detail_str:
        return f"{clean_title[:120]}. ({detail_str})"
    return f"{clean_title[:140]}." if len(clean_title) > 15 else title


def generate_synthetic_description(
    title: str,
    source: str,
    context_map: Optional[Dict[str, str]] = None,
) -> str:
    """Generate a contextual description when RSS provides none.

    Uses title content analysis to produce meaningful, specific summaries
    instead of generic template-based descriptions.
    """
    # Try title-based analysis first (produces specific, analytical content)
    analysis = _analyze_title_content(title)
    if analysis and analysis != title and len(analysis) > 20:
        return analysis

    # Fallback: build a title-derived description with source context
    label = _get_source_label(source, context_map or {})
    entities = _extract_title_entities(title)
    entity_str = ", ".join(entities[:3]) if entities else ""

    # Exchange-specific fallback
    if any(kw in source.lower() for kw in ["binance", "bybit", "okx", "upbit"]):
        return f"{label} 공지사항입니다." + (f" ({entity_str})" if entity_str else "")

    # Build a title-condensed description instead of boilerplate
    # Clean trailing source names from the title
    clean_title = re.sub(r"\s*[-–—|]\s*\S+$", "", title).strip()
    # For Korean titles, extract a condensed version
    kr_chars = len(re.findall(r"[가-힣]", clean_title))
    if kr_chars > len(clean_title) * 0.3:
        # Korean: use title core + entities for context
        core = clean_title[:80] if len(clean_title) > 80 else clean_title
        if entity_str:
            return f"{core}. {entity_str} 관련 세부 내용은 원문을 참고하세요."
        return f"{core}. 원문에서 상세 내용을 확인하세요."

    # English: use cleaned title with source context
    if label and label != source:
        return f"{label} 보도입니다. {clean_title[:100]}"
    return clean_title[:150] if len(clean_title) > 15 else title


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

    # Try fetching from URL (including Google News URLs via resolution)
    if fetch_url and link:
        counter = _fetch_counter or [0]
        if counter[0] < max_fetch:
            counter[0] += 1
            metadata = fetch_page_metadata(link)
            fetched = metadata.get("description", "")
            if fetched and fetched != title and len(fetched) > 20:
                # Clean HTML entities and normalize whitespace
                fetched = re.sub(r"&#?\w+;", " ", fetched)
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
    max_fetch: int = 30,
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

    # --- Image fetch pass (concurrent og:image for items missing images) ---
    fetch_images_concurrent(items, max_workers=8, max_items=30)

    # --- Description enrichment pass (concurrent fetch for synthetic descriptions) ---
    if fetch_url:
        fetch_descriptions_concurrent(items, max_workers=6, max_items=50)

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
        if (
            desc
            and detect_language(desc) == "en"
            and not any(
                desc.startswith(prefix)
                for prefix in (
                    "구글 뉴스",
                    "에서 보도",
                    "시장",
                    "규제",
                    "암호화폐",
                    "비트코인",
                    "이더리움",
                    "거래소",
                    "연준",
                    "인플레이션",
                    "미국",
                    "한국",
                    "관세",
                    "지정학",
                    "기업 실적",
                    "고용",
                    "보안",
                    "금융",
                    "AI·",
                    "반도체",
                    "원유",
                    "귀금속",
                    "부동산",
                    "배당",
                    "디지털",
                    "2차전지",
                    "외국인",
                    "중국",
                    "일본",
                    "유럽",
                )
            )
        ):
            ko_desc = translate_to_korean(desc)
            if ko_desc != desc:
                item["description_ko"] = ko_desc

    save_translation_cache()
