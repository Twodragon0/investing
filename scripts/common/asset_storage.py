"""Mirror generated images to an external object store (Cloudflare R2 / S3-compatible).

Background: ``cleanup-old-images.yml`` prunes ``assets/images/generated/*`` after
30 days to bound repo size, so posts older than 30 days lose their hero/og images
(now handled gracefully by the layout existence guards). Mirroring generated images
to R2 decouples image lifetime from repo size — see
``docs/design-image-offloading-r2.md`` (option D).

Graceful degradation is the core contract: when credentials are not configured (or
``boto3`` is unavailable), **every operation is a no-op and local-file behavior is
unchanged**. This lets the image pipeline start populating R2 the moment infra is
provisioned, with zero code change and zero risk while it is not.

Enable by setting all of (via ``config.get_env``):
    R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET, R2_PUBLIC_BASE_URL
"""

import logging
import os
from functools import lru_cache

from . import config

logger = logging.getLogger(__name__)

# Local URL prefix that generated images are referenced by, and the R2 key prefix.
_LOCAL_PREFIX = "/assets/images/generated/"
_KEY_PREFIX = "generated/"
_FS_PREFIX = os.path.join("assets", "images", "generated")

_CONTENT_TYPES = {
    ".png": "image/png",
    ".webp": "image/webp",
    ".avif": "image/avif",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}
# Unique, date-stamped filenames are effectively immutable → cache hard at the edge.
_CACHE_CONTROL = "public, max-age=31536000, immutable"

_REQUIRED_KEYS = (
    "R2_ACCOUNT_ID",
    "R2_ACCESS_KEY_ID",
    "R2_SECRET_ACCESS_KEY",
    "R2_BUCKET",
    "R2_PUBLIC_BASE_URL",
)


def _settings() -> dict[str, str]:
    return {key: config.get_env(key) for key in _REQUIRED_KEYS}


def is_enabled() -> bool:
    """True only when every required R2 credential/setting is present."""
    settings = _settings()
    return all(settings[key] for key in _REQUIRED_KEYS)


def public_url(filename: str) -> str:
    """Return the URL a post should reference for ``filename``.

    When R2 is enabled, an absolute CDN URL; otherwise the existing site-relative
    local path (so callers behave identically until R2 is provisioned).
    """
    name = os.path.basename(filename)
    if is_enabled():
        base = config.get_env("R2_PUBLIC_BASE_URL").rstrip("/")
        return f"{base}/{_KEY_PREFIX}{name}"
    return f"{_LOCAL_PREFIX}{name}"


@lru_cache(maxsize=1)
def _client():  # pragma: no cover - exercised via mocked client in tests
    """Lazily build an S3-compatible client for R2. Returns None on any failure."""
    try:
        import boto3
        from botocore.config import Config as BotoConfig
    except ImportError:
        logger.debug("boto3 not installed; remote asset mirroring disabled")
        return None
    account_id = config.get_env("R2_ACCOUNT_ID")
    try:
        return boto3.client(
            "s3",
            endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=config.get_env("R2_ACCESS_KEY_ID"),
            aws_secret_access_key=config.get_env("R2_SECRET_ACCESS_KEY"),
            region_name="auto",
            config=BotoConfig(
                connect_timeout=config.REQUEST_TIMEOUT,
                read_timeout=config.REQUEST_TIMEOUT,
                retries={"max_attempts": 3, "mode": "standard"},
            ),
        )
    except Exception as exc:  # noqa: BLE001 - never let client setup break callers
        logger.warning("R2 client init failed: %s", exc)
        return None


def _is_generated_path(local_path: str) -> bool:
    """Only mirror files under assets/images/generated/ (date-pruned set)."""
    norm = local_path.replace("\\", "/")
    return f"/{_FS_PREFIX.replace(os.sep, '/')}/" in f"/{norm}" or norm.startswith(_FS_PREFIX.replace(os.sep, "/"))


def upload_file(local_path: str) -> bool:
    """Upload one generated image to R2. No-op (False) when disabled; never raises."""
    if not is_enabled():
        return False
    if not local_path or not os.path.isfile(local_path):
        logger.debug("asset_storage: nothing to upload at %s", local_path)
        return False
    if not _is_generated_path(local_path):
        logger.debug("asset_storage: skipping non-generated path %s", local_path)
        return False

    client = _client()
    if client is None:
        return False

    name = os.path.basename(local_path)
    ext = os.path.splitext(name)[1].lower()
    content_type = _CONTENT_TYPES.get(ext, "application/octet-stream")
    bucket = config.get_env("R2_BUCKET")
    key = f"{_KEY_PREFIX}{name}"
    try:
        with open(local_path, "rb") as fh:
            client.put_object(
                Bucket=bucket,
                Key=key,
                Body=fh,
                ContentType=content_type,
                CacheControl=_CACHE_CONTROL,
            )
        logger.info("Mirrored to R2: %s", key)
        return True
    except Exception as exc:  # noqa: BLE001 - mirroring is best-effort, must not break generation
        logger.warning("R2 upload failed for %s: %s", name, exc)
        return False


def mirror_generated_variants(png_path: str) -> int:
    """Mirror a PNG and its sibling .webp/.avif variants to R2.

    Best-effort: returns the number of variants uploaded (0 when disabled). Never
    raises so it can be called from the image-generation hot path safely.
    """
    if not is_enabled() or not png_path:
        return 0
    base, _ = os.path.splitext(png_path)
    uploaded = 0
    for variant in (png_path, base + ".webp", base + ".avif"):
        if os.path.isfile(variant) and upload_file(variant):
            uploaded += 1
    return uploaded


def reset_cache() -> None:
    """Clear the memoized client (used by tests after changing env)."""
    clear = getattr(_client, "cache_clear", None)
    if clear is not None:
        clear()
