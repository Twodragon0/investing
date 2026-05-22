"""Tune CRITICAL_MEAN_TOP_3 and P0_ITEM_THRESHOLD from 30-day digest posts.

Usage:
    python3 scripts/tools/tune_risk_threshold.py \
        [--posts-dir _posts] \
        [--days 30] \
        [--target-critical-ratio 0.03] \
        [--output .omc/threshold_tuning_report.md]
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

_PROJECT_ROOT = Path(__file__).parent.parent.parent
_SCRIPTS_DIR = _PROJECT_ROOT / "scripts"
for _p in (str(_PROJECT_ROOT), str(_SCRIPTS_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from common.config import setup_logging  # noqa: E402
from common.risk_classifier import (  # noqa: E402
    CRITICAL_MEAN_TOP_3,
    P0_ITEM_THRESHOLD,
    score_item,
)

setup_logging()
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-daily-crypto-news-digest\.md$")

# Matches <a href="URL">TITLE</a> <span class="p0-desc">DESC</span> inside alert-urgent
_URGENT_LI_RE = re.compile(
    r'<li>\s*<a\s+href="(?P<href>[^"]*)"[^>]*>(?P<title>[^<]+)</a>\s*<span class="p0-desc">(?P<desc>[^<]*)</span>\s*</li>',
    re.DOTALL,
)

# Matches the alert-urgent block
_ALERT_URGENT_RE = re.compile(
    r'<div class="alert-box alert-urgent">(.*?)</div>',
    re.DOTALL,
)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class PostItems:
    date: str
    items: list[dict[str, str]] = field(default_factory=list)


@dataclass
class ThresholdResult:
    threshold: float
    critical_count: int
    total_posts: int

    @property
    def ratio(self) -> float:
        return self.critical_count / self.total_posts if self.total_posts else 0.0


# ---------------------------------------------------------------------------
# Post parsing
# ---------------------------------------------------------------------------


def load_digest_posts(posts_dir: Path, days: int) -> list[PostItems]:
    """Load recent N-day daily-crypto-news-digest posts, return parsed PostItems."""
    cutoff = datetime.now(UTC).date() - timedelta(days=days)
    results: list[PostItems] = []

    for path in sorted(posts_dir.glob("*-daily-crypto-news-digest.md")):
        m = _DATE_RE.match(path.name)
        if not m:
            continue
        try:
            post_date = datetime.strptime(m.group(1), "%Y-%m-%d").replace(tzinfo=UTC).date()
        except ValueError:
            continue
        if post_date < cutoff:
            continue

        text = path.read_text(encoding="utf-8")
        items = parse_priority_items(text)
        results.append(PostItems(date=m.group(1), items=items))
        logger.debug("Loaded %s: %d items", path.name, len(items))

    return results


def _source_from_href(href: str) -> str:
    """Derive a source string from a link URL.

    Strips ``www.`` and returns the netloc when parseable. For Google News
    redirect URLs this yields ``news.google.com`` (falls back to the legacy
    ``google news`` label so the aggregator weighting still applies).
    """
    if not href:
        return "google news"
    try:
        netloc = urlparse(href).netloc.lower()
    except Exception:
        return "google news"
    if not netloc:
        return "google news"
    if netloc.startswith("www."):
        netloc = netloc[4:]
    if netloc in {"news.google.com", "google.com"}:
        return "google news"
    return netloc


def parse_priority_items(text: str) -> list[dict[str, str]]:
    """Extract P0-level items from alert-urgent div in post body.

    Each item's ``source`` is derived from its link domain (preferring the
    real publisher domain so risk_classifier source weights actually apply).
    Google News redirect URLs collapse to ``"google news"`` (aggregator
    weight 1.0) as a safe legacy fallback.
    """
    items: list[dict[str, str]] = []

    block_m = _ALERT_URGENT_RE.search(text)
    if not block_m:
        return items

    block = block_m.group(1)
    for li_m in _URGENT_LI_RE.finditer(block):
        title = li_m.group("title").strip()
        desc = li_m.group("desc").strip()
        href = li_m.group("href").strip()
        if title:
            items.append(
                {
                    "title": title,
                    "description": desc,
                    "source": _source_from_href(href),
                }
            )

    return items


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------


def compute_aggregate_mean_top3(items: list[dict[str, str]]) -> float:
    """Score all items, return mean of top-3 scores."""
    if not items:
        return 0.0
    scored = sorted(
        [score_item(item).score for item in items],
        reverse=True,
    )
    top3 = scored[:3]
    return sum(top3) / len(top3)


def classify_posts_with_threshold(
    posts: list[PostItems],
    critical_mean_top3: float,
    p0_item_threshold: float,
) -> dict[str, int]:
    """Classify each post as critical/elevated/moderate/low under given thresholds."""
    counts: dict[str, int] = {"critical": 0, "elevated": 0, "moderate": 0, "low": 0}

    for post in posts:
        if not post.items:
            counts["low"] += 1
            continue

        scored = sorted(
            [score_item(item).score for item in post.items],
            reverse=True,
        )
        top3 = scored[:3]
        aggregate_mean = sum(top3) / len(top3) if top3 else 0.0

        p0_like = [s for s in scored if s >= p0_item_threshold]

        if len(p0_like) >= 3 and aggregate_mean >= critical_mean_top3:
            counts["critical"] += 1
        elif p0_like:
            counts["elevated"] += 1
        elif len([s for s in scored if s >= 3.5]) >= 2:
            counts["moderate"] += 1
        else:
            counts["low"] += 1

    return counts


# ---------------------------------------------------------------------------
# Binary search
# ---------------------------------------------------------------------------


def binary_search_critical_threshold(
    posts: list[PostItems],
    target_ratio: float,
    p0_threshold: float,
    lo: float = 2.0,
    hi: float = 10.0,
    iterations: int = 50,
) -> float:
    """Binary-search CRITICAL_MEAN_TOP_3 so critical ratio ≈ target_ratio."""
    for _ in range(iterations):
        mid = (lo + hi) / 2.0
        counts = classify_posts_with_threshold(posts, mid, p0_threshold)
        total = sum(counts.values())
        ratio = counts["critical"] / total if total else 0.0
        if ratio > target_ratio:
            lo = mid  # threshold too low → raise it
        else:
            hi = mid
        if hi - lo < 0.001:
            break
    return round((lo + hi) / 2.0, 2)


def binary_search_p0_threshold(
    posts: list[PostItems],
    target_ratio: float,
    critical_mean: float,
    lo: float = 0.5,
    hi: float = 10.0,
    iterations: int = 50,
) -> float:
    """Binary-search P0_ITEM_THRESHOLD so critical ratio ≈ target_ratio."""
    for _ in range(iterations):
        mid = (lo + hi) / 2.0
        counts = classify_posts_with_threshold(posts, critical_mean, mid)
        total = sum(counts.values())
        ratio = counts["critical"] / total if total else 0.0
        if ratio > target_ratio:
            lo = mid  # p0 threshold too low → raise it
        else:
            hi = mid
        if hi - lo < 0.001:
            break
    return round((lo + hi) / 2.0, 2)


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


def _distribution_table(counts: dict[str, int]) -> str:
    total = sum(counts.values())
    rows = []
    for level in ("critical", "elevated", "moderate", "low"):
        n = counts.get(level, 0)
        pct = n / total * 100 if total else 0.0
        rows.append(f"| {level} | {pct:.1f}% | {n} |")
    return "\n".join(rows)


def generate_report(
    posts: list[PostItems],
    target_ratio: float,
    recommended_critical: float,
    recommended_p0: float,
    days: int,
) -> str:
    today = datetime.now(UTC).date().isoformat()
    total_posts = len(posts)
    total_items = sum(len(p.items) for p in posts)

    if posts:
        min_date = min(p.date for p in posts)
        max_date = max(p.date for p in posts)
    else:
        min_date = max_date = today

    # Current distribution
    current_counts = classify_posts_with_threshold(posts, CRITICAL_MEAN_TOP_3, P0_ITEM_THRESHOLD)
    # Recommended distribution
    recommended_counts = classify_posts_with_threshold(posts, recommended_critical, recommended_p0)

    lines = [
        f"# Risk Threshold Tuning Report (generated {today})",
        "",
        "## 입력",
        f"- 기간: {min_date} ~ {max_date} ({total_posts} posts)",
        f"- 아이템 수: {total_items}건",
        f"- 목표 critical 비율: {target_ratio * 100:.1f}%",
        "",
        "## 현재 threshold 분포",
        f"- CRITICAL_MEAN_TOP_3: {CRITICAL_MEAN_TOP_3}",
        f"- P0_ITEM_THRESHOLD: {P0_ITEM_THRESHOLD}",
        "",
        "| 레벨 | 비율 | 건수 |",
        "|------|------|------|",
        _distribution_table(current_counts),
        "",
        "## 권장 threshold",
        f"- CRITICAL_MEAN_TOP_3: {CRITICAL_MEAN_TOP_3} → **{recommended_critical}**",
        f"- P0_ITEM_THRESHOLD: {P0_ITEM_THRESHOLD} → **{recommended_p0}**",
        "",
        "## 권장값 적용 시 분포",
        "",
        "| 레벨 | 비율 | 건수 |",
        "|------|------|------|",
        _distribution_table(recommended_counts),
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Tune risk thresholds from digest posts.")
    parser.add_argument("--posts-dir", default="_posts", help="Path to _posts directory")
    parser.add_argument("--days", type=int, default=30, help="Number of days to analyse")
    parser.add_argument(
        "--target-critical-ratio",
        type=float,
        default=0.03,
        help="Target fraction of posts classified as CRITICAL (default: 0.03)",
    )
    parser.add_argument(
        "--output",
        default=".omc/threshold_tuning_report.md",
        help="Output report path",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    posts_dir = Path(args.posts_dir)
    if not posts_dir.is_dir():
        logger.error("posts-dir not found: %s", posts_dir)
        return 2

    posts = load_digest_posts(posts_dir, args.days)
    if not posts:
        logger.warning("No digest posts found in the last %d days under %s", args.days, posts_dir)
        return 1

    logger.info("Loaded %d posts with %d total items", len(posts), sum(len(p.items) for p in posts))

    # Binary-search thresholds
    recommended_critical = binary_search_critical_threshold(
        posts,
        target_ratio=args.target_critical_ratio,
        p0_threshold=P0_ITEM_THRESHOLD,
    )
    recommended_p0 = binary_search_p0_threshold(
        posts,
        target_ratio=args.target_critical_ratio,
        critical_mean=recommended_critical,
    )

    report = generate_report(
        posts,
        target_ratio=args.target_critical_ratio,
        recommended_critical=recommended_critical,
        recommended_p0=recommended_p0,
        days=args.days,
    )

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")

    print(f"Report written to: {output_path}")
    logger.info(
        "Recommended CRITICAL_MEAN_TOP_3=%.2f P0_ITEM_THRESHOLD=%.2f",
        recommended_critical,
        recommended_p0,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
