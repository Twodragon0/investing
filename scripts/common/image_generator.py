"""Market visualization image generator.

Generates professional market cards, charts, and gauges using matplotlib and Pillow.
Images are saved to assets/images/generated/ for use in Jekyll posts.
"""

import logging
import os
from typing import Any, Dict, List, Optional

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
        logger.warning("No CJK font found, Korean text may not render correctly")

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

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
IMAGES_DIR = os.path.join(REPO_ROOT, "assets", "images", "generated")

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
}


def _to_en(text: str) -> str:
    """Translate Korean text to English for image rendering."""
    if text in _KO_TO_EN:
        return _KO_TO_EN[text]
    # If text contains any Hangul, try partial match or return as-is
    import re

    if re.search(r"[\uac00-\ud7af]", text):
        # Check if it's a known prefix match
        for ko, en in _KO_TO_EN.items():
            if ko in text:
                return text.replace(ko, en)
        return text
    return text


def _filter_en_keywords(keywords: list) -> list:
    """Filter out Korean-only keywords, keep English/mixed ones."""
    import re

    result = []
    for kw in keywords:
        # Keep if it has at least one Latin character
        if re.search(r"[a-zA-Z]", kw):
            result.append(kw)
    return result


# Dark theme colors
COLORS = {
    "bg": "#0d1117",
    "bg_card": "#161b22",
    "bg_inner": "#1c2128",
    "text": "#e6edf3",
    "text_secondary": "#8b949e",
    "green": "#3fb950",
    "red": "#f85149",
    "blue": "#58a6ff",
    "orange": "#d29922",
    "purple": "#bc8cff",
    "border": "#30363d",
    "gold": "#ffd700",
    "silver": "#c0c0c0",
    "bronze": "#cd7f32",
}


def _ensure_dir():
    """Ensure the images directory exists."""
    os.makedirs(IMAGES_DIR, exist_ok=True)


def _get_change_color(change: float) -> str:
    """Get color based on price change."""
    if change > 0:
        return COLORS["green"]
    elif change < 0:
        return COLORS["red"]
    return COLORS["text_secondary"]


def generate_top_coins_card(
    coins: List[Dict[str, Any]],
    date_str: str,
    source: str = "coingecko",
    filename: Optional[str] = None,
) -> Optional[str]:
    """Generate a top coins ranking card image.

    Returns relative path for Jekyll or None on failure.
    """
    if not _MPL_AVAILABLE:
        return None

    _ensure_dir()

    if not coins:
        return None

    display_coins = coins[:10]
    fig_height = 2.0 + len(display_coins) * 0.65

    fig, ax = plt.subplots(figsize=(12, fig_height))
    fig.patch.set_facecolor(COLORS["bg"])
    ax.set_facecolor(COLORS["bg"])
    ax.set_xlim(0, 10)
    ax.set_ylim(0, fig_height)
    ax.axis("off")

    # Title
    ax.text(
        5,
        fig_height - 0.5,
        "Top 10 Cryptocurrencies by Market Cap",
        ha="center",
        va="center",
        fontsize=18,
        fontweight="bold",
        color=COLORS["text"],
        fontfamily=_FONT_FAMILY,
    )
    ax.text(
        5,
        fig_height - 1.0,
        f"{date_str} | Source: {source}",
        ha="center",
        va="center",
        fontsize=10,
        color=COLORS["text_secondary"],
        fontfamily=_FONT_FAMILY,
    )

    # Column headers
    y_start = fig_height - 1.6
    ax.text(
        0.3,
        y_start,
        "#",
        fontsize=9,
        fontweight="bold",
        color=COLORS["text_secondary"],
        fontfamily=_FONT_FAMILY,
    )
    ax.text(
        1.0,
        y_start,
        "Coin",
        fontsize=9,
        fontweight="bold",
        color=COLORS["text_secondary"],
        fontfamily=_FONT_FAMILY,
    )
    ax.text(
        4.5,
        y_start,
        "Price (USD)",
        fontsize=9,
        fontweight="bold",
        color=COLORS["text_secondary"],
        fontfamily=_FONT_FAMILY,
        ha="right",
    )
    ax.text(
        6.0,
        y_start,
        "24h Change",
        fontsize=9,
        fontweight="bold",
        color=COLORS["text_secondary"],
        fontfamily=_FONT_FAMILY,
        ha="center",
    )
    ax.text(
        7.8,
        y_start,
        "7d Change",
        fontsize=9,
        fontweight="bold",
        color=COLORS["text_secondary"],
        fontfamily=_FONT_FAMILY,
        ha="center",
    )
    ax.text(
        9.7,
        y_start,
        "Market Cap",
        fontsize=9,
        fontweight="bold",
        color=COLORS["text_secondary"],
        fontfamily=_FONT_FAMILY,
        ha="right",
    )

    # Divider
    ax.plot(
        [0.2, 9.8],
        [y_start - 0.2, y_start - 0.2],
        color=COLORS["border"],
        linewidth=0.5,
    )

    # Coin rows
    for i, coin in enumerate(display_coins):
        y = y_start - 0.5 - i * 0.6

        if source == "coingecko":
            name = coin.get("symbol", "").upper()
            full_name = coin.get("name", "")
            price = coin.get("current_price", 0)
            change_24h = coin.get("price_change_percentage_24h", 0) or 0
            change_7d = coin.get("price_change_percentage_7d_in_currency", 0) or 0
            mcap = coin.get("market_cap", 0) or 0
        else:
            name = coin.get("symbol", "")
            full_name = coin.get("name", "")
            quote = coin.get("quote", {}).get("USD", {})
            price = quote.get("price", 0) or 0
            change_24h = quote.get("percent_change_24h", 0) or 0
            change_7d = quote.get("percent_change_7d", 0) or 0
            mcap = quote.get("market_cap", 0) or 0

        # Row background (alternating)
        if i % 2 == 0:
            rect = mpatches.FancyBboxPatch(
                (0.15, y - 0.2),
                9.7,
                0.55,
                boxstyle="round,pad=0.05",
                facecolor=COLORS["bg_inner"],
                edgecolor="none",
                alpha=0.5,
            )
            ax.add_patch(rect)

        # Rank medal colors
        rank_colors = {0: COLORS["gold"], 1: COLORS["silver"], 2: COLORS["bronze"]}
        rank_color = rank_colors.get(i, COLORS["text_secondary"])

        ax.text(
            0.4,
            y,
            str(i + 1),
            fontsize=11,
            fontweight="bold",
            color=rank_color,
            ha="center",
            fontfamily=_FONT_FAMILY,
        )

        # Coin name
        ax.text(
            1.0,
            y + 0.05,
            name,
            fontsize=11,
            fontweight="bold",
            color=COLORS["text"],
            fontfamily=_FONT_FAMILY,
        )
        ax.text(
            1.0,
            y - 0.18,
            full_name[:18],
            fontsize=7,
            color=COLORS["text_secondary"],
            fontfamily=_FONT_FAMILY,
        )

        # Price
        if price >= 1:
            price_str = f"${price:,.2f}"
        elif price >= 0.01:
            price_str = f"${price:,.4f}"
        else:
            price_str = f"${price:,.6f}"
        ax.text(
            4.5,
            y,
            price_str,
            fontsize=10,
            color=COLORS["text"],
            ha="right",
            fontfamily=_FONT_FAMILY,
        )

        # 24h change
        color_24h = _get_change_color(change_24h)
        arrow_24h = "▲" if change_24h >= 0 else "▼"
        ax.text(
            6.0,
            y,
            f"{arrow_24h} {abs(change_24h):.2f}%",
            fontsize=10,
            color=color_24h,
            ha="center",
            fontfamily=_FONT_FAMILY,
            fontweight="bold",
        )

        # 7d change
        color_7d = _get_change_color(change_7d)
        arrow_7d = "▲" if change_7d >= 0 else "▼"
        ax.text(
            7.8,
            y,
            f"{arrow_7d} {abs(change_7d):.2f}%",
            fontsize=10,
            color=color_7d,
            ha="center",
            fontfamily=_FONT_FAMILY,
        )

        # Market cap
        if mcap >= 1_000_000_000_000:
            mcap_str = f"${mcap / 1e12:.2f}T"
        elif mcap >= 1_000_000_000:
            mcap_str = f"${mcap / 1e9:.1f}B"
        elif mcap >= 1_000_000:
            mcap_str = f"${mcap / 1e6:.1f}M"
        else:
            mcap_str = f"${mcap:,.0f}"
        ax.text(
            9.7,
            y,
            mcap_str,
            fontsize=10,
            color=COLORS["text"],
            ha="right",
            fontfamily=_FONT_FAMILY,
        )

    # Footer
    ax.text(
        5,
        0.2,
        "Investing Dragon | Auto-generated Market Report",
        ha="center",
        fontsize=8,
        color=COLORS["text_secondary"],
        fontfamily=_FONT_FAMILY,
        style="italic",
    )

    if not filename:
        filename = f"top-coins-{date_str}.png"
    filepath = os.path.join(IMAGES_DIR, filename)

    plt.tight_layout(pad=0.5)
    plt.savefig(filepath, dpi=150, facecolor=COLORS["bg"], edgecolor="none", bbox_inches="tight")
    plt.close(fig)

    logger.info("Generated top coins card: %s", filename)
    return f"/assets/images/generated/{filename}"


def generate_fear_greed_gauge(
    value: int,
    classification: str,
    date_str: str,
    filename: Optional[str] = None,
) -> Optional[str]:
    """Generate a Fear & Greed gauge image."""
    if not _MPL_AVAILABLE:
        return None

    _ensure_dir()

    fig, ax = plt.subplots(figsize=(8, 5))
    fig.patch.set_facecolor(COLORS["bg"])
    ax.set_facecolor(COLORS["bg"])
    ax.set_xlim(-1.5, 1.5)
    ax.set_ylim(-0.5, 1.5)
    ax.set_aspect("equal")
    ax.axis("off")

    # Title
    ax.text(
        0,
        1.45,
        "Crypto Fear & Greed Index",
        ha="center",
        va="center",
        fontsize=16,
        fontweight="bold",
        color=COLORS["text"],
        fontfamily=_FONT_FAMILY,
    )
    ax.text(
        0,
        1.25,
        date_str,
        ha="center",
        va="center",
        fontsize=10,
        color=COLORS["text_secondary"],
        fontfamily=_FONT_FAMILY,
    )

    # Draw gauge arc (semicircle)
    _theta = np.linspace(np.pi, 0, 100)
    r = 1.0

    # Color gradient segments
    segments = [
        (np.pi, np.pi * 0.75, "#f85149"),  # Extreme Fear (red)
        (np.pi * 0.75, np.pi * 0.5, "#d29922"),  # Fear (orange)
        (np.pi * 0.5, np.pi * 0.375, "#8b949e"),  # Neutral (gray)
        (np.pi * 0.375, np.pi * 0.25, "#58a6ff"),  # Greed (blue)
        (np.pi * 0.25, 0, "#3fb950"),  # Extreme Greed (green)
    ]

    for start, end, color in segments:
        t = np.linspace(start, end, 30)
        for j in range(len(t) - 1):
            wedge = mpatches.Wedge(
                (0, 0),
                r + 0.15,
                np.degrees(t[j + 1]),
                np.degrees(t[j]),
                width=0.2,
                facecolor=color,
                edgecolor="none",
                alpha=0.8,
            )
            ax.add_patch(wedge)

    # Inner circle
    inner = mpatches.Circle((0, 0), 0.7, facecolor=COLORS["bg"], edgecolor=COLORS["border"], linewidth=1)
    ax.add_patch(inner)

    # Needle
    needle_angle = np.pi * (1 - value / 100)
    needle_x = 0.65 * np.cos(needle_angle)
    needle_y = 0.65 * np.sin(needle_angle)
    ax.annotate(
        "",
        xy=(needle_x, needle_y),
        xytext=(0, 0),
        arrowprops=dict(arrowstyle="-|>", color=COLORS["text"], lw=2.5),
    )

    # Center dot
    center_dot = mpatches.Circle((0, 0), 0.06, facecolor=COLORS["text"], edgecolor="none")
    ax.add_patch(center_dot)

    # Value display
    ax.text(
        0,
        0.25,
        str(value),
        ha="center",
        va="center",
        fontsize=36,
        fontweight="bold",
        color=COLORS["text"],
        fontfamily=_FONT_FAMILY,
    )
    ax.text(
        0,
        -0.05,
        classification,
        ha="center",
        va="center",
        fontsize=14,
        color=COLORS["text_secondary"],
        fontfamily=_FONT_FAMILY,
    )

    # Scale labels
    ax.text(
        -1.15,
        -0.15,
        "0",
        fontsize=9,
        color=COLORS["red"],
        ha="center",
        fontfamily=_FONT_FAMILY,
    )
    ax.text(
        -0.85,
        0.75,
        "25",
        fontsize=9,
        color=COLORS["orange"],
        ha="center",
        fontfamily=_FONT_FAMILY,
    )
    ax.text(
        0,
        1.05,
        "50",
        fontsize=9,
        color=COLORS["text_secondary"],
        ha="center",
        fontfamily=_FONT_FAMILY,
    )
    ax.text(
        0.85,
        0.75,
        "75",
        fontsize=9,
        color=COLORS["blue"],
        ha="center",
        fontfamily=_FONT_FAMILY,
    )
    ax.text(
        1.15,
        -0.15,
        "100",
        fontsize=9,
        color=COLORS["green"],
        ha="center",
        fontfamily=_FONT_FAMILY,
    )

    # Footer
    ax.text(
        0,
        -0.45,
        "Investing Dragon | alternative.me",
        ha="center",
        fontsize=8,
        color=COLORS["text_secondary"],
        fontfamily=_FONT_FAMILY,
        style="italic",
    )

    if not filename:
        filename = f"fear-greed-{date_str}.png"
    filepath = os.path.join(IMAGES_DIR, filename)

    plt.tight_layout(pad=0.3)
    plt.savefig(filepath, dpi=150, facecolor=COLORS["bg"], edgecolor="none", bbox_inches="tight")
    plt.close(fig)

    logger.info("Generated fear & greed gauge: %s", filename)
    return f"/assets/images/generated/{filename}"


def generate_market_heatmap(
    coins: List[Dict[str, Any]],
    date_str: str,
    source: str = "coingecko",
    filename: Optional[str] = None,
) -> Optional[str]:
    """Generate a market heatmap showing top coins by market cap with color-coded changes."""
    if not _MPL_AVAILABLE:
        return None

    _ensure_dir()

    if not coins:
        return None

    display_coins = coins[:20]
    fig, ax = plt.subplots(figsize=(14, 8))
    fig.patch.set_facecolor(COLORS["bg"])
    ax.set_facecolor(COLORS["bg"])
    ax.axis("off")

    # Title
    ax.text(
        0.5,
        0.97,
        "Crypto Market Heatmap - Top 20",
        ha="center",
        va="top",
        transform=ax.transAxes,
        fontsize=18,
        fontweight="bold",
        color=COLORS["text"],
        fontfamily=_FONT_FAMILY,
    )
    ax.text(
        0.5,
        0.93,
        f"{date_str} | 24h Price Change",
        ha="center",
        va="top",
        transform=ax.transAxes,
        fontsize=10,
        color=COLORS["text_secondary"],
        fontfamily=_FONT_FAMILY,
    )

    # Grid layout (5 cols x 4 rows)
    cols, rows = 5, 4
    margin = 0.03
    cell_w = (1.0 - margin * (cols + 1)) / cols
    cell_h = (0.88 - margin * (rows + 1)) / rows

    for i, coin in enumerate(display_coins):
        row = i // cols
        col = i % cols

        x = margin + col * (cell_w + margin)
        y = 0.88 - margin - (row + 1) * (cell_h + margin) + margin

        if source == "coingecko":
            symbol = coin.get("symbol", "").upper()
            price = coin.get("current_price", 0) or 0
            change = coin.get("price_change_percentage_24h", 0) or 0
            _mcap = coin.get("market_cap", 0) or 0
        else:
            symbol = coin.get("symbol", "")
            quote = coin.get("quote", {}).get("USD", {})
            price = quote.get("price", 0) or 0
            change = quote.get("percent_change_24h", 0) or 0
            _mcap = quote.get("market_cap", 0) or 0

        # Color based on change intensity
        if change >= 5:
            bg_color = "#1a4d2e"
        elif change >= 2:
            bg_color = "#1a3d25"
        elif change >= 0:
            bg_color = "#162d1e"
        elif change >= -2:
            bg_color = "#2d1a1a"
        elif change >= -5:
            bg_color = "#3d1a1a"
        else:
            bg_color = "#4d1a1a"

        rect = mpatches.FancyBboxPatch(
            (x, y),
            cell_w,
            cell_h,
            boxstyle="round,pad=0.008",
            facecolor=bg_color,
            edgecolor=COLORS["border"],
            linewidth=0.5,
            transform=ax.transAxes,
        )
        ax.add_patch(rect)

        # Symbol
        ax.text(
            x + cell_w / 2,
            y + cell_h * 0.72,
            symbol,
            ha="center",
            va="center",
            transform=ax.transAxes,
            fontsize=14,
            fontweight="bold",
            color=COLORS["text"],
            fontfamily=_FONT_FAMILY,
        )

        # Price
        if price >= 1:
            price_str = f"${price:,.2f}"
        else:
            price_str = f"${price:,.4f}"
        ax.text(
            x + cell_w / 2,
            y + cell_h * 0.42,
            price_str,
            ha="center",
            va="center",
            transform=ax.transAxes,
            fontsize=9,
            color=COLORS["text_secondary"],
            fontfamily=_FONT_FAMILY,
        )

        # Change
        change_color = _get_change_color(change)
        arrow = "▲" if change >= 0 else "▼"
        ax.text(
            x + cell_w / 2,
            y + cell_h * 0.18,
            f"{arrow} {abs(change):.2f}%",
            ha="center",
            va="center",
            transform=ax.transAxes,
            fontsize=11,
            fontweight="bold",
            color=change_color,
            fontfamily=_FONT_FAMILY,
        )

    # Footer
    ax.text(
        0.5,
        0.01,
        "Investing Dragon | Auto-generated Market Heatmap",
        ha="center",
        va="bottom",
        transform=ax.transAxes,
        fontsize=8,
        color=COLORS["text_secondary"],
        fontfamily=_FONT_FAMILY,
        style="italic",
    )

    if not filename:
        filename = f"market-heatmap-{date_str}.png"
    filepath = os.path.join(IMAGES_DIR, filename)

    plt.savefig(filepath, dpi=150, facecolor=COLORS["bg"], edgecolor="none", bbox_inches="tight")
    plt.close(fig)

    logger.info("Generated market heatmap: %s", filename)
    return f"/assets/images/generated/{filename}"


def generate_news_summary_card(
    categories: List[Dict[str, Any]],
    date_str: str,
    filename: Optional[str] = None,
) -> Optional[str]:
    """Generate a horizontal bar chart showing news source distribution.

    Args:
        categories: List of {"name": "CryptoPanic", "count": 15} dicts.
        date_str: Date string for the title.
        filename: Optional output filename.

    Returns relative path for Jekyll or None on failure.
    """
    if not _MPL_AVAILABLE:
        return None

    _ensure_dir()

    if not categories:
        return None

    bar_colors = [
        COLORS["blue"],
        COLORS["green"],
        COLORS["orange"],
        COLORS["purple"],
        COLORS["red"],
        COLORS["gold"],
        COLORS["silver"],
        COLORS["text_secondary"],
    ]

    names = [_to_en(c["name"]) for c in categories]
    counts = [c["count"] for c in categories]
    colors = [bar_colors[i % len(bar_colors)] for i in range(len(names))]

    fig, ax = plt.subplots(figsize=(10, 5))
    fig.patch.set_facecolor(COLORS["bg"])
    ax.set_facecolor(COLORS["bg"])

    y_pos = np.arange(len(names))
    bars = ax.barh(y_pos, counts, color=colors, height=0.6, edgecolor="none")

    ax.set_yticks(y_pos)
    ax.set_yticklabels(names, fontsize=11, color=COLORS["text"], fontfamily=_FONT_FAMILY)
    ax.invert_yaxis()

    ax.set_xlabel("Articles", fontsize=10, color=COLORS["text_secondary"], fontfamily=_FONT_FAMILY)
    ax.tick_params(axis="x", colors=COLORS["text_secondary"])
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["bottom"].set_color(COLORS["border"])
    ax.spines["left"].set_color(COLORS["border"])

    # Value labels on bars
    for bar, count in zip(bars, counts, strict=False):
        ax.text(
            bar.get_width() + 0.3,
            bar.get_y() + bar.get_height() / 2,
            str(count),
            va="center",
            fontsize=10,
            color=COLORS["text"],
            fontfamily=_FONT_FAMILY,
            fontweight="bold",
        )

    ax.set_title(
        f"News Source Distribution — {date_str}",
        fontsize=14,
        fontweight="bold",
        color=COLORS["text"],
        fontfamily=_FONT_FAMILY,
        pad=15,
    )

    # Footer
    fig.text(
        0.5,
        0.01,
        "Investing Dragon | Auto-generated",
        ha="center",
        fontsize=8,
        color=COLORS["text_secondary"],
        fontfamily=_FONT_FAMILY,
        style="italic",
    )

    if not filename:
        filename = f"news-summary-{date_str}.png"
    filepath = os.path.join(IMAGES_DIR, filename)

    plt.tight_layout(pad=1.0)
    plt.savefig(filepath, dpi=150, facecolor=COLORS["bg"], edgecolor="none", bbox_inches="tight")
    plt.close(fig)

    logger.info("Generated news summary card: %s", filename)
    return f"/assets/images/generated/{filename}"


def generate_market_snapshot_card(
    market_data: List[Dict[str, Any]],
    date_str: str,
    filename: Optional[str] = None,
) -> Optional[str]:
    """Generate a card-style table showing key index/ETF prices and changes.

    Args:
        market_data: List of {"name": "S&P 500", "price": "$5,964",
                     "change_pct": "+0.47%", "section": "US"} dicts.
        date_str: Date string for the title.
        filename: Optional output filename.

    Returns relative path for Jekyll or None on failure.
    """
    if not _MPL_AVAILABLE:
        return None

    _ensure_dir()

    if not market_data:
        return None

    row_count = len(market_data)
    fig_height = 2.5 + row_count * 0.55
    fig, ax = plt.subplots(figsize=(12, fig_height))
    fig.patch.set_facecolor(COLORS["bg"])
    ax.set_facecolor(COLORS["bg"])
    ax.set_xlim(0, 10)
    ax.set_ylim(0, fig_height)
    ax.axis("off")

    # Title
    ax.text(
        5,
        fig_height - 0.5,
        "Market Snapshot",
        ha="center",
        va="center",
        fontsize=18,
        fontweight="bold",
        color=COLORS["text"],
        fontfamily=_FONT_FAMILY,
    )
    ax.text(
        5,
        fig_height - 1.0,
        f"{date_str} | US & Korean Markets",
        ha="center",
        va="center",
        fontsize=10,
        color=COLORS["text_secondary"],
        fontfamily=_FONT_FAMILY,
    )

    # Column headers
    y_start = fig_height - 1.5
    ax.text(
        0.5,
        y_start,
        "Index / ETF",
        fontsize=9,
        fontweight="bold",
        color=COLORS["text_secondary"],
        fontfamily=_FONT_FAMILY,
    )
    ax.text(
        5.0,
        y_start,
        "Price",
        fontsize=9,
        fontweight="bold",
        color=COLORS["text_secondary"],
        fontfamily=_FONT_FAMILY,
        ha="center",
    )
    ax.text(
        8.0,
        y_start,
        "Change",
        fontsize=9,
        fontweight="bold",
        color=COLORS["text_secondary"],
        fontfamily=_FONT_FAMILY,
        ha="center",
    )

    ax.plot(
        [0.3, 9.7],
        [y_start - 0.2, y_start - 0.2],
        color=COLORS["border"],
        linewidth=0.5,
    )

    current_section = None
    y = y_start - 0.5

    for i, item in enumerate(market_data):
        section = item.get("section", "")
        if section and section != current_section:
            current_section = section
            ax.text(
                0.5,
                y,
                section,
                fontsize=10,
                fontweight="bold",
                color=COLORS["blue"],
                fontfamily=_FONT_FAMILY,
            )
            y -= 0.45

        # Row background
        if i % 2 == 0:
            rect = mpatches.FancyBboxPatch(
                (0.3, y - 0.18),
                9.4,
                0.5,
                boxstyle="round,pad=0.05",
                facecolor=COLORS["bg_inner"],
                edgecolor="none",
                alpha=0.5,
            )
            ax.add_patch(rect)

        name = item.get("name", "")
        price = item.get("price", "N/A")
        change_pct = item.get("change_pct", "N/A")

        # Determine color from change_pct
        try:
            pct_val = float(change_pct.replace("%", "").replace("+", ""))
            color = _get_change_color(pct_val)
            arrow = "▲" if pct_val >= 0 else "▼"
            change_display = f"{arrow} {change_pct}"
        except (ValueError, AttributeError):
            color = COLORS["text_secondary"]
            change_display = change_pct

        ax.text(0.5, y, name, fontsize=11, color=COLORS["text"], fontfamily=_FONT_FAMILY)
        ax.text(
            5.0,
            y,
            price,
            fontsize=11,
            color=COLORS["text"],
            fontfamily=_FONT_FAMILY,
            ha="center",
        )
        ax.text(
            8.0,
            y,
            change_display,
            fontsize=11,
            color=color,
            fontfamily=_FONT_FAMILY,
            ha="center",
            fontweight="bold",
        )

        y -= 0.55

    # Footer
    ax.text(
        5,
        0.15,
        "Investing Dragon | Auto-generated Market Snapshot",
        ha="center",
        fontsize=8,
        color=COLORS["text_secondary"],
        fontfamily=_FONT_FAMILY,
        style="italic",
    )

    if not filename:
        filename = f"market-snapshot-{date_str}.png"
    filepath = os.path.join(IMAGES_DIR, filename)

    plt.tight_layout(pad=0.5)
    plt.savefig(filepath, dpi=150, facecolor=COLORS["bg"], edgecolor="none", bbox_inches="tight")
    plt.close(fig)

    logger.info("Generated market snapshot card: %s", filename)
    return f"/assets/images/generated/{filename}"


def generate_source_distribution_card(
    sources: List[Dict[str, Any]],
    date_str: str,
    filename: Optional[str] = None,
) -> Optional[str]:
    """Generate a donut chart showing social media source distribution.

    Args:
        sources: List of {"name": "Telegram", "count": 10} dicts.
        date_str: Date string for the title.
        filename: Optional output filename.

    Returns relative path for Jekyll or None on failure.
    """
    if not _MPL_AVAILABLE:
        return None

    _ensure_dir()

    if not sources:
        return None

    donut_colors = [
        COLORS["blue"],
        COLORS["green"],
        COLORS["orange"],
        COLORS["purple"],
        COLORS["red"],
        COLORS["gold"],
        COLORS["silver"],
        COLORS["text_secondary"],
    ]

    names = [s["name"] for s in sources]
    counts = [s["count"] for s in sources]
    total = sum(counts)
    colors = [donut_colors[i % len(donut_colors)] for i in range(len(names))]

    fig, ax = plt.subplots(figsize=(8, 8))
    fig.patch.set_facecolor(COLORS["bg"])
    ax.set_facecolor(COLORS["bg"])

    wedges, _texts, autotexts = ax.pie(
        counts,
        labels=None,
        colors=colors,
        autopct="%1.1f%%",
        startangle=90,
        pctdistance=0.78,
        wedgeprops=dict(width=0.4, edgecolor=COLORS["bg"], linewidth=2),
    )

    for at in autotexts:
        at.set_color(COLORS["text"])
        at.set_fontsize(9)
        at.set_fontfamily("monospace")

    # Center text — total count
    ax.text(
        0,
        0.05,
        str(total),
        ha="center",
        va="center",
        fontsize=36,
        fontweight="bold",
        color=COLORS["text"],
        fontfamily=_FONT_FAMILY,
    )
    ax.text(
        0,
        -0.12,
        "total",
        ha="center",
        va="center",
        fontsize=12,
        color=COLORS["text_secondary"],
        fontfamily=_FONT_FAMILY,
    )

    # Title
    ax.set_title(
        f"Source Distribution — {date_str}",
        fontsize=14,
        fontweight="bold",
        color=COLORS["text"],
        fontfamily=_FONT_FAMILY,
        pad=20,
    )

    # Legend
    legend = ax.legend(
        wedges,
        [f"{n} ({c})" for n, c in zip(names, counts, strict=False)],
        loc="lower center",
        bbox_to_anchor=(0.5, -0.08),
        ncol=min(len(names), 4),
        fontsize=9,
        frameon=False,
    )
    for text in legend.get_texts():
        text.set_color(COLORS["text"])
        text.set_fontfamily("monospace")

    # Footer
    fig.text(
        0.5,
        0.01,
        "Investing Dragon | Auto-generated",
        ha="center",
        fontsize=8,
        color=COLORS["text_secondary"],
        fontfamily=_FONT_FAMILY,
        style="italic",
    )

    if not filename:
        filename = f"source-distribution-{date_str}.png"
    filepath = os.path.join(IMAGES_DIR, filename)

    plt.tight_layout(pad=1.0)
    plt.savefig(filepath, dpi=150, facecolor=COLORS["bg"], edgecolor="none", bbox_inches="tight")
    plt.close(fig)

    logger.info("Generated source distribution card: %s", filename)
    return f"/assets/images/generated/{filename}"


def generate_sector_heatmap(
    sector_data: Dict[str, Dict[str, Any]],
    date_str: str,
    filename: Optional[str] = None,
) -> Optional[str]:
    """Generate a sector performance heatmap showing S&P 500 sector ETFs.

    Args:
        sector_data: Dict of {symbol: {"name": str, "price": str, "change_pct": float}}.
        date_str: Date string for the title.
        filename: Optional output filename.

    Returns relative path for Jekyll or None on failure.
    """
    if not _MPL_AVAILABLE:
        return None

    _ensure_dir()

    if not sector_data:
        return None

    # Sort sectors by change for visual grouping
    sorted_sectors = sorted(sector_data.items(), key=lambda x: x[1].get("change_pct", 0), reverse=True)
    count = len(sorted_sectors)

    # Grid layout: adaptive columns
    cols = 4
    rows = (count + cols - 1) // cols

    fig, ax = plt.subplots(figsize=(14, 3.5 + rows * 1.8))
    fig.patch.set_facecolor(COLORS["bg"])
    ax.set_facecolor(COLORS["bg"])
    ax.axis("off")

    # Title
    ax.text(
        0.5,
        0.97,
        "S&P 500 Sector Performance",
        ha="center",
        va="top",
        transform=ax.transAxes,
        fontsize=18,
        fontweight="bold",
        color=COLORS["text"],
        fontfamily=_FONT_FAMILY,
    )
    ax.text(
        0.5,
        0.93,
        f"{date_str} | Daily Change",
        ha="center",
        va="top",
        transform=ax.transAxes,
        fontsize=10,
        color=COLORS["text_secondary"],
        fontfamily=_FONT_FAMILY,
    )

    margin = 0.03
    cell_w = (1.0 - margin * (cols + 1)) / cols
    cell_h = (0.88 - margin * (rows + 1)) / rows

    for i, (symbol, info) in enumerate(sorted_sectors):
        row = i // cols
        col = i % cols

        x = margin + col * (cell_w + margin)
        y = 0.88 - margin - (row + 1) * (cell_h + margin) + margin

        change = info.get("change_pct", 0)

        # Color based on change intensity
        if change >= 2:
            bg_color = "#1a4d2e"
        elif change >= 0.5:
            bg_color = "#1a3d25"
        elif change >= 0:
            bg_color = "#162d1e"
        elif change >= -0.5:
            bg_color = "#2d1a1a"
        elif change >= -2:
            bg_color = "#3d1a1a"
        else:
            bg_color = "#4d1a1a"

        rect = mpatches.FancyBboxPatch(
            (x, y),
            cell_w,
            cell_h,
            boxstyle="round,pad=0.008",
            facecolor=bg_color,
            edgecolor=COLORS["border"],
            linewidth=0.5,
            transform=ax.transAxes,
        )
        ax.add_patch(rect)

        # ETF Symbol
        ax.text(
            x + cell_w / 2,
            y + cell_h * 0.78,
            symbol,
            ha="center",
            va="center",
            transform=ax.transAxes,
            fontsize=13,
            fontweight="bold",
            color=COLORS["text"],
            fontfamily=_FONT_FAMILY,
        )

        # Sector name - extract English name from "한글 (English)" format
        raw_name = info["name"]
        if "(" in raw_name and ")" in raw_name:
            name_short = raw_name.split("(")[1].rstrip(")")[:15]
        else:
            name_short = _to_en(raw_name)[:15]
        ax.text(
            x + cell_w / 2,
            y + cell_h * 0.55,
            name_short,
            ha="center",
            va="center",
            transform=ax.transAxes,
            fontsize=8,
            color=COLORS["text_secondary"],
            fontfamily=_FONT_FAMILY,
        )

        # Price
        ax.text(
            x + cell_w / 2,
            y + cell_h * 0.35,
            f"${info['price']}",
            ha="center",
            va="center",
            transform=ax.transAxes,
            fontsize=9,
            color=COLORS["text_secondary"],
            fontfamily=_FONT_FAMILY,
        )

        # Change
        change_color = _get_change_color(change)
        arrow = "▲" if change >= 0 else "▼"
        ax.text(
            x + cell_w / 2,
            y + cell_h * 0.15,
            f"{arrow} {abs(change):.2f}%",
            ha="center",
            va="center",
            transform=ax.transAxes,
            fontsize=11,
            fontweight="bold",
            color=change_color,
            fontfamily=_FONT_FAMILY,
        )

    # Footer
    ax.text(
        0.5,
        0.01,
        "Investing Dragon | Auto-generated Sector Heatmap",
        ha="center",
        va="bottom",
        transform=ax.transAxes,
        fontsize=8,
        color=COLORS["text_secondary"],
        fontfamily=_FONT_FAMILY,
        style="italic",
    )

    if not filename:
        filename = f"sector-heatmap-{date_str}.png"
    filepath = os.path.join(IMAGES_DIR, filename)

    plt.savefig(filepath, dpi=150, facecolor=COLORS["bg"], edgecolor="none", bbox_inches="tight")
    plt.close(fig)

    logger.info("Generated sector heatmap: %s", filename)
    return f"/assets/images/generated/{filename}"


def generate_news_briefing_card(
    themes: List[Dict[str, Any]],
    date_str: str,
    category: str = "Daily Briefing",
    total_count: int = 0,
    urgent_alerts: Optional[List[str]] = None,
    filename: Optional[str] = None,
) -> Optional[str]:
    """Generate a high-quality news briefing card image.

    Replaces generate_news_summary_card with a richer layout:
    - Top: date + category + total count
    - Middle: theme icons + counts + top keywords (3-4 themes)
    - Bottom: P0 urgent alert (if present, highlighted)

    Args:
        themes: List of {"name": str, "emoji": str, "count": int,
                "keywords": list[str]} dicts.
        date_str: Date string for the header.
        category: Category label (e.g. "Crypto News", "Stock Market").
        total_count: Total news items collected.
        urgent_alerts: Optional list of P0 alert titles.
        filename: Optional output filename.

    Returns relative path for Jekyll or None on failure.
    """
    if not _MPL_AVAILABLE:
        return None

    _ensure_dir()

    if not themes:
        return None

    display_themes = themes[:5]
    use_emoji = _HAS_EMOJI_FONT
    has_urgent = urgent_alerts and len(urgent_alerts) > 0
    urgent_height = 0.8 if has_urgent else 0
    fig_height = 3.5 + len(display_themes) * 0.7 + urgent_height

    fig, ax = plt.subplots(figsize=(12, fig_height))
    fig.patch.set_facecolor(COLORS["bg"])
    ax.set_facecolor(COLORS["bg"])
    ax.set_xlim(0, 10)
    ax.set_ylim(0, fig_height)
    ax.axis("off")

    # Header background with gradient effect
    header_rect = mpatches.FancyBboxPatch(
        (0.2, fig_height - 1.6),
        9.6,
        1.4,
        boxstyle="round,pad=0.08",
        facecolor="#1a2332",
        edgecolor=COLORS["blue"],
        linewidth=1.5,
    )
    ax.add_patch(header_rect)

    # Title
    ax.text(
        5,
        fig_height - 0.5,
        category,
        ha="center",
        va="center",
        fontsize=20,
        fontweight="bold",
        color=COLORS["text"],
        fontfamily=_FONT_FAMILY,
    )
    ax.text(
        5,
        fig_height - 1.0,
        f"{date_str}  |  {total_count} articles collected",
        ha="center",
        va="center",
        fontsize=11,
        color=COLORS["text_secondary"],
        fontfamily=_FONT_FAMILY,
    )

    # Theme rows
    y_start = fig_height - 2.2

    theme_colors = [
        COLORS["orange"],
        COLORS["blue"],
        COLORS["purple"],
        COLORS["green"],
        COLORS["red"],
    ]

    for i, theme in enumerate(display_themes):
        y = y_start - i * 0.7
        t_color = theme_colors[i % len(theme_colors)]

        # Row background
        row_rect = mpatches.FancyBboxPatch(
            (0.3, y - 0.22),
            9.4,
            0.6,
            boxstyle="round,pad=0.05",
            facecolor=COLORS["bg_card"],
            edgecolor=t_color,
            linewidth=1.0,
            alpha=0.9,
        )
        ax.add_patch(row_rect)

        # Color accent bar
        accent = mpatches.FancyBboxPatch(
            (0.3, y - 0.22),
            0.15,
            0.6,
            boxstyle="round,pad=0.02",
            facecolor=t_color,
            edgecolor="none",
        )
        ax.add_patch(accent)

        # Theme emoji + name
        emoji = theme.get("emoji", "")
        if not use_emoji:
            emoji = ""
        name = _to_en(theme.get("name", ""))
        count = theme.get("count", 0)
        keywords = _filter_en_keywords(theme.get("keywords", []))

        ax.text(
            0.8,
            y + 0.05,
            f"{emoji} {name}".strip(),
            fontsize=13,
            fontweight="bold",
            color=COLORS["text"],
            fontfamily=_FONT_FAMILY,
            va="center",
        )

        # Count badge
        ax.text(
            4.5,
            y + 0.05,
            str(count),
            fontsize=12,
            fontweight="bold",
            color=t_color,
            fontfamily=_FONT_FAMILY,
            va="center",
            ha="center",
        )

        # Keywords
        if keywords:
            kw_str = " · ".join(keywords[:4])
            ax.text(
                5.5,
                y + 0.05,
                kw_str,
                fontsize=9,
                color=COLORS["text_secondary"],
                fontfamily=_FONT_FAMILY,
                va="center",
            )

    # Urgent alerts section
    if has_urgent:
        y_urgent = y_start - len(display_themes) * 0.7 - 0.3
        urgent_rect = mpatches.FancyBboxPatch(
            (0.3, y_urgent - 0.3),
            9.4,
            0.7,
            boxstyle="round,pad=0.05",
            facecolor="#2d1a1a",
            edgecolor=COLORS["red"],
            linewidth=1.5,
        )
        ax.add_patch(urgent_rect)

        ax.text(
            0.8,
            y_urgent + 0.05,
            "URGENT",
            fontsize=12,
            fontweight="bold",
            color=COLORS["red"],
            fontfamily=_FONT_FAMILY,
            va="center",
        )

        alert_text = ""
        if urgent_alerts:
            first_alert = urgent_alerts[0]
            alert_text = first_alert[:60]
            if len(first_alert) > 60:
                alert_text += "..."
        ax.text(
            2.8,
            y_urgent + 0.05,
            alert_text,
            fontsize=10,
            color=COLORS["text"],
            fontfamily=_FONT_FAMILY,
            va="center",
        )

    # Footer
    ax.text(
        5,
        0.2,
        "Investing Dragon | Auto-generated News Briefing",
        ha="center",
        fontsize=8,
        color=COLORS["text_secondary"],
        fontfamily=_FONT_FAMILY,
        style="italic",
    )

    if not filename:
        filename = f"news-briefing-{date_str}.png"
    filepath = os.path.join(IMAGES_DIR, filename)

    plt.tight_layout(pad=0.5)
    plt.savefig(filepath, dpi=150, facecolor=COLORS["bg"], edgecolor="none", bbox_inches="tight")
    plt.close(fig)

    logger.info("Generated news briefing card: %s", filename)
    return f"/assets/images/generated/{filename}"
