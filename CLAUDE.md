# Investing Dragon - Project Guide

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
  common/          # 공통 모듈 17개 (config, dedup, utils, post_generator, image_generator,
                   #   crypto_api, rss_fetcher, summarizer, formatters, browser,
                   #   collector_metrics, markdown_utils, enrichment, fmp_api,
                   #   translator, worldmonitor_utils, __init__)
  collect_*.py     # 뉴스 수집기 11개 (crypto, stock, social, regulatory, political,
                   #   coinmarketcap, worldmonitor, defi_llama, fmp_calendar, market_indicators,
                   #   geopolitical)
  generate_*.py    # 요약 생성기 5개 (daily_summary, market_summary, weekly_digest,
                   #   og_images, ops_10am_digest)
  respond_ai_mentions.py  # Slack 멘션 응답
_posts/            # Jekyll 포스트 (자동 생성)
_state/            # 중복 방지 상태 JSON (SHA256 해시 + fuzzy matching >80%)
_data/, _includes/, _layouts/, _sass/  # Jekyll 템플릿 및 스타일
assets/images/generated/  # 자동 생성 이미지
pages/             # 카테고리 랜딩 페이지 9개
.github/workflows/ # 25개 자동화 워크플로우
.github/actions/   # 재사용 액션 2개 (python-collect, resolve-slack-config)
```

## Key Commands

```bash
# Jekyll 로컬 실행
bundle exec jekyll serve

# Python 스크립트 실행
python scripts/collect_crypto_news.py
python scripts/generate_daily_summary.py

# 코드 품질 검사
python3 -m ruff check scripts/

# OpenCode 동기화 (git pull, 중앙 관리자)
bash ~/Desktop/.twodragon0/bin/hourly-opencode-git-pull.sh

# 서버 오전 9:10 자동 포스팅/품질 보정 크론 설치
bash scripts/install_server_morning_cron.sh

# 서버 오전 9:10 자동화 수동 실행
bash scripts/server_morning_autopost.sh

# 의존성 설치
pip install -r scripts/requirements.txt
bundle install
```

## Quick Skill Cheat Sheet

- 기본 진입: `superpowers/using-superpowers`
- 기능/구조 변경 시작: `superpowers/brainstorming` -> `superpowers/writing-plans`
- 기능 구현/버그 수정: `superpowers/test-driven-development`
- 장애/원인 분석: `superpowers/systematic-debugging`
- 완료 직전 검증: `superpowers/verification-before-completion`
- 리뷰/마무리: `superpowers/requesting-code-review`, `superpowers/finishing-a-development-branch`
- 저장소 전용: `site-health-check`, `security-review`, `post-validation`, `cost-audit`, `debug-workflow`, `add-data-source`, `new-collector`, `fix-issue`, `deep-research`

## Conventions

- Python 스크립트는 `scripts/common/config.py`의 `get_env()`, `setup_logging()` 사용
- 모든 수집기는 중복 방지를 위해 `scripts/common/dedup.py` 활용
- Jekyll 포스트 형식: `_posts/YYYY-MM-DD-title.md` (front matter 필수)
- 이미지 생성: `scripts/common/image_generator.py` (Pillow 기반, 한글 렌더링 지원)
- API 타임아웃: 15초 (`REQUEST_TIMEOUT`)
- SSL 인증서: certifi 우선, `DISABLE_SSL_VERIFY` 환경변수로 비활성화 가능

## Environment Variables

뉴스 API (선택, 없으면 graceful degradation):
- `CRYPTOPANIC_API_KEY`, `NEWSAPI_API_KEY`, `ALPHA_VANTAGE_API_KEY`, `FRED_API_KEY`
- `TWITTER_BEARER_TOKEN`, `CMC_API_KEY`, `COINGECKO_API_KEY`

Slack 연동:
- `SLACK_BOT_TOKEN`, `SLACK_AI_BOT_TOKEN`, `SLACK_CHANNEL_*`

## Important Notes

- `_state/*.json` 파일은 중복 방지 상태이므로 수동 수정 금지
- `assets/images/generated/`는 30일 이상 된 이미지 자동 정리됨
- GitHub Actions는 동시성 그룹(`collect-data`)으로 순차 실행
- 오전 9:10(KST) 자동 포스팅/품질 보정은 서버 크론(`server_morning_autopost.sh`)이 1차 책임
- `generate-daily-summary.yml`, `generate-market-summary.yml`는 스케줄 대신 수동 실행(`workflow_dispatch`)으로 운영

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
4. **테스트**: 스크립트 변경 시 `python3 -m ruff check scripts/`로 린팅 확인
5. **상태 파일 보호**: `_state/*.json` 직접 수정 금지
