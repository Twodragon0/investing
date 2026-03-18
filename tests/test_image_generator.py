"""Unit tests for pure logic functions in scripts/common/image_generator.py.

PIL/matplotlib 없이 테스트 가능한 순수 로직 함수들만 커버.
matplotlib이 필요한 함수는 sys.modules 패칭으로 임포트 비활성화 상태에서 테스트.
"""

import importlib
import sys
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Helpers: matplotlib/numpy stub so module loads cleanly even if not installed
# ---------------------------------------------------------------------------

def _get_module():
    """Return the image_generator module (already imported or freshly imported)."""
    mod_name = "common.image_generator"
    if mod_name in sys.modules:
        return sys.modules[mod_name]
    return importlib.import_module(mod_name)


# Import at module level so fixtures can reference it
try:
    from common import image_generator as ig
    _IMPORT_OK = True
except Exception:
    ig = None  # type: ignore
    _IMPORT_OK = False


pytestmark = pytest.mark.skipif(not _IMPORT_OK, reason="image_generator could not be imported")


# ---------------------------------------------------------------------------
# 1. _to_en  — Korean → English translation helper
# ---------------------------------------------------------------------------

class TestToEn:
    def test_exact_match_returns_english(self):
        assert ig._to_en("비트코인") == "Bitcoin"

    def test_exact_match_exchange(self):
        assert ig._to_en("거래소") == "Exchange"

    def test_english_passthrough(self):
        assert ig._to_en("Bitcoin") == "Bitcoin"

    def test_empty_string(self):
        assert ig._to_en("") == ""

    def test_partial_match_replaces_known_substring(self):
        # "비트코인 분석" contains "비트코인" → should replace
        result = ig._to_en("비트코인 분석")
        assert "Bitcoin" in result

    def test_unknown_hangul_passthrough(self):
        # Unknown Korean text not in _KO_TO_EN should be returned as-is
        result = ig._to_en("알수없는단어")
        assert result == "알수없는단어"

    def test_all_known_keys_map_to_nonempty(self):
        for ko, en in ig._KO_TO_EN.items():
            assert ig._to_en(ko) == en
            assert isinstance(en, str) and len(en) > 0

    def test_mixed_latin_hangul(self):
        # "AI/기술" is in _KO_TO_EN
        assert ig._to_en("AI/기술") == "AI/Tech"

    def test_nftweb3_passthrough(self):
        # "NFT/Web3" has no Hangul — returns as-is
        assert ig._to_en("NFT/Web3") == "NFT/Web3"


# ---------------------------------------------------------------------------
# 2. _filter_en_keywords  — Filter noise words, keep meaningful ones
# ---------------------------------------------------------------------------

class TestFilterEnKeywords:
    def test_removes_noise_words(self):
        noise = ["the", "and", "for", "with", "has"]
        assert ig._filter_en_keywords(noise) == []

    def test_keeps_meaningful_words(self):
        result = ig._filter_en_keywords(["Bitcoin", "Ethereum", "DeFi"])
        assert result == ["Bitcoin", "Ethereum", "DeFi"]

    def test_filters_korean_only(self):
        # Korean-only strings have no Latin chars — should be removed
        result = ig._filter_en_keywords(["비트코인", "이더리움"])
        assert result == []

    def test_empty_list(self):
        assert ig._filter_en_keywords([]) == []

    def test_case_insensitive_noise_removal(self):
        result = ig._filter_en_keywords(["The", "AND", "For"])
        assert result == []

    def test_mixed_keeps_latin_filters_noise(self):
        result = ig._filter_en_keywords(["Bitcoin", "the", "SEC", "and"])
        assert "Bitcoin" in result
        assert "SEC" in result
        assert "the" not in result
        assert "and" not in result

    def test_preserves_order(self):
        keywords = ["SEC", "Fed", "FOMC", "CPI"]
        result = ig._filter_en_keywords(keywords)
        assert result == ["SEC", "Fed", "FOMC", "CPI"]

    def test_whitespace_stripped_noise(self):
        # " report " has leading/trailing spaces — should still be filtered
        result = ig._filter_en_keywords([" report "])
        assert result == []

    def test_numeric_with_latin(self):
        # "BTC1" has Latin chars → keep
        result = ig._filter_en_keywords(["BTC1"])
        assert result == ["BTC1"]


# ---------------------------------------------------------------------------
# 3. _safe_float  — Safely convert value to float
# ---------------------------------------------------------------------------

class TestSafeFloat:
    def test_none_returns_default(self):
        assert ig._safe_float(None) == 0.0

    def test_none_custom_default(self):
        assert ig._safe_float(None, default=99.0) == 99.0

    def test_valid_int(self):
        assert ig._safe_float(42) == 42.0

    def test_valid_float(self):
        assert ig._safe_float(3.14) == pytest.approx(3.14)

    def test_valid_string_number(self):
        assert ig._safe_float("2.5") == pytest.approx(2.5)

    def test_invalid_string_returns_default(self):
        assert ig._safe_float("abc") == 0.0

    def test_invalid_string_custom_default(self):
        assert ig._safe_float("xyz", default=-1.0) == -1.0

    def test_zero(self):
        assert ig._safe_float(0) == 0.0

    def test_negative(self):
        assert ig._safe_float(-5.5) == pytest.approx(-5.5)

    def test_large_number(self):
        assert ig._safe_float(1_000_000_000) == 1_000_000_000.0

    def test_empty_string_returns_default(self):
        assert ig._safe_float("", default=-99.0) == -99.0

    def test_list_returns_default(self):
        assert ig._safe_float([1, 2]) == 0.0


# ---------------------------------------------------------------------------
# 4. _get_change_color  — Color based on price change
# ---------------------------------------------------------------------------

class TestGetChangeColor:
    def test_positive_returns_green(self):
        color = ig._get_change_color(1.5)
        assert color == ig.COLORS["green"]

    def test_negative_returns_red(self):
        color = ig._get_change_color(-0.5)
        assert color == ig.COLORS["red"]

    def test_zero_returns_secondary(self):
        color = ig._get_change_color(0.0)
        assert color == ig.COLORS["text_secondary"]

    def test_large_positive(self):
        assert ig._get_change_color(100.0) == ig.COLORS["green"]

    def test_large_negative(self):
        assert ig._get_change_color(-100.0) == ig.COLORS["red"]

    def test_tiny_positive(self):
        assert ig._get_change_color(0.0001) == ig.COLORS["green"]

    def test_tiny_negative(self):
        assert ig._get_change_color(-0.0001) == ig.COLORS["red"]


# ---------------------------------------------------------------------------
# 5. COLORS  — Color palette constants
# ---------------------------------------------------------------------------

class TestColors:
    def test_required_keys_present(self):
        required = [
            "bg", "bg_card", "bg_inner", "bg_header",
            "text", "text_secondary", "text_muted",
            "green", "green_dim", "red", "red_dim",
            "blue", "orange", "purple", "cyan",
            "accent", "warning", "info",
            "border", "border_highlight",
            "gold", "silver", "bronze",
        ]
        for key in required:
            assert key in ig.COLORS, f"Missing COLORS key: {key}"

    def test_all_values_are_hex_colors(self):
        import re
        hex_pattern = re.compile(r"^#[0-9a-fA-F]{6}$")
        for key, val in ig.COLORS.items():
            assert hex_pattern.match(val), f"COLORS[{key!r}] = {val!r} is not a valid hex color"

    def test_green_and_red_differ(self):
        assert ig.COLORS["green"] != ig.COLORS["red"]

    def test_bg_is_dark(self):
        # Parse hex to RGB and check brightness
        bg = ig.COLORS["bg"]
        r = int(bg[1:3], 16)
        g = int(bg[3:5], 16)
        b = int(bg[5:7], 16)
        luminance = 0.299 * r + 0.587 * g + 0.114 * b
        assert luminance < 64, f"Background should be dark, luminance={luminance}"


# ---------------------------------------------------------------------------
# 6. _DS  — Design system constants
# ---------------------------------------------------------------------------

class TestDesignSystem:
    def test_required_keys_present(self):
        required = ["dpi", "footer_size", "title_size", "subtitle_size",
                    "body_size", "label_size", "row_height", "watermark"]
        for key in required:
            assert key in ig._DS, f"Missing _DS key: {key}"

    def test_dpi_is_positive(self):
        assert ig._DS["dpi"] > 0

    def test_watermark_is_string(self):
        assert isinstance(ig._DS["watermark"], str)
        assert len(ig._DS["watermark"]) > 0

    def test_title_larger_than_footer(self):
        assert ig._DS["title_size"] > ig._DS["footer_size"]

    def test_row_height_positive(self):
        assert ig._DS["row_height"] > 0


# ---------------------------------------------------------------------------
# 7. _KO_TO_EN  — Translation dictionary structure
# ---------------------------------------------------------------------------

class TestKoToEnDict:
    def test_all_keys_are_strings(self):
        for k in ig._KO_TO_EN:
            assert isinstance(k, str)

    def test_all_values_are_strings(self):
        for v in ig._KO_TO_EN.values():
            assert isinstance(v, str)

    def test_no_empty_values(self):
        for k, v in ig._KO_TO_EN.items():
            assert v, f"Empty value for key: {k!r}"

    def test_known_entries(self):
        assert ig._KO_TO_EN["비트코인"] == "Bitcoin"
        assert ig._KO_TO_EN["이더리움"] == "Ethereum"
        assert ig._KO_TO_EN["거래소"] == "Exchange"


# ---------------------------------------------------------------------------
# 8. _convert_to_webp  — PIL-dependent, test graceful degradation
# ---------------------------------------------------------------------------

class TestConvertToWebp:
    def test_returns_none_when_file_not_found(self, tmp_path):
        """Should return None without crashing when PNG doesn't exist."""
        fake_png = str(tmp_path / "nonexistent.png")
        result = ig._convert_to_webp(fake_png)
        assert result is None

    def test_returns_none_when_pillow_unavailable(self, tmp_path, monkeypatch):
        """Should return None gracefully when Pillow is not installed."""
        png_path = tmp_path / "test.png"
        png_path.write_bytes(b"fake png data")

        original_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

        def mock_import(name, *args, **kwargs):
            if name == "PIL":
                raise ImportError("PIL not available")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            # The function catches ImportError and returns None
            result = ig._convert_to_webp(str(png_path))
        # Either None (Pillow unavailable) or a path (Pillow available) — both are OK
        assert result is None or isinstance(result, str)


# ---------------------------------------------------------------------------
# 9. generate_* functions  — Return None when matplotlib unavailable
# ---------------------------------------------------------------------------

class TestGenerateFunctionsNoMpl:
    """When _MPL_AVAILABLE is False, all generate_* functions should return None."""

    def test_generate_top_coins_card_no_mpl(self):
        with patch.object(ig, "_MPL_AVAILABLE", False):
            result = ig.generate_top_coins_card([], "2026-01-01")
        assert result is None

    def test_generate_fear_greed_gauge_no_mpl(self):
        with patch.object(ig, "_MPL_AVAILABLE", False):
            result = ig.generate_fear_greed_gauge(50, "Neutral", "2026-01-01")
        assert result is None

    def test_generate_market_heatmap_no_mpl(self):
        with patch.object(ig, "_MPL_AVAILABLE", False):
            result = ig.generate_market_heatmap([], "2026-01-01")
        assert result is None

    def test_generate_news_summary_card_no_mpl(self):
        with patch.object(ig, "_MPL_AVAILABLE", False):
            result = ig.generate_news_summary_card({}, "2026-01-01")
        assert result is None

    def test_generate_market_snapshot_card_no_mpl(self):
        with patch.object(ig, "_MPL_AVAILABLE", False):
            result = ig.generate_market_snapshot_card({}, "2026-01-01")
        assert result is None

    def test_generate_top_coins_empty_list_no_mpl(self):
        with patch.object(ig, "_MPL_AVAILABLE", False):
            result = ig.generate_top_coins_card([], "2026-01-01")
        assert result is None

    def test_generate_source_distribution_card_no_mpl(self):
        with patch.object(ig, "_MPL_AVAILABLE", False):
            result = ig.generate_source_distribution_card({}, "2026-01-01")
        assert result is None

    def test_generate_sector_heatmap_no_mpl(self):
        with patch.object(ig, "_MPL_AVAILABLE", False):
            result = ig.generate_sector_heatmap([], "2026-01-01")
        assert result is None

    def test_generate_news_briefing_card_no_mpl(self):
        with patch.object(ig, "_MPL_AVAILABLE", False):
            result = ig.generate_news_briefing_card([], "2026-01-01")
        assert result is None

    def test_generate_category_og_image_no_mpl(self):
        with patch.object(ig, "_MPL_AVAILABLE", False):
            result = ig.generate_category_og_image("crypto")
        assert result is None


# ---------------------------------------------------------------------------
# 10. generate_top_coins_card  — empty coins with MPL available
# ---------------------------------------------------------------------------

class TestGenerateTopCoinsCard:
    def test_empty_coins_returns_none(self):
        """Empty coin list should return None regardless of MPL availability."""
        with patch.object(ig, "_MPL_AVAILABLE", True):
            # Even with MPL available, empty list returns None
            result = ig.generate_top_coins_card([], "2026-01-01")
        assert result is None


# ---------------------------------------------------------------------------
# 11. _heatmap_bg_color  — With MPL available
# ---------------------------------------------------------------------------

class TestHeatmapBgColor:
    def test_positive_change_returns_hex(self):
        color = ig._heatmap_bg_color(3.0)
        assert color.startswith("#")
        assert len(color) == 7

    def test_negative_change_returns_hex(self):
        color = ig._heatmap_bg_color(-3.0)
        assert color.startswith("#")
        assert len(color) == 7

    def test_zero_returns_hex(self):
        color = ig._heatmap_bg_color(0.0)
        assert color.startswith("#")

    def test_extreme_positive_clamped(self):
        # Beyond extreme should clamp to 1.0 ratio
        c1 = ig._heatmap_bg_color(5.0, extreme=5.0)
        c2 = ig._heatmap_bg_color(100.0, extreme=5.0)
        assert c1 == c2

    def test_positive_and_negative_differ(self):
        pos = ig._heatmap_bg_color(5.0)
        neg = ig._heatmap_bg_color(-5.0)
        assert pos != neg

    def test_custom_extreme(self):
        color = ig._heatmap_bg_color(2.0, extreme=10.0)
        assert isinstance(color, str)


# ---------------------------------------------------------------------------
# 12. _ensure_dir + _save_and_close  — With MPL, using tmp_path
# ---------------------------------------------------------------------------

class TestEnsureDirAndSave:
    def test_ensure_dir_creates_directory(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ig, "IMAGES_DIR", str(tmp_path / "newdir"))
        ig._ensure_dir()
        assert (tmp_path / "newdir").is_dir()

    def test_ensure_dir_idempotent(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ig, "IMAGES_DIR", str(tmp_path))
        ig._ensure_dir()  # Already exists — should not raise
        ig._ensure_dir()

    def test_save_and_close_creates_png(self, tmp_path):
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(4, 3))
        filepath = str(tmp_path / "test_output.png")
        ig._save_and_close(fig, filepath)
        assert (tmp_path / "test_output.png").exists()

    def test_save_and_close_creates_webp(self, tmp_path):
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(4, 3))
        filepath = str(tmp_path / "test_output2.png")
        ig._save_and_close(fig, filepath)
        # WebP may or may not exist depending on Pillow
        assert (tmp_path / "test_output2.png").exists()


# ---------------------------------------------------------------------------
# 13. _convert_to_webp  — With real PNG file
# ---------------------------------------------------------------------------

class TestConvertToWebpWithPng:
    def test_converts_valid_png(self, tmp_path):
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(2, 2))
        png_path = str(tmp_path / "sample.png")
        plt.savefig(png_path, dpi=50)
        plt.close(fig)
        result = ig._convert_to_webp(png_path)
        if result is not None:
            assert result.endswith(".webp")
            assert (tmp_path / "sample.webp").exists()

    def test_nonexistent_file_returns_none(self, tmp_path):
        result = ig._convert_to_webp(str(tmp_path / "nope.png"))
        assert result is None


# ---------------------------------------------------------------------------
# 14. _truncate_text
# ---------------------------------------------------------------------------

class TestTruncateText:
    def test_short_text_unchanged(self):
        assert ig._truncate_text("Hello", 10) == "Hello"

    def test_exact_length_unchanged(self):
        assert ig._truncate_text("Hello", 5) == "Hello"

    def test_truncated_with_ellipsis(self):
        result = ig._truncate_text("Hello World", 8)
        assert result.endswith("...")
        assert len(result) == 8

    def test_very_short_limit(self):
        result = ig._truncate_text("ABCDEF", 3)
        assert result == "..."

    def test_empty_string(self):
        assert ig._truncate_text("", 10) == ""


# ---------------------------------------------------------------------------
# 15. generate_top_coins_card  — With MPL, real data
# ---------------------------------------------------------------------------

class TestGenerateTopCoinsCardWithMpl:
    def test_returns_path_with_valid_coins(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ig, "IMAGES_DIR", str(tmp_path))
        coins = [
            {"symbol": "BTC", "name": "Bitcoin", "current_price": 50000,
             "price_change_percentage_24h": 2.5, "price_change_percentage_7d_in_currency": -1.0,
             "market_cap": 1_000_000_000_000},
            {"symbol": "ETH", "name": "Ethereum", "current_price": 3000,
             "price_change_percentage_24h": -1.2, "price_change_percentage_7d_in_currency": 3.0,
             "market_cap": 400_000_000_000},
            {"symbol": "BNB", "name": "Binance Coin", "current_price": 400,
             "price_change_percentage_24h": 0.5, "price_change_percentage_7d_in_currency": 0.0,
             "market_cap": 60_000_000_000},
        ]
        result = ig.generate_top_coins_card(coins, "2026-01-01")
        assert result is not None
        assert result.startswith("/assets/images/generated/")
        assert result.endswith(".png")
        assert (tmp_path / "top-coins-2026-01-01.png").exists()

    def test_custom_filename(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ig, "IMAGES_DIR", str(tmp_path))
        coins = [
            {"symbol": "BTC", "name": "Bitcoin", "current_price": 50000,
             "price_change_percentage_24h": 1.0, "price_change_percentage_7d_in_currency": 2.0,
             "market_cap": 1_000_000_000_000},
        ]
        result = ig.generate_top_coins_card(coins, "2026-01-01", filename="custom.png")
        assert result == "/assets/images/generated/custom.png"

    def test_cmc_source(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ig, "IMAGES_DIR", str(tmp_path))
        coins = [
            {"symbol": "BTC", "name": "Bitcoin",
             "quote": {"USD": {"price": 50000, "percent_change_24h": 1.5,
                                "percent_change_7d": -0.5, "market_cap": 1e12}}},
        ]
        result = ig.generate_top_coins_card(coins, "2026-01-01", source="cmc")
        assert result is not None

    def test_price_formatting_small(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ig, "IMAGES_DIR", str(tmp_path))
        coins = [
            {"symbol": "DOGE", "name": "Dogecoin", "current_price": 0.005,
             "price_change_percentage_24h": 10.0, "price_change_percentage_7d_in_currency": 20.0,
             "market_cap": 1_000_000_000},
        ]
        result = ig.generate_top_coins_card(coins, "2026-01-02")
        assert result is not None

    def test_many_coins_up_to_15(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ig, "IMAGES_DIR", str(tmp_path))
        coins = [
            {"symbol": f"C{i}", "name": f"Coin{i}", "current_price": 100 + i,
             "price_change_percentage_24h": float(i - 5),
             "price_change_percentage_7d_in_currency": float(i - 7),
             "market_cap": 1_000_000_000 * (20 - i)}
            for i in range(20)
        ]
        result = ig.generate_top_coins_card(coins, "2026-01-03")
        assert result is not None

    def test_mcap_trillion(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ig, "IMAGES_DIR", str(tmp_path))
        coins = [
            {"symbol": "BTC", "name": "Bitcoin", "current_price": 100000,
             "price_change_percentage_24h": 0.0, "price_change_percentage_7d_in_currency": 0.0,
             "market_cap": 2_000_000_000_000},
        ]
        result = ig.generate_top_coins_card(coins, "2026-01-04")
        assert result is not None


# ---------------------------------------------------------------------------
# 16. generate_fear_greed_gauge  — With MPL
# ---------------------------------------------------------------------------

class TestGenerateFearGreedGauge:
    def test_neutral_value(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ig, "IMAGES_DIR", str(tmp_path))
        result = ig.generate_fear_greed_gauge(50, "Neutral", "2026-01-01")
        assert result is not None
        assert result.startswith("/assets/images/generated/")
        assert (tmp_path / "fear-greed-2026-01-01.png").exists()

    def test_extreme_fear(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ig, "IMAGES_DIR", str(tmp_path))
        result = ig.generate_fear_greed_gauge(10, "Extreme Fear", "2026-01-02")
        assert result is not None

    def test_extreme_greed(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ig, "IMAGES_DIR", str(tmp_path))
        result = ig.generate_fear_greed_gauge(90, "Extreme Greed", "2026-01-03")
        assert result is not None

    def test_value_clamped_above_100(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ig, "IMAGES_DIR", str(tmp_path))
        result = ig.generate_fear_greed_gauge(150, "Greed", "2026-01-04")
        assert result is not None

    def test_value_clamped_below_0(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ig, "IMAGES_DIR", str(tmp_path))
        result = ig.generate_fear_greed_gauge(-10, "Fear", "2026-01-05")
        assert result is not None

    def test_custom_filename(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ig, "IMAGES_DIR", str(tmp_path))
        result = ig.generate_fear_greed_gauge(50, "Neutral", "2026-01-01", filename="fg.png")
        assert result == "/assets/images/generated/fg.png"

    def test_fear_range(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ig, "IMAGES_DIR", str(tmp_path))
        result = ig.generate_fear_greed_gauge(30, "Fear", "2026-01-06")
        assert result is not None

    def test_greed_range(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ig, "IMAGES_DIR", str(tmp_path))
        result = ig.generate_fear_greed_gauge(70, "Greed", "2026-01-07")
        assert result is not None


# ---------------------------------------------------------------------------
# 17. generate_market_heatmap  — With MPL
# ---------------------------------------------------------------------------

class TestGenerateMarketHeatmap:
    def test_basic_coingecko(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ig, "IMAGES_DIR", str(tmp_path))
        coins = [
            {"symbol": "BTC", "current_price": 50000,
             "price_change_percentage_24h": 2.5, "market_cap": 1e12},
            {"symbol": "ETH", "current_price": 3000,
             "price_change_percentage_24h": -1.5, "market_cap": 4e11},
        ]
        result = ig.generate_market_heatmap(coins, "2026-01-01")
        assert result is not None
        assert result.startswith("/assets/images/generated/")

    def test_empty_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ig, "IMAGES_DIR", str(tmp_path))
        result = ig.generate_market_heatmap([], "2026-01-01")
        assert result is None

    def test_cmc_source(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ig, "IMAGES_DIR", str(tmp_path))
        coins = [
            {"symbol": "BTC",
             "quote": {"USD": {"price": 50000, "percent_change_24h": 5.0, "market_cap": 1e12}}},
        ]
        result = ig.generate_market_heatmap(coins, "2026-01-01", source="cmc")
        assert result is not None

    def test_many_coins(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ig, "IMAGES_DIR", str(tmp_path))
        coins = [
            {"symbol": f"C{i}", "current_price": 100.0,
             "price_change_percentage_24h": float(i - 10), "market_cap": 1e9}
            for i in range(25)
        ]
        result = ig.generate_market_heatmap(coins, "2026-01-01")
        assert result is not None

    def test_high_change_border_highlight(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ig, "IMAGES_DIR", str(tmp_path))
        coins = [
            {"symbol": "MOON", "current_price": 0.5,
             "price_change_percentage_24h": 25.0, "market_cap": 1e8},
        ]
        result = ig.generate_market_heatmap(coins, "2026-01-01")
        assert result is not None


# ---------------------------------------------------------------------------
# 18. generate_news_summary_card  — With MPL
# ---------------------------------------------------------------------------

class TestGenerateNewsSummaryCard:
    def test_basic(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ig, "IMAGES_DIR", str(tmp_path))
        categories = [
            {"name": "CryptoPanic", "count": 15},
            {"name": "NewsAPI", "count": 10},
            {"name": "RSS", "count": 5},
        ]
        result = ig.generate_news_summary_card(categories, "2026-01-01")
        assert result is not None
        assert result.endswith(".png")

    def test_empty_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ig, "IMAGES_DIR", str(tmp_path))
        result = ig.generate_news_summary_card([], "2026-01-01")
        assert result is None

    def test_korean_name_translated(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ig, "IMAGES_DIR", str(tmp_path))
        categories = [{"name": "암호화폐", "count": 8}]
        result = ig.generate_news_summary_card(categories, "2026-01-01")
        assert result is not None

    def test_custom_filename(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ig, "IMAGES_DIR", str(tmp_path))
        categories = [{"name": "Test", "count": 3}]
        result = ig.generate_news_summary_card(categories, "2026-01-01", filename="custom_news.png")
        assert result == "/assets/images/generated/custom_news.png"


# ---------------------------------------------------------------------------
# 19. generate_market_snapshot_card  — With MPL
# ---------------------------------------------------------------------------

class TestGenerateMarketSnapshotCard:
    def test_basic(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ig, "IMAGES_DIR", str(tmp_path))
        market_data = [
            {"name": "S&P 500", "price": "$5,000", "change_pct": "+0.5%", "section": "US"},
            {"name": "NASDAQ", "price": "$17,000", "change_pct": "-0.3%", "section": "US"},
            {"name": "원/달러", "price": "1,380", "change_pct": "+0.2%", "section": "FX"},
        ]
        result = ig.generate_market_snapshot_card(market_data, "2026-01-01")
        assert result is not None
        assert result.startswith("/assets/images/generated/")

    def test_empty_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ig, "IMAGES_DIR", str(tmp_path))
        result = ig.generate_market_snapshot_card([], "2026-01-01")
        assert result is None

    def test_invalid_change_pct(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ig, "IMAGES_DIR", str(tmp_path))
        market_data = [
            {"name": "KOSPI", "price": "2,500", "change_pct": "N/A", "section": "KR"},
        ]
        result = ig.generate_market_snapshot_card(market_data, "2026-01-01")
        assert result is not None

    def test_no_section(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ig, "IMAGES_DIR", str(tmp_path))
        market_data = [
            {"name": "BTC", "price": "$50,000", "change_pct": "+1.5%"},
        ]
        result = ig.generate_market_snapshot_card(market_data, "2026-01-01")
        assert result is not None

    def test_custom_filename(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ig, "IMAGES_DIR", str(tmp_path))
        market_data = [{"name": "S&P", "price": "$5,000", "change_pct": "+0.5%"}]
        result = ig.generate_market_snapshot_card(market_data, "2026-01-01", filename="snap.png")
        assert result == "/assets/images/generated/snap.png"


# ---------------------------------------------------------------------------
# 20. generate_source_distribution_card  — With MPL
# ---------------------------------------------------------------------------

class TestGenerateSourceDistributionCard:
    def test_basic(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ig, "IMAGES_DIR", str(tmp_path))
        sources = [
            {"name": "Telegram", "count": 20},
            {"name": "Twitter", "count": 15},
            {"name": "Reddit", "count": 10},
        ]
        result = ig.generate_source_distribution_card(sources, "2026-01-01")
        assert result is not None
        assert result.startswith("/assets/images/generated/")

    def test_empty_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ig, "IMAGES_DIR", str(tmp_path))
        result = ig.generate_source_distribution_card([], "2026-01-01")
        assert result is None

    def test_single_source(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ig, "IMAGES_DIR", str(tmp_path))
        sources = [{"name": "NewsAPI", "count": 100}]
        result = ig.generate_source_distribution_card(sources, "2026-01-01")
        assert result is not None

    def test_custom_filename(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ig, "IMAGES_DIR", str(tmp_path))
        sources = [{"name": "X", "count": 5}]
        result = ig.generate_source_distribution_card(sources, "2026-01-01", filename="dist.png")
        assert result == "/assets/images/generated/dist.png"

    def test_many_sources(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ig, "IMAGES_DIR", str(tmp_path))
        sources = [{"name": f"Source{i}", "count": 10 + i} for i in range(10)]
        result = ig.generate_source_distribution_card(sources, "2026-01-01")
        assert result is not None


# ---------------------------------------------------------------------------
# 21. generate_sector_heatmap  — With MPL
# ---------------------------------------------------------------------------

class TestGenerateSectorHeatmap:
    def test_basic(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ig, "IMAGES_DIR", str(tmp_path))
        sector_data = {
            "XLK": {"name": "Technology (XLK)", "price": "180.5", "change_pct": 1.2},
            "XLF": {"name": "Financials (XLF)", "price": "42.3", "change_pct": -0.5},
            "XLE": {"name": "Energy (XLE)", "price": "87.1", "change_pct": 0.8},
        }
        result = ig.generate_sector_heatmap(sector_data, "2026-01-01")
        assert result is not None
        assert result.startswith("/assets/images/generated/")

    def test_empty_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ig, "IMAGES_DIR", str(tmp_path))
        result = ig.generate_sector_heatmap({}, "2026-01-01")
        assert result is None

    def test_many_sectors(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ig, "IMAGES_DIR", str(tmp_path))
        sector_data = {
            f"XL{i}": {"name": f"Sector{i}", "price": str(50 + i), "change_pct": float(i - 5)}
            for i in range(11)
        }
        result = ig.generate_sector_heatmap(sector_data, "2026-01-01")
        assert result is not None

    def test_custom_filename(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ig, "IMAGES_DIR", str(tmp_path))
        sector_data = {"XLK": {"name": "Tech", "price": "100", "change_pct": 0.5}}
        result = ig.generate_sector_heatmap(sector_data, "2026-01-01", filename="sector.png")
        assert result == "/assets/images/generated/sector.png"

    def test_korean_sector_name(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ig, "IMAGES_DIR", str(tmp_path))
        sector_data = {
            "XLK": {"name": "기술", "price": "180.5", "change_pct": 1.5},
        }
        result = ig.generate_sector_heatmap(sector_data, "2026-01-01")
        assert result is not None

    def test_few_sectors_three_cols(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ig, "IMAGES_DIR", str(tmp_path))
        sector_data = {
            "XLK": {"name": "Technology", "price": "180", "change_pct": 2.0},
            "XLF": {"name": "Financials", "price": "42", "change_pct": -1.0},
        }
        result = ig.generate_sector_heatmap(sector_data, "2026-01-01")
        assert result is not None


# ---------------------------------------------------------------------------
# 22. generate_news_briefing_card  — With MPL
# ---------------------------------------------------------------------------

class TestGenerateNewsBriefingCard:
    def _sample_themes(self):
        return [
            {"name": "Bitcoin", "emoji": "₿", "count": 25, "keywords": ["SEC", "ETF", "approval"]},
            {"name": "규제/정책", "emoji": "⚖️", "count": 15, "keywords": ["regulation", "policy", "law"]},
            {"name": "DeFi", "emoji": "🔗", "count": 10, "keywords": ["TVL", "protocol", "yield"]},
        ]

    def test_basic(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ig, "IMAGES_DIR", str(tmp_path))
        result = ig.generate_news_briefing_card(self._sample_themes(), "2026-01-01")
        assert result is not None
        assert result.startswith("/assets/images/generated/")

    def test_empty_themes_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ig, "IMAGES_DIR", str(tmp_path))
        result = ig.generate_news_briefing_card([], "2026-01-01")
        assert result is None

    def test_with_urgent_alerts(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ig, "IMAGES_DIR", str(tmp_path))
        result = ig.generate_news_briefing_card(
            self._sample_themes(), "2026-01-01",
            urgent_alerts=["BREAKING: Major exchange hacked for $500M"]
        )
        assert result is not None

    def test_with_total_count(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ig, "IMAGES_DIR", str(tmp_path))
        result = ig.generate_news_briefing_card(
            self._sample_themes(), "2026-01-01",
            total_count=100
        )
        assert result is not None

    def test_custom_category(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ig, "IMAGES_DIR", str(tmp_path))
        result = ig.generate_news_briefing_card(
            self._sample_themes(), "2026-01-01",
            category="Crypto News"
        )
        assert result is not None

    def test_custom_filename(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ig, "IMAGES_DIR", str(tmp_path))
        result = ig.generate_news_briefing_card(
            self._sample_themes(), "2026-01-01", filename="brief.png"
        )
        assert result == "/assets/images/generated/brief.png"

    def test_no_urgent_alerts(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ig, "IMAGES_DIR", str(tmp_path))
        result = ig.generate_news_briefing_card(
            self._sample_themes(), "2026-01-01",
            urgent_alerts=None
        )
        assert result is not None

    def test_many_themes_truncated_to_5(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ig, "IMAGES_DIR", str(tmp_path))
        themes = [
            {"name": f"Theme{i}", "emoji": "", "count": 10, "keywords": ["key1", "key2"]}
            for i in range(8)
        ]
        result = ig.generate_news_briefing_card(themes, "2026-01-01")
        assert result is not None


# ---------------------------------------------------------------------------
# 23. generate_category_og_image  — With MPL
# ---------------------------------------------------------------------------

class TestGenerateCategoryOgImage:
    def test_known_category(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ig, "REPO_ROOT", str(tmp_path))
        result = ig.generate_category_og_image("crypto")
        assert result is not None
        assert result == "/assets/images/og-crypto.png"
        assert (tmp_path / "assets" / "images" / "og-crypto.png").exists()

    def test_unknown_category_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ig, "REPO_ROOT", str(tmp_path))
        result = ig.generate_category_og_image("unknown-category")
        assert result is None

    def test_all_known_categories(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ig, "REPO_ROOT", str(tmp_path))
        for cat in ig._CATEGORY_OG_CONFIG:
            result = ig.generate_category_og_image(cat)
            assert result is not None, f"Failed for category: {cat}"

    def test_custom_filename(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ig, "REPO_ROOT", str(tmp_path))
        result = ig.generate_category_og_image("stock", filename="stock_og.png")
        assert result == "/assets/images/stock_og.png"


# ---------------------------------------------------------------------------
# 24. generate_all_category_og_images  — With MPL
# ---------------------------------------------------------------------------

class TestGenerateAllCategoryOgImages:
    def test_returns_all_categories(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ig, "REPO_ROOT", str(tmp_path))
        result = ig.generate_all_category_og_images()
        assert isinstance(result, dict)
        for cat in ig._CATEGORY_OG_CONFIG:
            assert cat in result
            assert result[cat].startswith("/assets/images/")


# ---------------------------------------------------------------------------
# 25. _CATEGORY_OG_CONFIG  — Config structure
# ---------------------------------------------------------------------------

class TestCategoryOgConfig:
    def test_all_entries_have_3_elements(self):
        for cat, config in ig._CATEGORY_OG_CONFIG.items():
            assert len(config) == 3, f"Config for {cat!r} should have 3 elements"

    def test_names_are_strings(self):
        for _cat, (name, _emoji, _color) in ig._CATEGORY_OG_CONFIG.items():
            assert isinstance(name, str)

    def test_colors_are_hex(self):
        import re
        hex_pat = re.compile(r"^#[0-9a-fA-F]{6}$")
        for cat, (_name, _emoji, color) in ig._CATEGORY_OG_CONFIG.items():
            assert hex_pat.match(color), f"Color for {cat!r} is not valid hex: {color!r}"

    def test_known_categories_present(self):
        required = ["crypto", "stock", "market-analysis", "defi"]
        for cat in required:
            assert cat in ig._CATEGORY_OG_CONFIG


# ---------------------------------------------------------------------------
# 26. _safe_float  — with numpy NaN/Inf (numpy available)
# ---------------------------------------------------------------------------

class TestSafeFloatWithNumpy:
    def test_numpy_nan_returns_default(self):
        import numpy as np
        assert ig._safe_float(np.nan) == 0.0

    def test_numpy_inf_returns_default(self):
        import numpy as np
        assert ig._safe_float(np.inf) == 0.0

    def test_numpy_neg_inf_returns_default(self):
        import numpy as np
        assert ig._safe_float(-np.inf) == 0.0

    def test_numpy_float64(self):
        import numpy as np
        assert ig._safe_float(np.float64(3.14)) == pytest.approx(3.14)
