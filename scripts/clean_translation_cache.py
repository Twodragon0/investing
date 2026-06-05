#!/usr/bin/env python3
"""Clean translation cache by re-applying postprocess fixes.

Runs _postprocess_translation() on all cached values to fix artifacts
introduced by past translator bugs. Safe to run repeatedly — idempotent.

Usage:
    python scripts/clean_translation_cache.py          # apply fixes
    python scripts/clean_translation_cache.py --dry-run # preview only
"""

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from common.translator import _CACHE_PATH, _postprocess_translation

# Cached values whose synthetic "...관련 보도." suffix was mutated by Google
# Translate into 통보/알림/공지/안내/보상/경고 (see enrichment._split_synthetic_ko_suffix).
# These are removed (not patched) so they are re-translated cleanly; the source
# fix changes the translation key, so the bad entries are never re-created.
_MUTATION_ARTIFACT_RE = re.compile(r"관련\s?(?:통보|알림|공지|안내|보상|경고)(?:입니다)?\s*[.。]?\s*$")


def main() -> None:
    parser = argparse.ArgumentParser(description="Clean translation cache artifacts.")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without writing")
    args = parser.parse_args()

    if not _CACHE_PATH.exists():
        print("Translation cache not found, nothing to clean.")
        return

    with open(_CACHE_PATH, encoding="utf-8") as f:
        cache = json.load(f)

    fixed_count = 0
    removed_count = 0
    for key, value in list(cache.items()):
        # Remove suffix-mutation artifacts so they are re-translated cleanly.
        if _MUTATION_ARTIFACT_RE.search(value):
            removed_count += 1
            if args.dry_run:
                print(f"  [remove {key[:8]}] {value[-60:]}")
            else:
                del cache[key]
            continue
        cleaned = _postprocess_translation(value)
        if cleaned != value:
            fixed_count += 1
            if args.dry_run:
                print(f"  [{key[:8]}] {value[:60]}")
                print(f"        → {cleaned[:60]}")
            else:
                cache[key] = cleaned

    if fixed_count == 0 and removed_count == 0:
        print(f"Cache clean: {len(cache)} entries, 0 fixes needed.")
        return

    if args.dry_run:
        print(f"\n[DRY RUN] Would fix {fixed_count} and remove {removed_count} of {len(cache)} entries.")
    else:
        with open(_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False)
        print(f"Fixed {fixed_count}, removed {removed_count} of {len(cache)} cached translations.")


if __name__ == "__main__":
    main()
