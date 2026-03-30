"""Market visualization image generator package.

Generates professional market cards, charts, and gauges using matplotlib and Pillow.
Images are saved to assets/images/generated/ for use in Jekyll posts.

All public functions are re-exported here for backward compatibility:
    from common.image_generator import generate_news_briefing_card
    from common import image_generator as ig
"""

# Base infrastructure (constants, utilities, drawing helpers)
from .base import (
    _DS,
    _FK,
    _FONT_FAMILY,
    _FONT_STACK,
    _HAS_EMOJI_FONT,
    _KO_TO_EN,
    _MPL_AVAILABLE,
    COLORS,
    IMAGES_DIR,
    REPO_ROOT,
    _add_footer,
    _add_market_texture,
    _convert_to_avif,
    _convert_to_webp,
    _draw_candlestick_bg,
    _draw_category_illustration,
    _draw_globe_bg,
    _draw_gradient_bar,
    _draw_line_chart_bg,
    _draw_metric_chip,
    _draw_mini_donut,
    _draw_pulse_line,
    _draw_rounded_rect,
    _draw_shield_bg,
    _ensure_dir,
    _filter_en_keywords,
    _get_category_bg_drawer,
    _get_change_color,
    _heatmap_bg_color,
    _optimize_png,
    _safe_float,
    _sanitize_og_text,
    _save_and_close,
    _to_en,
    _truncate_text,
    fm,
    logger,
    mpatches,
    np,
    plt,
)

# Coin/market chart generators
from .coins import (
    generate_fear_greed_gauge,
    generate_market_heatmap,
    generate_top_coins_card,
)

# Market analysis generators
from .market import (
    generate_market_snapshot_card,
    generate_sector_heatmap,
    generate_source_distribution_card,
)

# News briefing generators
from .news import (
    generate_news_briefing_card,
    generate_news_summary_card,
)

# OG image generators
from .og import (
    _CATEGORY_OG_CONFIG,
    generate_all_category_og_images,
    generate_category_og_image,
)

__all__ = [
    # Constants
    "COLORS",
    "IMAGES_DIR",
    "REPO_ROOT",
    "_DS",
    "_FK",
    "_FONT_FAMILY",
    "_FONT_STACK",
    "_HAS_EMOJI_FONT",
    "_KO_TO_EN",
    "_MPL_AVAILABLE",
    "_CATEGORY_OG_CONFIG",
    # Module-level objects
    "fm",
    "logger",
    "mpatches",
    "np",
    "plt",
    # Utility functions
    "_add_footer",
    "_add_market_texture",
    "_convert_to_avif",
    "_convert_to_webp",
    "_draw_candlestick_bg",
    "_draw_category_illustration",
    "_draw_globe_bg",
    "_draw_gradient_bar",
    "_draw_line_chart_bg",
    "_draw_metric_chip",
    "_draw_mini_donut",
    "_draw_pulse_line",
    "_draw_rounded_rect",
    "_draw_shield_bg",
    "_ensure_dir",
    "_filter_en_keywords",
    "_get_category_bg_drawer",
    "_get_change_color",
    "_heatmap_bg_color",
    "_optimize_png",
    "_safe_float",
    "_sanitize_og_text",
    "_save_and_close",
    "_to_en",
    "_truncate_text",
    # Public generators
    "generate_top_coins_card",
    "generate_fear_greed_gauge",
    "generate_market_heatmap",
    "generate_news_summary_card",
    "generate_market_snapshot_card",
    "generate_source_distribution_card",
    "generate_sector_heatmap",
    "generate_news_briefing_card",
    "generate_category_og_image",
    "generate_all_category_og_images",
]
