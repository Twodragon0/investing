"""Shared RSS feed fetcher used by multiple collection scripts."""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, unquote, urlparse

import requests
from bs4 import BeautifulSoup

from .config import REQUEST_TIMEOUT, USER_AGENT, get_ssl_verify
from .utils import parse_date, remove_sponsored_text, sanitize_string

logger = logging.getLogger(__name__)

VERIFY_SSL = get_ssl_verify()

# Feed health tracking: {url: {"ok": int, "fail": int, "last_error": str}}
_feed_health: Dict[str, Dict[str, Any]] = {}


def get_feed_health() -> Dict[str, Dict[str, Any]]:
    """Return a copy of the feed health stats."""
    return dict(_feed_health)


def fetch_rss_feed(
    url: str,
    source_name: str,
    tags: List[str],
    limit: int = 15,
    max_age_hours: int = 48,
    fallback_urls: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Fetch news items from an RSS feed.

    Parses <item> elements and returns a list of dicts with keys:
    title, description, link, published, source, tags.
    """
    candidates: List[str] = [url]
    if fallback_urls:
        for fallback_url in fallback_urls:
            if fallback_url and fallback_url not in candidates:
                candidates.append(fallback_url)

    parsed = urlparse(url)
    if parsed.netloc == "worldmonitor.app" and parsed.path == "/api/rss-proxy":
        original = parse_qs(parsed.query).get("url", [""])[0]
        if original:
            decoded = unquote(original)
            if decoded and decoded not in candidates:
                candidates.append(decoded)

    last_error: Optional[str] = None

    for idx, candidate_url in enumerate(candidates, start=1):
        try:
            resp = requests.get(
                candidate_url,
                timeout=REQUEST_TIMEOUT,
                verify=VERIFY_SSL,
                headers={"User-Agent": USER_AGENT},
            )
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "xml")

            items = []
            entries = soup.find_all("item")[:limit]
            is_atom = False
            if not entries:
                entries = soup.find_all("entry")[:limit]
                is_atom = True

            for entry in entries:
                title_el = entry.find("title")

                if is_atom:
                    link_el = entry.find("link")
                    link_val = link_el.get("href", "") if link_el else ""
                    date_el = entry.find("updated") or entry.find("published")
                    desc_el = entry.find("summary") or entry.find("content")
                else:
                    link_el = entry.find("link")
                    link_val = link_el.get_text(strip=True) if link_el else ""
                    date_el = entry.find("pubDate")
                    desc_el = entry.find("description")

                title = sanitize_string(title_el.get_text(strip=True), 300) if title_el else ""
                if not title:
                    continue

                description = ""
                if desc_el:
                    raw_desc = desc_el.get_text(strip=True)
                    description = sanitize_string(
                        BeautifulSoup(raw_desc, "html.parser").get_text(" ", strip=True),
                        500,
                    )

                published_str = date_el.get_text(strip=True) if date_el else ""

                if max_age_hours and published_str:
                    pub_dt = parse_date(published_str)
                    if pub_dt:
                        cutoff = datetime.now(UTC) - timedelta(hours=max_age_hours)
                        if pub_dt < cutoff:
                            continue

                title = remove_sponsored_text(title)
                description = remove_sponsored_text(description)

                items.append(
                    {
                        "title": title,
                        "description": description,
                        "link": link_val,
                        "published": published_str,
                        "source": source_name,
                        "tags": tags,
                    }
                )

            logger.info(
                "RSS %s: fetched %d items%s",
                source_name,
                len(items),
                "" if idx == 1 else f" (fallback {idx - 1})",
            )
            _feed_health.setdefault(url, {"ok": 0, "fail": 0, "last_error": ""})
            _feed_health[url]["ok"] += 1
            _feed_health[url]["last_error"] = ""
            return items
        except requests.exceptions.RequestException as e:
            last_error = str(e)
            logger.warning(
                "RSS %s fetch failed (%d/%d): %s",
                source_name,
                idx,
                len(candidates),
                e,
            )

    _feed_health.setdefault(url, {"ok": 0, "fail": 0, "last_error": ""})
    _feed_health[url]["fail"] += 1
    _feed_health[url]["last_error"] = last_error or "unknown"
    return []


def fetch_rss_feeds_concurrent(
    feeds: list,
    max_workers: int = 5,
) -> list:
    """Fetch multiple RSS feeds concurrently.

    Parameters
    ----------
    feeds : list of tuples
        Each tuple is ``(url, source_name, tags)`` and optionally
        ``(url, source_name, tags, limit, max_age_hours)``.
    max_workers : int
        Maximum number of parallel threads (default 5).

    Returns
    -------
    list
        Combined list of news items from all feeds.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    all_items: List[Dict[str, Any]] = []

    def _fetch_one(feed_tuple):
        url, name, tags = feed_tuple[0], feed_tuple[1], feed_tuple[2]
        limit = feed_tuple[3] if len(feed_tuple) > 3 else 15
        max_age = feed_tuple[4] if len(feed_tuple) > 4 else 48
        options = feed_tuple[5] if len(feed_tuple) > 5 and isinstance(feed_tuple[5], dict) else {}
        fallback_urls = options.get("fallback_urls", [])
        return fetch_rss_feed(
            url,
            name,
            tags,
            limit=limit,
            max_age_hours=max_age,
            fallback_urls=fallback_urls,
        )

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_fetch_one, f): f for f in feeds}
        for future in as_completed(futures):
            try:
                items = future.result(timeout=25)
                all_items.extend(items)
            except TimeoutError:
                feed = futures[future]
                logger.warning("RSS fetch timed out for %s", feed[1])
            except Exception as e:
                feed = futures[future]
                logger.warning("Concurrent RSS fetch failed for %s: %s", feed[1], e)

    return all_items
