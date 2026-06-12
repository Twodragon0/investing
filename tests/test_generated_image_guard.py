"""Regression test: layout-rendered generated images must never 404.

``cleanup-old-images.yml`` prunes ``assets/images/generated/*`` files older than
30 days (by filename date) and commits the removal, but posts keep referencing
those images forever (front matter ``image:``, hero, related-posts, cards,
journal landings, og:image). The layout templates therefore guard against a
missing file via ``site.static_files`` existence checks:

- ``_includes/generated-picture.html`` — universal guard (renders nothing when
  the generated PNG is gone), protecting every caller.
- ``_layouts/default.html`` — og:image / preload / content-image fallback.
- ``_layouts/post.html`` — hero figure + related-post thumbnail + JSON-LD image.
- ``_includes/post-card.html`` — card thumbnail falls back to the SVG icon.

These tests scan the built ``_site/`` and assert no rendered ``<img>``/``<source>``
or ``og:image`` points at a file that does not exist on disk. Without the guards
~70% of posts (everything older than 30 days) emit broken images.

Requires a built ``_site/`` (run ``bundle exec jekyll build`` first); skips
otherwise so the unit suite stays fast when the site has not been built.
"""

import glob
import os
import re

import pytest

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
SITE_DIR = os.path.join(REPO_ROOT, "_site")

# src="..." or srcset="..." pointing at a generated image (first URL of a srcset)
_IMG_REF = re.compile(r'(?:src|srcset)="(/assets/images/generated/[^"\s]+)')
# absolute og:image meta, capturing the path portion
_OG_REF = re.compile(r'<meta property="og:image" content="https?://[^"]*?(/assets/images/generated/[^"]+)"')


def _exists(rel_url: str) -> bool:
    """True if the site-absolute URL maps to a real file in the repo."""
    return os.path.isfile(os.path.join(REPO_ROOT, rel_url.lstrip("/")))


def _read(page: str) -> str:
    try:
        with open(page, encoding="utf-8", errors="ignore") as fh:
            return fh.read()
    except OSError:
        return ""


@pytest.fixture(scope="module")
def rendered_pages() -> list[str]:
    if not os.path.isdir(SITE_DIR):
        pytest.skip("_site not built; run `bundle exec jekyll build` first")
    pages = glob.glob(os.path.join(SITE_DIR, "**", "*.html"), recursive=True)
    if not pages:
        pytest.skip("_site has no rendered HTML; build incomplete")
    return pages


def test_no_broken_generated_img(rendered_pages: list[str]) -> None:
    """No rendered <img>/<source> may reference a pruned generated image."""
    broken: list[tuple[str, str]] = []
    for page in rendered_pages:
        html = _read(page)
        if "/assets/images/generated/" not in html:
            continue
        for match in _IMG_REF.finditer(html):
            url = match.group(1)
            if not _exists(url):
                broken.append((os.path.relpath(page, SITE_DIR), url))

    assert not broken, (
        f"{len(broken)} rendered <img>/<source> point at missing generated "
        "images (layout guard regression): " + "; ".join(f"{page} -> {url}" for page, url in broken[:10])
    )


def test_no_broken_og_image(rendered_pages: list[str]) -> None:
    """No page's og:image may reference a pruned generated image."""
    broken: list[tuple[str, str]] = []
    for page in rendered_pages:
        html = _read(page)
        match = _OG_REF.search(html)
        if match and not _exists(match.group(1)):
            broken.append((os.path.relpath(page, SITE_DIR), match.group(1)))

    assert not broken, (
        f"{len(broken)} pages have an og:image pointing at a missing generated "
        "image (default.html guard regression): " + "; ".join(f"{page} -> {url}" for page, url in broken[:10])
    )
