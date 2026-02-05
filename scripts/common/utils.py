"""Utility functions for news collectors."""

import re
import logging
from urllib.parse import urlparse
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


def sanitize_string(text: str, max_length: int = 1000) -> str:
    """Sanitize string input to prevent injection and limit length."""
    if not isinstance(text, str):
        return ""
    sanitized = re.sub(r"[\x00-\x1f\x7f-\x9f]", "", text)
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
