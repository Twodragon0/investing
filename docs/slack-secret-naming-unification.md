# Slack Secret Naming Unification + `resolve-slack-config` 단순화

> Status: **Design v2 (review-incorporated, pre-implementation)**
> Owner: investing platform
> Last updated: 2026-06-01
> Review: 2 reviewers, REQUEST CHANGES (3 BLOCKER, 6 MAJOR, 4 MINOR resolved)

## 0. v2 변경 요약

v1 설계를 두 명의 reviewer 가 검토한 결과, **이론적 매트릭스 ≠ 실제 등록 상태**임이 실측 audit (`scripts/migrate_slack_naming.sh --phase=0`)로 드러났다. 이 문서는 그 결과를 반영한 v2이다.

| 변경 | 사유 |
|---|---|
| § 2.2 카탈로그를 실측치로 교체 | 워크플로우 YAML 의 fallback 후보 ≠ 실제 등록된 secret. 실측 결과 채널 legacy 22개는 미등록 |
| § 4 매핑표 단순화 | 미등록 entry 폐기 단계 불필요 → token rename 2건 + canonical 7개 추가만 남음 |
| § 5 action v2 안전성 보강 | `set -u` × `${!var}` BLOCKER, `bot` 화이트리스트 fail-loud, 출력 계약 명시 |
| § 5.3 compat-legacy 모드 제거 | 채널 legacy 가 미등록이므로 fallback 자체 불필요. § 6 Phase 2 env 매핑 모순 해소 |
| § 6 Phase 0.5 Vault snapshot 추가 | Phase 4 destructive 작업의 롤백 가능성 확보 |
| § 6 Phase 1 overwrite 차단 명시 | 기존 `SLACK_CHANNEL_ID` 등을 실수로 덮어쓰는 사고 방지 |
| § 6 Phase 2 atomicity 개선 | action.yml 을 additive 로 변경(구/신 input 모두 수락) → 17 워크플로우 점진 마이그레이션 |
| § 8 Reusable workflow 승격 | 후속 PR 후보 → primary 권장. composite 보다 보일러플레이트 1/4로 축소 |

## 1. 문제

GitHub Actions 워크플로우 17개가 Slack 으로 알림을 보내기 위해 `resolve-slack-config` composite action 을 호출한다. 현재 호출 패턴은 다음 두 문제를 일으킨다:

1. **워크플로우 YAML 보일러플레이트 폭증**: 각 alias 별로 `SLACK_CHANNEL_ID_<X>`, `OPENCLAW_SLACK_CHANNEL_ID_<X>`, `AI_SLACK_CHANNEL_ID_<X>`, `SLACK_CHANNEL_<X>` 4개의 후보를 모두 매핑. 호출 1회당 약 30라인.
2. **운영자 멘탈 모델 혼란**: 봇별 토큰 분리(`SLACK_BOT_TOKEN` vs `AI_SLACK_BOT_TOKEN` vs `OPENCLAW_SLACK_BOT_TOKEN`)와 채널 prefix 가 섞여, 어느 secret 을 등록해야 하는지 불명확. 실측 결과 OPENCLAW_/AI_ prefix 채널 secret 은 **단 1건도 등록되지 않은 상태**로 운영되고 있었음.

## 2. 현 상태 카탈로그 (실측)

### 2.1. 토큰 (실제 등록 4개)

| 이름 | 상태 | 비고 |
|---|---|---|
| `SLACK_BOT_TOKEN` | **등록됨** (canonical) | 주 봇. 이대로 유지 |
| `AI_SLACK_BOT_TOKEN` | **등록됨** (legacy) | → `SLACK_AI_BOT_TOKEN` 으로 rename |
| `OPENCLAW_SLACK_BOT_TOKEN` | **등록됨** (legacy) | → `SLACK_OPENCLAW_BOT_TOKEN` 으로 rename |
| `SLACK_TOKEN` | 미등록 | 일부 워크플로우 token_candidates 마지막 fallback. 폐기 |

### 2.2. 채널 (실제 등록 2개 / 워크플로우 YAML 참조 28개)

`scripts/migrate_slack_naming.sh --phase=0` 실측 결과 (2026-06-01 01:04 UTC):

```
Canonical present (3/10):
  - SLACK_BOT_TOKEN  (위에서 분류)
  - SLACK_CHANNEL_ID_OPENCLAW
  - SLACK_CHANNEL_ID_AI

Canonical missing (need Phase 1):
  - SLACK_AI_BOT_TOKEN
  - SLACK_OPENCLAW_BOT_TOKEN
  - SLACK_CHANNEL_ID
  - SLACK_CHANNEL_ID_OPS
  - SLACK_CHANNEL_ID_DEV
  - SLACK_CHANNEL_ID_SECURITY
  - SLACK_CHANNEL_ID_INVESTING

Legacy present (Phase 4 deletion candidates, 2 total):
  - AI_SLACK_BOT_TOKEN
  - OPENCLAW_SLACK_BOT_TOKEN

Legacy absent (워크플로우 YAML에만 fallback 으로 등장, 실제 미등록 22개):
  - OPENCLAW_SLACK_CHANNEL_ID(_OPS,_DEV,_SECURITY,_OPENCLAW,_AI,_INVESTING)  ×7
  - AI_SLACK_CHANNEL_ID(_OPS,_DEV,_SECURITY,_OPENCLAW,_AI,_INVESTING)        ×7
  - SLACK_CHANNEL(_OPS,_DEV,_SECURITY,_OPENCLAW,_AI,_INVESTING)              ×7
  - SLACK_TOKEN                                                              ×1
```

### 2.3. 워크플로우 사용처 (17개)

`alert-consecutive-failures.yml`, `classify-workflow-failures.yml`, `cleanup-old-images.yml`, `collect-defi-llama.yml`, `collect-defi-yields.yml`, `collector-heartbeat.yml`, `continuous-improvement-loop.yml`, `generate-daily-summary.yml`, `generate-market-summary.yml`, `generate-weekly-report.yml`, `notify-deploy-status.yml`, `ops-10am-digest.yml`, `push-folder-info-to-slack.yml`, `respond-ai-mentions.yml`, `site-health-check.yml`, `watchdog-zero-job-runs.yml`, `weekly-digest.yml`

스크립트 측: `scripts/respond_ai_mentions.py:174-211` 도 동일한 fallback 체인을 갖는다.

### 2.4. 중요 발견

**워크플로우 YAML 의 `channel_candidates_*` 목록 대부분이 dead code 였다.** v1 설계가 가정한 "31개 secret 중 23개 폐기" 는 잘못된 전제였고, 실제로는 token 2개만 rename·삭제하고 channel canonical 5~7개를 추가 등록하면 끝난다.

## 3. 설계 원칙

1. **토큰은 봇별, 채널은 alias별** — 두 축 분리. 채널 ID 는 모든 봇 공유.
2. **채널 ID 만 사용** — `SLACK_CHANNEL_*` (이름) 표기 폐기. ID 는 rename 내성.
3. **alias 화이트리스트** — `ops | dev | security | openclaw | ai | investing | default`. 미일치 → `default`.
4. **bot 화이트리스트 fail-loud** — `default | ai | openclaw` 외 입력 시 step 실패 (Reviewer B MINOR).
5. **channel ID 미마스킹 명시** — Slack 모델상 공개 식별자. 토큰만 `::add-mask::` (Reviewer B MAJOR).
6. **action 은 additive 마이그레이션** — 구/신 input 모두 수락하다가 Phase 4 에서 구 input 제거 (Reviewer A MAJOR, Reviewer B MAJOR).

## 4. Canonical 네이밍

### 4.1. 최종 secret 세트 (총 10개)

**토큰 (3):**
| Canonical | v1 → v2 변경 |
|---|---|
| `SLACK_BOT_TOKEN` | 동일 (이미 등록) |
| `SLACK_AI_BOT_TOKEN` | `AI_SLACK_BOT_TOKEN` 에서 rename (값 동일하게 복사) |
| `SLACK_OPENCLAW_BOT_TOKEN` | `OPENCLAW_SLACK_BOT_TOKEN` 에서 rename |

**채널 ID (7):**
| Canonical | 현재 상태 | 의미 |
|---|---|---|
| `SLACK_CHANNEL_ID` | 미등록 | default — alias 미지정 시 사용 |
| `SLACK_CHANNEL_ID_OPS` | 미등록 | 운영 |
| `SLACK_CHANNEL_ID_DEV` | 미등록 | 개발 |
| `SLACK_CHANNEL_ID_SECURITY` | 미등록 | 보안 |
| `SLACK_CHANNEL_ID_OPENCLAW` | **등록됨** | OpenClaw 루프 결과 |
| `SLACK_CHANNEL_ID_AI` | **등록됨** | AI 답변 |
| `SLACK_CHANNEL_ID_INVESTING` | 미등록 | 수집/포스트 결과 |

### 4.2. 실제 작업 부피 (Phase 별)

| Phase | 작업 | 부피 |
|---|---|---|
| 1 | canonical 등록 (missing 7개) | gh secret set ×7 |
| 4 | legacy 삭제 (실제 등록된 2 토큰만) | gh secret delete ×2 |
| 2 | action.yml additive 갱신 + 17 워크플로우 YAML 의 dead fallback 제거 | YAML diff |
| 3 | `scripts/respond_ai_mentions.py` fallback 체인 단순화 | python diff |

v1 의 "23개 삭제" 는 잘못된 추정. 실제 destructive 작업은 **legacy token 2건 삭제** 뿐.

## 5. `resolve-slack-config` v2

### 5.1. 인터페이스 (additive 마이그레이션)

v2 action.yml 은 **구 input 과 신 input 을 모두 수락**한다. 우선순위: 신 → 구.

**신 인터페이스 (권장):**
```yaml
- uses: ./.github/actions/resolve-slack-config
  id: slack
  with:
    target_channel_alias: ops
    bot: default            # default | ai | openclaw
  env:
    SLACK_BOT_TOKEN:            ${{ secrets.SLACK_BOT_TOKEN }}
    SLACK_AI_BOT_TOKEN:         ${{ secrets.SLACK_AI_BOT_TOKEN }}
    SLACK_OPENCLAW_BOT_TOKEN:   ${{ secrets.SLACK_OPENCLAW_BOT_TOKEN }}
    SLACK_CHANNEL_ID:           ${{ secrets.SLACK_CHANNEL_ID }}
    SLACK_CHANNEL_ID_OPS:       ${{ secrets.SLACK_CHANNEL_ID_OPS }}
    SLACK_CHANNEL_ID_DEV:       ${{ secrets.SLACK_CHANNEL_ID_DEV }}
    SLACK_CHANNEL_ID_SECURITY:  ${{ secrets.SLACK_CHANNEL_ID_SECURITY }}
    SLACK_CHANNEL_ID_OPENCLAW:  ${{ secrets.SLACK_CHANNEL_ID_OPENCLAW }}
    SLACK_CHANNEL_ID_AI:        ${{ secrets.SLACK_CHANNEL_ID_AI }}
    SLACK_CHANNEL_ID_INVESTING: ${{ secrets.SLACK_CHANNEL_ID_INVESTING }}
```

**구 인터페이스 (Phase 4 까지 호환):**
v1 의 `token_candidates`, `channel_candidates_*` 6개를 그대로 수락. 신 input 이 비어있을 때만 구 input 으로 fallback.

### 5.2. 출력 계약 (변경 없음)

| Output | 의미 |
|---|---|
| `can_post` | `"true"` / `"false"` |
| `token` | resolved bot token (`::add-mask::` 처리됨) |
| `channel` | resolved channel ID (Slack 모델상 공개 식별자 — **의도적으로 마스킹 안 함**) |
| `alias` | normalized alias (입력 검증 통과 후 lowercase) |
| `profile_label` | `${alias}-agent` 형식 |

> 보안 노트: `token` 은 `$GITHUB_OUTPUT` 으로 전달되며 GHA 가 후속 step 로그에서도 마스킹한다. 다만 `actions: read` 권한 보유자가 step output API 로 조회 가능하므로, 외부 워크플로우 공유 시 주의.

### 5.3. 액션 내부 로직 (set -u 안전 패턴)

Reviewer B BLOCKER 해결: 직접 변수 indirect expansion 대신 `case` + 명시적 변수 이름 사용.

```bash
set -euo pipefail

# 1) bot → token 변수 선택 (case 화이트리스트, 미일치 시 fail-loud)
case "${INPUT_BOT:-default}" in
  default)  token="${SLACK_BOT_TOKEN:-}" ;;
  ai)       token="${SLACK_AI_BOT_TOKEN:-}" ;;
  openclaw) token="${SLACK_OPENCLAW_BOT_TOKEN:-}" ;;
  *)
    echo "::error::unknown bot=${INPUT_BOT}; allowed: default|ai|openclaw"
    exit 1
    ;;
esac

# 2) alias → channel 변수 선택 (case 화이트리스트, 미일치 시 default)
alias_lc="$(printf '%s' "${INPUT_TARGET_ALIAS:-investing}" | tr '[:upper:]' '[:lower:]')"
case "$alias_lc" in
  ops)        channel="${SLACK_CHANNEL_ID_OPS:-}" ;;
  dev)        channel="${SLACK_CHANNEL_ID_DEV:-}" ;;
  security)   channel="${SLACK_CHANNEL_ID_SECURITY:-}" ;;
  openclaw)   channel="${SLACK_CHANNEL_ID_OPENCLAW:-}" ;;
  ai)         channel="${SLACK_CHANNEL_ID_AI:-}" ;;
  investing)  channel="${SLACK_CHANNEL_ID_INVESTING:-}" ;;
  *)          alias_lc="default"; channel="" ;;
esac

# 3) channel default fallback
if [ -z "$channel" ]; then
  channel="${SLACK_CHANNEL_ID:-}"
fi

# 4) 구 인터페이스 fallback (Phase 2~4 호환 기간)
if [ -z "$token" ] && [ -n "${INPUT_TOKEN_CANDIDATES:-}" ]; then
  token="$(printf '%s\n' "$INPUT_TOKEN_CANDIDATES" | first_non_empty || printf '')"
fi
if [ -z "$channel" ]; then
  # 구 채널 후보 → 신 변수에 정렬된 input 으로만 fallback (compat-legacy)
  case "$alias_lc" in
    ops)        legacy="${INPUT_CHANNEL_OPS:-}" ;;
    dev)        legacy="${INPUT_CHANNEL_DEV:-}" ;;
    security)   legacy="${INPUT_CHANNEL_SECURITY:-}" ;;
    openclaw)   legacy="${INPUT_CHANNEL_OPENCLAW:-}" ;;
    investing)  legacy="${INPUT_CHANNEL_INVESTING:-}" ;;
    *)          legacy="" ;;
  esac
  [ -z "$legacy" ] && legacy="${INPUT_CHANNEL_DEFAULT:-}"
  if [ -n "$legacy" ]; then
    channel="$(printf '%s\n' "$legacy" | first_non_empty || printf '')"
  fi
fi

# 5) whitespace trim 보존 (v1 hardening — Reviewer B MINOR)
token="$(printf '%s' "$token" | xargs || printf '')"
channel="$(printf '%s' "$channel" | xargs || printf '')"

can_post="true"
[ -z "$token" ] || [ -z "$channel" ] && can_post="false"
[ -n "$token" ] && echo "::add-mask::$token"

{
  echo "can_post=$can_post"
  echo "token=$token"
  echo "channel=$channel"
  echo "alias=$alias_lc"
  echo "profile_label=${alias_lc}-agent"
} >> "$GITHUB_OUTPUT"
```

핵심:
- `case` 화이트리스트로 변수 이름을 명시 → `set -u` 위반 없음.
- bot 입력은 fail-loud, alias 입력은 default fallback (v1 동작 호환).
- 구 인터페이스 (`INPUT_CHANNEL_OPS` 등 v1 input) 도 동일 case 로 매핑 → compat env 매핑 모순 해소.

### 5.4. Reusable Workflow 대안 (권장 후속)

Composite action 은 `secrets:` 키워드 불가 → 매 caller 가 12라인 env 매핑 반복. Reusable workflow (`workflow_call`) 는 `secrets: inherit` 로 caller 측 보일러플레이트를 1라인으로 축소한다.

```yaml
# .github/workflows/_post-to-slack.yml
on:
  workflow_call:
    inputs:
      alias:   { type: string, required: true }
      bot:     { type: string, default: default }
      message: { type: string, required: true }
    secrets: inherit
jobs:
  post:
    runs-on: ubuntu-latest
    steps:
      - uses: ./.github/actions/resolve-slack-config
        with:
          target_channel_alias: ${{ inputs.alias }}
          bot: ${{ inputs.bot }}
        env:
          # 12라인 env 매핑 (이 reusable workflow 안에서만 1회 정의)
          ...
      - uses: slackapi/slack-github-action@...
        if: steps.slack.outputs.can_post == 'true'
        with:
          method: chat.postMessage
          token: ${{ steps.slack.outputs.token }}
          payload: |
            channel: "${{ steps.slack.outputs.channel }}"
            text: "${{ inputs.message }}"
```

caller (예: `collect-defi-llama.yml`):
```yaml
post-slack:
  needs: collect
  uses: ./.github/workflows/_post-to-slack.yml
  with:
    alias: investing
    message: "[investing-agent] DeFi Llama collection completed - ${{ github.run_id }}"
  secrets: inherit
```

→ caller 당 ~30라인 → ~6라인. 별도 PR 로 진행 권장 (§ 8).

## 6. 마이그레이션 절차 (실측 기반 v2)

### Phase 0 — Audit (자동화 완료)

```bash
scripts/migrate_slack_naming.sh --phase=0
```

산출: canonical present/missing, legacy present/absent 카운트. 본 문서 § 2.2 의 데이터 출처.

### Phase 0.5 — Vault Snapshot (필수 게이트)

Phase 4 destructive 작업의 롤백 가능성 확보. 다음 2개 토큰 값을 1Password / Bitwarden / SOPS 등에 명명 entry 로 백업:

- `gh-investing-AI_SLACK_BOT_TOKEN`
- `gh-investing-OPENCLAW_SLACK_BOT_TOKEN`

검증: 1건은 실제 restore 테스트 (vault → 새 GH secret 등록 → 1분 후 삭제) 후 진행. 스냅샷 경로는 별도 runbook(commit-safe, 값 미포함) 에 기록.

### Phase 1 — Canonical 등록 (additive, 7건)

```bash
scripts/migrate_slack_naming.sh --phase=1            # dry-run 검토
scripts/migrate_slack_naming.sh --phase=1 --apply    # 값 입력 7회 (read -s)
```

안전 동작:
- 기본 dry-run, `--apply` 명시 시에만 실행.
- 이미 존재하는 canonical (`SLACK_CHANNEL_ID_OPENCLAW`, `SLACK_CHANNEL_ID_AI`) 은 **자동 skip**. `--force-overwrite` 미사용 시 덮어쓰기 없음.
- `printf '%s' "$v" | gh secret set NAME --body -` → 값 word-splitting 방지.
- 공백 trim 후 빈 문자열은 skip.

값 확정 작업: `SLACK_AI_BOT_TOKEN` / `SLACK_OPENCLAW_BOT_TOKEN` 은 기존 `AI_SLACK_BOT_TOKEN` / `OPENCLAW_SLACK_BOT_TOKEN` 값과 동일하게 복사. 채널 ID 5건은 운영자가 Slack 채널 카탈로그와 1회 매핑.

검증: `scripts/migrate_slack_naming.sh --phase=0` → `Canonical present: 10/10`.

### Phase 2 — `resolve-slack-config` v2 + 17 워크플로우 점진 갱신

PR 1 (action 만):
- `.github/actions/resolve-slack-config/action.yml` 를 § 5.3 의 additive 로직으로 교체.
- 구 input (`channel_candidates_*`, `token_candidates`) 은 `required: false` 로 유지하여 17 caller 가 그대로 동작.
- merge 후 모든 워크플로우 1회 dispatch → can_post=true 비율이 baseline 유지 확인.

PR 2~N (워크플로우 갱신):
- 1 PR 당 1~3 워크플로우씩 신 인터페이스 (`bot:` + env 블록) 로 전환.
- `respond-ai-mentions.yml` 부터 시작 (가장 복잡한 caller). 30분 모니터링 후 다음 PR.

### Phase 3 — 스크립트 동기화

`scripts/respond_ai_mentions.py:174-211` 의 `channel_id_for_alias()` 를 단순화:

```python
def channel_id_for_alias(alias: str) -> str:
    upper = alias.upper()
    if upper in {"OPS", "DEV", "SECURITY", "OPENCLAW", "AI", "INVESTING"}:
        return env_first(f"SLACK_CHANNEL_ID_{upper}", "SLACK_CHANNEL_ID")
    return os.getenv("SLACK_CHANNEL_ID", "")
```

기존 fallback `openclaw → AI → default` 의 의미를 보존해야 한다면 (Reviewer A MINOR), Phase 1 에서 `SLACK_CHANNEL_ID_OPENCLAW` 가 이미 등록되어 있음을 audit 으로 확인했으므로 직접 lookup 이 안전.

### Phase 4 — Legacy 삭제 (D+7, vault snapshot 검증 후)

```bash
scripts/migrate_slack_naming.sh --phase=4 \
  --vault=/path/to/vault-snapshot.txt \
  --apply
```

안전 동작:
- `--vault=PATH` 필수, 파일 존재 + 비어있지 않음 검증.
- 실행 직전 repo 이름 정확 입력 confirm.
- 멱등 삭제 (`|| true` 패턴) — 미등록 entry 무시.

실제 삭제 대상 (실측 기반): `AI_SLACK_BOT_TOKEN`, `OPENCLAW_SLACK_BOT_TOKEN` (legacy channel 22개는 미등록이므로 noop).

또한 action.yml 의 구 input 도 동시 제거 PR 가능.

### 롤백

- Phase 2: action.yml 만 git revert. 신 canonical secret 보존.
- Phase 4: vault snapshot 에서 `gh secret set` 재등록. action.yml 의 구 input 복원 PR.

## 7. 영향 분석

| 항목 | Before | After (Phase 4 완료) | After (+reusable workflow) |
|---|---|---|---|
| 등록된 secret 수 | 5 (canonical 3 + legacy 2) | 10 (canonical 10) | 10 |
| 워크플로우당 Slack 보일러플레이트 | ~30라인 | ~12라인 | ~6라인 |
| 신규 워크플로우 추가 시 결정 | 4 prefix × alias 후보 12개 | bot 1 + alias 1 = 2 | bot 1 + alias 1 = 2 |
| dead fallback (YAML 참조하나 미등록) | 22개 | 0 | 0 |

## 8. 오픈 이슈 / 후속

1. **Reusable workflow `_post-to-slack.yml` 추출** — Reviewer B MAJOR 권고. caller 보일러플레이트를 1/4로 축소. § 5.4 초안 기반으로 별도 PR.
2. **org-level secret 충돌 audit** — `gh api orgs/<org>/actions/secrets` (권한 시) → canonical 10개 이름이 org 레벨에서 다른 값으로 정의되어 있지 않은지 확인 (Reviewer A LOW).
3. **외부 스크립트 의존성** — `~/Desktop/.twodragon0/` 중앙 관리 스크립트가 동일 secret 명을 참조할 수 있음. 별도 검토.
4. **`SLACK_TOKEN` (deprecated) workflow 참조 정리** — `collect-defi-llama.yml:43` 등에서 fallback 으로 등장. Phase 2 워크플로우 갱신 시 제거.

## 9. 실행 체크리스트

- [x] Phase 0: audit 자동화 (`scripts/migrate_slack_naming.sh --phase=0`)
- [ ] Phase 0.5: 2개 legacy 토큰 vault snapshot + restore 테스트
- [ ] Phase 1: canonical 7개 등록 (`--phase=1 --apply`)
- [ ] Phase 2 (PR 1): action.yml v2 additive 배포
- [ ] Phase 2 (PR 2~N): 17 워크플로우 점진 갱신, `respond-ai-mentions.yml` 부터 canary
- [ ] Phase 3: `scripts/respond_ai_mentions.py` 단순화
- [ ] Phase 4 (D+7): legacy 토큰 2건 삭제 + action.yml 구 input 제거 PR
- [ ] (선택) Reusable workflow `_post-to-slack.yml` 별도 PR
- [ ] 회귀 모니터링 1주: Slack post 성공률 ≥ 직전 7일 baseline
