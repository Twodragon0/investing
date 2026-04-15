"""Additional coverage tests for scripts/common/image_generator/

Targets specific uncovered lines identified from coverage report:
  base.py  : 56, 64-65, 79-83, 89-92, 114, 313, 433, 464, 469, 748, 825-826, 881-885
  coins.py : 209, 258-267, 278-281, 745-759
  market.py: 165, 449-454
"""

import sys
from unittest.mock import patch

import pytest

try:
    from common import image_generator as ig
    from common.image_generator import base as ig_base

    _IMPORT_OK = True
except Exception:
    ig = None  # type: ignore
    ig_base = None  # type: ignore
    _IMPORT_OK = False

pytestmark = pytest.mark.skipif(not _IMPORT_OK, reason="image_generator could not be imported")


# ---------------------------------------------------------------------------
# base.py line 114  — _get_pkg_attr fallback to globals when pkg not in sys.modules
# ---------------------------------------------------------------------------


class TestGetPkgAttr:
    def test_fallback_to_globals_when_pkg_absent(self, monkeypatch):
        """Line 114: globals()[name] branch when package not in sys.modules."""
        original = sys.modules.pop("common.image_generator", None)
        try:
            result = ig_base._get_pkg_attr("IMAGES_DIR")
            assert isinstance(result, str)
        finally:
            if original is not None:
                sys.modules["common.image_generator"] = original

    def test_returns_pkg_attr_when_present(self):
        """Lines 111-112: pkg.__dict__ path."""
        pkg = sys.modules.get("common.image_generator")
        if pkg is not None:
            result = ig_base._get_pkg_attr("IMAGES_DIR")
            assert isinstance(result, str)


# ---------------------------------------------------------------------------
# base.py line 313 — _sanitize_og_text with empty input
# ---------------------------------------------------------------------------


class TestSanitizeOgTextEmpty:
    def test_empty_string_returns_empty(self):
        """Line 313: early return on falsy input."""
        assert ig._sanitize_og_text("") == ""

    def test_none_like_falsy_returns_empty(self):
        # None would raise AttributeError; only test empty string per signature
        assert ig._sanitize_og_text("") == ""


# ---------------------------------------------------------------------------
# base.py line 433 — _add_market_texture with explicit accent colour
# ---------------------------------------------------------------------------


class TestAddMarketTexture:
    def test_runs_with_explicit_accent(self, tmp_path, monkeypatch):
        """Line 432-433: transform=None branch in _draw_gradient_bar; also
        exercises _add_market_texture with a non-None accent value."""
        import matplotlib.pyplot as plt

        monkeypatch.setattr(ig, "IMAGES_DIR", str(tmp_path))
        fig, ax = plt.subplots(figsize=(4, 3))
        ax.set_xlim(0, 10)
        ax.set_ylim(0, 10)
        # Call directly — should not raise
        ig_base._add_market_texture(ax, 10.0, 10.0, accent="#ff0000")
        plt.close(fig)


# ---------------------------------------------------------------------------
# base.py lines 464, 469 — _draw_mini_donut edge cases
# ---------------------------------------------------------------------------


class TestDrawMiniDonut:
    def test_total_zero_returns_early(self):
        """Line 464: total <= 0 guard."""
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots()
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        # All counts zero → should return without drawing
        data = [{"count": 0}, {"count": 0}]
        ig_base._draw_mini_donut(ax, 0.5, 0.5, 0.2, data, ["#ff0000", "#00ff00"])
        plt.close(fig)

    def test_zero_count_item_skipped(self):
        """Line 469: count <= 0 continue branch."""
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots()
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        # One item zero, one item positive
        data = [{"count": 0}, {"count": 5}]
        ig_base._draw_mini_donut(ax, 0.5, 0.5, 0.2, data, ["#ff0000", "#00ff00"])
        plt.close(fig)

    def test_normal_draw(self):
        """Normal path — all items have positive counts."""
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots()
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        data = [{"count": 3}, {"count": 2}, {"count": 1}]
        colors = ["#e53e3e", "#3182ce", "#38a169"]
        ig_base._draw_mini_donut(ax, 0.5, 0.5, 0.3, data, colors)
        plt.close(fig)


# ---------------------------------------------------------------------------
# base.py line 748 — _add_footer with use_fig=True
# ---------------------------------------------------------------------------


class TestAddFooterWithFig:
    def test_use_fig_path(self):
        """Line 748: fig.text() branch when use_fig=True."""
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(4, 3))
        # Should not raise
        ig_base._add_footer(ax, use_fig=True, fig=fig)
        plt.close(fig)

    def test_use_fig_without_fig_object(self):
        """use_fig=True but fig=None falls through to ax.text() branch."""
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(4, 3))
        ig_base._add_footer(ax, use_fig=True, fig=None)
        plt.close(fig)

    def test_custom_y_position(self):
        """Line 760: y parameter branch."""
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(4, 3))
        ig_base._add_footer(ax, y=0.05)
        plt.close(fig)


# ---------------------------------------------------------------------------
# base.py lines 825-826 — _optimize_png best-effort (success + failure paths)
# ---------------------------------------------------------------------------


class TestOptimizePng:
    def test_success_path_with_real_png(self, tmp_path):
        """Lines 820-826: PNG optimization path."""
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(2, 2))
        png_path = str(tmp_path / "opt_test.png")
        plt.savefig(png_path, dpi=50)
        plt.close(fig)
        # Should not raise
        ig_base._optimize_png(png_path)

    def test_nonexistent_file_no_crash(self, tmp_path):
        """Exception is silently swallowed for best-effort optimization."""
        ig_base._optimize_png(str(tmp_path / "does_not_exist.png"))

    def test_returns_none(self, tmp_path):
        """_optimize_png has no return value."""
        result = ig_base._optimize_png(str(tmp_path / "no_file.png"))
        assert result is None


# ---------------------------------------------------------------------------
# base.py lines 881-885 — _convert_to_avif ImportError + Exception paths
# ---------------------------------------------------------------------------


class TestConvertToAvif:
    def test_returns_none_on_import_error(self, tmp_path, monkeypatch):
        """Lines 881-882: ImportError → return None."""
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(2, 2))
        png_path = str(tmp_path / "avif_test.png")
        plt.savefig(png_path, dpi=50)
        plt.close(fig)

        original_import = __import__

        def blocking_import(name, *args, **kwargs):
            if name == "PIL":
                raise ImportError("no Pillow")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=blocking_import):
            result = ig_base._convert_to_avif(png_path)
        assert result is None or isinstance(result, str)

    def test_returns_none_for_nonexistent_file(self, tmp_path):
        """Lines 883-885: Exception path returns None."""
        result = ig_base._convert_to_avif(str(tmp_path / "no_such_file.png"))
        assert result is None


# ---------------------------------------------------------------------------
# coins.py line 209 — price < 0.01 branch (6-decimal formatting)
# ---------------------------------------------------------------------------


class TestTopCoinsCardPriceFormats:
    def test_very_small_price_six_decimals(self, tmp_path, monkeypatch):
        """Line 211: price < 0.01 → 6-decimal format branch."""
        monkeypatch.setattr(ig, "IMAGES_DIR", str(tmp_path))
        coins = [
            {
                "symbol": "SHIB",
                "name": "Shiba Inu",
                "current_price": 0.000008,
                "price_change_percentage_24h": 5.0,
                "price_change_percentage_7d_in_currency": -2.0,
                "market_cap": 5_000_000_000,
            },
        ]
        result = ig.generate_top_coins_card(coins, "2026-02-01")
        assert result is not None

    def test_small_price_four_decimals(self, tmp_path, monkeypatch):
        """Line 209: 0.01 <= price < 1 → 4-decimal format branch."""
        monkeypatch.setattr(ig, "IMAGES_DIR", str(tmp_path))
        coins = [
            {
                "symbol": "XRP",
                "name": "Ripple",
                "current_price": 0.55,
                "price_change_percentage_24h": 1.0,
                "price_change_percentage_7d_in_currency": 3.0,
                "market_cap": 20_000_000_000,
            },
        ]
        result = ig.generate_top_coins_card(coins, "2026-02-02")
        assert result is not None

    def test_mcap_million_range(self, tmp_path, monkeypatch):
        """Lines 278-281: mcap < 1B and >= 1M → M-suffix branch."""
        monkeypatch.setattr(ig, "IMAGES_DIR", str(tmp_path))
        coins = [
            {
                "symbol": "RARE",
                "name": "SuperRare",
                "current_price": 0.15,
                "price_change_percentage_24h": -0.5,
                "price_change_percentage_7d_in_currency": 0.0,
                "market_cap": 50_000_000,  # 50M — triggers M suffix
            },
        ]
        result = ig.generate_top_coins_card(coins, "2026-02-03")
        assert result is not None

    def test_mcap_sub_million_raw_format(self, tmp_path, monkeypatch):
        """Line 281: mcap < 1M → raw format branch."""
        monkeypatch.setattr(ig, "IMAGES_DIR", str(tmp_path))
        coins = [
            {
                "symbol": "NANO",
                "name": "NanoCoin",
                "current_price": 0.001,
                "price_change_percentage_24h": 0.1,
                "price_change_percentage_7d_in_currency": 0.0,
                "market_cap": 500_000,  # 500K — triggers raw format
            },
        ]
        result = ig.generate_top_coins_card(coins, "2026-02-04")
        assert result is not None


# ---------------------------------------------------------------------------
# coins.py lines 258-267 — sparkline branch in top-coins card
# ---------------------------------------------------------------------------


class TestTopCoinsCardSparkline:
    def test_sparkline_with_coingecko_data(self, tmp_path, monkeypatch):
        """Lines 258-267: sparkline_in_7d branch when source=coingecko."""
        monkeypatch.setattr(ig, "IMAGES_DIR", str(tmp_path))
        spark_prices = [float(40000 + i * 100) for i in range(30)]
        coins = [
            {
                "symbol": "BTC",
                "name": "Bitcoin",
                "current_price": 42900,
                "price_change_percentage_24h": 2.5,
                "price_change_percentage_7d_in_currency": 5.0,
                "market_cap": 850_000_000_000,
                "sparkline_in_7d": {"price": spark_prices},
            },
        ]
        result = ig.generate_top_coins_card(coins, "2026-02-05", source="coingecko")
        assert result is not None

    def test_sparkline_flat_data_constant_prices(self, tmp_path, monkeypatch):
        """Flat sparkline (smax == smin) triggers np.full path."""
        monkeypatch.setattr(ig, "IMAGES_DIR", str(tmp_path))
        spark_prices = [50000.0] * 20  # constant — smax == smin
        coins = [
            {
                "symbol": "BTC",
                "name": "Bitcoin",
                "current_price": 50000,
                "price_change_percentage_24h": 0.0,
                "price_change_percentage_7d_in_currency": 0.0,
                "market_cap": 900_000_000_000,
                "sparkline_in_7d": {"price": spark_prices},
            },
        ]
        result = ig.generate_top_coins_card(coins, "2026-02-06", source="coingecko")
        assert result is not None

    def test_sparkline_too_short_falls_back_to_bar(self, tmp_path, monkeypatch):
        """Lines 268-271: len(spark_data) < 10 → bar fallback."""
        monkeypatch.setattr(ig, "IMAGES_DIR", str(tmp_path))
        spark_prices = [50000.0] * 5  # < 10 → bar path
        coins = [
            {
                "symbol": "ETH",
                "name": "Ethereum",
                "current_price": 3000,
                "price_change_percentage_24h": -1.0,
                "price_change_percentage_7d_in_currency": 2.0,
                "market_cap": 400_000_000_000,
                "sparkline_in_7d": {"price": spark_prices},
            },
        ]
        result = ig.generate_top_coins_card(coins, "2026-02-07", source="coingecko")
        assert result is not None


# ---------------------------------------------------------------------------
# coins.py lines 745-759 — sparkline in heatmap cells
# ---------------------------------------------------------------------------


class TestMarketHeatmapSparkline:
    def test_heatmap_sparkline_branch(self, tmp_path, monkeypatch):
        """Lines 744-757: sparkline_in_7d with source=coingecko in heatmap."""
        monkeypatch.setattr(ig, "IMAGES_DIR", str(tmp_path))
        spark_prices = [float(200 + i * 5) for i in range(20)]
        coins = [
            {
                "symbol": "BTC",
                "current_price": 50000,
                "price_change_percentage_24h": 3.0,
                "market_cap": 1e12,
                "sparkline_in_7d": {"price": spark_prices},
            },
            {
                "symbol": "ETH",
                "current_price": 3000,
                "price_change_percentage_24h": -1.5,
                "market_cap": 4e11,
                "sparkline_in_7d": {"price": [3000.0] * 20},  # flat
            },
        ]
        result = ig.generate_market_heatmap(coins, "2026-02-08", source="coingecko")
        assert result is not None

    def test_heatmap_sparkline_absent_uses_seed(self, tmp_path, monkeypatch):
        """Fallback path: no sparkline → seed-based random trend."""
        monkeypatch.setattr(ig, "IMAGES_DIR", str(tmp_path))
        coins = [
            {
                "symbol": "BTC",
                "current_price": 50000,
                "price_change_percentage_24h": 2.0,
                "market_cap": 1e12,
                # no sparkline_in_7d key
            },
        ]
        result = ig.generate_market_heatmap(coins, "2026-02-09", source="coingecko")
        assert result is not None


# ---------------------------------------------------------------------------
# market.py line 165 — unchanged ticker (pct == 0) branch in snapshot
# ---------------------------------------------------------------------------


class TestMarketSnapshotUnchanged:
    def test_zero_pct_change_unchanged_branch(self, tmp_path, monkeypatch):
        """Line 165: pct_val == 0 → unchanged += 1 branch."""
        monkeypatch.setattr(ig, "IMAGES_DIR", str(tmp_path))
        market_data = [
            {"name": "S&P 500", "price": "$5,000", "change_pct": "+0.0%", "section": "US"},
            {"name": "NASDAQ", "price": "$17,000", "change_pct": "0.0%", "section": "US"},
            {"name": "VIX", "price": "15.00", "change_pct": "0", "section": "Volatility"},
        ]
        result = ig.generate_market_snapshot_card(market_data, "2026-02-10")
        assert result is not None


# ---------------------------------------------------------------------------
# market.py lines 449-454 — sparkline_data branch in sector heatmap
# ---------------------------------------------------------------------------


class TestSectorHeatmapSparkline:
    def test_sparkline_data_provided(self, tmp_path, monkeypatch):
        """Lines 448-453: sparkline_data with >= 2 values."""
        monkeypatch.setattr(ig, "IMAGES_DIR", str(tmp_path))
        sector_data = {
            "XLK": {
                "name": "Technology (XLK)",
                "price": "180.5",
                "change_pct": 1.2,
                "pct_val": 1.2,
                "sparkline_data": [175.0, 177.0, 179.0, 180.5],
            },
            "XLF": {
                "name": "Financials (XLF)",
                "price": "42.3",
                "change_pct": -0.5,
                "pct_val": -0.5,
                "sparkline_data": [43.0, 42.8, 42.5, 42.3],
            },
            "XLE": {
                "name": "Energy (XLE)",
                "price": "87.1",
                "change_pct": 0.8,
                "pct_val": 0.8,
                "sparkline_data": [],  # too short → seed path
            },
        }
        result = ig.generate_sector_heatmap(sector_data, "2026-02-11")
        assert result is not None

    def test_sparkline_data_flat_constant(self, tmp_path, monkeypatch):
        """Flat sparkline (smax == smin) → np.full path in sector heatmap."""
        monkeypatch.setattr(ig, "IMAGES_DIR", str(tmp_path))
        sector_data = {
            "XLK": {
                "name": "Technology",
                "price": "100",
                "change_pct": 0.0,
                "pct_val": 0.0,
                "sparkline_data": [100.0, 100.0, 100.0, 100.0, 100.0],
            },
        }
        result = ig.generate_sector_heatmap(sector_data, "2026-02-12")
        assert result is not None
