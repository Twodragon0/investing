"""Golden snapshot tests for ThemeSummarizer.generate_themed_news_sections.

This is the PR4 safety net. See .omc/plans/golden-snapshot-themed-news-sections.md
for the full plan. The fixtures cover the 8 cases from the plan's matrix:
``tiny_below_threshold``, ``small``, ``medium``, ``large``,
``cross_theme_dedup_heavy``, ``korean_only_titles``,
``mixed_lang_with_synthetic_desc``, and ``image_variants``, plus
``punctuation_edge_cases`` added 2026-08-06 after a hyphen-truncation
regression reached main — the golden that caught it did so by accident.

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
    punctuation_edge_cases,
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
    ("punctuation_edge_cases", punctuation_edge_cases),
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


def test_update_golden_is_refused_in_ci(monkeypatch: pytest.MonkeyPatch) -> None:
    """`UPDATE_GOLDEN=1` in CI would make every golden rewrite itself and pass.

    Goldens exist to fail when output changes unexpectedly; a CI run that
    regenerates them proves nothing while staying green. CI never sets the var
    today — this pins that it cannot start doing so silently.
    """
    from tests._golden import assert_golden

    monkeypatch.setenv("UPDATE_GOLDEN", "1")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")

    with pytest.raises(AssertionError, match="vacuous"):
        assert_golden("generate_themed_news_sections/small", "anything")


def test_update_golden_still_works_locally(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The documented local workflow must keep working — the guard is CI-only."""
    from tests import _golden

    monkeypatch.setenv("UPDATE_GOLDEN", "1")
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setattr(_golden, "_SNAPSHOT_ROOT", tmp_path)

    _golden.assert_golden("scratch/case", "recorded output")
    assert (tmp_path / "scratch" / "case.txt").read_text(encoding="utf-8") == "recorded output"
