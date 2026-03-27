"""Tests for blockchain_api module — mock-based API response tests."""

from unittest.mock import MagicMock, patch


def _make_response(data: dict, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = data
    return resp


# ---------------------------------------------------------------------------
# fetch_btc_stats tests
# ---------------------------------------------------------------------------


class TestFetchBtcStats:
    def test_returns_parsed_stats(self):
        from common.blockchain_api import fetch_btc_stats

        mock_stats = {
            "hash_rate": 1077444735215.0,  # GH/s
            "difficulty": 133793147307542,
            "n_tx": 584087,
            "minutes_between_blocks": 8.23,
            "n_blocks_total": 942291,
            "market_price_usd": 70898.0,
            "trade_volume_usd": 5000000000.0,
        }
        mock_mempool = {"values": [{"x": 1, "y": 12500}]}

        call_count = {"n": 0}

        def _side_effect(url, **kwargs):
            call_count["n"] += 1
            if "mempool" in url:
                return _make_response(mock_mempool)
            return _make_response(mock_stats)

        with patch("common.blockchain_api.request_with_retry", side_effect=_side_effect):
            result = fetch_btc_stats()

        assert result["hash_rate_ehs"] == round(1077444735215.0 / 1e9, 1)
        assert result["difficulty"] == 133793147307542
        assert result["n_tx"] == 584087
        assert result["block_time_min"] == 8.2
        assert result["blocks_total"] == 942291
        assert result["market_price_usd"] == 70898.0
        assert result["mempool_size"] == 12500

    def test_returns_empty_on_failure(self):
        from common.blockchain_api import fetch_btc_stats

        with patch(
            "common.blockchain_api.request_with_retry",
            side_effect=Exception("Connection error"),
        ):
            result = fetch_btc_stats()

        assert result == {}

    def test_mempool_failure_graceful(self):
        from common.blockchain_api import fetch_btc_stats

        mock_stats = {
            "hash_rate": 500000000000.0,
            "difficulty": 100000000000000,
            "n_tx": 300000,
            "minutes_between_blocks": 10.0,
            "n_blocks_total": 900000,
            "market_price_usd": 50000.0,
            "trade_volume_usd": 3000000000.0,
        }

        def _side_effect(url, **kwargs):
            if "mempool" in url:
                raise Exception("Mempool API down")
            return _make_response(mock_stats)

        with patch("common.blockchain_api.request_with_retry", side_effect=_side_effect):
            result = fetch_btc_stats()

        assert result["n_tx"] == 300000
        assert result["mempool_size"] == 0  # graceful fallback


# ---------------------------------------------------------------------------
# fetch_eth_stats tests
# ---------------------------------------------------------------------------


class TestFetchEthStats:
    def test_returns_gas_and_supply(self):
        from common.blockchain_api import fetch_eth_stats

        gas_resp = {
            "status": "1",
            "result": {
                "SafeGasPrice": "5",
                "ProposeGasPrice": "8",
                "FastGasPrice": "12",
            },
        }
        supply_resp = {
            "status": "1",
            "result": "120500000000000000000000000",  # 120.5M ETH in Wei
        }
        price_resp = {
            "status": "1",
            "result": {"ethusd": "2169.38", "ethbtc": "0.0306"},
        }

        call_count = {"n": 0}

        def _side_effect(url, **kwargs):
            call_count["n"] += 1
            params = kwargs.get("params", {})
            action = params.get("action", "")
            if action == "gasoracle":
                return _make_response(gas_resp)
            elif action == "ethsupply":
                return _make_response(supply_resp)
            elif action == "ethprice":
                return _make_response(price_resp)
            return _make_response({"status": "0"})

        with patch("common.blockchain_api.request_with_retry", side_effect=_side_effect):
            result = fetch_eth_stats()

        assert result["gas_safe"] == "5"
        assert result["gas_propose"] == "8"
        assert result["gas_fast"] == "12"
        assert result["eth_supply"] == 120500000.0
        assert result["eth_price_usd"] == 2169.38
        assert result["eth_price_btc"] == 0.0306

    def test_returns_empty_on_failure(self):
        from common.blockchain_api import fetch_eth_stats

        with patch(
            "common.blockchain_api.request_with_retry",
            side_effect=Exception("API error"),
        ):
            result = fetch_eth_stats()

        assert result == {}

    def test_partial_data_when_some_calls_fail(self):
        from common.blockchain_api import fetch_eth_stats

        gas_resp = {
            "status": "1",
            "result": {
                "SafeGasPrice": "10",
                "ProposeGasPrice": "15",
                "FastGasPrice": "20",
            },
        }

        def _side_effect(url, **kwargs):
            params = kwargs.get("params", {})
            action = params.get("action", "")
            if action == "gasoracle":
                return _make_response(gas_resp)
            # Other calls return error status
            return _make_response({"status": "0", "message": "NOTOK"})

        with patch("common.blockchain_api.request_with_retry", side_effect=_side_effect):
            result = fetch_eth_stats()

        assert result["gas_safe"] == "10"
        assert "eth_supply" not in result
        assert "eth_price_usd" not in result


# ---------------------------------------------------------------------------
# fetch_l2_summary tests
# ---------------------------------------------------------------------------


class TestFetchL2Summary:
    def test_returns_top_projects(self):
        from common.blockchain_api import fetch_l2_summary

        mock_data = {
            "data": {
                "projects": [
                    {"name": "Arbitrum One", "slug": "arbitrum", "tvl": {"value": 18500000000}, "stage": "Stage 1"},
                    {"name": "Base", "slug": "base", "tvl": {"value": 12100000000}, "stage": "Stage 0"},
                    {"name": "Optimism", "slug": "optimism", "tvl": {"value": 7800000000}, "stage": "Stage 1"},
                ]
            }
        }

        with patch("common.blockchain_api.request_with_retry", return_value=_make_response(mock_data)):
            result = fetch_l2_summary()

        assert len(result) == 3
        assert result[0]["name"] == "Arbitrum One"
        assert result[0]["tvl"] == 18500000000
        assert result[0]["stage"] == "Stage 1"

    def test_returns_empty_on_failure(self):
        from common.blockchain_api import fetch_l2_summary

        with patch(
            "common.blockchain_api.request_with_retry",
            side_effect=Exception("Network error"),
        ):
            result = fetch_l2_summary()

        assert result == []

    def test_returns_empty_when_no_projects(self):
        from common.blockchain_api import fetch_l2_summary

        with patch(
            "common.blockchain_api.request_with_retry",
            return_value=_make_response({"data": {"projects": []}}),
        ):
            result = fetch_l2_summary()

        assert result == []

    def test_limits_to_10_projects(self):
        from common.blockchain_api import fetch_l2_summary

        projects = [
            {"name": f"L2-{i}", "slug": f"l2-{i}", "tvl": {"value": 1000000 * i}, "stage": ""}
            for i in range(20)
        ]
        mock_data = {"data": {"projects": projects}}

        with patch("common.blockchain_api.request_with_retry", return_value=_make_response(mock_data)):
            result = fetch_l2_summary()

        assert len(result) == 10


# ---------------------------------------------------------------------------
# build_report_content tests
# ---------------------------------------------------------------------------


class TestBuildReportContent:
    def test_btc_only(self):
        from collect_blockchain import build_report_content

        btc = {
            "hash_rate_ehs": 1064.1,
            "difficulty": 133793147307542,
            "n_tx": 576247,
            "block_time_min": 8.3,
            "blocks_total": 942291,
            "market_price_usd": 70050.0,
            "mempool_size": 0,
        }
        content, desc, excerpt = build_report_content(btc, {}, "2026-03-27")
        assert "Bitcoin 네트워크 현황" in content
        assert "1.06 ZH/s" in content
        assert "BTC 해시레이트" in desc

    def test_btc_and_eth(self):
        from collect_blockchain import build_report_content

        btc = {"hash_rate_ehs": 500.0, "difficulty": 1e14, "n_tx": 400000, "block_time_min": 10.0, "blocks_total": 900000}
        eth = {"gas_safe": "5", "gas_propose": "8", "gas_fast": "12", "eth_supply": 120500000.0, "eth_price_usd": 2100.0}
        content, desc, excerpt = build_report_content(btc, eth, "2026-03-27")
        assert "Ethereum 네트워크 현황" in content
        assert "8.00 Gwei" in content
        assert "ETH 가스" in desc

    def test_with_l2_projects(self):
        from collect_blockchain import build_report_content

        btc = {"hash_rate_ehs": 500.0, "difficulty": 1e14, "n_tx": 400000, "block_time_min": 10.0, "blocks_total": 900000}
        l2 = [
            {"name": "Arbitrum One", "tvl": 18500000000, "stage": "Stage 1"},
            {"name": "Base", "tvl": 12100000000, "stage": "Stage 0"},
        ]
        content, _, _ = build_report_content(btc, {}, "2026-03-27", l2_projects=l2)
        assert "Layer 2 네트워크 활동" in content
        assert "Arbitrum One" in content
        assert "L2Beat" in content

    def test_empty_data(self):
        from collect_blockchain import build_report_content

        content, desc, _ = build_report_content({}, {}, "2026-03-27")
        assert "데이터를 가져올 수 없습니다" in content
        assert "블록체인 네트워크 일일 리포트" in desc

    def test_fast_block_time_insight(self):
        from collect_blockchain import build_report_content

        btc = {"hash_rate_ehs": 1000.0, "difficulty": 1e14, "n_tx": 500000, "block_time_min": 7.5, "blocks_total": 950000}
        content, _, _ = build_report_content(btc, {}, "2026-03-27")
        assert "목표(10분)보다 빠르며" in content

    def test_slow_block_time_insight(self):
        from collect_blockchain import build_report_content

        btc = {"hash_rate_ehs": 800.0, "difficulty": 1e14, "n_tx": 500000, "block_time_min": 12.0, "blocks_total": 950000}
        content, _, _ = build_report_content(btc, {}, "2026-03-27")
        assert "목표(10분)보다 느리며" in content

    def test_high_gas_insight(self):
        from collect_blockchain import build_report_content

        eth = {"gas_safe": "80", "gas_propose": "100", "gas_fast": "150"}
        content, _, _ = build_report_content({}, eth, "2026-03-27")
        assert "혼잡 상태" in content

    def test_low_gas_insight(self):
        from collect_blockchain import build_report_content

        eth = {"gas_safe": "2", "gas_propose": "3", "gas_fast": "5"}
        content, _, _ = build_report_content({}, eth, "2026-03-27")
        assert "한산합니다" in content
