"""BettaFish InsightForge — 하위 질문 분해 기반 다차원 분석 (MiroFish 패턴).

핵심 질문을 하위 질문으로 자동 분해하고 규칙 기반 답변·증거를 생성하며,
세 관점 결과를 `ReportChapter` 목록으로 구조화한다. leaf 모듈
`bettafish_models`만 의존한다.

`bettafish_analyzer.py`가 `InsightForge`를 재-export하므로 기존 import
경로는 변경 없이 동작한다.
"""

from __future__ import annotations

from typing import Any

from .bettafish_models import ReportChapter, _format_list_inline

# ── InsightForge (MiroFish 하위 질문 분해 패턴) ────────────────────────────────


class InsightForge:
    """질문을 하위 질문으로 분해하여 다차원 분석을 수행한다.

    MiroFish의 InsightForge 패턴을 차용: 핵심 질문 → 하위 질문 자동 분해 →
    다차원 검색 → 종합. 규칙 기반으로 동작하며 외부 API 의존 없음.
    """

    # 시장 방향별 하위 질문 템플릿
    _MARKET_QUESTIONS: dict[str, list[str]] = {
        "강세": [
            "어떤 지표가 상승 모멘텀을 지지하는가?",
            "기관 투자자의 포지션 변화는?",
            "리스크 요인은 충분히 해소되었는가?",
        ],
        "약세": [
            "하방 리스크의 핵심 동인은 무엇인가?",
            "패닉 매도 징후가 있는가?",
            "매크로 환경이 추가 압박을 줄 가능성은?",
        ],
        "중립": [
            "방향성 결정을 지연시키는 요인은?",
            "다음 촉매(catalyst)는 무엇인가?",
            "변동성 확대 가능성은?",
        ],
        "혼조": [
            "상충되는 신호의 핵심 원인은?",
            "어느 관점이 선행 지표로서 더 신뢰할 수 있는가?",
            "혼조 국면 해소 시 예상 방향은?",
        ],
    }

    # 데이터 관점별 증거 추출 규칙
    _EVIDENCE_THRESHOLDS = {
        "fng_fear": 45,  # F&G 공포 구간 상한
        "fng_greed": 60,  # F&G 탐욕 구간 하한
        "vix_calm": 18.0,  # VIX 안정 임계
        "vix_fear": 25.0,  # VIX 공포 임계
        "us10y_pressure": 4.75,  # 10Y 금리 부담 임계
        "dxy_strong": 105.0,  # DXY 강달러 임계
    }

    def decompose(self, verdict: str, signals: dict[str, Any]) -> list[str]:
        """시장 상황을 하위 질문으로 분해한다.

        Args:
            verdict: 현재 시장 판정 ('강세' | '약세' | '중립' | '혼조').
            signals: 신호 데이터 딕셔너리 (composite_result, macro_data 등).

        Returns:
            list[str]: 분석할 하위 질문 목록.
        """
        base_questions = self._MARKET_QUESTIONS.get(verdict, self._MARKET_QUESTIONS["중립"]).copy()

        # 신호 데이터에 따라 추가 질문 삽입
        extra = self._generate_market_sub_questions(signals)
        combined = base_questions + [q for q in extra if q not in base_questions]
        return combined[:5]  # 최대 5개 하위 질문

    def analyze_sub_questions(
        self,
        questions: list[str],
        context: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """각 하위 질문에 대해 데이터 기반 답변을 생성한다.

        Args:
            questions: decompose()가 반환한 하위 질문 목록.
            context: 분석 컨텍스트 딕셔너리.
                지원 키: composite_result, macro_data, sentiment_result,
                          data_result, topic_clusters.

        Returns:
            list[dict]: 각 항목은 question(str), answer(str),
                        evidence(list[str]), confidence(str) 포함.
        """
        results: list[dict[str, Any]] = []
        for question in questions:
            answer, evidence, confidence = self._answer_question(question, context)
            results.append(
                {
                    "question": question,
                    "answer": answer,
                    "evidence": evidence,
                    "confidence": confidence,
                }
            )
        return results

    def build_chapters(
        self,
        data_result: dict[str, Any],
        sentiment_result: dict[str, Any],
        macro_result: dict[str, Any],
        sub_question_results: list[dict[str, Any]],
        context: dict[str, Any],
    ) -> list[ReportChapter]:
        """세 관점 결과를 ReportChapter 목록으로 변환한다.

        Args:
            data_result: DataPerspective.analyze() 반환값.
            sentiment_result: SentimentPerspective.analyze() 반환값.
            macro_result: MacroPerspective.analyze() 반환값.
            sub_question_results: analyze_sub_questions() 반환값.
            context: analyze() 컨텍스트 딕셔너리.

        Returns:
            list[ReportChapter]: 3개 관점 챕터 목록.
        """
        # 데이터 챕터 증거 추출
        data_evidence = self._extract_data_evidence(data_result, context.get("macro_data"))
        # 심리 챕터 증거 추출
        sent_evidence = self._extract_sentiment_evidence(sentiment_result)
        # 매크로 챕터 증거 추출
        macro_evidence = self._extract_macro_evidence(macro_result, context.get("macro_data"))

        # 데이터 챕터용 질문 (모멘텀/패닉 매도 관련)
        data_qs = [
            r["question"]
            for r in sub_question_results
            if any(kw in r["question"] for kw in ["지표", "모멘텀", "패닉", "하방 리스크", "방향성"])
        ][:2]
        # 심리 챕터용 질문 (투자자 심리/뉴스 관련)
        sent_qs = [
            r["question"]
            for r in sub_question_results
            if any(kw in r["question"] for kw in ["촉매", "뉴스", "심리", "포지션", "매도"])
        ][:2]
        # 매크로 챕터용 질문 (매크로 환경 관련)
        macro_qs = [
            r["question"]
            for r in sub_question_results
            if any(kw in r["question"] for kw in ["매크로", "압박", "변동성", "환경", "리스크 해소"])
        ][:2]

        return [
            ReportChapter(
                title="데이터 분석 (InsightAgent)",
                content=data_result.get("narrative", ""),
                evidence=data_evidence,
                sub_questions=data_qs,
                verdict=data_result.get("verdict", "중립"),
            ),
            ReportChapter(
                title="심리 분석 (SentimentAgent)",
                content=sentiment_result.get("narrative", ""),
                evidence=sent_evidence,
                sub_questions=sent_qs,
                verdict=sentiment_result.get("verdict", "중립"),
            ),
            ReportChapter(
                title="매크로 분석 (MacroAgent)",
                content=macro_result.get("narrative", ""),
                evidence=macro_evidence,
                sub_questions=macro_qs,
                verdict=macro_result.get("verdict", "중립"),
            ),
        ]

    # ── 내부 헬퍼 ──────────────────────────────────────────────────────────────

    def _generate_market_sub_questions(self, signals: dict[str, Any]) -> list[str]:
        """현재 신호 데이터에 따라 추가 하위 질문을 동적 생성한다."""
        extra: list[str] = []
        macro = signals.get("macro_data") or {}
        vix = macro.get("vix")
        us10y = macro.get("us10y")
        dxy = macro.get("dxy")

        if vix is not None and float(vix) >= self._EVIDENCE_THRESHOLDS["vix_fear"]:
            extra.append("VIX 급등이 위험자산 전반에 미치는 영향은?")

        if us10y is not None and float(us10y) >= self._EVIDENCE_THRESHOLDS["us10y_pressure"]:
            extra.append("고금리 지속이 암호화폐 밸류에이션에 미치는 구체적 영향은?")

        if dxy is not None and float(dxy) >= self._EVIDENCE_THRESHOLDS["dxy_strong"]:
            extra.append("강달러 환경에서 신흥시장 및 크립토 자금 유출 규모는?")

        data_result = signals.get("data_result") or {}
        agreement_ratio = data_result.get("agreement_ratio", 0.5)
        if agreement_ratio < 0.4:
            extra.append("신호 혼재 상황에서 가장 신뢰할 수 있는 선행 지표는?")

        return extra

    def _answer_question(
        self,
        question: str,
        context: dict[str, Any],
    ) -> tuple[str, list[str], str]:
        """단일 하위 질문에 대한 규칙 기반 답변을 생성한다.

        Returns:
            tuple: (answer: str, evidence: list[str], confidence: str)
        """
        macro = context.get("macro_data") or {}
        data_result = context.get("data_result") or {}
        sentiment_result = context.get("sentiment_result") or {}
        macro_result = context.get("macro_result") or {}

        vix = macro.get("vix")
        us10y = macro.get("us10y")
        fng = data_result.get("score")  # F&G proxy via composite score
        bearish_kws = sentiment_result.get("dominant_bearish_kws", [])
        negative_topics = sentiment_result.get("negative_topics", [])
        headwinds = macro_result.get("headwinds", [])
        tailwinds = macro_result.get("tailwinds", [])
        agreement_ratio = data_result.get("agreement_ratio", 0.5)

        evidence: list[str] = []
        answer = ""
        confidence = "medium"

        q_lower = question.lower()

        # 패닉 매도 관련 질문
        if "패닉" in question or "패닉 매도" in question:
            if fng is not None and float(fng) < self._EVIDENCE_THRESHOLDS["fng_fear"]:
                fng_val = float(fng)
                evidence.append(f"복합 신호 점수 {fng_val:.0f} — 공포 구간 진입")
                if fng_val > 25:
                    answer = f"복합 점수 {fng_val:.0f}로 공포 구간이나 극공포(25 미만)에는 미달 — 아직 패닉 단계 아님"
                    confidence = "high"
                else:
                    answer = f"복합 점수 {fng_val:.0f}으로 극공포 수준 — 패닉 매도 신호 감지"
                    confidence = "high"
            else:
                answer = "현재 지표상 패닉 매도 징후 없음 — 정상 조정 범위 내"
                confidence = "medium"

        # 하방 리스크 핵심 동인
        elif "하방 리스크" in question or "핵심 동인" in question:
            drivers: list[str] = []
            if vix is not None and float(vix) >= self._EVIDENCE_THRESHOLDS["vix_fear"]:
                vix_val = float(vix)
                drivers.append(f"VIX {vix_val:.1f} 급등")
                evidence.append(f"VIX {vix_val:.1f} — 공포 임계({self._EVIDENCE_THRESHOLDS['vix_fear']}) 초과")
            if us10y is not None and float(us10y) >= self._EVIDENCE_THRESHOLDS["us10y_pressure"]:
                us10y_val = float(us10y)
                drivers.append(f"10년물 금리 {us10y_val:.2f}% 고금리")
                evidence.append(
                    f"10년물 금리 {us10y_val:.2f}% — 부담 임계({self._EVIDENCE_THRESHOLDS['us10y_pressure']}%) 초과"
                )
            if headwinds:
                evidence.extend([hw.split(" — ")[0] for hw in headwinds[:2]])
            answer = _format_list_inline(drivers, ", ") + "이 주요 동인" if drivers else "뚜렷한 하방 동인 미확인"
            confidence = "high" if len(evidence) >= 2 else "medium"

        # 상승 모멘텀 지지 지표
        elif "상승 모멘텀" in question or "지표가" in question:
            supporters: list[str] = []
            strongest_bullish = data_result.get("strongest_bullish", "")
            if strongest_bullish:
                supporters.append(strongest_bullish)
                evidence.append(f"최강 강세 신호: {strongest_bullish}")
            if tailwinds:
                evidence.extend([tw.split(" — ")[0] for tw in tailwinds[:2]])
                supporters.extend([tw.split("(")[0].strip() for tw in tailwinds[:2]])
            answer = (
                _format_list_inline(supporters[:3], ", ") + "이 상승 모멘텀 지지"
                if supporters
                else "상승 모멘텀 지지 신호 부족"
            )
            confidence = "high" if len(evidence) >= 2 else "low"

        # 매크로 추가 압박 가능성
        elif "매크로" in question and "압박" in question:
            pressures: list[str] = []
            if us10y is not None and float(us10y) >= self._EVIDENCE_THRESHOLDS["us10y_pressure"]:
                us10y_val = float(us10y)
                pressures.append(f"10Y {us10y_val:.2f}% 상승 추세")
                evidence.append(f"10년물 금리 {us10y_val:.2f}%")
            macro_verdict = macro_result.get("verdict", "중립")
            if macro_verdict == "약세":
                pressures.append("매크로 종합 약세 판정")
                evidence.append(f"매크로 판정: {macro_verdict}")
            answer = (
                _format_list_inline(pressures, " + ") + "으로 추가 압박 가능성 있음"
                if pressures
                else "추가 매크로 압박 신호 제한적"
            )
            confidence = "medium"

        # 방향성 결정 지연 요인
        elif "방향성" in question or "지연" in question:
            delays: list[str] = []
            if agreement_ratio < 0.5:
                delays.append(f"신호 일치율 {agreement_ratio * 100:.0f}% — 혼재")
                evidence.append(f"신호 일치율 {agreement_ratio * 100:.0f}%")
            if bearish_kws and sentiment_result.get("dominant_bullish_kws"):
                delays.append("강세/약세 키워드 혼재")
            answer = _format_list_inline(delays, ", ") + "이 방향성 결정 지연" if delays else "방향성 지연 요인 불명확"
            confidence = "medium"

        # 다음 촉매
        elif "촉매" in question or "catalyst" in q_lower:
            catalysts: list[str] = []
            if negative_topics:
                catalysts.append(f"'{negative_topics[0]}' 해소 여부")
                evidence.append(f"부정 토픽: {negative_topics[0]}")
            strongest_bearish = data_result.get("strongest_bearish", "")
            if strongest_bearish:
                catalysts.append(f"{strongest_bearish} 반전")
                evidence.append(f"최강 약세 신호: {strongest_bearish}")
            answer = _format_list_inline(catalysts, ", ") + "가 다음 촉매 후보" if catalysts else "명확한 촉매 미확인"
            confidence = "low"

        # 변동성 확대 가능성
        elif "변동성" in question:
            if vix is not None:
                vix_val = float(vix)
                evidence.append(f"VIX {vix_val:.1f}")
                if vix_val >= self._EVIDENCE_THRESHOLDS["vix_fear"]:
                    answer = f"VIX {vix_val:.1f} — 이미 고변동성 구간, 추가 확대 경계 필요"
                    confidence = "high"
                elif vix_val >= self._EVIDENCE_THRESHOLDS["vix_calm"]:
                    answer = f"VIX {vix_val:.1f} — 중간 구간, 이벤트 발생 시 확대 가능"
                    confidence = "medium"
                else:
                    answer = f"VIX {vix_val:.1f} — 안정 구간, 단기 변동성 확대 가능성 낮음"
                    confidence = "high"
            else:
                answer = "VIX 데이터 없음 — 변동성 평가 불가"
                confidence = "low"

        # VIX 관련
        elif "vix" in q_lower or "VIX" in question:
            if vix is not None:
                vix_val = float(vix)
                evidence.append(f"VIX {vix_val:.1f}")
                answer = f"VIX {vix_val:.1f}으로 {'공포' if vix_val >= self._EVIDENCE_THRESHOLDS['vix_fear'] else '주의'} 수준"
                confidence = "high"
            else:
                answer = "VIX 데이터 미제공"
                confidence = "low"

        # 기본 답변 (매칭 실패)
        else:
            answer = "제공된 데이터로는 이 질문에 직접 답변이 어렵습니다."
            confidence = "low"

        return answer, evidence, confidence

    def _extract_data_evidence(
        self,
        data_result: dict[str, Any],
        macro_data: dict[str, Any] | None,
    ) -> list[str]:
        """데이터 관점에서 인용 가능한 증거를 추출한다."""
        evidence: list[str] = []
        score = data_result.get("score")
        verdict = data_result.get("verdict", "중립")
        agreement_ratio = data_result.get("agreement_ratio", 0.0)

        if score is not None:
            evidence.append(f"복합 신호 점수 {score:.0f}/100 — {verdict}")
        if agreement_ratio > 0:
            evidence.append(f"신호 일치율 {agreement_ratio * 100:.0f}%")

        strongest_bullish = data_result.get("strongest_bullish", "")
        strongest_bearish = data_result.get("strongest_bearish", "")
        if strongest_bullish:
            evidence.append(f"최강 강세 신호: {strongest_bullish}")
        if strongest_bearish:
            evidence.append(f"최강 약세 신호: {strongest_bearish}")

        # 매크로 데이터에서 VIX 추가 (데이터 관점에서도 참조)
        if macro_data:
            vix = macro_data.get("vix")
            if vix is not None:
                vix_val = float(vix)
                label = (
                    "공포"
                    if vix_val >= self._EVIDENCE_THRESHOLDS["vix_fear"]
                    else ("안정" if vix_val <= self._EVIDENCE_THRESHOLDS["vix_calm"] else "주의")
                )
                evidence.append(f"VIX {vix_val:.1f} — {label} 구간")

        return evidence[:4]

    def _extract_sentiment_evidence(self, sentiment_result: dict[str, Any]) -> list[str]:
        """심리 관점에서 인용 가능한 증거를 추출한다."""
        evidence: list[str] = []
        bearish_kws = sentiment_result.get("dominant_bearish_kws", [])
        bullish_kws = sentiment_result.get("dominant_bullish_kws", [])
        negative_topics = sentiment_result.get("negative_topics", [])
        positive_topics = sentiment_result.get("positive_topics", [])
        sentiment_score = sentiment_result.get("sentiment_score", 0.0)
        verdict = sentiment_result.get("verdict", "중립")

        evidence.append(f"평균 심리 점수 {sentiment_score:+.3f} — {verdict}")

        if negative_topics:
            evidence.append(f"부정 토픽 {len(negative_topics)}건: {', '.join(negative_topics[:3])}")
        if positive_topics:
            evidence.append(f"긍정 토픽 {len(positive_topics)}건: {', '.join(positive_topics[:3])}")
        if bearish_kws:
            evidence.append(f"약세 키워드: {', '.join(bearish_kws[:3])}")
        if bullish_kws:
            evidence.append(f"강세 키워드: {', '.join(bullish_kws[:3])}")

        return evidence[:4]

    def _extract_macro_evidence(
        self,
        macro_result: dict[str, Any],
        macro_data: dict[str, Any] | None,
    ) -> list[str]:
        """매크로 관점에서 인용 가능한 증거를 추출한다."""
        evidence: list[str] = []
        if macro_data:
            us10y = macro_data.get("us10y")
            dxy = macro_data.get("dxy")
            vix = macro_data.get("vix")
            fed_rate = macro_data.get("fed_rate")

            if us10y is not None:
                trend = macro_data.get("us10y_trend", "stable")
                arrow = "↑" if trend == "rising" else ("↓" if trend == "falling" else "→")
                evidence.append(f"10년물 금리 {float(us10y):.2f}%{arrow}")
            if dxy is not None:
                trend = macro_data.get("dxy_trend", "stable")
                arrow = "↑" if trend == "rising" else ("↓" if trend == "falling" else "→")
                evidence.append(f"DXY {float(dxy):.1f}{arrow}")
            if vix is not None:
                evidence.append(f"VIX {float(vix):.1f}")
            if fed_rate is not None:
                evidence.append(f"Fed금리 {float(fed_rate):.2f}%")

        headwinds = macro_result.get("headwinds", [])
        if headwinds:
            evidence.append(f"헤드윈드: {headwinds[0].split(' — ')[0]}")

        return evidence[:4]
