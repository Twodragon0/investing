"""Regression guards for test-suite working-tree isolation invariants.

These tests fail loudly if a conftest isolation fixture is removed or stops
firing, so integration tests can never silently start polluting the committed
repo tree again.
"""

import os
from pathlib import Path

import common.image_generator as ig

# Test-file-local anchor for the committed repo tree. We deliberately derive the
# path from ``__file__`` instead of importing ``common.image_generator.REPO_ROOT``:
# importing a production real-tree root constant into a test is itself banned by
# ``test_hermetic_test_writes_guard`` (it is the canonical non-hermetic-write
# signal). ``tests/`` lives at the repo root, so its parent is the checkout root.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_REPO_IMAGES = str((_REPO_ROOT / "assets" / "images" / "generated").resolve())


def test_generated_images_redirected_off_repo_tree():
    """``_isolate_generated_images`` must redirect writes off the repo tree.

    Every image_generator save resolves its output dir through
    ``common.image_generator.IMAGES_DIR``. Integration tests (daily summary,
    collectors, briefing cards) that do not patch it themselves rely on the
    autouse fixture to point it at a throwaway tmp dir. If that fixture is
    removed, those tests write PNG/WEBP/AVIF files into the committed
    ``assets/images/generated/`` tree, leaving dirty working-tree side effects.

    Asserting the active dir is not the committed tree turns a silent
    regression into an immediate, obvious failure.
    """
    active = os.path.abspath(ig.IMAGES_DIR)

    assert active != _REPO_IMAGES, (
        "image_generator.IMAGES_DIR points at the committed repo tree during "
        "tests — the _isolate_generated_images conftest fixture is not active. "
        "Image-generating tests will pollute the working tree."
    )
    # The redirect target must also never be nested inside the committed assets
    # tree, or writes would still dirty the working tree.
    assert not active.startswith(_REPO_IMAGES), (
        f"IMAGES_DIR ({active}) is nested inside the committed assets tree; writes would still dirty the working tree."
    )
