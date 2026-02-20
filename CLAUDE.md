# Investing Dragon - Project Guide

## Overview

Crypto & Stock 뉴스 수집 자동화 + 트레이딩 저널 사이트.
Jekyll(Ruby) 정적 사이트 + Python 수집 스크립트 + GitHub Actions CI/CD.

- **Live Site**: https://investing.2twodragon.com
- **Language**: Korean (ko), Timezone: Asia/Seoul
- **Theme**: minima (dark finance)

## Architecture

```
scripts/           # Python 자동화 스크립트
  common/          # 공통 모듈 13개 (config, dedup, utils, post_generator, image_generator,
                   #   crypto_api, rss_fetcher, summarizer, formatters, browser,
                   #   collector_metrics, markdown_utils, __init__)
  collect_*.py     # 뉴스 수집기 8개 (crypto, stock, social, regulatory, political,
                   #   coinmarketcap, worldmonitor, defi_llama)
  generate_*.py    # 요약 생성기 3개 (daily_summary, market_summary, weekly_digest)
  respond_ai_mentions.py  # Slack 멘션 응답
_posts/            # Jekyll 포스트 (자동 생성)
_state/            # 중복 방지 상태 JSON (SHA256 해시 + fuzzy matching >80%)
_data/, _includes/, _layouts/, _sass/  # Jekyll 템플릿 및 스타일
assets/images/generated/  # 자동 생성 이미지
pages/             # 카테고리 랜딩 페이지 9개
.github/workflows/ # 20개 자동화 워크플로우
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

# 의존성 설치
pip install -r scripts/requirements.txt
bundle install
```

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

### 3. DevOps Engineer (DevOps 엔지니어)
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

## Team Usage Examples

### 새 데이터 소스 추가
```
Create an agent team for adding a new data source:
- Collector Developer: scripts/collect_new_source.py 구현
- DevOps Engineer: .github/workflows/ 워크플로우 추가
- QA Reviewer: 코드 리뷰 및 보안 검사
각 팀원이 독립적으로 작업 후 통합하세요.
```

### 사이트 리디자인
```
Create an agent team for site redesign:
- Frontend Developer: 레이아웃과 스타일 수정
- Content Generator: 새 레이아웃에 맞는 포스트 템플릿 업데이트
- QA Reviewer: 반응형 디자인 및 접근성 검증
```

### 버그 조사
```
Create an agent team to investigate the bug:
- 3명의 팀원이 서로 다른 가설을 검증
- 서로의 이론을 반박하며 근본 원인을 찾으세요
```

## Team Rules

1. **파일 충돌 방지**: 각 팀원은 담당 디렉토리만 수정
2. **Plan approval**: 구조 변경 시 리드에게 계획 승인 요청
3. **한국어 우선**: 커밋 메시지와 주석은 한국어 사용
4. **테스트**: 스크립트 변경 시 `python3 -m ruff check scripts/`로 린팅 확인
5. **상태 파일 보호**: `_state/*.json` 직접 수정 금지
