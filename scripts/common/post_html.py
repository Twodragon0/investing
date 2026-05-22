"""Shared HTML builders for daily report posts.

Centralises the three repeating blocks (stat-grid / alert-box / footer-meta)
that 7 daily-report collectors emit by hand. Goal: single source of truth so
the Designer-audited conventions (div-based stat-value, 3-coloured alert
classes, wm-footer-meta layout) stay consistent and future tweaks land in
one place instead of fanning out across 7 files.
"""

from __future__ import annotations

from typing import Iterable, Literal, Sequence

AlertVariant = Literal["info", "warning", "urgent"]

# Variant icons surface meaning beyond the border color so the callout is
# distinguishable for color-blind readers (WCAG 1.4.1). The icons live in
# Python rather than CSS so screen readers receive them as part of the title.
_ALERT_ICON: dict[str, str] = {
    "info": "ℹ️",
    "warning": "⚠️",
    "urgent": "🚨",
}


def stat_grid(items: Sequence[tuple[str, str]]) -> str:
    """Render a `<div class="stat-grid">` with `<div class="stat-item">` children.

    `items` is a sequence of ``(value, label)`` tuples. Empty input returns ``""``
    so callers can chain without conditional wrappers.
    """
    if not items:
        return ""
    cells = "".join(
        f'<div class="stat-item"><div class="stat-value">{value}</div>'
        f'<div class="stat-label">{label}</div></div>'
        for value, label in items
    )
    return f'<div class="stat-grid">{cells}</div>'


def alert_box(title: str, bullets: Iterable[str], variant: AlertVariant = "info") -> str:
    """Render a `<div class="alert-box alert-{variant}">` callout.

    `bullets` items are inserted as raw `<li>` content (caller controls inline
    HTML/markdown). Empty bullets list returns ``""``. A variant-specific icon
    is prepended to the title so the callout's role stays legible without
    relying on the border color (WCAG 1.4.1).
    """
    bullet_list = list(bullets)
    if not bullet_list:
        return ""
    items_html = "".join(f"<li>{b}</li>" for b in bullet_list)
    icon = _ALERT_ICON[variant]
    return (
        f'<div class="alert-box alert-{variant}">'
        f"<strong>{icon} {title}</strong>"
        f"<ul>{items_html}</ul>"
        f"</div>"
    )


def summary_intro(
    date: str,
    label: str,
    headline: str | None,
    *,
    source: str | None = None,
    detail: str = "",
) -> str:
    """Render the lead paragraph that becomes ``page.excerpt``.

    Standard format used by daily-report collectors:
        ``**{date}** {label}: **{headline}** ({source}). {detail}\\n``

    Headline-missing fallback:
        ``**{date}** {label} — {detail}\\n``

    The trailing newline is included so callers can prepend the result directly
    to a section body without manual spacing.
    """
    if headline:
        src_part = f" ({source})" if source else ""
        return f"**{date}** {label}: **{headline}**{src_part}. {detail}\n"
    if detail:
        return f"**{date}** {label} — {detail}\n"
    return f"**{date}** {label}.\n"


def footer_meta(timestamp: str, sources: str | Sequence[str]) -> str:
    """Render the `<div class="wm-footer-meta">` post footer.

    `timestamp` is rendered as-is (caller decides locale/format). `sources`
    accepts either a pre-joined string or an iterable of source names.
    """
    if not isinstance(sources, str):
        sources = ", ".join(s for s in sources if s)
    return (
        f'<div class="wm-footer-meta">'
        f"<span>수집 시각: {timestamp}</span>"
        f"<span>소스: {sources or 'N/A'}</span>"
        f"</div>"
    )
