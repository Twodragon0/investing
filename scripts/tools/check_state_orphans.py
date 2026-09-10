#!/usr/bin/env python3
"""Report orphaned atomic-write temp files left behind in ``_state/``.

Every ``_state`` writer in this repo writes atomically: ``tempfile.mkstemp`` in
the target directory, then ``os.replace`` onto the final name. The temp file
therefore exists for milliseconds. One that is still there minutes later means
the process died between ``mkstemp`` and the rename, and nothing will ever
collect it.

That happened: on 2026-09-07 ``common/translator.py`` left four ~900KB orphans
in ``_state/`` before ``#1284`` added the ``finally`` cleanup. The cleanup fixes
the *cause*; this reports the *symptom*, because the next writer to grow an
un-cleaned early-return path will leak the same way and nothing watches for it.

**Age, not existence, is the signal.** A temp file that is seconds old is very
likely being written right now, and reporting it would train the reader to
ignore this check — or worse, invite a cleanup that truncates a live write.
``--min-age-minutes`` must stay comfortably above the longest legitimate write;
the largest state file in this repo is a few MB, so writes finish in
milliseconds and the 60-minute default has four orders of magnitude of slack.

This tool only reports. It never deletes: deciding that a file is garbage is
cheap to get wrong, and the payload here is a partially written copy of state
another process may still be holding open.

Usage:
    python scripts/tools/check_state_orphans.py
    python scripts/tools/check_state_orphans.py --min-age-minutes 120
    python scripts/tools/check_state_orphans.py --json

Exit status:
    0  no orphans older than the threshold
    1  orphans found (the report lists them)
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_STATE_DIR = REPO_ROOT / "_state"

# Atomic writes complete in milliseconds; this is four orders of magnitude of
# slack. Lower it only with a measurement of the slowest legitimate write.
_DEFAULT_MIN_AGE_MINUTES = 60

# `tempfile.mkstemp(suffix=".tmp")` is what every writer here uses.
_TEMP_GLOB = "*.tmp"


@dataclass(frozen=True)
class Orphan:
    """One temp file that outlived any plausible write."""

    path: Path
    size_bytes: int
    age_minutes: float


def find_orphans(
    state_dir: Path,
    min_age_minutes: float = _DEFAULT_MIN_AGE_MINUTES,
    now: datetime | None = None,
) -> list[Orphan]:
    """Temp files in ``state_dir`` whose mtime is older than the threshold.

    ``now`` is injectable so a test can age a file without sleeping. Not
    recursive: every writer targets ``_state/`` itself, and recursing would pull
    in unrelated temp files from any future subdirectory.
    """
    if not state_dir.is_dir():
        return []
    reference = now or datetime.now(UTC)
    found: list[Orphan] = []
    for path in sorted(state_dir.glob(_TEMP_GLOB)):
        if not path.is_file():
            continue
        try:
            stat = path.stat()
        except OSError:
            # Raced with a cleanup between glob and stat — that is the good case.
            continue
        age = (reference - datetime.fromtimestamp(stat.st_mtime, UTC)).total_seconds() / 60
        if age > min_age_minutes:
            found.append(Orphan(path=path, size_bytes=stat.st_size, age_minutes=age))
    return found


def format_report(orphans: list[Orphan], state_dir: Path, min_age_minutes: float) -> str:
    if not orphans:
        return f"• _state temp orphans: none older than {min_age_minutes:g}m ({state_dir})"
    total_mb = sum(o.size_bytes for o in orphans) / 1_048_576
    lines = [
        f"• _state temp orphans: [WARNING] {len(orphans)} file(s), {total_mb:.1f}MB older than {min_age_minutes:g}m",
    ]
    for orphan in orphans:
        lines.append(
            f"    {orphan.path.name}  {orphan.size_bytes / 1_048_576:.1f}MB  age {orphan.age_minutes / 60:.1f}h"
        )
    lines.append(
        "  A temp file this old means a writer died between mkstemp and os.replace. "
        "Check the owning writer's cleanup path, then remove the files by hand."
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Report orphaned atomic-write temp files in _state/.")
    parser.add_argument(
        "--state-dir",
        type=Path,
        default=_DEFAULT_STATE_DIR,
        help="검사할 디렉토리 (기본: 저장소 _state/)",
    )
    parser.add_argument(
        "--min-age-minutes",
        type=float,
        default=_DEFAULT_MIN_AGE_MINUTES,
        help=(
            "이보다 오래된 .tmp 만 보고한다. 방금 만든 temp 는 지금 쓰이고 있을 수 있으므로 "
            f"보고하지 않는다 (기본 {_DEFAULT_MIN_AGE_MINUTES}분)"
        ),
    )
    parser.add_argument("--json", action="store_true", help="JSON 으로 출력")
    args = parser.parse_args(argv)

    orphans = find_orphans(args.state_dir, args.min_age_minutes)

    if args.json:
        print(
            json.dumps(
                {
                    "state_dir": str(args.state_dir),
                    "min_age_minutes": args.min_age_minutes,
                    "count": len(orphans),
                    "total_bytes": sum(o.size_bytes for o in orphans),
                    "orphans": [
                        {"name": o.path.name, "size_bytes": o.size_bytes, "age_minutes": round(o.age_minutes, 1)}
                        for o in orphans
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(format_report(orphans, args.state_dir, args.min_age_minutes))

    return 1 if orphans else 0


if __name__ == "__main__":
    sys.exit(main())
