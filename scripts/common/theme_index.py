"""ThemeIndex: lazily score news items per theme and group articles by theme.

Extracted from ``scripts/common/summarizer.py`` to keep theme scoring/indexing
concerns separate from the rest of ``ThemeSummarizer`` markdown rendering.

External collectors (``scripts/collect_*.py``) historically read
``summarizer._theme_articles`` directly. ``ThemeSummarizer`` exposes
``@property`` adapters that forward to a ``ThemeIndex`` instance so this
extraction is API-preserving.
"""

import re
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

from .themes import THEMES, TOP_THEMES_COUNT


class ThemeIndex:
    """Score themes by keyword frequency and group articles by their best theme."""

    def __init__(self, items: List[Dict[str, Any]]):
        self.items = items
        self._theme_scores: Dict[str, int] = {}
        self._theme_articles: Dict[str, List[Dict[str, Any]]] = {}
        self._scored = False

    def _ensure_scored(self):
        """Score themes lazily on first access."""
        if self._scored:
            return
        self._score_themes()
        self._scored = True

    def _score_themes(self):
        """Score each theme by keyword frequency across all items."""
        all_text = " ".join(
            (item.get("title_original", item.get("title", "")) + " " + item.get("description", ""))
            for item in self.items
        ).lower()

        token_freq = Counter(re.findall(r"[a-z가-힣]+", all_text))

        for _theme_name, theme_key, _emoji, keywords in THEMES:
            score = sum(token_freq.get(kw, 0) for kw in keywords)
            for kw in keywords:
                if " " in kw:
                    score += all_text.count(kw)
            self._theme_scores[theme_key] = score

        # Match articles to themes (each article to its best-matching theme)
        article_assigned: Dict[int, str] = {}
        for _theme_name, theme_key, _emoji, keywords in THEMES:
            matched = []
            # Build regex patterns for word-boundary matching on short keywords
            kw_patterns = []
            plain_kw = []
            for kw in keywords:
                if " " in kw or len(kw) >= 4 or re.search(r"[가-힣]", kw):
                    plain_kw.append(kw)
                else:
                    kw_patterns.append(re.compile(r"\b" + re.escape(kw) + r"\b", re.IGNORECASE))
            for idx, item in enumerate(self.items):
                item_text = (
                    item.get("title_original", item.get("title", "")) + " " + item.get("description", "")
                ).lower()
                hit = any(kw in item_text for kw in plain_kw)
                if not hit:
                    item_text_raw = (
                        item.get("title_original", item.get("title", "")) + " " + item.get("description", "")
                    )
                    hit = any(p.search(item_text_raw) for p in kw_patterns)
                if hit:
                    matched.append(item)
                    if idx not in article_assigned:
                        article_assigned[idx] = theme_key
            self._theme_articles[theme_key] = matched

    def get_top_themes(self) -> List[Tuple[str, str, str, int]]:
        """Return top themes as (name, key, emoji, article_count) tuples."""
        self._ensure_scored()
        theme_lookup = {key: (name, emoji) for name, key, emoji, _ in THEMES}
        ranked = sorted(self._theme_scores.items(), key=lambda x: x[1], reverse=True)
        result = []
        for key, score in ranked:
            if score <= 0:
                continue
            name, emoji = theme_lookup.get(key, (key, ""))
            count = len(self._theme_articles.get(key, []))
            if count > 0:
                result.append((name, key, emoji, count))
            if len(result) >= TOP_THEMES_COUNT:
                break
        return result

    def get_articles_for_theme(
        self,
        theme_key: str,
        default: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        """Return articles matched to theme_key as a shallow copy.

        Scores themes lazily on first call. Article dicts inside the list
        are NOT copied — callers must treat them as read-only.
        """
        self._ensure_scored()
        if theme_key not in self._theme_articles:
            return list(default) if default is not None else []
        return list(self._theme_articles[theme_key])
