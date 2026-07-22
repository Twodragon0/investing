"""Network core for news enrichment (URL resolution, page fetch, extraction).

Holds the network-facing helpers of the enrichment pipeline: Google News URL
resolution, OG-image / page-metadata fetching over HTTP, and the HTML content
extractors that clean fetched descriptions.

Extracted 2026-07 from ``common.enrichment`` as part of the enrichment facade
decomposition (P2-A), mirroring the ``enrichment_images`` / ``enrichment_synthetic``
split. ``common.enrichment`` re-exports the public names so existing
``from common.enrichment import ...`` call sites (collectors, ``rss_fetcher``, …)
keep working unchanged.

NOTE (batches 1-3): the URL-safety wrapper, meta-description cleaner, Google
News base64 decoder, and the HTML metadata/content extractors (batch 1) plus
the Google News resolver chain (``_resolve_google_news_url`` / ``_inner`` /
``_resolve_via_gnewsdecoder``) and the og:image fetcher (batch 2) and the
page-metadata fetcher (``fetch_page_metadata``, batch 3) now live here.
The thin ``fetch_page_description`` wrapper still lives in the facade and is
moved in a later batch per ``docs/refactoring-plan-2026-07.md`` §1.4.
Patch-string relocation happens in the same commit as each symbol move to
keep every batch's test gate hermetic.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import requests

from . import summary_quality as _summary_quality_mod
from .config import get_verify_ssl
from .encoding_guard import force_utf8_if_mislabelled, sanitize_mojibake
from .enrichment_images import _is_valid_image_url, is_logo_like_url
from .enrichment_synthetic import _is_title_related_description
from .markdown_utils import smart_truncate
from .summary_quality import _is_site_boilerplate
from .utils import is_private_url_target

logger = logging.getLogger(__name__)

_VERIFY_SSL: Optional[object] = None


def _get_verify_ssl():
    global _VERIFY_SSL
    if _VERIFY_SSL is None:
        _VERIFY_SSL = get_verify_ssl()
    return _VERIFY_SSL


# readability-lxml is a declared dependency (requirements.txt); its absence is
# an environment regression that silently drops the best-quality extraction
# path. Warn once per process so the degradation is visible without flooding
# the per-URL enrichment loop.
_warned_readability_missing = False

# Cache for resolved Google News URLs to avoid redundant lookups
_gnews_url_cache: Dict[str, str] = {}


def is_private_url(url: str) -> bool:
    """Check if URL points to an obvious private/internal target."""
    return is_private_url_target(url)


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


def _is_google_news_host(url: str) -> bool:
    """True when ``url``'s host is Google News (``news.google.com`` or a subdomain).

    Parses the hostname instead of a substring match so a URL that merely
    contains ``news.google.com`` in its path/query is not misrouted through
    Google News resolution (CodeQL ``py/incomplete-url-substring-sanitization``).
    """
    host = (urlparse(url).hostname or "").lower()
    return host == "news.google.com" or host.endswith(".news.google.com")


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


_BROWSER_UA = _USER_AGENT


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


def _resolve_google_news_url(url: str, timeout: int = 8) -> str:
    """Follow Google News redirect to get the real article URL.

    Strategy:
    1. Return cached result if available.
    2. Try base64 decoding of the RSS article path (fastest, no network).
    3. Follow HTTP redirects with ``requests.head`` (max 5 hops) then ``requests.get``.
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
    if _is_google_news_host(url):
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
