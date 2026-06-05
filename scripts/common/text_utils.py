"""Text normalization, truncation, and favicon helpers for ThemeSummarizer.

Pure helpers extracted from summarizer.py — no module-level side effects.
"""

import re

from .post_generator import _MISTRANSLATION_FIXES
from .utils import truncate_sentence as _truncate_sentence_util


def _fix_mistranslations(text: str) -> str:
    """Apply mistranslation correction dictionary to text."""
    for wrong, correct in _MISTRANSLATION_FIXES.items():
        text = text.replace(wrong, correct)
    return text


# Trailing junk fragments that some sources/translations append to article
# descriptions (ad slugs, mangled "관련 X" tails). Anchored at the END only so
# legitimate body content is never touched — unlike the whole-description
# boilerplate reject in enrichment._is_site_boilerplate.
#
# Korean noun set is deliberately limited to terms that never carry article
# meaning in a news summary (광고/정보/뉴스/주소/홍보). "관련 보도" and similar
# are EXCLUDED because enrichment._analyze_*_title emits them as a legitimate
# synthetic suffix. An optional 2–5 char lead-in absorbs mangled fragments
# like "급락 " / "등급락 " so "...경고했습니다. 급락 관련 주소." → "...경고했습니다.".
# English markers are restricted to multi-word slugs to avoid truncating a real
# sentence that merely ends in "sponsored"/"advertisement".
_TRAILING_ARTIFACT_RE = re.compile(
    r"\s*(?:"
    r"(?:[가-힣]{2,5}\s+)?관련\s?(?:광고|정보|뉴스|주소|홍보)"
    r"|read\s+more|sponsored\s+content"
    r")\s*[.。!?]?\s*$",
    re.IGNORECASE,
)


def _strip_trailing_artifacts(text: str) -> str:
    """Strip trailing ad/boilerplate fragments left at the tail of a description.

    Removes only end-anchored junk (e.g. "... 가격이 폭락했습니다. 등급락 관련정보.")
    and loops so stacked tails are fully cleared. Returns the cleaned text with
    surrounding whitespace stripped.
    """
    if not text:
        return text
    prev = None
    while prev != text:
        prev = text
        text = _TRAILING_ARTIFACT_RE.sub("", text).rstrip()
    return text.strip()


def _truncate_sentence(text: str, max_len: int = 300) -> str:
    """Truncate text at the nearest sentence boundary within max_len.

    Uses forward-search strategy to find the first complete sentence,
    unlike utils.truncate_sentence which uses backward-search.
    Returns empty string if text is too short to be useful.
    """
    text = text.strip()
    if not text or len(text) < 15:
        return ""
    if len(text) <= max_len:
        return text

    _SENTENCE_ENDS = [
        "다. ",
        "요. ",
        "음. ",
        "됩니다. ",
        "입니다. ",
        "습니다. ",
        "했다. ",
        "됐다. ",
        "였다. ",
        "합니다. ",
        "했습니다. ",
        "겠습니다. ",
        "봅니다. ",
        "。",
        ". ",
        "! ",
        "? ",
    ]
    best_idx = -1
    for sep in _SENTENCE_ENDS:
        idx = text.find(sep, 20)
        if 20 < idx < max_len:
            candidate = idx + len(sep)
            if candidate > best_idx:
                best_idx = candidate

    if best_idx > 20:
        return text[:best_idx].strip()
    return _truncate_sentence_util(text, max_length=max_len)


def _favicon_url(link: str) -> str:
    """Return a Google Favicon API URL for the domain of *link*.

    Falls back to empty string if the link cannot be parsed. Uses sz=128
    for sharper rendering on retina displays.
    """
    if not link:
        return ""
    try:
        from urllib.parse import urlparse

        parsed = urlparse(link)
        domain = parsed.netloc or parsed.hostname or ""
        if domain:
            return f"https://www.google.com/s2/favicons?domain={domain}&sz=128"
    except Exception:  # noqa: S110
        return ""
    return ""


def _best_favicon_link(item: dict) -> str:
    """Pick the best link for favicon extraction.

    Prefers the resolved article URL (``original_url``) over the raw link,
    so Google News redirect URLs use the actual publisher's favicon
    (e.g., cnbc.com) instead of news.google.com's generic favicon.
    """
    original = item.get("original_url", "")
    if original and "news.google.com" not in original and "google." not in original.split("/")[2:3][0:1]:
        return original
    link = item.get("link", "")
    if link and "news.google.com" not in link:
        return link
    return original or link
