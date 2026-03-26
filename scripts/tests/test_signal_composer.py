"""Unit tests for scripts/common/signal_composer.py."""

import os
import sys

import pytest

# ---------------------------------------------------------------------------
# sys.path: make `scripts/` importable as a package root
# ---------------------------------------------------------------------------
_SCRIPTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from common.signal_composer import (  # noqa: E402
    CompositeResult,
    ScenarioResult,
    SignalComposer,
    SignalResult,
    StanceAnalysis,
    _fg_label_korean,
    _score_to_verdict,
    _verdict_with_icon,
    analyze_stance,
    compose_signals,
    generate_outlook_markdown,
    generate_prediction_markdown,
)

# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------

def _full_signals():
    """A complete set of all supported signal keys."""
    return {
        "fear_greed": {"value": 50, "label": "Neutral"},
        "vix": {"value": 20.0, "trend": "stable"},
        "sentiment": {"score": 0.1, "positive": 6, "negative": 4},
        "momentum": {"btc_7d": 2.0, "eth_7d": 1.5},
        "macro": {"us10y": 4.0, "dxy": 100.0},
        "technical": {"rsi_14": 55, "macd_signal": "neutral"},
    }


def _make_signal_result(name="테스트", normalized=0.5, verdict="중립", weight=0.2, raw_display="50", trend_arrow=""):
    return SignalResult(
        name=name,
        raw_display=raw_display,
        normalized=normalized,
        verdict=verdict,
        weight=weight,
        trend_arrow=trend_arrow,
    )


# ===========================================================================
# Module-level helper functions
# ===========================================================================

class TestScoreToVerdict:
    def test_bullish_at_threshold(self):
        assert _score_to_verdict(0.60) == "강세"

    def test_bullish_above_threshold(self):
        assert _score_to_verdict(0.80) == "강세"

    def test_bearish_at_threshold(self):
        assert _score_to_verdict(0.40) == "약세"

    def test_bearish_below_threshold(self):
        assert _score_to_verdict(0.20) == "약세"

    def test_neutral_in_middle(self):
        assert _score_to_verdict(0.50) == "중립"

    def test_neutral_just_above_bearish(self):
        assert _score_to_verdict(0.41) == "중립"

    def test_neutral_just_below_bullish(self):
        assert _score_to_verdict(0.59) == "중립"


class TestFgLabelKorean:
    def test_extreme_fear(self):
        assert _fg_label_korean("Extreme Fear", 10) == "극공포"

    def test_fear(self):
        assert _fg_label_korean("Fear", 30) == "공포"

    def test_neutral(self):
        assert _fg_label_korean("Neutral", 50) == "중립"

    def test_greed(self):
        assert _fg_label_korean("Greed", 65) == "탐욕"

    def test_extreme_greed(self):
        assert _fg_label_korean("Extreme Greed", 85) == "극탐욕"

    def test_case_insensitive(self):
        assert _fg_label_korean("extreme fear", 10) == "극공포"
        assert _fg_label_korean("GREED", 65) == "탐욕"

    def test_unknown_label_uses_value_extreme_fear(self):
        assert _fg_label_korean("", 10) == "극공포"

    def test_unknown_label_uses_value_fear(self):
        assert _fg_label_korean("", 35) == "공포"

    def test_unknown_label_uses_value_neutral(self):
        assert _fg_label_korean("", 50) == "중립"

    def test_unknown_label_uses_value_greed(self):
        assert _fg_label_korean("", 60) == "탐욕"

    def test_unknown_label_uses_value_extreme_greed(self):
        assert _fg_label_korean("", 80) == "극탐욕"


class TestVerdictWithIcon:
    def test_bullish_icon(self):
        result = _verdict_with_icon("강세")
        assert "강세" in result
        assert "📈" in result

    def test_bearish_icon(self):
        result = _verdict_with_icon("약세")
        assert "약세" in result
        assert "📉" in result

    def test_neutral_icon(self):
        result = _verdict_with_icon("중립")
        assert "중립" in result

    def test_mixed_icon(self):
        result = _verdict_with_icon("혼조")
        assert "혼조" in result

    def test_unknown_verdict_passthrough(self):
        assert _verdict_with_icon("unknown") == "unknown"


# ===========================================================================
# SignalComposer.__init__ and weight initialization
# ===========================================================================

class TestSignalComposerInit:
    def test_default_weights_sum_to_one(self):
        composer = SignalComposer()
        assert abs(sum(composer._weights.values()) - 1.0) < 1e-9

    def test_custom_weight_overrides(self):
        composer = SignalComposer(custom_weights={"fear_greed": 0.5})
        assert composer._weights["fear_greed"] == 0.5

    def test_custom_weight_unknown_key_ignored(self):
        composer = SignalComposer(custom_weights={"nonexistent": 0.99})
        assert "nonexistent" not in composer._weights

    def test_custom_weight_partial_override(self):
        composer = SignalComposer(custom_weights={"vix": 0.30})
        assert composer._weights["vix"] == 0.30
        # Other keys remain at defaults
        assert composer._weights["fear_greed"] == 0.25


# ===========================================================================
# SignalComposer.compose_signals — empty / missing data
# ===========================================================================

class TestComposeSignalsEmpty:
    def test_empty_dict_returns_default(self):
        result = SignalComposer().compose_signals({})
        assert isinstance(result, CompositeResult)
        assert result.score == 50.0
        assert result.verdict == "중립"
        assert result.confidence == "low"
        assert result.total_signals == 0
        assert len(result.scenarios) == 3

    def test_none_values_are_skipped(self):
        result = SignalComposer().compose_signals({"fear_greed": None, "vix": None})
        assert result.total_signals == 0

    def test_result_has_three_scenarios_on_default(self):
        result = SignalComposer().compose_signals({})
        labels = [s.label for s in result.scenarios]
        assert "강세" in labels
        assert "기본" in labels
        assert "약세" in labels


# ===========================================================================
# SignalComposer.compose_signals — single signal inputs
# ===========================================================================

class TestComposeSignalsSingle:
    def test_fear_greed_high_score_is_bullish(self):
        result = SignalComposer().compose_signals({"fear_greed": {"value": 80, "label": "Extreme Greed"}})
        assert result.score > 60
        assert result.verdict == "강세"

    def test_fear_greed_low_score_is_bearish(self):
        result = SignalComposer().compose_signals({"fear_greed": {"value": 10, "label": "Extreme Fear"}})
        assert result.score < 40
        assert result.verdict == "약세"

    def test_vix_low_is_bullish(self):
        result = SignalComposer().compose_signals({"vix": {"value": 10.0}})
        assert result.score > 60

    def test_vix_high_is_bearish(self):
        result = SignalComposer().compose_signals({"vix": {"value": 45.0}})
        assert result.score < 40

    def test_total_signals_count(self):
        result = SignalComposer().compose_signals({"fear_greed": {"value": 50}})
        assert result.total_signals == 1


# ===========================================================================
# SignalComposer.compose_signals — full signal set
# ===========================================================================

class TestComposeSignalsFull:
    def test_returns_composite_result(self):
        result = SignalComposer().compose_signals(_full_signals())
        assert isinstance(result, CompositeResult)

    def test_score_in_valid_range(self):
        result = SignalComposer().compose_signals(_full_signals())
        assert 0.0 <= result.score <= 100.0

    def test_verdict_is_valid_string(self):
        result = SignalComposer().compose_signals(_full_signals())
        assert result.verdict in ("강세", "약세", "중립", "혼조")

    def test_confidence_key_valid(self):
        result = SignalComposer().compose_signals(_full_signals())
        assert result.confidence in ("low", "medium", "high")

    def test_confidence_label_valid(self):
        result = SignalComposer().compose_signals(_full_signals())
        assert result.confidence_label in ("낮음", "보통", "높음")

    def test_signal_results_count(self):
        result = SignalComposer().compose_signals(_full_signals())
        assert result.total_signals == 6

    def test_signal_weights_sum_to_one(self):
        result = SignalComposer().compose_signals(_full_signals())
        total = sum(sr.weight for sr in result.signal_results)
        assert abs(total - 1.0) < 1e-6

    def test_three_scenarios_generated(self):
        result = SignalComposer().compose_signals(_full_signals())
        assert len(result.scenarios) == 3

    def test_scenario_probabilities_sum_to_100(self):
        result = SignalComposer().compose_signals(_full_signals())
        total = sum(s.probability for s in result.scenarios)
        assert total == 100

    def test_bullish_signals_produce_high_score(self):
        signals = {
            "fear_greed": {"value": 85, "label": "Extreme Greed"},
            "vix": {"value": 11.0, "trend": "falling"},
            "sentiment": {"score": 0.8, "positive": 9, "negative": 1},
            "momentum": {"btc_7d": 10.0, "eth_7d": 8.0},
        }
        result = SignalComposer().compose_signals(signals)
        assert result.score > 60
        assert result.verdict == "강세"

    def test_bearish_signals_produce_low_score(self):
        signals = {
            "fear_greed": {"value": 8, "label": "Extreme Fear"},
            "vix": {"value": 40.0, "trend": "rising"},
            "sentiment": {"score": -0.8, "positive": 1, "negative": 9},
            "momentum": {"btc_7d": -12.0, "eth_7d": -10.0},
        }
        result = SignalComposer().compose_signals(signals)
        assert result.score < 40
        assert result.verdict == "약세"

    def test_malformed_signal_is_skipped_gracefully(self):
        signals = {
            "fear_greed": {"value": "not_a_number"},
            "vix": {"value": 20.0},
        }
        # Should not raise; fear_greed may be processed (float("not_a_number") raises ValueError)
        # or may log warning and skip
        result = SignalComposer().compose_signals(signals)
        assert isinstance(result, CompositeResult)


# ===========================================================================
# Individual signal processors (_process_*)
# ===========================================================================

class TestProcessFearGreed:
    def setup_method(self):
        self.composer = SignalComposer()

    def test_extreme_greed(self):
        sr = self.composer._process_fear_greed({"value": 90, "label": "Extreme Greed"}, 0.25)
        assert sr.normalized >= 0.8
        assert sr.verdict == "강세"
        assert "극탐욕" in sr.raw_display

    def test_extreme_fear(self):
        sr = self.composer._process_fear_greed({"value": 10, "label": "Extreme Fear"}, 0.25)
        assert sr.normalized <= 0.2
        assert sr.verdict == "약세"
        assert "극공포" in sr.raw_display

    def test_neutral_value(self):
        sr = self.composer._process_fear_greed({"value": 50, "label": "Neutral"}, 0.25)
        assert sr.normalized == pytest.approx(0.5, abs=0.01)
        assert sr.verdict == "중립"

    def test_default_value_when_missing(self):
        sr = self.composer._process_fear_greed({}, 0.25)
        assert sr.normalized == pytest.approx(0.5, abs=0.01)

    def test_weight_stored(self):
        sr = self.composer._process_fear_greed({"value": 50}, 0.33)
        assert sr.weight == 0.33


class TestProcessVix:
    def setup_method(self):
        self.composer = SignalComposer()

    def test_low_vix_bullish(self):
        sr = self.composer._process_vix({"value": 10.0}, 0.20)
        assert sr.normalized == pytest.approx(1.0, abs=0.01)
        assert sr.verdict == "강세"

    def test_high_vix_bearish(self):
        sr = self.composer._process_vix({"value": 40.0}, 0.20)
        assert sr.normalized == pytest.approx(0.0, abs=0.01)
        assert sr.verdict == "약세"

    def test_rising_trend_reduces_score(self):
        sr_stable = self.composer._process_vix({"value": 20.0, "trend": "stable"}, 0.20)
        sr_rising = self.composer._process_vix({"value": 20.0, "trend": "rising"}, 0.20)
        assert sr_rising.normalized < sr_stable.normalized

    def test_falling_trend_increases_score(self):
        sr_stable = self.composer._process_vix({"value": 20.0, "trend": "stable"}, 0.20)
        sr_falling = self.composer._process_vix({"value": 20.0, "trend": "falling"}, 0.20)
        assert sr_falling.normalized > sr_stable.normalized

    def test_trend_arrow_rising(self):
        sr = self.composer._process_vix({"value": 20.0, "trend": "rising"}, 0.20)
        assert sr.trend_arrow == "↑"

    def test_trend_arrow_falling(self):
        sr = self.composer._process_vix({"value": 20.0, "trend": "falling"}, 0.20)
        assert sr.trend_arrow == "↓"

    def test_trend_arrow_stable(self):
        sr = self.composer._process_vix({"value": 20.0, "trend": "stable"}, 0.20)
        assert sr.trend_arrow == "→"

    def test_vix_clamps_above_40(self):
        sr = self.composer._process_vix({"value": 100.0}, 0.20)
        assert sr.normalized == 0.0

    def test_vix_clamps_below_10(self):
        sr = self.composer._process_vix({"value": 5.0}, 0.20)
        assert sr.normalized == pytest.approx(1.0, abs=0.01)


class TestProcessSentiment:
    def setup_method(self):
        self.composer = SignalComposer()

    def test_positive_sentiment_bullish(self):
        sr = self.composer._process_sentiment({"score": 0.8, "positive": 9, "negative": 1}, 0.20)
        assert sr.verdict == "강세"

    def test_negative_sentiment_bearish(self):
        sr = self.composer._process_sentiment({"score": -0.8, "positive": 1, "negative": 9}, 0.20)
        assert sr.verdict == "약세"

    def test_neutral_sentiment(self):
        # blending formula: score*0.5 + (ratio-0.5)*0.5 + 0.5*0.5
        # With score=0, ratio=0.5 → blended=0.25, normalized=(0.25+1)/2=0.625 → "강세"
        sr = self.composer._process_sentiment({"score": 0.0, "positive": 5, "negative": 5}, 0.20)
        assert sr.verdict == "강세"

    def test_no_article_counts_uses_score_only(self):
        sr = self.composer._process_sentiment({"score": 0.0}, 0.20)
        assert sr.normalized == pytest.approx(0.5, abs=0.01)

    def test_display_has_sign(self):
        sr = self.composer._process_sentiment({"score": 0.5}, 0.20)
        assert "+" in sr.raw_display

    def test_negative_display_no_plus(self):
        sr = self.composer._process_sentiment({"score": -0.5}, 0.20)
        assert "+" not in sr.raw_display


class TestProcessMomentum:
    def setup_method(self):
        self.composer = SignalComposer()

    def test_positive_momentum_bullish(self):
        sr = self.composer._process_momentum({"btc_7d": 15.0, "eth_7d": 12.0}, 0.20)
        assert sr.verdict == "강세"

    def test_negative_momentum_bearish(self):
        sr = self.composer._process_momentum({"btc_7d": -15.0, "eth_7d": -12.0}, 0.20)
        assert sr.verdict == "약세"

    def test_empty_data_returns_neutral(self):
        sr = self.composer._process_momentum({}, 0.20)
        assert sr.normalized == 0.5
        assert sr.verdict == "중립"
        assert sr.raw_display == "N/A"

    def test_avg_field_used_when_no_individual(self):
        sr = self.composer._process_momentum({"avg": 5.0}, 0.20)
        assert sr.verdict == "강세"

    def test_sp500_field_included(self):
        sr = self.composer._process_momentum({"sp500_5d": 3.0}, 0.20)
        assert sr.normalized > 0.5

    def test_display_shows_btc_and_eth(self):
        sr = self.composer._process_momentum({"btc_7d": 5.0, "eth_7d": 3.0}, 0.20)
        assert "BTC" in sr.raw_display
        assert "ETH" in sr.raw_display


class TestProcessMacro:
    def setup_method(self):
        self.composer = SignalComposer()

    def test_low_rates_bullish(self):
        sr = self.composer._process_macro({"us10y": 3.0, "dxy": 90.0}, 0.10)
        assert sr.verdict == "강세"

    def test_high_rates_bearish(self):
        sr = self.composer._process_macro({"us10y": 5.5, "dxy": 115.0, "fed_rate": 6.0}, 0.10)
        assert sr.verdict == "약세"

    def test_empty_data_returns_neutral(self):
        sr = self.composer._process_macro({}, 0.10)
        assert sr.normalized == 0.5
        assert sr.raw_display == "N/A"

    def test_fed_rate_included_in_score(self):
        sr_with = self.composer._process_macro({"fed_rate": 2.0}, 0.10)
        sr_without = self.composer._process_macro({}, 0.10)
        assert sr_with.normalized != sr_without.normalized

    def test_display_includes_10y(self):
        sr = self.composer._process_macro({"us10y": 4.5}, 0.10)
        assert "10Y" in sr.raw_display

    def test_display_includes_dxy(self):
        sr = self.composer._process_macro({"dxy": 100.0}, 0.10)
        assert "DXY" in sr.raw_display


class TestProcessTechnical:
    def setup_method(self):
        self.composer = SignalComposer()

    def test_golden_cross_bullish(self):
        sr = self.composer._process_technical({"ma_cross": "golden"}, 0.05)
        assert sr.verdict == "강세"

    def test_death_cross_bearish(self):
        sr = self.composer._process_technical({"ma_cross": "death"}, 0.05)
        assert sr.verdict == "약세"

    def test_bullish_macd_raises_score(self):
        sr = self.composer._process_technical({"macd_signal": "bullish"}, 0.05)
        assert sr.verdict == "강세"

    def test_bearish_macd_lowers_score(self):
        sr = self.composer._process_technical({"macd_signal": "bearish"}, 0.05)
        assert sr.verdict == "약세"

    def test_rsi_oversold(self):
        sr = self.composer._process_technical({"rsi_14": 25}, 0.05)
        # RSI <= 30 gives 0.35 (sub-threshold for bullish, so neutral or bearish)
        assert sr.normalized == pytest.approx(0.35, abs=0.01)

    def test_rsi_overbought(self):
        sr = self.composer._process_technical({"rsi_14": 75}, 0.05)
        assert sr.normalized == pytest.approx(0.65, abs=0.01)

    def test_empty_data_returns_neutral(self):
        sr = self.composer._process_technical({}, 0.05)
        assert sr.normalized == 0.5
        assert sr.raw_display == "N/A"

    def test_rsi_in_display(self):
        sr = self.composer._process_technical({"rsi_14": 55}, 0.05)
        assert "RSI" in sr.raw_display


# ===========================================================================
# _normalize_signal
# ===========================================================================

class TestNormalizeSignal:
    def setup_method(self):
        self.composer = SignalComposer()

    def test_fear_greed_midpoint(self):
        assert self.composer._normalize_signal("fear_greed", 50) == pytest.approx(0.5)

    def test_fear_greed_clamps_above_100(self):
        assert self.composer._normalize_signal("fear_greed", 150) == pytest.approx(1.0)

    def test_fear_greed_clamps_below_0(self):
        assert self.composer._normalize_signal("fear_greed", -10) == pytest.approx(0.0)

    def test_vix_10_equals_1(self):
        assert self.composer._normalize_signal("vix", 10) == pytest.approx(1.0)

    def test_vix_40_equals_0(self):
        assert self.composer._normalize_signal("vix", 40) == pytest.approx(0.0)

    def test_vix_25_equals_half(self):
        assert self.composer._normalize_signal("vix", 25) == pytest.approx(0.5)

    def test_sentiment_minus1_equals_0(self):
        assert self.composer._normalize_signal("sentiment", -1.0) == pytest.approx(0.0)

    def test_sentiment_plus1_equals_1(self):
        assert self.composer._normalize_signal("sentiment", 1.0) == pytest.approx(1.0)

    def test_sentiment_zero_equals_half(self):
        assert self.composer._normalize_signal("sentiment", 0.0) == pytest.approx(0.5)

    def test_rsi_50_equals_half(self):
        assert self.composer._normalize_signal("rsi", 50) == pytest.approx(0.5)

    def test_momentum_pct_zero_equals_half(self):
        assert self.composer._normalize_signal("momentum_pct", 0.0) == pytest.approx(0.5)

    def test_momentum_pct_plus20_equals_1(self):
        assert self.composer._normalize_signal("momentum_pct", 20.0) == pytest.approx(1.0)

    def test_momentum_pct_minus20_equals_0(self):
        assert self.composer._normalize_signal("momentum_pct", -20.0) == pytest.approx(0.0)

    def test_unknown_signal_returns_half(self):
        assert self.composer._normalize_signal("unknown_signal", 99) == pytest.approx(0.5)


# ===========================================================================
# _renormalize_weights
# ===========================================================================

class TestRenormalizeWeights:
    def setup_method(self):
        self.composer = SignalComposer()

    def test_weights_sum_to_one_after_renorm(self):
        results = [
            _make_signal_result(weight=0.25),
            _make_signal_result(weight=0.20),
        ]
        self.composer._renormalize_weights(results)
        total = sum(r.weight for r in results)
        assert abs(total - 1.0) < 1e-9

    def test_single_result_gets_weight_one(self):
        results = [_make_signal_result(weight=0.30)]
        self.composer._renormalize_weights(results)
        assert results[0].weight == pytest.approx(1.0)

    def test_zero_weight_fallback_equal_distribution(self):
        results = [
            _make_signal_result(weight=0.0),
            _make_signal_result(weight=0.0),
        ]
        self.composer._renormalize_weights(results)
        for r in results:
            assert r.weight == pytest.approx(0.5)


# ===========================================================================
# _calculate_weighted_score
# ===========================================================================

class TestCalculateWeightedScore:
    def setup_method(self):
        self.composer = SignalComposer()

    def test_all_bullish_score_near_100(self):
        results = [
            _make_signal_result(normalized=1.0, weight=0.5),
            _make_signal_result(normalized=1.0, weight=0.5),
        ]
        score = self.composer._calculate_weighted_score(results)
        assert score == pytest.approx(100.0)

    def test_all_bearish_score_near_0(self):
        results = [
            _make_signal_result(normalized=0.0, weight=0.5),
            _make_signal_result(normalized=0.0, weight=0.5),
        ]
        score = self.composer._calculate_weighted_score(results)
        assert score == pytest.approx(0.0)

    def test_neutral_score_near_50(self):
        results = [
            _make_signal_result(normalized=0.5, weight=0.5),
            _make_signal_result(normalized=0.5, weight=0.5),
        ]
        score = self.composer._calculate_weighted_score(results)
        assert score == pytest.approx(50.0)

    def test_weighted_average_correct(self):
        results = [
            _make_signal_result(normalized=0.8, weight=0.6),
            _make_signal_result(normalized=0.2, weight=0.4),
        ]
        expected = (0.8 * 0.6 + 0.2 * 0.4) * 100.0
        score = self.composer._calculate_weighted_score(results)
        assert score == pytest.approx(expected)


# ===========================================================================
# _determine_verdict
# ===========================================================================

class TestDetermineVerdict:
    def setup_method(self):
        self.composer = SignalComposer()

    def test_high_score_is_bullish(self):
        results = [_make_signal_result(verdict="강세")]
        assert self.composer._determine_verdict(70.0, results) == "강세"

    def test_low_score_is_bearish(self):
        results = [_make_signal_result(verdict="약세")]
        assert self.composer._determine_verdict(30.0, results) == "약세"

    def test_mixed_signals_in_middle_is_mixed(self):
        results = [
            _make_signal_result(verdict="강세"),
            _make_signal_result(verdict="약세"),
        ]
        assert self.composer._determine_verdict(50.0, results) == "혼조"

    def test_all_neutral_middle_score_is_neutral(self):
        results = [_make_signal_result(verdict="중립")]
        assert self.composer._determine_verdict(50.0, results) == "중립"

    def test_score_56_no_bears_is_bullish(self):
        results = [_make_signal_result(verdict="강세")]
        assert self.composer._determine_verdict(56.0, results) == "강세"

    def test_score_44_no_bulls_is_bearish(self):
        results = [_make_signal_result(verdict="약세")]
        assert self.composer._determine_verdict(44.0, results) == "약세"


# ===========================================================================
# _calculate_confidence
# ===========================================================================

class TestCalculateConfidence:
    def setup_method(self):
        self.composer = SignalComposer()

    def test_empty_results_low(self):
        conf, label, count = self.composer._calculate_confidence([], "중립")
        assert conf == "low"
        assert count == 0

    def test_all_agree_high_confidence(self):
        results = [_make_signal_result(verdict="강세") for _ in range(4)]
        conf, label, count = self.composer._calculate_confidence(results, "강세")
        assert conf == "high"
        assert label == "높음"

    def test_mixed_verdict_medium_confidence(self):
        results = [
            _make_signal_result(verdict="강세"),
            _make_signal_result(verdict="약세"),
        ]
        conf, label, count = self.composer._calculate_confidence(results, "혼조")
        assert conf == "medium"

    def test_low_agreement_low_confidence(self):
        results = [
            _make_signal_result(verdict="강세"),
            _make_signal_result(verdict="약세"),
            _make_signal_result(verdict="약세"),
            _make_signal_result(verdict="약세"),
        ]
        conf, label, count = self.composer._calculate_confidence(results, "강세")
        assert conf == "low"

    def test_neutral_signals_count_as_agreement(self):
        results = [
            _make_signal_result(verdict="강세"),
            _make_signal_result(verdict="중립"),
            _make_signal_result(verdict="중립"),
            _make_signal_result(verdict="중립"),
        ]
        conf, label, count = self.composer._calculate_confidence(results, "강세")
        # 4/4 = 1.0 >= 0.75 → high
        assert conf == "high"


# ===========================================================================
# _generate_scenarios
# ===========================================================================

class TestGenerateScenarios:
    def setup_method(self):
        self.composer = SignalComposer()

    def _base_results(self):
        fg = _make_signal_result(name="공포·탐욕 지수", raw_display="50 (중립)", normalized=0.5)
        vix = _make_signal_result(name="VIX 변동성", raw_display="20.0", normalized=0.5)
        mom = _make_signal_result(name="모멘텀", raw_display="BTC +2.0%", normalized=0.55)
        macro = _make_signal_result(name="매크로", raw_display="10Y 4.00%", normalized=0.5)
        return [fg, vix, mom, macro]

    def test_returns_three_scenarios(self):
        scenarios = self.composer._generate_scenarios(50.0, "중립", self._base_results())
        assert len(scenarios) == 3

    def test_bullish_verdict_gives_high_bull_prob(self):
        scenarios = self.composer._generate_scenarios(70.0, "강세", self._base_results())
        bull_prob = next(s.probability for s in scenarios if s.label == "강세")
        bear_prob = next(s.probability for s in scenarios if s.label == "약세")
        assert bull_prob > bear_prob

    def test_bearish_verdict_gives_high_bear_prob(self):
        scenarios = self.composer._generate_scenarios(30.0, "약세", self._base_results())
        bull_prob = next(s.probability for s in scenarios if s.label == "강세")
        bear_prob = next(s.probability for s in scenarios if s.label == "약세")
        assert bear_prob > bull_prob

    def test_prob_sum_is_100(self):
        scenarios = self.composer._generate_scenarios(50.0, "중립", self._base_results())
        assert sum(s.probability for s in scenarios) == 100

    def test_scenarios_have_time_horizon(self):
        scenarios = self.composer._generate_scenarios(50.0, "중립", self._base_results())
        for s in scenarios:
            assert s.time_horizon != ""

    def test_bull_scenario_has_resistance_level(self):
        scenarios = self.composer._generate_scenarios(50.0, "중립", self._base_results())
        bull = next(s for s in scenarios if s.label == "강세")
        assert bull.resistance_level != ""

    def test_bear_scenario_has_support_level(self):
        scenarios = self.composer._generate_scenarios(50.0, "중립", self._base_results())
        bear = next(s for s in scenarios if s.label == "약세")
        assert bear.support_level != ""

    def test_empty_results_no_crash(self):
        scenarios = self.composer._generate_scenarios(50.0, "중립", [])
        assert len(scenarios) == 3


# ===========================================================================
# analyze_stance
# ===========================================================================

class TestAnalyzeStance:
    def setup_method(self):
        self.composer = SignalComposer()

    def _make_result_with_verdicts(self, verdicts):
        srs = [_make_signal_result(verdict=v, name=f"지표{i}") for i, v in enumerate(verdicts)]
        return CompositeResult(
            score=50.0,
            verdict="중립",
            confidence="medium",
            confidence_label="보통",
            signal_results=srs,
        )

    def test_all_bullish_supportive(self):
        result = self._make_result_with_verdicts(["강세", "강세", "강세"])
        stance = self.composer.analyze_stance(result)
        assert stance.dominant_stance == "supportive"
        assert len(stance.bulls) == 3
        assert len(stance.bears) == 0

    def test_all_bearish_opposing(self):
        result = self._make_result_with_verdicts(["약세", "약세", "약세"])
        stance = self.composer.analyze_stance(result)
        assert stance.dominant_stance == "opposing"
        assert len(stance.bears) == 3

    def test_all_neutral_observer(self):
        result = self._make_result_with_verdicts(["중립", "중립", "중립"])
        stance = self.composer.analyze_stance(result)
        assert stance.dominant_stance == "observer"
        assert len(stance.observers) == 3

    def test_empty_signals_neutral(self):
        result = CompositeResult(
            score=50.0, verdict="중립", confidence="low", confidence_label="낮음"
        )
        stance = self.composer.analyze_stance(result)
        assert stance.dominant_stance == "neutral"
        assert stance.consensus_ratio == 0.0

    def test_consensus_ratio_range(self):
        result = self._make_result_with_verdicts(["강세", "강세", "약세"])
        stance = self.composer.analyze_stance(result)
        assert 0.0 <= stance.consensus_ratio <= 1.0

    def test_mixed_equal_bull_bear_neutral(self):
        result = self._make_result_with_verdicts(["강세", "약세"])
        stance = self.composer.analyze_stance(result)
        # bias = (1-1)/2 = 0.0 → abs < 0.3 and no observer majority → neutral
        assert stance.dominant_stance == "neutral"


# ===========================================================================
# generate_outlook_markdown
# ===========================================================================

class TestGenerateOutlookMarkdown:
    def setup_method(self):
        self.composer = SignalComposer()

    def _make_composite(self, score=55.0, verdict="강세"):
        sr = _make_signal_result(name="공포·탐욕 지수", raw_display="70 (탐욕)", normalized=0.7, weight=1.0, trend_arrow="↑")
        scenario = ScenarioResult(label="강세", emoji="🟢", probability=40, description="테스트")
        return CompositeResult(
            score=score,
            verdict=verdict,
            confidence="high",
            confidence_label="높음",
            signal_results=[sr],
            scenarios=[scenario],
            agreement_count=1,
            total_signals=1,
        )

    def test_contains_header(self):
        md = self.composer.generate_outlook_markdown(self._make_composite())
        assert "## 시장 전망 분석" in md

    def test_contains_score(self):
        md = self.composer.generate_outlook_markdown(self._make_composite(score=55.0))
        assert "55" in md

    def test_contains_signal_name(self):
        md = self.composer.generate_outlook_markdown(self._make_composite())
        assert "공포·탐욕 지수" in md

    def test_contains_trend_arrow(self):
        md = self.composer.generate_outlook_markdown(self._make_composite())
        assert "↑" in md

    def test_contains_scenario_section(self):
        md = self.composer.generate_outlook_markdown(self._make_composite())
        assert "시나리오 분석" in md

    def test_contains_disclaimer(self):
        md = self.composer.generate_outlook_markdown(self._make_composite())
        assert "투자 조언이 아닙니다" in md

    def test_returns_string(self):
        md = self.composer.generate_outlook_markdown(self._make_composite())
        assert isinstance(md, str)


# ===========================================================================
# generate_prediction_markdown
# ===========================================================================

class TestGeneratePredictionMarkdown:
    def setup_method(self):
        self.composer = SignalComposer()

    def _build(self):
        result = SignalComposer().compose_signals(_full_signals())
        stance = self.composer.analyze_stance(result)
        return result, stance

    def test_contains_stance_section(self):
        result, stance = self._build()
        md = self.composer.generate_prediction_markdown(result, stance)
        assert "시장 참여자 입장 분석" in md

    def test_contains_scenario_section(self):
        result, stance = self._build()
        md = self.composer.generate_prediction_markdown(result, stance)
        assert "시나리오 분석" in md

    def test_contains_disclaimer(self):
        result, stance = self._build()
        md = self.composer.generate_prediction_markdown(result, stance)
        assert "투자 조언이 아닙니다" in md

    def test_returns_string(self):
        result, stance = self._build()
        md = self.composer.generate_prediction_markdown(result, stance)
        assert isinstance(md, str)

    def test_catalysts_shown_when_present(self):
        result, stance = self._build()
        md = self.composer.generate_prediction_markdown(result, stance)
        assert "촉매" in md


# ===========================================================================
# Module-level convenience functions
# ===========================================================================

class TestModuleLevelFunctions:
    def test_compose_signals_convenience(self):
        result = compose_signals({"fear_greed": {"value": 70}})
        assert isinstance(result, CompositeResult)
        assert result.score > 50

    def test_compose_signals_with_weights(self):
        result = compose_signals(
            {"fear_greed": {"value": 70}},
            weights={"fear_greed": 0.5},
        )
        assert isinstance(result, CompositeResult)

    def test_generate_outlook_markdown_convenience(self):
        result = compose_signals(_full_signals())
        md = generate_outlook_markdown(result)
        assert "시장 전망 분석" in md

    def test_analyze_stance_convenience(self):
        result = compose_signals(_full_signals())
        stance = analyze_stance(result)
        assert isinstance(stance, StanceAnalysis)

    def test_generate_prediction_markdown_convenience(self):
        result = compose_signals(_full_signals())
        stance = analyze_stance(result)
        md = generate_prediction_markdown(result, stance)
        assert "시나리오 분석" in md


# ===========================================================================
# DataClass field defaults and structure
# ===========================================================================

class TestDataClasses:
    def test_signal_result_fields(self):
        sr = SignalResult(name="x", raw_display="v", normalized=0.5, verdict="중립", weight=0.1)
        assert sr.trend_arrow == ""

    def test_scenario_result_defaults(self):
        sc = ScenarioResult(label="기본", emoji="🟡", probability=50, description="desc")
        assert sc.catalysts == []
        assert sc.time_horizon == ""
        assert sc.support_level == ""
        assert sc.resistance_level == ""

    def test_composite_result_defaults(self):
        cr = CompositeResult(score=50.0, verdict="중립", confidence="low", confidence_label="낮음")
        assert cr.signal_results == []
        assert cr.scenarios == []
        assert cr.agreement_count == 0
        assert cr.total_signals == 0

    def test_stance_analysis_fields(self):
        sa = StanceAnalysis(bulls=["a"], bears=[], observers=["b"], dominant_stance="neutral", consensus_ratio=0.5)
        assert sa.dominant_stance == "neutral"
        assert sa.consensus_ratio == 0.5
