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
    """Verify @property adapters preserve direct attribute access."""

    def test_theme_articles_delegates_to_theme_index(self):
        summarizer = ThemeSummarizer(_make_items())
        # Trigger lazy scoring as collectors do (via get_top_themes()).
        summarizer.get_top_themes()
        # Direct access used by collectors: summarizer._theme_articles.get(key, [])
        articles = summarizer._theme_articles.get("bitcoin", [])
        assert isinstance(articles, list)
        # Identity check: property must forward to the ThemeIndex dict.
        assert summarizer._theme_articles is summarizer._theme_index._theme_articles

    def test_theme_scores_delegates_to_theme_index(self):
        summarizer = ThemeSummarizer(_make_items())
        summarizer._ensure_scored()
        assert summarizer._theme_scores is summarizer._theme_index._theme_scores
        # Bitcoin keywords should pick up at least one positive score.
        assert summarizer._theme_scores.get("bitcoin", 0) > 0

    def test_ensure_scored_flips_scored_flag(self):
        summarizer = ThemeSummarizer(_make_items())
        assert summarizer._scored is False
        summarizer._ensure_scored()
        assert summarizer._scored is True
        # Calling twice must remain idempotent.
        summarizer._ensure_scored()
        assert summarizer._scored is True

    def test_scored_setter_writes_through_to_theme_index(self):
        summarizer = ThemeSummarizer(_make_items())
        summarizer._scored = True
        assert summarizer._theme_index._scored is True
        summarizer._scored = False
        assert summarizer._theme_index._scored is False


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
        scores = [summarizer._theme_scores[key] for _, key, _, _ in result]
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
