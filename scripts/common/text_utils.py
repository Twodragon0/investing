"""Text normalization, truncation, and favicon helpers for ThemeSummarizer.

Pure helpers extracted from summarizer.py — no module-level side effects.
"""

from .post_generator import _MISTRANSLATION_FIXES
from .utils import truncate_sentence as _truncate_sentence_util


def _fix_mistranslations(text: str) -> str:
    """Apply mistranslation correction dictionary to text."""
    for wrong, correct in _MISTRANSLATION_FIXES.items():
        text = text.replace(wrong, correct)
    return text


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
