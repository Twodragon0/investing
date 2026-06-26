"""generate_daily_summary 의 카테고리별 게시물 요약(summarize_*) 함수 모음.

`generate_daily_summary.py` 에서 추출(2026-06-26). 각 함수는 수집기 카테고리별
게시물(dict)을 입력받아 일일 요약 빌드에 필요한 구조화 dict 를 돌려주는 순수
변환 함수다. 파싱 leaf 유틸은 [[summary_post_parsing]] 에 의존하며, 호출 측·테스트
호환을 위해 `generate_daily_summary` 모듈이 이 심볼들을 재-import 한다.
"""

import re
from typing import Any, Dict, List

from .summary_post_parsing import (
    _extract_highlights,
    count_news_items,
    extract_bullet_points,
    extract_section,
    extract_table_rows,
)


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

    # Strip "이슈 분포" heading and its content (up to next heading or end)
    cleaned = re.sub(r"^##\s+이슈 분포.*?(?=^##|\Z)", "", content, flags=re.MULTILINE | re.DOTALL)
    # Strip theme-distribution HTML blocks
    cleaned = re.sub(
        r'<div[^>]*class=["\']?theme-distribution["\']?[^>]*>.*?</div>\s*(?:</div>\s*)*', "", cleaned, flags=re.DOTALL
    )
    # Strip stat-grid HTML blocks
    cleaned = re.sub(
        r'<div[^>]*class=["\']?stat-grid["\']?[^>]*>.*?</div>\s*(?:</div>\s*)*', "", cleaned, flags=re.DOTALL
    )

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
