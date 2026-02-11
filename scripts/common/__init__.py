"""Common utilities for Investing Dragon news collectors."""

from .config import get_env, get_env_bool
from .dedup import DedupEngine
from .post_generator import PostGenerator
from .utils import sanitize_string, validate_url, slugify
from .rss_fetcher import fetch_rss_feed
from .summarizer import ThemeSummarizer
from .crypto_api import (
    fetch_coingecko_top_coins,
    fetch_coingecko_trending,
    fetch_coingecko_global,
    fetch_fear_greed_index,
)
from .formatters import fmt_number, fmt_percent

__all__ = [
    "get_env",
    "get_env_bool",
    "DedupEngine",
    "PostGenerator",
    "sanitize_string",
    "validate_url",
    "slugify",
    "fetch_rss_feed",
    "ThemeSummarizer",
    "fetch_coingecko_top_coins",
    "fetch_coingecko_trending",
    "fetch_coingecko_global",
    "fetch_fear_greed_index",
    "fmt_number",
    "fmt_percent",
]
