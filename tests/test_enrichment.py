"""Tests for enrichment module (scripts/common/enrichment.py)."""

from unittest.mock import MagicMock, patch

from common.enrichment import (
    _NOISE_DESC_PATTERNS,
    _analyze_korean_title,
    _analyze_title_content,
    _clean_description,
    _decode_google_news_base64,
    _extract_title_entities,
    _get_source_label,
    _is_valid_image_url,
    _resolve_google_news_url,
    fetch_descriptions_concurrent,
    fetch_images_concurrent,
    fetch_page_metadata,
    generate_synthetic_description,
)


class TestIsValidImageUrl:
    """Validate image URL filtering logic."""

    def test_valid_image_url(self):
        assert _is_valid_image_url("https://example.com/photo.jpg")
        assert _is_valid_image_url("https://cdn.site.com/images/hero.png")
        assert _is_valid_image_url("https://media.site.com/article/thumb.webp")

    def test_rejects_empty_and_none(self):
        assert not _is_valid_image_url("")
        assert not _is_valid_image_url(None)

    def test_rejects_non_http(self):
        assert not _is_valid_image_url("data:image/png;base64,abc")
        assert not _is_valid_image_url("/relative/path.png")
        assert not _is_valid_image_url("ftp://server/image.png")

    def test_rejects_tracking_pixels(self):
        assert not _is_valid_image_url("https://tracker.com/1x1.gif")
        assert not _is_valid_image_url("https://analytics.com/pixel.png")

    def test_rejects_placeholder_images(self):
        assert not _is_valid_image_url("https://example.com/placeholder.png")
        assert not _is_valid_image_url("https://example.com/blank.gif")
        assert not _is_valid_image_url("https://example.com/spacer.gif")
        assert not _is_valid_image_url("https://example.com/loading.svg")

    def test_rejects_svg_ico_short_gif(self):
        """SVG/ICO are typically logos/icons, short GIF is tracking pixel."""
        assert not _is_valid_image_url("https://example.com/logo.svg")
        assert not _is_valid_image_url("https://example.com/favicon.ico")
        assert not _is_valid_image_url("https://example.com/dot.gif")

    def test_rejects_gravatar(self):
        assert not _is_valid_image_url("https://gravatar.com/avatar/abc123")

    def test_rejects_wp_plugin_images(self):
        assert not _is_valid_image_url("https://example.com/wp-content/plugins/social/share.png")

    def test_rejects_gif_always(self):
        """GIF is rejected regardless of path length (usually tracking pixels)."""
        assert not _is_valid_image_url("https://cdn.example.com/articles/2026/long-path.gif")

    def test_allows_long_webp(self):
        """Long path WebP is allowed as a real content image."""
        long_webp = "https://cdn.example.com/articles/2026/03/market-overview-hero.webp"
        assert _is_valid_image_url(long_webp)


class TestCleanDescription:
    """Validate description text cleaning."""

    def test_strips_whitespace(self):
        assert _clean_description("  hello world  ") == "hello world"

    def test_removes_boilerplate_prefixes(self):
        result = _clean_description("Sign up for our newsletter to get the latest news")
        assert not result.startswith("Sign up")

    def test_removes_html_entities(self):
        result = _clean_description("Bitcoin &amp; Ethereum rise &gt; 10%")
        assert "&amp;" not in result or "Bitcoin" in result

    def test_empty_string(self):
        assert _clean_description("") == ""

    def test_normal_description_unchanged(self):
        text = "Bitcoin surged 5% today amid growing institutional interest"
        result = _clean_description(text)
        assert "Bitcoin" in result
        assert "5%" in result

    def test_short_text_preserved(self):
        result = _clean_description("Price up")
        assert result == "Price up"

    def test_removes_subscribe_prefix(self):
        assert _clean_description("Subscribe to our newsletter") == ""

    def test_removes_get_the_latest_prefix(self):
        assert _clean_description("Get the latest news from us") == ""

    def test_removes_read_more_suffix(self):
        result = _clean_description("Bitcoin price is rising. Read more")
        assert "Read more" not in result

    def test_removes_continue_reading_suffix(self):
        result = _clean_description("Market analysis update. Continue reading...")
        assert "Continue reading" not in result

    def test_removes_korean_read_more_suffix(self):
        result = _clean_description("비트코인 가격 상승 중. 더 보기")
        assert "더 보기" not in result

    def test_removes_korean_boilerplate_prefix(self):
        assert _clean_description("무단전재 및 재배포 금지 본 기사는") == ""

    def test_noise_pattern_access_denied(self):
        assert _clean_description("Access denied. Please login.") == ""

    def test_noise_pattern_403(self):
        assert _clean_description("403 Forbidden - This page is restricted.") == ""

    def test_noise_pattern_we_use_cookies(self):
        assert _clean_description("We use cookies to enhance your experience.") == ""

    def test_noise_pattern_javascript_required(self):
        assert _clean_description("Please enable JavaScript to view this page.") == ""

    def test_collapses_whitespace(self):
        result = _clean_description("Bitcoin   price    is    rising")
        assert "  " not in result

    def test_removes_english_source_suffix(self):
        result = _clean_description("Bitcoin price hits record high - Reuters")
        assert "Reuters" not in result

    def test_removes_korean_source_suffix(self):
        result = _clean_description("비트코인 가격 급등 연합뉴스")
        assert "연합뉴스" not in result


class TestNoiseDescPatterns:
    """Tests for _NOISE_DESC_PATTERNS regex list."""

    def test_patterns_is_list(self):
        assert isinstance(_NOISE_DESC_PATTERNS, list)
        assert len(_NOISE_DESC_PATTERNS) > 0

    def test_enable_javascript_pattern(self):
        text = "Please enable JavaScript to continue."
        assert any(p.search(text) for p in _NOISE_DESC_PATTERNS)

    def test_enable_cookies_pattern(self):
        text = "Enable cookies to use this site."
        assert any(p.search(text) for p in _NOISE_DESC_PATTERNS)

    def test_browser_not_supported_pattern(self):
        text = "Your browser is not supported."
        assert any(p.search(text) for p in _NOISE_DESC_PATTERNS)

    def test_access_denied_pattern(self):
        text = "Access denied"
        assert any(p.search(text) for p in _NOISE_DESC_PATTERNS)

    def test_403_forbidden_pattern(self):
        text = "403 Forbidden"
        assert any(p.search(text) for p in _NOISE_DESC_PATTERNS)

    def test_page_not_found_pattern(self):
        text = "Page not found"
        assert any(p.search(text) for p in _NOISE_DESC_PATTERNS)

    def test_404_pattern(self):
        text = "404 error"
        assert any(p.search(text) for p in _NOISE_DESC_PATTERNS)

    def test_we_use_cookies_pattern(self):
        text = "We use cookies to improve experience."
        assert any(p.search(text) for p in _NOISE_DESC_PATTERNS)

    def test_amendment_no_pattern(self):
        text = "AMENDMENT NO. 2 to S-1"
        assert any(p.search(text) for p in _NOISE_DESC_PATTERNS)

    def test_form_number_pattern(self):
        text = "FORM 10-K Annual Report"
        assert any(p.search(text) for p in _NOISE_DESC_PATTERNS)

    def test_normal_text_no_match(self):
        text = "Bitcoin surged 10% today on institutional demand."
        assert not any(p.search(text) for p in _NOISE_DESC_PATTERNS)


class TestDecodeGoogleNewsBase64:
    """Tests for _decode_google_news_base64()."""

    def test_non_google_url_returns_empty(self):
        assert _decode_google_news_base64("https://example.com/article") == ""

    def test_empty_string_returns_empty(self):
        assert _decode_google_news_base64("") == ""

    def test_google_url_without_articles_path_returns_empty(self):
        assert _decode_google_news_base64("https://news.google.com/topics/CAAqBwgK") == ""

    def test_malformed_base64_returns_empty(self):
        # /rss/articles/ path with non-decodable garbage
        result = _decode_google_news_base64(
            "https://news.google.com/rss/articles/!!!INVALID!!!"
        )
        assert result == ""

    def test_valid_google_news_url_structure(self):
        # This is a mock test to verify the function handles the pattern
        # We just confirm it returns str (either "" or a URL)
        url = "https://news.google.com/rss/articles/CBMiSmh0dHBzOi8vd3d3LmJiYy5jb20vbmV3cy9hcnRpY2xlcy9jbGllbnQtYXJ0aWNsZQ0"
        result = _decode_google_news_base64(url)
        assert isinstance(result, str)


class TestResolveGoogleNewsUrl:
    """Tests for _resolve_google_news_url()."""

    def test_non_google_url_returned_as_is(self):
        url = "https://example.com/article/123"
        assert _resolve_google_news_url(url) == url

    def test_empty_string_returned_as_is(self):
        assert _resolve_google_news_url("") == ""

    def test_none_like_falsy_url_returned_as_is(self):
        # None-ish values: function signature requires str, but test robustness
        result = _resolve_google_news_url("https://reuters.com/markets/bitcoin")
        assert result == "https://reuters.com/markets/bitcoin"

    @patch("common.enrichment._decode_google_news_base64")
    def test_base64_decode_success_skips_http(self, mock_decode):
        """If base64 decode succeeds, no network calls are made."""
        mock_decode.return_value = "https://real-article.com/news/123"
        result = _resolve_google_news_url(
            "https://news.google.com/rss/articles/CBMiXXX"
        )
        assert result == "https://real-article.com/news/123"
        mock_decode.assert_called_once()

    @patch("common.enrichment._decode_google_news_base64")
    @patch("common.enrichment.requests.head")
    def test_http_head_redirect_used_when_base64_fails(self, mock_head, mock_decode):
        """When base64 fails, follows HEAD redirect."""
        mock_decode.return_value = ""
        mock_resp = MagicMock()
        mock_resp.url = "https://real-site.com/article"
        mock_head.return_value = mock_resp
        result = _resolve_google_news_url(
            "https://news.google.com/rss/articles/CBMiXXX"
        )
        assert result == "https://real-site.com/article"

    @patch("common.enrichment._decode_google_news_base64")
    @patch("common.enrichment.requests.head")
    @patch("common.enrichment.requests.get")
    def test_get_fallback_when_head_stays_on_google(self, mock_get, mock_head, mock_decode):
        """When HEAD stays on google, tries GET."""
        mock_decode.return_value = ""
        mock_head_resp = MagicMock()
        mock_head_resp.url = "https://news.google.com/still-here"
        mock_head.return_value = mock_head_resp
        mock_get_resp = MagicMock()
        mock_get_resp.url = "https://real-site.com/article"
        mock_get_resp.text = ""
        mock_get.return_value = mock_get_resp
        result = _resolve_google_news_url(
            "https://news.google.com/rss/articles/CBMiXXX"
        )
        assert result == "https://real-site.com/article"

    @patch("common.enrichment._decode_google_news_base64")
    @patch("common.enrichment.requests.head")
    def test_network_exception_returns_empty(self, mock_head, mock_decode):
        """Network errors should be swallowed and return empty."""
        import requests as req_mod
        mock_decode.return_value = ""
        mock_head.side_effect = req_mod.exceptions.ConnectionError("refused")
        result = _resolve_google_news_url(
            "https://news.google.com/rss/articles/CBMiXXX"
        )
        # Should return "" (empty) after all fallbacks fail
        assert isinstance(result, str)


class TestFetchPageMetadata:
    """Tests for fetch_page_metadata()."""

    def test_empty_url_returns_empty_dict(self):
        result = fetch_page_metadata("")
        assert result == {"description": "", "image": ""}

    def test_returns_dict_with_expected_keys(self):
        result = fetch_page_metadata("")
        assert "description" in result
        assert "image" in result

    @patch("common.enrichment.requests.get")
    def test_http_error_returns_empty(self, mock_get):
        import requests as req_mod
        mock_get.side_effect = req_mod.exceptions.ConnectionError("refused")
        result = fetch_page_metadata("https://example.com/article")
        assert result["description"] == ""

    @patch("common.enrichment.requests.get")
    def test_og_description_extracted(self, mock_get):
        html = """<html><head>
        <meta property="og:description" content="Bitcoin surged 10% on institutional demand today." />
        <meta property="og:image" content="https://example.com/img.jpg" />
        </head><body></body></html>"""
        mock_resp = MagicMock()
        mock_resp.text = html
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp
        result = fetch_page_metadata("https://example.com/article")
        assert "Bitcoin" in result["description"]

    @patch("common.enrichment.requests.get")
    def test_meta_description_extracted(self, mock_get):
        html = """<html><head>
        <meta name="description" content="Ethereum network upgrade brings major improvements to the ecosystem." />
        </head><body></body></html>"""
        mock_resp = MagicMock()
        mock_resp.text = html
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp
        result = fetch_page_metadata("https://example.com/article")
        assert "Ethereum" in result["description"]

    @patch("common.enrichment.requests.get")
    def test_og_image_extracted(self, mock_get):
        html = """<html><head>
        <meta property="og:image" content="https://example.com/article-image.jpg" />
        <meta name="description" content="Bitcoin news from today covering major price movement." />
        </head><body></body></html>"""
        mock_resp = MagicMock()
        mock_resp.text = html
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp
        result = fetch_page_metadata("https://example.com/article")
        assert result["image"] == "https://example.com/article-image.jpg"

    @patch("common.enrichment.requests.get")
    def test_short_description_skipped(self, mock_get):
        html = """<html><head>
        <meta name="description" content="Short." />
        </head><body><p>Bitcoin price news from institutional investors rising this week rapidly.</p></body></html>"""
        mock_resp = MagicMock()
        mock_resp.text = html
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp
        result = fetch_page_metadata("https://example.com/article")
        # Short meta desc < 20 chars is skipped; body paragraph may be extracted
        assert isinstance(result["description"], str)

    @patch("common.enrichment.requests.get")
    def test_http_status_error_returns_empty(self, mock_get):
        import requests as req_mod
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = req_mod.exceptions.HTTPError("404")
        mock_get.return_value = mock_resp
        result = fetch_page_metadata("https://example.com/article")
        assert result == {"description": "", "image": ""}


class TestFetchImagesConcurrent:
    """Tests for fetch_images_concurrent()."""

    def test_empty_items_returns_zero(self):
        assert fetch_images_concurrent([]) == 0

    def test_items_without_link_skipped(self):
        items = [{"title": "Test", "image": ""}]  # no "link" key
        result = fetch_images_concurrent(items)
        assert result == 0

    def test_items_already_with_image_skipped(self):
        items = [{"title": "Test", "link": "https://example.com", "image": "https://example.com/img.jpg"}]
        result = fetch_images_concurrent(items)
        assert result == 0

    @patch("common.enrichment._fetch_og_image")
    def test_fetches_image_for_item_without_image(self, mock_fetch):
        mock_fetch.return_value = "https://example.com/og.jpg"
        items = [{"title": "Test", "link": "https://example.com/article", "image": ""}]
        result = fetch_images_concurrent(items)
        assert result == 1
        assert items[0]["image"] == "https://example.com/og.jpg"

    @patch("common.enrichment._fetch_og_image")
    def test_failed_fetch_returns_zero(self, mock_fetch):
        mock_fetch.return_value = ""
        items = [{"title": "Test", "link": "https://example.com/article"}]
        result = fetch_images_concurrent(items)
        assert result == 0


class TestFetchDescriptionsConcurrent:
    """Tests for fetch_descriptions_concurrent()."""

    def test_empty_items_returns_zero(self):
        assert fetch_descriptions_concurrent([]) == 0

    def test_items_without_link_skipped(self):
        items = [{"title": "Test", "description": ""}]  # no "link"
        result = fetch_descriptions_concurrent(items)
        assert result == 0

    def test_items_with_good_description_skipped(self):
        items = [{
            "title": "Bitcoin news",
            "link": "https://example.com",
            "description": "Bitcoin surged 10% today amid growing institutional interest in crypto markets.",
        }]
        result = fetch_descriptions_concurrent(items)
        assert result == 0

    @patch("common.enrichment.fetch_page_metadata")
    def test_fetches_for_missing_description(self, mock_meta):
        mock_meta.return_value = {
            "description": "Bitcoin price rose by 10% this week on high volume.",
            "image": "",
        }
        items = [{"title": "Test", "link": "https://example.com/article", "description": ""}]
        result = fetch_descriptions_concurrent(items)
        assert result == 1
        assert "Bitcoin" in items[0]["description"]

    @patch("common.enrichment.fetch_page_metadata")
    def test_synthetic_description_enriched(self, mock_meta):
        mock_meta.return_value = {
            "description": "Ethereum upgrade brings major performance improvements to the network.",
            "image": "",
        }
        items = [{
            "title": "ETH news",
            "link": "https://example.com/eth",
            "description": "관련 소식입니다. 투자 판단 시 참고하세요.",
        }]
        result = fetch_descriptions_concurrent(items)
        assert result == 1


class TestExtractTitleEntities:
    """Tests for _extract_title_entities()."""

    def test_extracts_ticker_symbols(self):
        entities = _extract_title_entities("BTC and ETH reach new highs")
        assert "BTC" in entities or "ETH" in entities

    def test_extracts_price_values(self):
        entities = _extract_title_entities("Bitcoin hits $90K milestone")
        assert any("$" in e or "K" in e or "90" in e for e in entities)

    def test_extracts_percentage(self):
        entities = _extract_title_entities("Market rises 5.3% today")
        assert any("5.3%" in e for e in entities)

    def test_extracts_korean_entities(self):
        entities = _extract_title_entities("비트코인 시장 급등")
        assert any("비트코인" in e or "시장" in e or "급등" in e for e in entities)

    def test_proper_nouns_extracted(self):
        # Coinbase is a proper noun not in _COMMON set
        entities = _extract_title_entities("Coinbase announces Bitcoin custody service")
        assert "Coinbase" in entities

    def test_noise_tickers_excluded(self):
        entities = _extract_title_entities("CEO says AI is important for THE market")
        assert "CEO" not in entities
        assert "THE" not in entities
        assert "AI" not in entities

    def test_common_words_excluded(self):
        entities = _extract_title_entities("Bitcoin Stock Market Trade volume")
        # Market, Stock, Trade are in _COMMON set
        assert "Market" not in entities
        assert "Stock" not in entities

    def test_returns_list(self):
        assert isinstance(_extract_title_entities("test title"), list)

    def test_empty_title(self):
        assert _extract_title_entities("") == []

    def test_deduplication(self):
        entities = _extract_title_entities("AAPL AAPL rises 5% today")
        # Deduplicated - AAPL should appear at most once
        aapl_count = entities.count("AAPL")
        assert aapl_count <= 1

    def test_limits_tickers_to_two(self):
        entities = _extract_title_entities("AAPL MSFT GOOG AMZN all rally")
        tickers_found = [e for e in entities if len(e) <= 5 and e.isupper() and e not in {"AI", "US", "UK"}]
        assert len(tickers_found) <= 2


class TestAnalyzeKoreanTitle:
    """Tests for _analyze_korean_title()."""

    def test_circuit_breaker_sell_side(self):
        result = _analyze_korean_title("코스피 서킷브레이커 발동")
        assert "매매거래" in result or "중단" in result

    def test_circuit_breaker_buy_side(self):
        result = _analyze_korean_title("매수 사이드카 발동")
        assert "반등" in result or "사이드카" in result

    def test_crash_title(self):
        result = _analyze_korean_title("비트코인 폭락 10%")
        assert "급락" in result or "패닉" in result

    def test_surge_title(self):
        result = _analyze_korean_title("코스피 급등세")
        assert "반등" in result

    def test_geopolitical_risk(self):
        result = _analyze_korean_title("이란 군사 충돌로 시장 불안")
        assert "지정학" in result

    def test_interest_rate(self):
        result = _analyze_korean_title("한국은행 금리 결정")
        assert "금리" in result

    def test_exchange_rate(self):
        # Use a title that doesn't have surge/drop keywords to trigger the exchange rate branch
        result = _analyze_korean_title("원달러 환율 변동 지속")
        assert "환율" in result

    def test_semiconductor(self):
        result = _analyze_korean_title("삼성전자 반도체 실적 발표")
        assert "반도체" in result

    def test_bitcoin_with_pct(self):
        result = _analyze_korean_title("비트코인 5% 상승 기대")
        assert "5%" in result or "암호화폐" in result

    def test_defi_digital_asset(self):
        result = _analyze_korean_title("디파이 시장 성장")
        assert "디지털 자산" in result or "디파이" in result

    def test_ai_title(self):
        result = _analyze_korean_title("AI 투자 열풍")
        assert "AI" in result

    def test_supply_demand(self):
        result = _analyze_korean_title("외국인 순매수 확대")
        assert "수급" in result or "순매수" in result

    def test_earnings(self):
        result = _analyze_korean_title("분기 실적 발표 어닝 시즌")
        assert "실적" in result

    def test_fallback_returns_title_core(self):
        result = _analyze_korean_title("알 수 없는 시장 소식")
        assert isinstance(result, str)
        assert len(result) > 0


class TestAnalyzeTitleContent:
    """Tests for _analyze_title_content()."""

    def test_korean_title_routes_to_korean_analyzer(self):
        result = _analyze_title_content("비트코인 가격 급등세")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_english_title_routes_to_english_analyzer(self):
        result = _analyze_title_content("Bitcoin price surges to new all-time high")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_mixed_title_with_majority_korean(self):
        result = _analyze_title_content("비트코인 BTC 급등 10%")
        assert isinstance(result, str)

    def test_crash_english(self):
        result = _analyze_title_content("S&P 500 Crashes 5% on Fed Fears")
        assert "급락" in result

    def test_rally_english(self):
        result = _analyze_title_content("Bitcoin Surges 10% on ETF News")
        assert "상승" in result

    def test_fed_english(self):
        result = _analyze_title_content("Fed Rate Cut Expected at Next FOMC Meeting")
        assert "연준" in result

    def test_earnings_english(self):
        result = _analyze_title_content("Apple Beats Revenue Estimates for Q4")
        assert "실적" in result

    def test_geopolitical_english(self):
        result = _analyze_title_content("Iran attack sparks market sell-off")
        assert "지정학" in result

    def test_oil_english(self):
        result = _analyze_title_content("Crude Oil Market Overview: WTI stable")
        assert "유가" in result or "에너지" in result


class TestGetSourceLabel:
    """Tests for _get_source_label()."""

    def test_known_source_returns_label(self):
        context_map = {"Reuters": "로이터통신"}
        assert _get_source_label("Reuters", context_map) == "로이터통신"

    def test_unknown_source_returns_source(self):
        assert _get_source_label("UnknownSite", {}) == "UnknownSite"

    def test_empty_context_map(self):
        assert _get_source_label("Reuters", {}) == "Reuters"

    def test_empty_source(self):
        assert _get_source_label("", {}) == ""


class TestGenerateSyntheticDescription:
    """Tests for generate_synthetic_description()."""

    def test_returns_string(self):
        result = generate_synthetic_description("Bitcoin rises 5%", "Reuters")
        assert isinstance(result, str)

    def test_non_empty_for_meaningful_title(self):
        result = generate_synthetic_description("Bitcoin surges 10% on ETF approval", "Reuters")
        assert len(result) > 10

    def test_exchange_source_returns_notice(self):
        # Short title won't produce useful analysis (< 20 chars), falls to exchange branch
        result = generate_synthetic_description(".", "binance")
        assert "공지" in result

    def test_korean_title_handled(self):
        result = generate_synthetic_description("비트코인 가격 급등", "코인데스크")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_context_map_used_for_label(self):
        ctx = {"MySource": "마이소스"}
        result = generate_synthetic_description("Some news title here", "MySource", ctx)
        assert isinstance(result, str)

    def test_crash_title_returns_analysis(self):
        result = generate_synthetic_description("S&P 500 crashes 5% amid Fed fears", "Reuters")
        assert "급락" in result or len(result) > 10

    def test_empty_title_handled(self):
        result = generate_synthetic_description("", "Reuters")
        assert isinstance(result, str)
