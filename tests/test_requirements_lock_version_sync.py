"""CI 인바리언트 가드: requirements.lock 의 핀 버전이 requirements.txt 명세를 만족.

배경: 기존 tests/test_requirements_lock_coverage.py 와 supply-chain-lock.yml 의
커버리지 검사는 **이름 기반**이라, 직접 의존성의 *버전 bump 후 락 미갱신*(stale)을
잡지 못한다. 예: requirements.txt 에서 `requests==2.33.1 → 2.34.0` 으로 올리고
락을 재생성하지 않으면 두 가드 모두 green 인데 락은 2.33.1 을 핀한 채 남는다 —
런타임은 신버전 설치, 무결성 검증은 구버전. 2026-07-06 차단 승격 후 잠재 리스크.

이 가드의 단일 불변식:
    직접 의존성마다 락의 핀 버전이 requirements.txt 의 PEP 508 specifier 를 만족한다.

packaging.SpecifierSet.contains() 로 정확 핀(==)과 범위 제약(>=,~=,<,...)을 동시에 커버:
  - txt `requests==2.34.0`, lock `2.33.1`  → 불만족 → 차단(정확 핀 bump stale).
  - txt `boto3>=1.44,<2`,  lock `1.43.36` → 불만족 → 차단(범위 floor 상향이 락 핀 이탈).
  - txt `boto3>=1.40,<2`,  lock `1.43.36` → 만족  → 통과(락이 범위 내 = stale 아님, 앵커 결정성).

비목표(의도): "범위 내 더 최신이 있다"는 stale 이 아니라 결정성이므로 검사하지 않는다.
전이 의존성 버전은 검사하지 않는다(--require-hashes 무결성이 담당). 이름 부재(커버리지)는
test_requirements_lock_coverage.py 책임 — 본 가드는 *버전 불일치*에만 발화(중복 없음).

network 없음: 설치/해소 없이 txt 명세와 락 핀의 정적 대조만 수행.
packaging 은 락의 전이 의존성(packaging==26.2)이자 pip 의존성이라 항상 설치돼 있다.
"""

from __future__ import annotations

import re
from pathlib import Path

from packaging.requirements import InvalidRequirement, Requirement
from packaging.version import InvalidVersion, Version

REPO_ROOT = Path(__file__).resolve().parent.parent
REQUIREMENTS_TXT = REPO_ROOT / "scripts" / "requirements.txt"
REQUIREMENTS_LOCK = REPO_ROOT / "scripts" / "requirements.lock"

# 인라인 주석(`pkg==1.0  # 설명`) 제거용 — PEP 508 마커에는 '#' 가 없어 안전.
_INLINE_COMMENT = re.compile(r"\s+#.*$")
# 락 핀 라인: name==ver 또는 name[extra1,extra2]==ver (컬럼 0).
_LOCK_PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]*\])?==([^\s\\]+)")


def _norm(name: str) -> str:
    return name.lower().replace("_", "-")


def direct_specifiers(text: str) -> dict[str, Requirement]:
    """requirements.txt 의 직접 의존성 이름(정규화) → Requirement."""
    out: dict[str, Requirement] = {}
    for raw in text.splitlines():
        line = _INLINE_COMMENT.sub("", raw.strip())
        if not line or line.startswith("#"):
            continue
        try:
            req = Requirement(line)
        except InvalidRequirement:  # noqa: S112 — 파싱 불가 라인은 본 가드 범위 밖(의도적 skip)
            continue
        out[_norm(req.name)] = req
    return out


def locked_versions(text: str) -> dict[str, Version]:
    """락의 ==핀 이름(정규화) → Version."""
    out: dict[str, Version] = {}
    for raw in text.splitlines():
        m = _LOCK_PIN.match(raw)
        if not m:
            continue
        try:
            out[_norm(m.group(1))] = Version(m.group(2))
        except InvalidVersion:
            continue
    return out


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


# --- canary: 대상 파일이 옮겨지거나 사라지면 vacuous 통과 대신 실패 ---


def test_target_files_exist_and_nonempty():
    assert REQUIREMENTS_TXT.is_file(), f"{REQUIREMENTS_TXT} not found"
    assert REQUIREMENTS_LOCK.is_file(), f"{REQUIREMENTS_LOCK} not found"
    assert _read(REQUIREMENTS_TXT).strip(), "requirements.txt 가 비어있음"
    assert _read(REQUIREMENTS_LOCK).strip(), "requirements.lock 이 비어있음"


def test_parsers_extract_nonempty_sets():
    direct = direct_specifiers(_read(REQUIREMENTS_TXT))
    locked = locked_versions(_read(REQUIREMENTS_LOCK))
    assert direct, "직접 의존성 명세를 하나도 추출하지 못함 — 파서 파손 또는 파일 이동"
    assert locked, "락 핀을 하나도 추출하지 못함 — 파서 파손 또는 파일 형식 변경"


# --- 핵심 불변식 ---


def test_lock_pins_satisfy_requirements_specifiers():
    """락의 핀 버전이 requirements.txt 의 PEP 508 명세를 만족해야 한다."""
    direct = direct_specifiers(_read(REQUIREMENTS_TXT))
    locked = locked_versions(_read(REQUIREMENTS_LOCK))
    violations = []
    for name, req in direct.items():
        pin = locked.get(name)
        if pin is None:
            # 이름 부재 = 커버리지 가드(test_requirements_lock_coverage.py) 책임.
            continue
        # prereleases=True: false-negative 방지(현 의존성에 prerelease 없음).
        if not req.specifier.contains(pin, prereleases=True):
            violations.append(f"{name}: txt '{req.specifier}' ↛ lock '{pin}'")
    assert not violations, (
        "락 핀이 requirements.txt 명세를 만족하지 않음(버전 bump 후 락 미갱신?):\n"
        + "\n".join(violations)
        + "\n→ bash scripts/refresh_requirements_lock.sh 로 락 재생성."
    )


# --- non-vacuous: negative — 합성 입력에서 assertion 이 실제로 trip 하는지 증명 ---


def test_flags_exact_pin_bump_stale():
    """정확 핀 bump 후 락 미갱신 케이스가 잡혀야 한다."""
    direct = direct_specifiers("requests==2.34.0\n")
    locked = locked_versions("requests==2.33.1 \\\n    --hash=sha256:dead\n")
    req = direct["requests"]
    assert not req.specifier.contains(locked["requests"], prereleases=True)


def test_flags_range_floor_raise_stale():
    """범위 floor 상향이 락 핀을 벗어나는 케이스가 잡혀야 한다."""
    direct = direct_specifiers("boto3>=1.44,<2\n")
    locked = locked_versions("boto3==1.43.36 \\\n    --hash=sha256:dead\n")
    req = direct["boto3"]
    assert not req.specifier.contains(locked["boto3"], prereleases=True)


def test_accepts_lock_within_range():
    """락이 범위 내면 통과해야 한다(범위 내 최신성은 stale 아님 — 결정성)."""
    direct = direct_specifiers("boto3>=1.40,<2\n")
    locked = locked_versions("boto3==1.43.36 \\\n    --hash=sha256:dead\n")
    req = direct["boto3"]
    assert req.specifier.contains(locked["boto3"], prereleases=True)


def test_parser_handles_extras_markers_and_normalization():
    """extras / 환경 마커 / 대소문자·언더스코어 정규화 케이스."""
    direct = direct_specifiers("Foo_Bar[extra]==1.0 ; python_version < '3.12'\nBAZ>=2.0  # inline comment\n")
    assert "foo-bar" in direct
    assert "baz" in direct
    locked = locked_versions("foo-bar[extra]==1.0 \\\n    --hash=sha256:dead\n")
    assert locked["foo-bar"] == Version("1.0")
