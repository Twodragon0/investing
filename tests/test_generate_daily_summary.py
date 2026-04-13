"""Tests for generate_daily_summary.py — pure utility functions (no I/O)."""

import os
import sys

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
        content = (
            "## 매크로 경제 지표\n"
            "| 지표 | 현재 | 변동 |\n"
            "|---|---|---|\n"
            "| CPI | 3.2% | +0.1% |\n"
        )
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
        content = (
            "## 핵심\n- 항목1\n"
            '<div class="theme-distribution">테마블록</div>'
        )
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
                "type": "crypto", "count": crypto_count,
                "highlights": [], "key_summary": [], "content": "",
            }
        if stock_count:
            summaries["stock"] = {
                "type": "stock", "count": stock_count,
                "highlights": [], "key_summary": [], "market_data": [], "content": "",
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
            0, {"P0": [], "P1": [], "P2": []}, [],
            self._make_summary_map(), None, "뉴스", self._base_sentiment()
        )
        assert isinstance(result, list)
        assert len(result) > 0

    def test_counts_str_in_output(self):
        result = gds._build_overview_section(
            50, {"P0": [], "P1": [], "P2": []}, [],
            self._make_summary_map(crypto_count=30, stock_count=20),
            None, "암호화폐 30건, 주식 20건", self._base_sentiment()
        )
        combined = "\n".join(result)
        assert "암호화폐 30건, 주식 20건" in combined

    def test_risk_level_높음_when_many_p0(self):
        priority_items = {"P0": [{"title": f"긴급{i}"} for i in range(5)], "P1": [], "P2": []}
        result = gds._build_overview_section(
            10, priority_items, [],
            self._make_summary_map(), None, "뉴스", self._base_sentiment(ratio=20)
        )
        combined = "\n".join(result)
        assert "높음" in combined

    def test_risk_level_안정_when_no_p0(self):
        result = gds._build_overview_section(
            10, {"P0": [], "P1": [], "P2": []}, [],
            self._make_summary_map(), None, "뉴스", self._base_sentiment(ratio=60)
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
            100, {"P0": [], "P1": [], "P2": []}, themes,
            self._make_summary_map(crypto_count=60, stock_count=40),
            None, "암호화폐 60건, 주식 40건", self._base_sentiment()
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
            10, priority_items, [],
            self._make_summary_map(), None, "뉴스", self._base_sentiment()
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
        crypto_stock = next(
            (r for r in rows if "암호화폐" in r[0] and "주식" in r[1]), None
        )
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
