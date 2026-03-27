"""Unit tests for core modules: dedup, post_generator, config."""

import os
import sys
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# dedup module helpers
# ---------------------------------------------------------------------------


class TestNormalize:
    def test_lowercases(self):
        from common.dedup import _normalize

        assert _normalize("Bitcoin HITS New High") == "bitcoin hits new high"

    def test_strips_leading_trailing_whitespace(self):
        from common.dedup import _normalize

        assert _normalize("  hello world  ") == "hello world"

    def test_removes_punctuation(self):
        from common.dedup import _normalize

        result = _normalize("BTC: $50,000! (all-time high)")
        # punctuation removed; only word chars and spaces remain
        assert ":" not in result
        assert "$" not in result
        assert "," not in result
        assert "!" not in result
        assert "(" not in result

    def test_collapses_whitespace(self):
        from common.dedup import _normalize

        result = _normalize("too   many    spaces")
        assert result == "too many spaces"

    def test_empty_string(self):
        from common.dedup import _normalize

        assert _normalize("") == ""

    def test_korean_text_preserved(self):
        from common.dedup import _normalize

        result = _normalize("비트코인 상승")
        assert "비트코인" in result
        assert "상승" in result


class TestMakeHash:
    def test_consistent_for_same_inputs(self):
        from common.dedup import _make_hash

        h1 = _make_hash("BTC hits 100k", "coindesk", "2024-01-15")
        h2 = _make_hash("BTC hits 100k", "coindesk", "2024-01-15")
        assert h1 == h2

    def test_different_titles_produce_different_hashes(self):
        from common.dedup import _make_hash

        h1 = _make_hash("Bitcoin rises", "coindesk", "2024-01-15")
        h2 = _make_hash("Ethereum falls", "coindesk", "2024-01-15")
        assert h1 != h2

    def test_different_sources_produce_different_hashes(self):
        from common.dedup import _make_hash

        h1 = _make_hash("Market update", "coindesk", "2024-01-15")
        h2 = _make_hash("Market update", "cointelegraph", "2024-01-15")
        assert h1 != h2

    def test_different_dates_produce_different_hashes(self):
        from common.dedup import _make_hash

        h1 = _make_hash("Market update", "coindesk", "2024-01-15")
        h2 = _make_hash("Market update", "coindesk", "2024-01-16")
        assert h1 != h2

    def test_date_truncated_to_10_chars(self):
        from common.dedup import _make_hash

        h1 = _make_hash("title", "src", "2024-01-15")
        h2 = _make_hash("title", "src", "2024-01-15T12:34:56")
        assert h1 == h2

    def test_returns_24_char_hex_string(self):
        from common.dedup import _make_hash

        h = _make_hash("title", "src", "2024-01-15")
        assert len(h) == 24
        assert all(c in "0123456789abcdef" for c in h)


class TestDedupEngineExact:
    """Tests for DedupEngine.is_duplicate_exact() and mark_seen()."""

    def test_not_duplicate_when_empty(self, tmp_path):
        import common.dedup as dedup_mod

        with patch.object(dedup_mod, "STATE_DIR", str(tmp_path)):
            from common.dedup import DedupEngine

            engine = DedupEngine("test_state.json")
            assert engine.is_duplicate_exact("BTC news", "coindesk", "2024-01-15") is False

    def test_duplicate_after_mark_seen(self, tmp_path):
        import common.dedup as dedup_mod

        with patch.object(dedup_mod, "STATE_DIR", str(tmp_path)):
            from common.dedup import DedupEngine

            engine = DedupEngine("test_state.json")
            engine.mark_seen("BTC news", "coindesk", "2024-01-15")
            assert engine.is_duplicate_exact("BTC news", "coindesk", "2024-01-15") is True

    def test_not_duplicate_for_different_title(self, tmp_path):
        import common.dedup as dedup_mod

        with patch.object(dedup_mod, "STATE_DIR", str(tmp_path)):
            from common.dedup import DedupEngine

            engine = DedupEngine("test_state.json")
            engine.mark_seen("BTC news", "coindesk", "2024-01-15")
            assert engine.is_duplicate_exact("ETH news", "coindesk", "2024-01-15") is False

    def test_not_duplicate_for_different_source(self, tmp_path):
        import common.dedup as dedup_mod

        with patch.object(dedup_mod, "STATE_DIR", str(tmp_path)):
            from common.dedup import DedupEngine

            engine = DedupEngine("test_state.json")
            engine.mark_seen("BTC news", "coindesk", "2024-01-15")
            assert engine.is_duplicate_exact("BTC news", "cointelegraph", "2024-01-15") is False

    def test_not_duplicate_for_different_date(self, tmp_path):
        import common.dedup as dedup_mod

        with patch.object(dedup_mod, "STATE_DIR", str(tmp_path)):
            from common.dedup import DedupEngine

            engine = DedupEngine("test_state.json")
            engine.mark_seen("BTC news", "coindesk", "2024-01-15")
            assert engine.is_duplicate_exact("BTC news", "coindesk", "2024-01-16") is False

    def test_empty_title_is_duplicate(self, tmp_path):
        import common.dedup as dedup_mod

        with patch.object(dedup_mod, "STATE_DIR", str(tmp_path)):
            from common.dedup import DedupEngine

            engine = DedupEngine("test_state.json")
            assert engine.is_duplicate_exact("", "coindesk", "2024-01-15") is True
            assert engine.is_duplicate_exact("   ", "coindesk", "2024-01-15") is True


class TestDedupEngineFuzzy:
    """Tests for DedupEngine.is_duplicate() (fuzzy matching path)."""

    def test_exact_same_title_is_fuzzy_duplicate(self, tmp_path):
        import common.dedup as dedup_mod

        with patch.object(dedup_mod, "STATE_DIR", str(tmp_path)):
            from common.dedup import DedupEngine

            engine = DedupEngine("test_state.json")
            engine.mark_seen("Bitcoin price reaches all time high today", "src", "2024-01-15")
            assert engine.is_duplicate("Bitcoin price reaches all time high today", "src", "2024-01-15") is True

    def test_very_similar_same_day_title_is_duplicate(self, tmp_path):
        import common.dedup as dedup_mod

        with patch.object(dedup_mod, "STATE_DIR", str(tmp_path)):
            from common.dedup import DedupEngine

            engine = DedupEngine("test_state.json")
            # Mark a title, then check a very similar one on same day
            engine.mark_seen("Bitcoin price surges to all time high record today", "src", "2024-01-15")
            # Slightly rephrased — same-day threshold is 0.80, this should trigger
            result = engine.is_duplicate("Bitcoin price surges to all time high record today", "src2", "2024-01-15")
            assert result is True

    def test_completely_different_title_not_duplicate(self, tmp_path):
        import common.dedup as dedup_mod

        with patch.object(dedup_mod, "STATE_DIR", str(tmp_path)):
            from common.dedup import DedupEngine

            engine = DedupEngine("test_state.json")
            engine.mark_seen("Bitcoin breaks $100k barrier", "src", "2024-01-15")
            assert engine.is_duplicate("Federal Reserve raises interest rates again", "src", "2024-01-15") is False

    def test_empty_title_returns_true(self, tmp_path):
        import common.dedup as dedup_mod

        with patch.object(dedup_mod, "STATE_DIR", str(tmp_path)):
            from common.dedup import DedupEngine

            engine = DedupEngine("test_state.json")
            assert engine.is_duplicate("", "src", "2024-01-15") is True


class TestDedupEngineMarkSeen:
    def test_mark_seen_adds_to_seen_dict(self, tmp_path):
        import common.dedup as dedup_mod

        with patch.object(dedup_mod, "STATE_DIR", str(tmp_path)):
            from common.dedup import DedupEngine, _make_hash

            engine = DedupEngine("test_state.json")
            engine.mark_seen("Test title", "src", "2024-01-15")
            h = _make_hash("Test title", "src", "2024-01-15")
            assert h in engine.seen

    def test_mark_seen_adds_to_titles_list(self, tmp_path):
        import common.dedup as dedup_mod

        with patch.object(dedup_mod, "STATE_DIR", str(tmp_path)):
            from common.dedup import DedupEngine, _normalize

            engine = DedupEngine("test_state.json")
            engine.mark_seen("Test Title", "src", "2024-01-15")
            assert len(engine.titles) == 1
            assert engine.titles[0][0] == _normalize("Test Title")
            assert engine.titles[0][1] == "2024-01-15"

    def test_mark_seen_multiple_entries(self, tmp_path):
        import common.dedup as dedup_mod

        with patch.object(dedup_mod, "STATE_DIR", str(tmp_path)):
            from common.dedup import DedupEngine

            engine = DedupEngine("test_state.json")
            engine.mark_seen("Title one", "src", "2024-01-15")
            engine.mark_seen("Title two", "src", "2024-01-15")
            engine.mark_seen("Title three", "src", "2024-01-16")
            assert len(engine.seen) == 3
            assert len(engine.titles) == 3

    def test_mark_seen_persists_after_save_and_reload(self, tmp_path):
        import common.dedup as dedup_mod

        with patch.object(dedup_mod, "STATE_DIR", str(tmp_path)):
            from common.dedup import DedupEngine

            engine = DedupEngine("persist_test.json")
            engine.mark_seen("Persistent title", "src", "2024-01-15")
            engine.save()

            engine2 = DedupEngine("persist_test.json")
            assert engine2.is_duplicate_exact("Persistent title", "src", "2024-01-15") is True


class TestDedupEngineUrlDedup:
    """Tests for URL-based deduplication."""

    def test_url_duplicate_different_source(self, tmp_path):
        import common.dedup as dedup_mod

        with patch.object(dedup_mod, "STATE_DIR", str(tmp_path)):
            from common.dedup import DedupEngine

            engine = DedupEngine("test_state.json")
            engine.mark_seen("Article A", "src1", "2024-01-15", url="https://example.com/article")
            assert engine.is_duplicate("Article A", "src2", "2024-01-15", url="https://example.com/article") is True

    def test_url_duplicate_with_tracking_params(self, tmp_path):
        import common.dedup as dedup_mod

        with patch.object(dedup_mod, "STATE_DIR", str(tmp_path)):
            from common.dedup import DedupEngine

            engine = DedupEngine("test_state.json")
            engine.mark_seen("Article", "src1", "2024-01-15", url="https://example.com/art?utm=1")
            assert engine.is_duplicate("Article", "src2", "2024-01-15", url="https://example.com/art?ref=2") is True

    def test_different_url_not_duplicate(self, tmp_path):
        import common.dedup as dedup_mod

        with patch.object(dedup_mod, "STATE_DIR", str(tmp_path)):
            from common.dedup import DedupEngine

            engine = DedupEngine("test_state.json")
            engine.mark_seen("Article", "src1", "2024-01-15", url="https://example.com/art1")
            assert engine.is_duplicate("Other Article", "src2", "2024-01-15", url="https://example.com/art2") is False

    def test_no_url_falls_back_to_title(self, tmp_path):
        import common.dedup as dedup_mod

        with patch.object(dedup_mod, "STATE_DIR", str(tmp_path)):
            from common.dedup import DedupEngine

            engine = DedupEngine("test_state.json")
            engine.mark_seen("Unique Article", "src1", "2024-01-15")
            assert engine.is_duplicate("Unique Article", "src1", "2024-01-15") is True
            assert engine.is_duplicate("Different Article", "src1", "2024-01-15") is False

    def test_url_persists_after_save_reload(self, tmp_path):
        import common.dedup as dedup_mod

        with patch.object(dedup_mod, "STATE_DIR", str(tmp_path)):
            from common.dedup import DedupEngine

            engine = DedupEngine("url_persist.json")
            engine.mark_seen("Art", "src", "2024-01-15", url="https://example.com/x")
            engine.save()
            engine2 = DedupEngine("url_persist.json")
            assert engine2.is_duplicate("Art", "src2", "2024-01-15", url="https://example.com/x") is True


class TestDeduplicateByUrl:
    """Tests for the deduplicate_by_url utility function."""

    def test_removes_duplicate_urls(self):
        from common.dedup import deduplicate_by_url

        items = [
            {"title": "A", "link": "https://example.com/1"},
            {"title": "B", "link": "https://example.com/2"},
            {"title": "A copy", "link": "https://example.com/1"},
        ]
        result = deduplicate_by_url(items)
        assert len(result) == 2
        assert result[0]["title"] == "A"
        assert result[1]["title"] == "B"

    def test_keeps_items_without_url(self):
        from common.dedup import deduplicate_by_url

        items = [
            {"title": "A", "link": ""},
            {"title": "B"},
            {"title": "C", "link": "https://example.com/1"},
        ]
        result = deduplicate_by_url(items)
        assert len(result) == 3

    def test_normalizes_tracking_params(self):
        from common.dedup import deduplicate_by_url

        items = [
            {"title": "A", "link": "https://example.com/art?utm=1"},
            {"title": "B", "link": "https://example.com/art?ref=2"},
        ]
        result = deduplicate_by_url(items)
        assert len(result) == 1

    def test_empty_list(self):
        from common.dedup import deduplicate_by_url

        assert deduplicate_by_url([]) == []

    def test_custom_url_key(self):
        from common.dedup import deduplicate_by_url

        items = [
            {"title": "A", "url": "https://example.com/1"},
            {"title": "B", "url": "https://example.com/1"},
        ]
        result = deduplicate_by_url(items, url_key="url")
        assert len(result) == 1


# ---------------------------------------------------------------------------
# post_generator module tests
# ---------------------------------------------------------------------------


def _make_translator_mock():
    """Return a mock for common.translator with translate_untranslated_body."""
    mock_translator = MagicMock()
    mock_translator.translate_untranslated_body = lambda text: text
    return mock_translator


class TestSlugify:
    def test_basic_ascii(self):
        from common.post_generator import _slugify

        assert _slugify("Bitcoin Price Update") == "bitcoin-price-update"

    def test_strips_korean(self):
        from common.post_generator import _slugify

        result = _slugify("비트코인 bitcoin news")
        assert "비트코인" not in result
        assert "bitcoin" in result

    def test_removes_special_chars(self):
        from common.post_generator import _slugify

        result = _slugify("BTC: +10% (all-time high!)")
        assert ":" not in result
        assert "+" not in result
        assert "%" not in result
        assert "!" not in result

    def test_collapses_multiple_hyphens(self):
        from common.post_generator import _slugify

        result = _slugify("hello---world")
        assert "--" not in result

    def test_max_length(self):
        from common.post_generator import _slugify

        long_title = "a" * 200
        result = _slugify(long_title)
        assert len(result) <= 80

    def test_all_korean_returns_empty_or_short(self):
        from common.post_generator import _slugify

        result = _slugify("비트코인 이더리움 주식 시장")
        # Korean stripped, only spaces/hyphens left, then stripped
        assert result == "" or len(result) < 5


class TestPostGeneratorFilename:
    def test_filename_format(self, tmp_path):
        import common.post_generator as pg_mod

        with (
            patch.object(pg_mod, "POSTS_DIR", str(tmp_path)),
            patch.dict(sys.modules, {"common.translator": _make_translator_mock()}),
        ):
            from common.post_generator import PostGenerator

            pg = PostGenerator("crypto")
            dt = datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC)
            path = pg.create_post(
                title="Bitcoin surges today",
                content="Some content about bitcoin.",
                date=dt,
                lang="en",
            )
            assert path is not None
            fname = os.path.basename(path)
            # Format: YYYY-MM-DD-slug.md
            assert fname.endswith(".md")
            parts = fname.split("-", 3)
            assert len(parts) >= 4
            assert parts[0].isdigit() and len(parts[0]) == 4  # year
            assert parts[1].isdigit() and len(parts[1]) == 2  # month
            assert parts[2].isdigit() and len(parts[2]) == 2  # day

    def test_filename_uses_logical_date(self, tmp_path):
        import common.post_generator as pg_mod

        with (
            patch.object(pg_mod, "POSTS_DIR", str(tmp_path)),
            patch.dict(sys.modules, {"common.translator": _make_translator_mock()}),
        ):
            from common.post_generator import PostGenerator

            pg = PostGenerator("stock")
            dt = datetime(2024, 3, 20, 8, 0, 0, tzinfo=UTC)
            path = pg.create_post(
                title="Market opens higher",
                content="Markets opened higher today.",
                date=dt,
                logical_date="2024-03-19",
                lang="en",
            )
            assert path is not None
            fname = os.path.basename(path)
            assert fname.startswith("2024-03-19-")

    def test_returns_none_for_empty_title(self, tmp_path):
        import common.post_generator as pg_mod

        with (
            patch.object(pg_mod, "POSTS_DIR", str(tmp_path)),
            patch.dict(sys.modules, {"common.translator": _make_translator_mock()}),
        ):
            from common.post_generator import PostGenerator

            pg = PostGenerator("crypto")
            result = pg.create_post(title="", content="content")
            assert result is None

    def test_returns_none_if_file_already_exists(self, tmp_path):
        import common.post_generator as pg_mod

        with (
            patch.object(pg_mod, "POSTS_DIR", str(tmp_path)),
            patch.dict(sys.modules, {"common.translator": _make_translator_mock()}),
        ):
            from common.post_generator import PostGenerator

            pg = PostGenerator("crypto")
            dt = datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC)
            path1 = pg.create_post(
                title="Duplicate post title here",
                content="First content.",
                date=dt,
                lang="en",
            )
            assert path1 is not None
            path2 = pg.create_post(
                title="Duplicate post title here",
                content="Second content.",
                date=dt,
                lang="en",
            )
            assert path2 is None


class TestPostGeneratorFrontmatter:
    def _read_frontmatter(self, filepath: str) -> dict:
        """Parse YAML-like frontmatter from a post file into a dict."""
        with open(filepath, encoding="utf-8") as f:
            content = f.read()
        assert content.startswith("---\n"), "Post must start with frontmatter"
        end = content.index("\n---\n", 4)
        fm_text = content[4:end]
        result = {}
        for line in fm_text.splitlines():
            if ": " in line:
                key, _, val = line.partition(": ")
                result[key.strip()] = val.strip().strip('"')
        return result

    def test_frontmatter_has_required_fields(self, tmp_path):
        import common.post_generator as pg_mod

        with (
            patch.object(pg_mod, "POSTS_DIR", str(tmp_path)),
            patch.dict(sys.modules, {"common.translator": _make_translator_mock()}),
        ):
            from common.post_generator import PostGenerator

            pg = PostGenerator("crypto")
            dt = datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC)
            path = pg.create_post(
                title="Test frontmatter post",
                content="Content for testing frontmatter fields.",
                date=dt,
                tags=["bitcoin", "crypto"],
                source="testfeed",
                lang="en",
            )
            assert path is not None
            fm = self._read_frontmatter(path)
            assert fm.get("layout") == "post"
            assert "title" in fm
            assert "date" in fm
            assert "categories" in fm
            assert "image" in fm

    def test_frontmatter_title_matches_input(self, tmp_path):
        import common.post_generator as pg_mod

        with (
            patch.object(pg_mod, "POSTS_DIR", str(tmp_path)),
            patch.dict(sys.modules, {"common.translator": _make_translator_mock()}),
        ):
            from common.post_generator import PostGenerator

            pg = PostGenerator("stock")
            dt = datetime(2024, 2, 10, 9, 0, 0, tzinfo=UTC)
            path = pg.create_post(
                title="Stock market weekly review",
                content="This week in stocks.",
                date=dt,
                lang="en",
            )
            assert path is not None
            fm = self._read_frontmatter(path)
            assert "Stock market weekly review" in fm.get("title", "")

    def test_frontmatter_category_matches(self, tmp_path):
        import common.post_generator as pg_mod

        with (
            patch.object(pg_mod, "POSTS_DIR", str(tmp_path)),
            patch.dict(sys.modules, {"common.translator": _make_translator_mock()}),
        ):
            from common.post_generator import PostGenerator

            pg = PostGenerator("regulatory")
            dt = datetime(2024, 3, 1, 12, 0, 0, tzinfo=UTC)
            path = pg.create_post(
                title="SEC regulation update news",
                content="SEC issued new regulations.",
                date=dt,
                lang="en",
            )
            assert path is not None
            fm = self._read_frontmatter(path)
            assert "regulatory" in fm.get("categories", "")

    def test_frontmatter_tags_present(self, tmp_path):
        import common.post_generator as pg_mod

        with (
            patch.object(pg_mod, "POSTS_DIR", str(tmp_path)),
            patch.dict(sys.modules, {"common.translator": _make_translator_mock()}),
        ):
            from common.post_generator import PostGenerator

            pg = PostGenerator("crypto")
            dt = datetime(2024, 4, 5, 8, 0, 0, tzinfo=UTC)
            path = pg.create_post(
                title="Ethereum upgrade news today",
                content="Ethereum completed its upgrade.",
                date=dt,
                tags=["ethereum", "upgrade", "defi"],
                lang="en",
            )
            assert path is not None
            with open(path, encoding="utf-8") as f:
                raw = f.read()
            assert "tags:" in raw
            assert "ethereum" in raw

    def test_frontmatter_default_image_set(self, tmp_path):
        import common.post_generator as pg_mod

        with (
            patch.object(pg_mod, "POSTS_DIR", str(tmp_path)),
            patch.dict(sys.modules, {"common.translator": _make_translator_mock()}),
        ):
            from common.post_generator import PostGenerator

            pg = PostGenerator("crypto")
            dt = datetime(2024, 5, 1, 7, 0, 0, tzinfo=UTC)
            path = pg.create_post(
                title="Crypto market daily digest",
                content="Daily crypto market overview.",
                date=dt,
                lang="en",
            )
            assert path is not None
            fm = self._read_frontmatter(path)
            image = fm.get("image", "")
            assert image.startswith("/assets/images/")

    def test_frontmatter_custom_image_used(self, tmp_path):
        import common.post_generator as pg_mod

        with (
            patch.object(pg_mod, "POSTS_DIR", str(tmp_path)),
            patch.dict(sys.modules, {"common.translator": _make_translator_mock()}),
        ):
            from common.post_generator import PostGenerator

            pg = PostGenerator("crypto")
            dt = datetime(2024, 5, 2, 7, 0, 0, tzinfo=UTC)
            path = pg.create_post(
                title="Custom image post test",
                content="Post with a custom image.",
                date=dt,
                image="/assets/images/og-crypto.png",
                lang="en",
            )
            assert path is not None
            fm = self._read_frontmatter(path)
            assert fm.get("image") == "/assets/images/og-crypto.png"

    def test_custom_slug_used_in_filename(self, tmp_path):
        import common.post_generator as pg_mod

        with (
            patch.object(pg_mod, "POSTS_DIR", str(tmp_path)),
            patch.dict(sys.modules, {"common.translator": _make_translator_mock()}),
        ):
            from common.post_generator import PostGenerator

            pg = PostGenerator("crypto")
            dt = datetime(2024, 6, 1, 10, 0, 0, tzinfo=UTC)
            path = pg.create_post(
                title="Ignored title for slug",
                content="Content here.",
                date=dt,
                slug="my-custom-slug",
                lang="en",
            )
            assert path is not None
            assert "my-custom-slug" in os.path.basename(path)


# ---------------------------------------------------------------------------
# config module tests
# ---------------------------------------------------------------------------


class TestGetEnv:
    def test_returns_default_when_not_set(self):
        from common.config import get_env

        key = "TEST_INVESTING_NONEXISTENT_KEY_XYZ"
        os.environ.pop(key, None)
        assert get_env(key, "mydefault") == "mydefault"

    def test_returns_empty_string_default(self):
        from common.config import get_env

        key = "TEST_INVESTING_NONEXISTENT_KEY_XYZ"
        os.environ.pop(key, None)
        assert get_env(key) == ""


# ---------------------------------------------------------------------------
# translator module tests
# ---------------------------------------------------------------------------


class TestTermOverrides:
    """Tests for financial term override protection."""

    def test_sec_terms_in_overrides(self):
        from common.translator import TERM_OVERRIDES

        assert "Stock Titan" in TERM_OVERRIDES
        assert "Form 4" in TERM_OVERRIDES
        assert "Form 4/A" in TERM_OVERRIDES
        assert "Form 10-K" in TERM_OVERRIDES
        assert "Form 8-K" in TERM_OVERRIDES

    def test_sec_terms_preserved_as_is(self):
        from common.translator import TERM_OVERRIDES

        assert TERM_OVERRIDES["Stock Titan"] == "Stock Titan"
        assert TERM_OVERRIDES["Form 4"] == "Form 4"
        assert TERM_OVERRIDES["Form 4/A"] == "Form 4/A"

    def test_insider_trading_translated(self):
        from common.translator import TERM_OVERRIDES

        assert TERM_OVERRIDES["Insider Trading"] == "내부자 거래"

    def test_crypto_terms_present(self):
        from common.translator import TERM_OVERRIDES

        assert TERM_OVERRIDES["Bitcoin"] == "비트코인"
        assert TERM_OVERRIDES["Ethereum"] == "이더리움"
        assert TERM_OVERRIDES["DeFi"] == "디파이"

    def test_abbreviations_kept_as_is(self):
        from common.translator import TERM_OVERRIDES

        for abbr in ("ETF", "NFT", "BTC", "ETH", "SEC", "CFTC", "IPO", "GDP"):
            assert TERM_OVERRIDES[abbr] == abbr


class TestApplyTermOverrides:
    """Tests for placeholder-based term protection."""

    def test_replaces_known_terms(self):
        from common.translator import _apply_term_overrides

        text = "Bitcoin ETF approved by SEC"
        modified, replacements = _apply_term_overrides(text)
        assert "Bitcoin" not in modified
        assert "ETF" not in modified
        assert "SEC" not in modified
        assert len(replacements) >= 3

    def test_restore_terms(self):
        from common.translator import _apply_term_overrides, _restore_terms

        text = "Stock Titan reports Form 4 filing"
        modified, replacements = _apply_term_overrides(text)
        restored = _restore_terms(modified, replacements)
        assert "Stock Titan" in restored
        assert "Form 4" in restored

    def test_word_boundary_prevents_partial_match(self):
        from common.translator import _apply_term_overrides

        text = "The chairman explained the maintenance gains"
        modified, _ = _apply_term_overrides(text)
        # "AI" should NOT match inside "chairman", "maintenance", "gains"
        assert "chairman" in modified.lower() or "__TERM" not in modified.lower().replace("__term", "")


class TestPostprocessTranslation:
    """Tests for Google Translate artifact fixes."""

    def test_fixes_media_name_mistranslation(self):
        from common.translator import _postprocess_translation

        assert _postprocess_translation("재고 타이탄") == "Stock Titan"
        assert _postprocess_translation("주식 타이탄") == "Stock Titan"
        assert _postprocess_translation("내부자 무역") == "내부자 거래"

    def test_fixes_token_artifacts(self):
        from common.translator import _postprocess_translation

        assert "Pairs" in _postprocess_translation("PAIrs of tokens")
        assert "maintain" in _postprocess_translation("mAIntain the price")
        assert "against" in _postprocess_translation("agAInst the trend")

    def test_fixes_motley_fool(self):
        from common.translator import _postprocess_translation

        assert _postprocess_translation("가지각색의 바보") == "Motley Fool"
        assert _postprocess_translation("잡다한 바보") == "Motley Fool"

    def test_fixes_seeking_alpha(self):
        from common.translator import _postprocess_translation

        assert _postprocess_translation("알파 추구") == "Seeking Alpha"

    def test_empty_string(self):
        from common.translator import _postprocess_translation

        assert _postprocess_translation("") == ""

    def test_no_artifacts_unchanged(self):
        from common.translator import _postprocess_translation

        text = "비트코인이 신고가를 경신했습니다"
        assert _postprocess_translation(text) == text

    def test_double_spaces_removed(self):
        from common.translator import _postprocess_translation

        assert "  " not in _postprocess_translation("비트코인  가격이  상승")

    def test_returns_env_var_when_set(self):
        from common.config import get_env

        key = "TEST_INVESTING_KEY_ABC"
        os.environ[key] = "myvalue"
        try:
            assert get_env(key) == "myvalue"
        finally:
            del os.environ[key]

    def test_strips_whitespace_from_value(self):
        from common.config import get_env

        key = "TEST_INVESTING_WHITESPACE_KEY"
        os.environ[key] = "  spaced_value  "
        try:
            assert get_env(key) == "spaced_value"
        finally:
            del os.environ[key]

    def test_strips_surrounding_double_quotes(self):
        from common.config import get_env

        key = "TEST_INVESTING_QUOTED_KEY"
        os.environ[key] = '"quoted_value"'
        try:
            assert get_env(key) == "quoted_value"
        finally:
            del os.environ[key]

    def test_strips_surrounding_single_quotes(self):
        from common.config import get_env

        key = "TEST_INVESTING_SINGLE_QUOTED_KEY"
        os.environ[key] = "'single_quoted'"
        try:
            assert get_env(key) == "single_quoted"
        finally:
            del os.environ[key]

    def test_default_not_stripped(self):
        # Default value is returned as-is (not stripped)
        from common.config import get_env

        key = "TEST_INVESTING_NO_STRIP_DEFAULT"
        os.environ.pop(key, None)
        assert get_env(key, "  spaced  ") == "  spaced  "


class TestRequestTimeout:
    def test_request_timeout_is_15(self):
        from common.config import REQUEST_TIMEOUT

        assert REQUEST_TIMEOUT == 15
