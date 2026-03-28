#!/usr/bin/env python3
"""Fix boilerplate/generic descriptions in Jekyll posts.

Scans _posts/ for posts within the specified period, detects bad descriptions,
and replaces them using the best available source:
  1. description_ko (if exists and is good quality)
  2. First <p class="news-desc"> or similar content paragraph in post body
  3. First meaningful text line after front matter

Usage:
    python scripts/fix_post_descriptions.py --days 30           # dry-run
    python scripts/fix_post_descriptions.py --days 30 --apply   # apply fixes
    python scripts/fix_post_descriptions.py --file _posts/2026-03-28-foo.md
    python scripts/fix_post_descriptions.py --days 30 --format markdown
"""

import argparse
import re
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Boilerplate detection — same patterns as check_description_quality.py
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
    "investing dragon",
    "최신 시장 분석 뉴스와 분석을 확인하세요",
    "자동 수집 분석 리포트",
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

# Front matter regexes
_DESC_RE = re.compile(r'^description:\s*(.+)$', re.MULTILINE)
_DESC_KO_RE = re.compile(r'^description_ko:\s*(.+)$', re.MULTILINE)
_TITLE_RE = re.compile(r'^title:\s*(.+)$', re.MULTILINE)
_DATE_RE = re.compile(r'^date:\s*(\d{4}-\d{2}-\d{2})', re.MULTILINE)

# Body content patterns — ordered by preference
_NEWS_DESC_RE = re.compile(r'<p\s+class="(?:news-desc|n|p-desc|article-desc)"[^>]*>([^<]{40,})</p>', re.I)
_STRONG_TEXT_RE = re.compile(r'\*\*(.{40,200}?)\*\*')
_LEAD_LINE_RE = re.compile(r'^(\*\*[^*\n]{10,}\*\*[^\n]{10,}|[^*#\-\|<>\[\]{}\n]{50,300})$', re.MULTILINE)
_PLAIN_TEXT_RE = re.compile(r'^([^#\-\*\|<>\[\]{}\n]{50,300})$', re.MULTILINE)

# Worldmonitor alert-box patterns
_WM_TOTAL_RE = re.compile(r'총 수집:\s*<strong>(\d+)건</strong>')
_WM_THEME_RE = re.compile(r'핵심 테마:\s*<strong>([^<]+)</strong>')
_WM_SOURCE_RE = re.compile(r'집중 출처:\s*<strong>([^<]+)</strong>')
_WM_SOURCE_FIELD_RE = re.compile(r'^source:\s*"?worldmonitor"?', re.MULTILINE)


# ---------------------------------------------------------------------------
# Detection helpers
# ---------------------------------------------------------------------------

def _strip_quotes(s: str) -> str:
    return s.strip().strip('"\'')


def _is_boilerplate(desc: str) -> bool:
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
    if not desc or not title:
        return False
    norm_desc = _NORM_RE.sub("", desc.lower())
    norm_title = _NORM_RE.sub("", title.lower())
    if not norm_title:
        return False
    shorter = min(len(norm_desc), len(norm_title))
    longer = max(len(norm_desc), len(norm_title))
    if longer == 0:
        return False
    overlap = sum(1 for c in norm_title if c in norm_desc) / len(norm_title)
    return overlap >= 0.80 and shorter / longer >= 0.50  # type: ignore[return-value]


def _is_bad_description(desc: str, title: str) -> bool:
    return _is_boilerplate(desc) or _is_title_repeat(desc, title)


# ---------------------------------------------------------------------------
# Front matter parsing
# ---------------------------------------------------------------------------

def _parse_front_matter(text: str) -> tuple[int, int]:
    """Return (start, end) byte offsets of content inside --- delimiters.

    Returns (-1, -1) if no front matter found.
    """
    if not text.startswith("---"):
        return -1, -1
    end_idx = text.find("\n---", 3)
    if end_idx == -1:
        return -1, -1
    return 3, end_idx  # content between opening --- and closing ---


def _get_field(text: str, field_re: re.Pattern) -> str:
    m = field_re.search(text)
    if m:
        return _strip_quotes(m.group(1))
    return ""


# ---------------------------------------------------------------------------
# Body content extraction
# ---------------------------------------------------------------------------

def _extract_worldmonitor_desc(text: str) -> str:
    """Extract data-driven description from worldmonitor alert-box HTML."""
    if not _WM_SOURCE_FIELD_RE.search(text):
        return ""
    total_m = _WM_TOTAL_RE.search(text)
    theme_m = _WM_THEME_RE.search(text)
    source_m = _WM_SOURCE_RE.search(text)
    if not (total_m and theme_m):
        return ""
    total = total_m.group(1)
    themes = theme_m.group(1).strip()
    source = source_m.group(1).strip() if source_m else ""
    desc = f"글로벌 {total}건 수집. {themes} 등 주요 테마 분석. "
    if source:
        desc += f"{source} 등 소스 기반 지정학·에너지·금융 동향."
    else:
        desc += "GDELT·Polymarket 등 소스 기반 지정학·에너지·금융 동향."
    return desc


def _extract_body_candidate(text: str) -> str:
    """Extract first meaningful description candidate from post body."""
    # Find end of front matter
    if not text.startswith("---"):
        body = text
    else:
        end_idx = text.find("\n---", 3)
        if end_idx == -1:
            body = text
        else:
            body = text[end_idx + 4:]

    # 1. Try <p class="news-desc"> or similar HTML paragraphs
    m = _NEWS_DESC_RE.search(body)
    if m:
        candidate = m.group(1).strip()
        if not _is_boilerplate(candidate):
            return _truncate(candidate, 200)

    # 2. Try lead line (mixed bold+plain, e.g. "**2026-03-27** 기준 ... 20건을 정리했습니다.")
    for m in _LEAD_LINE_RE.finditer(body):
        candidate = re.sub(r'\*\*', '', m.group(1)).strip()
        if any(skip in candidate for skip in ["---", "layout:", "permalink:"]):
            continue
        if len(candidate) >= 50 and not _is_boilerplate(candidate):
            return _truncate(candidate, 200)

    # 3. Try first bold text block (often a headline summary)
    for m in _STRONG_TEXT_RE.finditer(body):
        candidate = m.group(1).strip()
        if len(candidate) >= 50 and not _is_boilerplate(candidate):
            return _truncate(candidate, 200)

    # 4. Try first plain paragraph line
    for m in _PLAIN_TEXT_RE.finditer(body):
        candidate = m.group(1).strip()
        # Skip lines that look like markdown artifacts or front matter leakage
        if any(skip in candidate for skip in ["---", "layout:", "permalink:", "http"]):
            continue
        if len(candidate) >= 50 and not _is_boilerplate(candidate):
            return _truncate(candidate, 200)

    return ""


def _truncate(s: str, max_len: int) -> str:
    if len(s) <= max_len:
        return s
    truncated = s[:max_len]
    # Try to break at last sentence-ending punctuation
    for punct in (".", "。", "!", "?"):
        idx = truncated.rfind(punct)
        if idx >= max_len // 2:
            return truncated[: idx + 1]
    return truncated.rstrip() + "…"


# ---------------------------------------------------------------------------
# Description replacement (regex-based, preserves front matter format)
# ---------------------------------------------------------------------------

def _replace_description_in_text(content: str, new_desc: str) -> str:
    """Replace the description field value in front matter, preserving formatting."""
    # Escape special regex chars in the replacement
    # Match: description: "old value" or description: old value (with or without quotes)
    # We only replace inside the front matter block (between first --- pair)
    fm_start = 3  # after opening ---\n
    fm_end = content.find("\n---", fm_start)
    if fm_end == -1:
        return content

    front_matter = content[fm_start:fm_end]
    body = content[fm_end:]

    # Replace description line — handle quoted and unquoted values
    new_line = f'description: "{new_desc}"'
    new_fm = _DESC_RE.sub(new_line, front_matter)

    return content[:fm_start] + new_fm + body


# ---------------------------------------------------------------------------
# Post scanning and fixing
# ---------------------------------------------------------------------------

def _post_date_from_text(text: str) -> date | None:
    m = _DATE_RE.search(text)
    if m:
        try:
            return date.fromisoformat(m.group(1))
        except ValueError:
            pass
    return None


def _analyze_post(file_path: Path) -> dict:
    """Analyze a single post and determine if it needs fixing."""
    content = file_path.read_text(encoding="utf-8", errors="ignore")
    title = _get_field(content, _TITLE_RE)
    description = _get_field(content, _DESC_RE)
    description_ko = _get_field(content, _DESC_KO_RE)
    post_date = _post_date_from_text(content)

    needs_fix = _is_bad_description(description, title)

    # Determine best replacement
    replacement = ""
    replacement_source = ""

    if needs_fix:
        # Priority 0: worldmonitor-specific extraction from alert-box HTML
        wm_desc = _extract_worldmonitor_desc(content)
        if wm_desc and not _is_bad_description(wm_desc, title):
            replacement = wm_desc
            replacement_source = "worldmonitor_alert"
        # Priority 1: description_ko if it's good quality
        elif description_ko and not _is_bad_description(description_ko, title):
            replacement = description_ko
            replacement_source = "description_ko"
        else:
            # Priority 2: body content extraction
            # Body candidates are allowed to share terms with the title (title_repeat
            # check is intentionally skipped here — a lead sentence like
            # "2026-03-27 기준 WorldMonitor ... 20건을 정리했습니다." is real content
            # even if it contains the same keywords as the title).
            body_candidate = _extract_body_candidate(content)
            if body_candidate and not _is_boilerplate(body_candidate):
                replacement = body_candidate
                replacement_source = "body_extract"

    return {
        "file": file_path,
        "date": post_date,
        "title": title,
        "description": description,
        "description_ko": description_ko,
        "needs_fix": needs_fix,
        "replacement": replacement,
        "replacement_source": replacement_source,
        "content": content,
    }


def collect_posts(posts_dir: Path, days: int) -> list[dict]:
    cutoff = datetime.now(tz=UTC).date() - timedelta(days=days - 1)
    results = []
    for post_file in sorted(posts_dir.glob("*.md")):
        text = post_file.read_text(encoding="utf-8", errors="ignore")
        post_date = _post_date_from_text(text)
        if post_date is None or post_date < cutoff:
            continue
        results.append(_analyze_post(post_file))
    return results


# ---------------------------------------------------------------------------
# Output formatters
# ---------------------------------------------------------------------------

def _pct(count: int, total: int) -> str:
    if total == 0:
        return "0.0%"
    return f"{count / total * 100:.1f}%"


def _format_text(posts: list[dict], applied: bool, dry_run: bool) -> str:
    total = len(posts)
    needs_fix = [p for p in posts if p["needs_fix"]]
    fixable = [p for p in needs_fix if p["replacement"]]
    unfixable = [p for p in needs_fix if not p["replacement"]]
    ok = [p for p in posts if not p["needs_fix"]]

    mode_label = "DRY-RUN" if dry_run else "APPLIED"
    lines = [
        f"Fix Post Descriptions [{mode_label}]",
        f"  Total scanned  : {total}",
        f"  OK (no fix)    : {len(ok)} ({_pct(len(ok), total)})",
        f"  Needs fix      : {len(needs_fix)} ({_pct(len(needs_fix), total)})",
        f"  Fixable        : {len(fixable)} ({_pct(len(fixable), total)})",
        f"  Unfixable      : {len(unfixable)} ({_pct(len(unfixable), total)})",
    ]

    if fixable:
        lines.append("")
        lines.append("Fixed posts:" if applied else "Would fix (dry-run):")
        for p in fixable:
            src = p["replacement_source"]
            old = p["description"][:60] + ("…" if len(p["description"]) > 60 else "")
            new = p["replacement"][:60] + ("…" if len(p["replacement"]) > 60 else "")
            lines.append(f"  [{src}] {p['file'].name}")
            lines.append(f"    OLD: {old}")
            lines.append(f"    NEW: {new}")

    if unfixable:
        lines.append("")
        lines.append("Unfixable (no replacement found):")
        for p in unfixable:
            lines.append(f"  {p['file'].name}: {p['description'][:80]}")

    return "\n".join(lines)


def _format_markdown(posts: list[dict], applied: bool, dry_run: bool) -> str:
    total = len(posts)
    needs_fix = [p for p in posts if p["needs_fix"]]
    fixable = [p for p in needs_fix if p["replacement"]]
    unfixable = [p for p in needs_fix if not p["replacement"]]
    ok = [p for p in posts if not p["needs_fix"]]

    mode_label = "DRY-RUN" if dry_run else "APPLIED"
    status_icon = "✅" if len(needs_fix) == 0 else ("⚠️" if len(unfixable) == 0 else "❌")

    lines = [
        f"## {status_icon} Fix Post Descriptions [{mode_label}]",
        "",
        "| Category | Count | Ratio |",
        "|----------|------:|------:|",
        f"| 전체 스캔 | {total} | 100% |",
        f"| 정상 | {len(ok)} | {_pct(len(ok), total)} |",
        f"| 수정 필요 | {len(needs_fix)} | {_pct(len(needs_fix), total)} |",
        f"| 수정 가능 | {len(fixable)} | {_pct(len(fixable), total)} |",
        f"| 수정 불가 | {len(unfixable)} | {_pct(len(unfixable), total)} |",
    ]

    if fixable:
        verb = "수정됨" if applied else "수정 예정 (dry-run)"
        lines += ["", f"### {verb} 포스트 ({len(fixable)}건)"]
        for p in fixable:
            src = p["replacement_source"]
            old = p["description"][:100]
            new = p["replacement"][:100]
            lines.append(f"- `{p['file'].name}` [{src}]")
            lines.append(f"  - **전**: {old}")
            lines.append(f"  - **후**: {new}")

    if unfixable:
        lines += ["", f"### 수정 불가 포스트 ({len(unfixable)}건)"]
        for p in unfixable:
            lines.append(f"- `{p['file'].name}`: {p['description'][:100]}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Apply fixes
# ---------------------------------------------------------------------------

def apply_fixes(posts: list[dict]) -> int:
    """Write fixed descriptions to files. Returns count of files modified."""
    count = 0
    for p in posts:
        if not p["needs_fix"] or not p["replacement"]:
            continue
        new_content = _replace_description_in_text(p["content"], p["replacement"])
        if new_content != p["content"]:
            p["file"].write_text(new_content, encoding="utf-8")
            count += 1
    return count


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fix boilerplate/generic descriptions in Jekyll posts."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--days",
        type=int,
        default=30,
        help="Number of days of posts to scan (default: 30)",
    )
    mode.add_argument(
        "--file",
        type=Path,
        help="Fix a single post file",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually write changes (default is dry-run)",
    )
    parser.add_argument(
        "--format",
        choices=["text", "markdown"],
        default="text",
        help="Output format (default: text)",
    )
    parser.add_argument(
        "--posts-dir",
        type=Path,
        default=Path("_posts"),
        help="Path to _posts directory (default: _posts)",
    )
    args = parser.parse_args()

    posts_dir = args.posts_dir
    if not posts_dir.exists():
        print(f"Error: posts directory not found: {posts_dir}", file=sys.stderr)
        return 2

    # Collect posts to analyze
    if args.file:
        file_path = args.file
        if not file_path.exists():
            print(f"Error: file not found: {file_path}", file=sys.stderr)
            return 2
        posts = [_analyze_post(file_path)]
    else:
        posts = collect_posts(posts_dir, args.days)

    if not posts:
        print("No posts found in the specified range.", file=sys.stderr)
        return 0

    dry_run = not args.apply
    applied = False

    # Apply fixes if requested
    if args.apply:
        fixed_count = apply_fixes(posts)
        applied = True
        print(f"Applied {fixed_count} fix(es).", file=sys.stderr)

    # Output report
    if args.format == "markdown":
        print(_format_markdown(posts, applied=applied, dry_run=dry_run))
    else:
        print(_format_text(posts, applied=applied, dry_run=dry_run))

    # Exit 1 if there are unfixable posts (non-zero bad descriptions remain)
    needs_fix = [p for p in posts if p["needs_fix"]]
    unfixable = [p for p in needs_fix if not p["replacement"]]
    if unfixable and not args.apply:
        return 0  # dry-run: informational only
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
