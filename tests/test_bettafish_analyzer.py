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


# ---------------------------------------------------------------------------
# SentimentPerspective tests
# ---------------------------------------------------------------------------


class TestSentimentPerspective:
    def test_none_inputs_returns_neutral(self):
        from common.bettafish_analyzer import SentimentPerspective

        sp = SentimentPerspective()
        result = sp.analyze(None, None)
        assert result["verdict"] == "중립"
        assert result["sentiment_score"] == 0.0
        assert isinstance(result["narrative"], str)

    def test_with_keywords(self):
        from common.bettafish_analyzer import SentimentPerspective

        keywords = [
            {"keyword": "bitcoin", "count": 10, "sentiment": 0.8},
            {"keyword": "crash", "count": 3, "sentiment": -0.5},
        ]
        sp = SentimentPerspective()
        result = sp.analyze(None, keywords)
        assert result["verdict"] in ("강세", "약세", "중립", "혼조")
        assert isinstance(result["narrative"], str)
        assert len(result["narrative"]) > 0


# ---------------------------------------------------------------------------
# MacroPerspective tests
# ---------------------------------------------------------------------------


class TestMacroPerspective:
    def test_none_input_returns_neutral(self):
        from common.bettafish_analyzer import MacroPerspective

        mp = MacroPerspective()
        result = mp.analyze(None)
        assert result["verdict"] == "중립"
        assert "매크로" in result["narrative"] and "제공되지 않아" in result["narrative"]

    def test_with_macro_data(self):
        from common.bettafish_analyzer import MacroPerspective

        macro = {
            "us10y": 4.5,
            "us10y_trend": "rising",
            "dxy": 104.0,
            "dxy_trend": "stable",
            "vix": 28.0,
            "fed_rate": 5.25,
        }
        mp = MacroPerspective()
        result = mp.analyze(macro)
        assert result["verdict"] in ("강세", "약세", "중립", "혼조")
        assert isinstance(result["narrative"], str)
        assert len(result["narrative"]) > 10


# ---------------------------------------------------------------------------
# ForumSynthesis tests
# ---------------------------------------------------------------------------


class TestForumSynthesis:
    def _make_perspective_result(self, verdict="중립", score=0.0, narrative="분석 내용"):
        return {
            "verdict": verdict,
            "score": score,
            "narrative": narrative,
            "strongest_bullish": "",
            "strongest_bearish": "",
            "agreement_ratio": 0.5,
        }

    def test_synthesize_all_neutral(self):
        from common.bettafish_analyzer import ForumSynthesis

        forum = ForumSynthesis()
        result = forum.synthesize(
            self._make_perspective_result(),
            self._make_perspective_result(),
            self._make_perspective_result(),
        )
        assert result["verdict"] in ("강세", "약세", "중립", "혼조")
        assert isinstance(result["synthesis"], str)
        assert isinstance(result["risk_factors"], list)
        assert isinstance(result["opportunities"], list)

    def test_synthesize_mixed_signals(self):
        from common.bettafish_analyzer import ForumSynthesis

        forum = ForumSynthesis()
        result = forum.synthesize(
            self._make_perspective_result("강세", 0.7, "데이터 강세 신호"),
            self._make_perspective_result("약세", -0.5, "심리 약세"),
            self._make_perspective_result("중립", 0.0, "매크로 중립"),
        )
        assert result["verdict"] in ("강세", "약세", "중립", "혼조")
        assert result["confidence"] in ("low", "medium", "high")

    def test_cite_evidence(self):
        from common.bettafish_analyzer import ForumSynthesis

        forum = ForumSynthesis()
        result = forum._cite_evidence(
            narratives={"data": "데이터 분석", "sentiment": "심리 분석", "macro": "매크로 분석"},
            insights=[],
            chapters=[],
        )
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# InsightForge tests
# ---------------------------------------------------------------------------


class TestInsightForge:
    def test_decompose_returns_questions(self):
        from common.bettafish_analyzer import InsightForge

        forge = InsightForge()
        questions = forge.decompose("강세", {})
        assert isinstance(questions, list)
        assert len(questions) > 0

    def test_analyze_sub_questions(self):
        from common.bettafish_analyzer import InsightForge

        forge = InsightForge()
        questions = forge.decompose("약세", {"macro_data": {"vix": 30}})
        results = forge.analyze_sub_questions(questions, {"macro_data": {"vix": 30}})
        assert isinstance(results, list)
        assert len(results) == len(questions)
        for r in results:
            assert "question" in r
            assert "answer" in r

    def test_build_chapters(self):
        from common.bettafish_analyzer import InsightForge

        forge = InsightForge()
        chapters = forge.build_chapters(
            data_result={"narrative": "데이터", "verdict": "중립", "score": 0},
            sentiment_result={"narrative": "심리", "verdict": "중립", "score": 0},
            macro_result={"narrative": "매크로", "verdict": "중립", "score": 0},
            sub_question_results=[],
            context={},
        )
        assert isinstance(chapters, list)
        assert len(chapters) > 0


# ---------------------------------------------------------------------------
# BettaFishAnalyzer integration tests
# ---------------------------------------------------------------------------


class TestBettaFishAnalyzerIntegration:
    def test_analyze_all_none(self):
        from common.bettafish_analyzer import BettaFishAnalyzer

        analyzer = BettaFishAnalyzer()
        report = analyzer.analyze()
        assert report.verdict in ("강세", "약세", "중립", "혼조")
        assert report.confidence in ("low", "medium", "high")
        assert isinstance(report.data_narrative, str)
        assert isinstance(report.sentiment_narrative, str)
        assert isinstance(report.macro_narrative, str)
        assert isinstance(report.synthesis, str)
        assert isinstance(report.risk_factors, list)
        assert isinstance(report.opportunities, list)
        assert isinstance(report.chapters, list)
        assert report.timestamp != ""

    def test_analyze_with_macro_data(self):
        from common.bettafish_analyzer import BettaFishAnalyzer

        macro = {
            "us10y": 4.34,
            "us10y_trend": "falling",
            "dxy": 99.4,
            "dxy_trend": "stable",
            "vix": 25.1,
            "fed_rate": 3.64,
        }
        analyzer = BettaFishAnalyzer()
        report = analyzer.analyze(macro_data=macro)
        assert report.verdict in ("강세", "약세", "중립", "혼조")
        assert len(report.macro_narrative) > 10

    def test_analyze_with_keywords(self):
        from common.bettafish_analyzer import BettaFishAnalyzer

        keywords = [
            {"keyword": "bitcoin", "count": 15, "sentiment": 0.6},
            {"keyword": "regulation", "count": 8, "sentiment": -0.3},
            {"keyword": "ETF", "count": 5, "sentiment": 0.8},
        ]
        analyzer = BettaFishAnalyzer()
        report = analyzer.analyze(keywords=keywords)
        assert len(report.sentiment_narrative) > 10

    def test_generate_report_markdown(self):
        from common.bettafish_analyzer import BettaFishAnalyzer

        analyzer = BettaFishAnalyzer()
        report = analyzer.analyze()
        md = analyzer.generate_report_markdown(report)
        assert isinstance(md, str)
        assert "##" in md  # has markdown headings
        assert report.verdict in md

    def test_generate_brief_outlook(self):
        from common.bettafish_analyzer import BettaFishAnalyzer

        analyzer = BettaFishAnalyzer()
        report = analyzer.analyze()
        outlook = analyzer.generate_brief_outlook(report)
        assert isinstance(outlook, str)
        assert len(outlook) > 0
