#!/usr/bin/env python3
"""Clean legacy untranslated English artifacts in posts.

Removes redundant un-translated English fragments that accumulated in past posts:
1. Pure-English description lines directly below card markdown links
2. Malformed unclosed markdown link lines like '**1. [Binance Has Completed...'
3. Untranslated italic blurbs ('*English text*')
4. Untranslated bullet lines without links in daily news summary
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "scripts"))

from tools.check_untranslated_body import (  # noqa: E402
    _is_scannable,
    is_untranslated,
    scan_lines,
    select_posts,
    split_front_matter,
)


def clean_post_body(body: str) -> tuple[str, int]:
    """Clean untranslated fragments from post body. Return (new_body, removed_count)."""
    lines = body.splitlines()
    new_lines = []
    removed = 0
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Preserve non-scannable markup (HTML tags, tables, code blocks, etc.)
        if not _is_scannable(line):
            new_lines.append(line)
            i += 1
            continue

        # Rule 1: Card English description between markdown link and source tag
        if i > 0 and i + 1 < len(lines):
            prev = lines[i - 1].strip()
            nxt = lines[i + 1].strip()
            if (prev.startswith("**") and "http" in prev) and nxt.startswith('<span class="source-tag"'):
                if is_untranslated(stripped):
                    removed += 1
                    i += 1
                    continue

        # Rule 2: Malformed unclosed link like '**1. [Binance Has Completed...'
        if stripped.startswith("**") and "[" in stripped and "](" not in stripped:
            if is_untranslated(stripped):
                removed += 1
                i += 1
                continue

        # Rule 3: Duplicated list bullet like '- 1. Form 4...' or '[Form 4]...'
        if stripped.startswith("- 1. Form 4") or stripped.startswith("- [Form 4]") or stripped.startswith("[Form 4]"):
            if is_untranslated(stripped):
                removed += 1
                i += 1
                continue

        # Rule 4: Untranslated italic blurb like '*English blurb...*'
        if stripped.startswith("*") and stripped.endswith("*") and is_untranslated(stripped):
            removed += 1
            i += 1
            continue

        # Rule 5: Bare English bullet without link in summaries/digests
        if stripped.startswith("- ") and is_untranslated(stripped):
            removed += 1
            i += 1
            continue

        new_lines.append(line)
        i += 1

    return "\n".join(new_lines), removed


def clean_post(path: Path, *, apply: bool = False) -> tuple[int, int]:
    """Clean a single post. Return (findings_before, findings_after)."""
    original = path.read_text(encoding="utf-8")
    head, body = split_front_matter(original)
    before = len(scan_lines(body))
    if before == 0:
        return 0, 0

    cleaned_body, _ = clean_post_body(body)
    after = len(scan_lines(cleaned_body))

    if apply and after < before:
        # Preserve original trailing newline
        if original.endswith("\n") and not cleaned_body.endswith("\n"):
            cleaned_body += "\n"
        path.write_text(head + cleaned_body, encoding="utf-8")

    return before, after


def main() -> int:
    parser = argparse.ArgumentParser(description="Clean legacy untranslated fragments in posts")
    parser.add_argument("--days", type=int, default=7, help="Look back N days (default: 7)")
    parser.add_argument("--posts-dir", default=str(_REPO_ROOT / "_posts"))
    parser.add_argument("--apply", action="store_true", help="Apply changes (default: dry-run)")
    args = parser.parse_args()

    posts = select_posts(Path(args.posts_dir), args.days)
    total_before = 0
    total_after = 0
    modified = 0

    for path in posts:
        b, a = clean_post(path, apply=args.apply)
        if b > a:
            modified += 1
            total_before += b
            total_after += a
            action = "[CLEANED]" if args.apply else "[DRY]"
            print(f"{action} {path.name}: {b} -> {a}")

    print(f"\nScanned: {len(posts)}, Modified: {modified}")
    print(f"Untranslated lines: {total_before} -> {total_after}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
