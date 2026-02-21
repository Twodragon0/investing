"""Environment variable configuration loader."""

import os
import logging
from datetime import timezone, timedelta
from typing import Optional

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None

logger = logging.getLogger(__name__)


def get_ssl_verify():
    """Get SSL verification setting.

    Tries certifi bundle first.  On macOS with corporate proxies (e.g.
    Zscaler), the proxy root CA is not in certifi's bundle, so we detect
    it in the system keychain and build a combined CA bundle.
    Allows disabling via DISABLE_SSL_VERIFY=true for local dev.
    """
    if os.environ.get("DISABLE_SSL_VERIFY", "").lower() in ("true", "1"):
        logger.warning("SSL verification disabled via DISABLE_SSL_VERIFY")
        return False

    try:
        import certifi

        ca_bundle = certifi.where()
        if not os.path.exists(ca_bundle):
            return True
    except ImportError:
        return True

    # On macOS, check for corporate proxy CAs (e.g. Zscaler) in system keychain
    import sys

    if sys.platform == "darwin":
        combined = _get_combined_ca_bundle(ca_bundle)
        if combined:
            return combined

    return ca_bundle


def _get_combined_ca_bundle(certifi_bundle: str) -> Optional[str]:
    """Build a combined CA bundle with corporate proxy certs from macOS keychain.

    Returns path to combined bundle, or None if not needed.
    """
    import subprocess
    import shutil

    combined_path = os.path.join(os.path.dirname(certifi_bundle), "combined_ca.pem")

    # Return cached combined bundle if it exists and is recent (< 1 day)
    import time

    if os.path.exists(combined_path):
        age = time.time() - os.path.getmtime(combined_path)
        if age < 86400:
            return combined_path

    try:
        result = subprocess.run(
            [
                "security",
                "find-certificate",
                "-a",
                "-c",
                "Zscaler",
                "-p",
                "/Library/Keychains/System.keychain",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0 or "BEGIN CERTIFICATE" not in result.stdout:
            return None

        shutil.copy(certifi_bundle, combined_path)
        with open(combined_path, "a") as f:
            f.write("\n# Zscaler proxy CA from macOS system keychain\n")
            f.write(result.stdout)

        logger.info("Created combined CA bundle with Zscaler proxy cert")
        return combined_path
    except Exception as e:
        logger.debug("Failed to build combined CA bundle: %s", e)
        return None


def get_env(key: str, default: str = "") -> str:
    """Get environment variable with optional default."""
    return os.environ.get(key, default)


def get_env_bool(key: str, default: bool = False) -> bool:
    """Get boolean environment variable."""
    val = os.environ.get(key, "")
    if not val:
        return default
    return val.lower() in ("true", "1", "yes")


def setup_logging(name: str = "collector") -> logging.Logger:
    """Setup logging for collector scripts."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    return logging.getLogger(name)


def get_kst_timezone():
    if ZoneInfo:
        try:
            return ZoneInfo("Asia/Seoul")
        except Exception:
            pass
    return timezone(timedelta(hours=9))


# ── Shared constants ──
REQUEST_TIMEOUT = 15
USER_AGENT = "Mozilla/5.0 (compatible; InvestingDragon/1.0)"
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
