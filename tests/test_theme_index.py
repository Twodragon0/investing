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

    def test_theme_with_positive_score_but_no_articles_excluded(self):
        """Themes that have score > 0 but zero matched articles are excluded from top themes.

        This covers the ``if count > 0`` False-branch in get_top_themes (line 91→93).
        We force the state manually: mark_scored + direct attribute assignment.
        """
        idx = ThemeIndex([])
        # Bypass lazy scoring and inject state directly.
        idx._theme_scores = {"bitcoin": 5, "regulation": 3}
        # bitcoin has score but no matched articles; regulation has articles.
        idx._theme_articles = {"bitcoin": [], "regulation": [_REGULATION_ITEM]}
        idx.mark_scored(True)

        result = idx.get_top_themes()
        keys_in_result = [key for _name, key, _emoji, _count in result]
        # bitcoin must be excluded (count == 0) even though score == 5
        assert "bitcoin" not in keys_in_result
        # regulation must be included (count == 1, score == 3)
        assert "regulation" in keys_in_result


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


# ---------------------------------------------------------------------------
# PR2: get_theme_score, has_theme_score, is_scored, mark_scored
# ---------------------------------------------------------------------------


class TestGetThemeScore:
    """Unit tests for ThemeIndex.get_theme_score()."""

    def test_empty_items_returns_default_zero(self):
        idx = ThemeIndex([])
        assert idx.get_theme_score("bitcoin") == 0

    def test_custom_default_returned_for_missing_key(self):
        # After scoring, all THEMES keys are present in _theme_scores.
        # Use a key that cannot exist in THEMES to get the custom default.
        idx = ThemeIndex([])
        assert idx.get_theme_score("__no_such_theme__", default=-1) == -1

    def test_existing_theme_score_positive_for_matching_item(self):
        idx = ThemeIndex([_BITCOIN_ITEM])
        score = idx.get_theme_score("bitcoin")
        assert score > 0

    def test_lazy_scoring_triggered_on_first_call(self):
        idx = ThemeIndex([_BITCOIN_ITEM])
        assert idx._scored is False
        idx.get_theme_score("bitcoin")
        assert idx._scored is True

    def test_score_consistent_with_get_top_themes(self):
        """Score returned by get_theme_score must match the count used in get_top_themes."""
        ts = ThemeSummarizer(_make_items())
        top = ts.get_top_themes()
        # For every key in the top list the stored score must be positive.
        for _name, key, _emoji, _count in top:
            assert ts._theme_index.get_theme_score(key) > 0


class TestHasThemeScore:
    """Unit tests for ThemeIndex.has_theme_score()."""

    def test_empty_items_no_bitcoin_score(self):
        # After scoring empty items, bitcoin key IS present with score 0.
        # has_theme_score checks key existence, not score > 0.
        idx = ThemeIndex([])
        idx._ensure_scored()
        # The key is added for every THEME entry during _score_themes (score=0).
        assert idx.has_theme_score("bitcoin") is True

    def test_matching_item_returns_true(self):
        idx = ThemeIndex([_BITCOIN_ITEM])
        assert idx.has_theme_score("bitcoin") is True

    def test_nonexistent_key_returns_false(self):
        idx = ThemeIndex(_ITEMS)
        assert idx.has_theme_score("__no_such_theme__xyz__") is False

    def test_score_zero_key_still_returns_true(self):
        """Keys with score 0 are still added to _theme_scores; has_theme_score returns True."""
        idx = ThemeIndex([_UNRELATED_ITEM])
        idx._ensure_scored()
        # bitcoin has score 0 for an unrelated item, but the key exists.
        assert idx.has_theme_score("bitcoin") is True

    def test_lazy_scoring_triggered(self):
        idx = ThemeIndex([_BITCOIN_ITEM])
        assert idx._scored is False
        idx.has_theme_score("bitcoin")
        assert idx._scored is True


class TestIsScored:
    """Unit tests for ThemeIndex.is_scored()."""

    def test_false_immediately_after_instantiation(self):
        assert ThemeIndex([]).is_scored() is False

    def test_true_after_ensure_scored(self):
        idx = ThemeIndex([])
        idx._ensure_scored()
        assert idx.is_scored() is True

    def test_true_after_get_top_themes(self):
        idx = ThemeIndex(_make_items())
        idx.get_top_themes()
        assert idx.is_scored() is True

    def test_empty_items_also_becomes_true_after_ensure_scored(self):
        idx = ThemeIndex([])
        idx._ensure_scored()
        assert idx.is_scored() is True


class TestMarkScored:
    """Unit tests for ThemeIndex.mark_scored()."""

    def test_set_true(self):
        idx = ThemeIndex([])
        idx.mark_scored(True)
        assert idx.is_scored() is True

    def test_set_false_reverts_flag(self):
        idx = ThemeIndex([])
        idx._ensure_scored()
        assert idx.is_scored() is True
        idx.mark_scored(False)
        assert idx.is_scored() is False

    def test_default_argument_is_true(self):
        idx = ThemeIndex([])
        idx.mark_scored()
        assert idx.is_scored() is True

    def test_idempotent_double_true(self):
        idx = ThemeIndex([])
        idx.mark_scored(True)
        idx.mark_scored(True)
        assert idx.is_scored() is True

    def test_idempotent_double_false(self):
        idx = ThemeIndex([])
        idx.mark_scored(False)
        idx.mark_scored(False)
        assert idx.is_scored() is False

    def test_skip_scoring_escape_hatch(self):
        """mark_scored(True) on empty items prevents _score_themes execution.

        When the flag is already True, _ensure_scored returns early,
        so _theme_scores stays empty and get_top_themes returns [].
        """
        idx = ThemeIndex([])
        idx.mark_scored(True)
        # _score_themes was never called, so _theme_scores is empty.
        result = idx.get_top_themes()
        assert result == []
        assert idx._theme_scores == {}
