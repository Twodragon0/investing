"""Tests for bettafish_analyzer utility functions."""

from common.bettafish_analyzer import (
    _confidence_from_agreement,
    _format_list_inline,
    _score_to_verdict,
    _verdict_to_score,
)


class TestVerdictToScore:
    def test_bullish(self):
        assert _verdict_to_score("강세") == 1.0

    def test_bearish(self):
        assert _verdict_to_score("약세") == -1.0

    def test_neutral(self):
        assert _verdict_to_score("중립") == 0.0

    def test_mixed(self):
        assert _verdict_to_score("혼조") == 0.0

    def test_unknown(self):
        assert _verdict_to_score("unknown") == 0.0


class TestScoreToVerdict:
    def test_strong_positive(self):
        assert _score_to_verdict(0.8) == "강세"

    def test_strong_negative(self):
        assert _score_to_verdict(-0.6) == "약세"

    def test_neutral_zone(self):
        assert _score_to_verdict(0.05) == "중립"

    def test_mixed_positive(self):
        assert _score_to_verdict(0.3) == "혼조"

    def test_mixed_negative(self):
        assert _score_to_verdict(-0.3) == "혼조"

    def test_boundary_bullish(self):
        assert _score_to_verdict(0.4) == "강세"

    def test_boundary_bearish(self):
        assert _score_to_verdict(-0.4) == "약세"


class TestConfidenceFromAgreement:
    def test_zero_total(self):
        assert _confidence_from_agreement(0, 0) == "low"

    def test_high_confidence(self):
        assert _confidence_from_agreement(4, 5) == "high"

    def test_medium_confidence(self):
        assert _confidence_from_agreement(3, 5) == "medium"

    def test_low_confidence(self):
        assert _confidence_from_agreement(1, 5) == "low"

    def test_perfect_agreement(self):
        assert _confidence_from_agreement(5, 5) == "high"


class TestFormatListInline:
    def test_basic(self):
        assert _format_list_inline(["a", "b", "c"]) == "a, b, c"

    def test_empty(self):
        assert _format_list_inline([]) == "없음"

    def test_custom_sep(self):
        assert _format_list_inline(["x", "y"], " | ") == "x | y"

    def test_single_item(self):
        assert _format_list_inline(["only"]) == "only"


class TestDataPerspective:
    def test_none_input_returns_neutral(self):
        from common.bettafish_analyzer import DataPerspective

        dp = DataPerspective()
        result = dp.analyze(None)
        assert result["verdict"] == "중립"
        assert result["score"] == 0.0
        assert "데이터 신호가 제공되지 않아" in result["narrative"]

    def test_none_returns_defaults(self):
        from common.bettafish_analyzer import DataPerspective

        dp = DataPerspective()
        result = dp.analyze(None)
        assert result["strongest_bullish"] == ""
        assert result["strongest_bearish"] == ""
        assert result["agreement_ratio"] == 0.0


class TestBuildNarrative:
    def test_no_signals(self):
        from common.bettafish_analyzer import DataPerspective

        dp = DataPerspective()
        result = dp._build_narrative(
            score=50,
            verdict="중립",
            total_signals=0,
            agreement_ratio=0.3,
            signal_summary="",
            strongest_bullish="",
            strongest_bearish="",
            confidence_label="low",
        )
        assert "정량 데이터 신호가 부족" in result

    def test_bullish_only(self):
        from common.bettafish_analyzer import DataPerspective

        dp = DataPerspective()
        result = dp._build_narrative(
            score=70,
            verdict="강세",
            total_signals=5,
            agreement_ratio=0.8,
            signal_summary="강세 4 / 약세 1",
            strongest_bullish="Fear & Greed",
            strongest_bearish="",
            confidence_label="high",
        )
        assert "Fear & Greed" in result
        assert "컨센서스" in result

    def test_bearish_only(self):
        from common.bettafish_analyzer import DataPerspective

        dp = DataPerspective()
        result = dp._build_narrative(
            score=30,
            verdict="약세",
            total_signals=3,
            agreement_ratio=0.5,
            signal_summary="강세 1 / 약세 2",
            strongest_bullish="",
            strongest_bearish="VIX 급등",
            confidence_label="medium",
        )
        assert "VIX 급등" in result
        assert "추가 지표" in result
