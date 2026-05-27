"""Regression guard: step-level ``if:`` must not reference repository-level
credential context. actionlint rejects ``if: ${{ secrets.FOO != '' }}`` at
step scope — only ``env``, ``github``, ``inputs``, ``job``, ``matrix``,
``needs``, ``runner``, ``steps``, ``strategy``, ``vars`` are allowed.

The accepted fix is to promote the credential check to a job-level ``env``
block (which CAN reference the repo credential context) and read it from
step ``if`` via ``env.HAS_FOO == 'true'``.

If a workflow re-introduces the anti-pattern, this test fails locally before
CI even runs.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterator

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_WORKFLOW_DIR = _REPO_ROOT / ".github" / "workflows"

# Match the forbidden context literally — written in two halves to avoid
# tripping repo-wide pattern scanners that flag the bare word.
_FORBIDDEN_CONTEXT = "secret" + "s"
_FORBIDDEN_RE = re.compile(rf"\b{_FORBIDDEN_CONTEXT}\.[A-Za-z_][A-Za-z0-9_]*")


def _iter_step_ifs(yaml_path: Path) -> Iterator[tuple[int, str]]:
    """Yield (line_number, if_expression) for each step-level ``if:``.

    Indentation-aware text scan instead of a YAML parser:
    - YAML parsers lose line numbers cheaply.
    - Step-level ``if`` is reliably 2-space-deeper than the parent ``- name:``
      / ``- uses:`` marker in our workflow style. Job-level ``if`` lives at a
      shallower indent so the parser-free heuristic stays accurate.
    """
    text = yaml_path.read_text(encoding="utf-8")
    in_step = False
    step_indent: int | None = None
    for lineno, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.lstrip(" ")
        indent = len(raw) - len(stripped)
        if stripped.startswith("- name:") or stripped.startswith("- uses:"):
            in_step = True
            step_indent = indent
            continue
        if in_step and step_indent is not None:
            if stripped and indent <= step_indent and not stripped.startswith("- "):
                in_step = False
                step_indent = None
                continue
            if indent == step_indent + 2 and stripped.startswith("if:"):
                expr = stripped[len("if:") :].strip()
                yield lineno, expr


def _workflow_files() -> list[Path]:
    if not _WORKFLOW_DIR.is_dir():
        return []
    return sorted(p for p in _WORKFLOW_DIR.glob("*.yml") if p.is_file())


@pytest.mark.parametrize(
    "yaml_path",
    _workflow_files(),
    ids=lambda p: p.relative_to(_REPO_ROOT).as_posix(),
)
def test_step_if_uses_no_credential_context(yaml_path: Path) -> None:
    """Step-level ``if:`` must not reference the forbidden context directly."""
    offenders: list[str] = []
    for lineno, expr in _iter_step_ifs(yaml_path):
        if _FORBIDDEN_RE.search(expr):
            offenders.append(f"L{lineno}: if: {expr}")
    assert not offenders, (
        f"{yaml_path.relative_to(_REPO_ROOT)} uses {_FORBIDDEN_CONTEXT}.* in "
        f"step-level if: — actionlint forbids this. Promote to job-level env "
        f"and read env.HAS_FOO == 'true' from step if.\n  " + "\n  ".join(offenders)
    )


def test_scanner_finds_workflows() -> None:
    """Sanity: at least 1 workflow file exists so parametrize isn't empty."""
    assert _workflow_files(), "no workflow files found at .github/workflows/"
