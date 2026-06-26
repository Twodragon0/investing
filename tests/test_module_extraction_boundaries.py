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
        for name in (
            "_build_market_signal_section",
            "_build_snapshot_table",
            "_build_overview_section",
            "_build_briefing_section",
            "_build_priority_and_category_sections",
            "_render_generated_image",
            "_analyze_sentiment",
        ):
            assert getattr(gds, name).__module__ == "common.summary_sections", (
                f"gds.{name} must live in common.summary_sections"
            )

    def test_moved_constants_are_same_object_via_reexport(self):
        import common.summary_sections as ss

        for const in ("_SUMMARY_KEYWORD_LABELS", "_REPORT_CATEGORY_LABELS", "_NOISE_TITLE_PATTERNS"):
            assert getattr(gds, const) is getattr(ss, const)

    def test_orchestration_stays_in_parent_module(self):
        # main()/IO orchestration must NOT be pulled into the extracted module —
        # they own gds.POSTS_DIR / gds.datetime that integration tests patch.
        for name in ("main", "_write_summary_post", "_load_today_posts", "_resolve_frontmatter_image"):
            assert getattr(gds, name).__module__ != "common.summary_sections", (
                f"gds.{name} should stay in the parent module (owns patched globals)"
            )

    def test_render_image_posts_dir_boundary_is_documented(self):
        # _render_generated_image moved to summary_sections, so it reads
        # summary_sections.POSTS_DIR — NOT gds.POSTS_DIR. main() integration tests
        # must patch both bindings (see TestMainIntegration._patch_posts_dir).
        import common.summary_sections as ss

        assert gds._render_generated_image.__module__ == "common.summary_sections"
        assert hasattr(ss, "POSTS_DIR")
