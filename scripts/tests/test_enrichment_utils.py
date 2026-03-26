"""Unit tests for enrichment.py, formatters.py, and utils.py."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
import requests

# ---------------------------------------------------------------------------
# enrichment.py tests
# ---------------------------------------------------------------------------
from common.enrichment import (
    _analyze_korean_title,
    _dedup_entities,
    _extract_og_metadata,
    _extract_raw_patterns,
    _extract_title_entities,
    _extract_via_paragraphs,
    _filter_entities,
)


class TestExtractRawPatterns:
    def test_english_tickers(self):
        tickers, values, proper, kr = _extract_raw_patterns("AAPL and MSFT hit record highs")
        assert "AAPL" in tickers
        assert "MSFT" in tickers

    def test_dollar_values(self):
        _, values, _, _ = _extract_raw_patterns("Bitcoin hits $50,000 mark")
        assert any("50,000" in v for v in values)

    def test_percentage(self):
        _, values, _, _ = _extract_raw_patterns("S&P 500 rises 2.5% today")
        assert "2.5%" in values

    def test_korean_entities(self):
        _, _, _, kr = _extract_raw_patterns("삼성전자 주가 급등")
        assert "삼성전자" in kr
        assert "주가" in kr

    def test_proper_nouns(self):
        _, _, proper, _ = _extract_raw_patterns("Bitcoin surges as Federal Reserve signals pause")
        assert "Bitcoin" in proper or "Federal" in proper

    def test_empty_string(self):
        tickers, values, proper, kr = _extract_raw_patterns("")
        assert tickers == []
        assert values == []
        assert proper == []
        assert kr == []

    def test_mixed_title(self):
        tickers, values, proper, kr = _extract_raw_patterns("BTC 비트코인 $45,000 surge 5%")
        assert "BTC" in tickers
        assert "비트코인" in kr
        assert any("45,000" in v for v in values)
        assert "5%" in values


class TestFilterEntities:
    def test_removes_noise_tickers(self):
        clean_tickers, _ = _filter_entities(["AAPL", "CEO", "ETF", "MSFT"], [])
        assert "CEO" not in clean_tickers
        assert "ETF" not in clean_tickers
        assert "AAPL" in clean_tickers
        assert "MSFT" in clean_tickers

    def test_removes_common_words(self):
        _, clean_proper = _filter_entities([], ["Bitcoin", "The", "And", "Federal"])
        assert "The" not in clean_proper
        assert "And" not in clean_proper
        assert "Bitcoin" in clean_proper

    def test_empty_inputs(self):
        tickers, proper = _filter_entities([], [])
        assert tickers == []
        assert proper == []

    def test_all_noise(self):
        tickers, proper = _filter_entities(["SEC", "FED", "GDP"], ["The", "And", "For"])
        assert tickers == []
        assert proper == []


class TestDedupEntities:
    def test_basic_dedup(self):
        result = _dedup_entities(["BTC", "btc", "Bitcoin", "bitcoin"])
        assert len(result) == 2
        assert result[0] == "BTC"
        assert result[1] == "Bitcoin"

    def test_preserves_order(self):
        result = _dedup_entities(["Apple", "Google", "apple", "Microsoft"])
        assert result[0] == "Apple"
        assert result[1] == "Google"
        assert result[2] == "Microsoft"

    def test_empty(self):
        assert _dedup_entities([]) == []

    def test_no_duplicates(self):
        items = ["BTC", "ETH", "SOL"]
        assert _dedup_entities(items) == items


class TestExtractTitleEntities:
    def test_english_ticker_title(self):
        entities = _extract_title_entities("AAPL stock surges 5% after earnings beat")
        assert "5%" in entities
        assert "AAPL" in entities

    def test_korean_title(self):
        entities = _extract_title_entities("삼성전자 주가 급등 5%")
        assert "삼성전자" in entities or "5%" in entities

    def test_mixed_title(self):
        entities = _extract_title_entities("Bitcoin BTC hits $50,000 비트코인 급등")
        assert len(entities) > 0

    def test_empty_title(self):
        entities = _extract_title_entities("")
        assert entities == []

    def test_deduplication_applied(self):
        entities = _extract_title_entities("Bitcoin bitcoin BITCOIN crypto")
        # Should not have duplicates (case-insensitive)
        lower = [e.lower() for e in entities]
        assert len(lower) == len(set(lower))

    def test_limits_tickers_and_proper(self):
        # Only first 2 tickers and first 2 proper nouns should appear
        entities = _extract_title_entities("AAPL MSFT GOOG AMZN Apple Microsoft Google Amazon rise")
        tickers = [e for e in entities if e.isupper() and len(e) >= 2]
        assert len(tickers) <= 2


class TestAnalyzeKoreanTitle:
    def test_급등(self):
        result = _analyze_korean_title("코스피 급등세 지속")
        assert isinstance(result, str)
        assert len(result) > 10

    def test_폭락(self):
        result = _analyze_korean_title("비트코인 폭락 30%")
        assert "급락" in result or "30" in result

    def test_서킷브레이커(self):
        result = _analyze_korean_title("코스피 서킷브레이커 발동")
        assert "매매거래" in result or "급락" in result

    def test_서킷브레이커_매수(self):
        result = _analyze_korean_title("매수 사이드카 발동")
        assert "반등" in result or "매수" in result

    def test_반도체_매수(self):
        result = _analyze_korean_title("삼성전자 반도체 매수 기회")
        assert "매수" in result or "반도체" in result

    def test_반도체_하락(self):
        result = _analyze_korean_title("하이닉스 반도체 하락세")
        assert "약세" in result or "반도체" in result

    def test_반도체_generic(self):
        result = _analyze_korean_title("삼성전자 반도체 전망")
        assert "반도체" in result

    def test_금리(self):
        result = _analyze_korean_title("한국은행 기준금리 결정")
        assert "금리" in result or "통화정책" in result

    def test_환율(self):
        # "환율" title without surge keywords hits the 환율 category
        result = _analyze_korean_title("원달러 환율 변동 소식")
        assert "환율" in result

    def test_비트코인(self):
        result = _analyze_korean_title("비트코인 10% 상승")
        assert isinstance(result, str)
        assert len(result) > 5

    def test_비트코인_pct(self):
        # Title without surge keywords hits the bitcoin branch and includes pct
        result = _analyze_korean_title("비트코인 5% 상승")
        assert "5%" in result or "비트코인" in result

    def test_관세(self):
        result = _analyze_korean_title("미국 관세 인상 발표")
        assert "무역" in result or "관세" in result

    def test_실적(self):
        result = _analyze_korean_title("삼성 영업이익 발표")
        assert "실적" in result

    def test_외국인_수급(self):
        result = _analyze_korean_title("외국인 순매도 지속")
        assert "수급" in result or "외국인" in result

    def test_fallback(self):
        result = _analyze_korean_title("알 수 없는 뉴스 제목입니다")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_디파이(self):
        result = _analyze_korean_title("디파이 TVL 급증")
        assert "디지털" in result or "디파이" in result

    def test_AI(self):
        result = _analyze_korean_title("AI 챗봇 투자 기회")
        assert "AI" in result or "인공지능" in result


class TestExtractOgMetadata:
    def _make_soup(self, html: str):
        from bs4 import BeautifulSoup
        return BeautifulSoup(html, "html.parser")

    def test_og_description(self):
        soup = self._make_soup(
            '<meta property="og:description" content="Bitcoin reaches new all-time high in volatile session.">'
        )
        result = _extract_og_metadata(soup)
        assert "Bitcoin" in result["description"]

    def test_og_image(self):
        soup = self._make_soup(
            '<meta property="og:image" content="https://example.com/image.jpg">'
        )
        result = _extract_og_metadata(soup)
        assert result["image"] == "https://example.com/image.jpg"

    def test_twitter_image(self):
        soup = self._make_soup(
            '<meta name="twitter:image" content="https://example.com/twitter.jpg">'
        )
        result = _extract_og_metadata(soup)
        assert result["image"] == "https://example.com/twitter.jpg"

    def test_name_description(self):
        soup = self._make_soup(
            '<meta name="description" content="This is a news article about markets and trading.">'
        )
        result = _extract_og_metadata(soup)
        assert "markets" in result["description"]

    def test_empty_soup(self):
        soup = self._make_soup("<html><body></body></html>")
        result = _extract_og_metadata(soup)
        assert result["description"] == ""
        assert result["image"] == ""

    def test_noise_description_rejected(self):
        soup = self._make_soup(
            '<meta name="description" content="Please enable JavaScript to view this site.">'
        )
        result = _extract_og_metadata(soup)
        assert result["description"] == ""

    def test_short_description_rejected(self):
        # Content under 20 chars should not be returned
        soup = self._make_soup(
            '<meta property="og:description" content="Short">'
        )
        result = _extract_og_metadata(soup)
        assert result["description"] == ""

    def test_image_not_http_rejected(self):
        soup = self._make_soup(
            '<meta property="og:image" content="/relative/path/image.jpg">'
        )
        result = _extract_og_metadata(soup)
        assert result["image"] == ""


class TestExtractViaParagraphs:
    def _make_soup(self, html: str):
        from bs4 import BeautifulSoup
        return BeautifulSoup(html, "html.parser")

    def test_returns_first_substantial_paragraph(self):
        soup = self._make_soup(
            "<html><body>"
            "<p>Short.</p>"
            "<p>This is a longer paragraph with enough text to be considered substantial content for extraction.</p>"
            "</body></html>"
        )
        result = _extract_via_paragraphs(soup)
        assert "longer paragraph" in result

    def test_skips_noise_containers(self):
        soup = self._make_soup(
            '<html><body>'
            '<div class="sidebar"><p>This paragraph is inside a sidebar and has enough text to be long.</p></div>'
            '<p>This is the real article paragraph with substantial content for extraction testing purposes.</p>'
            '</body></html>'
        )
        result = _extract_via_paragraphs(soup)
        assert "real article" in result

    def test_empty_body(self):
        soup = self._make_soup("<html><body></body></html>")
        result = _extract_via_paragraphs(soup)
        assert result == ""

    def test_only_short_paragraphs(self):
        soup = self._make_soup(
            "<html><body><p>Too short.</p><p>Also short.</p></body></html>"
        )
        result = _extract_via_paragraphs(soup)
        assert result == ""


# ---------------------------------------------------------------------------
# formatters.py tests
# ---------------------------------------------------------------------------

from common.formatters import fmt_change_icon, fmt_date_kr, fmt_number, fmt_percent  # noqa: E402


class TestFmtChangeIcon:
    def test_positive(self):
        icon, display = fmt_change_icon("+3.14%")
        assert icon == "🟢"
        assert display == "+3.14%"

    def test_negative(self):
        icon, display = fmt_change_icon("-1.5%")
        assert icon == "🔴"
        assert display == "-1.50%"

    def test_zero(self):
        icon, display = fmt_change_icon("0%")
        assert icon == "🟢"
        assert display == "+0.00%"

    def test_na(self):
        icon, display = fmt_change_icon("N/A")
        assert icon == "⚪"
        assert display == "N/A"

    def test_empty_string(self):
        icon, display = fmt_change_icon("")
        assert icon == "⚪"

    def test_none(self):
        icon, display = fmt_change_icon(None)
        assert icon == "⚪"

    def test_dash(self):
        icon, display = fmt_change_icon("-")
        assert icon == "⚪"

    def test_no_sign(self):
        icon, display = fmt_change_icon("2.5%")
        assert icon == "🟢"
        assert display == "+2.50%"

    def test_invalid_string(self):
        icon, display = fmt_change_icon("abc%")
        assert icon == "⚪"
        assert display == "abc%"

    def test_comma_in_number(self):
        icon, display = fmt_change_icon("+1,234.56%")
        assert icon == "🟢"


class TestFmtDateKr:
    def test_with_datetime(self):
        dt = datetime(2025, 3, 15, tzinfo=UTC)
        result = fmt_date_kr(dt)
        assert result == "2025년 03월 15일"

    def test_no_arg_returns_today(self):
        result = fmt_date_kr()
        assert "년" in result
        assert "월" in result
        assert "일" in result

    def test_format_structure(self):
        dt = datetime(2024, 1, 5, tzinfo=UTC)
        result = fmt_date_kr(dt)
        assert result == "2024년 01월 05일"


class TestFmtNumber:
    def test_none(self):
        assert fmt_number(None) == "N/A"

    def test_trillions(self):
        result = fmt_number(2_000_000_000_000)
        assert "T" in result
        assert "2.00" in result

    def test_billions(self):
        result = fmt_number(1_500_000_000)
        assert "B" in result
        assert "1.50" in result

    def test_millions(self):
        result = fmt_number(500_000_000)
        assert "M" in result or "B" in result

    def test_small_number(self):
        result = fmt_number(42.5)
        assert "42.50" in result

    def test_no_prefix(self):
        result = fmt_number(1_000_000_000, prefix="", decimals=1)
        assert result.startswith("1.0")
        assert "$" not in result

    def test_negative(self):
        result = fmt_number(-500_000_000)
        assert "M" in result

    def test_custom_decimals(self):
        result = fmt_number(1_500_000_000, decimals=0)
        assert "2B" in result or "1B" in result or "B" in result


class TestFmtPercent:
    def test_positive(self):
        result = fmt_percent(3.14)
        assert "🟢" in result
        assert "+3.14%" in result

    def test_negative(self):
        result = fmt_percent(-1.5)
        assert "🔴" in result
        assert "-1.50%" in result

    def test_zero(self):
        result = fmt_percent(0)
        assert "🟢" in result
        assert "+0.00%" in result

    def test_none(self):
        assert fmt_percent(None) == "N/A"


# ---------------------------------------------------------------------------
# utils.py tests
# ---------------------------------------------------------------------------

from common.utils import (  # noqa: E402
    detect_language,
    parse_date,
    remove_sponsored_text,
    request_with_retry,
    sanitize_string,
    slugify,
    truncate_sentence,
    truncate_text,
    validate_news_item,
    validate_url,
)


class TestSanitizeString:
    def test_removes_control_chars(self):
        result = sanitize_string("hello\x00world\x1f")
        assert "\x00" not in result
        assert "\x1f" not in result
        assert "hello" in result

    def test_escapes_pipe(self):
        result = sanitize_string("a|b|c")
        assert "|" not in result
        assert "&#124;" in result

    def test_truncates(self):
        long = "a" * 2000
        assert len(sanitize_string(long, max_length=100)) == 100

    def test_non_string(self):
        assert sanitize_string(123) == ""  # type: ignore[arg-type]

    def test_empty(self):
        assert sanitize_string("") == ""


class TestValidateUrl:
    def test_valid_http(self):
        assert validate_url("http://example.com/path") is True

    def test_valid_https(self):
        assert validate_url("https://example.com") is True

    def test_no_scheme(self):
        assert validate_url("example.com") is False

    def test_ftp_scheme(self):
        assert validate_url("ftp://example.com") is False

    def test_empty(self):
        assert validate_url("") is False


class TestSlugify:
    def test_lowercase(self):
        assert slugify("Hello World") == "hello-world"

    def test_special_chars_removed(self):
        result = slugify("Hello! @World#")
        assert "!" not in result
        assert "@" not in result

    def test_multiple_spaces(self):
        result = slugify("hello   world")
        assert "--" not in result

    def test_korean_preserved(self):
        result = slugify("안녕 세계")
        assert "안녕" in result

    def test_max_length(self):
        result = slugify("a" * 200, max_length=50)
        assert len(result) <= 50


class TestParseDate:
    def test_iso_format(self):
        dt = parse_date("2025-01-15T10:30:00Z")
        assert dt is not None
        assert dt.year == 2025
        assert dt.month == 1
        assert dt.day == 15

    def test_date_only(self):
        dt = parse_date("2025-03-20")
        assert dt is not None
        assert dt.year == 2025

    def test_rfc2822(self):
        dt = parse_date("Mon, 15 Jan 2025 10:30:00 +0000")
        assert dt is not None
        assert dt.year == 2025

    def test_invalid_returns_none(self):
        assert parse_date("not-a-date") is None

    def test_empty_returns_none(self):
        assert parse_date("") is None

    def test_timezone_aware(self):
        dt = parse_date("2025-01-15T10:30:00Z")
        assert dt.tzinfo is not None


class TestDetectLanguage:
    def test_korean(self):
        assert detect_language("안녕하세요 반갑습니다") == "ko"

    def test_english(self):
        assert detect_language("Bitcoin price surges to new high") == "en"

    def test_empty(self):
        assert detect_language("") == "en"

    def test_mixed_mostly_korean(self):
        assert detect_language("삼성전자 주가 급등 ETF") == "ko"

    def test_mixed_mostly_english(self):
        assert detect_language("Bitcoin 비트 rises 5%") == "en"


class TestRemoveSponsoredText:
    def test_removes_sponsored_by(self):
        result = remove_sponsored_text("Great news\nSponsored by @company")
        assert "Sponsored" not in result

    def test_removes_ad_prefix(self):
        result = remove_sponsored_text("News\nAD: Buy now")
        assert "AD:" not in result

    def test_removes_decorative_markers(self):
        result = remove_sponsored_text("▶ Breaking news ◆")
        assert "▶" not in result
        assert "◆" not in result

    def test_empty(self):
        assert remove_sponsored_text("") == ""

    def test_none(self):
        assert remove_sponsored_text(None) is None  # type: ignore[arg-type]

    def test_no_sponsored(self):
        text = "Regular news article about markets."
        assert remove_sponsored_text(text) == text


class TestTruncateText:
    def test_short_text_unchanged(self):
        text = "Short text."
        assert truncate_text(text, 100) == text

    def test_truncates_at_word_boundary(self):
        text = "word " * 100
        result = truncate_text(text, 50)
        assert len(result) <= 54  # 50 + "..."
        assert result.endswith("...")

    def test_appends_ellipsis(self):
        text = "a" * 400
        result = truncate_text(text, 300)
        assert result.endswith("...")


class TestTruncateSentence:
    def test_short_text_unchanged(self):
        text = "짧은 텍스트입니다."
        assert truncate_sentence(text, 100) == text

    def test_truncates_at_korean_sentence_boundary(self):
        text = "첫 번째 문장입니다. " * 30
        result = truncate_sentence(text, 100)
        assert len(result) <= 110
        assert "입니다" in result

    def test_truncates_at_period(self):
        text = "First sentence. Second sentence. Third sentence. " * 10
        result = truncate_sentence(text, 60)
        assert len(result) <= 65


class TestValidateNewsItem:
    def test_valid_item(self):
        item = {"title": "Bitcoin hits new all-time high", "link": "https://example.com/news"}
        result = validate_news_item(item)
        assert result is not None

    def test_short_title_rejected(self):
        item = {"title": "Short", "link": "https://example.com"}
        result = validate_news_item(item)
        assert result is None

    def test_invalid_url_rejected(self):
        item = {"title": "Bitcoin hits new all-time high today", "link": "not-a-url"}
        result = validate_news_item(item)
        assert result is None

    def test_noise_title_10k_rejected(self):
        item = {"title": "10-K Annual Report Filing", "link": "https://example.com"}
        result = validate_news_item(item)
        assert result is None

    def test_noise_title_sec_rejected(self):
        item = {"title": "EDGAR Filing Form Submitted", "link": "https://example.com"}
        result = validate_news_item(item)
        assert result is None

    def test_desc_same_as_title_cleared(self):
        title = "Bitcoin reaches record high today in markets"
        item = {"title": title, "link": "https://example.com", "description": title}
        result = validate_news_item(item)
        assert result is not None
        assert result["description"] == ""

    def test_no_link_allowed(self):
        item = {"title": "Bitcoin reaches record high today in markets"}
        result = validate_news_item(item)
        assert result is not None


class TestRequestWithRetry:
    @patch("common.utils.requests.get")
    def test_success_on_first_attempt(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        resp = request_with_retry("https://example.com/api", max_retries=2, base_delay=0.01)
        assert resp == mock_resp
        assert mock_get.call_count == 1

    @patch("common.utils.time.sleep")
    @patch("common.utils.requests.get")
    def test_retries_on_connection_error(self, mock_get, mock_sleep):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        # Fail twice, succeed on third
        mock_get.side_effect = [
            requests.exceptions.ConnectionError("refused"),
            requests.exceptions.ConnectionError("refused"),
            mock_resp,
        ]

        resp = request_with_retry("https://example.com/api", max_retries=2, base_delay=0.01)
        assert resp == mock_resp
        assert mock_get.call_count == 3
        assert mock_sleep.call_count == 2

    @patch("common.utils.time.sleep")
    @patch("common.utils.requests.get")
    def test_raises_after_all_retries_exhausted(self, mock_get, mock_sleep):
        mock_get.side_effect = requests.exceptions.Timeout("timed out")

        with pytest.raises(requests.exceptions.Timeout):
            request_with_retry("https://example.com/api", max_retries=2, base_delay=0.01)
        assert mock_get.call_count == 3

    @patch("common.utils.requests.get")
    def test_no_retry_on_404(self, mock_get):
        http_err = requests.exceptions.HTTPError("404")
        mock_response = MagicMock()
        mock_response.status_code = 404
        http_err.response = mock_response
        mock_get.side_effect = http_err

        with pytest.raises(requests.exceptions.HTTPError):
            request_with_retry("https://example.com/api", max_retries=2, base_delay=0.01)
        # Should not retry on 404
        assert mock_get.call_count == 1

    @patch("common.utils.requests.get")
    def test_no_retry_on_401(self, mock_get):
        http_err = requests.exceptions.HTTPError("401")
        mock_response = MagicMock()
        mock_response.status_code = 401
        http_err.response = mock_response
        mock_get.side_effect = http_err

        with pytest.raises(requests.exceptions.HTTPError):
            request_with_retry("https://example.com/api", max_retries=3, base_delay=0.01)
        assert mock_get.call_count == 1

    @patch("common.utils.requests.get")
    def test_passes_params_and_headers(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        request_with_retry(
            "https://example.com/api",
            params={"key": "value"},
            headers={"Authorization": "Bearer token"},
            max_retries=0,
        )
        call_kwargs = mock_get.call_args
        assert call_kwargs[1]["params"] == {"key": "value"}
        assert call_kwargs[1]["headers"] == {"Authorization": "Bearer token"}
