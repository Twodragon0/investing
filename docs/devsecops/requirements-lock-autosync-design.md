# requirements.lock 자동 동기 PR 파이프라인 — 설계 (#2 원안)

> 상태: **부분 구현** (2026-08-21) · 작성 2026-06-24 · **§9 추가 2026-08-24 (권장안 교체)** · 대상 `scripts/requirements.txt` ↔ `scripts/requirements.lock`
> 선행 컨텍스트: `supply-chain-lock.yml`, `tests/test_requirements_lock_coverage.py`,
> `scripts/refresh_requirements_lock.sh`, `.github/dependabot.yml`, `.github/workflows/dependabot-auto-merge.yml`

## 0. 구현 상태 (2026-08-21)

`.github/workflows/requirements-lock-sync.yml` — 옵션 A 의 **토큰 불필요 부분집합**.
인바리언트 가드는 `tests/test_requirements_lock_sync_workflow_guard.py`.

| 설계 항목 | 상태 |
|---|---|
| §2 in-place 앵커 재생성 | 구현 — 헬퍼 그대로 호출, `--upgrade` 없음 (가드가 강제) |
| §5.2 `pull_request_target` 금지 | 구현 — `pull_request` 만 사용 (가드가 강제) |
| §5.4 무한 루프 방지 | 구현 — `paths` 를 `requirements.txt` 로 한정 (가드가 강제) |
| §5.5 결정성 (python 3.11) | 구현 (가드가 강제) |
| §6.1 임시 버전-동기 가드 | 이미 존재 — `tests/test_requirements_lock_version_sync.py` |
| §5.1 커밋백 | **미구현** — 그리고 §5.1/옵션 A 의 토큰 전제가 **틀렸다**. §9.1 참조 |
| §5.3 자동머지 순서 강제 | **미구현** — 아래 참조 |

### 커밋백을 넣지 않은 이유

토큰이 없다. 그래서 워크플로우는 재생성된 락을 **artifact + step summary** 로 내놓고
drift 시 잡을 실패시키는 데까지만 한다. 토큰 없이 커밋백 코드를 미리 넣으면 한 번도
실행해 볼 수 없는 경로가 되므로 넣지 않았다. 올리는 절차는 워크플로우 상단 주석에 있다.

> **2026-08-24 정정.** 워크플로우 상단 주석과 §5.1 / 옵션 A 가 지시하는 절차
> (`secrets.LOCK_SYNC_TOKEN` 을 등록하고 `actions/checkout` 에 `token:` 을 주는 것)는
> **Dependabot PR 에서 작동하지 않는다** — Dependabot 이 트리거한 런은 Actions 시크릿에
> 접근할 수 없어 그 시크릿이 빈 문자열로 해소되고 push 가 403 이 된다. 고치려는 대상이
> 바로 Dependabot PR 이므로 이 실패는 확정적이다. 구현에 착수하기 전 **§9 를 먼저 읽을
> 것**. 대안 구조(§9.2 `workflow_run` 분리)는 생산자 절반이 이미 구현돼 있고, 위 "실행해
> 볼 수 없는 코드" 반론도 벗어난다(§9.5).

### §5.3 은 여전히 열려 있다 (실측 2026-08-21)

main 룰셋(`20539046`)에는 **required status check 가 하나도 없다** — `deletion` 과
`non_fast_forward` 뿐이다. 즉 `test_requirements_lock_version_sync` 가 red 여도 머지를
물리적으로 막지 못하고, `dependabot-auto-merge.yml` 은 semver-patch 를 자동 승인·자동
머지한다. stale 락이 사람 리뷰 없이 들어갈 수 있는 구조가 그대로 남아 있다.

`supply-chain-lock.yml` 은 `paths:` 필터가 있어 그대로 required 로 지정하면 무관 PR 이
영구 대기한다(룰셋 Phase 2 가 막힌 것과 같은 이유). aggregator 잡 선행이 필요하며 이
문서 범위 밖의 별도 작업이다.

## 1. 문제 (왜 필요한가)

추가형 공급망 방어(2026-06-22)로 `scripts/requirements.lock`(해시 핀 락)을 도입했지만,
**의존성 봇이 `requirements.txt` 를 bump 할 때 락은 자동 갱신되지 않는다.** 봇 PR 은
직접 의존성 버전만 올리고 전이 의존성+해시 락은 손대지 않으므로 락이 stale 해진다.

### 1.1 현재 가드가 이 stale 을 잡지 못하는 구간 (실증)

| 가드 | 트리거 | 버전 bump(기존 dep)에 반응? | 신규 dep 추가에 반응? |
|------|--------|:--:|:--:|
| `tests/test_requirements_lock_coverage.py` (매 PR pytest) | 모든 PR | ❌ (이름 presence만 검사, 버전 무관) | ✅ (이름 미존재 → 실패) |
| `supply-chain-lock.yml` Verify lock integrity (`--require-hashes --dry-run`) | `requirements.{txt,lock}` 변경 | ❌ (락 내부 일관 → 통과, 단 **구버전**을 검증) | ❌ |
| `supply-chain-lock.yml` Verify lock covers direct deps | 〃 | ❌ (이름 기반) | ✅ |

→ **버전 bump 의 경우** 모든 가드가 green 인데도 락은 구버전을 핀한 채로 남는다.
런타임 12개 워크플로우는 `pip install -r requirements.txt` 로 **신버전**을 받고,
락 무결성 검증은 **구버전**을 확인한다 → 검증 대상과 실제 설치 대상의 괴리.

### 1.2 위험 증폭 요인

- `dependabot-auto-merge.yml` 은 patch bump 를 **자동 승인·자동 머지**한다.
  stale 락이 사람 리뷰 없이 main 에 들어갈 수 있다.
- **2026-07-06 차단 승격 예정**(`supply-chain-lock.yml` 상단 주석): 승격 후에는
  `--require-hashes` 가 차단 게이트가 되므로, 봇 bump 후 락 미갱신 상태에서 누군가
  락을 부분 수정하면 무결성 실패로 CI 가 red 가 된다. 자동 동기화가 없으면 봇 PR마다
  수동 `refresh_requirements_lock.sh` 가 강제된다(운영 마찰).

## 2. 목표

> `requirements.txt` 를 바꾸는 PR(특히 의존성 봇 PR)에서 `requirements.lock` 을
> **in-place 재생성**(앵커 유지 → bump 된 패키지만 이동, 무관 패키지 상류 drift 0)하여
> 머지/자동머지 **이전에** txt↔lock 을 lockstep 으로 맞춘다.

비목표: 전 패키지 일괄 최신화(그건 `lockFileMaintenance`/주기 작업의 영역), 락 포맷 변경.

## 3. 핵심 실증 (이 설계의 전제, 2026-06-24 측정)

격리 venv(python3.11.15) + `pip-compile --generate-hashes`:

1. **신선 파일로 재생성** → `boto3 1.43.34→1.43.36`, `botocore` 동반 상승.
   원인: 유일한 범위 제약 `boto3>=1.40,<2` 가 앵커 없을 때 최신으로 해소됨.
2. **기존 락을 앵커로 in-place 재생성**(= 헬퍼의 실제 동작, `--upgrade` 없음)
   → 커밋된 락과 **비-주석 byte-identical**. (헤더의 `--output-file=` 경로만 상이)
3. pip-tools **7.5.3** 가 위 byte-identical 을 만든 버전. → 헬퍼 기본 핀으로 고정.

**설계 함의:** 동기화는 반드시 **기존 락을 체크아웃한 상태에서 in-place** 로 돌려야
무관 패키지 drift 없이 "봇이 올린 그 패키지만" 락에 반영된다. `refresh_requirements_lock.sh`
가 이미 이 동작을 한다 → 파이프라인은 이 헬퍼를 그대로 호출하면 된다.

## 4. 설계 옵션

### 옵션 A — Dependabot 유지 + 반응형 lock-sync 워크플로우 (권장)

`requirements.txt` 를 건드리는 PR 에서 락을 재생성해 **같은 PR 브랜치에 커밋백**.

```yaml
# .github/workflows/requirements-lock-sync.yml  (스케치)
name: Requirements Lock Sync
on:
  pull_request:
    paths: ['scripts/requirements.txt']
permissions:
  contents: write          # PR 브랜치에 커밋백
  pull-requests: write
concurrency:
  group: lock-sync-${{ github.event.pull_request.number }}
  cancel-in-progress: true
jobs:
  sync:
    runs-on: ubuntu-latest
    timeout-minutes: 12
    steps:
      - uses: actions/checkout@<pin v6>
        with:
          ref: ${{ github.head_ref }}     # PR head 체크아웃 (기존 락=앵커 포함)
          token: ${{ secrets.LOCK_SYNC_TOKEN }}  # ← 아래 5절 토큰 주의
      - uses: actions/setup-python@<pin v6>
        with: { python-version: '3.11' }   # 락은 3.11 에서 생성
      - run: bash scripts/refresh_requirements_lock.sh   # pip-tools 7.5.3 핀, in-place
      - name: Commit lock if changed
        run: |
          if ! git diff --quiet -- scripts/requirements.lock; then
            git config user.name  "github-actions[bot]"
            git config user.email "github-actions[bot]@users.noreply.github.com"
            git add scripts/requirements.lock
            git commit -m "chore(deps): sync requirements.lock for $(git log -1 --format=%h)"
            git push origin HEAD:${{ github.head_ref }}
          fi
```

장점: dependabot 설정 유지, 헬퍼 재사용, 변경 최소.
단점: **봇 PR 푸시백 토큰 제약**(5절) 때문에 별도 PAT/App 토큰 필요. 커밋백이
새 CI 를 자동 재트리거하지 않는 점도 토큰 선택과 얽힘.

### 옵션 B — Renovate `pip-compile` manager (대안)

Renovate 는 `pip-compile` 출력 파일을 네이티브로 인식해 **같은 PR 안에서** txt bump 와
lock 재생성을 함께 만든다(커밋백 해킹·별도 토큰 불필요).

```jsonc
// renovate.json (스케치)
{
  "$schema": "https://docs.renovatebot.com/renovate-schema.json",
  "extends": ["config:recommended"],
  "pip-compile": {
    "fileMatch": ["^scripts/requirements\\.txt$"]
  },
  "lockFileMaintenance": { "enabled": true, "schedule": ["before 5am on monday"] }
}
```

장점: 단일 PR, 락이 항상 txt 와 동행, 푸시백/토큰 이슈 없음. `lockFileMaintenance` 로
전이 의존성 주기 갱신까지 일원화.
단점: Dependabot→Renovate **봇 교체**(현 `dependabot.yml`/`dependabot-auto-merge.yml`
폐기 또는 공존 정리 필요). 호스티드 Renovate 앱은 `postUpgradeTasks` 임의 명령에 제약이
있으나 `pip-compile` manager 는 빌트인이라 무관. Python 버전 고정(3.11) 보장 방법 확인 필요.

## 5. 보안·운영 foot-gun (반드시 설계에 반영)

1. **Dependabot PR 토큰은 기본 read-only.** Actions 의 `GITHUB_TOKEN` 은 dependabot
   이벤트에서 권한이 축소되고, **그 토큰으로 푸시한 커밋은 새 워크플로우를 재트리거하지
   않는다.** → 커밋백이 CI 를 다시 돌리려면 **fine-grained PAT** 또는 **GitHub App
   토큰**(`secrets.LOCK_SYNC_TOKEN`)이 필요. (현 repo 의 자가 커밋 워크플로우들은 main
   에 `GITHUB_TOKEN` 으로 직접 푸시 — PR 브랜치 푸시백과는 토큰 요건이 다르다.)
2. **`pull_request_target` 금지(또는 극도 주의).** write 토큰을 얻으려 `pull_request_target`
   + PR head 체크아웃 + 코드 실행은 전형적 권한 상승 RCE 패턴. `pip-compile` 은 sdist
   빌드 시 임의 코드를 실행할 수 있어 위험. → 옵션 A 는 `pull_request`(read 토큰)에서
   돌리고 **푸시만** 별도 PAT/App 로 수행, 또는 신뢰 봇 PR 로 한정(`github.actor`).
3. **자동머지 순서.** `dependabot-auto-merge.yml` 의 auto-merge 가 lock-sync 보다 먼저
   완료되면 stale 락이 머지된다. → lock-sync 를 **required check** 로 걸어 머지를 게이트
   하거나, auto-merge 활성 스텝이 lock-sync 성공에 의존하도록 순서를 강제.
4. **무한 루프 방지.** 커밋백이 동일 워크플로우를 다시 트리거하지 않도록 `paths` 필터를
   `requirements.txt` 로 한정(락만 바뀐 푸시는 트리거 안 됨) — 위 스케치는 이미 충족.
5. **결정성.** 반드시 `python-version: '3.11'` + 헬퍼의 `PIP_TOOLS_VERSION=7.5.3` 기본
   핀 + in-place(앵커) 경로 유지. 신선 파일 재생성/`--upgrade` 는 무관 패키지 drift 를
   부른다(3절).

## 6. 권장안

- **단기(저마찰):** 옵션 A. 단, **PAT/App 토큰 등록이 선행 조건**. 토큰 없이 `GITHUB_TOKEN`
  으로 봇 PR 브랜치에 푸시는 사실상 불가/재트리거 불가 → 토큰 확보 전까지는 "락 미동기 시
  CI 실패" 가드만으로 **수동 헬퍼 실행을 강제**하는 편이 안전(아래 6.1).
- **중기(일원화):** 봇을 Renovate 로 통일할 의향이 있으면 옵션 B 가 구조적으로 가장 깔끔
  (단일 PR·토큰 무관·전이 갱신 일원화). 봇 교체 비용만 수용하면 됨.

### 6.1 토큰 도입 전 임시 가드(권장 즉시 적용 가능, 별도 설계)

버전 bump 시 stale 을 **확정적으로 red** 로 만들기 위해, `supply-chain-lock.yml` 에
"txt 직접 의존성의 `==`/범위 해소 버전이 락의 핀과 일치하는지" 검사를 추가하면(이름뿐
아니라 **버전**까지) 봇 PR 의 stale 을 즉시 노출 → 작성자가 `refresh_requirements_lock.sh`
실행하도록 강제. (현 coverage 가드는 이름만 봐서 1.1 의 구멍이 남음.) 단 범위 제약
(`>=`,`~=`,`<`)은 "해소된 버전"을 알아야 하므로 단순 문자열 비교론 부족 — pip 해소 결과와
대조해야 한다. 이 버전-동기 가드는 별도 RFC 로 분리 권장.

## 7. 롤아웃 & 검증 체크리스트

1. 토큰 결정(PAT/App vs Renovate) → `AskUser`.
2. 워크플로우/Config 추가, **모든 액션 SHA 핀**(repo 관례).
3. 실 봇 PR 1건에서 dry-run: 락이 in-place 로만 갱신되는지(무관 drift 0) 확인 —
   `git diff scripts/requirements.lock` 가 bump 패키지+전이만 보여야 함.
4. `tests/test_requirements_lock_coverage.py` + `supply-chain-lock.yml` 둘 다 green.
5. auto-merge 와의 순서: lock-sync 를 required check 로 등록했는지 확인.
6. 2026-07-06 차단 승격과 상호작용 재점검(stale 락이 차단 게이트에 걸리지 않는지).

## 8. 결론

핵심은 **"in-place 앵커 재생성"** 한 줄로 요약된다 — 헬퍼가 이미 그 동작을 하므로
파이프라인은 *언제·어떤 토큰으로* 헬퍼를 호출하느냐의 문제로 환원된다. 토큰 제약이
유일한 실질 난점이며, 그것을 피하려면 Renovate `pip-compile` manager(옵션 B)가
구조적으로 우월하다. 구현 착수 전 7.1(토큰 결정)을 사용자에게 질의할 것.

> **2026-08-24.** 토큰 제약의 정확한 성질이 §9.1 에서 규명됐고, 그에 따라 권장안은
> 옵션 A → **옵션 C(§9)** 로 교체된다. 옵션 B(Renovate)는 여전히 유효한 대안이며,
> "아무것도 하지 않는다"(§9.8)도 실측 정체 비용을 근거로 합리적 선택지다.

---

## 9. 옵션 C — `workflow_run` 분리 커밋백 (2026-08-24 추가, **권장으로 대체**)

> 이 절은 §5.1 / 옵션 A 의 토큰 전제를 **정정**한다. 옵션 A 스케치를 그대로 구현하면
> Dependabot PR 에서 조용히 아무 일도 일어나지 않는다.

### 9.1 옵션 A 가 작동하지 않는 이유 (문서화되지 않았던 제약)

§5.1 과 옵션 A 스케치는 `secrets.LOCK_SYNC_TOKEN` 을 등록하면 된다고 적었다. 그런데
**Dependabot 이 트리거한 워크플로우는 Actions 시크릿에 접근할 수 없다.** 접근 가능한
것은 별도 저장소인 **Dependabot 시크릿** 뿐이다:

> For workflows initiated by Dependabot using the `pull_request` … events,
> `GITHUB_TOKEN` has read-only permissions by default, **secrets are populated from
> Dependabot secrets, and GitHub Actions secrets are not available.**

즉 옵션 A 를 그대로 구현하면 `secrets.LOCK_SYNC_TOKEN` 이 **빈 문자열**로 해소되고,
`actions/checkout` 은 기본 `GITHUB_TOKEN`(read-only)으로 폴백해 push 가 403 으로 죽는다.
고치려는 대상이 바로 Dependabot PR 이므로, **이 실패는 100% 발생한다.**

`pull_request_target` 도 탈출구가 아니다 — PR 작성자가 dependabot 이면 그쪽도 토큰이
read-only 이고 시크릿이 없다(§5.2 의 RCE 논거와 별개로 애초에 작동하지 않는다).

따라서 옵션 A 를 살리려면 토큰을 **Dependabot 시크릿 저장소**에 등록해야 하는데, 그
경우 장수명 쓰기 자격증명이 `pip-compile`(sdist 빌드로 임의 코드 실행 가능)과 **같은
잡** 에 노출된다. §5.2 가 `pull_request_target` 을 거부한 것과 정확히 같은 위험이다.

### 9.2 구조

권한 경계를 잡 단위로 쪼갠다.

```
[생산자] requirements-lock-sync.yml          ← 이미 구현되어 있음
  트리거: pull_request (paths: scripts/requirements.txt)
  토큰  : read-only GITHUB_TOKEN, 시크릿 없음
  하는일: refresh_requirements_lock.sh 실행 (← 신뢰할 수 없는 코드가 여기서 돈다)
          재생성된 락을 artifact `requirements-lock` 으로 업로드
          drift 시 잡 실패
                          │
                          │ workflow_run: completed
                          ▼
[소비자] requirements-lock-commitback.yml    ← 신규 (이 절의 대상)
  트리거: workflow_run (workflows: [Requirements Lock Sync])
  컨텍스트: **기본 브랜치**. Actions 시크릿 + write 토큰 사용 가능
  하는일: artifact 다운로드 → 검증 → App 토큰으로 PR head 브랜치에 push
```

핵심 근거는 `workflow_run` 의 문서화된 성질이다:

> The workflow started by the `workflow_run` event is able to access secrets and
> write tokens, **even if the previous workflow was not.**

이것이 9.1 의 제약을 해소한다. 소비자는 Dependabot 이 트리거한 것이 아니라 **기본
브랜치에서 실행되는 별개 워크플로우**이므로 정상적인 Actions 시크릿을 받는다.
Dependabot 시크릿 저장소를 쓸 필요가 없다.

### 9.3 왜 소비자도 `GITHUB_TOKEN` 으로는 부족한가

소비자의 `GITHUB_TOKEN` 은 `contents: write` 를 받을 수 있어 push 자체는 된다. 그런데:

> events triggered by the `GITHUB_TOKEN` … will not create a new workflow run

즉 커밋백 후 PR 의 `sync`/`verify`/`quality` 가 **재실행되지 않아** 낡은 red 가 그대로
남고, `dependabot-auto-merge.yml` 은 영원히 진행하지 못한다. 락을 고쳐놓고도 PR 은
막힌 채로 있는, 지금보다 더 헷갈리는 상태가 된다.

**GitHub App 설치 토큰**은 이 억제 대상이 아니라 push 가 워크플로우를 재트리거한다.
문서도 이 용도로 App 토큰 또는 PAT 를 지목한다. 조직 자동화에서는 봇 계정 PAT 보다 App
이 권장되며, App 설치 토큰은 **단수명(1시간)** 이라 장수명 PAT 보다 유출 피해가 작다.

필요한 Actions 시크릿(더미값 표기):

```
LOCK_SYNC_APP_ID          = your-app-id-here
LOCK_SYNC_APP_PRIVATE_KEY = your-private-key-pem-here
```

App 권한은 최소로: 대상 저장소에 `contents: write` 만. PR 쓰기·이슈 쓰기 불필요.

### 9.4 소비자는 artifact 를 신뢰해서는 안 된다 (이 설계의 핵심 안전 요구)

`workflow_run` 소비자는 **특권** 컨텍스트다. 그리고 artifact 를 만든 생산자는
**PR 의 체크아웃에서** `scripts/refresh_requirements_lock.sh` 를 실행했다. 악의적 PR 은
그 스크립트나 워크플로우 자체를 수정해 임의 내용을 artifact 에 담을 수 있다. 소비자가
그것을 그대로 푸시하면 특권 경계를 우회하는 통로가 된다 — GitHub 문서도
`workflow_run` 에서 신뢰할 수 없는 코드를 다루는 위험을 경고한다.

그래서 소비자는 push 전에 다음을 **모두** 만족하는지 확인하고, 하나라도 어긋나면
중단한다:

1. **작성자 제한** — 트리거한 run 의 PR 작성자가 `dependabot[bot]` 일 것.
   (사람 PR 은 커밋백 대상이 아니다. 사람은 헬퍼를 직접 돌리면 된다.)
2. **동일 저장소 head** — head repo == base repo. 포크 PR 은 거부.
   (Dependabot 브랜치는 항상 같은 저장소다.)
3. **PR 이 신뢰 경계를 건드리지 않았을 것** — 그 PR 의 변경 파일이
   `scripts/requirements.txt` **하나뿐**일 것. `refresh_requirements_lock.sh`,
   `.github/workflows/**`, `pyproject.toml`, `scripts/**/*.py` 를 건드린 PR 은 거부.
4. **artifact 가 락 파일 하나일 것** — 경로가 정확히 `scripts/requirements.lock`,
   심링크·경로탈출(`..`) 없음, 크기 상한 검사.
5. **가드 재실행** — 기본 브랜치의(즉 신뢰되는) 코드로
   `tests/test_requirements_lock_coverage.py` + `test_requirements_lock_version_sync.py`
   를 artifact 락에 대해 다시 돌릴 것. 생산자가 돌린 결과를 믿지 않는다.
6. **diff 범위** — push 하는 커밋이 `scripts/requirements.lock` **한 파일만** 바꿀 것.

3번이 특히 중요하다. Dependabot 은 `requirements.txt` 만 바꾸므로 이 제한은 정상
동작을 전혀 막지 않으면서, 신뢰 경계를 건드린 PR 을 자동 커밋백에서 배제한다.

### 9.5 "실행해 볼 수 없는 코드" 반론에 대한 답

`requirements-lock-sync.yml` 상단 주석은 커밋백을 미루는 이유를 이렇게 적었다 —
"토큰이 없어 한 번도 실행해 볼 수 없는 코드가 된다." 옳은 판단이었고, 옵션 A 에는
그대로 적용된다(Dependabot PR 에서만 실행되므로 토큰 없이는 검증 불가).

옵션 C 는 그 반론을 벗어난다. 소비자는 `workflow_run` 으로 트리거되고, 생산자는
**사람 PR 에서도** 돈다(`paths: scripts/requirements.txt` 만 맞으면 된다). 따라서:

- 사람이 `scripts/requirements.txt` 를 건드린 PR 을 하나 열면 생산자 → 소비자 체인이
  실제로 실행된다. 9.4 의 1번(작성자 제한) 때문에 push 는 하지 않고 "dependabot PR
  아님 → skip" 으로 끝나지만, **artifact 다운로드·검증·토큰 발급까지의 경로는 전부
  실측된다.**
- 그 skip 지점을 `workflow_dispatch` 입력으로 우회할 수 있게 두면 push 까지 1회
  end-to-end 검증이 가능하다(전용 테스트 브랜치 대상).

즉 옵션 C 는 토큰 등록 **이전에** 대부분을, 등록 직후에 전부 검증할 수 있다.

### 9.6 §5.3(자동머지 순서)과의 상호작용

커밋백이 성공하면 App 토큰 push 가 체크를 재트리거하고, 그 결과가 green 이면
auto-merge 가 진행된다 — 여기까지는 의도된 흐름이다.

문제는 **커밋백이 실패했거나 아직 안 끝난 창(window)** 이다. main 룰셋에 required
status check 가 하나도 없으므로(§0 실측, 룰셋 `20539046`) 그 창에서 stale 락이
auto-merge 로 들어갈 수 있다. 옵션 C 는 이 구멍을 **좁히지만 닫지 않는다.**

닫으려면 §0 에 적힌 aggregator 잡 선행이 필요하다(`paths:` 필터가 있는 워크플로우를
그대로 required 로 걸면 무관 PR 이 영구 대기). 이 문서 범위 밖이며, 옵션 C 의
전제조건이 아니라 **병행 과제**다.

### 9.7 롤아웃 순서

1. GitHub App 생성(대상 저장소 `contents: write` 만), 설치, `LOCK_SYNC_APP_ID` /
   `LOCK_SYNC_APP_PRIVATE_KEY` 를 **Actions** 시크릿으로 등록.
   (Dependabot 시크릿 저장소에는 **넣지 않는다** — 옵션 C 는 필요로 하지 않고, 넣으면
   9.1 이 지적한 노출 경로가 다시 열린다.)
2. `requirements-lock-commitback.yml` 추가. 모든 액션 SHA 핀(저장소 관례,
   `action-pin-verify.yml` 이 강제). 9.4 의 6개 검사를 **하나의 스텝에서 조기 종료**로
   구현하고, 각 거부 사유를 step summary 에 남긴다.
3. 인바리언트 가드 추가 — `tests/test_lock_commitback_workflow_guard.py`:
   - 트리거가 `workflow_run` 이고 `pull_request_target` 이 아닐 것
   - 9.4 의 6개 검사가 각각 존재할 것(뮤테이션으로 falsifiability 확인)
   - push 대상이 `scripts/requirements.lock` 로 한정될 것
   - App 토큰 경로를 쓸 것(`GITHUB_TOKEN` push 로 회귀하면 red)
4. 사람 PR 1건으로 9.5 의 skip 경로 실측 → step summary 에 "dependabot PR 아님" 확인.
5. 실 Dependabot PR 1건에서 end-to-end: 락이 in-place 로만 갱신(무관 drift 0),
   커밋백 후 체크가 **재실행**되는지 확인(재실행되지 않으면 3번 App 토큰 배선 오류).
6. 1주 관찰 후 `requirements-lock-sync.yml` 상단 주석의 "커밋백을 넣지 않은 이유"
   단락과 §0 표를 갱신.

### 9.8 채택하지 않을 경우의 대안

옵션 C 도 결국 App 생성·시크릿 관리·특권 워크플로우 심사라는 고정비를 만든다. 정체
비용이 그보다 작다고 판단하면 **현행 유지**가 합리적이다. 실측 정체 비용(2026-08-24):
pip 런타임 bump PR 이 락 게이트에 걸려 최대 2주 대기했고, 사람이 헬퍼를 1회 돌려
(#1183, #1203) 한 번에 해소했다 — 즉 **주 1회 수동 개입 수준**이다.

그 경우 §6.1 의 버전-동기 가드(이미 `test_requirements_lock_version_sync.py` 로 존재)가
stale 을 확정적으로 red 로 만들고, `requirements-lock-sync.yml` 의 artifact + step
summary 가 사람의 재생성 비용을 낮추는 현 구조가 그대로 최선이다. 이 문서를 남기는
목적은, 나중에 누가 옵션 A 를 구현하려 할 때 **9.1 에서 반드시 막힌다는 사실**을
먼저 읽게 하는 것이다.

### 9.9 출처

- Dependabot 트리거 시 Actions 시크릿 미제공 / read-only 토큰 —
  <https://docs.github.com/en/code-security/reference/supply-chain-security/troubleshoot-dependabot/dependabot-on-actions>
- `workflow_run` 은 이전 워크플로우가 못 받았어도 시크릿·write 토큰을 받는다 —
  <https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows>
- `GITHUB_TOKEN` push 는 워크플로우를 재트리거하지 않는다 / App 토큰·PAT 를 쓸 것 —
  <https://docs.github.com/en/actions/concepts/security/github_token>
- 두-워크플로우 분리 패턴(생산자 unprivileged + `workflow_run` 소비자) 선례 —
  <https://github.com/dependabot/dependabot-actions-workflow>
