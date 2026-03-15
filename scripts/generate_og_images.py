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
    "crypto-trading-journal": "#14b8a6",
    "stock-trading-journal": "#22c55e",
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
    "crypto-trading-journal": "Crypto Trading Journal",
    "stock-trading-journal": "Stock Trading Journal",
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
_MPL_AVAILABLE = False
matplotlib: Any = None
fm: Any = None
mpatches: Any = None
plt: Any = None
try:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.font_manager as fm
    import matplotlib.patches as mpatches
    import matplotlib.pyplot as plt

    _MPL_AVAILABLE = True
except ImportError:
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
    matplotlib.rcParams["text.parse_math"] = False

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

    for key in (
        "title",
        "date",
        "description",
        "excerpt",
        "image",
        "permalink",
        "categories",
        "journal_market_regime",
        "journal_confidence",
        "journal_risk_posture",
        "journal_day_result",
        "journal_trade_count",
        "journal_win_rate",
        "journal_realized_pnl",
        "journal_next_focus",
    ):
        pattern = rf"^{key}:\s*(.+)$"
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


def safe_text(text: str) -> str:
    """Escape characters that matplotlib may interpret as math text."""
    return text.replace("$", r"\$")


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

    title_lines = wrap_text(safe_text(title), max_width=28, max_lines=2)
    desc_lines = wrap_text(safe_text(description), max_width=42, max_lines=2) if description else []

    fig = plt.figure(figsize=(12, 6.3), dpi=100)
    ax = fig.add_axes((0, 0, 1, 1))
    ax.set_xlim(0, 1200)
    ax.set_ylim(0, 630)
    ax.set_axis_off()

    bg_rect = mpatches.FancyBboxPatch((0, 0), 1200, 630, boxstyle="square,pad=0", facecolor=BG_COLOR, edgecolor="none")
    ax.add_patch(bg_rect)

    for cx, cy, radius, alpha, color in [
        (170, 560, 160, 0.10, accent_color),
        (1080, 110, 190, 0.07, accent_color),
        (980, 520, 120, 0.04, "#22d3ee"),
    ]:
        glow = mpatches.Circle((cx, cy), radius, facecolor=color, edgecolor="none", alpha=alpha)
        ax.add_patch(glow)

    for y in range(70, 590, 64):
        ax.plot([48, 1152], [y, y], color="#334155", linewidth=0.8, alpha=0.12)
    for x in range(80, 1125, 170):
        ax.plot([x, x], [54, 576], color="#334155", linewidth=0.8, alpha=0.08)

    accent_bar = mpatches.FancyBboxPatch(
        (0, 620), 1200, 10, boxstyle="square,pad=0", facecolor=accent_color, edgecolor="none"
    )
    ax.add_patch(accent_bar)

    frame = mpatches.FancyBboxPatch(
        (34, 34),
        1132,
        562,
        boxstyle="round,pad=0.012,rounding_size=24",
        facecolor="none",
        edgecolor="#334155",
        linewidth=1.2,
        alpha=0.45,
    )
    ax.add_patch(frame)

    header_panel = mpatches.FancyBboxPatch(
        (52, 488),
        1096,
        86,
        boxstyle="round,pad=0.012,rounding_size=22",
        facecolor="#0f1724",
        edgecolor="#243447",
        linewidth=1.0,
        alpha=0.98,
    )
    ax.add_patch(header_panel)

    ax.text(60, 580, "INVESTING DRAGON", fontsize=14, color="#7dd3fc", fontweight="bold", ha="left", va="center", **_FK)
    ax.text(60, 554, "Market intelligence briefing", fontsize=12, color=TEXT_GRAY, ha="left", va="center", **_FK)

    badge_text = f"  {category_label}  "
    badge_x, badge_y = 60, 516
    badge_width = len(badge_text) * 11
    badge_rect = mpatches.FancyBboxPatch(
        (badge_x - 4, badge_y - 14),
        badge_width,
        30,
        boxstyle="round,pad=4",
        facecolor=accent_color,
        edgecolor="none",
        alpha=0.9,
    )
    ax.add_patch(badge_rect)
    ax.text(
        badge_x + badge_width / 2 - 4,
        badge_y,
        category_label,
        fontsize=13,
        color=TEXT_WHITE,
        fontweight="bold",
        ha="center",
        va="center",
        **_FK,
    )

    title_y_start = 420
    for i, line in enumerate(title_lines):
        ax.text(
            60,
            title_y_start - i * 50,
            line,
            fontsize=34,
            color=TEXT_WHITE,
            fontweight="bold",
            ha="left",
            va="center",
            **_FK,
        )

    date_y = title_y_start - len(title_lines) * 50 - 6
    ax.text(60, date_y, date_korean, fontsize=15, color=TEXT_GRAY, ha="left", va="center", **_FK)

    desc_y_start = date_y - 46
    for i, line in enumerate(desc_lines):
        ax.text(60, desc_y_start - i * 30, line, fontsize=14, color=TEXT_GRAY, ha="left", va="center", **_FK)

    side_panel = mpatches.FancyBboxPatch(
        (860, 140),
        256,
        278,
        boxstyle="round,pad=0.012,rounding_size=20",
        facecolor="#111b2a",
        edgecolor="#243447",
        linewidth=1.0,
        alpha=0.98,
    )
    ax.add_patch(side_panel)
    ax.text(892, 384, "BRIEF", fontsize=11, color=TEXT_MUTED, fontweight="bold", ha="left", va="center", **_FK)
    ax.text(892, 344, category_label, fontsize=22, color=TEXT_WHITE, fontweight="bold", ha="left", va="center", **_FK)
    ax.text(892, 308, date_dotted, fontsize=13, color=TEXT_GRAY, ha="left", va="center", **_FK)
    ax.plot([892, 1084], [284, 284], color="#243447", linewidth=1.0)
    ax.text(892, 248, "Signal", fontsize=10, color=TEXT_MUTED, fontweight="bold", ha="left", va="center", **_FK)
    ax.text(892, 220, "High-conviction market context", fontsize=13, color=TEXT_WHITE, ha="left", va="center", **_FK)
    ax.text(892, 176, "investing.2twodragon.com", fontsize=11, color=TEXT_GRAY, ha="left", va="center", **_FK)

    divider_y = 88
    ax.plot([60, 1140], [divider_y, divider_y], color=DIVIDER_COLOR, linewidth=1)
    ax.text(60, 48, "investing.2twodragon.com", fontsize=13, color=TEXT_MUTED, ha="left", va="center", **_FK)
    ax.text(1140, 48, date_dotted, fontsize=13, color=TEXT_MUTED, ha="right", va="center", **_FK)

    accent_dot = mpatches.Circle((1116, 544), 8, facecolor=accent_color, edgecolor="none", alpha=0.7)
    ax.add_patch(accent_dot)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    try:
        fig.savefig(output_path, dpi=100, facecolor=BG_COLOR, edgecolor="none", bbox_inches=None, pad_inches=0)
        logger.info("Generated: %s", output_path)
        return True
    except OSError as e:
        logger.error("Failed to save %s: %s", output_path, e)
        return False
    finally:
        plt.close(fig)


def _journal_term_to_en(text: str) -> str:
    mapping = {
        "변동성 확대": "Volatility Up",
        "반등 시도": "Rebound Attempt",
        "중간": "Medium",
        "높음": "High",
        "낮음": "Low",
        "포지션 축소": "Risk Trim",
        "선별 매수": "Selective Long",
        "관망": "Wait & See",
    }
    return mapping.get(text, text)


def generate_trading_journal_og_image(post: Dict[str, str], output_path: str) -> bool:
    if not _MPL_AVAILABLE:
        logger.error("matplotlib not available, cannot generate image")
        return False

    category = post.get("category", "")
    accent_color = CATEGORY_COLORS.get(category, DEFAULT_ACCENT)
    board_title = "Crypto Trading Journal" if category == "crypto-trading-journal" else "Stock Trading Journal"
    subtitle = "Session Board / Execution Review"
    date_str = post.get("date", "")
    date_dotted = date_str.replace("-", ".")

    metrics = [
        ("DAY RESULT", post.get("journal_day_result", "-")),
        ("TRADES", post.get("journal_trade_count", "-")),
        ("WIN RATE", post.get("journal_win_rate", "-")),
        ("REALIZED", post.get("journal_realized_pnl", "-")),
    ]
    regime = _journal_term_to_en(post.get("journal_market_regime", "-") or "-")
    confidence = _journal_term_to_en(post.get("journal_confidence", "-") or "-")
    risk_posture = _journal_term_to_en(post.get("journal_risk_posture", "-") or "-")
    next_focus = post.get("journal_next_focus", "Stay disciplined.") or "Stay disciplined."
    desc = post.get("excerpt") or post.get("description") or "Execution notes, PnL and next session focus."
    desc_lines = wrap_text(safe_text(desc), max_width=48, max_lines=3)

    fig = plt.figure(figsize=(12, 6.3), dpi=100)
    ax = fig.add_axes((0, 0, 1, 1))
    ax.set_xlim(0, 1200)
    ax.set_ylim(0, 630)
    ax.set_axis_off()

    bg_rect = mpatches.FancyBboxPatch((0, 0), 1200, 630, boxstyle="square,pad=0", facecolor="#0a0f18", edgecolor="none")
    ax.add_patch(bg_rect)
    for cx, cy, radius, alpha, color in [
        (180, 540, 180, 0.14, accent_color),
        (1040, 120, 210, 0.1, "#38bdf8"),
        (980, 510, 120, 0.05, "#ffffff"),
    ]:
        ax.add_patch(mpatches.Circle((cx, cy), radius, facecolor=color, edgecolor="none", alpha=alpha))

    for y in range(84, 570, 58):
        ax.plot([56, 1144], [y, y], color="#203042", linewidth=0.8, alpha=0.14)
    for x in range(80, 1120, 160):
        ax.plot([x, x], [60, 580], color="#203042", linewidth=0.7, alpha=0.1)

    ax.add_patch(
        mpatches.FancyBboxPatch(
            (40, 40),
            1120,
            550,
            boxstyle="round,pad=0.02,rounding_size=28",
            facecolor="none",
            edgecolor="#2a3b4e",
            linewidth=1.2,
            alpha=0.55,
        )
    )
    ax.add_patch(
        mpatches.FancyBboxPatch(
            (60, 454),
            1080,
            108,
            boxstyle="round,pad=0.03,rounding_size=24",
            facecolor="#101926",
            edgecolor="#243447",
            linewidth=1.0,
            alpha=0.98,
        )
    )

    ax.text(78, 542, "INVESTING DRAGON", fontsize=13, color="#7dd3fc", fontweight="bold", ha="left", va="center", **_FK)
    ax.text(78, 504, board_title, fontsize=28, color=TEXT_WHITE, fontweight="bold", ha="left", va="center", **_FK)
    ax.text(78, 474, f"{subtitle}  |  {date_dotted}", fontsize=12, color="#94a3b8", ha="left", va="center", **_FK)

    pill_specs = [
        (860, 516, 112, 30, f"REGIME {regime}"),
        (978, 516, 98, 30, f"CONF {confidence}"),
        (1082, 516, 38, 30, risk_posture[:3].upper()),
    ]
    for x, y, w, h, label in pill_specs:
        ax.add_patch(
            mpatches.FancyBboxPatch(
                (x, y),
                w,
                h,
                boxstyle="round,pad=0.25,rounding_size=14",
                facecolor="#132334",
                edgecolor="#2a4966",
                linewidth=0.9,
            )
        )
        ax.text(
            x + w / 2, y + h / 2, label, fontsize=9, color="#cbd5e1", fontweight="bold", ha="center", va="center", **_FK
        )

    card_x_positions = [78, 342, 606, 870]
    for (label, value), x in zip(metrics, card_x_positions, strict=False):
        ax.add_patch(
            mpatches.FancyBboxPatch(
                (x, 350),
                220,
                84,
                boxstyle="round,pad=0.03,rounding_size=18",
                facecolor="#111b28",
                edgecolor="#25364a",
                linewidth=1.0,
                alpha=0.98,
            )
        )
        ax.text(x + 18, 406, label, fontsize=9, color="#7c8ea5", fontweight="bold", ha="left", va="center", **_FK)
        ax.text(
            x + 18,
            374,
            value,
            fontsize=22,
            color=TEXT_WHITE if label != "DAY RESULT" else accent_color,
            fontweight="bold",
            ha="left",
            va="center",
            **_FK,
        )

    ax.add_patch(
        mpatches.FancyBboxPatch(
            (78, 120),
            598,
            196,
            boxstyle="round,pad=0.03,rounding_size=22",
            facecolor="#101926",
            edgecolor="#243447",
            linewidth=1.0,
            alpha=0.98,
        )
    )
    ax.text(
        102, 286, "SESSION TAKEAWAY", fontsize=10, color="#7c8ea5", fontweight="bold", ha="left", va="center", **_FK
    )
    for idx, line in enumerate(desc_lines):
        ax.text(102, 246 - idx * 30, line, fontsize=15, color="#e2e8f0", ha="left", va="center", **_FK)

    ax.add_patch(
        mpatches.FancyBboxPatch(
            (704, 120),
            436,
            196,
            boxstyle="round,pad=0.03,rounding_size=22",
            facecolor="#111c2a",
            edgecolor="#243447",
            linewidth=1.0,
            alpha=0.98,
        )
    )
    ax.text(728, 286, "NEXT SESSION", fontsize=10, color="#7c8ea5", fontweight="bold", ha="left", va="center", **_FK)
    next_lines = wrap_text(safe_text(next_focus), max_width=28, max_lines=4)
    for idx, line in enumerate(next_lines):
        ax.text(728, 246 - idx * 28, line, fontsize=14, color="#f8fafc", ha="left", va="center", **_FK)

    ax.plot([78, 1122], [92, 92], color=DIVIDER_COLOR, linewidth=1)
    ax.text(78, 58, "investing.2twodragon.com", fontsize=12, color=TEXT_MUTED, ha="left", va="center", **_FK)
    ax.text(1122, 58, date_dotted, fontsize=12, color=TEXT_MUTED, ha="right", va="center", **_FK)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    try:
        fig.savefig(output_path, dpi=100, facecolor="#0a0f18", edgecolor="none", bbox_inches=None, pad_inches=0)
        logger.info("Generated journal OG: %s", output_path)
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
    rest = content[fm_match.end() :]
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

        posts.append(
            {
                "filepath": filepath,
                "slug": slug_from_filename(filename),
                "date": file_date,
                "title": fm.get("title", ""),
                "category": fm.get("categories", ""),
                "description": fm.get("description", ""),
                "excerpt": fm.get("excerpt", ""),
                "permalink": fm.get("permalink", ""),
                "journal_market_regime": fm.get("journal_market_regime", ""),
                "journal_confidence": fm.get("journal_confidence", ""),
                "journal_risk_posture": fm.get("journal_risk_posture", ""),
                "journal_day_result": fm.get("journal_day_result", ""),
                "journal_trade_count": fm.get("journal_trade_count", ""),
                "journal_win_rate": fm.get("journal_win_rate", ""),
                "journal_realized_pnl": fm.get("journal_realized_pnl", ""),
                "journal_next_focus": fm.get("journal_next_focus", ""),
            }
        )

    return posts


def og_image_path(slug: str, date_str: str) -> str:
    """Build the output path for an OG image."""
    return os.path.join(IMAGES_DIR, f"og-{slug}-{date_str}.png")


def og_image_url(slug: str, date_str: str) -> str:
    """Build the Jekyll-relative URL for an OG image."""
    return f"/assets/images/generated/og-{slug}-{date_str}.png"


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate OG images (1200x630) for Jekyll posts")
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

        if post["category"] in {"crypto-trading-journal", "stock-trading-journal"}:
            ok = generate_trading_journal_og_image(post, out_path)
        else:
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
        generated,
        skipped,
        updated,
    )


if __name__ == "__main__":
    main()
