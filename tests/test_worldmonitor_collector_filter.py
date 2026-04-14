"""Tests for entertainment filter integration in WorldMonitorCollector.process()."""

import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.collect_worldmonitor_news import WorldMonitorCollector


def _make_items(*titles):
    return [{"title": t, "description": "", "link": f"https://example.com/{i}", "source": "test"}
            for i, t in enumerate(titles)]


class TestWorldMonitorCollectorFilter:
    """WorldMonitorCollector.process()가 엔터테인먼트 필터를 올바르게 적용하는지 검증."""

    def _make_collector(self):
        with patch("scripts.collect_worldmonitor_news.WorldMonitorCollector.__init__", return_value=None):
            collector = WorldMonitorCollector.__new__(WorldMonitorCollector)
        collector.logger = MagicMock()
        collector._entertainment_filtered_count = 0

        def _record(count):
            collector._entertainment_filtered_count += count

        collector.record_entertainment_filtered = _record
        return collector

    def test_entertainment_items_removed(self):
        collector = self._make_collector()
        items = _make_items(
            "NBA Finals Game 7 Tonight",
            "Federal Reserve raises interest rates",
            "NFL playoff results",
        )
        with patch("scripts.collect_worldmonitor_news.enrich_items"), \
             patch("scripts.collect_worldmonitor_news.deduplicate_by_url", side_effect=lambda x: x):
            result = collector.process(items)

        titles = [i["title"] for i in result]
        assert "Federal Reserve raises interest rates" in titles
        assert not any("NBA" in t for t in titles)
        assert not any("NFL" in t for t in titles)

    def test_non_entertainment_items_kept(self):
        collector = self._make_collector()
        items = _make_items(
            "Oil prices surge amid OPEC tensions",
            "Ukraine ceasefire negotiations stall",
            "Federal Reserve holds rates steady",
        )
        with patch("scripts.collect_worldmonitor_news.enrich_items"), \
             patch("scripts.collect_worldmonitor_news.deduplicate_by_url", side_effect=lambda x: x):
            result = collector.process(items)

        assert len(result) == 3

    def test_record_entertainment_filtered_called(self):
        collector = self._make_collector()
        items = _make_items(
            "Grammy awards ceremony recap",
            "Bitcoin ETF approved by SEC",
        )
        with patch("scripts.collect_worldmonitor_news.enrich_items"), \
             patch("scripts.collect_worldmonitor_news.deduplicate_by_url", side_effect=lambda x: x):
            collector.process(items)

        assert collector._entertainment_filtered_count == 1
