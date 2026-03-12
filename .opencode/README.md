# OpenCode Baseline

This repository uses a shared OpenCode baseline with:

- Lead orchestration agent (`lead`) as default
- Specialist subagents (`explore`, `validate`, `code`)
- Safety plugin hooks for command/read guardrails
- Governance/security/cost/validation skills

## Structure

- `opencode.json`: runtime config, permissions, MCP, agent defaults
- `agents/*.md`: agent role definitions
- `plugins/*.js`: runtime hook policies
- `skills/*/SKILL.md`: reusable operational guidance

## Notes

- Existing repo-specific `.opencode` was backed up before baseline apply.
- Customize commands and repo-specific skills after baseline rollout.

## Repo Automation Hooks

- `scripts/opencode_git_pull.sh`: cache-first sync helper for automated `git pull --rebase` on `main`
- `.github/workflows/continuous-improvement-loop.yml`: hourly OpenClaw loop (`0 * * * *`)
- Loop flow: `opencode_git_pull.sh` -> Ralph quality sweep -> Ultrawork image backfill -> forum report
- Forum domains: ops, security, monitoring, performance, code-quality, content-quality, uiux, design
