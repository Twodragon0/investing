---
description: Investing Dragon collector, post, and workflow guardrails
globs: ["scripts/**/*.py", "_posts/**/*.md", ".github/workflows/**/*.yml"]
---

# Source Of Truth

- Primary repo workflow and guardrails live in `AGENTS.md`
- `CLAUDE.md` adds project context and command references
- `.opencode/README.md` defines OpenCode routing and safety baseline

# Collector And Script Guardrails

- Reuse `scripts/common/config.py` for `get_env()` and `setup_logging()`
- Reuse `scripts/common/dedup.py` and keep collectors deterministic and idempotent
- Prefer shared helpers in `scripts/common/` before adding new request or parsing logic
- Validate external payloads and URLs before processing
- Keep API timeout at 15 seconds and prefer certifi-first SSL handling
- Use Python logging only; do not add `print()` debugging
- Never hardcode secrets, tokens, cookies, or internal URLs

# Post And Image Guardrails

- Auto-generated posts belong in `_posts/YYYY-MM-DD-title.md`
- Preserve parser-safe front matter and existing post structure unless coordinated with `crypto`
- Verify required front matter fields for the target post type, permalink uniqueness, and image existence
- Keep Korean-first operational readability in generated summaries and briefings
- Generated image filenames must stay English-only under `assets/images/generated/`
- Never manually edit `_state/*.json`

# Workflow And Automation Guardrails

- Treat workflow and scheduler edits as production changes
- Pin GitHub Actions explicitly and keep schedules and concurrency intentional
- Run the target script once before enabling or changing cron-style automation
- Prefer existing helpers such as `scripts/opencode_git_pull.sh` for sync automation

# Verification Shortcuts

- Python collector or shared-module changes: `python3 -m ruff check scripts/`
- Jekyll or layout-facing changes: `bundle exec jekyll build`
- Post edits: verify front matter, image references, and parser-contract safety
