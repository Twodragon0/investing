"""apt 설치 스텝의 진단 가능성·재시도 가드.

## 왜 있나

2026-09-09 `Collect Market Indicators` 런 34384107923 이 red 가 됐고, 자동
분류기는 `code` 로 판정해 이슈 #1299 를 열었다. 실제 실패 스텝은
`Install CJK fonts` 였고 종료 코드는 **100** — `apt-get` 이 미러에 닿지 못했을 때
내는 코드다. 즉 전형적인 일시적(transient) 실패다.

그런데 그 스텝은 이렇게 쓰여 있었다:

    sudo apt-get update -qq && sudo apt-get install -y -qq fonts-noto-cjk >/dev/null 2>&1

`2>&1` 이 stderr 를 `/dev/null` 로 보내므로 **apt 의 실패 사유가 로그에서 사라진다**.
남는 건 러너가 붙이는 `##[error]Process completed with exit code 100.` 한 줄뿐이다.
결과는 두 겹으로 나빴다:

1. 분류기가 볼 수 있는 transient 근거가 0건 → `code` 판정 → 자동 재시도 대신 이슈.
   (`classify_failure_log.py` 의 fail direction 은 "근거 없으면 code" 이고, 그건
   의도된 설계다. 근거를 지운 쪽이 잘못이다.)
2. 이슈의 "Classifier evidence" 블록에는 실패와 무관한
   `Verify SSL is enabled` 가드의 **자기 소스 echo** 가 실렸다.

재시도도 없었다. 미러 한 번 삐끗하면 수집 런 전체가 red 다.

## 이 가드가 지키는 것

`apt-get install` 을 하는 모든 `run:` 블록은

* 출력을 `/dev/null` 로 버리지 않는다 — 실패 사유가 로그에 남아야 분류기가
  `network` 로 읽고 자동 재시도할 수 있다;
* 재시도 루프를 가진다 — 일시적 미러 실패로 수집이 죽지 않게.

가드는 파일 원문이 아니라 **파싱된 `run:` 값만** 읽는다. 원문을 읽으면 이 파일의
설명 주석이나 워크플로우의 주석이 스스로에게 매칭돼 항상 green(또는 항상 red)이
된다.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
_WORKFLOWS_DIR = _REPO_ROOT / ".github" / "workflows"
_ACTIONS_DIR = _REPO_ROOT / ".github" / "actions"

# 출력을 버리는 리다이렉션. apt 는 `-qq` 로 이미 조용하므로, 여기에 더해
# `/dev/null` 로 보내는 건 실패 사유까지 지우는 것뿐이다.
_DISCARDS_OUTPUT = (">/dev/null", "> /dev/null")

# 재시도 의도를 드러내는 셸 구성. 어느 형태를 쓰든 상관없지만 하나는 있어야 한다.
_RETRY_MARKERS = ("for attempt", "for i in", "until ", "retry", "retries")


def _yaml_files() -> list[Path]:
    files: list[Path] = []
    if _WORKFLOWS_DIR.is_dir():
        files.extend(sorted(_WORKFLOWS_DIR.glob("*.yml")))
    if _ACTIONS_DIR.is_dir():
        files.extend(sorted(_ACTIONS_DIR.glob("*/action.yml")))
    return files


def _iter_run_blocks(node: object):
    """모든 중첩 깊이의 `run:` 문자열을 (step_name, run_text) 으로 내놓는다."""
    if isinstance(node, dict):
        run = node.get("run")
        if isinstance(run, str):
            name = node.get("name")
            yield (name if isinstance(name, str) else "<unnamed step>", run)
        for value in node.values():
            yield from _iter_run_blocks(value)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_run_blocks(item)


def _apt_install_steps() -> list[tuple[Path, str, str]]:
    found: list[tuple[Path, str, str]] = []
    for path in _yaml_files():
        try:
            doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:  # pragma: no cover - 파싱 불가는 다른 가드 소관
            pytest.fail(f"{path.relative_to(_REPO_ROOT)} could not be parsed: {exc}")
        for step_name, run in _iter_run_blocks(doc):
            if "apt-get install" in run:
                found.append((path, step_name, run))
    return found


def test_repo_actually_has_apt_install_steps() -> None:
    """대상이 0건이면 아래 두 검사는 아무것도 증명하지 않는다."""
    steps = _apt_install_steps()
    assert steps, "no `apt-get install` step found — this guard would be vacuously green"


@pytest.mark.parametrize(
    ("path", "step_name", "run"), _apt_install_steps(), ids=lambda v: getattr(v, "name", str(v))[:40]
)
def test_apt_install_does_not_discard_its_output(path: Path, step_name: str, run: str) -> None:
    offending = [line.strip() for line in run.splitlines() if any(tok in line for tok in _DISCARDS_OUTPUT)]
    assert not offending, (
        f"{path.relative_to(_REPO_ROOT)} :: {step_name!r} discards apt output.\n"
        f"  {chr(10).join(offending)}\n"
        "An apt mirror failure exits 100 with its reason on stderr. Discarding it "
        "leaves the classifier no transient evidence, so a retryable failure gets "
        "filed as a code bug (run 34384107923 -> issue #1299)."
    )


@pytest.mark.parametrize(
    ("path", "step_name", "run"), _apt_install_steps(), ids=lambda v: getattr(v, "name", str(v))[:40]
)
def test_apt_install_retries(path: Path, step_name: str, run: str) -> None:
    assert any(marker in run for marker in _RETRY_MARKERS), (
        f"{path.relative_to(_REPO_ROOT)} :: {step_name!r} runs apt-get install without a retry.\n"
        "A single transient mirror error otherwise reds the whole run."
    )
