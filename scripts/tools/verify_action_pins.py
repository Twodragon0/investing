#!/usr/bin/env python3
"""Verify every SHA-pinned GitHub Action really *is* the version its comment claims.

## The blind spot this closes

`tests/test_workflow_action_pinning_guard.py` proves every external `uses:` is
pinned to a 40-hex SHA, and `tests/test_workflow_action_version_label_guard.py`
proves each pin carries a `# vX.Y` label and that two labels for the same SHA
never contradict each other. Both are **offline** checks: neither can tell
whether the SHA actually belongs to the claimed version. Only upstream knows.

That gap is not theoretical. When this tool was written it found three pins whose
labels were false:

| ref | label | actual |
|---|---|---|
| `actions/checkout@de0fac2e` | `# v4` | v6.0.2 |
| `actions/github-script@3a2844b7` | `# v7` | v9.0.0 |
| `stefanzweifel/git-auto-commit-action@04702edd` | `# v5` | v7.1.0 |

The label is the only human-readable version signal in a workflow — a reviewer
reading `# v5` on a v7.1.0 pin reasons about the wrong action's behaviour,
changelog, and CVEs. The SHA pin keeps CI *reproducible*; the label is what keeps
it *reviewable*.

## Not everything that differs is wrong

A floating major tag moves. `actions/cache/restore@27d5ce7f  # v5` is pinned to
what `v5` meant when Dependabot last bumped it (v5.0.5); `v5` upstream has since
advanced. That is normal lag, not a false label — so this tool compares against
the *immutable* tag the SHA belongs to, not against wherever the floating tag
currently points, and accepts any tag whose version is a component-wise extension
of the label (`v5` ⊇ `v5.0.5`).

Two pin forms are both legitimate and both handled:

* **commit SHA** — the usual case. Resolved by scanning immutable tags whose name
  extends the label (`GET /git/matching-refs/tags/<label>`) and dereferencing
  each to its commit.
* **annotated tag-object SHA** — e.g. `github/codeql-action/upload-sarif@256d6340`
  is the `v4` *tag object*, not a commit. Tag objects are content-addressed, so
  this is every bit as immutable as a commit pin. `GET /git/tags/<sha>` names it
  directly, which is why that lookup runs first.

## Usage

    python scripts/tools/verify_action_pins.py
    python scripts/tools/verify_action_pins.py --allow-unverified

Set `GITHUB_TOKEN` (or `GH_TOKEN`) to lift the 60 req/h anonymous rate limit.
Exit 0 when every pin verifies, 1 on any MISMATCH (and on UNVERIFIED unless
`--allow-unverified`).

stdlib-only on purpose: the CI job needs no `pip install` step, so a dependency
resolution failure can never turn this supply-chain check green-by-skipping.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "common"))
from config import setup_logging  # noqa: E402

logger = setup_logging("verify_action_pins")

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"
ACTIONS_DIR = REPO_ROOT / ".github" / "actions"

API_ROOT = "https://api.github.com"
REQUEST_TIMEOUT = 15  # scripts/common/config.py convention

# `uses: owner/repo[/sub/path]@<40-hex>` optionally followed by a `# version`
# comment. Anchored at the YAML key so prose mentioning `uses:` is not matched.
_PIN_RE = re.compile(
    r"^\s*(?:-\s+)?uses:\s*(?P<ref>[^@\s'\"]+)@(?P<sha>[0-9a-f]{40})(?:\s*#\s*(?P<label>\S+))?",
    re.M,
)


@dataclass(frozen=True)
class Pin:
    """One deduplicated `owner/repo[/path]@sha  # label` reference."""

    ref: str  # full path incl. sub-action, e.g. actions/cache/restore
    sha: str
    label: str | None

    @property
    def repo(self) -> str:
        """`owner/repo` — the API-addressable part of a sub-path action."""
        return "/".join(self.ref.split("/")[:2])


def collect_pins() -> list[Pin]:
    """Every distinct SHA-pinned external reference across workflows and actions."""
    sources = sorted(WORKFLOWS_DIR.glob("*.yml")) + sorted(ACTIONS_DIR.glob("*/action.yml"))
    pins: set[Pin] = set()
    for path in sources:
        for match in _PIN_RE.finditer(path.read_text(encoding="utf-8")):
            ref = match.group("ref")
            if ref.startswith("./"):
                continue  # local action — checked out with the calling commit
            pins.add(Pin(ref=ref, sha=match.group("sha"), label=match.group("label")))
    return sorted(pins, key=lambda p: (p.ref, p.label or "", p.sha))


def _segment(value: str) -> str:
    """Percent-encode a path segment taken from workflow YAML.

    `repo` and `label` come out of files on disk, so they reach the URL as
    attacker-influenced-in-principle input. Encoding stops a `?` or `/` in a
    version comment from splicing on a query string or an extra path segment.

    It does *not* stop `..` — dots are unreserved, so `quote` leaves them
    untouched. Traversal is rejected in `_api` instead.
    """
    return urllib.parse.quote(value, safe="")


def _repo_path(repo: str) -> str:
    """`owner/name` with each half encoded independently, so the `/` survives."""
    return "/".join(_segment(part) for part in repo.split("/"))


def _api(path: str) -> object | None:
    """GET a GitHub API path. `None` on 404/422 (absent object), raises otherwise."""
    url = f"{API_ROOT}{path}"
    parsed = urllib.parse.urlparse(url)
    # `hostname`, not a substring check: `https://api.github.com@evil.example.com`
    # and `https://api.github.com.evil.com` both contain the literal host.
    if parsed.scheme != "https" or parsed.hostname != "api.github.com":
        raise ValueError(f"refusing to fetch off-host URL: {url}")
    if ".." in parsed.path.split("/"):
        raise ValueError(f"refusing to fetch traversing path: {url}")

    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "investing-verify-action-pins",
        },
    )
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        # Scheme and host are asserted above and every interpolated segment is
        # percent-encoded, so no `file:`/custom-scheme path reaches urlopen.
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:  # noqa: S310  # nosec B310
            return json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code in (404, 422):
            return None
        raise


def version_parts(label: str) -> tuple[int, ...] | None:
    """`v5.0.5` -> `(5, 0, 5)`. `None` for tags that are not dotted numerics."""
    stripped = label[1:] if label.startswith(("v", "V")) else label
    if not stripped or not re.fullmatch(r"\d+(\.\d+)*", stripped):
        return None
    return tuple(int(part) for part in stripped.split("."))


def labels_compatible(label: str, actual: str) -> bool:
    """True when `actual` is the same version as `label`, or a refinement of it.

    `v5` vs `v5.0.5` -> True (a floating major pinned at a concrete patch).
    `v4` vs `v6.0.2` -> False (different major — the label lies).
    Non-numeric tags (`codeql-bundle-...`) compare exactly.
    """
    if label == actual:
        return True
    left, right = version_parts(label), version_parts(actual)
    if left is None or right is None:
        return False
    shorter, longer = sorted((left, right), key=len)
    return longer[: len(shorter)] == shorter


def _deref_to_commit(repo: str, sha: str, obj_type: str) -> str | None:
    """Resolve a ref target to a commit SHA, unwrapping one annotated-tag layer."""
    if obj_type == "commit":
        return sha
    tag = _api(f"/repos/{_repo_path(repo)}/git/tags/{_segment(sha)}")
    if isinstance(tag, dict):
        return (tag.get("object") or {}).get("sha")
    return None


def resolve_tag_names(pin: Pin) -> list[str]:
    """Immutable tag name(s) the pinned SHA belongs to, best-effort.

    Two lookups, cheapest and most authoritative first:

    1. the SHA *is* an annotated tag object -> that tag's own name;
    2. the SHA is a commit -> any tag whose name extends the label and
       dereferences to it. Scoped by `matching-refs` to keep the call count
       bounded on repos with thousands of tags (`github/codeql-action`).
    """
    tag_object = _api(f"/repos/{_repo_path(pin.repo)}/git/tags/{_segment(pin.sha)}")
    if isinstance(tag_object, dict) and tag_object.get("tag"):
        return [str(tag_object["tag"])]

    if pin.label is None:
        return []

    refs = _api(f"/repos/{_repo_path(pin.repo)}/git/matching-refs/tags/{_segment(pin.label)}")
    if not isinstance(refs, list):
        return []
    names: list[str] = []
    for ref in refs:
        obj = (ref or {}).get("object") or {}
        name = str(ref.get("ref", "")).removeprefix("refs/tags/")
        if not name:
            continue
        if obj.get("sha") == pin.sha:  # pinned directly at the tag object
            names.append(name)
            continue
        if _deref_to_commit(pin.repo, str(obj.get("sha")), str(obj.get("type"))) == pin.sha:
            names.append(name)
    return names


# Reverse lookup scans the most recent tags only. Enough to name a stale label
# (`v7` on a v9 SHA) without paginating thousands of tags on github/codeql-action.
_REVERSE_LOOKUP_PAGES = 3


def reverse_lookup_tags(pin: Pin) -> list[str]:
    """Tag name(s) pointing at the pinned SHA, searched *without* the label as a hint.

    `resolve_tag_names` only looks under the claimed version, so a label naming
    the wrong major finds nothing and would land in the soft UNVERIFIED bucket
    next to genuine upstream retags. This names what the SHA actually is, which
    both makes the error actionable and promotes it to a hard MISMATCH.
    """
    names: list[str] = []
    for page in range(1, _REVERSE_LOOKUP_PAGES + 1):
        tags = _api(f"/repos/{_repo_path(pin.repo)}/tags?per_page=100&page={page}")
        if not isinstance(tags, list) or not tags:
            break
        names.extend(
            str(tag["name"])
            for tag in tags
            if ((tag or {}).get("commit") or {}).get("sha") == pin.sha and tag.get("name")
        )
    return names


def verify(pin: Pin) -> tuple[str, str]:
    """`(verdict, detail)` where verdict is OK / MISMATCH / UNVERIFIED / NO-LABEL."""
    if pin.label is None:
        return "NO-LABEL", "no `# version` comment — nothing to verify against"
    names = resolve_tag_names(pin)
    if names and any(labels_compatible(pin.label, name) for name in names):
        return "OK", ", ".join(names)
    actual = names or reverse_lookup_tags(pin)
    if actual:
        return "MISMATCH", f"SHA is {', '.join(actual)} — label claims {pin.label}"
    return "UNVERIFIED", f"no tag matching {pin.label} points at this SHA, and no other tag names it either"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--allow-unverified",
        action="store_true",
        help="exit 0 when a pin cannot be resolved upstream (still fails on MISMATCH)",
    )
    args = parser.parse_args()

    pins = collect_pins()
    if not pins:
        logger.error("no SHA-pinned external actions found — the parser is broken, not the repo")
        return 1

    failures: list[str] = []
    soft: list[str] = []
    for pin in pins:
        verdict, detail = verify(pin)
        line = f"{verdict:<10} {pin.ref}@{pin.sha[:8]}  # {pin.label or '-'}  ({detail})"
        if verdict == "MISMATCH":
            logger.error(line)
            failures.append(line)
        elif verdict in ("UNVERIFIED", "NO-LABEL"):
            logger.warning(line)
            soft.append(line)
        else:
            logger.info(line)

    logger.info("%d pins checked: %d mismatch, %d unverified", len(pins), len(failures), len(soft))
    if failures:
        logger.error("version label(s) contradict upstream — correct the `# vX.Y` comment to the actual tag")
        return 1
    if soft and not args.allow_unverified:
        logger.error("unresolved pin(s); re-run with --allow-unverified if upstream retagged")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
