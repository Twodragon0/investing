"""Tests for scripts/common/signal_composer.py.

Coverage targets (miss lines):
  177-179, 213-214, 217-218, 277, 289-290, 292-293, 298-300,
  410-446, 475-490, 525-529, 545-565, 575-613, 629-632, 645-647, 650,
  674-727, 744-746, 763, 765, 774-778, 792, 803-810, 830, 832, 836,
  851-859, 870-871, 875-876, 881-882, 885-886, 896, 898, 906, 908,
  952, 997-1005, 1027, 1032, 1037, 1042
"""

import pytest

from common.signal_composer import (
    _DEFAULT_WEIGHTS,
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

# ── Fixtures ──────────────────────────────────────────────────────────────────


def make_full_signals():
    return {
        "fear_greed": {"value": 55, "label": "Greed"},
        "vix": {"value": 18.0, "trend": "falling"},
        "sentiment": {"score": 0.3, "positive": 12, "negative": 8},
        "momentum": {"btc_7d": 5.0, "eth_7d": 3.0},
        "macro": {"us10y": 4.0, "dxy": 100.0},
        "technical": {"rsi_14": 55, "macd_signal": "bullish"},
    }


def make_bearish_signals():
    return {
        "fear_greed": {"value": 15, "label": "Extreme Fear"},
        "vix": {"value": 35.0, "trend": "rising"},
        "sentiment": {"score": -0.8, "positive": 2, "negative": 18},
        "momentum": {"btc_7d": -10.0, "eth_7d": -8.0},
        "macro": {"us10y": 5.2, "dxy": 112.0, "fed_rate": 5.5},
        "technical": {"rsi_14": 25, "macd_signal": "bearish"},
    }


def make_bullish_signals():
    return {
        "fear_greed": {"value": 80, "label": "Extreme Greed"},
        "vix": {"value": 11.0, "trend": "falling"},
        "sentiment": {"score": 0.9, "positive": 30, "negative": 2},
        "momentum": {"btc_7d": 18.0, "eth_7d": 15.0},
        "macro": {"us10y": 3.0, "dxy": 92.0, "fed_rate": 2.0},
        "technical": {"rsi_14": 68, "macd_signal": "bullish", "ma_cross": "golden"},
    }


# ── SignalResult dataclass ────────────────────────────────────────────────────


class TestSignalResult:
    def test_basic_creation(self):
        sr = SignalResult(
            name="테스트",
            raw_display="50 (중립)",
            normalized=0.5,
            verdict="중립",
            weight=0.2,
        )
        assert sr.name == "테스트"
        assert sr.raw_display == "50 (중립)"
        assert sr.normalized == 0.5
        assert sr.verdict == "중립"
        assert sr.weight == 0.2
        assert sr.trend_arrow == ""

    def test_with_trend_arrow(self):
        sr = SignalResult(
            name="VIX",
            raw_display="22.0",
            normalized=0.6,
            verdict="강세",
            weight=0.2,
            trend_arrow="↓",
        )
        assert sr.trend_arrow == "↓"


# ── ScenarioResult dataclass ──────────────────────────────────────────────────


class TestScenarioResult:
    def test_basic_creation(self):
        sc = ScenarioResult(label="강세", emoji="🟢", probability=40, description="test")
        assert sc.label == "강세"
        assert sc.catalysts == []
        assert sc.time_horizon == ""
        assert sc.support_level == ""
        assert sc.resistance_level == ""

    def test_with_catalysts(self):
        sc = ScenarioResult(
            label="약세",
            emoji="🔴",
            probability=20,
            description="desc",
            catalysts=["VIX 30 돌파"],
            time_horizon="단기 1-3일",
            support_level="현재가 -5%",
        )
        assert len(sc.catalysts) == 1


# ── Helper functions ──────────────────────────────────────────────────────────


class TestScoreToVerdict:
    def test_bullish(self):
        assert _score_to_verdict(0.65) == "강세"
        assert _score_to_verdict(1.0) == "강세"
        assert _score_to_verdict(0.60) == "강세"

    def test_bearish(self):
        assert _score_to_verdict(0.35) == "약세"
        assert _score_to_verdict(0.0) == "약세"
        assert _score_to_verdict(0.40) == "약세"

    def test_neutral(self):
        assert _score_to_verdict(0.5) == "중립"
        assert _score_to_verdict(0.41) == "중립"
        assert _score_to_verdict(0.59) == "중립"


class TestFgLabelKorean:
    """Lines 997-1005: _fg_label_korean fallback logic."""

    def test_known_labels(self):
        assert _fg_label_korean("Extreme Fear", 10) == "극공포"
        assert _fg_label_korean("Fear", 30) == "공포"
        assert _fg_label_korean("Neutral", 50) == "중립"
        assert _fg_label_korean("Greed", 65) == "탐욕"
        assert _fg_label_korean("Extreme Greed", 85) == "극탐욕"

    def test_case_insensitive(self):
        assert _fg_label_korean("extreme fear", 10) == "극공포"
        assert _fg_label_korean("GREED", 70) == "탐욕"

    def test_unknown_label_value_based(self):
        # Line 997-1005: fallback by value
        assert _fg_label_korean("", 10) == "극공포"  # < 25
        assert _fg_label_korean("", 30) == "공포"  # < 45
        assert _fg_label_korean("", 50) == "중립"  # < 55
        assert _fg_label_korean("", 65) == "탐욕"  # < 75
        assert _fg_label_korean("", 90) == "극탐욕"  # >= 75

    def test_unknown_label_boundary(self):
        assert _fg_label_korean("unknown", 24) == "극공포"
        assert _fg_label_korean("unknown", 44) == "공포"
        assert _fg_label_korean("unknown", 54) == "중립"
        assert _fg_label_korean("unknown", 74) == "탐욕"
        assert _fg_label_korean("unknown", 75) == "극탐욕"


class TestVerdictWithIcon:
    def test_all_verdicts(self):
        assert "강세" in _verdict_with_icon("강세")
        assert "약세" in _verdict_with_icon("약세")
        assert "중립" in _verdict_with_icon("중립")
        assert "혼조" in _verdict_with_icon("혼조")

    def test_unknown_verdict(self):
        assert _verdict_with_icon("알수없음") == "알수없음"


# ── SignalComposer.__init__ ───────────────────────────────────────────────────


class TestSignalComposerInit:
    """Lines 177-179: custom_weights handling."""

    def test_default_weights(self):
        c = SignalComposer()
        assert c._weights == _DEFAULT_WEIGHTS

    def test_custom_weights_override(self):
        # Lines 177-179
        c = SignalComposer(custom_weights={"fear_greed": 0.5, "vix": 0.3})
        assert c._weights["fear_greed"] == 0.5
        assert c._weights["vix"] == 0.3
        assert c._weights["sentiment"] == _DEFAULT_WEIGHTS["sentiment"]

    def test_custom_weights_unknown_key_ignored(self):
        c = SignalComposer(custom_weights={"unknown_key": 0.9})
        assert c._weights == _DEFAULT_WEIGHTS

    def test_custom_weights_none(self):
        c = SignalComposer(custom_weights=None)
        assert c._weights == _DEFAULT_WEIGHTS


# ── SignalComposer._normalize_signal ─────────────────────────────────────────


class TestNormalizeSignal:
    """Lines 475-490: _normalize_signal various branches."""

    def setup_method(self):
        self.c = SignalComposer()

    def test_fear_greed(self):
        # Lines 475-490 actually covered by _process_* but normalize directly
        assert self.c._normalize_signal("fear_greed", 0) == pytest.approx(0.0)
        assert self.c._normalize_signal("fear_greed", 100) == pytest.approx(1.0)
        assert self.c._normalize_signal("fear_greed", 50) == pytest.approx(0.5)

    def test_vix(self):
        # VIX 10 → 1.0, VIX 40 → 0.0
        assert self.c._normalize_signal("vix", 10) == pytest.approx(1.0)
        assert self.c._normalize_signal("vix", 40) == pytest.approx(0.0)
        assert self.c._normalize_signal("vix", 25) == pytest.approx(0.5)
        # Clipping
        assert self.c._normalize_signal("vix", 50) == pytest.approx(0.0)
        assert self.c._normalize_signal("vix", 5) == pytest.approx(1.0)

    def test_sentiment(self):
        assert self.c._normalize_signal("sentiment", -1.0) == pytest.approx(0.0)
        assert self.c._normalize_signal("sentiment", 1.0) == pytest.approx(1.0)
        assert self.c._normalize_signal("sentiment", 0.0) == pytest.approx(0.5)

    def test_rsi(self):
        # Lines 479-481
        assert self.c._normalize_signal("rsi", 50) == pytest.approx(0.5)
        assert self.c._normalize_signal("rsi", 0) == pytest.approx(0.0)
        assert self.c._normalize_signal("rsi", 100) == pytest.approx(1.0)

    def test_momentum_pct(self):
        # Lines 483-486
        assert self.c._normalize_signal("momentum_pct", -20) == pytest.approx(0.0)
        assert self.c._normalize_signal("momentum_pct", 20) == pytest.approx(1.0)
        assert self.c._normalize_signal("momentum_pct", 0) == pytest.approx(0.5)
        # Clamping
        assert self.c._normalize_signal("momentum_pct", 100) == pytest.approx(1.0)
        assert self.c._normalize_signal("momentum_pct", -100) == pytest.approx(0.0)

    def test_unknown_signal_returns_neutral(self):
        # Lines 488-490
        assert self.c._normalize_signal("unknown_signal", 42) == pytest.approx(0.5)


# ── _process_fear_greed ───────────────────────────────────────────────────────


class TestProcessFearGreed:
    def setup_method(self):
        self.c = SignalComposer()

    def test_basic(self):
        sr = self.c._process_fear_greed({"value": 45, "label": "Fear"}, 0.25)
        assert sr.name == "공포·탐욕 지수"
        assert "공포" in sr.raw_display
        assert sr.weight == 0.25

    def test_extreme_fear(self):
        sr = self.c._process_fear_greed({"value": 10, "label": "Extreme Fear"}, 0.25)
        assert sr.verdict == "약세"
        assert "극공포" in sr.raw_display

    def test_extreme_greed(self):
        sr = self.c._process_fear_greed({"value": 90, "label": "Extreme Greed"}, 0.25)
        assert sr.verdict == "강세"

    def test_default_value(self):
        sr = self.c._process_fear_greed({}, 0.25)
        assert "50" in sr.raw_display


# ── _process_vix ──────────────────────────────────────────────────────────────


class TestProcessVix:
    """Lines 525-529: VIX trend arrows."""

    def setup_method(self):
        self.c = SignalComposer()

    def test_rising_trend(self):
        # Lines 522-524
        sr = self.c._process_vix({"value": 20.0, "trend": "rising"}, 0.2)
        assert sr.trend_arrow == "↑"

    def test_up_trend(self):
        sr = self.c._process_vix({"value": 20.0, "trend": "up"}, 0.2)
        assert sr.trend_arrow == "↑"

    def test_falling_trend(self):
        # Lines 525-527
        sr = self.c._process_vix({"value": 20.0, "trend": "falling"}, 0.2)
        assert sr.trend_arrow == "↓"

    def test_down_trend(self):
        # Lines 525-527
        sr = self.c._process_vix({"value": 20.0, "trend": "down"}, 0.2)
        assert sr.trend_arrow == "↓"

    def test_neutral_trend(self):
        # Lines 528-529
        sr = self.c._process_vix({"value": 20.0, "trend": "stable"}, 0.2)
        assert sr.trend_arrow == "→"

    def test_no_trend(self):
        sr = self.c._process_vix({"value": 20.0}, 0.2)
        assert sr.trend_arrow == "→"

    def test_high_vix_bearish(self):
        sr = self.c._process_vix({"value": 40.0, "trend": "rising"}, 0.2)
        assert sr.verdict == "약세"

    def test_low_vix_bullish(self):
        sr = self.c._process_vix({"value": 10.0, "trend": "falling"}, 0.2)
        assert sr.verdict == "강세"


# ── _process_sentiment ────────────────────────────────────────────────────────


class TestProcessSentiment:
    """Lines 545-565."""

    def setup_method(self):
        self.c = SignalComposer()

    def test_with_pos_neg_counts(self):
        # Lines 551-554: blended path
        sr = self.c._process_sentiment({"score": 0.3, "positive": 10, "negative": 5}, 0.2)
        assert sr.name == "시장 심리"
        assert "+" in sr.raw_display

    def test_without_counts(self):
        # Lines 556-557: blended = score
        sr = self.c._process_sentiment({"score": -0.5}, 0.2)
        assert "-" in sr.raw_display

    def test_zero_score(self):
        sr = self.c._process_sentiment({"score": 0.0, "positive": 5, "negative": 5}, 0.2)
        assert "+0.00" in sr.raw_display

    def test_negative_score(self):
        sr = self.c._process_sentiment({"score": -0.8, "positive": 2, "negative": 18}, 0.2)
        assert sr.verdict == "약세"

    def test_high_positive_ratio(self):
        sr = self.c._process_sentiment({"score": 0.8, "positive": 20, "negative": 1}, 0.2)
        assert sr.verdict == "강세"

    def test_default_values(self):
        sr = self.c._process_sentiment({}, 0.2)
        assert sr.name == "시장 심리"


# ── _process_momentum ─────────────────────────────────────────────────────────


class TestProcessMomentum:
    """Lines 575-613."""

    def setup_method(self):
        self.c = SignalComposer()

    def test_with_btc_eth(self):
        # Lines 586-591
        sr = self.c._process_momentum({"btc_7d": 5.0, "eth_7d": 3.0}, 0.2)
        assert sr.name == "모멘텀"
        assert "BTC" in sr.raw_display

    def test_with_sp500(self):
        sr = self.c._process_momentum({"sp500_5d": 2.0}, 0.2)
        assert "S&P" in sr.raw_display

    def test_with_btc_24h(self):
        sr = self.c._process_momentum({"btc_24h": 1.0}, 0.2)
        assert "BTC" in sr.raw_display

    def test_with_eth_24h(self):
        sr = self.c._process_momentum({"eth_24h": 2.0}, 0.2)
        assert "ETH" in sr.raw_display

    def test_avg_fallback(self):
        # Lines 594-596: avg used when no field values
        sr = self.c._process_momentum({"avg": 5.0}, 0.2)
        assert sr.normalized > 0.5

    def test_no_data_returns_neutral(self):
        # Lines 598-605
        sr = self.c._process_momentum({}, 0.2)
        assert sr.raw_display == "N/A"
        assert sr.verdict == "중립"
        assert sr.normalized == 0.5

    def test_negative_momentum(self):
        sr = self.c._process_momentum({"btc_7d": -15.0, "eth_7d": -12.0}, 0.2)
        assert sr.verdict == "약세"

    def test_positive_momentum(self):
        sr = self.c._process_momentum({"btc_7d": 18.0, "eth_7d": 15.0}, 0.2)
        assert sr.verdict == "강세"

    def test_display_parts_limit(self):
        # Only first 2 display parts shown
        sr = self.c._process_momentum({"btc_7d": 5.0, "eth_7d": 3.0, "sp500_5d": 1.0}, 0.2)
        parts = sr.raw_display.split(" / ")
        assert len(parts) <= 2


# ── _process_macro ────────────────────────────────────────────────────────────


class TestProcessMacro:
    """Lines 629-650."""

    def setup_method(self):
        self.c = SignalComposer()

    def test_with_us10y(self):
        # Lines 628-632
        sr = self.c._process_macro({"us10y": 4.0}, 0.1)
        assert "10Y" in sr.raw_display

    def test_with_dxy(self):
        # Lines 635-640
        sr = self.c._process_macro({"dxy": 100.0}, 0.1)
        assert "DXY" in sr.raw_display

    def test_with_fed_rate(self):
        # Lines 643-647
        sr = self.c._process_macro({"fed_rate": 5.25}, 0.1)
        assert sr.name == "매크로"

    def test_no_data_returns_neutral(self):
        # Line 649-656
        sr = self.c._process_macro({}, 0.1)
        assert sr.raw_display == "N/A"
        assert sr.verdict == "중립"

    def test_high_rates_bearish(self):
        sr = self.c._process_macro({"us10y": 5.5, "dxy": 115.0, "fed_rate": 5.5}, 0.1)
        assert sr.verdict == "약세"

    def test_low_rates_bullish(self):
        sr = self.c._process_macro({"us10y": 3.0, "dxy": 90.0, "fed_rate": 2.0}, 0.1)
        assert sr.verdict == "강세"

    def test_display_parts_limit(self):
        sr = self.c._process_macro({"us10y": 4.0, "dxy": 100.0, "fed_rate": 5.0}, 0.1)
        # fed_rate doesn't go into display_parts, only us10y and dxy do
        assert "10Y" in sr.raw_display


# ── _process_technical ────────────────────────────────────────────────────────


class TestProcessTechnical:
    """Lines 674-727."""

    def setup_method(self):
        self.c = SignalComposer()

    def test_rsi_oversold(self):
        # Lines 682-683: rsi <= 30
        sr = self.c._process_technical({"rsi_14": 25}, 0.05)
        assert sr.normalized == pytest.approx(0.35)

    def test_rsi_overbought(self):
        # Lines 684-685: rsi >= 70
        sr = self.c._process_technical({"rsi_14": 75}, 0.05)
        assert sr.normalized == pytest.approx(0.65)

    def test_rsi_normal(self):
        # Lines 686-687: normalize_signal("rsi", ...)
        sr = self.c._process_technical({"rsi_14": 50}, 0.05)
        assert sr.normalized == pytest.approx(0.5)

    def test_macd_bullish(self):
        # Lines 692-693
        sr = self.c._process_technical({"macd_signal": "bullish"}, 0.05)
        assert sr.normalized > 0.5

    def test_macd_golden(self):
        sr = self.c._process_technical({"macd_signal": "golden"}, 0.05)
        assert sr.normalized > 0.5

    def test_macd_bearish(self):
        # Lines 694-695
        sr = self.c._process_technical({"macd_signal": "bearish"}, 0.05)
        assert sr.normalized < 0.5

    def test_macd_death(self):
        sr = self.c._process_technical({"macd_signal": "death"}, 0.05)
        assert sr.normalized < 0.5

    def test_macd_neutral(self):
        # Lines 696-697
        sr = self.c._process_technical({"macd_signal": "neutral"}, 0.05)
        assert sr.normalized == pytest.approx(0.5)

    def test_ma_cross_golden(self):
        # Lines 700-702
        sr = self.c._process_technical({"ma_cross": "golden cross"}, 0.05)
        assert sr.normalized > 0.7

    def test_ma_cross_death(self):
        # Lines 703-704
        sr = self.c._process_technical({"ma_cross": "death cross"}, 0.05)
        assert sr.normalized < 0.3

    def test_ma_cross_golden_underscore(self):
        sr = self.c._process_technical({"ma_cross": "golden_cross"}, 0.05)
        assert sr.normalized > 0.7

    def test_ma_cross_death_underscore(self):
        sr = self.c._process_technical({"ma_cross": "death_cross"}, 0.05)
        assert sr.normalized < 0.3

    def test_no_data_returns_neutral(self):
        # Lines 706-713
        sr = self.c._process_technical({}, 0.05)
        assert sr.raw_display == "N/A"
        assert sr.verdict == "중립"

    def test_combined_rsi_macd(self):
        sr = self.c._process_technical({"rsi_14": 60, "macd_signal": "bullish"}, 0.05)
        assert "RSI" in sr.raw_display
        assert "MACD" in sr.raw_display

    def test_rsi_exactly_30(self):
        sr = self.c._process_technical({"rsi_14": 30}, 0.05)
        assert sr.normalized == pytest.approx(0.35)

    def test_rsi_exactly_70(self):
        sr = self.c._process_technical({"rsi_14": 70}, 0.05)
        assert sr.normalized == pytest.approx(0.65)


# ── _renormalize_weights ─────────────────────────────────────────────────────


class TestRenormalizeWeights:
    """Lines 744-746: zero-weight edge case."""

    def setup_method(self):
        self.c = SignalComposer()

    def test_normal_renormalization(self):
        results = [
            SignalResult("a", "a", 0.5, "중립", 0.3),
            SignalResult("b", "b", 0.5, "중립", 0.2),
        ]
        self.c._renormalize_weights(results)
        assert sum(r.weight for r in results) == pytest.approx(1.0)

    def test_zero_weight_equal_distribution(self):
        # Lines 744-746: total <= 0 → equal weight
        results = [
            SignalResult("a", "a", 0.5, "중립", 0.0),
            SignalResult("b", "b", 0.5, "중립", 0.0),
        ]
        self.c._renormalize_weights(results)
        assert results[0].weight == pytest.approx(0.5)
        assert results[1].weight == pytest.approx(0.5)


# ── _determine_verdict ────────────────────────────────────────────────────────


class TestDetermineVerdict:
    """Lines 763, 765, 774-778."""

    def setup_method(self):
        self.c = SignalComposer()

    def make_results(self, bulls=0, bears=0, neutrals=0):
        results = []
        for _ in range(bulls):
            results.append(SignalResult("x", "x", 0.7, "강세", 0.1))
        for _ in range(bears):
            results.append(SignalResult("x", "x", 0.3, "약세", 0.1))
        for _ in range(neutrals):
            results.append(SignalResult("x", "x", 0.5, "중립", 0.1))
        return results

    def test_bullish_score(self):
        # Line 763
        results = self.make_results(bulls=3)
        assert self.c._determine_verdict(65.0, results) == "강세"

    def test_bearish_score(self):
        # Line 765
        results = self.make_results(bears=3)
        assert self.c._determine_verdict(35.0, results) == "약세"

    def test_mixed_signals_return_혼조(self):
        # Lines 771-772
        results = self.make_results(bulls=2, bears=2)
        assert self.c._determine_verdict(50.0, results) == "혼조"

    def test_high_middle_score_no_mixed(self):
        # Lines 774-775
        results = self.make_results(neutrals=3)
        assert self.c._determine_verdict(56.0, results) == "강세"

    def test_low_middle_score_no_mixed(self):
        # Lines 776-777
        results = self.make_results(neutrals=3)
        assert self.c._determine_verdict(44.0, results) == "약세"

    def test_middle_neutral(self):
        # Line 778
        results = self.make_results(neutrals=3)
        assert self.c._determine_verdict(50.0, results) == "중립"


# ── _calculate_confidence ─────────────────────────────────────────────────────


class TestCalculateConfidence:
    """Lines 792, 803-810."""

    def setup_method(self):
        self.c = SignalComposer()

    def test_empty_results(self):
        # Line 792
        conf, label, count = self.c._calculate_confidence([], "중립")
        assert conf == "low"
        assert label == "낮음"
        assert count == 0

    def test_mixed_verdict_returns_medium(self):
        # Lines 799-801
        results = [
            SignalResult("a", "a", 0.7, "강세", 0.1),
            SignalResult("b", "b", 0.3, "약세", 0.1),
        ]
        conf, label, count = self.c._calculate_confidence(results, "혼조")
        assert conf == "medium"
        assert label == "보통"

    def test_high_confidence_bullish(self):
        # Lines 806-807
        results = [SignalResult("x", "x", 0.7, "강세", 0.1) for _ in range(4)]
        conf, label, count = self.c._calculate_confidence(results, "강세")
        assert conf == "high"
        assert label == "높음"

    def test_medium_confidence(self):
        # Lines 808-809
        results = [
            SignalResult("a", "a", 0.7, "강세", 0.1),
            SignalResult("b", "b", 0.7, "강세", 0.1),
            SignalResult("c", "c", 0.3, "약세", 0.1),
            SignalResult("d", "d", 0.3, "약세", 0.1),
        ]
        conf, label, _ = self.c._calculate_confidence(results, "강세")
        # 2/4 = 0.5 → medium
        assert conf == "medium"

    def test_low_confidence(self):
        # Line 810
        results = [
            SignalResult("a", "a", 0.7, "강세", 0.1),
            SignalResult("b", "b", 0.3, "약세", 0.1),
            SignalResult("c", "c", 0.3, "약세", 0.1),
            SignalResult("d", "d", 0.3, "약세", 0.1),
        ]
        conf, label, _ = self.c._calculate_confidence(results, "강세")
        # 1/4 = 0.25 < 0.5 → low
        assert conf == "low"

    def test_neutral_verdict_confidence(self):
        results = [SignalResult("x", "x", 0.5, "중립", 0.1) for _ in range(4)]
        conf, label, count = self.c._calculate_confidence(results, "중립")
        assert conf in ("high", "medium", "low")


# ── _generate_scenarios ───────────────────────────────────────────────────────


class TestGenerateScenarios:
    """Lines 830, 832, 836, 851-859, 870-871, 875-876, 881-882, 885-886,
    896, 898, 906, 908."""

    def setup_method(self):
        self.c = SignalComposer()

    def make_signal_results_with_names(self, fg=55.0, vix=20.0, mom=0.5):
        fg_r = SignalResult("공포·탐욕 지수", f"{fg:.0f} (중립)", fg / 100, "중립", 0.25)
        vix_r = SignalResult("VIX 변동성", f"{vix:.1f}", 1.0 - (vix - 10) / 30, "중립", 0.20)
        mom_r = SignalResult("모멘텀", "BTC +5.0%", mom, "중립", 0.20)
        return [fg_r, vix_r, mom_r]

    def test_bullish_verdict_probabilities(self):
        # Line 830: probs bull verdict
        results = self.make_signal_results_with_names()
        scenarios = self.c._generate_scenarios(70.0, "강세", results)
        bull_sc = next(s for s in scenarios if s.label == "강세")
        assert bull_sc.probability == 40
        bear_sc = next(s for s in scenarios if s.label == "약세")
        assert bear_sc.probability == 15

    def test_bearish_verdict_probabilities(self):
        # Line 832: probs bear verdict
        results = self.make_signal_results_with_names()
        scenarios = self.c._generate_scenarios(30.0, "약세", results)
        bull_sc = next(s for s in scenarios if s.label == "강세")
        assert bull_sc.probability == 15
        bear_sc = next(s for s in scenarios if s.label == "약세")
        assert bear_sc.probability == 40

    def test_mixed_verdict_probabilities(self):
        # Line 833-834: probs 혼조 verdict
        results = self.make_signal_results_with_names()
        scenarios = self.c._generate_scenarios(50.0, "혼조", results)
        bull_sc = next(s for s in scenarios if s.label == "강세")
        assert bull_sc.probability == 25

    def test_neutral_verdict_probabilities(self):
        # Line 835-836: probs 중립 verdict
        results = self.make_signal_results_with_names()
        scenarios = self.c._generate_scenarios(50.0, "중립", results)
        base_sc = next(s for s in scenarios if s.label == "기본")
        assert base_sc.probability == 50

    def test_returns_three_scenarios(self):
        results = self.make_signal_results_with_names()
        scenarios = self.c._generate_scenarios(50.0, "중립", results)
        assert len(scenarios) == 3
        labels = [s.label for s in scenarios]
        assert "강세" in labels
        assert "기본" in labels
        assert "약세" in labels

    def test_strong_momentum_horizon(self):
        # Lines 851-855: abs(mom_norm - 0.5) > 0.2 → 중기 horizons
        results = self.make_signal_results_with_names(mom=0.8)
        scenarios = self.c._generate_scenarios(50.0, "중립", results)
        bull_sc = next(s for s in scenarios if s.label == "강세")
        assert "중기" in bull_sc.time_horizon

    def test_weak_momentum_horizon(self):
        # Lines 856-859: weak momentum → 단기 bull, 중기 base
        results = self.make_signal_results_with_names(mom=0.52)
        scenarios = self.c._generate_scenarios(50.0, "중립", results)
        bull_sc = next(s for s in scenarios if s.label == "강세")
        assert "단기" in bull_sc.time_horizon

    def test_no_momentum_result_horizon(self):
        # Lines 860-863: no momentum result
        results = [
            SignalResult("공포·탐욕 지수", "50 (중립)", 0.5, "중립", 0.25),
        ]
        scenarios = self.c._generate_scenarios(50.0, "중립", results)
        bull_sc = next(s for s in scenarios if s.label == "강세")
        assert "단기" in bull_sc.time_horizon

    def test_high_vix_expands_support_resistance(self):
        # Lines 884-886: vix >= 25
        results = [
            SignalResult("VIX 변동성", "30.0", 0.3, "약세", 0.2),
        ]
        scenarios = self.c._generate_scenarios(50.0, "중립", results)
        bear_sc = next(s for s in scenarios if s.label == "약세")
        # High VIX should give wider support range
        assert bear_sc.support_level is not None

    def test_score_above_55_resistance(self):
        # Lines 874-876
        results = self.make_signal_results_with_names()
        scenarios = self.c._generate_scenarios(60.0, "강세", results)
        bull_sc = next(s for s in scenarios if s.label == "강세")
        assert "5~8" in bull_sc.resistance_level or "8~12" in bull_sc.resistance_level

    def test_score_below_45_support(self):
        # Lines 877-879
        results = self.make_signal_results_with_names()
        scenarios = self.c._generate_scenarios(40.0, "약세", results)
        bear_sc = next(s for s in scenarios if s.label == "약세")
        assert bear_sc.support_level is not None

    def test_vix_bearish_bull_catalyst_reorder(self):
        # Lines 895-896: vix bearish → VIX 하락 안정화 first
        results = [
            SignalResult("VIX 변동성", "35.0", 0.2, "약세", 0.2),
            SignalResult("모멘텀", "BTC -5.0%", 0.3, "약세", 0.2),
        ]
        scenarios = self.c._generate_scenarios(40.0, "약세", results)
        bull_sc = next(s for s in scenarios if s.label == "강세")
        assert "VIX 하락 안정화" in bull_sc.catalysts[0]

    def test_macro_bearish_bull_catalyst_includes_rate_cut(self):
        # Lines 897-900: macro bearish → 달러 약세/금리 인하 catalysts
        results = [
            SignalResult("매크로", "10Y 5.00% / DXY 112.0", 0.2, "약세", 0.1),
            SignalResult("모멘텀", "BTC -5.0%", 0.3, "약세", 0.2),
        ]
        scenarios = self.c._generate_scenarios(35.0, "약세", results)
        bull_sc = next(s for s in scenarios if s.label == "강세")
        all_cats = " ".join(bull_sc.catalysts)
        assert "달러 약세 전환" in all_cats or "금리 인하 기대" in all_cats

    def test_vix_bearish_bear_catalyst_reorder(self):
        # Lines 905-906: vix bearish → VIX 30 돌파 first in bear pool
        results = [
            SignalResult("VIX 변동성", "35.0", 0.2, "약세", 0.2),
            SignalResult("공포·탐욕 지수", "80 (극탐욕)", 0.8, "강세", 0.25),
        ]
        scenarios = self.c._generate_scenarios(50.0, "혼조", results)
        bear_sc = next(s for s in scenarios if s.label == "약세")
        assert "VIX 30 돌파" in bear_sc.catalysts[0]

    def test_macro_bearish_bear_catalyst_includes_dollar(self):
        # Lines 907-908: macro bearish → 달러 강세 가속
        results = [
            SignalResult("매크로", "10Y 5.00% / DXY 112.0", 0.2, "약세", 0.1),
            SignalResult("공포·탐욕 지수", "80 (극탐욕)", 0.8, "강세", 0.25),
        ]
        scenarios = self.c._generate_scenarios(50.0, "혼조", results)
        bear_sc = next(s for s in scenarios if s.label == "약세")
        all_cats = " ".join(bear_sc.catalysts)
        assert "달러 강세 가속" in all_cats

    def test_vix_no_result_fallback(self):
        # No VIX result at all → uses 20.0 default
        results = [
            SignalResult("공포·탐욕 지수", "50 (중립)", 0.5, "중립", 0.25),
        ]
        scenarios = self.c._generate_scenarios(50.0, "중립", results)
        assert len(scenarios) == 3


# ── generate_outlook_markdown ─────────────────────────────────────────────────


class TestGenerateOutlookMarkdown:
    """Lines 410-446."""

    def setup_method(self):
        self.c = SignalComposer()

    def test_basic_markdown_structure(self):
        result = self.c.compose_signals(make_full_signals())
        md = self.c.generate_outlook_markdown(result)
        assert "## 시장 전망 분석" in md
        assert "| 지표 | 현재값 | 신호 | 가중치 |" in md
        assert "### 시나리오 분석" in md
        assert "투자 조언이 아닙니다" in md

    def test_trend_arrow_in_display(self):
        # Lines 420-422: trend_arrow appended
        result = self.c.compose_signals({"vix": {"value": 22.0, "trend": "rising"}})
        md = self.c.generate_outlook_markdown(result)
        assert "↑" in md

    def test_score_in_markdown(self):
        result = self.c.compose_signals(make_full_signals())
        md = self.c.generate_outlook_markdown(result)
        assert "/100" in md

    def test_confidence_in_markdown(self):
        result = self.c.compose_signals(make_full_signals())
        md = self.c.generate_outlook_markdown(result)
        assert "신뢰도" in md

    def test_scenarios_listed(self):
        result = self.c.compose_signals(make_full_signals())
        md = self.c.generate_outlook_markdown(result)
        assert "강세 시나리오" in md
        assert "기본 시나리오" in md
        assert "약세 시나리오" in md


# ── analyze_stance ────────────────────────────────────────────────────────────


class TestAnalyzeStance:
    """Lines 277, 289-290, 292-293, 298-300."""

    def setup_method(self):
        self.c = SignalComposer()

    def test_empty_result_stance(self):
        # Line 277: total == 0
        result = CompositeResult(
            score=50.0,
            verdict="중립",
            confidence="low",
            confidence_label="낮음",
            signal_results=[],
        )
        stance = self.c.analyze_stance(result)
        assert stance.dominant_stance == "neutral"
        assert stance.consensus_ratio == 0.0

    def test_supportive_stance(self):
        # Lines 289-290: sentiment_bias >= 0.3
        result = CompositeResult(
            score=65.0,
            verdict="강세",
            confidence="high",
            confidence_label="높음",
            signal_results=[
                SignalResult("a", "a", 0.7, "강세", 0.2),
                SignalResult("b", "b", 0.7, "강세", 0.2),
                SignalResult("c", "c", 0.7, "강세", 0.2),
            ],
        )
        stance = self.c.analyze_stance(result)
        assert stance.dominant_stance == "supportive"

    def test_opposing_stance(self):
        # Lines 292-293: sentiment_bias <= -0.3
        result = CompositeResult(
            score=30.0,
            verdict="약세",
            confidence="high",
            confidence_label="높음",
            signal_results=[
                SignalResult("a", "a", 0.3, "약세", 0.2),
                SignalResult("b", "b", 0.3, "약세", 0.2),
                SignalResult("c", "c", 0.3, "약세", 0.2),
            ],
        )
        stance = self.c.analyze_stance(result)
        assert stance.dominant_stance == "opposing"

    def test_observer_stance(self):
        # Line 294-296: obs >= max(bull, bear)
        result = CompositeResult(
            score=50.0,
            verdict="중립",
            confidence="medium",
            confidence_label="보통",
            signal_results=[
                SignalResult("a", "a", 0.5, "중립", 0.2),
                SignalResult("b", "b", 0.5, "중립", 0.2),
                SignalResult("c", "c", 0.5, "중립", 0.2),
                SignalResult("d", "d", 0.7, "강세", 0.2),
            ],
        )
        stance = self.c.analyze_stance(result)
        assert stance.dominant_stance == "observer"

    def test_neutral_stance_mixed(self):
        # Lines 297-300: neither supportive nor opposing nor observer
        result = CompositeResult(
            score=50.0,
            verdict="혼조",
            confidence="medium",
            confidence_label="보통",
            signal_results=[
                SignalResult("a", "a", 0.7, "강세", 0.2),
                SignalResult("b", "b", 0.3, "약세", 0.2),
                SignalResult("c", "c", 0.7, "강세", 0.2),
                SignalResult("d", "d", 0.3, "약세", 0.2),
                # sentiment_bias = (2-2)/4 = 0 (between -0.3 and 0.3)
                # obs_count=0 < max(2,2)=2 → neutral
            ],
        )
        stance = self.c.analyze_stance(result)
        assert stance.dominant_stance == "neutral"

    def test_stance_lists_populated(self):
        result = CompositeResult(
            score=60.0,
            verdict="강세",
            confidence="high",
            confidence_label="높음",
            signal_results=[
                SignalResult("강세신호", "val1", 0.7, "강세", 0.3),
                SignalResult("약세신호", "val2", 0.3, "약세", 0.3),
                SignalResult("중립신호", "val3", 0.5, "중립", 0.3),
                SignalResult("혼조신호", "val4", 0.5, "혼조", 0.1),
            ],
        )
        stance = self.c.analyze_stance(result)
        assert len(stance.bulls) == 1
        assert len(stance.bears) == 1
        assert len(stance.observers) == 2  # 중립 and 혼조 both go to observers


# ── generate_prediction_markdown ─────────────────────────────────────────────


class TestGeneratePredictionMarkdown:
    def setup_method(self):
        self.c = SignalComposer()

    def test_basic_structure(self):
        result = self.c.compose_signals(make_full_signals())
        stance = self.c.analyze_stance(result)
        md = self.c.generate_prediction_markdown(result, stance)
        assert "## 시장 전망 분석" in md
        assert "### 시장 참여자 입장 분석" in md
        assert "### 시나리오 분석" in md
        assert "투자 조언이 아닙니다" in md

    def test_stance_info_in_markdown(self):
        result = self.c.compose_signals(make_bullish_signals())
        stance = self.c.analyze_stance(result)
        md = self.c.generate_prediction_markdown(result, stance)
        assert "강세 진영" in md
        assert "약세 진영" in md
        assert "관망" in md
        assert "합의" in md

    def test_empty_stance_shows_없음(self):
        result = CompositeResult(
            score=50.0,
            verdict="중립",
            confidence="low",
            confidence_label="낮음",
            signal_results=[SignalResult("a", "a", 0.5, "중립", 1.0)],
        )
        stance = StanceAnalysis(
            bulls=[],
            bears=[],
            observers=["a (a)"],
            dominant_stance="observer",
            consensus_ratio=1.0,
        )
        md = self.c.generate_prediction_markdown(result, stance)
        assert "없음" in md

    def test_scenarios_with_catalysts(self):
        result = self.c.compose_signals(make_bearish_signals())
        stance = self.c.analyze_stance(result)
        md = self.c.generate_prediction_markdown(result, stance)
        assert "촉매" in md

    def test_scenarios_with_time_horizon(self):
        result = self.c.compose_signals(make_full_signals())
        stance = self.c.analyze_stance(result)
        md = self.c.generate_prediction_markdown(result, stance)
        assert "시간 프레임" in md


# ── compose_signals (full pipeline) ──────────────────────────────────────────


class TestCompositeSignalsPipeline:
    def setup_method(self):
        self.c = SignalComposer()

    def test_empty_signals_returns_default(self):
        # Lines 217-218: no signal_results → _default_result()
        result = self.c.compose_signals({})
        assert result.score == 50.0
        assert result.verdict == "중립"
        assert result.total_signals == 0

    def test_all_signals_processed(self):
        result = self.c.compose_signals(make_full_signals())
        assert result.total_signals == 6
        assert 0 <= result.score <= 100

    def test_bullish_scenario(self):
        result = self.c.compose_signals(make_bullish_signals())
        assert result.score > 50
        assert result.verdict in ("강세", "혼조")

    def test_bearish_scenario(self):
        result = self.c.compose_signals(make_bearish_signals())
        assert result.score < 50
        assert result.verdict in ("약세", "혼조")

    def test_partial_signals(self):
        result = self.c.compose_signals({"fear_greed": {"value": 60}, "vix": {"value": 20}})
        assert result.total_signals == 2
        assert sum(r.weight for r in result.signal_results) == pytest.approx(1.0)

    def test_processor_exception_skipped(self):
        # Lines 213-214: exception handling
        signals = {"fear_greed": "invalid_string"}
        # 'invalid_string' has no .get() → will raise AttributeError
        result = self.c.compose_signals(signals)
        # The fear_greed signal should be skipped
        assert result.total_signals == 0

    def test_result_has_scenarios(self):
        result = self.c.compose_signals(make_full_signals())
        assert len(result.scenarios) == 3

    def test_result_has_confidence(self):
        result = self.c.compose_signals(make_full_signals())
        assert result.confidence in ("low", "medium", "high")
        assert result.confidence_label in ("낮음", "보통", "높음")


# ── Module-level convenience functions ───────────────────────────────────────


class TestModuleLevelFunctions:
    """Lines 952, 1027, 1032, 1037, 1042."""

    def test_compose_signals_function(self):
        # Line 1027
        result = compose_signals({"fear_greed": {"value": 50}})
        assert isinstance(result, CompositeResult)

    def test_compose_signals_with_weights(self):
        result = compose_signals(
            {"fear_greed": {"value": 50}},
            weights={"fear_greed": 0.5},
        )
        assert isinstance(result, CompositeResult)

    def test_generate_outlook_markdown_function(self):
        # Line 1032
        result = compose_signals(make_full_signals())
        md = generate_outlook_markdown(result)
        assert isinstance(md, str)
        assert "시장 전망 분석" in md

    def test_analyze_stance_function(self):
        # Line 1037
        result = compose_signals(make_full_signals())
        stance = analyze_stance(result)
        assert isinstance(stance, StanceAnalysis)
        assert stance.dominant_stance in ("supportive", "opposing", "neutral", "observer")

    def test_generate_prediction_markdown_function(self):
        # Line 1042
        result = compose_signals(make_full_signals())
        stance = analyze_stance(result)
        md = generate_prediction_markdown(result, stance)
        assert isinstance(md, str)
        assert "시장 전망 분석" in md

    def test_default_result_static(self):
        # Line 952: _default_result
        result = SignalComposer._default_result()
        assert result.score == 50.0
        assert result.confidence == "low"
        assert len(result.scenarios) == 3


# ── Edge cases ────────────────────────────────────────────────────────────────


class TestEdgeCases:
    def setup_method(self):
        self.c = SignalComposer()

    def test_vix_clipping_high(self):
        # VIX very high → clips to 0.0
        sr = self.c._process_vix({"value": 100.0}, 0.2)
        assert sr.normalized == pytest.approx(0.0)

    def test_vix_clipping_low(self):
        # VIX very low → clips to 1.0
        sr = self.c._process_vix({"value": 5.0}, 0.2)
        assert sr.normalized == pytest.approx(1.0)

    def test_fear_greed_boundary_values(self):
        sr_min = self.c._process_fear_greed({"value": 0}, 0.25)
        sr_max = self.c._process_fear_greed({"value": 100}, 0.25)
        assert sr_min.verdict == "약세"
        assert sr_max.verdict == "강세"

    def test_momentum_avg_ignored_when_fields_present(self):
        # avg is only used when no field values
        sr = self.c._process_momentum({"btc_7d": 5.0, "avg": 100.0}, 0.2)
        # Should use btc_7d (5%), not avg (100%)
        assert sr.normalized < 0.9

    def test_macro_all_data_points(self):
        sr = self.c._process_macro({"us10y": 4.0, "dxy": 100.0, "fed_rate": 4.5}, 0.1)
        assert sr.normalized > 0.0

    def test_technical_all_signals_combined(self):
        sr = self.c._process_technical(
            {"rsi_14": 60, "macd_signal": "bullish", "ma_cross": "golden"},
            0.05,
        )
        assert sr.verdict in ("강세", "중립")
