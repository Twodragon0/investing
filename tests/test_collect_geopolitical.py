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
    assert "분석 대상</span></div>" in rendered
    assert '>1</span><span class="stat-label">분석 대상<' in rendered
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
    assert '>2</span><span class="stat-label">분석 대상<' in rendered
    assert "$30,000" in rendered
    assert "$500,000" not in rendered
