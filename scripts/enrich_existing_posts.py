#!/usr/bin/env python3
"""Batch-enrich existing stock news digest posts with descriptions.

Parses each post's HTML, finds news-card-items without descriptions,
generates analytical summaries from titles, and writes the improved post.
Also removes duplicate 글로벌/한국 주식 뉴스 sections.
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common.enrichment import _analyze_title_content

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

# Check if card already has a description
_HAS_DESC_RE = re.compile(r'class="news-desc"')

# Match the duplicate 글로벌/한국 주식 뉴스 sections
_GLOBAL_SECTION_RE = re.compile(
    r'\n## 글로벌 주식 뉴스\n.*?(?=\n## |\n---|\Z)',
    re.DOTALL,
)
_KOREAN_SECTION_RE = re.compile(
    r'\n## 한국 주식 뉴스\n.*?(?=\n## |\n---|\Z)',
    re.DOTALL,
)

# Match overflow list items without descriptions
_OVERFLOW_ITEM_RE = re.compile(
    r'<li><a href="([^"]*)"[^>]*>([^<]+)</a></li>',
)


def _html_escape(text: str) -> str:
    """Simple HTML escape."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#x27;")
    )


def enrich_card(card_html: str) -> str:
    """Add description to a news-card-item if missing."""
    if _HAS_DESC_RE.search(card_html):
        return card_html  # Already has description

    title_match = _TITLE_RE.search(card_html)
    if not title_match:
        return card_html

    title = title_match.group(1).strip()
    # Unescape HTML entities in title
    title = (
        title.replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#x27;", "'")
        .replace("&#39;", "'")
    )

    desc = _analyze_title_content(title)
    if not desc or desc == title or len(desc) < 20:
        return card_html

    safe_desc = _html_escape(desc)

    # Insert description before the source-tag
    source_tag_pos = card_html.find('<span class="source-tag"')
    if source_tag_pos == -1:
        # Insert before closing </div></div>
        close_pos = card_html.rfind("</div>")
        if close_pos > 0:
            close_pos = card_html.rfind("</div>", 0, close_pos)
        if close_pos > 0:
            return (
                card_html[:close_pos]
                + f'\n<p class="news-desc">{safe_desc}</p>\n'
                + card_html[close_pos:]
            )
    else:
        return (
            card_html[:source_tag_pos]
            + f'<p class="news-desc">{safe_desc}</p>\n'
            + card_html[source_tag_pos:]
        )

    return card_html


def enrich_overflow_item(match: re.Match) -> str:
    """Add a brief description to overflow list items."""
    url = match.group(1)
    title = match.group(2).strip()

    title_unesc = (
        title.replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&#x27;", "'")
    )

    # Only add description if item doesn't already have one
    full_match = match.group(0)
    if " — " in full_match:
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
    return f'<li><a href="{url}">{title}</a> — {safe_desc}</li>'


def process_post(filepath: str) -> bool:
    """Process a single post file. Returns True if modified."""
    with open(filepath, encoding="utf-8") as f:
        content = f.read()

    original = content

    # 1. Enrich news-card-items without descriptions
    content = _CARD_RE.sub(lambda m: enrich_card(m.group(0)), content)

    # 2. Enrich overflow list items
    content = _OVERFLOW_ITEM_RE.sub(enrich_overflow_item, content)

    # 3. Remove duplicate 글로벌/한국 주식 뉴스 sections
    content = _GLOBAL_SECTION_RE.sub("", content)
    content = _KOREAN_SECTION_RE.sub("", content)

    # 4. Clean up excessive blank lines
    content = re.sub(r"\n{4,}", "\n\n\n", content)

    if content != original:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        return True
    return False


def main():
    """Process all stock news digest posts."""
    pattern = re.compile(r"\d{4}-\d{2}-\d{2}-daily-stock-news-digest\.md$")
    posts = sorted(
        f
        for f in os.listdir(POSTS_DIR)
        if pattern.search(f)
    )

    modified = 0
    for filename in posts:
        filepath = os.path.join(POSTS_DIR, filename)
        if process_post(filepath):
            modified += 1
            print(f"  ✓ {filename}")
        else:
            print(f"  - {filename} (no changes)")

    print(f"\nProcessed {len(posts)} posts, modified {modified}")


if __name__ == "__main__":
    main()
