#!/usr/bin/env python3
"""Generate weekly digest post consolidating the past week's daily posts."""

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


def generate_digest(posts: List[Dict]) -> str:
    """Generate weekly digest content in Korean."""
    now = datetime.now(timezone.utc)
    week_start = (now - timedelta(days=7)).strftime("%m월 %d일")
    week_end = now.strftime("%m월 %d일")

    content_parts = [
        f"이번 주 ({week_start} ~ {week_end}) 투자 관련 뉴스와 시장 분석을 종합 정리합니다.\n",
    ]

    # Group posts by category
    categories = {}
    for post in posts:
        cat = post.get("categories", "기타").strip("[]")
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(post)

    # Category display names (Korean)
    cat_names = {
        "crypto-news": "암호화폐 뉴스",
        "stock-news": "주식 시장",
        "security-alerts": "보안 알림",
        "market-analysis": "시장 분석",
        "social-media": "소셜 미디어",
    }

    for cat, cat_posts in categories.items():
        display_name = cat_names.get(cat, cat)
        content_parts.append(f"## {display_name}\n")
        content_parts.append("| 날짜 | 제목 |")
        content_parts.append("|------|------|")
        for p in sorted(cat_posts, key=lambda x: x.get("file_date", ""), reverse=True):
            title = p.get("title", "제목 없음")
            date = p.get("file_date", "")
            content_parts.append(f"| {date} | **{title}** |")
        content_parts.append("")

    # Summary stats
    content_parts.append("## 주간 통계\n")
    content_parts.append(f"- 총 포스트 수: {len(posts)}건")
    content_parts.append(f"- 카테고리: {len(categories)}개")
    content_parts.append(f"- 기간: {week_start} ~ {week_end}")

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
