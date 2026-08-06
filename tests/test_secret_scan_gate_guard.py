"""CI config regression guard: the Gitleaks secret-scan gate stays load-bearing.

`security-scan.yml`'s `gitleaks` job is the repo's only blocking secret scanner.
Unlike a coverage floor there is no number to watch — the gate is a `gitleaks
detect` exit code, and several one-line edits leave the job in place while
making it incapable of failing. Each is asserted separately below.

## The four ways this gate dies quietly

* **Config neutered** — `[extend] useDefault = false` drops the ~100 upstream
  rules (AWS, GCP, Slack, GitHub PAT). `gitleaks detect` then reports "no leaks
  found" on a repo full of them.
* **Allowlist widened** — the allowlist is deliberately narrow: two
  low-precision rules (`targetRules`) on two auto-generated public-data paths.
  Dropping `targetRules` applies the suppression to *every* rule on those
  paths; adding a path extends it to real source. Both keep the file looking
  like a working config. Pinned by set equality, so any change trips here and
  has to be re-justified.
* **Invocation softened** — `|| true`, `--exit-code 0`, or
  `continue-on-error: true` turn a red scan into an annotation.
* **History truncated** — the scan is `gitleaks detect` over git history, so it
  needs `fetch-depth: 0`. At the default depth of 1 it inspects a single commit
  and a secret introduced earlier goes unseen.

Direction: `useDefault` and `fetch-depth: 0` are presence; the allowlist sets
are `==` (any widening *or* narrowing trips — narrowing is safe but should be a
deliberate edit here too). If a suppression is genuinely needed, update
`_ALLOWED_TARGET_RULES` / `_ALLOWED_PATHS` in the same commit.

Config parsing only (`tomllib` + text scan; no PyYAML) per the guard conventions
in `docs/devsecops/ci-regression-guards.md`.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "security-scan.yml"
_GITLEAKS_CONFIG = _REPO_ROOT / ".gitleaks.toml"

# The allowlist as justified in .gitleaks.toml's header comment. Both are
# auto-generated, public-data-only files; see that file for the full rationale.
_ALLOWED_TARGET_RULES = frozenset({"linkedin-client-secret", "generic-api-key"})
_ALLOWED_PATHS = frozenset({r"_state/translation_cache\.json", r"_posts/.*\.md"})

_JOB_START_RE = re.compile(r"^  (?P<name>[A-Za-z0-9_-]+):$", re.M)
_STEP_START_RE = re.compile(r"^ *- name: ", re.M)
_CONTINUE_ON_ERROR_RE = re.compile(r"continue-on-error:\s*(\S+)")
_FETCH_DEPTH_RE = re.compile(r"fetch-depth:\s*(\S+)")

# Shell escapes that swallow a non-zero exit: `|| true`, `; true`, `|| :`.
# `\b` cannot terminate `:` (not a word character), so the trailing context is
# spelled as an explicit lookahead — otherwise `|| :` slips through.
_SWALLOW_RE = re.compile(r"(\|\||;)\s*(true|:)(?=\s|$)")


def _gitleaks_job() -> str:
    """The `gitleaks:` job block of security-scan.yml, as text.

    Job-scoped rather than file-scoped on purpose: the sibling `bandit` job
    legitimately uses `continue-on-error` (it re-raises in a later step), so a
    whole-file scan would be permanently red.
    """
    text = _WORKFLOW.read_text(encoding="utf-8")
    starts = [(m.start(), m.group("name")) for m in _JOB_START_RE.finditer(text)]
    bounds = [*(s for s, _ in starts[1:]), len(text)]
    for (start, name), end in zip(starts, bounds, strict=True):
        if name == "gitleaks":
            return text[start:end]
    raise AssertionError(
        "security-scan.yml no longer defines a `gitleaks:` job — the secret-scan "
        "gate was removed or renamed. Restore it, or update this guard if it "
        "moved, with justification."
    )


def _detect_commands() -> list[str]:
    """Lines in the gitleaks job that invoke `gitleaks detect`."""
    return [line.strip() for line in _gitleaks_job().splitlines() if "gitleaks detect" in line]


def test_gate_files_exist() -> None:
    """Canary: a moved/renamed config fails loudly instead of vacuously."""
    assert _WORKFLOW.is_file(), f"{_WORKFLOW} not found"
    assert _GITLEAKS_CONFIG.is_file(), f"{_GITLEAKS_CONFIG} not found"


def test_gitleaks_config_extends_default_rules() -> None:
    """`[extend] useDefault` must stay true.

    With it false the scan keeps running and keeps passing while checking
    against an empty rule set — the quietest possible failure mode.
    """
    config = tomllib.loads(_GITLEAKS_CONFIG.read_text(encoding="utf-8"))
    assert config.get("extend", {}).get("useDefault") is True, (
        "`.gitleaks.toml` no longer sets `[extend] useDefault = true`. Without "
        "the upstream rule set (AWS, GCP, Slack, GitHub PAT, ...) the scan "
        "reports 'no leaks found' regardless of what is committed."
    )


def test_gitleaks_allowlist_is_scoped_to_known_false_positives() -> None:
    """The allowlist must stay pinned to the two justified rules and paths.

    Dropping `targetRules` silently promotes a two-rule suppression into a
    blanket one covering every rule on those paths.
    """
    allowlist = tomllib.loads(_GITLEAKS_CONFIG.read_text(encoding="utf-8")).get("allowlist", {})

    target_rules = set(allowlist.get("targetRules", []))
    assert target_rules == set(_ALLOWED_TARGET_RULES), (
        f"gitleaks allowlist targetRules changed: {sorted(target_rules)} != "
        f"{sorted(_ALLOWED_TARGET_RULES)}. An empty/absent targetRules "
        f"suppresses *all* rules on the allowlisted paths. If the change is "
        f"intended, update _ALLOWED_TARGET_RULES here in the same commit."
    )

    paths = set(allowlist.get("paths", []))
    assert paths == set(_ALLOWED_PATHS), (
        f"gitleaks allowlist paths changed: {sorted(paths)} != "
        f"{sorted(_ALLOWED_PATHS)}. Each added path is a directory where "
        f"secrets stop being reported. If intended, update _ALLOWED_PATHS here "
        f"in the same commit."
    )


def test_gitleaks_step_uses_the_repo_config() -> None:
    """The scan must run against `.gitleaks.toml`.

    gitleaks v8.24.2 does not auto-load the file; without `--config` the tuned
    allowlist disappears and the job drowns in false positives (244 of them,
    recorded in that file's header).
    """
    commands = _detect_commands()
    assert commands, "the `gitleaks:` job no longer runs `gitleaks detect` — the secret-scan gate is gone."

    unconfigured = [c for c in commands if "--config" not in c]
    assert not unconfigured, "`gitleaks detect` invoked without `--config .gitleaks.toml`:\n" + "\n".join(
        f"  - {c}" for c in unconfigured
    )


def test_gitleaks_gate_is_blocking() -> None:
    """A finding must fail the job — no `continue-on-error`, no swallowed exit.

    Checked at job level, at step level, and in the shell command itself:
    any one of the three turns the gate into an annotation.
    """
    job = _gitleaks_job()

    soft: list[str] = []

    job_header = job.split("steps:", 1)[0]
    job_match = _CONTINUE_ON_ERROR_RE.search(job_header)
    if job_match and job_match.group(1).lower() != "false":
        soft.append(f"job-level -> continue-on-error: {job_match.group(1)}")

    starts = [m.start() for m in _STEP_START_RE.finditer(job)]
    steps = [job[s:e] for s, e in zip(starts, [*starts[1:], len(job)], strict=True)]
    for step in steps:
        if "gitleaks detect" not in step:
            continue
        match = _CONTINUE_ON_ERROR_RE.search(step)
        if match and match.group(1).lower() != "false":
            soft.append(f"{step.splitlines()[0].strip()} -> continue-on-error: {match.group(1)}")

    for command in _detect_commands():
        if _SWALLOW_RE.search(command):
            soft.append(f"exit code swallowed by shell: {command}")
        if "--exit-code" in command and "--exit-code 0" in command:
            soft.append(f"`--exit-code 0` makes findings non-fatal: {command}")

    assert not soft, "the secret-scan gate is non-blocking (findings would not fail the job):\n" + "\n".join(
        f"  - {s}" for s in soft
    )


def test_gitleaks_job_checks_out_full_history() -> None:
    """`fetch-depth: 0` — `gitleaks detect` scans history, not the worktree.

    At the runner default (depth 1) only the tip commit is present, so a secret
    committed earlier and never touched again is invisible to the scan.
    """
    job = _gitleaks_job()
    depths = _FETCH_DEPTH_RE.findall(job)
    assert depths, (
        "the `gitleaks:` job's checkout no longer sets `fetch-depth: 0`. "
        "A shallow checkout limits `gitleaks detect` to the tip commit, so "
        "secrets already in history are never reported."
    )
    assert "0" in depths, (
        f"the `gitleaks:` job checks out at fetch-depth {depths} — history scan needs `fetch-depth: 0`."
    )


def test_swallow_detector_recognises_the_common_escapes() -> None:
    """The shell-escape detector must not rot into a no-op.

    A `_SWALLOW_RE` that stopped matching would leave
    `test_gitleaks_gate_is_blocking` permanently green.
    """
    for swallowed in ("gitleaks detect --source . || true", "gitleaks detect --source .; true", "gitleaks detect || :"):
        assert _SWALLOW_RE.search(swallowed), f"detector misses swallowed exit in {swallowed!r}"
    assert not _SWALLOW_RE.search("gitleaks detect --source . --config .gitleaks.toml --no-banner --redact"), (
        "detector flags a clean invocation"
    )
