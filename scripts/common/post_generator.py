"""Jekyll markdown post generator.

Generates _posts/ files with proper frontmatter and content formatting.
"""

import html
import logging
import os
import re
from datetime import UTC, datetime
from typing import Dict, List, Optional

from common.asset_storage import is_enabled as _r2_enabled
from common.asset_storage import public_url as _r2_public_url
from common.config import get_kst_now, get_kst_timezone
from common.markdown_utils import smart_truncate

KST = get_kst_timezone()

logger = logging.getLogger(__name__)

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
POSTS_DIR = os.path.join(REPO_ROOT, "_posts")

# ---------------------------------------------------------------------------
# Translation artifact cleanup
# ---------------------------------------------------------------------------

# Known artifacts produced when crypto/finance token names get embedded inside
# ordinary English words during the placeholder-based translation process.
# Format: {wrong_form: correct_form}
_TOKEN_ARTIFACTS: dict[str, str] = {
    # AI token artifacts
    "RAIse": "Raise",
    "RAIses": "Raises",
    "RAIsed": "Raised",
    "RAIsing": "Raising",
    "gAIn": "gain",
    "gAIns": "gains",
    "gAIned": "gained",
    "gAIning": "gaining",
    "ChAIrman": "Chairman",
    "ChAIr": "Chair",
    "ChAIn": "Chain",
    "trAIl": "trail",
    "trAIling": "trailing",
    "pAId": "paid",
    "sAId": "said",
    "mAIn": "main",
    "mAIntain": "maintain",
    "mAIntains": "maintains",
    "remAIn": "remain",
    "remAIns": "remains",
    "remAIning": "remaining",
    "contAIn": "contain",
    "contAIns": "contains",
    "contAIner": "container",
    "certAIn": "certain",
    "sustAIn": "sustain",
    "explAIn": "explain",
    "obtAIn": "obtain",
    "attAIn": "attain",
    "agAInst": "against",
    "BrAIner": "Brainer",
    "brAIner": "brainer",
    "BillAIre": "Billionaire",
    "billAIre": "billionaire",
    "DubAI": "Dubai",
    "JamAIca": "Jamaica",
    "jamAIca": "jamaica",
    "DAIly": "Daily",
    "dAIly": "daily",
    "AIrspace": "airspace",
    "AIrport": "airport",
    "AIrline": "airline",
    "AIrlines": "airlines",
    "AIrcraft": "aircraft",
    "fAIr": "fair",
    "fAIled": "failed",
    "fAIlure": "failure",
    "fAIl": "fail",
    "wAIt": "wait",
    "wAIting": "waiting",
    "clAIm": "claim",
    "clAIms": "claims",
    "clAImed": "claimed",
    # SOL token artifacts
    "GaSOLine": "Gasoline",
    "gaSOLine": "gasoline",
    "abSOLute": "absolute",
    "abSOLutely": "absolutely",
    "reSOLve": "resolve",
    "reSOLved": "resolved",
    "reSOLution": "resolution",
    "SOLution": "Solution",
    "SOLutions": "Solutions",
    "SOLving": "Solving",
    "diSSOLve": "dissolve",
    "conSOLidate": "consolidate",
    "conSOLidation": "consolidation",
    # XRP token artifacts (less common but possible)
    "XRPected": "Expected",
    "XRPress": "Express",
    # ETH token artifacts
    "ETHical": "Ethical",
    "ETHics": "Ethics",
    # AI token artifacts (additional)
    "AIm": "aim",
    "AImed": "aimed",
    "AIming": "aiming",
    "trAIned": "trained",
    "trAIning": "training",
    "strAIght": "straight",
    "portrAIt": "portrait",
    # SOL token artifacts (additional)
    "SOLar": "solar",
    "SOLe": "sole",
    "SOLid": "solid",
    # DOT token artifacts
    "anecDOTe": "anecdote",
}

# ---------------------------------------------------------------------------
# Mistranslation correction dictionary
# ---------------------------------------------------------------------------

# Maps commonly mistranslated Korean words to their correct forms in
# financial/news context. Applied after _TOKEN_ARTIFACTS corrections.
_MISTRANSLATION_FIXES: dict[str, str] = {
    # Common verb mistranslations
    "선전하면서": "경고하면서",
    "선전함에": "경고함에",
    "선전했습니다": "경고했습니다",
    "선전하고": "경고하고",
    "시장을 선전하지만": "시장을 홍보하지만",
    "선전하는": "홍보하는",
    # "멸종" misused for weakening/elimination
    "멸종되고": "와해되고",
    "멸종시키": "제거하",
    "멸종될": "제거될",
    "'멸종'되고": "'와해'되고",
    # "열:" misused as column header
    "열: ": "칼럼: ",
    # Financial terms commonly mistranslated
    "해자가": "경쟁 우위가",
    "해자를": "경쟁 우위를",
    # "몽유병" misused for sleepwalking into crisis
    "몽유병에 빠져": "무방비 상태로",
    # Common awkward phrasings
    "돌연 급락": "급락",
    # News wire tags that leak into titles
    "(상보)": "",
    "(종합)": "",
    "(1보)": "",
    "(2보)": "",
    "(3보)": "",
    # AI slop overused words
    "획기적인 ": "",
    "혁신적인 ": "",
    "주목할 만한 수치입니다": "수치입니다",
    "다양한 이슈가 주요 화제입니다": "주요 이슈를 정리했습니다",
    "다양한 이슈": "주요 이슈",
    # "촉진" → more natural alternatives
    "발전을 촉진하는": "발전을 지원하는",
    "성장을 촉진": "성장을 견인",
    "채택을 촉진": "채택을 촉진",
    # 직역체: "선전한" in news context = "주장한/발표한"
    "선전한 후": "주장한 후",
    "을 선전": "을 주장",
    # 조사 오류: 받침 없는 이름 + 으로
    "트럼프으로": "트럼프와",
    # 띄어쓰기 오류
    "미국과이란": "미국과 이란",
    # 직역체: "unkillable" → "격추 불가능한"
    "죽일 수 없는": "격추 불가능한",
    # 직역체: 어색한 명사구
    "이더리움 눈 ": "이더리움, ",
    # 직역체: 어색한 강조 반복
    "매우 매우 ": "매우 ",
    # 조사 오류: "강세이 된" → "강세를 보인"
    "강세이 된": "강세를 보인",
    "강세이 ": "강세를 ",
    # 어색한 직역체: 의문형 기사 제목
    "잊어버리고 대신": "대신",
    # 어색한 직역: "반등 시간을 그리워"
    "시간을 그리워해야": "시점을 기다려야",
    "시간을 그리워": "시점을 기다려야",
}


# ---------------------------------------------------------------------------
# Category default og:image mapping
# ---------------------------------------------------------------------------

_DEFAULT_CATEGORY_IMAGES: dict[str, str] = {
    "crypto": "/assets/images/og-crypto.png",
    "crypto-news": "/assets/images/og-crypto.png",
    "stock": "/assets/images/og-stock.png",
    "stock-news": "/assets/images/og-stock.png",
    "market-analysis": "/assets/images/og-market-analysis.png",
    "social-media": "/assets/images/og-social-media.png",
    "regulatory": "/assets/images/og-regulatory.png",
    "regulatory-news": "/assets/images/og-regulatory.png",
    "defi": "/assets/images/og-defi.png",
    "political-trades": "/assets/images/og-political-trades.png",
    "worldmonitor": "/assets/images/og-worldmonitor.png",
    "security-alerts": "/assets/images/og-security-alerts.png",
    "blockchain": "/assets/images/og-blockchain.png",
}


def _default_category_image(category: str) -> str:
    fallback = _DEFAULT_CATEGORY_IMAGES.get(category)
    if fallback:
        return fallback
    logger.warning("Unknown post category for default image: %s", category)
    return "/assets/images/og-default.png"


def _resolve_post_image(image: str, category: str) -> str:
    if not image:
        return _default_category_image(category)

    if not image.startswith("/assets/images/"):
        logger.warning("Unexpected image path outside assets/images: %s", image)
        return _default_category_image(category)

    if "/generated/" not in image:
        return image

    if not image.endswith((".png", ".webp", ".jpg", ".jpeg", ".svg")):
        logger.warning("Unexpected generated image extension: %s", image)
        return _default_category_image(category)

    abs_img = os.path.join(REPO_ROOT, image.lstrip("/"))
    if not os.path.exists(abs_img):
        logger.warning("Generated image missing: %s", image)
        return _default_category_image(category)
    if os.path.getsize(abs_img) <= 0:
        logger.warning("Generated image empty: %s", image)
        return _default_category_image(category)

    # R2 활성 시 CDN URL 반환, 비활성 시 로컬 경로 그대로 반환
    if _r2_enabled():
        return _r2_public_url(image)
    return image


_WORDING_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    ("견인고", "견인하고"),
    ("실제로 확인해야 합니다.", ""),
    ("실제로 확인이 필요합니다.", ""),
    ("..", "."),
    (" .", "."),
    # Korean subject-particle corrections for proper nouns without 받침 (final consonant).
    # Names ending in an open syllable (no 받침) must take "가/는/를" not "이/은/을".
    ("트럼프이 ", "트럼프가 "),
    ("트럼프이란", "트럼프가 이란"),
    ("트럼프은 ", "트럼프는 "),
    ("트럼프을 ", "트럼프를 "),
    ("테슬라이 ", "테슬라가 "),
    ("테슬라은 ", "테슬라는 "),
    ("메타이 ", "메타가 "),
    ("메타은 ", "메타는 "),
    ("엔비디아이 ", "엔비디아가 "),
    ("엔비디아은 ", "엔비디아는 "),
    ("시진핑이 ", "시진핑이 "),  # 시진핑 has 받침 — keep "이"
    ("오바마이 ", "오바마가 "),
)


def _normalize_logical_date(logical_date: Optional[str], date_kst: datetime) -> str:
    if logical_date:
        normalized = logical_date.strip()
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", normalized):
            raise ValueError(f"logical_date must be YYYY-MM-DD, got: {logical_date}")
        return normalized
    return date_kst.strftime("%Y-%m-%d")


def _safe_path_component(s: str) -> str:
    """Validate and sanitize a path component for use in permalinks.

    Raises ValueError if the input cannot be sanitized to a valid component.
    """
    if not s:
        raise ValueError("Path component cannot be empty")
    # Lowercase, strip, remove outer slashes
    s = s.lower().strip().strip("/")
    # Reject traversal sequences
    if ".." in s or "\x00" in s:
        raise ValueError(f"Invalid path component: {s!r}")
    # Whitelist: alphanumeric, hyphens, underscores — replace others with hyphen
    s = re.sub(r"[^a-z0-9_-]", "-", s)
    # Collapse multiple hyphens
    s = re.sub(r"-+", "-", s).strip("-")
    if not s:
        raise ValueError("Path component empty after sanitization")
    return s


def build_dated_permalink(category: str, logical_date: str, slug: str) -> str:
    normalized_date = _normalize_logical_date(logical_date, get_kst_now())
    safe_category = _safe_path_component(category)
    safe_slug = _safe_path_component(slug)
    return f"/{safe_category}/{normalized_date.replace('-', '/')}/{safe_slug}/"


def _fix_translation_artifacts(text: str) -> str:
    """Remove token-name artifacts embedded in ordinary words after translation.

    When the placeholder-based translation system fails to protect a token name
    (e.g. AI, SOL) from being matched inside common words, the restored text
    can contain mixed-case oddities like "gAIn" or "GaSOLine". This function
    corrects those known patterns as a safety net.

    Also applies _MISTRANSLATION_FIXES to correct common Korean financial
    mistranslations produced during AI translation.
    """
    for wrong, correct in _TOKEN_ARTIFACTS.items():
        text = text.replace(wrong, correct)
    for wrong, correct in _MISTRANSLATION_FIXES.items():
        text = text.replace(wrong, correct)
    return text


def _polish_generated_text(text: str) -> str:
    if not text:
        return text
    for wrong, correct in _WORDING_REPLACEMENTS:
        text = text.replace(wrong, correct)
    # Fix incomplete "시장 영향 가능" without already being "가능성이 있는"
    text = re.sub(r"시장 영향 가능(?!성이 있는)", "시장 영향 가능성이 있는", text)
    # Collapse multiple spaces within lines but preserve newlines for markdown structure
    text = re.sub(r"[^\S\n]+", " ", text)
    # Collapse 3+ consecutive blank lines into 2
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    text = re.sub(r"([.!?]){2,}", r"\1", text)
    text = re.sub(r"\s+([,.!?])", r"\1", text)
    return text.strip()


def _slugify(text: str, max_length: int = 80) -> str:
    """Convert text to URL-safe slug (English-only, strips Korean characters).

    Intentionally different from utils.slugify which preserves Korean (가-힣).
    This version is used for Jekyll filenames where ASCII-only slugs are needed.
    """
    text = text.lower().strip()
    # Keep only English alphanumeric, spaces, and hyphens
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"-+", "-", text)
    text = text.strip("-")
    return text[:max_length]


_HARDCODED_IMG_RE = re.compile(r"!\[([^\]]*)\]\((/assets/images/generated/[^)]+)\)")
_LIQUID_IMG_RE = re.compile(
    r"!\[([^\]]*)\]\(\{\{\s*'(/assets/images/generated/[^']+\.png)'\s*\|\s*relative_url\s*\}\}\)"
)


def _normalize_image_paths(content: str) -> str:
    """Replace hardcoded /assets/images/generated/... paths with Liquid relative_url.

    Converts ``![alt](/assets/images/generated/foo.png)`` to the Liquid form
    ``![alt]({{ '/assets/images/generated/foo.png' | relative_url }})`` so
    images render correctly on both the live site and any subdirectory deploy.
    Already-converted Liquid references are left unchanged.
    """

    def _replace(match: re.Match) -> str:
        alt = match.group(1)
        path = match.group(2)
        return "![" + alt + "]({{ '" + path + "' | relative_url }})"

    return _HARDCODED_IMG_RE.sub(_replace, content)


def _normalize_generated_body(content: str) -> str:
    content = re.sub(
        r"(\*\*\d+\.\s+)\[([^\]\n]+)\]\s([^\n\]]+)\]\(([^)]+)\)\*\*",
        lambda m: f"{m.group(1)}[{m.group(2)} {m.group(3)}]({m.group(4)})**",
        content,
    )
    content = re.sub(
        r"(^\s*[-*]\s+)\[([^\]\n]+)\]\s([^\n\]]+)\]\(([^)]+)\)",
        lambda m: f"{m.group(1)}[{m.group(2)} {m.group(3)}]({m.group(4)})",
        content,
        flags=re.MULTILINE,
    )
    content = content.replace(r"\]", "]")
    content = re.sub(r"(\[[^\]\n]{1,120}\])(?=[가-힣A-Za-z\"])", r"\1 ", content)
    content = re.sub(r"<li><em>\.외\s+(\d+)건</em></li>", r"<li><em>외 \1건</em></li>", content)
    content = re.sub(r">\.외\s+(\d+)건<", r">외 \1건<", content)
    content = re.sub(r"(^\s*[-*])\s+-\s+", r"\1 ", content, flags=re.MULTILINE)

    stat_match = re.search(
        r'<div class="stat-value">(\d+)</div><div class="stat-label">수집 건수</div>',
        content,
    )
    total_count = stat_match.group(1) if stat_match else None
    if not total_count:
        intro_match = re.search(r"총\s+(\d+)건(?:의 뉴스)?가?\s+(?:수집|분석)", content)
        total_count = intro_match.group(1) if intro_match else None
    if total_count:
        content = re.sub(r"- 총 \*\*\d+건\*\* 수집", f"- 총 **{total_count}건** 수집", content)

    return content


def _wrap_picture_tags(content: str) -> str:
    """Convert generated PNG markdown images to HTML <picture> tags with WebP.

    Transforms Liquid-form ``![alt]({{ '/assets/images/generated/foo.png' | relative_url }})``
    into ``<picture><source srcset="..." type="image/webp"><img src="..." alt="..." loading="lazy"></picture>``
    for server-side WebP-first rendering without JavaScript dependency.
    """

    def _picture_replace(match: re.Match) -> str:
        alt = match.group(1)
        png_path = match.group(2)
        webp_path = png_path.replace(".png", ".webp")
        return (
            "<picture>"
            "<source srcset=\"{{ '" + webp_path + '\' | relative_url }}" type="image/webp">'
            "<img src=\"{{ '" + png_path + "' | relative_url }}\" "
            'alt="' + alt + '" loading="lazy" decoding="async">'
            "</picture>\n"
        )

    return _LIQUID_IMG_RE.sub(_picture_replace, content)


def _extract_description(content: str) -> str:
    """Extract first meaningful text line from markdown content for SEO description.

    Prioritizes executive opener (긴급/P0 sections) and bold-lead sentences
    before falling back to generic first-line extraction.
    """
    # Try theme summary first (### 테마별 동향 section) for richer SEO descriptions
    theme_match = re.search(r"### 테마별 동향\n+((?:- .+\n?){1,3})", content)
    if theme_match:
        theme_lines = theme_match.group(1).strip().split("\n")
        parts = []
        for tl in theme_lines[:2]:
            clean = re.sub(r"[*_`~]", "", tl.lstrip("- ")).strip()
            if clean and len(clean) >= 15:
                parts.append(clean)
        if parts:
            combined = " ".join(parts)
            return smart_truncate(combined, 160)

    # Prefer data-driven sentences with numbers/percentages for richer SEO
    data_match = re.search(
        r"(?:^|\n)\s*\**([^#\n|<>]{25,160}?\d+[\d,.]*%?[^#\n|<>]{0,80}?)[.\n]",
        content[:1500],
    )
    if data_match:
        lead = data_match.group(1).strip()
        lead = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", lead)
        lead = re.sub(r"[*_`~]", "", lead).strip()
        if len(lead) >= 30 and not lead.startswith("긴급") and re.search(r"\d", lead):
            return smart_truncate(lead, 160)

    # Try to extract executive opener (bold lead sentence), skip "긴급:" patterns
    bold_match = re.search(r"\*\*(.{20,120}?)\*\*", content[:600])
    if bold_match:
        lead = bold_match.group(1).strip()
        lead = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", lead)
        lead = re.sub(r"[*_`~]", "", lead).strip()
        # Skip "긴급:" leads — they are redundant with alert boxes
        if len(lead) >= 30 and not lead.startswith("긴급"):
            return smart_truncate(lead, 160)

    # Strip HTML block elements (stat-grid, alert-box divs) before line-by-line scan
    content = re.sub(r"<div[^>]*>.*?</div>", " ", content, flags=re.DOTALL)
    # Re-split on sentence boundaries after div removal to restore scannable lines
    content = re.sub(r"\s*##\s+", "\n## ", content)
    candidates = []
    for line in content.strip().split("\n"):
        stripped = line.strip()
        is_list_item = stripped.startswith("- ") and len(stripped) >= 4
        candidate = stripped[2:].strip() if is_list_item else stripped
        plain_candidate = re.sub(r"[*_`~]", "", candidate).strip()
        if (
            candidate
            and not candidate.startswith("#")
            and not candidate.startswith("|")
            and not candidate.startswith(">")
            and not candidate.startswith("![")
            and not candidate.startswith("---")
            and not candidate.startswith("<")
            and not (candidate.startswith("*") and not candidate.startswith("**"))
            and len(candidate) >= 20
            and not re.match(r"^https?://", candidate)
            and not re.match(r"^\d+[\.\)]\s", candidate)
            and not plain_candidate.endswith(":")
            and not re.match(r"^\d{4}-\d{2}-\d{2}\b", plain_candidate)
            and (is_list_item or not stripped.startswith("-"))
        ):
            candidates.append(candidate)
            if len(candidates) >= 3:
                break

    # Filter out boilerplate intro patterns that would create duplication
    _current_year = str(datetime.now(UTC).year)
    _prev_year = str(int(_current_year) - 1)
    _BOILERPLATE_STARTS = [
        "총 ",
        "오늘 ",
        "금일 ",
        f"{_current_year}-",
        f"{_prev_year}-",
        "전 세계 ",
        "미국 정치인",
        "소셜 미디어",
    ]
    filtered = [c for c in candidates if not any(c.startswith(prefix) for prefix in _BOILERPLATE_STARTS)]
    candidates = filtered or candidates  # fall back to original if all filtered

    if not candidates:
        return ""

    # Try single best candidate first
    desc_text = candidates[0]
    desc_text = re.sub(r"<[^>]+>", " ", desc_text)
    desc_text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", desc_text)
    desc_text = re.sub(r"[*_`~]", "", desc_text)
    desc_text = re.sub(r"\s+", " ", desc_text).strip()

    # If too short, combine multiple candidates
    if len(desc_text) < 80 and len(candidates) > 1:
        combined = []
        total = 0
        for c in candidates:
            c = re.sub(r"<[^>]+>", " ", c)
            c = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", c)
            c = re.sub(r"[*_`~]", "", c)
            c = re.sub(r"\s+", " ", c).strip()
            combined.append(c)
            total += len(c)
            if total >= 80:
                break
        desc_text = " ".join(combined)

    return smart_truncate(desc_text, 160)


# Category Korean names for fallback descriptions
_CATEGORY_KO: dict[str, str] = {
    "crypto": "암호화폐",
    "crypto-news": "암호화폐",
    "stock": "주식",
    "stock-news": "주식",
    "market-analysis": "시장 분석",
    "social-media": "소셜 미디어",
    "regulatory": "규제",
    "regulatory-news": "규제",
    "defi": "DeFi",
    "blockchain": "블록체인",
    "geopolitical": "지정학",
    "daily-summary": "일일요약",
    "political-trades": "정치인 거래",
    "worldmonitor": "글로벌 이슈",
    "security-alerts": "보안",
}


_CATEGORY_DESC_TEMPLATES: dict[str, list[str]] = {
    "crypto-news": [
        "{title} — 비트코인·이더리움 시세 변동과 온체인 데이터를 분석합니다.",
        "오늘의 암호화폐 브리핑: {title}. 크립토 시장 심리와 자금 흐름을 점검합니다.",
        "{title}. 주요 코인 가격 동향과 거래량 변화를 정리합니다.",
    ],
    "stock-news": [
        "{title} — 미국·한국 주식 시장 동향과 섹터별 투자 포인트를 분석합니다.",
        "오늘의 주식 시장: {title}. 주요 지수 흐름과 종목 이슈를 정리합니다.",
        "{title}. 매크로 지표와 기업 실적이 투자 전략에 미치는 영향을 살펴봅니다.",
    ],
    "regulatory-news": [
        "{title} — 글로벌 금융 규제 변화와 시장 영향을 분석합니다.",
        "규제 동향 브리핑: {title}. 각국 규제 기관의 최신 결정을 정리합니다.",
        "{title}. 규제 환경 변화가 투자 전략에 미칠 영향을 점검합니다.",
    ],
    "worldmonitor": [
        "{title} — 지정학적 리스크와 글로벌 안보 이슈를 모니터링합니다.",
        "글로벌 브리핑: {title}. 국제 정세가 금융 시장에 미치는 영향을 분석합니다.",
        "{title}. 지정학적 변수와 매크로 리스크 요인을 점검합니다.",
    ],
    "political-trades": [
        "{title} — 미국 의회 내부자 거래와 정책 연관성을 분석합니다.",
        "정치인 거래 리포트: {title}. 입법 동향과 의원 포트폴리오 변화를 추적합니다.",
    ],
    "social-media": [
        "{title} — 소셜 미디어 트렌드와 시장 심리를 분석합니다.",
        "소셜 브리핑: {title}. 커뮤니티 반응과 투자 심리 변화를 정리합니다.",
    ],
    "market-analysis": [
        "{title} — 시장 전반의 흐름과 크로스에셋 투자 시사점을 분석합니다.",
        "시장 분석 브리핑: {title}. 주요 자산군의 상관관계와 방향성을 점검합니다.",
    ],
    "security-alerts": [
        "{title} — 사이버 보안 위협과 취약점 대응 현황을 정리합니다.",
        "보안 알림: {title}. 주요 보안 사고와 시장 신뢰에 미칠 영향을 분석합니다.",
    ],
    "defi": [
        "{title} — DeFi 프로토콜 TVL 변동과 유동성 흐름을 분석합니다.",
        "DeFi 리포트: {title}. 주요 프로토콜 수익률과 리스크 지표를 점검합니다.",
        "{title}. 탈중앙 금융 생태계의 성장성과 위험 요인을 정리합니다.",
    ],
    "blockchain": [
        "{title} — 블록체인 네트워크 해시레이트와 온체인 활동을 분석합니다.",
        "블록체인 리포트: {title}. 네트워크 건전성과 트랜잭션 동향을 점검합니다.",
        "{title}. 주요 체인별 가스비·활성 주소·TPS 지표를 정리합니다.",
    ],
}


def _is_mostly_english(text: str) -> bool:
    """Return True if text is predominantly English (>60% ASCII letters)."""
    if not text:
        return False
    alpha_chars = [c for c in text if c.isalpha()]
    if not alpha_chars:
        return False
    ascii_count = sum(1 for c in alpha_chars if ord(c) < 128)
    return ascii_count / len(alpha_chars) > 0.6


def _build_fallback_description(title: str, category: str, tags: Optional[List[str]] = None) -> str:
    """Build a fallback SEO description from title and category.

    Uses category-specific templates for better SEO diversity,
    falling back to generic templates when no match exists.
    """
    cat_ko = _CATEGORY_KO.get(category, category)

    # Clean title for description use
    clean_title = re.sub(r"[*_`~]", "", title).strip()
    # Remove date suffix from title if present (e.g., "- 2026-03-25")
    clean_title = re.sub(r"\s*[-–]\s*\d{4}-\d{2}-\d{2}\s*$", "", clean_title).strip()

    # Try category-specific template first
    cat_templates = _CATEGORY_DESC_TEMPLATES.get(category)
    if cat_templates:
        seed = hash((datetime.now(UTC).date().isoformat(), title))
        template = cat_templates[seed % len(cat_templates)]
        desc = template.format(title=clean_title)
        return smart_truncate(desc, 160)

    templates = [
        f"{clean_title} — 최신 {cat_ko} 뉴스와 투자 포인트를 정리합니다.",
        f"{cat_ko} 핵심 동향: {clean_title}. 시장 영향과 대응 전략을 확인하세요.",
        f"오늘의 {cat_ko} 브리핑 — {clean_title}. 주요 이슈와 투자 시사점을 분석합니다.",
        f"{clean_title} — {cat_ko} 시장에 미칠 영향을 점검합니다.",
    ]
    seed = hash((datetime.now(UTC).date().isoformat(), title))
    desc = templates[seed % len(templates)]
    return smart_truncate(desc, 160)


def _clean_description(desc: str) -> str:
    """Clean and optimize description for SEO.

    - Removes HTML tags and markdown formatting
    - Fixes encoding artifacts (e.g. "612개월" → "6~12개월")
    - Truncates to 160 chars at a natural sentence boundary
    - Pads to at least 80 chars if too short
    """
    # Fix concatenated number artifacts (e.g. "612개월" → "6~12개월")
    # Only match 2-3 digit numbers where first digit < second group (realistic ranges)
    desc = re.sub(
        r"(?<!\d)(?<![A-Za-z가-힣])([1-9])(\d{1,2})(개월|년|일|시간)",
        lambda m: (
            m.group(1) + "~" + m.group(2) + m.group(3)
            if int(m.group(1)) < int(m.group(2)) and int(m.group(2)) <= 31
            else m.group(0)
        ),
        desc,
    )
    # Remove HTML tags (replace with space to avoid concatenation artifacts)
    desc = re.sub(r"<[^>]+>", " ", desc)
    # Remove markdown links but keep link text
    desc = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", desc)
    # Remove markdown formatting characters
    desc = re.sub(r"[*_`#~]", "", desc)
    desc = re.sub(r"^[^\w\uAC00-\uD7A3]+", "", desc)
    # Remove emojis and special unicode symbols (bad for SEO/social previews)
    desc = re.sub(
        r"[\U0001F300-\U0001F9FF\U00002702-\U000027B0\U0000FE00-\U0000FE0F"
        r"\U0001FA00-\U0001FA6F\U0001FA70-\U0001FAFF\U00002600-\U000026FF"
        r"\U0000200D\U00002640\U00002642]+",
        " ",
        desc,
    )
    # Collapse multiple whitespace
    desc = re.sub(r"\s+", " ", desc).strip()
    # Truncate to 160 chars at sentence boundary
    if len(desc) > 160:
        cut = -1
        for end in ["니다.", "습니다.", "세요.", "다.", "요."]:
            idx = desc.rfind(end, 0, 160)
            if idx > 80:
                cut = idx + len(end)
                break
        if cut > 0:
            desc = desc[:cut]
        else:
            desc = desc[:157] + "..."
    # Pad if too short
    if len(desc) < 80 and desc:
        desc = desc.rstrip(".") + " - Investing Dragon 자동 수집 분석 리포트."
    return desc


class PostGenerator:
    """Generate Jekyll markdown posts from collected news data."""

    def __init__(self, category: str):
        self.category = category
        os.makedirs(POSTS_DIR, exist_ok=True)

    def create_post(
        self,
        title: str,
        content: str,
        date: Optional[datetime] = None,
        logical_date: Optional[str] = None,
        tags: Optional[List[str]] = None,
        source: str = "",
        source_url: str = "",
        lang: str = "ko",
        image: str = "",
        extra_frontmatter: Optional[Dict[str, str]] = None,
        slug: Optional[str] = None,
    ) -> Optional[str]:
        """Create a Jekyll markdown post file.

        Returns the file path if created, None if skipped.
        """
        if not title or not title.strip():
            return None

        # Decode HTML entities (e.g. &#x27; → ', &amp; → &) in title and content
        title = _polish_generated_text(html.unescape(title))
        content = _polish_generated_text(html.unescape(content))
        content = _normalize_generated_body(content)

        if date is None:
            date = get_kst_now()

        if date.tzinfo is not None:
            date_kst = date.astimezone(KST)
        else:
            date_kst = date.replace(tzinfo=UTC).astimezone(KST)

        if slug is None:
            slug = _slugify(title)
        if not slug:
            slug = f"post-{date.strftime('%H%M%S')}"

        filename_date = _normalize_logical_date(logical_date, date_kst)
        filename = f"{filename_date}-{slug}.md"
        filepath = os.path.join(POSTS_DIR, filename)

        if os.path.exists(filepath):
            logger.debug("Post already exists: %s", filename)
            return None

        # Build frontmatter
        escaped_title = title.replace("\\", "\\\\").replace('"', '\\"')
        frontmatter_lines = [
            "---",
            "layout: post",
            f'title: "{escaped_title}"',
            f"date: {date_kst.strftime('%Y-%m-%d %H:%M:%S %z')}",
            f"categories: [{self.category}]",
        ]

        if tags:
            safe_tags = [f'"{t.replace(chr(34), chr(92) + chr(34))}"' for t in tags[:10]]
            frontmatter_lines.append(f"tags: [{', '.join(safe_tags)}]")
            # tags 기반으로 keywords 생성 (SEO용)
            keywords = ", ".join(tags[:5]).replace('"', '\\"').replace("\n", " ")
            frontmatter_lines.append(f'keywords: "{keywords}"')

        if source:
            safe_source = source.replace('"', '\\"').replace("\n", " ")
            frontmatter_lines.append(f'source: "{safe_source}"')
        if source_url:
            safe_url = source_url.replace('"', '\\"').replace("\n", "")
            frontmatter_lines.append(f'source_url: "{safe_url}"')
        if lang:
            frontmatter_lines.append(f'lang: "{lang}"')
        image = _resolve_post_image(image, self.category)
        frontmatter_lines.append(f'image: "{image}"')

        if extra_frontmatter:
            for key, value in extra_frontmatter.items():
                # description_ko는 description 생성 소스로만 사용 — front-matter에 직접 출력하지 않음
                if key == "description_ko":
                    continue
                safe_value = str(value).replace('"', '\\"').replace("\n", " ")
                frontmatter_lines.append(f'{key}: "{safe_value}"')

        # description 자동 생성 (SEO용, 80-200자)
        desc_text = ""
        has_desc = extra_frontmatter and "description" in extra_frontmatter
        if not has_desc:
            # description_ko가 있으면 우선 사용
            if extra_frontmatter and extra_frontmatter.get("description_ko"):
                desc_text = _clean_description(str(extra_frontmatter["description_ko"]))
            else:
                desc_text = _extract_description(content)
                desc_text = _clean_description(desc_text)
                # Detect predominantly English description and use Korean fallback
                if desc_text and _is_mostly_english(desc_text):
                    desc_text = _build_fallback_description(title, self.category, tags)
                    desc_text = _clean_description(desc_text)
            if not desc_text or len(desc_text) < 80:
                desc_text = _build_fallback_description(title, self.category, tags)
                desc_text = _clean_description(desc_text)
            if desc_text and len(desc_text) >= 80:
                safe_desc = _polish_generated_text(desc_text).replace('"', "'")
                frontmatter_lines.append(f'description: "{safe_desc}"')

        # excerpt 자동 생성 (SNS 미리보기용, 짧은 요약)
        if not (extra_frontmatter and "excerpt" in extra_frontmatter):
            excerpt_text = desc_text if desc_text else _extract_description(content)
            if excerpt_text and _is_mostly_english(excerpt_text):
                excerpt_text = _build_fallback_description(title, self.category, tags)
            if excerpt_text:
                excerpt_text = _polish_generated_text(smart_truncate(excerpt_text, 100)).replace('"', "'")
                frontmatter_lines.append(f'excerpt: "{excerpt_text}"')

        # image_alt 자동 생성 (접근성 + SNS 이미지 설명)
        if not (extra_frontmatter and "image_alt" in extra_frontmatter):
            cat_ko = _CATEGORY_KO.get(self.category, self.category)
            clean_title = re.sub(r"[*_`~]", "", title).strip()
            image_alt = _polish_generated_text(f"{clean_title} - {cat_ko} 뉴스 요약 이미지")
            safe_alt = image_alt.replace('"', "'")
            frontmatter_lines.append(f'image_alt: "{safe_alt}"')

        frontmatter_lines.append("---")

        # Fix translation artifacts (e.g. "gAIn", "GaSOLine") before writing
        content = _polish_generated_text(_fix_translation_artifacts(content))
        if lang == "ko":
            try:
                from common.translator import translate_untranslated_body

                content = translate_untranslated_body(content)
            except Exception as exc:  # noqa: BLE001
                logger.debug("Body post-processing translation skipped: %s", exc)
            content = _polish_generated_text(_fix_translation_artifacts(content))

        normalized_content = _normalize_image_paths(content.strip())
        # Convert generated PNG images to <picture> tags with WebP sources
        normalized_content = _wrap_picture_tags(normalized_content)

        # Build content
        post_content = "\n".join(frontmatter_lines) + "\n\n" + normalized_content

        # Validate frontmatter structure (must start with --- and have closing ---)
        if not post_content.startswith("---\n") or "\n---\n" not in post_content[4:]:
            logger.warning("Invalid frontmatter in post: %s", filename)
            return None

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(post_content)

        logger.info("Created post: %s", filename)
        return filepath

    def create_summary_post(
        self,
        title: str,
        sections: Dict[str, str],
        date: Optional[datetime] = None,
        logical_date: Optional[str] = None,
        tags: Optional[List[str]] = None,
        image: str = "",
        slug: Optional[str] = None,
    ) -> Optional[str]:
        """Create a summary post with multiple sections (e.g., market summary)."""
        content_parts = []
        for section_title, section_content in sections.items():
            stripped = section_content.strip()
            if stripped.startswith("## "):
                content_parts.append(stripped)
            else:
                content_parts.append(f"## {section_title}\n\n{stripped}")

        content = "\n\n".join(content_parts)
        return self.create_post(
            title=title,
            content=content,
            date=date,
            logical_date=logical_date,
            tags=tags,
            source="auto-generated",
            image=image,
            slug=slug,
        )
