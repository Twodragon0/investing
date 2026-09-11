"""워크플로우 스캐너 공통 헬퍼 — 가드는 **실행되는 내용**만 읽어야 한다.

## 왜 있나

이 저장소의 워크플로우 가드는 같은 결함으로 반복해서 터졌다. 파일 원문을 문자열로
검색하면 **실행되지 않는 산문**(YAML 주석, `run:` 안의 셸 주석, 설명 문단)에
매칭된다. 양방향으로 틀린다:

* **false-green** — 2026-09-10 `component_counts.main_push_workflows()` 가
  `action-pin-verify.yml` 을 "main 직접 푸시" 로 셌다. 그 파일은 아무것도 푸시하지
  않고, 주석이 액션 핀 라벨 사례로 `git-auto-commit-action` 을 언급할 뿐이다.
  같은 날 `reports-e2e.yml` 도 상호참조 주석 때문에 들어갔다 — 그 주석은 몇 시간
  전 다른 PR 이 넣은 것이다.
* **false-red** — 2026-09-02 에 두 번, 2026-09-11 에 한 번 실측됐다.
  `test_coverage_floor_guard` 는 coverage gate 스텝 안에
  `# continue-on-error: true 는 여기서 쓰지 않는다` 라는 **금지를 설명하는 주석**만
  넣어도 red 가 됐다. 가드가 자기 설명에 걸린 것이다.

false-red 가 더 고약하다. 원인이 "고치라고 적어 둔 문장" 이라 읽는 사람이 진짜
위반을 찾느라 시간을 쓴다.

## 규약

워크플로우에서 **행동**(무엇을 실행하는가, 어떤 설정이 걸렸는가)을 판정하는 가드는
이 모듈을 쓴다. 세 함수면 충분하다:

    steps(path)              # 파싱된 step 매핑들
    run_blocks(path)         # (step 이름, 셸 주석을 걷어낸 run 텍스트)
    strip_shell_comments(s)  # run 문자열 하나에 대해

## 예외 — 원문을 읽는 것이 맞는 경우

주석 **자체가 검사 대상**인 가드는 이 모듈을 쓰면 안 된다. 예:
`tests/test_workflow_action_version_label_guard.py` 는 `uses: x@<sha>  # v1.2.3`
의 라벨이 업스트림 태그와 맞는지 본다 — 라벨은 주석이고, 그게 요점이다.

그런 가드는 다음 표식을 파일에 남긴다(메타 가드가 이 문자열을 찾는다):

    # scanner: raw-text intentional — <이유>
"""

from __future__ import annotations

import re
from collections.abc import Iterator  # noqa: TC003 - 런타임 애노테이션 평가에 필요
from pathlib import Path  # noqa: TC003 - 기본 인자/런타임 사용

import yaml

#: 예외를 선언하는 표식. 메타 가드가 이 접두어를 찾는다.
RAW_TEXT_OPT_OUT = "scanner: raw-text intentional"

_TRAILING_COMMENT_RE = re.compile(r"\s+#(?=\s).*$")


def strip_shell_comments(run: str) -> str:
    """`run:` 블록에서 셸 주석을 제거한다.

    "원문 말고 `run:` 을 읽어라" 만으로는 부족하다 — `run:` **값 안에도** 주석이
    있고 그것도 실행되지 않는다. 2026-09-10 실측: 배선 검사가 `run:` 안의 설명
    주석에 매칭돼, 워크플로우가 아직 리터럴 핀을 쓰고 있는데도 green 을 냈다.

    셸 파서를 흉내 내지 않는다. 줄 전체가 주석인 경우와, 공백 뒤에 오는 `#` 부터
    줄 끝까지만 자른다. `#` 이 따옴표 안에 있을 수 있으므로(URL 프래그먼트 등)
    공백을 요구해 오탐을 줄인다.
    """
    kept = []
    for line in run.splitlines():
        if line.lstrip().startswith("#"):
            continue
        kept.append(_TRAILING_COMMENT_RE.sub("", line))
    return "\n".join(kept)


def _iter_steps(node: object) -> Iterator[dict]:
    if isinstance(node, dict):
        if "uses" in node or "run" in node:
            yield node
        for value in node.values():
            yield from _iter_steps(value)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_steps(item)


def load(path: Path) -> object:
    """파싱된 워크플로우/액션 문서. 파싱 실패는 호출자에게 맡긴다."""
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def steps(path: Path) -> list[dict]:
    """모든 중첩 깊이의 step 매핑.

    composite action(`runs.steps`)과 워크플로우(`jobs.<id>.steps`)를 모두 덮으므로
    호출자가 구조를 알 필요가 없다.
    """
    return list(_iter_steps(load(path)))


def run_blocks(path: Path) -> list[tuple[str, str]]:
    """(step 이름, 셸 주석을 걷어낸 `run:` 텍스트).

    이름이 없는 step 은 `"<unnamed step>"` 으로 준다 — 실패 메시지에서 위치를
    가리키는 용도이므로 비워 두지 않는다.
    """
    out: list[tuple[str, str]] = []
    for step in steps(path):
        run = step.get("run")
        if isinstance(run, str):
            name = step.get("name")
            out.append((name if isinstance(name, str) else "<unnamed step>", strip_shell_comments(run)))
    return out


def step_text(step: dict) -> str:
    """step 의 실행 관련 값만 이어 붙인 텍스트.

    `continue-on-error` 같은 **step 수준 설정**과 `run:`/`uses:` 를 한 번에 훑어야
    하는 가드를 위한 것이다. 값만 담으므로 주석은 구조적으로 들어올 수 없다.
    """
    parts: list[str] = []
    for key, value in step.items():
        if key == "run" and isinstance(value, str):
            parts.append(strip_shell_comments(value))
        elif isinstance(value, (str, int, float, bool)):
            parts.append(f"{key}: {value}")
    return "\n".join(parts)
