"""Tests for scripts/tools/fix_untranslated_body.py.

The defect being repaired is not a selection bug — it is a *silent* one.
``common.translator.translate_to_korean`` returns its input when the Google
Translate call raises and logs at ``DEBUG``, so a transient failure during a
collection run publishes English prose and nothing ever retries it.

Measured on 2026-09-02: three of the longest-standing findings
(``Velocity Financial (VEL) legal chief sells shares…``,
``Insider at Trilogy Metals (TMQ) logs new share trades…``,
``Trump tariffs take $11 billion toll on Ohio Axios``) were absent from
``_state/translation_cache.json`` and every one of them translated on a later
call — the pipeline had simply given up on them.

These tests therefore fix the two properties a repair pass must have:
it must actually replace the English, and it must refuse to write when
translation did not help (fail-open must not become fail-destructive).
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from tools.check_untranslated_body import scan_lines, split_front_matter  # noqa: E402
from tools.fix_untranslated_body import fix_post, resolve_files  # noqa: E402

_ENGLISH_LINE = "The Federal Reserve signalled a rate cut as price pressures continued to cool this quarter."
_KOREAN_LINE = "연방준비제도가 물가 압력 완화를 근거로 금리 인하 가능성을 시사했습니다."
_FRONT_MATTER = '---\ntitle: "t"\nlang: "ko"\n---\n'


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


def _write_post(posts_dir: Path, name: str, body: str) -> Path:
    path = posts_dir / name
    path.write_text(f"{_FRONT_MATTER}\n{body}\n", encoding="utf-8")
    return path


class TestSplitFrontMatter:
    """``split_body`` is defined in terms of this, so the halves must rejoin."""

    def test_halves_rejoin_to_the_original(self):
        text = f"{_FRONT_MATTER}\n{_KOREAN_LINE}\n"
        head, body = split_front_matter(text)
        assert head + body == text

    def test_no_front_matter_yields_empty_head(self):
        head, body = split_front_matter("본문만 있다")
        assert head == ""
        assert body == "본문만 있다"


class TestFixPost:
    def test_translates_and_writes_when_applying(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "tools.fix_untranslated_body.translate_untranslated_body",
            lambda body: body.replace(_ENGLISH_LINE, _KOREAN_LINE),
        )
        path = _write_post(tmp_path, f"{_today()}-a.md", _ENGLISH_LINE)
        before, after = fix_post(path, apply=True)
        assert (before, after) == (1, 0)
        written = path.read_text(encoding="utf-8")
        assert _KOREAN_LINE in written
        assert _ENGLISH_LINE not in written
        assert written.startswith(_FRONT_MATTER), "front matter must survive verbatim"

    def test_preserves_the_trailing_newline(self, tmp_path, monkeypatch):
        """``translate_untranslated_body`` rebuilds the body with
        ``"\\n".join(splitlines())``, which drops the final newline. Writing that
        back marks every repaired post "\\ No newline at end of file" — noise in
        the diff of an auto-committing repo, on a line nobody edited."""
        monkeypatch.setattr(
            "tools.fix_untranslated_body.translate_untranslated_body",
            lambda body: body.replace(_ENGLISH_LINE, _KOREAN_LINE).rstrip("\n"),
        )
        path = _write_post(tmp_path, f"{_today()}-a.md", _ENGLISH_LINE)
        assert path.read_text(encoding="utf-8").endswith("\n")
        fix_post(path, apply=True)
        assert path.read_text(encoding="utf-8").endswith("\n")

    def test_does_not_add_a_newline_to_a_file_that_lacked_one(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "tools.fix_untranslated_body.translate_untranslated_body",
            lambda body: body.replace(_ENGLISH_LINE, _KOREAN_LINE),
        )
        path = tmp_path / f"{_today()}-a.md"
        path.write_text(f"{_FRONT_MATTER}\n{_ENGLISH_LINE}", encoding="utf-8")
        fix_post(path, apply=True)
        assert not path.read_text(encoding="utf-8").endswith("\n")

    def test_dry_run_reports_without_writing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "tools.fix_untranslated_body.translate_untranslated_body",
            lambda body: body.replace(_ENGLISH_LINE, _KOREAN_LINE),
        )
        path = _write_post(tmp_path, f"{_today()}-a.md", _ENGLISH_LINE)
        original = path.read_text(encoding="utf-8")
        before, after = fix_post(path, apply=False)
        assert (before, after) == (1, 0)
        assert path.read_text(encoding="utf-8") == original

    def test_refuses_to_write_when_translation_did_not_help(self, tmp_path, monkeypatch):
        """Fail-open translation returns its input. Rewriting the file then
        burns a commit and hides the failure behind a "fixed" report."""
        monkeypatch.setattr(
            "tools.fix_untranslated_body.translate_untranslated_body",
            lambda body: body,
        )
        path = _write_post(tmp_path, f"{_today()}-a.md", _ENGLISH_LINE)
        original = path.read_text(encoding="utf-8")
        before, after = fix_post(path, apply=True)
        assert (before, after) == (1, 1)
        assert path.read_text(encoding="utf-8") == original

    def test_refuses_to_write_a_change_that_is_not_an_improvement(self, tmp_path, monkeypatch):
        """The dangerous case is a body that *changed* without getting better —
        one English line swapped for another. An identity mock cannot catch a
        missing guard here, because writing the unchanged body is invisible.
        """
        other_english = "Congressional filings show a second round of share purchases across the caucus."
        monkeypatch.setattr(
            "tools.fix_untranslated_body.translate_untranslated_body",
            lambda body: body.replace(_ENGLISH_LINE, other_english),
        )
        path = _write_post(tmp_path, f"{_today()}-a.md", _ENGLISH_LINE)
        original = path.read_text(encoding="utf-8")
        before, after = fix_post(path, apply=True)
        assert (before, after) == (1, 1)
        assert path.read_text(encoding="utf-8") == original, "a lateral change must not be written"

    def test_refuses_to_write_when_line_count_changes(self, tmp_path, monkeypatch):
        """The translator must preserve markdown structure. A body that gained
        or lost lines means it mangled the post, so the finding count dropping
        is not evidence of success."""
        monkeypatch.setattr(
            "tools.fix_untranslated_body.translate_untranslated_body",
            lambda body: _KOREAN_LINE,
        )
        path = _write_post(tmp_path, f"{_today()}-a.md", _ENGLISH_LINE)
        original = path.read_text(encoding="utf-8")
        before, after = fix_post(path, apply=True)
        assert before == 1
        assert after == 1, "a structural change must be reported as unfixed"
        assert path.read_text(encoding="utf-8") == original

    def test_clean_post_is_a_no_op(self, tmp_path, monkeypatch):
        def _boom(body: str) -> str:
            raise AssertionError("must not call the translator for a clean post")

        monkeypatch.setattr("tools.fix_untranslated_body.translate_untranslated_body", _boom)
        path = _write_post(tmp_path, f"{_today()}-a.md", _KOREAN_LINE)
        assert fix_post(path, apply=True) == (0, 0)


class TestMultiPass:
    """A single pass measurably under-repairs: on the 2026-08-04..09-02 corpus
    pass 1 went 151 → 13 and pass 2 went 13 → 0 with no code change between."""

    SECOND_ENGLISH = "Congressional filings show a second round of share purchases across the caucus."

    def _one_line_per_call(self):
        order = [(_ENGLISH_LINE, _KOREAN_LINE), (self.SECOND_ENGLISH, _KOREAN_LINE)]

        def _translate(body: str) -> str:
            for english, korean in order:
                if english in body:
                    return body.replace(english, korean)
            return body

        return _translate

    def test_retries_until_no_further_improvement(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "tools.fix_untranslated_body.translate_untranslated_body",
            self._one_line_per_call(),
        )
        path = _write_post(tmp_path, f"{_today()}-a.md", f"{_ENGLISH_LINE}\n{self.SECOND_ENGLISH}")
        assert fix_post(path, apply=True) == (2, 0), "a single pass would leave 1 finding"

    def test_stops_calling_once_a_pass_stops_improving(self, tmp_path, monkeypatch):
        calls = []

        def _translate(body: str) -> str:
            calls.append(body)
            return body

        monkeypatch.setattr("tools.fix_untranslated_body.translate_untranslated_body", _translate)
        path = _write_post(tmp_path, f"{_today()}-a.md", _ENGLISH_LINE)
        assert fix_post(path, apply=True) == (1, 1)
        assert len(calls) == 1, "an unimprovable post must not burn every pass"


class TestResolveFiles:
    """The collector feeds this its created-post manifest."""

    def test_accepts_posts_inside_posts_dir(self, tmp_path):
        path = _write_post(tmp_path, f"{_today()}-a.md", _KOREAN_LINE)
        assert resolve_files(tmp_path, [str(path)]) == [path]

    def test_rejects_paths_outside_posts_dir(self, tmp_path):
        posts_dir = tmp_path / "_posts"
        posts_dir.mkdir()
        outside = tmp_path / "elsewhere.md"
        outside.write_text("x", encoding="utf-8")
        assert resolve_files(posts_dir, [str(outside)]) == []

    def test_ignores_missing_and_non_markdown(self, tmp_path):
        other = tmp_path / "note.txt"
        other.write_text("x", encoding="utf-8")
        assert resolve_files(tmp_path, [str(other), str(tmp_path / "gone.md")]) == []


class TestSharedDetection:
    """Detector and fixer must not drift: both count with ``scan_lines``."""

    def test_fixer_counts_with_the_checkers_detector(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "tools.fix_untranslated_body.translate_untranslated_body",
            lambda body: body.replace(_ENGLISH_LINE, _KOREAN_LINE),
        )
        path = _write_post(tmp_path, f"{_today()}-a.md", f"{_ENGLISH_LINE}\n{_KOREAN_LINE}")
        _, body = split_front_matter(path.read_text(encoding="utf-8"))
        assert len(scan_lines(body)) == 1
        assert fix_post(path, apply=True) == (1, 0)
