"""Unit tests for scripts/common/summarizer_chart.py.

Tests cover generate_distribution_chart() and BAR_COLORS directly without
going through ThemeSummarizer.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from common.summarizer_chart import BAR_COLORS, generate_distribution_chart

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _items(n: int):
    """Return n minimal item dicts."""
    return [{"title": f"item {i}"} for i in range(n)]


def _themes(count_list):
    """Build top_themes tuples from a list of counts."""
    return [
        (f"Theme{i}", f"theme_{i}", f"T{i}", c)
        for i, c in enumerate(count_list)
    ]


# ---------------------------------------------------------------------------
# Early-return guards
# ---------------------------------------------------------------------------


class TestGenerateDistributionChartEarlyReturn:
    def test_fewer_than_5_items_returns_empty_string(self):
        result = generate_distribution_chart(_items(4), _themes([10]))
        assert result == ""

    def test_zero_items_returns_empty_string(self):
        result = generate_distribution_chart([], _themes([10]))
        assert result == ""

    def test_exactly_4_items_returns_empty_string(self):
        result = generate_distribution_chart(_items(4), _themes([5, 3]))
        assert result == ""

    def test_empty_top_themes_returns_empty_string(self):
        result = generate_distribution_chart(_items(5), [])
        assert result == ""

    def test_5_items_empty_themes_returns_empty_string(self):
        result = generate_distribution_chart(_items(5), [])
        assert result == ""


# ---------------------------------------------------------------------------
# Normal output structure
# ---------------------------------------------------------------------------


class TestGenerateDistributionChartNormal:
    def test_5_items_1_theme_returns_nonempty_html(self):
        result = generate_distribution_chart(_items(5), _themes([7]))
        assert result != ""

    def test_output_contains_outer_div(self):
        result = generate_distribution_chart(_items(5), _themes([7]))
        assert '<div class="theme-distribution">' in result

    def test_output_contains_theme_row(self):
        result = generate_distribution_chart(_items(5), _themes([7]))
        assert '<div class="theme-row">' in result

    def test_output_contains_theme_label(self):
        result = generate_distribution_chart(_items(5), _themes([7]))
        assert '<span class="theme-label">' in result

    def test_output_contains_bar_track(self):
        result = generate_distribution_chart(_items(5), _themes([7]))
        assert '<div class="bar-track">' in result

    def test_output_contains_bar_fill(self):
        result = generate_distribution_chart(_items(5), _themes([7]))
        assert "bar-fill" in result

    def test_output_contains_theme_count(self):
        result = generate_distribution_chart(_items(5), _themes([7]))
        assert '<span class="theme-count">' in result

    def test_output_contains_count_with_건(self):
        result = generate_distribution_chart(_items(5), _themes([7]))
        assert "7건</span>" in result

    def test_output_contains_footer_text(self):
        result = generate_distribution_chart(_items(5), _themes([3]))
        assert "*기사는 여러 테마에 중복 집계될 수 있음*" in result

    def test_single_theme_row_count(self):
        result = generate_distribution_chart(_items(5), _themes([10]))
        assert result.count('<div class="theme-row">') == 1

    def test_multiple_themes_row_count(self):
        result = generate_distribution_chart(_items(10), _themes([10, 5, 3]))
        assert result.count('<div class="theme-row">') == 3


# ---------------------------------------------------------------------------
# BAR_COLORS cycling
# ---------------------------------------------------------------------------


class TestBarColorsCycling:
    def test_bar_colors_has_5_entries(self):
        assert len(BAR_COLORS) == 5

    def test_bar_colors_all_strings(self):
        for color in BAR_COLORS:
            assert isinstance(color, str)

    def test_6_themes_cycle_colors(self):
        # 6 themes → colors at indices 0,1,2,3,4,0
        themes = _themes([10, 9, 8, 7, 6, 5])
        result = generate_distribution_chart(_items(10), themes)
        # First color appears at least twice (index 0 and 5)
        first_color = BAR_COLORS[0]
        assert result.count(first_color) >= 2

    def test_5_themes_each_color_once(self):
        themes = _themes([10, 9, 8, 7, 6])
        result = generate_distribution_chart(_items(10), themes)
        for color in BAR_COLORS:
            assert color in result


# ---------------------------------------------------------------------------
# Bar width normalisation
# ---------------------------------------------------------------------------


class TestBarWidthNormalisation:
    def test_max_count_theme_gets_100_percent(self):
        themes = [("Alpha", "alpha", "A", 10)]
        result = generate_distribution_chart(_items(5), themes)
        assert 'style="width:100%"' in result

    def test_half_count_gets_50_percent(self):
        themes = [
            ("Alpha", "alpha", "A", 10),
            ("Beta", "beta", "B", 5),
        ]
        result = generate_distribution_chart(_items(5), themes)
        assert 'style="width:50%"' in result

    def test_zero_count_theme_gets_0_percent(self):
        # A theme with count 0 relative to max 10 → 0%
        themes = [
            ("Alpha", "alpha", "A", 10),
            ("Beta", "beta", "B", 0),
        ]
        result = generate_distribution_chart(_items(5), themes)
        assert 'style="width:0%"' in result

    def test_single_theme_always_100_percent(self):
        # Any non-zero count with only one theme → 100%
        themes = [("Only", "only", "O", 3)]
        result = generate_distribution_chart(_items(5), themes)
        assert 'style="width:100%"' in result


# ---------------------------------------------------------------------------
# Theme label content
# ---------------------------------------------------------------------------


class TestThemeLabelContent:
    def test_emoji_appears_in_label(self):
        themes = [("Crypto", "crypto", "🪙", 5)]
        result = generate_distribution_chart(_items(5), themes)
        assert "🪙" in result

    def test_theme_name_appears_in_label(self):
        themes = [("Crypto", "crypto", "🪙", 5)]
        result = generate_distribution_chart(_items(5), themes)
        assert "Crypto" in result

    def test_count_appears_in_theme_count_span(self):
        themes = [("Crypto", "crypto", "🪙", 42)]
        result = generate_distribution_chart(_items(5), themes)
        assert "42건</span>" in result
