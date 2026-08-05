"""Unit tests for the runtime real-tree write detector.

``test_suite_isolation_guard.test_real_tree_writes_detected`` proves the
detector is *installed*; these prove it is *correct*. A detector that classifies
every path as safe would pass the installation check and catch nothing, so the
path-classification rules are pinned here in both directions — what must be
flagged, and what must be spared.

The false-negative direction matters as much as the false-positive one: an
over-eager detector that flagged tmp dirs or ``__pycache__`` would be turned off
within a day, which is the same outcome as having no detector.
"""

from __future__ import annotations

import contextlib
import os
from typing import TYPE_CHECKING

import pytest
from _tree_write_guard import (
    REPO_ROOT,
    TreeWriteGuard,
    Violation,
    _is_write_mode,
    _relative_if_protected,
    diff_tree,
    suspended,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


class _Blocked(Exception):
    """Sentinel: the guard refused a write. Never escapes ``_collect``."""


def _remove(path: Path) -> None:
    """Delete ``path`` if present, with the installed guards lifted.

    ``Path.unlink`` goes through the patched ``os.unlink``; deleting an existing
    file under ``_state/`` is itself a protected-tree mutation, so the session
    guard would refuse the cleanup. Suspending is required, not cosmetic.
    """
    with suspended():
        path.unlink(missing_ok=True)


@pytest.fixture
def probe_path(request: pytest.FixtureRequest) -> Iterator[Path]:
    """An absent path inside the protected tree, guaranteed clean either side.

    The tests below deliberately aim a write at the committed tree. When the
    detector works the write never lands — but these same tests are run by the
    falsifiability harness with the detector *broken*, and then it does. CI
    caught exactly that: the ``io.open`` mutation let ``Path.write_text``
    through and left ``_state/__unit_probe_pathlib.json`` behind, failing the
    "working tree restored" check. A test that proves writes are blocked must
    clean up after the case where they are not.
    """
    target = REPO_ROOT / "_state" / f"__unit_probe_{request.node.name}.json"
    _remove(target)
    try:
        yield target
    finally:
        _remove(target)


class TestProtectedPathClassification:
    """``_relative_if_protected`` — the rule that decides what counts."""

    @pytest.mark.parametrize(
        "relative",
        [
            "_posts/2026-08-05-x.md",
            "_state/dedup_seen.json",
            "assets/images/generated/x.png",
            "_data/nav.yml",
            "_layouts/post.html",
            "scripts/common/dedup.py",
            "docs/test-isolation.md",
        ],
    )
    def test_committed_tree_paths_are_protected(self, relative: str) -> None:
        assert _relative_if_protected(str(REPO_ROOT / relative)) == relative

    @pytest.mark.parametrize(
        "relative",
        [
            "tests/__pycache__/test_x.cpython-313.pyc",
            "scripts/common/__pycache__/dedup.cpython-313.pyc",
            ".git/index",
            ".pytest_cache/v/cache/lastfailed",
            "node_modules/foo/index.js",
            ".omc/state/session.json",
            "coverage-html/index.html",
            ".coverage",
            ".coverage.host.12345.987654",
            "coverage.json",
        ],
    )
    def test_build_artifacts_are_exempt(self, relative: str) -> None:
        assert _relative_if_protected(str(REPO_ROOT / relative)) is None

    def test_paths_outside_the_checkout_are_ignored(self, tmp_path: Path) -> None:
        assert _relative_if_protected(str(tmp_path / "anything.json")) is None
        assert _relative_if_protected("/dev/null") is None

    def test_accepts_path_objects_and_bytes(self) -> None:
        target = REPO_ROOT / "_state" / "x.json"
        assert _relative_if_protected(target) == "_state/x.json"
        assert _relative_if_protected(os.fsencode(str(target))) == "_state/x.json"

    def test_file_descriptors_are_not_paths(self) -> None:
        """``open(fd, "w")`` passes an int — a descriptor, not a filesystem target."""
        assert _relative_if_protected(3) is None

    def test_relative_path_with_dir_fd_is_ignored(self) -> None:
        """``dir_fd`` resolves the name against a descriptor, not cwd.

        ``tempfile.TemporaryDirectory`` teardown calls
        ``os.unlink(name, dir_fd=fd)``. Treating that bare name as cwd-relative
        reported a correctly hermetic tmp cleanup as a write to
        ``REPO_ROOT/<name>`` — 26 of the 29 findings in the first discovery run
        were this one bug.
        """
        assert _relative_if_protected("_state", dir_fd=7) is None
        assert _relative_if_protected("cache.json", dir_fd=7) is None
        # An absolute path is unambiguous even when dir_fd is supplied.
        assert _relative_if_protected(str(REPO_ROOT / "_state" / "x.json"), dir_fd=7) == "_state/x.json"


class TestWriteModeDetection:
    @pytest.mark.parametrize("mode", ["w", "wb", "a", "ab", "x", "r+", "rb+", "w+b"])
    def test_write_modes_detected(self, mode: str) -> None:
        assert _is_write_mode(mode)

    @pytest.mark.parametrize("mode", ["r", "rb", "rt"])
    def test_read_modes_ignored(self, mode: str) -> None:
        assert not _is_write_mode(mode)


class TestInterception:
    """End-to-end: the patched entry points actually observe writes."""

    def _collect(self, action) -> list[Violation]:
        """Run ``action`` under a fresh guard that blocks on the first violation.

        Two details this encodes:

        * The session guard is *suspended*. Wrappers chain — a guard installed on
          top of the session one records the call and then hands it to what it
          replaced, i.e. the session guard's wrapper, which raises. Suspending
          isolates this instance's behaviour.
        * The callback raises rather than merely recording. A record-and-continue
          callback lets the write through, so the "detected" assertion would pass
          *and* leave a real file in ``_state/`` — the very pollution under test.
          Blocking keeps these tests hermetic, which is the point.
        """
        found: list[Violation] = []

        def block(violation: Violation) -> None:
            found.append(violation)
            raise _Blocked

        with suspended(), TreeWriteGuard(block), contextlib.suppress(_Blocked):
            action()
        return found

    def test_builtin_open_write_into_tree_is_caught(self, probe_path: Path) -> None:
        relative = str(probe_path.relative_to(REPO_ROOT))
        found = self._collect(lambda: self._swallow(lambda: open(probe_path, "w")))  # noqa: SIM115 — must be refused
        assert [v.path for v in found] == [relative]
        assert not probe_path.exists(), "the guard must refuse the write, not observe it after the fact"

    def test_pathlib_write_text_is_caught(self, probe_path: Path) -> None:
        """``Path.write_text`` goes through ``io.open``, not ``builtins.open``."""
        relative = str(probe_path.relative_to(REPO_ROOT))
        found = self._collect(lambda: self._swallow(lambda: probe_path.write_text("x", encoding="utf-8")))
        assert [v.path for v in found] == [relative]
        assert not probe_path.exists(), "io.open path is unguarded — Path.write_text slipped through"

    def test_reads_are_not_caught(self) -> None:
        found = self._collect(lambda: self._swallow(lambda: open(REPO_ROOT / "pyproject.toml").close()))
        assert found == []

    def test_tmp_writes_are_not_caught(self, tmp_path: Path) -> None:
        def write() -> None:
            (tmp_path / "ok.json").write_text("{}", encoding="utf-8")

        assert self._collect(write) == []

    def test_creating_an_existing_directory_is_not_a_change(self) -> None:
        """``post_generator`` calls ``os.makedirs(POSTS_DIR, exist_ok=True)`` on
        every collector test; the real ``_posts/`` already exists, so nothing
        changes and reporting it would be pure noise."""
        found = self._collect(lambda: os.makedirs(REPO_ROOT / "_posts", exist_ok=True))
        assert found == []

    def test_deleting_a_missing_path_is_not_a_change(self) -> None:
        found = self._collect(lambda: self._swallow(lambda: os.remove(REPO_ROOT / "_state" / "__absent.json")))
        assert found == []

    def test_uninstall_restores_every_entry_point(self) -> None:
        import builtins
        import io

        before = [builtins.open, io.open, os.open, os.replace, os.remove]
        with TreeWriteGuard(lambda _v: None):
            assert getattr(builtins.open, "_tree_write_guard_stub", False)
            assert getattr(io.open, "_tree_write_guard_stub", False)
        after = [builtins.open, io.open, os.open, os.replace, os.remove]
        assert before == after, "guard did not restore the original write entry points"

    @staticmethod
    def _swallow(action) -> None:
        """Run ``action`` ignoring OS errors — we assert on detection, not IO."""
        try:
            result = action()
        except OSError:
            return
        close = getattr(result, "close", None)
        if close is not None:
            close()


class TestSnapshotDiff:
    """The complementary out-of-process net."""

    def test_reports_added_removed_and_modified(self) -> None:
        before = {"a": 1, "b": 2, "c": 3}
        after = {"b": 2, "c": 99, "d": 4}
        assert diff_tree(before, after) == ["added: d", "removed: a", "modified: c"]

    def test_identical_snapshots_are_clean(self) -> None:
        assert diff_tree({"a": 1}, {"a": 1}) == []
