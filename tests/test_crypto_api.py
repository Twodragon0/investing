"""Tests for crypto_api module (scripts/common/crypto_api.py)."""

from unittest.mock import MagicMock, patch

from common.crypto_api import (
    fetch_coingecko_global,
    fetch_coingecko_top_coins,
    fetch_coingecko_trending,
    fetch_fear_greed_index,
)


class TestFetchCoingeckoTopCoins:
    """Tests for fetch_coingecko_top_coins()."""

    @patch("common.crypto_api.request_with_retry")
    def test_returns_list(self, mock_req):
        mock_resp = MagicMock()
        mock_resp.json.return_value = [{"id": "bitcoin", "symbol": "btc"}]
        mock_req.return_value = mock_resp

        result = fetch_coingecko_top_coins()
        assert isinstance(result, list)
        assert len(result) == 1

    @patch("common.crypto_api.request_with_retry")
    def test_returns_data_from_api(self, mock_req):
        coins = [{"id": "bitcoin"}, {"id": "ethereum"}]
        mock_resp = MagicMock()
        mock_resp.json.return_value = coins
        mock_req.return_value = mock_resp

        result = fetch_coingecko_top_coins(limit=2)
        assert result == coins

    @patch("common.crypto_api.request_with_retry")
    def test_network_error_returns_empty(self, mock_req):
        import requests as req
        mock_req.side_effect = req.exceptions.ConnectionError("refused")

        result = fetch_coingecko_top_coins()
        assert result == []

    @patch("common.crypto_api.request_with_retry")
    def test_request_exception_returns_empty(self, mock_req):
        import requests as req
        mock_req.side_effect = req.exceptions.Timeout("timed out")

        result = fetch_coingecko_top_coins()
        assert result == []

    @patch("common.crypto_api.request_with_retry")
    def test_empty_response_returns_empty_list(self, mock_req):
        mock_resp = MagicMock()
        mock_resp.json.return_value = []
        mock_req.return_value = mock_resp

        result = fetch_coingecko_top_coins()
        assert result == []


class TestFetchCoingeckoTrending:
    """Tests for fetch_coingecko_trending()."""

    @patch("common.crypto_api.request_with_retry")
    def test_returns_coins_list(self, mock_req):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "coins": [{"item": {"id": "pepe", "symbol": "PEPE"}}]
        }
        mock_req.return_value = mock_resp

        result = fetch_coingecko_trending()
        assert isinstance(result, list)
        assert len(result) == 1

    @patch("common.crypto_api.request_with_retry")
    def test_missing_coins_key_returns_empty(self, mock_req):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {}
        mock_req.return_value = mock_resp

        result = fetch_coingecko_trending()
        assert result == []

    @patch("common.crypto_api.request_with_retry")
    def test_network_error_returns_empty(self, mock_req):
        import requests as req
        mock_req.side_effect = req.exceptions.ConnectionError("refused")

        result = fetch_coingecko_trending()
        assert result == []

    @patch("common.crypto_api.request_with_retry")
    def test_multiple_trending_coins(self, mock_req):
        coins = [{"item": {"id": f"coin{i}"}} for i in range(5)]
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"coins": coins}
        mock_req.return_value = mock_resp

        result = fetch_coingecko_trending()
        assert len(result) == 5


class TestFetchCoingeckoGlobal:
    """Tests for fetch_coingecko_global()."""

    @patch("common.crypto_api.request_with_retry")
    def test_returns_dict(self, mock_req):
        global_data = {"total_market_cap": {"usd": 2_000_000_000_000}}
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": global_data}
        mock_req.return_value = mock_resp

        result = fetch_coingecko_global()
        assert isinstance(result, dict)
        assert "total_market_cap" in result

    @patch("common.crypto_api.request_with_retry")
    def test_missing_data_key_returns_empty(self, mock_req):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {}
        mock_req.return_value = mock_resp

        result = fetch_coingecko_global()
        assert result == {}

    @patch("common.crypto_api.request_with_retry")
    def test_network_error_returns_empty(self, mock_req):
        import requests as req
        mock_req.side_effect = req.exceptions.ConnectionError("refused")

        result = fetch_coingecko_global()
        assert result == {}

    @patch("common.crypto_api.request_with_retry")
    def test_timeout_returns_empty(self, mock_req):
        import requests as req
        mock_req.side_effect = req.exceptions.Timeout("timed out")

        result = fetch_coingecko_global()
        assert result == {}


class TestFetchFearGreedIndex:
    """Tests for fetch_fear_greed_index()."""

    @patch("common.crypto_api.request_with_retry")
    def test_returns_current_value(self, mock_req):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "data": [{"value": "75", "value_classification": "Greed"}]
        }
        mock_req.return_value = mock_resp

        result = fetch_fear_greed_index()
        assert result["value"] == 75
        assert result["classification"] == "Greed"

    @patch("common.crypto_api.request_with_retry")
    def test_with_history_includes_prev(self, mock_req):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "data": [
                {"value": "75", "value_classification": "Greed"},
                {"value": "60", "value_classification": "Fear"},
            ]
        }
        mock_req.return_value = mock_resp

        result = fetch_fear_greed_index(history_days=2)
        assert result["value"] == 75
        assert result["prev_value"] == 60
        assert result["prev_classification"] == "Fear"

    @patch("common.crypto_api.request_with_retry")
    def test_single_entry_no_prev(self, mock_req):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "data": [{"value": "50", "value_classification": "Neutral"}]
        }
        mock_req.return_value = mock_resp

        result = fetch_fear_greed_index()
        assert "prev_value" not in result

    @patch("common.crypto_api.request_with_retry")
    def test_empty_data_returns_empty(self, mock_req):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": []}
        mock_req.return_value = mock_resp

        result = fetch_fear_greed_index()
        assert result == {}

    @patch("common.crypto_api.request_with_retry")
    def test_network_error_returns_empty(self, mock_req):
        import requests as req
        mock_req.side_effect = req.exceptions.ConnectionError("refused")

        result = fetch_fear_greed_index()
        assert result == {}

    @patch("common.crypto_api.request_with_retry")
    def test_value_is_int(self, mock_req):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "data": [{"value": "42", "value_classification": "Fear"}]
        }
        mock_req.return_value = mock_resp

        result = fetch_fear_greed_index()
        assert isinstance(result["value"], int)
