"""Tests for markdown utilities (scripts/common/markdown_utils.py)."""


from common.markdown_utils import (
    _classify_source,
    dedupe_references,
    escape_table_cell,
    html_source_tag,
    html_text,
    markdown_link,
    markdown_table,
    smart_truncate,
)


class TestEscapeTableCell:
    def test_escapes_pipe(self):
        assert escape_table_cell("a|b") == "a\\|b"

    def test_strips_newlines(self):
        assert escape_table_cell("line1\nline2") == "line1 line2"

    def test_none_becomes_empty(self):
        assert escape_table_cell(None) == ""

    def test_int_converted(self):
        assert escape_table_cell(42) == "42"


class TestMarkdownLink:
    def test_basic_link(self):
        result = markdown_link("Click here", "https://example.com")
        assert result == "[Click here](https://example.com)"

    def test_pipe_in_title_escaped(self):
        result = markdown_link("A|B", "https://example.com")
        assert "\\|" in result


class TestMarkdownTable:
    def test_basic_table(self):
        result = markdown_table(["Name", "Value"], [["BTC", "100K"], ["ETH", "3K"]])
        lines = result.split("\n")
        assert len(lines) == 4  # header + sep + 2 rows
        assert "| Name | Value |" in lines[0]
        assert "---" in lines[1]

    def test_right_alignment(self):
        result = markdown_table(["Name", "Price"], [["BTC", "100"]], aligns=["left", "right"])
        assert "---:" in result

    def test_center_alignment(self):
        result = markdown_table(["Name"], [["BTC"]], aligns=["center"])
        assert ":---:" in result


class TestClassifySource:
    def test_crypto_media(self):
        assert _classify_source("CoinDesk") == "crypto-media"

    def test_exchange(self):
        assert _classify_source("Binance") == "exchange"

    def test_regulator(self):
        assert _classify_source("SEC Filing") == "regulator"

    def test_unknown(self):
        assert _classify_source("RandomBlog") == "default"

    def test_empty(self):
        assert _classify_source("") == "default"

    def test_case_insensitive(self):
        assert _classify_source("REUTERS") == "finance-media"


class TestHtmlSourceTag:
    def test_contains_data_attribute(self):
        result = html_source_tag("CoinDesk")
        assert 'data-source-type="crypto-media"' in result
        assert "CoinDesk" in result


class TestHtmlText:
    def test_escapes_html(self):
        result = html_text("<script>alert(1)</script>")
        assert "<script>" not in result
        assert "&lt;" in result

    def test_pipe_escaped(self):
        result = html_text("a|b")
        # pipe is replaced with &#124; then escape() encodes & to &amp;
        assert "|" not in result
        assert "a" in result and "b" in result


class TestSmartTruncate:
    def test_short_text_unchanged(self):
        assert smart_truncate("hello", 100) == "hello"

    def test_truncates_with_ellipsis(self):
        result = smart_truncate("word1 word2 word3 word4 word5", 20)
        assert result.endswith("…")
        assert len(result) <= 20

    def test_word_boundary(self):
        result = smart_truncate("Bitcoin price surges past milestone today", 25)
        # Should not cut mid-word
        assert not result.rstrip("…").endswith("mil")


class TestDedupeReferences:
    def test_basic_dedup(self):
        refs = [
            {"title": "A", "link": "https://a.com", "source": "s1"},
            {"title": "B", "link": "https://a.com", "source": "s2"},  # same link
            {"title": "C", "link": "https://c.com", "source": "s3"},
        ]
        result = dedupe_references(refs)
        assert len(result) == 2

    def test_google_news_dedup(self):
        refs = [
            {"title": "A", "link": "https://news.google.com/read/CBMiABC123", "source": "s1"},
            {"title": "B", "link": "https://news.google.com/rss/articles/CBMiABC123", "source": "s2"},
        ]
        result = dedupe_references(refs)
        assert len(result) == 1

    def test_limit(self):
        refs = [{"title": f"T{i}", "link": f"https://example.com/{i}", "source": "s"} for i in range(10)]
        result = dedupe_references(refs, limit=3)
        assert len(result) == 3

    def test_empty_link_skipped(self):
        refs = [{"title": "A", "link": "", "source": "s"}]
        result = dedupe_references(refs)
        assert len(result) == 0

    def test_title_ko_preserved(self):
        refs = [{"title": "English", "title_ko": "한국어", "link": "https://a.com", "source": "s"}]
        result = dedupe_references(refs)
        assert result[0]["title_ko"] == "한국어"
