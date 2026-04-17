"""Unit tests for generate_thumbnail() in generate_og_images.py.

검증 시나리오:
1. _PIL_AVAILABLE = False  → False 반환, logger.warning 발생
2. PNG 파일이 존재하지 않음 → False 반환, logger.warning 발생
3. 정상 입력 (PIL 사용 가능 + PNG 존재) → True 반환, thumb 파일 저장됨
4. _convert_formats_parallel이 thumb_path 인자로 호출됨
5. 출력 경로 규칙: thumb-{basename} 형태인지 검증
"""

import os
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

_FAKE_SLUG = "some-post"
_FAKE_DATE = "2026-04-17"
_OG_BASENAME = f"og-{_FAKE_SLUG}-{_FAKE_DATE}.png"


def _make_fake_png(directory) -> str:
    """tmp_path 아래에 빈 PNG 파일을 만들고 절대 경로를 반환한다."""
    p = directory / _OG_BASENAME
    p.write_bytes(b"\x89PNG\r\n\x1a\n")  # minimal PNG header bytes
    return str(p)


# ---------------------------------------------------------------------------
# TestGenerateThumbnailPilUnavailable
# ---------------------------------------------------------------------------


class TestGenerateThumbnailPilUnavailable:
    """_PIL_AVAILABLE = False 분기 검증."""

    def test_returns_false_when_pil_unavailable(self, monkeypatch):
        """PIL을 사용할 수 없을 때 False를 반환한다."""
        monkeypatch.setattr(og, "_PIL_AVAILABLE", False)
        result = og.generate_thumbnail("/any/path/og-dummy.png")
        assert result is False

    def test_emits_warning_when_pil_unavailable(self, monkeypatch):
        """PIL을 사용할 수 없을 때 logger.warning을 발생시킨다."""
        monkeypatch.setattr(og, "_PIL_AVAILABLE", False)
        with patch.object(og.logger, "warning") as mock_warn:
            og.generate_thumbnail("/any/path/og-dummy.png")
        mock_warn.assert_called_once()
        # 경고 메시지에 경로가 포함됐는지 확인
        warning_text = str(mock_warn.call_args)
        assert "og-dummy.png" in warning_text


# ---------------------------------------------------------------------------
# TestGenerateThumbnailFileMissing
# ---------------------------------------------------------------------------


class TestGenerateThumbnailFileMissing:
    """소스 PNG 파일이 존재하지 않는 경우 검증."""

    def test_returns_false_when_source_png_missing(self, tmp_path, monkeypatch):
        """소스 OG PNG가 없으면 False를 반환한다."""
        monkeypatch.setattr(og, "_PIL_AVAILABLE", True)
        missing_path = str(tmp_path / "does-not-exist.png")
        result = og.generate_thumbnail(missing_path)
        assert result is False

    def test_emits_warning_when_source_png_missing(self, tmp_path, monkeypatch):
        """소스 OG PNG가 없으면 logger.warning을 발생시킨다."""
        monkeypatch.setattr(og, "_PIL_AVAILABLE", True)
        missing_path = str(tmp_path / "does-not-exist.png")
        with patch.object(og.logger, "warning") as mock_warn:
            og.generate_thumbnail(missing_path)
        mock_warn.assert_called_once()
        warning_text = str(mock_warn.call_args)
        assert "does-not-exist.png" in warning_text


# ---------------------------------------------------------------------------
# TestGenerateThumbnailHappyPath
# ---------------------------------------------------------------------------


class TestGenerateThumbnailHappyPath:
    """PIL 사용 가능 + PNG 존재 정상 경로 검증."""

    def _run_with_mocked_pil(self, png_path: str):
        """PIL Image.open과 _convert_formats_parallel을 mock하여 함수를 실행한다."""
        mock_img = MagicMock()
        mock_thumb = MagicMock()
        mock_img.__enter__ = MagicMock(return_value=mock_img)
        mock_img.__exit__ = MagicMock(return_value=False)
        mock_img.resize.return_value = mock_thumb

        mock_convert = MagicMock()

        with (
            patch.object(og, "_PIL_AVAILABLE", True),
            patch.object(og, "PILImage") as mock_pil_cls,
            patch.object(og, "_convert_formats_parallel", mock_convert),
        ):
            mock_pil_cls.open.return_value = mock_img
            mock_pil_cls.Resampling.LANCZOS = 1
            result = og.generate_thumbnail(png_path)

        return result, mock_thumb, mock_convert

    def test_returns_true_on_success(self, tmp_path):
        """정상 입력이면 True를 반환한다."""
        png_path = _make_fake_png(tmp_path)
        result, _, _ = self._run_with_mocked_pil(png_path)
        assert result is True

    def test_thumb_saved_with_correct_name(self, tmp_path):
        """thumb.save가 thumb-{basename} 경로로 호출된다."""
        png_path = _make_fake_png(tmp_path)
        _, mock_thumb, _ = self._run_with_mocked_pil(png_path)

        mock_thumb.save.assert_called_once()
        saved_path = mock_thumb.save.call_args[0][0]
        expected_basename = f"thumb-{_OG_BASENAME}"
        assert os.path.basename(saved_path) == expected_basename

    def test_convert_formats_called_with_thumb_path(self, tmp_path):
        """_convert_formats_parallel이 thumb_path 인자로 호출된다."""
        png_path = _make_fake_png(tmp_path)
        _, mock_thumb, mock_convert = self._run_with_mocked_pil(png_path)

        mock_convert.assert_called_once()
        convert_arg = mock_convert.call_args[0][0]
        assert os.path.basename(convert_arg) == f"thumb-{_OG_BASENAME}"

    def test_thumb_path_in_same_directory_as_source(self, tmp_path):
        """썸네일은 소스 PNG와 같은 디렉터리에 저장된다."""
        png_path = _make_fake_png(tmp_path)
        _, mock_thumb, _ = self._run_with_mocked_pil(png_path)

        saved_path = mock_thumb.save.call_args[0][0]
        assert os.path.dirname(saved_path) == str(tmp_path)


# ---------------------------------------------------------------------------
# TestGenerateThumbnailOutputNamingRule
# ---------------------------------------------------------------------------


class TestGenerateThumbnailOutputNamingRule:
    """출력 파일 경로 명명 규칙 검증."""

    def test_thumb_prefix_added_to_og_basename(self, tmp_path):
        """thumb- 접두사가 og 파일 basename에 붙는다."""
        og_name = f"og-{_FAKE_SLUG}-{_FAKE_DATE}.png"
        png_path = str(tmp_path / og_name)
        (tmp_path / og_name).write_bytes(b"\x89PNG\r\n\x1a\n")

        mock_img = MagicMock()
        mock_thumb = MagicMock()
        mock_img.__enter__ = MagicMock(return_value=mock_img)
        mock_img.__exit__ = MagicMock(return_value=False)
        mock_img.resize.return_value = mock_thumb

        with (
            patch.object(og, "_PIL_AVAILABLE", True),
            patch.object(og, "PILImage") as mock_pil_cls,
            patch.object(og, "_convert_formats_parallel", MagicMock()),
        ):
            mock_pil_cls.open.return_value = mock_img
            mock_pil_cls.Resampling.LANCZOS = 1
            og.generate_thumbnail(png_path)

        saved_path = mock_thumb.save.call_args[0][0]
        expected = f"thumb-og-{_FAKE_SLUG}-{_FAKE_DATE}.png"
        assert os.path.basename(saved_path) == expected

    def test_thumb_name_pattern_matches_expected_format(self, tmp_path):
        """thumb 파일명이 thumb-og-{slug}-{date}.png 패턴에 맞는지 확인한다."""
        import re

        og_name = f"og-{_FAKE_SLUG}-{_FAKE_DATE}.png"
        png_path = str(tmp_path / og_name)
        (tmp_path / og_name).write_bytes(b"\x89PNG\r\n\x1a\n")

        mock_img = MagicMock()
        mock_thumb = MagicMock()
        mock_img.__enter__ = MagicMock(return_value=mock_img)
        mock_img.__exit__ = MagicMock(return_value=False)
        mock_img.resize.return_value = mock_thumb

        with (
            patch.object(og, "_PIL_AVAILABLE", True),
            patch.object(og, "PILImage") as mock_pil_cls,
            patch.object(og, "_convert_formats_parallel", MagicMock()),
        ):
            mock_pil_cls.open.return_value = mock_img
            mock_pil_cls.Resampling.LANCZOS = 1
            og.generate_thumbnail(png_path)

        saved_path = mock_thumb.save.call_args[0][0]
        basename = os.path.basename(saved_path)
        pattern = re.compile(r"^thumb-og-.+-\d{4}-\d{2}-\d{2}\.png$")
        assert pattern.match(basename), f"파일명 패턴 불일치: {basename!r}"


# ---------------------------------------------------------------------------
# TestGenerateThumbnailOSError
# ---------------------------------------------------------------------------


class TestGenerateThumbnailOSError:
    """PIL 작업 중 OSError/ValueError 예외 처리 검증."""

    def test_returns_false_on_oserror(self, tmp_path, monkeypatch):
        """PILImage.open이 OSError를 raise하면 False를 반환한다."""
        png_path = _make_fake_png(tmp_path)
        monkeypatch.setattr(og, "_PIL_AVAILABLE", True)

        with (
            patch.object(og, "PILImage") as mock_pil_cls,
            patch.object(og, "_convert_formats_parallel", MagicMock()),
        ):
            mock_pil_cls.open.side_effect = OSError("corrupt file")
            result = og.generate_thumbnail(png_path)

        assert result is False

    def test_returns_false_on_value_error(self, tmp_path, monkeypatch):
        """PILImage.open이 ValueError를 raise하면 False를 반환한다."""
        png_path = _make_fake_png(tmp_path)
        monkeypatch.setattr(og, "_PIL_AVAILABLE", True)

        with (
            patch.object(og, "PILImage") as mock_pil_cls,
            patch.object(og, "_convert_formats_parallel", MagicMock()),
        ):
            mock_pil_cls.open.side_effect = ValueError("bad image")
            result = og.generate_thumbnail(png_path)

        assert result is False
