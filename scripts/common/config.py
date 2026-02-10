"""Environment variable configuration loader."""

import os
import ssl
import logging

logger = logging.getLogger(__name__)


def get_ssl_verify():
    """Get SSL verification setting.

    On macOS, certifi may not have the system certificates registered.
    This function tries certifi first, falls back to True (system default),
    and allows disabling via DISABLE_SSL_VERIFY=true for local dev.
    """
    if os.environ.get("DISABLE_SSL_VERIFY", "").lower() in ("true", "1"):
        logger.warning("SSL verification disabled via DISABLE_SSL_VERIFY")
        return False

    try:
        import certifi
        ca_bundle = certifi.where()
        if os.path.exists(ca_bundle):
            return ca_bundle
    except ImportError:
        pass

    # Fall back to system SSL
    return True


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
