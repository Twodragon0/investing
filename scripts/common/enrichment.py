"""Shared URL content enrichment for news collectors.

Provides functions to fetch meta descriptions from URLs and generate
synthetic descriptions when actual content is unavailable.
"""

import logging
import re
from typing import Any, Dict, Optional

import requests

from . import summary_quality as _summary_quality_mod
from .config import get_verify_ssl
from .encoding_guard import force_utf8_if_mislabelled, sanitize_mojibake
from .enrichment_images import (  # noqa: F401  (re-exported for backward compat)
    _is_valid_image_url,
    is_logo_like_url,
    match_bad_image_pattern,
    match_logo_pattern,
)
from .enrichment_synthetic import (  # noqa: F401  (re-exported for backward compat)
    _CRYPTO_SOURCE_CONTEXT,
    _POLITICAL_SOURCE_CONTEXT,
    _SOCIAL_SOURCE_CONTEXT,
    _STOCK_SOURCE_CONTEXT,
    _WORLDMONITOR_SOURCE_CONTEXT,
    _analyze_english_title,
    _analyze_korean_title,
    _analyze_title_content,
    _dedup_entities,
    _extract_overlap_keywords,
    _extract_raw_patterns,
    _extract_title_entities,
    _filter_entities,
    _get_source_label,
    _is_desc_duplicate_of_title,
    _is_title_related_description,
    generate_synthetic_description,
)
from .markdown_utils import smart_truncate
from .summary_quality import _is_site_boilerplate  # noqa: F401  (re-exported for backward compat)
from .utils import is_private_url_target

logger = logging.getLogger(__name__)

# readability-lxml is a declared dependency (requirements.txt); its absence is
# an environment regression that silently drops the best-quality extraction
# path. Warn once per process so the degradation is visible without flooding
# the per-URL enrichment loop.
_warned_readability_missing = False

# Public API — names documented for import by collectors and renderers.
# Names prefixed with _ remain internal helpers (shared via explicit import only).
__all__ = [
    "MAX_IMAGES_PER_DIGEST",
    "enrich_item",
    "enrich_items",
    "fetch_descriptions_concurrent",
    "fetch_images_concurrent",
    "fetch_page_description",
    "fetch_page_metadata",
    "generate_synthetic_description",
    "is_logo_like_url",
    "is_private_url",
    "match_bad_image_pattern",
    "match_logo_pattern",
]

# Maximum og:image fetch count per enrich_items call.
# Digest size is typically top (~100) + overflow (~50) ≈ 150 items; 120 covers the bulk.
MAX_IMAGES_PER_DIGEST = 120

# Cache for resolved Google News URLs to avoid redundant lookups
_gnews_url_cache: Dict[str, str] = {}

# Site-level boilerplate detection (``_is_site_boilerplate`` + its patterns)
# now lives in ``common.summary_quality`` and is re-exported at the top of this
# module for backward compatibility. Article-specific token detection likewise
# lives in ``summary_quality.ARTICLE_SPECIFIC_RE`` (accessed via
# ``_summary_quality_mod.ARTICLE_SPECIFIC_RE``); do not redefine either here.


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


# Synthetic Korean category suffix appended by _analyze_*_title — it always
# ends in "...보도." (관련 보도 / 섹터 보도 / 시장 보도 / 산업 보도 / 자산 보도).
# When such a suffix rides on an English-dominant synthetic description, the
# downstream translation pass would re-translate the whole string and Google
# Translate mutates "보도" → 통보/알림/공지/안내/보상/경고. We split the suffix
# off, translate only the English body, then reattach the suffix verbatim.
_SYNTHETIC_KO_SUFFIX_RE = re.compile(r"\s+[가-힣][가-힣A-Za-z0-9·\s]*보도\.\s*$")


def _split_synthetic_ko_suffix(desc: str) -> tuple:
    """Split a synthetic description into ``(english_body, korean_suffix)``.

    Returns ``(desc, "")`` when no trailing "...보도." category suffix exists.
    """
    m = _SYNTHETIC_KO_SUFFIX_RE.search(desc)
    if m:
        return desc[: m.start()], m.group(0)
    return desc, ""


def is_private_url(url: str) -> bool:
    """Check if URL points to an obvious private/internal target."""
    return is_private_url_target(url)


_VERIFY_SSL: Optional[object] = None


def _get_verify_ssl():
    global _VERIFY_SSL
    if _VERIFY_SSL is None:
        _VERIFY_SSL = get_verify_ssl()
    return _VERIFY_SSL


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

# Boilerplate/legal/syndication snippets often found in low-quality meta tags
_BOILERPLATE_FRAGMENT_PATTERNS = [
    re.compile(r"\ball rights reserved\b", re.I),
    re.compile(r"\bcopyright\b", re.I),
    re.compile(r"\bsyndicat(?:ed|ion)\b", re.I),
    re.compile(r"\bthis material may not be published\b", re.I),
    re.compile(r"\breproduction (?:without|in whole or in part)\b", re.I),
    re.compile(r"\bfor informational purposes only\b", re.I),
    re.compile(r"\bnot investment advice\b", re.I),
    re.compile(r"\bterms of use\b", re.I),
    re.compile(r"\bprivacy policy\b", re.I),
    re.compile(r"무단전재", re.I),
    re.compile(r"재배포", re.I),
    re.compile(r"저작권자", re.I),
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
    # Reject legal/syndication boilerplate fragments
    for pattern in _BOILERPLATE_FRAGMENT_PATTERNS:
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
    if _is_low_information_fragment(text):
        return ""
    return text


def _is_low_information_fragment(desc: str) -> bool:
    """Return True for short, generic, low-information fragments."""
    if not desc:
        return True
    if len(desc) < 25:
        generic_tokens = {"news", "update", "latest", "market", "story", "기사", "속보", "뉴스", "보도"}
        token_count = len(re.findall(r"[A-Za-z]+|[가-힣]+", desc.lower()))
        has_specific = bool(_summary_quality_mod.ARTICLE_SPECIFIC_RE.search(desc))
        has_generic = any(tok in desc.lower() for tok in generic_tokens)
        if token_count <= 6 and (has_generic or not has_specific):
            return True
    return False


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

    # 3. Follow HTTP redirects via HEAD manually (max 5 hops), checking each hop
    try:
        if is_private_url(url):
            logger.warning("SSRF blocked: %s resolves to private IP", url[:80])
            return ""
        current_url = url
        max_hops = 5
        for _hop in range(max_hops):
            head_resp = requests.head(
                current_url,
                timeout=timeout,
                allow_redirects=False,
                headers={"User-Agent": _BROWSER_UA},
                verify=_get_verify_ssl(),
            )
            if head_resp.status_code in (301, 302, 303, 307, 308):
                location = head_resp.headers.get("Location", "")
                if not location:
                    break
                # Resolve relative redirects
                if not location.startswith("http"):
                    from urllib.parse import urljoin

                    location = urljoin(current_url, location)
                if is_private_url(location):
                    logger.warning("SSRF blocked (redirect hop): %s -> %s", current_url[:60], location[:80])
                    return ""
                if "news.google.com" not in location:
                    logger.debug("Google News HEAD redirect: %s -> %s", url[:60], location[:80])
                    return location
                current_url = location
            else:
                # No redirect; use final URL if not on Google domain
                final_url = head_resp.url or current_url
                if final_url and "news.google.com" not in final_url:
                    if is_private_url(final_url):
                        logger.warning("SSRF blocked (redirect): %s -> %s", url[:60], final_url[:80])
                        return ""
                    logger.debug("Google News HEAD resolved: %s -> %s", url[:60], final_url[:80])
                    return final_url
                break
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
            verify=_get_verify_ssl(),
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

# Image URL validation (``match_bad_image_pattern``, ``_is_valid_image_url``,
# ``match_logo_pattern``, ``is_logo_like_url`` + their pattern data) now lives
# in ``common.enrichment_images`` and is re-exported at the top of this module
# for backward compatibility.


# Meta tag patterns for article image extraction, tried in priority order.
# Each entry is (attr_pair, label) — the regex builder below produces both
# content-first and property/name-first variants to handle either attr order.
# Logo-like URLs are rejected so the fallback chain keeps searching for a
# real article image instead of returning a site banner.
_IMAGE_META_PATTERNS = [
    # OpenGraph standard
    (r'property=["\']og:image["\']', "og:image"),
    (r'property=["\']og:image:secure_url["\']', "og:image:secure_url"),
    (r'property=["\']og:image:url["\']', "og:image:url"),
    # Twitter Cards
    (r'name=["\']twitter:image["\']', "twitter:image"),
    (r'name=["\']twitter:image:src["\']', "twitter:image:src"),
    # OpenGraph article namespace (used by some Korean/legacy publishers)
    (r'property=["\']article:image["\']', "article:image"),
    # Schema.org / Microdata
    (r'itemprop=["\']image["\']', "itemprop=image"),
]


def _fetch_og_image(url: str, timeout: int = 8) -> str:
    """Fetch an article image URL from a page's meta tags.

    Searches in priority order: og:image, og:image:secure_url, og:image:url,
    twitter:image, twitter:image:src, article:image, itemprop=image, and
    <link rel="image_src">. Returns the first URL that passes both
    _is_valid_image_url (rejects placeholders/trackers) and is_logo_like_url
    (rejects site logos/favicons). Returns empty string on network failure,
    SSRF block, or when no valid article image is found.
    """
    if not url:
        return ""
    try:
        if is_private_url(url):
            logger.warning("SSRF blocked: %s resolves to private IP", url[:80])
            return ""
        resp = requests.get(
            url,
            timeout=timeout,
            headers={"User-Agent": _BROWSER_UA},
            verify=_get_verify_ssl(),
        )
        resp.raise_for_status()
        force_utf8_if_mislabelled(resp)
        # Search first 60KB — modern sites often have bloated <head> with many
        # script/link tags before the image meta tags.
        head_html = resp.text[:60_000]

        def _accept(img_url: str) -> bool:
            img_url = img_url.strip()
            if not img_url.startswith(("http://", "https://")):
                return False
            if not _is_valid_image_url(img_url):
                return False
            if is_logo_like_url(img_url):
                return False
            return True

        for attr_pattern, _label in _IMAGE_META_PATTERNS:
            # Try both attribute orders (property-first or content-first)
            for regex in (
                rf'<meta[^>]+{attr_pattern}[^>]+content=["\']([^"\']+)',
                rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+{attr_pattern}',
            ):
                match = re.search(regex, head_html, re.IGNORECASE)
                if match and _accept(match.group(1)):
                    return match.group(1).strip()

        # <link rel="image_src" href="..."> — Pinterest/legacy schema
        link_match = re.search(
            r'<link[^>]+rel=["\']image_src["\'][^>]+href=["\']([^"\']+)',
            head_html,
            re.IGNORECASE,
        )
        if link_match and _accept(link_match.group(1)):
            return link_match.group(1).strip()

        # JSON-LD schema.org image (modern publisher pattern)
        for ld_match in re.finditer(
            r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
            head_html,
            re.IGNORECASE | re.DOTALL,
        ):
            ld_text = ld_match.group(1)
            for img_match in re.finditer(
                r'"image"\s*:\s*(?:"([^"]+)"|\{[^{}]*"url"\s*:\s*"([^"]+)")',
                ld_text,
            ):
                candidate = (img_match.group(1) or img_match.group(2) or "").strip()
                if candidate and _accept(candidate):
                    return candidate
    except Exception as exc:
        logger.debug("og:image fetch failed for %s: %s", url, exc)
    return ""


def fetch_images_concurrent(
    items: list,
    max_workers: int = 8,
    max_items: int = 60,
) -> int:
    """Fetch og:image for items missing or carrying a logo image.

    Resolves Google News redirect URLs first, then fetches og:image.
    Prioritizes items that have no image at all (so the first N cards
    on a post never degrade to favicon fallback), then retries items
    whose RSS-provided image is clearly a site logo/icon.
    Returns the number of images successfully fetched or replaced.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    missing: list[tuple[int, dict]] = []
    logo_only: list[tuple[int, dict]] = []
    for i, item in enumerate(items):
        link = item.get("link")
        if not link:
            continue
        img = item.get("image") or ""
        if not img:
            missing.append((i, item))
        elif is_logo_like_url(img):
            logo_only.append((i, item))

    targets = (missing + logo_only)[:max_items]

    if not targets:
        return 0

    fetched = 0
    replaced = 0

    def _fetch_one(idx: int, item: dict) -> tuple:
        link = item["link"]
        original_url = item.get("original_url", "")
        if original_url and "news.google.com" not in original_url:
            link = original_url
        elif "news.google.com" in link:
            link = _resolve_google_news_url(link)
            # Persist resolved URL back to item so favicon rendering and other
            # downstream steps use the publisher's domain instead of news.google.com.
            if link and "news.google.com" not in link:
                item["original_url"] = link
        if not link:
            return idx, ""
        return idx, _fetch_og_image(link)

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_fetch_one, idx, item): idx for idx, item in targets}
        for future in as_completed(futures):
            item_idx = futures[future]
            try:
                idx, img_url = future.result(timeout=15)
                if not img_url:
                    continue
                prev = items[idx].get("image") or ""
                if not prev:
                    items[idx]["image"] = img_url
                    fetched += 1
                elif is_logo_like_url(prev) and not is_logo_like_url(img_url):
                    items[idx]["image"] = img_url
                    replaced += 1
            except Exception as exc:
                logger.debug("Image fetch failed for item %d: %s", item_idx, exc)

    if fetched or replaced:
        logger.info(
            "Fetched %d og:images, replaced %d logo images (%d targets)",
            fetched,
            replaced,
            len(targets),
        )
    return fetched + replaced


def fetch_descriptions_concurrent(
    items: list,
    max_workers: int = 6,
    max_items: int = 80,
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
            if link and "news.google.com" not in link:
                item["original_url"] = link
        if not link:
            return idx, ""
        metadata = fetch_page_metadata(link, title=item.get("title", ""))
        return idx, metadata.get("description", "")

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_fetch_one, idx, item): idx for idx, item in targets}
        for future in as_completed(futures):
            try:
                idx, desc = future.result(timeout=15)
                if (
                    desc
                    and len(desc) > 30
                    and not _is_desc_duplicate_of_title(desc, items[idx].get("title", ""))
                    and _is_title_related_description(items[idx].get("title", ""), desc)
                ):
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


def _extract_og_metadata(soup: Any, title: str = "") -> Dict[str, str]:
    """Extract Open Graph / twitter meta tags from a parsed page.

    Returns a dict with keys: ``image``, ``description``, ``published_time``,
    ``author``, ``section`` (all may be empty). The article:* fields come from
    the OpenGraph article namespace and are useful for downstream consumers
    (RSS metadata, search indexing, description fallback synthesis).
    """
    from bs4 import BeautifulSoup as BS4  # noqa: F401 – type hint only

    result: Dict[str, str] = {
        "description": "",
        "image": "",
        "published_time": "",
        "author": "",
        "section": "",
    }

    # og:image / twitter:image
    for img_attr_key, img_attr_val in [
        ("property", "og:image"),
        ("name", "twitter:image"),
    ]:
        meta = soup.find("meta", attrs={img_attr_key: img_attr_val})
        if meta:
            img_url = str(meta.get("content", "")).strip()
            if _is_valid_image_url(img_url):
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
        if (
            cleaned
            and len(cleaned) > 20
            and not _is_site_boilerplate(cleaned)
            and _is_title_related_description(title, cleaned)
        ):
            result["description"] = smart_truncate(cleaned, 1000)
            break

    # article:published_time — ISO-8601 timestamp (fallback to modified_time)
    for attr_key, attr_val in [
        ("property", "article:published_time"),
        ("property", "article:modified_time"),
        ("name", "pubdate"),
        ("itemprop", "datePublished"),
    ]:
        meta = soup.find("meta", attrs={attr_key: attr_val})
        content = str(meta.get("content", "")).strip() if meta else ""
        if content:
            result["published_time"] = content[:40]
            break

    # article:author — article-level author metadata
    for attr_key, attr_val in [
        ("property", "article:author"),
        ("name", "author"),
        ("itemprop", "author"),
    ]:
        meta = soup.find("meta", attrs={attr_key: attr_val})
        content = str(meta.get("content", "")).strip() if meta else ""
        if content and len(content) < 200:
            result["author"] = content
            break

    # article:section — topic/category
    meta = soup.find("meta", attrs={"property": "article:section"})
    if meta:
        content = str(meta.get("content", "")).strip()
        if content and len(content) < 100:
            result["section"] = content

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
        # Declared dep missing: best-quality extraction disabled, callers fall
        # through to bs4/paragraph extractors. Warn once (parity with
        # text_lang's langdetect fail-open) instead of silently passing.
        global _warned_readability_missing
        if not _warned_readability_missing:
            _warned_readability_missing = True
            logger.warning(
                "readability-lxml not installed; high-quality article extraction "
                "disabled (falling back to bs4/paragraph). Install readability-lxml to restore."
            )
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


def fetch_page_metadata(url: str, timeout: int = 8, title: str = "") -> Dict[str, str]:
    """Fetch meta description, image and article metadata from a URL page.

    Returns a dict with keys ``description``, ``image``, ``published_time``,
    ``author``, ``section`` (all may be empty). All article:* fields are
    best-effort and default to empty string on failure or when the page
    does not emit that tag.
    """
    result: Dict[str, str] = {
        "description": "",
        "image": "",
        "published_time": "",
        "author": "",
        "section": "",
    }
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
            verify=_get_verify_ssl(),
        )
        resp.raise_for_status()
        force_utf8_if_mislabelled(resp)
        soup = BS4(resp.text, "html.parser")

        # Extract OG metadata (image + description + article:* fields)
        og = _extract_og_metadata(soup, title=title)
        result["image"] = og["image"]
        result["published_time"] = og.get("published_time", "")
        result["author"] = og.get("author", "")
        result["section"] = og.get("section", "")
        if og["description"]:
            cleaned = sanitize_mojibake(og["description"])
            if cleaned:
                result["description"] = cleaned
                return result

        # Try readability-lxml for high-quality article extraction
        desc = sanitize_mojibake(_extract_via_readability(resp.text, url))
        if desc:
            if _is_title_related_description(title, desc):
                result["description"] = desc
            else:
                logger.debug("Rejected readability description as unrelated to title")
            return result

        # Article body paragraphs (BS4 fallback)
        desc = sanitize_mojibake(_extract_via_bs4_article(soup))
        if desc:
            if _is_title_related_description(title, desc):
                result["description"] = desc
            else:
                logger.debug("Rejected article-body description as unrelated to title")
            return result

        # Last resort: any substantial <p> not in noise containers
        desc = sanitize_mojibake(_extract_via_paragraphs(soup))
        if desc:
            if _is_title_related_description(title, desc):
                result["description"] = desc
            else:
                logger.debug("Rejected paragraph description as unrelated to title")
            return result

    except Exception as e:  # noqa: BLE001
        logger.debug("Failed to fetch metadata from %s: %s", url, e)
    return result


def fetch_page_description(url: str, timeout: int = 8) -> str:
    """Try to fetch meta description from a URL page (best-effort).

    Wrapper around :func:`fetch_page_metadata` for backward compatibility.
    """
    return fetch_page_metadata(url, timeout=timeout).get("description", "")


def _fetch_and_parse_page(url: str, title: str = "") -> Dict[str, str]:
    """Fetch a URL and return parsed metadata (description + image).

    Thin wrapper around :func:`fetch_page_metadata` that isolates the
    HTTP fetch + HTML parsing step for use inside :func:`enrich_item`.
    """
    return fetch_page_metadata(url, title=title)


def _clean_html_content(text: str) -> str:
    """Clean HTML entities and normalize whitespace in a fetched description."""
    text = re.sub(r"&#?\w+;", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


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
    # Title-duplicate descriptions get priority fetch (bypass max_fetch budget)
    is_title_dup = bool(desc) and _is_desc_duplicate_of_title(desc, title)
    if fetch_url and fetch_link:
        if _fetch_counter is None:
            if max_fetch != 10:
                logger.debug(
                    "enrich_item: max_fetch=%d set but no _fetch_counter provided; "
                    "rate limiting is per-call only (counter resets each invocation).",
                    max_fetch,
                )
            counter = [0]
        else:
            counter = _fetch_counter
        if counter[0] < max_fetch or is_title_dup:
            if not is_title_dup:
                counter[0] += 1
            metadata = _fetch_and_parse_page(fetch_link, title=title)
            fetched = metadata.get("description", "")
            if fetched and fetched != title and len(fetched) > 20 and _is_title_related_description(title, fetched):
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
    # Prioritize items whose description duplicates the title — these benefit
    # most from URL fetching and should consume the max_fetch budget first.
    items_priority = sorted(
        items,
        key=lambda x: (
            0
            if _is_desc_duplicate_of_title(
                x.get("description", "").strip(),
                x.get("title", ""),
            )
            else 1
        ),
    )
    for item in items_priority:
        enrich_item(
            item,
            context_map=context_map,
            fetch_url=fetch_url,
            max_fetch=max_fetch,
            _fetch_counter=counter,
        )

    # --- Image fetch pass (concurrent og:image for items missing images) ---
    # Budget covers digest size (top + overflow ~150 items).
    fetch_images_concurrent(items, max_workers=8, max_items=MAX_IMAGES_PER_DIGEST)

    # --- Description enrichment pass (concurrent fetch for synthetic descriptions) ---
    if fetch_url:
        fetch_descriptions_concurrent(items, max_workers=6, max_items=80)

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
            # Protect a synthetic Korean category suffix ("...보도.") from being
            # re-translated and mutated. Translate only the English body, then
            # reattach the suffix verbatim.
            if item.get("_synthetic"):
                body, suffix = _split_synthetic_ko_suffix(desc)
            else:
                body, suffix = desc, ""
            ko_body = translate_to_korean(body)
            ko_desc = (ko_body.rstrip() + suffix) if suffix else ko_body
            if ko_desc != desc:
                item["description_ko"] = ko_desc

    save_translation_cache()
