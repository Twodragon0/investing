"""TDD tests for scripts/common/image_rejection_metrics.py.

All tests must FAIL before the implementation exists (ImportError or AttributeError).
Run: PYTHONPATH=scripts python3 -m pytest tests/test_image_rejection_metrics.py --no-cov -v
"""

import concurrent.futures
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

# Allow `from common.X import Y` when running from repo root
_SCRIPTS = os.path.join(os.path.dirname(__file__), "..", "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)


# ---------------------------------------------------------------------------
# Helper: reset module-level state between tests so counters don't bleed.
# ---------------------------------------------------------------------------


def _reset_module():
    """Reset in-memory counters and re-evaluate kill switch for isolation."""

    import common.image_rejection_metrics as m

    with m._LOCK:
        m._IMAGE_REJECTION_COUNTS.clear()


# ---------------------------------------------------------------------------
# Test 1: record_increments_bucket — happy path, single-thread
# ---------------------------------------------------------------------------


def test_record_increments_bucket():
    import common.image_rejection_metrics as m

    _reset_module()
    m.record_image_rejection("bad_image", "pixel")
    m.record_image_rejection("bad_image", "pixel")
    m.record_image_rejection("bad_image", "tracker")
    with m._LOCK:
        assert m._IMAGE_REJECTION_COUNTS["bad_image"]["pixel"] == 2
        assert m._IMAGE_REJECTION_COUNTS["bad_image"]["tracker"] == 1


# ---------------------------------------------------------------------------
# Test 2: concurrent 8 threads, 10k total calls split across 3 distinct buckets
# ---------------------------------------------------------------------------


def test_concurrent_8_threads_10k_calls_per_bucket():
    import common.image_rejection_metrics as m

    _reset_module()

    buckets = ["pixel", "tracker", "beacon"]
    calls_per_bucket = 10_000 // len(buckets)  # ~3333 each

    def _call(family_bucket):
        family, bucket = family_bucket
        m.record_image_rejection(family, bucket)

    tasks = [("bad_image", b) for b in buckets for _ in range(calls_per_bucket)]

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(_call, tasks))

    with m._LOCK:
        counts = m._IMAGE_REJECTION_COUNTS.get("bad_image", {})
        for b in buckets:
            assert counts.get(b) == calls_per_bucket, f"bucket={b!r} expected={calls_per_bucket} got={counts.get(b)}"
        total = sum(counts.values())
        assert total == calls_per_bucket * len(buckets)


# ---------------------------------------------------------------------------
# Test 3: flock 2-process mutual exclusion
# ---------------------------------------------------------------------------


def test_flock_2_process_mutual_exclusion(tmp_path):
    """Spawn 2 subprocesses each calling flush_to_state() with distinct counters.

    After both finish, state file must be valid JSON with schema_version=1
    and no partial writes.
    """
    state_file = tmp_path / "image_rejection_metrics.json"

    # Helper script each subprocess will run
    helper_code = textwrap.dedent(
        """
        import sys, os, json
        sys.path.insert(0, sys.argv[1])
        os.environ["IMAGE_REJECTION_METRICS_ENABLED"] = "1"

        import common.image_rejection_metrics as m
        m._STATE_PATH = __import__('pathlib').Path(sys.argv[2])

        family = sys.argv[3]
        bucket = sys.argv[4]
        count = int(sys.argv[5])

        with m._LOCK:
            m._IMAGE_REJECTION_COUNTS.setdefault(family, {})[bucket] = count

        m.flush_to_state()
        """
    ).strip()

    helper_path = tmp_path / "helper.py"
    helper_path.write_text(helper_code)

    scripts_dir = str(Path(__file__).resolve().parent.parent / "scripts")

    p1 = subprocess.Popen(
        [
            sys.executable,
            str(helper_path),
            scripts_dir,
            str(state_file),
            "bad_image",
            "pixel",
            "7",
        ]
    )
    p2 = subprocess.Popen(
        [
            sys.executable,
            str(helper_path),
            scripts_dir,
            str(state_file),
            "bad_image",
            "tracker",
            "3",
        ]
    )
    p1.wait(timeout=30)
    p2.wait(timeout=30)

    assert state_file.exists(), "state file not created by either subprocess"
    raw = state_file.read_text()
    data = json.loads(raw)  # raises if partial/corrupt write
    assert data.get("schema_version") == 1
    families = data.get("families", {})
    assert "bad_image" in families


# ---------------------------------------------------------------------------
# Test 4: kill-switch — record is a no-op when disabled
# ---------------------------------------------------------------------------


def test_kill_switch_record_is_noop(monkeypatch):

    # Must reload to pick up env change at module init time
    monkeypatch.setenv("IMAGE_REJECTION_METRICS_ENABLED", "0")
    import common.image_rejection_metrics as m

    # Force re-evaluate _ENABLED
    monkeypatch.setattr(m, "_ENABLED", False)
    _reset_module()

    m.record_image_rejection("bad_image", "pixel")
    with m._LOCK:
        assert "bad_image" not in m._IMAGE_REJECTION_COUNTS


# ---------------------------------------------------------------------------
# Test 5: kill-switch — _render_image_rejection_section emits disabled stub
# ---------------------------------------------------------------------------


def test_kill_switch_report_emits_stub(monkeypatch, tmp_path):
    import common.image_rejection_metrics as m

    monkeypatch.setattr(m, "_ENABLED", False)

    # Import the weekly report module and call the section renderer
    scripts_dir = str(Path(__file__).resolve().parent.parent / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)

    import generate_weekly_report as report

    result = report._render_image_rejection_section()
    assert "disabled" in result.lower() or "metrics disabled" in result.lower()


# ---------------------------------------------------------------------------
# Test 6: schema v1 load
# ---------------------------------------------------------------------------


def test_schema_v1_load(tmp_path):
    import common.image_rejection_metrics as m

    state_file = tmp_path / "image_rejection_metrics.json"
    v1_data = {
        "schema_version": 1,
        "families": {
            "bad_image": {
                "buckets": {"pixel": 5, "tracker": 2},
            }
        },
        "since": "2026-01-01T00:00:00",
        "last_seen": "2026-01-07T00:00:00",
    }
    state_file.write_text(json.dumps(v1_data))

    result = m.load_state(path=state_file)
    assert result["schema_version"] == 1
    assert "bad_image" in result["families"]
    bad = result["families"]["bad_image"]
    assert bad.get("buckets", {}).get("pixel") == 5 or bad.get("pixel") == 5


# ---------------------------------------------------------------------------
# Test 7: schema v0 flat fallback
# ---------------------------------------------------------------------------


def test_schema_v0_flat_fallback(tmp_path):
    import common.image_rejection_metrics as m

    state_file = tmp_path / "image_rejection_metrics.json"
    v0_data = {"buckets": {"pixel": 10, "tracker": 3}}
    state_file.write_text(json.dumps(v0_data))

    result = m.load_state(path=state_file)
    assert result["schema_version"] == 1
    families = result.get("families", {})
    assert "bad_image" in families
    bad_buckets = families["bad_image"].get("buckets", families["bad_image"])
    assert bad_buckets.get("pixel") == 10


# ---------------------------------------------------------------------------
# Test 8: reset_for_archive creates parent dir and archives file
# ---------------------------------------------------------------------------


def test_reset_for_archive_creates_parent_dir(tmp_path, monkeypatch):
    import common.image_rejection_metrics as m

    # Redirect state and archive paths to tmp_path
    state_file = tmp_path / "image_rejection_metrics.json"
    archive_dir = tmp_path / "archive"

    monkeypatch.setattr(m, "_STATE_PATH", state_file)
    monkeypatch.setattr(m, "_ARCHIVE_DIR", archive_dir)

    # Seed state file
    state_file.write_text(json.dumps({"schema_version": 1, "families": {"bad_image": {"buckets": {"pixel": 3}}}}))

    assert not archive_dir.exists()
    m.reset_for_archive("2026-W17")

    assert archive_dir.exists()
    archived = list(archive_dir.glob("image_rejection_metrics-*.json"))
    assert len(archived) == 1


# ---------------------------------------------------------------------------
# Test 9: symmetry with match_bad_image_pattern (PR #747 contract lock)
# ---------------------------------------------------------------------------


def test_symmetry_with_match_bad_image_pattern():
    """Feed URLs through _is_valid_image_url and verify rejection tokens match.

    _IMAGE_REJECTION_COUNTS["bad_image"] must contain exactly the pattern
    tokens returned by match_bad_image_pattern for rejected URLs.
    """
    import common.image_rejection_metrics as m
    from common.enrichment import _is_valid_image_url, match_bad_image_pattern

    _reset_module()

    test_urls = [
        "https://tracker.com/pixel.png",  # matches "pixel"
        "https://analytics.com/beacon.gif",  # matches "beacon"
        "https://cdn.example.com/article-hero.jpg",  # valid — no rejection
        "https://example.com/spacer.gif",  # matches "spacer"
        "https://media.site.com/photo.jpg",  # valid — no rejection
    ]

    expected_patterns = set()
    for url in test_urls:
        # Call purely for its side effect of recording rejection bucket
        _is_valid_image_url(url)
        token = match_bad_image_pattern(url)
        if token is not None:
            expected_patterns.add(token)

    with m._LOCK:
        recorded = m._IMAGE_REJECTION_COUNTS.get("bad_image", {})

    for token in expected_patterns:
        assert token in recorded, (
            f"Expected rejected token {token!r} in _IMAGE_REJECTION_COUNTS but got {dict(recorded)}"
        )
