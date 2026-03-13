"""Tests for collector_metrics module (scripts/common/collector_metrics.py)."""

import time
from unittest.mock import MagicMock

from common.collector_metrics import _format_extras, log_collection_summary


class TestFormatExtras:
    """Tests for _format_extras()."""

    def test_none_returns_empty(self):
        assert _format_extras(None) == ""

    def test_empty_dict_returns_empty(self):
        assert _format_extras({}) == ""

    def test_single_field(self):
        result = _format_extras({"key": "value"})
        assert "key=value" in result
        assert result.startswith(" ")

    def test_multiple_fields_sorted(self):
        result = _format_extras({"b": 2, "a": 1})
        assert "a=1" in result
        assert "b=2" in result
        # Sorted alphabetically: a comes before b
        assert result.index("a=1") < result.index("b=2")

    def test_numeric_value(self):
        result = _format_extras({"count": 42})
        assert "count=42" in result

    def test_multiple_fields_space_separated(self):
        result = _format_extras({"x": 1, "y": 2})
        # Both key=value pairs should be present
        assert "x=1" in result
        assert "y=2" in result


class TestLogCollectionSummary:
    """Tests for log_collection_summary()."""

    def test_calls_logger_info(self):
        logger = MagicMock()
        started = time.monotonic()
        log_collection_summary(
            logger=logger,
            collector="test_collector",
            source_count=5,
            unique_items=10,
            post_created=3,
            started_at=started,
        )
        logger.info.assert_called_once()

    def test_log_message_contains_collector_name(self):
        logger = MagicMock()
        started = time.monotonic()
        log_collection_summary(
            logger=logger,
            collector="my_collector",
            source_count=1,
            unique_items=1,
            post_created=1,
            started_at=started,
        )
        args = logger.info.call_args[0]
        assert "my_collector" in args

    def test_negative_counts_clamped_to_zero(self):
        """Negative counts should be clamped to 0 via max(0, ...)."""
        logger = MagicMock()
        started = time.monotonic()
        log_collection_summary(
            logger=logger,
            collector="collector",
            source_count=-5,
            unique_items=-1,
            post_created=-2,
            started_at=started,
        )
        args = logger.info.call_args[0]
        # The format string has %d placeholders; negative values become 0
        # args[0] is the format string, args[1..] are the values
        assert args[2] == 0  # source_count clamped
        assert args[3] == 0  # unique_items clamped
        assert args[4] == 0  # post_created clamped

    def test_duration_is_non_negative(self):
        """Duration should always be >= 0."""
        logger = MagicMock()
        # started_at in the future would give negative raw duration
        future_start = time.monotonic() + 9999
        log_collection_summary(
            logger=logger,
            collector="collector",
            source_count=1,
            unique_items=1,
            post_created=1,
            started_at=future_start,
        )
        args = logger.info.call_args[0]
        # args[5] is the duration
        assert args[5] >= 0.0

    def test_extras_included_in_log(self):
        logger = MagicMock()
        started = time.monotonic()
        log_collection_summary(
            logger=logger,
            collector="collector",
            source_count=1,
            unique_items=1,
            post_created=1,
            started_at=started,
            extras={"api_calls": 10},
        )
        # The extra_fields string should be the last positional arg
        args = logger.info.call_args[0]
        extra_str = args[6]
        assert "api_calls=10" in extra_str

    def test_no_extras_passes_empty_string(self):
        logger = MagicMock()
        started = time.monotonic()
        log_collection_summary(
            logger=logger,
            collector="collector",
            source_count=1,
            unique_items=1,
            post_created=1,
            started_at=started,
        )
        args = logger.info.call_args[0]
        extra_str = args[6]
        assert extra_str == ""
