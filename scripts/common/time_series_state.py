"""time_series_state.py — Time-series state file validator and store.

Provides schema-based validation, append, compact, and load operations
for _state/*.json time-series files (e.g. defi_tvl_history.json).

CLI:
    python -m common.time_series_state --check <path>
    python -m common.time_series_state --fix <path> --dry-run
    python -m common.time_series_state --fix <path> --apply
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal

# ---------------------------------------------------------------------------
# Schema definitions
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Bounds:
    """Numeric range constraint for a field value."""

    min_exclusive: float | None = None
    max_exclusive: float | None = None
    min_inclusive: float | None = None
    max_inclusive: float | None = None

    def check(self, value: float) -> bool:
        """Return True if value is within all defined bounds."""
        if self.min_exclusive is not None and not (value > self.min_exclusive):
            return False
        if self.max_exclusive is not None and not (value < self.max_exclusive):
            return False
        if self.min_inclusive is not None and not (value >= self.min_inclusive):
            return False
        if self.max_inclusive is not None and not (value <= self.max_inclusive):
            return False
        return True

    def describe(self) -> str:
        """Human-readable description of the bounds."""
        parts = []
        if self.min_exclusive is not None:
            parts.append(f"> {self.min_exclusive}")
        if self.min_inclusive is not None:
            parts.append(f">= {self.min_inclusive}")
        if self.max_exclusive is not None:
            parts.append(f"< {self.max_exclusive}")
        if self.max_inclusive is not None:
            parts.append(f"<= {self.max_inclusive}")
        return " and ".join(parts) if parts else "unbounded"


@dataclass(frozen=True)
class TimeSeriesSchema:
    """Schema definition for a time-series JSON file."""

    required_fields: list[str]
    numeric_fields: dict[str, Bounds]
    date_field: str = "date"
    date_format: str = "%Y-%m-%d"
    max_entries: int | None = None
    allow_null_fields: list[str] = field(default_factory=list)
    extra_fields_allowed: bool = True


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ValidationIssue:
    """A single validation finding for a record."""

    severity: Literal["error", "warning"]
    code: str  # ZERO_VALUE / UNSORTED / DUPLICATE_DATE / MISSING_FIELD / BOUND_VIOLATION / INVALID_DATE
    index: int
    message: str


@dataclass
class AppendResult:
    """Result of a TimeSeriesStore.append() call."""

    ok: bool
    reason: str | None = None


@dataclass
class CompactionReport:
    """Summary of a TimeSeriesStore.compact() run."""

    removed_invalid: int
    removed_duplicates: int
    resorted: bool
    final_count: int


# ---------------------------------------------------------------------------
# Core store
# ---------------------------------------------------------------------------


class TimeSeriesStore:
    """Read/write/validate a time-series JSON state file."""

    def __init__(self, path: Path, schema: TimeSeriesSchema, logger=None) -> None:
        if schema.date_field not in schema.required_fields:
            raise ValueError(
                f"date_field '{schema.date_field}' must be in required_fields"
            )
        self._path = Path(path)
        self._schema = schema
        self._logger = logger

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load(self, *, validate: bool = True) -> list[dict]:
        """Load records from file.

        Returns [] when file does not exist. If validate=True, error-level
        issues are logged and affected records are filtered from the returned view.
        The file itself is never modified by load().
        """
        if not self._path.exists():
            return []

        try:
            with self._path.open(encoding="utf-8") as fh:
                records = json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            self._log_warning("파일 로드 실패: %s", exc)
            return []

        if not isinstance(records, list):
            self._log_warning("파일 형식 오류: 리스트가 아님, 빈 목록 반환")
            return []

        if not validate:
            return records

        issues = self.validate(records)
        error_indices = {iss.index for iss in issues if iss.severity == "error"}
        for iss in issues:
            if iss.severity == "error":
                self._log_warning("validate error [%s] idx=%d: %s", iss.code, iss.index, iss.message)
            else:
                self._log_warning("validate warning [%s] idx=%d: %s", iss.code, iss.index, iss.message)

        if error_indices:
            return [r for i, r in enumerate(records) if i not in error_indices]
        return records

    def append(
        self,
        record: dict,
        *,
        on_invalid: Literal["skip", "raise"] = "skip",
    ) -> AppendResult:
        """Append a single record, enforcing schema and dedup rules.

        Duplicate dates use "last-in wins" semantics. max_entries trims oldest.
        Writes are atomic (os.replace). File is not modified on validation failure.
        """
        issues = self.validate([record])
        errors = [iss for iss in issues if iss.severity == "error"]
        if errors:
            reason = "; ".join(e.message for e in errors)
            if on_invalid == "raise":
                raise ValueError(reason)
            return AppendResult(ok=False, reason=reason)

        existing = self.load(validate=False)

        # Merge: last-in wins for duplicate dates
        date_key = record.get(self._schema.date_field)
        merged: dict[str, dict] = {}
        for r in existing:
            k = r.get(self._schema.date_field)
            merged[k] = r
        merged[date_key] = record  # new record wins

        result = list(merged.values())
        result.sort(key=lambda r: r.get(self._schema.date_field, ""))

        if self._schema.max_entries is not None:
            result = result[-self._schema.max_entries :]

        self._write_atomic(result)
        return AppendResult(ok=True)

    def compact(self) -> CompactionReport:
        """Remove invalid/duplicate records, re-sort, apply max_entries.

        Idempotent: calling twice produces the same result. Writes atomically.
        """
        if not self._path.exists():
            return CompactionReport(
                removed_invalid=0,
                removed_duplicates=0,
                resorted=False,
                final_count=0,
            )

        records = self.load(validate=False)
        original_count = len(records)

        # 1. Remove records with schema errors
        valid_records = []
        for r in records:
            issues = self.validate([r])
            if not any(iss.severity == "error" for iss in issues):
                valid_records.append(r)
        removed_invalid = original_count - len(valid_records)

        # 2. Deduplicate — last-in wins
        seen: dict[str, dict] = {}
        for r in valid_records:
            k = r.get(self._schema.date_field)
            seen[k] = r
        deduped = list(seen.values())
        removed_duplicates = len(valid_records) - len(deduped)

        # 3. Sort by date field
        pre_sort = [r.get(self._schema.date_field, "") for r in deduped]
        deduped.sort(key=lambda r: r.get(self._schema.date_field, ""))
        post_sort = [r.get(self._schema.date_field, "") for r in deduped]
        resorted = pre_sort != post_sort

        # 4. Apply max_entries
        if self._schema.max_entries is not None:
            deduped = deduped[-self._schema.max_entries :]

        self._write_atomic(deduped)
        return CompactionReport(
            removed_invalid=removed_invalid,
            removed_duplicates=removed_duplicates,
            resorted=resorted,
            final_count=len(deduped),
        )

    def validate(self, records: list[dict]) -> list[ValidationIssue]:
        """Validate a list of records against the schema.

        Returns all issues found in traversal order. Does not modify any state.
        """
        issues: list[ValidationIssue] = []
        schema = self._schema
        prev_date: str | None = None

        for i, record in enumerate(records):
            # MISSING_FIELD
            for req in schema.required_fields:
                if req not in record:
                    issues.append(
                        ValidationIssue(
                            severity="error",
                            code="MISSING_FIELD",
                            index=i,
                            message=f"필수 필드 누락: '{req}'",
                        )
                    )

            # INVALID_DATE
            date_val = record.get(schema.date_field)
            if date_val is None:
                valid_date = False
                issues.append(
                    ValidationIssue(
                        severity="error",
                        code="MISSING_FIELD",
                        index=i,
                        message=f"필수 날짜 필드 값이 null: '{schema.date_field}'",
                    )
                )
            else:
                try:
                    datetime.strptime(str(date_val), schema.date_format)  # noqa: DTZ007
                    valid_date = True
                except ValueError:
                    valid_date = False
                    issues.append(
                        ValidationIssue(
                            severity="error",
                            code="INVALID_DATE",
                            index=i,
                            message=f"날짜 형식 오류: '{date_val}' (expected {schema.date_format})",
                        )
                    )

            # UNSORTED, DUPLICATE_DATE (only if dates are valid)
            if valid_date and date_val is not None:
                date_str = str(date_val)
                if prev_date is not None:
                    if date_str < prev_date:
                        issues.append(
                            ValidationIssue(
                                severity="warning",
                                code="UNSORTED",
                                index=i,
                                message=f"날짜 순서 역전: '{date_str}' < '{prev_date}'",
                            )
                        )
                    elif date_str == prev_date:
                        issues.append(
                            ValidationIssue(
                                severity="warning",
                                code="DUPLICATE_DATE",
                                index=i,
                                message=f"날짜 중복: '{date_str}'",
                            )
                        )
                prev_date = date_str

            # Numeric field checks
            for fname, bounds in schema.numeric_fields.items():
                if fname not in record:
                    continue  # MISSING_FIELD already reported above if required

                val = record[fname]

                # Allow null if field is in allow_null_fields
                if val is None:
                    if fname not in schema.allow_null_fields:
                        issues.append(
                            ValidationIssue(
                                severity="error",
                                code="MISSING_FIELD",
                                index=i,
                                message=f"필드 값이 null: '{fname}'",
                            )
                        )
                    continue

                # ZERO_VALUE (special case: value exactly 0 with min_exclusive=0 bound)
                if val == 0 and bounds.min_exclusive is not None and bounds.min_exclusive >= 0:
                    issues.append(
                        ValidationIssue(
                            severity="error",
                            code="ZERO_VALUE",
                            index=i,
                            message=f"필드 '{fname}' 값이 0 (허용 안 됨)",
                        )
                    )
                    continue

                if not isinstance(val, (int, float)):
                    issues.append(
                        ValidationIssue(
                            severity="error",
                            code="MISSING_FIELD",
                            index=i,
                            message=f"필드 '{fname}' 값이 숫자가 아님: {val!r}",
                        )
                    )
                    continue

                if not bounds.check(val):
                    issues.append(
                        ValidationIssue(
                            severity="error",
                            code="BOUND_VIOLATION",
                            index=i,
                            message=f"필드 '{fname}' 범위 위반: {val} (요구: {bounds.describe()})",
                        )
                    )

        return issues

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _write_atomic(self, records: list[dict]) -> None:
        """Write records to file atomically using os.replace."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # NOTE: tmp path is deterministic. Safe only for single-process cron.
        # Phase 2+ may switch to tempfile.NamedTemporaryFile for concurrent safety.
        tmp = self._path.with_suffix(".tmp")
        try:
            with tmp.open("w", encoding="utf-8") as fh:
                json.dump(records, fh, ensure_ascii=False, indent=2)
                fh.write("\n")
            os.replace(str(tmp), str(self._path))
        except OSError as exc:
            self._log_warning("원자적 쓰기 실패: %s", exc)
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            raise

    def _log_warning(self, msg: str, *args: object) -> None:
        if self._logger is not None:
            self._logger.warning(msg, *args)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Time-series state file validator and compactor",
        prog="python -m common.time_series_state",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", metavar="PATH", help="Validate file and exit 1 on errors")
    group.add_argument("--fix", metavar="PATH", help="Compact file (dry-run by default)")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="With --fix: actually write changes (default: dry-run)",
    )
    return parser


def _make_generic_schema(records: list[dict]) -> TimeSeriesSchema:
    """Infer a minimal schema from the first record for CLI use."""
    if not records:
        return TimeSeriesSchema(required_fields=["date"], numeric_fields={})
    sample = records[0]
    numeric_fields = {
        k: Bounds(min_exclusive=0)
        for k, v in sample.items()
        if k != "date" and isinstance(v, (int, float))
    }
    return TimeSeriesSchema(
        required_fields=list(sample.keys()),
        numeric_fields=numeric_fields,
    )


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns exit code."""
    # Import here to avoid circular import issues when used as a module
    from common.config import setup_logging  # noqa: PLC0415

    logger = setup_logging("time_series_state")
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.check:
        path = Path(args.check)
        if not path.exists():
            logger.error("파일을 찾을 수 없음: %s", path)
            return 1
        with path.open(encoding="utf-8") as fh:
            try:
                records = json.load(fh)
            except json.JSONDecodeError as exc:
                logger.error("JSON 파싱 실패: %s", exc)
                return 1
        schema = _make_generic_schema(records)
        store = TimeSeriesStore(path, schema, logger)
        issues = store.validate(records)
        errors = [iss for iss in issues if iss.severity == "error"]
        warnings = [iss for iss in issues if iss.severity == "warning"]
        for iss in issues:
            lvl = "ERROR" if iss.severity == "error" else "WARN "
            logger.info("[%s] idx=%d [%s] %s", lvl, iss.index, iss.code, iss.message)
        logger.info(
            "검증 완료: %d건, error=%d, warning=%d",
            len(records),
            len(errors),
            len(warnings),
        )
        return 1 if errors else 0

    # --fix path
    path = Path(args.fix)
    if not path.exists():
        logger.error("파일을 찾을 수 없음: %s", path)
        return 1

    with path.open(encoding="utf-8") as fh:
        try:
            records = json.load(fh)
        except json.JSONDecodeError as exc:
            logger.error("JSON 파싱 실패: %s", exc)
            return 1

    schema = _make_generic_schema(records)
    store = TimeSeriesStore(path, schema, logger)

    if not args.apply:
        # Dry-run: simulate compact without writing
        original_count = len(records)
        valid_records = []
        for r in records:
            issues = store.validate([r])
            if not any(iss.severity == "error" for iss in issues):
                valid_records.append(r)
        removed_invalid = original_count - len(valid_records)

        seen: dict[str, dict] = {}
        for r in valid_records:
            seen[r.get(schema.date_field)] = r
        deduped = list(seen.values())
        removed_dup = len(valid_records) - len(deduped)

        pre_dedup_order = [r.get(schema.date_field, "") for r in deduped]
        deduped.sort(key=lambda r: r.get(schema.date_field, ""))
        post_dedup_order = [r.get(schema.date_field, "") for r in deduped]
        resorted = pre_dedup_order != post_dedup_order

        if removed_invalid == 0 and removed_dup == 0 and not resorted:
            logger.info("[dry-run] 변경 사항 없음 (no changes)")
        else:
            logger.info(
                "[dry-run] invalid 제거: %d건, 중복 제거: %d건, 재정렬: %s — --apply로 적용 가능",
                removed_invalid,
                removed_dup,
                resorted,
            )
        return 0

    # Apply
    report = store.compact()
    logger.info(
        "compact 완료 — invalid 제거: %d건, 중복 제거: %d건, 재정렬: %s, 최종: %d건",
        report.removed_invalid,
        report.removed_duplicates,
        report.resorted,
        report.final_count,
    )
    return 0


if __name__ == "__main__":
    # Allow running as: python scripts/common/time_series_state.py --check ...
    _scripts_dir = str(Path(__file__).parent.parent)
    if _scripts_dir not in sys.path:
        sys.path.insert(0, _scripts_dir)
    sys.exit(main())
