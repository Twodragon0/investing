"""표준 OG 이미지 합성(`generate_og_image`).

`generate_og_images.py` 에서 추출(2026-06-26). 카테고리별 비주얼([[og_visuals]])과
공유 렌더링 프리미티브([[og_render]]), 포맷 변환([[og_image_formats]])을 조합해
1200x630 OG 이미지를 합성한다. trading-journal 전용 이미지와 thumbnail/CLI 는
메인 모듈에 남아 여기서 카테고리 색/라벨·텍스트 헬퍼·변환 함수를 재사용한다.
"""

import inspect
import logging
import os
import re
import textwrap
from typing import Any, Dict, List

from common import asset_storage
from common.og_image_formats import _convert_formats_parallel
from common.og_render import (
    _FK,
    _MPL_AVAILABLE,
    BG_COLOR,
    DIVIDER_COLOR,
    TEXT_GRAY,
    TEXT_WHITE,
    mpatches,
    plt,
)
from common.og_visuals import (
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

logger = logging.getLogger("og-image-gen")

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
