"""Common utilities for Investing Dragon news collectors."""

from .config import get_env, get_env_bool
from .crypto_api import (
    fetch_coingecko_global,
    fetch_coingecko_top_coins,
    fetch_coingecko_trending,
    fetch_fear_greed_index,
)
from .dedup import DedupEngine
from .formatters import fmt_number, fmt_percent
from .post_generator import PostGenerator
from .rss_fetcher import fetch_rss_feed
from .summarizer import ThemeSummarizer
from .utils import (
    parse_date,
    request_with_retry,
    sanitize_string,
    slugify,
    validate_url,
)

try:
    from .browser import (
        BrowserSession,
        extract_google_news_links,
        is_playwright_available,
        scrape_page,
    )
except ImportError:
    BrowserSession = None
    scrape_page = None
    extract_google_news_links = None

    def is_playwright_available():
        return False


__all__ = [
    "get_env",
    "get_env_bool",
    "DedupEngine",
    "PostGenerator",
    "sanitize_string",
    "validate_url",
    "slugify",
    "parse_date",
    "request_with_retry",
    "fetch_rss_feed",
    "ThemeSummarizer",
    "fetch_coingecko_top_coins",
    "fetch_coingecko_trending",
    "fetch_coingecko_global",
    "fetch_fear_greed_index",
    "fmt_number",
    "fmt_percent",
    "BrowserSession",
    "scrape_page",
    "is_playwright_available",
    "extract_google_news_links",
]
