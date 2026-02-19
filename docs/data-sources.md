# Data Sources

전체 데이터 소스 카탈로그 및 API 키 설정 가이드.

## 소스 카탈로그

### 암호화폐 뉴스 (`collect_crypto_news.py`)

| 소스 | 유형 | API 키 | 설명 |
|:-----|:-----|:-------|:-----|
| CryptoPanic | REST API | `CRYPTOPANIC_API_KEY` (선택) | 암호화폐 핫 뉴스 피드 |
| NewsAPI | REST API | `NEWSAPI_API_KEY` (선택) | 키워드 기반 뉴스 검색 |
| Google News RSS | RSS | 불필요 | 한국어/영어 암호화폐 뉴스 |
| OKX 공지 | Public API | 불필요 | OKX 거래소 공지사항 |
| Binance 공지 | Public API | 불필요 | Binance 거래소 공지사항 |
| Bybit 공지 | Public API | 불필요 | Bybit 거래소 공지사항 |
| Rekt News | RSS/웹 | 불필요 | 해킹/취약점 보안 사건 (security-alerts) |

### 주식 뉴스 (`collect_stock_news.py`)

| 소스 | 유형 | API 키 | 설명 |
|:-----|:-----|:-------|:-----|
| NewsAPI | REST API | `NEWSAPI_API_KEY` (선택) | KOSPI, S&P 500 키워드 뉴스 |
| Yahoo Finance RSS | RSS | 불필요 | 글로벌 주식 뉴스 피드 |
| yfinance | Python 라이브러리 | 불필요 | 한국 시장 데이터 (KOSPI, KOSDAQ) |
| KRX (Google News) | RSS | 불필요 | 한국거래소 관련 뉴스 |
| Alpha Vantage | REST API | `ALPHA_VANTAGE_API_KEY` (선택) | 미국 시장 스냅샷 데이터 |

### CoinMarketCap/CoinGecko (`collect_coinmarketcap.py`)

| 소스 | 유형 | API 키 | 설명 |
|:-----|:-----|:-------|:-----|
| CoinMarketCap | REST API | `CMC_API_KEY` (선택) | Top 코인 시가총액, 트렌딩, 상승/하락 |
| CoinGecko | REST API | `COINGECKO_API_KEY` (선택) | 무료 대체: Top 코인, 트렌딩, 글로벌 데이터 |

### DeFi TVL (`collect_defi_llama.py`)

| 소스 | 엔드포인트 | 설명 |
|:-----|:----------|:-----|
| DeFi Llama | `GET /v2/protocols` | Top 20 프로토콜 TVL (Lido, AAVE 등) |
| DeFi Llama | `GET /v2/chains` | Top 15 체인 TVL (Ethereum, Solana 등) |

API 키: **불필요** (공개 API, `https://api.llama.fi`)

### 소셜 미디어 (`collect_social_media.py`)

| 소스 | 유형 | API 키 | 설명 |
|:-----|:-----|:-------|:-----|
| Telegram 공개 채널 | HTML 스크래핑 | 불필요 | `t.me/s/channel` 공개 메시지 수집 |
| Twitter/X | API v2 | `TWITTER_BEARER_TOKEN` (선택) | 암호화폐 키워드 트윗 검색 |
| Google News RSS | RSS | 불필요 | 소셜 키워드 뉴스 (fallback) |

### 규제 뉴스 (`collect_regulatory.py`)

| 소스 | 지역 | 유형 | 설명 |
|:-----|:-----|:-----|:-----|
| SEC | 미국 | Google News RSS | 증권거래위원회 관련 뉴스 |
| CFTC | 미국 | 공식 RSS | 상품선물거래위원회 보도자료 |
| Federal Reserve | 미국 | Atom 피드 | 연방준비제도 성명/결정 |
| FSC (금융위원회) | 한국 | 공식 RSS | 금융위원회 보도자료 |
| Google News (한국 규제) | 한국 | RSS | 한국 금융 규제 관련 뉴스 |
| FSA (금융청) | 일본 | 공식 RSS | 일본 금융청 발표 |
| MAS (통화청) | 싱가포르 | Google News RSS | 싱가포르 통화 정책 |
| ESMA | 유럽 | Google News RSS | 유럽증권시장감독국 규제 |
| FCA | 영국 | Google News RSS | 영국 금융감독원 조치 |

API 키: **불필요** (모두 공개 RSS/피드)

### 정치인 거래 (`collect_political_trades.py`)

| 소스 | 유형 | 설명 |
|:-----|:-----|:-----|
| 미국 의회 주식거래 공시 | Google News RSS | Congressional stock trading 공시 |
| SEC EDGAR (Form 4) | Google News RSS | 기업 내부자 거래 신고 |
| 트럼프 행정명령/경제정책 | Google News RSS | 대통령 경제 정책 및 행정명령 |
| 한국 정치인 자산공개 | Google News RSS | 국회의원 재산 변동 내역 |
| 중앙은행 정책 결정 | Google News RSS | 한/미/일/EU 중앙은행 금리 결정 |

API 키: **불필요** (모두 공개 RSS)

### WorldMonitor (`collect_worldmonitor_news.py`)

| 소스 | 유형 | 설명 |
|:-----|:-----|:-----|
| WorldMonitor RSS Proxy | RSS | 지정학/안보 뉴스 브리핑 |
| WorldMonitor RSS Proxy | RSS | 에너지 시장 뉴스 브리핑 |

API 키: **불필요** (`https://worldmonitor.app/api/rss-proxy`)

### 시장 분석 생성 (`generate_market_summary.py`)

| 소스 | 유형 | API 키 | 설명 |
|:-----|:-----|:-------|:-----|
| CoinGecko | REST API | `COINGECKO_API_KEY` (선택) | 코인 시세, 트렌딩, 글로벌 시장 데이터 |
| Alpha Vantage | REST API | `ALPHA_VANTAGE_API_KEY` (선택) | S&P 500, 나스닥 등 미국 시장 |
| yfinance | Python 라이브러리 | 불필요 | KOSPI, KOSDAQ 한국 시장 |
| FRED | REST API | `FRED_API_KEY` (선택) | 기준금리, 실업률, CPI 등 매크로 |
| Fear & Greed Index | Public API | 불필요 | 시장 심리 지수 (0-100) |

## API 키 설정 가이드

모든 API 키는 **선택 사항**입니다. 키가 없으면 해당 소스를 건너뛰고 나머지로 수집합니다.

### 환경변수 목록

| 환경변수 | 서비스 | 취득 방법 |
|:---------|:-------|:---------|
| `CRYPTOPANIC_API_KEY` | CryptoPanic | [cryptopanic.com/developers/api](https://cryptopanic.com/developers/api/) 가입 후 발급 |
| `NEWSAPI_API_KEY` | NewsAPI | [newsapi.org](https://newsapi.org/) 가입 후 발급 (무료 플랜 가능) |
| `ALPHA_VANTAGE_API_KEY` | Alpha Vantage | [alphavantage.co/support](https://www.alphavantage.co/support/) 무료 키 신청 |
| `FRED_API_KEY` | FRED | [fred.stlouisfed.org](https://fred.stlouisfed.org/docs/api/api_key.html) 가입 후 발급 |
| `TWITTER_BEARER_TOKEN` | Twitter/X v2 | [developer.twitter.com](https://developer.twitter.com/) 개발자 계정 후 Bearer Token |
| `COINGECKO_API_KEY` | CoinGecko | [coingecko.com/en/api](https://www.coingecko.com/en/api) Pro 또는 무료 플랜 |
| `CMC_API_KEY` | CoinMarketCap | [coinmarketcap.com/api](https://coinmarketcap.com/api/) Basic 무료 플랜 |

### Slack 연동 (알림용)

| 환경변수 | 용도 |
|:---------|:-----|
| `SLACK_BOT_TOKEN` | 수집 결과 알림 전송 |
| `SLACK_AI_BOT_TOKEN` | AI 멘션 자동 응답 |
| `SLACK_CHANNEL_INVESTING` | 투자 채널 ID |
| `SLACK_CHANNEL_OPS` | 운영 채널 ID |
| `SLACK_CHANNEL_DEV` | 개발 채널 ID |
| `SLACK_CHANNEL_SECURITY` | 보안 채널 ID |

### 로컬 환경 설정

```bash
# .env 파일 또는 shell에서 설정
export CRYPTOPANIC_API_KEY=your_key
export NEWSAPI_API_KEY=your_key
export ALPHA_VANTAGE_API_KEY=your_key
export FRED_API_KEY=your_key
export TWITTER_BEARER_TOKEN=your_token
export COINGECKO_API_KEY=your_key
export CMC_API_KEY=your_key
```

### GitHub Actions 설정

Repository **Settings > Secrets and variables > Actions**에서 위 환경변수를 Secret으로 등록합니다.

## Graceful Degradation 동작

| 시나리오 | 동작 |
|:---------|:-----|
| API 키 미설정 | 해당 소스 건너뛰기, `INFO` 로그 출력 |
| API 호출 실패 | `request_with_retry()`로 최대 3회 재시도 후 건너뛰기 |
| 모든 소스 실패 | 빈 결과로 정상 종료, 다음 스케줄에서 재시도 |
| SSL 인증서 문제 | certifi → 시스템 SSL → `DISABLE_SSL_VERIFY=true` (비권장) |
| API 타임아웃 | 기본 15초 (`REQUEST_TIMEOUT`), crypto_api는 20초 |

### 소스 우선순위

| 우선순위 | 유형 | 특징 |
|:---------|:-----|:-----|
| 1순위 | 전용 API (CryptoPanic, NewsAPI 등) | 구조화된 데이터, 필터링, 페이지네이션 |
| 2순위 | 공개 API (CoinGecko free, DeFi Llama) | 키 불필요, 사용량 제한 있음 |
| 3순위 | RSS/Google News | 항상 가용, 텍스트 기반 |
| 4순위 | 웹 스크래핑 (Telegram) | Playwright 필요, 가장 불안정 |
