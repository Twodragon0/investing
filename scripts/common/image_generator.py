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
    # collect_stock_news.py market snapshot names
    "다우존스": "Dow Jones",
    "다우존스 ETF": "Dow Jones ETF",
    "원/달러": "USD/KRW",
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
    """Filter out Korean-only keywords and common noise words, keep meaningful ones."""
    import re

    _NOISE_KEYWORDS = {
        "the", "and", "for", "with", "has", "are", "its", "but", "how", "why",
        "what", "new", "all", "can", "now", "get", "set", "may", "not", "other",
        "only", "just", "also", "more", "most", "some", "much", "many", "each",
        "even", "very", "here", "there", "then", "than", "into", "from", "this",
        "that", "been", "were", "will", "your", "they", "them", "such", "like",
        "better", "bigger", "lower", "higher", "early", "late", "huge", "linked",
        "issues", "says", "said", "first", "last", "next", "after", "before",
        "about", "every", "where", "which", "while", "could", "would", "should",
        "still", "today", "monday", "tuesday", "wednesday", "thursday", "friday",
        "saturday", "sunday", "report", "update", "alert", "check", "watch",
        "live", "latest", "breaking", "global", "world", "major", "keep",
    }
    result = []
    for kw in keywords:
        # Keep if it has at least one Latin character and is not a noise word
        if re.search(r"[a-zA-Z]", kw) and kw.lower().strip() not in _NOISE_KEYWORDS:
            result.append(kw)
    return result


# ---------------------------------------------------------------------------
# Professional dark finance color palette
# ---------------------------------------------------------------------------
COLORS = {
    # Backgrounds -- deeper, richer darks
    "bg": "#0b1018",
    "bg_card": "#111820",
    "bg_inner": "#161d27",
    "bg_header": "#0f1923",
    # Text hierarchy
    "text": "#f0f4fc",
    "text_secondary": "#8b9bb0",
    "text_muted": "#4a5568",
    # Positive / Negative -- higher contrast
    "green": "#00f07a",
    "green_dim": "#0b3d24",
    "red": "#ff5263",
    "red_dim": "#3d1420",
    # Accent colors
    "blue": "#4da6ff",
    "orange": "#ffb347",
    "purple": "#b57bff",
    "cyan": "#22d3ee",
    # Semantic
    "accent": "#4da6ff",
    "warning": "#ffb347",
    "info": "#22d3ee",
    # Borders & separators
    "border": "#1e2a3a",
    "border_highlight": "#2d4a6a",
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
    "dpi": 200,
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
    os.makedirs(IMAGES_DIR, exist_ok=True)


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
    ax, x, y, w, h, *, facecolor, edgecolor="none", linewidth=0, alpha=1.0, transform=None, pad=0.012
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
            alpha=0.65,
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
            alpha=0.65,
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
    """Shared save-and-close to reduce repetition."""
    bg_color = bg or COLORS["bg"]
    plt.savefig(
        filepath,
        dpi=_DS["dpi"],
        facecolor=bg_color,
        edgecolor="none",
        bbox_inches="tight",
        pad_inches=0.15,
    )
    plt.close(fig)


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
    if not _MPL_AVAILABLE:
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

        # --- 7d change with mini bar ---
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
    filepath = os.path.join(IMAGES_DIR, filename)

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
    if not _MPL_AVAILABLE:
        return None

    _ensure_dir()

    fig, ax = plt.subplots(figsize=(8, 6.5))
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
    label_r = r_outer + 0.15
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
    filepath = os.path.join(IMAGES_DIR, filename)

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
        bg_color = _heatmap_bg_color(change, extreme=5.0)

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
    for li in range(n_legend):
        frac = li / (n_legend - 1)
        pct = -7.0 + 14.0 * frac
        lc = _heatmap_bg_color(pct, extreme=7.0)
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
        "-7%",
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
        "+7%",
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
    filepath = os.path.join(IMAGES_DIR, filename)

    _save_and_close(fig, filepath)

    logger.info("Generated market heatmap: %s", filename)
    return f"/assets/images/generated/{filename}"


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
    if not _MPL_AVAILABLE:
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
    filepath = os.path.join(IMAGES_DIR, filename)

    plt.tight_layout(pad=1.0)
    _save_and_close(fig, filepath)

    logger.info("Generated news summary card: %s", filename)
    return f"/assets/images/generated/{filename}"


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
    if not _MPL_AVAILABLE:
        return None

    _ensure_dir()

    if not market_data:
        logger.warning("No market data for snapshot card")
        return None

    row_count = len(market_data)
    # Count section headers (each adds extra vertical space)
    section_count = len({item.get("section", "") for item in market_data if item.get("section")})
    fig_height = 3.0 + row_count * 0.55 + section_count * 0.45
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
        fontsize=_DS["title_size"],
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
        fontsize=_DS["subtitle_size"],
        color=COLORS["text_secondary"],
        fontfamily=_FONT_FAMILY,
    )

    # Column headers
    y_start = fig_height - 1.5
    ax.text(
        0.5,
        y_start,
        "Index / ETF",
        fontsize=_DS["header_size"],
        fontweight="bold",
        color=COLORS["text_muted"],
        fontfamily=_FONT_FAMILY,
    )
    ax.text(
        5.0,
        y_start,
        "Price",
        fontsize=_DS["header_size"],
        fontweight="bold",
        color=COLORS["text_muted"],
        fontfamily=_FONT_FAMILY,
        ha="center",
    )
    ax.text(
        8.0,
        y_start,
        "Change",
        fontsize=_DS["header_size"],
        fontweight="bold",
        color=COLORS["text_muted"],
        fontfamily=_FONT_FAMILY,
        ha="center",
    )

    ax.plot([0.3, 9.7], [y_start - 0.2, y_start - 0.2], color=COLORS["border"], linewidth=0.5)

    current_section = None
    y = y_start - 0.5

    for i, item in enumerate(market_data):
        section = item.get("section", "")
        if section and section != current_section:
            current_section = section
            # Section header with accent bar
            _draw_rounded_rect(ax, 0.3, y - 0.12, 0.12, 0.35, facecolor=COLORS["accent"], pad=0.005)
            ax.text(
                0.6,
                y,
                section,
                fontsize=10,
                fontweight="bold",
                color=COLORS["accent"],
                fontfamily=_FONT_FAMILY,
            )
            y -= 0.45

        # Row background
        if i % 2 == 0:
            _draw_rounded_rect(ax, 0.3, y - 0.18, 9.4, 0.5, facecolor=COLORS["bg_inner"], alpha=0.5)

        name = _to_en(item.get("name", ""))
        price = item.get("price", "N/A")
        change_pct = item.get("change_pct", "N/A")

        # Determine color from change_pct
        try:
            pct_val = float(change_pct.replace("%", "").replace("+", ""))
            color = _get_change_color(pct_val)
            sign = "+" if pct_val >= 0 else ""
            change_display = f"{sign}{change_pct}" if not change_pct.startswith(("+", "-")) else change_pct
        except (ValueError, AttributeError):
            color = COLORS["text_secondary"]
            change_display = change_pct

        ax.text(0.5, y, name, fontsize=_DS["body_size"], color=COLORS["text"], fontfamily=_FONT_FAMILY)
        ax.text(5.0, y, price, fontsize=_DS["body_size"], color=COLORS["text"], fontfamily=_FONT_FAMILY, ha="center")
        ax.text(
            8.0,
            y,
            change_display,
            fontsize=_DS["body_size"],
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
        f"{_DS['watermark']} | {date_str}",
        ha="center",
        fontsize=_DS["footer_size"],
        color=COLORS["text_secondary"],
        fontfamily=_FONT_FAMILY,
        style="italic",
        alpha=0.65,
    )

    if not filename:
        filename = f"market-snapshot-{date_str}.png"
    filepath = os.path.join(IMAGES_DIR, filename)

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
        at.set_fontsize(_DS["small_size"])
        at.set_fontfamily("monospace")

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
        "total",
        ha="center",
        va="center",
        fontsize=12,
        color=COLORS["text_secondary"],
        fontfamily=_FONT_FAMILY,
    )

    # Title
    ax.set_title(
        f"Source Distribution \u2014 {date_str}",
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
        fontsize=_DS["small_size"],
        frameon=False,
    )
    for text in legend.get_texts():
        text.set_color(COLORS["text"])
        text.set_fontfamily("monospace")

    # Footer
    fig.text(
        0.5,
        0.01,
        f"{_DS['watermark']} | Auto-generated",
        ha="center",
        fontsize=_DS["footer_size"],
        color=COLORS["text_muted"],
        fontfamily=_FONT_FAMILY,
        style="italic",
    )

    if not filename:
        filename = f"source-distribution-{date_str}.png"
    filepath = os.path.join(IMAGES_DIR, filename)

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
    if not _MPL_AVAILABLE:
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
    filepath = os.path.join(IMAGES_DIR, filename)

    _save_and_close(fig, filepath)

    logger.info("Generated sector heatmap: %s", filename)
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
        logger.warning("No themes provided for briefing card")
        return None

    display_themes = themes[:5]
    use_emoji = _HAS_EMOJI_FONT
    has_urgent = urgent_alerts and len(urgent_alerts) > 0
    urgent_height = 0.9 if has_urgent else 0
    fig_height = 3.8 + len(display_themes) * 0.75 + urgent_height

    fig, ax = plt.subplots(figsize=(12, fig_height))
    fig.patch.set_facecolor(COLORS["bg"])
    ax.set_facecolor(COLORS["bg"])
    ax.set_xlim(0, 10)
    ax.set_ylim(0, fig_height)
    ax.axis("off")

    # --- Header card with gradient background ---
    header_y = fig_height - 1.8
    header_h = 1.6
    # Gradient fill for header
    _draw_gradient_bar(
        ax, 0.2, header_y, 9.6, header_h, color_start="#0f1923", color_end="#152238", steps=30, alpha=0.95
    )
    # Border for header
    _draw_rounded_rect(
        ax, 0.2, header_y, 9.6, header_h, facecolor="none", edgecolor=COLORS["accent"], linewidth=1.5, pad=0.08
    )

    # Title
    ax.text(
        5,
        fig_height - 0.55,
        category,
        ha="center",
        va="center",
        fontsize=22,
        fontweight="bold",
        color=COLORS["text"],
        fontfamily=_FONT_FAMILY,
    )
    # Date and count
    ax.text(
        5,
        fig_height - 1.1,
        f"{date_str}  |  {total_count} articles collected",
        ha="center",
        va="center",
        fontsize=_DS["body_size"],
        color=COLORS["text_secondary"],
        fontfamily=_FONT_FAMILY,
    )

    # --- Theme rows ---
    y_start = fig_height - 2.4

    theme_colors = [
        COLORS["orange"],
        COLORS["blue"],
        COLORS["purple"],
        COLORS["green"],
        COLORS["cyan"],
    ]

    for i, theme in enumerate(display_themes):
        y = y_start - i * 0.75
        t_color = theme_colors[i % len(theme_colors)]

        # Row background card
        _draw_rounded_rect(
            ax, 0.3, y - 0.25, 9.4, 0.65, facecolor=COLORS["bg_card"], edgecolor=COLORS["border"], linewidth=0.5
        )

        # Left accent bar
        _draw_rounded_rect(ax, 0.3, y - 0.25, 0.12, 0.65, facecolor=t_color, pad=0.005)

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

        # Count badge with background circle
        badge_x, badge_y = 4.5, y + 0.05
        badge_circle = mpatches.Circle(
            (badge_x, badge_y),
            0.2,
            facecolor=t_color,
            alpha=0.15,
            edgecolor="none",
        )
        ax.add_patch(badge_circle)
        ax.text(
            badge_x,
            badge_y,
            str(count),
            fontsize=13,
            fontweight="bold",
            color=t_color,
            fontfamily=_FONT_FAMILY,
            va="center",
            ha="center",
        )

        # Keywords with dot separator
        if keywords:
            kw_str = " \u00b7 ".join(keywords[:4])
            ax.text(
                5.2,
                y + 0.05,
                kw_str,
                fontsize=_DS["small_size"],
                color=COLORS["text_secondary"],
                fontfamily=_FONT_FAMILY,
                va="center",
            )

    # --- Urgent alerts section ---
    if has_urgent:
        y_urgent = y_start - len(display_themes) * 0.75 - 0.3

        # Urgent box with red glow
        _draw_rounded_rect(
            ax, 0.3, y_urgent - 0.35, 9.4, 0.75, facecolor=COLORS["red_dim"], edgecolor=COLORS["red"], linewidth=1.5
        )

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
        f"{_DS['watermark']} | Auto-generated News Briefing",
        ha="center",
        fontsize=_DS["footer_size"],
        color=COLORS["text_muted"],
        fontfamily=_FONT_FAMILY,
        style="italic",
    )

    if not filename:
        filename = f"news-briefing-{date_str}.png"
    filepath = os.path.join(IMAGES_DIR, filename)

    plt.tight_layout(pad=_DS["pad_outer"])
    _save_and_close(fig, filepath)

    logger.info("Generated news briefing card: %s", filename)
    return f"/assets/images/generated/{filename}"


# ===================================================================
# Category OG Images (1200x630 for SNS sharing)
# ===================================================================

# 카테고리별 설정 (이름, 이모지, 색상)
_CATEGORY_OG_CONFIG = {
    "crypto": ("Crypto News", "₿", COLORS["orange"]),
    "stock": ("Stock Market", "📊", COLORS["green"]),
    "market-analysis": ("Market Analysis", "📈", COLORS["blue"]),
    "social-media": ("Social Media", "💬", COLORS["purple"]),
    "regulatory": ("Regulatory", "⚖️", COLORS["cyan"]),
    "defi": ("DeFi & Web3", "🔗", COLORS["purple"]),
    "political-trades": ("Political Trades", "🏛️", COLORS["orange"]),
    "worldmonitor": ("World Monitor", "🌍", COLORS["blue"]),
    "security-alerts": ("Security Alerts", "🛡️", COLORS["red"]),
}


def generate_category_og_image(
    category: str,
    filename: Optional[str] = None,
) -> Optional[str]:
    """Generate a 1200x630 OG image for a category.

    SNS(카카오톡, LinkedIn, X 등) 공유 시 미리보기에 사용되는 이미지를 생성합니다.
    """
    if not _MPL_AVAILABLE:
        return None

    # OG 이미지는 assets/images/ 디렉토리에 저장 (generated가 아닌 상위)
    og_dir = os.path.join(REPO_ROOT, "assets", "images")
    os.makedirs(og_dir, exist_ok=True)

    config = _CATEGORY_OG_CONFIG.get(category)
    if not config:
        return None

    cat_name, emoji, accent = config

    # 1200x630 @ 150dpi -> 8x4.2 inches
    fig, ax = plt.subplots(figsize=(8, 4.2))
    fig.patch.set_facecolor(COLORS["bg"])
    ax.set_facecolor(COLORS["bg"])
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 6.3)
    ax.axis("off")

    # 배경 그라디언트 효과
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

    # 하단 액센트 라인
    _draw_rounded_rect(
        ax,
        0.5,
        0.4,
        11,
        0.08,
        facecolor=accent,
        alpha=0.7,
        pad=0.005,
    )

    # 사이트 로고 텍스트
    ax.text(
        6,
        5.2,
        "🐉 Investing Dragon",
        ha="center",
        va="center",
        fontsize=14,
        color=COLORS["text_secondary"],
        fontfamily=_FONT_FAMILY,
    )

    # 카테고리명 (큰 텍스트)
    ax.text(
        6,
        3.2,
        cat_name,
        ha="center",
        va="center",
        fontsize=36,
        fontweight="bold",
        color=COLORS["text"],
        fontfamily=_FONT_FAMILY,
    )

    # 설명 텍스트
    ax.text(
        6,
        1.8,
        "Crypto & Stock News • Trading Journal",
        ha="center",
        va="center",
        fontsize=12,
        color=COLORS["text_secondary"],
        fontfamily=_FONT_FAMILY,
    )

    # 액센트 장식 (좌우 라인)
    ax.plot([1.5, 4.5], [4.3, 4.3], color=accent, linewidth=2, alpha=0.5)
    ax.plot([7.5, 10.5], [4.3, 4.3], color=accent, linewidth=2, alpha=0.5)

    if not filename:
        filename = f"og-{category}.png"
    filepath = os.path.join(og_dir, filename)

    plt.tight_layout(pad=0)
    plt.savefig(
        filepath,
        dpi=150,
        facecolor=COLORS["bg"],
        edgecolor="none",
        bbox_inches="tight",
        pad_inches=0,
    )
    plt.close(fig)

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
