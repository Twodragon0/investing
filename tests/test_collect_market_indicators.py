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
    monkeypatch.setattr(mod, "fetch_treasury_yield_news", lambda: ([], 0))
    monkeypatch.setattr(mod, "fetch_put_call_ratio_news", lambda: ([], 0))
    monkeypatch.setattr(mod, "fetch_market_breadth_news", lambda: ([], 0))
    monkeypatch.setattr(mod, "fetch_margin_debt_news", lambda: ([], 0))
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
        lambda: ([{"title": "Yield rises", "link": "https://t", "source": "GN"}], 0),
    )
    monkeypatch.setattr(mod, "fetch_put_call_ratio_news", lambda: ([], 0))
    monkeypatch.setattr(mod, "fetch_market_breadth_news", lambda: ([], 0))
    monkeypatch.setattr(mod, "fetch_margin_debt_news", lambda: ([], 0))
    monkeypatch.setattr(mod, "fetch_btc_price", lambda: None)

    _patch_mi_isolation(monkeypatch, tmp_path)

    collector = mod.MarketIndicatorsCollector()
    collector.run()

    posts = list(tmp_path.glob("*.md"))
    assert len(posts) == 1


# ── Dedup idempotency ────────────────────────────────────────────────────────


# ── Entertainment filter ─────────────────────────────────────────────────────


def test_is_entertainment_sports_keywords():
    """스포츠 키워드가 포함된 제목은 True를 반환해야 합니다."""
    assert collect_market_indicators._is_entertainment("NBA Finals 2026: Heat vs Celtics")
    assert collect_market_indicators._is_entertainment("NHL Stanley Cup playoffs preview")
    assert collect_market_indicators._is_entertainment("NFL Super Bowl odds this week")
    assert collect_market_indicators._is_entertainment("FIFA World Cup Soccer schedule")
    assert collect_market_indicators._is_entertainment("MLB World Series highlights")


def test_is_entertainment_media_keywords():
    """엔터테인먼트 키워드가 포함된 제목은 True를 반환해야 합니다."""
    assert collect_market_indicators._is_entertainment("Netflix Q1 earnings beat estimates")
    assert collect_market_indicators._is_entertainment("Grammy awards ceremony live stream")
    assert collect_market_indicators._is_entertainment("GTA 6 release date announced")
    assert collect_market_indicators._is_entertainment("New movie box office record")
    assert collect_market_indicators._is_entertainment("Celebrity scandal hits tabloids")


def test_is_entertainment_market_news_not_filtered():
    """금융/시장 관련 제목은 False를 반환해야 합니다."""
    assert not collect_market_indicators._is_entertainment("10-year treasury yield rises to 4.5%")
    assert not collect_market_indicators._is_entertainment("Fed raises interest rates by 25bps")
    assert not collect_market_indicators._is_entertainment("S&P 500 advances decline market breadth")
    assert not collect_market_indicators._is_entertainment("Put/call ratio spikes on CBOE")
    assert not collect_market_indicators._is_entertainment("Margin debt elevated at NYSE")
    assert not collect_market_indicators._is_entertainment("DXY dollar index weakens")


def test_filter_rss_items_removes_entertainment():
    """_filter_rss_items는 엔터테인먼트 항목을 제거하고 금융 항목은 유지해야 합니다."""
    items = [
        {"title": "Treasury yield hits 4.8%", "link": "https://a", "source": "Reuters"},
        {"title": "NBA Finals: Lakers vs Celtics game 5", "link": "https://b", "source": "ESPN"},
        {"title": "Put/call ratio signals fear", "link": "https://c", "source": "CBOE"},
        {"title": "Grammy awards top performances", "link": "https://d", "source": "Billboard"},
        {"title": "Market breadth weakens on NYSE", "link": "https://e", "source": "Bloomberg"},
    ]
    filtered, removed = collect_market_indicators._filter_rss_items(items)
    titles = [i["title"] for i in filtered]
    assert "Treasury yield hits 4.8%" in titles
    assert "Put/call ratio signals fear" in titles
    assert "Market breadth weakens on NYSE" in titles
    assert "NBA Finals: Lakers vs Celtics game 5" not in titles
    assert "Grammy awards top performances" not in titles
    assert len(filtered) == 3
    assert removed == 2


def test_filter_rss_items_empty_list():
    """빈 리스트 입력 시 빈 리스트를 반환해야 합니다."""
    filtered, removed = collect_market_indicators._filter_rss_items([])
    assert filtered == []
    assert removed == 0


def test_filter_rss_items_all_pass():
    """금융 뉴스만 있으면 모두 통과해야 합니다."""
    items = [
        {"title": "Yield curve inverts again", "link": "https://a", "source": "FT"},
        {"title": "VIX spikes to 35 on recession fears", "link": "https://b", "source": "CBOE"},
    ]
    filtered, removed = collect_market_indicators._filter_rss_items(items)
    assert filtered == items
    assert removed == 0


def test_entertainment_keywords_set_not_empty():
    """_ENTERTAINMENT_KEYWORDS 세트는 비어있지 않아야 합니다."""
    assert len(collect_market_indicators._ENTERTAINMENT_KEYWORDS) >= 30


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
    monkeypatch.setattr(mod, "fetch_treasury_yield_news", lambda: ([], 0))
    monkeypatch.setattr(mod, "fetch_put_call_ratio_news", lambda: ([], 0))
    monkeypatch.setattr(mod, "fetch_market_breadth_news", lambda: ([], 0))
    monkeypatch.setattr(mod, "fetch_margin_debt_news", lambda: ([], 0))
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
