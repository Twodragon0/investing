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
        "커버리지 하한 하향 (70 -> 50)",
        "pyproject.toml",
        "--cov-fail-under=70",
        "--cov-fail-under=50",
        "tests/test_coverage_floor_guard.py::test_pyproject_coverage_floor_enforced",
    ),
    StaticCase(
        "커버리지 게이트 제거 (addopts)",
        "pyproject.toml",
        " --cov-fail-under=70",
        "",
        "tests/test_coverage_floor_guard.py::test_pyproject_coverage_floor_enforced",
    ),
    StaticCase(
        "워크플로우 전역 커버리지 하한 하향 (70 -> 40)",
        ".github/workflows/code-quality.yml",
        "--fail-under=70",
        "--fail-under=40",
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
        '"--cov=scripts --cov-fail-under=70"',
        '"--cov=scripts/common/summary_sections.py --cov-fail-under=70"',
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
        "      - name: Generate coverage report\n        run: |",
        "      - name: Generate coverage report\n        continue-on-error: true\n        run: |",
        "tests/test_coverage_floor_guard.py::test_workflow_coverage_gate_steps_are_blocking",
    ),
    StaticCase(
        "커버리지 게이트에서 모듈 제외 (--omit)",
        ".github/workflows/code-quality.yml",
        "python3 -m coverage report --fail-under=70",
        'python3 -m coverage report --fail-under=70 --omit="*/collect_*.py"',
        "tests/test_coverage_floor_guard.py::test_workflow_coverage_gate_omits_nothing",
    ),
    StaticCase(
        "커버리지 설정에서 모듈 제외 ([tool.coverage.run] omit)",
        "pyproject.toml",
        "[tool.coverage.run]\nrelative_files = true",
        '[tool.coverage.run]\nrelative_files = true\nomit = ["*/collect_*.py"]',
        "tests/test_coverage_floor_guard.py::test_pyproject_coverage_config_omits_nothing",
    ),
    # ---------------------------------------------------------------------
    # Part 3 (2026-08-05): 런타임 트리-쓰기 탐지기. fixture 를 끄는 케이스는
    # CASES 에 있고, 여기서는 **탐지기 자체를 무력화**하는 변형을 검증한다.
    # ---------------------------------------------------------------------
    StaticCase(
        "트리-쓰기 탐지기 무력화 (모든 경로를 안전으로 분류)",
        "tests/_tree_write_guard.py",
        "    if isinstance(target, int):  # file descriptor, not a path\n        return None",
        "    return None\n    if isinstance(target, int):  # file descriptor, not a path\n        return None",
        "tests/test_tree_write_guard.py::TestProtectedPathClassification::test_committed_tree_paths_are_protected[_state/dedup_seen.json]",
    ),
    StaticCase(
        "트리-쓰기 탐지기: io.open 패치 누락 (Path.write_text 우회)",
        "tests/_tree_write_guard.py",
        '        for owner in (builtins, io):\n            self._patch(owner, "open", self._wrap_open)',
        '        for owner in (builtins,):\n            self._patch(owner, "open", self._wrap_open)',
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
        "세션 baseline 미등록 (tripwire 무력화)",
        "tests/_tree_write_guard.py",
        "    global _SESSION_BASELINE\n    _SESSION_BASELINE = snapshot_tree()\n    return _SESSION_BASELINE",
        "    return snapshot_tree()",
        "tests/test_suite_isolation_guard.py::test_real_tree_writes_detected",
    ),
    StaticCase(
        "세션 스냅샷 비교 무력화 (변화를 무시)",
        "tests/_tree_write_guard.py",
        "    changes = diff_tree(baseline, snapshot_tree())\n    if not changes:\n        return",
        "    changes = diff_tree(baseline, snapshot_tree())\n    if changes or not changes:\n        return",
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
        "    name: Falsifiability gate\n    if: always()\n",
        "    name: Falsifiability gate\n",
        "tests/test_required_check_aggregator_guard.py::test_aggregator_runs_unconditionally[guard-falsifiability.yml]",
    ),
    StaticCase(
        "PR 트리거에 paths 필터 재도입 (required check 영구 대기)",
        ".github/workflows/guard-falsifiability.yml",
        "  pull_request:\n    branches: [main]\n",
        "  pull_request:\n    branches: [main]\n    paths:\n      - 'tests/conftest.py'\n",
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
        # 앵커는 튜플의 **여는 줄**이다. 항목을 나열하면 대조군을 넓힐 때마다 앵커가
        # 낡는다 — 2026-08-12 에 2개에서 9개로 넓히면서 실제로 그렇게 깨졌다.
        # 뒤에 남는 항목들은 `_FALSIFIABILITY_UNUSED` 로 흘러가 문법이 유지된다.
        "대조군을 비워 대조군 비 지표를 소멸시킴",
        "scripts/tools/check_pilot_observation.py",
        'CONTROL_COLLECTORS = (\n    "political",',
        'CONTROL_COLLECTORS = ()\n_FALSIFIABILITY_UNUSED = (\n    "political",',
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
        "묶음 집계가 층화 대신 단일 경계로 자름",
        "scripts/tools/check_pilot_observation.py",
        "            runs,\n            pilot_starts[name],",
        "            runs,\n            min(pilot_starts.values()),",
        "tests/test_check_pilot_observation_load_adjusted.py::test_group_mode_splits_each_collector_at_its_own_start",
    ),
)


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
