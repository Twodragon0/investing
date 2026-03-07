"""Tests for config module (scripts/common/config.py)."""

import os
from unittest.mock import patch

import pytest

from common.config import get_env, get_env_bool, get_kst_timezone, setup_logging


class TestGetEnv:
    def test_returns_env_value(self):
        with patch.dict(os.environ, {"TEST_KEY": "test_value"}):
            assert get_env("TEST_KEY") == "test_value"

    def test_returns_default(self):
        assert get_env("NONEXISTENT_KEY_XYZ", "fallback") == "fallback"

    def test_empty_default(self):
        assert get_env("NONEXISTENT_KEY_XYZ") == ""


class TestGetEnvBool:
    @pytest.mark.parametrize("val", ["true", "1", "yes", "True", "YES"])
    def test_truthy_values(self, val):
        with patch.dict(os.environ, {"BOOL_KEY": val}):
            assert get_env_bool("BOOL_KEY") is True

    @pytest.mark.parametrize("val", ["false", "0", "no", "random"])
    def test_falsy_values(self, val):
        with patch.dict(os.environ, {"BOOL_KEY": val}):
            assert get_env_bool("BOOL_KEY") is False

    def test_missing_uses_default(self):
        assert get_env_bool("MISSING_BOOL_XYZ", default=True) is True
        assert get_env_bool("MISSING_BOOL_XYZ", default=False) is False


class TestGetKstTimezone:
    def test_offset_is_9_hours(self):
        from datetime import datetime, timedelta

        tz = get_kst_timezone()
        dt = datetime(2026, 1, 1, 0, 0, 0, tzinfo=tz)
        utc_offset = dt.utcoffset()
        assert utc_offset == timedelta(hours=9)


class TestSetupLogging:
    def test_returns_logger(self):
        logger = setup_logging("test_logger")
        assert logger.name == "test_logger"
