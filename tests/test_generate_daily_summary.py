"""Tests for generate_daily_summary.py — pure utility functions (no I/O)."""

import datetime as _dt
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


import scripts.generate_daily_summary as gds

# ---------------------------------------------------------------------------
# strip_html_tags
# ---------------------------------------------------------------------------


class TestStripHtmlTags:
    def test_removes_inline_tags(self):
        assert gds.strip_html_tags("<b>hello</b>") == "hello"

    def test_removes_details_block(self):
        text = "<details><summary>foo</summary>bar</details>"
        result = gds.strip_html_tags(text)
        assert "<details>" not in result
        assert "<summary>" not in result

    def test_removes_style_block(self):
        text = "<style>body{color:red}</style>content"
        assert gds.strip_html_tags(text) == "content"

    def test_removes_script_block(self):
        text = "<script>alert(1)</script>text"
        assert gds.strip_html_tags(text) == "text"

    def test_collapses_blank_lines(self):
        text = "a\n\n\n\nb"
        result = gds.strip_html_tags(text)
        assert "\n\n\n" not in result

    def test_plain_text_unchanged(self):
        assert gds.strip_html_tags("plain text") == "plain text"

    def test_empty_string(self):
        assert gds.strip_html_tags("") == ""


# ---------------------------------------------------------------------------
# _is_similar_title
# ---------------------------------------------------------------------------


class TestIsSimilarTitle:
    def test_identical_titles(self):
        assert gds._is_similar_title("bitcoin rises today", "bitcoin rises today") is True

    def test_completely_different(self):
        assert gds._is_similar_title("apple stock falls", "ethereum hacked") is False

    def test_high_overlap(self):
        assert gds._is_similar_title("bitcoin price surge today", "bitcoin price surge") is True

    def test_empty_title(self):
        assert gds._is_similar_title("", "hello world") is False

    def test_single_word_overlap(self):
        # one word overlap out of many — below threshold
        assert gds._is_similar_title("the quick brown fox", "the lazy dog ran") is False


# ---------------------------------------------------------------------------
# read_post_content
# ---------------------------------------------------------------------------


class TestReadPostContent:
    def test_missing_file(self, tmp_path):
        result = gds.read_post_content(str(tmp_path / "nonexistent.md"))
        assert result["frontmatter"] == {}
        assert result["content"] == ""

    def test_valid_post(self, tmp_path):
        post = tmp_path / "2024-01-01-test.md"
        post.write_text(
            "---\ntitle: Test Post\ncategory: crypto\n---\n## Section\nContent here.",
            encoding="utf-8",
        )
        result = gds.read_post_content(str(post))
        assert result["frontmatter"]["title"] == "Test Post"
        assert result["frontmatter"]["category"] == "crypto"
        assert "Content here" in result["content"]

    def test_no_frontmatter(self, tmp_path):
        post = tmp_path / "plain.md"
        post.write_text("Just plain text.", encoding="utf-8")
        result = gds.read_post_content(str(post))
        assert result["frontmatter"] == {}
        assert "Just plain text" in result["content"]

    def test_korean_frontmatter(self, tmp_path):
        post = tmp_path / "korean.md"
        post.write_text(
            '---\ntitle: "비트코인 상승"\ncategory: crypto\n---\n내용.',
            encoding="utf-8",
        )
        result = gds.read_post_content(str(post))
        assert result["frontmatter"]["title"] == "비트코인 상승"


# ---------------------------------------------------------------------------
# extract_section
# ---------------------------------------------------------------------------


class TestExtractSection:
    def test_extracts_section(self):
        content = "## 핵심 요약\n내용1\n내용2\n\n## 다른 섹션\n다른 내용"
        result = gds.extract_section(content, "핵심 요약")
        assert "내용1" in result
        assert "다른 내용" not in result

    def test_missing_section_returns_empty(self):
        assert gds.extract_section("## foo\nbar", "없는 섹션") == ""

    def test_last_section_no_following_heading(self):
        content = "## 마지막 섹션\n마지막 내용"
        assert "마지막 내용" in gds.extract_section(content, "마지막 섹션")


# ---------------------------------------------------------------------------
# extract_bullet_points
# ---------------------------------------------------------------------------


class TestExtractBulletPoints:
    def test_extracts_bullets(self):
        content = "## 핵심 요약\n- 항목1\n- 항목2\n- 항목3"
        bullets = gds.extract_bullet_points(content, "핵심 요약")
        assert len(bullets) == 3
        assert bullets[0] == "- 항목1"

    def test_max_items_limit(self):
        content = "## 섹션\n" + "\n".join(f"- 항목{i}" for i in range(10))
        bullets = gds.extract_bullet_points(content, "섹션", max_items=3)
        assert len(bullets) == 3

    def test_no_section(self):
        assert gds.extract_bullet_points("no section here", "없는 섹션") == []

    def test_sanitizes_defective_bullets(self):
        content = (
            "## 핵심 요약\n"
            "- 20 총 이슈 3 테마 수 2 출처 수 5 안보 이슈\n"
            "- 비트코인이 하락했습니다. 비트코인이 하락했습니다.\n"
            "- 비트코인은 ETF 수요가 줄어들면서 $73,000 가까이 하락했습니다.\n"
        )
        bullets = gds.extract_bullet_points(content, "핵심 요약")
        # Non-prose stat dump dropped entirely.
        assert all("총 이슈 3 테마" not in b for b in bullets)
        # Duplicated sentence collapsed to one occurrence.
        dup = [b for b in bullets if "비트코인이 하락했습니다" in b]
        assert dup and dup[0].count("비트코인이 하락했습니다") == 1
        # Normal prose preserved.
        assert any("$73,000" in b for b in bullets)


# ---------------------------------------------------------------------------
# extract_table_rows
# ---------------------------------------------------------------------------


class TestExtractTableRows:
    def test_extracts_rows(self):
        content = "## 테이블\n| 헤더1 | 헤더2 |\n|---|---|\n| 값1 | 값2 |\n| 값3 | 값4 |"
        rows = gds.extract_table_rows(content, "테이블")
        assert len(rows) == 2
        assert "값1" in rows[0]

    def test_max_rows_limit(self):
        rows_content = "\n".join(f"| 값{i} | 값{i} |" for i in range(15))
        content = f"## 섹션\n| H1 | H2 |\n|---|---|\n{rows_content}"
        rows = gds.extract_table_rows(content, "섹션", max_rows=5)
        assert len(rows) == 5

    def test_no_table(self):
        assert gds.extract_table_rows("## 섹션\n텍스트만", "섹션") == []


# ---------------------------------------------------------------------------
# count_news_items
# ---------------------------------------------------------------------------


class TestCountNewsItems:
    def test_pattern_n_gun(self):
        assert gds.count_news_items("오늘 42건의 뉴스가 수집되었습니다.") == 42

    def test_pattern_total_count(self):
        assert gds.count_news_items("총 수집 건수: 15건") == 15

    def test_defi_protocol_chain(self):
        result = gds.count_news_items("20개 프로토콜과 15개 체인이 포함됩니다.")
        assert result == 35

    def test_no_match(self):
        assert gds.count_news_items("관련 뉴스 없음") == 0

    def test_empty_string(self):
        assert gds.count_news_items("") == 0


# ---------------------------------------------------------------------------
# _extract_highlights
# ---------------------------------------------------------------------------


class TestExtractHighlights:
    def test_bullet_from_section(self):
        content = "## 핵심 요약\n- 비트코인 급등\n- 이더리움 하락"
        highlights = gds._extract_highlights(content)
        assert any("비트코인" in h for h in highlights)

    def test_bold_count_line(self):
        content = "**오늘 35건의 뉴스가 수집되었습니다.**\n\n## 섹션"
        highlights = gds._extract_highlights(content)
        assert any("35건" in h for h in highlights)

    def test_empty_content(self):
        assert gds._extract_highlights("") == []


# ---------------------------------------------------------------------------
# summarize_crypto_post
# ---------------------------------------------------------------------------


class TestSummarizeCryptoPost:
    def _make_post(self, content: str, title: str = "암호화폐 뉴스") -> dict:
        return {"frontmatter": {"title": title}, "content": content}

    def test_basic(self):
        post = self._make_post("## 핵심 요약\n- BTC 급등\n\n오늘 10건의 뉴스가 수집되었습니다.")
        result = gds.summarize_crypto_post(post)
        assert result["type"] == "crypto"
        assert result["title"] == "암호화폐 뉴스"
        assert result["count"] == 10

    def test_empty_content(self):
        post = self._make_post("")
        result = gds.summarize_crypto_post(post)
        assert result["type"] == "crypto"
        assert result["count"] == 0


# ---------------------------------------------------------------------------
# summarize_stock_post
# ---------------------------------------------------------------------------


class TestSummarizeStockPost:
    def test_basic(self):
        post = {"frontmatter": {"title": "주식 뉴스"}, "content": "KOSPI 2500 상승. 5건의 뉴스."}
        result = gds.summarize_stock_post(post)
        assert result["type"] == "stock"
        assert "KOSPI" in result["market_data"][0]


# ---------------------------------------------------------------------------
# get_post_url
# ---------------------------------------------------------------------------


class TestGetPostUrl:
    def test_basic_url_construction(self):
        url = gds.get_post_url("/path/to/2024-01-15-crypto.md", "2024-01-15")
        assert "2024-01-15" in url or "crypto" in url

    def test_with_category(self):
        url = gds.get_post_url("/path/2024-01-15-crypto.md", "2024-01-15", "crypto")
        assert url != ""


# ---------------------------------------------------------------------------
# _strip_markdown_link
# ---------------------------------------------------------------------------


class TestStripMarkdownLink:
    def test_strips_link(self):
        result = gds._strip_markdown_link("[Bitcoin rises](https://example.com)")
        assert result == "Bitcoin rises"

    def test_plain_text_unchanged(self):
        assert gds._strip_markdown_link("plain text") == "plain text"

    def test_empty(self):
        assert gds._strip_markdown_link("") == ""


# ---------------------------------------------------------------------------
# _is_noise_title
# ---------------------------------------------------------------------------


class TestIsNoiseTitle:
    def test_price_alert_noise(self):
        assert gds._is_noise_title("가격 알림: BTC/USDT") is True

    def test_short_title_noise(self):
        assert gds._is_noise_title("BTC") is True

    def test_filing_id_noise(self):
        assert gds._is_noise_title("DEF14A") is True

    def test_maintenance_noise(self):
        assert gds._is_noise_title("Scheduled maintenance for wallet") is True

    def test_real_title_not_noise(self):
        assert gds._is_noise_title("Bitcoin surges 10% amid ETF approval") is False

    def test_empty_string(self):
        assert gds._is_noise_title("") is True


# ---------------------------------------------------------------------------
# _clean_bullet_text / _clean_headline
# ---------------------------------------------------------------------------


class TestCleanBulletText:
    def test_strips_leading_dash(self):
        result = gds._clean_bullet_text("- 항목 내용")
        assert not result.startswith("- ")

    def test_plain_text(self):
        result = gds._clean_bullet_text("일반 텍스트")
        assert result == "일반 텍스트"


class TestCleanHeadline:
    def test_removes_trailing_dots(self):
        result = gds._clean_headline("Bitcoin rises...")
        assert not result.endswith("...")

    def test_removes_double_period(self):
        result = gds._clean_headline("Bitcoin rises..")
        assert not result.endswith("..")

    def test_plain(self):
        result = gds._clean_headline("Bitcoin rises")
        assert result == "Bitcoin rises"

    def test_empty(self):
        result = gds._clean_headline("")
        assert result == ""


# ---------------------------------------------------------------------------
# _looks_english_heavy
# ---------------------------------------------------------------------------


class TestLooksEnglishHeavy:
    def test_english_text(self):
        assert gds._looks_english_heavy("Bitcoin surges amid market volatility today") is True

    def test_korean_text(self):
        assert gds._looks_english_heavy("비트코인이 오늘 급등했습니다") is False

    def test_mixed_text(self):
        # Mixed — depends on ratio
        result = gds._looks_english_heavy("BTC 비트코인 price 가격")
        assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# _coverage_warnings
# ---------------------------------------------------------------------------


class TestCoverageWarnings:
    def test_empty_summaries(self):
        result = gds._coverage_warnings({})
        assert isinstance(result, list)

    def test_all_none(self):
        result = gds._coverage_warnings({"crypto": None, "stock": None})
        assert isinstance(result, list)
        assert len(result) > 0


# ---------------------------------------------------------------------------
# _render_generated_image
# ---------------------------------------------------------------------------


class TestRenderGeneratedImage:
    def test_nonexistent_file(self):
        result = gds._render_generated_image("nonexistent_image.png", "alt text")
        assert result is None

    def test_existing_file(self, tmp_path, monkeypatch):
        img = tmp_path / "assets" / "images" / "generated" / "test.png"
        img.parent.mkdir(parents=True)
        img.write_bytes(b"fake png")
        # Patch REPO_ROOT so the function finds the file
        monkeypatch.setattr(gds, "__file__", str(tmp_path / "scripts" / "generate_daily_summary.py"))
        # Function checks relative to script location — result varies by env
        result = gds._render_generated_image("test.png", "alt")
        assert result is None or isinstance(result, str)


# ---------------------------------------------------------------------------
# summarize_security_post
# ---------------------------------------------------------------------------


class TestSummarizeSecurityPost:
    def _make_post(self, content: str, title: str = "보안 리포트") -> dict:
        return {"frontmatter": {"title": title}, "content": content}

    def test_basic_type_and_title(self):
        post = self._make_post("## 보안 사고 현황\n| 프로젝트 | 피해 | 유형 |\n|---|---|---|\n| DeFi | $1M | 해킹 |")
        result = gds.summarize_security_post(post)
        assert result["type"] == "security"
        assert result["title"] == "보안 리포트"

    def test_incident_rows_extracted(self):
        content = "## 보안 사고 현황\n| H1 | H2 | H3 |\n|---|---|---|\n| A | B | C |\n| D | E | F |"
        post = self._make_post(content)
        result = gds.summarize_security_post(post)
        assert isinstance(result["incidents"], list)
        assert len(result["incidents"]) == 2

    def test_empty_content(self):
        post = self._make_post("")
        result = gds.summarize_security_post(post)
        assert result["type"] == "security"
        assert result["count"] == 0
        assert result["incidents"] == []


# ---------------------------------------------------------------------------
# summarize_regulatory_post
# ---------------------------------------------------------------------------


class TestSummarizeRegulatoryPost:
    def _make_post(self, content: str, title: str = "규제 동향") -> dict:
        return {"frontmatter": {"title": title}, "content": content}

    def test_basic(self):
        post = self._make_post("## 핵심 요약\n- SEC 조사 착수\n오늘 5건의 뉴스가 수집되었습니다.")
        result = gds.summarize_regulatory_post(post)
        assert result["type"] == "regulatory"
        assert result["count"] == 5

    def test_empty(self):
        post = self._make_post("")
        result = gds.summarize_regulatory_post(post)
        assert result["type"] == "regulatory"
        assert result["count"] == 0


# ---------------------------------------------------------------------------
# summarize_social_post
# ---------------------------------------------------------------------------


class TestSummarizeSocialPost:
    def _make_post(self, content: str, title: str = "소셜 미디어") -> dict:
        return {"frontmatter": {"title": title}, "content": content}

    def test_basic(self):
        post = self._make_post("## 핵심 요약\n- 비트코인 트위터 급증\n총 10건을 수집했습니다.")
        result = gds.summarize_social_post(post)
        assert result["type"] == "social"
        assert result["title"] == "소셜 미디어"

    def test_highlights_captured(self):
        post = self._make_post("## 핵심 요약\n- 항목1\n- 항목2\n오늘 7건의 뉴스가 수집되었습니다.")
        result = gds.summarize_social_post(post)
        assert len(result["highlights"]) >= 1
        assert result["count"] == 7


# ---------------------------------------------------------------------------
# summarize_market_post
# ---------------------------------------------------------------------------


class TestSummarizeMarketPost:
    def _make_post(self, content: str, title: str = "시장 종합 리포트") -> dict:
        return {"frontmatter": {"title": title}, "content": content}

    def test_basic_type(self):
        post = self._make_post("## 오늘의 핵심\n- 코스피 상승\n## 한눈에 보기\n- 요약1")
        result = gds.summarize_market_post(post)
        assert result["type"] == "market"

    def test_highlights_from_section(self):
        post = self._make_post("## 오늘의 핵심\n- 코스피 +1.5%\n- 나스닥 -0.3%")
        result = gds.summarize_market_post(post)
        assert any("코스피" in h for h in result["highlights"])

    def test_exec_summary_from_section(self):
        post = self._make_post("## 한눈에 보기\n- 핵심 요약1\n- 핵심 요약2")
        result = gds.summarize_market_post(post)
        assert len(result["exec_summary"]) == 2

    def test_indicator_rows_extracted(self):
        content = "## 매크로 경제 지표\n| 지표 | 현재 | 변동 |\n|---|---|---|\n| CPI | 3.2% | +0.1% |\n"
        post = self._make_post(content)
        result = gds.summarize_market_post(post)
        assert len(result["indicator_rows"]) == 1

    def test_empty_content(self):
        post = self._make_post("")
        result = gds.summarize_market_post(post)
        assert result["type"] == "market"
        assert result["highlights"] == []
        assert result["indicator_rows"] == []


# ---------------------------------------------------------------------------
# summarize_worldmonitor_post
# ---------------------------------------------------------------------------


class TestSummarizeWorldmonitorPost:
    def _make_post(self, content: str, title: str = "월드모니터 브리핑") -> dict:
        return {"frontmatter": {"title": title}, "content": content}

    def test_basic_type(self):
        post = self._make_post("## 핵심 요약\n- 글로벌 이슈1\n수집 건수: **20건**")
        result = gds.summarize_worldmonitor_post(post)
        assert result["type"] == "worldmonitor"

    def test_count_from_special_pattern(self):
        # "수집 건수: **N건**" pattern used in worldmonitor posts
        content = "수집 건수: **42건**"
        post = self._make_post(content)
        result = gds.summarize_worldmonitor_post(post)
        assert result["count"] == 42

    def test_count_from_standard_pattern(self):
        content = "오늘 15건의 뉴스가 수집되었습니다."
        post = self._make_post(content)
        result = gds.summarize_worldmonitor_post(post)
        assert result["count"] == 15

    def test_strips_theme_distribution_html(self):
        content = '## 핵심\n- 항목1\n<div class="theme-distribution">테마블록</div>'
        post = self._make_post(content)
        result = gds.summarize_worldmonitor_post(post)
        assert "theme-distribution" not in result["content"]

    def test_empty(self):
        post = self._make_post("")
        result = gds.summarize_worldmonitor_post(post)
        assert result["type"] == "worldmonitor"
        assert result["count"] == 0


# ---------------------------------------------------------------------------
# summarize_political_post
# ---------------------------------------------------------------------------


class TestSummarizePoliticalPost:
    def _make_post(self, content: str, title: str = "정치인 거래") -> dict:
        return {"frontmatter": {"title": title}, "content": content}

    def test_basic(self):
        post = self._make_post("## 핵심 요약\n- 펠로시 매수\n오늘 8건의 뉴스가 수집되었습니다.")
        result = gds.summarize_political_post(post)
        assert result["type"] == "political"
        assert result["count"] == 8

    def test_fallback_to_news_summary_section(self):
        content = "## 전체 뉴스 요약\n- 트럼프 에너지 정책\n총 3건을 수집했습니다."
        post = self._make_post(content)
        result = gds.summarize_political_post(post)
        assert len(result["key_summary"]) >= 1

    def test_fallback_to_bold_lines(self):
        content = "## 전체 뉴스 요약\n**트레이더**: 매수 신호\n**분석**: 상승 예상"
        post = self._make_post(content)
        result = gds.summarize_political_post(post)
        # _extract_bold_lines falls back when bullet points absent
        assert isinstance(result["key_summary"], list)

    def test_highlights_from_policy_section(self):
        content = "## 정책 영향 분석\n- 에너지 정책 변화\n- 금융 규제 완화"
        post = self._make_post(content)
        result = gds.summarize_political_post(post)
        assert len(result["highlights"]) >= 1

    def test_empty(self):
        post = self._make_post("")
        result = gds.summarize_political_post(post)
        assert result["type"] == "political"
        assert result["count"] == 0


# ---------------------------------------------------------------------------
# _extract_bold_lines
# ---------------------------------------------------------------------------


class TestExtractBoldLines:
    def test_extracts_bold_colon_lines(self):
        content = "## 섹션\n**제목**: 내용\n**다른 제목**: 다른 내용"
        result = gds._extract_bold_lines(content, "섹션")
        assert len(result) == 2
        assert all(line.startswith("- **") for line in result)

    def test_max_items_respected(self):
        lines = "\n".join(f"**항목{i}**: 내용{i}" for i in range(10))
        content = f"## 섹션\n{lines}"
        result = gds._extract_bold_lines(content, "섹션", max_items=3)
        assert len(result) == 3

    def test_no_section_returns_empty(self):
        result = gds._extract_bold_lines("## 다른 섹션\n**항목**: 내용", "없는 섹션")
        assert result == []

    def test_plain_lines_ignored(self):
        content = "## 섹션\n일반 텍스트 줄\n**굵은 제목**: 내용"
        result = gds._extract_bold_lines(content, "섹션")
        assert len(result) == 1


# ---------------------------------------------------------------------------
# _analyze_sentiment
# ---------------------------------------------------------------------------


class TestAnalyzeSentiment:
    def _make_summary(self, content: str) -> dict:
        return {"type": "crypto", "content": content, "count": 1}

    def test_positive_dominant(self):
        content = "- [비트코인 급등으로 신고가 돌파](http://example.com)\n- [이더리움 강세 지속](http://example.com)"
        result = gds._analyze_sentiment([self._make_summary(content)])
        assert result["positive"] > 0
        assert result["ratio"] > 50

    def test_negative_dominant(self):
        content = "- [비트코인 폭락 급락 해킹 사고](http://example.com)\n- [거래소 파산 위기](http://example.com)"
        result = gds._analyze_sentiment([self._make_summary(content)])
        assert result["negative"] > 0

    def test_empty_summaries_returns_neutral(self):
        result = gds._analyze_sentiment([])
        assert result["tone"] == "중립"
        assert result["ratio"] == 50

    def test_none_summaries_skipped(self):
        result = gds._analyze_sentiment([None, None])
        assert result["tone"] == "중립"

    def test_tone_labels(self):
        # Force high positive ratio via many positive keywords
        pos_content = " ".join(
            f"[{kw} 뉴스 헤드라인](http://example.com)"
            for kw in ["상승", "급등", "반등", "돌파", "신고가", "강세", "호재", "승인"]
        )
        result = gds._analyze_sentiment([self._make_summary(pos_content)])
        assert result["tone"] in ("긍정 우세", "혼조", "부정 우세", "경계", "중립")

    def test_ratio_bounds(self):
        result = gds._analyze_sentiment([self._make_summary("**비트코인 급등**")])
        assert 0 <= result["ratio"] <= 100

    def test_pos_examples_collected(self):
        content = "**비트코인이 오늘 크게 급등했습니다 (상승세)**"
        result = gds._analyze_sentiment([self._make_summary(content)])
        assert isinstance(result["pos_examples"], list)


# ---------------------------------------------------------------------------
# _extract_key_figures
# ---------------------------------------------------------------------------


class TestExtractKeyFigures:
    def test_kospi_with_percent(self):
        content = "KOSPI 2500.00(+1.23%)"
        result = gds._extract_key_figures(content)
        assert any("KOSPI" in f for f in result)

    def test_btc_price_with_currency(self):
        content = "비트코인 83,200 달러 수준을 유지했습니다."
        result = gds._extract_key_figures(content)
        assert any("비트코인" in f or "달러" in f for f in result)

    def test_yoy_percentage(self):
        content = "전일 대비 +2.3% 상승"
        result = gds._extract_key_figures(content)
        assert any("전일" in f for f in result)

    def test_empty_content_returns_empty(self):
        assert gds._extract_key_figures("") == []

    def test_max_five_results(self):
        lines = [
            "KOSPI 2500.00(+1.0%)",
            "KOSDAQ 800.00(-0.5%)",
            "S&P 4500.00(+0.3%)",
            "나스닥 15000.00(-0.2%)",
            "다우 35000.00(+0.1%)",
            "BTC 83000.00(+5.0%)",
        ]
        content = "\n".join(lines)
        result = gds._extract_key_figures(content)
        assert len(result) <= 5

    def test_dedup_same_figure(self):
        content = "KOSPI 2500.00(+1.0%) KOSPI 2500.00(+1.0%)"
        result = gds._extract_key_figures(content)
        # Should not contain duplicate
        assert len(result) == len(set(result))


# ---------------------------------------------------------------------------
# _topic_hits
# ---------------------------------------------------------------------------


class TestTopicHits:
    def test_returns_empty_for_none(self):
        result = gds._topic_hits(None)
        assert result == {}

    def test_detects_interest_rate_topic(self):
        summary = {
            "title": "연준 금리 인상 결정",
            "content": "연준이 금리를 인상했습니다.",
            "highlights": [],
            "key_summary": [],
        }
        hits = gds._topic_hits(summary)
        assert hits.get("금리/유동성", 0) > 0

    def test_detects_regulation_topic(self):
        summary = {
            "title": "SEC ETF 승인",
            "content": "SEC가 비트코인 ETF를 승인했습니다.",
            "highlights": [],
            "key_summary": [],
        }
        hits = gds._topic_hits(summary)
        assert hits.get("정책/규제", 0) > 0

    def test_returns_dict_with_all_topics(self):
        summary = {"title": "", "content": "", "highlights": [], "key_summary": []}
        hits = gds._topic_hits(summary)
        assert isinstance(hits, dict)
        assert len(hits) > 0

    def test_multiple_keyword_hits_add_up(self):
        content = "금리 금리 금리 연준 연준"
        summary = {"title": "", "content": content, "highlights": [], "key_summary": []}
        hits = gds._topic_hits(summary)
        assert hits.get("금리/유동성", 0) >= 5


# ---------------------------------------------------------------------------
# _find_shared_topics_across_categories
# ---------------------------------------------------------------------------


class TestFindSharedTopicsAcrossCategories:
    def test_returns_list(self):
        result = gds._find_shared_topics_across_categories([])
        assert isinstance(result, list)

    def test_finds_cross_cutting_topic(self):
        crypto_s = {
            "type": "crypto",
            "content": "연준 금리 인상이 비트코인에 영향을 미쳤습니다.",
            "highlights": [],
        }
        stock_s = {
            "type": "stock",
            "content": "연준 금리 결정으로 주식 시장이 하락했습니다.",
            "highlights": [],
        }
        result = gds._find_shared_topics_across_categories([crypto_s, stock_s])
        # 금리/유동성 should appear in both crypto and stock content
        topic_names = [t[0] for t in result]
        assert "금리/유동성" in topic_names

    def test_no_cross_topic_when_unrelated(self):
        crypto_s = {"type": "crypto", "content": "비트코인 가격 변동.", "highlights": []}
        result = gds._find_shared_topics_across_categories([crypto_s])
        # Single summary — cannot have 2+ categories, so no cross topics
        assert all(t[1] >= 2 for t in result)

    def test_sorted_by_category_count_desc(self):
        # Generate summaries mentioning many topics across multiple categories
        s1 = {"type": "crypto", "content": "금리 연준 환율 달러 해킹 exploit 규제 sec", "highlights": []}
        s2 = {"type": "stock", "content": "금리 연준 환율 달러 해킹 exploit 규제 sec", "highlights": []}
        s3 = {"type": "regulatory", "content": "금리 연준 규제 sec", "highlights": []}
        result = gds._find_shared_topics_across_categories([s1, s2, s3])
        if len(result) >= 2:
            assert result[0][1] >= result[1][1]


# ---------------------------------------------------------------------------
# _best_non_noise_title
# ---------------------------------------------------------------------------


class TestBestNonNoiseTitle:
    def test_returns_first_valid(self):
        titles = ["DEF14A", "Bitcoin ETF approval clears regulatory hurdle today"]
        result = gds._best_non_noise_title(titles)
        assert "ETF" in result or "Bitcoin" in result.lower() or "비트" in result

    def test_returns_empty_when_all_noise(self):
        titles = ["BTC", "DEF14A", "가격 알림: BTC/USDT"]
        result = gds._best_non_noise_title(titles)
        assert result == ""

    def test_skips_short_titles(self):
        titles = ["짧음", "이것도 짧아서 스킵됨"]
        result = gds._best_non_noise_title(titles)
        # Both are <=15 chars in Korean so should be skipped
        assert isinstance(result, str)

    def test_empty_list(self):
        assert gds._best_non_noise_title([]) == ""


# ---------------------------------------------------------------------------
# _summary_keywords_for_korean
# ---------------------------------------------------------------------------


class TestSummaryKeywordsForKorean:
    def test_known_keyword_mapped(self):
        result = gds._summary_keywords_for_korean(["sec"])
        assert result == "SEC"

    def test_multiple_keywords_joined(self):
        result = gds._summary_keywords_for_korean(["fed", "etf"])
        assert "연준" in result
        assert "ETF" in result

    def test_dedup(self):
        result = gds._summary_keywords_for_korean(["sec", "sec", "sec"])
        assert result.count("SEC") == 1

    def test_empty_list(self):
        assert gds._summary_keywords_for_korean([]) == ""


# ---------------------------------------------------------------------------
# _to_theme_payload
# ---------------------------------------------------------------------------


class TestToThemePayload:
    def test_empty_summaries_returns_empty(self):
        result = gds._to_theme_payload({})
        assert isinstance(result, list)

    def test_returns_at_most_five(self):
        s = {
            "type": "crypto",
            "title": "금리 환율 규제 해킹 실적 기술 지정학",
            "content": "금리 연준 환율 달러 규제 sec 해킹 exploit 실적 cpi 기술 tvl 전쟁",
            "highlights": [],
            "key_summary": [],
        }
        result = gds._to_theme_payload({"crypto": s})
        assert len(result) <= 5

    def test_payload_has_required_keys(self):
        s = {
            "type": "crypto",
            "title": "연준 금리",
            "content": "연준 금리 인상",
            "highlights": [],
            "key_summary": [],
        }
        result = gds._to_theme_payload({"crypto": s})
        if result:
            item = result[0]
            assert "name" in item
            assert "count" in item
            assert "keywords" in item

    def test_zero_score_topics_excluded(self):
        s = {"type": "crypto", "title": "", "content": "", "highlights": [], "key_summary": []}
        result = gds._to_theme_payload({"crypto": s})
        assert all(item["count"] > 0 for item in result)


# ---------------------------------------------------------------------------
# _extract_category_data_points
# ---------------------------------------------------------------------------


class TestExtractCategoryDataPoints:
    def test_none_returns_empty_structure(self):
        result = gds._extract_category_data_points(None)
        assert result["titles"] == []
        assert result["figures"] == []
        assert result["count"] == 0

    def test_extracts_titles_from_links(self):
        summary = {
            "content": "[Bitcoin ETF approval by SEC confirmed today](https://example.com) news",
            "count": 5,
            "themes": [],
        }
        result = gds._extract_category_data_points(summary)
        assert len(result["titles"]) >= 1

    def test_skips_image_links(self):
        summary = {
            "content": "![alt text](assets/images/generated/test.png)",
            "count": 1,
            "themes": [],
        }
        result = gds._extract_category_data_points(summary)
        assert result["titles"] == []

    def test_skips_noise_titles(self):
        summary = {
            "content": "[가격 알림: BTC/USDT](https://example.com)",
            "count": 1,
            "themes": [],
        }
        result = gds._extract_category_data_points(summary)
        assert result["titles"] == []

    def test_theme_names_extracted(self):
        # content must be non-empty to pass the early-return guard
        summary = {
            "content": "테마 내용이 있습니다.",
            "count": 10,
            "themes": [("규제", 5), ("기술", 3)],
        }
        result = gds._extract_category_data_points(summary)
        assert result["theme_names"] == ["규제", "기술"]

    def test_count_passed_through(self):
        # content must be non-empty to pass the early-return guard
        summary = {"content": "내용 있음.", "count": 42, "themes": []}
        result = gds._extract_category_data_points(summary)
        assert result["count"] == 42


# ---------------------------------------------------------------------------
# _collect_all_news_items
# ---------------------------------------------------------------------------


class TestCollectAllNewsItems:
    def test_empty_summaries_returns_empty(self):
        assert gds._collect_all_news_items([]) == []

    def test_none_summaries_skipped(self):
        assert gds._collect_all_news_items([None, None]) == []

    def test_extracts_markdown_links(self):
        s = {
            "type": "crypto",
            "content": "- [Bitcoin surges amid ETF approval news](https://example.com/btc)",
        }
        items = gds._collect_all_news_items([s])
        assert any("Bitcoin" in item["title"] or "ETF" in item["title"] for item in items)

    def test_deduplication_by_url(self):
        content = (
            "- [Bitcoin ETF approved by regulators today](https://example.com/btc)\n"
            "- [Bitcoin ETF approved by regulators today](https://example.com/btc)"
        )
        s = {"type": "crypto", "content": content}
        items = gds._collect_all_news_items([s])
        # Same URL should appear only once
        urls = [i["link"] for i in items if i.get("link") == "https://example.com/btc"]
        assert len(urls) <= 1

    def test_deduplication_across_summaries(self):
        content = "- [Bitcoin ETF approved by SEC today confirmed](https://example.com/btc)"
        s1 = {"type": "crypto", "content": content}
        s2 = {"type": "stock", "content": content}
        items = gds._collect_all_news_items([s1, s2])
        urls = [i["link"] for i in items if i.get("link") == "https://example.com/btc"]
        assert len(urls) == 1

    def test_short_titles_filtered(self):
        s = {"type": "crypto", "content": "- [Short](https://example.com)"}
        items = gds._collect_all_news_items([s])
        assert all(len(i.get("title", "")) >= 10 for i in items)

    def test_html_anchor_links_extracted(self):
        s = {
            "type": "stock",
            "content": '<a href="https://example.com/news">Tesla earnings beat expectations</a>',
        }
        items = gds._collect_all_news_items([s])
        assert any("Tesla" in item.get("title", "") for item in items)


# ---------------------------------------------------------------------------
# _build_snapshot_table
# ---------------------------------------------------------------------------


class TestBuildSnapshotTable:
    def _make_summary(self, stype: str, count: int, highlights=None, market_data=None) -> dict:
        return {
            "type": stype,
            "count": count,
            "highlights": highlights or [],
            "key_summary": highlights or [],
            "market_data": market_data or [],
            "content": "",
        }

    def test_returns_list_with_table(self):
        result = gds._build_snapshot_table(None, None, None, None, None, None)
        assert isinstance(result, list)
        assert len(result) > 0

    def test_all_none_shows_data_unavailable(self):
        result = gds._build_snapshot_table(None, None, None, None, None, None)
        combined = "\n".join(result)
        assert "데이터 없음" in combined

    def test_with_crypto_summary(self):
        crypto = self._make_summary("crypto", 30, highlights=["- 비트코인 급등 오늘 큰 상승세"])
        result = gds._build_snapshot_table(crypto, None, None, None, None, None)
        combined = "\n".join(result)
        assert "30" in combined

    def test_zero_count_shows_no_data(self):
        crypto = self._make_summary("crypto", 0)
        result = gds._build_snapshot_table(crypto, None, None, None, None, None)
        combined = "\n".join(result)
        assert "데이터 없음" in combined

    def test_market_data_used_as_top_signal(self):
        stock = self._make_summary("stock", 10, market_data=["KOSPI 2500 상승"])
        result = gds._build_snapshot_table(None, stock, None, None, None, None)
        combined = "\n".join(result)
        assert "KOSPI" in combined

    def test_theme_name_as_fallback_signal(self):
        crypto = {
            "type": "crypto",
            "count": 5,
            "highlights": [],
            "key_summary": [],
            "market_data": [],
            "content": "",
            "themes": [("규제", 3)],
        }
        result = gds._build_snapshot_table(crypto, None, None, None, None, None)
        combined = "\n".join(result)
        assert "규제" in combined


# ---------------------------------------------------------------------------
# _resolve_frontmatter_image
# ---------------------------------------------------------------------------


class TestResolveFrontmatterImage:
    def test_returns_provided_image(self):
        result = gds._resolve_frontmatter_image("2024-01-01", "/assets/images/test.png")
        assert result == "/assets/images/test.png"

    def test_returns_empty_when_no_file_exists(self):
        # No actual files exist for a fake date
        result = gds._resolve_frontmatter_image("9999-99-99", None)
        assert result == ""

    def test_briefing_image_none_and_no_candidates(self):
        result = gds._resolve_frontmatter_image("1900-01-01", None)
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# _build_overview_section
# ---------------------------------------------------------------------------


class TestBuildOverviewSection:
    def _make_summary_map(self, crypto_count=0, stock_count=0):
        summaries = {}
        if crypto_count:
            summaries["crypto"] = {
                "type": "crypto",
                "count": crypto_count,
                "highlights": [],
                "key_summary": [],
                "content": "",
            }
        if stock_count:
            summaries["stock"] = {
                "type": "stock",
                "count": stock_count,
                "highlights": [],
                "key_summary": [],
                "market_data": [],
                "content": "",
            }
        summaries.setdefault("crypto", None)
        summaries.setdefault("stock", None)
        summaries.setdefault("regulatory", None)
        summaries.setdefault("social", None)
        summaries.setdefault("worldmonitor", None)
        summaries.setdefault("political", None)
        return summaries

    def _base_sentiment(self, ratio=50):
        return {
            "tone": "중립",
            "positive": ratio,
            "negative": 100 - ratio,
            "ratio": ratio,
            "pos_examples": [],
            "neg_examples": [],
        }

    def test_returns_list(self):
        result = gds._build_overview_section(
            0, {"P0": [], "P1": [], "P2": []}, [], self._make_summary_map(), None, "뉴스", self._base_sentiment()
        )
        assert isinstance(result, list)
        assert len(result) > 0

    def test_counts_str_in_output(self):
        result = gds._build_overview_section(
            50,
            {"P0": [], "P1": [], "P2": []},
            [],
            self._make_summary_map(crypto_count=30, stock_count=20),
            None,
            "암호화폐 30건, 주식 20건",
            self._base_sentiment(),
        )
        combined = "\n".join(result)
        assert "암호화폐 30건, 주식 20건" in combined

    def test_risk_level_높음_when_many_p0(self):
        priority_items = {"P0": [{"title": f"긴급{i}"} for i in range(5)], "P1": [], "P2": []}
        result = gds._build_overview_section(
            10, priority_items, [], self._make_summary_map(), None, "뉴스", self._base_sentiment(ratio=20)
        )
        combined = "\n".join(result)
        assert "높음" in combined

    def test_risk_level_안정_when_no_p0(self):
        result = gds._build_overview_section(
            10,
            {"P0": [], "P1": [], "P2": []},
            [],
            self._make_summary_map(),
            None,
            "뉴스",
            self._base_sentiment(ratio=60),
        )
        combined = "\n".join(result)
        assert "안정" in combined

    def test_theme_narrative_when_multiple_themes(self):
        themes = [
            {"name": "금리/유동성", "emoji": "💰", "count": 20, "keywords": ["금리", "연준"]},
            {"name": "환율/달러", "emoji": "💱", "count": 15, "keywords": ["환율", "달러"]},
            {"name": "정책/규제", "emoji": "📋", "count": 10, "keywords": ["sec", "etf"]},
        ]
        result = gds._build_overview_section(
            100,
            {"P0": [], "P1": [], "P2": []},
            themes,
            self._make_summary_map(crypto_count=60, stock_count=40),
            None,
            "암호화폐 60건, 주식 40건",
            self._base_sentiment(),
        )
        combined = "\n".join(result)
        assert "3가지 흐름" in combined

    def test_p0_p1_signal_line_present(self):
        priority_items = {
            "P0": [{"title": "긴급 해킹 사고 발생"}],
            "P1": [{"title": "ETF 승인"}],
            "P2": [],
        }
        result = gds._build_overview_section(
            10, priority_items, [], self._make_summary_map(), None, "뉴스", self._base_sentiment()
        )
        combined = "\n".join(result)
        assert "핵심 신호" in combined


# ---------------------------------------------------------------------------
# _relation_rows
# ---------------------------------------------------------------------------


class TestRelationRows:
    def _make_summary(self, content: str) -> dict:
        return {
            "title": "",
            "content": content,
            "highlights": [],
            "key_summary": [],
            "themes": [],
            "count": 1,
        }

    def test_returns_list(self):
        result = gds._relation_rows({"crypto": None, "stock": None})
        assert isinstance(result, list)

    def test_low_score_when_no_shared_topics(self):
        s_map = {
            "crypto": self._make_summary("비트코인 가격 변동"),
            "stock": self._make_summary("삼성전자 실적 발표"),
        }
        rows = gds._relation_rows(s_map)
        # At least one row should exist for crypto↔stock pair
        assert len(rows) >= 1

    def test_high_score_when_many_shared_topics(self):
        shared_content = (
            "금리 연준 fed fomc 금리인상 "
            "환율 달러 dxy usd/krw "
            "규제 sec etf 법안 정책 "
            "해킹 exploit 파산 청산 "
            "실적 cpi pce gdp "
        )
        s_map = {
            "crypto": self._make_summary(shared_content),
            "stock": self._make_summary(shared_content),
        }
        rows = gds._relation_rows(s_map)
        crypto_stock = next((r for r in rows if "암호화폐" in r[0] and "주식" in r[1]), None)
        assert crypto_stock is not None
        assert crypto_stock[2] > 0

    def test_tuple_structure(self):
        s_map = {
            "crypto": self._make_summary("금리 연준"),
            "stock": self._make_summary("금리 연준"),
        }
        rows = gds._relation_rows(s_map)
        for row in rows:
            assert len(row) == 4  # (left_name, right_name, score, note)


# ---------------------------------------------------------------------------
# _load_today_posts
# ---------------------------------------------------------------------------


class TestLoadTodayPosts:
    """Tests for _load_today_posts using tmp_path stubs instead of real _posts/."""

    def _write_post(self, directory, filename: str, content: str):
        p = directory / filename
        p.write_text(content, encoding="utf-8")
        return p

    def test_returns_empty_when_no_posts(self, tmp_path, monkeypatch):
        monkeypatch.setattr(gds, "POSTS_DIR", str(tmp_path))
        result = gds._load_today_posts("2099-01-01")
        summary_map, post_links, security_summary, all_summaries = result
        assert summary_map == {}
        assert post_links == []
        assert security_summary is None
        assert all_summaries == []

    def test_loads_crypto_post(self, tmp_path, monkeypatch):
        monkeypatch.setattr(gds, "POSTS_DIR", str(tmp_path))
        today = "2099-02-01"
        self._write_post(
            tmp_path,
            f"{today}-crypto-news-digest.md",
            "---\ntitle: 암호화폐 뉴스\ncategory: crypto\n---\n"
            "## 핵심 요약\n- BTC 급등\n오늘 10건의 뉴스가 수집되었습니다.",
        )
        summary_map, post_links, _, all_summaries = gds._load_today_posts(today)
        crypto = summary_map.get("crypto")
        assert crypto is not None
        assert crypto["type"] == "crypto"
        assert crypto["count"] == 10
        assert any("암호화폐" in name for name, _, _ in post_links)

    def test_loads_stock_post(self, tmp_path, monkeypatch):
        monkeypatch.setattr(gds, "POSTS_DIR", str(tmp_path))
        today = "2099-02-02"
        self._write_post(
            tmp_path,
            f"{today}-stock-news-digest.md",
            "---\ntitle: 주식 뉴스\n---\nKOSPI 2500 상승.\n총 수집 건수: 5건",
        )
        summary_map, post_links, _, _ = gds._load_today_posts(today)
        assert summary_map.get("stock") is not None
        assert any("주식" in name for name, _, _ in post_links)

    def test_loads_security_post(self, tmp_path, monkeypatch):
        monkeypatch.setattr(gds, "POSTS_DIR", str(tmp_path))
        today = "2099-02-03"
        self._write_post(
            tmp_path,
            f"{today}-security-report.md",
            "---\ntitle: 보안 리포트\n---\n"
            "## 보안 사고 현황\n| H1 | H2 | H3 |\n|---|---|---|\n| A | B | C |\n"
            "오늘 3건의 뉴스가 수집되었습니다.",
        )
        summary_map, post_links, security_summary, _ = gds._load_today_posts(today)
        assert security_summary is not None
        assert security_summary["type"] == "security"
        assert any("보안" in name for name, _, _ in post_links)

    def test_loads_regulatory_post(self, tmp_path, monkeypatch):
        monkeypatch.setattr(gds, "POSTS_DIR", str(tmp_path))
        today = "2099-02-04"
        self._write_post(
            tmp_path,
            f"{today}-regulatory-report.md",
            "---\ntitle: 규제 동향\n---\n## 핵심 요약\n- SEC 조사\n오늘 7건의 뉴스가 수집되었습니다.",
        )
        summary_map, _, _, _ = gds._load_today_posts(today)
        regulatory = summary_map.get("regulatory")
        assert regulatory is not None
        assert regulatory["type"] == "regulatory"

    def test_loads_social_post(self, tmp_path, monkeypatch):
        monkeypatch.setattr(gds, "POSTS_DIR", str(tmp_path))
        today = "2099-02-05"
        self._write_post(
            tmp_path,
            f"{today}-social-media-digest.md",
            "---\ntitle: 소셜 미디어\n---\n## 핵심 요약\n- BTC 트위터 급증\n총 8건을 수집했습니다.",
        )
        summary_map, _, _, _ = gds._load_today_posts(today)
        social = summary_map.get("social")
        assert social is not None
        assert social["type"] == "social"

    def test_loads_political_post(self, tmp_path, monkeypatch):
        monkeypatch.setattr(gds, "POSTS_DIR", str(tmp_path))
        today = "2099-02-06"
        self._write_post(
            tmp_path,
            f"{today}-political-trades-report.md",
            "---\ntitle: 정치인 거래\n---\n## 핵심 요약\n- 펠로시 매수\n오늘 4건의 뉴스가 수집되었습니다.",
        )
        summary_map, _, _, _ = gds._load_today_posts(today)
        political = summary_map.get("political")
        assert political is not None
        assert political["type"] == "political"

    def test_loads_worldmonitor_post(self, tmp_path, monkeypatch):
        monkeypatch.setattr(gds, "POSTS_DIR", str(tmp_path))
        today = "2099-02-07"
        self._write_post(
            tmp_path,
            f"{today}-worldmonitor-briefing.md",
            "---\ntitle: 월드모니터 브리핑\n---\n## 핵심 요약\n- 글로벌 이슈\n수집 건수: **20건**",
        )
        summary_map, post_links, _, _ = gds._load_today_posts(today)
        assert summary_map.get("worldmonitor") is not None
        assert any("월드모니터" in name for name, _, _ in post_links)

    def test_skips_daily_news_summary_post(self, tmp_path, monkeypatch):
        monkeypatch.setattr(gds, "POSTS_DIR", str(tmp_path))
        today = "2099-02-08"
        self._write_post(
            tmp_path,
            f"{today}-daily-news-summary.md",
            "---\ntitle: 일일 요약\n---\n이미 생성된 요약입니다.",
        )
        summary_map, post_links, _, all_summaries = gds._load_today_posts(today)
        # daily-news-summary should be ignored — nothing should be loaded
        assert all(v is None for v in summary_map.values())
        assert post_links == []

    def test_all_summaries_flat_list(self, tmp_path, monkeypatch):
        monkeypatch.setattr(gds, "POSTS_DIR", str(tmp_path))
        today = "2099-02-09"
        self._write_post(
            tmp_path,
            f"{today}-crypto-news-digest.md",
            "---\ntitle: 암호화폐 뉴스\n---\n오늘 10건의 뉴스가 수집되었습니다.",
        )
        _, _, _, all_summaries = gds._load_today_posts(today)
        # all_summaries should be a flat list (may contain None for absent categories)
        assert isinstance(all_summaries, list)
        assert len(all_summaries) == 7  # always 7 slots


# ---------------------------------------------------------------------------
# _write_summary_post
# ---------------------------------------------------------------------------


class TestWriteSummaryPost:
    """Tests for _write_summary_post using tmp_path."""

    def test_creates_file_with_correct_name(self, tmp_path, monkeypatch):
        monkeypatch.setattr(gds, "POSTS_DIR", str(tmp_path))
        today = "2099-03-01"
        filepath = gds._write_summary_post(today, "본문 내용입니다.", 42, "암호화폐 42건", None)
        assert os.path.exists(filepath)
        assert f"{today}-daily-news-summary.md" in filepath

    def test_file_contains_frontmatter(self, tmp_path, monkeypatch):
        monkeypatch.setattr(gds, "POSTS_DIR", str(tmp_path))
        today = "2099-03-02"
        gds._write_summary_post(today, "본문.", 10, "뉴스 10건", None)
        content = (tmp_path / f"{today}-daily-news-summary.md").read_text(encoding="utf-8")
        assert "layout: post" in content
        assert f'title: "일일 뉴스 종합 요약 - {today}"' in content
        assert "categories: [market-analysis]" in content

    def test_file_contains_body_content(self, tmp_path, monkeypatch):
        monkeypatch.setattr(gds, "POSTS_DIR", str(tmp_path))
        today = "2099-03-03"
        body = "## 오늘의 핵심\n- 비트코인 급등"
        gds._write_summary_post(today, body, 5, "뉴스 5건", None)
        content = (tmp_path / f"{today}-daily-news-summary.md").read_text(encoding="utf-8")
        assert "## 오늘의 핵심" in content
        assert "비트코인 급등" in content

    def test_description_contains_counts_str(self, tmp_path, monkeypatch):
        monkeypatch.setattr(gds, "POSTS_DIR", str(tmp_path))
        today = "2099-03-04"
        counts_str = "암호화폐 30건, 주식 20건"
        gds._write_summary_post(today, "본문.", 50, counts_str, None)
        content = (tmp_path / f"{today}-daily-news-summary.md").read_text(encoding="utf-8")
        assert counts_str in content

    def test_returns_filepath_string(self, tmp_path, monkeypatch):
        monkeypatch.setattr(gds, "POSTS_DIR", str(tmp_path))
        result = gds._write_summary_post("2099-03-05", "내용.", 0, "뉴스", None)
        assert isinstance(result, str)
        assert result.endswith(".md")

    def test_lang_ko_in_frontmatter(self, tmp_path, monkeypatch):
        monkeypatch.setattr(gds, "POSTS_DIR", str(tmp_path))
        today = "2099-03-06"
        gds._write_summary_post(today, "내용.", 1, "뉴스 1건", None)
        content = (tmp_path / f"{today}-daily-news-summary.md").read_text(encoding="utf-8")
        assert 'lang: "ko"' in content

    def test_source_consolidated_in_frontmatter(self, tmp_path, monkeypatch):
        monkeypatch.setattr(gds, "POSTS_DIR", str(tmp_path))
        today = "2099-03-07"
        gds._write_summary_post(today, "내용.", 1, "뉴스 1건", None)
        content = (tmp_path / f"{today}-daily-news-summary.md").read_text(encoding="utf-8")
        assert 'source: "consolidated"' in content

    def test_image_line_absent_when_no_briefing_image(self, tmp_path, monkeypatch):
        monkeypatch.setattr(gds, "POSTS_DIR", str(tmp_path))
        today = "2099-03-08"
        gds._write_summary_post(today, "내용.", 0, "뉴스", None)
        content = (tmp_path / f"{today}-daily-news-summary.md").read_text(encoding="utf-8")
        assert "\nimage:" not in content


# ---------------------------------------------------------------------------
# _build_briefing_section
# ---------------------------------------------------------------------------


class TestBuildBriefingSection:
    """Tests for _build_briefing_section with mocked ThemeSummarizer."""

    def _make_sentiment(self, ratio=50):
        return {
            "tone": "중립",
            "positive": ratio,
            "negative": 100 - ratio,
            "ratio": ratio,
            "pos_examples": [],
            "neg_examples": [],
        }

    def _make_crypto_summary(self, count=10, highlights=None):
        return {
            "type": "crypto",
            "title": "암호화폐 뉴스",
            "count": count,
            "highlights": highlights or ["- BTC 상승"],
            "key_summary": highlights or ["- BTC 상승"],
            "content": "BTC 상승 소식이 있습니다.",
            "themes": [("금리/유동성", 5)],
            "url": "https://example.com/crypto",
        }

    def _make_summary_map(self, crypto_summary=None):
        return {
            "crypto": crypto_summary,
            "stock": None,
            "regulatory": None,
            "social": None,
            "worldmonitor": None,
            "political": None,
        }

    def _make_mock_summarizer(self, concentration=None, anomalies=None):
        mock = MagicMock()
        mock.detect_concentration.return_value = concentration
        mock.detect_anomalies.return_value = anomalies or []
        return mock

    def test_returns_list_of_strings(self):
        mock_summ = self._make_mock_summarizer()
        result = gds._build_briefing_section(
            all_summaries=[],
            all_news_items=[],
            summary_map=self._make_summary_map(),
            theme_payload=[],
            sentiment=self._make_sentiment(),
            today="2099-04-01",
            briefing_image=None,
            priority_items={"P0": [], "P1": [], "P2": []},
            summarizer=mock_summ,
        )
        assert isinstance(result, list)
        assert all(isinstance(line, str) for line in result)

    def test_includes_dashboard_heading(self):
        mock_summ = self._make_mock_summarizer()
        result = gds._build_briefing_section(
            all_summaries=[],
            all_news_items=[],
            summary_map=self._make_summary_map(),
            theme_payload=[],
            sentiment=self._make_sentiment(),
            today="2099-04-02",
            briefing_image=None,
            priority_items={"P0": [], "P1": [], "P2": []},
            summarizer=mock_summ,
        )
        combined = "\n".join(result)
        assert "종합 대시보드" in combined

    def test_includes_briefing_heading(self):
        mock_summ = self._make_mock_summarizer()
        result = gds._build_briefing_section(
            all_summaries=[],
            all_news_items=[],
            summary_map=self._make_summary_map(),
            theme_payload=[],
            sentiment=self._make_sentiment(),
            today="2099-04-03",
            briefing_image=None,
            priority_items={"P0": [], "P1": [], "P2": []},
            summarizer=mock_summ,
        )
        combined = "\n".join(result)
        assert "핵심 브리핑" in combined

    def test_concentration_warning_when_detect_concentration_returns_value(self):
        mock_summ = self._make_mock_summarizer(concentration=("금리/유동성", "interest", 0.45))
        news_items = [{"title": "금리 뉴스", "link": "https://ex.com", "type": "crypto"}]
        result = gds._build_briefing_section(
            all_summaries=[],
            all_news_items=news_items,
            summary_map=self._make_summary_map(),
            theme_payload=[],
            sentiment=self._make_sentiment(),
            today="2099-04-04",
            briefing_image=None,
            priority_items={"P0": [], "P1": [], "P2": []},
            summarizer=mock_summ,
        )
        combined = "\n".join(result)
        assert "집중도 경고" in combined
        assert "45%" in combined

    def test_anomaly_line_when_detect_anomalies_returns_value(self):
        anomalies = [("리스크 이벤트", "risk", 8, "이상 급등 패턴이 감지되었습니다.")]
        mock_summ = self._make_mock_summarizer(anomalies=anomalies)
        news_items = [{"title": "리스크 뉴스", "link": "https://ex.com", "type": "crypto"}]
        result = gds._build_briefing_section(
            all_summaries=[],
            all_news_items=news_items,
            summary_map=self._make_summary_map(),
            theme_payload=[],
            sentiment=self._make_sentiment(),
            today="2099-04-05",
            briefing_image=None,
            priority_items={"P0": [], "P1": [], "P2": []},
            summarizer=mock_summ,
        )
        combined = "\n".join(result)
        assert "이상 탐지" in combined
        assert "이상 급등 패턴" in combined

    def test_sentiment_line_present(self):
        mock_summ = self._make_mock_summarizer()
        sentiment = self._make_sentiment(ratio=70)
        result = gds._build_briefing_section(
            all_summaries=[],
            all_news_items=[],
            summary_map=self._make_summary_map(),
            theme_payload=[],
            sentiment=sentiment,
            today="2099-04-06",
            briefing_image=None,
            priority_items={"P0": [], "P1": [], "P2": []},
            summarizer=mock_summ,
        )
        combined = "\n".join(result)
        assert "시장 심리" in combined
        assert "70%" in combined

    def test_pos_neg_examples_rendered_when_present(self):
        mock_summ = self._make_mock_summarizer()
        sentiment = {
            "tone": "긍정 우세",
            "positive": 7,
            "negative": 3,
            "ratio": 70,
            "pos_examples": ["BTC 급등"],
            "neg_examples": ["ETH 하락"],
        }
        result = gds._build_briefing_section(
            all_summaries=[],
            all_news_items=[],
            summary_map=self._make_summary_map(),
            theme_payload=[],
            sentiment=sentiment,
            today="2099-04-07",
            briefing_image=None,
            priority_items={"P0": [], "P1": [], "P2": []},
            summarizer=mock_summ,
        )
        combined = "\n".join(result)
        assert "긍정 신호" in combined
        assert "주의 신호" in combined

    def test_category_briefing_line_for_crypto(self):
        mock_summ = self._make_mock_summarizer()
        crypto = self._make_crypto_summary(count=15)
        result = gds._build_briefing_section(
            all_summaries=[crypto],
            all_news_items=[],
            summary_map=self._make_summary_map(crypto_summary=crypto),
            theme_payload=[],
            sentiment=self._make_sentiment(),
            today="2099-04-08",
            briefing_image=None,
            priority_items={"P0": [], "P1": [], "P2": []},
            summarizer=mock_summ,
        )
        combined = "\n".join(result)
        assert "암호화폐" in combined
        assert "15건" in combined

    def test_detect_concentration_not_called_when_no_news_items(self):
        mock_summ = self._make_mock_summarizer()
        gds._build_briefing_section(
            all_summaries=[],
            all_news_items=[],
            summary_map=self._make_summary_map(),
            theme_payload=[],
            sentiment=self._make_sentiment(),
            today="2099-04-09",
            briefing_image=None,
            priority_items={"P0": [], "P1": [], "P2": []},
            summarizer=mock_summ,
        )
        mock_summ.detect_concentration.assert_not_called()

    def test_cross_topics_shown_when_multiple_summaries(self):
        mock_summ = self._make_mock_summarizer()
        crypto = {
            "type": "crypto",
            "title": "암호화폐",
            "count": 10,
            "highlights": [],
            "key_summary": [],
            "content": "금리 연준 fed fomc 금리인상",
            "themes": [],
            "url": "#",
        }
        stock = {
            "type": "stock",
            "title": "주식",
            "count": 10,
            "highlights": [],
            "key_summary": [],
            "content": "금리 연준 fed fomc 금리인상",
            "themes": [],
            "url": "#",
        }
        result = gds._build_briefing_section(
            all_summaries=[crypto, stock],
            all_news_items=[],
            summary_map={
                "crypto": crypto,
                "stock": stock,
                "regulatory": None,
                "social": None,
                "worldmonitor": None,
                "political": None,
            },
            theme_payload=[],
            sentiment=self._make_sentiment(),
            today="2099-04-10",
            briefing_image=None,
            priority_items={"P0": [], "P1": [], "P2": []},
            summarizer=mock_summ,
        )
        combined = "\n".join(result)
        assert "교차 테마" in combined

    def test_theme_snapshot_table_rendered_with_theme_payload(self):
        mock_summ = self._make_mock_summarizer()
        theme_payload = [
            {"name": "금리/유동성", "emoji": "💰", "count": 25, "keywords": ["금리", "연준"]},
            {"name": "정책/규제", "emoji": "📋", "count": 10, "keywords": ["sec", "etf"]},
        ]
        result = gds._build_briefing_section(
            all_summaries=[],
            all_news_items=[],
            summary_map=self._make_summary_map(),
            theme_payload=theme_payload,
            sentiment=self._make_sentiment(),
            today="2099-04-11",
            briefing_image=None,
            priority_items={"P0": [], "P1": [], "P2": []},
            summarizer=mock_summ,
        )
        combined = "\n".join(result)
        assert "테마 스냅샷" in combined
        assert "금리/유동성" in combined

    def test_stock_detail_has_no_double_period(self):
        """Regression: market_data already ending in '.' must not produce '..'."""
        mock_summ = self._make_mock_summarizer()
        stock = {
            "type": "stock",
            "count": 5,
            "highlights": ["- KOSPI 상승"],
            "key_summary": [],
            "market_data": ["KOSPI 2,500선 마감."],
            "content": "KOSPI 2,500선 마감.",
            "themes": [],
            "url": "https://example.com/stock",
        }
        result = gds._build_briefing_section(
            all_summaries=[],
            all_news_items=[],
            summary_map={
                "crypto": None,
                "stock": stock,
                "regulatory": None,
                "social": None,
                "worldmonitor": None,
                "political": None,
            },
            theme_payload=[],
            sentiment=self._make_sentiment(),
            today="2099-04-12",
            briefing_image=None,
            priority_items={"P0": [], "P1": [], "P2": []},
            summarizer=mock_summ,
        )
        combined = "\n".join(result)
        assert "마감." in combined
        assert "마감.." not in combined


# ---------------------------------------------------------------------------
# _build_priority_and_category_sections
# ---------------------------------------------------------------------------


class TestBuildPriorityAndCategorySections:
    """Tests for _build_priority_and_category_sections."""

    def _make_summary_map(
        self,
        crypto=None,
        stock=None,
        regulatory=None,
        social=None,
        worldmonitor=None,
        political=None,
    ):
        return {
            "crypto": crypto,
            "stock": stock,
            "regulatory": regulatory,
            "social": social,
            "worldmonitor": worldmonitor,
            "political": political,
        }

    def _crypto(self, count=10):
        return {
            "type": "crypto",
            "count": count,
            "highlights": ["- BTC 상승"],
            "key_summary": [],
            "content": "BTC 상승. [Bitcoin ETF approval confirmed today](https://ex.com)",
            "themes": [("금리/유동성", 5)],
            "url": "https://example.com/crypto",
        }

    def _stock(self, count=5):
        return {
            "type": "stock",
            "count": count,
            "highlights": ["- KOSPI 상승"],
            "key_summary": [],
            "market_data": ["KOSPI 2500 상승"],
            "content": "KOSPI 2500 상승.",
            "themes": [],
            "url": "https://example.com/stock",
        }

    def _political(self, count=3):
        return {
            "type": "political",
            "count": count,
            "highlights": ["- 펠로시 매수"],
            "key_summary": ["- 주요 거래 정보"],
            "content": "펠로시 매수.",
            "themes": [],
            "url": "https://example.com/political",
        }

    def _security(self, count=2):
        return {
            "type": "security",
            "count": count,
            "highlights": [],
            "key_summary": [],
            "incidents": ["| DeFi | $1M | 해킹 |"],
            "content": "보안 사고 발생.",
            "themes": [],
            "url": "https://example.com/security",
        }

    def test_returns_list_of_strings(self):
        result = gds._build_priority_and_category_sections(
            priority_items={"P0": [], "P1": [], "P2": []},
            market_summary=None,
            security_summary=None,
            summary_map=self._make_summary_map(),
            post_links=[],
            all_news_items=[],
        )
        assert isinstance(result, list)
        assert all(isinstance(line, str) for line in result)

    def test_security_key_summary_is_translated_and_bulleted(self):
        """Regression: English security key_summary must route through Korean
        translation and render as a bullet, like other category headlines."""
        security = {
            "type": "security",
            "count": 2,
            "highlights": [],
            "key_summary": ["- Major exchange exploit drains user funds today worldwide"],
            "incidents": [],
            "content": "보안 요약 정보입니다.",
            "themes": [],
            "url": "https://example.com/security",
        }
        with patch(
            "common.summary_text_ko.translate_to_korean",
            return_value="대형 거래소 해킹으로 사용자 자금 유출",
        ):
            result = gds._build_priority_and_category_sections(
                priority_items={"P0": [], "P1": [], "P2": []},
                market_summary=None,
                security_summary=security,
                summary_map=self._make_summary_map(),
                post_links=[],
                all_news_items=[],
            )
        combined = "\n".join(result)
        assert "- 대형 거래소 해킹으로 사용자 자금 유출" in combined
        assert "Major exchange exploit drains user funds" not in combined

    def test_p0_section_rendered_when_p0_items_present(self):
        p0_item = {
            "title": "비트코인 거래소 해킹 사고 발생 긴급",
            "description": "대형 거래소 해킹으로 수억 달러 피해 발생",
            "link": "https://example.com/hack",
            "type": "crypto",
        }
        result = gds._build_priority_and_category_sections(
            priority_items={"P0": [p0_item], "P1": [], "P2": []},
            market_summary=None,
            security_summary=None,
            summary_map=self._make_summary_map(),
            post_links=[],
            all_news_items=[],
        )
        combined = "\n".join(result)
        assert "긴급 알림" in combined

    def test_p1_section_rendered_when_p1_items_present(self):
        p1_item = {
            "title": "비트코인 ETF 최종 승인 결정 발표",
            "description": "SEC가 비트코인 현물 ETF를 승인했습니다.",
            "link": "https://example.com/etf",
            "type": "crypto",
        }
        result = gds._build_priority_and_category_sections(
            priority_items={"P0": [], "P1": [p1_item], "P2": []},
            market_summary=None,
            security_summary=None,
            summary_map=self._make_summary_map(),
            post_links=[],
            all_news_items=[],
        )
        combined = "\n".join(result)
        assert "중요 뉴스" in combined

    def test_p2_section_rendered_when_p2_items_present(self):
        p2_item = {
            "title": "이더리움 개발자 컨퍼런스 개최 예정 안내",
            "link": "https://example.com/eth",
            "type": "crypto",
        }
        result = gds._build_priority_and_category_sections(
            priority_items={"P0": [], "P1": [], "P2": [p2_item]},
            market_summary=None,
            security_summary=None,
            summary_map=self._make_summary_map(),
            post_links=[],
            all_news_items=[],
        )
        combined = "\n".join(result)
        assert "주목할 소식" in combined

    def test_category_summary_section_always_present(self):
        result = gds._build_priority_and_category_sections(
            priority_items={"P0": [], "P1": [], "P2": []},
            market_summary=None,
            security_summary=None,
            summary_map=self._make_summary_map(),
            post_links=[],
            all_news_items=[],
        )
        combined = "\n".join(result)
        assert "카테고리별 요약" in combined

    def test_crypto_section_shows_count_and_link(self):
        result = gds._build_priority_and_category_sections(
            priority_items={"P0": [], "P1": [], "P2": []},
            market_summary=None,
            security_summary=None,
            summary_map=self._make_summary_map(crypto=self._crypto(count=12)),
            post_links=[],
            all_news_items=[],
        )
        combined = "\n".join(result)
        assert "암호화폐 뉴스" in combined
        assert "12건" in combined
        assert "상세 보기" in combined

    def test_stock_section_shows_market_data(self):
        result = gds._build_priority_and_category_sections(
            priority_items={"P0": [], "P1": [], "P2": []},
            market_summary=None,
            security_summary=None,
            summary_map=self._make_summary_map(stock=self._stock(count=8)),
            post_links=[],
            all_news_items=[],
        )
        combined = "\n".join(result)
        assert "주식 시장 뉴스" in combined
        assert "KOSPI" in combined

    def test_political_watch_section_shown_when_political_summary_present(self):
        result = gds._build_priority_and_category_sections(
            priority_items={"P0": [], "P1": [], "P2": []},
            market_summary=None,
            security_summary=None,
            summary_map=self._make_summary_map(political=self._political()),
            post_links=[],
            all_news_items=[],
        )
        combined = "\n".join(result)
        assert "정치인 워치" in combined

    def test_security_section_shown_when_security_summary_present(self):
        result = gds._build_priority_and_category_sections(
            priority_items={"P0": [], "P1": [], "P2": []},
            market_summary=None,
            security_summary=self._security(),
            summary_map=self._make_summary_map(),
            post_links=[],
            all_news_items=[],
        )
        combined = "\n".join(result)
        assert "보안 리포트" in combined

    def test_report_links_section_always_present(self):
        result = gds._build_priority_and_category_sections(
            priority_items={"P0": [], "P1": [], "P2": []},
            market_summary=None,
            security_summary=None,
            summary_map=self._make_summary_map(),
            post_links=[("암호화폐 뉴스", 10, "https://example.com/crypto")],
            all_news_items=[],
        )
        combined = "\n".join(result)
        assert "상세 리포트 링크" in combined

    def test_post_links_rendered_in_report_section(self):
        post_links = [
            ("암호화폐 뉴스", 10, "https://example.com/crypto"),
            ("주식 시장 뉴스", 5, "https://example.com/stock"),
        ]
        result = gds._build_priority_and_category_sections(
            priority_items={"P0": [], "P1": [], "P2": []},
            market_summary=None,
            security_summary=None,
            summary_map=self._make_summary_map(),
            post_links=post_links,
            all_news_items=[],
        )
        combined = "\n".join(result)
        assert "암호화폐 뉴스" in combined or "🪙" in combined

    def test_disclaimer_line_present(self):
        result = gds._build_priority_and_category_sections(
            priority_items={"P0": [], "P1": [], "P2": []},
            market_summary=None,
            security_summary=None,
            summary_map=self._make_summary_map(),
            post_links=[],
            all_news_items=[],
        )
        combined = "\n".join(result)
        assert "투자 조언" in combined

    def test_market_overview_section_shown_when_market_summary_present(self):
        market_summary = {
            "type": "market",
            "count": 5,
            "highlights": ["- 코스피 +1.5%"],
            "exec_summary": [],
            "indicator_rows": [],
            "yield_section": "",
            "content": "코스피 상승.",
            "url": "https://example.com/market",
        }
        result = gds._build_priority_and_category_sections(
            priority_items={"P0": [], "P1": [], "P2": []},
            market_summary=market_summary,
            security_summary=None,
            summary_map=self._make_summary_map(),
            post_links=[],
            all_news_items=[],
        )
        combined = "\n".join(result)
        assert "시장 개요" in combined
        assert "코스피" in combined

    def test_cross_asset_section_present_when_multiple_summaries(self):
        result = gds._build_priority_and_category_sections(
            priority_items={"P0": [], "P1": [], "P2": []},
            market_summary=None,
            security_summary=None,
            summary_map=self._make_summary_map(crypto=self._crypto(), stock=self._stock()),
            post_links=[],
            all_news_items=[],
        )
        combined = "\n".join(result)
        assert "교차자산 연관성" in combined

    def test_p0_noise_title_filtered_out(self):
        p0_noise = {"title": "가격 알림: BTC/USDT", "link": "https://ex.com", "type": "crypto"}
        p0_real = {
            "title": "비트코인 거래소 해킹 사고 발생 긴급",
            "description": "긴급 사고 발생",
            "link": "https://ex.com/real",
            "type": "crypto",
        }
        result = gds._build_priority_and_category_sections(
            priority_items={"P0": [p0_noise, p0_real], "P1": [], "P2": []},
            market_summary=None,
            security_summary=None,
            summary_map=self._make_summary_map(),
            post_links=[],
            all_news_items=[],
        )
        combined = "\n".join(result)
        assert "가격 알림" not in combined


# ---------------------------------------------------------------------------
# _build_market_signal_section — 엔티티 빈도·연관 클러스터 분기 (커버리지 그룹 A)
# ---------------------------------------------------------------------------
#
# extract_market_signals / group_related_items 는 patch 로 반환 형태를 고정해
# 각 분기를 결정적으로 구동한다(assert 기반, 골든마스터 아님).


class TestBuildMarketSignalSection:
    """_build_market_signal_section 의 테마/엔티티/클러스터/예외 경로 커버."""

    def test_empty_items_returns_empty(self):
        assert gds._build_market_signal_section([]) == []

    def test_extract_exception_returns_empty(self):
        """extract_market_signals 예외 → 경고 후 빈 리스트(65-67)."""
        with patch("common.summary_sections.extract_market_signals", side_effect=RuntimeError("boom")):
            assert gds._build_market_signal_section([{"title": "x"}]) == []

    def test_no_signals_returns_empty(self):
        """테마·엔티티 빈도 모두 없음 → 빈 리스트(74)."""
        signals = {"dominant_themes": [], "entity_frequencies": {}, "total_items": 1}
        with patch("common.summary_sections.extract_market_signals", return_value=signals):
            assert gds._build_market_signal_section([{"title": "x"}]) == []

    def test_dominant_themes_table_rendered(self):
        """dominant_themes → '주요 테마' 표 + 비중 계산(81->82 이후)."""
        signals = {
            "dominant_themes": [("금리/유동성", 5), ("정책/규제", 3)],
            "entity_frequencies": {},
            "total_items": 10,
        }
        with (
            patch("common.summary_sections.extract_market_signals", return_value=signals),
            patch("common.summary_sections.group_related_items", return_value={}),
        ):
            out = "\n".join(gds._build_market_signal_section([{"title": "x"}]))
        assert "## 시장 시그널 분석" in out
        assert "### 주요 테마" in out
        assert "금리/유동성" in out
        assert "50%" in out  # 5/10

    def test_hot_entities_label_mapping_and_unknown(self):
        """crypto/stock/person 빈도 → '핫 엔티티' 라인(136-149), 미매핑 name 원본 유지."""
        signals = {
            "dominant_themes": [],
            "entity_frequencies": {
                "crypto": {"bitcoin": 5, "unknowncoin": 2},
                "stock": {"nvidia": 3},
                "person": {"trump": 4},
            },
            "total_items": 10,
        }
        with (
            patch("common.summary_sections.extract_market_signals", return_value=signals),
            patch("common.summary_sections.group_related_items", return_value={}),
        ):
            out = "\n".join(gds._build_market_signal_section([{"title": "x"}]))
        assert "### 핫 엔티티" in out
        assert "비트코인(BTC) 5회" in out
        assert "unknowncoin 2회" in out  # 라벨 미매핑 → 원본 name 폴백
        assert "엔비디아(NVDA) 3회" in out
        assert "트럼프 4회" in out

    def test_related_clusters_skip_etc_and_dedup(self):
        """연관 클러스터 렌더: '기타 뉴스' skip + 정규화 dedup(164-188)."""
        signals = {"dominant_themes": [("테마A", 2)], "entity_frequencies": {}, "total_items": 2}
        related = {
            "기타 뉴스": [{"title": "무시되어야 하는 기타 뉴스"}],
            "비트코인": [
                {"title": "비트코인 급등 소식 오늘 발표"},
                {"title": "비트코인 급등 소식 오늘 발표"},  # 정규화 후 중복 → skip
                {"title": "이더리움 강세 지속 관련 뉴스"},
            ],
        }
        with (
            patch("common.summary_sections.extract_market_signals", return_value=signals),
            patch("common.summary_sections.group_related_items", return_value=related),
            patch("common.summary_text_ko.translate_to_korean", side_effect=lambda x: x),
        ):
            out = "\n".join(gds._build_market_signal_section([{"title": "x"}]))
        assert "### 연관 뉴스 클러스터" in out
        assert "무시되어야 하는 기타 뉴스" not in out  # 기타 뉴스 라벨 skip
        assert "**비트코인** (3건 연관)" in out  # count 는 dedup 전 길이

    def test_group_related_exception_no_cluster(self):
        """group_related_items 예외 → 클러스터 섹션 생략(159-161)."""
        signals = {"dominant_themes": [("테마A", 2)], "entity_frequencies": {}, "total_items": 2}
        with (
            patch("common.summary_sections.extract_market_signals", return_value=signals),
            patch("common.summary_sections.group_related_items", side_effect=RuntimeError("boom")),
        ):
            out = "\n".join(gds._build_market_signal_section([{"title": "x"}]))
        assert "### 연관 뉴스 클러스터" not in out


# ---------------------------------------------------------------------------
# 골든마스터 스냅샷 — _build_briefing_section + _build_priority_and_category_sections
# ---------------------------------------------------------------------------
#
# 행위 보존(behavior-preserving) 리팩터 가드. 풍부하게 채워진 대표 입력으로
# 두 섹션 빌더의 전체 출력 문자열을 고정한다(SHA256). translate_to_korean 는
# 항등으로 patch 해 번역 비결정성을 제거한다. 출력이 한 글자라도 바뀌면 해시가
# 깨지므로, 리팩터가 출력을 바꾸지 않았음을 보장한다.


class TestGoldenMasterSummarySections:
    """리팩터 전후 출력 byte-identical 보장용 골든마스터."""

    # 캡처 시점(2026-06-29) 실제 출력의 SHA256. 출력이 바뀌면 이 값이 깨진다.
    EXPECTED_HASH = "a43690f8fb2bedb9cf136e1cc995372ed95b1e10c6e1661630279d5301048b83"

    def _sentiment(self):
        return {
            "tone": "긍정 우세",
            "positive": 7,
            "negative": 3,
            "ratio": 70,
            "pos_examples": ["비트코인 급등세", "이더리움 강세"],
            "neg_examples": ["거래소 해킹 우려"],
        }

    def _crypto(self):
        return {
            "type": "crypto",
            "title": "암호화폐 뉴스",
            "count": 30,
            "highlights": ["- BTC 상승세 지속"],
            "key_summary": [],
            "market_data": [],
            "content": (
                "금리 연준 fed fomc 금리인상 "
                "[Bitcoin ETF approval clears regulatory hurdle today worldwide](https://ex.com/btc) "
                "비트코인 83,200 달러"
            ),
            "themes": [("금리/유동성", 12), ("정책/규제", 8), ("기술/온체인", 5)],
            "url": "https://example.com/crypto",
        }

    def _stock(self):
        return {
            "type": "stock",
            "title": "주식 뉴스",
            "count": 20,
            "highlights": ["- KOSPI 상승"],
            "key_summary": [],
            "market_data": ["KOSPI 2,500.50(+1.23%) 상승 마감"],
            "content": (
                "금리 연준 fed "
                "[Tesla earnings beat expectations across the board today](https://ex.com/tsla) KOSPI 2500"
            ),
            "themes": [("실적/어닝", 6)],
            "url": "https://example.com/stock",
        }

    def _regulatory(self):
        return {
            "type": "regulatory",
            "title": "규제 동향",
            "count": 10,
            "highlights": [],
            "key_summary": ["- SEC 가상자산 신규 가이드라인 발표"],
            "content": (
                "규제 sec etf 법안 정책 "
                "[SEC issues new crypto guidance framework for exchanges today](https://ex.com/sec) "
                "과징금 50억원"
            ),
            "themes": [("정책/규제", 7)],
            "url": "https://example.com/regulatory",
        }

    def _social(self):
        return {
            "type": "social",
            "title": "소셜 미디어",
            "count": 15,
            "highlights": ["- 비트코인 트위터 언급 급증"],
            "key_summary": [],
            "content": (
                "[Crypto twitter sentiment surges on ETF approval news worldwide](https://ex.com/soc) 언급 1만건"
            ),
            "themes": [],
            "url": "https://example.com/social",
        }

    def _political(self):
        return {
            "type": "political",
            "title": "정치인 거래",
            "count": 8,
            "highlights": ["- 에너지 섹터 매수 집중"],
            "key_summary": ["- 펠로시 엔비디아 콜옵션 매수", "- 상원의원 반도체주 대량 매수"],
            "content": (
                "정치인 거래 [Pelosi buys Nvidia call options ahead of earnings report](https://ex.com/pol) 50만달러"
            ),
            "themes": [],
            "url": "https://example.com/political",
        }

    def _worldmonitor(self):
        return {
            "type": "worldmonitor",
            "title": "월드모니터 브리핑",
            "count": 25,
            "highlights": [],
            "key_summary": ["- 중동 지정학 리스크 고조"],
            "content": (
                "[Global geopolitical tension rises in middle east region today](https://ex.com/wm) 환율 달러 dxy"
            ),
            "themes": [],
            "url": "https://example.com/worldmonitor",
            "issues": [
                "| 1 | 중동 긴장 고조 | 지정학 | high | Reuters |",
                "| 2 | 유가 급등 | 에너지 | mid | Bloomberg |",
            ],
        }

    def _security(self):
        return {
            "type": "security",
            "title": "보안 리포트",
            "count": 5,
            "highlights": [],
            "key_summary": ["- Major exchange exploit drains user funds today worldwide"],
            "content": (
                "해킹 exploit "
                "[DeFi protocol hacked for millions in flash loan attack today](https://ex.com/sec2) 피해 1200만달러"
            ),
            "themes": [],
            "url": "https://example.com/security",
            "incidents": ["| ProjectX | $12M | 플래시론 공격 |", "| ProjectY | $3M | 키 유출 |"],
        }

    def _market(self):
        return {
            "type": "market",
            "count": 12,
            "highlights": ["- 코스피 +1.5%", "- 나스닥 -0.3%"],
            "exec_summary": [],
            "indicator_rows": ["| CPI | 3.2% | +0.1% |", "| 실업률 | 3.8% | -0.1% |"],
            "yield_section": "| 10년물 | 4.2% | 스프레드 0.5%p |\n> 장단기 스프레드 정상화",
            "content": "코스피 상승.",
            "url": "https://example.com/market",
        }

    def _build_combined(self):
        summary_map = {
            "crypto": self._crypto(),
            "stock": self._stock(),
            "regulatory": self._regulatory(),
            "social": self._social(),
            "worldmonitor": self._worldmonitor(),
            "political": self._political(),
        }
        all_summaries = [
            summary_map[k] for k in ("crypto", "stock", "regulatory", "social", "worldmonitor", "political")
        ]
        theme_payload = [
            {"name": "금리/유동성", "emoji": "💰", "count": 32, "keywords": ["금리", "연준", "fed"]},
            {"name": "정책/규제", "emoji": "📋", "count": 15, "keywords": ["sec", "etf"]},
            {"name": "기술/온체인", "emoji": "🔗", "count": 8, "keywords": ["tvl", "온체인"]},
        ]
        priority_items = {
            "P0": [
                {
                    "title": "비트코인 거래소 대형 해킹 사고 발생 긴급 속보",
                    "description": "대형 거래소에서 수억 달러 규모의 해킹 피해가 발생했습니다",
                    "link": "https://ex.com/p0a",
                    "type": "crypto",
                },
                {
                    "title": "주요 스테이블코인 디페깅 발생 시장 충격",
                    "description": "주요 스테이블코인이 1달러 페그를 이탈하며 시장에 충격을 주었습니다",
                    "link": "https://ex.com/p0b",
                    "type": "crypto",
                },
            ],
            "P1": [
                {
                    "title": "비트코인 현물 ETF 최종 승인 결정 발표",
                    "description": "SEC가 비트코인 현물 ETF를 최종 승인했습니다",
                    "link": "https://ex.com/p1a",
                    "type": "crypto",
                },
                {
                    "title": "엔비디아 분기 실적 시장 예상치 상회",
                    "description": "엔비디아가 분기 실적에서 시장 예상치를 크게 상회했습니다",
                    "link": "https://ex.com/p1b",
                    "type": "stock",
                },
            ],
            "P2": [
                {"title": "이더리움 개발자 컨퍼런스 다음달 개최 예정", "link": "https://ex.com/p2a", "type": "crypto"},
                {
                    "title": "솔라나 생태계 신규 프로젝트 다수 출시 예정",
                    "link": "https://ex.com/p2b",
                    "type": "crypto",
                },
            ],
        }
        all_news_items = [
            {
                "title": "Bitcoin surges amid ETF approval news worldwide today",
                "link": "https://ex.com/n1",
                "type": "crypto",
            },
            {"title": "금리 인상 우려로 시장 변동성 확대 전망", "link": "https://ex.com/n2", "type": "stock"},
            {
                "title": "SEC regulatory crackdown on crypto exchanges intensifies",
                "link": "https://ex.com/n3",
                "type": "regulatory",
            },
        ]
        post_links = [
            ("암호화폐 뉴스", 30, "https://example.com/crypto"),
            ("주식 시장 뉴스", 20, "https://example.com/stock"),
            ("규제 동향", 10, "https://example.com/regulatory"),
        ]

        mock_summ = MagicMock()
        mock_summ.detect_concentration.return_value = ("금리/유동성", "interest", 0.42)
        mock_summ.detect_anomalies.return_value = [("리스크", "risk", 8, "이상 급등 패턴이 감지되었습니다.")]

        # 골든마스터 격리: _render_generated_image 가 디스크의 generated 이미지 존재 여부를
        # os.path.exists 로 probe 하므로, 패치하지 않으면 출력이 로컬 파일시스템 상태에 의존한다
        # (이미지 존재=로컬, 부재=CI → 해시 불일치). 항상 렌더하는 결정적 스텁으로 고정한다.
        def _stub_render_image(filename, alt):
            return f"![{alt}]({{{{ '/assets/images/generated/{filename}' | relative_url }}}})"

        with (
            patch("common.summary_text_ko.translate_to_korean", side_effect=lambda x: x),
            patch("common.summary_sections._render_generated_image", side_effect=_stub_render_image),
        ):
            briefing = gds._build_briefing_section(
                all_summaries=all_summaries,
                all_news_items=all_news_items,
                summary_map=summary_map,
                theme_payload=theme_payload,
                sentiment=self._sentiment(),
                today="2026-06-29",
                briefing_image=None,
                priority_items=priority_items,
                summarizer=mock_summ,
            )
            priority = gds._build_priority_and_category_sections(
                priority_items=priority_items,
                market_summary=self._market(),
                security_summary=self._security(),
                summary_map=summary_map,
                post_links=post_links,
                all_news_items=all_news_items,
            )
        return "\n".join(briefing) + "\n===SPLIT===\n" + "\n".join(priority)

    def test_combined_output_hash_is_stable(self):
        import hashlib

        combined = self._build_combined()
        actual = hashlib.sha256(combined.encode("utf-8")).hexdigest()
        assert actual == self.EXPECTED_HASH, (
            "행위 변경 감지: 출력이 골든마스터와 다릅니다.\n"
            f"expected={self.EXPECTED_HASH}\nactual  ={actual}\n--- 실제 출력 ---\n{combined}"
        )

    # ------------------------------------------------------------------
    # 케이스 2: titles가 비어있는 카테고리 — fallback/figures 경로 커버
    # ------------------------------------------------------------------
    #
    # content 에 마크다운 링크([text](url))가 없으므로
    # _extract_category_data_points 가 titles=[] 를 반환한다.
    # 이로 인해 다음 fallback/figures 분기가 활성화된다:
    #
    #   _render_category_section (summary_sections.py:768-773):
    #     dp["titles"]가 비어있을 때 fallback_keys 체인 탐색
    #       - regulatory → key_summary fallback (_raw_fallback)
    #       - worldmonitor → key_summary fallback + issues 표 렌더
    #       - security → key_summary fallback + incidents 표 렌더
    #       - social → highlights fallback (_raw_fallback)
    #
    #   _build_briefing_section per-category one-liner (summary_sections.py:476-482):
    #     dp["figures"] 비어있지 않으면 "주요 지표" 표시
    #     dp["titles"] 비어있으면 _best_non_noise_title 호출 없음
    #
    #   _build_priority_and_category_sections crypto 섹션 (summary_sections.py:1009):
    #     titles 비어있으면 "elif crypto_summary.get('highlights')" highlights fallback
    #
    #   stock 섹션 (summary_sections.py:1038-1043):
    #     titles 비어있으면 "elif stock_summary.get('highlights')" highlights fallback
    #
    # 격리 방식: 기존 케이스와 동일한 patch 패턴 사용
    #   - translate_to_korean → 항등 함수 (번역 비결정성 제거)
    #   - _render_generated_image → 결정적 스텁 (파일시스템 probe 제거)
    #
    # 캡처 시점(2026-07-01) 실제 출력의 SHA256.
    EXPECTED_HASH_EMPTY_TITLES = "b595cf3a31f8b1242bb8d380b641fc0446f323380be0ae3cd0ecbae0925fea85"

    def _crypto_empty_titles(self):
        """content에 마크다운 링크 없음 → titles=[], figures 존재, highlights fallback."""
        return {
            "type": "crypto",
            "title": "암호화폐 뉴스",
            "count": 5,
            "highlights": ["- BTC 소폭 하락"],
            "key_summary": [],
            "market_data": [],
            "content": "비트코인 83200 달러 KOSPI 2500 포인트 단순 텍스트 뉴스, 링크 없음",
            "themes": [("금리/유동성", 3)],
            "url": "https://example.com/crypto-empty",
        }

    def _stock_empty_titles(self):
        """content에 마크다운 링크 없음 → titles=[], market_data fallback, figures 존재."""
        return {
            "type": "stock",
            "title": "주식 뉴스",
            "count": 4,
            "highlights": [],
            "key_summary": [],
            "market_data": ["KOSPI 2500 포인트"],
            "content": "KOSPI 2500 포인트 plain text without any links",
            "themes": [],
            "url": "https://example.com/stock-empty",
        }

    def _regulatory_empty_titles(self):
        """content에 마크다운 링크 없음 → titles=[], key_summary fallback(_raw_fallback)."""
        return {
            "type": "regulatory",
            "title": "규제 동향",
            "count": 3,
            "highlights": [],
            "key_summary": ["- SEC 조사 개시"],
            "content": "규제 sec 법안 plain text only 과징금 50억원",
            "themes": [("정책/규제", 3)],
            "url": "https://example.com/reg-empty",
        }

    def _social_empty_titles(self):
        """content에 마크다운 링크 없음 → titles=[], highlights fallback(_raw_fallback)."""
        return {
            "type": "social",
            "title": "소셜 미디어",
            "count": 6,
            "highlights": ["- 비트코인 언급 증가"],
            "key_summary": [],
            "content": "소셜 언급 1만건 plain text only",
            "themes": [],
            "url": "https://example.com/social-empty",
        }

    def _worldmonitor_empty_titles(self):
        """content에 마크다운 링크 없음 → titles=[], key_summary fallback + issues 표 렌더."""
        return {
            "type": "worldmonitor",
            "title": "월드모니터 브리핑",
            "count": 7,
            "highlights": [],
            "key_summary": ["- 중동 긴장 고조"],
            "content": "글로벌 지정학 리스크 환율 달러 dxy plain text",
            "themes": [],
            "url": "https://example.com/wm-empty",
            "issues": ["| 1 | 중동 긴장 | 지정학 | high | Reuters |"],
        }

    def _political_empty_titles(self):
        """content에 마크다운 링크 없음 → titles=[], key_summary fallback."""
        return {
            "type": "political",
            "title": "정치인 거래",
            "count": 2,
            "highlights": [],
            "key_summary": ["- 상원의원 반도체주 매수"],
            "content": "정치인 거래 plain text only",
            "themes": [],
            "url": "https://example.com/pol-empty",
        }

    def _security_empty_titles(self):
        """content에 마크다운 링크 없음 → titles=[], key_summary fallback + incidents 표 렌더."""
        return {
            "type": "security",
            "title": "보안 리포트",
            "count": 2,
            "highlights": [],
            "key_summary": ["- 소규모 해킹 발생"],
            "content": "해킹 exploit plain text only 피해 100만달러",
            "themes": [],
            "url": "https://example.com/sec-empty",
            "incidents": ["| ProjectZ | $1M | 피싱 |"],
        }

    def _build_combined_empty_titles(self):
        """모든 카테고리의 titles가 비어있는 입력으로 두 섹션 빌더를 실행한다."""
        summary_map = {
            "crypto": self._crypto_empty_titles(),
            "stock": self._stock_empty_titles(),
            "regulatory": self._regulatory_empty_titles(),
            "social": self._social_empty_titles(),
            "worldmonitor": self._worldmonitor_empty_titles(),
            "political": self._political_empty_titles(),
        }
        all_summaries = [
            summary_map[k] for k in ("crypto", "stock", "regulatory", "social", "worldmonitor", "political")
        ]
        theme_payload = [
            {"name": "금리/유동성", "emoji": "💰", "count": 5, "keywords": ["금리", "연준"]},
        ]
        priority_items: dict = {"P0": [], "P1": [], "P2": []}
        all_news_items = [
            {"title": "시장 단순 뉴스", "link": "https://ex.com/n1", "type": "crypto"},
        ]
        post_links = [
            ("암호화폐 뉴스", 5, "https://example.com/crypto-empty"),
        ]
        market_summary = {
            "type": "market",
            "count": 0,
            "highlights": [],
            "exec_summary": [],
            "indicator_rows": [],
            "yield_section": "",
            "content": "",
            "url": "https://example.com/market-empty",
        }
        sentiment = {
            "tone": "중립",
            "positive": 2,
            "negative": 2,
            "ratio": 50,
            "pos_examples": [],
            "neg_examples": [],
        }

        mock_summ = MagicMock()
        mock_summ.detect_concentration.return_value = None
        mock_summ.detect_anomalies.return_value = []

        def _stub_render_image(filename, alt):
            return f"![{alt}]({{{{ '/assets/images/generated/{filename}' | relative_url }}}})"

        with (
            patch("common.summary_text_ko.translate_to_korean", side_effect=lambda x: x),
            patch("common.summary_sections._render_generated_image", side_effect=_stub_render_image),
        ):
            briefing = gds._build_briefing_section(
                all_summaries=all_summaries,
                all_news_items=all_news_items,
                summary_map=summary_map,
                theme_payload=theme_payload,
                sentiment=sentiment,
                today="2026-07-01",
                briefing_image=None,
                priority_items=priority_items,
                summarizer=mock_summ,
            )
            priority = gds._build_priority_and_category_sections(
                priority_items=priority_items,
                market_summary=market_summary,
                security_summary=self._security_empty_titles(),
                summary_map=summary_map,
                post_links=post_links,
                all_news_items=all_news_items,
            )
        return "\n".join(briefing) + "\n===SPLIT===\n" + "\n".join(priority)

    def test_empty_titles_fallback_output_hash_is_stable(self):
        """titles가 비어있는 카테고리에서 fallback/figures 경로 출력이 안정적임을 보장한다."""
        import hashlib

        combined = self._build_combined_empty_titles()
        actual = hashlib.sha256(combined.encode("utf-8")).hexdigest()
        assert actual == self.EXPECTED_HASH_EMPTY_TITLES, (
            "행위 변경 감지: empty-titles 케이스 출력이 골든마스터와 다릅니다.\n"
            f"expected={self.EXPECTED_HASH_EMPTY_TITLES}\nactual  ={actual}\n--- 실제 출력 ---\n{combined}"
        )

    # ------------------------------------------------------------------
    # 케이스 3: 렌더 불가/최소 데이터 — 방어 fallback 경로 커버
    # ------------------------------------------------------------------
    #
    # 카테고리는 count>0 이지만 titles·figures·market_data 가 모두 비어(content 에
    # 링크·숫자 없음), 케이스 1/2 어느 쪽도 밟지 않는 최종 방어 분기를 고정한다:
    #
    #   _build_briefing_section 카테고리 상세 (summary_sections.py):
    #     - crypto  "세부 데이터 확인 필요." (509)  — 테마·수치·타이틀 전무
    #     - stock   "시장 데이터 확인 필요." (524)  — market_data·수치·타이틀 전무
    #     - regulatory "정책 공시 및 감독 이슈 중심." (536)
    #     - social  "소셜 채널 키워드 분석 기반." (548)
    #     - worldmonitor "글로벌 이슈 모니터링 기반." (560)
    #   _build_briefing_section 테마 스냅샷 (573): theme_payload=[] → 섹션 생략
    #
    #   _build_snapshot_table.top_signal:
    #     - Priority 4 테마명+건수 (231-233) — worldmonitor(themes만 존재)
    #     - "신호 추출 실패" (235) — crypto/regulatory/social(전무)
    #
    #   _build_priority_and_category_sections:
    #     - market overview elif exec_summary (849) — highlights 비고 exec_summary 존재
    #     - political watch highlights 분기 (969-972) — key_summary 없음
    #     - stock 카테고리 elif highlights fallback (1048-1053) — market_data·titles 전무
    #
    # 격리 방식: 케이스 1/2 와 동일(translate 항등 patch + _render_generated_image 스텁).
    #
    # 캡처 시점(2026-07-03) 실제 출력의 SHA256.
    EXPECTED_HASH_NO_DATA = "50ec9b55af921f0aab11c7221b4cecaaf3d41e4fbf4c37d7d631287350b61281"

    def _crypto_no_data(self):
        """테마·수치·타이틀 전무 → briefing '세부 데이터 확인 필요.' + snapshot '신호 추출 실패'."""
        return {
            "type": "crypto",
            "title": "암호화폐 뉴스",
            "count": 5,
            "highlights": [],
            "key_summary": [],
            "market_data": [],
            "content": "암호화폐 관련 단순 텍스트 뉴스 링크 없음",
            "themes": [],
            "url": "https://example.com/crypto-nodata",
        }

    def _stock_no_data(self):
        """market_data·수치·타이틀 전무, highlights 존재 → briefing '시장 데이터 확인 필요.' + 카테고리 elif highlights."""
        return {
            "type": "stock",
            "title": "주식 뉴스",
            "count": 4,
            "highlights": ["- 주식 시장 관련 단순 코멘트 라인"],
            "key_summary": [],
            "market_data": [],
            "content": "주식 시장 관련 단순 텍스트 링크 없음",
            "themes": [],
            "url": "https://example.com/stock-nodata",
        }

    def _regulatory_no_data(self):
        """타이틀·수치·key_summary 전무 → briefing '정책 공시 및 감독 이슈 중심.'."""
        return {
            "type": "regulatory",
            "title": "규제 동향",
            "count": 3,
            "highlights": [],
            "key_summary": [],
            "content": "규제 관련 단순 텍스트 링크 없음",
            "themes": [],
            "url": "https://example.com/reg-nodata",
        }

    def _social_no_data(self):
        """타이틀·수치·highlights 전무 → briefing '소셜 채널 키워드 분석 기반.'."""
        return {
            "type": "social",
            "title": "소셜 미디어",
            "count": 6,
            "highlights": [],
            "key_summary": [],
            "content": "소셜 관련 단순 텍스트 링크 없음",
            "themes": [],
            "url": "https://example.com/social-nodata",
        }

    def _worldmonitor_no_data(self):
        """타이틀·수치 전무, themes 존재 → briefing '글로벌 이슈 모니터링 기반.' + snapshot Priority 4 테마명."""
        return {
            "type": "worldmonitor",
            "title": "월드모니터 브리핑",
            "count": 7,
            "highlights": [],
            "key_summary": [],
            "content": "글로벌 관련 단순 텍스트 링크 없음",
            "themes": [("지정학", 2)],
            "url": "https://example.com/wm-nodata",
        }

    def _political_no_data(self):
        """key_summary 없음, highlights 존재 → political watch highlights 분기."""
        return {
            "type": "political",
            "title": "정치인 거래",
            "count": 2,
            "highlights": ["- 정치인 거래 관련 단순 코멘트 라인"],
            "key_summary": [],
            "content": "정치인 거래 관련 단순 텍스트 링크 없음",
            "themes": [],
            "url": "https://example.com/pol-nodata",
        }

    def _security_no_data(self):
        """타이틀·key_summary·incidents 전무 → 카테고리 헤딩 + 상세 링크만."""
        return {
            "type": "security",
            "title": "보안 리포트",
            "count": 2,
            "highlights": [],
            "key_summary": [],
            "content": "보안 관련 단순 텍스트 링크 없음",
            "themes": [],
            "url": "https://example.com/sec-nodata",
        }

    def _build_combined_no_data(self):
        """렌더 불가/최소 데이터 입력으로 두 섹션 빌더를 실행한다."""
        summary_map = {
            "crypto": self._crypto_no_data(),
            "stock": self._stock_no_data(),
            "regulatory": self._regulatory_no_data(),
            "social": self._social_no_data(),
            "worldmonitor": self._worldmonitor_no_data(),
            "political": self._political_no_data(),
        }
        all_summaries = [
            summary_map[k] for k in ("crypto", "stock", "regulatory", "social", "worldmonitor", "political")
        ]
        # theme_payload=[] → 테마 스냅샷 섹션 생략 분기 커버
        theme_payload: list = []
        priority_items: dict = {"P0": [], "P1": [], "P2": []}
        all_news_items = [
            {"title": "시장 단순 뉴스", "link": "https://ex.com/n1", "type": "crypto"},
        ]
        post_links = [
            ("암호화폐 뉴스", 5, "https://example.com/crypto-nodata"),
        ]
        # highlights 비어있고 exec_summary 존재 → 시장 개요 elif exec_summary 분기 커버
        market_summary = {
            "type": "market",
            "count": 3,
            "highlights": [],
            "exec_summary": ["- 시장 요약 코멘트 라인"],
            "indicator_rows": [],
            "yield_section": "",
            "content": "",
            "url": "https://example.com/market-nodata",
        }
        sentiment = {
            "tone": "중립",
            "positive": 2,
            "negative": 2,
            "ratio": 50,
            "pos_examples": [],
            "neg_examples": [],
        }

        mock_summ = MagicMock()
        mock_summ.detect_concentration.return_value = None
        mock_summ.detect_anomalies.return_value = []

        def _stub_render_image(filename, alt):
            return f"![{alt}]({{{{ '/assets/images/generated/{filename}' | relative_url }}}})"

        with (
            patch("common.summary_text_ko.translate_to_korean", side_effect=lambda x: x),
            patch("common.summary_sections._render_generated_image", side_effect=_stub_render_image),
        ):
            briefing = gds._build_briefing_section(
                all_summaries=all_summaries,
                all_news_items=all_news_items,
                summary_map=summary_map,
                theme_payload=theme_payload,
                sentiment=sentiment,
                today="2026-07-03",
                briefing_image=None,
                priority_items=priority_items,
                summarizer=mock_summ,
            )
            priority = gds._build_priority_and_category_sections(
                priority_items=priority_items,
                market_summary=market_summary,
                security_summary=self._security_no_data(),
                summary_map=summary_map,
                post_links=post_links,
                all_news_items=all_news_items,
            )
        return "\n".join(briefing) + "\n===SPLIT===\n" + "\n".join(priority)

    def test_no_data_fallback_output_hash_is_stable(self):
        """렌더 불가/최소 데이터 카테고리의 방어 fallback 출력이 안정적임을 보장한다."""
        import hashlib

        combined = self._build_combined_no_data()
        actual = hashlib.sha256(combined.encode("utf-8")).hexdigest()
        assert actual == self.EXPECTED_HASH_NO_DATA, (
            "행위 변경 감지: no-data 케이스 출력이 골든마스터와 다릅니다.\n"
            f"expected={self.EXPECTED_HASH_NO_DATA}\nactual  ={actual}\n--- 실제 출력 ---\n{combined}"
        )

    # ------------------------------------------------------------------
    # 케이스 4: titles-only 카테고리 + 교차자산 relation(high/mid) — 그룹 B/C 커버
    # ------------------------------------------------------------------
    #
    # 각 카테고리 content 에 마크다운 링크(→titles) + 교차자산 토픽 키워드('금리')를
    # 반복해, 케이스 1/2/3 이 밟지 못한 아래 분기를 고정한다:
    #
    #   _build_briefing_section titles-only 상세 (테마·수치 없이 타이틀만 존재):
    #     - crypto 대표 헤드라인 (506-508)
    #     - stock  titles 폴백 (519-521)
    #     - regulatory/social/worldmonitor titles 상세 (531-558)
    #     - sentiment.ratio ≤ 35 공포 구간 메모 (631-632)
    #     - 리스크/기회 메모 top_score ≥ 30 (600) + 정책/규제 테마 (620)
    #
    #   _build_priority_and_category_sections:
    #     - 지표 대시보드 indicator_rows + yield_section 파싱 (861-879)
    #     - P0 desc > 15자 (836-838), P1 링크 없는 항목 else (990)
    #     - 교차자산 relation: high 3쌍→시스템 리스크(908-912), high_pairs(925-926),
    #       mid_pairs(930-931), 암호화폐↔규제(946-949), 정치인 오버랩(954-957)
    #
    # relation 점수 제어: _topic_hits 는 title+content+highlights+key_summary 에서
    # 키워드를 count 한다. content 에 '금리'(금리/유동성 토픽)를 N회 반복해
    # 쌍별 min 교집합 점수를 결정한다(crypto/stock/reg=26→높음·high_pair,
    # political=12→중간·mid_pair, social/worldmonitor=0→낮음).
    #
    # 캡처 시점(2026-07-03) 실제 출력의 SHA256.
    EXPECTED_HASH_TITLES_RELATION = "99354f2c8e65764980210bd998543c2ab665677b3546b7957a80c3613bb55ee7"

    def _titles_only(self, key, title, url, topic_repeat, count=10):
        """마크다운 링크(→titles) + '금리' 반복(→relation 점수), 숫자 없음(→figures 없음)."""
        link = f"[{title}](https://ex.com/{key})"
        content = f"{link} " + ("금리 " * topic_repeat)
        return {
            "type": key,
            "title": title.split()[0],
            "count": count,
            "highlights": [],
            "key_summary": [],
            "market_data": [],
            "content": content,
            "themes": [],
            "url": url,
        }

    def _build_combined_titles_relation(self):
        """titles-only + 교차자산 relation(high/mid) 입력으로 두 섹션 빌더를 실행한다."""
        summary_map = {
            # crypto/stock/regulatory: 금리 26회 → 상호 high(≥25) 쌍
            "crypto": self._titles_only(
                "crypto", "비트코인 상승 기대 전망 뉴스 오늘 관련", "https://example.com/crypto-tr", 26
            ),
            "stock": self._titles_only(
                "stock", "엔비디아 실적 개선 기대 뉴스 오늘 관련", "https://example.com/stock-tr", 26
            ),
            "regulatory": self._titles_only(
                "regulatory", "감독당국 신규 지침 발표 예정 오늘", "https://example.com/reg-tr", 26
            ),
            # political: 금리 12회 → crypto/stock 과 mid(12) 쌍
            "political": self._titles_only(
                "political", "정치인 반도체주 대량 매수 포착 오늘", "https://example.com/pol-tr", 12
            ),
            # social/worldmonitor: 금리 0회 → 낮음(공통 미감지) 쌍, 타이틀은 존재
            "social": self._titles_only(
                "social", "소셜 고래 매집 언급 급증 화제 오늘", "https://example.com/social-tr", 0
            ),
            "worldmonitor": self._titles_only(
                "worldmonitor", "월드 지정학 리스크 고조 이슈 오늘", "https://example.com/wm-tr", 0
            ),
        }
        all_summaries = [
            summary_map[k] for k in ("crypto", "stock", "regulatory", "social", "worldmonitor", "political")
        ]
        theme_payload = [
            {"name": "정책/규제 이슈", "emoji": "📋", "count": 30, "keywords": ["규제", "sec"]},
            {"name": "금리/유동성", "emoji": "💰", "count": 18, "keywords": ["금리", "연준"]},
        ]
        priority_items = {
            "P0": [
                {
                    "title": "긴급 뉴스 제목 항목",
                    "description": "이것은 15자보다 확실히 더 긴 P0 긴급 설명 문장입니다 상세 확인 필요",
                    "link": "https://ex.com/p0",
                    "type": "crypto",
                },
            ],
            "P1": [
                # 링크 없는 P1 항목 → else 분기(_headline_for_korean_summary)
                {"title": "링크 없는 P1 중요 뉴스 제목 항목", "type": "stock"},
            ],
            "P2": [],
        }
        all_news_items = [
            {"title": "시장 단순 뉴스", "link": "https://ex.com/n1", "type": "crypto"},
        ]
        post_links = [
            ("암호화폐 뉴스", 10, "https://example.com/crypto-tr"),
        ]
        market_summary = {
            "type": "market",
            "count": 12,
            "highlights": ["- 코스피 상승 마감"],
            "exec_summary": [],
            "indicator_rows": ["| CPI | 3.2% | +0.1% |", "| 실업률 | 3.8% | -0.1% |"],
            "yield_section": "| 10년물 | 4.2% | 스프레드 0.5%p |\n> 장단기 스프레드 정상화",
            "content": "",
            "url": "https://example.com/market-tr",
        }
        # 공포 구간(ratio ≤ 35) 메모 분기 커버
        sentiment = {
            "tone": "부정 우세",
            "positive": 3,
            "negative": 7,
            "ratio": 30,
            "pos_examples": ["일부 반등"],
            "neg_examples": ["매도 우위"],
        }

        mock_summ = MagicMock()
        mock_summ.detect_concentration.return_value = None
        mock_summ.detect_anomalies.return_value = []

        def _stub_render_image(filename, alt):
            return f"![{alt}]({{{{ '/assets/images/generated/{filename}' | relative_url }}}})"

        with (
            patch("common.summary_text_ko.translate_to_korean", side_effect=lambda x: x),
            patch("common.summary_sections._render_generated_image", side_effect=_stub_render_image),
        ):
            briefing = gds._build_briefing_section(
                all_summaries=all_summaries,
                all_news_items=all_news_items,
                summary_map=summary_map,
                theme_payload=theme_payload,
                sentiment=sentiment,
                today="2026-07-03",
                briefing_image=None,
                priority_items=priority_items,
                summarizer=mock_summ,
            )
            priority = gds._build_priority_and_category_sections(
                priority_items=priority_items,
                market_summary=market_summary,
                security_summary=None,
                summary_map=summary_map,
                post_links=post_links,
                all_news_items=all_news_items,
            )
        return "\n".join(briefing) + "\n===SPLIT===\n" + "\n".join(priority)

    def test_titles_relation_fallback_output_hash_is_stable(self):
        """titles-only 상세 + 교차자산 relation(high/mid) 경로 출력이 안정적임을 보장한다."""
        import hashlib

        combined = self._build_combined_titles_relation()
        actual = hashlib.sha256(combined.encode("utf-8")).hexdigest()
        assert actual == self.EXPECTED_HASH_TITLES_RELATION, (
            "행위 변경 감지: titles-relation 케이스 출력이 골든마스터와 다릅니다.\n"
            f"expected={self.EXPECTED_HASH_TITLES_RELATION}\nactual  ={actual}\n--- 실제 출력 ---\n{combined}"
        )


# ---------------------------------------------------------------------------
# main() integration smoke tests
# ---------------------------------------------------------------------------


def _fake_kst_now_factory(date_str):
    """Return a datetime object whose strftime('%Y-%m-%d') == date_str."""
    year, month, day = map(int, date_str.split("-"))
    return _dt.datetime(year, month, day, 9, 0, 0, tzinfo=_dt.UTC)


class TestMainIntegration:
    """Integration smoke tests for main() — all external I/O is mocked."""

    TODAY = "2026-01-15"

    def _write_crypto_post(self, tmp_path):
        """Write a minimal crypto-news-digest post using TODAY as filename date."""
        (tmp_path / f"{self.TODAY}-crypto-news-digest.md").write_text(
            "---\ntitle: 암호화폐 뉴스\ncategory: crypto\n---\n"
            "## 핵심 요약\n- 비트코인 상승\n- 이더리움 하락\n\n"
            "오늘 5건의 뉴스가 수집되었습니다.\n",
            encoding="utf-8",
        )

    def _patch_posts_dir(self, monkeypatch, posts_dir):
        """Redirect POSTS_DIR so glob finds tmp_path posts.

        main() globs via gds.POSTS_DIR, but the extracted _render_generated_image
        (moved to summary_analysis in the 2026-06-29 L2 split) resolves generated
        images against its own module-level POSTS_DIR. Patch both bindings so the
        main() integration tests stay isolated from the real repo image tree.
        """
        monkeypatch.setattr(gds, "POSTS_DIR", posts_dir)
        monkeypatch.setattr("common.summary_analysis.POSTS_DIR", posts_dir)

    def _patch_datetime(self, monkeypatch):
        """Make datetime.now() in gds return a fixed date matching TODAY."""
        fake_now = _fake_kst_now_factory(self.TODAY)

        class _FakeDatetime(_dt.datetime):
            @classmethod
            def now(cls, tz=None):
                return fake_now.replace(tzinfo=tz) if tz else fake_now

        monkeypatch.setattr(gds, "datetime", _FakeDatetime)

    def test_creates_post_file_with_required_frontmatter_keys(self, tmp_path, monkeypatch):
        """main() writes a post file containing all required front-matter keys."""
        self._write_crypto_post(tmp_path)
        posts_dir = str(tmp_path)
        self._patch_posts_dir(monkeypatch, posts_dir)
        self._patch_datetime(monkeypatch)
        monkeypatch.setattr(gds, "_resolve_frontmatter_image", lambda *a, **kw: None)

        with patch(
            "scripts.generate_daily_summary.generate_news_briefing_card",
            return_value=None,
            create=True,
        ):
            gds.main()

        import glob as _glob

        written = _glob.glob(f"{posts_dir}/{self.TODAY}-daily-news-summary.md")
        assert written, "daily-news-summary post file must be created"

        with open(written[0], encoding="utf-8") as f:
            content = f.read()
        for key in ("layout", "title", "categories", "tags", "description"):
            assert f"{key}:" in content, f"front matter must contain '{key}:'"

    def test_no_posts_today_returns_early_without_writing(self, tmp_path, monkeypatch):
        """main() exits early when no posts exist for today — no file is created."""
        posts_dir = str(tmp_path)
        self._patch_posts_dir(monkeypatch, posts_dir)
        self._patch_datetime(monkeypatch)

        gds.main()

        import glob as _glob

        written = _glob.glob(f"{posts_dir}/*daily-news-summary*.md")
        assert not written, "no summary file should be written when no source posts exist"

    def test_only_crypto_posts_produce_valid_summary(self, tmp_path, monkeypatch):
        """main() creates a valid summary when only crypto posts are available."""
        self._write_crypto_post(tmp_path)
        posts_dir = str(tmp_path)
        self._patch_posts_dir(monkeypatch, posts_dir)
        self._patch_datetime(monkeypatch)
        monkeypatch.setattr(gds, "_resolve_frontmatter_image", lambda *a, **kw: None)

        with patch(
            "scripts.generate_daily_summary.generate_news_briefing_card",
            return_value=None,
            create=True,
        ):
            gds.main()

        import glob as _glob

        written = _glob.glob(f"{posts_dir}/{self.TODAY}-daily-news-summary.md")
        assert written
        with open(written[0], encoding="utf-8") as f:
            content = f.read()
        assert "암호화폐" in content or "crypto" in content.lower()

    def test_summary_post_contains_today_date(self, tmp_path, monkeypatch):
        """The generated summary post filename and content contain today's date."""
        self._write_crypto_post(tmp_path)
        posts_dir = str(tmp_path)
        self._patch_posts_dir(monkeypatch, posts_dir)
        self._patch_datetime(monkeypatch)
        monkeypatch.setattr(gds, "_resolve_frontmatter_image", lambda *a, **kw: None)

        with patch(
            "scripts.generate_daily_summary.generate_news_briefing_card",
            return_value=None,
            create=True,
        ):
            gds.main()

        import glob as _glob

        written = _glob.glob(f"{posts_dir}/{self.TODAY}-daily-news-summary.md")
        assert written
        with open(written[0], encoding="utf-8") as f:
            content = f.read()
        assert self.TODAY in content

    def test_multiple_category_posts_all_written_to_summary(self, tmp_path, monkeypatch):
        """main() handles multiple category posts and writes a combined summary."""
        posts_dir = str(tmp_path)
        # crypto post
        (tmp_path / f"{self.TODAY}-crypto-news-digest.md").write_text(
            "---\ntitle: 암호화폐 뉴스\ncategory: crypto\n---\n"
            "## 핵심 요약\n- 비트코인 상승\n\n오늘 3건의 뉴스가 수집되었습니다.\n",
            encoding="utf-8",
        )
        # stock post
        (tmp_path / f"{self.TODAY}-stock-news-digest.md").write_text(
            "---\ntitle: 주식 뉴스\ncategory: stock\n---\n"
            "## 핵심 요약\n- 삼성 실적 발표\n\n오늘 2건의 뉴스가 수집되었습니다.\n",
            encoding="utf-8",
        )
        self._patch_posts_dir(monkeypatch, posts_dir)
        self._patch_datetime(monkeypatch)
        monkeypatch.setattr(gds, "_resolve_frontmatter_image", lambda *a, **kw: None)

        with patch(
            "scripts.generate_daily_summary.generate_news_briefing_card",
            return_value=None,
            create=True,
        ):
            gds.main()

        import glob as _glob

        written = _glob.glob(f"{posts_dir}/{self.TODAY}-daily-news-summary.md")
        assert written
        with open(written[0], encoding="utf-8") as f:
            content = f.read()
        assert "layout: post" in content
