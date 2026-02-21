#!/usr/bin/env python3
"""Collect worldmonitor-curated RSS feeds and generate a daily briefing post."""

import os
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List
from urllib.parse import quote

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common.config import setup_logging
from common.dedup import DedupEngine
from common.markdown_utils import (
    escape_table_cell,
    html_source_tag,
    html_text,
    markdown_link,
    markdown_table,
)
from common.post_generator import PostGenerator
from common.rss_fetcher import fetch_rss_feeds_concurrent
from common.collector_metrics import log_collection_summary


logger = setup_logging("collect_worldmonitor_news")

WM_PROXY = "https://worldmonitor.app/api/rss-proxy?url="


def classify_theme(title: str) -> str:
    text = title.lower()
    if any(
        key in text
        for key in [
            "iran",
            "war",
            "military",
            "nuclear",
            "ukraine",
            "israel",
            "syria",
            "prisoner",
            "sanction",
        ]
    ):
        return "지정학/안보"
    if any(key in text for key in ["oil", "opec", "lng", "pipeline", "energy", "gas"]):
        return "에너지"
    if any(
        key in text
        for key in [
            "market",
            "stock",
            "bond",
            "inflation",
            "rate",
            "economy",
            "earnings",
            "etf",
        ]
    ):
        return "금융시장"
    if any(
        key in text
        for key in [
            "court",
            "judge",
            "law",
            "minister",
            "election",
            "administration",
            "policy",
        ]
    ):
        return "정책/법률"
    return "사회/기타"


def impact_label(theme: str) -> str:
    if theme == "지정학/안보":
        return "높음"
    if theme in {"에너지", "금융시장"}:
        return "중간~높음"
    if theme == "정책/법률":
        return "중간"
    return "낮음~중간"


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
            15,
            48,
            {
                "fallback_urls": [
                    "https://www.cnbc.com/id/100003114/device/rss/rss.html",
                    "https://news.google.com/rss/search?q=site:cnbc.com+markets+when:2d&hl=en-US&gl=US&ceid=US:en",
                ]
            },
        ),
        (
            wm_url("https://feeds.marketwatch.com/marketwatch/topstories/"),
            "WorldMonitor/MarketWatch",
            ["worldmonitor", "markets"],
            15,
            48,
            {
                "fallback_urls": [
                    "https://feeds.marketwatch.com/marketwatch/topstories/",
                    "https://news.google.com/rss/search?q=site:marketwatch.com+markets+when:2d&hl=en-US&gl=US&ceid=US:en",
                ]
            },
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
    started_at = time.monotonic()

    dedup = DedupEngine("worldmonitor_news_seen.json")
    generator = PostGenerator("market-analysis")

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    now = datetime.now(timezone.utc)
    post_title = f"WorldMonitor 글로벌 인텔리전스 브리핑 - {today}"

    if dedup.is_duplicate_exact(post_title, "worldmonitor", today):
        logger.info("WorldMonitor post already exists, skipping")
        log_collection_summary(
            logger,
            collector="collect_worldmonitor_news",
            source_count=0,
            unique_items=0,
            post_created=0,
            started_at=started_at,
            extras={"status": "duplicate"},
        )
        dedup.save()
        return

    items = fetch_worldmonitor_feeds()
    if not items:
        logger.warning("No worldmonitor items collected, skipping post")
        log_collection_summary(
            logger,
            collector="collect_worldmonitor_news",
            source_count=0,
            unique_items=0,
            post_created=0,
            started_at=started_at,
            extras={"status": "empty"},
        )
        dedup.save()
        return

    source_counter: Counter = Counter()
    theme_counter: Counter = Counter()
    rows: List[List[object]] = []
    source_rows: List[List[object]] = []
    ref_items: List[Dict[str, str]] = []

    for item in items:
        if len(rows) >= 20:
            break

        title = item.get("title", "").strip()
        link = item.get("link", "").strip()
        source = item.get("source", "unknown").strip()
        if not title:
            continue

        source_counter[source] += 1
        theme = classify_theme(title)
        theme_counter[theme] += 1
        impact = impact_label(theme)

        if link:
            rows.append(
                [
                    len(rows) + 1,
                    markdown_link(f"**{title}**", link),
                    theme,
                    impact,
                    source,
                ]
            )
            ref_items.append({"title": title, "link": link, "source": source})
        else:
            rows.append(
                [
                    len(rows) + 1,
                    f"**{escape_table_cell(title)}**",
                    theme,
                    impact,
                    source,
                ]
            )

    total_items = len(rows)
    top_sources = ", ".join(
        f"{name} ({count}건)" for name, count in source_counter.most_common(5)
    )

    for name, count in source_counter.most_common(6):
        ratio = (count / max(total_items, 1)) * 100
        source_rows.append([name, f"{count}건", f"{ratio:.0f}%"])

    theme_rows = []
    for theme, count in theme_counter.most_common(5):
        ratio = (count / max(total_items, 1)) * 100
        width = max(8, min(100, int(ratio)))
        theme_rows.append(
            '<div class="theme-row">'
            f'<span class="theme-label">{theme}</span>'
            '<div class="bar-track">'
            f'<div class="bar-fill bar-fill-blue" style="width:{width}%"></div>'
            "</div>"
            f'<span class="theme-count">{count}건 ({ratio:.0f}%)</span>'
            "</div>"
        )

    content_parts = [
        f"**{today}** 기준 WorldMonitor 연계 소스에서 글로벌 이벤트/시장/에너지 관련 뉴스 {total_items}건을 정리했습니다.",
        "",
        '<div class="alert-box alert-info"><strong>오늘의 글로벌 리스크 스냅샷</strong><ul>',
        f"<li>총 수집: <strong>{total_items}건</strong></li>",
        f"<li>핵심 테마: <strong>{', '.join(t for t, _ in theme_counter.most_common(3))}</strong></li>",
        f"<li>집중 출처: <strong>{source_counter.most_common(1)[0][0] if source_counter else 'N/A'}</strong></li>",
        "</ul></div>",
        "",
        "## 핵심 요약",
        f"- 수집 건수: **{total_items}건**",
        "- 범위: 글로벌 지정학, 금융시장, 에너지 이슈",
        f"- 주요 출처: {top_sources}",
        "",
        "## 이슈 분포",
        '<div class="stat-grid">',
        f'<div class="stat-item"><div class="stat-value">{total_items}</div><div class="stat-label">총 이슈</div></div>',
        f'<div class="stat-item"><div class="stat-value">{len(theme_counter)}</div><div class="stat-label">테마 수</div></div>',
        f'<div class="stat-item"><div class="stat-value">{len(source_counter)}</div><div class="stat-label">출처 수</div></div>',
        f'<div class="stat-item"><div class="stat-value">{theme_counter.get("지정학/안보", 0)}</div><div class="stat-label">안보 이슈</div></div>',
        "</div>",
        "",
        '<div class="theme-distribution">',
    ]
    content_parts.extend(theme_rows)
    content_parts.extend(
        [
            "</div>",
            "",
            "## 주요 이슈",
            "",
            markdown_table(
                ["#", "이슈", "테마", "시장 영향", "출처"],
                rows,
                aligns=["center", "left", "center", "center", "left"],
            ),
        ]
    )

    content_parts.extend(
        [
            "",
            "## 출처 커버리지",
            "",
            markdown_table(
                ["출처", "건수", "비중"],
                source_rows,
                aligns=["left", "right", "right"],
            ),
        ]
    )

    if ref_items:
        content_parts.extend(["", "## 원문 링크 묶음"])
        seen = set()
        unique_refs = []
        for ref in ref_items[:20]:
            link = ref["link"]
            if link in seen:
                continue
            seen.add(link)
            unique_refs.append(ref)

        content_parts.append(
            '<div class="wm-reference-summary">'
            "<strong>원문 링크 탐색 가이드</strong>"
            "<p>시장 영향이 높은 이슈를 우선 확인할 수 있도록 출처별 커버리지를 함께 제공합니다.</p>"
            "</div>"
        )

        source_pills = []
        for source, count in Counter(ref["source"] for ref in unique_refs).most_common(
            6
        ):
            source_pills.append(html_source_tag(f"{source} · {count}건"))
        if source_pills:
            content_parts.append(
                '<div class="wm-reference-pills">' + " ".join(source_pills) + "</div>"
            )

        detail_lines = [
            f'<details class="wm-reference-details"><summary>전체 원문 {len(unique_refs)}건 펼치기</summary><div class="details-content">',
            '<ol class="wm-reference-list">',
        ]
        for ref in unique_refs:
            link = html_text(ref["link"])
            title = html_text(ref["title"][:110])
            source = html_text(ref["source"])
            detail_lines.append(
                "<li>"
                f'<a href="{link}" target="_blank" rel="noopener noreferrer">{title}</a>'
                f"{html_source_tag(source)}"
                "</li>"
            )
        detail_lines.extend(["</ol>", "</div></details>"])
        content_parts.append("\n".join(detail_lines))
    else:
        content_parts.extend(["", "## 원문 링크 묶음"])
        content_parts.append(
            '<details class="wm-reference-details"><summary>전체 원문 0건</summary>'
            '<div class="details-content"><p>수집된 원문 링크가 없습니다.</p></div>'
            "</details>"
        )

    content_parts.extend(
        [
            "",
            "## 읽는 방법",
            "- **지정학/안보(높음)**: 금/원유/방산/안전자산 변동성과 동시 확인",
            "- **에너지(중간~높음)**: 원유/가스 가격과 인플레이션 민감 섹터 연동 점검",
            "- **정책/법률(중간)**: 규제 발표 시 섹터별 이벤트 드리븐 리스크 점검",
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
    unique_count = len(
        {
            f"{item.get('title', '')}|{item.get('source', '')}|{item.get('link', '')}"
            for item in items
            if item.get("title")
        }
    )
    log_collection_summary(
        logger,
        collector="collect_worldmonitor_news",
        source_count=len(source_counter),
        unique_items=unique_count,
        post_created=1 if filepath else 0,
        started_at=started_at,
    )


if __name__ == "__main__":
    main()
