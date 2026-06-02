#!/usr/bin/env python3
"""Batch improve existing posts quality.

Addresses:
1. Duplicate content between intro, "전체 뉴스 요약", "오늘의 인사이트"
2. Generic/fixed insight phrases replaced with theme-specific analysis
3. Duplicate "주요 기사" lines in insight section
4. SEO description cleanup (HTML tags, length)
5. Empty data rows/sections cleanup
6. Monitoring keywords: add Korean translations
"""

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common.markdown_utils import sanitize_summary_bullet  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

POSTS_DIR = Path(__file__).resolve().parent.parent / "_posts"


def _strip_wrapping_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1].strip()
    return value


def _parse_list_literal(value: str) -> list[str]:
    value = value.strip()
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [_strip_wrapping_quotes(part.strip()) for part in inner.split(",") if part.strip()]
    return [_strip_wrapping_quotes(value)] if value else []


# Theme combination -> contextual insight mapping (at least 15 combos)
THEME_INSIGHTS: dict[tuple[str, str], str] = {
    ("비트코인", "가격/시장"): (
        "비트코인 가격 변동이 시장 전반에 영향을 미치고 있으며, 단기 방향성에 주목할 필요가 있습니다."
    ),
    ("비트코인", "거래소"): (
        "비트코인 관련 거래소 이슈가 부각되고 있어, 거래소 정책 변화와 수급 동향을 함께 살펴야 합니다."
    ),
    ("비트코인", "규제/정책"): (
        "비트코인을 둘러싼 규제 논의가 활발해지고 있어, 각국 정책 방향이 시장에 미칠 영향을 주시해야 합니다."
    ),
    ("비트코인", "이더리움"): (
        "비트코인과 이더리움이 동시에 주목받고 있어, 주요 코인 간 자금 흐름과 도미넌스 변화를 확인할 필요가 있습니다."
    ),
    ("비트코인", "정치/정책"): (
        "정치적 이슈가 비트코인 시장 심리에 영향을 주고 있어, 정책 발표와 관련 인사들의 발언에 주의가 필요합니다."
    ),
    ("비트코인", "AI/기술"): (
        "AI/기술 섹터 동향이 비트코인 시장 심리와 맞물리고 있어, 기술주 실적과 크립토 시장의 연관성을 주시해야 합니다."
    ),
    ("비트코인", "매크로/금리"): (
        "거시 경제 지표가 비트코인 가격에 직접적 영향을 미치고 있어, "
        "금리 결정과 인플레이션 데이터를 함께 모니터링해야 합니다."
    ),
    ("규제/정책", "거래소"): (
        "규제 환경 변화가 거래소 운영에 직접적 영향을 미칠 수 있어 관련 동향 모니터링이 중요합니다."
    ),
    ("AI/기술", "가격/시장"): (
        "AI/반도체 섹터 동향이 시장 심리에 큰 영향을 주고 있어, 기술주 실적과 연계한 흐름을 주시해야 합니다."
    ),
    ("매크로/금리", "정치/정책"): ("거시 경제 지표와 정책 변화가 시장의 핵심 변수로 작용하고 있습니다."),
    ("매크로/금리", "가격/시장"): (
        "금리와 인플레이션 데이터가 시장 가격에 직접적으로 반영되고 있어, 매크로 지표 발표 일정에 주목해야 합니다."
    ),
    ("가격/시장", "거래소"): (
        "시장 가격 변동과 거래소 동향이 밀접하게 연결되어 있어, 거래량 변화와 거래소 공지사항을 함께 확인해야 합니다."
    ),
    ("가격/시장", "정치/정책"): (
        "정치적 불확실성이 시장 가격에 변동성을 높이고 있어, 정책 관련 뉴스 흐름을 면밀히 추적해야 합니다."
    ),
    ("이더리움", "가격/시장"): (
        "이더리움 가격 움직임이 알트코인 시장 전반에 신호를 주고 있어, "
        "ETH 생태계 업데이트와 가격 추이를 함께 살펴야 합니다."
    ),
    ("이더리움", "규제/정책"): (
        "이더리움 관련 규제 이슈가 부각되고 있어, 스테이킹 규제와 ETF 승인 논의에 주목해야 합니다."
    ),
    ("규제/정책", "정치/정책"): (
        "금융 규제와 정치적 의제가 동시에 움직이고 있어, 입법 동향과 규제 기관 발표를 병행 모니터링해야 합니다."
    ),
    ("AI/기술", "정치/정책"): (
        "AI/기술 정책과 정치적 논의가 시장에 새로운 변수를 만들고 있어, 관련 법안과 정부 지원 정책에 주목해야 합니다."
    ),
    ("AI/기술", "매크로/금리"): (
        "AI/기술 투자 심리가 금리 환경에 민감하게 반응하고 있어, 기술 성장주와 금리 방향성의 관계를 주시해야 합니다."
    ),
}

# Fallback insight when no combo matches
FALLBACK_INSIGHT = (
    "오늘 부각된 테마들의 교차점에서 시장 방향성에 대한 "
    "단서를 찾을 수 있으므로, 관련 뉴스 흐름을 종합적으로 점검할 필요가 있습니다."
)

# Keyword Korean translations
KEYWORD_KO: dict[str, str] = {
    "bitcoin": "비트코인",
    "ethereum": "이더리움",
    "ai": "인공지능",
    "crypto": "암호화폐",
    "altcoin": "알트코인",
    "altcoins": "알트코인",
    "blockchain": "블록체인",
    "regulation": "규제",
    "stablecoin": "스테이블코인",
    "defi": "디파이",
    "nft": "대체불가토큰",
    "exchange": "거래소",
    "sec": "미국증권거래위원회",
    "fed": "연방준비제도",
    "inflation": "인플레이션",
    "interest": "금리",
    "tariff": "관세",
    "tariffs": "관세",
    "mining": "채굴",
    "etf": "상장지수펀드",
    "token": "토큰",
    "whale": "고래",
    "solana": "솔라나",
    "xrp": "리플",
    "trump": "트럼프",
    "nvidia": "엔비디아",
    "gold": "금",
    "oil": "원유",
    "dollar": "달러",
    "stock": "주식",
    "stocks": "주식",
    "market": "시장",
    "bond": "채권",
    "bonds": "채권",
    "binance": "바이낸스",
    "coinbase": "코인베이스",
    "staking": "스테이킹",
    "layer": "레이어",
    "l2": "레이어2",
    "halving": "반감기",
    "wallet": "지갑",
}

# Generic phrases to detect and replace in insight section
GENERIC_INSIGHT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"두 테마가 동시에 부각되고 있어 시장의 방향성을 가늠하는 핵심 신호로 볼 수 있습니다[.]?"),
    re.compile(r"두 테마의 동시 부각은 시장의 방향성을 가늠하는 데 중요한 신호가 될 수 있습니다[.]?"),
]


# ---------------------------------------------------------------------------
# Front matter parsing (no external libs)
# ---------------------------------------------------------------------------


def parse_post(content: str) -> tuple[dict[str, str], str]:
    """Parse front matter and body from a post file.

    Returns (front_matter_dict, body_string).
    Front matter values are kept as raw strings.
    """
    if not content.startswith("---"):
        return {}, content

    end = content.index("---", 3)
    fm_raw = content[3:end].strip()
    body = content[end + 3 :].lstrip("\n")

    fm: dict[str, str] = {}
    for line in fm_raw.split("\n"):
        if ":" in line:
            key, _, val = line.partition(":")
            fm[key.strip()] = val.strip()
    return fm, body


def serialize_front_matter(fm: dict[str, str]) -> str:
    """Serialize front matter dict back to YAML-like string."""
    lines = ["---"]
    for key, val in fm.items():
        lines.append(f"{key}: {val}")
    lines.append("---")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Improvement functions
# ---------------------------------------------------------------------------


def clean_description(fm: dict[str, str]) -> bool:
    """Clean description: remove HTML, markdown blockquote, trim to 160 chars."""
    desc = fm.get("description", "")
    if not desc:
        return False

    original = desc
    # Strip surrounding quotes
    if (desc.startswith('"') and desc.endswith('"')) or (desc.startswith("'") and desc.endswith("'")):
        inner = desc[1:-1]
    else:
        inner = desc

    # Remove HTML tags
    inner = re.sub(r"<[^>]+>", "", inner)
    # Remove leading > (blockquote)
    inner = re.sub(r"^>\s*", "", inner)
    # Remove markdown bold
    inner = re.sub(r"\*\*([^*]+)\*\*", r"\1", inner)
    # Remove trailing raw tag strings (e.g., "주요 키워드: crypto, news, daily-digest.")
    inner = re.sub(r"\s*주요 키워드:[\s\w,.-]+\.?\s*$", "", inner)
    # Collapse whitespace
    inner = re.sub(r"\s+", " ", inner).strip()

    # Truncate to 160 chars at a word boundary
    if len(inner) > 160:
        truncated = inner[:157]
        last_space = truncated.rfind(" ")
        if last_space > 100:
            truncated = truncated[:last_space]
        inner = truncated.rstrip(".,;:") + "..."

    new_desc = f'"{inner}"'
    if new_desc != original:
        fm["description"] = new_desc
        return True
    return False


def rebuild_low_quality_metadata(fm: dict[str, str], body: str) -> dict[str, int]:
    try:
        from common.markdown_utils import smart_truncate
        from common.post_generator import _build_fallback_description, _clean_description, _extract_description
    except ImportError:
        return {}

    title = _strip_wrapping_quotes(fm.get("title", ""))
    categories = _parse_list_literal(fm.get("categories", ""))
    tags = _parse_list_literal(fm.get("tags", ""))
    category = categories[0] if categories else "market-analysis"

    def _looks_low_quality(text: str) -> bool:
        cleaned = _strip_wrapping_quotes(text)
        if not cleaned or len(cleaned) < 55:
            return True
        if any(token in cleaned for token in ("http://", "https://", "](", "<div", "<span")):
            return True
        # Raw tag strings leaking into description
        if "주요 키워드:" in cleaned:
            return True
        ascii_letters = len(re.findall(r"[A-Za-z]", cleaned))
        hangul_letters = len(re.findall(r"[가-힣]", cleaned))
        if ascii_letters >= 40 and hangul_letters < 15:
            return True
        if cleaned.startswith("긴급:") and ascii_letters > hangul_letters:
            return True
        if re.search(r"[—-]\s*[A-Za-z]{1,3}[.]?$", cleaned):
            return True
        return False

    stats: dict[str, int] = {}
    if _looks_low_quality(fm.get("description", "")):
        rebuilt_desc = _clean_description(_build_fallback_description(title, category, tags))
        fm["description"] = f'"{rebuilt_desc.replace(chr(34), chr(39))}"'
        stats["description_rebuilt"] = 1

    if _looks_low_quality(fm.get("excerpt", "")):
        excerpt_source = _extract_description(body) or _strip_wrapping_quotes(fm.get("description", ""))
        if not excerpt_source:
            excerpt_source = _build_fallback_description(title, category, tags)
        rebuilt_excerpt = smart_truncate(_clean_description(excerpt_source), 100).replace('"', "'")
        fm["excerpt"] = f'"{rebuilt_excerpt}"'
        stats["excerpt_rebuilt"] = 1

    return stats


def fix_markdown_link_artifacts(body: str) -> tuple[str, bool]:
    original = body
    body = re.sub(
        r"(\*\*\d+\.\s+)\[([^\]\n]+)\]\s([^\n\]]+)\]\(([^)]+)\)\*\*",
        lambda m: f"{m.group(1)}[{m.group(2)} {m.group(3)}]({m.group(4)})**",
        body,
    )
    body = re.sub(
        r"(^\s*[-*]\s+)\[([^\]\n]+)\]\s([^\n\]]+)\]\(([^)]+)\)",
        lambda m: f"{m.group(1)}[{m.group(2)} {m.group(3)}]({m.group(4)})",
        body,
        flags=re.MULTILINE,
    )
    body = body.replace(r"\]", "]")
    body = re.sub(r"(\[[^\]\n]{1,120}\])(?=[가-힣A-Za-z\"])", r"\1 ", body)
    body = re.sub(r"<li><em>\.외\s+(\d+)건</em></li>", r"<li><em>외 \1건</em></li>", body)
    body = re.sub(r">\.외\s+(\d+)건<", r">외 \1건<", body)
    return body, body != original


def sync_summary_total_count(body: str) -> tuple[str, bool]:
    original = body
    stat_match = re.search(
        r'<div class="stat-value">(\d+)</div><div class="stat-label">수집 건수</div>',
        body,
    )
    total_count = stat_match.group(1) if stat_match else None
    if not total_count:
        intro_match = re.search(r"총\s+(\d+)건(?:의 뉴스)?가?\s+(?:수집|분석)", body)
        total_count = intro_match.group(1) if intro_match else None
    if total_count:
        body = re.sub(r"- 총 \*\*\d+건\*\* 수집", f"- 총 **{total_count}건** 수집", body)
    return body, body != original


def remove_intro_duplication_in_summary(body: str) -> tuple[str, bool]:
    """Remove lines in '전체 뉴스 요약' that duplicate the intro paragraph."""
    # Extract intro: first non-empty paragraph BEFORE any ## heading
    first_heading = re.search(r"^## ", body, re.MULTILINE)
    intro_region = body[: first_heading.start()] if first_heading else ""

    intro_text = ""
    for line in intro_region.split("\n"):
        stripped = line.strip()
        if stripped and not stripped.startswith("<") and not stripped.startswith("---"):
            # Remove markdown bold for comparison
            intro_text = re.sub(r"\*\*([^*]+)\*\*", r"\1", stripped)
            break

    if not intro_text or len(intro_text) < 20:
        return body, False

    # Find the summary section
    summary_pattern = re.compile(r"^## 전체 뉴스 요약\s*$", re.MULTILINE)
    match = summary_pattern.search(body)
    if not match:
        return body, False

    # Find the end of the summary section (next ## heading or end)
    section_start = match.end()
    next_heading = re.search(r"^## ", body[section_start:], re.MULTILINE)
    if next_heading:
        section_end = section_start + next_heading.start()
    else:
        section_end = len(body)

    section = body[section_start:section_end]
    new_lines = []
    changed = False

    # Normalize intro for fuzzy matching
    intro_norm = re.sub(r"[*\s]+", " ", intro_text).strip().lower()

    for line in section.split("\n"):
        line_stripped = line.strip()
        if line_stripped.startswith("- ") or line_stripped.startswith("* "):
            bullet_content = line_stripped[2:].strip()
        else:
            bullet_content = line_stripped

        # Normalize for comparison
        bullet_norm = re.sub(r"[*\s]+", " ", bullet_content).strip().lower()

        # Check if this line is substantially similar to intro
        if bullet_norm and intro_norm and len(bullet_norm) > 20:
            # Check if intro is contained in bullet or vice versa
            if bullet_norm in intro_norm or intro_norm in bullet_norm:
                changed = True
                continue
            # Check overlap ratio
            intro_words = set(intro_norm.split())
            bullet_words = set(bullet_norm.split())
            if intro_words and bullet_words:
                overlap = len(intro_words & bullet_words) / max(len(intro_words), len(bullet_words))
                if overlap > 0.7:
                    changed = True
                    continue

        new_lines.append(line)

    if changed:
        new_section = "\n".join(new_lines)
        body = body[:section_start] + new_section + body[section_end:]

    return body, changed


def remove_summary_article_duplicates(body: str) -> tuple[str, bool]:
    """Remove summary list items that duplicate numbered article titles below.

    Detects patterns like:
      - 1. Title text here. - Source Title text here.
    where the same title appears again in a numbered entry in a later section.
    Also removes list items with "- N." prefix that repeat themselves internally.
    """
    original = body
    lines = body.split("\n")
    new_lines = []
    # Collect all numbered article titles (e.g. "**1. [Title..." or "**1. Title...")
    article_titles = set()
    for line in lines:
        m = re.match(r"\*\*\d+\.\s*(?:\[)?(.{15,80}?)(?:\]|\*)", line)
        if m:
            article_titles.add(m.group(1).strip()[:50])

    for line in lines:
        # Check for "- 1. Title - Source Title" pattern with internal duplication
        m = re.match(r"^- \d+\.\s+(.+)$", line)
        if m:
            content = m.group(1)
            # Check if first half repeats in second half (internal dup)
            half = len(content) // 2
            if half > 20 and content[:half].strip().rstrip(".") in content[half:]:
                continue
            # Check if this title already appears as a numbered article
            clean = re.sub(r"\s*-\s*\S+\s*$", "", content).strip()[:50]
            if clean and any(clean in t or t in clean for t in article_titles):
                continue
        new_lines.append(line)

    result = "\n".join(new_lines)
    return result, result != original


def remove_duplicate_articles_in_insight(body: str) -> tuple[str, bool]:
    """Remove duplicate '주요 기사' lines in '오늘의 인사이트' section."""
    insight_pattern = re.compile(r"^## 오늘의 인사이트\s*$", re.MULTILINE)
    match = insight_pattern.search(body)
    if not match:
        return body, False

    section_start = match.end()
    next_heading = re.search(r"^## ", body[section_start:], re.MULTILINE)
    if next_heading:
        section_end = section_start + next_heading.start()
    else:
        # Look for --- separator or end of file
        separator = re.search(r"^---\s*$", body[section_start:], re.MULTILINE)
        if separator:
            section_end = section_start + separator.start()
        else:
            section_end = len(body)

    section = body[section_start:section_end]
    seen_articles: set[str] = set()
    new_lines: list[str] = []
    changed = False

    for line in section.split("\n"):
        # Detect "주요 기사" lines
        if "주요 기사:" in line or "주요 기사*:" in line:
            # Extract article title for dedup
            article_match = re.search(r"\*([^*]+)\*", line)
            if article_match:
                title = article_match.group(1).strip()
                if title in seen_articles:
                    changed = True
                    continue
                seen_articles.add(title)
        new_lines.append(line)

    if changed:
        new_section = "\n".join(new_lines)
        body = body[:section_start] + new_section + body[section_end:]

    return body, changed


def _extract_themes_from_insight(line: str) -> tuple[str, str]:
    """Extract two theme names from the insight opening line."""
    # Pattern: "오늘 가장 주목할 테마는 **비트코인**와 **가격/시장**입니다"
    # or with emoji: "**🟠 비트코인**(52건)과 **📈 가격/시장**(26건)"
    theme_matches = re.findall(
        r"\*\*(?:[^\*]*?)(비트코인|가격/시장|거래소|규제/정책|이더리움|"
        r"정치/정책|AI/기술|매크로/금리|DeFi|NFT|스테이블코인|알트코인)\*\*",
        line,
    )
    if len(theme_matches) >= 2:
        return theme_matches[0], theme_matches[1]
    return "", ""


def replace_generic_insight(body: str) -> tuple[str, bool]:
    """Replace generic insight phrases with theme-specific analysis."""
    changed = False

    for pattern in GENERIC_INSIGHT_PATTERNS:
        match = pattern.search(body)
        if not match:
            continue

        # Find the context line to extract themes
        match_start = match.start()
        # Look backward for the line containing theme info
        preceding = body[:match_start]
        preceding_lines = preceding.split("\n")

        theme1, theme2 = "", ""
        # Check the same line and previous lines for theme info
        for check_line in reversed(preceding_lines[-3:]):
            theme1, theme2 = _extract_themes_from_insight(check_line)
            if theme1 and theme2:
                break

        # Also check the matched line itself
        if not (theme1 and theme2):
            line_start = body.rfind("\n", 0, match_start) + 1
            line_end = body.find("\n", match.end())
            if line_end == -1:
                line_end = len(body)
            full_line = body[line_start:line_end]
            theme1, theme2 = _extract_themes_from_insight(full_line)

        if theme1 and theme2:
            # Try both orderings
            replacement = THEME_INSIGHTS.get(
                (theme1, theme2),
                THEME_INSIGHTS.get((theme2, theme1), FALLBACK_INSIGHT),
            )
        else:
            replacement = FALLBACK_INSIGHT

        body = body[: match.start()] + replacement + body[match.end() :]
        changed = True
        break  # Only one pattern per post expected

    return body, changed


def add_korean_to_keywords(body: str) -> tuple[str, bool]:
    """Add Korean translations to monitoring keywords.

    Transform: **bitcoin**(37회) -> **bitcoin(비트코인)**(37회)
    Transform: **bitcoin** -> **bitcoin(비트코인)**
    """
    changed = False

    def _replace_keyword(m: re.Match[str]) -> str:
        nonlocal changed
        keyword = m.group(1)
        rest = m.group(2) or ""  # e.g., "(37회)" or empty

        # Skip if already has Korean in parens
        if re.search(r"\([가-힣]+\)", keyword):
            return m.group(0)

        ko = KEYWORD_KO.get(keyword.lower())
        if ko:
            changed = True
            return f"**{keyword}({ko})**{rest}"
        return m.group(0)

    # Pattern: **keyword**(N회) or **keyword**
    body = re.sub(
        r"\*\*([a-zA-Z0-9/]+)\*\*(\(\d+회\))?",
        _replace_keyword,
        body,
    )
    return body, changed


def clean_keyword_none_artifacts(body: str) -> tuple[str, bool]:
    new_body = body
    new_body = re.sub(r"(\*\*[^*]+\*\*)None\(", r"\1(", new_body)
    new_body = re.sub(r"(\*\*[^*]+\*\*)None\s+\(", r"\1 (", new_body)
    new_body = re.sub(r"(\*\*[^*]+\*\*)None(?=[가-힣])", r"\1", new_body)
    new_body = re.sub(r"(\*\*[^*]+\*\*)None(?=\s|[.,:;!?])", r"\1", new_body)
    return new_body, new_body != body


def clean_empty_data_sections(body: str) -> tuple[str, bool]:
    """Remove lines with 'data unavailable' messages and clean up empty sections."""
    changed = False

    empty_patterns = [
        r"^>?\s*글로벌 암호화폐 시장 데이터를 일시적으로 가져올 수 없습니다\.?\s*$",
        r"^>?\s*코인 데이터를 일시적으로 가져올 수 없습니다\.?\s*$",
        r"^>?\s*\*?트렌딩 데이터를 가져올 수 없습니다\.?\*?\s*$",
        r"^>?\s*\*?데이터를 가져올 수 없습니다\.?\*?\s*$",
        r"^>?\s*매크로 경제 지표를 일시적으로 가져올 수 없습니다.*$",
        r"^>?\s*\*?데이터 없음\*?\s*$",
        r"^-?\s*\*?Alpha Vantage.*데이터를 가져올 수 없습니다.*\*?\s*$",
        r"^>?\s*\*?고래 거래 데이터를 가져올 수 없습니다\.?\*?\s*$",
        r"^>?\s*\*?Alpha Vantage API를 통한.*데이터를 가져올 수 없습니다.*\*?\s*$",
    ]

    for pat_str in empty_patterns:
        pat = re.compile(pat_str, re.MULTILINE)
        if pat.search(body):
            body = pat.sub("", body)
            changed = True

    # Remove table rows containing "데이터 없음"
    table_row_pat = re.compile(r"^\|[^|]*\|[^|]*\|\s*데이터 없음\s*\|\s*$", re.MULTILINE)
    if table_row_pat.search(body):
        body = table_row_pat.sub("", body)
        changed = True

    return body, changed


def collapse_blank_lines(body: str) -> tuple[str, bool]:
    """Reduce 3+ consecutive blank lines to 2."""
    new_body = re.sub(r"\n{4,}", "\n\n\n", body)
    return new_body, new_body != body


def remove_duplicate_articles_in_themes(body: str) -> tuple[str, bool]:
    """Remove duplicate articles across theme sections.

    When the same article (by URL) appears as #1 in multiple theme sections,
    the duplicates are flagged. We don't remove the entire entry because
    each theme section should list its articles, but we remove exact
    duplicate italic summary lines above numbered entries.
    """
    changed = False

    # Find theme sections: ### emoji theme (Nk)
    theme_pattern = re.compile(r"^### .+? \(\d+건\)\s*$", re.MULTILINE)
    matches = list(theme_pattern.finditer(body))

    if len(matches) < 2:
        return body, changed

    # For each theme section, find the italic summary line (standalone *text*)
    # and check if it duplicates a previous one
    seen_summaries: set[str] = set()
    replacements: list[tuple[int, int, str]] = []

    for i, m in enumerate(matches):
        section_start = m.end()
        if i + 1 < len(matches):
            section_end = matches[i + 1].start()
        else:
            # Find next ## heading or ---
            next_h2 = re.search(r"^## ", body[section_start:], re.MULTILINE)
            next_sep = re.search(r"^---\s*$", body[section_start:], re.MULTILINE)
            ends = []
            if next_h2:
                ends.append(section_start + next_h2.start())
            if next_sep:
                ends.append(section_start + next_sep.start())
            section_end = min(ends) if ends else len(body)

        section = body[section_start:section_end]

        # Find standalone italic line: starts with \n*text*\n
        italic_match = re.search(r"\n(\*[^*\n]+\*)\s*\n", section)
        if italic_match:
            summary_text = italic_match.group(1).strip()
            if summary_text in seen_summaries:
                # Remove this duplicate italic line
                abs_start = section_start + italic_match.start()
                abs_end = section_start + italic_match.end()
                replacements.append((abs_start, abs_end, "\n"))
                changed = True
            else:
                seen_summaries.add(summary_text)

    # Apply replacements in reverse order
    for start, end, replacement in reversed(replacements):
        body = body[:start] + replacement + body[end:]

    return body, changed


def fix_translation_artifacts(body: str) -> tuple[str, bool]:
    """Fix known machine translation artifacts in post body.

    Applies _MISTRANSLATION_FIXES from post_generator, particle corrections,
    name fixes, and awkward phrasing cleanup.
    """
    original = body

    # Apply centralized mistranslation dictionary first
    try:
        from common.post_generator import _MISTRANSLATION_FIXES

        for wrong, correct in _MISTRANSLATION_FIXES.items():
            body = body.replace(wrong, correct)
    except ImportError:
        pass

    fixes = [
        # Particle corrections (names without 받침)
        ("트럼프은 ", "트럼프는 "),
        ("트럼프을 ", "트럼프를 "),
        ("트럼프이 ", "트럼프가 "),
        ("테슬라은 ", "테슬라는 "),
        ("테슬라이 ", "테슬라가 "),
        ("엔비디아은 ", "엔비디아는 "),
        ("엔비디아이 ", "엔비디아가 "),
        ("메타은 ", "메타는 "),
        ("메타이 ", "메타가 "),
        ("오바마은 ", "오바마는 "),
        ("오바마이 ", "오바마가 "),
        # Name mistranslations
        ("시과의 만남", "시진핑과의 만남"),
        ("시과의", "시진핑과의"),
        ("시과 ", "시진핑과 "),
    ]
    for wrong, correct in fixes:
        body = body.replace(wrong, correct)

    # Regex-based fixes
    body = re.sub(r"무엇을 말했습니까\??", "어떤 입장을 밝혔나?", body)
    body = re.sub(r"말했습니까\?", "밝혔나?", body)
    # Inline picture tag separation
    body = re.sub(r"([^\n>])<picture>", r"\1\n\n<picture>", body)
    # Double text bug
    body = re.sub(r"시장 영향 가능성이 있는성이 있는", "시장 영향 가능성이 있는", body)

    return body, body != original


# ---------------------------------------------------------------------------
# Main processing
# ---------------------------------------------------------------------------


def sanitize_summary_bullets(body: str) -> tuple[str, bool]:
    """Clean plain-text summary bullet lines via ``sanitize_summary_bullet``.

    Drops non-prose stat dumps / meta-commentary bullets and collapses
    duplicated text. Conservative: bullets containing a markdown link or
    table syntax are left untouched so source links are never corrupted.
    """
    changed = False
    out_lines: list[str] = []
    for line in body.split("\n"):
        match = re.match(r"^(\s*)-\s+(.*\S)\s*$", line)
        if not match:
            out_lines.append(line)
            continue
        indent, text = match.group(1), match.group(2)
        # Skip tables and code-span/aligned content (backtick spans wrap ASCII
        # bar charts whose spacing is meaningful).
        if "|" in text or "`" in text:
            out_lines.append(line)
            continue
        # Weekly-digest format "[title](url) -- <summary>": clean only the
        # summary tail, preserving the link prefix. If the summary is non-prose
        # (stat dump/meta), drop just the tail and keep the bare link.
        if " -- " in text and "](" in text:
            prefix, summary = text.rsplit(" -- ", 1)
            cleaned = sanitize_summary_bullet(summary)
            if cleaned == summary:
                out_lines.append(line)
            elif cleaned:
                changed = True
                out_lines.append(f"{indent}- {prefix} -- {cleaned}")
            else:
                changed = True
                out_lines.append(f"{indent}- {prefix}")
            continue
        # Other linked bullets: leave untouched to avoid corrupting links.
        if "](" in text:
            out_lines.append(line)
            continue
        cleaned = sanitize_summary_bullet(text)
        if not cleaned:
            changed = True  # drop non-prose / meta bullet entirely
            continue
        if cleaned != text:
            changed = True
            out_lines.append(f"{indent}- {cleaned}")
        else:
            out_lines.append(line)
    return "\n".join(out_lines), changed


def process_post(filepath: Path, dry_run: bool = False) -> dict[str, int]:
    """Process a single post file. Returns dict of improvement counts."""
    content = filepath.read_text(encoding="utf-8")
    fm, body = parse_post(content)

    if not fm:
        return {}

    stats: dict[str, int] = {}

    # 1. Clean description
    if clean_description(fm):
        stats["description_cleaned"] = 1

    metadata_stats = rebuild_low_quality_metadata(fm, body)
    stats.update(metadata_stats)

    # 2. Remove intro duplication in summary
    body, did_change = remove_intro_duplication_in_summary(body)
    if did_change:
        stats["intro_dedup"] = 1

    body, did_change = remove_summary_article_duplicates(body)
    if did_change:
        stats["summary_article_dedup"] = 1

    # 3. Remove duplicate articles in insight
    body, did_change = remove_duplicate_articles_in_insight(body)
    if did_change:
        stats["insight_article_dedup"] = 1

    # 4. Replace generic insight phrases
    body, did_change = replace_generic_insight(body)
    if did_change:
        stats["insight_improved"] = 1

    # 5. Add Korean to monitoring keywords
    body, did_change = add_korean_to_keywords(body)
    if did_change:
        stats["keywords_translated"] = 1

    # 6. Clean empty data sections
    body, did_change = clean_empty_data_sections(body)
    if did_change:
        stats["empty_sections_cleaned"] = 1

    body, did_change = clean_keyword_none_artifacts(body)
    if did_change:
        stats["keyword_none_cleaned"] = 1

    body, did_change = remove_duplicate_articles_in_themes(body)
    if did_change:
        stats["theme_summary_dedup"] = 1

    body, did_change = sanitize_summary_bullets(body)
    if did_change:
        stats["summary_bullets_sanitized"] = 1

    body, did_change = sync_summary_total_count(body)
    if did_change:
        stats["summary_total_synced"] = 1

    body, did_change = fix_markdown_link_artifacts(body)
    if did_change:
        stats["markdown_fixed"] = 1

    # Remove "주요 키워드: ..." tails from body text (HTML and markdown)
    _body_before = body
    body = re.sub(r"\.\s*주요 키워드:[^<\n]{3,80}\.", ".", body)
    body = re.sub(r"\s*주요 키워드:[^<\n]{3,80}\.?(?=</)", "", body)
    if body != _body_before:
        stats["body_keyword_tail_cleaned"] = 1

    body, did_change = collapse_blank_lines(body)
    if did_change:
        stats["blank_lines_collapsed"] = 1

    # 9. Fix translation artifacts (particles, names, phrasing)
    body, did_change = fix_translation_artifacts(body)
    if did_change:
        stats["translation_fixed"] = 1

    if not stats:
        return {}

    # Write back
    new_content = serialize_front_matter(fm) + "\n\n" + body
    if not dry_run:
        filepath.write_text(new_content, encoding="utf-8")

    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Batch improve existing posts quality.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without modifying files.",
    )
    parser.add_argument(
        "--posts-dir",
        type=Path,
        default=POSTS_DIR,
        help="Path to _posts directory.",
    )
    parser.add_argument(
        "--files",
        nargs="*",
        default=None,
        help="Specific post files to process (absolute or relative paths).",
    )
    args = parser.parse_args()

    posts_dir: Path = args.posts_dir
    if not posts_dir.exists():
        print(f"Error: Posts directory not found: {posts_dir}", file=sys.stderr)
        sys.exit(1)

    if args.files:
        post_files = []
        for file_arg in args.files:
            path = Path(file_arg)
            if not path.is_absolute():
                direct_path = path.resolve()
                if direct_path.exists():
                    path = direct_path
                else:
                    path = (posts_dir / path).resolve()
            if path.exists() and path.suffix == ".md" and path.is_relative_to(posts_dir):
                post_files.append(path)
            elif path.exists() and path.suffix == ".md":
                print(f"Warning: Skipping file outside posts_dir: {path}", file=sys.stderr)
        post_files = sorted(set(post_files))
    else:
        post_files = sorted(posts_dir.glob("*.md"))
    print(f"Found {len(post_files)} posts in {posts_dir}")

    if args.dry_run:
        print("[DRY RUN] No files will be modified.\n")

    total_stats: dict[str, int] = {}
    modified_count = 0

    for filepath in post_files:
        stats = process_post(filepath, dry_run=args.dry_run)
        if stats:
            modified_count += 1
            changes = ", ".join(f"{k}={v}" for k, v in stats.items())
            print(f"  {'[DRY]' if args.dry_run else '[MOD]'} {filepath.name}: {changes}")
            for k, v in stats.items():
                total_stats[k] = total_stats.get(k, 0) + v

    print(f"\n{'=' * 60}")
    print(f"Total posts scanned: {len(post_files)}")
    print(f"Posts modified: {modified_count}")
    if total_stats:
        print("\nImprovements applied:")
        labels = {
            "description_cleaned": "Description SEO 정리",
            "description_rebuilt": "저품질 description 재생성",
            "excerpt_rebuilt": "저품질 excerpt 재생성",
            "intro_dedup": "인트로 중복 제거 (전체 뉴스 요약)",
            "insight_article_dedup": "주요 기사 중복 제거 (인사이트)",
            "insight_improved": "고정 인사이트 문구 개선",
            "keywords_translated": "모니터링 키워드 한국어 추가",
            "empty_sections_cleaned": "빈 데이터 섹션 정리",
            "keyword_none_cleaned": "키워드 None 아티팩트 정리",
            "theme_summary_dedup": "테마별 중복 요약 제거",
            "summary_bullets_sanitized": "요약 bullet 정제 (통계나열/메타/중복 제거)",
            "summary_total_synced": "요약 수집 건수 동기화",
            "markdown_fixed": "마크다운 링크/오버플로 아티팩트 정리",
            "blank_lines_collapsed": "불필요 빈 줄 축소",
            "translation_fixed": "번역 품질 교정 (조사/인명/어미)",
        }
        for key, count in sorted(total_stats.items()):
            label = labels.get(key, key)
            print(f"  - {label}: {count}건")
    else:
        print("No improvements needed.")


if __name__ == "__main__":
    main()
