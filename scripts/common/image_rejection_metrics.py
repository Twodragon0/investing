"""Thread-safe, flock-guarded image rejection metrics aggregator.

Records per-family, per-bucket rejection counts in-process and flushes them
to a JSON state file on ``atexit``.  A file-level lock (``fcntl.flock``) makes
concurrent flush calls from multiple OS processes safe.

Kill-switch: set ``IMAGE_REJECTION_METRICS_ENABLED=0`` to make every public
function a no-op.  The weekly report renderer emits a stub when disabled.

Schema v1:
    {
        "schema_version": 1,
        "families": {
            "bad_image": {
                "buckets": {"pixel": 3, "tracker": 1, ...}
            }
        },
        "since": "ISO-8601",
        "last_seen": "ISO-8601"
    }
"""

import atexit
import fcntl
import json
import os
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Dict

from .config import setup_logging

logger = setup_logging("image_rejection_metrics")

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_LOCK: threading.Lock = threading.Lock()
_IMAGE_REJECTION_COUNTS: Dict[str, Dict[str, int]] = {}
# Anchor state paths to the repo root so they resolve identically regardless of
# the caller's cwd (dedup.py/signal_tracker.py/translator.py use the same idiom).
# Previously bare-relative Path("_state/...") created a stray scripts/_state/ when
# a script was run from the scripts/ directory.
_REPO_ROOT: Path = Path(__file__).resolve().parent.parent.parent
_STATE_PATH: Path = _REPO_ROOT / "_state" / "image_rejection_metrics.json"
_ARCHIVE_DIR: Path = _REPO_ROOT / "_state" / "archive"
_SCHEMA_VERSION: int = 1
_ENABLED: bool = os.environ.get("IMAGE_REJECTION_METRICS_ENABLED", "1") != "0"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def record_image_rejection(family: str, bucket: str) -> None:
    """Increment the in-memory counter for *family* / *bucket*.

    No-op when the kill-switch is active (``IMAGE_REJECTION_METRICS_ENABLED=0``).
    Thread-safe: protected by ``_LOCK``.
    """
    if not _ENABLED:
        return
    with _LOCK:
        if family not in _IMAGE_REJECTION_COUNTS:
            _IMAGE_REJECTION_COUNTS[family] = {}
        _IMAGE_REJECTION_COUNTS[family][bucket] = _IMAGE_REJECTION_COUNTS[family].get(bucket, 0) + 1


def flush_to_state(path: Path | None = None) -> None:
    """Merge in-memory counts into the JSON state file atomically.

    Uses ``fcntl.flock(LOCK_EX)`` on a sidecar lock file so concurrent OS
    processes do not corrupt the state.  Writes via tmp-file + rename for
    crash-safety.  No-op when the kill-switch is active.
    """
    if not _ENABLED:
        return

    target = path if path is not None else _STATE_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    lock_path = target.with_suffix(".lock")

    with open(lock_path, "a") as lock_fd:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        try:
            existing = _read_raw(target)
            # Merge in-memory counts into existing state
            with _LOCK:
                snapshot = {f: dict(buckets) for f, buckets in _IMAGE_REJECTION_COUNTS.items()}
            for family, buckets in snapshot.items():
                fam_entry = existing["families"].setdefault(family, {"buckets": {}})
                fam_buckets = fam_entry.setdefault("buckets", {})
                for bucket, count in buckets.items():
                    fam_buckets[bucket] = fam_buckets.get(bucket, 0) + count

            existing["last_seen"] = _now_iso()
            if not existing.get("since"):
                existing["since"] = existing["last_seen"]

            # Atomic write
            tmp = target.with_suffix(".tmp")
            tmp.write_text(json.dumps(existing, ensure_ascii=False, indent=2))
            tmp.replace(target)
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)


def load_state(path: Path | None = None) -> dict:
    """Return the current on-disk state as a v1-shaped dict.

    Coerces the legacy v0 flat shape ``{"buckets": {...}}`` into v1.
    Returns an empty stub if the file is missing or unreadable.
    """
    target = path if path is not None else _STATE_PATH
    return _read_raw(target)


def reset_for_archive(week_label: str) -> Path:
    """Rotate the live state file into ``_state/archive/`` and zero counters.

    Creates the archive directory if it does not exist.  Returns the path of
    the archived file.
    """
    target = _STATE_PATH
    dest_dir = _ARCHIVE_DIR
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"image_rejection_metrics-{week_label}.json"

    if target.exists():
        target.replace(dest)

    with _LOCK:
        _IMAGE_REJECTION_COUNTS.clear()

    return dest


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%S")


def _empty_v1() -> dict:
    return {
        "schema_version": _SCHEMA_VERSION,
        "families": {},
        "since": "",
        "last_seen": "",
    }


def _read_raw(path: Path) -> dict:
    """Read and coerce the JSON state file to v1 shape.  Returns empty stub on error."""
    if not path.exists():
        return _empty_v1()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("image_rejection_metrics: could not read %s: %s", path, exc)
        return _empty_v1()

    # v0 flat shape: {"buckets": {...}} — no schema_version key
    if "schema_version" not in data and "buckets" in data:
        return {
            "schema_version": _SCHEMA_VERSION,
            "families": {"bad_image": {"buckets": dict(data["buckets"])}},
            "since": data.get("since", ""),
            "last_seen": data.get("last_seen", ""),
        }

    # Already v1 (or future version) — return as-is, ensure families key exists
    data.setdefault("schema_version", _SCHEMA_VERSION)
    data.setdefault("families", {})
    data.setdefault("since", "")
    data.setdefault("last_seen", "")
    return data


# ---------------------------------------------------------------------------
# Register atexit flush
# ---------------------------------------------------------------------------
atexit.register(flush_to_state)
