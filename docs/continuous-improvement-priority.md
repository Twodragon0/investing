# Continuous Improvement Priority Plan

## P0 - Reliability (This Week)

1. Stabilize analyze/search-mode background result recovery
   - Use `task_id + session_id` capture as mandatory
   - Prefer short non-blocking polls, then session continuation fallback
   - Record timeout sessions in run summary for follow-up

2. Harden workflow quality gate visibility
   - Keep `actionlint` annotations + PR comment upsert active
   - Fail fast when workflow syntax errors are found

3. Keep post rendering consistency centralized
   - Use `scripts/common/markdown_utils.py` helpers for source tags/references
   - Avoid direct inline `<span class="source-tag">...` in collectors

## P1 - Observability (Next)

1. Collector completion log standardization
   - Common log schema: `source_count`, `unique_items`, `post_created`, `duration`
   - Apply across crypto/stock/social/regulatory/political/worldmonitor collectors

2. Workflow failure triage improvements
   - Keep dedupe key (`workflow + run + sha`) and attach classifier evidence snippet
   - Track rerun outcome in issue body for faster debugging

3. Deployment verification logging
   - Add short post-deploy check summary (latest post URL + render smoke status)

## P2 - Content Quality (After P0/P1)

1. Generated post structure contracts
   - Validate section order and required blocks (summary/table/reference/footer)
   - Expand fixture set for more edge cases (long links, mixed sources, empty refs)

2. Historical post consistency maintenance
   - Regenerate key recurring post types when generator format changes
   - Avoid manual post edits unless hotfix is required

## Operating Rules

- Prefer utility/function reuse over per-script inline HTML assembly
- Verify with `py_compile + rendered fixture smoke + jekyll build` before push
- Keep commits small and purpose-focused for easier rollback
