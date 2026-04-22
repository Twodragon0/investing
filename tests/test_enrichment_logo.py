"""Logo URL pattern precision regression tests.

Covers the RALPLAN A-lite change:
1. Six pattern-match cases (one per pattern family still in _LOGO_URL_PATTERNS).
2. Two pattern-miss cases (real article image, empty string).
3. Two size-pattern removal checks (256x256 and 64x64 must now pass).
4. Two API-contract checks (match_logo_pattern return type + is_logo_like_url
   boolean identity with match_logo_pattern).
"""

import sys
from pathlib import Path

# Allow `from common.enrichment import ...` when running tests from repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from common.enrichment import is_logo_like_url, match_logo_pattern  # noqa: E402

# ---------------------------------------------------------------------------
# Pattern match cases (6) — one per retained pattern family
# ---------------------------------------------------------------------------


def test_favicon_matches():
    assert match_logo_pattern("https://www.google.com/s2/favicons?domain=x") == "/favicon"


def test_logo_directory_matches():
    assert match_logo_pattern("https://cdn.example.com/logo/site-banner.png") == "/logo/"


def test_dash_logo_dot_matches():
    assert match_logo_pattern("https://cdn.example.com/assets/site-logo.png") == "-logo."


def test_underscore_logo_dot_matches():
    assert match_logo_pattern("https://cdn.example.com/assets/site_logo.png") == "_logo."


def test_snslogo_matches():
    assert match_logo_pattern("https://www.etoday.co.kr/_var/snslogo.png") == "snslogo"


def test_default_logo_matches():
    assert match_logo_pattern("https://example.com/default-logo.png") == "default-logo"


# ---------------------------------------------------------------------------
# Pattern miss cases (2) — real article images
# ---------------------------------------------------------------------------


def test_real_article_image_returns_none():
    assert match_logo_pattern("https://cdn.sanity.io/images/photo-hero.jpg") is None


def test_empty_string_returns_none():
    assert match_logo_pattern("") is None


# ---------------------------------------------------------------------------
# Size-pattern removal (2) — these used to be flagged, now must pass through
# ---------------------------------------------------------------------------


def test_256x256_path_no_longer_flagged():
    """RALPLAN A-lite removed size tokens — OG-standard 256x256 must pass."""
    assert match_logo_pattern("https://cdn.example.com/img/256x256/hero.jpg") is None


def test_64x64_path_no_longer_flagged():
    assert match_logo_pattern("https://cdn.example.com/64x64/banner.png") is None


# ---------------------------------------------------------------------------
# API contract (2) — return type + boolean identity
# ---------------------------------------------------------------------------


def test_match_logo_pattern_return_type():
    hit = match_logo_pattern("https://cdn.example.com/logo/x.png")
    miss = match_logo_pattern("https://cdn.example.com/article-hero.jpg")
    assert isinstance(hit, str)
    assert miss is None


def test_is_logo_like_url_matches_bool_of_match_logo_pattern():
    samples = [
        "https://www.google.com/s2/favicons?domain=x",
        "https://cdn.sanity.io/images/photo-hero.jpg",
        "",
    ]
    for url in samples:
        assert is_logo_like_url(url) is (match_logo_pattern(url) is not None)
