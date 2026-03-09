---
name: add-data-source
description: Add a new data source and collector to the investing news aggregation platform
---

# Add Data Source

## Steps
1. Research the target data source API
2. Create collector script in `scripts/` following existing patterns
3. Add required API keys to `.env.example`
4. Create GitHub Actions workflow for scheduled collection
5. Define Jekyll post template with proper frontmatter
6. Test collector locally: `python scripts/<collector>.py`
7. Verify generated posts render correctly: `bundle exec jekyll build`
8. Add error handling and rate limiting
