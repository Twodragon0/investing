# Investing Dragon

Crypto & Stock 뉴스 자동 수집 및 트레이딩 일지 사이트

**Live Site**: [investing.2twodragon.com](https://investing.2twodragon.com)

## Features

- **암호화폐 뉴스**: CryptoPanic, NewsAPI, Google News RSS, 거래소 공지 등 다중 소스 자동 수집
- **주식 뉴스**: NewsAPI, Yahoo Finance, KRX, Alpha Vantage 자동 수집
- **규제 동향**: SEC, CFTC, FSC, FSA, ESMA, FCA 등 글로벌 규제 뉴스
- **정치인 거래**: 미국 의회 주식거래, SEC 내부자거래, 한국 정치인 자산공개
- **DeFi TVL**: DeFi Llama 기반 프로토콜/체인별 TVL 추적
- **World Monitor**: 지정학, 에너지, 글로벌 뉴스 브리핑
- **CoinMarketCap/CoinGecko**: 시가총액 순위, 트렌딩, 상승/하락 코인
- **소셜 미디어**: Telegram 채널, Twitter/X 크립토 동향
- **보안 알림**: 해킹, 취약점, Rekt News 자동 수집
- **시장 분석**: 일일/주간 요약, 매크로 지표 (FRED), 공포/탐욕 지수
- **트레이딩 일지**: 암호화폐/주식 거래 기록 및 손익 분석

## Architecture

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  Collection  │ ──▶ │  Processing  │ ──▶ │ Presentation │
│   (Python)   │     │   (Python)   │     │   (Jekyll)   │
└──────────────┘     └──────────────┘     └──────────────┘
  8 Collectors         3 Generators        GitHub Pages
  20+ Data Sources     Image Generator     Dark Finance Theme
  GitHub Actions       Dedup Engine        9 Category Pages
```

- **Jekyll**: 정적 사이트 생성 (dark finance theme, minima 기반)
- **Python Scripts**: 뉴스 수집, 중복 제거, 요약 생성, 이미지 생성
- **GitHub Actions**: 22개 워크플로우 (스케줄 기반 자동 수집, 배포, 모니터링)

> 상세 아키텍처: [docs/architecture.md](docs/architecture.md)

## Data Sources

### 수집기별 데이터 소스 요약

| 수집기 | 주기 | 주요 소스 |
|:-------|:----:|:---------|
| `collect_crypto_news` | 6h | CryptoPanic, NewsAPI, Google News, 거래소 공지(OKX/Binance/Bybit), Rekt News |
| `collect_stock_news` | 6h | NewsAPI, Yahoo Finance, yfinance, KRX, Alpha Vantage |
| `collect_coinmarketcap` | 6h | CoinMarketCap API, CoinGecko API (fallback) |
| `collect_defi_llama` | 6h | DeFi Llama API (프로토콜/체인 TVL) |
| `collect_social_media` | 12h | Telegram 공개 채널, Twitter/X API v2 |
| `collect_regulatory` | 12h | SEC, CFTC, Fed, FSC, FSA, MAS, ESMA, FCA (RSS) |
| `collect_political_trades` | 일간 | 미국 의회 거래공시, SEC EDGAR, 한국 정치인 자산 |
| `collect_worldmonitor_news` | 일간 | WorldMonitor RSS (지정학, 에너지) |

### API 키 (모두 선택 사항)

| 환경변수 | 서비스 | 용도 |
|:---------|:-------|:-----|
| `CRYPTOPANIC_API_KEY` | [CryptoPanic](https://cryptopanic.com/developers/api/) | 암호화폐 뉴스 핫 피드 |
| `NEWSAPI_API_KEY` | [NewsAPI](https://newsapi.org/) | 키워드 기반 뉴스 검색 |
| `ALPHA_VANTAGE_API_KEY` | [Alpha Vantage](https://www.alphavantage.co/support/) | 미국 시장 데이터 |
| `FRED_API_KEY` | [FRED](https://fred.stlouisfed.org/docs/api/api_key.html) | 매크로 경제 지표 |
| `TWITTER_BEARER_TOKEN` | [Twitter API v2](https://developer.twitter.com/) | 암호화폐 트윗 검색 |
| `COINGECKO_API_KEY` | [CoinGecko](https://www.coingecko.com/en/api) | 코인 가격/트렌딩 |
| `CMC_API_KEY` | [CoinMarketCap](https://coinmarketcap.com/api/) | 시가총액 순위 데이터 |

키가 없으면 해당 소스를 건너뛰고 나머지로 수집합니다 (Graceful degradation).

> 전체 소스 카탈로그: [docs/data-sources.md](docs/data-sources.md)

## Setup

### 1. Clone & Local Dev

```bash
git clone https://github.com/Twodragon0/investing.git
cd investing
bundle install
bundle exec jekyll serve
```

### 2. GitHub Secrets

**Settings > Secrets and variables > Actions**에서 위 API 키를 Secret으로 등록합니다.

추가 Slack 연동 (선택):

| 환경변수 | 용도 |
|:---------|:-----|
| `SLACK_BOT_TOKEN` | 수집 결과 알림 |
| `SLACK_AI_BOT_TOKEN` | AI 멘션 자동 응답 |
| `SLACK_CHANNEL_*` | 채널 ID (ops/dev/security/investing) |

추가 Vercel/Sentry 연동 (GitHub App 권장):

- **Vercel GitHub App** 설치 후 해당 저장소를 Vercel 프로젝트에 연결
- **Sentry GitHub App** 설치 후 저장소와 프로젝트 연결 (이슈/알림 연동)
- CI에서는 별도 토큰 없이 GitHub App 기반 연동을 사용

추가 Vercel Analytics/Speed Insights (선택):

- Vercel 대시보드에서 **Analytics** 및 **Speed Insights**를 활성화
- HTML 스니펫은 `_layouts/default.html`에 포함되어 있어 별도 패키지 설치 없이 동작

### 3. Enable GitHub Pages

1. **Settings > Pages** 이동
2. Source: **GitHub Actions** 선택
3. `deploy-pages.yml` 워크플로우가 자동 배포 처리

### 4. Test Collectors Locally

```bash
pip install -r scripts/requirements.txt

# API 키 설정 (선택)
export NEWSAPI_API_KEY=your_key_here

# 수집기 실행
python scripts/collect_crypto_news.py
python scripts/collect_stock_news.py
python scripts/collect_coinmarketcap.py
python scripts/collect_regulatory.py
python scripts/collect_political_trades.py
python scripts/collect_social_media.py
python scripts/collect_worldmonitor_news.py
python scripts/collect_defi_llama.py

# 생성기 실행
python scripts/generate_market_summary.py
python scripts/generate_daily_summary.py
python scripts/generate_weekly_digest.py
```

## GitHub Actions Workflows

### 데이터 수집 (8개)

| 워크플로우 | 스케줄 (UTC) | 설명 |
|:-----------|:------------|:-----|
| `collect-crypto-news` | 매 6h `:00` | 암호화폐 뉴스 수집 (CryptoPanic, NewsAPI, RSS, 거래소) |
| `collect-coinmarketcap` | 매 6h `:15` | CoinMarketCap/CoinGecko 시가총액 데이터 |
| `collect-stock-news` | 매 6h `:30` | 주식 뉴스 수집 (NewsAPI, Yahoo, Alpha Vantage) |
| `collect-defi-llama` | 매 6h `:45` | DeFi TVL 데이터 (프로토콜/체인) |
| `collect-social-media` | 매 12h `01:00/13:00` | 소셜 미디어 (Telegram, Twitter/X) |
| `collect-regulatory` | 매 12h `01:15/13:15` | 글로벌 규제 뉴스 (SEC, FSC 등 9개 기관) |
| `collect-political-trades` | 매일 `13:30` | 정치인 거래 (의회 공시, SEC EDGAR) |
| `collect-worldmonitor-news` | 매일 `01:30` | WorldMonitor 글로벌 뉴스 브리핑 |

### 콘텐츠 생성 (4개)

| 워크플로우 | 스케줄 (UTC) | 설명 |
|:-----------|:------------|:-----|
| `generate-market-summary` | 매일 `01:45` | 시장 분석 요약 + 시각화 이미지 생성 |
| `generate-daily-summary` | 매일 `02:00` | 당일 수집 뉴스 종합 요약 (우선순위별) |
| `backfill-post-summaries` | 매일 `02:15` | 포스트 요약/분석 자동 보강 |
| `weekly-digest` | 일요일 `23:00` | 주간 다이제스트 (카테고리별 분석) |

### 배포 & 운영 (10개)

| 워크플로우 | 트리거 | 설명 |
|:-----------|:------|:-----|
| `deploy-pages` | Push to main | Jekyll 빌드, GitHub Pages 배포 |
| `code-quality` | Push, PR, 주간 | ruff 린팅, actionlint, import 검사 |
| `dependency-check` | 매주 월요일 | pip-audit 보안 의존성 검사 |
| `site-health-check` | 매일 `16:00` | 사이트 가용성, 최신 포스트 확인 |
| `cleanup-old-images` | 매주 일요일 | 30일 이상 된 생성 이미지 정리 |
| `respond-ai-mentions` | 5분마다 | Slack AI 봇 멘션 자동 응답 |
| `push-folder-info-to-slack` | 매일 `01:00` | 일일 레포지토리 상태 Slack 알림 |
| `ops-10am-digest` | 매일 `01:00` | 운영 10AM 다이제스트 Slack 알림 |
| `classify-workflow-failures` | 워크플로우 실패 시 | CI 실패 자동 분류 (네트워크 vs 코드) |
| `continuous-improvement-loop` | 매 6h | 개선 리포트 생성 및 Slack 다이제스트 |

수동 실행: `gh workflow run <workflow-name>.yml`

## Deduplication

포스트 중복 방지 3단계:

1. **SHA256 해시**: `normalize(title) + source + date[:10]` 해싱
2. **Fuzzy 매칭**: `difflib.SequenceMatcher` 유사도 80% 초과 시 중복 판정
3. **상태 파일**: `_state/*.json`에 해시 저장 (30일 보관)

## Project Structure

```
investing/
├── _config.yml                 # Jekyll 설정
├── _layouts/                   # HTML 레이아웃
├── _includes/                  # 재사용 컴포넌트
├── _sass/                      # SCSS 스타일 (다크 테마)
├── _data/                      # Jekyll 데이터 파일
├── _posts/                     # 자동 생성 포스트
├── _state/                     # 중복 방지 상태 파일
├── assets/images/generated/    # 자동 생성 이미지 (30일 보관)
├── pages/                      # 카테고리 페이지 (9개)
├── scripts/
│   ├── common/                 # 공통 모듈 (13개)
│   │   ├── config.py           # 환경변수, 로깅 설정
│   │   ├── dedup.py            # 중복 방지 (SHA256 + fuzzy)
│   │   ├── utils.py            # sanitize, retry, date parse
│   │   ├── post_generator.py   # Jekyll 포스트 생성
│   │   ├── image_generator.py  # 시장 시각화 (matplotlib/Pillow)
│   │   ├── crypto_api.py       # CoinGecko, Fear&Greed API
│   │   ├── rss_fetcher.py      # RSS 병렬 수집
│   │   ├── summarizer.py       # 키워드 기반 테마 요약
│   │   ├── formatters.py       # 숫자 포맷 (K/M/B/T)
│   │   ├── browser.py          # Playwright 브라우저
│   │   ├── collector_metrics.py # 수집 메트릭 로깅
│   │   └── markdown_utils.py   # 마크다운 헬퍼
│   ├── collect_*.py            # 수집기 8개
│   ├── generate_*.py           # 생성기 3개
│   └── respond_ai_mentions.py  # Slack AI 멘션 응답
├── .github/
│   ├── workflows/              # 워크플로우 22개
│   └── actions/                # 재사용 액션
│       ├── python-collect/     # Python 수집 & 커밋
│       └── resolve-slack-config/ # Slack 설정 해석
├── docs/                       # 프로젝트 문서
├── Gemfile                     # Ruby 의존성
└── README.md
```

## Documentation

| 문서 | 내용 |
|:-----|:-----|
| [Architecture](docs/architecture.md) | 시스템 아키텍처, 데이터 흐름, 컴포넌트 상세 |
| [Data Sources](docs/data-sources.md) | 전체 데이터 소스 카탈로그, API 키 설정 가이드 |
| [Improvement Priority](docs/continuous-improvement-priority.md) | 지속적 개선 우선순위 (P0/P1/P2) |

## License

MIT
