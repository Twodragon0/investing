# requirements.lock 자동 동기 PR 파이프라인 — 설계 (#2 원안)

> 상태: **설계 (미구현)** · 작성 2026-06-24 · 대상 `scripts/requirements.txt` ↔ `scripts/requirements.lock`
> 선행 컨텍스트: `supply-chain-lock.yml`, `tests/test_requirements_lock_coverage.py`,
> `scripts/refresh_requirements_lock.sh`, `.github/dependabot.yml`, `.github/workflows/dependabot-auto-merge.yml`

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
