"""Jekyll markdown post generator.

Generates _posts/ files with proper frontmatter and content formatting.
"""

import logging
import os
import re
from datetime import UTC, datetime
from typing import Dict, List, Optional

from common.markdown_utils import smart_truncate

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
        frontmatter_lines = [
            "---",
            "layout: post",
            f'title: "{escaped_title}"',
            f"date: {date.strftime('%Y-%m-%d %H:%M:%S %z')}",
            f"categories: [{self.category}]",
        ]

        if tags:
            safe_tags = [f'"{t.replace(chr(34), chr(92) + chr(34))}"' for t in tags[:10]]
            frontmatter_lines.append(f"tags: [{', '.join(safe_tags)}]")

        if source:
            frontmatter_lines.append(f'source: "{source}"')
        if source_url:
            frontmatter_lines.append(f'source_url: "{source_url}"')
        if lang:
            frontmatter_lines.append(f'lang: "{lang}"')
        if image:
            frontmatter_lines.append(f'image: "{image}"')

        if extra_frontmatter:
            for key, value in extra_frontmatter.items():
                safe_value = str(value).replace('"', '\\"').replace("\n", " ")
                frontmatter_lines.append(f'{key}: "{safe_value}"')

        # description 자동 생성 (SEO용, 160자 이내)
        if not (extra_frontmatter and "description" in extra_frontmatter):
            desc_text = ""
            for line in content.strip().split("\n"):
                stripped = line.strip()
                if (
                    stripped
                    and not stripped.startswith("#")
                    and not stripped.startswith("|")
                    and not stripped.startswith(">")
                    and not stripped.startswith("![")
                    and not stripped.startswith("---")
                    and not stripped.startswith("-")
                    and not stripped.startswith("<")
                    and not (stripped.startswith("*") and not stripped.startswith("**"))
                    and len(stripped) >= 50
                    and not re.match(r"^https?://", stripped)
                    and not re.match(r"^\d+[\.\)]\s", stripped)
                ):
                    desc_text = stripped
                    break
            if desc_text:
                desc_text = re.sub(r"<[^>]+>", "", desc_text)
                desc_text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", desc_text)
                desc_text = re.sub(r"[*_`~]", "", desc_text)
                desc_text = re.sub(r"\s+", " ", desc_text).strip()
                desc_text = smart_truncate(desc_text, 160)
                if desc_text:
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
