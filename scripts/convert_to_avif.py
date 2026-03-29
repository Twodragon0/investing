"""assets/images/generated/ 디렉토리의 PNG 파일을 AVIF로 일괄 변환합니다.

Usage:
    python scripts/convert_to_avif.py [--dry-run] [--quality 50]
"""

from __future__ import annotations

import argparse
import os
import sys

# scripts 디렉토리를 sys.path에 추가 (common 모듈 접근)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common.config import setup_logging  # noqa: E402

logger = setup_logging("convert_to_avif")

IMAGES_DIR = os.path.join(
    os.path.dirname(__file__), "..", "assets", "images", "generated"
)


def convert_png_to_avif(png_path: str, quality: int, dry_run: bool) -> bool:
    """단일 PNG 파일을 AVIF로 변환합니다.

    Returns True on success, False on failure.
    """
    avif_path = os.path.splitext(png_path)[0] + ".avif"

    if os.path.exists(avif_path):
        logger.debug("스킵 (이미 존재): %s", os.path.basename(avif_path))
        return False  # False = 스킵 (변환 안 함)

    if dry_run:
        logger.info("[dry-run] 변환 예정: %s → %s", os.path.basename(png_path), os.path.basename(avif_path))
        return True

    try:
        from PIL import Image

        with Image.open(png_path) as img:
            img.save(avif_path, "AVIF", quality=quality)

        png_size = os.path.getsize(png_path)
        avif_size = os.path.getsize(avif_path)
        savings = (1 - avif_size / png_size) * 100 if png_size > 0 else 0
        logger.info(
            "변환 완료: %s (%.0f%% 절감: %dKB → %dKB)",
            os.path.basename(avif_path),
            savings,
            png_size // 1024,
            avif_size // 1024,
        )
        return True
    except ImportError:
        logger.error("Pillow가 설치되어 있지 않습니다. pip install Pillow>=10.0 을 실행하세요.")
        sys.exit(1)
    except Exception as exc:
        logger.warning("변환 실패: %s — %s", os.path.basename(png_path), exc)
        return False


def main() -> None:
    parser = argparse.ArgumentParser(
        description="PNG → AVIF 일괄 변환 (assets/images/generated/)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="실제 변환 없이 변환 대상 파일 목록만 출력",
    )
    parser.add_argument(
        "--quality",
        type=int,
        default=50,
        help="AVIF 품질 (0-100, 기본값: 50)",
    )
    args = parser.parse_args()

    images_dir = os.path.abspath(IMAGES_DIR)
    if not os.path.isdir(images_dir):
        logger.error("이미지 디렉토리를 찾을 수 없습니다: %s", images_dir)
        sys.exit(1)

    png_files = sorted(
        os.path.join(images_dir, f)
        for f in os.listdir(images_dir)
        if f.lower().endswith(".png")
    )

    if not png_files:
        logger.info("변환할 PNG 파일이 없습니다: %s", images_dir)
        return

    logger.info(
        "PNG 파일 %d개 발견 (디렉토리: %s, dry-run: %s, quality: %d)",
        len(png_files),
        images_dir,
        args.dry_run,
        args.quality,
    )

    converted = 0
    skipped = 0
    failed = 0

    for png_path in png_files:
        avif_path = os.path.splitext(png_path)[0] + ".avif"
        if os.path.exists(avif_path):
            skipped += 1
            logger.debug("스킵: %s", os.path.basename(avif_path))
            continue

        result = convert_png_to_avif(png_path, quality=args.quality, dry_run=args.dry_run)
        if result:
            converted += 1
        else:
            failed += 1

    print()  # noqa: T201
    print("=== 변환 결과 ===")  # noqa: T201
    print(f"  전체 PNG:    {len(png_files)}개")  # noqa: T201
    print(f"  변환 완료:   {converted}개{'(예정)' if args.dry_run else ''}")  # noqa: T201
    print(f"  스킵 (기존): {skipped}개")  # noqa: T201
    print(f"  실패:        {failed}개")  # noqa: T201


if __name__ == "__main__":
    main()
