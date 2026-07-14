"""BettaFish 멀티 관점 시장 분석 엔진.

MiroFish의 BettaFish 시스템에서 영감을 받아, 세 가지 분석 관점
(데이터/심리/매크로)을 병렬로 분석한 뒤 ForumSynthesis로 종합하는
규칙 기반(rule-based) 엔진이다. 외부 API 호출이나 ML 라이브러리 없이
순수 Python으로 동작한다.

주요 클래스:
    - BettaFishAnalyzer: 메인 분석 클래스
    - DataPerspective: 정량 데이터 분석 (InsightAgent 역할)
    - SentimentPerspective: 뉴스 심리 분석 (MediaAgent 역할)
    - MacroPerspective: 매크로 환경 분석 (QueryAgent 역할)
    - ForumSynthesis: 전체 관점 종합 (ForumEngine 역할)
    - InsightForge: 하위 질문 분해 기반 다차원 분석 (MiroFish 패턴)
    - ReportChapter: 챕터별 증거 인용 구조체
    - AnalysisReport: 최종 분석 보고서 데이터 클래스
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .bettafish_insight import InsightForge  # noqa: F401  (re-exported for backward compat)
from .bettafish_models import (  # noqa: F401  (re-exported for backward compat)
    AnalysisReport,
    ReportChapter,
    _confidence_from_agreement,
    _format_list_inline,
    _score_to_verdict,
    _verdict_to_score,
)
from .bettafish_perspectives import (  # noqa: F401  (re-exported for backward compat)
    DataPerspective,
    MacroPerspective,
    SentimentPerspective,
)
from .bettafish_synthesis import ForumSynthesis  # noqa: F401  (re-exported for backward compat)
from .config import setup_logging

logger = setup_logging("bettafish_analyzer")


# ── 메인 엔진 ─────────────────────────────────────────────────────────────────


class BettaFishAnalyzer:
    """세 가지 분석 관점을 조율하고 최종 보고서를 생성하는 멀티 관점 분석 엔진.

    BettaFish 시스템의 QueryAgent(MacroPerspective), InsightAgent(DataPerspective),
    MediaAgent(SentimentPerspective), ForumEngine(ForumSynthesis)에 해당하는
    컴포넌트를 내부적으로 보유하며, analyze() 단일 진입점으로 사용한다.

    사용 예시::

        from common.bettafish_analyzer import BettaFishAnalyzer
        from common.signal_composer import SignalComposer
        from common.mindspider import MindSpider

        composer = SignalComposer()
        composite = composer.compose_signals({...})

        spider = MindSpider()
        clusters = spider.cluster_topics(news_items)
        keywords = spider.extract_keywords(news_items)

        analyzer = BettaFishAnalyzer()
        report = analyzer.analyze(
            composite_result=composite,
            topic_clusters=clusters,
            keywords=keywords,
            macro_data={"us10y": 4.25, "dxy": 104.5, "vix": 22.5, "fed_rate": 5.25},
        )
        print(analyzer.generate_report_markdown(report))
        print(analyzer.generate_brief_outlook(report))
    """

    def __init__(self) -> None:
        self._data_perspective = DataPerspective()
        self._sentiment_perspective = SentimentPerspective()
        self._macro_perspective = MacroPerspective()
        self._forum = ForumSynthesis()
        self._insight_forge = InsightForge()

    def analyze(
        self,
        composite_result: Any | None = None,
        topic_clusters: list[Any] | None = None,
        keywords: list[dict] | None = None,
        macro_data: dict[str, Any] | None = None,
    ) -> AnalysisReport:
        """세 관점을 병렬로 분석하고 ForumSynthesis로 종합해 최종 보고서를 반환한다.

        Args:
            composite_result: signal_composer.CompositeResult. None 허용.
            topic_clusters: mindspider.TopicCluster 목록. None 허용.
            keywords: mindspider.extract_keywords() 결과 딕셔너리 목록. None 허용.
            macro_data: 매크로 지표 딕셔너리 (us10y, dxy, vix, fed_rate 등). None 허용.

        Returns:
            AnalysisReport: 완성된 분석 보고서.
        """
        logger.info(
            "BettaFishAnalyzer 분석 시작 — composite=%s, clusters=%s, keywords=%s, macro=%s",
            composite_result is not None,
            len(topic_clusters) if topic_clusters else 0,
            len(keywords) if keywords else 0,
            list(macro_data.keys()) if macro_data else [],
        )

        # 세 관점 독립 분석
        data_result = self._data_perspective.analyze(composite_result)
        sentiment_result = self._sentiment_perspective.analyze(topic_clusters, keywords)
        macro_result = self._macro_perspective.analyze(macro_data)

        # 종합
        forum_result = self._forum.synthesize(data_result, sentiment_result, macro_result)

        # InsightForge: 하위 질문 분해 + 다차원 분석
        final_verdict = forum_result["verdict"]
        insight_context: dict[str, Any] = {
            "macro_data": macro_data,
            "data_result": data_result,
            "sentiment_result": sentiment_result,
            "macro_result": macro_result,
        }
        sub_questions = self._insight_forge.decompose(final_verdict, insight_context)
        sub_question_results = self._insight_forge.analyze_sub_questions(sub_questions, insight_context)
        chapters = self._insight_forge.build_chapters(
            data_result=data_result,
            sentiment_result=sentiment_result,
            macro_result=macro_result,
            sub_question_results=sub_question_results,
            context=insight_context,
        )

        # 증거 인용 기반 종합 강화
        cited_evidence = self._forum._cite_evidence(
            narratives={
                "data": data_result["narrative"],
                "sentiment": sentiment_result["narrative"],
                "macro": macro_result["narrative"],
            },
            insights=sub_question_results,
            chapters=chapters,
        )
        if cited_evidence:
            enhanced_synthesis = forum_result["synthesis"] + "\n\n" + cited_evidence
        else:
            enhanced_synthesis = forum_result["synthesis"]

        logger.info(
            "InsightForge 완료: 하위질문=%d개, 챕터=%d개",
            len(sub_questions),
            len(chapters),
        )

        # 타임스탬프
        timestamp = datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

        report = AnalysisReport(
            data_narrative=data_result["narrative"],
            sentiment_narrative=sentiment_result["narrative"],
            macro_narrative=macro_result["narrative"],
            synthesis=enhanced_synthesis,
            risk_factors=forum_result["risk_factors"],
            opportunities=forum_result["opportunities"],
            verdict=forum_result["verdict"],
            confidence=forum_result["confidence"],
            key_levels={},
            chapters=chapters,
            timestamp=timestamp,
        )

        logger.info(
            "BettaFishAnalyzer 완료: verdict=%s, confidence=%s",
            report.verdict,
            report.confidence,
        )
        return report

    def generate_report_markdown(self, report: AnalysisReport) -> str:
        """AnalysisReport를 Jekyll 포스트 삽입용 전체 마크다운 섹션으로 변환한다.

        Args:
            report: analyze()의 반환값.

        Returns:
            str: 마크다운 형식의 멀티 관점 분석 섹션.
        """
        confidence_kr = {"high": "높음", "medium": "보통", "low": "낮음"}.get(report.confidence, "낮음")
        verdict_icon = {
            "강세": "📈",
            "약세": "📉",
            "중립": "➡️",
            "혼조": "↔️",
        }.get(report.verdict, "📊")

        lines: list[str] = []

        lines.append("## 멀티 관점 시장 분석")
        lines.append("")

        # 챕터 기반 렌더링 (InsightForge 결과 포함)
        if report.chapters:
            for chapter in report.chapters:
                lines.append(f"### {chapter.title}")
                lines.append(chapter.content)
                lines.append("")

                # 챕터별 핵심 증거 blockquote 인용
                if chapter.evidence:
                    for ev in chapter.evidence[:2]:
                        lines.append(f'> "{ev}"')
                    lines.append("")

                # 챕터별 하위 질문 없으면 생략
                if chapter.sub_questions:
                    lines.append("**핵심 질문 분석:**")
                    # sub_questions에 매칭되는 답변을 synthesis에서 탐색
                    for i, sq in enumerate(chapter.sub_questions, 1):
                        lines.append(f"{i}. **{sq}** → *(InsightForge 분석 참조)*")
                    lines.append("")
        else:
            # 폴백: 기존 방식
            lines.append("### 데이터 분석 (InsightAgent)")
            lines.append(report.data_narrative)
            lines.append("")

            lines.append("### 심리 분석 (SentimentAgent)")
            lines.append(report.sentiment_narrative)
            lines.append("")

            lines.append("### 매크로 분석 (MacroAgent)")
            lines.append(report.macro_narrative)
            lines.append("")

        # 종합 의견 섹션 (증거 인용 포함)
        lines.append("### 종합 의견 (ForumSynthesis)")
        lines.append(report.synthesis)
        lines.append("")

        # 리스크 / 기회
        if report.risk_factors:
            risk_str = _format_list_inline(report.risk_factors, ", ")
            lines.append(f"**리스크 요인**: {risk_str}")

        if report.opportunities:
            opp_str = _format_list_inline(report.opportunities, ", ")
            lines.append(f"**기회 요인**: {opp_str}")

        lines.append("")

        # 최종 판정 배지
        lines.append(f"> {verdict_icon} **최종 판정**: {report.verdict} (신뢰도: {confidence_kr}) — {report.timestamp}")
        lines.append("")
        lines.append(
            "> 📊 본 분석은 MindSpider 토픽 추출 + BettaFish 멀티 관점 엔진 + InsightForge 하위 질문 분해 기반 자동 생성입니다."
        )

        return "\n".join(lines)

    def generate_brief_outlook(self, report: AnalysisReport) -> str:
        """AnalysisReport를 2-3줄 요약 문자열로 변환한다.

        Args:
            report: analyze()의 반환값.

        Returns:
            str: 컴팩트 포스트용 짧은 분석 요약.
        """
        confidence_kr = {"high": "높음", "medium": "보통", "low": "낮음"}.get(report.confidence, "낮음")
        verdict_icon = {
            "강세": "📈",
            "약세": "📉",
            "중립": "➡️",
            "혼조": "↔️",
        }.get(report.verdict, "📊")

        parts: list[str] = []

        # 최종 판정 한 줄
        parts.append(f"{verdict_icon} **시장 판정**: {report.verdict} (신뢰도 {confidence_kr})")

        # 핵심 리스크/기회 한 줄
        if report.risk_factors and report.opportunities:
            risk_str = _format_list_inline(report.risk_factors[:2], " · ")
            opp_str = _format_list_inline(report.opportunities[:2], " · ")
            parts.append(f"⚠️ 리스크: {risk_str} | ✅ 기회: {opp_str}")
        elif report.risk_factors:
            risk_str = _format_list_inline(report.risk_factors[:3], " · ")
            parts.append(f"⚠️ 주요 리스크: {risk_str}")
        elif report.opportunities:
            opp_str = _format_list_inline(report.opportunities[:3], " · ")
            parts.append(f"✅ 주요 기회: {opp_str}")

        # 종합 서사 첫 문장 발췌
        synthesis_first = report.synthesis.split(". ")[0] + "."
        parts.append(synthesis_first)

        return "\n".join(parts)


# ── 편의 함수 ─────────────────────────────────────────────────────────────────


def analyze(
    composite_result: Any | None = None,
    topic_clusters: list[Any] | None = None,
    keywords: list[dict] | None = None,
    macro_data: dict[str, Any] | None = None,
) -> AnalysisReport:
    """BettaFishAnalyzer를 인스턴스화 없이 사용하는 편의 함수.

    Args:
        composite_result: signal_composer.CompositeResult. None 허용.
        topic_clusters: mindspider.TopicCluster 목록. None 허용.
        keywords: mindspider.extract_keywords() 결과. None 허용.
        macro_data: 매크로 지표 딕셔너리. None 허용.

    Returns:
        AnalysisReport
    """
    return BettaFishAnalyzer().analyze(
        composite_result=composite_result,
        topic_clusters=topic_clusters,
        keywords=keywords,
        macro_data=macro_data,
    )


def generate_report_markdown(report: AnalysisReport) -> str:
    """AnalysisReport → 마크다운 편의 함수."""
    return BettaFishAnalyzer().generate_report_markdown(report)


def generate_brief_outlook(report: AnalysisReport) -> str:
    """AnalysisReport → 요약 편의 함수."""
    return BettaFishAnalyzer().generate_brief_outlook(report)
