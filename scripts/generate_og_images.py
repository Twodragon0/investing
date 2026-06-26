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
import sys
import textwrap
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

try:
    from PIL import Image as PILImage

    _PIL_AVAILABLE = True
except ImportError:
    _PIL_AVAILABLE = False

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

sys.path.insert(0, SCRIPT_DIR)
from common import asset_storage  # noqa: E402  (sys.path 설정 후 import)
from common.og_render import (  # noqa: E402  (sys.path 설정 후 import)
    _FK,
    _MPL_AVAILABLE,
    BG_COLOR,
    DIVIDER_COLOR,
    TEXT_GRAY,
    TEXT_MUTED,
    TEXT_WHITE,
    mpatches,
    plt,
)
from common.og_visuals import (  # noqa: E402,F401  (재-export: og.<name> 레지스트리/테스트 호환)
    _draw_visual_analysis,
    _draw_visual_blockchain,
    _draw_visual_crypto,
    _draw_visual_default,
    _draw_visual_defi,
    _draw_visual_economic_calendar,
    _draw_visual_geopolitical,
    _draw_visual_political,
    _draw_visual_regulatory,
    _draw_visual_security,
    _draw_visual_social,
    _draw_visual_stock,
    _draw_visual_world,
)

# ── Category colors ──
CATEGORY_COLORS: Dict[str, str] = {
    "crypto-news": "#f7931a",
    "stock-news": "#10b981",
    "crypto-trading-journal": "#14b8a6",
    "stock-trading-journal": "#22c55e",
    "market-analysis": "#3b82f6",
    "regulatory-news": "#06b6d4",
    "social-media": "#f43f5e",
    "defi": "#8b5cf6",
    "political-trades": "#f97316",
    "worldmonitor": "#14b8a6",
    "security": "#ef4444",
    "security-alerts": "#ef4444",
    "geopolitical": "#f59e0b",
    "daily-summary": "#eab308",
    "blockchain": "#6366f1",
}
DEFAULT_ACCENT = "#64748b"

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
    "security-alerts": "보안",
    "geopolitical": "지정학",
    "daily-summary": "일일요약",
    "blockchain": "블록체인",
}


def _convert_to_webp(png_path: str, quality: int = 85) -> bool:
    """Convert a PNG file to WebP format alongside the original."""
    if not _PIL_AVAILABLE:
        return False
    webp_path = re.sub(r"\.png$", ".webp", png_path)
    try:
        with PILImage.open(png_path) as img:
            img.save(webp_path, "WEBP", quality=quality, method=4)
        logger.info("Converted to WebP: %s", webp_path)
        return True
    except (OSError, ValueError) as e:
        logger.warning("WebP conversion failed for %s: %s", png_path, e)
        return False


def _convert_to_avif(png_path: str, quality: int = 50) -> bool:
    """Convert a PNG file to AVIF format alongside the original."""
    if not _PIL_AVAILABLE:
        return False
    avif_path = re.sub(r"\.png$", ".avif", png_path)
    try:
        with PILImage.open(png_path) as img:
            img.save(avif_path, "AVIF", quality=quality)
        logger.info("Converted to AVIF: %s", avif_path)
        return True
    except (OSError, ValueError) as e:
        logger.warning("AVIF conversion failed for %s: %s", png_path, e)
        return False


def _convert_formats_parallel(png_path: str, webp_quality: int = 82) -> None:
    """Convert PNG to WebP and AVIF in parallel using threads."""
    with ThreadPoolExecutor(max_workers=2) as pool:
        pool.submit(_convert_to_webp, png_path, webp_quality)
        pool.submit(_convert_to_avif, png_path)


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
        "journal_mode",
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


def _extract_metrics(description: str) -> List[tuple]:
    """Extract key metrics from post description for data overlay.

    Returns list of (label, value, color) tuples, max 3 items.
    """
    metrics: List[tuple] = []
    if not description:
        return metrics

    # BTC price
    m = re.search(r"BTC\s*\$?([\d,]+)", description)
    if m:
        metrics.append(("BTC", f"${m.group(1)}", "#f7931a"))

    # Fear & Greed
    m = re.search(r"(?:공포[·.]?탐욕|Fear.*Greed)[^:]*[:：]?\s*(\d+(?:\.\d+)?)\s*/?\s*100", description)
    if m:
        val = float(m.group(1))
        color = "#ef4444" if val < 30 else "#eab308" if val < 60 else "#10b981"
        metrics.append(("F&G", f"{m.group(1)}", color))

    # KOSPI
    m = re.search(r"KOSPI\s*([\d,.]+)\s*\(([^)]+)\)", description)
    if m:
        change = m.group(2)
        color = "#10b981" if "+" in change else "#ef4444"
        metrics.append(("KOSPI", f"{m.group(1)}", color))

    # VIX
    m = re.search(r"VIX\s*([\d.]+)", description)
    if m:
        val = float(m.group(1))
        color = "#ef4444" if val > 25 else "#eab308" if val > 18 else "#10b981"
        metrics.append(("VIX", m.group(1), color))

    # DXY / dollar index
    m = re.search(r"(?:달러지수|DXY)\s*([\d.]+)", description)
    if m:
        metrics.append(("DXY", m.group(1), "#3b82f6"))

    # News count
    m = re.search(r"(\d+)건\s*수집", description)
    if m:
        metrics.append(("NEWS", f"{m.group(1)}건", "#8b5cf6"))

    return metrics[:3]


def _draw_data_chips(ax, metrics: List[tuple], accent: str) -> None:
    """Draw data metric chips at the bottom-right of the visual area."""
    if not metrics:
        return
    chip_y = 120
    chip_x_start = 780
    chip_spacing = 140

    for i, (label, value, color) in enumerate(metrics):
        x = chip_x_start + i * chip_spacing
        # Chip background
        ax.add_patch(
            mpatches.FancyBboxPatch(
                (x, chip_y - 15),
                120,
                42,
                boxstyle="round,pad=4",
                facecolor=color,
                edgecolor="none",
                alpha=0.15,
            )
        )
        # Label
        ax.text(
            x + 60,
            chip_y + 16,
            label,
            fontsize=7,
            color=color,
            fontweight="bold",
            ha="center",
            va="center",
            alpha=0.7,
            **_FK,
        )
        # Value
        ax.text(
            x + 60,
            chip_y - 2,
            value,
            fontsize=12,
            color=TEXT_WHITE,
            fontweight="bold",
            ha="center",
            va="center",
            **_FK,
        )


# Category -> visual drawing function
_CATEGORY_VISUALS = {
    "crypto-news": _draw_visual_crypto,
    "stock-news": _draw_visual_stock,
    "market-analysis": _draw_visual_analysis,
    "regulatory-news": _draw_visual_regulatory,
    "social-media": _draw_visual_social,
    "defi": _draw_visual_defi,
    "political-trades": _draw_visual_political,
    "worldmonitor": _draw_visual_world,
    "security": _draw_visual_security,
    "security-alerts": _draw_visual_security,
    "geopolitical": _draw_visual_geopolitical,
    "daily-summary": _draw_visual_default,
    "blockchain": _draw_visual_blockchain,
}


def generate_og_image(
    title: str,
    date_str: str,
    category: str,
    description: str,
    output_path: str,
) -> bool:
    """Generate a single OG image (1200x630px) and save to output_path.

    Visual-first design: large category-specific chart/graphic on the right,
    minimal text (title + category + date) on the left.

    Returns True on success, False on failure.
    """
    if not _MPL_AVAILABLE:
        logger.error("matplotlib not available, cannot generate image")
        return False

    accent_color = CATEGORY_COLORS.get(category, DEFAULT_ACCENT)
    category_label = CATEGORY_LABELS.get(category, category)
    date_dotted = date_str.replace("-", ".")

    # Multi-line title support (up to 2 lines, wider for Korean readability)
    title_lines = wrap_text(safe_text(title), max_width=26, max_lines=2)
    # Description lines (up to 2 lines below title)
    desc_text = description if description else ""
    desc_lines = wrap_text(safe_text(desc_text), max_width=34, max_lines=2) if desc_text else []

    fig = plt.figure(figsize=(12, 6.3), dpi=150)
    ax = fig.add_axes((0, 0, 1, 1))
    ax.set_xlim(0, 1200)
    ax.set_ylim(0, 630)
    ax.set_axis_off()

    # Background
    bg_rect = mpatches.FancyBboxPatch((0, 0), 1200, 630, boxstyle="square,pad=0", facecolor=BG_COLOR, edgecolor="none")
    ax.add_patch(bg_rect)

    # Ambient glows (enhanced for SNS impact)
    for cx, cy, radius, alpha, color in [
        (160, 520, 240, 0.12, accent_color),
        (900, 300, 320, 0.08, accent_color),
        (1050, 520, 180, 0.05, "#22d3ee"),
        (600, 315, 400, 0.03, accent_color),
    ]:
        ax.add_patch(mpatches.Circle((cx, cy), radius, facecolor=color, edgecolor="none", alpha=alpha))

    # Subtle grid
    for y in range(70, 590, 64):
        ax.plot([48, 1152], [y, y], color="#334155", linewidth=0.6, alpha=0.08)
    for x in range(80, 1125, 170):
        ax.plot([x, x], [54, 576], color="#334155", linewidth=0.6, alpha=0.05)

    # Top accent bar
    ax.add_patch(
        mpatches.FancyBboxPatch(
            (0, 620),
            1200,
            10,
            boxstyle="square,pad=0",
            facecolor=accent_color,
            edgecolor="none",
        )
    )

    # Outer frame
    ax.add_patch(
        mpatches.FancyBboxPatch(
            (34, 34),
            1132,
            562,
            boxstyle="round,pad=0.012,rounding_size=24",
            facecolor="none",
            edgecolor="#334155",
            linewidth=1.0,
            alpha=0.35,
        )
    )

    # === Visual element (right side) ===
    # Slug-based visual override for posts sharing the same category
    _SLUG_VISUAL_OVERRIDES = {
        "fmp-economic-calendar": _draw_visual_economic_calendar,
        "blockchain-network": _draw_visual_blockchain,
        "geopolitical": _draw_visual_geopolitical,
    }
    slug = os.path.basename(output_path).replace(".png", "").replace(".webp", "")
    for slug_key, visual_fn in _SLUG_VISUAL_OVERRIDES.items():
        if slug_key in slug:
            draw_fn = visual_fn
            break
    else:
        draw_fn = _CATEGORY_VISUALS.get(category, _draw_visual_default)

    # Extract dynamic data for visual functions from description
    visual_data: Dict[str, Any] = {}
    if description:
        fg_match = re.search(
            r"(?:공포[·.]?탐욕|[Ff]ear.*[Gg]reed)[^:]*[:：]?\s*(\d+(?:\.\d+)?)\s*/?\s*100",
            description,
        )
        if fg_match:
            visual_data["fear_greed"] = float(fg_match.group(1))
        kospi_match = re.search(r"KOSPI\s*([\d,.]+)", description)
        if kospi_match:
            visual_data["kospi"] = kospi_match.group(1)
        btc_match = re.search(r"BTC\s*\$?([\d,]+)", description)
        if btc_match:
            visual_data["btc_price"] = btc_match.group(1)

    import inspect

    if "data" in inspect.signature(draw_fn).parameters:
        draw_fn(ax, accent_color, data=visual_data)  # pyright: ignore[reportCallIssue]
    else:
        draw_fn(ax, accent_color)

    # === Data chips overlay (dynamic metrics from description) ===
    metrics = _extract_metrics(description)
    _draw_data_chips(ax, metrics, accent_color)

    # === Left side: rich text layout (Safe Zone 80px for SNS preview) ===
    LM = 80  # left margin (safe zone for KakaoTalk/Twitter)

    # Brand
    ax.text(LM, 560, "INVESTING DRAGON", fontsize=13, color="#7dd3fc", fontweight="bold", ha="left", va="center", **_FK)

    # Category badge
    badge_width = max(len(category_label) * 12, 80)
    ax.add_patch(
        mpatches.FancyBboxPatch(
            (LM - 4, 484),
            badge_width,
            36,
            boxstyle="round,pad=4",
            facecolor=accent_color,
            edgecolor="none",
            alpha=0.85,
        )
    )
    ax.text(
        LM - 4 + badge_width / 2,
        502,
        category_label,
        fontsize=14,
        color=TEXT_WHITE,
        fontweight="bold",
        ha="center",
        va="center",
        **_FK,
    )

    # Title (multi-line, large - 32pt for SNS impact)
    title_y = 410
    for idx, line in enumerate(title_lines):
        ax.text(
            LM,
            title_y - idx * 46,
            line,
            fontsize=32,
            color=TEXT_WHITE,
            fontweight="bold",
            ha="left",
            va="center",
            **_FK,
        )

    # Date
    date_y = title_y - len(title_lines) * 46 - 10
    ax.text(LM, date_y, date_dotted, fontsize=14, color=TEXT_GRAY, ha="left", va="center", **_FK)

    # Description (2 lines below date, alpha=0.7 for visual hierarchy)
    if desc_lines:
        desc_start_y = date_y - 35
        for idx, line in enumerate(desc_lines):
            ax.text(
                LM,
                desc_start_y - idx * 24,
                line,
                fontsize=13,
                color=TEXT_GRAY,
                ha="left",
                va="center",
                alpha=0.7,
                **_FK,
            )

    # Vertical accent line
    accent_line_bottom = date_y - 35 - len(desc_lines) * 24 if desc_lines else date_y - 20
    ax.plot([LM - 4, LM - 4], [max(accent_line_bottom, 200), 510], color=accent_color, linewidth=3, alpha=0.5)

    # Footer
    ax.plot([LM, 1140], [88, 88], color=DIVIDER_COLOR, linewidth=0.8)
    ax.text(LM, 48, "investing.2twodragon.com", fontsize=12, color=TEXT_GRAY, ha="left", va="center", **_FK)
    ax.text(1140, 48, date_dotted, fontsize=12, color=TEXT_GRAY, ha="right", va="center", **_FK)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    try:
        fig.savefig(output_path, dpi=150, facecolor=BG_COLOR, edgecolor="none", bbox_inches=None, pad_inches=0)
        logger.info("Generated: %s", output_path)
        _convert_formats_parallel(output_path, webp_quality=82)
        asset_storage.mirror_generated_variants(output_path)
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

    fig = plt.figure(figsize=(12, 6.3), dpi=150)
    ax = fig.add_axes((0, 0, 1, 1))
    ax.set_xlim(0, 1200)
    ax.set_ylim(0, 630)
    ax.set_axis_off()

    bg_rect = mpatches.FancyBboxPatch((0, 0), 1200, 630, boxstyle="square,pad=0", facecolor=BG_COLOR, edgecolor="none")
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

    journal_mode = post.get("journal_mode", "")
    if journal_mode == "live":
        mode_color, mode_label = "#16a34a", "LIVE"
    elif journal_mode == "paper":
        mode_color, mode_label = "#2563eb", "PAPER"
    else:
        mode_color, mode_label = "", ""
    if mode_label:
        ax.add_patch(
            mpatches.FancyBboxPatch(
                (270, 530),
                76,
                26,
                boxstyle="round,pad=0,rounding_size=13",
                facecolor=mode_color,
                edgecolor="none",
                alpha=0.95,
            )
        )
        ax.text(308, 543, mode_label, fontsize=11, color="#ffffff", fontweight="bold", ha="center", va="center", **_FK)

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
        fig.savefig(output_path, dpi=150, facecolor=BG_COLOR, edgecolor="none", bbox_inches=None, pad_inches=0)
        logger.info("Generated journal OG: %s", output_path)
        _convert_formats_parallel(output_path, webp_quality=88)
        asset_storage.mirror_generated_variants(output_path)
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
    allowed_categories: Optional[List[str]] = None,
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

        category = fm.get("categories", "")
        if allowed_categories and category not in allowed_categories:
            continue

        posts.append(
            {
                "filepath": filepath,
                "slug": slug_from_filename(filename),
                "date": file_date,
                "title": fm.get("title", ""),
                "category": category,
                "description": fm.get("description", ""),
                "excerpt": fm.get("excerpt", ""),
                "permalink": fm.get("permalink", ""),
                "journal_mode": fm.get("journal_mode", ""),
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


def thumb_image_path(slug: str, date_str: str) -> str:
    """Build the output path for a thumbnail image.

    Mirrors generate_thumbnail()'s naming: thumb- prefix on the og image basename.
    """
    return os.path.join(IMAGES_DIR, f"thumb-og-{slug}-{date_str}.png")


def thumb_image_url(slug: str, date_str: str) -> str:
    """Build the Jekyll-relative URL for a thumbnail image."""
    return f"/assets/images/generated/thumb-og-{slug}-{date_str}.png"


def generate_thumbnail(png_path: str) -> bool:
    """Generate a 600x315 thumbnail from an existing OG image PNG.

    Saves as thumb-{same-name}.png in the same directory, then converts
    to WebP and AVIF using _convert_formats_parallel.
    """
    if not _PIL_AVAILABLE:
        logger.warning("Pillow not available; cannot generate thumbnail for %s", png_path)
        return False
    if not os.path.exists(png_path):
        logger.warning("Source OG image not found: %s", png_path)
        return False

    basename = os.path.basename(png_path)
    thumb_name = f"thumb-{basename}"
    thumb_path = os.path.join(os.path.dirname(png_path), thumb_name)

    try:
        with PILImage.open(png_path) as img:
            thumb = img.resize((600, 315), PILImage.Resampling.LANCZOS)
            thumb.save(thumb_path, "PNG")
        logger.info("Thumbnail saved: %s", thumb_path)
        _convert_formats_parallel(thumb_path)
        asset_storage.mirror_generated_variants(thumb_path)
        return True
    except (OSError, ValueError) as e:
        logger.warning("Thumbnail generation failed for %s: %s", png_path, e)
        return False


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
    parser.add_argument(
        "--category",
        action="append",
        dest="categories",
        default=None,
        help="Restrict generation to specific categories (repeatable)",
    )
    parser.add_argument(
        "--thumbnails-only",
        action="store_true",
        help="Only regenerate thumbnails from existing OG images",
    )
    args = parser.parse_args()

    if not args.date and not args.all_posts:
        parser.error("Specify --date DATE or --all")

    posts = collect_posts(target_date=args.date, allowed_categories=args.categories)
    if not posts:
        logger.warning("No posts found%s", f" for date {args.date}" if args.date else "")
        return

    logger.info("Found %d post(s) to process", len(posts))

    # --thumbnails-only: resize existing OG images without re-rendering charts
    if args.thumbnails_only:
        thumbs = 0
        for post in posts:
            og_path = og_image_path(post["slug"], post["date"])
            if generate_thumbnail(og_path):
                thumbs += 1
        logger.info("Done: %d thumbnail(s) generated", thumbs)
        return

    if not _MPL_AVAILABLE:
        logger.error("matplotlib is required. Install with: pip install matplotlib")
        return

    generated = 0
    skipped = 0
    updated = 0

    for post in posts:
        out_path = og_image_path(post["slug"], post["date"])
        thumb_path = thumb_image_path(post["slug"], post["date"])
        og_exists = os.path.exists(out_path)
        thumb_exists = os.path.exists(thumb_path)

        if og_exists and thumb_exists and not args.force:
            logger.debug("Exists, skipping: %s", out_path)
            skipped += 1
            continue

        if og_exists and not args.force:
            # Backfill missing thumbnail without regenerating the og image.
            generate_thumbnail(out_path)
            generated += 1
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
            # Generate card thumbnail
            generate_thumbnail(out_path)
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
