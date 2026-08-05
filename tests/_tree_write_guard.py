"""Runtime detector for non-hermetic writes into the committed repo tree.

## Why a runtime detector, when static guards already exist

``test_hermetic_test_writes_guard.py`` AST-scans tests for the *shape* of a
real-tree write (importing a production ``REPO_ROOT``). That catches the
canonical vector, but it reasons about source text: a path assembled at runtime,
handed in by a fixture, or reached through a production default argument is
invisible to it. Static analysis can only see the ways it knows to look.

## Why interception, not a before/after snapshot

The obvious runtime design — snapshot ``assets/``/``_posts/`` before the suite
and diff after — cannot catch the incident that motivated this guard. On
2026-06-30 tests wrote real files under ``REPO_ROOT/assets/images/generated/``
**and removed them in a ``finally`` block**; the leak surfaced only on abnormal
termination. A before/after diff of a normally-terminating run is empty. The
write has to be caught *as it happens*.

So this module patches the write entry points and raises on the first write
whose resolved target is a protected path. That also gives exact attribution —
pytest reports the failing test, and the traceback names the offending line —
where a snapshot only says "something, somewhere, changed".

``builtins.open`` and ``io.open`` are the *same function object* but are reached
through different module attributes: ``Path.write_text``/``Path.open`` call
``io.open``, while ``open(...)`` and PIL's ``Image.save`` call
``builtins.open``. Both names must be patched or half the writes slip through.

## Scope and blind spots (stated, not implied)

In-process writes only. A subprocess (``bundle exec jekyll build``, a collector
launched via ``subprocess.run``) writes through its own interpreter and is not
seen here — :func:`snapshot_tree` / :func:`diff_tree` provide the complementary
end-of-session net for that case. C extensions that write via raw syscalls
without going through ``os``/``io`` are likewise invisible.
"""

from __future__ import annotations

import builtins
import contextlib
import io
import os
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, NamedTuple

if TYPE_CHECKING:
    from collections.abc import Iterator

# Derived from __file__, never imported from production — importing a production
# root constant into a test module is exactly what the hermetic guard bans.
REPO_ROOT = Path(__file__).resolve().parent.parent

# Path components that make a write allowed wherever it appears. These are build
# and tooling artifacts that legitimately live inside the checkout.
_EXEMPT_PARTS = frozenset(
    {
        "__pycache__",
        ".git",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        "node_modules",
        ".venv",
        "vendor",
        ".bundle",
        ".omc",
        "coverage-html",
        ".jekyll-cache",
        ".jekyll-metadata",
    }
)

# Repo-relative path prefixes that are allowed to be written.
_EXEMPT_PREFIXES: tuple[str, ...] = (
    ".coverage",  # coverage data files (.coverage, .coverage.host.pid.random)
    "coverage.json",
)


class Violation(NamedTuple):
    """A single attempted write into the protected tree."""

    operation: str  # "open", "os.open", "os.remove", ...
    path: str  # repo-relative

    def __str__(self) -> str:  # pragma: no cover - formatting only
        return f"{self.operation} -> {self.path}"


def _relative_if_protected(target: Any, *, dir_fd: int | None = None) -> str | None:
    """Return the repo-relative path if writing ``target`` pollutes the tree.

    Returns ``None`` for anything outside the checkout (tmp dirs, /dev/null,
    site-packages) and for the exempt build artifacts above. Non-path arguments
    — an already-open file descriptor handed to ``open()``, for instance — are
    not filesystem targets and are also ``None``.

    ``dir_fd`` with a *relative* path resolves against that descriptor, not cwd,
    so the usual ``abspath`` assumption is wrong and the target is unknowable
    without the fd. This is not hypothetical: ``tempfile.TemporaryDirectory``
    cleanup unlinks via ``os.unlink(name, dir_fd=fd)``, which made a properly
    hermetic tmp-dir teardown look like a write to ``REPO_ROOT/<name>``.
    """
    if isinstance(target, int):  # file descriptor, not a path
        return None
    try:
        path = Path(os.fsdecode(target))
    except (TypeError, ValueError):
        return None
    if dir_fd is not None and not path.is_absolute():
        return None

    # abspath, not resolve(): resolve() follows symlinks and stats the
    # filesystem on every call, which is far too costly on this hot path.
    absolute = Path(os.path.abspath(path))
    try:
        relative = absolute.relative_to(REPO_ROOT)
    except ValueError:
        return None  # outside the checkout — always fine

    parts = relative.parts
    if not parts:
        return None
    if _EXEMPT_PARTS.intersection(parts):
        return None
    if parts[0].startswith(_EXEMPT_PREFIXES):
        return None
    return str(relative)


def _is_write_mode(mode: str) -> bool:
    return any(c in mode for c in "wax+")


# O_RDONLY is 0, so a flags value is a write iff one of these bits is set.
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC

# Operations whose effect depends on whether the target already exists.
_CREATE_OPS = frozenset({"os.mkdir", "os.makedirs"})
_DELETE_OPS = frozenset({"os.remove", "os.unlink", "os.rmdir", "shutil.rmtree"})


class TreeWriteGuard:
    """Patches the write entry points and reports protected-tree writes.

    ``on_violation`` decides the policy: raise to block the write and fail the
    test, or append to a list for a report-only discovery run.
    """

    def __init__(self, on_violation: Callable[[Violation], None]) -> None:
        self._on_violation = on_violation
        self._originals: list[tuple[Any, str, Any]] = []

    # -- patching ---------------------------------------------------------

    def _patch(self, owner: Any, name: str, factory: Callable[[Any], Any]) -> None:
        original = getattr(owner, name)
        self._originals.append((owner, name, original))
        wrapper = factory(original)
        # Tripwire: lets the isolation guard confirm this patch point is live
        # without performing a write. Mirrors ``_ssrf_dns_stub`` /
        # ``_http_block_stub`` in conftest.
        wrapper._tree_write_guard_stub = True
        setattr(owner, name, wrapper)

    def install(self) -> None:
        _INSTALLED.append(self)
        # `open` — patched on BOTH names: same object, different lookup paths.
        for owner in (builtins, io):
            self._patch(owner, "open", self._wrap_open)
        self._patch(os, "open", self._wrap_os_open)
        for name in ("remove", "unlink", "rmdir", "mkdir", "makedirs"):
            self._patch(os, name, self._wrap_path_arg(f"os.{name}"))
        for name in ("rename", "replace"):
            self._patch(os, name, self._wrap_two_path_args(f"os.{name}"))
        # shutil.copyfile/copy/move funnel through open(), but rmtree calls
        # os.unlink/os.rmdir on a walk it performs itself — cheap to cover here
        # and it names the whole tree rather than one leaf file.
        self._patch(shutil, "rmtree", self._wrap_path_arg("shutil.rmtree"))

    def uninstall(self) -> None:
        for owner, name, original in reversed(self._originals):
            setattr(owner, name, original)
        self._originals.clear()
        if self in _INSTALLED:
            _INSTALLED.remove(self)

    def __enter__(self) -> TreeWriteGuard:
        self.install()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.uninstall()

    # -- wrappers ---------------------------------------------------------

    def _report(self, operation: str, target: Any, *, dir_fd: int | None = None) -> None:
        relative = _relative_if_protected(target, dir_fd=dir_fd)
        if relative is None:
            return
        # Only calls that actually change the tree count. Creating a directory
        # that already exists, or deleting a path that does not, is a no-op —
        # `post_generator.os.makedirs(POSTS_DIR, exist_ok=True)` reaches the real
        # `_posts/` on every collector test but leaves it untouched. Reporting
        # those would bury the writes that do land under constant noise.
        exists = (REPO_ROOT / relative).exists()
        if operation in _CREATE_OPS and exists:
            return
        if operation in _DELETE_OPS and not exists:
            return
        self._on_violation(Violation(operation, relative))

    def _wrap_open(self, original: Any) -> Any:
        def guarded(file: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
            if _is_write_mode(mode):
                self._report("open", file)
            return original(file, mode, *args, **kwargs)

        return guarded

    def _wrap_os_open(self, original: Any) -> Any:
        def guarded(path: Any, flags: int, *args: Any, **kwargs: Any) -> Any:
            if flags & _WRITE_FLAGS:
                self._report("os.open", path, dir_fd=kwargs.get("dir_fd"))
            return original(path, flags, *args, **kwargs)

        return guarded

    def _wrap_path_arg(self, operation: str) -> Callable[[Any], Any]:
        def factory(original: Any) -> Any:
            def guarded(path: Any, *args: Any, **kwargs: Any) -> Any:
                self._report(operation, path, dir_fd=kwargs.get("dir_fd"))
                return original(path, *args, **kwargs)

            return guarded

        return factory

    def _wrap_two_path_args(self, operation: str) -> Callable[[Any], Any]:
        def factory(original: Any) -> Any:
            def guarded(src: Any, dst: Any, *args: Any, **kwargs: Any) -> Any:
                self._report(operation, src, dir_fd=kwargs.get("src_dir_fd"))
                self._report(operation, dst, dir_fd=kwargs.get("dst_dir_fd"))
                return original(src, dst, *args, **kwargs)

            return guarded

        return factory


# Guards currently patched in, outermost first. Wrappers chain — an inner guard
# calls what it replaced, which is the outer guard's wrapper — so a second guard
# installed on top of the session one still trips the session policy.
_INSTALLED: list[TreeWriteGuard] = []


@contextlib.contextmanager
def suspended() -> Iterator[None]:
    """Lift every installed guard for the block, then reinstall them.

    Test-infrastructure only, for exercising a guard instance in isolation
    (``tests/test_tree_write_guard.py``). Production tests must never reach for
    this to "allow" a write — redirect the module's path constant instead.
    """
    lifted = list(_INSTALLED)
    for guard in reversed(lifted):
        guard.uninstall()
    try:
        yield
    finally:
        for guard in lifted:
            guard.install()


# ---------------------------------------------------------------------------
# Complementary net: catches out-of-process writes the interceptor cannot see.
# ---------------------------------------------------------------------------

# Trees worth snapshotting: committed content a stray write would dirty. Kept
# narrow because this walks the filesystem.
_SNAPSHOT_DIRS: tuple[str, ...] = ("_posts", "_state", "assets/images/generated")


def snapshot_tree() -> dict[str, int]:
    """Map repo-relative path -> size for the snapshotted content dirs.

    Size rather than a hash: this runs on a tree with thousands of images, and
    the goal is detecting *appearance/disappearance/growth*, not byte-level
    equality. Hashing every file would cost more than the guard is worth.
    """
    snapshot: dict[str, int] = {}
    for relative_dir in _SNAPSHOT_DIRS:
        root = REPO_ROOT / relative_dir
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if path.is_file() and not _EXEMPT_PARTS.intersection(path.parts):
                snapshot[str(path.relative_to(REPO_ROOT))] = path.stat().st_size
    return snapshot


def diff_tree(before: dict[str, int], after: dict[str, int]) -> list[str]:
    """Human-readable added/removed/modified entries between two snapshots."""
    changes = [f"added: {p}" for p in sorted(set(after) - set(before))]
    changes += [f"removed: {p}" for p in sorted(set(before) - set(after))]
    changes += [f"modified: {p}" for p in sorted(set(before) & set(after)) if before[p] != after[p]]
    return changes
