"""Tests for post generator (scripts/common/post_generator.py)."""

from common.post_generator import (
    _DEFAULT_CATEGORY_IMAGES,
    _TOKEN_ARTIFACTS,
    _extract_description,
    _fix_translation_artifacts,
    _normalize_image_paths,
    _slugify,
    _wrap_picture_tags,
)


class TestNormalizeImagePaths:
    def test_hardcoded_path_converted_to_liquid(self):
        md = "![alt](/assets/images/generated/foo-2026-01-01.png)"
        result = _normalize_image_paths(md)
        assert "{{ '/assets/images/generated/foo-2026-01-01.png' | relative_url }}" in result
        assert "![alt]" in result

    def test_already_liquid_unchanged(self):
        md = "![alt]({{ '/assets/images/generated/foo.png' | relative_url }})"
        result = _normalize_image_paths(md)
        assert result == md

    def test_non_generated_image_unchanged(self):
        md = "![logo](/assets/images/logo.png)"
        result = _normalize_image_paths(md)
        assert result == md

    def test_multiple_images(self):
        md = "![a](/assets/images/generated/a.png)\ntext\n![b](/assets/images/generated/b.png)"
        result = _normalize_image_paths(md)
        assert result.count("relative_url") == 2


class TestWrapPictureTags:
    def test_liquid_png_converted_to_picture(self):
        md = "![top-coins]({{ '/assets/images/generated/top-coins-2026-03-13.png' | relative_url }})"
        result = _wrap_picture_tags(md)
        assert "<picture>" in result
        assert "<source srcset=" in result
        assert "top-coins-2026-03-13.webp" in result
        assert "top-coins-2026-03-13.png" in result
        assert 'type="image/webp"' in result
        assert 'loading="lazy"' in result
        assert 'decoding="async"' in result

    def test_alt_text_preserved(self):
        md = "![market-heatmap-cmc]({{ '/assets/images/generated/heatmap.png' | relative_url }})"
        result = _wrap_picture_tags(md)
        assert 'alt="market-heatmap-cmc"' in result

    def test_non_generated_image_unchanged(self):
        md = "![logo]({{ '/assets/images/logo.png' | relative_url }})"
        result = _wrap_picture_tags(md)
        assert "<picture>" not in result
        assert result == md

    def test_non_png_unchanged(self):
        md = "![chart]({{ '/assets/images/generated/chart.jpg' | relative_url }})"
        result = _wrap_picture_tags(md)
        assert "<picture>" not in result

    def test_multiple_images_converted(self):
        md = (
            "![a]({{ '/assets/images/generated/a.png' | relative_url }})\n"
            "text between\n"
            "![b]({{ '/assets/images/generated/b.png' | relative_url }})"
        )
        result = _wrap_picture_tags(md)
        assert result.count("<picture>") == 2
        assert result.count("</picture>") == 2
        assert "a.webp" in result
        assert "b.webp" in result

    def test_double_quote_liquid_not_matched(self):
        """_wrap_picture_tags only handles single-quoted Liquid syntax."""
        md = '![alt]({{ "/assets/images/generated/foo.png" | relative_url }})'
        result = _wrap_picture_tags(md)
        assert "<picture>" not in result

    def test_empty_alt_text(self):
        md = "![]({{ '/assets/images/generated/chart.png' | relative_url }})"
        result = _wrap_picture_tags(md)
        assert "<picture>" in result
        assert 'alt=""' in result

    def test_picture_contains_liquid_relative_url(self):
        md = "![x]({{ '/assets/images/generated/x.png' | relative_url }})"
        result = _wrap_picture_tags(md)
        assert "| relative_url }}" in result
        assert result.count("relative_url") == 2  # one for webp, one for png


class TestFixTranslationArtifacts:
    """Tests for _fix_translation_artifacts()."""

    def test_ai_artifact_corrected(self):
        assert _fix_translation_artifacts("gAIn 5%") == "gain 5%"
        assert _fix_translation_artifacts("gAIns reported") == "gains reported"
        assert _fix_translation_artifacts("mAIn driver") == "main driver"

    def test_sol_artifact_corrected(self):
        assert _fix_translation_artifacts("SOLution found") == "Solution found"
        assert _fix_translation_artifacts("abSOLute zero") == "absolute zero"
        assert _fix_translation_artifacts("reSOLve conflict") == "resolve conflict"

    def test_xrp_artifact_corrected(self):
        assert _fix_translation_artifacts("XRPected outcome") == "Expected outcome"

    def test_eth_artifact_corrected(self):
        assert _fix_translation_artifacts("ETHical standards") == "Ethical standards"
        assert _fix_translation_artifacts("ETHics matters") == "Ethics matters"

    def test_clean_text_unchanged(self):
        text = "Bitcoin rises 10% today"
        assert _fix_translation_artifacts(text) == text

    def test_empty_string_unchanged(self):
        assert _fix_translation_artifacts("") == ""

    def test_multiple_artifacts_in_sentence(self):
        text = "mAIntain gAIns and remAIn SOLid"
        result = _fix_translation_artifacts(text)
        assert "maintain" in result
        assert "gains" in result
        assert "remain" in result
        assert "solid" in result

    def test_all_artifacts_defined_as_strings(self):
        for wrong, correct in _TOKEN_ARTIFACTS.items():
            assert isinstance(wrong, str)
            assert isinstance(correct, str)


class TestSlugify:
    """Tests for _slugify()."""

    def test_basic_english_slug(self):
        assert _slugify("Hello World") == "hello-world"

    def test_strips_korean_characters(self):
        result = _slugify("Bitcoin 비트코인 news")
        assert "비트코인" not in result
        assert "bitcoin" in result

    def test_special_chars_removed(self):
        result = _slugify("Bitcoin's Rise: 10%!")
        assert "'" not in result
        assert "!" not in result
        assert "%" not in result

    def test_max_length_truncated(self):
        long_text = "a" * 100
        result = _slugify(long_text, max_length=80)
        assert len(result) <= 80

    def test_multiple_spaces_become_single_hyphen(self):
        result = _slugify("bitcoin   news   today")
        assert "--" not in result
        assert result == "bitcoin-news-today"

    def test_leading_trailing_hyphens_removed(self):
        result = _slugify("-bitcoin news-")
        assert not result.startswith("-")
        assert not result.endswith("-")

    def test_empty_string(self):
        assert _slugify("") == ""

    def test_all_korean_returns_empty(self):
        result = _slugify("비트코인 이더리움")
        assert result == ""

    def test_lowercase_applied(self):
        result = _slugify("BITCOIN ETF APPROVED")
        assert result == result.lower()


class TestExtractDescription:
    """Tests for _extract_description()."""

    def test_basic_paragraph(self):
        content = "Bitcoin surged 10% today amid growing institutional interest.\n\nMore text here."
        result = _extract_description(content)
        assert "Bitcoin" in result

    def test_heading_skipped(self):
        content = "# Title\n\nReal content starts here with useful information."
        result = _extract_description(content)
        assert result.startswith("Real content")

    def test_markdown_link_resolved(self):
        content = "[Read more about Bitcoin](https://example.com/bitcoin-news-today)"
        result = _extract_description(content)
        # Link text extracted but URL stripped
        assert "https://" not in result

    def test_html_tags_stripped(self):
        content = "<div>Bitcoin price news update today for investors.</div>"
        result = _extract_description(content)
        assert "<div>" not in result

    def test_short_candidates_combined(self):
        content = "BTC rises today.\n\nETH also gains significantly.\n\nMarket sentiment positive."
        result = _extract_description(content)
        assert isinstance(result, str)

    def test_empty_content_returns_empty(self):
        assert _extract_description("") == ""

    def test_only_headings_returns_empty(self):
        content = "# Heading 1\n## Heading 2\n### Heading 3"
        result = _extract_description(content)
        assert result == ""

    def test_table_rows_skipped(self):
        content = "| Col1 | Col2 |\n| --- | --- |\nReal paragraph with useful content."
        result = _extract_description(content)
        assert "|" not in result

    def test_list_items_included(self):
        content = "- Bitcoin surges to all time high price record today\n- Ethereum follows"
        result = _extract_description(content)
        assert "Bitcoin" in result

    def test_blockquote_skipped(self):
        content = "> quoted text here\n\nReal paragraph with good content for readers."
        result = _extract_description(content)
        assert result.startswith("Real paragraph")

    def test_max_length_respected(self):
        long_content = "A" * 200 + " is a very long sentence that should be truncated."
        result = _extract_description(long_content)
        assert len(result) <= 200

    def test_boilerplate_start_filtered(self):
        content = "총 10건의 뉴스가 수집되었습니다.\n\n비트코인 가격이 급등하며 신고가를 경신했습니다."
        result = _extract_description(content)
        # "총 " prefix should be filtered and use the second candidate
        assert "비트코인" in result or "총" not in result


class TestDefaultCategoryImages:
    """Tests for _DEFAULT_CATEGORY_IMAGES data."""

    def test_non_empty(self):
        assert len(_DEFAULT_CATEGORY_IMAGES) > 0

    def test_crypto_key_exists(self):
        assert "crypto" in _DEFAULT_CATEGORY_IMAGES

    def test_all_values_start_with_slash(self):
        for key, val in _DEFAULT_CATEGORY_IMAGES.items():
            assert val.startswith("/"), f"Key {key!r} value doesn't start with /"

    def test_all_values_are_png(self):
        for key, val in _DEFAULT_CATEGORY_IMAGES.items():
            assert val.endswith(".png"), f"Key {key!r} value is not PNG"


class TestNormalizeAndWrapPipeline:
    """Test the full pipeline: hardcoded -> liquid -> picture."""

    def test_full_pipeline(self):
        md = "![coins](/assets/images/generated/top-coins-2026-03-13.png)"
        step1 = _normalize_image_paths(md)
        step2 = _wrap_picture_tags(step1)
        assert "<picture>" in step2
        assert "top-coins-2026-03-13.webp" in step2
        assert 'alt="coins"' in step2

    def test_mixed_content_preserved(self):
        md = (
            "# Title\n\n"
            "Some text here.\n\n"
            "![chart](/assets/images/generated/chart.png)\n\n"
            "More text.\n\n"
            "![logo](/assets/images/logo.png)\n"
        )
        step1 = _normalize_image_paths(md)
        step2 = _wrap_picture_tags(step1)
        assert step2.count("<picture>") == 1  # only generated image
        assert "# Title" in step2
        assert "More text." in step2
        assert "logo.png" in step2
        assert "<picture>" not in step2.split("logo")[0].split("More")[1]
