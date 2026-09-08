"""Tests for `scripts/tools/measure_blurb_inflow.py`.

The question the tool answers — "what share of blurbs are published in English?"
— cannot be answered from the working tree, because the backfill repairs those
same posts afterwards. Counting current state measures the backfill, not the
inflow.

Each post's *creation* blob is still in git, so the measurement is retroactive
and immune to later repair. The immunity test below is the reason this tool
exists rather than a `--days 1` cron step: it builds a repo where the creation
state and the current state disagree, and pins that the tool reports the former.
"""

from __future__ import annotations

import importlib
import subprocess as sp
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

inflow = importlib.import_module("tools.measure_blurb_inflow")


ENGLISH_BLURB = (
    '<p class="news-desc">U.S. President Donald Trump posted a stream of AI-generated '
    "images and a series of sweeping and unverified claims on Truth Social on Sunday</p>"
)
KOREAN_BLURB = (
    '<p class="news-desc">도널드 트럼프 미국 대통령이 일요일 트루스소셜에 AI 생성 이미지와 '
    "검증되지 않은 주장을 잇달아 게시했습니다.</p>"
)
CLEAN_BLURB = '<p class="news-desc">국내 기관 투자자들이 비트코인 현물 ETF 보유를 늘렸습니다.</p>'


def _git(repo: Path, *args: str) -> str:
    return sp.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
        env={
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.com",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.com",
            "PATH": "/usr/bin:/bin:/usr/local/bin",
            "HOME": str(repo),
        },
    ).stdout


def _post(body: str) -> str:
    return f"---\ntitle: 테스트\n---\n\n{body}\n"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repo with a baseline commit, then two posts added after it."""
    r = tmp_path / "repo"
    (r / "_posts").mkdir(parents=True)
    _git(r, "init", "-q", "-b", "main")
    (r / "README.md").write_text("baseline\n", encoding="utf-8")
    _git(r, "add", "README.md")
    _git(r, "commit", "-q", "-m", "baseline")

    (r / "_posts" / "2026-09-08-a.md").write_text(_post(ENGLISH_BLURB), encoding="utf-8")
    (r / "_posts" / "2026-09-08-b.md").write_text(_post(CLEAN_BLURB), encoding="utf-8")
    _git(r, "add", "_posts")
    _git(r, "commit", "-q", "-m", "collect news")
    return r


def _baseline(repo: Path) -> str:
    return _git(repo, "rev-list", "--max-parents=0", "HEAD").strip()


def test_counts_blurbs_in_posts_added_since_the_base(repo: Path) -> None:
    report = inflow.measure(repo, _baseline(repo))
    assert report.posts == 2
    assert report.total_at_birth == 2
    assert report.english_at_birth == 1


def test_immune_to_a_later_backfill_repair(repo: Path) -> None:
    """The whole point: repairing the post must not move the inflow number.

    Without reading the creation blob this returns 0 and the measurement
    silently reports the backfill's success as an absence of leaks.
    """
    before = inflow.measure(repo, _baseline(repo))

    # Simulate the backfill translating the English blurb in place.
    (repo / "_posts" / "2026-09-08-a.md").write_text(_post(KOREAN_BLURB), encoding="utf-8")
    _git(repo, "add", "_posts")
    _git(repo, "commit", "-q", "-m", "backfill url summaries")

    after = inflow.measure(repo, _baseline(repo))

    assert after.english_at_birth == before.english_at_birth == 1, (
        "inflow moved after a repair — the tool is reading current state, not the creation blob"
    )
    # And the current-state figure *should* move, which is what makes the
    # assertion above discriminating rather than a tautology.
    assert after.english_now == 0
    assert before.english_now == 1
    assert after.repaired_since_birth == 1


def test_posts_deleted_after_creation_drop_out_of_the_population(repo: Path) -> None:
    """A post added *and* deleted after the base is not in the population.

    `git diff --diff-filter=A base HEAD` is a two-point diff, so a file with no
    net presence at HEAD carries no `A` status — it is simply absent. That is
    the right population for "what we publish and still have", and the
    assertion records the semantics so a future reader does not mistake it for
    a bug. Posts are not deleted in this repo; the case is pinned so the tool
    cannot start crashing on it.
    """
    (repo / "_posts" / "2026-09-08-b.md").unlink()
    _git(repo, "add", "-A", "_posts")
    _git(repo, "commit", "-q", "-m", "remove post")

    report = inflow.measure(repo, _baseline(repo))
    assert report.posts == 1
    # The surviving post is the English one, so the inflow figure is unaffected
    # by the deletion of the clean one.
    assert report.english_at_birth == 1
    assert report.total_at_birth == 1


def test_no_posts_since_base_reports_zero_not_a_crash(repo: Path) -> None:
    head = _git(repo, "rev-parse", "HEAD").strip()
    report = inflow.measure(repo, head)
    assert report.posts == 0
    assert report.total_at_birth == 0
    assert report.rate_at_birth is None, "a rate over zero blurbs must be None, not 0.0 or a ZeroDivisionError"


def test_rate_is_reported_as_a_share(repo: Path) -> None:
    report = inflow.measure(repo, _baseline(repo))
    assert report.rate_at_birth == pytest.approx(0.5)
