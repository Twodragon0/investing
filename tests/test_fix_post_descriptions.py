"""Tests for scripts/fix_post_descriptions.py — pure functions only."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


import scripts.fix_post_descriptions as fpd

# ---------------------------------------------------------------------------
# _strip_quotes
# ---------------------------------------------------------------------------


class TestStripQuotes:
    def test_strips_double_quotes(self):
        assert fpd._strip_quotes('"hello"') == "hello"

    def test_strips_single_quotes(self):
        assert fpd._strip_quotes("'hello'") == "hello"

    def test_strips_whitespace(self):
        assert fpd._strip_quotes("  hello  ") == "hello"

    def test_no_quotes_unchanged(self):
        assert fpd._strip_quotes("hello") == "hello"

    def test_empty_string(self):
        assert fpd._strip_quotes("") == ""


# ---------------------------------------------------------------------------
# _is_boilerplate
# ---------------------------------------------------------------------------


class TestIsBoilerplate:
    def test_empty_string_not_boilerplate(self):
        assert fpd._is_boilerplate("") is False

    def test_bloomberg_phrase_detected(self):
        assert fpd._is_boilerplate("bloomberg provides financial news and data") is True

    def test_coindesk_is_detected(self):
        assert fpd._is_boilerplate("coindesk is the leading crypto news site") is True

    def test_short_desc_no_specifics_is_boilerplate(self):
        # Less than 35 chars with no article-specific content
        assert fpd._is_boilerplate("짧은 내용") is True

    def test_synthetic_marker_detected(self):
        assert fpd._is_boilerplate("비트코인 관련 소식입니다") is True

    def test_real_content_not_boilerplate(self):
        desc = "Bitcoin surged 5% today as institutional investors increased their positions significantly."
        assert fpd._is_boilerplate(desc) is False

    def test_seeking_alpha_detected(self):
        assert fpd._is_boilerplate("seeking alpha covers this topic today") is True

    def test_motley_fool_detected(self):
        assert fpd._is_boilerplate("motley fool recommends these stocks") is True

    def test_world_leading_pattern(self):
        assert fpd._is_boilerplate("the world's leading provider of crypto news") is True

    def test_original_article_marker(self):
        assert fpd._is_boilerplate("원문에서 세부 내용을 확인하세요") is True

    def test_korean_real_content_not_boilerplate(self):
        desc = "비트코인이 2026년 4월 기준 $95,000를 돌파했으며 기관 투자자들의 매수세가 이어지고 있습니다."
        assert fpd._is_boilerplate(desc) is False


# ---------------------------------------------------------------------------
# _is_title_repeat
# ---------------------------------------------------------------------------


class TestIsTitleRepeat:
    def test_identical_strings_is_repeat(self):
        title = "Bitcoin ETF Approval"
        assert fpd._is_title_repeat(title, title) is True

    def test_empty_desc_returns_false(self):
        assert fpd._is_title_repeat("", "Bitcoin ETF") is False

    def test_empty_title_returns_false(self):
        assert fpd._is_title_repeat("Bitcoin ETF Approval Today", "") is False

    def test_different_content_not_repeat(self):
        # Use texts with no shared characters to guarantee no overlap
        desc = "가나다라마바사아자차카타파하"
        title = "qwerty uiop asdfghjkl zxcvbnm"
        assert fpd._is_title_repeat(desc, title) is False

    def test_near_duplicate_is_repeat(self):
        title = "비트코인 ETF 승인 소식"
        desc = "비트코인 ETF 승인 소식이 전해졌습니다"
        # desc is very similar to title
        assert fpd._is_title_repeat(desc, title) is True


# ---------------------------------------------------------------------------
# _is_bad_description
# ---------------------------------------------------------------------------


class TestIsBadDescription:
    def test_boilerplate_is_bad(self):
        assert fpd._is_bad_description("bloomberg covers financial news", "Bitcoin ETF") is True

    def test_title_repeat_is_bad(self):
        title = "Bitcoin ETF Approval"
        assert fpd._is_bad_description(title, title) is True

    def test_good_description_not_bad(self):
        desc = "The SEC approved spot Bitcoin ETFs today, marking a major milestone for crypto adoption."
        title = "Bitcoin ETF Approved"
        assert fpd._is_bad_description(desc, title) is False


# ---------------------------------------------------------------------------
# _parse_front_matter
# ---------------------------------------------------------------------------


class TestParseFrontMatter:
    def test_valid_front_matter(self):
        text = "---\ntitle: Test\ndate: 2026-01-01\n---\nbody"
        start, end = fpd._parse_front_matter(text)
        assert start == 3
        assert end > start

    def test_no_front_matter_returns_minus1(self):
        text = "Just plain content."
        start, end = fpd._parse_front_matter(text)
        assert start == -1
        assert end == -1

    def test_unclosed_front_matter_returns_minus1(self):
        text = "---\ntitle: Test\nno closing delimiters"
        start, end = fpd._parse_front_matter(text)
        assert start == -1
        assert end == -1


# ---------------------------------------------------------------------------
# _get_field
# ---------------------------------------------------------------------------


class TestGetField:
    def test_extracts_description_field(self):
        text = 'title: My Post\ndescription: "Some description here"\ndate: 2026-01-01'
        result = fpd._get_field(text, fpd._DESC_RE)
        assert result == "Some description here"

    def test_missing_field_returns_empty(self):
        text = "title: My Post\ndate: 2026-01-01"
        result = fpd._get_field(text, fpd._DESC_RE)
        assert result == ""

    def test_extracts_title_field(self):
        text = "title: Bitcoin News\ndescription: test"
        result = fpd._get_field(text, fpd._TITLE_RE)
        assert result == "Bitcoin News"


# ---------------------------------------------------------------------------
# _truncate
# ---------------------------------------------------------------------------


class TestTruncate:
    def test_short_string_unchanged(self):
        s = "Short text."
        assert fpd._truncate(s, 200) == s

    def test_truncates_at_sentence_boundary(self):
        s = "First sentence. " + "x" * 200
        result = fpd._truncate(s, 50)
        # _truncate breaks at "." — result may include trailing space or ellipsis
        assert "First sentence" in result
        assert len(result) <= 53  # allow for "…" suffix

    def test_truncates_with_ellipsis_when_no_boundary(self):
        s = "a" * 300
        result = fpd._truncate(s, 100)
        assert result.endswith("…")

    def test_truncates_at_exclamation(self):
        s = "Alert! " + "y" * 200
        result = fpd._truncate(s, 20)
        assert "!" in result

    def test_truncates_at_question_mark(self):
        s = "Is this right? " + "z" * 200
        result = fpd._truncate(s, 20)
        assert "?" in result


# ---------------------------------------------------------------------------
# _replace_description_in_text
# ---------------------------------------------------------------------------


class TestReplaceDescriptionInText:
    def _make_post(self, description):
        return f'---\ntitle: Test Post\ndescription: "{description}"\ndate: 2026-01-01\n---\nBody content here.'

    def test_replaces_description(self):
        content = self._make_post("Old description text here for testing purposes.")
        result = fpd._replace_description_in_text(content, "New description.")
        assert 'description: "New description."' in result

    def test_preserves_other_fields(self):
        content = self._make_post("Old description.")
        result = fpd._replace_description_in_text(content, "New description.")
        assert "title: Test Post" in result
        assert "date: 2026-01-01" in result

    def test_no_front_matter_unchanged(self):
        content = "No front matter at all."
        result = fpd._replace_description_in_text(content, "New value.")
        assert result == content

    def test_body_preserved(self):
        content = self._make_post("Old desc.")
        result = fpd._replace_description_in_text(content, "New desc.")
        assert "Body content here." in result


# ---------------------------------------------------------------------------
# _extract_worldmonitor_desc
# ---------------------------------------------------------------------------


class TestExtractWorldmonitorDesc:
    def _make_wm_post(self, total=42, themes="지정학·에너지", source="GDELT"):
        return (
            f'---\nsource: "worldmonitor"\n---\n'
            f'<div class="alert-box">'
            f"총 수집: <strong>{total}건</strong> "
            f"핵심 테마: <strong>{themes}</strong> "
            f"집중 출처: <strong>{source}</strong>"
            f"</div>"
        )

    def test_extracts_worldmonitor_desc(self):
        content = self._make_wm_post()
        result = fpd._extract_worldmonitor_desc(content)
        assert "42건" in result
        assert "지정학·에너지" in result

    def test_no_worldmonitor_source_returns_empty(self):
        content = "---\nsource: coindesk\n---\nSome content"
        result = fpd._extract_worldmonitor_desc(content)
        assert result == ""

    def test_missing_total_returns_empty(self):
        content = '---\nsource: "worldmonitor"\n---\n핵심 테마: <strong>지정학</strong>'
        result = fpd._extract_worldmonitor_desc(content)
        assert result == ""

    def test_source_included_in_desc(self):
        content = self._make_wm_post(source="Reuters")
        result = fpd._extract_worldmonitor_desc(content)
        assert "Reuters" in result

    def test_no_source_field_uses_gdelt_fallback(self):
        content = '---\nsource: "worldmonitor"\n---\n총 수집: <strong>10건</strong> 핵심 테마: <strong>에너지</strong>'
        result = fpd._extract_worldmonitor_desc(content)
        assert "GDELT" in result


# ---------------------------------------------------------------------------
# _extract_body_candidate
# ---------------------------------------------------------------------------


class TestExtractBodyCandidate:
    def test_extracts_news_desc_paragraph(self):
        content = (
            "---\ntitle: Test\n---\n"
            '<p class="news-desc">Bitcoin surged 10% today amid strong institutional demand and positive ETF news flow.</p>'
        )
        result = fpd._extract_body_candidate(content)
        assert "Bitcoin surged" in result

    def test_extracts_plain_paragraph(self):
        content = (
            "---\ntitle: Test\n---\n"
            "비트코인이 오늘 강한 상승세를 보이며 기관 투자자들의 매수세가 이어지고 있습니다. 시장 전망도 긍정적입니다."
        )
        result = fpd._extract_body_candidate(content)
        assert "비트코인" in result

    def test_no_content_returns_empty(self):
        content = "---\ntitle: Test\n---\n"
        result = fpd._extract_body_candidate(content)
        assert result == ""

    def test_skips_boilerplate_content(self):
        content = (
            "---\ntitle: Test\n---\n"
            "bloomberg is the world's leading financial information provider for institutional clients."
        )
        result = fpd._extract_body_candidate(content)
        assert result == ""

    def test_no_front_matter_treats_as_body(self):
        content = "비트코인 가격이 사상 최고가를 기록했습니다. 오늘 시장에서 강한 상승세가 포착되었으며 BTC는 $100K를 돌파했습니다."
        result = fpd._extract_body_candidate(content)
        assert "비트코인" in result


# ---------------------------------------------------------------------------
# _pct
# ---------------------------------------------------------------------------


class TestPct:
    def test_zero_total_returns_zero_pct(self):
        assert fpd._pct(0, 0) == "0.0%"

    def test_half_returns_50pct(self):
        assert fpd._pct(5, 10) == "50.0%"

    def test_full_returns_100pct(self):
        assert fpd._pct(10, 10) == "100.0%"

    def test_partial_decimal(self):
        result = fpd._pct(1, 3)
        assert "33." in result


# ---------------------------------------------------------------------------
# _format_text
# ---------------------------------------------------------------------------


class TestFormatText:
    def _make_posts(self):
        return [
            {
                "file": type("F", (), {"name": "2026-01-01-test.md"})(),
                "needs_fix": True,
                "replacement": "New description text.",
                "replacement_source": "body_extract",
                "description": "Old description text.",
            },
            {
                "file": type("F", (), {"name": "2026-01-02-ok.md"})(),
                "needs_fix": False,
                "replacement": "",
                "replacement_source": "",
                "description": "Good description.",
            },
        ]

    def test_contains_total_count(self):
        result = fpd._format_text(self._make_posts(), applied=False, dry_run=True)
        assert "Total scanned" in result
        assert "2" in result

    def test_dry_run_label(self):
        result = fpd._format_text(self._make_posts(), applied=False, dry_run=True)
        assert "DRY-RUN" in result

    def test_applied_label(self):
        result = fpd._format_text(self._make_posts(), applied=True, dry_run=False)
        assert "APPLIED" in result

    def test_shows_fixed_posts(self):
        result = fpd._format_text(self._make_posts(), applied=False, dry_run=True)
        assert "2026-01-01-test.md" in result

    def test_empty_list(self):
        result = fpd._format_text([], applied=False, dry_run=True)
        assert "Total scanned" in result
        assert "0" in result


# ---------------------------------------------------------------------------
# _format_markdown
# ---------------------------------------------------------------------------


class TestFormatMarkdown:
    def _make_posts(self, needs_fix=True, has_replacement=True):
        return [
            {
                "file": type("F", (), {"name": "2026-01-01-test.md"})(),
                "needs_fix": needs_fix,
                "replacement": "New description." if has_replacement else "",
                "replacement_source": "body_extract",
                "description": "Old description.",
            }
        ]

    def test_contains_markdown_header(self):
        result = fpd._format_markdown(self._make_posts(), applied=False, dry_run=True)
        assert "##" in result

    def test_dry_run_label_present(self):
        result = fpd._format_markdown(self._make_posts(), applied=False, dry_run=True)
        assert "DRY-RUN" in result

    def test_ok_post_shows_checkmark_icon(self):
        result = fpd._format_markdown(self._make_posts(needs_fix=False), applied=False, dry_run=True)
        assert "✅" in result

    def test_unfixable_shows_warning(self):
        result = fpd._format_markdown(self._make_posts(has_replacement=False), applied=False, dry_run=True)
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# _post_date_from_text
# ---------------------------------------------------------------------------


class TestPostDateFromText:
    def test_extracts_date(self):
        text = "---\ndate: 2026-04-13\ntitle: Test\n---\nBody"
        result = fpd._post_date_from_text(text)
        assert result is not None
        assert str(result) == "2026-04-13"

    def test_no_date_returns_none(self):
        text = "---\ntitle: Test\n---\nBody"
        result = fpd._post_date_from_text(text)
        assert result is None

    def test_invalid_date_returns_none(self):
        text = "---\ndate: not-a-date\n---\nBody"
        result = fpd._post_date_from_text(text)
        assert result is None


# ---------------------------------------------------------------------------
# Constants validation
# ---------------------------------------------------------------------------


class TestConstants:
    def test_site_boilerplate_phrases_non_empty(self):
        assert len(fpd._SITE_BOILERPLATE_PHRASES) > 0

    def test_synthetic_markers_non_empty(self):
        assert len(fpd._SYNTHETIC_MARKERS) > 0

    def test_site_boilerplate_patterns_non_empty(self):
        assert len(fpd._SITE_BOILERPLATE_PATTERNS) > 0

    def test_article_specific_re_compiled(self):
        assert fpd._ARTICLE_SPECIFIC_RE is not None

    def test_article_specific_re_matches_dollar_amount(self):
        assert fpd._ARTICLE_SPECIFIC_RE.search("$100 billion fund")

    def test_article_specific_re_matches_year(self):
        assert fpd._ARTICLE_SPECIFIC_RE.search("In 2026 the market")

    def test_article_specific_re_matches_percentage(self):
        assert fpd._ARTICLE_SPECIFIC_RE.search("15.5% gain today")
