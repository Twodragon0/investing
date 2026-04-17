from pathlib import Path

import check_post_images as cpi


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_extract_image_path_reads_front_matter(tmp_path):
    post = tmp_path / "post.md"
    _write_text(
        post,
        """---
title: Demo
image: "/assets/images/generated/og-demo.png"
---
body
""",
    )

    assert cpi.extract_image_path(str(post)) == "/assets/images/generated/og-demo.png"


def test_extract_image_path_returns_none_without_front_matter_match(tmp_path):
    post = tmp_path / "post.md"
    _write_text(post, "title: no front matter\nimage: /assets/demo.png\n")

    assert cpi.extract_image_path(str(post)) is None


def test_check_image_exists_reports_generated_and_thumbnail_variants(tmp_path, monkeypatch):
    repo_root = tmp_path
    monkeypatch.setattr(cpi, "REPO_ROOT", str(repo_root))

    original = repo_root / "assets/images/generated/og-demo.png"
    _write_text(original, "png")

    missing = cpi.check_image_exists("/assets/images/generated/og-demo.png")

    assert set(missing) == {
        "assets/images/generated/og-demo.webp",
        "assets/images/generated/og-demo.avif",
        "assets/images/generated/thumb-og-demo.png",
        "assets/images/generated/thumb-og-demo.webp",
        "assets/images/generated/thumb-og-demo.avif",
    }


def test_check_image_exists_returns_empty_when_all_variants_exist(tmp_path, monkeypatch):
    repo_root = tmp_path
    monkeypatch.setattr(cpi, "REPO_ROOT", str(repo_root))

    for rel_path in (
        "assets/images/generated/og-demo.png",
        "assets/images/generated/og-demo.webp",
        "assets/images/generated/og-demo.avif",
        "assets/images/generated/thumb-og-demo.png",
        "assets/images/generated/thumb-og-demo.webp",
        "assets/images/generated/thumb-og-demo.avif",
    ):
        _write_text(repo_root / rel_path, "asset")

    assert cpi.check_image_exists("/assets/images/generated/og-demo.png") == []


def test_main_returns_zero_when_no_posts_exist(tmp_path, monkeypatch):
    posts_dir = tmp_path / "_posts"
    posts_dir.mkdir()
    monkeypatch.setattr(cpi, "POSTS_DIR", str(posts_dir))
    monkeypatch.setattr(cpi, "REPO_ROOT", str(tmp_path))

    assert cpi.main() == 0


def test_main_reports_missing_images(tmp_path, monkeypatch):
    posts_dir = tmp_path / "_posts"
    monkeypatch.setattr(cpi, "POSTS_DIR", str(posts_dir))
    monkeypatch.setattr(cpi, "REPO_ROOT", str(tmp_path))

    _write_text(
        posts_dir / "2026-04-17-demo.md",
        """---
title: Demo
image: "/assets/images/generated/og-demo.png"
---
body
""",
    )
    _write_text(tmp_path / "assets/images/generated/og-demo.png", "png")

    assert cpi.main() == 1


def test_main_returns_zero_when_all_referenced_images_exist(tmp_path, monkeypatch):
    posts_dir = tmp_path / "_posts"
    monkeypatch.setattr(cpi, "POSTS_DIR", str(posts_dir))
    monkeypatch.setattr(cpi, "REPO_ROOT", str(tmp_path))

    _write_text(
        posts_dir / "2026-04-17-demo.md",
        """---
title: Demo
image: "/assets/images/generated/og-demo.png"
---
body
""",
    )

    for rel_path in (
        "assets/images/generated/og-demo.png",
        "assets/images/generated/og-demo.webp",
        "assets/images/generated/og-demo.avif",
        "assets/images/generated/thumb-og-demo.png",
        "assets/images/generated/thumb-og-demo.webp",
        "assets/images/generated/thumb-og-demo.avif",
    ):
        _write_text(tmp_path / rel_path, "asset")

    assert cpi.main() == 0
