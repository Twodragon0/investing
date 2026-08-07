"""CI config regression guard: `vercel.json` stays within Vercel's schema limits.

## The incident this exists for (2026-08-07)

`vercel.json` gained a path-aware `ignoreCommand` so that pushes which cannot
change the built site skip the build. The command was **456 characters**.
Vercel's own schema (`https://openapi.vercel.sh/vercel.json`) caps every command
field at **256**, so the deployment never ran:

    Vercel: failure — "Deployment failed."
    target_url: https://vercel.com/docs/concepts/projects/project-configuration

Production stopped deploying for every commit after that merge. Nothing in the
repo caught it: the JSON was valid, `jekyll build` passed locally, and the whole
test suite was green — the constraint lives in Vercel's schema, not in the file.

## The second trap: `:!` pathspec magic depends on the path's first character

The shortened command used `':!_state'`. Git reads what follows `:!` as pathspec
*magic* and rejects `_`:

    fatal: Unimplemented pathspec magic '_' in ':!_state'

Measured on git 2.x, 2026-08-07: `:!tests`, `:!docs`, `:!.github`, `:!scripts`
all parse fine — only `:!_state` aborts. So the bare form is not broken in
general; whether it works **depends on the first character of the path**, which
is a terrible property for a config nobody re-tests.

Worse, the failure is silent. `ignoreCommand` is fail-open by design (non-zero
exit means "build") and git's fatal *is* non-zero, so the broken command still
answered "build" — four of five hand-checked cases looked correct. Only the one
case whose expected verdict was "skip" exposed it.

This guard therefore **mandates the unambiguous form** (`:!./path` or
`:(exclude)path`) rather than claiming bare forms are broken. It will reject
`:!tests`, which does work today; that is the intended trade — it removes the
whole class instead of relying on nobody ever excluding a path that starts with
the wrong character.

Direction: `<=` for the length cap (shorter is fine), presence for the pathspec
form. Text/JSON scan only — no network, no Vercel CLI.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_VERCEL_JSON = _REPO_ROOT / "vercel.json"

# https://openapi.vercel.sh/vercel.json — `maxLength: 256` on each command field.
# Confirmed against the live schema on 2026-08-07. If Vercel raises the cap,
# bump this constant and say so here; do not silently exceed it.
_COMMAND_MAX_LENGTH = 256
_COMMAND_FIELDS = ("buildCommand", "installCommand", "devCommand", "ignoreCommand")

# `:!` followed by anything other than `/` or `.` re-enters magic-letter parsing.
_SHORT_EXCLUDE_RE = re.compile(r":!(?![./])")


def _config() -> dict:
    return json.loads(_VERCEL_JSON.read_text(encoding="utf-8"))


def test_vercel_json_exists_and_parses() -> None:
    """Canary: a moved or malformed file fails here rather than vacuously."""
    assert _VERCEL_JSON.is_file(), f"{_VERCEL_JSON} not found"
    assert isinstance(_config(), dict), "vercel.json must be a JSON object"


@pytest.mark.parametrize("field", _COMMAND_FIELDS)
def test_command_fields_within_vercel_length_cap(field: str) -> None:
    """Vercel rejects the whole config when a command exceeds 256 characters."""
    value = _config().get(field)
    if value is None:
        pytest.skip(f"{field} not configured")
    assert len(value) <= _COMMAND_MAX_LENGTH, (
        f"vercel.json `{field}` is {len(value)} characters; Vercel's schema caps it at "
        f"{_COMMAND_MAX_LENGTH}. Exceeding it makes every deployment fail with "
        '"Deployment failed." and a link to the project-configuration docs — the '
        "site silently stops updating. Move logic out of the command or shorten it."
    )


def test_ignore_command_uses_unambiguous_exclude_pathspec_form() -> None:
    """Require `:!./path` or `:(exclude)path` — never bare `:!path`.

    Whether the bare form parses depends on the path's first character
    (`:!tests` works, `:!_state` aborts), and the abort is fail-open so it reads
    as "build" rather than as an error.
    """
    command = _config().get("ignoreCommand")
    if command is None:
        pytest.skip("ignoreCommand not configured")
    bad = _SHORT_EXCLUDE_RE.findall(command)
    assert not bad, (
        "vercel.json `ignoreCommand` uses a bare `:!<path>` pathspec. Git reads what "
        "follows `:!` as pathspec magic, so whether it works depends on the path's "
        "first character — `:!_state` aborts with "
        "`fatal: Unimplemented pathspec magic '_'` while `:!tests` is fine. Because the "
        'command is fail-open, that abort silently reads as "build". Use `:!./<path>` '
        "or `:(exclude)<path>`."
    )


def test_ignore_command_still_gates_on_main() -> None:
    """Presence: previews must stay skipped, or every PR burns deploy quota."""
    command = _config().get("ignoreCommand")
    if command is None:
        pytest.skip("ignoreCommand not configured")
    assert "VERCEL_GIT_COMMIT_REF" in command, (
        "`ignoreCommand` no longer checks `VERCEL_GIT_COMMIT_REF`. Without the branch "
        "gate, non-main refs build too, which is what the original command existed to "
        "prevent."
    )


def test_exclude_pathspec_detector_is_bidirectional() -> None:
    """A detector loosened to match nothing would leave the assertion green.

    `:!tests` is listed as disallowed even though it parses today — the rule is
    "always prefix", not "only the forms that happen to break".
    """
    for disallowed in (":!_state", ":!tests", ":!docs", "':!_state'", ":!scripts"):
        assert _SHORT_EXCLUDE_RE.search(disallowed), f"detector misses bare form {disallowed!r}"
    for allowed in (":!./_state", ":!./.github", ":!./tests", ":(exclude)_state"):
        assert not _SHORT_EXCLUDE_RE.search(allowed), f"detector flags prefixed form {allowed!r}"
