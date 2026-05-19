"""Unit tests for scripts/common/summarizer_priority.py.

Tests cover classify_priority() and _make_keyword_pattern() directly without
going through ThemeSummarizer. Each test class is named after the behaviour
being verified.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from common.summarizer_priority import (
    _P0_RE,
    _P1_RE,
    _P2_RE,
    PRIORITY_KEYWORDS,
    _make_keyword_pattern,
    classify_priority,
)

# ---------------------------------------------------------------------------
# classify_priority — basic bucketing
# ---------------------------------------------------------------------------


class TestClassifyPriorityEmptyInput:
    def test_empty_list_returns_all_buckets_empty(self):
        result = classify_priority([])
        assert result == {"P0": [], "P1": [], "P2": []}


class TestClassifyPriorityP0Matching:
    def test_crash_english_goes_to_p0(self):
        items = [{"title": "Market crash wipes out billions"}]
        result = classify_priority(items)
        assert len(result["P0"]) == 1
        assert result["P0"][0] is items[0]
        assert len(result["P1"]) == 0
        assert len(result["P2"]) == 0

    def test_폭락_korean_goes_to_p0(self):
        items = [{"title": "비트코인 폭락 공포 확산"}]
        result = classify_priority(items)
        assert len(result["P0"]) == 1

    def test_hack_english_goes_to_p0(self):
        items = [{"title": "Exchange hack confirmed, $100M stolen"}]
        result = classify_priority(items)
        assert len(result["P0"]) == 1

    def test_긴급_korean_goes_to_p0(self):
        items = [{"title": "긴급 공지: 거래소 점검"}]
        result = classify_priority(items)
        assert len(result["P0"]) == 1


class TestClassifyPriorityP1Matching:
    def test_regulation_english_goes_to_p1(self):
        items = [{"title": "New regulation targets crypto exchanges"}]
        result = classify_priority(items)
        assert len(result["P1"]) == 1
        assert len(result["P0"]) == 0

    def test_etf_goes_to_p1(self):
        items = [{"title": "Bitcoin ETF approval expected next week"}]
        result = classify_priority(items)
        assert len(result["P1"]) == 1

    def test_approval_goes_to_p1(self):
        items = [{"title": "SEC approval granted for spot Bitcoin ETF"}]
        result = classify_priority(items)
        assert len(result["P1"]) == 1

    def test_규제_korean_goes_to_p1(self):
        items = [{"title": "가상자산 규제 법안 발의"}]
        result = classify_priority(items)
        assert len(result["P1"]) == 1


class TestClassifyPriorityP2Matching:
    def test_partnership_goes_to_p2(self):
        items = [{"title": "Coinbase announces partnership with major bank"}]
        result = classify_priority(items)
        assert len(result["P2"]) == 1
        assert len(result["P0"]) == 0
        assert len(result["P1"]) == 0

    def test_launch_goes_to_p2(self):
        items = [{"title": "New DeFi protocol launch scheduled for Q3"}]
        result = classify_priority(items)
        assert len(result["P2"]) == 1

    def test_airdrop_goes_to_p2(self):
        items = [{"title": "Airdrop tokens distributed to early users"}]
        result = classify_priority(items)
        assert len(result["P2"]) == 1

    def test_출시_korean_goes_to_p2(self):
        items = [{"title": "새 지갑 앱 출시 예정"}]
        result = classify_priority(items)
        assert len(result["P2"]) == 1


# ---------------------------------------------------------------------------
# Priority: single assignment (highest bucket only)
# ---------------------------------------------------------------------------


class TestClassifyPrioritySingleAssignment:
    def test_p0_and_p1_keywords_assigned_to_p0_only(self):
        # "crash" (P0) + "regulation" (P1) → only P0
        items = [{"title": "Regulation causes market crash today"}]
        result = classify_priority(items)
        assert len(result["P0"]) == 1
        assert len(result["P1"]) == 0
        assert len(result["P2"]) == 0

    def test_p1_and_p2_keywords_assigned_to_p1_only(self):
        # "etf" (P1) + "launch" (P2) → only P1
        items = [{"title": "ETF product launch announced by BlackRock"}]
        result = classify_priority(items)
        assert len(result["P1"]) == 1
        assert len(result["P2"]) == 0

    def test_all_three_priorities_assigned_to_p0_only(self):
        # P0: "hack", P1: "regulation", P2: "partnership"
        items = [{"title": "Hack sparks regulation talks and partnership collapse"}]
        result = classify_priority(items)
        assert len(result["P0"]) == 1
        assert len(result["P1"]) == 0
        assert len(result["P2"]) == 0


# ---------------------------------------------------------------------------
# Deduplication within bucket
# ---------------------------------------------------------------------------


class TestClassifyPriorityDedup:
    def test_duplicate_titles_in_same_bucket_deduplicated(self):
        items = [
            {"title": "Bitcoin crash hits 30k"},
            {"title": "Bitcoin crash hits 30k"},  # exact duplicate
        ]
        result = classify_priority(items)
        assert len(result["P0"]) == 1

    def test_case_insensitive_dedup(self):
        items = [
            {"title": "bitcoin crash hits 30k"},
            {"title": "Bitcoin Crash Hits 30k"},
        ]
        result = classify_priority(items)
        assert len(result["P0"]) == 1

    def test_different_titles_not_deduplicated(self):
        items = [
            {"title": "Bitcoin crash reported today"},
            {"title": "Ethereum crash recorded"},
        ]
        result = classify_priority(items)
        assert len(result["P0"]) == 2


# ---------------------------------------------------------------------------
# title vs title_original fallback
# ---------------------------------------------------------------------------


class TestClassifyPriorityTitleFallback:
    def test_title_field_used_when_present(self):
        item = {"title": "Market crash confirmed", "title_original": "no keyword here"}
        result = classify_priority([item])
        assert len(result["P0"]) == 1

    def test_title_original_used_when_title_absent(self):
        item = {"title_original": "Bitcoin hack discovered"}
        result = classify_priority([item])
        assert len(result["P0"]) == 1

    def test_empty_title_falls_back_to_title_original(self):
        item = {"title": "", "title_original": "Exchange hack"}
        result = classify_priority([item])
        assert len(result["P0"]) == 1


# ---------------------------------------------------------------------------
# Description field matching
# ---------------------------------------------------------------------------


class TestClassifyPriorityDescriptionMatching:
    def test_p0_keyword_in_description_matched(self):
        item = {"title": "Breaking news from crypto world", "description": "A major hack occurred overnight"}
        result = classify_priority([item])
        assert len(result["P0"]) == 1

    def test_p1_keyword_in_description_matched(self):
        item = {"title": "Industry update", "description": "New ETF product under review"}
        result = classify_priority([item])
        assert len(result["P1"]) == 1

    def test_p2_keyword_in_description_matched(self):
        item = {"title": "Company news", "description": "Announced airdrop for community members"}
        result = classify_priority([item])
        assert len(result["P2"]) == 1

    def test_no_match_in_title_or_description_not_bucketed(self):
        item = {"title": "Weather forecast today", "description": "Sunny skies expected"}
        result = classify_priority([item])
        total = len(result["P0"]) + len(result["P1"]) + len(result["P2"])
        assert total == 0


# ---------------------------------------------------------------------------
# Word boundary: partial matches should not trigger
# ---------------------------------------------------------------------------


class TestClassifyPriorityWordBoundary:
    def test_crashed_does_not_match_crash_pattern(self):
        # "crashed" should not match P0 "crash" keyword due to word boundary
        item = {"title": "the market has crashed badly this week"}
        result = classify_priority([item])
        # "crashed" ends with extra chars — word boundary prevents match
        # NOTE: actual behaviour depends on regex; we verify no false positive
        # only if the implementation explicitly uses \b for "crash"
        # The implementation uses \b for ASCII keywords → "crashed" ≠ "crash"
        assert len(result["P0"]) == 0

    def test_crashes_does_not_match_crash(self):
        item = {"title": "Stock market crashes into bear territory"}
        result = classify_priority([item])
        # "crashes" contains extra 'es' — should not match "crash\b"
        assert len(result["P0"]) == 0

    def test_exact_crash_matches(self):
        item = {"title": "A crash occurred in the market"}
        result = classify_priority([item])
        assert len(result["P0"]) == 1


# ---------------------------------------------------------------------------
# _make_keyword_pattern
# ---------------------------------------------------------------------------


class TestMakeKeywordPattern:
    def test_non_empty_list_returns_compiled_pattern(self):
        import re
        pattern = _make_keyword_pattern(["crash", "hack"])
        assert isinstance(pattern, re.Pattern)

    def test_pattern_matches_keyword(self):
        pattern = _make_keyword_pattern(["crash"])
        assert pattern.search("a crash happened")

    def test_pattern_is_case_insensitive(self):
        pattern = _make_keyword_pattern(["crash"])
        assert pattern.search("CRASH")
        assert pattern.search("Crash")

    def test_empty_list_returns_compiled_pattern(self):
        import re

        # Empty keyword list → re.compile("") or similar; must return a Pattern
        pattern = _make_keyword_pattern([])
        assert isinstance(pattern, re.Pattern)


# ---------------------------------------------------------------------------
# Re-exported regex constants
# ---------------------------------------------------------------------------


class TestReExportedRegexPatterns:
    def test_p0_re_matches_crash(self):
        assert _P0_RE.search("market crash")

    def test_p1_re_matches_etf(self):
        assert _P1_RE.search("Bitcoin ETF news")

    def test_p2_re_matches_airdrop(self):
        assert _P2_RE.search("upcoming airdrop event")

    def test_priority_keywords_has_p0_p1_p2_keys(self):
        assert set(PRIORITY_KEYWORDS.keys()) == {"P0", "P1", "P2"}

    def test_each_priority_has_at_least_one_keyword(self):
        for level in ("P0", "P1", "P2"):
            assert len(PRIORITY_KEYWORDS[level]) > 0
