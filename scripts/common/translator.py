"""English-to-Korean translation module with caching.

Translates news titles and descriptions using Google Translate
via the deep-translator library. Results are cached in
``_state/translation_cache.json`` to avoid redundant API calls.

Environment variable ``ENABLE_TRANSLATION`` (default ``true``)
can disable translation entirely for CI or testing.
"""

import hashlib
import json
import logging
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_CACHE_PATH = _REPO_ROOT / "_state" / "translation_cache.json"
_MAX_CACHE_ENTRIES = 5_000
_BATCH_SIZE = 5
_BATCH_DELAY = 0.3  # seconds between batches

TRANSLATION_ENABLED = os.getenv("ENABLE_TRANSLATION", "true").lower() in (
    "true",
    "1",
    "yes",
)

# ---------------------------------------------------------------------------
# Financial term overrides — preserved as-is through translation
# ---------------------------------------------------------------------------

TERM_OVERRIDES: Dict[str, str] = {
    # Crypto
    "Bitcoin": "비트코인",
    "Ethereum": "이더리움",
    "Solana": "솔라나",
    "Ripple": "리플",
    "Cardano": "카르다노",
    "Dogecoin": "도지코인",
    "Polkadot": "폴카닷",
    "Chainlink": "체인링크",
    "Avalanche": "아발란체",
    "Litecoin": "라이트코인",
    "Polygon": "폴리곤",
    "Uniswap": "유니스왑",
    "Aave": "에이브",
    "Tether": "테더",
    "Stablecoin": "스테이블코인",
    "Stablecoins": "스테이블코인",
    "Altcoin": "알트코인",
    "Altcoins": "알트코인",
    "DeFi": "디파이",
    "Memecoin": "밈코인",
    "Memecoins": "밈코인",
    # Indices & markets
    "S&P 500": "S&P 500",
    "NASDAQ": "나스닥",
    "Nasdaq": "나스닥",
    "Dow Jones": "다우존스",
    "Wall Street": "월스트리트",
    "NYSE": "NYSE",
    # Institutions
    "Fed": "연준",
    "Federal Reserve": "연준",
    "SEC": "SEC",
    "CFTC": "CFTC",
    "IMF": "IMF",
    "ECB": "ECB",
    "FOMC": "FOMC",
    "NATO": "NATO",
    "OPEC": "OPEC",
    "WHO": "WHO",
    "WTO": "WTO",
    "DOJ": "DOJ",
    "Bank of Korea": "한국은행",
    "Bank of Japan": "일본은행",
    "People's Bank of China": "중국인민은행",
    "World Bank": "세계은행",
    # SEC filing terms (keep as-is to prevent mistranslation)
    "Stock Titan": "Stock Titan",
    "Form 4": "Form 4",
    "Form 4/A": "Form 4/A",
    "Form 3": "Form 3",
    "Form 13F": "Form 13F",
    "Form 8-K": "Form 8-K",
    "Form 10-K": "Form 10-K",
    "Form 10-Q": "Form 10-Q",
    "Form S-1": "Form S-1",
    "Insider Trading": "내부자 거래",
    "insider trading": "내부자 거래",
    # Terms to keep as-is
    "ETF": "ETF",
    "NFT": "NFT",
    "BTC": "BTC",
    "ETH": "ETH",
    "SOL": "SOL",
    "XRP": "XRP",
    "DOGE": "DOGE",
    "ADA": "ADA",
    "USDT": "USDT",
    "USDC": "USDC",
    "IPO": "IPO",
    "GDP": "GDP",
    "CPI": "CPI",
    "PPI": "PPI",
    "PMI": "PMI",
    "PCE": "PCE",
    "AI": "AI",
    "CEO": "CEO",
    "CFO": "CFO",
    "API": "API",
    "TVL": "TVL",
    "HBM": "HBM",
    "ESG": "ESG",
    # Companies
    "Tesla": "테슬라",
    "Apple": "애플",
    "Microsoft": "마이크로소프트",
    "Google": "구글",
    "Alphabet": "알파벳",
    "Amazon": "아마존",
    "Meta": "메타",
    "Nvidia": "엔비디아",
    "NVIDIA": "엔비디아",
    "Samsung": "삼성",
    "TSMC": "TSMC",
    "Intel": "인텔",
    "AMD": "AMD",
    "Qualcomm": "퀄컴",
    "Broadcom": "브로드컴",
    "Micron": "마이크론",
    "Coinbase": "코인베이스",
    "Binance": "바이낸스",
    "BlackRock": "블랙록",
    "JPMorgan": "JP모건",
    "Goldman Sachs": "골드만삭스",
    "Morgan Stanley": "모건스탠리",
    "Citigroup": "시티그룹",
    "Berkshire Hathaway": "버크셔 해서웨이",
    # People
    "Trump": "트럼프",
    "Elon Musk": "일론 머스크",
    "Xi Jinping": "시진핑",
    "Xi": "시진핑",
    "Putin": "푸틴",
    "Zelensky": "젤렌스키",
    "Biden": "바이든",
    "Powell": "파월",
    "Yellen": "옐런",
    "Newsom": "뉴섬",
    "Booker": "부커",
    "Bessent": "베센트",
    "Rubio": "루비오",
    "Vance": "밴스",
    "Janet Yellen": "재닛 옐런",
    "Jerome Powell": "제롬 파월",
    "Christine Lagarde": "크리스틴 라가르드",
    "Warren Buffett": "워런 버핏",
    "Jamie Dimon": "제이미 다이먼",
    "Larry Fink": "래리 핑크",
    "Jensen Huang": "젠슨 황",
    "Tim Cook": "팀 쿡",
    "Satya Nadella": "사티아 나델라",
    "Mark Zuckerberg": "마크 저커버그",
    # General finance
    "Bullish": "강세",
    "Bearish": "약세",
    "Rally": "랠리",
    "Crash": "폭락",
    "Whale": "고래",
    "Whales": "고래",
    "Halving": "반감기",
    "Staking": "스테이킹",
    "Airdrop": "에어드롭",
    "Mainnet": "메인넷",
    "Testnet": "테스트넷",
    "Layer 2": "레이어2",
    "Layer-2": "레이어2",
    # Media names (prevent mistranslation)
    "Motley Fool": "Motley Fool",
    "The Motley Fool": "The Motley Fool",
    "Seeking Alpha": "Seeking Alpha",
    "CoinDesk": "CoinDesk",
    "CoinTelegraph": "CoinTelegraph",
    "Cointelegraph": "CoinTelegraph",
    "The Block": "The Block",
    "Decrypt": "Decrypt",
    "MarketWatch": "MarketWatch",
    "Barron's": "Barron's",
    "TheStreet": "TheStreet",
    "Benzinga": "Benzinga",
    "Investopedia": "Investopedia",
    "CoinMetrics": "CoinMetrics",
    # DeFi protocols, L1/L2 chains & bridges — proper nouns prone to MT mangling
    # (e.g. "Cetus Protocol", "Wormhole"). Matching is word-boundary + case-
    # insensitive, so names that collide with common English words are
    # DELIBERATELY EXCLUDED or qualified with a multi-word form to avoid false
    # positives like "market optimism" → "market 옵티미즘" or "yield curve" →
    # "yield 커브". Excluded bare: Optimism, Curve, Maker, Balancer, Yearn, Base,
    # Near, Compound, Convex, Harmony, Cosmos, Sui, TON, Blast, Jupiter.
    "Lido": "리도",
    "Arbitrum": "아비트럼",
    "Aptos": "앱토스",
    "Synthetix": "신세틱스",
    "Celestia": "셀레스티아",
    "Starknet": "스타크넷",
    "Fantom": "팬텀",
    "Tron": "트론",
    "PancakeSwap": "팬케이크스왑",
    "SushiSwap": "스시스왑",
    "MakerDAO": "MakerDAO",
    "zkSync": "zkSync",
    "EigenLayer": "EigenLayer",
    "Pendle": "Pendle",
    "Ethena": "Ethena",
    "GMX": "GMX",
    "dYdX": "dYdX",
    "Frax": "Frax",
    "1inch": "1inch",
    "Raydium": "Raydium",
    "Jito": "Jito",
    "Hyperliquid": "Hyperliquid",
    "Berachain": "Berachain",
    # Multi-word forms (avoid bare-word collisions)
    "Curve Finance": "Curve Finance",
    "Compound Finance": "Compound Finance",
    "Euler Finance": "Euler Finance",
    "Ondo Finance": "Ondo Finance",
    "NEAR Protocol": "NEAR Protocol",
    "Cetus Protocol": "Cetus Protocol",
    "Mango Markets": "Mango Markets",
    "Celsius Network": "Celsius Network",
    "Terra Luna": "Terra Luna",
    # Bridges / notable hack targets
    "Wormhole": "Wormhole",
    "Ronin Bridge": "Ronin Bridge",
    "Ronin Network": "Ronin Network",
    "Nomad Bridge": "Nomad Bridge",
    "Poly Network": "Poly Network",
    "Beanstalk": "Beanstalk",
    "Mt. Gox": "마운트곡스",
    "FTX": "FTX",
}

# Build case-insensitive lookup (key_lower -> (original_key, korean))
_TERM_LOOKUP: Dict[str, tuple] = {k.lower(): (k, v) for k, v in TERM_OVERRIDES.items()}

# ---------------------------------------------------------------------------
# Cache management
# ---------------------------------------------------------------------------

_cache: Optional[Dict[str, str]] = None
_cache_dirty = False

# Regex matching 3+ consecutive Latin-1 extended characters (U+00C0–U+00FF).
# A run of these in text that should be Korean/English strongly indicates
# mojibake (e.g. Latin-1 bytes re-decoded as UTF-8).
_MOJIBAKE_RE = re.compile(r"[\u00c0-\u00ff]{3,}")


def _is_mojibake(text: str) -> bool:
    """Return True if *text* looks like mojibake (corrupted encoding).

    Heuristic: a sequence of 3 or more characters from the Latin-1 extended
    block (U+00C0–U+00FF) inside a string that is supposed to be Korean or
    English is a reliable indicator that Latin-1 bytes were misinterpreted as
    UTF-8.  Legitimate Korean text never contains such runs.
    """
    if not text:
        return False
    return bool(_MOJIBAKE_RE.search(text))


def _cache_key(text: str) -> str:
    """SHA256 hash of text for cache key."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _load_cache() -> Dict[str, str]:
    """Load translation cache from disk, cleaning artifact-contaminated entries."""
    global _cache, _cache_dirty
    if _cache is not None:
        return _cache

    _cache = {}
    if _CACHE_PATH.exists():
        try:
            data = json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                _cache = data
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Translation cache load failed: %s", e)
            _cache = {}

    # Remove mojibake-corrupted entries before any further processing.
    mojibake_keys = [k for k, v in _cache.items() if _is_mojibake(v)]
    for k in mojibake_keys:
        del _cache[k]
    if mojibake_keys:
        _cache_dirty = True
        logger.warning(
            "Removed %d mojibake-corrupted entries from translation cache",
            len(mojibake_keys),
        )

    # Clean remaining entries with known translation artifacts.
    cleaned = 0
    keys_to_fix = []
    for key, value in _cache.items():
        fixed = _postprocess_translation(value)
        if fixed != value:
            keys_to_fix.append((key, fixed))
    for key, fixed in keys_to_fix:
        _cache[key] = fixed
        cleaned += 1
    if cleaned:
        _cache_dirty = True
        logger.info("Cleaned %d cached translations with artifacts", cleaned)

    logger.info("Translation cache loaded: %d entries", len(_cache))
    return _cache


def _save_cache() -> None:
    """Save translation cache atomically (temp file + rename)."""
    global _cache_dirty
    if not _cache_dirty or _cache is None:
        return

    # Evict oldest entries if over limit (FIFO order)
    if len(_cache) > _MAX_CACHE_ENTRIES:
        evict_count = len(_cache) - _MAX_CACHE_ENTRIES
        keys = list(_cache.keys())
        for k in keys[:evict_count]:
            del _cache[k]
        logger.info("Evicted %d old cache entries (limit: %d)", evict_count, _MAX_CACHE_ENTRIES)

    # Strip any mojibake entries that may have been inserted this session.
    bad_keys = [k for k, v in _cache.items() if _is_mojibake(v)]
    for k in bad_keys:
        del _cache[k]
    if bad_keys:
        logger.warning(
            "Skipped saving %d mojibake-corrupted entries from translation cache",
            len(bad_keys),
        )

    _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd, tmp = tempfile.mkstemp(dir=str(_CACHE_PATH.parent), suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(_cache, f, ensure_ascii=False)
        os.replace(tmp, str(_CACHE_PATH))
        _cache_dirty = False
    except OSError as e:
        logger.warning("Translation cache save failed: %s", e)


# ---------------------------------------------------------------------------
# Core translation
# ---------------------------------------------------------------------------


def _apply_term_overrides(text: str) -> tuple:
    """Replace known terms with placeholders before translation.

    Returns (modified_text, replacements) where replacements is a list
    of (placeholder, korean_term) tuples for post-translation restoration.

    Uses word boundaries (\\b) to prevent partial-word matches such as
    "AI" inside "gain" → "gAIn", or "SOL" inside "Gasoline" → "GaSOLine".
    """
    replacements = []
    result = text

    # Sort by length (longest first) to avoid partial matches
    sorted_terms = sorted(_TERM_LOOKUP.items(), key=lambda x: len(x[0]), reverse=True)

    for _lower_key, (original, korean) in sorted_terms:
        # Use word boundaries to prevent matching inside other words.
        # re.escape handles special chars (e.g. "S&P 500"); \b anchors to
        # word boundaries so "AI" won't match inside "gain" or "raise".
        escaped = re.escape(original)
        # Only wrap with \b when the term starts/ends with a word character
        left_b = r"\b" if re.match(r"\w", original[0]) else ""
        right_b = r"\b" if re.match(r"\w", original[-1]) else ""
        pattern = re.compile(left_b + escaped + right_b, re.IGNORECASE)
        if pattern.search(result):
            placeholder = f"__TERM{len(replacements)}__"
            result = pattern.sub(placeholder, result)
            replacements.append((placeholder, korean))

    return result, replacements


def _restore_terms(text: str, replacements: list) -> str:
    """Restore placeholders with Korean terms after translation."""
    result = text
    for placeholder, korean in replacements:
        result = result.replace(placeholder, korean)
    return result


# ---------------------------------------------------------------------------
# Post-processing: fix Google Translate artifacts
# ---------------------------------------------------------------------------

# Token-name artifacts that leak into translated text (e.g. "PAIrs", "BrAIn")
# These occur when \b word-boundary matching fails or from cached old translations
_TOKEN_ARTIFACT_MAP: Dict[str, str] = {
    # AI artifacts
    "PAIrs": "Pairs",
    "PAIr": "Pair",
    "pAIrs": "pairs",
    "pAIr": "pair",
    "MAIntenance": "Maintenance",
    "mAIntenance": "maintenance",
    "MAInnet": "Mainnet",
    "mAInnet": "mainnet",
    "BrAIn": "Brain",
    "brAIn": "brain",
    "ChAIn": "Chain",
    "chAIn": "chain",
    "ChAInlink": "Chainlink",
    "rAPId": "rapid",
    "RAPId": "Rapid",
    "RAIse": "Raise",
    "rAIse": "raise",
    "RAIses": "Raises",
    "rAIses": "raises",
    "RAIsed": "Raised",
    "rAIsed": "raised",
    "gAIn": "gain",
    "gAIns": "gains",
    "gAIned": "gained",
    "ChAIrman": "Chairman",
    "chAIrman": "chairman",
    "pAId": "paid",
    "sAId": "said",
    "mAIn": "main",
    "mAIntain": "maintain",
    "remAIn": "remain",
    "remAIns": "remains",
    "contAIn": "contain",
    "contAIns": "contains",
    "agAInst": "against",
    "AgAInst": "Against",
    "clAIm": "claim",
    "clAIms": "claims",
    "fAIl": "fail",
    "fAIled": "failed",
    "wAIt": "wait",
    "wAIting": "waiting",
    "trAIning": "training",
    "trAIned": "trained",
    "explAIn": "explain",
    "certAIn": "certain",
    "obtAIn": "obtain",
    "sustAIn": "sustain",
    "strAIght": "straight",
    "AIr": "Air",
    "aIr": "air",
    "DAIly": "Daily",
    "dAIly": "daily",
    "TakAIchi": "Takaichi",
    # SOL artifacts
    "SOLution": "Solution",
    "SOLutions": "Solutions",
    "reSOLve": "resolve",
    "reSOLved": "resolved",
    "conSOLidate": "consolidate",
    "conSOLidation": "consolidation",
    "abSOLute": "absolute",
    "SOLar": "solar",
    # XRP/ETH/DOT artifacts
    "XRPected": "Expected",
    "ETHical": "Ethical",
    # Additional AI artifacts (compound words)
    "entertAIn": "entertain",
    "entertAIns": "entertains",
    "entertAInment": "entertainment",
    "complAIn": "complain",
    "complAInt": "complaint",
    "complAIns": "complains",
    "portrAIt": "portrait",
    "curtAIn": "curtain",
    "mountAIn": "mountain",
    "fountAIn": "fountain",
    "captAIn": "captain",
    "certAInly": "certainly",
    "villAIn": "villain",
    "bargAIn": "bargain",
    "domAIn": "domain",
    "remAIning": "remaining",
    "remAInder": "remainder",
    "mAInstream": "mainstream",
    "mAInly": "mainly",
    "contAIner": "container",
    "contAIning": "containing",
    "detAIl": "detail",
    "detAIls": "details",
    "retAIl": "retail",
    "retAIler": "retailer",
    # DOT artifacts
    "DOTted": "Dotted",
    "anecDOTe": "anecdote",
}

# Media/source names that Google Translate incorrectly translates
_MEDIA_NAME_FIXES: Dict[str, str] = {
    "가지각색의 바보": "Motley Fool",
    "잡다한 바보": "Motley Fool",
    "얼룩덜룩한 바보": "Motley Fool",
    "알파 추구": "Seeking Alpha",
    "알파를 추구": "Seeking Alpha",
    "동전 데스크": "CoinDesk",
    "동전 텔레그래프": "CoinTelegraph",
    "동전 전보": "CoinTelegraph",
    "해독": "Decrypt",
    "더 블록": "The Block",
    "야후 재무": "Yahoo Finance",
    "야후 금융": "Yahoo Finance",
    "바론의": "Barron's",
    "배런의": "Barron's",
    "거리": "TheStreet",
    "벤징가": "Benzinga",
    "코인 메트릭스": "CoinMetrics",
    "코인 메트릭": "CoinMetrics",
    "디크립트": "Decrypt",
    "포브스 디지털": "Forbes Digital",
    "시장 감시": "MarketWatch",
    # SEC filing source names
    "재고 타이탄": "Stock Titan",
    "주식 타이탄": "Stock Titan",
    "스톡 타이탄": "Stock Titan",
    "내부자 무역": "내부자 거래",
    "투자자의 비즈니스 일간지": "Investor's Business Daily",
    "비즈니스 인사이더": "Business Insider",
    "월스트리트 저널": "Wall Street Journal",
    "뉴욕 타임스": "New York Times",
    "뉴욕 타임즈": "New York Times",
    "로이터": "Reuters",
    "더 가디언": "The Guardian",
    "인베스토피디아": "Investopedia",
}

# Awkward Korean patterns from machine translation → natural Korean
_KOREAN_STYLE_FIXES: list = [
    # "~의 짧은 붕괴" → "~의 단기 급락"
    (r"짧은 붕괴", "단기 급락"),
    # "$X를 넘어섰습니다" is OK, but "$X를 넘어섰다" needs 습니다 ending for news
    # "~할 수 있습니까" → "~할 수 있을까"
    (r"할 수 있습니까\??", "할 수 있을까?"),
    # "~하는 것이 더 나은 암호화폐" → "더 나은 투자 대상"
    (
        r"(?:지금\s+)?(?:\$[\d,]+로\s+)?(?:지금\s+)?구매하고\s+(\d+)년\s+동안\s+보유하는\s+것이\s+더\s+나은\s+암호화폐",
        r"\1년 장기 보유 시 더 유망한 암호화폐",
    ),
    # "~인가요?" → "~일까?" (more natural for news headlines)
    (r"(\S+)인가요\?", r"\1일까?"),
    # Remove trailing "- 나스닥", "- 알파 추구" etc. (source names that leaked)
    (r"\s*[-–—]\s*(?:나스닥|알파 추구|가지각색의 바보|야후 파이낸스)\s*$", ""),
    # "~달러 상당의" → "~달러 규모"
    (r"달러 상당의", "달러 규모"),
    # "~가 빠져나갔다고 연구원들이 밝혔습니다" → cleaner ending
    (r"밝혔습니다\.\s*$", "밝혔습니다"),
    # Korean particle corrections for names without 받침 (final consonant)
    # 트럼프(no 받침) → 는/가/를, not 은/이/을
    (r"트럼프은\b", "트럼프는"),
    (r"트럼프을\b", "트럼프를"),
    (r"트럼프이\b", "트럼프가"),
    (r"오바마은\b", "오바마는"),
    (r"오바마이\b", "오바마가"),
    (r"테슬라은\b", "테슬라는"),
    (r"테슬라이\b", "테슬라가"),
    (r"엔비디아은\b", "엔비디아는"),
    (r"엔비디아이\b", "엔비디아가"),
    (r"메타은\b", "메타는"),
    (r"메타이\b", "메타가"),
    # Additional names without 받침 → correct particles
    (r"카르다노은\b", "카르다노는"),
    (r"카르다노이\b", "카르다노가"),
    (r"솔라나은\b", "솔라나는"),
    (r"솔라나이\b", "솔라나가"),
    (r"아발란체은\b", "아발란체는"),
    (r"아발란체이\b", "아발란체가"),
    (r"코인베이스은\b", "코인베이스는"),
    (r"코인베이스이\b", "코인베이스가"),
    (r"바이낸스은\b", "바이낸스는"),
    (r"바이낸스이\b", "바이낸스가"),
    # "시과의" → "시진핑과의" (Xi mistranslation)
    (r"시과의", "시진핑과의"),
    (r"시과 ", "시진핑과 "),
    # Awkward interrogative "무엇을 말했습니까?" → "어떤 입장을 밝혔나?"
    (r"무엇을 말했습니까\??", "어떤 입장을 밝혔나?"),
    (r"말했습니까\?", "밝혔나?"),
    # "그리고 버거는." and similar "And X is/are." direct translation artifacts
    (r"^그리고 ", ""),  # Remove leading "그리고" (And) from headlines
    # Fix European-style number formatting artifact from Google Translate:
    # e.g. "BTC$71.018,21" → "BTC $71,018.21" (dots=thousands, comma=decimal → US format)
    (r"([A-Z]{2,5})\$(\d{1,3})\.(\d{3}),(\d{2})\b", r"\1 $\2,\3.\4"),
    # Same pattern without ticker prefix: "$71.018,21" → "$71,018.21"
    (r"\$(\d{1,3})\.(\d{3}),(\d{2})\b", r"$\1,\2.\3"),
    # Double spaces
    (r"\s{2,}", " "),
]


def _postprocess_translation(text: str) -> str:
    """Fix common Google Translate artifacts in Korean translations.

    Applied after term restoration, this function:
    1. Fixes token-name artifacts (PAIrs → Pairs)
    2. Corrects mistranslated media/source names
    3. Improves awkward Korean phrasing patterns
    """

    if not text:
        return text

    # 1. Fix token artifacts (case-sensitive replacements)
    for wrong, correct in _TOKEN_ARTIFACT_MAP.items():
        if wrong in text:
            text = text.replace(wrong, correct)

    # 2. Fix mistranslated media names
    for wrong, correct in _MEDIA_NAME_FIXES.items():
        if wrong in text:
            text = text.replace(wrong, correct)

    # 3. Apply Korean style fixes (regex-based)
    for pattern, replacement in _KOREAN_STYLE_FIXES:
        text = re.sub(pattern, replacement, text)

    return text.strip()


def translate_to_korean(text: str) -> str:
    """Translate English text to Korean. Returns original on failure.

    Uses Google Translate via deep-translator with term override
    protection and result caching.
    """
    if not text or not text.strip():
        return text

    if not TRANSLATION_ENABLED:
        return text

    # Check cache first
    cache = _load_cache()
    key = _cache_key(text)
    if key in cache:
        return cache[key]

    try:
        from deep_translator import GoogleTranslator

        # Protect known terms with placeholders
        modified, replacements = _apply_term_overrides(text)

        translated = GoogleTranslator(source="en", target="ko").translate(modified)

        if translated:
            # Restore Korean terms from placeholders
            result = _restore_terms(translated, replacements)
            # Post-process to fix Google Translate artifacts
            result = _postprocess_translation(result)

            # Cache the result and flush to disk
            global _cache_dirty
            cache[key] = result
            _cache_dirty = True
            _save_cache()

            return result
    except Exception as e:  # noqa: BLE001
        logger.debug("Translation failed for '%s': %s", text[:50], e)

    return text


def translate_batch(texts: List[str]) -> List[str]:
    """Translate a list of English texts to Korean.

    Processes in batches of 5 with 0.3s delay between batches
    to avoid rate limiting. Skips already-cached texts.
    """
    if not texts or not TRANSLATION_ENABLED:
        return list(texts)

    results = list(texts)  # copy — fallback is original
    cache = _load_cache()

    # Identify which texts need translation (not cached, not empty)
    to_translate: List[tuple] = []  # (index, text)
    for i, text in enumerate(texts):
        if not text or not text.strip():
            continue
        key = _cache_key(text)
        if key in cache:
            results[i] = cache[key]
        else:
            to_translate.append((i, text))

    if not to_translate:
        return results

    # Translate in batches
    for batch_start in range(0, len(to_translate), _BATCH_SIZE):
        batch = to_translate[batch_start : batch_start + _BATCH_SIZE]

        if batch_start > 0:
            time.sleep(_BATCH_DELAY)

        for idx, text in batch:
            translated = translate_to_korean(text)
            results[idx] = translated

    _save_cache()
    return results


_NON_TRANSLATABLE_LINE_RE = re.compile(r"^(?:#{1,6}\s|```|<[^>]+>|\|.*\||!\[.*\]\(|\[.*\]\(|https?://)")
_LEADING_MARKER_RE = re.compile(r"^(\s*(?:[-*+]\s+|\d+[.)]\s+|>\s+)?)")
_ENGLISH_SENTENCE_RE = re.compile(r"[A-Za-z][A-Za-z'’-]+")


def _should_translate_body_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped or _NON_TRANSLATABLE_LINE_RE.match(stripped):
        return False
    if "](" in stripped or "<picture" in stripped or "<img" in stripped:
        return False
    if re.search(r"[가-힣]", stripped):
        return False
    words = _ENGLISH_SENTENCE_RE.findall(stripped)
    return len(words) >= 4 and len(" ".join(words)) >= 24


def translate_untranslated_body(content: str) -> str:
    """Translate obvious English prose lines in markdown body content.

    Keeps markdown structure intact and only translates English-dominant lines
    that look like prose, while skipping links, HTML, tables, and image markup.
    """
    if not content or not TRANSLATION_ENABLED:
        return content

    lines = content.splitlines()
    targets: List[int] = []
    payloads: List[str] = []

    for idx, line in enumerate(lines):
        if not _should_translate_body_line(line):
            continue
        marker_match = _LEADING_MARKER_RE.match(line)
        marker = marker_match.group(1) if marker_match else ""
        payload = line[len(marker) :].strip()
        if not payload:
            continue
        targets.append(idx)
        payloads.append(payload)

    if not payloads:
        return content

    translated = translate_batch(payloads)
    for idx, translated_line in zip(targets, translated, strict=False):
        marker_match = _LEADING_MARKER_RE.match(lines[idx])
        marker = marker_match.group(1) if marker_match else ""
        lines[idx] = f"{marker}{translated_line.strip()}"

    return "\n".join(lines)


def get_display_title(item: Dict[str, Any]) -> str:
    """Return Korean title if available, otherwise original title."""
    return item.get("title_ko") or item.get("title", "")


def get_display_description(item: Dict[str, Any]) -> str:
    """Return Korean description if available, otherwise original."""
    return item.get("description_ko") or item.get("description", "")


def save_translation_cache() -> None:
    """Flush any pending cache writes to disk.

    Call this at the end of a collection run to ensure all
    translations are persisted.
    """
    _save_cache()
