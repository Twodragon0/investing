"""Regression tests for ThemeIndex extraction from ThemeSummarizer.

These guard the API surface that external collectors rely on, including
direct ``summarizer._theme_articles.get(...)`` access. See
``scripts/common/theme_index.py`` for the underlying implementation.
"""

from common.summarizer import ThemeSummarizer
from common.theme_index import ThemeIndex


def _make_items():
    """Return a small heterogeneous fixture covering multiple themes."""
    return [
        {
            "title": "Bitcoin surges past 100k",
            "title_original": "Bitcoin surges past 100k",
            "description": "BTC price hits a new all-time high",
        },
        {
            "title": "Ethereum upgrade boosts DeFi",
            "title_original": "Ethereum upgrade boosts DeFi",
            "description": "ETH ecosystem keeps expanding on layer 2",
        },
        {
            "title": "SEC announces new crypto regulation",
            "title_original": "SEC announces new crypto regulation",
            "description": "Regulators set fresh rules for exchanges",
        },
        {
            "title": "Bitcoin ETF inflows accelerate",
            "title_original": "Bitcoin ETF inflows accelerate",
            "description": "Institutional demand drives BTC adoption",
        },
    ]


class TestThemeSummarizerAdapters:
    """Verify ThemeSummarizer exposes scoring state through ThemeIndex public API."""

    def test_theme_scores_accessible_via_theme_index(self):
        summarizer = ThemeSummarizer(_make_items())
        summarizer._ensure_scored()
        # Bitcoin keywords should pick up at least one positive score.
        assert summarizer._theme_index.get_theme_score("bitcoin") > 0

    def test_ensure_scored_flips_scored_flag(self):
        summarizer = ThemeSummarizer(_make_items())
        assert summarizer._theme_index.is_scored() is False
        summarizer._ensure_scored()
        assert summarizer._theme_index.is_scored() is True
        # Calling twice must remain idempotent.
        summarizer._ensure_scored()
        assert summarizer._theme_index.is_scored() is True

    def test_mark_scored_writes_through_to_theme_index(self):
        summarizer = ThemeSummarizer(_make_items())
        summarizer._theme_index.mark_scored(True)
        assert summarizer._theme_index.is_scored() is True
        summarizer._theme_index.mark_scored(False)
        assert summarizer._theme_index.is_scored() is False


class TestGetTopThemes:
    """Behavioural guarantees about ThemeSummarizer.get_top_themes()."""

    def test_returns_list_of_4_tuples(self):
        summarizer = ThemeSummarizer(_make_items())
        result = summarizer.get_top_themes()
        assert isinstance(result, list)
        for entry in result:
            assert isinstance(entry, tuple)
            assert len(entry) == 4
            name, key, emoji, count = entry
            assert isinstance(name, str)
            assert isinstance(key, str)
            assert isinstance(emoji, str)
            assert isinstance(count, int)

    def test_results_sorted_by_score_descending(self):
        summarizer = ThemeSummarizer(_make_items())
        result = summarizer.get_top_themes()
        # Look up the score for each returned key and confirm non-increasing order.
        scores = [summarizer._theme_index.get_theme_score(key) for _, key, _, _ in result]
        assert scores == sorted(scores, reverse=True)

    def test_empty_items_returns_empty_list(self):
        summarizer = ThemeSummarizer([])
        assert summarizer.get_top_themes() == []


class TestThemeIndexDirect:
    """Smoke test the standalone ThemeIndex class."""

    def test_direct_instance_scores_lazily(self):
        index = ThemeIndex(_make_items())
        assert index._scored is False
        index._ensure_scored()
        assert index._scored is True
        assert index._theme_scores  # non-empty
        # Articles dict must be keyed by theme keys present in scores.
        assert set(index._theme_articles.keys()) == set(index._theme_scores.keys())

    def test_get_top_themes_matches_summarizer(self):
        items = _make_items()
        from_index = ThemeIndex(items).get_top_themes()
        from_summarizer = ThemeSummarizer(items).get_top_themes()
        assert from_index == from_summarizer


# ---------------------------------------------------------------------------
# PR1: get_articles_for_theme public method (migration plan step 1)
# ---------------------------------------------------------------------------

_BITCOIN_ITEM = {
    "title": "Bitcoin ETF sees record inflows",
    "title_original": "Bitcoin ETF sees record inflows",
    "description": "Spot bitcoin ETF recorded $1B in a single day.",
}

_REGULATION_ITEM = {
    "title": "SEC sues crypto exchange",
    "title_original": "SEC sues crypto exchange",
    "description": "The SEC filed a lawsuit against a major exchange over regulatory compliance.",
}

_UNRELATED_ITEM = {
    "title": "Weather forecast",
    "title_original": "Weather forecast",
    "description": "Sunny skies expected tomorrow.",
}

_ITEMS = [_BITCOIN_ITEM, _REGULATION_ITEM, _UNRELATED_ITEM]


class TestGetArticlesForTheme:
    """Tests for ThemeSummarizer.get_articles_for_theme()."""

    def test_existing_key_returns_articles(self):
        ts = ThemeSummarizer([_BITCOIN_ITEM])
        result = ts.get_articles_for_theme("bitcoin")
        assert isinstance(result, list)
        assert len(result) >= 1
        assert _BITCOIN_ITEM in result

    def test_missing_key_returns_empty_list(self):
        ts = ThemeSummarizer(_ITEMS)
        result = ts.get_articles_for_theme("nonexistent_theme_xyz")
        assert result == []

    def test_missing_key_returns_custom_default(self):
        sentinel = [{"title": "sentinel"}]
        ts = ThemeSummarizer(_ITEMS)
        result = ts.get_articles_for_theme("nonexistent_theme_xyz", default=sentinel)
        assert result == sentinel
        assert result is not sentinel

    def test_returns_shallow_copy_not_reference(self):
        """Mutating the returned list must not affect subsequent calls."""
        ts = ThemeSummarizer([_BITCOIN_ITEM])
        first = ts.get_articles_for_theme("bitcoin")
        original_len = len(first)
        first.append({"title": "injected"})
        second = ts.get_articles_for_theme("bitcoin")
        assert len(second) == original_len
        assert {"title": "injected"} not in second

    def test_article_dicts_are_shared_references(self):
        """Returned list contains the same dict objects as the original items (depth-1 copy only)."""
        ts = ThemeSummarizer([_BITCOIN_ITEM])
        result = ts.get_articles_for_theme("bitcoin")
        assert any(article is _BITCOIN_ITEM for article in result)

    def test_lazy_scoring_triggered_on_first_call(self):
        ts = ThemeSummarizer([_BITCOIN_ITEM])
        assert ts._theme_index.is_scored() is False
        ts.get_articles_for_theme("bitcoin")
        assert ts._theme_index.is_scored() is True

    def test_multiple_calls_return_equal_lists(self):
        ts = ThemeSummarizer(_ITEMS)
        first = ts.get_articles_for_theme("bitcoin")
        second = ts.get_articles_for_theme("bitcoin")
        assert first == second
        assert first is not second

    def test_empty_items_returns_empty(self):
        ts = ThemeSummarizer([])
        assert ts.get_articles_for_theme("bitcoin") == []
        assert ts.get_articles_for_theme("regulation") == []

    def test_default_none_returns_fresh_empty_list(self):
        ts = ThemeSummarizer([])
        a = ts.get_articles_for_theme("nonexistent", default=None)
        b = ts.get_articles_for_theme("nonexistent", default=None)
        assert a == []
        assert b == []
        assert a is not b


class TestThemeIndexGetArticlesForTheme:
    """Smoke test: ThemeIndex directly also exposes get_articles_for_theme()."""

    def test_direct_call_returns_articles(self):
        index = ThemeIndex([_BITCOIN_ITEM])
        result = index.get_articles_for_theme("bitcoin")
        assert isinstance(result, list)
        assert _BITCOIN_ITEM in result

    def test_returns_shallow_copy(self):
        index = ThemeIndex([_BITCOIN_ITEM])
        first = index.get_articles_for_theme("bitcoin")
        first.append({"title": "x"})
        second = index.get_articles_for_theme("bitcoin")
        assert {"title": "x"} not in second
