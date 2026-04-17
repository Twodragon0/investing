"""Tests for scripts/common/content_filters.py."""

import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


from scripts.common.content_filters import (
    _DEFAULT_ENTERTAINMENT_KEYWORDS,
    filter_entertainment,
    is_entertainment,
    load_entertainment_keywords,
)

# ---------------------------------------------------------------------------
# _DEFAULT_ENTERTAINMENT_KEYWORDS
# ---------------------------------------------------------------------------


class TestDefaultKeywords:
    def test_nba_in_defaults(self):
        assert "nba" in _DEFAULT_ENTERTAINMENT_KEYWORDS

    def test_nfl_in_defaults(self):
        assert "nfl" in _DEFAULT_ENTERTAINMENT_KEYWORDS

    def test_oscar_in_defaults(self):
        assert "oscar" in _DEFAULT_ENTERTAINMENT_KEYWORDS

    def test_all_lowercase(self):
        for kw in _DEFAULT_ENTERTAINMENT_KEYWORDS:
            assert kw == kw.lower(), f"Keyword not lowercase: {kw!r}"

    def test_frozenset_type(self):
        assert isinstance(_DEFAULT_ENTERTAINMENT_KEYWORDS, frozenset)


# ---------------------------------------------------------------------------
# load_entertainment_keywords
# ---------------------------------------------------------------------------


class TestLoadEntertainmentKeywords:
    def test_fallback_on_exception(self):
        with patch(
            "scripts.common.content_filters.get_collector_config",
            side_effect=FileNotFoundError("no config"),
        ):
            result = load_entertainment_keywords("nonexistent")
            assert result == _DEFAULT_ENTERTAINMENT_KEYWORDS

    def test_fallback_when_no_keywords_section(self):
        with patch(
            "scripts.common.content_filters.get_collector_config",
            return_value={"some_other_key": {}},
        ):
            result = load_entertainment_keywords("crypto_news")
            assert result == _DEFAULT_ENTERTAINMENT_KEYWORDS

    def test_uses_custom_keywords_when_present(self):
        custom = ["soccer", "basketball", "tennis"]
        with patch(
            "scripts.common.content_filters.get_collector_config",
            return_value={"keywords": {"entertainment_keywords": custom}},
        ):
            result = load_entertainment_keywords("crypto_news")
            assert result == frozenset(custom)

    def test_fallback_when_empty_list(self):
        with patch(
            "scripts.common.content_filters.get_collector_config",
            return_value={"keywords": {"entertainment_keywords": []}},
        ):
            result = load_entertainment_keywords("test")
            assert result == _DEFAULT_ENTERTAINMENT_KEYWORDS

    def test_fallback_when_keywords_not_dict(self):
        with patch(
            "scripts.common.content_filters.get_collector_config",
            return_value={"keywords": "not a dict"},
        ):
            result = load_entertainment_keywords("test")
            assert result == _DEFAULT_ENTERTAINMENT_KEYWORDS


# ---------------------------------------------------------------------------
# is_entertainment
# ---------------------------------------------------------------------------


class TestIsEntertainment:
    def test_nba_in_title(self):
        item = {"title": "NBA Finals Game 7 tonight", "description": ""}
        assert is_entertainment(item) is True

    def test_nfl_in_description(self):
        item = {"title": "Weekend sports", "description": "NFL playoffs game"}
        assert is_entertainment(item) is True

    def test_investing_news_not_entertainment(self):
        item = {"title": "Bitcoin ETF approval by SEC", "description": "Major crypto milestone"}
        assert is_entertainment(item) is False

    def test_case_insensitive(self):
        item = {"title": "NBA FINALS", "description": ""}
        assert is_entertainment(item) is True

    def test_empty_item(self):
        assert is_entertainment({}) is False

    def test_custom_keywords(self):
        item = {"title": "Custom sport event", "description": ""}
        custom_kws = frozenset(["custom sport"])
        assert is_entertainment(item, keywords=custom_kws) is True

    def test_oscar_in_title(self):
        item = {"title": "Oscar ceremony 2024", "description": ""}
        assert is_entertainment(item) is True

    def test_bitcoin_not_filtered(self):
        item = {"title": "Bitcoin surges 10%", "description": "Crypto market analysis"}
        assert is_entertainment(item) is False

    def test_missing_keys(self):
        item = {"title": "NBA game recap"}
        assert is_entertainment(item) is True

    def test_description_only_match(self):
        item = {"title": "Weekend update", "description": "super bowl halftime show"}
        assert is_entertainment(item) is True


# ---------------------------------------------------------------------------
# filter_entertainment
# ---------------------------------------------------------------------------


class TestFilterEntertainment:
    def test_filters_entertainment_items(self):
        items = [
            {"title": "NBA Finals tonight", "description": ""},
            {"title": "Bitcoin ETF approved", "description": "Crypto news"},
            {"title": "NFL playoff results", "description": ""},
        ]
        result = filter_entertainment(items)
        assert len(result) == 1
        assert result[0]["title"] == "Bitcoin ETF approved"

    def test_empty_list(self):
        assert filter_entertainment([]) == []

    def test_all_entertainment_filtered(self):
        items = [
            {"title": "NBA game 7", "description": ""},
            {"title": "Oscars ceremony", "description": ""},
        ]
        result = filter_entertainment(items)
        assert result == []

    def test_no_entertainment_all_kept(self):
        items = [
            {"title": "Bitcoin rises 5%", "description": "Crypto rally"},
            {"title": "SEC approves ETF", "description": "Regulatory news"},
        ]
        result = filter_entertainment(items)
        assert len(result) == 2

    def test_custom_keywords(self):
        custom = frozenset(["custom_sport_kw"])
        items = [
            {"title": "custom_sport_kw event", "description": ""},
            {"title": "Bitcoin news", "description": ""},
        ]
        result = filter_entertainment(items, keywords=custom)
        assert len(result) == 1
        assert result[0]["title"] == "Bitcoin news"

    def test_with_logger(self):
        import logging

        logger = logging.getLogger("test")
        items = [{"title": "NBA game", "description": ""}]
        result = filter_entertainment(items, logger=logger)
        assert result == []

    def test_count_reduction_logged(self, caplog):
        import logging

        items = [
            {"title": "NFL playoffs", "description": ""},
            {"title": "Ethereum news", "description": ""},
        ]
        with caplog.at_level(logging.DEBUG, logger="scripts.common.content_filters"):
            result = filter_entertainment(items)
        assert len(result) == 1
