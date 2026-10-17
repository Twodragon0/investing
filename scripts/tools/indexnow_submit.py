#!/usr/bin/env python3
"""IndexNow URL submission tool.

Submits URLs to the IndexNow API so that Bing, Yandex, and other participating
search engines index new or updated content immediately.

Usage
-----
  # Submit specific URLs
  python scripts/tools/indexnow_submit.py --urls https://investing.2twodragon.com/foo/

  # Submit most-recent N posts (scans _posts/)
  python scripts/tools/indexnow_submit.py --from-recent-posts 30

  # Submit URLs from a live sitemap
  python scripts/tools/indexnow_submit.py --from-sitemap

  # Submit changed posts since a git ref
  python scripts/tools/indexnow_submit.py --from-changed-posts HEAD~1

Configuration
-------------
  INDEXNOW_KEY  — API key (default: embedded public key)

References
----------
  https://www.indexnow.org/documentation
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit
from xml.etree import ElementTree

# Import config.py directly without going through common/__init__.py — keeps
# this tool stdlib-only so the IndexNow workflow does not need to install the
# heavy collector dependency tree (requests, lxml, playwright, etc.).
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "common"))
from config import REQUEST_TIMEOUT, get_env, setup_logging  # noqa: E402

logger = setup_logging("indexnow_submit")

# Public IndexNow key — lives in <KEY>.txt at the site root.
# This is intentionally not a secret; the file at the keyLocation URL
# must contain exactly this string for verification to pass.
_DEFAULT_KEY = "f71a0af133e16771baeeb3c5e137d8df"

INDEXNOW_ENDPOINT = "https://api.indexnow.org/IndexNow"
HOST = "investing.2twodragon.com"
MAX_URLS_PER_BATCH = 10_000


# ── helpers ──────────────────────────────────────────────────────────────────


def _get_key(args: argparse.Namespace) -> str:
    """Return the IndexNow key from CLI flag, env var, or embedded default."""
    if args.key:
        return args.key
    env_key = get_env("INDEXNOW_KEY", "")
    return env_key if env_key else _DEFAULT_KEY


def _validate_url(url: str) -> bool:
    """Return True if url belongs to the configured HOST."""
    return url.startswith(f"https://{HOST}/") or url.startswith(f"http://{HOST}/")


def _batch(items: list, size: int):
    """Yield successive chunks of *size* from *items*."""
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _submit_batch(urls: list[str], key: str) -> bool:
    """POST one batch of URLs to the IndexNow API.

    Returns True on success (HTTP 200/202), False otherwise.
    """
    payload = {
        "host": HOST,
        "key": key,
        "keyLocation": f"https://{HOST}/{key}.txt",
        "urlList": urls,
    }
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        INDEXNOW_ENDPOINT,
        data=body,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "InvestingDragon-IndexNow/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(
            req, timeout=REQUEST_TIMEOUT
        ) as resp:  # fixed https IndexNow endpoint  # nosec B310
            status = resp.status
            if status in (200, 202):
                logger.info("IndexNow accepted %d URL(s) — HTTP %d", len(urls), status)
                return True
            body_text = resp.read(512).decode("utf-8", errors="replace")
            logger.error(
                "IndexNow returned HTTP %d for %d URL(s): %s",
                status,
                len(urls),
                body_text,
            )
            return False
    except urllib.error.HTTPError as exc:
        error_body = exc.read(512).decode("utf-8", errors="replace") if exc.fp else ""
        logger.error(
            "IndexNow HTTP error %d for %d URL(s): %s",
            exc.code,
            len(urls),
            error_body,
        )
        return False
    except urllib.error.URLError as exc:
        logger.error("IndexNow network error for %d URL(s): %s", len(urls), exc.reason)
        return False


def submit_urls(urls: list[str], key: str) -> bool:
    """Validate, deduplicate, batch, and submit *urls*.

    Returns True only if every batch succeeds.
    """
    valid = [u for u in urls if _validate_url(u)]
    invalid = set(urls) - set(valid)
    if invalid:
        for u in sorted(invalid):
            logger.warning("Skipping URL that does not match host %s: %s", HOST, u)

    deduped = list(dict.fromkeys(valid))  # preserve order, drop dups
    if not deduped:
        logger.warning("No valid URLs to submit after filtering.")
        return True  # nothing to do is not a failure

    logger.info("Submitting %d URL(s) to IndexNow in batches of %d", len(deduped), MAX_URLS_PER_BATCH)
    all_ok = True
    for chunk in _batch(deduped, MAX_URLS_PER_BATCH):
        if not _submit_batch(chunk, key):
            all_ok = False
    return all_ok


# ── URL derivation strategies ─────────────────────────────────────────────────


def _permalink_from_post(md_path: Path) -> Optional[str]:
    """Extract or derive the permalink for a Jekyll post.

    Reads the front matter (up to the second '---' delimiter) to find an
    explicit ``permalink:`` field.  Falls back to deriving the URL from the
    filename pattern ``YYYY-MM-DD-slug.md``.
    """
    try:
        content = md_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        logger.warning("Cannot read %s: %s", md_path, exc)
        return None

    # Extract YAML front matter
    fm_match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
    if fm_match:
        fm_text = fm_match.group(1)
        # Look for explicit permalink: /some/path/
        pl_match = re.search(r'^permalink:\s*["\']?(/[^\s"\']+)["\']?', fm_text, re.MULTILINE)
        if pl_match:
            path = pl_match.group(1).rstrip("/") + "/"
            return f"https://{HOST}{path}"

        # Extract categories for fallback URL construction
        cat_match = re.search(r"^categories:\s*\[([^\]]+)\]", fm_text, re.MULTILINE)
        if cat_match:
            # Take the first category
            categories = [c.strip().strip("\"'") for c in cat_match.group(1).split(",")]
            category = categories[0] if categories else "uncategorized"
        else:
            category = "news"
    else:
        category = "news"

    # Derive from filename: YYYY-MM-DD-slug.md
    stem = md_path.stem
    date_match = re.match(r"^(\d{4})-(\d{2})-(\d{2})-(.+)$", stem)
    if not date_match:
        logger.warning("Cannot derive permalink from filename: %s", md_path.name)
        return None

    year, month, day, slug = date_match.groups()
    return f"https://{HOST}/{category}/{year}/{month}/{day}/{slug}/"


def urls_from_recent_posts(n: int, posts_dir: Path) -> list[str]:
    """Return URLs for the most-recent *n* posts sorted by filename (newest first)."""
    posts = sorted(posts_dir.glob("*.md"), reverse=True)[:n]
    urls = []
    for post in posts:
        url = _permalink_from_post(post)
        if url:
            urls.append(url)
    logger.info("Derived %d URL(s) from most-recent %d post(s)", len(urls), len(posts))
    return urls


def urls_from_sitemap(sitemap_source: str) -> list[str]:
    """Parse a sitemap XML (file path or URL) and return all <loc> values."""
    if urlsplit(sitemap_source).scheme in ("http", "https"):
        try:
            with urllib.request.urlopen(
                sitemap_source, timeout=REQUEST_TIMEOUT
            ) as resp:  # scheme allow-listed to http/https above  # nosec B310
                xml_bytes = resp.read()
        except urllib.error.URLError as exc:
            logger.error("Failed to fetch sitemap %s: %s", sitemap_source, exc)
            return []
    else:
        try:
            xml_bytes = Path(sitemap_source).read_bytes()
        except OSError as exc:
            logger.error("Failed to read sitemap %s: %s", sitemap_source, exc)
            return []

    try:
        root = ElementTree.fromstring(xml_bytes)  # sitemap is our own or trusted source  # nosec B314
    except ElementTree.ParseError as exc:
        logger.error("Failed to parse sitemap XML: %s", exc)
        return []

    # Handle namespace
    ns_match = re.match(r"\{([^}]+)\}", root.tag)
    ns = f"{{{ns_match.group(1)}}}" if ns_match else ""
    urls = [loc.text.strip() for loc in root.iter(f"{ns}loc") if loc.text]
    logger.info("Found %d URL(s) in sitemap", len(urls))
    return urls


def urls_from_changed_posts(base_ref: str, posts_dir: Path) -> list[str]:
    """Return URLs for _posts/*.md files changed since *base_ref* via git diff."""
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", base_ref, "HEAD", "--", "_posts/"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            logger.error("git diff failed: %s", result.stderr.strip())
            return []
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        logger.error("git diff error: %s", exc)
        return []

    repo_root = posts_dir.parent
    urls = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line.endswith(".md"):
            continue
        post_path = repo_root / line
        url = _permalink_from_post(post_path)
        if url:
            urls.append(url)
    logger.info("Derived %d URL(s) from changed posts since %s", len(urls), base_ref)
    return urls


# ── CLI ───────────────────────────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Submit URLs to the IndexNow API for immediate indexing by Bing/Yandex.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--key",
        metavar="KEY",
        default="",
        help="IndexNow API key (overrides INDEXNOW_KEY env var and built-in default)",
    )

    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--urls",
        nargs="+",
        metavar="URL",
        help="One or more URLs to submit",
    )
    source.add_argument(
        "--from-recent-posts",
        type=int,
        metavar="N",
        help="Derive URLs from the N most-recent _posts/*.md files",
    )
    source.add_argument(
        "--from-sitemap",
        nargs="?",
        const="",
        metavar="SOURCE",
        help=(
            "Parse sitemap XML. Omit SOURCE to auto-detect (_site/sitemap.xml "
            f"or live https://{HOST}/sitemap.xml). "
            "Pass a path or URL to override."
        ),
    )
    source.add_argument(
        "--from-changed-posts",
        metavar="BASE_REF",
        help="Submit posts changed since BASE_REF (e.g. HEAD~1)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    key = _get_key(args)

    # Locate _posts/ relative to this script's repo root
    repo_root = Path(__file__).resolve().parents[2]
    posts_dir = repo_root / "_posts"

    if args.urls:
        urls = args.urls
    elif args.from_recent_posts is not None:
        urls = urls_from_recent_posts(args.from_recent_posts, posts_dir)
    elif args.from_sitemap is not None:
        if args.from_sitemap:
            source = args.from_sitemap
        else:
            # Auto-detect: prefer local _site/sitemap.xml, fall back to live
            local = repo_root / "_site" / "sitemap.xml"
            source = str(local) if local.exists() else f"https://{HOST}/sitemap.xml"
        urls = urls_from_sitemap(source)
    else:  # --from-changed-posts
        urls = urls_from_changed_posts(args.from_changed_posts, posts_dir)

    ok = submit_urls(urls, key)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
