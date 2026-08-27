"""`scripts/generate_weekly_report.py` 테스트 — 이 모듈에는 기존 테스트가 없었다.

`tests/test_generate_weekly_digest.py` 는 이름이 비슷하지만 **다른 모듈**
(`generate_weekly_digest.py`)을 덮는다. 이 리포트 생성기는 커버리지 0% 였다
(풀 스위트에서 13% 로 보이는 것은 다른 테스트가 import 만 해서 생긴 모듈 레벨
커버리지다).

## 이 모듈이 조용히 틀릴 수 있는 지점

주간 리포트는 매주 월요일 크론이 자동 생성하고 **아무도 즉시 읽지 않는다.** 그래서
아래가 깨져도 워크플로우는 성공한다:

- 주 경계 계산 — 하루만 밀려도 커밋·포스트가 옆 주로 새어 나간다
- `git log --shortstat` 파싱 — 정규식이 안 맞으면 통계가 조용히 0 이 된다
- 슬러그 → 카테고리 매핑 — `CAT_NAMES` 순회 순서에 의존한다
- 중복 가드 — 이 가드가 사라지면 손으로 채운 리포트를 덮어쓴다

## 격리

`POSTS_DIR` / `DOCS_DIR` 은 임포트 시점에 `__file__` 로부터 계산되고 `main()` 은
`DOCS_DIR` 에 **파일을 쓴다.** 프로덕션 상수를 임포트하지 않고 `monkeypatch` 로 tmp 를
주입한다. git 은 `_run` 을 대체해 실제 저장소 히스토리에 의존하지 않게 한다 — 실제
히스토리를 읽으면 결과가 커밋될 때마다 바뀐다.
"""

from __future__ import annotations

import importlib
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import pytest

wr = importlib.import_module("generate_weekly_report")

_KST = timezone(timedelta(hours=9))


def _kst(year: int, month: int, day: int, hour: int = 12) -> datetime:
    return datetime(year, month, day, hour, tzinfo=_KST)


@pytest.fixture
def isolated_dirs(tmp_path, monkeypatch):
    """`POSTS_DIR` / `DOCS_DIR` 을 tmp 로 돌린다 — `main()` 은 DOCS_DIR 에 쓴다."""
    posts = tmp_path / "_posts"
    docs = tmp_path / "docs"
    posts.mkdir()
    docs.mkdir()
    monkeypatch.setattr(wr, "POSTS_DIR", str(posts))
    monkeypatch.setattr(wr, "DOCS_DIR", str(docs))
    return posts, docs


@pytest.fixture
def frozen_now(monkeypatch):
    """`get_kst_now` 를 2026-08-27(목, W35)로 고정한다."""
    monkeypatch.setattr(wr, "get_kst_now", lambda: _kst(2026, 8, 27, 15))
    return _kst(2026, 8, 27, 15)


# ---------------------------------------------------------------------------
# _week_bounds
# ---------------------------------------------------------------------------


class TestWeekBounds:
    def test_offset_one_is_the_previous_completed_week(self, frozen_now) -> None:
        """2026-08-27 은 목요일 → offset 1 은 08-17(월) ~ 08-23(일), W34."""
        start, end, iso_year, iso_week = wr._week_bounds(1)
        assert start.strftime("%Y-%m-%d") == "2026-08-17"
        assert end.strftime("%Y-%m-%d") == "2026-08-23"
        assert (iso_year, iso_week) == (2026, 34)

    def test_offset_zero_is_the_current_week(self, frozen_now) -> None:
        start, end, _y, iso_week = wr._week_bounds(0)
        assert start.strftime("%Y-%m-%d") == "2026-08-24"
        assert end.strftime("%Y-%m-%d") == "2026-08-30"
        assert iso_week == 35

    def test_week_starts_monday_midnight(self, frozen_now) -> None:
        start, _end, _y, _w = wr._week_bounds(1)
        assert start.weekday() == 0
        assert (start.hour, start.minute, start.second, start.microsecond) == (0, 0, 0, 0)

    def test_week_ends_sunday_end_of_day(self, frozen_now) -> None:
        _start, end, _y, _w = wr._week_bounds(1)
        assert end.weekday() == 6
        assert (end.hour, end.minute, end.second) == (23, 59, 59)

    def test_span_is_exactly_seven_days(self, frozen_now) -> None:
        start, end, _y, _w = wr._week_bounds(3)
        assert (end - start).days == 6

    def test_larger_offset_goes_further_back(self, frozen_now) -> None:
        start1, _e1, _y1, w1 = wr._week_bounds(1)
        start4, _e4, _y4, w4 = wr._week_bounds(4)
        assert (start1 - start4).days == 21
        assert (w1, w4) == (34, 31)

    def test_monday_now_still_reports_the_prior_week(self, monkeypatch) -> None:
        """월요일 00시 크론이 도는 순간에도 offset 1 은 완료된 주여야 한다."""
        monkeypatch.setattr(wr, "get_kst_now", lambda: _kst(2026, 8, 24, 0))
        start, end, _y, iso_week = wr._week_bounds(1)
        assert start.strftime("%Y-%m-%d") == "2026-08-17"
        assert end.strftime("%Y-%m-%d") == "2026-08-23"
        assert iso_week == 34


# ---------------------------------------------------------------------------
# _run
# ---------------------------------------------------------------------------


class TestRun:
    def test_returns_stripped_stdout(self, monkeypatch) -> None:
        class _Result:
            returncode = 0
            stdout = "  출력값\n"
            stderr = ""

        monkeypatch.setattr(wr.subprocess, "run", lambda *_a, **_kw: _Result())
        assert wr._run(["git", "log"]) == "출력값"

    def test_nonzero_exit_returns_empty(self, monkeypatch, caplog) -> None:
        class _Result:
            returncode = 128
            stdout = "무시됨"
            stderr = "fatal: not a git repository"

        monkeypatch.setattr(wr.subprocess, "run", lambda *_a, **_kw: _Result())
        with caplog.at_level("DEBUG"):
            assert wr._run(["git", "log"]) == ""

    @pytest.mark.parametrize(
        "exc",
        [
            FileNotFoundError("git 없음"),
            None,  # TimeoutExpired 는 인자가 필요해 아래에서 생성한다
        ],
    )
    def test_failure_returns_empty(self, monkeypatch, exc) -> None:
        import subprocess as sp

        error = exc if exc is not None else sp.TimeoutExpired(["git"], 30)

        def boom(*_a, **_kw):
            raise error

        monkeypatch.setattr(wr.subprocess, "run", boom)
        assert wr._run(["git", "log"]) == ""

    def test_passes_cwd_and_timeout(self, monkeypatch) -> None:
        captured: Dict[str, Any] = {}

        class _Result:
            returncode = 0
            stdout = ""
            stderr = ""

        def fake_run(cmd, cwd=None, capture_output=None, text=None, timeout=None):
            captured.update({"cmd": cmd, "cwd": cwd, "timeout": timeout})
            return _Result()

        monkeypatch.setattr(wr.subprocess, "run", fake_run)
        wr._run(["git", "status"], cwd="/tmp")
        assert captured["cwd"] == "/tmp"
        assert captured["timeout"] == 30


# ---------------------------------------------------------------------------
# git_stats
# ---------------------------------------------------------------------------


def _patch_run(monkeypatch, mapping: Dict[str, str], calls: List[List[str]] | None = None):
    """`_run` 을 대체한다. `mapping` 은 인자에 포함된 표식 → 출력."""

    def fake_run(cmd, cwd=wr.REPO_ROOT):
        if calls is not None:
            calls.append(cmd)
        for marker, output in mapping.items():
            if marker in cmd:
                return output
        return ""

    monkeypatch.setattr(wr, "_run", fake_run)


class TestGitStats:
    def test_parses_shortstat_and_counts_commits(self, monkeypatch) -> None:
        shortstat = (
            " 3 files changed, 40 insertions(+), 5 deletions(-)\n"
            " 1 file changed, 2 insertions(+)\n"
            " 2 files changed, 7 deletions(-)\n"
        )
        oneline = "abc1 feat: a\ndef2 fix: b\n\nghi3 docs: c\n"
        _patch_run(monkeypatch, {"--shortstat": shortstat, "--oneline": oneline})

        stats = wr.git_stats(_kst(2026, 8, 17), _kst(2026, 8, 23))
        assert stats == {"commits": 3, "files_changed": 6, "insertions": 42, "deletions": 12}

    def test_singular_file_changed_is_parsed(self, monkeypatch) -> None:
        """`1 file changed` (단수) 도 세야 한다 — 정규식이 `files?` 인 이유."""
        _patch_run(monkeypatch, {"--shortstat": " 1 file changed, 1 insertion(+)\n", "--oneline": "a x\n"})
        stats = wr.git_stats(_kst(2026, 8, 17), _kst(2026, 8, 23))
        assert stats["files_changed"] == 1
        assert stats["insertions"] == 1

    def test_empty_history_yields_zeros(self, monkeypatch) -> None:
        _patch_run(monkeypatch, {})
        assert wr.git_stats(_kst(2026, 8, 17), _kst(2026, 8, 23)) == {
            "commits": 0,
            "files_changed": 0,
            "insertions": 0,
            "deletions": 0,
        }

    def test_until_is_exclusive_so_it_advances_one_second(self, monkeypatch) -> None:
        """`--until` 은 주 종료(일 23:59:59)에 1초를 더해 다음 날짜가 된다.

        이 +1초가 없으면 마지막 날 커밋이 빠진다.
        """
        calls: List[List[str]] = []
        _patch_run(monkeypatch, {}, calls)
        wr.git_stats(_kst(2026, 8, 17, 0), datetime(2026, 8, 23, 23, 59, 59, tzinfo=_KST))
        flat = " ".join(calls[0])
        assert "--since=2026-08-17" in flat
        assert "--until=2026-08-24" in flat

    def test_merges_are_excluded_from_commit_count(self, monkeypatch) -> None:
        calls: List[List[str]] = []
        _patch_run(monkeypatch, {}, calls)
        wr.git_stats(_kst(2026, 8, 17), _kst(2026, 8, 23))
        assert all("--no-merges" in cmd for cmd in calls)


class TestMergedPrs:
    def test_returns_merge_subjects(self, monkeypatch) -> None:
        output = "Merge pull request #1 from a\n\nMerge pull request #2 from b\n"
        _patch_run(monkeypatch, {"--merges": output})
        assert wr.merged_prs(_kst(2026, 8, 17), _kst(2026, 8, 23)) == [
            "Merge pull request #1 from a",
            "Merge pull request #2 from b",
        ]

    def test_empty_output_returns_empty_list(self, monkeypatch) -> None:
        _patch_run(monkeypatch, {})
        assert wr.merged_prs(_kst(2026, 8, 17), _kst(2026, 8, 23)) == []

    def test_requests_merges_only(self, monkeypatch) -> None:
        calls: List[List[str]] = []
        _patch_run(monkeypatch, {}, calls)
        wr.merged_prs(_kst(2026, 8, 17), _kst(2026, 8, 23))
        assert "--merges" in calls[0]


# ---------------------------------------------------------------------------
# post_counts
# ---------------------------------------------------------------------------


class TestPostCounts:
    def _write(self, posts, *names: str) -> None:
        for name in names:
            (posts / name).write_text("x", encoding="utf-8")

    def test_missing_posts_dir_returns_empty(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(wr, "POSTS_DIR", str(tmp_path / "없음"))
        assert wr.post_counts(_kst(2026, 8, 17), _kst(2026, 8, 23)) == {}

    def test_counts_by_category(self, isolated_dirs) -> None:
        posts, _docs = isolated_dirs
        self._write(
            posts,
            "2026-08-18-daily-crypto-news-digest.md",
            "2026-08-19-daily-crypto-news-digest.md",
            "2026-08-20-daily-stock-news-digest.md",
        )
        counts = wr.post_counts(_kst(2026, 8, 17), _kst(2026, 8, 23))
        assert counts == {"암호화폐 뉴스": 2, "주식 시장": 1}

    def test_posts_outside_the_week_are_excluded(self, isolated_dirs) -> None:
        posts, _docs = isolated_dirs
        self._write(
            posts,
            "2026-08-16-daily-crypto-news-digest.md",  # 주 시작 전날
            "2026-08-17-daily-crypto-news-digest.md",  # 주 시작일 (포함)
            "2026-08-23-daily-crypto-news-digest.md",  # 주 종료일 (포함)
            "2026-08-24-daily-crypto-news-digest.md",  # 주 종료 다음날
        )
        assert wr.post_counts(_kst(2026, 8, 17), _kst(2026, 8, 23)) == {"암호화폐 뉴스": 2}

    def test_non_markdown_files_are_ignored(self, isolated_dirs) -> None:
        posts, _docs = isolated_dirs
        self._write(posts, "2026-08-18-daily-crypto-news-digest.txt", "README")
        assert wr.post_counts(_kst(2026, 8, 17), _kst(2026, 8, 23)) == {}

    def test_filenames_without_date_prefix_are_ignored(self, isolated_dirs) -> None:
        posts, _docs = isolated_dirs
        self._write(posts, "about-page.md")
        assert wr.post_counts(_kst(2026, 8, 17), _kst(2026, 8, 23)) == {}

    def test_invalid_date_is_ignored(self, isolated_dirs) -> None:
        """`\\d{4}-\\d{2}-\\d{2}` 를 통과하지만 실제 날짜가 아닌 경우."""
        posts, _docs = isolated_dirs
        self._write(posts, "2026-13-45-daily-crypto-news-digest.md")
        assert wr.post_counts(_kst(2026, 8, 17), _kst(2026, 8, 23)) == {}

    def test_unknown_slug_falls_into_기타(self, isolated_dirs) -> None:
        posts, _docs = isolated_dirs
        self._write(posts, "2026-08-18-알-수-없는-슬러그.md")
        assert wr.post_counts(_kst(2026, 8, 17), _kst(2026, 8, 23)) == {"기타": 1}

    def test_category_match_uses_first_key_in_cat_names_order(self, isolated_dirs) -> None:
        """`defi-tvl` 이 `defi` 보다 `CAT_NAMES` 에서 앞에 있어야 TVL 로 분류된다.

        dict 순회 순서에 의존하는 매핑이라, 키 순서를 바꾸면 분류가 조용히 달라진다.
        """
        posts, _docs = isolated_dirs
        self._write(posts, "2026-08-18-daily-defi-tvl-report.md")
        assert wr.post_counts(_kst(2026, 8, 17), _kst(2026, 8, 23)) == {"DeFi TVL": 1}
        keys = list(wr.CAT_NAMES)
        assert keys.index("defi-tvl") < keys.index("defi"), "CAT_NAMES 순서가 바뀌어 분류가 뒤집힌다"


# ---------------------------------------------------------------------------
# ci_summary
# ---------------------------------------------------------------------------


class TestCiSummary:
    def test_links_to_actions_dashboard(self) -> None:
        text = wr.ci_summary()
        assert "https://github.com/Twodragon0/investing/actions" in text
        assert "Code Quality (ruff)" in text


# ---------------------------------------------------------------------------
# 이미지 거부 지표 섹션
# ---------------------------------------------------------------------------


_SAMPLE_STATE = {
    "since": "2026-04-23T08:54:23",
    "last_seen": "2026-08-23T22:47:49",
    "families": {
        "bad_image": {"buckets": {"pixel": 42, "tracker": 18, "1x1-pixel": 9, "beacon": 3}},
        "logo": {"buckets": {"favicon": 5}},
    },
}


class TestImageRejectionSlackOneliner:
    def test_disabled_returns_empty(self, monkeypatch) -> None:
        monkeypatch.setattr(wr, "_METRICS_ENABLED", False)
        assert wr._render_image_rejection_slack_oneliner() == ""

    def test_top_three_buckets_sorted_desc(self, monkeypatch) -> None:
        monkeypatch.setattr(wr, "_METRICS_ENABLED", True)
        monkeypatch.setattr(wr, "_load_metrics_state", lambda: _SAMPLE_STATE)
        assert wr._render_image_rejection_slack_oneliner() == "이미지 거부 Top3: pixel=42, tracker=18, 1x1-pixel=9"

    def test_no_state_returns_empty(self, monkeypatch) -> None:
        monkeypatch.setattr(wr, "_METRICS_ENABLED", True)
        monkeypatch.setattr(wr, "_load_metrics_state", dict)
        assert wr._render_image_rejection_slack_oneliner() == ""

    def test_no_bad_image_family_returns_empty(self, monkeypatch) -> None:
        monkeypatch.setattr(wr, "_METRICS_ENABLED", True)
        monkeypatch.setattr(wr, "_load_metrics_state", lambda: {"families": {"logo": {"buckets": {"a": 1}}}})
        assert wr._render_image_rejection_slack_oneliner() == ""

    def test_output_is_single_line(self, monkeypatch) -> None:
        """워크플로우가 이 값을 한 줄로 캡처한다 — 개행이 들어가면 캡처가 깨진다."""
        monkeypatch.setattr(wr, "_METRICS_ENABLED", True)
        monkeypatch.setattr(wr, "_load_metrics_state", lambda: _SAMPLE_STATE)
        assert "\n" not in wr._render_image_rejection_slack_oneliner()


class TestImageRejectionSection:
    def test_disabled_emits_stub(self, monkeypatch) -> None:
        monkeypatch.setattr(wr, "_METRICS_ENABLED", False)
        section = wr._render_image_rejection_section()
        assert section.startswith("## 이미지 거부 패턴 통계")
        assert "metrics disabled 상태였습니다" in section

    def test_no_families_emits_different_stub(self, monkeypatch) -> None:
        """ "비활성" 과 "집계 없음" 은 원인이 달라 문구도 달라야 한다."""
        monkeypatch.setattr(wr, "_METRICS_ENABLED", True)
        monkeypatch.setattr(wr, "_load_metrics_state", dict)
        assert "집계된 거부 이벤트 없음" in wr._render_image_rejection_section()

    def test_renders_table_sorted_by_count_desc(self, monkeypatch) -> None:
        monkeypatch.setattr(wr, "_METRICS_ENABLED", True)
        monkeypatch.setattr(wr, "_load_metrics_state", lambda: _SAMPLE_STATE)
        section = wr._render_image_rejection_section()
        assert "| 패밀리 | 버킷 | 건수 |" in section
        rows = [ln for ln in section.splitlines() if ln.startswith("| bad_image |")]
        assert [r.split("|")[3].strip() for r in rows] == ["42", "18", "9", "3"]

    def test_families_are_sorted_by_name(self, monkeypatch) -> None:
        monkeypatch.setattr(wr, "_METRICS_ENABLED", True)
        monkeypatch.setattr(wr, "_load_metrics_state", lambda: _SAMPLE_STATE)
        section = wr._render_image_rejection_section()
        assert section.index("| bad_image |") < section.index("| logo |")

    def test_period_line_uses_state_timestamps(self, monkeypatch) -> None:
        monkeypatch.setattr(wr, "_METRICS_ENABLED", True)
        monkeypatch.setattr(wr, "_load_metrics_state", lambda: _SAMPLE_STATE)
        assert "- 기간: 2026-04-23T08:54:23 ~ 2026-08-23T22:47:49" in wr._render_image_rejection_section()

    def test_missing_timestamps_render_question_marks(self, monkeypatch) -> None:
        monkeypatch.setattr(wr, "_METRICS_ENABLED", True)
        monkeypatch.setattr(
            wr,
            "_load_metrics_state",
            lambda: {"since": "2026-01-01", "families": {"bad_image": {"buckets": {"a": 1}}}},
        )
        assert "- 기간: 2026-01-01 ~ ?" in wr._render_image_rejection_section()

    def test_period_line_omitted_without_timestamps(self, monkeypatch) -> None:
        monkeypatch.setattr(wr, "_METRICS_ENABLED", True)
        monkeypatch.setattr(wr, "_load_metrics_state", lambda: {"families": {"bad_image": {"buckets": {"a": 1}}}})
        assert "- 기간:" not in wr._render_image_rejection_section()


# ---------------------------------------------------------------------------
# build_report
# ---------------------------------------------------------------------------


class TestBuildReport:
    @pytest.fixture(autouse=True)
    def _quiet_metrics(self, monkeypatch):
        monkeypatch.setattr(wr, "_METRICS_ENABLED", False)
        monkeypatch.setattr(wr, "get_kst_now", lambda: _kst(2026, 8, 27, 15))

    def _report(self, monkeypatch, *, shortstat: str = "", oneline: str = "", merges: str = "") -> str:
        _patch_run(monkeypatch, {"--shortstat": shortstat, "--oneline": oneline, "--merges": merges})
        return wr.build_report(2026, 34, _kst(2026, 8, 17, 0), _kst(2026, 8, 23, 23))

    def test_header_shows_week_and_span(self, monkeypatch, isolated_dirs) -> None:
        report = self._report(monkeypatch)
        assert report.startswith("# W34 주간 성과 보고서 (2026-08-17 ~ 2026-08-23)")

    def test_all_sections_present(self, monkeypatch, isolated_dirs) -> None:
        report = self._report(monkeypatch)
        for heading in (
            "## 커밋/변경 통계",
            "## 주요 PR 및 기능",
            "## 수집기 현황",
            "## 이미지 거부 패턴 통계",
            "## 버그 수정 및 개선",
            "## CI/CD 상태",
            "## 다음 주 계획 (W35)",
        ):
            assert heading in report, heading

    def test_stats_table_is_thousand_separated(self, monkeypatch, isolated_dirs) -> None:
        report = self._report(
            monkeypatch,
            shortstat=" 1945 files changed, 23549 insertions(+), 2366 deletions(-)\n",
            oneline="\n".join(f"c{i} m" for i in range(199)),
        )
        assert "| 총 커밋 수 | 199 |" in report
        assert "| 변경 파일 수 | 1,945 |" in report
        assert "| 코드 추가 | +23,549 lines |" in report
        assert "| 코드 삭제 | -2,366 lines |" in report

    def test_no_prs_message(self, monkeypatch, isolated_dirs) -> None:
        assert "- (이번 주 병합된 PR 없음)" in self._report(monkeypatch)

    def test_prs_are_listed(self, monkeypatch, isolated_dirs) -> None:
        report = self._report(monkeypatch, merges="Merge pull request #1 from a\n")
        assert "- Merge pull request #1 from a" in report
        assert "| 병합 PR 수 | 1 |" in report

    def test_post_table_sorted_desc_with_total_row(self, monkeypatch, isolated_dirs) -> None:
        posts, _docs = isolated_dirs
        for name in (
            "2026-08-18-daily-crypto-news-digest.md",
            "2026-08-19-daily-crypto-news-digest.md",
            "2026-08-20-daily-stock-news-digest.md",
        ):
            (posts / name).write_text("x", encoding="utf-8")
        report = self._report(monkeypatch)
        assert report.index("| 암호화폐 뉴스 | 2 |") < report.index("| 주식 시장 | 1 |")
        assert "| **합계** | **3** |" in report
        assert "| 생성 포스트 수 | 3 |" in report

    def test_no_posts_message(self, monkeypatch, isolated_dirs) -> None:
        assert "| (데이터 없음) | 0 |" in self._report(monkeypatch)

    def test_next_week_wraps_at_week_52(self, monkeypatch, isolated_dirs) -> None:
        _patch_run(monkeypatch, {})
        report = wr.build_report(2026, 52, _kst(2026, 12, 21, 0), _kst(2026, 12, 27, 23))
        assert "## 다음 주 계획 (W01)" in report

    def test_next_week_increments_normally(self, monkeypatch, isolated_dirs) -> None:
        assert "## 다음 주 계획 (W35)" in self._report(monkeypatch)

    def test_footer_has_generated_timestamp(self, monkeypatch, isolated_dirs) -> None:
        assert "*자동 생성: 2026-08-27 15:00 KST*" in self._report(monkeypatch)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


class TestMain:
    def _run_main(self, monkeypatch, argv: List[str]) -> int:
        import sys

        monkeypatch.setattr(sys, "argv", ["generate_weekly_report.py", *argv])
        return wr.main()

    def test_slack_oneliner_prints_and_exits(self, monkeypatch, capsys) -> None:
        monkeypatch.setattr(wr, "_METRICS_ENABLED", True)
        monkeypatch.setattr(wr, "_load_metrics_state", lambda: _SAMPLE_STATE)
        assert self._run_main(monkeypatch, ["--slack-oneliner"]) == 0
        assert capsys.readouterr().out.strip() == "이미지 거부 Top3: pixel=42, tracker=18, 1x1-pixel=9"

    def test_slack_oneliner_does_not_write_a_report(self, monkeypatch, isolated_dirs, capsys) -> None:
        _posts, docs = isolated_dirs
        monkeypatch.setattr(wr, "_METRICS_ENABLED", False)
        self._run_main(monkeypatch, ["--slack-oneliner"])
        capsys.readouterr()
        assert list(docs.glob("*.md")) == []

    def test_negative_offset_is_rejected(self, monkeypatch, caplog) -> None:
        with caplog.at_level("ERROR"):
            assert self._run_main(monkeypatch, ["--week-offset", "-1"]) == 1
        assert any("--week-offset must be >= 0" in r.message for r in caplog.records)

    def test_writes_report_to_docs_dir(self, monkeypatch, isolated_dirs, frozen_now) -> None:
        _posts, docs = isolated_dirs
        monkeypatch.setattr(wr, "_METRICS_ENABLED", False)
        _patch_run(monkeypatch, {})
        assert self._run_main(monkeypatch, []) == 0

        written = list(docs.glob("*.md"))
        assert [p.name for p in written] == ["weekly-report-2026-w34.md"]
        assert written[0].read_text(encoding="utf-8").startswith("# W34 주간 성과 보고서")

    def test_existing_report_is_not_overwritten(self, monkeypatch, isolated_dirs, frozen_now, caplog) -> None:
        """이 가드가 사라지면 손으로 채운 리포트를 크론이 덮어쓴다."""
        _posts, docs = isolated_dirs
        target = docs / "weekly-report-2026-w34.md"
        target.write_text("손으로 채운 내용", encoding="utf-8")
        monkeypatch.setattr(wr, "_METRICS_ENABLED", False)
        _patch_run(monkeypatch, {})

        with caplog.at_level("INFO"):
            assert self._run_main(monkeypatch, []) == 0
        assert target.read_text(encoding="utf-8") == "손으로 채운 내용"
        assert any("Report already exists" in r.message for r in caplog.records)

    def test_force_overwrites(self, monkeypatch, isolated_dirs, frozen_now) -> None:
        _posts, docs = isolated_dirs
        target = docs / "weekly-report-2026-w34.md"
        target.write_text("낡은 내용", encoding="utf-8")
        monkeypatch.setattr(wr, "_METRICS_ENABLED", False)
        _patch_run(monkeypatch, {})

        assert self._run_main(monkeypatch, ["--force"]) == 0
        assert target.read_text(encoding="utf-8").startswith("# W34 주간 성과 보고서")

    def test_week_offset_selects_the_filename(self, monkeypatch, isolated_dirs, frozen_now) -> None:
        _posts, docs = isolated_dirs
        monkeypatch.setattr(wr, "_METRICS_ENABLED", False)
        _patch_run(monkeypatch, {})
        self._run_main(monkeypatch, ["--week-offset", "3"])
        assert [p.name for p in docs.glob("*.md")] == ["weekly-report-2026-w32.md"]

    def test_docs_dir_is_created_when_missing(self, tmp_path, monkeypatch, frozen_now) -> None:
        monkeypatch.setattr(wr, "POSTS_DIR", str(tmp_path / "_posts"))
        monkeypatch.setattr(wr, "DOCS_DIR", str(tmp_path / "docs"))
        monkeypatch.setattr(wr, "_METRICS_ENABLED", False)
        _patch_run(monkeypatch, {})
        assert self._run_main(monkeypatch, []) == 0
        assert (tmp_path / "docs" / "weekly-report-2026-w34.md").is_file()

    def test_build_failure_returns_1(self, monkeypatch, isolated_dirs, frozen_now, caplog) -> None:
        def boom(*_a, **_kw):
            raise RuntimeError("조립 실패")

        monkeypatch.setattr(wr, "build_report", boom)
        with caplog.at_level("ERROR"):
            assert self._run_main(monkeypatch, []) == 1
        assert any("Failed to build report" in r.message for r in caplog.records)

    def test_write_failure_returns_1(self, monkeypatch, isolated_dirs, frozen_now, caplog) -> None:
        _posts, docs = isolated_dirs
        monkeypatch.setattr(wr, "_METRICS_ENABLED", False)
        _patch_run(monkeypatch, {})

        real_open = open

        def failing_open(path, *args, **kwargs):
            if str(path).endswith("weekly-report-2026-w34.md"):
                raise OSError("디스크 꽉 찼음")
            return real_open(path, *args, **kwargs)

        monkeypatch.setattr("builtins.open", failing_open)
        with caplog.at_level("ERROR"):
            assert self._run_main(monkeypatch, []) == 1
        assert any("Failed to write report" in r.message for r in caplog.records)
