"""Deduplication engine for news posts.

Uses SHA256 hashing on normalized (title + source + date) and
fuzzy matching with difflib.SequenceMatcher for cross-source dedup.
State is persisted in JSON files under _state/.
"""

import hashlib
import json
import os
import re
import logging
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from typing import Dict, List

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
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


class DedupEngine:
    """Deduplication engine with JSON state persistence."""

    def __init__(self, state_file: str, max_age_days: int = 30):
        self.state_path = os.path.join(STATE_DIR, state_file)
        self.max_age_days = max_age_days
        self.seen: Dict[str, str] = {}  # hash -> timestamp
        self.titles: List[str] = []  # for fuzzy matching
        self._load()

    def _load(self) -> None:
        """Load state from JSON file."""
        if os.path.exists(self.state_path):
            try:
                with open(self.state_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.seen = data.get("seen", {})
                self.titles = data.get("titles", [])
                self._prune()
            except (json.JSONDecodeError, KeyError, IOError, OSError):
                logger.warning("Corrupt state file %s, resetting", self.state_path)
                self.seen = {}
                self.titles = []

    def _prune(self) -> None:
        """Remove entries older than max_age_days."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=self.max_age_days)).isoformat()
        pruned = {k: v for k, v in self.seen.items() if v >= cutoff}
        if len(pruned) < len(self.seen):
            logger.info("Pruned %d old entries from dedup state", len(self.seen) - len(pruned))
        self.seen = pruned
        # Keep titles list manageable
        self.titles = self.titles[-(5000):]

    def save(self) -> None:
        """Persist state to JSON file (atomic write via temp file)."""
        os.makedirs(os.path.dirname(self.state_path), exist_ok=True)
        tmp_path = self.state_path + ".tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump({"seen": self.seen, "titles": self.titles}, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self.state_path)
        except OSError as e:
            logger.warning("Failed to save dedup state: %s", e)
            # Clean up temp file if it exists
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    def is_duplicate(self, title: str, source: str, date_str: str) -> bool:
        """Check if a news item is a duplicate.

        Uses exact hash match first, then fuzzy title matching (>80% similarity).
        """
        if not title or not title.strip():
            return True

        # Exact hash check
        h = _make_hash(title, source, date_str)
        if h in self.seen:
            return True

        # Fuzzy matching against recent titles
        normalized_title = _normalize(title)
        for existing_title in self.titles[-500:]:
            ratio = SequenceMatcher(None, normalized_title, existing_title).ratio()
            if ratio > 0.80:
                logger.debug("Fuzzy duplicate: %.2f '%s' ~ '%s'", ratio, title[:50], existing_title[:50])
                return True

        return False

    def is_duplicate_exact(self, title: str, source: str, date_str: str) -> bool:
        """Check if a news item is a duplicate using exact hash match only.

        Use this for consolidated/daily digest posts where the title contains
        a date and fuzzy matching would incorrectly flag different days as duplicates.
        """
        if not title or not title.strip():
            return True

        h = _make_hash(title, source, date_str)
        return h in self.seen

    def mark_seen(self, title: str, source: str, date_str: str) -> None:
        """Mark a news item as seen."""
        h = _make_hash(title, source, date_str)
        self.seen[h] = datetime.now(timezone.utc).isoformat()
        self.titles.append(_normalize(title))
