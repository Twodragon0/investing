"""Network core for news enrichment (URL resolution, page fetch, extraction).

Holds the network-facing helpers of the enrichment pipeline: Google News URL
resolution, OG-image / page-metadata fetching over HTTP, and the HTML content
extractors that clean fetched descriptions.

Extracted 2026-07 from ``common.enrichment`` as part of the enrichment facade
decomposition (P2-A), mirroring the ``enrichment_images`` / ``enrichment_synthetic``
split. ``common.enrichment`` re-exports the public names so existing
``from common.enrichment import ...`` call sites (collectors, ``rss_fetcher``, …)
keep working unchanged.

NOTE (batch 1 — leaf move): the URL-safety wrapper, meta-description cleaner,
Google News base64 decoder, and the HTML metadata/content extractors now live
here. The resolver chain and page-fetch orchestrators still live in the facade
and are moved in later batches per ``docs/refactoring-plan-2026-07.md`` §1.4.
Patch-string relocation happens in the same commit as each symbol move to keep
every batch's test gate hermetic.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict

from . import summary_quality as _summary_quality_mod
from .enrichment_images import _is_valid_image_url
from .enrichment_synthetic import _is_title_related_description
from .markdown_utils import smart_truncate
from .summary_quality import _is_site_boilerplate
from .utils import is_private_url_target

logger = logging.getLogger(__name__)

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
