"""Image URL validation for news enrichment.

Pure, network-free helpers that decide whether an image URL is a usable
article image, a tracking pixel / placeholder, or a site logo/icon.

Extracted 2026-07 from ``common.enrichment`` as part of the enrichment facade
decomposition. ``common.enrichment`` re-exports the public names
(``match_bad_image_pattern``, ``is_logo_like_url``, ``match_logo_pattern``,
``_is_valid_image_url``) so existing ``from common.enrichment import ...``
call sites keep working.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

from .image_rejection_metrics import record_image_rejection

logger = logging.getLogger(__name__)


def _has_http_image_scheme(url: str) -> bool:
    parsed = urlparse((url or "").strip())
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


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
