"""Shared URL content enrichment for news collectors.

Provides functions to fetch meta descriptions from URLs and generate
synthetic descriptions when actual content is unavailable.
"""

import logging
import re
from typing import Any, Dict, Optional

import requests

from .encoding_guard import force_utf8_if_mislabelled, sanitize_mojibake
from .enrichment_images import (  # noqa: F401  (re-exported for backward compat)
    _is_valid_image_url,
    is_logo_like_url,
    match_bad_image_pattern,
    match_logo_pattern,
)
from .enrichment_network import (  # noqa: F401  (re-exported for backward compat)
    _BOILERPLATE_FRAGMENT_PATTERNS,
    _BROWSER_UA,
    _EXCLUDE_CLASS_RE,
    _IMAGE_META_PATTERNS,
    _NOISE_DESC_PATTERNS,
    _USER_AGENT,
    _clean_meta_description,
    _decode_google_news_base64,
    _extract_og_metadata,
    _extract_via_bs4_article,
    _extract_via_paragraphs,
    _extract_via_readability,
    _fetch_og_image,
    _get_verify_ssl,
    _gnews_url_cache,
    _is_low_information_fragment,
    _resolve_google_news_url,
    _resolve_google_news_url_inner,
    _resolve_via_gnewsdecoder,
    is_private_url,
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
from .summary_quality import _is_site_boilerplate  # noqa: F401  (re-exported for backward compat)

logger = logging.getLogger(__name__)

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

# Site-level boilerplate detection (``_is_site_boilerplate`` + its patterns)
# now lives in ``common.summary_quality`` and is re-exported at the top of this
# module for backward compatibility. Article-specific token detection likewise
# lives in ``summary_quality.ARTICLE_SPECIFIC_RE``; do not redefine either here.


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


# Image URL validation (``match_bad_image_pattern``, ``_is_valid_image_url``,
# ``match_logo_pattern``, ``is_logo_like_url`` + their pattern data) now lives
# in ``common.enrichment_images``. The Google News resolver chain
# (``_resolve_google_news_url`` / ``_inner`` / ``_resolve_via_gnewsdecoder``),
# the og:image fetcher (``_fetch_og_image``), and the SSL-verify helper
# (``_get_verify_ssl``) now live in ``common.enrichment_network``. All are
# re-exported at the top of this module for backward compatibility.


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
