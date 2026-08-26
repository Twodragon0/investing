"""Any function that puts a credential in request params must redact its errors.

`requests` embeds the full URL — query string included — in its exception text, so
`logger.warning("...: %s", e)` publishes the key. This repo is public and its
collectors run on Actions twice daily, which makes those log lines publicly
readable.

`common.utils.request_with_retry` redacts the exception before re-raising, so any
caller that fetches through it is covered for free. The failure mode this guard
exists for is the *bypass*: a function that builds its own credential params and
calls `requests.get` directly. Two such sites existed when this guard was written
(`generate_market_summary._fetch_alpha_vantage` and
`collect_crypto_news.fetch_cryptopanic_news`), and neither was findable by looking
at `common/utils.py` — the helper was already fixed and they still leaked.

The rule enforced here: a function containing a credential-valued request
parameter must reach `request_with_retry` or call `redact_credentials`.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"

# Mirrors common.utils._CREDENTIAL_QUERY_PARAMS. Kept as a literal rather than
# imported so that loosening the production tuple cannot silently loosen the guard.
CREDENTIAL_PARAM_KEYS = {
    "apikey",
    "api_key",
    "auth_token",
    "token",
    "access_key",
    "secret",
    "password",
    "key",
}

SAFE_CALLS = {"request_with_retry", "redact_credentials"}


def _python_files() -> list[Path]:
    return sorted(p for p in SCRIPTS_DIR.rglob("*.py") if "__pycache__" not in p.parts)


def _called_names(node: ast.AST) -> set[str]:
    names = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            func = sub.func
            if isinstance(func, ast.Name):
                names.add(func.id)
            elif isinstance(func, ast.Attribute):
                names.add(func.attr)
    return names


def _calls_requests_directly(node: ast.AST) -> bool:
    """True if the function calls ``requests.<verb>(...)`` itself.

    The leak mechanism is specific to ``requests``: it renders the full URL, query
    string included, into the exception message. ``urllib`` does not, so a
    ``urllib.request.urlopen`` call with a key in the JSON *body* is not this bug
    — that is why ``tools/indexnow_submit._submit_batch`` is not flagged (and its
    "key" is a published verification token anyway, echoed in ``keyLocation``).
    Narrowing on the mechanism keeps this guard from needing an allowlist, which
    would be the place future exceptions get parked without review.
    """
    for sub in ast.walk(node):
        if not isinstance(sub, ast.Call):
            continue
        func = sub.func
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id == "requests":
            return True
    return False


def _has_credential_param_dict(node: ast.AST) -> bool:
    """True if the function builds a dict with a credential-looking key.

    Matches on the key name only. A constant *value* would be a hardcoded secret,
    which ruff's S105/S106 already rejects, so the interesting case is always a
    variable value.
    """
    for sub in ast.walk(node):
        if not isinstance(sub, ast.Dict):
            continue
        for key in sub.keys:
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                if key.value.lower() in CREDENTIAL_PARAM_KEYS:
                    return True
    return False


def _offending_functions() -> list[str]:
    offenders = []
    for path in _python_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover — a parse failure is its own bug
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            if not _has_credential_param_dict(node):
                continue
            if not _calls_requests_directly(node):
                continue
            if _called_names(node) & SAFE_CALLS:
                continue
            rel = path.relative_to(SCRIPTS_DIR.parent)
            offenders.append(f"{rel}:{node.lineno} {node.name}()")
    return offenders


def test_credential_bearing_requests_are_redacted():
    offenders = _offending_functions()
    assert not offenders, (
        "These functions build credential request params but neither fetch through "
        "request_with_retry nor call redact_credentials, so a requests exception "
        "would log the key:\n  " + "\n  ".join(offenders)
    )


def test_guard_detects_a_synthetic_violation(tmp_path, monkeypatch):
    """The guard must fail on a real violation, not just pass vacuously.

    Without this, deleting the detection logic would leave a permanently green
    test that reads like coverage.
    """
    offending = tmp_path / "scripts" / "bad_collector.py"
    offending.parent.mkdir(parents=True)
    offending.write_text(
        "import requests\n"
        "import logging\n"
        "logger = logging.getLogger(__name__)\n"
        "def fetch(api_key):\n"
        "    params = {'apikey': api_key}\n"
        "    try:\n"
        "        return requests.get('https://x/y', params=params)\n"
        "    except requests.exceptions.RequestException as e:\n"
        "        logger.warning('failed: %s', e)\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("tests.test_credential_logging_guard.SCRIPTS_DIR", offending.parent, raising=False)
    # Re-resolve through the module global the helpers read.
    import tests.test_credential_logging_guard as guard

    monkeypatch.setattr(guard, "SCRIPTS_DIR", offending.parent)
    offenders = guard._offending_functions()
    assert any("fetch()" in o for o in offenders), offenders


@pytest.mark.parametrize("safe_call", sorted(SAFE_CALLS))
def test_guard_accepts_either_safe_path(tmp_path, monkeypatch, safe_call):
    """Both remediations count — routing through the helper, or redacting inline.

    The body still calls ``requests`` directly so the narrowing in
    ``_calls_requests_directly`` cannot be what makes this pass; the safe call is.
    """
    safe = tmp_path / "scripts" / "good_collector.py"
    safe.parent.mkdir(parents=True, exist_ok=True)
    safe.write_text(
        "import requests\n"
        "import logging\n"
        "logger = logging.getLogger(__name__)\n"
        "def fetch(api_key):\n"
        "    params = {'apikey': api_key}\n"
        "    try:\n"
        "        return requests.get('https://x/y', params=params)\n"
        "    except requests.exceptions.RequestException as e:\n"
        f"        logger.warning('failed: %s', {safe_call}(e))\n",
        encoding="utf-8",
    )
    import tests.test_credential_logging_guard as guard

    monkeypatch.setattr(guard, "SCRIPTS_DIR", safe.parent)
    assert guard._offending_functions() == []
