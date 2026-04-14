"""Tests for summarizer.py helper functions not covered by test_summarizer.py."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


from scripts.common.summarizer import (
    _SEV_BADGE_HTML,
    _SEVERITY_HIGH_KW,
    _SEVERITY_LOW_KW,
    _classify_news_severity,
    _favicon_url,
    _fix_mistranslations,
    _is_logo_url,
)

# ---------------------------------------------------------------------------
# _classify_news_severity
# ---------------------------------------------------------------------------


class TestClassifyNewsSeverity:
    def test_crash_keyword_is_high(self):
        assert _classify_news_severity("Market crash detected today") == "high"

    def test_surge_keyword_is_high(self):
        assert _classify_news_severity("Bitcoin surges to all time high") == "high"

    def test_korean_급등_is_high(self):
        assert _classify_news_severity("비트코인 급등 신고가 경신") == "high"

    def test_korean_폭락_is_high(self):
        assert _classify_news_severity("암호화폐 시장 폭락 지속") == "high"

    def test_war_keyword_is_high(self):
        assert _classify_news_severity("war breaks out in Eastern Europe") == "high"

    def test_fomc_keyword_is_high(self):
        assert _classify_news_severity("FOMC rate decision announced") == "high"

    def test_금리_keyword_is_high(self):
        assert _classify_news_severity("금리 인상 결정 발표") == "high"

    def test_breaking_keyword_is_high(self):
        assert _classify_news_severity("breaking news Bitcoin SEC") == "high"

    def test_opinion_keyword_is_low(self):
        assert _classify_news_severity("opinion: why crypto matters") == "low"

    def test_review_keyword_is_low(self):
        assert _classify_news_severity("review of top crypto wallets") == "low"

    def test_guide_keyword_is_low(self):
        assert _classify_news_severity("guide to Bitcoin investing") == "low"

    def test_korean_리뷰_is_low(self):
        assert _classify_news_severity("코인 리뷰 가이드") == "low"

    def test_neutral_title_is_medium(self):
        assert _classify_news_severity("Bitcoin ETF update this week") == "medium"

    def test_description_used_in_classification(self):
        # title is neutral but description contains high keyword
        result = _classify_news_severity("Bitcoin news", "market crash detected")
        assert result == "high"

    def test_empty_title_is_medium(self):
        assert _classify_news_severity("") == "medium"

    def test_case_insensitive(self):
        assert _classify_news_severity("BREAKING: Bitcoin CRASH") == "high"


# ---------------------------------------------------------------------------
# _SEV_BADGE_HTML
# ---------------------------------------------------------------------------


class TestSevBadgeHtml:
    def test_high_badge_present(self):
        assert "high" in _SEV_BADGE_HTML
        assert "HIGH" in _SEV_BADGE_HTML["high"]

    def test_medium_badge_present(self):
        assert "medium" in _SEV_BADGE_HTML
        assert "MED" in _SEV_BADGE_HTML["medium"]

    def test_low_badge_present(self):
        assert "low" in _SEV_BADGE_HTML
        assert "LOW" in _SEV_BADGE_HTML["low"]

    def test_all_badges_are_html_spans(self):
        for _level, html in _SEV_BADGE_HTML.items():
            assert html.startswith("<span")
            assert html.endswith("</span>")


# ---------------------------------------------------------------------------
# _fix_mistranslations
# ---------------------------------------------------------------------------


class TestFixMistranslations:
    def test_returns_string(self):
        result = _fix_mistranslations("some text")
        assert isinstance(result, str)

    def test_empty_string_unchanged(self):
        assert _fix_mistranslations("") == ""

    def test_no_mistranslations_unchanged(self):
        text = "비트코인 가격이 상승했습니다."
        assert _fix_mistranslations(text) == text

    def test_applies_corrections(self):
        # Import the corrections dict to find a real entry to test
        from scripts.common.post_generator import _MISTRANSLATION_FIXES
        if _MISTRANSLATION_FIXES:
            wrong, correct = next(iter(_MISTRANSLATION_FIXES.items()))
            result = _fix_mistranslations(f"prefix {wrong} suffix")
            assert correct in result
            assert wrong not in result


# ---------------------------------------------------------------------------
# _is_logo_url
# ---------------------------------------------------------------------------


class TestIsLogoUrl:
    def test_empty_string_returns_false(self):
        assert _is_logo_url("") is False

    def test_logo_path_returns_true(self):
        assert _is_logo_url("https://example.com/logo/site-logo.png") is True

    def test_logos_path_returns_true(self):
        assert _is_logo_url("https://cdn.example.com/logos/brand.svg") is True

    def test_favicon_returns_true(self):
        assert _is_logo_url("https://example.com/favicon.ico") is True

    def test_icon_path_returns_true(self):
        assert _is_logo_url("https://example.com/icon/app-icon.png") is True

    def test_icon_dimensions_256_returns_true(self):
        assert _is_logo_url("https://example.com/image-256x256.png") is True

    def test_icon_dimensions_128_returns_true(self):
        assert _is_logo_url("https://example.com/image-128x128.png") is True

    def test_icon_dimensions_64_returns_true(self):
        assert _is_logo_url("https://example.com/image-64x64.png") is True

    def test_icon_dimensions_32_returns_true(self):
        assert _is_logo_url("https://example.com/image-32x32.png") is True

    def test_icon_dimensions_16_returns_true(self):
        assert _is_logo_url("https://example.com/image-16x16.png") is True

    def test_snslogo_returns_true(self):
        assert _is_logo_url("https://example.com/snslogo.jpg") is True

    def test_dash_logo_returns_true(self):
        assert _is_logo_url("https://cdn.example.com/brand-logo.png") is True

    def test_underscore_logo_returns_true(self):
        assert _is_logo_url("https://cdn.example.com/brand_logo.png") is True

    def test_article_image_returns_false(self):
        assert _is_logo_url("https://example.com/articles/bitcoin-article.jpg") is False

    def test_regular_image_returns_false(self):
        assert _is_logo_url("https://cdn.example.com/photos/news-photo.jpg") is False

    def test_case_insensitive(self):
        assert _is_logo_url("https://example.com/FAVICON.PNG") is True


# ---------------------------------------------------------------------------
# _favicon_url
# ---------------------------------------------------------------------------


class TestFaviconUrl:
    def test_empty_link_returns_empty(self):
        assert _favicon_url("") == ""

    def test_returns_google_favicon_url(self):
        result = _favicon_url("https://coindesk.com/article/123")
        assert "google.com/s2/favicons" in result
        assert "coindesk.com" in result

    def test_includes_sz_64(self):
        result = _favicon_url("https://cointelegraph.com/news/btc")
        assert "sz=64" in result

    def test_domain_extracted_correctly(self):
        result = _favicon_url("https://www.bloomberg.com/crypto/2026")
        assert "bloomberg.com" in result

    def test_subdomain_included(self):
        result = _favicon_url("https://markets.businessinsider.com/news")
        assert "markets.businessinsider.com" in result

    def test_none_like_empty_string(self):
        # None-like values (empty string already tested)
        assert _favicon_url("") == ""


# ---------------------------------------------------------------------------
# Severity keyword constants
# ---------------------------------------------------------------------------


class TestSeverityKeywords:
    def test_high_keywords_non_empty(self):
        assert len(_SEVERITY_HIGH_KW) > 0

    def test_low_keywords_non_empty(self):
        assert len(_SEVERITY_LOW_KW) > 0

    def test_crash_in_high(self):
        assert "crash" in _SEVERITY_HIGH_KW

    def test_war_in_high(self):
        assert "war" in _SEVERITY_HIGH_KW

    def test_opinion_in_low(self):
        assert "opinion" in _SEVERITY_LOW_KW

    def test_review_in_low(self):
        assert "review" in _SEVERITY_LOW_KW

    def test_no_overlap_between_high_and_low(self):
        high_set = set(_SEVERITY_HIGH_KW)
        low_set = set(_SEVERITY_LOW_KW)
        assert len(high_set & low_set) == 0
