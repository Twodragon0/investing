# Agent .md OMC 4.13.x Convention Audit — 2026-05-07

**Audited by**: executor agent (claude-sonnet-4-6)
**Scope**: `.claude/agents/*.md` (9 files)
**Convention ref**: OMC 4.13.x — `name` must match filename without `.md`

---

## Audit Results Table

| File | `name` field (before) | Matches filename? | `description` | `tools` | `model` | Issues found | Fix applied |
|------|----------------------|-------------------|---------------|---------|---------|-------------|-------------|
| `architect.md` | `investing-architect` | **NO** | present | present | opus | name mismatch | `name: architect` |
| `collector-reviewer.md` | `collector-reviewer` | YES | present | present | sonnet | none | — |
| `content-pipeline.md` | `content-pipeline` | YES | present | present | sonnet | none | — |
| `data-pipeline-lead.md` | `data-pipeline-lead` | YES | present | present | sonnet | none | — |
| `investing-lead.md` | `investing-lead` | YES | present | present | opus | none | — |
| `jekyll-checker.md` | `jekyll-checker` | YES | present | present | haiku | none | — |
| `test-engineer.md` | `investing-test-engineer` | **NO** | present | present | sonnet | name mismatch | `name: test-engineer` |
| `workflow-debugger.md` | `workflow-debugger` | YES | present | present | sonnet | none | — |
| `workflow-optimizer.md` | `workflow-optimizer` | YES | present | present | sonnet | none | — |

**Result**: 2 of 9 files had `name:` mismatches. Both fixed.

---

## Fixes Applied

### 1. `architect.md`
- **Before**: `name: investing-architect`
- **After**: `name: architect`
- **Reason**: OMC task routing uses the `name` field to match the agent file. Mismatched name breaks `Task(subagent_type="architect")` invocations.

### 2. `test-engineer.md`
- **Before**: `name: investing-test-engineer`
- **After**: `name: test-engineer`
- **Reason**: Same routing breakage. The file is `test-engineer.md`, so the `name` must be `test-engineer`.

---

## YAML Validation Results

All 9 files passed `yaml.safe_load` on their frontmatter:

```
architect.md: OK
collector-reviewer.md: OK
content-pipeline.md: OK
data-pipeline-lead.md: OK
investing-lead.md: OK
jekyll-checker.md: OK
test-engineer.md: OK
workflow-debugger.md: OK
workflow-optimizer.md: OK
```

---

## Recommendations for Manual Follow-Up

The following are informational — no safety issue, but worth considering:

1. **`architect.md` — `vibe` field**: Contains a non-standard `vibe: Data flows from 11 sources...` key at the frontmatter level. This is outside the OMC spec (optional fields: `color`, `emoji`, `memory`). Not harmful, but could cause confusion. Consider moving to a comment or the Identity section.

2. **`test-engineer.md` — `vibe` field**: Same pattern — `vibe: Every collector is deterministic...` is an inline string at frontmatter level. Other agents wrap `vibe` as a quoted string. Minor formatting inconsistency.

3. **`collector-reviewer.md` / `data-pipeline-lead.md` / `jekyll-checker.md` / `workflow-debugger.md`**: All use `permissionMode: plan` and `disallowedTools: Write, Edit`. This is intentional (read-only agents). No action needed.

4. **`investing-lead.md`**: Uses `tools: ..., Agent` which is correct for an orchestrator role. Verify that `Agent` is still a recognized tool name in your OMC version.

5. **`content-pipeline.md`**: Uses `maxTurns: 20` (highest of all agents). This is intentional for the content generation workload. No issue, just worth noting during capacity planning.

---

## Files Modified

- `.claude/agents/architect.md` — `name` field corrected
- `.claude/agents/test-engineer.md` — `name` field corrected
- `reports/agent-audit-2026-05-07.md` — this report (new file)
