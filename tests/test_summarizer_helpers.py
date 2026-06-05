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
)
from scripts.common.text_utils import _strip_trailing_artifacts

# ---------------------------------------------------------------------------
# _strip_trailing_artifacts — remove trailing ad/boilerplate tails only
# ---------------------------------------------------------------------------


class TestStripTrailingArtifacts:
    def test_strips_korean_ad_tail(self):
        out = _strip_trailing_artifacts("다우 가격이 더 높아졌습니다. 관련 광고.")
        assert out == "다우 가격이 더 높아졌습니다."

    def test_strips_mangled_related_info_tail(self):
        out = _strip_trailing_artifacts("가격이 폭락했습니다. 등급락 관련정보.")
        assert out == "가격이 폭락했습니다."

    def test_strips_stacked_tail(self):
        out = _strip_trailing_artifacts("두 개의 ETF가 있습니다. 등급락 관련정보.")
        assert out == "두 개의 ETF가 있습니다."

    def test_strips_english_read_more(self):
        assert _strip_trailing_artifacts("Bitcoin surges to new high. Read more") == (
            "Bitcoin surges to new high."
        )

    def test_normal_korean_sentence_unchanged(self):
        text = "비트코인이 사상 최고가를 경신했습니다."
        assert _strip_trailing_artifacts(text) == text

    def test_preserves_legitimate_period(self):
        out = _strip_trailing_artifacts("ETF 수요가 줄었습니다. 관련 광고.")
        assert out.endswith("줄었습니다.")

    def test_empty_input(self):
        assert _strip_trailing_artifacts("") == ""

    def test_strips_mangled_address_tail_with_leadin(self):
        # "급락 관련 주소." is a translation-mangled tail; lead-in word absorbed.
        out = _strip_trailing_artifacts("폭락을 경고했습니다. 급락 관련 주소.")
        assert out == "폭락을 경고했습니다."

    def test_strips_promo_tail(self):
        out = _strip_trailing_artifacts("암호화폐 거래를 시작합니다. 관련 홍보.")
        assert out == "암호화폐 거래를 시작합니다."

    def test_preserves_legitimate_보도_suffix(self):
        # "관련 보도." is a legitimate synthetic suffix from enrichment — keep it.
        text = "비트코인 가격이 급락했습니다. 급락 관련 보도."
        assert _strip_trailing_artifacts(text) == text

    def test_does_not_truncate_sentence_ending_in_sponsored(self):
        # Bare "sponsored" as a real sentence ending must NOT be stripped.
        text = "This research segment was sponsored"
        assert _strip_trailing_artifacts(text) == text

    def test_strips_sponsored_content_slug(self):
        out = _strip_trailing_artifacts("Bitcoin hits new high. Sponsored content")
        assert out == "Bitcoin hits new high."


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


# NOTE: _is_logo_url test class removed — the function was retired in #741
# (로고 패턴 정밀화 + match_logo_pattern API A-lite). Logo detection is now
# covered by tests/test_enrichment_logo.py against match_logo_pattern /
# is_logo_like_url, which summarizer.py consumes via `from .enrichment import
# is_logo_like_url`. Size-dimension patterns (256x256, 64x64, etc.) were
# intentionally dropped in A-lite as false-positive-prone OG image conflicts.


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

    def test_includes_sz_128(self):
        # Quality bumped from 64px to 128px in commit e6c37136 — test renamed
        # and assertion updated to match the new resolution.
        result = _favicon_url("https://cointelegraph.com/news/btc")
        assert "sz=128" in result

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
