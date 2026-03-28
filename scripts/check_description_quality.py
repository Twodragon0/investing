#!/usr/bin/env python3
"""Check post description quality and report boilerplate ratio.

Scans _posts/ for recent posts, extracts description_ko front matter fields,
and classifies each as: real content, title repeat, or boilerplate.
Exits with code 1 if boilerplate ratio exceeds 50%.
"""

import argparse
import re
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Boilerplate detection — mirrors enrichment.py patterns (standalone copy)
# ---------------------------------------------------------------------------

_SITE_BOILERPLATE_PHRASES = [
    "motley fool",
    "seeking alpha",
    "cnbc international",
    "investopedia",
    "yahoo finance",
    "bloomberg",
    "coindesk is",
    "cointelegraph is",
    "decrypt is",
    "뉴스의 리더입니다",
    "뉴스를 제공하는",
    "투자 통찰력과 개인 금융",
    "투자 커뮤니티",
    "프리미엄 뉴스를 제공",
    "businesspost",
    "비즈니스포스트",
    "인물중심 기업인 프로파일",
    "경제미디어 경제신문",
    "올인원 플랫폼입니다",
    "포트폴리오를 개선하고",
    "개인 금융 뉴스 및 비즈니스 예측",
    "선두주자입니다",
    "우리의 목적은 세상을",
    "더 스마트하고, 더 행복하고",
    "simply wall st",
    "kiplinger",
    "tipranks",
    "stock analysis",
    "관련 광고",
    "포트폴리오 업데이트 보고서",
]

_SITE_BOILERPLATE_PATTERNS = [
    re.compile(r"(?:the )?(?:world'?s?|global) (?:leading|largest|premier|#1)\b", re.I),
    re.compile(r"(?:join|subscribe to|sign up for) (?:the )?(?:world'?s|our)\b", re.I),
    re.compile(
        r"(?:providing|delivers?|offers?) .{0,40}(?:news|analysis|insights|information)"
        r" .{0,40}(?:since|for over|for \d+)",
        re.I,
    ),
    re.compile(r"^(?:the )?(?:latest|breaking|live|real-time) (?:news|updates?|prices?)\b", re.I),
    re.compile(r"(?:세계 최대|글로벌 리더|세계적인 리더)", re.I),
    re.compile(r"(?:에 참여하세요|구독하세요|가입하세요)$", re.I),
    re.compile(r"\d+년 (?:넘게|이상) .{0,40}(?:제공|서비스)", re.I),
]

_SYNTHETIC_MARKERS = [
    "관련 소식입니다",
    "관련 시장 뉴스입니다",
    "원문에서 세부 내용을 확인하세요",
    "원문 기사의 세부 내용을 확인하세요",
    "투자 판단 시",
    "면밀히 분석해야 합니다",
    "함께 고려해야 합니다",
    "주시해야 합니다",
    "확인하세요",
    "관련 시장 동향입니다",
    "관련 세부 내용은",
    "관련 변경사항을",
    "시장 심리와 가격",
    "투자 시사점을",
    "거래소 공지사항",
    "산업 동향",
    "관련 보도.",
    "섹터 보도.",
    "산업 보도.",
    "시장 보도.",
]

_ARTICLE_SPECIFIC_RE = re.compile(
    r"(?:[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)"
    r"|(?:\b[A-Z]{2,}\b)"
    r"|(?:\b\d{4}\b)"
    r"|(?:\b\d+[\.,]\d+)"
    r"|(?:\$|€|£|₩|¥)\s*\d"
    r"|(?:\d+\s*(?:%|억|만|조|달러|원|위안))"
    r"|(?:월|년|일)\s*\d"
)

_NORM_RE = re.compile(r"[\s\W]+")

# Front matter description field patterns (description_ko or description)
_DESC_KO_RE = re.compile(r'^description_ko:\s*["\']?(.+?)["\']?\s*$', re.MULTILINE)
_DESC_RE = re.compile(r'^description:\s*["\']?(.+?)["\']?\s*$', re.MULTILINE)
_TITLE_RE = re.compile(r'^title:\s*["\']?(.+?)["\']?\s*$', re.MULTILINE)
_DATE_RE = re.compile(r'^date:\s*(\d{4}-\d{2}-\d{2})', re.MULTILINE)


def _is_boilerplate(desc: str) -> bool:
    """Return True if description is site boilerplate or synthetic filler."""
    if not desc:
        return False
    lower = desc.lower()
    for phrase in _SITE_BOILERPLATE_PHRASES:
        if phrase.lower() in lower:
            return True
    for pattern in _SITE_BOILERPLATE_PATTERNS:
        if pattern.search(desc):
            return True
    for marker in _SYNTHETIC_MARKERS:
        if marker in desc:
            return True
    if len(desc) < 35 and not _ARTICLE_SPECIFIC_RE.search(desc):
        return True
    return False


def _is_title_repeat(desc: str, title: str) -> bool:
    """Return True if description is 80%+ overlap with the post title."""
    if not desc or not title:
        return False
    norm_desc = _NORM_RE.sub("", desc.lower())
    norm_title = _NORM_RE.sub("", title.lower())
    if not norm_title:
        return False
    # Count shared characters via longest common subsequence ratio
    shorter = min(len(norm_desc), len(norm_title))
    longer = max(len(norm_desc), len(norm_title))
    if longer == 0:
        return False
    # Simple containment check: if title is almost fully in desc
    overlap = sum(1 for c in norm_title if c in norm_desc) / len(norm_title)
    return overlap >= 0.80 and shorter / longer >= 0.50  # type: ignore[return-value]


def _extract_front_matter(text: str) -> tuple[str, str]:
    """Extract (description, title) from post front matter."""
    desc = ""
    title = ""
    m = _DESC_KO_RE.search(text)
    if m:
        desc = m.group(1).strip('"\'')
    else:
        m = _DESC_RE.search(text)
        if m:
            desc = m.group(1).strip('"\'')
    m = _TITLE_RE.search(text)
    if m:
        title = m.group(1).strip('"\'')
    return desc, title


def _post_date(text: str) -> date | None:
    """Extract post date from front matter."""
    m = _DATE_RE.search(text)
    if m:
        try:
            return date.fromisoformat(m.group(1))
        except ValueError:
            pass
    return None


def collect_posts(posts_dir: Path, days: int) -> list[dict]:
    """Scan _posts/ and return list of post dicts within the last N days."""
    cutoff = datetime.now(tz=UTC).date() - timedelta(days=days - 1)
    results = []
    for post_file in sorted(posts_dir.glob("*.md")):
        text = post_file.read_text(encoding="utf-8", errors="ignore")
        post_date = _post_date(text)
        if post_date is None or post_date < cutoff:
            continue
        desc, title = _extract_front_matter(text)
        results.append(
            {
                "file": post_file.name,
                "date": post_date,
                "description": desc,
                "title": title,
            }
        )
    return results


def classify_posts(posts: list[dict]) -> dict:
    """Classify each post description and return aggregated stats."""
    total = len(posts)
    boilerplate_items = []
    title_repeat_items = []
    real_items = []
    no_desc_items = []

    for p in posts:
        desc = p["description"]
        title = p["title"]
        if not desc:
            no_desc_items.append(p)
            continue
        if _is_boilerplate(desc):
            boilerplate_items.append(p)
        elif _is_title_repeat(desc, title):
            title_repeat_items.append(p)
        else:
            real_items.append(p)

    return {
        "total": total,
        "no_desc": no_desc_items,
        "boilerplate": boilerplate_items,
        "title_repeat": title_repeat_items,
        "real": real_items,
    }


def _pct(count: int, total: int) -> str:
    if total == 0:
        return "0.0%"
    return f"{count / total * 100:.1f}%"


def format_text(stats: dict, days: int) -> str:
    """Format stats as plain text."""
    total = stats["total"]
    real_count = len(stats["real"])
    bp_count = len(stats["boilerplate"])
    tr_count = len(stats["title_repeat"])
    nd_count = len(stats["no_desc"])

    lines = [
        f"Description Quality Report (last {days} day(s))",
        f"  Posts scanned   : {total}",
        f"  Real content    : {real_count} ({_pct(real_count, total)})",
        f"  Title repeat    : {tr_count} ({_pct(tr_count, total)})",
        f"  Boilerplate     : {bp_count} ({_pct(bp_count, total)})",
        f"  No description  : {nd_count} ({_pct(nd_count, total)})",
    ]
    if stats["boilerplate"]:
        lines.append("")
        lines.append("Boilerplate posts:")
        for p in stats["boilerplate"]:
            lines.append(f"  - {p['file']}: {p['description'][:80]}")
    if stats["title_repeat"]:
        lines.append("")
        lines.append("Title-repeat posts:")
        for p in stats["title_repeat"]:
            lines.append(f"  - {p['file']}: {p['description'][:80]}")
    return "\n".join(lines)


def format_markdown(stats: dict, days: int) -> str:
    """Format stats as GitHub Actions markdown summary."""
    total = stats["total"]
    real_count = len(stats["real"])
    bp_count = len(stats["boilerplate"])
    tr_count = len(stats["title_repeat"])
    nd_count = len(stats["no_desc"])

    bp_pct = bp_count / total * 100 if total else 0
    status_icon = "✅" if bp_pct < 30 else ("⚠️" if bp_pct < 50 else "❌")

    lines = [
        f"## {status_icon} Description Quality Report (last {days} day(s))",
        "",
        "| Category | Count | Ratio |",
        "|----------|------:|------:|",
        f"| 전체 포스트 | {total} | 100% |",
        f"| 실제 콘텐츠 | {real_count} | {_pct(real_count, total)} |",
        f"| 제목 반복 | {tr_count} | {_pct(tr_count, total)} |",
        f"| Boilerplate | {bp_count} | {_pct(bp_count, total)} |",
        f"| description 없음 | {nd_count} | {_pct(nd_count, total)} |",
    ]

    if bp_pct >= 30:
        lines += [
            "",
            f"> ⚠️ **경고**: Boilerplate 비율이 {bp_pct:.1f}%입니다 (임계값: 30%).",
        ]

    if stats["boilerplate"]:
        lines += ["", "### Boilerplate 포스트"]
        for p in stats["boilerplate"]:
            lines.append(f"- `{p['file']}`: {p['description'][:100]}")

    if stats["title_repeat"]:
        lines += ["", "### 제목 반복 포스트"]
        for p in stats["title_repeat"]:
            lines.append(f"- `{p['file']}`: {p['description'][:100]}")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check post description quality and report boilerplate ratio."
    )
    parser.add_argument(
        "--days",
        type=int,
        default=1,
        help="Number of days of posts to check (default: 1)",
    )
    parser.add_argument(
        "--format",
        choices=["text", "markdown"],
        default="text",
        help="Output format: text or markdown (default: text)",
    )
    parser.add_argument(
        "--posts-dir",
        type=Path,
        default=Path("_posts"),
        help="Path to _posts directory (default: _posts)",
    )
    parser.add_argument(
        "--warn-threshold",
        type=float,
        default=30.0,
        help="Boilerplate %% to trigger warning log (default: 30)",
    )
    args = parser.parse_args()

    posts_dir = args.posts_dir
    if not posts_dir.exists():
        print(f"Error: posts directory not found: {posts_dir}", file=sys.stderr)
        return 2

    posts = collect_posts(posts_dir, args.days)
    stats = classify_posts(posts)

    total = stats["total"]
    bp_count = len(stats["boilerplate"])
    bp_pct = bp_count / total * 100 if total else 0

    if args.format == "markdown":
        print(format_markdown(stats, args.days))
    else:
        print(format_text(stats, args.days))

    if bp_pct >= args.warn_threshold:
        print(
            f"WARNING: boilerplate ratio {bp_pct:.1f}% >= {args.warn_threshold:.0f}% threshold",
            file=sys.stderr,
        )

    # Exit 1 only when boilerplate exceeds 50%
    if bp_pct > 50:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
