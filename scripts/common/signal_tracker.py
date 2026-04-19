"""신호 추적기 — 일별 복합 신호 결과를 저장하고 정확도를 추적한다.

SignalComposer의 CompositeResult를 _state/signal_history.json에 기록하고,
전날 예측과 실제 가격 움직임을 비교하여 정확도 통계를 산출한다.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from .config import setup_logging
from .time_series_state import TimeSeriesSchema, TimeSeriesStore

if TYPE_CHECKING:
    from .signal_composer import CompositeResult

logger = setup_logging("signal_tracker")

# repo root: scripts/common/ 로부터 두 단계 위
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_STATE_DIR = os.path.join(_REPO_ROOT, "_state")
_HISTORY_FILE = os.path.join(_STATE_DIR, "signal_history.json")

# 히스토리 보존 기간 (일)
_MAX_AGE_DAYS = 365

# ── TimeSeriesStore 스키마 및 인스턴스 ──────────────────────────────────────────

_SIGNAL_SCHEMA = TimeSeriesSchema(
    required_fields=["date"],  # btc_price는 nullable이므로 required에 포함 안 함
    numeric_fields={},  # btc_price bound는 두지 않음 (null 허용)
    date_field="date",
    date_format="%Y-%m-%d",
    max_entries=365,  # 1년 히스토리
    allow_null_fields=["btc_price"],
    extra_fields_allowed=True,  # accuracy 중첩 필드 허용
)

_SIGNAL_STORE = TimeSeriesStore(Path(_HISTORY_FILE), _SIGNAL_SCHEMA, logger)


# ── 데이터 클래스 ────────────────────────────────────────────────────────────


@dataclass
class SignalSnapshot:
    """하루치 신호 스냅샷."""

    date: str
    """YYYY-MM-DD 형식 날짜."""
    composite_score: float
    """복합 점수 0~100."""
    verdict: str
    """시장 전망: '강세' | '약세' | '중립' | '혼조'."""
    confidence: str
    """신뢰도: 'low' | 'medium' | 'high'."""
    signal_scores: Dict[str, float] = field(default_factory=dict)
    """개별 신호 정규화 점수 {signal_name: normalized_score}."""
    btc_price: Optional[float] = None
    """당일 BTC 가격 (USD). 없으면 None."""
    recorded_at: str = ""
    """기록 시각 ISO 8601."""


@dataclass
class AccuracyRecord:
    """전날 예측 vs 실제 결과 비교 레코드."""

    date: str
    """YYYY-MM-DD 형식 날짜 (검증 대상일)."""
    predicted_verdict: str
    """예측 버딕트 (전날 저장된 verdict)."""
    predicted_score: float
    """예측 복합 점수."""
    actual_price_change_pct: Optional[float]
    """실제 BTC 가격 변동률 (%). 없으면 None."""
    actual_direction: Optional[str]
    """실제 방향: '상승' | '하락' | '보합'. 없으면 None."""
    correct: Optional[bool]
    """예측 일치 여부. 데이터 부족 시 None."""


@dataclass
class AccuracyReport:
    """정확도 집계 리포트."""

    total_predictions: int
    """평가 가능한 예측 총 수."""
    correct_predictions: int
    """올바른 예측 수."""
    win_rate: float
    """적중률 0.0~1.0."""
    by_verdict: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    """버딕트 유형별 통계 {'강세': {'total': N, 'correct': M, 'win_rate': R}, ...}."""
    recent_accuracy: List[AccuracyRecord] = field(default_factory=list)
    """최근 30일 정확도 레코드."""
    avg_score_error: Optional[float] = None
    """평균 복합 점수와 실제 방향 간 평균 오차 (참고용)."""


# ── 내부 헬퍼 ─────────────────────────────────────────────────────────────────


def _load_history(path: str) -> List[Dict[str, Any]]:
    """히스토리 JSON 파일을 로드한다. 오류 시 빈 리스트 반환.

    TimeSeriesStore.load()에 위임한다. 기존 호출자 호환성을 위해 유지.
    """
    store = TimeSeriesStore(Path(path), _SIGNAL_SCHEMA, logger)
    return store.load(validate=False)


def _save_history(path: str, entries: List[Dict[str, Any]]) -> None:
    """히스토리를 원자적 쓰기(os.replace)로 저장한다.

    TimeSeriesStore._write_atomic()에 위임한다. 기존 호출자 호환성을 위해 유지.
    """
    store = TimeSeriesStore(Path(path), _SIGNAL_SCHEMA, logger)
    store._write_atomic(entries)
    logger.debug("signal_history.json 저장 완료 (%d 항목)", len(entries))


def _prune_old_entries(entries: List[Dict[str, Any]], max_age_days: int = _MAX_AGE_DAYS) -> List[Dict[str, Any]]:
    """max_age_days 이전 항목을 제거한다."""
    cutoff = (datetime.now(UTC) - timedelta(days=max_age_days)).strftime("%Y-%m-%d")
    pruned = [e for e in entries if e.get("date", "") >= cutoff]
    removed = len(entries) - len(pruned)
    if removed:
        logger.info("signal_history: %d개 오래된 항목 제거 (cutoff=%s)", removed, cutoff)
    return pruned


def _verdict_to_direction(verdict: str) -> Optional[str]:
    """버딕트를 방향으로 변환한다. 혼조/중립은 None 반환 (평가 불가)."""
    if verdict == "강세":
        return "상승"
    if verdict == "약세":
        return "하락"
    return None  # 중립·혼조는 명확한 방향 예측 없음


def _price_direction(change_pct: float) -> str:
    """가격 변동률을 방향 레이블로 변환한다."""
    if change_pct > 1.0:
        return "상승"
    if change_pct < -1.0:
        return "하락"
    return "보합"


# ── 메인 클래스 ──────────────────────────────────────────────────────────────


class SignalTracker:
    """일별 신호 결과 저장 및 정확도 추적 클래스.

    사용 예::

        tracker = SignalTracker()
        tracker.record(composite_result, btc_price=95000.0)
        report = tracker.accuracy_report()
        print(f"승률: {report.win_rate:.1%}")
    """

    def __init__(self, history_path: str = _HISTORY_FILE) -> None:
        """초기화.

        Args:
            history_path: 히스토리 JSON 파일 경로. 기본값은 _state/signal_history.json.
        """
        self._path = history_path
        self._store = TimeSeriesStore(Path(history_path), _SIGNAL_SCHEMA, logger)
        self._entries: List[Dict[str, Any]] = self._store.load(validate=False)
        logger.debug("SignalTracker 초기화: %d개 항목 로드", len(self._entries))

    # ── 퍼블릭 API ──────────────────────────────────────────────────────────

    def record(
        self,
        result: CompositeResult,
        btc_price: Optional[float] = None,
        date: Optional[str] = None,
    ) -> SignalSnapshot:
        """당일 신호 결과를 히스토리에 저장한다.

        이전 예측(전날 항목)이 있으면 btc_price와 비교하여 정확도를 역산 기록한다.

        Args:
            result: SignalComposer.compose_signals() 반환값.
            btc_price: 당일 BTC 현재 가격 (USD). 없으면 정확도 평가 생략.
            date: YYYY-MM-DD 형식 날짜. 없으면 KST 오늘 날짜.

        Returns:
            저장된 SignalSnapshot 객체.
        """
        if date is None:
            from .config import get_kst_now

            date = get_kst_now().strftime("%Y-%m-%d")

        now_utc = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

        # 개별 신호 점수 추출
        signal_scores: Dict[str, float] = {sr.name: round(sr.normalized, 4) for sr in result.signal_results}

        snapshot = SignalSnapshot(
            date=date,
            composite_score=result.score,
            verdict=result.verdict,
            confidence=result.confidence,
            signal_scores=signal_scores,
            btc_price=btc_price,
            recorded_at=now_utc,
        )

        # btc_price가 있으면 전날 예측의 정확도를 업데이트한다
        if btc_price is not None:
            self._update_previous_accuracy(date, btc_price)

        # 기존 항목 교체 또는 추가 (같은 날짜가 이미 있으면 덮어쓴다)
        entry_dict = asdict(snapshot)
        existing_idx = next((i for i, e in enumerate(self._entries) if e.get("date") == date), None)
        if existing_idx is not None:
            logger.info("기존 항목 덮어쓰기 (date=%s)", date)
            self._entries[existing_idx] = entry_dict
        else:
            self._entries.append(entry_dict)

        # 오래된 항목 정리
        self._entries = _prune_old_entries(self._entries)

        # 원자적 저장 (TimeSeriesStore 위임)
        self._store._write_atomic(self._entries)
        logger.info("신호 기록 완료: date=%s score=%.1f verdict=%s", date, result.score, result.verdict)
        return snapshot

    def accuracy_report(self, lookback_days: int = 30) -> AccuracyReport:
        """최근 N일 예측 정확도 리포트를 생성한다.

        Args:
            lookback_days: 분석할 최근 일수 (기본 30일).

        Returns:
            AccuracyReport: 승률, 버딕트별 통계, 최근 레코드 포함.
        """
        cutoff = (datetime.now(UTC) - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
        recent = [e for e in self._entries if e.get("date", "") >= cutoff]

        records: List[AccuracyRecord] = []
        for entry in recent:
            acc = entry.get("accuracy")
            if acc is None:
                continue
            records.append(
                AccuracyRecord(
                    date=entry["date"],
                    predicted_verdict=acc.get("predicted_verdict", ""),
                    predicted_score=acc.get("predicted_score", 0.0),
                    actual_price_change_pct=acc.get("actual_price_change_pct"),
                    actual_direction=acc.get("actual_direction"),
                    correct=acc.get("correct"),
                )
            )

        evaluable = [r for r in records if r.correct is not None]
        correct_count = sum(1 for r in evaluable if r.correct)
        win_rate = correct_count / len(evaluable) if evaluable else 0.0

        # 버딕트 유형별 집계
        by_verdict: Dict[str, Dict[str, Any]] = {}
        for r in evaluable:
            v = r.predicted_verdict
            if v not in by_verdict:
                by_verdict[v] = {"total": 0, "correct": 0, "win_rate": 0.0}
            by_verdict[v]["total"] += 1
            if r.correct:
                by_verdict[v]["correct"] += 1
        for _v, stats in by_verdict.items():
            stats["win_rate"] = stats["correct"] / stats["total"] if stats["total"] else 0.0

        return AccuracyReport(
            total_predictions=len(evaluable),
            correct_predictions=correct_count,
            win_rate=win_rate,
            by_verdict=by_verdict,
            recent_accuracy=sorted(records, key=lambda r: r.date, reverse=True)[:lookback_days],
        )

    def get_history(self, days: int = 30) -> List[SignalSnapshot]:
        """최근 N일 스냅샷을 반환한다.

        Args:
            days: 반환할 최근 일수.

        Returns:
            날짜 역순(최신 → 오래된) SignalSnapshot 리스트.
        """
        cutoff = (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%d")
        snapshots = []
        for e in self._entries:
            if e.get("date", "") >= cutoff:
                try:
                    snapshots.append(
                        SignalSnapshot(
                            date=e["date"],
                            composite_score=e.get("composite_score", 0.0),
                            verdict=e.get("verdict", ""),
                            confidence=e.get("confidence", ""),
                            signal_scores=e.get("signal_scores", {}),
                            btc_price=e.get("btc_price"),
                            recorded_at=e.get("recorded_at", ""),
                        )
                    )
                except (KeyError, TypeError) as exc:
                    logger.debug("항목 파싱 실패 (date=%s): %s", e.get("date"), exc)
        return sorted(snapshots, key=lambda s: s.date, reverse=True)

    def format_accuracy_summary(self, lookback_days: int = 30) -> str:
        """정확도 요약을 마크다운 문자열로 반환한다.

        히스토리가 없거나 평가 불가 시 빈 문자열을 반환한다.

        Args:
            lookback_days: 분석할 최근 일수.

        Returns:
            마크다운 형식 정확도 요약 문자열.
        """
        report = self.accuracy_report(lookback_days=lookback_days)
        if report.total_predictions == 0:
            return ""

        lines = [
            f"### 📊 신호 예측 정확도 (최근 {lookback_days}일)",
            "",
            f"- **전체 승률**: {report.win_rate:.1%} ({report.correct_predictions}/{report.total_predictions})",
        ]

        # 버딕트별 승률
        if report.by_verdict:
            lines.append("- **버딕트별 정확도**:")
            for verdict, stats in report.by_verdict.items():
                lines.append(f"  - {verdict}: {stats['win_rate']:.1%} ({stats['correct']}/{stats['total']})")

        # 최근 5일 예측 이력
        recent5 = report.recent_accuracy[:5]
        if recent5:
            lines.append("")
            lines.append("| 날짜 | 예측 | 점수 | 실제 방향 | 결과 |")
            lines.append("|------|------|------|-----------|------|")
            for r in recent5:
                chg = f"{r.actual_price_change_pct:+.2f}%" if r.actual_price_change_pct is not None else "—"
                result_icon = "✅" if r.correct else ("❌" if r.correct is False else "—")
                lines.append(
                    f"| {r.date} | {r.predicted_verdict} | {r.predicted_score:.1f} "
                    f"| {r.actual_direction or '—'} ({chg}) | {result_icon} |"
                )

        return "\n".join(lines)

    # ── 내부 메서드 ─────────────────────────────────────────────────────────

    def _update_previous_accuracy(self, today_date: str, today_btc_price: float) -> None:
        """오늘 BTC 가격을 이용해 전날 예측 정확도를 업데이트한다.

        전날 항목을 찾아 btc_price 대비 변동률을 계산하고,
        verdict 예측 방향과 비교하여 correct 필드를 기록한다.

        Args:
            today_date: 오늘 날짜 YYYY-MM-DD.
            today_btc_price: 오늘 BTC 가격 (USD).
        """
        try:
            today_dt = datetime.strptime(today_date, "%Y-%m-%d").replace(tzinfo=UTC)
            yesterday_str = (today_dt - timedelta(days=1)).strftime("%Y-%m-%d")
        except ValueError:
            return

        prev_entry = next((e for e in self._entries if e.get("date") == yesterday_str), None)
        if prev_entry is None:
            logger.debug("전날 항목 없음 (date=%s)", yesterday_str)
            return

        prev_btc = prev_entry.get("btc_price")
        if prev_btc is None or prev_btc <= 0:
            logger.debug("전날 BTC 가격 없음, 정확도 평가 불가")
            return

        change_pct = ((today_btc_price - prev_btc) / prev_btc) * 100
        actual_dir = _price_direction(change_pct)

        predicted_verdict = prev_entry.get("verdict", "")
        predicted_direction = _verdict_to_direction(predicted_verdict)

        correct: Optional[bool] = None
        if predicted_direction is not None:
            correct = predicted_direction == actual_dir

        prev_entry["accuracy"] = {
            "predicted_verdict": predicted_verdict,
            "predicted_score": prev_entry.get("composite_score", 0.0),
            "actual_price_change_pct": round(change_pct, 4),
            "actual_direction": actual_dir,
            "correct": correct,
            "evaluated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

        result_label = "✅ 정확" if correct else ("❌ 오류" if correct is False else "평가불가")
        logger.info(
            "정확도 업데이트 (date=%s): 예측=%s 실제=%s(%+.2f%%) → %s",
            yesterday_str,
            predicted_verdict,
            actual_dir,
            change_pct,
            result_label,
        )
