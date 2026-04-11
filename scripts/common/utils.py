"""Utility functions for news collectors."""

import email.utils
import ipaddress
import logging
import re
import time
from datetime import UTC, datetime
from typing import Optional, Union
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

_PRIVATE_HOSTNAMES = {
    "localhost",
    "localhost.localdomain",
    "metadata.google.internal",
}
_PRIVATE_HOST_SUFFIXES = (
    ".internal",
    ".local",
    ".localdomain",
    ".localhost",
    ".home",
    ".lan",
)
_DNS_REBIND_HOST_SUFFIXES = (
    ".nip.io",
    ".xip.io",
    ".sslip.io",
    ".localtest.me",
    ".lvh.me",
)


# Common source suffixes to strip from news titles (shared across collectors and summaries)
SOURCE_SUFFIX_RE = re.compile(
    r"\s*[-–—|]\s*(?:"
    # English media
    r"Reuters|Bloomberg|CNBC|CNN|BBC|AP\s*(?:News)?|Forbes|WSJ"
    r"|Yahoo\s*Finance|MarketWatch|The\s*(?:Block|Verge|Guardian)"
    r"|CBS\s*(?:News|뉴스)?|NBC\s*News|ABC\s*News|Fox\s*(?:News|Business)"
    r"|Variety|Barron'?s|Motley\s*Fool|Nasdaq"
    r"|Investing\.com|Seeking\s*Alpha|Benzinga|TheStreet"
    # Korean media
    r"|디지털투데이|연합인포맥스|펜앤마이크|네이트|복지TV\S*"
    r"|이코노믹리뷰|매일경제|한국경제|조선일보|중앙일보"
    r"|경향신문|한겨레|이데일리|뉴시스|아시아경제"
    r"|서울경제|인포스탁데일리|이투데이|국제신문|부산일보"
    r"|뉴스1|노컷뉴스|SBS뉴스|MBC뉴스|KBS뉴스"
    r"|JTBC|채널A|TV조선|연합뉴스|파이낸셜뉴스"
    r"|헤럴드경제|머니투데이|더팩트|데일리안|뉴데일리"
    r"|오마이뉴스|프레시안|시사저널|공감신문|브레이크뉴스"
    r"|한국글로벌뉴스|핀포인트뉴스|글로벌이코노믹|비즈니스포스트|토큰포스트|블록미디어|코인데스크코리아|디센터"
    r"|전자신문|ZDNet\s*Korea|IT조선|디지털데일리|바이라인네트워크"
    r"|BBS불교방송|ER\s*이코노믹리뷰"
    # Additional sources from daily summary
    r"|The New York Times|CryptoRank|Winston & Strawn|European Business Magazine|SEC\.gov|BeInCrypto|Bitget"
    # Domain suffixes
    r"|v\.daum\.net|gukjenews\.com|ilyoseoul\.co\.kr"
    r"|ir\.edaily\.co\.kr|simplywall\.st"
    r"|[a-z][a-z0-9-]*\.(?:com|co\.kr|net|org|io)"
    r")\s*$",
    re.IGNORECASE,
)


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


def _is_non_public_ip(ip: ipaddress._BaseAddress) -> bool:
    return any(
        [
            ip.is_private,
            ip.is_loopback,
            ip.is_link_local,
            ip.is_multicast,
            ip.is_unspecified,
            getattr(ip, "is_reserved", False),
        ]
    )


def is_private_url_target(url: str) -> bool:
    """Best-effort SSRF guard for URL targets.

    Blocks obvious internal targets:
    - localhost and common internal host suffixes
    - DNS-rebinding helper domains that map arbitrary IPs
    - literal private/loopback/link-local IP addresses
    - single-label hostnames such as ``redis`` or ``minio``

    It intentionally does not DNS-resolve arbitrary public-looking hostnames.
    The previous DNS-based approach produced false positives in CI/sandbox
    environments and blocked normal public URLs like ``example.com``.
    """
    try:
        parsed = urlparse(url)
        hostname = (parsed.hostname or "").strip().rstrip(".").lower()
    except Exception:
        return True

    if not hostname:
        return True
    if hostname in _PRIVATE_HOSTNAMES:
        return True
    if any(hostname.endswith(suffix) for suffix in (*_PRIVATE_HOST_SUFFIXES, *_DNS_REBIND_HOST_SUFFIXES)):
        return True

    try:
        return _is_non_public_ip(ipaddress.ip_address(hostname))
    except ValueError:
        pass

    # Single-label names usually indicate internal service discovery targets.
    if "." not in hostname:
        return True

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
        "다. ",
        "요. ",
        "음. ",
        "됩니다. ",
        "입니다. ",
        "습니다. ",
        "했다. ",
        "됐다. ",
        "였다. ",
        "합니다. ",
        "했습니다. ",
        "겠습니다. ",
        "봅니다. ",
        ". ",
        "。",
        "! ",
        "? ",
        ".\n",
    ]:
        last_sep = truncated.rfind(sep)
        if last_sep > max_length * 0.4:
            return truncated[: last_sep + len(sep)].strip()
    # Fall back to word boundary
    return truncate_text(text, max_length)


# Pre-compiled patterns for filtering noise titles (SEC forms, addresses, system pages)
_NOISE_TITLE_PATTERNS = [
    re.compile(r"^(?:Washington,?\s*DC\s*\d+)", re.IGNORECASE),
    re.compile(r"^(?:10-[KQ](?:\s|$))", re.IGNORECASE),
    re.compile(r"^(?:Form\s+\d)", re.IGNORECASE),
    re.compile(r"^(?:SEC\.gov\s*-?\s*SEC\.gov)", re.IGNORECASE),
    re.compile(r"^(?:EDGAR\s)", re.IGNORECASE),
    re.compile(r"^(?:AMENDMENT NO\.)", re.IGNORECASE),
]


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
    for pattern in _NOISE_TITLE_PATTERNS:
        if pattern.match(title):
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
            # Don't retry on client errors (401-422) — they won't succeed
            status = getattr(getattr(e, "response", None), "status_code", None)
            if status in (401, 402, 403, 404, 405, 422):
                logger.warning("Request to %s failed (HTTP %s, no retry): %s", url, status, e)
                break
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
