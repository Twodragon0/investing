"""Tests for post generator (scripts/common/post_generator.py)."""

from common.post_generator import (
    _normalize_image_paths,
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
