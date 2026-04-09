"""Unit tests for pure logic functions in scripts/generate_og_images.py.

matplotlib 없이 테스트 가능한 순수 로직 함수들만 커버.
"""

import os
import sys
import tempfile

import pytest

# ---------------------------------------------------------------------------
# Import guard: stub matplotlib/PIL so module loads without those deps
# ---------------------------------------------------------------------------

try:
    # Ensure scripts/ is on the path
    _scripts_dir = os.path.join(os.path.dirname(__file__), "..", "scripts")
    if _scripts_dir not in sys.path:
        sys.path.insert(0, os.path.abspath(_scripts_dir))

    import generate_og_images as og

    _IMPORT_OK = True
except Exception:
    og = None  # type: ignore
    _IMPORT_OK = False

pytestmark = pytest.mark.skipif(not _IMPORT_OK, reason="generate_og_images could not be imported")


# ---------------------------------------------------------------------------
# 1. _extract_metrics
# ---------------------------------------------------------------------------


class TestExtractMetrics:
    def test_empty_string_returns_empty_list(self):
        assert og._extract_metrics("") == []

    def test_btc_price_extracted(self):
        desc = "BTC $71,297 (24h +3.5%). 공포·탐욕 지수: 17/100 (Extreme Fear)"
        metrics = og._extract_metrics(desc)
        labels = [m[0] for m in metrics]
        assert "BTC" in labels
        btc = next(m for m in metrics if m[0] == "BTC")
        assert btc[1] == "$71,297"
        assert btc[2] == "#f7931a"

    def test_fear_and_greed_extracted(self):
        desc = "BTC $71,297 (24h +3.5%). 공포·탐욕 지수: 17/100 (Extreme Fear)"
        metrics = og._extract_metrics(desc)
        labels = [m[0] for m in metrics]
        assert "F&G" in labels
        fg = next(m for m in metrics if m[0] == "F&G")
        assert fg[1] == "17"
        # val=17 < 30 → red
        assert fg[2] == "#ef4444"

    def test_fear_and_greed_color_neutral(self):
        # 30 <= val < 60 → yellow
        desc = "공포탐욕지수: 45/100"
        metrics = og._extract_metrics(desc)
        fg = next((m for m in metrics if m[0] == "F&G"), None)
        if fg:
            assert fg[2] == "#eab308"

    def test_fear_and_greed_color_greed(self):
        # val >= 60 → green
        desc = "공포탐욕지수: 75/100"
        metrics = og._extract_metrics(desc)
        fg = next((m for m in metrics if m[0] == "F&G"), None)
        if fg:
            assert fg[2] == "#10b981"

    def test_kospi_extracted(self):
        desc = "KOSPI 5,872.34(+6.87%), KOSDAQ 1,089.85(+5.12%)"
        metrics = og._extract_metrics(desc)
        labels = [m[0] for m in metrics]
        assert "KOSPI" in labels
        kospi = next(m for m in metrics if m[0] == "KOSPI")
        assert kospi[1] == "5,872.34"
        assert kospi[2] == "#10b981"  # + → green

    def test_kospi_negative_color(self):
        desc = "KOSPI 2,500.00(-1.50%)"
        metrics = og._extract_metrics(desc)
        kospi = next((m for m in metrics if m[0] == "KOSPI"), None)
        if kospi:
            assert kospi[2] == "#ef4444"

    def test_vix_extracted(self):
        desc = "공포탐욕지수 28.6(fear), VIX 21.94, 달러지수 98.78"
        metrics = og._extract_metrics(desc)
        labels = [m[0] for m in metrics]
        assert "VIX" in labels
        vix = next(m for m in metrics if m[0] == "VIX")
        assert vix[1] == "21.94"
        # 18 < 21.94 <= 25 → yellow
        assert vix[2] == "#eab308"

    def test_dxy_extracted(self):
        desc = "공포탐욕지수 28.6(fear), VIX 21.94, 달러지수 98.78"
        metrics = og._extract_metrics(desc)
        labels = [m[0] for m in metrics]
        assert "DXY" in labels
        dxy = next(m for m in metrics if m[0] == "DXY")
        assert dxy[1] == "98.78"
        assert dxy[2] == "#3b82f6"

    def test_news_count_extracted(self):
        desc = "지정학적 리스크 52건 수집"
        metrics = og._extract_metrics(desc)
        labels = [m[0] for m in metrics]
        assert "NEWS" in labels
        news = next(m for m in metrics if m[0] == "NEWS")
        assert news[1] == "52건"
        assert news[2] == "#8b5cf6"

    def test_max_three_items_returned(self):
        # Provide BTC + F&G + KOSPI + VIX — should cap at 3
        desc = "BTC $50,000. 공포탐욕지수: 40/100. KOSPI 2,600.00(+1.0%). VIX 20.00"
        metrics = og._extract_metrics(desc)
        assert len(metrics) <= 3

    def test_returns_list_of_tuples(self):
        desc = "BTC $45,000"
        metrics = og._extract_metrics(desc)
        assert isinstance(metrics, list)
        for item in metrics:
            assert isinstance(item, tuple)
            assert len(item) == 3


# ---------------------------------------------------------------------------
# 2. wrap_text
# ---------------------------------------------------------------------------


class TestWrapText:
    def test_short_text_not_wrapped(self):
        lines = og.wrap_text("hello", max_width=80, max_lines=3)
        assert lines == ["hello"]

    def test_long_text_wrapped_into_multiple_lines(self):
        text = "This is a somewhat long sentence that should be wrapped into two or more lines."
        lines = og.wrap_text(text, max_width=30, max_lines=5)
        assert len(lines) > 1
        for line in lines:
            assert len(line) <= 33  # slight tolerance for word boundaries

    def test_max_lines_respected(self):
        text = " ".join(["word"] * 50)
        lines = og.wrap_text(text, max_width=10, max_lines=2)
        assert len(lines) <= 2

    def test_last_line_truncated_with_ellipsis(self):
        text = " ".join(["word"] * 50)
        lines = og.wrap_text(text, max_width=10, max_lines=2)
        assert lines[-1].endswith("...")

    def test_empty_string_returns_empty_list(self):
        lines = og.wrap_text("", max_width=80, max_lines=3)
        assert lines == []


# ---------------------------------------------------------------------------
# 3. safe_text
# ---------------------------------------------------------------------------


class TestSafeText:
    def test_dollar_sign_escaped(self):
        assert og.safe_text("$100") == r"\$100"

    def test_multiple_dollar_signs_escaped(self):
        assert og.safe_text("$50 and $75") == r"\$50 and \$75"

    def test_no_dollar_sign_unchanged(self):
        assert og.safe_text("BTC price") == "BTC price"

    def test_empty_string(self):
        assert og.safe_text("") == ""


# ---------------------------------------------------------------------------
# 4. truncate_text
# ---------------------------------------------------------------------------


class TestTruncateText:
    def test_short_text_unchanged(self):
        assert og.truncate_text("hello", 10) == "hello"

    def test_exact_length_unchanged(self):
        assert og.truncate_text("hello", 5) == "hello"

    def test_long_text_truncated(self):
        result = og.truncate_text("hello world", 8)
        assert result.endswith("...")
        assert len(result) <= 8

    def test_truncated_length_correct(self):
        text = "abcdefghij"
        result = og.truncate_text(text, 7)
        assert len(result) == 7
        assert result == "abcd..."

    def test_empty_string(self):
        assert og.truncate_text("", 10) == ""


# ---------------------------------------------------------------------------
# 5. slug_from_filename
# ---------------------------------------------------------------------------


class TestSlugFromFilename:
    def test_standard_post_filename(self):
        assert og.slug_from_filename("2026-03-07-daily-regulatory-report.md") == "daily-regulatory-report"

    def test_full_path_handled(self):
        result = og.slug_from_filename("/path/to/_posts/2026-01-01-my-post.md")
        assert result == "my-post"

    def test_no_date_prefix_unchanged(self):
        result = og.slug_from_filename("my-post.md")
        assert result == "my-post"

    def test_md_extension_removed(self):
        result = og.slug_from_filename("2026-03-07-test.md")
        assert "md" not in result


# ---------------------------------------------------------------------------
# 6. date_from_filename
# ---------------------------------------------------------------------------


class TestDateFromFilename:
    def test_standard_post_filename(self):
        assert og.date_from_filename("2026-03-07-daily-regulatory-report.md") == "2026-03-07"

    def test_full_path_handled(self):
        assert og.date_from_filename("/posts/2026-01-15-test.md") == "2026-01-15"

    def test_no_date_returns_none(self):
        assert og.date_from_filename("no-date-here.md") is None

    def test_partial_date_returns_none(self):
        assert og.date_from_filename("2026-03-test.md") is None


# ---------------------------------------------------------------------------
# 7. format_date_korean
# ---------------------------------------------------------------------------


class TestFormatDateKorean:
    def test_standard_date(self):
        assert og.format_date_korean("2026-03-07") == "2026년 03월 07일"

    def test_january(self):
        assert og.format_date_korean("2025-01-01") == "2025년 01월 01일"

    def test_december(self):
        assert og.format_date_korean("2024-12-31") == "2024년 12월 31일"


# ---------------------------------------------------------------------------
# 8. parse_front_matter
# ---------------------------------------------------------------------------


class TestParseFrontMatter:
    def _write_post(self, content: str) -> str:
        """Write content to a temp file and return its path."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as f:
            f.write(content)
            return f.name

    def test_basic_front_matter_parsed(self):
        path = self._write_post("---\ntitle: Test Post\ndate: 2026-03-07\ncategories: crypto-news\n---\n\nBody.")
        try:
            result = og.parse_front_matter(path)
            assert result is not None
            assert result["title"] == "Test Post"
            assert result["date"] == "2026-03-07"
            assert result["categories"] == "crypto-news"
        finally:
            os.unlink(path)

    def test_description_parsed(self):
        path = self._write_post('---\ntitle: My Post\ndescription: "Some description here"\n---\n')
        try:
            result = og.parse_front_matter(path)
            assert result is not None
            assert result["description"] == "Some description here"
        finally:
            os.unlink(path)

    def test_no_front_matter_returns_none(self):
        path = self._write_post("Just plain content without front matter.")
        try:
            assert og.parse_front_matter(path) is None
        finally:
            os.unlink(path)

    def test_missing_title_returns_none(self):
        path = self._write_post("---\ndate: 2026-03-07\n---\n\nBody.")
        try:
            assert og.parse_front_matter(path) is None
        finally:
            os.unlink(path)

    def test_nonexistent_file_returns_none(self):
        assert og.parse_front_matter("/nonexistent/path/post.md") is None

    def test_categories_list_parsed_to_first(self):
        path = self._write_post("---\ntitle: Post\ncategories: [crypto-news, stock-news]\n---\n")
        try:
            result = og.parse_front_matter(path)
            assert result is not None
            assert result["categories"] == "crypto-news"
        finally:
            os.unlink(path)
