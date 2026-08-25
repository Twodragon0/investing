"""tests/test_backfill_images.py — backfill_images 단위 테스트."""

import importlib.util
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import backfill_images as bi
import pytest

# ---------------------------------------------------------------------------
# get_post_type
# ---------------------------------------------------------------------------


class TestGetPostType:
    def test_extracts_slug_from_standard_filename(self):
        assert bi.get_post_type("2026-08-25-daily-crypto-news-digest.md") == "daily-crypto-news-digest"

    def test_extracts_basename_from_full_path(self):
        assert bi.get_post_type("/some/dir/2026-08-25-daily-security-report.md") == "daily-security-report"

    def test_weekly_investment_digest_collapses_date_suffix(self):
        filename = "2026-08-25-weekly-investment-digest-2026-08-18.md"
        assert bi.get_post_type(filename) == "weekly-investment-digest"

    def test_no_match_returns_none(self):
        assert bi.get_post_type("not-a-valid-post-filename.md") is None

    def test_missing_extension_returns_none(self):
        assert bi.get_post_type("2026-08-25-daily-crypto-news-digest") is None


# ---------------------------------------------------------------------------
# get_date_from_filename
# ---------------------------------------------------------------------------


class TestGetDateFromFilename:
    def test_extracts_date_prefix(self):
        assert bi.get_date_from_filename("2026-08-25-test-post.md") == "2026-08-25"

    def test_no_date_returns_none(self):
        assert bi.get_date_from_filename("test-post.md") is None

    def test_malformed_date_single_digit_month_returns_none(self):
        assert bi.get_date_from_filename("2026-8-25-test-post.md") is None


# ---------------------------------------------------------------------------
# parse_frontmatter
# ---------------------------------------------------------------------------


class TestParseFrontmatter:
    def test_parses_fields_and_body(self):
        content = '---\ntitle: Test Post\ndescription: "A description here"\ndate: 2026-08-25\n---\nBody text.\n'
        fm, body = bi.parse_frontmatter(content)
        assert fm == {"title": "Test Post", "description": "A description here", "date": "2026-08-25"}
        assert body == "Body text."

    def test_strips_single_and_double_quotes(self):
        content = "---\ntitle: 'Single'\ndescription: \"Double\"\n---\nbody"
        fm, _ = bi.parse_frontmatter(content)
        assert fm["title"] == "Single"
        assert fm["description"] == "Double"

    def test_no_frontmatter_returns_empty_dict_and_original_body(self):
        content = "그냥 본문 내용입니다."
        fm, body = bi.parse_frontmatter(content)
        assert fm == {}
        assert body == content

    def test_unclosed_frontmatter_returns_empty_dict_and_original_body(self):
        content = "---\ntitle: Test\n계속되는 내용, 닫는 구분자가 없음"
        fm, body = bi.parse_frontmatter(content)
        assert fm == {}
        assert body == content

    def test_line_without_colon_is_ignored(self):
        content = "---\ntitle: Test\n콜론이없는줄\n---\nbody"
        fm, _ = bi.parse_frontmatter(content)
        assert fm == {"title": "Test"}

    def test_empty_content(self):
        fm, body = bi.parse_frontmatter("")
        assert fm == {}
        assert body == ""


# ---------------------------------------------------------------------------
# needs_image_refresh
# ---------------------------------------------------------------------------


class TestNeedsImageRefresh:
    def test_missing_file_returns_false(self, tmp_path):
        assert bi.needs_image_refresh(str(tmp_path / "missing.md")) is False

    def test_no_image_field_returns_true(self, tmp_path):
        p = tmp_path / "post.md"
        p.write_text("---\ntitle: Test\n---\nbody\n", encoding="utf-8")
        assert bi.needs_image_refresh(str(p)) is True

    def test_generic_og_prefix_returns_true(self, tmp_path):
        p = tmp_path / "post.md"
        p.write_text('---\nimage: "/assets/images/og-default.png"\n---\nbody\n', encoding="utf-8")
        assert bi.needs_image_refresh(str(p)) is True

    def test_generic_generated_og_prefix_returns_true(self, tmp_path):
        p = tmp_path / "post.md"
        p.write_text('---\nimage: "/assets/images/generated/og-briefing.png"\n---\nbody\n', encoding="utf-8")
        assert bi.needs_image_refresh(str(p)) is True

    def test_specific_generated_image_returns_false(self, tmp_path):
        p = tmp_path / "post.md"
        image = "/assets/images/generated/news-briefing-crypto-2026-08-25.png"
        p.write_text(f'---\nimage: "{image}"\n---\nbody\n', encoding="utf-8")
        assert bi.needs_image_refresh(str(p)) is False


# ---------------------------------------------------------------------------
# needs_image
# ---------------------------------------------------------------------------


class TestNeedsImage:
    def test_missing_file_returns_false(self, tmp_path):
        assert bi.needs_image(str(tmp_path / "missing.md")) is False

    def test_no_image_field_returns_true(self, tmp_path):
        p = tmp_path / "post.md"
        p.write_text("---\ntitle: Test\n---\nbody\n", encoding="utf-8")
        assert bi.needs_image(str(p)) is True

    def test_default_placeholder_returns_true(self, tmp_path):
        p = tmp_path / "post.md"
        p.write_text('---\nimage: "/assets/images/og-default.png"\n---\nbody\n', encoding="utf-8")
        assert bi.needs_image(str(p)) is True

    def test_missing_disk_file_returns_true(self, tmp_path, monkeypatch):
        monkeypatch.setattr("backfill_images.REPO_ROOT", str(tmp_path))
        p = tmp_path / "post.md"
        p.write_text('---\nimage: "/assets/images/generated/foo.png"\n---\nbody\n', encoding="utf-8")
        assert bi.needs_image(str(p)) is True

    def test_existing_disk_file_returns_false(self, tmp_path, monkeypatch):
        monkeypatch.setattr("backfill_images.REPO_ROOT", str(tmp_path))
        img_dir = tmp_path / "assets" / "images" / "generated"
        img_dir.mkdir(parents=True)
        (img_dir / "foo.png").write_text("png", encoding="utf-8")
        p = tmp_path / "post.md"
        p.write_text('---\nimage: "/assets/images/generated/foo.png"\n---\nbody\n', encoding="utf-8")
        assert bi.needs_image(str(p)) is False

    def test_non_absolute_image_path_returns_false(self, tmp_path):
        p = tmp_path / "post.md"
        p.write_text('---\nimage: "relative/path.png"\n---\nbody\n', encoding="utf-8")
        assert bi.needs_image(str(p)) is False


# ---------------------------------------------------------------------------
# extract_themes
# ---------------------------------------------------------------------------


class TestExtractThemes:
    def test_extracts_section_name_count_and_emoji(self):
        content = (
            "intro line\n"
            "## 비트코인 시장\n"
            "- BTC 상승세 지속\n"
            "- ETH 강세\n"
            "- 알트코인 회복\n"
            "## 규제 동향\n"
            "- SEC 조사 발표\n"
        )
        themes = bi.extract_themes(content, "daily-crypto-news-digest")
        assert themes[0]["name"] == "비트코인 시장"
        assert themes[0]["count"] == 3
        assert themes[0]["emoji"] == "\U0001f4b0"  # 비트코인 키워드 매칭
        assert themes[1]["name"] == "규제 동향"
        assert themes[1]["emoji"] == "⚖️"  # 규제 키워드 매칭

    def test_default_emoji_cycle_for_unknown_post_type(self):
        content = "## A\n- x\n## B\n- y\n"
        themes = bi.extract_themes(content, "totally-unknown-post-type")
        assert themes[0]["emoji"] == bi.DEFAULT_EMOJIS[0]
        assert themes[1]["emoji"] == bi.DEFAULT_EMOJIS[1]

    def test_max_themes_limits_result(self):
        sections = "".join(f"## Section {i}\n- item\n" for i in range(7))
        themes = bi.extract_themes(sections, "daily-news-summary", max_themes=3)
        assert len(themes) == 3

    def test_no_headings_returns_empty_list(self):
        assert bi.extract_themes("no headings here, just text", "daily-news-summary") == []

    def test_bullets_before_first_heading_are_discarded(self):
        content = "- orphan bullet 1\n- orphan bullet 2\n## Real Section\n- real bullet\n"
        themes = bi.extract_themes(content, "daily-news-summary")
        assert len(themes) == 1
        assert themes[0]["count"] == 1

    def test_keywords_captured_from_bullets(self):
        content = "## 시장 동향\n- 비트코인 급등 소식\n- 이더리움 강세 지속\n"
        themes = bi.extract_themes(content, "daily-crypto-news-digest")
        assert len(themes[0]["keywords"]) > 0

    def test_section_count_defaults_to_one_without_bullets(self):
        content = "## Empty Section\n\n## Next Section\n- bullet\n"
        themes = bi.extract_themes(content, "daily-news-summary")
        assert themes[0]["count"] == 1


# ---------------------------------------------------------------------------
# extract_categories_for_weekly
# ---------------------------------------------------------------------------


class TestExtractCategoriesForWeekly:
    def test_extracts_name_and_count(self):
        content = "## 암호화폐\n- 뉴스1\n- 뉴스2\n## 주식\n- 뉴스3\n"
        categories = bi.extract_categories_for_weekly(content)
        assert categories == [{"name": "암호화폐", "count": 2}, {"name": "주식", "count": 1}]

    def test_caps_at_eight_categories(self):
        sections = "".join(f"## Section {i}\n- item\n" for i in range(10))
        categories = bi.extract_categories_for_weekly(sections)
        assert len(categories) == 8

    def test_no_headings_returns_empty_list(self):
        assert bi.extract_categories_for_weekly("no headings here") == []


# ---------------------------------------------------------------------------
# extract_source_data
# ---------------------------------------------------------------------------


class TestExtractSourceData:
    def test_extracts_telegram_count(self):
        result = bi.extract_source_data("Telegram 채널에서 10건 발견")
        assert result == [{"name": "Telegram", "count": 10}]

    def test_extracts_korean_source_name(self):
        result = bi.extract_source_data("텔레그램에서 5건 발견되었습니다")
        assert result == [{"name": "텔레그램", "count": 5}]

    def test_zero_count_excluded(self):
        result = bi.extract_source_data("Telegram 0건 수집됨")
        assert result == []

    def test_dedups_by_name_case_insensitive(self):
        content = "Telegram 5건 수집, 이후 telegram 3건 추가 수집"
        result = bi.extract_source_data(content)
        assert len(result) == 1

    def test_no_match_returns_empty_list(self):
        assert bi.extract_source_data("아무 소스 정보도 없는 문장입니다") == []


# ---------------------------------------------------------------------------
# _match_emoji
# ---------------------------------------------------------------------------


class TestMatchEmoji:
    def test_matches_keyword_case_insensitively(self):
        emoji_map = {"BTC": "\U0001f4b0"}
        assert bi._match_emoji("btc 급등", emoji_map, idx=0) == "\U0001f4b0"

    def test_falls_back_to_default_emoji_cycle(self):
        assert bi._match_emoji("아무 매칭도 없는 섹션", {}, idx=0) == bi.DEFAULT_EMOJIS[0]
        assert bi._match_emoji("아무 매칭도 없는 섹션", {}, idx=5) == bi.DEFAULT_EMOJIS[0]
        assert bi._match_emoji("아무 매칭도 없는 섹션", {}, idx=1) == bi.DEFAULT_EMOJIS[1]

    def test_first_matching_keyword_wins(self):
        emoji_map = {"규제": "⚖️", "거래": "\U0001f4b0"}
        assert bi._match_emoji("규제 및 거래 동향", emoji_map, idx=0) == "⚖️"


# ---------------------------------------------------------------------------
# _dedupe_keywords
# ---------------------------------------------------------------------------


class TestDedupeKeywords:
    def test_removes_case_insensitive_duplicates(self):
        assert bi._dedupe_keywords(["BTC", "btc", "ETH"]) == ["BTC", "ETH"]

    def test_filters_single_char_keywords(self):
        assert bi._dedupe_keywords(["a", "bb"]) == ["bb"]

    def test_preserves_original_order(self):
        assert bi._dedupe_keywords(["ETH", "BTC", "eth"]) == ["ETH", "BTC"]

    def test_empty_list_returns_empty_list(self):
        assert bi._dedupe_keywords([]) == []


# ---------------------------------------------------------------------------
# extract_total_count
# ---------------------------------------------------------------------------


class TestExtractTotalCount:
    def test_pattern_chong_geon(self):
        assert bi.extract_total_count("오늘 총 42건 수집되었습니다.") == 42

    def test_pattern_chong_sujip_geon(self):
        assert bi.extract_total_count("총 수집 건수: 15건") == 15

    def test_pattern_geon_ui_news(self):
        assert bi.extract_total_count("오늘 20건의 뉴스가 있었습니다.") == 20

    def test_pattern_geon_eul_jeongri(self):
        assert bi.extract_total_count("30건을 정리했습니다.") == 30

    def test_pattern_geon_eul_yosong(self):
        assert bi.extract_total_count("30건을 요약했습니다.") == 30

    def test_no_match_returns_zero(self):
        assert bi.extract_total_count("아무 숫자도 없는 문장입니다.") == 0


# ---------------------------------------------------------------------------
# _load_image_generator
# ---------------------------------------------------------------------------


class TestLoadImageGenerator:
    """`_load_image_generator` 는 **실제 패키지를 디스크에서 로드**하는 경로를 검증한다.

    그래서 이 클래스만 `sys.modules` 복원이 필요하다. 프로덕션 코드는
    `sys.modules["common.image_generator"] = mod` 로 **이미 import 된 모듈 객체를
    통째로 교체**한다(`backfill_images.py:527`). conftest 의 autouse
    `_isolate_generated_images` 는 그 시점에 존재하던 **옛 객체**에
    `IMAGES_DIR` 를 monkeypatch 해 둔 상태이므로, 교체 이후의 `import
    common.image_generator` 는 리다이렉트가 없는 새 객체를 받는다.

    monkeypatch 의 되돌리기도 옛 객체에 적용되므로 오염이 **세션 끝까지 남는다** —
    2026-08-25 실측으로 이 파일을 함께 돌리면 `test_image_generator_coverage.py`
    등에서 트리-쓰기 가드가 60건 red 였다
    (`테스트가 커밋된 레포 트리에 썼습니다: assets/images/generated/...`).

    단독 실행에서는 절대 안 보인다 — 파일 하나만 돌리면 오염을 관측할 다른 테스트가
    없기 때문이다. 그래서 격리를 이 클래스에 못박는다.
    """

    @pytest.fixture(autouse=True)
    def _restore_image_generator_modules(self):
        """교체된 `sys.modules` 엔트리를 원래 객체로 되돌린다."""
        names = ("common.image_generator", "scripts.common.image_generator", "image_generator")
        saved = {name: sys.modules.get(name) for name in names}
        try:
            yield
        finally:
            for name, mod in saved.items():
                if mod is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = mod

    def _reset(self, monkeypatch):
        monkeypatch.setattr("backfill_images._IMG_GEN_LOADED", False)
        monkeypatch.setattr("backfill_images._IMG_GEN_MOD", None)

    def test_loads_real_module_with_expected_api(self, monkeypatch):
        self._reset(monkeypatch)
        mod = bi._load_image_generator()
        assert mod is not None
        assert hasattr(mod, "generate_news_briefing_card")
        assert hasattr(mod, "generate_news_summary_card")

    def test_caches_after_first_successful_call(self, monkeypatch):
        self._reset(monkeypatch)
        original_spec_from_file_location = importlib.util.spec_from_file_location
        spy = MagicMock(side_effect=original_spec_from_file_location)
        monkeypatch.setattr(importlib.util, "spec_from_file_location", spy)

        first = bi._load_image_generator()
        second = bi._load_image_generator()

        assert first is second
        assert spy.call_count == 1

    def test_returns_none_when_spec_loader_missing(self, monkeypatch):
        self._reset(monkeypatch)
        monkeypatch.setattr(importlib.util, "spec_from_file_location", lambda *a, **kw: None)

        assert bi._load_image_generator() is None


# ---------------------------------------------------------------------------
# generate_image_for_post
# ---------------------------------------------------------------------------


class TestGenerateImageForPost:
    def _fake_img_mod(self):
        return SimpleNamespace(
            generate_news_briefing_card=MagicMock(return_value="/assets/images/generated/mock-briefing.png"),
            generate_news_summary_card=MagicMock(return_value="/assets/images/generated/mock-summary.png"),
        )

    def test_returns_none_when_generator_unavailable(self, monkeypatch, tmp_path):
        monkeypatch.setattr("backfill_images._load_image_generator", lambda: None)
        result = bi.generate_image_for_post(str(tmp_path / "post.md"), "daily-crypto-news-digest", "2026-08-25", "본문")
        assert result is None

    def test_returns_existing_disk_image_without_generating(self, monkeypatch, tmp_path):
        img_mod = self._fake_img_mod()
        monkeypatch.setattr("backfill_images._load_image_generator", lambda: img_mod)
        monkeypatch.setattr("backfill_images.IMAGES_DIR", str(tmp_path))
        (tmp_path / "news-briefing-crypto-2026-08-25.png").write_text("png", encoding="utf-8")

        result = bi.generate_image_for_post("unused.md", "daily-crypto-news-digest", "2026-08-25", "본문")

        assert result == "/assets/images/generated/news-briefing-crypto-2026-08-25.png"
        img_mod.generate_news_briefing_card.assert_not_called()

    def test_uses_fallback_prefix_when_available_on_disk(self, monkeypatch, tmp_path):
        img_mod = self._fake_img_mod()
        monkeypatch.setattr("backfill_images._load_image_generator", lambda: img_mod)
        monkeypatch.setattr("backfill_images.IMAGES_DIR", str(tmp_path))
        (tmp_path / "market-snapshot-2026-08-25.png").write_text("png", encoding="utf-8")

        result = bi.generate_image_for_post("unused.md", "daily-stock-news-digest", "2026-08-25", "본문")

        assert result == "/assets/images/generated/market-snapshot-2026-08-25.png"

    def test_weekly_digest_uses_summary_card_with_categories(self, monkeypatch, tmp_path):
        img_mod = self._fake_img_mod()
        monkeypatch.setattr("backfill_images._load_image_generator", lambda: img_mod)
        monkeypatch.setattr("backfill_images.IMAGES_DIR", str(tmp_path))
        body = "## 암호화폐\n- 뉴스1\n- 뉴스2\n## 주식\n- 뉴스3\n"

        result = bi.generate_image_for_post("unused.md", "weekly-investment-digest", "2026-08-25", body)

        assert result == "/assets/images/generated/mock-summary.png"
        img_mod.generate_news_summary_card.assert_called_once()
        call_kwargs = img_mod.generate_news_summary_card.call_args.kwargs
        assert call_kwargs["date_str"] == "2026-08-25"
        assert call_kwargs["filename"] == "news-summary-weekly-2026-08-25.png"

    def test_default_type_uses_briefing_card_with_extracted_themes(self, monkeypatch, tmp_path):
        img_mod = self._fake_img_mod()
        monkeypatch.setattr("backfill_images._load_image_generator", lambda: img_mod)
        monkeypatch.setattr("backfill_images.IMAGES_DIR", str(tmp_path))
        body = "## 비트코인 소식\n- BTC 상승\n- ETH 강세\n"

        result = bi.generate_image_for_post("unused.md", "daily-crypto-news-digest", "2026-08-25", body)

        assert result == "/assets/images/generated/mock-briefing.png"
        call_kwargs = img_mod.generate_news_briefing_card.call_args.kwargs
        assert call_kwargs["category"] == "Crypto News Briefing"
        assert len(call_kwargs["themes"]) == 1

    def test_empty_body_falls_back_to_single_category_theme(self, monkeypatch, tmp_path):
        img_mod = self._fake_img_mod()
        monkeypatch.setattr("backfill_images._load_image_generator", lambda: img_mod)
        monkeypatch.setattr("backfill_images.IMAGES_DIR", str(tmp_path))

        bi.generate_image_for_post("unused.md", "daily-crypto-news-digest", "2026-08-25", "")

        call_kwargs = img_mod.generate_news_briefing_card.call_args.kwargs
        themes = call_kwargs["themes"]
        assert len(themes) == 1
        assert themes[0]["name"] == "Crypto News Briefing"


# ---------------------------------------------------------------------------
# update_frontmatter_image
# ---------------------------------------------------------------------------


class TestUpdateFrontmatterImage:
    def test_inserts_image_after_description_line(self, tmp_path):
        p = tmp_path / "post.md"
        p.write_text('---\ntitle: Test\ndescription: "desc here"\ndate: 2026-08-25\n---\nbody\n', encoding="utf-8")

        result = bi.update_frontmatter_image(str(p), "/assets/images/generated/foo.png")

        assert result is True
        content = p.read_text(encoding="utf-8")
        assert 'image: "/assets/images/generated/foo.png"' in content
        lines = content.splitlines()
        desc_idx = next(i for i, line in enumerate(lines) if line.startswith("description:"))
        assert lines[desc_idx + 1].startswith("image:")

    def test_replaces_existing_image_field(self, tmp_path):
        p = tmp_path / "post.md"
        p.write_text('---\ntitle: Test\nimage: "/old/path.png"\n---\nbody\n', encoding="utf-8")

        bi.update_frontmatter_image(str(p), "/new/path.png")

        content = p.read_text(encoding="utf-8")
        assert "/old/path.png" not in content
        assert 'image: "/new/path.png"' in content

    def test_inserts_at_end_when_no_description_field(self, tmp_path):
        p = tmp_path / "post.md"
        p.write_text("---\ntitle: Test\n---\nbody\n", encoding="utf-8")

        result = bi.update_frontmatter_image(str(p), "/assets/images/generated/foo.png")

        assert result is True
        assert 'image: "/assets/images/generated/foo.png"' in p.read_text(encoding="utf-8")

    def test_returns_false_without_frontmatter(self, tmp_path):
        p = tmp_path / "post.md"
        original = "no frontmatter body text"
        p.write_text(original, encoding="utf-8")

        result = bi.update_frontmatter_image(str(p), "/foo.png")

        assert result is False
        assert p.read_text(encoding="utf-8") == original

    def test_returns_false_when_frontmatter_unclosed(self, tmp_path):
        p = tmp_path / "post.md"
        original = "---\ntitle: Test\nno closing delimiter here"
        p.write_text(original, encoding="utf-8")

        result = bi.update_frontmatter_image(str(p), "/foo.png")

        assert result is False
        assert p.read_text(encoding="utf-8") == original

    def test_preserves_korean_body_content(self, tmp_path):
        p = tmp_path / "post.md"
        p.write_text("---\ntitle: Test\n---\n본문 내용입니다.\n", encoding="utf-8")

        bi.update_frontmatter_image(str(p), "/foo.png")

        assert "본문 내용입니다." in p.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# collect_target_posts
# ---------------------------------------------------------------------------


class TestCollectTargetPosts:
    def test_missing_posts_dir_returns_empty_list(self, tmp_path, monkeypatch):
        monkeypatch.setattr("backfill_images.POSTS_DIR", str(tmp_path / "nonexistent"))
        assert bi.collect_target_posts() == []

    def test_collects_only_posts_missing_image(self, tmp_path, monkeypatch):
        posts_dir = tmp_path / "_posts"
        posts_dir.mkdir()
        monkeypatch.setattr("backfill_images.POSTS_DIR", str(posts_dir))
        monkeypatch.setattr("backfill_images.REPO_ROOT", str(tmp_path))

        no_image = posts_dir / "2026-08-25-a.md"
        no_image.write_text("---\ntitle: A\n---\nbody\n", encoding="utf-8")

        img_dir = tmp_path / "assets" / "images" / "generated"
        img_dir.mkdir(parents=True)
        (img_dir / "foo.png").write_text("png", encoding="utf-8")
        has_image = posts_dir / "2026-08-25-b.md"
        has_image.write_text('---\ntitle: B\nimage: "/assets/images/generated/foo.png"\n---\nbody\n', encoding="utf-8")

        result = bi.collect_target_posts()

        assert result == [str(no_image)]

    def test_files_param_excludes_paths_outside_posts_dir(self, tmp_path, monkeypatch):
        posts_dir = tmp_path / "_posts"
        posts_dir.mkdir()
        monkeypatch.setattr("backfill_images.POSTS_DIR", str(posts_dir))
        monkeypatch.setattr("backfill_images.REPO_ROOT", str(tmp_path))

        inside = posts_dir / "2026-08-25-a.md"
        inside.write_text("---\ntitle: A\n---\nbody\n", encoding="utf-8")
        outside = tmp_path / "2026-08-25-outside.md"
        outside.write_text("---\ntitle: Outside\n---\nbody\n", encoding="utf-8")

        result = bi.collect_target_posts(files=[str(inside), str(outside)])

        assert result == [str(inside)]

    def test_rewrite_og_flag_includes_generic_og_image_posts(self, tmp_path, monkeypatch):
        posts_dir = tmp_path / "_posts"
        posts_dir.mkdir()
        monkeypatch.setattr("backfill_images.POSTS_DIR", str(posts_dir))
        monkeypatch.setattr("backfill_images.REPO_ROOT", str(tmp_path))

        img_dir = tmp_path / "assets" / "images" / "generated"
        img_dir.mkdir(parents=True)
        (img_dir / "og-foo.png").write_text("png", encoding="utf-8")

        post = posts_dir / "2026-08-25-og.md"
        post.write_text('---\ntitle: OG\nimage: "/assets/images/generated/og-foo.png"\n---\nbody\n', encoding="utf-8")

        assert bi.collect_target_posts(rewrite_og=False) == []
        assert bi.collect_target_posts(rewrite_og=True) == [str(post)]
