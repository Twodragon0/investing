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

**main 실측 확인.** 프로브 브랜치 결과는 같은 룰셋·같은 규칙 타입이지만 main 자체는
아니었다. 룰셋 활성(05:07:18Z) 이후 `github-actions[bot]` 이 main 에 실제로
푸시한 것을 확인했다:

- `05:48:49Z` `chore: collect social media`
- `05:53:12Z` `chore: collect stock news`

두 건 모두 `python-collect` 공유 액션 경유다. 즉 23개 자동 푸시 경로 중 가장 많이
쓰이는 것이 Phase 1 아래서 정상 동작한다.

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
- `Vercel` — 무료 티어 빌드 쿼터로 실패한다. PR #1119 에서 코드와 무관하게
  `upgradeToPro=build-rate-limit` 로 FAILURE 였다. required 로 걸면 쿼터 소진이
  머지 차단이 된다.

#### 검토 후 기각: `tests/test_vercel_config_guard.py` 를 독립 체크로 분리 (2026-08-08)

`vercel.json` 가드가 11분짜리 `quality` 잡 안에 묻혀 있으니 전용 워크플로우로
빼서 required 로 걸자는 안을 검토했고, **기각한다.** 두 가지가 근거다.

1. **커버리지 갭이 없다.** 이 가드는 `tests/` 에 있고 `code-quality.yml` 은 PR
   트리거에 `paths:` 필터가 없다 — 즉 모든 PR 에서 돈다. 위 표의 `quality` 가
   이미 그 커버리지를 대표한다. 분리하면 같은 불변식에 required 컨텍스트가 둘로
   늘 뿐이다.
2. **분리해도 required 가 되지 않는다.** required 등록은 아래 bypass actor 제약에
   걸려 저장소 전체가 막혀 있다. 새 워크플로우를 만들어도 Phase 2 가 열리기
   전까지는 그냥 체크 하나가 더 생기는 것이다.

남는 이득은 피드백 지연 단축(11m37s → ~1min)뿐인데, 가드의 역할은 PR 을 막는
것이고 그건 두 배치 모두에서 동일하다. 지연이 실제로 문제가 된 사례가 나오면
그때 다시 본다 — 워크플로우 신설의 근거는 "더 빠르다"가 아니라 "느려서 사고가
났다"여야 한다.

### 차단 사유 — `github-actions` 는 이 저장소에서 bypass actor 가 될 수 없다 (2026-08-07 실측)

Phase 2 의 `pull_request`·`required_status_checks` 는 **직접 푸시를 막으므로 자동
푸시 23개를 그대로 차단한다.** 따라서 `github-actions[bot]` 을 bypass actor 로
넣는 것이 전제인데, GitHub 이 이를 **거부**한다:

```
POST /repos/Twodragon0/investing/rulesets
bypass_actors: [{actor_id: 15368, actor_type: "Integration", ...}]
-> 422 Validation Failed
   "Actor GitHub Actions integration must be part of the ruleset source or owner organization"
```

`enforcement: disabled` + 존재하지 않는 ref 조건으로 프로브 룰셋을 만들어 actor
타입별로 확인했다(전부 즉시 삭제):

| bypass actor | 결과 |
|---|---|
| `Integration` **github-actions** (15368) | **거부** |
| `Integration` **github-advanced-security** (57789) | **거부** |
| `Integration` vercel (8329) | 허용 |
| `Integration` gitguardian (46505) | 허용 |
| `RepositoryRole` admin(5) / maintain(2) / write(4) | 허용 |
| `DeployKey` | 허용 |

즉 "User 소유 저장소는 Integration 을 쓸 수 없다"가 아니라 **GitHub 1st-party 앱은
소유 조직에 속하지 않으면 bypass actor 가 될 수 없다**는 제약이다. 설치된
third-party 앱은 허용된다.

`RepositoryRole` 은 *사용자* 역할이라 `GITHUB_TOKEN`(= `github-actions[bot]`) 푸시를
덮지 못한다 — 허용되더라도 해결책이 아니다.

### Phase 2 를 열려면 (셋 중 하나를 골라야 한다)

1. **사용자 소유 GitHub App 생성 + 설치** (권장). 위 표에서 third-party 앱이 허용됨이
   확인됐으므로 자체 App 도 bypass actor 가 된다. 워크플로우는
   `actions/create-github-app-token` 으로 설치 토큰을 받아 푸시한다. 토큰이 여전히
   **단기·스코프 한정**이라 보안 특성이 GITHUB_TOKEN 과 가깝다. 비용: App 생성(UI
   수동), App ID·private key 시크릿 등록, 23개 푸시 지점 수정.
2. **Deploy key 푸시**. API 상 허용됨이 확인됐다. 비용은 낮지만 **장기 유효한 write
   자격증명**이 생겨 ephemeral GITHUB_TOKEN 보다 보안이 후퇴한다.
3. **저장소를 조직으로 이전**. 그러면 `github-actions` Integration bypass 가 바로
   허용된다. 가장 근본적이지만 소유 구조 변경이다.

어느 것도 고르지 않으면 **Phase 1 이 이 저장소의 상한**이다. Phase 1 은 되돌릴 수
없는 사고(force push·브랜치 삭제)를 이미 막고 있으므로 무보호 상태는 아니다.

### 결정 (2026-08-07): 보류 — Phase 1 을 상한으로 유지한다

세 경로 모두 셋업 비용 또는 보안·소유구조 트레이드오프가 있고, Phase 1 이 이미
되돌릴 수 없는 사고를 막고 있어 **지금 얻는 이득 대비 비용이 크다**고 판단했다.

이 결정을 다시 열어야 하는 신호:

- 협업자가 늘어 사람의 직접 푸시를 막을 실익이 생긴다
- 저장소를 조직으로 옮길 다른 이유가 생긴다(그러면 경로 3이 공짜가 된다)
- required check 를 우회한 회귀가 실제로 발생한다

준비 작업(조치 A·B, required check 후보 9종, 집계 잡)은 **이미 머지돼 있으므로**
경로를 고르는 순간 룰셋 생성만 남는다.

### 어느 경로를 택하든 남는 트레이드오프

bypass 를 넣으면 "그 actor 로 도는 어떤 워크플로우든 main 에 푸시 가능"이 된다.
워크플로우 파일 자체는 Phase 2 로 보호되므로 사람이 몰래 바꿀 수는 없지만, 권한
축소가 아니라 **권한 이전**임을 인식할 것.

## Phase 3 — 자동 푸시를 PR + auto-merge 로 (권장하지 않음)

수집기가 하루 여러 번 도는 구조라 PR 이 하루 수십 건 생긴다. bypass 제거의
이득보다 노이즈·API 사용량·머지 큐 지연 비용이 크다고 판단했다. 판단을 바꿀
근거가 생기면 이 절을 갱신할 것.

## 부록 — Vercel 배포 트리거 (2026-08-07)

브랜치 보호와 별개지만 같은 "main 푸시가 무엇을 유발하는가" 축이라 여기 남긴다.

`vercel.json` 의 `ignoreCommand` 가 main 푸시 중 사이트 산출물에 영향 없는 것을
건너뛴다(`_state/`·`.github/`·`tests/`·`docs/` 만 바뀐 경우). **이것이 줄이는 것은
빌드 시간뿐이다** — 배포 레코드는 skip 되어도 생성된다. 실측은 아래 "실측 결과"
절을 볼 것.

알고 있어야 하는 제약:

1. **command 필드는 256자 제한**(Vercel 스키마). 456자를 넣었다가 배포가 전부
   실패했다 — `tests/test_vercel_config_guard.py` 가 이제 이를 막는다. 이 제한
   때문에 `scripts/` 제외 + postbuild 예외(305자)를 넣을 수 없어, 제외 집합이
   `_state/`·`.github/`·`tests/`·`docs/` 로 좁아졌다(`scripts/` 변경은 빌드한다).
2. **`:!<path>` bare pathspec 금지.** 경로 첫 글자에 따라 git 이 죽고, fail-open
   이라 그 fatal 이 "빌드"로 읽혀 조용하다. `:!./<path>` 를 쓴다.
3. **프리뷰도 배포 레코드를 만든다.** `ignoreCommand` 가 비-main 을 즉시 skip 해도
   레코드는 `CANCELED` 로 남는다(2026-08-07 하루 36건 = 그날 Production 레코드와
   동수). `vercel.json` 의 `git.deploymentEnabled` 로 브랜치별 생성을 끄는 길이
   스키마상 존재하지만, **main 에 넣는 것만으로는 듣지 않는다**(2026-08-08 실측,
   아래 "후속 실측" 절). 스키마의 객체 형태는 "지정한 브랜치만 false" 이므로
   *"main 빼고 전부"* 는 표현할 수 없고, boolean 형태(`false`)는 main 까지 꺼버린다.
4. **rate limit 에 걸린 커밋은 `ignoreCommand` 를 평가조차 하지 않는다.** Vercel 이
   배포 생성 단계에서 거부하므로, 이미 쿼터가 소진된 상태에서는 이 최적화가
   개입할 여지가 없다.

### 실측 결과 (2026-08-08, 전체 목록 기준) — skip 도 배포 레코드를 만든다

이 절은 하루 사이 세 번 고쳐 적혔다. 앞의 세 서술("30% 절감으로 쿼터 관찰",
"절감은 빌드 시간뿐", "skip 은 레코드를 만들지 않으므로 배포 수도 준다")은
**모두 틀렸다.** 세 번째가 틀린 이유는 표본이다 — main 커밋 9건만 보고
Production 레코드 4건과 맞췄는데, 그날 실제 레코드는 26건이었다.

측정 방법: `vercel ls investing --environment {production,preview} -F json` 을
`--next` 로 끝까지 페이지네이션한 뒤 KST 일자별로 집계(원시 데이터 305건).

| 날짜(KST) | main 커밋 | Production 레코드 | READY | CANCELED | Preview 레코드 | 레코드 합 |
|---|---|---|---|---|---|---|
| 2026-08-04 | 40 | 13 | 12 | 1 | 11 | 24 |
| 2026-08-05 | 39 | 38 | 38 | 0 | 7 | 45 |
| 2026-08-06 | 47 | 47 | 46 | 1 | 23 | 70 |
| 2026-08-07 | 61 | 36 | 23 | 13 | 36 | **72** |
| 2026-08-08 (14:41까지) | 26 | 26 | 17 | 9 | 3 | 29 |

확정되는 것:

1. **skip 은 레코드를 만든다.** 2026-08-08 main 커밋 26건 ↔ Production 레코드
   26건이 **SHA 기준 1:1**(중복 0). 그중 9건이 `CANCELED`(= Canceled by Ignored
   Build Step)이고 나머지 17건이 `READY` 다. 즉 `ignoreCommand` 는 **빌드 시간만**
   줄이고 배포 레코드 수는 줄이지 않는다. 그날 빌드 skip 비율은 9/26 = **34.6%**
   (앞서 적은 56% 는 9건 표본에서 나온 값이다).
2. **프리뷰도 레코드를 만든다.** 최근 5일 프리뷰 레코드 80건이 전부 `CANCELED` —
   빌드는 0초지만 레코드는 남는다. 2026-08-07 에는 프리뷰 36건이 Production 36건과
   **동수**였다.
3. **레코드가 아예 안 생기는 경우가 진짜 쿼터 거절이다.** 2026-08-07 main 커밋
   61건 중 25건은 레코드가 없다. 거절은 15:54–17:56 구간에 12건 연속으로 몰렸고
   그 앞뒤 커밋은 정상 생성됐다 — 누적 총량이 아니라 시간 구간에 반응한다.
   (같은 푸시에 담긴 연속 커밋 중 앞 커밋이 빠지는 건 별개 현상이다: 10:06 / 10:35
   / 10:40 처럼 5초 간격 쌍에서 head 커밋만 배포된다.)

**프리뷰 소비원 (2026-08-04~08, 프리뷰 80건):**

| 건수 | 브랜치 |
|---|---|
| 27 | `python-coverage-comment-action-data` |
| 5 | `feat/url-summary-backfill` |
| 3 | `dependabot/github_actions/actions/checkout-7.0.1` |
| 나머지 | PR 브랜치 1–2건씩 |

**결정: 봇 데이터 브랜치의 배포 생성을 끈다.** `python-coverage-comment-action-data`
는 커버리지 액션이 데이터를 커밋하는 orphan 브랜치라 프리뷰가 아무 의미도 없는데
프리뷰 레코드의 **34%(27/80)** 를 혼자 쓴다. main 의 `vercel.json` 에
`git.deploymentEnabled: {"python-coverage-comment-action-data": false}` 를 넣었다 —
**다만 이것만으로는 막히지 않았다.** 아래 "후속 실측" 절을 볼 것.

PR 브랜치 프리뷰는 남긴다 — 건수가 분산돼 있고 리뷰 가치가 있다. 그래도 부족하면
수집기 푸시 배칭(main 커밋 자체를 줄이는 유일한 레버) → 플랜 업그레이드 순이다.

### 후속 실측 (2026-08-08 15:24) — main 에 넣은 `git.deploymentEnabled` 는 듣지 않았다

위 조치의 "아직 미검증" 항목을 머지 직후 확인했고, **기대는 틀렸다.**

| 시각(KST) | 사건 |
|---|---|
| 15:16:13 | `git.deploymentEnabled` 를 담은 머지 커밋 `afa44a862` 가 main 에 착지 |
| 15:24:09 | 커버리지 액션이 `dc3a0957d` 를 `python-coverage-comment-action-data` 에 푸시 |
| 15:24:13 | Vercel 이 프리뷰 배포 레코드를 **생성** — `CANCELED` |

즉 main 의 `vercel.json` 은 다른 브랜치의 배포 생성을 막지 못한다. 설정이
전파될 8분이 있었고 브랜치 키는 정확히 일치했다.

가장 잘 들어맞는 설명은 **Vercel 이 `vercel.json` 을 푸시된 커밋의 ref 에서
읽는다**는 것이다. 배포를 만들기 *전에* 판정해야 하므로 그 ref 말고는 읽을
것이 없다. 같은 관측이 이를 뒷받침한다 — 이 브랜치는 자체 `vercel.json`
(`{"ignoreCommand": "exit 0"}`, 커밋 `d4afb3172`)을 갖고 있고, 레코드가 매번
`CANCELED` 로 남는 것이 바로 그 브랜치-로컬 설정이 적용된 결과다.

Vercel 공식 문서(`/docs/project-configuration/git-configuration`)는 어느 ref 에서
읽는지를 **명시하지 않는다**. 위 설명은 관측 1건에 대한 최적 가설이지 벤더가
확인해 준 사실이 아니다.

### 확정 (2026-08-10) — 설정은 그 브랜치 자신의 `vercel.json` 에 있어야 한다

위 가설대로 `git.deploymentEnabled` 를 `python-coverage-comment-action-data`
브랜치 자신의 `vercel.json` 에 넣고 관측했다.

| 커밋 | 시각(KST) | 브랜치 vercel.json 에 설정 | 프리뷰 레코드 |
|---|---|---|---|
| `5f2fd673` … `dc3a0957` (6건) | 08-07~08-08 | ✗ | **6건 전부 생성**(CANCELED) |
| `ea93958a` (설정을 넣은 커밋) | 08-10 10:00:55 | ✓ | **없음** |
| `b30a1fd9` (커버리지 액션의 다음 푸시) | 08-10 10:06:25 | ✓ | **없음** |

**대조군이 결정적이다.** 같은 10:07:53–10:08:09 구간에 Dependabot 브랜치 5건이
정상적으로 프리뷰 레코드를 만들었다 — Vercel Git 통합이 죽어 있어서 안 생긴 게
아니다. 커버리지 액션이 그 뒤로도 `vercel.json` 을 지우지 않는 것도 확인했다
(`b30a1fd9` 트리에 그대로 있다).

결론 세 줄:

1. `git.deploymentEnabled` 는 **푸시된 커밋의 ref** 에 있는 `vercel.json` 에서
   읽힌다. main 에 넣어도 다른 브랜치에는 듣지 않는다.
2. 따라서 main 의 `vercel.json` 에 있는
   `{"python-coverage-comment-action-data": false}` 는 **아무 일도 하지 않는다.**
   지우지는 않았다 — 해롭지 않고, 어느 ref 에서 읽는지가 벤더 문서에 없는 이상
   동작이 바뀔 수 있는 선언을 한쪽만 남기는 게 더 위험하다.
3. 프리뷰를 끄고 싶은 봇 브랜치가 또 생기면 **그 브랜치에** 같은 파일을 넣는다.
   저장소 중앙에서 일괄로 끄는 방법은 이 경로로는 없다.
