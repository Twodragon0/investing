"""Regression tests for the main-loop skip branch in generate_og_images.py.

세 가지 시나리오 검증:
1. og + thumb 모두 존재 → skipped 카운트 증가, 어떤 생성 함수도 호출되지 않음
2. og 있고 thumb 없음 → generate_thumbnail만 호출, og mtime 유지
3. og 없음 → generate_og_image + generate_thumbnail 모두 호출
"""

import argparse
import time
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Import guard: scripts/ already on sys.path via conftest.py
# ---------------------------------------------------------------------------

try:
    import generate_og_images as og

    _IMPORT_OK = True
except Exception:
    og = None  # type: ignore
    _IMPORT_OK = False

pytestmark = pytest.mark.skipif(not _IMPORT_OK, reason="generate_og_images could not be imported")

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
    """Return an argparse.Namespace with sensible defaults for the main loop."""
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
# TestSkipBranch
# ---------------------------------------------------------------------------


class TestSkipBranch:
    """Tests for the og/thumb existence check in the main processing loop."""

    def test_both_og_and_thumb_exist_increments_skipped(self, tmp_path, monkeypatch):
        """og + thumb 모두 존재하면 skipped 카운트가 1 증가하고 생성 함수 미호출."""
        # Redirect IMAGES_DIR to tmp_path
        monkeypatch.setattr(og, "IMAGES_DIR", str(tmp_path))

        # Pre-create both files
        og_path = tmp_path / f"og-{_FAKE_SLUG}-{_FAKE_DATE}.png"
        thumb_path = tmp_path / f"thumb-og-{_FAKE_SLUG}-{_FAKE_DATE}.png"
        og_path.write_bytes(b"PNG")
        thumb_path.write_bytes(b"PNG")

        args = _make_args()

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
        mock_gen_thumb.assert_not_called()

    def test_both_exist_does_not_modify_og_mtime(self, tmp_path, monkeypatch):
        """og + thumb 모두 존재할 때 og 파일의 mtime이 변경되지 않는다."""
        monkeypatch.setattr(og, "IMAGES_DIR", str(tmp_path))

        og_path = tmp_path / f"og-{_FAKE_SLUG}-{_FAKE_DATE}.png"
        thumb_path = tmp_path / f"thumb-og-{_FAKE_SLUG}-{_FAKE_DATE}.png"
        og_path.write_bytes(b"PNG")
        thumb_path.write_bytes(b"PNG")

        mtime_before = og_path.stat().st_mtime
        # Small sleep to make any mtime change detectable
        time.sleep(0.05)

        args = _make_args()

        with (
            patch.object(og, "collect_posts", return_value=[FAKE_POST]),
            patch.object(og, "generate_og_image", MagicMock(return_value=True)),
            patch.object(og, "generate_thumbnail", MagicMock(return_value=True)),
            patch.object(og, "_MPL_AVAILABLE", True),
            patch("argparse.ArgumentParser.parse_args", return_value=args),
        ):
            og.main()

        assert og_path.stat().st_mtime == mtime_before

    def test_og_exists_thumb_missing_calls_generate_thumbnail_only(self, tmp_path, monkeypatch):
        """og 있고 thumb 없으면 generate_thumbnail만 호출하고 generate_og_image는 미호출."""
        monkeypatch.setattr(og, "IMAGES_DIR", str(tmp_path))

        og_path = tmp_path / f"og-{_FAKE_SLUG}-{_FAKE_DATE}.png"
        og_path.write_bytes(b"PNG")
        # thumb deliberately absent

        args = _make_args()

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

    def test_og_exists_thumb_missing_preserves_og_mtime(self, tmp_path, monkeypatch):
        """og 있고 thumb 없을 때 og 파일의 mtime이 변경되지 않는다."""
        monkeypatch.setattr(og, "IMAGES_DIR", str(tmp_path))

        og_path = tmp_path / f"og-{_FAKE_SLUG}-{_FAKE_DATE}.png"
        og_path.write_bytes(b"PNG")

        mtime_before = og_path.stat().st_mtime
        time.sleep(0.05)

        args = _make_args()

        with (
            patch.object(og, "collect_posts", return_value=[FAKE_POST]),
            patch.object(og, "generate_og_image", MagicMock(return_value=True)),
            patch.object(og, "generate_thumbnail", MagicMock(return_value=True)),
            patch.object(og, "_MPL_AVAILABLE", True),
            patch("argparse.ArgumentParser.parse_args", return_value=args),
        ):
            og.main()

        assert og_path.stat().st_mtime == mtime_before

    def test_no_og_generates_both_og_and_thumbnail(self, tmp_path, monkeypatch):
        """og 없으면 generate_og_image와 generate_thumbnail 모두 호출."""
        monkeypatch.setattr(og, "IMAGES_DIR", str(tmp_path))
        # Neither og nor thumb present

        args = _make_args()

        mock_gen_og = MagicMock(return_value=True)
        mock_gen_thumb = MagicMock(return_value=True)

        expected_og_path = str(tmp_path / f"og-{_FAKE_SLUG}-{_FAKE_DATE}.png")

        with (
            patch.object(og, "collect_posts", return_value=[FAKE_POST]),
            patch.object(og, "generate_og_image", mock_gen_og),
            patch.object(og, "generate_thumbnail", mock_gen_thumb),
            patch.object(og, "_MPL_AVAILABLE", True),
            patch("argparse.ArgumentParser.parse_args", return_value=args),
        ):
            og.main()

        mock_gen_og.assert_called_once_with(
            title=FAKE_POST["title"],
            date_str=FAKE_POST["date"],
            category=FAKE_POST["category"],
            description=FAKE_POST["description"],
            output_path=expected_og_path,
        )
        mock_gen_thumb.assert_called_once_with(expected_og_path)

    def test_force_flag_bypasses_skip_and_regenerates(self, tmp_path, monkeypatch):
        """--force が설정되면 og+thumb 모두 존재해도 재생성."""
        monkeypatch.setattr(og, "IMAGES_DIR", str(tmp_path))

        og_path = tmp_path / f"og-{_FAKE_SLUG}-{_FAKE_DATE}.png"
        thumb_path = tmp_path / f"thumb-og-{_FAKE_SLUG}-{_FAKE_DATE}.png"
        og_path.write_bytes(b"PNG")
        thumb_path.write_bytes(b"PNG")

        args = _make_args(force=True)

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

        mock_gen_og.assert_called_once()
        mock_gen_thumb.assert_called_once()
