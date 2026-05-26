"""Unified summary quality detectors — single source of truth.

Public API:
  - ``ARTICLE_SPECIFIC_RE`` — canonical positive-signal pattern. Both
    ``common.enrichment`` and ``scripts.fix_post_descriptions`` import it
    from here, so a pattern update lands in one place.
  - ``is_boilerplate(desc)`` — orchestrates the three boilerplate detectors
    (``common.enrichment._is_site_boilerplate``,
    ``common.summarizer._is_generic_desc``,
    ``common.summarizer._is_boilerplate_desc``).
  - ``has_positive_signal(body)`` — True if body carries a real-content
    token (number, currency, acronym, headline lead-in).

Circular-import resolution: this module is imported both as a consumer
(needs detectors from enrichment/summarizer) and as a provider (enrichment
needs ARTICLE_SPECIFIC_RE). We bind sibling modules with
``from . import <name> as _<name>_mod`` so each side only resolves the
other's attributes lazily inside function bodies. ARTICLE_SPECIFIC_RE is
defined BEFORE the sibling imports so partial-module access from
enrichment during its own load finds the pattern.

Lookaround over ``\\b``: in Python 3 ``\\w`` includes Hangul, so
``\\b\\d{4}\\b`` does NOT match ``2026년`` (no boundary between ``6`` and
``년``). ``(?<!\\d)`` / ``(?!\\d)`` is used instead.
"""

from __future__ import annotations

import re

__all__ = [
    "ARTICLE_SPECIFIC_RE",
    "has_positive_signal",
    "is_boilerplate",
]


# ---------------------------------------------------------------------------
# Canonical positive-signal pattern.
# Defined BEFORE sibling imports so enrichment.py can read it from a partial
# summary_quality module during its own load (circular import resolution).
# ---------------------------------------------------------------------------
ARTICLE_SPECIFIC_RE = re.compile(
    r"(?:[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)"                       # Title-case word pair (proper noun)
    r"|(?:(?<![A-Za-z])[A-Z]{2,}(?![A-Za-z]))"                   # Acronym / ticker
    r"|(?:(?<!\d)\d{4}(?!\d))"                                    # 4-digit year (2026…)
    r"|(?:\d+[.,]\d+)"                                            # Decimal/comma number
    r"|(?:[$€£₩¥]\s*\d)"                                          # Currency + digit
    r"|(?:\d+\s*(?:%|억|만|조|달러|원|위안|위|건|종|개|월|일))"     # Number with unit
    r"|(?:(?:월|년|일)\s*\d)"                                     # Korean date fragment (월 04, 년 2026)
    r"|(?:\d{1,3}(?:,\d{3})+)"                                    # 1,234,567 grouping
    r'|(?:["“‘][^"”’]{3,}["”’])'                                  # Quoted phrase
    r"|(?:주요\s*(?:테마|출처|이벤트|이슈|종목)\s*:)"               # Korean headline lead-in
    r"|(?:오늘의?\s*헤드라인\s*:)"                                 # "오늘의 헤드라인:"
)


def has_positive_signal(body: str) -> bool:
    """Return True if body carries at least one positive content signal."""
    if not body:
        return False
    return bool(ARTICLE_SPECIFIC_RE.search(body))


# ---------------------------------------------------------------------------
# Sibling-module references for boilerplate orchestration.
# Module-level bindings (``from . import X as _X_mod``) tolerate the cycle
# because attribute lookup happens at call time, not load time.
# ---------------------------------------------------------------------------
from . import enrichment as _enrichment_mod  # noqa: E402
from . import summarizer as _summarizer_mod  # noqa: E402


def is_boilerplate(desc: str) -> bool:
    """Return True if desc matches any boilerplate / generic detector.

    Orchestrates the three canonical detectors in ``common.enrichment`` /
    ``common.summarizer``. This function is the single dependency that
    consumers should import.
    """
    if not desc:
        return False
    if _enrichment_mod._is_site_boilerplate(desc):
        return True
    if _summarizer_mod._is_generic_desc(desc):
        return True
    if _summarizer_mod._is_boilerplate_desc(desc):
        return True
    return False
