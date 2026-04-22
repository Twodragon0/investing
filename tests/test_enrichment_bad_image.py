"""Bad image pattern (tracking pixel / placeholder) regression tests.

Symmetric with ``tests/test_enrichment_logo.py``. Covers the
``match_bad_image_pattern`` API added in the A-lite follow-up:

1. Substring-pattern cases — one per retained family in ``_BAD_IMAGE_PATTERNS``.
2. Regex-bucketed 1x1 tracking pixel cases — all variants collapse to the
   synthetic token ``"1x1-pixel"`` for metric bucketing.
3. Miss cases — real article images and empty string return ``None``.
4. API contract — return type and boolean identity with ``_is_valid_image_url``
   behavior for logged rejection paths.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from common.enrichment import _is_valid_image_url, match_bad_image_pattern  # noqa: E402

# ---------------------------------------------------------------------------
# Substring-pattern match cases — one per family in _BAD_IMAGE_PATTERNS
# ---------------------------------------------------------------------------


def test_pixel_substring_matches():
    assert match_bad_image_pattern("https://ads.example.com/pixel/track.png") == "pixel"


def test_tracker_substring_matches():
    assert match_bad_image_pattern("https://tracker.example.com/beacon.png") == "tracker"


def test_beacon_substring_matches():
    # Hostname lacks "tracker" so "beacon" wins — independent of tracker pattern.
    assert match_bad_image_pattern("https://ads.cdn.io/beacon-hit.png") == "beacon"


def test_spacer_substring_matches():
    assert match_bad_image_pattern("https://cdn.example.com/spacer.gif") == "spacer"


def test_placeholder_substring_matches():
    assert match_bad_image_pattern("https://cdn.example.com/placeholder.png") == "placeholder"


def test_default_image_substring_matches():
    assert match_bad_image_pattern("https://cdn.example.com/default-image.jpg") == "default-image"


def test_no_image_substring_matches():
    assert match_bad_image_pattern("https://cdn.example.com/no-image.png") == "no-image"


def test_blank_substring_matches():
    assert match_bad_image_pattern("https://cdn.example.com/blank.gif") == "blank."


def test_gravatar_substring_matches():
    assert match_bad_image_pattern("https://gravatar.com/avatar/abc123") == "gravatar.com/avatar"


def test_wp_plugin_substring_matches():
    assert match_bad_image_pattern("https://example.com/wp-content/plugins/share.png") == "wp-content/plugins"


# ---------------------------------------------------------------------------
# Regex-bucketed 1x1 tracking pixel cases — all collapse to "1x1-pixel"
# ---------------------------------------------------------------------------


def test_1x1_bare_filename_returns_pixel_bucket():
    assert match_bad_image_pattern("https://images.cdn.io/assets/1x1.png") == "1x1-pixel"


def test_1x1_hyphen_prefixed_returns_pixel_bucket():
    assert match_bad_image_pattern("https://images.cdn.io/ad-1x1.png") == "1x1-pixel"


def test_1x1_underscore_prefixed_returns_pixel_bucket():
    assert match_bad_image_pattern("https://images.cdn.io/ad_1x1.png") == "1x1-pixel"


def test_1x1_with_query_string_returns_pixel_bucket():
    assert match_bad_image_pattern("https://serve.cdn.io/1x1?campaign=x") == "1x1-pixel"


def test_1x1_path_end_returns_pixel_bucket():
    assert match_bad_image_pattern("https://serve.cdn.io/proxy/1x1") == "1x1-pixel"


# ---------------------------------------------------------------------------
# Miss cases — real article images and empty string return None
# ---------------------------------------------------------------------------


def test_real_article_image_returns_none():
    assert match_bad_image_pattern("https://cdn.sanity.io/images/article-hero.jpg") is None


def test_empty_string_returns_none():
    assert match_bad_image_pattern("") is None


def test_1x1_as_article_slug_fragment_returns_none():
    """Article about 1-on-1 ('1x1') written in URL slug must not be flagged."""
    url = "https://cdn.example.com/articles/1x1-interview-with-ceo.jpg"
    assert match_bad_image_pattern(url) is None


def test_11x1_digit_run_returns_none():
    """Previous substring check rejected anything containing '1x1'; regex must not."""
    assert match_bad_image_pattern("https://cdn.example.com/galleries/11x1.webp") is None


# ---------------------------------------------------------------------------
# API contract — return type + boolean identity with _is_valid_image_url
# ---------------------------------------------------------------------------


def test_match_bad_image_pattern_return_type():
    hit = match_bad_image_pattern("https://cdn.example.com/1x1.png")
    miss = match_bad_image_pattern("https://cdn.example.com/article-hero.jpg")
    assert isinstance(hit, str)
    assert miss is None


def test_is_valid_image_url_mirrors_match_bad_image_pattern():
    """When match_bad_image_pattern returns non-None, _is_valid_image_url must be False."""
    samples = [
        "https://ads.example.com/pixel/track.png",
        "https://cdn.example.com/placeholder.png",
        "https://images.cdn.io/assets/1x1.png",
        "https://cdn.example.com/articles/1x1-interview.jpg",  # miss — FP regression
        "https://cdn.sanity.io/images/article-hero.jpg",  # miss — real image
    ]
    for url in samples:
        bad = match_bad_image_pattern(url)
        valid = _is_valid_image_url(url)
        # If bad pattern matched, URL must not be valid; converse isn't guaranteed
        # (e.g., .gif extension also rejects via a separate rule).
        if bad is not None:
            assert valid is False, f"{url!r} matched {bad!r} but _is_valid_image_url=True"
