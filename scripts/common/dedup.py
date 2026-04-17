"""Deduplication engine for news posts.

Uses SHA256 hashing on normalized (title + source + date) and
fuzzy matching with difflib.SequenceMatcher for cross-source dedup.
State is persisted in JSON files under _state/.
"""

import hashlib
import json
import logging
import os
import re
from datetime import UTC, datetime, timedelta
from difflib import SequenceMatcher
from typing import Dict, List, Union

logger = logging.getLogger(__name__)

# Repo root is two levels up from scripts/common/
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
STATE_DIR = os.path.join(REPO_ROOT, "_state")


def _normalize(text: str) -> str:
    """Normalize text for hashing: lowercase, strip whitespace/punctuation."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text


def _make_hash(title: str, source: str, date_str: str) -> str:
    """Create SHA256 hash ID from normalized title + source + date[:10]."""
    normalized = _normalize(title) + "|" + source + "|" + date_str[:10]
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]


def _normalize_url(url: str) -> str:
    """Normalize URL for dedup: strip tracking params and fragments."""
    if not url:
        return ""
    # Remove common tracking parameters and fragments
    url = re.sub(r"[?#].*$", "", url.strip())
    # Remove trailing slash
    url = url.rstrip("/")
    return url.lower()


class DedupEngine:
    """Deduplication engine with JSON state persistence."""

    SAME_DAY_THRESHOLD = 0.80
    CROSS_DAY_THRESHOLD = 0.95

    def __init__(self, state_file: str, max_age_days: int = 30):
        self.state_path = os.path.join(STATE_DIR, state_file)
        self.max_age_days = max_age_days
        self.seen: Dict[str, str] = {}  # hash -> timestamp
        self.titles: List[List[str]] = []  # [[normalized_title, date_str], ...]
        self.seen_urls: Dict[str, str] = {}  # normalized_url -> timestamp
        self._checked = 0
        self._duplicates = 0
        self._load()

    def _load(self) -> None:
        """Load state from JSON file."""
        if os.path.exists(self.state_path):
            try:
                with open(self.state_path, encoding="utf-8") as f:
                    data = json.load(f)
                self.seen = data.get("seen", {})
                raw_titles: List[Union[str, List[str]]] = data.get("titles", [])
                # Backward compatibility: convert old plain strings to [title, ""] pairs
                # Get file mtime as fallback date for old entries
                fallback_date = ""
                try:
                    mtime = os.path.getmtime(self.state_path)
                    fallback_date = datetime.fromtimestamp(mtime, tz=UTC).strftime("%Y-%m-%d")
                except OSError:
                    pass
                converted: List[List[str]] = []
                migrated_count = 0
                for entry in raw_titles:
                    if isinstance(entry, list) and len(entry) == 2:
                        converted.append(entry)
                    else:
                        converted.append([str(entry), fallback_date])
                        migrated_count += 1
                if migrated_count:
                    logger.warning(
                        "Migrated %d old dedup entries with fallback date %s",
                        migrated_count,
                        fallback_date,
                    )
                self.titles = converted
                self.seen_urls = data.get("seen_urls", {})
                self._prune()
            except (json.JSONDecodeError, KeyError, OSError):
                logger.warning("Corrupt state file %s, resetting", self.state_path)
                self.seen = {}
                self.titles = []
                self.seen_urls = {}

    def _prune(self) -> None:
        """Remove entries older than max_age_days."""
        cutoff = (datetime.now(UTC) - timedelta(days=self.max_age_days)).strftime("%Y-%m-%dT%H:%M:%S")
        pruned = {k: v for k, v in self.seen.items() if v >= cutoff}
        if len(pruned) < len(self.seen):
            logger.info("Pruned %d old entries from dedup state", len(self.seen) - len(pruned))
        self.seen = pruned
        # Prune old URLs
        pruned_urls = {k: v for k, v in self.seen_urls.items() if v >= cutoff}
        if len(pruned_urls) < len(self.seen_urls):
            logger.info("Pruned %d old URL entries", len(self.seen_urls) - len(pruned_urls))
        self.seen_urls = pruned_urls
        # Keep titles list manageable
        self.titles = self.titles[-(5000):]

    def save(self) -> None:
        """Persist state to JSON file (atomic write via temp file)."""
        os.makedirs(os.path.dirname(self.state_path), exist_ok=True)
        tmp_path = self.state_path + ".tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(
                    {"seen": self.seen, "titles": self.titles, "seen_urls": self.seen_urls},
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
            os.replace(tmp_path, self.state_path)
        except OSError as e:
            logger.warning("Failed to save dedup state: %s", e)
            # Clean up temp file if it exists
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    def log_stats(self) -> None:
        """Log dedup statistics for the current session."""
        if self._checked:
            kept = self._checked - self._duplicates
            logger.info(
                "Dedup stats: checked %d, removed %d duplicates, kept %d items",
                self._checked, self._duplicates, kept,
            )

    def is_duplicate(self, title: str, source: str, date_str: str, url: str = "") -> bool:
        """Check if a news item is a duplicate.

        Uses URL match first (catches same article from different source tags),
        then exact hash match, then date-aware fuzzy title matching:
        - Same-day comparisons use 0.80 threshold (catch rephrased duplicates)
        - Cross-day comparisons use 0.95 threshold (only catch near-identical titles)
        """
        if not title or not title.strip():
            return True
        self._checked += 1

        # URL-based dedup: same URL from different source tags
        if url:
            norm_url = _normalize_url(url)
            if norm_url and norm_url in self.seen_urls:
                logger.debug("URL duplicate: %s (source: %s)", url[:80], source)
                self._duplicates += 1
                return True

        # Exact hash check
        h = _make_hash(title, source, date_str)
        if h in self.seen:
            self._duplicates += 1
            return True

        # Date-aware fuzzy matching against recent titles
        normalized_title = _normalize(title)
        current_date = date_str[:10]
        for entry in self.titles[-1000:]:
            existing_title = entry[0] if isinstance(entry, list) else entry
            existing_date = entry[1] if isinstance(entry, list) and len(entry) > 1 else ""
            # Use stricter threshold for cross-day comparison
            threshold = self.SAME_DAY_THRESHOLD if existing_date == current_date else self.CROSS_DAY_THRESHOLD
            matcher = SequenceMatcher(None, normalized_title, existing_title)
            if matcher.quick_ratio() <= threshold:
                continue
            ratio = matcher.ratio()
            if ratio > threshold:
                logger.debug(
                    "Fuzzy duplicate (threshold=%.2f, %s): %.2f '%s' ~ '%s'",
                    threshold,
                    "same-day" if existing_date == current_date else "cross-day",
                    ratio,
                    title[:50],
                    existing_title[:50],
                )
                self._duplicates += 1
                return True

        return False

    def is_duplicate_exact(self, title: str, source: str, date_str: str) -> bool:
        """Check if a news item is a duplicate using exact hash match only.

        Use this for consolidated/daily digest posts where the title contains
        a date and fuzzy matching would incorrectly flag different days as duplicates.
        """
        if not title or not title.strip():
            return True
        self._checked += 1

        h = _make_hash(title, source, date_str)
        if h in self.seen:
            self._duplicates += 1
            return True
        return False

    def mark_seen(self, title: str, source: str, date_str: str, url: str = "") -> None:
        """Mark a news item as seen."""
        h = _make_hash(title, source, date_str)
        now_str = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S")
        self.seen[h] = now_str
        self.titles.append([_normalize(title), date_str[:10]])
        if url:
            norm_url = _normalize_url(url)
            if norm_url:
                self.seen_urls[norm_url] = now_str


def deduplicate_by_url(items: List[Dict], url_key: str = "link") -> List[Dict]:
    """Remove duplicate items sharing the same URL within a collection run.

    Keeps the first occurrence. Items without a URL are always kept.
    This is meant for in-session dedup before building a post, not
    cross-session (use DedupEngine for that).
    """
    seen: set = set()
    unique: List[Dict] = []
    removed = 0
    for item in items:
        url = item.get(url_key, "")
        if url:
            norm = _normalize_url(url)
            if norm in seen:
                removed += 1
                continue
            seen.add(norm)
        unique.append(item)
    if removed:
        logger.info("URL dedup removed %d duplicate items (%d → %d)", removed, len(items), len(unique))
    return unique
