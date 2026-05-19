"""Golden snapshot tests for ThemeSummarizer.generate_themed_news_sections.

This is the PR4 safety net. See .omc/plans/golden-snapshot-themed-news-sections.md
for the full plan. Only the `small` fixture is recorded here as the first
case; remaining fixtures (medium/large/cross-theme/...) will be added in
follow-up PRs as the plan is executed.

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
from tests.fixtures.themed_news import small as small_fixture  # noqa: E402


@pytest.fixture
def stub_favicon(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace _favicon_url with a deterministic stub.

    The real helper hits the urllib.parse.urlparse stdlib (deterministic),
    but the plan calls for stubbing to immunize the golden against any
    future caching/hashing changes inside the helper.
    """
    monkeypatch.setattr(
        "common.summarizer._favicon_url",
        lambda link: "https://stub.invalid/favicon.ico" if link else "",
    )


def test_generate_themed_news_sections_small(stub_favicon: None) -> None:
    summarizer = ThemeSummarizer(small_fixture.ITEMS)
    output = summarizer.generate_themed_news_sections(max_articles=5, featured_count=3)
    assert_golden("generate_themed_news_sections/small", output)
