"""Pytest fixtures for i18n Playwright E2E tests.

The Jekyll preview server is expected to be started by the surrounding
environment (CI workflow step or local `bundle exec jekyll serve`). This
conftest only performs a non-blocking health check so failures surface as a
clear ``pytest.skip`` instead of an opaque Playwright timeout.

Override the target URL with ``I18N_E2E_BASE_URL`` (e.g. ``http://127.0.0.1:4000``).

The health-check logic itself lives in ``tests/_i18n_healthcheck.py`` so it can be
unit-tested — a conftest is not importable by name, which is why the 30s wait loop
had never been covered. See that module for why "nothing is listening" and
"listening but not ready" must be told apart.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from _i18n_healthcheck import (
    FAST_FAIL_GRACE_S,
    HEALTHCHECK_INTERVAL_S,
    HEALTHCHECK_TIMEOUT_S,
    resolve_base_url,
    should_fail_hard,
    unreachable_message,
    wait_for_server,
)

# The root conftest's autouse ``sleep_calls`` fixture swaps ``time.sleep`` for a
# recorder that skips any delay >= 0.25s — and ``HEALTHCHECK_INTERVAL_S`` is 0.5.
# Without a real sleep the poll below would spin the CPU instead of waiting
# between attempts, so bind the real function at import, before any fixture can
# replace it.
_REAL_SLEEP = time.sleep

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def base_url() -> str:
    """Resolve the Jekyll preview base URL and verify the server is reachable."""
    url = resolve_base_url()
    probe = wait_for_server(
        url,
        HEALTHCHECK_TIMEOUT_S,
        FAST_FAIL_GRACE_S,
        interval_s=HEALTHCHECK_INTERVAL_S,
        sleep=_REAL_SLEEP,
    )
    if probe.ok:
        return url

    message = unreachable_message(url, probe)
    if should_fail_hard():
        # CI 에서 서버가 사라지면 skip 이 아니라 red 여야 한다 — 그러지 않으면 e2e 가
        # "16 skipped" 로 조용히 통과한다.
        pytest.fail(message)
    pytest.skip(message)


@pytest.fixture(scope="session")
def lang_strings() -> dict:
    """Load the per-language stable text fixture used by S1 assertions."""
    path = FIXTURES_DIR / "lang_strings.json"
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args: dict) -> dict:
    """Override pytest-playwright defaults: fix viewport + locale for stability."""
    return {
        **browser_context_args,
        "viewport": {"width": 1280, "height": 800},
        "locale": "ko-KR",
        "timezone_id": "Asia/Seoul",
    }


def wait_lang_toggle_ready(page, hover_first: bool = True, timeout_ms: int = 5_000) -> None:
    """Ensure ``google-translate.js`` has loaded and ``initLangToggle`` has bound.

    The site lazy-loads ``assets/js/google-translate.js`` on the first
    ``mouseenter``/``focusin``/``touchstart``/``click`` of ``#lang-toggle``.
    Without this wait, Playwright's first ``click`` can fire before the
    dropdown-open click handler is attached (the IIFE schedules
    ``initLangToggle`` via ``setTimeout(..., 100)``), so the dropdown
    silently fails to open and ``.lang-option`` stays hidden.

    Most callers should ``hover_first=True``: hover triggers the script
    fetch without consuming the click. For keyboard-only flows pass
    ``hover_first=False`` and call ``page.focus("#lang-toggle")`` before this
    helper — focusin also triggers the lazy load.
    """
    if hover_first:
        page.hover("#lang-toggle")
    # Wait for the IIFE to expose its preload trigger; that proves the
    # script has executed and the click handler binding is imminent.
    page.wait_for_function(
        "typeof window.__preloadGoogleTranslate === 'function'",
        timeout=timeout_ms,
    )
    # Cover the IIFE's setTimeout(initLangToggle, 100) grace.
    page.wait_for_timeout(150)
