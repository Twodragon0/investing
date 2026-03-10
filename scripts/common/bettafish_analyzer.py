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
    - AnalysisReport: 최종 분석 보고서 데이터 클래스
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .config import setup_logging

logger = setup_logging("bettafish_analyzer")


# ── 데이터 클래스 ─────────────────────────────────────────────────────────────


@dataclass
class AnalysisReport:
    """BettaFishAnalyzer.analyze()의 최종 반환 객체."""

    data_narrative: str
    """데이터 관점 분석 (2-3문장)."""

    sentiment_narrative: str
    """심리 관점 분석 (2-3문장)."""

    macro_narrative: str
    """매크로 관점 분석 (2-3문장)."""

    synthesis: str
    """종합 분석 (3-4문장)."""

    risk_factors: list[str]
    """주요 리스크 요인 목록."""

    opportunities: list[str]
    """기회 요인 목록."""

    verdict: str
    """최종 판정: '강세' | '약세' | '중립' | '혼조'."""

    confidence: str
    """신뢰도: 'low' | 'medium' | 'high'."""

    key_levels: dict[str, Any] = field(default_factory=dict)
    """주요 가격 수준 (optional, 예: {'support': 42000, 'resistance': 48000})."""

    timestamp: str = ""
    """분석 시점 (ISO 8601)."""


# ── 내부 헬퍼 ─────────────────────────────────────────────────────────────────


def _verdict_to_score(verdict: str) -> float:
    """버딕트를 -1.0 ~ 1.0 수치 점수로 변환한다."""
    mapping = {"강세": 1.0, "약세": -1.0, "중립": 0.0, "혼조": 0.0}
    return mapping.get(verdict, 0.0)


def _score_to_verdict(score: float) -> str:
    """수치 점수(-1.0 ~ 1.0)를 버딕트 문자열로 변환한다."""
    if score >= 0.4:
        return "강세"
    if score <= -0.4:
        return "약세"
    if abs(score) < 0.15:
        return "중립"
    return "혼조"


def _confidence_from_agreement(agree_count: int, total: int) -> str:
    """일치 개수 / 전체 관점 수로 신뢰도를 결정한다."""
    if total == 0:
        return "low"
    ratio = agree_count / total
    if ratio >= 0.75:
        return "high"
    if ratio >= 0.5:
        return "medium"
    return "low"


def _format_list_inline(items: list[str], sep: str = ", ") -> str:
    """리스트를 구분자로 이어붙인 문자열로 반환한다. 빈 경우 '없음' 반환."""
    return sep.join(items) if items else "없음"


# ── 데이터 관점 (InsightAgent) ────────────────────────────────────────────────


class DataPerspective:
    """정량 신호 데이터를 분석해 서사(narrative)를 생성하는 관점 모듈.

    SignalComposer의 CompositeResult를 입력받아:
    - 신호 일치/불일치 패턴 분석
    - 가장 강한 강세/약세 신호 식별
    - 데이터 기반 서사 문단 생성
    """

    def analyze(self, composite_result: Any | None) -> dict[str, Any]:
        """CompositeResult를 분석해 데이터 관점 결과를 반환한다.

        Args:
            composite_result: signal_composer.CompositeResult 인스턴스.
                None이면 기본값(중립)을 반환한다.

        Returns:
            dict: narrative(str), verdict(str), score(float),
                  strongest_bullish(str), strongest_bearish(str),
                  agreement_ratio(float) 포함.
        """
        if composite_result is None:
            logger.warning("DataPerspective: composite_result 없음 → 기본값 반환")
            return {
                "narrative": "데이터 신호가 제공되지 않아 정량 분석을 수행할 수 없습니다. 시장 중립 상태로 가정합니다.",
                "verdict": "중립",
                "score": 0.0,
                "strongest_bullish": "",
                "strongest_bearish": "",
                "agreement_ratio": 0.0,
                "risk_factors": [],
                "opportunities": [],
            }

        score = getattr(composite_result, "score", 50.0)
        verdict = getattr(composite_result, "verdict", "중립")
        signal_results = getattr(composite_result, "signal_results", [])
        agreement_count = getattr(composite_result, "agreement_count", 0)
        total_signals = getattr(composite_result, "total_signals", 0)
        confidence_label = getattr(composite_result, "confidence_label", "낮음")

        agreement_ratio = agreement_count / total_signals if total_signals > 0 else 0.0

        # 가장 강한 강세/약세 신호 식별
        bullish_signals = sorted(
            [s for s in signal_results if getattr(s, "verdict", "") == "강세"],
            key=lambda s: getattr(s, "normalized", 0.5),
            reverse=True,
        )
        bearish_signals = sorted(
            [s for s in signal_results if getattr(s, "verdict", "") == "약세"],
            key=lambda s: getattr(s, "normalized", 0.5),
        )

        strongest_bullish = bullish_signals[0].name if bullish_signals else ""
        strongest_bearish = bearish_signals[0].name if bearish_signals else ""

        # 신호 요약 문자열
        signal_summary_parts = []
        for sr in signal_results[:3]:
            name = getattr(sr, "name", "")
            raw = getattr(sr, "raw_display", "")
            sv = getattr(sr, "verdict", "")
            arrow = getattr(sr, "trend_arrow", "")
            signal_summary_parts.append(f"{name}({raw}{arrow}: {sv})")
        signal_summary = ", ".join(signal_summary_parts) if signal_summary_parts else "신호 없음"

        # 서사 생성
        narrative = self._build_narrative(
            score=score,
            verdict=verdict,
            signal_summary=signal_summary,
            strongest_bullish=strongest_bullish,
            strongest_bearish=strongest_bearish,
            agreement_ratio=agreement_ratio,
            confidence_label=confidence_label,
            total_signals=total_signals,
        )

        # 리스크/기회 추출
        risk_factors = [s.name for s in bearish_signals[:3]] if bearish_signals else []
        opportunities = [s.name for s in bullish_signals[:3]] if bullish_signals else []

        logger.info(
            "DataPerspective 분석 완료: verdict=%s, score=%.1f, agreement=%.0f%%",
            verdict,
            score,
            agreement_ratio * 100,
        )

        return {
            "narrative": narrative,
            "verdict": verdict,
            "score": score,
            "strongest_bullish": strongest_bullish,
            "strongest_bearish": strongest_bearish,
            "agreement_ratio": agreement_ratio,
            "risk_factors": risk_factors,
            "opportunities": opportunities,
        }

    def _build_narrative(
        self,
        score: float,
        verdict: str,
        signal_summary: str,
        strongest_bullish: str,
        strongest_bearish: str,
        agreement_ratio: float,
        confidence_label: str,
        total_signals: int,
    ) -> str:
        """데이터 관점 서사를 2-3문장으로 생성한다."""
        lines: list[str] = []

        # 첫 문장: 종합 점수와 신호 현황
        if total_signals > 0:
            lines.append(
                f"복합 신호 점수가 {score:.0f}/100({verdict})을 기록하며, "
                f"총 {total_signals}개 지표 중 {agreement_ratio * 100:.0f}%가 "
                f"같은 방향을 가리키고 있습니다({signal_summary})."
            )
        else:
            lines.append("정량 데이터 신호가 부족하여 신뢰할 수 있는 복합 점수 산출이 어렵습니다.")

        # 둘째 문장: 강세/약세 신호 강조
        if strongest_bullish and strongest_bearish:
            lines.append(
                f"가장 강한 강세 신호는 {strongest_bullish}이며, "
                f"반대로 {strongest_bearish}는 하방 압력을 지속하고 있어 "
                f"신호 간 괴리가 존재합니다."
            )
        elif strongest_bullish:
            lines.append(
                f"{strongest_bullish}가 주요 강세 동인으로 작용하고 있으며, 뚜렷한 약세 신호는 현재 감지되지 않습니다."
            )
        elif strongest_bearish:
            lines.append(
                f"{strongest_bearish}가 뚜렷한 약세 신호를 보내고 있으며, "
                f"반전을 이끌 강세 촉매가 아직 확인되지 않습니다."
            )

        # 셋째 문장: 신뢰도 코멘트
        if agreement_ratio >= 0.75:
            lines.append(f"신뢰도가 {confidence_label}으로 이 방향성에 대한 시장 컨센서스가 형성되어 있습니다.")
        elif agreement_ratio >= 0.5:
            lines.append(f"신뢰도가 {confidence_label} 수준으로, 추세 확인을 위한 추가 지표 모니터링이 권고됩니다.")
        else:
            lines.append("신뢰도가 낮아 현재 신호들이 혼재된 상태이며, 단기 방향성 예측이 어렵습니다.")

        return " ".join(lines)


# ── 심리 관점 (MediaAgent) ────────────────────────────────────────────────────


class SentimentPerspective:
    """뉴스 심리와 토픽 데이터를 분석해 서사를 생성하는 관점 모듈.

    MindSpider의 키워드/클러스터 결과를 입력받아:
    - 토픽별 감성 분포 분석
    - 심리-키워드 패턴 식별 (어떤 토픽이 긍정/부정 감성을 유발하는지)
    - 심리 관점 서사 문단 생성
    """

    def analyze(
        self,
        topic_clusters: list[Any] | None,
        keywords: list[dict] | None,
    ) -> dict[str, Any]:
        """토픽 클러스터와 키워드를 분석해 심리 관점 결과를 반환한다.

        Args:
            topic_clusters: mindspider.TopicCluster 리스트. None이면 기본값 반환.
            keywords: extract_keywords() 반환 딕셔너리 리스트.
                각 항목은 'keyword', 'sentiment', 'count' 키를 포함.

        Returns:
            dict: narrative(str), verdict(str), sentiment_score(float),
                  positive_topics(list), negative_topics(list),
                  dominant_bearish_kws(list), dominant_bullish_kws(list),
                  risk_factors(list), opportunities(list) 포함.
        """
        clusters = topic_clusters or []
        kws = keywords or []

        if not clusters and not kws:
            logger.warning("SentimentPerspective: 입력 데이터 없음 → 기본값 반환")
            return {
                "narrative": "뉴스 심리 데이터가 제공되지 않아 심리 분석을 수행할 수 없습니다. 시장 중립 상태로 가정합니다.",
                "verdict": "중립",
                "sentiment_score": 0.0,
                "positive_topics": [],
                "negative_topics": [],
                "dominant_bullish_kws": [],
                "dominant_bearish_kws": [],
                "risk_factors": [],
                "opportunities": [],
            }

        # 토픽별 감성 분류
        positive_topics: list[str] = []
        negative_topics: list[str] = []
        total_score = 0.0
        n_clusters = len(clusters)

        for cluster in clusters:
            topic_name = getattr(cluster, "topic_name", "")
            sentiment = getattr(cluster, "sentiment_score", 0.0)
            total_score += sentiment
            if sentiment > 0.05:
                positive_topics.append(topic_name)
            elif sentiment < -0.05:
                negative_topics.append(topic_name)

        avg_sentiment = total_score / n_clusters if n_clusters > 0 else 0.0

        # 키워드별 강세/약세 분류
        bullish_kws = [kw["keyword"] for kw in kws if kw.get("sentiment") == "bullish"][:5]
        bearish_kws = [kw["keyword"] for kw in kws if kw.get("sentiment") == "bearish"][:5]

        # 감성 점수 → 버딕트
        if avg_sentiment > 0.15:
            verdict = "강세"
        elif avg_sentiment < -0.15:
            verdict = "약세"
        elif abs(avg_sentiment) <= 0.05 and positive_topics and negative_topics:
            verdict = "혼조"
        else:
            verdict = "중립"

        narrative = self._build_narrative(
            n_clusters=n_clusters,
            avg_sentiment=avg_sentiment,
            verdict=verdict,
            positive_topics=positive_topics,
            negative_topics=negative_topics,
            bullish_kws=bullish_kws,
            bearish_kws=bearish_kws,
        )

        # 리스크: 부정 토픽 + 약세 키워드
        risk_factors = list(negative_topics[:2]) + [f"키워드 '{kw}'" for kw in bearish_kws[:2]]
        opportunities = list(positive_topics[:2]) + [f"키워드 '{kw}'" for kw in bullish_kws[:2]]

        logger.info(
            "SentimentPerspective 분석 완료: verdict=%s, avg_sentiment=%.3f, 클러스터=%d개",
            verdict,
            avg_sentiment,
            n_clusters,
        )

        return {
            "narrative": narrative,
            "verdict": verdict,
            "sentiment_score": round(avg_sentiment, 3),
            "positive_topics": positive_topics,
            "negative_topics": negative_topics,
            "dominant_bullish_kws": bullish_kws,
            "dominant_bearish_kws": bearish_kws,
            "risk_factors": risk_factors,
            "opportunities": opportunities,
        }

    def _build_narrative(
        self,
        n_clusters: int,
        avg_sentiment: float,
        verdict: str,
        positive_topics: list[str],
        negative_topics: list[str],
        bullish_kws: list[str],
        bearish_kws: list[str],
    ) -> str:
        """심리 관점 서사를 2-3문장으로 생성한다."""
        lines: list[str] = []

        # 첫 문장: 토픽 전반의 감성 분포
        pos_n = len(positive_topics)
        neg_n = len(negative_topics)
        sentiment_sign = "+" if avg_sentiment >= 0 else ""
        if n_clusters > 0:
            lines.append(
                f"주요 토픽 {n_clusters}개 중 긍정 {pos_n}건, 부정 {neg_n}건이 감지되어 "
                f"전체 심리 점수가 {sentiment_sign}{avg_sentiment:.2f}({verdict})을 기록했습니다."
            )
        else:
            lines.append("토픽 클러스터 데이터 없이 키워드 기반으로만 심리를 분석합니다.")

        # 둘째 문장: 부정/긍정 키워드 강조
        if bearish_kws and bullish_kws:
            bearish_str = _format_list_inline(bearish_kws[:3], " · ")
            bullish_str = _format_list_inline(bullish_kws[:3], " · ")
            lines.append(
                f"특히 '{bearish_str}' 관련 뉴스가 하방 심리를 자극하는 반면, "
                f"'{bullish_str}' 토픽에서는 긍정적 흐름이 관측됩니다."
            )
        elif bearish_kws:
            bearish_str = _format_list_inline(bearish_kws[:3], " · ")
            lines.append(
                f"'{bearish_str}' 관련 뉴스가 전반적인 하방 심리를 주도하고 있으며, "
                f"반전을 이끌 긍정적 재료는 제한적입니다."
            )
        elif bullish_kws:
            bullish_str = _format_list_inline(bullish_kws[:3], " · ")
            lines.append(
                f"'{bullish_str}' 관련 뉴스가 시장 낙관론을 뒷받침하고 있으며, 부정적 재료는 현재 두드러지지 않습니다."
            )

        # 셋째 문장: 심리 수렴/발산 코멘트
        if pos_n > 0 and neg_n > 0 and abs(pos_n - neg_n) <= 1:
            lines.append(
                "긍정과 부정 심리가 팽팽하게 맞서고 있어 단기 방향성은 뉴스 흐름 변화에 민감하게 반응할 수 있습니다."
            )
        elif pos_n > neg_n * 2:
            lines.append("긍정적 심리가 압도적으로 우세해 현재 시장 분위기는 낙관론이 지배적입니다.")
        elif neg_n > pos_n * 2:
            lines.append("부정적 심리가 강하게 우세해 투자자들의 공포 및 불확실성이 높아진 상태입니다.")

        return " ".join(lines)


# ── 매크로 관점 (QueryAgent) ──────────────────────────────────────────────────


class MacroPerspective:
    """매크로 경제 지표를 분석해 서사를 생성하는 관점 모듈.

    금리(us10y), 달러지수(dxy), VIX, 연준 기준금리(fed_rate) 등을 입력받아:
    - 매크로 환경 우호도 평가
    - 주요 리스크 요인 및 테일윈드 식별
    - 매크로 관점 서사 문단 생성
    """

    # 임계값 상수 — 수치 기반 판단 기준
    _US10Y_FRIENDLY = 4.0  # 10년물 금리 우호 상한
    _US10Y_PRESSURE = 4.75  # 10년물 금리 부담 임계
    _DXY_NEUTRAL = 100.0  # DXY 중립 수준
    _DXY_STRONG = 105.0  # DXY 강달러 임계
    _VIX_CALM = 18.0  # VIX 안정 임계
    _VIX_FEAR = 25.0  # VIX 공포 임계
    _FED_LOW = 2.5  # 연준 금리 우호 상한
    _FED_HIGH = 4.5  # 연준 금리 부담 임계

    def analyze(self, macro_data: dict[str, Any] | None) -> dict[str, Any]:
        """매크로 데이터를 분석해 매크로 관점 결과를 반환한다.

        Args:
            macro_data: 매크로 지표 딕셔너리. 지원 키:
                - us10y (float): 미국 10년물 금리 (%)
                - dxy (float): 달러지수
                - vix (float): VIX
                - fed_rate (float): 연준 기준금리 (%)
                - us10y_trend (str): 'rising' | 'falling' | 'stable'
                - dxy_trend (str): 'rising' | 'falling' | 'stable'
                None이면 기본값(중립) 반환.

        Returns:
            dict: narrative(str), verdict(str), macro_score(float),
                  tailwinds(list), headwinds(list),
                  risk_factors(list), opportunities(list) 포함.
        """
        if not macro_data:
            logger.warning("MacroPerspective: macro_data 없음 → 기본값 반환")
            return {
                "narrative": "매크로 지표 데이터가 제공되지 않아 거시경제 분석을 수행할 수 없습니다. 매크로 환경은 중립으로 가정합니다.",
                "verdict": "중립",
                "macro_score": 0.0,
                "tailwinds": [],
                "headwinds": [],
                "risk_factors": [],
                "opportunities": [],
            }

        sub_scores: list[float] = []
        headwinds: list[str] = []
        tailwinds: list[str] = []
        display_parts: list[str] = []

        # 미국 10년물 금리 분석
        us10y = macro_data.get("us10y")
        if us10y is not None:
            us10y = float(us10y)
            trend = str(macro_data.get("us10y_trend", "stable")).lower()
            arrow = "↑" if trend == "rising" else ("↓" if trend == "falling" else "→")
            display_parts.append(f"10년물 금리 {us10y:.2f}%{arrow}")

            if us10y <= self._US10Y_FRIENDLY:
                sub_scores.append(0.7)
                tailwinds.append(f"저금리 환경({us10y:.2f}%) — 위험자산 유동성 우호")
            elif us10y >= self._US10Y_PRESSURE:
                sub_scores.append(0.25)
                headwinds.append(f"고금리 부담({us10y:.2f}%) — 위험자산 밸류에이션 압박")
            else:
                sub_scores.append(0.5)

        # 달러지수 분석
        dxy = macro_data.get("dxy")
        if dxy is not None:
            dxy = float(dxy)
            trend = str(macro_data.get("dxy_trend", "stable")).lower()
            arrow = "↑" if trend == "rising" else ("↓" if trend == "falling" else "→")
            display_parts.append(f"DXY {dxy:.1f}{arrow}")

            if dxy >= self._DXY_STRONG:
                sub_scores.append(0.25)
                headwinds.append(f"강달러({dxy:.1f}) — 크립토·신흥시장 자금 이탈 압박")
            elif dxy <= self._DXY_NEUTRAL:
                sub_scores.append(0.65)
                tailwinds.append(f"약달러({dxy:.1f}) — 위험자산 선호 환경")
            else:
                sub_scores.append(0.45)

        # VIX 분석
        vix = macro_data.get("vix")
        if vix is not None:
            vix = float(vix)
            display_parts.append(f"VIX {vix:.1f}")

            if vix <= self._VIX_CALM:
                sub_scores.append(0.7)
                tailwinds.append(f"저변동성 환경(VIX {vix:.1f}) — 위험 선호 분위기")
            elif vix >= self._VIX_FEAR:
                sub_scores.append(0.25)
                headwinds.append(f"고변동성 공포(VIX {vix:.1f}) — 리스크 오프 심화")
            else:
                sub_scores.append(0.5)

        # 연준 기준금리 분석
        fed_rate = macro_data.get("fed_rate")
        if fed_rate is not None:
            fed_rate = float(fed_rate)
            display_parts.append(f"Fed금리 {fed_rate:.2f}%")

            if fed_rate <= self._FED_LOW:
                sub_scores.append(0.7)
                tailwinds.append(f"완화적 통화정책({fed_rate:.2f}%) — 유동성 확대 기대")
            elif fed_rate >= self._FED_HIGH:
                sub_scores.append(0.25)
                headwinds.append(f"긴축 기조({fed_rate:.2f}%) — 유동성 수축 압박")
            else:
                sub_scores.append(0.5)

        if not sub_scores:
            macro_score_norm = 0.5
        else:
            macro_score_norm = sum(sub_scores) / len(sub_scores)

        macro_score_100 = (macro_score_norm - 0.5) * 2.0  # -1.0 ~ 1.0
        verdict = _score_to_verdict(macro_score_100)

        narrative = self._build_narrative(
            display_parts=display_parts,
            verdict=verdict,
            tailwinds=tailwinds,
            headwinds=headwinds,
            macro_score_norm=macro_score_norm,
        )

        logger.info(
            "MacroPerspective 분석 완료: verdict=%s, score_norm=%.2f, 테일윈드=%d 헤드윈드=%d",
            verdict,
            macro_score_norm,
            len(tailwinds),
            len(headwinds),
        )

        return {
            "narrative": narrative,
            "verdict": verdict,
            "macro_score": round(macro_score_100, 2),
            "tailwinds": tailwinds,
            "headwinds": headwinds,
            "risk_factors": headwinds[:3],
            "opportunities": tailwinds[:3],
        }

    def _build_narrative(
        self,
        display_parts: list[str],
        verdict: str,
        tailwinds: list[str],
        headwinds: list[str],
        macro_score_norm: float,
    ) -> str:
        """매크로 관점 서사를 2-3문장으로 생성한다."""
        lines: list[str] = []

        # 첫 문장: 현재 매크로 수치 현황
        if display_parts:
            indicators_str = ", ".join(display_parts)
            lines.append(
                f"현재 매크로 환경은 {indicators_str}으로 구성되어 있으며, "
                f"전반적인 매크로 우호도는 {verdict} 수준으로 평가됩니다."
            )
        else:
            lines.append("매크로 지표가 충분하지 않아 전반적 환경 평가만 제한적으로 수행합니다.")

        # 둘째 문장: 테일윈드/헤드윈드 분석
        if tailwinds and headwinds:
            tw_str = _format_list_inline([tw.split(" — ")[0] for tw in tailwinds[:2]], ", ")
            hw_str = _format_list_inline([hw.split(" — ")[0] for hw in headwinds[:2]], ", ")
            lines.append(f"{tw_str}는 상방 요인으로 작용하는 반면, {hw_str}는 주요 하방 리스크로 지목됩니다.")
        elif tailwinds:
            tw_str = _format_list_inline([tw.split(" — ")[0] for tw in tailwinds[:2]], ", ")
            lines.append(f"{tw_str}이 매크로 테일윈드로 위험자산 투자 환경을 지지하고 있습니다.")
        elif headwinds:
            hw_str = _format_list_inline([hw.split(" — ")[0] for hw in headwinds[:2]], ", ")
            lines.append(f"{hw_str}이 뚜렷한 매크로 역풍으로 작용하여 투자 심리를 억누르고 있습니다.")

        # 셋째 문장: 결론 코멘트
        if macro_score_norm >= 0.65:
            lines.append(
                "전반적으로 거시경제 환경이 위험자산에 우호적이며, 중기 투자 관점에서 긍정적 신호가 우세합니다."
            )
        elif macro_score_norm <= 0.35:
            lines.append(
                "거시경제 환경이 전반적으로 위험자산에 비우호적이며, 헤지 전략 및 방어적 포지션 검토가 권고됩니다."
            )
        else:
            lines.append(
                "매크로 환경은 뚜렷한 방향성 없이 중립 수준을 유지하고 있어, 단기 이벤트에 따른 변동성에 주목해야 합니다."
            )

        return " ".join(lines)


# ── 포럼 종합 (ForumEngine) ───────────────────────────────────────────────────


class ForumSynthesis:
    """세 관점의 분석 결과를 종합해 최종 판단을 생성하는 엔진.

    각 관점의 버딕트와 서사를 교차 참조해:
    - 합의/불일치 여부 확인
    - 가중 평균 기반 최종 버딕트 결정
    - 종합 서사 및 리스크/기회 목록 통합 생성
    """

    # 관점별 가중치 (데이터 > 심리 > 매크로)
    _WEIGHTS = {
        "data": 0.45,
        "sentiment": 0.35,
        "macro": 0.20,
    }

    def synthesize(
        self,
        data_result: dict[str, Any],
        sentiment_result: dict[str, Any],
        macro_result: dict[str, Any],
    ) -> dict[str, Any]:
        """세 관점 결과를 종합해 최종 분석 결과를 반환한다.

        Args:
            data_result: DataPerspective.analyze() 반환값.
            sentiment_result: SentimentPerspective.analyze() 반환값.
            macro_result: MacroPerspective.analyze() 반환값.

        Returns:
            dict: synthesis(str), verdict(str), confidence(str),
                  risk_factors(list), opportunities(list),
                  perspective_agreement(str) 포함.
        """
        data_verdict = data_result.get("verdict", "중립")
        sent_verdict = sentiment_result.get("verdict", "중립")
        macro_verdict = macro_result.get("verdict", "중립")

        # 수치 점수로 변환 후 가중 평균
        data_score = _verdict_to_score(data_verdict)
        sent_score = _verdict_to_score(sent_verdict)
        macro_score_raw = macro_result.get("macro_score", 0.0)
        # macro_score는 이미 -1.0 ~ 1.0
        macro_score_weighted = float(macro_score_raw)

        weighted_sum = (
            data_score * self._WEIGHTS["data"]
            + sent_score * self._WEIGHTS["sentiment"]
            + macro_score_weighted * self._WEIGHTS["macro"]
        )

        final_verdict = _score_to_verdict(weighted_sum)

        # 일치도 계산
        verdicts = [data_verdict, sent_verdict, macro_verdict]
        main_direction = final_verdict if final_verdict in ("강세", "약세") else None

        if main_direction:
            agree_count = sum(1 for v in verdicts if v == main_direction)
        else:
            # 중립/혼조의 경우 중립 계열 일치도
            agree_count = sum(1 for v in verdicts if v in ("중립", "혼조"))

        confidence = _confidence_from_agreement(agree_count, len(verdicts))

        # 관점 합의 문자열
        perspective_agreement = self._describe_agreement(data_verdict, sent_verdict, macro_verdict, final_verdict)

        # 리스크/기회 통합 (중복 제거, 최대 5개씩)
        all_risks: list[str] = (
            data_result.get("risk_factors", [])
            + sentiment_result.get("risk_factors", [])
            + macro_result.get("risk_factors", [])
        )
        all_opps: list[str] = (
            data_result.get("opportunities", [])
            + sentiment_result.get("opportunities", [])
            + macro_result.get("opportunities", [])
        )

        risk_factors = list(dict.fromkeys(r for r in all_risks if r))[:5]
        opportunities = list(dict.fromkeys(o for o in all_opps if o))[:5]

        synthesis = self._build_synthesis(
            data_verdict=data_verdict,
            sent_verdict=sent_verdict,
            macro_verdict=macro_verdict,
            final_verdict=final_verdict,
            perspective_agreement=perspective_agreement,
            confidence=confidence,
            risk_factors=risk_factors,
            opportunities=opportunities,
        )

        logger.info(
            "ForumSynthesis 완료: final=%s, confidence=%s, 합의=%s",
            final_verdict,
            confidence,
            perspective_agreement,
        )

        return {
            "synthesis": synthesis,
            "verdict": final_verdict,
            "confidence": confidence,
            "risk_factors": risk_factors,
            "opportunities": opportunities,
            "perspective_agreement": perspective_agreement,
        }

    def _describe_agreement(
        self,
        data_v: str,
        sent_v: str,
        macro_v: str,
        final_v: str,
    ) -> str:
        """세 관점의 합의 또는 불일치를 한 문장으로 표현한다."""
        verdicts = [data_v, sent_v, macro_v]
        unique = set(verdicts)

        if len(unique) == 1:
            return f"세 관점 모두 {final_v}로 완전 합의"
        if len(unique) == 2:
            majority = max(unique, key=verdicts.count)
            minority = (unique - {majority}).pop()
            return f"다수 관점({majority}) vs 소수 관점({minority}) — 부분 합의"
        return "세 관점 모두 다른 방향을 가리키는 완전 분산 상태"

    def _build_synthesis(
        self,
        data_verdict: str,
        sent_verdict: str,
        macro_verdict: str,
        final_verdict: str,
        perspective_agreement: str,
        confidence: str,
        risk_factors: list[str],
        opportunities: list[str],
    ) -> str:
        """종합 서사를 3-4문장으로 생성한다."""
        confidence_kr = {"high": "높음", "medium": "보통", "low": "낮음"}.get(confidence, "낮음")
        lines: list[str] = []

        # 첫 문장: 관점별 버딕트 요약
        lines.append(
            f"데이터 분석 관점은 {data_verdict}, 심리 분석은 {sent_verdict}, "
            f"매크로 환경은 {macro_verdict}를 나타내며, "
            f"가중 종합 판단은 {final_verdict}입니다."
        )

        # 둘째 문장: 합의/불일치 설명
        lines.append(f"{perspective_agreement}으로, 분석 신뢰도는 {confidence_kr} 수준입니다.")

        # 셋째 문장: 리스크 vs 기회
        if risk_factors and opportunities:
            risk_str = _format_list_inline(risk_factors[:3], " · ")
            opp_str = _format_list_inline(opportunities[:3], " · ")
            lines.append(
                f"주요 하방 리스크로는 {risk_str}이 있으며, 반면 {opp_str}은 상방 기회 요인으로 작용할 수 있습니다."
            )
        elif risk_factors:
            risk_str = _format_list_inline(risk_factors[:3], " · ")
            lines.append(f"주요 리스크 요인은 {risk_str}으로, 방어적 포지션 관리가 중요합니다.")
        elif opportunities:
            opp_str = _format_list_inline(opportunities[:3], " · ")
            lines.append(f"현재 {opp_str}가 주요 기회 요인으로 부각되고 있습니다.")

        # 넷째 문장: 최종 투자 시사점
        if final_verdict == "강세":
            lines.append("전반적으로 위험자산 비중 확대 관점이 유효하나, 신뢰도를 감안해 단계적 접근이 권고됩니다.")
        elif final_verdict == "약세":
            lines.append(
                "단기적으로 위험자산 비중 축소 및 현금 비율 확대를 고려할 시점이며, 손절 라인 설정이 중요합니다."
            )
        elif final_verdict == "혼조":
            lines.append(
                "시장 방향성이 불분명한 혼조 국면으로, 중립 포지션을 유지하며 명확한 신호 출현을 기다리는 전략이 유효합니다."
            )
        else:
            lines.append(
                "현 시장은 명확한 방향성 없이 중립 구간에 위치해 있으므로, 이벤트 모니터링과 분할 매수 전략이 적합합니다."
            )

        return " ".join(lines)


# ── 메인 엔진 ─────────────────────────────────────────────────────────────────


class BettaFishAnalyzer:
    """세 가지 분석 관점을 조율하고 최종 보고서를 생성하는 멀티 관점 분석 엔진.

    BettaFish 시스템의 QueryAgent(MacroPerspective), InsightAgent(DataPerspective),
    MediaAgent(SentimentPerspective), ForumEngine(ForumSynthesis)에 해당하는
    컴포넌트를 내부적으로 보유하며, analyze() 단일 진입점으로 사용한다.

    사용 예시::

        from scripts.common.bettafish_analyzer import BettaFishAnalyzer
        from scripts.common.signal_composer import SignalComposer
        from scripts.common.mindspider import MindSpider

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

        # 타임스탬프
        timestamp = datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

        report = AnalysisReport(
            data_narrative=data_result["narrative"],
            sentiment_narrative=sentiment_result["narrative"],
            macro_narrative=macro_result["narrative"],
            synthesis=forum_result["synthesis"],
            risk_factors=forum_result["risk_factors"],
            opportunities=forum_result["opportunities"],
            verdict=forum_result["verdict"],
            confidence=forum_result["confidence"],
            key_levels={},
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

        # 데이터 분석 섹션
        lines.append("### 데이터 분석 (InsightAgent)")
        lines.append(report.data_narrative)
        lines.append("")

        # 심리 분석 섹션
        lines.append("### 심리 분석 (SentimentAgent)")
        lines.append(report.sentiment_narrative)
        lines.append("")

        # 매크로 분석 섹션
        lines.append("### 매크로 분석 (MacroAgent)")
        lines.append(report.macro_narrative)
        lines.append("")

        # 종합 의견 섹션
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
        lines.append("> 📊 본 분석은 MindSpider 토픽 추출 + BettaFish 멀티 관점 엔진 기반 자동 생성입니다.")

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
