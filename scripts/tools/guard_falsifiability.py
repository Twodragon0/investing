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

Part 2 (2026-08-05): 가드 자체의 **우회 경로**를 감사해 10건을 STATIC_CASES 에
편입했다 — cwd 프리픽스/f-string 형태의 `_state` 루팅, 모듈 레벨 writer 표
드리프트, `getattr`/`import_module` 를 통한 production 루트 취득, 그리고
`--fail-under` 숫자는 그대로 둔 채 게이트를 무력화하는 4가지 커버리지 편집
(측정 범위 축소 x2, `--omit`, `continue-on-error`).

Part 3 (2026-08-05): 런타임 트리-쓰기 탐지기(`tests/_tree_write_guard.py`).
in-process 가로채기 3건과 서브프로세스용 세션 스냅샷 3건. 스냅샷 층은 세션
teardown 에서만 발현해 배선을 끊어도 스위트가 조용하므로, baseline 등록
tripwire · 비교 로직 · 스냅샷 범위를 각각 별도 케이스로 falsify 한다.

Part 4 (2026-08-06): 공급망/시크릿 축 10건 — 액션 SHA 핀닝 3, Gitleaks 게이트 4,
reusable workflow permission lint 배선 3. 감사 시점까지 이 세 축에는 falsifiable
가드가 없었다: 핀닝은 `security-scan.yml` 의 `actions-permissions` 잡이 경고만
내고 exit 하지 않아 구조적으로 vacuous 였고(`has_issues=true` 는 파이프라인
서브셸에 갇혀 전파조차 안 된다), Gitleaks 는 `.gitleaks.toml` 을 어떻게 풀어도
잡이 green 이었으며, permission lint 는 도구 단위 테스트만 있어 CI 배선이 끊겨도
조용했다.

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
from typing import NamedTuple

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
    "_isolate_tvl_history_state": "test_tvl_history_redirected_off_repo_tree",
    "_detect_real_tree_writes": "test_real_tree_writes_detected",
    "_reset_translator_breaker": "test_translator_breaker_closed_at_test_start",
    "sleep_calls": "test_rate_limit_sleeps_are_stubbed",
}

# ``autouse=True`` may sit alongside other kwargs (``scope="session"``), in any
# order. Matching the exact single-kwarg spelling let a session-scoped autouse
# fixture escape the drift check entirely — found 2026-08-05 when
# ``_detect_real_tree_writes`` was added and the registry stayed silent.
_AUTOUSE_RE = re.compile(r"@pytest\.fixture\([^)]*autouse=True[^)]*\)\n(?:@[^\n]*\n)*def (\w+)\(")


class StaticCase(NamedTuple):
    """정적(AST/설정) 가드용 mutation 케이스.

    격리 fixture 가드와 달리 "fixture 를 끈다"가 아니라 **가드가 막으려는 위반을
    실제로 주입**한다. ``old`` 가 None 이면 ``new`` 를 파일 끝에 덧붙인다.
    """

    label: str
    target: str  # 레포 상대 경로
    old: str | None
    new: str
    node_id: str  # 전체 pytest node id


# 액션 핀 가드용 프로브. **실제 액션 SHA 를 앵커로 쓰지 않는다.**
#
# 2026-08-07: 초기 케이스들은 `actions/checkout@de0fac2e…  # v6.0.2` 처럼 실제 핀을
# 앵커로 삼았다. Dependabot 이 checkout 을 6.0.2 -> 7.0.1 로 올린 PR #1105 에서
# 그 앵커가 사라져 하네스가 AMBIGUOUS-ANCHOR 로 죽었다 — 가드가 틀린 게 아니라
# 하네스가 bump 에 결합돼 있었다. 같은 결합이 lighthouse-ci-action·setup-python
# 앵커에도 잠재해 있었다(총 5건).
#
# 대신 존재하지 않는 `probe/*` 참조를 주입한다. 위반 자체가 주입물 안에서 완결되므로
# 어떤 액션이 bump 돼도 앵커가 유효하다.
_PROBE_ANCHOR = "      - name: Verify pins\n"
_PROBE_SHA_A = "d" * 40
_PROBE_SHA_B = "e" * 40


def _probe_steps(*refs: str) -> str:
    """`uses:` 가 주어진 프로브 스텝들 + 원래 앵커. 주입 후에도 YAML 이 유효하다."""
    steps = "".join(f"      - name: Falsifiability probe {i}\n        uses: {ref}\n" for i, ref in enumerate(refs))
    return steps + _PROBE_ANCHOR


# 정적 가드 mutation 케이스.
#
# ``old`` 앵커는 대상 파일에 **정확히 1회**만 나타나야 한다(아래 검증). 이 규칙은
# 실제 오탐에서 나왔다: `fix_defi_tvl_history.py` 감사에서 `__file__` 을 치환했더니
# 19행 `sys.path.insert` 가 바뀌고 정작 24행 `HISTORY_PATH` 는 그대로여서 가드가
# 정당하게 green 이었다 — 가드가 아니라 mutation 이 틀린 것이었다. 첫 일치를 조용히
# 바꾸는 대신 AMBIGUOUS-ANCHOR 로 실패시킨다.
#
# 두 번째 규약(2026-08-05 갭 감사): **주입 코드는 대상 파일에서 실행 가능해야 한다.**
# 초기 form A 케이스는 `dedup.py` 에 `Path("_state/probe.json")` 을 주입했는데 그
# 모듈은 `pathlib` 을 import 하지 않아 autouse fixture 의 dedup import 가 NameError
# 로 죽었다 — 테스트 본문은 실행조차 되지 않았는데 rc!=0 이라 FALSIFIABLE 로 보였다.
# 주입은 대상 모듈에 이미 있는 이름만 쓸 것(또는 import 불필요한 리터럴).
# 커버리지 하한 케이스의 앵커는 **현재 값에서 파생**시킨다. 하드코딩하면 하한을
# ratchet 할 때마다(55 -> 65 -> 70 -> 73 ...) 이 하네스가 AMBIGUOUS-ANCHOR 로
# 죽는다 — 2026-08-25 에 70 -> 73 상향에서 실제로 5개 앵커가 한꺼번에 깨졌다.
# 가드는 "하한이 내려가는 것"을 막으라고 있는 것이지, 올라갈 때 손이 가라고 있는
# 게 아니다.
#
# 세 번째 규약(2026-09-11): **앵커는 유일성이 허락하는 만큼 좁게.** 앵커에 든 줄은
# 전부 결합면이다 — 변형과 무관한 인접 줄을 끌어안으면 그 줄을 고치는 순간
# AMBIGUOUS-ANCHOR 로 죽는다. 가드가 틀린 게 아니라 하네스가 남의 편집에 결합된
# 것이다(`_PROBE_ANCHOR` 주석의 액션 bump 사고와 같은 실패 모드). 그래서:
#   * `old`/`new` 에서 **양쪽이 동일한 줄은 앵커에 넣지 않는다** — 치환에 기여하지
#     않으면서 결합만 늘린다.
#   * 인접 줄이 유일성 때문에 필요하면 남기되, 그 이유를 케이스에 적는다
#     (아래 `pilot_starts[name]` 케이스가 유일한 잔존 사례).
#   * 주석은 앵커에 넣지 않는다. 주석 문구는 코드 의미와 무관하게 바뀐다.
# 유일성은 `test_static_case_anchors_are_unique_in_their_targets` 가 PR 시점에 강제한다.
_COV_FLOOR_RE = re.compile(r"--cov-fail-under=(\d+)")


def _current_coverage_floor() -> int:
    """`pyproject.toml` 의 현재 커버리지 하한. 못 찾으면 조용히 넘어가지 않는다."""
    src = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    found = _COV_FLOOR_RE.findall(src)
    if len(found) != 1:
        raise RuntimeError(
            f"pyproject.toml 에서 --cov-fail-under 를 정확히 1개 찾지 못했다 (found={found}). "
            "커버리지 하한 mutation 케이스의 앵커를 만들 수 없다."
        )
    return int(found[0])


#: 현재 하한과, 그 아래로 끌어내리는 mutation 목표값. 목표값은 어떤 합리적 하한보다도
#: 낮아야 `test_*_coverage_floor_enforced` 가 red 가 된다.
_FLOOR = _current_coverage_floor()
_FLOOR_LOWERED = 50
_WORKFLOW_FLOOR_LOWERED = 40

STATIC_CASES: tuple[StaticCase, ...] = (
    StaticCase(
        "AST 스캔: 스크립트에 cwd-상대 _state 주입 (form A)",
        "scripts/common/dedup.py",
        None,
        '\n_FALSIFIABILITY_PROBE = "_state/probe.json"\n',
        "tests/test_state_path_anchoring.py::test_no_cwd_relative_state_paths_in_scripts",
    ),
    StaticCase(
        "_state 탐지기 무력화 (_is_slash_rooted)",
        "tests/test_state_path_anchoring.py",
        'return bare.startswith(_BARE_ROOT + "/") or bare.startswith(_BARE_ROOT + "\\\\")',
        "return False",
        "tests/test_state_path_anchoring.py::test_guard_detects_known_antipatterns",
    ),
    StaticCase(
        "image_rejection_metrics __file__ 앵커 제거",
        "scripts/common/image_rejection_metrics.py",
        "_REPO_ROOT: Path = Path(__file__).resolve().parent.parent.parent",
        '_REPO_ROOT: Path = Path("/var/tmp/falsifiability-probe")',
        "tests/test_state_path_anchoring.py::test_image_rejection_metrics_anchors_state_to_repo_root",
    ),
    StaticCase(
        "dedup.STATE_DIR 을 bare-relative 로 (AST 가드)",
        "scripts/common/dedup.py",
        'STATE_DIR = os.path.join(REPO_ROOT, "_state")',
        'STATE_DIR = "_state"',
        "tests/test_state_path_anchoring.py::test_module_level_state_paths_anchored_to_repo_root[common/dedup.py]",
    ),
    StaticCase(
        "dedup.STATE_DIR 을 bare-relative 로 (런타임 절대경로 가드)",
        "scripts/common/dedup.py",
        'STATE_DIR = os.path.join(REPO_ROOT, "_state")',
        'STATE_DIR = "_state"',
        "tests/test_state_path_anchoring.py::test_module_state_path_is_absolute_and_under_repo_root[dedup.STATE_DIR]",
    ),
    StaticCase(
        "fix_defi_tvl_history HISTORY_PATH 앵커 제거",
        "scripts/fix_defi_tvl_history.py",
        'HISTORY_PATH = Path(__file__).parent.parent / "_state" / "defi_tvl_history.json"',
        'HISTORY_PATH = Path("_state/defi_tvl_history.json")',
        "tests/test_state_path_anchoring.py::test_fix_defi_tvl_history_state_path_uses_file_anchor",
    ),
    StaticCase(
        "테스트가 프로덕션 REPO_ROOT 를 import",
        "tests/test_encoding_guard.py",
        None,
        "\nfrom common.image_generator import REPO_ROOT  # noqa: E402\n\n_FALSIFIABILITY_PROBE = REPO_ROOT\n",
        "tests/test_hermetic_test_writes_guard.py::test_no_test_imports_production_repo_root",
    ),
    StaticCase(
        "hermetic 탐지기 무력화 (_BANNED_NAMES 비움)",
        "tests/test_hermetic_test_writes_guard.py",
        '_BANNED_NAMES = ("REPO_ROOT", "POSTS_DIR", "SITE_DIR")',
        "_BANNED_NAMES = ()",
        "tests/test_hermetic_test_writes_guard.py::test_detector_flags_all_banned_forms",
    ),
    StaticCase(
        f"커버리지 하한 하향 ({_FLOOR} -> {_FLOOR_LOWERED})",
        "pyproject.toml",
        f"--cov-fail-under={_FLOOR}",
        f"--cov-fail-under={_FLOOR_LOWERED}",
        "tests/test_coverage_floor_guard.py::test_pyproject_coverage_floor_enforced",
    ),
    StaticCase(
        "커버리지 게이트 제거 (addopts)",
        "pyproject.toml",
        f" --cov-fail-under={_FLOOR}",
        "",
        "tests/test_coverage_floor_guard.py::test_pyproject_coverage_floor_enforced",
    ),
    StaticCase(
        f"워크플로우 전역 커버리지 하한 하향 ({_FLOOR} -> {_WORKFLOW_FLOOR_LOWERED})",
        ".github/workflows/code-quality.yml",
        f"--fail-under={_FLOOR}",
        f"--fail-under={_WORKFLOW_FLOOR_LOWERED}",
        "tests/test_coverage_floor_guard.py::test_workflow_global_coverage_floor_enforced",
    ),
    # ---------------------------------------------------------------------
    # Part 2 (2026-08-05): 갭 감사에서 나온 10건. 각 케이스는 "가드가 통과한다"가
    # 아니라 "이 우회를 실제로 주입하면 red 가 된다"를 증명한다.
    # ---------------------------------------------------------------------
    StaticCase(
        "cwd 프리픽스 우회 주입 (form C1: ./_state/)",
        "scripts/common/dedup.py",
        None,
        '\n_FALSIFIABILITY_PROBE = "./_state/probe.json"\n',
        "tests/test_state_path_anchoring.py::test_no_cwd_relative_state_paths_in_scripts",
    ),
    StaticCase(
        'f-string 우회 주입 (form C2: f"_state/{...}")',
        "scripts/common/dedup.py",
        None,
        '\n_FALSIFIABILITY_PROBE = f"_state/{__name__}.json"\n',
        "tests/test_state_path_anchoring.py::test_no_cwd_relative_state_paths_in_scripts",
    ),
    StaticCase(
        "미등록 모듈 레벨 _state writer 추가 (드리프트)",
        "scripts/check_description_quality.py",
        None,
        '\n_FALSIFIABILITY_PROBE = Path(__file__).resolve().parent.parent / "_state" / "probe.json"\n',
        "tests/test_state_path_anchoring.py::test_module_level_writers_table_has_no_drift",
    ),
    StaticCase(
        "테스트가 getattr 로 production REPO_ROOT 취득",
        "tests/test_encoding_guard.py",
        None,
        "\nimport common.image_generator as _fp_ig  # noqa: E402\n\n"
        '_FALSIFIABILITY_PROBE = getattr(_fp_ig, "REPO_ROOT")\n',
        "tests/test_hermetic_test_writes_guard.py::test_no_test_imports_production_repo_root",
    ),
    StaticCase(
        "테스트가 import_module 체인으로 production REPO_ROOT 취득",
        "tests/test_encoding_guard.py",
        None,
        "\nimport importlib as _fp_il  # noqa: E402\n\n"
        '_FALSIFIABILITY_PROBE = _fp_il.import_module("common.image_generator").REPO_ROOT\n',
        "tests/test_hermetic_test_writes_guard.py::test_no_test_imports_production_repo_root",
    ),
    StaticCase(
        "커버리지 측정 범위 축소 (pyproject --cov)",
        "pyproject.toml",
        f'"--cov=scripts --cov-fail-under={_FLOOR}"',
        f'"--cov=scripts/common/summary_sections.py --cov-fail-under={_FLOOR}"',
        "tests/test_coverage_floor_guard.py::test_pyproject_coverage_scope_not_narrowed",
    ),
    StaticCase(
        "커버리지 측정 범위 축소 (워크플로우 --cov)",
        ".github/workflows/code-quality.yml",
        "--cov=scripts/common --cov-report=",
        "--cov=scripts/common/summary_sections.py --cov-report=",
        "tests/test_coverage_floor_guard.py::test_workflow_coverage_scope_not_narrowed",
    ),
    StaticCase(
        "커버리지 게이트 비차단화 (continue-on-error)",
        ".github/workflows/code-quality.yml",
        "      - name: Generate coverage report\n",
        "      - name: Generate coverage report\n        continue-on-error: true\n",
        "tests/test_coverage_floor_guard.py::test_workflow_coverage_gate_steps_are_blocking",
    ),
    StaticCase(
        "커버리지 게이트에서 모듈 제외 (--omit)",
        ".github/workflows/code-quality.yml",
        f"python3 -m coverage report --fail-under={_FLOOR}",
        f'python3 -m coverage report --fail-under={_FLOOR} --omit="*/collect_*.py"',
        "tests/test_coverage_floor_guard.py::test_workflow_coverage_gate_omits_nothing",
    ),
    StaticCase(
        "커버리지 설정에서 모듈 제외 ([tool.coverage.run] omit)",
        "pyproject.toml",
        "[tool.coverage.run]\n",
        '[tool.coverage.run]\nomit = ["*/collect_*.py"]\n',
        "tests/test_coverage_floor_guard.py::test_pyproject_coverage_config_omits_nothing",
    ),
    # ---------------------------------------------------------------------
    # Part 3 (2026-08-05): 런타임 트리-쓰기 탐지기. fixture 를 끄는 케이스는
    # CASES 에 있고, 여기서는 **탐지기 자체를 무력화**하는 변형을 검증한다.
    # ---------------------------------------------------------------------
    StaticCase(
        "트리-쓰기 탐지기 무력화 (모든 경로를 안전으로 분류)",
        "tests/_tree_write_guard.py",
        "    if isinstance(target, int):",
        "    return None\n    if isinstance(target, int):",
        "tests/test_tree_write_guard.py::TestProtectedPathClassification::test_committed_tree_paths_are_protected[_state/dedup_seen.json]",
    ),
    StaticCase(
        "트리-쓰기 탐지기: io.open 패치 누락 (Path.write_text 우회)",
        "tests/_tree_write_guard.py",
        "        for owner in (builtins, io):",
        "        for owner in (builtins,):",
        "tests/test_tree_write_guard.py::TestInterception::test_pathlib_write_text_is_caught",
    ),
    StaticCase(
        "트리-쓰기 탐지기: 쓰기 모드 판정 무력화",
        "tests/_tree_write_guard.py",
        'return any(c in mode for c in "wax+")',
        "return False",
        "tests/test_tree_write_guard.py::TestWriteModeDetection::test_write_modes_detected[w]",
    ),
    # 서브프로세스용 세션 스냅샷 층. 이 층은 세션 teardown 에서만 발현하므로
    # 배선을 끊어도 스위트 어디서도 red 가 나지 않는다 — 그 침묵을 막는 케이스들.
    StaticCase(
        # `global` 만 지우면 `_SESSION_BASELINE = snapshot_tree()` 가 지역 변수
        # 대입이 되어 모듈 전역은 None 으로 남는다 — 함수 본문 전체를 앵커로
        # 잡지 않고도 "baseline 이 등록되지 않는다"를 그대로 재현한다.
        "세션 baseline 미등록 (tripwire 무력화)",
        "tests/_tree_write_guard.py",
        "    global _SESSION_BASELINE\n",
        "",
        "tests/test_suite_isolation_guard.py::test_real_tree_writes_detected",
    ),
    StaticCase(
        "세션 스냅샷 비교 무력화 (변화를 무시)",
        "tests/_tree_write_guard.py",
        "    if not changes:",
        "    if changes or not changes:",
        "tests/test_tree_write_guard.py::TestOutOfProcessNet::test_added_file_is_reported",
    ),
    StaticCase(
        "세션 스냅샷 범위 붕괴 (빈 스냅샷)",
        "tests/_tree_write_guard.py",
        '_SNAPSHOT_DIRS: tuple[str, ...] = ("_posts", "_state", "assets/images/generated")',
        "_SNAPSHOT_DIRS: tuple[str, ...] = ()",
        "tests/test_tree_write_guard.py::TestOutOfProcessNet::test_snapshot_covers_the_content_dirs",
    ),
    # ---------------------------------------------------------------------
    # Part 4 (2026-08-06): 공급망/시크릿 축. 액션 SHA 핀닝 · Gitleaks 게이트 ·
    # reusable workflow permission lint 배선. 이 세 축은 감사 시점까지
    # falsifiable 한 가드가 없었다 — 특히 액션 핀닝은 security-scan.yml 의
    # `actions-permissions` 잡이 "감사"라는 이름으로 경고만 내고 exit 하지
    # 않아(그리고 `has_issues=true` 가 파이프라인 서브셸에 갇혀) 무엇을 풀어도
    # green 이었다. 아래 케이스들이 붙는 대상은 그 잡이 아니라 blocking pytest
    # 잡에서 도는 신규 가드다.
    # ---------------------------------------------------------------------
    StaticCase(
        "외부 액션 핀 해제 (SHA -> 가변 태그)",
        ".github/workflows/action-pin-verify.yml",
        _PROBE_ANCHOR,
        _probe_steps("probe/unpinned-action@v1"),
        "tests/test_workflow_action_pinning_guard.py::test_all_external_actions_are_sha_pinned",
    ),
    StaticCase(
        "핀닝 탐지기 완화 (가변 ref 를 핀으로 인정)",
        "tests/test_workflow_action_pinning_guard.py",
        '_SHA_PINNED_RE = re.compile(r"^[^@\\s]+@[0-9a-f]{40}$")',
        '_SHA_PINNED_RE = re.compile(r"^[^@\\s]+@.+$")',
        "tests/test_workflow_action_pinning_guard.py::test_pinning_detector_rejects_mutable_refs",
    ),
    StaticCase(
        "핀닝 스캐너 붕괴 (uses: 를 하나도 못 찾음)",
        "tests/test_workflow_action_pinning_guard.py",
        '_USES_RE = re.compile(r"^\\s*(?:-\\s+)?uses:\\s*(?P<ref>\\S+)", re.M)',
        '_USES_RE = re.compile(r"^\\s*(?:-\\s+)?uses-absent:\\s*(?P<ref>\\S+)", re.M)',
        "tests/test_workflow_action_pinning_guard.py::test_external_action_reference_count_is_plausible",
    ),
    StaticCase(
        "Gitleaks 기본 룰셋 해제 (useDefault=false)",
        ".gitleaks.toml",
        "useDefault = true",
        "useDefault = false",
        "tests/test_secret_scan_gate_guard.py::test_gitleaks_config_extends_default_rules",
    ),
    StaticCase(
        "Gitleaks allowlist 를 전체 룰로 확대 (targetRules 제거)",
        ".gitleaks.toml",
        'targetRules = ["linkedin-client-secret", "generic-api-key"]',
        "targetRules = []",
        "tests/test_secret_scan_gate_guard.py::test_gitleaks_allowlist_is_scoped_to_known_false_positives",
    ),
    StaticCase(
        "Gitleaks 게이트 비차단화 (|| true)",
        ".github/workflows/security-scan.yml",
        "gitleaks detect --source . --config .gitleaks.toml --no-banner --verbose --redact",
        "gitleaks detect --source . --config .gitleaks.toml --no-banner --verbose --redact || true",
        "tests/test_secret_scan_gate_guard.py::test_gitleaks_gate_is_blocking",
    ),
    StaticCase(
        "Gitleaks 히스토리 절단 (fetch-depth 0 -> 1)",
        ".github/workflows/security-scan.yml",
        "fetch-depth: 0",
        "fetch-depth: 1",
        "tests/test_secret_scan_gate_guard.py::test_gitleaks_job_checks_out_full_history",
    ),
    StaticCase(
        "permission lint 스텝 제거 (도구는 그대로, 배선만 끊김)",
        ".github/workflows/code-quality.yml",
        "run: python3 scripts/tools/check_workflow_permissions.py --workflows-dir .github/workflows",
        "run: 'true'",
        "tests/test_workflow_permission_gate_guard.py::test_permission_lint_runs_in_ci",
    ),
    StaticCase(
        "permission lint 대상 디렉토리 우회 (--workflows-dir)",
        ".github/workflows/code-quality.yml",
        "run: python3 scripts/tools/check_workflow_permissions.py --workflows-dir .github/workflows",
        "run: python3 scripts/tools/check_workflow_permissions.py --workflows-dir tests/fixtures",
        "tests/test_workflow_permission_gate_guard.py::test_permission_lint_scans_the_real_workflow_tree",
    ),
    # Part 5 (2026-08-06): 구분자 정규식 회귀 가드. 같은 결함이 네 번 반복돼
    # 패턴 자체를 금지했다 — 가드가 실제 위반을 잡는지 여기서 증명한다.
    StaticCase(
        "구분자 정규식에 \\s* 재도입 (하이픈 복합어 절단)",
        "scripts/common/summarizer.py",
        'clean = re.sub(r"\\s+[-–—|]\\s*\\S+$", "", title).strip()',
        'clean = re.sub(r"\\s*[-–—|]\\s*\\S+$", "", title).strip()',
        "tests/test_delimiter_regex_guard.py::test_no_open_ended_delimiter_strip_without_leading_space",
    ),
    StaticCase(
        "구분자 탐지기 무력화 (델리미터 클래스 비움)",
        "tests/test_delimiter_regex_guard.py",
        '_DELIM_CLASS = r"\\[[^\\]]*[–—|][^\\]]*\\]"',
        '_DELIM_CLASS = r"(?!x)x"',
        # 파라미터라이즈 id 는 유니코드/백슬래시가 이스케이프돼 취약하다. 카나리는
        # _DELIM_CLASS 를 공유하므로 같은 변형에 red 가 된다.
        "tests/test_delimiter_regex_guard.py::test_safe_spelling_is_actually_present_in_the_repo",
    ),
    StaticCase(
        "permission lint 비차단화 (continue-on-error)",
        ".github/workflows/code-quality.yml",
        "      - name: Check reusable workflow permission coverage\n",
        "      - name: Check reusable workflow permission coverage\n        continue-on-error: true\n",
        "tests/test_workflow_permission_gate_guard.py::test_permission_lint_step_is_blocking",
    ),
    # ---------------------------------------------------------------------
    # Part 6 (2026-08-07): 액션 핀 **버전 라벨** 축. Part 4 의 핀닝 가드는 SHA
    # 형식만 본다 — 40-hex 이기만 하면 `# v4` 라벨이 실제로 v6.0.2 를 가리켜도
    # green 이다. 감사 시점에 그런 거짓 라벨이 3건 있었다(checkout `# v4`→v6.0.2,
    # github-script `# v7`→v9.0.0, git-auto-commit `# v5`→v7.1.0).
    #
    # 업스트림 대조는 네트워크가 필요해 `.github/workflows/action-pin-verify.yml`
    # 이 담당하고, 여기서 검증하는 건 네트워크 없이 판정 가능한 오프라인 불변식
    # 층이다 — 라벨 존재·형태, 그리고 라벨끼리의 모순.
    # ---------------------------------------------------------------------
    StaticCase(
        "액션 핀에서 버전 라벨 제거",
        ".github/workflows/action-pin-verify.yml",
        _PROBE_ANCHOR,
        _probe_steps(f"probe/labelless-action@{_PROBE_SHA_A}"),
        "tests/test_workflow_action_version_label_guard.py::test_every_pin_carries_a_version_label",
    ),
    StaticCase(
        "버전 라벨을 비교 불가한 문자열로 (# latest)",
        ".github/workflows/action-pin-verify.yml",
        _PROBE_ANCHOR,
        _probe_steps(f"probe/badlabel-action@{_PROBE_SHA_A}  # latest"),
        "tests/test_workflow_action_version_label_guard.py::test_version_labels_are_version_shaped",
    ),
    StaticCase(
        "같은 SHA 에 모순 라벨 (# v1 과 # v2 가 한 SHA 에)",
        ".github/workflows/action-pin-verify.yml",
        _PROBE_ANCHOR,
        _probe_steps(
            f"probe/conflict-action@{_PROBE_SHA_A}  # v1",
            f"probe/conflict-action@{_PROBE_SHA_A}  # v2",
        ),
        "tests/test_workflow_action_version_label_guard.py::test_one_sha_never_carries_contradictory_labels",
    ),
    StaticCase(
        "한 버전이 두 SHA 로 분기 (절반만 적용된 bump)",
        ".github/workflows/action-pin-verify.yml",
        _PROBE_ANCHOR,
        _probe_steps(
            f"probe/split-action@{_PROBE_SHA_A}  # v1.0.0",
            f"probe/split-action@{_PROBE_SHA_B}  # v1.0.0",
        ),
        "tests/test_workflow_action_version_label_guard.py::test_one_claimed_version_never_maps_to_two_shas",
    ),
    StaticCase(
        "라벨 비교기 무력화 (모든 라벨을 호환으로 판정)",
        "tests/test_workflow_action_version_label_guard.py",
        "    return longer[: len(shorter)] == shorter",
        "    return True",
        "tests/test_workflow_action_version_label_guard.py::test_label_comparison_is_bidirectional",
    ),
    StaticCase(
        "라벨 가드 스캐너 붕괴 (핀을 하나도 못 찾음)",
        "tests/test_workflow_action_version_label_guard.py",
        "?uses:",
        "?usez:",
        "tests/test_workflow_action_version_label_guard.py::test_pin_count_is_plausible",
    ),
    # ---------------------------------------------------------------------
    # Part 7 (2026-08-07): required status check 집계(aggregator) 층. 룰셋의
    # required check 는 이름으로 매칭되므로, 경로 필터가 걸린 워크플로우의 체크를
    # required 로 걸면 그 경로를 건드리지 않은 PR 이 영구 대기한다. 그래서 필터를
    # 걷고 잡을 `if:` 로 게이팅하며 항상 도는 집계 잡을 둔다 — 그 집계 잡이
    # 조용히 무력화되는 세 경로(needs 누락, always() 제거, 필터 재도입)를 검증한다.
    # ---------------------------------------------------------------------
    StaticCase(
        "집계 잡 needs 축소 (falsifiability 가 게이트 밖으로)",
        ".github/workflows/guard-falsifiability.yml",
        "    needs: [changes, falsifiability]",
        "    needs: [changes]",
        "tests/test_required_check_aggregator_guard.py::test_aggregator_needs_every_other_job[guard-falsifiability.yml]",
    ),
    StaticCase(
        "집계 잡 if: always() 제거 (upstream skip 시 체크 미생성)",
        ".github/workflows/guard-falsifiability.yml",
        "    if: always()\n",
        "",
        "tests/test_required_check_aggregator_guard.py::test_aggregator_runs_unconditionally[guard-falsifiability.yml]",
    ),
    StaticCase(
        "PR 트리거에 paths 필터 재도입 (required check 영구 대기)",
        ".github/workflows/guard-falsifiability.yml",
        "  pull_request:\n",
        "  pull_request:\n    paths:\n      - 'tests/conftest.py'\n",
        "tests/test_required_check_aggregator_guard.py::test_aggregated_workflow_has_no_pull_request_path_filter[guard-falsifiability.yml]",
    ),
    StaticCase(
        "잡 id 스캐너 완화 (중첩 키를 잡으로 오인)",
        "tests/test_required_check_aggregator_guard.py",
        r'_JOB_ID_RE = re.compile(r"^  (?P<job>[A-Za-z_][A-Za-z0-9_-]*):\s*$", re.M)',
        r'_JOB_ID_RE = re.compile(r"^\s*(?P<job>[A-Za-z_][A-Za-z0-9_-]*):\s*$", re.M)',
        "tests/test_required_check_aggregator_guard.py::test_job_id_scanner_rejects_nested_keys",
    ),
    StaticCase(
        # 앵커는 튜플의 **여는 줄뿐**이다. 항목을 하나라도 끼우면 대조군을 넓힐
        # 때마다 앵커가 낡는다 — 2026-08-12 에 2개에서 9개로 넓히면서 실제로 그렇게
        # 깨졌다(당시 첫 항목까지 앵커에 들어 있었다). 뒤에 남는 항목들은 이어지는
        # `_FALSIFIABILITY_UNUSED` 로 흘러가 문법이 유지된다.
        "대조군을 비워 대조군 비 지표를 소멸시킴",
        "scripts/tools/check_pilot_observation.py",
        "CONTROL_COLLECTORS = (\n",
        "CONTROL_COLLECTORS = ()\n_FALSIFIABILITY_UNUSED = (\n",
        "tests/test_check_pilot_observation_control_group_guard.py::test_control_group_is_not_empty",
    ),
    StaticCase(
        "확대된 수집기의 파일럿 플래그가 조용히 되돌아감",
        ".github/workflows/collect-crypto-news.yml",
        "skip-noop-state-commits: 'true'",
        "skip-noop-state-commits: 'false'",
        "tests/test_check_pilot_observation_control_group_guard.py::test_every_mapped_collector_is_either_pilot_or_control",
    ),
    StaticCase(
        # 앵커가 2줄인 유일한 케이스다. `pilot_starts[name],` 한 줄은 이 파일에
        # 2회 나타나 단독으로는 AMBIGUOUS-ANCHOR 가 된다 — 앞의 `runs,` 는 결합이
        # 아니라 유일성을 만드는 최소 컨텍스트다.
        "묶음 집계가 층화 대신 단일 경계로 자름",
        "scripts/tools/check_pilot_observation.py",
        "            runs,\n            pilot_starts[name],",
        "            runs,\n            min(pilot_starts.values()),",
        "tests/test_check_pilot_observation_load_adjusted.py::test_group_mode_splits_each_collector_at_its_own_start",
    ),
    # Part 5 (2026-08-18): `--kind` 축 필터가 판정으로 새는 경로.
    #
    # 이 케이스가 여기 있는 이유는 리뷰에서 뮤테이션으로 갭이 실증됐기 때문이다.
    # 단위 테스트만 있을 때 아래 주입으로 39/39 가 통과했다 — 기존 테스트가 두
    # frozenset 을 테스트 본문에서 손으로 만들어 `classify_commits` 에 먹였을 뿐,
    # `main()` 이 실제로 어느 쪽을 만드는지는 보지 않았다.
    #
    # 새면 조용히 틀린다: 걸러진 레코드를 받은 커밋이 전부 "레코드 없음 = 거절" 이
    # 되어 `--kind collector` 하나로 PR 머지 커밋이 거절로 둔갑한다. 그 숫자는
    # `branch-protection.md` 의 쿼터 서사를 통째로 뒤집는다.
    StaticCase(
        "Vercel 축 필터가 SHA 대조로 샘 (거절 수 조작)",
        "scripts/tools/check_vercel_quota.py",
        'deployed_shas = frozenset(r.sha for r in records if r.env == "production" and r.sha)',
        'deployed_shas = frozenset(r.sha for r in filter_kind(records, args.kind) if r.env == "production" and r.sha)',
        "tests/test_check_vercel_quota.py::test_main_rejection_count_is_independent_of_kind",
    ),
    # ---------------------------------------------------------------------
    # Part 8 (2026-09-11): `supply-chain-lock.yml` 게이트. 계획서 Step 3 의 첫
    # 등록 대상이다 — required-check 토폴로지라는 점에서 Part 7(aggregator)과
    # 같은 결함 계열이라 뮤테이션 3종(paths 재도입 / always() 제거 / needs 축소)을
    # 그대로 옮길 수 있었고, 여기에 이 게이트 고유의 두 축을 더했다:
    # `--require-hashes` 무결성과 스크립트의 fail-closed 기본값.
    # ---------------------------------------------------------------------
    StaticCase(
        "공급망 게이트 PR 트리거에 paths 필터 재도입 (required check 영구 대기)",
        ".github/workflows/supply-chain-lock.yml",
        "  pull_request:\n",
        "  pull_request:\n    paths:\n      - 'scripts/requirements.lock'\n",
        "tests/test_supply_chain_lock_gate_guard.py::TestAlwaysReports::test_pull_request_has_no_paths_filter",
    ),
    StaticCase(
        "공급망 게이트 if: always() 제거 (upstream skip 시 체크 미생성)",
        ".github/workflows/supply-chain-lock.yml",
        "    if: always()\n",
        "",
        "tests/test_supply_chain_lock_gate_guard.py::TestAlwaysReports::test_gate_runs_unconditionally",
    ),
    StaticCase(
        "공급망 게이트 needs 축소 (verify 가 게이트 밖으로)",
        ".github/workflows/supply-chain-lock.yml",
        "    needs: [changes, verify]",
        "    needs: [changes]",
        "tests/test_supply_chain_lock_gate_guard.py::TestAlwaysReports::test_gate_needs_both_upstream_jobs",
    ),
    StaticCase(
        # 2026-06-22~08-26 동안 실제로 non-blocking 이었던 스텝이다. 되돌림이
        # 조용하다는 것이 이 케이스가 있는 이유다.
        "락 무결성에서 --require-hashes 제거 (해시 검증 없이 통과)",
        ".github/workflows/supply-chain-lock.yml",
        "pip install --require-hashes --dry-run -r scripts/requirements.lock",
        "pip install --dry-run -r scripts/requirements.lock",
        "tests/test_supply_chain_lock_gate_guard.py::TestLockIntegrityStaysBlocking::test_step_still_runs_require_hashes",
    ),
    StaticCase(
        # 판정 잡이 죽었는데 게이트가 통과하면, 장애가 "검증 면제"로 위장한다.
        "게이트 fail-open (판정 잡 실패를 무시)",
        ".github/workflows/supply-chain-lock.yml",
        '          if [ "${CHANGES_RESULT}" != "success" ]; then',
        "          if false; then",
        "tests/test_supply_chain_lock_gate_guard.py::TestFailClosed::test_changes_failure_blocks",
    ),
    # ---------------------------------------------------------------------
    # Part 9 (2026-09-13): Tier 2 잔여 3축 — 락 동기화 워크플로우, `_state` 고아
    # 탐지 배선, 자격증명 로깅. 계획서 Step 3 을 여기서 마친다.
    # ---------------------------------------------------------------------
    StaticCase(
        # `pip-compile` 은 sdist 를 빌드하며 임의 코드를 실행한다. write 토큰과
        # 결합하면 권한 상승이다 — 이 워크플로우에서 가장 비싼 실수.
        "락 동기화에 pull_request_target 도입 (권한 상승)",
        ".github/workflows/requirements-lock-sync.yml",
        "  pull_request:\n",
        "  pull_request_target:\n  pull_request:\n",
        "tests/test_requirements_lock_sync_workflow_guard.py::test_does_not_use_pull_request_target",
    ),
    StaticCase(
        "락 생성 파이썬 버전 변경 (무관 패키지까지 drift)",
        ".github/workflows/requirements-lock-sync.yml",
        "python-version: '3.11'",
        "python-version: '3.12'",
        "tests/test_requirements_lock_sync_workflow_guard.py::test_python_is_pinned_to_the_lock_generation_version",
    ),
    StaticCase(
        # in-place 앵커가 깨지면 봇 PR 하나가 전 의존성을 끌어올린다.
        "락 재생성에 --upgrade 추가 (in-place 앵커 파괴)",
        ".github/workflows/requirements-lock-sync.yml",
        "        run: bash scripts/refresh_requirements_lock.sh\n",
        "        run: bash scripts/refresh_requirements_lock.sh --upgrade\n",
        "tests/test_requirements_lock_sync_workflow_guard.py::test_regeneration_stays_in_place",
    ),
    StaticCase(
        # 수집기가 죽었을 때야말로 고아 temp 가 남는다. always() 가 빠지면 정확히
        # 그 경우에만 검사가 돌지 않는다.
        "고아 탐지 if: always() 제거 (수집기 크래시 시 미실행)",
        ".github/actions/python-collect/action.yml",
        "      if: always()\n",
        "",
        "tests/test_state_orphan_ci_detection_guard.py::test_check_runs_even_when_the_collector_crashed",
    ),
    StaticCase(
        "고아 탐지 임계값 상향 (영원히 발화하지 않음)",
        ".github/actions/python-collect/action.yml",
        "check_state_orphans.py --min-age-minutes 0",
        "check_state_orphans.py --min-age-minutes 60",
        "tests/test_state_orphan_ci_detection_guard.py::test_threshold_is_low_enough_to_ever_fire",
    ),
    StaticCase(
        # 주입은 대상 모듈에서 실행 가능해야 한다(2번 규약). `crypto_api.py` 는
        # 이미 `requests` 를 import 하므로 이름이 해석된다.
        "자격증명 파라미터를 redact 없이 requests 로 보냄",
        "scripts/common/crypto_api.py",
        None,
        "\n\ndef _falsifiability_probe(key: str) -> None:\n"
        '    params = {"api_key": key}\n'
        '    requests.get("https://example.invalid/probe", params=params, timeout=1)\n',
        "tests/test_credential_logging_guard.py::test_credential_bearing_requests_are_redacted",
    ),
    # ---------------------------------------------------------------------
    # Part 10 (2026-09-13): `dev_sync_state_safe.sh`. 이 가드는 등록 **전에**
    # 재작성이 필요했다 — 안전 단언 5건이 전부 소스 텍스트를 읽고 있어서,
    # 등록하면 "문자열을 지우는" 뮤테이션에 red 가 되어 falsifiable 해 보이지만
    # "문자열을 남긴 채 행동만 바꾸는" 회귀에는 여전히 눈이 멀어 있었다.
    #
    # 아래 뮤테이션이 정확히 그 맹점이고, 판별력을 실측했다: 재작성 **전** 텍스트
    # 테스트는 11 passed(놓침), 재작성 **후** 행동 테스트는 2 failed(잡음).
    # ---------------------------------------------------------------------
    StaticCase(
        # `_state` 밖 파일을 INSIDE 로 분류 = 되돌리기 대상에 포함. 텍스트 마커는
        # 전부 그대로다 — `_state/*` 리터럴, `${#OUTSIDE[@]}` 블록,
        # `git checkout -- "${INSIDE[@]}"`, MAX_STATE_DIFF_LINES, FORCE,
        # restore_skip_worktree, trap ERR. 소스를 읽는 가드는 이걸 볼 수 없다.
        "동기화 스크립트가 _state 밖 변경까지 되돌림 (사용자 작업물 삭제)",
        "scripts/dev_sync_state_safe.sh",
        '  else\n    OUTSIDE+=("${f}")\n  fi',
        '  else\n    INSIDE+=("${f}")\n  fi',
        "tests/test_dev_sync_state_safe_guard.py::test_aborts_when_non_state_files_are_dirty",
    ),
    # ---------------------------------------------------------------------
    # Part 12 (2026-09-15): `close-stale-ci-failure-issues.yml` 의 github-script
    # 본문. 이 가드도 등록 **전에** 층이 하나 더 필요했다 — 판정 로직 전부가
    # 워크플로우 YAML 안의 JS 인데 가드는 그 소스 텍스트만 읽고 있었다.
    #
    # 양방향으로 판별력을 실측했고, 두 층이 **서로 다른 것**을 잡는다:
    #   continue 제거  -> 텍스트 층 15 passed(눈멂) / 행동 층 1 failed(잡음)
    #   per_page 제거  -> 텍스트 층  1 failed(잡음) / 행동 층 9 passed(눈멂)
    # 그래서 텍스트 단언을 지우지 않고 행동 층을 덧붙였다.
    # ---------------------------------------------------------------------
    StaticCase(
        # 앵커가 2줄인 두 번째 케이스다. `continue;` 는 이 파일에 3회 나타나
        # 단독으로는 AMBIGUOUS-ANCHOR 가 된다 — 앞의 `kept.push` 줄은 결합이
        # 아니라 유일성을 만드는 최소 컨텍스트다(`pilot_starts` 케이스와 동일).
        #
        # 이 변형은 `(issue.comments || 0) > 0` 문자열을 건드리지 않는다. 그래서
        # 소스를 읽는 단언은 전부 통과하고, 사람이 트리아지한 이슈가 요약에
        # "kept" 로 기록되면서 **동시에 닫힌다** — 감사 기록이 거짓말을 한다.
        "스윕이 사람 트리아지 이슈까지 닫음 (코멘트 게이트 fall-through)",
        ".github/workflows/close-stale-ci-failure-issues.yml",
        "                kept.push({ number: issue.number, why: `코멘트 ${issue.comments}건 (사람 트리아지)` });\n                continue;\n",
        "                kept.push({ number: issue.number, why: `코멘트 ${issue.comments}건 (사람 트리아지)` });\n",
        "tests/test_close_stale_ci_failure_issues_guard.py::TestBehaviour::test_commented_issue_is_never_closed",
    ),
    # ---------------------------------------------------------------------
    # Part 11 (2026-09-13): `.claude/hooks/` 의 차단 훅 2종. Tier 3 를 여기서
    # 마친다. 이 둘은 재작성이 필요 없었다 — 2026-09-13 판정에서 이미 임시 git
    # 저장소에 훅을 실제로 돌리고 rc·JSON 결정 페이로드를 단언하고 있었다.
    #
    # 겨냥하는 것은 **fail-open** 이다. 두 훅 다 `exit 2` 로 도구 호출을
    # 차단하는데, 차단을 놓치면 훅은 조용히 `exit 0` 으로 끝나고 아무 흔적도
    # 남지 않는다. 파라미터라이즈 노드는 id 이스케이프가 취약하므로
    # (`_DELIM_CLASS` 케이스 주석 참조) 비-파라미터라이즈 테스트만 겨냥한다.
    # ---------------------------------------------------------------------
    StaticCase(
        "component-counts 훅 fail-open (드리프트인데 통과)",
        ".claude/hooks/component-counts-drift-guard.sh",
        "if [[ $RC -ne 0 ]]; then",
        "if false; then",
        "tests/test_component_counts_drift_hook_guard.py::test_hook_denies_push_on_drift",
    ),
    StaticCase(
        # deny 결정을 내면서 종료 코드만 0 으로 바꾸면, 훅 프로토콜상 차단이
        # 일어나지 않는다 — 이유 문자열은 그대로라 로그만 보면 막힌 것처럼 보인다.
        "component-counts 훅이 deny 하면서 exit 0 (차단 미발생)",
        ".claude/hooks/component-counts-drift-guard.sh",
        "  exit 2",
        "  exit 0",
        "tests/test_component_counts_drift_hook_guard.py::test_hook_denies_push_on_drift",
    ),
    StaticCase(
        "_state 커밋 가드 fail-open (조건 반전)",
        ".claude/hooks/pre-commit-state-guard.sh",
        'if [[ -n "$STAGED" ]]; then',
        'if [[ -z "$STAGED" ]]; then',
        "tests/test_state_guard_command_matching.py::test_blocks_when_state_mixed_with_other_files",
    ),
    StaticCase(
        # 차단은 하되 이유에 첫 파일만 싣는다. rc 만 보는 테스트는 통과하므로,
        # "무엇을 되돌려야 하는가"를 단언하는 테스트가 있어야 잡힌다.
        "_state 커밋 가드 이유 절단 (staged 목록 일부만 보고)",
        ".claude/hooks/pre-commit-state-guard.sh",
        'grep "^_state/"',
        'grep "^_state/" | head -1',
        "tests/test_state_guard_command_matching.py::test_reason_lists_staged_files_and_remedy",
    ),
    # Part 8 (2026-09-15): dependabot auto-merge. 이 워크플로우의 실패는 **머지를
    # 막지 않는다**(required check 가 아니다) — PR 이 조용히 쌓일 뿐이라 red 를
    # 아무도 안 본다. 그래서 정적 가드가 유일한 조기 경보다.
    StaticCase(
        "성공할 수 없는 승인 호출 재도입 (--approve)",
        ".github/workflows/dependabot-auto-merge.yml",
        "          set -euo pipefail\n",
        '          set -euo pipefail\n          gh pr review "$PR_URL" --approve\n',
        "tests/test_dependabot_auto_merge_guard.py::TestNoCallsThatCannotSucceed::test_does_not_approve_the_pull_request",
    ),
    StaticCase(
        "GitHub auto-merge 재도입 (--auto)",
        ".github/workflows/dependabot-auto-merge.yml",
        'gh pr merge "$PR_URL" --squash --delete-branch',
        'gh pr merge "$PR_URL" --auto --squash --delete-branch',
        "tests/test_dependabot_auto_merge_guard.py::TestNoCallsThatCannotSucceed::test_does_not_use_github_auto_merge",
    ),
    StaticCase(
        # 잡 이름과 제외 키가 어긋나면 자기 자신을 기다리다 30분 타임아웃한다.
        "대기 루프 자기 제외 키 드리프트 (SELF_CHECK)",
        ".github/workflows/dependabot-auto-merge.yml",
        "SELF_CHECK: auto-merge",
        "SELF_CHECK: automerge",
        "tests/test_dependabot_auto_merge_guard.py::TestMergeWaitsForChecks::test_self_check_name_matches_the_job_name",
    ),
    StaticCase(
        # `gh pr checks` 는 대기 중이면 exit 8 이다. 종료코드로 판정하면 출력을
        # 통째로 버려 **전부 통과한 PR 도 머지되지 않는다**(2026-09-15 스텁 실측).
        '체크 조회 출력을 종료코드로 폐기 (|| raw="")',
        ".github/workflows/dependabot-auto-merge.yml",
        'raw="$(gh pr checks "$PR_URL" --json name,state 2>/dev/null || true)"',
        'raw="$(gh pr checks "$PR_URL" --json name,state 2>/dev/null)" || raw=""',
        "tests/test_dependabot_auto_merge_guard.py::TestMergeWaitsForChecks::test_check_query_does_not_discard_output_on_nonzero_exit",
    ),
    StaticCase(
        "체크 state 분류 fail-open (화이트리스트 부정 제거)",
        ".github/workflows/dependabot-auto-merge.yml",
        "| not)",
        "| tostring)",
        "tests/test_dependabot_auto_merge_guard.py::TestMergeWaitsForChecks::test_unknown_check_states_are_treated_as_failure",
    ),
)


#: 하네스 등록에서 **의도적으로 제외한** 가드 파일과 그 사유.
#:
#: 2026-09-11 감사: `tests/test_*guard*.py` 41개 중 falsify 되는 것은 11개뿐이었고,
#: 나머지 30개는 "통과한다"만 알려져 있었다 — vacuous 인지 아닌지는 측정된 적이
#: 없었다. 이 저장소는 vacuous 가드를 이미 3회 실측으로 잡았으므로(2026-08-04
#: `_isolate_image_rejection_state`, 2026-08-06 `actions-permissions` 잡과 Gitleaks
#: 게이트) 그 30개는 가설이 아니라 미계측 위험이다.
#:
#: 이 목록의 목적은 면죄가 아니라 **상태를 바꾸는 것**이다 — "아직 등록 안 됨"(암묵)
#: 을 "판단해서 뺐고 사유는 이것"(명시)으로 만든다. 새 가드는 `STATIC_CASES` 에
#: 등록하거나 여기에 사유와 함께 올려야 하고, 둘 다 안 하면
#: `test_every_guard_file_is_registered_or_exempted` 가 red 가 된다.
#:
#: 목록은 `_MAX_EXEMPTIONS` 로 래칫된다. 커지지 않고 줄기만 한다.
UNREGISTERED_BY_DESIGN: dict[str, str] = {
    # --- 영구 면제: 하네스 자신의 메타 테스트 ---
    # 가드가 아니라 하네스의 단위 테스트다. 하네스로 falsify 하면 자기 자신을
    # 재귀 실행하게 된다(test_guard_falsifiability_tool.py 모듈 docstring).
    "tests/test_guard_falsifiability_shard.py": "하네스 메타 테스트 — 하네스가 자기 자신을 재귀 실행하게 된다",
    "tests/test_guard_falsifiability_tool.py": "하네스 메타 테스트 — 하네스가 자기 자신을 재귀 실행하게 된다",
    # --- Tier 1: glob 스캐너 계열. 스캐너 붕괴(결함 A) 방어는 실측 결과 이미 있다 ---
    #
    # 2026-09-11 최초 분류는 이 여섯을 "규모 단언 없음"으로 적었다. **틀렸다.**
    # 분류 정규식이 `len(...) >= N` 형태만 찾았는데 이 저장소는 관용형
    # `assert <collection>, "..."` 을 쓴다 — 철자를 측정하고 존재를 측정했다고
    # 착각한 것이다. 재측정 결과 여섯 모두 트립와이어를 갖고 있다(아래 행 번호).
    #
    # 그래서 이 계열에 규모 단언을 더 넣는 것은 중복 방어다. 남는 노출은 결함 B
    # (단언 무력)뿐이고, 그건 하네스 등록 = Tier 2/3 의 문제다.
    "tests/test_alert_delivery_reachability_guard.py": "Tier 1 — glob 스캐너. _callers() 에 호출자 0건 트립와이어 보유(:100)",
    "tests/test_findings_exit_zero_guard.py": "Tier 1 — glob 아님(CONVERTED 리터럴 파라미터라이즈). script/title_lines/predicates 존재 단언 보유",
    "tests/test_coverage_comment_activity_guard.py": "Tier 1 — glob 스캐너. steps/consumers/producers 트립와이어 + 사용처 집합 등식 보유",
    "tests/test_apt_install_resilience_guard.py": "Tier 1 — glob 스캐너. test_repo_actually_has_apt_install_steps 가 명시 트립와이어",
    "tests/test_workflow_concurrency_scope_guard.py": "Tier 1 — glob 스캐너. test_guard_covers_at_least_one_workflow 가 트립와이어",
    "tests/test_dependabot_pip_scope_guard.py": "Tier 1 — 설정 스캐너. dirs/manifests 트립와이어 보유",
    # --- Tier 2: 전원 등록 완료 (2026-09-11 supply_chain_lock_gate, 2026-09-13 잔여 3축) ---
    # --- Tier 3: 셸 스크립트 가드. 2026-09-13 판정 결과 셋이 갈렸다 ---
    # 계획서는 셋을 "셸 행동 가드"로 묶었으나 실측하니 하나는 텍스트 단언이다.
    #
    # `dev_sync_state_safe` 는 전 테스트가 `_code_only(_SCRIPT.read_text())` 결과에
    # substring/regex 를 건다(`"set -euo pipefail" in code` 등). `subprocess` import 는
    # 로컬 bash 버전 확인용 skip 조건일 뿐 스크립트를 실행하지 않는다. 이건 결함 B 가
    # 아니라 **검증이 프로덕션 경로를 관측하지 않는** 더 나쁜 상태다 — 문자열을 지우는
    # 뮤테이션에는 red 가 되므로 등록하면 falsifiable 해 **보이지만**, 문자열을 남긴 채
    # 행동만 바꾸는 회귀에는 여전히 눈이 멀어 있다. 처방은 등록이 아니라 재작성이다.
    # 나머지 둘은 임시 git 저장소에서 훅을 실제 실행하고 returncode·JSON 결정
    # 페이로드를 단언한다. 진짜 행동 관측이므로 등록 가능하다.
    # --- Tier 4: 자기검증 카나리 보유. 하네스 등록의 한계 효용이 낮다 ---
    # 알려진 위반을 넣어 red 를 확인하는 테스트를 이미 갖고 있어 결함 B 에 대한
    # 로컬 증거가 존재한다.
    "tests/test_injection_guard.py": "Tier 4 — **한 방향만**(2026-09-13). 거짓양성은 막지만 탐지 능력 자체는 미검증. 26개 테스트의 폭이 실질 방어선",
    "tests/test_encoding_guard.py": "Tier 4 — **양방향 카나리** 확인(2026-09-13). detects_corrupted_run + french_accent_not_flagged 가 짝을 이룬다",
    "tests/test_workflow_alerting_coverage_guard.py": "Tier 4 — 카나리 절반 유효(2026-09-13). 첫 단언은 항진명제(glob 결과에 suffix 단언), 둘째만 오염을 잡고 그것도 .github/workflows/AGENTS.md 존재에 의존",
    "tests/test_desc_headline_guard.py": "Tier 4 — **카나리 아님**(2026-09-13). 함수 객체 동일성(is) 단언 — 드리프트는 막지만 탐지 능력은 미검증",
    "tests/test_collector_noop_commit_whitelist_guard.py": "Tier 4 — **양방향 카나리** 확인(2026-09-13). 위반 탐지 + 정상 미탐지 둘 다 단언",
    "tests/test_lock_guard_parity.py": "Tier 4 — **한 방향만**(2026-09-13). 합성 발산 입력 1건, 대조군 없음",
    "tests/test_vercel_config_guard.py": "Tier 4 — **양방향 카나리** 확인(2026-09-13). 위반 탐지 + 정상 미탐지 둘 다 단언",
    "tests/test_pytest_plugin_install_sync_guard.py": "Tier 4 — **카나리 아님**(2026-09-13). 일반 불변식 테스트다. 다만 addopts/설치본 대조라 스캐너 붕괴 경로가 없다",
    "tests/test_rss_source_url_guard.py": "Tier 4 — **양방향 카나리** 확인(2026-09-13). 다만 두 단언 모두 _is_article_url 만 보고 is_safe_url 전제에 의존",
    "tests/test_workflow_scanner_convention_guard.py": "Tier 4 — **메타 규약 검사**(2026-09-13). 카나리가 아니라 다른 가드들의 스캔 방식을 강제한다",
    # --- Tier 4: 내용 품질 축. 규모 단언 보유 또는 범위 협소 ---
    "tests/test_backfill_url_summaries_workflow_guard.py": "Tier 4 — 규모 단언 2건 보유",
    "tests/test_python_version_declaration_guard.py": "Tier 4 — 규모 단언 1건 보유",
    "tests/test_generated_image_guard.py": "Tier 4 — 단일 회귀 재현 테스트. 불변식 스캐너가 아니다",
    "tests/test_state_temp_ignored_guard.py": "Tier 4 — .gitignore 단일 값 단언. 스캐너 붕괴 경로 없음",
}

#: 면제 목록 크기 상한. **커지지 않는다.**
#:
#: 커버리지 하한과 같은 래칫이다. 가드를 `STATIC_CASES` 에 등록하거나 Tier 1
#: 처방(규모 단언)으로 면제 사유를 없앨 때마다 이 값을 함께 내린다. 상한이 없으면
#: 목록이 고무도장이 된다 — 등록보다 면제가 항상 싸기 때문이다.
_MAX_EXEMPTIONS = 22

#: 가드 테스트 모듈로 간주하는 파일명 패턴.
#:
#: **이 글롭은 전수가 아니다.** 이름에 `guard` 가 없는 가드 파일은 걸리지 않는다
#: (`test_state_path_anchoring.py` 가 그 예 — 가드지만 이름 규칙 밖이고, 이미
#: STATIC_CASES 에 등록돼 있다). 여기서 막는 것은 "가드라고 이름 붙여 놓고
#: falsifiability 증명 없이 들어오는" 경로다. 이름 규칙 밖 가드까지 잡으려면
#: 정적 분류가 필요한데, 그건 이 단계의 범위가 아니다.
GUARD_FILE_GLOB = "test_*guard*.py"


def guard_files() -> list[str]:
    """`tests/` 의 가드 테스트 모듈 (저장소-상대 경로)."""
    return sorted(p.relative_to(REPO_ROOT).as_posix() for p in (REPO_ROOT / "tests").glob(GUARD_FILE_GLOB))


def registered_guard_files() -> set[str]:
    """하네스가 실제로 falsify 하는 가드 파일 집합.

    `STATIC_CASES` 의 node id 가 가리키는 파일 + 격리 fixture 가드 파일
    (`CASES` 의 노드는 전부 `GUARD_FILE` 안에서 돈다 — `_run_guard` 참조).
    """
    files = {case.node_id.split("::", 1)[0] for case in STATIC_CASES}
    files.add(GUARD_FILE.relative_to(REPO_ROOT).as_posix())
    return files


def parse_shard(spec: str) -> tuple[int, int]:
    """``"2/5"`` -> ``(2, 5)``. Index is 1-based, as it appears in CI job names."""
    try:
        index_text, total_text = spec.split("/", 1)
        index, total = int(index_text), int(total_text)
    except ValueError as exc:
        raise SystemExit(f"--shard 형식은 'N/M' 이다 (받은 값: {spec!r})") from exc
    if total < 1 or not (1 <= index <= total):
        raise SystemExit(f"--shard 범위 오류: 1 <= N <= M 이어야 한다 (받은 값: {spec!r})")
    return index, total


def select_shard(items: list, shard: tuple[int, int] | None) -> list:
    """Round-robin slice of ``items`` for one shard.

    Round-robin rather than contiguous blocks: cases are grouped by guard file
    in source order, so a contiguous split would put every coverage case in one
    shard and every tree-write case in another, making shard runtimes lopsided.
    Interleaving spreads the slow ones evenly.

    Every item lands in exactly one shard for any (index, total), so a run split
    across shards covers the same set as an unsharded run — asserted in
    ``tests/test_guard_falsifiability.py``.
    """
    if shard is None:
        return list(items)
    index, total = shard
    return [item for position, item in enumerate(items) if position % total == index - 1]


def apply_static_mutation(source: str, case: StaticCase) -> str:
    """정적 케이스의 변형을 적용한다.

    앵커가 0회 또는 2회 이상이면 조용히 첫 일치를 바꾸는 대신 예외를 던진다 —
    엉뚱한 줄을 바꾼 mutation 은 가드를 통과시켜 VACUOUS 오탐을 만든다.
    """
    if case.old is None:
        return source + case.new
    occurrences = source.count(case.old)
    if occurrences != 1:
        raise RuntimeError(
            f"{case.target}: 앵커가 정확히 1회가 아니다 (found={occurrences}). "
            f"엉뚱한 위치를 변형하면 VACUOUS 오탐이 난다. 앵커: {case.old!r}"
        )
    return source.replace(case.old, case.new, 1)


def discover_autouse_fixtures(src: str) -> list[str]:
    """conftest 소스에서 autouse fixture 이름을 전수 수집한다."""
    return _AUTOUSE_RE.findall(src)


def trigger_paths() -> list[str]:
    """저장소-상대 경로 중 **변경 시 이 하네스를 돌려야 하는** 것 전부.

    워크플로우가 `on.pull_request.paths` 에 같은 목록을 손으로 유지하면 반드시
    드리프트한다 — 새 STATIC_CASES 가 새 파일을 겨냥해도 트리거는 모르므로,
    그 가드는 falsifiability 검증 없이 머지된다. 그래서 목록을 케이스 정의에서
    **파생**시키고, 워크플로우는 `--list-targets` 로 이걸 읽는다.

    포함 대상:

    * 하네스가 덮어썼다 복원하는 파일(`_mutated_files`) — 변형 대상이 바뀌면
      앵커가 어긋날 수 있다;
    * 각 케이스가 돌리는 가드 테스트 파일(node id 의 파일 부분) — 가드 본체가
      바뀌면 여전히 falsifiable 한지 다시 봐야 한다;
    * 하네스 자신과 그 워크플로우.
    """
    paths = {str(p.relative_to(REPO_ROOT)) for p in _mutated_files()}
    paths.update(case.node_id.split("::", 1)[0] for case in STATIC_CASES)
    paths.add(str(Path(__file__).resolve().relative_to(REPO_ROOT)))
    paths.add(".github/workflows/guard-falsifiability.yml")
    return sorted(paths)


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
    """지정 fixture 의 autouse=True 를 False 로 바꾼다.

    데코레이터에 다른 kwarg(``scope="session"`` 등)가 함께 있어도 매칭한다 —
    ``autouse=True`` 만 치환하고 나머지 인자는 보존한다.
    """
    pattern = re.compile(r"@pytest\.fixture\(([^)]*)autouse=True([^)]*)\)\n(def " + re.escape(name) + r"\()")
    patched, count = pattern.subn(r"@pytest.fixture(\1autouse=False\2)\n\3", src)
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


def _run_node(node_id: str) -> int:
    """pytest node id 하나만 실행하고 종료 코드를 돌려준다."""
    _purge_pycache()
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    proc = subprocess.run(
        [sys.executable, "-B", "-m", "pytest", node_id, "-q", "--no-cov", "-p", "no:randomly"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=env,
    )
    return proc.returncode


def _run_guard(node: str) -> int:
    """격리 가드 파일의 테스트 1개를 실행한다."""
    return _run_node(f"tests/test_suite_isolation_guard.py::{node}")


def _mutated_files() -> list[Path]:
    """하네스가 덮어썼다 복원하는 파일 전체."""
    return [CONFTEST, GUARD_FILE, *(REPO_ROOT / c.target for c in STATIC_CASES)]


def _assert_safe_to_run() -> None:
    """하네스가 건드릴 파일에 커밋되지 않은 변경이 있으면 중단한다.

    하네스는 대상 파일을 덮어썼다 복원한다. 미커밋 변경이 있는 상태에서 중간에
    죽으면 사용자의 작업이 사라질 수 있다.
    """
    targets = sorted({str(p) for p in _mutated_files()})
    proc = subprocess.run(
        ["git", "status", "--porcelain", "--", *targets],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.stdout.strip():
        raise SystemExit(
            "중단: 하네스가 변형할 파일에 커밋되지 않은 변경이 있다. 덮어썼다 "
            "복원하는 방식이므로 먼저 커밋하거나 stash 할 것.\n" + proc.stdout
        )


def _snapshot_state() -> dict[Path, bytes]:
    """`_state/` 파일 내용을 스냅샷한다.

    `module-level:image_rejection_metrics` 케이스는 import 시점 리다이렉트를
    일부러 깨뜨리므로, 그 실행의 atexit flush 가 진짜
    `_state/image_rejection_metrics.json` 에 기록된다 — 리다이렉트가 막던 바로
    그 오염이다. 하네스가 남긴 이 부작용은 하네스가 되돌려야 한다.
    """
    state_dir = REPO_ROOT / "_state"
    if not state_dir.is_dir():
        return {}
    return {p: p.read_bytes() for p in state_dir.rglob("*") if p.is_file()}


def _restore_state(snapshot: dict[Path, bytes]) -> list[str]:
    """스냅샷과 달라진 `_state/` 파일을 되돌리고 복원한 목록을 돌려준다."""
    restored = []
    for path, content in snapshot.items():
        if not path.exists() or path.read_bytes() != content:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            restored.append(str(path.relative_to(REPO_ROOT)))
    return restored


def _verdict(rc_mutated: int, rc_control: int) -> str:
    if rc_mutated != 0 and rc_control == 0:
        return "FALSIFIABLE"
    if rc_mutated == 0:
        return "VACUOUS"
    return "CONTROL-FAIL"


def _run_static_cases(shard: tuple[int, int] | None = None) -> list[dict]:
    """정적 가드 케이스를 검증한다 (각각 자기 대상 파일만 변형/복원)."""
    results: list[dict] = []
    for case in select_shard(list(STATIC_CASES), shard):
        target = REPO_ROOT / case.target
        original = target.read_text(encoding="utf-8")
        try:
            target.write_text(apply_static_mutation(original, case), encoding="utf-8")
            rc_mutated = _run_node(case.node_id)
            target.write_text(original, encoding="utf-8")
            rc_control = _run_node(case.node_id)
        except RuntimeError as exc:  # 앵커 불일치 — 변형 자체가 무효
            results.append(
                {
                    "fixture": case.label,
                    "guard": case.node_id,
                    "patched_rc": None,
                    "control_rc": None,
                    "verdict": "AMBIGUOUS-ANCHOR",
                    "detail": str(exc),
                }
            )
            continue
        finally:
            target.write_text(original, encoding="utf-8")
            _purge_pycache()

        results.append(
            {
                "fixture": case.label,
                "guard": case.node_id,
                "patched_rc": rc_mutated,
                "control_rc": rc_control,
                "verdict": _verdict(rc_mutated, rc_control),
            }
        )
    return results


def run_all(shard: tuple[int, int] | None = None) -> list[dict]:
    """모든 케이스를 검증하고 결과 리스트를 돌려준다.

    ``shard`` 가 주어지면 해당 샤드에 배정된 케이스만 실행한다. 드리프트 검사
    (CASES 미등록 fixture)는 샤드와 무관하게 항상 전수로 돈다 — 특정 샤드에서만
    보이는 미등록 fixture 는 없고, 누락은 어느 샤드에서든 즉시 드러나야 한다.
    """
    _assert_safe_to_run()
    original = CONFTEST.read_text(encoding="utf-8")
    state_snapshot = _snapshot_state()

    unmapped = [f for f in discover_autouse_fixtures(original) if f not in CASES]
    fixture_cases = select_shard(list(CASES.items()), shard)

    results: list[dict] = []
    try:
        for name, node in fixture_cases:
            patched = (
                _disable_module_level(original) if name == _MODULE_LEVEL_CASE else _disable_fixture(original, name)
            )

            CONFTEST.write_text(patched, encoding="utf-8")
            rc_patched = _run_guard(node)

            CONFTEST.write_text(original, encoding="utf-8")
            rc_control = _run_guard(node)

            results.append(
                {
                    "fixture": name,
                    "guard": node,
                    "patched_rc": rc_patched,
                    "control_rc": rc_control,
                    "verdict": _verdict(rc_patched, rc_control),
                }
            )
    finally:
        CONFTEST.write_text(original, encoding="utf-8")
        restored = _restore_state(state_snapshot)
        if restored:
            print(f"[guard-falsifiability] _state 복원: {', '.join(restored)}", file=sys.stderr)
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

    results.extend(_run_static_cases(shard))
    return results


def _render_table(results: list[dict]) -> str:
    lines = []
    for r in results:
        rc = f"patched_rc={r['patched_rc']} control_rc={r['control_rc']}"
        lines.append(f"{r['verdict']:17} | {rc:32} | {r['fixture']:44} | {r['guard'] or '(가드 없음)'}")
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
    mode.add_argument(
        "--list-targets",
        action="store_true",
        help="변경 시 이 하네스를 돌려야 하는 저장소-상대 경로를 한 줄씩 출력 (워크플로우 트리거 판정용)",
    )
    parser.add_argument("--shard", metavar="N/M", help="N번째/M개 샤드만 실행 (CI 매트릭스용)")
    args = parser.parse_args()

    if args.list_targets:
        print("\n".join(trigger_paths()))
        return 0

    results = run_all(parse_shard(args.shard) if args.shard else None)

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
