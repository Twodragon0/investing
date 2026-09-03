#!/usr/bin/env python3
"""Report post body lines that look untranslated (predominantly ASCII).

Advisory check for `.github/workflows/post-quality.yml`. It replaces an inline
bash loop whose file selection was
``find _posts -name "*.md" -newer /tmp/quality-report.txt``. That report file is
written by an *earlier step of the same job*, after checkout has already written
every post, so it was always newer than all of them and the ``find`` returned
nothing. ``find`` exits 0 on no matches, so the ``||`` fallback never fired
either: the loop body never ran once. Real CI evidence (run 33591232799) — the
step printed its result 9.8 ms after starting, and reported
``Untranslated lines found: 0``.

Selection here is by **filename date**, not mtime: deterministic, bounded, and
never silently empty. ``--min-files`` makes an empty scan an error instead of a
green no-op, because a check that inspects nothing is worse than no check — it
reports success.

The ASCII threshold comes from ``common.summary_quality`` so this and
``check_description_quality.py`` cannot drift apart.
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "scripts"))

from common.summary_quality import ASCII_RATIO_THRESHOLD, ascii_ratio  # noqa: E402

_POST_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-")
_HANGUL_RE = re.compile(r"[가-힣]")
# Lines shorter than this are headings, table cells, and tickers — too short for
# a language judgement, and the same floor the report uses for descriptions.
_MIN_ALPHA = 30


def split_front_matter(text: str) -> tuple[str, str]:
    """Return ``(front_matter, body)``; the halves concatenate to *text*.

    ``fix_untranslated_body.py`` rewrites only the body, so it needs the head
    back verbatim. Splitting in one place keeps the writer from disagreeing
    with the reader about where the body starts.
    """
    if not text.startswith("---"):
        return "", text
    closing = text.find("\n---", 3)
    if closing == -1:
        return "", text
    return text[: closing + 4], text[closing + 4 :]


def split_body(text: str) -> str:
    """Return the post body, dropping YAML front matter."""
    return split_front_matter(text)[1]


def is_untranslated(line: str) -> bool:
    """True if the line carries enough letters to judge and reads as English.

    A line containing Hangul is Korean prose that quotes English entity names
    ("주요 공격 유형: Spot Price Manipulation(2건)", "Freight Technologies(FRGT)
    내부자가 …"), not an untranslated line. Judging those by ASCII ratio alone
    produced 196 findings on the 2026 corpus, mostly of that shape — and an
    advisory check that noisy gets ignored, which is the no-op it replaces.
    Untranslated means the translation never happened, so there is no Hangul.
    """
    alpha = sum(1 for c in line if c.isalpha())
    if alpha < _MIN_ALPHA:
        return False
    if _HANGUL_RE.search(line):
        return False
    return ascii_ratio(line) > ASCII_RATIO_THRESHOLD


def _is_scannable(line: str) -> bool:
    """Skip markup-only lines: HTML blocks, tables, links, and raw URLs carry
    ASCII by construction and say nothing about translation quality."""
    stripped = line.strip()
    if not stripped or stripped.startswith(("<", "|", "#", "!", ">", "```")):
        return False
    return "http://" not in stripped and "https://" not in stripped


def select_posts(posts_dir: Path, days: int) -> list[Path]:
    """Return posts whose *filename* date falls within the window."""
    cutoff = (datetime.now(UTC) - timedelta(days=days)).date().isoformat()
    selected = []
    for path in sorted(posts_dir.glob("*.md")):
        match = _POST_DATE_RE.match(path.name)
        if match and match.group(1) >= cutoff:
            selected.append(path)
    return selected


def scan_lines(body: str) -> list[str]:
    """Return the untranslated-looking lines of a post *body*.

    The single detection entry point. ``fix_untranslated_body.py`` measures
    before/after with this same function so a repair pass cannot report success
    against a laxer rule than the check that reports the finding.
    """
    return [line.strip() for line in body.splitlines() if _is_scannable(line) and is_untranslated(line)]


def scan(posts_dir: Path, days: int) -> tuple[int, list[tuple[Path, str]]]:
    """Return (files_scanned, findings)."""
    findings: list[tuple[Path, str]] = []
    posts = select_posts(posts_dir, days)
    for path in posts:
        body = split_body(path.read_text(encoding="utf-8", errors="ignore"))
        for line in scan_lines(body):
            findings.append((path, line[:120]))
    return len(posts), findings


def main() -> int:
    parser = argparse.ArgumentParser(description="Detect untranslated English in post bodies")
    parser.add_argument("--days", type=int, default=7, help="Look back N days by filename date (default: 7)")
    parser.add_argument("--posts-dir", default=str(_REPO_ROOT / "_posts"))
    parser.add_argument(
        "--min-files",
        type=int,
        default=1,
        help="Fail if fewer than N posts were scanned — an empty scan must not report success (default: 1)",
    )
    parser.add_argument(
        "--max-findings",
        type=int,
        default=-1,
        help="Exit 1 when findings exceed N. Negative means advisory only (default: -1)",
    )
    args = parser.parse_args()

    posts_dir = Path(args.posts_dir)
    if not posts_dir.is_dir():
        print(f"posts dir not found: {posts_dir}", file=sys.stderr)
        return 2

    scanned, findings = scan(posts_dir, args.days)
    print(f"Posts scanned (last {args.days}d by filename date): {scanned}")
    for path, line in findings:
        print(f"::warning file={path.as_posix()}::Untranslated: {line}")
    print(f"Untranslated lines found: {len(findings)}")

    if scanned < args.min_files:
        print(
            f"::error::스캔한 포스트가 {scanned}건으로 --min-files={args.min_files} 미달 — "
            "검사가 실제로 아무것도 보지 않았다. 대상 선정이 깨졌는지 확인하라.",
            file=sys.stderr,
        )
        return 1
    if args.max_findings >= 0 and len(findings) > args.max_findings:
        print(f"::error::번역 누락 의심 {len(findings)}건이 상한 {args.max_findings} 을 넘었다", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
