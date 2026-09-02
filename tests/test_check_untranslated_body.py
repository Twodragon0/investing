"""Tests for scripts/tools/check_untranslated_body.py.

The check this replaces never inspected a single post. `post-quality.yml:55`
selected files with ``find _posts -name "*.md" -newer /tmp/quality-report.txt``,
but that report is written by an earlier step of the same job — after checkout
has already written every post — so it was always newer than all of them.
``find`` exits 0 on no matches, so the ``|| find … | tail -20`` fallback never
fired either.

CI evidence (run 33591232799): the step printed ``Untranslated lines found: 0``
**9.8 ms** after starting. Scanning even 20 posts line-by-line with per-line
subshells takes seconds.

The tests below therefore fix two properties, not one: the detection must work,
and an empty scan must be an error rather than a green no-op.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from tools.check_untranslated_body import (  # noqa: E402
    is_untranslated,
    scan,
    select_posts,
    split_body,
)

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "tools" / "check_untranslated_body.py"

_ENGLISH_LINE = "The Federal Reserve signalled a rate cut as price pressures continued to cool this quarter."
_KOREAN_LINE = "연방준비제도가 물가 압력 완화를 근거로 금리 인하 가능성을 시사했습니다."


def _write_post(posts_dir: Path, name: str, body: str) -> Path:
    path = posts_dir / name
    path.write_text(f'---\ntitle: "t"\n---\n\n{body}\n', encoding="utf-8")
    return path


class TestSplitBody:
    def test_drops_front_matter(self):
        assert split_body('---\ntitle: "a"\n---\n\n본문\n').strip() == "본문"

    def test_passes_through_when_no_front_matter(self):
        assert split_body("본문만 있다").strip() == "본문만 있다"


class TestIsUntranslated:
    def test_english_prose_is_flagged(self):
        assert is_untranslated(_ENGLISH_LINE)

    def test_korean_prose_is_not_flagged(self):
        assert not is_untranslated(_KOREAN_LINE)

    def test_short_line_is_not_judged(self):
        """Headings, tickers, and table cells carry too few letters to judge."""
        assert not is_untranslated("BTC ETF")

    def test_korean_quoting_english_is_not_flagged(self):
        line = "미국 증권거래위원회(SEC)가 현물 비트코인 ETF 상장을 승인했다고 밝혔습니다. Bloomberg 보도."
        assert not is_untranslated(line)


class TestSelectPostsUsesFilenameDate:
    def test_selects_by_filename_not_mtime(self, tmp_path):
        """mtime was the bug. An old post rewritten today must stay out."""
        old = _write_post(tmp_path, "2020-01-01-old.md", "본문")
        recent_name = f"{__import__('datetime').datetime.now(__import__('datetime').UTC).date().isoformat()}-new.md"
        new = _write_post(tmp_path, recent_name, "본문")
        old.touch()  # rewritten "now" — mtime is newer than the recent post
        selected = select_posts(tmp_path, days=7)
        assert selected == [new]


class TestScan:
    def test_finds_english_body_line(self, tmp_path):
        name = f"{__import__('datetime').datetime.now(__import__('datetime').UTC).date().isoformat()}-a.md"
        _write_post(tmp_path, name, _ENGLISH_LINE)
        scanned, findings = scan(tmp_path, days=7)
        assert scanned == 1
        assert len(findings) == 1

    def test_ignores_markup_and_urls(self, tmp_path):
        """HTML blocks, tables, and raw links are ASCII by construction."""
        name = f"{__import__('datetime').datetime.now(__import__('datetime').UTC).date().isoformat()}-b.md"
        body = "\n".join(
            [
                '<div class="news-card"><span>Federal Reserve signals a rate cut soon</span></div>',
                "| Symbol | Price | Change | Volume | Market Cap | Notes about it |",
                "https://www.example.com/federal-reserve-signals-a-rate-cut-this-quarter",
                "## Federal Reserve signals a rate cut as pressures cool",
                _KOREAN_LINE,
            ]
        )
        _write_post(tmp_path, name, body)
        scanned, findings = scan(tmp_path, days=7)
        assert scanned == 1
        assert findings == []


class TestCliGuardsAgainstEmptyScan:
    """The failure this replaces was a check that inspected nothing and passed."""

    def _run(self, posts_dir: Path, *extra: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(_SCRIPT), "--posts-dir", str(posts_dir), *extra],
            capture_output=True,
            text=True,
        )

    def test_empty_scan_is_an_error(self, tmp_path):
        result = self._run(tmp_path)
        assert result.returncode == 1
        assert "min-files" in result.stderr

    def test_non_empty_scan_succeeds(self, tmp_path):
        name = f"{__import__('datetime').datetime.now(__import__('datetime').UTC).date().isoformat()}-a.md"
        _write_post(tmp_path, name, _KOREAN_LINE)
        result = self._run(tmp_path)
        assert result.returncode == 0, result.stderr
        assert "Posts scanned" in result.stdout

    def test_max_findings_can_fail_the_step(self, tmp_path):
        name = f"{__import__('datetime').datetime.now(__import__('datetime').UTC).date().isoformat()}-a.md"
        _write_post(tmp_path, name, _ENGLISH_LINE)
        result = self._run(tmp_path, "--max-findings", "0")
        assert result.returncode == 1
        assert "상한" in result.stderr

    def test_findings_are_advisory_by_default(self, tmp_path):
        name = f"{__import__('datetime').datetime.now(__import__('datetime').UTC).date().isoformat()}-a.md"
        _write_post(tmp_path, name, _ENGLISH_LINE)
        result = self._run(tmp_path)
        assert result.returncode == 0
        assert "Untranslated lines found: 1" in result.stdout


class TestWorkflowWiring:
    """`post-quality.yml` must not reintroduce either vacuous check."""

    WORKFLOW = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "post-quality.yml"

    @staticmethod
    def _run_bodies(path: Path) -> str:
        import yaml

        cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
        steps = ((cfg or {}).get("jobs") or {}).get("quality", {}).get("steps") or []
        return "\n".join(str(step.get("run", "")) for step in steps)

    def test_no_mtime_based_selection(self):
        assert "-newer" not in self._run_bodies(self.WORKFLOW), (
            "post-quality.yml 이 다시 mtime 으로 대상을 고른다 — 리포트 파일이 항상 더 새로워 0건이 된다."
        )

    def test_issue_count_reads_the_scripts_own_summary(self):
        """`grep -c 'would fix|would change|would clean'` never matched: the
        dry-run prints `[DRY] <file>: …` lines and a `Posts modified: N`
        summary. Measured — 36 output lines, 0 pattern matches, 26 `[DRY]`."""
        body = self._run_bodies(self.WORKFLOW)
        assert "would fix" not in body, "실제 출력과 맞지 않는 grep 패턴이 되살아났다"
        assert "Posts modified" in body, "스크립트가 스스로 보고하는 요약 줄을 읽어야 한다"

    def test_untranslated_check_uses_the_script(self):
        assert "check_untranslated_body.py" in self._run_bodies(self.WORKFLOW)

    def test_untranslated_check_is_not_advisory_only(self):
        """Advisory reported 106 findings on the 7-day window and blocked
        nothing. Without ``--max-findings`` the step is a report, not a gate."""
        assert "--max-findings" in self._run_bodies(self.WORKFLOW), (
            "상한이 사라졌다 — 검사가 다시 advisory 로 돌아가 회귀를 통과시킨다."
        )


class TestCollectorRetryWiring:
    """The cap in ``post-quality.yml`` only holds because the collector retries.

    ``translate_to_korean`` is fail-open with no retry, so untranslated lines
    re-accumulate at roughly 15/day. Remove the retry step and the cap of 10
    fails within days — these two changes are load-bearing for each other.
    """

    ACTION = Path(__file__).resolve().parent.parent / ".github" / "actions" / "python-collect" / "action.yml"

    def test_action_retries_translation_on_created_posts(self):
        import yaml

        cfg = yaml.safe_load(self.ACTION.read_text(encoding="utf-8"))
        bodies = "\n".join(str(step.get("run", "")) for step in (cfg or {}).get("runs", {}).get("steps") or [])
        assert "fix_untranslated_body.py" in bodies, (
            "번역 재시도 스텝이 사라졌다 — post-quality.yml 의 --max-findings 상한이 곧 터진다."
        )
        assert "CREATED_POSTS_MANIFEST" in bodies, "재시도는 매니페스트가 고른 신규 포스트만 대상으로 해야 한다"
