"""Shared RSS feed fetcher used by multiple collection scripts."""

import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, unquote, urlparse

import requests
from bs4 import BeautifulSoup

from .config import REQUEST_TIMEOUT, USER_AGENT, get_ssl_verify
from .utils import parse_date, remove_sponsored_text, sanitize_string, truncate_sentence

logger = logging.getLogger(__name__)

VERIFY_SSL = get_ssl_verify()

# Feed health tracking: {url: {"ok": int, "fail": int, "last_error": str}}
_feed_health: Dict[str, Dict[str, Any]] = {}


def get_feed_health() -> Dict[str, Dict[str, Any]]:
    """Return a copy of the feed health stats."""
    return dict(_feed_health)


# Common source suffixes to strip from RSS titles
_SOURCE_SUFFIX_RE = re.compile(
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
    # Domain suffixes
    r"|v\.daum\.net|gukjenews\.com|ilyoseoul\.co\.kr"
    r"|ir\.edaily\.co\.kr|simplywall\.st"
    r"|[a-z][a-z0-9-]*\.(?:com|co\.kr|net|org|io)"
    r")\s*$",
    re.IGNORECASE,
)


def _clean_rss_title(title: str) -> str:
    """Remove trailing source names and decorative markers from RSS titles."""
    cleaned = _SOURCE_SUFFIX_RE.sub("", title).strip()
    # Remove decorative prefixes like "▒종합 경제정보 미디어 - 이데일리IR▒"
    cleaned = re.sub(r"^[▒▶▷►◆◇■□●○※☆★\[\]【】〔〕]+\s*", "", cleaned)
    cleaned = re.sub(r"\s*[▒▶▷►◆◇■□●○※☆★\[\]【】〔〕]+\s*$", "", cleaned)
    # Remove Korean news category tags like "[속보]", "[단독]", "(종합)", "(1보)"
    cleaned = re.sub(r"^\s*[\[〈<]\s*(?:속보|단독|긴급|종합|1보|2보|3보|포토|영상|인터뷰)\s*[\]〉>]\s*", "", cleaned)
    cleaned = re.sub(r"^\s*\(\s*(?:속보|단독|종합|1보|2보|3보)\s*\)\s*", "", cleaned)
    return cleaned if len(cleaned) >= 10 else title


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
                    cleaned_desc = BeautifulSoup(raw_desc, "html.parser").get_text(" ", strip=True)
                    # Remove Korean news boilerplate
                    cleaned_desc = re.sub(
                        r"(?:무단\s*전재\s*및\s*재배포\s*금지|저작권자\s*©[^.]*\.|"
                        r"기사제보[^.]*\.|ⓒ[^.]*\.)",
                        "",
                        cleaned_desc,
                    )
                    # Remove trailing whitespace/dots artifacts
                    cleaned_desc = re.sub(r"\s*\.{2,}\s*$", "", cleaned_desc)
                    cleaned_desc = re.sub(r"\s+", " ", cleaned_desc).strip()
                    description = truncate_sentence(sanitize_string(cleaned_desc, 600), 300)

                published_str = date_el.get_text(strip=True) if date_el else ""

                if max_age_hours and published_str:
                    pub_dt = parse_date(published_str)
                    if pub_dt:
                        cutoff = datetime.now(UTC) - timedelta(hours=max_age_hours)
                        if pub_dt < cutoff:
                            continue

                title = remove_sponsored_text(title)
                title = _clean_rss_title(title)
                description = remove_sponsored_text(description)

                # Extract image URL from RSS entry
                image_url = ""
                # 1. media:content (most common for news RSS)
                # BS4 xml parser may strip namespace prefix → try both
                media = entry.find("media:content") or entry.find("content", attrs={"url": True})
                if media and media.get("url"):
                    image_url = media["url"]
                # 2. media:thumbnail
                if not image_url:
                    thumb = entry.find("media:thumbnail") or entry.find("thumbnail", attrs={"url": True})
                    if thumb and thumb.get("url"):
                        image_url = thumb["url"]
                # 3. enclosure (podcast/media feeds)
                if not image_url:
                    enclosure = entry.find("enclosure")
                    if enclosure and enclosure.get("url"):
                        enc_type = str(enclosure.get("type", "") or "")
                        if enc_type.startswith("image/") or enc_type == "":
                            image_url = enclosure["url"]
                # 4. Embedded <img> in description HTML
                if not image_url and desc_el:
                    raw_html = str(desc_el)
                    img_match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', raw_html)
                    if img_match:
                        image_url = img_match.group(1)

                item_data = {
                    "title": title,
                    "description": description,
                    "link": link_val,
                    "published": published_str,
                    "source": source_name,
                    "tags": tags,
                }
                if image_url:
                    item_data["image"] = image_url

                items.append(item_data)

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
