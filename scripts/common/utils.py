"""Utility functions for news collectors."""

import email.utils
import logging
import re
import time
from datetime import UTC, datetime
from typing import Optional, Union
from urllib.parse import urlparse

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
            dt = datetime.strptime(date_str, fmt)  # noqa: DTZ007 - tz added below
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt
        except ValueError:
            continue

    # Fallback: email.utils for RFC 2822 dates with text timezones (GMT, EST, etc.)
    try:
        dt = email.utils.parsedate_to_datetime(date_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
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
    total_chars = len(re.sub(r"\s+", "", text))
    if total_chars > 0 and korean_chars >= 2 and korean_chars / total_chars > 0.2:
        return "ko"
    return "en"


def remove_sponsored_text(text: str) -> str:
    """Remove 'Sponsored by @xxx' and similar ad/promo patterns from text."""
    if not text:
        return text
    text = re.sub(r"\s*[Ss]ponsored\s+by\s+@?\S+.*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"\s*[Aa][Dd]:\s+.*$", "", text, flags=re.MULTILINE)
    # Remove decorative bracket markers
    text = re.sub(r"[▒▶▷►◆◇■□●○※☆★]+", "", text)
    return text.strip()


def truncate_text(text: str, max_length: int = 300) -> str:
    """Truncate text at word boundary."""
    if len(text) <= max_length:
        return text
    truncated = text[:max_length]
    last_space = truncated.rfind(" ")
    if last_space > max_length * 0.7:
        truncated = truncated[:last_space]
    return truncated + "..."


def truncate_sentence(text: str, max_length: int = 300) -> str:
    """Truncate text at sentence boundary, falling back to word boundary."""
    if len(text) <= max_length:
        return text
    truncated = text[:max_length]
    # Try Korean sentence endings first, then general
    for sep in [
        "다. ", "요. ", "음. ", "됩니다. ", "입니다. ", "습니다. ",
        "했다. ", "됐다. ", "였다. ", "합니다. ",
        ". ", "。", "! ", "? ", ".\n",
    ]:
        last_sep = truncated.rfind(sep)
        if last_sep > max_length * 0.4:
            return truncated[: last_sep + len(sep)].strip()
    # Fall back to word boundary
    return truncate_text(text, max_length)


def validate_news_item(item: dict) -> Optional[dict]:
    """Validate and clean a news item dict.

    Returns the cleaned item, or None if invalid.
    Required fields: title (min 10 chars), link (valid URL).
    Fixes: description == title → empty string.
    """
    title = item.get("title", "").strip()
    if len(title) < 10:
        logger.debug("Skipping item with short title: %r", title[:30])
        return None

    link = item.get("link", "").strip()
    if link and not validate_url(link):
        logger.debug("Skipping item with invalid URL: %r", link[:60])
        return None

    # Filter noise titles (SEC forms, addresses, system pages)
    _NOISE_TITLE_PATTERNS = [
        r"^(?:Washington,?\s*DC\s*\d+)",
        r"^(?:10-[KQ](?:\s|$))",
        r"^(?:Form\s+\d)",
        r"^(?:SEC\.gov\s*-?\s*SEC\.gov)",
        r"^(?:EDGAR\s)",
        r"^(?:AMENDMENT NO\.)",
    ]
    for pattern in _NOISE_TITLE_PATTERNS:
        if re.match(pattern, title, re.IGNORECASE):
            logger.debug("Skipping noise title: %r", title[:50])
            return None

    # Fix description that's identical to title
    desc = item.get("description", "").strip()
    if desc == title:
        item["description"] = ""

    return item


def request_with_retry(
    url: str,
    params=None,
    max_retries: int = 2,
    base_delay: float = 2.0,
    timeout: int = 20,
    verify_ssl: Union[bool, str] = True,
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
                delay = base_delay * (2**attempt)
                logger.warning(
                    "Request to %s failed (attempt %d/%d): %s — retrying in %.1fs",
                    url,
                    attempt + 1,
                    max_retries + 1,
                    e,
                    delay,
                )
                time.sleep(delay)
            else:
                logger.warning(
                    "Request to %s failed after %d attempts: %s",
                    url,
                    max_retries + 1,
                    e,
                )
    raise last_exc  # type: ignore[misc]
