"""CI 인바리언트 가드: requirements.lock 이 모든 직접 의존성을 해시 핀으로 커버.

배경: 2026-06-22 추가형(additive) 공급망 방어로 scripts/requirements.lock
(pip-compile --generate-hashes — 직접+전이 의존성 전체, 휠 해시 포함)을 도입했다.
.github/workflows/supply-chain-lock.yml 이 동일 불변식을 검사하지만, 그 워크플로우는
requirements.{txt,lock} 변경 시에만 트리거된다(paths 필터). 이 가드는 일반 pytest
잡(Code Quality)에서 매 PR 실행돼, 락 staleness/hashless 회귀를 워크플로우 트리거
이전에 — 로컬에서도 — 잡는다.

불변식:
  1. 커버리지: requirements.txt 의 모든 직접 의존성 이름이 락에 ==핀으로 존재
     (direct ⊆ locked). requirements.txt 에 의존성을 추가/제거하고 락을 재생성하지
     않으면 trip → 락 staleness(검증되지 않는 새 의존성) 차단.
  2. 해시 presence: 락의 모든 ==핀 라인이 최소 1개의 --hash 를 보유. hashless 핀이
     섞이면 --require-hashes 무결성 검증이 그 패키지에 대해 무력화되므로 차단.

방향: 커버리지=부분집합(direct ⊆ locked), 해시=presence(모든 핀에 1+).
의도적 의존성 변경 시 락을 재생성하면(supply-chain-lock.yml 상단 주석 참고) 그대로 통과.
stdlib-only(정규식 라인 스캔) — 측정 대상 소스를 import 하지 않아 커버리지 무영향,
network 없음(실제 설치/해시 다운로드 검증은 supply-chain-lock.yml 책임).

regex 는 supply-chain-lock.yml 의 인라인 "Verify lock covers all direct dependencies"
스텝과 의도적으로 동일하게 유지한다(두 곳이 같은 불변식을 같은 방식으로 본다).
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
REQUIREMENTS_TXT = REPO_ROOT / "scripts" / "requirements.txt"
REQUIREMENTS_LOCK = REPO_ROOT / "scripts" / "requirements.lock"


def direct_names(text: str) -> set[str]:
    """requirements.txt 의 직접 의존성 이름(정규화) 집합."""
    names = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # PEP 508 이름만 추출 (>=, ==, ~=, <, ; extras 앞부분)
        m = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)", line)
        if m:
            names.add(m.group(1).lower().replace("_", "-"))
    return names


def locked_names(text: str) -> set[str]:
    """락의 ==핀 이름(정규화) 집합 — name==ver 또는 name[extra]==ver."""
    names = set()
    for raw in text.splitlines():
        m = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]*\])?==", raw)
        if m:
            names.add(m.group(1).lower().replace("_", "-"))
    return names


def pins_with_hash_flag(text: str) -> dict[str, bool]:
    """락의 각 ==핀 이름 → 그 핀 블록이 최소 1개 --hash 를 보유하는지.

    pip-compile 형식: 핀 라인은 컬럼 0, 이어지는 `    --hash=...` / `    # via` 는
    들여쓰기. 들여쓴 줄이나 빈 줄까지를 핀 블록으로 본다. 다음 컬럼 0 핀/주석을 만나면
    블록 종료.
    """
    result: dict[str, bool] = {}
    current: str | None = None
    for raw in text.splitlines():
        m = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]*\])?==", raw)
        if m:
            current = m.group(1).lower().replace("_", "-")
            result.setdefault(current, "--hash=" in raw)
            if "--hash=" in raw:
                result[current] = True
        elif current is not None and (raw.startswith(" ") or raw.startswith("\t")):
            if "--hash=" in raw:
                result[current] = True
        elif raw.strip() == "":
            continue
        else:
            # 컬럼 0 의 비핀/주석 라인 → 현재 블록 종료
            current = None
    return result


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


# --- canary: 대상 파일이 옮겨지거나 사라지면 vacuous 하게 통과하지 말고 실패 ---


def test_target_files_exist_and_nonempty():
    assert REQUIREMENTS_TXT.is_file(), f"{REQUIREMENTS_TXT} not found"
    assert REQUIREMENTS_LOCK.is_file(), f"{REQUIREMENTS_LOCK} not found"
    assert _read(REQUIREMENTS_TXT).strip(), "requirements.txt 가 비어있음"
    assert _read(REQUIREMENTS_LOCK).strip(), "requirements.lock 이 비어있음"


def test_lock_covers_all_direct_dependencies():
    """requirements.txt 의 모든 직접 의존성이 락에 ==핀으로 존재해야 한다."""
    direct = direct_names(_read(REQUIREMENTS_TXT))
    locked = locked_names(_read(REQUIREMENTS_LOCK))
    assert direct, "직접 의존성을 하나도 추출하지 못함 — 가드 파손 또는 파일 이동"
    missing = sorted(direct - locked)
    assert not missing, (
        f"requirements.lock 이 다음 직접 의존성을 핀하지 않음: {missing}\n"
        "requirements.txt 변경 후 락을 재생성하세요: "
        "pip-compile --generate-hashes --output-file scripts/requirements.lock "
        "scripts/requirements.txt (supply-chain-lock.yml 상단 주석 참고)."
    )


def test_every_lock_pin_carries_a_hash():
    """락의 모든 ==핀이 최소 1개 --hash 를 보유해야 한다(hashless 핀 금지)."""
    flags = pins_with_hash_flag(_read(REQUIREMENTS_LOCK))
    assert flags, "락에서 ==핀을 하나도 찾지 못함 — 가드 파손 또는 파일 형식 변경"
    hashless = sorted(name for name, has_hash in flags.items() if not has_hash)
    assert not hashless, (
        f"락의 다음 핀이 --hash 없이 존재함: {hashless}\n"
        "hashless 핀은 --require-hashes 무결성 검증을 그 패키지에 대해 무력화한다. "
        "--generate-hashes 로 락을 재생성하세요."
    )


# --- non-vacuous: negative — 합성 입력에서 assertion 이 실제로 trip 하는지 증명 ---


def test_coverage_check_flags_missing_dependency():
    txt = "requests==2.33.1\nnewpkg>=1.0\n"
    lock = "requests==2.33.1 \\\n    --hash=sha256:deadbeef\n"
    direct = direct_names(txt)
    locked = locked_names(lock)
    assert sorted(direct - locked) == ["newpkg"]


def test_hash_check_flags_hashless_pin():
    lock = (
        "requests==2.33.1 \\\n"
        "    --hash=sha256:deadbeef\n"
        "    # via -r scripts/requirements.txt\n"
        "evil==6.6.6\n"  # 해시 없는 핀
        "    # via something\n"
    )
    flags = pins_with_hash_flag(lock)
    hashless = sorted(name for name, has_hash in flags.items() if not has_hash)
    assert hashless == ["evil"]
    assert flags["requests"] is True


def test_hash_check_accepts_inline_and_multiline_hashes():
    inline = "foo==1.0 --hash=sha256:abc\n"
    multiline = "bar==2.0 \\\n    --hash=sha256:def \\\n    --hash=sha256:ghi\n"
    assert pins_with_hash_flag(inline)["foo"] is True
    assert pins_with_hash_flag(multiline)["bar"] is True
