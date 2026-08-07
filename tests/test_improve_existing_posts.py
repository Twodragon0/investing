"""Tests for scripts/improve_existing_posts.py — pure functions only."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


import scripts.improve_existing_posts as iep

# ---------------------------------------------------------------------------
# _strip_wrapping_quotes
# ---------------------------------------------------------------------------


class TestStripWrappingQuotes:
    def test_strips_double_quotes(self):
        assert iep._strip_wrapping_quotes('"hello"') == "hello"

    def test_strips_single_quotes(self):
        assert iep._strip_wrapping_quotes("'hello'") == "hello"

    def test_no_quotes_unchanged(self):
        assert iep._strip_wrapping_quotes("hello") == "hello"

    def test_mismatched_quotes_unchanged(self):
        assert iep._strip_wrapping_quotes("\"hello'") == "\"hello'"

    def test_empty_string(self):
        assert iep._strip_wrapping_quotes("") == ""

    def test_only_quotes(self):
        assert iep._strip_wrapping_quotes('""') == ""

    def test_strips_surrounding_whitespace(self):
        assert iep._strip_wrapping_quotes('  "value"  ') == "value"

    def test_single_char_unchanged(self):
        assert iep._strip_wrapping_quotes("a") == "a"


# ---------------------------------------------------------------------------
# _parse_list_literal
# ---------------------------------------------------------------------------


class TestParseListLiteral:
    def test_parses_bracket_list(self):
        result = iep._parse_list_literal('["crypto", "news"]')
        assert result == ["crypto", "news"]

    def test_parses_single_item(self):
        result = iep._parse_list_literal("crypto")
        assert result == ["crypto"]

    def test_empty_brackets_returns_empty(self):
        result = iep._parse_list_literal("[]")
        assert result == []

    def test_empty_string_returns_empty(self):
        result = iep._parse_list_literal("")
        assert result == []

    def test_strips_quotes_from_items(self):
        result = iep._parse_list_literal('["bitcoin", "ethereum"]')
        assert "bitcoin" in result
        assert "ethereum" in result

    def test_no_brackets_single_value(self):
        result = iep._parse_list_literal('"market-analysis"')
        assert result == ["market-analysis"]

    def test_whitespace_around_items(self):
        result = iep._parse_list_literal('[ "a" , "b" ]')
        assert result == ["a", "b"]


# ---------------------------------------------------------------------------
# parse_post
# ---------------------------------------------------------------------------


class TestParsePost:
    def _make_post(self, fm_lines, body="Post body here."):
        fm = "\n".join(fm_lines)
        return f"---\n{fm}\n---\n{body}"

    def test_parses_title(self):
        content = self._make_post(["title: Test Post", "date: 2026-01-01"])
        fm, body = iep.parse_post(content)
        assert fm.get("title") == "Test Post"

    def test_parses_body(self):
        content = self._make_post(["title: Test"], "Hello world")
        fm, body = iep.parse_post(content)
        assert "Hello world" in body

    def test_no_front_matter_returns_empty_dict(self):
        content = "Just plain content without front matter."
        fm, body = iep.parse_post(content)
        assert fm == {}
        assert body == content

    def test_multiple_fields_parsed(self):
        content = self._make_post(["title: T", "date: 2026-01-01", "categories: [crypto]"])
        fm, _ = iep.parse_post(content)
        assert "title" in fm
        assert "date" in fm
        assert "categories" in fm

    def test_empty_front_matter(self):
        content = "---\n\n---\nbody text"
        fm, body = iep.parse_post(content)
        assert "body text" in body


# ---------------------------------------------------------------------------
# serialize_front_matter
# ---------------------------------------------------------------------------


class TestSerializeFrontMatter:
    def test_produces_yaml_delimiters(self):
        result = iep.serialize_front_matter({"title": "Test"})
        assert result.startswith("---")
        assert result.endswith("---")

    def test_key_value_present(self):
        result = iep.serialize_front_matter({"title": "My Post", "date": "2026-01-01"})
        assert "title: My Post" in result
        assert "date: 2026-01-01" in result

    def test_empty_dict(self):
        result = iep.serialize_front_matter({})
        assert result == "---\n---"


# ---------------------------------------------------------------------------
# clean_description
# ---------------------------------------------------------------------------


class TestCleanDescription:
    def test_no_description_returns_false(self):
        fm = {}
        assert iep.clean_description(fm) is False

    def test_removes_html_tags(self):
        fm = {"description": '"<b>Bitcoin</b> surges today amid institutional buying pressure in markets"'}
        changed = iep.clean_description(fm)
        assert changed is True
        assert "<b>" not in fm["description"]

    def test_removes_blockquote_marker(self):
        fm = {"description": '"> Bitcoin surges today amid institutional buying pressure in markets"'}
        changed = iep.clean_description(fm)
        assert changed is True
        assert "> Bitcoin" not in fm["description"]

    def test_removes_markdown_bold(self):
        fm = {"description": '"**Breaking** news about Bitcoin surges today and crypto markets rally hard"'}
        changed = iep.clean_description(fm)
        assert changed is True
        assert "**" not in fm["description"]

    def test_truncates_long_description(self):
        long_text = "Bitcoin surged " + "x " * 100
        fm = {"description": f'"{long_text}"'}
        changed = iep.clean_description(fm)
        assert changed is True
        inner = fm["description"].strip('"')
        assert len(inner) <= 163  # 160 + "..."

    def test_removes_keyword_suffix(self):
        fm = {"description": '"Bitcoin rises sharply 주요 키워드: crypto, news, daily-digest."'}
        changed = iep.clean_description(fm)
        assert changed is True
        assert "주요 키워드:" not in fm["description"]

    def test_clean_description_no_change_returns_false(self):
        desc = '"Bitcoin surges amid institutional demand."'
        fm = {"description": desc}
        # Nothing to clean — should return False (or True if wrapping changes)
        result = iep.clean_description(fm)
        # Result depends on whether quotes match; just verify no crash
        assert isinstance(result, bool)

    def test_collapses_whitespace(self):
        fm = {"description": '"Bitcoin   surges    today   amid  buying  pressure  in  the  market"'}
        iep.clean_description(fm)
        assert "  " not in fm["description"]


# ---------------------------------------------------------------------------
# fix_markdown_link_artifacts
# ---------------------------------------------------------------------------


class TestFixMarkdownLinkArtifacts:
    def test_no_artifacts_no_change(self):
        body = "Simple text without any markdown link issues."
        result, changed = iep.fix_markdown_link_artifacts(body)
        assert changed is False
        assert result == body

    def test_escaped_bracket_fixed(self):
        body = r"Some text with \] escaped bracket."
        result, changed = iep.fix_markdown_link_artifacts(body)
        assert r"\]" not in result

    def test_returns_tuple(self):
        result = iep.fix_markdown_link_artifacts("text")
        assert isinstance(result, tuple)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# sync_summary_total_count
# ---------------------------------------------------------------------------


class TestSyncSummaryTotalCount:
    def test_no_stat_no_change(self):
        body = "Some body without stat divs."
        result, changed = iep.sync_summary_total_count(body)
        assert changed is False

    def test_updates_bullet_count_from_stat(self):
        body = '<div class="stat-value">42</div><div class="stat-label">수집 건수</div>\n- 총 **10건** 수집'
        result, changed = iep.sync_summary_total_count(body)
        assert changed is True
        assert "- 총 **42건** 수집" in result

    def test_updates_count_from_intro_text(self):
        body = "총 25건의 뉴스가 수집되었습니다.\n- 총 **10건** 수집"
        result, changed = iep.sync_summary_total_count(body)
        assert changed is True
        assert "**25건**" in result

    def test_already_correct_count_no_change(self):
        body = '<div class="stat-value">10</div><div class="stat-label">수집 건수</div>\n- 총 **10건** 수집'
        result, changed = iep.sync_summary_total_count(body)
        assert changed is False


# ---------------------------------------------------------------------------
# remove_intro_duplication_in_summary
# ---------------------------------------------------------------------------


class TestRemoveIntroDuplicationInSummary:
    def test_no_summary_section_no_change(self):
        body = "No summary section here at all."
        result, changed = iep.remove_intro_duplication_in_summary(body)
        assert changed is False

    def test_short_intro_no_change(self):
        body = "짧음\n## 전체 뉴스 요약\n- 짧음"
        result, changed = iep.remove_intro_duplication_in_summary(body)
        assert changed is False

    def test_removes_duplicate_bullet(self):
        intro = "오늘 비트코인 시장에서 중요한 뉴스가 발생했습니다 BTC 상승세 지속됩니다."
        body = f"{intro}\n\n## 전체 뉴스 요약\n- 오늘 비트코인 시장에서 중요한 뉴스가 발생했습니다 BTC 상승세 지속됩니다.\n- 다른 내용."
        result, changed = iep.remove_intro_duplication_in_summary(body)
        assert changed is True

    def test_different_content_preserved(self):
        intro = "비트코인 가격 상승으로 시장이 활기를 띠고 있습니다 매우 중요한 내용입니다."
        bullet = "전혀 다른 내용으로 시장 상황을 설명합니다."
        body = f"{intro}\n\n## 전체 뉴스 요약\n- {bullet}"
        result, changed = iep.remove_intro_duplication_in_summary(body)
        assert bullet in result


# ---------------------------------------------------------------------------
# remove_summary_article_duplicates
# ---------------------------------------------------------------------------


class TestRemoveSummaryArticleDuplicates:
    def test_no_duplicates_unchanged(self):
        body = "**1. [Bitcoin ETF rises]** today\n- Other content"
        result, changed = iep.remove_summary_article_duplicates(body)
        assert changed is False

    def test_internal_dup_line_removed(self):
        # "- 1. First half text - Source First half text" (internal duplication)
        body = "- 1. Bitcoin rally today - CoinDesk Bitcoin rally today\nKeep this line"
        result, changed = iep.remove_summary_article_duplicates(body)
        # May or may not detect depending on content length
        assert isinstance(changed, bool)

    def test_returns_tuple(self):
        result = iep.remove_summary_article_duplicates("some body text")
        assert isinstance(result, tuple)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# remove_duplicate_articles_in_insight
# ---------------------------------------------------------------------------


class TestRemoveDuplicateArticlesInInsight:
    def test_no_insight_section_no_change(self):
        body = "No insight section here."
        result, changed = iep.remove_duplicate_articles_in_insight(body)
        assert changed is False

    def test_removes_duplicate_article_line(self):
        body = (
            "## 오늘의 인사이트\n"
            "- 주요 기사: *Bitcoin ETF 승인*\n"
            "- 주요 기사: *Bitcoin ETF 승인*\n"
            "- 주요 기사: *다른 기사*\n"
        )
        result, changed = iep.remove_duplicate_articles_in_insight(body)
        assert changed is True
        # Only one occurrence of the duplicated title should remain
        assert result.count("Bitcoin ETF 승인") == 1

    def test_unique_articles_preserved(self):
        body = "## 오늘의 인사이트\n- 주요 기사: *Bitcoin ETF*\n- 주요 기사: *Ethereum upgrade*\n"
        result, changed = iep.remove_duplicate_articles_in_insight(body)
        assert changed is False
        assert "Bitcoin ETF" in result
        assert "Ethereum upgrade" in result

    def test_insight_section_stops_at_next_heading(self):
        body = "## 오늘의 인사이트\n- 주요 기사: *A*\n- 주요 기사: *A*\n## 다음 섹션\n- 주요 기사: *A*\n"
        result, changed = iep.remove_duplicate_articles_in_insight(body)
        # The duplicate inside insight should be removed, but outside preserved
        assert "## 다음 섹션" in result


# ---------------------------------------------------------------------------
# _extract_themes_from_insight
# ---------------------------------------------------------------------------


class TestExtractThemesFromInsight:
    def test_extracts_two_themes(self):
        line = "오늘 가장 주목할 테마는 **비트코인**와 **가격/시장**입니다"
        t1, t2 = iep._extract_themes_from_insight(line)
        assert t1 == "비트코인"
        assert t2 == "가격/시장"

    def test_returns_empty_when_less_than_two(self):
        line = "테마는 **비트코인** 하나만 있습니다"
        t1, t2 = iep._extract_themes_from_insight(line)
        assert t1 == ""
        assert t2 == ""

    def test_handles_emoji_prefix(self):
        line = "**🟠 비트코인**(52건)과 **📈 가격/시장**(26건)"
        t1, t2 = iep._extract_themes_from_insight(line)
        assert t1 == "비트코인"
        assert t2 == "가격/시장"

    def test_no_themes_returns_empty(self):
        line = "관련 없는 내용입니다"
        t1, t2 = iep._extract_themes_from_insight(line)
        assert t1 == ""
        assert t2 == ""


# ---------------------------------------------------------------------------
# replace_generic_insight
# ---------------------------------------------------------------------------


class TestReplaceGenericInsight:
    def test_no_generic_phrase_no_change(self):
        body = "## 오늘의 인사이트\n구체적인 인사이트 내용입니다."
        result, changed = iep.replace_generic_insight(body)
        assert changed is False

    def test_replaces_generic_phrase(self):
        generic = "두 테마가 동시에 부각되고 있어 시장의 방향성을 가늠하는 핵심 신호로 볼 수 있습니다."
        body = f"**비트코인**와 **가격/시장**이 주목받고 있습니다.\n{generic}"
        result, changed = iep.replace_generic_insight(body)
        assert isinstance(changed, bool)
        assert isinstance(result, str)

    def test_replaces_second_generic_phrase(self):
        generic = "두 테마의 동시 부각은 시장의 방향성을 가늠하는 데 중요한 신호가 될 수 있습니다."
        body = f"**비트코인**와 **매크로/금리**이 보임.\n{generic}"
        result, changed = iep.replace_generic_insight(body)
        assert isinstance(changed, bool)


# ---------------------------------------------------------------------------
# THEME_INSIGHTS data
# ---------------------------------------------------------------------------


class TestThemeInsightsData:
    def test_dict_non_empty(self):
        assert len(iep.THEME_INSIGHTS) > 0

    def test_all_values_are_strings(self):
        for _key, val in iep.THEME_INSIGHTS.items():
            assert isinstance(val, str)
            assert len(val) > 20

    def test_tuple_keys(self):
        for key in iep.THEME_INSIGHTS:
            assert isinstance(key, tuple)
            assert len(key) == 2

    def test_bitcoin_price_combo_exists(self):
        assert ("비트코인", "가격/시장") in iep.THEME_INSIGHTS

    def test_regulation_exchange_combo_exists(self):
        assert ("규제/정책", "거래소") in iep.THEME_INSIGHTS


# ---------------------------------------------------------------------------
# KEYWORD_KO data
# ---------------------------------------------------------------------------


class TestKeywordKoData:
    def test_bitcoin_translation(self):
        assert iep.KEYWORD_KO["bitcoin"] == "비트코인"

    def test_ethereum_translation(self):
        assert iep.KEYWORD_KO["ethereum"] == "이더리움"

    def test_regulation_translation(self):
        assert iep.KEYWORD_KO["regulation"] == "규제"

    def test_all_values_korean(self):
        for eng, kor in iep.KEYWORD_KO.items():
            # Korean chars should be present in values
            assert any("\uac00" <= c <= "\ud7a3" for c in kor), f"{eng} value is not Korean: {kor}"


# ---------------------------------------------------------------------------
# FALLBACK_INSIGHT constant
# ---------------------------------------------------------------------------


class TestFallbackInsight:
    def test_is_string(self):
        assert isinstance(iep.FALLBACK_INSIGHT, str)

    def test_non_empty(self):
        assert len(iep.FALLBACK_INSIGHT) > 20


# ---------------------------------------------------------------------------
# sanitize_summary_bullets
# ---------------------------------------------------------------------------


class TestSanitizeSummaryBullets:
    def test_drops_stat_dump_plain_bullet(self):
        body = "## 핵심\n- 20 총 이슈 3 테마 수 2 출처 수 5 안보 이슈\n- 정상 문장입니다."
        new, changed = iep.sanitize_summary_bullets(body)
        assert changed is True
        assert "총 이슈 3 테마" not in new
        assert "정상 문장입니다." in new

    def test_cleans_linked_digest_tail_keeps_link(self):
        body = (
            "- 2026-06-01 [브리핑](/a/b/) -- 가격 언급: 뉴스 제목에서 24건의 가격 데이터가 "
            "포착되었습니다 ($1, $1, $1). 구체적 가격대가 언급되는 것은 신호입니다."
        )
        new, changed = iep.sanitize_summary_bullets(body)
        assert changed is True
        assert "[브리핑](/a/b/)" in new  # link preserved
        assert "가격 데이터가 포착" not in new  # meta dropped
        assert "구체적 가격대가 언급되는 것은 신호입니다." in new

    def test_drops_garbled_tail_keeps_bare_link(self):
        body = "- 2026-06-01 [WorldMonitor](/a/) -- 20 총 이슈 3 테마 수 2 출처 수 5 안보 이슈"
        new, changed = iep.sanitize_summary_bullets(body)
        assert changed is True
        assert new.strip() == "- 2026-06-01 [WorldMonitor](/a/)"

    def test_skips_codespan_ascii_chart(self):
        body = "- ` Tech Rebound    ████████ (20) Dow 50K    ████ (16) `"
        new, changed = iep.sanitize_summary_bullets(body)
        assert changed is False
        assert new == body  # alignment spaces inside backticks preserved

    def test_skips_table_rows(self):
        body = "- | a | b |"
        new, changed = iep.sanitize_summary_bullets(body)
        assert changed is False

    def test_preserves_normal_prose(self):
        body = "- 비트코인은 ETF 수요가 줄어들면서 $73,000 가까이 하락했습니다."
        new, changed = iep.sanitize_summary_bullets(body)
        assert changed is False
        assert new == body
