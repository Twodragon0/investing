"""Synthetic description synthesis and title/entity analysis for enrichment.

Pure, network-free helpers that turn a news title + source into a Korean
synthetic description, extract salient entities, and score title-vs-description
relevance / duplication. Extracted 2026-07 from ``common.enrichment`` as part
of the enrichment facade decomposition; ``common.enrichment`` re-exports the
public names so existing ``from common.enrichment import ...`` call sites keep
working.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Dict, Optional

# Pre-compiled regex for text normalization (used in duplicate detection)
_NORM_RE = re.compile(r"[\s\W]+")


# ---------------------------------------------------------------------------
# Source context maps for synthetic descriptions
# ---------------------------------------------------------------------------

_CRYPTO_SOURCE_CONTEXT: Dict[str, str] = {
    "CryptoPanic": "암호화폐 뉴스 플랫폼",
    "CoinDesk RSS": "코인데스크",
    "CoinTelegraph RSS": "코인텔레그래프",
    "The Block RSS": "더블록",
    "Decrypt RSS": "디크립트",
    "Bitcoin Magazine": "비트코인 매거진",
    "Binance": "바이낸스 거래소",
    "Google News": "구글 뉴스",
    "Rekt News": "보안사고 전문 매체",
    "DeFiLlama": "디파이 분석 플랫폼",
}

_STOCK_SOURCE_CONTEXT: Dict[str, str] = {
    "CNBC Top News": "CNBC",
    "MarketWatch": "마켓워치",
    "한국경제": "한국경제신문",
    "매일경제": "매일경제신문",
    "조선비즈": "조선비즈",
    "Google News Stocks EN": "구글 뉴스 주식",
    "Google News Stocks KR": "구글 뉴스 한국주식",
    "Yahoo Finance": "야후 파이낸스",
    "Reuters": "로이터",
    "Bloomberg": "블룸버그",
    "Google News": "구글 뉴스",
}

_POLITICAL_SOURCE_CONTEXT: Dict[str, str] = {
    "Capitol Trades": "미국 의회 거래",
    "Capitol Trades Korean": "미국 의회 거래",
    "SEC Insider Trading": "SEC 내부자 거래",
    "SEC Insider Activity": "SEC 내부자 활동",
    "SEC 내부자거래 KR": "SEC 내부자 거래",
    "Trump EO Economy": "트럼프 경제 정책",
    "Trump Tariff Policy": "트럼프 관세 정책",
    "Trump Crypto Policy": "트럼프 암호화폐 정책",
    "SEC EDGAR": "SEC 공시 시스템",
    "Google News": "구글 뉴스",
}

_WORLDMONITOR_SOURCE_CONTEXT: Dict[str, str] = {
    "BBC World": "BBC 월드 뉴스",
    "Reuters World": "로이터 세계 뉴스",
    "Guardian World": "가디언 세계 뉴스",
    "Al Jazeera": "알자지라",
    "AP News World": "AP 통신",
    "France24": "프랑스24",
    "DW News": "도이체벨레",
    "NHK World": "NHK 월드",
    "WorldMonitor": "월드모니터",
    "Google News": "구글 뉴스",
}

_SOCIAL_SOURCE_CONTEXT: Dict[str, str] = {
    "Twitter/X": "트위터/X",
    "Google News Social EN": "구글 뉴스 소셜",
    "Google News Social KR": "구글 뉴스 소셜",
    "Whale & On-chain": "고래·온체인 분석",
    "Trump Crypto Policy": "트럼프 암호화폐 정책",
    "Trump Economy": "트럼프 경제 정책",
    "트럼프 경제정책 KR": "트럼프 경제정책",
    "이재명 경제정책": "이재명 경제정책",
    "이재명 암호화폐정책": "이재명 암호화폐정책",
    "이재명 부동산·금리": "이재명 부동산·금리",
    "Fed Policy": "연준 통화정책",
    "한국은행 금리정책": "한국은행 금리정책",
    "한국증시 수급": "한국증시 수급",
    "r/CryptoCurrency": "Reddit 암호화폐",
    "r/Bitcoin": "Reddit 비트코인",
    "r/EthTrader": "Reddit 이더리움",
    "r/WallStreetBets": "Reddit 월스트리트벳",
    "r/Stocks": "Reddit 주식",
    "r/Investing": "Reddit 투자",
    "r/DeFi": "Reddit 디파이",
    "Google News": "구글 뉴스",
}


def _get_source_label(source: str, context_map: Dict[str, str]) -> str:
    """Get a Korean label for a source name."""
    return context_map.get(source, source)


# ---------------------------------------------------------------------------
# Entity extraction constants
# ---------------------------------------------------------------------------

# Common English words that should not be treated as proper-noun entities
_COMMON_WORDS = {
    "The",
    "And",
    "For",
    "With",
    "Has",
    "Are",
    "Its",
    "But",
    "How",
    "Why",
    "What",
    "New",
    "All",
    "Can",
    "Now",
    "Get",
    "Set",
    "May",
    "Not",
    "Other",
    "Others",
    "Another",
    "Being",
    "Having",
    "Doing",
    "Becomes",
    "Become",
    "Getting",
    "Going",
    "Coming",
    "Making",
    "Says",
    "Said",
    "Warns",
    "Faces",
    "Shows",
    "Finds",
    "Takes",
    "Gives",
    "Looks",
    "Tells",
    "Seems",
    "Turns",
    "Leads",
    "Holds",
    "Spikes",
    "Spike",
    "Surges",
    "Surge",
    "Drops",
    "Drop",
    "Falls",
    "First",
    "Last",
    "Next",
    "After",
    "Before",
    "During",
    "Under",
    "Over",
    "About",
    "Every",
    "Where",
    "Which",
    "While",
    "Their",
    "These",
    "Those",
    "Could",
    "Would",
    "Should",
    "Might",
    "Still",
    "Just",
    "Also",
    "More",
    "Most",
    "Some",
    "Much",
    "Many",
    "Each",
    "Only",
    "Even",
    "Very",
    "Here",
    "There",
    "Then",
    "Than",
    "Into",
    "From",
    "This",
    "That",
    "Been",
    "Were",
    "Will",
    "Your",
    "They",
    "Them",
    "Such",
    "Like",
    "Near",
    "Amid",
    "Ahead",
    "Along",
    "Among",
    "Above",
    "Below",
    "Behind",
    "Between",
    "Through",
    "Against",
    "Within",
    "Without",
    "Across",
    "Inside",
    "Global",
    "World",
    "Major",
    "Latest",
    "Breaking",
    "Live",
    "Watch",
    "Alert",
    "Update",
    "Report",
    "Check",
    "Shares",
    "Stock",
    "Stocks",
    "Market",
    "Markets",
    "Price",
    "Prices",
    "Trade",
    "Trades",
    "Trading",
    "Company",
    "Companies",
    "Industry",
    "Million",
    "Billion",
    "Trillion",
    "Today",
    "Yesterday",
    "Tomorrow",
    "Year",
    "Week",
    "Month",
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
    "Better",
    "Bigger",
    "Lower",
    "Higher",
    "Early",
    "Late",
    "Huge",
    "Massive",
    "Record",
    "Rising",
    "Falling",
    "Since",
    "Until",
    "Whether",
    "Biggest",
    "Worst",
    "Best",
    "Headed",
    "Heads",
    "Keep",
    "Keeps",
    "Stayed",
    "Stays",
    "Stay",
    "Worse",
    "Linked",
    "Issues",
    "Issue",
    "Based",
    "Using",
    "Asked",
    "Asking",
    "Called",
    "Calls",
    "Named",
    "Known",
    "Seen",
    "Taken",
    "Given",
    "Several",
    "Certain",
    "Entire",
    "Recent",
    "Little",
    "Large",
    "Small",
    "Long",
    "Short",
    "Full",
    "Half",
    "Wants",
    "Needs",
    "Tries",
    "Three",
    "Four",
    "Five",
}

# Uppercase sequences that look like tickers but are not meaningful financial symbols
_NOISE_TICKER_SYMBOLS = {
    "CEO",
    "IPO",
    "SEC",
    "FED",
    "GDP",
    "CPI",
    "ETF",
    "AI",
    "US",
    "UK",
    "EU",
    "USD",
    "FOR",
    "THE",
    "ARE",
    "HAS",
    "NOT",
    "BUT",
    "ALL",
    "CAN",
    "NOW",
    "HOW",
    "NEW",
    "CBS",
    "FBI",
    "GOP",
    "DHS",
    "RFK",
    "ITS",
    "WAS",
    "HIS",
    "HER",
    "WHO",
    "MAY",
    "BIG",
    "TOP",
    "TWO",
    "OUR",
    "SAY",
    "ANY",
    "FEW",
    "RED",
}


def _extract_raw_patterns(title: str) -> tuple:
    """Run regex extractions on title and return (tickers, values, proper, kr_entities)."""
    tickers = re.findall(r"\b[A-Z]{2,5}\b", title)
    values = re.findall(r"\$[\d,.]+[KkMmBbTt]?|\d+(?:\.\d+)?%", title)
    kr_entities = re.findall(r"[가-힣]{2,}", title)
    proper = re.findall(r"\b[A-Z][a-z]{2,}\b", title)
    return tickers, values, proper, kr_entities


def _filter_entities(tickers: list, proper: list) -> tuple:
    """Filter noise from ticker and proper-noun lists."""
    clean_tickers = [t for t in tickers if t not in _NOISE_TICKER_SYMBOLS]
    clean_proper = [w for w in proper if w not in _COMMON_WORDS]
    return clean_tickers, clean_proper


def _dedup_entities(entities: list) -> list:
    """Deduplicate entity list while preserving insertion order (case-insensitive)."""
    seen: set = set()
    deduped = []
    for e in entities:
        if e.lower() not in seen:
            seen.add(e.lower())
            deduped.append(e)
    return deduped


def _extract_title_entities(title: str) -> list:
    """Extract meaningful entities (names, tickers, numbers) from title."""
    tickers, values, proper, kr_entities = _extract_raw_patterns(title)
    tickers, proper = _filter_entities(tickers, proper)

    entities: list = []
    entities.extend(values)
    entities.extend(tickers[:2])
    entities.extend(proper[:2])
    entities.extend(kr_entities[:3])
    return _dedup_entities(entities)


def _analyze_title_content(title: str) -> str:
    """Generate an analytical Korean description from a news title.

    Instead of generic templates, this produces a title-derived summary
    that explains what the article is about and why it matters.
    """
    title_lower = title.lower()
    title_stripped = title.strip()

    # --- Korean title: extract meaning and add context ---
    kr_chars = len(re.findall(r"[가-힣]", title_stripped))
    if kr_chars > len(title_stripped) * 0.3:
        return _analyze_korean_title(title_stripped)

    # --- English title: translate key concepts and add analysis ---
    return _analyze_english_title(title_stripped, title_lower)


# ---------------------------------------------------------------------------
# Keyword -> fixed description mapping for Korean title analysis.
# Each entry is (keywords, description_string). Categories that require
# dynamic content (pct extraction, clean title) are handled inline below.
# ---------------------------------------------------------------------------
_KOREAN_TITLE_CATEGORIES: Dict[str, str] = {
    # Surge / rebound
    "급등|폭등|반등": "시장 반등 관련 보도.",
    # Geopolitical risk
    "전쟁|분쟁|군사|이란|중동": "지정학적 리스크 관련 보도.",
    # Monetary policy
    "금리|금통위|한은|한국은행": "한국은행 통화정책 관련 보도.",
    # FX
    "환율|원달러|원화": "환율 변동 관련 보도.",
    # Market fraud / delisting
    "상장폐지|주가조작|불공정거래": "불공정거래 관련 보도.",
    # Market rules
    "거래시간|제도|규정": "증시 제도 변경 관련 보도.",
    # Valuation bubble
    "버블|과열|밸류에이션": "시장 밸류에이션 관련 보도.",
    # Bio / pharma
    "바이오|제약": "바이오·제약 섹터 관련 보도.",
    # IPO / listing
    "IPO|공모|상장": "IPO·신규 상장 관련 보도.",
    # Oil / energy
    "유가|원유|석유": "유가 변동 관련 보도.",
    # Trade / tariffs
    "관세|무역|수출|수입": "통상·무역 정책 관련 보도.",
    # Dividends / buybacks
    "배당|주주환원|자사주": "배당·주주환원 정책 관련 보도.",
    # Real estate
    "부동산|아파트|전세|분양": "부동산 시장 관련 보도.",
    # M&A
    "인수|합병|M&A": "기업 인수·합병(M&A) 관련 보도.",
}

# Pre-compiled keyword sets derived from _KOREAN_TITLE_CATEGORIES for O(1) lookup
_KOREAN_TITLE_KW_SETS: list = [(frozenset(k.split("|")), v) for k, v in _KOREAN_TITLE_CATEGORIES.items()]


def _analyze_korean_title(title: str) -> str:
    """Analyze a Korean news title and generate a fact-based description.

    Produces clean, factual descriptions based on the title content
    rather than speculative or template-heavy commentary.
    """
    clean = re.sub(r"\s*[-–—|]\s*\S+$", "", title).strip()
    pct = re.search(r"(\d+(?:\.\d+)?)\s*%", title)
    amount = re.search(r"(\d[\d,.]*)\s*(?:억|조|만|원|달러)", title)
    kr_entities = re.findall(r"[가-힣]{2,}", title)[:3]

    # Build context suffix from extracted data
    context_parts = []
    if pct:
        context_parts.append(f"{pct.group(1)}% 변동")
    if amount:
        context_parts.append(f"{amount.group(0)}")
    context_suffix = f" ({', '.join(context_parts)})" if context_parts else ""

    # Circuit breaker / market crash
    if any(kw in title for kw in ["서킷브레이커", "사이드카"]):
        trigger = "매수 사이드카" if "매수" in title else "서킷브레이커/사이드카"
        return f"{clean[:120]}. {trigger} 발동{context_suffix}."

    # Crash / panic
    if any(kw in title for kw in ["폭락", "급락", "패닉"]):
        return f"{clean[:120]}.{context_suffix} 급락 관련 보도."

    # Semiconductor
    if any(kw in title for kw in ["삼성전자", "하이닉스", "반도체"]):
        return f"{clean[:120]}.{context_suffix} 반도체 섹터 보도."

    # Fixed-response categories via dict table
    for kw_set, category_label in _KOREAN_TITLE_KW_SETS:
        if any(kw in title for kw in kw_set):
            return f"{clean[:120]}.{context_suffix} {category_label}"

    # Crypto majors
    if any(kw in title for kw in ["비트코인", "이더리움", "알트코인", "리플"]):
        return f"{clean[:120]}.{context_suffix} 암호화폐 시장 보도."

    # DeFi / digital assets
    if any(kw in title for kw in ["디파이", "디지털자산", "가상자산", "코인", "블록체인"]):
        return f"{clean[:120]}.{context_suffix} 디지털 자산 보도."

    # AI / tech
    if any(kw in title for kw in ["AI", "인공지능", "챗봇", "생성형"]):
        return f"{clean[:120]}.{context_suffix} AI 산업 보도."

    # EV / battery
    if any(kw in title for kw in ["2차전지", "배터리", "전기차", "EV"]):
        return f"{clean[:120]}.{context_suffix} 전기차·배터리 보도."

    # Foreign / institutional flow
    if any(kw in title for kw in ["외국인", "기관", "순매수", "순매도", "수급"]):
        return f"{clean[:120]}.{context_suffix} 수급 동향 보도."

    # Earnings
    if any(kw in title for kw in ["실적", "어닝", "매출", "영업이익"]):
        return f"{clean[:120]}.{context_suffix} 기업 실적 보도."

    # Fallback: use clean title + entity context
    if kr_entities:
        entity_str = ", ".join(kr_entities[:3])
        return f"{clean[:120]}.{context_suffix} 주요 키워드: {entity_str}."
    return clean[:150] if len(clean) > 15 else title


# ---------------------------------------------------------------------------
# Keyword -> fixed suffix mapping for English title analysis.
# Each entry is (keywords, suffix_string). Categories that require dynamic
# content (detail_str injection, extra logic) are handled inline in the
# function body below.
# ---------------------------------------------------------------------------
_ENGLISH_TITLE_CATEGORIES: Dict[str, str] = {
    # Geopolitical risk
    "iran|war|conflict|military|attack": "지정학 관련 보도.",
    # Earnings
    "earning|revenue|profit|guidance|beat|miss": "기업 실적 관련 보도.",
    # Fed / monetary policy
    "fed|fomc|powell|rate cut|rate hike": "연준 통화정책 관련 보도.",
    # Trump / policy
    "trump|white house|executive order|tariff": "정책 관련 보도.",
    # Crypto majors — no suffix (title alone)
    "bitcoin|btc|crypto|ethereum|altcoin": "",
    # AI / semiconductors — no suffix (title alone)
    "ai |artificial intelligence|nvidia|semiconductor|chip": "",
    # Precious metals — no suffix (title alone)
    "gold|silver|precious": "",
}

# Pre-compiled keyword sets derived from _ENGLISH_TITLE_CATEGORIES for O(1) lookup
_ENGLISH_TITLE_KW_SETS: list = [(frozenset(k.split("|")), v) for k, v in _ENGLISH_TITLE_CATEGORIES.items()]


def _analyze_english_title(title: str, title_lower: str) -> str:
    """Analyze an English news title and generate a specific Korean description."""
    _subj = _extract_title_entities(title)
    # Use only named entities (not raw numbers/prices) for the subject prefix
    _named = [e for e in _subj if not re.match(r"^[\d$,.%+\-]+$", e)]

    # Extract numbers/percentages/prices from title for specificity
    pct_match = re.search(r"(\d[\d,.]*)\s*%", title)
    # Full-word units allow a leading space ("$80 thousand"); single-letter
    # units must be immediately adjacent ("$73K"). Word units are matched first
    # so the "t" in "thousand" is never mistaken for a trillion suffix, and the
    # letter alt has no leading \s* so "$73 Kelvin" stays "$73" (not "$73K").
    # No trailing \b: "$5MM" still degrades to "$5M" instead of dropping detail.
    price_match = re.search(
        r"\$(\d[\d,.]*(?:\.\d+)?)"
        r"(?:\s*(trillion|billion|million|thousand)s?|([KMBT]))?",
        title,
        re.IGNORECASE,
    )
    points_match = re.search(r"(\d[\d,.]*)\s*(?:points?|pts?)", title, re.IGNORECASE)

    # Clean title: remove trailing source names for use as base description
    clean_title = re.sub(
        r"\s*[-–—|]\s*(?:Reuters|Bloomberg|CNBC|AP|MarketWatch|CoinDesk|Cointelegraph|TradingView|Yahoo Finance|The Motley Fool|Investopedia)\s*$",
        "",
        title,
        flags=re.IGNORECASE,
    ).strip()
    # Also remove generic trailing patterns (require a space before separator to avoid
    # matching hyphenated words like "All-Time")
    clean_title = re.sub(r"\s+[–—|]\s*[A-Z][\w\s]{2,20}$", "", clean_title).strip()

    # Build detail string from extracted numbers
    detail_parts = []
    if pct_match:
        detail_parts.append(f"{pct_match.group(1)}% 변동")
    if price_match:
        # Normalize the magnitude suffix to a canonical single letter so the
        # extracted detail never contradicts the full number in the body text
        # (e.g. "$73K" — not a misleading "$73" — for a "$73,000" article).
        _word_unit = (price_match.group(2) or "").lower()
        _letter_unit = (price_match.group(3) or "").upper()
        unit = {"trillion": "T", "billion": "B", "million": "M", "thousand": "K"}.get(_word_unit, _letter_unit)
        detail_parts.append(f"${price_match.group(1)}{unit}")
    if points_match:
        detail_parts.append(f"{points_match.group(1)}포인트")
    detail_str = ", ".join(detail_parts)

    # Determine event category and add specific context

    # Build extra context from extracted numbers
    extra = f" ({detail_str})" if detail_str else ""

    # --- Dynamic categories: inject detail_str into result ---
    if any(kw in title_lower for kw in ["crash", "plunge", "tumble", "sink", "slump", "dive"]):
        return f"{clean_title[:120]}.{extra} 급락 관련 보도."

    if any(kw in title_lower for kw in ["rally", "surge", "soar", "jump", "climb", "gain"]):
        return f"{clean_title[:120]}.{extra} 상승 관련 보도."

    if any(kw in title_lower for kw in ["drop", "fall ", "decline", "down ", "lower", "slip"]):
        return f"{clean_title[:120]}.{extra}"

    if any(kw in title_lower for kw in ["rise", "up ", "higher", "advance"]):
        return f"{clean_title[:120]}.{extra}"

    if any(kw in title_lower for kw in ["oil", "crude", "brent", "wti"]):
        return f"{clean_title[:120]}.{extra} 유가 관련 보도."

    if any(kw in title_lower for kw in ["s&p", "nasdaq", "dow", "futures", "stock market"]):
        return f"{clean_title[:120]}.{extra}"

    # --- Fixed-suffix categories via dict table ---
    for kw_set, suffix in _ENGLISH_TITLE_KW_SETS:
        if any(kw in title_lower for kw in kw_set):
            return f"{clean_title[:120]}.{extra}" if not suffix else f"{clean_title[:120]}.{extra} {suffix}"

    # Default: use cleaned title with entity context
    _meaningful = [e for e in _named if len(e) > 2]
    if _meaningful:
        subj = ", ".join(_meaningful[:2])
        return f"{clean_title[:120]}.{extra} {subj} 관련 보도."
    if detail_str:
        return f"{clean_title[:120]}.{extra}"
    return f"{clean_title[:140]}." if len(clean_title) > 15 else title


def generate_synthetic_description(
    title: str,
    source: str,
    context_map: Optional[Dict[str, str]] = None,
) -> str:
    """Generate a contextual description when RSS provides none.

    Uses title content analysis to produce meaningful, specific summaries
    instead of generic template-based descriptions.
    """
    # Try title-based analysis first (produces specific, analytical content)
    analysis = _analyze_title_content(title)
    if analysis and analysis != title and len(analysis) > 20:
        return analysis

    # Fallback: build a title-derived description with source context
    label = _get_source_label(source, context_map or {})
    entities = _extract_title_entities(title)
    entity_str = ", ".join(entities[:3]) if entities else ""

    # Exchange-specific fallback
    if any(kw in source.lower() for kw in ["binance", "bybit", "okx", "upbit"]):
        return f"{label} 공지. " + (f"{entity_str} 관련." if entity_str else f"{title[:80]}.")

    # Build a title-condensed description instead of boilerplate
    # Clean trailing source names from the title
    clean_title = re.sub(r"\s*[-–—|]\s*\S+$", "", title).strip()
    # For Korean titles, extract a condensed version
    kr_chars = len(re.findall(r"[가-힣]", clean_title))
    if kr_chars > len(clean_title) * 0.3:
        core = clean_title[:80] if len(clean_title) > 80 else clean_title
        if entity_str:
            return f"{core}. {entity_str} 관련 보도."
        return f"{core}."

    # English: use cleaned title with source context
    if label and label != source:
        return f"{label} 보도. {clean_title[:100]}"
    return clean_title[:150] if len(clean_title) > 15 else title


def _extract_overlap_keywords(title: str, text: str) -> tuple[set, set]:
    """Extract normalized keyword sets from title and text for relevance scoring."""
    title_tokens = set(re.findall(r"[A-Za-z0-9$%]{3,}|[가-힣]{2,}", title.lower()))
    text_tokens = set(re.findall(r"[A-Za-z0-9$%]{3,}|[가-힣]{2,}", text.lower()))
    return title_tokens, text_tokens


def _is_title_related_description(title: str, desc: str) -> bool:
    """Return True if description appears related to title content."""
    if not title or not desc:
        return True
    # Backward-compatible: do not aggressively reject when title itself is weak.
    if len(title.strip()) < 18:
        return True
    if _is_desc_duplicate_of_title(desc, title):
        return True

    title_tokens, desc_tokens = _extract_overlap_keywords(title, desc)
    if not title_tokens or not desc_tokens:
        return True

    if title_tokens & desc_tokens:
        return True

    title_entities = {e.lower() for e in _extract_title_entities(title)}
    if len(title_entities) < 2 and len(title_tokens) < 3:
        return True
    if title_entities and not (title_entities & desc_tokens):
        return False
    return True


def _is_desc_duplicate_of_title(desc: str, title: str) -> bool:
    """Return True if desc is essentially a duplicate of title (no extra info).

    Checks:
    - Normalized text equality (lowercase, stripped punctuation/whitespace)
    - desc contains >= 80% of title characters
    - desc length < 1.3x title length (insufficient additional info)
    - Word-token Jaccard similarity > 0.7
    """
    if not desc or not title:
        return False

    # Normalize: lowercase, remove punctuation and whitespace
    norm_desc = _NORM_RE.sub("", desc.lower())
    norm_title = _NORM_RE.sub("", title.lower())

    # Exact normalized match
    if norm_desc == norm_title:
        return True

    # Sequence-based similarity: catches near-duplicates without false positives
    # from bag-of-characters approach
    if norm_title and len(norm_title) > 5:
        ratio = SequenceMatcher(None, norm_desc, norm_title).ratio()
        if ratio > 0.8 and len(norm_desc) < len(norm_title) * 1.3:
            return True

    # Word-token Jaccard similarity (skip for very short titles to avoid noise)
    desc_tokens = set(desc.lower().split())
    title_tokens = set(title.lower().split())
    union = desc_tokens | title_tokens
    if len(union) >= 4:
        intersection = desc_tokens & title_tokens
        if len(intersection) / len(union) > 0.7:
            return True

    return False
