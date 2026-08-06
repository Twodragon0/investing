"""CI config regression guard: every external GitHub Action stays SHA-pinned.

A `uses:` reference resolved by tag (`@v4`) or branch (`@main`) is a mutable
pointer: whoever controls the upstream repo can move it to new code that runs
inside this repo's CI with the job's `GITHUB_TOKEN`. Pinning to a full 40-hex
commit SHA is what makes the dependency reproducible and reviewable — Dependabot
still bumps the SHA, but the bump lands as a reviewable diff.

Every one of this repo's external references is already SHA-pinned; this guard
locks that state in. Direction: presence — adding a SHA-pinned action stays
green, only an unpinned (tag/branch) reference trips it.

## Why a *test* and not the workflow audit

`.github/workflows/security-scan.yml` has an `actions-permissions` job that
greps for unpinned actions, but it cannot fail a build:

* it never exits non-zero — every finding is an `::warning::` annotation;
* its `has_issues=true` for the pinning check runs inside a `grep ... | while`
  pipeline, i.e. a subshell, so the assignment cannot even escape;
* `grep -v '@v'` treats `@v4` — a mutable tag, the exact thing at issue — as
  pinned, and `grep -v '#'` skips any line carrying a trailing comment.

So before this guard the pinning invariant had zero enforcement. Anything under
`tests/` runs in the blocking Code Quality pytest job.

Text scan only (no PyYAML, no import of workflow tooling) per the guard
conventions in `docs/devsecops/ci-regression-guards.md`.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_WORKFLOWS_DIR = _REPO_ROOT / ".github" / "workflows"
_ACTIONS_DIR = _REPO_ROOT / ".github" / "actions"

# Canary floor: the repo had 60+ external references when this guard was
# written. A glob that silently stops matching would otherwise pass vacuously.
_MIN_EXTERNAL_REFS = 20

# Anchored at the start of a YAML key so shell text that merely mentions
# `uses:` (security-scan.yml greps for it) is not mistaken for a reference.
_USES_RE = re.compile(r"^\s*(?:-\s+)?uses:\s*(?P<ref>\S+)", re.M)

# `owner/repo@<40 hex>` or `owner/repo/sub/path@<40 hex>`.
_SHA_PINNED_RE = re.compile(r"^[^@\s]+@[0-9a-f]{40}$")


def _yaml_sources() -> list[Path]:
    """Workflow definitions plus composite action definitions."""
    return sorted(_WORKFLOWS_DIR.glob("*.yml")) + sorted(_ACTIONS_DIR.glob("*/action.yml"))


def _external_refs() -> list[tuple[Path, str]]:
    """`(file, ref)` for every `uses:` that points outside this repo.

    Local references (`./.github/actions/x`, `./.github/workflows/y.yml`) are
    checked out with the calling commit, so they carry no upstream mutability.
    """
    refs: list[tuple[Path, str]] = []
    for path in _yaml_sources():
        for match in _USES_RE.finditer(path.read_text(encoding="utf-8")):
            ref = match.group("ref").strip("'\"")
            if ref.startswith("./"):
                continue
            refs.append((path, ref))
    return refs


def test_workflow_sources_exist() -> None:
    """Canary: a moved/renamed workflow tree fails loudly instead of vacuously."""
    assert _WORKFLOWS_DIR.is_dir(), f"{_WORKFLOWS_DIR} not found"
    assert _ACTIONS_DIR.is_dir(), f"{_ACTIONS_DIR} not found"
    assert _yaml_sources(), "no workflow or composite-action YAML found — the glob no longer matches anything."


def test_external_action_reference_count_is_plausible() -> None:
    """Canary: the scan must still see the bulk of the references.

    Without this, a regex that stops matching turns the pinning assertion below
    into a check over an empty list — green, and proving nothing.
    """
    refs = _external_refs()
    assert len(refs) >= _MIN_EXTERNAL_REFS, (
        f"only {len(refs)} external `uses:` references found (expected "
        f">= {_MIN_EXTERNAL_REFS}). The scanner is likely broken rather than the "
        f"repo having shrunk; fix the parser before trusting this guard."
    )


def test_all_external_actions_are_sha_pinned() -> None:
    """Every external action must be pinned to a full 40-hex commit SHA.

    Tags and branches are mutable: `@v4` today and `@v4` after an upstream
    compromise are different code with the same name.
    """
    unpinned = sorted(
        {f"{path.relative_to(_REPO_ROOT)}: {ref}" for path, ref in _external_refs() if not _SHA_PINNED_RE.match(ref)}
    )
    assert not unpinned, (
        "external action(s) not pinned to a full commit SHA:\n"
        + "\n".join(f"  - {entry}" for entry in unpinned)
        + "\n\nPin with `uses: owner/repo@<40-hex-sha>  # vX.Y` — a tag or branch "
        "lets upstream change what runs in CI without a diff here."
    )


def test_pinning_detector_rejects_mutable_refs() -> None:
    """The detector itself must classify mutable refs as unpinned.

    A `_SHA_PINNED_RE` loosened to accept `@v4` would leave the assertion above
    permanently green. Both directions are pinned here so the detector cannot
    rot into a no-op.
    """
    pinned = "actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd"
    assert _SHA_PINNED_RE.match(pinned), "detector rejects a legitimately SHA-pinned ref"
    assert _SHA_PINNED_RE.match("github/codeql-action/upload-sarif@" + "0" * 40), (
        "detector rejects a SHA-pinned sub-path action"
    )

    for mutable in (
        "actions/checkout@v6",
        "actions/checkout@main",
        "actions/checkout@de0fac2",  # abbreviated SHA — still ambiguous
        "actions/checkout",  # no ref at all -> default branch
        "actions/checkout@DE0FAC2E4500DABE0009E67214FF5F5447CE83DD",  # not lowercase hex
    ):
        assert not _SHA_PINNED_RE.match(mutable), f"detector accepts mutable ref {mutable!r} as pinned"
