"""Market analysis chart generators.

Generates market snapshot cards, source distribution donuts, and sector heatmaps.
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
    _draw_gradient_bar,
    _draw_line_chart_bg,
    _draw_metric_chip,
    _draw_rounded_rect,
    _ensure_dir,
    _get_change_color,
    _heatmap_bg_color,
    _save_and_close,
    _to_en,
    _truncate_text,
    mpatches,
    np,
    plt,
)

logger = logging.getLogger(__name__)


# ===================================================================
# 5. Market Snapshot Card
# ===================================================================


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
    if not _base._get_pkg_attr("_MPL_AVAILABLE"):
        return None

    _ensure_dir()

    if not market_data:
        logger.warning("No market data for snapshot card")
        return None

    row_count = len(market_data)
    section_count = len({item.get("section", "") for item in market_data if item.get("section")})
    fig_height = 4.8 + row_count * 0.72 + section_count * 0.52
    fig, ax = plt.subplots(figsize=(12, fig_height))
    fig.patch.set_facecolor(COLORS["bg"])
    ax.set_facecolor(COLORS["bg"])
    ax.set_xlim(0, 10)
    ax.set_ylim(0, fig_height)
    ax.axis("off")
    _draw_line_chart_bg(ax, 0.3, 0.5, 9.4, fig_height - 1.0, alpha=0.04)
    _add_market_texture(ax, 10, fig_height, accent=COLORS["green"])
    _draw_rounded_rect(
        ax,
        0.16,
        0.16,
        9.68,
        fig_height - 0.32,
        facecolor="none",
        edgecolor=COLORS["border_highlight"],
        linewidth=1.2,
        alpha=0.6,
        pad=0.08,
    )

    header_y = fig_height - 2.1
    header_h = 1.7
    _draw_gradient_bar(
        ax,
        0.22,
        header_y,
        9.56,
        header_h,
        color_start="#13334a",
        color_end="#10202f",
        steps=48,
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
        fig_height - 0.62,
        "GLOBAL MARKET SNAPSHOT",
        fontsize=9,
        fontweight="bold",
        color=COLORS["cyan"],
        fontfamily=_FONT_FAMILY,
        va="center",
    )
    ax.text(
        0.55,
        fig_height - 1.08,
        "US and Korea indices, ETFs, FX and risk tone",
        fontsize=10,
        color=COLORS["text_secondary"],
        fontfamily=_FONT_FAMILY,
        va="center",
    )
    ax.text(
        0.55,
        fig_height - 1.55,
        date_str,
        fontsize=24,
        fontweight="bold",
        color=COLORS["text"],
        fontfamily=_FONT_FAMILY,
        va="center",
    )

    parsed_rows = []
    advancers = 0
    decliners = 0
    unchanged = 0
    best_row = None
    worst_row = None
    for item in market_data:
        change_pct = item.get("change_pct", "N/A")
        pct_val = None
        try:
            pct_val = float(str(change_pct).replace("%", "").replace("+", "").replace(",", ""))
        except (ValueError, TypeError, AttributeError):
            pct_val = None
        if pct_val is None:
            change_display = str(change_pct)
            color = COLORS["text_secondary"]
        else:
            if pct_val > 0:
                advancers += 1
            elif pct_val < 0:
                decliners += 1
            else:
                unchanged += 1
            color = _get_change_color(pct_val)
            sign = "+" if pct_val >= 0 else ""
            raw_change = str(change_pct)
            change_display = raw_change if raw_change.startswith(("+", "-")) else f"{sign}{raw_change}"
            if best_row is None or pct_val > best_row["pct_val"]:
                best_row = {"name": _to_en(item.get("name", "")), "pct_val": pct_val}
            if worst_row is None or pct_val < worst_row["pct_val"]:
                worst_row = {"name": _to_en(item.get("name", "")), "pct_val": pct_val}
        parsed_rows.append(
            {
                "section": item.get("section", ""),
                "name": _to_en(item.get("name", "")),
                "price": str(item.get("price", "N/A")),
                "change_display": change_display,
                "pct_val": pct_val,
                "color": color,
            }
        )

    coverage_label = f"{advancers}/{decliners}/{unchanged}"
    leader_label = "No signal"
    leader_color = COLORS["text"]
    if best_row and worst_row:
        leader = best_row if abs(best_row["pct_val"]) >= abs(worst_row["pct_val"]) else worst_row
        leader_label = f"{_truncate_text(leader['name'], 12)} {leader['pct_val']:+.2f}%"
        leader_color = _get_change_color(leader["pct_val"])

    # Summary donut in header (right side, clear of title text on left)
    _adv_total = advancers + decliners + unchanged
    if _adv_total > 0:
        _donut_data = [
            {"name": "Up", "count": advancers},
            {"name": "Down", "count": decliners},
            {"name": "Flat", "count": unchanged},
        ]
        _donut_colors = [COLORS["green"], COLORS["red"], COLORS["text_muted"]]
        _donut_cx = 8.8
        _donut_cy = fig_height - 1.08
        _donut_r = 0.52
        _donut_total = _adv_total
        _start_angle = 90
        for _di, _ditem in enumerate(_donut_data):
            _dcount = _ditem.get("count", 0)
            if _dcount <= 0:
                continue
            _sweep = 360 * _dcount / _donut_total
            _end_angle = _start_angle - _sweep
            _wedge = mpatches.Wedge(
                (_donut_cx, _donut_cy),
                _donut_r,
                _end_angle,
                _start_angle,
                width=_donut_r * (1 - 0.58),
                facecolor=_donut_colors[_di % len(_donut_colors)],
                edgecolor=COLORS["bg"],
                linewidth=1.5,
                alpha=0.82,
            )
            ax.add_patch(_wedge)
            _start_angle = _end_angle
        _glow_ring = mpatches.Circle(
            (_donut_cx, _donut_cy),
            _donut_r * 0.58 + 0.02,
            facecolor="none",
            edgecolor=COLORS["border_highlight"],
            linewidth=0.6,
            alpha=0.35,
        )
        ax.add_patch(_glow_ring)
        ax.text(
            _donut_cx,
            _donut_cy + 0.07,
            str(_adv_total),
            ha="center",
            va="center",
            fontsize=9,
            fontweight="bold",
            color=COLORS["text"],
            fontfamily=_FONT_FAMILY,
        )
        ax.text(
            _donut_cx,
            _donut_cy - 0.14,
            "mkts",
            ha="center",
            va="center",
            fontsize=6,
            color=COLORS["text_muted"],
            fontfamily=_FONT_FAMILY,
        )

    chip_y = header_y - 0.9
    chip_w = 2.78
    chip_gap = 0.22
    _draw_metric_chip(ax, 0.35, chip_y, chip_w, 0.72, label="Coverage", value=str(row_count), accent=COLORS["cyan"])
    _draw_metric_chip(
        ax, 0.35 + chip_w + chip_gap, chip_y, chip_w, 0.72, label="A D U", value=coverage_label, accent=COLORS["green"]
    )
    _draw_metric_chip(
        ax,
        0.35 + (chip_w + chip_gap) * 2,
        chip_y,
        chip_w + 0.3,
        0.72,
        label="Leader",
        value=leader_label,
        accent=COLORS["blue"],
        value_color=leader_color,
    )

    # Visual breadth indicator bar (advance/decline ratio)
    _breadth_bar_y = chip_y - 0.22
    _breadth_bar_x0 = 0.45
    _breadth_bar_x1 = 9.55
    _breadth_bar_w = _breadth_bar_x1 - _breadth_bar_x0
    _breadth_bar_h = 0.15
    _draw_rounded_rect(
        ax,
        _breadth_bar_x0,
        _breadth_bar_y,
        _breadth_bar_w,
        _breadth_bar_h,
        facecolor=COLORS["bg_inner"],
        alpha=0.85,
        pad=0.02,
    )
    _adv_dec_total = advancers + decliners
    if _adv_dec_total > 0:
        _green_frac = advancers / _adv_dec_total
        _red_frac = decliners / _adv_dec_total
        if _green_frac > 0:
            _draw_rounded_rect(
                ax,
                _breadth_bar_x0,
                _breadth_bar_y,
                _breadth_bar_w * _green_frac,
                _breadth_bar_h,
                facecolor=COLORS["green"],
                alpha=0.72,
                pad=0.01,
            )
        if _red_frac > 0:
            _draw_rounded_rect(
                ax,
                _breadth_bar_x0 + _breadth_bar_w * _green_frac,
                _breadth_bar_y,
                _breadth_bar_w * _red_frac,
                _breadth_bar_h,
                facecolor=COLORS["red"],
                alpha=0.72,
                pad=0.01,
            )

    panel_y = chip_y - 0.55
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

    y_start = panel_y - 0.28
    ax.text(
        0.55, y_start, "Benchmarks", fontsize=9, fontweight="bold", color=COLORS["text_muted"], fontfamily=_FONT_FAMILY
    )
    ax.text(
        5.15,
        y_start,
        "Last",
        fontsize=9,
        fontweight="bold",
        color=COLORS["text_muted"],
        fontfamily=_FONT_FAMILY,
        ha="center",
    )
    ax.text(
        7.98,
        y_start,
        "1D",
        fontsize=9,
        fontweight="bold",
        color=COLORS["text_muted"],
        fontfamily=_FONT_FAMILY,
        ha="center",
    )
    ax.text(
        9.2,
        y_start,
        "Bias",
        fontsize=9,
        fontweight="bold",
        color=COLORS["text_muted"],
        fontfamily=_FONT_FAMILY,
        ha="center",
    )
    ax.plot([0.45, 9.55], [y_start - 0.18, y_start - 0.18], color=COLORS["border"], linewidth=0.8, alpha=0.8)

    current_section = None
    y = y_start - 0.55

    for item in parsed_rows:
        section = item["section"]
        if section and section != current_section:
            current_section = section
            _draw_rounded_rect(ax, 0.45, y - 0.13, 9.1, 0.38, facecolor=COLORS["bg_inner"], alpha=0.55, pad=0.03)
            _draw_rounded_rect(ax, 0.55, y - 0.08, 0.12, 0.26, facecolor=COLORS["accent"], pad=0.004)
            ax.text(
                0.82,
                y,
                section,
                fontsize=9,
                fontweight="bold",
                color=COLORS["accent"],
                fontfamily=_FONT_FAMILY,
                va="center",
            )
            y -= 0.48

        bg_color = (
            _heatmap_bg_color(item["pct_val"] or 0.0, extreme=2.5) if item["pct_val"] is not None else COLORS["bg_card"]
        )
        _draw_rounded_rect(
            ax,
            0.45,
            y - 0.28,
            9.1,
            0.62,
            facecolor=bg_color,
            edgecolor=COLORS["border"],
            linewidth=0.6,
            alpha=0.92,
            pad=0.03,
        )
        ax.text(0.7, y + 0.03, item["name"], fontsize=11.5, color=COLORS["text"], fontfamily=_FONT_FAMILY, va="center")
        ax.text(
            5.15,
            y + 0.03,
            item["price"],
            fontsize=11.2,
            color=COLORS["text"],
            fontfamily=_FONT_FAMILY,
            ha="center",
            va="center",
        )
        ax.text(
            7.98,
            y + 0.03,
            item["change_display"],
            fontsize=11.5,
            color=item["color"],
            fontfamily=_FONT_FAMILY,
            ha="center",
            fontweight="bold",
            va="center",
        )
        bar_x = 8.72
        bar_y = y - 0.11
        _draw_rounded_rect(ax, bar_x, bar_y, 0.92, 0.28, facecolor=COLORS["bg_inner"], alpha=0.95, pad=0.01)
        if item["pct_val"] is not None:
            magnitude = min(abs(item["pct_val"]) / 3.0, 1.0)
            fill_w = 0.18 + magnitude * 0.62
            fill_x = bar_x + 0.46 - fill_w if item["pct_val"] < 0 else bar_x + 0.46
            _draw_rounded_rect(
                ax,
                fill_x,
                bar_y + 0.03,
                fill_w,
                0.22,
                facecolor=item["color"],
                alpha=0.8,
                pad=0.008,
            )
            # Mini sparkline overlay inside the bias bar region
            _spark_raw = item.get("sparkline_data")
            _spark_n = 5
            if _spark_raw and len(_spark_raw) >= 2:
                _spark_prices = np.array(_spark_raw[-_spark_n:], dtype=float)
                _smin, _smax = _spark_prices.min(), _spark_prices.max()
                _spark_vals = (
                    ((_spark_prices - _smin) / (_smax - _smin)) if _smax > _smin else np.full(len(_spark_prices), 0.5)
                )
                _spark_n = len(_spark_vals)
            else:
                _spark_seed = abs(hash(item["name"])) % 2**31
                _spark_rng = np.random.RandomState(_spark_seed)
                if item["pct_val"] >= 0:
                    _spark_trend = np.linspace(0.0, 0.6, _spark_n)
                else:
                    _spark_trend = np.linspace(0.6, 0.0, _spark_n)
                _spark_noise = _spark_rng.uniform(-0.18, 0.18, _spark_n)
                _spark_vals = np.clip(_spark_trend + _spark_noise, 0.0, 1.0)
            _spark_x0 = bar_x + 0.06
            _spark_x1 = bar_x + 0.86
            _spark_y0 = bar_y + 0.04
            _spark_y1 = bar_y + 0.24
            _spark_xs = np.linspace(_spark_x0, _spark_x1, _spark_n)
            _spark_ys = _spark_y0 + _spark_vals * (_spark_y1 - _spark_y0)
            ax.plot(
                _spark_xs,
                _spark_ys,
                color=item["color"],
                linewidth=1.2,
                alpha=0.4,
                solid_capstyle="round",
                solid_joinstyle="round",
            )
        y -= 0.72

    _add_footer(ax, f"{_DS['watermark']} | {date_str} | Market breadth auto-generated", y=0.12)

    if not filename:
        filename = f"market-snapshot-{date_str}.png"
    filepath = os.path.join(_base._get_pkg_attr("IMAGES_DIR"), filename)

    plt.tight_layout(pad=_DS["pad_outer"])
    _save_and_close(fig, filepath)

    logger.info("Generated market snapshot card: %s", filename)
    return f"/assets/images/generated/{filename}"


# ===================================================================
# 6. Source Distribution (donut chart)
# ===================================================================


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
    if not _base._get_pkg_attr("_MPL_AVAILABLE"):
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

    ranked_sources = sorted(sources, key=lambda s: s.get("count", 0), reverse=True)
    if len(ranked_sources) > 4:
        top_sources = ranked_sources[:4]
        other_count = sum(max(0, int(src.get("count", 0))) for src in ranked_sources[4:])
        if other_count > 0:
            top_sources.append({"name": "Other", "count": other_count})
        ranked_sources = top_sources

    names = [_to_en(str(s["name"])) for s in ranked_sources]
    counts = [s["count"] for s in ranked_sources]
    total = sum(counts)
    colors = [donut_colors[i % len(donut_colors)] for i in range(len(names))]

    dominant_idx = int(np.argmax(counts)) if counts else 0
    dominant_name = names[dominant_idx] if names else "N/A"
    dominant_share = (counts[dominant_idx] / total * 100) if total else 0.0

    fig, ax = plt.subplots(figsize=(8, 8))
    fig.patch.set_facecolor(COLORS["bg"])
    ax.set_facecolor(COLORS["bg"])

    wedges, _texts, autotexts = ax.pie(
        counts,
        labels=None,
        colors=colors,
        autopct=lambda pct: f"{pct:.0f}%" if pct >= 10 else "",
        startangle=90,
        pctdistance=0.76,
        wedgeprops=dict(width=0.4, edgecolor=COLORS["bg"], linewidth=2),
    )

    for at in autotexts:
        at.set_color(COLORS["text"])
        at.set_fontsize(_DS["small_size"])
        at.set_fontfamily(_FONT_FAMILY)

    # Center text -- total count
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
        "total flow",
        ha="center",
        va="center",
        fontsize=12,
        color=COLORS["text_secondary"],
        fontfamily=_FONT_FAMILY,
    )
    ax.text(
        0,
        -0.31,
        f"Top {dominant_name}",
        ha="center",
        va="center",
        fontsize=11,
        color=COLORS["text"],
        fontfamily=_FONT_FAMILY,
        fontweight="bold",
    )
    ax.text(
        0,
        -0.47,
        f"{dominant_share:.0f}% share",
        ha="center",
        va="center",
        fontsize=10,
        color=COLORS["text_secondary"],
        fontfamily=_FONT_FAMILY,
    )

    # Title
    ax.set_title(
        f"Social Flow \u2014 {date_str}",
        fontsize=14,
        fontweight="bold",
        color=COLORS["text"],
        fontfamily=_FONT_FAMILY,
        pad=20,
    )

    # Legend
    legend = ax.legend(
        wedges,
        names,
        loc="lower center",
        bbox_to_anchor=(0.5, -0.12),
        ncol=min(len(names), 4),
        fontsize=_DS["small_size"],
        frameon=False,
    )
    for text in legend.get_texts():
        text.set_color(COLORS["text"])
        text.set_fontfamily(_FONT_FAMILY)

    # Footer
    fig.text(
        0.5,
        -0.02,
        f"{_DS['watermark']} | Visual mix",
        ha="center",
        fontsize=_DS["footer_size"],
        color=COLORS["text_muted"],
        fontfamily=_FONT_FAMILY,
        style="italic",
    )

    if not filename:
        filename = f"source-distribution-{date_str}.png"
    filepath = os.path.join(_base._get_pkg_attr("IMAGES_DIR"), filename)

    plt.tight_layout(pad=1.0)
    _save_and_close(fig, filepath)

    logger.info("Generated source distribution card: %s", filename)
    return f"/assets/images/generated/{filename}"


# ===================================================================
# 7. Sector Heatmap
# ===================================================================


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
    if not _base._get_pkg_attr("_MPL_AVAILABLE"):
        return None

    _ensure_dir()

    if not sector_data:
        return None

    # Sort sectors by change for visual grouping
    sorted_sectors = sorted(
        sector_data.items(),
        key=lambda x: x[1].get("change_pct", 0),
        reverse=True,
    )
    count = len(sorted_sectors)

    # Adaptive columns -- make cells wider when fewer sectors
    cols = 4 if count > 8 else 3
    rows = (count + cols - 1) // cols

    fig, ax = plt.subplots(figsize=(14, 4.5 + rows * 2.0))
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
        fontsize=_DS["title_size"],
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
        fontsize=_DS["subtitle_size"],
        color=COLORS["text_secondary"],
        fontfamily=_FONT_FAMILY,
    )

    margin = 0.03
    gap = 0.01
    top_area = 0.88
    bottom_area = 0.07  # reserve space for legend
    cell_w = (1.0 - margin * 2 - gap * (cols - 1)) / cols
    cell_h = (top_area - bottom_area - margin * 2 - gap * (rows - 1)) / rows

    # Find the range for scaling
    all_changes = [info.get("change_pct", 0) for _, info in sorted_sectors]
    max_abs = max(abs(c) for c in all_changes) if all_changes else 3.0
    scale_extreme = max(max_abs, 1.0)  # at least 1% range

    for i, (symbol, info) in enumerate(sorted_sectors):
        row = i // cols
        col = i % cols

        x = margin + col * (cell_w + gap)
        y = 0.88 - margin - (row + 1) * (cell_h + gap) + gap

        change = info.get("change_pct", 0)

        # Dynamic colour based on actual data range
        bg_color = _heatmap_bg_color(change, extreme=scale_extreme)

        # Highlight border for extreme movers
        edge_color = COLORS["border"]
        edge_width = 0.5
        if abs(change) >= scale_extreme * 0.7:
            edge_color = _get_change_color(change)
            edge_width = 1.5

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

        # ETF Symbol -- larger
        ax.text(
            x + cell_w / 2,
            y + cell_h * 0.78,
            symbol,
            ha="center",
            va="center",
            transform=ax.transAxes,
            fontsize=14,
            fontweight="bold",
            color=COLORS["text"],
            fontfamily=_FONT_FAMILY,
        )

        # Sector name
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
            fontsize=_DS["small_size"],
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
            fontsize=_DS["small_size"],
            color=COLORS["text_secondary"],
            fontfamily=_FONT_FAMILY,
        )

        # Change -- prominent
        change_color = _get_change_color(change)
        sign = "+" if change >= 0 else ""
        ax.text(
            x + cell_w / 2,
            y + cell_h * 0.15,
            f"{sign}{change:.2f}%",
            ha="center",
            va="center",
            transform=ax.transAxes,
            fontsize=12,
            fontweight="bold",
            color=change_color,
            fontfamily=_FONT_FAMILY,
        )

    # Color scale legend
    legend_y = 0.015
    legend_h = 0.015
    legend_x_start = 0.30
    legend_w = 0.40
    n_legend = 30
    for li in range(n_legend):
        frac = li / (n_legend - 1)
        pct = -scale_extreme + 2 * scale_extreme * frac
        lc = _heatmap_bg_color(pct, extreme=scale_extreme)
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
        f"-{scale_extreme:.1f}%",
        ha="right",
        va="center",
        transform=ax.transAxes,
        fontsize=7,
        color=COLORS["text_secondary"],
        fontfamily=_FONT_FAMILY,
    )
    ax.text(
        legend_x_start + legend_w + 0.02,
        legend_y + legend_h / 2,
        f"+{scale_extreme:.1f}%",
        ha="left",
        va="center",
        transform=ax.transAxes,
        fontsize=7,
        color=COLORS["text_secondary"],
        fontfamily=_FONT_FAMILY,
    )

    if not filename:
        filename = f"sector-heatmap-{date_str}.png"
    filepath = os.path.join(_base._get_pkg_attr("IMAGES_DIR"), filename)

    _save_and_close(fig, filepath)

    logger.info("Generated sector heatmap: %s", filename)
    return f"/assets/images/generated/{filename}"
