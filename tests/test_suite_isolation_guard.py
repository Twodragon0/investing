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

    # Behavioural corollary: a public URL must not be blocked by the guard.
    from common.utils import is_private_url_target

    assert is_private_url_target("https://example.com/feed.rss") is False, (
        "example.com is blocked by the SSRF guard under the pinned resolver — "
        "the deterministic DNS stub is not returning a public address."
    )
