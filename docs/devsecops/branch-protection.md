# main 브랜치 보호 — 단계별 적용 기록

이 저장소는 **main 에 직접 푸시하는 워크플로우가 23개**다. 그래서 브랜치 보호를
한 번에 켜면 수집 파이프라인이 멈춘다. 단계를 나눈 이유와 각 단계의 제약을 여기
기록한다.

매핑: OWASP **CICD-SEC-1**(Insufficient Flow Control), NIST SSDF(SP 800-218)
**PO.3 / PS.1**.

## 자동 푸시 인벤토리

| 경로 | 개수 | 비고 |
|---|---|---|
| `.github/actions/python-collect/action.yml:197` 의 `git push origin main` | 17 워크플로우 | 공유 composite action. rebase 재시도 루프 포함 |
| 워크플로우 내 직접 푸시 | 6 | `backfill-url-summaries`, `check-post-images`, `cleanup-old-images`, `generate-journal-og-images`, `generate-weekly-report`, `watchdog-zero-job-runs`(git-auto-commit-action) |

소유자가 User 계정이므로 classic branch protection 의 push allowlist(조직 전용)를
쓸 수 없다. **ruleset** 으로 구성한다.

## Phase 1 — force-push · 브랜치 삭제 차단 (적용됨)

- 룰셋 **id 20539046** `main: block force-push and deletion (phase 1)`
- 대상 `refs/heads/main`, rules `deletion` + `non_fast_forward`
- `bypass_actors: []` — 예외 없음
- enforcement `active`, 적용 2026-08-07T05:07:18Z

**bypass 가 필요 없는 이유:** 두 규칙은 fast-forward 푸시를 건드리지 않는다.
자동 푸시 23개는 전부 fast-forward(또는 rebase 후 fast-forward)이므로 영향이 없다.

### 실측 검증

프로브 브랜치를 같은 룰셋 범위에 임시 편입해 세 경로를 확인한 뒤 범위를 main
전용으로 복원했다. main 자체를 실험 대상으로 삼지 않았다.

| 케이스 | 결과 | rc |
|---|---|---|
| fast-forward 푸시 | 허용 | 0 |
| force-push 되감기 | 거부 (`GH013: Repository rule violations found`) | 1 |
| 브랜치 삭제 | 거부 (`GH013`) | 1 |

> 검증 하네스 주의: `if git push ... \| tail` 은 `tail` 의 종료코드를 평가하므로
> 거부를 "통과"로 오판한다. `out=$(cmd 2>&1); rc=$?` 로 캡처할 것.

## Phase 2 — PR 필수 + 상태 체크 필수 (미적용)

### 막고 있던 제약: 경로 필터와 required check 는 공존하지 않는다

required status check 는 **이름으로 매칭**된다. 워크플로우 수준 `paths:` 필터가
걸려 있으면 그 경로를 건드리지 않은 PR 에서 워크플로우가 아예 돌지 않고, 체크가
생성되지 않는다. 그 이름을 required 로 등록하면 그런 PR 은 **영구 대기**한다.

반대로 워크플로우는 항상 돌고 **잡만** `if:` 로 skip 하면 체크가 `skipped` 로
보고되고, GitHub 은 skipped required check 를 통과로 취급한다. 이것이 아래 두
가지 조치의 근거다.

### 조치 A — 저렴한 게이트는 필터를 걷었다

| 워크플로우 | 조치 | 근거 |
|---|---|---|
| `security-scan.yml` | PR 트리거의 `paths:` 제거 | **보안 갭이었다.** 필터가 `scripts/**`·`.github/workflows/**`·`.gitleaks.toml` 뿐이어서 `_posts/`·`_data/`·`docs/`·`assets/`·루트 설정에 커밋된 시크릿은 그 PR 에서 스캔되지 않았다. 비용 실측 ~3 job-minute |
| `dependency-review.yml` | PR 트리거의 `paths:` 제거 | 액션이 의존성 diff 를 보므로 매니페스트 무변경 PR 은 즉시 통과(~30s) |

`security-scan.yml` 의 `push` 트리거 필터는 유지했다 — main 푸시는 자동 커밋이
하루 수십 건이고 required check 대상이 아니며 주간 스케줄이 전수를 덮는다.

### 조치 B — 비싼 게이트는 집계(aggregator) 잡으로

`guard-falsifiability.yml` 은 8샤드 ~4분이라 매 PR 전수 실행이 낭비다. 구조를
바꿨다:

```
changes (항상 실행, 변경 파일 판정)
  └─ falsifiability (if: needs.changes.outputs.relevant == 'true', 8샤드)
       └─ gate (if: always(), needs: [changes, falsifiability])   ← required check 대상
```

- `gate` 는 `skipped` 를 **통과**로, `failure`/`cancelled` 를 실패로 본다.
  `success` 만 통과로 두면 skip 경로가 전부 red 가 된다.
- `changes` 가 실패하면 "관련 변경 없음"을 신뢰할 수 없으므로 fail closed.
- **샤드를 직접 required 로 걸지 않는다.** 체크 이름이 `falsifiability (3/8)`
  처럼 매트릭스 크기를 포함하므로, 샤드 수를 바꾸면 등록된 컨텍스트가 존재하지
  않는 이름이 되어 모든 PR 이 영구 대기한다. `gate` 는 이름이 고정이다.

#### 트리거 경로를 손으로 유지하지 않는다

`changes` 잡은 `guard_falsifiability.py --list-targets` 가 **케이스 정의에서
파생한** 경로 목록을 쓴다. 손으로 유지하던 19개 목록은 이미 7개를 놓치고
있었다 — `tests/_tree_write_guard.py`(STATIC_CASES 5건의 변형 대상),
`scripts/common/dedup.py`, `scripts/common/image_rejection_metrics.py`,
`scripts/fix_defi_tvl_history.py`, `scripts/check_description_quality.py`,
`tests/test_tree_write_guard.py`, `tests/test_encoding_guard.py`. 즉 그 파일들을
편집해도 하네스가 돌지 않았다. 파생으로 바꿔 드리프트를 구조적으로 없앴다.

이 배선은 `tests/test_required_check_aggregator_guard.py` 가 강제한다(5케이스:
`needs:` 완결성, `always()` 존재, `paths:` 부재, 스캐너 양방향).

### required check 후보 (Phase 2 적용 시)

전 PR 무조건 생성되는 체크만 등록할 수 있다.

| 체크 이름 | 출처 | 적격 |
|---|---|---|
| `quality` | `code-quality.yml` | ✅ 필터 없음 |
| `Analyze (actions)` / `(javascript-typescript)` / `(python)` / `(ruby)` | CodeQL default setup(워크플로우 파일 없음) | ✅ |
| `Python SAST (Bandit)` · `Secret Detection` · `Workflow Permissions Audit` | `security-scan.yml` | ✅ 조치 A 이후 |
| `Dependency Review` | `dependency-review.yml` | ✅ 조치 A 이후 |
| `Falsifiability gate` | `guard-falsifiability.yml` | ✅ 조치 B 이후 |

**등록하지 않을 것:**

- `i18n-e2e` / `reports-e2e` — Playwright 기반이고 기능 한정. 두 워크플로우의 잡
  id 가 **둘 다 `e2e`** 여서 required 컨텍스트로 모호하다(이름을 먼저 구분해야
  한다).
- `Verify action pins against upstream` — 업스트림 API 의존. 네트워크/rate limit
  장애가 머지를 막는 대가가 이득보다 크다. 주간 스케줄 + 워크플로우 변경 PR 로
  충분하다.
- `lighthouse-ci` / `coverage-comment` — `pull_request` 트리거가 없다.

### 남은 미검증 항목

- Phase 2 는 PR 필수화가 자동 푸시를 막으므로 **bypass actor 가 필요**하다.
  `github-actions[bot]`(Integration) 을 bypass 로 넣는 것이 후보이며, 룰셋을 실제로
  만들어봐야 API 형태가 확정된다. Phase 1 은 bypass 가 없어 이 불확실성이 없다.
- bypass 를 넣으면 "어떤 워크플로우든 main 에 푸시 가능"이 된다. 워크플로우 파일
  자체는 Phase 2 로 보호되므로 사람이 몰래 바꿀 수는 없지만, 권한 축소가 아니라
  **권한 이전**임을 인식할 것.

## Phase 3 — 자동 푸시를 PR + auto-merge 로 (권장하지 않음)

수집기가 하루 여러 번 도는 구조라 PR 이 하루 수십 건 생긴다. bypass 제거의
이득보다 노이즈·API 사용량·머지 큐 지연 비용이 크다고 판단했다. 판단을 바꿀
근거가 생기면 이 절을 갱신할 것.
