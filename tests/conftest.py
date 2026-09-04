"""Shared fixtures for investing tests."""

import os
import sys
import time

import pytest

# Add scripts/ to path so `from common.X import Y` works
SCRIPTS_DIR = os.path.join(os.path.dirname(__file__), "..", "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

# Add scripts/tools/ to path so tool modules can be imported directly
TOOLS_DIR = os.path.join(SCRIPTS_DIR, "tools")
if TOOLS_DIR not in sys.path:
    sys.path.insert(0, TOOLS_DIR)

# Add tests/ to path for the leading-underscore test *helper* modules that are
# not themselves collected (``_tree_write_guard``).
TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
if TESTS_DIR not in sys.path:
    sys.path.insert(0, TESTS_DIR)


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
    adapter, so they are unaffected. The DNS layer is handled separately by
    ``_deterministic_dns_resolution`` (SSRF guard resolution).
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

    # Tripwire for the isolation guard: lets it confirm the transport is blocked
    # without issuing a request (which, if the fixture were gone, would be a real
    # outbound call). Mirrors ``_ssrf_dns_stub`` below.
    _blocked._http_block_stub = True
    monkeypatch.setattr(HTTPAdapter, "send", _blocked)


# A globally-routable public IP. ``_is_non_public_ip`` returns False for it, so a
# hostname resolving here is treated as a public (allowed) SSRF target. The
# ``_ssrf_dns_stub`` marker below lets the isolation guard confirm the resolver
# is stubbed without depending on the runner's live DNS.
_PUBLIC_TEST_IP = "93.184.216.34"


@pytest.fixture(autouse=True)
def _deterministic_dns_resolution(monkeypatch):
    """Pin the SSRF guard's DNS resolution so it never depends on live network.

    ``common.utils.is_private_url_target`` resolves multi-label public hostnames
    via ``socket.getaddrinfo`` and *fails closed* — treating the URL as private
    and blocking it — when resolution fails. On a runner with no outbound DNS
    (offline local dev, a sandboxed CI job) a public test URL such as
    ``https://example.com/feed.rss`` is then blocked, so ``fetch_rss_feed`` /
    ``fetch_page_metadata`` return nothing and the collector/enrichment tests
    that drive them fail. When DNS *is* reachable the same tests pass. That
    network coupling is a latent flaky-green: the outcome depends on the
    runner's resolver, not the code under test.

    Pinning ``socket.getaddrinfo`` to a fixed public IP makes any hostname that
    reaches the DNS step resolve deterministically to a non-blocked address.
    Private targets (literal IPs, single-label names, ``.internal`` / rebind
    suffixes) are rejected *before* the DNS step, so they are unaffected. Tests
    that assert the DNS branch itself (``test_utils_ssrf``) install their own
    ``patch("socket.getaddrinfo", ...)`` inside the test body, which overrides
    this fixture for that scope and restores it on exit.

    Loopback and literal-IP lookups pass through to the real resolver: a test
    that connects to a local server (``127.0.0.1``, ``localhost``) must not have
    that address rewritten to an off-box public IP, which fails as an opaque
    ``Can't assign requested address``. Only name lookups — the ones the SSRF
    guard's DNS step actually performs — are pinned.

    The guard memoizes results in a module-level ``TTLCache``; clear it (on both
    the ``common.*`` and ``scripts.common.*`` module twins) so a value cached
    under a prior real/offline resolution cannot leak across tests.
    """
    import importlib
    import ipaddress
    import socket

    real_getaddrinfo = socket.getaddrinfo
    _LOCAL_HOSTNAMES = {"localhost", "localhost.localdomain", "ip6-localhost"}

    def _fake_getaddrinfo(host, port=None, *args, **kwargs):
        name = (host or "").strip().rstrip(".").lower()
        if name in _LOCAL_HOSTNAMES:
            return real_getaddrinfo(host, port, *args, **kwargs)
        try:
            ipaddress.ip_address(name)
        except ValueError:
            pass
        else:  # already a literal address — no name resolution to pin
            return real_getaddrinfo(host, port, *args, **kwargs)
        # Preserve the requested port so a caller that dials the returned
        # sockaddr reaches the port it asked for (service names -> 0).
        sock_port = port if isinstance(port, int) else 0
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (_PUBLIC_TEST_IP, sock_port))]

    _fake_getaddrinfo._ssrf_dns_stub = True  # tripwire for the isolation guard
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo)

    for mod_name in ("common.utils", "scripts.common.utils"):
        try:
            mod = importlib.import_module(mod_name)
        except ImportError:
            continue
        cache = getattr(mod, "_dns_cache", None)
        lock = getattr(mod, "_dns_cache_lock", None)
        if cache is not None and lock is not None:
            with lock:
                cache.clear()


@pytest.fixture(autouse=True)
def _isolate_generated_images(tmp_path, monkeypatch):
    """Redirect generated-image writes to a per-test tmp dir.

    Every image_generator save resolves its output directory through
    ``_base._get_pkg_attr("IMAGES_DIR")``, which reads the mutable package
    attribute ``common.image_generator.IMAGES_DIR``. Integration tests that
    exercise real render paths (daily summary, collectors, briefing cards)
    without patching that attribute would otherwise write PNG/WEBP/AVIF files
    into the committed ``assets/images/generated/`` tree, leaving dirty
    working-tree side effects after the suite runs. Pointing the package
    attribute at a throwaway directory keeps those writes hermetic.

    Tests that already patch ``IMAGES_DIR`` themselves (test_image_generator*)
    run their own ``monkeypatch.setattr`` after this fixture, which wins.
    """
    try:
        import common.image_generator as ig
    except ImportError:
        return

    dest = tmp_path / "generated"
    monkeypatch.setattr(ig, "IMAGES_DIR", str(dest))

    # Some tests import via ``scripts.common.*`` (a distinct module object).
    # ``_get_pkg_attr`` only reads ``common.image_generator``, but patch the
    # twin defensively so both namespaces agree on the redirect.
    try:
        import scripts.common.image_generator as ig_scripts

        if ig_scripts is not ig:
            monkeypatch.setattr(ig_scripts, "IMAGES_DIR", str(dest))
    except ImportError:
        pass


@pytest.fixture(autouse=True)
def _isolate_dedup_state(request, tmp_path, monkeypatch):
    """Redirect dedup ``_state/*.json`` writes to a per-test tmp dir.

    Every collector persists its cross-run dedup state through
    ``DedupEngine``, which resolves its output file at construction time as
    ``os.path.join(common.dedup.STATE_DIR, state_file)``. Integration tests
    that drive a real collector's ``save_state()`` path (base collector,
    collector integration, per-source collectors) without patching
    ``STATE_DIR`` themselves would otherwise write ``*_seen.json`` files into
    the committed ``_state/`` tree — the same dirty-working-tree side effect
    the image fixtures prevent, and one the ``pre-commit-state-guard`` hook
    would then block at commit time. Pointing the module attribute at a
    throwaway directory keeps those writes hermetic.

    Because ``DedupEngine.__init__`` reads the module global at call time,
    this autouse redirect covers collectors constructed inside the test body.
    Tests that patch ``STATE_DIR`` themselves (test_dedup, collector configs)
    set it after this fixture, so their value wins and is restored to this
    tmp on teardown before monkeypatch unwinds to the real path.

    Opt-out: tests marked ``no_state_isolation`` need the *real*
    repo-anchored value (e.g. the runtime path-anchoring guard in
    ``test_state_path_anchoring.py`` asserts ``STATE_DIR`` is under the repo
    root). This redirect would defeat that guard, so it skips such tests.

    Scope note: this covers the shared dedup ``_state`` family. The signal
    history ``_state`` file is redirected separately by
    ``_isolate_signal_history_state``.
    """
    if request.node.get_closest_marker("no_state_isolation"):
        return
    try:
        import common.dedup as dedup
    except ImportError:
        return

    dest = str(tmp_path / "_state")
    monkeypatch.setattr(dedup, "STATE_DIR", dest)

    # Some tests import via ``scripts.common.*`` (a distinct module object).
    # Patch the twin defensively so both namespaces agree on the redirect.
    try:
        import scripts.common.dedup as dedup_scripts

        if dedup_scripts is not dedup:
            monkeypatch.setattr(dedup_scripts, "STATE_DIR", dest)
    except ImportError:
        pass


@pytest.fixture(autouse=True)
def _isolate_signal_history_state(request, tmp_path, monkeypatch):
    """Redirect signal_tracker ``_state/signal_history.json`` writes to a tmp dir.

    ``SignalTracker`` persists the daily composite-signal history through a
    ``TimeSeriesStore`` bound to ``history_path``, which defaults to the module
    global ``common.signal_tracker._HISTORY_FILE`` resolved *at call time*
    (lazy sentinel). Integration tests that construct a no-arg
    ``SignalTracker()`` — as ``collect_market_indicators`` does in production —
    without passing an explicit ``history_path`` would otherwise write
    ``signal_history.json`` into the committed ``_state/`` tree. Pointing the
    module attribute at a throwaway file keeps those writes hermetic.

    Because the constructor reads ``_HISTORY_FILE`` at call time, this autouse
    redirect covers no-arg trackers built inside the test body. Tests that pass
    ``history_path=`` explicitly still win — their value is used verbatim.

    Opt-out: tests marked ``no_state_isolation`` (e.g. the runtime
    path-anchoring guard) need the real repo-anchored value, so this redirect
    skips them — consistent with ``_isolate_dedup_state``.
    """
    if request.node.get_closest_marker("no_state_isolation"):
        return
    try:
        import common.signal_tracker as st
    except ImportError:
        return

    dest = str(tmp_path / "_state" / "signal_history.json")
    monkeypatch.setattr(st, "_HISTORY_FILE", dest)

    # Some tests import via ``scripts.common.*`` (a distinct module object).
    # Patch the twin defensively so both namespaces agree on the redirect.
    try:
        import scripts.common.signal_tracker as st_scripts

        if st_scripts is not st:
            monkeypatch.setattr(st_scripts, "_HISTORY_FILE", dest)
    except ImportError:
        pass


@pytest.fixture(autouse=True)
def _isolate_translation_cache(request, tmp_path, monkeypatch):
    """Redirect translator ``_state/translation_cache.json`` writes to a tmp dir.

    ``_save_cache()`` / ``_load_cache()`` read the module global
    ``common.translator._CACHE_PATH`` *at call time* (no import-time default-arg
    binding), so a plain attribute redirect covers any code path that persists
    the cache. Integration tests that drive a real translation flow
    (``translate_batch`` → ``save_translation_cache``) without patching
    ``_CACHE_PATH`` themselves would otherwise write ``translation_cache.json``
    into the committed ``_state/`` tree — the dirty-working-tree side effect the
    dedup/signal fixtures also prevent. Pointing the module attribute at a
    throwaway file keeps those writes hermetic.

    The module memoizes the loaded cache in the ``_cache`` global (``_load_cache``
    returns early when it is not ``None``). Reset ``_cache``/``_cache_dirty`` too,
    or a cache loaded by an earlier test would leak forward and defeat the
    redirect (the early return skips re-reading the now-repointed path).

    Opt-out: tests marked ``no_state_isolation`` (e.g. the runtime
    path-anchoring guard, which asserts ``_CACHE_PATH`` is under the repo root)
    need the real repo-anchored value, so this redirect skips them — consistent
    with ``_isolate_dedup_state`` / ``_isolate_signal_history_state``.
    """
    if request.node.get_closest_marker("no_state_isolation"):
        return
    try:
        import common.translator as translator
    except ImportError:
        return

    dest = tmp_path / "_state" / "translation_cache.json"
    monkeypatch.setattr(translator, "_CACHE_PATH", dest)
    monkeypatch.setattr(translator, "_cache", None)
    monkeypatch.setattr(translator, "_cache_dirty", False)

    # Some tests import via ``scripts.common.*`` (a distinct module object).
    # Patch the twin defensively so both namespaces agree on the redirect.
    try:
        import scripts.common.translator as translator_scripts

        if translator_scripts is not translator:
            monkeypatch.setattr(translator_scripts, "_CACHE_PATH", dest)
            monkeypatch.setattr(translator_scripts, "_cache", None)
            monkeypatch.setattr(translator_scripts, "_cache_dirty", False)
    except ImportError:
        pass


@pytest.fixture(autouse=True)
def _reset_translator_breaker(monkeypatch):
    """Give every test a closed translation circuit breaker.

    ``common.translator`` keeps the breaker in module globals on purpose — it
    exists to stop a *process* from burning its workflow budget — so nothing
    resets it between tests. Give-ups accumulate across unrelated tests, and at
    five consecutive the breaker latches open for the rest of the session.

    That used to be invisible: the old breaker only dropped the retries, so a
    call still went out and could succeed. Now it skips the call entirely, so a
    leaked open breaker makes ``translate_to_korean`` return its input and any
    later test that expects a translation fails. Measured 2026-09-04: with no
    reset, ``test_translator.py::…::test_translation_result_cached`` failed in
    the full suite while passing alone, and a probe at that point read
    ``breaker_open=True consecutive=5``.

    ``_timeout_patched`` is left alone deliberately — the shim is installed on
    the real ``deep_translator.google`` module and is safe to keep across tests;
    the shim's own tests reset it themselves when they need to.

    The ``_breaker_reset_for_test`` marker exists because the reset values are
    also the module defaults, so a guard that only asserted "breaker closed"
    would pass with the fixture removed — the harness reported exactly that
    (VACUOUS). Mirrors the ``_http_block_stub`` / ``_ssrf_dns_stub`` /
    ``_no_real_sleep_stub`` tripwires: something the guard can observe that is
    true only while the fixture is active.
    """
    try:
        import common.translator as translator
    except ImportError:
        return

    for name, value in (
        ("_consecutive_failures", 0),
        ("_breaker_open", False),
        ("_failure_time_spent", 0.0),
        ("_failure_total", 0),
        ("_failure_warned", False),
        ("_failure_reported", 0),
        ("_breaker_reset_for_test", True),
    ):
        monkeypatch.setattr(translator, name, value, raising=False)


@pytest.fixture(autouse=True)
def _isolate_tvl_history_state(request, tmp_path, monkeypatch):
    """Redirect ``collect_defi_llama`` TVL-history writes to a per-test tmp file.

    ``build_post_content()`` calls ``_check_tvl_staleness()``, which appends to a
    ``TimeSeriesStore`` bound to the module global ``_TVL_HISTORY_PATH``. That
    write happens on the *content-building* path, so a test needs no collector,
    no network and no fixtures to trigger it — ``test_build_post_content_
    contains_key_sections`` takes no arguments at all and still rewrote the
    committed ``_state/defi_tvl_history.json`` on every run.

    Found by ``_detect_real_tree_writes`` below, not by any static guard: the
    path is correctly ``__file__``-anchored and the test imports no production
    root, so every source-shape check passes. Only watching the actual write
    surfaced it.

    Opt-out: ``no_state_isolation``, consistent with the other ``_state``
    redirects.
    """
    if request.node.get_closest_marker("no_state_isolation"):
        return
    try:
        import collect_defi_llama as defi
    except ImportError:
        return
    monkeypatch.setattr(defi, "_TVL_HISTORY_PATH", str(tmp_path / "_state" / "defi_tvl_history.json"))


@pytest.fixture(scope="session", autouse=True)
def _detect_real_tree_writes():
    """Fail the moment a test writes into the committed repo tree.

    The static guards check what tests *look* like; this checks what they *do*.
    See ``tests/_tree_write_guard.py`` for why interception beats a before/after
    snapshot (writes cleaned up in ``finally`` leave no diff) and for the stated
    blind spots.

    Session-scoped so the patch cost is paid once, not 4900 times. Attribution
    is unaffected: the exception is raised inside whichever test performs the
    write, so pytest reports that test and the traceback names the line.

    Two layers, because the first one structurally cannot see everything:

    1. *Interception* — patches the write entry points; blocks the write, names
       the test and the line. In-process only.
    2. *Session snapshot* — compares the content dirs against a baseline taken
       at session start. Catches what a subprocess or a raw-syscall C extension
       wrote, which layer 1 has no way to observe. Coarse attribution (the
       session, not the test) and ~165ms per walk × 2, so it is session-scoped
       only — per-test would add ~14 minutes to the suite.

    Remaining blind spot, stated: writes during interpreter shutdown land after
    this teardown. That vector is the ``atexit`` flush in
    ``image_rejection_metrics``, handled by the module-level redirect at the top
    of this file (and covered by its own harness case).
    """
    from _tree_write_guard import (
        TreeWriteGuard,
        Violation,
        assert_no_out_of_process_writes,
        capture_session_baseline,
    )

    def _fail(violation: Violation) -> None:
        raise AssertionError(
            f"테스트가 커밋된 레포 트리에 썼습니다: {violation}\n"
            "실제 트리 쓰기는 워킹 트리를 더럽히고, 파일시스템 상태에 의존하는 "
            "다른 테스트를 로컬 green / CI red 로 갈라놓습니다.\n"
            "해당 모듈의 경로 상수를 tmp 로 리다이렉트하세요 (conftest 의 "
            "_isolate_* fixture 패턴 참고).\n"
            "이 경로가 정말 써도 되는 산출물이면 _tree_write_guard._EXEMPT_PARTS / "
            "_EXEMPT_PREFIXES 에 근거와 함께 추가하세요."
        )

    baseline = capture_session_baseline()
    with TreeWriteGuard(_fail):
        yield
    assert_no_out_of_process_writes(baseline)


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


# ---------------------------------------------------------------------------
# Rate-limit / backoff sleeps
# ---------------------------------------------------------------------------

#: Real ``time.sleep``, captured before any fixture replaces it. Kept module-level
#: so helpers that genuinely need wall-clock delay can reach it after the autouse
#: fixture below is active.
REAL_SLEEP = time.sleep


#: Sleeps at or above this many seconds are treated as deliberate pacing and skipped;
#: anything shorter is passed through to the real ``time.sleep``.
#:
#: The floor is not cosmetic — a blanket no-op breaks third-party polling loops.
#: ``yfinance.multi._download_impl`` waits on its worker threads with
#: ``while ...: time.sleep(0.01)``. Skipping that turns a cooperative wait into a
#: spin: measured 2026-08-25 on ``test_dedup_idempotent_stock``, the loop went from
#: ~1.9s to ~15s (115k iterations become ~10M, starving the very threads it waits
#: for, and the recorder below balloons to ~800MB of entries).
#:
#: 0.25s separates the two populations cleanly. Every pacing delay in ``scripts/`` is
#: 0.3s-2s (``blockchain_api`` 0.3s, the collectors 1-2s); library poll intervals are
#: 0.01-0.05s.
SKIPPED_SLEEP_FLOOR_S = 0.25


class _SleepRecorder:
    """Stand-in for ``time.sleep`` that skips pacing delays and remembers them."""

    #: Tripwire for the isolation guard, mirroring ``_http_block_stub`` /
    #: ``_ssrf_dns_stub``: lets it confirm the stub is installed without having to
    #: actually sleep (which, if the fixture were gone, would be the very wall-clock
    #: cost this guard exists to prevent).
    _no_real_sleep_stub = True

    def __init__(self) -> None:
        self.calls: list[float] = []

    def __call__(self, seconds: float) -> None:
        if seconds < SKIPPED_SLEEP_FLOOR_S:
            REAL_SLEEP(seconds)
            return
        self.calls.append(seconds)

    @property
    def total(self) -> float:
        return sum(self.calls)


@pytest.fixture(autouse=True)
def sleep_calls(request, monkeypatch):
    """Skip rate-limit sleeps so they cost no wall-clock, and record what was skipped.

    Collectors pace their outbound requests with real sleeps — ``collect_social_media``
    waits 2s per Telegram channel and 1s per Twitter query, ``collect_coinmarketcap``
    1-2s per endpoint, ``generate_market_summary`` 1s per Alpha Vantage symbol. Under
    test every fetch is mocked, so those sleeps buy nothing and are pure wall-clock:
    2026-08-25 ``--durations=30`` put them at ~102s of a 184s suite (55%), with a
    single test (``test_dedup_idempotent_social``) at 48.6s.

    Sleeping is not what those tests assert. The retry/backoff *behaviour* is covered
    by call-count assertions that already patch sleep themselves
    (``test_utils.TestRequestWithRetry``, ``test_enrichment_utils`` — ``mock_sleep.call_count``,
    ``test_translator`` — batch delay count), and no test asserts elapsed time. So the
    delays are removable without losing coverage.

    Removing them silently *would* lose something: a backoff that starts computing
    absurd delays no longer shows up as a slow test. That is why this is a recorder
    and not a bare ``lambda``. Request ``sleep_calls`` to assert the sequence —
    ``test_utils.test_backoff_delays_are_exponential`` pins it for
    ``request_with_retry``.

    Only sleeps at or above ``SKIPPED_SLEEP_FLOOR_S`` are skipped — see that constant
    for why a blanket no-op is wrong. Opt out entirely with ``@pytest.mark.real_sleep``
    when a test needs wall-clock to pass, e.g. to make a file mtime measurably change
    (``test_generate_og_images_skip_branch``).
    """
    recorder = _SleepRecorder()
    if request.node.get_closest_marker("real_sleep") is None:
        monkeypatch.setattr(time, "sleep", recorder)
    return recorder
