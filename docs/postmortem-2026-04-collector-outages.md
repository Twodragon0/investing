# Postmortem — 2026-04 수집기 파이프라인 2단 장애

- **작성일**: 2026-04-24
- **상태**: 해결 진행 중 (1차 원인 해결 완료, 2차 원인 PR 리뷰 대기)
- **영향 수집기**: crypto-news, stock-news, regulatory, social-media, political-trades, market-indicators, geopolitical, worldmonitor, coinmarketcap, defi-llama, defi-yields, fmp-calendar, blockchain (총 13개)

## TL;DR

2026-04-18 ~ 04-24 사이 수집기 전면 장애가 **두 개의 독립된 근본 원인**에서 순차 발생:

1. **(#773)** `scripts/common/risk_classifier.py`의 `from scripts.common.*` 절대 import가 `scripts/`를 패키지 루트로 잡지 않는 실행 환경에서 `ModuleNotFoundError` 유발. **6일간 무음 방치**.
2. **(#777/#783 → #786 수정)** `alert-consecutive-failures.yml` reusable workflow가 `permissions: contents: read, actions: read`를 선언했지만, 호출 측 `collect-*.yml`은 `contents: write`만 선언 → GitHub Actions 검증 단계에서 `startup_failure` (jobs=0, 2초 내 종료). PR #777 머지 직후부터 13개 수집기 전면 마비.

두 원인 모두 **운영 관측 공백**이 증상을 키웠다. 알림 인프라가 없었던 1차 장애는 품질 리포트 수동 점검으로만 발견, 2차 장애는 1차 대응 중 유입되어 도미노 효과.

## Timeline (모든 시각 UTC 기준)

| 시각 | 이벤트 |
|---|---|
| 2026-04-18 ~ 04-23 | **1차 장애**: `risk_classifier.py` 최상위 import가 collector runtime에서 `ModuleNotFoundError`. 13개 수집기 장기 무음 실패. |
| 2026-04-23 08:32 | PR #754 머지 — `image_rejection_metrics.json` 집계 인프라 도입. |
| 2026-04-23 08:50:33 | **PR #773 머지** — `risk_classifier.py` top-level import를 relative로 수정. **1차 장애 해결**. |
| 2026-04-23 08:51, 10:25 UTC | crypto-news 수동/크론 ✅ success |
| 2026-04-23 08:51, 11:33 UTC | stock-news 수동/크론 ✅ success |
| 2026-04-23 13:30 | PR #775 머지 — `regulatory` inline 실패 알림 추가. |
| 2026-04-23 14:08 | **PR #777 머지** — 재사용 워크플로우 `alert-consecutive-failures.yml` 도입, 4개 수집기에 `uses:` 호출 추가. **2차 장애 유입**. |
| 2026-04-23 14:13+ UTC | stock/regulatory/social/political 수집기 `startup_failure` 시작. |
| 2026-04-23 14:30 | PR #783 머지 — 6개 보조 수집기에 동일 reusable 호출 확산. 13/13 커버리지 달성과 동시에 **13/13 전면 장애**. |
| 2026-04-23 23:08 / 23:11 UTC | 마지막 스케줄 실행도 startup_failure. 알림조차 울릴 수 없는 상태(호출 job이 시작하지 못함). |
| 2026-04-24 00:00~01:30 | **진단 세션 (본 문서)**: ULTRAWORK로 crypto/stock 수동 트리거 재시도 → 동일 실패 확인 → run attempt 메타데이터(`referenced_workflows`, 2초 실행, 0 jobs)로 startup_failure 확정 → permission mismatch 가설 도출. |
| 2026-04-24 01:40 | **PR #786 제출** — 13개 `collect-*.yml`에 `actions: read` 권한 추가. |
| 2026-04-24 01:50 | **PR #788 제출** — `scripts/tools/check_workflow_permissions.py` + pytest 8개 + code-quality.yml 통합으로 재발 방지. |

## 근본 원인 #1 — 절대 import 패키지 경로

### 증상

collect_*.py 실행 시:
```
ModuleNotFoundError: No module named 'scripts'
```
`risk_classifier.py:326`의 lazy import가 호출 경로에 진입하면 즉시 폭발. top-level import가 먼저 터져 collector가 시작도 못 하는 경우도 있음.

### 원인

repository는 collector를 `python scripts/collect_X.py` 형태로 실행한다. `conftest.py`와 `sys.path` 초기화는 `scripts/`를 루트로 올려 `from common.X import Y` 패턴을 사용하게 한다. 누군가 `risk_classifier.py`에 `from scripts.common.markdown_utils import ...` 형태 절대 import를 실수로 삽입 → `scripts` 자체가 모듈이 아니라서 실패.

PR #773은 **top-level import만 수정**했고, line 326의 lazy import는 놓쳤다. 본 세션에서 발견해 추가 커밋으로 포함.

### 해결 (PR #773 + 본 세션 lazy import 추가 수정)

- top-level: `from .markdown_utils import _classify_source`
- lazy (`_resolve_source_weight` 내부): 동일 relative import

### 회귀 방지

1. `tests/test_import_compatibility.py` (32 tests): 모든 `common/*` 모듈의 `from common.X import Y` 방식 import + collector subprocess 실행 + AST 스캔.
2. `.pre-commit-config.yaml`의 `relative-imports-in-scripts-common` 훅 (#777) + `scripts/tools/check_relative_imports.py` AST 파서.
3. CI `code-quality.yml`의 pre-commit 실행 (#783).

## 근본 원인 #2 — Reusable Workflow Permission 함정

### 증상

collector 워크플로우 실행 시:
- conclusion: `startup_failure`
- duration: ~2초
- jobs: 빈 배열 (`/actions/runs/<id>/attempts/1/jobs` → `[]`)
- 로그: `log not found` (실행 단계 진입 전 실패)
- UI/API annotations: 모두 404 또는 빈 응답

### 원인

```yaml
# .github/workflows/alert-consecutive-failures.yml (callee, reusable)
permissions:
  contents: read
  actions: read      # ← gh run list 용도
```

```yaml
# .github/workflows/collect-crypto-news.yml (caller)
permissions:
  contents: write    # ← actions 스코프 전혀 선언 안 함
...
jobs:
  alert-consecutive-failures:
    needs: collect
    if: failure()
    uses: ./.github/workflows/alert-consecutive-failures.yml
    secrets: inherit
```

**GitHub Actions 검증 규칙**: reusable workflow가 선언한 permission 스코프가 caller의 permission 블록에 부재하면 워크플로우 전체를 `startup_failure`로 거부한다. caller가 `contents: write`만 선언한 순간, `actions`는 암묵적으로 "없음" 상태이며 이는 callee의 `actions: read` 요구와 불일치 → 전체 caller workflow가 시작조차 못 함.

중요: 이 실패는 **`collect` job의 성공/실패와 무관**하게 발생한다. `collect` 자체는 시작도 못 한다. `alert-consecutive-failures` job이 `if: failure()` 조건이어서 실제로는 실행될 일이 거의 없는데도, 워크플로우 정적 검증 단계에서 reference 자체가 유효성 검사되기 때문.

### 해결 (PR #786)

13개 caller workflow 모두에 2줄 추가:

```yaml
permissions:
  contents: write
  actions: read       # ← 추가
```

### 회귀 방지 (PR #788)

`scripts/tools/check_workflow_permissions.py`:
- `.github/workflows/*.yml`을 PyYAML로 파싱
- `on.workflow_call`을 가진 reusable workflow의 permissions 수집
- `jobs.*.uses: ./.github/workflows/<name>.yml` 호출하는 caller의 permissions와 대조
- 불충족 시 ERROR 출력 + exit 1

pytest 8 케이스 + `code-quality.yml`에 신규 job 통합 → PR 시점 차단.

## 왜 오래 걸렸는가

### 1차 장애

- 알림 인프라 부재: GitHub Actions 실패 알림이 특정 채널로 라우팅되지 않아 Slack 오퍼레이터가 **6일간 인지 불가**.
- 품질 리포트(`description_quality`)가 "입력 포스트 수 = 0" 상태를 "정상"으로 해석하는 엣지케이스 → CI 리포트도 녹색.
- 첫 수정 후 lazy import를 놓쳐 "완료" 상태가 부정확하게 보고됨 (본 세션에서 발견).

### 2차 장애

- `startup_failure`의 jobs 배열이 비어 있어 **`if: failure()` 알림 트리거가 영영 작동 안 함**. 방금 도입한 알림 장치가 자기 자신의 장애는 못 잡는 구조적 모순.
- PR #777 머지 후 즉시 스케줄 실행이 모두 실패했지만, 당시에는 알림도 로그도 없어 관리자가 PR 리뷰/머지 워크플로우(`Security Scan`, `CodeQL`, `Code Quality`)만 보고 "정상"으로 착각 가능.
- 2초 안에 끝나는 실행은 CI 대시보드에서 "빠르게 성공한 것처럼" 보임.

## Action Items

| 항목 | 담당 | 기한 | 상태 |
|---|---|---|---|
| PR #786 머지 (13 workflow actions:read) | @Twodragon0 | 2026-04-24 | 리뷰 대기 |
| PR #788 머지 (permission lint CI) | @Twodragon0 | 2026-04-24 | 리뷰 대기 |
| `alert-consecutive-failures` 자체가 startup_failure일 때의 fallback 알림 채널 추가 | — | 2026-04-30 | 미착수 |
| GitHub Actions "zero-job run" 감지 크론 추가 (5분 주기, 최근 10개 run에서 `jobs=0`인 것 Slack 알림) | — | 2026-04-30 | 미착수 |
| `description_quality` CI에서 "입력 0 = 실패"로 분류하는 엣지케이스 패치 | — | 2026-05-07 | 미착수 |
| 수집기 성공 신호를 Slack에 1일 1회 "heartbeat" 형태로 발행 (silent failure 조기 탐지) | — | 2026-05-07 | 미착수 |
| 모든 reusable workflow를 caller와 함께 `actionlint` 검증 대상에 포함 | — | 2026-05-14 | 미착수 |

## Learnings

1. **알림 인프라는 자기 자신을 감시하지 못한다.** `if: failure()` 패턴은 "워크플로우가 시작은 했다"를 전제로 한다. startup_failure를 감지할 별도 채널이 필요하다 (예: 외부 크론에서 `gh run list --json conclusion`을 폴링).
2. **Reusable workflow 도입은 permission 축소 변경이다.** caller가 명시적 permission 블록을 쓰고 있다면, callee의 모든 permission 스코프를 caller에 선언해야 함. 자동 검증(PR #788) 없이는 사람 눈에 의존 불가.
3. **"배포 후 첫 실행"을 CI가 강제로 검증해야 한다.** PR 머지 직후 대표 workflow 1개를 workflow_dispatch로 자동 트리거하고 결과를 확인하는 post-merge smoke 단계가 있었다면 2시간 내 탐지 가능했을 것.
4. **Lazy import는 테스트 커버리지 사각지대.** top-level import는 `import module` 만으로 검출되지만, `def foo(): from x import y` 형태는 해당 경로가 호출될 때만 실행된다. 정적 스캔(AST)이 runtime 커버리지를 보완해야 한다.
5. **"6일 무음"은 모니터링 공백의 결과**. GitHub Actions "Run completed ✅" 배지만 보면 실패한 run이 큐에 쌓여 있어도 모른다. 대시보드에 "last success timestamp per workflow" 지표를 노출해야 한다.

## Related PRs

- PR #773 — risk_classifier import 경로 수정 (1차 장애 해결)
- PR #775 — regulatory 수집기 실패 알림 + 정규식 오탐 제거
- PR #777 — 실패 알림 reusable workflow 도입 (2차 장애 유입)
- PR #780 — 실패 알림 3개 수집기 추가 확산
- PR #783 — 실패 알림 13/13 커버 완료 + 알림 메시지 풍부화
- **PR #786** — collect-*.yml에 `actions: read` 추가 (2차 장애 해결, 리뷰 대기)
- **PR #788** — workflow_call permission lint CI 추가 (재발 방지, 리뷰 대기)
