"""Tests for RSS fetcher (scripts/common/rss_fetcher.py)."""

from common.rss_fetcher import _clean_rss_title, _sanitize_mojibake, get_feed_health


class TestSanitizeMojibake:
    """Regression tests for the mojibake (UTF-8↔Latin-1) sanitizer.

    Added after a CPBC RSS description leaked through as Latin-1-decoded
    UTF-8 bytes into a production post. The sanitizer must:
    1. Pass clean Korean/English text through unchanged.
    2. Round-trip recover recoverable Latin-1→UTF-8 mojibake.
    3. Drop unrecoverable mojibake (so synthetic fallback can take over).
    4. Avoid false positives on legitimate accented European text.
    """

    def test_clean_korean_passthrough(self):
        text = "한국은행이 기준금리 2.5%를 7회 연속 동결했다."
        assert _sanitize_mojibake(text) == text

    def test_clean_english_passthrough(self):
        text = "Bitcoin hits $70,000 amid strong ETF inflows"
        assert _sanitize_mojibake(text) == text

    def test_empty_string(self):
        assert _sanitize_mojibake("") == ""

    def test_recoverable_mojibake_roundtrip(self):
        # Korean UTF-8 bytes that were decoded as Latin-1 somewhere upstream.
        original = "한국 경제 뉴스"
        corrupted = original.encode("utf-8").decode("latin-1")
        assert corrupted != original  # guard: corruption actually occurred
        assert _sanitize_mojibake(corrupted) == original

    def test_unrecoverable_cpbc_mojibake_dropped(self):
        # The exact string that leaked into the 2026-04-11 political trades
        # post. Contains a U+03BC (μ) char that breaks strict Latin-1 encoding,
        # so recovery is impossible — the description must be dropped.
        corrupted = "ì£¼ëì ê¸°ì ììì ì íê³ ì¸ìì ë³μìíë¥¼ ìí´ ì²ì£¼êμê° ì¤ë¦½í ê°í¨ë¦ ì¬íì»¤ë®¤ëì¼ì´ì ë§¤ì²´ CPBC"
        assert _sanitize_mojibake(corrupted) == ""

    def test_french_accents_not_false_positive(self):
        # Legitimate accented text must pass through unchanged (no CJK in
        # hypothetical latin-1 recovery and no 3+ char mojibake runs).
        text = "Café société française à Paris"
        assert _sanitize_mojibake(text) == text

    def test_german_umlauts_not_false_positive(self):
        text = "Bundesbank erhöht Leitzins"
        assert _sanitize_mojibake(text) == text


class TestCleanRssTitle:
    def test_removes_english_source(self):
        assert _clean_rss_title("Bitcoin surges - Reuters") == "Bitcoin surges"

    def test_removes_korean_source(self):
        # Title must be >= 10 chars after cleaning, otherwise original is returned
        result = _clean_rss_title("비트코인 가격이 급등하고 있습니다 - 매일경제")
        assert "매일경제" not in result

    def test_removes_decorative_prefix(self):
        result = _clean_rss_title("▶◆ Big news today")
        assert result == "Big news today"

    def test_removes_breaking_tag(self):
        result = _clean_rss_title("[속보] 대통령 발표 내용 전문")
        assert "[속보]" not in result

    def test_removes_exclusive_tag(self):
        result = _clean_rss_title("[단독] 정부 새 정책 발표 예정")
        assert "[단독]" not in result

    def test_short_result_returns_original(self):
        original = "Short - Reuters"
        result = _clean_rss_title(original)
        # "Short" is < 10 chars, so should return original
        assert result == original

    def test_no_source_unchanged(self):
        title = "Bitcoin surges past all time high records"
        assert _clean_rss_title(title) == title

    def test_removes_domain_suffix(self):
        result = _clean_rss_title("News headline - example.com")
        assert "example.com" not in result

    def test_bloomberg(self):
        result = _clean_rss_title("Market rally continues - Bloomberg")
        assert result == "Market rally continues"

    def test_multiple_korean_sources(self):
        for source in ["한국경제", "조선일보", "이데일리", "뉴시스"]:
            result = _clean_rss_title(f"테스트 뉴스 제목입니다 헤드라인 - {source}")
            assert source not in result


class TestFeedHealth:
    def test_returns_dict(self):
        health = get_feed_health()
        assert isinstance(health, dict)
