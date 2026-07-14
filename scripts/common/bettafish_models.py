"""BettaFish 분석 엔진의 데이터 클래스와 순수 헬퍼.

`bettafish_analyzer.py`의 leaf 계층으로, 외부 의존이 없는 데이터 구조체
(`ReportChapter`, `AnalysisReport`)와 버딕트/점수 변환 헬퍼를 보유한다.
상위 모듈(perspectives/insight/synthesis/analyzer)은 이 모듈만 의존한다.

`bettafish_analyzer.py`가 상단에서 이 심볼들을 재-export하므로
`from common.bettafish_analyzer import AnalysisReport` 등 기존 import 경로는
변경 없이 동작한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ── 데이터 클래스 ─────────────────────────────────────────────────────────────


@dataclass
class ReportChapter:
    """MiroFish ReportSection 패턴을 차용한 챕터별 분석 구조체.

    각 관점의 분석 결과를 증거 인용과 하위 질문 답변을 포함해 구조화한다.
    """

    title: str
    """챕터 제목 (예: '데이터 분석 (InsightAgent)')."""

    content: str
    """챕터 본문 서사."""

    evidence: list[str]
    """인용된 데이터 포인트 목록 (예: ['공포·탐욕 지수 45 — 공포 구간, 가중치 25%'])."""

    sub_questions: list[str]
    """분해된 핵심 하위 질문 목록."""

    verdict: str
    """챕터 판정: '강세' | '약세' | '중립' | '혼조'."""


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

    chapters: list[ReportChapter] = field(default_factory=list)
    """InsightForge가 생성한 챕터별 분석 구조체 목록."""

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
