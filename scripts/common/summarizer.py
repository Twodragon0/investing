"""Keyword-based theme summarizer for collected news items.

Classifies news items into predefined themes using keyword matching
and generates markdown summary sections including:
- Issue distribution ASCII bar chart
- Theme-based news grouping with articles per theme
- Top keyword analysis

No LLM or external dependencies required.
"""

import json
import logging
import os
import re
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

from .enrichment import is_logo_like_url
from .markdown_utils import html_source_tag, markdown_link
from .post_generator import _MISTRANSLATION_FIXES
from .themes import (  # noqa: F401  (BAR_WIDTH re-exported for backward compat)
    _THEME_NAME_KEYWORDS,
    ARTICLES_PER_THEME,
    BAR_WIDTH,
    OVERFLOW_PREVIEW_LIMIT,
    THEMES,
    TOP_THEMES_COUNT,
)
from .utils import truncate_sentence as _truncate_sentence_util

logger = logging.getLogger(__name__)


_SEVERITY_HIGH_KW = [
    "crash",
    "surge",
    "record",
    "halt",
    "warn",
    "폭락",
    "급등",
    "급락",
    "사상최",
    "최고치",
    "최저치",
    "긴급",
    "속보",
    "전쟁",
    "war",
    "bomb",
    "attack",
    "sanction",
    "ban",
    "default",
    "bankruptcy",
    "파산",
    "fraud",
    "sec ",
    "fda ",
    "fed ",
    "fomc",
    "금리",
    "인상",
    "인하",
    "breaking",
    "crisis",
    "위기",
]
_SEVERITY_LOW_KW = [
    "opinion",
    "column",
    "editorial",
    "인터뷰",
    "리뷰",
    "review",
    "guide",
    "가이드",
    "tip",
    "팁",
    "예정",
    "계획",
]


def _classify_news_severity(title: str, description: str = "") -> str:
    """Classify news severity as high/medium/low based on keywords."""
    text = (title + " " + description).lower()
    if any(kw in text for kw in _SEVERITY_HIGH_KW):
        return "high"
    if any(kw in text for kw in _SEVERITY_LOW_KW):
        return "low"
    return "medium"


_SEV_BADGE_HTML = {
    "high": '<span class="news-severity news-severity-high">HIGH</span>',
    "medium": '<span class="news-severity news-severity-med">MED</span>',
    "low": '<span class="news-severity news-severity-low">LOW</span>',
}


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


def _generate_title_based_desc(title: str, theme_key: str) -> str:
    """Generate a short analytical description from the news title and theme.

    Extracts key entities (company names, numbers, percentages) from the title
    and builds a title-specific Korean description instead of generic boilerplate.
    Returns empty string if the title is too short to generate useful content.
    """
    if len(title) < 10:
        return ""

    # 테마별 분석적 컨텍스트 (짧은 맥락 설명)
    _THEME_CONTEXT = {
        "bitcoin": "비트코인 시장 심리와 가격 흐름에 주목하세요.",
        "ethereum": "이더리움 생태계의 기술적 발전을 반영합니다.",
        "altcoin": "알트코인 순환매 여부를 판단하는 데 참고하세요.",
        "regulation": "규제 방향이 시장 구조를 바꿀 수 있습니다.",
        "price": "단기 트레이딩 관점에서 주요 변동 요인입니다.",
        "price_market": "시장 모멘텀과 투자 심리를 반영하는 핵심 지표입니다.",
        "defi": "탈중앙 금융 프로토콜의 TVL과 수익률에 주목하세요.",
        "nft": "디지털 자산 시장의 문화적·경제적 트렌드를 보여줍니다.",
        "nft_web3": "Web3 생태계의 채택률과 사용자 경험 변화를 주시하세요.",
        "exchange": "거래소 정책 변화는 유동성과 접근성에 직결됩니다.",
        "macro": "거시경제 흐름이 위험자산 선호도를 좌우합니다.",
        "ai_tech": "AI 기술 혁신이 산업 전반의 투자 기회를 창출합니다.",
        "politics": "정치적 결정이 시장 불확실성의 핵심 변수로 작용합니다.",
        "security": "보안 사고는 시장 신뢰도와 자산 가격에 즉각적 영향을 줍니다.",
        "stock_market": "주요 종목의 실적과 밸류에이션 변화를 분석하세요.",
        "earnings": "실적 발표가 해당 섹터 전반에 미치는 파급 효과를 주목하세요.",
        "trade_war": "무역 갈등이 공급망과 환율에 미치는 영향을 확인하세요.",
        "energy": "에너지 가격 변동이 인플레이션과 소비에 미치는 연쇄 효과를 주시하세요.",
        "real_estate": "부동산 시장의 금리 민감도와 수급 변화를 분석하세요.",
        "labor": "고용 지표가 연준 정책 결정에 미치는 신호를 확인하세요.",
        "geopolitical": "지정학적 리스크가 안전자산 선호도에 미치는 영향을 분석하세요.",
        "cbdc": "중앙은행 디지털 화폐 정책이 기존 금융 시스템에 미치는 변화를 주시하세요.",
        "mining": "채굴 난이도와 해시레이트 변화가 네트워크 보안에 미치는 영향입니다.",
        "stablecoin": "스테이블코인 유통량 변화가 시장 유동성의 선행 지표로 작용합니다.",
    }

    # Extract key entities from title for specificity
    tickers = re.findall(r"\b[A-Z]{2,5}\b", title)
    _NOISE = {
        "CEO",
        "IPO",
        "SEC",
        "FED",
        "GDP",
        "CPI",
        "ETF",
        "AI",
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
        "RSS",
        "API",
    }
    tickers = [t for t in tickers if t not in _NOISE][:2]
    values = re.findall(r"\$[\d,.]+[KkMmBbTt]?|\d+(?:\.\d+)?%", title)[:2]
    kr_nouns = re.findall(r"[가-힣]{2,}", title)[:3]

    # Build entity string for specificity
    key_parts = values + tickers + kr_nouns
    entity_str = ", ".join(key_parts[:3]) if key_parts else ""

    # Check if title is already Korean
    has_korean = bool(re.search(r"[가-힣]", title))
    if has_korean:
        # Korean title: condense and add entity-specific context
        clean = re.sub(r"\s*[-–—|]\s*\S+$", "", title).strip()
        ctx = _THEME_CONTEXT.get(theme_key, "")
        if len(clean) > 80:
            clean = clean[:77] + "..."
        if entity_str and ctx:
            return f"{clean}. {ctx}"
        if ctx:
            return f"{clean}. {ctx}"
        return clean

    # English title: build entity-rich Korean description
    # Remove source suffix (expanded list)
    clean = re.sub(
        r"\s*[-–—|]\s*(?:Reuters|Bloomberg|CNBC|CNN|BBC|AP|Forbes|WSJ"
        r"|MarketWatch|Yahoo\s*Finance|The\s*(?:Block|Verge|Guardian)"
        r"|Decrypt|CoinDesk|CoinTelegraph|Barron'?s)\s*$",
        "",
        title,
        flags=re.I,
    ).strip()
    if len(clean) > 120:
        clean = clean[:117] + "..."

    ctx = _THEME_CONTEXT.get(theme_key, "시장 참여자들이 주목하는 소식입니다.")
    if entity_str:
        return f"{clean}. {entity_str} — {ctx}"
    return f"{clean}. {ctx}"


_GENERIC_DESC_PATTERNS = [
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


def _is_generic_desc(desc: str) -> bool:
    """Return True if description is a generic/synthetic placeholder with no real info."""
    return any(p.search(desc.strip()) for p in _GENERIC_DESC_PATTERNS)


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


# Noise title patterns to filter out (e.g., SEC page addresses, form names)
_NOISE_TITLE_RE = re.compile(
    r"^(?:"
    r"(?:Washington,?\s*DC\s*\d+)|"  # SEC address
    r"(?:10-[KQ](?:\s|$))|"  # SEC form names
    r"(?:Form\s+\d)|"  # SEC form numbers
    r"(?:SEC\.gov\s*-?\s*SEC\.gov)|"  # SEC.gov self-links
    r"(?:EDGAR\s)|"  # EDGAR system pages
    r"(?:Advertisement\s)|"  # Ad pages
    r"(?:Sponsored\s)|"  # Sponsored content
    r"(?:Subscribe\s)|"  # Subscription pages
    r"(?:Login\s)"  # Login pages
    r")",
    re.IGNORECASE,
)

# Common English finance terms -> Korean translation for keyword display
def _load_en_keyword_ko() -> Dict[str, str]:
    """Load English-to-Korean keyword dictionary from external JSON."""
    json_path = os.path.join(os.path.dirname(__file__), "en_keyword_ko.json")
    try:
        with open(json_path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        logger.warning("en_keyword_ko.json not found, using empty dict")
        return {}


_EN_KEYWORD_KO: Dict[str, str] = _load_en_keyword_ko()

# Cross-theme analysis patterns: (theme_key_a, theme_key_b) -> list of insight templates
# Each template should describe what the co-occurrence means for the market.
CROSS_THEME_INSIGHTS: Dict[Tuple[str, str], List[str]] = {
    ("bitcoin", "price_market"): [
        "비트코인 가격 변동성이 확대되면서 시장 전반의 방향성에 대한 관심이 높아지고 있습니다",
        "비트코인 가격 움직임이 전체 시장 심리를 좌우하는 상황입니다",
        "비트코인과 가격/시장 테마가 동시에 부각되어 트레이딩 기회와 리스크가 공존합니다",
    ],
    ("regulation", "exchange"): [
        "규제 당국의 움직임이 거래소 운영에 직접적인 영향을 미치고 있어 주의가 필요합니다",
        "거래소 관련 규제 강화 신호가 감지되고 있으며, 상장/상폐 이슈에 유의해야 합니다",
        "규제와 거래소 테마가 동시에 부각되어 거래 환경 변화 가능성이 있습니다",
    ],
    ("regulation", "politics"): [
        "정치적 결정이 규제 방향에 영향을 주고 있어, 정책 변화를 면밀히 모니터링해야 합니다",
        "정치권의 암호화폐 관련 입장 변화가 규제 환경에 파급 효과를 줄 수 있습니다",
        "정치/정책과 규제 테마가 맞물리며 법적 프레임워크 변화 가능성이 제기됩니다",
    ],
    ("bitcoin", "regulation"): [
        "비트코인 관련 규제 동향이 가격과 시장 구조에 영향을 미칠 수 있습니다",
        "비트코인 ETF, 채굴 규제 등 제도권 편입 관련 이슈가 동시에 부각되고 있습니다",
        "규제 당국의 비트코인 관련 정책 변화에 시장이 민감하게 반응할 수 있습니다",
    ],
    ("defi", "security"): [
        "DeFi 프로토콜의 보안 취약점이 부각되고 있어, 스마트 컨트랙트 리스크에 주의해야 합니다",
        "DeFi 해킹/보안 이슈가 발생하여 프로토콜 안전성에 대한 점검이 필요합니다",
        "DeFi 성장과 함께 보안 위협도 증가하고 있어 리스크 관리가 중요합니다",
    ],
    ("macro", "price_market"): [
        "금리/경제 지표 변화가 시장 가격에 직접적인 영향을 미치는 국면입니다",
        "매크로 환경 변화가 위험자산 전반의 가격 움직임을 주도하고 있습니다",
        "거시경제 이벤트와 시장 가격이 밀접하게 연동되고 있어 경제 지표 발표에 주목해야 합니다",
    ],
    ("macro", "bitcoin"): [
        "거시경제 흐름이 비트코인 가격에 영향을 미치는 구간입니다",
        "금리/인플레이션 관련 이슈가 비트코인 투자 심리에 파급되고 있습니다",
        "연준/중앙은행 정책이 비트코인을 포함한 위험자산 전반에 영향을 주고 있습니다",
    ],
    # 이더리움-DeFi 연계 분석
    ("ethereum", "defi"): [
        "이더리움 생태계와 DeFi 프로토콜의 동반 성장이 가속화되고 있습니다",
        "이더리움 업그레이드가 DeFi TVL과 유동성 구조에 직접적인 영향을 미칩니다",
        "L2 확장과 DeFi 혁신이 이더리움 수요를 견인하는 핵심 동력입니다",
    ],
    # 거래소 보안 이슈
    ("security", "exchange"): [
        "거래소 보안 사고가 발생하여 자산 자기 보관의 중요성이 다시 부각됩니다",
        "보안 취약점이 거래소 유동성과 사용자 신뢰에 즉각적인 타격을 줄 수 있습니다",
        "거래소 해킹 관련 뉴스 집중 시 출금 지연 및 서비스 중단 가능성에 유의해야 합니다",
    ],
    ("ai_tech", "price_market"): [
        "AI/기술 섹터의 뉴스가 관련 토큰 및 주식 가격에 영향을 미치고 있습니다",
        "AI 관련 기술 발전이 시장에서 새로운 투자 테마로 주목받고 있습니다",
        "AI/반도체 테마가 시장 가격과 연동되어 기술주 흐름에 주의가 필요합니다",
    ],
    # 정치 이벤트와 시장 가격 연동
    ("politics", "price_market"): [
        "정치적 이벤트가 시장 가격에 직접 영향을 미치고 있어 정세 변화에 주의가 필요합니다",
        "정치 리스크가 시장 변동성을 높이는 요인으로 작용하고 있습니다",
        "정책 방향에 따른 시장 가격 변동 가능성에 대비해야 합니다",
    ],
    ("ethereum", "regulation"): [
        "이더리움 관련 규제 논의가 활발해지며 ETH 가격과 DeFi 생태계에 파급 효과가 예상됩니다",
        "이더리움 기반 서비스의 규제 준수 요구가 강화되는 추세입니다",
        "이더리움 증권성 논의와 규제 프레임워크 변화에 시장이 주목하고 있습니다",
    ],
    ("defi", "macro"): [
        "거시경제 환경 변화가 DeFi 수익률과 유동성 구조에 직접적인 영향을 미치고 있습니다",
        "금리 변동이 DeFi 대출·예치 수익률과 경쟁하며 자금 흐름이 재편되고 있습니다",
        "매크로 불확실성이 DeFi 프로토콜의 TVL 변동성을 높이는 요인입니다",
    ],
    ("ai_tech", "regulation"): [
        "AI 기술 관련 규제 움직임이 관련 토큰과 기업에 영향을 줄 수 있습니다",
        "AI 산업 규제 프레임워크 논의가 기술주와 관련 암호화폐 시장에 파급됩니다",
        "인공지능 규제 강화 신호가 AI 토큰 시장의 불확실성을 높이고 있습니다",
    ],
    ("bitcoin", "ai_tech"): [
        "비트코인 채굴의 에너지 효율화에 AI 기술이 접목되는 추세입니다",
        "AI와 비트코인 기술 융합이 새로운 투자 테마로 부상하고 있습니다",
        "AI 인프라 확장과 비트코인 네트워크 성장이 에너지 수요 증가를 견인합니다",
    ],
}

# Risk level descriptions based on P0/P1 counts
RISK_LEVELS = {
    "critical": "시장 긴급 상황이 감지되었습니다. 포트폴리오 점검을 권고합니다.",
    "elevated": "주요 리스크 이벤트가 확인되었습니다. 시장 동향을 면밀히 주시하세요.",
    "moderate": "일부 주의 이벤트가 있으나, 전반적으로 안정적인 상황입니다.",
    "low": "특별한 리스크 이벤트 없이 안정적인 시장 흐름입니다.",
}

# Theme dominant narrative templates
THEME_DOMINANT_NARRATIVES: Dict[str, List[str]] = {
    "bitcoin": [
        "비트코인 관련 이슈가 시장을 주도하고 있습니다",
        "비트코인이 오늘 시장의 핵심 화제입니다",
    ],
    "price_market": [
        "가격 변동과 시장 흐름에 대한 관심이 집중되고 있습니다",
        "시장 가격 움직임이 투자자들의 이목을 끌고 있습니다",
    ],
    "regulation": [
        "규제/정책 관련 뉴스가 시장의 불확실성을 높이고 있습니다",
        "규제 동향이 시장 참여자들의 주요 관심사입니다",
    ],
    "macro": [
        "거시경제 지표와 통화정책이 시장의 주요 변수로 작용하고 있습니다",
        "금리/경제 관련 이슈가 투자 심리에 큰 영향을 미치고 있습니다",
    ],
    "security": [
        "보안/해킹 이슈가 시장 신뢰에 영향을 주고 있습니다",
        "보안 사건이 발생하여 시장 참여자들의 경각심이 높아지고 있습니다",
    ],
    "exchange": [
        "거래소 관련 뉴스가 거래 환경에 영향을 미치고 있습니다",
        "거래소 상장/운영 관련 변동이 주목받고 있습니다",
    ],
    "defi": [
        "DeFi 프로토콜 활동과 TVL 변화가 주요 이슈입니다",
        "탈중앙화 금융 관련 뉴스가 집중되고 있습니다",
    ],
    "ethereum": [
        "이더리움 생태계 업데이트가 시장의 관심을 받고 있습니다",
        "이더리움 관련 기술 발전과 생태계 변화가 진행 중입니다",
    ],
    "politics": [
        "정치적 이슈가 시장에 불확실성을 더하고 있습니다",
        "정치/정책 변화가 투자 환경에 영향을 미칠 수 있습니다",
    ],
    "ai_tech": [
        "AI/기술 관련 뉴스가 시장의 새로운 동력으로 주목받고 있습니다",
        "기술 섹터 변화가 투자 테마에 영향을 주고 있습니다",
    ],
    "nft_web3": [
        "NFT/Web3 관련 활동이 주목받고 있습니다",
        "디지털 자산 및 Web3 생태계 변화가 감지되고 있습니다",
    ],
}

# Priority classification keywords
PRIORITY_KEYWORDS: Dict[str, List[str]] = {
    "P0": [
        "crash",
        "폭락",
        "hack",
        "해킹",
        "executive order",
        "행정명령",
        "rate decision",
        "금리 결정",
        "파산",
        "bankruptcy",
        "emergency",
        "긴급",
        "bank run",
        "뱅크런",
        "exploit",
        "rug pull",
        "circuit breaker",
        "서킷브레이커",
        "사이드카",
        "flash crash",
        "급락",
        "theft",
        "도난",
        "zero-day",
    ],
    "P1": [
        "regulation",
        "규제",
        "etf",
        "approval",
        "fomc",
        "tariff",
        "관세",
        "earnings",
        "실적",
        "sanctions",
        "제재",
        "indictment",
        "기소",
        "sec filing",
        "listing",
        "상장",
        "delisting",
        "상장폐지",
        "인수",
        "acquisition",
        "merger",
        "합병",
        "ipo",
        "antitrust",
        "독점",
        "반독점",
        "settlement",
        "합의",
        "fine",
        "벌금",
        "경고",
        "warning",
    ],
    "P2": [
        "partnership",
        "upgrade",
        "launch",
        "airdrop",
        "report",
        "update",
        "integration",
        "collaboration",
        "제휴",
        "출시",
        "업그레이드",
        "에어드롭",
        "리포트",
        "mainnet",
        "메인넷",
        "testnet",
        "테스트넷",
        "roadmap",
        "로드맵",
        "whitepaper",
        "백서",
        "funding",
        "투자유치",
        "series",
        "시리즈",
    ],
}


def _make_keyword_pattern(keywords: list) -> re.Pattern:
    """Compile a regex that matches each keyword at word boundaries.

    English keywords use ``\\b`` anchors; Korean/mixed keywords use
    negative look-around assertions so that a match is only valid when not
    immediately surrounded by Korean or ASCII letters.
    """
    parts = []
    for kw in keywords:
        escaped = re.escape(kw)
        if re.match(r"^[a-zA-Z]", kw):
            parts.append(r"\b" + escaped + r"\b")
        else:
            parts.append(r"(?<![가-힣a-zA-Z])" + escaped + r"(?![가-힣a-zA-Z])")
    return re.compile("|".join(parts), re.IGNORECASE)


_P0_RE = _make_keyword_pattern(PRIORITY_KEYWORDS["P0"])
_P1_RE = _make_keyword_pattern(PRIORITY_KEYWORDS["P1"])
_P2_RE = _make_keyword_pattern(PRIORITY_KEYWORDS["P2"])


class ThemeSummarizer:
    """Classify news items into themes and generate markdown summary sections."""

    def __init__(self, items: List[Dict[str, Any]]):
        self.items = items
        self._theme_scores: Dict[str, int] = {}
        self._theme_articles: Dict[str, List[Dict[str, Any]]] = {}
        self._scored = False
        self._last_risk_verdict = None

    def _ensure_scored(self):
        """Score themes lazily on first access."""
        if self._scored:
            return
        self._score_themes()
        self._scored = True

    def _score_themes(self):
        """Score each theme by keyword frequency across all items."""
        all_text = " ".join(
            (item.get("title_original", item.get("title", "")) + " " + item.get("description", ""))
            for item in self.items
        ).lower()

        token_freq = Counter(re.findall(r"[a-z가-힣]+", all_text))

        for _theme_name, theme_key, _emoji, keywords in THEMES:
            score = sum(token_freq.get(kw, 0) for kw in keywords)
            for kw in keywords:
                if " " in kw:
                    score += all_text.count(kw)
            self._theme_scores[theme_key] = score

        # Match articles to themes (each article to its best-matching theme)
        article_assigned: Dict[int, str] = {}
        for _theme_name, theme_key, _emoji, keywords in THEMES:
            matched = []
            # Build regex patterns for word-boundary matching on short keywords
            kw_patterns = []
            plain_kw = []
            for kw in keywords:
                if " " in kw or len(kw) >= 4 or re.search(r"[가-힣]", kw):
                    plain_kw.append(kw)
                else:
                    kw_patterns.append(re.compile(r"\b" + re.escape(kw) + r"\b", re.IGNORECASE))
            for idx, item in enumerate(self.items):
                item_text = (
                    item.get("title_original", item.get("title", "")) + " " + item.get("description", "")
                ).lower()
                hit = any(kw in item_text for kw in plain_kw)
                if not hit:
                    item_text_raw = (
                        item.get("title_original", item.get("title", "")) + " " + item.get("description", "")
                    )
                    hit = any(p.search(item_text_raw) for p in kw_patterns)
                if hit:
                    matched.append(item)
                    if idx not in article_assigned:
                        article_assigned[idx] = theme_key
            self._theme_articles[theme_key] = matched

    def get_top_themes(self) -> List[Tuple[str, str, str, int]]:
        """Return top themes as (name, key, emoji, article_count) tuples."""
        self._ensure_scored()
        theme_lookup = {key: (name, emoji) for name, key, emoji, _ in THEMES}
        ranked = sorted(self._theme_scores.items(), key=lambda x: x[1], reverse=True)
        result = []
        for key, score in ranked:
            if score <= 0:
                continue
            name, emoji = theme_lookup.get(key, (key, ""))
            count = len(self._theme_articles.get(key, []))
            if count > 0:
                result.append((name, key, emoji, count))
            if len(result) >= TOP_THEMES_COUNT:
                break
        return result

    def classify_priority(self) -> Dict[str, List[Dict[str, Any]]]:
        """Classify items into priority buckets (P0, P1, P2).

        Returns dict with keys "P0", "P1", "P2" mapping to lists of items.
        Items are matched using word-boundary regex patterns to reduce false
        positives from substring matches (e.g. "crashed" matching "crash").
        Each item is assigned to only its highest priority bucket.
        Title is counted once: translated title takes precedence over original
        to avoid double-counting the same keyword from both fields.
        Identical titles (case-insensitive) are deduplicated within each bucket.
        """
        result: Dict[str, List[Dict[str, Any]]] = {"P0": [], "P1": [], "P2": []}
        assigned: set = set()
        seen_titles: Dict[str, set] = {"P0": set(), "P1": set(), "P2": set()}

        for priority, pattern in [("P0", _P0_RE), ("P1", _P1_RE), ("P2", _P2_RE)]:
            for idx, item in enumerate(self.items):
                if idx in assigned:
                    continue
                # Use translated title when available, fall back to original;
                # count it once to avoid inflating keyword hits via both fields.
                title = item.get("title") or item.get("title_original") or ""
                description = item.get("description") or ""
                text = (title + " " + description).lower()
                if pattern.search(text):
                    # Deduplicate identical titles within the same bucket
                    title_key = title.strip().lower()
                    if title_key and title_key in seen_titles[priority]:
                        assigned.add(idx)
                        continue
                    result[priority].append(item)
                    assigned.add(idx)
                    if title_key:
                        seen_titles[priority].add(title_key)

        return result

    # Color classes for theme distribution bars
    _BAR_COLORS = [
        "bar-fill-orange",
        "bar-fill-blue",
        "bar-fill-purple",
        "bar-fill-green",
        "bar-fill-red",
    ]

    def generate_distribution_chart(self) -> str:
        """Generate HTML progress bars for issue distribution.

        Returns empty string if fewer than 5 items.
        """
        if len(self.items) < 5:
            return ""

        top_themes = self.get_top_themes()
        if not top_themes:
            return ""

        # Use max theme count as denominator for bar width so bars are
        # proportional. Articles can match multiple themes so percentages
        # would be misleading — display counts only.
        max_theme_count = max(c for _, _, _, c in top_themes) or 1

        lines = ['<div class="theme-distribution">']
        for i, (name, _key, emoji, count) in enumerate(top_themes):
            bar_pct = count / max_theme_count * 100
            color = self._BAR_COLORS[i % len(self._BAR_COLORS)]
            lines.append(
                f'<div class="theme-row">'
                f'<span class="theme-label">{emoji} {name}</span>'
                f'<div class="bar-track">'
                f'<div class="{color} bar-fill" style="width:{bar_pct:.0f}%"></div>'
                f"</div>"
                f'<span class="theme-count">{count}건</span>'
                f"</div>"
            )
        lines.append("</div>")
        lines.append("\n*기사는 여러 테마에 중복 집계될 수 있음*\n")
        return "\n".join(lines)

    def generate_themed_news_sections(
        self,
        max_articles: int = ARTICLES_PER_THEME,
        featured_count: int = 3,
    ) -> str:
        """Generate theme-based news sections with cross-theme deduplication.

        Top articles per theme include description summaries in card format.
        Articles already featured (top N) in a previous theme are skipped
        in subsequent themes to avoid repetitive #1 articles.
        Remaining articles are shown in a collapsible <details> block.
        Returns empty string if fewer than 5 items.

        Args:
            max_articles: Maximum total articles to show per theme.
            featured_count: Number of articles to show with full description.
        """
        if len(self.items) < 5:
            return ""

        top_themes = self.get_top_themes()
        if not top_themes:
            return ""

        lines = ["## 테마별 주요 뉴스\n"]

        # Cross-theme dedup: track titles that have been featured (top N)
        # across themes so the same article doesn't appear as #1 everywhere.
        cross_theme_featured: set = set()

        for name, key, emoji, count in top_themes:
            articles = self._theme_articles.get(key, [])
            subtitle = self._generate_theme_subtitle(key, articles)
            lines.append(f"### {emoji} {name} ({count}건)\n")
            if subtitle:
                lines.append(f"*{subtitle}*\n")

            shown = 0
            seen_titles: set = set()
            remaining_links = []
            for article in articles:
                orig_title = article.get("title", "")
                if not orig_title or orig_title in seen_titles:
                    continue
                if _NOISE_TITLE_RE.search(orig_title):
                    continue
                seen_titles.add(orig_title)
                title = _fix_mistranslations(article.get("title_ko") or orig_title)
                link = article.get("link", "")
                source = article.get("source", "")
                description = _fix_mistranslations(
                    (article.get("description_ko") or article.get("description", "")).strip()
                )

                # Skip articles already featured in previous themes
                if shown < featured_count and orig_title in cross_theme_featured:
                    # Demote to remaining links instead
                    remaining_links.append(
                        {
                            "title": title,
                            "link": link,
                            "image": article.get("image", ""),
                            "source": article.get("source", ""),
                        }
                    )
                    continue

                if shown < featured_count:
                    # Build HTML card for featured item
                    num = shown + 1
                    from html import escape as _esc

                    safe_title = _esc(title, quote=True)
                    severity = _classify_news_severity(title, description or "")
                    sev_badge = _SEV_BADGE_HTML[severity]
                    card_parts = [
                        f'<div class="news-card-item news-sev-{severity}">',
                        f'<div class="news-card-num">{num}</div>',
                    ]

                    # Add thumbnail if image available and not a site logo/icon
                    image_url = article.get("image", "")
                    if image_url and not is_logo_like_url(image_url):
                        safe_img = _esc(image_url, quote=True)
                        onerr = "this.parentElement.style.display='none'"
                        card_parts.append(
                            f'<div class="news-card-thumb">'
                            f'<img src="{safe_img}" alt="" loading="lazy"'
                            f' onerror="{onerr}">'
                            f"</div>"
                        )
                    elif link:
                        fav_link = _best_favicon_link(article)
                        fav = _favicon_url(fav_link or link)
                        if fav:
                            safe_fav = _esc(fav, quote=True)
                            card_parts.append(
                                f'<div class="news-card-thumb news-card-thumb--favicon">'
                                f'<img src="{safe_fav}" alt="" loading="lazy">'
                                f"</div>"
                            )

                    card_parts.append('<div class="news-card-body">')
                    card_parts.append(sev_badge)
                    if link:
                        safe_link = _esc(link, quote=True)
                        card_parts.append(
                            f'<a href="{safe_link}" class="news-title"'
                            f' target="_blank" rel="noopener noreferrer">'
                            f"{safe_title}</a>"
                        )
                    else:
                        card_parts.append(f'<span class="news-title">{safe_title}</span>')

                    if description and description != title and not _is_generic_desc(description):
                        # Additional boilerplate check for translated descriptions
                        if not _is_boilerplate_desc(description):
                            desc_text = _truncate_sentence(description, max_len=300)
                            if desc_text:
                                card_parts.append(f'<p class="news-desc">{_esc(desc_text, quote=True)}</p>')
                    else:
                        # Fallback: generate analytical description from title
                        fallback_desc = _generate_title_based_desc(orig_title, key)
                        if fallback_desc:
                            card_parts.append(f'<p class="news-desc">{_esc(fallback_desc, quote=True)}</p>')

                    if source:
                        card_parts.append(html_source_tag(source))

                    card_parts.append("</div>")  # close news-card-body
                    card_parts.append("</div>")  # close news-card-item
                    lines.append("")  # blank line before HTML block
                    lines.append("\n".join(card_parts))
                    lines.append("")  # blank line after HTML block
                    cross_theme_featured.add(orig_title)
                else:
                    remaining_links.append(
                        {
                            "title": title,
                            "link": link,
                            "image": article.get("image", ""),
                            "source": article.get("source", ""),
                        }
                    )

                shown += 1
                # Featured cards stop at max_articles, but keep accumulating
                # remaining_links up to OVERFLOW_PREVIEW_LIMIT so the <details>
                # overflow section renders thumbnails for ~10 items instead of
                # collapsing to a bare "외 N건" stub.
                if shown >= max_articles and len(remaining_links) >= OVERFLOW_PREVIEW_LIMIT:
                    break

            overflow = len([a for a in articles if a.get("title") and a["title"] not in seen_titles])
            remaining_count = len(remaining_links) + overflow
            if remaining_links:
                from html import escape as _esc

                lines.append(
                    f"<details><summary>그 외 {remaining_count}건 보기</summary>"
                    f'<div class="details-content"><ol class="news-overflow-list">'
                )
                for item in remaining_links[:OVERFLOW_PREVIEW_LIMIT]:
                    if isinstance(item, dict):
                        t = _esc(item.get("title", ""), quote=True)
                        lnk = item.get("link", "")
                        img = item.get("image", "")
                        src = item.get("source", "")
                        thumb_html = ""
                        if img and not is_logo_like_url(img):
                            safe_img = _esc(img, quote=True)
                            onerr = "this.parentElement.style.display='none'"
                            thumb_html = (
                                f'<span class="overflow-thumb">'
                                f'<img src="{safe_img}" alt="" loading="lazy"'
                                f' onerror="{onerr}"></span>'
                            )
                        elif lnk:
                            fav_link = _best_favicon_link(item)
                            fav = _favicon_url(fav_link or lnk)
                            if fav:
                                safe_fav = _esc(fav, quote=True)
                                thumb_html = (
                                    f'<span class="overflow-thumb overflow-thumb--favicon">'
                                    f'<img src="{safe_fav}" alt="" loading="lazy">'
                                    f"</span>"
                                )
                        src_html = ""
                        if src:
                            src_html = f'<span class="overflow-source">{_esc(src, quote=True)}</span>'
                        if lnk:
                            safe_link = _esc(lnk, quote=True)
                            lines.append(
                                f'<li class="overflow-preview">'
                                f"{thumb_html}"
                                f'<span class="overflow-body">'
                                f'<a href="{safe_link}" target="_blank" rel="noopener noreferrer">{t}</a>'
                                f"{src_html}</span></li>"
                            )
                        else:
                            lines.append(
                                f'<li class="overflow-preview">'
                                f"{thumb_html}"
                                f'<span class="overflow-body">'
                                f"<span>{t}</span>"
                                f"{src_html}</span></li>"
                            )
                    else:
                        lines.append(f"<li>{item}</li>")
                if remaining_count > OVERFLOW_PREVIEW_LIMIT:
                    lines.append(f"<li><em>...외 {remaining_count - OVERFLOW_PREVIEW_LIMIT}건</em></li>")
                lines.append("</ol></div></details>\n")

            lines.append("")

        return "\n".join(lines)

    # Stop words to exclude from theme briefing keywords
    _STOP_WORDS = {
        # English
        "stock",
        "market",
        "today",
        "will",
        "this",
        "that",
        "with",
        "from",
        "have",
        "been",
        "were",
        "what",
        "when",
        "where",
        "which",
        "while",
        "more",
        "than",
        "also",
        "just",
        "into",
        "over",
        "some",
        "most",
        "here",
        "they",
        "their",
        "them",
        "there",
        "these",
        "those",
        "about",
        "after",
        "before",
        "could",
        "would",
        "should",
        "other",
        "news",
        "says",
        "said",
        "like",
        "amid",
        "near",
        "latest",
        "first",
        "last",
        "next",
        "week",
        "year",
        "days",
        "time",
        "back",
        "still",
        "even",
        "very",
        "much",
        "many",
        "each",
        "every",
        "make",
        "made",
        "does",
        "know",
        "take",
        "come",
        "look",
        "show",
        "close",
        "closes",
        "gains",
        "little",
        "changed",
        "under",
        "posts",
        "surprise",
        "better",
        "despite",
        "price",
        "update",
        "updates",
        "live",
        "report",
        "check",
        "according",
        "following",
        "based",
        "and",
        "the",
        "are",
        "new",
        "but",
        "down",
        "may",
        "set",
        "get",
        "has",
        "had",
        "not",
        "all",
        "can",
        "now",
        "how",
        "why",
        "who",
        "its",
        "our",
        "his",
        "her",
        "per",
        "via",
        "top",
        "two",
        "one",
        "see",
        "use",
        "big",
        "old",
        "own",
        "off",
        "run",
        "try",
        "way",
        "end",
        "let",
        "put",
        "say",
        "too",
        "did",
        "got",
        "hit",
        "low",
        "key",
        "any",
        "yet",
        "ago",
        "day",
        "due",
        "far",
        "few",
        "high",
        "hold",
        "keep",
        "left",
        "long",
        "move",
        "need",
        "open",
        "part",
        "plan",
        "play",
        "push",
        "pull",
        "real",
        "rise",
        "risk",
        "seen",
        "send",
        "sent",
        "sure",
        "tell",
        "test",
        "turn",
        "view",
        "want",
        "well",
        "went",
        "wide",
        "work",
        "help",
        "head",
        "eyes",
        "call",
        "data",
        "full",
        "goes",
        "gone",
        "good",
        "half",
        "hand",
        "hard",
        "line",
        "mark",
        "mean",
        "meet",
        "note",
        "once",
        "only",
        "past",
        "rate",
        "read",
        "rest",
        "role",
        "rule",
        "soon",
        "step",
        "stop",
        "talk",
        "told",
        "true",
        "upon",
        "used",
        "wins",
        "lost",
        "lead",
        "drop",
        "fell",
        "grew",
        "lose",
        "pays",
        "sell",
        "rose",
        "https",
        "unknown",
        "was",
        "your",
        "through",
        "between",
        "such",
        # Korean common
        "관련",
        "이슈",
        "뉴스",
        "시장",
        "오늘",
        "최근",
        "현재",
        "전일",
        "대비",
        "분야",
        "주요",
        "방안부터",
        "전망까지",
        "주요뉴스",
        # Additional English stop words
        "for",
        "you",
        "crypto",
        "cryptocurrency",
        "blockchain",
        "token",
        "tokens",
        "digital",
        "asset",
        "assets",
        "trading",
        "exchange",
        "becomes",
        "become",
        "becoming",
        "others",
        "another",
        "being",
        "having",
        "doing",
        "going",
        "getting",
        "million",
        "billion",
        "trillion",
        "during",
        "without",
        "within",
        "against",
        "really",
        "already",
        "enough",
        "announces",
        "announced",
        "announcement",
        "reports",
        "reported",
        "company",
        "companies",
        "global",
        "world",
        "international",
        "major",
        "breaking",
        "shares",
        "investors",
        "investor",
        "article",
        "source",
        "watch",
        "alert",
        "warns",
        # Additional Korean stop words
        "텔레그램",
        "전송",
        "알려진",
        "보도",
        "발표",
        "설명",
        "정부입장",
        "확정된",
        "바",
        "검토",
        "것으로",
        "있는",
        "따르면",
        "한다",
        "있다",
        "했다",
        "된다",
        "라고",
        "에서",
        "이번",
        "통해",
        "대해",
        "위해",
        "가운데",
        "것이",
        "하는",
        "것을",
        # Korean sentence endings (appearing as keywords)
        "없습니다",
        "있습니다",
        "아닙니다",
        "됩니다",
        "합니다",
        "입니다",
        "했습니다",
        "됐습니다",
        # Korean postpositions / filler
        "대한",
        "따른",
        "관해",
        # Korean reporting verbs
        "선정하였습니다",
        "수용한다는",
        "발표했습니다",
        "밝혔습니다",
        "전했습니다",
        "보도했습니다",
        "보도에",
        # Korean particles / connectors
        "것이다",
        "으로",
        "에게",
        # Korean media names (noise in keywords)
        "서울경제",
        "한겨레",
        "한국경제",
        "뉴시스",
        "연합뉴스",
        "조선일보",
        "중앙일보",
        "한국일보",
        "동아일보",
        "경향신문",
        "매일경제",
        "머니투데이",
        "아시아경제",
    }

    _NOISE_ENGLISH = {
        "becomes",
        "become",
        "becoming",
        "spikes",
        "spike",
        "gets",
        "getting",
        "other",
        "others",
        "another",
        "makes",
        "making",
        "takes",
        "taking",
        "going",
        "coming",
        "shows",
        "showing",
        "looks",
        "looking",
        "gives",
        "giving",
        "being",
        "having",
        "doing",
        "finds",
        "finding",
        "seems",
        "tells",
        "warns",
        "warning",
        "faces",
        "facing",
        "says",
        "might",
        "could",
        "should",
        "would",
        "every",
        "where",
        "which",
        "while",
        "until",
        "since",
        "among",
        "along",
        "above",
        "below",
        "ahead",
        "across",
        "behind",
        "before",
        "during",
        "inside",
    }

    def _extract_title_keywords(self, articles: List[Dict[str, Any]], max_keywords: int = 5) -> List[str]:
        """Extract salient keywords from article titles, excluding stop words.

        Returns up to *max_keywords* unique keywords ordered by frequency.
        Prefers longer / more specific tokens.
        """
        word_counter: Counter = Counter()
        for article in articles[:15]:
            title = article.get("title", "")
            # Extract tokens: English 3+ chars, Korean 2+ chars, numbers with $ or %
            tokens = re.findall(r"\$[\d,.]+[KkMmBb]?%?|[\d,.]+%|[A-Za-z]{3,}|[가-힣]{2,}", title)
            for token in tokens:
                normalized = token.lower() if re.match(r"[A-Za-z]", token) else token
                if re.fullmatch(r"[가-힣]{2,}", token):
                    normalized = re.sub(r"(은|는|이|가|을|를|의|에|와|과|도|만|로|으로)$", "", normalized)
                if (
                    normalized not in self._STOP_WORDS
                    and normalized not in self._NOISE_ENGLISH
                    and len(normalized) >= 2
                ):
                    # Skip short generic English tokens (1-2 chars)
                    if re.match(r"^[a-z]{1,2}$", normalized):
                        continue
                    word_counter[normalized] += 1
        # Sort by frequency desc, then length desc (prefer specific tokens)
        sorted_words = sorted(
            word_counter.items(),
            key=lambda x: (x[1], len(x[0])),
            reverse=True,
        )
        seen_lower: set = set()
        result = []
        for word, _count in sorted_words:
            lower = word.lower()
            if lower not in seen_lower:
                seen_lower.add(lower)
                result.append(word)
            if len(result) >= max_keywords:
                break
        return result

    def _prepare_display_keywords(self, keywords: List[str], max_keywords: int = 3) -> List[str]:
        display: List[str] = []
        seen: set = set()

        for keyword in keywords:
            token = str(keyword).strip().strip(".,:;()[]{}<>\"'")
            if not token:
                continue

            lower = token.lower()
            translated = _EN_KEYWORD_KO.get(lower)

            if re.search(r"[가-힣]", token):
                candidate = token
            elif translated:
                candidate = translated
            elif token.isupper() or lower in {"btc", "eth", "xrp", "etf", "sec", "cpi", "ppi", "fomc", "ipo", "ai"}:
                candidate = token.upper()
            else:
                continue

            normalized = candidate.lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            display.append(candidate)
            if len(display) >= max_keywords:
                break

        return display

    def _generate_single_theme_briefing(self, theme_key: str, articles: List[Dict[str, Any]]) -> str:
        """Generate a keyword-rich 1-line briefing for a single theme.

        Strategy:
        1. Extract top keywords from article titles within this theme.
        2. Combine them into a comma-separated briefing line.
        3. Falls back to the best description snippet if keyword extraction
           yields too few results.
        """
        if not articles:
            return ""

        # Strategy 1: Build keyword-based composite briefing
        keywords = self._extract_title_keywords(articles, max_keywords=7)

        # Filter out keywords that match OTHER theme names (not current theme)
        filtered_kw = []
        for kw in keywords:
            kw_lower = kw.lower()
            # Skip if keyword matches a theme name/key that isn't the current theme
            if kw_lower in _THEME_NAME_KEYWORDS and kw_lower != theme_key.lower():
                # Also allow if it's a substring of the current theme name
                current_theme_name = ""
                for t_name, t_key, _e, _k in THEMES:
                    if t_key == theme_key:
                        current_theme_name = t_name.lower()
                        break
                if kw_lower not in current_theme_name and kw_lower != theme_key:
                    continue
            filtered_kw.append(kw)
        keywords = filtered_kw

        if len(keywords) >= 2:
            display_kw = self._prepare_display_keywords(keywords, max_keywords=3)
            if not display_kw:
                display_kw = keywords[:3]

            kw_str = ", ".join(display_kw)

            # Theme-aware analytical templates
            n_articles = len(articles)
            count_str = f"({n_articles}건)"

            # Theme-specific context for richer summaries
            _THEME_BRIEFING_CTX: dict[str, list[str]] = {
                "bitcoin": [
                    f"{kw_str} 가격 흐름과 온체인 지표 변화를 함께 확인하세요.",
                    f"{kw_str} 관련 {count_str} 보도 — 거래량과 펀딩비 추이에 주목할 구간입니다.",
                    f"{kw_str} 심리 지표가 변동 중이며, 주요 지지·저항선 근접 여부를 점검하세요.",
                ],
                "ethereum": [
                    f"{kw_str} 생태계 동향 {count_str} — 가스비·TVL 변화를 함께 확인하세요.",
                    f"{kw_str} 네트워크 업데이트와 L2 확장이 가격에 미칠 영향을 주시하세요.",
                ],
                "regulation": [
                    f"{kw_str} 규제 움직임 {count_str} — 시장 접근성과 유동성에 직접적 영향이 예상됩니다.",
                    f"{kw_str} 정책 변화가 감지되어, 관련 자산 규제 리스크를 재점검하세요.",
                ],
                "price_market": [
                    f"{kw_str} 가격 변동 {count_str} — 거래량 대비 변동폭을 확인하고 진입 타이밍을 점검하세요.",
                    f"{kw_str} 시장 흐름이 활발하며, 주요 가격대에서의 매물 분포를 살펴보세요.",
                ],
                "ai_tech": [
                    f"{kw_str} 기술 이슈 {count_str} — 반도체·AI 섹터 실적 영향과 밸류에이션을 점검하세요.",
                    f"{kw_str} 테크 동향이 시장 주도주 교체에 영향을 줄 수 있습니다.",
                ],
                "macro": [
                    f"{kw_str} 매크로 변수 {count_str} — 금리·환율 방향성이 자산 배분에 핵심 변수입니다.",
                    f"{kw_str} 거시경제 지표 발표에 따른 시장 변동성 확대에 대비하세요.",
                ],
                "defi": [
                    f"{kw_str} DeFi 동향 {count_str} — TVL 변화와 프로토콜 수익률을 비교 점검하세요.",
                    f"{kw_str} 탈중앙 금융 이슈가 부각되며 유동성 풀 리밸런싱 여부에 주목하세요.",
                ],
                "politics": [
                    f"{kw_str} 정치 이슈 {count_str} — 정책 불확실성이 시장 방향성에 영향을 줄 수 있습니다.",
                    f"{kw_str} 정치적 변수가 투자 심리에 작용하고 있어, 관련 섹터를 점검하세요.",
                ],
                "security": [
                    f"{kw_str} 보안 이슈 {count_str} — 해킹·사기 사건이 시장 신뢰에 미칠 영향을 확인하세요.",
                    f"{kw_str} 보안 사고가 보고되어, 관련 프로토콜·거래소의 대응을 주시하세요.",
                ],
            }

            import datetime as _dt

            today_str = _dt.datetime.now(tz=_dt.UTC).date().isoformat()

            # Try theme-specific template first
            theme_templates = _THEME_BRIEFING_CTX.get(theme_key)
            if theme_templates:
                seed = hash((today_str, theme_key, kw_str))
                return theme_templates[seed % len(theme_templates)]

            # Generic templates (no duplicates, each has distinct angle)
            templates = [
                f"{kw_str} 흐름이 두드러지며, 추세 전환 신호를 주시할 구간입니다.",
                f"{kw_str} 이슈가 부각되며 해당 섹터의 단기 변동성 확대 가능성이 있습니다.",
                f"{kw_str} 관련 불확실성이 커지고 있어 리스크 관리에 유의하세요.",
                f"{kw_str} 관련 보도가 이어지고 있어 관련 포지션 점검이 필요합니다.",
                f"{kw_str} 이슈에 대한 시장 반응을 모니터링할 필요가 있습니다.",
                f"{kw_str} 관련 지표와 수급 흐름을 함께 확인하세요.",
                f"{kw_str} 동향이 포트폴리오 전략에 영향을 줄 수 있어 주시가 필요합니다.",
                f"{kw_str} 이슈가 시장 구조 변화의 신호일 수 있어 심층 분석이 권장됩니다.",
            ]
            # Use theme_key in seed so different themes get different templates
            seed = hash((today_str, theme_key, kw_str))
            return templates[seed % len(templates)]

        # Strategy 2: Best description snippet from top articles
        best_desc = ""
        for article in articles[:5]:
            desc = article.get("description", "").strip()
            title = article.get("title", "")
            text = desc if desc and desc != title and len(desc) > 30 else ""
            if text:
                sentences = re.split(r"(?<=[.!?。])\s+", text)
                snippet = sentences[0] if sentences else text
                if len(snippet) > 150:
                    snippet = snippet[:150].rsplit(" ", 1)[0]
                if len(snippet) > len(best_desc):
                    best_desc = snippet

        if best_desc:
            return best_desc

        # Strategy 3: Use top article title
        for article in articles[:3]:
            title = article.get("title", "").strip()
            if title and len(title) > 15:
                return title

        # Strategy 4: return whatever keywords we have (formatted, not raw dump)
        if keywords:
            return f"주요 키워드: {', '.join(keywords)}"

        return ""

    def _generate_theme_subtitle(self, theme_key: str, articles: List[Dict[str, Any]]) -> str:
        """Generate a subtitle from the best article description for theme headings.

        Unlike _generate_single_theme_briefing which uses keyword analysis,
        this returns a direct description snippet from the top article,
        giving readers a concrete preview of the most important story.
        """
        if not articles:
            return ""

        for article in articles[:5]:
            # Prefer Korean description
            desc = _fix_mistranslations((article.get("description_ko") or article.get("description", "")).strip())
            title = _fix_mistranslations(article.get("title_ko") or article.get("title", ""))
            if not desc or desc == title or len(desc) < 20:
                continue
            if _is_generic_desc(desc):
                continue
            # Extract first sentence
            sentences = re.split(r"(?<=[.!?。다요음])\s+", desc)
            snippet = sentences[0] if sentences else desc
            if len(snippet) > 120:
                snippet = snippet[:117].rsplit(" ", 1)[0] + "..."
            if len(snippet) >= 15:
                return snippet
        return ""

    def generate_theme_briefing(self) -> str:
        """Generate combined theme briefings for all top themes.

        Returns a section with 1-2 sentence briefings per theme,
        based on article descriptions.
        """
        if len(self.items) < 5:
            return ""

        top_themes = self.get_top_themes()
        if not top_themes:
            return ""

        lines = ["## 테마별 브리핑\n"]
        has_content = False

        for name, key, emoji, _count in top_themes:
            articles = self._theme_articles.get(key, [])
            briefing = self._generate_single_theme_briefing(key, articles)
            # Validate briefing is not circular (repeated theme name)
            if briefing and briefing.strip() != name and len(briefing.strip()) > len(name):
                lines.append(f"- {emoji} **{name}**: {briefing}")
                has_content = True

        if not has_content:
            return ""

        lines.append("")
        return "\n".join(lines)

    def generate_summary_section(self) -> str:
        """Generate a concise markdown theme summary section.

        Returns empty string if fewer than 5 items are available.
        """
        if len(self.items) < 5:
            return ""

        top_themes = self.get_top_themes()
        if not top_themes:
            return ""

        total = len(self.items)
        lines = ["\n## 주요 테마 분석\n"]

        for name, key, emoji, count in top_themes:
            articles = self._theme_articles.get(key, [])
            ratio = count / total if total > 0 else 0

            lines.append(f"### {emoji} {name} ({count}건)\n")

            # Analysis sentence with ratio and source breakdown
            analysis_parts = []
            if ratio > 0.4:
                analysis_parts.append(f"전체의 {ratio:.0%}로 압도적 비중을 차지합니다.")
            elif ratio > 0.2:
                analysis_parts.append(f"전체의 {ratio:.0%}로 주요 테마입니다.")
            else:
                analysis_parts.append(f"전체의 {ratio:.0%}입니다.")

            source_counts: Counter = Counter(a.get("source", "") for a in articles if a.get("source"))
            if source_counts:
                top_src = ", ".join(f"{s}({c}건)" for s, c in source_counts.most_common(3))
                analysis_parts.append(f"주요 출처: {top_src}.")

            if analysis_parts:
                lines.append(" ".join(analysis_parts))
                lines.append("")

            shown = 0
            seen_titles: set = set()
            for article in articles:
                title = article.get("title", "")
                if not title or title in seen_titles or len(title.strip()) < 5:
                    continue
                if _NOISE_TITLE_RE.search(title):
                    continue
                seen_titles.add(title)
                link = article.get("link", "")
                source = article.get("source", "")
                desc = article.get("description", "").strip()

                title = _fix_mistranslations(title)
                if link:
                    lines.append(f"- {markdown_link(title, link)} — {source}")
                else:
                    lines.append(f"- {title} — {source}")

                # Add description excerpt (first sentence, up to 150 chars)
                if desc and desc != title and len(desc) > 20 and not _is_generic_desc(desc):
                    desc_short = _fix_mistranslations(_truncate_sentence(desc, max_len=150))
                    if desc_short:
                        lines.append(f"  > {desc_short}")

                shown += 1
                if shown >= 3:
                    break

            lines.append("")

        return "\n".join(lines)

    def _assess_risk_level(self, priority_items: Dict[str, List[Dict[str, Any]]]) -> str:
        """Assess market risk level using weighted impact scoring via risk_classifier.

        Delegates to classify_risk() for score-based verdict, stores the verdict
        in self._last_risk_verdict for top_items access by callers.
        """
        from .risk_classifier import classify_risk  # lazy import

        verdict = classify_risk(
            items=self.items,
            priority_items=priority_items,
        )
        self._last_risk_verdict = verdict
        if logger:
            logger.info(
                "risk_level=%s mean_top3=%.2f rules=%s",
                verdict.level,
                verdict.aggregate_mean,
                verdict.rule_trace,
            )
        return verdict.level

    def _build_narrative_intro(
        self,
        top_themes: List[Tuple[str, str, str, int]],
        priority_items: Dict[str, List[Dict[str, Any]]],
        total: int,
    ) -> str:
        """Build a narrative intro paragraph based on actual news content.

        Uses P0 issues, dominant themes, and cross-theme patterns to construct
        a descriptive opening rather than generic count-based summaries.
        """
        p0_items = priority_items.get("P0", [])
        p1_items = priority_items.get("P1", [])

        # Case 1: P0 urgent issues exist — lead with them
        if p0_items:
            p0_title = _fix_mistranslations(
                p0_items[0].get("title_ko")
                or p0_items[0].get("title_translated")
                or p0_items[0].get("title", "긴급 이슈")
            )
            # Truncate long titles
            if len(p0_title) > 100:
                p0_title = p0_title[:97] + "..."
            intro = f"**긴급**: {p0_title}  \n"
            if len(p0_items) > 1:
                intro += f"외 P0 긴급 이슈 {len(p0_items) - 1}건이 추가 감지되었습니다. "
            intro += f"총 {total}건의 뉴스 중 "
            if p1_items:
                intro += f"P1 주요 이슈도 {len(p1_items)}건 확인됩니다."
            else:
                intro += "긴급 이슈를 중심으로 시장 움직임을 분석합니다."
            return intro

        # Case 2: Strong dominant theme (>40% of articles)
        if top_themes:
            dominant = top_themes[0]
            dominant_ratio = dominant[3] / total if total > 0 else 0
            theme_key = dominant[1]

            if dominant_ratio > 0.4 and theme_key in THEME_DOMINANT_NARRATIVES:
                narratives = THEME_DOMINANT_NARRATIVES[theme_key]
                # Use date+total as seed for daily variety
                import datetime as _dt

                today_str = _dt.datetime.now(tz=_dt.UTC).date().isoformat()
                seed = hash((today_str, total, theme_key))
                idx = seed % len(narratives)
                intro = f"총 {total}건의 뉴스 중 **{dominant[0]}** 관련이 "
                intro += f"{dominant[3]}건({dominant_ratio:.0%})으로 압도적입니다. "
                intro += narratives[idx]
                return intro

        # Case 3: Two themes dominating together — detect cross-theme pattern
        if len(top_themes) >= 2:
            key_a = top_themes[0][1]
            key_b = top_themes[1][1]
            pair = (key_a, key_b)
            pair_rev = (key_b, key_a)
            cross_insights = CROSS_THEME_INSIGHTS.get(pair) or CROSS_THEME_INSIGHTS.get(pair_rev)
            if cross_insights:
                import datetime as _dt

                today_str = _dt.datetime.now(tz=_dt.UTC).date().isoformat()
                seed = hash((today_str, total, pair))
                idx = seed % len(cross_insights)
                intro = (
                    f"총 {total}건의 뉴스에서 "
                    f"**{top_themes[0][0]}**({top_themes[0][3]}건)과 "
                    f"**{top_themes[1][0]}**({top_themes[1][3]}건)이 "
                    f"동시에 부각되고 있습니다. "
                    f"{cross_insights[idx]}"
                )
                return intro

        # Case 4: General multi-theme
        if top_themes and len(top_themes) >= 2:
            theme_names = [f"**{t[0]}**({t[3]}건)" for t in top_themes[:3]]
            intro = (
                f"총 {total}건의 뉴스에서 "
                f"{', '.join(theme_names[:-1])}과 {theme_names[-1]} 순으로 "
                f"많은 보도가 집중되고 있습니다."
            )
            return intro

        # Fallback
        return f"총 **{total}건**의 뉴스가 수집되었습니다."

    def generate_overall_summary_section(
        self,
        extra_data: Optional[Dict[str, Any]] = None,
        title: str = "전체 뉴스 요약",
        total_override: Optional[int] = None,
    ) -> str:
        """Generate a content-aware overall summary section.

        Analyzes P0/P1 issues, dominant themes, and cross-theme patterns
        to produce a narrative summary rather than generic count listings.

        Args:
            total_override: If provided, use this as the total count instead of
                len(self.items). Useful when the opening paragraph already states
                a different count (e.g., pre-dedup count).
        """
        if len(self.items) < 3:
            return ""

        extra = extra_data or {}
        total = total_override if total_override is not None else len(self.items)
        top_themes = self.get_top_themes()
        priority_items = self.classify_priority()

        lines = [f"## {title}\n"]

        # Narrative intro based on actual content analysis
        intro = self._build_narrative_intro(top_themes, priority_items, total)
        lines.append(f"{intro}\n")

        # Theme breakdown with keyword-based briefings
        if top_themes:
            lines.append("### 테마별 동향\n")
            for name, key, emoji, count in top_themes[:3]:
                articles = self._theme_articles.get(key, [])
                snippet = self._generate_single_theme_briefing(key, articles)
                if snippet:
                    lines.append(f"- **{emoji} {name}** ({count}건): {snippet}")
                else:
                    lines.append(f"- **{emoji} {name}**: {count}건 수집")
            lines.append("")

        # Risk assessment
        risk_level = self._assess_risk_level(priority_items)
        if risk_level != "low":
            risk_desc = RISK_LEVELS.get(risk_level, "")
            if risk_desc:
                lines.append(f"**리스크 수준 [{risk_level.upper()}]**: {risk_desc}\n")

        # Priority signal with specific titles
        p0_items = priority_items.get("P0", [])
        p1_items = priority_items.get("P1", [])
        if p0_items:
            lines.append("### 긴급 이슈\n")
            for item in p0_items[:3]:
                p0_title = _fix_mistranslations(
                    item.get("title_ko") or item.get("title_translated") or item.get("title", "")
                )[:100]
                if p0_title:
                    lines.append(f"- {p0_title}")
            lines.append("")
        if p1_items:
            lines.append("### 주요 이슈\n")
            for item in p1_items[:3]:
                p1_title = _fix_mistranslations(
                    item.get("title_ko") or item.get("title_translated") or item.get("title", "")
                )[:80]
                if p1_title:
                    lines.append(f"- {p1_title}")
            if len(p1_items) > 3:
                lines.append(f"- 외 {len(p1_items) - 3}건")
            lines.append("")

        # Investor checkpoint
        checkpoints = []
        top_keywords = extra.get("top_keywords") or []
        if top_keywords:
            kw_names = self._prepare_display_keywords([kw for kw, _ in top_keywords[:5]], max_keywords=3)
            checkpoints.append(f"**핫 키워드**: {', '.join(kw_names)}")

        region_counts = extra.get("region_counts")
        if region_counts:
            regions_str = ", ".join(f"{name} {count}건" for name, count in region_counts.most_common(3))
            if regions_str:
                checkpoints.append(f"**주요 지역**: {regions_str}")

        source_counter = extra.get("source_counter")
        if source_counter:
            top_sources = source_counter.most_common(3)
            if top_sources:
                src_str = ", ".join(f"{name}({count}건)" for name, count in top_sources)
                checkpoints.append(f"**주요 출처**: {src_str}")

        summary_points = extra.get("summary_points") or []
        for point in summary_points[:2]:
            if point:
                checkpoints.append(point)

        if checkpoints:
            lines.append("### 투자자 체크포인트\n")
            for cp in checkpoints:
                lines.append(f"- {cp}")
            lines.append("")

        return "\n".join(lines)

    def _build_executive_opener(
        self,
        category_type: str,
        top_themes: List[Tuple[str, str, str, int]],
        priority_items: Dict[str, List[Dict[str, Any]]],
        total: int,
        extra: Dict[str, Any],
    ) -> str:
        """Build a specific, content-driven opener for the executive summary.

        Prioritizes P0 issues and price data over generic theme listings.
        """
        p0_items = priority_items.get("P0", [])

        # If P0 issues exist, lead with the most urgent one
        if p0_items:
            p0_title = (
                p0_items[0].get("title_ko") or p0_items[0].get("title_translated") or p0_items[0].get("title", "")
            )
            if len(p0_title) > 100:
                # Try to extract key phrase
                keywords = self._prepare_display_keywords(
                    self._extract_title_keywords(p0_items[:1], max_keywords=5),
                    max_keywords=3,
                )
                p0_title = ", ".join(keywords) if keywords else p0_title[:97] + "..."
            prefix = {
                "crypto": "암호화폐",
                "stock": "주식 시장",
                "regulatory": "규제",
                "social": "소셜",
                "security": "보안",
                "market": "시장",
            }.get(category_type, "시장")
            return f"{prefix} 긴급: {p0_title} - {total}건 분석"

        # Use theme keywords for more specific openers
        if top_themes:
            dominant_key = top_themes[0][1]
            dominant_articles = self._theme_articles.get(dominant_key, [])
            top_kws = self._prepare_display_keywords(
                self._extract_title_keywords(dominant_articles, max_keywords=5),
                max_keywords=3,
            )
            kw_str = ", ".join(top_kws[:3]) if top_kws else top_themes[0][0]

            openers = {
                "crypto": f"암호화폐: {kw_str} 중심 {total}건 분석",
                "stock": f"주식 시장: {kw_str} 부각 {total}건 분석",
                "regulatory": f"글로벌 규제: {kw_str} 관련 {total}건 수집",
                "social": f"소셜 트렌드: {kw_str} 관련 {total}건 포착",
                "security": f"보안: {kw_str} 관련 {total}건 보고",
                "market": f"시장: {kw_str} 주도 {total}건 분석",
            }
            return openers.get(category_type, f"{kw_str} 관련 {total}건 수집")

        themes_str = ", ".join(t[0] for t in top_themes[:2]) if top_themes else "다양한 이슈"
        return f"{themes_str} 관련 {total}건 수집"

    def generate_executive_summary(
        self,
        category_type: str = "general",
        extra_data: Optional[Dict[str, Any]] = None,
        total_override: Optional[int] = None,
    ) -> str:
        """Generate an enhanced TL;DR executive summary with HTML components.

        Uses stat grid, keyword-based theme briefings, and styled P0 alerts.
        Opener is content-driven: P0 issues or dominant keywords lead.

        Args:
            category_type: One of "crypto", "stock", "regulatory", "social",
                           "market", "security"
            extra_data: Optional dict with market data, region counts, etc.
            total_override: If provided, use this as the total count.

        Returns:
            Markdown/HTML string with stat grid, briefings, and alerts.
        """
        if len(self.items) < 3:
            return ""

        top_themes = self.get_top_themes()
        extra = extra_data or {}
        total = total_override if total_override is not None else len(self.items)
        priority_items = self.classify_priority()

        opener = self._build_executive_opener(category_type, top_themes, priority_items, total, extra)

        lines = ["## 한눈에 보기\n"]

        # Stat grid — risk level stat added
        risk_level = self._assess_risk_level(priority_items)
        stat_items = []
        stat_items.append(
            f'<div class="stat-item"><div class="stat-value">{total}</div><div class="stat-label">수집 건수</div></div>'
        )
        if top_themes:
            t = top_themes[0]
            stat_items.append(
                f'<div class="stat-item">'
                f'<div class="stat-value">{t[2]} {t[3]}</div>'
                f'<div class="stat-label">{t[0]}</div></div>'
            )
        # Risk level indicator
        risk_labels = {
            "critical": "높음",
            "elevated": "주의",
            "moderate": "보통",
            "low": "안정",
        }
        risk_emoji = {"critical": "🔴", "elevated": "🟡", "moderate": "🟢", "low": "🟢"}
        stat_items.append(
            f'<div class="stat-item">'
            f'<div class="stat-value">{risk_emoji[risk_level]} {risk_labels[risk_level]}</div>'
            f'<div class="stat-label">시장 경계</div></div>'
        )
        # Category-specific stats
        if category_type == "stock" and extra.get("kr_market"):
            kr = extra["kr_market"]
            for mkt_name, info in list(kr.items())[:2]:
                pct = info.get("change_pct", "")
                stat_items.append(
                    f'<div class="stat-item">'
                    f'<div class="stat-value">{info["price"]}</div>'
                    f'<div class="stat-label">{mkt_name} {pct}</div></div>'
                )
        if extra.get("top_keywords"):
            top_kw = extra["top_keywords"][0]
            top_kw_label = self._prepare_display_keywords([top_kw[0]], max_keywords=1)
            top_kw_value = top_kw_label[0] if top_kw_label else top_kw[0]
            stat_items.append(
                f'<div class="stat-item">'
                f'<div class="stat-value">{top_kw_value}</div>'
                f'<div class="stat-label">핫 키워드 ({top_kw[1]}회)</div></div>'
            )
        if category_type == "regulatory" and extra.get("region_counts"):
            regions = extra["region_counts"]
            top_r = regions.most_common(1)[0] if regions else None
            if top_r:
                stat_items.append(
                    f'<div class="stat-item">'
                    f'<div class="stat-value">{top_r[1]}</div>'
                    f'<div class="stat-label">{top_r[0]}</div></div>'
                )

        stat_html = "\n".join(stat_items)
        lines.append(f'<div class="stat-grid">\n{stat_html}\n</div>')

        # Theme briefings — ultra-short for at-a-glance box (max ~40 chars)
        briefing_items = []
        _sponsored_re = re.compile(r"\s*[Ss]ponsored\s+by\s+@?\S+.*$", flags=re.MULTILINE)
        for name, key, emoji, count in top_themes[:4]:
            articles = self._theme_articles.get(key, [])
            if not articles:
                continue
            # Build ultra-short keyword summary for at-a-glance
            kws = self._extract_title_keywords(articles, max_keywords=5)
            # Filter out keywords that match OTHER theme names (prevents wrong attribution)
            current_theme_name = ""
            for t_name, t_key, _e, _k in THEMES:
                if t_key == key:
                    current_theme_name = t_name.lower()
                    break
            filtered_kws = []
            for kw in kws:
                kw_lower = kw.lower()
                if kw_lower in _THEME_NAME_KEYWORDS and kw_lower != key.lower():
                    if kw_lower not in current_theme_name and kw_lower != key:
                        continue
                filtered_kws.append(kw)
            kws = self._prepare_display_keywords(filtered_kws, max_keywords=3)
            # Filter out meaningless short keywords (< 2 chars for Korean, < 3 for others)
            kws = [kw for kw in kws if len(kw) >= 2 and kw not in ("기사", "제하", "관련")]
            if kws:
                import datetime as _dt

                _seed = hash((_dt.datetime.now(tz=_dt.UTC).date().isoformat(), key, count))
                _patterns = [
                    ", ".join(kws[:2]) + " 주목",
                    ", ".join(kws[:2]) + " 이슈 부각",
                    ", ".join(kws[:2]) + f" 관련 {count}건",
                    ", ".join(kws[:2]) + " 동향 주시",
                ]
                short_briefing = _patterns[_seed % len(_patterns)]
            else:
                short_briefing = ""
            if short_briefing:
                short_briefing = _sponsored_re.sub("", short_briefing).strip()
            if short_briefing and len(short_briefing) > 40:
                short_briefing = short_briefing[:37] + "..."
            if short_briefing:
                briefing_items.append(f"<li>{emoji} <strong>{name}</strong>: {short_briefing}</li>")
            else:
                briefing_items.append(f"<li>{emoji} <strong>{name}</strong>: {count}건 수집</li>")

        if briefing_items:
            items_html = "\n".join(briefing_items)
            lines.append(
                f'<div class="alert-box alert-info">\n<strong>{opener}</strong>\n<ul>\n{items_html}\n</ul>\n</div>'
            )

        # P0 urgent alerts as red callout
        if priority_items.get("P0"):
            p0_html_items = []
            for item in priority_items["P0"][:3]:
                p0_title = item.get("title_ko") or item.get("title_translated") or item.get("title", "")
                link = item.get("link", "")
                desc = (item.get("description_ko") or item.get("description", "")).strip()
                # Build alert content: title + short description (Korean only)
                desc_part = ""
                if desc and desc != p0_title and desc != item.get("title", "") and len(desc) > 15:
                    # Skip descriptions that are mostly English (non-Korean)
                    korean_chars = sum(1 for c in desc if "\uac00" <= c <= "\ud7a3")
                    if korean_chars >= len(desc) * 0.3:
                        desc_short = desc[:100] + "..." if len(desc) > 100 else desc
                        desc_part = f' <span class="p0-desc">{desc_short}</span>'
                if link:
                    p0_html_items.append(f'<li><a href="{link}">{p0_title}</a>{desc_part}</li>')
                else:
                    p0_html_items.append(f"<li>{p0_title}{desc_part}</li>")
            if p0_html_items:
                p0_html = "\n".join(p0_html_items)
                lines.append(
                    f'<div class="alert-box alert-urgent">\n<strong>긴급 알림</strong>\n<ul>\n{p0_html}\n</ul>\n</div>'
                )

        return "\n".join(lines)

    def generate_market_insight(self) -> str:
        """Generate cross-theme market insight with monitoring points.

        Analyzes theme co-occurrence patterns and priority issues to produce
        actionable investor takeaways. Does not rely on LLM -- uses rule-based
        pattern matching against CROSS_THEME_INSIGHTS and priority data.

        Returns:
            Markdown section with market insight, or empty string if
            insufficient data.
        """
        if len(self.items) < 5:
            return ""

        top_themes = self.get_top_themes()
        if len(top_themes) < 2:
            return ""

        priority_items = self.classify_priority()
        total = len(self.items)

        lines = ["## 투자자 인사이트\n"]

        # 1. Cross-theme pattern detection
        insight_found = False
        seen_pairs: set = set()
        theme_keys = [t[1] for t in top_themes]

        for i, key_a in enumerate(theme_keys):
            for key_b in theme_keys[i + 1 :]:
                pair = (key_a, key_b)
                pair_rev = (key_b, key_a)
                if pair in seen_pairs or pair_rev in seen_pairs:
                    continue
                seen_pairs.add(pair)

                insights = CROSS_THEME_INSIGHTS.get(pair) or CROSS_THEME_INSIGHTS.get(pair_rev)
                if insights:
                    idx = total % len(insights)
                    name_a = next((t[0] for t in top_themes if t[1] == key_a), key_a)
                    name_b = next((t[0] for t in top_themes if t[1] == key_b), key_b)
                    lines.append(f"- **{name_a} + {name_b}**: {insights[idx]}")
                    insight_found = True

        # 2. Risk assessment
        risk_level = self._assess_risk_level(priority_items)
        risk_desc = RISK_LEVELS.get(risk_level, "")
        if risk_desc:
            lines.append(f"\n**리스크 평가**: {risk_desc}")

        # 3. Monitoring points based on dominant themes
        monitor_points: List[str] = []
        p0_items = priority_items.get("P0", [])
        p1_items = priority_items.get("P1", [])

        if p0_items:
            p0_kws = self._extract_title_keywords(p0_items, max_keywords=3)
            if p0_kws:
                monitor_points.append(f"P0 긴급 이슈 ({', '.join(p0_kws)}) 후속 보도")

        if p1_items:
            p1_kws = self._extract_title_keywords(p1_items, max_keywords=3)
            if p1_kws:
                monitor_points.append(f"P1 주요 이슈 ({', '.join(p1_kws)}) 전개 방향")

        # Theme-specific monitoring suggestions
        theme_monitors: Dict[str, str] = {
            "regulation": "규제 당국 후속 조치 및 시행 일정",
            "price_market": "주요 지지/저항선 돌파 여부 및 거래량 변화",
            "bitcoin": "비트코인 온체인 지표 (해시레이트, 고래 움직임)",
            "macro": "다음 경제 지표 발표 일정 (CPI, FOMC, 고용)",
            "security": "해킹 피해 규모 확정 및 자금 추적 현황",
            "exchange": "거래소 상장/상폐 확정 공지 및 거래량 변화",
            "defi": "TVL 변동 추이 및 프로토콜 업데이트 일정",
            "ethereum": "가스비 추이 및 L2 활동량 변화",
            "politics": "법안 진행 상황 및 투표 일정",
            "ai_tech": "AI 관련 토큰/주식 가격 및 거래량 추이",
        }
        for _name, key, _emoji, _count in top_themes[:3]:
            if key in theme_monitors:
                monitor_points.append(theme_monitors[key])

        if monitor_points:
            lines.append("\n**모니터링 포인트**:")
            for point in monitor_points[:5]:
                lines.append(f"- {point}")

        # 4. Theme concentration analysis
        if top_themes:
            dominant_ratio = top_themes[0][3] / total if total > 0 else 0
            if dominant_ratio > 0.5:
                lines.append(
                    f"\n> {top_themes[0][0]} 테마가 전체의 "
                    f"{dominant_ratio:.0%}를 차지하며 시장의 관심이 "
                    f"집중되어 있습니다. 다른 테마의 중요 뉴스가 "
                    f"묻힐 수 있으니 주의가 필요합니다."
                )

        if not insight_found and not monitor_points:
            return ""

        lines.append("")
        return "\n".join(lines)

    # Impact multipliers by source authority
    _SOURCE_WEIGHTS = {
        "reuters": 2.0,
        "bloomberg": 2.0,
        "coindesk": 1.5,
        "cointelegraph": 1.5,
        "sec": 2.0,
        "fed": 2.0,
        "wsj": 1.8,
        "cnbc": 1.5,
        "google news": 1.0,
        "binance": 1.3,
        "cryptopanic": 1.0,
    }

    def score_impact(self, item: Dict[str, Any]) -> float:
        """Score an item's impact (0-10) based on source authority and content signals."""
        text = (item.get("title", "") + " " + item.get("description", "")).lower()
        source = item.get("source", "").lower()

        # Base score from source authority
        base = 1.0
        for src_key, weight in self._SOURCE_WEIGHTS.items():
            if src_key in source:
                base = weight
                break

        # Content signals
        signals = 0.0
        # Price percentage mentions suggest quantitative impact
        if re.search(r"[+-]?\d+\.?\d*%", text):
            signals += 1.5
        # Large dollar amounts
        if re.search(r"\$[\d,.]+\s*(?:billion|million|B|M)", text, re.I):
            signals += 2.0
        # Institutional names
        institutions = ["fed", "sec", "ecb", "imf", "world bank", "금융위", "한국은행", "금감원"]
        if any(inst in text for inst in institutions):
            signals += 1.5
        # Urgency words
        urgency = ["breaking", "urgent", "emergency", "속보", "긴급", "flash"]
        if any(u in text for u in urgency):
            signals += 2.0

        return min(base + signals, 10.0)

    _SENTIMENT_POS = {
        "rally",
        "surge",
        "bull",
        "gain",
        "rise",
        "jump",
        "soar",
        "breakout",
        "upgrade",
        "adoption",
        "approval",
        "recovery",
        "상승",
        "급등",
        "반등",
        "돌파",
        "강세",
        "호재",
        "승인",
        "회복",
        "성장",
    }
    _SENTIMENT_NEG = {
        "crash",
        "dump",
        "bear",
        "drop",
        "fall",
        "plunge",
        "decline",
        "hack",
        "exploit",
        "fraud",
        "ban",
        "lawsuit",
        "bankruptcy",
        "하락",
        "급락",
        "폭락",
        "약세",
        "악재",
        "해킹",
        "파산",
        "소송",
        "위축",
    }

    def get_theme_sentiment(self, theme_key: str) -> str:
        """Return sentiment label for a theme: 'bullish', 'bearish', or 'neutral'."""
        self._ensure_scored()
        articles = self._theme_articles.get(theme_key, [])
        if not articles:
            return "neutral"
        pos = neg = 0
        for item in articles:
            text = (item.get("title", "") + " " + item.get("description", "")).lower()
            pos += sum(1 for kw in self._SENTIMENT_POS if kw in text)
            neg += sum(1 for kw in self._SENTIMENT_NEG if kw in text)
        if pos > neg * 1.5:
            return "bullish"
        elif neg > pos * 1.5:
            return "bearish"
        return "neutral"

    def detect_concentration(self) -> Optional[Tuple[str, str, float]]:
        """Detect if news is unusually concentrated on one theme.

        Returns (theme_name, theme_key, concentration_ratio) if >40% of articles
        fall into a single theme, else None.
        """
        self._ensure_scored()
        total = len(self.items)
        if total < 5:
            return None
        top = self.get_top_themes()
        if not top:
            return None
        name, key, _emoji, count = top[0]
        ratio = count / total
        if ratio >= 0.4:
            return (name, key, ratio)
        return None

    def get_top_themes_with_sentiment(self) -> List[Tuple[str, str, str, int, str]]:
        """Return top themes with sentiment: (name, key, emoji, count, sentiment)."""
        themes = self.get_top_themes()
        result = []
        for name, key, emoji, count in themes:
            sentiment = self.get_theme_sentiment(key)
            sentiment_label = {"bullish": "📈", "bearish": "📉", "neutral": "➡️"}
            result.append((name, key, emoji, count, sentiment_label.get(sentiment, "➡️")))
        return result

    def detect_anomalies(self) -> List[Tuple[str, str, int, str]]:
        """Detect themes with unusually high article counts.

        Returns list of (name, key, count, description) for anomalous themes.
        """
        self._ensure_scored()
        top = self.get_top_themes()
        if len(top) < 3:
            return []
        counts = [c for _, _, _, c in top]
        avg = sum(counts) / len(counts)
        anomalies = []
        for name, key, _emoji, count in top:
            if count > avg * 2 and count >= 5:
                anomalies.append(
                    (name, key, count, f"{name} 관련 뉴스가 평균 대비 {count / avg:.1f}배 집중 — 주요 이벤트 가능성")
                )
        return anomalies
