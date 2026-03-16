#!/usr/bin/env python3

import sys
from pathlib import Path

from bs4 import BeautifulSoup

EXPECTED_TABS = [
    "all",
    "crypto",
    "stock",
    "analysis",
    "regulatory",
    "social",
    "blockchain",
    "security",
    "political",
]

EXPECTED_CARD_PATHS = [
    "/crypto-news/",
    "/stock-news/",
    "/crypto-journal/",
    "/stock-journal/",
    "/security-alerts/",
    "/market-analysis/",
    "/regulatory-news/",
    "/political-trades/",
    "/social-media/",
    "/blockchain/",
]


def _read_soup(path: Path) -> BeautifulSoup:
    return BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def check_home(site_dir: Path) -> None:
    home = _read_soup(site_dir / "index.html")
    tabs = [node.get("data-category") for node in home.select(".posts-tab")]
    _assert(tabs == EXPECTED_TABS, f"unexpected home tabs: {tabs}")

    card_links = [node.get("href") for node in home.select(".category-grid-v2 .cat-card")]
    _assert(card_links == EXPECTED_CARD_PATHS, f"unexpected home card links: {card_links}")

    script_text = "\n".join(node.get_text() for node in home.select("script"))
    _assert("currentCategory" in script_text, "home script missing currentCategory controller")
    _assert("updateVisibility" in script_text, "home script missing updateVisibility")
    _assert(home.select_one("#posts-container") is not None, "home missing posts container")
    _assert(home.select_one("#load-more-btn") is not None, "home missing load more button")


def check_category(site_dir: Path, slug: str) -> None:
    page = _read_soup(site_dir / slug / "index.html")
    _assert(page.select_one("#category-filter") is not None, f"{slug} missing category filter")
    _assert(page.select_one("#posts-list") is not None, f"{slug} missing posts list")
    script_text = "\n".join(node.get_text() for node in page.select("script"))
    _assert("updateDateDividers" in script_text, f"{slug} missing date divider script")
    _assert("load-more-btn" in script_text, f"{slug} missing load more behavior")


def main() -> int:
    site_dir = Path("_site")
    _assert(site_dir.exists(), "_site directory not found; run Jekyll build first")
    check_home(site_dir)
    check_category(site_dir, "blockchain")
    print("Rendered page smoke tests passed.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from None
