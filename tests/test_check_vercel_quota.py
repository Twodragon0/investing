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


# ── 인증 ─────────────────────────────────────────────────────────────────────


def test_vercel_list_cmd_omits_token_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """로컬은 `vercel login` 세션을 쓴다 — 빈 토큰을 붙이면 인증이 깨진다."""
    monkeypatch.delenv("VERCEL_TOKEN", raising=False)
    assert "--token" not in cvq.vercel_list_cmd("investing", "production")

    monkeypatch.setenv("VERCEL_TOKEN", "   ")
    assert "--token" not in cvq.vercel_list_cmd("investing", "production")


def test_vercel_list_cmd_appends_token_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VERCEL_TOKEN", "xxx-dummy-token")
    cmd = cvq.vercel_list_cmd("investing", "preview")
    assert cmd[-2:] == ["--token", "xxx-dummy-token"]
    assert "--environment" in cmd and "preview" in cmd


# ── `--kind` 축 필터 ─────────────────────────────────────────────────────────
#
# 이 렌즈가 필요한 이유는 총량 피크가 개발 활동에 지배될 때 파일럿이 움직일 수 있는
# 축을 따로 봐야 하기 때문이다(모듈 docstring 의 95→52 / 수집기 30→36 실측).
#
# 위험한 것은 필터가 **보고 축을 넘어 판정으로 새는 것**이다. 걸러진 목록으로
# `deployed_shas` 를 만들면 걸러진 레코드를 받은 커밋이 전부 "레코드 없음 = 거절" 이
# 된다. `--kind collector` 하나로 PR 머지 커밋 수십 건이 거절로 둔갑하는 경로다.


def test_filter_kind_all_is_identity() -> None:
    """기본값은 기존 동작을 한 글자도 바꾸지 않아야 한다."""
    records = [
        _record(7, 1, subject="chore: collect crypto news"),
        _record(7, 2, env="preview", subject="feat: x"),
        _record(7, 3, subject="Merge pull request #1 from x"),
    ]
    assert cvq.filter_kind(records, "all") == records


def test_filter_kind_collector_keeps_only_collector_axis() -> None:
    collector = _record(7, 1, subject="chore: collect crypto news")
    backfill = _record(7, 2, subject="chore: backfill post images")
    merge = _record(7, 3, subject="Merge pull request #1 from x")
    preview = _record(7, 4, env="preview", subject="chore: collect crypto news")
    records = [collector, backfill, merge, preview]

    assert cvq.filter_kind(records, "collector") == [collector, backfill]
    # `dev` 는 여집합이다 — 두 축이 겹치거나 비면 부하 구성이 어디론가 샌다.
    assert cvq.filter_kind(records, "dev") == [merge, preview]


def test_kind_choices_and_labels_stay_in_sync() -> None:
    """CLI choices 는 `KIND_FILTERS` 에서 나오고 라벨은 따로 있다 — 갈리면 KeyError.

    `report_peaks` 가 `KIND_LABELS[kind]` 로 헤더를 찍으므로, 필터에만 축을 추가하면
    도구가 런타임에 죽는다.
    """
    assert set(cvq.KIND_FILTERS) == set(cvq.KIND_LABELS)
    assert cvq.DEFAULT_KIND in cvq.KIND_FILTERS


def test_filtering_does_not_touch_rejection_verdict() -> None:
    """축 필터는 보고 축만이다. SHA 대조는 전량으로 돌아야 한다.

    수집기 커밋 1건 + PR 머지 커밋 1건이 **둘 다** 레코드를 받은 상황을 만든다.
    거른 목록으로 대조하면 PR 머지 커밋이 거절로 둔갑한다.
    """
    collector_rec = _record(7, 1, sha="aaa", subject="chore: collect crypto news")
    merge_rec = _record(7, 2, sha="bbb", subject="Merge pull request #1 from x")
    records = [collector_rec, merge_rec]
    commits = [
        _commit(7, 1, 0, "aaa", subject="chore: collect crypto news"),
        _commit(7, 2, 0, "bbb", subject="Merge pull request #1 from x"),
    ]

    whole = frozenset(r.sha for r in records if r.env == "production" and r.sha)
    assert cvq.classify_commits(commits, whole, timedelta(seconds=90)).rejected == []

    # 필터를 판정에 새게 하면 이렇게 된다 — 이 단언이 그 회귀의 모양을 박아 둔다.
    leaked = frozenset(r.sha for r in cvq.filter_kind(records, "collector") if r.env == "production" and r.sha)
    leaked_verdict = cvq.classify_commits(commits, leaked, timedelta(seconds=90))
    assert [c.sha for c in leaked_verdict.rejected] == ["bbb"]


def test_composition_reports_full_load_even_when_filtered(caplog: pytest.LogCaptureFixture) -> None:
    """거른 뒤 구성을 내면 "수집기 100%" 만 남아 그 창의 실제 부하가 사라진다."""
    # 수집기 레코드를 **가장 늦게** 둔다. 피크 창은 그 레코드에서 끝나므로, 앞에
    # 두면 뒤따르는 preview·머지가 창 밖으로 나가 이 단언이 창 경계를 재게 된다.
    records = [
        _record(7, 1, env="preview", subject="feat: x"),
        _record(7, 2, subject="Merge pull request #1 from x"),
        _record(7, 3, subject="chore: collect crypto news"),
    ]

    with caplog.at_level("INFO"):
        cvq.report_peaks(records, timedelta(hours=24), None, _at(7, 0), "collector")
    text = caplog.text
    assert "수집기 축만" in text
    assert "쿼터 부하가 아니다" in text
    # 구성 표는 전량 기준 — preview 와 PR 머지가 살아 있어야 한다.
    assert "피크 창 구성 (총 3건)" in text


def test_main_rejection_count_is_independent_of_kind(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """`--kind` 를 바꿔도 `[3]` 거절 수가 흔들리면 안 된다 — `main()` 배선까지 본다.

    단위 테스트로는 부족하다는 것이 2026-08-18 리뷰에서 뮤테이션으로 드러났다.
    `main()` 의 `deployed_shas` 를 거른 목록으로 바꿔도 39/39 가 통과했다 — 기존
    테스트는 두 frozenset 을 **테스트 본문에서** 손으로 만들어 `classify_commits` 에
    먹였을 뿐, `main()` 이 실제로 어느 쪽을 만드는지는 보지 않았다.

    그래서 여기서는 `main()` 을 직접 돌린다. 수집기 커밋 1건과 PR 머지 커밋 1건이
    **둘 다** 레코드를 받은 상황이라, 필터가 판정으로 새면 `--kind collector` 에서
    머지 커밋이 거절 1건으로 나타난다.
    """

    def _fake_records(project: str, env: str, since: datetime) -> list[cvq.Record]:
        if env != "production":
            return []
        return [
            _record(7, 1, sha="aaa", subject="chore: collect crypto news"),
            _record(7, 2, sha="bbb", subject="Merge pull request #1 from x"),
        ]

    git_log = "aaa|2026-08-07T01:00:00+09:00|chore: collect crypto news\nbbb|2026-08-07T02:00:00+09:00|Merge pull request #1 from x\n"

    def _run_main(kind: str) -> str:
        monkeypatch.setattr(cvq, "fetch_records", _fake_records)
        monkeypatch.setattr(cvq, "_run", lambda cmd: git_log)
        monkeypatch.setattr(sys, "argv", ["check_vercel_quota.py", "--since", "2026-08-01", "--kind", kind])
        caplog.clear()
        with caplog.at_level("INFO"):
            assert cvq.main() == 0
        return caplog.text

    rejection_line = "레코드 없음 = 거절   0"
    all_text = _run_main("all")
    assert rejection_line in all_text
    assert "production+preview" in all_text

    collector_text = _run_main("collector")
    assert rejection_line in collector_text, "축 필터가 SHA 대조로 샜다 — 머지 커밋이 거절로 둔갑했다"
    assert "수집기 축만" in collector_text


def test_rejection_load_uses_the_same_window_rule_as_peaks() -> None:
    """거절에 붙는 부하는 `rolling_peak` 과 같은 `(t-window, t]` 여야 한다.

    규칙이 갈리면 같은 데이터에서 피크와 부하가 1건씩 어긋나고, 그 1건이
    `branch-protection.md` 의 94 대 95 를 만든 차이다.
    """
    times = [_at(7, 0), _at(8, 0), _at(8, 1)]
    window = timedelta(hours=24)
    # 정확히 창 폭만큼 떨어진 08-07 00:00 은 **빠진다**.
    assert cvq.load_at(times, _at(8, 0), window) == 1
    assert cvq.load_at(times, _at(8, 1), window) == 2
    assert cvq.load_at(times, _at(7, 0), window) == 1


def test_rejection_report_omits_load_column_without_records(caplog: pytest.LogCaptureFixture) -> None:
    """부하를 못 내면 열을 빼야 한다 — 0 으로 폴백하면 "부하 0에서 거절" 로 읽힌다."""
    verdict = cvq.Verdict(deployed=[], non_head=[], rejected=[_commit(7, 12, 0, "a", subject="chore: collect x")])
    with caplog.at_level("INFO"):
        cvq.report_rejections(verdict, None)
    assert "부하" not in caplog.text


def test_report_daily_respects_kind_filter(caplog: pytest.LogCaptureFixture) -> None:
    """`[2]` 도 축을 걸러야 한다.

    `[1]` 만 거르고 `[2]` 를 그대로 두면 두 절의 숫자가 다른 모집단을 세면서 같은
    헤더 라벨을 달고 나온다 — 나란히 읽는 사람이 "피크는 내려갔는데 일자별은 그대로"
    라는 없는 현상을 본다. 2026-08-18 뮤테이션 감사에서 이 경로만 무방비였다.
    """
    records = [
        _record(7, 1, subject="chore: collect crypto news"),
        _record(7, 2, env="preview", subject="feat: x"),
        _record(7, 3, subject="Merge pull request #1 from x"),
    ]
    with caplog.at_level("INFO"):
        cvq.report_daily(records, timedelta(hours=24), _at(7, 0), "collector")
    assert "2026-08-07  레코드   1" in caplog.text, "축을 안 걸렀다 — 3건이 그대로 세졌다"
    assert "쿼터 부하가 아니다" in caplog.text

    caplog.clear()
    with caplog.at_level("INFO"):
        cvq.report_daily(records, timedelta(hours=24), _at(7, 0), "all")
    assert "2026-08-07  레코드   3" in caplog.text
