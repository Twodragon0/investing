"""Backfill missing accuracy fields in _state/signal_history.json.

Entries recorded before Phase 3 signal_tracker migration may be missing the
`accuracy` nested dict.  This script normalises those entries by inserting a
stub accuracy structure that is schema-compatible with SignalTracker.

The stub uses the entry's own verdict/score and leaves price-dependent fields
(actual_price_change_pct, actual_direction, correct) as None, since historical
BTC prices are not re-fetched here.  btc_price=null entries are left as-is
(nullable, already handled by _SIGNAL_SCHEMA.allow_null_fields).

Usage:
    python scripts/backfill_signal_history_accuracy.py          # dry-run (default)
    python scripts/backfill_signal_history_accuracy.py --apply  # write changes
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Allow running from repo root or scripts/ directory
_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_SCRIPTS_DIR, ".."))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from common.config import setup_logging  # noqa: E402
from common.time_series_state import TimeSeriesSchema, TimeSeriesStore  # noqa: E402

logger = setup_logging("backfill_signal_history_accuracy")

_HISTORY_FILE = os.path.join(_REPO_ROOT, "_state", "signal_history.json")
_NOW_UTC = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

# Mirrors _SIGNAL_SCHEMA from signal_tracker.py — kept local to avoid import
# side-effects (signal_tracker imports signal_composer which may not be
# available in all environments).
_SIGNAL_SCHEMA = TimeSeriesSchema(
    required_fields=["date"],
    numeric_fields={},
    date_field="date",
    date_format="%Y-%m-%d",
    max_entries=365,
    allow_null_fields=["btc_price"],
    extra_fields_allowed=True,
)


# ── Accuracy stub ─────────────────────────────────────────────────────────────


def _make_accuracy_stub(entry: dict[str, Any]) -> dict[str, Any]:
    """Return a minimal accuracy dict compatible with signal_tracker schema.

    Fields that require a subsequent day's BTC price are set to None.
    The stub is valid for SignalTracker.accuracy_report() — it skips records
    where correct is None.

    Args:
        entry: A signal_history entry dict.

    Returns:
        accuracy dict with all required keys.
    """
    return {
        "predicted_verdict": entry.get("verdict", ""),
        "predicted_score": entry.get("composite_score", 0.0),
        "actual_price_change_pct": None,
        "actual_direction": None,
        "correct": None,
        "evaluated_at": _NOW_UTC,
        "backfilled_accuracy_stub": True,
    }


# ── Core logic ────────────────────────────────────────────────────────────────


def find_missing_accuracy_indices(entries: list[dict[str, Any]]) -> list[int]:
    """Return list of indices where accuracy field is absent.

    Args:
        entries: List of signal_history records.

    Returns:
        List of integer indices (0-based) of entries missing accuracy.
    """
    return [i for i, e in enumerate(entries) if "accuracy" not in e]


def backfill(history_file: str = _HISTORY_FILE, dry_run: bool = True) -> int:
    """Main backfill routine.

    Args:
        history_file: Path to signal_history.json.
        dry_run: If True, report changes without writing.  Default True.

    Returns:
        0 on success, 1 on error.
    """
    path = Path(history_file)

    if not path.exists():
        logger.info("파일 없음, 종료: %s", history_file)
        print(f"File not found (nothing to do): {history_file}")
        return 0

    store = TimeSeriesStore(path, _SIGNAL_SCHEMA, logger)
    entries: list[dict[str, Any]] = store.load(validate=False)

    if not entries:
        logger.info("빈 히스토리, 종료")
        print("Empty history file. Nothing to backfill.")
        return 0

    missing_indices = find_missing_accuracy_indices(entries)

    if not missing_indices:
        logger.info("accuracy 누락 항목 없음. 완료.")
        print("No missing accuracy entries found. Nothing to backfill.")
        return 0

    missing_dates = [entries[i].get("date", f"idx={i}") for i in missing_indices]
    print(f"누락된 accuracy: {len(missing_indices)}건")
    print(f"수정 대상 idx 리스트: {missing_indices}")
    print(f"수정 대상 날짜: {missing_dates}")
    print()

    if dry_run:
        for i in missing_indices:
            entry = entries[i]
            date = entry.get("date", f"idx={i}")
            btc = entry.get("btc_price")
            btc_note = f"btc_price={btc}" if btc is not None else "btc_price=null (nullable, kept)"
            print(f"  DRY-RUN WOULD PATCH idx={i} date={date} ({btc_note})")
        print()
        print("DRY-RUN: no changes written. Re-run with --apply to write.")
        return 0

    # Apply: insert stubs for missing entries
    for i in missing_indices:
        entries[i]["accuracy"] = _make_accuracy_stub(entries[i])
        logger.info(
            "accuracy 스텁 삽입: idx=%d date=%s",
            i,
            entries[i].get("date", "?"),
        )

    store._write_atomic(entries)
    print(f"APPLIED: {len(missing_indices)}건 accuracy 스텁 삽입, 파일 원자적 쓰기 완료.")

    # Post-apply validation
    issues = store.validate(entries)
    errors = [iss for iss in issues if iss.severity == "error"]
    if errors:
        logger.warning("사후 검증 오류 %d건", len(errors))
        for iss in errors:
            logger.warning("  [%s] idx=%d %s", iss.code, iss.index, iss.message)
        print(f"WARNING: {len(errors)} validation error(s) after apply (see logs).")
    else:
        print("VALIDATION: 0 errors after apply.")

    # Confirm no remaining missing accuracy
    remaining = find_missing_accuracy_indices(entries)
    if remaining:
        print(f"WARNING: {len(remaining)} entries still missing accuracy: {remaining}")
    else:
        print("VALIDATION: 0 missing accuracy entries remain.")

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill missing accuracy fields in signal_history.json")
    parser.add_argument(
        "--apply",
        action="store_true",
        default=False,
        help="Actually write changes (default: dry-run mode)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        dest="dry_run_flag",
        help="Explicit dry-run (default when --apply is not set)",
    )
    parser.add_argument(
        "--file",
        default=_HISTORY_FILE,
        help=f"Path to signal_history.json (default: {_HISTORY_FILE})",
    )
    args = parser.parse_args()
    dry_run = not args.apply

    if dry_run:
        print("Mode: DRY-RUN (pass --apply to write changes)\n")
    else:
        print("Mode: APPLY\n")

    sys.exit(backfill(history_file=args.file, dry_run=dry_run))


if __name__ == "__main__":
    main()
