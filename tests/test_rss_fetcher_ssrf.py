"""SSRF guard regression tests for scripts/common/rss_fetcher.py.

Covers the *positive* (blocking) path of the two SSRF guards inside
``fetch_rss_feed`` — something the existing suite (``test_rss_fetcher.py``,
``test_rss_fetcher_extended.py``) never exercised:

* Guard 1 (``rss_fetcher.py`` worldmonitor-proxy branch): a decoded
  ``?url=`` query param that resolves to a private/internal target is never
  added to the fetch candidates.
* Guard 2 (``rss_fetcher.py`` fetch loop): a private/internal candidate URL
  never reaches ``requests.get`` — the loop raises before the call.

Every assertion here is on an *observable side effect* (whether
``requests.get`` was actually invoked with a given URL), not on the return
value alone, so a guard silently replaced with ``return []`` cannot pass.
Each guard also gets a control case with a public URL to prove the guard
does not fail closed for legitimate targets (which would let a return-[]
stub pass unnoticed).

Real ``is_private_url_target`` judgement is used throughout (no mocking of
the guard functions themselves) so a mutation to the guard's own logic is
caught, not just a mutation to the call site.
"""

from unittest.mock import MagicMock, patch
from urllib.parse import quote

from common.rss_fetcher import fetch_rss_feed

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


def _called_urls(mock_get) -> list:
    """Extract the URL each ``requests.get`` call actually targeted."""
    urls = []
    for call in mock_get.call_args_list:
        if call.args:
            urls.append(call.args[0])
        else:
            urls.append(call.kwargs.get("url"))
    return urls


def _mock_feed_response() -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.text = RSS_MINIMAL
    mock_resp.raise_for_status.return_value = None
    return mock_resp


class TestCandidateLoopSsrfGuard:
    """Guard 2 (rss_fetcher.py:204-207): per-candidate private-URL block."""

    @patch("common.rss_fetcher.requests.get")
    def test_literal_private_ip_never_requested(self, mock_get):
        """A raw loopback IP must never reach requests.get."""
        mock_get.return_value = _mock_feed_response()

        items = fetch_rss_feed("http://127.0.0.1/internal-feed.rss", "Source", [])

        assert items == []
        mock_get.assert_not_called()

    @patch("common.rss_fetcher.requests.get")
    def test_literal_private_class_a_ip_never_requested(self, mock_get):
        """10.0.0.0/8 is private per RFC1918 — must never reach requests.get."""
        mock_get.return_value = _mock_feed_response()

        items = fetch_rss_feed("http://10.0.0.1/feed.rss", "Source", [])

        assert items == []
        mock_get.assert_not_called()

    @patch("common.rss_fetcher.requests.get")
    def test_localhost_hostname_never_requested(self, mock_get):
        mock_get.return_value = _mock_feed_response()

        items = fetch_rss_feed("http://localhost:8080/feed.rss", "Source", [])

        assert items == []
        mock_get.assert_not_called()

    @patch("common.rss_fetcher.requests.get")
    def test_internal_suffix_hostname_never_requested(self, mock_get):
        mock_get.return_value = _mock_feed_response()

        items = fetch_rss_feed("http://service.internal/feed.rss", "Source", [])

        assert items == []
        mock_get.assert_not_called()

    @patch("common.rss_fetcher.requests.get")
    def test_public_url_control_case_is_actually_requested(self, mock_get):
        """Control: a public URL must be requested — proves the guard isn't
        fail-closed for everything (which a hardcoded ``return []`` would
        also satisfy on the blocked-case tests above)."""
        mock_get.return_value = _mock_feed_response()

        items = fetch_rss_feed("https://example.com/feed.rss", "Source", [])

        assert len(items) == 1
        called_urls = _called_urls(mock_get)
        assert "https://example.com/feed.rss" in called_urls


class TestWorldmonitorProxySsrfGuard:
    """Guard 1 (rss_fetcher.py:188-200): decoded worldmonitor proxy ?url= param."""

    @patch("common.rss_fetcher.is_private_url", return_value=False)
    @patch("common.rss_fetcher.requests.get")
    def test_private_decoded_target_never_requested(self, mock_get, _neutralize_candidate_loop_guard):  # noqa: PT019
        """A private target hidden behind the worldmonitor proxy's ?url= param
        must never be added as a fetch candidate.

        The candidate-loop guard (guard 2) is neutralized here on purpose so
        this test isolates guard 1: if guard 1's own private-URL check were
        disabled (e.g. mutated to ``if False``), the decoded target would be
        appended to ``candidates`` and — with guard 2 neutralized too — would
        actually reach ``requests.get`` once the primary proxy fetch fails.
        Leaving guard 2 real here would let it silently absorb a guard-1
        failure, making this test pass regardless of guard 1's state.
        """
        import requests as req

        def side_effect(url, **kwargs):
            if "worldmonitor.app" in url:
                raise req.exceptions.ConnectionError("proxy unreachable")
            return _mock_feed_response()

        mock_get.side_effect = side_effect

        private_target = "http://127.0.0.1/admin"
        proxy_url = f"https://worldmonitor.app/api/rss-proxy?url={quote(private_target, safe='')}"

        items = fetch_rss_feed(proxy_url, "Source", [])

        called_urls = _called_urls(mock_get)
        assert private_target not in called_urls
        # The proxy fetch failed and the private candidate was never added,
        # so there was no fallback candidate left to try.
        assert items == []

    @patch("common.rss_fetcher.requests.get")
    def test_public_decoded_target_control_case_is_actually_requested(self, mock_get):
        """Control: a public target behind the proxy's ?url= param must be
        added as a candidate and actually requested when the primary proxy
        fetch fails. Without this, the guard-1 blocked-case test above could
        be satisfied by a mutant that never adds *any* decoded candidate."""
        import requests as req

        def side_effect(url, **kwargs):
            if "worldmonitor.app" in url:
                raise req.exceptions.ConnectionError("proxy unreachable")
            return _mock_feed_response()

        mock_get.side_effect = side_effect

        public_target = "https://actual-source.example.com/feed.rss"
        proxy_url = f"https://worldmonitor.app/api/rss-proxy?url={quote(public_target, safe='')}"

        items = fetch_rss_feed(proxy_url, "Source", [])

        called_urls = _called_urls(mock_get)
        assert public_target in called_urls
        assert len(items) == 1
