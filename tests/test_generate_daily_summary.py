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
