"""`scripts/tools/dependabot_update_type.py` 가 upstream 액션과 **같은 답**을 내는지 고정한다.

## 왜 있나

이 모듈의 계약은 "정확히 분류한다" 가 아니라 **"`dependabot/fetch-metadata` 와 같게
분류한다"** 이다. 스위퍼가 액션보다 넓게(또는 좁게) 머지하면 자동 머지 대상 집합이
조용히 바뀌기 때문이다.

그래서 fixture 의 기대값은 이 모듈의 출력이 아니라 **실제 액션 런이 낸 값**이다
(`manifest.json` 의 `observed_in_run`). 골든을 구현으로부터 만들면 구현의 버그가
그대로 골든이 된다.

## 아티팩트를 일부러 고정한다

#1321 · #1329(boto3 범위 제약 bump)는 패치 크기인데 `semver-major` 로 분류된다.
`from` 캡처가 이전 제약의 상한에서 `2,>=` 를 삼키기 때문이다. **버그로 보이지만 그대로
재현하는 것이 이 모듈의 목적**이므로, 그 기대값을 테스트로 못 박는다. 나중에 누가
"버그니까 고치자" 며 정규식을 손보면 이 테스트가 red 가 되어, 그 변경이 **액션과의
일치를 깨는 결정**임을 알린다.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from tools.dependabot_update_type import (  # noqa: E402
    calculate_update_type,
    parse_update_type,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_FIXTURES = _REPO_ROOT / "tests" / "fixtures" / "dependabot_commits"
_SCRIPT = _REPO_ROOT / "scripts" / "tools" / "dependabot_update_type.py"


def _manifest() -> dict:
    return json.loads((_FIXTURES / "manifest.json").read_text(encoding="utf-8"))


def _cases() -> list[dict]:
    cases = _manifest()["cases"]
    assert cases, "fixture manifest 가 비었다 — 이 테스트가 아무것도 지키지 않는다"
    return cases


@pytest.mark.parametrize("case", _cases(), ids=lambda c: f"pr{c['pr']}")
def test_matches_the_update_type_the_action_produced(case: dict) -> None:
    """각 fixture 에서 실제 액션 런이 낸 값과 동일해야 한다."""
    message = (_FIXTURES / f"pr-{case['pr']}.txt").read_text(encoding="utf-8")
    got = parse_update_type(message, case["branch"])
    assert got == case["expected"], (
        f"PR #{case['pr']}: 기대 {case['expected']!r} (런 {case['observed_in_run']} 관측), 실제 {got!r}.\n"
        f"{case['note']}"
    )


def test_range_constraint_artifact_is_reproduced() -> None:
    """범위 제약 bump 가 major 로 떨어지는 아티팩트를 **의도적으로** 고정한다.

    이 단언이 red 가 되면 정규식을 "고친" 것이다. 그건 버그 수정이 아니라
    **액션과의 일치를 깨는 결정**이므로, 호출부 정책과 함께 논의해야 한다.
    """
    artifact_cases = [c for c in _cases() if "아티팩트" in c["note"]]
    assert artifact_cases, "아티팩트 케이스가 fixture 에서 사라졌다 — 회귀 감시 대상이 없어졌다"
    for case in artifact_cases:
        message = (_FIXTURES / f"pr-{case['pr']}.txt").read_text(encoding="utf-8")
        assert parse_update_type(message, case["branch"]) == "version-update:semver-major"


class TestCalculateUpdateType:
    """upstream `update_metadata.ts:159-176` 축자 이식의 경계."""

    @pytest.mark.parametrize(
        ("last", "nxt", "expected"),
        [
            ("1.2.3", "1.2.4", "version-update:semver-patch"),
            ("1.2.3", "1.3.0", "version-update:semver-minor"),
            ("1.2.3", "2.0.0", "version-update:semver-major"),
            ("v1.2.3", "v1.2.4", "version-update:semver-patch"),
            # 한쪽에 마이너가 없으면 minor 로 본다(upstream 의 length < 2 분기).
            ("1", "1", ""),
            ("1.2", "1.2", ""),
            ("2", "3", "version-update:semver-major"),
            ("1.2.3", "1.2.3", ""),
            ("", "1.2.3", ""),
            ("1.2.3", "", ""),
            # 아티팩트의 핵심 — 숫자가 아닌 찌꺼기가 섞이면 문자열 비교가 갈린다.
            ("2,>=1.43.92", "1.43.93,<2", "version-update:semver-major"),
        ],
    )
    def test_boundaries(self, last: str, nxt: str, expected: str) -> None:
        assert calculate_update_type(last, nxt) == expected

    def test_does_not_use_a_semver_parser(self) -> None:
        """semver 파서를 쓰면 아티팩트가 사라져 액션과 어긋난다.

        `"2,>=1.43.92"` 는 어떤 semver 파서로도 파싱되지 않는다. 그런데도 upstream 은
        답을 내므로(문자열 split), 이 입력이 예외 없이 major 를 내는지로 구현 방식을
        판별한다.
        """
        assert calculate_update_type("2,>=1.43.92", "1.43.93,<2") == "version-update:semver-major"


class TestRejectsWhatTheActionRejects:
    def test_non_dependabot_branch_yields_nothing(self) -> None:
        """upstream `update_metadata.ts:80` 이 브랜치 접두사를 요구한다."""
        message = (_FIXTURES / "pr-1328.txt").read_text(encoding="utf-8")
        assert parse_update_type(message, "feature/my-branch") == ""

    def test_missing_yaml_fragment_yields_nothing(self) -> None:
        assert parse_update_type("chore: 평범한 커밋\n\n본문\n", "dependabot/pip/x") == ""

    def test_malformed_yaml_yields_nothing_instead_of_raising(self) -> None:
        broken = "chore(deps): update x requirement from 1.0.0 to 1.0.1\n\n---\n: : :\n...\n"
        assert parse_update_type(broken, "dependabot/pip/x") == ""


class TestCli:
    def test_prints_update_type_and_exits_zero(self) -> None:
        case = _cases()[0]
        proc = subprocess.run(
            [sys.executable, str(_SCRIPT), str(_FIXTURES / f"pr-{case['pr']}.txt"), "--branch", case["branch"]],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.strip() == case["expected"]

    def test_exits_nonzero_when_undecidable(self) -> None:
        """판정 실패를 0 으로 끝내면 호출부가 빈 문자열을 '판정됨' 으로 읽는다."""
        proc = subprocess.run(
            [sys.executable, str(_SCRIPT), "--branch", "feature/not-dependabot"],
            input="chore: 아무 커밋\n",
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert proc.returncode == 1
        assert proc.stdout.strip() == ""
        assert proc.stderr.strip()


def test_fixture_manifest_records_upstream_pin() -> None:
    """upstream 을 올릴 때 기대값을 재확인하도록 핀을 기록해 둔다."""
    upstream = _manifest()["upstream"]
    assert upstream["sha"], "upstream SHA 가 비었다"
    workflow = (_REPO_ROOT / ".github" / "workflows" / "dependabot-auto-merge.yml").read_text(encoding="utf-8")
    assert upstream["sha"] in workflow, (
        f"manifest 의 upstream SHA {upstream['sha']} 가 워크플로우의 액션 핀과 다르다. "
        "액션을 올렸다면 fixture 기대값을 실제 런으로 다시 확인할 것."
    )
