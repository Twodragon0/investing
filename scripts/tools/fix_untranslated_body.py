#!/usr/bin/env python3
"""Retry translation on post body lines that were published untranslated.

Counterpart to ``check_untranslated_body.py``: that script reports the
findings, this one repairs them.

Why a retry pass is the right repair. ``common.translator.translate_to_korean``
is fail-open — it returns its input when the Google Translate call raises, and
logs the failure at ``DEBUG``. Nothing retries, so a transient failure or
rate-limit window during a collection run publishes English prose permanently.
The symptom is partial *within a single post*: on
``_posts/2026-09-02-daily-political-trades-report.md`` item 4's headline is
Korean while the description right below it is still English.

Measured on 2026-09-02: three of the oldest findings were absent from
``_state/translation_cache.json`` (so nothing cached a bad result), were
eligible under ``translator._should_translate_body_line`` (so selection was
never the problem), and all three translated successfully on a later call.
The pipeline had simply given up on them.

Usage::

    python scripts/tools/fix_untranslated_body.py --days 30           # dry-run
    python scripts/tools/fix_untranslated_body.py --days 30 --apply   # write
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "scripts"))

from common.translator import translate_untranslated_body  # noqa: E402
from tools.check_untranslated_body import (  # noqa: E402
    scan_lines,
    select_posts,
    split_front_matter,
)

# One pass is measurably not enough. On the 2026-08-04..09-02 corpus the first
# pass took 151 findings to 13 and a second pass took those 13 to 0, with no
# code change in between — the residue was the same fail-open failure, hit
# again because the pass itself bursts requests at the endpoint. Passes stop as
# soon as one stops improving, so a genuinely untranslatable line costs one
# extra call, not three.
_MAX_PASSES = 3


def fix_post(path: Path, *, apply: bool) -> tuple[int, int]:
    """Retry translation on *path*; return ``(findings_before, findings_after)``.

    Writes only when the finding count actually dropped **and** the body kept
    its line count. Both guards exist because the translator is fail-open: it
    returns the body unchanged on failure, and rewriting the file anyway would
    burn a commit while reporting a fix that did not happen.
    """
    original = path.read_text(encoding="utf-8")
    head, body = split_front_matter(original)
    before = len(scan_lines(body))
    if before == 0:
        return 0, 0

    current, remaining = body, before
    for _ in range(_MAX_PASSES):
        candidate = translate_untranslated_body(current)
        if len(candidate.splitlines()) != len(current.splitlines()):
            # translate_untranslated_body maps line-to-line. A different line
            # count means it mangled the markdown, so a lower finding count
            # would be damage, not repair.
            break
        found = len(scan_lines(candidate))
        if found >= remaining:
            break
        current, remaining = candidate, found
        if remaining == 0:
            break

    if remaining >= before:
        return before, before

    if apply:
        # translate_untranslated_body rebuilds the body with
        # "\n".join(splitlines()), which drops the final newline. Restoring the
        # original's ending keeps repaired posts from showing a spurious
        # "\ No newline at end of file" on a line nobody touched.
        if original.endswith("\n") and not current.endswith("\n"):
            current += "\n"
        path.write_text(head + current, encoding="utf-8")
    return before, remaining


def resolve_files(posts_dir: Path, files: list[str]) -> list[Path]:
    """Resolve ``--files`` arguments to posts inside *posts_dir*.

    Containment is enforced the same way ``improve_existing_posts.py`` does it:
    the collector action feeds this a manifest written by the collection run,
    and a path outside ``_posts`` must not be rewritten.
    """
    resolved: list[Path] = []
    for raw in files:
        path = Path(raw)
        if not path.is_absolute():
            direct = path.resolve()
            path = direct if direct.exists() else (posts_dir / path).resolve()
        if path.suffix != ".md" or not path.exists():
            continue
        if not path.is_relative_to(posts_dir):
            print(f"::warning::posts_dir 밖의 파일을 건너뛴다: {path}", file=sys.stderr)
            continue
        resolved.append(path)
    return sorted(set(resolved))


def main() -> int:
    parser = argparse.ArgumentParser(description="Retry translation on untranslated post body lines")
    parser.add_argument("--days", type=int, default=30, help="Look back N days by filename date (default: 30)")
    parser.add_argument("--posts-dir", default=str(_REPO_ROOT / "_posts"))
    parser.add_argument("--apply", action="store_true", help="Write changes (default: dry-run)")
    parser.add_argument(
        "--files",
        nargs="*",
        default=None,
        help="Process only these posts (overrides --days). Used with the collector's created-post manifest.",
    )
    args = parser.parse_args()

    posts_dir = Path(args.posts_dir).resolve()
    if not posts_dir.is_dir():
        print(f"posts dir not found: {posts_dir}", file=sys.stderr)
        return 2

    if args.files:
        posts = resolve_files(posts_dir, args.files)
        scope = f"{len(posts)} explicit files"
    else:
        posts = select_posts(posts_dir, args.days)
        scope = f"last {args.days}d by filename date"
    total_before = total_after = changed = unfixed_files = 0

    for path in posts:
        before, after = fix_post(path, apply=args.apply)
        if before == 0:
            continue
        total_before += before
        total_after += after
        prefix = "FIX" if args.apply else "DRY"
        if after < before:
            changed += 1
            print(f"[{prefix}] {path.name}: {before} → {after}")
        else:
            unfixed_files += 1
            print(f"[SKIP] {path.name}: {before} findings — translation did not help")

    print(f"Posts scanned ({scope}): {len(posts)}")
    print(f"Posts modified: {changed}")
    print(f"Untranslated lines: {total_before} → {total_after}")
    if unfixed_files:
        print(f"::warning::{unfixed_files}개 포스트는 재시도로도 번역되지 않았다 — 번역 엔드포인트 상태를 확인하라")
    if not args.apply and changed:
        print("dry-run — rerun with --apply to write")
    return 0


if __name__ == "__main__":
    sys.exit(main())
