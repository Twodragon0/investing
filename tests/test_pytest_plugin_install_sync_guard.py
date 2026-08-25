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


def _ini_options() -> dict:
    data = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
    return data.get("tool", {}).get("pytest", {}).get("ini_options", {})


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

    2026-08-24 `--durations=15` 실측 최장은 48.6s
    (`test_dedup_idempotent_social` — `collect_social_media.py` 의 실제
    `time.sleep(1)/(2)` 가 대부분이다). sleep 은 wall-clock 이라 CI 에서도 거의
    같다. 여유 4배를 최소 조건으로 둔다.
    """
    slowest_observed = 48.6
    timeout = _ini_options().get("timeout")
    if timeout is None:
        pytest.skip("pyproject 가 timeout 을 선언하지 않음")
    assert timeout >= slowest_observed * 4, (
        f"timeout={timeout}s 는 실측 최장 테스트 {slowest_observed}s 대비 여유가 부족하다. "
        "너무 낮으면 느린 러너에서 flaky red 가 된다 — 낮추려면 먼저 "
        "`pytest --durations` 로 다시 재고 이 상수를 갱신할 것."
    )
