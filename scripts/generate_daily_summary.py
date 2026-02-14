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

import sys
import os
import re
import glob
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common.config import setup_logging
from common.post_generator import POSTS_DIR
from common.summarizer import ThemeSummarizer

logger = setup_logging("generate_daily_summary")


def read_post_content(filepath: str) -> Dict[str, Any]:
    """Read a Jekyll post and parse frontmatter + content."""
    with open(filepath, "r", encoding="utf-8") as f:
        text = f.read()

    # Parse frontmatter
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {"frontmatter": {}, "content": text, "filepath": filepath}

    frontmatter_text = parts[1].strip()
    content = parts[2].strip()

    frontmatter = {}
    for line in frontmatter_text.split("\n"):
        if ":" in line:
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            frontmatter[key] = value

    return {
        "frontmatter": frontmatter,
        "content": content,
        "filepath": filepath,
    }


def extract_section(content: str, heading: str) -> str:
    """Extract content under a specific ## heading."""
    pattern = rf"## {re.escape(heading)}\s*\n(.*?)(?=\n## |\Z)"
    match = re.search(pattern, content, re.DOTALL)
    return match.group(1).strip() if match else ""


def extract_bullet_points(content: str, heading: str, max_items: int = 5) -> List[str]:
    """Extract bullet points from a section."""
    section = extract_section(content, heading)
    if not section:
        return []

    bullets = []
    for line in section.split("\n"):
        line = line.strip()
        if line.startswith("- "):
            bullets.append(line)
            if len(bullets) >= max_items:
                break
    return bullets


def extract_table_rows(content: str, heading: str, max_rows: int = 10) -> List[str]:
    """Extract table rows (excluding header) from a section."""
    section = extract_section(content, heading)
    if not section:
        return []

    rows = []
    header_passed = 0
    for line in section.split("\n"):
        line = line.strip()
        if line.startswith("|"):
            header_passed += 1
            if header_passed > 2:  # Skip header + separator
                rows.append(line)
                if len(rows) >= max_rows:
                    break
    return rows


def count_news_items(content: str) -> int:
    """Try to extract total news count from content."""
    patterns = [
        r"(\d+)건의 뉴스",
        r"총 뉴스 건수\*?\*?:\s*(\d+)건",
        r"총 수집 건수\*?\*?:\s*(\d+)건",
        r"총 (\d+)건",
        r"(\d+)건이 수집",
    ]
    for pattern in patterns:
        match = re.search(pattern, content)
        if match:
            return int(match.group(1))
    return 0


def summarize_crypto_post(post: Dict[str, Any]) -> Dict[str, Any]:
    """Extract key info from crypto news post."""
    content = post["content"]
    count = count_news_items(content)

    highlights = extract_bullet_points(content, "오늘의 핵심")
    key_summary = extract_bullet_points(content, "핵심 요약")

    themes = []
    dist_section = extract_section(content, "이슈 분포 현황")
    if dist_section:
        for line in dist_section.split("\n"):
            match = re.match(r"(\S+)\s+[█░]+\s+\d+%\s+\((\d+)건\)", line.strip())
            if match:
                themes.append((match.group(1), int(match.group(2))))

    return {
        "type": "crypto",
        "title": post["frontmatter"].get("title", ""),
        "count": count,
        "highlights": highlights,
        "key_summary": key_summary,
        "themes": themes,
        "content": content,
    }


def summarize_stock_post(post: Dict[str, Any]) -> Dict[str, Any]:
    """Extract key info from stock news post."""
    content = post["content"]
    count = count_news_items(content)

    highlights = extract_bullet_points(content, "오늘의 핵심")
    key_summary = extract_bullet_points(content, "핵심 요약")

    market_data = []
    for line in content.split("\n")[:5]:
        if "KOSPI" in line or "KOSDAQ" in line or "USD/KRW" in line:
            market_data.append(line.strip())

    return {
        "type": "stock",
        "title": post["frontmatter"].get("title", ""),
        "count": count,
        "highlights": highlights,
        "key_summary": key_summary,
        "market_data": market_data,
        "content": content,
    }


def summarize_security_post(post: Dict[str, Any]) -> Dict[str, Any]:
    """Extract key info from security post."""
    content = post["content"]
    count = count_news_items(content)
    key_summary = extract_bullet_points(content, "핵심 요약")
    incidents = extract_table_rows(content, "보안 사고 현황", 5)

    return {
        "type": "security",
        "title": post["frontmatter"].get("title", ""),
        "count": count,
        "key_summary": key_summary,
        "incidents": incidents,
        "content": content,
    }


def summarize_regulatory_post(post: Dict[str, Any]) -> Dict[str, Any]:
    """Extract key info from regulatory post."""
    content = post["content"]
    count = count_news_items(content)
    key_summary = extract_bullet_points(content, "핵심 요약")

    return {
        "type": "regulatory",
        "title": post["frontmatter"].get("title", ""),
        "count": count,
        "key_summary": key_summary,
        "content": content,
    }


def summarize_social_post(post: Dict[str, Any]) -> Dict[str, Any]:
    """Extract key info from social media post."""
    content = post["content"]
    count = count_news_items(content)
    highlights = extract_bullet_points(content, "오늘의 핵심")
    key_summary = extract_bullet_points(content, "핵심 요약")

    return {
        "type": "social",
        "title": post["frontmatter"].get("title", ""),
        "count": count,
        "highlights": highlights,
        "key_summary": key_summary,
        "content": content,
    }


def summarize_market_post(post: Dict[str, Any]) -> Dict[str, Any]:
    """Extract key info from market summary post."""
    content = post["content"]
    highlights = extract_bullet_points(content, "오늘의 핵심")
    exec_summary = extract_bullet_points(content, "한눈에 보기")

    # Extract indicator data
    indicator_rows = extract_table_rows(content, "매크로 경제 지표", 10)
    yield_section = extract_section(content, "국채 수익률 스프레드 (2Y-10Y)")
    sector_section = extract_section(content, "S&P 500 섹터 퍼포먼스")

    return {
        "type": "market",
        "title": post["frontmatter"].get("title", ""),
        "highlights": highlights,
        "exec_summary": exec_summary,
        "indicator_rows": indicator_rows,
        "yield_section": yield_section,
        "sector_section": sector_section,
        "content": content,
    }


def summarize_political_post(post: Dict[str, Any]) -> Dict[str, Any]:
    """Extract key info from political trades post."""
    content = post["content"]
    count = count_news_items(content)
    key_summary = extract_bullet_points(content, "핵심 요약")
    highlights = extract_bullet_points(content, "정책 영향 분석", 3)

    return {
        "type": "political",
        "title": post["frontmatter"].get("title", ""),
        "count": count,
        "key_summary": key_summary,
        "highlights": highlights,
        "content": content,
    }


def get_post_url(filepath: str, today: str, category: str = "") -> str:
    """Generate relative URL for a post following Jekyll permalink structure."""
    filename = os.path.basename(filepath)
    slug = filename.replace(f"{today}-", "").replace(".md", "")
    date_path = today.replace("-", "/")
    if category:
        return f"/{category}/{date_path}/{slug}/"
    return f"/{date_path}/{slug}/"


def _collect_all_news_items(summaries: List[Optional[Dict]]) -> List[Dict[str, Any]]:
    """Collect all news item titles+descriptions from post contents for priority classification."""
    items = []
    for s in summaries:
        if not s or not s.get("content"):
            continue
        content = s["content"]
        # Extract titles from markdown table rows and bullet points
        for line in content.split("\n"):
            line = line.strip()
            if line.startswith("| ") and "**" in line:
                # Table row with bold title
                match = re.search(r"\*\*(.+?)\*\*", line)
                if match:
                    items.append({
                        "title": match.group(1),
                        "description": line,
                        "source": s.get("type", ""),
                    })
            elif line.startswith("- ") and len(line) > 10:
                items.append({
                    "title": line[2:],
                    "description": line,
                    "source": s.get("type", ""),
                })
    return items


def main():
    """Generate daily news summary with priority-based structure."""
    logger.info("=== Generating daily news summary ===")

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Find all posts for today
    pattern = os.path.join(POSTS_DIR, f"{today}-*.md")
    today_posts = sorted(glob.glob(pattern))

    if not today_posts:
        logger.warning("No posts found for today (%s), skipping summary", today)
        return

    logger.info("Found %d posts for %s", len(today_posts), today)

    # Read and categorize posts
    crypto_summary = None
    stock_summary = None
    security_summary = None
    regulatory_summary = None
    social_summary = None
    market_summary = None
    political_summary = None

    post_links = []

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
            social_summary["url"] = get_post_url(filepath, today, "crypto-news")
            post_links.append(("소셜 미디어", social_summary["count"], social_summary["url"]))
        elif "political-trades-report" in slug:
            political_summary = summarize_political_post(post)
            political_summary["url"] = get_post_url(filepath, today, "political-trades")
            post_links.append(("정치인 거래", political_summary["count"], political_summary["url"]))
        elif "market-report" in slug:
            market_summary = summarize_market_post(post)
            market_summary["url"] = get_post_url(filepath, today, "market-analysis")
            post_links.append(("시장 종합 리포트", 0, market_summary["url"]))

    # Calculate total count
    all_summaries = [crypto_summary, stock_summary, security_summary,
                     regulatory_summary, social_summary, political_summary]
    total_count = sum(
        s["count"] for s in all_summaries
        if s and s.get("count")
    )

    # Priority classification
    all_news_items = _collect_all_news_items(all_summaries)
    priority_items = {"P0": [], "P1": [], "P2": []}
    if all_news_items:
        summarizer = ThemeSummarizer(all_news_items)
        priority_items = summarizer.classify_priority()

    # Build summary content
    content_parts = []

    # Opening with counts
    count_parts = []
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
    if political_summary and political_summary["count"]:
        count_parts.append(f"정치인 거래 {political_summary['count']}건")

    counts_str = ", ".join(count_parts) if count_parts else "뉴스"
    content_parts.append(f"> {counts_str}의 뉴스를 종합 분석한 일일 요약입니다.\n")

    # ═══════════════════════════════════════
    # 1. URGENT ALERTS (P0)
    # ═══════════════════════════════════════
    if priority_items.get("P0"):
        content_parts.append("## 긴급 알림\n")
        content_parts.append("> 즉시 확인이 필요한 긴급 뉴스입니다.\n")
        for item in priority_items["P0"][:5]:
            title = item.get("title", "")
            content_parts.append(f"- **{title}**")
        content_parts.append("")

    # ═══════════════════════════════════════
    # 2. MARKET OVERVIEW
    # ═══════════════════════════════════════
    if market_summary:
        content_parts.append("## 시장 개요\n")
        if market_summary.get("highlights"):
            for h in market_summary["highlights"]:
                content_parts.append(h)
        elif market_summary.get("exec_summary"):
            for h in market_summary["exec_summary"]:
                content_parts.append(h)
        content_parts.append("")

    # ═══════════════════════════════════════
    # 3. INDICATOR DASHBOARD
    # ═══════════════════════════════════════
    indicator_parts = []

    # Macro indicators from market report
    if market_summary and market_summary.get("indicator_rows"):
        indicator_parts.append("| 지표 | 현재 값 | 변동 |")
        indicator_parts.append("|------|---------|------|")
        for row in market_summary["indicator_rows"]:
            indicator_parts.append(row)

    # Yield spread
    if market_summary and market_summary.get("yield_section"):
        if indicator_parts:
            indicator_parts.append("")
        indicator_parts.append("**국채 수익률 스프레드:**")
        # Extract just the key info
        for line in market_summary["yield_section"].split("\n"):
            line = line.strip()
            if line.startswith("|") and "스프레드" in line:
                indicator_parts.append(line)
            elif line.startswith(">"):
                indicator_parts.append(line)

    if indicator_parts:
        content_parts.append("## 지표 대시보드\n")
        content_parts.extend(indicator_parts)
        content_parts.append("")

    # ═══════════════════════════════════════
    # 4. POLITICAL WATCH
    # ═══════════════════════════════════════
    if political_summary:
        content_parts.append("---\n")
        content_parts.append("## 정치인 워치\n")
        if political_summary.get("key_summary"):
            for h in political_summary["key_summary"][:5]:
                content_parts.append(h)
        if political_summary.get("highlights"):
            content_parts.append("")
            for h in political_summary["highlights"][:3]:
                content_parts.append(h)
        content_parts.append(f"\n[상세 보기]({political_summary.get('url', '#')})\n")

    # ═══════════════════════════════════════
    # 5. IMPORTANT NEWS (P1)
    # ═══════════════════════════════════════
    if priority_items.get("P1"):
        content_parts.append("---\n")
        content_parts.append("## 중요 뉴스\n")
        content_parts.append("> 규제, ETF, 실적 등 주요 뉴스입니다.\n")
        for item in priority_items["P1"][:7]:
            title = item.get("title", "")
            content_parts.append(f"- {title}")
        content_parts.append("")

    # ═══════════════════════════════════════
    # 6. CATEGORY SUMMARIES
    # ═══════════════════════════════════════
    content_parts.append("---\n")
    content_parts.append("## 카테고리별 요약\n")

    # Crypto section
    if crypto_summary:
        content_parts.append(f"### 암호화폐 뉴스 ({crypto_summary['count']}건)\n")
        if crypto_summary.get("themes"):
            themes_str = ", ".join(f"**{t[0]}**({t[1]}건)" for t in crypto_summary["themes"][:4])
            content_parts.append(f"주요 테마: {themes_str}\n")
        if crypto_summary.get("highlights"):
            for h in crypto_summary["highlights"][:3]:
                content_parts.append(h)
        elif crypto_summary.get("key_summary"):
            for h in crypto_summary["key_summary"][:3]:
                content_parts.append(h)
        content_parts.append(f"\n[상세 보기]({crypto_summary.get('url', '#')})\n")

    # Stock section
    if stock_summary:
        content_parts.append(f"### 주식 시장 뉴스 ({stock_summary['count']}건)\n")
        if stock_summary.get("highlights"):
            for h in stock_summary["highlights"][:3]:
                content_parts.append(h)
        elif stock_summary.get("key_summary"):
            for h in stock_summary["key_summary"][:3]:
                content_parts.append(h)
        content_parts.append(f"\n[상세 보기]({stock_summary.get('url', '#')})\n")

    # Regulatory section
    if regulatory_summary:
        content_parts.append(f"### 규제 동향 ({regulatory_summary['count']}건)\n")
        if regulatory_summary.get("key_summary"):
            for h in regulatory_summary["key_summary"][:3]:
                content_parts.append(h)
        content_parts.append(f"\n[상세 보기]({regulatory_summary.get('url', '#')})\n")

    # Security section
    if security_summary:
        content_parts.append(f"### 보안 리포트 ({security_summary['count']}건)\n")
        if security_summary.get("key_summary"):
            for h in security_summary["key_summary"][:3]:
                content_parts.append(h)
        if security_summary.get("incidents"):
            content_parts.append("\n| 프로젝트 | 피해 규모 | 공격 유형 |")
            content_parts.append("|----------|----------|----------|")
            for row in security_summary["incidents"][:3]:
                content_parts.append(row)
        content_parts.append(f"\n[상세 보기]({security_summary.get('url', '#')})\n")

    # Social section
    if social_summary:
        content_parts.append(f"### 소셜 미디어 동향 ({social_summary['count']}건)\n")
        if social_summary.get("highlights"):
            for h in social_summary["highlights"][:3]:
                content_parts.append(h)
        elif social_summary.get("key_summary"):
            for h in social_summary["key_summary"][:3]:
                content_parts.append(h)
        content_parts.append(f"\n[상세 보기]({social_summary.get('url', '#')})\n")

    # ═══════════════════════════════════════
    # 7. NOTABLE NEWS (P2)
    # ═══════════════════════════════════════
    if priority_items.get("P2"):
        content_parts.append("---\n")
        content_parts.append("## 주목할 소식\n")
        for item in priority_items["P2"][:5]:
            title = item.get("title", "")
            content_parts.append(f"- {title}")
        content_parts.append("")

    # ═══════════════════════════════════════
    # 8. REPORT LINKS
    # ═══════════════════════════════════════
    content_parts.append("---\n")
    content_parts.append("## 상세 리포트 링크\n")
    content_parts.append("| 리포트 | 수집 건수 | 링크 |")
    content_parts.append("|:---|:---:|:---|")
    for name, count, url in post_links:
        count_str = f"{count}건" if count else "-"
        content_parts.append(f"| {name} | {count_str} | [바로가기]({url}) |")

    content_parts.append("\n---\n")
    content_parts.append("*본 요약은 자동 수집된 뉴스 데이터를 기반으로 작성되었으며, 투자 조언이 아닙니다.*")

    content = "\n".join(content_parts)

    # Create post with pin: true
    title = f"일일 뉴스 종합 요약 - {today}"
    slug = "daily-news-summary"
    filename = f"{today}-{slug}.md"
    filepath = os.path.join(POSTS_DIR, filename)

    tags = ["일일요약", "암호화폐", "주식", "규제", "소셜미디어", "보안", "정치인거래"]
    escaped_title = title.replace('"', '\\"')

    frontmatter = f"""---
title: "{escaped_title}"
date: {today} 12:00:00 +0900
categories: [market-analysis]
tags: [{', '.join(tags)}]
source: "consolidated"
lang: "ko"
pin: true
excerpt: "{counts_str}의 뉴스를 종합 분석한 일일 요약"
---"""

    post_content = frontmatter + "\n\n" + content.strip()

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(post_content)

    logger.info("Created daily summary: %s (total %d news items)", filepath, total_count)
    logger.info("=== Daily summary generation complete ===")


if __name__ == "__main__":
    main()
