#!/usr/bin/env python3
"""Backfill generated images for Jekyll posts that lack them.

Scans all posts in _posts/, identifies those without a valid generated image,
parses post content to extract theme/section data, generates an appropriate
image using the image_generator module, and updates the post frontmatter
with the new image path.
"""

import sys
import os
import re
import importlib.util
from typing import Dict, List, Optional, Tuple

# Add scripts directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import setup_logging directly from common/config.py to avoid triggering
# common/__init__.py which pulls in heavy dependencies (bs4, requests, etc.)
_config_path = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "common", "config.py"
)
_spec = importlib.util.spec_from_file_location("common_config", _config_path)
assert _spec is not None and _spec.loader is not None
_config_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_config_mod)
setup_logging = _config_mod.setup_logging

logger = setup_logging("backfill_images")

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
POSTS_DIR = os.path.join(REPO_ROOT, "_posts")
IMAGES_DIR = os.path.join(REPO_ROOT, "assets", "images", "generated")

# ── Emoji mappings per post type ──────────────────────────────────────────────

EMOJI_MAPS: Dict[str, Dict[str, str]] = {
    "daily-political-trades-report": {
        "정치": "\U0001f3db\ufe0f",
        "SEC": "\U0001f4cb",
        "규제": "\u2696\ufe0f",
        "거래": "\U0001f4b0",
        "트럼프": "\U0001f3db\ufe0f",
        "의회": "\U0001f3db\ufe0f",
        "행정명령": "\U0001f4dc",
        "내부자": "\U0001f4b0",
        "정책": "\U0001f4dc",
        "매크로": "\U0001f4c8",
    },
    "daily-security-report": {
        "해킹": "\U0001f513",
        "취약점": "\u26a0\ufe0f",
        "DeFi": "\U0001f4a5",
        "사기": "\U0001f6a8",
        "보안": "\U0001f513",
        "스마트": "\u26a0\ufe0f",
        "컨트랙트": "\u26a0\ufe0f",
        "피싱": "\U0001f6a8",
        "익스플로잇": "\U0001f4a5",
    },
    "blockchain-security-report": {
        "해킹": "\U0001f513",
        "취약점": "\u26a0\ufe0f",
        "DeFi": "\U0001f4a5",
        "보안": "\U0001f513",
        "스마트": "\u26a0\ufe0f",
        "컨트랙트": "\u26a0\ufe0f",
    },
    "daily-worldmonitor-briefing": {
        "지정학": "\U0001f30d",
        "정책": "\U0001f4dc",
        "경제": "\U0001f4ca",
        "사회": "\U0001f465",
        "안보": "\U0001f30d",
        "에너지": "\u26a1",
        "법률": "\U0001f4dc",
        "금융": "\U0001f4ca",
        "글로벌": "\U0001f30d",
    },
    "daily-regulatory-report": {
        "규제": "\u2696\ufe0f",
        "거래소": "\U0001f3e6",
        "정책": "\U0001f4dc",
        "SEC": "\U0001f4cb",
        "CFTC": "\U0001f4cb",
        "법안": "\U0001f4dc",
        "라이선스": "\U0001f3e6",
        "감독": "\u2696\ufe0f",
    },
    "daily-crypto-news-digest": {
        "비트코인": "\U0001f4b0",
        "이더리움": "\U0001f4b0",
        "DeFi": "\U0001f4a5",
        "NFT": "\U0001f5bc\ufe0f",
        "거래소": "\U0001f3e6",
        "규제": "\u2696\ufe0f",
        "ETF": "\U0001f4c8",
        "BTC": "\U0001f4b0",
    },
    "daily-news-summary": {
        "암호화폐": "\U0001f4b0",
        "주식": "\U0001f4c8",
        "규제": "\u2696\ufe0f",
        "소셜": "\U0001f4f1",
        "보안": "\U0001f513",
        "시장": "\U0001f4ca",
        "경제": "\U0001f4ca",
    },
    "daily-market-report": {
        "시장": "\U0001f4ca",
        "BTC": "\U0001f4b0",
        "ETH": "\U0001f4b0",
        "주식": "\U0001f4c8",
        "매크로": "\U0001f30d",
        "금리": "\U0001f3e6",
        "핵심": "\U0001f525",
    },
    "daily-crypto-market-report": {
        "BTC": "\U0001f4b0",
        "ETH": "\U0001f4b0",
        "DeFi": "\U0001f4a5",
        "시장": "\U0001f4ca",
        "거래량": "\U0001f4c8",
        "Top": "\U0001f3c6",
    },
    "daily-social-media-digest": {
        "텔레그램": "\U0001f4e8",
        "트위터": "\U0001f426",
        "레딧": "\U0001f4ac",
        "소셜": "\U0001f4f1",
        "커뮤니티": "\U0001f465",
        "Telegram": "\U0001f4e8",
        "Twitter": "\U0001f426",
        "Reddit": "\U0001f4ac",
    },
    "daily-stock-news-digest": {
        "주식": "\U0001f4c8",
        "S&P": "\U0001f4ca",
        "나스닥": "\U0001f4ca",
        "실적": "\U0001f4b5",
        "IPO": "\U0001f680",
        "배당": "\U0001f4b0",
        "ETF": "\U0001f4c8",
        "산업": "\U0001f3ed",
    },
    "daily-defi-tvl-report": {
        "DeFi": "\U0001f4a5",
        "TVL": "\U0001f4ca",
        "프로토콜": "\u2699\ufe0f",
        "체인": "\U0001f517",
        "유동성": "\U0001f4b0",
    },
}

# Category label mapping
CATEGORY_LABELS: Dict[str, str] = {
    "daily-political-trades-report": "Political Trades Report",
    "daily-security-report": "Security Alert Report",
    "blockchain-security-report": "Security Alert Report",
    "daily-worldmonitor-briefing": "World Monitor Briefing",
    "daily-regulatory-report": "Regulatory Report",
    "daily-crypto-news-digest": "Crypto News Briefing",
    "daily-news-summary": "Daily News Summary",
    "daily-market-report": "Market Report",
    "daily-crypto-market-report": "Crypto Market Report",
    "daily-social-media-digest": "Social Media Digest",
    "daily-stock-news-digest": "Stock Market Report",
    "daily-defi-tvl-report": "DeFi TVL Report",
    "weekly-investment-digest": "Weekly Investment Digest",
    "economic-indicators-report": "Economic Indicators",
    "insider-trading-report": "Insider Trading Report",
    "crypto-news-briefing": "Crypto News Briefing",
    "collected-materials-summary": "Daily News Summary",
    "crypto-trading-journal-template": "Trading Journal",
    "stock-trading-journal-template": "Trading Journal",
}

# Filename prefix mapping for generated images
FILENAME_PREFIXES: Dict[str, str] = {
    "daily-political-trades-report": "news-briefing-political",
    "daily-security-report": "news-briefing-security",
    "blockchain-security-report": "news-briefing-security",
    "daily-worldmonitor-briefing": "news-briefing-worldmonitor",
    "daily-regulatory-report": "news-briefing-regulatory",
    "daily-crypto-news-digest": "news-briefing-crypto",
    "daily-news-summary": "news-briefing-summary",
    "daily-market-report": "news-briefing-market",
    "daily-crypto-market-report": "news-briefing-cryptomarket",
    "daily-social-media-digest": "news-briefing-social",
    "daily-stock-news-digest": "news-briefing-stock",
    "daily-defi-tvl-report": "news-briefing-defi",
    "weekly-investment-digest": "news-summary-weekly",
    "economic-indicators-report": "news-briefing-economic",
    "insider-trading-report": "news-briefing-insider",
    "crypto-news-briefing": "news-briefing-crypto",
    "collected-materials-summary": "news-briefing-collected",
    "crypto-trading-journal-template": "news-briefing-journal",
    "stock-trading-journal-template": "news-briefing-journal-stock",
}

# Default emoji when no keyword match is found
DEFAULT_EMOJIS = [
    "\U0001f4ca",
    "\U0001f4c8",
    "\U0001f4b0",
    "\U0001f30d",
    "\U0001f525",
]


# ── Post parsing utilities ────────────────────────────────────────────────────


def get_post_type(filename: str) -> Optional[str]:
    """Extract post type slug from Jekyll filename."""
    basename = os.path.basename(filename)
    m = re.match(r"\d{4}-\d{2}-\d{2}-(.*?)\.md$", basename)
    if m:
        slug = m.group(1)
        # weekly-investment-digest-YYYY-MM-DD -> weekly-investment-digest
        if slug.startswith("weekly-investment-digest"):
            return "weekly-investment-digest"
        return slug
    return None


def get_date_from_filename(filename: str) -> Optional[str]:
    """Extract date string (YYYY-MM-DD) from Jekyll filename."""
    basename = os.path.basename(filename)
    m = re.match(r"(\d{4}-\d{2}-\d{2})-", basename)
    if m:
        return m.group(1)
    return None


def parse_frontmatter(content: str) -> Tuple[Dict[str, str], str]:
    """Parse YAML frontmatter from Jekyll post content.

    Returns (frontmatter_dict, body_content).
    """
    fm: Dict[str, str] = {}
    body = content

    if not content.startswith("---"):
        return fm, body

    # Find closing ---
    end_idx = content.find("---", 3)
    if end_idx == -1:
        return fm, body

    fm_text = content[3:end_idx].strip()
    body = content[end_idx + 3 :].strip()

    for line in fm_text.split("\n"):
        line = line.strip()
        if ":" in line:
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            fm[key] = value

    return fm, body


def needs_image(filepath: str) -> bool:
    """Check if a post needs an image generated."""
    with open(filepath, encoding="utf-8") as f:
        content = f.read()

    fm, _ = parse_frontmatter(content)
    img = fm.get("image", "")

    # No image field at all
    if not img:
        return True

    # Placeholder default image
    if img == "/assets/images/og-default.png":
        return True

    return False


def extract_themes(
    content: str, post_type: str, max_themes: int = 5
) -> List[Dict[str, object]]:
    """Extract section themes from post body content.

    Parses ## headings and counts bullet points per section,
    extracting keywords from bullet text.
    """
    emoji_map = EMOJI_MAPS.get(post_type, {})
    themes: List[Dict[str, object]] = []
    current_section: Optional[str] = None
    bullet_count = 0
    keywords: List[str] = []

    for line in content.split("\n"):
        line_stripped = line.strip()

        if line_stripped.startswith("## "):
            # Save previous section
            if current_section:
                emoji = _match_emoji(current_section, emoji_map, len(themes))
                themes.append(
                    {
                        "name": current_section,
                        "emoji": emoji,
                        "count": max(bullet_count, 1),
                        "keywords": _dedupe_keywords(keywords[:4]),
                    }
                )
            current_section = line_stripped[3:].strip()
            # Strip any markdown formatting from section name
            current_section = re.sub(r"[*_`]", "", current_section)
            bullet_count = 0
            keywords = []

        elif line_stripped.startswith(("- ", "* ")):
            bullet_count += 1
            # Extract meaningful words from bullet text
            text = line_stripped[2:80]
            # Remove markdown links
            text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
            # Remove bold/italic markers
            text = re.sub(r"[*_`]", "", text)
            words = re.findall(r"[가-힣A-Za-z0-9$%]+", text)
            keywords.extend(words[:3])

    # Capture final section
    if current_section:
        emoji = _match_emoji(current_section, emoji_map, len(themes))
        themes.append(
            {
                "name": current_section,
                "emoji": emoji,
                "count": max(bullet_count, 1),
                "keywords": _dedupe_keywords(keywords[:4]),
            }
        )

    return themes[:max_themes]


def extract_categories_for_weekly(content: str) -> List[Dict[str, object]]:
    """Extract categories with counts for weekly digest posts.

    Parses ## headings and counts bullet points per section.
    Returns data suitable for generate_news_summary_card.
    """
    categories: List[Dict[str, object]] = []
    current_section: Optional[str] = None
    bullet_count = 0

    for line in content.split("\n"):
        line_stripped = line.strip()

        if line_stripped.startswith("## "):
            if current_section:
                categories.append(
                    {"name": current_section, "count": max(bullet_count, 1)}
                )
            current_section = line_stripped[3:].strip()
            current_section = re.sub(r"[*_`]", "", current_section)
            bullet_count = 0

        elif line_stripped.startswith(("- ", "* ")):
            bullet_count += 1

    if current_section:
        categories.append({"name": current_section, "count": max(bullet_count, 1)})

    return categories[:8]


def extract_source_data(content: str) -> List[Dict[str, object]]:
    """Try to extract source distribution data from social media posts.

    Looks for patterns like "Telegram (10건)" or table rows with source counts.
    """
    sources: List[Dict[str, object]] = []

    # Pattern: source_name count건 or source_name (count건)
    pattern = re.compile(
        r"(Telegram|Twitter|Reddit|텔레그램|트위터|레딧|Discord|YouTube|"
        r"Naver|네이버)[^0-9]*(\d+)\s*건",
        re.IGNORECASE,
    )
    for m in pattern.finditer(content):
        name = m.group(1)
        count = int(m.group(2))
        if count > 0:
            sources.append({"name": name, "count": count})

    # Deduplicate by name
    seen: set = set()
    unique: List[Dict[str, object]] = []
    for s in sources:
        name = str(s["name"]).lower()
        if name not in seen:
            seen.add(name)
            unique.append(s)

    return unique


def _match_emoji(section_name: str, emoji_map: Dict[str, str], idx: int) -> str:
    """Find the best emoji for a section name using the emoji map."""
    for keyword, emoji in emoji_map.items():
        if keyword.lower() in section_name.lower():
            return emoji
    # Fallback: cycle through defaults
    return DEFAULT_EMOJIS[idx % len(DEFAULT_EMOJIS)]


def _dedupe_keywords(keywords: List[str]) -> List[str]:
    """Remove duplicate keywords while preserving order."""
    seen: set = set()
    result: List[str] = []
    for kw in keywords:
        lower = kw.lower()
        if lower not in seen and len(kw) > 1:
            seen.add(lower)
            result.append(kw)
    return result


def extract_total_count(content: str) -> int:
    """Try to extract total article/news count from post content."""
    # Pattern: 총 N건 or 총 수집 건수: N건 or N건의 뉴스
    patterns = [
        re.compile(r"총\s*(\d+)\s*건"),
        re.compile(r"총\s*수집[^0-9]*(\d+)\s*건"),
        re.compile(r"(\d+)\s*건의\s*뉴스"),
        re.compile(r"(\d+)\s*건을\s*(?:정리|분석|요약)"),
    ]
    for pat in patterns:
        m = pat.search(content)
        if m:
            return int(m.group(1))
    return 0


# ── Image generation ──────────────────────────────────────────────────────────

_IMG_GEN_MOD = None
_IMG_GEN_LOADED = False


def _load_image_generator():
    """Load image_generator module directly, bypassing common/__init__.py."""
    global _IMG_GEN_MOD, _IMG_GEN_LOADED
    if _IMG_GEN_LOADED:
        return _IMG_GEN_MOD
    _IMG_GEN_LOADED = True
    try:
        img_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "common", "image_generator.py"
        )
        spec = importlib.util.spec_from_file_location("image_generator", img_path)
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _IMG_GEN_MOD = mod
        return mod
    except Exception as exc:
        logger.warning("Failed to load image_generator: %s", exc)
        return None


def generate_image_for_post(
    filepath: str, post_type: str, date_str: str, body: str
) -> Optional[str]:
    """Generate an appropriate image for the given post.

    Returns the relative image path (e.g. /assets/images/generated/foo.png)
    or None on failure.
    """
    try:
        img_mod = _load_image_generator()
        if img_mod is None:
            return None
        generate_news_briefing_card = img_mod.generate_news_briefing_card
        generate_news_summary_card = img_mod.generate_news_summary_card
        generate_source_distribution_card = img_mod.generate_source_distribution_card
    except Exception as exc:
        logger.warning("image_generator not available: %s", exc)
        return None

    prefix = FILENAME_PREFIXES.get(post_type, f"news-briefing-{post_type}")
    filename = f"{prefix}-{date_str}.png"

    # Check if image file already exists on disk
    disk_path = os.path.join(IMAGES_DIR, filename)
    if os.path.exists(disk_path):
        logger.info("Image already exists on disk: %s", filename)
        return f"/assets/images/generated/{filename}"

    category = CATEGORY_LABELS.get(post_type, "Daily Briefing")
    total_count = extract_total_count(body)

    # Weekly digest -> news summary card (bar chart)
    if post_type == "weekly-investment-digest":
        categories = extract_categories_for_weekly(body)
        if categories:
            return generate_news_summary_card(
                categories=categories,
                date_str=date_str,
                filename=filename,
            )

    # Social media -> try source distribution first
    if post_type == "daily-social-media-digest":
        sources = extract_source_data(body)
        if len(sources) >= 2:
            return generate_source_distribution_card(
                sources=sources,
                date_str=date_str,
                filename=filename,
            )
        # Fall through to briefing card

    # Default: news briefing card for all other types
    themes = extract_themes(body, post_type)
    if not themes:
        # Build a minimal single-theme fallback
        themes = [
            {
                "name": category,
                "emoji": DEFAULT_EMOJIS[0],
                "count": max(total_count, 1),
                "keywords": [],
            }
        ]

    return generate_news_briefing_card(
        themes=themes,
        date_str=date_str,
        category=category,
        total_count=total_count,
        filename=filename,
    )


# ── Frontmatter update ───────────────────────────────────────────────────────


def update_frontmatter_image(filepath: str, image_path: str) -> bool:
    """Update or insert the image: field in a post's frontmatter.

    Returns True if the file was modified.
    """
    with open(filepath, encoding="utf-8") as f:
        content = f.read()

    if not content.startswith("---"):
        logger.warning("No frontmatter found in %s", filepath)
        return False

    end_idx = content.find("---", 3)
    if end_idx == -1:
        logger.warning("Unclosed frontmatter in %s", filepath)
        return False

    fm_text = content[3:end_idx]
    rest = content[end_idx:]

    # Check if image: already exists in frontmatter
    image_line = f'image: "{image_path}"'
    image_re = re.compile(r"^image:.*$", re.MULTILINE)

    if image_re.search(fm_text):
        # Replace existing image line
        new_fm = image_re.sub(image_line, fm_text)
    else:
        # Insert image: before the closing ---
        # Try to insert after description: line for consistency
        desc_re = re.compile(r"^(description:.*$)", re.MULTILINE)
        desc_match = desc_re.search(fm_text)
        if desc_match:
            insert_pos = desc_match.end()
            new_fm = fm_text[:insert_pos] + "\n" + image_line + fm_text[insert_pos:]
        else:
            # Insert at the end of frontmatter (before closing ---)
            new_fm = fm_text.rstrip("\n") + "\n" + image_line + "\n"

    new_content = "---" + new_fm + rest

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(new_content)

    return True


# ── Main ──────────────────────────────────────────────────────────────────────


def find_posts_without_images() -> List[str]:
    """Find all Jekyll posts that need image generation."""
    if not os.path.isdir(POSTS_DIR):
        logger.error("Posts directory not found: %s", POSTS_DIR)
        return []

    posts = []
    for filename in sorted(os.listdir(POSTS_DIR)):
        if not filename.endswith(".md"):
            continue
        filepath = os.path.join(POSTS_DIR, filename)
        if needs_image(filepath):
            posts.append(filepath)

    return posts


def main() -> None:
    """Backfill images for all posts that lack them."""
    os.makedirs(IMAGES_DIR, exist_ok=True)

    posts = find_posts_without_images()
    if not posts:
        logger.info("All posts already have images. Nothing to do.")
        return

    logger.info("Found %d posts without images", len(posts))

    success_count = 0
    skip_count = 0
    fail_count = 0

    for filepath in posts:
        filename = os.path.basename(filepath)
        post_type = get_post_type(filename)
        date_str = get_date_from_filename(filename)

        if not post_type or not date_str:
            logger.warning("Could not parse post info from: %s", filename)
            skip_count += 1
            continue

        logger.info("Processing: %s (type=%s, date=%s)", filename, post_type, date_str)

        # Read post content
        with open(filepath, encoding="utf-8") as f:
            content = f.read()
        _, body = parse_frontmatter(content)

        # Generate image
        image_path = generate_image_for_post(filepath, post_type, date_str, body)
        if not image_path:
            logger.warning("Failed to generate image for: %s", filename)
            fail_count += 1
            continue

        # Update frontmatter
        if update_frontmatter_image(filepath, image_path):
            logger.info("Updated frontmatter: %s -> %s", filename, image_path)
            success_count += 1
        else:
            logger.warning("Failed to update frontmatter for: %s", filename)
            fail_count += 1

    logger.info(
        "Backfill complete: %d success, %d skipped, %d failed (of %d total)",
        success_count,
        skip_count,
        fail_count,
        len(posts),
    )


if __name__ == "__main__":
    main()
