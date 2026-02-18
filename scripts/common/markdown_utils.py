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
    row_lines = [
        "| " + " | ".join(escape_table_cell(c) for c in row) + " |" for row in rows
    ]
    return "\n".join([header_line, sep_line, *row_lines])


def html_text(value: object) -> str:
    return escape(str(value or "").replace("|", "&#124;").strip(), quote=True)


def html_details_list(
    summary: str, items: Iterable[str], css_class: str = "details-content"
) -> str:
    li = "".join(f"<li>{item}</li>" for item in items)
    return (
        f"<details><summary>{html_text(summary)}</summary>"
        f'<div class="{css_class}"><ol>{li}</ol></div></details>'
    )


def html_source_tag(source: str) -> str:
    return f'<span class="source-tag">{html_text(source)}</span>'


def dedupe_references(
    references: Iterable[Dict[str, str]], limit: Optional[int] = None
) -> List[Dict[str, str]]:
    deduped: List[Dict[str, str]] = []
    seen_links = set()

    for ref in references:
        link = str(ref.get("link", "")).strip()
        if not link or link in seen_links:
            continue
        seen_links.add(link)
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
        title = html_text(ref["title"][:title_max_len])
        link = html_text(ref["link"])
        source = html_source_tag(ref["source"])
        items.append(f'<a href="{link}"{attrs}>{title}</a> {source}')

    summary_text = summary
    if include_count:
        summary_text = f"{summary} ({len(deduped_refs)}건)"

    return html_details_list(summary_text, items, css_class=css_class)
