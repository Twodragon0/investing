"""Tests for generate_daily_summary.py — pure functions only (no I/O)."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


import scripts.generate_daily_summary as gds

# ---------------------------------------------------------------------------
# strip_html_tags
# ---------------------------------------------------------------------------


class TestStripHtmlTags:
    def test_removes_inline_tags(self):
        result = gds.strip_html_tags("<b>Bitcoin</b> surges today")
        assert "<b>" not in result
        assert "Bitcoin" in result

    def test_removes_div_block(self):
        result = gds.strip_html_tags('<div class="foo">hidden content</div>remaining')
        assert "<div" not in result
        assert "remaining" in result

    def test_removes_details_block(self):
        text = "<details><summary>Show</summary>content</details>after"
        result = gds.strip_html_tags(text)
        assert "<details>" not in result
        assert "after" in result

    def test_removes_style_block(self):
        text = "<style>body { color: red; }</style>visible"
        result = gds.strip_html_tags(text)
        assert "<style>" not in result
        assert "visible" in result

    def test_removes_script_block(self):
        text = "<script>alert('xss')</script>clean"
        result = gds.strip_html_tags(text)
        assert "<script>" not in result
        assert "clean" in result

    def test_collapses_multiple_blank_lines(self):
        text = "line1\n\n\n\n\nline2"
        result = gds.strip_html_tags(text)
        assert "\n\n\n" not in result

    def test_plain_text_unchanged(self):
        text = "Plain text without any HTML."
        result = gds.strip_html_tags(text)
        assert result == text

    def test_empty_string(self):
        assert gds.strip_html_tags("") == ""

    def test_strips_leading_trailing_whitespace(self):
        result = gds.strip_html_tags("  <b>hello</b>  ")
        assert not result.startswith(" ")
        assert not result.endswith(" ")


# ---------------------------------------------------------------------------
# _is_similar_title
# ---------------------------------------------------------------------------


class TestIsSimilarTitle:
    def test_identical_titles_are_similar(self):
        assert gds._is_similar_title("Bitcoin ETF Approval", "Bitcoin ETF Approval") is True

    def test_completely_different_titles(self):
        assert gds._is_similar_title("Bitcoin surges today", "Fed raises interest rates") is False

    def test_empty_titles_return_false(self):
        assert gds._is_similar_title("", "Bitcoin") is False
        assert gds._is_similar_title("Bitcoin", "") is False

    def test_high_overlap_similar(self):
        t1 = "Bitcoin ETF approval news"
        t2 = "Bitcoin ETF approval announced"
        assert gds._is_similar_title(t1, t2) is True

    def test_low_overlap_not_similar(self):
        t1 = "Bitcoin mining hash rate record"
        t2 = "Ethereum DeFi TVL drops sharply"
        assert gds._is_similar_title(t1, t2) is False

    def test_custom_threshold(self):
        t1 = "Bitcoin price rises"
        t2 = "Bitcoin price drops"
        # 2/3 word overlap = ~0.67, above default 0.6
        assert gds._is_similar_title(t1, t2, threshold=0.5) is True
        assert gds._is_similar_title(t1, t2, threshold=0.9) is False


# ---------------------------------------------------------------------------
# extract_section
# ---------------------------------------------------------------------------


class TestExtractSection:
    def _body(self):
        return (
            "## 소개\n소개 내용입니다.\n\n"
            "## 뉴스 요약\n뉴스 내용이 여기에 있습니다.\n항목 1\n항목 2\n\n"
            "## 마무리\n마무리 내용입니다."
        )

    def test_extracts_matching_section(self):
        result = gds.extract_section(self._body(), "뉴스 요약")
        assert "뉴스 내용이 여기에 있습니다." in result

    def test_missing_section_returns_empty(self):
        result = gds.extract_section(self._body(), "없는 섹션")
        assert result == ""

    def test_stops_at_next_heading(self):
        result = gds.extract_section(self._body(), "뉴스 요약")
        assert "마무리" not in result

    def test_empty_content(self):
        assert gds.extract_section("", "any") == ""


# ---------------------------------------------------------------------------
# extract_bullet_points
# ---------------------------------------------------------------------------


class TestExtractBulletPoints:
    def _body(self):
        return (
            "## 주요 뉴스\n"
            "- 비트코인 상승\n"
            "- 이더리움 보합\n"
            "- 리플 하락\n"
            "- 솔라나 급등\n"
            "- BNB 횡보\n"
            "- 도지코인 급락\n"
        )

    def test_extracts_bullets(self):
        result = gds.extract_bullet_points(self._body(), "주요 뉴스")
        assert len(result) > 0
        assert all(b.startswith("- ") for b in result)

    def test_max_items_respected(self):
        result = gds.extract_bullet_points(self._body(), "주요 뉴스", max_items=3)
        assert len(result) == 3

    def test_missing_section_returns_empty(self):
        result = gds.extract_bullet_points(self._body(), "없는 섹션")
        assert result == []

    def test_default_max_5(self):
        result = gds.extract_bullet_points(self._body(), "주요 뉴스")
        assert len(result) <= 5


# ---------------------------------------------------------------------------
# extract_table_rows
# ---------------------------------------------------------------------------


class TestExtractTableRows:
    def _body(self):
        return (
            "## 테이블\n"
            "| 이름 | 값 |\n"
            "|---|---|\n"
            "| 비트코인 | 100 |\n"
            "| 이더리움 | 200 |\n"
            "| 리플 | 300 |\n"
        )

    def test_extracts_data_rows(self):
        result = gds.extract_table_rows(self._body(), "테이블")
        assert len(result) > 0
        assert all(r.startswith("|") for r in result)

    def test_skips_header_rows(self):
        result = gds.extract_table_rows(self._body(), "테이블")
        # Header "이름" and separator "---" should not be in data rows
        assert all("이름" not in r for r in result)
        assert all("---" not in r for r in result)

    def test_missing_section_returns_empty(self):
        result = gds.extract_table_rows(self._body(), "없는 섹션")
        assert result == []

    def test_max_rows_respected(self):
        result = gds.extract_table_rows(self._body(), "테이블", max_rows=2)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# count_news_items
# ---------------------------------------------------------------------------


class TestCountNewsItems:
    def test_matches_n_건의_뉴스(self):
        assert gds.count_news_items("오늘 42건의 뉴스가 수집되었습니다.") == 42

    def test_matches_총_n건(self):
        assert gds.count_news_items("총 **25건** 수집되었습니다.") == 25

    def test_matches_n건이_수집(self):
        assert gds.count_news_items("총 15건이 수집되었습니다.") == 15

    def test_matches_n건을_수집(self):
        assert gds.count_news_items("오늘 30건을 수집했습니다.") == 30

    def test_no_match_returns_0(self):
        assert gds.count_news_items("아무 숫자도 없는 텍스트입니다.") == 0

    def test_empty_string_returns_0(self):
        assert gds.count_news_items("") == 0


# ---------------------------------------------------------------------------
# read_post_content — filesystem (tmp file)
# ---------------------------------------------------------------------------


class TestReadPostContent:
    def _write_post(self, tmp_path, fm_lines, body="Post body"):
        fm = "\n".join(fm_lines)
        content = f"---\n{fm}\n---\n{body}"
        p = tmp_path / "post.md"
        p.write_text(content, encoding="utf-8")
        return str(p)

    def test_parses_frontmatter(self, tmp_path):
        path = self._write_post(tmp_path, ["title: Test Post", "date: 2026-01-01"])
        result = gds.read_post_content(path)
        assert result["frontmatter"]["title"] == "Test Post"

    def test_parses_body(self, tmp_path):
        path = self._write_post(tmp_path, ["title: T"], "Hello world content here")
        result = gds.read_post_content(path)
        assert "Hello world" in result["content"]

    def test_strips_html_from_content(self, tmp_path):
        path = self._write_post(tmp_path, ["title: T"], "<b>Bold text</b> plain text")
        result = gds.read_post_content(path)
        assert "<b>" not in result["content"]
        assert "Bold text" in result["content"]

    def test_missing_file_returns_empty(self):
        result = gds.read_post_content("/nonexistent/path/post.md")
        assert result["frontmatter"] == {}
        assert result["content"] == ""

    def test_no_front_matter_returns_text_as_content(self, tmp_path):
        p = tmp_path / "no_fm.md"
        p.write_text("Just plain content without front matter.", encoding="utf-8")
        result = gds.read_post_content(str(p))
        assert "Just plain content" in result["content"]

    def test_filepath_preserved(self, tmp_path):
        path = self._write_post(tmp_path, ["title: T"])
        result = gds.read_post_content(path)
        assert result["filepath"] == path


# ---------------------------------------------------------------------------
# _SUMMARY_KEYWORD_LABELS constant
# ---------------------------------------------------------------------------


class TestSummaryKeywordLabels:
    def test_sec_label(self):
        assert gds._SUMMARY_KEYWORD_LABELS["sec"] == "SEC"

    def test_fed_label(self):
        assert gds._SUMMARY_KEYWORD_LABELS["fed"] == "연준"

    def test_etf_label(self):
        assert gds._SUMMARY_KEYWORD_LABELS["etf"] == "ETF"

    def test_fomc_label(self):
        assert gds._SUMMARY_KEYWORD_LABELS["fomc"] == "FOMC"


# ---------------------------------------------------------------------------
# _REPORT_CATEGORY_LABELS constant
# ---------------------------------------------------------------------------


class TestReportCategoryLabels:
    def test_crypto_label_present(self):
        assert "암호화폐 뉴스" in gds._REPORT_CATEGORY_LABELS

    def test_defi_label_present(self):
        assert "DeFi TVL 리포트" in gds._REPORT_CATEGORY_LABELS

    def test_all_values_have_emoji(self):
        for key, val in gds._REPORT_CATEGORY_LABELS.items():
            # Each value should contain a non-ASCII emoji or Korean
            assert len(val) > len(key)  # emoji adds chars
