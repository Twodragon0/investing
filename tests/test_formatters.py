"""Tests for formatters module (scripts/common/formatters.py)."""

from datetime import UTC, datetime

from common.formatters import fmt_change_icon, fmt_date_kr, fmt_number, fmt_percent


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


class TestFmtChangeIcon:
    """Tests for fmt_change_icon()."""

    def test_empty_string_returns_neutral(self):
        icon, display = fmt_change_icon("")
        assert icon == "⚪"

    def test_none_returns_neutral(self):
        icon, display = fmt_change_icon(None)
        assert icon == "⚪"
        assert display == "N/A"

    def test_na_string(self):
        icon, display = fmt_change_icon("N/A")
        assert icon == "⚪"

    def test_dash_string(self):
        icon, display = fmt_change_icon("-")
        assert icon == "⚪"

    def test_positive_change(self):
        icon, display = fmt_change_icon("+3.14%")
        assert icon == "🟢"
        assert "+3.14%" in display

    def test_negative_change(self):
        icon, display = fmt_change_icon("-1.50%")
        assert icon == "🔴"
        assert "-1.50%" in display

    def test_no_sign_positive(self):
        icon, display = fmt_change_icon("2.5%")
        assert icon == "🟢"
        assert "+2.50%" in display

    def test_zero_change(self):
        icon, display = fmt_change_icon("0%")
        assert icon == "🟢"
        assert "+0.00%" in display

    def test_invalid_string(self):
        icon, display = fmt_change_icon("abc")
        assert icon == "⚪"
        assert display == "abc"

    def test_comma_separated(self):
        icon, display = fmt_change_icon("+1,234.56%")
        assert icon == "🟢"


class TestFmtDateKr:
    """Tests for fmt_date_kr()."""

    def test_default_returns_today(self):
        result = fmt_date_kr()
        assert "년" in result and "월" in result and "일" in result

    def test_specific_date(self):
        dt = datetime(2026, 3, 17, tzinfo=UTC)
        result = fmt_date_kr(dt)
        assert result == "2026년 03월 17일"

    def test_single_digit_month(self):
        dt = datetime(2026, 1, 5, tzinfo=UTC)
        result = fmt_date_kr(dt)
        assert "01월" in result
        assert "05일" in result
