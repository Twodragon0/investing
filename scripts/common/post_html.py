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
    HTML/markdown). Empty bullets list returns ``""``.
    """
    bullet_list = list(bullets)
    if not bullet_list:
        return ""
    items_html = "".join(f"<li>{b}</li>" for b in bullet_list)
    return (
        f'<div class="alert-box alert-{variant}">'
        f"<strong>{title}</strong>"
        f"<ul>{items_html}</ul>"
        f"</div>"
    )


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
