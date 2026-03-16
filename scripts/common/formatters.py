"""Shared number and percentage formatting helpers."""

from datetime import UTC, datetime


def fmt_change_icon(change_str: str) -> tuple[str, str]:
    """Parse a percent-change string and return (icon, display_str).

    Handles formats like "+3.14%", "-1.5%", "3.14%", "N/A".
    Returns ("🟢", "+3.14%") or ("🔴", "-1.50%") or ("⚪", "N/A").
    """
    if not change_str or change_str.strip() in ("N/A", "-", ""):
        return "⚪", change_str or "N/A"
    try:
        cleaned = change_str.replace("%", "").replace("+", "").replace(",", "").strip()
        val = float(cleaned)
        icon = "🟢" if val >= 0 else "🔴"
        return icon, f"{val:+.2f}%"
    except (ValueError, AttributeError):
        return "⚪", change_str


def fmt_date_kr(dt=None) -> str:
    """Format datetime to Korean date string (YYYY년 MM월 DD일)."""
    if dt is None:
        dt = datetime.now(UTC)
    return dt.strftime("%Y년 %m월 %d일")


def fmt_number(n, prefix: str = "$", decimals: int = 2) -> str:
    """Format a number with K/M/B/T suffix and prefix.

    Examples:
        fmt_number(1_500_000_000) -> "$1.50B"
        fmt_number(42.5, prefix="", decimals=1) -> "42.5"
    """
    if n is None:
        return "N/A"
    if abs(n) >= 1_000_000_000_000:
        return f"{prefix}{n / 1_000_000_000_000:,.{decimals}f}T"
    if abs(n) >= 1_000_000_000:
        return f"{prefix}{n / 1_000_000_000:,.{decimals}f}B"
    if abs(n) >= 1_000_000:
        return f"{prefix}{n / 1_000_000:,.{min(decimals, 1)}f}M"
    return f"{prefix}{n:,.{decimals}f}"


def fmt_percent(n) -> str:
    """Format a percentage with a colored circle indicator.

    Examples:
        fmt_percent(3.14)  -> "🟢 +3.14%"
        fmt_percent(-1.5)  -> "🔴 -1.50%"
    """
    if n is None:
        return "N/A"
    icon = "🟢" if n >= 0 else "🔴"
    return f"{icon} {n:+.2f}%"
