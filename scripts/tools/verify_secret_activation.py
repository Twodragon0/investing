"""Secret activation verifier.

Compare baseline vs. recent post metrics to confirm that newly registered
GitHub Actions secrets (TWITTER_BEARER_TOKEN, GSC_SERVICE_ACCOUNT_JSON)
are producing measurable results.

Usage:
    python scripts/tools/verify_secret_activation.py --secret twitter
    python scripts/tools/verify_secret_activation.py --secret gsc
    python scripts/tools/verify_secret_activation.py --secret both --baseline-days 7
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import subprocess
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import NamedTuple

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("verify_secret_activation")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
POSTS_DIR = REPO_ROOT / "_posts"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


class PostMetrics(NamedTuple):
    date: str
    total_items: int
    twitter_items: int
    telegram_items: int
    political_items: int
    social_items: int


class GscRunInfo(NamedTuple):
    run_id: str
    conclusion: str
    started_at: str
    indexed_count: int | None  # None when artifact is unavailable


# ---------------------------------------------------------------------------
# Twitter / social-media post parsing
# ---------------------------------------------------------------------------

_SOCIAL_DIGEST_PATTERN = re.compile(r"^(\d{4}-\d{2}-\d{2})-daily-social-media-digest\.md$")

# Front-matter field matchers
_TOTAL_RE = re.compile(r"^총\s+(\d+)건이?\s+수집", re.MULTILINE)
_TWITTER_RE = re.compile(r"소셜\s*미디어\s*(\d+)건", re.MULTILINE)
_TELEGRAM_RE = re.compile(r"텔레그램\s*(\d+)건", re.MULTILINE)
_POLITICAL_RE = re.compile(r"정치·경제\s*(\d+)건", re.MULTILINE)

# Also capture counts from stat-grid divs
_STAT_SOCIAL_RE = re.compile(r'<span class="stat-value">(\d+)</span>\s*<span class="stat-label">소셜 미디어</span>')
_STAT_POLITICAL_RE = re.compile(r'<span class="stat-value">(\d+)</span>\s*<span class="stat-label">정치·경제</span>')
_STAT_TELEGRAM_RE = re.compile(r'<span class="stat-value">(\d+)</span>\s*<span class="stat-label">텔레그램</span>')


def _extract_int(pattern: re.Pattern, text: str, default: int = 0) -> int:
    m = pattern.search(text)
    return int(m.group(1)) if m else default


def parse_social_digest(path: Path) -> PostMetrics:
    """Parse a daily-social-media-digest post and return item counts."""
    text = path.read_text(encoding="utf-8", errors="replace")
    date_str = _SOCIAL_DIGEST_PATTERN.match(path.name)
    date = date_str.group(1) if date_str else path.name[:10]

    total = _extract_int(_TOTAL_RE, text)
    if total == 0:
        # Fallback: sum stat values
        social = _extract_int(_STAT_SOCIAL_RE, text)
        telegram = _extract_int(_STAT_TELEGRAM_RE, text)
        political = _extract_int(_STAT_POLITICAL_RE, text)
        total = social + telegram + political
    else:
        social = _extract_int(_STAT_SOCIAL_RE, text)
        telegram = _extract_int(_STAT_TELEGRAM_RE, text)
        political = _extract_int(_STAT_POLITICAL_RE, text)

    # Sentence-level fallback for twitter items
    twitter = _extract_int(_TWITTER_RE, text, default=social)
    telegram_count = _extract_int(_TELEGRAM_RE, text, default=telegram)

    return PostMetrics(
        date=date,
        total_items=total,
        twitter_items=twitter,
        telegram_items=telegram_count,
        political_items=political,
        social_items=social,
    )


def collect_social_metrics(baseline_days: int, observe_hours: int) -> tuple[list[PostMetrics], list[PostMetrics]]:
    """Return (baseline_posts, recent_posts) based on date windows."""
    now = datetime.now(tz=UTC)
    baseline_cutoff = now - timedelta(days=baseline_days)
    observe_cutoff = now - timedelta(hours=observe_hours)

    baseline: list[PostMetrics] = []
    recent: list[PostMetrics] = []

    for path in sorted(POSTS_DIR.glob("*-daily-social-media-digest.md")):
        m = _SOCIAL_DIGEST_PATTERN.match(path.name)
        if not m:
            continue
        post_date = datetime.strptime(m.group(1), "%Y-%m-%d").replace(tzinfo=UTC)
        metrics = parse_social_digest(path)

        if post_date >= observe_cutoff:
            recent.append(metrics)
        elif post_date >= baseline_cutoff:
            baseline.append(metrics)

    return baseline, recent


def _avg(values: list[int]) -> float:
    return sum(values) / len(values) if values else 0.0


def _delta_pct(baseline: float, recent: float) -> str:
    if baseline == 0:
        return "N/A" if recent == 0 else "+∞"
    pct = (recent - baseline) / baseline * 100
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.1f}%"


def render_twitter_report(baseline: list[PostMetrics], recent: list[PostMetrics], observe_hours: int) -> str:
    lines: list[str] = []
    lines.append("## Twitter/X Secret 활성화 검증 리포트")
    lines.append("")

    if not baseline:
        lines.append("> 경고: baseline 포스트 없음 — 분석 기간을 늘려보세요.")
    if not recent:
        lines.append(f"> 최근 {observe_hours}h 포스트 없음 — 다음 cron 실행 후 재시도하세요.")
        lines.append("")

    b_total = _avg([m.total_items for m in baseline])
    b_twitter = _avg([m.twitter_items for m in baseline])
    b_telegram = _avg([m.telegram_items for m in baseline])
    b_political = _avg([m.political_items for m in baseline])

    r_total = _avg([m.total_items for m in recent])
    r_twitter = _avg([m.twitter_items for m in recent])
    r_telegram = _avg([m.telegram_items for m in recent])
    r_political = _avg([m.political_items for m in recent])

    header = f"| 지표 | baseline 평균 ({len(baseline)}건) | 최근 {observe_hours}h 평균 ({len(recent)}건) | Δ% |"
    sep = "|------|------|------|------|"
    rows = [
        f"| 전체 수집 건수 | {b_total:.1f} | {r_total:.1f} | {_delta_pct(b_total, r_total)} |",
        f"| 소셜/트위터 항목 | {b_twitter:.1f} | {r_twitter:.1f} | {_delta_pct(b_twitter, r_twitter)} |",
        f"| 텔레그램 항목 | {b_telegram:.1f} | {r_telegram:.1f} | {_delta_pct(b_telegram, r_telegram)} |",
        f"| 정치·경제 항목 | {b_political:.1f} | {r_political:.1f} | {_delta_pct(b_political, r_political)} |",
    ]
    lines += [header, sep] + rows
    lines.append("")

    if recent:
        lines.append("### 최근 포스트 상세")
        for m in recent:
            lines.append(
                f"- {m.date}: 총 {m.total_items}건 (소셜 {m.twitter_items}, 텔레그램 {m.telegram_items}, 정치 {m.political_items})"
            )
    else:
        lines.append("### 판정")
        lines.append("- TWITTER_BEARER_TOKEN 등록 후 다음 cron(`collect-social`) 실행을 기다려 재실행하세요.")

    if recent and r_twitter > b_twitter:
        lines.append("")
        lines.append("> **판정: 개선** — 소셜/트위터 항목 수 증가 확인.")
    elif recent and r_twitter == b_twitter and b_twitter == 0:
        lines.append("")
        lines.append("> **판정: 미활성** — twitter 항목이 여전히 0. 토큰 등록 및 워크플로우 실행을 확인하세요.")
    elif recent:
        lines.append("")
        lines.append("> **판정: 변화 없음** — baseline 대비 유의미한 증가 없음.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# GSC run analysis via gh CLI
# ---------------------------------------------------------------------------

_GSC_WORKFLOW_FILE = "gsc-index-audit.yml"


def _run_gh(args: list[str]) -> tuple[bool, str]:
    """Run a gh CLI command; return (success, stdout)."""
    try:
        result = subprocess.run(
            ["gh", *args],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            return True, result.stdout.strip()
        logger.debug("gh error: %s", result.stderr.strip())
        return False, result.stderr.strip()
    except FileNotFoundError:
        return False, "gh CLI를 찾을 수 없습니다. GitHub CLI를 설치하세요."
    except subprocess.TimeoutExpired:
        return False, "gh CLI 타임아웃"


def fetch_gsc_runs(limit: int = 20) -> list[dict]:
    """Return recent workflow runs for gsc-index-audit.yml."""
    ok, out = _run_gh(
        [
            "run",
            "list",
            "--workflow",
            _GSC_WORKFLOW_FILE,
            "--limit",
            str(limit),
            "--json",
            "databaseId,conclusion,startedAt,status",
        ]
    )
    if not ok:
        logger.warning("gh run list 실패: %s", out)
        return []
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        logger.warning("gh run list 출력 파싱 실패")
        return []


def _fetch_artifact_indexed_count(run_id: str) -> int | None:
    """Download gsc-audit artifact and parse indexed count. Returns None on failure."""
    with tempfile.TemporaryDirectory() as tmpdir:
        ok, _ = _run_gh(
            [
                "run",
                "download",
                str(run_id),
                "--dir",
                tmpdir,
            ]
        )
        if not ok:
            return None

        tmp = Path(tmpdir)
        # Look for any text file inside downloaded artifact dirs
        txt_files = list(tmp.rglob("*.txt")) + list(tmp.rglob("*.log"))
        for txt_path in txt_files:
            content = txt_path.read_text(errors="replace")
            # Pattern: "Indexed: 123" or similar
            m = re.search(r"(?:indexed|색인됨)[:\s]+(\d+)", content, re.IGNORECASE)
            if m:
                return int(m.group(1))
        return None


def collect_gsc_runs(baseline_days: int, observe_hours: int) -> tuple[list[GscRunInfo], list[GscRunInfo]]:
    """Return (baseline_runs, recent_runs)."""
    now = datetime.now(tz=UTC)
    baseline_cutoff = now - timedelta(days=baseline_days)
    observe_cutoff = now - timedelta(hours=observe_hours)

    runs = fetch_gsc_runs(limit=30)

    baseline: list[GscRunInfo] = []
    recent: list[GscRunInfo] = []

    for run in runs:
        started = run.get("startedAt", "")
        try:
            # GitHub returns ISO8601 with Z suffix
            run_dt = datetime.fromisoformat(started.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            continue

        info = GscRunInfo(
            run_id=str(run.get("databaseId", "")),
            conclusion=run.get("conclusion") or run.get("status", "unknown"),
            started_at=started,
            indexed_count=None,
        )

        if run_dt >= observe_cutoff:
            recent.append(info)
        elif run_dt >= baseline_cutoff:
            baseline.append(info)

    return baseline, recent


def render_gsc_report(baseline: list[GscRunInfo], recent: list[GscRunInfo], observe_hours: int) -> str:
    lines: list[str] = []
    lines.append("## GSC Secret 활성화 검증 리포트")
    lines.append("")

    if not baseline and not recent:
        lines.append("> **gh CLI 미응답** 또는 **워크플로우 실행 기록 없음**.")
        lines.append("> `gh auth status` 와 `gh run list --workflow gsc-index-audit.yml` 를 직접 확인하세요.")
        return "\n".join(lines)

    b_count = len(baseline)
    r_count = len(recent)
    b_success = sum(1 for r in baseline if r.conclusion == "success")
    r_success = sum(1 for r in recent if r.conclusion == "success")

    header = f"| 지표 | baseline ({b_count}회) | 최근 {observe_hours}h ({r_count}회) |"
    sep = "|------|------|------|"
    rows = [
        f"| 실행 횟수 | {b_count} | {r_count} |",
        f"| 성공 횟수 | {b_success} | {r_success} |",
    ]
    lines += [header, sep] + rows
    lines.append("")

    if recent:
        lines.append("### 최근 실행 상세")
        for r in recent:
            lines.append(f"- run `{r.run_id}` — {r.conclusion} ({r.started_at})")
    else:
        lines.append("### 판정")
        lines.append(
            "- GSC_SERVICE_ACCOUNT_JSON 등록 후 다음 월요일 cron 또는 수동 `workflow_dispatch` 후 재실행하세요."
        )

    if r_count > 0 and r_success > 0:
        lines.append("")
        lines.append("> **판정: 활성** — GSC 감사 워크플로우가 성공적으로 실행됨.")
    elif r_count > 0:
        lines.append("")
        lines.append("> **판정: 실행 중이나 오류** — 실행은 되었으나 성공 없음. 워크플로우 로그를 확인하세요.")
    elif b_count == 0:
        lines.append("")
        lines.append("> **판정: 미실행** — baseline 기간에도 실행 기록 없음. Secret 미등록 상태로 추정.")
    else:
        lines.append("")
        lines.append("> **판정: 대기 중** — baseline 실행은 있으나 최근 실행 없음.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Secret 활성화 전후 효과 비교 리포트 생성",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  # Twitter 등록 다음 cron 후
  python scripts/tools/verify_secret_activation.py --secret twitter --baseline-days 7

  # GSC 등록 다음 주 cron 후
  python scripts/tools/verify_secret_activation.py --secret gsc --baseline-days 7

  # 둘 다 한 번에
  python scripts/tools/verify_secret_activation.py --secret both
""",
    )
    parser.add_argument(
        "--secret",
        choices=["twitter", "gsc", "both"],
        default="both",
        help="검증할 secret 종류 (기본: both)",
    )
    parser.add_argument(
        "--baseline-days",
        type=int,
        default=7,
        metavar="N",
        help="baseline 집계 기간 (일, 기본 7)",
    )
    parser.add_argument(
        "--observe-hours",
        type=int,
        default=24,
        metavar="H",
        help="비교 대상 최근 기간 (시간, 기본 24)",
    )
    parser.add_argument(
        "--output",
        choices=["markdown", "text"],
        default="markdown",
        help="출력 형식 (기본: markdown)",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    secret = args.secret
    baseline_days = args.baseline_days
    observe_hours = args.observe_hours

    reports: list[str] = []

    if secret in ("twitter", "both"):
        logger.info("소셜 미디어 포스트 분석 중 (baseline %d일, 최근 %dh)…", baseline_days, observe_hours)
        baseline, recent = collect_social_metrics(baseline_days, observe_hours)
        logger.info("baseline %d건, 최근 %d건 발견", len(baseline), len(recent))
        report = render_twitter_report(baseline, recent, observe_hours)
        reports.append(report)

    if secret in ("gsc", "both"):
        logger.info("GSC 워크플로우 실행 기록 조회 중…")
        baseline_runs, recent_runs = collect_gsc_runs(baseline_days, observe_hours)
        report = render_gsc_report(baseline_runs, recent_runs, observe_hours)
        reports.append(report)

    output = "\n\n---\n\n".join(reports)
    print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
