"""Tests for formatters module (scripts/common/formatters.py)."""

from common.formatters import fmt_number, fmt_percent


class TestFmtNumber:
    """Tests for fmt_number()."""

    def test_none_returns_na(self):
        assert fmt_number(None) == "N/A"

    def test_trillion(self):
        result = fmt_number(1_500_000_000_000)
        assert "T" in result
        assert "1.50" in result

    def test_negative_trillion(self):
        result = fmt_number(-2_000_000_000_000)
        assert "T" in result

    def test_billion(self):
        result = fmt_number(1_500_000_000)
        assert "B" in result
        assert "1.50" in result

    def test_negative_billion(self):
        result = fmt_number(-2_000_000_000)
        assert "B" in result

    def test_million(self):
        result = fmt_number(1_500_000)
        assert "M" in result

    def test_million_decimals_capped_at_1(self):
        # decimals=2 for millions is min(2,1)=1 so only 1 decimal
        result = fmt_number(1_234_567)
        assert "M" in result
        # Should have at most 1 decimal place in the M value
        m_part = result.split("M")[0].split("$")[-1]
        decimal_part = m_part.split(".")
        if len(decimal_part) > 1:
            assert len(decimal_part[1]) <= 1

    def test_small_number(self):
        result = fmt_number(42.5)
        assert "42.50" in result
        assert "$" in result

    def test_custom_prefix(self):
        result = fmt_number(1_000_000_000, prefix="₩")
        assert "₩" in result
        assert "$" not in result

    def test_no_prefix(self):
        result = fmt_number(42.5, prefix="", decimals=1)
        assert result == "42.5"

    def test_custom_decimals(self):
        result = fmt_number(1_500_000_000, decimals=3)
        assert "1.500" in result

    def test_zero(self):
        result = fmt_number(0)
        assert "0.00" in result

    def test_exactly_one_trillion(self):
        result = fmt_number(1_000_000_000_000)
        assert "T" in result

    def test_exactly_one_billion(self):
        result = fmt_number(1_000_000_000)
        assert "B" in result

    def test_exactly_one_million(self):
        result = fmt_number(1_000_000)
        assert "M" in result

    def test_just_below_million(self):
        result = fmt_number(999_999)
        assert "M" not in result
        assert "B" not in result
        assert "T" not in result


class TestFmtPercent:
    """Tests for fmt_percent()."""

    def test_none_returns_na(self):
        assert fmt_percent(None) == "N/A"

    def test_positive_has_green_circle(self):
        result = fmt_percent(3.14)
        assert "🟢" in result

    def test_positive_has_plus_sign(self):
        result = fmt_percent(3.14)
        assert "+3.14%" in result

    def test_negative_has_red_circle(self):
        result = fmt_percent(-1.5)
        assert "🔴" in result

    def test_negative_has_minus_sign(self):
        result = fmt_percent(-1.5)
        assert "-1.50%" in result

    def test_zero_treated_as_positive(self):
        result = fmt_percent(0)
        assert "🟢" in result
        assert "+0.00%" in result

    def test_small_positive(self):
        result = fmt_percent(0.01)
        assert "🟢" in result
        assert "+0.01%" in result

    def test_large_negative(self):
        result = fmt_percent(-99.99)
        assert "🔴" in result
        assert "-99.99%" in result

    def test_two_decimal_places(self):
        result = fmt_percent(1.1)
        assert "+1.10%" in result
