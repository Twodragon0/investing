from html import escape
from typing import Iterable, List, Optional, Sequence


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
