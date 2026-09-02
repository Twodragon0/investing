"""Record the posts a run actually created.

`.github/actions/python-collect` used to answer "which posts are new?" with
``find _posts/ -name "*.md" -newer /tmp/collect-start-marker``. That returns every
file whose mtime changed, not every file that was created — so a script that only
rewrites existing posts (``backfill_post_summaries.py``, ``backfill_images.py``,
``improve_existing_posts.py``) made past posts look new.

The consequence was concrete: on 2026-09-01 ``backfill_post_summaries.py``
rewrote ``_posts/2026-08-27-daily-geopolitical-risk-report.md``; the action then
fed it to ``improve_existing_posts.py``, which reverted PR #1259's excerpt
backfill (commit ``6880034f5``) and left main failing ``check_post_summary``.

This module moves the question from the filesystem to the code that creates
posts. Only ``PostGenerator.create_post`` and the one script that bypasses it
(``generate_daily_summary.py``) record here, so modifier scripts drop out of
downstream processing without an opt-out flag anyone could forget.

Recording is opt-in via ``CREATED_POSTS_MANIFEST``: unset means no-op, which
keeps local runs and the test suite from writing files.
"""

from __future__ import annotations

import logging
import os
from typing import List

logger = logging.getLogger(__name__)

__all__ = ["MANIFEST_ENV_VAR", "manifest_path", "read_manifest", "record_created_post"]

MANIFEST_ENV_VAR = "CREATED_POSTS_MANIFEST"


def manifest_path() -> str:
    """Return the configured manifest path, or ``""`` when recording is off."""
    return (os.environ.get(MANIFEST_ENV_VAR) or "").strip()


def record_created_post(filepath: str) -> None:
    """Append ``filepath`` to the manifest when one is configured.

    Failures are swallowed: a bookkeeping file must never take down a collection
    run. They are logged at warning level rather than debug — a silently empty
    manifest would make every downstream step a no-op while the job stays green,
    which is the failure mode this module exists to remove.
    """
    path = manifest_path()
    if not path or not filepath:
        return
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"{filepath}\n")
    except OSError as exc:  # noqa: BLE001 - bookkeeping must not break collection
        logger.warning("created-post manifest write failed (%s): %s", path, exc)


def read_manifest() -> List[str]:
    """Return the recorded paths, or ``[]`` when there is no manifest."""
    path = manifest_path()
    if not path:
        return []
    try:
        with open(path, encoding="utf-8") as fh:
            return [line.strip() for line in fh if line.strip()]
    except OSError:
        return []
