"""Extended tests for RSS fetcher fetch_rss_feed() and concurrent fetch."""

from concurrent.futures import Future
from unittest.mock import MagicMock, patch

from common.rss_fetcher import (
    _decode_url_candidate,
    _resolve_google_news_url,
    fetch_rss_feed,
    fetch_rss_feeds_concurrent,
    is_safe_url,
)

RSS_MINIMAL = """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Test Feed</title>
    <item>
      <title>Bitcoin surges past 100K milestone today</title>
      <link>https://example.com/bitcoin-100k</link>
      <description>Bitcoin price hit a new all time high today.</description>
      <pubDate>Thu, 01 Jan 2099 10:00:00 +0000</pubDate>
    </item>
  </channel>
</rss>"""


RSS_TWO_ITEMS = """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Test Feed</title>
    <item>
      <title>Bitcoin surges past 100K milestone reached today</title>
      <link>https://example.com/btc</link>
      <description>Bitcoin is rising strongly today.</description>
      <pubDate>Thu, 01 Jan 2099 10:00:00 +0000</pubDate>
    </item>
    <item>
      <title>Ethereum upgrade goes live on mainnet successfully</title>
      <link>https://example.com/eth</link>
      <description>The upgrade is complete and working fine.</description>
      <pubDate>Thu, 01 Jan 2099 09:00:00 +0000</pubDate>
    </item>
  </channel>
</rss>"""


RSS_WITH_MEDIA = """<?xml version="1.0"?>
<rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/">
  <channel>
    <title>Media Feed</title>
    <item>
      <title>Market update with image attached today published</title>
      <link>https://example.com/market</link>
      <description>Market moved today on strong volume.</description>
      <pubDate>Thu, 01 Jan 2099 10:00:00 +0000</pubDate>
      <media:content url="https://example.com/image.jpg" medium="image"/>
    </item>
  </channel>
</rss>"""


ATOM_FEED = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Atom Test Feed</title>
  <entry>
    <title>ETH price analysis for this week in detail</title>
    <link href="https://example.com/eth-analysis"/>
    <updated>2099-01-01T10:00:00Z</updated>
    <summary>ETH is showing strong bullish momentum today.</summary>
  </entry>
</feed>"""


def _rss_with_link(link: str) -> str:
    return f"""<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Test Feed</title>
    <item>
      <title>Google feed article title for redirect resolver test</title>
      <link>{link}</link>
      <description>Google News redirect test item.</description>
      <pubDate>Thu, 01 Jan 2099 10:00:00 +0000</pubDate>
    </item>
  </channel>
</rss>"""


class TestFetchRssFeed:
    """Tests for fetch_rss_feed() with mocked HTTP."""

    @patch("common.rss_fetcher.requests.get")
    def test_returns_items_list(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.text = RSS_MINIMAL
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        items = fetch_rss_feed("https://example.com/feed.rss", "TestSource", ["test"])
        assert isinstance(items, list)
        assert len(items) == 1

    @patch("common.rss_fetcher.requests.get")
    def test_item_has_required_keys(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.text = RSS_MINIMAL
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        items = fetch_rss_feed("https://example.com/feed.rss", "TestSource", ["test"])
        item = items[0]
        assert "title" in item
        assert "description" in item
        assert "link" in item
        assert "published" in item
        assert "source" in item
        assert "tags" in item

    @patch("common.rss_fetcher.requests.get")
    def test_source_name_set_correctly(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.text = RSS_MINIMAL
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        items = fetch_rss_feed("https://example.com/feed.rss", "MySource", ["crypto"])
        assert items[0]["source"] == "MySource"

    @patch("common.rss_fetcher.requests.get")
    def test_tags_set_correctly(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.text = RSS_MINIMAL
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        items = fetch_rss_feed("https://example.com/feed.rss", "Source", ["crypto", "btc"])
        assert items[0]["tags"] == ["crypto", "btc"]

    @patch("common.rss_fetcher.requests.get")
    def test_two_items_returned(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.text = RSS_TWO_ITEMS
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        items = fetch_rss_feed("https://example.com/feed.rss", "Source", [])
        assert len(items) == 2

    @patch("common.rss_fetcher.requests.get")
    def test_limit_respected(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.text = RSS_TWO_ITEMS
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        items = fetch_rss_feed("https://example.com/feed.rss", "Source", [], limit=1)
        assert len(items) == 1

    @patch("common.rss_fetcher.requests.get")
    def test_network_error_returns_empty(self, mock_get):
        import requests as req

        mock_get.side_effect = req.exceptions.ConnectionError("refused")

        items = fetch_rss_feed("https://example.com/feed.rss", "Source", [])
        assert items == []

    @patch("common.rss_fetcher.requests.get")
    def test_http_error_returns_empty(self, mock_get):
        import requests as req

        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = req.exceptions.HTTPError("503")
        mock_get.return_value = mock_resp

        items = fetch_rss_feed("https://example.com/feed.rss", "Source", [])
        assert items == []

    @patch("common.rss_fetcher.requests.get")
    def test_atom_feed_parsed(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.text = ATOM_FEED
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        items = fetch_rss_feed("https://example.com/atom.xml", "AtomSource", [])
        assert len(items) == 1
        assert "ETH" in items[0]["title"]

    @patch("common.rss_fetcher.is_private_url", return_value=False)
    @patch("common.rss_fetcher.requests.get")
    def test_fallback_url_used_on_error(self, mock_get, _mock_private):  # noqa: PT019
        import requests as req

        fallback_rss = RSS_MINIMAL

        def side_effect(url, **kwargs):
            if "primary" in url:
                raise req.exceptions.ConnectionError("primary failed")
            mock_resp = MagicMock()
            mock_resp.text = fallback_rss
            mock_resp.raise_for_status.return_value = None
            return mock_resp

        mock_get.side_effect = side_effect

        items = fetch_rss_feed(
            "https://primary.com/feed.rss",
            "Source",
            [],
            fallback_urls=["https://fallback.com/feed.rss"],
        )
        assert len(items) == 1

    @patch("common.rss_fetcher.requests.get")
    def test_google_news_query_url_resolved_without_extra_request(self, mock_get):
        google_link = "https://news.google.com/rss/articles/CBMi?url=https%3A%2F%2Forigin.example%2Fstory"
        mock_resp = MagicMock()
        mock_resp.text = _rss_with_link(google_link)
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        items = fetch_rss_feed("https://example.com/feed.rss", "Source", [])
        assert len(items) == 1
        assert items[0]["link"] == "https://origin.example/story"
        assert items[0]["original_url"] == "https://origin.example/story"
        assert mock_get.call_count == 1

    @patch("common.rss_fetcher.is_private_url", return_value=False)
    @patch("common.rss_fetcher.requests.get")
    def test_google_news_redirect_location_resolved(self, mock_get, _mock_private):  # noqa: PT019
        google_link = "https://news.google.com/rss/articles/CBMiTest?oc=5"

        feed_resp = MagicMock()
        feed_resp.text = _rss_with_link(google_link)
        feed_resp.raise_for_status.return_value = None

        redirect_resp = MagicMock()
        redirect_resp.headers = {"Location": "https://origin.example/final-story"}

        def side_effect(url, **kwargs):
            if url == "https://example.com/feed.rss":
                return feed_resp
            if url == google_link and kwargs.get("allow_redirects") is False:
                return redirect_resp
            raise AssertionError(f"Unexpected URL call: {url}")

        mock_get.side_effect = side_effect

        items = fetch_rss_feed("https://example.com/feed.rss", "Source", [])
        assert len(items) == 1
        assert items[0]["link"] == "https://origin.example/final-story"
        assert items[0]["original_url"] == "https://origin.example/final-story"

    @patch("common.rss_fetcher.requests.get")
    def test_google_news_resolve_rejects_unsafe_redirect_scheme(self, mock_get):
        google_link = "https://news.google.com/rss/articles/CBMiUnsafe?oc=5"

        feed_resp = MagicMock()
        feed_resp.text = _rss_with_link(google_link)
        feed_resp.raise_for_status.return_value = None

        redirect_resp = MagicMock()
        redirect_resp.headers = {"Location": "javascript:alert(1)"}

        def side_effect(url, **kwargs):
            if url == "https://example.com/feed.rss":
                return feed_resp
            if url == google_link and kwargs.get("allow_redirects") is False:
                return redirect_resp
            raise AssertionError(f"Unexpected URL call: {url}")

        mock_get.side_effect = side_effect

        items = fetch_rss_feed("https://example.com/feed.rss", "Source", [])
        assert len(items) == 1
        assert items[0]["link"] == google_link
        assert "original_url" not in items[0]

    @patch("common.rss_fetcher.requests.get")
    def test_google_news_resolve_failure_keeps_original_link(self, mock_get):
        import requests as req

        google_link = "https://news.google.com/rss/articles/CBMiTimeout?oc=5"

        feed_resp = MagicMock()
        feed_resp.text = _rss_with_link(google_link)
        feed_resp.raise_for_status.return_value = None

        def side_effect(url, **kwargs):
            if url == "https://example.com/feed.rss":
                return feed_resp
            if url == google_link and kwargs.get("allow_redirects") is False:
                raise req.exceptions.Timeout("resolver timeout")
            raise AssertionError(f"Unexpected URL call: {url}")

        mock_get.side_effect = side_effect

        items = fetch_rss_feed("https://example.com/feed.rss", "Source", [])
        assert len(items) == 1
        assert items[0]["link"] == google_link


class TestFetchRssFeedsConcurrent:
    """Tests for fetch_rss_feeds_concurrent()."""

    @patch("common.rss_fetcher.fetch_rss_feed")
    def test_empty_feeds_returns_empty(self, mock_fetch):
        result = fetch_rss_feeds_concurrent([])
        assert result == []

    @patch("common.rss_fetcher.fetch_rss_feed")
    def test_combines_results(self, mock_fetch):
        mock_fetch.return_value = [{"title": "item", "source": "test"}]
        feeds = [
            ("https://a.com/feed", "A", ["tag"]),
            ("https://b.com/feed", "B", ["tag"]),
        ]
        result = fetch_rss_feeds_concurrent(feeds)
        assert len(result) == 2

    @patch("common.rss_fetcher.fetch_rss_feed")
    def test_uses_limit_from_tuple(self, mock_fetch):
        mock_fetch.return_value = []
        feeds = [("https://a.com/feed", "A", ["tag"], 5)]
        fetch_rss_feeds_concurrent(feeds)
        call_kwargs = mock_fetch.call_args
        assert call_kwargs[1].get("limit") == 5 or call_kwargs[0][3] == 5

    @patch("common.rss_fetcher.fetch_rss_feed")
    def test_uses_max_age_from_tuple(self, mock_fetch):
        mock_fetch.return_value = []
        feeds = [("https://a.com/feed", "A", ["tag"], 10, 24)]
        fetch_rss_feeds_concurrent(feeds)
        call_kwargs = mock_fetch.call_args
        assert call_kwargs[1].get("max_age_hours") == 24 or call_kwargs[0][4] == 24

    @patch("common.rss_fetcher.fetch_rss_feed")
    def test_exception_in_worker_skipped(self, mock_fetch):
        mock_fetch.side_effect = Exception("unexpected error")
        feeds = [("https://a.com/feed", "A", ["tag"])]
        # Should not raise, just return empty
        result = fetch_rss_feeds_concurrent(feeds)
        assert result == []

    @patch("common.rss_fetcher.fetch_rss_feed")
    def test_timeout_in_worker_skipped(self, mock_fetch):
        """Covers lines 352-353: TimeoutError branch in concurrent fetch."""
        # Make future.result() raise TimeoutError by patching as_completed inside the module's local scope
        bad_future = Future()
        bad_future.set_exception(TimeoutError("timed out"))

        import concurrent.futures as cf_module  # noqa: F401

        class _FakePool:
            def __init__(self, *a, **kw):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

            def submit(self, fn, arg):
                return bad_future

        with (
            patch("concurrent.futures.ThreadPoolExecutor", _FakePool),
            patch("concurrent.futures.as_completed", return_value=[bad_future]),
        ):
            result = fetch_rss_feeds_concurrent([("https://a.com/feed", "A", ["tag"])])

        assert result == []

    @patch("common.rss_fetcher.fetch_rss_feed")
    def test_fallback_urls_from_options_dict(self, mock_fetch):
        """Covers tuple[5] options dict with fallback_urls."""
        mock_fetch.return_value = [{"title": "item"}]
        feeds = [
            (
                "https://a.com/feed",
                "A",
                ["tag"],
                15,
                48,
                {"fallback_urls": ["https://b.com/feed"]},
            )
        ]
        result = fetch_rss_feeds_concurrent(feeds)
        assert len(result) == 1
        call_kwargs = mock_fetch.call_args
        assert call_kwargs[1].get("fallback_urls") == ["https://b.com/feed"]


class TestIsSafeUrl:
    """Covers lines 27-28: is_safe_url exception path."""

    def test_safe_http_url(self):
        assert is_safe_url("http://example.com") is True

    def test_safe_https_url(self):
        assert is_safe_url("https://example.com/path") is True

    def test_empty_string_is_safe(self):
        # Empty scheme "" is allowed
        assert is_safe_url("") is True

    def test_javascript_scheme_rejected(self):
        assert is_safe_url("javascript:alert(1)") is False

    def test_data_scheme_rejected(self):
        assert is_safe_url("data:text/html,<h1>x</h1>") is False

    def test_exception_returns_false(self):
        """Covers line 27-28: exception branch returns False."""
        # Force urlparse to raise by patching it
        with patch("common.rss_fetcher.urlparse", side_effect=ValueError("bad")):
            result = is_safe_url("http://example.com")
        assert result is False


class TestDecodeUrlCandidate:
    """Covers line 38: break when decoded == candidate (no change)."""

    def test_already_decoded_breaks_early(self):
        """If the string doesn't change after unquote, loop breaks (line 38)."""

        plain = "https://example.com/path"
        result = _decode_url_candidate(plain)
        assert result == plain

    def test_percent_encoded_decoded(self):

        encoded = "https%3A%2F%2Fexample.com%2Fpath"
        result = _decode_url_candidate(encoded)
        assert result == "https://example.com/path"

    def test_empty_string_returns_empty(self):

        assert _decode_url_candidate("") == ""


class TestResolveGoogleNewsUrl:
    """Covers lines 59, 63, 84, 91-97, 100."""

    def test_empty_url_returns_empty(self):
        """Covers line 59: not url."""
        result = _resolve_google_news_url("")
        assert result == ""

    def test_unsafe_url_returns_empty(self):
        """Covers line 59: not is_safe_url."""
        result = _resolve_google_news_url("javascript:alert(1)")
        assert result == ""

    def test_non_google_host_returns_empty(self):
        """Covers line 63: netloc not in _GOOGLE_NEWS_HOSTS."""
        result = _resolve_google_news_url("https://other.example.com/rss/article")
        assert result == ""

    @patch("common.rss_fetcher.requests.get")
    def test_empty_location_header_returns_empty(self, mock_get):
        """Covers line 84: location header is empty."""
        mock_resp = MagicMock()
        mock_resp.headers = {"Location": ""}
        mock_resp.close.return_value = None
        mock_get.return_value = mock_resp

        result = _resolve_google_news_url("https://news.google.com/rss/articles/CBMiTest")
        assert result == ""

    @patch("common.rss_fetcher.requests.get")
    def test_nested_google_redirect_resolved_via_query(self, mock_get):
        """Covers lines 91-94: location is another Google URL with query param."""
        # First redirect points to another google URL with url= param
        nested_google = "https://news.google.com/rss/articles/CBMiNested?url=https%3A%2F%2Ffinal.example.com%2Fstory"
        mock_resp = MagicMock()
        mock_resp.headers = {"Location": nested_google}
        mock_resp.close.return_value = None
        mock_get.return_value = mock_resp

        result = _resolve_google_news_url("https://news.google.com/rss/articles/CBMiOuter")
        assert result == "https://final.example.com/story"

    @patch("common.rss_fetcher.requests.get")
    def test_nested_google_redirect_no_query_continues_loop(self, mock_get):
        """Covers lines 95-96 and 100: nested google URL with no query → loop exhausted → return ''."""
        # Always returns a google URL without query params → loop runs twice then returns ""
        nested_google = "https://news.google.com/rss/articles/CBMiNested"
        mock_resp = MagicMock()
        mock_resp.headers = {"Location": nested_google}
        mock_resp.close.return_value = None
        mock_get.return_value = mock_resp

        result = _resolve_google_news_url("https://news.google.com/rss/articles/CBMiOuter")
        assert result == ""

    @patch("common.rss_fetcher.requests.get")
    def test_location_with_non_http_non_google_scheme_returns_empty(self, mock_get):
        """Covers line 97: Location is a protocol-relative URL (scheme='') with non-Google netloc.

        is_safe_url passes (empty scheme allowed), but the scheme is not http/https
        so line 89 is False, and netloc is not Google so line 91 is False → line 97 hit.
        """
        mock_resp = MagicMock()
        # Protocol-relative URL: urlparse gives scheme='' and netloc='example.com'
        mock_resp.headers = {"Location": "//example.com/article"}
        mock_resp.close.return_value = None
        mock_get.return_value = mock_resp

        result = _resolve_google_news_url("https://news.google.com/rss/articles/CBMiRelative")
        assert result == ""


class TestFetchRssFeedUncoveredBranches:
    """Covers remaining uncovered branches in fetch_rss_feed."""

    # Both is_private_url patches are load-bearing (NOT redundant): the
    # ``common.enrichment.is_private_url`` patch covers the lazy
    # ``from .enrichment import is_private_url`` guard in fetch_rss_feed's
    # worldmonitor-proxy branch (rss_fetcher.py:~177), which runs on the DECODED
    # candidate URL; the ``common.rss_fetcher.is_private_url`` patch covers the
    # per-candidate guard in the fetch loop. Dropping either makes the decoded/
    # candidate URL hit the real resolver (real DNS → non-hermetic).
    @patch("common.enrichment.is_private_url", return_value=False)
    @patch("common.rss_fetcher.is_private_url", return_value=False)
    @patch("common.rss_fetcher.requests.get")
    def test_worldmonitor_proxy_url_adds_decoded_candidate(self, mock_get, _mock_private, _mock_enrich_private):  # noqa: PT019
        """Covers lines 147-151: worldmonitor proxy adds decoded URL to candidates."""
        import requests as req

        # Primary worldmonitor URL fails; decoded candidate also fails → empty
        mock_get.side_effect = req.exceptions.ConnectionError("fail")

        encoded_url = "https%3A%2F%2Factual-source.example.com%2Ffeed.rss"
        proxy_url = f"https://worldmonitor.app/api/rss-proxy?url={encoded_url}"

        items = fetch_rss_feed(proxy_url, "Source", [])
        assert items == []
        # Both worldmonitor URL and decoded URL should have been tried
        assert mock_get.call_count == 2
        calls = [c[0][0] for c in mock_get.call_args_list]
        assert any("worldmonitor.app" in c for c in calls)
        assert any("actual-source.example.com" in c for c in calls)

    @patch("common.rss_fetcher.requests.get")
    def test_item_with_empty_title_skipped(self, mock_get):
        """Covers line 189: entry with no title text is skipped."""
        rss_no_title = """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Feed</title>
    <item>
      <title></title>
      <link>https://example.com/no-title</link>
      <description>Some description here.</description>
      <pubDate>Thu, 01 Jan 2099 10:00:00 +0000</pubDate>
    </item>
  </channel>
</rss>"""
        mock_resp = MagicMock()
        mock_resp.text = rss_no_title
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        items = fetch_rss_feed("https://example.com/feed.rss", "Source", [])
        assert items == []

    @patch("common.rss_fetcher.requests.get")
    def test_old_article_filtered_by_max_age(self, mock_get):
        """Covers line 214: pub_dt < cutoff → item skipped."""
        rss_old = """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Feed</title>
    <item>
      <title>Very old article that should be filtered out here</title>
      <link>https://example.com/old</link>
      <description>This is an old article description text.</description>
      <pubDate>Thu, 01 Jan 2000 10:00:00 +0000</pubDate>
    </item>
  </channel>
</rss>"""
        mock_resp = MagicMock()
        mock_resp.text = rss_old
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        items = fetch_rss_feed("https://example.com/feed.rss", "Source", [], max_age_hours=48)
        assert items == []

    @patch("common.rss_fetcher.requests.get")
    def test_unsafe_link_url_blocked_and_cleared(self, mock_get):
        """Covers lines 222-223: link_val with unsafe scheme is warned and blanked."""
        rss_unsafe_link = """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Feed</title>
    <item>
      <title>Article with dangerous javascript link scheme here</title>
      <link>javascript:alert(document.cookie)</link>
      <description>Malicious link article description text here.</description>
      <pubDate>Thu, 01 Jan 2099 10:00:00 +0000</pubDate>
    </item>
  </channel>
</rss>"""
        mock_resp = MagicMock()
        mock_resp.text = rss_unsafe_link
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        items = fetch_rss_feed("https://example.com/feed.rss", "Source", [])
        assert len(items) == 1
        assert items[0]["link"] == ""

    @patch("common.rss_fetcher.requests.get")
    def test_image_from_content_tag_url_attr(self, mock_get):
        """Covers line 231: image from plain <content url="..."> when namespace is stripped."""
        rss_content_tag = """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Feed</title>
    <item>
      <title>Article with content tag image url attribute for coverage test</title>
      <link>https://example.com/content-tag</link>
      <description>Content tag image test description text goes here.</description>
      <pubDate>Thu, 01 Jan 2099 10:00:00 +0000</pubDate>
      <content url="https://example.com/content-img.jpg" medium="image"/>
    </item>
  </channel>
</rss>"""
        mock_resp = MagicMock()
        mock_resp.text = rss_content_tag
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        items = fetch_rss_feed("https://example.com/feed.rss", "Source", [])
        assert len(items) == 1
        assert items[0].get("image") == "https://example.com/content-img.jpg"

    @patch("common.rss_fetcher.requests.get")
    def test_image_from_media_thumbnail(self, mock_get):
        """Covers line 236: image URL from media:thumbnail element."""
        rss_thumbnail = """<?xml version="1.0"?>
<rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/">
  <channel>
    <title>Feed</title>
    <item>
      <title>Article with thumbnail image attached for testing purposes</title>
      <link>https://example.com/thumb</link>
      <description>Article with thumbnail description text here.</description>
      <pubDate>Thu, 01 Jan 2099 10:00:00 +0000</pubDate>
      <media:thumbnail url="https://example.com/thumb.jpg"/>
    </item>
  </channel>
</rss>"""
        mock_resp = MagicMock()
        mock_resp.text = rss_thumbnail
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        items = fetch_rss_feed("https://example.com/feed.rss", "Source", [])
        assert len(items) == 1
        assert items[0].get("image") == "https://example.com/thumb.jpg"

    @patch("common.rss_fetcher.requests.get")
    def test_image_from_enclosure_tag(self, mock_get):
        """Covers lines 241-243: image URL from enclosure element."""
        rss_enclosure = """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Feed</title>
    <item>
      <title>Article with enclosure image attached for testing purposes</title>
      <link>https://example.com/enc</link>
      <description>Article with enclosure description text here.</description>
      <pubDate>Thu, 01 Jan 2099 10:00:00 +0000</pubDate>
      <enclosure url="https://example.com/photo.jpg" type="image/jpeg" length="12345"/>
    </item>
  </channel>
</rss>"""
        mock_resp = MagicMock()
        mock_resp.text = rss_enclosure
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        items = fetch_rss_feed("https://example.com/feed.rss", "Source", [])
        assert len(items) == 1
        assert items[0].get("image") == "https://example.com/photo.jpg"

    @patch("common.rss_fetcher.requests.get")
    def test_image_from_embedded_img_in_description(self, mock_get):
        """Covers line 249: image URL extracted from <img> tag in description HTML.

        The img element must be an actual XML child of <description> so that
        str(desc_el) contains the raw <img src="..."> markup the regex matches.
        """
        rss_img_desc = """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Feed</title>
    <item>
      <title>Article with embedded image in description for testing purposes</title>
      <link>https://example.com/img-desc</link>
      <description><img src="https://example.com/inline.jpg" alt="img"/> Some text here for the article.</description>
      <pubDate>Thu, 01 Jan 2099 10:00:00 +0000</pubDate>
    </item>
  </channel>
</rss>"""
        mock_resp = MagicMock()
        mock_resp.text = rss_img_desc
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        items = fetch_rss_feed("https://example.com/feed.rss", "Source", [])
        assert len(items) == 1
        assert items[0].get("image") == "https://example.com/inline.jpg"

    @patch("common.rss_fetcher.requests.get")
    def test_original_url_from_source_element(self, mock_get):
        """Covers lines 255-258: original_url from <source url=""> element."""
        rss_source_url = """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Feed</title>
    <item>
      <title>Article with source element for original url tracking here</title>
      <link>https://example.com/article</link>
      <description>Article with source element description text here.</description>
      <pubDate>Thu, 01 Jan 2099 10:00:00 +0000</pubDate>
      <source url="https://origin.example.com/original">Origin Source</source>
    </item>
  </channel>
</rss>"""
        mock_resp = MagicMock()
        mock_resp.text = rss_source_url
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        items = fetch_rss_feed("https://example.com/feed.rss", "Source", [])
        assert len(items) == 1
        assert items[0].get("original_url") == "https://origin.example.com/original"

    @patch("common.rss_fetcher.requests.get")
    def test_image_key_set_in_item_data(self, mock_get):
        """Covers line 277: item_data['image'] is set when image_url is found (enclosure fallback)."""
        rss_with_enc = """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Feed</title>
    <item>
      <title>Article with image key test for coverage of line 277 here</title>
      <link>https://example.com/img-key</link>
      <description>Image key test description text goes here.</description>
      <pubDate>Thu, 01 Jan 2099 10:00:00 +0000</pubDate>
      <enclosure url="https://example.com/cover.png" type="image/png" length="999"/>
    </item>
  </channel>
</rss>"""
        mock_resp = MagicMock()
        mock_resp.text = rss_with_enc
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        items = fetch_rss_feed("https://example.com/feed.rss", "Source", [])
        assert len(items) == 1
        assert "image" in items[0]
        assert items[0]["image"] == "https://example.com/cover.png"
