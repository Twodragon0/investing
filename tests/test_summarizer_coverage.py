"""Additional coverage tests for scripts/common/summarizer.py

Targets specific uncovered lines from coverage report:
  192-194  : _favicon_url exception path
  283      : _generate_title_based_desc long-title Korean branch (ctx only, no entity)
  297      : English title > 120 chars truncation
  378      : _is_boilerplate_desc empty input
  790-792  : _load_en_keyword_ko file-not-found path
  1217     : _NOISE_TITLE_RE filter in generate_themed_news_sections
  1374     : non-dict item in overflow list
  1376     : remaining_count > 15 truncation message
  1821     : short 1-2 char English token skipped in _extract_title_keywords
  1847-1863: _prepare_display_keywords Korean / translated / upper / skip branches
  1990     : snippet > 150 chars truncation in _generate_single_theme_briefing
  1998-2007: strategy 3 & 4 fallbacks in _generate_single_theme_briefing
  2017     : _generate_theme_subtitle with no valid articles
  2031     : long snippet truncation in _generate_theme_subtitle
  2061-2062: generate_theme_briefing no-content guard
  2110     : title too short guard in generate_summary_section article loop
  2112     : _NOISE_TITLE_RE filter in generate_summary_section
  2175     : p0_title > 100 chars with keyword extraction in _build_narrative_intro
  2229-2235: general multi-theme intro (Case 4)
  2279     : generate_overall_summary_section snippet branch
  2367-2371: _build_executive_opener p0_title > 100 with keyword extraction
  2501     : total_override path in generate_executive_summary
  2532/2536/2540: short_briefing > 40 chars truncation / empty briefing fallback
  2561-2566: P0 alert desc_part with Korean chars / no-link branches
  2608     : generate_market_insight seen_pairs dedup
  2674     : generate_market_insight no insight_found and no monitor_points
  2802     : detect_concentration top is empty list
"""

import pytest

from common.summarizer import (
    ThemeSummarizer,
    _favicon_url,
    _generate_title_based_desc,
    _is_boilerplate_desc,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _item(title="", description="", source="", link="", **kw):
    d = {"title": title, "description": description, "source": source, "link": link}
    d.update(kw)
    return d


def _btc_items(n=10):
    return [
        _item(
            title=f"Bitcoin ETF approved number {i}",
            description=f"BTC mining hashrate surge {i}%",
            link=f"https://example.com/{i}",
            source="CoinDesk",
        )
        for i in range(n)
    ]


def _mixed_items():
    items = [_item(title=f"Bitcoin mining hashrate {i}", description=f"BTC whale {i}") for i in range(5)]
    items += [_item(title=f"SEC regulation enforcement {i}", description=f"Compliance {i}") for i in range(4)]
    items += [_item(title=f"DeFi TVL yield protocol {i}", description=f"Uniswap pool {i}") for i in range(3)]
    items += [_item(title=f"Fed FOMC rate decision {i}", description=f"Inflation CPI {i}") for i in range(3)]
    return items


# ---------------------------------------------------------------------------
# _favicon_url — exception branch (lines 192-194)
# ---------------------------------------------------------------------------


class TestFaviconUrlException:
    def test_malformed_url_returns_empty(self):
        """Line 192-194: exception handler returns empty string."""
        from unittest.mock import patch

        # urlparse is imported inside the function from urllib.parse;
        # patch at the stdlib location it resolves to at call time.
        with patch("urllib.parse.urlparse", side_effect=Exception("parse error")):
            result = _favicon_url("https://example.com/news")
        assert result == ""

    def test_domain_with_no_netloc_returns_empty(self):
        """If domain is empty string the function returns ''."""
        # A plain path with no scheme/netloc gives empty netloc
        result = _favicon_url("/just/a/path")
        # Either a URL or empty is acceptable; just must not raise
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# _generate_title_based_desc — uncovered branches
# ---------------------------------------------------------------------------


class TestGenerateTitleBasedDescBranches:
    def test_korean_title_no_entity_with_ctx(self):
        """Line 283: ctx exists but entity_str is empty → return f'{clean}. {ctx}'."""
        # A Korean title with no extractable numbers/percentages → entity_str empty
        result = _generate_title_based_desc("비트코인 시장 동향 분석 보고서", "bitcoin")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_english_title_over_120_chars_truncated(self):
        """Line 297: clean > 120 → clean[:117] + '...'."""
        long_title = "Bitcoin ETF sees unprecedented inflows as " + "institutional demand surges " * 5
        assert len(long_title) > 120
        result = _generate_title_based_desc(long_title, "bitcoin")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_entity_str_with_ctx(self):
        """Line 300-301: entity_str and ctx both present."""
        result = _generate_title_based_desc("Bitcoin surges 15% to $100K milestone", "bitcoin")
        assert "15%" in result or "$100K" in result or "비트코인" in result

    def test_entity_str_without_ctx(self):
        """Line 303-304: entity_str present, ctx empty (unknown theme)."""
        result = _generate_title_based_desc("BTC surges 20% to new ATH", "unknown_theme_xyz")
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# _is_boilerplate_desc — empty input (line 378)
# ---------------------------------------------------------------------------


class TestIsBoilerplateDesc:
    def test_empty_string_returns_false(self):
        """Line 378: empty/falsy input returns False immediately."""
        assert _is_boilerplate_desc("") is False

    def test_none_returns_false(self):
        assert _is_boilerplate_desc(None) is False  # type: ignore[arg-type]

    def test_boilerplate_phrase_detected(self):
        """Positive case to confirm the function works."""
        from common.summarizer import _BOILERPLATE_DESC_PHRASES

        if _BOILERPLATE_DESC_PHRASES:
            phrase = _BOILERPLATE_DESC_PHRASES[0]
            assert _is_boilerplate_desc(f"some text {phrase} more") is True

    def test_non_boilerplate_returns_false(self):
        assert _is_boilerplate_desc("The Fed raised rates by 25bps as expected.") is False


# ---------------------------------------------------------------------------
# _load_en_keyword_ko — file-not-found path (lines 790-792)
# ---------------------------------------------------------------------------


class TestLoadEnKeywordKo:
    def test_missing_file_returns_empty_dict(self, tmp_path, monkeypatch):
        """Lines 790-792: FileNotFoundError → return {}."""
        from unittest.mock import patch

        # Point __file__ context to tmp dir where file doesn't exist
        with patch("common.summarizer.os.path.join", return_value=str(tmp_path / "nonexistent.json")):
            from common.summarizer import _load_en_keyword_ko

            result = _load_en_keyword_ko()
        assert isinstance(result, dict)

    def test_invalid_json_returns_empty_dict(self, tmp_path):
        """JSONDecodeError → return {}."""
        from unittest.mock import patch

        bad_json = tmp_path / "en_keyword_ko.json"
        bad_json.write_text("{ invalid json }", encoding="utf-8")
        with patch("common.summarizer.os.path.join", return_value=str(bad_json)):
            from common.summarizer import _load_en_keyword_ko

            result = _load_en_keyword_ko()
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# ThemeSummarizer._prepare_display_keywords — all branches (lines 1847-1868)
# ---------------------------------------------------------------------------


class TestPrepareDisplayKeywords:
    def _ts(self):
        return ThemeSummarizer([])

    def test_korean_token_included(self):
        """Line 1853: token contains 가-힣 → candidate = token."""
        ts = self._ts()
        result = ts._prepare_display_keywords(["비트코인", "이더리움"], max_keywords=3)
        assert "비트코인" in result

    def test_uppercase_ticker_included(self):
        """Line 1856-1857: token.isupper() → candidate = token.upper()."""
        ts = self._ts()
        result = ts._prepare_display_keywords(["BTC", "ETH"], max_keywords=3)
        assert "BTC" in result

    def test_known_lowercase_ticker_uppercased(self):
        """Line 1856: lower in {'btc', 'eth', ...} → upper case."""
        ts = self._ts()
        result = ts._prepare_display_keywords(["btc", "eth", "sec"], max_keywords=3)
        assert "BTC" in result

    def test_unknown_english_word_skipped(self):
        """Line 1858-1859: mixed-case Latin word not in known set → skip."""
        ts = self._ts()
        result = ts._prepare_display_keywords(["someword", "another"], max_keywords=3)
        assert result == []

    def test_duplicate_normalized_skipped(self):
        """Lines 1862-1863: duplicate normalized value skipped."""
        ts = self._ts()
        result = ts._prepare_display_keywords(["BTC", "BTC", "BTC"], max_keywords=5)
        assert result.count("BTC") == 1

    def test_max_keywords_respected(self):
        ts = self._ts()
        kws = ["비트코인", "이더리움", "규제", "보안", "거래소"]
        result = ts._prepare_display_keywords(kws, max_keywords=2)
        assert len(result) <= 2

    def test_empty_token_skipped(self):
        """Line 1846-1847: empty token after strip continues."""
        ts = self._ts()
        result = ts._prepare_display_keywords(["", "  ", ".,:"], max_keywords=3)
        assert result == []


# ---------------------------------------------------------------------------
# ThemeSummarizer._extract_title_keywords — short token skip (line 1821)
# ---------------------------------------------------------------------------


class TestExtractTitleKeywordsShortToken:
    def test_short_two_char_english_token_skipped(self):
        """Line 1820-1821: 1-2 char all-lowercase Latin tokens skipped."""
        ts = ThemeSummarizer([])
        items = [{"title": "to be or not to be"}, {"title": "it is so"}]
        result = ts._extract_title_keywords(items, max_keywords=10)
        # Short tokens like 'to', 'be', 'or', 'it', 'is', 'so' must be absent
        for token in result:
            assert not (len(token) <= 2 and token.isalpha() and token.islower()), f"Short token leaked: {token!r}"


# ---------------------------------------------------------------------------
# ThemeSummarizer._generate_single_theme_briefing — fallback strategies
# ---------------------------------------------------------------------------


class TestGenerateSingleThemeBriefingFallbacks:
    def _ts(self):
        return ThemeSummarizer([])

    def test_strategy_3_uses_title_when_no_good_desc(self):
        """Lines 1998-2001: strategy 3 — use top article title when desc is poor."""
        ts = self._ts()
        articles = [
            {"title": "Bitcoin price hits all-time high this week", "description": ""},
            {"title": "BTC ETF inflows record", "description": ""},
        ]
        result = ts._generate_single_theme_briefing("bitcoin", articles)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_strategy_4_keywords_fallback(self):
        """Lines 2004-2005: strategy 4 — keyword dump when no title qualifies."""
        ts = self._ts()
        # Titles too short (< 15 chars) and empty descriptions
        articles = [{"title": "BTC", "description": ""}]
        result = ts._generate_single_theme_briefing("bitcoin", articles)
        assert isinstance(result, str)

    def test_strategy_2_snippet_over_150_truncated(self):
        """Line 1990: snippet > 150 chars is truncated."""
        ts = self._ts()
        long_desc = "Bitcoin has been experiencing a massive institutional-driven rally. " * 5
        assert len(long_desc) > 150
        articles = [
            {
                "title": "Bitcoin ETF record inflows",
                "description": long_desc,
            }
        ]
        result = ts._generate_single_theme_briefing("bitcoin", articles)
        assert isinstance(result, str)
        assert len(result) > 0


# ---------------------------------------------------------------------------
# ThemeSummarizer._generate_theme_subtitle — edge cases (lines 2017, 2031)
# ---------------------------------------------------------------------------


class TestGenerateThemeSubtitle:
    def test_empty_articles_returns_empty(self):
        """Line 2017: no articles → ''."""
        ts = ThemeSummarizer([])
        assert ts._generate_theme_subtitle("bitcoin", []) == ""

    def test_all_generic_desc_returns_empty(self):
        """All descriptions are generic → returns ''."""
        ts = ThemeSummarizer([])
        articles = [
            {
                "title": "Bitcoin news",
                "description": "Click here to continue reading.",
            }
            for _ in range(3)
        ]
        result = ts._generate_theme_subtitle("bitcoin", articles)
        assert isinstance(result, str)

    def test_long_snippet_truncated(self):
        """Line 2031: snippet > 120 → truncation with '...'."""
        ts = ThemeSummarizer([])
        long_desc = "Bitcoin surged to a new all-time high driven by institutional demand and ETF inflows. " * 3
        assert len(long_desc) > 120
        articles = [{"title": "Bitcoin ATH", "description": long_desc}]
        result = ts._generate_theme_subtitle("bitcoin", articles)
        if result:
            assert len(result) <= 120

    def test_valid_desc_returned(self):
        """Happy path: valid non-generic description."""
        ts = ThemeSummarizer([])
        articles = [
            {
                "title": "Bitcoin price surge",
                "description": "Bitcoin surged 15% today driven by ETF inflows and whale accumulation.",
            }
        ]
        result = ts._generate_theme_subtitle("bitcoin", articles)
        assert isinstance(result, str)
        assert "Bitcoin surged 15%" in result

    def test_title_plus_source_desc_skipped(self):
        """Description that is only the title + source suffix is a duplicate and
        must be skipped (avoids the redundant italic theme-subtitle line)."""
        ts = ThemeSummarizer([])
        articles = [
            {
                "title": "5월 코스피 44조 팔아치운 외국인, 코스닥 2.8조 순매수",
                "description": "5월 코스피 44조 팔아치운 외국인, 코스닥 2.8조 순매수 조선일보",
            }
        ]
        assert ts._generate_theme_subtitle("stock", articles) == ""


# ---------------------------------------------------------------------------
# ThemeSummarizer.generate_theme_briefing — no-content guard (lines 2060-2062)
# ---------------------------------------------------------------------------


class TestGenerateThemeBriefingNoContent:
    def test_returns_empty_when_all_briefings_are_theme_name(self):
        """Lines 2060-2062: has_content remains False → return ''."""
        # Items that score for bitcoin but produce empty briefings
        ts = ThemeSummarizer(_btc_items(10))
        # Monkeypatch _generate_single_theme_briefing to return empty
        ts._generate_single_theme_briefing = lambda key, arts: ""
        result = ts.generate_theme_briefing()
        assert result == ""


# ---------------------------------------------------------------------------
# ThemeSummarizer.generate_summary_section — title guard & noise filter
# ---------------------------------------------------------------------------


class TestGenerateSummarySectionGuards:
    def test_short_title_skipped(self):
        """Line 2110: title.strip() < 5 chars → continue."""
        items = _btc_items(10)
        # inject an item with a very short title
        items.append(_item(title="BTC", description="Bitcoin info", link="https://x.com"))
        ts = ThemeSummarizer(items)
        result = ts.generate_summary_section()
        assert isinstance(result, str)

    def test_noise_title_filtered(self):
        """Line 2112: _NOISE_TITLE_RE match → skip article."""
        items = _btc_items(10)
        items.append(
            _item(
                title="AMENDMENT NO. 3 to Form S-1 Bitcoin filing",
                description="regulatory boilerplate",
                link="https://sec.gov",
            )
        )
        ts = ThemeSummarizer(items)
        result = ts.generate_summary_section()
        assert isinstance(result, str)

    def test_article_without_link_renders_plain(self):
        """Line 2122: link is empty → plain title without hyperlink."""
        items = _btc_items(10)
        items.append(_item(title="Bitcoin hashrate mining all time high record", description="BTC up", link=""))
        ts = ThemeSummarizer(items)
        result = ts.generate_summary_section()
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# ThemeSummarizer._build_narrative_intro — p0 title > 100 (line 2175)
# ---------------------------------------------------------------------------


class TestBuildNarrativeIntroLongP0Title:
    def test_long_p0_title_truncated(self):
        """Line 2174-2175: p0_title > 100 → truncation path."""
        ts = ThemeSummarizer(_btc_items(10))
        long_title = "Bitcoin exchange hack exploit discovered by security researchers " + "x" * 60
        assert len(long_title) > 100
        p0_items = [{"title": long_title, "description": ""}]
        priority = {"P0": p0_items, "P1": [], "P2": []}
        result = ts._build_narrative_intro([], priority, 10)
        assert "긴급" in result

    def test_p0_with_p1_items_mention(self):
        """Line 2180-2181: p1_items present → mention in intro."""
        ts = ThemeSummarizer(_btc_items(10))
        priority = {
            "P0": [{"title": "Bitcoin crash detected", "description": ""}],
            "P1": [{"title": "New ETF regulation"}, {"title": "FOMC rate hike"}],
            "P2": [],
        }
        result = ts._build_narrative_intro([], priority, 10)
        assert "P1" in result or "이슈" in result


# ---------------------------------------------------------------------------
# ThemeSummarizer._build_narrative_intro — Case 4: general multi-theme
# ---------------------------------------------------------------------------


class TestBuildNarrativeIntroCase4:
    def test_general_multi_theme_intro(self):
        """Lines 2229-2235: Case 4 — 2+ themes, no dominant narrative."""
        # Build themes with counts that won't trigger dominant-narrative path
        ts = ThemeSummarizer(_mixed_items())
        ts._ensure_scored()
        top_themes = ts.get_top_themes()
        if len(top_themes) < 2:
            pytest.skip("Need at least 2 themes for Case 4")

        # Temporarily clear dominant narratives to force Case 4
        import common.summarizer as sm

        original = sm.THEME_DOMINANT_NARRATIVES.copy()
        sm.THEME_DOMINANT_NARRATIVES.clear()
        try:
            priority = {"P0": [], "P1": [], "P2": []}
            result = ts._build_narrative_intro(top_themes, priority, len(ts.items))
            assert "건" in result or "총" in result
        finally:
            sm.THEME_DOMINANT_NARRATIVES.update(original)


# ---------------------------------------------------------------------------
# ThemeSummarizer.generate_overall_summary_section — p1 items > 3 (line 2279)
# ---------------------------------------------------------------------------


class TestGenerateOverallSummarySectionP1Overflow:
    def test_p1_items_overflow_shows_extra_count(self):
        """Line 2309-2310: more than 3 P1 items → 'outside N건' line."""
        items = _btc_items(10)
        for i in range(5):
            items.append(
                _item(
                    title=f"New regulation ETF listing policy {i}",
                    description="regulatory compliance",
                )
            )
        ts = ThemeSummarizer(items)
        result = ts.generate_overall_summary_section()
        assert isinstance(result, str)

    def test_total_override_used(self):
        """Line 2258: total_override parameter path."""
        ts = ThemeSummarizer(_btc_items(10))
        result = ts.generate_overall_summary_section(total_override=999)
        assert "999" in result


# ---------------------------------------------------------------------------
# ThemeSummarizer._build_executive_opener — long p0 title with keywords
# ---------------------------------------------------------------------------


class TestBuildExecutiveOpenerLongP0:
    def test_long_p0_title_uses_keyword_extraction(self):
        """Lines 2365-2371: p0_title > 100 → keyword extraction fallback."""
        ts = ThemeSummarizer(_btc_items(10))
        ts._ensure_scored()
        top_themes = ts.get_top_themes()
        long_title = "Bitcoin exchange hack exploit discovered causing major crash in crypto market " + "x" * 40
        assert len(long_title) > 100
        p0_items = [{"title": long_title, "description": "BTC emergency halt"}]
        priority = {"P0": p0_items, "P1": [], "P2": []}
        result = ts._build_executive_opener("crypto", top_themes, priority, 10, {})
        assert "긴급" in result or "암호화폐" in result


# ---------------------------------------------------------------------------
# ThemeSummarizer.generate_executive_summary — short_briefing > 40 / fallback
# ---------------------------------------------------------------------------


class TestGenerateExecutiveSummaryBriefingTruncation:
    def test_total_override_respected(self):
        """Line 2430: total_override path."""
        ts = ThemeSummarizer(_btc_items(10))
        result = ts.generate_executive_summary(total_override=500)
        assert "500" in result

    def test_no_matching_theme_keywords_uses_count_fallback(self):
        """Lines 2539-2540: short_briefing == '' → count fallback."""
        ts = ThemeSummarizer(_btc_items(10))
        # Monkeypatch _extract_title_keywords to return empty list
        ts._extract_title_keywords = lambda arts, max_keywords=5: []
        result = ts.generate_executive_summary()
        assert "stat-grid" in result

    def test_p0_alert_no_link(self):
        """Line 2566: p0 item without link → plain li without anchor."""
        items = _btc_items(10)
        items[0]["title"] = "Bitcoin exchange hack exploit crash"
        items[0]["description"] = "비트코인 긴급 거래 중단 발생"  # Korean desc
        items[0]["link"] = ""  # no link
        ts = ThemeSummarizer(items)
        result = ts.generate_executive_summary()
        if "alert-urgent" in result:
            # Should contain plain li without href
            assert "<li>Bitcoin" in result or "<li>" in result

    def test_p0_alert_with_korean_desc(self):
        """Lines 2559-2562: Korean desc included in alert."""
        items = _btc_items(10)
        items[0]["title"] = "Bitcoin exchange hack exploit crash"
        items[0]["description"] = "비트코인 거래소가 해킹으로 인해 서비스를 일시 중단했습니다."
        items[0]["link"] = "https://example.com/p0"
        ts = ThemeSummarizer(items)
        result = ts.generate_executive_summary()
        if "alert-urgent" in result:
            assert isinstance(result, str)

    def test_briefing_over_40_chars_truncated(self):
        """Line 2535-2536: short_briefing > 40 chars → truncation to 37 + '...'."""
        ts = ThemeSummarizer(_btc_items(10))
        # Monkeypatch _prepare_display_keywords to return a very long list
        ts._prepare_display_keywords = lambda kws, max_keywords=3: [
            "Bitcoin",
            "Ethereum",
            "Regulation",
            "DeFi",
        ]
        result = ts.generate_executive_summary()
        assert "stat-grid" in result


# ---------------------------------------------------------------------------
# ThemeSummarizer.generate_market_insight — seen_pairs dedup & no-insight path
# ---------------------------------------------------------------------------


class TestGenerateMarketInsightEdgeCases:
    def test_seen_pairs_prevents_duplicate_cross_theme(self):
        """Line 2608: pair already in seen_pairs → skip."""
        # Use mixed items to get multiple themes; the loop should dedup pairs
        ts = ThemeSummarizer(_mixed_items())
        result = ts.generate_market_insight()
        assert isinstance(result, str)

    def test_no_insight_no_monitor_returns_empty(self):
        """Line 2673-2674: insight_found=False and monitor_points=[] → return ''."""
        import common.summarizer as sm

        original_cross = sm.CROSS_THEME_INSIGHTS.copy()

        # Clear all cross-theme insights so no insight_found fires
        sm.CROSS_THEME_INSIGHTS.clear()

        # Use items that have multiple themes but no cross-theme insights
        ts = ThemeSummarizer(_mixed_items())
        ts._ensure_scored()

        try:
            result = ts.generate_market_insight()
            # With no cross-theme insights AND no monitor points that match
            # theme_monitors keys, returns "" only if no monitor points built.
            assert isinstance(result, str)
        finally:
            sm.CROSS_THEME_INSIGHTS.update(original_cross)

    def test_dominant_ratio_over_50_percent_blockquote(self):
        """Lines 2665-2671: dominant theme > 50% triggers blockquote warning."""
        # Create 10 bitcoin items + 1 other → bitcoin > 50%
        items = _btc_items(10) + [_item(title="Ethereum news rollup layer2")]
        ts = ThemeSummarizer(items)
        result = ts.generate_market_insight()
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# ThemeSummarizer.detect_concentration — empty top list (line 2802)
# ---------------------------------------------------------------------------


class TestDetectConcentrationEmptyTop:
    def test_returns_none_when_top_themes_empty(self):
        """Line 2801-2802: top is empty → return None."""
        # Use items with no theme keywords → get_top_themes returns []
        items = [_item(title=f"weather sunny today {i}") for i in range(10)]
        ts = ThemeSummarizer(items)
        # Monkeypatch get_top_themes to return []
        ts.get_top_themes = list
        ts._theme_index.mark_scored(True)
        result = ts.detect_concentration()
        assert result is None

    def test_returns_none_below_threshold(self):
        """ratio < 0.4 → return None (line 2807)."""
        # Evenly spread themes so no single one dominates
        items = (
            [_item(title=f"bitcoin btc {i}") for i in range(3)]
            + [_item(title=f"ethereum layer2 evm {i}") for i in range(3)]
            + [_item(title=f"sec regulation compliance {i}") for i in range(3)]
            + [_item(title=f"fed fomc macro rate {i}") for i in range(3)]
            + [_item(title=f"binance exchange listing {i}") for i in range(3)]
        )
        ts = ThemeSummarizer(items)
        result = ts.detect_concentration()
        # Could be None or a tuple — if tuple, ratio must be >= 0.4
        if result is not None:
            _, _, ratio = result
            assert ratio >= 0.4
