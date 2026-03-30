"""Coin and market heatmap chart generators.

Generates top coins ranking cards, fear & greed gauges, and market heatmaps.
"""

import logging
import os
from typing import Any, Dict, List, Optional

from . import base as _base
from .base import (
    _DS,
    _FONT_FAMILY,
    COLORS,
    _add_footer,
    _draw_gradient_bar,
    _draw_rounded_rect,
    _ensure_dir,
    _get_change_color,
    _heatmap_bg_color,
    _safe_float,
    _save_and_close,
    mpatches,
    np,
    plt,
)

logger = logging.getLogger(__name__)


# ===================================================================
# 1. Top Coins Card
# ===================================================================


def generate_top_coins_card(
    coins: List[Dict[str, Any]],
    date_str: str,
    source: str = "coingecko",
    filename: Optional[str] = None,
) -> Optional[str]:
    """Generate a top coins ranking card image.

    Returns relative path for Jekyll or None on failure.
    """
    if not _base._get_pkg_attr("_MPL_AVAILABLE"):
        return None

    _ensure_dir()

    if not coins:
        return None

    display_coins = coins[:15]
    row_h = _DS["row_height"]
    fig_height = 2.6 + len(display_coins) * row_h

    fig, ax = plt.subplots(figsize=(12, fig_height))
    fig.patch.set_facecolor(COLORS["bg"])
    ax.set_facecolor(COLORS["bg"])
    ax.set_xlim(0, 10)
    ax.set_ylim(0, fig_height)
    ax.axis("off")

    # 전체 카드 외곽 border
    _draw_rounded_rect(
        ax,
        0.05,
        0.05,
        9.9,
        fig_height - 0.1,
        facecolor="none",
        edgecolor=COLORS["border_highlight"],
        linewidth=1.0,
        alpha=0.6,
    )

    # 헤더 영역 배경 그라디언트 바
    _draw_gradient_bar(
        ax,
        0.1,
        fig_height - 1.25,
        9.8,
        1.1,
        color_start=COLORS["bg_header"],
        color_end=COLORS["bg"],
        steps=25,
        alpha=0.7,
    )

    # Title
    ax.text(
        5,
        fig_height - 0.5,
        "Top 10 Cryptocurrencies by Market Cap",
        ha="center",
        va="center",
        fontsize=_DS["title_size"],
        fontweight="bold",
        color=COLORS["text"],
        fontfamily=_FONT_FAMILY,
    )
    ax.text(
        5,
        fig_height - 1.0,
        f"{date_str}  |  Source: {source}",
        ha="center",
        va="center",
        fontsize=_DS["subtitle_size"],
        color=COLORS["text_secondary"],
        fontfamily=_FONT_FAMILY,
    )

    # Column headers
    y_start = fig_height - 1.6
    headers = [
        (0.3, "#", "left"),
        (1.0, "Coin", "left"),
        (4.5, "Price (USD)", "right"),
        (5.8, "24h", "center"),
        (7.2, "7d", "center"),
        (9.7, "Market Cap", "right"),
    ]
    for hx, hlabel, ha in headers:
        ax.text(
            hx,
            y_start,
            hlabel,
            fontsize=_DS["header_size"],
            fontweight="bold",
            color=COLORS["text_muted"],
            fontfamily=_FONT_FAMILY,
            ha=ha if ha != "left" else "left",
        )

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

        # Row background (alternating) -- 상위 3개 코인은 더 두드러진 배경색 적용
        if i < 3:
            _draw_rounded_rect(ax, 0.15, y - 0.2, 9.7, 0.55, facecolor=COLORS["bg_inner"], alpha=0.85)
        elif i % 2 == 0:
            _draw_rounded_rect(ax, 0.15, y - 0.2, 9.7, 0.55, facecolor=COLORS["bg_inner"], alpha=0.6)

        # Rank: medal colours for top 3, with larger font
        rank_colors = {0: COLORS["gold"], 1: COLORS["silver"], 2: COLORS["bronze"]}
        rank_color = rank_colors.get(i, COLORS["text_secondary"])
        rank_size = 13 if i < 3 else 11

        # Medal circle for top 3
        if i < 3:
            circle = mpatches.Circle((0.4, y), 0.18, facecolor=rank_color, edgecolor="none", alpha=0.15)
            ax.add_patch(circle)

        ax.text(
            0.4,
            y,
            str(i + 1),
            fontsize=rank_size,
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
            fontsize=_DS["body_size"],
            fontweight="bold",
            color=COLORS["text"],
            fontfamily=_FONT_FAMILY,
        )
        ax.text(
            1.0,
            y - 0.18,
            full_name[:16],
            fontsize=8,
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

        # --- 24h change with mini bar ---
        color_24h = _get_change_color(change_24h)
        arrow_24h = "+" if change_24h >= 0 else ""
        ax.text(
            5.5,
            y,
            f"{arrow_24h}{change_24h:.2f}%",
            fontsize=10,
            color=color_24h,
            ha="left",
            fontfamily=_FONT_FAMILY,
            fontweight="bold",
        )
        # Visual bar for 24h change
        bar_max_w = 0.8
        bar_w = min(abs(change_24h) / 10.0, 1.0) * bar_max_w
        bar_x = 6.4
        _draw_rounded_rect(ax, bar_x, y - 0.06, bar_w, 0.12, facecolor=color_24h, alpha=0.35, pad=0.005)

        # --- 7d change with sparkline ---
        color_7d = _get_change_color(change_7d)
        arrow_7d = "+" if change_7d >= 0 else ""
        ax.text(
            7.0,
            y,
            f"{arrow_7d}{change_7d:.2f}%",
            fontsize=10,
            color=color_7d,
            ha="left",
            fontfamily=_FONT_FAMILY,
        )
        # Draw sparkline from CoinGecko 7d price data if available
        spark_data = None
        if source == "coingecko":
            spark_data = (coin.get("sparkline_in_7d") or {}).get("price")
        if spark_data and len(spark_data) >= 10:
            spark_arr = np.array(spark_data[-24:], dtype=float)  # Last 24 data points (~1 day intervals)
            smin, smax = spark_arr.min(), spark_arr.max()
            if smax > smin:
                spark_norm = (spark_arr - smin) / (smax - smin)
            else:
                spark_norm = np.full(len(spark_arr), 0.5)
            sx = np.linspace(7.9, 8.7, len(spark_norm))
            sy = y - 0.15 + spark_norm * 0.3
            ax.plot(sx, sy, color=color_7d, linewidth=1.2, alpha=0.7, solid_capstyle="round")
            ax.fill_between(sx, y - 0.15, sy, color=color_7d, alpha=0.08)
        else:
            bar_w_7d = min(abs(change_7d) / 15.0, 1.0) * bar_max_w
            bar_x_7d = 7.9
            _draw_rounded_rect(ax, bar_x_7d, y - 0.06, bar_w_7d, 0.12, facecolor=color_7d, alpha=0.3, pad=0.005)

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

    # Row separator lines for readability
    for i in range(len(display_coins)):
        y_line = y_start - 0.5 - i * 0.6 - 0.28
        ax.plot([0.2, 9.8], [y_line, y_line], color=COLORS["border"], linewidth=0.3, alpha=0.5)

    # Footer
    ax.text(
        5,
        0.2,
        f"{_DS['watermark']} | {date_str}",
        ha="center",
        fontsize=_DS["footer_size"],
        color=COLORS["text_secondary"],
        fontfamily=_FONT_FAMILY,
        style="italic",
        alpha=0.65,
    )

    if not filename:
        filename = f"top-coins-{date_str}.png"
    filepath = os.path.join(_base._get_pkg_attr("IMAGES_DIR"), filename)

    plt.tight_layout(pad=_DS["pad_outer"])
    _save_and_close(fig, filepath)

    logger.info("Generated top coins card: %s", filename)
    return f"/assets/images/generated/{filename}"


# ===================================================================
# 2. Fear & Greed Gauge
# ===================================================================


def generate_fear_greed_gauge(
    value: int,
    classification: str,
    date_str: str,
    filename: Optional[str] = None,
) -> Optional[str]:
    """Generate a Fear & Greed gauge image."""
    if not _base._get_pkg_attr("_MPL_AVAILABLE"):
        return None

    # Clamp value to valid range
    value = max(0, min(100, int(value)))

    _ensure_dir()

    fig, ax = plt.subplots(figsize=(8, 7.0))
    fig.patch.set_facecolor(COLORS["bg"])
    ax.set_facecolor(COLORS["bg"])
    ax.set_xlim(-1.6, 1.6)
    ax.set_ylim(-0.6, 1.75)
    ax.set_aspect("equal")
    ax.axis("off")

    # Title
    ax.text(
        0,
        1.65,
        "Crypto Fear & Greed Index",
        ha="center",
        va="center",
        fontsize=_DS["title_size"],
        fontweight="bold",
        color=COLORS["text"],
        fontfamily=_FONT_FAMILY,
    )
    ax.text(
        0,
        1.45,
        date_str,
        ha="center",
        va="center",
        fontsize=_DS["subtitle_size"],
        color=COLORS["text_secondary"],
        fontfamily=_FONT_FAMILY,
    )

    # --- Gradient arc segments ---
    r_outer = 1.15
    r_inner = 0.82
    arc_width = r_outer - r_inner

    segment_defs = [
        (np.pi, np.pi * 0.75, COLORS["red"], COLORS["red"]),
        (np.pi * 0.75, np.pi * 0.50, COLORS["orange"], COLORS["orange"]),
        (np.pi * 0.50, np.pi * 0.375, COLORS["text_secondary"], COLORS["text_secondary"]),
        (np.pi * 0.375, np.pi * 0.25, COLORS["blue"], COLORS["blue"]),
        (np.pi * 0.25, 0, COLORS["green"], COLORS["green"]),
    ]

    for start, end, c_start, c_end in segment_defs:
        from matplotlib.colors import to_rgba

        c0 = np.array(to_rgba(c_start))
        c1 = np.array(to_rgba(c_end))
        n_steps = 40
        t_vals = np.linspace(start, end, n_steps + 1)
        for j in range(n_steps):
            frac = j / max(n_steps - 1, 1)
            c_mix = c0 * (1 - frac) + c1 * frac
            # Brightness gradient: brighter toward outer edge
            alpha_val = 0.65 + 0.35 * frac
            wedge = mpatches.Wedge(
                (0, 0),
                r_outer,
                np.degrees(t_vals[j + 1]),
                np.degrees(t_vals[j]),
                width=arc_width,
                facecolor=c_mix,
                edgecolor="none",
                alpha=alpha_val,
            )
            ax.add_patch(wedge)

    # Outer glow ring
    glow = mpatches.Wedge(
        (0, 0),
        r_outer + 0.03,
        0,
        180,
        width=0.03,
        facecolor="none",
        edgecolor=COLORS["border_highlight"],
        linewidth=0.8,
        alpha=0.5,
    )
    ax.add_patch(glow)

    # Inner filled circle
    inner = mpatches.Circle(
        (0, 0),
        r_inner - 0.04,
        facecolor=COLORS["bg"],
        edgecolor=COLORS["border"],
        linewidth=1.5,
    )
    ax.add_patch(inner)

    # --- Needle ---
    needle_angle = np.pi * (1 - value / 100)
    needle_len = r_inner - 0.08
    needle_x = needle_len * np.cos(needle_angle)
    needle_y = needle_len * np.sin(needle_angle)
    # 바늘 그림자 효과 (약간 offset으로 어둡게)
    shadow_offset = 0.02
    ax.annotate(
        "",
        xy=(needle_x + shadow_offset, needle_y - shadow_offset),
        xytext=(shadow_offset, -shadow_offset),
        arrowprops=dict(arrowstyle="-|>", color="#000000", lw=3.0, alpha=0.3),
    )
    # 실제 바늘
    ax.annotate(
        "",
        xy=(needle_x, needle_y),
        xytext=(0, 0),
        arrowprops=dict(arrowstyle="-|>", color=COLORS["text"], lw=2.5),
    )

    # Center dot
    center_dot = mpatches.Circle(
        (0, 0),
        0.07,
        facecolor=COLORS["text"],
        edgecolor=COLORS["bg"],
        linewidth=2,
    )
    ax.add_patch(center_dot)

    # --- Value display (larger, bolder) ---
    # Color the value according to the gauge segment
    if value <= 25:
        val_color = COLORS["red"]
    elif value <= 45:
        val_color = COLORS["orange"]
    elif value <= 55:
        val_color = COLORS["text_secondary"]
    elif value <= 75:
        val_color = COLORS["blue"]
    else:
        val_color = COLORS["green"]

    ax.text(
        0,
        0.33,
        str(value),
        ha="center",
        va="center",
        fontsize=48,
        fontweight="bold",
        color=val_color,
        fontfamily=_FONT_FAMILY,
    )
    # "/ 100" 보조 텍스트
    ax.text(
        0,
        0.10,
        "/ 100",
        ha="center",
        va="center",
        fontsize=12,
        color=COLORS["text_muted"],
        fontfamily=_FONT_FAMILY,
    )
    ax.text(
        0,
        -0.05,
        classification,
        ha="center",
        va="center",
        fontsize=16,
        fontweight="bold",
        color=COLORS["text_secondary"],
        fontfamily=_FONT_FAMILY,
    )

    # --- Segment labels along the arc ---
    label_r = r_outer + 0.22
    zone_labels = [
        (np.pi * 0.875, "Extreme\nFear", COLORS["red"]),
        (np.pi * 0.625, "Fear", COLORS["orange"]),
        (np.pi * 0.4375, "Neutral", COLORS["text_secondary"]),
        (np.pi * 0.3125, "Greed", COLORS["blue"]),
        (np.pi * 0.125, "Extreme\nGreed", COLORS["green"]),
    ]
    for angle, label, color in zone_labels:
        lx = label_r * np.cos(angle)
        ly = label_r * np.sin(angle)
        ax.text(
            lx,
            ly,
            label,
            fontsize=7,
            color=color,
            ha="center",
            va="center",
            fontfamily=_FONT_FAMILY,
            fontweight="bold",
            linespacing=1.0,
        )

    # Scale tick numbers
    for tick_val, tick_angle, tick_color in [
        ("0", np.pi, COLORS["red"]),
        ("25", np.pi * 0.75, COLORS["orange"]),
        ("50", np.pi * 0.5, COLORS["text_secondary"]),
        ("75", np.pi * 0.25, COLORS["blue"]),
        ("100", 0, COLORS["green"]),
    ]:
        tx = (r_outer + 0.04) * np.cos(tick_angle)
        ty = (r_outer + 0.04) * np.sin(tick_angle)
        ax.text(
            tx,
            ty,
            tick_val,
            fontsize=8,
            color=tick_color,
            ha="center",
            va="center",
            fontfamily=_FONT_FAMILY,
        )

    # Footer
    ax.text(
        0,
        -0.50,
        f"{_DS['watermark']} | {date_str} | alternative.me",
        ha="center",
        fontsize=_DS["footer_size"],
        color=COLORS["text_secondary"],
        fontfamily=_FONT_FAMILY,
        style="italic",
        alpha=0.65,
    )

    if not filename:
        filename = f"fear-greed-{date_str}.png"
    filepath = os.path.join(_base._get_pkg_attr("IMAGES_DIR"), filename)

    plt.tight_layout(pad=0.3)
    _save_and_close(fig, filepath)

    logger.info("Generated fear & greed gauge: %s", filename)
    return f"/assets/images/generated/{filename}"


# ===================================================================
# 3. Market Heatmap
# ===================================================================


def generate_market_heatmap(
    coins: List[Dict[str, Any]],
    date_str: str,
    source: str = "coingecko",
    filename: Optional[str] = None,
) -> Optional[str]:
    """Generate a market heatmap showing top coins by market cap with color-coded changes."""
    if not _base._get_pkg_attr("_MPL_AVAILABLE"):
        return None

    _ensure_dir()

    if not coins:
        return None

    display_coins = coins[:20]

    # Calculate dynamic color scale from actual data range (minimum 3.0)
    _changes = []
    for c in display_coins:
        if source == "coingecko":
            _changes.append(_safe_float(c.get("price_change_percentage_24h", 0)))
        else:
            _changes.append(_safe_float(c.get("quote", {}).get("USD", {}).get("percent_change_24h", 0)))
    max_change = max(max(abs(v) for v in _changes) if _changes else 5.0, 3.0)

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
        fontsize=_DS["title_size"],
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
        fontsize=_DS["subtitle_size"],
        color=COLORS["text_secondary"],
        fontfamily=_FONT_FAMILY,
    )

    # Grid layout (5 cols x 4 rows) with wider gap
    cols, rows = 5, 4
    margin = 0.025
    gap = 0.008  # inter-cell gap
    cell_w = (1.0 - margin * 2 - gap * (cols - 1)) / cols
    cell_h = (0.88 - margin * 2 - gap * (rows - 1)) / rows

    for i, coin in enumerate(display_coins):
        row = i // cols
        col = i % cols

        x = margin + col * (cell_w + gap)
        y = 0.88 - margin - (row + 1) * (cell_h + gap) + gap

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

        # Dynamic background color scaling with change magnitude
        bg_color = _heatmap_bg_color(change, extreme=max_change)

        # Cell border highlight for large movers
        edge_color = COLORS["border"]
        edge_width = 0.5
        if abs(change) >= 5:
            edge_color = _get_change_color(change)
            edge_width = 1.2

        _draw_rounded_rect(
            ax,
            x,
            y,
            cell_w,
            cell_h,
            facecolor=bg_color,
            edgecolor=edge_color,
            linewidth=edge_width,
            transform=ax.transAxes,
            pad=0.008,
        )

        # 순위 번호 (왼쪽 상단 코너에 작게 표시)
        ax.text(
            x + 0.012,
            y + cell_h - 0.012,
            str(i + 1),
            ha="left",
            va="top",
            transform=ax.transAxes,
            fontsize=7,
            color=COLORS["text_muted"],
            fontfamily=_FONT_FAMILY,
            alpha=0.8,
        )

        # Symbol -- larger, bolder
        ax.text(
            x + cell_w / 2,
            y + cell_h * 0.72,
            symbol,
            ha="center",
            va="center",
            transform=ax.transAxes,
            fontsize=15,
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
            y + cell_h * 0.44,
            price_str,
            ha="center",
            va="center",
            transform=ax.transAxes,
            fontsize=_DS["small_size"],
            color=COLORS["text_secondary"],
            fontfamily=_FONT_FAMILY,
        )

        # Change -- with sign prefix instead of arrow for clarity
        change_color = _get_change_color(change)
        sign = "+" if change >= 0 else ""

        # Sparkline overlay if available
        spark_data = None
        if source == "coingecko":
            spark_data = (coin.get("sparkline_in_7d") or {}).get("price")
        if spark_data and len(spark_data) >= 10:
            spark_arr = np.array(spark_data[-48:], dtype=float)
            smin, smax = spark_arr.min(), spark_arr.max()
            if smax > smin:
                spark_norm = (spark_arr - smin) / (smax - smin)
            else:
                spark_norm = np.full(len(spark_arr), 0.5)
            sx = np.linspace(x + 0.01, x + cell_w - 0.01, len(spark_norm))
            sy_base = y + cell_h * 0.02
            sy = sy_base + spark_norm * (cell_h * 0.28)
            ax.plot(
                sx, sy, color=change_color, linewidth=0.8, alpha=0.5, transform=ax.transAxes, solid_capstyle="round"
            )
            ax.fill_between(sx, sy_base, sy, color=change_color, alpha=0.06, transform=ax.transAxes)
            # Change text above sparkline
            ax.text(
                x + cell_w / 2,
                y + cell_h * 0.35,
                f"{sign}{change:.2f}%",
                ha="center",
                va="center",
                transform=ax.transAxes,
                fontsize=12,
                fontweight="bold",
                color=change_color,
                fontfamily=_FONT_FAMILY,
            )
        else:
            ax.text(
                x + cell_w / 2,
                y + cell_h * 0.18,
                f"{sign}{change:.2f}%",
                ha="center",
                va="center",
                transform=ax.transAxes,
                fontsize=12,
                fontweight="bold",
                color=change_color,
                fontfamily=_FONT_FAMILY,
            )

    # Color scale legend at bottom
    legend_y = 0.03
    legend_h = 0.018
    legend_x_start = 0.25
    legend_w = 0.50
    n_legend = 40
    legend_extreme = max_change
    for li in range(n_legend):
        frac = li / (n_legend - 1)
        pct = -legend_extreme + 2 * legend_extreme * frac
        lc = _heatmap_bg_color(pct, extreme=legend_extreme)
        strip_w = legend_w / n_legend
        rect = mpatches.Rectangle(
            (legend_x_start + li * strip_w, legend_y),
            strip_w,
            legend_h,
            facecolor=lc,
            edgecolor="none",
            transform=ax.transAxes,
        )
        ax.add_patch(rect)
    ax.text(
        legend_x_start - 0.02,
        legend_y + legend_h / 2,
        f"-{legend_extreme:.0f}%",
        ha="right",
        va="center",
        transform=ax.transAxes,
        fontsize=9,
        fontweight="bold",
        color=COLORS["red"],
        fontfamily=_FONT_FAMILY,
    )
    ax.text(
        legend_x_start + legend_w + 0.02,
        legend_y + legend_h / 2,
        f"+{legend_extreme:.0f}%",
        ha="left",
        va="center",
        transform=ax.transAxes,
        fontsize=9,
        fontweight="bold",
        color=COLORS["green"],
        fontfamily=_FONT_FAMILY,
    )
    # 범례 중앙 레이블
    ax.text(
        legend_x_start + legend_w / 2,
        legend_y + legend_h + 0.012,
        "24h Change",
        ha="center",
        va="bottom",
        transform=ax.transAxes,
        fontsize=7,
        color=COLORS["text_muted"],
        fontfamily=_FONT_FAMILY,
    )

    _add_footer(ax, f"{_DS['watermark']} | {date_str}")

    if not filename:
        filename = f"market-heatmap-{date_str}.png"
    filepath = os.path.join(_base._get_pkg_attr("IMAGES_DIR"), filename)

    _save_and_close(fig, filepath)

    logger.info("Generated market heatmap: %s", filename)
    return f"/assets/images/generated/{filename}"
