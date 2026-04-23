"""Tests for scripts/common/risk_classifier.py — Phase 1.

Layer 1: Signal extraction (18+ tests)
Layer 2: Score calculation (8+ tests)
Layer 3: Override rules (4+ tests)
Layer 4: classify_risk integration (3+ tests)
"""

from __future__ import annotations

import pathlib

from scripts.common.risk_classifier import (
    _AMOUNT_RE,
    P0_ITEM_THRESHOLD,
    ItemScore,
    RiskSignals,
    _downgrade_one,
    apply_overrides,
    classify_risk,
    extract_signals,
    score_item,
)

# ---------------------------------------------------------------------------
# Regression: #773 — risk_classifier.py must use relative imports.
# ---------------------------------------------------------------------------


def test_risk_classifier_uses_relative_imports():
    """risk_classifier.py must import config via relative import.

    Regression for PR #773. The absolute form `from scripts.common.config`
    fails with ModuleNotFoundError when collect_regulatory.py invokes
    summarizer.py which lazy-imports risk_classifier in package context
    (the `scripts` namespace is not on sys.path at that point).
    """
    src_path = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "common" / "risk_classifier.py"
    content = src_path.read_text(encoding="utf-8")
    assert "from scripts.common" not in content, "risk_classifier.py must use relative imports (regression for #773)"
    assert "from .config import" in content, "risk_classifier.py must import config via relative import (from .config)"


def test_risk_classifier_lazy_import_chain_works():
    """Exercise summarizer's lazy `from .risk_classifier import classify_risk`.

    Regression for #773. The production failure chain was:
        collect_regulatory.py
          → ThemeSummarizer.generate_executive_summary()
            → self._assess_risk_level(priority_items)
              → `from .risk_classifier import classify_risk`  # lazy
                → risk_classifier.py top-level `from scripts.common.config …`
                → ModuleNotFoundError: No module named 'scripts'

    If risk_classifier ever re-acquires an absolute `scripts.*` import,
    re-importing it here will raise ModuleNotFoundError and fail this test.
    """
    import importlib
    import sys

    # Drop cached risk_classifier so its top-level imports are re-executed.
    sys.modules.pop("scripts.common.risk_classifier", None)

    # Summarizer lazy-imports risk_classifier from inside _assess_risk_level.
    from scripts.common import summarizer as _summarizer  # noqa: F401

    module = importlib.import_module("scripts.common.risk_classifier")
    assert callable(module.classify_risk)

    verdict = module.classify_risk(items=[], priority_items={})
    assert verdict.level in {"critical", "elevated", "normal", "low"}


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def make_item(title: str = "", description: str = "", source: str = "google news", title_original: str = "") -> dict:
    return {"title": title, "description": description, "source": source, "title_original": title_original}


def _make_score(
    score: float,
    is_opinion: bool = False,
    market_mech: bool = False,
    src_weight: float = 1.0,
    has_amount: bool = False,
    security_exploit: bool = False,
) -> ItemScore:
    """Build a minimal ItemScore for override-rule tests."""
    signals = RiskSignals(
        source_weight=src_weight,
        has_amount=has_amount,
        has_institution=False,
        market_mechanism=market_mech,
        is_opinion=is_opinion,
        is_entertainment=False,
        sentiment="neu",
        security_exploit=security_exploit,
    )
    return ItemScore(
        item_id="test",
        score=score,
        signals=signals,
        contributions={},
        rule_overrides=[],
    )


# ===========================================================================
# Layer 1 — Signal extraction
# ===========================================================================


class TestExtractSignals:
    # --- Opinion markers ---

    def test_opinion_marker_english_says(self):
        item = make_item(title="Analyst says Bitcoin will crash")
        sig = extract_signals(item)
        assert sig.is_opinion is True

    def test_opinion_marker_english_predicts(self):
        item = make_item(title="Whale predicts 50% correction by Q4")
        sig = extract_signals(item)
        assert sig.is_opinion is True

    def test_opinion_marker_korean(self):
        item = make_item(title="O.C. Guy는 비트코인이 '여전히 폰지 사기'라고 말합니다.")
        sig = extract_signals(item)
        assert sig.is_opinion is True

    def test_opinion_marker_korean_interview(self):
        item = make_item(title="배우 A와의 인터뷰: 가상자산은 도박이다")
        sig = extract_signals(item)
        assert sig.is_opinion is True

    def test_opinion_marker_mixed(self):
        item = make_item(title="Expert says 비트코인 주장이 맞다")
        sig = extract_signals(item)
        assert sig.is_opinion is True

    def test_opinion_not_triggered_on_neutral_title(self):
        item = make_item(title="Bitcoin reaches $75,000 all-time high")
        sig = extract_signals(item)
        assert sig.is_opinion is False

    # --- R2 mitigation: institution suppresses opinion ---

    def test_r2_sec_chair_says_not_opinion(self):
        """SEC entity presence clears the opinion flag — §7 R2 mitigation."""
        item = make_item(title="SEC Chair says crypto regulation is coming")
        sig = extract_signals(item)
        # 'says' would normally flag opinion, but SEC is an institution
        assert sig.is_opinion is False
        assert sig.has_institution is True

    def test_r2_fed_statement_not_opinion(self):
        item = make_item(title="Federal Reserve warns that rate hike imminent")
        sig = extract_signals(item)
        assert sig.is_opinion is False
        assert sig.has_institution is True

    # --- Amount regex ---

    def test_amount_usd_million(self):
        assert _AMOUNT_RE.search("$280 million drained from protocol") is not None

    def test_amount_usd_billion(self):
        assert _AMOUNT_RE.search("$1.2 billion exploit confirmed") is not None

    def test_amount_usd_short_M(self):
        assert _AMOUNT_RE.search("$50M stolen in hack") is not None

    def test_amount_korean_eok_dollar(self):
        assert _AMOUNT_RE.search("2억 달러 규모 드리프트 프로토콜 악용") is not None

    def test_amount_percentage(self):
        assert _AMOUNT_RE.search("BTC -15.3% in 1h") is not None

    def test_amount_positive_percent(self):
        assert _AMOUNT_RE.search("ETH +5.3% surge") is not None

    def test_amount_not_matched_plain_number(self):
        assert _AMOUNT_RE.search("3 users reported an issue") is None

    def test_amount_detected_in_item(self):
        item = make_item(title="$280M DeFi exploit confirmed")
        sig = extract_signals(item)
        assert sig.has_amount is True

    # --- Institutional entity ---

    def test_institution_sec_detected(self):
        item = make_item(title="SEC files charges against exchange")
        sig = extract_signals(item)
        assert sig.has_institution is True

    def test_institution_korean_gamsawon(self):
        item = make_item(title="금감원, 가상자산 거래소 조사 착수")
        sig = extract_signals(item)
        assert sig.has_institution is True

    def test_institution_ecb_detected(self):
        item = make_item(title="ECB announces new digital euro regulations")
        sig = extract_signals(item)
        assert sig.has_institution is True

    def test_institution_not_triggered_on_random_text(self):
        item = make_item(title="Local trader buys 10 BTC")
        sig = extract_signals(item)
        assert sig.has_institution is False

    # --- Market mechanism ---

    def test_market_mechanism_circuit_breaker(self):
        item = make_item(title="NYSE circuit breaker triggered after Nasdaq drop")
        sig = extract_signals(item)
        assert sig.market_mechanism is True

    def test_market_mechanism_bank_run(self):
        item = make_item(title="Bank run fears spread across regional banks")
        sig = extract_signals(item)
        assert sig.market_mechanism is True

    def test_market_mechanism_flash_crash(self):
        item = make_item(title="Flash crash wipes 8% off BTC in minutes")
        sig = extract_signals(item)
        assert sig.market_mechanism is True

    def test_market_mechanism_korean_bangkeurun(self):
        item = make_item(title="업비트에서 뱅크런 공포 확산")
        sig = extract_signals(item)
        assert sig.market_mechanism is True

    def test_market_mechanism_not_triggered(self):
        item = make_item(title="Bitcoin price stabilizes after weekend dip")
        sig = extract_signals(item)
        assert sig.market_mechanism is False

    # --- Entertainment ---

    def test_entertainment_celebrity_detected(self):
        item = make_item(title="Celebrity gossip: star invests in meme coin")
        sig = extract_signals(item)
        assert sig.is_entertainment is True

    def test_entertainment_sports_detected(self):
        item = make_item(title="NBA star launches new NFT collection")
        sig = extract_signals(item)
        assert sig.is_entertainment is True

    def test_entertainment_not_triggered_on_finance_news(self):
        item = make_item(title="Bitcoin ETF sees $1.2B inflows this week")
        sig = extract_signals(item)
        assert sig.is_entertainment is False

    # --- Sentiment ---

    def test_sentiment_positive(self):
        item = make_item(title="Bitcoin surges to new all-time high amid ETF rally")
        sig = extract_signals(item)
        assert sig.sentiment == "pos"

    def test_sentiment_negative(self):
        item = make_item(title="Crypto exchange hack causes massive fund loss")
        sig = extract_signals(item)
        assert sig.sentiment == "neg"

    def test_sentiment_neutral(self):
        item = make_item(title="Bitcoin maintains steady price around $70k")
        sig = extract_signals(item)
        assert sig.sentiment == "neu"

    # --- Security exploit signal (S8) ---

    def test_security_exploit_detected_english(self):
        item = make_item(title="$280M DeFi protocol exploit drains Drift")
        sig = extract_signals(item)
        assert sig.security_exploit is True

    def test_security_exploit_detected_korean(self):
        item = make_item(title="500억원 규모 크로스체인 브리지 해킹")
        sig = extract_signals(item)
        assert sig.security_exploit is True

    def test_security_exploit_rug_pull(self):
        item = make_item(title="MemeCoin rug pull nets attackers $8M")
        sig = extract_signals(item)
        assert sig.security_exploit is True

    def test_security_exploit_defensive_article(self):
        """Defensive guide article triggers security_exploit=True but has_amount=False."""
        item = make_item(title="How to avoid crypto hacks in 2026")
        sig = extract_signals(item)
        assert sig.security_exploit is True
        assert sig.has_amount is False

    def test_security_exploit_not_triggered_on_generic_drop(self):
        item = make_item(title="BTC crashes 8% on macro fears")
        sig = extract_signals(item)
        assert sig.security_exploit is False


# ===========================================================================
# Layer 2 — Score calculation
# ===========================================================================


class TestScoreItem:
    def test_score_hack_with_amount_high(self):
        """$280M exploit with SEC involvement and circuit breaker should score >= 7.0."""
        item = make_item(
            title="SEC confirms $280M DeFi circuit breaker exploit drains protocol",
            source="reuters",
        )
        result = score_item(item)
        assert result.score >= 7.0

    def test_score_opinion_piece_penalized(self):
        """Pure opinion piece should score < 3.0."""
        item = make_item(
            title="Ben McKenzie says Bitcoin is still a ponzi scheme",
            description="Actor interview opinion column",
            source="google news",
        )
        result = score_item(item)
        assert result.score < 3.0

    def test_score_clipped_at_10(self):
        """Score cannot exceed 10."""
        # Stack all positive signals
        item = make_item(
            title="SEC announces circuit breaker $1B exploit",
            source="reuters",
        )
        result = score_item(item)
        assert result.score <= 10.0

    def test_score_clipped_at_0(self):
        """Score cannot go below 0."""
        # Entertainment + opinion double-penalty
        item = make_item(
            title="Celebrity gossip: star says Bitcoin is dead",
            source="google news",
        )
        result = score_item(item)
        assert result.score >= 0.0

    def test_contributions_recorded(self):
        """contributions dict must contain all signal keys."""
        item = make_item(title="$100M hack exploit confirmed", source="coindesk")
        result = score_item(item)
        expected_keys = {
            "source",
            "amount",
            "institution",
            "market_mechanism",
            "opinion_penalty",
            "entertainment_penalty",
            "sentiment",
        }
        assert expected_keys == set(result.contributions.keys())

    def test_institution_boosts_score(self):
        """Item with institution reference scores higher than one without."""
        item_inst = make_item(title="SEC sues crypto exchange for fraud", source="coindesk")
        item_plain = make_item(title="Exchange faces fraud allegations", source="coindesk")
        assert score_item(item_inst).score > score_item(item_plain).score

    def test_positive_sentiment_lowers_score(self):
        """Positive sentiment reduces score compared to neutral equivalent."""
        item_pos = make_item(title="Bitcoin surges rally breakout $1B inflows", source="coindesk")
        item_neg = make_item(title="Bitcoin crash plunge hack $1B outflows", source="coindesk")
        assert score_item(item_neg).score > score_item(item_pos).score

    def test_market_mechanism_raises_score(self):
        """circuit breaker + institution + credible source should push score above P0 threshold."""
        item = make_item(title="SEC orders trading halt circuit breaker on all exchanges", source="reuters")
        result = score_item(item)
        assert result.score >= P0_ITEM_THRESHOLD


# ===========================================================================
# Layer 3 — Override rules
# ===========================================================================


class TestApplyOverrides:
    def test_rule_6_hard_critical(self):
        """market_mechanism + source_weight >= 1.5 forces CRITICAL."""
        scores = [_make_score(6.0, market_mech=True, src_weight=2.0)]
        level, trace = apply_overrides(scores, "elevated")
        assert level == "critical"
        assert "rule_6_market_mechanism_hard_override" in trace

    def test_rule_6_skipped_if_low_source_weight(self):
        """market_mechanism alone with low source weight should NOT trigger rule 6."""
        scores = [_make_score(6.0, market_mech=True, src_weight=1.0)]
        level, trace = apply_overrides(scores, "elevated")
        assert level == "elevated"
        assert "rule_6_market_mechanism_hard_override" not in trace

    def test_rule_7_opinion_majority_downgrades(self):
        """>50% opinion among P0-like items downgrades level."""
        # 3 opinion items above threshold, 1 non-opinion
        scores = [
            _make_score(6.0, is_opinion=True),
            _make_score(5.5, is_opinion=True),
            _make_score(5.0, is_opinion=True),
            _make_score(5.0, is_opinion=False),
        ]
        level, trace = apply_overrides(scores, "critical")
        assert level == "elevated"  # downgraded from critical
        assert any("rule_7" in r for r in trace)

    def test_no_override_all_non_opinion(self):
        """No overrides applied when no opinion majority and no market mechanism."""
        scores = [_make_score(6.0, is_opinion=False)]
        level, trace = apply_overrides(scores, "elevated")
        assert level == "elevated"
        assert trace == []

    def test_downgrade_chain(self):
        """_downgrade_one covers the full chain."""
        assert _downgrade_one("critical") == "elevated"
        assert _downgrade_one("elevated") == "moderate"
        assert _downgrade_one("moderate") == "low"
        assert _downgrade_one("low") == "low"

    def test_rule_6_takes_precedence_over_rule_7(self):
        """Rule 6 short-circuits before rule 7 is evaluated."""
        scores = [
            _make_score(6.0, is_opinion=True, market_mech=True, src_weight=2.0),
            _make_score(5.5, is_opinion=True),
            _make_score(5.0, is_opinion=True),
        ]
        level, trace = apply_overrides(scores, "elevated")
        assert level == "critical"
        assert "rule_6_market_mechanism_hard_override" in trace

    def test_rule_6b_security_exploit_hard_critical(self):
        """exploit + amount + source(reuters, weight>=1.5) → critical with rule_6b trace."""
        scores = [_make_score(4.5, security_exploit=True, has_amount=True, src_weight=2.0)]
        level, trace = apply_overrides(scores, "elevated")
        assert level == "critical"
        assert any("rule_6b" in r for r in trace)

    def test_rule_6b_skipped_without_amount(self):
        """exploit without amount → rule 6b not triggered, base_level preserved."""
        scores = [_make_score(4.5, security_exploit=True, has_amount=False, src_weight=2.0)]
        level, trace = apply_overrides(scores, "elevated")
        assert level == "elevated"
        assert not any("rule_6b" in r for r in trace)

    def test_rule_6b_skipped_on_low_source_weight(self):
        """exploit + amount + blog (src_weight < 1.5) → rule 6b not triggered."""
        scores = [_make_score(4.5, security_exploit=True, has_amount=True, src_weight=1.0)]
        level, trace = apply_overrides(scores, "elevated")
        assert level == "elevated"
        assert not any("rule_6b" in r for r in trace)

    def test_rule_6_takes_precedence_over_rule_6b(self):
        """market_mech + exploit simultaneously → only rule_6 in trace, rule_6b absent."""
        scores = [_make_score(6.0, market_mech=True, security_exploit=True, has_amount=True, src_weight=2.0)]
        level, trace = apply_overrides(scores, "elevated")
        assert level == "critical"
        assert "rule_6_market_mechanism_hard_override" in trace
        assert not any("rule_6b" in r for r in trace)


# ===========================================================================
# Layer 4 — classify_risk integration
# ===========================================================================


class TestClassifyRisk:
    def test_empty_items_returns_low(self):
        """Empty input is safe default → low."""
        verdict = classify_risk([])
        assert verdict.level == "low"
        assert verdict.aggregate_mean == 0.0
        assert verdict.top_items == []

    def test_all_opinion_not_critical(self):
        """If all items are pure opinion pieces, level should be elevated or below."""
        items = [
            make_item(title=f"Analyst says Bitcoin will {act}", source="google news")
            for act in ["crash", "dump", "plunge", "fail", "collapse", "die", "implode"]
        ]
        verdict = classify_risk(items)
        assert verdict.level != "critical"

    def test_institution_and_amount_majority_can_reach_critical(self):
        """Multiple items with institution + amount should reach critical or elevated."""
        items = [make_item(title=f"SEC fines exchange ${i}00M for fraud", source="reuters") for i in range(1, 6)]
        verdict = classify_risk(items)
        assert verdict.level in ("critical", "elevated")

    def test_top_items_sorted_descending(self):
        """top_items must be sorted by score descending."""
        items = [
            make_item(title="Celebrity gossip star opinion says", source="google news"),
            make_item(title="$500M DeFi circuit breaker hack exploit", source="reuters"),
            make_item(title="SEC fines $200M fraud exchange", source="bloomberg"),
        ]
        verdict = classify_risk(items)
        scores = [s.score for s in verdict.top_items]
        assert scores == sorted(scores, reverse=True)

    def test_market_mechanism_triggers_critical_via_rule_6(self):
        """A single circuit breaker item from a credible source → CRITICAL."""
        items = [make_item(title="NYSE circuit breaker triggered halting all trading", source="reuters")]
        verdict = classify_risk(items)
        assert verdict.level == "critical"
        assert "rule_6_market_mechanism_hard_override" in verdict.rule_trace

    def test_verdict_has_rule_trace(self):
        """RiskVerdict.rule_trace is always a list."""
        verdict = classify_risk([make_item(title="Bitcoin price stable")])
        assert isinstance(verdict.rule_trace, list)

    def test_aggregate_mean_top3(self):
        """aggregate_mean is computed from the top-3 items only."""
        items = [
            make_item(title="$500M exploit circuit breaker SEC", source="reuters"),
            make_item(title="$200M hack fraud Federal Reserve", source="bloomberg"),
            make_item(title="SEC charges $100M fine fraud", source="coindesk"),
            make_item(title="Local trader buys 1 BTC", source="google news"),
        ]
        verdict = classify_risk(items)
        top3_scores = [s.score for s in verdict.top_items[:3]]
        expected_mean = sum(top3_scores) / 3
        assert abs(verdict.aggregate_mean - expected_mean) < 1e-9

    def test_smoke_2026_04_20_not_critical(self):
        """Smoke: 2026-04-20 3 items (opinion + positive + neutral policy) must not be CRITICAL."""
        items = [
            {
                "title": "O.C. Guy는 비트코인이 여전히 폰지 사기라고 말합니다.",
                "description": "배우 Ben McKenzie 인터뷰. 개인 발언.",
                "source": "google news",
            },
            {
                "title": "비트코인, 한달 만에 7.5만달러 재탈환",
                "description": "비트코인이 긍정적 반등세를 보이며 75000달러를 회복했다.",
                "source": "coindesk",
            },
            {
                "title": "美, 전략적 비트코인 비축고 설립 임박…트럼프 행정명령 가동",
                "description": "미국 정부가 비트코인 비축고 설립을 위한 행정명령을 준비 중이다.",
                "source": "cointelegraph",
            },
        ]
        verdict = classify_risk(items)
        # Opinion majority + positive sentiment → not critical
        assert verdict.level != "critical", f"Expected non-critical but got {verdict.level}: {verdict.rule_trace}"
        # At least one item in the verdict should be flagged as opinion
        assert any(s.signals.is_opinion for s in verdict.top_items)
