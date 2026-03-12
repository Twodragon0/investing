import importlib

collect_fmp_calendar = importlib.import_module("collect_fmp_calendar")


def test_fmt_number_and_change_pct():
    assert collect_fmp_calendar._fmt_number(1234.567, 2) == "1,234.57"
    assert collect_fmp_calendar._fmt_number(1234.567, 0) == "1,234"
    assert collect_fmp_calendar._fmt_number(None) == "N/A"

    assert collect_fmp_calendar._fmt_change_pct(1.23) == "🟢 +1.23%"
    assert collect_fmp_calendar._fmt_change_pct("-0.5") == "🔴 -0.50%"
    assert collect_fmp_calendar._fmt_change_pct(None) == "N/A"


def test_build_economic_section_high_before_medium():
    events = [
        {
            "date": "2026-03-12",
            "country": "US",
            "event": "Retail Sales",
            "impact": "Medium",
            "forecast": "0.2%",
            "previous": "0.1%",
            "actual": "",
        },
        {
            "date": "2026-03-10",
            "country": "US",
            "event": "CPI",
            "impact": "High",
            "forecast": "3.0%",
            "previous": "2.9%",
            "actual": "",
        },
    ]
    section = collect_fmp_calendar._build_economic_section(events)
    assert section.index("**CPI**") < section.index("**Retail Sales**")


def test_build_earnings_section_news_fallback_mode():
    earnings = [
        {
            "is_news_fallback": True,
            "title": "Apple earnings beat estimates",
            "link": "https://example.com/apple",
            "date": "2026-03-10",
        }
    ]
    section = collect_fmp_calendar._build_earnings_section(earnings)
    assert "실적 관련 뉴스" in section
    assert "[Apple earnings beat estimates](https://example.com/apple)" in section
