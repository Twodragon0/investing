#!/usr/bin/env python3
"""Collect worldmonitor-curated RSS feeds and generate a daily briefing post."""

import os
import sys
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List
from urllib.parse import quote

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common.config import setup_logging
from common.dedup import DedupEngine
from common.post_generator import PostGenerator
from common.rss_fetcher import fetch_rss_feeds_concurrent


logger = setup_logging("collect_worldmonitor_news")

WM_PROXY = "https://worldmonitor.app/api/rss-proxy?url="


def wm_url(source_url: str) -> str:
    return WM_PROXY + quote(source_url, safe="")


def fetch_worldmonitor_feeds() -> List[Dict[str, Any]]:
    feeds = [
        (
            wm_url("https://feeds.bbci.co.uk/news/world/rss.xml"),
            "WorldMonitor/BBC World",
            ["worldmonitor", "geopolitics"],
        ),
        (
            wm_url("https://www.theguardian.com/world/rss"),
            "WorldMonitor/Guardian World",
            ["worldmonitor", "geopolitics"],
        ),
        (
            wm_url("https://www.aljazeera.com/xml/rss/all.xml"),
            "WorldMonitor/Al Jazeera",
            ["worldmonitor", "middleeast"],
        ),
        (
            wm_url(
                "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114"
            ),
            "WorldMonitor/CNBC",
            ["worldmonitor", "markets"],
        ),
        (
            wm_url("https://feeds.marketwatch.com/marketwatch/topstories/"),
            "WorldMonitor/MarketWatch",
            ["worldmonitor", "markets"],
        ),
        (
            wm_url("https://www.ft.com/rss/home"),
            "WorldMonitor/Financial Times",
            ["worldmonitor", "markets"],
        ),
        (
            wm_url(
                "https://news.google.com/rss/search?q=(oil+price+OR+OPEC+OR+pipeline+OR+LNG)+when:2d&hl=en-US&gl=US&ceid=US:en"
            ),
            "WorldMonitor/Energy",
            ["worldmonitor", "energy"],
        ),
    ]
    return fetch_rss_feeds_concurrent(feeds)


def main() -> None:
    logger.info("=== Starting worldmonitor feed collection ===")

    dedup = DedupEngine("worldmonitor_news_seen.json")
    generator = PostGenerator("market-analysis")

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    now = datetime.now(timezone.utc)
    post_title = f"WorldMonitor 글로벌 인텔리전스 브리핑 - {today}"

    if dedup.is_duplicate_exact(post_title, "worldmonitor", today):
        logger.info("WorldMonitor post already exists, skipping")
        dedup.save()
        return

    items = fetch_worldmonitor_feeds()
    if not items:
        logger.warning("No worldmonitor items collected, skipping post")
        dedup.save()
        return

    source_counter: Counter = Counter()
    rows: List[str] = []
    ref_items: List[Dict[str, str]] = []

    for item in items:
        title = item.get("title", "").strip()
        link = item.get("link", "").strip()
        source = item.get("source", "unknown").strip()
        if not title:
            continue

        source_counter[source] += 1

        if link:
            rows.append(f"| {len(rows) + 1} | [**{title}**]({link}) | {source} |")
            ref_items.append({"title": title, "link": link, "source": source})
        else:
            rows.append(f"| {len(rows) + 1} | **{title}** | {source} |")

    rows = rows[:20]
    top_sources = ", ".join(
        f"{name} ({count}건)" for name, count in source_counter.most_common(5)
    )

    content_parts = [
        f"**{today}** 기준 WorldMonitor 연계 소스에서 글로벌 이벤트/시장/에너지 관련 뉴스 {len(rows)}건을 정리했습니다.",
        "",
        "## 핵심 요약",
        f"- 수집 건수: **{len(rows)}건**",
        "- 범위: 글로벌 지정학, 금융시장, 에너지 이슈",
        f"- 주요 출처: {top_sources}",
        "",
        "## 주요 이슈",
        "| # | 제목 | 출처 |",
        "|---|------|------|",
    ]
    content_parts.extend(rows)

    if ref_items:
        content_parts.extend(
            [
                "",
                "## 참고 링크",
            ]
        )
        seen = set()
        rank = 1
        for ref in ref_items[:20]:
            link = ref["link"]
            if link in seen:
                continue
            seen.add(link)
            content_parts.append(
                f"{rank}. [{ref['title'][:90]}]({link}) - {ref['source']}"
            )
            rank += 1

    content_parts.extend(
        [
            "",
            "> *본 브리핑은 worldmonitor.app RSS proxy를 통해 자동 수집된 데이터를 기반으로 하며, 투자 조언이 아닙니다.*",
            "",
            "---",
            f"**데이터 수집 시각**: {now.strftime('%Y-%m-%d %H:%M')} UTC",
            "**연계 소스**: worldmonitor.app/api/rss-proxy",
        ]
    )

    content = "\n".join(content_parts)

    filepath = generator.create_post(
        title=post_title,
        content=content,
        date=now,
        tags=["worldmonitor", "geopolitics", "macro", "daily-digest"],
        source="worldmonitor",
        source_url="https://worldmonitor.app",
        lang="ko",
        slug="daily-worldmonitor-briefing",
    )

    if filepath:
        dedup.mark_seen(post_title, "worldmonitor", today)
        logger.info("Created worldmonitor briefing: %s", filepath)

    dedup.save()
    logger.info("=== Worldmonitor feed collection complete ===")


if __name__ == "__main__":
    main()
