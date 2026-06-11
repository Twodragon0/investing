#!/usr/bin/env python3
"""R2로 생성 이미지 마이그레이션 스크립트.

_posts/*.md 중 front matter image: 가 /assets/images/generated/ 를 가리키고
해당 PNG 파일이 로컬에 실재하는 포스트를 대상으로:
  1. R2에 png/webp/avif 변형을 업로드한다.
  2. front matter image: 를 CDN 절대 URL로 치환한다.

이미 삭제된(로컬 파일 없는) 이미지는 원본 소실이므로 skip.

Usage:
    python scripts/migrate_images_to_r2.py              # dry-run (기본)
    python scripts/migrate_images_to_r2.py --apply      # 실제 적용
    python scripts/migrate_images_to_r2.py --days 30    # 최근 30일 제한
    python scripts/migrate_images_to_r2.py --limit 10   # 최대 10건만 처리
"""

import argparse
import os
import re
import sys
import tempfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from common import asset_storage  # noqa: E402
from common.config import setup_logging  # noqa: E402

logger = setup_logging("migrate_images_to_r2")

REPO_ROOT = Path(__file__).resolve().parent.parent
POSTS_DIR = REPO_ROOT / "_posts"
GENERATED_PREFIX = "/assets/images/generated/"

# front matter image: 필드 파싱 (따옴표 있음/없음 모두)
_IMAGE_RE = re.compile(r'^(image:\s*)"?(/assets/images/generated/([^"\s]+))"?\s*$', re.MULTILINE)
_DATE_RE = re.compile(r"^date:\s*(\d{4}-\d{2}-\d{2})", re.MULTILINE)


def _parse_image_field(content: str) -> tuple[str, str] | None:
    """front matter image: 필드에서 (로컬경로, 파일명) 추출. 없으면 None."""
    m = _IMAGE_RE.search(content)
    if not m:
        return None
    local_url = m.group(2)  # e.g. /assets/images/generated/foo.png
    filename = m.group(3)   # e.g. foo.png
    return local_url, filename


def _post_date_from_content(content: str) -> date | None:
    m = _DATE_RE.search(content)
    if m:
        try:
            return date.fromisoformat(m.group(1))
        except ValueError:
            pass
    return None


def _replace_image_url(content: str, new_url: str) -> str:
    """front matter의 image: 라인만 CDN URL로 치환. 나머지 필드·본문 보존."""
    def _replacer(m: re.Match) -> str:
        prefix = m.group(1)  # 'image: '
        return f'{prefix}"{new_url}"'

    return _IMAGE_RE.sub(_replacer, content, count=1)


def _atomic_write(file_path: Path, content: str, make_backup: bool = True) -> None:
    """임시파일→os.replace 원자적 쓰기. make_backup=True면 .bak 파일 생성."""
    if make_backup:
        bak_path = file_path.with_suffix(file_path.suffix + ".bak")
        bak_path.write_text(file_path.read_text(encoding="utf-8"), encoding="utf-8")

    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=file_path.parent,
        prefix=".migrate_tmp_",
        suffix=".md",
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.replace(tmp_path, file_path)
    except Exception:
        # 임시 파일 정리
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def collect_candidates(
    posts_dir: Path,
    repo_root: Path,
    days: int | None = None,
    limit: int | None = None,
) -> list[dict]:
    """마이그레이션 대상 포스트 목록 반환.

    각 항목:
      file       : Path
      content    : str
      local_url  : str (/assets/images/generated/foo.png)
      filename   : str (foo.png)
      local_png  : Path (REPO_ROOT 기준 실제 경로)
      cdn_url    : str (public_url 반환값)
    """
    cutoff: date | None = None
    if days is not None:
        cutoff = datetime.now(tz=UTC).date() - timedelta(days=days - 1)

    candidates = []
    for post_file in sorted(posts_dir.glob("*.md")):
        content = post_file.read_text(encoding="utf-8", errors="ignore")
        result = _parse_image_field(content)
        if result is None:
            continue
        local_url, filename = result

        # .png 파일 로컬 존재 여부 확인
        local_png = repo_root / "assets" / "images" / "generated" / filename
        if not local_png.is_file():
            logger.debug("로컬 파일 없음 (skip): %s → %s", post_file.name, filename)
            continue

        # 날짜 필터
        if cutoff is not None:
            post_date = _post_date_from_content(content)
            if post_date is None or post_date < cutoff:
                continue

        cdn_url = asset_storage.public_url(filename)
        candidates.append(
            {
                "file": post_file,
                "content": content,
                "local_url": local_url,
                "filename": filename,
                "local_png": local_png,
                "cdn_url": cdn_url,
            }
        )

        if limit is not None and len(candidates) >= limit:
            break

    return candidates


def run_dry_run(candidates: list[dict]) -> None:
    """dry-run: 대상 포스트 경로·현재 image·CDN URL·건수를 logging 출력."""
    logger.info("=== dry-run 모드: 실제 업로드·파일 수정 없음 ===")
    logger.info("마이그레이션 대상: %d건", len(candidates))
    for item in candidates:
        logger.info(
            "[대상] %s | 현재: %s → CDN: %s",
            item["file"].name,
            item["local_url"],
            item["cdn_url"],
        )
    logger.info("dry-run 완료. --apply 플래그로 실제 적용하세요.")


def run_apply(candidates: list[dict]) -> int:
    """실제 업로드 및 front matter 치환. 성공 건수 반환."""
    if not asset_storage.is_enabled():
        logger.error(
            "R2가 활성화되지 않았습니다. "
            "R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, "
            "R2_BUCKET, R2_PUBLIC_BASE_URL 환경변수를 설정하세요. "
            "쓰기 없이 종료합니다."
        )
        return -1

    logger.info("=== apply 모드: 총 %d건 업로드 및 front matter 치환 ===", len(candidates))
    success = 0
    for item in candidates:
        png_path = str(item["local_png"])
        uploaded = asset_storage.mirror_generated_variants(png_path)
        if uploaded == 0:
            # 단일 파일 업로드 시도 (변형 없이 png만 있을 경우 대비)
            ok = asset_storage.upload_file(png_path)
            if not ok:
                logger.warning(
                    "업로드 실패 (skip): %s | %s",
                    item["file"].name,
                    item["filename"],
                )
                continue

        # front matter 치환
        new_content = _replace_image_url(item["content"], item["cdn_url"])
        if new_content == item["content"]:
            logger.warning("image: 치환 변화 없음 (skip): %s", item["file"].name)
            continue

        _atomic_write(item["file"], new_content, make_backup=True)
        logger.info(
            "완료: %s | %s → %s",
            item["file"].name,
            item["local_url"],
            item["cdn_url"],
        )
        success += 1

    logger.info("적용 완료: %d / %d건 성공", success, len(candidates))
    return success


def main() -> int:
    parser = argparse.ArgumentParser(
        description="_posts의 로컬 생성 이미지를 R2에 업로드하고 front matter CDN URL로 치환합니다.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="실제 업로드 및 파일 수정 (기본: dry-run)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="쓰기 없이 대상만 출력 (기본 동작, 명시용). --apply와 함께 쓰면 거부",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=None,
        metavar="N",
        help="최근 N일 포스트만 대상 (기본: 전체)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="최대 N건만 처리 (기본: 제한 없음)",
    )
    parser.add_argument(
        "--posts-dir",
        type=Path,
        default=POSTS_DIR,
        help="_posts 디렉토리 경로 (기본: 레포 루트/_posts)",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=REPO_ROOT,
        help="레포 루트 경로 (기본: 스크립트 상위 2단계)",
    )
    args = parser.parse_args()

    if args.apply and args.dry_run:
        logger.error("--apply와 --dry-run은 함께 사용할 수 없습니다.")
        return 2

    posts_dir = args.posts_dir
    repo_root = args.repo_root

    if not posts_dir.exists():
        logger.error("_posts 디렉토리를 찾을 수 없습니다: %s", posts_dir)
        return 2

    candidates = collect_candidates(
        posts_dir=posts_dir,
        repo_root=repo_root,
        days=args.days,
        limit=args.limit,
    )

    if not candidates:
        logger.info("마이그레이션 대상 포스트가 없습니다.")
        return 0

    if not args.apply:
        run_dry_run(candidates)
        return 0

    result = run_apply(candidates)
    if result == -1:
        return 1
    # 후보가 있었는데 한 건도 성공 못 하면 실패로 간주(전체 업로드 실패 등).
    if result == 0 and candidates:
        logger.error("적용 대상 %d건 중 0건 성공. 실패로 종료합니다.", len(candidates))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
