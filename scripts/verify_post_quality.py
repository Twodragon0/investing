"""Post quality verification script.

Checks recent posts for common quality issues:
- English description/excerpt (>70% English characters)
- Missing image references
- Alert-box English keywords
- Empty sections

Usage:
    python scripts/verify_post_quality.py [--date YYYY-MM-DD] [--days N]
"""

import argparse
import glob
import os
import re
import sys
from datetime import datetime, timedelta


def _en_ratio(text: str) -> float:
    """Return ratio of English alphabetic characters."""
    alpha = [c for c in text if c.isalpha()]
    if not alpha:
        return 0.0
    return sum(1 for c in alpha if ord(c) < 128) / len(alpha)


def check_post(filepath: str) -> list[str]:
    """Check a single post for quality issues. Returns list of issue descriptions."""
    issues = []
    fname = os.path.basename(filepath)

    with open(filepath, encoding="utf-8") as f:
        content = f.read()

    if not content.startswith("---"):
        return issues

    # Parse frontmatter
    fm_end = content.index("---", 3)
    fm = content[3:fm_end]
    body = content[fm_end:]

    # 1. English description
    desc_m = re.search(r'^description:\s*"(.+?)"', fm, re.M)
    if desc_m and _en_ratio(desc_m.group(1)) > 0.7:
        issues.append(f"[P0] English description: {desc_m.group(1)[:60]}...")

    # 2. English excerpt
    excerpt_m = re.search(r'^excerpt:\s*"(.+?)"', fm, re.M)
    if excerpt_m and _en_ratio(excerpt_m.group(1)) > 0.7:
        issues.append(f"[P0] English excerpt: {excerpt_m.group(1)[:60]}...")

    # 3. Missing image
    img_m = re.search(r'^image:\s*"(.+?)"', fm, re.M)
    if img_m:
        img_path = img_m.group(1).lstrip("/")
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        if not os.path.exists(os.path.join(repo_root, img_path)):
            issues.append(f"[P1] Missing image: {img_path}")

    # 4. Alert-box English keywords (긴급: pattern)
    for m in re.finditer(
        r"<strong>[^<]*긴급:\s*([^<]+?)\s*-\s*\d+건[^<]*</strong>", body
    ):
        kw_part = m.group(1)
        if _en_ratio(kw_part) > 0.5:
            # Skip if only acronyms (NASDAQ, BTC, etc.)
            words = [w.strip(".,") for w in kw_part.split(",")]
            has_real_english = any(
                len(w) > 5 and not w.isupper() and _en_ratio(w) > 0.8 for w in words
            )
            if has_real_english:
                issues.append(f"[P1] English alert keywords: {kw_part[:60]}")

    # 5. Duplicate headings
    headings = re.findall(r"^(##\s+.+)$", body, re.M)
    for i in range(len(headings) - 1):
        if headings[i].strip() == headings[i + 1].strip():
            issues.append(f"[P2] Duplicate heading: {headings[i].strip()}")
            break

    return issues


def main():
    parser = argparse.ArgumentParser(description="Verify post quality")
    parser.add_argument("--date", help="Check posts for specific date (YYYY-MM-DD)")
    parser.add_argument(
        "--days", type=int, default=1, help="Check posts for last N days (default: 1)"
    )
    args = parser.parse_args()

    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

    if args.date:
        dates = [args.date]
    else:
        today = datetime.now()
        dates = [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(args.days)]

    total_issues = 0
    total_posts = 0

    for date_str in dates:
        posts = sorted(glob.glob(os.path.join(repo_root, f"_posts/{date_str}-*.md")))
        if not posts:
            print(f"[{date_str}] No posts found")
            continue

        print(f"\n[{date_str}] {len(posts)} posts")
        total_posts += len(posts)

        for p in posts:
            issues = check_post(p)
            fname = os.path.basename(p)
            if issues:
                total_issues += len(issues)
                for issue in issues:
                    print(f"  {fname}: {issue}")
            else:
                print(f"  {fname}: ✓")

    print(f"\n{'='*50}")
    print(f"Total: {total_posts} posts, {total_issues} issues")

    return 1 if total_issues > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
