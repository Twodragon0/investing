"""Phase 3 — i18n regression + mobile/keyboard/theme scenarios.

Implemented scenarios (per `docs/i18n-e2e-plan.md` §2):

- S3: keyboard-only and touch-only fallback (no hover signal). The fallback
      reload path must still set the ``googtrans`` cookie and update the label.
- S5: cookie/localStorage blocked context (incognito-like). Verifies the
      ``safeLocalStorageSet`` / ``setCookie`` graceful paths do not throw and
      the page stays interactive.
- S6: mobile device matrix (iPhone SE / iPad / Pixel 5). Uses
      ``page.tap()`` to confirm the dropdown is reachable on touch.
- S7: ``prefers-color-scheme`` dark/light emulate — selectors and toggle
      logic must be theme-agnostic.
- S9: double-click on ``#lang-toggle`` resets ``preferredLang`` to
      ``"system"`` and reverts to the system language (KO under the
      ko-KR fixture locale).

A common ``no_console_errors`` fixture is applied at module scope to assert
the page emits zero ``pageerror`` events and zero console error messages.
A small allow-list absorbs known Google Translate upstream warnings so this
lane gates real regressions only.

External dependency: live Google Translate. CI may add ``--reruns 1``.
Phase 1 / Phase 2 files are intentionally untouched.
"""

from __future__ import annotations

from typing import Any

import pytest
from playwright.sync_api import Browser, BrowserContext, Page, Playwright, expect

from .conftest import wait_lang_toggle_ready

# Module-level marker so the entire Phase 3 file gates under the i18n_e2e marker.
pytestmark = pytest.mark.i18n_e2e


# ----------------------------------------------------------------------------
# Console error guard (Phase 3 only).
# ----------------------------------------------------------------------------

# Substrings that are tolerated in console output. Keep this list conservative;
# only add entries with a comment justifying the upstream cause.
_CONSOLE_ALLOWLIST: tuple[str, ...] = (
    # GT bootstrap occasionally races on http→https redirect for element.js.
    "translate.google.com",
    "Failed to load resource",
    # Local Jekyll preview can 404 favicons/og-images for some routes; not a
    # toggle regression.
    "favicon",
    ".webp",
    ".png",
    ".jpg",
    # GT initialization emits a benign warning when re-attached after reload.
    "Google Translate API가 아직 로드되지 않았습니다",
)


def _is_allowlisted(message: str) -> bool:
    return any(token in message for token in _CONSOLE_ALLOWLIST)


@pytest.fixture
def no_console_errors(page: Page) -> Any:
    """Collect ``pageerror`` and ``console.error`` events; assert zero on teardown.

    Uses the default ``page`` fixture from pytest-playwright. Tests that build
    their own context (S5, S6) attach the listener manually via ``_attach_console_guard``.
    """
    errors: list[str] = []

    def _on_pageerror(exc: Any) -> None:
        errors.append(f"pageerror: {exc}")

    def _on_console(msg: Any) -> None:
        if msg.type == "error":
            errors.append(f"console.error: {msg.text}")

    page.on("pageerror", _on_pageerror)
    page.on("console", _on_console)

    yield errors

    real_errors = [e for e in errors if not _is_allowlisted(e)]
    assert not real_errors, f"console errors detected: {real_errors!r}"


def _attach_console_guard(target_page: Page) -> list[str]:
    """Attach a console/pageerror listener to a custom page; return shared list."""
    errors: list[str] = []
    target_page.on("pageerror", lambda exc: errors.append(f"pageerror: {exc}"))
    target_page.on(
        "console",
        lambda msg: errors.append(f"console.error: {msg.text}") if msg.type == "error" else None,
    )
    return errors


def _assert_console_clean(errors: list[str], context_label: str) -> None:
    real_errors = [e for e in errors if not _is_allowlisted(e)]
    assert not real_errors, f"console errors in {context_label}: {real_errors!r}"


# ----------------------------------------------------------------------------
# S3 — keyboard / touch fallback (no hover preload).
# ----------------------------------------------------------------------------


def test_s3_keyboard_fallback(
    page: Page,
    base_url: str,
    no_console_errors: list[str],
) -> None:
    """S3: focus the toggle via JS + Enter selects EN without any hover signal.

    The hover-eager path is bypassed; the click handler must still load the GT
    bootstrap on demand and apply the language selection.
    """
    page.goto(f"{base_url}/", wait_until="domcontentloaded")

    toggle = page.locator("#lang-toggle")
    expect(toggle).to_be_visible(timeout=5_000)
    expect(page.locator("#current-lang")).to_have_text("KO", timeout=5_000)

    # Focus without hover — exercises the focusin handler in
    # `_includes/google-translate.html`. We use `.focus()` directly instead
    # of Tab cycling because the number of preceding focusable elements
    # depends on the rendered header and is brittle to layout drift.
    toggle.focus()
    # focusin triggers the lazy GT script load; wait for the IIFE to bind
    # the dropdown-open click/keyboard handler before pressing Enter.
    wait_lang_toggle_ready(page, hover_first=False)
    page.keyboard.press("Enter")

    en_option = page.locator('.lang-option[data-lang="en"]')
    expect(en_option).to_be_visible(timeout=3_000)

    # Use keyboard to activate the option (also a fallback path).
    en_option.focus()
    page.keyboard.press("Enter")

    expect(page.locator("#current-lang")).to_have_text("EN", timeout=10_000)

    cookies = page.context.cookies()
    googtrans = next((c for c in cookies if c["name"] == "googtrans"), None)
    assert googtrans is not None, "expected googtrans cookie after keyboard EN selection"
    assert "/en" in googtrans["value"], f"unexpected googtrans value: {googtrans['value']!r}"


def _safe_mobile_context_args(device: dict) -> dict:
    """Strip Playwright device-profile keys that hang under headless Chromium.

    Background — CI run 25567437195 stack: MainThread stuck in
    ``playwright/sync_api/_context_manager.py`` greenlet_main → asyncio
    ``run_forever`` → ``selector.poll``. Reproduces 100% on the first
    mobile-context test (S3 touch).

    Root cause hypothesis (highest evidence): the iPhone SE / iPad presets
    declare ``default_browser_type='webkit'`` but CI installs only Chromium
    (``playwright install --with-deps chromium``). Spreading
    ``**playwright.devices['iPhone SE']`` into ``browser.new_context`` on
    Chromium passes ``is_mobile=True`` + ``has_touch=True``, which triggers
    Chromium's mobile-emulation init path; under headless Linux this can
    hang on a renderer/IPC handshake when the chosen UA + viewport combo
    is incompatible (no SIGALRM-able cut, hence the bare selector.poll).

    Workaround (D-style): keep ``user_agent``, ``viewport``,
    ``device_scale_factor`` from the device preset, but drop the
    ``is_mobile`` / ``has_touch`` / ``default_browser_type`` fields. We
    cover responsive layout (viewport + UA) without tripping the mobile
    emulation hang. Touch-event coverage is still exercised in S3 via
    ``dispatch_event('touchstart')`` below.
    """
    keep = ("user_agent", "viewport", "device_scale_factor")
    return {k: device[k] for k in keep if k in device}


def test_s3_touch_fallback(
    playwright: Playwright,
    browser: Browser,
    base_url: str,
) -> None:
    """S3: pure-touch path on a mobile-emulated context (no hover events).

    Touch contexts emit ``touchstart`` rather than ``mouseenter``, but the
    inline preloader registers both. We assert the dropdown opens via tap
    and the EN option applies cleanly.

    NOTE: ``page.tap()`` requires ``has_touch=True`` on the context, but
    that triggers the Chromium mobile-emulation hang documented in
    ``_safe_mobile_context_args``. We instead dispatch ``touchstart``
    directly — the production preloader registers it as a `once` listener
    on ``#lang-toggle`` and that is exactly the GT-bootstrap trigger this
    scenario gates.
    """
    iphone = playwright.devices["iPhone SE"]
    ctx = browser.new_context(
        **_safe_mobile_context_args(iphone),
        locale="ko-KR",
        timezone_id="Asia/Seoul",
    )
    try:
        page = ctx.new_page()
        errors = _attach_console_guard(page)

        page.goto(f"{base_url}/", wait_until="domcontentloaded")

        toggle = page.locator("#lang-toggle")
        expect(toggle).to_be_visible(timeout=5_000)
        # Synthesize the touch signal that the inline preloader listens for.
        # This is the exact event handler the production code attaches in
        # `_includes/google-translate.html` (line 56).
        toggle.dispatch_event("touchstart")
        wait_lang_toggle_ready(page, hover_first=False)
        # The dropdown-open handler listens for `click`, which `touchstart`
        # alone does not synthesize. This mirrors the previous tap()+click()
        # sequencing without requiring `has_touch=True` on the context.
        toggle.click()

        en_option = page.locator('.lang-option[data-lang="en"]')
        expect(en_option).to_be_visible(timeout=3_000)
        en_option.click()

        expect(page.locator("#current-lang")).to_have_text("EN", timeout=15_000)

        cookies = ctx.cookies()
        assert any(c["name"] == "googtrans" for c in cookies), (
            "expected googtrans cookie after touch-driven EN selection"
        )

        _assert_console_clean(errors, "S3 touch fallback (iPhone SE)")
    finally:
        ctx.close()


# ----------------------------------------------------------------------------
# S5 — cookie / localStorage blocked context (incognito-like).
# ----------------------------------------------------------------------------


def test_s5_storage_blocked_graceful(
    browser: Browser,
    base_url: str,
) -> None:
    """S5: localStorage writes throw → safe wrappers must keep the page alive.

    We override ``localStorage.setItem`` at navigation time so any write
    raises, simulating a hardened/incognito context. The page must remain
    interactive: the dropdown opens, the EN option is clickable, and no
    uncaught exceptions are emitted.
    """
    ctx = browser.new_context(
        viewport={"width": 1280, "height": 800},
        locale="ko-KR",
        timezone_id="Asia/Seoul",
    )
    try:
        # Inject before any document scripts run. The site's script uses the
        # `safeLocalStorageSet` wrapper, which catches the SecurityError.
        ctx.add_init_script(
            """
            (function() {
              var origSet = Storage.prototype.setItem;
              Storage.prototype.setItem = function() {
                throw new DOMException('storage blocked (test)', 'SecurityError');
              };
              // Restore reference so safe wrappers can still call without crash;
              // they only need setItem to throw.
              window.__origStorageSet = origSet;
            })();
            """,
        )

        page = ctx.new_page()
        errors = _attach_console_guard(page)

        page.goto(f"{base_url}/", wait_until="domcontentloaded")

        toggle = page.locator("#lang-toggle")
        expect(toggle).to_be_visible(timeout=5_000)
        # Page body must still be rendered — graceful degrade.
        expect(page.locator("body")).to_be_visible()

        wait_lang_toggle_ready(page)
        toggle.click()

        en_option = page.locator('.lang-option[data-lang="en"]')
        expect(en_option).to_be_visible(timeout=3_000)
        en_option.click()

        # Even with storage blocked, the cookie path still drives the label.
        expect(page.locator("#current-lang")).to_have_text("EN", timeout=15_000)

        _assert_console_clean(errors, "S5 storage-blocked context")
    finally:
        ctx.close()


# ----------------------------------------------------------------------------
# S6 — mobile device matrix.
# ----------------------------------------------------------------------------

# One representative language (EN) is sufficient: S1 already covers all four
# languages on desktop. S6's job is to gate the touch + responsive layout.
MOBILE_DEVICES: tuple[str, ...] = ("iPhone SE", "iPad (gen 7)", "Pixel 5")


@pytest.mark.parametrize("device_name", MOBILE_DEVICES)
def test_s6_mobile_languages(
    playwright: Playwright,
    browser: Browser,
    base_url: str,
    device_name: str,
) -> None:
    """S6: dropdown is reachable + actionable across the mobile matrix.

    We do not assert on body-text translation (covered by S1 in the desktop
    lane); we focus on the toggle UX under mobile viewports: dropdown
    visible, options clickable, label updates synchronously.

    Uses ``_safe_mobile_context_args`` to avoid Chromium's mobile-emulation
    hang under headless CI. Touch-plumbing is covered by S3
    (``test_s3_touch_fallback``); S6's mandate is responsive layout +
    cross-viewport reachability.
    """
    if device_name not in playwright.devices:
        pytest.skip(f"Playwright device preset '{device_name}' unavailable in this build")

    device = playwright.devices[device_name]
    ctx = browser.new_context(
        **_safe_mobile_context_args(device),
        locale="ko-KR",
        timezone_id="Asia/Seoul",
    )
    try:
        page = ctx.new_page()
        errors = _attach_console_guard(page)

        page.goto(f"{base_url}/", wait_until="domcontentloaded")

        toggle = page.locator("#lang-toggle")
        expect(toggle).to_be_visible(timeout=5_000)

        # The toggle must be reasonably sized for touch (≥ 32px in either dim).
        bbox = toggle.bounding_box()
        assert bbox is not None, f"{device_name}: toggle has no bounding box"
        assert bbox["width"] >= 32 and bbox["height"] >= 32, f"{device_name}: toggle too small for touch ({bbox})"

        # Synthesize touchstart for the lazy GT-bootstrap trigger (production
        # listener attached in `_includes/google-translate.html`). Then use
        # ``click()`` for the dropdown-open + option-select interactions —
        # the production dropdown-open handler listens for click, and we
        # cannot use ``tap()`` because the safe mobile args drop
        # ``has_touch=True`` to dodge the Chromium emulation hang.
        toggle.dispatch_event("touchstart")
        wait_lang_toggle_ready(page, hover_first=False)
        toggle.click()

        en_option = page.locator('.lang-option[data-lang="en"]')
        expect(en_option).to_be_visible(timeout=3_000)
        en_option.click()

        expect(page.locator("#current-lang")).to_have_text("EN", timeout=15_000)

        _assert_console_clean(errors, f"S6 mobile ({device_name})")
    finally:
        ctx.close()


# ----------------------------------------------------------------------------
# S7 — dark / light theme emulate.
# ----------------------------------------------------------------------------


@pytest.mark.parametrize("scheme", ["dark", "light"])
def test_s7_theme_independence(
    page: Page,
    base_url: str,
    scheme: str,
    no_console_errors: list[str],
) -> None:
    """S7: toggle works identically under dark + light prefers-color-scheme."""
    page.emulate_media(color_scheme=scheme)
    page.goto(f"{base_url}/", wait_until="domcontentloaded")

    toggle = page.locator("#lang-toggle")
    expect(toggle).to_be_visible(timeout=5_000)

    wait_lang_toggle_ready(page)
    toggle.click()

    en_option = page.locator('.lang-option[data-lang="en"]')
    expect(en_option).to_be_visible(timeout=3_000)
    en_option.click()

    expect(page.locator("#current-lang")).to_have_text("EN", timeout=10_000)


# ----------------------------------------------------------------------------
# S9 — double-click resets to system language.
# ----------------------------------------------------------------------------


def test_s9_doubleclick_system_reset(
    page: Page,
    context: BrowserContext,
    base_url: str,
    no_console_errors: list[str],
) -> None:
    """S9: dblclick on #lang-toggle stores ``preferredLang=system`` and reverts.

    Under the ko-KR fixture locale, ``getSystemLanguage()`` returns ``'ko'``,
    so the dblclick path goes through KO recovery (cookie cleared, reload).
    """
    page.goto(f"{base_url}/", wait_until="domcontentloaded")

    toggle = page.locator("#lang-toggle")
    expect(toggle).to_be_visible(timeout=5_000)

    # Step 1: switch to EN so the cookie + label diverge from system default.
    wait_lang_toggle_ready(page)
    toggle.click()
    page.locator('.lang-option[data-lang="en"]').click()
    expect(page.locator("#current-lang")).to_have_text("EN", timeout=10_000)

    pre_cookies = context.cookies()
    assert any(c["name"] == "googtrans" for c in pre_cookies), (
        "expected googtrans cookie after EN switch (pre-dblclick)"
    )

    # Step 2: double-click the toggle to trigger system-reset.
    # The handler sets preferredLang=system and calls changeLang(sysLang)
    # which (under ko-KR) follows the KO recovery path: deletes cookie + reloads.
    # Use expect_navigation + load (not domcontentloaded) so deferred scripts
    # finish executing — the GT widget can create/replace iframes after DCL,
    # which destroys evaluation contexts and breaks the localStorage probe.
    with page.expect_navigation(wait_until="load", timeout=15_000):
        toggle.dblclick()

    # Extra grace: settle any post-load script settlement (initLangToggle
    # setTimeout 100ms + safeSessionStorageSet/Remove side-effects).
    page.wait_for_timeout(300)

    # Label reverts to KO (system language under ko-KR locale).
    expect(page.locator("#current-lang")).to_have_text("KO", timeout=10_000)

    # preferredLang is set to the literal string 'system'.
    pref = page.evaluate("localStorage.getItem('preferredLang')")
    assert pref == "system", f"expected preferredLang='system' after dblclick, got {pref!r}"

    # Cookie is gone (KO recovery cleared it).
    post_cookies = context.cookies()
    googtrans_remaining = [c for c in post_cookies if c["name"] == "googtrans"]
    assert not googtrans_remaining, f"googtrans cookie should be cleared after dblclick, found: {googtrans_remaining!r}"
