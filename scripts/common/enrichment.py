"""Shared URL content enrichment for news collectors.

Provides functions to fetch meta descriptions from URLs and generate
synthetic descriptions when actual content is unavailable.
"""

import ipaddress
import logging
import re
import socket
from difflib import SequenceMatcher
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import requests

from .config import get_verify_ssl
from .markdown_utils import smart_truncate

logger = logging.getLogger(__name__)

# Cache for resolved Google News URLs to avoid redundant lookups
_gnews_url_cache: Dict[str, str] = {}

# Pre-compiled regex for text normalization (used in duplicate detection)
_NORM_RE = re.compile(r"[\s\W]+")

# Site-level boilerplate patterns — descriptions that describe the site, not the article
_SITE_BOILERPLATE_PATTERNS = [
    # English patterns: site self-descriptions
    re.compile(r"(?:the )?(?:world'?s?|global) (?:leading|largest|premier|#1)\b", re.I),
    re.compile(r"(?:join|subscribe to|sign up for) (?:the )?(?:world'?s|our)\b", re.I),
    re.compile(
        r"(?:providing|delivers?|offers?) .{0,40}(?:news|analysis|insights|information)"
        r" .{0,40}(?:since|for over|for \d+)",
        re.I,
    ),
    re.compile(r"^(?:the )?(?:latest|breaking|live|real-time) (?:news|updates?|prices?)\b", re.I),
    # Korean patterns: translated site descriptions
    re.compile(r"(?:세계 최대|글로벌 리더|세계적인 리더)", re.I),
    re.compile(r"(?:에 참여하세요|구독하세요|가입하세요)$", re.I),
    re.compile(r"\d+년 (?:넘게|이상) .{0,40}(?:제공|서비스)", re.I),
]

# Known site boilerplate phrases (case-insensitive substring match)
_SITE_BOILERPLATE_PHRASES = [
    "motley fool",
    "seeking alpha",
    "cnbc international",
    "investopedia",
    "yahoo finance",
    "bloomberg",
    "coindesk is",
    "cointelegraph is",
    "decrypt is",
    "뉴스의 리더입니다",
    "뉴스를 제공하는",
    "투자 통찰력과 개인 금융",
    "투자 커뮤니티",
    "프리미엄 뉴스를 제공",
]

# Regex to detect at least one article-specific token (proper noun, number, date)
# NOTE: Intentionally avoids matching generic Korean phrases to prevent false negatives.
_ARTICLE_SPECIFIC_RE = re.compile(
    r"(?:[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)"  # Two+ consecutive title-case words (proper noun)
    r"|(?:\b[A-Z]{2,}\b)"                   # Acronym / ticker (SEC, ETF, BTC, XRP, etc.)
    r"|(?:\b\d{4}\b)"                        # 4-digit year
    r"|(?:\b\d+[\.,]\d+)"                    # Number with decimal/comma (e.g. price, %)
    r"|(?:\$|€|£|₩|¥)\s*\d"                 # Currency + digit
    r"|(?:\d+\s*(?:%|억|만|조|달러|원|위안))"  # Number with unit
    r"|(?:월|년|일)\s*\d"                     # Korean date fragments
)


def _is_site_boilerplate(desc: str) -> bool:
    """Return True if description appears to be a site-level description, not article content.

    Checks against known boilerplate phrases, regex patterns for site self-descriptions,
    and short generic descriptions lacking article-specific tokens.
    """
    if not desc:
        return False

    lower = desc.lower()

    # 1. Known site boilerplate phrases
    for phrase in _SITE_BOILERPLATE_PHRASES:
        if phrase.lower() in lower:
            logger.debug("Boilerplate phrase matched (%r): %r", phrase, desc[:80])
            return True

    # 2. Regex patterns for site self-descriptions
    for pattern in _SITE_BOILERPLATE_PATTERNS:
        if pattern.search(desc):
            logger.debug("Boilerplate pattern matched: %r", desc[:80])
            return True

    # 3. Very short descriptions without any article-specific tokens
    # Threshold kept low (35) to catch pure site taglines ("전 세계 시장에 대한 뉴스 및 분석.")
    # while preserving medium-length Korean sentences that lack numbers/acronyms.
    if len(desc) < 35 and not _ARTICLE_SPECIFIC_RE.search(desc):
        logger.debug("Short generic description (no specific tokens): %r", desc[:80])
        return True

    return False


# Module-level synthetic markers for consistent detection across functions
_SYNTHETIC_MARKERS = [
    "관련 소식입니다",
    "관련 시장 뉴스입니다",
    "원문에서 세부 내용을 확인하세요",
    "원문 기사의 세부 내용을 확인하세요",
    "투자 판단 시",
    "면밀히 분석해야 합니다",
    "함께 고려해야 합니다",
    "주시해야 합니다",
    "확인하세요",
    "관련 시장 동향입니다",
    "관련 세부 내용은",
    "관련 변경사항을",
    "시장 심리와 가격",
    "투자 시사점을",
    "거래소 공지사항",
    "산업 동향",
    "관련 보도.",
    "섹터 보도.",
    "산업 보도.",
    "시장 보도.",
]


def is_private_url(url: str) -> bool:
    """Check if URL resolves to a private/internal IP address."""
    try:
        hostname = urlparse(url).hostname
        if not hostname:
            return True
        ip = socket.gethostbyname(hostname)
        return ipaddress.ip_address(ip).is_private
    except Exception:
        return True  # Block on resolution failure


VERIFY_SSL = get_verify_ssl()

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


def _clean_meta_description(text: str) -> str:
    """Clean extracted meta description text for quality."""
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
    # Final boilerplate guard — reject site-level descriptions
    if _is_site_boilerplate(text):
        return ""
    return text


def _decode_google_news_base64(url: str) -> str:
    """Try to extract the actual article URL from a Google News RSS URL.

    Google News RSS URLs like ``https://news.google.com/rss/articles/CBMi...``
    contain a base64-encoded payload that wraps the real article URL.
    """
    import base64
    import urllib.parse

    try:
        # Extract the base64 segment after /articles/ or /read/
        match = re.search(r"(?:/rss/articles/|/read/)([A-Za-z0-9_-]+)", url)
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
    1. Return cached result if available.
    2. Try base64 decoding of the RSS article path (fastest, no network).
    3. Follow HTTP redirects with ``requests.head`` (max 3 hops) then ``requests.get``.
    4. Parse HTML for canonical/og:url if still on Google domain.

    Handles both ``/rss/articles/CBMi...`` and ``/read/CBMi...`` URL formats.
    """
    if not url or "news.google.com" not in url:
        return url

    # Check cache first
    if url in _gnews_url_cache:
        return _gnews_url_cache[url]

    resolved = _resolve_google_news_url_inner(url, timeout)
    _gnews_url_cache[url] = resolved
    return resolved


def _resolve_google_news_url_inner(url: str, timeout: int = 8) -> str:
    """Inner implementation for Google News URL resolution (uncached)."""
    # 1. Try base64 decoding (no network call needed)
    decoded = _decode_google_news_base64(url)
    if decoded:
        logger.debug("Google News base64 decoded: %s -> %s", url[:60], decoded[:80])
        return decoded

    # Normalize /read/ URLs to /rss/articles/ and retry base64
    if "/read/" in url:
        rss_url = url.replace("/read/", "/rss/articles/")
        decoded = _decode_google_news_base64(rss_url)
        if decoded:
            logger.debug("Google News /read/ base64 decoded: %s -> %s", url[:60], decoded[:80])
            return decoded

    # 2. Try googlenewsdecoder (handles newer protobuf-encoded URLs)
    resolved = _resolve_via_gnewsdecoder(url)
    if resolved:
        return resolved

    # 3. Follow HTTP redirects via HEAD (max 3 hops)
    try:
        if is_private_url(url):
            logger.warning("SSRF blocked: %s resolves to private IP", url[:80])
            return ""
        head_resp = requests.head(
            url,
            timeout=timeout,
            allow_redirects=True,
            headers={"User-Agent": _BROWSER_UA},
            verify=VERIFY_SSL,
        )
        final_url = head_resp.url or ""
        if final_url and "news.google.com" not in final_url:
            if is_private_url(final_url):
                logger.warning("SSRF blocked (redirect): %s -> %s", url[:60], final_url[:80])
                return ""
            logger.debug("Google News HEAD redirect: %s -> %s", url[:60], final_url[:80])
            return final_url
        # Check intermediate redirect hops (up to 3)
        if hasattr(head_resp, "history") and head_resp.history:
            for hop in head_resp.history[-3:]:
                hop_loc = hop.headers.get("Location", "")
                if hop_loc and "news.google.com" not in hop_loc and hop_loc.startswith("http"):
                    if not is_private_url(hop_loc):
                        logger.debug("Google News hop redirect: %s -> %s", url[:60], hop_loc[:80])
                        return hop_loc
    except requests.exceptions.RequestException:
        pass

    # 4. Full GET and parse HTML for canonical/og:url
    try:
        if is_private_url(url):
            logger.warning("SSRF blocked: %s resolves to private IP", url[:80])
            return ""
        resp = requests.get(
            url,
            timeout=timeout,
            allow_redirects=True,
            headers={"User-Agent": _BROWSER_UA},
            verify=VERIFY_SSL,
        )
        if resp.url and "news.google.com" not in resp.url:
            if is_private_url(resp.url):
                logger.warning("SSRF blocked (redirect): %s -> %s", url[:60], resp.url[:80])
                return ""
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


def _resolve_via_gnewsdecoder(url: str) -> str:
    """Resolve Google News URL using googlenewsdecoder library.

    This handles the newer protobuf-encoded URLs (2024+) that cannot be
    decoded via simple base64. Falls back gracefully if the library is
    unavailable or decoding fails.
    """
    try:
        from googlenewsdecoder import gnewsdecoder

        result = gnewsdecoder(url)
        if result and result.get("status") and result.get("decoded_url"):
            decoded_url = result["decoded_url"]
            if is_private_url(decoded_url):
                logger.warning("SSRF blocked (gnewsdecoder): %s -> %s", url[:60], decoded_url[:80])
                return ""
            logger.debug("Google News gnewsdecoder: %s -> %s", url[:60], decoded_url[:80])
            return decoded_url
    except ImportError:
        logger.debug("googlenewsdecoder not installed, skipping")
    except Exception as exc:  # noqa: BLE001
        logger.debug("gnewsdecoder failed for %s: %s", url[:60], exc)
    return ""


_BROWSER_UA = _USER_AGENT


def _is_valid_image_url(url: str) -> bool:
    """Check if a URL is likely a valid, useful image (not a placeholder/tracking pixel)."""
    if not url or not url.startswith("http"):
        return False
    url_lower = url.lower()
    # Reject known tracking pixels and placeholder images
    _BAD_PATTERNS = [
        "1x1",
        "pixel",
        "tracker",
        "beacon",
        "spacer",
        "placeholder",
        "default-image",
        "no-image",
        "blank.",
        "gravatar.com/avatar",
        "wp-content/plugins",
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

        if is_private_url(url):
            logger.warning("SSRF blocked: %s resolves to private IP", url[:80])
            return ""
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
        # Prefer original_url (pre-resolved from RSS <source url="">) over Google News URL
        original_url = item.get("original_url", "")
        if original_url and "news.google.com" not in original_url:
            link = original_url
        elif "news.google.com" in link:
            link = _resolve_google_news_url(link)
        if not link:
            return idx, ""
        return idx, _fetch_og_image(link)

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_fetch_one, idx, item): idx for idx, item in targets}
        for future in as_completed(futures):
            item_idx = futures[future]
            try:
                idx, img_url = future.result(timeout=15)
                if img_url:
                    items[idx]["image"] = img_url
                    fetched += 1
            except Exception as exc:
                logger.debug("Image fetch failed for item %d: %s", item_idx, exc)

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

    def _needs_enrichment(item: dict) -> bool:
        # Check _synthetic flag first (primary signal)
        if item.get("_synthetic"):
            return True
        desc = item.get("description", "").strip()
        if not desc or len(desc) < 30:
            return True
        if _is_desc_duplicate_of_title(desc, item.get("title", "")):
            return True
        # Fallback: marker-based detection for backward compatibility
        return any(marker in desc for marker in _SYNTHETIC_MARKERS)

    targets = [(i, item) for i, item in enumerate(items) if _needs_enrichment(item) and item.get("link")][:max_items]

    if not targets:
        return 0

    fetched = 0

    def _fetch_one(idx: int, item: dict) -> tuple:
        link = item.get("link", "")
        # Prefer original_url (pre-resolved from RSS <source url="">) over Google News URL
        original_url = item.get("original_url", "")
        if original_url and "news.google.com" not in original_url:
            link = original_url
        elif "news.google.com" in link:
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
                if desc and len(desc) > 30 and not _is_desc_duplicate_of_title(desc, items[idx].get("title", "")):
                    items[idx]["description"] = desc
                    items[idx].pop("_synthetic", None)
                    fetched += 1
            except Exception as exc:
                logger.debug("Description fetch failed for item %d: %s", futures[future], exc)

    if fetched:
        logger.info("Concurrent description fetch: enriched %d/%d items", fetched, len(targets))
    return fetched


_EXCLUDE_CLASS_RE = re.compile(
    r"sidebar|widget|nav|menu|footer|header|comment|social|share|promo|"
    r"ad-|ads-|advert|sponsor|related|recommend|popup|modal|cookie|banner",
    re.I,
)


def _extract_og_metadata(soup: Any) -> Dict[str, str]:
    """Extract Open Graph / twitter meta tags from a parsed page.

    Returns a dict with ``image`` (may be empty) and ``description`` (may be empty).
    """
    from bs4 import BeautifulSoup as BS4  # noqa: F401 – type hint only

    result: Dict[str, str] = {"description": "", "image": ""}

    # og:image / twitter:image
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

    # meta description / og:description / twitter:description
    # Prioritize og:description (most reliable), then standard description,
    # then twitter:description. Korean news sites often use og:description
    # and/or <meta name="description"> with good article summaries.
    for attr_key, attr_val in [
        ("property", "og:description"),
        ("name", "description"),
        ("name", "twitter:description"),
        ("property", "twitter:description"),
    ]:
        meta = soup.find("meta", attrs={attr_key: attr_val})
        content = str(meta.get("content", "")) if meta else ""
        cleaned = _clean_meta_description(content)
        if cleaned and len(cleaned) > 20 and not _is_site_boilerplate(cleaned):
            result["description"] = smart_truncate(cleaned, 1000)
            break

    return result


def _extract_via_readability(html: str, url: str) -> str:
    """Extract article text using readability-lxml (best quality).

    Returns a non-empty description string on success, or empty string if
    readability is not installed or extraction fails.
    """
    from bs4 import BeautifulSoup as BS4

    try:
        from readability import Document

        doc = Document(html)
        summary_html = doc.summary()
        summary_soup = BS4(summary_html, "html.parser")
        paragraphs = []
        for p in summary_soup.find_all("p"):
            text = _clean_meta_description(p.get_text(strip=True))
            if len(text) > 50:
                paragraphs.append(text)
            if len(paragraphs) >= 5:
                break
        if paragraphs:
            return smart_truncate(" ".join(paragraphs), 1000)
    except ImportError:
        pass  # readability-lxml not installed, fall through
    except Exception as exc:  # noqa: BLE001
        logger.debug("readability extraction failed for %s: %s", url, exc)
    return ""


def _extract_via_bs4_article(soup: Any) -> str:
    """Extract article text from BeautifulSoup <article> or article-class containers.

    Returns a non-empty description string on success, or empty string if no
    suitable article container is found.
    """
    article = soup.find("article")
    if not article:
        for tag in soup.find_all(
            class_=re.compile(
                r"article[-_]?(body|content|text)|post[-_]?(body|content|text)|entry[-_]?(body|content|text)"
            )
        ):
            if not _EXCLUDE_CLASS_RE.search(str(tag.get("class", ""))):
                article = tag
                break
    if not article:
        for tag in soup.find_all(class_=re.compile(r"^(article|post|entry|content)$")):
            if not _EXCLUDE_CLASS_RE.search(str(tag.get("class", ""))):
                article = tag
                break
    if not article:
        return ""

    for noise in article.find_all(class_=_EXCLUDE_CLASS_RE):
        noise.decompose()
    paragraphs = []
    for p in article.find_all("p"):
        text = _clean_meta_description(p.get_text(strip=True))
        if len(text) > 50:
            paragraphs.append(text)
        if len(paragraphs) >= 5:
            break
    if paragraphs:
        return smart_truncate(" ".join(paragraphs), 1000)
    return ""


def _extract_via_paragraphs(soup: Any) -> str:
    """Fallback: extract the first substantial <p> not inside a noise container.

    Returns a non-empty description string on success, or empty string if none found.
    """
    for p in soup.find_all("p"):
        if p.find_parent(class_=_EXCLUDE_CLASS_RE):
            continue
        text = _clean_meta_description(p.get_text(strip=True))
        if len(text) > 50:
            return smart_truncate(text, 1000)
    return ""


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

        if is_private_url(url):
            logger.warning("SSRF blocked: %s resolves to private IP", url[:80])
            return result
        resp = requests.get(
            url,
            timeout=timeout,
            headers={"User-Agent": _USER_AGENT},
            verify=VERIFY_SSL,
        )
        resp.raise_for_status()
        soup = BS4(resp.text, "html.parser")

        # Extract OG metadata (image + meta description tags)
        og = _extract_og_metadata(soup)
        result["image"] = og["image"]
        if og["description"]:
            result["description"] = og["description"]
            return result

        # Try readability-lxml for high-quality article extraction
        desc = _extract_via_readability(resp.text, url)
        if desc:
            result["description"] = desc
            return result

        # Article body paragraphs (BS4 fallback)
        desc = _extract_via_bs4_article(soup)
        if desc:
            result["description"] = desc
            return result

        # Last resort: any substantial <p> not in noise containers
        desc = _extract_via_paragraphs(soup)
        if desc:
            result["description"] = desc
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


# ---------------------------------------------------------------------------
# Entity extraction constants
# ---------------------------------------------------------------------------

# Common English words that should not be treated as proper-noun entities
_COMMON_WORDS = {
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

# Uppercase sequences that look like tickers but are not meaningful financial symbols
_NOISE_TICKER_SYMBOLS = {
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


def _extract_raw_patterns(title: str) -> tuple:
    """Run regex extractions on title and return (tickers, values, proper, kr_entities)."""
    tickers = re.findall(r"\b[A-Z]{2,5}\b", title)
    values = re.findall(r"\$[\d,.]+[KkMmBbTt]?|\d+(?:\.\d+)?%", title)
    kr_entities = re.findall(r"[가-힣]{2,}", title)
    proper = re.findall(r"\b[A-Z][a-z]{2,}\b", title)
    return tickers, values, proper, kr_entities


def _filter_entities(tickers: list, proper: list) -> tuple:
    """Filter noise from ticker and proper-noun lists."""
    clean_tickers = [t for t in tickers if t not in _NOISE_TICKER_SYMBOLS]
    clean_proper = [w for w in proper if w not in _COMMON_WORDS]
    return clean_tickers, clean_proper


def _dedup_entities(entities: list) -> list:
    """Deduplicate entity list while preserving insertion order (case-insensitive)."""
    seen: set = set()
    deduped = []
    for e in entities:
        if e.lower() not in seen:
            seen.add(e.lower())
            deduped.append(e)
    return deduped


def _extract_title_entities(title: str) -> list:
    """Extract meaningful entities (names, tickers, numbers) from title."""
    tickers, values, proper, kr_entities = _extract_raw_patterns(title)
    tickers, proper = _filter_entities(tickers, proper)

    entities: list = []
    entities.extend(values)
    entities.extend(tickers[:2])
    entities.extend(proper[:2])
    entities.extend(kr_entities[:3])
    return _dedup_entities(entities)


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


# ---------------------------------------------------------------------------
# Keyword -> fixed description mapping for Korean title analysis.
# Each entry is (keywords, description_string). Categories that require
# dynamic content (pct extraction, clean title) are handled inline below.
# ---------------------------------------------------------------------------
_KOREAN_TITLE_CATEGORIES: Dict[str, str] = {
    # Surge / rebound
    "급등|폭등|반등": "시장 반등 관련 보도.",
    # Geopolitical risk
    "전쟁|분쟁|군사|이란|중동": "지정학적 리스크 관련 보도.",
    # Monetary policy
    "금리|금통위|한은|한국은행": "한국은행 통화정책 관련 보도.",
    # FX
    "환율|원달러|원화": "환율 변동 관련 보도.",
    # Market fraud / delisting
    "상장폐지|주가조작|불공정거래": "불공정거래 관련 보도.",
    # Market rules
    "거래시간|제도|규정": "증시 제도 변경 관련 보도.",
    # Valuation bubble
    "버블|과열|밸류에이션": "시장 밸류에이션 관련 보도.",
    # Bio / pharma
    "바이오|제약": "바이오·제약 섹터 관련 보도.",
    # IPO / listing
    "IPO|공모|상장": "IPO·신규 상장 관련 보도.",
    # Oil / energy
    "유가|원유|석유": "유가 변동 관련 보도.",
    # Trade / tariffs
    "관세|무역|수출|수입": "통상·무역 정책 관련 보도.",
    # Dividends / buybacks
    "배당|주주환원|자사주": "배당·주주환원 정책 관련 보도.",
    # Real estate
    "부동산|아파트|전세|분양": "부동산 시장 관련 보도.",
    # M&A
    "인수|합병|M&A": "기업 인수·합병(M&A) 관련 보도.",
}

# Pre-compiled keyword sets derived from _KOREAN_TITLE_CATEGORIES for O(1) lookup
_KOREAN_TITLE_KW_SETS: list = [(frozenset(k.split("|")), v) for k, v in _KOREAN_TITLE_CATEGORIES.items()]


def _analyze_korean_title(title: str) -> str:
    """Analyze a Korean news title and generate a fact-based description.

    Produces clean, factual descriptions based on the title content
    rather than speculative or template-heavy commentary.
    """
    clean = re.sub(r"\s*[-–—|]\s*\S+$", "", title).strip()
    pct = re.search(r"(\d+(?:\.\d+)?)\s*%", title)
    amount = re.search(r"(\d[\d,.]*)\s*(?:억|조|만|원|달러)", title)
    kr_entities = re.findall(r"[가-힣]{2,}", title)[:3]

    # Build context suffix from extracted data
    context_parts = []
    if pct:
        context_parts.append(f"{pct.group(1)}% 변동")
    if amount:
        context_parts.append(f"{amount.group(0)}")
    context_suffix = f" ({', '.join(context_parts)})" if context_parts else ""

    # Circuit breaker / market crash
    if any(kw in title for kw in ["서킷브레이커", "사이드카"]):
        trigger = "매수 사이드카" if "매수" in title else "서킷브레이커/사이드카"
        return f"{clean[:120]}. {trigger} 발동{context_suffix}."

    # Crash / panic
    if any(kw in title for kw in ["폭락", "급락", "패닉"]):
        return f"{clean[:120]}.{context_suffix} 급락 관련 보도."

    # Semiconductor
    if any(kw in title for kw in ["삼성전자", "하이닉스", "반도체"]):
        return f"{clean[:120]}.{context_suffix} 반도체 섹터 보도."

    # Fixed-response categories via dict table
    for kw_set, category_label in _KOREAN_TITLE_KW_SETS:
        if any(kw in title for kw in kw_set):
            return f"{clean[:120]}.{context_suffix} {category_label}"

    # Crypto majors
    if any(kw in title for kw in ["비트코인", "이더리움", "알트코인", "리플"]):
        return f"{clean[:120]}.{context_suffix} 암호화폐 시장 보도."

    # DeFi / digital assets
    if any(kw in title for kw in ["디파이", "디지털자산", "가상자산", "코인", "블록체인"]):
        return f"{clean[:120]}.{context_suffix} 디지털 자산 보도."

    # AI / tech
    if any(kw in title for kw in ["AI", "인공지능", "챗봇", "생성형"]):
        return f"{clean[:120]}.{context_suffix} AI 산업 보도."

    # EV / battery
    if any(kw in title for kw in ["2차전지", "배터리", "전기차", "EV"]):
        return f"{clean[:120]}.{context_suffix} 전기차·배터리 보도."

    # Foreign / institutional flow
    if any(kw in title for kw in ["외국인", "기관", "순매수", "순매도", "수급"]):
        return f"{clean[:120]}.{context_suffix} 수급 동향 보도."

    # Earnings
    if any(kw in title for kw in ["실적", "어닝", "매출", "영업이익"]):
        return f"{clean[:120]}.{context_suffix} 기업 실적 보도."

    # Fallback: use clean title + entity context
    if kr_entities:
        entity_str = ", ".join(kr_entities[:3])
        return f"{clean[:120]}.{context_suffix} 주요 키워드: {entity_str}."
    return clean[:150] if len(clean) > 15 else title


# ---------------------------------------------------------------------------
# Keyword -> fixed suffix mapping for English title analysis.
# Each entry is (keywords, suffix_string). Categories that require dynamic
# content (detail_str injection, extra logic) are handled inline in the
# function body below.
# ---------------------------------------------------------------------------
_ENGLISH_TITLE_CATEGORIES: Dict[str, str] = {
    # Geopolitical risk
    "iran|war|conflict|military|attack": "지정학 관련 보도.",
    # Earnings
    "earning|revenue|profit|guidance|beat|miss": "기업 실적 관련 보도.",
    # Fed / monetary policy
    "fed|fomc|powell|rate cut|rate hike": "연준 통화정책 관련 보도.",
    # Trump / policy
    "trump|white house|executive order|tariff": "정책 관련 보도.",
    # Crypto majors — no suffix (title alone)
    "bitcoin|btc|crypto|ethereum|altcoin": "",
    # AI / semiconductors — no suffix (title alone)
    "ai |artificial intelligence|nvidia|semiconductor|chip": "",
    # Precious metals — no suffix (title alone)
    "gold|silver|precious": "",
}

# Pre-compiled keyword sets derived from _ENGLISH_TITLE_CATEGORIES for O(1) lookup
_ENGLISH_TITLE_KW_SETS: list = [(frozenset(k.split("|")), v) for k, v in _ENGLISH_TITLE_CATEGORIES.items()]


def _analyze_english_title(title: str, title_lower: str) -> str:
    """Analyze an English news title and generate a specific Korean description."""
    _subj = _extract_title_entities(title)
    # Use only named entities (not raw numbers/prices) for the subject prefix
    _named = [e for e in _subj if not re.match(r"^[\d$,.%+\-]+$", e)]

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

    # Build extra context from extracted numbers
    extra = f" ({detail_str})" if detail_str else ""

    # --- Dynamic categories: inject detail_str into result ---
    if any(kw in title_lower for kw in ["crash", "plunge", "tumble", "sink", "slump", "dive"]):
        return f"{clean_title[:120]}.{extra} 급락 관련 보도."

    if any(kw in title_lower for kw in ["rally", "surge", "soar", "jump", "climb", "gain"]):
        return f"{clean_title[:120]}.{extra} 상승 관련 보도."

    if any(kw in title_lower for kw in ["drop", "fall ", "decline", "down ", "lower", "slip"]):
        return f"{clean_title[:120]}.{extra}"

    if any(kw in title_lower for kw in ["rise", "up ", "higher", "advance"]):
        return f"{clean_title[:120]}.{extra}"

    if any(kw in title_lower for kw in ["oil", "crude", "brent", "wti"]):
        return f"{clean_title[:120]}.{extra} 유가 관련 보도."

    if any(kw in title_lower for kw in ["s&p", "nasdaq", "dow", "futures", "stock market"]):
        return f"{clean_title[:120]}.{extra}"

    # --- Fixed-suffix categories via dict table ---
    for kw_set, suffix in _ENGLISH_TITLE_KW_SETS:
        if any(kw in title_lower for kw in kw_set):
            return f"{clean_title[:120]}.{extra}" if not suffix else f"{clean_title[:120]}.{extra} {suffix}"

    # Default: use cleaned title with entity context
    _meaningful = [e for e in _named if len(e) > 2]
    if _meaningful:
        subj = ", ".join(_meaningful[:2])
        return f"{clean_title[:120]}.{extra} {subj} 관련 보도."
    if detail_str:
        return f"{clean_title[:120]}.{extra}"
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
        return f"{label} 공지. " + (f"{entity_str} 관련." if entity_str else f"{title[:80]}.")

    # Build a title-condensed description instead of boilerplate
    # Clean trailing source names from the title
    clean_title = re.sub(r"\s*[-–—|]\s*\S+$", "", title).strip()
    # For Korean titles, extract a condensed version
    kr_chars = len(re.findall(r"[가-힣]", clean_title))
    if kr_chars > len(clean_title) * 0.3:
        core = clean_title[:80] if len(clean_title) > 80 else clean_title
        if entity_str:
            return f"{core}. {entity_str} 관련 보도."
        return f"{core}."

    # English: use cleaned title with source context
    if label and label != source:
        return f"{label} 보도. {clean_title[:100]}"
    return clean_title[:150] if len(clean_title) > 15 else title


def _fetch_and_parse_page(url: str) -> Dict[str, str]:
    """Fetch a URL and return parsed metadata (description + image).

    Thin wrapper around :func:`fetch_page_metadata` that isolates the
    HTTP fetch + HTML parsing step for use inside :func:`enrich_item`.
    """
    return fetch_page_metadata(url)


def _clean_html_content(text: str) -> str:
    """Clean HTML entities and normalize whitespace in a fetched description."""
    text = re.sub(r"&#?\w+;", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _is_desc_duplicate_of_title(desc: str, title: str) -> bool:
    """Return True if desc is essentially a duplicate of title (no extra info).

    Checks:
    - Normalized text equality (lowercase, stripped punctuation/whitespace)
    - desc contains >= 80% of title characters
    - desc length < 1.3x title length (insufficient additional info)
    - Word-token Jaccard similarity > 0.7
    """
    if not desc or not title:
        return False

    # Normalize: lowercase, remove punctuation and whitespace
    norm_desc = _NORM_RE.sub("", desc.lower())
    norm_title = _NORM_RE.sub("", title.lower())

    # Exact normalized match
    if norm_desc == norm_title:
        return True

    # Sequence-based similarity: catches near-duplicates without false positives
    # from bag-of-characters approach
    if norm_title and len(norm_title) > 5:
        ratio = SequenceMatcher(None, norm_desc, norm_title).ratio()
        if ratio > 0.8 and len(norm_desc) < len(norm_title) * 1.3:
            return True

    # Word-token Jaccard similarity (skip for very short titles to avoid noise)
    desc_tokens = set(desc.lower().split())
    title_tokens = set(title.lower().split())
    union = desc_tokens | title_tokens
    if len(union) >= 4:
        intersection = desc_tokens & title_tokens
        if len(intersection) / len(union) > 0.7:
            return True

    return False


def _generate_synthetic_description(
    item: Dict[str, Any],
    context_map: Optional[Dict[str, str]],
) -> str:
    """Generate a synthetic description for an item from its title and source.

    Delegates to :func:`generate_synthetic_description` using the item's
    ``title`` and ``source`` fields.
    """
    title = item.get("title", "")
    source = item.get("source", "")
    return generate_synthetic_description(title, source, context_map)


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
    link = item.get("link", "")

    # Check if existing description is actually good
    if desc and len(desc) > 20:
        # Reject if desc is just title with source appended (RSS artifact)
        # e.g. "Article Title Here sourcename.com"
        if _is_desc_duplicate_of_title(desc, title):
            pass  # fall through to enrichment
        elif title and desc.startswith(title[:30]):
            pass  # description is title prefix + noise
        elif any(p.search(desc) for p in _NOISE_DESC_PATTERNS):
            pass  # noise content (JS required, etc.)
        else:
            return  # already has a good description

    # Try fetching from URL (including Google News URLs via resolution)
    # Prefer original_url if available (pre-resolved from RSS <source url="">)
    original_url = item.get("original_url", "")
    fetch_link = link
    if original_url and "news.google.com" not in original_url:
        fetch_link = original_url
    if fetch_url and fetch_link:
        counter = _fetch_counter or [0]
        if counter[0] < max_fetch:
            counter[0] += 1
            metadata = _fetch_and_parse_page(fetch_link)
            fetched = metadata.get("description", "")
            if fetched and fetched != title and len(fetched) > 20:
                item["description"] = _clean_html_content(fetched)
                item.pop("_synthetic", None)
            # Extract og:image if not already set from RSS
            if not item.get("image") and metadata.get("image"):
                item["image"] = metadata["image"]
            if item.get("description") and len(item["description"]) > 20 and not item.get("_synthetic"):
                return

    # Generate synthetic description
    item["description"] = _generate_synthetic_description(item, context_map)
    item["_synthetic"] = True


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
