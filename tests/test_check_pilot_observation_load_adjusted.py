"""`check_pilot_observation.py` 의 부하 보정 절감 지표 단위 테스트.

## 왜 부하 보정이 필요한가

파일럿(no-op 커밋 skip, `collect-regulatory`, 08-10 13:14 KST 머지)의 절감을
**일자별 커밋 수 원값**으로 읽으면 부하 변동과 구분되지 않는다. 수집기가 그날 몇
번 돌았는지, 뉴스가 많았는지에 따라 커밋 수는 파일럿과 무관하게 움직인다.

두 개의 비율로 보정한다. 서로 다른 교란을 상쇄하므로 교차 검증이 된다:

1. **실행당 커밋** — 분모가 워크플로우 실행 수. "몇 번 돌았나" 를 상쇄한다.
2. **대조군 비** — 분모가 파일럿 미적용 수집기들의 커밋 수. 뉴스량처럼 모든
   수집기에 공통으로 걸리는 변동을 상쇄한다 (difference-in-differences).

## 이 파일이 지키는 것

- 파일럿 수집기가 대조군에 들어가면 지표가 자기참조가 되어 조용히 무의미해진다.
  대조군 상수는 파일럿 대상을 포함해서는 안 되고, 비어서도 안 된다.
- `collect political` 이 `collect geopolitical` 을 잡아채면 두 수집기가 한 축으로
  합쳐진다. 커밋 주제 매칭은 수집기를 정확히 갈라야 한다.
- 분모가 0일 때 0.0 을 돌려주면 "절감 100%" 로 읽힌다. `None` 이어야 한다.
- 관측 기간이 게이트(3일)에 못 미치면 판정을 내리지 않고 보류해야 한다.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

_ROOT = Path(__file__).parent.parent
_TOOLS = _ROOT / "scripts" / "tools"
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))
if str(_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(_ROOT / "scripts"))

import check_pilot_observation as cpo  # noqa: E402

_KST = timezone(timedelta(hours=9))
_PILOT = datetime(2026, 8, 10, 13, 14, 51, tzinfo=_KST)


def _ts(day: int, hour: int) -> datetime:
    return datetime(2026, 8, day, hour, 0, tzinfo=_KST)


# ---------------------------------------------------------------------------
# 대조군 상수 — 자기참조/공집합 가드
# ---------------------------------------------------------------------------


def test_control_collectors_exclude_pilot_default():
    """대조군에 파일럿 대상이 들어가면 지표가 자기참조가 된다."""
    assert cpo.DEFAULT_COLLECTOR not in cpo.CONTROL_COLLECTORS, (
        f"대조군에 파일럿 대상 {cpo.DEFAULT_COLLECTOR!r} 이(가) 들어 있다. "
        "분자와 분모가 같은 축을 세면 비율이 파일럿 효과에 반응하지 않는다."
    )


def test_control_collectors_not_empty():
    """대조군이 비면 분모가 0이라 지표가 항상 판정 불가가 된다."""
    assert cpo.CONTROL_COLLECTORS, "대조군 수집기가 비어 있다"


# ---------------------------------------------------------------------------
# 커밋 주제 파싱 — 수집기 구분
# ---------------------------------------------------------------------------


_LOG = "\n".join(
    [
        "2026-08-09T07:15:00+09:00|chore: collect regulatory news 2026-08-08T22:14Z",
        "2026-08-09T08:15:00+09:00|chore: collect political trades 2026-08-08T23:14Z",
        "2026-08-09T09:15:00+09:00|chore: collect geopolitical news 2026-08-09T00:14Z",
        "2026-08-11T07:15:00+09:00|chore: collect regulatory news 2026-08-10T22:14Z",
        "malformed line without a pipe",
    ]
)


def test_parse_commit_timestamps_picks_only_target():
    got = cpo.parse_commit_timestamps(_LOG, "regulatory")
    assert [t.hour for t in got] == [7, 7]
    assert all(t.day in (9, 11) for t in got)


def test_parse_commit_timestamps_separates_political_and_geopolitical():
    """`collect political` 이 `collect geopolitical` 을 잡아채면 두 축이 합쳐진다."""
    political = cpo.parse_commit_timestamps(_LOG, "political")
    geopolitical = cpo.parse_commit_timestamps(_LOG, "geopolitical")
    assert len(political) == 1, f"political 이 {len(political)}건 — geopolitical 을 잡아챘다"
    assert len(geopolitical) == 1
    assert political[0].hour == 8
    assert geopolitical[0].hour == 9


def test_parse_commit_timestamps_ignores_malformed_lines():
    assert len(cpo.parse_commit_timestamps(_LOG, "regulatory")) == 2


# ---------------------------------------------------------------------------
# 파일럿 경계 분할
# ---------------------------------------------------------------------------


def test_split_by_pilot_boundary_is_inclusive_on_post_side():
    """머지 시각과 정확히 같은 타임스탬프는 '후' 다."""
    pre, post = cpo.split_by_pilot([_PILOT], _PILOT)
    assert (pre, post) == (0, 1)


def test_split_by_pilot_counts_both_sides():
    stamps = [_ts(9, 7), _ts(10, 7), _ts(10, 22), _ts(11, 7)]
    assert cpo.split_by_pilot(stamps, _PILOT) == (2, 2)


def test_split_by_pilot_normalizes_timezones():
    """UTC 로 들어온 실행 시각과 KST 커밋 시각이 같은 축에서 비교돼야 한다."""
    utc_before = datetime(2026, 8, 10, 4, 0, tzinfo=UTC)  # 13:00 KST — 머지 전
    utc_after = datetime(2026, 8, 10, 5, 0, tzinfo=UTC)  # 14:00 KST — 머지 후
    assert cpo.split_by_pilot([utc_before, utc_after], _PILOT) == (1, 1)


# ---------------------------------------------------------------------------
# 비율 계산
# ---------------------------------------------------------------------------


def test_build_ratio_computes_pre_post_and_delta():
    numerator = [_ts(9, 7), _ts(9, 17), _ts(9, 22), _ts(10, 22)]  # 전 3, 후 1
    denominator = [_ts(9, 7), _ts(9, 17), _ts(9, 22), _ts(10, 17), _ts(10, 22)]  # 전 3, 후 2
    ratio = cpo.build_ratio(numerator, denominator, _PILOT)

    assert (ratio.pre_num, ratio.pre_den) == (3, 3)
    assert (ratio.post_num, ratio.post_den) == (1, 2)
    assert ratio.pre() == pytest.approx(1.0)
    assert ratio.post() == pytest.approx(0.5)
    assert ratio.delta_pct() == pytest.approx(-50.0)


def test_build_ratio_zero_denominator_is_none_not_zero():
    """분모 0을 0.0 으로 돌려주면 '절감 100%' 로 읽힌다."""
    ratio = cpo.build_ratio([], [], _PILOT)
    assert ratio.pre() is None
    assert ratio.post() is None
    assert ratio.delta_pct() is None


def test_build_ratio_since_applies_to_both_series():
    """창 정렬이 빠지면 분모만 멀리까지 새어 전 구간 비율이 낮게 나온다.

    커밋은 git `--since`, 실행은 gh `--limit` 으로 각각 잘려 오므로 두 계열의 창은
    자동으로 맞지 않는다.
    """
    window_start = _ts(9, 0)
    numerator = [_ts(8, 7), _ts(9, 7)]  # 창 밖 1, 안 1
    denominator = [_ts(7, 7), _ts(8, 7), _ts(9, 7)]  # 창 밖 2, 안 1

    aligned = cpo.build_ratio(numerator, denominator, _PILOT, since=window_start)
    assert (aligned.pre_num, aligned.pre_den) == (1, 1)
    assert aligned.pre() == pytest.approx(1.0)

    unaligned = cpo.build_ratio(numerator, denominator, _PILOT)
    assert (unaligned.pre_num, unaligned.pre_den) == (2, 3), "창을 안 맞추면 분모가 샌다 — 이 테스트의 전제"
    assert unaligned.pre() != pytest.approx(aligned.pre())


def test_build_ratio_delta_none_when_pre_is_zero():
    """전 구간 비율이 0이면 변화율을 정의할 수 없다 (0 으로 나눔)."""
    numerator = [_ts(11, 7)]
    denominator = [_ts(9, 7), _ts(11, 7)]
    ratio = cpo.build_ratio(numerator, denominator, _PILOT)
    assert ratio.pre() == pytest.approx(0.0)
    assert ratio.delta_pct() is None


# ---------------------------------------------------------------------------
# 표본 게이트
# ---------------------------------------------------------------------------


def test_observation_is_underpowered_before_gate():
    now = _PILOT + timedelta(days=cpo.MIN_OBSERVATION_DAYS) - timedelta(hours=1)
    assert cpo.is_underpowered(_PILOT, now) is True


def test_observation_is_powered_at_gate():
    now = _PILOT + timedelta(days=cpo.MIN_OBSERVATION_DAYS)
    assert cpo.is_underpowered(_PILOT, now) is False


def test_min_observation_days_matches_design_gate():
    """설계 문서의 '최소 3일 관측' 게이트와 어긋나면 안 된다."""
    assert cpo.MIN_OBSERVATION_DAYS == 3


# ---------------------------------------------------------------------------
# gh 부재 시 graceful degradation
# ---------------------------------------------------------------------------


def test_collect_run_timestamps_degrades_when_gh_missing(monkeypatch):
    def _boom(*_a, **_k):
        raise FileNotFoundError("gh")

    monkeypatch.setattr(cpo.subprocess, "run", _boom)
    stamps, reason = cpo.collect_run_timestamps("collect-regulatory.yml", 30)
    assert stamps == []
    assert reason and "gh" in reason


def test_report_load_adjusted_passes_window_to_both_ratios(monkeypatch):
    """창 인자가 호출부에서 빠지면 조용한 실패다 — `build_ratio` 단위 테스트는 못 잡는다."""
    seen: list[datetime | None] = []
    real = cpo.build_ratio

    def spy(numerator, denominator, pilot_merged, since=None):
        seen.append(since)
        return real(numerator, denominator, pilot_merged, since=since)

    monkeypatch.setattr(cpo, "build_ratio", spy)
    monkeypatch.setattr(cpo, "commit_log", lambda _days: _LOG)
    monkeypatch.setattr(cpo, "collect_run_timestamps", lambda _wf, limit: ([_ts(9, 7)], None))

    now = _ts(11, 12)
    cpo.report_load_adjusted("regulatory", 7, _PILOT, now)

    assert len(seen) == 2, f"실행당 커밋·대조군 비 두 지표가 모두 계산돼야 한다 (호출 {len(seen)}회)"
    assert all(s == now - timedelta(days=7) for s in seen), f"창이 전달되지 않았다: {seen}"


def test_report_load_adjusted_still_reports_control_ratio_without_gh(monkeypatch):
    """gh 가 없어도 대조군 비는 git 만으로 계산된다."""
    seen: list[datetime | None] = []
    real = cpo.build_ratio

    def spy(numerator, denominator, pilot_merged, since=None):
        seen.append(since)
        return real(numerator, denominator, pilot_merged, since=since)

    monkeypatch.setattr(cpo, "build_ratio", spy)
    monkeypatch.setattr(cpo, "commit_log", lambda _days: _LOG)
    monkeypatch.setattr(cpo, "collect_run_timestamps", lambda _wf, limit: ([], "gh CLI 미설치"))

    cpo.report_load_adjusted("regulatory", 7, _PILOT, _ts(11, 12))

    assert len(seen) == 1, "gh 부재 시 대조군 비 한 건은 계산돼야 한다"


def test_collect_run_timestamps_parses_iso(monkeypatch):
    class _Out:
        stdout = '[{"createdAt":"2026-08-10T04:00:00Z"},{"createdAt":"2026-08-10T05:00:00Z"}]'

    monkeypatch.setattr(cpo.subprocess, "run", lambda *_a, **_k: _Out())
    stamps, reason = cpo.collect_run_timestamps("collect-regulatory.yml", 30)
    assert reason is None
    assert cpo.split_by_pilot(stamps, _PILOT) == (1, 1)
