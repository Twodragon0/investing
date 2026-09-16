#!/usr/bin/env python3
r"""Dependabot 커밋 메시지에서 `update-type`(semver 변화 등급)을 판정한다.

## 왜 이 모듈이 필요한가

`dependabot-auto-merge.yml` 은 `dependabot/fetch-metadata` 액션의 `update-type`
출력으로 자동 머지 대상을 가른다. 그런데 **그 액션은 `pull_request` /
`pull_request_target` 전용**이다 (2026-09-16 upstream 확인):

* `src/dependabot/verified_commits.ts:20` 이 이벤트 페이로드의 `pull_request` 키를
  요구하고, 없으면 *"Make sure you're triggering this action on the `pull_request`
  or `pull_request_target` events"* 로 실패한다.
* `action.yml` 의 inputs 5개(`alert-lookup`, `compat-lookup`, `github-token`,
  `skip-commit-verification`, `skip-verification`) 중 **PR 번호를 넘기는 것이 없다.**

따라서 `schedule` 스위퍼(열린 dependabot PR 을 주기적으로 순회해 머지하는 구조)는
그 액션을 쓸 수 없다. 이 모듈은 그 자리를 메운다.

## 취약하지 않은 이유 — 같은 출처를 읽는다

PR 제목을 파싱하는 방식이 아니다. `fetch-metadata` **자신이 읽는 원본**이 dependabot
커밋 메시지이고(`src/dependabot/update_metadata.ts:69-81`), 같은 데이터를
`gh api repos/{o}/{r}/pulls/{n}/commits` 로 얻을 수 있다.

## upstream 동작을 그대로 재현한다 (아티팩트 포함)

판정 결과가 액션과 **달라지면 안 된다.** 스위퍼가 액션보다 넓게 머지하는 순간
"자동 머지 대상 집합"이 조용히 바뀌기 때문이다. 그래서 알려진 파싱 아티팩트까지
재현한다:

    chore(deps): update boto3 requirement from <2,>=1.43.92 to >=1.43.93,<2

이 줄에서 `from` 캡처는 `2,>=1.43.92` 가 된다 — 정규식의 `\S*?` 가 이전 제약의
상한 `<2,` 중 `<` 만 삼키고 멈추기 때문이다. 결과적으로 `lastParts[0] == "2,>=1"`,
`nextParts[0] == "1"` 이 되어 **패치 크기 bump 가 `semver-major` 로 떨어진다**.
#1321 · #1329 가 그렇게 분류돼 자동 머지 경로를 타지 못했다(실측).

이것은 의미 판단이 아니라 버그로 보이지만, **여기서 고치지 않는다.** 고치면 스위퍼가
액션과 다르게 동작한다. 분류를 바로잡는 것은 별도 결정이며, 그때는 이 모듈이 아니라
호출부의 정책으로 다뤄야 한다(그래야 "액션과 일치" 라는 이 모듈의 계약이 유지된다).

고정 대상 upstream: `dependabot/fetch-metadata` v3.1.0
(`25dd0e34f4fe68f24cc83900b1fe3fe149efef98`). 로직 출처는
`src/dependabot/update_metadata.ts:69-176`, `src/dependabot/output.ts:10-14,79-86`.
upstream 을 올릴 때 `tests/fixtures/dependabot_commits/manifest.json` 의 기대값을
다시 확인할 것.

## 사용법

    python3 scripts/tools/dependabot_update_type.py --branch <브랜치명> [커밋메시지파일]
    gh api repos/o/r/pulls/123/commits --jq '.[0].commit.message' \
      | python3 scripts/tools/dependabot_update_type.py --branch dependabot/pip/x

판정 불가(형식 불일치, dependabot 브랜치 아님 등)는 빈 문자열을 출력하고 종료코드 1.
액션도 메타데이터를 못 찾으면 실패 코드를 낸다.
"""

from __future__ import annotations

import argparse
import re
import sys

import yaml

#: upstream `output.ts:10-14`. 여러 의존성이 한 PR 에 있으면 **가장 큰** 변화를 쓴다.
UPDATE_TYPES_PRIORITY = (
    "version-update:semver-major",
    "version-update:semver-minor",
    "version-update:semver-patch",
)

#: upstream `update_metadata.ts:70-74`. 표기를 바꾸지 말 것 — 아티팩트까지 동일해야 한다.
_UPDATE_RE = re.compile(r"\b[Uu]pdate .* requirement from \S*? ?(?P<from>v?\d\S*) to \S*? ?(?P<to>v?\d\S*)")
_BUMP_RE = re.compile(r"^Bumps .* from (?P<from>v?\d[^ ]*) to (?P<to>v?\d[^ ]*)\.$", re.M)
_YAML_RE = re.compile(r"^-{3}\n(?P<dependencies>[\S\s]*?)\n^\.{3}\n", re.M)


def calculate_update_type(last_version: str, next_version: str) -> str:
    """upstream `update_metadata.ts:159-176` 의 축자 이식.

    semver 파서를 쓰지 않는다 — upstream 이 문자열을 `.` 으로 쪼개 비교할 뿐이라,
    파서를 쓰면 위 아티팩트가 재현되지 않는다.
    """
    if not last_version or not next_version or last_version == next_version:
        return ""

    last_parts = last_version.replace("v", "").split(".")
    next_parts = next_version.replace("v", "").split(".")

    if last_parts[0] != next_parts[0]:
        return "version-update:semver-major"
    if len(last_parts) < 2 or len(next_parts) < 2 or last_parts[1] != next_parts[1]:
        return "version-update:semver-minor"
    return "version-update:semver-patch"


def parse_update_type(commit_message: str, branch_name: str) -> str:
    """커밋 메시지 + 브랜치명에서 `update-type` 을 판정한다. 판정 불가면 빈 문자열.

    upstream 과 같은 조건을 요구한다 — YAML 조각이 있고 브랜치가 `dependabot` 으로
    시작할 것(`update_metadata.ts:80`). 둘 중 하나라도 어긋나면 액션도 메타데이터를
    만들지 않는다.
    """
    yaml_match = _YAML_RE.search(commit_message)
    if not yaml_match or not branch_name.startswith("dependabot"):
        return ""

    try:
        data = yaml.safe_load(yaml_match.group("dependencies"))
    except yaml.YAMLError:
        return ""
    if not isinstance(data, dict) or not data.get("updated-dependencies"):
        return ""

    # upstream `update_metadata.ts:71-72`: `Bumps …` 는 메시지 **전체**에서(그 줄은
    # 보통 3번째다), `Update … requirement` 는 **첫 줄**에서만 찾는다. 순서도 같다 —
    # bump 가 우선이다.
    #
    # 한 변수에 담아 두는 이유: `(bump or update).group(...) if (bump or update)` 로
    # 쓰면 두 번 평가라 타입 narrowing 이 되지 않는다(basedpyright
    # `reportOptionalMemberAccess`, 2026-09-16 CI 에서 실제로 걸렸다).
    version_match = _BUMP_RE.search(commit_message) or _UPDATE_RE.search(commit_message.split("\n")[0])
    prev = version_match.group("from") if version_match else ""
    nxt = version_match.group("to") if version_match else ""

    levels: set[str] = set()
    for index, dependency in enumerate(data["updated-dependencies"]):
        if not isinstance(dependency, dict):
            continue
        # upstream `update_metadata.ts:100-103`: 첫 의존성만 커밋 메시지의 from/to 를
        # 물려받는다. 둘째부터는 YAML 의 값에만 의존한다.
        last_version = prev if index == 0 else ""
        next_version = dependency.get("dependency-version") or (nxt if index == 0 else "")
        levels.add(dependency.get("update-type") or calculate_update_type(last_version, next_version))

    for level in UPDATE_TYPES_PRIORITY:
        if level in levels:
            return level
    return ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Dependabot 커밋 메시지에서 update-type 판정")
    parser.add_argument("message_file", nargs="?", help="커밋 메시지 파일 (생략 시 stdin)")
    parser.add_argument("--branch", required=True, help="PR 의 head 브랜치명")
    args = parser.parse_args(argv)

    if args.message_file:
        try:
            with open(args.message_file, encoding="utf-8") as handle:
                message = handle.read()
        except OSError as exc:
            print(f"could not read {args.message_file}: {exc}", file=sys.stderr)
            return 2
    else:
        message = sys.stdin.read()

    update_type = parse_update_type(message, args.branch)
    if not update_type:
        print(
            "update-type 을 판정하지 못했다 (YAML 조각 부재, 비-dependabot 브랜치, 또는 버전 추출 실패)",
            file=sys.stderr,
        )
        return 1

    sys.stdout.write(update_type + "\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI 진입점
    raise SystemExit(main())
