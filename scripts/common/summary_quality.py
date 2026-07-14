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
    (``_is_site_boilerplate``, ``is_generic_desc``, ``_is_boilerplate_desc``),
    all defined in this module.

Acyclic layering: this module is a pure *provider* of quality detectors with
no sibling imports. ``common.enrichment`` re-exports ``_is_site_boilerplate``
and ``common.summarizer`` re-exports ``_is_boilerplate_desc`` /
``_BOILERPLATE_DESC_PHRASES`` from here for backward compatibility, so the
detector definitions live in exactly one place and the previous
``summarizer ↔ summary_quality`` / ``enrichment ↔ summary_quality`` import
cycles (which needed deferred ``# noqa: E402`` imports) are gone.

Lookaround over ``\\b``: in Python 3 ``\\w`` includes Hangul, so
``\\b\\d{4}\\b`` does NOT match ``2026년`` (no boundary between ``6`` and
``년``). ``(?<!\\d)`` / ``(?!\\d)`` is used instead.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

__all__ = [
    "ARTICLE_SPECIFIC_RE",
    "GENERIC_DESC_PATTERNS",
    "has_positive_signal",
    "is_boilerplate",
    "is_generic_desc",
]


# ---------------------------------------------------------------------------
# Canonical positive-signal pattern.
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
# Site-level boilerplate detection.
# Moved here 2026-07 from ``common.enrichment`` so the ``is_boilerplate``
# orchestrator no longer needs a deferred import back into enrichment.
# ``common.enrichment`` re-exports ``_is_site_boilerplate`` for backward
# compatibility (collectors and tests import it from there).
# ---------------------------------------------------------------------------
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
    if len(desc) < 35 and not ARTICLE_SPECIFIC_RE.search(desc):
        logger.debug("Short generic description (no specific tokens): %r", desc[:80])
        return True

    return False


# ---------------------------------------------------------------------------
# Phrase-list boilerplate detection.
# Moved here 2026-07 from ``common.summarizer`` so the ``is_boilerplate``
# orchestrator no longer needs a deferred import back into summarizer.
# ``common.summarizer`` re-exports ``_is_boilerplate_desc`` and
# ``_BOILERPLATE_DESC_PHRASES`` for backward compatibility.
# ---------------------------------------------------------------------------
# Known site boilerplate phrases that leak through translation
_BOILERPLATE_DESC_PHRASES = [
    "우리의 목적은 세상을",
    "더 스마트하고, 더 행복하고",
    "깊이있는 인터뷰와 칼럼",
    "뉴스 제공.",
    "포트폴리오를 개선하고",
    "개인 금융 뉴스 및 비즈니스",
    "올인원 플랫폼입니다",
    "선두주자입니다",
    "motley fool",
    "seeking alpha",
]


def _is_boilerplate_desc(desc: str) -> bool:
    """Return True if description is site-level boilerplate, not article content."""
    if not desc:
        return False
    lower = desc.lower()
    return any(phrase in lower for phrase in _BOILERPLATE_DESC_PHRASES)


def is_boilerplate(desc: str) -> bool:
    """Return True if desc matches any boilerplate / generic detector.

    Orchestrates the three canonical detectors, all defined in this module:
    site-level boilerplate (``_is_site_boilerplate``), generic-desc patterns
    (``is_generic_desc``), and the phrase-list filter (``_is_boilerplate_desc``).
    """
    if not desc:
        return False
    if _is_site_boilerplate(desc):
        return True
    if is_generic_desc(desc):
        return True
    if _is_boilerplate_desc(desc):
        return True
    return False
