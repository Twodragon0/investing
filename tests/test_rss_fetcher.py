"""Tests for RSS fetcher (scripts/common/rss_fetcher.py)."""

from common.rss_fetcher import _clean_rss_title, get_feed_health


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
