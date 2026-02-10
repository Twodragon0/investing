#!/usr/bin/env python3
"""Generate weekly digest post with real analysis from the past week's posts.

Enhanced version with:
- Key highlights extraction from post bodies
- Category-wise summaries with insights
- Weekly performance overview
- Actionable takeaways
"""

import sys
import os
import re
from datetime import datetime, timedelta, timezone
from typing import List, Dict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common.config import setup_logging
from common.post_generator import PostGenerator

logger = setup_logging("generate_weekly_digest")

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
POSTS_DIR = os.path.join(REPO_ROOT, "_posts")


def parse_post_frontmatter(filepath: str) -> Dict:
    """Parse YAML frontmatter from a markdown post file."""
    result = {"title": "", "date": "", "categories": "", "tags": []}
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        # Extract frontmatter between --- markers
        match = re.match(r"^---\n(.*?)\n---\n(.*)", content, re.DOTALL)
        if not match:
            return result

        frontmatter = match.group(1)
        body = match.group(2).strip()
        result["body"] = body

        for line in frontmatter.split("\n"):
            if line.startswith("title:"):
                result["title"] = line.split(":", 1)[1].strip().strip('"').strip("'")
            elif line.startswith("date:"):
                result["date"] = line.split(":", 1)[1].strip()
            elif line.startswith("categories:"):
                result["categories"] = line.split(":", 1)[1].strip()

        return result
    except Exception as e:
        logger.warning("Failed to parse %s: %s", filepath, e)
        return result


def collect_weekly_posts(days: int = 7) -> List[Dict]:
    """Collect all posts from the past N days."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)
    cutoff_str = cutoff.strftime("%Y-%m-%d")

    posts = []
    if not os.path.isdir(POSTS_DIR):
        logger.warning("Posts directory not found: %s", POSTS_DIR)
        return posts

    for filename in sorted(os.listdir(POSTS_DIR)):
        if not filename.endswith(".md"):
            continue

        # Parse date from filename (YYYY-MM-DD-slug.md)
        date_match = re.match(r"^(\d{4}-\d{2}-\d{2})-", filename)
        if not date_match:
            continue

        file_date = date_match.group(1)
        if file_date < cutoff_str:
            continue

        filepath = os.path.join(POSTS_DIR, filename)
        post_data = parse_post_frontmatter(filepath)
        post_data["filename"] = filename
        post_data["file_date"] = file_date
        posts.append(post_data)

    logger.info("Found %d posts from the past %d days", len(posts), days)
    return posts


def extract_key_bullets(body: str, max_bullets: int = 3) -> List[str]:
    """Extract key bullet points from a post body."""
    if not body:
        return []

    bullets = []

    # Try to find "오늘의 핵심" or "핵심" section bullets
    core_match = re.search(r"##\s*(?:오늘의\s*)?핵심.*?\n((?:- .+\n?)+)", body)
    if core_match:
        raw = core_match.group(1).strip()
        for line in raw.split("\n"):
            line = line.strip()
            if line.startswith("- "):
                # Clean markdown bold and truncate
                clean = re.sub(r"\*\*(.+?)\*\*", r"\1", line[2:])
                if len(clean) > 120:
                    clean = clean[:117] + "..."
                bullets.append(clean)
                if len(bullets) >= max_bullets:
                    break
        return bullets

    # Fallback: extract first paragraph as summary
    paragraphs = [p.strip() for p in body.split("\n\n") if p.strip() and not p.strip().startswith(("#", "|", "!", "---", ">", "```"))]
    if paragraphs:
        first = paragraphs[0]
        # Remove markdown
        first = re.sub(r"\*\*(.+?)\*\*", r"\1", first)
        first = re.sub(r"\[(.+?)\]\(.+?\)", r"\1", first)
        if len(first) > 150:
            first = first[:147] + "..."
        bullets.append(first)

    return bullets


def extract_market_data(posts: List[Dict]) -> Dict:
    """Extract market data from market-analysis posts."""
    data = {
        "fear_greed": [],
        "btc_prices": [],
        "total_mcap": [],
        "kr_market": [],
    }

    for post in posts:
        cat = post.get("categories", "").strip("[]")
        if cat != "market-analysis":
            continue

        body = post.get("body", "")
        date = post.get("file_date", "")

        # Extract Fear & Greed Index
        fg_match = re.search(r"공포/탐욕 지수:\s*(\d+)/100", body)
        if fg_match:
            data["fear_greed"].append({"date": date, "value": int(fg_match.group(1))})

        # Extract BTC price
        btc_match = re.search(r"\*\*Bitcoin\*\*.*?\$([0-9,]+(?:\.\d+)?)", body)
        if btc_match:
            price_str = btc_match.group(1).replace(",", "")
            try:
                data["btc_prices"].append({"date": date, "price": float(price_str)})
            except ValueError:
                pass

        # Extract total market cap
        mcap_match = re.search(r"총 시가총액\s*\|\s*\$([0-9.]+)T", body)
        if mcap_match:
            try:
                data["total_mcap"].append({"date": date, "value": float(mcap_match.group(1))})
            except ValueError:
                pass

    return data


def generate_digest(posts: List[Dict]) -> str:
    """Generate comprehensive weekly digest content in Korean."""
    now = datetime.now(timezone.utc)
    week_start = (now - timedelta(days=7)).strftime("%m월 %d일")
    week_end = now.strftime("%m월 %d일")

    content_parts = [
        f"이번 주 ({week_start} ~ {week_end}) 투자 시장의 주요 동향과 핵심 이슈를 종합 분석합니다.\n",
    ]

    # Group posts by category
    categories = {}
    for post in posts:
        cat = post.get("categories", "기타").strip("[]")
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(post)

    # Extract market data for overview
    market_data = extract_market_data(posts)

    # ── Weekly Market Overview ──
    content_parts.append("## 주간 시장 개요\n")

    overview_lines = []

    # BTC price range
    if market_data["btc_prices"]:
        prices = [d["price"] for d in market_data["btc_prices"]]
        overview_lines.append(f"| BTC 가격 범위 | ${min(prices):,.0f} ~ ${max(prices):,.0f} |")
        if len(prices) >= 2:
            weekly_change = ((prices[-1] - prices[0]) / prices[0]) * 100
            direction = "🟢" if weekly_change >= 0 else "🔴"
            overview_lines.append(f"| BTC 주간 변동 | {direction} {weekly_change:+.1f}% |")

    # Fear & Greed trend
    if market_data["fear_greed"]:
        fg_values = [d["value"] for d in market_data["fear_greed"]]
        fg_start = market_data["fear_greed"][0]["value"]
        fg_end = market_data["fear_greed"][-1]["value"]
        overview_lines.append(f"| 공포/탐욕 지수 | {fg_start} → {fg_end} (범위: {min(fg_values)}~{max(fg_values)}) |")

    # Total market cap
    if market_data["total_mcap"]:
        mcaps = [d["value"] for d in market_data["total_mcap"]]
        overview_lines.append(f"| 총 시가총액 | ${mcaps[-1]:.2f}T |")

    if overview_lines:
        content_parts.append("| 지표 | 값 |")
        content_parts.append("|------|------|")
        content_parts.extend(overview_lines)
        content_parts.append("")

    # ── Category Sections with Insights ──
    cat_names = {
        "crypto-news": "암호화폐 뉴스",
        "stock-news": "주식 시장",
        "security-alerts": "보안 알림",
        "market-analysis": "시장 분석",
        "social-media": "소셜 미디어",
    }

    # Priority order for categories
    cat_order = ["market-analysis", "crypto-news", "stock-news", "security-alerts"]

    for cat in cat_order:
        if cat not in categories:
            continue
        cat_posts = categories[cat]
        display_name = cat_names.get(cat, cat)

        content_parts.append(f"## {display_name}\n")

        # Extract and display key insights from each post
        for p in sorted(cat_posts, key=lambda x: x.get("file_date", ""), reverse=True):
            title = p.get("title", "제목 없음")
            date = p.get("file_date", "")
            content_parts.append(f"### {title} ({date})\n")

            bullets = extract_key_bullets(p.get("body", ""))
            if bullets:
                for b in bullets:
                    content_parts.append(f"- {b}")
                content_parts.append("")
            else:
                # Fallback: show first sentence of body
                body = p.get("body", "").strip()
                if body:
                    first_line = body.split("\n")[0].strip()
                    if first_line and not first_line.startswith(("#", "|", "!")):
                        clean = re.sub(r"\*\*(.+?)\*\*", r"\1", first_line)
                        if len(clean) > 150:
                            clean = clean[:147] + "..."
                        content_parts.append(f"- {clean}")
                content_parts.append("")

    # Remaining categories not in priority order
    for cat, cat_posts in categories.items():
        if cat in cat_order:
            continue
        display_name = cat_names.get(cat, cat)
        content_parts.append(f"## {display_name}\n")
        content_parts.append("| 날짜 | 제목 |")
        content_parts.append("|------|------|")
        for p in sorted(cat_posts, key=lambda x: x.get("file_date", ""), reverse=True):
            title = p.get("title", "제목 없음")
            date = p.get("file_date", "")
            content_parts.append(f"| {date} | **{title}** |")
        content_parts.append("")

    # ── Weekly Statistics ──
    content_parts.append("## 주간 통계\n")
    content_parts.append(f"- 총 포스트 수: **{len(posts)}건**")
    content_parts.append(f"- 카테고리: **{len(categories)}개**")
    content_parts.append(f"- 기간: {week_start} ~ {week_end}")

    # Post count by category
    content_parts.append("\n| 카테고리 | 포스트 수 |")
    content_parts.append("|----------|----------|")
    for cat, cat_posts in sorted(categories.items(), key=lambda x: len(x[1]), reverse=True):
        display_name = cat_names.get(cat, cat)
        content_parts.append(f"| {display_name} | {len(cat_posts)}건 |")

    content_parts.append("")
    content_parts.append("> *본 다이제스트는 한 주간 수집된 데이터를 기반으로 자동 생성되었으며, 투자 조언이 아닙니다.*")

    return "\n".join(content_parts)


def main():
    """Main weekly digest generation routine."""
    logger.info("=== Starting weekly digest generation ===")

    now = datetime.now(timezone.utc)
    gen = PostGenerator("market-analysis")

    posts = collect_weekly_posts(days=7)
    if not posts:
        logger.info("No posts found for the past week, skipping digest")
        return

    week_str = now.strftime("%Y년 %m월 %d일")
    title = f"주간 투자 다이제스트 - {week_str}"
    content = generate_digest(posts)

    filepath = gen.create_post(
        title=title,
        content=content,
        date=now,
        tags=["weekly-digest", "summary", "market-analysis"],
        source="auto-generated",
        lang="ko",
        slug=f"weekly-investment-digest-{now.strftime('%Y-%m-%d')}",
    )

    if filepath:
        logger.info("Created weekly digest: %s", filepath)
    else:
        logger.info("Weekly digest already exists or skipped")

    logger.info("=== Weekly digest generation complete ===")


if __name__ == "__main__":
    main()
