#!/usr/bin/env python3
"""Generate weekly performance report for the investing project.

Collects data from git history and _posts/ directory for a given ISO week,
then writes a Korean markdown report to docs/weekly-report-YYYY-wWW.md.

Usage:
    python scripts/generate_weekly_report.py              # last week (default)
    python scripts/generate_weekly_report.py --week-offset 2
    python scripts/generate_weekly_report.py --week-offset 1 --force
"""

import argparse
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common.config import get_kst_now, setup_logging

logger = setup_logging("generate_weekly_report")

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
POSTS_DIR = os.path.join(REPO_ROOT, "_posts")
DOCS_DIR = os.path.join(REPO_ROOT, "docs")

CAT_NAMES: Dict[str, str] = {
    "crypto-news": "암호화폐 뉴스",
    "stock-news": "주식 시장",
    "security-alerts": "보안 알림",
    "market-analysis": "시장 분석",
    "crypto-trading-journal": "크립토 트레이딩 일지",
    "stock-trading-journal": "주식 트레이딩 일지",
    "social-media": "소셜 미디어",
    "regulatory-news": "규제 동향",
    "political-trades": "정치인 거래",
    "defi-tvl": "DeFi TVL",
    "defi": "DeFi",
    "defi-yields": "DeFi 수익률",
    "blockchain-report": "블록체인",
    "blockchain": "블록체인",
    "geopolitical-risk": "지정학 리스크",
    "worldmonitor": "글로벌 이슈",
    "market-indicators": "시장 지표",
    "economic-calendar": "경제 캘린더",
}


def _week_bounds(week_offset: int) -> Tuple[datetime, datetime, int, int]:
    """Return (week_start, week_end, iso_year, iso_week) for the target week.

    Week starts Monday 00:00 KST, ends Sunday 23:59:59 KST.
    week_offset=1 means the previous (most recently completed) week.
    """
    now = get_kst_now()
    # Monday of current week
    current_monday = now - timedelta(days=now.weekday())
    current_monday = current_monday.replace(hour=0, minute=0, second=0, microsecond=0)
    target_monday = current_monday - timedelta(weeks=week_offset)
    target_sunday = target_monday + timedelta(days=6, hours=23, minutes=59, seconds=59)
    iso = target_monday.isocalendar()
    return target_monday, target_sunday, iso[0], iso[1]


def _run(cmd: List[str], cwd: str = REPO_ROOT) -> str:
    """Run a subprocess command and return stdout. Returns empty string on failure."""
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            logger.debug("Command %s returned %d: %s", cmd, result.returncode, result.stderr.strip())
            return ""
        return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        logger.debug("Command %s failed: %s", cmd, exc)
        return ""


# ---------------------------------------------------------------------------
# Data collectors
# ---------------------------------------------------------------------------


def git_stats(week_start: datetime, week_end: datetime) -> Dict[str, int]:
    """Return commit count, files changed, insertions, deletions for the week."""
    since = week_start.strftime("%Y-%m-%d")
    until = (week_end + timedelta(seconds=1)).strftime("%Y-%m-%d")

    log_output = _run([
        "git", "log",
        f"--since={since}",
        f"--until={until}",
        "--shortstat",
        "--no-merges",
        "--format=",
    ])

    commits_output = _run([
        "git", "log",
        f"--since={since}",
        f"--until={until}",
        "--no-merges",
        "--oneline",
    ])

    commit_count = len([line for line in commits_output.splitlines() if line.strip()])

    files_changed = 0
    insertions = 0
    deletions = 0

    for line in log_output.splitlines():
        line = line.strip()
        m = re.search(r"(\d+) files? changed", line)
        if m:
            files_changed += int(m.group(1))
        m = re.search(r"(\d+) insertions?", line)
        if m:
            insertions += int(m.group(1))
        m = re.search(r"(\d+) deletions?", line)
        if m:
            deletions += int(m.group(1))

    return {
        "commits": commit_count,
        "files_changed": files_changed,
        "insertions": insertions,
        "deletions": deletions,
    }


def merged_prs(week_start: datetime, week_end: datetime) -> List[str]:
    """Return list of merge commit subject lines for the week (no gh CLI needed)."""
    since = week_start.strftime("%Y-%m-%d")
    until = (week_end + timedelta(seconds=1)).strftime("%Y-%m-%d")

    output = _run([
        "git", "log",
        f"--since={since}",
        f"--until={until}",
        "--merges",
        "--format=%s",
    ])

    prs = []
    for line in output.splitlines():
        line = line.strip()
        if line:
            prs.append(line)
    return prs


def post_counts(week_start: datetime, week_end: datetime) -> Dict[str, int]:
    """Count _posts/ files created within the week by category slug."""
    if not os.path.isdir(POSTS_DIR):
        return {}

    counts: Dict[str, int] = {}
    start_date = week_start.date()
    end_date = week_end.date()

    for fname in os.listdir(POSTS_DIR):
        if not fname.endswith(".md"):
            continue
        # Filename pattern: YYYY-MM-DD-slug.md
        m = re.match(r"^(\d{4}-\d{2}-\d{2})-(.+)\.md$", fname)
        if not m:
            continue
        try:
            post_date = datetime.strptime(m.group(1), "%Y-%m-%d").date()  # noqa: DTZ007
        except ValueError:
            continue
        if not (start_date <= post_date <= end_date):
            continue

        slug = m.group(2)
        # Derive category from slug: find the first matching CAT_NAMES key
        category = "기타"
        for cat_key in CAT_NAMES:
            if cat_key in slug:
                category = CAT_NAMES[cat_key]
                break

        counts[category] = counts.get(category, 0) + 1

    return counts


def ci_summary() -> str:
    """Return a placeholder CI summary section (no API access in script context)."""
    return (
        "CI/CD 상태는 GitHub Actions 대시보드에서 확인하세요: "
        "https://github.com/Twodragon0/investing/actions\n\n"
        "주요 체크 항목:\n"
        "- Jekyll Deploy\n"
        "- Lighthouse CI\n"
        "- Code Quality (ruff)\n"
        "- Description Quality\n"
        "- Coverage\n"
    )


# ---------------------------------------------------------------------------
# Report builder
# ---------------------------------------------------------------------------


def build_report(
    iso_year: int,
    iso_week: int,
    week_start: datetime,
    week_end: datetime,
) -> str:
    """Assemble the full Korean markdown report string."""
    logger.info("Collecting git stats for W%02d %d…", iso_week, iso_year)
    stats = git_stats(week_start, week_end)
    logger.info("Collecting merged PRs…")
    prs = merged_prs(week_start, week_end)
    logger.info("Counting posts…")
    posts = post_counts(week_start, week_end)

    start_str = week_start.strftime("%Y-%m-%d")
    end_str = week_end.strftime("%Y-%m-%d")
    total_posts = sum(posts.values())

    lines: List[str] = []

    # Header
    lines.append(f"# W{iso_week:02d} 주간 성과 보고서 ({start_str} ~ {end_str})\n")

    # 1. 커밋 통계
    lines.append("## 커밋/변경 통계\n")
    lines.append("| 지표 | 값 |")
    lines.append("|------|-----|")
    lines.append(f"| 총 커밋 수 | {stats['commits']} |")
    lines.append(f"| 변경 파일 수 | {stats['files_changed']:,} |")
    lines.append(f"| 코드 추가 | +{stats['insertions']:,} lines |")
    lines.append(f"| 코드 삭제 | -{stats['deletions']:,} lines |")
    lines.append(f"| 병합 PR 수 | {len(prs)} |")
    lines.append(f"| 생성 포스트 수 | {total_posts} |")
    lines.append("")

    # 2. 주요 PR
    lines.append("## 주요 PR 및 기능\n")
    if prs:
        for pr in prs:
            lines.append(f"- {pr}")
    else:
        lines.append("- (이번 주 병합된 PR 없음)")
    lines.append("")

    # 3. 수집기 현황
    lines.append("## 수집기 현황\n")
    lines.append("| 카테고리 | 포스트 수 |")
    lines.append("|----------|-----------|")
    if posts:
        for cat, count in sorted(posts.items(), key=lambda x: -x[1]):
            lines.append(f"| {cat} | {count} |")
        lines.append(f"| **합계** | **{total_posts}** |")
    else:
        lines.append("| (데이터 없음) | 0 |")
    lines.append("")

    # 4. 버그 수정 및 개선
    lines.append("## 버그 수정 및 개선\n")
    lines.append("### 수정된 버그")
    lines.append("- (이번 주 수정 사항을 직접 입력하세요)")
    lines.append("")
    lines.append("### 새로 추가된 기능")
    lines.append("- (이번 주 신규 기능을 직접 입력하세요)")
    lines.append("")

    # 5. CI/CD 상태
    lines.append("## CI/CD 상태\n")
    lines.append(ci_summary())

    # 6. 다음 주 계획
    next_week = iso_week + 1 if iso_week < 52 else 1
    lines.append(f"## 다음 주 계획 (W{next_week:02d})\n")
    lines.append("1. (다음 주 계획 항목을 입력하세요)")
    lines.append("2. (다음 주 계획 항목을 입력하세요)")
    lines.append("3. (다음 주 계획 항목을 입력하세요)")
    lines.append("")

    # Footer
    generated_at = get_kst_now().strftime("%Y-%m-%d %H:%M KST")
    lines.append(f"---\n\n*자동 생성: {generated_at}*")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate weekly performance report for the investing project."
    )
    parser.add_argument(
        "--week-offset",
        type=int,
        default=1,
        metavar="N",
        help="How many weeks back to report (default: 1 = previous week)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing report file",
    )
    args = parser.parse_args()

    if args.week_offset < 0:
        logger.error("--week-offset must be >= 0")
        return 1

    week_start, week_end, iso_year, iso_week = _week_bounds(args.week_offset)
    report_filename = f"weekly-report-{iso_year}-w{iso_week:02d}.md"
    report_path = os.path.join(DOCS_DIR, report_filename)

    logger.info(
        "Target week: W%02d %d (%s ~ %s)",
        iso_week,
        iso_year,
        week_start.strftime("%Y-%m-%d"),
        week_end.strftime("%Y-%m-%d"),
    )

    # Dedup guard
    if os.path.exists(report_path) and not args.force:
        logger.info("Report already exists: %s (use --force to overwrite)", report_path)
        return 0

    os.makedirs(DOCS_DIR, exist_ok=True)

    try:
        content = build_report(iso_year, iso_week, week_start, week_end)
    except Exception as exc:
        logger.error("Failed to build report: %s", exc)
        return 1

    try:
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(content)
    except OSError as exc:
        logger.error("Failed to write report: %s", exc)
        return 1

    logger.info("Report written: %s", report_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
