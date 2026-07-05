"""Shared URL content enrichment for news collectors.

Provides functions to fetch meta descriptions from URLs and generate
synthetic descriptions when actual content is unavailable.
"""

import logging
import re
from difflib import SequenceMatcher
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import requests

from . import summary_quality as _summary_quality_mod
from .config import get_verify_ssl
from .encoding_guard import force_utf8_if_mislabelled, sanitize_mojibake
from .image_rejection_metrics import record_image_rejection
from .markdown_utils import smart_truncate
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
    # Korean patterns: translated site self-descriptions.
    # Anchored to end-of-string copula ("입니다"/"제공합니다") to avoid false
    # positives on factual news quoting (e.g. "세계 최대 생산업체인 카렉스는…").
    re.compile(
        r"(?:세계 최대|글로벌 리더|세계적인 리더)"
        r"[^.!?\n]{0,40}"
        r"\s*(?:입니다|을 제공(?:합니다)?|를 제공(?:합니다)?)\s*\.?\s*$",
        re.I,
    ),
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
    "businesspost",
    "비즈니스포스트",
    "인물중심 기업인 프로파일",
    "경제미디어 경제신문",
    "올인원 플랫폼입니다",
    "포트폴리오를 개선하고",
    "개인 금융 뉴스 및 비즈니스 예측",
    "선두주자입니다",
    "우리의 목적은 세상을",
    "더 스마트하고, 더 행복하고",
    "simply wall st",
    "kiplinger",
    "tipranks",
    "stock analysis",
    "관련 광고",
    "포트폴리오 업데이트 보고서",
]

# Article-specific token detection now lives in common.summary_quality.
# The canonical pattern is ``summary_quality.ARTICLE_SPECIFIC_RE`` —
# do not redefine here. Attribute access via the module reference keeps the
# circular import (summary_quality ↔ enrichment) safe by deferring lookup
# to call time.


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
    if len(desc) < 35 and not _summary_quality_mod.ARTICLE_SPECIFIC_RE.search(desc):
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


def _has_http_image_scheme(url: str) -> bool:
    parsed = urlparse((url or "").strip())
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


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


def _extract_overlap_keywords(title: str, text: str) -> tuple[set, set]:
    """Extract normalized keyword sets from title and text for relevance scoring."""
    title_tokens = set(re.findall(r"[A-Za-z0-9$%]{3,}|[가-힣]{2,}", title.lower()))
    text_tokens = set(re.findall(r"[A-Za-z0-9$%]{3,}|[가-힣]{2,}", text.lower()))
    return title_tokens, text_tokens


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


def _is_title_related_description(title: str, desc: str) -> bool:
    """Return True if description appears related to title content."""
    if not title or not desc:
        return True
    # Backward-compatible: do not aggressively reject when title itself is weak.
    if len(title.strip()) < 18:
        return True
    if _is_desc_duplicate_of_title(desc, title):
        return True

    title_tokens, desc_tokens = _extract_overlap_keywords(title, desc)
    if not title_tokens or not desc_tokens:
        return True

    if title_tokens & desc_tokens:
        return True

    title_entities = {e.lower() for e in _extract_title_entities(title)}
    if len(title_entities) < 2 and len(title_tokens) < 3:
        return True
    if title_entities and not (title_entities & desc_tokens):
        return False
    return True


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

# Tracking pixels and placeholder image URL patterns
_BAD_IMAGE_PATTERNS = [
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
# "1x1" must match as a path/filename token (tracking pixel), not a bare substring.
# A substring check previously flagged article slugs like "/articles/1x1-interview.jpg"
# as tracking pixels. This regex requires 1x1 to be bounded by a path separator on
# the left AND followed by an extension / query marker / end-of-string on the right.
_BAD_IMAGE_REGEX = re.compile(r"(?:^|[/_-])1x1(?:\.[a-z0-9]{2,4}|[?#]|$)")
# Synthetic bucket token returned by match_bad_image_pattern when the 1x1 regex
# fires. All size-marker variants collapse to this single metric key so callers
# counting rejections get stable bucketing across /1x1.gif, -1x1.png, /1x1?... etc.
_BAD_IMAGE_REGEX_BUCKET = "1x1-pixel"
# Non-image file extensions to reject (.gif is often a tracking pixel; .svg/.ico are usually logos)
# Note: .webp is intentionally excluded — webp images are valid content images
_BAD_IMAGE_EXTENSIONS = [".gif", ".svg", ".ico"]

# Logo/icon URL patterns. When an RSS feed ships only a site logo, we should
# still try to fetch a proper og:image so the post thumbnail reflects real
# article content. Size patterns (256x256, 64x64, …) were removed in the
# A-lite iteration: they conflict with OG standard image sizes and never
# contributed a real logo rejection in recent measurements.
_LOGO_URL_PATTERNS = (
    "/logo/",
    "/logos/",
    "/favicon",
    "/icon/",
    "/icons/",
    "default-logo",
    "snslogo",
    "snslogotrans",
    "-logo.",
    "_logo.",
    "logo%20",
)


def match_bad_image_pattern(url: str) -> str | None:
    """Return the matched bad-image pattern token for *url*, or None.

    Exposes which pattern fired so callers can log or bucket image
    rejections by cause. Substring matches from ``_BAD_IMAGE_PATTERNS``
    return the matched substring verbatim; the 1x1 tracking-pixel regex
    returns the synthetic bucket token ``"1x1-pixel"`` so all size-marker
    variants (``/1x1.gif``, ``-1x1.png``, ``/1x1?...``) collapse to a
    single metric key. Symmetric with :func:`match_logo_pattern`.
    """
    if not url:
        return None
    url_lower = url.lower()
    for pattern in _BAD_IMAGE_PATTERNS:
        if pattern in url_lower:
            return pattern
    if _BAD_IMAGE_REGEX.search(url_lower):
        return _BAD_IMAGE_REGEX_BUCKET
    return None


def _is_valid_image_url(url: str) -> bool:
    """Check if a URL is likely a valid, useful image (not a placeholder/tracking pixel)."""
    if not _has_http_image_scheme(url):
        return False
    bad = match_bad_image_pattern(url)
    if bad is not None:
        logger.debug("image rejected: bad_pattern=%s url=%s", bad, url[:80])
        record_image_rejection("bad_image", bad)
        return False
    url_lower = url.lower()
    matched_ext = next((ext for ext in _BAD_IMAGE_EXTENSIONS if url_lower.endswith(ext)), None)
    if matched_ext is not None:
        # Allow large gif if it has a meaningful path length
        if len(url) > 80:
            return True
        logger.debug("image rejected: bad_extension=%s url=%s", url_lower[-5:], url[:80])
        record_image_rejection("bad_image", f"ext:{matched_ext.lstrip('.')}")
        return False
    return True


def match_logo_pattern(url: str) -> str | None:
    """Return the matched logo/icon substring for *url*, or None.

    Exposes which pattern fired so callers can log or bucket rejections
    by cause. The boolean wrapper ``is_logo_like_url`` stays the public
    yes/no API to preserve callers' existing truthy-check semantics.
    """
    if not url:
        return None
    url_lower = url.lower()
    for pattern in _LOGO_URL_PATTERNS:
        if pattern in url_lower:
            return pattern
    return None


def is_logo_like_url(url: str) -> bool:
    """Return True if *url* looks like a site logo/icon rather than article art."""
    return match_logo_pattern(url) is not None


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
    # Full-word units allow a leading space ("$80 thousand"); single-letter
    # units must be immediately adjacent ("$73K"). Word units are matched first
    # so the "t" in "thousand" is never mistaken for a trillion suffix, and the
    # letter alt has no leading \s* so "$73 Kelvin" stays "$73" (not "$73K").
    # No trailing \b: "$5MM" still degrades to "$5M" instead of dropping detail.
    price_match = re.search(
        r"\$(\d[\d,.]*(?:\.\d+)?)"
        r"(?:\s*(trillion|billion|million|thousand)s?|([KMBT]))?",
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
        # Normalize the magnitude suffix to a canonical single letter so the
        # extracted detail never contradicts the full number in the body text
        # (e.g. "$73K" — not a misleading "$73" — for a "$73,000" article).
        _word_unit = (price_match.group(2) or "").lower()
        _letter_unit = (price_match.group(3) or "").upper()
        unit = {"trillion": "T", "billion": "B", "million": "M", "thousand": "K"}.get(_word_unit, _letter_unit)
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
