"""Shared fixtures for investing tests."""

import os
import sys

import pytest

# Add scripts/ to path so `from common.X import Y` works
SCRIPTS_DIR = os.path.join(os.path.dirname(__file__), "..", "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

# Add scripts/tools/ to path so tool modules can be imported directly
TOOLS_DIR = os.path.join(SCRIPTS_DIR, "tools")
if TOOLS_DIR not in sys.path:
    sys.path.insert(0, TOOLS_DIR)


# ---------------------------------------------------------------------------
# Module-level: redirect image_rejection_metrics state to a tmp dir BEFORE any
# test imports the module, so the module's ``atexit`` flush (which runs at
# interpreter shutdown, AFTER per-test monkeypatch has been restored) cannot
# pollute the committed ``_state/image_rejection_metrics.json``.
# ---------------------------------------------------------------------------
try:
    import tempfile
    from pathlib import Path as _Path

    import common.image_rejection_metrics as _irm_a

    _IRM_TEST_DIR = _Path(tempfile.mkdtemp(prefix="inv_irm_test_"))
    _STATE_TMP = _IRM_TEST_DIR / "image_rejection_metrics.json"
    _ARCHIVE_TMP = _IRM_TEST_DIR / "archive"

    _irm_a._STATE_PATH = _STATE_TMP
    _irm_a._ARCHIVE_DIR = _ARCHIVE_TMP

    # Some tests import via `scripts.common.*` (e.g. test_summarizer_helpers.py),
    # which registers a distinct module object in sys.modules from `common.*`.
    # Patch both namespaces so the atexit flush cannot target the repo state.
    try:
        import scripts.common.image_rejection_metrics as _irm_b

        if _irm_b is not _irm_a:
            _irm_b._STATE_PATH = _STATE_TMP
            _irm_b._ARCHIVE_DIR = _ARCHIVE_TMP
    except ImportError:
        pass
except ImportError:
    pass


@pytest.fixture(autouse=True)
def _block_real_http(monkeypatch):
    """Fail fast if a test makes a real outbound HTTP call via ``requests``.

    The enrichment pipeline reaches the network only through ``requests``, and
    every enrichment test mocks it. A misplaced patch (e.g. after the P2-A module
    split relocates a symbol) can silently become inert, letting a real GET hit a
    public host that the SSRF guard permits (``example.com`` resolves publicly) —
    a slow, flaky "green". Blocking the transport layer turns that into an
    immediate, obvious failure. Tests that mock ``requests`` never reach this
    adapter, so they are unaffected; DNS-resolution guards (``socket.getaddrinfo``)
    are also untouched.
    """
    try:
        from requests.adapters import HTTPAdapter
    except ImportError:
        return

    def _blocked(self, request, *args, **kwargs):
        raise RuntimeError(
            f"Real outbound HTTP blocked in tests: {request.method} {request.url}. "
            "A requests mock is missing or patched on the wrong module namespace."
        )

    monkeypatch.setattr(HTTPAdapter, "send", _blocked)


@pytest.fixture(autouse=True)
def _isolate_image_rejection_state(tmp_path, monkeypatch):
    """Redirect image_rejection_metrics state + archive paths to a per-test tmp dir.

    The module registers an ``atexit`` flush that would otherwise pollute the
    committed ``_state/image_rejection_metrics.json`` during local and CI test
    runs. Routing both paths to a throwaway location preserves the module's
    contract without touching production state. Individual tests can still
    override via ``monkeypatch.setattr`` when they need to assert the path.
    """
    try:
        import common.image_rejection_metrics as m
    except ImportError:
        return
    monkeypatch.setattr(m, "_STATE_PATH", tmp_path / "image_rejection_metrics.json")
    monkeypatch.setattr(m, "_ARCHIVE_DIR", tmp_path / "archive")
