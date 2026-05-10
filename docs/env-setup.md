# Environment Setup Guide

작성: 2026-05-09 / 적용 범위: investing-dragon 저장소 + 운영 도구 전반

이 문서는 본 저장소의 운영에 필요한 모든 환경 변수와 자격 증명을 4개 레이어로 나누어 관리하는 best practice를 정리한다. 각 키의 **목적, 저장 위치, 부재 시 동작**을 명시해 새로 합류한 개발자가 한 곳에서 전체 그림을 파악할 수 있도록 한다.

## 4 레이어 모델

| 레이어 | 위치 | 사용 시점 | 비밀 여부 |
|--------|------|----------|-----------|
| L1 프로젝트 런타임 | `<repo>/.env` (gitignored) | `python scripts/...` 로컬 실행 | 비밀 |
| L2 도구 CLI | `~/.config/<tool>/` 또는 OS keychain | `claude` / `codex` / `gemini` 직접 사용 | 비밀 |
| L3 CI 자동화 | GitHub Actions Secrets | `.github/workflows/*.yml` | 비밀 |
| L4 배포 플랫폼 | Vercel Project Environment Variables | 빌드/런타임 | 비밀 (일부 공개) |

**원칙**:
- 한 키는 한 레이어에만 둔다 (중복 금지). 예: `CMC_API_KEY`는 L1 또는 L3에만.
- 시크릿은 **절대** 평문 커밋 금지. `.env`, `~/.config/<tool>/auth.json` 모두 gitignore + chmod 600.
- 부재 시 graceful degrade가 기본. 키가 없어도 빌드/테스트는 통과해야 함.
- 키 회전 주기: 90일 (분기). 회전 후 L3/L4에 동시 갱신.

---

## L1 — 프로젝트 런타임 (`.env`)

### 위치 + 권한
```bash
# .env 는 gitignored, .env.example 만 커밋
chmod 600 .env
```

### 키 카탈로그

| 키 | 용도 | 부재 시 동작 |
|----|------|------|
| `CRYPTOPANIC_API_KEY` | crypto news 수집 | 다른 RSS로 폴백 |
| `NEWSAPI_API_KEY` | 일반 뉴스 보강 | RSS-only |
| `ALPHA_VANTAGE_API_KEY` | 주식 가격 보조 | yfinance fallback |
| `FRED_API_KEY` | 거시 지표 | 일부 카드 skip |
| `TWITTER_BEARER_TOKEN` | social_media 수집 | 모듈 전체 skip |
| `CMC_API_KEY` | CoinMarketCap | CoinGecko fallback |
| `COINGECKO_API_KEY` | CoinGecko Pro | free tier (rate-limited) |
| `FMP_API_KEY` | 주식 캘린더 | 모듈 skip |
| `SLACK_BOT_TOKEN` | Slack 운영 알림 | print-only |
| `SLACK_AI_BOT_TOKEN` | AI 멘션 응답 | 응답 비활성 |
| `SLACK_CHANNEL_*` | 채널 ID | DM 폴백 |

### 검증
```bash
python scripts/common/config.py  # 누락 키 출력 (가능하면)
python scripts/collect_crypto_news.py --dry-run
```

---

## L2 — 도구 CLI (Claude / Codex / Gemini)

### Claude Code
- **인증**: `claude login` (브라우저 OAuth, 키체인 저장)
- **확인**: `claude /doctor` 또는 `claude auth status`
- **API 직접 호출 시**: `ANTHROPIC_API_KEY` (선택, OAuth 우선)
- **위치**: macOS 키체인 (`~/.claude/credentials` 백업 가능)

### Codex (OpenAI)
- **인증**: `codex login` 또는 `OPENAI_API_KEY` 환경변수
- **권장**: 환경변수 (CI/headless에서 동일 패턴)
- **저장**: `~/.config/codex/auth.json` (chmod 600)

### Gemini CLI
- **인증**: `gemini auth login` 또는 `GEMINI_API_KEY` / `GOOGLE_API_KEY`
- **권장**: `GEMINI_API_KEY` 환경변수
- **저장**: `~/.gemini/credentials.json` (chmod 600)

### Harness (Claude Code harness mode)
- **컨텍스트**: `claude --harness` 또는 자동 감지 (CI runner)
- **환경변수**: `CLAUDE_HARNESS_MODE=true` (선택, 자동 감지가 기본)
- **로그**: `~/.claude/sessions/*.jsonl`

### 통합 셸 셋업

`~/.zshenv` 또는 `~/.config/twodragon/env.sh` (분리 권장):
```bash
# tool API keys (best practice: separate file, source from .zshrc)
export ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-}"   # 선택, OAuth 우선
export OPENAI_API_KEY="${OPENAI_API_KEY:-}"         # codex CLI 헤드리스
export GEMINI_API_KEY="${GEMINI_API_KEY:-}"         # gemini CLI 헤드리스
# 프로젝트 .env는 dotenv 라이브러리가 로드하므로 셸에 export 불필요
```

`~/.zshrc`:
```bash
# tool env (gitignored, chmod 600)
[ -f ~/.config/twodragon/env.sh ] && source ~/.config/twodragon/env.sh
```

CCG (claude-codex-gemini) 트리오케스트레이션 활용 시 3개 모두 필요. `omc ask` / `/oh-my-claudecode:ccg` 사용 가능 여부:
```bash
echo "${ANTHROPIC_API_KEY:+claude OK}" "${OPENAI_API_KEY:+codex OK}" "${GEMINI_API_KEY:+gemini OK}"
```

---

## L3 — GitHub Actions Secrets

### 현재 등록 (확인일 2026-05-09)

| Secret | 용도 워크플로우 |
|--------|----------------|
| `CMC_API_KEY` | Collect CoinMarketCap Data |
| `FMP_API_KEY` | Collect FMP Calendar |
| `FRED_API_KEY` | Collect Market Indicators |
| `SLACK_BOT_TOKEN` | 운영 알림 전반 |
| `SLACK_APP_TOKEN` | Slack Socket Mode |
| `AI_SLACK_BOT_TOKEN` | Respond AI Mentions |
| `OPENCLAW_SLACK_BOT_TOKEN` | OpenClaw Hourly Loop |
| `SLACK_CHANNEL_ID_AI` | AI 채널 라우팅 |
| `SLACK_CHANNEL_ID_OPENCLAW` | OpenClaw 채널 |

### 미등록 — 활성화 필요

| Secret | 활성화 시 효과 |
|--------|---------------|
| `GSC_SERVICE_ACCOUNT_JSON` | Google Search Console 색인 자동 감사 |
| `CRYPTOPANIC_API_KEY` | crypto news 다양성 확대 |
| `NEWSAPI_API_KEY` | 일반 뉴스 카드 |
| `TWITTER_BEARER_TOKEN` | social_media 워크플로우 활성 |
| `COINGECKO_API_KEY` | rate limit 완화 |
| `ALPHA_VANTAGE_API_KEY` | 주식 가격 보조 |

### 등록 방법
```bash
# GSC 서비스 계정 JSON 파일 → secret 등록
gh secret set GSC_SERVICE_ACCOUNT_JSON < /path/to/sa.json

# 단일 키
echo -n "$KEY" | gh secret set CRYPTOPANIC_API_KEY
```

워크플로우 전반에 자동 노출 (`secrets.GSC_SERVICE_ACCOUNT_JSON`).

---

## L4 — Vercel 배포

### 위치
Vercel Dashboard → Project → Settings → Environment Variables

### 권장 키 (Production 환경)

| 키 | 값 | 비고 |
|----|----|------|
| `JEKYLL_ENV` | `production` | `vercel.json` build에서도 export |
| `VERCEL_GIT_COMMIT_REF` | (자동) | `vercel.json` ignoreCommand에서 main 가드 |

### Vercel Bot Log
- 배포 로그는 Vercel Dashboard > Deployments > 각 배포의 Build/Function Logs
- Webhook으로 Slack 통지: Project Settings → Git → Vercel for GitHub → Notifications
- **상태**: 변경 완료 (2026-05-09 사용자 확인)

---

## Google Search Console (GSC) 활성화 절차

현재 `GSC_SERVICE_ACCOUNT_JSON` secret이 미설정 — `scripts/tools/gsc_api.py` 호출 시 graceful skip. 활성화 단계:

1. **서비스 계정 생성** (Google Cloud Console)
   - Project: `investing-dragon` (또는 기존)
   - Service Account: `gsc-reporter@<project>.iam.gserviceaccount.com`
   - Role: Search Console API 권한
   - JSON 키 다운로드

2. **Search Console에 사용자 추가**
   - https://search.google.com/search-console
   - Property: `investing.2twodragon.com`
   - Settings → Users and permissions → Add user
   - 이메일: 서비스 계정 이메일, 권한: Owner

3. **GitHub Secret 등록**
   ```bash
   gh secret set GSC_SERVICE_ACCOUNT_JSON < /path/to/sa.json
   ```

4. **자동화 워크플로우 (secret 등록 후 즉시 동작)**

   | 워크플로우 | 트리거 | 역할 |
   |-----------|--------|------|
   | `.github/workflows/gsc-index-audit.yml` | 매주 월요일 03:00 UTC + 수동 | URL 색인 상태 감사 → artifact 저장 |
   | `.github/workflows/gsc-sitemap-submit.yml` | 배포 완료 후 + 수동 | GSC에 sitemap 강제 재제출 |

   secret이 없으면 두 워크플로우 모두 graceful skip (빌드 실패 없음).

5. **첫 실행 및 결과 확인**
   ```bash
   # 수동으로 첫 실행
   gh workflow run gsc-index-audit.yml
   gh workflow run gsc-sitemap-submit.yml

   # 실행 상태 확인
   gh run list --workflow=gsc-index-audit.yml --limit 5

   # artifact 다운로드 (run-id 확인 후)
   gh run download <run-id> --name gsc-audit-<run-id>
   cat gsc-audit-output.txt
   ```

   Actions UI에서는: **Actions → GSC Index Audit → 최근 실행 → Artifacts → gsc-audit-xxx**

6. **로컬 테스트**
   ```bash
   GOOGLE_APPLICATION_CREDENTIALS=/path/to/sa.json \
     python scripts/tools/gsc_api.py submit-sitemap \
     https://investing.2twodragon.com/sitemap-index.xml --confirm
   ```

---

## 키 회전 (Rotation) Best Practice

- **주기**: 90일 (CMC, FMP, NEWSAPI 등 외부 API)
- **방식**: 발급사 콘솔에서 새 키 생성 → L1/L3/L4 동시 갱신 → 24h 모니터 → 구 키 폐기
- **자동 알람**: GitHub Dependabot은 secret 회전을 안 함. 별도 cron 또는 1Password CLI 통합 검토.

## 자가 진단 체크리스트

```bash
# L1
[ -f .env ] && [ "$(stat -f %A .env 2>/dev/null || stat -c %a .env)" = "600" ] && echo "L1 perms OK"

# L2
echo "${ANTHROPIC_API_KEY:+claude}" "${OPENAI_API_KEY:+codex}" "${GEMINI_API_KEY:+gemini}"

# L3
gh secret list

# L4
vercel env ls 2>&1 | head  # vercel CLI 로그인 필요
```

## 참고

- 본 저장소 가이드: `CLAUDE.md`, `.claude/rules/security.md`, `.claude/rules/news-collector.md`
- IndexNow + GSC 파이프라인 상세: `CLAUDE.md` § "SEO Indexing Pipeline"
- 비밀 노출 방지: `pre-commit` `gitleaks` hook (`.pre-commit-config.yaml`)
- 보안 인시던트 대응: `docs/sop-incident-response.md`
