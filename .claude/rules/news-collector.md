---
description: Investing Dragon news collector and Jekyll site rules
globs: ["scripts/**/*.py", "_posts/**/*.md", ".github/workflows/**/*.yml"]
---

# Python Script Conventions

- All scripts MUST use `scripts/common/config.py` (`get_env()`, `setup_logging()`)
- All collectors use `scripts/common/dedup.py` for duplicate prevention
- API timeout: 15 seconds
- SSL: certifi-first, `DISABLE_SSL_VERIFY` env override available
- Logging: Python logging module only, never print()

# Post Format

- Auto-generated posts: `_posts/YYYY-MM-DD-title.md`
- Front matter required: title, date, categories, tags, source
- State tracking: `_state/*.json` (SHA256 hash + fuzzy match >80%)
- NEVER manually edit `_state/*.json` files

# Jekyll

- `bundle exec jekyll serve` for local dev
- Theme: minima (dark finance)
- Auto-generated images: `assets/images/generated/` (cleaned after 30 days)

# Collector Architecture

- 11 collectors in `scripts/collect_*.py`
- 5 generators in `scripts/generate_*.py`
- 17 shared modules in `scripts/common/`
- Slack mention handler: `scripts/respond_ai_mentions.py`

# Workflows

- 25 GitHub Actions workflows
- 2 reusable actions in `.github/actions/`
