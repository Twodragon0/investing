---
name: opencode-governance
description: Standardize lead-agent delegation, safety hooks, and verification flow for this repository
compatibility: opencode
license: MIT
metadata:
  audience: maintainers
  domain: platform-ops
---

Use this skill when setting up or auditing OpenCode project configuration.

Checklist:
1. Lead agent exists and delegates to specialized subagents.
2. Commands target stable agent names used in this repo.
3. Safety hooks block destructive shell actions and sensitive reads.
4. Permissions follow least privilege while keeping daily workflows smooth.
5. Validation gates are explicit for changed scope.

Deliverables:
- Config delta summary with rationale
- Rollback-safe migration notes for team adoption
