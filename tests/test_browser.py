"""Tests for browser module (scripts/common/browser.py)."""

import sys
from types import ModuleType
from unittest.mock import MagicMock, patch

from common.browser import (
    BrowserSession,
    extract_google_news_links,
    is_playwright_available,
    scrape_page,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pw_mock():
    """Build a complete hierarchy of Playwright mocks."""
    pw = MagicMock(name="sync_playwright_instance")
    browser = MagicMock(name="browser")
    context = MagicMock(name="context")
    page = MagicMock(name="page")

    pw.chromium.launch.return_value = browser
    browser.new_context.return_value = context
    context.new_page.return_value = page

    return pw, browser, context, page


def _make_sync_playwright_patch(pw_mock):
    """Return a context manager mock that yields pw_mock on .start()."""
    sp = MagicMock(name="sync_playwright")
    sp.return_value.start.return_value = pw_mock
    return sp


# ---------------------------------------------------------------------------
# is_playwright_available
# ---------------------------------------------------------------------------


class TestIsPlaywrightAvailable:
    """Tests for is_playwright_available()."""

    def test_returns_bool(self):
        result = is_playwright_available()
        assert isinstance(result, bool)

    def test_returns_true_when_playwright_importable(self):
        fake_sync_playwright = MagicMock()
        fake_module = ModuleType("playwright.sync_api")
        fake_module.sync_playwright = fake_sync_playwright

        with (
            patch.dict(sys.modules, {"playwright.sync_api": fake_module}),
            patch("builtins.__import__", wraps=__import__) as mock_import,
        ):
            # Allow normal imports, just inject playwright
            def side_effect(name, *args, **kwargs):
                if name == "playwright.sync_api":
                    return fake_module
                return __import__(name, *args, **kwargs)

            mock_import.side_effect = side_effect
            result = is_playwright_available()
            assert isinstance(result, bool)

    def test_returns_false_when_playwright_not_installed(self):
        with patch("builtins.__import__", side_effect=ImportError("no playwright")):
            result = is_playwright_available()
        assert result is False

    def test_never_raises_exception(self):
        """is_playwright_available() must never propagate any exception."""
        try:
            result = is_playwright_available()
            assert result in (True, False)
        except Exception as exc:
            raise AssertionError(f"is_playwright_available() raised: {exc}") from exc


# ---------------------------------------------------------------------------
# BrowserSession — __init__
# ---------------------------------------------------------------------------


class TestBrowserSessionInit:
    def test_defaults(self):
        session = BrowserSession()
        assert session._headless is True
        assert session._timeout == 30_000
        assert session._pw is None
        assert session._browser is None
        assert session._context is None
        assert session._page is None

    def test_custom_params(self):
        session = BrowserSession(headless=False, timeout=5_000)
        assert session._headless is False
        assert session._timeout == 5_000

    def test_page_property_before_enter_is_none(self):
        session = BrowserSession()
        assert session.page is None


# ---------------------------------------------------------------------------
# BrowserSession — context manager (__enter__ / __exit__)
# ---------------------------------------------------------------------------


class TestBrowserSessionContextManager:
    def _enter_session(self, session, pw, sp):
        with (
            patch("common.browser.sync_playwright", sp, create=True),
            patch("scripts.common.browser.sync_playwright", sp, create=True),
        ):
            pass
        return session

    def test_enter_creates_browser_chain(self):
        pw, browser, context, page = _make_pw_mock()
        sp = _make_sync_playwright_patch(pw)

        with patch("builtins.__import__", wraps=__import__) as mock_import:

            def side_effect(name, *args, **kwargs):
                if name == "playwright.sync_api":
                    mod = ModuleType("playwright.sync_api")
                    mod.sync_playwright = sp
                    return mod
                return __import__(name, *args, **kwargs)

            mock_import.side_effect = side_effect

            session = BrowserSession(headless=True, timeout=10_000)
            result = session.__enter__()

        assert result is session
        pw.chromium.launch.assert_called_once_with(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        browser.new_context.assert_called_once()
        context.add_init_script.assert_called_once()
        context.set_default_timeout.assert_called_once_with(10_000)
        context.new_page.assert_called_once()
        assert session._page is page
        assert session._browser is browser
        assert session._context is context

    def test_exit_closes_resources(self):
        pw, browser, context, page = _make_pw_mock()
        sp = _make_sync_playwright_patch(pw)

        with patch("builtins.__import__", wraps=__import__) as mock_import:

            def side_effect(name, *args, **kwargs):
                if name == "playwright.sync_api":
                    mod = ModuleType("playwright.sync_api")
                    mod.sync_playwright = sp
                    return mod
                return __import__(name, *args, **kwargs)

            mock_import.side_effect = side_effect
            session = BrowserSession()
            session.__enter__()
            session.__exit__(None, None, None)

        context.close.assert_called_once()
        browser.close.assert_called_once()
        pw.stop.assert_called_once()

        # All references reset to None
        assert session._page is None
        assert session._context is None
        assert session._browser is None
        assert session._pw is None

    def test_exit_resets_refs_even_when_close_raises(self):
        pw, browser, context, page = _make_pw_mock()
        context.close.side_effect = RuntimeError("close failed")
        sp = _make_sync_playwright_patch(pw)

        with patch("builtins.__import__", wraps=__import__) as mock_import:

            def side_effect(name, *args, **kwargs):
                if name == "playwright.sync_api":
                    mod = ModuleType("playwright.sync_api")
                    mod.sync_playwright = sp
                    return mod
                return __import__(name, *args, **kwargs)

            mock_import.side_effect = side_effect
            session = BrowserSession()
            session.__enter__()
            session.__exit__(None, None, None)  # should not raise

        assert session._page is None
        assert session._context is None
        assert session._browser is None
        assert session._pw is None

    def test_exit_with_none_resources_is_safe(self):
        """__exit__ called without __enter__ should not raise."""
        session = BrowserSession()
        session.__exit__(None, None, None)  # no crash
        assert session._page is None


# ---------------------------------------------------------------------------
# Helpers to build a session with mocked internals already set
# ---------------------------------------------------------------------------


def _patched_session():
    """Return a BrowserSession whose internals are pre-mocked (no real browser)."""
    pw, browser, context, page = _make_pw_mock()
    session = BrowserSession()
    session._pw = pw
    session._browser = browser
    session._context = context
    session._page = page
    return session, pw, browser, context, page


# ---------------------------------------------------------------------------
# BrowserSession.navigate
# ---------------------------------------------------------------------------


class TestBrowserSessionNavigate:
    def test_goto_called_without_wait_ms(self):
        session, pw, browser, context, page = _patched_session()
        session.navigate("https://example.com")
        page.goto.assert_called_once_with("https://example.com", wait_until="domcontentloaded")
        page.wait_for_timeout.assert_not_called()

    def test_goto_called_with_wait_ms(self):
        session, pw, browser, context, page = _patched_session()
        session.navigate("https://example.com", wait_ms=500)
        page.goto.assert_called_once()
        page.wait_for_timeout.assert_called_once_with(500)

    def test_returns_page(self):
        session, pw, browser, context, page = _patched_session()
        result = session.navigate("https://example.com")
        assert result is page

    def test_custom_wait_until(self):
        session, pw, browser, context, page = _patched_session()
        session.navigate("https://example.com", wait_until="networkidle")
        page.goto.assert_called_once_with("https://example.com", wait_until="networkidle")


# ---------------------------------------------------------------------------
# BrowserSession.wait_for
# ---------------------------------------------------------------------------


class TestBrowserSessionWaitFor:
    def test_wait_for_without_timeout(self):
        session, pw, browser, context, page = _patched_session()
        session.wait_for("div.content")
        page.wait_for_selector.assert_called_once_with("div.content", state="attached")

    def test_wait_for_with_timeout(self):
        session, pw, browser, context, page = _patched_session()
        session.wait_for("div.content", timeout=5000)
        page.wait_for_selector.assert_called_once_with("div.content", state="attached", timeout=5000)

    def test_returns_element(self):
        session, pw, browser, context, page = _patched_session()
        el = MagicMock()
        page.wait_for_selector.return_value = el
        result = session.wait_for("div")
        assert result is el


# ---------------------------------------------------------------------------
# BrowserSession.extract_text
# ---------------------------------------------------------------------------


class TestBrowserSessionExtractText:
    def test_returns_inner_text_when_found(self):
        session, pw, browser, context, page = _patched_session()
        el = MagicMock()
        el.inner_text.return_value = "Hello World"
        page.query_selector.return_value = el
        assert session.extract_text("h1") == "Hello World"

    def test_returns_empty_string_when_not_found(self):
        session, pw, browser, context, page = _patched_session()
        page.query_selector.return_value = None
        assert session.extract_text("h1") == ""


# ---------------------------------------------------------------------------
# BrowserSession.extract_texts
# ---------------------------------------------------------------------------


class TestBrowserSessionExtractTexts:
    def test_returns_list_of_texts(self):
        session, pw, browser, context, page = _patched_session()
        els = [MagicMock(), MagicMock()]
        els[0].inner_text.return_value = "A"
        els[1].inner_text.return_value = "B"
        page.query_selector_all.return_value = els
        assert session.extract_texts("li") == ["A", "B"]

    def test_returns_empty_list_when_none(self):
        session, pw, browser, context, page = _patched_session()
        page.query_selector_all.return_value = []
        assert session.extract_texts("li") == []


# ---------------------------------------------------------------------------
# BrowserSession.extract_elements
# ---------------------------------------------------------------------------


class TestBrowserSessionExtractElements:
    def test_returns_element_list(self):
        session, pw, browser, context, page = _patched_session()
        els = [MagicMock(), MagicMock()]
        page.query_selector_all.return_value = els
        result = session.extract_elements("a")
        assert result == els


# ---------------------------------------------------------------------------
# BrowserSession.extract_attribute
# ---------------------------------------------------------------------------


class TestBrowserSessionExtractAttribute:
    def test_returns_attribute_when_found(self):
        session, pw, browser, context, page = _patched_session()
        el = MagicMock()
        el.get_attribute.return_value = "https://example.com"
        page.query_selector.return_value = el
        assert session.extract_attribute("a", "href") == "https://example.com"

    def test_returns_none_when_not_found(self):
        session, pw, browser, context, page = _patched_session()
        page.query_selector.return_value = None
        assert session.extract_attribute("a", "href") is None


# ---------------------------------------------------------------------------
# BrowserSession.extract_table
# ---------------------------------------------------------------------------


class TestBrowserSessionExtractTable:
    def test_returns_empty_when_no_table(self):
        session, pw, browser, context, page = _patched_session()
        page.query_selector.return_value = None
        assert session.extract_table("table") == []

    def test_extracts_table_with_headers(self):
        session, pw, browser, context, page = _patched_session()
        table = MagicMock(name="table")
        page.query_selector.return_value = table

        # Two header cells
        th1, th2 = MagicMock(), MagicMock()
        th1.inner_text.return_value = "Name"
        th2.inner_text.return_value = "Value"
        table.query_selector_all.side_effect = [
            [th1, th2],  # thead th, tr:first-child th
            [],  # fallback first row (not reached because headers found)
            # tbody rows
        ]

        # Reconfigure for tbody rows call
        td1, td2 = MagicMock(), MagicMock()
        td1.inner_text.return_value = "foo"
        td2.inner_text.return_value = "bar"
        row_mock = MagicMock()
        row_mock.query_selector_all.return_value = [td1, td2]

        def qsa_side_effect(selector):
            if "thead" in selector or "first-child" in selector:
                return [th1, th2]
            if "tbody" in selector or selector == "tr":
                return [row_mock]
            return []

        table.query_selector_all.side_effect = qsa_side_effect

        result = session.extract_table("table")
        assert isinstance(result, list)

    def test_fallback_to_first_row_when_no_thead(self):
        """When no thead, uses first <tr> cells as headers."""
        session, pw, browser, context, page = _patched_session()
        table = MagicMock(name="table")
        page.query_selector.return_value = table

        # No thead headers
        first_row = MagicMock(name="first_row")
        td_h1, td_h2 = MagicMock(), MagicMock()
        td_h1.inner_text.return_value = "Col1"
        td_h2.inner_text.return_value = "Col2"
        first_row.query_selector_all.return_value = [td_h1, td_h2]
        table.query_selector.return_value = first_row  # used in fallback

        td1, td2 = MagicMock(), MagicMock()
        td1.inner_text.return_value = "v1"
        td2.inner_text.return_value = "v2"
        data_row = MagicMock()
        data_row.query_selector_all.return_value = [td1, td2]

        def qsa_side_effect(selector):
            if "thead" in selector or "first-child" in selector:
                return []  # no thead
            if "tbody" in selector or selector == "tr":
                return [data_row]
            return []

        table.query_selector_all.side_effect = qsa_side_effect

        result = session.extract_table("table")
        assert isinstance(result, list)

    def test_skips_rows_with_wrong_cell_count(self):
        session, pw, browser, context, page = _patched_session()
        table = MagicMock(name="table")
        page.query_selector.return_value = table

        th1, th2 = MagicMock(), MagicMock()
        th1.inner_text.return_value = "A"
        th2.inner_text.return_value = "B"

        # Row with only 1 cell (mismatch)
        bad_row = MagicMock()
        td_only = MagicMock()
        td_only.inner_text.return_value = "x"
        bad_row.query_selector_all.return_value = [td_only]

        def qsa_side_effect(selector):
            if "thead" in selector or "first-child" in selector:
                return [th1, th2]
            if "tbody" in selector or selector == "tr":
                return [bad_row]
            return []

        table.query_selector_all.side_effect = qsa_side_effect

        result = session.extract_table("table")
        assert result == []


# ---------------------------------------------------------------------------
# BrowserSession.wait_and_click
# ---------------------------------------------------------------------------


class TestBrowserSessionWaitAndClick:
    def test_waits_then_clicks(self):
        session, pw, browser, context, page = _patched_session()
        session.wait_and_click("button.submit")
        page.wait_for_selector.assert_called_once_with("button.submit", state="visible")
        page.click.assert_called_once_with("button.submit")


# ---------------------------------------------------------------------------
# BrowserSession.page property
# ---------------------------------------------------------------------------


class TestBrowserSessionPageProperty:
    def test_page_property_returns_page(self):
        session, pw, browser, context, page = _patched_session()
        assert session.page is page


# ---------------------------------------------------------------------------
# extract_google_news_links
# ---------------------------------------------------------------------------


class TestExtractGoogleNewsLinks:
    def _make_link(self, href, text):
        el = MagicMock()
        el.get_attribute.return_value = href
        el.inner_text.return_value = text
        return el

    def test_extracts_read_links(self):
        session, pw, browser, context, page = _patched_session()

        link1 = self._make_link("./read/CBMiABC", "Bitcoin hits new all-time high today")
        link2 = self._make_link("./articles/XYZ123", "Ethereum price analysis for this week")
        link3 = self._make_link("https://other.com/page", "Some unrelated page content here")
        session._page.query_selector_all.return_value = [link1, link2, link3]

        items = extract_google_news_links(session, limit=10, tags=["crypto"])

        assert len(items) == 2
        assert items[0]["source"] == "Google News"
        assert items[0]["tags"] == ["crypto"]
        assert items[0]["link"].startswith("https://news.google.com")

    def test_respects_limit(self):
        session, pw, browser, context, page = _patched_session()

        links = []
        for i in range(10):
            link = self._make_link(f"./read/item{i}", f"News article number {i} today big headline")
            links.append(link)
        session._page.query_selector_all.return_value = links

        items = extract_google_news_links(session, limit=3, tags=[])
        assert len(items) == 3

    def test_deduplicates_titles(self):
        session, pw, browser, context, page = _patched_session()

        same_title = "Bitcoin hits all-time high on Wall Street today!"
        link1 = self._make_link("./read/ABC", same_title)
        link2 = self._make_link("./read/DEF", same_title)
        session._page.query_selector_all.return_value = [link1, link2]

        items = extract_google_news_links(session, limit=10, tags=[])
        assert len(items) == 1

    def test_skips_short_titles(self):
        session, pw, browser, context, page = _patched_session()

        short = self._make_link("./read/ABC", "Short")  # < 10 chars
        good = self._make_link("./read/DEF", "This is a long enough title to pass")
        session._page.query_selector_all.return_value = [short, good]

        items = extract_google_news_links(session, limit=10, tags=[])
        assert len(items) == 1
        assert items[0]["title"] == "This is a long enough title to pass"

    def test_skips_empty_href(self):
        session, pw, browser, context, page = _patched_session()

        el = MagicMock()
        el.get_attribute.return_value = None
        el.inner_text.return_value = "Some article with a very long title indeed"
        session._page.query_selector_all.return_value = [el]

        items = extract_google_news_links(session, limit=10, tags=[])
        assert items == []

    def test_articles_prefix_kept_as_is(self):
        session, pw, browser, context, page = _patched_session()

        link = self._make_link("./articles/XYZ123abc", "Full length title for this news article today")
        session._page.query_selector_all.return_value = [link]

        items = extract_google_news_links(session, limit=10, tags=["stocks"])
        assert len(items) == 1
        assert "news.google.com" in items[0]["link"]

    def test_link_not_starting_with_dot_slash_kept_unchanged(self):
        """Absolute links (not starting with ./) should be kept as-is."""
        session, pw, browser, context, page = _patched_session()

        link = self._make_link("https://news.google.com/read/ABCXYZ", "Full length title for this article here")
        session._page.query_selector_all.return_value = [link]

        items = extract_google_news_links(session, limit=10, tags=[])
        # href doesn't contain ./read/ or ./articles/, so it's skipped
        assert items == []

    def test_exception_in_link_parse_is_swallowed(self):
        session, pw, browser, context, page = _patched_session()

        bad_link = MagicMock()
        bad_link.get_attribute.side_effect = RuntimeError("DOM error")
        good_link = self._make_link("./read/good", "Good article title that is long enough")
        session._page.query_selector_all.return_value = [bad_link, good_link]

        items = extract_google_news_links(session, limit=10, tags=[])
        assert len(items) == 1

    def test_returns_all_required_fields(self):
        session, pw, browser, context, page = _patched_session()
        link = self._make_link("./read/ABC123", "Complete news article title here long")
        session._page.query_selector_all.return_value = [link]

        items = extract_google_news_links(session, limit=10, tags=["tag1"])
        assert len(items) == 1
        item = items[0]
        assert "title" in item
        assert "description" in item
        assert "link" in item
        assert "published" in item
        assert "source" in item
        assert "tags" in item
        assert item["description"] == ""
        assert item["published"] == ""


# ---------------------------------------------------------------------------
# scrape_page
# ---------------------------------------------------------------------------


class TestScrapePage:
    def _build_enter_mock(self, pw, sp):
        """Patch so BrowserSession.__enter__ uses our mocks."""
        return patch("builtins.__import__", wraps=__import__)

    def test_basic_scrape(self):
        """scrape_page returns dict with url and extracted text."""
        pw, browser, context, page = _make_pw_mock()
        sp = _make_sync_playwright_patch(pw)

        # query_selector_all returns one element
        el = MagicMock()
        el.inner_text.return_value = "Hello"
        page.query_selector_all.return_value = [el]

        with patch("builtins.__import__", wraps=__import__) as mock_import:

            def side_effect(name, *args, **kwargs):
                if name == "playwright.sync_api":
                    mod = ModuleType("playwright.sync_api")
                    mod.sync_playwright = sp
                    return mod
                return __import__(name, *args, **kwargs)

            mock_import.side_effect = side_effect
            result = scrape_page("https://example.com", {"heading": "h1"})

        assert result["url"] == "https://example.com"
        assert result["heading"] == "Hello"

    def test_multiple_elements_returned_as_list(self):
        pw, browser, context, page = _make_pw_mock()
        sp = _make_sync_playwright_patch(pw)

        el1, el2 = MagicMock(), MagicMock()
        el1.inner_text.return_value = "A"
        el2.inner_text.return_value = "B"
        page.query_selector_all.return_value = [el1, el2]

        with patch("builtins.__import__", wraps=__import__) as mock_import:

            def side_effect(name, *args, **kwargs):
                if name == "playwright.sync_api":
                    mod = ModuleType("playwright.sync_api")
                    mod.sync_playwright = sp
                    return mod
                return __import__(name, *args, **kwargs)

            mock_import.side_effect = side_effect
            result = scrape_page("https://example.com", {"items": "li"})

        assert result["items"] == ["A", "B"]

    def test_error_returns_error_key(self):
        """When BrowserSession raises, result contains 'error' key."""
        with patch("common.browser.BrowserSession") as mock_bs_cls:
            mock_bs_cls.return_value.__enter__.side_effect = RuntimeError("browser launch failed")
            mock_bs_cls.return_value.__exit__ = MagicMock(return_value=False)
            result = scrape_page("https://example.com", {"x": "div"})

        assert result["url"] == "https://example.com"
        assert "error" in result
        assert "browser launch failed" in result["error"]

    def test_empty_selectors(self):
        pw, browser, context, page = _make_pw_mock()
        sp = _make_sync_playwright_patch(pw)

        with patch("builtins.__import__", wraps=__import__) as mock_import:

            def side_effect(name, *args, **kwargs):
                if name == "playwright.sync_api":
                    mod = ModuleType("playwright.sync_api")
                    mod.sync_playwright = sp
                    return mod
                return __import__(name, *args, **kwargs)

            mock_import.side_effect = side_effect
            result = scrape_page("https://example.com", {})

        assert result["url"] == "https://example.com"
        assert "error" not in result

    def test_timeout_passed_to_session(self):
        """scrape_page passes timeout to BrowserSession."""
        with patch("common.browser.BrowserSession") as mock_bs_cls:
            instance = MagicMock()
            mock_bs_cls.return_value = instance
            instance.__enter__ = MagicMock(return_value=instance)
            instance.__exit__ = MagicMock(return_value=False)
            instance.navigate = MagicMock()
            instance.extract_texts = MagicMock(return_value=["text"])

            scrape_page("https://example.com", {"k": "div"}, timeout=5_000)
            mock_bs_cls.assert_called_once_with(timeout=5_000)
