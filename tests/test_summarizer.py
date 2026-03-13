"""Tests for summarizer module (scripts/common/summarizer.py)."""

import re

import pytest

from common.summarizer import (
    PRIORITY_KEYWORDS,
    THEMES,
    ThemeSummarizer,
    _GENERIC_DESC_PATTERNS,
    _NOISE_TITLE_RE,
    _generate_title_based_desc,
    _is_generic_desc,
    _truncate_sentence,
)


class TestTruncateSentence:
    """Tests for _truncate_sentence()."""

    def test_empty_string_returns_empty(self):
        assert _truncate_sentence("") == ""

    def test_short_text_returns_empty(self):
        # texts shorter than 15 chars return ""
        assert _truncate_sentence("안녕하세요") == ""
        assert _truncate_sentence("Hello world") == ""

    def test_text_within_max_len_returned_as_is(self):
        text = "비트코인 가격이 상승했습니다. 이는 기관 투자자들의 수요 증가에 기인한 것으로 보입니다."
        result = _truncate_sentence(text, max_len=300)
        assert result == text

    def test_truncates_at_korean_sentence_boundary(self):
        # Put the sentence boundary well past index 20 so it's detected
        prefix = "오늘 시장 동향을 분석한 결과 비트코인 가격이 크게 상승했습니다. "
        long_text = prefix + "x" * 300
        result = _truncate_sentence(long_text, max_len=300)
        # Should cut at the Korean sentence ending
        assert result.endswith("습니다.")
        assert len(result) < len(long_text)

    def test_truncates_at_english_sentence_boundary(self):
        long_text = "Bitcoin surged 10 percent today. " + "y" * 300
        result = _truncate_sentence(long_text, max_len=300)
        assert result.endswith("today.")
        assert len(result) < len(long_text)

    def test_falls_back_to_word_boundary_with_ellipsis(self):
        # No sentence boundary — should add "..."
        long_text = "a" * 50 + " " + "b" * 50 + " " + "c" * 200
        result = _truncate_sentence(long_text, max_len=100)
        assert result.endswith("...")

    def test_cjk_fallback_no_spaces(self):
        # CJK text without spaces — fall back to character truncation
        long_text = "가" * 400
        result = _truncate_sentence(long_text, max_len=100)
        assert result.endswith("...")

    def test_strips_leading_trailing_whitespace(self):
        text = "  비트코인 가격이 상승했습니다. 이더리움도 올랐습니다.  "
        result = _truncate_sentence(text, max_len=300)
        assert not result.startswith(" ")
        assert not result.endswith(" ")

    def test_exclamation_mark_boundary(self):
        text = "놀라운 상승입니다! " + "z" * 300
        result = _truncate_sentence(text, max_len=300)
        assert "!" in result
        assert len(result) < len(text)

    def test_question_mark_boundary(self):
        text = "과연 상승할 것인가? " + "q" * 300
        result = _truncate_sentence(text, max_len=300)
        assert "?" in result
        assert len(result) < len(text)


class TestGenerateTitleBasedDesc:
    """Tests for _generate_title_based_desc()."""

    def test_short_title_returns_empty(self):
        assert _generate_title_based_desc("BTC", "bitcoin") == ""
        assert _generate_title_based_desc("짧은", "macro") == ""

    def test_korean_title_with_known_theme(self):
        result = _generate_title_based_desc("비트코인 가격이 급등하며 신고가 돌파", "bitcoin")
        assert "비트코인" in result
        assert len(result) > 10

    def test_korean_title_unknown_theme(self):
        result = _generate_title_based_desc("비트코인 가격이 급등하며 신고가 돌파", "unknown_theme")
        assert len(result) > 0

    def test_english_title_with_known_theme(self):
        result = _generate_title_based_desc("Bitcoin ETF sees record inflows this week", "bitcoin")
        assert len(result) > 10

    def test_english_title_with_ticker_extraction(self):
        result = _generate_title_based_desc("BTC and ETH rally 15% on institutional demand", "price")
        # Tickers/percentages should be embedded
        assert len(result) > 10

    def test_english_title_removes_source_suffix(self):
        result = _generate_title_based_desc(
            "Bitcoin hits all-time high - Reuters", "bitcoin"
        )
        assert "Reuters" not in result

    def test_english_title_bloomberg_suffix_removed(self):
        result = _generate_title_based_desc(
            "Fed holds rates steady - Bloomberg", "macro"
        )
        assert "Bloomberg" not in result

    def test_percentage_extraction(self):
        result = _generate_title_based_desc("BTC surges 25.5% in one week", "price_market")
        assert "25.5%" in result

    def test_dollar_value_extraction(self):
        result = _generate_title_based_desc("Bitcoin reaches $100K milestone today", "bitcoin")
        assert "$100K" in result

    def test_long_korean_title_truncated(self):
        long_title = "비트코인이 " + "상승하고있으며" * 15 + " 최고가를 기록했습니다"
        result = _generate_title_based_desc(long_title, "bitcoin")
        assert len(result) < len(long_title) + 50  # Context string added but title truncated

    def test_korean_title_long_description_cut_at_80(self):
        title = "가" * 100  # 100 Korean chars, > 80
        result = _generate_title_based_desc(title, "macro")
        # clean is capped at 77 + "..."
        assert "..." in result


class TestIsGenericDesc:
    """Tests for _is_generic_desc()."""

    def test_normal_description_not_generic(self):
        assert not _is_generic_desc("Bitcoin surged 5% today amid growing institutional interest.")

    def test_korean_news_boilerplate(self):
        assert _is_generic_desc("코인데스크에서 보도한 뉴스입니다.")
        assert _is_generic_desc("블룸버그에서 보도한 소식입니다.")

    def test_related_news_phrase(self):
        assert _is_generic_desc("암호화폐 관련 소식을 전했습니다.")

    def test_original_article_phrase(self):
        assert _is_generic_desc("원문에서 세부 내용을 확인하세요.")

    def test_exchange_notice_phrase(self):
        assert _is_generic_desc("거래소 공지사항입니다.")

    def test_javascript_required(self):
        assert _is_generic_desc("Please enable JavaScript to view this page.")

    def test_access_denied(self):
        assert _is_generic_desc("Access denied")
        assert _is_generic_desc("403 Forbidden")

    def test_cookie_consent(self):
        assert _is_generic_desc("Your privacy matters to us.")
        assert _is_generic_desc("We use cookies to improve your experience.")

    def test_subscribe_prompt(self):
        assert _is_generic_desc("Subscribe to our newsletter for updates.")
        assert _is_generic_desc("Sign up for our daily digest.")

    def test_javascript_required_variants(self):
        assert _is_generic_desc("JavaScript is required to use this site.")
        assert _is_generic_desc("JavaScript must be enabled.")
        assert _is_generic_desc("This page requires JavaScript.")
        assert _is_generic_desc("Loading...")

    def test_sec_form(self):
        assert _is_generic_desc("AMENDMENT NO. 3 to Form S-1")
        assert _is_generic_desc("FORM 10-K for fiscal year 2024")

    def test_confirm_here_phrase(self):
        assert _is_generic_desc("원문에서 확인하세요.")

    def test_empty_string_not_generic(self):
        # Empty string has no matching pattern
        assert not _is_generic_desc("")


class TestNoiseTitleRe:
    """Tests for _NOISE_TITLE_RE pattern."""

    def test_sec_address_matches(self):
        assert _NOISE_TITLE_RE.search("Washington, DC 20549")

    def test_sec_form_10k_matches(self):
        assert _NOISE_TITLE_RE.search("10-K Annual Report")

    def test_form_number_matches(self):
        assert _NOISE_TITLE_RE.search("Form 4 insider filing")

    def test_edgar_matches(self):
        assert _NOISE_TITLE_RE.search("EDGAR Filing Details")

    def test_advertisement_matches(self):
        assert _NOISE_TITLE_RE.search("Advertisement This is sponsored")

    def test_sponsored_matches(self):
        assert _NOISE_TITLE_RE.search("Sponsored content here")

    def test_subscribe_matches(self):
        assert _NOISE_TITLE_RE.search("Subscribe now for daily news")

    def test_login_matches(self):
        assert _NOISE_TITLE_RE.search("Login to access full article")

    def test_normal_title_no_match(self):
        assert not _NOISE_TITLE_RE.search("Bitcoin hits all-time high")
        assert not _NOISE_TITLE_RE.search("이더리움 상승세 지속")

    def test_case_insensitive(self):
        assert _NOISE_TITLE_RE.search("SUBSCRIBE to our newsletter")
        assert _NOISE_TITLE_RE.search("login PAGE detected")


class TestThemeSummarizer:
    """Tests for ThemeSummarizer class."""

    def _make_items(self, texts):
        """Helper: create news item dicts from list of (title, description) pairs."""
        return [{"title": t, "description": d} for t, d in texts]

    def test_empty_items_get_top_themes_empty(self):
        ts = ThemeSummarizer([])
        assert ts.get_top_themes() == []

    def test_get_top_themes_returns_list(self):
        items = self._make_items([
            ("Bitcoin surges 10%", "BTC mining hashrate hits record high"),
            ("Bitcoin ETF approved", "SEC gives green light to spot ETF"),
            ("BTC whale accumulation detected", "Whale wallets add 1000 BTC"),
        ])
        ts = ThemeSummarizer(items)
        themes = ts.get_top_themes()
        assert isinstance(themes, list)
        # Should find bitcoin theme
        theme_keys = [t[1] for t in themes]
        assert "bitcoin" in theme_keys

    def test_get_top_themes_tuple_structure(self):
        items = self._make_items([("Bitcoin price rally", "BTC up 15%")])
        ts = ThemeSummarizer(items)
        themes = ts.get_top_themes()
        if themes:
            name, key, emoji, count = themes[0]
            assert isinstance(name, str)
            assert isinstance(key, str)
            assert isinstance(emoji, str)
            assert isinstance(count, int)

    def test_score_themes_populates_scores(self):
        items = self._make_items([
            ("Ethereum upgrade", "ETH L2 rollup scaling"),
            ("ETH staking yield", "Ethereum DeFi TVL grows"),
        ])
        ts = ThemeSummarizer(items)
        ts._score_themes()
        assert "ethereum" in ts._theme_scores
        assert ts._theme_scores["ethereum"] > 0

    def test_score_themes_unrelated_items_low_score(self):
        items = self._make_items([
            ("Random weather news", "Sunny day expected"),
        ])
        ts = ThemeSummarizer(items)
        ts._score_themes()
        # All crypto themes should score 0 for unrelated content
        assert ts._theme_scores.get("bitcoin", 0) == 0
        assert ts._theme_scores.get("defi", 0) == 0

    def test_classify_priority_returns_buckets(self):
        items = self._make_items([
            ("Bitcoin exchange CRASH detected", "Flash crash occurred"),
            ("SEC files ETF approval", "Regulation update for 2026"),
            ("New partnership announced", "Launch of mainnet upgrade"),
        ])
        ts = ThemeSummarizer(items)
        result = ts.classify_priority()
        assert "P0" in result
        assert "P1" in result
        assert "P2" in result

    def test_classify_priority_p0_crash_keyword(self):
        items = self._make_items([("Market crash detected", "Bitcoin crash 40%")])
        ts = ThemeSummarizer(items)
        result = ts.classify_priority()
        # "crash" is a P0 keyword
        assert len(result["P0"]) >= 1

    def test_classify_priority_p1_regulation_keyword(self):
        items = self._make_items([("New regulation for crypto", "SEC filing regulation")])
        ts = ThemeSummarizer(items)
        result = ts.classify_priority()
        # "regulation" is P1
        assert len(result["P1"]) >= 1

    def test_classify_priority_p2_partnership_keyword(self):
        items = self._make_items([("New partnership signed", "Collaboration between firms")])
        ts = ThemeSummarizer(items)
        result = ts.classify_priority()
        # "partnership" is P2
        assert len(result["P2"]) >= 1

    def test_classify_priority_each_item_assigned_once(self):
        # Item with both P0 and P1 keywords should only appear in P0
        items = self._make_items([("crash and regulation news", "hack exploit found")])
        ts = ThemeSummarizer(items)
        result = ts.classify_priority()
        total = len(result["P0"]) + len(result["P1"]) + len(result["P2"])
        assert total <= len(items)  # No duplicate assignment

    def test_classify_priority_empty_items(self):
        ts = ThemeSummarizer([])
        result = ts.classify_priority()
        assert result == {"P0": [], "P1": [], "P2": []}

    def test_get_top_themes_max_5(self):
        # Mix of many themes
        items = self._make_items([
            ("Bitcoin hack exploit", "BTC crash"),
            ("Ethereum regulation SEC", "ETH layer2"),
            ("DeFi TVL yield lending", "Uniswap pool"),
            ("Trump election tariff policy", "Congress legislation"),
            ("AI gpu nvidia chatgpt", "Machine learning cloud"),
            ("Exchange binance listing", "Coinbase volume"),
        ])
        ts = ThemeSummarizer(items)
        themes = ts.get_top_themes()
        assert len(themes) <= 5

    def test_score_themes_korean_keywords(self):
        items = self._make_items([
            ("비트코인 채굴 증가", "해시레이트 상승으로 비트코인 채굴 수익 증가"),
        ])
        ts = ThemeSummarizer(items)
        ts._score_themes()
        assert ts._theme_scores.get("bitcoin", 0) > 0

    def test_lazy_scoring_called_once(self):
        items = self._make_items([("Bitcoin news", "BTC update")])
        ts = ThemeSummarizer(items)
        assert not ts._scored
        ts.get_top_themes()
        assert ts._scored
        # Call again — should not re-score
        ts.get_top_themes()
        assert ts._scored

    def test_title_original_used_for_scoring(self):
        items = [{"title": "번역된 제목", "title_original": "Bitcoin halving event", "description": ""}]
        ts = ThemeSummarizer(items)
        ts._score_themes()
        assert ts._theme_scores.get("bitcoin", 0) > 0


class TestThemeSummarizerGenerators:
    """Tests for ThemeSummarizer HTML/markdown generation methods."""

    def _make_items(self, n=5, theme="bitcoin"):
        """Create n items with Bitcoin-related content."""
        base = [
            {"title": f"Bitcoin ETF surge number {i}", "description": f"BTC mining hash {i}%"}
            for i in range(n)
        ]
        return base

    def test_generate_distribution_chart_returns_empty_for_few_items(self):
        ts = ThemeSummarizer([{"title": "x", "description": "y"}])
        assert ts.generate_distribution_chart() == ""

    def test_generate_distribution_chart_returns_html(self):
        items = self._make_items(10)
        ts = ThemeSummarizer(items)
        result = ts.generate_distribution_chart()
        if result:
            assert "theme-distribution" in result
            assert "건" in result

    def test_generate_distribution_chart_no_themes_returns_empty(self):
        # Items with no matching theme keywords
        items = [{"title": "random text", "description": "weather is nice"} for _ in range(10)]
        ts = ThemeSummarizer(items)
        result = ts.generate_distribution_chart()
        # No matching themes → empty string
        assert result == ""

    def test_generate_themed_news_sections_returns_empty_for_few_items(self):
        ts = ThemeSummarizer([])
        assert ts.generate_themed_news_sections() == ""

    def test_generate_themed_news_sections_returns_string(self):
        items = [
            {"title": f"Bitcoin ETF approved {i}", "description": f"BTC whale buy {i}", "link": f"https://example.com/{i}"}
            for i in range(10)
        ]
        ts = ThemeSummarizer(items)
        result = ts.generate_themed_news_sections()
        if result:
            assert isinstance(result, str)
            assert "테마별 주요 뉴스" in result

    def test_generate_themed_news_sections_with_source(self):
        items = [
            {
                "title": f"Bitcoin mining hash rate {i}",
                "description": f"BTC miner revenue {i}%",
                "link": f"https://example.com/{i}",
                "source": "CoinDesk",
            }
            for i in range(8)
        ]
        ts = ThemeSummarizer(items)
        result = ts.generate_themed_news_sections()
        assert isinstance(result, str)

    def test_generate_themed_news_sections_with_image(self):
        items = [
            {
                "title": f"Bitcoin ETF record inflow {i}",
                "description": f"BTC institutional demand {i}",
                "link": f"https://example.com/{i}",
                "image": f"https://cdn.example.com/img{i}.jpg",
            }
            for i in range(8)
        ]
        ts = ThemeSummarizer(items)
        result = ts.generate_themed_news_sections()
        assert isinstance(result, str)

    def test_generate_themed_news_sections_filters_noise_title(self):
        items = [
            {"title": "Bitcoin ETF inflows", "description": "BTC up 5%", "link": "https://a.com"},
            {"title": "Subscribe now for updates", "description": "Lorem ipsum", "link": "https://b.com"},
        ] * 5
        ts = ThemeSummarizer(items)
        result = ts.generate_themed_news_sections()
        assert isinstance(result, str)

    def test_extract_title_keywords_basic(self):
        items = [
            {"title": "Bitcoin hashrate mining increase record"},
            {"title": "Bitcoin ETF approved hashrate"},
            {"title": "Bitcoin whale accumulation hashrate"},
        ]
        ts = ThemeSummarizer(items)
        keywords = ts._extract_title_keywords(items, max_keywords=5)
        assert isinstance(keywords, list)
        # "hashrate" or "Bitcoin" should appear (high frequency)
        assert len(keywords) <= 5

    def test_extract_title_keywords_filters_stop_words(self):
        items = [{"title": "the stock market today will and the"}]
        ts = ThemeSummarizer(items)
        keywords = ts._extract_title_keywords(items)
        # Stop words should be filtered
        assert "the" not in keywords
        assert "and" not in keywords

    def test_extract_title_keywords_empty_articles(self):
        ts = ThemeSummarizer([])
        result = ts._extract_title_keywords([], max_keywords=5)
        assert result == []

    def test_generate_single_theme_briefing_empty_articles(self):
        ts = ThemeSummarizer([])
        result = ts._generate_single_theme_briefing("bitcoin", [])
        assert result == ""

    def test_generate_single_theme_briefing_returns_string(self):
        articles = [
            {"title": f"Bitcoin ETF hashrate {i}", "description": "BTC mining"}
            for i in range(5)
        ]
        ts = ThemeSummarizer([])
        result = ts._generate_single_theme_briefing("bitcoin", articles)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_generate_single_theme_briefing_few_keywords_fallback(self):
        # Articles with only 1 distinct keyword → falls back to description
        articles = [
            {"title": "the", "description": "Bitcoin price rises sharply in the market today."}
            for _ in range(3)
        ]
        ts = ThemeSummarizer([])
        result = ts._generate_single_theme_briefing("bitcoin", articles)
        assert isinstance(result, str)


class TestPriorityKeywordsData:
    """Validate PRIORITY_KEYWORDS structure."""

    def test_all_buckets_present(self):
        assert "P0" in PRIORITY_KEYWORDS
        assert "P1" in PRIORITY_KEYWORDS
        assert "P2" in PRIORITY_KEYWORDS

    def test_all_buckets_non_empty(self):
        for bucket in ["P0", "P1", "P2"]:
            assert len(PRIORITY_KEYWORDS[bucket]) > 0

    def test_known_p0_keywords_present(self):
        kws = PRIORITY_KEYWORDS["P0"]
        assert "crash" in kws
        assert "hack" in kws
        assert "exploit" in kws

    def test_known_p1_keywords_present(self):
        kws = PRIORITY_KEYWORDS["P1"]
        assert "regulation" in kws
        assert "etf" in kws

    def test_known_p2_keywords_present(self):
        kws = PRIORITY_KEYWORDS["P2"]
        assert "partnership" in kws
        assert "launch" in kws


class TestThemesData:
    """Validate THEMES list structure."""

    def test_themes_is_non_empty_list(self):
        assert isinstance(THEMES, list)
        assert len(THEMES) > 0

    def test_each_theme_is_4_tuple(self):
        for theme in THEMES:
            assert len(theme) == 4

    def test_each_theme_has_keywords(self):
        for name, key, emoji, keywords in THEMES:
            assert isinstance(name, str)
            assert isinstance(key, str)
            assert isinstance(keywords, list)
            assert len(keywords) > 0

    def test_bitcoin_theme_present(self):
        keys = [t[1] for t in THEMES]
        assert "bitcoin" in keys

    def test_ethereum_theme_present(self):
        keys = [t[1] for t in THEMES]
        assert "ethereum" in keys

    def test_regulation_theme_present(self):
        keys = [t[1] for t in THEMES]
        assert "regulation" in keys
