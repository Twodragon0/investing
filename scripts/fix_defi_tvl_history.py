#!/usr/bin/env python3
"""DeFi TVL 히스토리 정제 스크립트 (TimeSeriesStore CLI 래퍼).

_state/defi_tvl_history.json에서:
  - total_tvl <= 0 항목 제거
  - date 기준 오름차순 정렬
  - 동일 date 중복 시 나중 값 우선 유지

Usage:
    python scripts/fix_defi_tvl_history.py           # dry-run (기본)
    python scripts/fix_defi_tvl_history.py --apply   # 실제 저장
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from common.config import setup_logging
from common.time_series_state import Bounds, TimeSeriesSchema, TimeSeriesStore

HISTORY_PATH = Path(__file__).parent.parent / "_state" / "defi_tvl_history.json"

_SCHEMA = TimeSeriesSchema(
    required_fields=["date", "total_tvl"],
    numeric_fields={"total_tvl": Bounds(min_exclusive=0)},
)


def load_history(path: Path) -> list[dict]:
    """JSON 파일 읽기."""
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def clean_history(records: list[dict]) -> tuple[list[dict], int, int]:
    """오염 항목 제거, 중복 해소, 날짜 정렬.

    Returns:
        (정제된 레코드 리스트, 제거된 zero 항목 수, 제거된 중복 수)
    """
    # 1. total_tvl <= 0 제거
    before_zero = len(records)
    valid = [r for r in records if r.get("total_tvl", 0) > 0]
    removed_zero = before_zero - len(valid)

    # 2. 동일 date 중복 해소 — 같은 날짜면 나중에 등장한 레코드 우선
    seen: dict[str, dict] = {}
    for record in valid:
        seen[record["date"]] = record
    deduped = list(seen.values())
    removed_dup = len(valid) - len(deduped)

    # 3. date 오름차순 정렬
    deduped.sort(key=lambda r: r["date"])

    return deduped, removed_zero, removed_dup


def save_history(path: Path, records: list[dict]) -> None:
    """정제된 데이터 저장 (2-space indent, trailing newline)."""
    with path.open("w", encoding="utf-8") as fh:
        json.dump(records, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="DeFi TVL 히스토리 정제 (zero 제거 + 정렬 + 중복 해소)")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="실제로 파일을 덮어씀 (기본: dry-run)",
    )
    parser.add_argument(
        "--path",
        default=str(HISTORY_PATH),
        help="대상 JSON 파일 경로 (기본: _state/defi_tvl_history.json)",
    )
    args = parser.parse_args()

    logger = setup_logging("fix_defi_tvl_history")
    target = Path(args.path)

    if not target.exists():
        logger.error("파일을 찾을 수 없음: %s", target)
        return 1

    records = load_history(target)
    logger.info("로드 완료: %d건", len(records))

    cleaned, removed_zero, removed_dup = clean_history(records)

    logger.info(
        "정제 결과 — zero 제거: %d건, 중복 제거: %d건, 최종: %d건",
        removed_zero,
        removed_dup,
        len(cleaned),
    )

    if removed_zero == 0 and removed_dup == 0:
        logger.info("오염 항목 없음. 변경 불필요.")
        return 0

    if args.apply:
        store = TimeSeriesStore(target, _SCHEMA, logger)
        store.compact()
        logger.info("저장 완료: %s", target)
    else:
        logger.info("[dry-run] 실제 저장 생략. --apply 플래그로 적용 가능.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
