#!/usr/bin/env python3
"""Batch-enrich existing news digest posts with descriptions.

Parses each post's HTML, finds news-card-items without descriptions,
generates analytical summaries from titles, and writes the improved post.
Also removes duplicate sections.

Modes:
  (default)                Add descriptions to cards missing them.
  --refresh-descriptions   Replace boilerplate/generic descriptions with better ones.
  --dry-run                Preview changes without writing files.
  --all-posts              Process all post types, not just stock digests.
"""

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common.enrichment import _analyze_title_content, fetch_page_description  # noqa: E402

POSTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_posts")

# Match news-card-item blocks
_CARD_RE = re.compile(
    r'(<div class="news-card-item">.*?</div>\s*</div>)',
    re.DOTALL,
)

# Match title inside a card
_TITLE_RE = re.compile(
    r'class="news-title"[^>]*>([^<]+)</a>',
    re.DOTALL,
)

# Match link inside a card
_LINK_RE = re.compile(
    r'class="news-title"[^>]*href="([^"]+)"',
    re.DOTALL,
)

# Check if card already has a description
_HAS_DESC_RE = re.compile(r'class="news-desc"')

# Extract existing description text
_DESC_TEXT_RE = re.compile(
    r'<p class="news-desc">([^<]+)</p>',
    re.DOTALL,
)

# Match the duplicate sections
_GLOBAL_SECTION_RE = re.compile(
    r"\n## 글로벌 주식 뉴스\n.*?(?=\n## |\n---|\Z)",
    re.DOTALL,
)
_KOREAN_SECTION_RE = re.compile(
    r"\n## 한국 주식 뉴스\n.*?(?=\n## |\n---|\Z)",
    re.DOTALL,
)

# Match overflow list items without descriptions
_OVERFLOW_ITEM_RE = re.compile(
    r'<li><a href="([^"]*)"[^>]*>([^<]+)</a></li>',
)

# Known boilerplate description patterns to replace in --refresh mode
_BOILERPLATE_PATTERNS = [
    re.compile(r"^암호화폐 시장 관련 소식입니다\.?$"),
    re.compile(r"에서 보도한 뉴스입니다\.?$"),
    re.compile(r"에서 보도한 소식입니다\.?\s*원문에서 세부 내용을 확인하세요\.?$"),
    re.compile(r"에서 보도한 소식입니다\.?$"),
    re.compile(r"관련 소식을 전했습니다\.?$"),
    re.compile(r"^거래소 공지사항입니다\.?\s*$"),
    re.compile(r"^구글 뉴스에서 보도한 소식입니다"),
    re.compile(r"^please enable javascript", re.I),
    re.compile(r"^access denied", re.I),
    re.compile(r"^403 forbidden", re.I),
    re.compile(r"^AMENDMENT NO\.", re.I),
    re.compile(r"^FORM\s+\d", re.I),
]


def _is_boilerplate(desc: str) -> bool:
    """Return True if a description matches known boilerplate patterns."""
    desc = desc.strip()
    if not desc:
        return True
    return any(p.search(desc) for p in _BOILERPLATE_PATTERNS)


def _html_escape(text: str) -> str:
    """Simple HTML escape."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#x27;")
    )


def _html_unescape(text: str) -> str:
    """Reverse simple HTML entities."""
    return (
        text.replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#x27;", "'")
        .replace("&#39;", "'")
    )


def enrich_card(card_html: str, refresh: bool = False, fetch_url: bool = False) -> str:
    """Add or refresh description in a news-card-item."""
    has_desc = _HAS_DESC_RE.search(card_html)

    if has_desc and not refresh:
        return card_html  # Already has description, not refreshing

    title_match = _TITLE_RE.search(card_html)
    if not title_match:
        return card_html

    title = _html_unescape(title_match.group(1).strip())

    # In refresh mode, check if existing desc is boilerplate
    if has_desc and refresh:
        desc_match = _DESC_TEXT_RE.search(card_html)
        if desc_match:
            existing = _html_unescape(desc_match.group(1).strip())
            if not _is_boilerplate(existing):
                return card_html  # Existing desc is good, keep it

    # Try fetching real description from URL first
    desc = ""
    if fetch_url:
        link_match = _LINK_RE.search(card_html)
        if link_match:
            link = link_match.group(1)
            try:
                fetched = fetch_page_description(link, timeout=10)
                if fetched and fetched != title and len(fetched) > 20:
                    desc = fetched
            except Exception:  # noqa: BLE001, S110
                pass

    # Fall back to title-based analysis
    if not desc:
        desc = _analyze_title_content(title)
    if not desc or desc == title or len(desc) < 20:
        return card_html

    safe_desc = _html_escape(desc[:500])

    # If refreshing, replace existing desc
    if has_desc and refresh:
        return _DESC_TEXT_RE.sub(f'<p class="news-desc">{safe_desc}</p>', card_html)

    # Insert description before the source-tag
    source_tag_pos = card_html.find('<span class="source-tag"')
    if source_tag_pos == -1:
        # Insert before closing </div></div>
        close_pos = card_html.rfind("</div>")
        if close_pos > 0:
            close_pos = card_html.rfind("</div>", 0, close_pos)
        if close_pos > 0:
            return card_html[:close_pos] + f'\n<p class="news-desc">{safe_desc}</p>\n' + card_html[close_pos:]
    else:
        return card_html[:source_tag_pos] + f'<p class="news-desc">{safe_desc}</p>\n' + card_html[source_tag_pos:]

    return card_html


def enrich_overflow_item(match: re.Match) -> str:
    """Add a brief description to overflow list items."""
    url = match.group(1)
    title = match.group(2).strip()

    title_unesc = _html_unescape(title)

    # Only add description if item doesn't already have one
    full_match = match.group(0)
    if " \u2014 " in full_match:
        return full_match

    desc = _analyze_title_content(title_unesc)
    if not desc or desc == title_unesc or len(desc) < 20:
        return full_match

    # Truncate for overflow items
    short_desc = desc[:80]
    if len(desc) > 80:
        space_idx = short_desc.rfind(" ", 40)
        if space_idx > 40:
            short_desc = short_desc[:space_idx]
        short_desc += "..."

    safe_desc = _html_escape(short_desc)
    return f'<li><a href="{url}">{title}</a> \u2014 {safe_desc}</li>'


def process_post(
    filepath: str,
    refresh: bool = False,
    dry_run: bool = False,
    fetch_url: bool = False,
) -> tuple:
    """Process a single post file.

    Returns (modified: bool, changes_count: int).
    """
    with open(filepath, encoding="utf-8") as f:
        content = f.read()

    original = content

    # 1. Enrich news-card-items (add or refresh descriptions)
    content = _CARD_RE.sub(
        lambda m: enrich_card(m.group(0), refresh=refresh, fetch_url=fetch_url),
        content,
    )

    # 2. Enrich overflow list items
    content = _OVERFLOW_ITEM_RE.sub(enrich_overflow_item, content)

    # 3. Remove duplicate sections
    content = _GLOBAL_SECTION_RE.sub("", content)
    content = _KOREAN_SECTION_RE.sub("", content)

    # 4. Clean up excessive blank lines
    content = re.sub(r"\n{4,}", "\n\n\n", content)

    if content != original:
        # Count approximate changes
        orig_lines = set(original.splitlines())
        new_lines = set(content.splitlines())
        changes = len(new_lines - orig_lines)

        if not dry_run:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)
        return True, changes
    return False, 0


def main():
    """Process news digest posts with enrichment options."""
    parser = argparse.ArgumentParser(description="Enrich existing news posts with better descriptions.")
    parser.add_argument(
        "--refresh-descriptions",
        action="store_true",
        help="Replace boilerplate descriptions with better title-based ones.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without writing files.",
    )
    parser.add_argument(
        "--all-posts",
        action="store_true",
        help="Process all post types, not just stock digests.",
    )
    parser.add_argument(
        "--fetch-urls",
        action="store_true",
        help="Attempt to fetch real descriptions from article URLs (slow).",
    )
    args = parser.parse_args()

    if args.all_posts:
        pattern = re.compile(r"\d{4}-\d{2}-\d{2}-.*\.md$")
    else:
        pattern = re.compile(r"\d{4}-\d{2}-\d{2}-daily-stock-news-digest\.md$")

    posts = sorted(f for f in os.listdir(POSTS_DIR) if pattern.search(f))

    if not posts:
        print("No matching posts found.")
        return

    mode_label = "[DRY RUN] " if args.dry_run else ""
    refresh_label = "[REFRESH] " if args.refresh_descriptions else ""
    print(f"{mode_label}{refresh_label}Processing {len(posts)} posts...\n")

    modified = 0
    total_changes = 0
    for filename in posts:
        filepath = os.path.join(POSTS_DIR, filename)
        changed, changes = process_post(
            filepath,
            refresh=args.refresh_descriptions,
            dry_run=args.dry_run,
            fetch_url=args.fetch_urls,
        )
        if changed:
            modified += 1
            total_changes += changes
            action = "would modify" if args.dry_run else "modified"
            print(f"  + {filename} ({action}, ~{changes} lines changed)")
        else:
            print(f"  - {filename} (no changes)")

    print(f"\n{mode_label}Processed {len(posts)} posts, {modified} modified, ~{total_changes} lines changed")


if __name__ == "__main__":
    main()
