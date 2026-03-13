"""Tests for enrichment module (scripts/common/enrichment.py)."""

from common.enrichment import _clean_description, _is_valid_image_url


class TestIsValidImageUrl:
    """Validate image URL filtering logic."""

    def test_valid_image_url(self):
        assert _is_valid_image_url("https://example.com/photo.jpg")
        assert _is_valid_image_url("https://cdn.site.com/images/hero.png")
        assert _is_valid_image_url("https://media.site.com/article/thumb.webp")

    def test_rejects_empty_and_none(self):
        assert not _is_valid_image_url("")
        assert not _is_valid_image_url(None)

    def test_rejects_non_http(self):
        assert not _is_valid_image_url("data:image/png;base64,abc")
        assert not _is_valid_image_url("/relative/path.png")
        assert not _is_valid_image_url("ftp://server/image.png")

    def test_rejects_tracking_pixels(self):
        assert not _is_valid_image_url("https://tracker.com/1x1.gif")
        assert not _is_valid_image_url("https://analytics.com/pixel.png")

    def test_rejects_placeholder_images(self):
        assert not _is_valid_image_url("https://example.com/placeholder.png")
        assert not _is_valid_image_url("https://example.com/blank.gif")
        assert not _is_valid_image_url("https://example.com/spacer.gif")
        assert not _is_valid_image_url("https://example.com/loading.svg")

    def test_rejects_svg_ico_short_gif(self):
        """SVG/ICO are typically logos/icons, short GIF is tracking pixel."""
        assert not _is_valid_image_url("https://example.com/logo.svg")
        assert not _is_valid_image_url("https://example.com/favicon.ico")
        assert not _is_valid_image_url("https://example.com/dot.gif")

    def test_rejects_gravatar(self):
        assert not _is_valid_image_url("https://gravatar.com/avatar/abc123")

    def test_rejects_wp_plugin_images(self):
        assert not _is_valid_image_url("https://example.com/wp-content/plugins/social/share.png")

    def test_rejects_gif_always(self):
        """GIF is rejected regardless of path length (usually tracking pixels)."""
        assert not _is_valid_image_url("https://cdn.example.com/articles/2026/long-path.gif")

    def test_allows_long_webp(self):
        """Long path WebP is allowed as a real content image."""
        long_webp = "https://cdn.example.com/articles/2026/03/market-overview-hero.webp"
        assert _is_valid_image_url(long_webp)


class TestCleanDescription:
    """Validate description text cleaning."""

    def test_strips_whitespace(self):
        assert _clean_description("  hello world  ") == "hello world"

    def test_removes_boilerplate_prefixes(self):
        result = _clean_description("Sign up for our newsletter to get the latest news")
        assert not result.startswith("Sign up")

    def test_removes_html_entities(self):
        result = _clean_description("Bitcoin &amp; Ethereum rise &gt; 10%")
        assert "&amp;" not in result or "Bitcoin" in result

    def test_empty_string(self):
        assert _clean_description("") == ""

    def test_normal_description_unchanged(self):
        text = "Bitcoin surged 5% today amid growing institutional interest"
        result = _clean_description(text)
        assert "Bitcoin" in result
        assert "5%" in result

    def test_short_text_preserved(self):
        result = _clean_description("Price up")
        assert result == "Price up"
