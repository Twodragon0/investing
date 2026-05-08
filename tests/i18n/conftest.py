"""Pytest fixtures for i18n Playwright E2E tests.

The Jekyll preview server is expected to be started by the surrounding
environment (CI workflow step or local `bundle exec jekyll serve`). This
conftest only performs a non-blocking health check so failures surface as a
clear ``pytest.skip`` instead of an opaque Playwright timeout.

Override the target URL with ``I18N_E2E_BASE_URL`` (e.g. ``http://127.0.0.1:4000``).
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

DEFAULT_BASE_URL = "http://127.0.0.1:4000"
HEALTHCHECK_TIMEOUT_S = float(os.environ.get("I18N_E2E_HEALTHCHECK_TIMEOUT", "30"))
HEALTHCHECK_INTERVAL_S = 0.5

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _resolve_base_url() -> str:
    return os.environ.get("I18N_E2E_BASE_URL", DEFAULT_BASE_URL).rstrip("/")


def _wait_for_server(url: str, timeout_s: float) -> bool:
    """Poll the homepage until it returns any response or timeout elapses."""
    deadline = time.monotonic() + timeout_s
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url + "/", timeout=2) as resp:  # noqa: S310
                if 200 <= resp.status < 500:
                    return True
        except (urllib.error.URLError, ConnectionError, TimeoutError) as exc:
            last_error = exc
        time.sleep(HEALTHCHECK_INTERVAL_S)
    if last_error is not None:
        print(f"[i18n-e2e] healthcheck failed for {url}: {last_error}")  # noqa: T201
    return False


@pytest.fixture(scope="session")
def base_url() -> str:
    """Resolve the Jekyll preview base URL and verify the server is reachable."""
    url = _resolve_base_url()
    if not _wait_for_server(url, HEALTHCHECK_TIMEOUT_S):
        pytest.skip(
            f"Jekyll preview at {url} is unreachable; "
            "start `bundle exec jekyll serve --port 4000` or set I18N_E2E_BASE_URL."
        )
    return url


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
