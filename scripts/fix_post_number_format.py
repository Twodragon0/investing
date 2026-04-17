#!/usr/bin/env python3
"""유럽식 숫자 포맷 깨짐을 미국식으로 일괄 보정.

_posts/ 디렉토리에서 최근 N일 내 .md 파일을 스캔하여
유럽식 숫자 포맷(예: "BTC$71.018,21")을 미국식(예: "BTC $71,018.21")으로 치환.

사용법:
    python scripts/fix_post_number_format.py --days 30        # dry-run (기본)
    python scripts/fix_post_number_format.py --days 30 --apply  # 실제 적용
"""

import argparse
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

# translator.py:563-565 와 동일한 정규식
_PATTERNS: list[tuple[re.Pattern, str]] = [
    # "BTC$71.018,21" → "BTC $71,018.21"
    (re.compile(r"([A-Z]{2,5})\$(\d{1,3})\.(\d{3}),(\d{2})\b"), r"\1 $\2,\3.\4"),
    # "$71.018,21" → "$71,018.21"
    (re.compile(r"\$(\d{1,3})\.(\d{3}),(\d{2})\b"), r"$\1,\2.\3"),
]


def _fix_content(content: str) -> tuple[str, int]:
    """콘텐츠에 패턴 치환 적용. (수정된 내용, 치환 횟수) 반환."""
    total_subs = 0
    for pattern, replacement in _PATTERNS:
        content, n = pattern.subn(replacement, content)
        total_subs += n
    return content, total_subs


def _post_mtime(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)


def scan_posts(posts_dir: Path, days: int) -> list[Path]:
    """mtime 기준 최근 N일 내 .md 파일 목록 반환."""
    cutoff = datetime.now(tz=UTC) - timedelta(days=days)
    return sorted(p for p in posts_dir.glob("*.md") if _post_mtime(p) >= cutoff)


def main() -> int:
    parser = argparse.ArgumentParser(description="유럽식 숫자 포맷을 미국식으로 일괄 보정.")
    parser.add_argument("--days", type=int, default=30, help="스캔할 최근 일수 (기본: 30)")
    parser.add_argument("--apply", action="store_true", help="실제 파일 변경 (없으면 dry-run)")
    parser.add_argument(
        "--posts-dir",
        type=Path,
        default=Path("_posts"),
        help="_posts 디렉토리 경로 (기본: _posts)",
    )
    args = parser.parse_args()

    posts_dir = args.posts_dir
    if not posts_dir.exists():
        print(f"오류: _posts 디렉토리를 찾을 수 없습니다: {posts_dir}", file=sys.stderr)
        return 2

    mode = "적용" if args.apply else "DRY-RUN"
    print(f"[숫자 포맷 보정 | {mode}] 최근 {args.days}일 포스트 스캔 중...")

    posts = scan_posts(posts_dir, args.days)
    print(f"  스캔 대상: {len(posts)}개 파일")

    changed_files: list[tuple[Path, int]] = []
    total_replacements = 0

    for post in posts:
        content = post.read_text(encoding="utf-8", errors="ignore")
        new_content, subs = _fix_content(content)
        if subs == 0:
            continue
        changed_files.append((post, subs))
        total_replacements += subs
        if args.apply:
            post.write_text(new_content, encoding="utf-8")
            print(f"  [수정됨] {post.name} ({subs}건 치환)")
        else:
            print(f"  [예정]   {post.name} ({subs}건 치환 예정)")

    print()
    if args.apply:
        print(f"완료: {len(changed_files)}개 파일 수정, 총 {total_replacements}건 치환.")
    else:
        print(f"DRY-RUN 결과: {len(changed_files)}개 파일 영향, 총 {total_replacements}건 치환 예정.")
        if changed_files:
            print("실제 적용하려면:")
            print(f"  python scripts/fix_post_number_format.py --days {args.days} --apply")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
