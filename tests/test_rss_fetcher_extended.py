"""Extended tests for RSS fetcher fetch_rss_feed() and concurrent fetch."""

from unittest.mock import MagicMock, patch

from common.rss_fetcher import fetch_rss_feed, fetch_rss_feeds_concurrent

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

    @patch("common.rss_fetcher.requests.get")
    def test_fallback_url_used_on_error(self, mock_get):
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
