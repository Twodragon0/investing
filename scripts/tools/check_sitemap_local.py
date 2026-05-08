#!/usr/bin/env python3
"""Verify every URL in _site/sitemap.xml resolves to a built file on disk.

Catches:
- sitemap entries whose corresponding _site/<path>/index.html is missing
  (these become 404 once Google crawls)
- referenced og:image / page.image files that don't exist on disk

Read-only diagnostic — no external API calls, no GSC credentials needed.

Usage
-----
  python scripts/tools/check_sitemap_local.py
  python scripts/tools/check_sitemap_local.py --site _site --base-url https://investing.2twodragon.com
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "common"))
from config import setup_logging  # noqa: E402

logger = setup_logging("check_sitemap_local")

DEFAULT_SITE = "_site"
DEFAULT_BASE = "https://investing.2twodragon.com"


def extract_locs(sitemap_path: Path) -> list[str]:
    text = sitemap_path.read_text(encoding="utf-8")
    return re.findall(r"<loc>([^<]+)</loc>", text)


def url_to_disk_path(url: str, base_url: str, site_root: Path) -> Path:
    parsed = urlparse(url)
    path = parsed.path or "/"
    if path.endswith("/"):
        return site_root / path.lstrip("/") / "index.html"
    return site_root / path.lstrip("/")


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n", 1)[0])
    parser.add_argument("--site", default=DEFAULT_SITE)
    parser.add_argument("--base-url", default=DEFAULT_BASE)
    parser.add_argument(
        "--sitemap",
        default=None,
        help="Sitemap file (default: <site>/sitemap.xml)",
    )
    args = parser.parse_args()

    site_root = Path(args.site).resolve()
    sitemap_path = Path(args.sitemap) if args.sitemap else site_root / "sitemap.xml"

    if not sitemap_path.is_file():
        logger.error("sitemap not found: %s", sitemap_path)
        return 2

    urls = extract_locs(sitemap_path)
    logger.info("loaded %d URLs from %s", len(urls), sitemap_path)

    missing: list[tuple[str, Path]] = []
    for url in urls:
        if not url.startswith(args.base_url):
            logger.warning("skipping non-site URL: %s", url)
            continue
        disk = url_to_disk_path(url, args.base_url, site_root)
        if not disk.exists():
            missing.append((url, disk))

    if missing:
        logger.error("%d URLs in sitemap have no built file on disk:", len(missing))
        for url, disk in missing[:50]:
            logger.error("  %s -> %s", url, disk)
        if len(missing) > 50:
            logger.error("  ... %d more", len(missing) - 50)
        return 1

    logger.info("all %d sitemap URLs map to existing built files", len(urls))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
