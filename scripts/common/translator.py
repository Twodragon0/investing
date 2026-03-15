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
    # Terms to keep as-is
    "ETF": "ETF",
    "NFT": "NFT",
    "BTC": "BTC",
    "ETH": "ETH",
    "SOL": "SOL",
    "XRP": "XRP",
    "IPO": "IPO",
    "GDP": "GDP",
    "CPI": "CPI",
    "AI": "AI",
    "CEO": "CEO",
    "API": "API",
    "TVL": "TVL",
    # Companies
    "Tesla": "테슬라",
    "Apple": "애플",
    "Microsoft": "마이크로소프트",
    "Google": "구글",
    "Amazon": "아마존",
    "Meta": "메타",
    "Nvidia": "엔비디아",
    "NVIDIA": "엔비디아",
    # People
    "Trump": "트럼프",
    "Elon Musk": "일론 머스크",
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
}

# Build case-insensitive lookup (key_lower -> (original_key, korean))
_TERM_LOOKUP: Dict[str, tuple] = {k.lower(): (k, v) for k, v in TERM_OVERRIDES.items()}

# ---------------------------------------------------------------------------
# Cache management
# ---------------------------------------------------------------------------

_cache: Optional[Dict[str, str]] = None
_cache_dirty = False


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

    # Clean existing cache entries with known artifacts
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

    import re

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
    import re

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
