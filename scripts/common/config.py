"""Environment variable configuration loader."""

import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None

logger = logging.getLogger(__name__)


_CI_ENV_VARS = ("CI", "GITHUB_ACTIONS", "CONTINUOUS_INTEGRATION", "BUILD_NUMBER")


def _is_interactive_local_dev() -> bool:
    """Return True only in interactive local dev — not CI, not service, has TTY."""
    try:
        if not sys.stdin.isatty():
            return False
    except (AttributeError, OSError):
        return False
    for var in _CI_ENV_VARS:
        if os.environ.get(var):
            return False
    try:
        if os.getuid() == 0:
            return False
    except AttributeError:
        pass  # Windows has no getuid
    return True


def get_ssl_verify():
    """Get SSL verification setting.

    Tries certifi bundle first.  On macOS with corporate proxies (e.g.
    Zscaler), the proxy root CA is not in certifi's bundle, so we detect
    it in the system keychain and build a combined CA bundle.

    DISABLE_SSL_VERIFY=true is only honoured in interactive local dev
    sessions and requires DISABLE_SSL_VERIFY_ACK=yes-i-understand-mitm.
    Any other context (CI, root, no-TTY) keeps SSL verification ENABLED.
    """
    if os.environ.get("DISABLE_SSL_VERIFY", "").lower() in ("true", "1"):
        if not _is_interactive_local_dev():
            logger.error(
                "DISABLE_SSL_VERIFY refused: not in interactive local dev context. SSL verification remains ENABLED."
            )
            return True
        ack = os.environ.get("DISABLE_SSL_VERIFY_ACK", "")
        if ack != "yes-i-understand-mitm":
            logger.error(
                "DISABLE_SSL_VERIFY refused: DISABLE_SSL_VERIFY_ACK must equal "
                "'yes-i-understand-mitm' to acknowledge MITM risk. "
                "SSL verification remains ENABLED."
            )
            return True
        logger.critical(
            "SSL verification DISABLED — LOCAL INTERACTIVE DEV ONLY. All HTTPS traffic is now MITM-vulnerable."
        )
        return False

    try:
        import certifi

        ca_bundle = certifi.where()
        if not os.path.exists(ca_bundle):
            return True
    except ImportError:
        return True

    # On macOS, check for corporate proxy CAs (e.g. Zscaler) in system keychain
    if sys.platform == "darwin":
        combined = _get_combined_ca_bundle(ca_bundle)
        if combined:
            return combined

    return ca_bundle


def _get_combined_ca_bundle(certifi_bundle: str) -> Optional[str]:
    """Build a combined CA bundle with corporate proxy certs from macOS keychain.

    Writes to ~/.cache/investing-dragon/ (mode 0o700) with an atomic os.open()
    call that sets 0o600 at file creation — no world-readable /tmp exposure.
    Returns path to combined bundle, or None if not needed.
    """
    import subprocess
    import time

    cache_dir = Path.home() / ".cache" / "investing-dragon"
    cache_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    combined_path = str(cache_dir / "combined_ca.pem")

    # Return cached combined bundle if it exists and is recent (< 1 day)
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

        with open(certifi_bundle, encoding="utf-8") as src:
            certifi_contents = src.read()
        zscaler_cert = result.stdout

        # Atomic write: file is created with 0o600 from birth — no chmod race
        fd = os.open(
            combined_path,
            os.O_CREAT | os.O_WRONLY | os.O_TRUNC,
            0o600,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(certifi_contents)
                f.write("\n# Zscaler proxy CA from macOS system keychain\n")
                f.write(zscaler_cert)
        except Exception:
            # fd already consumed by fdopen on success; only close on early error
            raise

        logger.info("Created combined CA bundle with Zscaler proxy cert: %s", combined_path)
        return combined_path
    except Exception as e:
        logger.debug("Failed to build combined CA bundle: %s", e)
        return None


def get_env(key: str, default: str = "") -> str:
    """Get environment variable with optional default.

    Strips leading/trailing whitespace and surrounding quotes to prevent
    issues with copy-pasted or shell-exported values.
    """
    val = os.environ.get(key, default)
    if val and val != default:
        val = val.strip().strip("\"'")
    return val


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


def get_kst_now() -> datetime:
    return datetime.now(get_kst_timezone())


# ── Shared constants ──

# Lazy-cached SSL verification setting (avoids repeated keychain lookups)
_verify_ssl_cache = None


def get_verify_ssl():
    """Return cached SSL verification value (lazy singleton)."""
    global _verify_ssl_cache  # noqa: PLW0603
    if _verify_ssl_cache is None:
        _verify_ssl_cache = get_ssl_verify()
    return _verify_ssl_cache


SITE_URL = "https://investing.2twodragon.com"
REQUEST_TIMEOUT = 15
USER_AGENT = "Mozilla/5.0 (compatible; InvestingDragon/1.0)"
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
