#!/usr/bin/env python3
"""Validate post-summary regression on recently built Jekyll posts.

Reads ``_site/`` rendered HTML, finds the post-summary section in each post
within the last N days, and flags low-quality summaries via two passes:

Negative checks (issue found → fail):
- empty or whitespace-only ``<p>``
- raw HTML leaking through ``strip_html`` (means the body's first paragraph
  started with a HTML block instead of natural-language lead)
- pure count-only excerpts (``N건 수집`` without other context)
- too-short (< 30 chars) excerpts

Positive validation (any one signal must be present):
- numeric tokens with units/currency/percent
- proper nouns / acronyms / tickers (BTC, KOSPI, ...)
- quoted phrases or Korean colon-introduced headline clauses
A body that passes the negative checks but carries no positive signal is
flagged as ``no-signal`` (filler-only excerpt).

Designed to run weekly in CI (``.github/workflows/check-post-summary.yml``).
Exits 1 with a structured report when regressions exceed the threshold.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SITE_DIR = _REPO_ROOT / "_site"

# Ensure scripts/ is importable when invoked as `python3 scripts/check_post_summary.py`.
if str(_REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "scripts"))

from common.summary_quality import has_positive_signal  # noqa: E402

# Capture the <p>...</p> inside the post-summary section
_POST_SUMMARY_RE = re.compile(
    r'<section class="post-summary">.*?<p>(?P<body>.*?)</p>\s*</section>',
    re.DOTALL,
)

# Post URL prefix → date extraction (e.g. /crypto-news/2026/05/22/...)
_POST_DATE_RE = re.compile(r"/(\d{4})/(\d{2})/(\d{2})/")

# Patterns that indicate low-quality summary
_LEAKED_HTML_RE = re.compile(r"<[a-zA-Z][^>]*>")
_PURE_COUNT_RE = re.compile(
    r"^[\d\s,.\-]*[\d]+\s*(건|종|개)[\s.,]*$",  # e.g. "47건 수집." with no other content
)


@dataclass
class SummaryFinding:
    path: Path
    post_date: str
    body: str
    issue: str


def _extract_post_date(path: Path) -> str:
    """Best-effort date extraction from rendered post URL."""
    rel = path.relative_to(_SITE_DIR).as_posix()
    m = _POST_DATE_RE.search("/" + rel)
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else "unknown"


def _classify(body: str) -> str | None:
    """Return issue label if body has a regression, else None.

    Order: empty → html-leak → pure-count → too-short → no-signal.
    ``no-signal`` flags filler-only summaries that pass length/HTML checks but
    lack any positive marker (number, proper noun, headline lead-in).
    """
    stripped = body.strip()
    if not stripped:
        return "empty"
    if _LEAKED_HTML_RE.search(stripped):
        return "html-leak"
    if _PURE_COUNT_RE.match(stripped):
        return "pure-count"
    if len(stripped) < 30:
        return "too-short"
    if not has_positive_signal(stripped):
        return "no-signal"
    return None


def scan_site(days: int) -> list[SummaryFinding]:
    """Walk ``_site/`` for post HTMLs within the cutoff and surface regressions."""
    if not _SITE_DIR.exists():
        raise SystemExit(f"_site not found at {_SITE_DIR}; run `bundle exec jekyll build` first")

    cutoff = (datetime.now(UTC) - timedelta(days=days)).date().isoformat()
    findings: list[SummaryFinding] = []

    for html_path in _SITE_DIR.rglob("index.html"):
        post_date = _extract_post_date(html_path)
        if post_date == "unknown" or post_date < cutoff:
            continue
        text = html_path.read_text(encoding="utf-8", errors="ignore")
        m = _POST_SUMMARY_RE.search(text)
        if not m:
            continue  # no post-summary section (some pages skip the layout)
        body = m.group("body")
        issue = _classify(body)
        if issue:
            findings.append(SummaryFinding(html_path, post_date, body[:120], issue))

    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description="Post-summary regression check")
    parser.add_argument("--days", type=int, default=7, help="Look back N days (default: 7)")
    parser.add_argument(
        "--max-failures",
        type=int,
        default=0,
        help="Allow up to N regressions before exit 1 (default: 0 — strict mode)",
    )
    args = parser.parse_args()

    findings = scan_site(days=args.days)
    if not findings:
        print(f"OK: no post-summary regressions in last {args.days} days")
        return 0

    print(f"Found {len(findings)} post-summary regression(s) in last {args.days} days:\n")
    for f in findings:
        rel = f.path.relative_to(_REPO_ROOT).as_posix()
        print(f"  [{f.issue}] {f.post_date}  {rel}")
        print(f"    body: {f.body!r}")

    if len(findings) > args.max_failures:
        print(f"\nFAIL: {len(findings)} regressions exceed --max-failures={args.max_failures}")
        return 1
    print(f"\nWARN: {len(findings)} regressions within tolerance (--max-failures={args.max_failures})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
