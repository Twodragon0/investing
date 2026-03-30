"""OG image and category image generators.

Generates category OG images (1200x630) for SNS sharing previews.
"""

import logging
import os
from typing import Dict, Optional

from . import base as _base
from .base import (
    _DS,
    _FONT_FAMILY,
    COLORS,
    _convert_to_avif,
    _convert_to_webp,
    _draw_category_illustration,
    _draw_gradient_bar,
    _draw_rounded_rect,
    _get_category_bg_drawer,
    mpatches,
    np,
    plt,
)

logger = logging.getLogger(__name__)

# ===================================================================
# Category OG Images (1200x630 for SNS sharing)
# ===================================================================

# 카테고리별 설정 (이름, 이모지, 색상)
_CATEGORY_OG_CONFIG = {
    "crypto": ("Crypto News", "\u20bf", COLORS["orange"]),
    "stock": ("Stock Market", "\U0001f4ca", COLORS["green"]),
    "market-analysis": ("Market Analysis", "\U0001f4c8", COLORS["blue"]),
    "social-media": ("Social Media", "\U0001f4ac", COLORS["purple"]),
    "regulatory": ("Regulatory", "\u2696\ufe0f", COLORS["cyan"]),
    "defi": ("DeFi & Web3", "\U0001f517", COLORS["purple"]),
    "political-trades": ("Political Trades", "\U0001f3db\ufe0f", COLORS["orange"]),
    "worldmonitor": ("World Monitor", "\U0001f30d", COLORS["blue"]),
    "security-alerts": ("Security Alerts", "\U0001f6e1\ufe0f", COLORS["red"]),
}


def generate_category_og_image(
    category: str,
    filename: Optional[str] = None,
) -> Optional[str]:
    """Generate a 1200x630 OG image with category-specific illustrations.

    SNS sharing preview image with visual illustrations instead of text-only.
    """
    if not _base._get_pkg_attr("_MPL_AVAILABLE"):
        return None

    og_dir = os.path.join(_base._get_pkg_attr("REPO_ROOT"), "assets", "images")
    os.makedirs(og_dir, exist_ok=True)

    config = _CATEGORY_OG_CONFIG.get(category)
    if not config:
        return None

    cat_name, _emoji, accent = config

    # 1200x630 @ 150dpi -> 8x4.2 inches
    fig, ax = plt.subplots(figsize=(8, 4.2))
    fig.patch.set_facecolor(COLORS["bg"])
    ax.set_facecolor(COLORS["bg"])
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 6.3)
    ax.axis("off")

    # Background gradient
    _draw_gradient_bar(
        ax,
        0,
        0,
        12,
        6.3,
        color_start=COLORS["bg"],
        color_end=COLORS["bg_header"],
        steps=30,
        alpha=0.8,
    )

    # Category-specific background illustration (large, prominent)
    cat_type = _get_category_bg_drawer(cat_name)
    _draw_category_illustration(ax, cat_type, 0.5, 0.5, 11, 5.5, alpha=0.1)

    # Decorative accent orbs
    orb_specs = [
        (2.0, 5.0, 1.2, accent, 0.06),
        (10.0, 1.5, 1.5, COLORS["cyan"], 0.04),
        (9.0, 4.5, 0.8, COLORS["green"], 0.05),
    ]
    for ox, oy, orad, ocolor, oalpha in orb_specs:
        orb = mpatches.Circle((ox, oy), orad, facecolor=ocolor, edgecolor="none", alpha=oalpha)
        ax.add_patch(orb)

    # Bottom accent bar (gradient)
    _draw_gradient_bar(
        ax,
        0.5,
        0.3,
        11,
        0.12,
        color_start=accent,
        color_end=COLORS["bg"],
        steps=30,
        alpha=0.7,
    )

    # Top accent bar
    _draw_gradient_bar(
        ax,
        0.5,
        5.95,
        11,
        0.08,
        color_start=COLORS["bg"],
        color_end=accent,
        steps=30,
        alpha=0.5,
    )

    # Site logo
    ax.text(
        6,
        5.35,
        "INVESTING DRAGON",
        ha="center",
        va="center",
        fontsize=11,
        fontweight="bold",
        color=COLORS["text_muted"],
        fontfamily=_FONT_FAMILY,
        alpha=0.8,
    )

    # Category name (large, with subtle shadow)
    ax.text(
        6.06,
        3.14,
        cat_name,
        ha="center",
        va="center",
        fontsize=38,
        fontweight="bold",
        color="#000000",
        fontfamily=_FONT_FAMILY,
        alpha=0.3,
    )
    ax.text(
        6,
        3.2,
        cat_name,
        ha="center",
        va="center",
        fontsize=38,
        fontweight="bold",
        color=COLORS["text"],
        fontfamily=_FONT_FAMILY,
    )

    # Accent underline below category name
    name_w = len(cat_name) * 0.38
    _draw_rounded_rect(
        ax,
        6 - name_w / 2,
        2.45,
        name_w,
        0.08,
        facecolor=accent,
        alpha=0.6,
        pad=0.005,
    )

    # Description
    ax.text(
        6,
        1.7,
        "Crypto and Stock Market Intelligence",
        ha="center",
        va="center",
        fontsize=13,
        color=COLORS["text_secondary"],
        fontfamily=_FONT_FAMILY,
    )

    # Decorative accent lines (left and right of logo)
    ax.plot([1.5, 4.2], [4.5, 4.5], color=accent, linewidth=1.5, alpha=0.4)
    ax.plot([7.8, 10.5], [4.5, 4.5], color=accent, linewidth=1.5, alpha=0.4)
    # Small diamond at line ends
    for dx, dy in [(4.25, 4.5), (7.75, 4.5)]:
        diamond = mpatches.RegularPolygon(
            (dx, dy),
            4,
            radius=0.1,
            orientation=np.pi / 4,
            facecolor=accent,
            edgecolor="none",
            alpha=0.5,
        )
        ax.add_patch(diamond)

    if not filename:
        filename = f"og-{category}.png"
    filepath = os.path.join(og_dir, filename)

    plt.tight_layout(pad=0)
    plt.savefig(
        filepath,
        dpi=_DS["dpi"],
        facecolor=COLORS["bg"],
        edgecolor="none",
        bbox_inches="tight",
        pad_inches=0,
    )
    plt.close(fig)
    _convert_to_webp(filepath)
    _convert_to_avif(filepath)

    logger.info("Generated category OG image: %s", filename)
    return f"/assets/images/{filename}"


def generate_all_category_og_images() -> Dict[str, str]:
    """Generate OG images for all categories.

    Returns dict mapping category -> image path.
    """
    results = {}
    for cat in _CATEGORY_OG_CONFIG:
        path = generate_category_og_image(cat)
        if path:
            results[cat] = path
    return results
