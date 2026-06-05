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

# Boilerplate detection goes through the unified facade in
# common/summary_quality.py — the underscore-private detectors in
# common/enrichment and common/summarizer should not be imported directly
# from CLI scripts (DIP). The facade orchestrates all three so a pattern
# update in any single source file remains observable to every consumer.
from common.summary_quality import is_boilerplate as _is_boilerplate
from common.text_utils import _strip_trailing_artifacts

_NORM_RE = re.compile(r"[\s\W]+")

# ---------------------------------------------------------------------------
# Body-text quality: rendered news-desc / p0-desc segments are NOT covered by
# the front-matter checks above. Scan them for the two artifact classes that
# the generator pipeline now prevents at the source (so any hit is a
# regression): leftover ad/boilerplate tails and misleading bare "$NN" number
# annotations that contradict a fuller number in the same sentence.
# ---------------------------------------------------------------------------
# Match either an opening news-desc <p> or p0-desc <span> with its OWN closing
# tag (no cross-tag pairing like <p>...</span>).
_BODY_DESC_SEG_RE = re.compile(
    r'<p class="news-desc">(.*?)</p>|<span class="p0-desc">(.*?)</span>',
    re.S,
)
# Bare 1–3 digit dollar annotation, e.g. "($73)". Excludes "($1.2B)"/"($50K)"
# because the closing paren must follow the digits directly.
_BARE_NUM_RE = re.compile(r"\(\$(\d{1,3})\)")
# Any dollar figure with its leading digit-run and optional magnitude suffix.
_DOLLAR_NUM_RE = re.compile(r"\$(\d[\d,]*(?:\.\d+)?)([KMBTkmbt]?)")


def _is_misleading_number(segment: str) -> bool:
    """Return True if a bare "$NN" annotation is a truncation of a richer figure.

    The artifact is specifically a magnitude-dropping copy of another number in
    the same segment — e.g. "$73,000 ... ($73)" or "$73K ... ($73)". Two
    genuinely distinct figures ("$73,000 ... ($500)") are NOT flagged.
    """
    bare = _BARE_NUM_RE.findall(segment)
    if not bare:
        return False
    richer = _DOLLAR_NUM_RE.findall(segment)
    for bdigits in bare:
        for rnum, runit in richer:
            rdigits = rnum.replace(",", "").replace(".", "")
            if rdigits.startswith(bdigits) and (len(rdigits) > len(bdigits) or runit):
                return True
    return False


def _segment_has_artifact(segment: str) -> bool:
    """Return True if a rendered description segment carries a known artifact."""
    if not segment:
        return False
    # Misleading bare "$NN" that drops the magnitude of a fuller figure nearby.
    if _is_misleading_number(segment):
        return True
    # Trailing ad/boilerplate tail (delegated to the canonical stripper).
    return _strip_trailing_artifacts(segment) != segment.strip()


def _count_body_artifacts(body: str) -> int:
    """Count rendered description segments that carry artifacts in a post body."""
    if not body:
        return 0
    # group(1) = news-desc <p>, group(2) = p0-desc <span>; exactly one is set.
    return sum(
        1
        for m in _BODY_DESC_SEG_RE.finditer(body)
        if _segment_has_artifact(m.group(1) or m.group(2) or "")
    )

# Front matter description field patterns (description_ko or description)
_DESC_KO_RE = re.compile(r'^description_ko:\s*["\']?(.+?)["\']?\s*$', re.MULTILINE)
_DESC_RE = re.compile(r'^description:\s*["\']?(.+?)["\']?\s*$', re.MULTILINE)
_TITLE_RE = re.compile(r'^title:\s*["\']?(.+?)["\']?\s*$', re.MULTILINE)
_DATE_RE = re.compile(r"^date:\s*(\d{4}-\d{2}-\d{2})", re.MULTILINE)


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


_ASCII_RATIO_THRESHOLD = 0.70
_ASCII_MIN_LEN = 30


def _ascii_ratio(desc: str) -> float:
    """Return the ratio of ASCII alphabetic chars to all alphabetic chars.

    Returns 0.0 when desc has no alphabetic characters (division-by-zero guard).
    """
    alpha_total = sum(1 for c in desc if c.isalpha())
    if alpha_total == 0:
        return 0.0
    ascii_alpha = sum(1 for c in desc if c.isalpha() and c.isascii())
    return ascii_alpha / alpha_total


def _is_ascii_ratio_high(desc: str) -> bool:
    """Return True if ASCII alphabetic chars exceed the threshold ratio.

    Skips descriptions shorter than _ASCII_MIN_LEN (already caught by other rules).
    """
    if not desc or len(desc) < _ASCII_MIN_LEN:
        return False
    return _ascii_ratio(desc) > _ASCII_RATIO_THRESHOLD


def classify_posts(posts: list[dict]) -> dict:
    """Classify each post description and return aggregated stats."""
    total = len(posts)
    boilerplate_items = []
    title_repeat_items = []
    real_items = []
    no_desc_items = []
    translation_issue_items = []
    ascii_ratio_high_items: list[dict] = []

    mojibake_items: list[dict] = []
    body_artifact_items: list[dict] = []

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
        # ASCII ratio check is independent of other classifications.
        if _is_ascii_ratio_high(desc):
            ascii_ratio_high_items.append(p)
        # Full-body mojibake scan — checks entire post content, not just description
        body = p.get("body", "")
        if body and _MOJIBAKE_RE.search(body):
            mojibake_items.append(p)
        # Rendered body description artifacts (news-desc / p0-desc tails + bad numbers).
        artifact_count = _count_body_artifacts(body)
        if artifact_count:
            body_artifact_items.append({**p, "artifact_count": artifact_count})

    return {
        "total": total,
        "no_desc": no_desc_items,
        "boilerplate": boilerplate_items,
        "title_repeat": title_repeat_items,
        "real": real_items,
        "translation_issues": translation_issue_items,
        "ascii_ratio_high": ascii_ratio_high_items,
        "mojibake": mojibake_items,
        "body_artifacts": body_artifact_items,
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
    ar_count = len(stats["ascii_ratio_high"])
    mj_count = len(stats["mojibake"])
    ba_items = stats.get("body_artifacts", [])
    ba_posts = len(ba_items)
    ba_segs = sum(p.get("artifact_count", 0) for p in ba_items)

    lines = [
        f"Description Quality Report (last {days} day(s))",
        f"  Posts scanned   : {total}",
        f"  Real content    : {real_count} ({_pct(real_count, total)})",
        f"  Title repeat    : {tr_count} ({_pct(tr_count, total)})",
        f"  Boilerplate desc: {bp_count} ({_pct(bp_count, total)})",
        f"  Translation issues: {ti_count} ({_pct(ti_count, total)})",
        f"  ASCII-heavy desc: {ar_count} ({_pct(ar_count, total)})",
        f"  Mojibake (body) : {mj_count} ({_pct(mj_count, total)})",
        f"  Body desc artifacts: {ba_posts} post(s), {ba_segs} segment(s)",
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
    if stats["ascii_ratio_high"]:
        lines.append("")
        lines.append("ASCII-heavy desc posts (top 10):")
        for p in stats["ascii_ratio_high"][:10]:
            lines.append(f"  - {p['file']}: {p['description'][:80]}")
    if stats["mojibake"]:
        lines.append("")
        lines.append("Mojibake (encoding corruption) posts:")
        for p in stats["mojibake"]:
            lines.append(f"  - {p['file']}")
    if ba_items:
        lines.append("")
        lines.append("Body description artifact posts:")
        for p in ba_items:
            lines.append(f"  - {p['file']}: {p['artifact_count']} segment(s)")
    return "\n".join(lines)


def format_markdown(stats: dict, days: int) -> str:
    """Format stats as GitHub Actions markdown summary."""
    total = stats["total"]
    real_count = len(stats["real"])
    bp_count = len(stats["boilerplate"])
    tr_count = len(stats["title_repeat"])
    nd_count = len(stats["no_desc"])
    ti_count = len(stats["translation_issues"])
    ar_count = len(stats["ascii_ratio_high"])
    mj_count = len(stats["mojibake"])
    ba_items = stats.get("body_artifacts", [])
    ba_posts = len(ba_items)
    ba_segs = sum(p.get("artifact_count", 0) for p in ba_items)

    bp_pct = bp_count / total * 100 if total else 0
    ar_pct = ar_count / total * 100 if total else 0
    status_icon = "✅" if bp_pct < 30 else ("⚠️" if bp_pct < 50 else "❌")
    if mj_count > 0 or ar_pct > 50 or ba_posts > 0:
        status_icon = "❌"
    elif ar_pct >= 30 and status_icon == "✅":
        status_icon = "⚠️"

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
        f"| ASCII 과다 desc | {ar_count} | {_pct(ar_count, total)} |",
        f"| Mojibake (인코딩) | {mj_count} | {_pct(mj_count, total)} |",
        f"| 본문 desc 잔재 | {ba_posts} | {ba_segs} segment(s) |",
        f"| description 없음 | {nd_count} | {_pct(nd_count, total)} |",
    ]

    if bp_pct >= 30:
        lines += [
            "",
            f"> ⚠️ **경고**: Boilerplate 비율이 {bp_pct:.1f}%입니다 (임계값: 30%).",
        ]

    if ar_pct >= 30:
        lines += [
            "",
            f"> ⚠️ **경고**: ASCII 과다 description 비율이 {ar_pct:.1f}%입니다 (임계값: 30%).",
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

    if stats["ascii_ratio_high"]:
        lines += ["", "### ASCII 과다 description 포스트 (최대 10개)"]
        for p in stats["ascii_ratio_high"][:10]:
            lines.append(f"- `{p['file']}`: {p['description'][:100]}")

    if ba_items:
        lines += [
            "",
            f"> ❌ **본문 desc 잔재**: {ba_posts}개 포스트에서 {ba_segs}개 세그먼트 검출"
            " (광고/잡음 꼬리 또는 오해 소지 숫자).",
            "",
            "### 본문 desc 잔재 포스트",
        ]
        for p in ba_items:
            lines.append(f"- `{p['file']}`: {p['artifact_count']} segment(s)")

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

    # Guard: zero posts is always a failure, not a "clean" result.
    # When --days N is given and nothing matches, that still means collectors
    # silently produced no output — treating it as "OK" (as the old 0/0 = 0%
    # boilerplate path did) masked the 2026-04-21~23 silent outage for 3 days.
    if total == 0:
        print(
            "ERROR: no posts analyzed — this usually means collectors are silently failing."
            " Check recent workflow runs.",
            file=sys.stderr,
        )
        return 3

    bp_count = len(stats["boilerplate"])
    bp_pct = bp_count / total * 100 if total else 0
    ar_count = len(stats["ascii_ratio_high"])
    ar_pct = ar_count / total * 100 if total else 0

    if args.format == "markdown":
        print(format_markdown(stats, args.days))
    else:
        print(format_text(stats, args.days))

    if bp_pct >= args.warn_threshold:
        print(
            f"WARNING: boilerplate ratio {bp_pct:.1f}% >= {args.warn_threshold:.0f}% threshold",
            file=sys.stderr,
        )

    if ar_pct >= args.warn_threshold:
        print(
            f"WARNING: ASCII-heavy desc ratio {ar_pct:.1f}% >= {args.warn_threshold:.0f}% threshold",
            file=sys.stderr,
        )

    # Exit 1 when boilerplate exceeds 30%, ASCII-heavy exceeds 30%, or any mojibake found
    if bp_pct > 30:
        return 1
    if ar_pct > 30:
        print(
            f"ERROR: ASCII-heavy description ratio {ar_pct:.1f}% exceeds 30% threshold",
            file=sys.stderr,
        )
        return 1
    if len(stats["mojibake"]) > 0:
        print("ERROR: mojibake (encoding corruption) detected in post body", file=sys.stderr)
        return 1
    ba_items = stats.get("body_artifacts", [])
    if ba_items:
        ba_segs = sum(p.get("artifact_count", 0) for p in ba_items)
        print(
            f"ERROR: {ba_segs} body description artifact(s) across {len(ba_items)} post(s)"
            " — ad/boilerplate tails or misleading bare-$ numbers in news-desc/p0-desc.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
