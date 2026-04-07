<!-- Parent: ../AGENTS.md -->

# AGENTS.md — scripts/

Generated: 2026-04-08

## Purpose

Python automation layer: 13 data collectors, 5 content generators, shared common modules, and maintenance utilities. All scripts run via GitHub Actions or server cron.

## Directory Layout

```
scripts/
├── common/                     # 25 shared modules
│   ├── config.py               # get_env(), setup_logging(), REQUEST_TIMEOUT
│   ├── dedup.py                # SHA256 + fuzzy dedup engine (>80% threshold)
│   ├── base_collector.py       # abstract base class for all collectors
│   ├── post_generator.py       # front matter and markdown post creation
│   ├── image_generator/        # Pillow-based OG/chart image generation
│   ├── rss_fetcher.py          # RSS fetch with 1000-char description extraction
│   ├── enrichment.py           # URL extraction, boilerplate filter, synthetic desc
│   ├── summarizer.py           # keyword-based summarization, _GENERIC_DESC_PATTERNS
│   ├── formatters.py           # post body formatters and templates
│   ├── translator.py           # Korean translation helpers
│   ├── crypto_api.py           # CoinGecko and CryptoPanic wrappers
│   ├── fmp_api.py              # Financial Modeling Prep API wrapper
│   ├── blockchain_api.py       # on-chain data API wrappers
│   ├── worldmonitor_utils.py   # WorldMonitor-specific parsing
│   ├── collector_metrics.py    # per-run metrics collection and reporting
│   ├── collector_config.py     # per-collector configuration registry
│   ├── markdown_utils.py       # markdown helpers and sanitizers
│   ├── browser.py              # headless browser fetch (Playwright/requests fallback)
│   ├── mindspider.py           # web crawl and content extraction
│   ├── entity_extractor.py     # named entity extraction
│   ├── signal_composer.py      # signal aggregation and scoring
│   ├── signal_tracker.py       # persistent signal state
│   ├── bettafish_analyzer.py   # pattern analysis utility
│   └── utils.py                # general utilities
├── collect_crypto_news.py      # CryptoPanic, NewsAPI, Google News, exchange notices
├── collect_stock_news.py       # NewsAPI, Yahoo Finance, yfinance, KRX, Alpha Vantage
├── collect_social_media.py     # Twitter/X API v2, Telegram channels
├── collect_regulatory.py       # SEC, CFTC, Fed, FSC, FSA, MAS, ESMA, FCA (RSS)
├── collect_political_trades.py # US congressional trades, SEC EDGAR
├── collect_coinmarketcap.py    # CoinMarketCap API, CoinGecko fallback
├── collect_worldmonitor_news.py # geopolitical and energy (WorldMonitor RSS)
├── collect_defi_llama.py       # DeFi Llama protocol/chain TVL
├── collect_defi_yields.py      # DeFi yield data
├── collect_fmp_calendar.py     # FMP earnings and economic calendar
├── collect_market_indicators.py # CNN Fear & Greed, VIX/DXY, market breadth
├── collect_geopolitical.py     # Polymarket geopolitical risk data
├── collect_blockchain.py       # on-chain blockchain metrics
├── generate_daily_summary.py   # daily cross-asset summary post
├── generate_market_summary.py  # intraday market summary + visualizations
├── generate_weekly_digest.py   # weekly digest post
├── generate_og_images.py       # OG image generation for posts
├── generate_ops_10am_digest.py # morning operational digest
├── check_description_quality.py # quality measurement (CI integration)
├── fix_post_descriptions.py    # bulk description backfill
├── backfill_images.py          # image backfill for existing posts
├── backfill_post_summaries.py  # summary backfill
├── improve_existing_posts.py   # post quality improvement runner
├── enrich_existing_posts.py    # enrichment backfill
├── verify_post_quality.py      # post quality verification
├── smoke_test_rendered_pages.py # smoke tests on rendered HTML
├── validate_collector_summary_contract.py # contract validation
├── respond_ai_mentions.py      # Slack AI mention responder
├── continuous_improvement_loop.py # automated improvement orchestration
├── server_morning_autopost.sh  # 09:10 KST server-side autopost runner
├── install_server_morning_cron.sh # cron installer for server morning autopost
└── requirements.txt
```

## For AI Agents

### Mandatory Conventions

- All new collectors must subclass `base_collector.py` and register metrics via `collector_metrics.py`.
- Use `get_env()` and `setup_logging()` from `common/config.py` — never use `os.environ[]` directly or `print()`.
- All collectors must call `dedup.py` before writing posts; the SHA256 + fuzzy pipeline is not optional.
- API timeout: 15 seconds (`REQUEST_TIMEOUT` constant from `config.py`).
- SSL: use `certifi`; disable only via `DISABLE_SSL_VERIFY` env var.
- Do not add new request or parsing logic before checking existing helpers in `common/`.

### Description Quality Pipeline

```
RSS/API → enrichment.py → translator.py → post_generator.py
              |
    1. URL content extraction (og:desc → readability → bs4 → paragraph)
    2. Boilerplate filter (_is_site_boilerplate)
    3. Title-duplicate detection (_is_desc_duplicate_of_title)
    4. Synthetic description generation (_synthetic flag)
    5. Concurrent re-fetch (80 items, title-dup priority)
```

Quality targets: real content > 90%; boilerplate > 50% fails CI.

### Verification

```bash
python3 -m ruff check scripts/          # lint all scripts
python3 -m pytest tests/                # full test suite
python scripts/check_description_quality.py --days 7
```
