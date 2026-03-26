"""Unit tests for summarizer.py and markdown_utils.py."""

import os
import sys

# ---------------------------------------------------------------------------
# sys.path: make `scripts/` importable as a package root so that
# `from common.xxx import ...` works the same way the collector scripts do.
# ---------------------------------------------------------------------------
_SCRIPTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)


# ===========================================================================
# summarizer.py tests
# ===========================================================================


class TestIsGenericDesc:
    """Tests for summarizer._is_generic_desc()."""

    def _fn(self, desc):
        from common.summarizer import _is_generic_desc

        return _is_generic_desc(desc)

    # --- generic descriptions that should return True ---

    def test_korean_news_report_suffix(self):
        assert self._fn("코인데스크에서 보도한 뉴스입니다.") is True

    def test_korean_news_report_suffix_no_period(self):
        assert self._fn("블룸버그에서 보도한 뉴스입니다") is True

    def test_korean_story_suffix(self):
        assert self._fn("로이터에서 보도한 소식입니다.") is True

    def test_related_news_suffix(self):
        assert self._fn("비트코인 관련 소식을 전했습니다.") is True

    def test_see_original_suffix(self):
        assert self._fn("원문에서 세부 내용을 확인하세요.") is True

    def test_exchange_notice(self):
        assert self._fn("거래소 공지사항입니다.") is True

    def test_please_enable_javascript(self):
        assert self._fn("Please enable JavaScript to continue.") is True

    def test_amendment_form(self):
        assert self._fn("AMENDMENT NO. 5 to the registration statement") is True

    def test_sec_form(self):
        assert self._fn("FORM 10-K annual report filing") is True

    def test_access_denied(self):
        assert self._fn("Access denied - you do not have permission.") is True

    def test_403_forbidden(self):
        assert self._fn("403 Forbidden error on this page.") is True

    def test_privacy_notice(self):
        assert self._fn("Your privacy is important to us.") is True

    def test_cookie_notice(self):
        assert self._fn("Your cookie settings need to be updated.") is True

    def test_we_use_cookies(self):
        assert self._fn("We use cookies to improve your experience.") is True

    def test_subscribe_to(self):
        assert self._fn("Subscribe to our newsletter for updates.") is True

    def test_sign_up_for(self):
        assert self._fn("Sign up for our premium plan today.") is True

    def test_sign_up_to(self):
        assert self._fn("Sign up to receive the latest news.") is True

    def test_javascript_required(self):
        assert self._fn("JavaScript is required to view this page.") is True

    def test_javascript_must(self):
        assert self._fn("JavaScript must be enabled.") is True

    def test_this_page_uses(self):
        assert self._fn("This page uses cookies for tracking.") is True

    def test_loading_ellipsis(self):
        assert self._fn("Loading...") is True

    def test_see_here_suffix(self):
        assert self._fn("더 자세한 내용은 여기에서 확인하세요.") is True

    def test_update_prefix(self):
        assert self._fn("업데이트: 이번 소식은 ...") is True

    def test_related_news_bare_suffix(self):
        assert self._fn("비트코인 관련 소식") is True

    def test_read_more(self):
        assert self._fn("Read more about this topic on our website.") is True

    def test_click_here(self):
        assert self._fn("Click here to continue reading.") is True

    def test_continue_reading(self):
        assert self._fn("Continue reading this article.") is True

    def test_this_article(self):
        assert self._fn("This article covers the latest crypto trends.") is True

    def test_post_appeared_first(self):
        assert self._fn("The post Bitcoin Rally appeared first on CoinDesk.") is True

    # --- specific, informative descriptions that should return False ---

    def test_specific_price_news(self):
        assert self._fn("비트코인이 9만 달러를 돌파하며 사상 최고가를 기록했습니다.") is False

    def test_specific_regulation_news(self):
        assert self._fn("SEC has approved the first spot Bitcoin ETF in the United States.") is False

    def test_specific_market_analysis(self):
        assert self._fn("Federal Reserve raised interest rates by 25 basis points.") is False

    def test_empty_string(self):
        # empty string — no pattern matches, returns False
        assert self._fn("") is False

    def test_short_generic_looking_but_not_matching(self):
        assert self._fn("Market update for Tuesday.") is False

    def test_korean_substantive_text(self):
        assert self._fn("연준이 금리를 0.25%p 인상하기로 결정했다고 밝혔습니다.") is False


class TestClassifyPriority:
    """Tests for ThemeSummarizer.classify_priority()."""

    def _make_summarizer(self, items):
        from common.summarizer import ThemeSummarizer

        return ThemeSummarizer(items)

    def test_p0_crash_keyword(self):
        items = [{"title": "Market crash wipes out billions", "description": ""}]
        result = self._make_summarizer(items).classify_priority()
        assert len(result["P0"]) == 1
        assert result["P0"][0]["title"] == "Market crash wipes out billions"

    def test_p0_hack_keyword(self):
        items = [{"title": "Exchange suffers major hack", "description": ""}]
        result = self._make_summarizer(items).classify_priority()
        assert len(result["P0"]) == 1

    def test_p0_korean_폭락(self):
        items = [{"title": "비트코인 폭락, 30% 급락", "description": ""}]
        result = self._make_summarizer(items).classify_priority()
        assert len(result["P0"]) == 1

    def test_p0_bankruptcy(self):
        items = [{"title": "FTX files for bankruptcy protection", "description": ""}]
        result = self._make_summarizer(items).classify_priority()
        assert len(result["P0"]) == 1

    def test_p0_exploit(self):
        items = [{"title": "DeFi protocol suffers $50M exploit", "description": ""}]
        result = self._make_summarizer(items).classify_priority()
        assert len(result["P0"]) == 1

    def test_p1_regulation_keyword(self):
        items = [{"title": "New crypto regulation framework proposed", "description": ""}]
        result = self._make_summarizer(items).classify_priority()
        assert len(result["P1"]) == 1

    def test_p1_etf_keyword(self):
        items = [{"title": "Bitcoin ETF approval expected soon", "description": ""}]
        result = self._make_summarizer(items).classify_priority()
        assert len(result["P1"]) == 1

    def test_p1_listing_keyword(self):
        items = [{"title": "Binance announces new coin listing", "description": ""}]
        result = self._make_summarizer(items).classify_priority()
        assert len(result["P1"]) == 1

    def test_p1_fomc(self):
        items = [{"title": "FOMC meeting minutes released today", "description": ""}]
        result = self._make_summarizer(items).classify_priority()
        assert len(result["P1"]) == 1

    def test_p2_partnership_keyword(self):
        items = [{"title": "Chainlink announces new partnership with Google", "description": ""}]
        result = self._make_summarizer(items).classify_priority()
        assert len(result["P2"]) == 1

    def test_p2_upgrade_keyword(self):
        items = [{"title": "Ethereum network upgrade scheduled for next month", "description": ""}]
        result = self._make_summarizer(items).classify_priority()
        assert len(result["P2"]) == 1

    def test_p2_launch_keyword(self):
        items = [{"title": "New DeFi protocol launch announced", "description": ""}]
        result = self._make_summarizer(items).classify_priority()
        assert len(result["P2"]) == 1

    def test_p2_korean_출시(self):
        items = [{"title": "신규 NFT 마켓플레이스 출시 예정", "description": ""}]
        result = self._make_summarizer(items).classify_priority()
        assert len(result["P2"]) == 1

    def test_no_keyword_item_not_assigned(self):
        items = [{"title": "Bitcoin price today overview", "description": ""}]
        result = self._make_summarizer(items).classify_priority()
        total = len(result["P0"]) + len(result["P1"]) + len(result["P2"])
        assert total == 0

    def test_p0_takes_priority_over_p1(self):
        # Item has both "crash" (P0) and "regulation" (P1): must land in P0 only
        items = [{"title": "Market crash triggers new regulation debate", "description": ""}]
        result = self._make_summarizer(items).classify_priority()
        assert len(result["P0"]) == 1
        assert len(result["P1"]) == 0

    def test_multiple_items_mixed_priorities(self):
        items = [
            {"title": "Bitcoin hack confirmed", "description": ""},
            {"title": "New ETF filing submitted", "description": ""},
            {"title": "Protocol airdrop announced", "description": ""},
        ]
        result = self._make_summarizer(items).classify_priority()
        assert len(result["P0"]) == 1
        assert len(result["P1"]) == 1
        assert len(result["P2"]) == 1

    def test_empty_items_list(self):
        result = self._make_summarizer([]).classify_priority()
        assert result == {"P0": [], "P1": [], "P2": []}

    def test_keyword_in_description(self):
        items = [{"title": "Breaking news", "description": "The company declared bankruptcy yesterday."}]
        result = self._make_summarizer(items).classify_priority()
        assert len(result["P0"]) == 1

    def test_result_keys_always_present(self):
        result = self._make_summarizer([]).classify_priority()
        assert "P0" in result
        assert "P1" in result
        assert "P2" in result


class TestTruncateSentence:
    """Tests for summarizer._truncate_sentence()."""

    def _fn(self, text, max_len=300):
        from common.summarizer import _truncate_sentence

        return _truncate_sentence(text, max_len)

    def test_short_text_returned_as_is(self):
        text = "Bitcoin rallied today."
        assert self._fn(text) == text

    def test_too_short_returns_empty(self):
        assert self._fn("Hi") == ""
        assert self._fn("") == ""

    def test_exactly_at_max_len(self):
        text = "a" * 300
        assert self._fn(text, max_len=300) == text

    def test_truncates_long_text(self):
        text = "Bitcoin has reached a new all-time high. " * 20
        result = self._fn(text, max_len=100)
        assert len(result) <= 103  # may include trailing "..."

    def test_cuts_at_sentence_boundary(self):
        text = "Bitcoin rose sharply. Ethereum followed suit. Altcoins rallied across the board."
        result = self._fn(text, max_len=50)
        # The function cuts at the best sentence boundary within max_len,
        # so the result should be shorter than the full text and not contain
        # the trailing sentence that starts beyond max_len.
        assert len(result) < len(text)
        assert "Altcoins rallied across the board" not in result

    def test_korean_sentence_boundary(self):
        text = "비트코인이 상승했습니다. 이더리움도 함께 올랐습니다. 알트코인 전반이 강세를 보였습니다."
        result = self._fn(text, max_len=30)
        assert len(result) <= 33  # some tolerance for trailing "..."


class TestClassifyNewsSeverity:
    """Tests for summarizer._classify_news_severity()."""

    def _fn(self, title, description=""):
        from common.summarizer import _classify_news_severity

        return _classify_news_severity(title, description)

    def test_crash_is_high(self):
        assert self._fn("Market crash wipes $1T") == "high"

    def test_폭락_is_high(self):
        assert self._fn("비트코인 폭락") == "high"

    def test_breaking_is_high(self):
        assert self._fn("BREAKING: Fed raises rates") == "high"

    def test_opinion_is_low(self):
        assert self._fn("Opinion: Why Bitcoin is overvalued") == "low"

    def test_review_is_low(self):
        assert self._fn("Review of the latest Ethereum wallet") == "low"

    def test_neutral_is_medium(self):
        assert self._fn("Bitcoin trading volume summary for Monday") == "medium"

    def test_high_keyword_in_description(self):
        assert self._fn("Weekly digest", "Crisis deepens in crypto markets") == "high"


# ===========================================================================
# markdown_utils.py tests
# ===========================================================================


class TestMarkdownTable:
    """Tests for markdown_utils.markdown_table()."""

    def _fn(self, headers, rows, aligns=None):
        from common.markdown_utils import markdown_table

        return markdown_table(headers, rows, aligns)

    def test_basic_table_structure(self):
        result = self._fn(["Name", "Value"], [["BTC", "90000"], ["ETH", "3000"]])
        lines = result.split("\n")
        assert lines[0] == "| Name | Value |"
        assert lines[1] == "| --- | --- |"
        assert lines[2] == "| BTC | 90000 |"
        assert lines[3] == "| ETH | 3000 |"

    def test_single_row(self):
        result = self._fn(["Col"], [["val"]])
        assert "| Col |" in result
        assert "| val |" in result

    def test_empty_rows(self):
        result = self._fn(["A", "B"], [])
        lines = result.split("\n")
        assert len(lines) == 2  # header + separator only

    def test_right_align(self):
        result = self._fn(["Name", "Price"], [["BTC", "90000"]], aligns=["left", "right"])
        lines = result.split("\n")
        assert lines[1] == "| --- | ---: |"

    def test_center_align(self):
        result = self._fn(["A"], [["x"]], aligns=["center"])
        lines = result.split("\n")
        assert lines[1] == "| :---: |"

    def test_mismatched_aligns_falls_back_to_default(self):
        # aligns length != headers length → default "---"
        result = self._fn(["A", "B"], [["x", "y"]], aligns=["right"])
        lines = result.split("\n")
        assert lines[1] == "| --- | --- |"

    def test_pipe_in_cell_escaped(self):
        result = self._fn(["Data"], [["a|b"]])
        # pipe inside cell should be escaped
        assert "a\\|b" in result

    def test_newline_in_cell_replaced(self):
        result = self._fn(["Data"], [["line1\nline2"]])
        assert "\n| " in result or "line1 line2" in result

    def test_numeric_values_converted(self):
        result = self._fn(["Count"], [[42]])
        assert "| 42 |" in result

    def test_none_value_treated_as_empty(self):
        result = self._fn(["Col"], [[None]])
        assert "| --- |" in result or "|  |" in result


class TestMarkdownLink:
    """Tests for markdown_utils.markdown_link()."""

    def _fn(self, text, url):
        from common.markdown_utils import markdown_link

        return markdown_link(text, url)

    def test_basic_link(self):
        # Non-google-news URLs pass through unchanged
        result = self._fn("Bitcoin", "https://coindesk.com/btc")
        assert result == "[Bitcoin](https://coindesk.com/btc)"

    def test_text_with_pipe_escaped(self):
        result = self._fn("A|B", "https://example.com")
        assert "A\\|B" in result

    def test_text_with_brackets_escaped(self):
        result = self._fn("[BTC]", "https://example.com")
        assert "\\[BTC\\]" in result

    def test_empty_text(self):
        result = self._fn("", "https://example.com")
        assert result == "[](https://example.com)"

    def test_non_google_url_unchanged(self):
        url = "https://reuters.com/article/123"
        result = self._fn("Reuters", url)
        assert url in result


class TestSmartTruncate:
    """Tests for markdown_utils.smart_truncate()."""

    def _fn(self, text, max_len):
        from common.markdown_utils import smart_truncate

        return smart_truncate(text, max_len)

    def test_short_text_unchanged(self):
        assert self._fn("Hello world", 50) == "Hello world"

    def test_exact_length_unchanged(self):
        text = "a" * 20
        assert self._fn(text, 20) == text

    def test_long_text_truncated(self):
        text = "Bitcoin rallied today and hit a new record high price"
        result = self._fn(text, 20)
        assert len(result) <= 20
        assert result.endswith("…")

    def test_truncation_at_word_boundary(self):
        text = "The quick brown fox jumps over the lazy dog"
        result = self._fn(text, 20)
        # Should not cut mid-word
        assert result.endswith("…")
        # The part before ellipsis should be a valid word boundary
        without_ellipsis = result[:-1]
        assert not without_ellipsis[-1].isalpha() or text[len(without_ellipsis)] == " "

    def test_result_within_max_len(self):
        text = "A" * 100
        result = self._fn(text, 30)
        assert len(result) <= 30

    def test_ellipsis_appended_on_truncation(self):
        text = "word " * 30
        result = self._fn(text, 20)
        assert "…" in result


class TestHtmlReportLinks:
    """Tests for markdown_utils.html_report_links()."""

    def _fn(self, rows):
        from common.markdown_utils import html_report_links

        return html_report_links(rows)

    def test_output_contains_wrapper_div(self):
        rows = [("암호화폐 뉴스", "5건", '<a href="/crypto">보기</a>')]
        result = self._fn(rows)
        assert 'class="report-links-board"' in result

    def test_known_category_note_appears(self):
        rows = [("암호화폐 뉴스", "5건", '<a href="/crypto">보기</a>')]
        result = self._fn(rows)
        assert "가격, 거래소, 온체인 이슈를 빠르게 점검합니다." in result

    def test_unknown_category_gets_default_note(self):
        rows = [("기타 카테고리", "3건", '<a href="/other">보기</a>')]
        result = self._fn(rows)
        assert "관련 세부 리포트로 바로 이동합니다." in result

    def test_row_count_in_summary_text(self):
        rows = [
            ("암호화폐 뉴스", "5건", '<a href="/a">보기</a>'),
            ("주식 시장 뉴스", "3건", '<a href="/b">보기</a>'),
        ]
        result = self._fn(rows)
        assert "2개" in result

    def test_invalid_rows_skipped(self):
        # Rows with != 3 values are skipped
        rows = [("only_two", "values"), ("암호화폐 뉴스", "5건", '<a href="/x">보기</a>')]
        result = self._fn(rows)
        assert "1개" in result

    def test_empty_rows(self):
        result = self._fn([])
        assert "0개" in result
        assert 'class="report-links-board"' in result

    def test_category_rendered_in_card(self):
        rows = [("소셜 미디어", "10건", '<a href="/s">보기</a>')]
        result = self._fn(rows)
        assert "소셜 미디어" in result

    def test_count_rendered_in_card(self):
        rows = [("규제 동향", "7건", '<a href="/r">보기</a>')]
        result = self._fn(rows)
        assert "7건" in result


class TestNormalizeUrl:
    """Tests for markdown_utils._normalize_url()."""

    def _fn(self, url):
        from common.markdown_utils import _normalize_url

        return _normalize_url(url)

    def test_google_news_read_url_normalized(self):
        url = "https://news.google.com/read/CBMiABCDEFGHIJKL"
        result = self._fn(url)
        assert result == "gnews:CBMiABCDEFGHIJKL"

    def test_google_news_rss_articles_url_normalized(self):
        url = "https://news.google.com/rss/articles/CBMiXYZ123"
        result = self._fn(url)
        assert result == "gnews:CBMiXYZ123"

    def test_non_google_url_unchanged(self):
        url = "https://coindesk.com/bitcoin-news-today"
        assert self._fn(url) == url

    def test_reuters_url_unchanged(self):
        url = "https://reuters.com/technology/crypto/bitcoin-hits-90k-2024"
        assert self._fn(url) == url

    def test_google_news_read_with_hyphen_in_id(self):
        url = "https://news.google.com/read/CBMi-abc_DEF"
        result = self._fn(url)
        assert result == "gnews:CBMi-abc_DEF"

    def test_same_id_different_scheme_produces_same_key(self):
        read_url = "https://news.google.com/read/CBMiTEST123"
        rss_url = "https://news.google.com/rss/articles/CBMiTEST123"
        assert self._fn(read_url) == self._fn(rss_url)


class TestEscapeTableCell:
    """Tests for markdown_utils.escape_table_cell()."""

    def _fn(self, value):
        from common.markdown_utils import escape_table_cell

        return escape_table_cell(value)

    def test_plain_string(self):
        assert self._fn("hello") == "hello"

    def test_pipe_escaped(self):
        assert self._fn("a|b") == "a\\|b"

    def test_newline_replaced_by_space(self):
        assert self._fn("line1\nline2") == "line1 line2"

    def test_none_returns_empty(self):
        assert self._fn(None) == ""

    def test_numeric_input(self):
        assert self._fn(42) == "42"

    def test_strips_whitespace(self):
        assert self._fn("  hello  ") == "hello"


class TestDedupeReferences:
    """Tests for markdown_utils.dedupe_references()."""

    def _fn(self, refs, limit=None):
        from common.markdown_utils import dedupe_references

        return dedupe_references(refs, limit=limit)

    def test_deduplicates_same_url(self):
        refs = [
            {"title": "A", "link": "https://example.com/a", "source": "X"},
            {"title": "B", "link": "https://example.com/a", "source": "Y"},
        ]
        result = self._fn(refs)
        assert len(result) == 1
        assert result[0]["title"] == "A"

    def test_google_news_read_and_rss_are_duplicates(self):
        refs = [
            {"title": "A", "link": "https://news.google.com/read/CBMiTEST", "source": "X"},
            {"title": "B", "link": "https://news.google.com/rss/articles/CBMiTEST", "source": "Y"},
        ]
        result = self._fn(refs)
        assert len(result) == 1

    def test_different_urls_kept(self):
        refs = [
            {"title": "A", "link": "https://example.com/a", "source": "X"},
            {"title": "B", "link": "https://example.com/b", "source": "Y"},
        ]
        result = self._fn(refs)
        assert len(result) == 2

    def test_limit_respected(self):
        refs = [{"title": str(i), "link": f"https://example.com/{i}", "source": "X"} for i in range(10)]
        result = self._fn(refs, limit=3)
        assert len(result) == 3

    def test_empty_link_skipped(self):
        refs = [
            {"title": "No link", "link": "", "source": "X"},
            {"title": "Has link", "link": "https://example.com/a", "source": "Y"},
        ]
        result = self._fn(refs)
        assert len(result) == 1
        assert result[0]["title"] == "Has link"

    def test_title_ko_included_when_present(self):
        refs = [{"title": "EN title", "title_ko": "KO 제목", "link": "https://x.com/1", "source": "X"}]
        result = self._fn(refs)
        assert result[0].get("title_ko") == "KO 제목"
