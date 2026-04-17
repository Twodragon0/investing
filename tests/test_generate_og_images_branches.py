"""Regression tests for --thumbnails-only and --update-frontmatter branches.

--thumbnails-only 분기 (4 케이스):
1. og 있고 thumb 없음  → generate_thumbnail 호출됨 (generate_thumbnail 자체가 존재 여부 판단)
2. og 있고 thumb 있음  → generate_thumbnail 호출됨 (--thumbnails-only는 skip 로직 없음)
3. og 없음             → generate_thumbnail 호출됨, 반환값 False (og 없으면 내부 실패)
4. --force 조합        → generate_og_image 미호출, generate_thumbnail만 호출됨

--update-frontmatter 분기 (4 케이스):
5. og 새로 생성 성공 + update_frontmatter=True → update_post_frontmatter 호출, updated += 1
6. og 이미 존재 (skip 분기)                    → update_post_frontmatter 미호출
7. og 있고 thumb 없는 backfill 분기            → update_post_frontmatter 미호출
8. update_post_frontmatter False 반환           → updated 카운트 증가하지 않음
"""

import argparse
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Import guard
# ---------------------------------------------------------------------------

try:
    import generate_og_images as og

    _IMPORT_OK = True
except Exception:
    og = None  # type: ignore
    _IMPORT_OK = False

pytestmark = pytest.mark.skipif(
    not _IMPORT_OK, reason="generate_og_images could not be imported"
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FAKE_SLUG = "test-post"
_FAKE_DATE = "2026-04-17"

FAKE_POST = {
    "slug": _FAKE_SLUG,
    "date": _FAKE_DATE,
    "title": "Test Post Title",
    "description": "A short description for testing.",
    "category": "crypto-news",
    "filepath": "/fake/_posts/2026-04-17-test-post.md",
}


def _make_args(**kwargs) -> argparse.Namespace:
    """Return an argparse.Namespace with sensible defaults."""
    defaults = {
        "date": _FAKE_DATE,
        "all_posts": False,
        "force": False,
        "update_frontmatter": False,
        "categories": None,
        "thumbnails_only": False,
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


# ---------------------------------------------------------------------------
# TestThumbnailsOnlyBranch
# ---------------------------------------------------------------------------


class TestThumbnailsOnlyBranch:
    """--thumbnails-only 플래그 분기 검증."""

    def test_og_exists_thumb_missing_calls_generate_thumbnail(self, tmp_path, monkeypatch):
        """og 있고 thumb 없음: generate_thumbnail이 호출된다."""
        monkeypatch.setattr(og, "IMAGES_DIR", str(tmp_path))

        og_path = tmp_path / f"og-{_FAKE_SLUG}-{_FAKE_DATE}.png"
        og_path.write_bytes(b"PNG")
        # thumb 미생성 (의도적)

        args = _make_args(thumbnails_only=True)
        mock_gen_og = MagicMock(return_value=True)
        mock_gen_thumb = MagicMock(return_value=True)

        with (
            patch.object(og, "collect_posts", return_value=[FAKE_POST]),
            patch.object(og, "generate_og_image", mock_gen_og),
            patch.object(og, "generate_thumbnail", mock_gen_thumb),
            patch.object(og, "_MPL_AVAILABLE", True),
            patch("argparse.ArgumentParser.parse_args", return_value=args),
        ):
            og.main()

        mock_gen_thumb.assert_called_once_with(str(og_path))
        mock_gen_og.assert_not_called()

    def test_og_exists_thumb_exists_still_calls_generate_thumbnail(self, tmp_path, monkeypatch):
        """og + thumb 모두 존재해도 --thumbnails-only는 skip 없이 generate_thumbnail을 호출한다."""
        monkeypatch.setattr(og, "IMAGES_DIR", str(tmp_path))

        og_path = tmp_path / f"og-{_FAKE_SLUG}-{_FAKE_DATE}.png"
        thumb_path = tmp_path / f"thumb-og-{_FAKE_SLUG}-{_FAKE_DATE}.png"
        og_path.write_bytes(b"PNG")
        thumb_path.write_bytes(b"PNG")

        args = _make_args(thumbnails_only=True)
        mock_gen_og = MagicMock(return_value=True)
        mock_gen_thumb = MagicMock(return_value=True)

        with (
            patch.object(og, "collect_posts", return_value=[FAKE_POST]),
            patch.object(og, "generate_og_image", mock_gen_og),
            patch.object(og, "generate_thumbnail", mock_gen_thumb),
            patch.object(og, "_MPL_AVAILABLE", True),
            patch("argparse.ArgumentParser.parse_args", return_value=args),
        ):
            og.main()

        # --thumbnails-only 루프에는 skip 조건이 없으므로 항상 호출
        mock_gen_thumb.assert_called_once_with(str(og_path))
        mock_gen_og.assert_not_called()

    def test_og_missing_calls_generate_thumbnail_but_returns_false(self, tmp_path, monkeypatch):
        """og 없음: generate_thumbnail은 호출되지만 False를 반환한다 (og 없으면 내부 실패)."""
        monkeypatch.setattr(og, "IMAGES_DIR", str(tmp_path))
        # og 파일 미생성 (의도적)

        args = _make_args(thumbnails_only=True)
        mock_gen_og = MagicMock(return_value=True)
        # generate_thumbnail이 og 없음을 감지해 False 반환하도록 설정
        mock_gen_thumb = MagicMock(return_value=False)

        expected_og_path = str(tmp_path / f"og-{_FAKE_SLUG}-{_FAKE_DATE}.png")

        with (
            patch.object(og, "collect_posts", return_value=[FAKE_POST]),
            patch.object(og, "generate_og_image", mock_gen_og),
            patch.object(og, "generate_thumbnail", mock_gen_thumb),
            patch.object(og, "_MPL_AVAILABLE", True),
            patch("argparse.ArgumentParser.parse_args", return_value=args),
        ):
            og.main()

        # --thumbnails-only 루프는 og 존재 여부를 별도 확인하지 않고 generate_thumbnail에 위임
        mock_gen_thumb.assert_called_once_with(expected_og_path)
        mock_gen_og.assert_not_called()

    def test_thumbnails_only_with_force_does_not_call_generate_og_image(
        self, tmp_path, monkeypatch
    ):
        """--thumbnails-only + --force 조합: generate_og_image는 여전히 미호출."""
        monkeypatch.setattr(og, "IMAGES_DIR", str(tmp_path))

        og_path = tmp_path / f"og-{_FAKE_SLUG}-{_FAKE_DATE}.png"
        thumb_path = tmp_path / f"thumb-og-{_FAKE_SLUG}-{_FAKE_DATE}.png"
        og_path.write_bytes(b"PNG")
        thumb_path.write_bytes(b"PNG")

        # --force를 함께 넘겨도 thumbnails_only 분기는 main loop 전에 return
        args = _make_args(thumbnails_only=True, force=True)
        mock_gen_og = MagicMock(return_value=True)
        mock_gen_thumb = MagicMock(return_value=True)

        with (
            patch.object(og, "collect_posts", return_value=[FAKE_POST]),
            patch.object(og, "generate_og_image", mock_gen_og),
            patch.object(og, "generate_thumbnail", mock_gen_thumb),
            patch.object(og, "_MPL_AVAILABLE", True),
            patch("argparse.ArgumentParser.parse_args", return_value=args),
        ):
            og.main()

        mock_gen_og.assert_not_called()
        mock_gen_thumb.assert_called_once_with(str(og_path))


# ---------------------------------------------------------------------------
# TestUpdateFrontmatterBranch
# ---------------------------------------------------------------------------


class TestUpdateFrontmatterBranch:
    """--update-frontmatter 플래그 분기 검증."""

    def test_new_og_generated_calls_update_post_frontmatter(self, tmp_path, monkeypatch):
        """og 새로 생성 성공 + update_frontmatter=True → update_post_frontmatter 호출."""
        monkeypatch.setattr(og, "IMAGES_DIR", str(tmp_path))
        # og 및 thumb 미존재 → 새 생성 분기로 진입

        args = _make_args(update_frontmatter=True)
        mock_gen_og = MagicMock(return_value=True)
        mock_gen_thumb = MagicMock(return_value=True)
        mock_update_fm = MagicMock(return_value=True)

        expected_url = f"/assets/images/generated/og-{_FAKE_SLUG}-{_FAKE_DATE}.png"

        with (
            patch.object(og, "collect_posts", return_value=[FAKE_POST]),
            patch.object(og, "generate_og_image", mock_gen_og),
            patch.object(og, "generate_thumbnail", mock_gen_thumb),
            patch.object(og, "update_post_frontmatter", mock_update_fm),
            patch.object(og, "_MPL_AVAILABLE", True),
            patch("argparse.ArgumentParser.parse_args", return_value=args),
        ):
            og.main()

        mock_update_fm.assert_called_once_with(FAKE_POST["filepath"], expected_url)

    def test_og_exists_skip_branch_does_not_call_update_post_frontmatter(
        self, tmp_path, monkeypatch
    ):
        """og + thumb 모두 존재 (skip 분기): update_post_frontmatter 미호출."""
        monkeypatch.setattr(og, "IMAGES_DIR", str(tmp_path))

        og_path = tmp_path / f"og-{_FAKE_SLUG}-{_FAKE_DATE}.png"
        thumb_path = tmp_path / f"thumb-og-{_FAKE_SLUG}-{_FAKE_DATE}.png"
        og_path.write_bytes(b"PNG")
        thumb_path.write_bytes(b"PNG")

        args = _make_args(update_frontmatter=True)
        mock_gen_og = MagicMock(return_value=True)
        mock_gen_thumb = MagicMock(return_value=True)
        mock_update_fm = MagicMock(return_value=True)

        with (
            patch.object(og, "collect_posts", return_value=[FAKE_POST]),
            patch.object(og, "generate_og_image", mock_gen_og),
            patch.object(og, "generate_thumbnail", mock_gen_thumb),
            patch.object(og, "update_post_frontmatter", mock_update_fm),
            patch.object(og, "_MPL_AVAILABLE", True),
            patch("argparse.ArgumentParser.parse_args", return_value=args),
        ):
            og.main()

        mock_update_fm.assert_not_called()

    def test_backfill_branch_does_not_call_update_post_frontmatter(self, tmp_path, monkeypatch):
        """og 있고 thumb 없는 backfill 분기: update_post_frontmatter 미호출."""
        monkeypatch.setattr(og, "IMAGES_DIR", str(tmp_path))

        og_path = tmp_path / f"og-{_FAKE_SLUG}-{_FAKE_DATE}.png"
        og_path.write_bytes(b"PNG")
        # thumb 미생성 → backfill 분기 진입

        args = _make_args(update_frontmatter=True)
        mock_gen_og = MagicMock(return_value=True)
        mock_gen_thumb = MagicMock(return_value=True)
        mock_update_fm = MagicMock(return_value=True)

        with (
            patch.object(og, "collect_posts", return_value=[FAKE_POST]),
            patch.object(og, "generate_og_image", mock_gen_og),
            patch.object(og, "generate_thumbnail", mock_gen_thumb),
            patch.object(og, "update_post_frontmatter", mock_update_fm),
            patch.object(og, "_MPL_AVAILABLE", True),
            patch("argparse.ArgumentParser.parse_args", return_value=args),
        ):
            og.main()

        # backfill 분기 (line 2294-2298)는 update_post_frontmatter를 호출하지 않는다
        mock_update_fm.assert_not_called()

    def test_update_frontmatter_returns_false_does_not_increment_updated(
        self, tmp_path, monkeypatch
    ):
        """update_post_frontmatter가 False 반환 시 updated 카운트 증가하지 않음."""
        monkeypatch.setattr(og, "IMAGES_DIR", str(tmp_path))
        # og 및 thumb 미존재 → 새 생성 분기

        args = _make_args(update_frontmatter=True)
        mock_gen_og = MagicMock(return_value=True)
        mock_gen_thumb = MagicMock(return_value=True)
        # False 반환 → updated 카운트 증가 안 됨
        mock_update_fm = MagicMock(return_value=False)

        log_messages: list[str] = []

        def _capture_info(msg, *args_inner, **kwargs):
            log_messages.append(msg % args_inner if args_inner else msg)

        with (
            patch.object(og, "collect_posts", return_value=[FAKE_POST]),
            patch.object(og, "generate_og_image", mock_gen_og),
            patch.object(og, "generate_thumbnail", mock_gen_thumb),
            patch.object(og, "update_post_frontmatter", mock_update_fm),
            patch.object(og, "_MPL_AVAILABLE", True),
            patch.object(og.logger, "info", side_effect=_capture_info),
            patch("argparse.ArgumentParser.parse_args", return_value=args),
        ):
            og.main()

        # update_post_frontmatter는 호출되지만 False를 반환했으므로 updated=0
        mock_update_fm.assert_called_once()
        done_msgs = [m for m in log_messages if m.startswith("Done:")]
        assert done_msgs, "Done: 로그 메시지가 없음"
        assert "0 front matter updated" in done_msgs[-1]
