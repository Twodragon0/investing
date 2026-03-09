---
name: debug-workflow
description: Debug failing GitHub Actions workflows for the investing project
---

# Debug GitHub Actions Workflow

## Steps
1. Check workflow run history: `gh run list --workflow=<name>`
2. Read failing run logs: `gh run view <run-id> --log-failed`
3. Read the workflow YAML in `.github/workflows/`
4. Check for common issues:
   - Expired or missing secrets
   - API rate limits
   - Cron scheduling conflicts
   - Dependency version changes
   - Jekyll build errors
5. Fix the issue and verify locally if possible
6. Push fix and monitor next run
