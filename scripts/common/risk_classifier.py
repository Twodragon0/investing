"""Risk classifier for news items — Phase 1 skeleton.

Computes a weighted impact score per item and aggregates into a RiskVerdict.
summarizer.py integration is deferred to Phase 3.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Literal

from scripts.common.config import setup_logging

setup_logging()
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Threshold initial values — tune in Phase 2 based on 30-day distribution.
P0_ITEM_THRESHOLD = 5.0
ELEVATED_ITEM_THRESHOLD = 3.5
CRITICAL_MEAN_TOP_3 = 6.0

# Scoring weights — §5-3
WEIGHTS: dict[str, Any] = {
    "source_base": (0.5, 2.5),  # (min_clip, max_clip)
    "amount": 2.0,
    "institution": 1.5,
    "market_mechanism": 2.5,
    "opinion_penalty": -2.0,  # relaxed from -3.0: "says"-type markers are common in titles
    "entertainment_penalty": -4.0,
    "sentiment_pos_penalty": -1.0,  # relaxed from -1.5: positive crypto news less aggressively dampened
    "sentiment_neg_bonus": 1.0,  # raised from +0.5: strengthen signal for hack/crash/lawsuit items
}

# Source type → base weight mapping (6-type from markdown_utils._SOURCE_RULES)
_SOURCE_TYPE_WEIGHTS: dict[str, float] = {
    "regulator": 2.5,
    "finance-media": 2.0,
    "crypto-media": 1.5,
    "exchange": 1.3,
    "world-media": 1.5,
    "kr-media": 1.2,
    "aggregator": 1.0,
    "default": 1.0,
}

# Fallback per-domain weights (from summarizer._SOURCE_WEIGHTS, kept for compat)
_DOMAIN_WEIGHTS: dict[str, float] = {
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

# Opinion / personal-commentary markers — §5-2
_OPINION_MARKERS: frozenset[str] = frozenset(
    {
        # English
        "says",
        "opinion",
        "column",
        "editorial",
        "interview",
        "predicts",
        "claims",
        "thinks",
        "argues",
        "warns that",
        "according to",
        # Korean
        "말합니다",
        "주장",
        "인터뷰",
        "칼럼",
        "오피니언",
        "예상",
        "전망",
        "라고 밝혔",
        "밝혔다",
        "라고 평",
        "시각",
        "관점",
    }
)

# Security exploit / attack signal terms — §5-5-A S8
_SECURITY_EXPLOIT_TERMS: frozenset[str] = frozenset(
    {
        # English
        "hack",
        "hacked",
        "hacking",
        "exploit",
        "exploited",
        "drain",
        "drained",
        "draining",
        "bridge exploit",
        "rug pull",
        "rugpull",
        "breach",
        "breached",
        "heist",
        "stolen",
        "theft",
        "compromised",
        "compromise",
        # Korean
        "해킹",
        "탈취",
        "유출",
        "익스플로잇",
        "러그풀",
        "도난",
    }
)

# Market-structure mechanism triggers — §5-2
_MARKET_MECHANISM: frozenset[str] = frozenset(
    {
        "circuit breaker",
        "서킷브레이커",
        "사이드카",
        "trading halt",
        "거래 중단",
        "거래 정지",
        "bank run",
        "뱅크런",
        "flash crash",
        "withdrawal halt",
        "출금 중단",
    }
)

# Dollar / percentage amount pattern — §5-2
_AMOUNT_RE = re.compile(
    r"\$[\d,.]+\s*(?:billion|million|B\b|M\b)"
    r"|\d+\s*(?:억|조)\s*(?:달러|원)"
    r"|[+-]?\d+\.?\d+%",
    re.IGNORECASE,
)

# Institutional / regulatory entities — from entity_extractor._ORG_ENTITIES
_ORG_ENTITY_TERMS: list[str] = [
    # English
    "Fed",
    "Federal Reserve",
    "FOMC",
    "SEC",
    "ECB",
    "BOJ",
    "BOK",
    "IMF",
    "World Bank",
    "CFTC",
    "FCA",
    "ESMA",
    "BIS",
    # Korean
    "연준",
    "증권거래위원회",
    "유럽중앙은행",
    "일본은행",
    "한국은행",
    "금감원",
    "금융위",
    "금융위원회",
    "금융감독원",
    "한은",
]

# Positive / negative sentiment keywords (from summarizer._SENTIMENT_POS/NEG)
_SENTIMENT_POS: frozenset[str] = frozenset(
    {
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
)

_SENTIMENT_NEG: frozenset[str] = frozenset(
    {
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
)

# Entertainment keywords (subset from content_filters._DEFAULT_ENTERTAINMENT_KEYWORDS)
_ENTERTAINMENT_KEYWORDS: frozenset[str] = frozenset(
    {
        "oscar",
        "grammy",
        "emmy",
        "golden globe",
        "cannes",
        "celebrity",
        "reality tv",
        "tv show",
        "movie",
        "album",
        "billboard",
        "netflix",
        "spotify",
        "nba",
        "nfl",
        "mlb",
        "nhl",
        "mls",
        "ufc",
        "fifa",
        "premier league",
        "super bowl",
        "world series",
        "playoffs",
        "lakers",
        "celtics",
        "yankees",
        "dodgers",
        "taylor swift concert",
        "met gala",
        "celebrity gossip",
        "celebrity drama",
    }
)

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RiskSignals:
    """Extracted boolean/categorical signals for a single news item."""

    source_weight: float  # S1 — authority multiplier
    has_amount: bool  # S2 — concrete dollar/% figure
    has_institution: bool  # S3 — regulatory/institutional entity
    market_mechanism: bool  # S4 — circuit breaker / halt / bank-run
    is_opinion: bool  # S5 — personal opinion / commentary (cleared by S3)
    is_entertainment: bool  # S6 — sports / pop-culture noise
    sentiment: Literal["pos", "neg", "neu"]  # S7
    security_exploit: bool  # S8 — hack / exploit / drain / rug-pull (§5-5-A)


@dataclass(frozen=True)
class ItemScore:
    """Score result for one item."""

    item_id: str
    score: float  # 0.0 – 10.0 (clipped)
    signals: RiskSignals
    contributions: dict[str, float]  # per-signal contribution
    rule_overrides: list[str]  # applied override tags


@dataclass(frozen=True)
class RiskVerdict:
    """Aggregated risk verdict for the full item set."""

    level: Literal["critical", "elevated", "moderate", "low"]
    reason: str
    top_items: list[ItemScore]  # descending by score
    aggregate_mean: float  # mean of top-3 scores
    rule_trace: list[str]  # applied override rule tags


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_source_weight(source: str) -> float:
    """Return base weight for a source string using 6-type classification."""
    # Lazy import to avoid circular dependency with markdown_utils
    try:
        from scripts.common.markdown_utils import _classify_source  # type: ignore[import]

        src_type = _classify_source(source)
        weight = _SOURCE_TYPE_WEIGHTS.get(src_type, 1.0)
    except Exception:
        weight = 1.0

    # Fallback: per-domain override (catches named sources not yet in _SOURCE_RULES)
    src_low = source.lower()
    for domain, w in _DOMAIN_WEIGHTS.items():
        if domain in src_low:
            weight = max(weight, w)
            break

    # Clip to (0.5, 2.5)
    lo, hi = WEIGHTS["source_base"]
    return max(lo, min(hi, weight))


def _has_institution(text: str) -> bool:
    """Return True when text mentions a regulatory / institutional entity."""
    return any(_word_present(term, text) for term in _ORG_ENTITY_TERMS)


def _word_present(term: str, text: str) -> bool:
    """Check presence with light word-boundary handling for mixed ko/en."""
    if not term:
        return False
    # English: use \b word boundaries
    if term.isascii():
        pattern = re.compile(r"\b" + re.escape(term) + r"\b", re.IGNORECASE)
        return bool(pattern.search(text))
    # Korean: check surrounding chars are whitespace / punctuation / start-end
    idx = text.find(term)
    if idx == -1:
        return False
    pre_ok = idx == 0 or not text[idx - 1].isalpha()
    post_idx = idx + len(term)
    post_ok = post_idx >= len(text) or not text[post_idx].isalpha()
    return pre_ok and post_ok


def _detect_sentiment(text: str) -> Literal["pos", "neg", "neu"]:
    """Classify sentiment as pos / neg / neu from keyword presence."""
    pos_hits = sum(1 for kw in _SENTIMENT_POS if kw in text.lower())
    neg_hits = sum(1 for kw in _SENTIMENT_NEG if kw in text.lower())
    if pos_hits > neg_hits:
        return "pos"
    if neg_hits > pos_hits:
        return "neg"
    return "neu"


def _downgrade_one(level: str) -> str:
    """Demote risk level by one tier."""
    return {"critical": "elevated", "elevated": "moderate", "moderate": "low", "low": "low"}[level]


def _item_text(item: dict[str, Any]) -> str:
    """Build combined text for signal extraction (title-first, no duplication)."""
    title = item.get("title", "")
    title_original = item.get("title_original", "")
    description = item.get("description", "")
    # Avoid counting title twice when title_original is the same (F5 mitigation)
    if title_original.strip().lower() == title.strip().lower():
        title_original = ""
    return f"{title} {title_original} {description}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def extract_signals(
    item: dict[str, Any],
    sentiment_fn: Any = None,
    source_classifier: Any = None,
) -> RiskSignals:
    """Extract structured risk signals from a single news item dict.

    sentiment_fn and source_classifier are optional callables for extension;
    built-in heuristics are used when they are None.
    """
    source = item.get("source", "")
    text = _item_text(item)
    text_low = text.lower()

    source_weight = _resolve_source_weight(source) if source_classifier is None else _resolve_source_weight(source)

    has_amount = bool(_AMOUNT_RE.search(text))
    has_inst = _has_institution(text)
    market_mech = any(kw in text_low for kw in _MARKET_MECHANISM)
    sec_exploit = any(kw in text_low for kw in _SECURITY_EXPLOIT_TERMS)
    is_entertain = any(_word_present(kw, text) for kw in _ENTERTAINMENT_KEYWORDS)

    # Opinion detection
    is_opinion = any(_word_present(marker, text) for marker in _OPINION_MARKERS)
    # R2 mitigation: institution mention overrides opinion flag
    if has_inst:
        is_opinion = False

    # Sentiment
    if sentiment_fn is not None:
        try:
            raw = sentiment_fn(item)
            sentiment: Literal["pos", "neg", "neu"] = raw if raw in ("pos", "neg", "neu") else "neu"
        except Exception:
            sentiment = _detect_sentiment(text)
    else:
        sentiment = _detect_sentiment(text)

    return RiskSignals(
        source_weight=source_weight,
        has_amount=has_amount,
        has_institution=has_inst,
        market_mechanism=market_mech,
        is_opinion=is_opinion,
        is_entertainment=is_entertain,
        sentiment=sentiment,
        security_exploit=sec_exploit,
    )


def score_item(
    item: dict[str, Any],
    item_id: str | None = None,
    sentiment_fn: Any = None,
    source_classifier: Any = None,
) -> ItemScore:
    """Compute a 0–10 impact score for a single news item."""
    if item_id is None:
        item_id = item.get("id", item.get("url", item.get("title", "unknown")))

    signals = extract_signals(item, sentiment_fn=sentiment_fn, source_classifier=source_classifier)
    contributions: dict[str, float] = {}

    # S1 — source base
    contributions["source"] = signals.source_weight

    # S2 — concrete amount
    amt = WEIGHTS["amount"] if signals.has_amount else 0.0
    contributions["amount"] = amt

    # S3 — institutional entity
    inst = WEIGHTS["institution"] if signals.has_institution else 0.0
    contributions["institution"] = inst

    # S4 — market mechanism
    mech = WEIGHTS["market_mechanism"] if signals.market_mechanism else 0.0
    contributions["market_mechanism"] = mech

    # S5 — opinion penalty
    op = WEIGHTS["opinion_penalty"] if signals.is_opinion else 0.0
    contributions["opinion_penalty"] = op

    # S6 — entertainment penalty
    ent = WEIGHTS["entertainment_penalty"] if signals.is_entertainment else 0.0
    contributions["entertainment_penalty"] = ent

    # S7 — sentiment
    if signals.sentiment == "pos":
        sent = WEIGHTS["sentiment_pos_penalty"]
    elif signals.sentiment == "neg":
        sent = WEIGHTS["sentiment_neg_bonus"]
    else:
        sent = 0.0
    contributions["sentiment"] = sent

    raw_score = sum(contributions.values())
    clipped = max(0.0, min(10.0, raw_score))

    return ItemScore(
        item_id=str(item_id),
        score=clipped,
        signals=signals,
        contributions=contributions,
        rule_overrides=[],
    )


def apply_overrides(
    scores: list[ItemScore],
    base_level: str,
) -> tuple[str, list[str]]:
    """Apply rule-based overrides on top of weighted-sum base level.

    Rule 6: market_mechanism + source_weight >= 1.5 → hard CRITICAL.
    Rule 7: majority of P0-like items are opinion → downgrade one tier.
    """
    trace: list[str] = []

    # Rule 6 — hard critical for structural market events from credible sources
    hard_critical = [s for s in scores if s.signals.market_mechanism and s.signals.source_weight >= 1.5]
    if hard_critical:
        trace.append("rule_6_market_mechanism_hard_override")
        return "critical", trace

    # Rule 6b — security exploit + amount + credible source → hard CRITICAL
    sec_critical = [
        s for s in scores if s.signals.security_exploit and s.signals.has_amount and s.signals.source_weight >= 1.5
    ]
    if sec_critical:
        trace.append("rule_6b_security_exploit_hard_override")
        return "critical", trace

    # Rule 7 — opinion majority among high-scoring items triggers downgrade
    p0_like = [s for s in scores if s.score >= P0_ITEM_THRESHOLD]
    if p0_like:
        opinion_ratio = sum(1 for s in p0_like if s.signals.is_opinion) / len(p0_like)
        if opinion_ratio > 0.5:
            trace.append(f"rule_7_opinion_ratio={opinion_ratio:.2f}_downgrade")
            return _downgrade_one(base_level), trace

    return base_level, trace


def classify_risk(
    items: list[dict[str, Any]],
    priority_items: dict[str, Any] | None = None,
    sentiment_fn: Any = None,
    source_classifier: Any = None,
) -> RiskVerdict:
    """Classify overall risk level for a list of news items.

    Returns RiskVerdict with level, top_items (score-descending), and rule_trace.
    """
    if not items:
        return RiskVerdict(
            level="low",
            reason="no items",
            top_items=[],
            aggregate_mean=0.0,
            rule_trace=[],
        )

    # Score all items
    scored: list[ItemScore] = []
    for i, item in enumerate(items):
        item_id = item.get("id", item.get("url", f"item_{i}"))
        scored.append(score_item(item, item_id=item_id, sentiment_fn=sentiment_fn, source_classifier=source_classifier))

    # Sort descending by score
    sorted_scores = sorted(scored, key=lambda x: x.score, reverse=True)

    # Aggregate mean of top-3
    top3 = sorted_scores[:3]
    aggregate_mean = sum(s.score for s in top3) / len(top3) if top3 else 0.0

    # Determine base level from weighted-sum scores
    p0_items = [s for s in sorted_scores if s.score >= P0_ITEM_THRESHOLD]
    elevated_items = [s for s in sorted_scores if s.score >= ELEVATED_ITEM_THRESHOLD]

    if len(p0_items) >= 3 and aggregate_mean >= CRITICAL_MEAN_TOP_3:
        base_level = "critical"
        reason = f"{len(p0_items)} high-score items, mean_top3={aggregate_mean:.2f}"
    elif p0_items:
        base_level = "elevated"
        reason = f"{len(p0_items)} items above P0 threshold"
    elif len(elevated_items) >= 5:
        base_level = "elevated"
        reason = f"{len(elevated_items)} items above elevated threshold"
    elif len(elevated_items) >= 2:
        base_level = "moderate"
        reason = f"{len(elevated_items)} items above elevated threshold"
    else:
        base_level = "low"
        reason = "no significant items"

    # Apply rule overrides
    final_level, rule_trace = apply_overrides(sorted_scores, base_level)

    logger.info(
        "risk_level=%s base=%s mean_top3=%.2f rules=%s",
        final_level,
        base_level,
        aggregate_mean,
        rule_trace,
    )

    return RiskVerdict(
        level=final_level,
        reason=reason,
        top_items=sorted_scores,
        aggregate_mean=aggregate_mean,
        rule_trace=rule_trace,
    )
