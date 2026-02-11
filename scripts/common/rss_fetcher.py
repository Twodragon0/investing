"""Shared RSS feed fetcher used by multiple collection scripts."""

import logging
import requests
from typing import List, Dict, Any
from bs4 import BeautifulSoup
from .config import get_ssl_verify
from .utils import sanitize_string

logger = logging.getLogger(__name__)

VERIFY_SSL = get_ssl_verify()
REQUEST_TIMEOUT = 15
USER_AGENT = "Mozilla/5.0 (compatible; InvestingDragon/1.0)"


def fetch_rss_feed(
    url: str,
    source_name: str,
    tags: List[str],
    limit: int = 15,
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

            items.append({
                "title": title,
                "description": description,
                "link": link_val,
                "published": date_el.get_text(strip=True) if date_el else "",
                "source": source_name,
                "tags": tags,
            })
        logger.info("RSS %s: fetched %d items", source_name, len(items))
        return items
    except requests.exceptions.RequestException as e:
        logger.warning("RSS %s fetch failed: %s", source_name, e)
        return []
