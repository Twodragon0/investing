"""BettaFish 세 가지 분석 관점 (InsightAgent / MediaAgent / QueryAgent).

정량 데이터(DataPerspective), 뉴스 심리(SentimentPerspective), 매크로 환경
(MacroPerspective)을 각각 분석해 관점별 서사·버딕트를 생성한다. leaf 모듈
`bettafish_models`만 의존한다.

`bettafish_analyzer.py`가 세 클래스를 재-export하므로 기존 import 경로는
변경 없이 동작한다.
"""

from __future__ import annotations

from typing import Any

from .bettafish_models import _format_list_inline, _score_to_verdict
from .config import setup_logging

logger = setup_logging("bettafish_analyzer")


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
