"""Tests for collect_worldmonitor_news collector."""

import importlib
import os
import sys
from collections import Counter

SCRIPTS_DIR = os.path.join(os.path.dirname(__file__), "..", "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)


# ---------------------------------------------------------------------------
# Pure-logic tests (no network)
# ---------------------------------------------------------------------------


def test_classify_theme_security():
    mod = importlib.import_module("collect_worldmonitor_news")
    assert mod.classify_theme("Iran nuclear deal collapses amid sanctions") == "지정학/안보"


def test_classify_theme_energy():
    mod = importlib.import_module("collect_worldmonitor_news")
    assert mod.classify_theme("OPEC cuts oil production by 1 million barrels") == "에너지"


def test_classify_theme_financial():
    mod = importlib.import_module("collect_worldmonitor_news")
    assert mod.classify_theme("S&P 500 hits record on strong earnings") == "금융시장"


def test_classify_theme_policy():
    mod = importlib.import_module("collect_worldmonitor_news")
    assert mod.classify_theme("Court rules on new financial regulation law") == "정책/법률"


def test_classify_theme_other():
    mod = importlib.import_module("collect_worldmonitor_news")
    assert mod.classify_theme("Community event at local park") == "사회/기타"


def test_impact_label_security_is_high():
    mod = importlib.import_module("collect_worldmonitor_news")
    assert mod.impact_label("지정학/안보") == "높음"


def test_impact_label_social_is_low():
    mod = importlib.import_module("collect_worldmonitor_news")
    assert mod.impact_label("사회/기타") == "낮음"


def test_generate_worldmonitor_summary_returns_string():
    mod = importlib.import_module("collect_worldmonitor_news")
    theme_counter = Counter({"지정학/안보": 8, "에너지": 5, "금융시장": 3})
    issue_items = [
        {"title": "**Iran nuclear talks fail**", "theme": "지정학/안보", "impact": "높음", "source": "BBC"},
        {"title": "**Oil price spikes**", "theme": "에너지", "impact": "중간", "source": "Reuters"},
    ]
    result = mod._generate_worldmonitor_summary(
        theme_counter,
        total_items=16,
        top_sources="BBC (8건), Reuters (5건)",
        issue_items=issue_items,
    )
    assert isinstance(result, str)
    assert len(result) > 0


def test_build_map_snapshot_section_returns_empty_on_empty_snapshot():
    mod = importlib.import_module("collect_worldmonitor_news")
    result = mod.build_map_snapshot_section({})
    assert result == []


def test_build_map_snapshot_section_returns_list_with_data():
    mod = importlib.import_module("collect_worldmonitor_news")
    snapshot = {
        "conflicts": {"acled": [{"country": "Syria"}], "ucdp": []},
        "outages": [],
        "earthquakes": [],
        "climate": [],
        "nav_warnings": [],
        "disruptions": [],
        "density_zones": [],
        "military_flights": [],
        "military_clusters": [],
        "macro": {},
        "energy": {"prices": [{"name": "WTI", "price": 75.5, "change": -0.5, "unit": "USD"}]},
    }
    result = mod.build_map_snapshot_section(snapshot)
    assert isinstance(result, list)
    assert len(result) > 0


# ---------------------------------------------------------------------------
# Network-mocked tests
# ---------------------------------------------------------------------------


def test_collector_run_no_network(tmp_path, monkeypatch):
    """WorldMonitorCollector.run() completes without raising when feeds return empty."""
    mod = importlib.import_module("collect_worldmonitor_news")

    monkeypatch.setattr(mod, "fetch_worldmonitor_feeds", list)
    monkeypatch.setattr(mod, "fetch_worldmonitor_map_snapshot", lambda days=7: {})
    monkeypatch.setattr(mod, "enrich_items", lambda items, *a, **kw: None)

    from common import post_generator as pg_mod

    monkeypatch.setattr(pg_mod, "POSTS_DIR", str(tmp_path))

    collector = mod.WorldMonitorCollector()
    collector.run()


def test_dedup_idempotent_worldmonitor(tmp_path, monkeypatch):
    """Running WorldMonitorCollector twice with same feed items creates no extra posts."""
    mod = importlib.import_module("collect_worldmonitor_news")

    fake_items = [
        {
            "title": "Iran sanctions tighten amid nuclear standoff",
            "description": "World leaders react to Iran nuclear developments.",
            "link": "https://bbc.com/world/iran-nuclear",
            "source": "WorldMonitor/BBC World",
            "tags": ["worldmonitor", "geopolitics"],
        }
    ]

    monkeypatch.setattr(mod, "fetch_worldmonitor_feeds", lambda: fake_items)
    monkeypatch.setattr(mod, "fetch_worldmonitor_map_snapshot", lambda days=7: {})
    monkeypatch.setattr(mod, "enrich_items", lambda items, *a, **kw: None)

    from common import post_generator as pg_mod

    monkeypatch.setattr(pg_mod, "POSTS_DIR", str(tmp_path))

    c1 = mod.WorldMonitorCollector()
    c1.run()
    posts_after_first = list(tmp_path.glob("*.md"))

    c2 = mod.WorldMonitorCollector()
    c2.dedup = c1.dedup
    c2.run()
    posts_after_second = list(tmp_path.glob("*.md"))

    assert len(posts_after_second) == len(posts_after_first)
