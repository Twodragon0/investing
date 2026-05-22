import importlib

collect_geopolitical = importlib.import_module("collect_geopolitical")


def test_polymarket_section_uses_filtered_set_for_count_and_volume():
    markets = [
        {
            "title": "Will NBA finals go to game 7?",
            "link": "https://polymarket.com/event/nba",
            "probability": "🟢 Yes 60%",
            "volume": 999_999,
        },
        {
            "title": "Will new sanctions hit Iran this quarter?",
            "link": "https://polymarket.com/event/iran-sanctions",
            "probability": "🟢 Yes 55%",
            "volume": 12_345,
        },
    ]

    lines, filtered = collect_geopolitical._build_polymarket_section(markets)
    rendered = "\n".join(lines)

    assert len(filtered) == 1
    assert "분석 대상</div></div>" in rendered
    assert '>1</div><div class="stat-label">분석 대상<' in rendered
    assert "$12,345" in rendered
    assert "$999,999" not in rendered


def test_polymarket_section_fallback_basis_is_consistent():
    markets = [
        {
            "title": "Will GTA 6 launch this year?",
            "link": "https://polymarket.com/event/gta6",
            "probability": "🟢 Yes 65%",
            "volume": 500_000,
        },
        {
            "title": "Will CPI stay above 3% by year-end?",
            "link": "https://polymarket.com/event/cpi",
            "probability": "🟢 Yes 52%",
            "volume": 20_000,
        },
        {
            "title": "Will AI chip exports face tighter rules?",
            "link": "https://polymarket.com/event/chip-export-rules",
            "probability": "🟢 Yes 51%",
            "volume": 10_000,
        },
    ]

    lines, filtered = collect_geopolitical._build_polymarket_section(markets)
    rendered = "\n".join(lines)

    # geo-keyword filtered count is < 3, so section falls back to non-entertainment set.
    assert len(filtered) == 2
    assert '>2</div><div class="stat-label">분석 대상<' in rendered
    assert "$30,000" in rendered
    assert "$500,000" not in rendered


# ---------------------------------------------------------------------------
# Regression tests for the two bug fixes applied 2026-04-13
# ---------------------------------------------------------------------------


def test_polymarket_section_all_entertainment_no_sports_shown():
    """When ALL markets are entertainment/sports, no fallback fires.

    filtered_markets must be empty and the section should display the
    "no geopolitical markets" message instead of sports content.
    """
    markets = [
        {
            "title": "Will NBA playoffs end in 6 games?",
            "link": "https://polymarket.com/event/nba-playoffs",
            "probability": "🟢 Yes 58%",
            "volume": 300_000,
        },
        {
            "title": "Who wins the Oscars best picture?",
            "link": "https://polymarket.com/event/oscars",
            "probability": "🔴 No 40%",
            "volume": 150_000,
        },
        {
            "title": "Will GTA 6 release before year end?",
            "link": "https://polymarket.com/event/gta-6",
            "probability": "🟢 Yes 72%",
            "volume": 200_000,
        },
    ]

    lines, filtered = collect_geopolitical._build_polymarket_section(markets)
    rendered = "\n".join(lines)

    # No sports/entertainment should bleed through — filtered must be empty
    assert len(filtered) == 0
    # "No geopolitical markets" message must appear
    assert "지정학 관련 활성 예측 마켓이 없습니다" in rendered
    # Sports titles must not appear in the rendered output
    assert "NBA" not in rendered
    assert "Oscars" not in rendered
    assert "GTA" not in rendered
    # Stats box with real volumes must NOT appear
    assert "$300,000" not in rendered
    assert "$650,000" not in rendered


def test_polymarket_section_empty_markets_shows_dash_not_zero():
    """Bug fix: empty markets list should show '-' in the stat box, not '분석 대상 0'
    or '합산 거래량 $0'.

    Previously filtered_markets was empty but the stats box still rendered the
    count and volume as 0. Now the else-branch renders '-' with no volume line.
    """
    lines, filtered = collect_geopolitical._build_polymarket_section([])
    rendered = "\n".join(lines)

    # Empty input → empty output lists, no lines rendered at all
    assert lines == []
    assert filtered == []
    # Confirm neither the zero-count nor zero-volume strings appear
    assert "분석 대상 0" not in rendered
    assert "$0" not in rendered
