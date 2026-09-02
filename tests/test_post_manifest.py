"""Posts created by a run are recorded explicitly, not inferred from mtime.

`.github/actions/python-collect` identified "newly generated posts" with
``find _posts/ -newer /tmp/collect-start-marker``. That returns every file whose
mtime changed, which includes posts a backfill script merely rewrote — the step
name said "newly generated" but the query said "recently touched".

The concrete consequence: on 2026-09-01 `backfill_post_summaries.py` rewrote
`_posts/2026-08-27-daily-geopolitical-risk-report.md`, the action then fed it to
`improve_existing_posts.py`, and PR #1259's excerpt backfill was reverted
(commit 6880034f5), leaving main failing `check_post_summary`.

The manifest moves the question "what is new?" from the filesystem to the code
that actually creates posts. Scripts that only modify posts never write to it,
so they drop out of downstream processing without needing a flag anyone could
forget to set.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from common.post_manifest import MANIFEST_ENV_VAR, read_manifest, record_created_post


@pytest.fixture
def manifest_path(tmp_path, monkeypatch):
    path = tmp_path / "created-posts.txt"
    monkeypatch.setenv(MANIFEST_ENV_VAR, str(path))
    return path


class TestRecordCreatedPost:
    def test_appends_one_line_per_post(self, manifest_path):
        record_created_post("/repo/_posts/2026-09-02-a.md")
        record_created_post("/repo/_posts/2026-09-02-b.md")
        assert manifest_path.read_text(encoding="utf-8").splitlines() == [
            "/repo/_posts/2026-09-02-a.md",
            "/repo/_posts/2026-09-02-b.md",
        ]

    def test_is_a_noop_without_the_env_var(self, tmp_path, monkeypatch):
        """Local runs and tests must not litter the filesystem."""
        monkeypatch.delenv(MANIFEST_ENV_VAR, raising=False)
        record_created_post(str(tmp_path / "_posts" / "x.md"))
        assert list(tmp_path.iterdir()) == []

    def test_ignores_empty_path(self, manifest_path):
        record_created_post("")
        record_created_post(None)  # type: ignore[arg-type]
        assert not manifest_path.exists()

    def test_read_manifest_returns_empty_when_absent(self, manifest_path):
        assert read_manifest() == []

    def test_read_manifest_skips_blank_lines(self, manifest_path):
        manifest_path.write_text("a.md\n\n  \nb.md\n", encoding="utf-8")
        assert read_manifest() == ["a.md", "b.md"]

    def test_recording_failure_does_not_break_the_caller(self, tmp_path, monkeypatch):
        """A manifest write must never take down a collection run."""
        monkeypatch.setenv(MANIFEST_ENV_VAR, str(tmp_path / "missing-dir" / "m.txt"))
        record_created_post("/repo/_posts/x.md")  # must not raise


class TestPostGeneratorRecordsCreatedPosts:
    """`PostGenerator.create_post` is the choke point for 14 of the 15 creation
    sites (13 collectors via `BaseCollector`, plus `generate_weekly_digest.py`)."""

    def test_created_post_is_recorded(self, manifest_path, tmp_path):
        from common.post_generator import PostGenerator

        posts_dir = tmp_path / "_posts"
        posts_dir.mkdir()
        with patch("common.post_generator.POSTS_DIR", str(posts_dir)):
            gen = PostGenerator("crypto-news")
            filepath = gen.create_post(title="비트코인 시세 점검", content="본문입니다. 총 3건 수집.\n\n## 요약\n")
        assert filepath is not None
        assert manifest_path.read_text(encoding="utf-8").splitlines() == [filepath]

    def test_skipped_post_is_not_recorded(self, manifest_path, tmp_path):
        """A duplicate filename returns None — nothing was created, so nothing
        may be recorded."""
        from common.post_generator import PostGenerator

        posts_dir = tmp_path / "_posts"
        posts_dir.mkdir()
        with patch("common.post_generator.POSTS_DIR", str(posts_dir)):
            gen = PostGenerator("crypto-news")
            first = gen.create_post(title="비트코인 시세 점검", content="본문입니다. 총 3건 수집.\n\n## 요약\n")
            second = gen.create_post(title="비트코인 시세 점검", content="본문입니다. 총 3건 수집.\n\n## 요약\n")
        assert first is not None
        assert second is None
        assert manifest_path.read_text(encoding="utf-8").splitlines() == [first]


class TestModifierScriptsDoNotRecord:
    """The property that makes the manifest safe: scripts that only rewrite
    existing posts never touch `PostGenerator.create_post`, so they cannot land
    in the manifest — no opt-out flag to forget."""

    @pytest.mark.parametrize(
        "script",
        [
            "scripts/backfill_post_summaries.py",
            "scripts/backfill_images.py",
            "scripts/improve_existing_posts.py",
        ],
    )
    def test_modifier_scripts_do_not_import_the_recorder(self, script: str):
        src = Path(__file__).resolve().parent.parent / script
        text = src.read_text(encoding="utf-8")
        assert "record_created_post" not in text, (
            f"{script} 는 기존 포스트를 수정만 한다 — 매니페스트에 기록하면 "
            "후속 처리 대상이 되어 mtime 방식의 문제가 되돌아온다."
        )


class TestActionUsesManifestNotMtime:
    """The action must not fall back to asking the filesystem what is new.

    These guards read the parsed ``run:`` bodies, never the raw file. A
    whole-file search would match this change's own explanatory comments — the
    same trap recorded for YAML guards in this repo, just inverted: instead of
    passing forever it would fail forever, and the obvious "fix" is to delete
    the comment rather than the behaviour.
    """

    ACTION = Path(__file__).resolve().parent.parent / ".github" / "actions" / "python-collect" / "action.yml"

    @staticmethod
    def _run_bodies(path: Path) -> str:
        import yaml

        cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
        steps = ((cfg or {}).get("runs") or {}).get("steps") or []
        return "\n".join(str(step.get("run", "")) for step in steps)

    def test_action_does_not_use_find_newer(self):
        assert "-newer" not in self._run_bodies(self.ACTION), (
            "python-collect 액션이 다시 mtime 으로 신규 포스트를 판별한다. "
            "매니페스트(CREATED_POSTS_MANIFEST)를 읽어야 한다."
        )

    def test_action_exports_the_manifest_path(self):
        assert MANIFEST_ENV_VAR in self._run_bodies(self.ACTION), f"액션이 {MANIFEST_ENV_VAR} 를 설정하지 않는다"

    def test_manifest_path_is_run_scoped(self):
        """`collect-data` 동시성 그룹을 공유하는 잡들이 같은 러너 경로를 쓰면 섞인다."""
        assert "GITHUB_RUN_ID" in self._run_bodies(self.ACTION), "매니페스트 경로에 런 고유값이 없다"


def test_manifest_env_var_name_is_stable():
    """The action and the recorder must agree on the variable name.

    Renaming one side without the other makes every downstream step a silent
    no-op while the job stays green.
    """
    assert MANIFEST_ENV_VAR == "CREATED_POSTS_MANIFEST"
