#!/usr/bin/env python3
"""격리 가드 falsifiability 검증 하네스.

`tests/test_suite_isolation_guard.py` 의 가드들은 `tests/conftest.py` 의 격리
fixture 가 제거되면 red 가 되어야 의미가 있다. "통과한다" 만으로는 가드가
vacuous(무엇을 꺼도 green) 한지 알 수 없다.

이 도구는 fixture 를 **실제로 하나씩 비활성화**하고 대응 가드만 실행해
`patched_rc != 0` (red) 이고 `control_rc == 0` (green) 인지 확인한다.
2026-08-04 최초 실행에서 실제 vacuous 가드 1건을 찾아냈다 —
`_isolate_image_rejection_state` 가드가 off-tree 만 단언했는데 모듈 레벨
리다이렉트가 이미 이를 보장해 fixture 를 꺼도 green 이었다.

드리프트 방지: `tests/conftest.py` 의 autouse fixture 를 전수 수집해 아래
CASES 에 없는 fixture 가 있으면 실패한다. 새 격리 fixture 를 가드 없이
추가하는 것을 차단한다.

사용법:
    python scripts/tools/guard_falsifiability.py            # 표 출력
    python scripts/tools/guard_falsifiability.py --json     # JSON 출력
    python scripts/tools/guard_falsifiability.py --check    # vacuous/미등록 시 exit 1 (CI)

규약 전문: docs/test-isolation.md
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFTEST = REPO_ROOT / "tests" / "conftest.py"
GUARD_FILE = REPO_ROOT / "tests" / "test_suite_isolation_guard.py"

# 모듈 레벨(import 시점) 리다이렉트는 autouse fixture 가 아니므로 별도 케이스로 둔다.
_MODULE_LEVEL_IMPORT = "    import common.image_rejection_metrics as _irm_a"
_MODULE_LEVEL_CASE = "module-level:image_rejection_metrics"

# fixture 이름 -> 대응 가드 테스트 함수명.
# 새 autouse 격리 fixture 를 추가하면 여기에도 등록해야 한다(미등록 시 --check 실패).
CASES: dict[str, str] = {
    _MODULE_LEVEL_CASE: "test_image_rejection_atexit_baseline_off_repo_tree",
    "_block_real_http": "test_real_http_transport_blocked",
    "_deterministic_dns_resolution": "test_ssrf_dns_resolution_pinned_off_live_network",
    "_isolate_generated_images": "test_generated_images_redirected_off_repo_tree",
    "_isolate_dedup_state": "test_dedup_state_redirected_off_repo_tree",
    "_isolate_signal_history_state": "test_signal_history_redirected_off_repo_tree",
    "_isolate_translation_cache": "test_translation_cache_redirected_off_repo_tree",
    "_isolate_image_rejection_state": "test_image_rejection_state_redirected_off_repo_tree",
}

_AUTOUSE_RE = re.compile(r"@pytest\.fixture\(autouse=True\)\n(?:@[^\n]*\n)*def (\w+)\(")


def discover_autouse_fixtures(src: str) -> list[str]:
    """conftest 소스에서 autouse fixture 이름을 전수 수집한다."""
    return _AUTOUSE_RE.findall(src)


def _purge_pycache() -> None:
    """__pycache__ 전량 삭제.

    conftest.py 를 짧은 간격으로 반복 덮어쓰면 pyc 검증(mtime+size)이 변경을
    놓쳐 스테일 바이트코드가 재사용된다. 초기 하네스가 이 때문에 실행마다
    다른 결과를 냈다.
    """
    for path in (REPO_ROOT / "tests", REPO_ROOT / "scripts"):
        for cache_dir in path.rglob("__pycache__"):
            shutil.rmtree(cache_dir, ignore_errors=True)


def _disable_fixture(src: str, name: str) -> str:
    """지정 fixture 의 autouse=True 를 False 로 바꾼다."""
    pattern = re.compile(r"@pytest\.fixture\(autouse=True\)\n(def " + re.escape(name) + r"\()")
    patched, count = pattern.subn(r"@pytest.fixture(autouse=False)\n\1", src)
    if count != 1:
        raise RuntimeError(f"fixture {name!r} 의 autouse 데코레이터를 정확히 1개 찾지 못했다 (found={count})")
    return patched


def _disable_module_level(src: str) -> str:
    """import 시점 리다이렉트가 ImportError 를 맞도록 모듈명을 비존재로 바꾼다."""
    if _MODULE_LEVEL_IMPORT not in src:
        raise RuntimeError("conftest 에서 모듈 레벨 image_rejection_metrics import 를 찾지 못했다")
    return src.replace(
        _MODULE_LEVEL_IMPORT,
        "    import common.image_rejection_metrics_ABSENT as _irm_a",
        1,
    )


def _run_guard(node: str) -> int:
    """가드 테스트 1개만 실행하고 종료 코드를 돌려준다."""
    _purge_pycache()
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    proc = subprocess.run(
        [
            sys.executable,
            "-B",
            "-m",
            "pytest",
            f"tests/test_suite_isolation_guard.py::{node}",
            "-q",
            "--no-cov",
            "-p",
            "no:randomly",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=env,
    )
    return proc.returncode


def _assert_safe_to_run() -> None:
    """conftest/가드 파일에 커밋되지 않은 변경이 있으면 중단한다.

    하네스는 conftest.py 를 덮어썼다 복원한다. 미커밋 변경이 있는 상태에서
    중간에 죽으면 사용자의 작업이 사라질 수 있다.
    """
    proc = subprocess.run(
        ["git", "status", "--porcelain", "--", str(CONFTEST), str(GUARD_FILE)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.stdout.strip():
        raise SystemExit(
            "중단: tests/conftest.py 또는 tests/test_suite_isolation_guard.py 에 "
            "커밋되지 않은 변경이 있다. 하네스는 이 파일들을 덮어썼다 복원하므로 "
            "먼저 커밋하거나 stash 할 것.\n" + proc.stdout
        )


def run_all() -> list[dict]:
    """모든 케이스를 검증하고 결과 리스트를 돌려준다."""
    _assert_safe_to_run()
    original = CONFTEST.read_text(encoding="utf-8")

    unmapped = [f for f in discover_autouse_fixtures(original) if f not in CASES]

    results: list[dict] = []
    try:
        for name, node in CASES.items():
            patched = (
                _disable_module_level(original) if name == _MODULE_LEVEL_CASE else _disable_fixture(original, name)
            )

            CONFTEST.write_text(patched, encoding="utf-8")
            rc_patched = _run_guard(node)

            CONFTEST.write_text(original, encoding="utf-8")
            rc_control = _run_guard(node)

            if rc_patched != 0 and rc_control == 0:
                verdict = "FALSIFIABLE"
            elif rc_patched == 0:
                verdict = "VACUOUS"
            else:
                verdict = "CONTROL-FAIL"

            results.append(
                {
                    "fixture": name,
                    "guard": node,
                    "patched_rc": rc_patched,
                    "control_rc": rc_control,
                    "verdict": verdict,
                }
            )
    finally:
        CONFTEST.write_text(original, encoding="utf-8")
        _purge_pycache()

    for fixture in unmapped:
        results.append(
            {
                "fixture": fixture,
                "guard": None,
                "patched_rc": None,
                "control_rc": None,
                "verdict": "UNMAPPED",
            }
        )
    return results


def _render_table(results: list[dict]) -> str:
    lines = []
    for r in results:
        rc = f"patched_rc={r['patched_rc']} control_rc={r['control_rc']}"
        lines.append(f"{r['verdict']:12} | {rc:32} | {r['fixture']:34} | {r['guard'] or '(가드 없음)'}")
    ok = sum(1 for r in results if r["verdict"] == "FALSIFIABLE")
    lines.append("")
    lines.append(f"{ok}/{len(results)} guards falsifiable")
    for r in results:
        if r["verdict"] != "FALSIFIABLE":
            lines.append(f"  {r['verdict']}: {r['fixture']} -> {r['guard'] or 'CASES 미등록'}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="격리 가드 falsifiability 검증")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--json", action="store_true", help="JSON 출력")
    mode.add_argument("--check", action="store_true", help="vacuous/미등록 시 exit 1 (CI)")
    args = parser.parse_args()

    results = run_all()

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print(_render_table(results))

    failed = [r for r in results if r["verdict"] != "FALSIFIABLE"]
    if args.check and failed:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
