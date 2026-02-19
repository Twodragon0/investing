# Architecture

## 시스템 개요

Investing Dragon은 3-tier 아키텍처로 구성됩니다:

```
┌─────────────────────────────────────────────────────────────────────┐
│                        GitHub Actions (Cron)                        │
│  20 Workflows  │  Concurrency Group: collect-data  │  Auto Deploy  │
└────────┬────────────────────┬──────────────────────┬────────────────┘
         │                    │                      │
         ▼                    ▼                      ▼
┌─────────────────┐  ┌─────────────────┐  ┌──────────────────┐
│   Collection    │  │   Processing    │  │   Presentation   │
│                 │  │                 │  │                  │
│  8 Collectors   │─▶│  3 Generators   │─▶│  Jekyll Site     │
│  20+ Sources    │  │  Image Gen      │  │  GitHub Pages    │
│  Dedup Engine   │  │  Summarizer     │  │  9 Categories    │
└────────┬────────┘  └────────┬────────┘  └──────────────────┘
         │                    │
         ▼                    ▼
┌─────────────────────────────────────────┐
│           _state/*.json                 │
│   SHA256 Hash + Fuzzy Match (>80%)      │
│   30-day retention                      │
└─────────────────────────────────────────┘
```

## 데이터 흐름

```
[External APIs / RSS Feeds]
        │
        ▼
┌───────────────────────┐
│  collect_*.py (8개)   │  수집 → 중복검사 → 포스트 생성
│                       │
│  dedup.py             │  SHA256 + fuzzy matching
│  utils.py             │  sanitize, retry, date parse
│  rss_fetcher.py       │  병렬 RSS 수집
└───────┬───────────────┘
        │  _posts/*.md + _state/*.json
        ▼
┌───────────────────────┐
│  generate_*.py (3개)  │  포스트 읽기 → 분석 → 요약 생성
│                       │
│  summarizer.py        │  키워드 분류, 테마 요약
│  image_generator.py   │  차트, 히트맵, 게이지
│  crypto_api.py        │  CoinGecko, Fear&Greed
└───────┬───────────────┘
        │  _posts/*.md + assets/images/generated/*
        ▼
┌───────────────────────┐
│  Jekyll Build         │  Markdown → HTML → GitHub Pages
│  deploy-pages.yml     │
└───────────────────────┘
```

## 수집기 (Collectors) - 8개

### 1. `collect_crypto_news.py` - 암호화폐 뉴스

| 항목 | 내용 |
|:-----|:-----|
| **소스** | CryptoPanic API, NewsAPI, Google News RSS (KR/EN), 거래소 공지 (OKX, Binance, Bybit), Rekt News |
| **주기** | 매 6시간 |
| **API 키** | `CRYPTOPANIC_API_KEY`, `NEWSAPI_API_KEY` (모두 선택) |
| **카테고리** | crypto-news, security-alerts |
| **상태 파일** | `_state/collect_crypto_news_seen.json` |

### 2. `collect_stock_news.py` - 주식 뉴스

| 항목 | 내용 |
|:-----|:-----|
| **소스** | NewsAPI (KOSPI/S&P 500 키워드), Yahoo Finance RSS, yfinance (한국 시장), KRX Google News, Alpha Vantage |
| **주기** | 매 6시간 |
| **API 키** | `NEWSAPI_API_KEY`, `ALPHA_VANTAGE_API_KEY` (모두 선택) |
| **카테고리** | stock-news |
| **상태 파일** | `_state/collect_stock_news_seen.json` |

### 3. `collect_coinmarketcap.py` - 시가총액 데이터

| 항목 | 내용 |
|:-----|:-----|
| **소스** | CoinMarketCap API (top 코인, 트렌딩, 상승/하락), CoinGecko API (무료 fallback) |
| **주기** | 매 6시간 |
| **API 키** | `CMC_API_KEY`, `COINGECKO_API_KEY` (모두 선택, CoinGecko는 무료 대체) |
| **카테고리** | crypto-news |
| **상태 파일** | `_state/collect_coinmarketcap_seen.json` |

### 4. `collect_defi_llama.py` - DeFi TVL

| 항목 | 내용 |
|:-----|:-----|
| **소스** | DeFi Llama API - `GET /v2/protocols` (Top 20), `GET /v2/chains` (Top 15) |
| **주기** | 매 6시간 |
| **API 키** | 불필요 (공개 API) |
| **카테고리** | crypto-news |
| **상태 파일** | `_state/defi_llama_seen.json` |

### 5. `collect_social_media.py` - 소셜 미디어

| 항목 | 내용 |
|:-----|:-----|
| **소스** | Telegram 공개 채널 (HTML 스크래핑), Twitter/X API v2, Google News RSS (fallback) |
| **주기** | 매 12시간 |
| **API 키** | `TWITTER_BEARER_TOKEN` (선택) |
| **카테고리** | social-media |
| **상태 파일** | `_state/collect_social_media_seen.json` |

### 6. `collect_regulatory.py` - 규제 뉴스

| 항목 | 내용 |
|:-----|:-----|
| **소스** | 미국: SEC, CFTC (RSS), Federal Reserve (Atom) / 한국: FSC (RSS), Google News / 아시아: FSA / 유럽: ESMA, FCA, MAS |
| **주기** | 매 12시간 |
| **API 키** | 불필요 (모두 공개 RSS/피드) |
| **카테고리** | regulation |
| **상태 파일** | `_state/collect_regulatory_seen.json` |

### 7. `collect_political_trades.py` - 정치인 거래

| 항목 | 내용 |
|:-----|:-----|
| **소스** | 미국 의회 주식거래 공시, SEC EDGAR Form 4, 대통령 경제정책, 한국 정치인 자산공개, 중앙은행 정책 |
| **주기** | 매일 |
| **API 키** | 불필요 (모두 Google News RSS) |
| **카테고리** | political-trades |
| **상태 파일** | `_state/collect_political_trades_seen.json` |

### 8. `collect_worldmonitor_news.py` - 글로벌 뉴스

| 항목 | 내용 |
|:-----|:-----|
| **소스** | WorldMonitor RSS Proxy (지정학/안보, 에너지 테마) |
| **주기** | 매일 |
| **API 키** | 불필요 |
| **카테고리** | world-monitor |
| **상태 파일** | `_state/collect_worldmonitor_news_seen.json` |

### 수집기 공통 동작

1. **소스 순회**: 각 데이터 소스에서 뉴스/데이터 가져오기
2. **정규화**: 제목, 본문 정리 (`utils.sanitize_string`)
3. **중복 검사**: `dedup.py`로 SHA256 해시 + fuzzy matching
4. **포스트 생성**: `post_generator.py`로 Jekyll 마크다운 생성
5. **상태 저장**: `_state/collect_*_seen.json`에 해시 기록
6. **메트릭 로깅**: `collector_metrics.py`로 수집 통계 출력

## 생성기 (Generators) - 3개

### 1. `generate_market_summary.py` - 시장 분석 요약

| 항목 | 내용 |
|:-----|:-----|
| **입력** | CoinGecko (코인), Alpha Vantage (미국 시장), yfinance (한국 시장), FRED (매크로), Fear&Greed |
| **출력** | 시장 분석 포스트 + 시각화 이미지 (히트맵, 게이지, 카드) |
| **스케줄** | 매일 00:30 UTC |
| **API 키** | `ALPHA_VANTAGE_API_KEY`, `FRED_API_KEY` (선택) |

### 2. `generate_daily_summary.py` - 일일 종합 요약

| 항목 | 내용 |
|:-----|:-----|
| **입력** | 당일 `_posts/` 전체 포스트 |
| **출력** | 우선순위별 종합 뉴스 요약 (P0 긴급 → P1 주요 → P2 주목) |
| **스케줄** | 매일 01:00 UTC |
| **구조** | 긴급 알림 → 시장 개요 → 지표 → 정치 → 규제/ETF → 카테고리별 → 링크 |

### 3. `generate_weekly_digest.py` - 주간 다이제스트

| 항목 | 내용 |
|:-----|:-----|
| **입력** | 7일간 `_posts/` 전체 포스트 |
| **출력** | 주간 분석 (하이라이트, 카테고리별 인사이트, 실행 가능 요약) |
| **스케줄** | 매주 일요일 23:00 UTC |

## 공통 모듈 (Common) - 13개

| 모듈 | 역할 | 주요 API |
|:-----|:-----|:---------|
| `config.py` | 환경변수 로드, 로깅 설정 | `get_env()`, `setup_logging()`, `get_ssl_verify()` |
| `dedup.py` | 중복 방지 엔진 | SHA256 해싱 + `SequenceMatcher` fuzzy (>80%) |
| `utils.py` | 유틸리티 함수 | `sanitize_string()`, `parse_date()`, `request_with_retry()` |
| `post_generator.py` | Jekyll 포스트 생성 | `_slugify()`, `POSTS_DIR` |
| `image_generator.py` | 시장 시각화 이미지 | matplotlib + Pillow (히트맵, 게이지, 카드) |
| `crypto_api.py` | 암호화폐 가격 API | `fetch_coingecko_*()`, `fetch_fear_greed_index()` |
| `rss_fetcher.py` | RSS 피드 수집 | `fetch_rss_feed()`, `fetch_rss_feeds_concurrent()` |
| `summarizer.py` | 키워드 기반 요약 | 테마 분류, 이슈 분포 차트, 키워드 분석 |
| `formatters.py` | 숫자/퍼센트 포맷 | `fmt_number()` → `$1.50B`, `fmt_percent()` |
| `browser.py` | Playwright 브라우저 | `is_playwright_available()`, `BrowserSession` |
| `collector_metrics.py` | 수집 통계 로깅 | `log_collection_summary()` |
| `markdown_utils.py` | 마크다운 헬퍼 | `escape_table_cell()`, `markdown_table()` |
| `__init__.py` | 패키지 초기화 | - |

### 모듈 의존성 관계

```
collect_*.py ──▶ config.py          (환경변수)
             ──▶ dedup.py           (중복 검사)
             ──▶ utils.py           (sanitize, retry)
             ──▶ rss_fetcher.py     (RSS 수집)
             ──▶ post_generator.py  (포스트 생성)
             ──▶ collector_metrics.py (메트릭)
             ──▶ markdown_utils.py  (마크다운)

generate_*.py ──▶ config.py         (환경변수)
              ──▶ crypto_api.py     (API 호출)
              ──▶ image_generator.py (이미지)
              ──▶ summarizer.py     (요약)
              ──▶ formatters.py     (포맷)
              ──▶ post_generator.py (포스트 생성)
```

## 중복 방지 시스템

```
입력: (title, source, date)
        │
        ▼
┌─────────────────────┐
│  1. 정규화           │  lowercase, strip whitespace/punctuation
└───────┬─────────────┘
        │
        ▼
┌─────────────────────┐
│  2. SHA256 해싱      │  hash(normalize(title) + source + date[:10])
└───────┬─────────────┘
        │
        ├── 해시 일치 → 중복 (건너뛰기)
        │
        ▼ (해시 불일치)
┌─────────────────────┐
│  3. Fuzzy Matching  │  SequenceMatcher > 80%
└───────┬─────────────┘
        │
        ├── 유사도 >80% → 중복 (건너뛰기)
        │
        ▼ (유사도 <=80%)
┌─────────────────────┐
│  4. 새 항목 등록     │  해시 → _state/*.json (30일 만료)
│     포스트 생성      │
└─────────────────────┘
```

## 이미지 생성 파이프라인

`generate_market_summary.py`에서 `image_generator.py`를 사용:

| 이미지 | 설명 | 데이터 소스 |
|:-------|:-----|:-----------|
| 시장 히트맵 | 코인별 가격 변동률 색상 시각화 | CoinGecko top coins |
| 공포/탐욕 게이지 | 현재 시장 심리 지수 표시 | Fear & Greed Index |
| Top 코인 카드 | 상위 코인 가격/변동률 요약 카드 | CoinGecko trending |

저장 위치: `assets/images/generated/` (매주 `cleanup-old-images.yml`이 30일 이상 파일 정리)

## Jekyll 사이트 구조

### 카테고리 페이지 (`pages/`) - 9개

| 페이지 | 카테고리 | 설명 |
|:-------|:---------|:-----|
| `crypto-news.md` | crypto-news | 암호화폐 뉴스 |
| `stock-news.md` | stock-news | 주식 뉴스 |
| `crypto-journal.md` | crypto-journal | 크립토 트레이딩 일지 |
| `stock-journal.md` | stock-journal | 주식 트레이딩 일지 |
| `market-analysis.md` | market-analysis | 시장 분석 |
| `security-alerts.md` | security-alerts | 보안 알림 |
| `regulatory-news.md` | regulation | 규제 동향 |
| `political-trades.md` | political-trades | 정치인 거래 |
| `about.md` | - | 사이트 소개 |

### 테마
- minima 기반 **다크 파이낸스** 스타일
- 반응형 디자인 (모바일/데스크탑)
- 테이블, 차트, 카드 전용 스타일

## CI/CD 파이프라인

### 워크플로우 그룹

| 그룹 | 워크플로우 수 | 동시성 | 설명 |
|:-----|:------------|:-------|:-----|
| **수집** | 8개 | `collect-data` 그룹 | 시간차 실행으로 push 충돌 방지 |
| **생성** | 3개 | 독립 | 수집 이후 시간대 실행 (00:30, 01:00 UTC) |
| **운영** | 9개 | 독립 | 배포, 모니터링, 유지보수 |

### 재사용 액션 (`.github/actions/`)

| 액션 | 용도 |
|:-----|:-----|
| `python-collect` | Python 수집 스크립트 공통 실행 (Python 3.11 + pip 캐시 + Playwright + SSL 검증 + commit & push with retry) |
| `resolve-slack-config` | Slack 토큰/채널 후보 중 유효값 자동 선택 (ops/dev/security/investing 별칭 지원) |

### 스케줄 타임라인 (UTC)

```
매 6시간:
  :00  collect-crypto-news
  :12  collect-coinmarketcap
  :24  collect-stock-news
  :36  collect-defi-llama

매 12시간:
  :36  collect-social-media
  :48  collect-regulatory

매일:
  00:30  generate-market-summary
  01:00  generate-daily-summary, collect-worldmonitor-news,
         push-folder-info-to-slack
  13:00  collect-political-trades
  16:00  site-health-check

매주:
  일요일 00:00  code-quality
  일요일 03:00  cleanup-old-images
  일요일 23:00  weekly-digest
  월요일 02:00  dependency-check

이벤트 기반:
  Push to main      → deploy-pages
  Workflow 실패     → classify-workflow-failures
  5분마다           → respond-ai-mentions
  매시간            → continuous-improvement-loop
```
