"""tests/test_verify_post_quality.py — verify_post_quality 단위 테스트.

이 모듈은 0% 커버리지였다. `_en_ratio` 의 약어 정규화가 이 스크립트의 핵심이다 —
"KOSPI, NASDAQ, BTC" 같은 티커는 한국어 본문에서도 라틴 문자로 남으므로, 정규화
없이 세면 정상 한국어 포스트가 "English description" 으로 무더기 오탐된다.
그 정규화가 조용히 깨지면 스크립트는 실패하지 않고 **거짓 경보만 늘린다**.

격리 규칙: `check_post` 는 `os.path.dirname(__file__)` 로 저장소 루트를 계산해
이미지 존재를 확인하고, `main()` 은 실제 `_posts/` 를 glob 한다. 둘 다 monkeypatch
로 차단해 저장소 상태에 의존하지 않게 한다.
"""

import pytest
import verify_post_quality as vpq


def _post(tmp_path, frontmatter: str, body: str = "") -> str:
    path = tmp_path / "2026-08-26-sample.md"
    path.write_text(f"---\n{frontmatter}\n---\n{body}", encoding="utf-8")
    return str(path)


# ---------------------------------------------------------------------------
# _en_ratio
# ---------------------------------------------------------------------------


class TestEnRatio:
    def test_pure_english_is_one(self):
        assert vpq._en_ratio("hello world") == 1.0

    def test_pure_korean_is_zero(self):
        assert vpq._en_ratio("안녕하세요 반갑습니다") == 0.0

    def test_no_alphabetic_characters_returns_zero(self):
        assert vpq._en_ratio("123 !!! ---") == 0.0
        assert vpq._en_ratio("") == 0.0

    def test_mixed_text_is_between(self):
        ratio = vpq._en_ratio("코스피 상승 rally")
        assert 0.0 < ratio < 1.0

    @pytest.mark.parametrize("ticker", ["KOSPI", "KOSDAQ", "NASDAQ", "BTC", "ETH", "ETF", "IPO"])
    def test_known_tickers_are_stripped_before_counting(self, ticker):
        """티커가 정규화되지 않으면 정상 한국어 포스트가 영문으로 오탐된다."""
        assert vpq._en_ratio(f"{ticker} 지수가 상승했다") == 0.0

    def test_currency_pairs_are_stripped(self):
        assert vpq._en_ratio("USD/KRW 환율 상승") == 0.0
        assert vpq._en_ratio("EUR/USD 하락") == 0.0

    def test_generic_uppercase_acronym_is_stripped(self):
        assert vpq._en_ratio("FOMC 회의 결과 발표") == 0.0

    def test_lowercase_english_word_still_counts(self):
        """정규화는 대문자 약어만 지운다 — 진짜 영문 산문은 그대로 잡혀야 한다."""
        assert vpq._en_ratio("BTC surged sharply today") > 0.9


# ---------------------------------------------------------------------------
# check_post
# ---------------------------------------------------------------------------


class TestCheckPostFrontmatterGuard:
    def test_file_without_frontmatter_yields_no_issues(self, tmp_path):
        path = tmp_path / "plain.md"
        path.write_text("본문만 있는 파일", encoding="utf-8")
        assert vpq.check_post(str(path)) == []

    def test_clean_korean_post_yields_no_issues(self, tmp_path):
        path = _post(tmp_path, 'description: "코스피가 상승 마감했다"\nexcerpt: "국내 증시 요약"')
        assert vpq.check_post(path) == []


class TestCheckPostEnglishText:
    def test_english_description_is_p0(self, tmp_path):
        path = _post(tmp_path, 'description: "The market rallied sharply after the announcement"')
        issues = vpq.check_post(path)
        assert len(issues) == 1
        assert issues[0].startswith("[P0] English description:")

    def test_english_excerpt_is_p0(self, tmp_path):
        path = _post(tmp_path, 'excerpt: "Stocks climbed broadly across every major sector"')
        issues = vpq.check_post(path)
        assert len(issues) == 1
        assert issues[0].startswith("[P0] English excerpt:")

    def test_ticker_heavy_korean_description_is_not_flagged(self, tmp_path):
        """회귀 방지: 정규화가 깨지면 여기가 먼저 red 가 된다."""
        path = _post(tmp_path, 'description: "KOSPI, NASDAQ, BTC 동반 상승 마감"')
        assert vpq.check_post(path) == []

    def test_description_snippet_is_truncated(self, tmp_path):
        long_desc = "the quick brown fox jumps over the lazy dog again and again and again"
        path = _post(tmp_path, f'description: "{long_desc}"')
        issues = vpq.check_post(path)
        assert issues[0].endswith("...")
        assert long_desc[:60] in issues[0]
        assert long_desc[:61] not in issues[0]


class TestCheckPostImage:
    def test_missing_image_is_p1(self, tmp_path, monkeypatch):
        monkeypatch.setattr("os.path.exists", lambda _p: False)
        path = _post(tmp_path, 'image: "/assets/images/generated/nope.png"')
        issues = vpq.check_post(path)
        assert issues == ["[P1] Missing image: assets/images/generated/nope.png"]

    def test_existing_image_is_not_flagged(self, tmp_path, monkeypatch):
        monkeypatch.setattr("os.path.exists", lambda _p: True)
        path = _post(tmp_path, 'image: "/assets/images/generated/ok.png"')
        assert vpq.check_post(path) == []

    def test_no_image_field_skips_the_check(self, tmp_path, monkeypatch):
        monkeypatch.setattr("os.path.exists", lambda _p: pytest.fail("image 필드가 없으면 존재 확인을 하면 안 된다"))
        path = _post(tmp_path, 'description: "코스피 상승"')
        assert vpq.check_post(path) == []


class TestCheckPostAlertKeywords:
    def _body(self, keywords: str) -> str:
        return f"<strong>긴급: {keywords} - 3건 보고</strong>"

    def test_english_alert_keywords_are_p1(self, tmp_path):
        path = _post(tmp_path, 'title: "x"', self._body("regulation, enforcement"))
        issues = vpq.check_post(path)
        assert len(issues) == 1
        assert issues[0].startswith("[P1] English alert keywords:")

    def test_acronym_only_keywords_are_not_flagged(self, tmp_path):
        """NASDAQ/BTC 만 있는 알림은 번역 대상이 아니다."""
        path = _post(tmp_path, 'title: "x"', self._body("NASDAQ, BTC, ETF"))
        assert vpq.check_post(path) == []

    def test_short_english_words_are_not_flagged(self, tmp_path):
        """5자 이하 단어는 약어 취급 — 오탐을 줄이려는 의도적 하한이다."""
        path = _post(tmp_path, 'title: "x"', self._body("hack, fine"))
        assert vpq.check_post(path) == []

    def test_korean_alert_keywords_are_not_flagged(self, tmp_path):
        path = _post(tmp_path, 'title: "x"', self._body("규제, 집행"))
        assert vpq.check_post(path) == []


class TestCheckPostDuplicateHeadings:
    def test_adjacent_duplicate_heading_is_p2(self, tmp_path):
        path = _post(tmp_path, 'title: "x"', "## 시장 요약\n내용\n## 시장 요약\n")
        issues = vpq.check_post(path)
        assert issues == ["[P2] Duplicate heading: ## 시장 요약"]

    def test_non_adjacent_duplicate_is_not_flagged(self, tmp_path):
        path = _post(tmp_path, 'title: "x"', "## A\n## B\n## A\n")
        assert vpq.check_post(path) == []

    def test_reports_at_most_one_duplicate(self, tmp_path):
        path = _post(tmp_path, 'title: "x"', "## A\n## A\n## B\n## B\n")
        assert len(vpq.check_post(path)) == 1


class TestCheckPostAccumulatesIssues:
    def test_multiple_categories_are_all_reported(self, tmp_path, monkeypatch):
        monkeypatch.setattr("os.path.exists", lambda _p: False)
        path = _post(
            tmp_path,
            'description: "The market rallied sharply after the announcement"\nimage: "/assets/x.png"',
            "## 요약\n## 요약\n",
        )
        prefixes = [i.split("]")[0] + "]" for i in vpq.check_post(path)]
        assert prefixes == ["[P0]", "[P1]", "[P2]"]


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


class TestMain:
    @pytest.fixture
    def fake_posts(self, monkeypatch):
        """실제 `_posts/` 대신 제어된 목록을 돌려준다."""
        registry: dict[str, list[str]] = {}

        def fake_glob(pattern: str) -> list[str]:
            for date_str, paths in registry.items():
                if f"_posts/{date_str}-" in pattern:
                    return paths
            return []

        monkeypatch.setattr(vpq.glob, "glob", fake_glob)
        return registry

    def test_no_posts_reports_zero_and_succeeds(self, fake_posts, monkeypatch, capsys):
        monkeypatch.setattr("sys.argv", ["verify_post_quality.py", "--date", "2026-08-26"])
        assert vpq.main() == 0
        out = capsys.readouterr().out
        assert "[2026-08-26] No posts found" in out
        assert "Total: 0 posts, 0 issues" in out

    def test_clean_post_marks_check_and_returns_zero(self, fake_posts, monkeypatch, capsys):
        fake_posts["2026-08-26"] = ["/fake-posts/2026-08-26-clean.md"]
        monkeypatch.setattr(vpq, "check_post", lambda _p: [])
        monkeypatch.setattr("sys.argv", ["verify_post_quality.py", "--date", "2026-08-26"])

        assert vpq.main() == 0
        out = capsys.readouterr().out
        assert "2026-08-26-clean.md: ✓" in out
        assert "Total: 1 posts, 0 issues" in out

    def test_issues_are_printed_and_exit_is_nonzero(self, fake_posts, monkeypatch, capsys):
        fake_posts["2026-08-26"] = ["/fake-posts/2026-08-26-bad.md"]
        monkeypatch.setattr(vpq, "check_post", lambda _p: ["[P0] a", "[P1] b"])
        monkeypatch.setattr("sys.argv", ["verify_post_quality.py", "--date", "2026-08-26"])

        assert vpq.main() == 1, "이슈가 있으면 비-0 로 끝나야 CI 가 알아챈다"
        out = capsys.readouterr().out
        assert "2026-08-26-bad.md: [P0] a" in out
        assert "Total: 1 posts, 2 issues" in out

    def test_days_argument_scans_a_window(self, fake_posts, monkeypatch, capsys):
        seen: list[str] = []

        def recording_glob(pattern: str) -> list[str]:
            seen.append(pattern)
            return []

        monkeypatch.setattr(vpq.glob, "glob", recording_glob)
        monkeypatch.setattr("sys.argv", ["verify_post_quality.py", "--days", "3"])

        assert vpq.main() == 0
        assert len(seen) == 3, f"--days 3 이면 3일치를 훑어야 한다 (got {len(seen)})"

    def test_defaults_to_one_day(self, fake_posts, monkeypatch, capsys):
        seen: list[str] = []
        monkeypatch.setattr(vpq.glob, "glob", lambda p: seen.append(p) or [])
        monkeypatch.setattr("sys.argv", ["verify_post_quality.py"])

        assert vpq.main() == 0
        assert len(seen) == 1
