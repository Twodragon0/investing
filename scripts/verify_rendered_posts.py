#!/usr/bin/env python3

import glob
import os
import re
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
POSTS_DIR = os.path.join(REPO_ROOT, "_posts")
SITE_DIR = os.path.join(REPO_ROOT, "_site")

TARGETS = [
    {
        "glob": "*daily-worldmonitor-briefing*.md",
        "must_table": True,
        "must_details": True,
        "forbid": [r"\|\s*#\s*\|\s*이슈\s*\|", r"\|[—-]{3,}\|[—-]{3,}\|"],
    },
    {
        "glob": "*daily-news-summary*.md",
        "must_table": True,
        "must_details": False,
        "forbid": [r"\|\s*리포트\s*\|\s*수집 건수\s*\|\s*링크\s*\|"],
    },
    {
        "glob": "*daily-market-report*.md",
        "must_table": True,
        "must_details": False,
        "forbid": [],
    },
]


def _latest_post(pattern: str) -> str:
    files = sorted(glob.glob(os.path.join(POSTS_DIR, pattern)))
    return files[-1] if files else ""


def _site_path_for_post(post_path: str) -> str:
    base = os.path.basename(post_path).replace(".md", "")
    y, m, d, slug = base.split("-", 3)

    # Read category from front matter instead of hardcoding
    category = "market-analysis"
    try:
        with open(post_path, encoding="utf-8") as f:
            in_front = False
            for line in f:
                if line.strip() == "---":
                    if in_front:
                        break
                    in_front = True
                    continue
                if in_front:
                    cat_match = re.match(r"categories:\s*\[([^\]]+)\]", line)
                    if cat_match:
                        category = cat_match.group(1).split(",")[0].strip()
                        break
    except Exception:
        pass

    return os.path.join(SITE_DIR, category, y, m, d, slug, "index.html")


def main() -> int:
    failures = []
    checked = 0

    for target in TARGETS:
        post_path = _latest_post(target["glob"])
        if not post_path:
            continue

        html_path = _site_path_for_post(post_path)
        if not os.path.exists(html_path):
            failures.append(f"missing-rendered-html:{html_path}")
            continue

        checked += 1
        with open(html_path, encoding="utf-8") as f:
            html = f.read()

        if target["must_table"] and "<table" not in html:
            failures.append(f"missing-table:{html_path}")

        if target["must_details"] and "<details" not in html:
            failures.append(f"missing-details:{html_path}")

        for pattern in target["forbid"]:
            if re.search(pattern, html):
                failures.append(f"forbidden-pattern:{pattern}:{html_path}")

    if checked == 0:
        print("No target posts found for rendered smoke tests.")
        return 0

    if failures:
        print("Rendered smoke test failures:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print(f"Rendered smoke tests passed for {checked} post(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
