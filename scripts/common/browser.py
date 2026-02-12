"""Playwright CDP browser session manager for web scraping.

Provides a reusable browser context for scraping JavaScript-rendered pages.
Falls back gracefully when Playwright is not installed — callers should use
``is_playwright_available()`` or wrap imports with try/except.
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def is_playwright_available() -> bool:
    """Return True if Playwright sync API is importable."""
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
        return True
    except ImportError:
        return False


class BrowserSession:
    """Playwright CDP browser context manager (sync API).

    Usage::

        with BrowserSession() as session:
            session.navigate("https://example.com")
            text = session.extract_text("h1")
    """

    def __init__(self, headless: bool = True, timeout: int = 30_000) -> None:
        self._headless = headless
        self._timeout = timeout
        self._pw: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._page: Any = None

    # -- context manager --------------------------------------------------

    def __enter__(self) -> "BrowserSession":
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(
            headless=self._headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        )
        self._context = self._browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
        )
        # Hide webdriver flag from detection scripts
        self._context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => false});"
        )
        self._context.set_default_timeout(self._timeout)
        self._page = self._context.new_page()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        try:
            if self._context:
                self._context.close()
            if self._browser:
                self._browser.close()
            if self._pw:
                self._pw.stop()
        except Exception as e:
            logger.debug("Browser cleanup error: %s", e)
        finally:
            self._page = None
            self._context = None
            self._browser = None
            self._pw = None

    # -- navigation --------------------------------------------------------

    def navigate(self, url: str, wait_until: str = "domcontentloaded",
                 wait_ms: int = 0) -> Any:
        """Navigate to *url* and return the Page object.

        *wait_ms* — additional milliseconds to wait after the page event
        (useful for JS-rendered content).
        """
        self._page.goto(url, wait_until=wait_until)
        if wait_ms > 0:
            self._page.wait_for_timeout(wait_ms)
        return self._page

    def wait_for(self, selector: str, timeout: int = 0) -> Any:
        """Wait for *selector* to appear in the DOM and return the element."""
        kwargs: Dict[str, Any] = {"state": "attached"}
        if timeout > 0:
            kwargs["timeout"] = timeout
        return self._page.wait_for_selector(selector, **kwargs)

    # -- extraction helpers ------------------------------------------------

    def extract_text(self, selector: str) -> str:
        """Return combined inner text of the first element matching *selector*."""
        el = self._page.query_selector(selector)
        return el.inner_text() if el else ""

    def extract_texts(self, selector: str) -> List[str]:
        """Return inner text of every element matching *selector*."""
        elements = self._page.query_selector_all(selector)
        return [el.inner_text() for el in elements]

    def extract_elements(self, selector: str) -> list:
        """Return all ElementHandle objects matching *selector*."""
        return self._page.query_selector_all(selector)

    def extract_attribute(self, selector: str, attribute: str) -> Optional[str]:
        """Return an attribute value from the first matching element."""
        el = self._page.query_selector(selector)
        return el.get_attribute(attribute) if el else None

    def extract_table(self, selector: str) -> List[Dict[str, str]]:
        """Extract an HTML table into a list of dicts (header → cell).

        *selector* should point to a ``<table>`` element.
        """
        table = self._page.query_selector(selector)
        if not table:
            return []

        headers: List[str] = []
        for th in table.query_selector_all("thead th, tr:first-child th"):
            headers.append(th.inner_text().strip())

        if not headers:
            # Fallback: use first row as headers
            first_row = table.query_selector("tr")
            if first_row:
                for td in first_row.query_selector_all("td, th"):
                    headers.append(td.inner_text().strip())

        rows: List[Dict[str, str]] = []
        for tr in table.query_selector_all("tbody tr, tr"):
            cells = tr.query_selector_all("td")
            if not cells or len(cells) != len(headers):
                continue
            row = {headers[i]: cells[i].inner_text().strip() for i in range(len(headers))}
            rows.append(row)

        return rows

    def wait_and_click(self, selector: str) -> None:
        """Wait for *selector* to become visible then click it."""
        self._page.wait_for_selector(selector, state="visible")
        self._page.click(selector)

    @property
    def page(self) -> Any:
        """Return the underlying Playwright Page (for advanced usage)."""
        return self._page


# -- module-level convenience --------------------------------------------------


def scrape_page(
    url: str,
    selectors: Dict[str, str],
    timeout: int = 30_000,
) -> Dict[str, Any]:
    """Quick single-page scrape.

    Parameters
    ----------
    url : str
        Page to load.
    selectors : dict
        Mapping of ``{key: css_selector}``.  Each selector's inner text is
        returned under the same key.
    timeout : int
        Navigation timeout in milliseconds.

    Returns
    -------
    dict
        ``{key: extracted_text, ...}`` plus ``"url"`` echoed back.
    """
    result: Dict[str, Any] = {"url": url}
    try:
        with BrowserSession(timeout=timeout) as session:
            session.navigate(url)
            for key, sel in selectors.items():
                texts = session.extract_texts(sel)
                result[key] = texts if len(texts) != 1 else texts[0]
    except Exception as e:
        logger.warning("scrape_page(%s) failed: %s", url, e)
        result["error"] = str(e)
    return result
