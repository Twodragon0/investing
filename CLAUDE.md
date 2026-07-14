# Investing Dragon - Project Guide

> See `~/Desktop/personal/CLAUDE.md` for cross-repo workspace conventions (this repo's local rules take precedence inside this directory).

## Global OpenCode Precedence

- Use global OpenCode settings as the runtime baseline (`~/.config/opencode/opencode.json`, `~/.config/opencode/instructions.md`).
- This repo guide defines project workflow only and should not override global model/reasoning/default-agent defaults.

## Overview

Crypto & Stock 뉴스 수집 자동화 + 트레이딩 저널 사이트.
Jekyll(Ruby) 정적 사이트 + Python 수집 스크립트 + GitHub Actions CI/CD.

- **Live Site**: https://investing.2twodragon.com
- **Language**: Korean (ko), Timezone: Asia/Seoul
- **Theme**: minima (dark finance)

## Architecture

```
scripts/           # Python 자동화 스크립트
  common/          # 공통 모듈 18개 (config, dedup, utils, post_generator, image_generator,
                   #   crypto_api, rss_fetcher, summarizer, formatters, browser,
                   #   collector_metrics, markdown_utils, enrichment, fmp_api,
                   #   translator, worldmonitor_utils, blockchain_api, __init__)
  collect_*.py     # 뉴스 수집기 12개 (crypto, stock, social, regulatory, political,
                   #   coinmarketcap, worldmonitor, defi_llama, fmp_calendar, market_indicators,
                   #   geopolitical, blockchain)
  generate_*.py    # 요약 생성기 5개 (daily_summary, market_summary, weekly_digest,
                   #   og_images, ops_10am_digest)
  tools/           # SEO/색인 도구 (gsc_api, gsc_index_audit, indexnow_submit,
                   #   check_sitemap_local, postbuild_fix_feed_enclosures)
  respond_ai_mentions.py  # Slack 멘션 응답
_posts/            # Jekyll 포스트 (자동 생성)
_state/            # 중복 방지 상태 JSON (SHA256 해시 + fuzzy matching >80%)
_data/, _includes/, _layouts/, _sass/  # Jekyll 템플릿 및 스타일
assets/images/generated/  # 자동 생성 이미지
pages/             # 카테고리 랜딩 페이지 (개수: docs/component-counts.md)
.github/workflows/ # 자동화 워크플로우 (개수: docs/component-counts.md)
.github/actions/   # 재사용 액션 2개 (python-collect, resolve-slack-config)
```

## Key Commands

```bash
# Jekyll 로컬 실행
bundle exec jekyll serve

# Python 스크립트 실행
python scripts/collect_crypto_news.py
python scripts/generate_daily_summary.py

# 코드 품질 검사 (CI Code Quality와 동일 — lint + format. format 누락 시 CI red)
python3 -m ruff check scripts/ tests/
python3 -m ruff format --check scripts/ tests/

# OpenCode 동기화 (git pull, 중앙 관리자)
bash ~/Desktop/.twodragon0/bin/hourly-opencode-git-pull.sh

# 서버 오전 9:10 자동 포스팅/품질 보정 크론 설치
bash scripts/install_server_morning_cron.sh

# 서버 오전 9:10 자동화 수동 실행
bash scripts/server_morning_autopost.sh

# 의존성 설치
pip install -r scripts/requirements.txt
bundle install

# i18n E2E 로컬 검증 (Playwright)
pip install -r requirements-dev.txt && playwright install --with-deps chromium
bundle exec jekyll serve --port 4000          # 별도 터미널 (헬스체크 30s)
python3 -m pytest tests/i18n/ --browser chromium --no-cov -q
# 다른 포트/원격 미리보기: I18N_E2E_BASE_URL=http://127.0.0.1:4001 pytest ...

# SEO/색인 도구
python scripts/check_description_quality.py --days 7
python scripts/check_post_images.py
python scripts/tools/check_sitemap_local.py
python scripts/tools/indexnow_submit.py --from-recent-posts 30

# GSC 도구 (서비스 계정 필요)
GOOGLE_APPLICATION_CREDENTIALS=/path/to/sa.json \
  python scripts/tools/gsc_api.py submit-sitemap \
  https://investing.2twodragon.com/sitemap-index.xml --confirm

GOOGLE_APPLICATION_CREDENTIALS=/path/to/sa.json \
  python scripts/tools/gsc_index_audit.py --from-sitemap
```

## Quick Skill Cheat Sheet

> Verified 2026-05-22 against `.claude/skills/` and `~/.claude/plugins/installed_plugins.json`.

External skills (require the `superpowers` plugin — **installed v5.1.0 from `claude-plugins-official` marketplace**):
- 기본 진입: `superpowers/using-superpowers`
- 기능/구조 변경 시작: `superpowers/brainstorming` → `superpowers/writing-plans`
- 기능 구현/버그 수정: `superpowers/test-driven-development`
- 장애/원인 분석: `superpowers/systematic-debugging`
- 완료 직전 검증: `superpowers/verification-before-completion`
- 리뷰/마무리: `superpowers/requesting-code-review`, `superpowers/finishing-a-development-branch`

Repo-local skills (live in `.claude/skills/`):
- `add-data-source`, `new-collector` — 데이터 소스/수집기 추가
- `site-health-check` — 사이트 상태 점검
- `debug-workflow`, `fix-issue` — 워크플로우/이슈 디버깅
- `deep-research` — 심층 조사
- `lint-fix` — 린팅 자동 수정
- `omc-reference` — OMC 사용 가이드 (참조)

Built-in slash commands (always available):
- `/security-review` — 보안 리뷰
- `/review`, `/init`

OMC equivalents (`superpowers/*` 가 비활성/미설치일 때의 대체 매핑): brainstorming/writing-plans → `/oh-my-claudecode:plan`; systematic-debugging → `/oh-my-claudecode:debug`; verification-before-completion → `/oh-my-claudecode:verify`; requesting-code-review → `/review` or `/oh-my-claudecode:team N:code-reviewer`. 자세한 cross-repo 규약은 `~/Desktop/personal/CLAUDE.md` 참조.

## Conventions

- Python 스크립트는 `scripts/common/config.py`의 `get_env()`, `setup_logging()` 사용
- 모든 수집기는 중복 방지를 위해 `scripts/common/dedup.py` 활용
- Jekyll 포스트 형식: `_posts/YYYY-MM-DD-title.md` (front matter 필수)
- 이미지 생성: `scripts/common/image_generator.py` (Pillow 기반, 한글 렌더링 지원)
- API 타임아웃: 15초 (`REQUEST_TIMEOUT`)
- SSL 인증서: certifi 우선, `DISABLE_SSL_VERIFY` 환경변수로 비활성화 가능

## SEO Indexing Pipeline

GSC 색인 가속 + IndexNow 즉시 통지 + sitemap 강화:

```
포스트 푸시 → Vercel 빌드 → 사이트 라이브
                              ↓
              ┌───────────────┴───────────────┐
              ↓                               ↓
        IndexNow 워크플로우           Submit-sitemap 잡 (deploy-pages)
        (Bing/Yandex 즉시)         (GSC sitemap 재제출)
              ↓                               ↓
        api.indexnow.org            search.google.com/search-console
```

핵심 파일:
- `sitemap.xml` (커스텀 Liquid) — priority/changefreq/last_modified_at 티어링
- `f71a0af133e16771baeeb3c5e137d8df.txt` — IndexNow 키 검증 파일 (사이트 루트)
- `scripts/tools/indexnow_submit.py` — IndexNow CLI (4가지 URL 모드)
- `scripts/tools/gsc_api.py` — GSC URL Inspection / Search Analytics / sitemap submit
- `scripts/tools/gsc_index_audit.py` — URL 일괄 감사 + 카테고리 집계
- `scripts/tools/check_sitemap_local.py` — 로컬 sitemap 무결성 검사
- `.github/workflows/indexnow-submit.yml` — 배포 후 자동 IndexNow ping

요구 시크릿:
- `GSC_SERVICE_ACCOUNT_JSON` (선택, 미설정 시 graceful skip) — Google Cloud 서비스 계정 JSON 본문
- IndexNow 키는 공개 토큰이므로 시크릿 불필요

## Description Quality Pipeline

수집기에서 생성되는 포스트의 description 품질을 관리하는 파이프라인:

```
RSS/API → enrichment → translation → post_generator
          ↓
    1. URL 콘텐츠 추출 (og:desc → readability → bs4 → paragraph)
    2. boilerplate 필터 (_is_site_boilerplate)
    3. 제목 중복 감지 (_is_desc_duplicate_of_title)
    4. 합성 설명 생성 (팩트 기반, _synthetic 플래그)
    5. concurrent re-fetch (80개, title-dup 우선)
```

핵심 파일:
- `scripts/common/enrichment.py` — 콘텐츠 추출, boilerplate 필터, 중복 감지
- `scripts/common/rss_fetcher.py` — RSS description 추출 (1000자)
- `scripts/common/summarizer.py` — _GENERIC_DESC_PATTERNS 동기화
- `scripts/check_description_quality.py` — 포스트 품질 측정 (CI 연동)
- `scripts/fix_post_descriptions.py` — 과거 포스트 일괄 보정
- `.github/workflows/description-quality-check.yml` — 자동 품질 리포트

품질 기준:
- 목표: 실제 콘텐츠 비율 > 90%
- 경고: boilerplate > 30%
- 실패: boilerplate > 50%

명령어:
```bash
# 품질 측정
python scripts/check_description_quality.py --days 7

# 과거 포스트 보정 (dry-run)
python scripts/fix_post_descriptions.py --days 30

# 실제 적용
python scripts/fix_post_descriptions.py --days 30 --apply
```

## Environment Variables

뉴스 API (선택, 없으면 graceful degradation):
- `CRYPTOPANIC_API_KEY`, `ALPHA_VANTAGE_API_KEY`, `FRED_API_KEY`
- `TWITTER_BEARER_TOKEN`, `CMC_API_KEY`, `COINGECKO_API_KEY`
- ~~`NEWSAPI_API_KEY`~~ — DEPRECATED 2026-05-10 (코드 사용처 0건, Google News 스크래핑으로 대체)

Slack 연동:
- `SLACK_BOT_TOKEN`, `SLACK_AI_BOT_TOKEN`, `SLACK_CHANNEL_*`

## Important Notes

- `_state/*.json` 파일은 중복 방지 상태이므로 수동 수정 금지 (Claude 훅 `pre-commit-state-guard`가 커밋 시도 차단)
- 로컬 개발 시 `_state` 변경 노이즈/충돌 완화: `bash scripts/dev_ignore_state.sh` (셋업 가이드: `docs/state-friction-mitigation.md`)
- `.claude/settings.json`에 팀 공유 권한 + 5개 자동 훅 등록 (자세한 내용: `.claude/README.md`)
- `assets/images/generated/`는 30일 이상 된 이미지 자동 정리됨
- 수집기 워크플로우(`collect-*.yml`)는 각자 독립 동시성 그룹을 가짐. `collect-data` 그룹을 실제로 공유하는 건 backfill/daily-summary/weekly-report/weekly-digest 등 후속 잡뿐
- 오전 9:10(KST) 자동 포스팅/품질 보정은 서버 크론(`server_morning_autopost.sh`)이 1차 책임
- `generate-daily-summary.yml`, `generate-market-summary.yml`는 스케줄 대신 수동 실행(`workflow_dispatch`)으로 운영
- 최근 SEO/환경 작업 정리: `docs/session-2026-05-07-seo-and-environment.md`
- 검색 UX 통합 (4개 표면 / Clear·`/`·하이라이트·URL `?q=`): `docs/session-2026-05-18-search-ux-final.md`

## Continuous Improvement Loop

- `.github/workflows/continuous-improvement-loop.yml`는 매시간(`0 * * * *`) OpenClaw 기반 개선 루프를 실행
- 루프 시작 시 중앙 관리자 스크립트로 동기화 수행
- 루프는 Ralph(포스트 품질) + Ultrawork(이미지 백필) + 개선 리포트 생성을 결합
- 개선 포럼 축: 운영, 보안, 모니터링, 성능, 코드 품질, 콘텐츠 품질, UI/UX, 디자인

---

# Agent Teams Configuration

이 프로젝트에서 Agent Teams을 활용할 때 아래 역할 정의를 참고하세요.

## Team Roles

### 1. Collector Developer (수집기 개발자)
- **담당**: `scripts/collect_*.py` 및 `scripts/common/` 모듈
- **전문**: 새 데이터 소스 추가, API 연동, RSS 파싱, 중복 방지 로직
- **핵심 파일**: `scripts/common/config.py`, `scripts/common/dedup.py`, `scripts/common/rss_fetcher.py`, `scripts/common/crypto_api.py`

### 2. Frontend Developer (프론트엔드 개발자)
- **담당**: Jekyll 템플릿, 스타일, 레이아웃
- **전문**: `_layouts/`, `_includes/`, `_sass/`, `pages/`, `assets/`
- **핵심**: minima 테마 커스터마이징, 다크 테마, 반응형 디자인

### 3. Workflow Automation Engineer (워크플로우 자동화 엔지니어)
- **담당**: `.github/workflows/`, `.github/actions/`, CI/CD
- **전문**: GitHub Actions 워크플로우, 크론 스케줄링, 배포 파이프라인
- **핵심**: 동시성 그룹 관리, 타임아웃 설정, Slack 연동

### 4. Content Generator (콘텐츠 생성기)
- **담당**: `scripts/generate_*.py`, 요약 및 분석 생성
- **전문**: 일일/주간 요약, 마켓 분석, 이미지 생성
- **핵심 파일**: `scripts/common/summarizer.py`, `scripts/common/image_generator.py`, `scripts/common/formatters.py`

### 5. QA & Security Reviewer (품질/보안 리뷰어)
- **담당**: 코드 품질, 보안 취약점, 의존성 검사
- **전문**: ruff 린팅, pip-audit, API 키 노출 방지, OWASP 검사
- **핵심**: `.github/workflows/code-quality.yml`, `.github/workflows/dependency-check.yml`

### 6. Architect (시스템 아키텍트)
- **담당**: 수집 파이프라인 설계, Jekyll 통합, 워크플로우 자동화 아키텍처
- **전문**: 11개 수집기 데이터 흐름, `scripts/common/` 모듈 설계, GitHub Actions 구조
- **핵심 파일**: `scripts/common/config.py`, `scripts/common/dedup.py`

### 7. Test Engineer (테스트 엔지니어)
- **담당**: 수집기 테스트, dedup 검증, Jekyll 빌드 유효성
- **전문**: pytest, API 모킹, 한국어 텍스트 처리 테스트, 멱등성 검증
- **핵심**: `scripts/` 모듈 단위 테스트

### Agent Responsibilities

| Agent | Primary Files | Key Tools |
|-------|--------------|-----------|
| `investing-lead` | All — coordination role | Read, Grep, Glob, Bash, Agent |
| `architect` | scripts/common/config.py, scripts/common/dedup.py | Read, Grep, Glob, Bash |
| `data-pipeline-lead` | scripts/collect_*.py, scripts/common/ | Read, Grep, Glob, Bash |
| `collector-reviewer` | scripts/collect_*.py, scripts/common/ | Read, Grep, Glob, Bash |
| `content-pipeline` | scripts/generate_*.py, scripts/common/summarizer.py | Read, Grep, Glob, Bash, Edit, Write |
| `workflow-optimizer` | .github/workflows/, .github/actions/ | Read, Grep, Glob, Bash, Edit, Write |
| `workflow-debugger` | .github/workflows/ | Read, Grep, Glob, Bash |
| `jekyll-checker` | _layouts/, _includes/, _sass/, pages/ | Read, Grep, Glob, Bash |
| `test-engineer` | scripts/ unit tests | Read, Write, Edit, Bash, Grep, Glob |

## Multi-Agent Workflow Patterns

#### New Data Source Addition
```
1. investing-lead    → 데이터 소스 분석 및 영향 평가
2. Parallel:
   - data-pipeline-lead → collect_*.py 구현
   - workflow-optimizer  → GitHub Actions 워크플로우 추가
   - test-engineer       → 테스트 작성 (TDD)
3. collector-reviewer    → 코드 리뷰 및 중복 방지 검증
4. architect             → 아키텍처 적합성 확인
```

#### Daily Summary Pipeline
```
1. content-pipeline   → generate_daily_summary.py 수정
2. jekyll-checker      → 포스트 템플릿 검증
3. test-engineer       → 요약 출력 검증
4. workflow-optimizer  → 워크플로우 스케줄 조정
```

#### Site Redesign
```
1. architect           → 레이아웃 구조 설계
2. Parallel:
   - jekyll-checker    → 템플릿/스타일 구현
   - content-pipeline  → 포스트 템플릿 업데이트
3. test-engineer       → 반응형/접근성 검증
```

#### Bug Investigation
```
1. workflow-debugger   → CI/워크플로우 로그 분석
2. data-pipeline-lead  → 수집기 데이터 흐름 추적
3. test-engineer       → 재현 테스트 작성
4. investing-lead      → 근본 원인 판정 및 수정 지시
```

## Team Rules

1. **파일 충돌 방지**: 각 팀원은 담당 디렉토리만 수정
2. **Plan approval**: 구조 변경 시 리드에게 계획 승인 요청
3. **한국어 우선**: 커밋 메시지와 주석은 한국어 사용
4. **테스트**: 스크립트 변경 시 `python3 -m ruff check scripts/ tests/` 린팅 + `python3 -m ruff format --check scripts/ tests/` 포맷 확인 (pre-commit 훅이 자동 적용)
5. **상태 파일 보호**: `_state/*.json` 직접 수정 금지
