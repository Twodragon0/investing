# OpenCode Baseline

This repository uses a shared OpenCode baseline with:

- Lead orchestration agent (`lead`) as default
- Specialist subagents (`explore`, `validate`, `code`, `content`, `media`)
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

## AI Reinforced Mode

- Primary model: `openai/gpt-5.4` with `variant=medium`
- Routing best practice:
  - `lead` / `primary` / `code` / `content`: `openai/gpt-5.4` (`variant=medium`)
  - `explore`: `google/antigravity-gemini-3-flash` (`variant=medium`)
  - `validate` / `media`: `google/antigravity-claude-sonnet-4-5-thinking` (`variant=low`)
- Recommended flow for post automation:
  - `explore` finds repo patterns and recent regressions
  - `content` refines post quality logic and wording safety
  - `media` reviews image/OG quality risks
  - `validate` performs final quality/security checks
- Goal: keep implementation quality on GPT-5.4 while using Gemini for broad discovery and Claude for strict review.
