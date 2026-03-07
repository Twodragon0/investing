"""Keyword-based theme summarizer for collected news items.

Classifies news items into predefined themes using keyword matching
and generates markdown summary sections including:
- Issue distribution ASCII bar chart
- Theme-based news grouping with articles per theme
- Top keyword analysis

No LLM or external dependencies required.
"""

import logging
import re
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

from .markdown_utils import html_source_tag

logger = logging.getLogger(__name__)


def _truncate_sentence(text: str, max_len: int = 300) -> str:
    """Truncate text at the nearest sentence boundary within max_len.

    Handles Korean sentence endings (다., 요., 음., 됩니다.)
    as well as English (. ) and Japanese (。) boundaries.
    Returns empty string if text is too short to be useful.
    """
    text = text.strip()
    if not text or len(text) < 15:
        return ""
    if len(text) <= max_len:
        return text

    # Korean and English sentence-ending patterns
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

    # No sentence boundary found — cut at word/character boundary
    truncated = text[:max_len]
    # Try space-based word boundary first
    space_idx = truncated.rfind(" ", max_len // 2)
    if space_idx > max_len // 2:
        return truncated[:space_idx].strip() + "..."
    # For CJK text without spaces, cut at max_len
    return truncated.strip() + "..."


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
        "bitcoin": "비트코인 시장에 영향을 줄 수 있는 변화입니다.",
        "ethereum": "이더리움 생태계 발전에 관련된 소식입니다.",
        "altcoin": "알트코인 시장 흐름에 영향을 미칠 수 있습니다.",
        "regulation": "규제 환경 변화에 주목할 필요가 있습니다.",
        "price": "가격 동향과 투자 심리에 직접적 영향이 있습니다.",
        "price_market": "가격 동향과 투자 심리에 직접적 영향이 있습니다.",
        "defi": "디파이 생태계의 성장과 리스크에 관한 내용입니다.",
        "nft": "디지털 자산과 Web3 생태계 관련 내용입니다.",
        "nft_web3": "디지털 자산과 Web3 생태계 관련 내용입니다.",
        "exchange": "거래소 운영 환경 변화와 관련된 소식입니다.",
        "macro": "거시경제 흐름이 자산 시장에 미치는 영향입니다.",
        "ai_tech": "AI·기술 혁신이 투자 환경에 미치는 영향입니다.",
        "politics": "정책 변화가 금융시장에 미치는 파급 효과입니다.",
        "security": "보안 이슈가 시장 신뢰도에 미치는 영향입니다.",
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

    ctx = _THEME_CONTEXT.get(theme_key, "관련 소식입니다.")
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
]


def _is_generic_desc(desc: str) -> bool:
    """Return True if description is a generic/synthetic placeholder with no real info."""
    return any(p.search(desc.strip()) for p in _GENERIC_DESC_PATTERNS)


# Noise title patterns to filter out (e.g., SEC page addresses, form names)
_NOISE_TITLE_RE = re.compile(
    r"^(?:"
    r"(?:Washington,?\s*DC\s*\d+)|"  # SEC address
    r"(?:10-[KQ](?:\s|$))|"  # SEC form names
    r"(?:Form\s+\d)|"  # SEC form numbers
    r"(?:SEC\.gov\s*-?\s*SEC\.gov)|"  # SEC.gov self-links
    r"(?:EDGAR\s)"  # EDGAR system pages
    r")",
    re.IGNORECASE,
)

# Theme definitions: (theme_name_ko, theme_key, emoji, keywords)
THEMES = [
    (
        "규제/정책",
        "regulation",
        "🔵",
        [
            "sec",
            "cftc",
            "fca",
            "regulation",
            "regulatory",
            "compliance",
            "규제",
            "금융위",
            "금감원",
            "mica",
            "esma",
            "mas",
            "법안",
            "bill",
            "enforcement",
            "lawsuit",
            "소송",
            "제재",
            "금융감독원",
            "자본시장법",
            "mifid",
            "doj",
            "fbi",
            "irs",
            "audit",
            "감사",
            "처분",
            "stablecoin bill",
            "market structure",
            "cbdc",
        ],
    ),
    (
        "DeFi",
        "defi",
        "🟣",
        [
            "defi",
            "dex",
            "yield",
            "lending",
            "tvl",
            "liquidity",
            "aave",
            "uniswap",
            "compound",
            "staking",
            "restaking",
            "bridge",
            "swap",
            "pool",
            "vault",
            "amm",
            "lp",
            "impermanent",
            "curve",
            "maker",
            "ondo",
            "rwa",
            "tokenized",
            "real world asset",
            "intent",
            "chain abstraction",
            "payfi",
        ],
    ),
    (
        "비트코인",
        "bitcoin",
        "🟠",
        [
            "bitcoin",
            "btc",
            "mining",
            "halving",
            "비트코인",
            "채굴",
            "satoshi",
            "lightning network",
            "ordinals",
            "runes",
            "etf",
            "miner",
            "마이너",
            "hash rate",
            "해시레이트",
            "hodl",
            "whale",
            "고래",
            "accumulation",
            "block reward",
            "spot etf",
            "strategic reserve",
            "taproot",
        ],
    ),
    (
        "이더리움",
        "ethereum",
        "🔷",
        [
            "ethereum",
            "eth",
            "layer2",
            "rollup",
            "이더리움",
            "solidity",
            "evm",
            "l2",
            "blob",
            "dencun",
            "arbitrum",
            "optimism",
            "base",
            "zksync",
            "starknet",
            "polygon",
            "scroll",
            "mantle",
            "linea",
            "pectra",
            "eip",
            "gasless",
            "account abstraction",
            "verkle",
            "blob space",
            "restaking",
        ],
    ),
    (
        "AI/기술",
        "ai_tech",
        "🤖",
        [
            "artificial intelligence",
            "gpu",
            "인공지능",
            "machine learning",
            "chatgpt",
            "nvidia",
            "반도체",
            "엔비디아",
            "openai",
            "anthropic",
            "semiconductor",
            "tsmc",
            "ai agent",
            "ai model",
            "생성형 ai",
            "apple",
            "meta",
            "google",
            "microsoft",
            "데이터센터",
            "cloud",
            "클라우드",
            "ai chip",
            "hbm",
            "딥시크",
            "deepseek",
            "llm",
            "transformer",
            "ai agent",
            "inference",
            "sovereign ai",
        ],
    ),
    (
        "매크로/금리",
        "macro",
        "📊",
        [
            "fed",
            "interest rate",
            "inflation",
            "금리",
            "한국은행",
            "gdp",
            "cpi",
            "fomc",
            "rate cut",
            "rate hike",
            "환율",
            "물가",
            "실업률",
            "고용",
            "소비자물가",
            "pce",
            "기준금리",
            "양적완화",
            "양적긴축",
            "treasury",
            "채권",
            "powell",
            "파월",
            "boj",
            "ecb",
            "경제성장",
            "gdp성장",
            "무역수지",
            "경상수지",
            "nonfarm",
            "비농업",
        ],
    ),
    (
        "거래소",
        "exchange",
        "🏦",
        [
            "binance",
            "coinbase",
            "exchange",
            "listing",
            "거래소",
            "upbit",
            "bithumb",
            "bybit",
            "okx",
            "kraken",
            "상장",
            "상장폐지",
            "delisting",
            "coinone",
            "korbit",
            "htx",
            "gate",
            "bitget",
            "거래량",
            "volume",
            "ipo",
            "자진상폐",
        ],
    ),
    (
        "보안/해킹",
        "security",
        "🔴",
        [
            "hack",
            "exploit",
            "vulnerability",
            "security",
            "해킹",
            "breach",
            "phishing",
            "scam",
            "rug pull",
            "drain",
            "flash loan",
            "oracle",
            "재진입",
            "bridge exploit",
            "front-running",
            "mev",
            "sandwich",
            "dusting",
            "smart contract bug",
            "취약점",
            "인증",
            "zero day",
            "social engineering",
            "private key",
        ],
    ),
    (
        "정치/정책",
        "politics",
        "🏛️",
        [
            "trump",
            "이재명",
            "election",
            "policy",
            "정책",
            "tariff",
            "sanction",
            "congress",
            "의회",
            "관세",
            "백악관",
            "대통령",
            "executive order",
            "행정명령",
            "biden",
            "바이든",
            "kamala",
            "의원",
            "senator",
            "representative",
            "입법",
            "legislation",
            "대선",
            "총선",
            "국회",
        ],
    ),
    (
        "NFT/Web3",
        "nft_web3",
        "🎨",
        [
            "nft",
            "metaverse",
            "web3",
            "opensea",
            "메타버스",
            "digital collectible",
            "gamefi",
            "socialfi",
            "creator",
        ],
    ),
    (
        "가격/시장",
        "price_market",
        "📈",
        [
            "price",
            "rally",
            "crash",
            "plunge",
            "시세",
            "상승",
            "하락",
            "급등",
            "급락",
            "폭락",
            "반등",
            "bull",
            "bear",
            "bullish",
            "bearish",
            "강세",
            "약세",
            "조정",
            "correction",
            "코스피",
            "코스닥",
            "나스닥",
            "다우존스",
            "금",
            "원유",
            "달러",
            "support",
            "resistance",
            "지지",
            "저항",
            "돌파",
            "breakout",
            "ath",
            "all-time high",
            "거래량",
            "volume",
            "매수",
            "매도",
            "시총",
            "market cap",
            "liquidation",
            "open interest",
            "funding rate",
        ],
    ),
]

TOP_THEMES_COUNT = 5
ARTICLES_PER_THEME = 5
BAR_WIDTH = 18

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


class ThemeSummarizer:
    """Classify news items into themes and generate markdown summary sections."""

    def __init__(self, items: List[Dict[str, Any]]):
        self.items = items
        self._theme_scores: Dict[str, int] = {}
        self._theme_articles: Dict[str, List[Dict[str, Any]]] = {}
        self._scored = False

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
        Items are matched by keyword presence in title + description.
        Each item is assigned to only its highest priority bucket.
        """
        result: Dict[str, List[Dict[str, Any]]] = {"P0": [], "P1": [], "P2": []}
        assigned: set = set()

        for priority in ["P0", "P1", "P2"]:
            keywords = PRIORITY_KEYWORDS[priority]
            for idx, item in enumerate(self.items):
                if idx in assigned:
                    continue
                text = (item.get("title", "") + " " + item.get("description", "")).lower()
                if any(kw in text for kw in keywords):
                    result[priority].append(item)
                    assigned.add(idx)

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
        lines.append(f"\n*총 {len(self.items)}건 수집 (기사는 여러 테마에 중복 집계될 수 있음)*\n")
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
            briefing = self._generate_single_theme_briefing(key, articles)
            lines.append(f"### {emoji} {name} ({count}건)\n")
            if briefing:
                lines.append(f"*{briefing}*\n")

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
                title = article.get("title_ko") or orig_title
                link = article.get("link", "")
                source = article.get("source", "")
                description = (article.get("description_ko") or article.get("description", "")).strip()

                # Skip articles already featured in previous themes
                if shown < featured_count and orig_title in cross_theme_featured:
                    # Demote to remaining links instead
                    if link:
                        remaining_links.append(f'<a href="{link}">{title}</a>')
                    else:
                        remaining_links.append(title)
                    continue

                if shown < featured_count:
                    # Build HTML card for featured item
                    num = shown + 1
                    from html import escape as _esc

                    safe_title = _esc(title, quote=True)
                    card_parts = [
                        '<div class="news-card-item">',
                        f'<div class="news-card-num">{num}</div>',
                    ]

                    # Add thumbnail if image available
                    image_url = article.get("image", "")
                    if image_url:
                        safe_img = _esc(image_url, quote=True)
                        onerr = "this.parentElement.style.display='none'"
                        card_parts.append(
                            f'<div class="news-card-thumb">'
                            f'<img src="{safe_img}" alt="" loading="lazy"'
                            f' onerror="{onerr}">'
                            f"</div>"
                        )

                    card_parts.append('<div class="news-card-body">')
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
                    if link:
                        remaining_links.append(f'<a href="{link}">{title}</a>')
                    else:
                        remaining_links.append(title)

                shown += 1
                if shown >= max_articles:
                    break

            overflow = len([a for a in articles if a.get("title") and a["title"] not in seen_titles])
            remaining_count = len(remaining_links) + overflow
            if remaining_links:
                lines.append(
                    f"<details><summary>그 외 {remaining_count}건 보기</summary>"
                    f'<div class="details-content"><ol class="news-overflow-list">'
                )
                for link_html in remaining_links[:15]:
                    lines.append(f"<li>{link_html}</li>")
                if remaining_count > 15:
                    lines.append(f"<li><em>...외 {remaining_count - 15}건</em></li>")
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
                if (
                    normalized not in self._STOP_WORDS
                    and normalized not in self._NOISE_ENGLISH
                    and len(normalized) >= 2
                ):
                    # Skip short generic English tokens (1-2 chars)
                    if re.match(r"^[a-z]{1,2}$", normalized):
                        continue
                    word_counter[token] += 1
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
        keywords = self._extract_title_keywords(articles, max_keywords=5)
        if len(keywords) >= 2:
            count = len(articles)
            # Separate Korean and English keywords for natural phrasing
            kr_kw = [k for k in keywords if re.search(r"[가-힣]", k)]
            en_kw = [k for k in keywords if not re.search(r"[가-힣]", k)]

            # Build a more natural Korean briefing
            display_kw = kr_kw[:3] if kr_kw else en_kw[:3]
            if not display_kw:
                display_kw = keywords[:3]

            kw_str = ", ".join(display_kw)

            # Use varied templates instead of one fixed pattern
            templates = [
                f"{kw_str} 중심으로 {count}건의 뉴스가 수집되었습니다.",
                f"{kw_str} 이슈가 {count}건으로 주목받고 있습니다.",
                f"{count}건의 뉴스에서 {kw_str} 키워드가 부각되고 있습니다.",
            ]
            return templates[count % len(templates)]

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
            if briefing:
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
                analysis_parts.append(f"전체의 {ratio:.0%}로 가장 높은 비중을 차지합니다.")
            elif ratio > 0.2:
                analysis_parts.append(f"전체의 {ratio:.0%}로 주요 테마입니다.")

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

                if link:
                    lines.append(f"- [{title}]({link}) — {source}")
                else:
                    lines.append(f"- {title} — {source}")

                # Add description excerpt (first sentence, up to 150 chars)
                if desc and desc != title and len(desc) > 20 and not _is_generic_desc(desc):
                    desc_short = _truncate_sentence(desc, max_len=150)
                    if desc_short:
                        lines.append(f"  > {desc_short}")

                shown += 1
                if shown >= 3:
                    break

            lines.append("")

        return "\n".join(lines)

    def _assess_risk_level(self, priority_items: Dict[str, List[Dict[str, Any]]]) -> str:
        """Assess market risk level based on P0/P1 issue counts."""
        p0_count = len(priority_items.get("P0", []))
        p1_count = len(priority_items.get("P1", []))
        if p0_count >= 3:
            return "critical"
        if p0_count >= 1:
            return "elevated"
        if p1_count >= 5:
            return "elevated"
        if p1_count >= 2:
            return "moderate"
        return "low"

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
            p0_title = p0_items[0].get("title_ko") or p0_items[0].get("title", "긴급 이슈")
            # Truncate long titles
            if len(p0_title) > 80:
                p0_title = p0_title[:77] + "..."
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
                # Use total as seed for deterministic but varying selection
                idx = total % len(narratives)
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
                idx = total % len(cross_insights)
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
    ) -> str:
        """Generate a content-aware overall summary section.

        Analyzes P0/P1 issues, dominant themes, and cross-theme patterns
        to produce a narrative summary rather than generic count listings.
        """
        if len(self.items) < 3:
            return ""

        extra = extra_data or {}
        total = len(self.items)
        top_themes = self.get_top_themes()
        priority_items = self.classify_priority()

        lines = [f"## {title}\n"]

        # Narrative intro based on actual content analysis
        intro = self._build_narrative_intro(top_themes, priority_items, total)
        lines.append(f"{intro}\n")

        # Theme breakdown with keyword-based briefings
        if top_themes:
            for i, (name, key, emoji, count) in enumerate(top_themes[:3], 1):
                articles = self._theme_articles.get(key, [])
                snippet = self._generate_single_theme_briefing(key, articles)
                if snippet:
                    lines.append(f"{i}. **{emoji} {name}** ({count}건): {snippet}")
                else:
                    lines.append(f"{i}. **{emoji} {name}** ({count}건)")
            lines.append("")

        # Risk assessment
        risk_level = self._assess_risk_level(priority_items)
        if risk_level != "low":
            risk_desc = RISK_LEVELS.get(risk_level, "")
            if risk_desc:
                lines.append(f"**리스크 수준 [{risk_level.upper()}]**: {risk_desc}")

        # Priority signal with specific titles instead of just counts
        p0_items = priority_items.get("P0", [])
        p1_items = priority_items.get("P1", [])
        if p0_items:
            p0_titles = [(item.get("title_ko") or item.get("title", ""))[:60] for item in p0_items[:3]]
            lines.append(f"**P0 긴급**: {' / '.join(t for t in p0_titles if t)}")
        if p1_items and len(p1_items) <= 5:
            p1_titles = [(item.get("title_ko") or item.get("title", ""))[:50] for item in p1_items[:3]]
            lines.append(f"**P1 주요**: {' / '.join(t for t in p1_titles if t)}")
        elif p1_items:
            lines.append(f"**P1 주요**: {len(p1_items)}건 확인")

        # Top keywords
        top_keywords = extra.get("top_keywords") or []
        if top_keywords:
            kw_str = ", ".join(f"**{kw}**" for kw, _ in top_keywords[:5])
            lines.append(f"**핵심 키워드**: {kw_str}")

        # Additional context
        region_counts = extra.get("region_counts")
        if region_counts:
            regions_str = ", ".join(f"{name} {count}건" for name, count in region_counts.most_common(3))
            if regions_str:
                lines.append(f"**주요 지역**: {regions_str}")

        source_counter = extra.get("source_counter")
        if source_counter:
            top_sources = source_counter.most_common(3)
            if top_sources:
                src_str = ", ".join(f"{name}({count}건)" for name, count in top_sources)
                lines.append(f"**주요 출처**: {src_str}")

        summary_points = extra.get("summary_points") or []
        for point in summary_points[:2]:
            if point:
                lines.append(f"- {point}")

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
            p0_title = p0_items[0].get("title_ko") or p0_items[0].get("title", "")
            if len(p0_title) > 60:
                # Try to extract key phrase
                keywords = self._extract_title_keywords(p0_items[:1], max_keywords=3)
                p0_title = ", ".join(keywords) if keywords else p0_title[:57] + "..."
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
            top_kws = self._extract_title_keywords(dominant_articles, max_keywords=3)
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
    ) -> str:
        """Generate an enhanced TL;DR executive summary with HTML components.

        Uses stat grid, keyword-based theme briefings, and styled P0 alerts.
        Opener is content-driven: P0 issues or dominant keywords lead.

        Args:
            category_type: One of "crypto", "stock", "regulatory", "social",
                           "market", "security"
            extra_data: Optional dict with market data, region counts, etc.

        Returns:
            Markdown/HTML string with stat grid, briefings, and alerts.
        """
        if len(self.items) < 3:
            return ""

        top_themes = self.get_top_themes()
        extra = extra_data or {}
        total = len(self.items)
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
            "critical": "위험",
            "elevated": "주의",
            "moderate": "보통",
            "low": "안정",
        }
        risk_emoji = {"critical": "🔴", "elevated": "🟡", "moderate": "🟢", "low": "🟢"}
        stat_items.append(
            f'<div class="stat-item">'
            f'<div class="stat-value">{risk_emoji[risk_level]}</div>'
            f'<div class="stat-label">리스크 {risk_labels[risk_level]}</div></div>'
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
            stat_items.append(
                f'<div class="stat-item">'
                f'<div class="stat-value">{top_kw[0]}</div>'
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

        lines.append(f'<div class="stat-grid">{"".join(stat_items)}</div>')

        # Theme briefings — use keyword-extracted briefings
        briefing_items = []
        _sponsored_re = re.compile(r"\s*[Ss]ponsored\s+by\s+@?\S+.*$", flags=re.MULTILINE)
        for name, key, emoji, count in top_themes[:4]:
            articles = self._theme_articles.get(key, [])
            if not articles:
                continue
            # Use improved keyword-based briefing
            briefing = self._generate_single_theme_briefing(key, articles)
            if briefing:
                # Clean sponsored text from briefing
                briefing = _sponsored_re.sub("", briefing).strip()
            if briefing:
                briefing_items.append(f"<li>{emoji} <strong>{name}</strong> ({count}건): {briefing}</li>")
            else:
                briefing_items.append(f"<li>{emoji} <strong>{name}</strong>: {count}건 수집</li>")

        if briefing_items:
            lines.append(
                f'<div class="alert-box alert-info"><strong>{opener}</strong><ul>{"".join(briefing_items)}</ul></div>'
            )

        # P0 urgent alerts as red callout
        if priority_items.get("P0"):
            p0_html_items = []
            for item in priority_items["P0"][:3]:
                p0_title = item.get("title_ko") or item.get("title", "")
                link = item.get("link", "")
                desc = (item.get("description_ko") or item.get("description", "")).strip()
                # Build alert content: title + short description
                desc_part = ""
                if desc and desc != p0_title and desc != item.get("title", "") and len(desc) > 15:
                    desc_short = desc[:100] + "..." if len(desc) > 100 else desc
                    desc_part = f' <span class="p0-desc">{desc_short}</span>'
                if link:
                    p0_html_items.append(f'<li><a href="{link}">{p0_title}</a>{desc_part}</li>')
                else:
                    p0_html_items.append(f"<li>{p0_title}{desc_part}</li>")
            if p0_html_items:
                lines.append(
                    f'<div class="alert-box alert-urgent">'
                    f"<strong>긴급 알림</strong>"
                    f"<ul>{''.join(p0_html_items)}</ul></div>"
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
