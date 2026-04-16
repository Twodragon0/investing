"""Tests for dedup engine (scripts/common/dedup.py)."""

from datetime import UTC

import pytest

from common.dedup import DedupEngine, _make_hash, _normalize, _normalize_url, deduplicate_by_url


class TestNormalize:
    def test_lowercase_and_strip(self):
        assert _normalize("  Hello World  ") == "hello world"

    def test_remove_punctuation(self):
        assert _normalize("BTC hits $100,000!") == "btc hits 100000"

    def test_collapse_whitespace(self):
        assert _normalize("a   b\t\nc") == "a b c"

    def test_empty_string(self):
        assert _normalize("") == ""

    def test_korean_preserved(self):
        result = _normalize("비트코인 가격 상승!")
        assert "비트코인" in result
        assert "!" not in result


class TestMakeHash:
    def test_deterministic(self):
        h1 = _make_hash("title", "source", "2026-03-08")
        h2 = _make_hash("title", "source", "2026-03-08")
        assert h1 == h2

    def test_different_inputs_different_hash(self):
        h1 = _make_hash("title A", "source", "2026-03-08")
        h2 = _make_hash("title B", "source", "2026-03-08")
        assert h1 != h2

    def test_hash_length_24(self):
        h = _make_hash("test", "src", "2026-01-01")
        assert len(h) == 24

    def test_date_truncated_to_10(self):
        h1 = _make_hash("t", "s", "2026-03-08T12:00:00")
        h2 = _make_hash("t", "s", "2026-03-08T23:59:59")
        assert h1 == h2


class TestDedupEngine:
    @pytest.fixture
    def engine(self, tmp_path):
        # Patch STATE_DIR to tmp_path
        import common.dedup as dedup_mod

        original_state_dir = dedup_mod.STATE_DIR
        dedup_mod.STATE_DIR = str(tmp_path)
        eng = DedupEngine("test_dedup.json", max_age_days=30)
        yield eng
        dedup_mod.STATE_DIR = original_state_dir

    def test_not_duplicate_first_time(self, engine):
        assert engine.is_duplicate("Bitcoin hits new ATH", "CoinDesk", "2026-03-08") is False

    def test_exact_duplicate_after_mark(self, engine):
        engine.mark_seen("Bitcoin hits new ATH", "CoinDesk", "2026-03-08")
        assert engine.is_duplicate("Bitcoin hits new ATH", "CoinDesk", "2026-03-08") is True

    def test_empty_title_is_duplicate(self, engine):
        assert engine.is_duplicate("", "source", "2026-03-08") is True
        assert engine.is_duplicate("   ", "source", "2026-03-08") is True

    def test_fuzzy_same_day_duplicate(self, engine):
        engine.mark_seen("Bitcoin price surges past 100K milestone", "CoinDesk", "2026-03-08")
        # Slightly rephrased same-day title
        assert engine.is_duplicate("Bitcoin price surges past 100K milestones", "Reuters", "2026-03-08") is True

    def test_fuzzy_cross_day_needs_higher_similarity(self, engine):
        engine.mark_seen("Bitcoin price surges past 100K milestone", "CoinDesk", "2026-03-07")
        # Same rephrasing but different day - should NOT be flagged with stricter threshold
        result = engine.is_duplicate("Bitcoin price surges past a different topic entirely", "Reuters", "2026-03-08")
        assert result is False

    def test_exact_only_mode(self, engine):
        engine.mark_seen("Daily Digest 2026-03-07", "system", "2026-03-07")
        # Fuzzy would match, but exact-only should not
        assert engine.is_duplicate_exact("Daily Digest 2026-03-08", "system", "2026-03-08") is False

    def test_save_and_reload(self, tmp_path):
        import common.dedup as dedup_mod

        original_state_dir = dedup_mod.STATE_DIR
        dedup_mod.STATE_DIR = str(tmp_path)
        try:
            eng1 = DedupEngine("persist_test.json")
            eng1.mark_seen("Persist me", "src", "2026-03-08")
            eng1.save()

            eng2 = DedupEngine("persist_test.json")
            assert eng2.is_duplicate("Persist me", "src", "2026-03-08") is True
        finally:
            dedup_mod.STATE_DIR = original_state_dir

    def test_corrupt_state_resets(self, tmp_path):
        import common.dedup as dedup_mod

        original_state_dir = dedup_mod.STATE_DIR
        dedup_mod.STATE_DIR = str(tmp_path)
        try:
            state_path = tmp_path / "corrupt.json"
            state_path.write_text("NOT VALID JSON{{{")
            eng = DedupEngine("corrupt.json")
            assert eng.seen == {}
            assert eng.titles == []
        finally:
            dedup_mod.STATE_DIR = original_state_dir

    def test_titles_list_capped_at_5000_on_reload(self, tmp_path):
        import common.dedup as dedup_mod

        original_state_dir = dedup_mod.STATE_DIR
        dedup_mod.STATE_DIR = str(tmp_path)
        try:
            eng = DedupEngine("cap_test.json")
            for i in range(5100):
                eng.mark_seen(f"Title {i}", "src", "2026-03-08")
            eng.save()
            # Pruning happens on reload
            eng2 = DedupEngine("cap_test.json")
            assert len(eng2.titles) <= 5000
        finally:
            dedup_mod.STATE_DIR = original_state_dir

    def test_old_format_migration(self, tmp_path):
        """Old format entries (plain strings) should be migrated to [title, date] pairs."""
        import json

        import common.dedup as dedup_mod

        original_state_dir = dedup_mod.STATE_DIR
        dedup_mod.STATE_DIR = str(tmp_path)
        try:
            state_path = tmp_path / "old_format.json"
            # Old format: titles as plain strings instead of [title, date] pairs
            state_path.write_text(
                json.dumps(
                    {
                        "seen": {"abc123": "2026-03-08T00:00:00"},
                        "titles": ["Old Title One", "Old Title Two"],
                    }
                )
            )
            eng = DedupEngine("old_format.json")
            # Should have migrated: each entry becomes [title, fallback_date]
            assert len(eng.titles) == 2
            for entry in eng.titles:
                assert isinstance(entry, list)
                assert len(entry) == 2
        finally:
            dedup_mod.STATE_DIR = original_state_dir

    def test_is_duplicate_exact_empty_title(self, engine):
        """Empty title should be treated as duplicate in exact mode."""
        assert engine.is_duplicate_exact("", "src", "2026-03-08") is True
        assert engine.is_duplicate_exact("   ", "src", "2026-03-08") is True

    def test_pruning_old_entries(self, tmp_path):
        """Old entries beyond max_age_days should be pruned."""
        import json
        from datetime import datetime, timedelta

        import common.dedup as dedup_mod

        original_state_dir = dedup_mod.STATE_DIR
        dedup_mod.STATE_DIR = str(tmp_path)
        try:
            now = datetime.now(UTC)
            old_ts = (now - timedelta(days=365)).strftime("%Y-%m-%dT%H:%M:%S")
            new_ts = (now - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S")
            state_path = tmp_path / "prune_test.json"
            state_path.write_text(
                json.dumps(
                    {
                        "seen": {
                            "old_hash": old_ts,
                            "new_hash": new_ts,
                        },
                        "titles": [["Old", old_ts[:10]], ["New", new_ts[:10]]],
                    }
                )
            )
            eng = DedupEngine("prune_test.json", max_age_days=30)
            # Old entry should be pruned
            assert "old_hash" not in eng.seen
            assert "new_hash" in eng.seen
        finally:
            dedup_mod.STATE_DIR = original_state_dir

    def test_pruning_old_url_entries(self, tmp_path):
        """Old seen_urls entries beyond max_age_days should be pruned (covers line 112 log)."""
        import json
        from datetime import datetime, timedelta

        import common.dedup as dedup_mod

        original_state_dir = dedup_mod.STATE_DIR
        dedup_mod.STATE_DIR = str(tmp_path)
        try:
            now = datetime.now(UTC)
            old_ts = (now - timedelta(days=365)).strftime("%Y-%m-%dT%H:%M:%S")
            new_ts = (now - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S")
            state_path = tmp_path / "prune_url_test.json"
            state_path.write_text(
                json.dumps(
                    {
                        "seen": {},
                        "titles": [],
                        "seen_urls": {
                            "http://old.example.com/article": old_ts,
                            "http://new.example.com/article": new_ts,
                        },
                    }
                )
            )
            eng = DedupEngine("prune_url_test.json", max_age_days=30)
            assert "http://old.example.com/article" not in eng.seen_urls
            assert "http://new.example.com/article" in eng.seen_urls
        finally:
            dedup_mod.STATE_DIR = original_state_dir

    def test_save_oserror_cleans_up_tmp(self, tmp_path, monkeypatch):
        """OSError during save should be handled; temp file removed if present (lines 130-136)."""
        import common.dedup as dedup_mod

        original_state_dir = dedup_mod.STATE_DIR
        dedup_mod.STATE_DIR = str(tmp_path)
        try:
            eng = DedupEngine("save_err_test.json")
            eng.mark_seen("Some title", "src", "2026-01-01")

            # Make os.replace raise OSError to trigger the except block
            original_replace = dedup_mod.os.replace

            def bad_replace(src, dst):
                raise OSError("disk full")

            monkeypatch.setattr(dedup_mod.os, "replace", bad_replace)
            # Should not raise; just log warning
            eng.save()
        finally:
            monkeypatch.setattr(dedup_mod.os, "replace", original_replace)
            dedup_mod.STATE_DIR = original_state_dir

    def test_save_oserror_tmp_already_gone(self, tmp_path, monkeypatch):
        """OSError during save when temp file also missing (covers the inner OSError pass)."""
        import common.dedup as dedup_mod

        original_state_dir = dedup_mod.STATE_DIR
        dedup_mod.STATE_DIR = str(tmp_path)
        try:
            eng = DedupEngine("save_err2_test.json")
            eng.mark_seen("Another title", "src", "2026-01-01")

            original_replace = dedup_mod.os.replace
            original_remove = dedup_mod.os.remove

            def bad_replace(src, dst):
                raise OSError("disk full")

            def bad_remove(path):
                raise OSError("already gone")

            monkeypatch.setattr(dedup_mod.os, "replace", bad_replace)
            monkeypatch.setattr(dedup_mod.os, "remove", bad_remove)
            # Should not raise
            eng.save()
        finally:
            monkeypatch.setattr(dedup_mod.os, "replace", original_replace)
            monkeypatch.setattr(dedup_mod.os, "remove", original_remove)
            dedup_mod.STATE_DIR = original_state_dir

    def test_load_mtime_oserror_fallback(self, tmp_path, monkeypatch):
        """OSError when reading mtime during migration should use empty fallback_date (lines 77-78)."""
        import json

        import common.dedup as dedup_mod

        original_state_dir = dedup_mod.STATE_DIR
        dedup_mod.STATE_DIR = str(tmp_path)
        try:
            state_path = tmp_path / "mtime_err.json"
            state_path.write_text(
                json.dumps(
                    {
                        "seen": {},
                        "titles": ["Plain String Title"],  # old format triggers migration
                    }
                )
            )
            original_getmtime = dedup_mod.os.path.getmtime

            def bad_getmtime(path):
                raise OSError("no mtime")

            monkeypatch.setattr(dedup_mod.os.path, "getmtime", bad_getmtime)
            eng = DedupEngine("mtime_err.json")
            # Should have migrated with empty fallback_date
            assert len(eng.titles) == 1
            assert eng.titles[0] == ["Plain String Title", ""]
        finally:
            monkeypatch.setattr(dedup_mod.os.path, "getmtime", original_getmtime)
            dedup_mod.STATE_DIR = original_state_dir

    def test_url_dedup_detects_duplicate_url(self, engine):
        """URL seen in seen_urls should trigger duplicate detection (lines 151-154)."""
        engine.mark_seen("Article with URL", "src", "2026-01-01", url="https://example.com/article?utm_source=x")
        # Same URL (tracking param stripped) from different source/title
        assert engine.is_duplicate("Totally Different Title", "other", "2026-01-01", url="https://example.com/article") is True

    def test_url_dedup_different_url_not_duplicate(self, engine):
        """Different URLs should not trigger URL-based duplicate detection."""
        engine.mark_seen("Bitcoin rally continues", "src", "2026-01-01", url="https://example.com/bitcoin-rally")
        assert engine.is_duplicate("Ethereum upgrade announced", "src", "2026-01-01", url="https://example.com/ethereum-upgrade") is False

    def test_mark_seen_with_url_stores_normalized_url(self, engine):
        """mark_seen with URL should store normalized URL in seen_urls (lines 205-207)."""
        engine.mark_seen("Title", "src", "2026-01-01", url="https://Example.COM/path?tracking=1")
        assert "https://example.com/path" in engine.seen_urls

    def test_mark_seen_with_empty_url_does_not_store(self, engine):
        """mark_seen with empty URL should not add anything to seen_urls."""
        engine.mark_seen("Title", "src", "2026-01-01", url="")
        assert len(engine.seen_urls) == 0

    def test_is_duplicate_url_empty_after_normalize_skipped(self, engine):
        """URL that normalizes to empty string should not trigger URL check."""
        # A URL that strips to empty (e.g. just a fragment)
        result = engine.is_duplicate("New title", "src", "2026-01-01", url="#fragment")
        assert result is False


class TestNormalizeUrl:
    def test_empty_string_returns_empty(self):
        assert _normalize_url("") == ""

    def test_strips_query_params(self):
        assert _normalize_url("https://example.com/path?utm_source=twitter") == "https://example.com/path"

    def test_strips_fragment(self):
        assert _normalize_url("https://example.com/path#section") == "https://example.com/path"

    def test_strips_trailing_slash(self):
        assert _normalize_url("https://example.com/path/") == "https://example.com/path"

    def test_lowercases_url(self):
        assert _normalize_url("https://EXAMPLE.COM/Path") == "https://example.com/path"

    def test_strips_leading_whitespace(self):
        assert _normalize_url("  https://example.com/page  ") == "https://example.com/page"


class TestDeduplicateByUrl:
    def test_removes_duplicate_urls_keeps_first(self):
        items = [
            {"link": "https://example.com/a", "title": "First"},
            {"link": "https://example.com/a?utm=x", "title": "Second"},
            {"link": "https://example.com/b", "title": "Third"},
        ]
        result = deduplicate_by_url(items)
        assert len(result) == 2
        assert result[0]["title"] == "First"
        assert result[1]["title"] == "Third"

    def test_items_without_url_always_kept(self):
        items = [
            {"title": "No URL 1"},
            {"title": "No URL 2"},
            {"link": "", "title": "Empty URL"},
        ]
        result = deduplicate_by_url(items)
        assert len(result) == 3

    def test_empty_list_returns_empty(self):
        assert deduplicate_by_url([]) == []

    def test_no_duplicates_unchanged(self):
        items = [
            {"link": "https://example.com/a", "title": "A"},
            {"link": "https://example.com/b", "title": "B"},
        ]
        result = deduplicate_by_url(items)
        assert len(result) == 2

    def test_custom_url_key(self):
        items = [
            {"url": "https://example.com/x", "title": "X1"},
            {"url": "https://example.com/x", "title": "X2"},
        ]
        result = deduplicate_by_url(items, url_key="url")
        assert len(result) == 1
        assert result[0]["title"] == "X1"

    def test_all_duplicates_keeps_one(self):
        items = [
            {"link": "https://example.com/same", "title": "A"},
            {"link": "https://example.com/same", "title": "B"},
            {"link": "https://example.com/same", "title": "C"},
        ]
        result = deduplicate_by_url(items)
        assert len(result) == 1

    def test_logs_removed_count(self, caplog):
        import logging

        items = [
            {"link": "https://example.com/dup", "title": "First"},
            {"link": "https://example.com/dup", "title": "Second"},
        ]
        with caplog.at_level(logging.INFO, logger="common.dedup"):
            deduplicate_by_url(items)
        assert any("URL dedup removed" in r.message for r in caplog.records)
