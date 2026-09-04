"""Regression guards for test-suite working-tree isolation invariants.

These tests fail loudly if a conftest isolation fixture is removed or stops
firing, so integration tests can never silently start polluting the committed
repo tree again.
"""

import os
from pathlib import Path

import pytest

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


def test_translator_breaker_closed_at_test_start():
    """``_reset_translator_breaker`` must hand every test a closed breaker.

    ``common.translator`` keeps the circuit breaker in module globals on
    purpose — it exists to stop a *process* from burning its workflow budget —
    so give-ups accumulate across unrelated tests and latch it open at five
    consecutive. Once open, ``translate_to_korean`` skips the call and returns
    its input, so any later test expecting a translation fails.

    Measured 2026-09-04: without the fixture,
    ``test_translator.py::TestTranslateToKoreanDeepTranslator::
    test_translation_result_cached`` failed in the full suite while passing
    alone, and a probe at that point read ``breaker_open=True consecutive=5``.
    Asserting the state here turns that ordering-dependent failure into a
    direct one that names the cause.

    The marker is load-bearing, not decoration: the reset values *are* the
    module defaults, so asserting only "breaker closed" passes with the fixture
    removed — the falsifiability harness reported this guard VACUOUS until the
    marker was added. Same reason ``_http_block_stub`` and
    ``_no_real_sleep_stub`` exist.
    """
    assert getattr(translator, "_breaker_reset_for_test", False), (
        "_reset_translator_breaker conftest fixture 가 비활성이다. "
        "번역 서킷 브레이커는 프로세스 전역이라, 이전 테스트의 give-up 5건이 "
        "누적되면 열린 채로 남아 이후 번역 테스트가 순서에 따라 깨진다."
    )
    assert translator._breaker_open is False
    assert translator._consecutive_failures == 0
    assert translator._failure_total == 0


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
    assert baseline is not None, "_STATE_TMP 앵커가 사라졌다 — 이 가드가 무력화됐다"
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


def test_tvl_history_redirected_off_repo_tree():
    """``_isolate_tvl_history_state`` must redirect TVL-history writes off the tree.

    ``collect_defi_llama.build_post_content()`` calls ``_check_tvl_staleness()``,
    which appends to a ``TimeSeriesStore`` bound to the module global
    ``_TVL_HISTORY_PATH``. Because the write sits on the content-building path, a
    test needs no collector, no network and no fixtures to trigger it — which is
    exactly how ``test_build_post_content_contains_key_sections`` rewrote the
    committed ``_state/defi_tvl_history.json`` on every run before the fixture
    existed.

    No static guard could see it: the path is properly ``__file__``-anchored and
    the test imports no production root. Only the runtime write detector found
    it, and only this redirect keeps it off the tree.
    """
    import collect_defi_llama as defi

    active = os.path.abspath(defi._TVL_HISTORY_PATH)

    assert not active.startswith(_REPO_STATE + os.sep), (
        f"collect_defi_llama._TVL_HISTORY_PATH ({active}) points inside the "
        "committed _state tree during tests — the _isolate_tvl_history_state "
        "conftest fixture is not active. build_post_content() tests will "
        "rewrite the committed TVL history."
    )


def test_real_tree_writes_detected():
    """``_detect_real_tree_writes`` must have every write entry point patched.

    Three layers, because any one alone can pass while the guard is useless:

    1. *Tripwire* — each patch point carries ``_tree_write_guard_stub``.
       ``builtins.open`` and ``io.open`` are the same function object reached
       through different module attributes (``Path.write_text`` calls ``io.open``,
       ``open()`` and PIL call ``builtins.open``), so both names are asserted
       separately; patching one and missing the other silently halves coverage.
    2. *Behaviour* — an actual write into the committed tree must be refused.
       A live tripwire on a detector whose path logic no longer fires would
       still pass layer 1.
    3. *Session baseline* — the out-of-process snapshot half must have run. It
       only manifests at session teardown, so nothing else in the suite would
       notice if the capture were dropped; an unwired snapshot is a silent
       no-op that reads as coverage.
    """
    import builtins
    import io

    from _tree_write_guard import session_baseline

    for owner, name in ((builtins, "open"), (io, "open"), (os, "open"), (os, "replace"), (os, "remove")):
        target = getattr(owner, name)
        assert getattr(target, "_tree_write_guard_stub", False), (
            f"{owner.__name__}.{name} is not patched — the _detect_real_tree_writes "
            "conftest fixture is not active. Tests can write into the committed tree undetected."
        )

    # The probe is only ever created if the detector is inert; when it is live
    # the write is refused before the file exists, so the cleanup is a no-op.
    probe = _REPO_ROOT / "_state" / "__tree_write_guard_probe.tmp"
    try:
        with pytest.raises(AssertionError, match="커밋된 레포 트리에 썼습니다"), open(probe, "w", encoding="utf-8"):
            pass
    finally:
        if probe.exists():
            probe.unlink()

    baseline = session_baseline()
    assert baseline is not None, (
        "no session baseline was captured — the out-of-process snapshot half of "
        "_detect_real_tree_writes is not wired in. Subprocess writes into the "
        "committed tree would go unnoticed."
    )
    assert len(baseline) > 100, (
        f"session baseline holds only {len(baseline)} files; the snapshot walk is "
        "broken (wrong dirs, or every path filtered out) and the comparison at "
        "teardown would be vacuous."
    )


def test_rate_limit_sleeps_are_stubbed():
    """``sleep_calls`` must keep ``time.sleep`` replaced for the whole suite.

    Collectors pace outbound requests with real sleeps (2s per Telegram channel,
    1s per Twitter query, 1-2s per CoinMarketCap endpoint). Under test every fetch
    is mocked, so those sleeps buy nothing and are pure wall-clock — before the
    fixture they were ~102s of a 184s suite.

    Asserted via the recorder's ``_no_real_sleep_stub`` marker rather than by timing
    a sleep: a behavioural probe would have to actually wait, which is the cost this
    guard exists to prevent. This test deliberately does *not* request the
    ``sleep_calls`` fixture — that is what makes it fail when the fixture stops
    being autouse rather than quietly picking it up as an explicit dependency.
    """
    import time

    assert getattr(time.sleep, "_no_real_sleep_stub", False), (
        "time.sleep is the real builtin during tests — the sleep_calls conftest "
        "fixture is not active. Collector rate-limit delays will be paid in real "
        "wall-clock and the suite roughly doubles in duration."
    )
