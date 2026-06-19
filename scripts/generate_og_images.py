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

# ── Theme colors (aligned with scripts/common/image_generator/base.py) ──
BG_COLOR = "#0d1117"
TEXT_WHITE = "#e6edf3"
TEXT_GRAY = "#9da5ae"
TEXT_MUTED = "#6b7280"
DIVIDER_COLOR = "#30363d"

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


def _discover_cjk_fonts() -> List[str]:
    """Return CJK font paths: static candidates + dynamic discovery."""
    candidates = [
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansKR-Regular.ttf",
        "/System/Library/Fonts/AppleSDGothicNeo.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
        "/System/Library/Fonts/Supplemental/AppleGothic.ttf",
    ]
    # Dynamic discovery for Ubuntu 24.04+ where paths may differ
    import glob as _gl
    import subprocess

    for pattern in [
        "/usr/share/fonts/**/NotoSansCJK*.*",
        "/usr/share/fonts/**/NotoSans*KR*.*",
        "/usr/share/fonts/**/Noto*CJK*.*",
    ]:
        candidates.extend(_gl.glob(pattern, recursive=True))
    # fc-list fallback
    try:
        _result = subprocess.run(
            ["fc-list", ":lang=ko", "-f", "%{file}\n"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        for _line in _result.stdout.strip().split("\n"):
            if _line and os.path.exists(_line):
                candidates.append(_line)
    except Exception as exc:
        logger.debug("fc-list fallback failed: %s", exc)
    # deduplicate while preserving order
    seen: set = set()
    unique: List[str] = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            unique.append(c)
    return unique


if _MPL_AVAILABLE:
    _korean_font_candidates = _discover_cjk_fonts()
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


def _draw_visual_crypto(ax, accent: str) -> None:
    """Draw rich candlestick chart with Bitcoin symbol and volume bars."""
    import numpy as np

    np.random.seed(42)
    cx, cy = 920, 310
    # Background glow layers
    ax.add_patch(mpatches.Circle((cx, cy), 240, facecolor=accent, edgecolor="none", alpha=0.08))
    ax.add_patch(mpatches.Circle((cx - 60, cy + 60), 120, facecolor="#f7931a", edgecolor="none", alpha=0.04))

    # Candlestick bars (16 bars for richer chart)
    opens = [200, 220, 210, 240, 230, 260, 250, 280, 270, 300, 290, 320, 310, 340, 330, 360]
    closes = [220, 210, 240, 230, 260, 250, 280, 270, 300, 290, 320, 310, 340, 330, 360, 390]
    for i, (o, c) in enumerate(zip(opens, closes, strict=False)):
        x = cx - 240 + i * 30
        is_up = c > o
        color = "#3fb950" if is_up else "#f85149"
        body_bot = min(o, c)
        body_h = abs(c - o)
        wick_lo = body_bot - np.random.randint(8, 22)
        wick_hi = max(o, c) + np.random.randint(8, 22)
        ax.plot([x, x], [cy + wick_lo - 200, cy + wick_hi - 200], color=color, linewidth=1.2, alpha=0.65)
        bar = mpatches.FancyBboxPatch(
            (x - 8, cy + body_bot - 200),
            16,
            max(body_h, 4),
            boxstyle="round,pad=1.5",
            facecolor=color,
            edgecolor="none",
            alpha=0.85,
        )
        ax.add_patch(bar)
        # Volume bars at bottom
        vol_h = np.random.randint(10, 40)
        ax.add_patch(
            mpatches.FancyBboxPatch(
                (x - 6, cy - 190),
                12,
                vol_h,
                boxstyle="round,pad=1",
                facecolor=color,
                edgecolor="none",
                alpha=0.3,
            )
        )

    # Bollinger band area
    xs_line = [cx - 240 + i * 30 for i in range(16)]
    mid = [cy + v - 200 for v in [210, 215, 225, 235, 245, 255, 265, 275, 285, 295, 305, 315, 325, 335, 345, 375]]
    upper = [y + 30 for y in mid]
    lower = [y - 30 for y in mid]
    from matplotlib.patches import Polygon

    band_verts = list(zip(xs_line, upper, strict=False)) + list(zip(reversed(xs_line), reversed(lower), strict=False))
    ax.add_patch(Polygon(band_verts, closed=True, facecolor=accent, alpha=0.06, edgecolor="none"))
    ax.plot(xs_line, mid, color=accent, linewidth=2, alpha=0.5)

    # Bitcoin / ETH text symbols
    ax.text(
        cx + 180,
        cy + 140,
        "BTC",
        fontsize=22,
        color="#f7931a",
        fontweight="bold",
        ha="center",
        va="center",
        alpha=0.25,
        **_FK,
    )
    ax.text(
        cx - 180,
        cy + 130,
        "ETH",
        fontsize=18,
        color="#627eea",
        fontweight="bold",
        ha="center",
        va="center",
        alpha=0.2,
        **_FK,
    )


def _draw_visual_stock(ax, accent: str, data: Optional[Dict] = None) -> None:
    """Draw rich area chart with multiple indicators and financial symbols."""
    import numpy as np

    cx, cy_base = 920, 140
    # Background glow
    ax.add_patch(mpatches.Circle((cx, 310), 200, facecolor=accent, edgecolor="none", alpha=0.05))

    xs = np.linspace(cx - 220, cx + 220, 60)
    np.random.seed(7)
    trend = np.linspace(0, 280, 60)
    noise = np.cumsum(np.random.randn(60) * 6)
    ys = cy_base + trend + noise
    ys = np.clip(ys, cy_base, cy_base + 360)

    # Gradient area fill (multiple layers for depth)
    from matplotlib.patches import Polygon

    for alpha_v, y_shift in [(0.15, 0), (0.08, -15), (0.03, -30)]:
        verts = list(zip(xs, ys + y_shift, strict=False)) + [(xs[-1], cy_base), (xs[0], cy_base)]
        ax.add_patch(Polygon(verts, closed=True, facecolor=accent, alpha=alpha_v, edgecolor="none"))

    # Main line
    ax.plot(xs, ys, color=accent, linewidth=2.8, alpha=0.85)
    # Moving averages
    for window, color, lw in [(10, "#22d3ee", 1.8), (20, "#d29922", 1.3)]:
        ma = np.convolve(ys, np.ones(window) / window, mode="valid")
        ax.plot(xs[window - 1 :], ma, color=color, linewidth=lw, alpha=0.45, linestyle="--")
    # Highlight last point with glow
    ax.add_patch(mpatches.Circle((xs[-1], ys[-1]), 14, facecolor=accent, edgecolor="none", alpha=0.2))
    ax.add_patch(mpatches.Circle((xs[-1], ys[-1]), 7, facecolor=accent, edgecolor=TEXT_WHITE, linewidth=1.5, alpha=0.9))

    # Volume bars at bottom
    np.random.seed(17)
    for i in range(0, 60, 2):
        vol = np.random.randint(8, 35)
        c = "#3fb950" if ys[i] > ys[max(0, i - 1)] else "#f85149"
        ax.add_patch(
            mpatches.FancyBboxPatch(
                (xs[i] - 3, cy_base - 5),
                6,
                vol,
                boxstyle="round,pad=1",
                facecolor=c,
                edgecolor="none",
                alpha=0.35,
            )
        )

    # Financial symbols
    ax.text(
        cx + 190,
        cy_base + 340,
        "$",
        fontsize=52,
        color="#3fb950",
        fontweight="bold",
        ha="center",
        va="center",
        alpha=0.15,
        **_FK,
    )
    ax.text(
        cx - 190,
        cy_base + 320,
        "₩",
        fontsize=38,
        color=accent,
        fontweight="bold",
        ha="center",
        va="center",
        alpha=0.12,
        **_FK,
    )
    # Mini KOSPI label
    kospi_label = "KOSPI"
    if data and data.get("kospi"):
        kospi_label = f"KOSPI {data['kospi']}"
    ax.text(
        cx + 140, cy_base + 280, kospi_label, fontsize=9, color=TEXT_MUTED, ha="center", va="center", alpha=0.4, **_FK
    )


def _draw_visual_analysis(ax, accent: str, data: Optional[Dict] = None) -> None:
    """Draw donut gauge with mini charts and indicator labels."""
    import numpy as np

    cx, cy = 920, 310
    # Background glow
    ax.add_patch(mpatches.Circle((cx, cy), 190, facecolor=accent, edgecolor="none", alpha=0.04))

    r_outer, r_inner = 130, 82
    segments = [
        (0, 72, "#f85149"),
        (72, 144, "#d29922"),
        (144, 216, "#8b949e"),
        (216, 288, "#58a6ff"),
        (288, 360, "#3fb950"),
    ]
    for start, end, color in segments:
        wedge = mpatches.Wedge(
            (cx, cy),
            r_outer,
            start,
            end,
            width=r_outer - r_inner,
            facecolor=color,
            edgecolor="none",
            alpha=0.75,
        )
        ax.add_patch(wedge)
    ax.add_patch(mpatches.Circle((cx, cy), r_inner - 4, facecolor=BG_COLOR, edgecolor="#334155", linewidth=1.5))
    # Use real Fear & Greed score if available, else fall back to hardcoded 62
    fg_score = data.get("fear_greed", 62.0) if data else 62.0
    # Map score 0-100 to gauge angle: 0 → 0°, 100 → 360° but gauge runs 0–360
    # Original hardcoded was 223° for score 62 → linear mapping: angle = score * 3.6
    gauge_angle_deg = fg_score * 3.6
    angle = np.radians(gauge_angle_deg)
    nx = cx + (r_inner + 20) * np.cos(angle)
    ny = cy + (r_inner + 20) * np.sin(angle)
    ax.annotate("", xy=(nx, ny), xytext=(cx, cy), arrowprops=dict(arrowstyle="-|>", color=TEXT_WHITE, lw=2.2))
    ax.add_patch(mpatches.Circle((cx, cy), 8, facecolor=TEXT_WHITE, edgecolor=BG_COLOR, linewidth=2))
    ax.text(
        cx,
        cy - 20,
        str(int(fg_score)),
        fontsize=30,
        color=TEXT_WHITE,
        fontweight="bold",
        ha="center",
        va="center",
        **_FK,
    )
    ax.text(cx, cy - 48, "/ 100", fontsize=10, color=TEXT_MUTED, ha="center", va="center", **_FK)

    # Mini sparklines around gauge
    np.random.seed(9)
    for x_off, y_off, c in [(-170, 130, "#3fb950"), (170, 130, "#f85149"), (-170, -80, "#58a6ff")]:
        sx = np.linspace(cx + x_off - 40, cx + x_off + 40, 15)
        sy = cy + y_off + np.cumsum(np.random.randn(15) * 4)
        ax.plot(sx, sy, color=c, linewidth=1.5, alpha=0.6)
        ax.add_patch(mpatches.Circle((sx[-1], sy[-1]), 3, facecolor=c, edgecolor="none", alpha=0.8))

    # Indicator labels
    for label, x_off, y_off, c in [
        ("RSI", -170, 150, "#3fb950"),
        ("MACD", 170, 150, "#f85149"),
        ("VOL", -170, -60, "#58a6ff"),
    ]:
        ax.text(
            cx + x_off,
            cy + y_off,
            label,
            fontsize=7,
            color=c,
            fontweight="bold",
            ha="center",
            va="center",
            alpha=0.5,
            **_FK,
        )


def _draw_visual_regulatory(ax, accent: str) -> None:
    """Draw balance scale with document icons, gavel, and regulation tags."""

    cx, cy = 920, 310
    ax.add_patch(mpatches.Circle((cx, cy), 240, facecolor=accent, edgecolor="none", alpha=0.07))

    # Pillar with gradient effect
    for i in range(5):
        ax.plot(
            [cx - i * 0.5, cx - i * 0.5],
            [cy - 130, cy + 110],
            color="#58a6ff",
            linewidth=3 - i * 0.4,
            alpha=0.6 - i * 0.1,
        )
    # Base pedestal
    ax.add_patch(
        mpatches.FancyBboxPatch(
            (cx - 50, cy - 150),
            100,
            25,
            boxstyle="round,pad=2",
            facecolor="#334155",
            edgecolor=accent,
            linewidth=1.2,
            alpha=0.5,
        )
    )
    # Beam with tilt
    beam_tilt = 8
    ax.plot([cx - 140, cx + 140], [cy + 80 + beam_tilt, cy + 80 - beam_tilt], color=accent, linewidth=4, alpha=0.7)
    # Left pan (heavier - lower)
    from matplotlib.patches import Polygon

    left_xs = [cx - 140, cx - 180, cx - 100]
    left_ys = [cy + 80 + beam_tilt, cy + 20 + beam_tilt, cy + 20 + beam_tilt]
    ax.add_patch(
        Polygon(
            list(zip(left_xs, left_ys, strict=False)),
            closed=True,
            facecolor=accent,
            alpha=0.25,
            edgecolor=accent,
            linewidth=1.2,
        )
    )
    # Document stack on left pan
    for j in range(3):
        ax.add_patch(
            mpatches.FancyBboxPatch(
                (cx - 168 + j * 8, cy - 5 + beam_tilt + j * 12),
                56,
                18,
                boxstyle="round,pad=1",
                facecolor=accent,
                alpha=0.3 - j * 0.05,
                edgecolor="none",
            )
        )
    ax.text(
        cx - 140,
        cy - 15 + beam_tilt,
        "SEC",
        fontsize=7,
        color=accent,
        fontweight="bold",
        ha="center",
        va="center",
        alpha=0.5,
        **_FK,
    )
    # Right pan
    right_xs = [cx + 140, cx + 100, cx + 180]
    right_ys = [cy + 80 - beam_tilt, cy + 20 - beam_tilt, cy + 20 - beam_tilt]
    ax.add_patch(
        Polygon(
            list(zip(right_xs, right_ys, strict=False)),
            closed=True,
            facecolor="#3fb950",
            alpha=0.25,
            edgecolor="#3fb950",
            linewidth=1.2,
        )
    )
    # Coin stack on right pan
    for j in range(4):
        ax.add_patch(
            mpatches.Circle(
                (cx + 140, cy - 10 - beam_tilt + j * 10),
                8,
                facecolor="#3fb950",
                edgecolor="#2ea043",
                linewidth=0.8,
                alpha=0.5 - j * 0.08,
            )
        )
    ax.text(
        cx + 140,
        cy - 25 - beam_tilt,
        "$",
        fontsize=9,
        color="#3fb950",
        fontweight="bold",
        ha="center",
        va="center",
        alpha=0.6,
        **_FK,
    )
    # Top circle (fulcrum)
    ax.add_patch(mpatches.Circle((cx, cy + 120), 22, facecolor=accent, edgecolor="none", alpha=0.4))
    ax.text(
        cx, cy + 120, "REG", fontsize=6, color=TEXT_WHITE, fontweight="bold", ha="center", va="center", alpha=0.7, **_FK
    )
    # Regulation tags
    tags = [
        ("MiCA", -180, 160, "#22d3ee"),
        ("KYC", -120, 175, "#bc8cff"),
        ("AML", 120, 175, "#d29922"),
        ("FATF", 180, 160, "#f85149"),
    ]
    for label, xo, yo, c in tags:
        ax.add_patch(
            mpatches.FancyBboxPatch(
                (cx + xo - 18, cy + yo - 8), 36, 16, boxstyle="round,pad=2", facecolor=c, edgecolor="none", alpha=0.2
            )
        )
        ax.text(
            cx + xo, cy + yo, label, fontsize=6, color=c, fontweight="bold", ha="center", va="center", alpha=0.5, **_FK
        )
    # Decorative rings
    for r in [160, 185]:
        ax.add_patch(mpatches.Circle((cx, cy + 40), r, facecolor="none", edgecolor=accent, linewidth=0.6, alpha=0.08))
    # Gavel icon top-right
    ax.plot([cx + 140, cx + 170], [cy + 130, cy + 145], color="#d29922", linewidth=3, alpha=0.4)
    ax.add_patch(
        mpatches.FancyBboxPatch(
            (cx + 160, cy + 138), 28, 14, boxstyle="round,pad=2", facecolor="#d29922", edgecolor="none", alpha=0.35
        )
    )


def _draw_visual_social(ax, accent: str) -> None:
    """Draw network graph with platform icons and sentiment waves."""
    import numpy as np

    cx, cy = 920, 310
    ax.add_patch(mpatches.Circle((cx, cy), 240, facecolor=accent, edgecolor="none", alpha=0.07))

    np.random.seed(3)
    nodes = [(cx + np.random.randint(-180, 180), cy + np.random.randint(-140, 140)) for _ in range(14)]
    colors = [
        accent,
        "#e91e63",
        "#22d3ee",
        "#bc8cff",
        "#3fb950",
        "#d29922",
        "#1da1f2",
        accent,
        "#e91e63",
        "#22d3ee",
        "#bc8cff",
        "#3fb950",
        "#d29922",
        "#1da1f2",
    ]
    sizes = [24, 18, 15, 22, 14, 16, 20, 12, 19, 13, 17, 15, 11, 16]
    edges = [
        (0, 1),
        (0, 3),
        (1, 2),
        (2, 5),
        (3, 4),
        (4, 6),
        (5, 7),
        (6, 8),
        (7, 9),
        (8, 10),
        (9, 11),
        (0, 6),
        (3, 7),
        (1, 5),
        (10, 12),
        (11, 13),
        (2, 13),
    ]
    for i, j in edges:
        if i < len(nodes) and j < len(nodes):
            ax.plot([nodes[i][0], nodes[j][0]], [nodes[i][1], nodes[j][1]], color="#475569", linewidth=1.0, alpha=0.3)
    for (nx, ny), color, size in zip(nodes, colors, sizes, strict=False):
        ax.add_patch(mpatches.Circle((nx, ny), size + 8, facecolor=color, edgecolor="none", alpha=0.08))
        ax.add_patch(mpatches.Circle((nx, ny), size, facecolor=color, edgecolor="none", alpha=0.7))

    # Sentiment wave at bottom
    wave_x = np.linspace(cx - 200, cx + 200, 50)
    wave_y = cy - 160 + 15 * np.sin(wave_x * 0.04) + 8 * np.sin(wave_x * 0.08)
    ax.plot(wave_x, wave_y, color=accent, linewidth=1.5, alpha=0.4)
    ax.plot(wave_x, wave_y + 12, color="#22d3ee", linewidth=1, alpha=0.3)

    # Platform hints
    for label, xo, yo, c in [("X", -160, 160, "#1da1f2"), ("Reddit", 160, 160, "#ff4500")]:
        ax.text(
            cx + xo, cy + yo, label, fontsize=9, color=c, fontweight="bold", ha="center", va="center", alpha=0.3, **_FK
        )


def _draw_visual_defi(ax, accent: str) -> None:
    """Draw interlocking protocol rings with TVL bars and token symbols."""
    import numpy as np

    cx, cy = 920, 310
    ax.add_patch(mpatches.Circle((cx, cy), 240, facecolor=accent, edgecolor="none", alpha=0.07))

    ring_specs = [
        (cx - 80, cy + 50, 65, accent, "AAVE"),
        (cx + 30, cy + 50, 65, "#22d3ee", "UNI"),
        (cx - 25, cy - 30, 65, "#bc8cff", "MKR"),
        (cx + 80, cy - 30, 65, "#3fb950", "LIDO"),
    ]
    for rx, ry, r, color, label in ring_specs:
        ax.add_patch(mpatches.Circle((rx, ry), r, facecolor="none", edgecolor=color, linewidth=3, alpha=0.55))
        ax.add_patch(mpatches.Circle((rx, ry), r - 6, facecolor=color, edgecolor="none", alpha=0.06))
        ax.text(rx, ry, label, fontsize=7, color=color, fontweight="bold", ha="center", va="center", alpha=0.5, **_FK)
    ax.add_patch(mpatches.Circle((cx, cy + 10), 20, facecolor=accent, edgecolor=TEXT_WHITE, linewidth=2, alpha=0.8))

    # TVL mini bars
    np.random.seed(13)
    bar_x = cx - 180
    for i, (h, c) in enumerate([(60, accent), (45, "#22d3ee"), (80, "#bc8cff"), (35, "#3fb950"), (55, "#d29922")]):
        ax.add_patch(
            mpatches.FancyBboxPatch(
                (bar_x + i * 22, cy - 170),
                16,
                h,
                boxstyle="round,pad=1",
                facecolor=c,
                edgecolor="none",
                alpha=0.45,
            )
        )
    ax.text(bar_x + 44, cy - 180, "TVL", fontsize=7, color=TEXT_MUTED, ha="center", va="top", alpha=0.4, **_FK)


def _draw_visual_political(ax, accent: str) -> None:
    """Draw political trades chart with buy/sell bars, capitol dome, and party indicators."""
    import numpy as np

    cx, cy = 920, 310
    ax.add_patch(mpatches.Circle((cx, cy), 240, facecolor=accent, edgecolor="none", alpha=0.07))

    cy_base = 160
    # Buy/sell paired bars (political insider trades)
    bar_pairs = [(120, -60), (180, -90), (140, -40), (220, -110), (160, -80), (200, -70), (130, -50), (190, -100)]
    bar_w = 18
    gap = 6
    total_w = len(bar_pairs) * (bar_w * 2 + gap)
    start_x = cx - total_w // 2

    for i, (buy_h, sell_h) in enumerate(bar_pairs):
        x = start_x + i * (bar_w * 2 + gap)
        # Buy bar (green, upward)
        ax.add_patch(
            mpatches.FancyBboxPatch(
                (x, cy_base), bar_w, buy_h, boxstyle="round,pad=1", facecolor="#3fb950", edgecolor="none", alpha=0.65
            )
        )
        # Sell bar (red, downward from baseline)
        ax.add_patch(
            mpatches.FancyBboxPatch(
                (x + bar_w, cy_base + sell_h),
                bar_w,
                abs(sell_h),
                boxstyle="round,pad=1",
                facecolor="#f85149",
                edgecolor="none",
                alpha=0.65,
            )
        )

    # Baseline
    ax.plot([start_x - 15, start_x + total_w + 15], [cy_base, cy_base], color="#475569", linewidth=1.5, alpha=0.5)
    # Labels
    ax.text(
        start_x - 20,
        cy_base + 10,
        "BUY",
        fontsize=6,
        color="#3fb950",
        fontweight="bold",
        ha="right",
        va="center",
        alpha=0.5,
        **_FK,
    )
    ax.text(
        start_x - 20,
        cy_base - 10,
        "SELL",
        fontsize=6,
        color="#f85149",
        fontweight="bold",
        ha="right",
        va="center",
        alpha=0.5,
        **_FK,
    )

    # Capitol dome silhouette (top area)
    dome_cx, dome_cy = cx, cy + 150
    # Dome arc
    theta = np.linspace(0, np.pi, 30)
    dome_x = dome_cx + 60 * np.cos(theta)
    dome_y = dome_cy + 35 * np.sin(theta)
    ax.plot(dome_x, dome_y, color=accent, linewidth=2, alpha=0.3)
    ax.fill_between(dome_x, dome_cy, dome_y, alpha=0.06, color=accent)
    # Pillars
    for px in [-50, -25, 0, 25, 50]:
        ax.plot([dome_cx + px, dome_cx + px], [dome_cy - 5, dome_cy + 5], color=accent, linewidth=1.5, alpha=0.2)
    # Base
    ax.plot([dome_cx - 65, dome_cx + 65], [dome_cy - 5, dome_cy - 5], color=accent, linewidth=1.5, alpha=0.25)

    # Party color indicators
    tags = [
        ("SEN", -170, 155, "#1e40af"),
        ("REP", -170, 135, "#dc2626"),
        ("$VOL", 170, 155, "#d29922"),
        ("TRADES", 170, 135, "#8b949e"),
    ]
    for label, xo, yo, c in tags:
        ax.text(
            cx + xo, cy + yo, label, fontsize=6, color=c, fontweight="bold", ha="center", va="center", alpha=0.4, **_FK
        )

    # Trend arrow
    ax.annotate(
        "",
        xy=(cx + 180, cy_base + 200),
        xytext=(cx + 180, cy_base + 120),
        arrowprops=dict(arrowstyle="->", color="#3fb950", lw=1.5, alpha=0.3),
    )


def _draw_visual_world(ax, accent: str) -> None:
    """Draw globe with trade routes, market hotspots, and regional index labels."""
    import numpy as np
    from matplotlib.patches import Arc

    cx, cy = 920, 310
    # Globe outline with glow
    for r_off, a in [(8, 0.03), (4, 0.06)]:
        ax.add_patch(mpatches.Circle((cx, cy), 150 + r_off, facecolor=accent, edgecolor="none", alpha=a))
    ax.add_patch(mpatches.Circle((cx, cy), 150, facecolor="none", edgecolor=accent, linewidth=2.5, alpha=0.4))
    ax.add_patch(mpatches.Circle((cx, cy), 150, facecolor=accent, edgecolor="none", alpha=0.04))

    # Latitude lines
    for lat in [-80, -40, 0, 40, 80]:
        r = 150 * np.cos(np.radians(lat))
        y_off = 150 * np.sin(np.radians(lat)) * 0.4
        if r > 10:
            arc = Arc(
                (cx, cy + y_off),
                r * 2,
                r * 0.4,
                angle=0,
                theta1=0,
                theta2=360,
                edgecolor=accent,
                linewidth=0.8,
                alpha=0.2,
            )
            ax.add_patch(arc)
    # Longitude lines
    for lon in range(0, 180, 30):
        arc = Arc(
            (cx, cy), 300, 300 * 0.9, angle=lon, theta1=0, theta2=180, edgecolor=accent, linewidth=0.6, alpha=0.15
        )
        ax.add_patch(arc)

    # Market hotspots with labels (major financial centers)
    hotspots = [
        (-80, 40, 12, "#3fb950", "NYSE"),  # New York
        (-40, 60, 10, "#22d3ee", "LSE"),  # London
        (60, 55, 10, "#f85149", "SSE"),  # Shanghai
        (80, 45, 11, "#bc8cff", "KOSPI"),  # Seoul
        (85, 50, 9, "#d29922", "NIKKEI"),  # Tokyo
        (-20, 10, 8, "#3fb950", "JSE"),  # Johannesburg
        (45, 30, 8, "#22d3ee", "BSE"),  # Mumbai
        (-60, -20, 7, "#d29922", "B3"),  # Sao Paulo
    ]
    for angle_deg, dist_pct, size, color, label in hotspots:
        angle = np.radians(angle_deg)
        dist = 150 * dist_pct / 100
        px = cx + dist * np.cos(angle)
        py = cy + dist * np.sin(angle) * 0.7
        # Pulse ring
        ax.add_patch(mpatches.Circle((px, py), size + 6, facecolor=color, edgecolor="none", alpha=0.1))
        ax.add_patch(mpatches.Circle((px, py), size, facecolor=color, edgecolor="none", alpha=0.55))
        ax.text(
            px,
            py - size - 5,
            label,
            fontsize=5,
            color=color,
            fontweight="bold",
            ha="center",
            va="top",
            alpha=0.5,
            **_FK,
        )

    # Trade route arcs connecting hotspots
    route_pairs = [(0, 1), (1, 2), (2, 3), (3, 4), (0, 7), (1, 5), (2, 6)]
    np.random.seed(11)
    for i, j in route_pairs:
        h1 = hotspots[i]
        h2 = hotspots[j]
        a1, d1 = np.radians(h1[0]), 150 * h1[1] / 100
        a2, d2 = np.radians(h2[0]), 150 * h2[1] / 100
        x1, y1 = cx + d1 * np.cos(a1), cy + d1 * np.sin(a1) * 0.7
        x2, y2 = cx + d2 * np.cos(a2), cy + d2 * np.sin(a2) * 0.7
        ax.annotate(
            "",
            xy=(x2, y2),
            xytext=(x1, y1),
            arrowprops=dict(arrowstyle="-", color=accent, lw=0.8, alpha=0.15, connectionstyle="arc3,rad=0.3"),
        )

    # Global index tickers around the globe
    tickers = [
        ("S&P", -185, 10, "#3fb950"),
        ("FTSE", -170, 90, "#22d3ee"),
        ("DAX", 170, 90, "#d29922"),
        ("HSI", 185, 10, "#f85149"),
    ]
    for label, xo, yo, c in tickers:
        ax.text(
            cx + xo, cy + yo, label, fontsize=6, color=c, fontweight="bold", ha="center", va="center", alpha=0.35, **_FK
        )


def _draw_visual_security(ax, accent: str) -> None:
    """Draw shield with lock, binary rain, threat indicators, and security labels."""
    import numpy as np
    from matplotlib.patches import Polygon

    cx, cy = 920, 310
    ax.add_patch(mpatches.Circle((cx, cy), 240, facecolor=accent, edgecolor="none", alpha=0.07))

    # Binary rain background
    np.random.seed(42)
    for _ in range(40):
        bx = cx + np.random.randint(-190, 190)
        by = cy + np.random.randint(-170, 170)
        bit = str(np.random.randint(0, 2))
        ax.text(
            bx, by, bit, fontsize=6, color=accent, alpha=np.random.uniform(0.05, 0.15), ha="center", va="center", **_FK
        )

    # Shield shape with glow
    shield_pts = [
        (cx, cy + 165),
        (cx - 125, cy + 112),
        (cx - 145, cy - 20),
        (cx - 82, cy - 105),
        (cx, cy - 145),
        (cx + 82, cy - 105),
        (cx + 145, cy - 20),
        (cx + 125, cy + 112),
    ]
    # Outer glow
    shield_glow = [(x + (x - cx) * 0.08, y + (y - cy) * 0.08) for x, y in shield_pts]
    ax.add_patch(Polygon(shield_glow, closed=True, facecolor=accent, alpha=0.05, edgecolor="none"))
    # Main shield
    ax.add_patch(Polygon(shield_pts, closed=True, facecolor=accent, alpha=0.12, edgecolor=accent, linewidth=2.5))
    # Inner shield
    inner = [
        (cx, cy + 125),
        (cx - 88, cy + 82),
        (cx - 104, cy - 12),
        (cx - 58, cy - 74),
        (cx, cy - 104),
        (cx + 58, cy - 74),
        (cx + 104, cy - 12),
        (cx + 88, cy + 82),
    ]
    ax.add_patch(
        Polygon(inner, closed=True, facecolor=accent, alpha=0.08, edgecolor=accent, linewidth=1.2, linestyle="--")
    )

    # Lock icon (shackle + body)
    ax.add_patch(mpatches.Circle((cx, cy + 32), 28, facecolor="none", edgecolor=TEXT_WHITE, linewidth=2.5, alpha=0.6))
    ax.add_patch(
        mpatches.FancyBboxPatch(
            (cx - 38, cy - 42),
            76,
            55,
            boxstyle="round,pad=3",
            facecolor=accent,
            edgecolor=TEXT_WHITE,
            linewidth=1.5,
            alpha=0.5,
        )
    )
    # Keyhole
    ax.add_patch(mpatches.Circle((cx, cy - 18), 8, facecolor=TEXT_WHITE, edgecolor="none", alpha=0.6))
    ax.plot([cx, cx], [cy - 18, cy - 35], color=TEXT_WHITE, linewidth=2.5, alpha=0.5)

    # Threat level indicator (top-right)
    threat_colors = ["#3fb950", "#3fb950", "#d29922", "#d29922", "#f85149"]
    for i, tc in enumerate(threat_colors):
        ax.add_patch(
            mpatches.FancyBboxPatch(
                (cx + 155, cy + 130 - i * 14),
                28,
                10,
                boxstyle="round,pad=1",
                facecolor=tc,
                edgecolor="none",
                alpha=0.4 if i < 3 else 0.7,
            )
        )
    ax.text(
        cx + 169,
        cy + 145,
        "THREAT",
        fontsize=5,
        color=TEXT_MUTED,
        fontweight="bold",
        ha="center",
        va="bottom",
        alpha=0.4,
        **_FK,
    )

    # Security labels
    labels = [
        ("2FA", -175, 140, "#3fb950"),
        ("SSL", -175, 120, "#22d3ee"),
        ("AUDIT", 175, -80, "#bc8cff"),
        ("CVE", 175, -100, "#f85149"),
    ]
    for label, xo, yo, c in labels:
        ax.add_patch(
            mpatches.FancyBboxPatch(
                (cx + xo - 20, cy + yo - 7), 40, 14, boxstyle="round,pad=2", facecolor=c, edgecolor="none", alpha=0.15
            )
        )
        ax.text(
            cx + xo, cy + yo, label, fontsize=6, color=c, fontweight="bold", ha="center", va="center", alpha=0.5, **_FK
        )

    # Checkmark in shield center-top
    ax.text(
        cx,
        cy + 80,
        "SECURE",
        fontsize=7,
        color=TEXT_WHITE,
        fontweight="bold",
        ha="center",
        va="center",
        alpha=0.4,
        **_FK,
    )


def _draw_visual_blockchain(ax, accent: str) -> None:
    """Draw blockchain network visual with connected blocks and hash patterns."""
    import numpy as np

    cx, cy = 920, 310
    np.random.seed(42)
    ax.add_patch(mpatches.Circle((cx, cy), 240, facecolor=accent, edgecolor="none", alpha=0.07))

    # Draw chain of 5 blocks connected by lines (shifted left to avoid clipping)
    block_positions = [
        (cx - 180, cy + 80),
        (cx - 90, cy + 80),
        (cx, cy + 80),
        (cx + 90, cy + 80),
        (cx + 180, cy + 80),
    ]

    # Connection lines between blocks
    for i in range(len(block_positions) - 1):
        x1, y1 = block_positions[i]
        x2, y2 = block_positions[i + 1]
        ax.plot([x1 + 35, x2 - 5], [y1, y2], color=accent, linewidth=2.5, alpha=0.6)

    # Draw blocks
    for i, (bx, by) in enumerate(block_positions):
        alpha = 0.9 - i * 0.12
        ax.add_patch(
            mpatches.FancyBboxPatch(
                (bx - 5, by - 22),
                40,
                44,
                boxstyle="round,pad=4",
                facecolor="#161b22",
                edgecolor=accent,
                linewidth=1.8,
                alpha=alpha,
            )
        )
        ax.text(
            bx + 15,
            by + 8,
            f"#{i + 1}",
            fontsize=8,
            color=TEXT_GRAY,
            ha="center",
            va="center",
            fontweight="bold",
            **_FK,
        )
        # Hash pattern inside block
        ax.text(
            bx + 15,
            by - 8,
            "0x" + format(np.random.randint(0, 0xFFFF), "04x"),
            fontsize=5,
            color=accent,
            ha="center",
            va="center",
            alpha=0.5,
            **_FK,
        )

    # Network nodes below blocks (centered within visual area)
    node_colors = ["#3fb950", "#f7931a", "#627eea", "#e91e63", "#22d3ee", "#7c4dff"]
    node_positions = [
        (cx - 140, cy - 60),
        (cx - 20, cy - 80),
        (cx + 100, cy - 60),
        (cx - 80, cy - 130),
        (cx + 40, cy - 130),
        (cx + 160, cy - 100),
    ]

    # Network edges
    edges = [(0, 1), (1, 2), (0, 3), (1, 4), (2, 5), (3, 4), (4, 5)]
    for a, b in edges:
        x1, y1 = node_positions[a]
        x2, y2 = node_positions[b]
        ax.plot([x1, x2], [y1, y2], color="#334155", linewidth=1.2, alpha=0.4)

    for i, (nx, ny) in enumerate(node_positions):
        size = np.random.randint(8, 16)
        ax.add_patch(
            mpatches.Circle((nx, ny), size, facecolor=node_colors[i % len(node_colors)], edgecolor="none", alpha=0.7)
        )

    # Labels
    for label, x_off, y_off, c in [
        ("BTC", -120, 160, "#f7931a"),
        ("ETH", 120, 160, "#627eea"),
        ("HASH", 0, -160, accent),
    ]:
        ax.text(
            cx + x_off,
            cy + y_off,
            label,
            fontsize=8,
            color=c,
            fontweight="bold",
            ha="center",
            va="center",
            alpha=0.5,
            **_FK,
        )


def _draw_visual_economic_calendar(ax, accent: str) -> None:
    """Draw economic calendar visual with event timeline and importance indicators."""
    import numpy as np

    cx, cy = 920, 310
    np.random.seed(7)
    ax.add_patch(mpatches.Circle((cx, cy), 240, facecolor=accent, edgecolor="none", alpha=0.07))

    # Calendar grid (4x3)
    grid_x, grid_y = cx - 150, cy + 50
    cell_w, cell_h = 65, 45
    for row in range(3):
        for col in range(4):
            x = grid_x + col * (cell_w + 8)
            y = grid_y - row * (cell_h + 8)
            alpha = 0.15 + np.random.random() * 0.25
            color = ["#3fb950", "#f85149", "#d29922", "#58a6ff"][np.random.randint(0, 4)]
            ax.add_patch(
                mpatches.FancyBboxPatch(
                    (x, y),
                    cell_w,
                    cell_h,
                    boxstyle="round,pad=3",
                    facecolor=color,
                    edgecolor="none",
                    alpha=alpha,
                )
            )
            # Day number
            day = row * 4 + col + 1
            ax.text(
                x + cell_w / 2,
                y + cell_h / 2,
                str(day),
                fontsize=11,
                color=TEXT_WHITE,
                ha="center",
                va="center",
                fontweight="bold",
                alpha=0.7,
                **_FK,
            )

    # Importance indicator bars on the right
    bar_x = cx + 160
    for i, (label, h, color) in enumerate(
        [
            ("HIGH", 55, "#f85149"),
            ("MED", 40, "#d29922"),
            ("LOW", 25, "#3fb950"),
        ]
    ):
        bar_y = cy + 90 - i * 75
        ax.add_patch(
            mpatches.FancyBboxPatch(
                (bar_x, bar_y),
                28,
                h,
                boxstyle="round,pad=2",
                facecolor=color,
                edgecolor="none",
                alpha=0.7,
            )
        )
        ax.text(
            bar_x + 14,
            bar_y - 12,
            label,
            fontsize=6,
            color=color,
            ha="center",
            va="center",
            fontweight="bold",
            alpha=0.6,
            **_FK,
        )

    # Timeline arrow at bottom
    ax.annotate(
        "", xy=(cx + 200, cy - 140), xytext=(cx - 200, cy - 140), arrowprops=dict(arrowstyle="-|>", color=accent, lw=2)
    )
    for i in range(6):
        tx = cx - 170 + i * 72
        ax.add_patch(mpatches.Circle((tx, cy - 140), 4, facecolor=accent, edgecolor="none", alpha=0.8))
        ax.plot([tx, tx], [cy - 140, cy - 120 + np.random.randint(-15, 15)], color=accent, linewidth=1.5, alpha=0.4)

    # Labels
    ax.text(
        cx - 150,
        cy + 150,
        "ECON",
        fontsize=9,
        color=accent,
        fontweight="bold",
        ha="left",
        va="center",
        alpha=0.5,
        **_FK,
    )
    ax.text(
        cx + 150,
        cy + 150,
        "CAL",
        fontsize=9,
        color="#d29922",
        fontweight="bold",
        ha="right",
        va="center",
        alpha=0.5,
        **_FK,
    )


def _draw_visual_default(ax, accent: str) -> None:
    """Draw a daily summary dashboard with market overview heat tiles and performance bars."""
    import numpy as np

    cx, cy = 920, 310
    np.random.seed(5)
    ax.add_patch(mpatches.Circle((cx, cy), 240, facecolor=accent, edgecolor="none", alpha=0.07))

    # Market heatmap grid (3x4 tiles)
    tile_colors = [
        "#3fb950",
        "#f85149",
        "#3fb950",
        "#d29922",
        "#f85149",
        "#3fb950",
        "#58a6ff",
        "#f85149",
        "#d29922",
        "#3fb950",
        "#f85149",
        "#3fb950",
    ]
    tile_labels = ["BTC", "ETH", "SOL", "XRP", "AAPL", "TSLA", "NVDA", "MSFT", "KOSPI", "S&P", "GOLD", "OIL"]
    tile_w, tile_h = 62, 50
    for i in range(12):
        row, col = divmod(i, 4)
        x = cx - 145 + col * (tile_w + 8)
        y = cy + 75 - row * (tile_h + 8)
        intensity = 0.15 + np.random.random() * 0.35
        ax.add_patch(
            mpatches.FancyBboxPatch(
                (x, y),
                tile_w,
                tile_h,
                boxstyle="round,pad=3",
                facecolor=tile_colors[i],
                edgecolor="none",
                alpha=intensity,
            )
        )
        ax.text(
            x + tile_w / 2,
            y + tile_h / 2 + 5,
            tile_labels[i],
            fontsize=7,
            color=TEXT_WHITE,
            ha="center",
            va="center",
            fontweight="bold",
            alpha=0.8,
            **_FK,
        )
        # Mini change indicator
        change = np.random.uniform(-5, 5)
        sign = "+" if change > 0 else ""
        ax.text(
            x + tile_w / 2,
            y + tile_h / 2 - 10,
            f"{sign}{change:.1f}%",
            fontsize=5,
            color=tile_colors[i],
            ha="center",
            va="center",
            alpha=0.6,
            **_FK,
        )

    # Sentiment bar at bottom
    bar_y = cy - 120
    bar_w = 280
    for ratio, color in [(0.45, "#3fb950"), (0.30, "#8b949e"), (0.25, "#f85149")]:
        w = bar_w * ratio
        ax.add_patch(
            mpatches.FancyBboxPatch(
                (cx - 140, bar_y),
                w,
                18,
                boxstyle="round,pad=2",
                facecolor=color,
                edgecolor="none",
                alpha=0.65,
            )
        )
        ax.text(
            cx - 140 + w / 2,
            bar_y + 9,
            f"{int(ratio * 100)}%",
            fontsize=6,
            color=TEXT_WHITE,
            ha="center",
            va="center",
            fontweight="bold",
            **_FK,
        )
    ax.text(cx - 140, bar_y - 14, "BULLISH", fontsize=6, color="#3fb950", ha="left", va="center", alpha=0.5, **_FK)
    ax.text(cx + 140, bar_y - 14, "BEARISH", fontsize=6, color="#f85149", ha="right", va="center", alpha=0.5, **_FK)

    # Date frame
    ax.text(
        cx,
        cy + 155,
        "DAILY OVERVIEW",
        fontsize=9,
        color=accent,
        fontweight="bold",
        ha="center",
        va="center",
        alpha=0.6,
        **_FK,
    )


def _draw_visual_geopolitical(ax, accent: str) -> None:
    """Draw geopolitical risk visual with radar chart and risk zones."""
    import numpy as np

    cx, cy = 920, 310
    ax.add_patch(mpatches.Circle((cx, cy), 240, facecolor=accent, edgecolor="none", alpha=0.07))

    # Radar/hexagon shape for multi-factor risk
    n_axes = 6
    angles = np.linspace(0, 2 * np.pi, n_axes, endpoint=False)
    r_max = 130
    # Concentric rings
    for r_frac in [0.33, 0.66, 1.0]:
        r = r_max * r_frac
        pts = [(cx + r * np.cos(a), cy + r * np.sin(a)) for a in angles]
        pts.append(pts[0])
        xs, ys = zip(*pts, strict=False)
        ax.plot(xs, ys, color=accent, linewidth=0.8, alpha=0.2)
    # Axis lines
    for a in angles:
        ax.plot(
            [cx, cx + r_max * np.cos(a)],
            [cy, cy + r_max * np.sin(a)],
            color="#475569",
            linewidth=0.7,
            alpha=0.25,
        )
    # Risk polygon fill
    np.random.seed(77)
    risk_vals = [0.5, 0.8, 0.6, 0.9, 0.4, 0.7]
    from matplotlib.patches import Polygon

    risk_pts = [
        (cx + r_max * v * np.cos(a), cy + r_max * v * np.sin(a)) for v, a in zip(risk_vals, angles, strict=False)
    ]
    ax.add_patch(Polygon(risk_pts, closed=True, facecolor=accent, alpha=0.15, edgecolor=accent, linewidth=2))
    # Risk dots
    for (rx, ry), v in zip(risk_pts, risk_vals, strict=False):
        c = "#f85149" if v > 0.7 else "#d29922" if v > 0.5 else "#3fb950"
        ax.add_patch(mpatches.Circle((rx, ry), 6, facecolor=c, edgecolor="none", alpha=0.8))

    # Axis labels
    risk_labels = ["TRADE", "CONFLICT", "SANCTION", "ENERGY", "POLICY", "ALLIANCE"]
    for label, a in zip(risk_labels, angles, strict=False):
        lx = cx + (r_max + 22) * np.cos(a)
        ly = cy + (r_max + 22) * np.sin(a)
        ax.text(
            lx, ly, label, fontsize=6, color=TEXT_MUTED, fontweight="bold", ha="center", va="center", alpha=0.45, **_FK
        )

    # Alert badge
    ax.add_patch(
        mpatches.FancyBboxPatch(
            (cx + 140, cy + 140),
            50,
            20,
            boxstyle="round,pad=2",
            facecolor="#f85149",
            edgecolor="none",
            alpha=0.7,
        )
    )
    ax.text(
        cx + 165,
        cy + 150,
        "ALERT",
        fontsize=7,
        color=TEXT_WHITE,
        fontweight="bold",
        ha="center",
        va="center",
        alpha=0.9,
        **_FK,
    )


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
