"""BettaFish 포럼 종합 엔진 (ForumEngine 역할).

세 관점(데이터/심리/매크로)의 분석 결과를 교차 참조해 가중 평균 기반
최종 버딕트와 종합 서사를 생성한다. leaf 모듈 `bettafish_models`만 의존한다.

`bettafish_analyzer.py`가 `ForumSynthesis`를 재-export하므로 기존 import
경로는 변경 없이 동작한다.
"""

from __future__ import annotations

from typing import Any

from .bettafish_models import (
    ReportChapter,
    _confidence_from_agreement,
    _format_list_inline,
    _score_to_verdict,
    _verdict_to_score,
)
from .config import setup_logging

logger = setup_logging("bettafish_analyzer")


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

    def _cite_evidence(
        self,
        narratives: dict[str, str],
        insights: list[dict[str, Any]],
        chapters: list[ReportChapter] | None = None,
    ) -> str:
        """MiroFish ReACT 패턴: 분석 근거를 인용하여 종합 서사를 생성한다.

        각 관점의 핵심 증거를 blockquote 형식으로 인용하고
        InsightForge의 하위 질문 답변을 종합 서사에 통합한다.

        Args:
            narratives: 관점별 서사 딕셔너리 (data, sentiment, macro 키).
            insights: InsightForge.analyze_sub_questions() 반환값.
            chapters: InsightForge.build_chapters() 반환값 (optional).

        Returns:
            str: 증거 인용이 포함된 종합 서사 마크다운 문자열.
        """
        lines: list[str] = []

        # 각 관점에서 핵심 증거 인용
        if chapters:
            for chapter in chapters:
                if chapter.evidence:
                    primary_evidence = chapter.evidence[0]
                    perspective_label = chapter.title.split(" (")[0]
                    lines.append(f'> "{primary_evidence}" ({perspective_label})')

        # InsightForge 고신뢰 하위 질문 답변 통합
        high_conf_insights = [i for i in insights if i.get("confidence") == "high"]
        if high_conf_insights:
            lines.append("")
            lines.append("**핵심 분석 결과:**")
            for insight in high_conf_insights[:3]:
                q = insight["question"]
                a = insight["answer"]
                lines.append(f"- **{q}** → {a}")

        return "\n".join(lines) if lines else ""
