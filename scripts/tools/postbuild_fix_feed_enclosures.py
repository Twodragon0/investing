#!/usr/bin/env python3
"""Postbuild fixer: fill RSS <enclosure length="0"> with real byte sizes.

jekyll-feed always emits ``length="0"`` because Liquid cannot stat files.
Some podcast/aggregator clients prefer or require a real byte length per
RFC 4287 / RSS 2.0. This script runs after ``jekyll build`` and rewrites
enclosure tags in ``_site/feed.xml`` to use the actual file size from the
matching path under ``_site/``.

Usage
-----
  python3 scripts/tools/postbuild_fix_feed_enclosures.py            # default _site/feed.xml
  python3 scripts/tools/postbuild_fix_feed_enclosures.py --site DIR

Wire into vercel.json buildCommand so it runs on every deploy:
  bundle exec jekyll build && \\
  python3 scripts/tools/postbuild_fix_feed_enclosures.py

Idempotent — running twice is a no-op.

Implementation note: regex-based rewrite (no XML parser) is intentional.
The feed contains CDATA blocks with arbitrary HTML; a stricter parser
would re-serialize and risk altering whitespace or escaping. The pattern
matches only the self-closing ``<enclosure ... length="N" />`` tag, which
is unambiguous.
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

# Self-contained logging — this script must run in Vercel's build env where
# scripts/common is not deployed (.vercelignore excludes the wider scripts/
# tree to keep deploy size small; only this single file is un-ignored).
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("fix_feed_enclosures")

ENCLOSURE_RE = re.compile(r'<enclosure\s+url="(?P<url>[^"]+)"\s+type="(?P<type>[^"]+)"\s+length="(?P<len>\d+)"\s*/>')


def _emit(msg: str) -> None:
    sys.stdout.write(msg + "\n")


def _resolve_local_path(site_dir: Path, url: str) -> Path | None:
    """Map an absolute or relative URL onto a path under site_dir/."""
    parsed = urlparse(url)
    path = parsed.path.lstrip("/")
    if not path:
        return None
    candidate = (site_dir / path).resolve()
    # Prevent path-traversal escape from site_dir
    try:
        candidate.relative_to(site_dir.resolve())
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def fix_feed(feed_path: Path, site_dir: Path) -> tuple[int, int, int]:
    """Rewrite enclosures with real byte sizes. Returns (total, fixed, missing)."""
    text = feed_path.read_text(encoding="utf-8")
    total = fixed = missing = 0

    def _replace(match: re.Match[str]) -> str:
        nonlocal total, fixed, missing
        total += 1
        url = match.group("url")
        type_ = match.group("type")
        old_len = match.group("len")
        local = _resolve_local_path(site_dir, url)
        if local is None:
            missing += 1
            logger.debug("missing local file for enclosure URL: %s", url)
            return match.group(0)
        size = local.stat().st_size
        if str(size) == old_len:
            return match.group(0)
        fixed += 1
        return f'<enclosure url="{url}" type="{type_}" length="{size}"/>'

    new_text = ENCLOSURE_RE.sub(_replace, text)
    if new_text != text:
        feed_path.write_text(new_text, encoding="utf-8")
    return total, fixed, missing


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument(
        "--site",
        default="_site",
        help="Path to the built Jekyll output directory (default: _site)",
    )
    parser.add_argument(
        "--feed",
        default=None,
        help="Path to feed.xml within the site dir (default: <site>/feed.xml)",
    )
    args = parser.parse_args(argv)

    site_dir = Path(args.site).resolve()
    feed_path = Path(args.feed).resolve() if args.feed else site_dir / "feed.xml"

    if not feed_path.is_file():
        logger.warning("feed not found at %s; nothing to do", feed_path)
        return 0
    if not site_dir.is_dir():
        logger.error("site dir not found: %s", site_dir)
        return 2

    total, fixed, missing = fix_feed(feed_path, site_dir)
    _emit(f"enclosures: total={total} fixed={fixed} unchanged={total - fixed - missing} missing={missing}")
    if missing:
        logger.warning(
            "%d enclosures pointed at files not present in %s "
            '(probably absolute URLs to assets served elsewhere); left as length="0"',
            missing,
            site_dir,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
