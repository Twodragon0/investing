"""Tests for collect_defi_llama collector."""

import importlib
import os
import sys
from datetime import UTC, datetime
from unittest.mock import patch

SCRIPTS_DIR = os.path.join(os.path.dirname(__file__), "..", "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)


# ---------------------------------------------------------------------------
# Pure-logic tests (no network)
# ---------------------------------------------------------------------------


def test_format_tvl_billions():
    mod = importlib.import_module("collect_defi_llama")
    assert mod._format_tvl(2_500_000_000) == "$2.50B"


def test_format_tvl_millions():
    mod = importlib.import_module("collect_defi_llama")
    assert mod._format_tvl(123_456_789) == "$123.5M"


def test_format_tvl_thousands():
    mod = importlib.import_module("collect_defi_llama")
    assert mod._format_tvl(9_500) == "$9.5K"


def test_format_mcap_none():
    mod = importlib.import_module("collect_defi_llama")
    assert mod._format_mcap(None) == "N/A"


def test_korean_ro_vowel_ending():
    mod = importlib.import_module("collect_defi_llama")
    # English word ending in vowel -> '로'
    assert mod._korean_ro("Aave") == "로"


def test_korean_ro_consonant_ending():
    mod = importlib.import_module("collect_defi_llama")
    # English word ending in consonant -> '으로'
    assert mod._korean_ro("Lido") == "로"
    assert mod._korean_ro("Uniswap") == "으로"


def test_build_post_content_contains_key_sections():
    mod = importlib.import_module("collect_defi_llama")
    protocols = [
        {"name": "Lido", "tvl": 20_000_000_000, "category": "Liquid Staking", "symbol": "LDO", "mcap": 1e9},
        {"name": "Aave", "tvl": 10_000_000_000, "category": "Lending", "symbol": "AAVE", "mcap": 5e8},
    ]
    chains = [
        {"name": "Ethereum", "tvl": 55_000_000_000, "tokenSymbol": "ETH"},
        {"name": "BSC", "tvl": 8_000_000_000, "tokenSymbol": "BNB"},
    ]
    now = datetime(2026, 4, 11, 10, 0, tzinfo=UTC)
    content = mod.build_post_content(protocols, chains, "2026-04-11", now, chart_path=None)
    assert "Lido" in content
    assert "Ethereum" in content
    assert "TVL" in content
    assert "DeFi" in content


def test_build_post_content_empty_data():
    mod = importlib.import_module("collect_defi_llama")
    now = datetime(2026, 4, 11, 10, 0, tzinfo=UTC)
    content = mod.build_post_content([], [], "2026-04-11", now, chart_path=None)
    assert isinstance(content, str)


# ---------------------------------------------------------------------------
# Network-mocked tests
# ---------------------------------------------------------------------------


def test_fetch_protocols_excludes_cex():
    """fetch_protocols() must filter out CEX-category entries."""
    mod = importlib.import_module("collect_defi_llama")
    from unittest.mock import MagicMock

    fake_data = [
        {"name": "Binance", "tvl": 153_000_000_000, "category": "CEX", "symbol": "BNB", "mcap": None},
        {"name": "OKX", "tvl": 10_000_000_000, "category": "cex", "symbol": "OKB", "mcap": None},
        {"name": "Lido", "tvl": 21_000_000_000, "category": "Liquid Staking", "symbol": "LDO", "mcap": 1e9},
        {"name": "Aave", "tvl": 10_000_000_000, "category": "Lending", "symbol": "AAVE", "mcap": 5e8},
    ]

    mock_resp = MagicMock()
    mock_resp.json.return_value = fake_data

    with patch("collect_defi_llama.request_with_retry", return_value=mock_resp):
        result = mod.fetch_protocols()

    names = [p["name"] for p in result]
    assert "Binance" not in names, "CEX protocol must be excluded"
    assert "OKX" not in names, "CEX protocol (lowercase) must be excluded"
    assert "Lido" in names
    assert "Aave" in names


def test_fetch_protocols_uses_v1_endpoint():
    """fetch_protocols() must call /protocols (v1), not /v2/protocols."""
    mod = importlib.import_module("collect_defi_llama")
    from unittest.mock import MagicMock

    mock_resp = MagicMock()
    mock_resp.json.return_value = []

    with patch("collect_defi_llama.request_with_retry", return_value=mock_resp) as mock_req:
        mod.fetch_protocols()

    called_url = mock_req.call_args[0][0]
    assert "/v2/protocols" not in called_url, "Must not use deprecated /v2/protocols"
    assert called_url.endswith("/protocols"), f"Must use /protocols endpoint, got: {called_url}"


def test_fetch_protocols_returns_empty_on_request_error():
    mod = importlib.import_module("collect_defi_llama")
    import requests

    # Patch the name as it exists in the collect_defi_llama module namespace
    with patch("collect_defi_llama.request_with_retry", side_effect=requests.exceptions.ConnectionError("offline")):
        result = mod.fetch_protocols()
    assert result == []


def test_fetch_chains_returns_empty_on_request_error():
    mod = importlib.import_module("collect_defi_llama")
    import requests

    with patch("collect_defi_llama.request_with_retry", side_effect=requests.exceptions.ConnectionError("offline")):
        result = mod.fetch_chains()
    assert result == []


def test_collector_run_no_network(tmp_path, monkeypatch):
    """DefiLlamaCollector.run() completes without raising when APIs return empty."""
    mod = importlib.import_module("collect_defi_llama")

    monkeypatch.setattr(mod, "fetch_protocols", list)
    monkeypatch.setattr(mod, "fetch_chains", list)
    monkeypatch.setattr(mod, "generate_tvl_chart_image", lambda *a, **kw: None)

    from common import post_generator as pg_mod

    monkeypatch.setattr(pg_mod, "POSTS_DIR", str(tmp_path))

    collector = mod.DefiLlamaCollector()
    collector.run()


def test_dedup_idempotent_defi_llama(tmp_path, monkeypatch):
    """Running DefiLlamaCollector twice with same data creates no extra posts."""
    mod = importlib.import_module("collect_defi_llama")

    fake_protocols = [
        {"name": "Lido", "tvl": 20_000_000_000, "category": "Liquid Staking", "symbol": "LDO", "mcap": 1e9},
    ]
    fake_chains = [
        {"name": "Ethereum", "tvl": 55_000_000_000, "tokenSymbol": "ETH"},
    ]

    monkeypatch.setattr(mod, "fetch_protocols", lambda: fake_protocols)
    monkeypatch.setattr(mod, "fetch_chains", lambda: fake_chains)
    monkeypatch.setattr(mod, "generate_tvl_chart_image", lambda *a, **kw: None)
    # Suppress TVL staleness file writes (uses _state/ which may not exist in tmp_path)
    monkeypatch.setattr(mod, "_check_tvl_staleness", lambda *a, **kw: None)

    from common import post_generator as pg_mod

    monkeypatch.setattr(pg_mod, "POSTS_DIR", str(tmp_path))

    c1 = mod.DefiLlamaCollector()
    c1.run()
    posts_after_first = list(tmp_path.glob("*.md"))

    c2 = mod.DefiLlamaCollector()
    c2.dedup = c1.dedup
    c2.run()
    posts_after_second = list(tmp_path.glob("*.md"))

    assert len(posts_after_second) == len(posts_after_first)


# ---------------------------------------------------------------------------
# V1_MIGRATION_DATE annotation tests
# ---------------------------------------------------------------------------


def test_v1_migration_date_constant_exists():
    """V1_MIGRATION_DATE 상수가 모듈에 정의되어 있어야 한다."""
    mod = importlib.import_module("collect_defi_llama")
    assert hasattr(mod, "V1_MIGRATION_DATE"), "V1_MIGRATION_DATE 상수가 없습니다"
    assert mod.V1_MIGRATION_DATE == "2026-04-20"


def test_generate_tvl_chart_annotation_text(monkeypatch):
    """generate_tvl_chart_image()가 V1_MIGRATION_DATE annotation 텍스트를 차트에 추가해야 한다."""
    import importlib.util

    import pytest

    mod = importlib.import_module("collect_defi_llama")

    if importlib.util.find_spec("matplotlib") is None:
        pytest.skip("matplotlib not available")

    import matplotlib.pyplot as _plt

    import common.image_generator as _ig

    protocols = [{"name": "Lido", "tvl": 20_000_000_000, "category": "Liquid Staking", "symbol": "LDO", "mcap": 1e9}]
    chains = [{"name": "Ethereum", "tvl": 55_000_000_000, "tokenSymbol": "ETH"}]

    texts_seen = []

    class _CapturingAxes:
        """ax.text 호출 결과를 수집하는 래퍼."""

        def __init__(self, real_ax):
            self._ax = real_ax

        def __getattr__(self, name):
            if name == "text":

                def _text(*args, **kwargs):
                    if args:
                        texts_seen.append(str(args[2]) if len(args) > 2 else "")
                    return self._ax.text(*args, **kwargs)

                return _text
            return getattr(self._ax, name)

    _orig_subplots = _plt.subplots

    def _mock_subplots(*args, **kwargs):
        real_fig, real_ax = _orig_subplots(*args, **kwargs)
        return real_fig, _CapturingAxes(real_ax)

    monkeypatch.setattr(_plt, "subplots", _mock_subplots)
    monkeypatch.setattr(_ig, "_save_and_close", lambda *a, **kw: None)

    mod.generate_tvl_chart_image(protocols, chains, "2026-04-21")

    migration_label = mod.V1_MIGRATION_DATE
    found = any(migration_label in t for t in texts_seen)
    assert found, (
        f"차트 텍스트에서 V1_MIGRATION_DATE({migration_label})를 찾을 수 없습니다. 수집된 텍스트: {texts_seen}"
    )
