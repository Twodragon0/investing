import re
from html import escape
from typing import Dict, Iterable, List, Optional, Sequence


def escape_table_cell(value: object) -> str:
    text = str(value or "").replace("\n", " ").strip()
    return text.replace("|", "\\|")


def markdown_link(text: str, url: str) -> str:
    return f"[{escape_table_cell(text)}]({url})"


def markdown_table(
    headers: Sequence[str],
    rows: Iterable[Sequence[object]],
    aligns: Optional[Sequence[str]] = None,
) -> str:
    safe_headers = [escape_table_cell(h) for h in headers]
    header_line = "| " + " | ".join(safe_headers) + " |"

    if aligns and len(aligns) == len(headers):
        sep_cells: List[str] = []
        for align in aligns:
            if align == "right":
                sep_cells.append("---:")
            elif align == "center":
                sep_cells.append(":---:")
            else:
                sep_cells.append("---")
    else:
        sep_cells = ["---" for _ in headers]

    sep_line = "| " + " | ".join(sep_cells) + " |"
    row_lines = ["| " + " | ".join(escape_table_cell(c) for c in row) + " |" for row in rows]
    return "\n".join([header_line, sep_line, *row_lines])


def html_text(value: object) -> str:
    return escape(str(value or "").replace("|", "&#124;").strip(), quote=True)


def html_details_list(summary: str, items: Iterable[str], css_class: str = "details-content") -> str:
    li = "".join(f"<li>{item}</li>" for item in items)
    return f'<details><summary>{html_text(summary)}</summary><div class="{css_class}"><ol>{li}</ol></div></details>'


_SOURCE_TYPE_MAP: Dict[str, str] = {}
_SOURCE_RULES: List[tuple] = [
    ("crypto-media", ["coindesk", "decrypt", "cointelegraph", "theblock", "bitcoinmagazine", "blockworks"]),
    ("exchange", ["binance", "okx", "bybit", "upbit", "coinbase", "bithumb", "kraken", "bitfinex"]),
    ("finance-media", ["reuters", "bloomberg", "cnbc", "marketwatch", "wsj", "ft.com", "barron"]),
    ("world-media", ["bbc", "guardian", "al jazeera", "nytimes", "washingtonpost", "worldmonitor"]),
    ("regulator", ["sec", "cftc", "금융위", "금감원", "fca", "esma", "bis", "federal reserve"]),
    ("aggregator", ["google news", "rss", "yahoo", "investing.com"]),
]


def _classify_source(source: str) -> str:
    """Classify source name into one of 6 predefined types for color coding."""
    if not source:
        return "default"
    low = source.lower().strip()
    # Check cache first
    if low in _SOURCE_TYPE_MAP:
        return _SOURCE_TYPE_MAP[low]
    for src_type, keywords in _SOURCE_RULES:
        for kw in keywords:
            if kw in low:
                _SOURCE_TYPE_MAP[low] = src_type
                return src_type
    _SOURCE_TYPE_MAP[low] = "default"
    return "default"


def html_source_tag(source: str) -> str:
    src_type = _classify_source(source)
    return f'<span class="source-tag" data-source-type="{src_type}">{html_text(source)}</span>'


_GOOGLE_NEWS_RE = re.compile(
    r"https://news\.google\.com/(?:read|rss/articles)/(CBMi[A-Za-z0-9_\-]+)",
    re.IGNORECASE,
)


def _normalize_url(url: str) -> str:
    """Return a canonical key for deduplication.

    Google News publishes the same article under two URL schemes::

        https://news.google.com/read/CBMi<id>
        https://news.google.com/rss/articles/CBMi<id>

    Both are normalised to ``gnews:<id>`` so they are treated as duplicates.
    All other URLs are returned unchanged.
    """
    m = _GOOGLE_NEWS_RE.match(url)
    if m:
        return f"gnews:{m.group(1)}"
    return url


def dedupe_references(references: Iterable[Dict[str, str]], limit: Optional[int] = None) -> List[Dict[str, str]]:
    deduped: List[Dict[str, str]] = []
    seen_keys: set = set()

    for ref in references:
        link = str(ref.get("link", "")).strip()
        if not link:
            continue
        key = _normalize_url(link)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduped.append(
            {
                "title": str(ref.get("title", "")).strip(),
                "link": link,
                "source": str(ref.get("source", "")).strip(),
            }
        )
        if limit is not None and len(deduped) >= limit:
            break

    return deduped


def smart_truncate(text: str, max_len: int) -> str:
    """Truncate *text* to at most *max_len* characters without cutting mid-word.

    Truncation always happens at the last whitespace boundary within the
    allowed length so that words like "De", "Io", or "Wisdom" are never
    produced by a mid-word cut.  A trailing ellipsis ("…") is appended when
    the text is shortened.
    """
    if len(text) <= max_len:
        return text
    # Reserve 1 character for the ellipsis so the final string stays within
    # max_len.
    candidate = text[: max_len - 1]
    last_space = candidate.rfind(" ")
    # Only snap to the word boundary when the result would not be too short
    # (require at least 70% of the allowed length to avoid over-trimming).
    if last_space >= int(max_len * 0.7):
        candidate = candidate[:last_space]
    return candidate.rstrip() + "…"


# Backward-compatible alias
_truncate_title = smart_truncate


def html_reference_details(
    summary: str,
    references: Iterable[Dict[str, str]],
    limit: int = 20,
    title_max_len: int = 90,
    css_class: str = "details-content",
    open_in_new_tab: bool = False,
    include_count: bool = True,
) -> str:
    deduped_refs = dedupe_references(references, limit=limit)
    if not deduped_refs:
        return ""

    attrs = ' target="_blank" rel="noopener noreferrer"' if open_in_new_tab else ""
    items = []
    for ref in deduped_refs:
        title = html_text(_truncate_title(ref["title"], title_max_len))
        link = html_text(ref["link"])
        source = html_source_tag(ref["source"])
        items.append(f'<a href="{link}"{attrs}>{title}</a> {source}')

    summary_text = summary
    if include_count:
        summary_text = f"{summary} ({len(deduped_refs)}건)"

    return html_details_list(summary_text, items, css_class=css_class)
