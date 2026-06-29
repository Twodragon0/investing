"""generate_daily_summary — 한국어 텍스트/노이즈 정리 leaf 헬퍼 (L0).

`summary_sections.py` 에서 추출(2026-06-29, L2 분리 캠페인). 제목/불릿 정리,
노이즈 필터, 한국어 표기 정규화 등 최하위 leaf 헬퍼. 다른 분리 모듈을 import
하지 않는다(순수 L0). [[summary-analysis]](L1)·섹션 빌더(L2)가 이 위에 쌓인다.
메인 모듈/테스트는 gds.<name> 으로 재-export 참조한다.
"""

import logging
import re
from typing import Any, Dict, List  # noqa: F401

from common.translator import get_display_title, translate_to_korean
from common.utils import SOURCE_SUFFIX_RE as _SOURCE_SUFFIX_RE

logger = logging.getLogger("daily-summary")


_SUMMARY_KEYWORD_LABELS = {
    "sec": "SEC",
    "cftc": "CFTC",
    "etf": "ETF",
    "whale": "고래",
    "opec": "OPEC",
    "fed": "연준",
    "fomc": "FOMC",
    "usd/krw": "원/달러",
    "dxy": "달러인덱스",
}

_NOISE_TITLE_PATTERNS = [
    re.compile(r"^new cryptocurrency listing[s]?$", re.I),
    re.compile(r"^new fiat listing[s]?$", re.I),
    re.compile(r"^api update[s]?$", re.I),
    re.compile(r"^new listing[s]?$", re.I),
    re.compile(r"^maintenance update[s]?$", re.I),
    re.compile(r"^scheduled maintenance", re.I),
    re.compile(r"^notice:", re.I),
    re.compile(r"^announcement$", re.I),
    re.compile(r"^latest (?:binance |)(?:news|activities|announcements)$", re.I),
    re.compile(r"^delisting", re.I),
    re.compile(r"^token (?:swap|migration)", re.I),
    re.compile(r"^trading pair (?:add|remov)", re.I),
    re.compile(r"^system (?:upgrade|maintenance)", re.I),
    re.compile(r"^\[.*\]\s*$"),
    re.compile(r"^wallet maintenance", re.I),
    re.compile(r"^notice of removal", re.I),
    re.compile(r"^listing (?:of|new)", re.I),
    re.compile(r"^margin tier update", re.I),
    re.compile(r"^api (?:update|maintenance|change)", re.I),
    re.compile(r"^(?:AMENDMENT|FORM)\s+(?:NO\.?\s*)?\d", re.I),
    re.compile(r"^(?:10-[KQ]|8-K|DEF\s*14|S-\d|F-\d)", re.I),
    re.compile(r"^asst-\d+", re.I),
]


def _strip_markdown_link(text: str) -> str:
    text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)
    text = text.replace("**", "")
    return text.strip()


def _is_noise_title(title: str) -> bool:
    """Return True if *title* is a low-value noise headline (e.g. exchange notices)."""
    clean = _strip_markdown_link(title).strip()
    if len(clean) < 10:
        return True
    clean_lower = clean.lower()
    # SEC/regulatory filing artifact: "Washington, DC 20549"
    if "dc 20549" in clean_lower or "20549" in clean:
        return True
    # Filing-style IDs: mostly uppercase letters, numbers, dashes, no spaces
    # e.g. "FORM-10K-2024", "DEF14A", "8-K/A"
    if re.match(r"^[A-Z0-9/\-]{4,20}$", clean):
        return True
    if any(
        kw in clean_lower
        for kw in [
            "가격 알림",
            "price alert",
            "share rewards",
            "보상을 공유",
            "vip loan",
            "vip 대출",
            "hodler airdrop",
            "hodler 에어드롭",
            "perpetual milestone challenge",
            "무기한 계약 출시",
            "상품 에디션",
            "기간 한정 혜택",
            "연이율 최대",
            "적립 구독",
            "획득하세요",
            "수익 창출 아레나",
            "yield arena",
        ]
    ):
        return True
    # Exchange wallet/system maintenance notices
    if any(
        kw in clean_lower
        for kw in [
            "wallet maintenance",
            "system maintenance",
            "scheduled maintenance",
            "notice of removal",
            "network upgrade",
            "margin tier update",
        ]
    ):
        return True
    return any(p.match(clean) for p in _NOISE_TITLE_PATTERNS)


def _clean_bullet_text(text: str) -> str:
    text = _strip_markdown_link(text)
    if text.startswith("- "):
        text = text[2:]
    return text.strip()


def _clean_headline(title: str) -> str:
    """Remove trailing period artifacts (.., ..., double periods) from a headline."""
    title = title.rstrip()
    title = _SOURCE_SUFFIX_RE.sub("", title)
    # Collapse multiple trailing dots/ellipsis into nothing or single ellipsis
    title = re.sub(r"\.{2,}$", "", title)
    title = re.sub(r"\.\s*\.$", "", title)
    return title.rstrip(". ").strip()


def _looks_english_heavy(text: str) -> bool:
    letters = re.findall(r"[A-Za-z]", text)
    korean = re.findall(r"[가-힣]", text)
    if len(letters) < 8:
        return False
    return len(letters) > len(korean) * 2


def _headline_for_korean_summary(title: str) -> str:
    cleaned = _clean_headline(title)
    if _looks_english_heavy(cleaned):
        translated = translate_to_korean(cleaned).strip()
        if translated:
            return _clean_headline(translated)
    return cleaned


def _summary_keywords_for_korean(keywords: List[str]) -> str:
    converted = []
    seen = set()
    for kw in keywords:
        normalized = _SUMMARY_KEYWORD_LABELS.get(kw.lower(), _headline_for_korean_summary(kw))
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        converted.append(normalized)
    return ", ".join(converted)


def _display_title_for_korean_item(item: Dict[str, Any]) -> str:
    return _headline_for_korean_summary(get_display_title(item))


def _description_for_korean_item(item: Dict[str, Any]) -> str:
    desc = (item.get("description_ko") or item.get("description") or "").strip()
    return _headline_for_korean_summary(desc) if desc else ""


def _best_non_noise_title(titles: List[str]) -> str:
    for title in titles:
        cleaned = _headline_for_korean_summary(title)
        if len(cleaned) > 15 and not _is_noise_title(cleaned):
            return cleaned
    return ""
