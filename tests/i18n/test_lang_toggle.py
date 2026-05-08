"""Phase 2 — i18n language toggle E2E scenarios.

Implemented scenarios (per `docs/i18n-e2e-plan.md`):

- S1: hover -> click in-place transition, parametrized over EN/JA/zh-CN/ES.
- S2: race condition between hover preload and immediate click — verifies
      the GT element script is injected exactly once (no duplicate inject).
- S4: Korean recovery from a non-KO state — verifies the googtrans cookie
      is cleared and the toggle label reverts to "KO".
- S8: localStorage `preferredLang` is honoured on a fresh page load,
      auto-applying the saved language without any user click.

External dependency: these tests load the live Google Translate widget. CI
runs with `--reruns 1` (when configured) to absorb upstream GT flakiness.
Phase 3 expands to keyboard/touch fallback, mobile devices, and theme
emulation.
"""

from __future__ import annotations

import re
from typing import Any

import pytest
from playwright.sync_api import BrowserContext, Page, expect

# (data-lang, expected #current-lang label) — matches LANG_MAP in
# `assets/js/google-translate.js`. Keep this list in sync with the
# parametrized scenarios in `docs/i18n-e2e-plan.md` §2.
LANG_MATRIX = [
    ("en", "EN"),
    ("ja", "JA"),
    ("zh-CN", "CN"),
    ("es", "ES"),
]


@pytest.mark.i18n_e2e
@pytest.mark.parametrize(("lang_code", "lang_label"), LANG_MATRIX)
def test_s1_hover_click_in_place(
    page: Page,
    base_url: str,
    lang_strings: dict,
    lang_code: str,
    lang_label: str,
) -> None:
    """S1: hover preload + click selects the language in-place (no full reload).

    Phase 2 keeps the in-place tolerance at ``<= 1`` extra navigation to absorb
    a single GT-fallback reload. Phase 3 will tighten to ``== 0`` once the
    flake rate is measured.
    """
    nav_count = {"value": 0}

    def _on_frame_navigated(frame) -> None:
        if frame == page.main_frame:
            nav_count["value"] += 1

    page.on("framenavigated", _on_frame_navigated)

    page.goto(f"{base_url}/", wait_until="domcontentloaded")
    initial_nav = nav_count["value"]

    toggle = page.locator("#lang-toggle")
    expect(toggle).to_be_visible(timeout=5_000)
    expect(page.locator("#current-lang")).to_have_text("KO", timeout=5_000)

    # Hover preloads the GT SDK script tag (via __preloadGoogleTranslate).
    toggle.hover()
    page.wait_for_selector(
        'script[src*="translate_a/element.js"]',
        timeout=5_000,
        state="attached",
    )

    # Open the dropdown and click the requested language option.
    toggle.click()
    option = page.locator(f'.lang-option[data-lang="{lang_code}"]')
    expect(option).to_be_visible(timeout=2_000)
    option.click()

    # Button label updates synchronously in JS before any reload path.
    expect(page.locator("#current-lang")).to_have_text(lang_label, timeout=10_000)

    # The googtrans cookie should now point at /ko/{lang_code}.
    cookies = page.context.cookies()
    googtrans = next((c for c in cookies if c["name"] == "googtrans"), None)
    assert googtrans is not None, f"expected googtrans cookie to be set after {lang_label} click"
    assert f"/{lang_code}" in googtrans["value"], f"unexpected googtrans value for {lang_code}: {googtrans['value']!r}"

    # In-place path tolerates at most one extra navigation (single GT fallback
    # reload). Phase 3 tightens this to == 0 once flake rate is measured.
    extra_navs = nav_count["value"] - initial_nav
    assert extra_navs <= 1, f"too many navigations after {lang_label} click: {extra_navs}"

    # Body-text translation is best-effort. We assert the expected language
    # string eventually appears somewhere in the body, with a generous timeout
    # and a soft skip on GT-side delays so this lane stays a smoke check.
    expected = lang_strings[lang_code]["nav_reports"]
    pattern = re.compile(expected, re.IGNORECASE)
    try:
        expect(page.locator("body")).to_contain_text(pattern, timeout=15_000)
    except AssertionError:
        pytest.skip(
            f"Google Translate body-text did not update to {lang_code} within "
            "timeout; treated as a soft skip. Inspect the trace artifact."
        )


@pytest.mark.i18n_e2e
def test_s2_race_condition_single_script(page: Page, base_url: str) -> None:
    """S2: hover then click within ~50ms — element.js must be fetched only once.

    The hover handler and the lazy click handler both call ``loadTranslate``;
    the once-flag must dedupe so we only see a single GT element bootstrap
    fetch. Counting network requests is more robust than counting DOM script
    elements, because Google Translate may detach/replace the bootstrap
    script after initialization (timing-dependent DOM count is flaky).
    """
    element_js_requests: list[str] = []

    def _on_request(request: Any) -> None:
        # Filter out redirect targets — when the page is served over HTTP locally,
        # the protocol-relative `//translate.google.com/...` resolves to HTTP and
        # Google issues a 301 to HTTPS, producing a second request event for the
        # same logical fetch. Only count the initial inject.
        if "translate_a/element.js" in request.url and request.redirected_from is None:
            element_js_requests.append(request.url)

    page.on("request", _on_request)

    page.goto(f"{base_url}/", wait_until="domcontentloaded")

    toggle = page.locator("#lang-toggle")
    expect(toggle).to_be_visible(timeout=5_000)

    # Hover triggers the eager preload; click within ~50ms exercises the
    # race window between the hover-loaded script and the click-fallback path.
    toggle.hover()
    toggle.click(delay=50)

    en_option = page.locator('.lang-option[data-lang="en"]')
    expect(en_option).to_be_visible(timeout=2_000)
    en_option.click()

    # Wait until the toggle label reflects EN — guarantees GT chain attached.
    expect(page.locator("#current-lang")).to_have_text("EN", timeout=10_000)

    # Critical invariant: bootstrap script is fetched exactly once even when
    # hover + click race; the existingScript guard in loadTranslateScript
    # must dedupe duplicate inject attempts.
    assert len(element_js_requests) == 1, (
        f"expected 1 GT element.js fetch under race, got {len(element_js_requests)}: {element_js_requests}"
    )


@pytest.mark.i18n_e2e
def test_s4_korean_recovery_clears_cookie(
    page: Page,
    context: BrowserContext,
    base_url: str,
) -> None:
    """S4: switching back to KO clears the googtrans cookie and resets the label.

    Korean is the page's source language, so recovery deletes the cookie
    rather than setting ``/ko/ko``. This guards the deleteCookie() path in
    `assets/js/google-translate.js`.
    """
    page.goto(f"{base_url}/", wait_until="domcontentloaded")

    toggle = page.locator("#lang-toggle")
    expect(toggle).to_be_visible(timeout=5_000)

    # Step 1: switch to EN so the cookie is set.
    toggle.hover()
    page.wait_for_selector(
        'script[src*="translate_a/element.js"]',
        timeout=5_000,
        state="attached",
    )
    toggle.click()
    page.locator('.lang-option[data-lang="en"]').click()
    expect(page.locator("#current-lang")).to_have_text("EN", timeout=10_000)

    pre_cookies = context.cookies()
    assert any(c["name"] == "googtrans" for c in pre_cookies), "expected googtrans cookie to exist after EN switch"

    # Step 2: open the toggle again and click KO. This triggers the recovery
    # path, which deletes the cookie and reloads the page.
    toggle.click()
    page.locator('.lang-option[data-lang="ko"]').click()

    # The KO recovery path issues a clean reload after ~80ms; wait for it.
    page.wait_for_load_state("networkidle")

    # After reload the label must show KO and the googtrans cookie must be gone.
    expect(page.locator("#current-lang")).to_have_text("KO", timeout=10_000)

    post_cookies = context.cookies()
    googtrans_remaining = [c for c in post_cookies if c["name"] == "googtrans"]
    assert not googtrans_remaining, (
        f"googtrans cookie should be cleared after KO recovery, found: {googtrans_remaining!r}"
    )


@pytest.mark.i18n_e2e
def test_s8_local_storage_auto_apply(page: Page, base_url: str) -> None:
    """S8: a stored ``preferredLang`` auto-applies on page load (no user click).

    The script's ``applySystemLanguage()`` path reads localStorage and calls
    ``changeLang()`` automatically when the preference differs from the
    current cookie/state. We seed the preference, reload, and assert the
    toggle label reflects the saved choice without any user interaction.
    """
    # First navigation is required so the localStorage key resolves to the
    # site's origin. ``page.evaluate`` before any goto can fail on about:blank.
    page.goto(f"{base_url}/", wait_until="domcontentloaded")
    page.evaluate("localStorage.setItem('preferredLang', 'en')")

    # Reload so the bootstrap path observes the seeded preference.
    page.reload(wait_until="domcontentloaded")

    # Auto-apply is async (it waits for the GT script to load and dispatch
    # a change event, then may reload). Allow a generous timeout.
    expect(page.locator("#current-lang")).to_have_text("EN", timeout=15_000)
