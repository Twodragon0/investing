"""Shared RSS feed fetcher used by multiple collection scripts."""

import logging
import requests
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any
from bs4 import BeautifulSoup
from .config import get_ssl_verify
from .utils import sanitize_string, parse_date

logger = logging.getLogger(__name__)

VERIFY_SSL = get_ssl_verify()
REQUEST_TIMEOUT = 15
USER_AGENT = "Mozilla/5.0 (compatible; InvestingDragon/1.0)"

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
) -> List[Dict[str, Any]]:
    """Fetch news items from an RSS feed.

    Parses <item> elements and returns a list of dicts with keys:
    title, description, link, published, source, tags.
    """
    try:
        resp = requests.get(
            url,
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
                    BeautifulSoup(raw_desc, "html.parser").get_text(" ", strip=True), 500
                )

            published_str = date_el.get_text(strip=True) if date_el else ""

            # Freshness filter: skip items older than max_age_hours
            if max_age_hours and published_str:
                pub_dt = parse_date(published_str)
                if pub_dt:
                    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
                    if pub_dt < cutoff:
                        continue

            items.append({
                "title": title,
                "description": description,
                "link": link_val,
                "published": published_str,
                "source": source_name,
                "tags": tags,
            })
        logger.info("RSS %s: fetched %d items", source_name, len(items))
        _feed_health.setdefault(url, {"ok": 0, "fail": 0, "last_error": ""})
        _feed_health[url]["ok"] += 1
        return items
    except requests.exceptions.RequestException as e:
        logger.warning("RSS %s fetch failed: %s", source_name, e)
        _feed_health.setdefault(url, {"ok": 0, "fail": 0, "last_error": ""})
        _feed_health[url]["fail"] += 1
        _feed_health[url]["last_error"] = str(e)
        return []
