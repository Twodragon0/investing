"""Priority classification for news items.

Extracted from summarizer.py to keep classification logic isolated from the
larger ThemeSummarizer class. Pure data + a single free function — safe to
import anywhere with no dependency on summarizer.py.

Public API:
- ``PRIORITY_KEYWORDS``: dict of P0/P1/P2 keyword lists.
- ``_P0_RE``, ``_P1_RE``, ``_P2_RE``: compiled regex patterns.
- ``_make_keyword_pattern``: helper for word-boundary regex construction.
- ``classify_priority(items)``: bucket items into {"P0", "P1", "P2"} lists.
"""

import re
from typing import Any, Dict, List

# Priority classification keywords
PRIORITY_KEYWORDS: Dict[str, List[str]] = {
    "P0": [
        "crash",
        "폭락",
        "hack",
        "해킹",
        "executive order",
        "행정명령",
        "rate decision",
        "금리 결정",
        "파산",
        "bankruptcy",
        "emergency",
        "긴급",
        "bank run",
        "뱅크런",
        "exploit",
        "rug pull",
        "circuit breaker",
        "서킷브레이커",
        "사이드카",
        "flash crash",
        "급락",
        "theft",
        "도난",
        "zero-day",
    ],
    "P1": [
        "regulation",
        "규제",
        "etf",
        "approval",
        "fomc",
        "tariff",
        "관세",
        "earnings",
        "실적",
        "sanctions",
        "제재",
        "indictment",
        "기소",
        "sec filing",
        "listing",
        "상장",
        "delisting",
        "상장폐지",
        "인수",
        "acquisition",
        "merger",
        "합병",
        "ipo",
        "antitrust",
        "독점",
        "반독점",
        "settlement",
        "합의",
        "fine",
        "벌금",
        "경고",
        "warning",
    ],
    "P2": [
        "partnership",
        "upgrade",
        "launch",
        "airdrop",
        "report",
        "update",
        "integration",
        "collaboration",
        "제휴",
        "출시",
        "업그레이드",
        "에어드롭",
        "리포트",
        "mainnet",
        "메인넷",
        "testnet",
        "테스트넷",
        "roadmap",
        "로드맵",
        "whitepaper",
        "백서",
        "funding",
        "투자유치",
        "series",
        "시리즈",
    ],
}


def _make_keyword_pattern(keywords: list) -> re.Pattern:
    """Compile a regex that matches each keyword at word boundaries.

    English keywords use ``\\b`` anchors; Korean/mixed keywords use
    negative look-around assertions so that a match is only valid when not
    immediately surrounded by Korean or ASCII letters.
    """
    parts = []
    for kw in keywords:
        escaped = re.escape(kw)
        if re.match(r"^[a-zA-Z]", kw):
            parts.append(r"\b" + escaped + r"\b")
        else:
            parts.append(r"(?<![가-힣a-zA-Z])" + escaped + r"(?![가-힣a-zA-Z])")
    return re.compile("|".join(parts), re.IGNORECASE)


_P0_RE = _make_keyword_pattern(PRIORITY_KEYWORDS["P0"])
_P1_RE = _make_keyword_pattern(PRIORITY_KEYWORDS["P1"])
_P2_RE = _make_keyword_pattern(PRIORITY_KEYWORDS["P2"])


def classify_priority(items: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Classify items into priority buckets (P0, P1, P2).

    Returns dict with keys "P0", "P1", "P2" mapping to lists of items.
    Items are matched using word-boundary regex patterns to reduce false
    positives from substring matches (e.g. "crashed" matching "crash").
    Each item is assigned to only its highest priority bucket.
    Title is counted once: translated title takes precedence over original
    to avoid double-counting the same keyword from both fields.
    Identical titles (case-insensitive) are deduplicated within each bucket.
    """
    result: Dict[str, List[Dict[str, Any]]] = {"P0": [], "P1": [], "P2": []}
    assigned: set = set()
    seen_titles: Dict[str, set] = {"P0": set(), "P1": set(), "P2": set()}

    for priority, pattern in [("P0", _P0_RE), ("P1", _P1_RE), ("P2", _P2_RE)]:
        for idx, item in enumerate(items):
            if idx in assigned:
                continue
            # Use translated title when available, with title_original as the
            # alternate; count it once to avoid inflating keyword hits via
            # both fields.
            title = item.get("title") or item.get("title_original") or ""
            description = item.get("description") or ""
            text = (title + " " + description).lower()
            if pattern.search(text):
                # Deduplicate identical titles within the same bucket
                title_key = title.strip().lower()
                if title_key and title_key in seen_titles[priority]:
                    assigned.add(idx)
                    continue
                result[priority].append(item)
                assigned.add(idx)
                if title_key:
                    seen_titles[priority].add(title_key)

    return result
