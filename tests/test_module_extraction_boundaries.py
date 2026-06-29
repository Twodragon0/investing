"""Module-extraction boundary guards.

These tests document and protect the re-export boundaries created when large
generators were split into focused `common.*` modules:

- `generate_og_images` → `common.og_compose` (generate_og_image body) +
  `common.og_image_formats` (PNG→WebP/AVIF conversion)
- `generate_daily_summary` → `common.summary_sections` (section builders +
  sentiment/relation/Korean-text helpers)

Why this guard exists
---------------------
Tests patch internals via the *parent* module namespace
(`patch.object(og, "generate_og_image")`, `monkeypatch.setattr(gds, "...")`).
After extraction, a patched name only takes effect for code that reads it as a
**parent-module global** — code living in the extracted module reads the name
from *its own* module. So when mocking the internals of an extracted function
(e.g. `generate_og_image`'s call to `_convert_formats_parallel`), you must patch
the **owning** module (`common.og_compose` / `common.og_image_formats` /
`common.summary_sections`), not the parent. These assertions pin the owning
module so a future move (or a broken re-export) fails loudly here instead of
silently narrowing the patch surface.
"""

import sys

SCRIPTS_DIR = "scripts"
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import generate_og_images as og  # noqa: E402

import scripts.generate_daily_summary as gds  # noqa: E402


class TestOgImageBoundaries:
    """og.<name> re-exports resolve to their extracted owning modules."""

    def test_compose_symbols_owned_by_og_compose(self):
        for name in (
            "generate_og_image",
            "_extract_metrics",
            "_draw_data_chips",
            "safe_text",
            "wrap_text",
        ):
            assert getattr(og, name).__module__ == "common.og_compose", (
                f"og.{name} must live in common.og_compose — patch internals there, not on `og`"
            )

    def test_format_symbols_owned_by_og_image_formats(self):
        for name in ("_convert_to_webp", "_convert_to_avif", "_convert_formats_parallel"):
            assert getattr(og, name).__module__ == "common.og_image_formats", (
                f"og.{name} must live in common.og_image_formats"
            )

    def test_reexport_identity_matches_owning_module(self):
        import common.og_compose as og_compose
        import common.og_image_formats as fmt

        assert og.generate_og_image is og_compose.generate_og_image
        assert og._convert_formats_parallel is fmt._convert_formats_parallel
        # PIL availability state has a single source of truth in og_image_formats
        assert og._PIL_AVAILABLE is fmt._PIL_AVAILABLE
        assert og.PILImage is fmt.PILImage


class TestDailySummaryBoundaries:
    """gds.<name> re-exports resolve to common.summary_sections."""

    def test_section_builders_owned_by_summary_sections(self):
        # L2 = the 5 section builders only (2026-06-29 L2 split).
        for name in (
            "_build_market_signal_section",
            "_build_snapshot_table",
            "_build_overview_section",
            "_build_briefing_section",
            "_build_priority_and_category_sections",
        ):
            assert getattr(gds, name).__module__ == "common.summary_sections", (
                f"gds.{name} must live in common.summary_sections (L2)"
            )

    def test_analysis_helpers_owned_by_summary_analysis(self):
        # L1 = sentiment/relation/data helpers (incl. _render_generated_image).
        for name in (
            "_analyze_sentiment",
            "_cross_asset_topics",
            "_sentiment_keywords",
            "_extract_key_figures",
            "_find_shared_topics_across_categories",
            "_extract_category_data_points",
            "_topic_hits",
            "_relation_rows",
            "_coverage_warnings",
            "_render_generated_image",
        ):
            assert getattr(gds, name).__module__ == "common.summary_analysis", (
                f"gds.{name} must live in common.summary_analysis (L1)"
            )

    def test_text_ko_helpers_owned_by_summary_text_ko(self):
        # L0 = Korean-text/noise leaf helpers.
        for name in (
            "_strip_markdown_link",
            "_is_noise_title",
            "_clean_bullet_text",
            "_clean_headline",
            "_looks_english_heavy",
            "_headline_for_korean_summary",
            "_summary_keywords_for_korean",
            "_display_title_for_korean_item",
            "_description_for_korean_item",
            "_best_non_noise_title",
        ):
            assert getattr(gds, name).__module__ == "common.summary_text_ko", (
                f"gds.{name} must live in common.summary_text_ko (L0)"
            )

    def test_moved_constants_are_same_object_via_reexport(self):
        import common.summary_sections as ss
        import common.summary_text_ko as ko

        # L0 constants live in summary_text_ko, L2 constant in summary_sections.
        assert gds._SUMMARY_KEYWORD_LABELS is ko._SUMMARY_KEYWORD_LABELS
        assert gds._NOISE_TITLE_PATTERNS is ko._NOISE_TITLE_PATTERNS
        assert gds._REPORT_CATEGORY_LABELS is ss._REPORT_CATEGORY_LABELS

    def test_layering_is_unidirectional(self):
        # L2 → L1 → L0; lower layers must not import the parent module or a
        # higher layer. Inspect actual import statements (not docstring prose).
        import ast

        import common.summary_analysis as analysis
        import common.summary_text_ko as ko

        def imported_modules(module):
            with open(module.__file__, encoding="utf-8") as f:
                tree = ast.parse(f.read())
            mods = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    mods.add(node.module)
                elif isinstance(node, ast.Import):
                    mods.update(a.name for a in node.names)
            return mods

        forbidden_parent = {"generate_daily_summary", "scripts.generate_daily_summary"}
        # L1 must not import the parent orchestration module
        assert not (imported_modules(analysis) & forbidden_parent)
        # L0 is a true leaf: no parent, no L1, no L2
        ko_imports = imported_modules(ko)
        assert not (ko_imports & forbidden_parent)
        assert "common.summary_analysis" not in ko_imports
        assert "common.summary_sections" not in ko_imports

    def test_orchestration_stays_in_parent_module(self):
        # main()/IO orchestration must NOT be pulled into the extracted modules —
        # they own gds.POSTS_DIR / gds.datetime that integration tests patch.
        extracted = {"common.summary_sections", "common.summary_analysis", "common.summary_text_ko"}
        for name in ("main", "_write_summary_post", "_load_today_posts", "_resolve_frontmatter_image"):
            assert getattr(gds, name).__module__ not in extracted, (
                f"gds.{name} should stay in the parent module (owns patched globals)"
            )

    def test_render_image_posts_dir_boundary_is_documented(self):
        # _render_generated_image moved to summary_analysis (L1), so it reads
        # summary_analysis.POSTS_DIR — NOT gds.POSTS_DIR. main() integration tests
        # must patch both bindings (see TestMainIntegration._patch_posts_dir).
        import common.summary_analysis as analysis

        assert gds._render_generated_image.__module__ == "common.summary_analysis"
        assert hasattr(analysis, "POSTS_DIR")


class TestSummaryPostHelperBoundaries:
    """gds.<name> re-exports for the earlier categorizer/parsing extractions."""

    def test_categorizers_owned_by_summary_post_categorizers(self):
        for name in (
            "_extract_bold_lines",
            "summarize_crypto_post",
            "summarize_market_post",
            "summarize_political_post",
            "summarize_regulatory_post",
            "summarize_security_post",
            "summarize_social_post",
            "summarize_stock_post",
            "summarize_worldmonitor_post",
        ):
            assert getattr(gds, name).__module__ == "common.summary_post_categorizers", (
                f"gds.{name} must live in common.summary_post_categorizers"
            )

    def test_parsing_helpers_owned_by_summary_post_parsing(self):
        for name in (
            "_extract_highlights",
            "_is_similar_title",
            "count_news_items",
            "extract_bullet_points",
            "extract_section",
            "extract_table_rows",
            "read_post_content",
            "strip_html_tags",
        ):
            assert getattr(gds, name).__module__ == "common.summary_post_parsing", (
                f"gds.{name} must live in common.summary_post_parsing"
            )

    def test_reexport_identity_matches_owning_modules(self):
        import common.summary_post_categorizers as cat
        import common.summary_post_parsing as par

        assert gds.summarize_crypto_post is cat.summarize_crypto_post
        assert gds.read_post_content is par.read_post_content
