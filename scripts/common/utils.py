"""Utility functions for news collectors."""

import re
import logging
import time
import email.utils
from urllib.parse import urlparse
from datetime import datetime, timezone
from typing import Optional

import requests

logger = logging.getLogger(__name__)


def sanitize_string(text: str, max_length: int = 1000) -> str:
    """Sanitize string input to prevent injection and limit length."""
    if not isinstance(text, str):
        return ""
    sanitized = re.sub(r"[\x00-\x1f\x7f-\x9f]", "", text)
    sanitized = sanitized.replace("|", "&#124;")
    return sanitized[:max_length].strip()


def validate_url(url: str) -> bool:
    """Validate URL format."""
    try:
        result = urlparse(url)
        return all([result.scheme in ("http", "https"), result.netloc])
    except Exception:
        return False


def slugify(text: str, max_length: int = 80) -> str:
    """Convert text to URL-safe slug."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s가-힣-]", "", text)
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-")[:max_length]


def parse_date(date_str: str) -> Optional[datetime]:
    """Parse various date formats to datetime."""
    if not date_str:
        return None

    formats = [
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S %Z",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(date_str, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue

    # Fallback: email.utils for RFC 2822 dates with text timezones (GMT, EST, etc.)
    try:
        dt = email.utils.parsedate_to_datetime(date_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        pass

    logger.debug("Could not parse date: %s", date_str)
    return None


def detect_language(text: str) -> str:
    """Simple language detection based on character ranges."""
    if not text:
        return "en"
    korean_chars = len(re.findall(r"[가-힣]", text))
    total_chars = len(text.strip())
    if total_chars > 0 and korean_chars / total_chars > 0.1:
        return "ko"
    return "en"


def truncate_text(text: str, max_length: int = 300) -> str:
    """Truncate text at word boundary."""
    if len(text) <= max_length:
        return text
    truncated = text[:max_length]
    last_space = truncated.rfind(" ")
    if last_space > max_length * 0.7:
        truncated = truncated[:last_space]
    return truncated + "..."


def request_with_retry(
    url: str,
    params=None,
    max_retries: int = 2,
    base_delay: float = 2.0,
    timeout: int = 20,
    verify_ssl: bool = True,
    headers=None,
) -> requests.Response:
    """HTTP GET with exponential backoff retry.

    Retries on any RequestException up to max_retries times with
    exponential backoff (base_delay * 2^attempt). Raises the last
    exception if all attempts fail.
    """
    last_exc: Optional[Exception] = None
    for attempt in range(max_retries + 1):
        try:
            resp = requests.get(
                url,
                params=params,
                timeout=timeout,
                verify=verify_ssl,
                headers=headers,
            )
            resp.raise_for_status()
            return resp
        except requests.exceptions.RequestException as e:
            last_exc = e
            if attempt < max_retries:
                delay = base_delay * (2 ** attempt)
                logger.warning("Request to %s failed (attempt %d/%d): %s — retrying in %.1fs",
                               url, attempt + 1, max_retries + 1, e, delay)
                time.sleep(delay)
            else:
                logger.warning("Request to %s failed after %d attempts: %s", url, max_retries + 1, e)
    raise last_exc  # type: ignore[misc]
