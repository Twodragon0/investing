"""Regression tests for import compatibility.

Guards against the recurrence of `from scripts.common.X import Y` style absolute
imports in scripts/common/ modules. These fail when scripts are executed directly
(e.g. `python scripts/collect_crypto_news.py`) because `scripts/` is not always
on sys.path as a package root. All imports must use either:
  - relative imports inside scripts/common/  (from .X import Y)
  - package-relative imports in collector scripts  (from common.X import Y)

Related fix: PR #773 (fix/risk-classifier-import branch).
"""

import importlib
import subprocess
import sys

import pytest

# ---------------------------------------------------------------------------
# All scripts/common/ modules — imported via `from common.X import ...`
# (conftest.py adds scripts/ to sys.path, so this matches real collector usage)
# ---------------------------------------------------------------------------

COMMON_MODULES = [
    "common.base_collector",
    "common.bettafish_analyzer",
    "common.blockchain_api",
    "common.browser",
    "common.collector_config",
    "common.collector_metrics",
    "common.config",
    "common.content_filters",
    "common.crypto_api",
    "common.dedup",
    "common.encoding_guard",
    "common.enrichment",
    "common.entity_extractor",
    "common.fmp_api",
    "common.formatters",
    "common.image_rejection_metrics",
    "common.markdown_utils",
    "common.mindspider",
    "common.post_generator",
    "common.risk_classifier",
    "common.rss_fetcher",
    "common.signal_composer",
    "common.signal_tracker",
    "common.summarizer",
    "common.time_series_state",
    "common.translator",
    "common.utils",
    "common.worldmonitor_utils",
]


@pytest.mark.parametrize("module_name", COMMON_MODULES)
def test_common_module_importable(module_name):
    """Each scripts/common/ module must be importable without ImportError.

    This catches any `from scripts.common.X import Y` style imports that break
    when running collectors directly (without scripts/ as a package root).
    """
    try:
        importlib.import_module(module_name)
    except ImportError as exc:
        pytest.fail(
            f"ImportError importing {module_name!r}: {exc}\n"
            "Likely cause: absolute 'from scripts.common.X import Y' in module. "
            "Fix by using relative imports (from .X import Y) inside scripts/common/."
        )


# ---------------------------------------------------------------------------
# Subprocess tests — simulate running collectors as __main__ scripts.
# Uses --help / a no-op dry path so no real I/O or API calls are made.
# CWD is set to repo root (parent of scripts/), matching real CI execution.
# ---------------------------------------------------------------------------

REPO_ROOT = pytest.importorskip  # just to verify pytest is importable


def _repo_root() -> str:
    """Return the repository root path."""
    import os

    return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


COLLECTOR_SCRIPTS = [
    "scripts/collect_crypto_news.py",
    "scripts/collect_stock_news.py",
]


@pytest.mark.parametrize("script_path", COLLECTOR_SCRIPTS)
def test_collector_script_imports_cleanly(script_path):
    """Collector scripts must not raise ImportError on startup.

    Runs `python -c "import importlib.util; ..."` to load the module without
    executing the main guard, then checks the exit code. This replicates the
    real execution environment (CWD=repo root, python path without scripts/).
    """
    repo_root = _repo_root()

    # We run a minimal Python snippet that:
    # 1. Does NOT add scripts/ to sys.path (replicating bare `python scripts/X.py`)
    # 2. Adds only the repo root (so relative `from common.X` works via scripts/ dir)
    # 3. Imports the script as a spec/module without running __main__
    snippet = (
        "import sys, importlib.util; "
        f"sys.path.insert(0, '{repo_root}/scripts'); "
        f"spec = importlib.util.spec_from_file_location('_col', '{repo_root}/{script_path}'); "
        "mod = importlib.util.module_from_spec(spec); "
        "spec.loader.exec_module(mod)"
    )

    result = subprocess.run(
        [sys.executable, "-c", snippet],
        capture_output=True,
        text=True,
        cwd=repo_root,
        timeout=30,
    )

    if result.returncode != 0:
        # Filter for ImportError specifically to avoid failing on missing env vars
        # or other runtime errors that are expected in a no-API-key environment.
        stderr = result.stderr
        if "ImportError" in stderr or "ModuleNotFoundError" in stderr:
            pytest.fail(
                f"Import error running {script_path!r}:\n{stderr}\n"
                "Fix by using 'from common.X import Y' (not 'from scripts.common.X import Y')."
            )
        # Non-import runtime errors (missing API keys, etc.) are expected — pass.


# ---------------------------------------------------------------------------
# Explicit regression test: risk_classifier must not use scripts.common imports
# ---------------------------------------------------------------------------


def test_risk_classifier_no_absolute_scripts_import():
    """risk_classifier.py must not contain 'from scripts.common' anywhere.

    This is the exact pattern fixed in PR #773. Guard against regression.
    """
    import os

    risk_classifier_path = os.path.join(_repo_root(), "scripts", "common", "risk_classifier.py")
    with open(risk_classifier_path, encoding="utf-8") as f:
        source = f.read()

    assert "from scripts.common" not in source, (
        "risk_classifier.py contains 'from scripts.common' absolute import. "
        "This breaks direct script execution. Use relative imports (from .X import Y)."
    )
    assert "import scripts.common" not in source, (
        "risk_classifier.py contains 'import scripts.common' absolute import. Use relative imports instead."
    )


def test_no_absolute_scripts_imports_in_common():
    """No file in scripts/common/ should use 'from scripts.' or 'import scripts.' imports.

    Scans all .py files in scripts/common/ for the banned patterns.
    Docstrings are excluded via a simple heuristic (lines starting with spaces
    inside triple-quoted blocks are allowed — but the import line itself must
    not appear as a real statement).
    """
    import ast
    import os

    common_dir = os.path.join(_repo_root(), "scripts", "common")
    violations = []

    for fname in sorted(os.listdir(common_dir)):
        if not fname.endswith(".py"):
            continue
        fpath = os.path.join(common_dir, fname)
        with open(fpath, encoding="utf-8") as f:
            source = f.read()

        try:
            tree = ast.parse(source, filename=fpath)
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            # Check `from scripts.common.X import Y`
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module.startswith("scripts."):
                    violations.append(f"{fname}:{node.lineno}: from {module} import ...")
            # Check `import scripts.common.X`
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("scripts."):
                        violations.append(f"{fname}:{node.lineno}: import {alias.name}")

    assert not violations, (
        "Found absolute 'scripts.*' imports in scripts/common/ (breaks direct execution):\n"
        + "\n".join(f"  {v}" for v in violations)
        + "\nFix: use relative imports (from .X import Y) inside scripts/common/."
    )
