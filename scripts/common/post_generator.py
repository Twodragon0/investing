"""Jekyll markdown post generator.

Generates _posts/ files with proper frontmatter and content formatting.
"""

import os
import re
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
POSTS_DIR = os.path.join(REPO_ROOT, "_posts")


def _slugify(text: str, max_length: int = 80) -> str:
    """Convert text to URL-safe slug."""
    text = text.lower().strip()
    # Keep Korean characters, alphanumeric, spaces
    text = re.sub(r"[^\w\s가-힣-]", "", text)
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"-+", "-", text)
    text = text.strip("-")
    return text[:max_length]


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
        extra_frontmatter: Optional[Dict[str, str]] = None,
    ) -> Optional[str]:
        """Create a Jekyll markdown post file.

        Returns the file path if created, None if skipped.
        """
        if not title or not title.strip():
            return None

        if date is None:
            date = datetime.now(timezone.utc)

        slug = _slugify(title)
        if not slug:
            slug = f"post-{date.strftime('%H%M%S')}"

        filename = f"{date.strftime('%Y-%m-%d')}-{slug}.md"
        filepath = os.path.join(POSTS_DIR, filename)

        if os.path.exists(filepath):
            logger.debug("Post already exists: %s", filename)
            return None

        # Build frontmatter
        escaped_title = title.replace('"', '\\"')
        frontmatter_lines = [
            "---",
            f'title: "{escaped_title}"',
            f"date: {date.strftime('%Y-%m-%d %H:%M:%S %z').strip()}",
            f"categories: [{self.category}]",
        ]

        if tags:
            safe_tags = [t.replace('"', '\\"') for t in tags[:10]]
            frontmatter_lines.append(f"tags: [{', '.join(safe_tags)}]")

        if source:
            frontmatter_lines.append(f"source: \"{source}\"")
        if source_url:
            frontmatter_lines.append(f"source_url: \"{source_url}\"")
        if lang:
            frontmatter_lines.append(f"lang: \"{lang}\"")

        if extra_frontmatter:
            for key, value in extra_frontmatter.items():
                frontmatter_lines.append(f"{key}: \"{value}\"")

        frontmatter_lines.append("---")

        # Build content
        post_content = "\n".join(frontmatter_lines) + "\n\n" + content.strip()

        # Add source attribution
        if source_url:
            post_content += f"\n\n---\n*출처: [{source}]({source_url})*\n"

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
        )
