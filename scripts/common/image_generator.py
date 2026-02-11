"""Market visualization image generator.

Generates professional market cards, charts, and gauges using matplotlib and Pillow.
Images are saved to assets/images/generated/ for use in Jekyll posts.
"""

import os
import logging
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)

# Import matplotlib once at module level
_MPL_AVAILABLE = False
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    import numpy as np
    _MPL_AVAILABLE = True
except ImportError:
    logger.warning("matplotlib/numpy not available, image generation disabled")

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
IMAGES_DIR = os.path.join(REPO_ROOT, "assets", "images", "generated")

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
    ax.text(5, fig_height - 0.5, "Top 10 Cryptocurrencies by Market Cap",
            ha="center", va="center", fontsize=18, fontweight="bold",
            color=COLORS["text"], fontfamily="monospace")
    ax.text(5, fig_height - 1.0, f"{date_str} | Source: {source}",
            ha="center", va="center", fontsize=10, color=COLORS["text_secondary"],
            fontfamily="monospace")

    # Column headers
    y_start = fig_height - 1.6
    ax.text(0.3, y_start, "#", fontsize=9, fontweight="bold", color=COLORS["text_secondary"], fontfamily="monospace")
    ax.text(1.0, y_start, "Coin", fontsize=9, fontweight="bold", color=COLORS["text_secondary"], fontfamily="monospace")
    ax.text(4.5, y_start, "Price (USD)", fontsize=9, fontweight="bold", color=COLORS["text_secondary"], fontfamily="monospace", ha="right")
    ax.text(6.0, y_start, "24h Change", fontsize=9, fontweight="bold", color=COLORS["text_secondary"], fontfamily="monospace", ha="center")
    ax.text(7.8, y_start, "7d Change", fontsize=9, fontweight="bold", color=COLORS["text_secondary"], fontfamily="monospace", ha="center")
    ax.text(9.7, y_start, "Market Cap", fontsize=9, fontweight="bold", color=COLORS["text_secondary"], fontfamily="monospace", ha="right")

    # Divider
    ax.plot([0.2, 9.8], [y_start - 0.2, y_start - 0.2], color=COLORS["border"], linewidth=0.5)

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
            rect = mpatches.FancyBboxPatch((0.15, y - 0.2), 9.7, 0.55,
                                           boxstyle="round,pad=0.05",
                                           facecolor=COLORS["bg_inner"], edgecolor="none", alpha=0.5)
            ax.add_patch(rect)

        # Rank medal colors
        rank_colors = {0: COLORS["gold"], 1: COLORS["silver"], 2: COLORS["bronze"]}
        rank_color = rank_colors.get(i, COLORS["text_secondary"])

        ax.text(0.4, y, str(i + 1), fontsize=11, fontweight="bold",
                color=rank_color, ha="center", fontfamily="monospace")

        # Coin name
        ax.text(1.0, y + 0.05, name, fontsize=11, fontweight="bold",
                color=COLORS["text"], fontfamily="monospace")
        ax.text(1.0, y - 0.18, full_name[:18], fontsize=7,
                color=COLORS["text_secondary"], fontfamily="monospace")

        # Price
        if price >= 1:
            price_str = f"${price:,.2f}"
        elif price >= 0.01:
            price_str = f"${price:,.4f}"
        else:
            price_str = f"${price:,.6f}"
        ax.text(4.5, y, price_str, fontsize=10, color=COLORS["text"],
                ha="right", fontfamily="monospace")

        # 24h change
        color_24h = _get_change_color(change_24h)
        arrow_24h = "▲" if change_24h >= 0 else "▼"
        ax.text(6.0, y, f"{arrow_24h} {abs(change_24h):.2f}%", fontsize=10,
                color=color_24h, ha="center", fontfamily="monospace", fontweight="bold")

        # 7d change
        color_7d = _get_change_color(change_7d)
        arrow_7d = "▲" if change_7d >= 0 else "▼"
        ax.text(7.8, y, f"{arrow_7d} {abs(change_7d):.2f}%", fontsize=10,
                color=color_7d, ha="center", fontfamily="monospace")

        # Market cap
        if mcap >= 1_000_000_000_000:
            mcap_str = f"${mcap/1e12:.2f}T"
        elif mcap >= 1_000_000_000:
            mcap_str = f"${mcap/1e9:.1f}B"
        elif mcap >= 1_000_000:
            mcap_str = f"${mcap/1e6:.1f}M"
        else:
            mcap_str = f"${mcap:,.0f}"
        ax.text(9.7, y, mcap_str, fontsize=10, color=COLORS["text"],
                ha="right", fontfamily="monospace")

    # Footer
    ax.text(5, 0.2, "Investing Dragon | Auto-generated Market Report",
            ha="center", fontsize=8, color=COLORS["text_secondary"],
            fontfamily="monospace", style="italic")

    if not filename:
        filename = f"top-coins-{date_str}.png"
    filepath = os.path.join(IMAGES_DIR, filename)

    plt.tight_layout(pad=0.5)
    plt.savefig(filepath, dpi=150, facecolor=COLORS["bg"],
                edgecolor="none", bbox_inches="tight")
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
    ax.text(0, 1.45, "Crypto Fear & Greed Index", ha="center", va="center",
            fontsize=16, fontweight="bold", color=COLORS["text"], fontfamily="monospace")
    ax.text(0, 1.25, date_str, ha="center", va="center",
            fontsize=10, color=COLORS["text_secondary"], fontfamily="monospace")

    # Draw gauge arc (semicircle)
    _theta = np.linspace(np.pi, 0, 100)
    r = 1.0

    # Color gradient segments
    segments = [
        (np.pi, np.pi * 0.75, "#f85149"),      # Extreme Fear (red)
        (np.pi * 0.75, np.pi * 0.5, "#d29922"),  # Fear (orange)
        (np.pi * 0.5, np.pi * 0.375, "#8b949e"),  # Neutral (gray)
        (np.pi * 0.375, np.pi * 0.25, "#58a6ff"),  # Greed (blue)
        (np.pi * 0.25, 0, "#3fb950"),             # Extreme Greed (green)
    ]

    for start, end, color in segments:
        t = np.linspace(start, end, 30)
        for j in range(len(t) - 1):
            wedge = mpatches.Wedge((0, 0), r + 0.15, np.degrees(t[j + 1]), np.degrees(t[j]),
                                    width=0.2, facecolor=color, edgecolor="none", alpha=0.8)
            ax.add_patch(wedge)

    # Inner circle
    inner = plt.Circle((0, 0), 0.7, facecolor=COLORS["bg"], edgecolor=COLORS["border"], linewidth=1)
    ax.add_patch(inner)

    # Needle
    needle_angle = np.pi * (1 - value / 100)
    needle_x = 0.65 * np.cos(needle_angle)
    needle_y = 0.65 * np.sin(needle_angle)
    ax.annotate("", xy=(needle_x, needle_y), xytext=(0, 0),
                arrowprops=dict(arrowstyle="-|>", color=COLORS["text"], lw=2.5))

    # Center dot
    center_dot = plt.Circle((0, 0), 0.06, facecolor=COLORS["text"], edgecolor="none")
    ax.add_patch(center_dot)

    # Value display
    ax.text(0, 0.25, str(value), ha="center", va="center",
            fontsize=36, fontweight="bold", color=COLORS["text"], fontfamily="monospace")
    ax.text(0, -0.05, classification, ha="center", va="center",
            fontsize=14, color=COLORS["text_secondary"], fontfamily="monospace")

    # Scale labels
    ax.text(-1.15, -0.15, "0", fontsize=9, color=COLORS["red"], ha="center", fontfamily="monospace")
    ax.text(-0.85, 0.75, "25", fontsize=9, color=COLORS["orange"], ha="center", fontfamily="monospace")
    ax.text(0, 1.05, "50", fontsize=9, color=COLORS["text_secondary"], ha="center", fontfamily="monospace")
    ax.text(0.85, 0.75, "75", fontsize=9, color=COLORS["blue"], ha="center", fontfamily="monospace")
    ax.text(1.15, -0.15, "100", fontsize=9, color=COLORS["green"], ha="center", fontfamily="monospace")

    # Footer
    ax.text(0, -0.45, "Investing Dragon | alternative.me",
            ha="center", fontsize=8, color=COLORS["text_secondary"],
            fontfamily="monospace", style="italic")

    if not filename:
        filename = f"fear-greed-{date_str}.png"
    filepath = os.path.join(IMAGES_DIR, filename)

    plt.tight_layout(pad=0.3)
    plt.savefig(filepath, dpi=150, facecolor=COLORS["bg"],
                edgecolor="none", bbox_inches="tight")
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
    ax.text(0.5, 0.97, "Crypto Market Heatmap - Top 20",
            ha="center", va="top", transform=ax.transAxes,
            fontsize=18, fontweight="bold", color=COLORS["text"], fontfamily="monospace")
    ax.text(0.5, 0.93, f"{date_str} | 24h Price Change",
            ha="center", va="top", transform=ax.transAxes,
            fontsize=10, color=COLORS["text_secondary"], fontfamily="monospace")

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
            (x, y), cell_w, cell_h,
            boxstyle="round,pad=0.008",
            facecolor=bg_color, edgecolor=COLORS["border"], linewidth=0.5,
            transform=ax.transAxes,
        )
        ax.add_patch(rect)

        # Symbol
        ax.text(x + cell_w / 2, y + cell_h * 0.72, symbol,
                ha="center", va="center", transform=ax.transAxes,
                fontsize=14, fontweight="bold", color=COLORS["text"], fontfamily="monospace")

        # Price
        if price >= 1:
            price_str = f"${price:,.2f}"
        else:
            price_str = f"${price:,.4f}"
        ax.text(x + cell_w / 2, y + cell_h * 0.42, price_str,
                ha="center", va="center", transform=ax.transAxes,
                fontsize=9, color=COLORS["text_secondary"], fontfamily="monospace")

        # Change
        change_color = _get_change_color(change)
        arrow = "▲" if change >= 0 else "▼"
        ax.text(x + cell_w / 2, y + cell_h * 0.18, f"{arrow} {abs(change):.2f}%",
                ha="center", va="center", transform=ax.transAxes,
                fontsize=11, fontweight="bold", color=change_color, fontfamily="monospace")

    # Footer
    ax.text(0.5, 0.01, "Investing Dragon | Auto-generated Market Heatmap",
            ha="center", va="bottom", transform=ax.transAxes,
            fontsize=8, color=COLORS["text_secondary"], fontfamily="monospace", style="italic")

    if not filename:
        filename = f"market-heatmap-{date_str}.png"
    filepath = os.path.join(IMAGES_DIR, filename)

    plt.savefig(filepath, dpi=150, facecolor=COLORS["bg"],
                edgecolor="none", bbox_inches="tight")
    plt.close(fig)

    logger.info("Generated market heatmap: %s", filename)
    return f"/assets/images/generated/{filename}"
