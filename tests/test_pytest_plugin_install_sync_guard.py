"""`pyproject.toml` 이 요구하는 pytest 플러그인이 CI 에 실제로 설치되는지 지킨다.

## 왜 있나

`pyproject.toml` 의 `[tool.pytest.ini_options]` 에 플러그인 전용 키를 적어도, 그
플러그인이 없으면 pytest 는 **경고 한 줄만 내고 조용히 무시한다**:

    PytestConfigWarning: Unknown config option: timeout_method

2026-08-24 실측으로 `code-quality.yml` 이 정확히 그 상태였다 — `timeout_method`
(그리고 이 커밋이 추가한 `timeout`)를 선언해 두고 `pytest-timeout` 을 설치하지
않았다. 설정은 있는데 효과는 0이고, CI 는 green 이다.

결과가 나쁜 쪽으로만 조용하다:

- **행 보호가 없다.** 테스트 하나가 멈추면 잡 타임아웃(25분)을 통째로 태운 뒤
  "workflow timeout" 이라는 원인 불명 실패로 끝난다. 어느 테스트인지 로그에
  나오지 않는다.
- **경고가 진짜 문제를 가린다.** `Unknown config option` 은 오타·리네임과 구분되지
  않는다.

`requirements-dev.txt` 는 `pytest-timeout` 을 갖고 있지만 `code-quality.yml` 은
**그 파일을 쓰지 않는다** — 플러그인을 인라인으로 나열한다. 그래서 두 목록이
독립적으로 드리프트한다.

## 지키는 것

`[tool.pytest.ini_options]` 에 등장하는 **플러그인 전용 키**마다, 그 키를 제공하는
플러그인이 `code-quality.yml` 의 설치 목록에 있을 것.

키→플러그인 매핑은 손으로 유지한다(pytest 가 키의 출처를 런타임에 알려주지 않는다).
매핑에 없는 키는 코어로 간주해 통과시킨다 — 그래서 새 플러그인 키를 도입하면
`_PLUGIN_KEYS` 에 한 줄 추가하는 것이 이 가드를 켜는 행위가 된다.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
_PYPROJECT = _REPO_ROOT / "pyproject.toml"
_CODE_QUALITY = _REPO_ROOT / ".github" / "workflows" / "code-quality.yml"

# pytest 코어가 아니라 **플러그인이 제공하는** ini 키 → 배포 패키지 이름.
# 새 플러그인 설정을 pyproject 에 넣으면 여기에도 추가할 것.
_PLUGIN_KEYS: dict[str, str] = {
    "timeout": "pytest-timeout",
    "timeout_method": "pytest-timeout",
    "timeout_func_only": "pytest-timeout",
    "session_timeout": "pytest-timeout",
    "asyncio_mode": "pytest-asyncio",
    "playwright_browser_name": "pytest-playwright",
}

# `--cov` 류는 ini 키가 아니라 addopts 안에 있으므로 별도로 본다.
_ADDOPTS_FLAGS: dict[str, str] = {
    "--cov": "pytest-cov",
    "-n": "pytest-xdist",
    "--timeout": "pytest-timeout",
}

#: `pytest tests/ -m "not i18n_e2e"` 의 실측 최장 test item (2026-08-25, `--durations=12`).
#: `test_dedup_idempotent_stock`. 갱신하려면 같은 명령으로 다시 잴 것.
_SLOWEST_OBSERVED_S = 1.9

#: i18n 을 디셀렉트하지 않았을 때 매 런 발생하는 setup phase 실측(2026-08-25).
#: `tests/i18n/conftest.py` 의 세션 fixture 가 `HEALTHCHECK_TIMEOUT_S=30` 동안
#: 서버를 폴링한 뒤 skip 한다 — `16 skipped in 30.43s`.
_I18N_HEALTHCHECK_SETUP_S = 30.4


def _ini_options() -> dict:
    data = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
    return data.get("tool", {}).get("pytest", {}).get("ini_options", {})


#: pytest 를 **호출하는** 줄. `pip install ... pytest pytest-cov` 는 이름을 나열할 뿐이라
#: 별도로 걸러낸다(아래 `_invokes_pytest` 참고).
_PYTEST_INVOCATION = re.compile(r"(?:^|\s|&&|\||;)\s*(?:python3?(?:\.\d+)?\s+-m\s+)?pytest(?:\s|$)")


def _invokes_pytest(script: str) -> bool:
    return any(
        _PYTEST_INVOCATION.search(line)
        for raw in script.splitlines()
        if not (line := raw.strip()).startswith("#") and "pip install" not in line
    )


def _pytest_run_scripts(workflow: Path) -> list[str]:
    """워크플로우에서 pytest 를 **실행하는** `run:` 스크립트만 뽑는다.

    세 가지 false-green 을 구조적으로 막는다 — 셋 다 2026-08-25 뮤테이션에서 실제로
    가드를 통과시켰다:

    1. 파일 전체 문자열 검색 → 이 배선을 **설명하는 주석**에 매칭된다. `run:` 만 본다.
    2. `run:` 안의 주석 줄 → 스텝 내부 주석에 매칭된다. `#` 줄을 버린다.
    3. `pip install ... pytest pytest-cov ...` → pytest 를 **언급**할 뿐 실행하지 않는다.

    매칭된 스텝은 원문 전체를 돌려준다. `-m "not i18n_e2e"` 는 백슬래시 연속 줄에 있어서
    호출 줄만 잘라내면 놓치기 때문이다.
    """
    wf = yaml.safe_load(workflow.read_text(encoding="utf-8"))
    return [
        script
        for job in (wf.get("jobs") or {}).values()
        for step in (job.get("steps") or [])
        if _invokes_pytest(script := str(step.get("run", "")))
    ]


def _installed_packages() -> set[str]:
    """`code-quality.yml` 의 pip install 라인에서 패키지 이름을 뽑는다."""
    text = _CODE_QUALITY.read_text(encoding="utf-8")
    packages: set[str] = set()
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("pip install"):
            continue
        for token in stripped.split():
            if token in {"pip", "install"} or token.startswith("-"):
                continue
            # `ruff==0.16.4` → `ruff`
            name = re.split(r"[=<>!~\[]", token, maxsplit=1)[0]
            if name:
                packages.add(name)
    return packages


def test_pip_install_line_is_parseable() -> None:
    """추출이 빈손이면 아래 테스트가 전부 no-op 으로 통과한다 — 그걸 막는다."""
    packages = _installed_packages()
    assert "pytest" in packages, (
        f"code-quality.yml 의 pip install 라인에서 pytest 를 찾지 못했다(추출 결과: "
        f"{sorted(packages)}). 설치 방식이 바뀌었다면 _installed_packages() 를 갱신할 것 — "
        "그러지 않으면 이 가드가 조용히 아무것도 검사하지 않게 된다."
    )


@pytest.mark.parametrize("key", sorted(_PLUGIN_KEYS))
def test_declared_plugin_option_has_its_plugin_installed(key: str) -> None:
    if key not in _ini_options():
        pytest.skip(f"pyproject 가 {key!r} 를 선언하지 않음")
    package = _PLUGIN_KEYS[key]
    assert package in _installed_packages(), (
        f"pyproject.toml 이 `{key}` 를 선언하는데 code-quality.yml 이 `{package}` 를 "
        f"설치하지 않는다. pytest 는 `PytestConfigWarning: Unknown config option: {key}` "
        "한 줄만 내고 설정을 무시하므로 CI 는 green 인 채로 효과가 0이 된다."
    )


def test_addopts_flags_have_their_plugins_installed() -> None:
    addopts = str(_ini_options().get("addopts", ""))
    installed = _installed_packages()
    missing = [f"{flag} → {pkg}" for flag, pkg in _ADDOPTS_FLAGS.items() if flag in addopts and pkg not in installed]
    assert not missing, (
        f"addopts 가 쓰는 플래그의 플러그인이 code-quality.yml 에 없다: {missing}. "
        "addopts 플래그는 인자 파싱 단계에서 거부되므로 이쪽은 경고가 아니라 "
        "즉시 에러다(실측: run 32454917372 에서 `--cov` 미인식으로 헬퍼가 죽었다)."
    )


def test_timeout_value_exceeds_slowest_observed_test() -> None:
    """타임아웃이 실측 최장 테스트보다 충분히 커야 flaky red 가 나지 않는다.

    2026-08-25 `--durations=12` 실측 최장은 1.9s (`test_dedup_idempotent_stock`).
    직전 실측은 48.6s (`test_dedup_idempotent_social`) 였고, 그 대부분은 수집기의
    rate-limit `time.sleep(1)/(2)` 였다 — `tests/conftest.py` 의 `sleep_calls`
    fixture 가 그 pacing 을 건너뛰면서 사라졌다. 여유 4배를 최소 조건으로 둔다.

    이 1.9s 는 **i18n 을 디셀렉트한 스위트** 기준이다 — 전제는
    `test_code_quality_deselects_i18n_e2e` 가 따로 지킨다.
    """
    slowest_observed = _SLOWEST_OBSERVED_S
    timeout = _ini_options().get("timeout")
    if timeout is None:
        pytest.skip("pyproject 가 timeout 을 선언하지 않음")
    assert timeout >= slowest_observed * 4, (
        f"timeout={timeout}s 는 실측 최장 테스트 {slowest_observed}s 대비 여유가 부족하다. "
        "너무 낮으면 느린 러너에서 flaky red 가 된다 — 낮추려면 먼저 "
        "`pytest --durations` 로 다시 재고 이 상수를 갱신할 것."
    )


def test_code_quality_deselects_i18n_e2e() -> None:
    """`code-quality.yml` 은 `-m "not i18n_e2e"` 로 Playwright 스위트를 빼야 한다.

    이 잡은 :4000 에 Jekyll 을 띄우지 않으므로 `tests/i18n/**` 16건은 **항상**
    skip 된다. 문제는 공짜로 skip 되지 않는다는 것이다 — `tests/i18n/conftest.py`
    의 세션 fixture 가 `HEALTHCHECK_TIMEOUT_S=30` 동안 서버를 폴링한 뒤에야
    skip 한다. 2026-08-25 실측: `16 skipped in 30.43s`, 그중 setup phase 30.40s.

    두 가지가 걸려 있다:

    1. 매 런 30초 낭비. skip 이라 로그에는 `s` 열여섯 개로만 보인다.
    2. **`timeout` 산정의 전제.** 디셀렉트하지 않으면 이 잡의 최장 test item phase
       가 1.9s 가 아니라 30.4s 가 되고, `_SLOWEST_OBSERVED_S` 를 근거로 낮춘
       per-test 상한이 그 순간 근거를 잃는다. 위
       `test_timeout_value_exceeds_slowest_observed_test` 는 상수만 보므로 이
       전제가 깨지는 것을 스스로는 알아채지 못한다.

    회귀는 조용하다 — `-m` 을 지워도 테스트는 전부 통과하고 잡도 green 이다.

    파일 전체를 문자열 검색하면 **이 배선을 설명하는 주석에 걸려 항상 통과한다**
    (2026-08-25 뮤테이션으로 실제 확인). 반드시 실행되는 `run:` 스크립트만 본다.
    """
    runs = _pytest_run_scripts(_CODE_QUALITY)
    assert runs, "code-quality.yml 에서 pytest 를 실행하는 `run:` 스텝을 찾지 못했다 — 이 가드가 no-op 이 됐다."
    for script in runs:
        assert "not i18n_e2e" in script, (
            "code-quality.yml 의 pytest 실행이 i18n_e2e 를 디셀렉트하지 않는다: "
            f"{script.strip()!r}. 그러면 세션 fixture 폴링으로 매 런 "
            f"~{_I18N_HEALTHCHECK_SETUP_S}s 를 버리고, per-test 상한 "
            f"{_ini_options().get('timeout')}s 가 근거로 삼는 최장치 "
            f"{_SLOWEST_OBSERVED_S}s 도 더 이상 맞지 않는다(실제 최장 phase 가 "
            f"{_I18N_HEALTHCHECK_SETUP_S}s 가 된다)."
        )
