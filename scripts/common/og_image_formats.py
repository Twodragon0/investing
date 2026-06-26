"""OG 이미지 포맷 변환 헬퍼 (PNG → WebP/AVIF).

`generate_og_images.py` 에서 추출(2026-06-26). Pillow 기반 포맷 변환을 한 곳에
모아, [[og_compose]] 의 `generate_og_image` 와 메인 모듈의 trading-journal /
thumbnail 경로가 동일한 변환 로직을 공유한다. PIL 가용성(`_PIL_AVAILABLE`)과
`PILImage` 핸들도 여기서 노출한다.
"""

import logging
import re
from concurrent.futures import ThreadPoolExecutor

try:
    from PIL import Image as PILImage

    _PIL_AVAILABLE = True
except ImportError:
    PILImage = None  # type: ignore[assignment]
    _PIL_AVAILABLE = False

logger = logging.getLogger("og-image-gen")


def _convert_to_webp(png_path: str, quality: int = 85) -> bool:
    """Convert a PNG file to WebP format alongside the original."""
    if not _PIL_AVAILABLE:
        return False
    webp_path = re.sub(r"\.png$", ".webp", png_path)
    try:
        with PILImage.open(png_path) as img:
            img.save(webp_path, "WEBP", quality=quality, method=4)
        logger.info("Converted to WebP: %s", webp_path)
        return True
    except (OSError, ValueError) as e:
        logger.warning("WebP conversion failed for %s: %s", png_path, e)
        return False


def _convert_to_avif(png_path: str, quality: int = 50) -> bool:
    """Convert a PNG file to AVIF format alongside the original."""
    if not _PIL_AVAILABLE:
        return False
    avif_path = re.sub(r"\.png$", ".avif", png_path)
    try:
        with PILImage.open(png_path) as img:
            img.save(avif_path, "AVIF", quality=quality)
        logger.info("Converted to AVIF: %s", avif_path)
        return True
    except (OSError, ValueError) as e:
        logger.warning("AVIF conversion failed for %s: %s", png_path, e)
        return False


def _convert_formats_parallel(png_path: str, webp_quality: int = 82) -> None:
    """Convert PNG to WebP and AVIF in parallel using threads."""
    with ThreadPoolExecutor(max_workers=2) as pool:
        pool.submit(_convert_to_webp, png_path, webp_quality)
        pool.submit(_convert_to_avif, png_path)
