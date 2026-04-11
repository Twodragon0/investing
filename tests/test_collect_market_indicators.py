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


# ---------------------------------------------------------------------------
# Additional tests (appended — do not modify tests above this line)
# ---------------------------------------------------------------------------

import os  # noqa: E402
import sys  # noqa: E402

SCRIPTS_DIR = os.path.join(os.path.dirname(__file__), "..", "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)


# ── Pure-logic: formatting helpers ──────────────────────────────────────────


def test_rating_to_korean_all_values():
    mapping = {
        "Extreme Fear": "극도의 공포",
        "Fear": "공포",
        "Neutral": "중립",
        "Greed": "탐욕",
        "Extreme Greed": "극도의 탐욕",
    }
    for eng, kor in mapping.items():
        assert collect_market_indicators._rating_to_korean(eng) == kor


def test_rating_to_korean_unknown_passthrough():
    assert collect_market_indicators._rating_to_korean("Unknown") == "Unknown"


def test_fear_greed_signal_boundaries():
    assert "역발상" in collect_market_indicators._fear_greed_signal(20)
    assert "신중한" in collect_market_indicators._fear_greed_signal(40)
    assert "중립" in collect_market_indicators._fear_greed_signal(60)
    assert "리스크" in collect_market_indicators._fear_greed_signal(80)
    assert "과매수" in collect_market_indicators._fear_greed_signal(81)


def test_vix_signal_levels():
    assert "안정" in collect_market_indicators._vix_signal(12)
    assert "보통" in collect_market_indicators._vix_signal(17)
    assert "불안" in collect_market_indicators._vix_signal(25)
    assert "공포" in collect_market_indicators._vix_signal(35)
    assert "패닉" in collect_market_indicators._vix_signal(45)


def test_build_fred_section_returns_empty_for_empty_data():
    result = collect_market_indicators._build_fred_section({})
    assert result == ""


def test_build_fred_section_yield_curve_inversion_warning():
    fred_data = {
        "T10Y2Y": {
            "label": "10Y-2Y 스프레드",
            "value": -0.5,
            "date": "2026-04-11",
            "change": -0.1,
            "series_id": "T10Y2Y",
        },
    }
    result = collect_market_indicators._build_fred_section(fred_data)
    assert "역전" in result or "장단기" in result


def test_build_fred_section_hy_spread_levels():
    # Below 4% -> 낙관론
    fred_low = {
        "BAMLH0A0HYM2": {
            "label": "HY스프레드",
            "value": 3.0,
            "date": "2026-04-11",
            "change": 0.0,
            "series_id": "BAMLH0A0HYM2",
        },
    }
    result_low = collect_market_indicators._build_fred_section(fred_low)
    assert "낙관론" in result_low

    # Above 6% -> 위기
    fred_high = {
        "BAMLH0A0HYM2": {
            "label": "HY스프레드",
            "value": 7.0,
            "date": "2026-04-11",
            "change": 0.5,
            "series_id": "BAMLH0A0HYM2",
        },
    }
    result_high = collect_market_indicators._build_fred_section(fred_high)
    assert "위기" in result_high


def test_build_post_content_dxy_strong_dollar_note():
    now = datetime(2026, 3, 9, 0, 0, tzinfo=UTC)
    content = collect_market_indicators.build_post_content(
        cnn_fg={},
        market_data={
            "DXY": {"price": 107.0, "price_fmt": "107.00", "change_pct": 0.3, "change_pct_fmt": "+0.30%"},
        },
        treasury_news=[],
        put_call_news=[],
        breadth_news=[],
        margin_news=[],
        today="2026-03-09",
        now=now,
    )
    assert "강달러" in content


def test_build_post_content_empty_all_sources():
    now = datetime(2026, 3, 9, 0, 0, tzinfo=UTC)
    content = collect_market_indicators.build_post_content(
        cnn_fg={},
        market_data={},
        treasury_news=[],
        put_call_news=[],
        breadth_news=[],
        margin_news=[],
        today="2026-03-09",
        now=now,
    )
    assert isinstance(content, str)
    assert len(content) > 0


# ── Network-mocked: main() runs without exception ───────────────────────────


def _patch_mi_isolation(monkeypatch, tmp_path):
    """Patch POSTS_DIR and dedup STATE_DIR to tmp_path for full isolation."""
    from common import dedup as dedup_mod
    from common import post_generator as pg_mod

    state_dir = str(tmp_path / "_state")
    monkeypatch.setattr(pg_mod, "POSTS_DIR", str(tmp_path))
    monkeypatch.setattr(dedup_mod, "STATE_DIR", state_dir)

    import contextlib

    with contextlib.suppress(Exception):
        from common import image_generator as ig_mod

        monkeypatch.setattr(ig_mod, "generate_news_briefing_card", lambda *a, **kw: None)


def test_main_runs_with_mocked_network(tmp_path, monkeypatch):
    """MarketIndicatorsCollector.run() completes without raising when all sources return empty."""
    mod = collect_market_indicators

    monkeypatch.setattr(mod, "fetch_cnn_fear_greed", dict)
    monkeypatch.setattr(mod, "fetch_yfinance_market_data", dict)
    monkeypatch.setattr(mod, "fetch_fred_indicators", lambda _key: {})
    monkeypatch.setattr(mod, "fetch_treasury_yield_news", list)
    monkeypatch.setattr(mod, "fetch_put_call_ratio_news", list)
    monkeypatch.setattr(mod, "fetch_market_breadth_news", list)
    monkeypatch.setattr(mod, "fetch_margin_debt_news", list)
    monkeypatch.setattr(mod, "fetch_btc_price", lambda: None)

    _patch_mi_isolation(monkeypatch, tmp_path)

    collector = mod.MarketIndicatorsCollector()
    collector.run()  # must not raise


def test_main_runs_with_full_mocked_data(tmp_path, monkeypatch):
    """MarketIndicatorsCollector.run() creates a post when all sources return data."""
    mod = collect_market_indicators

    monkeypatch.setattr(mod, "fetch_cnn_fear_greed", lambda: {"score": 30.0, "rating": "Fear", "change": -3.0})
    monkeypatch.setattr(
        mod,
        "fetch_yfinance_market_data",
        lambda: {
            "VIX": {"price": 25.0, "price_fmt": "25.00", "change_pct": 2.1, "change_pct_fmt": "+2.10%"},
            "DXY": {"price": 102.0, "price_fmt": "102.00", "change_pct": 0.1, "change_pct_fmt": "+0.10%"},
        },
    )
    monkeypatch.setattr(mod, "fetch_fred_indicators", lambda _key: {})
    monkeypatch.setattr(
        mod,
        "fetch_treasury_yield_news",
        lambda: [{"title": "Yield rises", "link": "https://t", "source": "GN"}],
    )
    monkeypatch.setattr(mod, "fetch_put_call_ratio_news", list)
    monkeypatch.setattr(mod, "fetch_market_breadth_news", list)
    monkeypatch.setattr(mod, "fetch_margin_debt_news", list)
    monkeypatch.setattr(mod, "fetch_btc_price", lambda: None)

    _patch_mi_isolation(monkeypatch, tmp_path)

    collector = mod.MarketIndicatorsCollector()
    collector.run()

    posts = list(tmp_path.glob("*.md"))
    assert len(posts) == 1


# ── Dedup idempotency ────────────────────────────────────────────────────────


def test_dedup_idempotent_market_indicators(tmp_path, monkeypatch):
    """Running MarketIndicatorsCollector twice with same data creates no extra posts."""
    mod = collect_market_indicators

    monkeypatch.setattr(mod, "fetch_cnn_fear_greed", lambda: {"score": 30.0, "rating": "Fear", "change": -3.0})
    monkeypatch.setattr(
        mod,
        "fetch_yfinance_market_data",
        lambda: {
            "VIX": {"price": 25.0, "price_fmt": "25.00", "change_pct": 2.1, "change_pct_fmt": "+2.10%"},
        },
    )
    monkeypatch.setattr(mod, "fetch_fred_indicators", lambda _key: {})
    monkeypatch.setattr(mod, "fetch_treasury_yield_news", list)
    monkeypatch.setattr(mod, "fetch_put_call_ratio_news", list)
    monkeypatch.setattr(mod, "fetch_market_breadth_news", list)
    monkeypatch.setattr(mod, "fetch_margin_debt_news", list)
    monkeypatch.setattr(mod, "fetch_btc_price", lambda: None)

    _patch_mi_isolation(monkeypatch, tmp_path)

    c1 = mod.MarketIndicatorsCollector()
    c1.run()
    posts_after_first = list(tmp_path.glob("*.md"))

    c2 = mod.MarketIndicatorsCollector()
    c2.dedup = c1.dedup  # share dedup state
    c2.run()
    posts_after_second = list(tmp_path.glob("*.md"))

    assert len(posts_after_second) == len(posts_after_first)
