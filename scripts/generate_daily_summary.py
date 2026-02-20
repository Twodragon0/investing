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
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common.config import get_kst_timezone, setup_logging
from common.markdown_utils import markdown_table
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
        r"뉴스\s*(\d+)건",
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


def _extract_highlights(content: str) -> List[str]:
    """Extract highlight info from post opening and alert-info HTML."""
    highlights = []
    # Try opening paragraph (first non-empty line after frontmatter)
    for line in content.split("\n")[:5]:
        line = line.strip()
        if line.startswith("**") and "건" in line:
            highlights.append(f"- {line}")
            break
    # Try old-style sections as fallback
    for section in ["오늘의 핵심", "핵심 요약"]:
        bullets = extract_bullet_points(content, section)
        if bullets:
            highlights.extend(bullets)
            break
    # Try alert-info content
    match = re.search(
        r'class="alert-box alert-info"[^>]*>.*?<strong>(.*?)</strong>', content
    )
    if match and not highlights:
        highlights.append(f"- {match.group(1)}")
    return highlights


def summarize_crypto_post(post: Dict[str, Any]) -> Dict[str, Any]:
    """Extract key info from crypto news post."""
    content = post["content"]
    count = count_news_items(content)
    highlights = _extract_highlights(content)

    # Extract themes from HTML progress bars or ASCII chart
    themes = []
    for match in re.finditer(
        r'class="theme-label">.\s*(\S+)</span>.*?(\d+)건', content
    ):
        themes.append((match.group(1), int(match.group(2))))
    if not themes:
        dist_section = extract_section(content, "이슈 분포 현황")
        if dist_section:
            for line in dist_section.split("\n"):
                m = re.match(r"(\S+)\s+[█░]+\s+\d+%\s+\((\d+)건\)", line.strip())
                if m:
                    themes.append((m.group(1), int(m.group(2))))

    return {
        "type": "crypto",
        "title": post["frontmatter"].get("title", ""),
        "count": count,
        "highlights": highlights,
        "key_summary": highlights,
        "themes": themes,
        "content": content,
    }


def summarize_stock_post(post: Dict[str, Any]) -> Dict[str, Any]:
    """Extract key info from stock news post."""
    content = post["content"]
    count = count_news_items(content)
    highlights = _extract_highlights(content)

    market_data = []
    for line in content.split("\n")[:5]:
        if "KOSPI" in line or "KOSDAQ" in line or "USD/KRW" in line:
            market_data.append(line.strip())

    return {
        "type": "stock",
        "title": post["frontmatter"].get("title", ""),
        "count": count,
        "highlights": highlights,
        "key_summary": highlights,
        "market_data": market_data,
        "content": content,
    }


def summarize_security_post(post: Dict[str, Any]) -> Dict[str, Any]:
    """Extract key info from security post."""
    content = post["content"]
    count = count_news_items(content)
    key_summary = _extract_highlights(content)
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
    key_summary = _extract_highlights(content)

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
    highlights = _extract_highlights(content)

    return {
        "type": "social",
        "title": post["frontmatter"].get("title", ""),
        "count": count,
        "highlights": highlights,
        "key_summary": highlights,
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


def summarize_worldmonitor_post(post: Dict[str, Any]) -> Dict[str, Any]:
    content = post["content"]
    count = count_news_items(content)
    key_summary = extract_bullet_points(content, "핵심 요약", 4)
    issues = extract_table_rows(content, "주요 이슈", 6)

    if not count:
        for line in content.split("\n"):
            m = re.search(r"수집 건수:\s*\*\*(\d+)건\*\*", line)
            if m:
                count = int(m.group(1))
                break

    return {
        "type": "worldmonitor",
        "title": post["frontmatter"].get("title", ""),
        "count": count,
        "key_summary": key_summary,
        "issues": issues,
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
    seen_titles = set()
    for s in summaries:
        if not s or not s.get("content"):
            continue
        content = s["content"]
        in_card_section = False
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
                    # Deduplicate by normalized title
                    norm = re.sub(r"[^a-z가-힣0-9]", "", title.lower())
                    if norm not in seen_titles:
                        seen_titles.add(norm)
                        items.append(
                            {
                                "title": f"[{title}]({link})",
                                "description": title,
                                "source": s.get("type", ""),
                            }
                        )
            # Also extract description lines right after card items
            if (
                in_card_section
                and not line.startswith("**")
                and not line.startswith(">")
                and not line.startswith("`")
                and not line.startswith("#")
                and not line.startswith("|")
                and line
                and not line.startswith("---")
            ):
                # This might be a description line, skip it for item collection
                pass
            # Stop card parsing at next major section
            if line.startswith("## ") and in_card_section:
                in_card_section = False
    return items


def _cross_asset_topics() -> Dict[str, List[str]]:
    return {
        "금리/유동성": ["금리", "연준", "fed", "fomc", "유동성", "국채", "yield"],
        "환율/달러": ["환율", "usd/krw", "달러", "dxy"],
        "정책/규제": [
            "규제",
            "sec",
            "etf",
            "법안",
            "정책",
            "행정명령",
            "tariff",
            "관세",
        ],
        "리스크 이벤트": ["해킹", "exploit", "파산", "청산", "liquidation", "보안사고"],
        "수급/심리": ["고래", "whale", "수급", "공포", "탐욕", "sentiment", "social"],
        "실적/지표": ["실적", "cpi", "pce", "고용", "매출", "earnings"],
    }


def _topic_hits(summary: Optional[Dict[str, Any]]) -> Dict[str, int]:
    if not summary:
        return {}
    text = "\n".join(
        [
            summary.get("title", ""),
            summary.get("content", ""),
            " ".join(summary.get("highlights", []) or []),
            " ".join(summary.get("key_summary", []) or []),
        ]
    ).lower()
    hits: Dict[str, int] = {}
    for topic, keywords in _cross_asset_topics().items():
        score = 0
        for kw in keywords:
            score += text.count(kw.lower())
        hits[topic] = score
    return hits


def _relation_rows(
    summaries: Dict[str, Optional[Dict[str, Any]]],
) -> List[Tuple[str, str, int, str]]:
    rows: List[Tuple[str, str, int, str]] = []
    pairs = [
        ("암호화폐", "주식", "crypto", "stock"),
        ("암호화폐", "정치인 거래", "crypto", "political"),
        ("주식", "정치인 거래", "stock", "political"),
        ("암호화폐", "규제", "crypto", "regulatory"),
        ("주식", "규제", "stock", "regulatory"),
        ("암호화폐", "소셜", "crypto", "social"),
        ("월드모니터", "암호화폐", "worldmonitor", "crypto"),
        ("월드모니터", "주식", "worldmonitor", "stock"),
    ]
    topic_keys = list(_cross_asset_topics().keys())
    hit_maps = {k: _topic_hits(v) for k, v in summaries.items()}

    for left_name, right_name, left_key, right_key in pairs:
        left = hit_maps.get(left_key, {})
        right = hit_maps.get(right_key, {})
        if not left or not right:
            continue
        shared_topics: List[Tuple[str, int]] = []
        for t in topic_keys:
            if left.get(t, 0) > 0 and right.get(t, 0) > 0:
                shared_topics.append((t, min(left[t], right[t])))
        shared_topics.sort(key=lambda x: x[1], reverse=True)
        if not shared_topics:
            rows.append((left_name, right_name, 0, "낮음"))
            continue
        score = sum(v for _, v in shared_topics[:3])
        top_topics = ", ".join(t for t, _ in shared_topics[:2])
        if score >= 8:
            level = "높음"
        elif score >= 4:
            level = "중간"
        else:
            level = "낮음"
        rows.append((left_name, right_name, score, f"{level} ({top_topics})"))
    return rows


def _coverage_warnings(summaries: Dict[str, Optional[Dict[str, Any]]]) -> List[str]:
    warnings = []
    if not summaries.get("crypto"):
        warnings.append(
            "- 암호화폐 일일 리포트가 없어 코인-주식 연계 분석 정밀도가 낮습니다."
        )
    if not summaries.get("stock"):
        warnings.append("- 주식 일일 리포트가 없어 교차자산 수급 비교가 제한됩니다.")
    if not summaries.get("market"):
        warnings.append(
            "- 시장 종합 리포트가 없어 매크로(금리/환율) 연결 해석이 제한됩니다."
        )
    if not summaries.get("worldmonitor"):
        warnings.append(
            "- 월드모니터 브리핑이 없어 글로벌 지정학/에너지 리스크 연결 분석이 제한됩니다."
        )
    if not summaries.get("political") and not summaries.get("regulatory"):
        warnings.append(
            "- 정책/규제 데이터가 부족해 이벤트 기반 리스크 점검이 약합니다."
        )
    return warnings


def _strip_markdown_link(text: str) -> str:
    text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)
    text = text.replace("**", "")
    return text.strip()


def _clean_bullet_text(text: str) -> str:
    text = _strip_markdown_link(text)
    if text.startswith("- "):
        text = text[2:]
    return text.strip()


def _to_theme_payload(
    summaries: Dict[str, Optional[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    payload = []
    topic_def = _cross_asset_topics()
    hit_totals = {k: 0 for k in topic_def.keys()}
    for summary in summaries.values():
        hits = _topic_hits(summary)
        for k, v in hits.items():
            hit_totals[k] += v

    emojis = {
        "금리/유동성": "🏦",
        "환율/달러": "💵",
        "정책/규제": "📜",
        "리스크 이벤트": "🚨",
        "수급/심리": "🧭",
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


def _render_generated_image(filename: str, alt: str) -> Optional[str]:
    image_path = os.path.join(
        POSTS_DIR, "..", "assets", "images", "generated", filename
    )
    if not os.path.exists(image_path):
        return None
    return f"![{alt}]({{{{ '/assets/images/generated/{filename}' | relative_url }}}})"


def _build_snapshot_table(
    crypto_summary: Optional[Dict[str, Any]],
    stock_summary: Optional[Dict[str, Any]],
    worldmonitor_summary: Optional[Dict[str, Any]],
    regulatory_summary: Optional[Dict[str, Any]],
    social_summary: Optional[Dict[str, Any]],
    political_summary: Optional[Dict[str, Any]],
) -> List[str]:
    rows = []

    def top_signal(summary: Optional[Dict[str, Any]]) -> str:
        if not summary:
            return "데이터 없음"
        if summary.get("themes"):
            name, cnt = summary["themes"][0]
            return f"{name} {cnt}건"
        if summary.get("market_data"):
            return _clean_bullet_text(summary["market_data"][0])[:80]
        hl = summary.get("highlights") or summary.get("key_summary") or []
        if hl:
            return _clean_bullet_text(hl[0])[:80]
        return "신호 추출 실패"

    dataset = [
        ("암호화폐", crypto_summary),
        ("주식", stock_summary),
        ("월드모니터", worldmonitor_summary),
        ("규제", regulatory_summary),
        ("소셜", social_summary),
        ("정치인 거래", political_summary),
    ]
    for name, summary in dataset:
        count = summary.get("count", 0) if summary else 0
        rows.append([name, count, top_signal(summary)])
    return [
        markdown_table(
            ["영역", "수집 건수", "핵심 신호"],
            rows,
            aligns=["left", "right", "left"],
        )
    ]


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

    logger.info("Found %d posts for %s", len(today_posts), today)

    # Read and categorize posts
    crypto_summary = None
    stock_summary = None
    security_summary = None
    regulatory_summary = None
    social_summary = None
    market_summary = None
    worldmonitor_summary = None
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
            post_links.append(
                ("암호화폐 뉴스", crypto_summary["count"], crypto_summary["url"])
            )
        elif "stock-news-digest" in slug:
            stock_summary = summarize_stock_post(post)
            stock_summary["url"] = get_post_url(filepath, today, "stock-news")
            post_links.append(
                ("주식 시장 뉴스", stock_summary["count"], stock_summary["url"])
            )
        elif "security-report" in slug:
            security_summary = summarize_security_post(post)
            security_summary["url"] = get_post_url(filepath, today, "security-alerts")
            post_links.append(
                ("보안 리포트", security_summary["count"], security_summary["url"])
            )
        elif "regulatory-report" in slug:
            regulatory_summary = summarize_regulatory_post(post)
            regulatory_summary["url"] = get_post_url(filepath, today, "regulatory-news")
            post_links.append(
                ("규제 동향", regulatory_summary["count"], regulatory_summary["url"])
            )
        elif "social-media-digest" in slug:
            social_summary = summarize_social_post(post)
            social_summary["url"] = get_post_url(filepath, today, "crypto-news")
            post_links.append(
                ("소셜 미디어", social_summary["count"], social_summary["url"])
            )
        elif "political-trades-report" in slug:
            political_summary = summarize_political_post(post)
            political_summary["url"] = get_post_url(filepath, today, "political-trades")
            post_links.append(
                ("정치인 거래", political_summary["count"], political_summary["url"])
            )
        elif "market-report" in slug:
            market_summary = summarize_market_post(post)
            market_summary["url"] = get_post_url(filepath, today, "market-analysis")
            post_links.append(("시장 종합 리포트", 0, market_summary["url"]))
        elif "worldmonitor-briefing" in slug:
            worldmonitor_summary = summarize_worldmonitor_post(post)
            worldmonitor_summary["url"] = get_post_url(
                filepath, today, "market-analysis"
            )
            post_links.append(
                (
                    "월드모니터 브리핑",
                    worldmonitor_summary["count"],
                    worldmonitor_summary["url"],
                )
            )

    # Calculate total count
    all_summaries = [
        crypto_summary,
        stock_summary,
        security_summary,
        regulatory_summary,
        social_summary,
        worldmonitor_summary,
        political_summary,
    ]
    total_count = sum(s["count"] for s in all_summaries if s and s.get("count"))

    # Priority classification
    all_news_items = _collect_all_news_items(all_summaries)
    priority_items = {"P0": [], "P1": [], "P2": []}
    if all_news_items:
        summarizer = ThemeSummarizer(all_news_items)
        priority_items = summarizer.classify_priority()

    summary_map = {
        "crypto": crypto_summary,
        "stock": stock_summary,
        "market": market_summary,
        "regulatory": regulatory_summary,
        "social": social_summary,
        "worldmonitor": worldmonitor_summary,
        "political": political_summary,
    }

    theme_payload = _to_theme_payload(summary_map)
    urgent_alerts = [
        _strip_markdown_link(x.get("title", "")) for x in priority_items.get("P0", [])
    ]

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
    if worldmonitor_summary and worldmonitor_summary["count"]:
        count_parts.append(f"월드모니터 {worldmonitor_summary['count']}건")
    if political_summary and political_summary["count"]:
        count_parts.append(f"정치인 거래 {political_summary['count']}건")

    counts_str = ", ".join(count_parts) if count_parts else "뉴스"
    content_parts.append(f"> {counts_str}의 뉴스를 종합 분석한 일일 요약입니다.\n")

    content_parts.append(
        '<div class="alert-box alert-info"><strong>한눈에 보는 시장 상황</strong><ul>'
    )
    content_parts.append(f"<li>총 수집: <strong>{total_count}건</strong></li>")
    content_parts.append(
        f"<li>긴급 알림(P0): <strong>{len(priority_items.get('P0', []))}건</strong></li>"
    )
    content_parts.append(
        f"<li>중요 뉴스(P1): <strong>{len(priority_items.get('P1', []))}건</strong></li>"
    )
    content_parts.append("</ul></div>\n")

    content_parts.append("## 종합 대시보드\n")
    content_parts.extend(
        _build_snapshot_table(
            crypto_summary,
            stock_summary,
            worldmonitor_summary,
            regulatory_summary,
            social_summary,
            political_summary,
        )
    )
    content_parts.append("")

    if briefing_image:
        content_parts.append(f"![multi-asset-briefing]({briefing_image})\n")
    fallback_briefing = _render_generated_image(
        f"news-briefing-daily-{today}.png", "multi-asset-briefing"
    )
    legacy_briefing = _render_generated_image(
        f"news-briefing-{today}.png", "multi-asset-briefing"
    )
    if not briefing_image and fallback_briefing:
        content_parts.append(fallback_briefing + "\n")
    elif not briefing_image and legacy_briefing:
        content_parts.append(legacy_briefing + "\n")

    indicator_img = _render_generated_image(
        f"indicator-dashboard-{today}.png", "indicator-dashboard"
    )
    if indicator_img:
        content_parts.append(indicator_img + "\n")

    heatmap_img = _render_generated_image(
        f"market-heatmap-{today}.png", "market-heatmap"
    )
    if heatmap_img:
        content_parts.append(heatmap_img + "\n")

    # Executive briefing: 3-5 line summary from each category
    briefing_lines = []
    for s in all_summaries:
        if not s or not s.get("highlights"):
            continue
        # Pick the most informative highlight
        for h in s["highlights"][:1]:
            line = h.strip()
            if line.startswith("- "):
                line = line[2:]
            if len(line) > 15:
                briefing_lines.append(f"> - {line}")
    if briefing_lines:
        content_parts.append("## 핵심 브리핑\n")
        content_parts.extend(briefing_lines)
        content_parts.append("")

    content_parts.append("## 뉴스 내용 기반 핵심 요약\n")
    if crypto_summary:
        crypto_themes = ", ".join(
            f"{name}({cnt})" for name, cnt in (crypto_summary.get("themes") or [])[:3]
        )
        if crypto_themes:
            content_parts.append(
                f"- **암호화폐:** {crypto_summary.get('count', 0)}건. 핵심 테마는 {crypto_themes}이며 변동성 확대 헤드라인이 우세합니다."
            )
    if stock_summary:
        stock_line = ""
        if stock_summary.get("market_data"):
            stock_line = _clean_bullet_text(stock_summary["market_data"][0])
        content_parts.append(
            f"- **주식:** {stock_summary.get('count', 0)}건. {stock_line if stock_line else '글로벌/국내 혼조 신호가 공존합니다.'}"
        )
    if regulatory_summary:
        content_parts.append(
            f"- **규제:** {regulatory_summary.get('count', 0)}건. 정책 공시/감독 이슈 비중이 높아 업권별 이벤트 리스크 관리가 필요합니다."
        )
    if social_summary:
        content_parts.append(
            f"- **소셜:** {social_summary.get('count', 0)}건. 텔레그램·정치/거시 키워드 확산이 단기 심리 변동을 키우고 있습니다."
        )
    if worldmonitor_summary:
        content_parts.append(
            f"- **월드모니터:** {worldmonitor_summary.get('count', 0)}건. 지정학/안보 이슈가 에너지·안전자산 민감도를 높이고 있습니다."
        )
    if priority_items.get("P0") or priority_items.get("P1"):
        content_parts.append(
            f"- **우선순위:** P0 {len(priority_items.get('P0', []))}건, P1 {len(priority_items.get('P1', []))}건 중심으로 장중 대응 우선순위를 조정합니다."
        )
    content_parts.append("")

    if theme_payload:
        content_parts.append("## 테마 스냅샷\n")
        theme_rows = []
        for item in theme_payload:
            keywords = ", ".join(item.get("keywords", []))
            theme_rows.append(
                [
                    f"{item.get('emoji', '•')} {item.get('name', '')}",
                    item.get("count", 0),
                    keywords if keywords else "-",
                ]
            )
        content_parts.append(
            markdown_table(
                ["테마", "신호 강도", "대표 키워드"],
                theme_rows,
                aligns=["left", "right", "left"],
            )
        )
        content_parts.append("")
        content_parts.append("**리스크/기회 메모**")
        content_parts.append(
            "- 상위 테마에 집중되는 구간에서는 헤드라인 변동성이 확대될 수 있습니다."
        )
        content_parts.append(
            "- 테마별 키워드가 규제/정책과 겹치면 이벤트 드리븐 리스크 점검이 우선입니다."
        )
        content_parts.append("")

    # ═══════════════════════════════════════
    # 1. URGENT ALERTS (P0)
    # ═══════════════════════════════════════
    if priority_items.get("P0"):
        content_parts.append("## 긴급 알림\n")
        content_parts.append("> 즉시 확인이 필요한 긴급 뉴스입니다.\n")
        seen_p0 = set()
        for item in priority_items["P0"][:5]:
            title = item.get("title", "")
            norm = re.sub(r"[^a-z가-힣0-9]", "", item.get("description", title).lower())
            if norm in seen_p0:
                continue
            seen_p0.add(norm)
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
    indicator_rows: List[List[str]] = []

    # Macro indicators from market report
    if market_summary and market_summary.get("indicator_rows"):
        for row in market_summary["indicator_rows"]:
            parts = [p.strip() for p in row.split("|") if p.strip()]
            if len(parts) >= 3:
                indicator_rows.append(parts[:3])

    if indicator_rows:
        indicator_parts.append(
            markdown_table(["지표", "현재 값", "변동"], indicator_rows)
        )

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

    relation_rows = _relation_rows(summary_map)
    coverage_notes = _coverage_warnings(summary_map)

    if relation_rows or coverage_notes:
        content_parts.append("## 교차자산 연관성 체크\n")
        content_parts.append(
            "> 뉴스, 주식, 코인, 정치/규제 이벤트를 연결해 당일 리스크/기회 신호를 점검합니다.\n"
        )

        if relation_rows:
            corr_rows = []
            for left, right, score, note in relation_rows:
                corr_rows.append([f"{left} ↔ {right}", score, note])
            content_parts.append(
                markdown_table(
                    ["비교 구간", "연관 점수", "진단"],
                    corr_rows,
                    aligns=["left", "right", "left"],
                )
            )
            content_parts.append("")

        if coverage_notes:
            content_parts.append("**데이터 커버리지 경고**")
            content_parts.extend(coverage_notes)
            content_parts.append("")

        content_parts.append("**운영 체크리스트**")
        content_parts.append(
            "- 연관 점수 '높음' 구간은 장중 변동성 확대 가능성으로 우선 모니터링"
        )
        content_parts.append(
            "- 정책/규제 + 정치인 거래가 동시 급증하면 포지션 규모와 레버리지 보수적으로 조정"
        )
        content_parts.append(
            "- 코인/주식 모두 수급·심리 키워드가 증가하면 단기 과열/과매도 반전 가능성 점검"
        )
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
        seen_p1 = set()
        for item in priority_items["P1"][:7]:
            title = item.get("title", "")
            norm = re.sub(r"[^a-z가-힣0-9]", "", item.get("description", title).lower())
            if norm in seen_p1:
                continue
            seen_p1.add(norm)
            content_parts.append(f"- {title}")
        content_parts.append("")

    # ═══════════════════════════════════════
    # 6. CATEGORY SUMMARIES
    # ═══════════════════════════════════════
    content_parts.append("---\n")
    content_parts.append("## 카테고리별 요약\n")

    # Crypto section with description highlights
    if crypto_summary:
        content_parts.append(f"### 암호화폐 뉴스 ({crypto_summary['count']}건)\n")
        if crypto_summary.get("themes"):
            themes_str = ", ".join(
                f"**{t[0]}**({t[1]}건)" for t in crypto_summary["themes"][:4]
            )
            content_parts.append(f"주요 테마: {themes_str}\n")
        if crypto_summary.get("highlights"):
            for h in crypto_summary["highlights"][:4]:
                content_parts.append(h)
        elif crypto_summary.get("key_summary"):
            for h in crypto_summary["key_summary"][:4]:
                content_parts.append(h)
        content_parts.append(f"\n[상세 보기]({crypto_summary.get('url', '#')})\n")

    # Stock section with description highlights
    if stock_summary:
        content_parts.append(f"### 주식 시장 뉴스 ({stock_summary['count']}건)\n")
        seen_stock = set()
        if stock_summary.get("market_data"):
            for md in stock_summary["market_data"][:3]:
                cleaned = _clean_bullet_text(md)
                if cleaned and cleaned not in seen_stock:
                    content_parts.append(f"- {cleaned}")
                    seen_stock.add(cleaned)
            content_parts.append("")
        if stock_summary.get("highlights"):
            for h in stock_summary["highlights"][:4]:
                cleaned = _clean_bullet_text(h)
                if cleaned and cleaned not in seen_stock:
                    content_parts.append(f"- {cleaned}")
                    seen_stock.add(cleaned)
        elif stock_summary.get("key_summary"):
            for h in stock_summary["key_summary"][:4]:
                cleaned = _clean_bullet_text(h)
                if cleaned and cleaned not in seen_stock:
                    content_parts.append(f"- {cleaned}")
                    seen_stock.add(cleaned)
        content_parts.append(f"\n[상세 보기]({stock_summary.get('url', '#')})\n")

    # Regulatory section
    if regulatory_summary:
        content_parts.append(f"### 규제 동향 ({regulatory_summary['count']}건)\n")
        if regulatory_summary.get("key_summary"):
            for h in regulatory_summary["key_summary"][:3]:
                content_parts.append(h)
        content_parts.append(f"\n[상세 보기]({regulatory_summary.get('url', '#')})\n")

    if worldmonitor_summary:
        content_parts.append(
            f"### 월드모니터 브리핑 ({worldmonitor_summary['count']}건)\n"
        )
        if worldmonitor_summary.get("key_summary"):
            for h in worldmonitor_summary["key_summary"][:3]:
                content_parts.append(h)
        if worldmonitor_summary.get("issues"):
            world_rows = []
            for row in worldmonitor_summary["issues"][:3]:
                parts = [p.strip() for p in row.split("|") if p.strip()]
                if len(parts) >= 5:
                    world_rows.append([parts[1], parts[4]])
                elif len(parts) >= 3:
                    world_rows.append([parts[1], parts[2]])
            if world_rows:
                content_parts.append("")
                content_parts.append(markdown_table(["제목", "출처"], world_rows))
        content_parts.append(f"\n[상세 보기]({worldmonitor_summary.get('url', '#')})\n")

    # Security section
    if security_summary:
        content_parts.append(f"### 보안 리포트 ({security_summary['count']}건)\n")
        if security_summary.get("key_summary"):
            for h in security_summary["key_summary"][:3]:
                content_parts.append(h)
        if security_summary.get("incidents"):
            incident_rows = []
            for row in security_summary["incidents"][:3]:
                parts = [p.strip() for p in row.split("|") if p.strip()]
                if len(parts) >= 3:
                    incident_rows.append(parts[:3])
            if incident_rows:
                content_parts.append("")
                content_parts.append(
                    markdown_table(
                        ["프로젝트", "피해 규모", "공격 유형"], incident_rows
                    )
                )
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
        seen_p2 = set()
        for item in priority_items["P2"][:5]:
            title = item.get("title", "")
            norm = re.sub(r"[^a-z가-힣0-9]", "", item.get("description", title).lower())
            if norm in seen_p2:
                continue
            seen_p2.add(norm)
            content_parts.append(f"- {title}")
        content_parts.append("")

    # ═══════════════════════════════════════
    # 8. REPORT LINKS
    # ═══════════════════════════════════════
    content_parts.append("---\n")
    content_parts.append("## 상세 리포트 링크\n")
    report_rows = []
    for name, count, url in post_links:
        count_str = f"{count}건" if count else "-"
        report_rows.append([name, count_str, f"[바로가기]({url})"])
    if report_rows:
        content_parts.append(
            markdown_table(
                ["리포트", "수집 건수", "링크"],
                report_rows,
                aligns=["left", "center", "left"],
            )
        )

    content_parts.append("\n---\n")
    content_parts.append(
        "*본 요약은 자동 수집된 뉴스 데이터를 기반으로 작성되었으며, 투자 조언이 아닙니다.*"
    )

    content = "\n".join(content_parts)

    # Create post with pin: true
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

    frontmatter = f"""---
title: "{escaped_title}"
date: {today} 12:00:00 +0900
categories: [market-analysis]
tags: [{", ".join(tags)}]
source: "consolidated"
lang: "ko"
pin: true
excerpt: "{counts_str}의 뉴스를 종합 분석한 일일 요약"
---"""

    post_content = frontmatter + "\n\n" + content.strip()

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(post_content)

    logger.info(
        "Created daily summary: %s (total %d news items)", filepath, total_count
    )
    logger.info("=== Daily summary generation complete ===")


if __name__ == "__main__":
    main()
