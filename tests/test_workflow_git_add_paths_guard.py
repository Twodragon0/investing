"""CI config regression guard: collector workflows committing posts must include assets/images.

## Background

`.github/actions/python-collect/action.yml` runs `scripts/generate_og_images.py`
for all newly generated posts. That script creates OG image files in
`assets/images/generated/` and updates the post front matter `image:` field to point
to the generated image path.

If a collector workflow specifies `git-add-paths: '_posts/ _state/'` without
`assets/images/`, git only stages `_posts/` and `_state/`. As a result:
1. The post is committed with `image: /assets/images/generated/...`
2. The image file itself is NOT committed to git.
3. On the next push, `.github/workflows/check-post-images.yml` detects the missing
   image file and fails with exit code 1.

This incident occurred on 2026-10-13 when `collect-blockchain.yml` omitted
`assets/images/` in its `git-add-paths`.

This guard statically ensures that every workflow using `python-collect` to commit
`_posts/` also stages `assets/images/`.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_WORKFLOWS_DIR = _REPO_ROOT / ".github" / "workflows"

# Extracts git-add-paths values under python-collect steps
_GIT_ADD_PATHS_RE = re.compile(
    r"uses:\s*\./\.github/actions/python-collect.*?git-add-paths:\s*['\"](?P<paths>[^'\"]+)['\"]",
    re.DOTALL,
)


def _extract_git_add_paths(workflow_path: Path) -> list[str]:
    """Extract git-add-paths values from all python-collect steps in a workflow."""
    text = workflow_path.read_text(encoding="utf-8")
    paths_list = []
    for match in _GIT_ADD_PATHS_RE.finditer(text):
        paths_list.append(match.group("paths"))
    return paths_list


def _has_image_path(paths_str: str) -> bool:
    """Check if git-add-paths includes assets/images."""
    paths = paths_str.split()
    return any(p.startswith("assets/images") for p in paths)


def _has_posts_path(paths_str: str) -> bool:
    """Check if git-add-paths includes _posts/."""
    paths = paths_str.split()
    return any(p.startswith("_posts") for p in paths)


def test_workflows_dir_exists() -> None:
    """Canary: workflows directory exists and contains yaml files."""
    assert _WORKFLOWS_DIR.is_dir(), f"{_WORKFLOWS_DIR} not found"
    workflows = list(_WORKFLOWS_DIR.glob("*.yml"))
    assert len(workflows) >= 20, f"Expected >= 20 workflows, found {len(workflows)}"


def test_collector_workflows_include_image_paths() -> None:
    """All 13 collect-*.yml workflows must include assets/images/ in git-add-paths."""
    collect_workflows = sorted(_WORKFLOWS_DIR.glob("collect-*.yml"))
    assert len(collect_workflows) >= 12, f"Found only {len(collect_workflows)} collect-*.yml workflows, expected >= 12"

    missing_image_paths: list[str] = []
    for wf in collect_workflows:
        paths_list = _extract_git_add_paths(wf)
        for paths_str in paths_list:
            if _has_posts_path(paths_str) and not _has_image_path(paths_str):
                missing_image_paths.append(f"{wf.name}: git-add-paths='{paths_str}'")

    assert not missing_image_paths, (
        "Collector workflows omit assets/images in git-add-paths:\n"
        + "\n".join(missing_image_paths)
        + "\nWhen python-collect commits new posts, it generates OG images into "
        "assets/images/generated/. If assets/images is not staged, check-post-images fails."
    )


def test_generator_workflows_include_image_paths() -> None:
    """generate-daily-summary.yml and weekly-digest.yml must include assets/images/."""
    for wf_name in ("generate-daily-summary.yml", "weekly-digest.yml"):
        wf = _WORKFLOWS_DIR / wf_name
        assert wf.is_file(), f"{wf_name} not found"
        paths_list = _extract_git_add_paths(wf)
        assert paths_list, f"No python-collect step found in {wf_name}"
        for paths_str in paths_list:
            if _has_posts_path(paths_str):
                assert _has_image_path(paths_str), (
                    f"{wf_name} commits posts but omits assets/images in git-add-paths: {paths_str!r}"
                )


def test_detector_correctness() -> None:
    """Unit test for path helper functions."""
    assert _has_posts_path("_posts/ _state/")
    assert not _has_image_path("_posts/ _state/")

    assert _has_posts_path("_posts/ _state/ assets/images/")
    assert _has_image_path("_posts/ _state/ assets/images/")

    assert _has_posts_path("_posts/ assets/images/generated/")
    assert _has_image_path("_posts/ assets/images/generated/")

    assert not _has_posts_path("_state/ only")
    assert not _has_image_path("_state/ only")
