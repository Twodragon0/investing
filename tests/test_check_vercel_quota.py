"""`check_vercel_quota.py` 단위 테스트.

## 이 파일이 지키는 것

이 도구가 손으로 돌리던 절차(`docs/devsecops/branch-protection.md` 의 "재측정
(2026-08-10)")를 고정한 것이므로, 그 절차가 매번 밟던 함정 세 개가 그대로 회귀
표면이다. 셋 다 **조용히 틀린 숫자**를 만든다 — 예외가 나지 않는다:

- **non-head 를 거절로 세면 거절이 부풀려진다.** 한 푸시에 커밋이 여러 개면 Vercel
  은 head 하나에만 레코드를 만든다. 08-10 재측정에서 24건 중 3건이 이 경로였다.
- **페이지네이션 커서를 못 읽으면 최근 20건만 본다.** `vercel ls` 한 페이지는 20건
  이고, 커서를 놓치면 "피크 20" 이라는 답이 나온다. 커서 부재와 커서 0 을 섞어
  다루면 무한 루프도 된다.
- **창 경계 규칙이 흔들리면 피크가 1건 달라진다.** 재측정 문서의 94 와 이 도구의
  95 가 정확히 그 차이라, 규칙을 단언으로 못 박아 둔다.

구성 분류(`record_kind`)도 함께 지킨다. 피크 하락을 파일럿 성과로 오독하는 것을
막는 것이 이 도구의 존재 이유인데, 그 판단이 전적으로 이 분류에 걸려 있다.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_ROOT = Path(__file__).parent.parent
_TOOLS = _ROOT / "scripts" / "tools"
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))
if str(_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(_ROOT / "scripts"))

import check_vercel_quota as cvq  # noqa: E402

KST = timezone(timedelta(hours=9))


def _at(day: int, hour: int = 0, minute: int = 0, second: int = 0) -> datetime:
    return datetime(2026, 8, day, hour, minute, second, tzinfo=KST)


def _commit(day: int, hour: int, minute: int, sha: str, *, second: int = 0, subject: str = "chore: x") -> cvq.Commit:
    return cvq.Commit(at=_at(day, hour, minute, second), sha=sha, subject=subject)


def _record(day: int, hour: int, *, env: str = "production", sha: str = "s", subject: str = "") -> cvq.Record:
    return cvq.Record(at=_at(day, hour), env=env, state="READY", sha=sha, subject=subject)


# ── 롤링 피크 ────────────────────────────────────────────────────────────────


def test_rolling_peak_counts_densest_window() -> None:
    times = [_at(7, 0), _at(7, 1), _at(7, 2), _at(9, 0)]
    at, count = cvq.rolling_peak(times, timedelta(hours=24))
    assert count == 3
    assert at == _at(7, 2)


def test_rolling_peak_window_is_right_closed_left_open() -> None:
    """`(t - window, t]` — 정확히 창 폭만큼 떨어진 레코드는 **빠진다**.

    이 한 건이 재측정 문서의 94 와 이 도구의 95 를 가른다. 규칙이 바뀌면 두 수치를
    비교하는 서술이 전부 어긋나므로 단언으로 고정한다.
    """
    exactly_24h_apart = [_at(7, 0), _at(8, 0)]
    _, count = cvq.rolling_peak(exactly_24h_apart, timedelta(hours=24))
    assert count == 1

    one_second_inside = [_at(7, 0, 0, 1), _at(8, 0)]
    _, count = cvq.rolling_peak(one_second_inside, timedelta(hours=24))
    assert count == 2


def test_rolling_peak_handles_unsorted_input() -> None:
    times = [_at(9, 0), _at(7, 0), _at(7, 1)]
    at, count = cvq.rolling_peak(times, timedelta(hours=24))
    assert (at, count) == (_at(7, 1), 2)


def test_rolling_peak_returns_none_when_empty() -> None:
    """레코드 0건에 피크 0 을 돌려주면 "쿼터 여유 있음" 으로 오독된다."""
    assert cvq.rolling_peak([], timedelta(hours=24)) is None


def test_rolling_peak_end_bounds_do_not_filter_counted_records() -> None:
    """`min_end` 는 **창 종료**만 제한한다 — 창 안의 앞선 레코드는 그대로 센다.

    레코드 쪽을 걸러 파일럿 전/후를 나누면, 경계 직후 창에서 실제 쿼터 부하가
    과소평가된다. 쿼터 카운터는 파일럿 머지 시각을 모른다.
    """
    times = [_at(7, 0), _at(7, 1), _at(8, 0)]
    peak = cvq.rolling_peak(times, timedelta(hours=24), min_end=_at(8, 0))
    assert peak is not None, "창 종료가 min_end 를 만족하는데 None — 레코드까지 걸러졌다"
    at, count = peak
    assert at == _at(8, 0)
    assert count == 2  # 08-07 01:00 과 08-08 00:00 — 창 종료만 제한됐다


def test_rolling_peak_max_end_stops_at_boundary() -> None:
    times = [_at(7, 0), _at(7, 1), _at(9, 0), _at(9, 1), _at(9, 2)]
    at, count = cvq.rolling_peak(times, timedelta(hours=24), max_end=_at(8, 0))
    assert (at, count) == (_at(7, 1), 2)


def test_rolling_peak_returns_none_when_no_window_end_qualifies() -> None:
    """조건에 맞는 창이 없으면 None — 0 을 돌려주면 "부하 없음" 으로 읽힌다."""
    times = [_at(7, 0), _at(7, 1)]
    assert cvq.rolling_peak(times, timedelta(hours=24), min_end=_at(9, 0)) is None


# ── SHA 대조 ─────────────────────────────────────────────────────────────────


def test_classify_separates_push_batch_non_head_from_rejection() -> None:
    """90초 이내 후속 커밋이 레코드를 받았으면 거절이 아니라 non-head 다."""
    commits = [
        _commit(7, 12, 0, "a", second=0),
        _commit(7, 12, 0, "b", second=30),
    ]
    verdict = cvq.classify_commits(commits, frozenset({"b"}), timedelta(seconds=90))
    assert [c.sha for c in verdict.deployed] == ["b"]
    assert [c.sha for c in verdict.non_head] == ["a"]
    assert verdict.rejected == []


def test_classify_counts_rejection_when_follower_is_outside_batch_window() -> None:
    """91초 뒤 커밋은 같은 푸시가 아니다 — 앞 커밋은 거절이다."""
    commits = [
        _commit(7, 12, 0, "a", second=0),
        _commit(7, 12, 1, "b", second=31),
    ]
    verdict = cvq.classify_commits(commits, frozenset({"b"}), timedelta(seconds=90))
    assert [c.sha for c in verdict.rejected] == ["a"]
    assert verdict.non_head == []


def test_classify_counts_rejection_when_follower_also_missing() -> None:
    """후속 커밋도 레코드를 못 받았으면 둘 다 거절이다 — batch 로 숨기지 않는다."""
    commits = [
        _commit(7, 12, 0, "a", second=0),
        _commit(7, 12, 0, "b", second=30),
    ]
    verdict = cvq.classify_commits(commits, frozenset(), timedelta(seconds=90))
    assert [c.sha for c in verdict.rejected] == ["a", "b"]
    assert verdict.non_head == []


def test_classify_looks_past_the_immediate_follower() -> None:
    """batch 의 head 가 세 번째 커밋이면 앞의 둘 다 non-head 다."""
    commits = [
        _commit(7, 12, 0, "a", second=0),
        _commit(7, 12, 0, "b", second=10),
        _commit(7, 12, 0, "c", second=20),
    ]
    verdict = cvq.classify_commits(commits, frozenset({"c"}), timedelta(seconds=90))
    assert [c.sha for c in verdict.non_head] == ["a", "b"]
    assert verdict.rejected == []


def test_classify_last_commit_without_record_is_rejected() -> None:
    """뒤에 아무 커밋도 없으면 batch 로 설명할 수 없다."""
    commits = [_commit(7, 12, 0, "a")]
    verdict = cvq.classify_commits(commits, frozenset(), timedelta(seconds=90))
    assert [c.sha for c in verdict.rejected] == ["a"]


def test_classify_handles_same_second_commits(monkeypatch: pytest.MonkeyPatch) -> None:
    """커밋 시각이 **같을** 때도 non-head 를 거절로 세면 안 된다.

    `git log` 는 시각이 동률이면 자식(head)을 부모보다 먼저 낸다 — 임시 레포에서
    확인했다. 그대로 안정 정렬하면 head 가 non-head 앞에 남고, `classify_commits`
    는 뒤만 보므로 non-head 를 못 찾아 거절로 센다. 거절이 부풀려지는 것은 이
    도구가 없애려던 바로 그 오류라, 파싱부터 판정까지 묶어서 지킨다.
    """
    git_log_output = (
        "childsha|2026-08-07T12:00:00+09:00|child (head)\nparentsha|2026-08-07T12:00:00+09:00|parent (non-head)\n"
    )
    monkeypatch.setattr(cvq, "_run", lambda cmd: git_log_output)

    commits = cvq.fetch_commits(_at(7))
    assert commits is not None
    assert [c.sha for c in commits] == ["parentsha", "childsha"], "부모가 자식보다 앞이어야 한다"

    verdict = cvq.classify_commits(commits, frozenset({"childsha"}), timedelta(seconds=90))
    assert [c.sha for c in verdict.non_head] == ["parentsha"]
    assert verdict.rejected == []


def test_fetch_commits_skips_unparsable_lines(monkeypatch: pytest.MonkeyPatch) -> None:
    """필드가 모자라거나 시각이 깨진 줄로 집계를 죽이지 않는다."""
    monkeypatch.setattr(
        cvq,
        "_run",
        lambda cmd: "짧은줄\nsha|not-a-date|x\ngood|2026-08-07T12:00:00+09:00|ok\n",
    )
    commits = cvq.fetch_commits(_at(7))
    assert commits is not None
    assert [c.sha for c in commits] == ["good"]


def test_fetch_commits_returns_none_when_git_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """빈 목록으로 폴백하면 커밋 0건 = 거절 0건이라 거짓 PASS 가 된다."""
    monkeypatch.setattr(cvq, "_run", lambda cmd: None)
    assert cvq.fetch_commits(_at(7)) is None


# ── vercel 출력 파싱 ─────────────────────────────────────────────────────────


def test_parse_records_reads_page_and_cursor() -> None:
    payload = json.dumps(
        {
            "deployments": [
                {
                    "createdAt": 1786662786994,
                    "state": "READY",
                    "meta": {"githubCommitSha": "abc", "githubCommitMessage": "chore: collect x"},
                }
            ],
            "pagination": {"count": 1, "next": 1786618037434},
        }
    )
    records, cursor = cvq.parse_records(payload, "production")
    assert cursor == 1786618037434
    assert len(records) == 1
    assert records[0].sha == "abc"
    assert records[0].env == "production"


def test_parse_records_returns_none_cursor_on_last_page() -> None:
    """`next` 가 없으면 None — 0 이나 falsy 커서로 루프가 돌면 무한이 된다."""
    payload = json.dumps({"deployments": [], "pagination": {"count": 0}})
    records, cursor = cvq.parse_records(payload, "preview")
    assert records == []
    assert cursor is None


def test_parse_records_survives_malformed_payload() -> None:
    """파싱 실패에 예외를 던지면 집계 전체가 죽는다. 빈 페이지로 내려간다."""
    assert cvq.parse_records("not json", "production") == ([], None)


def test_parse_records_skips_entries_without_timestamp() -> None:
    """`createdAt` 없는 항목을 지금 시각으로 치면 피크가 오염된다."""
    payload = json.dumps({"deployments": [{"state": "READY"}, {"createdAt": 1786662786994}]})
    records, _ = cvq.parse_records(payload, "production")
    assert len(records) == 1


def test_parse_records_tolerates_missing_meta() -> None:
    """수동 배포는 `meta` 가 없다 — SHA 없음으로 남기고 거절 판정에서 제외한다."""
    payload = json.dumps({"deployments": [{"createdAt": 1786662786994, "state": "READY"}]})
    records, _ = cvq.parse_records(payload, "production")
    assert records[0].sha is None
    assert records[0].subject == ""


# ── 피크 창 구성 ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("env", "subject", "expected"),
    [
        ("preview", "chore: collect crypto news", "preview(PR)"),
        ("production", "chore: collect crypto news", "수집기"),
        ("production", "chore: backfill post images", "수집기"),
        ("production", "Merge pull request #1 from x", "PR 머지"),
        ("production", "feat: 뭔가 (#1161)", "PR 머지"),
        ("production", "docs: 손으로 푸시", "그 외"),
    ],
)
def test_record_kind(env: str, subject: str, expected: str) -> None:
    assert cvq.record_kind(_record(7, 0, env=env, subject=subject)) == expected


def test_preview_env_wins_over_subject() -> None:
    """preview 는 PR 브랜치 배포다. 제목이 수집기여도 개발 활동으로 세야 한다.

    여기서 갈리면 "피크의 71%가 개발 활동" 이라는 판단이 조용히 뒤집힌다.
    """
    record = _record(7, 0, env="preview", subject="chore: collect crypto news")
    assert cvq.record_kind(record) == "preview(PR)"


# ── 페이지네이션 ─────────────────────────────────────────────────────────────


def _page(cursor: int | None, day: int, hour: int) -> str:
    epoch_ms = int(_at(day, hour).timestamp() * 1000)
    body: dict = {"deployments": [{"createdAt": epoch_ms, "state": "READY"}]}
    if cursor is not None:
        body["pagination"] = {"next": cursor}
    return json.dumps(body)


def test_fetch_records_stops_once_since_is_covered(monkeypatch: pytest.MonkeyPatch) -> None:
    pages = [_page(111, 9, 0), _page(222, 8, 0), _page(333, 6, 0)]
    calls: list[list[str]] = []

    def fake_run(cmd: list[str]) -> str:
        calls.append(cmd)
        return pages[len(calls) - 1]

    monkeypatch.setattr(cvq, "_run", fake_run)
    records = cvq.fetch_records("investing", "production", _at(7))
    assert records is not None
    assert len(records) == 3  # 08-06 페이지에서 since 를 넘겼다
    assert "--next" in calls[1] and "111" in calls[1]


def test_fetch_records_stops_when_cursor_stalls(monkeypatch: pytest.MonkeyPatch) -> None:
    """커서가 안 움직이면 멈춘다 — 같은 페이지를 상한까지 쌓으면 피크가 부풀려진다."""
    monkeypatch.setattr(cvq, "_run", lambda cmd: _page(111, 9, 0))
    records = cvq.fetch_records("investing", "production", _at(1))
    assert records is not None
    assert len(records) == 2  # 첫 페이지 + 커서 정체를 감지한 두 번째


def test_fetch_records_fails_closed_on_page_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """상한에 걸리면 None. 부분 결과를 내면 안 덮인 구간이 전부 거절로 보고된다."""
    cursor = iter(range(10_000))
    monkeypatch.setattr(cvq, "_run", lambda cmd: _page(next(cursor), 9, 0))
    monkeypatch.setattr(cvq, "MAX_PAGES", 3)
    assert cvq.fetch_records("investing", "production", _at(1)) is None


def test_fetch_records_propagates_command_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cvq, "_run", lambda cmd: None)
    assert cvq.fetch_records("investing", "production", _at(7)) is None


# ── 피크 창 구성 ─────────────────────────────────────────────────────────────


def test_window_composition_respects_window_bounds() -> None:
    records = [
        _record(7, 0, subject="chore: collect a"),
        _record(7, 12, subject="feat: b (#1)"),
        _record(6, 0, subject="chore: collect old"),
    ]
    counts = cvq.window_composition(records, _at(7, 12), timedelta(hours=24))
    assert counts == {"수집기": 1, "PR 머지": 1}
