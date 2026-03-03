#!/usr/bin/env python3

import argparse
import os
import re
from html import unescape as html_unescape
from typing import Dict, List, Optional, Tuple

from common.config import setup_logging
from common.markdown_utils import markdown_table, smart_truncate
from common.worldmonitor_utils import worldmonitor_sort_key

logger = setup_logging("backfill_post_summaries")

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
POSTS_DIR = os.path.join(REPO_ROOT, "_posts")
SUMMARY_TITLE = "전체 뉴스 요약"
ANALYSIS_TITLE = "내용 분석"
URL_SUMMARY_TITLE = "URL 요약"

SECTION_PRIORITY = [
    "핵심 요약",
    "오늘의 핵심",
    "전체 뉴스 요약",
    "뉴스 내용 기반 핵심 요약",
    "시장 인사이트",
    "오늘의 시장 인사이트",
    "시장 개요",
    "규제 인사이트",
    "정책 영향 분석",
    "소셜 동향 분석",
    "주요 소셜 미디어 트렌드",
    "정치·경제 동향",
    "DeFi 시장 인사이트",
    "한눈에 보기",
]

IMAGE_MARKDOWN_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
IMAGE_HTML_RE = re.compile(r"<img[^>]+src=[\"']([^\"']+)[\"']")
LIQUID_PATH_RE = re.compile(r"\{\{\s*['\"]([^'\"]+)['\"]\s*\|\s*relative_url\s*\}\}")


def _get_front_list(front: Dict[str, object], key: str) -> List[str]:
    value = front.get(key, [])
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, str) and value:
        return [value]
    return []


def _get_front_date(front: Dict[str, object]) -> str:
    date_val = front.get("date", "")
    if not isinstance(date_val, str):
        return ""
    return date_val[:10]


def split_frontmatter(content: str) -> Tuple[str, str]:
    if not content.startswith("---\n"):
        return "", content
    parts = content.split("---\n", 2)
    if len(parts) < 3:
        return "", content
    front = "---\n" + parts[1] + "---\n"
    body = parts[2]
    return front, body


def parse_frontmatter(frontmatter: str) -> Dict[str, object]:
    data: Dict[str, object] = {}
    if not frontmatter:
        return data
    for raw in frontmatter.splitlines():
        line = raw.strip()
        if not line or line == "---" or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip().strip('"')
        if value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            items = []
            if inner:
                for part in inner.split(","):
                    item = part.strip().strip('"')
                    if item:
                        items.append(item)
            data[key] = items
        else:
            data[key] = value
    return data


def clean_text(text: str) -> str:
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"`(.+?)`", r"\1", text)
    text = re.sub(r"\[(.+?)\]\([^\)]+\)", r"\1", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"Sponsored by[^.]*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\bSponsored\b.*", "", text, flags=re.IGNORECASE)
    return text.strip()


def is_noise_text(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    if stripped in {"---", "--", "-", "*"}:
        return True
    if re.match(r"^\*?총\s*\d+건\s*수집\*?$", stripped):
        return True
    if stripped.startswith(("![", "##")):
        return True
    if any(key in stripped.lower() for key in ["news-briefing", "source-distribution", "market-heatmap"]):
        return True
    if stripped.startswith("데이터 수집"):
        return True
    return False


def normalize_title(title: str) -> str:
    title = clean_text(title)
    title = title.replace("...", " ").replace("…", " ")
    title = re.sub(r"^\s*\d+\.\s*", "", title)
    title = re.sub(r"\s+[–—-]\s+\d+\.\s+\[.*$", "", title)
    title = re.sub(r"\s+-\s+[^-]+$", "", title)
    title = re.sub(r"\s+[–—]\s+[^–—]+$", "", title)
    title = re.sub(r"\s*\((?:상보|종합|라이브|Live.*?|Updated.*?)\)\s*", " ", title)
    title = re.sub(r"\s*\[(?:상보|종합|속보|단독|포토)\]\s*", " ", title)
    title = re.sub(r"\s+", " ", title)
    return title.strip()


def normalize_summary(text: str) -> str:
    text = clean_text(text)
    text = text.replace("...", " ").replace("…", " ")
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return ""
    sentences = re.split(r"(?<=[.!?])\s+|(?<=다\.)\s+|(?<=니다\.)\s+", text)
    sentence = sentences[0].strip() if sentences else text
    if len(sentence) < 20 and len(sentences) > 1:
        sentence = (sentence + " " + sentences[1]).strip()
    if not sentence:
        return ""
    if not re.search(r"[.!?]$", sentence):
        # Korean endings: 다/요/까/나/음/임/기/죠/지 — don't append extra suffix
        if not re.search(r"[다요까나음임기죠지]$", sentence):
            sentence += "."
    return sentence


def _shorten_title_for_summary(title: str, limit: int = 80) -> str:
    """Shorten a title to use as a summary, keeping meaningful content."""
    title = normalize_title(title)
    if len(title) <= limit:
        return title
    # Try to cut at a word boundary
    truncated = title[:limit]
    last_space = truncated.rfind(" ")
    if last_space > limit * 0.6:
        truncated = truncated[:last_space]
    # Remove trailing articles, prepositions, and conjunctions
    trailing_words = {
        "the",
        "a",
        "an",
        "of",
        "in",
        "on",
        "at",
        "to",
        "for",
        "and",
        "or",
        "but",
        "as",
        "by",
        "with",
        "from",
        "is",
        "are",
        "its",
        "their",
        "this",
        "that",
        "these",
        "those",
    }
    words = truncated.split()
    while len(words) > 3 and words[-1].lower().rstrip(".,;:- ") in trailing_words:
        words.pop()
    truncated = " ".join(words)
    return truncated.rstrip(".,;:- ") + "..."


def summarize_from_title(title: str) -> str:
    title = normalize_title(title)
    # Split concatenated titles (e.g. "New ListingCheck out the latest...")
    # Detect lowercase→uppercase boundary without space
    concat_match = re.search(r"[a-z][A-Z]", title)
    if concat_match:
        title = title[: concat_match.start() + 1]
    low = title.lower()
    subject = ""

    if any(k in low for k in ["bitcoin", "btc", "비트코인"]):
        subject = "비트코인"
    elif any(k in low for k in ["ethereum", "eth", "이더리움"]):
        subject = "이더리움"
    elif any(k in low for k in ["xrp", "ripple", "리플"]):
        subject = "XRP"
    elif any(k in low for k in ["solana", "솔라나"]) or re.search(r"\bsol\b", low):
        subject = "솔라나"
    elif any(k in low for k in ["nasdaq", "나스닥"]):
        subject = "나스닥"
    elif any(k in low for k in ["s&p", "s&p 500", "sp500", "s&p500"]):
        subject = "S&P 500"
    elif any(k in low for k in ["dow", "다우"]):
        subject = "다우존스"
    elif any(k in low for k in ["kospi", "코스피"]):
        subject = "코스피"
    elif any(k in low for k in ["kosdaq", "코스닥"]):
        subject = "코스닥"
    elif any(k in low for k in ["fed", "fomc", "연준"]):
        subject = "미 연준"
    elif any(k in low for k in ["sec", "cftc", "fsa", "fsc", "금융위원회", "금감원"]):
        subject = "규제 당국"
    elif any(k in low for k in ["etf", "상장지수펀드"]):
        subject = "ETF"
    elif any(
        k in low
        for k in [
            "binance",
            "coinbase",
            "kraken",
            "upbit",
            "bithumb",
            "bybit",
            "okx",
            "exchange",
            "거래소",
        ]
    ):
        subject = "거래소"
    elif any(k in low for k in ["환율", "dxy", "달러", "usd/krw"]):
        subject = "환율"
    elif any(k in low for k in ["crypto", "cryptocurrency", "암호화폐"]):
        subject = "암호화폐"
    elif any(k in low for k in ["금리", "cpi", "pce", "inflation", "yield"]):
        subject = "거시 지표"
    elif any(k in low for k in ["hack", "exploit", "breach", "ransom", "해킹", "취약"]):
        subject = "보안 사고"
    elif any(k in low for k in ["trump", "트럼프"]):
        subject = "트럼프"
    elif any(k in low for k in ["gold", "금값", "금가격"]):
        subject = "금"
    elif any(k in low for k in ["oil", "원유", "wti", "brent"]):
        subject = "원유"

    # Korean titles are already readable — use them directly
    if re.search(r"[가-힣]", title) and len(title) > 15:
        return normalize_summary(_shorten_title_for_summary(title, 100))

    # Use word-boundary matching for short keywords to avoid false positives
    # (e.g. "up" matching inside "pump", "setup"; "down" inside "countdown")
    _up_words = [
        "rises",
        "rise",
        "gains",
        "surge",
        "surges",
        "jump",
        "jumps",
        "climb",
        "climbs",
        "rebound",
        "rallies",
        "rally",
        "상승",
        "급등",
        "반등",
    ]
    _up_boundary = [re.compile(r"\bup\b", re.IGNORECASE)]
    price_up = any(k in low for k in _up_words) or any(p.search(title) for p in _up_boundary)
    _down_words = [
        "falls",
        "fall",
        "drops",
        "drop",
        "slump",
        "slides",
        "slide",
        "tumbles",
        "tumble",
        "crash",
        "sell-off",
        "plunge",
        "하락",
        "급락",
        "폭락",
    ]
    _down_boundary = [re.compile(r"\bdown\b", re.IGNORECASE)]
    price_down = any(k in low for k in _down_words) or any(p.search(title) for p in _down_boundary)

    # Build more specific summaries using title context
    if price_up and subject:
        return normalize_summary(f"{subject} 상승 — {_shorten_title_for_summary(title, 60)}")
    if price_down and subject:
        return normalize_summary(f"{subject} 하락 — {_shorten_title_for_summary(title, 60)}")
    if price_up:
        return normalize_summary(f"시장 상승 — {_shorten_title_for_summary(title, 60)}")
    if price_down:
        return normalize_summary(f"시장 하락 — {_shorten_title_for_summary(title, 60)}")
    if any(k in low for k in ["tariff", "관세", "trade war", "무역"]):
        return normalize_summary(f"무역·관세 — {_shorten_title_for_summary(title, 60)}")
    if any(k in low for k in ["crisis", "fear", "panic", "불안", "공포"]):
        return normalize_summary(f"시장 심리 — {_shorten_title_for_summary(title, 60)}")
    if any(k in low for k in ["hack", "exploit", "breach", "ransom", "해킹", "취약"]):
        return normalize_summary(f"보안 이슈 — {_shorten_title_for_summary(title, 60)}")
    if any(k in low for k in ["lawsuit", "court", "판결", "소송", "charged", "accused"]):
        return normalize_summary(f"법적 분쟁 — {_shorten_title_for_summary(title, 60)}")
    if any(k in low for k in ["listing", "listed", "상장", "상장폐지", "delist"]):
        return normalize_summary(f"상장·상폐 — {_shorten_title_for_summary(title, 60)}")
    if any(
        k in low
        for k in [
            "approval",
            "approve",
            "launch",
            "introduce",
            "발표",
            "공시",
            "announcement",
        ]
    ):
        return normalize_summary(f"{subject or '신규'} 발표 — {_shorten_title_for_summary(title, 60)}")
    if any(
        k in low
        for k in [
            "buy",
            "bought",
            "sell",
            "selling",
            "acquire",
            "stake",
            "holdings",
            "treasury",
            "매수",
            "매도",
        ]
    ):
        return normalize_summary(f"{subject or '기관'} 매수·매도 — {_shorten_title_for_summary(title, 60)}")
    if any(k in low for k in ["whale", "wallet", "transfer", "inflow", "outflow", "고래", "이체"]):
        return normalize_summary(f"온체인 이동 — {_shorten_title_for_summary(title, 60)}")
    if any(k in low for k in ["regulation", "regulatory", "법안", "규제", "정책"]):
        return normalize_summary(f"규제·정책 — {_shorten_title_for_summary(title, 60)}")
    if subject:
        return normalize_summary(f"{subject} — {_shorten_title_for_summary(title, 60)}")
    # Default: use shortened title directly
    return normalize_summary(_shorten_title_for_summary(title, 90))


def extract_links(lines: List[str]) -> List[Tuple[str, str, str, str]]:
    link_re = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)")
    html_re = re.compile(r"<a href=\"(https?://[^\"]+)\"[^>]*>([^<]+)</a>")
    source_re = re.compile(r"source-tag\">([^<]+)")
    results: List[Tuple[str, str, str, str]] = []

    i = 0
    while i < len(lines):
        line = lines[i]
        matches = list(link_re.finditer(line))
        html_matches = list(html_re.finditer(line))
        if not matches and not html_matches:
            i += 1
            continue

        link_items = []
        for m in matches:
            link_items.append((m.group(1), m.group(2)))
        for m in html_matches:
            link_items.append((m.group(2), m.group(1)))

        for raw_title, raw_url in link_items:
            title = html_unescape(raw_title)
            url = html_unescape(raw_url)
            desc = ""
            source = ""
            for look_ahead in range(1, 5):
                if i + look_ahead >= len(lines):
                    break
                nxt = lines[i + look_ahead].strip()
                if not nxt:
                    if desc:
                        break
                    continue
                if nxt.startswith(("## ", "### ")):
                    break
                if "![" in nxt:
                    continue
                if link_re.search(nxt) or html_re.search(nxt):
                    break
                src_match = source_re.search(nxt)
                if src_match:
                    source = clean_text(src_match.group(1))
                    continue
                if nxt.startswith("<"):
                    continue
                if not desc:
                    desc = nxt
            results.append((title, url, desc, source))
        i += 1

    seen = set()
    deduped = []
    for title, url, desc, source in results:
        if url in seen:
            continue
        seen.add(url)
        deduped.append((title, url, desc, source))
    return deduped


def build_url_summary(lines: List[str]) -> List[str]:
    items = extract_links(lines)
    summaries = []
    for title, url, desc, _source in items:
        summary = ""
        if desc and not is_noise_text(desc):
            summary = normalize_summary(desc)
        if summary:
            norm_summary = normalize_title(summary)
            norm_title = normalize_title(title)
            if norm_summary == norm_title or (
                norm_title and norm_title in norm_summary and len(norm_summary) <= len(norm_title) + 20
            ):
                summary = ""
        if not summary:
            summary = summarize_from_title(title)
        if summary and not re.search(r"[가-힣]", summary):
            summary = summarize_from_title(title)
        if not summary:
            continue
        clean_title = normalize_title(title)
        clean_title = re.sub(r"\s+\d+\.\s+\[.*$", "", clean_title).strip()
        if not clean_title:
            continue
        if re.match(r"^\d+\.\s*\[", summary):
            summary = summarize_from_title(clean_title)
        summaries.append(f"- [{clean_title}]({url}) — {summary}")
    return summaries


def find_heading_index(lines: List[str], title: str) -> int:
    pattern = re.compile(rf"^##\s+{re.escape(title)}\s*$")
    for idx, line in enumerate(lines):
        if pattern.match(line.strip()):
            return idx
    return -1


def find_section_end(lines: List[str], start_idx: int) -> int:
    for idx in range(start_idx + 1, len(lines)):
        if re.match(r"^##\s+", lines[idx].strip()):
            return idx
    return len(lines)


def extract_section_bullets(lines: List[str], title: str, limit: int = 3) -> List[str]:
    idx = find_heading_index(lines, title)
    if idx == -1:
        return []
    end = find_section_end(lines, idx)
    bullets: List[str] = []
    for line in lines[idx + 1 : end]:
        raw = line.strip()
        if raw.startswith(("- ", "* ")):
            cleaned = clean_text(raw[2:])
            if cleaned and not is_noise_text(cleaned):
                bullets.append(cleaned)
        if len(bullets) >= limit:
            break
    return bullets


def extract_section_sentences(lines: List[str], title: str, limit: int = 2) -> List[str]:
    idx = find_heading_index(lines, title)
    if idx == -1:
        return []
    end = find_section_end(lines, idx)
    results: List[str] = []
    for line in lines[idx + 1 : end]:
        raw = line.strip()
        if not raw:
            if results:
                break
            continue
        if raw.startswith(("#", "|", "!", "<", ">")):
            continue
        if raw.startswith(("- ", "* ")):
            continue
        cleaned = clean_text(raw)
        if cleaned and not is_noise_text(cleaned):
            cleaned = smart_truncate(cleaned, 160)
            results.append(cleaned)
        if len(results) >= limit:
            break
    return results


def extract_theme_names(lines: List[str]) -> List[str]:
    names: List[str] = []

    idx = find_heading_index(lines, "테마 스냅샷")
    if idx != -1:
        end = find_section_end(lines, idx)
        for line in lines[idx + 1 : end]:
            if not line.strip().startswith("|"):
                continue
            if "| ---" in line or "| 테마" in line:
                continue
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if cells:
                theme = clean_text(cells[0])
                if theme and theme not in names:
                    names.append(theme)
            if len(names) >= 3:
                return names

    label_pattern = re.compile(r"theme-label\">([^<]+)")
    for line in lines:
        match = label_pattern.search(line)
        if not match:
            continue
        label = clean_text(match.group(1))
        if label and label not in names:
            names.append(label)
        if len(names) >= 3:
            break

    return names


def extract_total_count(body: str) -> str:
    # Strip table rows and HTML blocks to avoid picking up embedded counts
    # (e.g. social media "총 25건" inside a dashboard table cell)
    cleaned = re.sub(r"^\|.*\|$", "", body, flags=re.MULTILINE)
    cleaned = re.sub(r"<[^>]+>.*?</[^>]+>", "", cleaned, flags=re.DOTALL)
    patterns = [
        r"총\s*\*\*(\d{1,6})\*\*\s*건",
        r"총\s*수집[^\d]*(\d{1,6})\s*건",
        r"수집\s*건수\s*[:：]?\s*(\d{1,6})",
        r"총\s*(\d{1,6})\s*건",
        r"(?:뉴스|이슈)\s*(\d{1,6})\s*건",
        r"(\d{1,6})\s*건\s*을\s*정리",
    ]
    for pattern in patterns:
        match = re.search(pattern, cleaned)
        if match:
            return match.group(1)
    return ""


def has_urgent_alert(body: str) -> bool:
    return "긴급 알림" in body or "alert-urgent" in body


def build_content_analysis(lines: List[str], body: str) -> List[str]:
    analysis = []
    total = extract_total_count(body)
    themes = extract_theme_names(lines)
    urgent_count = _extract_urgent_count(body)

    # Build a more informative analysis
    if total and themes:
        analysis.append(f"총 {total}건의 뉴스 중 {', '.join(themes[:2])} 테마가 가장 많은 비중을 차지합니다.")
    elif total:
        analysis.append(f"총 {total}건의 뉴스를 수집하여 주요 이슈를 정리했습니다.")

    if urgent_count:
        analysis.append(f"긴급 이슈 {urgent_count}건이 감지되어 우선 확인이 필요합니다.")

    # Count how many distinct content sections exist in the post
    found_sections = []
    for section in SECTION_PRIORITY:
        if find_heading_index(lines, section) != -1:
            found_sections.append(section)

    if found_sections and len(analysis) < 3:
        analysis.append(
            f"본문은 {', '.join(found_sections[:3])} 등 {len(found_sections)}개 섹션으로 구성되어 있습니다."
        )

    # Count links to indicate reference density
    link_count = sum(1 for line in lines if re.search(r"\[.*?\]\(https?://", line))
    if link_count > 5 and len(analysis) < 3:
        analysis.append(f"총 {link_count}개의 출처 링크가 포함되어 있어 원문 확인이 가능합니다.")

    if not analysis:
        analysis.append("핵심 이슈를 중심으로 요약과 링크를 정리했습니다.")
    return analysis[:3]


def extract_intro_bullets(lines: List[str], limit: int = 2) -> List[str]:
    paragraphs: List[str] = []
    buffer: List[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if buffer:
                paragraphs.append(" ".join(buffer))
                buffer = []
            continue
        if stripped.startswith(("#", "|", "!", "<", ">")):
            continue
        if stripped in {"---", "--"}:
            continue
        buffer.append(stripped)
    if buffer:
        paragraphs.append(" ".join(buffer))

    bullets: List[str] = []
    for para in paragraphs[:2]:
        cleaned = clean_text(para)
        cleaned = smart_truncate(cleaned, 160)
        if cleaned and not is_noise_text(cleaned):
            bullets.append(cleaned)
        if len(bullets) >= limit:
            break
    return bullets


def is_social_media_post(front: Dict[str, object], body: str) -> bool:
    title = str(front.get("title", ""))
    tags = _get_front_list(front, "tags")
    categories = _get_front_list(front, "categories")

    # Exclude daily summary posts that mention social media keywords
    if front.get("pin") and "market-analysis" in categories:
        return False
    if "일일요약" in tags or "일일 뉴스 종합" in title:
        return False

    if "social-media" in tags:
        return True
    if "소셜 미디어 동향" in title:
        return True
    return "소셜 미디어" in body and "텔레그램" in body


def _extract_social_counts(body: str) -> Dict[str, str]:
    counts = {}
    patterns = {
        "total": r"총\s*(\d{1,5})\s*건",
        "telegram": r"텔레그램\s*(\d{1,5})\s*건",
        "social": r"소셜\s*미디어\s*(\d{1,5})\s*건",
        "political": r"정치·경제\s*(\d{1,5})\s*건",
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, body)
        if match:
            counts[key] = match.group(1)
    return counts


def _extract_social_themes(body: str, limit: int = 3) -> List[str]:
    themes = []
    for match in re.finditer(r"<strong>([^<]+)</strong>\s*\(\d+건\)", body):
        theme = clean_text(match.group(1))
        if theme and theme not in themes:
            themes.append(theme)
        if len(themes) >= limit:
            break
    return themes


def _extract_urgent_count(body: str) -> int:
    if "긴급 알림" not in body:
        return 0
    block = re.search(r"긴급 알림.*?(</ul>|\n\n)", body, flags=re.DOTALL)
    if not block:
        return 1
    return len(re.findall(r"<li>", block.group(0))) or 1


def _trim_sentence(text: str, limit: int = 110) -> str:
    text = normalize_summary(text)
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def build_social_summary(body: str) -> List[str]:
    counts = _extract_social_counts(body)
    total = counts.get("total", "0")
    telegram = counts.get("telegram", "0")
    social = counts.get("social", "0")
    political = counts.get("political", "0")
    themes = _extract_social_themes(body)
    urgent = _extract_urgent_count(body)

    themes_text = " 및 ".join(themes[:2]) if themes else "다양한"
    urgent_text = f"긴급 알림 {urgent}건" if urgent else "긴급 알림 없음"

    lines = [
        _trim_sentence(
            f"오늘 수집된 총 {total}건 중 텔레그램 {telegram}건, 소셜 {social}건, "
            f"정치·경제 {political}건으로 {themes_text} 이슈가 주요 화제입니다.",
            160,
        ),
        "",
        "**핵심 신호 정리**",
        f"- 주요 테마: {', '.join(themes) if themes else '다양한 이슈'}",
        f"- {urgent_text}에 대한 선별 모니터링",
    ]

    return lines


def build_summary(lines: List[str], body: str) -> List[str]:
    summary: List[str] = []
    total = extract_total_count(body)
    if total:
        summary.append(f"총 **{total}건** 수집")

    theme_names = extract_theme_names(lines)
    if theme_names:
        summary.append(f"주요 테마: {', '.join(theme_names)}")

    used = set(summary)

    for section in SECTION_PRIORITY:
        for bullet in extract_section_bullets(lines, section, limit=3):
            if bullet in used:
                continue
            if total and total in bullet and ("총" in bullet or "수집" in bullet):
                continue
            summary.append(bullet)
            used.add(bullet)
            if len(summary) >= 4:
                return summary
        for sentence in extract_section_sentences(lines, section, limit=2):
            if sentence in used:
                continue
            summary.append(sentence)
            used.add(sentence)
            if len(summary) >= 4:
                return summary

    if len(summary) < 3:
        for bullet in extract_intro_bullets(lines, limit=3):
            if bullet in used:
                continue
            summary.append(bullet)
            used.add(bullet)
            if len(summary) >= 4:
                break

    return summary[:4]


def insert_summary(lines: List[str], summary_lines: List[str]) -> List[str]:
    if not summary_lines:
        return lines

    summary_block = [f"## {SUMMARY_TITLE}", ""]
    summary_block.extend([f"- {line}" for line in summary_lines])
    summary_block.append("")

    for title in ("한눈에 보기", "핵심 요약"):
        idx = find_heading_index(lines, title)
        if idx != -1:
            end = find_section_end(lines, idx)
            return lines[:end] + [""] + summary_block + lines[end:]

    start = 0
    while start < len(lines) and not lines[start].strip():
        start += 1
    end = start
    while end < len(lines) and lines[end].strip():
        end += 1
    return lines[:end] + [""] + summary_block + lines[end:]


def insert_social_summary(lines: List[str], summary_lines: List[str]) -> List[str]:
    if not summary_lines:
        return lines

    summary_block = [f"## {SUMMARY_TITLE}", ""]
    summary_block.extend(summary_lines)
    summary_block.append("")

    for title in ("한눈에 보기", "핵심 요약"):
        idx = find_heading_index(lines, title)
        if idx != -1:
            end = find_section_end(lines, idx)
            return lines[:end] + [""] + summary_block + lines[end:]

    start = 0
    while start < len(lines) and not lines[start].strip():
        start += 1
    end = start
    while end < len(lines) and lines[end].strip():
        end += 1
    return lines[:end] + [""] + summary_block + lines[end:]


def _extract_local_image_path(raw: str) -> str:
    text = raw.strip()
    if text.startswith("http://") or text.startswith("https://"):
        return ""
    if text.startswith("data:"):
        return ""

    liquid_match = LIQUID_PATH_RE.search(text)
    if liquid_match:
        return liquid_match.group(1).strip()

    return text


def remove_missing_local_images(lines: List[str]) -> List[str]:
    cleaned: List[str] = []
    for line in lines:
        markdown_match = IMAGE_MARKDOWN_RE.search(line)
        html_match = IMAGE_HTML_RE.search(line)
        if not markdown_match and not html_match:
            cleaned.append(line)
            continue

        raw_path = ""
        if markdown_match:
            raw_path = markdown_match.group(1)
        elif html_match:
            raw_path = html_match.group(1)
        image_path = _extract_local_image_path(raw_path)
        if not image_path:
            cleaned.append(line)
            continue

        normalized = image_path.lstrip("./")
        if normalized.startswith("/"):
            normalized = normalized.lstrip("/")
        if normalized.startswith("assets/"):
            file_path = os.path.join(REPO_ROOT, normalized)
        else:
            file_path = os.path.join(REPO_ROOT, normalized)

        if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
            cleaned.append(line)
    return cleaned


def normalize_worldmonitor_snapshot(lines: List[str]) -> List[str]:
    marker_idx = -1
    for idx, line in enumerate(lines):
        if "오늘의 글로벌 리스크 스냅샷" in line:
            marker_idx = idx
            break

    if marker_idx == -1:
        return lines

    if '<div class="alert-box alert-info">' in lines[marker_idx]:
        return lines
    if marker_idx > 0 and '<div class="alert-box alert-info">' in lines[marker_idx - 1]:
        return lines

    total_line = ""
    theme_line = ""
    source_line = ""
    end_idx = marker_idx

    for idx in range(marker_idx + 1, min(len(lines), marker_idx + 10)):
        raw = lines[idx].strip()
        if not raw:
            end_idx = idx
            break
        if raw.startswith("## "):
            end_idx = idx
            break
        cleaned = clean_text(raw)
        if cleaned.startswith("총 수집:"):
            total_line = cleaned
        elif cleaned.startswith("핵심 테마:"):
            theme_line = cleaned
        elif cleaned.startswith("집중 출처:"):
            source_line = cleaned
        end_idx = idx + 1

    total_line = total_line or "총 수집: N/A"
    theme_line = theme_line or "핵심 테마: N/A"
    source_line = source_line or "집중 출처: N/A"

    replacement = [
        '<div class="alert-box alert-info"><strong>오늘의 글로벌 리스크 스냅샷</strong><ul>',
        f"<li>{total_line}</li>",
        f"<li>{theme_line}</li>",
        f"<li>{source_line}</li>",
        "</ul></div>",
    ]

    return lines[:marker_idx] + replacement + lines[end_idx:]


def list_zero_byte_images() -> List[str]:
    assets_dir = os.path.join(REPO_ROOT, "assets", "images", "generated")
    zero_files: List[str] = []
    if not os.path.isdir(assets_dir):
        return zero_files

    for root, _dirs, files in os.walk(assets_dir):
        for filename in files:
            path = os.path.join(root, filename)
            try:
                if os.path.getsize(path) == 0:
                    zero_files.append(os.path.relpath(path, REPO_ROOT))
            except OSError:
                continue

    return sorted(zero_files)


def remove_existing_summary(lines: List[str]) -> Tuple[List[str], bool]:
    idx = find_heading_index(lines, SUMMARY_TITLE)
    if idx == -1:
        return lines, False
    end = find_section_end(lines, idx)
    return lines[:idx] + lines[end:], True


def remove_existing_url_summary(lines: List[str]) -> Tuple[List[str], bool]:
    idx = find_heading_index(lines, URL_SUMMARY_TITLE)
    if idx == -1:
        return lines, False
    end = find_section_end(lines, idx)
    return lines[:idx] + lines[end:], True


def remove_existing_analysis(lines: List[str]) -> Tuple[List[str], bool]:
    idx = find_heading_index(lines, ANALYSIS_TITLE)
    if idx == -1:
        return lines, False
    end = find_section_end(lines, idx)
    return lines[:idx] + lines[end:], True


def insert_analysis(lines: List[str], analysis_lines: List[str]) -> List[str]:
    if not analysis_lines:
        return lines
    block = [f"## {ANALYSIS_TITLE}", ""]
    block.extend([f"- {line}" for line in analysis_lines])
    block.append("")
    idx = find_heading_index(lines, SUMMARY_TITLE)
    if idx != -1:
        end = find_section_end(lines, idx)
        return lines[:end] + [""] + block + lines[end:]
    return lines + [""] + block


def insert_url_summary(lines: List[str], summary_lines: List[str]) -> List[str]:
    if not summary_lines:
        return lines

    block = [f"## {URL_SUMMARY_TITLE}", ""]
    block.extend(summary_lines)
    block.append("")

    idx = find_heading_index(lines, ANALYSIS_TITLE)
    if idx != -1:
        end = find_section_end(lines, idx)
        return lines[:end] + [""] + block + lines[end:]
    idx = find_heading_index(lines, SUMMARY_TITLE)
    if idx != -1:
        end = find_section_end(lines, idx)
        return lines[:end] + [""] + block + lines[end:]

    start = 0
    while start < len(lines) and not lines[start].strip():
        start += 1
    end = start
    while end < len(lines) and lines[end].strip():
        end += 1
    return lines[:end] + [""] + block + lines[end:]


def _parse_table(lines: List[str], start_idx: int) -> Tuple[int, List[List[str]]]:
    rows: List[List[str]] = []
    idx = start_idx
    if idx >= len(lines):
        return start_idx, rows

    header = lines[idx].strip()
    if not (header.startswith("|") and header.endswith("|")):
        return start_idx, rows

    idx += 1
    if idx >= len(lines):
        return start_idx, rows

    sep = lines[idx].strip()
    if "---" not in sep:
        return start_idx, rows

    idx += 1
    while idx < len(lines):
        line = lines[idx].strip()
        if not line or not (line.startswith("|") and line.endswith("|")):
            break
        cells = [c.strip() for c in line.strip("|").split("|")]
        rows.append(cells)
        idx += 1

    return idx, rows


def reorder_worldmonitor_table(
    lines: List[str],
    front: Dict[str, object],
    wm_from: Optional[str] = None,
    wm_to: Optional[str] = None,
) -> List[str]:
    idx = find_heading_index(lines, "주요 이슈")
    if idx == -1:
        return lines

    title = str(front.get("title", ""))
    tags = _get_front_list(front, "tags")
    if "worldmonitor" not in tags and "WorldMonitor" not in title and "월드모니터" not in title:
        return lines

    post_date = _get_front_date(front)
    if wm_from and post_date and post_date < wm_from:
        return lines
    if wm_to and post_date and post_date > wm_to:
        return lines

    table_start = idx + 1
    while table_start < len(lines) and not lines[table_start].strip().startswith("|"):
        if lines[table_start].strip().startswith("## "):
            return lines
        table_start += 1

    if table_start >= len(lines):
        return lines

    header = lines[table_start].strip()
    if "시장 영향" not in header or "테마" not in header or "이슈" not in header:
        return lines

    table_end, rows = _parse_table(lines, table_start)
    if not rows:
        return lines

    def _rank_cell(cells: List[str]) -> Tuple[int, int]:
        impact = clean_text(cells[3]) if len(cells) > 3 else ""
        theme = clean_text(cells[2]) if len(cells) > 2 else ""
        return worldmonitor_sort_key(impact, theme)

    sorted_rows = sorted(rows, key=_rank_cell)

    rebuilt = []
    for i, cells in enumerate(sorted_rows, 1):
        if cells:
            cells[0] = str(i)
        rebuilt.append(cells)

    table_text = markdown_table(
        ["순번", "주요 이슈", "테마", "시장 영향", "출처"],
        rebuilt,
        aligns=["center", "left", "center", "center", "left"],
    )
    new_lines = lines[:table_start]
    new_lines.extend(table_text.splitlines())
    new_lines.extend(lines[table_end:])
    return new_lines


def process_post(
    filepath: str,
    wm_from: Optional[str] = None,
    wm_to: Optional[str] = None,
    clean_images_only: bool = False,
) -> bool:
    with open(filepath, encoding="utf-8") as f:
        content = f.read()

    front, body = split_frontmatter(content)
    if not body:
        return False

    front_data = parse_frontmatter(front)

    original_lines = body.splitlines()
    lines = normalize_worldmonitor_snapshot(original_lines)
    if clean_images_only:
        updated_lines = remove_missing_local_images(lines)
        if updated_lines == lines:
            return False
        updated_content = front + "\n".join(updated_lines).rstrip() + "\n"
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(updated_content)
        return True

    stripped_lines, _ = remove_existing_summary(lines)
    stripped_lines, _ = remove_existing_analysis(stripped_lines)
    stripped_lines, _ = remove_existing_url_summary(stripped_lines)
    rebuilt_body = "\n".join(stripped_lines)

    # Skip redundant "전체 뉴스 요약" if post already has a summary section
    has_existing_summary = any(find_heading_index(stripped_lines, t) != -1 for t in ("오늘의 핵심", "핵심 요약"))

    if is_social_media_post(front_data, rebuilt_body):
        summary_lines = build_social_summary(rebuilt_body)
        updated_lines = insert_social_summary(stripped_lines, summary_lines)
    elif has_existing_summary:
        # Post already has a prominent summary — don't duplicate
        updated_lines = stripped_lines
    else:
        summary_lines = build_summary(stripped_lines, rebuilt_body)
        updated_lines = insert_summary(stripped_lines, summary_lines)
    updated_lines = reorder_worldmonitor_table(updated_lines, front_data, wm_from, wm_to)
    updated_lines = remove_missing_local_images(updated_lines)

    if updated_lines == original_lines:
        return False

    updated_content = front + "\n".join(updated_lines).rstrip() + "\n"
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(updated_content)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill post summaries and reorder WorldMonitor tables.")
    parser.add_argument(
        "--wm-from",
        dest="wm_from",
        help="Reorder WorldMonitor tables from date (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--wm-to",
        dest="wm_to",
        help="Reorder WorldMonitor tables up to date (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--clean-images-only",
        action="store_true",
        help="Remove missing or zero-byte local images only.",
    )
    parser.add_argument(
        "--zero-image-report",
        dest="zero_image_report",
        help="Write a report of zero-byte images to the given path.",
    )
    parser.add_argument(
        "--from-date",
        dest="from_date",
        help="Process posts from date (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--to-date",
        dest="to_date",
        help="Process posts up to date (YYYY-MM-DD).",
    )
    args = parser.parse_args()

    if args.zero_image_report:
        report_path = args.zero_image_report
        os.makedirs(os.path.dirname(report_path), exist_ok=True)
        zero_files = list_zero_byte_images()
        with open(report_path, "w", encoding="utf-8") as f:
            f.write("Zero-byte images\n")
            f.write("=================\n")
            if not zero_files:
                f.write("None\n")
            else:
                for rel_path in zero_files:
                    f.write(f"- {rel_path}\n")

    if not os.path.isdir(POSTS_DIR):
        logger.warning("Posts directory not found: %s", POSTS_DIR)
        return

    updated = 0
    total = 0
    for filename in sorted(os.listdir(POSTS_DIR)):
        if not filename.endswith(".md"):
            continue
        post_date = filename[:10]
        if args.from_date and post_date < args.from_date:
            continue
        if args.to_date and post_date > args.to_date:
            continue
        total += 1
        filepath = os.path.join(POSTS_DIR, filename)
        if process_post(
            filepath,
            wm_from=args.wm_from,
            wm_to=args.wm_to,
            clean_images_only=args.clean_images_only,
        ):
            updated += 1

    logger.info("Checked %d posts, updated %d", total, updated)


if __name__ == "__main__":
    main()
