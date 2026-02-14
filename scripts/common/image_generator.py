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
        COLORS["blue"], COLORS["green"], COLORS["orange"],
        COLORS["purple"], COLORS["red"], COLORS["gold"],
        COLORS["silver"], COLORS["text_secondary"],
    ]

    names = [c["name"] for c in categories]
    counts = [c["count"] for c in categories]
    colors = [bar_colors[i % len(bar_colors)] for i in range(len(names))]

    fig, ax = plt.subplots(figsize=(10, 5))
    fig.patch.set_facecolor(COLORS["bg"])
    ax.set_facecolor(COLORS["bg"])

    y_pos = np.arange(len(names))
    bars = ax.barh(y_pos, counts, color=colors, height=0.6, edgecolor="none")

    ax.set_yticks(y_pos)
    ax.set_yticklabels(names, fontsize=11, color=COLORS["text"], fontfamily="monospace")
    ax.invert_yaxis()

    ax.set_xlabel("Articles", fontsize=10, color=COLORS["text_secondary"], fontfamily="monospace")
    ax.tick_params(axis="x", colors=COLORS["text_secondary"])
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["bottom"].set_color(COLORS["border"])
    ax.spines["left"].set_color(COLORS["border"])

    # Value labels on bars
    for bar, count in zip(bars, counts):
        ax.text(bar.get_width() + 0.3, bar.get_y() + bar.get_height() / 2,
                str(count), va="center", fontsize=10, color=COLORS["text"],
                fontfamily="monospace", fontweight="bold")

    ax.set_title(f"News Source Distribution — {date_str}",
                 fontsize=14, fontweight="bold", color=COLORS["text"],
                 fontfamily="monospace", pad=15)

    # Footer
    fig.text(0.5, 0.01, "Investing Dragon | Auto-generated",
             ha="center", fontsize=8, color=COLORS["text_secondary"],
             fontfamily="monospace", style="italic")

    if not filename:
        filename = f"news-summary-{date_str}.png"
    filepath = os.path.join(IMAGES_DIR, filename)

    plt.tight_layout(pad=1.0)
    plt.savefig(filepath, dpi=150, facecolor=COLORS["bg"],
                edgecolor="none", bbox_inches="tight")
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
    ax.text(5, fig_height - 0.5, "Market Snapshot",
            ha="center", va="center", fontsize=18, fontweight="bold",
            color=COLORS["text"], fontfamily="monospace")
    ax.text(5, fig_height - 1.0, f"{date_str} | US & Korean Markets",
            ha="center", va="center", fontsize=10, color=COLORS["text_secondary"],
            fontfamily="monospace")

    # Column headers
    y_start = fig_height - 1.5
    ax.text(0.5, y_start, "Index / ETF", fontsize=9, fontweight="bold",
            color=COLORS["text_secondary"], fontfamily="monospace")
    ax.text(5.0, y_start, "Price", fontsize=9, fontweight="bold",
            color=COLORS["text_secondary"], fontfamily="monospace", ha="center")
    ax.text(8.0, y_start, "Change", fontsize=9, fontweight="bold",
            color=COLORS["text_secondary"], fontfamily="monospace", ha="center")

    ax.plot([0.3, 9.7], [y_start - 0.2, y_start - 0.2],
            color=COLORS["border"], linewidth=0.5)

    current_section = None
    y = y_start - 0.5

    for i, item in enumerate(market_data):
        section = item.get("section", "")
        if section and section != current_section:
            current_section = section
            ax.text(0.5, y, section, fontsize=10, fontweight="bold",
                    color=COLORS["blue"], fontfamily="monospace")
            y -= 0.45

        # Row background
        if i % 2 == 0:
            rect = mpatches.FancyBboxPatch((0.3, y - 0.18), 9.4, 0.5,
                                           boxstyle="round,pad=0.05",
                                           facecolor=COLORS["bg_inner"],
                                           edgecolor="none", alpha=0.5)
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

        ax.text(0.5, y, name, fontsize=11, color=COLORS["text"], fontfamily="monospace")
        ax.text(5.0, y, price, fontsize=11, color=COLORS["text"],
                fontfamily="monospace", ha="center")
        ax.text(8.0, y, change_display, fontsize=11, color=color,
                fontfamily="monospace", ha="center", fontweight="bold")

        y -= 0.55

    # Footer
    ax.text(5, 0.15, "Investing Dragon | Auto-generated Market Snapshot",
            ha="center", fontsize=8, color=COLORS["text_secondary"],
            fontfamily="monospace", style="italic")

    if not filename:
        filename = f"market-snapshot-{date_str}.png"
    filepath = os.path.join(IMAGES_DIR, filename)

    plt.tight_layout(pad=0.5)
    plt.savefig(filepath, dpi=150, facecolor=COLORS["bg"],
                edgecolor="none", bbox_inches="tight")
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
        COLORS["blue"], COLORS["green"], COLORS["orange"],
        COLORS["purple"], COLORS["red"], COLORS["gold"],
        COLORS["silver"], COLORS["text_secondary"],
    ]

    names = [s["name"] for s in sources]
    counts = [s["count"] for s in sources]
    total = sum(counts)
    colors = [donut_colors[i % len(donut_colors)] for i in range(len(names))]

    fig, ax = plt.subplots(figsize=(8, 8))
    fig.patch.set_facecolor(COLORS["bg"])
    ax.set_facecolor(COLORS["bg"])

    wedges, _texts, autotexts = ax.pie(
        counts, labels=None, colors=colors, autopct="%1.1f%%",
        startangle=90, pctdistance=0.78,
        wedgeprops=dict(width=0.4, edgecolor=COLORS["bg"], linewidth=2),
    )

    for at in autotexts:
        at.set_color(COLORS["text"])
        at.set_fontsize(9)
        at.set_fontfamily("monospace")

    # Center text — total count
    ax.text(0, 0.05, str(total), ha="center", va="center",
            fontsize=36, fontweight="bold", color=COLORS["text"], fontfamily="monospace")
    ax.text(0, -0.12, "total", ha="center", va="center",
            fontsize=12, color=COLORS["text_secondary"], fontfamily="monospace")

    # Title
    ax.set_title(f"Source Distribution — {date_str}",
                 fontsize=14, fontweight="bold", color=COLORS["text"],
                 fontfamily="monospace", pad=20)

    # Legend
    legend = ax.legend(wedges, [f"{n} ({c})" for n, c in zip(names, counts)],
                       loc="lower center", bbox_to_anchor=(0.5, -0.08),
                       ncol=min(len(names), 4), fontsize=9,
                       frameon=False)
    for text in legend.get_texts():
        text.set_color(COLORS["text"])
        text.set_fontfamily("monospace")

    # Footer
    fig.text(0.5, 0.01, "Investing Dragon | Auto-generated",
             ha="center", fontsize=8, color=COLORS["text_secondary"],
             fontfamily="monospace", style="italic")

    if not filename:
        filename = f"source-distribution-{date_str}.png"
    filepath = os.path.join(IMAGES_DIR, filename)

    plt.tight_layout(pad=1.0)
    plt.savefig(filepath, dpi=150, facecolor=COLORS["bg"],
                edgecolor="none", bbox_inches="tight")
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
    ax.text(0.5, 0.97, "S&P 500 Sector Performance",
            ha="center", va="top", transform=ax.transAxes,
            fontsize=18, fontweight="bold", color=COLORS["text"], fontfamily="monospace")
    ax.text(0.5, 0.93, f"{date_str} | Daily Change",
            ha="center", va="top", transform=ax.transAxes,
            fontsize=10, color=COLORS["text_secondary"], fontfamily="monospace")

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
            (x, y), cell_w, cell_h,
            boxstyle="round,pad=0.008",
            facecolor=bg_color, edgecolor=COLORS["border"], linewidth=0.5,
            transform=ax.transAxes,
        )
        ax.add_patch(rect)

        # ETF Symbol
        ax.text(x + cell_w / 2, y + cell_h * 0.78, symbol,
                ha="center", va="center", transform=ax.transAxes,
                fontsize=13, fontweight="bold", color=COLORS["text"], fontfamily="monospace")

        # Sector name (truncated)
        name_short = info["name"].split("(")[0].strip()[:12]
        ax.text(x + cell_w / 2, y + cell_h * 0.55, name_short,
                ha="center", va="center", transform=ax.transAxes,
                fontsize=8, color=COLORS["text_secondary"], fontfamily="monospace")

        # Price
        ax.text(x + cell_w / 2, y + cell_h * 0.35, f"${info['price']}",
                ha="center", va="center", transform=ax.transAxes,
                fontsize=9, color=COLORS["text_secondary"], fontfamily="monospace")

        # Change
        change_color = _get_change_color(change)
        arrow = "▲" if change >= 0 else "▼"
        ax.text(x + cell_w / 2, y + cell_h * 0.15, f"{arrow} {abs(change):.2f}%",
                ha="center", va="center", transform=ax.transAxes,
                fontsize=11, fontweight="bold", color=change_color, fontfamily="monospace")

    # Footer
    ax.text(0.5, 0.01, "Investing Dragon | Auto-generated Sector Heatmap",
            ha="center", va="bottom", transform=ax.transAxes,
            fontsize=8, color=COLORS["text_secondary"], fontfamily="monospace", style="italic")

    if not filename:
        filename = f"sector-heatmap-{date_str}.png"
    filepath = os.path.join(IMAGES_DIR, filename)

    plt.savefig(filepath, dpi=150, facecolor=COLORS["bg"],
                edgecolor="none", bbox_inches="tight")
    plt.close(fig)

    logger.info("Generated sector heatmap: %s", filename)
    return f"/assets/images/generated/{filename}"


def generate_indicator_dashboard(
    indicators: Dict[str, Any],
    date_str: str,
    filename: Optional[str] = None,
) -> Optional[str]:
    """Generate a key indicators dashboard card.

    Args:
        indicators: Dict with optional keys:
            - fear_greed: {"value": int, "classification": str}
            - yield_spread: {"spread": float, "inverted": bool}
            - vix: {"label": str, "value": float}
            - dxy: {"price": str, "change_pct": str}
            - btc_dominance: float
        date_str: Date string for the title.
        filename: Optional output filename.

    Returns relative path for Jekyll or None on failure.
    """
    if not _MPL_AVAILABLE:
        return None

    _ensure_dir()

    if not indicators:
        return None

    # Build indicator cards
    cards = []
    if "fear_greed" in indicators:
        fg = indicators["fear_greed"]
        val = fg.get("value", 0)
        cls = fg.get("classification", "N/A")
        if val <= 25:
            color = COLORS["red"]
        elif val <= 50:
            color = COLORS["orange"]
        elif val <= 75:
            color = COLORS["blue"]
        else:
            color = COLORS["green"]
        cards.append(("공포/탐욕", str(val), cls, color))

    if "vix" in indicators:
        vix = indicators["vix"]
        val = vix.get("value", 0)
        color = COLORS["red"] if val > 30 else (COLORS["orange"] if val > 20 else COLORS["green"])
        cards.append(("VIX", f"{val:.1f}", "변동성 지수", color))

    if "yield_spread" in indicators:
        ys = indicators["yield_spread"]
        spread = ys.get("spread", 0)
        inverted = ys.get("inverted", False)
        color = COLORS["red"] if inverted else COLORS["green"]
        status = "역전" if inverted else "정상"
        cards.append(("2Y-10Y 스프레드", f"{spread:+.2f}%", status, color))

    if "dxy" in indicators:
        dxy = indicators["dxy"]
        cards.append(("달러 인덱스", dxy.get("price", "N/A"), "DXY", COLORS["blue"]))

    if "btc_dominance" in indicators:
        dom = indicators["btc_dominance"]
        color = COLORS["orange"] if dom > 55 else COLORS["blue"]
        cards.append(("BTC 도미넌스", f"{dom:.1f}%", "비트코인 점유율", color))

    if not cards:
        return None

    # Layout
    cols = min(len(cards), 5)
    fig_width = max(cols * 3.0, 10)
    fig, ax = plt.subplots(figsize=(fig_width, 3.5))
    fig.patch.set_facecolor(COLORS["bg"])
    ax.set_facecolor(COLORS["bg"])
    ax.axis("off")

    # Title
    ax.text(0.5, 0.95, "Key Indicators Dashboard",
            ha="center", va="top", transform=ax.transAxes,
            fontsize=16, fontweight="bold", color=COLORS["text"], fontfamily="monospace")
    ax.text(0.5, 0.85, date_str,
            ha="center", va="top", transform=ax.transAxes,
            fontsize=9, color=COLORS["text_secondary"], fontfamily="monospace")

    margin = 0.03
    card_w = (1.0 - margin * (cols + 1)) / cols

    for i, (label, value, subtitle, color) in enumerate(cards):
        x = margin + i * (card_w + margin)
        y = 0.1

        # Card background
        rect = mpatches.FancyBboxPatch(
            (x, y), card_w, 0.65,
            boxstyle="round,pad=0.015",
            facecolor=COLORS["bg_card"], edgecolor=color, linewidth=1.5,
            transform=ax.transAxes,
        )
        ax.add_patch(rect)

        # Color accent bar at top
        bar = mpatches.FancyBboxPatch(
            (x, y + 0.60), card_w, 0.05,
            boxstyle="round,pad=0.008",
            facecolor=color, edgecolor="none",
            transform=ax.transAxes,
        )
        ax.add_patch(bar)

        # Label
        ax.text(x + card_w / 2, y + 0.52, label,
                ha="center", va="center", transform=ax.transAxes,
                fontsize=9, color=COLORS["text_secondary"], fontfamily="monospace")

        # Value (large)
        ax.text(x + card_w / 2, y + 0.35, value,
                ha="center", va="center", transform=ax.transAxes,
                fontsize=20, fontweight="bold", color=color, fontfamily="monospace")

        # Subtitle
        ax.text(x + card_w / 2, y + 0.15, subtitle,
                ha="center", va="center", transform=ax.transAxes,
                fontsize=8, color=COLORS["text_secondary"], fontfamily="monospace")

    # Footer
    ax.text(0.5, 0.02, "Investing Dragon | Auto-generated Indicators",
            ha="center", va="bottom", transform=ax.transAxes,
            fontsize=7, color=COLORS["text_secondary"], fontfamily="monospace", style="italic")

    if not filename:
        filename = f"indicator-dashboard-{date_str}.png"
    filepath = os.path.join(IMAGES_DIR, filename)

    plt.tight_layout(pad=0.3)
    plt.savefig(filepath, dpi=150, facecolor=COLORS["bg"],
                edgecolor="none", bbox_inches="tight")
    plt.close(fig)

    logger.info("Generated indicator dashboard: %s", filename)
    return f"/assets/images/generated/{filename}"
