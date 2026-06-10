"""Common infrastructure for image generation.

Shared constants, font setup, color palette, design system, and utility functions
used by all image generator modules.
"""

import logging
import os
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Import matplotlib once at module level
_MPL_AVAILABLE = False
plt: Any = None
mpatches: Any = None
fm: Any = None
np: Any = None
_FONT_FAMILY = "monospace"
_FONT_STACK = [_FONT_FAMILY]
_HAS_EMOJI_FONT = False
try:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.font_manager as fm
    import matplotlib.patches as mpatches
    import matplotlib.pyplot as plt
    import numpy as np

    _MPL_AVAILABLE = True

    # Configure Korean/CJK font support
    _FONT_FAMILY = "monospace"
    _korean_font_candidates = [
        # Linux (CI: Ubuntu)
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansKR-Regular.ttf",
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
        "/usr/share/fonts/truetype/fonts-nanum/NanumGothic.ttf",
        # macOS
        "/System/Library/Fonts/AppleSDGothicNeo.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
        "/System/Library/Fonts/Supplemental/AppleGothic.ttf",
    ]
    for _fp in _korean_font_candidates:
        if os.path.exists(_fp):
            fm.fontManager.addfont(_fp)
            _prop = fm.FontProperties(fname=_fp)
            _FONT_FAMILY = _prop.get_name()
            logger.info("Using font '%s' for CJK support", _FONT_FAMILY)
            break
    else:
        logger.warning(
            "No CJK font found. Korean text will render as □□□. "
            "Install: apt-get install fonts-noto-cjk (Linux) or check system fonts (macOS)"
        )

    def _is_font_usable(path: str) -> bool:
        try:
            font = fm.get_font(path)
            font.set_size(12)
            return True
        except Exception:
            return False

    _emoji_font_candidates = [
        "/System/Library/Fonts/Apple Color Emoji.ttc",
        "/System/Library/Fonts/Supplemental/Apple Color Emoji.ttc",
        "/Library/Fonts/NotoColorEmoji.ttf",
        "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",
        "/usr/share/fonts/truetype/noto/NotoEmoji-Regular.ttf",
    ]
    _emoji_fonts = []
    for _fp in _emoji_font_candidates:
        if os.path.exists(_fp) and _is_font_usable(_fp):
            fm.fontManager.addfont(_fp)
            _prop = fm.FontProperties(fname=_fp)
            _name = _prop.get_name()
            if _name not in _emoji_fonts:
                _emoji_fonts.append(_name)

    _FONT_STACK = [_FONT_FAMILY] + _emoji_fonts if _emoji_fonts else [_FONT_FAMILY]
    matplotlib.rcParams["font.family"] = _FONT_STACK
    _FONT_FAMILY = _FONT_STACK
    if _emoji_fonts:
        logger.info("Using emoji fallback fonts: %s", ", ".join(_emoji_fonts))
        _HAS_EMOJI_FONT = True
except ImportError:
    logger.warning("matplotlib/numpy not available, image generation disabled")

# Shorthand for font kwarg used throughout
_FK = {"fontfamily": _FONT_STACK} if _MPL_AVAILABLE else {}

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
IMAGES_DIR = os.path.join(REPO_ROOT, "assets", "images", "generated")


def _get_pkg_attr(name: str):
    """Look up an attribute from the package module (supports monkeypatching).

    Tests may patch attributes on ``common.image_generator`` (the package).
    Sub-modules must read mutable settings through this helper so that
    monkeypatched values are visible at call time.
    """
    import sys

    pkg = sys.modules.get("common.image_generator")
    if pkg is not None and name in pkg.__dict__:
        return pkg.__dict__[name]
    # Fallback to this module's own globals
    return globals()[name]


# Korean-to-English mapping for image text (CI has no CJK fonts)
_KO_TO_EN = {
    # generate_daily_summary.py _cross_asset_topics()
    "금리/유동성": "Rates/Liquidity",
    "환율/달러": "FX/Dollar",
    "정책/규제": "Policy/Regulation",
    "리스크 이벤트": "Risk Events",
    "수급/심리": "Supply/Sentiment",
    "실적/지표": "Earnings/Indicators",
    # summarizer.py THEMES
    "규제/정책": "Regulation/Policy",
    "비트코인": "Bitcoin",
    "이더리움": "Ethereum",
    "AI/기술": "AI/Tech",
    "매크로/금리": "Macro/Rates",
    "거래소": "Exchange",
    "보안/해킹": "Security/Hacking",
    "정치/정책": "Politics/Policy",
    "가격/시장": "Price/Market",
    # collect_coinmarketcap.py
    "공포/탐욕": "Fear/Greed",
    "시장지배력": "Market Dominance",
    # generate_daily_summary.py category names
    "암호화폐": "Crypto",
    "주식": "Stock",
    "소셜 미디어": "Social Media",
    "소셜": "Social",
    "월드모니터": "WorldMonitor",
    "정치인 거래": "Political Trades",
    "보안": "Security",
    "NFT/Web3": "NFT/Web3",
    # collect_stock_news.py market snapshot names
    "다우존스": "Dow Jones",
    "다우존스 ETF": "Dow Jones ETF",
    "원/달러": "USD/KRW",
    # S&P 500 sector ETF names
    "금융": "Financials",
    "부동산": "Real Estate",
    "산업재": "Industrials",
    "기술": "Technology",
    "통신": "Communication",
    "소비재(필수)": "Cons. Staples",
    "소비재(임의)": "Cons. Discret.",
    "헬스케어": "Health Care",
    "에너지": "Energy",
    "소재": "Materials",
    "유틸리티": "Utilities",
    # worldmonitor themes
    "사회/기타": "Society/Other",
    "지정학/안보": "Geopolitics/Security",
    "금융시장": "Financial Markets",
    "기타 지정학": "Other Geopolitics",
    "정책/법률": "Policy/Law",
    "경제/통상": "Economy/Trade",
    "기술/과학": "Tech/Science",
    "환경/기후": "Environment/Climate",
    "보건/의료": "Health/Medical",
    "문화/사회": "Culture/Society",
    # geopolitical
    "지정학": "Geopolitics",
    "안보": "Security",
    "분쟁": "Conflict",
    "무역": "Trade",
    "외교": "Diplomacy",
    # common standalone terms
    "법률": "Law",
    "정책": "Policy",
    "경제": "Economy",
    "통상": "Trade Policy",
    "기후": "Climate",
    "과학": "Science",
}


def _to_en(text: str) -> str:
    """Translate Korean text to English for image rendering."""
    if text in _KO_TO_EN:
        return _KO_TO_EN[text]
    # If text contains any Hangul, try partial match or return as-is

    if re.search(r"[\uac00-\ud7af]", text):
        # Longest match first to avoid partial replacements
        for ko, en in sorted(_KO_TO_EN.items(), key=lambda x: len(x[0]), reverse=True):
            if ko in text:
                return text.replace(ko, en)
        return text
    return text


def _filter_en_keywords(keywords: list) -> list:
    """Filter out Korean-only keywords and common noise words, keep meaningful ones."""

    _NOISE_KEYWORDS = {
        "the",
        "and",
        "for",
        "with",
        "has",
        "are",
        "its",
        "but",
        "how",
        "why",
        "what",
        "new",
        "all",
        "can",
        "now",
        "get",
        "set",
        "may",
        "not",
        "other",
        "only",
        "just",
        "also",
        "more",
        "most",
        "some",
        "much",
        "many",
        "each",
        "even",
        "very",
        "here",
        "there",
        "then",
        "than",
        "into",
        "from",
        "this",
        "that",
        "been",
        "were",
        "will",
        "your",
        "they",
        "them",
        "such",
        "like",
        "better",
        "bigger",
        "lower",
        "higher",
        "early",
        "late",
        "huge",
        "linked",
        "issues",
        "says",
        "said",
        "first",
        "last",
        "next",
        "after",
        "before",
        "about",
        "every",
        "where",
        "which",
        "while",
        "could",
        "would",
        "should",
        "still",
        "today",
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
        "report",
        "update",
        "alert",
        "check",
        "watch",
        "live",
        "latest",
        "breaking",
        "global",
        "world",
        "major",
        "keep",
    }
    result = []
    for kw in keywords:
        # Keep if it has at least one Latin character and is not a noise word
        if re.search(r"[a-zA-Z]", kw) and kw.lower().strip() not in _NOISE_KEYWORDS:
            result.append(kw)
    return result


def _sanitize_og_text(text: str) -> str:
    if not text:
        return ""
    cleaned = text.replace("□", " ")
    cleaned = re.sub(r"[^A-Za-z0-9\s.,:;/%()+\-&']", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


# ---------------------------------------------------------------------------
# Professional dark finance color palette
# ---------------------------------------------------------------------------
COLORS = {
    # Backgrounds -- aligned with web CSS (_variables.scss)
    "bg": "#0d1117",
    "bg_card": "#161b22",
    "bg_inner": "#1c2128",
    "bg_header": "#0d1117",
    # Text hierarchy -- aligned with web CSS
    "text": "#e6edf3",
    "text_secondary": "#9da5ae",
    "text_muted": "#6e7681",
    # Positive / Negative -- aligned with web accent colors
    "green": "#3fb950",
    "green_dim": "#0b3d24",
    "red": "#f85149",
    "red_dim": "#4a1c2d",
    # Accent colors -- aligned with web accent colors
    "blue": "#58a6ff",
    "orange": "#d29922",
    "purple": "#bc8cff",
    "cyan": "#22d3ee",
    # Semantic
    "accent": "#58a6ff",
    "warning": "#d29922",
    "info": "#22d3ee",
    # Borders & separators -- aligned with web border
    "border": "#30363d",
    "border_highlight": "#3d4450",
    # Medal colors -- richer metallics
    "gold": "#ffd54f",
    "silver": "#b0bec5",
    "bronze": "#d4915c",
}

# ---------------------------------------------------------------------------
# Design system constants -- applied to every chart
# ---------------------------------------------------------------------------
_DS = {
    "pad_outer": 0.5,  # tight_layout outer padding
    "pad_title": 15,  # title top padding (set_title pad)
    "dpi": 150,
    "footer_size": 8,
    "title_size": 20,
    "subtitle_size": 10,
    "header_size": 9,
    "body_size": 12,
    "label_size": 10,
    "small_size": 9,
    "row_height": 0.62,  # unified row height
    "line_spacing": 0.55,  # vertical spacing between rows
    "watermark": "Investing Dragon",
}


def _ensure_dir():
    """Ensure the images directory exists."""
    os.makedirs(_get_pkg_attr("IMAGES_DIR"), exist_ok=True)


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Safely convert value to float, handling None/NaN/Inf."""
    if value is None:
        return default
    try:
        f = float(value)
        if np and (np.isnan(f) or np.isinf(f)):
            return default
        return f
    except (ValueError, TypeError):
        return default


def _get_change_color(change: float) -> str:
    """Get color based on price change."""
    if change > 0:
        return COLORS["green"]
    elif change < 0:
        return COLORS["red"]
    return COLORS["text_secondary"]


def _draw_rounded_rect(
    ax, x, y, w, h, *, facecolor, edgecolor="none", linewidth=0.0, alpha=1.0, transform=None, pad=0.012
):
    """Draw a rounded rectangle -- centralised helper."""
    kwargs = {
        "boxstyle": f"round,pad={pad}",
        "facecolor": facecolor,
        "edgecolor": edgecolor,
        "linewidth": linewidth,
        "alpha": alpha,
    }
    if transform is not None:
        kwargs["transform"] = transform
    rect = mpatches.FancyBboxPatch((x, y), w, h, **kwargs)
    ax.add_patch(rect)
    return rect


def _draw_gradient_bar(ax, x, y, w, h, *, color_start, color_end, steps=20, transform=None, alpha=1.0):
    """Approximate a horizontal gradient rectangle using thin strips."""
    from matplotlib.colors import to_rgba

    c0 = np.array(to_rgba(color_start))
    c1 = np.array(to_rgba(color_end))
    strip_w = w / steps
    for i in range(steps):
        t = i / max(steps - 1, 1)
        c = c0 * (1 - t) + c1 * t
        c[3] = alpha
        kwargs = {}
        if transform is not None:
            kwargs["transform"] = transform
        rect = mpatches.Rectangle((x + i * strip_w, y), strip_w, h, facecolor=c, edgecolor="none", **kwargs)
        ax.add_patch(rect)


def _add_market_texture(ax, width: float, height: float, *, accent: Optional[str] = None):
    """Add subtle ambient texture for premium-looking finance cards."""
    accent_color = accent or COLORS["accent"]

    glow_specs = [
        (width * 0.14, height * 0.88, width * 0.16, accent_color, 0.08),
        (width * 0.88, height * 0.16, width * 0.18, COLORS["cyan"], 0.05),
        (width * 0.78, height * 0.82, width * 0.12, COLORS["green"], 0.04),
    ]
    for cx, cy, radius, color, alpha in glow_specs:
        glow = mpatches.Circle((cx, cy), radius, facecolor=color, edgecolor="none", alpha=alpha)
        ax.add_patch(glow)

    for idx in range(7):
        y = height * (0.16 + idx * 0.11)
        ax.plot([0.35, width - 0.35], [y, y], color=COLORS["border_highlight"], linewidth=0.6, alpha=0.09)

    for idx in range(6):
        x = 0.6 + idx * (width - 1.2) / 5
        ax.plot([x, x], [0.45, height - 0.45], color=COLORS["border_highlight"], linewidth=0.6, alpha=0.06)


def _draw_mini_donut(ax, cx, cy, radius, data, colors, *, inner_ratio=0.58, center_value=None):
    """Draw a mini donut chart showing theme proportions visually."""
    total = sum(d.get("count", 0) for d in data)
    if total <= 0:
        return
    start_angle = 90
    for i, item in enumerate(data):
        count = item.get("count", 0)
        if count <= 0:
            continue
        sweep = 360 * count / total
        end_angle = start_angle - sweep
        wedge = mpatches.Wedge(
            (cx, cy),
            radius,
            end_angle,
            start_angle,
            width=radius * (1 - inner_ratio),
            facecolor=colors[i % len(colors)],
            edgecolor=COLORS["bg"],
            linewidth=2.5,
            alpha=0.92,
        )
        ax.add_patch(wedge)
        start_angle = end_angle
    # Inner glow ring
    glow = mpatches.Circle(
        (cx, cy),
        radius * inner_ratio + 0.02,
        facecolor="none",
        edgecolor=COLORS["border_highlight"],
        linewidth=0.8,
        alpha=0.4,
    )
    ax.add_patch(glow)
    # Center total text (use center_value if provided, else sum)
    display_val = str(center_value) if center_value is not None else str(total)
    ax.text(
        cx,
        cy + 0.12,
        display_val,
        ha="center",
        va="center",
        fontsize=22,
        fontweight="bold",
        color=COLORS["text"],
        fontfamily=_FONT_FAMILY,
    )
    ax.text(
        cx,
        cy - 0.18,
        "stories",
        ha="center",
        va="center",
        fontsize=8,
        color=COLORS["text_muted"],
        fontfamily=_FONT_FAMILY,
    )


def _draw_candlestick_bg(ax, x_start, y_start, width, height, *, n=10, alpha=0.07):
    """Draw subtle decorative candlestick pattern for crypto/market cards."""
    rng = np.random.RandomState(42)
    spacing = width / n
    for i in range(n):
        x = x_start + i * spacing + spacing * 0.5
        body_h = rng.uniform(0.25, 0.6) * height * 0.35
        body_y = y_start + rng.uniform(0.2, 0.5) * height
        is_bull = rng.random() > 0.45
        color = COLORS["green"] if is_bull else COLORS["red"]
        body_w = spacing * 0.35
        # Wick
        wick_top = body_y + body_h + rng.uniform(0.05, 0.2) * height * 0.3
        wick_bottom = body_y - rng.uniform(0.05, 0.2) * height * 0.3
        ax.plot([x, x], [wick_bottom, wick_top], color=color, linewidth=1.2, alpha=alpha)
        # Body
        rect = mpatches.FancyBboxPatch(
            (x - body_w / 2, body_y),
            body_w,
            body_h,
            boxstyle="round,pad=0.01",
            facecolor=color if is_bull else COLORS["bg"],
            edgecolor=color,
            linewidth=0.8,
            alpha=alpha * 1.8,
        )
        ax.add_patch(rect)


def _draw_line_chart_bg(ax, x_start, y_start, width, height, *, alpha=0.09):
    """Draw subtle decorative line chart / area chart pattern for stock cards."""
    n_points = 30
    x = np.linspace(x_start, x_start + width, n_points)
    rng = np.random.RandomState(123)
    y_base = y_start + height * 0.5
    y = y_base + np.cumsum(rng.randn(n_points) * height * 0.06)
    y = np.clip(y, y_start + height * 0.15, y_start + height * 0.85)
    ax.fill_between(x, y_start, y, color=COLORS["green"], alpha=alpha * 0.4)
    ax.plot(x, y, color=COLORS["green"], linewidth=1.8, alpha=alpha * 1.5)
    # Second line (secondary)
    y2 = y_base + np.cumsum(rng.randn(n_points) * height * 0.04) - height * 0.08
    y2 = np.clip(y2, y_start + height * 0.1, y_start + height * 0.8)
    ax.plot(x, y2, color=COLORS["blue"], linewidth=1.2, alpha=alpha)


def _draw_globe_bg(ax, cx, cy, radius, *, alpha=0.06):
    """Draw subtle decorative globe pattern for world/geopolitical cards."""
    circle = mpatches.Circle(
        (cx, cy),
        radius,
        facecolor="none",
        edgecolor=COLORS["cyan"],
        linewidth=1.8,
        alpha=alpha * 2,
    )
    ax.add_patch(circle)
    # Latitude ellipses
    for frac in [0.3, 0.6, 0.9]:
        ellipse = mpatches.Ellipse(
            (cx, cy),
            radius * 2,
            radius * 2 * frac,
            facecolor="none",
            edgecolor=COLORS["cyan"],
            linewidth=0.7,
            alpha=alpha,
        )
        ax.add_patch(ellipse)
    # Longitude arcs
    for angle_deg in [0, 30, 60, 90, 120, 150]:
        rad = np.radians(angle_deg)
        x1 = cx + radius * np.cos(rad)
        y1 = cy + radius * np.sin(rad)
        x2 = cx - radius * np.cos(rad)
        y2 = cy - radius * np.sin(rad)
        ax.plot([x1, x2], [y1, y2], color=COLORS["cyan"], linewidth=0.6, alpha=alpha * 0.8)
    # Connection dots
    for angle_deg in range(0, 360, 45):
        rad = np.radians(angle_deg)
        dx = cx + radius * 0.7 * np.cos(rad)
        dy = cy + radius * 0.7 * np.sin(rad)
        dot = mpatches.Circle((dx, dy), 0.06, facecolor=COLORS["cyan"], alpha=alpha * 3)
        ax.add_patch(dot)


def _draw_shield_bg(ax, cx, cy, size, *, alpha=0.06):
    """Draw subtle decorative shield pattern for regulatory/security cards."""
    from matplotlib.path import Path

    s = size
    verts = [
        (cx, cy + s * 1.0),  # top
        (cx + s * 0.8, cy + s * 0.6),
        (cx + s * 0.8, cy - s * 0.2),
        (cx + s * 0.4, cy - s * 0.7),
        (cx, cy - s * 1.0),  # bottom
        (cx - s * 0.4, cy - s * 0.7),
        (cx - s * 0.8, cy - s * 0.2),
        (cx - s * 0.8, cy + s * 0.6),
        (cx, cy + s * 1.0),  # close
    ]
    codes = [Path.MOVETO] + [Path.CURVE3] * 7 + [Path.CLOSEPOLY]
    path = Path(verts, codes)
    patch = mpatches.PathPatch(
        path,
        facecolor=COLORS["cyan"],
        edgecolor=COLORS["cyan"],
        linewidth=1.5,
        alpha=alpha,
    )
    ax.add_patch(patch)
    # Checkmark inside
    ax.plot(
        [cx - s * 0.25, cx - s * 0.05, cx + s * 0.3],
        [cy, cy - s * 0.25, cy + s * 0.3],
        color=COLORS["cyan"],
        linewidth=2.0,
        alpha=alpha * 3,
    )


def _draw_pulse_line(ax, x_start, y_center, width, *, alpha=0.1):
    """Draw subtle decorative heartbeat/pulse line pattern."""
    x = np.linspace(x_start, x_start + width, 200)
    y = np.zeros_like(x)
    # Create pulse-like pattern
    for peak_x in np.linspace(x_start + width * 0.1, x_start + width * 0.9, 5):
        dist = np.abs(x - peak_x)
        spike = np.exp(-dist * 8) * np.sin(dist * 40) * 0.3
        y += spike
    ax.plot(x, y_center + y, color=COLORS["accent"], linewidth=1.5, alpha=alpha)


def _get_category_bg_drawer(category: str):
    """Return the appropriate background illustration drawer for a category."""
    cat_lower = category.lower()
    if any(k in cat_lower for k in ["blockchain"]) or any(
        k in cat_lower for k in ["crypto", "bitcoin", "defi", "coin"]
    ):
        return "crypto"
    elif any(k in cat_lower for k in ["stock", "market snapshot", "sector"]):
        return "stock"
    elif any(k in cat_lower for k in ["world", "geopolit", "global", "monitor"]):
        return "world"
    elif any(k in cat_lower for k in ["regulat", "security", "policy", "legal"]):
        return "regulatory"
    elif any(k in cat_lower for k in ["social", "media", "community"]):
        return "social"
    elif any(k in cat_lower for k in ["politic", "trade", "congress"]):
        return "political"
    return "crypto"


def _draw_category_illustration(ax, category_type, x, y, w, h, *, alpha=0.07):
    """Draw category-specific background illustration."""
    if category_type == "crypto":
        _draw_candlestick_bg(ax, x, y, w, h, alpha=alpha)
    elif category_type == "stock":
        _draw_line_chart_bg(ax, x, y, w, h, alpha=alpha)
    elif category_type == "world":
        _draw_globe_bg(ax, x + w * 0.5, y + h * 0.5, min(w, h) * 0.4, alpha=alpha)
    elif category_type == "regulatory":
        _draw_shield_bg(ax, x + w * 0.5, y + h * 0.5, min(w, h) * 0.35, alpha=alpha)
    else:
        _draw_pulse_line(ax, x, y + h * 0.5, w, alpha=alpha)


def _draw_metric_chip(ax, x, y, w, h, *, label: str, value: str, accent: str, value_color: Optional[str] = None):
    """Draw a compact metric chip with layered background."""
    _draw_rounded_rect(
        ax,
        x,
        y,
        w,
        h,
        facecolor=COLORS["bg_card"],
        edgecolor=COLORS["border"],
        linewidth=0.9,
        alpha=0.96,
        pad=0.035,
    )
    _draw_gradient_bar(
        ax,
        x + 0.03,
        y + h - 0.1,
        w - 0.06,
        0.06,
        color_start=accent,
        color_end=COLORS["bg_card"],
        steps=24,
        alpha=0.7,
    )
    ax.text(
        x + 0.16,
        y + h - 0.22,
        label.upper(),
        fontsize=8,
        fontweight="bold",
        color=COLORS["text_muted"],
        fontfamily=_FONT_FAMILY,
        va="top",
    )
    ax.text(
        x + 0.16,
        y + 0.2,
        value,
        fontsize=14,
        fontweight="bold",
        color=value_color or COLORS["text"],
        fontfamily=_FONT_FAMILY,
        va="bottom",
    )


def _truncate_text(text: str, limit: int) -> str:
    """Safely truncate text for compact image layouts."""
    if len(text) <= limit:
        return text
    return text[: max(limit - 3, 0)].rstrip() + "..."


def _add_footer(ax, text=None, *, use_fig=False, fig=None, y=None):
    """Add the standard watermark footer.

    alpha를 높여 더 세련된 워터마크를 표시한다.
    """
    label = text or f"{_DS['watermark']} | Auto-generated"
    if use_fig and fig is not None:
        fig.text(
            0.5,
            0.01,
            label,
            ha="center",
            fontsize=_DS["footer_size"],
            color=COLORS["text_secondary"],
            fontfamily=_FONT_FAMILY,
            style="italic",
            alpha=0.80,
        )
    else:
        y_pos = y if y is not None else 0.01
        ax.text(
            0.5,
            y_pos,
            label,
            ha="center",
            va="bottom",
            transform=ax.transAxes,
            fontsize=_DS["footer_size"],
            color=COLORS["text_secondary"],
            fontfamily=_FONT_FAMILY,
            style="italic",
            alpha=0.80,
        )


def _heatmap_bg_color(change: float, *, extreme=5.0) -> str:
    """Return a background colour that scales with the magnitude of *change*.

    Uses linear interpolation between the dim colour and a vivid accent so
    that small moves look subtle and large moves are immediately obvious.
    """
    from matplotlib.colors import to_hex, to_rgba

    change = _safe_float(change)
    ratio = min(abs(change) / extreme, 1.0)
    if change >= 0:
        base = np.array(to_rgba(COLORS["bg_card"]))
        vivid = np.array(to_rgba(COLORS["green_dim"]))
    else:
        base = np.array(to_rgba(COLORS["bg_card"]))
        vivid = np.array(to_rgba(COLORS["red_dim"]))
    mixed = base * (1 - ratio) + vivid * ratio
    mixed = np.clip(mixed, 0, 1)
    return to_hex(mixed[:3])


def _save_and_close(fig, filepath, *, bg=None):
    """Shared save-and-close with automatic WebP conversion."""
    bg_color = bg or COLORS["bg"]
    plt.savefig(
        filepath,
        dpi=_DS["dpi"],
        facecolor=bg_color,
        edgecolor="none",
        bbox_inches="tight",
        pad_inches=0.15,
        metadata={"Software": _DS["watermark"]},
    )
    plt.close(fig)
    # Optimize PNG file size via Pillow re-save
    _optimize_png(filepath)
    # Generate WebP alongside PNG for faster page loads
    _convert_to_webp(filepath)
    # Generate AVIF alongside PNG for maximum compression (graceful degradation)
    _convert_to_avif(filepath)
    # Mirror variants to external object storage when configured (no-op otherwise).
    _mirror_to_remote(filepath)


def _mirror_to_remote(png_path: str) -> None:
    """Best-effort mirror of generated image variants to R2 (no-op when disabled).

    Wrapped so remote storage can never break local image generation. See
    scripts/common/asset_storage.py and docs/design-image-offloading-r2.md.
    """
    try:
        from ..asset_storage import mirror_generated_variants

        mirror_generated_variants(png_path)
    except Exception as exc:  # noqa: BLE001 - mirroring must never break generation
        logger.debug("remote image mirror skipped for %s: %s", os.path.basename(png_path), exc)


def _optimize_png(png_path: str) -> None:
    """Re-save PNG with Pillow optimize flag to reduce file size."""
    try:
        from PIL import Image

        with Image.open(png_path) as img:
            img.save(png_path, "PNG", optimize=True)
    except Exception:  # noqa: BLE001, S110
        pass  # optimization is best-effort


def _convert_to_webp(png_path: str, quality: int = 88) -> Optional[str]:
    """Convert a PNG image to WebP format for smaller file sizes.

    Returns the WebP file path on success, None on failure.
    """
    try:
        from PIL import Image

        webp_path = os.path.splitext(png_path)[0] + ".webp"
        with Image.open(png_path) as img:
            img.save(webp_path, "WEBP", quality=quality, method=4)
        png_size = os.path.getsize(png_path)
        webp_size = os.path.getsize(webp_path)
        savings = (1 - webp_size / png_size) * 100 if png_size > 0 else 0
        logger.info(
            "WebP: %s (%.0f%% smaller: %dKB → %dKB)",
            os.path.basename(webp_path),
            savings,
            png_size // 1024,
            webp_size // 1024,
        )
        return webp_path
    except ImportError:
        logger.debug("Pillow not available for WebP conversion")
    except Exception as exc:
        logger.debug("WebP conversion failed for %s: %s", png_path, exc)
    return None


def _convert_to_avif(png_path: str, quality: int = 50) -> Optional[str]:
    """Convert a PNG image to AVIF format for smaller file sizes.

    Returns the AVIF file path on success, None on failure.
    AVIF 저장 실패 시 경고만 출력하고 에러는 발생시키지 않음.
    """
    try:
        from PIL import Image

        avif_path = os.path.splitext(png_path)[0] + ".avif"
        with Image.open(png_path) as img:
            img.save(avif_path, "AVIF", quality=quality)
        png_size = os.path.getsize(png_path)
        avif_size = os.path.getsize(avif_path)
        savings = (1 - avif_size / png_size) * 100 if png_size > 0 else 0
        logger.info(
            "AVIF: %s (%.0f%% smaller: %dKB → %dKB)",
            os.path.basename(avif_path),
            savings,
            png_size // 1024,
            avif_size // 1024,
        )
        return avif_path
    except ImportError:
        logger.debug("Pillow not available for AVIF conversion")
    except Exception as exc:
        logger.warning("AVIF conversion failed for %s: %s", os.path.basename(png_path), exc)
    return None
