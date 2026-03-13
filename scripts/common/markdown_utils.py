import re
from html import escape
from typing import Dict, Iterable, List, Optional, Sequence


def escape_table_cell(value: object) -> str:
    text = str(value or "").replace("\n", " ").strip()
    return text.replace("|", "\\|")


def markdown_link(text: str, url: str) -> str:
    safe = escape_table_cell(text).replace("[", "\\[").replace("]", "\\]")
    return f"[{safe}]({url})"


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


def html_table(
    headers: Sequence[str],
    rows: Iterable[Sequence[object]],
    aligns: Optional[Sequence[str]] = None,
) -> str:
    align_map = {"left": "left", "center": "center", "right": "right"}
    if aligns and len(aligns) == len(headers):
        header_aligns = [align_map.get(a, "left") for a in aligns]
    else:
        header_aligns = ["left" for _ in headers]

    thead_cells = "".join(
        f'<th style="text-align:{align};">{html_text(header)}</th>'
        for header, align in zip(headers, header_aligns, strict=False)
    )

    body_rows = []
    for row in rows:
        body_cells = "".join(
            f'<td style="text-align:{align};">{cell}</td>' for cell, align in zip(row, header_aligns, strict=False)
        )
        body_rows.append(f"<tr>{body_cells}</tr>")

    tbody = "".join(body_rows)
    return f"<table><thead><tr>{thead_cells}</tr></thead><tbody>{tbody}</tbody></table>"


def html_report_links(rows: Iterable[Sequence[object]]) -> str:
    category_notes = {
        "암호화폐 뉴스": "가격, 거래소, 온체인 이슈를 빠르게 점검합니다.",
        "defi tvl 리포트": "체인별 TVL 흐름과 자금 이동을 비교합니다.",
        "시장 종합 리포트": "주요 지수와 자산군 흐름을 한 번에 확인합니다.",
        "규제 동향": "정책, 감독기관 발표, 법안 변화를 추적합니다.",
        "소셜 미디어": "커뮤니티 심리와 화제 키워드를 압축해 봅니다.",
        "월드모니터 브리핑": "거시, 지정학, 에너지 변수의 시장 영향을 훑습니다.",
        "경제 캘린더": "핵심 경제 지표 일정과 이벤트 리스크를 체크합니다.",
        "일일 시장 종합": "당일 자산 흐름과 핵심 포인트를 요약합니다.",
        "주식 시장 뉴스": "기업, 지수, 섹터별 재료를 빠르게 추립니다.",
        "소셜 미디어 동향": "투자자 심리와 실시간 반응을 정리합니다.",
        "블록체인 보안": "해킹, 취약점, 보안 경보를 우선 확인합니다.",
        "kospi 투자자 수급": "유가증권시장 수급 흐름을 바로 확인합니다.",
        "kosdaq 투자자 수급": "코스닥 수급과 위험 선호 변화를 체크합니다.",
    }

    def normalize_category(value: object) -> str:
        text = str(value or "").strip()
        text = re.sub(r"^[^\w가-힣A-Za-z]+\s*", "", text)
        return text.lower()

    cards = []
    row_count = 0
    for row in rows:
        values = list(row)
        if len(values) != 3:
            continue
        category, count, link_html = values
        note = category_notes.get(normalize_category(category), "관련 세부 리포트로 바로 이동합니다.")
        row_count += 1
        cards.extend(
            [
                '  <div class="report-links-card">',
                '    <div class="report-links-meta">',
                f'      <div class="report-links-category">{category}</div>',
                f'      <div class="report-links-note">{html_text(note)}</div>',
                "    </div>",
                f'    <div class="report-links-count">{html_text(count)}</div>',
                f'    <div class="report-links-action">{link_html}</div>',
                "  </div>",
            ]
        )

    return "\n".join(
        [
            '<div class="report-links-board">',
            '  <div class="report-links-summary">',
            '    <div class="report-links-summary-label">Quick Access</div>',
            f'    <div class="report-links-summary-text">지금 확인할 수 있는 세부 리포트 {row_count}개를 주제별로 정리했습니다.</div>',
            "  </div>",
            '  <div class="report-links-head">',
            '    <span class="report-links-head-item report-links-head-category">카테고리</span>',
            '    <span class="report-links-head-item report-links-head-count">건수</span>',
            '    <span class="report-links-head-item report-links-head-link">리포트 링크</span>',
            "  </div>",
            '  <div class="report-links-grid">',
            *cards,
            "  </div>",
            "</div>",
        ]
    )


def html_details_list(summary: str, items: Iterable[str], css_class: str = "details-content") -> str:
    li = "".join(f"<li>{item}</li>" for item in items)
    return f'<details><summary>{html_text(summary)}</summary><div class="{css_class}"><ol>{li}</ol></div></details>'


_SOURCE_TYPE_MAP: Dict[str, str] = {}
_SOURCE_RULES: List[tuple] = [
    ("crypto-media", ["coindesk", "decrypt", "cointelegraph", "theblock", "bitcoinmagazine", "blockworks"]),
    ("exchange", ["binance", "okx", "bybit", "upbit", "coinbase", "bithumb", "kraken", "bitfinex"]),
    ("finance-media", ["reuters", "bloomberg", "cnbc", "marketwatch", "wsj", "ft.com", "barron"]),
    ("world-media", ["bbc", "guardian", "al jazeera", "nytimes", "washingtonpost", "worldmonitor"]),
    (
        "regulator",
        [
            "sec",
            "cftc",
            "금융위",
            "금감원",
            "fca",
            "esma",
            "bis",
            "federal reserve",
            "금융위원회",
            "한국은행",
            "금융감독원",
        ],
    ),
    ("aggregator", ["google news", "rss", "yahoo", "investing.com"]),
    ("kr-media", ["연합뉴스", "한국경제", "매일경제", "조선비즈", "서울경제", "이데일리", "머니투데이", "한겨레"]),
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
        entry: Dict[str, str] = {
            "title": str(ref.get("title", "")).strip(),
            "link": link,
            "source": str(ref.get("source", "")).strip(),
        }
        title_ko = ref.get("title_ko")
        if title_ko:
            entry["title_ko"] = str(title_ko).strip()
        deduped.append(entry)
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
    elif last_space < int(max_len * 0.7):
        # Korean fallback: try to break at sentence endings
        for ending in ["다.", "요.", "음.", "임.", "됨."]:
            ko_idx = candidate.rfind(ending, 0, max_len)
            if ko_idx >= int(max_len * 0.5):
                candidate = candidate[: ko_idx + len(ending)]
                break
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
        raw_title = ref.get("title_ko") or ref.get("title", "")
        title = html_text(_truncate_title(raw_title, title_max_len))
        link = html_text(ref["link"])
        source = html_source_tag(ref["source"])
        items.append(f'<a href="{link}"{attrs}>{title}</a> {source}')

    summary_text = summary
    if include_count:
        summary_text = f"{summary} ({len(deduped_refs)}건)"

    return html_details_list(summary_text, items, css_class=css_class)
