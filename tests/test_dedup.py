"""Tests for dedup engine (scripts/common/dedup.py)."""


import pytest

from common.dedup import DedupEngine, _make_hash, _normalize


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

    def test_hash_length_16(self):
        h = _make_hash("test", "src", "2026-01-01")
        assert len(h) == 16

    def test_date_truncated_to_10(self):
        h1 = _make_hash("t", "s", "2026-03-08T12:00:00")
        h2 = _make_hash("t", "s", "2026-03-08T23:59:59")
        assert h1 == h2


class TestDedupEngine:
    @pytest.fixture
    def engine(self, tmp_path):
        state_file = str(tmp_path / "test_dedup.json")
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
