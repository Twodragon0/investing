"""Tests for collect_regulatory collector."""

import importlib
import os
import sys

SCRIPTS_DIR = os.path.join(os.path.dirname(__file__), "..", "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)


# ---------------------------------------------------------------------------
# Pure-logic tests (no network)
# ---------------------------------------------------------------------------


def test_is_noise_title_short_string():
    mod = importlib.import_module("collect_regulatory")
    assert mod._is_noise_title("SEC") is True


def test_is_noise_title_normal_title():
    mod = importlib.import_module("collect_regulatory")
    assert mod._is_noise_title("SEC proposes new crypto disclosure rules") is False


def test_clean_rss_title_removes_sec_suffix():
    mod = importlib.import_module("collect_regulatory")
    assert mod._clean_rss_title("New crypto rules - SEC.gov") == "New crypto rules"


def test_clean_rss_title_handles_japan_fsa_format():
    mod = importlib.import_module("collect_regulatory")
    result = mod._clean_rss_title("Publication,Publication of AI Discussion Paper")
    assert result == "Publication of AI Discussion Paper"


def test_clean_rss_title_passthrough_no_comma():
    mod = importlib.import_module("collect_regulatory")
    title = "CFTC announces enforcement action"
    assert mod._clean_rss_title(title) == title


def test_generate_synthetic_description_known_source():
    mod = importlib.import_module("collect_regulatory")
    result = mod._generate_synthetic_description("New rule announced", "SEC (Google News)")
    assert isinstance(result, str)
    assert len(result) > 0


def test_generate_synthetic_description_unknown_source():
    mod = importlib.import_module("collect_regulatory")
    result = mod._generate_synthetic_description("New rule announced", "UnknownSource")
    assert "New rule announced" in result


# ---------------------------------------------------------------------------
# Network-mocked tests
# ---------------------------------------------------------------------------


def test_collector_run_no_network(tmp_path, monkeypatch):
    """RegulatoryCollector.run() completes without raising when all feeds return empty."""
    mod = importlib.import_module("collect_regulatory")

    monkeypatch.setattr(mod, "fetch_region_feeds", lambda feeds, region: [])
    monkeypatch.setattr(mod, "enrich_items", lambda items, *a, **kw: None)

    from common import post_generator as pg_mod

    monkeypatch.setattr(pg_mod, "POSTS_DIR", str(tmp_path))

    collector = mod.RegulatoryCollector()
    collector.run()


def test_dedup_idempotent_regulatory(tmp_path, monkeypatch):
    """Running RegulatoryCollector twice with same feed items creates no extra posts."""
    mod = importlib.import_module("collect_regulatory")

    fake_items = [
        {
            "title": "SEC proposes new crypto disclosure requirements",
            "description": "The SEC has issued a new proposal requiring crypto exchanges to disclose holdings.",
            "link": "https://sec.gov/news/crypto-disclosure",
            "source": "SEC (Google News)",
            "tags": ["regulation", "sec", "us"],
            "region": "미국",
        }
    ]

    monkeypatch.setattr(mod, "fetch_region_feeds", lambda feeds, region: fake_items if region == "미국" else [])
    monkeypatch.setattr(mod, "enrich_items", lambda items, *a, **kw: None)

    from common import post_generator as pg_mod

    monkeypatch.setattr(pg_mod, "POSTS_DIR", str(tmp_path))

    c1 = mod.RegulatoryCollector()
    c1.run()
    posts_after_first = list(tmp_path.glob("*.md"))

    c2 = mod.RegulatoryCollector()
    c2.dedup = c1.dedup
    c2.run()
    posts_after_second = list(tmp_path.glob("*.md"))

    assert len(posts_after_second) == len(posts_after_first)
