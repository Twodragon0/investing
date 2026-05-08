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
