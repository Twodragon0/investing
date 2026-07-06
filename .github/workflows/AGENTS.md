<!-- Parent: ../../AGENTS.md -->

# AGENTS.md — .github/workflows/

Generated: 2026-04-08

## Purpose

35 GitHub Actions workflows covering data collection, content generation, deployment, quality gates, and operational automation for the DragonQuant data intelligence layer.

## Workflow Inventory

### Data Collection (13)

| Workflow | Schedule (UTC) | Script |
|----------|---------------|--------|
| `collect-crypto-news.yml` | Every 6h :00 | `collect_crypto_news.py` |
| `collect-coinmarketcap.yml` | Every 6h :15 | `collect_coinmarketcap.py` |
| `collect-stock-news.yml` | Every 6h :30 | `collect_stock_news.py` |
| `collect-defi-llama.yml` | Every 6h :45 | `collect_defi_llama.py` |
| `collect-defi-yields.yml` | Every 12h | `collect_defi_yields.py` |
| `collect-social-media.yml` | Every 12h | `collect_social_media.py` |
| `collect-regulatory.yml` | Every 12h | `collect_regulatory.py` |
| `collect-political-trades.yml` | Daily | `collect_political_trades.py` |
| `collect-worldmonitor-news.yml` | Daily | `collect_worldmonitor_news.py` |
| `collect-fmp-calendar.yml` | Every 12h :00 | `collect_fmp_calendar.py` |
| `collect-market-indicators.yml` | Weekdays 14:00/22:00 | `collect_market_indicators.py` |
| `collect-geopolitical.yml` | Every 12h | `collect_geopolitical.py` |
| `collect-blockchain.yml` | Every 12h | `collect_blockchain.py` |

### Content Generation (5)

| Workflow | Schedule | Dispatch |
|----------|---------|---------|
| `generate-daily-summary.yml` | — | `workflow_dispatch` only |
| `generate-journal-og-images.yml` | Daily | — |
| `weekly-digest.yml` | Weekly Sunday | — |
| `ops-10am-digest.yml` | Daily | — |

### Quality & CI (7)

| Workflow | Trigger |
|----------|--------|
| `code-quality.yml` | Push, PR, weekly |
| `dependency-check.yml` | Weekly Monday |
| `security-scan.yml` | Push, PR |
| `description-quality-check.yml` | Daily, push |
| `post-quality.yml` | Push, PR |
| `lighthouse-ci.yml` | Push to main |
| `reports-e2e.yml` | Push to main |

### Deployment & Operations (10)

| Workflow | Trigger |
|----------|--------|
| `deploy-pages.yml` | Push to main |
| `site-health-check.yml` | Daily |
| `cleanup-old-images.yml` | Weekly Sunday |
| `backfill-post-summaries.yml` | Daily |
| `continuous-improvement-loop.yml` | Hourly |
| `push-folder-info-to-slack.yml` | Daily |
| `respond-ai-mentions.yml` | Every 30 minutes |
| `coverage-comment.yml` | PR |
| `dependabot-auto-merge.yml` | Dependabot PRs |
| `classify-workflow-failures.yml` | Workflow failure |

## For AI Agents

### Guardrails

- Pin all third-party actions to a specific SHA, not a floating tag.
- All collection workflows must use the `collect-data` concurrency group to prevent parallel state corruption.
- Never store secrets in workflow YAML — reference only via `${{ secrets.NAME }}`.
- Prefer the reusable `python-collect` composite action for Python collector steps.
- Use `resolve-slack-config` action for Slack channel resolution.
- Verify that any referenced script path exists before committing a workflow change.
- Treat workflow changes as production changes — test with `workflow_dispatch` before enabling cron.

### Reusable Actions

- `.github/actions/python-collect/` — composite action for Python collector runs (setup, install, execute, commit).
- `.github/actions/resolve-slack-config/` — resolves Slack channel ID from repo context.

### Adding a New Collection Workflow

1. Copy an existing collector workflow as a template.
2. Set a unique cron offset within the `collect-data` concurrency group.
3. Reference `python-collect` composite action.
4. Add required secrets to the workflow and document them in `README.md`.
5. Run once via `workflow_dispatch` before enabling the schedule.
