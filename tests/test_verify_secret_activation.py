"""tests/test_verify_secret_activation.py — verify_secret_activation 단위 테스트.

Secret 활성화(TWITTER_BEARER_TOKEN, GSC_SERVICE_ACCOUNT_JSON) 전후 효과를
비교하는 리포트 생성기. ``gh`` CLI 호출은 ``subprocess.run``을 모킹해
절대 실제로 실행되지 않도록 하고, 시간 의존 로직은 ``datetime``을 고정
서브클래스로 교체해 결정적으로 구동한다.
"""

import datetime as dt_module
import json
import subprocess
import sys

import verify_secret_activation as vsa

_HOST_UNUSED = None  # placeholder to keep import block simple


class _Namespace:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def _fixed_datetime(monkeypatch, year=2026, month=7, day=20, hour=12, minute=0):
    """Freeze ``vsa.datetime.now()`` while keeping strptime/replace semantics.

    Subclassing the real ``datetime`` preserves ``strptime`` and ``replace``
    behaviour (they return instances of ``cls``), so only ``now`` needs
    overriding.
    """

    class _FixedDateTime(dt_module.datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(year, month, day, hour, minute, tzinfo=tz)

    monkeypatch.setattr(vsa, "datetime", _FixedDateTime)
    return _FixedDateTime(year, month, day, hour, minute, tzinfo=dt_module.UTC)


# ---------------------------------------------------------------------------
# _extract_int
# ---------------------------------------------------------------------------


class TestExtractInt:
    def test_match_returns_int(self):
        assert vsa._extract_int(vsa._TOTAL_RE, "총 14건이 수집되었습니다") == 14

    def test_no_match_returns_default(self):
        assert vsa._extract_int(vsa._TOTAL_RE, "no match here", default=7) == 7

    def test_no_match_default_zero(self):
        assert vsa._extract_int(vsa._TWITTER_RE, "nothing") == 0


# ---------------------------------------------------------------------------
# _avg
# ---------------------------------------------------------------------------


class TestAvg:
    def test_empty_list(self):
        assert vsa._avg([]) == 0.0

    def test_average(self):
        assert vsa._avg([1, 2, 3]) == 2.0


# ---------------------------------------------------------------------------
# _delta_pct
# ---------------------------------------------------------------------------


class TestDeltaPct:
    def test_both_zero_returns_na(self):
        assert vsa._delta_pct(0, 0) == "N/A"

    def test_baseline_zero_recent_positive_returns_infinity(self):
        assert vsa._delta_pct(0, 5) == "+∞"

    def test_positive_delta_has_plus_sign(self):
        assert vsa._delta_pct(10, 20) == "+100.0%"

    def test_negative_delta_has_minus_sign(self):
        assert vsa._delta_pct(10, 5) == "-50.0%"


# ---------------------------------------------------------------------------
# parse_social_digest
# ---------------------------------------------------------------------------


class TestParseSocialDigest:
    def test_total_present_uses_stat_grid_breakdown(self, tmp_path):
        p = tmp_path / "2026-07-20-daily-social-media-digest.md"
        p.write_text(
            "총 14건이 수집되었습니다\n\n"
            '<div class="stat-item"><span class="stat-value">1</span>'
            '<span class="stat-label">소셜 미디어</span></div>\n'
            '<div class="stat-item"><span class="stat-value">13</span>'
            '<span class="stat-label">정치·경제</span></div>\n'
            '<div class="stat-item"><span class="stat-value">0</span>'
            '<span class="stat-label">텔레그램</span></div>\n',
            encoding="utf-8",
        )
        m = vsa.parse_social_digest(p)
        assert m.date == "2026-07-20"
        assert m.total_items == 14
        assert m.social_items == 1
        assert m.political_items == 13
        assert m.telegram_items == 0

    def test_zero_total_falls_back_to_stat_sum(self, tmp_path):
        p = tmp_path / "2026-07-20-daily-social-media-digest.md"
        p.write_text(
            '<div class="stat-item"><span class="stat-value">2</span>'
            '<span class="stat-label">소셜 미디어</span></div>\n'
            '<div class="stat-item"><span class="stat-value">3</span>'
            '<span class="stat-label">정치·경제</span></div>\n'
            '<div class="stat-item"><span class="stat-value">1</span>'
            '<span class="stat-label">텔레그램</span></div>\n',
            encoding="utf-8",
        )
        m = vsa.parse_social_digest(p)
        assert m.total_items == 6  # 2 + 1 + 3, summed as fallback
        assert m.social_items == 2
        assert m.telegram_items == 1
        assert m.political_items == 3

    def test_missing_spans_all_zero(self, tmp_path):
        p = tmp_path / "2026-07-20-daily-social-media-digest.md"
        p.write_text("no structured data here at all", encoding="utf-8")
        m = vsa.parse_social_digest(p)
        assert m.total_items == 0
        assert m.social_items == 0
        assert m.telegram_items == 0
        assert m.political_items == 0
        assert m.twitter_items == 0

    def test_date_fallback_when_filename_does_not_match_pattern(self, tmp_path):
        p = tmp_path / "2026-07-20-something-else.md"
        p.write_text("no data", encoding="utf-8")
        m = vsa.parse_social_digest(p)
        assert m.date == "2026-07-20"  # falls back to path.name[:10]

    def test_sentence_level_twitter_and_telegram_override_stat_default(self, tmp_path):
        p = tmp_path / "2026-07-20-daily-social-media-digest.md"
        # "총 N건이 수집" only matches at line-start (^ with MULTILINE), so it
        # must be on its own line — separate from the sentence-level twitter/
        # telegram counts, which match anywhere in the text.
        p.write_text(
            "소셜 미디어 5건, 텔레그램 9건, 정치·경제 0건\n총 14건이 수집되었습니다\n",
            encoding="utf-8",
        )
        m = vsa.parse_social_digest(p)
        assert m.total_items == 14
        assert m.twitter_items == 5
        assert m.telegram_items == 9


# ---------------------------------------------------------------------------
# collect_social_metrics — POSTS_DIR monkeypatched to tmp_path, time frozen
# ---------------------------------------------------------------------------


class TestCollectSocialMetrics:
    def test_baseline_recent_bucketing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(vsa, "POSTS_DIR", tmp_path)
        _fixed_datetime(monkeypatch, year=2026, month=7, day=20, hour=12)

        recent_post = tmp_path / "2026-07-20-daily-social-media-digest.md"
        recent_post.write_text("총 1건이 수집되었습니다", encoding="utf-8")

        baseline_post = tmp_path / "2026-07-15-daily-social-media-digest.md"
        baseline_post.write_text("총 2건이 수집되었습니다", encoding="utf-8")

        too_old_post = tmp_path / "2026-07-10-daily-social-media-digest.md"
        too_old_post.write_text("총 3건이 수집되었습니다", encoding="utf-8")

        baseline, recent = vsa.collect_social_metrics(baseline_days=7, observe_hours=24)

        assert [m.date for m in recent] == ["2026-07-20"]
        assert [m.date for m in baseline] == ["2026-07-15"]

    def test_no_matching_posts_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr(vsa, "POSTS_DIR", tmp_path)
        _fixed_datetime(monkeypatch)
        (tmp_path / "not-a-digest.md").write_text("irrelevant", encoding="utf-8")
        baseline, recent = vsa.collect_social_metrics(baseline_days=7, observe_hours=24)
        assert baseline == []
        assert recent == []


# ---------------------------------------------------------------------------
# render_twitter_report
# ---------------------------------------------------------------------------


class TestRenderTwitterReport:
    def test_empty_baseline_and_recent_warns(self):
        out = vsa.render_twitter_report([], [], observe_hours=24)
        assert "경고: baseline 포스트 없음" in out
        assert "최근 24h 포스트 없음" in out
        assert "TWITTER_BEARER_TOKEN 등록 후" in out

    def test_verdict_improved(self):
        baseline = [vsa.PostMetrics("2026-07-10", 5, 1, 1, 3, 1)]
        recent = [vsa.PostMetrics("2026-07-20", 10, 5, 1, 4, 5)]
        out = vsa.render_twitter_report(baseline, recent, observe_hours=24)
        assert "판정: 개선" in out

    def test_verdict_inactive_when_both_zero(self):
        baseline = [vsa.PostMetrics("2026-07-10", 5, 0, 1, 3, 0)]
        recent = [vsa.PostMetrics("2026-07-20", 5, 0, 1, 3, 0)]
        out = vsa.render_twitter_report(baseline, recent, observe_hours=24)
        assert "판정: 미활성" in out

    def test_verdict_no_change(self):
        baseline = [vsa.PostMetrics("2026-07-10", 5, 3, 1, 3, 3)]
        recent = [vsa.PostMetrics("2026-07-20", 5, 2, 1, 3, 2)]
        out = vsa.render_twitter_report(baseline, recent, observe_hours=24)
        assert "판정: 변화 없음" in out


# ---------------------------------------------------------------------------
# render_gsc_report
# ---------------------------------------------------------------------------


class TestRenderGscReport:
    def test_no_runs_at_all(self):
        out = vsa.render_gsc_report([], [], observe_hours=24)
        assert "gh CLI 미응답" in out

    def test_verdict_active(self):
        recent = [vsa.GscRunInfo("1", "success", "2026-07-20T00:00:00Z", None)]
        out = vsa.render_gsc_report([], recent, observe_hours=24)
        assert "판정: 활성" in out

    def test_verdict_running_but_error(self):
        recent = [vsa.GscRunInfo("1", "failure", "2026-07-20T00:00:00Z", None)]
        out = vsa.render_gsc_report([], recent, observe_hours=24)
        assert "판정: 실행 중이나 오류" in out

    def test_verdict_waiting(self):
        baseline = [vsa.GscRunInfo("1", "success", "2026-07-10T00:00:00Z", None)]
        out = vsa.render_gsc_report(baseline, [], observe_hours=24)
        assert "판정: 대기 중" in out


# ---------------------------------------------------------------------------
# build_parser
# ---------------------------------------------------------------------------


class TestBuildParser:
    def test_defaults(self):
        parser = vsa.build_parser()
        args = parser.parse_args([])
        assert args.secret == "both"  # noqa: S105 -- CLI choice value, not a credential
        assert args.baseline_days == 7
        assert args.observe_hours == 24
        assert args.output == "markdown"


# ---------------------------------------------------------------------------
# _run_gh
# ---------------------------------------------------------------------------


class TestRunGh:
    def test_success(self, monkeypatch):
        def _fake_run(cmd, capture_output, text, timeout):
            assert cmd[0] == "gh"
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="ok\n", stderr="")

        monkeypatch.setattr(subprocess, "run", _fake_run)
        ok, out = vsa._run_gh(["run", "list"])
        assert ok is True
        assert out == "ok"

    def test_failure_returncode(self, monkeypatch):
        def _fake_run(cmd, capture_output, text, timeout):
            return subprocess.CompletedProcess(cmd, returncode=1, stdout="", stderr="bad\n")

        monkeypatch.setattr(subprocess, "run", _fake_run)
        ok, out = vsa._run_gh(["run", "list"])
        assert ok is False
        assert out == "bad"

    def test_gh_not_found(self, monkeypatch):
        def _fake_run(cmd, capture_output, text, timeout):
            raise FileNotFoundError("gh missing")

        monkeypatch.setattr(subprocess, "run", _fake_run)
        ok, out = vsa._run_gh(["run", "list"])
        assert ok is False
        assert "설치" in out

    def test_timeout(self, monkeypatch):
        def _fake_run(cmd, capture_output, text, timeout):
            raise subprocess.TimeoutExpired(cmd=cmd, timeout=timeout)

        monkeypatch.setattr(subprocess, "run", _fake_run)
        ok, out = vsa._run_gh(["run", "list"])
        assert ok is False
        assert "타임아웃" in out


# ---------------------------------------------------------------------------
# fetch_gsc_runs
# ---------------------------------------------------------------------------


class TestFetchGscRuns:
    def test_json_ok(self, monkeypatch):
        payload = [{"databaseId": 1, "conclusion": "success", "startedAt": "2026-07-20T00:00:00Z"}]
        monkeypatch.setattr(vsa, "_run_gh", lambda args: (True, json.dumps(payload)))
        result = vsa.fetch_gsc_runs(limit=5)
        assert result == payload

    def test_gh_failure_returns_empty(self, monkeypatch):
        monkeypatch.setattr(vsa, "_run_gh", lambda args: (False, "error"))
        assert vsa.fetch_gsc_runs() == []

    def test_malformed_json_returns_empty(self, monkeypatch):
        monkeypatch.setattr(vsa, "_run_gh", lambda args: (True, "not json"))
        assert vsa.fetch_gsc_runs() == []


# ---------------------------------------------------------------------------
# collect_gsc_runs
# ---------------------------------------------------------------------------


class TestCollectGscRuns:
    def test_iso8601_bucketing_and_malformed_skip(self, monkeypatch):
        _fixed_datetime(monkeypatch, year=2026, month=7, day=20, hour=12)
        runs = [
            {"databaseId": 1, "conclusion": "success", "startedAt": "2026-07-20T00:00:00Z"},  # recent
            {"databaseId": 2, "conclusion": "success", "startedAt": "2026-07-15T00:00:00Z"},  # baseline
            {"databaseId": 3, "conclusion": "success", "startedAt": "2026-07-01T00:00:00Z"},  # too old
            {"databaseId": 4, "conclusion": "success", "startedAt": "not-a-date"},  # malformed, skipped
            {"databaseId": 5, "status": "in_progress", "startedAt": "2026-07-20T01:00:00Z"},  # no conclusion
        ]
        monkeypatch.setattr(vsa, "fetch_gsc_runs", lambda limit=30: runs)
        baseline, recent = vsa.collect_gsc_runs(baseline_days=7, observe_hours=24)
        assert [r.run_id for r in recent] == ["1", "5"]
        assert [r.run_id for r in baseline] == ["2"]
        assert [r for r in recent if r.run_id == "5"][0].conclusion == "in_progress"


# ---------------------------------------------------------------------------
# _fetch_artifact_indexed_count
# ---------------------------------------------------------------------------


class TestFetchArtifactIndexedCount:
    def test_success_parses_indexed_count(self, monkeypatch):
        def _fake_run(cmd, capture_output, text, timeout):
            assert cmd[0] == "gh"
            dir_index = cmd.index("--dir") + 1
            target_dir = cmd[dir_index]
            (__import__("pathlib").Path(target_dir) / "summary.txt").write_text(
                "Run summary\nIndexed: 42\n", encoding="utf-8"
            )
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

        monkeypatch.setattr(subprocess, "run", _fake_run)
        assert vsa._fetch_artifact_indexed_count("123") == 42

    def test_download_failure_returns_none(self, monkeypatch):
        def _fake_run(cmd, capture_output, text, timeout):
            return subprocess.CompletedProcess(cmd, returncode=1, stdout="", stderr="fail")

        monkeypatch.setattr(subprocess, "run", _fake_run)
        assert vsa._fetch_artifact_indexed_count("123") is None

    def test_no_matching_pattern_returns_none(self, monkeypatch):
        def _fake_run(cmd, capture_output, text, timeout):
            dir_index = cmd.index("--dir") + 1
            target_dir = cmd[dir_index]
            (__import__("pathlib").Path(target_dir) / "summary.txt").write_text("no relevant data\n", encoding="utf-8")
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

        monkeypatch.setattr(subprocess, "run", _fake_run)
        assert vsa._fetch_artifact_indexed_count("123") is None


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


class TestMain:
    def test_secret_twitter_only(self, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv", ["verify_secret_activation.py", "--secret", "twitter"])
        monkeypatch.setattr(vsa, "collect_social_metrics", lambda baseline_days, observe_hours: ([], []))
        monkeypatch.setattr(
            vsa,
            "collect_gsc_runs",
            lambda baseline_days, observe_hours: (_ for _ in ()).throw(AssertionError("gsc should not run")),
        )
        rc = vsa.main()
        assert rc == 0
        out = capsys.readouterr().out
        assert "Twitter/X Secret" in out
        assert "GSC Secret" not in out

    def test_secret_gsc_only(self, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv", ["verify_secret_activation.py", "--secret", "gsc"])
        monkeypatch.setattr(
            vsa,
            "collect_social_metrics",
            lambda baseline_days, observe_hours: (_ for _ in ()).throw(AssertionError("twitter should not run")),
        )
        monkeypatch.setattr(vsa, "collect_gsc_runs", lambda baseline_days, observe_hours: ([], []))
        rc = vsa.main()
        assert rc == 0
        out = capsys.readouterr().out
        assert "GSC Secret" in out
        assert "Twitter/X Secret" not in out

    def test_secret_both(self, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv", ["verify_secret_activation.py", "--secret", "both"])
        monkeypatch.setattr(vsa, "collect_social_metrics", lambda baseline_days, observe_hours: ([], []))
        monkeypatch.setattr(vsa, "collect_gsc_runs", lambda baseline_days, observe_hours: ([], []))
        rc = vsa.main()
        assert rc == 0
        out = capsys.readouterr().out
        assert "Twitter/X Secret" in out
        assert "GSC Secret" in out
