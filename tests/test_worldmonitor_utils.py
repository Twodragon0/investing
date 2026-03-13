"""Tests for worldmonitor_utils module (scripts/common/worldmonitor_utils.py)."""

from common.worldmonitor_utils import IMPACT_RANK, THEME_RANK, worldmonitor_sort_key


class TestWorldmonitorSortKey:
    """Tests for worldmonitor_sort_key()."""

    def test_high_impact_geopolitical_returns_lowest_tuple(self):
        key = worldmonitor_sort_key("높음", "지정학/안보")
        assert key == (0, 0)

    def test_high_impact_energy(self):
        key = worldmonitor_sort_key("높음", "에너지")
        assert key == (0, 1)

    def test_medium_impact_financial_market(self):
        key = worldmonitor_sort_key("중간", "금융시장")
        assert key == (2, 1)

    def test_low_impact_social(self):
        key = worldmonitor_sort_key("낮음~중간", "사회/기타")
        assert key == (3, 3)

    def test_unknown_impact_returns_9(self):
        key = worldmonitor_sort_key("알 수 없음", "지정학/안보")
        assert key[0] == 9

    def test_unknown_theme_returns_9(self):
        key = worldmonitor_sort_key("높음", "미지 테마")
        assert key[1] == 9

    def test_both_unknown_returns_9_9(self):
        key = worldmonitor_sort_key("unknown", "unknown")
        assert key == (9, 9)

    def test_returns_tuple_of_two_ints(self):
        key = worldmonitor_sort_key("중간", "에너지")
        assert isinstance(key, tuple)
        assert len(key) == 2
        assert all(isinstance(v, int) for v in key)

    def test_sorting_order_high_before_low(self):
        high = worldmonitor_sort_key("높음", "지정학/안보")
        low = worldmonitor_sort_key("낮음~중간", "사회/기타")
        assert high < low


class TestImpactRank:
    """Tests for IMPACT_RANK dictionary."""

    def test_has_four_entries(self):
        assert len(IMPACT_RANK) == 4

    def test_high_is_lowest_rank(self):
        assert IMPACT_RANK["높음"] == 0

    def test_low_medium_is_highest_rank(self):
        assert IMPACT_RANK["낮음~중간"] == 3


class TestThemeRank:
    """Tests for THEME_RANK dictionary."""

    def test_geopolitical_is_top_priority(self):
        assert THEME_RANK["지정학/안보"] == 0

    def test_social_is_lowest_priority(self):
        assert THEME_RANK["사회/기타"] == 3
