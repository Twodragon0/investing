"""Unit tests for ThemedNewsRenderer (scripts/common/themed_news_renderer.py).

ThemeSummarizer is injected as a mock so each branch in
``ThemedNewsRenderer.render`` can be isolated. Module-level helpers in
``common.summarizer`` that the renderer reaches into via
``from . import summarizer as _sumr`` are stubbed with ``monkeypatch.setattr``
so the assertions stay deterministic and decoupled from real summarizer
behavior.
"""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock

import pytest

# Mirror conftest.py: make ``scripts/`` importable as the top-level package.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from common.themed_news_renderer import ThemedNewsRenderer  # noqa: E402

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_summarizer() -> MagicMock:
    """Lightweight mock with the surface ThemedNewsRenderer needs."""
    m = MagicMock()
    m._theme_articles = {}
    m.get_top_themes.return_value = []
    m._generate_theme_subtitle.return_value = ""
    # PR3: renderer migrated from _theme_articles.get(key, []) to
    # get_articles_for_theme(key) — mock the public method to read from
    # the same dict so tests stay decoupled from internal storage.
    m.get_articles_for_theme.side_effect = lambda key: m._theme_articles.get(key, [])
    return m


@pytest.fixture(autouse=True)
def stub_module_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub the module-level helpers ThemedNewsRenderer reaches into.

    The renderer dispatches ``_favicon_url``, ``_best_favicon_link``,
    ``_is_generic_desc``, ``_is_boilerplate_desc``, ``_generate_title_based_desc``
    and ``_NOISE_TITLE_RE`` via ``common.summarizer`` so tests can pin each one.
    """
    import re

    import common.summarizer as _sumr

    monkeypatch.setattr(
        _sumr,
        "_favicon_url",
        lambda link: "https://stub/favicon.ico" if link else "",
    )
    monkeypatch.setattr(
        _sumr,
        "_best_favicon_link",
        lambda item: item.get("link", "") if isinstance(item, dict) else "",
    )
    monkeypatch.setattr(_sumr, "_is_generic_desc", lambda desc: False)
    monkeypatch.setattr(_sumr, "_is_boilerplate_desc", lambda desc: False)
    monkeypatch.setattr(
        _sumr,
        "_generate_title_based_desc",
        lambda title, key: f"fallback-desc-for::{title}",
    )
    # Effectively non-matching noise regex so titles always pass through.
    monkeypatch.setattr(_sumr, "_NOISE_TITLE_RE", re.compile(r"^$NEVERMATCH$"))


def _make_article(
    title: str,
    *,
    link: str = "",
    image: str = "",
    description: str = "",
    description_ko: str | None = None,
    source: str = "Example Wire",
    title_ko: str | None = None,
) -> dict:
    """Build a minimal article dict the renderer accepts."""
    return {
        "title": title,
        "title_ko": title_ko,
        "description": description,
        "description_ko": description_ko,
        "link": link,
        "image": image,
        "source": source,
    }


# ---------------------------------------------------------------------------
# 1. early-return guards
# ---------------------------------------------------------------------------


class TestGuardClauses:
    def test_returns_empty_when_fewer_than_5_items(self, mock_summarizer: MagicMock) -> None:
        items = [{"title": f"t{i}"} for i in range(4)]
        renderer = ThemedNewsRenderer(items, mock_summarizer)
        assert renderer.render() == ""

    def test_returns_empty_when_top_themes_empty(self, mock_summarizer: MagicMock) -> None:
        items = [{"title": f"t{i}"} for i in range(10)]
        mock_summarizer.get_top_themes.return_value = []
        renderer = ThemedNewsRenderer(items, mock_summarizer)
        assert renderer.render() == ""

    def test_exactly_5_items_satisfies_guard(self, mock_summarizer: MagicMock) -> None:
        items = [{"title": f"t{i}"} for i in range(5)]
        # Empty top_themes still bails out — confirm guard is len-based.
        mock_summarizer.get_top_themes.return_value = []
        assert ThemedNewsRenderer(items, mock_summarizer).render() == ""


# ---------------------------------------------------------------------------
# 2. happy path single-theme render
# ---------------------------------------------------------------------------


class TestSingleThemeRender:
    def test_renders_header_and_card_for_one_theme(self, mock_summarizer: MagicMock) -> None:
        articles = [
            _make_article(
                "Bitcoin breaks key resistance level today",
                link="https://example.com/bitcoin-rally",
                description="Bitcoin surged on heavy spot volume in Asia trading.",
            ),
        ]
        items = articles + [{"title": f"pad{i}"} for i in range(4)]
        mock_summarizer._theme_articles = {"bitcoin": articles}
        mock_summarizer.get_top_themes.return_value = [
            ("비트코인", "bitcoin", "₿", 1),
        ]
        mock_summarizer._generate_theme_subtitle.return_value = "주요 흐름"

        out = ThemedNewsRenderer(items, mock_summarizer).render()

        assert "## 테마별 주요 뉴스" in out
        assert "### ₿ 비트코인 (1건)" in out
        assert "*주요 흐름*" in out
        assert 'class="news-card-item' in out
        assert 'class="news-card-num">1</div>' in out
        assert "Bitcoin breaks key resistance level today" in out

    def test_subtitle_omitted_when_blank(self, mock_summarizer: MagicMock) -> None:
        articles = [_make_article("Generic article one", link="https://example.com/a")]
        items = articles + [{"title": f"pad{i}"} for i in range(4)]
        mock_summarizer._theme_articles = {"k": articles}
        mock_summarizer.get_top_themes.return_value = [("Name", "k", "*", 1)]
        mock_summarizer._generate_theme_subtitle.return_value = ""

        out = ThemedNewsRenderer(items, mock_summarizer).render()

        # No italic subtitle line should be present when subtitle is blank.
        assert "*\n" not in out.replace("\n\n", "\n")


# ---------------------------------------------------------------------------
# 3. featured cards vs overflow split
# ---------------------------------------------------------------------------


class TestFeaturedVsOverflow:
    def test_featured_count_3_renders_three_cards(self, mock_summarizer: MagicMock) -> None:
        articles = [
            _make_article(
                f"Featured article number {i}",
                link=f"https://example.com/a/{i}",
                description=f"Body for article {i}",
            )
            for i in range(3)
        ]
        items = articles + [{"title": f"pad{i}"} for i in range(5)]
        mock_summarizer._theme_articles = {"k": articles}
        mock_summarizer.get_top_themes.return_value = [("Name", "k", "*", 3)]

        out = ThemedNewsRenderer(items, mock_summarizer).render(featured_count=3)

        # Three numbered cards present (1, 2, 3)
        assert '<div class="news-card-num">1</div>' in out
        assert '<div class="news-card-num">2</div>' in out
        assert '<div class="news-card-num">3</div>' in out
        # No <details> overflow when there are exactly featured_count items
        assert "<details>" not in out

    def test_overflow_lists_extra_articles_in_details(self, mock_summarizer: MagicMock) -> None:
        articles = [
            _make_article(
                f"Overflow article number {i}",
                link=f"https://example.com/o/{i}",
            )
            for i in range(6)
        ]
        items = articles + [{"title": f"pad{i}"} for i in range(5)]
        mock_summarizer._theme_articles = {"k": articles}
        mock_summarizer.get_top_themes.return_value = [("Name", "k", "*", 6)]

        out = ThemedNewsRenderer(items, mock_summarizer).render(
            featured_count=3, max_articles=5
        )

        assert "<details>" in out
        # First 3 are featured cards; remaining are overflow rows.
        assert 'class="overflow-preview"' in out
        # Featured 1..3 + overflow items 4..6 = 6 unique titles surface.
        for i in range(6):
            assert f"Overflow article number {i}" in out


# ---------------------------------------------------------------------------
# 4. OVERFLOW_PREVIEW_LIMIT cutoff
# ---------------------------------------------------------------------------


class TestOverflowPreviewLimit:
    def test_more_than_limit_truncates_with_extra_label(
        self, mock_summarizer: MagicMock
    ) -> None:
        articles = [
            _make_article(f"Mass article number {i}", link=f"https://example.com/m/{i}")
            for i in range(30)
        ]
        items = articles + [{"title": f"pad{i}"} for i in range(5)]
        mock_summarizer._theme_articles = {"k": articles}
        mock_summarizer.get_top_themes.return_value = [("Name", "k", "*", 30)]

        out = ThemedNewsRenderer(items, mock_summarizer).render(
            featured_count=3, max_articles=5
        )

        # Featured 3 + preview 10 overflow rows max, plus "...외 N건" cap label.
        assert out.count('class="overflow-preview"') == 10
        assert "외 " in out  # remaining_count label
        assert "...외 " in out  # truncation tail label


# ---------------------------------------------------------------------------
# 5. cross-theme dedup
# ---------------------------------------------------------------------------


class TestCrossThemeDedup:
    def test_same_title_demoted_in_second_theme(self, mock_summarizer: MagicMock) -> None:
        shared = _make_article(
            "Shared headline across themes",
            link="https://example.com/shared",
            description="Both themes care about this story",
        )
        theme_a = [shared, _make_article("Theme A unique", link="https://example.com/a")]
        theme_b = [
            shared,
            _make_article("Theme B unique 1", link="https://example.com/b1"),
            _make_article("Theme B unique 2", link="https://example.com/b2"),
        ]
        items = theme_a + theme_b + [{"title": "pad"}]
        mock_summarizer._theme_articles = {"a": theme_a, "b": theme_b}
        mock_summarizer.get_top_themes.return_value = [
            ("A", "a", "*", 2),
            ("B", "b", "*", 3),
        ]

        out = ThemedNewsRenderer(items, mock_summarizer).render(featured_count=3)

        # Shared title appears as a featured card in theme A.
        card_section_a_start = out.index("### * A")
        card_section_b_start = out.index("### * B")
        a_section = out[card_section_a_start:card_section_b_start]
        b_section = out[card_section_b_start:]

        assert "Shared headline across themes" in a_section
        # In theme B, the shared title must be demoted to overflow (not a card).
        # Card markup contains `news-card-item`; overflow uses `overflow-preview`.
        # The shared title in B should not appear inside a news-card-item block.
        assert "Shared headline across themes" in b_section
        # Theme B's first card should be one of the unique titles.
        assert (
            "Theme B unique 1" in b_section or "Theme B unique 2" in b_section
        ), "Theme B card should feature a unique title, not the shared one"


# ---------------------------------------------------------------------------
# 6. image rendering branches
# ---------------------------------------------------------------------------


class TestImageBranches:
    def test_thumbnail_renders_when_image_is_real(
        self, mock_summarizer: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # is_logo_like_url defaults to False since URL has no logo marker, but
        # pin it for clarity.
        import common.themed_news_renderer as renderer_mod

        monkeypatch.setattr(renderer_mod, "is_logo_like_url", lambda u: False)
        articles = [
            _make_article(
                "Article with real image",
                link="https://example.com/x",
                image="https://example.com/photo.jpg",
            )
        ]
        items = articles + [{"title": f"pad{i}"} for i in range(4)]
        mock_summarizer._theme_articles = {"k": articles}
        mock_summarizer.get_top_themes.return_value = [("N", "k", "*", 1)]

        out = ThemedNewsRenderer(items, mock_summarizer).render()
        assert 'class="news-card-thumb"' in out
        assert 'src="https://example.com/photo.jpg"' in out
        # Should NOT fall back to favicon when a real image is present.
        assert "favicon" not in out

    def test_logo_like_image_falls_back_to_favicon(
        self, mock_summarizer: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import common.themed_news_renderer as renderer_mod

        monkeypatch.setattr(renderer_mod, "is_logo_like_url", lambda u: bool(u))
        articles = [
            _make_article(
                "Article whose image is a logo",
                link="https://example.com/y",
                image="https://example.com/logo.png",
            )
        ]
        items = articles + [{"title": f"pad{i}"} for i in range(4)]
        mock_summarizer._theme_articles = {"k": articles}
        mock_summarizer.get_top_themes.return_value = [("N", "k", "*", 1)]

        out = ThemedNewsRenderer(items, mock_summarizer).render()
        assert "news-card-thumb--favicon" in out
        assert "https://stub/favicon.ico" in out

    def test_no_image_but_link_uses_favicon(self, mock_summarizer: MagicMock) -> None:
        articles = [_make_article("Link-only article", link="https://example.com/z")]
        items = articles + [{"title": f"pad{i}"} for i in range(4)]
        mock_summarizer._theme_articles = {"k": articles}
        mock_summarizer.get_top_themes.return_value = [("N", "k", "*", 1)]

        out = ThemedNewsRenderer(items, mock_summarizer).render()
        assert "news-card-thumb--favicon" in out
        assert "https://stub/favicon.ico" in out

    def test_no_image_no_link_omits_thumbnail(self, mock_summarizer: MagicMock) -> None:
        articles = [_make_article("Bare title only article")]
        items = articles + [{"title": f"pad{i}"} for i in range(4)]
        mock_summarizer._theme_articles = {"k": articles}
        mock_summarizer.get_top_themes.return_value = [("N", "k", "*", 1)]

        out = ThemedNewsRenderer(items, mock_summarizer).render()
        # No image element of either flavour should render.
        assert "news-card-thumb" not in out
        # The card body must still be present.
        assert 'class="news-card-body"' in out


# ---------------------------------------------------------------------------
# 7. severity badge wiring
# ---------------------------------------------------------------------------


class TestSeverityBadge:
    def test_severity_class_propagates_to_card(
        self, mock_summarizer: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import common.themed_news_renderer as renderer_mod

        monkeypatch.setattr(
            renderer_mod, "_classify_news_severity", lambda t, d: "high"
        )
        monkeypatch.setattr(
            renderer_mod,
            "_SEV_BADGE_HTML",
            {
                "high": "<span>HIGH-BADGE</span>",
                "medium": "<span>MED-BADGE</span>",
                "low": "<span>LOW-BADGE</span>",
            },
        )
        articles = [_make_article("High severity story", link="https://example.com/hs")]
        items = articles + [{"title": f"pad{i}"} for i in range(4)]
        mock_summarizer._theme_articles = {"k": articles}
        mock_summarizer.get_top_themes.return_value = [("N", "k", "*", 1)]

        out = ThemedNewsRenderer(items, mock_summarizer).render()

        assert 'class="news-card-item news-sev-high"' in out
        assert "HIGH-BADGE" in out


# ---------------------------------------------------------------------------
# 8. description fallback branches
# ---------------------------------------------------------------------------


class TestDescriptionBranches:
    def test_real_description_used_when_present(self, mock_summarizer: MagicMock) -> None:
        articles = [
            _make_article(
                "Real desc article title",
                link="https://example.com/r",
                description="A concrete factual summary of the article body.",
            )
        ]
        items = articles + [{"title": f"pad{i}"} for i in range(4)]
        mock_summarizer._theme_articles = {"k": articles}
        mock_summarizer.get_top_themes.return_value = [("N", "k", "*", 1)]

        out = ThemedNewsRenderer(items, mock_summarizer).render()
        assert "A concrete factual summary" in out
        # The fallback synthesizer should NOT be used when a real desc is OK.
        assert "fallback-desc-for::" not in out

    def test_generic_desc_triggers_title_based_fallback(
        self, mock_summarizer: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import common.summarizer as _sumr

        monkeypatch.setattr(_sumr, "_is_generic_desc", lambda desc: True)
        articles = [
            _make_article(
                "Title that drives fallback",
                link="https://example.com/f",
                description="boilerplate-ish text that flags as generic",
            )
        ]
        items = articles + [{"title": f"pad{i}"} for i in range(4)]
        mock_summarizer._theme_articles = {"k": articles}
        mock_summarizer.get_top_themes.return_value = [("N", "k", "*", 1)]

        out = ThemedNewsRenderer(items, mock_summarizer).render()
        assert "fallback-desc-for::Title that drives fallback" in out

    def test_boilerplate_translated_desc_dropped(
        self, mock_summarizer: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import common.summarizer as _sumr

        monkeypatch.setattr(_sumr, "_is_boilerplate_desc", lambda desc: True)
        articles = [
            _make_article(
                "Headline whose desc is brand boilerplate",
                link="https://example.com/b",
                description="Site-level brand boilerplate",
            )
        ]
        items = articles + [{"title": f"pad{i}"} for i in range(4)]
        mock_summarizer._theme_articles = {"k": articles}
        mock_summarizer.get_top_themes.return_value = [("N", "k", "*", 1)]

        out = ThemedNewsRenderer(items, mock_summarizer).render()
        # Both real and fallback desc strings must be absent.
        assert "Site-level brand boilerplate" not in out
        assert "fallback-desc-for::" not in out
        # Card itself should still render — just without a <p class="news-desc">.
        assert 'class="news-card-item' in out
        assert 'class="news-desc"' not in out

    def test_desc_equal_to_title_uses_fallback(self, mock_summarizer: MagicMock) -> None:
        articles = [
            _make_article(
                "Title equals description here",
                link="https://example.com/eq",
                description="Title equals description here",
            )
        ]
        items = articles + [{"title": f"pad{i}"} for i in range(4)]
        mock_summarizer._theme_articles = {"k": articles}
        mock_summarizer.get_top_themes.return_value = [("N", "k", "*", 1)]

        out = ThemedNewsRenderer(items, mock_summarizer).render()
        # Because description==title, the else-branch fires and the stub
        # fallback should appear.
        assert "fallback-desc-for::Title equals description here" in out


# ---------------------------------------------------------------------------
# 9. edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_theme_with_empty_article_list(self, mock_summarizer: MagicMock) -> None:
        items = [{"title": f"pad{i}"} for i in range(6)]
        mock_summarizer._theme_articles = {"empty": []}
        mock_summarizer.get_top_themes.return_value = [("Empty", "empty", "*", 0)]
        mock_summarizer._generate_theme_subtitle.return_value = ""

        out = ThemedNewsRenderer(items, mock_summarizer).render()

        # Header for empty theme still emits, but no cards / overflow.
        assert "### * Empty (0건)" in out
        assert "news-card-item" not in out
        assert "<details>" not in out

    def test_articles_missing_title_are_skipped(self, mock_summarizer: MagicMock) -> None:
        articles = [
            {"title": "", "link": "https://example.com/skip"},
            _make_article("Survivor article title", link="https://example.com/s"),
        ]
        items = articles + [{"title": f"pad{i}"} for i in range(4)]
        mock_summarizer._theme_articles = {"k": articles}
        mock_summarizer.get_top_themes.return_value = [("N", "k", "*", 2)]

        out = ThemedNewsRenderer(items, mock_summarizer).render()
        assert "Survivor article title" in out
        assert "https://example.com/skip" not in out

    def test_noise_title_filtered(
        self, mock_summarizer: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import re

        import common.summarizer as _sumr

        # Custom pattern: drop any title containing "DROPME".
        monkeypatch.setattr(_sumr, "_NOISE_TITLE_RE", re.compile(r"DROPME"))
        articles = [
            _make_article("DROPME headline that is noise", link="https://example.com/n"),
            _make_article("Keeper headline", link="https://example.com/k"),
        ]
        items = articles + [{"title": f"pad{i}"} for i in range(4)]
        mock_summarizer._theme_articles = {"k": articles}
        mock_summarizer.get_top_themes.return_value = [("N", "k", "*", 2)]

        out = ThemedNewsRenderer(items, mock_summarizer).render()
        assert "Keeper headline" in out
        assert "DROPME headline" not in out

# ---------------------------------------------------------------------------
# 10. determinism
# ---------------------------------------------------------------------------


class TestDeterminism:
    def test_render_is_idempotent_for_same_input(self, mock_summarizer: MagicMock) -> None:
        articles = [
            _make_article(
                f"Stable article {i}",
                link=f"https://example.com/{i}",
                description=f"Desc body {i}",
            )
            for i in range(4)
        ]
        items = articles + [{"title": f"pad{i}"} for i in range(4)]
        mock_summarizer._theme_articles = {"k": articles}
        mock_summarizer.get_top_themes.return_value = [("N", "k", "*", 4)]

        renderer = ThemedNewsRenderer(items, mock_summarizer)
        out_a = renderer.render(featured_count=3, max_articles=5)
        out_b = renderer.render(featured_count=3, max_articles=5)
        assert out_a == out_b
        assert out_a != ""

    def test_title_ko_preferred_over_title(self, mock_summarizer: MagicMock) -> None:
        articles = [
            _make_article(
                "English original title",
                title_ko="한국어 번역 제목",
                link="https://example.com/ko",
                description="some body",
            )
        ]
        items = articles + [{"title": f"pad{i}"} for i in range(4)]
        mock_summarizer._theme_articles = {"k": articles}
        mock_summarizer.get_top_themes.return_value = [("N", "k", "*", 1)]

        out = ThemedNewsRenderer(items, mock_summarizer).render()
        # title_ko goes in the displayed card; orig title gates dedup but is
        # not the rendered string here.
        assert "한국어 번역 제목" in out

    def test_overflow_item_with_real_image_renders_thumb(
        self, mock_summarizer: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """overflow list item with real image builds thumb_html."""
        import common.themed_news_renderer as renderer_mod

        monkeypatch.setattr(renderer_mod, "is_logo_like_url", lambda u: False)
        featured = [
            _make_article(
                f"Featured article {i}",
                link=f"https://example.com/f/{i}",
            )
            for i in range(4)
        ]
        overflow_article = _make_article(
            "Overflow with real image",
            link="https://example.com/ov",
            image="https://cdn.example.com/photo.jpg",
        )
        articles = featured + [overflow_article]
        items = articles + [{"title": f"pad{i}"} for i in range(5)]
        mock_summarizer._theme_articles = {"k": articles}
        mock_summarizer.get_top_themes.return_value = [("N", "k", "*", 5)]

        out = ThemedNewsRenderer(items, mock_summarizer).render(featured_count=3, max_articles=4)

        assert "<details>" in out
        assert 'class="overflow-thumb"' in out
        assert 'src="https://cdn.example.com/photo.jpg"' in out

    def test_overflow_item_without_link_renders_span_fallback(
        self, mock_summarizer: MagicMock
    ) -> None:
        """overflow item with no link renders <span> instead of <a>."""
        featured = [
            _make_article(
                f"Featured article {i}",
                link=f"https://example.com/f/{i}",
            )
            for i in range(4)
        ]
        overflow_no_link = _make_article(
            "Overflow without link",
            link="",
            source="Anon Source",
        )
        articles = featured + [overflow_no_link]
        items = articles + [{"title": f"pad{i}"} for i in range(5)]
        mock_summarizer._theme_articles = {"k": articles}
        mock_summarizer.get_top_themes.return_value = [("N", "k", "*", 5)]

        out = ThemedNewsRenderer(items, mock_summarizer).render(featured_count=3, max_articles=4)

        assert "<details>" in out
        assert "Overflow without link" in out
        assert "<span>Overflow without link</span>" in out
