# CI 회귀 가드 카탈로그

이 저장소의 **CI 인바리언트 가드** 인벤토리. 각 가드는 "조용히 약화되면
보호가 사라지는" 특정 불변식을, 일반 단위 테스트 스위트(`tests/`, Code
Quality 워크플로우의 pytest 잡) 안에서 강제한다. 로컬에서도 CI보다 먼저
실패하므로 회귀가 PR 단계에서 잡힌다.

매핑: OWASP **CICD-SEC-1**(Insufficient Flow Control) / **CICD-SEC-7**(Insecure
System Configuration), NIST SSDF(SP 800-218) **PO.3 / PW.4**.

> 작성 2026-06-22. 새 가드 추가/제거 시 이 표를 갱신할 것.

## 가드 일람

| 가드 테스트 | 케이스 | 불변식 (방향) | 막는 사고 |
|---|---|---|---|
| `tests/test_state_path_anchoring.py` | 16 | 모든 `_state` 작성자가 `__file__` 앵커(절대·repo-root 하위)를 쓴다 — bare-relative 금지 | 잘못된 cwd 에서 스크립트 실행 시 stray `scripts/_state/` 생성, dedup 상태 분기 |
| `tests/test_pip_audit_ignore_sync.py` | 4 | `code-quality.yml` ↔ `dependency-check.yml` 의 pip-audit `--ignore-vuln` ID 집합 동일(equality), 파일 내 모든 호출이 동일 집합 보유 | 한쪽만 ignore 갱신 → 다른 쪽 보안 게이트 매주 silent red (2026-06 사고) |
| `tests/test_ruff_version_pin_sync.py` | 3 | ruff 버전 핀 3곳(`.pre-commit-config.yaml` rev, `requirements-dev.txt`, `code-quality.yml`) 동기화(equality) | 핀 불일치 → format 규칙 차이로 코드 변경 없이 main 이 red |
| `tests/test_workflow_step_if_safety.py` | 48 | step-level `if:` 가 `secrets.*` 컨텍스트를 직접 참조하지 않음(presence) — 전 워크플로우 파라미터화 | actionlint 가 거부하는 expression → 워크플로우 startup_failure |
| `tests/test_workflow_permission_lint.py` | 8 | `check_workflow_permissions.py` 도구가 워크플로우 `permissions:` 최소권한 규칙을 검사 | 과대 권한(`contents: write` 남발) GITHUB_TOKEN 노출면 확대 |
| `tests/test_generated_image_guard.py` | 2 | 레이아웃이 렌더하는 생성 이미지가 404 나지 않음(존재 보장) | 30일 이미지 정리가 참조 살아있는 og/hero 이미지를 삭제 → 깨진 이미지 |
| `tests/test_encoding_guard.py` | 16 | `encoding_guard` 모듈의 UTF-8/CP949 라벨 교정 동작 불변 | 한국어 텍스트 인코딩 깨짐(mojibake) |
| `tests/test_requirements_lock_coverage.py` | 6 | `requirements.txt` 직접 의존성 전부가 `requirements.lock` 에 ==핀(부분집합) + 락의 모든 핀이 최소 1개 `--hash` 보유(presence) | 락 staleness(검증 안 되는 새 의존성) / hashless 핀이 `--require-hashes` 무결성 검증을 무력화하는 공급망 변조 창 |

총 **103 케이스**.

## 설계 규약 (신규 가드 작성 시)

`.claude/skills/ci-config-guard` 플레이북을 따른다:

1. **위치**: `tests/` — 기존 pytest 잡이 CI 에서 실행하므로 그대로 실행됨.
2. **최소 의존**: stdlib + 텍스트/regex 스캔 우선. 워크플로우 YAML 검사용으로
   PyYAML 같은 파서를 새로 들이지 말 것. 측정 대상 소스를 import 하지 말 것
   (coverage 게이트를 움직이지 않도록).
3. **방향 명시**: 하한선은 `>=`(상향은 green), 핀은 `==`/집합 동일(어떤 변경도
   trip), 트리거/플래그는 presence. docstring 에 방향을 적는다.
4. **non-vacuous 필수**: 실제 파일에서 통과(positive) + 임시 사본을 변형하면
   assertion 이 FAIL(negative) 둘 다 증명한 뒤 머지. 실제 워크플로우 파일은
   변형하지 말고 모듈의 경로 상수를 임시 파일로 monkeypatch.
5. **카나리**: 대상 파일 존재 + 비어있지 않음을 확인하는 테스트를 둬서, 파일
   이동/리네임 시 vacuous 통과 대신 명확히 실패하게 한다.
6. **메시지**: 다음 엔지니어에게 고치는 법(또는 의도적 변경이면 가드 갱신법)을
   알려주는 assertion 메시지를 쓴다.

## 가드를 "추가하지 않는" 기준

가드 난립(sprawl) 방지: **특정 불변식의 조용한 약화가 실제로 강제를 무력화**
하고, 구체적 과거/유력 사고를 댈 수 있을 때만 추가한다. 사고가 없으면 보통
추가하지 않는다.

## 관련 운영 사실

- **dev-tool install 갭** (ruff/yamllint/basedpyright/pytest/pre-commit/actionlint/
  bandit/gitleaks 등 `scripts/requirements.txt` 에 없는 도구를 install 없이 호출)
  은 2026-06-22 전수 재감사에서 **잔여 0건** 확인. 신규 워크플로우에서 이들 도구
  호출 시 동일 잡 내 install 선행을 확인할 것. (사고 이력: `generate-weekly-report.yml`
  이 ruff 미설치로 매주 red → 중복 lint 스텝 제거로 해소.)
- CI red 진단은 `gh run list --limit 60` 으로 워크플로우별 실패 tally 를 먼저 떠서
  만성/일회성을 구분하고, 만성 의심 시 `gh workflow run "<name>"` 로 수동 트리거해
  스케줄 대기 없이 즉시 검증한다.
- **공급망 락 차단 승격 예약**: `.github/workflows/supply-chain-lock.yml` 의
  `--require-hashes` 무결성 스텝은 현재 non-blocking(경고). 도입 2026-06-22, 안정화
  2주 → **승격 예정일 2026-07-06(이후)**. 게이트: 예정일 경과 + 무결성 스텝 연속 green
  + `::warning title=lock integrity::` 0건. 승격은 그 스텝의 `|| echo ...` fallback
  제거로 수행. staleness/hashless 회귀는 위 `test_requirements_lock_coverage.py` 가
  워크플로우 트리거와 무관하게 매 PR 차단하므로, 승격은 무결성(다운로드 검증) 차단만
  추가하는 것이다.
