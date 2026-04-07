# Investing Agent Guide

This repository is the data intelligence layer for DragonQuant. It collects market data, generates structured posts, and feeds `_posts/*.md` into the downstream `crypto` parser.

## Mission

- Keep collectors deterministic, idempotent, and resilient when data sources fail.
- Keep generated posts and images compatible with the Jekyll site and the downstream parser contract.
- Prefer small, reversible changes with explicit local verification.

## Source Of Truth

- Use this file for repository-specific agent workflow and guardrails.
- Treat `CLAUDE.md` as supporting project context and legacy team notes.
- Treat `.opencode/README.md` as the baseline for OpenCode routing, skills, and safety hooks.

## Repository Map

### Scripts

- `scripts/collect_*.py` — 12 source collectors:
  - `collect_crypto_news.py` — crypto news via RSS and CryptoPanic
  - `collect_stock_news.py` — stock news via RSS and NewsAPI
  - `collect_social_media.py` — social signals (Twitter/X)
  - `collect_regulatory.py` — regulatory filings and alerts
  - `collect_political_trades.py` — US congressional trades
  - `collect_coinmarketcap.py` — CMC token data
  - `collect_worldmonitor_news.py` — geopolitical and world news
  - `collect_defi_llama.py` — DeFi protocol TVL and metrics
  - `collect_defi_yields.py` — DeFi yield data
  - `collect_fmp_calendar.py` — earnings and economic calendar (FMP)
  - `collect_market_indicators.py` — macro indicators (FRED, Alpha Vantage)
  - `collect_geopolitical.py` — geopolitical risk events
  - `collect_blockchain.py` — on-chain blockchain metrics

- `scripts/generate_*.py` — 5 content generators:
  - `generate_daily_summary.py` — daily cross-asset summary post
  - `generate_market_summary.py` — intraday market summary post
  - `generate_weekly_digest.py` — weekly digest post
  - `generate_og_images.py` — OG images for posts
  - `generate_ops_10am_digest.py` — operational morning digest

- `scripts/common/` — 25 shared modules:
  - `config.py` — env loading (`get_env()`), logging (`setup_logging()`), `REQUEST_TIMEOUT`
  - `dedup.py` — SHA256 + fuzzy dedup engine (>80% threshold)
  - `post_generator.py` — front matter and markdown post creation
  - `image_generator.py` — Pillow-based OG image generation (Korean-safe)
  - `rss_fetcher.py` — RSS fetch with 1000-char description extraction
  - `enrichment.py` — URL content extraction, boilerplate filter, synthetic description
  - `summarizer.py` — LLM-based summarization, `_GENERIC_DESC_PATTERNS`
  - `formatters.py` — post body formatters and templates
  - `translator.py` — Korean translation helpers
  - `crypto_api.py` — CoinGecko and CryptoPanic API wrappers
  - `fmp_api.py` — Financial Modeling Prep API wrapper
  - `blockchain_api.py` — on-chain data API wrappers
  - `worldmonitor_utils.py` — WorldMonitor-specific parsing
  - `collector_metrics.py` — per-run metrics collection and reporting
  - `collector_config.py` — per-collector configuration registry
  - `base_collector.py` — abstract base class for all collectors
  - `markdown_utils.py` — markdown helpers and sanitizers
  - `browser.py` — headless browser fetch (Playwright/requests fallback)
  - `mindspider.py` — web crawl and content extraction
  - `entity_extractor.py` — named entity extraction from text
  - `signal_composer.py` — signal aggregation and scoring
  - `signal_tracker.py` — persistent signal tracking
  - `bettafish_analyzer.py` — pattern analysis utility
  - `utils.py` — general utility functions
  - `__init__.py`

- `scripts/respond_ai_mentions.py` — Slack AI mention responder
- `scripts/continuous_improvement_loop.py` — automated improvement orchestration
- `scripts/check_description_quality.py` — post description quality measurement (CI)
- `scripts/fix_post_descriptions.py` — bulk backfill of post descriptions
- `scripts/backfill_images.py` — image backfill for existing posts
- `scripts/backfill_post_summaries.py` — summary backfill for existing posts
- `scripts/improve_existing_posts.py` — post quality improvement runner
- `scripts/enrich_existing_posts.py` — enrichment backfill runner
- `scripts/verify_post_quality.py` — post quality verification
- `scripts/smoke_test_rendered_pages.py` — smoke tests on rendered HTML
- `scripts/validate_collector_summary_contract.py` — contract validation between collectors and summary generator
- `scripts/server_morning_autopost.sh` — server-side 09:10 KST autopost runner
- `scripts/install_server_morning_cron.sh` — install server morning cron
- `scripts/opencode_git_pull.sh` — central sync pull helper

### Site And Content

- `_posts/` — generated markdown posts consumed here and by `crypto`
- `_state/` — dedup and runtime state JSON files; do not edit manually
- `_layouts/` — Jekyll layout templates
- `_includes/` — Jekyll include partials
- `_sass/` — SCSS stylesheets (minima dark finance theme)
- `_data/` — Jekyll data files
- `assets/images/generated/` — generated OG and briefing images; keep filenames English-only
- `pages/` — 14 category landing pages (crypto-news, stock-news, defi, blockchain, market-analysis, political-trades, regulatory-news, social-media, worldmonitor, crypto-journal, stock-journal, security-alerts, reports, about)

### Automation

- `.github/workflows/` — 35 automation workflows (see Workflow Inventory below)
- `.github/actions/python-collect/` — reusable composite action for Python collector runs
- `.github/actions/resolve-slack-config/` — reusable action for Slack channel resolution

### Tests

- `tests/` — pytest suite covering all common modules and collectors (~40 test files)

### Docs

- `docs/architecture.md` — system architecture overview
- `docs/data-sources.md` — data source registry and status
- `docs/platform-architecture.md` — platform-level design
- `docs/continuous-improvement-priority.md` — improvement backlog priorities
- `docs/refactoring-plan-base-collector.md` — base collector refactor plan
- `docs/trading-journal-improvements.md` — trading journal feature roadmap
- `docs/business-plan/` — business planning documents

## Workflow Inventory (35 Workflows)

| Workflow | Purpose |
|----------|---------|
| `collect-crypto-news.yml` | Crypto news collection |
| `collect-stock-news.yml` | Stock news collection |
| `collect-social-media.yml` | Social media signals |
| `collect-regulatory.yml` | Regulatory filings |
| `collect-political-trades.yml` | Congressional trade data |
| `collect-coinmarketcap.yml` | CMC token data |
| `collect-worldmonitor-news.yml` | World news collection |
| `collect-defi-llama.yml` | DeFi TVL metrics |
| `collect-defi-yields.yml` | DeFi yield data |
| `collect-fmp-calendar.yml` | Earnings/economic calendar |
| `collect-market-indicators.yml` | Macro indicators |
| `collect-geopolitical.yml` | Geopolitical events |
| `collect-blockchain.yml` | On-chain blockchain data |
| `generate-daily-summary.yml` | Daily summary (manual dispatch) |
| `generate-market-summary.yml` | Market summary (manual dispatch) |
| `generate-journal-og-images.yml` | Journal OG image generation |
| `weekly-digest.yml` | Weekly digest post |
| `ops-10am-digest.yml` | Morning operational digest |
| `continuous-improvement-loop.yml` | Hourly improvement loop |
| `backfill-post-summaries.yml` | Summary backfill automation |
| `description-quality-check.yml` | Post description quality CI |
| `post-quality.yml` | Post quality gates |
| `code-quality.yml` | Ruff lint + type checks |
| `dependency-check.yml` | pip-audit dependency scanning |
| `security-scan.yml` | Security vulnerability scan |
| `site-health-check.yml` | Jekyll site health verification |
| `lighthouse-ci.yml` | Lighthouse performance CI |
| `reports-e2e.yml` | Reports page E2E tests |
| `deploy-pages.yml` | Jekyll site deployment |
| `cleanup-old-images.yml` | 30-day image cleanup |
| `push-folder-info-to-slack.yml` | Slack folder info push |
| `respond-ai-mentions.yml` | Slack AI mention handler |
| `coverage-comment.yml` | PR coverage comment |
| `dependabot-auto-merge.yml` | Dependabot auto-merge |
| `classify-workflow-failures.yml` | Workflow failure classification |

## Operating Rules

- Use shared configuration through `scripts/common/config.py` for env loading and logging.
- Preserve front matter schema and post structure unless downstream parser updates are coordinated.
- Never hardcode secrets, tokens, cookies, or internal URLs.
- Never manually edit `_state/*.json`.
- Treat scheduler and workflow changes as production changes; verify one-shot execution before automation.
- Keep Korean-first operational readability in posts and summaries.
- All collectors must extend `scripts/common/base_collector.py` and register metrics via `collector_metrics.py`.

## Agent Routing

### Lead Orchestrator
- Scope: cross-cutting tasks, planning, verification, and integration.
- Default behavior: inspect repository state first, keep edits focused, verify modified scope before handoff.

### Data Collector Lead
- Scope: `scripts/collect_*.py`, `scripts/common/base_collector.py`, `scripts/common/rss_fetcher.py`, `scripts/common/crypto_api.py`, `scripts/common/fmp_api.py`, `scripts/common/blockchain_api.py`, source adapters.
- Focus: source reliability, graceful degradation, dedup quality, deterministic output.
- Guardrails:
  - Reuse shared helpers before adding new request or parsing logic.
  - Validate external payloads and URLs before processing.
  - Prefer cache-first or low-cost fetch patterns when possible.
  - All new collectors must subclass `base_collector.py`.

### Content Pipeline Engineer
- Scope: `scripts/generate_*.py`, `scripts/common/formatters.py`, `scripts/common/summarizer.py`, `scripts/common/image_generator.py`, `scripts/common/post_generator.py`, post-quality tooling.
- Focus: stable summaries, parser-safe front matter, consistent markdown structure, image completeness.
- Guardrails:
  - Keep post schema stable for `crypto` consumption.
  - Ensure image references point to real generated assets.
  - Maintain clear separation between facts, interpretation, and trading-journal notes.

### Frontend And Site Engineer
- Scope: `_layouts/`, `_includes/`, `_sass/`, `pages/`, static assets.
- Focus: responsive finance UI, build stability, category navigation, OG and metadata integrity.
- Guardrails:
  - Preserve existing visual language unless redesign is explicitly requested.
  - Avoid introducing unused CSS or JS.
  - Confirm `bundle exec jekyll build` after site-facing changes.

### Workflow Automation Engineer
- Scope: `.github/workflows/`, `.github/actions/`, cron scripts, operational automation.
- Focus: idempotent automation, least-privilege secrets, retries, low-noise alerting.
- Guardrails:
  - Pin actions explicitly.
  - Keep concurrency and schedules intentional.
  - Prefer existing helper scripts such as `scripts/opencode_git_pull.sh`.

### Security And QA Reviewer
- Scope: changed code, scripts, workflow config, generated post compliance.
- Focus: secret handling, safe logging, outbound request safety, quality gates.
- Guardrails:
  - Never log API keys or tokens.
  - Run relevant checks for touched scope.
  - Flag parser-contract or publication risks before merge.

## Project Agents (`.claude/agents/`)

| Agent File | Model | Role |
|-----------|-------|------|
| `investing-lead.md` | opus | 프로젝트 리드, 전체 조율, 작업 분배 |
| `architect.md` | opus | 수집 파이프라인 설계, Jekyll 통합 아키텍처 |
| `data-pipeline-lead.md` | sonnet | 수집기 개발 리드, API 연동 |
| `collector-reviewer.md` | sonnet | 수집기 코드 리뷰, 중복 방지 검증 |
| `content-pipeline.md` | sonnet | 요약/분석 생성, 이미지 생성 |
| `workflow-optimizer.md` | sonnet | GitHub Actions 워크플로우 최적화 |
| `workflow-debugger.md` | sonnet | CI/워크플로우 디버깅 |
| `jekyll-checker.md` | haiku | Jekyll 빌드 검증, 템플릿/스타일 |
| `test-engineer.md` | sonnet | 수집기 테스트, dedup 검증, 멱등성 |

### Multi-Agent Workflow Patterns

- **데이터 소스 추가**: investing-lead → data-pipeline-lead + workflow-optimizer + test-engineer (병렬) → collector-reviewer → architect
- **일일 요약 파이프라인**: content-pipeline → jekyll-checker → test-engineer → workflow-optimizer
- **사이트 리디자인**: architect → jekyll-checker + content-pipeline (병렬) → test-engineer
- **버그 조사**: workflow-debugger → data-pipeline-lead → test-engineer → investing-lead

## Preferred Skills

- `add-data-source`: new collector or source integration.
- `new-collector`: creating a new collection script.
- `debug-workflow`: failing GitHub Actions or automation issues.
- `site-health-check`: Jekyll site verification.
- `lint-fix`: ruff-driven Python cleanup.
- `fix-issue`: issue-oriented debugging and fixes.
- `post-validation`: pre-publication post and image checks.
- `security-review`: focused review for changed code and scripts.
- `cost-audit`: API or AI usage efficiency review.
- `deep-research`: deep codebase analysis and investigation.

## Verification Matrix

- Python collector or common-module changes: `python3 -m ruff check scripts/`
- Test suite: `python3 -m pytest tests/`
- Jekyll/site/layout changes: `bundle exec jekyll build`
- Morning automation changes: run the target script once before enabling cron.
- Post additions or edits: verify front matter, permalink uniqueness, image existence, and relevant build success.
- Workflow changes: inspect YAML carefully and verify referenced scripts or paths still exist.
- Description quality: `python scripts/check_description_quality.py --days 7`

## Post And Image Guardrails

- `_posts/*.md` must keep required front matter fields and parser-safe structure.
- Trading journal posts should keep numeric summary fields aligned with visible body numbers.
- Generated image filenames should stay English-only and live under `assets/images/generated/`.
- If a post references an OG image, generate or verify that asset before commit.
- Breaking schema changes require synchronized updates in the `crypto` repository.
- Description quality target: real content ratio > 90%; boilerplate > 50% fails CI.

## Description Quality Pipeline

Manages description quality across all collected posts:

```
RSS/API → enrichment → translation → post_generator
          ↓
    1. URL content extraction (og:desc → readability → bs4 → paragraph)
    2. Boilerplate filter (_is_site_boilerplate)
    3. Title-duplicate detection (_is_desc_duplicate_of_title)
    4. Synthetic description generation (fact-based, _synthetic flag)
    5. Concurrent re-fetch (80 items, title-dup priority)
```

Key files: `scripts/common/enrichment.py`, `scripts/common/rss_fetcher.py`, `scripts/common/summarizer.py`, `scripts/check_description_quality.py`, `scripts/fix_post_descriptions.py`.

## Delivery Checklist

- Inspect current git state before edits.
- Limit changes to the requested scope.
- Verify modified files with relevant local checks.
- Summarize risks, follow-ups, and any blocked remote operations.
