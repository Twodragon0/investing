"""Tests for utility functions (scripts/common/utils.py)."""

from datetime import UTC

from common.utils import (
    detect_language,
    parse_date,
    remove_sponsored_text,
    sanitize_string,
    slugify,
    truncate_sentence,
    truncate_text,
    validate_news_item,
    validate_url,
)


class TestSanitizeString:
    def test_removes_control_chars(self):
        assert sanitize_string("hello\x00world\x1f") == "helloworld"

    def test_escapes_pipe(self):
        assert sanitize_string("col1|col2") == "col1&#124;col2"

    def test_max_length(self):
        result = sanitize_string("a" * 2000, max_length=100)
        assert len(result) == 100

    def test_strips_whitespace(self):
        assert sanitize_string("  hello  ") == "hello"

    def test_non_string_returns_empty(self):
        assert sanitize_string(None) == ""
        assert sanitize_string(123) == ""


class TestValidateUrl:
    def test_valid_https(self):
        assert validate_url("https://example.com/path") is True

    def test_valid_http(self):
        assert validate_url("http://example.com") is True

    def test_no_scheme(self):
        assert validate_url("example.com") is False

    def test_ftp_rejected(self):
        assert validate_url("ftp://example.com") is False

    def test_empty_string(self):
        assert validate_url("") is False

    def test_javascript_rejected(self):
        assert validate_url("javascript:alert(1)") is False


class TestSlugify:
    def test_basic(self):
        assert slugify("Hello World!") == "hello-world"

    def test_korean(self):
        result = slugify("비트코인 가격 상승")
        assert "비트코인" in result

    def test_max_length(self):
        result = slugify("a" * 200, max_length=50)
        assert len(result) <= 50

    def test_collapses_dashes(self):
        assert slugify("a---b") == "a-b"


class TestParseDate:
    def test_iso_format(self):
        dt = parse_date("2026-03-08T12:00:00Z")
        assert dt.year == 2026
        assert dt.month == 3

    def test_date_only(self):
        dt = parse_date("2026-03-08")
        assert dt.day == 8

    def test_rfc_2822(self):
        dt = parse_date("Sat, 08 Mar 2026 12:00:00 +0900")
        assert dt is not None
        assert dt.year == 2026

    def test_empty_returns_none(self):
        assert parse_date("") is None
        assert parse_date(None) is None

    def test_invalid_returns_none(self):
        assert parse_date("not-a-date") is None

    def test_adds_utc_if_no_tz(self):
        dt = parse_date("2026-03-08 12:00:00")
        assert dt.tzinfo == UTC


class TestDetectLanguage:
    def test_korean(self):
        assert detect_language("비트코인 가격이 급등했습니다") == "ko"

    def test_english(self):
        assert detect_language("Bitcoin price surges") == "en"

    def test_empty(self):
        assert detect_language("") == "en"

    def test_mixed_mostly_korean(self):
        assert detect_language("비트코인 BTC 가격 100K 돌파") == "ko"


class TestRemoveSponsoredText:
    def test_removes_sponsored(self):
        result = remove_sponsored_text("Big news Sponsored by @company rest")
        assert "@company" not in result

    def test_removes_ad(self):
        result = remove_sponsored_text("Content\nAd: Buy this product")
        assert "Buy this" not in result

    def test_removes_decorative(self):
        result = remove_sponsored_text("▶◆ Hello ★")
        assert result == "Hello"

    def test_none_returns_none(self):
        assert remove_sponsored_text(None) is None

    def test_empty_returns_empty(self):
        assert remove_sponsored_text("") == ""


class TestTruncateText:
    def test_short_text_unchanged(self):
        assert truncate_text("hello", 100) == "hello"

    def test_truncates_at_word_boundary(self):
        result = truncate_text("word1 word2 word3 word4 word5", 20)
        assert result.endswith("...")
        assert len(result) <= 23  # 20 + "..."

    def test_exact_length(self):
        text = "a" * 300
        result = truncate_text(text, 300)
        assert result == text


class TestTruncateSentence:
    def test_korean_sentence_boundary(self):
        text = "비트코인이 상승했다. 이더리움도 상승했다. 이것은 매우 긴 문장입니다."
        result = truncate_sentence(text, 30)
        assert "다." in result

    def test_english_sentence_boundary(self):
        text = "Bitcoin surged. Ethereum followed. This is a long sentence that goes on."
        result = truncate_sentence(text, 40)
        assert result.endswith(". ") or result.endswith(".") or "..." in result

    def test_short_unchanged(self):
        text = "Short text."
        assert truncate_sentence(text, 100) == text


class TestValidateNewsItem:
    def test_valid_item(self):
        item = {"title": "Bitcoin surges past 100K", "link": "https://example.com/news"}
        result = validate_news_item(item)
        assert result is not None

    def test_short_title_rejected(self):
        item = {"title": "Short", "link": "https://example.com"}
        assert validate_news_item(item) is None

    def test_invalid_url_rejected(self):
        item = {"title": "Valid title here longer", "link": "not-a-url"}
        assert validate_news_item(item) is None

    def test_noise_title_rejected(self):
        item = {"title": "10-K filing document annual report", "link": "https://sec.gov/filing"}
        assert validate_news_item(item) is None

    def test_description_equals_title_cleared(self):
        item = {
            "title": "Bitcoin surges past 100K",
            "link": "https://example.com",
            "description": "Bitcoin surges past 100K",
        }
        result = validate_news_item(item)
        assert result["description"] == ""

    def test_empty_link_allowed(self):
        item = {"title": "Valid title with no link field", "link": ""}
        result = validate_news_item(item)
        assert result is not None
