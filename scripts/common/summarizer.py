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

from . import post_html as post_html  # noqa: PLC0414 (re-export-safe local alias)
from . import summary_quality as _summary_quality_mod
from .markdown_utils import markdown_link
from .severity import (  # noqa: F401  (re-exported for backward compat)
    _SEV_BADGE_HTML,
    _SEVERITY_HIGH_KW,
    _SEVERITY_LOW_KW,
    _classify_news_severity,
)
from .summarizer_chart import BAR_COLORS as _summarizer_chart_bar_colors
from .summarizer_chart import generate_distribution_chart as _generate_distribution_chart
from .summarizer_keywords import NOISE_ENGLISH, STOP_WORDS
from .summarizer_priority import (  # noqa: F401  (re-exported for backward compat)
    _P0_RE,
    _P1_RE,
    _P2_RE,
    PRIORITY_KEYWORDS,
    _make_keyword_pattern,
)
from .summarizer_priority import classify_priority as _classify_priority
from .summary_quality import (  # noqa: F401  (_is_boilerplate_desc / _BOILERPLATE_DESC_PHRASES re-exported for backward compat)
    _BOILERPLATE_DESC_PHRASES,
    _is_boilerplate_desc,
)
from .text_utils import (  # noqa: F401  (_best_favicon_link, _favicon_url re-exported for golden test monkey-patching)
    _best_favicon_link,
    _favicon_url,
    _fix_mistranslations,
    _strip_trailing_artifacts,
    _truncate_sentence,
)
from .theme_briefing import ThemeBriefingGenerator
from .theme_index import ThemeIndex
from .themes import (  # noqa: F401  (BAR_WIDTH re-exported for backward compat)
    _THEME_NAME_KEYWORDS,
    ARTICLES_PER_THEME,
    BAR_WIDTH,
    OVERFLOW_PREVIEW_LIMIT,
    THEMES,
    TOP_THEMES_COUNT,
)

logger = logging.getLogger(__name__)


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


# Generic/synthetic description detection now lives in common.summary_quality.
# The canonical list is ``summary_quality.GENERIC_DESC_PATTERNS`` — do not
# redefine here. ``_is_boilerplate_desc`` / ``_BOILERPLATE_DESC_PHRASES`` also
# live in ``summary_quality`` now (re-exported at the top of this module for
# backward compatibility), so the ``summary_quality.is_boilerplate``
# orchestrator no longer needs a deferred import back into summarizer.


def _is_generic_desc(desc: str) -> bool:
    """Thin backward-compat wrapper around the facade's ``is_generic_desc``.

    Existing internal callers (e.g. the summary-section builder in this module)
    and the ``summary_quality.is_boilerplate`` orchestrator both reach the
    facade through this name. Future code should call
    ``summary_quality.is_generic_desc(desc)`` directly.
    """
    return _summary_quality_mod.is_generic_desc(desc)


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


class ThemeSummarizer:
    """Classify news items into themes and generate markdown summary sections."""

    def __init__(self, items: List[Dict[str, Any]]):
        self.items = items
        self._theme_index = ThemeIndex(items)
        self._last_risk_verdict = None
        self._briefing = ThemeBriefingGenerator(self)

    def _ensure_scored(self):
        """Score themes lazily on first access (delegates to ThemeIndex)."""
        return self._theme_index._ensure_scored()

    def _score_themes(self):
        """Score each theme by keyword frequency (delegates to ThemeIndex)."""
        return self._theme_index._score_themes()

    def get_top_themes(self) -> List[Tuple[str, str, str, int]]:
        """Return top themes as (name, key, emoji, article_count) tuples."""
        return self._theme_index.get_top_themes()

    def get_articles_for_theme(
        self,
        theme_key: str,
        default: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        """Return articles matched to theme_key.

        Scores themes lazily on first call. Returns a *shallow copy* of the
        internal list so callers cannot mutate the index. Article dicts inside
        the list are NOT copied — callers must treat them as read-only.

        Args:
            theme_key: One of ``THEMES`` keys (e.g. ``"bitcoin"``, ``"regulation"``).
            default: Returned when ``theme_key`` is not indexed. Defaults to
                ``[]`` (a fresh list per call, never shared).
        """
        return self._theme_index.get_articles_for_theme(theme_key, default)

    def classify_priority(self) -> Dict[str, List[Dict[str, Any]]]:
        """Classify items into priority buckets (P0, P1, P2).

        Thin wrapper around :func:`summarizer_priority.classify_priority` for
        backward compatibility with the original instance-method API.
        """
        return _classify_priority(self.items)

    # Class attribute mirror of summarizer_chart.BAR_COLORS so external code
    # that historically reads ``ThemeSummarizer._BAR_COLORS`` keeps working.
    _BAR_COLORS = _summarizer_chart_bar_colors

    def generate_distribution_chart(self) -> str:
        """Generate HTML progress bars for issue distribution.

        Thin wrapper around :func:`summarizer_chart.generate_distribution_chart`
        that passes pre-computed top themes.
        """
        return _generate_distribution_chart(self.items, self.get_top_themes())

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
        # Lazy import to avoid circular import: themed_news_renderer imports
        # ``common.summarizer`` at call time for favicon helper monkey-patching.
        from .themed_news_renderer import ThemedNewsRenderer

        return ThemedNewsRenderer(self.items, self).render(max_articles, featured_count)

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
                if normalized not in STOP_WORDS and normalized not in NOISE_ENGLISH and len(normalized) >= 2:
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
        """Thin delegating wrapper — see :class:`ThemeBriefingGenerator`.

        Kept on ThemeSummarizer because ``themed_news_renderer`` and the
        existing test suite monkey-patch / call this attribute directly.
        """
        return self._briefing.generate_single_theme_briefing(theme_key, articles)

    def _generate_theme_subtitle(self, theme_key: str, articles: List[Dict[str, Any]]) -> str:
        """Thin delegating wrapper — see :class:`ThemeBriefingGenerator`."""
        return self._briefing.generate_theme_subtitle(theme_key, articles)

    def generate_theme_briefing(self) -> str:
        """Thin delegating wrapper — see :class:`ThemeBriefingGenerator`."""
        return self._briefing.generate_theme_briefing()

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
            articles = self.get_articles_for_theme(key)
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
                articles = self.get_articles_for_theme(key)
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
            dominant_articles = self.get_articles_for_theme(dominant_key)
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
            articles = self.get_articles_for_theme(key)
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
            # briefing_items hold full "<li>...</li>" strings; alert_box wraps
            # bullets in <li>, so strip the outer tags before handing off.
            _bullets = [item.removeprefix("<li>").removesuffix("</li>") for item in briefing_items]
            lines.append(post_html.alert_box(opener, _bullets, variant="info"))

        # P0 urgent alerts as red callout
        if priority_items.get("P0"):
            p0_html_items = []
            for item in priority_items["P0"][:3]:
                p0_title = item.get("title_ko") or item.get("title_translated") or item.get("title", "")
                # Prefer original publisher URL when RSS preserved it via <source url="">;
                # falls back to link (which may be a Google News redirect).
                link = item.get("original_url") or item.get("link", "")
                desc = (item.get("description_ko") or item.get("description", "")).strip()
                # Build alert content: title + short description (Korean only)
                desc_part = ""
                if desc and desc != p0_title and desc != item.get("title", "") and len(desc) > 15:
                    # Skip descriptions that are mostly English (non-Korean)
                    korean_chars = sum(1 for c in desc if "\uac00" <= c <= "\ud7a3")
                    if korean_chars >= len(desc) * 0.3:
                        desc = _strip_trailing_artifacts(desc)
                        desc_short = desc[:100] + "..." if len(desc) > 100 else desc
                        desc_part = f' <span class="p0-desc">{desc_short}</span>'
                if link:
                    p0_html_items.append(f'<li><a href="{link}">{p0_title}</a>{desc_part}</li>')
                else:
                    p0_html_items.append(f"<li>{p0_title}{desc_part}</li>")
            if p0_html_items:
                # p0_html_items hold full "<li>...</li>" strings; alert_box wraps
                # bullets in <li>, so strip the outer tags before handing off.
                _bullets = [item.removeprefix("<li>").removesuffix("</li>") for item in p0_html_items]
                lines.append(post_html.alert_box("긴급 알림", _bullets, variant="urgent"))

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
        articles = self.get_articles_for_theme(theme_key)
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
