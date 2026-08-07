"""CI config regression guard: every action pin carries a truthful version label.

`test_workflow_action_pinning_guard.py` proves each external `uses:` is pinned to
a 40-hex SHA. A SHA alone is reproducible but unreadable — the trailing
`# vX.Y` comment is the only version signal a reviewer, or Dependabot's PR
description, has to reason about. If it drifts from the SHA, everyone downstream
reasons about the wrong action: the wrong changelog, the wrong CVE list, the
wrong breaking changes.

It had drifted. When this guard was written three pins were mislabeled:

| ref | label | actually |
|---|---|---|
| `actions/checkout@de0fac2e` | `# v4` | v6.0.2 |
| `actions/github-script@3a2844b7` | `# v7` | v9.0.0 |
| `stefanzweifel/git-auto-commit-action@04702edd` | `# v5` | v7.1.0 |

## Division of labour with the online verifier

Proving a label matches upstream needs the network, and `tests/conftest.py`
blocks outbound HTTP for the whole suite on purpose (see
`reference_ci_network_not_isolated_http_guard`). So the authoritative comparison
lives in `scripts/tools/verify_action_pins.py`, run by
`.github/workflows/action-pin-verify.yml`.

What is left for a *blocking* offline test is everything derivable from the repo
alone, and that turns out to include two of the three real defects above:

* a label must exist at all, and be version-shaped — otherwise there is nothing
  for the online verifier to compare against (presence);
* one SHA must not carry two contradictory labels — `# v4` and `# v6` on the same
  40 hex characters means at least one is a lie, provable without any network
  (internal consistency);
* one claimed version must not map to two different SHAs — that is a half-applied
  bump, where some workflows moved and others silently did not.

The third defect (`# v5` on a v7.1.0 SHA, appearing exactly once) is only
detectable upstream; that is precisely why the online job exists too.

Deliberately self-contained: this test does **not** import
`scripts/tools/verify_action_pins.py`. That module defines `REPO_ROOT`, and
importing production path anchors into a test trips
`test_hermetic_test_writes_guard.py`; it would also fold a tool into the coverage
measurement this guard has no business moving. Text scan only, per
`docs/devsecops/ci-regression-guards.md`.
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_WORKFLOWS_DIR = _REPO_ROOT / ".github" / "workflows"
_ACTIONS_DIR = _REPO_ROOT / ".github" / "actions"

# Canary floor: 20+ distinct external pins existed when this guard was written.
_MIN_PINS = 15

# `uses: owner/repo[/sub/path]@<40-hex>` plus an optional `# label`. The label
# group stays optional on purpose — a missing label is a finding, not a
# non-match, so it must reach the assertion rather than be skipped by the regex.
_PIN_RE = re.compile(
    r"^\s*(?:-\s+)?uses:\s*(?P<ref>[^@\s'\"]+)@(?P<sha>[0-9a-f]{40})(?P<tail>[^\n]*)",
    re.M,
)
_LABEL_RE = re.compile(r"#\s*(?P<label>\S+)")

# `v1`, `v6.0.2`, `1.302.0`. Anything else (`# latest`, `# pinned`, `# TODO`)
# would satisfy "a label exists" while carrying no comparable version.
_VERSION_SHAPED_RE = re.compile(r"^v?\d+(\.\d+)*$")


def _yaml_sources() -> list[Path]:
    return sorted(_WORKFLOWS_DIR.glob("*.yml")) + sorted(_ACTIONS_DIR.glob("*/action.yml"))


def _pins() -> list[tuple[Path, str, str, str | None]]:
    """`(file, ref, sha, label)` for every external SHA-pinned reference."""
    found: list[tuple[Path, str, str, str | None]] = []
    for path in _yaml_sources():
        for match in _PIN_RE.finditer(path.read_text(encoding="utf-8")):
            ref = match.group("ref")
            if ref.startswith("./"):
                continue
            label_match = _LABEL_RE.search(match.group("tail"))
            found.append((path, ref, match.group("sha"), label_match.group("label") if label_match else None))
    return found


def _repo_of(ref: str) -> str:
    """`actions/cache/restore` -> `actions/cache`: sub-path actions share a repo."""
    return "/".join(ref.split("/")[:2])


def _version_parts(label: str) -> tuple[int, ...] | None:
    stripped = label[1:] if label.startswith(("v", "V")) else label
    if not re.fullmatch(r"\d+(\.\d+)*", stripped or ""):
        return None
    return tuple(int(part) for part in stripped.split("."))


def labels_compatible(left: str, right: str) -> bool:
    """True when one label is the same version as, or a refinement of, the other.

    `v5` / `v5.0.5` -> True: a floating major and a concrete patch inside it can
    legitimately describe one SHA.
    `v4` / `v6` -> False: no SHA is both.
    """
    if left == right:
        return True
    a, b = _version_parts(left), _version_parts(right)
    if a is None or b is None:
        return False
    shorter, longer = sorted((a, b), key=len)
    return longer[: len(shorter)] == shorter


def test_workflow_sources_exist() -> None:
    """Canary: a moved workflow tree fails loudly instead of vacuously."""
    assert _WORKFLOWS_DIR.is_dir(), f"{_WORKFLOWS_DIR} not found"
    assert _yaml_sources(), "no workflow or composite-action YAML found — the glob no longer matches."


def test_pin_count_is_plausible() -> None:
    """Canary: a broken regex must not turn the assertions below into no-ops."""
    pins = _pins()
    assert len(pins) >= _MIN_PINS, (
        f"only {len(pins)} SHA-pinned references found (expected >= {_MIN_PINS}). "
        "Fix the parser before trusting this guard."
    )


def test_every_pin_carries_a_version_label() -> None:
    """Presence: a pin with no `# vX.Y` comment has nothing to verify against."""
    unlabeled = sorted(
        {f"{path.relative_to(_REPO_ROOT)}: {ref}@{sha[:8]}" for path, ref, sha, label in _pins() if label is None}
    )
    assert not unlabeled, (
        "action pin(s) missing a trailing version comment:\n"
        + "\n".join(f"  - {entry}" for entry in unlabeled)
        + "\n\nWrite `uses: owner/repo@<sha>  # vX.Y.Z`. Without the label a reader "
        "cannot tell which version runs, and scripts/tools/verify_action_pins.py "
        "has nothing to compare the SHA against."
    )


def test_version_labels_are_version_shaped() -> None:
    """Presence: `# latest` / `# pinned` would satisfy the label check vacuously."""
    malformed = sorted(
        {
            f"{path.relative_to(_REPO_ROOT)}: {ref} # {label}"
            for path, ref, _sha, label in _pins()
            if label is not None and not _VERSION_SHAPED_RE.match(label)
        }
    )
    assert not malformed, (
        "action pin label(s) are not version-shaped:\n"
        + "\n".join(f"  - {entry}" for entry in malformed)
        + "\n\nUse the upstream tag (`v6`, `v6.0.2`). If an action genuinely ships "
        "non-semver tags, widen _VERSION_SHAPED_RE and say why in this docstring."
    )


def test_one_sha_never_carries_contradictory_labels() -> None:
    """Internal consistency: `# v4` and `# v6` on one SHA means one of them lies.

    Network-free, and it caught two of the three real mislabels this guard was
    written for.
    """
    by_sha: dict[tuple[str, str], set[str]] = defaultdict(set)
    for _path, ref, sha, label in _pins():
        if label is not None:
            by_sha[(_repo_of(ref), sha)].add(label)

    conflicts = [
        f"{repo}@{sha[:8]} labeled {sorted(labels)}"
        for (repo, sha), labels in sorted(by_sha.items())
        if not all(labels_compatible(a, b) for a in labels for b in labels)
    ]
    assert not conflicts, (
        "the same SHA is labeled with incompatible versions:\n"
        + "\n".join(f"  - {entry}" for entry in conflicts)
        + "\n\nOne label is wrong. Resolve the SHA upstream "
        "(`gh api repos/<owner>/<repo>/tags --jq '.[]|select(.commit.sha==\"<sha>\")|.name'`) "
        "and correct every occurrence to the real tag."
    )


def test_one_claimed_version_never_maps_to_two_shas() -> None:
    """Internal consistency: a half-applied bump leaves one version on two SHAs."""
    by_label: dict[tuple[str, str], set[str]] = defaultdict(set)
    for _path, ref, sha, label in _pins():
        if label is not None:
            by_label[(_repo_of(ref), label)].add(sha)

    split = [
        f"{repo} # {label} -> {sorted(sha[:8] for sha in shas)}"
        for (repo, label), shas in sorted(by_label.items())
        if len(shas) > 1
    ]
    assert not split, (
        "one claimed version maps to multiple SHAs:\n"
        + "\n".join(f"  - {entry}" for entry in split)
        + "\n\nA version bump was applied to some workflows but not others. Move "
        "every occurrence to the same SHA, or label them with the versions they "
        "actually are."
    )


def test_label_comparison_is_bidirectional() -> None:
    """The comparator must accept refinements and reject genuine conflicts.

    A `labels_compatible` loosened to `return True` would leave the consistency
    assertions permanently green, so both directions are pinned here.
    """
    for left, right in (("v5", "v5"), ("v5", "v5.0.5"), ("v5.0.5", "v5"), ("v1.302.0", "v1.302.0"), ("v9", "v9.0.0")):
        assert labels_compatible(left, right), f"comparator rejects compatible pair {left}/{right}"

    for left, right in (("v4", "v6"), ("v7", "v9.0.0"), ("v5", "v7.1.0"), ("v4.6.2", "v4.7.1"), ("v1", "v10")):
        assert not labels_compatible(left, right), f"comparator accepts contradictory pair {left}/{right}"

    assert _version_parts("latest") is None, "non-numeric label must not parse as a version"
    assert not labels_compatible("latest", "v1"), "non-numeric label must not match a version"
