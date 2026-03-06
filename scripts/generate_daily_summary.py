#!/usr/bin/env python3
"""Generate a daily news summary post by reading today's collected posts.

Reads all posts generated for the current date and creates a comprehensive
summary post (pinned, market-analysis category) with priority-based structure:
1. Urgent alerts (P0) - crashes, hacks, executive orders
2. Market overview
3. Indicator dashboard
4. Political watch - politician trades/policy highlights
5. Important news (P1) - regulation, ETF, earnings
6. Category summaries
7. Notable news (P2)
8. Report links
"""

import glob
import os
import re
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common.config import SITE_URL, get_kst_timezone, setup_logging
from common.markdown_utils import _normalize_url, markdown_table, smart_truncate
from common.post_generator import POSTS_DIR
from common.summarizer import ThemeSummarizer
from common.translator import get_display_title

logger = setup_logging("generate_daily_summary")


_HTML_TAG_RE = re.compile(r"<[^>]+>")
_HTML_BLOCK_RE = re.compile(r"<div\b[^>]*>.*?</div>", re.DOTALL)


def strip_html_tags(text: str) -> str:
    """Remove HTML tags from text, preserving readable content."""
    # Remove entire HTML block elements (div, details, summary) first
    text = re.sub(r"<details[^>]*>.*?</details>", "", text, flags=re.DOTALL)
    text = _HTML_BLOCK_RE.sub("", text)
    # Remove remaining inline tags
    text = _HTML_TAG_RE.sub("", text)
    # Collapse multiple blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def read_post_content(filepath: str) -> Dict[str, Any]:
    """Read a Jekyll post and parse frontmatter + content."""
    try:
        with open(filepath, encoding="utf-8") as f:
            text = f.read()
    except OSError as e:
        logger.warning("Failed to read post %s: %s", filepath, e)
        return {"frontmatter": {}, "content": "", "filepath": filepath}

    # Parse frontmatter
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {"frontmatter": {}, "content": text, "filepath": filepath}

    frontmatter_text = parts[1].strip()
    content = parts[2].strip()

    frontmatter = {}
    for line in frontmatter_text.split("\n"):
        if ":" in line:
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            frontmatter[key] = value

    # Strip HTML tags from content for clean markdown extraction
    content = strip_html_tags(content)

    return {
        "frontmatter": frontmatter,
        "content": content,
        "filepath": filepath,
    }


def extract_section(content: str, heading: str) -> str:
    """Extract content under a specific ## heading."""
    pattern = rf"## {re.escape(heading)}\s*\n(.*?)(?=\n## |\Z)"
    match = re.search(pattern, content, re.DOTALL)
    return match.group(1).strip() if match else ""


def extract_bullet_points(content: str, heading: str, max_items: int = 5) -> List[str]:
    """Extract bullet points from a section."""
    section = extract_section(content, heading)
    if not section:
        return []

    bullets = []
    for line in section.split("\n"):
        line = line.strip()
        if line.startswith("- "):
            bullets.append(line)
            if len(bullets) >= max_items:
                break
    return bullets


def extract_table_rows(content: str, heading: str, max_rows: int = 10) -> List[str]:
    """Extract table rows (excluding header) from a section."""
    section = extract_section(content, heading)
    if not section:
        return []

    rows = []
    header_passed = 0
    for line in section.split("\n"):
        line = line.strip()
        if line.startswith("|"):
            header_passed += 1
            if header_passed > 2:  # Skip header + separator
                rows.append(line)
                if len(rows) >= max_rows:
                    break
    return rows


def count_news_items(content: str) -> int:
    """Try to extract total news count from content."""
    patterns = [
        r"(\d+)건의 뉴스",
        r"뉴스\s*(\d+)건",
        r"총 뉴스 건수\*?\*?:\s*(\d+)건",
        r"총 수집 건수\*?\*?:\s*(\d+)건",
        r"총\s*\*{0,2}(\d+)건\*{0,2}",
        r"(\d+)건이 수집",
    ]
    for pattern in patterns:
        match = re.search(pattern, content)
        if match:
            return int(match.group(1))
    return 0


def _extract_highlights(content: str) -> List[str]:
    """Extract highlight info from post opening and alert-info HTML."""
    highlights = []
    # Try opening paragraph (first non-empty line after frontmatter)
    for line in content.split("\n")[:5]:
        line = line.strip()
        if line.startswith("**") and "건" in line:
            highlights.append(f"- {line}")
            break
    # Try old-style sections as fallback
    for section in ["오늘의 핵심", "핵심 요약"]:
        bullets = extract_bullet_points(content, section)
        if bullets:
            highlights.extend(bullets)
            break
    # Try alert-info content
    match = re.search(r'class="alert-box alert-info"[^>]*>.*?<strong>(.*?)</strong>', content)
    if match and not highlights:
        highlights.append(f"- {match.group(1)}")
    return highlights


def summarize_crypto_post(post: Dict[str, Any]) -> Dict[str, Any]:
    """Extract key info from crypto news post."""
    content = post["content"]
    count = count_news_items(content)
    highlights = _extract_highlights(content)

    # Extract themes from HTML progress bars or ASCII chart
    themes = []
    for match in re.finditer(r'class="theme-label">.\s*(\S+)</span>.*?(\d+)건', content):
        themes.append((match.group(1), int(match.group(2))))
    if not themes:
        dist_section = extract_section(content, "이슈 분포 현황")
        if dist_section:
            for line in dist_section.split("\n"):
                m = re.match(r"(\S+)\s+[█░]+\s+\d+%\s+\((\d+)건\)", line.strip())
                if m:
                    themes.append((m.group(1), int(m.group(2))))

    return {
        "type": "crypto",
        "title": post["frontmatter"].get("title", ""),
        "count": count,
        "highlights": highlights,
        "key_summary": highlights,
        "themes": themes,
        "content": content,
    }


def summarize_stock_post(post: Dict[str, Any]) -> Dict[str, Any]:
    """Extract key info from stock news post."""
    content = post["content"]
    count = count_news_items(content)
    highlights = _extract_highlights(content)

    market_data = []
    for line in content.split("\n")[:5]:
        if "KOSPI" in line or "KOSDAQ" in line or "USD/KRW" in line:
            market_data.append(line.strip())

    return {
        "type": "stock",
        "title": post["frontmatter"].get("title", ""),
        "count": count,
        "highlights": highlights,
        "key_summary": highlights,
        "market_data": market_data,
        "content": content,
    }


def summarize_security_post(post: Dict[str, Any]) -> Dict[str, Any]:
    """Extract key info from security post."""
    content = post["content"]
    count = count_news_items(content)
    key_summary = _extract_highlights(content)
    incidents = extract_table_rows(content, "보안 사고 현황", 5)

    return {
        "type": "security",
        "title": post["frontmatter"].get("title", ""),
        "count": count,
        "key_summary": key_summary,
        "incidents": incidents,
        "content": content,
    }


def summarize_regulatory_post(post: Dict[str, Any]) -> Dict[str, Any]:
    """Extract key info from regulatory post."""
    content = post["content"]
    count = count_news_items(content)
    key_summary = _extract_highlights(content)

    return {
        "type": "regulatory",
        "title": post["frontmatter"].get("title", ""),
        "count": count,
        "key_summary": key_summary,
        "content": content,
    }


def summarize_social_post(post: Dict[str, Any]) -> Dict[str, Any]:
    """Extract key info from social media post."""
    content = post["content"]
    count = count_news_items(content)
    highlights = _extract_highlights(content)

    return {
        "type": "social",
        "title": post["frontmatter"].get("title", ""),
        "count": count,
        "highlights": highlights,
        "key_summary": highlights,
        "content": content,
    }


def summarize_market_post(post: Dict[str, Any]) -> Dict[str, Any]:
    """Extract key info from market summary post."""
    content = post["content"]
    highlights = extract_bullet_points(content, "오늘의 핵심")
    exec_summary = extract_bullet_points(content, "한눈에 보기")

    # Extract indicator data
    indicator_rows = extract_table_rows(content, "매크로 경제 지표", 10)
    yield_section = extract_section(content, "국채 수익률 스프레드 (2Y-10Y)")
    sector_section = extract_section(content, "S&P 500 섹터 퍼포먼스")

    return {
        "type": "market",
        "title": post["frontmatter"].get("title", ""),
        "highlights": highlights,
        "exec_summary": exec_summary,
        "indicator_rows": indicator_rows,
        "yield_section": yield_section,
        "sector_section": sector_section,
        "content": content,
    }


def summarize_worldmonitor_post(post: Dict[str, Any]) -> Dict[str, Any]:
    content = post["content"]
    count = count_news_items(content)
    key_summary = extract_bullet_points(content, "핵심 요약", 4)
    issues = extract_table_rows(content, "주요 이슈", 6)

    if not count:
        for line in content.split("\n"):
            m = re.search(r"수집 건수:\s*\*\*(\d+)건\*\*", line)
            if m:
                count = int(m.group(1))
                break

    # Strip section headings and stat-grid blocks that would be duplicated
    cleaned = re.sub(r"^##\s+이슈 분포.*$", "", content, flags=re.MULTILINE)
    cleaned = re.sub(r'<div class="stat-grid">.*?</div>\s*</div>\s*</div>', "", cleaned, flags=re.DOTALL)

    return {
        "type": "worldmonitor",
        "title": post["frontmatter"].get("title", ""),
        "count": count,
        "key_summary": key_summary,
        "issues": issues,
        "content": cleaned,
    }


def _extract_bold_lines(content: str, heading: str, max_items: int = 5) -> List[str]:
    """Extract **bold**: text lines from a section (fallback for non-bullet sections)."""
    section = extract_section(content, heading)
    if not section:
        return []
    lines = []
    for line in section.split("\n"):
        stripped = line.strip()
        if stripped.startswith("**") and ":" in stripped:
            lines.append(f"- {stripped}")
            if len(lines) >= max_items:
                break
    return lines


def summarize_political_post(post: Dict[str, Any]) -> Dict[str, Any]:
    """Extract key info from political trades post."""
    content = post["content"]
    count = count_news_items(content)
    # Try multiple section names and formats used by political trades posts
    key_summary = (
        extract_bullet_points(content, "핵심 요약")
        or extract_bullet_points(content, "전체 뉴스 요약", 5)
        or _extract_bold_lines(content, "전체 뉴스 요약", 5)
    )
    highlights = (
        extract_bullet_points(content, "정책 영향 분석", 3)
        or _extract_bold_lines(content, "정책 영향 분석", 3)
        or extract_bullet_points(content, "한눈에 보기", 3)
    )

    return {
        "type": "political",
        "title": post["frontmatter"].get("title", ""),
        "count": count,
        "key_summary": key_summary,
        "highlights": highlights,
        "content": content,
    }


def get_post_url(filepath: str, today: str, category: str = "") -> str:
    """Generate absolute URL for a post following Jekyll permalink structure."""
    filename = os.path.basename(filepath)
    slug = filename.replace(f"{today}-", "").replace(".md", "")
    date_path = today.replace("-", "/")
    if category:
        return f"{SITE_URL}/{category}/{date_path}/{slug}/"
    return f"{SITE_URL}/{date_path}/{slug}/"


def _collect_all_news_items(summaries: List[Optional[Dict]]) -> List[Dict[str, Any]]:
    """Collect all news item titles+descriptions from post contents for priority classification."""
    items = []
    seen_titles = set()
    seen_urls: set[str] = set()
    for s in summaries:
        if not s or not s.get("content"):
            continue
        content = s["content"]
        in_card_section = False
        last_card_item: Optional[Dict[str, Any]] = None
        for line in content.split("\n"):
            line = line.strip()
            # Detect card section headers (### 🟠 비트코인, etc.)
            if line.startswith("### ") and "건)" in line:
                in_card_section = True
                continue
            # Extract from card format: **1. [Title](link)**
            if in_card_section and line.startswith("**") and "[" in line:
                match = re.search(r"\[([^\]]+)\]\(([^)]+)\)", line)
                if match:
                    title = match.group(1)
                    link = match.group(2)
                    url_key = _normalize_url(link)
                    # Deduplicate by normalized title and URL
                    norm = re.sub(r"[^a-z가-힣0-9]", "", title.lower())
                    if norm not in seen_titles and url_key not in seen_urls:
                        seen_titles.add(norm)
                        seen_urls.add(url_key)
                        last_card_item = {
                            "title": f"[{title}]({link})",
                            "description": title,
                            "link": link,
                            "source": s.get("type", ""),
                        }
                        items.append(last_card_item)
                    else:
                        last_card_item = None
                else:
                    last_card_item = None
            # Capture description line right after a card item
            elif (
                in_card_section
                and last_card_item is not None
                and not line.startswith(("**", ">", "`", "#", "|", "---", "<"))
                and line
                and len(line) > 15
            ):
                last_card_item["description"] = line
                last_card_item = None
            # Stop card parsing at next major section
            if line.startswith("## ") and in_card_section:
                in_card_section = False

        # Second comprehensive pass: extract ALL links from the full content
        # 1. <a href="URL">Title</a> tags (details blocks, HTML)
        for match in re.finditer(r'<a\s+href="([^"]+)"[^>]*>([^<]+)</a>', content):
            link = match.group(1)
            title = match.group(2).strip()
            if not title or len(title) < 10:
                continue
            url_key = _normalize_url(link)
            norm = re.sub(r"[^a-z가-힣0-9]", "", title.lower())
            if norm not in seen_titles and url_key not in seen_urls:
                seen_titles.add(norm)
                seen_urls.add(url_key)
                items.append({"title": title, "description": title, "link": link, "source": s.get("type", "")})

        # 2. Bullet points with markdown links: - [Title](URL) or - **[Title](URL)**
        for match in re.finditer(r"[-*]\s+(?:\*\*)?(?:\d+\.\s*)?\[([^\]]+)\]\(([^)]+)\)", content):
            title = match.group(1).strip()
            link = match.group(2).strip()
            if not title or len(title) < 10:
                continue
            url_key = _normalize_url(link)
            norm = re.sub(r"[^a-z가-힣0-9]", "", title.lower())
            if norm not in seen_titles and url_key not in seen_urls:
                seen_titles.add(norm)
                seen_urls.add(url_key)
                items.append({"title": title, "description": title, "link": link, "source": s.get("type", "")})

        # 3. All remaining markdown links: [Title](URL) or [**Title**](URL) (tables, etc.)
        for match in re.finditer(r"\[(?:\*\*)?([^\]]+?)(?:\*\*)?\]\(([^)]+)\)", content):
            title = match.group(1).strip()
            link = match.group(2).strip()
            if not title or len(title) < 10:
                continue
            url_key = _normalize_url(link)
            norm = re.sub(r"[^a-z가-힣0-9]", "", title.lower())
            if norm not in seen_titles and url_key not in seen_urls:
                seen_titles.add(norm)
                seen_urls.add(url_key)
                items.append({"title": title, "description": title, "link": link, "source": s.get("type", "")})

    return items


def _cross_asset_topics() -> Dict[str, List[str]]:
    return {
        "금리/유동성": [
            "금리",
            "연준",
            "fed",
            "fomc",
            "유동성",
            "국채",
            "yield",
            "기준금리",
            "인하",
            "인상",
            "양적",
            "긴축",
            "완화",
            "pivot",
        ],
        "환율/달러": [
            "환율",
            "usd/krw",
            "달러",
            "dxy",
            "원화",
            "엔화",
            "위안",
            "강달러",
            "약달러",
            "환헤지",
        ],
        "정책/규제": [
            "규제",
            "sec",
            "etf",
            "법안",
            "정책",
            "행정명령",
            "tariff",
            "관세",
            "승인",
            "거부",
            "감독",
            "제재",
            "스테이블코인",
            "자금세탁",
            "aml",
            "kyc",
            "mifid",
        ],
        "리스크 이벤트": [
            "해킹",
            "exploit",
            "파산",
            "청산",
            "liquidation",
            "보안사고",
            "러그풀",
            "디페깅",
            "depeg",
            "공격",
            "취약점",
            "유출",
        ],
        "수급/심리": [
            "고래",
            "whale",
            "수급",
            "공포",
            "탐욕",
            "sentiment",
            "social",
            "거래량",
            "미결제약정",
            "open interest",
            "펀딩비",
            "매수",
            "매도",
            "롱",
            "숏",
            "청산량",
        ],
        "실적/지표": [
            "실적",
            "cpi",
            "pce",
            "고용",
            "매출",
            "earnings",
            "gdp",
            "ism",
            "pmi",
            "소비자신뢰",
            "실업률",
            "비농업",
        ],
        "기술/온체인": [
            "tvl",
            "defi",
            "nft",
            "레이어2",
            "l2",
            "업그레이드",
            "하드포크",
            "반감기",
            "halving",
            "해시레이트",
            "gas",
        ],
        "지정학": [
            "전쟁",
            "분쟁",
            "제재",
            "opec",
            "원유",
            "에너지",
            "중국",
            "러시아",
            "대만",
            "nato",
            "무역전쟁",
        ],
    }


def _sentiment_keywords() -> Dict[str, List[str]]:
    """Keywords for positive/negative sentiment classification."""
    return {
        "positive": [
            "상승",
            "급등",
            "반등",
            "돌파",
            "신고가",
            "강세",
            "호재",
            "승인",
            "확대",
            "성장",
            "개선",
            "회복",
            "상향",
            "증가",
            "rally",
            "bull",
            "surge",
            "breakout",
            "upgrade",
            "adoption",
            "매수",
            "유입",
            "낙관",
            "기대감",
            "사상최고",
        ],
        "negative": [
            "하락",
            "급락",
            "폭락",
            "약세",
            "악재",
            "위험",
            "경고",
            "해킹",
            "파산",
            "소송",
            "제재",
            "규제",
            "위축",
            "감소",
            "crash",
            "bear",
            "dump",
            "hack",
            "exploit",
            "fraud",
            "매도",
            "유출",
            "공포",
            "불안",
            "하향",
            "적자",
        ],
    }


def _analyze_sentiment(summaries: List[Optional[Dict[str, Any]]]) -> Dict[str, Any]:
    """Analyze sentiment across all summaries by counting keyword hits in titles and content."""
    pos_kw = _sentiment_keywords()["positive"]
    neg_kw = _sentiment_keywords()["negative"]

    pos_count = 0
    neg_count = 0
    pos_examples: List[str] = []
    neg_examples: List[str] = []

    for s in summaries:
        if not s or not s.get("content"):
            continue
        # Analyze titles extracted from bullet points and headings
        titles = []
        content = s["content"]
        for line in content.split("\n"):
            line = line.strip()
            # Extract titles from markdown links
            for m in re.finditer(r"\[([^\]]+)\]", line):
                titles.append(m.group(1))
            # Extract from bold text
            for m in re.finditer(r"\*\*([^*]+)\*\*", line):
                titles.append(m.group(1))

        for title in titles:
            t_lower = title.lower()
            for kw in pos_kw:
                if kw in t_lower:
                    pos_count += 1
                    if len(pos_examples) < 3 and len(title) > 10:
                        if title not in pos_examples:
                            pos_examples.append(smart_truncate(title, 120))
                    break
            for kw in neg_kw:
                if kw in t_lower:
                    neg_count += 1
                    if len(neg_examples) < 3 and len(title) > 10:
                        if title not in neg_examples:
                            neg_examples.append(smart_truncate(title, 120))
                    break

    total = pos_count + neg_count
    if total == 0:
        tone = "중립"
        ratio = 50
    else:
        ratio = round(pos_count / total * 100)
        if ratio >= 65:
            tone = "긍정 우세"
        elif ratio >= 45:
            tone = "혼조"
        elif ratio >= 30:
            tone = "부정 우세"
        else:
            tone = "경계"

    return {
        "tone": tone,
        "positive": pos_count,
        "negative": neg_count,
        "ratio": ratio,
        "pos_examples": pos_examples,
        "neg_examples": neg_examples,
    }


def _extract_key_figures(content: str) -> List[str]:
    """Extract clean numeric data points (prices, index levels, percentages) from content."""
    figures: List[str] = []
    seen: set[str] = set()

    def _add(fig: str) -> None:
        key = re.sub(r"[^\w%.]", "", fig.lower())
        if key not in seen and len(fig) > 5:
            seen.add(key)
            figures.append(fig)

    # Market indices with percentage: "KOSPI 6,244.13(-1.00%)"
    for m in re.finditer(
        r"((?:KOSPI|KOSDAQ|S&P|나스닥|다우|USD/KRW|EUR/USD|BTC|ETH)"
        r"\s*[\d,.]+\s*\([+-]?[\d.]+%\))",
        content,
    ):
        _add(m.group(1).strip())

    # Named prices: "비트코인 83,200 달러" — require currency right after number
    for m in re.finditer(
        r"((?:비트코인|BTC|이더리움|ETH|KOSPI|KOSDAQ|S&P|나스닥|다우)"
        r"\s+[\d,.]+\s*(?:달러|원|포인트|pt))",
        content,
    ):
        _add(m.group(1).strip())

    # Explicit percentage changes: "전일 대비 +2.3%"
    for m in re.finditer(
        r"((?:전일|전주|전월|YoY|MoM|QoQ)\s*대비\s*[+-]?[\d.]+\s*%)",
        content,
    ):
        _add(m.group(1).strip())

    return figures[:5]


def _find_shared_topics_across_categories(
    summaries: List[Optional[Dict[str, Any]]],
) -> List[Tuple[str, int, List[str]]]:
    """Find topics that appear across multiple categories, returning (topic, category_count, categories)."""
    topic_defs = _cross_asset_topics()
    # Map: topic -> list of category names that mention it
    topic_presence: Dict[str, List[str]] = {t: [] for t in topic_defs}
    category_labels = {
        "crypto": "암호화폐",
        "stock": "주식",
        "regulatory": "규제",
        "social": "소셜",
        "worldmonitor": "월드모니터",
        "political": "정치인 거래",
        "market": "시장",
        "security": "보안",
    }

    for s in summaries:
        if not s or not s.get("content"):
            continue
        stype = s.get("type", "")
        label = category_labels.get(stype, stype)
        text = (s.get("content", "") + " " + " ".join(s.get("highlights", []) or [])).lower()
        for topic, keywords in topic_defs.items():
            for kw in keywords:
                if kw.lower() in text:
                    if label not in topic_presence[topic]:
                        topic_presence[topic].append(label)
                    break

    # Only topics mentioned in 2+ categories are cross-cutting
    cross_topics = [(topic, len(cats), cats) for topic, cats in topic_presence.items() if len(cats) >= 2]
    cross_topics.sort(key=lambda x: x[1], reverse=True)
    return cross_topics


def _extract_category_data_points(summary: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Extract structured data points from a category summary for richer output."""
    if not summary or not summary.get("content"):
        return {"titles": [], "figures": [], "theme_names": [], "count": 0}

    content = summary["content"]
    count = summary.get("count", 0)

    # Extract top titles (first 5 meaningful ones)
    titles: List[str] = []
    for m in re.finditer(r"(?<!!)\[([^\]]{10,})\]\(([^)]+)\)", content):
        title = m.group(1).strip()
        url = m.group(2)
        # Skip image file links (e.g. .png, .jpg, assets/images paths)
        if re.search(r"\.(png|jpg|jpeg|gif|svg|webp)", url, re.IGNORECASE):
            continue
        if _is_noise_title(title):
            continue
        if title not in titles:
            titles.append(title)
        if len(titles) >= 5:
            break

    # Numeric figures
    figures = _extract_key_figures(content)

    # Theme names from crypto themes
    theme_names = [t[0] for t in (summary.get("themes") or [])]

    return {
        "titles": titles,
        "figures": figures,
        "theme_names": theme_names,
        "count": count,
    }


def _topic_hits(summary: Optional[Dict[str, Any]]) -> Dict[str, int]:
    if not summary:
        return {}
    text = "\n".join(
        [
            summary.get("title", ""),
            summary.get("content", ""),
            " ".join(summary.get("highlights", []) or []),
            " ".join(summary.get("key_summary", []) or []),
        ]
    ).lower()
    hits: Dict[str, int] = {}
    for topic, keywords in _cross_asset_topics().items():
        score = 0
        matched_keywords: List[str] = []
        for kw in keywords:
            cnt = text.count(kw.lower())
            if cnt > 0:
                score += cnt
                matched_keywords.append(kw)
        hits[topic] = score
    return hits


def _relation_rows(
    summaries: Dict[str, Optional[Dict[str, Any]]],
) -> List[Tuple[str, str, int, str]]:
    rows: List[Tuple[str, str, int, str]] = []
    pairs = [
        ("암호화폐", "주식", "crypto", "stock"),
        ("암호화폐", "정치인 거래", "crypto", "political"),
        ("주식", "정치인 거래", "stock", "political"),
        ("암호화폐", "규제", "crypto", "regulatory"),
        ("주식", "규제", "stock", "regulatory"),
        ("암호화폐", "소셜", "crypto", "social"),
        ("월드모니터", "암호화폐", "worldmonitor", "crypto"),
        ("월드모니터", "주식", "worldmonitor", "stock"),
    ]
    topic_keys = list(_cross_asset_topics().keys())
    hit_maps = {k: _topic_hits(v) for k, v in summaries.items()}

    # Diagnostic templates by topic
    diagnostics = {
        "금리/유동성": "금리/유동성 이슈가 양쪽 자산에 동시 영향",
        "환율/달러": "달러·환율 변동이 교차 자산 민감도 확대",
        "정책/규제": "정책·규제 이벤트가 복수 시장에 파급",
        "리스크 이벤트": "리스크 이벤트(해킹/청산 등) 동시 노출",
        "수급/심리": "수급·심리 키워드 동반 급증 → 변동성 주의",
        "실적/지표": "매크로 지표 발표가 연쇄 반응 유발 가능",
        "기술/온체인": "온체인·기술 이슈가 시장 전반에 확산",
        "지정학": "지정학 리스크가 안전자산·위험자산 동시 압박",
    }

    for left_name, right_name, left_key, right_key in pairs:
        left = hit_maps.get(left_key, {})
        right = hit_maps.get(right_key, {})
        if not left or not right:
            continue
        shared_topics: List[Tuple[str, int]] = []
        for t in topic_keys:
            if left.get(t, 0) > 0 and right.get(t, 0) > 0:
                shared_topics.append((t, min(left[t], right[t])))
        shared_topics.sort(key=lambda x: x[1], reverse=True)
        if not shared_topics:
            rows.append((left_name, right_name, 0, "낮음 — 공통 이슈 미감지"))
            continue
        score = sum(v for _, v in shared_topics[:3])
        top_topic = shared_topics[0][0]
        diag = diagnostics.get(top_topic, f"{top_topic} 관련 공통 신호 감지")
        if score >= 20:
            level = "높음"
        elif score >= 12:
            level = "중간"
        else:
            level = "낮음"
        rows.append((left_name, right_name, score, f"{level} — {diag}"))
    return rows


def _coverage_warnings(summaries: Dict[str, Optional[Dict[str, Any]]]) -> List[str]:
    warnings = []
    if not summaries.get("crypto"):
        warnings.append("- 암호화폐 일일 리포트가 없어 코인-주식 연계 분석 정밀도가 낮습니다.")
    if not summaries.get("stock"):
        warnings.append("- 주식 일일 리포트가 없어 교차자산 수급 비교가 제한됩니다.")
    if not summaries.get("market"):
        warnings.append("- 시장 종합 리포트가 없어 매크로(금리/환율) 연결 해석이 제한됩니다.")
    if not summaries.get("worldmonitor"):
        warnings.append("- 월드모니터 브리핑이 없어 글로벌 지정학/에너지 리스크 연결 분석이 제한됩니다.")
    if not summaries.get("political") and not summaries.get("regulatory"):
        warnings.append("- 정책/규제 데이터가 부족해 이벤트 기반 리스크 점검이 약합니다.")
    return warnings


def _strip_markdown_link(text: str) -> str:
    text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)
    text = text.replace("**", "")
    return text.strip()


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
]


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
    # Collapse multiple trailing dots/ellipsis into nothing or single ellipsis
    title = re.sub(r"\.{2,}$", "", title)
    title = re.sub(r"\.\s*\.$", "", title)
    return title.rstrip(". ").strip()


def _to_theme_payload(
    summaries: Dict[str, Optional[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    payload = []
    topic_def = _cross_asset_topics()
    hit_totals = dict.fromkeys(topic_def.keys(), 0)
    for summary in summaries.values():
        hits = _topic_hits(summary)
        for k, v in hits.items():
            hit_totals[k] += v

    emojis = {
        "금리/유동성": "🏦",
        "환율/달러": "💵",
        "정책/규제": "📜",
        "리스크 이벤트": "🚨",
        "수급/심리": "🧭",
        "실적/지표": "📊",
    }

    for topic, score in sorted(hit_totals.items(), key=lambda x: x[1], reverse=True):
        if score <= 0:
            continue
        payload.append(
            {
                "name": topic,
                "emoji": emojis.get(topic, "•"),
                "count": score,
                "keywords": topic_def.get(topic, [])[:4],
            }
        )
    return payload[:5]


def _render_generated_image(filename: str, alt: str) -> Optional[str]:
    image_path = os.path.join(POSTS_DIR, "..", "assets", "images", "generated", filename)
    if not os.path.exists(image_path):
        return None
    return f"![{alt}]({{{{ '/assets/images/generated/{filename}' | relative_url }}}})"


def _resolve_frontmatter_image(today: str, briefing_image: Optional[str]) -> str:
    if briefing_image:
        return briefing_image

    candidates = [
        f"news-briefing-daily-{today}.png",
        f"news-briefing-{today}.png",
        f"market-heatmap-{today}.png",
    ]
    for filename in candidates:
        image_path = os.path.join(POSTS_DIR, "..", "assets", "images", "generated", filename)
        if os.path.exists(image_path):
            return f"/assets/images/generated/{filename}"
    return ""


def _build_snapshot_table(
    crypto_summary: Optional[Dict[str, Any]],
    stock_summary: Optional[Dict[str, Any]],
    worldmonitor_summary: Optional[Dict[str, Any]],
    regulatory_summary: Optional[Dict[str, Any]],
    social_summary: Optional[Dict[str, Any]],
    political_summary: Optional[Dict[str, Any]],
) -> List[str]:
    rows = []

    def top_signal(summary: Optional[Dict[str, Any]]) -> str:
        if not summary:
            return "데이터 없음"
        if summary.get("count", 0) == 0:
            return "데이터 없음"

        # Priority 1: market data (price, index values)
        if summary.get("market_data"):
            return smart_truncate(_clean_bullet_text(summary["market_data"][0]), 80)

        # Priority 2: meaningful highlights/key_summary
        hl = summary.get("highlights") or summary.get("key_summary") or []
        for h in hl:
            cleaned = _clean_bullet_text(h)
            # Skip noise: pure count lines, empty signals
            if re.match(r"^[\d,]+건", cleaned) or "수집 건수" in cleaned:
                continue
            if len(cleaned) > 15:
                return smart_truncate(cleaned, 80)

        # Priority 3: top theme + representative headline
        dp = _extract_category_data_points(summary)
        if dp["titles"]:
            headline = _clean_headline(dp["titles"][0])
            if len(headline) > 15 and not _is_noise_title(headline):
                return smart_truncate(headline, 80)

        # Priority 4: theme name with count
        if summary.get("themes"):
            name, cnt = summary["themes"][0]
            return f"{name} {cnt}건"

        return "신호 추출 실패"

    dataset = [
        ("암호화폐", crypto_summary),
        ("주식", stock_summary),
        ("월드모니터", worldmonitor_summary),
        ("규제", regulatory_summary),
        ("소셜", social_summary),
        ("정치인 거래", political_summary),
    ]
    for name, summary in dataset:
        count = summary.get("count", 0) if summary else 0
        has_data = summary is not None and count > 0
        count_display: Any = count if has_data else "-"
        signal = top_signal(summary)
        # When there is no data, collapse into a single clean "데이터 없음" signal
        if not has_data:
            signal = "데이터 없음"
        rows.append([name, count_display, signal])
    return [
        markdown_table(
            ["영역", "수집 건수", "핵심 신호"],
            rows,
            aligns=["left", "right", "left"],
        )
    ]


def main():
    """Generate daily news summary with priority-based structure."""
    logger.info("=== Generating daily news summary ===")

    today = datetime.now(get_kst_timezone()).strftime("%Y-%m-%d")

    # Find all posts for today
    pattern = os.path.join(POSTS_DIR, f"{today}-*.md")
    today_posts = sorted(glob.glob(pattern))

    if not today_posts:
        logger.warning("No posts found for today (%s), skipping summary", today)
        return

    logger.info("Found %d posts for %s", len(today_posts), today)

    # Read and categorize posts
    crypto_summary = None
    stock_summary = None
    security_summary = None
    regulatory_summary = None
    social_summary = None
    market_summary = None
    worldmonitor_summary = None
    political_summary = None

    post_links = []

    for filepath in today_posts:
        filename = os.path.basename(filepath)
        if "daily-news-summary" in filename or "test-post" in filename:
            continue

        post = read_post_content(filepath)
        slug = filename.replace(f"{today}-", "").replace(".md", "")

        if "crypto-news-digest" in slug:
            crypto_summary = summarize_crypto_post(post)
            crypto_summary["url"] = get_post_url(filepath, today, "crypto-news")
            post_links.append(("암호화폐 뉴스", crypto_summary["count"], crypto_summary["url"]))
        elif "stock-news-digest" in slug:
            stock_summary = summarize_stock_post(post)
            stock_summary["url"] = get_post_url(filepath, today, "stock-news")
            post_links.append(("주식 시장 뉴스", stock_summary["count"], stock_summary["url"]))
        elif "security-report" in slug:
            security_summary = summarize_security_post(post)
            security_summary["url"] = get_post_url(filepath, today, "security-alerts")
            post_links.append(("보안 리포트", security_summary["count"], security_summary["url"]))
        elif "regulatory-report" in slug:
            regulatory_summary = summarize_regulatory_post(post)
            regulatory_summary["url"] = get_post_url(filepath, today, "regulatory-news")
            post_links.append(("규제 동향", regulatory_summary["count"], regulatory_summary["url"]))
        elif "social-media-digest" in slug:
            social_summary = summarize_social_post(post)
            social_summary["url"] = get_post_url(filepath, today, "social-media")
            post_links.append(("소셜 미디어", social_summary["count"], social_summary["url"]))
        elif "political-trades-report" in slug:
            political_summary = summarize_political_post(post)
            political_summary["url"] = get_post_url(filepath, today, "political-trades")
            post_links.append(("정치인 거래", political_summary["count"], political_summary["url"]))
        elif slug == "daily-market-report" or slug.endswith("-market-report"):
            # Avoid matching crypto-market-report (already handled as crypto)
            if "crypto-market" in slug:
                continue
            market_summary = summarize_market_post(post)
            market_summary["url"] = get_post_url(filepath, today, "market-analysis")
            post_links.append(("시장 종합 리포트", market_summary.get("count", "-"), market_summary["url"]))
        elif "worldmonitor-briefing" in slug:
            worldmonitor_summary = summarize_worldmonitor_post(post)
            worldmonitor_summary["url"] = get_post_url(filepath, today, "market-analysis")
            post_links.append(
                (
                    "월드모니터 브리핑",
                    worldmonitor_summary["count"],
                    worldmonitor_summary["url"],
                )
            )

    # Calculate total count
    all_summaries = [
        crypto_summary,
        stock_summary,
        security_summary,
        regulatory_summary,
        social_summary,
        worldmonitor_summary,
        political_summary,
    ]
    total_count = sum(s["count"] for s in all_summaries if s and s.get("count"))

    # Priority classification
    all_news_items = _collect_all_news_items(all_summaries)
    priority_items = {"P0": [], "P1": [], "P2": []}
    if all_news_items:
        summarizer = ThemeSummarizer(all_news_items)
        priority_items = summarizer.classify_priority()

    summary_map = {
        "crypto": crypto_summary,
        "stock": stock_summary,
        "market": market_summary,
        "regulatory": regulatory_summary,
        "social": social_summary,
        "worldmonitor": worldmonitor_summary,
        "political": political_summary,
    }

    theme_payload = _to_theme_payload(summary_map)
    urgent_alerts = [_strip_markdown_link(get_display_title(x)) for x in priority_items.get("P0", [])]

    briefing_image = None
    try:
        from common.image_generator import generate_news_briefing_card

        briefing_image = generate_news_briefing_card(
            themes=theme_payload,
            date_str=today,
            category="Multi-Asset Daily Briefing",
            total_count=total_count,
            urgent_alerts=[x for x in urgent_alerts if x],
            filename=f"news-briefing-daily-{today}.png",
        )
    except Exception as e:
        logger.warning("Failed to generate daily briefing image: %s", e)

    # Build summary content
    content_parts = []

    # Opening with counts
    count_parts = []
    if crypto_summary and crypto_summary["count"]:
        count_parts.append(f"암호화폐 {crypto_summary['count']}건")
    if stock_summary and stock_summary["count"]:
        count_parts.append(f"주식 {stock_summary['count']}건")
    if security_summary and security_summary["count"]:
        count_parts.append(f"보안 {security_summary['count']}건")
    if regulatory_summary and regulatory_summary["count"]:
        count_parts.append(f"규제 {regulatory_summary['count']}건")
    if social_summary and social_summary["count"]:
        count_parts.append(f"소셜 미디어 {social_summary['count']}건")
    if worldmonitor_summary and worldmonitor_summary["count"]:
        count_parts.append(f"월드모니터 {worldmonitor_summary['count']}건")
    if political_summary and political_summary["count"]:
        count_parts.append(f"정치인 거래 {political_summary['count']}건")

    counts_str = ", ".join(count_parts) if count_parts else "뉴스"
    content_parts.append(f"> {counts_str}의 뉴스를 종합 분석한 일일 요약입니다.\n")

    # Calculate risk level
    p0_count = len(priority_items.get("P0", []))
    sentiment_for_risk = _analyze_sentiment(all_summaries)
    neg_ratio = 100 - sentiment_for_risk.get("ratio", 50)
    if p0_count >= 3 or neg_ratio >= 70:
        risk_level, risk_emoji = "높음", "🔴"
    elif p0_count >= 1 or neg_ratio >= 55:
        risk_level, risk_emoji = "주의", "🟡"
    else:
        risk_level, risk_emoji = "안정", "🟢"

    content_parts.append("> **한눈에 보는 시장 상황**")
    content_parts.append(f"> - 총 수집: **{total_count}건**")
    content_parts.append(f"> - 긴급 알림(P0): **{len(priority_items.get('P0', []))}건**")
    content_parts.append(f"> - 중요 뉴스(P1): **{len(priority_items.get('P1', []))}건**")
    content_parts.append(f"> - 리스크 레벨: **{risk_emoji} {risk_level}** (P0 {p0_count}건, 부정비율 {neg_ratio}%)\n")

    content_parts.append("## 전체 뉴스 요약\n")
    # Narrative-style summary
    if theme_payload and len(theme_payload) >= 2:
        theme_count = min(len(theme_payload), 3)
        content_parts.append(f"오늘 총 **{total_count}건**의 뉴스에서 크게 **{theme_count}가지 흐름**이 감지됩니다.\n")
        for i, item in enumerate(theme_payload[:3], 1):
            emoji = item.get("emoji", "•")
            name = item.get("name", "")
            score = item.get("count", 0)
            keywords = ", ".join(item.get("keywords", [])[:3])
            if keywords:
                content_parts.append(
                    f"{i}. **{emoji} {name}** (신호 강도 {score}): {keywords} 관련 이슈가 집중되고 있습니다."
                )
            else:
                content_parts.append(f"{i}. **{emoji} {name}** (신호 강도 {score})")
        content_parts.append("")
    else:
        content_parts.append(f"총 **{total_count}건**의 뉴스가 수집되었습니다. ({counts_str})\n")

    # Priority signal
    p0_count = len(priority_items.get("P0", []))
    p1_count = len(priority_items.get("P1", []))
    if p0_count or p1_count:
        signal_parts = []
        if p0_count:
            signal_parts.append(f"P0 긴급 {p0_count}건")
        if p1_count:
            signal_parts.append(f"P1 주요 {p1_count}건")
        content_parts.append(f"**핵심 신호**: {', '.join(signal_parts)}이 포착되었습니다.")
    content_parts.append("")

    content_parts.append("## 종합 대시보드\n")
    content_parts.extend(
        _build_snapshot_table(
            crypto_summary,
            stock_summary,
            worldmonitor_summary,
            regulatory_summary,
            social_summary,
            political_summary,
        )
    )
    content_parts.append("")

    if briefing_image:
        content_parts.append(f'![multi-asset-briefing]({{{{ "{briefing_image}" | relative_url }}}})\n')
    fallback_briefing = _render_generated_image(f"news-briefing-daily-{today}.png", "multi-asset-briefing")
    legacy_briefing = _render_generated_image(f"news-briefing-{today}.png", "multi-asset-briefing")
    if not briefing_image and fallback_briefing:
        content_parts.append(fallback_briefing + "\n")
    elif not briefing_image and legacy_briefing:
        content_parts.append(legacy_briefing + "\n")

    heatmap_img = _render_generated_image(f"market-heatmap-{today}.png", "market-heatmap")
    if heatmap_img:
        content_parts.append(heatmap_img + "\n")

    # Executive briefing: cross-category synthesis with data points
    content_parts.append("## 핵심 브리핑\n")

    # 1. Cross-cutting theme analysis
    cross_topics = _find_shared_topics_across_categories(all_summaries)
    if cross_topics:
        top_cross = cross_topics[:3]
        content_parts.append(f"오늘 **{len(cross_topics)}개 교차 테마**가 복수 카테고리에 걸쳐 감지되었습니다.\n")
        for topic_name, cat_count, cats in top_cross:
            cats_str = ", ".join(cats[:4])
            content_parts.append(f"> - **{topic_name}**: {cat_count}개 영역({cats_str})에서 동시 언급")
        content_parts.append("")

    # 2. Concentration & anomaly detection
    if all_news_items:
        concentration = summarizer.detect_concentration()
        if concentration:
            c_name, _c_key, c_ratio = concentration
            content_parts.append(
                f"> **집중도 경고**: 전체 뉴스의 **{c_ratio:.0%}**가 '{c_name}' 테마에 집중되어 있습니다. "
                f"단일 이벤트 발생 시 시장 변동성이 확대될 수 있으니 관련 포지션을 점검하세요.\n"
            )
        anomalies = summarizer.detect_anomalies()
        for _a_name, _a_key, _a_count, a_desc in anomalies:
            content_parts.append(f"> **이상 탐지**: {a_desc}\n")

    # 3. Sentiment snapshot
    sentiment = _analyze_sentiment(all_summaries)
    active_categories = sum(1 for s in all_summaries if s and s.get("count", 0) > 0)
    content_parts.append(
        f"**시장 심리**: {sentiment['tone']} "
        f"(긍정 {sentiment['positive']}건 vs 부정 {sentiment['negative']}건, "
        f"긍정 비율 {sentiment['ratio']}%) — "
        f"{active_categories}개 카테고리 {total_count}건 기준\n"
    )

    # Actionable insights based on sentiment
    if sentiment["pos_examples"] or sentiment["neg_examples"]:
        content_parts.append("")
        if sentiment["pos_examples"]:
            content_parts.append(f"  - 긍정 신호: {'; '.join(sentiment['pos_examples'][:2])}")
        if sentiment["neg_examples"]:
            content_parts.append(f"  - 주의 신호: {'; '.join(sentiment['neg_examples'][:2])}")
        content_parts.append("")

    # 4. Per-category one-liner with concrete data
    briefing_lines = []
    category_configs = [
        ("crypto", "암호화폐"),
        ("stock", "주식"),
        ("regulatory", "규제"),
        ("worldmonitor", "월드모니터"),
        ("social", "소셜"),
        ("political", "정치인 거래"),
    ]
    summary_lookup = {
        "crypto": crypto_summary,
        "stock": stock_summary,
        "regulatory": regulatory_summary,
        "worldmonitor": worldmonitor_summary,
        "social": social_summary,
        "political": political_summary,
    }
    for key, label in category_configs:
        s = summary_lookup.get(key)
        if not s or not s.get("count"):
            continue
        dp = _extract_category_data_points(s)
        line_parts = [f"**{label}** {dp['count']}건"]
        if dp["theme_names"]:
            line_parts.append(f"핵심 테마 {', '.join(dp['theme_names'][:3])}")
        if dp["figures"]:
            line_parts.append(f"주요 지표: {dp['figures'][0]}")
        elif dp["titles"]:
            line_parts.append(_clean_headline(dp["titles"][0]))
        # Add the top headline as a highlighted note for extra context
        if dp["titles"] and len(dp["titles"]) >= 1:
            top_title = smart_truncate(_clean_headline(dp["titles"][0]), 60)
            line_parts.append(f"주목: *{top_title}*")
        briefing_lines.append("> - " + " — ".join(line_parts))

    if briefing_lines:
        content_parts.extend(briefing_lines)
        content_parts.append("")

    content_parts.append("## 뉴스 내용 기반 핵심 요약\n")
    # Use sentiment already computed above (or compute if not yet)
    if "sentiment" not in dir():
        sentiment = _analyze_sentiment(all_summaries)

    if crypto_summary:
        crypto_dp = _extract_category_data_points(crypto_summary)
        crypto_themes = ", ".join(f"{name}({cnt})" for name, cnt in (crypto_summary.get("themes") or [])[:3])
        crypto_detail = ""
        if crypto_themes:
            crypto_detail = f"핵심 테마는 {crypto_themes}."
        if crypto_dp["figures"]:
            crypto_detail += f" 주요 수치: {crypto_dp['figures'][0]}."
        if crypto_dp["titles"]:
            crypto_detail += f" 대표 헤드라인: {_clean_headline(crypto_dp['titles'][0])}."
        if not crypto_detail:
            crypto_detail = "세부 데이터 확인 필요."
        content_parts.append(f"- **암호화폐:** {crypto_summary.get('count', 0)}건. {crypto_detail.strip()}")
    if stock_summary:
        stock_dp = _extract_category_data_points(stock_summary)
        stock_detail = ""
        if stock_summary.get("market_data"):
            stock_detail = _clean_bullet_text(stock_summary["market_data"][0]) + "."
        if stock_dp["figures"]:
            stock_detail += f" 주요 수치: {stock_dp['figures'][0]}."
        if stock_dp["titles"] and not stock_detail.strip():
            stock_detail = f"대표 헤드라인: {_clean_headline(stock_dp['titles'][0])}."
        content_parts.append(
            f"- **주식:** {stock_summary.get('count', 0)}건. {stock_detail.strip() if stock_detail.strip() else '시장 데이터 확인 필요.'}"
        )
    if regulatory_summary:
        reg_dp = _extract_category_data_points(regulatory_summary)
        reg_detail = ""
        if reg_dp["titles"]:
            reg_detail = f"주요 이슈: {_clean_headline(reg_dp['titles'][0])}."
        if reg_dp["figures"]:
            reg_detail += f" 관련 수치: {reg_dp['figures'][0]}."
        if not reg_detail:
            reg_detail = "정책 공시 및 감독 이슈 중심."
        content_parts.append(f"- **규제:** {regulatory_summary.get('count', 0)}건. {reg_detail.strip()}")
    if social_summary:
        social_dp = _extract_category_data_points(social_summary)
        social_detail = ""
        if social_dp["titles"]:
            social_detail = f"화제 키워드: {_clean_headline(social_dp['titles'][0])}."
        if social_dp["figures"]:
            social_detail += f" {social_dp['figures'][0]}."
        if not social_detail:
            social_detail = "소셜 채널 키워드 분석 기반."
        content_parts.append(f"- **소셜:** {social_summary.get('count', 0)}건. {social_detail.strip()}")
    if worldmonitor_summary:
        world_dp = _extract_category_data_points(worldmonitor_summary)
        world_detail = ""
        if world_dp["titles"]:
            world_detail = f"핵심 이슈: {_clean_headline(world_dp['titles'][0])}."
        if world_dp["figures"]:
            world_detail += f" {world_dp['figures'][0]}."
        if not world_detail:
            world_detail = "글로벌 이슈 모니터링 기반."
        content_parts.append(f"- **월드모니터:** {worldmonitor_summary.get('count', 0)}건. {world_detail.strip()}")
    if priority_items.get("P0") or priority_items.get("P1"):
        p0_titles = [
            _strip_markdown_link(get_display_title(x)) for x in priority_items.get("P0", [])[:2] if x.get("title")
        ]
        p0_hint = f" 긴급: {', '.join(p0_titles)}." if p0_titles else ""
        content_parts.append(
            f"- **우선순위:** P0 {len(priority_items.get('P0', []))}건, "
            f"P1 {len(priority_items.get('P1', []))}건.{p0_hint}"
        )
    content_parts.append("")

    if theme_payload:
        content_parts.append("## 테마 스냅샷\n")
        theme_rows = []
        for item in theme_payload:
            keywords = ", ".join(item.get("keywords", []))
            theme_rows.append(
                [
                    f"{item.get('emoji', '•')} {item.get('name', '')}",
                    item.get("count", 0),
                    keywords if keywords else "-",
                ]
            )
        content_parts.append(
            markdown_table(
                ["테마", "신호 강도", "대표 키워드"],
                theme_rows,
                aligns=["left", "right", "left"],
            )
        )
        content_parts.append("")

        # Dynamic risk/opportunity memo based on actual theme data
        content_parts.append("**리스크/기회 메모**")
        top_theme = theme_payload[0]
        top_name = top_theme.get("name", "")
        top_score = top_theme.get("count", 0)

        if top_score >= 30:
            content_parts.append(
                f"- **{top_name}** 테마에 신호가 집중(강도 {top_score})되어 "
                f"관련 자산의 단기 변동성 확대 가능성이 높습니다."
            )
        elif top_score >= 15:
            content_parts.append(
                f"- **{top_name}** 테마가 주도적(강도 {top_score})이며 후속 뉴스에 따라 방향성이 결정될 구간입니다."
            )
        else:
            content_parts.append(
                f"- 뚜렷한 지배 테마 없이 분산된 흐름(최대 강도 {top_score})으로 "
                f"개별 종목/이벤트 중심 대응이 유효합니다."
            )

        # Check policy/regulation overlap
        policy_theme = next(
            (t for t in theme_payload if "정책" in t.get("name", "") or "규제" in t.get("name", "")),
            None,
        )
        if policy_theme and policy_theme.get("count", 0) >= 5:
            content_parts.append(
                f"- 정책/규제 신호(강도 {policy_theme['count']})가 감지되어 이벤트 드리븐 포지션 점검이 필요합니다."
            )

        # Sentiment-driven observation
        if sentiment["ratio"] >= 65:
            content_parts.append(
                f"- 긍정 헤드라인 비율이 {sentiment['ratio']}%로 높아 "
                f"과열 가능성을 역발상 관점에서 점검할 필요가 있습니다."
            )
        elif sentiment["ratio"] <= 35:
            content_parts.append(
                f"- 부정 헤드라인 비율이 {100 - sentiment['ratio']}%로 높아 "
                f"공포 구간 매수 기회 여부를 점검할 수 있습니다."
            )
        content_parts.append("")

    # ═══════════════════════════════════════
    # 1. URGENT ALERTS (P0)
    # ═══════════════════════════════════════
    if priority_items.get("P0"):
        content_parts.append("## 긴급 알림\n")
        content_parts.append("> 즉시 확인이 필요한 긴급 뉴스입니다.\n")
        seen_p0 = set()
        for item in priority_items["P0"][:5]:
            orig_title = item.get("title", "")
            if _is_noise_title(orig_title):
                continue
            norm = re.sub(r"[^a-z가-힣0-9]", "", item.get("description", orig_title).lower())
            if norm in seen_p0:
                continue
            seen_p0.add(norm)
            display = get_display_title(item)
            link = item.get("link", "")
            desc = (item.get("description_ko") or item.get("description", "")).strip()
            # Build alert line: Korean title with link + description summary
            if link:
                title_part = f"[{display}]({link})"
            else:
                title_part = display
            content_parts.append(f"- **{title_part}**")
            # Add description summary if available and different from title
            if desc and desc != display and desc != orig_title and len(desc) > 15:
                desc_short = smart_truncate(desc, 120)
                content_parts.append(f"  > {desc_short}")
        content_parts.append("")

    # ═══════════════════════════════════════
    # 2. MARKET OVERVIEW
    # ═══════════════════════════════════════
    if market_summary:
        content_parts.append("## 시장 개요\n")
        if market_summary.get("highlights"):
            for h in market_summary["highlights"]:
                content_parts.append(h)
        elif market_summary.get("exec_summary"):
            for h in market_summary["exec_summary"]:
                content_parts.append(h)
        content_parts.append("")

    # ═══════════════════════════════════════
    # 3. INDICATOR DASHBOARD
    # ═══════════════════════════════════════
    indicator_parts = []
    indicator_rows: List[List[str]] = []

    # Macro indicators from market report
    if market_summary and market_summary.get("indicator_rows"):
        for row in market_summary["indicator_rows"]:
            parts = [p.strip() for p in row.split("|") if p.strip()]
            if len(parts) >= 3:
                indicator_rows.append(parts[:3])

    if indicator_rows:
        indicator_parts.append(markdown_table(["지표", "현재 값", "변동"], indicator_rows))

    # Yield spread
    if market_summary and market_summary.get("yield_section"):
        if indicator_parts:
            indicator_parts.append("")
        indicator_parts.append("**국채 수익률 스프레드:**")
        # Extract just the key info
        for line in market_summary["yield_section"].split("\n"):
            line = line.strip()
            if line.startswith("|") and "스프레드" in line or line.startswith(">"):
                indicator_parts.append(line)

    if indicator_parts:
        content_parts.append("## 지표 대시보드\n")
        content_parts.extend(indicator_parts)
        content_parts.append("")

    relation_rows = _relation_rows(summary_map)
    coverage_notes = _coverage_warnings(summary_map)

    if relation_rows or coverage_notes:
        content_parts.append("## 교차자산 연관성 체크\n")
        content_parts.append("> 뉴스, 주식, 코인, 정치/규제 이벤트를 연결해 당일 리스크/기회 신호를 점검합니다.\n")

        if relation_rows:
            corr_rows = []
            for left, right, score, note in relation_rows:
                corr_rows.append([f"{left} ↔ {right}", score, note])
            content_parts.append(
                markdown_table(
                    ["비교 구간", "연관 점수", "진단"],
                    corr_rows,
                    aligns=["left", "right", "left"],
                )
            )
            content_parts.append("")

            # System risk warning when 3+ pairs show high correlation
            high_relation_count = sum(1 for r in relation_rows if "높음" in r[3])
            if high_relation_count >= 3:
                content_parts.append(
                    "\n> **시스템 리스크 주의**: 3개 이상 자산 쌍에서 높은 연관성이 감지되었습니다. "
                    "단일 이벤트가 복수 시장에 동시 영향을 줄 수 있으니 포트폴리오 분산 상태를 점검하세요.\n"
                )

        if coverage_notes:
            content_parts.append("**데이터 커버리지 경고**")
            content_parts.extend(coverage_notes)
            content_parts.append("")

        # Dynamic operational checklist based on actual relation data
        content_parts.append("**운영 체크리스트**")
        high_pairs = [(left, right, sc, nt) for left, right, sc, nt in relation_rows if sc >= 25]
        mid_pairs = [(left, right, sc, nt) for left, right, sc, nt in relation_rows if 12 <= sc < 25]

        if high_pairs:
            pair_names = ", ".join(f"{left}↔{right}" for left, right, _, _ in high_pairs[:3])
            content_parts.append(
                f"- **높은 연관성 감지**: {pair_names} 구간에서 장중 변동성 확대 가능성이 높아 우선 모니터링 필요"
            )
        if mid_pairs:
            pair_names = ", ".join(f"{left}↔{right}" for left, right, _, _ in mid_pairs[:3])
            content_parts.append(f"- **중간 연관성**: {pair_names} 구간은 후속 이벤트에 따라 연관성 강화 가능")
        if not high_pairs and not mid_pairs:
            content_parts.append(
                "- 교차자산 연관성이 전반적으로 낮아 개별 자산/이벤트 중심의 독립적 대응이 적합합니다."
            )

        # Check specific cross patterns from actual data
        crypto_reg = next(
            (
                (left, right, sc, nt)
                for left, right, sc, nt in relation_rows
                if ("암호화폐" in left and "규제" in right) or ("규제" in left and "암호화폐" in right)
            ),
            None,
        )
        if crypto_reg and crypto_reg[2] >= 12:
            content_parts.append(
                f"- 암호화폐↔규제 연관 점수 {crypto_reg[2]}점: 규제 이벤트가 코인 시장에 직접 영향을 줄 수 있는 구간"
            )
        political_overlap = next(
            ((left, right, sc, nt) for left, right, sc, nt in relation_rows if "정치인" in left or "정치인" in right),
            None,
        )
        if political_overlap and political_overlap[2] >= 12:
            content_parts.append(
                f"- 정치인 거래 연관 점수 {political_overlap[2]}점: 정책 변화에 따른 인사이더 거래 패턴 주시"
            )
        content_parts.append("")

    # ═══════════════════════════════════════
    # 4. POLITICAL WATCH
    # ═══════════════════════════════════════
    if political_summary:
        content_parts.append("---\n")
        content_parts.append("## 정치인 워치\n")
        if political_summary.get("key_summary"):
            for h in political_summary["key_summary"][:5]:
                content_parts.append(h)
        if political_summary.get("highlights"):
            content_parts.append("")
            for h in political_summary["highlights"][:3]:
                content_parts.append(h)
        content_parts.append(f"\n[상세 보기]({political_summary.get('url', '#')})\n")

    # ═══════════════════════════════════════
    # 5. IMPORTANT NEWS (P1)
    # ═══════════════════════════════════════
    if priority_items.get("P1"):
        content_parts.append("---\n")
        content_parts.append("## 중요 뉴스\n")
        content_parts.append("> 규제, ETF, 실적 등 주요 뉴스입니다.\n")
        seen_p1 = set()
        for item in priority_items["P1"][:7]:
            title = item.get("title", "")
            if _is_noise_title(title):
                continue
            norm = re.sub(r"[^a-z가-힣0-9]", "", item.get("description", title).lower())
            if norm in seen_p1:
                continue
            seen_p1.add(norm)
            content_parts.append(f"- {title}")
        content_parts.append("")

    # ═══════════════════════════════════════
    # 6. CATEGORY SUMMARIES
    # ═══════════════════════════════════════
    content_parts.append("---\n")
    content_parts.append("## 카테고리별 요약\n")

    # Crypto section with data-driven analysis
    if crypto_summary:
        content_parts.append(f"### 암호화폐 뉴스 ({crypto_summary['count']}건)\n")
        crypto_dp = _extract_category_data_points(crypto_summary)
        if crypto_summary.get("themes"):
            themes_str = ", ".join(f"**{t[0]}**({t[1]}건)" for t in crypto_summary["themes"][:4])
            total_themed = sum(t[1] for t in crypto_summary["themes"])
            if total_themed and crypto_summary["count"]:
                coverage = round(total_themed / crypto_summary["count"] * 100)
                content_parts.append(f"주요 테마: {themes_str} (전체의 {coverage}% 커버)\n")
            else:
                content_parts.append(f"주요 테마: {themes_str}\n")
        # Data points first, then highlights
        if crypto_dp["figures"]:
            content_parts.append(f"**주요 수치**: {', '.join(crypto_dp['figures'][:3])}\n")
        if crypto_dp["titles"]:
            content_parts.append("**대표 헤드라인:**")
            for t in crypto_dp["titles"][:3]:
                content_parts.append(f"- {t}")
            content_parts.append("")
        elif crypto_summary.get("highlights"):
            for h in crypto_summary["highlights"][:3]:
                content_parts.append(h)
        content_parts.append(f"[상세 보기]({crypto_summary.get('url', '#')})\n")

    # Stock section with market data emphasis
    if stock_summary:
        content_parts.append(f"### 주식 시장 뉴스 ({stock_summary['count']}건)\n")
        stock_dp = _extract_category_data_points(stock_summary)
        seen_stock = set()
        if stock_summary.get("market_data"):
            content_parts.append("**시장 지표:**")
            for md in stock_summary["market_data"][:3]:
                cleaned = _clean_bullet_text(md)
                if cleaned and cleaned not in seen_stock:
                    content_parts.append(f"- {cleaned}")
                    seen_stock.add(cleaned)
            content_parts.append("")
        if stock_dp["figures"]:
            fig_str = ", ".join(f for f in stock_dp["figures"][:3] if f not in seen_stock)
            if fig_str:
                content_parts.append(f"**주요 수치**: {fig_str}\n")
        if stock_dp["titles"]:
            content_parts.append("**대표 헤드라인:**")
            for t in stock_dp["titles"][:3]:
                if t not in seen_stock:
                    content_parts.append(f"- {t}")
                    seen_stock.add(t)
            content_parts.append("")
        elif stock_summary.get("highlights"):
            for h in stock_summary["highlights"][:3]:
                cleaned = _clean_bullet_text(h)
                if cleaned and cleaned not in seen_stock:
                    content_parts.append(f"- {cleaned}")
                    seen_stock.add(cleaned)
        content_parts.append(f"[상세 보기]({stock_summary.get('url', '#')})\n")

    # Regulatory section with specific issue extraction
    if regulatory_summary:
        content_parts.append(f"### 규제 동향 ({regulatory_summary['count']}건)\n")
        reg_dp = _extract_category_data_points(regulatory_summary)
        if reg_dp["titles"]:
            content_parts.append("**주요 규제 이슈:**")
            for t in reg_dp["titles"][:3]:
                content_parts.append(f"- {t}")
            content_parts.append("")
        elif regulatory_summary.get("key_summary"):
            for h in regulatory_summary["key_summary"][:3]:
                content_parts.append(h)
        if reg_dp["figures"]:
            content_parts.append(f"**관련 수치**: {', '.join(reg_dp['figures'][:2])}\n")
        content_parts.append(f"[상세 보기]({regulatory_summary.get('url', '#')})\n")

    if worldmonitor_summary:
        content_parts.append(f"### 월드모니터 브리핑 ({worldmonitor_summary['count']}건)\n")
        world_dp = _extract_category_data_points(worldmonitor_summary)
        if world_dp["titles"]:
            content_parts.append("**주요 글로벌 이슈:**")
            for t in world_dp["titles"][:3]:
                content_parts.append(f"- {smart_truncate(t, 80)}")
            content_parts.append("")
        elif worldmonitor_summary.get("key_summary"):
            for h in worldmonitor_summary["key_summary"][:3]:
                content_parts.append(h)
        if worldmonitor_summary.get("issues"):
            world_rows = []
            for row in worldmonitor_summary["issues"][:3]:
                parts = [p.strip() for p in row.split("|") if p.strip()]
                if len(parts) >= 5:
                    world_rows.append([parts[1], parts[4]])
                elif len(parts) >= 3:
                    world_rows.append([parts[1], parts[2]])
            if world_rows:
                content_parts.append(markdown_table(["제목", "출처"], world_rows))
                content_parts.append("")
        if world_dp["figures"]:
            content_parts.append(f"**관련 수치**: {', '.join(world_dp['figures'][:2])}\n")
        content_parts.append(f"[상세 보기]({worldmonitor_summary.get('url', '#')})\n")

    # Security section with incident details
    if security_summary:
        content_parts.append(f"### 보안 리포트 ({security_summary['count']}건)\n")
        sec_dp = _extract_category_data_points(security_summary)
        if sec_dp["titles"]:
            content_parts.append("**주요 보안 이슈:**")
            for t in sec_dp["titles"][:3]:
                content_parts.append(f"- {t}")
            content_parts.append("")
        elif security_summary.get("key_summary"):
            for h in security_summary["key_summary"][:3]:
                content_parts.append(h)
        if security_summary.get("incidents"):
            incident_rows = []
            for row in security_summary["incidents"][:3]:
                parts = [p.strip() for p in row.split("|") if p.strip()]
                if len(parts) >= 3:
                    incident_rows.append(parts[:3])
            if incident_rows:
                content_parts.append(markdown_table(["프로젝트", "피해 규모", "공격 유형"], incident_rows))
                content_parts.append("")
        if sec_dp["figures"]:
            content_parts.append(f"**피해 수치**: {', '.join(sec_dp['figures'][:2])}\n")
        content_parts.append(f"[상세 보기]({security_summary.get('url', '#')})\n")

    # Social section with trend extraction
    if social_summary:
        content_parts.append(f"### 소셜 미디어 동향 ({social_summary['count']}건)\n")
        social_dp = _extract_category_data_points(social_summary)
        if social_dp["titles"]:
            content_parts.append("**화제 토픽:**")
            for t in social_dp["titles"][:3]:
                content_parts.append(f"- {t}")
            content_parts.append("")
        elif social_summary.get("highlights"):
            for h in social_summary["highlights"][:3]:
                content_parts.append(h)
        elif social_summary.get("key_summary"):
            for h in social_summary["key_summary"][:3]:
                content_parts.append(h)
        if social_dp["figures"]:
            content_parts.append(f"**관련 수치**: {', '.join(social_dp['figures'][:2])}\n")
        content_parts.append(f"[상세 보기]({social_summary.get('url', '#')})\n")

    # ═══════════════════════════════════════
    # 7. NOTABLE NEWS (P2)
    # ═══════════════════════════════════════
    if priority_items.get("P2"):
        content_parts.append("---\n")
        content_parts.append("## 주목할 소식\n")
        seen_p2 = set()
        for item in priority_items["P2"][:5]:
            title = item.get("title", "")
            if _is_noise_title(title):
                continue
            norm = re.sub(r"[^a-z가-힣0-9]", "", item.get("description", title).lower())
            if norm in seen_p2:
                continue
            seen_p2.add(norm)
            content_parts.append(f"- {title}")
        content_parts.append("")

    # ═══════════════════════════════════════
    # 8. REPORT LINKS
    # ═══════════════════════════════════════
    content_parts.append("---\n")
    content_parts.append("## 상세 리포트 링크\n")
    report_rows = []
    for name, count, url in post_links:
        count_str = f"{count}건" if isinstance(count, int) and count > 0 else "-"
        report_rows.append([name, count_str, f"[바로가기]({url})"])
    if report_rows:
        content_parts.append(
            markdown_table(
                ["카테고리", "건수", "상세 보기"],
                report_rows,
                aligns=["left", "center", "left"],
            )
        )

    content_parts.append("\n---\n")
    content_parts.append("*본 요약은 자동 수집된 뉴스 데이터를 기반으로 작성되었으며, 투자 조언이 아닙니다.*")

    content = "\n".join(content_parts)

    # Create post with pin: true
    title = f"일일 뉴스 종합 요약 - {today}"
    slug = "daily-news-summary"
    filename = f"{today}-{slug}.md"
    filepath = os.path.join(POSTS_DIR, filename)

    tags = [
        "일일요약",
        "암호화폐",
        "주식",
        "규제",
        "소셜미디어",
        "보안",
        "정치인거래",
        "월드모니터",
    ]
    escaped_title = title.replace('"', '\\"')

    frontmatter_image = _resolve_frontmatter_image(today, briefing_image)
    image_line = f'\nimage: "{frontmatter_image}"' if frontmatter_image else ""

    safe_tags = [f'"{t}"' for t in tags]
    safe_desc = f"{counts_str}의 뉴스를 종합 분석한 일일 요약입니다.".replace('"', "'")
    frontmatter = f"""---
layout: post
title: "{escaped_title}"
date: {today} 12:00:00 +0900
categories: [market-analysis]
tags: [{", ".join(safe_tags)}]
source: "consolidated"
lang: "ko"{image_line}
pin: true
description: "{safe_desc}"
excerpt: "{counts_str}의 뉴스를 종합 분석한 일일 요약"
---"""

    post_content = frontmatter + "\n\n" + content.strip()

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(post_content)

    logger.info("Created daily summary: %s (total %d news items)", filepath, total_count)
    logger.info("=== Daily summary generation complete ===")


if __name__ == "__main__":
    main()
