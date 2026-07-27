"""Unit tests for the real conversion logic in ``common.og_image_formats``.

기존 테스트(``test_generate_thumbnail``/``test_og_compose``)는
``_convert_formats_parallel``/``_convert_to_webp``/``_convert_to_avif`` 를
**mock 으로 대체**만 하고 실제 Pillow 변환 경로는 실행하지 않는다. 이 파일은
그 실 로직을 직접 구동한다:

1. ``_convert_to_webp``  — 정상 변환(True + .webp 생성) / PIL 부재(False) /
   손상 입력 예외(False + warning)
2. ``_convert_to_avif``  — 동일한 3분기
3. ``_convert_formats_parallel`` — 스레드풀로 두 포맷 실제 생성

Pillow(webp/avif)가 없으면 성공 경로만 skip 하고 나머지는 그대로 검증한다.
"""

import os

import pytest

import common.og_image_formats as fmt

# ---------------------------------------------------------------------------
# Capability probes
# ---------------------------------------------------------------------------

try:
    from PIL import features as _pil_features

    _WEBP_OK = fmt._PIL_AVAILABLE and _pil_features.check("webp")
    _AVIF_OK = fmt._PIL_AVAILABLE and _pil_features.check("avif")
except Exception:  # pragma: no cover - PIL 자체가 없는 환경
    _WEBP_OK = False
    _AVIF_OK = False


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_real_png(directory, name: str = "og-sample.png") -> str:
    """실제 디코딩 가능한 최소 PNG 파일을 만들고 절대 경로를 반환한다."""
    from PIL import Image

    path = directory / name
    Image.new("RGB", (8, 8), (10, 20, 30)).save(str(path), "PNG")
    return str(path)


def _make_corrupt_png(directory, name: str = "og-broken.png") -> str:
    """PNG 시그니처만 있고 디코딩 불가능한 손상 파일 경로를 반환한다."""
    path = directory / name
    path.write_bytes(b"\x89PNG\r\n\x1a\n")  # 서명뿐 — IHDR 없음
    return str(path)


# ---------------------------------------------------------------------------
# _convert_to_webp
# ---------------------------------------------------------------------------


class TestConvertToWebp:
    @pytest.mark.skipif(not _WEBP_OK, reason="Pillow WebP 지원 없음")
    def test_success_creates_webp_and_returns_true(self, tmp_path):
        png = _make_real_png(tmp_path)
        assert fmt._convert_to_webp(png) is True
        assert os.path.exists(png[:-4] + ".webp")

    def test_returns_false_when_pil_unavailable(self, tmp_path, monkeypatch):
        png = _make_corrupt_png(tmp_path)
        monkeypatch.setattr(fmt, "PILImage", None)
        assert fmt._convert_to_webp(png) is False
        assert not os.path.exists(png[:-4] + ".webp")

    @pytest.mark.skipif(not fmt._PIL_AVAILABLE, reason="Pillow 미설치")
    def test_returns_false_on_corrupt_input(self, tmp_path, caplog):
        png = _make_corrupt_png(tmp_path)
        with caplog.at_level("WARNING", logger="og-image-gen"):
            assert fmt._convert_to_webp(png) is False
        assert any("WebP conversion failed" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# _convert_to_avif
# ---------------------------------------------------------------------------


class TestConvertToAvif:
    @pytest.mark.skipif(not _AVIF_OK, reason="Pillow AVIF 지원 없음")
    def test_success_creates_avif_and_returns_true(self, tmp_path):
        png = _make_real_png(tmp_path)
        assert fmt._convert_to_avif(png) is True
        assert os.path.exists(png[:-4] + ".avif")

    def test_returns_false_when_pil_unavailable(self, tmp_path, monkeypatch):
        png = _make_corrupt_png(tmp_path)
        monkeypatch.setattr(fmt, "PILImage", None)
        assert fmt._convert_to_avif(png) is False
        assert not os.path.exists(png[:-4] + ".avif")

    @pytest.mark.skipif(not fmt._PIL_AVAILABLE, reason="Pillow 미설치")
    def test_returns_false_on_corrupt_input(self, tmp_path, caplog):
        png = _make_corrupt_png(tmp_path)
        with caplog.at_level("WARNING", logger="og-image-gen"):
            assert fmt._convert_to_avif(png) is False
        assert any("AVIF conversion failed" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# _convert_formats_parallel
# ---------------------------------------------------------------------------


class TestConvertFormatsParallel:
    @pytest.mark.skipif(not (_WEBP_OK and _AVIF_OK), reason="Pillow WebP+AVIF 지원 없음")
    def test_creates_both_formats(self, tmp_path):
        png = _make_real_png(tmp_path)
        assert fmt._convert_formats_parallel(png) is None
        assert os.path.exists(png[:-4] + ".webp")
        assert os.path.exists(png[:-4] + ".avif")

    def test_no_output_when_pil_unavailable(self, tmp_path, monkeypatch):
        png = _make_corrupt_png(tmp_path)
        monkeypatch.setattr(fmt, "PILImage", None)
        assert fmt._convert_formats_parallel(png) is None
        assert not os.path.exists(png[:-4] + ".webp")
        assert not os.path.exists(png[:-4] + ".avif")
