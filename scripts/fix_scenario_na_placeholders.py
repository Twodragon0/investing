#!/usr/bin/env python3
"""Strip ``(N/A)`` placeholders from scenario descriptions in published posts.

Earlier signal_composer revisions injected `VIX(N/A)`, `공포·탐욕(N/A)` and
`모멘텀(N/A)` into bull/base/bear scenario sentences when the underlying signal
was missing. The current code suppresses the parenthetical, but the artifacts
remain in already-published posts. This script rewrites them in place.

Usage:
    python scripts/fix_scenario_na_placeholders.py            # dry-run
    python scripts/fix_scenario_na_placeholders.py --apply    # write changes
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
POSTS_DIR = REPO_ROOT / "_posts"

# Order matters: match the longer "지수(N/A)" before the bare "탐욕(N/A)" form.
_REPLACEMENTS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"공포·탐욕 지수\(N/A\)"), "공포·탐욕 지수"),
    (re.compile(r"공포·탐욕\(N/A\)"), "공포·탐욕"),
    (re.compile(r"VIX\(N/A\)"), "VIX"),
    (re.compile(r"모멘텀\(N/A\)"), "모멘텀"),
]


def _patch(text: str) -> tuple[str, int]:
    total = 0
    for pattern, repl in _REPLACEMENTS:
        text, count = pattern.subn(repl, text)
        total += count
    return text, total


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write changes to disk")
    parser.add_argument(
        "--posts-dir",
        type=Path,
        default=POSTS_DIR,
        help="override posts directory (default: %(default)s)",
    )
    args = parser.parse_args()

    if not args.posts_dir.is_dir():
        print(f"[error] posts directory not found: {args.posts_dir}", file=sys.stderr)
        return 2

    files_changed = 0
    replacements = 0
    for path in sorted(args.posts_dir.glob("*.md")):
        original = path.read_text(encoding="utf-8")
        patched, count = _patch(original)
        if count == 0:
            continue
        files_changed += 1
        replacements += count
        if args.apply:
            path.write_text(patched, encoding="utf-8")
        print(f"{'fixed' if args.apply else 'would fix'}: {path.name} ({count} replacements)")

    mode = "applied" if args.apply else "dry-run"
    print(f"\n[{mode}] files={files_changed} replacements={replacements}")
    if not args.apply and files_changed:
        print("re-run with --apply to write changes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
