"""Unified summary quality detectors — single source of truth.

Public API:
  - ``ARTICLE_SPECIFIC_RE`` — canonical positive-signal pattern. Both
    ``common.enrichment`` and ``scripts.fix_post_descriptions`` import it
    from here, so a pattern update lands in one place.
  - ``GENERIC_DESC_PATTERNS`` — canonical list of generic/synthetic
    description regexes. ``common.summarizer`` consumes via the facade
    so the patterns live in exactly one location.
  - ``has_positive_signal(body)`` — True if body carries a real-content
    token (number, currency, acronym, headline lead-in).
  - ``is_generic_desc(desc)`` — True if desc matches any generic /
    synthetic placeholder pattern. Single SSoT for generic-desc detection.
  - ``is_boilerplate(desc)`` — orchestrates the three boilerplate detectors
    (``common.enrichment._is_site_boilerplate``,
    ``is_generic_desc`` defined here,
    ``common.summarizer._is_boilerplate_desc``).

Circular-import resolution: this module is imported both as a consumer
(needs detectors from enrichment/summarizer) and as a provider (enrichment
needs ARTICLE_SPECIFIC_RE; summarizer needs GENERIC_DESC_PATTERNS). We bind
sibling modules with ``from . import <name> as _<name>_mod`` so each side
only resolves the other's attributes lazily inside function bodies.
Canonical patterns are defined BEFORE the sibling imports so partial-module
access from enrichment/summarizer during their own load finds the patterns.

Lookaround over ``\\b``: in Python 3 ``\\w`` includes Hangul, so
``\\b\\d{4}\\b`` does NOT match ``2026년`` (no boundary between ``6`` and
``년``). ``(?<!\\d)`` / ``(?!\\d)`` is used instead.
"""

from __future__ import annotations

import re

__all__ = [
    "ARTICLE_SPECIFIC_RE",
    "GENERIC_DESC_PATTERNS",
    "has_positive_signal",
    "is_boilerplate",
    "is_generic_desc",
]


# ---------------------------------------------------------------------------
# Canonical positive-signal pattern.
# Defined BEFORE sibling imports so enrichment.py can read it from a partial
# summary_quality module during its own load (circular import resolution).
# ---------------------------------------------------------------------------
ARTICLE_SPECIFIC_RE = re.compile(
    r"(?:[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)"  # Title-case word pair (proper noun)
    r"|(?:(?<![A-Za-z])[A-Z]{2,}(?![A-Za-z]))"  # Acronym / ticker
    r"|(?:(?<!\d)\d{4}(?!\d))"  # 4-digit year (2026…)
    r"|(?:\d+[.,]\d+)"  # Decimal/comma number
    r"|(?:[$€£₩¥]\s*\d)"  # Currency + digit
    r"|(?:\d+\s*(?:%|억|만|조|달러|원|위안|위|건|종|개|월|일))"  # Number with unit
    r"|(?:(?:월|년|일)\s*\d)"  # Korean date fragment (월 04, 년 2026)
    r"|(?:\d{1,3}(?:,\d{3})+)"  # 1,234,567 grouping
    r'|(?:["“‘][^"”’]{3,}["”’])'  # Quoted phrase
    r"|(?:주요\s*(?:테마|출처|이벤트|이슈|종목)\s*:)"  # Korean headline lead-in
    r"|(?:오늘의?\s*헤드라인\s*:)"  # "오늘의 헤드라인:"
)


def has_positive_signal(body: str) -> bool:
    """Return True if body carries at least one positive content signal."""
    if not body:
        return False
    return bool(ARTICLE_SPECIFIC_RE.search(body))


# ---------------------------------------------------------------------------
# Canonical generic/synthetic description patterns.
# Migrated 2026-05-28 from ``common.summarizer._GENERIC_DESC_PATTERNS`` to
# establish a single SSoT (PR #947 facade pattern extension). summarizer.py
# now imports this list via the facade rather than redefining locally.
# Defined BEFORE the sibling imports so summarizer.py can read it from a
# partial summary_quality module during its own load.
# ---------------------------------------------------------------------------
GENERIC_DESC_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"에서 보도한 뉴스입니다\.?$"),
    re.compile(r"에서 보도한 소식입니다\.?$"),
    re.compile(r"관련 소식을 전했습니다\.?$"),
    re.compile(r"원문에서 세부 내용을 확인하세요\.?$"),
    re.compile(r"거래소 공지사항입니다\.?\s*$"),
    re.compile(r"please enable javascript", re.I),
    re.compile(r"^AMENDMENT NO\.", re.I),
    re.compile(r"^FORM\s+\d", re.I),
    re.compile(r"^access denied", re.I),
    re.compile(r"^403 forbidden", re.I),
    re.compile(r"^Your (?:privacy|cookie)", re.I),
    re.compile(r"^We use cookies", re.I),
    re.compile(r"^Subscribe to", re.I),
    re.compile(r"^Sign up (?:for|to)", re.I),
    re.compile(r"^JavaScript (?:is )?(?:required|must)", re.I),
    re.compile(r"^This (?:page|site|website) (?:uses|requires)", re.I),
    re.compile(r"^Loading\.\.\.", re.I),
    re.compile(r"에서 확인하세요\.?\s*$"),
    re.compile(r"^업데이트[\s:.]", re.I),
    re.compile(r"관련 소식$"),
    re.compile(r"^Read more", re.I),
    re.compile(r"^Click here", re.I),
    re.compile(r"^Continue reading", re.I),
    re.compile(r"^This article", re.I),
    re.compile(r"^The post .+ appeared first", re.I),
    # Synced with enrichment.py _SYNTHETIC_MARKERS
    re.compile(r"주시해야 합니다\.?\s*$"),
    re.compile(r"확인하세요\.?\s*$"),
    re.compile(r"관련 시장 동향입니다\.?\s*$"),
    re.compile(r"관련 세부 내용은"),
    re.compile(r"관련 변경사항을"),
    re.compile(r"시장 심리와 가격"),
    re.compile(r"투자 시사점을"),
    re.compile(r"관련 소식입니다\.?\s*$"),
    re.compile(r"거래소 공지사항"),
    re.compile(r"산업 동향"),
    re.compile(r"면밀히 분석해야 합니다"),
    re.compile(r"함께 고려해야 합니다"),
    re.compile(r"투자 판단 시"),
    re.compile(r"관련 시장 뉴스입니다"),
    re.compile(r"원문 기사의 세부 내용을 확인하세요"),
    # New-style synthetic descriptions (fact-based with "보도" suffix)
    re.compile(r"관련 보도\.?\s*$"),
    re.compile(r"섹터 보도\.?\s*$"),
    re.compile(r"산업 보도\.?\s*$"),
    re.compile(r"시장 보도\.?\s*$"),
]


def is_generic_desc(desc: str) -> bool:
    """Return True if desc matches any generic/synthetic placeholder pattern.

    Single SSoT consumed by ``common.summarizer._is_generic_desc`` (kept as a
    thin backward-compat wrapper) and by ``is_boilerplate`` orchestrator.
    """
    if not desc:
        return False
    body = desc.strip()
    return any(p.search(body) for p in GENERIC_DESC_PATTERNS)


# ---------------------------------------------------------------------------
# Sibling-module references for boilerplate orchestration.
# Module-level bindings (``from . import X as _X_mod``) tolerate the cycle
# because attribute lookup happens at call time, not load time.
# ---------------------------------------------------------------------------
from . import enrichment as _enrichment_mod  # noqa: E402
from . import summarizer as _summarizer_mod  # noqa: E402


def is_boilerplate(desc: str) -> bool:
    """Return True if desc matches any boilerplate / generic detector.

    Orchestrates the three canonical detectors: site-level boilerplate
    (``common.enrichment._is_site_boilerplate``), generic-desc patterns
    (``is_generic_desc`` defined above), and the phrase-list filter
    (``common.summarizer._is_boilerplate_desc``).
    """
    if not desc:
        return False
    if _enrichment_mod._is_site_boilerplate(desc):
        return True
    if is_generic_desc(desc):
        return True
    if _summarizer_mod._is_boilerplate_desc(desc):
        return True
    return False
