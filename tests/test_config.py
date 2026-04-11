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


class TestGetEnvStripping:
    def test_strips_whitespace(self):
        with patch.dict(os.environ, {"STRIP_KEY": "  hello  "}):
            assert get_env("STRIP_KEY") == "hello"

    def test_strips_quotes(self):
        with patch.dict(os.environ, {"QUOTE_KEY": '"api_key_123"'}):
            assert get_env("QUOTE_KEY") == "api_key_123"

    def test_strips_single_quotes(self):
        with patch.dict(os.environ, {"SQ_KEY": "'value'"}):
            assert get_env("SQ_KEY") == "value"


class TestGetSslVerify:
    def test_disabled_in_ci_returns_true(self):
        from common.config import get_ssl_verify

        with patch.dict(os.environ, {"DISABLE_SSL_VERIFY": "true", "CI": "true"}):
            result = get_ssl_verify()
            assert result is True

    def test_disabled_non_ci_without_ack_fails_closed(self):
        """DISABLE_SSL_VERIFY without the MITM ack must keep SSL enabled.

        Reflects the hardened behaviour introduced in config.py: the var
        alone is no longer sufficient — the caller must also provide TTY,
        non-CI env, non-root UID, and DISABLE_SSL_VERIFY_ACK=yes-i-understand-mitm.
        Anything short of that returns True (verification ENABLED, fail-closed).
        """
        from common.config import get_ssl_verify

        env = {"DISABLE_SSL_VERIFY": "true"}
        with patch.dict(os.environ, env, clear=False):
            # Ensure CI vars are not set
            os.environ.pop("CI", None)
            os.environ.pop("GITHUB_ACTIONS", None)
            os.environ.pop("DISABLE_SSL_VERIFY_ACK", None)
            result = get_ssl_verify()
            # Fail-closed: missing ack keeps SSL verification ENABLED.
            assert result is True

    def test_enabled_returns_path_or_true(self):
        from common.config import get_ssl_verify

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DISABLE_SSL_VERIFY", None)
            result = get_ssl_verify()
            # Should return a path string or True
            assert result is True or isinstance(result, str)


class TestSetupLogging:
    def test_returns_logger(self):
        logger = setup_logging("test_logger")
        assert logger.name == "test_logger"
