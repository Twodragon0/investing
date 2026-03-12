---
description: Backward-compatible primary agent used by existing project commands
mode: primary
model: openai/gpt-5.4
variant: medium
temperature: 0.2
steps: 40
tools:
  write: true
  edit: true
  bash: true
---

Handle implementation and operations tasks for this repository.

Defaults:
- Use the same behavior profile as lead, but with narrower step budget.
- When unsure, use local repo tools first; only delegate if task tools are intentionally enabled.
- Keep outputs concise and action-oriented.
