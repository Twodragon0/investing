"""복합 신호 점수 엔진 — 다중 시장 지표를 종합해 전망을 산출한다.

Fear & Greed, VIX, 심리 점수, 모멘텀, 매크로, 기술적 지표를 가중 평균해
0-100 범위의 복합 점수와 시장 전망 버딕트를 생성한다.
외부 ML 모델 없이 규칙 기반(rule-based)으로만 동작한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from .config import setup_logging

logger = setup_logging("signal_composer")


# ── MiroFish 촉매 상수 ───────────────────────────────────────────────────────

_BULLISH_CATALYSTS: List[str] = [
    "연준 비둘기파 발언",
    "ETF 승인",
    "기관 대량 매수",
    "VIX 하락 안정화",
    "달러 약세 전환",
    "금리 인하 기대",
]

_BEARISH_CATALYSTS: List[str] = [
    "VIX 30 돌파",
    "규제 강화 발표",
    "대규모 해킹",
    "금리 인상 시사",
    "달러 강세 가속",
    "대량 매도 포착",
]


# ── 데이터 클래스 ────────────────────────────────────────────────────────────


@dataclass
class SignalResult:
    """개별 신호 정규화 결과."""

    name: str
    """신호 이름 (한글 레이블)."""
    raw_display: str
    """원시값 표시 문자열 (예: '45 (공포)')."""
    normalized: float
    """정규화 점수 0.0 (극도 약세) ~ 1.0 (극도 강세)."""
    verdict: str
    """신호 개별 판정: '강세' | '약세' | '중립' | '혼조'."""
    weight: float
    """배분 가중치 (0~1, 실제 사용 가중치)."""
    trend_arrow: str = ""
    """추세 화살표 (↑ / ↓ / →)."""


@dataclass
class ScenarioResult:
    """시나리오 하나의 정보."""

    label: str
    """시나리오 이름: '강세' | '기본' | '약세'."""
    emoji: str
    """시각 구분 이모지."""
    probability: int
    """발생 확률 (%)."""
    description: str
    """시나리오 설명."""
    catalysts: List[str] = field(default_factory=list)
    """이 시나리오를 촉발할 수 있는 촉매 목록 (MiroFish 패턴)."""
    time_horizon: str = ""
    """예상 시간 프레임 (예: '단기 1-3일', '중기 1-2주')."""
    support_level: str = ""
    """지지선 수준 추정 (선택적)."""
    resistance_level: str = ""
    """저항선 수준 추정 (선택적)."""


@dataclass
class StanceAnalysis:
    """시장 참여자 입장 분석 (MiroFish AgentActivityConfig 패턴)."""

    bulls: List[str]
    """강세 입장 요인 목록."""
    bears: List[str]
    """약세 입장 요인 목록."""
    observers: List[str]
    """관망 요인 목록."""
    dominant_stance: str
    """지배 입장: 'supportive' | 'opposing' | 'neutral' | 'observer'."""
    consensus_ratio: float
    """합의 비율 0~1."""


@dataclass
class CompositeResult:
    """compose_signals()의 최종 반환 객체."""

    score: float
    """종합 점수 0~100 (높을수록 강세)."""
    verdict: str
    """시장 전망: '강세' | '약세' | '중립' | '혼조'."""
    confidence: str
    """신뢰도: 'low' | 'medium' | 'high'."""
    confidence_label: str
    """신뢰도 한글: '낮음' | '보통' | '높음'."""
    signal_results: List[SignalResult] = field(default_factory=list)
    """처리된 개별 신호 리스트."""
    scenarios: List[ScenarioResult] = field(default_factory=list)
    """bull / base / bear 시나리오."""
    agreement_count: int = 0
    """주 방향에 동의한 신호 수."""
    total_signals: int = 0
    """처리된 신호 총 수."""


# ── 상수 ────────────────────────────────────────────────────────────────────

# 각 신호의 기본 가중치 (합계 = 1.0)
_DEFAULT_WEIGHTS: Dict[str, float] = {
    "fear_greed": 0.25,
    "vix": 0.20,
    "sentiment": 0.20,
    "momentum": 0.20,
    "macro": 0.10,
    "technical": 0.05,
}

# 정규화 점수 → 버딕트 임계값
_BULLISH_THRESHOLD = 0.60  # 이상 → 강세
_BEARISH_THRESHOLD = 0.40  # 이하 → 약세
# 나머지 → 중립

# 종합 점수 → 최종 버딕트
_SCORE_BULLISH = 62.0
_SCORE_BEARISH = 38.0
_SCORE_MIXED_HIGH = 55.0
_SCORE_MIXED_LOW = 45.0

# 신뢰도 기준: 일치 비율
_CONF_HIGH = 0.75  # 75% 이상 일치
_CONF_LOW = 0.50  # 50% 미만 일치


# ── 메인 클래스 ──────────────────────────────────────────────────────────────


class SignalComposer:
    """다중 시장 신호를 조합해 복합 전망 점수를 산출하는 엔진.

    사용 예::

        composer = SignalComposer()
        result = composer.compose_signals({
            "fear_greed": {"value": 45, "label": "Fear"},
            "vix": {"value": 22.5, "trend": "rising"},
            "sentiment": {"score": 0.3, "positive": 12, "negative": 8},
        })
        print(result.score, result.verdict)
        print(composer.generate_outlook_markdown(result))
    """

    def __init__(self, custom_weights: Optional[Dict[str, float]] = None) -> None:
        """초기화.

        Args:
            custom_weights: 신호별 가중치 오버라이드 딕셔너리.
                미제공 키는 기본값(_DEFAULT_WEIGHTS)을 사용한다.
        """
        self._weights = dict(_DEFAULT_WEIGHTS)
        if custom_weights:
            for key, val in custom_weights.items():
                if key in self._weights:
                    self._weights[key] = float(val)

    # ── 퍼블릭 API ──────────────────────────────────────────────────────────

    def compose_signals(self, signals: Dict[str, Any]) -> CompositeResult:
        """다중 신호를 입력받아 복합 전망 점수를 반환한다.

        Args:
            signals: 선택적 키를 포함하는 딕셔너리.
                누락된 신호는 자동으로 건너뛰고 나머지 가중치를 재분배한다.

        Returns:
            CompositeResult: 점수, 버딕트, 신뢰도, 시나리오 포함.
        """
        signal_results: List[SignalResult] = []

        # 각 신호 처리
        processors = {
            "fear_greed": self._process_fear_greed,
            "vix": self._process_vix,
            "sentiment": self._process_sentiment,
            "momentum": self._process_momentum,
            "macro": self._process_macro,
            "technical": self._process_technical,
        }

        for key, processor in processors.items():
            raw = signals.get(key)
            if raw is None:
                continue
            try:
                result = processor(raw, self._weights[key])
                signal_results.append(result)
                logger.debug("신호 처리 완료: %s → %.3f (%s)", key, result.normalized, result.verdict)
            except Exception as exc:
                logger.warning("신호 처리 오류 [%s]: %s", key, exc)

        if not signal_results:
            logger.warning("처리된 신호가 없습니다. 기본값 반환.")
            return self._default_result()

        # 가중치 재정규화 (누락 신호 보정)
        self._renormalize_weights(signal_results)

        # 복합 점수 계산
        score = self._calculate_weighted_score(signal_results)

        # 버딕트 결정
        verdict = self._determine_verdict(score, signal_results)

        # 신뢰도 계산
        confidence, confidence_label, agreement_count = self._calculate_confidence(signal_results, verdict)

        # 시나리오 생성
        scenarios = self._generate_scenarios(score, verdict, signal_results)

        return CompositeResult(
            score=round(score, 1),
            verdict=verdict,
            confidence=confidence,
            confidence_label=confidence_label,
            signal_results=signal_results,
            scenarios=scenarios,
            agreement_count=agreement_count,
            total_signals=len(signal_results),
        )

    def analyze_stance(self, result: CompositeResult) -> StanceAnalysis:
        """개별 신호의 방향성을 분석하여 시장 참여자 입장을 추론한다.

        MiroFish의 AgentActivityConfig에서 영감: 각 지표를 시장 참여자의
        '입장(stance)'으로 해석한다.

        Args:
            result: compose_signals()의 반환값.

        Returns:
            StanceAnalysis: 강세/약세/관망 진영 분류 및 지배 입장.
        """
        bulls: List[str] = []
        bears: List[str] = []
        observers: List[str] = []

        for sr in result.signal_results:
            entry = f"{sr.name} ({sr.raw_display})"
            if sr.verdict == "강세":
                bulls.append(entry)
            elif sr.verdict == "약세":
                bears.append(entry)
            else:
                observers.append(entry)

        bull_count = len(bulls)
        bear_count = len(bears)
        obs_count = len(observers)
        total = bull_count + bear_count + obs_count

        if total == 0:
            return StanceAnalysis(
                bulls=bulls,
                bears=bears,
                observers=observers,
                dominant_stance="neutral",
                consensus_ratio=0.0,
            )

        # sentiment_bias 스타일 (-1.0 ~ 1.0): 강세 vs 약세 편향
        sentiment_bias = (bull_count - bear_count) / total  # -1.0 ~ 1.0

        if sentiment_bias >= 0.3:
            dominant_stance = "supportive"
            consensus_ratio = bull_count / total
        elif sentiment_bias <= -0.3:
            dominant_stance = "opposing"
            consensus_ratio = bear_count / total
        elif obs_count >= max(bull_count, bear_count):
            dominant_stance = "observer"
            consensus_ratio = obs_count / total
        else:
            dominant_stance = "neutral"
            # 중립: 어느 쪽도 지배하지 않음 → 가장 많은 진영 비율
            consensus_ratio = max(bull_count, bear_count, obs_count) / total

        return StanceAnalysis(
            bulls=bulls,
            bears=bears,
            observers=observers,
            dominant_stance=dominant_stance,
            consensus_ratio=round(consensus_ratio, 2),
        )

    def generate_prediction_markdown(
        self,
        result: CompositeResult,
        stance: StanceAnalysis,
    ) -> str:
        """MiroFish 스타일의 예측 분석 마크다운을 생성한다.

        기존 generate_outlook_markdown보다 상세한 예측 정보를 포함:
        - 시장 참여자 입장 분석 (MiroFish stance 패턴)
        - 시나리오별 촉매(catalyst) 분석
        - 시간 프레임 전망

        Args:
            result: compose_signals()의 반환값.
            stance: analyze_stance()의 반환값.

        Returns:
            str: 마크다운 형식의 상세 시장 전망 섹션.
        """
        lines: List[str] = []

        lines.append("## 시장 전망 분석")
        lines.append("")

        # 신호 테이블
        lines.append("| 지표 | 현재값 | 신호 | 가중치 |")
        lines.append("|------|--------|------|--------|")
        for sr in result.signal_results:
            weight_pct = f"{sr.weight * 100:.0f}%"
            display = sr.raw_display
            if sr.trend_arrow:
                display = f"{display} {sr.trend_arrow}"
            lines.append(f"| {sr.name} | {display} | {sr.verdict} | {weight_pct} |")

        lines.append("")

        # 종합 점수
        verdict_score_label = _verdict_with_icon(result.verdict)
        lines.append(f"**종합 점수**: {result.score:.0f}/100 ({verdict_score_label})")

        # 신뢰도
        agree_str = f"{result.agreement_count}/{result.total_signals} 지표 일치"
        lines.append(f"**신뢰도**: {result.confidence_label} ({agree_str})")

        lines.append("")

        # ── 시장 참여자 입장 분석 ──────────────────────────────────────────────
        lines.append("### 시장 참여자 입장 분석")

        bulls_str = ", ".join(stance.bulls) if stance.bulls else "없음"
        bears_str = ", ".join(stance.bears) if stance.bears else "없음"
        obs_str = ", ".join(stance.observers) if stance.observers else "없음"

        lines.append(f"- **강세 진영**: {bulls_str}")
        lines.append(f"- **약세 진영**: {bears_str}")
        lines.append(f"- **관망**: {obs_str}")

        dominant_label_map = {
            "supportive": "강세",
            "opposing": "약세",
            "neutral": "중립",
            "observer": "관망",
        }
        dominant_kr = dominant_label_map.get(stance.dominant_stance, stance.dominant_stance)
        consensus_pct = int(stance.consensus_ratio * 100)
        lines.append(f"- **지배 입장**: {dominant_kr} ({consensus_pct}% 합의)")

        lines.append("")

        # ── 시나리오 분석 ──────────────────────────────────────────────────────
        lines.append("### 시나리오 분석")

        for scenario in result.scenarios:
            lines.append(
                f"- {scenario.emoji} **{scenario.label} 시나리오** ({scenario.probability}%): {scenario.description}"
            )
            if scenario.catalysts:
                catalyst_str = ", ".join(scenario.catalysts)
                lines.append(f"  - *촉매*: {catalyst_str}")
            if scenario.time_horizon:
                lines.append(f"  - *시간 프레임*: {scenario.time_horizon}")
            if scenario.support_level:
                lines.append(f"  - *지지선*: {scenario.support_level}")
            if scenario.resistance_level:
                lines.append(f"  - *저항선*: {scenario.resistance_level}")

        lines.append("")
        lines.append("> ⚠️ 본 분석은 알고리즘 기반 자동 생성이며, 투자 조언이 아닙니다.")

        return "\n".join(lines)

    def generate_outlook_markdown(self, result: CompositeResult) -> str:
        """CompositeResult를 Jekyll 포스트 삽입용 마크다운으로 변환한다.

        Args:
            result: compose_signals()의 반환값.

        Returns:
            str: 마크다운 형식의 시장 전망 섹션.
        """
        lines: List[str] = []

        lines.append("## 시장 전망 분석")
        lines.append("")

        # 신호 테이블
        lines.append("| 지표 | 현재값 | 신호 | 가중치 |")
        lines.append("|------|--------|------|--------|")
        for sr in result.signal_results:
            weight_pct = f"{sr.weight * 100:.0f}%"
            display = sr.raw_display
            if sr.trend_arrow:
                display = f"{display} {sr.trend_arrow}"
            lines.append(f"| {sr.name} | {display} | {sr.verdict} | {weight_pct} |")

        lines.append("")

        # 종합 점수
        verdict_score_label = _verdict_with_icon(result.verdict)
        lines.append(f"**종합 점수**: {result.score:.0f}/100 ({verdict_score_label})")

        # 신뢰도
        agree_str = f"{result.agreement_count}/{result.total_signals} 지표 일치"
        lines.append(f"**신뢰도**: {result.confidence_label} ({agree_str})")

        lines.append("")
        lines.append("### 시나리오 분석")

        for scenario in result.scenarios:
            lines.append(
                f"- {scenario.emoji} **{scenario.label} 시나리오** ({scenario.probability}%): {scenario.description}"
            )

        lines.append("")
        lines.append("> ⚠️ 본 분석은 알고리즘 기반 자동 생성이며, 투자 조언이 아닙니다.")

        return "\n".join(lines)

    # ── 신호 정규화 (개별) ──────────────────────────────────────────────────

    def _normalize_signal(self, name: str, value: float) -> float:
        """개별 신호 값을 0.0~1.0 범위로 정규화한다.

        각 신호 유형별로 적합한 변환식을 적용한다.
        반환값이 높을수록 강세(bullish) 신호다.

        Args:
            name: 신호 식별자 ('fear_greed', 'vix', 등).
            value: 원시 수치값.

        Returns:
            float: 0.0~1.0 범위의 정규화 점수.
        """
        value = float(value)

        if name == "fear_greed":
            # Fear & Greed: 0(극공포)~100(극탐욕) → 직접 정규화
            return float(np.clip(value / 100.0, 0.0, 1.0))

        if name == "vix":
            # VIX: 낮을수록 강세 (10=안정, 40=패닉)
            # 10 이하 → 1.0, 40 이상 → 0.0
            normalized = 1.0 - (value - 10.0) / 30.0
            return float(np.clip(normalized, 0.0, 1.0))

        if name == "sentiment":
            # 감성 점수: -1.0(극부정)~1.0(극긍정) → 0~1 변환
            return float(np.clip((value + 1.0) / 2.0, 0.0, 1.0))

        if name == "rsi":
            # RSI: 30(과매도)~70(과매수) → 중간(50) = 0.5
            return float(np.clip(value / 100.0, 0.0, 1.0))

        if name == "momentum_pct":
            # 수익률 %: -20% → 0.0, +20% → 1.0
            normalized = (value + 20.0) / 40.0
            return float(np.clip(normalized, 0.0, 1.0))

        # 알 수 없는 신호: 0.5(중립) 반환
        logger.debug("미지원 신호 정규화 '%s': 0.5 반환", name)
        return 0.5

    # ── 개별 신호 프로세서 ──────────────────────────────────────────────────

    def _process_fear_greed(self, data: Dict[str, Any], base_weight: float) -> SignalResult:
        """Fear & Greed 지수 처리."""
        value = float(data.get("value", 50))
        label = data.get("label", "")

        normalized = self._normalize_signal("fear_greed", value)
        verdict = _score_to_verdict(normalized)

        # 레이블 한글화
        label_kr = _fg_label_korean(label, value)
        raw_display = f"{value:.0f} ({label_kr})"

        return SignalResult(
            name="공포·탐욕 지수",
            raw_display=raw_display,
            normalized=normalized,
            verdict=verdict,
            weight=base_weight,
        )

    def _process_vix(self, data: Dict[str, Any], base_weight: float) -> SignalResult:
        """VIX 변동성 지수 처리."""
        value = float(data.get("value", 20))
        trend = data.get("trend", "")

        normalized = self._normalize_signal("vix", value)

        # 추세 반영: rising VIX는 추가 약세 신호
        if trend in ("rising", "up"):
            normalized = max(0.0, normalized - 0.05)
            trend_arrow = "↑"
        elif trend in ("falling", "down"):
            normalized = min(1.0, normalized + 0.05)
            trend_arrow = "↓"
        else:
            trend_arrow = "→"

        verdict = _score_to_verdict(normalized)
        raw_display = f"{value:.1f}"

        return SignalResult(
            name="VIX 변동성",
            raw_display=raw_display,
            normalized=normalized,
            verdict=verdict,
            weight=base_weight,
            trend_arrow=trend_arrow,
        )

    def _process_sentiment(self, data: Dict[str, Any], base_weight: float) -> SignalResult:
        """뉴스 감성 점수 처리."""
        score = float(data.get("score", 0.0))
        positive = int(data.get("positive", 0))
        negative = int(data.get("negative", 0))

        # 긍/부정 기사 비율도 반영
        total = positive + negative
        if total > 0:
            ratio_score = positive / total  # 0~1
            # 텍스트 점수와 50:50 혼합
            blended = score * 0.5 + (ratio_score - 0.5) * 0.5 + 0.5 * 0.5
            blended = np.clip(blended, -1.0, 1.0)
        else:
            blended = score

        normalized = self._normalize_signal("sentiment", float(blended))
        verdict = _score_to_verdict(normalized)

        sign = "+" if score >= 0 else ""
        raw_display = f"{sign}{score:.2f}"

        return SignalResult(
            name="시장 심리",
            raw_display=raw_display,
            normalized=normalized,
            verdict=verdict,
            weight=base_weight,
        )

    def _process_momentum(self, data: Dict[str, Any], base_weight: float) -> SignalResult:
        """모멘텀 지표 처리 (BTC, ETH, S&P500 등 수익률 평균)."""
        pct_values: List[float] = []
        display_parts: List[str] = []

        field_labels = {
            "btc_7d": "BTC",
            "eth_7d": "ETH",
            "sp500_5d": "S&P",
            "btc_24h": "BTC",
            "eth_24h": "ETH",
        }

        for field_key, label in field_labels.items():
            val = data.get(field_key)
            if val is not None:
                pct_values.append(float(val))
                sign = "+" if float(val) >= 0 else ""
                display_parts.append(f"{label} {sign}{float(val):.1f}%")

        # 직접 제공된 평균값
        avg_val = data.get("avg")
        if avg_val is not None and not pct_values:
            pct_values = [float(avg_val)]

        if not pct_values:
            return SignalResult(
                name="모멘텀",
                raw_display="N/A",
                normalized=0.5,
                verdict="중립",
                weight=base_weight,
            )

        avg_pct = float(np.mean(pct_values))
        normalized = self._normalize_signal("momentum_pct", avg_pct)
        verdict = _score_to_verdict(normalized)

        raw_display = " / ".join(display_parts[:2]) if display_parts else f"{avg_pct:+.1f}%"

        return SignalResult(
            name="모멘텀",
            raw_display=raw_display,
            normalized=normalized,
            verdict=verdict,
            weight=base_weight,
        )

    def _process_macro(self, data: Dict[str, Any], base_weight: float) -> SignalResult:
        """매크로 지표 처리 (금리, DXY, 연준 금리 등)."""
        sub_scores: List[float] = []
        display_parts: List[str] = []

        # 미국 10년물 금리: 4.5% 이하 우호적, 5% 이상 부담
        us10y = data.get("us10y")
        if us10y is not None:
            us10y = float(us10y)
            score = 1.0 - np.clip((us10y - 3.5) / 2.0, 0.0, 1.0)
            sub_scores.append(float(score))
            display_parts.append(f"10Y {us10y:.2f}%")

        # DXY 달러지수: 강달러(높음)는 신흥시장/크립토에 부정적
        dxy = data.get("dxy")
        if dxy is not None:
            dxy = float(dxy)
            score = 1.0 - np.clip((dxy - 95.0) / 20.0, 0.0, 1.0)
            sub_scores.append(float(score))
            display_parts.append(f"DXY {dxy:.1f}")

        # 연준 기준금리: 높을수록 유동성 압박
        fed_rate = data.get("fed_rate")
        if fed_rate is not None:
            fed_rate = float(fed_rate)
            score = 1.0 - np.clip((fed_rate - 2.0) / 4.0, 0.0, 1.0)
            sub_scores.append(float(score))

        if not sub_scores:
            return SignalResult(
                name="매크로",
                raw_display="N/A",
                normalized=0.5,
                verdict="중립",
                weight=base_weight,
            )

        normalized = float(np.mean(sub_scores))
        normalized = float(np.clip(normalized, 0.0, 1.0))
        verdict = _score_to_verdict(normalized)

        raw_display = " / ".join(display_parts[:2]) if display_parts else "매크로 데이터"

        return SignalResult(
            name="매크로",
            raw_display=raw_display,
            normalized=normalized,
            verdict=verdict,
            weight=base_weight,
        )

    def _process_technical(self, data: Dict[str, Any], base_weight: float) -> SignalResult:
        """기술적 지표 처리 (RSI, MACD, 이동평균 등)."""
        sub_scores: List[float] = []

        # RSI: 30~70 범위
        rsi = data.get("rsi_14")
        if rsi is not None:
            rsi = float(rsi)
            # RSI 50 근방 = 중립, 30 이하 = 과매도(반등 기회), 70 이상 = 과매수(하락 위험)
            # 점수 계산: 50이 0.5, 30 이하는 0.35(약세 추세 중 과매도), 70 이상은 0.65
            if rsi <= 30:
                score = 0.35  # 약세이나 반등 가능
            elif rsi >= 70:
                score = 0.65  # 강세이나 과매수 경계
            else:
                score = self._normalize_signal("rsi", rsi)
            sub_scores.append(float(score))

        # MACD 신호
        macd_signal = str(data.get("macd_signal", "")).lower()
        if macd_signal in ("bullish", "강세", "golden"):
            sub_scores.append(0.72)
        elif macd_signal in ("bearish", "약세", "death"):
            sub_scores.append(0.28)
        elif macd_signal in ("neutral", "중립"):
            sub_scores.append(0.50)

        # 이동평균 크로스
        ma_cross = str(data.get("ma_cross", "")).lower()
        if ma_cross in ("golden", "golden cross", "golden_cross"):
            sub_scores.append(0.75)
        elif ma_cross in ("death", "dead", "death cross", "death_cross"):
            sub_scores.append(0.25)

        if not sub_scores:
            return SignalResult(
                name="기술적 지표",
                raw_display="N/A",
                normalized=0.5,
                verdict="중립",
                weight=base_weight,
            )

        normalized = float(np.mean(sub_scores))
        normalized = float(np.clip(normalized, 0.0, 1.0))
        verdict = _score_to_verdict(normalized)

        # 표시값 구성
        display_parts: List[str] = []
        if rsi is not None:
            display_parts.append(f"RSI {rsi:.0f}")
        if macd_signal:
            display_parts.append(f"MACD {macd_signal}")
        raw_display = " / ".join(display_parts) if display_parts else "기술적"

        return SignalResult(
            name="기술적 지표",
            raw_display=raw_display,
            normalized=normalized,
            verdict=verdict,
            weight=base_weight,
        )

    # ── 집계 로직 ────────────────────────────────────────────────────────────

    def _renormalize_weights(self, results: List[SignalResult]) -> None:
        """누락 신호로 인한 가중치 불균형을 재정규화한다.

        리스트 내 SignalResult.weight를 합계 1.0이 되도록 인플레이스 수정한다.
        """
        total = sum(r.weight for r in results)
        if total <= 0:
            equal = 1.0 / len(results)
            for r in results:
                r.weight = equal
        else:
            for r in results:
                r.weight = r.weight / total

    def _calculate_weighted_score(self, results: List[SignalResult]) -> float:
        """정규화된 신호들의 가중 평균을 0~100 점수로 반환한다."""
        total = sum(r.normalized * r.weight for r in results)
        return float(np.clip(total * 100.0, 0.0, 100.0))

    def _determine_verdict(self, score: float, results: List[SignalResult]) -> str:
        """종합 점수와 신호 분포를 고려해 최종 버딕트를 결정한다.

        Returns:
            '강세' | '약세' | '중립' | '혼조'
        """
        if score >= _SCORE_BULLISH:
            return "강세"
        if score <= _SCORE_BEARISH:
            return "약세"

        # 중간 구간: 신호 분포로 혼조 여부 판단
        bull_count = sum(1 for r in results if r.verdict == "강세")
        bear_count = sum(1 for r in results if r.verdict == "약세")

        if bull_count > 0 and bear_count > 0:
            return "혼조"

        if score >= _SCORE_MIXED_HIGH:
            return "강세"
        if score <= _SCORE_MIXED_LOW:
            return "약세"
        return "중립"

    def _calculate_confidence(self, results: List[SignalResult], verdict: str) -> Tuple[str, str, int]:
        """신호 일치도 기반 신뢰도를 계산한다.

        Args:
            results: 개별 신호 결과 리스트.
            verdict: 최종 버딕트.

        Returns:
            Tuple[str, str, int]: (confidence_key, confidence_label_kr, agreement_count)
        """
        n = len(results)
        if n == 0:
            return "low", "낮음", 0

        # 주 버딕트와 같은 방향 신호 개수
        # 혼조는 별도 처리
        direction_map = {"강세": "강세", "약세": "약세", "혼조": None, "중립": "중립"}
        main_dir = direction_map.get(verdict)

        if main_dir is None:
            # 혼조: 강세/약세가 섞인 경우 → 자동 medium
            return "medium", "보통", n // 2

        agreement = sum(1 for r in results if r.verdict == main_dir or r.verdict == "중립")
        ratio = agreement / n

        if ratio >= _CONF_HIGH:
            return "high", "높음", agreement
        if ratio >= _CONF_LOW:
            return "medium", "보통", agreement
        return "low", "낮음", agreement

    def _generate_scenarios(
        self,
        score: float,
        verdict: str,
        results: List[SignalResult],
    ) -> List[ScenarioResult]:
        """현재 신호 수준을 기반으로 bull/base/bear 시나리오를 생성한다.

        Args:
            score: 종합 점수 (0~100).
            verdict: 최종 버딕트.
            results: 개별 신호 결과.

        Returns:
            List[ScenarioResult]: [강세, 기본, 약세] 순서.
        """
        # 기본 확률 배분: 버딕트에 따라 기본 시나리오 확률 조정
        if verdict == "강세":
            probs = {"bull": 40, "base": 45, "bear": 15}
        elif verdict == "약세":
            probs = {"bull": 15, "base": 45, "bear": 40}
        elif verdict == "혼조":
            probs = {"bull": 25, "base": 50, "bear": 25}
        else:  # 중립
            probs = {"bull": 25, "base": 50, "bear": 25}

        # 신호에서 핵심 정보 추출 (설명 생성용)
        fg_result = next((r for r in results if r.name == "공포·탐욕 지수"), None)
        vix_result = next((r for r in results if r.name == "VIX 변동성"), None)
        momentum_result = next((r for r in results if r.name == "모멘텀"), None)
        macro_result = next((r for r in results if r.name == "매크로"), None)

        fg_display = fg_result.raw_display if fg_result else "N/A"
        vix_display = vix_result.raw_display if vix_result else "N/A"
        momentum_display = momentum_result.raw_display if momentum_result else "N/A"

        # ── 시간 프레임 결정 (모멘텀 강도 기반) ──────────────────────────────
        # 모멘텀 normalized 값으로 단기/중기 구분
        if momentum_result:
            mom_norm = momentum_result.normalized
            if abs(mom_norm - 0.5) > 0.2:  # 강한 방향성
                bull_horizon = "중기 1-2주 내 추세 지속 가능"
                base_horizon = "단기 1-3일 관망 후 방향 확인"
                bear_horizon = "단기 1-3일 내 압박 지속"
            else:  # 약한 방향성
                bull_horizon = "단기 1-3일 내 확인 가능"
                base_horizon = "중기 1-2주 횡보 예상"
                bear_horizon = "중기 1-2주 내 약세 전환 가능성"
        else:
            bull_horizon = "단기 1-3일 내 확인 가능"
            base_horizon = "중기 1-2주 방향 모색"
            bear_horizon = "단기 1-3일 내 압박 지속"

        # ── VIX 기반 지지/저항 수준 추정 ─────────────────────────────────────
        # VIX가 높으면 변동폭 확대 → 더 넓은 지지/저항 범위
        vix_val = float(vix_result.raw_display.split()[0]) if vix_result else 20.0
        try:
            vix_val = float(str(vix_result.raw_display).split()[0]) if vix_result else 20.0
        except (ValueError, IndexError):
            vix_val = 20.0

        # 점수 기반 레벨 표현 (구체적 가격 없이 상대적 수준)
        if score >= 55:
            support_est = "현재가 -3~5%"
            resistance_est = "현재가 +5~8%"
        elif score <= 45:
            support_est = "현재가 -5~8%"
            resistance_est = "현재가 +3~5%"
        else:
            support_est = "현재가 -3~4%"
            resistance_est = "현재가 +3~4%"

        if vix_val >= 25:  # 고변동성 → 범위 확대
            support_est = support_est.replace("3~5", "5~8").replace("5~8", "8~12").replace("3~4", "4~6")
            resistance_est = resistance_est.replace("5~8", "8~12").replace("3~5", "5~8").replace("3~4", "4~6")

        # ── 촉매 선택 (MiroFish 패턴) ─────────────────────────────────────────
        # 약세 신호가 많을수록 강세 시나리오에 더 많은 촉매 필요
        bear_signals = sum(1 for r in results if r.verdict == "약세")
        bull_signals = sum(1 for r in results if r.verdict == "강세")

        # 강세 시나리오 촉매: 주로 상승 전환 필요 조건
        bull_catalyst_pool = list(_BULLISH_CATALYSTS)
        if vix_result and vix_result.verdict == "약세":
            bull_catalyst_pool = ["VIX 하락 안정화"] + [c for c in bull_catalyst_pool if c != "VIX 하락 안정화"]
        if macro_result and macro_result.verdict == "약세":
            bull_catalyst_pool = ["달러 약세 전환", "금리 인하 기대"] + [
                c for c in bull_catalyst_pool if c not in ("달러 약세 전환", "금리 인하 기대")
            ]
        bull_catalysts = bull_catalyst_pool[: min(2, max(1, bear_signals))]

        # 약세 시나리오 촉매: 현재 약세 신호 악화
        bear_catalyst_pool = list(_BEARISH_CATALYSTS)
        if vix_result and vix_result.verdict == "약세":
            bear_catalyst_pool = ["VIX 30 돌파"] + [c for c in bear_catalyst_pool if c != "VIX 30 돌파"]
        if macro_result and macro_result.verdict == "약세":
            bear_catalyst_pool = ["달러 강세 가속"] + [c for c in bear_catalyst_pool if c != "달러 강세 가속"]
        bear_catalysts = bear_catalyst_pool[: min(2, max(1, bull_signals))]

        bull_desc = (
            f"공포·탐욕 지수({fg_display}) 반등 시 위험자산 선호 회복, "
            f"VIX({vix_display}) 안정화되며 기술적 저항선 돌파 가능"
        )
        base_desc = f"현 심리 수준({score:.0f}점) 유지, 모멘텀({momentum_display}) 방향 확인 후 점진적 포지션 조정 권장"
        bear_desc = (
            f"VIX({vix_display}) 추가 상승 및 매크로 압박 지속 시 "
            f"추가 조정 가능, 공포·탐욕({fg_display}) 극공포 구간 진입 주의"
        )

        return [
            ScenarioResult(
                label="강세",
                emoji="🟢",
                probability=probs["bull"],
                description=bull_desc,
                catalysts=bull_catalysts,
                time_horizon=bull_horizon,
                resistance_level=resistance_est,
            ),
            ScenarioResult(
                label="기본",
                emoji="🟡",
                probability=probs["base"],
                description=base_desc,
                time_horizon=base_horizon,
            ),
            ScenarioResult(
                label="약세",
                emoji="🔴",
                probability=probs["bear"],
                description=bear_desc,
                catalysts=bear_catalysts,
                time_horizon=bear_horizon,
                support_level=support_est,
            ),
        ]

    @staticmethod
    def _default_result() -> CompositeResult:
        """신호가 없을 때 반환하는 기본 결과."""
        return CompositeResult(
            score=50.0,
            verdict="중립",
            confidence="low",
            confidence_label="낮음",
            signal_results=[],
            scenarios=[
                ScenarioResult(
                    label="강세", emoji="🟢", probability=25, description="데이터 부족으로 시나리오 생성 불가"
                ),
                ScenarioResult(label="기본", emoji="🟡", probability=50, description="시장 중립 유지 가정"),
                ScenarioResult(
                    label="약세", emoji="🔴", probability=25, description="데이터 부족으로 시나리오 생성 불가"
                ),
            ],
            agreement_count=0,
            total_signals=0,
        )


# ── 모듈 수준 헬퍼 함수 ────────────────────────────────────────────────────


def _score_to_verdict(normalized: float) -> str:
    """정규화 점수(0~1)를 버딕트 문자열로 변환한다."""
    if normalized >= _BULLISH_THRESHOLD:
        return "강세"
    if normalized <= _BEARISH_THRESHOLD:
        return "약세"
    return "중립"


def _fg_label_korean(label: str, value: float) -> str:
    """Fear & Greed 영문 레이블을 한글로 변환한다."""
    label_lower = label.lower()
    mapping = {
        "extreme fear": "극공포",
        "fear": "공포",
        "neutral": "중립",
        "greed": "탐욕",
        "extreme greed": "극탐욕",
    }
    if label_lower in mapping:
        return mapping[label_lower]
    # 레이블 없으면 수치 기반 추정
    if value < 25:
        return "극공포"
    if value < 45:
        return "공포"
    if value < 55:
        return "중립"
    if value < 75:
        return "탐욕"
    return "극탐욕"


def _verdict_with_icon(verdict: str) -> str:
    """버딕트에 아이콘을 붙인 표시 문자열을 반환한다."""
    icons = {"강세": "📈 강세", "약세": "📉 약세", "중립": "➡️ 중립", "혼조": "↔️ 혼조"}
    return icons.get(verdict, verdict)


# ── 편의 함수 (모듈 레벨 진입점) ─────────────────────────────────────────


def compose_signals(signals: Dict[str, Any], weights: Optional[Dict[str, float]] = None) -> CompositeResult:
    """SignalComposer를 인스턴스화 없이 사용하는 편의 함수.

    Args:
        signals: 신호 딕셔너리 (SignalComposer.compose_signals 참조).
        weights: 선택적 가중치 오버라이드.

    Returns:
        CompositeResult
    """
    return SignalComposer(custom_weights=weights).compose_signals(signals)


def generate_outlook_markdown(result: CompositeResult) -> str:
    """CompositeResult → 마크다운 편의 함수."""
    return SignalComposer().generate_outlook_markdown(result)


def analyze_stance(result: CompositeResult) -> StanceAnalysis:
    """CompositeResult → StanceAnalysis 편의 함수."""
    return SignalComposer().analyze_stance(result)


def generate_prediction_markdown(result: CompositeResult, stance: StanceAnalysis) -> str:
    """CompositeResult + StanceAnalysis → MiroFish 스타일 마크다운 편의 함수."""
    return SignalComposer().generate_prediction_markdown(result, stance)
