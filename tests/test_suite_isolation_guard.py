"""Regression guards for test-suite working-tree isolation invariants.

These tests fail loudly if a conftest isolation fixture is removed or stops
firing, so integration tests can never silently start polluting the committed
repo tree again.
"""

import os
from pathlib import Path

import common.dedup as dedup
import common.image_generator as ig
import common.signal_tracker as st
import common.translator as translator

# Test-file-local anchor for the committed repo tree. We deliberately derive the
# path from ``__file__`` instead of importing ``common.image_generator.REPO_ROOT``:
# importing a production real-tree root constant into a test is itself banned by
# ``test_hermetic_test_writes_guard`` (it is the canonical non-hermetic-write
# signal). ``tests/`` lives at the repo root, so its parent is the checkout root.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_REPO_IMAGES = str((_REPO_ROOT / "assets" / "images" / "generated").resolve())
_REPO_STATE = str((_REPO_ROOT / "_state").resolve())


def test_generated_images_redirected_off_repo_tree():
    """``_isolate_generated_images`` must redirect writes off the repo tree.

    Every image_generator save resolves its output dir through
    ``common.image_generator.IMAGES_DIR``. Integration tests (daily summary,
    collectors, briefing cards) that do not patch it themselves rely on the
    autouse fixture to point it at a throwaway tmp dir. If that fixture is
    removed, those tests write PNG/WEBP/AVIF files into the committed
    ``assets/images/generated/`` tree, leaving dirty working-tree side effects.

    Asserting the active dir is not the committed tree turns a silent
    regression into an immediate, obvious failure.
    """
    active = os.path.abspath(ig.IMAGES_DIR)

    assert active != _REPO_IMAGES, (
        "image_generator.IMAGES_DIR points at the committed repo tree during "
        "tests — the _isolate_generated_images conftest fixture is not active. "
        "Image-generating tests will pollute the working tree."
    )
    # The redirect target must also never be nested inside the committed assets
    # tree, or writes would still dirty the working tree.
    assert not active.startswith(_REPO_IMAGES), (
        f"IMAGES_DIR ({active}) is nested inside the committed assets tree; writes would still dirty the working tree."
    )


def test_dedup_state_redirected_off_repo_tree():
    """``_isolate_dedup_state`` must redirect dedup writes off the repo tree.

    Every collector persists cross-run dedup state through ``DedupEngine``,
    which resolves its output file as ``os.path.join(common.dedup.STATE_DIR,
    state_file)``. Integration tests that drive a real collector's
    ``save_state()`` without patching ``STATE_DIR`` rely on the autouse
    fixture to point it at a throwaway tmp dir. If that fixture is removed,
    those tests write ``*_seen.json`` files into the committed ``_state/``
    tree, leaving dirty working-tree side effects.

    Asserting the active dir is not (and is not nested inside) the committed
    ``_state/`` tree turns a silent regression into an immediate failure.
    """
    active = os.path.abspath(dedup.STATE_DIR)

    assert active != _REPO_STATE, (
        "dedup.STATE_DIR points at the committed repo tree during tests — the "
        "_isolate_dedup_state conftest fixture is not active. Collector "
        "save_state() tests will pollute the working tree."
    )
    assert not active.startswith(_REPO_STATE + os.sep), (
        f"STATE_DIR ({active}) is nested inside the committed _state tree; writes would still dirty the working tree."
    )


def test_signal_history_redirected_off_repo_tree():
    """``_isolate_signal_history_state`` must redirect signal writes off the tree.

    ``SignalTracker`` defaults ``history_path`` to ``common.signal_tracker.
    _HISTORY_FILE`` resolved at call time (lazy sentinel). A no-arg
    ``SignalTracker()`` — the form ``collect_market_indicators`` uses in
    production — relies on the autouse fixture to point ``_HISTORY_FILE`` at a
    throwaway tmp file. If that fixture is removed, such tests write
    ``signal_history.json`` into the committed ``_state/`` tree, leaving dirty
    working-tree side effects.

    Asserting the active path is not inside the committed ``_state/`` tree turns
    a silent regression into an immediate failure.
    """
    active = os.path.abspath(st._HISTORY_FILE)

    assert not active.startswith(_REPO_STATE + os.sep), (
        f"signal_tracker._HISTORY_FILE ({active}) points inside the committed "
        "_state tree during tests — the _isolate_signal_history_state conftest "
        "fixture is not active. No-arg SignalTracker() tests will pollute the "
        "working tree."
    )


def test_translation_cache_redirected_off_repo_tree():
    """``_isolate_translation_cache`` must redirect translator writes off the tree.

    ``_save_cache()`` resolves its output through ``common.translator.
    _CACHE_PATH`` read at call time. A real translation flow
    (``translate_batch`` → ``save_translation_cache``) that does not patch
    ``_CACHE_PATH`` relies on the autouse fixture to point it at a throwaway
    tmp file. If that fixture is removed, such tests write
    ``translation_cache.json`` into the committed ``_state/`` tree, leaving
    dirty working-tree side effects.

    Asserting the active path is not inside the committed ``_state/`` tree turns
    a silent regression into an immediate failure.
    """
    active = os.path.abspath(translator._CACHE_PATH)

    assert not active.startswith(_REPO_STATE + os.sep), (
        f"translator._CACHE_PATH ({active}) points inside the committed "
        "_state tree during tests — the _isolate_translation_cache conftest "
        "fixture is not active. translate_batch()/save_translation_cache() "
        "tests will pollute the working tree."
    )


def test_ssrf_dns_resolution_pinned_off_live_network():
    """``_deterministic_dns_resolution`` must pin SSRF DNS off the live network.

    ``common.utils.is_private_url_target`` resolves public hostnames via
    ``socket.getaddrinfo`` and fails closed when resolution fails, so without the
    autouse fixture a runner with no outbound DNS blocks ``example.com`` and the
    collector/enrichment tests that fetch it fail (they pass again once DNS is
    reachable — a flaky-green). This asserts the resolver is the fixture's stub,
    which is network-independent: a live-DNS ``getaddrinfo`` carries no
    ``_ssrf_dns_stub`` marker, so removing the fixture fails here in CI too, not
    only offline.
    """
    import socket

    assert getattr(socket.getaddrinfo, "_ssrf_dns_stub", False), (
        "socket.getaddrinfo is the real resolver during tests — the "
        "_deterministic_dns_resolution conftest fixture is not active. SSRF "
        "DNS-dependent collector/enrichment tests will couple to the runner's "
        "live network and flake when DNS is unavailable."
    )

    # The fixture also clears the guard's DNS TTLCache on both module twins, but
    # it looks the cache up with getattr(..., None) — renaming ``_dns_cache`` or
    # ``_dns_cache_lock`` would turn that clear into a silent no-op and let a
    # resolution cached under a prior (real or offline) resolver leak across
    # tests. Assert the attributes still exist and the cache really is empty at
    # test start, before this test itself populates it below.
    import importlib

    checked = 0
    for mod_name in ("common.utils", "scripts.common.utils"):
        try:
            mod = importlib.import_module(mod_name)
        except ImportError:
            continue
        checked += 1
        assert hasattr(mod, "_dns_cache") and hasattr(mod, "_dns_cache_lock"), (
            f"{mod_name} no longer exposes _dns_cache/_dns_cache_lock — the "
            "_deterministic_dns_resolution cache clear is a silent no-op."
        )
        assert not mod._dns_cache, (
            f"{mod_name}._dns_cache is non-empty at test start — the "
            "_deterministic_dns_resolution fixture did not clear it, so a "
            "stale resolution can leak between tests."
        )

    assert checked, "neither common.utils nor scripts.common.utils was importable"

    # Behavioural corollary: a public URL must not be blocked by the guard.
    from common.utils import is_private_url_target

    assert is_private_url_target("https://example.com/feed.rss") is False, (
        "example.com is blocked by the SSRF guard under the pinned resolver — "
        "the deterministic DNS stub is not returning a public address."
    )


def test_real_http_transport_blocked():
    """``_block_real_http`` must keep the ``requests`` transport blocked.

    Enrichment/collector tests reach the network only through ``requests`` and
    all mock it. A misplaced patch can silently go inert, letting a real GET hit
    a public host the SSRF guard permits — a slow, flaky "green" that depends on
    the runner's connectivity rather than the code under test.

    Asserted via the fixture's ``_http_block_stub`` marker rather than by issuing
    a request: if the fixture were gone, a behavioural probe would itself perform
    the real outbound call this guard exists to prevent.
    """
    try:
        from requests.adapters import HTTPAdapter
    except ImportError:  # pragma: no cover - requests is a hard test dependency
        import pytest

        pytest.skip("requests not installed")

    assert getattr(HTTPAdapter.send, "_http_block_stub", False), (
        "HTTPAdapter.send is the real transport during tests — the "
        "_block_real_http conftest fixture is not active. A missing requests "
        "mock will silently make a real outbound call instead of failing."
    )


def test_image_rejection_state_redirected_off_repo_tree():
    """``_isolate_image_rejection_state`` must redirect metrics writes off-tree.

    ``image_rejection_metrics`` persists counters to ``_STATE_PATH`` and archives
    to ``_ARCHIVE_DIR``. Tests that record a rejection without patching those
    themselves rely on the autouse fixture; without it they write into the
    committed ``_state/`` tree, which the ``pre-commit-state-guard`` hook then
    blocks at commit time.

    Off-tree alone is not a sufficient assertion here: the import-time redirect
    (see ``test_image_rejection_atexit_baseline_off_repo_tree``) already moves
    ``_STATE_PATH`` off the repo tree, so that check stays green even with this
    fixture disabled — verified empirically. What the per-test fixture uniquely
    provides is *per-test* isolation, so also assert the active path has moved
    off the import-time baseline.
    """
    import common.image_rejection_metrics as m
    import tests.conftest as root_conftest

    for attr in ("_STATE_PATH", "_ARCHIVE_DIR"):
        active = os.path.abspath(str(getattr(m, attr)))
        assert not active.startswith(_REPO_STATE + os.sep), (
            f"image_rejection_metrics.{attr} ({active}) points inside the "
            "committed _state tree during tests — the "
            "_isolate_image_rejection_state conftest fixture is not active."
        )

    baseline = getattr(root_conftest, "_STATE_TMP", None)
    if baseline is not None:
        active_state = os.path.abspath(str(m._STATE_PATH))
        assert active_state != os.path.abspath(str(baseline)), (
            "image_rejection_metrics._STATE_PATH still equals the import-time "
            f"baseline ({baseline}) — the _isolate_image_rejection_state "
            "fixture is not active, so every test shares one metrics file "
            "instead of getting its own tmp copy."
        )


def test_image_rejection_atexit_baseline_off_repo_tree():
    """The conftest *module-level* redirect must survive monkeypatch teardown.

    ``image_rejection_metrics`` registers an ``atexit`` flush that runs at
    interpreter shutdown — after every per-test ``monkeypatch`` has been undone.
    So the per-test fixture alone is not enough: the value monkeypatch restores
    *to* must already be off-tree. ``tests/conftest.py`` handles this by
    reassigning ``_STATE_PATH`` at import time, before any test runs.

    That import-time block is wrapped in ``except ImportError: pass``, so if the
    module ever fails to import the redirect silently does not happen and the
    atexit flush lands in the committed ``_state/``. ``_STATE_TMP`` is only bound
    after that import succeeds, which makes it an exact tripwire.
    """
    import tests.conftest as root_conftest

    baseline = getattr(root_conftest, "_STATE_TMP", None)

    assert baseline is not None, (
        "tests/conftest.py did not bind _STATE_TMP — its module-level "
        "image_rejection_metrics redirect did not run (the import-time block "
        "swallowed an ImportError). The atexit flush will write into the "
        "committed _state/ tree at interpreter shutdown."
    )
    assert not os.path.abspath(str(baseline)).startswith(_REPO_STATE + os.sep), (
        f"the atexit restore target ({baseline}) is inside the committed "
        "_state tree; per-test isolation cannot prevent shutdown pollution."
    )
