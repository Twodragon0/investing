#!/usr/bin/env python3
"""Verify that every post's image: field points to an existing file.

For images under assets/images/generated/, also checks that .webp and .avif
variants exist (required by the <picture> element in generated-picture.html).

Exit code 0 = all OK, 1 = missing images found.
"""

import glob
import logging
import os
import re
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("check-post-images")

POSTS_DIR = os.path.join(os.path.dirname(__file__), "..", "_posts")
REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")

# Front matter image field pattern
IMAGE_RE = re.compile(r'^image:\s*["\']?(/[^"\']+)["\']?\s*$', re.MULTILINE)


def extract_image_path(post_path: str) -> str | None:
    """Extract image: field value from post front matter."""
    with open(post_path, encoding="utf-8") as f:
        content = f.read(4096)  # front matter is always near the top

    # Only look within front matter (between --- delimiters)
    parts = content.split("---", 2)
    if len(parts) < 3:
        return None

    match = IMAGE_RE.search(parts[1])
    return match.group(1) if match else None


def check_image_exists(image_url: str) -> list[str]:
    """Check if image file and its variants exist. Returns list of missing paths."""
    # Convert URL path to filesystem path
    rel_path = image_url.lstrip("/")
    abs_path = os.path.join(REPO_ROOT, rel_path)

    missing = []
    if not os.path.exists(abs_path):
        missing.append(rel_path)

    # For generated images, check webp and avif variants
    if "/assets/images/generated/" in image_url:
        base, ext = os.path.splitext(abs_path)
        for variant_ext in (".webp", ".avif"):
            variant_path = base + variant_ext
            if not os.path.exists(variant_path):
                missing.append(os.path.relpath(variant_path, REPO_ROOT))

    return missing


def main() -> int:
    posts = sorted(glob.glob(os.path.join(POSTS_DIR, "*.md")))
    if not posts:
        logger.warning("No posts found in %s", POSTS_DIR)
        return 0

    total_checked = 0
    all_missing: list[tuple[str, str, list[str]]] = []

    for post_path in posts:
        image_url = extract_image_path(post_path)
        if not image_url:
            continue

        total_checked += 1
        missing = check_image_exists(image_url)
        if missing:
            post_name = os.path.basename(post_path)
            all_missing.append((post_name, image_url, missing))

    logger.info("Checked %d posts with image references", total_checked)

    if all_missing:
        logger.error("Found %d posts with missing images:", len(all_missing))
        for post_name, image_url, missing_files in all_missing:
            logger.error("  %s (image: %s)", post_name, image_url)
            for mf in missing_files:
                logger.error("    MISSING: %s", mf)
        return 1

    logger.info("All image references are valid")
    return 0


if __name__ == "__main__":
    sys.exit(main())
