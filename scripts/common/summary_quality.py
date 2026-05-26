"""Unified summary quality detectors.

Single entry point for boilerplate / generic / positive-signal classification.

Before this module existed, callers (``check_description_quality``,
``check_post_summary``, post-build inspectors) each imported the three
underscore-prefixed helpers individually:

  - ``common.enrichment._is_site_boilerplate`` (site phrases + regex + short-desc rule)
  - ``common.summarizer._is_generic_desc``  (synthetic placeholder patterns)
  - ``common.summarizer._is_boilerplate_desc`` (MT-leak phrase list)

That cross-module private-name coupling is a DIP violation: a CLI script
should not reach into a detector module's underscore internals, and a
pattern update in one file would silently drift away from its mirror.
This facade exposes a single public surface and orchestrates the existing
implementations so production callers depend on one stable interface.

Public API:
  - ``is_boilerplate(desc)`` — True if desc matches any boilerplate detector
  - ``has_positive_signal(body)`` — True if body carries a real-content token
    (number, currency, acronym, headline lead-in)
  - ``ARTICLE_SPECIFIC_RE`` — re-export of the positive-signal pattern
"""

from __future__ import annotations

import re

try:
    from .enrichment import _is_site_boilerplate as _enrichment_boilerplate
    from .summarizer import _is_boilerplate_desc as _summarizer_boilerplate
    from .summarizer import _is_generic_desc as _summarizer_generic
except ImportError:  # pragma: no cover — only happens when scripts/ not on PYTHONPATH
    _enrichment_boilerplate = None  # type: ignore[assignment]
    _summarizer_boilerplate = None  # type: ignore[assignment]
    _summarizer_generic = None  # type: ignore[assignment]


__all__ = [
    "ARTICLE_SPECIFIC_RE",
    "has_positive_signal",
    "is_boilerplate",
]


# Positive-signal pattern. Mirrors ``common.enrichment._ARTICLE_SPECIFIC_RE``
# plus headline-style markers (quoted phrase, Korean "헤드라인:"/"주요 ...:"
# lead-in) used by post-summary validation.
#
# Lookaround over ``\b``: in Python 3 ``\w`` includes Hangul, so ``\b\d{4}\b``
# does NOT match ``2026년`` (no boundary between ``6`` and ``년``).
# Use ``(?<!\d)`` / ``(?!\d)`` to anchor "not surrounded by other digits"
# which works for Korean-mixed input as well.
ARTICLE_SPECIFIC_RE = re.compile(
    r"(?:[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)"             # Title-case word pair (proper noun)
    r"|(?:(?<![A-Za-z])[A-Z]{2,}(?![A-Za-z]))"        # Acronym / ticker
    r"|(?:(?<!\d)\d{4}(?!\d))"                         # 4-digit year (2026, 2024…)
    r"|(?:\d+[.,]\d+)"                                 # Decimal/comma number (e.g. 1.07, 75,000)
    r"|(?:[$€£₩¥]\s*\d)"                              # Currency + digit
    r"|(?:\d+\s*(?:%|억|만|조|달러|원|위안|위))"        # Number with unit
    r"|(?:\d{1,3}(?:,\d{3})+)"                         # 1,234,567 grouping
    r'|(?:["“‘][^"”’]{3,}["”’])'                       # Quoted phrase
    r"|(?:주요\s*(?:테마|출처|이벤트|이슈|종목)\s*:)"    # Korean headline lead-in
    r"|(?:오늘의?\s*헤드라인\s*:)"                      # "오늘의 헤드라인:"
)


def is_boilerplate(desc: str) -> bool:
    """Return True if desc matches any boilerplate / generic detector.

    Orchestrates three canonical detectors. The underlying implementations
    stay in ``common.enrichment`` and ``common.summarizer``; this function
    is the single dependency consumers should import.
    """
    if not desc:
        return False
    if _enrichment_boilerplate is not None and _enrichment_boilerplate(desc):
        return True
    if _summarizer_generic is not None and _summarizer_generic(desc):
        return True
    if _summarizer_boilerplate is not None and _summarizer_boilerplate(desc):
        return True
    return False


def has_positive_signal(body: str) -> bool:
    """Return True if body carries at least one positive content signal.

    Used by ``check_post_summary`` to flag filler-only excerpts that pass
    length/HTML checks but lack any number, proper noun, or headline marker.
    """
    if not body:
        return False
    return bool(ARTICLE_SPECIFIC_RE.search(body))
