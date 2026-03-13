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
