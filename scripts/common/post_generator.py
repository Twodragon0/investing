"""Jekyll markdown post generator.

Generates _posts/ files with proper frontmatter and content formatting.
"""

import logging
import os
import re
from datetime import UTC, datetime
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

from common.markdown_utils import smart_truncate

KST = ZoneInfo("Asia/Seoul")

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
# Category default og:image mapping
# ---------------------------------------------------------------------------

_DEFAULT_CATEGORY_IMAGES: dict[str, str] = {
    "crypto": "/assets/images/og-crypto.png",
    "stock": "/assets/images/og-stock.png",
    "market-analysis": "/assets/images/og-market-analysis.png",
    "social-media": "/assets/images/og-social-media.png",
    "regulatory": "/assets/images/og-regulatory.png",
    "defi": "/assets/images/og-defi.png",
    "political-trades": "/assets/images/og-political-trades.png",
    "worldmonitor": "/assets/images/og-worldmonitor.png",
    "security-alerts": "/assets/images/og-security-alerts.png",
}


def _fix_translation_artifacts(text: str) -> str:
    """Remove token-name artifacts embedded in ordinary words after translation.

    When the placeholder-based translation system fails to protect a token name
    (e.g. AI, SOL) from being matched inside common words, the restored text
    can contain mixed-case oddities like "gAIn" or "GaSOLine". This function
    corrects those known patterns as a safety net.
    """
    for wrong, correct in _TOKEN_ARTIFACTS.items():
        text = text.replace(wrong, correct)
    return text


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


def _extract_description(content: str) -> str:
    """Extract first meaningful text line from markdown content for SEO description."""
    candidates = []
    for line in content.strip().split("\n"):
        stripped = line.strip()
        is_list_item = stripped.startswith("- ") and len(stripped) >= 4
        candidate = stripped[2:].strip() if is_list_item else stripped
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
            and (is_list_item or not stripped.startswith("-"))
        ):
            candidates.append(candidate)
            if len(candidates) >= 3:
                break

    if not candidates:
        return ""

    # Try single best candidate first
    desc_text = candidates[0]
    desc_text = re.sub(r"<[^>]+>", "", desc_text)
    desc_text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", desc_text)
    desc_text = re.sub(r"[*_`~]", "", desc_text)
    desc_text = re.sub(r"\s+", " ", desc_text).strip()

    # If too short, combine multiple candidates
    if len(desc_text) < 80 and len(candidates) > 1:
        combined = []
        total = 0
        for c in candidates:
            c = re.sub(r"<[^>]+>", "", c)
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
    "stock": "주식",
    "market-analysis": "시장 분석",
    "social-media": "소셜 미디어",
    "regulatory": "규제",
    "defi": "DeFi",
    "political-trades": "정치인 거래",
    "worldmonitor": "글로벌 이슈",
    "security-alerts": "보안",
}


def _build_fallback_description(title: str, category: str, tags: Optional[List[str]] = None) -> str:
    """Build a fallback SEO description from title and category when content extraction fails."""
    cat_ko = _CATEGORY_KO.get(category, category)
    tag_str = ""
    if tags and len(tags) >= 2:
        tag_str = f" 주요 키워드: {', '.join(tags[:4])}."

    # Clean title for description use
    clean_title = re.sub(r"[*_`~]", "", title).strip()
    desc = f"{clean_title} - 최신 {cat_ko} 뉴스와 분석을 확인하세요.{tag_str}"
    return smart_truncate(desc, 160)


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
        import html

        title = html.unescape(title)
        content = html.unescape(content)

        if date is None:
            date = datetime.now(UTC)

        if slug is None:
            slug = _slugify(title)
        if not slug:
            slug = f"post-{date.strftime('%H%M%S')}"

        filename = f"{date.strftime('%Y-%m-%d')}-{slug}.md"
        filepath = os.path.join(POSTS_DIR, filename)

        if os.path.exists(filepath):
            logger.debug("Post already exists: %s", filename)
            return None

        # Build frontmatter
        escaped_title = title.replace("\\", "\\\\").replace('"', '\\"')
        # Convert to KST for frontmatter display (filename keeps original date)
        if date.tzinfo is not None:
            date_kst = date.astimezone(KST)
        else:
            date_kst = date.replace(tzinfo=UTC).astimezone(KST)
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
            keywords = ", ".join(tags[:5])
            frontmatter_lines.append(f'keywords: "{keywords}"')

        if source:
            frontmatter_lines.append(f'source: "{source}"')
        if source_url:
            frontmatter_lines.append(f'source_url: "{source_url}"')
        if lang:
            frontmatter_lines.append(f'lang: "{lang}"')
        if not image:
            image = _DEFAULT_CATEGORY_IMAGES.get(self.category, "/assets/images/og-default.png")
        frontmatter_lines.append(f'image: "{image}"')

        if extra_frontmatter:
            for key, value in extra_frontmatter.items():
                safe_value = str(value).replace('"', '\\"').replace("\n", " ")
                frontmatter_lines.append(f'{key}: "{safe_value}"')

        # description 자동 생성 (SEO용, 80-160자)
        if not (extra_frontmatter and "description" in extra_frontmatter):
            desc_text = _extract_description(content)
            if not desc_text or len(desc_text) < 80:
                # Fallback: combine title + category context for SEO
                desc_text = _build_fallback_description(title, self.category, tags)
            if desc_text and len(desc_text) >= 80:
                safe_desc = desc_text.replace('"', "'")
                frontmatter_lines.append(f'description: "{safe_desc}"')

        frontmatter_lines.append("---")

        # Fix translation artifacts (e.g. "gAIn", "GaSOLine") before writing
        content = _fix_translation_artifacts(content)

        # Normalize hardcoded image paths in content to Liquid relative_url syntax
        normalized_content = _normalize_image_paths(content.strip())

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
        tags: Optional[List[str]] = None,
        image: str = "",
        slug: Optional[str] = None,
    ) -> Optional[str]:
        """Create a summary post with multiple sections (e.g., market summary)."""
        content_parts = []
        for section_title, section_content in sections.items():
            content_parts.append(f"## {section_title}\n\n{section_content}")

        content = "\n\n".join(content_parts)
        return self.create_post(
            title=title,
            content=content,
            date=date,
            tags=tags,
            source="auto-generated",
            image=image,
            slug=slug,
        )
