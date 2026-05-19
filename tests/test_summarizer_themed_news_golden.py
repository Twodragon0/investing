"""Golden snapshot tests for ThemeSummarizer.generate_themed_news_sections.

This is the PR4 safety net. See .omc/plans/golden-snapshot-themed-news-sections.md
for the full plan. The fixtures cover the 8 cases from the plan's matrix:
``tiny_below_threshold``, ``small``, ``medium``, ``large``,
``cross_theme_dedup_heavy``, ``korean_only_titles``,
``mixed_lang_with_synthetic_desc``, and ``image_variants``.

To regenerate the golden after an intentional output change:
    UPDATE_GOLDEN=1 pytest tests/test_summarizer_themed_news_golden.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make `scripts/` importable as a top-level package (mirrors conftest.py setup).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from common.summarizer import ThemeSummarizer  # noqa: E402
from tests._golden import assert_golden  # noqa: E402
from tests.fixtures.themed_news import (  # noqa: E402
    cross_theme_dedup_heavy,
    image_variants,
    korean_only_titles,
    large,
    medium,
    mixed_lang_with_synthetic_desc,
    small,
    tiny_below_threshold,
)

# Each entry: (golden_name, fixture_module). The ``ITEMS`` list on each
# module is consumed verbatim by ThemeSummarizer so theme classification
# stays deterministic across runs.
_CASES = [
    ("tiny_below_threshold", tiny_below_threshold),
    ("small", small),
    ("medium", medium),
    ("large", large),
    ("cross_theme_dedup_heavy", cross_theme_dedup_heavy),
    ("korean_only_titles", korean_only_titles),
    ("mixed_lang_with_synthetic_desc", mixed_lang_with_synthetic_desc),
    ("image_variants", image_variants),
]


@pytest.fixture
def stub_favicon(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace _favicon_url with a deterministic stub.

    The real helper uses urllib.parse.urlparse (deterministic), but the plan
    calls for stubbing so the golden is immune to any future
    caching/hashing changes inside the helper. The stub returns a single
    fixed URL regardless of input link so all favicon-fallback rows render
    identically.
    """
    monkeypatch.setattr(
        "common.summarizer._favicon_url",
        lambda link: "https://stub.invalid/favicon.ico" if link else "",
    )


@pytest.mark.parametrize(("name", "fixture_mod"), _CASES, ids=[c[0] for c in _CASES])
def test_generate_themed_news_sections_golden(
    name: str,
    fixture_mod,
    stub_favicon: None,
) -> None:
    summarizer = ThemeSummarizer(fixture_mod.ITEMS)
    output = summarizer.generate_themed_news_sections(max_articles=5, featured_count=3)
    assert_golden(f"generate_themed_news_sections/{name}", output)
