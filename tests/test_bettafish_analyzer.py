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

    def test_analyze_vix_spike_scenario(self):
        """VIX 급등 시나리오: 고공포 환경."""
        from common.bettafish_analyzer import BettaFishAnalyzer

        macro = {"vix": 35.0, "us10y": 4.8, "us10y_trend": "rising", "dxy": 106.0}
        analyzer = BettaFishAnalyzer()
        report = analyzer.analyze(macro_data=macro)
        assert report.verdict in ("강세", "약세", "중립", "혼조")
        # High VIX + high rates should produce risk factors
        assert len(report.risk_factors) > 0 or "리스크" in report.synthesis.lower() or "위험" in report.synthesis

    def test_analyze_low_rate_bullish_scenario(self):
        """저금리 환경: 위험자산 우호적."""
        from common.bettafish_analyzer import BettaFishAnalyzer

        macro = {"vix": 12.0, "us10y": 2.5, "us10y_trend": "falling", "dxy": 95.0, "fed_rate": 2.0}
        analyzer = BettaFishAnalyzer()
        report = analyzer.analyze(macro_data=macro)
        assert report.verdict in ("강세", "약세", "중립", "혼조")
        assert len(report.macro_narrative) > 10

    def test_analyze_strong_dollar_scenario(self):
        """강달러 환경: DXY 106+."""
        from common.bettafish_analyzer import BettaFishAnalyzer

        macro = {"dxy": 108.0, "dxy_trend": "rising", "vix": 20.0, "us10y": 4.0}
        analyzer = BettaFishAnalyzer()
        report = analyzer.analyze(macro_data=macro)
        assert report.verdict in ("강세", "약세", "중립", "혼조")

    def test_analyze_full_inputs(self):
        """모든 입력이 있는 풀 분석."""
        from common.bettafish_analyzer import BettaFishAnalyzer

        macro = {"vix": 22.0, "us10y": 3.8, "dxy": 101.0, "fed_rate": 3.5}
        keywords = [
            {"keyword": "bitcoin", "count": 20, "sentiment": 0.5},
            {"keyword": "halving", "count": 8, "sentiment": 0.9},
            {"keyword": "regulation", "count": 12, "sentiment": -0.4},
            {"keyword": "crash", "count": 3, "sentiment": -0.8},
        ]
        analyzer = BettaFishAnalyzer()
        report = analyzer.analyze(keywords=keywords, macro_data=macro)
        assert report.verdict in ("강세", "약세", "중립", "혼조")
        assert report.confidence in ("low", "medium", "high")
        assert len(report.chapters) > 0
        assert len(report.synthesis) > 20

    def test_report_markdown_with_chapters(self):
        """챕터가 있는 리포트의 마크다운 생성."""
        from common.bettafish_analyzer import BettaFishAnalyzer

        macro = {"vix": 25.0, "us10y": 4.2, "dxy": 103.0}
        analyzer = BettaFishAnalyzer()
        report = analyzer.analyze(macro_data=macro)
        md = analyzer.generate_report_markdown(report)
        assert "## 멀티 관점 시장 분석" in md
        assert "종합 의견" in md
        assert "최종 판정" in md
        if report.chapters:
            assert "###" in md

    def test_report_markdown_risk_and_opportunities(self):
        """리스크/기회 요인이 마크다운에 포함되는지 확인."""
        from common.bettafish_analyzer import AnalysisReport, BettaFishAnalyzer

        analyzer = BettaFishAnalyzer()
        report = AnalysisReport(
            data_narrative="데이터 분석",
            sentiment_narrative="심리 분석",
            macro_narrative="매크로 분석",
            synthesis="종합 분석 내용입니다.",
            risk_factors=["고금리 지속", "VIX 급등"],
            opportunities=["AI 섹터 성장", "비트코인 반감기"],
            verdict="혼조",
            confidence="medium",
            chapters=[],
            timestamp="2026-03-26T12:00:00Z",
        )
        md = analyzer.generate_report_markdown(report)
        assert "고금리 지속" in md
        assert "AI 섹터 성장" in md
        assert "리스크 요인" in md
        assert "기회 요인" in md

    def test_brief_outlook_with_risks_and_opps(self):
        """리스크+기회 모두 있을 때 brief outlook 형식."""
        from common.bettafish_analyzer import AnalysisReport, BettaFishAnalyzer

        analyzer = BettaFishAnalyzer()
        report = AnalysisReport(
            data_narrative="",
            sentiment_narrative="",
            macro_narrative="",
            synthesis="시장 혼조세가 지속되고 있습니다.",
            risk_factors=["인플레이션"],
            opportunities=["ETF 승인"],
            verdict="혼조",
            confidence="low",
            chapters=[],
        )
        outlook = analyzer.generate_brief_outlook(report)
        assert "리스크" in outlook
        assert "기회" in outlook

    def test_brief_outlook_risks_only(self):
        """리스크만 있을 때 brief outlook."""
        from common.bettafish_analyzer import AnalysisReport, BettaFishAnalyzer

        analyzer = BettaFishAnalyzer()
        report = AnalysisReport(
            data_narrative="",
            sentiment_narrative="",
            macro_narrative="",
            synthesis="약세 압력이 지속됩니다.",
            risk_factors=["금리 인상", "달러 강세"],
            opportunities=[],
            verdict="약세",
            confidence="high",
            chapters=[],
        )
        outlook = analyzer.generate_brief_outlook(report)
        assert "리스크" in outlook
        assert "기회" not in outlook


# ---------------------------------------------------------------------------
# DataPerspective — real composite_result (non-None path, lines 168-224)
# ---------------------------------------------------------------------------


class TestDataPerspectiveWithCompositeResult:
    """Cover DataPerspective.analyze() when composite_result is not None."""

    def _make_signal(self, name, verdict, normalized):
        from types import SimpleNamespace

        return SimpleNamespace(
            name=name,
            verdict=verdict,
            normalized=normalized,
            raw_display="50",
            trend_arrow="→",
        )

    def _make_composite(self, score, verdict, signals, agreement_count, total_signals, confidence_label="보통"):
        from types import SimpleNamespace

        return SimpleNamespace(
            score=score,
            verdict=verdict,
            signal_results=signals,
            agreement_count=agreement_count,
            total_signals=total_signals,
            confidence_label=confidence_label,
        )

    def test_with_bullish_and_bearish_signals_returns_both(self):
        from common.bettafish_analyzer import DataPerspective

        signals = [
            self._make_signal("RSI", "강세", 0.8),
            self._make_signal("MACD", "약세", 0.3),
            self._make_signal("볼린저밴드", "강세", 0.7),
        ]
        composite = self._make_composite(65, "강세", signals, 2, 3, "높음")
        dp = DataPerspective()
        result = dp.analyze(composite)

        assert result["verdict"] == "강세"
        assert result["score"] == 65
        assert result["strongest_bullish"] == "RSI"
        assert result["strongest_bearish"] == "MACD"
        assert result["agreement_ratio"] == pytest.approx(2 / 3)
        assert "RSI" in result["narrative"]
        assert "MACD" in result["narrative"]

    def test_with_bullish_signals_only(self):
        from common.bettafish_analyzer import DataPerspective

        signals = [self._make_signal("Fear&Greed", "강세", 0.9)]
        composite = self._make_composite(75, "강세", signals, 1, 1, "높음")
        dp = DataPerspective()
        result = dp.analyze(composite)

        assert result["strongest_bullish"] == "Fear&Greed"
        assert result["strongest_bearish"] == ""
        assert len(result["opportunities"]) == 1
        assert len(result["risk_factors"]) == 0

    def test_with_bearish_signals_only(self):
        from common.bettafish_analyzer import DataPerspective

        signals = [self._make_signal("VIX", "약세", 0.2)]
        composite = self._make_composite(30, "약세", signals, 1, 1, "낮음")
        dp = DataPerspective()
        result = dp.analyze(composite)

        assert result["strongest_bullish"] == ""
        assert result["strongest_bearish"] == "VIX"
        assert len(result["risk_factors"]) == 1

    def test_with_zero_total_signals_agreement_ratio_zero(self):
        from common.bettafish_analyzer import DataPerspective

        composite = self._make_composite(50, "중립", [], 0, 0, "낮음")
        dp = DataPerspective()
        result = dp.analyze(composite)

        assert result["agreement_ratio"] == 0.0

    def test_signal_summary_built_from_up_to_three_signals(self):
        """신호 요약 문자열이 최대 3개 신호를 포함하는지 확인."""
        from common.bettafish_analyzer import DataPerspective

        signals = [self._make_signal(f"sig{i}", "강세", 0.5 + i * 0.1) for i in range(5)]
        composite = self._make_composite(70, "강세", signals, 5, 5, "높음")
        dp = DataPerspective()
        result = dp.analyze(composite)
        # narrative must mention sig0 (first signal)
        assert "sig0" in result["narrative"]


# ---------------------------------------------------------------------------
# DataPerspective._build_narrative — both bullish AND bearish branch (line 261)
# ---------------------------------------------------------------------------


class TestBuildNarrativeBothSignals:
    def test_both_bullish_and_bearish_present(self):
        from common.bettafish_analyzer import DataPerspective

        dp = DataPerspective()
        result = dp._build_narrative(
            score=55,
            verdict="혼조",
            total_signals=4,
            agreement_ratio=0.5,
            signal_summary="신호 혼재",
            strongest_bullish="RSI",
            strongest_bearish="VIX",
            confidence_label="보통",
        )
        assert "RSI" in result
        assert "VIX" in result
        assert "괴리" in result

    def test_low_agreement_ratio_low_trust_sentence(self):
        from common.bettafish_analyzer import DataPerspective

        dp = DataPerspective()
        result = dp._build_narrative(
            score=40,
            verdict="약세",
            total_signals=5,
            agreement_ratio=0.3,
            signal_summary="혼재",
            strongest_bullish="",
            strongest_bearish="",
            confidence_label="낮음",
        )
        assert "신뢰도가 낮아" in result

    def test_medium_agreement_ratio_medium_trust_sentence(self):
        from common.bettafish_analyzer import DataPerspective

        dp = DataPerspective()
        result = dp._build_narrative(
            score=55,
            verdict="혼조",
            total_signals=4,
            agreement_ratio=0.6,
            signal_summary="보통",
            strongest_bullish="",
            strongest_bearish="",
            confidence_label="보통",
        )
        assert "추가 지표 모니터링" in result


# ---------------------------------------------------------------------------
# SentimentPerspective — cluster-based paths (lines 341-347, 357-363)
# ---------------------------------------------------------------------------

import pytest  # noqa: E402 — moved here so it is available for approx above


class TestSentimentPerspectiveWithClusters:
    """Cover cluster processing and verdict branches."""

    def _make_cluster(self, topic_name, sentiment_score):
        from types import SimpleNamespace

        return SimpleNamespace(topic_name=topic_name, sentiment_score=sentiment_score)

    def test_bullish_verdict_from_positive_avg_sentiment(self):
        from common.bettafish_analyzer import SentimentPerspective

        clusters = [
            self._make_cluster("BTC 상승", 0.3),
            self._make_cluster("ETH 호재", 0.2),
        ]
        sp = SentimentPerspective()
        result = sp.analyze(clusters, None)
        assert result["verdict"] == "강세"
        assert len(result["positive_topics"]) == 2

    def test_bearish_verdict_from_negative_avg_sentiment(self):
        from common.bettafish_analyzer import SentimentPerspective

        clusters = [
            self._make_cluster("규제 리스크", -0.3),
            self._make_cluster("해킹 사태", -0.2),
        ]
        sp = SentimentPerspective()
        result = sp.analyze(clusters, None)
        assert result["verdict"] == "약세"
        assert len(result["negative_topics"]) == 2

    def test_mixed_verdict_when_near_zero_with_both_topic_types(self):
        """avg_sentiment ≈ 0, positive + negative topics → 혼조.

        The cluster sentiment must exceed the 0.05 threshold to register
        as a positive/negative topic, so we use ±0.1 here.
        avg_sentiment = (0.1 + -0.1) / 2 = 0.0, which is <= 0.05,
        and both topic lists are non-empty → verdict is '혼조'.
        """
        from common.bettafish_analyzer import SentimentPerspective

        clusters = [
            self._make_cluster("긍정 토픽", 0.1),
            self._make_cluster("부정 토픽", -0.1),
        ]
        sp = SentimentPerspective()
        result = sp.analyze(clusters, None)
        assert result["verdict"] == "혼조"

    def test_neutral_verdict_when_no_strong_signal(self):
        """avg_sentiment near zero but no pos/neg topics → 중립."""
        from common.bettafish_analyzer import SentimentPerspective

        clusters = [self._make_cluster("중립 토픽", 0.01)]
        sp = SentimentPerspective()
        result = sp.analyze(clusters, None)
        assert result["verdict"] == "중립"

    def test_bullish_keyword_string_sentiment(self):
        """'bullish' string sentiment keyword classification."""
        from common.bettafish_analyzer import SentimentPerspective

        kws = [
            {"keyword": "반감기", "sentiment": "bullish", "count": 10},
            {"keyword": "ETF승인", "sentiment": "bullish", "count": 8},
        ]
        sp = SentimentPerspective()
        result = sp.analyze(None, kws)
        assert "반감기" in result["dominant_bullish_kws"]

    def test_bearish_keyword_string_sentiment(self):
        """'bearish' string sentiment keyword classification."""
        from common.bettafish_analyzer import SentimentPerspective

        kws = [
            {"keyword": "규제", "sentiment": "bearish", "count": 5},
        ]
        sp = SentimentPerspective()
        result = sp.analyze(None, kws)
        assert "규제" in result["dominant_bearish_kws"]


# ---------------------------------------------------------------------------
# SentimentPerspective._build_narrative branches (lines 416-451)
# ---------------------------------------------------------------------------


class TestSentimentBuildNarrative:
    def test_n_clusters_zero_uses_keyword_only_sentence(self):
        from common.bettafish_analyzer import SentimentPerspective

        sp = SentimentPerspective()
        result = sp._build_narrative(
            n_clusters=0,
            avg_sentiment=0.0,
            verdict="중립",
            positive_topics=[],
            negative_topics=[],
            bullish_kws=["bitcoin"],
            bearish_kws=[],
        )
        assert "키워드 기반" in result

    def test_both_bearish_and_bullish_kws_second_sentence(self):
        from common.bettafish_analyzer import SentimentPerspective

        sp = SentimentPerspective()
        result = sp._build_narrative(
            n_clusters=2,
            avg_sentiment=0.0,
            verdict="혼조",
            positive_topics=["A"],
            negative_topics=["B"],
            bullish_kws=["상승", "ETF"],
            bearish_kws=["규제", "해킹"],
        )
        assert "규제" in result or "해킹" in result
        assert "상승" in result or "ETF" in result

    def test_bearish_kws_only_second_sentence(self):
        from common.bettafish_analyzer import SentimentPerspective

        sp = SentimentPerspective()
        result = sp._build_narrative(
            n_clusters=1,
            avg_sentiment=-0.2,
            verdict="약세",
            positive_topics=[],
            negative_topics=["규제"],
            bullish_kws=[],
            bearish_kws=["SEC", "벌금"],
        )
        assert "SEC" in result or "벌금" in result
        assert "반전" in result or "하방 심리" in result

    def test_bullish_kws_only_second_sentence(self):
        from common.bettafish_analyzer import SentimentPerspective

        sp = SentimentPerspective()
        result = sp._build_narrative(
            n_clusters=1,
            avg_sentiment=0.2,
            verdict="강세",
            positive_topics=["반감기"],
            negative_topics=[],
            bullish_kws=["반감기", "ETF"],
            bearish_kws=[],
        )
        assert "낙관론" in result

    def test_equal_positive_negative_tight_balance_sentence(self):
        """pos_n == neg_n triggers balance sentence."""
        from common.bettafish_analyzer import SentimentPerspective

        sp = SentimentPerspective()
        result = sp._build_narrative(
            n_clusters=2,
            avg_sentiment=0.0,
            verdict="혼조",
            positive_topics=["A"],
            negative_topics=["B"],
            bullish_kws=[],
            bearish_kws=[],
        )
        assert "팽팽하게" in result

    def test_dominant_positive_overwhelming_sentence(self):
        """pos_n > neg_n * 2 triggers dominant-positive sentence."""
        from common.bettafish_analyzer import SentimentPerspective

        sp = SentimentPerspective()
        result = sp._build_narrative(
            n_clusters=4,
            avg_sentiment=0.2,
            verdict="강세",
            positive_topics=["A", "B", "C"],
            negative_topics=["D"],
            bullish_kws=[],
            bearish_kws=[],
        )
        assert "압도적" in result

    def test_dominant_negative_overwhelming_sentence(self):
        """neg_n > pos_n * 2 triggers dominant-negative sentence."""
        from common.bettafish_analyzer import SentimentPerspective

        sp = SentimentPerspective()
        result = sp._build_narrative(
            n_clusters=4,
            avg_sentiment=-0.2,
            verdict="약세",
            positive_topics=["A"],
            negative_topics=["B", "C", "D"],
            bullish_kws=[],
            bearish_kws=[],
        )
        assert "공포 및 불확실성" in result


# ---------------------------------------------------------------------------
# MacroPerspective — empty sub_scores path (line 578) and no display_parts (630)
# ---------------------------------------------------------------------------


class TestMacroPerspectiveEdgeCases:
    def test_empty_macro_dict_uses_default_score(self):
        """매크로 데이터가 빈 dict이면 sub_scores 없이 0.5로 처리."""
        from common.bettafish_analyzer import MacroPerspective

        mp = MacroPerspective()
        result = mp.analyze({})
        # macro_score_norm=0.5 → macro_score_100=0.0 → 중립 or 혼조
        assert result["verdict"] in ("강세", "약세", "중립", "혼조")
        assert result["macro_score"] == pytest.approx(0.0)

    def test_macro_dict_with_only_unknown_keys_hits_empty_sub_scores(self):
        """알 수 없는 키만 있는 dict → sub_scores 비어 있어 line 578 실행."""
        from common.bettafish_analyzer import MacroPerspective

        mp = MacroPerspective()
        # None of the four recognised keys (us10y, dxy, vix, fed_rate) present
        result = mp.analyze({"unknown_key": 99, "another": "value"})
        assert result["macro_score"] == pytest.approx(0.0)
        assert result["verdict"] in ("강세", "약세", "중립", "혼조")

    def test_build_narrative_no_display_parts(self):
        """display_parts 비어있을 때 제한적 평가 문장이 생성된다."""
        from common.bettafish_analyzer import MacroPerspective

        mp = MacroPerspective()
        result = mp._build_narrative(
            display_parts=[],
            verdict="중립",
            tailwinds=[],
            headwinds=[],
            macro_score_norm=0.5,
        )
        assert "제한적" in result

    def test_build_narrative_score_high_favorable_sentence(self):
        """macro_score_norm >= 0.65 → 위험자산 우호 문장."""
        from common.bettafish_analyzer import MacroPerspective

        mp = MacroPerspective()
        result = mp._build_narrative(
            display_parts=["VIX 15.0"],
            verdict="강세",
            tailwinds=["저금리 환경(2.50%) — 위험자산 유동성 우호"],
            headwinds=[],
            macro_score_norm=0.7,
        )
        assert "우호적" in result

    def test_build_narrative_score_low_unfavorable_sentence(self):
        """macro_score_norm <= 0.35 → 비우호 문장."""
        from common.bettafish_analyzer import MacroPerspective

        mp = MacroPerspective()
        result = mp._build_narrative(
            display_parts=["VIX 30.0"],
            verdict="약세",
            tailwinds=[],
            headwinds=["고금리 부담(5.00%) — 위험자산 밸류에이션 압박"],
            macro_score_norm=0.3,
        )
        assert "비우호" in result or "헤지" in result

    def test_build_narrative_tailwinds_only(self):
        """tailwinds만 있고 headwinds 없을 때 테일윈드 문장."""
        from common.bettafish_analyzer import MacroPerspective

        mp = MacroPerspective()
        result = mp._build_narrative(
            display_parts=["10년물 금리 2.50%→"],
            verdict="강세",
            tailwinds=["저금리 환경(2.50%) — 위험자산 유동성 우호"],
            headwinds=[],
            macro_score_norm=0.7,
        )
        assert "테일윈드" in result

    def test_build_narrative_headwinds_only(self):
        """headwinds만 있고 tailwinds 없을 때 역풍 문장."""
        from common.bettafish_analyzer import MacroPerspective

        mp = MacroPerspective()
        result = mp._build_narrative(
            display_parts=["VIX 28.0"],
            verdict="약세",
            tailwinds=[],
            headwinds=["고변동성 공포(VIX 28.0) — 리스크 오프 심화"],
            macro_score_norm=0.3,
        )
        assert "역풍" in result


# ---------------------------------------------------------------------------
# InsightForge._answer_question — all uncovered branches
# ---------------------------------------------------------------------------


class TestInsightForgeAnswerQuestion:
    """Direct unit tests for _answer_question to cover every branch."""

    def _forge(self):
        from common.bettafish_analyzer import InsightForge

        return InsightForge()

    def _ctx(self, **kwargs):
        base = {
            "macro_data": {},
            "data_result": {},
            "sentiment_result": {},
            "macro_result": {},
        }
        base.update(kwargs)
        return base

    # 패닉 매도 — score < 45 but > 25 (line 884)
    def test_panic_sell_fear_but_not_extreme(self):
        forge = self._forge()
        ctx = self._ctx(data_result={"score": 35, "agreement_ratio": 0.5})
        answer, evidence, confidence = forge._answer_question("패닉 매도 징후가 있는가?", ctx)
        assert "아직 패닉 단계 아님" in answer
        assert confidence == "high"

    # 패닉 매도 — score <= 25 (line 887)
    def test_panic_sell_extreme_fear(self):
        forge = self._forge()
        ctx = self._ctx(data_result={"score": 20, "agreement_ratio": 0.5})
        answer, evidence, confidence = forge._answer_question("패닉 매도 징후가 있는가?", ctx)
        assert "극공포" in answer
        assert confidence == "high"

    # 패닉 매도 — score >= 45 (no panic, line 890)
    def test_panic_sell_no_signal_when_score_normal(self):
        forge = self._forge()
        ctx = self._ctx(data_result={"score": 60, "agreement_ratio": 0.5})
        answer, evidence, confidence = forge._answer_question("패닉 매도 징후가 있는가?", ctx)
        assert "패닉 매도 징후 없음" in answer

    # 하방 리스크 — VIX >= 25 and us10y >= 4.75 (lines 901-903)
    def test_downside_risk_vix_and_rate_drivers(self):
        forge = self._forge()
        ctx = self._ctx(
            macro_data={"vix": 30.0, "us10y": 5.0},
            macro_result={"headwinds": ["고금리 부담(5.00%) — 밸류에이션 압박"]},
        )
        answer, evidence, confidence = forge._answer_question("하방 리스크의 핵심 동인은 무엇인가?", ctx)
        assert "VIX" in answer
        assert confidence == "high"

    # 하방 리스크 — no drivers (line 908 else)
    def test_downside_risk_no_clear_driver(self):
        forge = self._forge()
        ctx = self._ctx(macro_data={"vix": 15.0, "us10y": 3.5})
        answer, evidence, confidence = forge._answer_question("하방 리스크의 핵심 동인은 무엇인가?", ctx)
        assert "미확인" in answer

    # 상승 모멘텀 — with strongest_bullish and tailwinds (lines 913-926)
    def test_upward_momentum_with_bullish_signal_and_tailwinds(self):
        forge = self._forge()
        ctx = self._ctx(
            data_result={"strongest_bullish": "RSI", "agreement_ratio": 0.8},
            macro_result={"tailwinds": ["저금리 환경(2.50%) — 유동성 우호", "약달러(95.0) — 선호 환경"]},
        )
        answer, evidence, confidence = forge._answer_question("어떤 지표가 상승 모멘텀을 지지하는가?", ctx)
        assert "RSI" in answer
        assert confidence == "high"

    # 상승 모멘텀 — no supporters (line 924 else)
    def test_upward_momentum_no_support(self):
        forge = self._forge()
        ctx = self._ctx(data_result={"strongest_bullish": "", "agreement_ratio": 0.3})
        answer, evidence, confidence = forge._answer_question("어떤 지표가 상승 모멘텀을 지지하는가?", ctx)
        assert "부족" in answer
        assert confidence == "low"

    # 매크로 압박 — high us10y and macro verdict 약세 (lines 932-938)
    def test_macro_pressure_with_high_rate_and_bearish_verdict(self):
        forge = self._forge()
        ctx = self._ctx(
            macro_data={"us10y": 5.0},
            macro_result={"verdict": "약세", "tailwinds": [], "headwinds": []},
        )
        answer, evidence, confidence = forge._answer_question("매크로 환경이 추가 압박을 줄 가능성은?", ctx)
        assert "압박" in answer

    # 매크로 압박 — no pressures (line 942 else)
    def test_macro_pressure_no_signal(self):
        forge = self._forge()
        ctx = self._ctx(
            macro_data={"us10y": 3.0},
            macro_result={"verdict": "중립", "tailwinds": [], "headwinds": []},
        )
        answer, evidence, confidence = forge._answer_question("매크로 환경이 추가 압박을 줄 가능성은?", ctx)
        assert "제한적" in answer

    # 방향성 지연 — agreement_ratio < 0.5 + mixed kws (line 953)
    def test_direction_delay_low_agreement_with_mixed_kws(self):
        forge = self._forge()
        ctx = self._ctx(
            data_result={"agreement_ratio": 0.3},
            sentiment_result={
                "dominant_bearish_kws": ["규제"],
                "dominant_bullish_kws": ["반감기"],
            },
        )
        answer, evidence, confidence = forge._answer_question("방향성 결정을 지연시키는 요인은?", ctx)
        assert "방향성 결정 지연" in answer

    # 방향성 지연 — no delays (line 954 else)
    def test_direction_delay_no_delay_factors(self):
        forge = self._forge()
        ctx = self._ctx(data_result={"agreement_ratio": 0.8})
        answer, evidence, confidence = forge._answer_question("방향성 결정을 지연시키는 요인은?", ctx)
        assert "불명확" in answer

    # 촉매 — with negative topics and strongest_bearish (lines 961-966)
    def test_catalyst_with_negative_topics_and_bearish_signal(self):
        forge = self._forge()
        ctx = self._ctx(
            sentiment_result={"negative_topics": ["SEC 규제"], "dominant_bullish_kws": []},
            data_result={"strongest_bearish": "VIX", "agreement_ratio": 0.5},
        )
        answer, evidence, confidence = forge._answer_question("다음 촉매(catalyst)는 무엇인가?", ctx)
        assert "촉매 후보" in answer
        assert confidence == "low"

    # 촉매 — no catalysts
    def test_catalyst_none_found(self):
        forge = self._forge()
        ctx = self._ctx(
            sentiment_result={"negative_topics": [], "dominant_bullish_kws": []},
            data_result={"strongest_bearish": "", "agreement_ratio": 0.5},
        )
        answer, evidence, confidence = forge._answer_question("다음 촉매(catalyst)는 무엇인가?", ctx)
        assert "미확인" in answer

    # 변동성 — VIX >= 25 (line 976)
    def test_volatility_high_vix(self):
        forge = self._forge()
        ctx = self._ctx(macro_data={"vix": 28.0})
        answer, evidence, confidence = forge._answer_question("변동성 확대 가능성은?", ctx)
        assert "고변동성" in answer
        assert confidence == "high"

    # 변동성 — VIX between calm and fear (line 979)
    def test_volatility_medium_vix(self):
        forge = self._forge()
        ctx = self._ctx(macro_data={"vix": 21.0})
        answer, evidence, confidence = forge._answer_question("변동성 확대 가능성은?", ctx)
        assert "중간 구간" in answer
        assert confidence == "medium"

    # 변동성 — VIX low (line 982)
    def test_volatility_low_vix(self):
        forge = self._forge()
        ctx = self._ctx(macro_data={"vix": 12.0})
        answer, evidence, confidence = forge._answer_question("변동성 확대 가능성은?", ctx)
        assert "안정 구간" in answer
        assert confidence == "high"

    # 변동성 — no VIX (line 985)
    def test_volatility_no_vix_data(self):
        forge = self._forge()
        ctx = self._ctx(macro_data={})
        answer, evidence, confidence = forge._answer_question("변동성 확대 가능성은?", ctx)
        assert "VIX 데이터 없음" in answer
        assert confidence == "low"

    # VIX 관련 — with vix (line 993)
    def test_vix_question_with_data(self):
        forge = self._forge()
        ctx = self._ctx(macro_data={"vix": 30.0})
        answer, evidence, confidence = forge._answer_question("VIX 급등이 위험자산 전반에 미치는 영향은?", ctx)
        assert "VIX" in answer
        assert confidence == "high"

    # VIX 관련 — below fear threshold (line 993 else branch)
    def test_vix_question_low_vix(self):
        forge = self._forge()
        ctx = self._ctx(macro_data={"vix": 15.0})
        answer, evidence, confidence = forge._answer_question("VIX 급등이 위험자산 전반에 미치는 영향은?", ctx)
        assert "주의" in answer

    # VIX 관련 — no vix (line 996)
    def test_vix_question_no_data(self):
        forge = self._forge()
        ctx = self._ctx(macro_data={})
        answer, evidence, confidence = forge._answer_question("VIX 급등이 위험자산 전반에 미치는 영향은?", ctx)
        assert "미제공" in answer
        assert confidence == "low"

    # 기본 답변 fallback (line 1001)
    def test_fallback_answer_for_unmatched_question(self):
        forge = self._forge()
        ctx = self._ctx()
        answer, evidence, confidence = forge._answer_question("완전히 매칭되지 않는 임의 질문입니다.", ctx)
        assert "직접 답변이 어렵습니다" in answer
        assert confidence == "low"


# ---------------------------------------------------------------------------
# InsightForge evidence extraction helpers (lines 1020-1062)
# ---------------------------------------------------------------------------


class TestInsightForgeEvidenceExtraction:
    def _forge(self):
        from common.bettafish_analyzer import InsightForge

        return InsightForge()

    def test_extract_data_evidence_with_all_fields(self):
        # evidence is capped at 4 items: score, agreement, bullish, bearish
        # VIX would be the 5th item and gets truncated — verify the first four
        data_result = {
            "score": 72,
            "verdict": "강세",
            "agreement_ratio": 0.8,
            "strongest_bullish": "RSI",
            "strongest_bearish": "볼린저밴드",
        }
        macro_data = {"vix": 30.0}
        forge = self._forge()
        evidence = forge._extract_data_evidence(data_result, macro_data)
        assert any("72" in e for e in evidence)
        assert any("RSI" in e for e in evidence)
        assert any("볼린저밴드" in e for e in evidence)
        assert len(evidence) == 4  # capped at 4

    def test_extract_data_evidence_vix_calm_label(self):
        """VIX <= 18 → '안정' label."""
        forge = self._forge()
        evidence = forge._extract_data_evidence(
            {"score": 60, "verdict": "강세", "agreement_ratio": 0.7},
            {"vix": 14.0},
        )
        assert any("안정" in e for e in evidence)

    def test_extract_data_evidence_vix_caution_label(self):
        """18 < VIX < 25 → '주의' label."""
        forge = self._forge()
        evidence = forge._extract_data_evidence(
            {"score": 50, "verdict": "중립", "agreement_ratio": 0.5},
            {"vix": 21.0},
        )
        assert any("주의" in e for e in evidence)

    def test_extract_data_evidence_no_macro_data(self):
        """macro_data=None does not add VIX evidence."""
        forge = self._forge()
        evidence = forge._extract_data_evidence(
            {"score": 50, "verdict": "중립", "agreement_ratio": 0.5},
            None,
        )
        assert not any("VIX" in e for e in evidence)

    def test_extract_sentiment_evidence_all_fields(self):
        # evidence is capped at 4: score+verdict, negative_topics, positive_topics, bearish_kws
        # bullish_kws would be the 5th item and gets truncated
        sentiment_result = {
            "sentiment_score": -0.25,
            "verdict": "약세",
            "negative_topics": ["규제", "해킹"],
            "positive_topics": ["반감기"],
            "dominant_bearish_kws": ["SEC", "ban"],
            "dominant_bullish_kws": ["ETF"],
        }
        forge = self._forge()
        evidence = forge._extract_sentiment_evidence(sentiment_result)
        assert any("규제" in e for e in evidence)
        assert any("반감기" in e for e in evidence)
        assert any("SEC" in e for e in evidence)
        assert len(evidence) == 4  # capped at 4; bullish_kws is the truncated 5th

    def test_extract_macro_evidence_all_fields(self):
        macro_result = {"headwinds": ["고금리 부담(5.00%) — 밸류에이션 압박"]}
        macro_data = {
            "us10y": 4.8,
            "us10y_trend": "rising",
            "dxy": 106.0,
            "dxy_trend": "falling",
            "vix": 28.0,
            "fed_rate": 5.25,
        }
        forge = self._forge()
        evidence = forge._extract_macro_evidence(macro_result, macro_data)
        assert any("4.80" in e for e in evidence)
        assert any("106.0" in e for e in evidence)
        assert any("28.0" in e for e in evidence)
        assert any("5.25" in e for e in evidence)

    def test_extract_macro_evidence_no_macro_data(self):
        """macro_data=None → only headwind evidence."""
        forge = self._forge()
        evidence = forge._extract_macro_evidence(
            {"headwinds": ["고금리 부담(5.00%) — 압박"]},
            None,
        )
        assert any("헤드윈드" in e for e in evidence)

    def test_extract_macro_evidence_no_headwinds(self):
        """headwinds empty → no headwind line."""
        forge = self._forge()
        evidence = forge._extract_macro_evidence({"headwinds": []}, None)
        assert not any("헤드윈드" in e for e in evidence)


# ---------------------------------------------------------------------------
# ForumSynthesis — neutral/혼조 agree_count path (line 1160-1163)
# ---------------------------------------------------------------------------


class TestForumSynthesisAgreementPaths:
    def _make_result(self, verdict, macro_score=0.0):
        return {
            "verdict": verdict,
            "macro_score": macro_score,
            "risk_factors": [],
            "opportunities": [],
        }

    def test_neutral_final_verdict_uses_neutral_혼조_agree_count(self):
        """Final verdict 중립 → agree_count counts 중립+혼조 perspectives."""
        from common.bettafish_analyzer import ForumSynthesis

        forum = ForumSynthesis()
        result = forum.synthesize(
            self._make_result("중립"),
            self._make_result("혼조"),
            self._make_result("중립", 0.0),
        )
        # All three are neutral-family → high confidence expected
        assert result["confidence"] in ("high", "medium")
        assert result["verdict"] in ("중립", "혼조")

    def test_bullish_final_verdict_uses_directional_agree_count(self):
        """Final verdict 강세 → line 1160: agree_count counts perspectives == '강세'."""
        from common.bettafish_analyzer import ForumSynthesis

        forum = ForumSynthesis()
        # All three perspectives bullish → weighted sum >> 0.4 → final = 강세
        result = forum.synthesize(
            self._make_result("강세", macro_score=1.0),
            self._make_result("강세", macro_score=1.0),
            self._make_result("강세", macro_score=1.0),
        )
        assert result["verdict"] == "강세"
        assert result["confidence"] == "high"  # all three agree

    def test_describe_agreement_all_same(self):
        from common.bettafish_analyzer import ForumSynthesis

        forum = ForumSynthesis()
        desc = forum._describe_agreement("강세", "강세", "강세", "강세")
        assert "완전 합의" in desc

    def test_describe_agreement_two_unique_values(self):
        from common.bettafish_analyzer import ForumSynthesis

        forum = ForumSynthesis()
        desc = forum._describe_agreement("강세", "강세", "약세", "강세")
        assert "부분 합의" in desc

    def test_describe_agreement_all_different(self):
        from common.bettafish_analyzer import ForumSynthesis

        forum = ForumSynthesis()
        desc = forum._describe_agreement("강세", "약세", "중립", "혼조")
        assert "완전 분산" in desc


# ---------------------------------------------------------------------------
# ForumSynthesis._build_synthesis verdict branches (lines 1271-1284)
# ---------------------------------------------------------------------------


class TestForumSynthesisBuildSynthesis:
    def _forum(self):
        from common.bettafish_analyzer import ForumSynthesis

        return ForumSynthesis()

    def _call(self, final_verdict, risk_factors=None, opportunities=None):
        return self._forum()._build_synthesis(
            data_verdict="중립",
            sent_verdict="중립",
            macro_verdict="중립",
            final_verdict=final_verdict,
            perspective_agreement="세 관점 모두 중립으로 완전 합의",
            confidence="medium",
            risk_factors=risk_factors or [],
            opportunities=opportunities or [],
        )

    def test_bearish_final_verdict_sentence(self):
        result = self._call("약세")
        assert "비중 축소" in result or "현금 비율" in result

    def test_mixed_final_verdict_sentence(self):
        result = self._call("혼조")
        assert "혼조" in result

    def test_neutral_final_verdict_sentence(self):
        result = self._call("중립")
        assert "중립 구간" in result or "분할 매수" in result

    def test_risks_only_no_opportunities(self):
        result = self._call("약세", risk_factors=["VIX 급등"], opportunities=[])
        assert "VIX 급등" in result
        assert "방어적" in result

    def test_opportunities_only_no_risks(self):
        result = self._call("강세", risk_factors=[], opportunities=["ETF 승인"])
        assert "ETF 승인" in result


# ---------------------------------------------------------------------------
# BettaFishAnalyzer — cited_evidence empty path (line 1436)
# ---------------------------------------------------------------------------


class TestBettaFishAnalyzerCitedEvidence:
    def test_empty_cited_evidence_does_not_append_to_synthesis(self):
        """When _cite_evidence returns '', synthesis is not extended."""
        from unittest.mock import patch

        from common.bettafish_analyzer import BettaFishAnalyzer

        analyzer = BettaFishAnalyzer()
        with patch.object(analyzer._forum, "_cite_evidence", return_value=""):
            report = analyzer.analyze()
        # synthesis should not have a double-newline separator
        assert "\n\n" not in report.synthesis


# ---------------------------------------------------------------------------
# generate_brief_outlook — opportunities-only path (lines 1580-1581)
# ---------------------------------------------------------------------------


class TestBriefOutlookOpportunitiesOnly:
    def test_opportunities_only_no_risks(self):
        from common.bettafish_analyzer import AnalysisReport, BettaFishAnalyzer

        analyzer = BettaFishAnalyzer()
        report = AnalysisReport(
            data_narrative="",
            sentiment_narrative="",
            macro_narrative="",
            synthesis="강세 기회가 포착됩니다.",
            risk_factors=[],
            opportunities=["비트코인 반감기", "ETF 승인"],
            verdict="강세",
            confidence="medium",
            chapters=[],
        )
        outlook = analyzer.generate_brief_outlook(report)
        assert "기회" in outlook
        assert "리스크" not in outlook


# ---------------------------------------------------------------------------
# Module-level convenience functions (lines 1610, 1620, 1625)
# ---------------------------------------------------------------------------


class TestModuleLevelFunctions:
    def test_analyze_convenience_function_returns_report(self):
        from common.bettafish_analyzer import AnalysisReport
        from common.bettafish_analyzer import analyze as bfa_analyze

        report = bfa_analyze()
        assert isinstance(report, AnalysisReport)
        assert report.verdict in ("강세", "약세", "중립", "혼조")

    def test_generate_report_markdown_convenience_function(self):
        from common.bettafish_analyzer import AnalysisReport, generate_report_markdown

        report = AnalysisReport(
            data_narrative="데이터",
            sentiment_narrative="심리",
            macro_narrative="매크로",
            synthesis="종합",
            risk_factors=[],
            opportunities=[],
            verdict="중립",
            confidence="low",
            chapters=[],
        )
        md = generate_report_markdown(report)
        assert "멀티 관점" in md

    def test_generate_brief_outlook_convenience_function(self):
        from common.bettafish_analyzer import AnalysisReport, generate_brief_outlook

        report = AnalysisReport(
            data_narrative="",
            sentiment_narrative="",
            macro_narrative="",
            synthesis="시장 중립입니다.",
            risk_factors=[],
            opportunities=[],
            verdict="중립",
            confidence="low",
            chapters=[],
        )
        outlook = generate_brief_outlook(report)
        assert "시장 판정" in outlook


# ---------------------------------------------------------------------------
# generate_report_markdown — no-chapters fallback path (lines 1511-1520)
# ---------------------------------------------------------------------------


class TestReportMarkdownFallback:
    def test_no_chapters_uses_fallback_rendering(self):
        """chapters=[] triggers the else branch with raw narrative sections."""
        from common.bettafish_analyzer import AnalysisReport, BettaFishAnalyzer

        analyzer = BettaFishAnalyzer()
        report = AnalysisReport(
            data_narrative="데이터 분석 내용",
            sentiment_narrative="심리 분석 내용",
            macro_narrative="매크로 분석 내용",
            synthesis="종합 분석 내용",
            risk_factors=[],
            opportunities=[],
            verdict="중립",
            confidence="medium",
            chapters=[],
        )
        md = analyzer.generate_report_markdown(report)
        assert "데이터 분석 (InsightAgent)" in md
        assert "심리 분석 (SentimentAgent)" in md
        assert "매크로 분석 (MacroAgent)" in md

    def test_report_markdown_chapter_with_sub_questions(self):
        """챕터에 sub_questions 있을 때 핵심 질문 분석 섹션이 포함된다."""
        from common.bettafish_analyzer import AnalysisReport, BettaFishAnalyzer, ReportChapter

        analyzer = BettaFishAnalyzer()
        chapter = ReportChapter(
            title="데이터 분석 (InsightAgent)",
            content="데이터 내용",
            evidence=["복합 신호 점수 70/100 — 강세"],
            sub_questions=["어떤 지표가 상승 모멘텀을 지지하는가?"],
            verdict="강세",
        )
        report = AnalysisReport(
            data_narrative="",
            sentiment_narrative="",
            macro_narrative="",
            synthesis="강세 종합",
            risk_factors=[],
            opportunities=[],
            verdict="강세",
            confidence="high",
            chapters=[chapter],
        )
        md = analyzer.generate_report_markdown(report)
        assert "핵심 질문 분석" in md
        assert "어떤 지표가 상승 모멘텀을 지지하는가?" in md


# ---------------------------------------------------------------------------
# InsightForge._cite_evidence — with chapters and high-confidence insights
# ---------------------------------------------------------------------------


class TestCiteEvidence:
    def _forge_synthesis(self):
        from common.bettafish_analyzer import ForumSynthesis

        return ForumSynthesis()

    def test_cite_evidence_with_chapters_and_high_conf_insights(self):
        from common.bettafish_analyzer import ReportChapter

        forum = self._forge_synthesis()
        chapter = ReportChapter(
            title="데이터 분석 (InsightAgent)",
            content="내용",
            evidence=["복합 신호 점수 70/100 — 강세"],
            sub_questions=[],
            verdict="강세",
        )
        insights = [
            {"question": "패닉 매도 징후가 있는가?", "answer": "없음", "confidence": "high"},
            {"question": "변동성 확대 가능성은?", "answer": "낮음", "confidence": "high"},
        ]
        result = forum._cite_evidence(
            narratives={"data": "데이터", "sentiment": "심리", "macro": "매크로"},
            insights=insights,
            chapters=[chapter],
        )
        assert "복합 신호 점수" in result
        assert "패닉 매도" in result
        assert "**핵심 분석 결과:**" in result

    def test_cite_evidence_chapter_without_evidence_skipped(self):
        from common.bettafish_analyzer import ReportChapter

        forum = self._forge_synthesis()
        chapter = ReportChapter(
            title="데이터 분석 (InsightAgent)",
            content="내용",
            evidence=[],  # empty — should be skipped
            sub_questions=[],
            verdict="중립",
        )
        result = forum._cite_evidence(
            narratives={},
            insights=[],
            chapters=[chapter],
        )
        assert result == ""
