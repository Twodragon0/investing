# AGENTS.md — Investing Dragon (DragonQuant Data Intelligence)

Generated: 2026-04-08

## Purpose

This repository is the data intelligence layer of the DragonQuant platform. It collects market data from 20+ sources across 13 collectors, generates structured Jekyll posts, and feeds `_posts/*.md` into the downstream `crypto` quant trading engine via `StructuredPostParser`.

Live site: https://investing.2twodragon.com

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Site | Jekyll 4.x (minima dark finance theme), GitHub Pages |
| Scripting | Python 3.10+ |
| CI/CD | GitHub Actions (35 workflows) |
| Image generation | Pillow, matplotlib |
| Linting | ruff, basedpyright |
| Testing | pytest |
| Notifications | Slack (Bot API) |
| Dependencies | `scripts/requirements.txt`, `Gemfile` |

## Directory Structure

```
investing/
├── scripts/
│   ├── common/             # 25 shared modules (config, dedup, enrichment, ...)
│   ├── collect_*.py        # 13 data collectors
│   ├── generate_*.py       # 5 content generators + OG image generator
│   ├── check_*.py          # quality measurement utilities
│   ├── fix_*.py            # post repair/backfill utilities
│   └── requirements.txt
├── tests/                  # pytest suite (~40 test files)
├── _posts/                 # auto-generated Jekyll posts (consumed by crypto repo)
├── _state/                 # dedup state JSON — do not edit manually
├── _layouts/               # Jekyll HTML layouts
├── _includes/              # Jekyll partials
├── _sass/                  # SCSS (dark finance theme)
├── _data/                  # Jekyll data files
├── assets/images/generated/ # OG images and briefing charts (30-day retention)
├── pages/                  # 14 category landing pages
├── docs/                   # Architecture, data sources, improvement backlog
├── .github/
│   ├── workflows/          # 35 automation workflows
│   └── actions/            # 2 reusable actions (python-collect, resolve-slack-config)
├── _config.yml             # Jekyll site configuration
├── Gemfile                 # Ruby dependencies
├── pyproject.toml          # Python project config
└── mise.toml               # Runtime version pinning
```

## Quick Start

```bash
# Jekyll local preview
bundle install
bundle exec jekyll serve        # http://localhost:4000

# Python collectors (graceful degradation without API keys)
pip install -r scripts/requirements.txt
python scripts/collect_crypto_news.py
python scripts/collect_stock_news.py

# Content generators
python scripts/generate_daily_summary.py
python scripts/generate_market_summary.py

# Code quality (CI Code Quality와 동일 — lint + format)
python3 -m ruff check scripts/ tests/
python3 -m ruff format --check scripts/ tests/

# Full test suite
python3 -m pytest tests/

# Description quality check
python scripts/check_description_quality.py --days 7

# Server morning cron setup (09:10 KST)
bash scripts/install_server_morning_cron.sh
```

## For AI Agents

### Source of Truth

- This file: repository-specific guardrails and routing.
- `CLAUDE.md`: project context, team role definitions, environment variables.
- `docs/architecture.md`: system architecture deep-dive.

### Operating Rules

- All collectors must subclass `scripts/common/base_collector.py` and register metrics via `collector_metrics.py`.
- Use `scripts/common/config.py` (`get_env()`, `setup_logging()`) for env access and logging — never `print()`.
- Use `scripts/common/dedup.py` for deduplication; never bypass the SHA256 + fuzzy (>80%) pipeline.
- Never hardcode secrets, tokens, or internal URLs.
- Never manually edit `_state/*.json`.
- Keep post front matter schema stable — breaking changes require coordinated updates in the `crypto` repository.
- Generated image filenames must be English-only and live under `assets/images/generated/`.
- Description quality target: real content ratio > 90%; boilerplate > 50% fails CI.

### Verification Matrix

| Change scope | Verification command |
|-------------|---------------------|
| Python collector or common module | `python3 -m ruff check scripts/ tests/ && python3 -m ruff format --check scripts/ tests/` |
| Any Python change | `python3 -m pytest tests/` |
| Jekyll / site / layout | `bundle exec jekyll build` |
| Post additions or edits | Check front matter, permalink uniqueness, image existence |
| Workflow changes | Inspect YAML; verify referenced scripts/paths exist |
| Description quality | `python scripts/check_description_quality.py --days 7` |
| Morning automation | Run target script once before enabling cron |

### Agent Routing

| Agent | Model | Scope |
|-------|-------|-------|
| `investing-lead` | opus | Cross-cutting orchestration, planning, verification |
| `architect` | opus | Collection pipeline design, Jekyll integration |
| `data-pipeline-lead` | sonnet | `collect_*.py`, source adapters, dedup quality |
| `collector-reviewer` | sonnet | Collector code review, dedup validation |
| `content-pipeline` | sonnet | `generate_*.py`, summarizer, image generator |
| `workflow-optimizer` | sonnet | GitHub Actions workflows, cron scheduling |
| `workflow-debugger` | sonnet | CI/workflow failure analysis |
| `jekyll-checker` | haiku | Jekyll build, templates, SCSS |
| `test-engineer` | sonnet | pytest suite, idempotency, collector mocking |

### Multi-Agent Patterns

- **New data source**: investing-lead → data-pipeline-lead + workflow-optimizer + test-engineer (parallel) → collector-reviewer → architect
- **Daily summary pipeline**: content-pipeline → jekyll-checker → test-engineer → workflow-optimizer
- **Site redesign**: architect → jekyll-checker + content-pipeline (parallel) → test-engineer
- **Bug investigation**: workflow-debugger → data-pipeline-lead → test-engineer → investing-lead

### Preferred Skills

`add-data-source`, `new-collector`, `debug-workflow`, `site-health-check`, `lint-fix`, `fix-issue`, `post-validation`, `security-review`, `cost-audit`, `deep-research`

## Dependencies

### Python (key packages — see `scripts/requirements.txt` for full list)

- `requests`, `feedparser` — HTTP and RSS fetching
- `Pillow`, `matplotlib` — image generation
- `vaderSentiment` — sentiment analysis
- `difflib` (stdlib) — fuzzy dedup
- `pytest`, `ruff` — testing and linting

### Ruby (see `Gemfile`)

- `jekyll ~> 4.x`, `minima` — static site generation

### External APIs (optional — graceful degradation without keys)

`CRYPTOPANIC_API_KEY`, `NEWSAPI_API_KEY`, `ALPHA_VANTAGE_API_KEY`, `FRED_API_KEY`, `TWITTER_BEARER_TOKEN`, `CMC_API_KEY`, `COINGECKO_API_KEY`, `SLACK_BOT_TOKEN`
