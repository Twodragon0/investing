---
name: site-health-check
description: Run health check on the investing Jekyll site
---

# Site Health Check

## Steps
1. Build site: `bundle exec jekyll build`
2. Check for broken links in generated HTML
3. Verify recent posts have correct frontmatter
4. Check that all collectors ran recently: review `_posts/` dates
5. Verify GitHub Pages deployment status: `gh api repos/{owner}/{repo}/pages`
6. Check workflow health: `gh run list --limit 10`
7. Report any stale data sources (no posts in 7+ days)
