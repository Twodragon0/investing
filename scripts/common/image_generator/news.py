"""News briefing card generators.

Generates news summary cards and visual news briefing cards.
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
    _add_market_texture,
    _draw_category_illustration,
    _draw_gradient_bar,
    _draw_metric_chip,
    _draw_mini_donut,
    _draw_rounded_rect,
    _ensure_dir,
    _get_category_bg_drawer,
    _sanitize_og_text,
    _save_and_close,
    _to_en,
    _truncate_text,
    mpatches,
    np,
    plt,
)

logger = logging.getLogger(__name__)


# ===================================================================
# 4. News Summary Card (horizontal bar chart)
# ===================================================================


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
    if not _base._get_pkg_attr("_MPL_AVAILABLE"):
        return None

    _ensure_dir()

    if not categories:
        logger.warning("No source data for summary card")
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
    bars = ax.barh(y_pos, counts, color=colors, height=0.55, edgecolor="none", alpha=0.85)

    # Rounded bar ends via overlay
    for bar, color in zip(bars, colors, strict=False):
        _draw_rounded_rect(
            ax,
            bar.get_x(),
            bar.get_y(),
            bar.get_width(),
            bar.get_height(),
            facecolor=color,
            alpha=0.15,
            pad=0.01,
        )

    ax.set_yticks(y_pos)
    ax.set_yticklabels(names, fontsize=_DS["body_size"], color=COLORS["text"], fontfamily=_FONT_FAMILY)
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
        f"News Source Distribution \u2014 {date_str}",
        fontsize=14,
        fontweight="bold",
        color=COLORS["text"],
        fontfamily=_FONT_FAMILY,
        pad=_DS["pad_title"],
    )

    # Footer
    fig.text(
        0.5,
        0.01,
        f"{_DS['watermark']} | {date_str}",
        ha="center",
        fontsize=_DS["footer_size"],
        color=COLORS["text_secondary"],
        fontfamily=_FONT_FAMILY,
        style="italic",
        alpha=0.65,
    )

    if not filename:
        filename = f"news-summary-{date_str}.png"
    filepath = os.path.join(_base._get_pkg_attr("IMAGES_DIR"), filename)

    plt.tight_layout(pad=1.0)
    _save_and_close(fig, filepath)

    logger.info("Generated news summary card: %s", filename)
    return f"/assets/images/generated/{filename}"


# ===================================================================
# 8. News Briefing Card
# ===================================================================


def generate_news_briefing_card(
    themes: List[Dict[str, Any]],
    date_str: str,
    category: str = "Daily Briefing",
    total_count: int = 0,
    urgent_alerts: Optional[List[str]] = None,
    filename: Optional[str] = None,
) -> Optional[str]:
    """Generate a visual news briefing card with donut chart and gradient bars.

    Layout:
    - Header: category title + date
    - Metric chips row
    - Left: mini donut chart (theme proportions)
    - Right: horizontal gradient bars per theme
    - Bottom: urgent alert (if present)
    - Background: category-specific illustration

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
    if not _base._get_pkg_attr("_MPL_AVAILABLE"):
        return None

    _ensure_dir()

    if not themes:
        logger.warning("No themes provided for briefing card")
        return None

    display_themes = themes[:4]
    has_urgent = urgent_alerts and len(urgent_alerts) > 0
    urgent_height = 1.15 if has_urgent else 0
    n_themes = len(display_themes)
    total_articles = total_count or sum(max(0, int(t.get("count", 0))) for t in display_themes)
    bar_area_h = max(n_themes * 0.78, 3.2)
    fig_height = 5.2 + bar_area_h + urgent_height

    fig, ax = plt.subplots(figsize=(12, fig_height))
    fig.patch.set_facecolor(COLORS["bg"])
    ax.set_facecolor(COLORS["bg"])
    ax.set_xlim(0, 10)
    ax.set_ylim(0, fig_height)
    ax.axis("off")

    cat_type = _get_category_bg_drawer(category)
    _draw_category_illustration(ax, cat_type, 0.3, 0.5, 9.4, fig_height - 1.0, alpha=0.05)
    _add_market_texture(ax, 10, fig_height, accent=COLORS["blue"])

    _draw_rounded_rect(
        ax,
        0.16,
        0.16,
        9.68,
        fig_height - 0.32,
        facecolor="none",
        edgecolor=COLORS["border_highlight"],
        linewidth=1.15,
        alpha=0.6,
        pad=0.08,
    )

    header_y = fig_height - 2.3
    header_h = 1.9
    _draw_gradient_bar(
        ax,
        0.22,
        header_y,
        9.56,
        header_h,
        color_start="#11253d",
        color_end="#0f1928",
        steps=44,
        alpha=0.98,
    )
    _draw_rounded_rect(
        ax,
        0.22,
        header_y,
        9.56,
        header_h,
        facecolor="none",
        edgecolor=COLORS["border_highlight"],
        linewidth=1.0,
        pad=0.08,
    )
    ax.text(
        0.55,
        fig_height - 0.68,
        "MARKET BRIEF",
        fontsize=9,
        fontweight="bold",
        color=COLORS["cyan"],
        fontfamily=_FONT_FAMILY,
        va="center",
    )
    ax.text(
        0.55,
        fig_height - 1.06,
        _sanitize_og_text(category),
        fontsize=23,
        fontweight="bold",
        color=COLORS["text"],
        fontfamily=_FONT_FAMILY,
        va="center",
    )
    ax.text(
        0.55,
        fig_height - 1.48,
        f"{date_str} | key market signals",
        fontsize=10.5,
        color=COLORS["text_secondary"],
        fontfamily=_FONT_FAMILY,
        va="center",
    )

    computed_total = total_articles
    alert_value = str(len(urgent_alerts or []))
    chip_y = header_y - 0.92
    chip_w = 2.84
    chip_gap = 0.2
    _draw_metric_chip(
        ax,
        0.35,
        chip_y,
        chip_w,
        0.72,
        label="Articles",
        value=str(total_articles),
        accent=COLORS["blue"],
    )
    _draw_metric_chip(
        ax,
        0.35 + chip_w + chip_gap,
        chip_y,
        chip_w,
        0.72,
        label="Themes",
        value=str(n_themes),
        accent=COLORS["cyan"],
    )
    _draw_metric_chip(
        ax,
        0.35 + (chip_w + chip_gap) * 2,
        chip_y,
        chip_w + 0.22,
        0.72,
        label="Alerts",
        value=alert_value,
        accent=COLORS["orange"] if has_urgent else COLORS["green"],
        value_color=COLORS["orange"] if has_urgent else COLORS["text"],
    )

    panel_y = chip_y - 0.6
    panel_h = panel_y - 0.38
    _draw_rounded_rect(
        ax,
        0.22,
        0.38,
        9.56,
        panel_h,
        facecolor=COLORS["bg_header"],
        edgecolor=COLORS["border"],
        linewidth=0.9,
        alpha=0.97,
        pad=0.08,
    )

    theme_colors = [
        COLORS["orange"],
        COLORS["blue"],
        COLORS["purple"],
        COLORS["green"],
        COLORS["cyan"],
    ]

    donut_cx = 2.2
    donut_cy = panel_y - panel_h * 0.45
    donut_r = min(panel_h * 0.32, 1.35)
    _draw_mini_donut(
        ax,
        donut_cx,
        donut_cy,
        donut_r,
        display_themes,
        theme_colors,
        center_value=computed_total,
    )

    legend_y_start = donut_cy - donut_r - 0.35
    for i, theme in enumerate(display_themes):
        name = _to_en(theme.get("name", ""))
        t_color = theme_colors[i % len(theme_colors)]
        col = i % 2
        row = i // 2
        lx = 0.55 + col * 1.85
        ly = legend_y_start - row * 0.28
        dot = mpatches.Circle((lx, ly), 0.06, facecolor=t_color, edgecolor="none", alpha=0.9)
        ax.add_patch(dot)
        ax.text(
            lx + 0.14,
            ly,
            _truncate_text(name, 10),
            fontsize=7.5,
            color=COLORS["text_secondary"],
            fontfamily=_FONT_FAMILY,
            va="center",
        )

    bar_x_start = 4.4
    bar_x_end = 9.4
    bar_max_w = bar_x_end - bar_x_start
    max_count = max((max(0, int(t.get("count", 0))) for t in display_themes), default=1) or 1
    bars_top = panel_y - 0.45

    ax.text(
        bar_x_start,
        bars_top + 0.25,
        "Theme Distribution",
        fontsize=9,
        fontweight="bold",
        color=COLORS["text_muted"],
        fontfamily=_FONT_FAMILY,
    )
    ax.plot(
        [bar_x_start, bar_x_end],
        [bars_top + 0.08, bars_top + 0.08],
        color=COLORS["border"],
        linewidth=0.6,
        alpha=0.6,
    )

    for i, theme in enumerate(display_themes):
        y = bars_top - 0.35 - i * 0.78
        t_color = theme_colors[i % len(theme_colors)]
        name = _to_en(theme.get("name", ""))
        count = max(0, int(theme.get("count", 0)))
        share = (count / total_articles * 100) if total_articles else 0.0

        ax.text(
            bar_x_start,
            y + 0.18,
            _truncate_text(name, 20),
            fontsize=11,
            fontweight="bold",
            color=COLORS["text"],
            fontfamily=_FONT_FAMILY,
            va="center",
        )
        ax.text(
            bar_x_end - 0.45,
            y + 0.18,
            f"{share:.0f}%",
            fontsize=10.5,
            fontweight="bold",
            color=t_color,
            fontfamily=_FONT_FAMILY,
            va="center",
            ha="right",
        )

        bar_y = y - 0.12
        bar_h = 0.22
        bar_w = max(bar_max_w * (count / max_count), 0.3)
        _draw_rounded_rect(
            ax,
            bar_x_start,
            bar_y,
            bar_max_w,
            bar_h,
            facecolor=COLORS["bg_inner"],
            alpha=0.5,
            pad=0.005,
        )
        _draw_gradient_bar(
            ax,
            bar_x_start,
            bar_y,
            bar_w,
            bar_h,
            color_start=t_color,
            color_end=COLORS["bg_card"],
            steps=20,
            alpha=0.85,
        )
        _draw_rounded_rect(
            ax,
            bar_x_start,
            bar_y,
            bar_w,
            bar_h,
            facecolor="none",
            edgecolor=t_color,
            linewidth=0.8,
            alpha=0.6,
            pad=0.005,
        )
        ax.text(
            bar_x_start + bar_w + 0.15,
            bar_y + bar_h * 0.5,
            str(count),
            fontsize=11,
            fontweight="bold",
            color=t_color,
            fontfamily=_FONT_FAMILY,
            va="center",
        )

    if has_urgent:
        y_urgent = 0.7 + urgent_height * 0.3
        _draw_rounded_rect(
            ax,
            0.45,
            y_urgent - 0.42,
            9.1,
            0.88,
            facecolor=COLORS["red_dim"],
            edgecolor=COLORS["red"],
            linewidth=1.2,
            alpha=0.96,
            pad=0.03,
        )
        _draw_gradient_bar(
            ax,
            0.45,
            y_urgent + 0.28,
            9.1,
            0.08,
            color_start=COLORS["red"],
            color_end=COLORS["red_dim"],
            steps=28,
            alpha=0.5,
        )
        tri_cx, tri_cy = 0.85, y_urgent + 0.02
        tri = mpatches.RegularPolygon(
            (tri_cx, tri_cy),
            3,
            radius=0.18,
            facecolor=COLORS["red"],
            edgecolor="none",
            alpha=0.3,
        )
        ax.add_patch(tri)
        ax.text(
            tri_cx,
            tri_cy - 0.02,
            "!",
            fontsize=12,
            fontweight="bold",
            color=COLORS["red"],
            fontfamily=_FONT_FAMILY,
            va="center",
            ha="center",
        )
        ax.text(
            1.25,
            y_urgent + 0.02,
            f"ALERT {alert_value}",
            fontsize=11,
            fontweight="bold",
            color=COLORS["red"],
            fontfamily=_FONT_FAMILY,
            va="center",
        )
        alert_text = ""
        if urgent_alerts:
            first_alert = _to_en(urgent_alerts[0])
            alert_text = _truncate_text(_sanitize_og_text(first_alert), 58)
        ax.text(
            2.55,
            y_urgent + 0.02,
            alert_text,
            fontsize=9.8,
            color=COLORS["text"],
            fontfamily=_FONT_FAMILY,
            va="center",
        )

    _add_footer(
        ax,
        _sanitize_og_text(f"{_DS['watermark']} | Visual briefing | {date_str}"),
        y=0.08,
    )

    if not filename:
        filename = f"news-briefing-{date_str}.png"
    filepath = os.path.join(_base._get_pkg_attr("IMAGES_DIR"), filename)

    plt.tight_layout(pad=_DS["pad_outer"])
    _save_and_close(fig, filepath)

    logger.info("Generated news briefing card: %s", filename)
    return f"/assets/images/generated/{filename}"
