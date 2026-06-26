#!/usr/bin/env python3
"""Generate a daily news summary post by reading today's collected posts.

Reads all posts generated for the current date and creates a comprehensive
summary post (pinned, market-analysis category) with priority-based structure:
1. Urgent alerts (P0) - crashes, hacks, executive orders
2. Market overview
3. Indicator dashboard
4. Political watch - politician trades/policy highlights
5. Important news (P1) - regulation, ETF, earnings
6. Category summaries
7. Notable news (P2)
8. Report links
"""

import glob
import os
import re
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common.config import SITE_URL, get_kst_timezone, setup_logging
from common.markdown_utils import (
    _normalize_url,
    markdown_link,
)
from common.post_generator import POSTS_DIR
from common.summarizer import ThemeSummarizer
from common.summary_post_categorizers import (  # noqa: F401  (재-export: gds.<name> 테스트/호출 호환)
    _extract_bold_lines,
    summarize_crypto_post,
    summarize_market_post,
    summarize_political_post,
    summarize_regulatory_post,
    summarize_security_post,
    summarize_social_post,
    summarize_stock_post,
    summarize_worldmonitor_post,
)
from common.summary_post_parsing import (  # noqa: F401  (재-export: gds.<name> 테스트/호출 호환)
    _extract_highlights,
    _is_similar_title,
    count_news_items,
    extract_bullet_points,
    extract_section,
    extract_table_rows,
    read_post_content,
    strip_html_tags,
)
from common.summary_sections import (  # noqa: F401  (재-export: gds.<name> 테스트/호출 호환)
    _NOISE_TITLE_PATTERNS,
    _REPORT_CATEGORY_LABELS,
    _SUMMARY_KEYWORD_LABELS,
    _analyze_sentiment,
    _best_non_noise_title,
    _build_briefing_section,
    _build_market_signal_section,
    _build_overview_section,
    _build_priority_and_category_sections,
    _build_snapshot_table,
    _clean_bullet_text,
    _clean_headline,
    _coverage_warnings,
    _cross_asset_topics,
    _description_for_korean_item,
    _display_title_for_korean_item,
    _extract_category_data_points,
    _extract_key_figures,
    _find_shared_topics_across_categories,
    _headline_for_korean_summary,
    _is_noise_title,
    _looks_english_heavy,
    _relation_rows,
    _render_generated_image,
    _sentiment_keywords,
    _strip_markdown_link,
    _summary_keywords_for_korean,
    _topic_hits,
)
from common.translator import get_display_title

logger = setup_logging("generate_daily_summary")


def get_post_url(filepath: str, today: str, category: str = "") -> str:
    """Generate absolute URL for a post following Jekyll permalink structure."""
    filename = os.path.basename(filepath)
    slug = filename.replace(f"{today}-", "").replace(".md", "")
    date_path = today.replace("-", "/")
    if category:
        return f"{SITE_URL}/{category}/{date_path}/{slug}/"
    return f"{SITE_URL}/{date_path}/{slug}/"


def _collect_all_news_items(summaries: List[Optional[Dict]]) -> List[Dict[str, Any]]:
    """Collect all news item titles+descriptions from post contents for priority classification."""
    items = []
    seen_titles = set()
    seen_urls: set[str] = set()
    for s in summaries:
        if not s or not s.get("content"):
            continue
        content = s["content"]
        in_card_section = False
        last_card_item: Optional[Dict[str, Any]] = None
        for line in content.split("\n"):
            line = line.strip()
            # Detect card section headers (### 🟠 비트코인, etc.)
            if line.startswith("### ") and "건)" in line:
                in_card_section = True
                continue
            # Extract from card format: **1. [Title](link)**
            if in_card_section and line.startswith("**") and "[" in line:
                match = re.search(r"\[([^\]]+)\]\(([^)]+)\)", line)
                if match:
                    title = match.group(1)
                    link = match.group(2)
                    url_key = _normalize_url(link)
                    # Deduplicate by normalized title and URL
                    norm = re.sub(r"[^a-z가-힣0-9]", "", title.lower())
                    if norm not in seen_titles and url_key not in seen_urls:
                        seen_titles.add(norm)
                        seen_urls.add(url_key)
                        last_card_item = {
                            "title": markdown_link(title, link),
                            "description": title,
                            "link": link,
                            "source": s.get("type", ""),
                        }
                        items.append(last_card_item)
                    else:
                        last_card_item = None
                else:
                    last_card_item = None
            # Capture description line right after a card item
            elif (
                in_card_section
                and last_card_item is not None
                and not line.startswith(("**", ">", "`", "#", "|", "---", "<"))
                and line
                and len(line) > 15
            ):
                last_card_item["description"] = line
                last_card_item = None
            # Stop card parsing at next major section
            if line.startswith("## ") and in_card_section:
                in_card_section = False

        # Second comprehensive pass: extract ALL links from the full content
        # 1. <a href="URL">Title</a> tags (details blocks, HTML)
        for match in re.finditer(r'<a\s+href="([^"]+)"[^>]*>([^<]+)</a>', content):
            link = match.group(1)
            title = match.group(2).strip()
            if not title or len(title) < 10:
                continue
            url_key = _normalize_url(link)
            norm = re.sub(r"[^a-z가-힣0-9]", "", title.lower())
            if norm not in seen_titles and url_key not in seen_urls:
                seen_titles.add(norm)
                seen_urls.add(url_key)
                items.append({"title": title, "description": title, "link": link, "source": s.get("type", "")})

        # 2. Bullet points with markdown links: - [Title](URL) or - **[Title](URL)**
        for match in re.finditer(r"[-*]\s+(?:\*\*)?(?:\d+\.\s*)?\[([^\]]+)\]\(([^)]+)\)", content):
            title = match.group(1).strip()
            link = match.group(2).strip()
            if not title or len(title) < 10:
                continue
            url_key = _normalize_url(link)
            norm = re.sub(r"[^a-z가-힣0-9]", "", title.lower())
            if norm not in seen_titles and url_key not in seen_urls:
                seen_titles.add(norm)
                seen_urls.add(url_key)
                items.append({"title": title, "description": title, "link": link, "source": s.get("type", "")})

        # 3. All remaining markdown links: [Title](URL) or [**Title**](URL) (tables, etc.)
        for match in re.finditer(r"\[(?:\*\*)?([^\]]+?)(?:\*\*)?\]\(([^)]+)\)", content):
            title = match.group(1).strip()
            link = match.group(2).strip()
            if not title or len(title) < 10:
                continue
            url_key = _normalize_url(link)
            norm = re.sub(r"[^a-z가-힣0-9]", "", title.lower())
            if norm not in seen_titles and url_key not in seen_urls:
                seen_titles.add(norm)
                seen_urls.add(url_key)
                items.append({"title": title, "description": title, "link": link, "source": s.get("type", "")})

    return items


def _to_theme_payload(
    summaries: Dict[str, Optional[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    payload = []
    topic_def = _cross_asset_topics()
    hit_totals = dict.fromkeys(topic_def.keys(), 0)
    for summary in summaries.values():
        hits = _topic_hits(summary)
        for k, v in hits.items():
            hit_totals[k] += v

    emojis = {
        "금리/유동성": "💰",
        "환율/달러": "💱",
        "정책/규제": "📋",
        "리스크 이벤트": "⚠️",
        "수급/심리": "🔄",
        "실적/지표": "📊",
    }

    for topic, score in sorted(hit_totals.items(), key=lambda x: x[1], reverse=True):
        if score <= 0:
            continue
        payload.append(
            {
                "name": topic,
                "emoji": emojis.get(topic, "•"),
                "count": score,
                "keywords": topic_def.get(topic, [])[:4],
            }
        )
    return payload[:5]


def _resolve_frontmatter_image(today: str, briefing_image: Optional[str]) -> str:
    if briefing_image:
        return briefing_image

    candidates = [
        f"news-briefing-daily-{today}.png",
        f"news-briefing-{today}.png",
        f"market-heatmap-{today}.png",
    ]
    for filename in candidates:
        image_path = os.path.join(POSTS_DIR, "..", "assets", "images", "generated", filename)
        if os.path.exists(image_path):
            return f"/assets/images/generated/{filename}"
    return ""


def _load_today_posts(
    today: str,
) -> Tuple[
    Dict[str, Optional[Dict[str, Any]]],
    List[Tuple[str, Any, str]],
    Optional[Dict[str, Any]],
    List[Optional[Dict[str, Any]]],
]:
    """Load and categorize all posts for *today*.

    Returns
    -------
    summary_map : dict
        Keys: crypto, stock, market, regulatory, social, worldmonitor, political.
    post_links : list[(name, count, url)]
    security_summary : dict | None
    all_summaries : list
        Flat list of per-category summaries (excluding market).
    """
    pattern = os.path.join(POSTS_DIR, f"{today}-*.md")
    today_posts = sorted(glob.glob(pattern))

    if not today_posts:
        return {}, [], None, []

    logger.info("Found %d posts for %s", len(today_posts), today)

    crypto_summary = None
    stock_summary = None
    security_summary = None
    regulatory_summary = None
    social_summary = None
    market_summary = None
    worldmonitor_summary = None
    political_summary = None

    post_links: List[Tuple[str, Any, str]] = []

    for filepath in today_posts:
        filename = os.path.basename(filepath)
        if "daily-news-summary" in filename or "test-post" in filename:
            continue

        post = read_post_content(filepath)
        slug = filename.replace(f"{today}-", "").replace(".md", "")

        if "crypto-news-digest" in slug:
            crypto_summary = summarize_crypto_post(post)
            crypto_summary["url"] = get_post_url(filepath, today, "crypto-news")
            post_links.append(("암호화폐 뉴스", crypto_summary["count"], crypto_summary["url"]))
        elif "stock-news-digest" in slug:
            stock_summary = summarize_stock_post(post)
            stock_summary["url"] = get_post_url(filepath, today, "stock-news")
            post_links.append(("주식 시장 뉴스", stock_summary["count"], stock_summary["url"]))
        elif "security-report" in slug:
            security_summary = summarize_security_post(post)
            security_summary["url"] = get_post_url(filepath, today, "security-alerts")
            post_links.append(("보안 리포트", security_summary["count"], security_summary["url"]))
        elif "regulatory-report" in slug:
            regulatory_summary = summarize_regulatory_post(post)
            regulatory_summary["url"] = get_post_url(filepath, today, "regulatory-news")
            post_links.append(("규제 동향", regulatory_summary["count"], regulatory_summary["url"]))
        elif "social-media-digest" in slug:
            social_summary = summarize_social_post(post)
            social_summary["url"] = get_post_url(filepath, today, "social-media")
            post_links.append(("소셜 미디어", social_summary["count"], social_summary["url"]))
        elif "political-trades-report" in slug:
            political_summary = summarize_political_post(post)
            political_summary["url"] = get_post_url(filepath, today, "political-trades")
            post_links.append(("정치인 거래", political_summary["count"], political_summary["url"]))
        elif slug == "daily-market-report" or slug.endswith("-market-report"):
            # Avoid matching crypto-market-report (already handled as crypto)
            if "crypto-market" in slug:
                continue
            market_summary = summarize_market_post(post)
            market_summary["url"] = get_post_url(filepath, today, "market-analysis")
            # Market report is a dashboard, not news items; count table rows as proxy
            market_count = count_news_items(post["content"])
            if not market_count:
                # Count Top 20 table rows as fallback
                top_rows = extract_table_rows(post["content"], "시가총액 Top 20", 25)
                market_count = len(top_rows) if top_rows else 0
            post_links.append(("시장 종합 리포트", market_count or "종합", market_summary["url"]))
        elif "worldmonitor-briefing" in slug:
            worldmonitor_summary = summarize_worldmonitor_post(post)
            worldmonitor_summary["url"] = get_post_url(filepath, today, "market-analysis")
            post_links.append(
                (
                    "월드모니터 브리핑",
                    worldmonitor_summary["count"],
                    worldmonitor_summary["url"],
                )
            )
        elif "defi-tvl-report" in slug:
            defi_post = read_post_content(filepath)
            defi_count = count_news_items(defi_post["content"])
            defi_url = get_post_url(filepath, today, "crypto-news")
            post_links.append(("DeFi TVL 리포트", defi_count or "-", defi_url))
        elif "fmp-economic-calendar" in slug:
            fmp_post = read_post_content(filepath)
            fmp_count = count_news_items(fmp_post["content"])
            fmp_url = get_post_url(filepath, today, "market-analysis")
            post_links.append(("경제 캘린더", fmp_count or "-", fmp_url))
        elif "blockchain-network-report" in slug:
            blockchain_post = read_post_content(filepath)
            blockchain_count = count_news_items(blockchain_post["content"])
            blockchain_url = get_post_url(filepath, today, "blockchain")
            post_links.append(("블록체인 네트워크", blockchain_count or "-", blockchain_url))

    summary_map = {
        "crypto": crypto_summary,
        "stock": stock_summary,
        "market": market_summary,
        "regulatory": regulatory_summary,
        "social": social_summary,
        "worldmonitor": worldmonitor_summary,
        "political": political_summary,
    }

    all_summaries = [
        crypto_summary,
        stock_summary,
        security_summary,
        regulatory_summary,
        social_summary,
        worldmonitor_summary,
        political_summary,
    ]

    return summary_map, post_links, security_summary, all_summaries


def _classify_and_analyze(
    all_summaries: List[Optional[Dict[str, Any]]],
    summary_map: Dict[str, Optional[Dict[str, Any]]],
) -> Dict[str, Any]:
    """Run priority classification and theme analysis.

    Returns dict with keys: priority_items, theme_payload, urgent_alerts,
    total_count, all_news_items, summarizer.
    """
    total_count = sum(s["count"] for s in all_summaries if s and s.get("count"))

    all_news_items = _collect_all_news_items(all_summaries)
    priority_items: Dict[str, list] = {"P0": [], "P1": [], "P2": []}
    summarizer = None
    if all_news_items:
        summarizer = ThemeSummarizer(all_news_items)
        priority_items = summarizer.classify_priority()

    theme_payload = _to_theme_payload(summary_map)
    urgent_alerts = [_strip_markdown_link(get_display_title(x)) for x in priority_items.get("P0", [])]

    return {
        "priority_items": priority_items,
        "theme_payload": theme_payload,
        "urgent_alerts": urgent_alerts,
        "total_count": total_count,
        "all_news_items": all_news_items,
        "summarizer": summarizer,
    }


def _write_summary_post(
    today: str,
    content: str,
    total_count: int,
    counts_str: str,
    briefing_image: Optional[str],
) -> str:
    """Write the summary post file and return the filepath."""
    title = f"일일 뉴스 종합 요약 - {today}"
    slug = "daily-news-summary"
    filename = f"{today}-{slug}.md"
    filepath = os.path.join(POSTS_DIR, filename)

    tags = [
        "일일요약",
        "암호화폐",
        "주식",
        "규제",
        "소셜미디어",
        "보안",
        "정치인거래",
        "월드모니터",
    ]
    escaped_title = title.replace('"', '\\"')

    frontmatter_image = _resolve_frontmatter_image(today, briefing_image)
    image_line = f'\nimage: "{frontmatter_image}"' if frontmatter_image else ""

    safe_tags = [f'"{t}"' for t in tags]
    keywords = ", ".join(tags[:5])
    safe_desc = f"{counts_str}의 뉴스를 종합 분석한 일일 요약입니다.".replace('"', "'")
    image_alt = f"{escaped_title} - 시장 분석 뉴스 요약 이미지"
    frontmatter = f"""---
layout: post
title: "{escaped_title}"
date: {today} 12:00:00 +0900
categories: [market-analysis]
tags: [{", ".join(safe_tags)}]
keywords: "{keywords}"
source: "consolidated"
lang: "ko"{image_line}
description: "{safe_desc}"
excerpt: "{counts_str}의 뉴스를 종합 분석한 일일 요약"
image_alt: "{image_alt}"
---"""

    post_content = frontmatter + "\n\n" + content.strip()

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(post_content)

    logger.info("Created daily summary: %s (total %d news items)", filepath, total_count)
    return filepath


def main():
    """Generate daily news summary with priority-based structure."""
    logger.info("=== Generating daily news summary ===")

    today = datetime.now(get_kst_timezone()).strftime("%Y-%m-%d")

    # Find all posts for today
    pattern = os.path.join(POSTS_DIR, f"{today}-*.md")
    today_posts = sorted(glob.glob(pattern))

    if not today_posts:
        logger.warning("No posts found for today (%s), skipping summary", today)
        return

    # 1. Load and categorize posts
    summary_map, post_links, security_summary, all_summaries = _load_today_posts(today)
    if not summary_map:
        logger.warning("No posts found for today (%s), skipping summary", today)
        return

    # 2. Classify priorities and analyze themes
    analysis = _classify_and_analyze(all_summaries, summary_map)
    priority_items = analysis["priority_items"]
    theme_payload = analysis["theme_payload"]
    urgent_alerts = analysis["urgent_alerts"]
    total_count = analysis["total_count"]
    all_news_items = analysis["all_news_items"]
    summarizer = analysis["summarizer"]

    # 3. Generate briefing image
    briefing_image = None
    try:
        from common.image_generator import generate_news_briefing_card

        briefing_image = generate_news_briefing_card(
            themes=theme_payload,
            date_str=today,
            category="Multi-Asset Daily Briefing",
            total_count=total_count,
            urgent_alerts=[x for x in urgent_alerts if x],
            filename=f"news-briefing-daily-{today}.png",
        )
    except Exception as e:
        logger.warning("Failed to generate daily briefing image: %s", e)

    # 4. Build counts_str (needed by overview and write)
    count_parts = []
    crypto_summary = summary_map.get("crypto")
    stock_summary = summary_map.get("stock")
    regulatory_summary = summary_map.get("regulatory")
    social_summary = summary_map.get("social")
    worldmonitor_summary = summary_map.get("worldmonitor")
    political_summary = summary_map.get("political")
    if crypto_summary and crypto_summary["count"]:
        count_parts.append(f"암호화폐 {crypto_summary['count']}건")
    if stock_summary and stock_summary["count"]:
        count_parts.append(f"주식 {stock_summary['count']}건")
    if security_summary and security_summary["count"]:
        count_parts.append(f"보안 {security_summary['count']}건")
    if regulatory_summary and regulatory_summary["count"]:
        count_parts.append(f"규제 {regulatory_summary['count']}건")
    if social_summary and social_summary["count"]:
        count_parts.append(f"소셜 미디어 {social_summary['count']}건")
    if worldmonitor_summary and worldmonitor_summary["count"]:
        count_parts.append(f"월드모니터 {worldmonitor_summary['count']}건")
    if political_summary and political_summary["count"]:
        count_parts.append(f"정치인 거래 {political_summary['count']}건")
    counts_str = ", ".join(count_parts) if count_parts else "뉴스"

    # 5. Compute sentiment once (used by overview and briefing)
    sentiment = _analyze_sentiment(all_summaries)

    # 6. Build content sections
    content_parts: List[str] = []

    content_parts.extend(
        _build_overview_section(
            total_count,
            priority_items,
            theme_payload,
            summary_map,
            security_summary,
            counts_str,
            sentiment,
        )
    )

    content_parts.extend(
        _build_briefing_section(
            all_summaries,
            all_news_items,
            summary_map,
            theme_payload,
            sentiment,
            today,
            briefing_image,
            priority_items,
            summarizer,
        )
    )

    market_summary = summary_map.get("market")
    content_parts.extend(
        _build_priority_and_category_sections(
            priority_items,
            market_summary,
            security_summary,
            summary_map,
            post_links,
            all_news_items,
        )
    )

    # 7. Write the post
    content = "\n".join(content_parts)
    _write_summary_post(today, content, total_count, counts_str, briefing_image)

    logger.info("=== Daily summary generation complete ===")


if __name__ == "__main__":
    main()
