#!/usr/bin/env python3
"""Validate URL quality for recent posts.

Checks URL format and performs lightweight reachability checks for links
appearing in recent posts (today and yesterday by default).
"""

from __future__ import annotations

import argparse
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

import requests

URL_PATTERN = re.compile(r"https?://[^\s)\]\"'>]+")


def collect_post_files(posts_dir: Path, days: int) -> list[Path]:
    today = datetime.now(timezone.utc).date()  # noqa: UP017
    targets = {str(today - timedelta(days=delta)) for delta in range(days)}
    return sorted(path for path in posts_dir.glob("*.md") if path.name[:10] in targets)


def extract_urls(paths: Iterable[Path]) -> list[str]:
    seen: set[str] = set()
    urls: list[str] = []
    for path in paths:
        text = path.read_text(encoding="utf-8", errors="ignore")
        for url in URL_PATTERN.findall(text):
            if url not in seen:
                seen.add(url)
                urls.append(url)
    return urls


def valid_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def check_url(url: str, timeout: float) -> tuple[int | None, str | None]:
    try:
        response = requests.head(url, timeout=timeout, allow_redirects=True)
        status = response.status_code
        if status >= 500 or status in {403, 405}:
            response = requests.get(url, timeout=timeout, allow_redirects=True)
            status = response.status_code
        if status >= 500:
            return status, "server_error"
        return status, None
    except requests.RequestException as exc:
        return None, str(exc)


def main() -> int:
    parser = argparse.ArgumentParser(description="Check recent post URL quality")
    parser.add_argument("--posts-dir", default="_posts")
    parser.add_argument("--days", type=int, default=2)
    parser.add_argument("--limit", type=int, default=60)
    parser.add_argument("--timeout", type=float, default=8.0)
    parser.add_argument("--report", default="_state/recent-url-quality.txt")
    args = parser.parse_args()

    posts_dir = Path(args.posts_dir)
    files = collect_post_files(posts_dir, max(args.days, 1))
    urls = extract_urls(files)
    invalid = [url for url in urls if not valid_url(url)]

    failures: list[tuple[str, int | None, str]] = []
    checked = 0
    for url in urls[: max(args.limit, 1)]:
        status, reason = check_url(url, args.timeout)
        checked += 1
        if reason is not None:
            failures.append((url, status, reason))

    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"posts_checked={len(files)}",
        f"unique_urls={len(urls)}",
        f"invalid_format={len(invalid)}",
        f"live_checked={checked}",
        f"live_failures={len(failures)}",
    ]
    if invalid:
        lines.append("[invalid]")
        lines.extend(invalid[:30])
    if failures:
        lines.append("[failures]")
        lines.extend(
            f"{status if status is not None else 'ERR'}\t{reason[:140]}\t{url}" for url, status, reason in failures[:50]
        )
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("URL quality summary")
    for line in lines[:5]:
        print(f"- {line}")
    if invalid or failures:
        print(f"- report={report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
