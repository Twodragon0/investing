"""Tests for scripts/tools/check_workflow_permissions.py"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

# Allow importing the script directly
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from tools.check_workflow_permissions import scan  # noqa: E402

# ---------------------------------------------------------------------------
# YAML fixtures
# ---------------------------------------------------------------------------

_CALLEE = textwrap.dedent("""\
    name: Reusable Alert
    on:
      workflow_call:
        inputs:
          workflow-name:
            required: true
            type: string
    permissions:
      contents: read
      actions: read
    jobs:
      check:
        runs-on: ubuntu-latest
        steps:
          - run: echo hi
""")

_CALLEE_NO_PERMS = textwrap.dedent("""\
    name: Reusable No Perms
    on:
      workflow_call:
        inputs:
          foo:
            required: false
            type: string
    jobs:
      job:
        runs-on: ubuntu-latest
        steps:
          - run: echo ok
""")

# Caller that satisfies both contents:read and actions:read
_CALLER_FULL_PERMS = textwrap.dedent("""\
    name: Caller Full
    on:
      schedule:
        - cron: '0 * * * *'
    permissions:
      contents: write
      actions: read
    jobs:
      main:
        runs-on: ubuntu-latest
        steps:
          - run: echo main
      alert:
        needs: main
        if: failure()
        uses: ./.github/workflows/callee.yml
        with:
          workflow-name: test
""")

# Caller missing actions:read
_CALLER_MISSING_ACTIONS = textwrap.dedent("""\
    name: Caller Missing Actions
    on:
      schedule:
        - cron: '0 * * * *'
    permissions:
      contents: write
    jobs:
      main:
        runs-on: ubuntu-latest
        steps:
          - run: echo main
      alert:
        needs: main
        if: failure()
        uses: ./.github/workflows/callee.yml
        with:
          workflow-name: test
""")

# Caller with only pull-requests:write (missing both contents and actions)
_CALLER_MISSING_BOTH = textwrap.dedent("""\
    name: Caller Missing Both
    on:
      schedule:
        - cron: '0 * * * *'
    permissions:
      pull-requests: write
    jobs:
      main:
        runs-on: ubuntu-latest
        steps:
          - run: echo main
      alert:
        needs: main
        if: failure()
        uses: ./.github/workflows/callee.yml
        with:
          workflow-name: test
""")

# Caller pointing at the no-perms callee
_CALLER_NOPERMS_CALLEE = textwrap.dedent("""\
    name: Caller No Perms Callee
    on:
      schedule:
        - cron: '0 * * * *'
    permissions:
      contents: write
    jobs:
      main:
        runs-on: ubuntu-latest
        steps:
          - run: echo main
      alert:
        needs: main
        if: failure()
        uses: ./.github/workflows/callee-noperms.yml
        with:
          workflow-name: test
""")


def _write(tmp_path: Path, name: str, content: str) -> None:
    (tmp_path / name).write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


def test_valid_caller_satisfies_callee(tmp_path):
    """Caller grants contents:write + actions:read — satisfies callee's read requirements."""
    _write(tmp_path, "callee.yml", _CALLEE)
    _write(tmp_path, "caller.yml", _CALLER_FULL_PERMS)

    errors = scan(tmp_path)
    assert errors == [], f"Expected no errors, got: {errors}"


def test_caller_missing_actions_read(tmp_path):
    """Caller only has contents:write — missing actions:read required by callee."""
    _write(tmp_path, "callee.yml", _CALLEE)
    _write(tmp_path, "caller.yml", _CALLER_MISSING_ACTIONS)

    errors = scan(tmp_path)
    assert len(errors) == 1
    assert "actions: read" in errors[0]
    assert "caller.yml" in errors[0]
    assert "callee.yml" in errors[0]
    assert "Fix:" in errors[0]


def test_external_reusable_call_skipped(tmp_path):
    """Calls to external reusable workflows (not local) should be ignored."""
    _write(
        tmp_path,
        "caller.yml",
        textwrap.dedent("""\
        name: External Caller
        on:
          push:
            branches: [main]
        permissions:
          contents: write
        jobs:
          call-external:
            uses: some-org/some-repo/.github/workflows/reusable.yml@main
            with:
              foo: bar
    """),
    )

    errors = scan(tmp_path)
    assert errors == [], f"Expected no errors for external call, got: {errors}"


def test_callee_without_permissions_block(tmp_path):
    """Reusable workflow with no permissions block should not trigger errors."""
    _write(tmp_path, "callee-noperms.yml", _CALLEE_NO_PERMS)
    _write(tmp_path, "caller.yml", _CALLER_NOPERMS_CALLEE)

    errors = scan(tmp_path)
    assert errors == [], f"Expected no errors when callee has no permissions, got: {errors}"


def test_caller_missing_multiple_permissions(tmp_path):
    """Caller missing both contents:read and actions:read should report both."""
    _write(tmp_path, "callee.yml", _CALLEE)
    _write(tmp_path, "caller.yml", _CALLER_MISSING_BOTH)

    errors = scan(tmp_path)
    assert len(errors) == 1
    assert "actions: read" in errors[0]
    assert "contents: read" in errors[0]


def test_invalid_yaml_emits_warning_not_crash(tmp_path, recwarn):
    """Malformed YAML file should emit a warning and not crash the scan."""
    (tmp_path / "bad.yml").write_text("key: [unclosed bracket\n  bad: indent: bad", encoding="utf-8")
    _write(tmp_path, "callee.yml", _CALLEE)
    _write(tmp_path, "caller.yml", _CALLER_FULL_PERMS)

    errors = scan(tmp_path)
    assert errors == []
    assert any("bad.yml" in str(w.message) for w in recwarn.list)


def test_subprocess_exit_code_clean(tmp_path):
    """Script exits 0 when no violations exist."""
    _write(tmp_path, "callee.yml", _CALLEE)
    _write(tmp_path, "caller.yml", _CALLER_FULL_PERMS)

    result = subprocess.run(
        [
            sys.executable,
            "scripts/tools/check_workflow_permissions.py",
            "--workflows-dir",
            str(tmp_path),
        ],
        cwd=str(Path(__file__).parent.parent),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_subprocess_exit_code_violation(tmp_path):
    """Script exits 1 when a permission violation is found."""
    _write(tmp_path, "callee.yml", _CALLEE)
    _write(tmp_path, "caller.yml", _CALLER_MISSING_ACTIONS)

    result = subprocess.run(
        [
            sys.executable,
            "scripts/tools/check_workflow_permissions.py",
            "--workflows-dir",
            str(tmp_path),
        ],
        cwd=str(Path(__file__).parent.parent),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "actions: read" in result.stdout
    assert "Fix:" in result.stdout
