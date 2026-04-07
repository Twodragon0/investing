<!-- Parent: ../AGENTS.md -->

# AGENTS.md — tests/

Generated: 2026-04-08

## Purpose

pytest suite covering all common modules, collectors, generators, and utilities. Approximately 40 test files targeting full coverage of the `scripts/` layer.

## Test File Map

| File | Coverage target |
|------|----------------|
| `test_collectors.py` | All 13 collectors (integration) |
| `test_collector_config.py` | `common/collector_config.py` |
| `test_collector_integration.py` | Cross-collector integration flows |
| `test_collector_metrics.py` | `common/collector_metrics.py` |
| `test_base_collector.py` | `common/base_collector.py` abstract base |
| `test_dedup.py` | SHA256 + fuzzy dedup engine |
| `test_enrichment.py` / `test_enrichment_utils.py` | URL extraction, boilerplate filter |
| `test_summarizer.py` / `test_summarizer_extended.py` / `test_summarizer_markdown.py` | Summarizer variants |
| `test_rss_fetcher.py` / `test_rss_fetcher_extended.py` | RSS fetch and description extraction |
| `test_post_generator.py` | Front matter and markdown generation |
| `test_image_generator.py` | Pillow-based image generation |
| `test_formatters.py` | Post body formatters |
| `test_translator.py` | Korean translation helpers |
| `test_crypto_api.py` | CoinGecko / CryptoPanic wrappers |
| `test_fmp_api.py` | FMP API wrapper |
| `test_blockchain_api.py` | On-chain data API wrappers |
| `test_config.py` | `common/config.py` env loading |
| `test_utils.py` | `common/utils.py` |
| `test_markdown_utils.py` | Markdown helpers |
| `test_entity_extractor.py` | Named entity extraction |
| `test_signal_composer.py` | Signal aggregation |
| `test_signal_tracker.py` | Signal state persistence |
| `test_bettafish_analyzer.py` | Pattern analysis |
| `test_mindspider.py` | Web crawl and extraction |
| `test_browser.py` | Headless browser fetch |
| `test_worldmonitor_utils.py` | WorldMonitor parsing |
| `test_core_modules.py` | Core module sanity checks |
| `test_collect_fmp_calendar.py` | FMP calendar collector |
| `test_collect_geopolitical.py` | Geopolitical collector |
| `test_collect_market_indicators.py` | Market indicators collector |
| `test_generate_weekly_digest.py` | Weekly digest generator |
| `test_respond_ai_mentions.py` | Slack AI mention responder |
| `test_reports_page.py` | Reports page rendering |
| `test_verify_rendered_posts.py` | Rendered post verification |
| `conftest.py` | Shared fixtures and session setup |
| `fixtures/` | Test fixture data files |

## For AI Agents

### Running Tests

```bash
python3 -m pytest tests/                        # full suite
python3 -m pytest tests/test_dedup.py -v        # single file
python3 -m pytest tests/ -k "collector" -v      # keyword filter
python3 -m pytest tests/ --tb=short             # short tracebacks
```

### Conventions

- Mock all external HTTP calls — no live API requests in tests.
- Tests must be independent; no shared mutable state between test functions.
- New collectors require a corresponding test file before the collector is merged.
- Use fixtures from `conftest.py` for common setup (config, temp dirs, state files).
- Test both happy path and failure/degradation paths for every collector.
- Idempotency: running the same collector twice must not produce duplicate posts.

### Adding Tests for a New Collector

1. Create `tests/test_collect_<name>.py`.
2. Mock HTTP responses using `unittest.mock` or `pytest-mock`.
3. Verify: post count, front matter fields, dedup state update, metrics registration.
4. Run `python3 -m pytest tests/test_collect_<name>.py -v` before submitting.
