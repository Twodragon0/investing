"""Tests for scripts/tools/check_state_orphans.py — orphaned `_state` temp files.

The load-bearing property is the *age* threshold, not the detection. A check
that flagged every `.tmp` would fire on every atomic write in progress, which
trains the reader to ignore it and invites a cleanup that truncates a live
write. So the tests below always pair "the old one is reported" with "the fresh
one is not" — asserting only the first passes with the threshold removed.

Paths are built from ``tmp_path`` and the module's own default is only read,
never written, so nothing here can touch the real ``_state/``.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from tools import check_state_orphans as mod

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def _write_tmp(directory: Path, name: str, *, age_minutes: float, size: int = 16) -> Path:
    """Create a `.tmp` file and backdate its mtime by ``age_minutes``."""
    path = directory / name
    path.write_bytes(b"x" * size)
    when = datetime.now(UTC) - timedelta(minutes=age_minutes)
    stamp = when.timestamp()
    os.utime(path, (stamp, stamp))
    return path


def test_reports_an_aged_temp_file_and_spares_a_fresh_one(tmp_path: Path) -> None:
    """The discriminating case: both files exist, only the aged one is reported."""
    _write_tmp(tmp_path, "old.tmp", age_minutes=180)
    _write_tmp(tmp_path, "fresh.tmp", age_minutes=1)

    orphans = mod.find_orphans(tmp_path, min_age_minutes=60)

    assert [o.path.name for o in orphans] == ["old.tmp"], (
        "a temp file created a minute ago is very likely being written right now"
    )


def test_returns_nothing_for_a_clean_directory(tmp_path: Path) -> None:
    (tmp_path / "real_state.json").write_text("{}", encoding="utf-8")
    assert mod.find_orphans(tmp_path, min_age_minutes=60) == []


def test_returns_nothing_for_a_missing_directory(tmp_path: Path) -> None:
    """A health check must not fail because the directory is not there yet."""
    assert mod.find_orphans(tmp_path / "absent", min_age_minutes=60) == []


def test_only_temp_suffixed_files_are_considered(tmp_path: Path) -> None:
    """State files themselves are aged by definition and must never be reported."""
    _write_tmp(tmp_path, "translation_cache.json", age_minutes=10_000)
    _write_tmp(tmp_path, "orphan.tmp", age_minutes=10_000)

    orphans = mod.find_orphans(tmp_path, min_age_minutes=60)

    assert [o.path.name for o in orphans] == ["orphan.tmp"]


def test_injected_now_ages_a_file_without_sleeping(tmp_path: Path) -> None:
    """`now` is what lets the threshold be tested at all; verify it is honoured."""
    _write_tmp(tmp_path, "borderline.tmp", age_minutes=0)

    assert mod.find_orphans(tmp_path, min_age_minutes=60) == []
    later = datetime.now(UTC) + timedelta(minutes=90)
    assert [o.path.name for o in mod.find_orphans(tmp_path, min_age_minutes=60, now=later)] == ["borderline.tmp"]


def test_subdirectories_are_not_recursed(tmp_path: Path) -> None:
    """Every writer targets `_state/` itself; recursion would pull in strangers."""
    nested = tmp_path / "nested"
    nested.mkdir()
    _write_tmp(nested, "deep.tmp", age_minutes=10_000)

    assert mod.find_orphans(tmp_path, min_age_minutes=60) == []


def test_a_directory_named_like_a_temp_file_is_skipped(tmp_path: Path) -> None:
    """The directory must be *aged*, or the age filter passes this vacuously.

    Verified by mutation: dropping the ``is_file()`` guard left this test green
    while the directory was freshly created, because a zero-minute-old entry is
    excluded by the threshold before the type check ever matters.
    """
    weird = tmp_path / "weird.tmp"
    weird.mkdir()
    stamp = (datetime.now(UTC) - timedelta(minutes=180)).timestamp()
    os.utime(weird, (stamp, stamp))

    assert mod.find_orphans(tmp_path, min_age_minutes=60) == []


def test_reported_size_and_age_are_carried_through(tmp_path: Path) -> None:
    _write_tmp(tmp_path, "big.tmp", age_minutes=120, size=4096)

    orphan = mod.find_orphans(tmp_path, min_age_minutes=60)[0]

    assert orphan.size_bytes == 4096
    assert 119 < orphan.age_minutes < 121


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_exit_status_is_zero_when_clean(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert mod.main(["--state-dir", str(tmp_path)]) == 0
    assert "none older than" in capsys.readouterr().out


def test_exit_status_is_one_when_orphans_are_found(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Non-zero is what the shell health check keys its Slack alert off."""
    _write_tmp(tmp_path, "old.tmp", age_minutes=180)

    assert mod.main(["--state-dir", str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "WARNING" in out
    assert "old.tmp" in out


def test_json_output_is_machine_readable(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write_tmp(tmp_path, "old.tmp", age_minutes=180, size=1024)

    mod.main(["--state-dir", str(tmp_path), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert payload["count"] == 1
    assert payload["total_bytes"] == 1024
    assert payload["orphans"][0]["name"] == "old.tmp"


def test_min_age_minutes_is_configurable(tmp_path: Path) -> None:
    _write_tmp(tmp_path, "old.tmp", age_minutes=180)

    assert mod.main(["--state-dir", str(tmp_path), "--min-age-minutes", "600"]) == 0
    assert mod.main(["--state-dir", str(tmp_path), "--min-age-minutes", "60"]) == 1


def test_the_tool_never_deletes(tmp_path: Path) -> None:
    """Reporting only. The payload is a partial copy of state someone may hold open."""
    path = _write_tmp(tmp_path, "old.tmp", age_minutes=180)

    mod.main(["--state-dir", str(tmp_path)])

    assert path.exists(), "the checker removed a file; it must only report"


def test_default_state_dir_is_repo_anchored() -> None:
    """A cwd-relative default would inspect whatever directory the caller sat in."""
    assert mod._DEFAULT_STATE_DIR.is_absolute()
    assert mod._DEFAULT_STATE_DIR.name == "_state"
    assert mod._DEFAULT_STATE_DIR.parent == mod.REPO_ROOT
