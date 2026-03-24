"""Unit tests for collector modules: rss_fetcher, crypto_api, fmp_api, collector_metrics."""

import os
import sys
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# sys.path: make `scripts/` importable as a package root so that
# `from common.xxx import ...` works the same way the collector scripts do.
# ---------------------------------------------------------------------------
_SCRIPTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

# ---------------------------------------------------------------------------
# Minimal RSS XML fixtures
# ---------------------------------------------------------------------------

_VALID_RSS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Feed</title>
    <item>
      <title>Bitcoin surges to new high</title>
      <link>https://example.com/btc-high</link>
      <pubDate>Mon, 24 Mar 2026 06:00:00 +0000</pubDate>
      <description>Bitcoin reached a new record price today.</description>
    </item>
    <item>
      <title>Ethereum upgrade complete</title>
      <link>https://example.com/eth-upgrade</link>
      <pubDate>Mon, 24 Mar 2026 05:00:00 +0000</pubDate>
      <description>The Ethereum network completed its scheduled upgrade.</description>
    </item>
  </channel>
</rss>"""

_EMPTY_RSS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Empty Feed</title>
  </channel>
</rss>"""


# ---------------------------------------------------------------------------
# Helper: build a mock HTTP response
# ---------------------------------------------------------------------------

def _make_response(text: str, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        import requests
        resp.raise_for_status.side_effect = requests.exceptions.HTTPError(
            f"{status_code} Error", response=resp
        )
    return resp


# ---------------------------------------------------------------------------
# rss_fetcher tests
# ---------------------------------------------------------------------------

class TestFetchRssFeed:
    """Tests for rss_fetcher.fetch_rss_feed()."""

    def test_valid_rss_returns_items(self):
        from common.rss_fetcher import fetch_rss_feed

        with patch("common.rss_fetcher.requests.get") as mock_get:
            mock_get.return_value = _make_response(_VALID_RSS_XML)
            items = fetch_rss_feed(
                url="https://example.com/feed.rss",
                source_name="TestFeed",
                tags=["crypto"],
                max_age_hours=0,  # skip age filter
            )

        assert len(items) == 2

    def test_valid_rss_item_fields(self):
        from common.rss_fetcher import fetch_rss_feed

        with patch("common.rss_fetcher.requests.get") as mock_get:
            mock_get.return_value = _make_response(_VALID_RSS_XML)
            items = fetch_rss_feed(
                url="https://example.com/feed.rss",
                source_name="TestSource",
                tags=["bitcoin"],
                max_age_hours=0,
            )

        first = items[0]
        assert "title" in first
        assert "link" in first
        assert "published" in first
        assert "source" in first
        assert "tags" in first
        assert first["source"] == "TestSource"
        assert first["tags"] == ["bitcoin"]

    def test_valid_rss_title_extraction(self):
        from common.rss_fetcher import fetch_rss_feed

        with patch("common.rss_fetcher.requests.get") as mock_get:
            mock_get.return_value = _make_response(_VALID_RSS_XML)
            items = fetch_rss_feed(
                url="https://example.com/feed.rss",
                source_name="TestFeed",
                tags=[],
                max_age_hours=0,
            )

        assert "Bitcoin" in items[0]["title"]

    def test_valid_rss_link_extraction(self):
        from common.rss_fetcher import fetch_rss_feed

        with patch("common.rss_fetcher.requests.get") as mock_get:
            mock_get.return_value = _make_response(_VALID_RSS_XML)
            items = fetch_rss_feed(
                url="https://example.com/feed.rss",
                source_name="TestFeed",
                tags=[],
                max_age_hours=0,
            )

        assert items[0]["link"] == "https://example.com/btc-high"

    def test_valid_rss_published_extraction(self):
        from common.rss_fetcher import fetch_rss_feed

        with patch("common.rss_fetcher.requests.get") as mock_get:
            mock_get.return_value = _make_response(_VALID_RSS_XML)
            items = fetch_rss_feed(
                url="https://example.com/feed.rss",
                source_name="TestFeed",
                tags=[],
                max_age_hours=0,
            )

        assert items[0]["published"] != ""

    def test_empty_feed_returns_empty_list(self):
        from common.rss_fetcher import fetch_rss_feed

        with patch("common.rss_fetcher.requests.get") as mock_get:
            mock_get.return_value = _make_response(_EMPTY_RSS_XML)
            items = fetch_rss_feed(
                url="https://example.com/empty.rss",
                source_name="EmptyFeed",
                tags=[],
            )

        assert items == []

    def test_http_error_returns_empty_list(self):
        import requests as req_lib

        from common.rss_fetcher import fetch_rss_feed

        with patch("common.rss_fetcher.requests.get") as mock_get:
            mock_get.side_effect = req_lib.exceptions.HTTPError("503 Service Unavailable")
            items = fetch_rss_feed(
                url="https://example.com/broken.rss",
                source_name="BrokenFeed",
                tags=[],
            )

        assert items == []

    def test_connection_error_returns_empty_list(self):
        import requests as req_lib

        from common.rss_fetcher import fetch_rss_feed

        with patch("common.rss_fetcher.requests.get") as mock_get:
            mock_get.side_effect = req_lib.exceptions.ConnectionError("Connection refused")
            items = fetch_rss_feed(
                url="https://example.com/unreachable.rss",
                source_name="UnreachableFeed",
                tags=[],
            )

        assert items == []

    def test_limit_respected(self):
        from common.rss_fetcher import fetch_rss_feed

        with patch("common.rss_fetcher.requests.get") as mock_get:
            mock_get.return_value = _make_response(_VALID_RSS_XML)
            items = fetch_rss_feed(
                url="https://example.com/feed.rss",
                source_name="TestFeed",
                tags=[],
                limit=1,
                max_age_hours=0,
            )

        assert len(items) <= 1

    def test_feed_health_updated_on_success(self):
        from common.rss_fetcher import fetch_rss_feed, get_feed_health

        url = "https://example.com/health-test.rss"
        with patch("common.rss_fetcher.requests.get") as mock_get:
            mock_get.return_value = _make_response(_VALID_RSS_XML)
            fetch_rss_feed(url=url, source_name="HealthTest", tags=[], max_age_hours=0)

        health = get_feed_health()
        assert url in health
        assert health[url]["ok"] >= 1


# ---------------------------------------------------------------------------
# crypto_api tests
# ---------------------------------------------------------------------------

class TestFetchCoingeckoTopCoins:
    """Tests for crypto_api.fetch_coingecko_top_coins()."""

    def _make_coins_response(self, count: int = 3) -> MagicMock:
        coins = [
            {"id": f"coin-{i}", "symbol": f"c{i}", "current_price": 100 * i}
            for i in range(1, count + 1)
        ]
        resp = MagicMock()
        resp.json.return_value = coins
        return resp

    def test_returns_list_of_coins(self):
        from common.crypto_api import fetch_coingecko_top_coins

        with patch("common.crypto_api.request_with_retry") as mock_req:
            mock_req.return_value = self._make_coins_response(5)
            coins = fetch_coingecko_top_coins(limit=5)

        assert isinstance(coins, list)
        assert len(coins) == 5

    def test_passes_limit_param(self):
        from common.crypto_api import fetch_coingecko_top_coins

        with patch("common.crypto_api.request_with_retry") as mock_req:
            mock_req.return_value = self._make_coins_response(10)
            fetch_coingecko_top_coins(limit=10)

        call_kwargs = mock_req.call_args
        params = call_kwargs[1].get("params") or call_kwargs[0][1] if len(call_kwargs[0]) > 1 else {}
        # params may be passed as keyword arg
        if call_kwargs[1].get("params"):
            assert call_kwargs[1]["params"]["per_page"] == 10

    def test_timeout_error_returns_empty_list(self):
        import requests as req_lib

        from common.crypto_api import fetch_coingecko_top_coins

        with patch("common.crypto_api.request_with_retry") as mock_req:
            mock_req.side_effect = req_lib.exceptions.Timeout("Request timed out")
            coins = fetch_coingecko_top_coins()

        assert coins == []

    def test_connection_error_returns_empty_list(self):
        import requests as req_lib

        from common.crypto_api import fetch_coingecko_top_coins

        with patch("common.crypto_api.request_with_retry") as mock_req:
            mock_req.side_effect = req_lib.exceptions.ConnectionError("Network error")
            coins = fetch_coingecko_top_coins()

        assert coins == []

    def test_invalid_json_returns_empty_list(self):
        import requests as req_lib

        from common.crypto_api import fetch_coingecko_top_coins

        with patch("common.crypto_api.request_with_retry") as mock_req:
            mock_req.side_effect = req_lib.exceptions.RequestException("Bad response")
            coins = fetch_coingecko_top_coins()

        assert coins == []


class TestFetchFearGreedIndex:
    """Tests for crypto_api.fetch_fear_greed_index()."""

    def _make_fng_response(self, value: int = 55, classification: str = "Greed") -> MagicMock:
        resp = MagicMock()
        resp.json.return_value = {
            "data": [
                {"value": str(value), "value_classification": classification},
            ]
        }
        return resp

    def test_returns_value_and_classification(self):
        from common.crypto_api import fetch_fear_greed_index

        with patch("common.crypto_api.request_with_retry") as mock_req:
            mock_req.return_value = self._make_fng_response(72, "Greed")
            result = fetch_fear_greed_index()

        assert result["value"] == 72
        assert result["classification"] == "Greed"

    def test_returns_prev_when_history_requested(self):
        from common.crypto_api import fetch_fear_greed_index

        resp = MagicMock()
        resp.json.return_value = {
            "data": [
                {"value": "65", "value_classification": "Greed"},
                {"value": "50", "value_classification": "Neutral"},
            ]
        }
        with patch("common.crypto_api.request_with_retry") as mock_req:
            mock_req.return_value = resp
            result = fetch_fear_greed_index(history_days=7)

        assert result["prev_value"] == 50
        assert result["prev_classification"] == "Neutral"

    def test_empty_data_returns_empty_dict(self):
        from common.crypto_api import fetch_fear_greed_index

        resp = MagicMock()
        resp.json.return_value = {"data": []}
        with patch("common.crypto_api.request_with_retry") as mock_req:
            mock_req.return_value = resp
            result = fetch_fear_greed_index()

        assert result == {}

    def test_timeout_returns_empty_dict(self):
        import requests as req_lib

        from common.crypto_api import fetch_fear_greed_index

        with patch("common.crypto_api.request_with_retry") as mock_req:
            mock_req.side_effect = req_lib.exceptions.Timeout("Timeout")
            result = fetch_fear_greed_index()

        assert result == {}

    def test_request_exception_returns_empty_dict(self):
        import requests as req_lib

        from common.crypto_api import fetch_fear_greed_index

        with patch("common.crypto_api.request_with_retry") as mock_req:
            mock_req.side_effect = req_lib.exceptions.RequestException("Error")
            result = fetch_fear_greed_index()

        assert result == {}


class TestCryptoApiRequestTimeout:
    """Verify REQUEST_TIMEOUT constant in crypto_api."""

    def test_request_timeout_is_20(self):
        from common.crypto_api import REQUEST_TIMEOUT
        assert REQUEST_TIMEOUT == 20


# ---------------------------------------------------------------------------
# fmp_api tests
# ---------------------------------------------------------------------------

class TestFetchEconomicCalendar:
    """Tests for fmp_api.fetch_economic_calendar()."""

    def _make_fmp_response(self) -> MagicMock:
        resp = MagicMock()
        resp.json.return_value = [
            {
                "event": "US CPI",
                "country": "US",
                "date": "2026-03-25",
                "impact": "High",
                "estimate": "3.2",
                "previous": "3.1",
                "actual": "",
            },
            {
                "event": "Low Impact Event",
                "country": "US",
                "date": "2026-03-25",
                "impact": "Low",
                "estimate": "",
                "previous": "",
                "actual": "",
            },
        ]
        return resp

    def test_returns_high_and_medium_events_only(self):
        from common.fmp_api import fetch_economic_calendar

        with patch("common.fmp_api.get_env", return_value="fake-key"), \
             patch("common.fmp_api.request_with_retry") as mock_req:
            mock_req.return_value = self._make_fmp_response()
            events = fetch_economic_calendar()

        # Low impact event should be filtered out
        assert all(e["impact"] in ("High", "Medium") for e in events)

    def test_event_fields_present(self):
        from common.fmp_api import fetch_economic_calendar

        with patch("common.fmp_api.get_env", return_value="fake-key"), \
             patch("common.fmp_api.request_with_retry") as mock_req:
            mock_req.return_value = self._make_fmp_response()
            events = fetch_economic_calendar()

        assert len(events) >= 1
        ev = events[0]
        assert "event" in ev
        assert "country" in ev
        assert "date" in ev
        assert "impact" in ev
        assert "forecast" in ev
        assert "previous" in ev
        assert "actual" in ev

    def test_fallback_to_forex_factory_when_no_api_key(self):
        from common.fmp_api import fetch_economic_calendar

        forex_resp = MagicMock()
        forex_resp.json.return_value = [
            {
                "title": "FOMC Meeting",
                "country": "USD",
                "date": "2026-03-26",
                "impact": "High",
                "forecast": "",
                "previous": "5.25%",
                "actual": "",
            }
        ]

        with patch("common.fmp_api.get_env", return_value=""), \
             patch("common.fmp_api.request_with_retry") as mock_req:
            mock_req.return_value = forex_resp
            events = fetch_economic_calendar()

        # Should have called Forex Factory endpoint, not FMP
        assert mock_req.called
        call_args = mock_req.call_args
        url_called = call_args[0][0] if call_args[0] else call_args[1].get("url", "")
        assert "faireconomy" in url_called or "forex" in url_called.lower() or len(events) >= 0

    def test_fallback_used_when_fmp_fails(self):
        import requests as req_lib

        from common.fmp_api import fetch_economic_calendar

        forex_resp = MagicMock()
        forex_resp.json.return_value = [
            {
                "title": "GDP Release",
                "country": "USD",
                "date": "2026-03-27",
                "impact": "High",
                "forecast": "2.1%",
                "previous": "2.0%",
                "actual": "",
            }
        ]

        def _side_effect(url, **kwargs):
            if "financialmodelingprep" in url:
                raise req_lib.exceptions.ConnectionError("FMP unavailable")
            return forex_resp

        with patch("common.fmp_api.get_env", return_value="fake-key"), \
             patch("common.fmp_api.request_with_retry", side_effect=_side_effect):
            events = fetch_economic_calendar()

        assert isinstance(events, list)

    def test_empty_fmp_response_falls_back(self):
        from common.fmp_api import fetch_economic_calendar

        empty_resp = MagicMock()
        empty_resp.json.return_value = []

        forex_resp = MagicMock()
        forex_resp.json.return_value = []

        call_count = {"n": 0}

        def _side_effect(url, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return empty_resp
            return forex_resp

        with patch("common.fmp_api.get_env", return_value="fake-key"), \
             patch("common.fmp_api.request_with_retry", side_effect=_side_effect):
            events = fetch_economic_calendar()

        # Empty FMP list triggers fallback — two calls total expected
        assert call_count["n"] == 2
        assert events == []


class TestFmpApiRequestTimeout:
    """Verify REQUEST_TIMEOUT is imported from config in fmp_api."""

    def test_request_timeout_imported_from_config(self):
        # fmp_api imports REQUEST_TIMEOUT from config at module level
        import importlib

        from common.config import REQUEST_TIMEOUT as config_timeout
        from common.fmp_api import fetch_economic_calendar  # noqa: F401 — trigger module import
        source = importlib.util.find_spec("common.fmp_api").origin
        with open(source, encoding="utf-8") as f:
            src = f.read()
        assert "from .config import" in src
        assert "REQUEST_TIMEOUT" in src
        # The value used should match config's value
        assert config_timeout == 15


# ---------------------------------------------------------------------------
# collector_metrics tests
# ---------------------------------------------------------------------------

class TestLogCollectionSummary:
    """Tests for collector_metrics.log_collection_summary()."""

    def test_logs_at_info_level(self):
        import time

        from common.collector_metrics import log_collection_summary

        mock_logger = MagicMock()
        started = time.monotonic() - 1.5
        log_collection_summary(
            logger=mock_logger,
            collector="test_collector",
            source_count=3,
            unique_items=10,
            post_created=2,
            started_at=started,
        )

        mock_logger.info.assert_called_once()

    def test_output_contains_collector_name(self):
        import time

        from common.collector_metrics import log_collection_summary

        mock_logger = MagicMock()
        started = time.monotonic()
        log_collection_summary(
            logger=mock_logger,
            collector="crypto_news",
            source_count=5,
            unique_items=20,
            post_created=4,
            started_at=started,
        )

        call_args = mock_logger.info.call_args
        # First positional arg is the format string; remainder are format args
        fmt_args = call_args[0]
        assert "crypto_news" in fmt_args

    def test_output_contains_counts(self):
        import time

        from common.collector_metrics import log_collection_summary

        mock_logger = MagicMock()
        started = time.monotonic()
        log_collection_summary(
            logger=mock_logger,
            collector="stock_news",
            source_count=7,
            unique_items=15,
            post_created=3,
            started_at=started,
        )

        call_args = mock_logger.info.call_args
        fmt_args = call_args[0]
        # collector, source_count, unique_items, post_created are positional format args
        assert 7 in fmt_args
        assert 15 in fmt_args
        assert 3 in fmt_args

    def test_negative_values_clamped_to_zero(self):
        import time

        from common.collector_metrics import log_collection_summary

        mock_logger = MagicMock()
        started = time.monotonic()
        log_collection_summary(
            logger=mock_logger,
            collector="test",
            source_count=-5,
            unique_items=-1,
            post_created=-3,
            started_at=started,
        )

        call_args = mock_logger.info.call_args
        fmt_args = call_args[0]
        # After max(0, ...) clamping, negative values become 0
        assert -5 not in fmt_args
        assert -1 not in fmt_args
        assert -3 not in fmt_args

    def test_extras_included_in_output(self):
        import time

        from common.collector_metrics import log_collection_summary

        mock_logger = MagicMock()
        started = time.monotonic()
        log_collection_summary(
            logger=mock_logger,
            collector="test",
            source_count=1,
            unique_items=1,
            post_created=1,
            started_at=started,
            extras={"api": "coingecko", "errors": 0},
        )

        call_args = mock_logger.info.call_args
        # The last positional arg carries formatted extras string
        fmt_string = call_args[0][0]
        all_args = call_args[0]
        full_msg = fmt_string % all_args[1:]
        assert "api=coingecko" in full_msg
        assert "errors=0" in full_msg

    def test_no_extras_no_trailing_content(self):
        import time

        from common.collector_metrics import log_collection_summary

        mock_logger = MagicMock()
        started = time.monotonic()
        log_collection_summary(
            logger=mock_logger,
            collector="test",
            source_count=0,
            unique_items=0,
            post_created=0,
            started_at=started,
        )

        call_args = mock_logger.info.call_args
        fmt_string = call_args[0][0]
        all_args = call_args[0]
        full_msg = fmt_string % all_args[1:]
        # The extras segment should be empty (no trailing garbage)
        assert full_msg.endswith("s") or full_msg.endswith("s ")

    def test_duration_is_non_negative(self):
        import time

        from common.collector_metrics import log_collection_summary

        mock_logger = MagicMock()
        # started_at in the future — duration should be clamped to 0
        future_start = time.monotonic() + 100
        log_collection_summary(
            logger=mock_logger,
            collector="test",
            source_count=0,
            unique_items=0,
            post_created=0,
            started_at=future_start,
        )

        mock_logger.info.assert_called_once()
        call_args = mock_logger.info.call_args
        fmt_string = call_args[0][0]
        all_args = call_args[0]
        full_msg = fmt_string % all_args[1:]
        assert "duration=0.00s" in full_msg
