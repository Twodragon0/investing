"""
Lint GitHub Actions workflows for caller/callee permission mismatches.

Prevents the class of outage from 2026-04-23 where a reusable workflow
declared `actions: read` but its callers only had `contents: write`,
causing startup_failure on all 13 collector workflows.

Exit codes:
  0 — all caller→callee permission pairs are satisfied
  1 — at least one caller is missing a permission required by a callee
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    print("ERROR: PyYAML is required. Run: pip install pyyaml", file=sys.stderr)
    sys.exit(2)

# Permission level ordering: higher index = broader access
_LEVELS = ["none", "read", "write"]


def _satisfies(caller_level: str, callee_level: str) -> bool:
    """Return True if caller_level covers the callee's requirement."""
    ci = _LEVELS.index(caller_level) if caller_level in _LEVELS else 0
    ri = _LEVELS.index(callee_level) if callee_level in _LEVELS else 0
    return ci >= ri


def _load_yaml(path: Path) -> dict | None:
    """Parse a YAML file; return None and emit a warning on error."""
    try:
        with path.open(encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except Exception as exc:  # noqa: BLE001
        warnings.warn(f"WARN: could not parse {path}: {exc}", stacklevel=2)
        return None


def _top_level_permissions(doc: dict) -> dict[str, str]:
    """Extract the top-level `permissions:` block as {scope: level}."""
    perms = doc.get("permissions") or {}
    if isinstance(perms, str):
        # e.g. `permissions: read-all`  — treat as broad grant, skip check
        return {"*": perms}
    if not isinstance(perms, dict):
        return {}
    return {k: str(v) for k, v in perms.items()}


def _is_reusable(doc: dict) -> bool:
    on = doc.get("on") or doc.get(True)  # YAML parses `on` as True
    if isinstance(on, dict):
        return "workflow_call" in on
    return False


def _local_reusable_calls(doc: dict) -> list[str]:
    """Return list of local reusable workflow filenames referenced in jobs."""
    refs: list[str] = []
    jobs = doc.get("jobs") or {}
    for job in jobs.values():
        if not isinstance(job, dict):
            continue
        uses = job.get("uses", "")
        if isinstance(uses, str) and uses.startswith("./.github/workflows/"):
            # e.g. "./.github/workflows/alert-consecutive-failures.yml"
            refs.append(uses.removeprefix("./.github/workflows/"))
    return refs


def scan(workflows_dir: Path) -> list[str]:
    """
    Scan all workflows under `workflows_dir`.
    Return a list of human-readable error strings (empty = clean).
    """
    workflow_files = sorted(workflows_dir.glob("*.yml"))

    docs: dict[str, dict] = {}
    for wf in workflow_files:
        doc = _load_yaml(wf)
        if doc is not None:
            docs[wf.name] = doc

    # Build index of reusable workflows and their required permissions
    reusable_perms: dict[str, dict[str, str]] = {}
    for name, doc in docs.items():
        if _is_reusable(doc):
            reusable_perms[name] = _top_level_permissions(doc)

    errors: list[str] = []

    for caller_name, caller_doc in docs.items():
        callees = _local_reusable_calls(caller_doc)
        if not callees:
            continue
        caller_perms = _top_level_permissions(caller_doc)

        # Broad grant: skip detailed checks
        if "*" in caller_perms:
            continue

        for callee_name in callees:
            if callee_name not in reusable_perms:
                # External or unknown callee — skip
                continue
            callee_perms = reusable_perms[callee_name]
            if "*" in callee_perms:
                continue

            missing: dict[str, str] = {}
            for scope, required_level in callee_perms.items():
                caller_level = caller_perms.get(scope, "none")
                if not _satisfies(caller_level, required_level):
                    missing[scope] = required_level

            if missing:
                caller_path = f".github/workflows/{caller_name}"
                callee_path = f".github/workflows/{callee_name}"
                missing_str = ", ".join(f"{k}: {v}" for k, v in sorted(missing.items()))
                caller_str = ", ".join(f"{k}: {v}" for k, v in sorted(caller_perms.items()))
                errors.append(
                    f"ERROR: caller '{caller_path}' calls reusable '{callee_path}' "
                    f"which requires permissions {{{missing_str}}}, "
                    f"but caller grants only {{{caller_str}}}.\n"
                    f"  Fix: add `{missing_str}` to caller's top-level `permissions:` block."
                )

    return errors


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workflows-dir",
        default=".github/workflows",
        help="Path to the workflows directory (default: .github/workflows)",
    )
    args = parser.parse_args(argv)

    workflows_dir = Path(args.workflows_dir)
    if not workflows_dir.is_dir():
        print(f"ERROR: workflows directory not found: {workflows_dir}", file=sys.stderr)
        return 2

    errors = scan(workflows_dir)
    for err in errors:
        print(err)

    if errors:
        print(f"\n{len(errors)} permission violation(s) found.", file=sys.stderr)
        return 1

    print("OK: all caller→callee workflow permissions satisfied.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
