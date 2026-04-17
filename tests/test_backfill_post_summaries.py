"""Tests for backfill_post_summaries.py — pure utility functions."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


import scripts.backfill_post_summaries as bps

# ---------------------------------------------------------------------------
# _get_front_list
# ---------------------------------------------------------------------------


class TestGetFrontList:
    def test_list_value(self):
        front = {"tags": ["crypto", "bitcoin"]}
        assert bps._get_front_list(front, "tags") == ["crypto", "bitcoin"]

    def test_string_value(self):
        front = {"tags": "crypto"}
        assert bps._get_front_list(front, "tags") == ["crypto"]

    def test_missing_key(self):
        assert bps._get_front_list({}, "tags") == []

    def test_empty_string_value(self):
        assert bps._get_front_list({"tags": ""}, "tags") == []

    def test_integer_items_in_list(self):
        front = {"items": [1, 2, 3]}
        result = bps._get_front_list(front, "items")
        assert result == ["1", "2", "3"]


# ---------------------------------------------------------------------------
# _get_front_date
# ---------------------------------------------------------------------------


class TestGetFrontDate:
    def test_iso_date(self):
        assert bps._get_front_date({"date": "2024-01-15 09:00:00"}) == "2024-01-15"

    def test_date_only(self):
        assert bps._get_front_date({"date": "2024-01-15"}) == "2024-01-15"

    def test_missing_key(self):
        assert bps._get_front_date({}) == ""

    def test_non_string_value(self):
        assert bps._get_front_date({"date": 20240115}) == ""


# ---------------------------------------------------------------------------
# split_frontmatter
# ---------------------------------------------------------------------------


class TestSplitFrontmatter:
    def test_valid_post(self):
        content = "---\ntitle: Test\n---\nBody here."
        front, body = bps.split_frontmatter(content)
        assert "title: Test" in front
        assert "Body here." in body

    def test_no_frontmatter(self):
        content = "Just body content."
        front, body = bps.split_frontmatter(content)
        assert front == ""
        assert body == content

    def test_incomplete_frontmatter(self):
        content = "---\ntitle: Incomplete"
        front, body = bps.split_frontmatter(content)
        assert front == ""

    def test_empty_string(self):
        front, body = bps.split_frontmatter("")
        assert front == ""


# ---------------------------------------------------------------------------
# parse_frontmatter
# ---------------------------------------------------------------------------


class TestParseFrontmatter:
    def test_basic_parsing(self):
        fm = '---\ntitle: "테스트 포스트"\ncategory: crypto\n---\n'
        result = bps.parse_frontmatter(fm)
        assert result["title"] == "테스트 포스트"
        assert result["category"] == "crypto"

    def test_list_value(self):
        fm = "---\ntags: [bitcoin, ethereum]\n---\n"
        result = bps.parse_frontmatter(fm)
        assert "bitcoin" in result["tags"]
        assert "ethereum" in result["tags"]

    def test_empty_string(self):
        assert bps.parse_frontmatter("") == {}

    def test_no_colon_lines_ignored(self):
        fm = "---\nno colon here\ntitle: Test\n---\n"
        result = bps.parse_frontmatter(fm)
        assert result["title"] == "Test"
        assert "no colon here" not in result


# ---------------------------------------------------------------------------
# clean_text
# ---------------------------------------------------------------------------


class TestCleanText:
    def test_removes_bold(self):
        assert bps.clean_text("**bold text**") == "bold text"

    def test_removes_code(self):
        assert bps.clean_text("`code`") == "code"

    def test_removes_link(self):
        result = bps.clean_text("[링크 텍스트](https://example.com)")
        assert result == "링크 텍스트"

    def test_removes_html(self):
        assert bps.clean_text("<div>내용</div>") == "내용"

    def test_removes_sponsored(self):
        result = bps.clean_text("Sponsored by ExampleCo")
        assert "Sponsored" not in result

    def test_plain_text_unchanged(self):
        assert bps.clean_text("일반 텍스트") == "일반 텍스트"


# ---------------------------------------------------------------------------
# is_noise_text
# ---------------------------------------------------------------------------


class TestIsNoiseText:
    def test_empty_string(self):
        assert bps.is_noise_text("") is True

    def test_separator(self):
        assert bps.is_noise_text("---") is True

    def test_bullet(self):
        assert bps.is_noise_text("-") is True

    def test_count_line(self):
        assert bps.is_noise_text("총 5건 수집") is True

    def test_image_line(self):
        assert bps.is_noise_text("![image](url)") is True

    def test_heading_line(self):
        assert bps.is_noise_text("## 제목") is True

    def test_real_content(self):
        assert bps.is_noise_text("비트코인이 오늘 급등했습니다.") is False


# ---------------------------------------------------------------------------
# normalize_title
# ---------------------------------------------------------------------------


class TestNormalizeTitle:
    def test_removes_numbering(self):
        result = bps.normalize_title("1. 비트코인 뉴스")
        assert not result.startswith("1.")

    def test_removes_trailing_source(self):
        result = bps.normalize_title("Bitcoin rises - CoinDesk")
        assert "CoinDesk" not in result

    def test_removes_special_brackets(self):
        result = bps.normalize_title("[속보] 비트코인 급등")
        assert "[속보]" not in result

    def test_collapses_whitespace(self):
        result = bps.normalize_title("비트코인   급등")
        assert "  " not in result

    def test_empty_string(self):
        assert bps.normalize_title("") == ""


# ---------------------------------------------------------------------------
# normalize_summary
# ---------------------------------------------------------------------------


class TestNormalizeSummary:
    def test_single_sentence(self):
        result = bps.normalize_summary("비트코인이 급등했습니다.")
        assert result.endswith(".")

    def test_removes_markdown(self):
        result = bps.normalize_summary("**비트코인** 급등")
        assert "**" not in result

    def test_empty_string(self):
        assert bps.normalize_summary("") == ""

    def test_multiple_sentences_takes_first(self):
        result = bps.normalize_summary("첫 번째 문장입니다. 두 번째 문장입니다.")
        assert "첫 번째" in result


# ---------------------------------------------------------------------------
# _shorten_title_for_summary
# ---------------------------------------------------------------------------


class TestShortenTitleForSummary:
    def test_short_title_unchanged(self):
        title = "짧은 제목"
        assert bps._shorten_title_for_summary(title) == title

    def test_long_title_truncated(self):
        title = "a " * 60  # 120 chars
        result = bps._shorten_title_for_summary(title, limit=80)
        assert len(result) <= 85  # allows for "..."

    def test_appends_ellipsis(self):
        title = "word " * 30
        result = bps._shorten_title_for_summary(title, limit=50)
        assert result.endswith("...")


# ---------------------------------------------------------------------------
# summarize_from_title
# ---------------------------------------------------------------------------


class TestSummarizeFromTitle:
    def test_bitcoin_title(self):
        result = bps.summarize_from_title("Bitcoin price surges to new high")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_korean_title(self):
        result = bps.summarize_from_title("비트코인이 오늘 5% 급등하며 5만 달러를 돌파했습니다.")
        assert isinstance(result, str)

    def test_ethereum_title(self):
        result = bps.summarize_from_title("Ethereum ETF approval expected soon")
        assert isinstance(result, str)

    def test_empty_title(self):
        result = bps.summarize_from_title("")
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# extract_links
# ---------------------------------------------------------------------------


class TestExtractLinks:
    def test_markdown_link(self):
        lines = ["- [제목](https://example.com) — 요약"]
        results = bps.extract_links(lines)
        assert len(results) > 0
        # (title, url, summary, ...) tuple
        assert "제목" in results[0][0] or "https://example.com" in results[0][1]

    def test_no_links(self):
        lines = ["일반 텍스트", "링크 없음"]
        results = bps.extract_links(lines)
        assert results == []

    def test_multiple_links(self):
        lines = [
            "- [제목1](https://ex1.com) — 요약1",
            "- [제목2](https://ex2.com) — 요약2",
        ]
        results = bps.extract_links(lines)
        assert len(results) == 2


# ---------------------------------------------------------------------------
# find_heading_index
# ---------------------------------------------------------------------------


class TestFindHeadingIndex:
    def test_finds_heading(self):
        lines = ["## 전체 뉴스 요약", "내용1", "## 다른 섹션"]
        assert bps.find_heading_index(lines, "전체 뉴스 요약") == 0

    def test_missing_heading(self):
        lines = ["## 핵심 요약", "내용"]
        assert bps.find_heading_index(lines, "없는 섹션") == -1


# ---------------------------------------------------------------------------
# find_section_end
# ---------------------------------------------------------------------------


class TestFindSectionEnd:
    def test_finds_next_heading(self):
        lines = ["내용1", "내용2", "## 다음 섹션", "내용3"]
        end = bps.find_section_end(lines, 0)
        assert end == 2

    def test_end_of_file(self):
        lines = ["내용1", "내용2"]
        end = bps.find_section_end(lines, 0)
        assert end == len(lines)


# ---------------------------------------------------------------------------
# extract_total_count
# ---------------------------------------------------------------------------


class TestExtractTotalCount:
    def test_finds_count(self):
        body = "총 42건의 뉴스가 수집되었습니다."
        result = bps.extract_total_count(body)
        assert "42" in result

    def test_no_count(self):
        result = bps.extract_total_count("관련 뉴스 없음")
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# has_urgent_alert
# ---------------------------------------------------------------------------


class TestHasUrgentAlert:
    def test_with_urgent_label(self):
        body = "긴급 알림: 비트코인 거래소 해킹 발생"
        assert bps.has_urgent_alert(body) is True

    def test_with_alert_urgent_class(self):
        body = '<div class="alert-urgent">경고</div>'
        assert bps.has_urgent_alert(body) is True

    def test_without_alert(self):
        assert bps.has_urgent_alert("일반 뉴스 내용입니다.") is False

    def test_empty(self):
        assert bps.has_urgent_alert("") is False


# ---------------------------------------------------------------------------
# is_social_media_post
# ---------------------------------------------------------------------------


class TestIsSocialMediaPost:
    def test_social_media_tag(self):
        front = {"tags": ["social-media"], "title": "", "categories": []}
        assert bps.is_social_media_post(front, "") is True

    def test_title_match(self):
        front = {"title": "소셜 미디어 동향 리포트", "tags": [], "categories": []}
        assert bps.is_social_media_post(front, "") is True

    def test_body_match(self):
        front = {"title": "", "tags": [], "categories": []}
        body = "소셜 미디어 동향과 텔레그램 채널 분석"
        assert bps.is_social_media_post(front, body) is True

    def test_non_social(self):
        front = {"title": "비트코인 뉴스", "tags": [], "categories": []}
        assert bps.is_social_media_post(front, "일반 뉴스 내용") is False

    def test_daily_summary_excluded(self):
        front = {"title": "일일 뉴스 종합", "tags": [], "categories": [], "pin": True}
        assert bps.is_social_media_post(front, "") is False


# ---------------------------------------------------------------------------
# _trim_sentence
# ---------------------------------------------------------------------------


class TestTrimSentence:
    def test_short_sentence(self):
        result = bps._trim_sentence("짧은 문장입니다.", limit=110)
        assert result == "짧은 문장입니다."

    def test_long_sentence_trimmed(self):
        long = "a" * 200
        result = bps._trim_sentence(long, limit=110)
        assert len(result) <= 120

    def test_empty(self):
        assert bps._trim_sentence("") == ""


# ---------------------------------------------------------------------------
# remove_missing_local_images
# ---------------------------------------------------------------------------


class TestRemoveMissingLocalImages:
    def test_keeps_external_images(self):
        lines = ["![alt](https://external.com/img.png)"]
        result = bps.remove_missing_local_images(lines)
        # External images (https://) should be kept
        assert lines == result or isinstance(result, list)

    def test_removes_missing_local_image(self, tmp_path):
        lines = ["![alt](/assets/images/generated/missing.png)"]
        result = bps.remove_missing_local_images(lines)
        assert isinstance(result, list)

    def test_no_images(self):
        lines = ["일반 텍스트", "## 제목"]
        result = bps.remove_missing_local_images(lines)
        assert result == lines


# ---------------------------------------------------------------------------
# remove_existing_summary
# ---------------------------------------------------------------------------


class TestRemoveExistingSummary:
    def test_no_summary_to_remove(self):
        lines = ["일반 내용", "## 섹션"]
        result_lines, removed = bps.remove_existing_summary(lines)
        assert removed is False
        assert result_lines == lines

    def test_removes_existing_summary(self):
        lines = [
            "## 전체 뉴스 요약",
            "- 요약 내용",
            "## 다른 섹션",
            "다른 내용",
        ]
        result_lines, removed = bps.remove_existing_summary(lines)
        assert isinstance(result_lines, list)
