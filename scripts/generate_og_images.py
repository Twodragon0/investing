"""OG image generator for SNS sharing (KakaoTalk, Twitter, LinkedIn).

Generates 1200x630px PNG images for each Jekyll post with:
- Dark background matching the site theme
- Category-specific accent color
- Post title, date, description, and branding
"""

import argparse
import logging
import os
import re
import textwrap
from typing import Any, Dict, List, Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("og-image-gen")

# ── Paths ──
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
POSTS_DIR = os.path.join(REPO_ROOT, "_posts")
IMAGES_DIR = os.path.join(REPO_ROOT, "assets", "images", "generated")

# ── Category colors ──
CATEGORY_COLORS: Dict[str, str] = {
    "crypto-news": "#f7931a",
    "stock-news": "#4caf50",
    "market-analysis": "#2196f3",
    "regulatory-news": "#00bcd4",
    "social-media": "#e91e63",
    "defi": "#7c4dff",
    "political-trades": "#ff5722",
    "worldmonitor": "#009688",
    "security": "#f44336",
    "daily-summary": "#ffc107",
}
DEFAULT_ACCENT = "#607d8b"

# ── Category display names ──
CATEGORY_LABELS: Dict[str, str] = {
    "crypto-news": "암호화폐",
    "stock-news": "주식",
    "market-analysis": "시장분석",
    "regulatory-news": "규제동향",
    "social-media": "소셜미디어",
    "defi": "DeFi",
    "political-trades": "정치거래",
    "worldmonitor": "글로벌",
    "security": "보안",
    "daily-summary": "일일요약",
}

# ── Theme colors ──
BG_COLOR = "#1a1f2e"
TEXT_WHITE = "#ffffff"
TEXT_GRAY = "#9ca3af"
TEXT_MUTED = "#6b7280"
DIVIDER_COLOR = "#374151"

# ── matplotlib setup ──
try:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.font_manager as fm
    import matplotlib.patches as mpatches
    import matplotlib.pyplot as plt

    _MPL_AVAILABLE = True
except ImportError:
    _MPL_AVAILABLE = False
    logger.error("matplotlib is required but not installed")

# ── Font setup (same candidates as image_generator.py) ──
_FONT_FAMILY = "monospace"
_FONT_BOLD_PATH: Optional[str] = None

if _MPL_AVAILABLE:
    _korean_font_candidates = [
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansKR-Regular.ttf",
        "/System/Library/Fonts/AppleSDGothicNeo.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
        "/System/Library/Fonts/Supplemental/AppleGothic.ttf",
    ]
    for _fp in _korean_font_candidates:
        if os.path.exists(_fp):
            fm.fontManager.addfont(_fp)
            _prop = fm.FontProperties(fname=_fp)
            _FONT_FAMILY = _prop.get_name()
            _FONT_BOLD_PATH = _fp
            logger.info("Using font '%s' for CJK support", _FONT_FAMILY)
            break
    else:
        logger.warning("No CJK font found, Korean text may not render correctly")

    matplotlib.rcParams["font.family"] = [_FONT_FAMILY]

_FK: Dict[str, Any] = {"fontfamily": _FONT_FAMILY} if _MPL_AVAILABLE else {}


# ── YAML front matter parser ──

def parse_front_matter(filepath: str) -> Optional[Dict[str, str]]:
    """Parse YAML front matter from a markdown file.

    Returns dict with title, date, categories, description, image, or None.
    """
    try:
        with open(filepath, encoding="utf-8") as f:
            content = f.read()
    except OSError as e:
        logger.warning("Cannot read %s: %s", filepath, e)
        return None

    match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
    if not match:
        return None

    fm_text = match.group(1)
    result: Dict[str, str] = {}

    for key in ("title", "date", "description", "image", "categories"):
        pattern = rf'^{key}:\s*(.+)$'
        m = re.search(pattern, fm_text, re.MULTILINE)
        if m:
            val = m.group(1).strip().strip('"').strip("'")
            if key == "categories":
                # Parse [cat1, cat2] or cat1
                val = val.strip("[]")
                val = val.split(",")[0].strip().strip('"').strip("'")
            result[key] = val

    if "title" not in result:
        return None

    return result


def slug_from_filename(filename: str) -> str:
    """Extract slug from post filename like 2026-03-07-daily-regulatory-report.md."""
    name = os.path.basename(filename)
    # Remove .md extension
    name = re.sub(r"\.md$", "", name)
    # Remove date prefix (YYYY-MM-DD-)
    name = re.sub(r"^\d{4}-\d{2}-\d{2}-", "", name)
    return name


def date_from_filename(filename: str) -> Optional[str]:
    """Extract date string (YYYY-MM-DD) from post filename."""
    name = os.path.basename(filename)
    m = re.match(r"^(\d{4}-\d{2}-\d{2})-", name)
    return m.group(1) if m else None


def format_date_korean(date_str: str) -> str:
    """Convert YYYY-MM-DD to Korean format like 2026년 03월 07일."""
    try:
        parts = date_str.split("-")
        return f"{parts[0]}년 {parts[1]}월 {parts[2]}일"
    except ValueError:
        return date_str


def truncate_text(text: str, max_chars: int) -> str:
    """Truncate text to max_chars, adding ... if needed."""
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def wrap_text(text: str, max_width: int, max_lines: int) -> List[str]:
    """Wrap text into lines with max_width chars, limited to max_lines."""
    lines = textwrap.wrap(text, width=max_width)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        # Truncate last line with ...
        if len(lines[-1]) > max_width - 3:
            lines[-1] = lines[-1][: max_width - 3] + "..."
        else:
            lines[-1] = lines[-1].rstrip() + "..."
    return lines


def generate_og_image(
    title: str,
    date_str: str,
    category: str,
    description: str,
    output_path: str,
) -> bool:
    """Generate a single OG image (1200x630px) and save to output_path.

    Returns True on success, False on failure.
    """
    if not _MPL_AVAILABLE:
        logger.error("matplotlib not available, cannot generate image")
        return False

    accent_color = CATEGORY_COLORS.get(category, DEFAULT_ACCENT)
    category_label = CATEGORY_LABELS.get(category, category)
    date_korean = format_date_korean(date_str)
    date_dotted = date_str.replace("-", ".")

    # Wrap title and description
    title_lines = wrap_text(title, max_width=28, max_lines=2)
    desc_lines = wrap_text(description, max_width=42, max_lines=2) if description else []

    # Create figure: 12x6.3 inches at 100 DPI = 1200x630 px
    fig = plt.figure(figsize=(12, 6.3), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1200)
    ax.set_ylim(0, 630)
    ax.set_axis_off()

    # Background
    bg_rect = mpatches.FancyBboxPatch(
        (0, 0), 1200, 630, boxstyle="square,pad=0", facecolor=BG_COLOR, edgecolor="none"
    )
    ax.add_patch(bg_rect)

    # Accent color bar at top (8px)
    accent_bar = mpatches.FancyBboxPatch(
        (0, 622), 1200, 8, boxstyle="square,pad=0", facecolor=accent_color, edgecolor="none"
    )
    ax.add_patch(accent_bar)

    # Branding: "INVESTING DRAGON"
    ax.text(
        60, 580, "INVESTING DRAGON",
        fontsize=14, color=TEXT_MUTED, fontweight="bold",
        ha="left", va="center", **_FK,
    )

    # Category badge
    badge_text = f"  {category_label}  "
    badge_x, badge_y = 60, 530
    badge_width = len(badge_text) * 11
    badge_rect = mpatches.FancyBboxPatch(
        (badge_x - 4, badge_y - 14),
        badge_width, 28,
        boxstyle="round,pad=4",
        facecolor=accent_color,
        edgecolor="none",
        alpha=0.9,
    )
    ax.add_patch(badge_rect)
    ax.text(
        badge_x + badge_width / 2 - 4, badge_y,
        category_label,
        fontsize=13, color=TEXT_WHITE, fontweight="bold",
        ha="center", va="center", **_FK,
    )

    # Title (large, bold, max 2 lines)
    title_y_start = 460
    for i, line in enumerate(title_lines):
        ax.text(
            60, title_y_start - i * 50,
            line,
            fontsize=32, color=TEXT_WHITE, fontweight="bold",
            ha="left", va="center", **_FK,
        )

    # Date in Korean format
    date_y = title_y_start - len(title_lines) * 50 - 10
    ax.text(
        60, date_y,
        date_korean,
        fontsize=15, color=TEXT_GRAY,
        ha="left", va="center", **_FK,
    )

    # Description (smaller, gray, max 2 lines)
    desc_y_start = date_y - 45
    for i, line in enumerate(desc_lines):
        ax.text(
            60, desc_y_start - i * 30,
            line,
            fontsize=14, color=TEXT_GRAY,
            ha="left", va="center", **_FK,
        )

    # Divider line
    divider_y = 70
    ax.plot(
        [60, 1140], [divider_y, divider_y],
        color=DIVIDER_COLOR, linewidth=1,
    )

    # Footer: site URL (left) and date (right)
    ax.text(
        60, 35,
        "investing.2twodragon.com",
        fontsize=13, color=TEXT_MUTED,
        ha="left", va="center", **_FK,
    )
    ax.text(
        1140, 35,
        date_dotted,
        fontsize=13, color=TEXT_MUTED,
        ha="right", va="center", **_FK,
    )

    # Subtle accent dot in bottom-right area
    accent_dot = mpatches.Circle(
        (1140, 580), 6, facecolor=accent_color, edgecolor="none", alpha=0.6
    )
    ax.add_patch(accent_dot)

    # Save
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    try:
        fig.savefig(
            output_path,
            dpi=100,
            facecolor=BG_COLOR,
            edgecolor="none",
            bbox_inches=None,
            pad_inches=0,
        )
        logger.info("Generated: %s", output_path)
        return True
    except OSError as e:
        logger.error("Failed to save %s: %s", output_path, e)
        return False
    finally:
        plt.close(fig)


def update_post_frontmatter(filepath: str, image_path: str) -> bool:
    """Update the image: field in a post's YAML front matter.

    Returns True if updated, False otherwise.
    """
    try:
        with open(filepath, encoding="utf-8") as f:
            content = f.read()
    except OSError as e:
        logger.warning("Cannot read %s: %s", filepath, e)
        return False

    # Check for existing image: line in front matter
    fm_match = re.match(r"^(---\s*\n)(.*?)(\n---)", content, re.DOTALL)
    if not fm_match:
        return False

    pre, fm_body, post = fm_match.group(1), fm_match.group(2), fm_match.group(3)
    rest = content[fm_match.end():]
    new_image_line = f'image: "{image_path}"'

    if re.search(r"^image:", fm_body, re.MULTILINE):
        new_fm = re.sub(r"^image:.*$", new_image_line, fm_body, flags=re.MULTILINE)
    else:
        new_fm = fm_body + "\n" + new_image_line

    new_content = pre + new_fm + post + rest

    if new_content == content:
        return False

    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(new_content)
        logger.info("Updated front matter: %s", filepath)
        return True
    except OSError as e:
        logger.error("Failed to write %s: %s", filepath, e)
        return False


def collect_posts(
    target_date: Optional[str] = None,
) -> List[Dict[str, str]]:
    """Collect posts from _posts/ directory.

    If target_date is provided (YYYY-MM-DD), only collect posts for that date.
    Returns list of dicts with keys: filepath, slug, date, title, category, description.
    """
    posts = []

    if not os.path.isdir(POSTS_DIR):
        logger.error("Posts directory not found: %s", POSTS_DIR)
        return posts

    for filename in sorted(os.listdir(POSTS_DIR)):
        if not filename.endswith(".md"):
            continue

        file_date = date_from_filename(filename)
        if not file_date:
            continue

        if target_date and file_date != target_date:
            continue

        filepath = os.path.join(POSTS_DIR, filename)
        fm = parse_front_matter(filepath)
        if not fm:
            logger.warning("No front matter in %s, skipping", filename)
            continue

        posts.append({
            "filepath": filepath,
            "slug": slug_from_filename(filename),
            "date": file_date,
            "title": fm.get("title", ""),
            "category": fm.get("categories", ""),
            "description": fm.get("description", ""),
        })

    return posts


def og_image_path(slug: str, date_str: str) -> str:
    """Build the output path for an OG image."""
    return os.path.join(IMAGES_DIR, f"og-{slug}-{date_str}.png")


def og_image_url(slug: str, date_str: str) -> str:
    """Build the Jekyll-relative URL for an OG image."""
    return f"/assets/images/generated/og-{slug}-{date_str}.png"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate OG images (1200x630) for Jekyll posts"
    )
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Generate OG images only for posts on this date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        dest="all_posts",
        help="Generate OG images for all posts",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing OG images",
    )
    parser.add_argument(
        "--update-frontmatter",
        action="store_true",
        help="Update each post's image: field to point to the generated OG image",
    )
    args = parser.parse_args()

    if not args.date and not args.all_posts:
        parser.error("Specify --date DATE or --all")

    if not _MPL_AVAILABLE:
        logger.error("matplotlib is required. Install with: pip install matplotlib")
        return

    posts = collect_posts(target_date=args.date)
    if not posts:
        logger.warning("No posts found%s", f" for date {args.date}" if args.date else "")
        return

    logger.info("Found %d post(s) to process", len(posts))

    generated = 0
    skipped = 0
    updated = 0

    for post in posts:
        out_path = og_image_path(post["slug"], post["date"])

        if os.path.exists(out_path) and not args.force:
            logger.debug("Exists, skipping: %s", out_path)
            skipped += 1
            continue

        ok = generate_og_image(
            title=post["title"],
            date_str=post["date"],
            category=post["category"],
            description=post["description"],
            output_path=out_path,
        )

        if ok:
            generated += 1
            if args.update_frontmatter:
                url = og_image_url(post["slug"], post["date"])
                if update_post_frontmatter(post["filepath"], url):
                    updated += 1

    logger.info(
        "Done: %d generated, %d skipped, %d front matter updated",
        generated, skipped, updated,
    )


if __name__ == "__main__":
    main()
