"""CI 인바리언트 가드(parity): 락 가드의 pytest 구현과 supply-chain-lock.yml 인라인
미러가 동일 불변식을 동일 방식으로 보도록 강제한다.

배경: 락 staleness 불변식은 두 곳에서 중복 구현된다 —
  - pytest 가드: tests/test_requirements_lock_coverage.py(커버리지),
    tests/test_requirements_lock_version_sync.py(버전-동기).
  - 트리거-경로 미러: .github/workflows/supply-chain-lock.yml 의 인라인 python 스텝
    "Verify lock covers all direct dependencies" / "Verify lock pins satisfy
    requirements specifiers".
두 곳의 주석은 "같은 불변식을 같은 방식으로 본다"고 선언하지만, 그동안 이를 강제하는
테스트가 없었다. 한쪽의 정규식/플래그만 바뀌면 미러가 조용히 갈라져 한 경로의 탐지가
약화될 수 있다(OWASP CICD-SEC-1 Insufficient Flow Control).

이 가드: 각 불변식의 load-bearing 토큰(정규식·플래그)이 짝이 되는 pytest 파일과
워크플로우 스텝 블록에 **모두** 존재해야 한다. 방향=presence(어느 한쪽만 바뀌면 실패).
의도적 변경 시 양쪽을 함께 고치면 통과한다.

stdlib-only(라인/정규식 스캔) — PyYAML 미사용, 측정 소스 미import(커버리지 무영향),
network 없음.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
COVERAGE_TEST = REPO_ROOT / "tests" / "test_requirements_lock_coverage.py"
VERSION_SYNC_TEST = REPO_ROOT / "tests" / "test_requirements_lock_version_sync.py"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "supply-chain-lock.yml"

COVERS_STEP = "Verify lock covers all direct dependencies"
SATISFY_STEP = "Verify lock pins satisfy requirements specifiers"

# 각 불변식의 load-bearing 토큰 — 짝이 되는 두 텍스트에 모두 존재해야 한다.
# 커버리지: 락 핀 이름 추출 정규식(버전 캡처 없음).
COVERAGE_REGEX = r"(?:\[[^\]]*\])?=="
# 버전-동기: 버전까지 캡처하는 락 핀 정규식 + specifier 만족 검사 + prerelease 플래그.
VERSION_SYNC_MARKERS = (
    r"(?:\[[^\]]*\])?==([^\s\\]+)",
    ".specifier.contains(",
    "prereleases=True",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def _step_block(yaml_text: str, step_name: str) -> str:
    """`- name: <step_name>` 부터 다음 `- name:` 직전(또는 끝)까지의 블록 텍스트."""
    start = re.compile(r"^\s*- name:\s*" + re.escape(step_name) + r"\s*$")
    nxt = re.compile(r"^\s*- name:\s")
    out: list[str] = []
    capturing = False
    for line in yaml_text.splitlines():
        if start.match(line):
            capturing = True
            out.append(line)
            continue
        if capturing and nxt.match(line):
            break
        if capturing:
            out.append(line)
    return "\n".join(out)


# --- canary: 대상 파일/스텝이 사라지면 vacuous 통과 대신 실패 ---


def test_target_files_exist():
    for p in (COVERAGE_TEST, VERSION_SYNC_TEST, WORKFLOW):
        assert p.is_file(), f"{p} not found"


def test_workflow_step_blocks_present_and_nonempty():
    wf = _read(WORKFLOW)
    covers = _step_block(wf, COVERS_STEP)
    satisfy = _step_block(wf, SATISFY_STEP)
    assert covers.strip(), f"워크플로우에 '{COVERS_STEP}' 스텝 블록 없음/비어있음"
    assert satisfy.strip(), f"워크플로우에 '{SATISFY_STEP}' 스텝 블록 없음/비어있음"


# --- parity 불변식 ---


def test_coverage_invariant_mirrored():
    """커버리지 락 핀 정규식이 pytest 가드와 워크플로우 covers 스텝에 모두 존재."""
    covers = _step_block(_read(WORKFLOW), COVERS_STEP)
    test = _read(COVERAGE_TEST)
    assert COVERAGE_REGEX in test, f"커버리지 테스트에 락 핀 정규식 '{COVERAGE_REGEX}' 없음 — 가드 파손?"
    assert COVERAGE_REGEX in covers, (
        f"supply-chain-lock.yml '{COVERS_STEP}' 스텝과 커버리지 테스트의 락 핀 "
        f"정규식이 갈라짐('{COVERAGE_REGEX}' 미존재). 양쪽을 동일하게 유지하세요."
    )


def test_version_sync_invariant_mirrored():
    """버전-동기 불변식(정규식+specifier 검사+prerelease)이 양쪽에 모두 존재."""
    satisfy = _step_block(_read(WORKFLOW), SATISFY_STEP)
    test = _read(VERSION_SYNC_TEST)
    for marker in VERSION_SYNC_MARKERS:
        assert marker in test, f"버전-동기 테스트에 '{marker}' 없음 — 가드 파손?"
        assert marker in satisfy, (
            f"supply-chain-lock.yml '{SATISFY_STEP}' 스텝과 버전-동기 테스트가 "
            f"갈라짐('{marker}' 미존재). 양쪽을 동일 불변식으로 유지하세요."
        )


# --- non-vacuous: 합성 입력에서 갈라짐이 실제로 잡히는지 증명 ---


def test_step_block_extraction_isolates_named_step():
    wf = (
        "      - name: Verify lock covers all direct dependencies\n"
        "        run: |\n"
        "          echo COVERS\n"
        "      - name: Verify lock pins satisfy requirements specifiers\n"
        "        run: |\n"
        "          echo SATISFY prereleases=True\n"
    )
    covers = _step_block(wf, COVERS_STEP)
    satisfy = _step_block(wf, SATISFY_STEP)
    assert "COVERS" in covers and "SATISFY" not in covers
    assert "prereleases=True" in satisfy and "COVERS" not in satisfy


def test_parity_check_flags_divergence():
    """미러 스텝에서 prerelease 플래그가 사라지면 parity 가 깨져야 한다."""
    satisfy_diverged = (
        "      - name: Verify lock pins satisfy requirements specifiers\n"
        "        run: |\n"
        "          # prereleases 플래그가 제거됨 → 갈라짐\n"
        "          if not spec.contains(pin):\n"
        "              fail()\n"
    )
    block = _step_block(satisfy_diverged, SATISFY_STEP)
    assert "prereleases=True" not in block  # 갈라짐이 탐지됨
