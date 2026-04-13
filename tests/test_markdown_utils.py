"""Tests for markdown utilities (scripts/common/markdown_utils.py)."""

from unittest.mock import MagicMock, patch

from common.markdown_utils import (
    _classify_source,
    _try_resolve_google_news_url,
    dedupe_references,
    escape_table_cell,
    html_reference_details,
    html_report_links,
    html_source_tag,
    html_table,
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

    def test_korean_sentence_boundary(self):
        # Korean text without spaces — should try sentence endings as break points
        korean = "비트코인이 급등했다." + "이더리움도 상승했다." * 5
        result = smart_truncate(korean, 30)
        assert result.endswith("…")

    def test_long_korean_no_spaces(self):
        # Long Korean without sentence endings — still truncates gracefully
        korean = "가" * 100
        result = smart_truncate(korean, 30)
        assert len(result) <= 31  # 30 + ellipsis


class TestHtmlReferenceDetails:
    def test_basic_output(self):
        refs = [{"title": "Test Article", "link": "https://example.com", "source": "News"}]
        result = html_reference_details("참고 링크", refs)
        assert "<details>" in result
        assert "Test Article" in result

    def test_empty_references(self):
        result = html_reference_details("참고", [])
        assert result == ""

    def test_no_valid_links(self):
        refs = [{"title": "No Link", "link": "", "source": "s"}]
        result = html_reference_details("참고", refs)
        assert result == ""

    def test_with_title_ko(self):
        refs = [{"title": "English", "title_ko": "한국어 제목", "link": "https://a.com", "source": "s"}]
        result = html_reference_details("참고", refs)
        assert "한국어 제목" in result

    def test_open_in_new_tab(self):
        refs = [{"title": "A", "link": "https://a.com", "source": "s"}]
        result = html_reference_details("참고", refs, open_in_new_tab=True)
        assert 'target="_blank"' in result

    def test_include_count(self):
        refs = [{"title": "A", "link": "https://a.com", "source": "s"}]
        result = html_reference_details("참고 링크", refs, include_count=True)
        assert "1건" in result


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


class TestHtmlTable:
    def test_basic_table(self):
        result = html_table(["Name", "Value"], [["BTC", "$50K"]])
        assert "<table>" in result
        assert "<th" in result
        assert "BTC" in result
        assert "$50K" in result

    def test_with_aligns(self):
        result = html_table(["A", "B"], [["1", "2"]], aligns=["left", "right"])
        assert "text-align:right" in result

    def test_without_aligns(self):
        result = html_table(["A"], [["1"]])
        assert "text-align:left" in result

    def test_multiple_rows(self):
        result = html_table(["H"], [["r1"], ["r2"], ["r3"]])
        assert result.count("<tr>") == 4  # 1 header + 3 body

    def test_empty_rows(self):
        result = html_table(["H"], [])
        assert "<tbody></tbody>" in result

    def test_mismatched_aligns_defaults_to_left(self):
        result = html_table(["A", "B"], [["1", "2"]], aligns=["center"])
        # aligns length != headers length → all default to left
        assert "text-align:left" in result


class TestHtmlReportLinks:
    def test_basic_report_links(self):
        rows = [("암호화폐 뉴스", "10건", '<a href="/crypto">보기</a>')]
        result = html_report_links(rows)
        assert "report-links-board" in result
        assert "암호화폐 뉴스" in result
        assert "10건" in result

    def test_multiple_categories(self):
        rows = [
            ("암호화폐 뉴스", "5건", '<a href="/a">보기</a>'),
            ("규제 동향", "3건", '<a href="/b">보기</a>'),
        ]
        result = html_report_links(rows)
        assert "2개" in result  # summary text

    def test_unknown_category_uses_default_note(self):
        rows = [("미지의 카테고리", "1건", '<a href="/x">보기</a>')]
        result = html_report_links(rows)
        assert "관련 세부 리포트로 바로 이동합니다" in result

    def test_skips_invalid_rows(self):
        rows = [("only", "two"), ("valid", "3건", '<a href="/x">보기</a>')]
        result = html_report_links(rows)
        assert "1개" in result  # only 1 valid row

    def test_empty_rows(self):
        result = html_report_links([])
        assert "0개" in result


class TestTryResolveGoogleNewsUrl:
    def test_non_google_url_returned_unchanged(self):
        url = "https://example.com/article"
        assert _try_resolve_google_news_url(url) == url

    def test_empty_url_returned_unchanged(self):
        assert _try_resolve_google_news_url("") == ""

    def test_base64_decode_rss_articles_path(self):
        # Craft a base64-encoded payload containing a real URL so the decode
        # branch (lines 20-36) is exercised and returns the inner URL.
        import base64

        inner = "https://reuters.com/article/bitcoin"
        encoded = base64.urlsafe_b64encode(inner.encode()).decode().rstrip("=")
        google_url = f"https://news.google.com/rss/articles/{encoded}"
        result = _try_resolve_google_news_url(google_url)
        assert result == inner

    def test_base64_decode_read_path(self):
        import base64

        inner = "https://coindesk.com/article/eth"
        encoded = base64.urlsafe_b64encode(inner.encode()).decode().rstrip("=")
        google_url = f"https://news.google.com/read/{encoded}"
        result = _try_resolve_google_news_url(google_url)
        assert result == inner

    def test_base64_decode_resolves_to_google_falls_through(self):
        # If decoded URL contains google.com, should not be returned; falls
        # through to HTTP redirect or returns original.
        import base64

        inner = "https://google.com/something"
        encoded = base64.urlsafe_b64encode(inner.encode()).decode().rstrip("=")
        google_url = f"https://news.google.com/rss/articles/{encoded}"
        # HTTP redirect will also fail (mocked), so original URL is returned.
        with patch("requests.head", side_effect=Exception("no network")):
            result = _try_resolve_google_news_url(google_url)
        assert result == google_url

    def test_http_redirect_followed_when_base64_fails(self):
        # Use a URL with no decodable base64 payload so decode branch raises/skips,
        # then verify the HTTP redirect branch (lines 41-54) is exercised.
        google_url = "https://news.google.com/rss/articles/!!!invalid!!!"
        mock_resp = MagicMock()
        mock_resp.url = "https://reuters.com/redirected"
        with patch("requests.head", return_value=mock_resp) as mock_head:
            result = _try_resolve_google_news_url(google_url)
        mock_head.assert_called_once()
        assert result == "https://reuters.com/redirected"

    def test_http_redirect_to_google_ignored(self):
        google_url = "https://news.google.com/rss/articles/!!!invalid!!!"
        mock_resp = MagicMock()
        mock_resp.url = "https://google.com/still-google"
        with patch("requests.head", return_value=mock_resp):
            result = _try_resolve_google_news_url(google_url)
        assert result == google_url

    def test_http_redirect_exception_returns_original(self):
        google_url = "https://news.google.com/rss/articles/!!!invalid!!!"
        with patch("requests.head", side_effect=Exception("timeout")):
            result = _try_resolve_google_news_url(google_url)
        assert result == google_url

    def test_base64_decode_exception_falls_through_to_http(self):
        # Trigger the except-branch (lines 37-38) by making base64 decode raise,
        # then have HTTP redirect also fail so the original URL is returned.
        import base64 as _base64

        google_url = "https://news.google.com/rss/articles/CBMiSOMEARTICLE"
        with patch.object(_base64, "urlsafe_b64decode", side_effect=ValueError("bad padding")):
            with patch("requests.head", side_effect=Exception("no network")):
                result = _try_resolve_google_news_url(google_url)
        assert result == google_url


class TestSmartTruncateKoreanBranch:
    def test_korean_sentence_ending_used_as_break(self):
        # Need: len(text) > max_len, no spaces (so last_space < 70% threshold),
        # and a "다." ending at index >= 50% of max_len within candidate.
        # max_len=20: candidate = text[:19], 50% threshold = 10, 70% threshold = 14
        # Place "다." at index 10 so ko_idx=10 >= 10, qualifies.
        # "가나다라마바사아자다.카타파하마바사아" — 20 chars, "다." at index 9-10
        # Actually "다" at index 9, "다." ends at index 10 (ko_idx=9, +len("다.")=2 → candidate[:11])
        # 9 >= int(20*0.5)=10? No. Use max_len=18: 50%=9, so index 9 qualifies.
        text = "가나다라마바사아다.카타파하마바사아"  # 18 chars, "다." at index 8
        # max_len=16: candidate=text[:15], 50% threshold=8, "다." rfind in [:15]
        # "다." is at index 8 in text, ko_idx=8 >= int(16*0.5)=8 → qualifies
        result = smart_truncate(text, 16)
        assert "다." in result
        assert result.endswith("…")

    def test_korean_no_matching_ending_falls_back_to_hard_cut(self):
        # Text with no Korean sentence endings — falls through the for loop
        # without breaking, so candidate is used as-is (hard cut + ellipsis).
        text = "가나다라마바사아자차카타파하" * 3
        result = smart_truncate(text, 20)
        assert result.endswith("…")
        assert len(result) <= 21  # 20 chars + ellipsis
