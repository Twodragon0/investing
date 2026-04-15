"""Tests for config module (scripts/common/config.py)."""

import os
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from common.config import get_env, get_env_bool, get_kst_now, get_kst_timezone, get_verify_ssl, setup_logging


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
        tz = get_kst_timezone()
        dt = datetime(2026, 1, 1, 0, 0, 0, tzinfo=tz)
        assert dt.utcoffset() == timedelta(hours=9)


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
            assert result is True or isinstance(result, str)


class TestSetupLogging:
    def test_returns_logger(self):
        logger = setup_logging("test_logger")
        assert logger.name == "test_logger"

    def test_default_name_is_collector(self):
        logger = setup_logging()
        assert logger.name == "collector"

    def test_returns_logger_instance(self):
        import logging

        logger = setup_logging("level_test_logger_2")
        assert isinstance(logger, logging.Logger)


class TestIsInteractiveLocalDev:
    def test_returns_false_when_no_tty(self):
        from common.config import _is_interactive_local_dev

        with patch("sys.stdin") as mock_stdin:
            mock_stdin.isatty.return_value = False
            assert _is_interactive_local_dev() is False

    def test_returns_false_when_isatty_raises_oserror(self):
        from common.config import _is_interactive_local_dev

        with patch("sys.stdin") as mock_stdin:
            mock_stdin.isatty.side_effect = OSError("no tty")
            assert _is_interactive_local_dev() is False

    def test_returns_false_when_isatty_raises_attribute_error(self):
        from common.config import _is_interactive_local_dev

        with patch("sys.stdin") as mock_stdin:
            mock_stdin.isatty.side_effect = AttributeError
            assert _is_interactive_local_dev() is False

    def test_returns_false_when_ci_env_set(self):
        from common.config import _is_interactive_local_dev

        with patch("sys.stdin") as mock_stdin:
            mock_stdin.isatty.return_value = True
            with patch.dict(os.environ, {"CI": "true"}, clear=False):
                assert _is_interactive_local_dev() is False

    def test_returns_false_when_github_actions_set(self):
        from common.config import _is_interactive_local_dev

        with patch("sys.stdin") as mock_stdin:
            mock_stdin.isatty.return_value = True
            env = {"GITHUB_ACTIONS": "true"}
            for v in ("CI", "CONTINUOUS_INTEGRATION", "BUILD_NUMBER"):
                os.environ.pop(v, None)
            with patch.dict(os.environ, env, clear=False):
                assert _is_interactive_local_dev() is False

    def test_returns_false_when_root_uid(self):
        from common.config import _is_interactive_local_dev

        with patch("sys.stdin") as mock_stdin:
            mock_stdin.isatty.return_value = True
            for v in ("CI", "GITHUB_ACTIONS", "CONTINUOUS_INTEGRATION", "BUILD_NUMBER"):
                os.environ.pop(v, None)
            with patch("os.getuid", return_value=0):
                assert _is_interactive_local_dev() is False

    def test_returns_true_when_tty_non_ci_non_root(self):
        from common.config import _is_interactive_local_dev

        with patch("sys.stdin") as mock_stdin:
            mock_stdin.isatty.return_value = True
            for v in ("CI", "GITHUB_ACTIONS", "CONTINUOUS_INTEGRATION", "BUILD_NUMBER"):
                os.environ.pop(v, None)
            with patch("os.getuid", return_value=1000):
                assert _is_interactive_local_dev() is True


class TestGetSslVerifyExtended:
    def test_disable_ssl_with_valid_ack_in_interactive_dev_returns_false(self):
        """When all conditions met (TTY, non-CI, non-root, valid ACK), SSL is disabled."""
        from common.config import get_ssl_verify

        env = {
            "DISABLE_SSL_VERIFY": "true",
            "DISABLE_SSL_VERIFY_ACK": "yes-i-understand-mitm",
        }
        for v in ("CI", "GITHUB_ACTIONS", "CONTINUOUS_INTEGRATION", "BUILD_NUMBER"):
            os.environ.pop(v, None)

        with (
            patch.dict(os.environ, env, clear=False),
            patch("common.config._is_interactive_local_dev", return_value=True),
        ):
            result = get_ssl_verify()
        assert result is False

    def test_certifi_not_installed_returns_true(self):
        """When certifi is not importable, returns True (SSL enabled)."""
        from common.config import get_ssl_verify

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DISABLE_SSL_VERIFY", None)
            with patch.dict("sys.modules", {"certifi": None}):
                result = get_ssl_verify()
        assert result is True

    def test_certifi_bundle_missing_returns_true(self):
        """When certifi is installed but the bundle path does not exist, returns True."""
        from common.config import get_ssl_verify

        mock_certifi = MagicMock()
        mock_certifi.where.return_value = "/nonexistent/path/ca-bundle.crt"

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DISABLE_SSL_VERIFY", None)
            with (
                patch.dict("sys.modules", {"certifi": mock_certifi}),
                patch("os.path.exists", return_value=False),
            ):
                result = get_ssl_verify()
        assert result is True

    def test_non_darwin_returns_certifi_path(self):
        """On non-darwin platforms, returns the certifi bundle path directly."""
        from common.config import get_ssl_verify

        mock_certifi = MagicMock()
        mock_certifi.where.return_value = "/fake/cacert.pem"

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DISABLE_SSL_VERIFY", None)
            with (
                patch.dict("sys.modules", {"certifi": mock_certifi}),
                patch("os.path.exists", return_value=True),
                patch("sys.platform", "linux"),
            ):
                result = get_ssl_verify()
        assert result == "/fake/cacert.pem"

    def test_darwin_with_combined_bundle_returns_combined_path(self):
        """On macOS, when _get_combined_ca_bundle succeeds, returns combined path."""
        from common.config import get_ssl_verify

        mock_certifi = MagicMock()
        mock_certifi.where.return_value = "/fake/cacert.pem"

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DISABLE_SSL_VERIFY", None)
            with (
                patch.dict("sys.modules", {"certifi": mock_certifi}),
                patch("os.path.exists", return_value=True),
                patch("sys.platform", "darwin"),
                patch("common.config._get_combined_ca_bundle", return_value="/fake/combined.pem"),
            ):
                result = get_ssl_verify()
        assert result == "/fake/combined.pem"

    def test_darwin_without_combined_bundle_returns_certifi_path(self):
        """On macOS, when _get_combined_ca_bundle returns None, falls back to certifi."""
        from common.config import get_ssl_verify

        mock_certifi = MagicMock()
        mock_certifi.where.return_value = "/fake/cacert.pem"

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DISABLE_SSL_VERIFY", None)
            with (
                patch.dict("sys.modules", {"certifi": mock_certifi}),
                patch("os.path.exists", return_value=True),
                patch("sys.platform", "darwin"),
                patch("common.config._get_combined_ca_bundle", return_value=None),
            ):
                result = get_ssl_verify()
        assert result == "/fake/cacert.pem"


class TestGetCombinedCaBundle:
    def test_returns_cached_path_when_fresh(self, tmp_path):
        """Returns existing combined bundle if it was modified within the last day."""
        import time

        from common.config import _get_combined_ca_bundle

        combined = tmp_path / "combined_ca.pem"
        combined.write_text("cert data")

        with (
            patch("common.config.Path.home", return_value=tmp_path),
            patch("os.path.getmtime", return_value=time.time()),
            patch("os.path.exists", return_value=True),
        ):
            result = _get_combined_ca_bundle("/fake/certifi.pem")

        assert result is not None
        assert "combined_ca.pem" in result

    def test_returns_none_when_no_zscaler_cert(self, tmp_path):
        """Returns None when Zscaler cert is not found in keychain."""
        from common.config import _get_combined_ca_bundle

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""

        with (
            patch("common.config.Path.home", return_value=tmp_path),
            patch("os.path.exists", return_value=False),
            patch("subprocess.run", return_value=mock_result),
        ):
            result = _get_combined_ca_bundle("/fake/certifi.pem")

        assert result is None

    def test_returns_none_on_subprocess_exception(self, tmp_path):
        """Returns None when subprocess raises an exception."""
        from common.config import _get_combined_ca_bundle

        with (
            patch("common.config.Path.home", return_value=tmp_path),
            patch("os.path.exists", return_value=False),
            patch("subprocess.run", side_effect=OSError("no security tool")),
        ):
            result = _get_combined_ca_bundle("/fake/certifi.pem")

        assert result is None

    def test_writes_combined_bundle_when_zscaler_found(self, tmp_path):
        """Writes combined bundle and returns path when Zscaler cert found."""
        from common.config import _get_combined_ca_bundle

        certifi_file = tmp_path / "cacert.pem"
        certifi_file.write_text("# certifi root CAs\n")

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "-----BEGIN CERTIFICATE-----\nfakedata\n-----END CERTIFICATE-----\n"

        with (
            patch("common.config.Path.home", return_value=tmp_path),
            patch("os.path.exists", return_value=False),
            patch("subprocess.run", return_value=mock_result),
        ):
            result = _get_combined_ca_bundle(str(certifi_file))

        assert result is not None
        assert os.path.exists(result)
        with open(result, encoding="utf-8") as f:
            content = f.read()
        assert "certifi root CAs" in content
        assert "Zscaler" in content


class TestGetKstTimezoneZoneInfoFallback:
    def test_falls_back_to_fixed_offset_when_zoneinfo_raises(self):
        """When ZoneInfo("Asia/Seoul") raises, falls back to UTC+9 fixed offset."""
        import common.config as cfg

        original_zoneinfo = cfg.ZoneInfo
        try:
            cfg.ZoneInfo = MagicMock(side_effect=Exception("tzdata missing"))
            tz = cfg.get_kst_timezone()
            dt = datetime(2026, 1, 1, tzinfo=tz)
            assert dt.utcoffset() == timedelta(hours=9)
        finally:
            cfg.ZoneInfo = original_zoneinfo

    def test_falls_back_to_fixed_offset_when_zoneinfo_is_none(self):
        """When ZoneInfo is None (import failed), returns UTC+9 fixed offset."""
        import common.config as cfg

        original_zoneinfo = cfg.ZoneInfo
        try:
            cfg.ZoneInfo = None
            tz = cfg.get_kst_timezone()
            assert tz == timezone(timedelta(hours=9))
        finally:
            cfg.ZoneInfo = original_zoneinfo


class TestGetKstNow:
    def test_returns_datetime_with_kst_offset(self):
        now = get_kst_now()
        assert isinstance(now, datetime)
        assert now.utcoffset() == timedelta(hours=9)

    def test_is_timezone_aware(self):
        now = get_kst_now()
        assert now.tzinfo is not None


class TestGetVerifySsl:
    def test_returns_same_value_on_repeated_calls(self):
        """get_verify_ssl caches the result — second call returns identical object."""
        import common.config as cfg

        cfg._verify_ssl_cache = None
        first = get_verify_ssl()
        second = get_verify_ssl()
        assert first == second

    def test_caches_result_after_first_call(self):
        """After first call, _verify_ssl_cache is populated."""
        import common.config as cfg

        cfg._verify_ssl_cache = None
        get_verify_ssl()
        assert cfg._verify_ssl_cache is not None

    def test_uses_cached_value_without_calling_get_ssl_verify_again(self):
        """When cache is already set, get_ssl_verify is not called again."""
        import common.config as cfg

        cfg._verify_ssl_cache = "cached-bundle-path"
        with patch("common.config.get_ssl_verify") as mock_ssl:
            result = get_verify_ssl()
        mock_ssl.assert_not_called()
        assert result == "cached-bundle-path"
        cfg._verify_ssl_cache = None


class TestModuleConstants:
    def test_request_timeout_is_15(self):
        from common.config import REQUEST_TIMEOUT

        assert REQUEST_TIMEOUT == 15

    def test_browser_timeout_ms_is_30000(self):
        from common.config import BROWSER_TIMEOUT_MS

        assert BROWSER_TIMEOUT_MS == 30_000

    def test_site_url_is_set(self):
        from common.config import SITE_URL

        assert SITE_URL == "https://investing.2twodragon.com"

    def test_user_agent_is_string(self):
        from common.config import USER_AGENT

        assert isinstance(USER_AGENT, str)
        assert len(USER_AGENT) > 0

    def test_browser_user_agent_is_string(self):
        from common.config import BROWSER_USER_AGENT

        assert isinstance(BROWSER_USER_AGENT, str)
        assert "Mozilla" in BROWSER_USER_AGENT
