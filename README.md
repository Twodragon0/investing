# Investing

Crypto & Stock 뉴스 자동 수집 및 트레이딩 일지 사이트

**Live Site**: [twodragon0.github.io/investing](https://twodragon0.github.io/investing)

## Features

- **암호화폐 뉴스**: CryptoPanic, NewsAPI, Google News RSS 등 다중 소스 자동 수집
- **주식 뉴스**: NewsAPI, Yahoo Finance, KRX 뉴스 자동 수집
- **크립토 트레이딩 일지**: 일일 거래 기록 및 손익 분석
- **주식 트레이딩 일지**: 주식 거래 기록
- **보안 알림**: 해킹, 취약점, Rekt News 자동 수집
- **시장 분석**: 일일 시장 요약, 매크로 지표 (FRED), 공포/탐욕 지수

## Architecture

```
Jekyll (GitHub Pages) + Python Collectors + GitHub Actions (Cron)
```

- **Jekyll**: 정적 사이트 생성 (dark finance theme)
- **Python Scripts**: 뉴스 수집, 중복 제거, 마크다운 포스트 생성
- **GitHub Actions**: 스케줄 기반 자동 수집 및 배포

## Data Sources

| Source | Type | Schedule |
|--------|------|----------|
| CryptoPanic API | Crypto news | Every 6h |
| NewsAPI | News (crypto + stock) | Every 6h |
| Google News RSS | News (KR/EN) | Every 6h |
| Binance Announcements | Exchange news | Every 6h |
| Rekt News | Security incidents | Every 6h |
| Yahoo Finance RSS | Stock news | Every 6h |
| Alpha Vantage | US market data | Every 6h / Daily |
| yfinance | KR market data | Daily |
| FRED | Macro indicators | Daily |
| CoinGecko | Crypto prices | Daily |
| Fear & Greed Index | Market sentiment | Daily |
| Telegram Channels | Social media | Every 12h |
| Twitter/X API | Social media | Every 12h |

## Setup

### 1. Clone & Local Dev

```bash
git clone https://github.com/Twodragon0/investing.git
cd investing
bundle install
bundle exec jekyll serve
```

### 2. GitHub Secrets

Add these secrets in **Settings > Secrets and variables > Actions**:

| Secret | Required | Description |
|--------|----------|-------------|
| `CRYPTOPANIC_API_KEY` | Optional | [CryptoPanic](https://cryptopanic.com/developers/api/) |
| `NEWSAPI_API_KEY` | Optional | [NewsAPI](https://newsapi.org/) |
| `ALPHA_VANTAGE_API_KEY` | Optional | [Alpha Vantage](https://www.alphavantage.co/support/) |
| `FRED_API_KEY` | Optional | [FRED](https://fred.stlouisfed.org/docs/api/api_key.html) |
| `TWITTER_BEARER_TOKEN` | Optional | [Twitter API v2](https://developer.twitter.com/) |
| `COINGECKO_API_KEY` | Optional | [CoinGecko](https://www.coingecko.com/en/api) |

All API keys are optional. Scripts gracefully skip sources without keys.

### 3. Enable GitHub Pages

1. Go to **Settings > Pages**
2. Source: **GitHub Actions**
3. The `deploy-pages.yml` workflow handles deployment automatically

### 4. Test Collectors Locally

```bash
cd scripts
pip install -r requirements.txt

# Set API keys (optional)
export NEWSAPI_API_KEY=your_key_here

# Run collectors
python collect_crypto_news.py
python collect_stock_news.py
python generate_market_summary.py
python collect_social_media.py
```

## GitHub Actions Workflows

| Workflow | Schedule | Description |
|----------|----------|-------------|
| `deploy-pages.yml` | On push to main | Build & deploy Jekyll site |
| `collect-crypto-news.yml` | `0 */6 * * *` | Collect crypto news |
| `collect-stock-news.yml` | `30 */6 * * *` | Collect stock news |
| `collect-social-media.yml` | `0 */12 * * *` | Collect social media posts |
| `generate-market-summary.yml` | `0 14 * * *` | Generate daily market summary |

Manual trigger: `gh workflow run <workflow-name>.yml`

## Deduplication

Posts are deduplicated using:
1. **SHA256 hash** of `normalize(title) + source + date[:10]`
2. **Fuzzy matching** via `difflib.SequenceMatcher` (>80% similarity threshold)
3. State persisted in `_state/*.json` files (30-day retention)

## Project Structure

```
investing/
├── _config.yml              # Jekyll config
├── _layouts/                # HTML layouts
├── _includes/               # Reusable components
├── _sass/                   # SCSS styles (dark theme)
├── _posts/                  # Auto-generated posts
├── _state/                  # Dedup state files
├── assets/                  # CSS, JS
├── pages/                   # Category pages
├── scripts/                 # Python collectors
│   ├── common/              # Shared modules
│   ├── collect_crypto_news.py
│   ├── collect_stock_news.py
│   ├── collect_social_media.py
│   └── generate_market_summary.py
├── .github/workflows/       # CI/CD
├── Gemfile                  # Ruby deps
└── README.md
```

## License

MIT
