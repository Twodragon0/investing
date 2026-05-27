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

# Inline SVG icons (MIT-licensed shapes inspired by Heroicons/Material). Inline
# rather than asset files so each post stays self-contained, and the path
# inherits the surrounding `<strong>` color via fill="currentColor" — no
# extra CSS to keep dark/light theme parity. aria-hidden because the
# accompanying title text already conveys the semantic role (WCAG 1.1.1).
_SVG_TEMPLATE = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" '
    'viewBox="0 0 24 24" fill="currentColor" aria-hidden="true" '
    'focusable="false" class="alert-icon">{path}</svg>'
)

_ALERT_ICON: dict[str, str] = {
    "info": _SVG_TEMPLATE.format(
        path='<path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-6h2v6zm0-8h-2V7h2v2z"/>'
    ),
    "warning": _SVG_TEMPLATE.format(path='<path d="M1 21h22L12 2 1 21zm12-3h-2v-2h2v2zm0-4h-2v-4h2v4z"/>'),
    "urgent": _SVG_TEMPLATE.format(
        path='<path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z"/>'
    ),
}


def stat_grid(items: Sequence[tuple[str, str]]) -> str:
    """Render a `<div class="stat-grid">` with `<div class="stat-item">` children.

    `items` is a sequence of ``(value, label)`` tuples. Empty input returns ``""``
    so callers can chain without conditional wrappers.
    """
    if not items:
        return ""
    cells = "".join(
        f'<div class="stat-item"><div class="stat-value">{value}</div><div class="stat-label">{label}</div></div>'
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
    return f'<div class="alert-box alert-{variant}"><strong>{icon} {title}</strong><ul>{items_html}</ul></div>'


def summary_intro(
    date: str,
    label: str,
    headline: str | None,
    *,
    tag: str | None = None,
    detail: str = "",
) -> str:
    """Render the lead paragraph that becomes ``page.excerpt``.

    Standard format used by daily-report collectors:
        ``**{date}** {label}: **{headline}** ({tag}). {detail}\\n``

    ``tag`` is the short qualifier shown in parentheses after the headline.
    It is purposefully generic — callers use it for source attribution
    ("GDELT", "Google News"), theme classification ("군사/분쟁"), or any
    other one-token context cue. Pass ``None`` to omit the parens entirely.

    Headline-missing fallback:
        ``**{date}** {label} — {detail}\\n``

    The trailing newline is included so callers can prepend the result directly
    to a section body without manual spacing.
    """
    if headline:
        tag_part = f" ({tag})" if tag else ""
        return f"**{date}** {label}: **{headline}**{tag_part}. {detail}\n"
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
    return f'<div class="wm-footer-meta"><span>수집 시각: {timestamp}</span><span>소스: {sources or "N/A"}</span></div>'
