"""Shared number and percentage formatting helpers."""


def fmt_number(n, prefix: str = "$", decimals: int = 2) -> str:
    """Format a number with K/M/B/T suffix and prefix.

    Examples:
        fmt_number(1_500_000_000) -> "$1.50B"
        fmt_number(42.5, prefix="", decimals=1) -> "42.5"
    """
    if n is None:
        return "N/A"
    if abs(n) >= 1_000_000_000_000:
        return f"{prefix}{n / 1_000_000_000_000:,.2f}T"
    if abs(n) >= 1_000_000_000:
        return f"{prefix}{n / 1_000_000_000:,.2f}B"
    if abs(n) >= 1_000_000:
        return f"{prefix}{n / 1_000_000:,.1f}M"
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
