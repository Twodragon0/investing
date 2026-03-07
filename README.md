# Investing Dragon - Market Data Intelligence Layer

[![Live Site](https://img.shields.io/badge/site-investing.2twodragon.com-blue.svg)](https://investing.2twodragon.com)
[![Python](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![Jekyll](https://img.shields.io/badge/jekyll-4.x-red.svg)](https://jekyllrb.com/)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**DragonQuant 플랫폼**의 데이터 인텔리전스 계층입니다.
20+ 소스에서 시장 데이터를 자동 수집하고, 구조화하여 퀀트 트레이딩 엔진([crypto](https://github.com/Twodragon0/crypto))에 시그널 원천 데이터를 공급합니다.

## Platform Position

```
DragonQuant Platform
┌─────────────────────────────────────────────────────────────────────┐
│                                                                     │
│  ┌─────────────────────────┐      ┌─────────────────────────────┐  │
│  │  investing (이 저장소)    │      │  crypto                     │  │
│  │  Data Intelligence       │─────▶│  Quant Trading Engine        │  │
│  │                          │      │                              │  │
│  │  20+ 소스 자동 수집       │      │  14-Component MI Signal     │  │
│  │  8 Collectors            │      │  6 Technical Indicators     │  │
│  │  중복 제거 + 감성 분석    │      │  Kelly + CVaR 리스크 제어    │  │
│  │  Jekyll 사이트 발행       │      │  Upbit/Bithumb 자동매매     │  │
│  └─────────────────────────┘      └─────────────────────────────┘  │
│                                                                     │
│  연동: _posts/*.md → StructuredPostParser → Market Intelligence     │
└─────────────────────────────────────────────────────────────────────┘
```

> 전체 플랫폼 아키텍처: [docs/platform-architecture.md](docs/platform-architecture.md)

## Features

### 데이터 수집 (8 Collectors)

| 수집기 | 주기 | 주요 소스 | 카테고리 |
|:-------|:----:|:---------|:---------|
| `collect_crypto_news` | 6h | CryptoPanic, NewsAPI, Google News, 거래소 공지, Rekt News | crypto-news |
| `collect_stock_news` | 6h | NewsAPI, Yahoo Finance, yfinance, KRX, Alpha Vantage | stock-news |
| `collect_coinmarketcap` | 6h | CoinMarketCap API, CoinGecko API (fallback) | crypto-news |
| `collect_defi_llama` | 6h | DeFi Llama API (프로토콜/체인 TVL) | crypto-news |
| `collect_social_media` | 12h | Telegram 채널, Twitter/X API v2 | social-media |
| `collect_regulatory` | 12h | SEC, CFTC, Fed, FSC, FSA, MAS, ESMA, FCA (RSS) | regulation |
| `collect_political_trades` | 일간 | 의회 거래공시, SEC EDGAR, 한국 정치인 자산 | political-trades |
| `collect_worldmonitor_news` | 일간 | WorldMonitor RSS (지정학, 에너지) | world-monitor |

### 콘텐츠 생성 (3 Generators)

| 생성기 | 스케줄 | 출력 |
|:-------|:------|:-----|
| `generate_market_summary` | 매일 | 시장 분석 + 시각화 이미지 (히트맵, 게이지, 카드) |
| `generate_daily_summary` | 매일 | 우선순위별 종합 뉴스 요약 (P0/P1/P2) |
| `generate_weekly_digest` | 매주 일 | 주간 다이제스트 (카테고리별 분석) |

### crypto repo 연동

이 저장소의 `_posts/*.md`는 [crypto](https://github.com/Twodragon0/crypto) 저장소의 `StructuredPostParser`가 파싱하여 매매 시그널에 반영합니다:

| 추출 데이터 | 시그널 가중치 | 파싱 소스 |
|:-----------|:------------|:---------|
| Fear & Greed Index | 0.17 | market-analysis 포스트 |
| 소셜 감성 | 0.12 | social-media 포스트 (VADER + 한국어 키워드) |
| 정치 리스크 | 0.08 | political-trades 포스트 |
| VIX 변동성 | 0.08 | stock-news 포스트 |
| 보안 이벤트 | 0.07 | crypto-news (해킹 금액 추출) |
| 한국 시장 | 0.07 | stock-news (KOSPI/KOSDAQ/USD-KRW) |
| BTC 도미넌스 | 0.06 | crypto-news 포스트 |
| 규제 시그널 | 0.04 | regulatory 포스트 |

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    GitHub Actions (22 Workflows)                 │
│  Concurrency Group: collect-data  │  Cron Schedule  │  Deploy   │
└────────┬────────────────────┬──────────────────────┬────────────┘
         │                    │                      │
         ▼                    ▼                      ▼
┌─────────────────┐  ┌─────────────────┐  ┌──────────────────┐
│   Collection    │  │   Processing    │  │   Presentation   │
│                 │  │                 │  │                  │
│  8 Collectors   │─▶│  3 Generators   │─▶│  Jekyll Site     │
│  20+ Sources    │  │  Image Gen      │  │  GitHub Pages    │
│  Dedup Engine   │  │  Summarizer     │  │  OG/SNS 최적화   │
│  Enrichment     │  │  OG Image Gen   │  │  9 Categories    │
└────────┬────────┘  └────────┬────────┘  └──────────────────┘
         │                    │
         ▼                    ▼
┌─────────────────────────────────────────┐
│  _state/*.json  │  _posts/*.md          │
│  SHA256 + Fuzzy │  → crypto repo 소비    │
└─────────────────────────────────────────┘
```

## Quick Start

### 1. Clone & Local Dev

```bash
git clone https://github.com/Twodragon0/investing.git
cd investing
bundle install
bundle exec jekyll serve    # http://localhost:4000
```

### 2. Python 수집기 실행

```bash
pip install -r scripts/requirements.txt

# 수집기 (API 키 없어도 동작, Graceful degradation)
python scripts/collect_crypto_news.py
python scripts/collect_stock_news.py

# 생성기
python scripts/generate_market_summary.py
python scripts/generate_daily_summary.py
```

### 3. GitHub Secrets (선택)

| 환경변수 | 서비스 | 용도 |
|:---------|:-------|:-----|
| `CRYPTOPANIC_API_KEY` | CryptoPanic | 암호화폐 뉴스 핫 피드 |
| `NEWSAPI_API_KEY` | NewsAPI | 키워드 기반 뉴스 검색 |
| `ALPHA_VANTAGE_API_KEY` | Alpha Vantage | 미국 시장 데이터 |
| `FRED_API_KEY` | FRED | 매크로 경제 지표 |
| `TWITTER_BEARER_TOKEN` | Twitter API v2 | 암호화폐 트윗 검색 |
| `COINGECKO_API_KEY` | CoinGecko | 코인 가격/트렌딩 |
| `CMC_API_KEY` | CoinMarketCap | 시가총액 순위 |

키가 없으면 해당 소스를 건너뛰고 나머지로 수집합니다.

## Deduplication

포스트 중복 방지 3단계:

1. **SHA256 해시**: `normalize(title) + source + date[:10]` 해싱
2. **Fuzzy 매칭**: `difflib.SequenceMatcher` 유사도 80% 초과 시 중복 판정
3. **상태 파일**: `_state/*.json`에 해시 저장 (30일 보관)

## GitHub Actions Workflows (22개)

### 데이터 수집 (8개)

| 워크플로우 | 스케줄 (UTC) | 설명 |
|:-----------|:------------|:-----|
| `collect-crypto-news` | 매 6h `:00` | 암호화폐 뉴스 |
| `collect-coinmarketcap` | 매 6h `:15` | CoinMarketCap/CoinGecko |
| `collect-stock-news` | 매 6h `:30` | 주식 뉴스 |
| `collect-defi-llama` | 매 6h `:45` | DeFi TVL |
| `collect-social-media` | 매 12h | 소셜 미디어 |
| `collect-regulatory` | 매 12h | 글로벌 규제 |
| `collect-political-trades` | 매일 | 정치인 거래 |
| `collect-worldmonitor-news` | 매일 | 글로벌 뉴스 |

### 콘텐츠 생성 (4개)

| 워크플로우 | 스케줄 | 설명 |
|:-----------|:------|:-----|
| `generate-market-summary` | 매일 | 시장 분석 + 시각화 |
| `generate-daily-summary` | 매일 | 일일 종합 요약 |
| `backfill-post-summaries` | 매일 | 포스트 요약 보강 |
| `weekly-digest` | 매주 일 | 주간 다이제스트 |

### 배포 & 운영 (10개)

| 워크플로우 | 트리거 | 설명 |
|:-----------|:------|:-----|
| `deploy-pages` | Push to main | Jekyll 빌드, GitHub Pages 배포 |
| `code-quality` | Push, PR, 주간 | ruff, basedpyright, actionlint |
| `dependency-check` | 매주 월 | pip-audit 보안 의존성 |
| `site-health-check` | 매일 | 사이트 가용성 확인 |
| `cleanup-old-images` | 매주 일 | 30일 이상 이미지 정리 |
| `respond-ai-mentions` | 5분마다 | Slack AI 봇 응답 |
| `push-folder-info-to-slack` | 매일 | 레포 상태 Slack 알림 |
| `ops-10am-digest` | 매일 | 운영 다이제스트 |
| `classify-workflow-failures` | 실패 시 | CI 실패 자동 분류 |
| `continuous-improvement-loop` | 매 6h | 개선 리포트 생성 |

## Project Structure

```
investing/
├── _config.yml                 # Jekyll 설정
├── _layouts/                   # HTML 레이아웃 (OG/Twitter meta 포함)
├── _includes/                  # 재사용 컴포넌트
├── _sass/                      # SCSS 스타일 (다크 파이낸스 테마)
├── _data/                      # Jekyll 데이터 파일
├── _posts/                     # 자동 생성 포스트 → crypto repo가 소비
├── _state/                     # 중복 방지 상태 파일 (수동 수정 금지)
├── assets/images/generated/    # OG 이미지 + 시각화 (30일 보관)
├── pages/                      # 카테고리 페이지 (9개)
├── scripts/
│   ├── common/                 # 공통 모듈 (13개)
│   │   ├── config.py           # 환경변수, 로깅
│   │   ├── dedup.py            # SHA256 + fuzzy 중복 방지
│   │   ├── enrichment.py       # URL 해석, 설명 생성
│   │   ├── summarizer.py       # 키워드 기반 요약
│   │   ├── image_generator.py  # matplotlib/Pillow 시각화
│   │   └── ...                 # utils, rss_fetcher, crypto_api 등
│   ├── collect_*.py            # 수집기 8개
│   ├── generate_*.py           # 생성기 3개 + OG 이미지
│   └── enrich_existing_posts.py # 포스트 품질 보강
├── docs/
│   ├── platform-architecture.md # DragonQuant 통합 아키텍처
│   ├── architecture.md         # 이 저장소 상세 아키텍처
│   └── data-sources.md         # 데이터 소스 카탈로그
├── .github/
│   ├── workflows/              # 22개 자동화 워크플로우
│   └── actions/                # 재사용 액션 (python-collect, resolve-slack-config)
├── Gemfile                     # Ruby 의존성
└── README.md
```

## Documentation

| 문서 | 내용 |
|:-----|:-----|
| [Platform Architecture](docs/platform-architecture.md) | DragonQuant 전체 플랫폼 설계, PSST 매핑, 백테스트 결과 |
| [Architecture](docs/architecture.md) | 이 저장소 상세 아키텍처, 데이터 흐름, 모듈 의존성 |
| [Data Sources](docs/data-sources.md) | 전체 데이터 소스 카탈로그, API 키 설정 가이드 |

## Related Repository

| 저장소 | 역할 | 링크 |
|:-------|:-----|:-----|
| **crypto** | 퀀트 트레이딩 엔진 (ATS 3.0) | [Twodragon0/crypto](https://github.com/Twodragon0/crypto) |
| | 14-Component 시그널 합성, Upbit/Bithumb 자동매매 | |
| | 보안 모니터링, FastAPI 대시보드 | |

## License

MIT
