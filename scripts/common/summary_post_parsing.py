"""generate_daily_summary 의 게시물 파싱/추출 leaf 유틸리티.

`generate_daily_summary.py` 에서 추출(2026-06-25). 외부 부수효과가 없는 순수
마크다운/프론트매터 파싱 함수 모음이며, 호출 측·테스트 호환을 위해
`generate_daily_summary` 모듈이 이 심볼들을 재-import 한다.
"""

import logging
import re
from typing import Any, Dict, List

from .markdown_utils import sanitize_summary_bullet

logger = logging.getLogger(__name__)

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_HTML_BLOCK_RE = re.compile(r"<div\b[^>]*>.*?</div>", re.DOTALL)


def strip_html_tags(text: str) -> str:
    """Remove HTML tags from text, preserving readable content."""
    # Remove entire HTML block elements (div, details, summary, style, script) first
    text = re.sub(r"<details[^>]*>.*?</details>", "", text, flags=re.DOTALL)
    text = re.sub(r"<summary[^>]*>.*?</summary>", "", text, flags=re.DOTALL)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
    text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL)
    text = _HTML_BLOCK_RE.sub("", text)
    # Remove remaining inline tags
    text = _HTML_TAG_RE.sub("", text)
    # Collapse multiple blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _is_similar_title(title1: str, title2: str, threshold: float = 0.6) -> bool:
    """두 제목의 단어 기반 유사도를 체크합니다."""
    words1 = set(title1.lower().split())
    words2 = set(title2.lower().split())
    if not words1 or not words2:
        return False
    overlap = len(words1 & words2)
    return overlap / min(len(words1), len(words2)) > threshold


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
            cleaned = sanitize_summary_bullet(line[2:].strip())
            if not cleaned:
                continue
            bullets.append(f"- {cleaned}")
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
        r"이벤트\s*(\d+)건",
        r"(\d+)건을 수집",
    ]
    for pattern in patterns:
        match = re.search(pattern, content)
        if match:
            return int(match.group(1))

    # DeFi TVL: sum protocol + chain counts (e.g. "20개 프로토콜", "15개 체인")
    proto_match = re.search(r"(\d+)개 프로토콜", content)
    chain_match = re.search(r"(\d+)개 체인", content)
    if proto_match or chain_match:
        total = 0
        if proto_match:
            total += int(proto_match.group(1))
        if chain_match:
            total += int(chain_match.group(1))
        return total

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
