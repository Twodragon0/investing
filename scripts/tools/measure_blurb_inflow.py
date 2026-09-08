#!/usr/bin/env python3
"""Measure the English-blurb *inflow* rate from each post's creation blob.

``check_description_quality.py`` reports the rate over the working tree, which
is the right question for "what does the site look like now" and the wrong one
for "how many leaks are we still publishing". The backfill
(``fix_post_url_summaries.py``, plus the daily
``backfill-url-summaries.yml``) repairs those same posts afterwards, so counting
current state measures the repair, not the inflow.

Each post's creation blob is still in git, so the measurement is **retroactive
and immune to later repair**: the number for a given day is the same whether it
is taken that day or a month later. That is why this exists as a query rather
than as a cron step appending to a log — the record is already in the history,
and a run-log line expires in 90 days.

Usage:
    python scripts/tools/measure_blurb_inflow.py                       # since the
                                                                       # translation-gate fix
    python scripts/tools/measure_blurb_inflow.py --since <ref-or-date>
    python scripts/tools/measure_blurb_inflow.py --json

Read the output as: ``at_birth`` is the inflow, ``now`` is the current state,
and their difference is what the backfill has recovered so far.
"""

from __future__ import annotations

import argparse
import json
import subprocess as sp
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from check_description_quality import count_blurb_language  # noqa: E402

# The enrichment translation-gate fix (#1283). Posts created before it carry the
# whole-string-gate leak, so it is the natural default baseline.
DEFAULT_SINCE = "f2b7d6386b79475cd2132d3cd99d2cf2dc2c9db5"


@dataclass(frozen=True)
class InflowReport:
    """Blurb-language counts for posts created after a baseline ref."""

    posts: int
    english_at_birth: int
    total_at_birth: int
    english_now: int
    total_now: int

    @property
    def rate_at_birth(self) -> float | None:
        """Share of blurbs published in English, or ``None`` over zero blurbs.

        ``None`` rather than ``0.0``: "no blurbs were published" and "no blurb
        was English" are different findings, and a caller plotting the second
        as zero would read an empty window as a perfect one.
        """
        if not self.total_at_birth:
            return None
        return self.english_at_birth / self.total_at_birth

    @property
    def rate_now(self) -> float | None:
        if not self.total_now:
            return None
        return self.english_now / self.total_now

    @property
    def repaired_since_birth(self) -> int:
        """English blurbs present at creation that are no longer English."""
        return max(0, self.english_at_birth - self.english_now)


def _git(repo_root: Path, *args: str) -> str:
    return sp.run(
        ["git", *args],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def posts_added_since(repo_root: Path, base_ref: str) -> list[str]:
    """Repo-relative paths of ``_posts`` entries added after ``base_ref``."""
    out = _git(repo_root, "diff", "--name-only", "--diff-filter=A", base_ref, "HEAD", "--", "_posts/")
    return [line for line in out.split("\n") if line.strip()]


def creation_blob(repo_root: Path, post_path: str) -> str:
    """The post's body as first committed, or ``""`` if the add cannot be found."""
    commit = _git(repo_root, "log", "--format=%H", "--diff-filter=A", "-1", "--", post_path).strip()
    if not commit:
        return ""
    return _git(repo_root, "show", f"{commit}:{post_path}")


def measure(repo_root: Path, base_ref: str = DEFAULT_SINCE) -> InflowReport:
    """Count blurb languages at creation and now for posts added since ``base_ref``."""
    paths = posts_added_since(repo_root, base_ref)
    e_birth = t_birth = e_now = t_now = 0
    counted = 0
    for rel in paths:
        born = creation_blob(repo_root, rel)
        if not born:
            continue
        counted += 1
        e, t = count_blurb_language(born)
        e_birth += e
        t_birth += t
        # A post deleted after creation has no current state; its creation-time
        # contribution still counts, so this is a skip rather than a failure.
        current = repo_root / rel
        if current.is_file():
            e2, t2 = count_blurb_language(current.read_text(encoding="utf-8", errors="replace"))
            e_now += e2
            t_now += t2
    return InflowReport(
        posts=counted,
        english_at_birth=e_birth,
        total_at_birth=t_birth,
        english_now=e_now,
        total_now=t_now,
    )


def _format(report: InflowReport, base_ref: str) -> str:
    def pct(rate: float | None) -> str:
        return "n/a" if rate is None else f"{100 * rate:.2f}%"

    return "\n".join(
        [
            f"영어 blurb 유입률 (기준: {base_ref[:12]})",
            f"  대상 포스트   : {report.posts}",
            f"  생성 시점     : {report.english_at_birth}/{report.total_at_birth} ({pct(report.rate_at_birth)})",
            f"  현재 상태     : {report.english_now}/{report.total_now} ({pct(report.rate_now)})",
            f"  백필이 복구   : {report.repaired_since_birth}",
        ]
    )


def main() -> int:
    # A literal, not `__doc__.split(...)`: `__doc__` is `None` under `-OO`, and
    # basedpyright rejects the member access outright (reportOptionalMemberAccess).
    parser = argparse.ArgumentParser(
        description="Measure the English-blurb inflow rate from each post's creation blob."
    )
    parser.add_argument(
        "--since",
        default=DEFAULT_SINCE,
        help="기준 커밋/태그/날짜 (기본: #1283 번역 게이트 수정 커밋)",
    )
    parser.add_argument("--json", action="store_true", help="JSON 출력")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent.parent
    report = measure(repo_root, args.since)

    if args.json:
        print(
            json.dumps(
                {
                    "since": args.since,
                    "posts": report.posts,
                    "english_at_birth": report.english_at_birth,
                    "total_at_birth": report.total_at_birth,
                    "rate_at_birth": report.rate_at_birth,
                    "english_now": report.english_now,
                    "total_now": report.total_now,
                    "rate_now": report.rate_now,
                    "repaired_since_birth": report.repaired_since_birth,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(_format(report, args.since))
    return 0


if __name__ == "__main__":
    sys.exit(main())
