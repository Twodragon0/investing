"""Shared encoding guards for text fetched from external sources.

Centralises the mojibake detector and recovery helper used by
``rss_fetcher.py`` and ``enrichment.py`` so that any description that
enters the post pipeline has a single, consistent sanitisation step.

Mojibake typically arises when a remote server sends UTF-8 bytes but
declares ``Content-Type: text/html; charset=iso-8859-1`` (or similar),
causing ``requests`` to decode ``resp.text`` as Latin-1. Downstream the
text looks like ``ì£¼ëì ê¸°ì ììì`` — legitimate Korean never contains
such runs.
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Runs of Latin-1 supplement + C1 control chars (U+0080–U+00FF) that
# indicate UTF-8 bytes were misinterpreted as Latin-1/CP1252 upstream.
# Legitimate Korean text never contains such runs; accented European text
# rarely exceeds 2 consecutive chars in this block.
_MOJIBAKE_RE = re.compile(r"[\u0080-\u00ff]{3,}")


def is_mojibake(text: str) -> bool:
    """Return True if *text* shows a mojibake pattern."""
    if not text:
        return False
    return bool(_MOJIBAKE_RE.search(text))


def sanitize_mojibake(text: str) -> str:
    """Return cleaned text, attempting Latin-1 → UTF-8 recovery when possible.

    Strategy:
    1. Round-trip recover: re-encode as Latin-1 and decode as UTF-8. If
       the recovered text contains Hangul or CJK characters, return it.
    2. If recovery fails AND the text still has a long mojibake run, drop
       the description so downstream synthetic fallback can take over.
    """
    if not text:
        return text
    # Fast path: no high-byte chars → nothing to recover.
    if not any(0x80 <= ord(c) <= 0xFF for c in text):
        return text
    # Attempt round-trip recovery: UTF-8 bytes misinterpreted as Latin-1.
    try:
        recovered = text.encode("latin-1", errors="strict").decode("utf-8", errors="strict")
    except (UnicodeEncodeError, UnicodeDecodeError):
        recovered = None
    if recovered and any(0xAC00 <= ord(c) <= 0xD7A3 or 0x4E00 <= ord(c) <= 0x9FFF for c in recovered):
        return recovered
    # Unrecoverable — if mojibake pattern is still present, drop the text.
    if _MOJIBAKE_RE.search(text):
        logger.warning("Description dropped due to unrecoverable mojibake")
        return ""
    return text


def force_utf8_if_mislabelled(response: Any) -> None:
    """Force ``response.encoding = 'utf-8'`` when the server labels the
    body as Latin-1 / ISO-8859-1 / ASCII.

    Many Korean news endpoints (Google News RSS, certain CDNs) serve
    UTF-8 with an incorrect ``Content-Type`` header; without this nudge
    ``response.text`` comes back as mojibake and downstream extraction is
    corrupted at the source.
    """
    encoding = getattr(response, "encoding", None)
    if encoding and encoding.lower() in ("iso-8859-1", "latin-1", "ascii"):
        response.encoding = "utf-8"
