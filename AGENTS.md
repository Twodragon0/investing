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

- `scripts/collect_*.py`: source collectors for crypto, stocks, regulation, political trades, and related feeds.
- `scripts/generate_*.py`: daily/weekly summaries, OG image generation, and operational digests.
- `scripts/common/`: shared config, dedup, enrichment, formatting, translation, image, and API helpers.
- `_posts/`: generated markdown posts consumed here and by `crypto`.
- `_state/`: dedup and runtime state files; do not edit manually.
- `assets/images/generated/`: generated OG and briefing images; keep filenames English-only.
- `.github/workflows/`: automation, scheduling, quality gates, and deployment.

## Operating Rules

- Use shared configuration through `scripts/common/config.py` for env loading and logging.
- Preserve front matter schema and post structure unless downstream parser updates are coordinated.
- Never hardcode secrets, tokens, cookies, or internal URLs.
- Never manually edit `_state/*.json`.
- Treat scheduler and workflow changes as production changes; verify one-shot execution before automation.
- Keep Korean-first operational readability in posts and summaries.

## Agent Routing

### Lead Orchestrator
- Scope: cross-cutting tasks, planning, verification, and integration.
- Default behavior: inspect repository state first, keep edits focused, verify modified scope before handoff.

### Data Collector Lead
- Scope: `scripts/collect_*.py`, `scripts/common/rss_fetcher.py`, `scripts/common/crypto_api.py`, source adapters.
- Focus: source reliability, graceful degradation, dedup quality, deterministic output.
- Guardrails:
  - Reuse shared helpers before adding new request or parsing logic.
  - Validate external payloads and URLs before processing.
  - Prefer cache-first or low-cost fetch patterns when possible.

### Content Pipeline Engineer
- Scope: `scripts/generate_*.py`, formatters, summarizers, image generation, post-quality tooling.
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

## Verification Matrix

- Python collector or common-module changes: `python3 -m ruff check scripts/`
- Jekyll/site/layout changes: `bundle exec jekyll build`
- Morning automation changes: run the target script once before enabling cron.
- Post additions or edits: verify front matter, permalink uniqueness, image existence, and relevant build success.
- Workflow changes: inspect YAML carefully and verify referenced scripts or paths still exist.

## Post And Image Guardrails

- `_posts/*.md` must keep required front matter fields and parser-safe structure.
- Trading journal posts should keep numeric summary fields aligned with visible body numbers.
- Generated image filenames should stay English-only and live under `assets/images/generated/`.
- If a post references an OG image, generate or verify that asset before commit.
- Breaking schema changes require synchronized updates in the `crypto` repository.

## Delivery Checklist

- Inspect current git state before edits.
- Limit changes to the requested scope.
- Verify modified files with relevant local checks.
- Summarize risks, follow-ups, and any blocked remote operations.
