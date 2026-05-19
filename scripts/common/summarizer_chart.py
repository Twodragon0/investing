"""Theme distribution chart rendering.

Extracted from summarizer.py to keep chart HTML generation isolated. The
function is pure — it takes items and pre-computed top themes and returns the
chart markup. Caller (ThemeSummarizer) supplies ``top_themes`` from its own
scoring pass.

Public API:
- ``BAR_COLORS``: CSS class names cycled per theme row.
- ``generate_distribution_chart(items, top_themes)``: return chart HTML.
"""

from typing import Any, Dict, List, Tuple

# Color classes for theme distribution bars
BAR_COLORS: List[str] = [
    "bar-fill-orange",
    "bar-fill-blue",
    "bar-fill-purple",
    "bar-fill-green",
    "bar-fill-red",
]


def generate_distribution_chart(
    items: List[Dict[str, Any]],
    top_themes: List[Tuple[str, str, str, int]],
) -> str:
    """Generate HTML progress bars for issue distribution.

    Returns empty string if fewer than 5 items or no top themes.

    Args:
        items: news items list (only the length is consulted, for the 5-item
            minimum guard).
        top_themes: pre-computed tuples of (name, key, emoji, count) from
            ThemeSummarizer.get_top_themes().
    """
    if len(items) < 5:
        return ""

    if not top_themes:
        return ""

    # Use max theme count as denominator for bar width so bars are
    # proportional. Articles can match multiple themes so percentages
    # would be misleading — display counts only.
    max_theme_count = max(c for _, _, _, c in top_themes) or 1

    lines = ['<div class="theme-distribution">']
    for i, (name, _key, emoji, count) in enumerate(top_themes):
        bar_pct = count / max_theme_count * 100
        color = BAR_COLORS[i % len(BAR_COLORS)]
        lines.append(
            f'<div class="theme-row">'
            f'<span class="theme-label">{emoji} {name}</span>'
            f'<div class="bar-track">'
            f'<div class="{color} bar-fill" style="width:{bar_pct:.0f}%"></div>'
            f"</div>"
            f'<span class="theme-count">{count}건</span>'
            f"</div>"
        )
    lines.append("</div>")
    lines.append("\n*기사는 여러 테마에 중복 집계될 수 있음*\n")
    return "\n".join(lines)
