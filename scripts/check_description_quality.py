#!/usr/bin/env python3
"""Check post description quality and report boilerplate ratio.

Scans _posts/ for recent posts, extracts description_ko front matter fields,
and classifies each as: real content, title repeat, or boilerplate.
Exits with code 1 if boilerplate ratio exceeds 30%.
"""

import argparse
import re
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

# Shared boilerplate detectors. The canonical definitions live in
# common/enrichment.py and common/summarizer.py — importing them here avoids
# pattern drift (the duplicated local copies previously missed the regex
# update in PR #775 because the two files weren't kept in sync).
# Fallback to None only when run in true standalone mode (no PYTHONPATH);
# callers should ensure scripts/ is importable for full detection.
try:
    from common.enrichment import _is_site_boilerplate as _enrichment_boilerplate  # noqa: PLC2701
    from common.summarizer import (  # noqa: PLC2701
        _is_boilerplate_desc as _summarizer_boilerplate,
    )
    from common.summarizer import (
        _is_generic_desc as _summarizer_generic,
    )
except ImportError:
    _enrichment_boilerplate = None  # type: ignore[assignment]
    _summarizer_boilerplate = None  # type: ignore[assignment]
    _summarizer_generic = None  # type: ignore[assignment]

_NORM_RE = re.compile(r"[\s\W]+")

# Front matter description field patterns (description_ko or description)
_DESC_KO_RE = re.compile(r'^description_ko:\s*["\']?(.+?)["\']?\s*$', re.MULTILINE)
_DESC_RE = re.compile(r'^description:\s*["\']?(.+?)["\']?\s*$', re.MULTILINE)
_TITLE_RE = re.compile(r'^title:\s*["\']?(.+?)["\']?\s*$', re.MULTILINE)
_DATE_RE = re.compile(r"^date:\s*(\d{4}-\d{2}-\d{2})", re.MULTILINE)


def _is_boilerplate(desc: str) -> bool:
    """Return True if description is site boilerplate or synthetic filler.

    Delegates to the three canonical detectors:
      - `common.enrichment._is_site_boilerplate` (site phrases + regex + short-desc rule)
      - `common.summarizer._is_generic_desc` (synthetic/generic patterns)
      - `common.summarizer._is_boilerplate_desc` (extra MT-leak phrases)
    """
    if not desc:
        return False
    if _enrichment_boilerplate is not None and _enrichment_boilerplate(desc):
        return True
    if _summarizer_generic is not None and _summarizer_generic(desc):
        return True
    if _summarizer_boilerplate is not None and _summarizer_boilerplate(desc):
        return True
    return False


# ---------------------------------------------------------------------------
# Translation quality detection
# ---------------------------------------------------------------------------

# Mojibake: 3+ consecutive Latin-1 supplement chars (U+00C0–U+00FF) that
# result from treating UTF-8 bytes as Latin-1.
_MOJIBAKE_RE = re.compile(r"[\u00c0-\u00ff]{3,}")

# Source-domain noise appended to Korean text (common MT artifact).
_DOMAIN_SUFFIX_RE = re.compile(
    r"[\uac00-\ud7a3][^.!?]*\s+(?:morningstar\.com|yahoo|reuters|bloomberg"
    r"|cnbc|marketwatch|seekingalpha|ft\.com|wsj\.com|investing\.com"
    r"|coindesk|cointelegraph|decrypt|theblock)\s*[.!?]?\s*$",
    re.I,
)

# Korean sentences ending with a bare Korean media brand (MT source leak).
_SOURCE_LEAK_RE = re.compile(
    r"[\uac00-\ud7a3][^.!?]{5,}\s+"
    r"(?:야후|디지털투데이|연합뉴스|뉴시스|아이뉴스|지디넷|테크크런치|포브스)\s*[.!?]?\s*$"
)

# Mixed-language: Korean sentence body with a trailing English-only phrase
# that looks like an untranslated fragment (≥4 consecutive ASCII word chars
# after Korean text, not a proper noun or ticker).
_MIXED_LANG_RE = re.compile(
    r"[\uac00-\ud7a3].{10,}\s+([a-z]{4,}(?:\s+[a-z]{4,}){1,})\s*[.!?]?\s*$",
    re.I,
)


def _has_translation_issue(desc: str) -> bool:
    """Return True if desc shows signs of poor machine translation quality."""
    if not desc:
        return False
    if _MOJIBAKE_RE.search(desc):
        return True
    if _DOMAIN_SUFFIX_RE.search(desc):
        return True
    if _SOURCE_LEAK_RE.search(desc):
        return True
    if _MIXED_LANG_RE.search(desc):
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
        desc = m.group(1).strip("\"'")
    else:
        m = _DESC_RE.search(text)
        if m:
            desc = m.group(1).strip("\"'")
    m = _TITLE_RE.search(text)
    if m:
        title = m.group(1).strip("\"'")
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
                "body": text,
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
    translation_issue_items = []

    mojibake_items: list[dict] = []

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
        # Translation check is independent — a desc can be real content but
        # still have translation quality issues.
        if desc and _has_translation_issue(desc):
            translation_issue_items.append(p)
        # Full-body mojibake scan — checks entire post content, not just description
        body = p.get("body", "")
        if body and _MOJIBAKE_RE.search(body):
            mojibake_items.append(p)

    return {
        "total": total,
        "no_desc": no_desc_items,
        "boilerplate": boilerplate_items,
        "title_repeat": title_repeat_items,
        "real": real_items,
        "translation_issues": translation_issue_items,
        "mojibake": mojibake_items,
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
    ti_count = len(stats["translation_issues"])
    mj_count = len(stats["mojibake"])

    lines = [
        f"Description Quality Report (last {days} day(s))",
        f"  Posts scanned   : {total}",
        f"  Real content    : {real_count} ({_pct(real_count, total)})",
        f"  Title repeat    : {tr_count} ({_pct(tr_count, total)})",
        f"  Boilerplate desc: {bp_count} ({_pct(bp_count, total)})",
        f"  Translation issues: {ti_count} ({_pct(ti_count, total)})",
        f"  Mojibake (body) : {mj_count} ({_pct(mj_count, total)})",
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
    if stats["translation_issues"]:
        lines.append("")
        lines.append("Translation-issue posts:")
        for p in stats["translation_issues"]:
            lines.append(f"  - {p['file']}: {p['description'][:80]}")
    if stats["mojibake"]:
        lines.append("")
        lines.append("Mojibake (encoding corruption) posts:")
        for p in stats["mojibake"]:
            lines.append(f"  - {p['file']}")
    return "\n".join(lines)


def format_markdown(stats: dict, days: int) -> str:
    """Format stats as GitHub Actions markdown summary."""
    total = stats["total"]
    real_count = len(stats["real"])
    bp_count = len(stats["boilerplate"])
    tr_count = len(stats["title_repeat"])
    nd_count = len(stats["no_desc"])
    ti_count = len(stats["translation_issues"])
    mj_count = len(stats["mojibake"])

    bp_pct = bp_count / total * 100 if total else 0
    status_icon = "✅" if bp_pct < 30 else ("⚠️" if bp_pct < 50 else "❌")
    if mj_count > 0:
        status_icon = "❌"

    lines = [
        f"## {status_icon} Description Quality Report (last {days} day(s))",
        "",
        "| Category | Count | Ratio |",
        "|----------|------:|------:|",
        f"| 전체 포스트 | {total} | 100% |",
        f"| 실제 콘텐츠 | {real_count} | {_pct(real_count, total)} |",
        f"| 제목 반복 | {tr_count} | {_pct(tr_count, total)} |",
        f"| Boilerplate | {bp_count} | {_pct(bp_count, total)} |",
        f"| 번역 품질 이슈 | {ti_count} | {_pct(ti_count, total)} |",
        f"| Mojibake (인코딩) | {mj_count} | {_pct(mj_count, total)} |",
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

    if stats["translation_issues"]:
        lines += ["", "### 번역 품질 이슈 포스트"]
        for p in stats["translation_issues"]:
            lines.append(f"- `{p['file']}`: {p['description'][:100]}")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Check post description quality and report boilerplate ratio.")
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

    # Exit 1 when boilerplate exceeds 30% or any mojibake found
    if bp_pct > 30:
        return 1
    if len(stats["mojibake"]) > 0:
        print("ERROR: mojibake (encoding corruption) detected in post body", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
