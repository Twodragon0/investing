"""Unit tests for BaseCollector (scripts/common/base_collector.py)."""

from __future__ import annotations

from datetime import UTC
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_dedup_engine():
    """Return a MagicMock that mimics DedupEngine behaviour."""
    engine = MagicMock()
    engine.is_duplicate.return_value = False
    engine.is_duplicate_exact.return_value = False
    return engine


def _make_mock_post_generator():
    """Return a MagicMock that mimics PostGenerator behaviour."""
    gen = MagicMock()
    gen.create_post.return_value = "_posts/2026-03-29-test-post.md"
    return gen


# ---------------------------------------------------------------------------
# Shared patches applied to every test in this module
# ---------------------------------------------------------------------------

_BASE_PATCHES = {
    "common.base_collector.setup_logging": MagicMock(return_value=MagicMock()),
    "common.base_collector.get_verify_ssl": MagicMock(return_value=True),
    "common.base_collector.get_collector_config": MagicMock(return_value={}),
}


def _patched_constructor(dedup_engine=None, post_gen=None):
    """Context-manager stack that patches BaseCollector's __init__ dependencies."""
    import contextlib

    @contextlib.contextmanager
    def _ctx():
        dedup = dedup_engine or _make_mock_dedup_engine()
        pg = post_gen or _make_mock_post_generator()
        with (
            patch("common.base_collector.setup_logging", return_value=MagicMock()),
            patch("common.base_collector.get_verify_ssl", return_value=True),
            patch("common.base_collector.get_collector_config", return_value={}),
            patch("common.base_collector.DedupEngine", return_value=dedup),
            patch("common.base_collector.PostGenerator", return_value=pg),
            patch("common.base_collector.get_kst_now") as mock_now,
        ):
            from datetime import datetime

            mock_now.return_value = datetime(2026, 3, 29, 9, 0, 0, tzinfo=UTC)
            yield dedup, pg

    return _ctx()


# ---------------------------------------------------------------------------
# Concrete subclass used across tests
# ---------------------------------------------------------------------------


def _make_collector_class(
    fetch_return=None,
    process_return=None,
    build_content_return="## 본문",
):
    """Factory that returns a minimal concrete BaseCollector subclass."""
    from common.base_collector import BaseCollector

    class MockCollector(BaseCollector):
        name = "test_collector"
        category = "test-category"
        state_file = "test_collector_seen.json"

        def fetch(self) -> List[Dict[str, Any]]:
            return fetch_return if fetch_return is not None else []

        def process(self, items):
            return process_return if process_return is not None else items

        def build_content(self, items):
            return build_content_return

    return MockCollector


# ---------------------------------------------------------------------------
# TestBaseCollectorInit — initialisation behaviour
# ---------------------------------------------------------------------------


class TestBaseCollectorInit:
    """BaseCollector.__init__ correctly wires up all attributes."""

    def test_name_attribute_set(self):
        with _patched_constructor():
            Cls = _make_collector_class()
            collector = Cls()
        assert collector.name == "test_collector"

    def test_category_attribute_set(self):
        with _patched_constructor():
            Cls = _make_collector_class()
            collector = Cls()
        assert collector.category == "test-category"

    def test_state_file_attribute_set(self):
        with _patched_constructor():
            Cls = _make_collector_class()
            collector = Cls()
        assert collector.state_file == "test_collector_seen.json"

    def test_logger_assigned(self):
        with _patched_constructor():
            Cls = _make_collector_class()
            collector = Cls()
        assert collector.logger is not None

    def test_verify_ssl_assigned(self):
        with _patched_constructor():
            Cls = _make_collector_class()
            collector = Cls()
        assert collector.verify_ssl is True

    def test_today_matches_kst_now(self):
        with _patched_constructor():
            Cls = _make_collector_class()
            collector = Cls()
        assert collector.today == "2026-03-29"

    def test_created_count_starts_at_zero(self):
        with _patched_constructor():
            Cls = _make_collector_class()
            collector = Cls()
        assert collector._created_count == 0

    def test_started_at_initialises_to_zero(self):
        with _patched_constructor():
            Cls = _make_collector_class()
            collector = Cls()
        assert collector._started_at == 0.0

    def test_missing_name_raises_value_error(self):
        import pytest

        from common.base_collector import BaseCollector

        class BadCollector(BaseCollector):
            name = ""
            category = "cat"
            state_file = "state.json"

            def fetch(self):
                return []

            def process(self, items):
                return items

            def build_content(self, items):
                return ""

        with _patched_constructor(), pytest.raises(ValueError, match="name"):
            BadCollector()

    def test_missing_category_raises_value_error(self):
        import pytest

        from common.base_collector import BaseCollector

        class BadCollector(BaseCollector):
            name = "test"
            category = ""
            state_file = "state.json"

            def fetch(self):
                return []

            def process(self, items):
                return items

            def build_content(self, items):
                return ""

        with _patched_constructor(), pytest.raises(ValueError, match="category"):
            BadCollector()

    def test_missing_state_file_raises_value_error(self):
        import pytest

        from common.base_collector import BaseCollector

        class BadCollector(BaseCollector):
            name = "test"
            category = "cat"
            state_file = ""

            def fetch(self):
                return []

            def process(self, items):
                return items

            def build_content(self, items):
                return ""

        with _patched_constructor(), pytest.raises(ValueError, match="state_file"):
            BadCollector()


# ---------------------------------------------------------------------------
# TestRunPipeline — run() orchestration order
# ---------------------------------------------------------------------------


class TestRunPipeline:
    """run() calls fetch → deduplicate → process → build_content in order."""

    def test_run_calls_fetch(self):
        call_log: list[str] = []

        with _patched_constructor():
            from common.base_collector import BaseCollector

            class TrackedCollector(BaseCollector):
                name = "tracked"
                category = "tracked-cat"
                state_file = "tracked_seen.json"

                def fetch(self):
                    call_log.append("fetch")
                    return []

                def process(self, items):
                    call_log.append("process")
                    return items

                def build_content(self, items):
                    call_log.append("build_content")
                    return ""

            collector = TrackedCollector()

        collector.run()
        assert "fetch" in call_log

    def test_run_calls_process_after_fetch(self):
        call_log: list[str] = []

        with _patched_constructor():
            from common.base_collector import BaseCollector

            class TrackedCollector(BaseCollector):
                name = "tracked"
                category = "tracked-cat"
                state_file = "tracked_seen.json"

                def fetch(self):
                    call_log.append("fetch")
                    return [{"title": "T", "source": "S", "link": "http://x.com/1"}]

                def process(self, items):
                    call_log.append("process")
                    return items

                def build_content(self, items):
                    call_log.append("build_content")
                    return "content"

            collector = TrackedCollector()

        collector.run()
        assert call_log.index("fetch") < call_log.index("process")

    def test_run_calls_build_content_after_process(self):
        call_log: list[str] = []

        with _patched_constructor():
            from common.base_collector import BaseCollector

            class TrackedCollector(BaseCollector):
                name = "tracked"
                category = "tracked-cat"
                state_file = "tracked_seen.json"

                def fetch(self):
                    call_log.append("fetch")
                    return [{"title": "T", "source": "S", "link": "http://x.com/1"}]

                def process(self, items):
                    call_log.append("process")
                    return items

                def build_content(self, items):
                    call_log.append("build_content")
                    return "content"

            collector = TrackedCollector()

        collector.run()
        assert call_log.index("process") < call_log.index("build_content")

    def test_run_saves_state(self):
        dedup = _make_mock_dedup_engine()
        with _patched_constructor(dedup_engine=dedup):
            Cls = _make_collector_class(fetch_return=[])
            collector = Cls()
        collector.run()
        dedup.save.assert_called()

    def test_run_increments_created_count_when_post_created(self):
        items = [{"title": "BTC News", "source": "CryptoFeed", "link": "http://x.com/btc"}]
        pg = _make_mock_post_generator()
        pg.create_post.return_value = "_posts/2026-03-29-test.md"

        dedup = _make_mock_dedup_engine()
        dedup.is_duplicate_exact.return_value = False

        with _patched_constructor(dedup_engine=dedup, post_gen=pg):
            Cls = _make_collector_class(fetch_return=items, process_return=items)
            collector = Cls()

        collector.run()
        assert collector._created_count == 1

    def test_run_does_not_create_post_when_duplicate(self):
        items = [{"title": "BTC News", "source": "CryptoFeed", "link": "http://x.com/btc"}]
        pg = _make_mock_post_generator()
        dedup = _make_mock_dedup_engine()
        dedup.is_duplicate_exact.return_value = True  # already seen

        with _patched_constructor(dedup_engine=dedup, post_gen=pg):
            Cls = _make_collector_class(fetch_return=items, process_return=items)
            collector = Cls()

        collector.run()
        pg.create_post.assert_not_called()


# ---------------------------------------------------------------------------
# TestRunEmptyFetch — early-return when fetch returns nothing
# ---------------------------------------------------------------------------


class TestRunEmptyFetch:
    """run() exits early and does not call build_content when items are empty."""

    def test_empty_fetch_skips_build_content(self):
        build_called = {"flag": False}

        with _patched_constructor():
            from common.base_collector import BaseCollector

            class EarlyReturnCollector(BaseCollector):
                name = "early"
                category = "early-cat"
                state_file = "early_seen.json"

                def fetch(self):
                    return []

                def process(self, items):
                    return items

                def build_content(self, items):
                    build_called["flag"] = True
                    return ""

            collector = EarlyReturnCollector()

        collector.run()
        assert build_called["flag"] is False

    def test_empty_fetch_still_saves_state(self):
        dedup = _make_mock_dedup_engine()
        with _patched_constructor(dedup_engine=dedup):
            Cls = _make_collector_class(fetch_return=[])
            collector = Cls()
        collector.run()
        dedup.save.assert_called()

    def test_empty_process_result_skips_post_creation(self):
        """process() returning [] after non-empty fetch still skips post creation."""
        pg = _make_mock_post_generator()
        items = [{"title": "T", "source": "S", "link": "http://x.com/1"}]

        with _patched_constructor(post_gen=pg):
            Cls = _make_collector_class(fetch_return=items, process_return=[])
            collector = Cls()

        collector.run()
        pg.create_post.assert_not_called()


# ---------------------------------------------------------------------------
# TestDeduplicate — URL-based in-session dedup
# ---------------------------------------------------------------------------


class TestDeduplicate:
    """deduplicate() removes items with duplicate URLs in the same session."""

    def test_removes_duplicate_url(self):
        with _patched_constructor():
            Cls = _make_collector_class()
            collector = Cls()

        items = [
            {"title": "A", "link": "http://example.com/a"},
            {"title": "B", "link": "http://example.com/a"},  # same URL
        ]
        result = collector.deduplicate(items)
        assert len(result) == 1

    def test_keeps_unique_urls(self):
        with _patched_constructor():
            Cls = _make_collector_class()
            collector = Cls()

        items = [
            {"title": "A", "link": "http://example.com/a"},
            {"title": "B", "link": "http://example.com/b"},
        ]
        result = collector.deduplicate(items)
        assert len(result) == 2

    def test_empty_list_returns_empty(self):
        with _patched_constructor():
            Cls = _make_collector_class()
            collector = Cls()

        assert collector.deduplicate([]) == []

    def test_items_without_link_are_kept(self):
        with _patched_constructor():
            Cls = _make_collector_class()
            collector = Cls()

        items = [{"title": "No link item"}]
        result = collector.deduplicate(items)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# TestIsDuplicate — cross-session dedup via DedupEngine
# ---------------------------------------------------------------------------


class TestIsDuplicate:
    """is_duplicate() delegates to DedupEngine with correct arguments."""

    def test_returns_false_when_engine_says_new(self):
        dedup = _make_mock_dedup_engine()
        dedup.is_duplicate.return_value = False

        with _patched_constructor(dedup_engine=dedup):
            Cls = _make_collector_class()
            collector = Cls()

        result = collector.is_duplicate("New Title", "SourceA", "http://x.com/1")
        assert result is False

    def test_returns_true_when_engine_says_seen(self):
        dedup = _make_mock_dedup_engine()
        dedup.is_duplicate.return_value = True

        with _patched_constructor(dedup_engine=dedup):
            Cls = _make_collector_class()
            collector = Cls()

        result = collector.is_duplicate("Old Title", "SourceA")
        assert result is True

    def test_passes_title_and_source_to_engine(self):
        dedup = _make_mock_dedup_engine()

        with _patched_constructor(dedup_engine=dedup):
            Cls = _make_collector_class()
            collector = Cls()

        collector.is_duplicate("My Title", "MySource", "http://x.com/news")
        dedup.is_duplicate.assert_called_once_with("My Title", "MySource", "2026-03-29", "http://x.com/news")

    def test_is_duplicate_exact_returns_false_when_new(self):
        dedup = _make_mock_dedup_engine()
        dedup.is_duplicate_exact.return_value = False

        with _patched_constructor(dedup_engine=dedup):
            Cls = _make_collector_class()
            collector = Cls()

        assert collector.is_duplicate_exact("Title", "src") is False

    def test_is_duplicate_exact_passes_today(self):
        dedup = _make_mock_dedup_engine()

        with _patched_constructor(dedup_engine=dedup):
            Cls = _make_collector_class()
            collector = Cls()

        collector.is_duplicate_exact("Title", "src")
        dedup.is_duplicate_exact.assert_called_once_with("Title", "src", "2026-03-29")


# ---------------------------------------------------------------------------
# TestMarkSeen — state recording
# ---------------------------------------------------------------------------


class TestMarkSeen:
    """mark_seen() delegates to DedupEngine with title, source, and today."""

    def test_calls_engine_mark_seen(self):
        dedup = _make_mock_dedup_engine()

        with _patched_constructor(dedup_engine=dedup):
            Cls = _make_collector_class()
            collector = Cls()

        collector.mark_seen("My Title", "MySource")
        dedup.mark_seen.assert_called_once_with("My Title", "MySource", "2026-03-29")

    def test_mark_seen_uses_today_not_arbitrary_date(self):
        dedup = _make_mock_dedup_engine()

        with _patched_constructor(dedup_engine=dedup):
            Cls = _make_collector_class()
            collector = Cls()

        collector.mark_seen("T", "S")
        _, _, date_arg = dedup.mark_seen.call_args[0]
        assert date_arg == collector.today


# ---------------------------------------------------------------------------
# TestBuildTitle — date-based title generation
# ---------------------------------------------------------------------------


class TestBuildTitle:
    """build_title() returns a date-stamped category string."""

    def test_contains_category(self):
        with _patched_constructor():
            Cls = _make_collector_class()
            collector = Cls()

        title = collector.build_title([])
        assert "test-category" in title

    def test_contains_today_date(self):
        with _patched_constructor():
            Cls = _make_collector_class()
            collector = Cls()

        title = collector.build_title([])
        assert "2026-03-29" in title

    def test_default_format(self):
        with _patched_constructor():
            Cls = _make_collector_class()
            collector = Cls()

        title = collector.build_title([{"title": "item"}])
        assert title == "test-category 뉴스 브리핑 - 2026-03-29"


# ---------------------------------------------------------------------------
# TestDefaultTags — category-based default tags
# ---------------------------------------------------------------------------


class TestDefaultTags:
    """default_tags() always includes category, 'news', and 'daily-digest'."""

    def test_contains_category_tag(self):
        with _patched_constructor():
            Cls = _make_collector_class()
            collector = Cls()

        tags = collector.default_tags()
        assert "test-category" in tags

    def test_contains_news_tag(self):
        with _patched_constructor():
            Cls = _make_collector_class()
            collector = Cls()

        assert "news" in collector.default_tags()

    def test_contains_daily_digest_tag(self):
        with _patched_constructor():
            Cls = _make_collector_class()
            collector = Cls()

        assert "daily-digest" in collector.default_tags()

    def test_returns_list(self):
        with _patched_constructor():
            Cls = _make_collector_class()
            collector = Cls()

        assert isinstance(collector.default_tags(), list)


# ---------------------------------------------------------------------------
# TestLogSummary — metric logging
# ---------------------------------------------------------------------------


class TestLogSummary:
    """log_summary() calls log_collection_summary with correct arguments."""

    def test_calls_log_collection_summary(self):
        with _patched_constructor():
            Cls = _make_collector_class()
            collector = Cls()

        with patch("common.base_collector.log_collection_summary") as mock_log:
            collector.log_summary([])
            mock_log.assert_called_once()

    def test_passes_collector_name(self):
        with _patched_constructor():
            Cls = _make_collector_class()
            collector = Cls()

        with patch("common.base_collector.log_collection_summary") as mock_log:
            collector.log_summary([])
            kwargs = mock_log.call_args[1]
            assert kwargs["collector"] == "collect_test_collector"

    def test_counts_unique_items_by_title_source_link(self):
        items = [
            {"title": "A", "source": "S1", "link": "http://x.com/1"},
            {"title": "A", "source": "S1", "link": "http://x.com/1"},  # exact duplicate
            {"title": "B", "source": "S2", "link": "http://x.com/2"},
        ]
        with _patched_constructor():
            Cls = _make_collector_class()
            collector = Cls()

        with patch("common.base_collector.log_collection_summary") as mock_log:
            collector.log_summary(items)
            kwargs = mock_log.call_args[1]
            assert kwargs["unique_items"] == 2

    def test_counts_distinct_sources(self):
        items = [
            {"title": "A", "source": "FeedA", "link": "http://x.com/1"},
            {"title": "B", "source": "FeedA", "link": "http://x.com/2"},
            {"title": "C", "source": "FeedB", "link": "http://x.com/3"},
        ]
        with _patched_constructor():
            Cls = _make_collector_class()
            collector = Cls()

        with patch("common.base_collector.log_collection_summary") as mock_log:
            collector.log_summary(items)
            kwargs = mock_log.call_args[1]
            assert kwargs["source_count"] == 2

    def test_passes_post_created_count(self):
        with _patched_constructor():
            Cls = _make_collector_class()
            collector = Cls()
            collector._created_count = 3

        with patch("common.base_collector.log_collection_summary") as mock_log:
            collector.log_summary([])
            kwargs = mock_log.call_args[1]
            assert kwargs["post_created"] == 3


# ---------------------------------------------------------------------------
# TestCreatePost — PostGenerator delegation
# ---------------------------------------------------------------------------


class TestCreatePost:
    """create_post() delegates to PostGenerator and increments _created_count."""

    def test_increments_created_count_on_success(self):
        pg = _make_mock_post_generator()
        pg.create_post.return_value = "_posts/2026-03-29-test.md"

        with _patched_constructor(post_gen=pg):
            Cls = _make_collector_class()
            collector = Cls()

        collector.create_post("Title", "content")
        assert collector._created_count == 1

    def test_does_not_increment_when_post_gen_returns_none(self):
        pg = _make_mock_post_generator()
        pg.create_post.return_value = None

        with _patched_constructor(post_gen=pg):
            Cls = _make_collector_class()
            collector = Cls()

        collector.create_post("Title", "content")
        assert collector._created_count == 0

    def test_returns_filepath_on_success(self):
        pg = _make_mock_post_generator()
        pg.create_post.return_value = "_posts/2026-03-29-test.md"

        with _patched_constructor(post_gen=pg):
            Cls = _make_collector_class()
            collector = Cls()

        path = collector.create_post("Title", "content")
        assert path == "_posts/2026-03-29-test.md"

    def test_returns_none_when_skipped(self):
        pg = _make_mock_post_generator()
        pg.create_post.return_value = None

        with _patched_constructor(post_gen=pg):
            Cls = _make_collector_class()
            collector = Cls()

        assert collector.create_post("Title", "content") is None

    def test_uses_custom_post_gen_when_provided(self):
        default_pg = _make_mock_post_generator()
        custom_pg = _make_mock_post_generator()
        custom_pg.create_post.return_value = "_posts/custom.md"

        with _patched_constructor(post_gen=default_pg):
            Cls = _make_collector_class()
            collector = Cls()

        collector.create_post("Title", "content", post_gen=custom_pg)
        custom_pg.create_post.assert_called_once()
        default_pg.create_post.assert_not_called()


# ---------------------------------------------------------------------------
# TestSaveState — persistence delegation
# ---------------------------------------------------------------------------


class TestSaveState:
    """save_state() calls DedupEngine.save()."""

    def test_delegates_to_dedup_save(self):
        dedup = _make_mock_dedup_engine()

        with _patched_constructor(dedup_engine=dedup):
            Cls = _make_collector_class()
            collector = Cls()

        collector.save_state()
        dedup.save.assert_called_once()


# ---------------------------------------------------------------------------
# TestErrorHandling — graceful failure
# ---------------------------------------------------------------------------


class TestErrorHandling:
    """BaseCollector.run() handles fetch failures gracefully."""

    def test_fetch_exception_propagates(self):
        """run() does not swallow exceptions from fetch — caller must handle."""
        import pytest

        with _patched_constructor():
            from common.base_collector import BaseCollector

            class BrokenCollector(BaseCollector):
                name = "broken"
                category = "broken-cat"
                state_file = "broken_seen.json"

                def fetch(self):
                    raise RuntimeError("Network failure")

                def process(self, items):
                    return items

                def build_content(self, items):
                    return ""

            collector = BrokenCollector()

        with pytest.raises(RuntimeError, match="Network failure"):
            collector.run()
