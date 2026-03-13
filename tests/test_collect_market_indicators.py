import importlib
from datetime import UTC, datetime

collect_market_indicators = importlib.import_module("collect_market_indicators")


def test_price_icon_thresholds():
    assert collect_market_indicators._price_icon(1.0) == "🟢"
    assert collect_market_indicators._price_icon(0.2) == "🔼"
    assert collect_market_indicators._price_icon(-0.2) == "🔽"
    assert collect_market_indicators._price_icon(-1.0) == "🔴"
    assert collect_market_indicators._price_icon(None) == ""


def test_format_news_rows_dedup_and_limit():
    items = [
        {"title": "A", "link": "https://a", "source": "S1"},
        {"title": "A", "link": "https://a2", "source": "S2"},
        {"title": "B", "link": "https://b", "source": "S3"},
    ]
    rows = collect_market_indicators._format_news_rows(items, limit=2)
    # Output uses bold numbered format: **1. [title](url)**
    assert "[A]" in rows
    assert "[B]" in rows
    # Dedup: only one "A" entry
    assert rows.count("[A]") == 1


def test_build_post_content_includes_signal_sections():
    now = datetime(2026, 3, 9, 0, 0, tzinfo=UTC)
    content = collect_market_indicators.build_post_content(
        cnn_fg={"score": 18.0, "rating": "Extreme Fear", "change": -2.0},
        market_data={
            "VIX": {"price": 22.5, "price_fmt": "22.50", "change_pct": 3.2, "change_pct_fmt": "+3.20%"},
            "DXY": {"price": 101.2, "price_fmt": "101.20", "change_pct": -0.1, "change_pct_fmt": "-0.10%"},
        },
        treasury_news=[{"title": "Treasury yields rise", "link": "https://t", "source": "Google News"}],
        put_call_news=[{"title": "Put/call ratio spikes", "link": "https://p", "source": "Google News"}],
        breadth_news=[{"title": "Breadth weakens", "link": "https://b", "source": "Google News"}],
        margin_news=[{"title": "Margin debt elevated", "link": "https://m", "source": "Google News"}],
        today="2026-03-09",
        now=now,
    )

    assert "시장 심리 지표" in content
    assert "CNN 공포탐욕 지수" in content
    assert "리스크 레벨 평가" in content or "수집 시각" in content
    assert "수집 시각" in content
