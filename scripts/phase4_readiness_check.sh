#!/usr/bin/env bash
# phase4_readiness_check.sh
#
# Slack secret naming unification — Phase 4 readiness gate (daily check).
# Related: docs/slack-secret-naming-unification.md § 6 Phase 4
#          docs/runbook-slack-vault-snapshot.md
#
# Why this script (not ralph): the Phase 4 gate requires a calendar wait of
# ≥7 days since Phase 2 deploy AND Slack post success rate ≥ baseline. A
# continuous ralph loop wastes Claude session budget for a 7-day wait. This
# script is meant to be invoked once per day (manually or via cron) and prints
# a structured go/no-go verdict.
#
# Exit codes:
#   0  Phase 4 ready (all gates pass)
#   1  Phase 4 NOT ready (at least one gate fails)
#   2  Script error (invalid inputs, missing dependencies)

set -euo pipefail

REPO="${REPO:-Twodragon0/investing}"
PHASE2_MERGE_DATE="${PHASE2_MERGE_DATE:-2026-06-01}"  # PR #996 merge date
MIN_WAIT_DAYS="${MIN_WAIT_DAYS:-7}"
BASELINE_SUCCESS_RATE="${BASELINE_SUCCESS_RATE:-0.95}"  # 95% successful Slack posts over window
VAULT_SNAPSHOT_PATH="${VAULT_SNAPSHOT_PATH:-}"

usage() {
  cat <<'USAGE'
Usage: phase4_readiness_check.sh [options]

Options:
  -h, --help            Show this help

Environment variables (overrides):
  REPO                     Default: Twodragon0/investing
  PHASE2_MERGE_DATE        ISO date (YYYY-MM-DD) of last Phase 2 merge; default 2026-06-01
  MIN_WAIT_DAYS            Minimum days since Phase 2; default 7
  BASELINE_SUCCESS_RATE    Slack post success rate threshold (0.0-1.0); default 0.95
  VAULT_SNAPSHOT_PATH      Path to vault snapshot file (required for full pass)

Exit codes:
  0  ALL GATES PASS — Phase 4 deletion is ready to proceed
  1  AT LEAST ONE GATE FAILS — DO NOT run Phase 4
  2  Script error
USAGE
}

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
  usage
  exit 0
fi

if ! command -v gh >/dev/null 2>&1; then
  echo "ERROR: gh CLI not installed" >&2
  exit 2
fi
if ! command -v jq >/dev/null 2>&1; then
  echo "ERROR: jq not installed" >&2
  exit 2
fi

log()  { printf '[%s] %s\n' "$(date -u +%H:%M:%SZ)" "$*"; }
gate_pass() { printf '  ✓ PASS — %s\n' "$1"; }
gate_fail() { printf '  ✗ FAIL — %s\n' "$1"; }

date_to_epoch() {
  # macOS BSD date or GNU date
  date -j -f "%Y-%m-%d" "$1" "+%s" 2>/dev/null || date -d "$1" "+%s"
}

today_iso() { date -u +%Y-%m-%d; }
days_between() {
  local a_epoch="$1"
  local b_epoch="$2"
  echo $(( (b_epoch - a_epoch) / 86400 ))
}

# --- Gate 1: calendar wait ---------------------------------------------------

gate_calendar() {
  log "Gate 1: calendar wait (≥ ${MIN_WAIT_DAYS} days since Phase 2)"

  local merge_epoch today_epoch days_elapsed
  if ! merge_epoch=$(date_to_epoch "$PHASE2_MERGE_DATE" 2>/dev/null); then
    gate_fail "invalid PHASE2_MERGE_DATE format: $PHASE2_MERGE_DATE (need YYYY-MM-DD)"
    return 1
  fi
  today_epoch=$(date -u +%s)
  days_elapsed=$(days_between "$merge_epoch" "$today_epoch")

  if [ "$days_elapsed" -ge "$MIN_WAIT_DAYS" ]; then
    gate_pass "${days_elapsed} days elapsed (≥ ${MIN_WAIT_DAYS} required)"
    return 0
  fi
  gate_fail "${days_elapsed}/${MIN_WAIT_DAYS} days elapsed — wait $((MIN_WAIT_DAYS - days_elapsed)) more day(s)"
  return 1
}

# --- Gate 2: vault snapshot ---------------------------------------------------

gate_vault() {
  log "Gate 2: vault snapshot present and non-empty"

  if [ -z "$VAULT_SNAPSHOT_PATH" ]; then
    gate_fail "VAULT_SNAPSHOT_PATH not set — required for rollback safety"
    return 1
  fi
  if [ ! -f "$VAULT_SNAPSHOT_PATH" ]; then
    gate_fail "snapshot file not found: $VAULT_SNAPSHOT_PATH"
    return 1
  fi
  if [ ! -s "$VAULT_SNAPSHOT_PATH" ]; then
    gate_fail "snapshot file is empty: $VAULT_SNAPSHOT_PATH"
    return 1
  fi

  local size
  size=$(wc -c <"$VAULT_SNAPSHOT_PATH" | tr -d ' ')
  gate_pass "snapshot present (${size} bytes): $VAULT_SNAPSHOT_PATH"
  return 0
}

# --- Gate 3: Slack post success rate (recent runs) ----------------------------

gate_slack_health() {
  log "Gate 3: Slack post success rate over last ${MIN_WAIT_DAYS} days ≥ $(awk -v r="$BASELINE_SUCCESS_RATE" 'BEGIN{printf "%.0f%%", r*100}')"

  local cutoff_iso
  # Cutoff = today minus MIN_WAIT_DAYS
  cutoff_iso=$(date -u -j -v-"${MIN_WAIT_DAYS}"d +%Y-%m-%d 2>/dev/null \
            || date -u -d "${MIN_WAIT_DAYS} days ago" +%Y-%m-%d)

  # Slack-posting workflows that we just migrated
  local workflows=(
    respond-ai-mentions.yml
    collect-defi-llama.yml
    collect-defi-yields.yml
    collector-heartbeat.yml
    generate-daily-summary.yml
    generate-market-summary.yml
    generate-weekly-report.yml
    alert-consecutive-failures.yml
    classify-workflow-failures.yml
    notify-deploy-status.yml
    cleanup-old-images.yml
    site-health-check.yml
    watchdog-zero-job-runs.yml
    ops-10am-digest.yml
    weekly-digest.yml
    continuous-improvement-loop.yml
    push-folder-info-to-slack.yml
  )

  local total=0 success=0
  for wf in "${workflows[@]}"; do
    local runs_json
    runs_json=$(gh run list --workflow "$wf" --repo "$REPO" \
                --limit 50 --json conclusion,createdAt 2>/dev/null \
                || echo "[]")
    # Filter runs after cutoff with non-null conclusion
    local in_window ok
    in_window=$(echo "$runs_json" | jq --arg c "${cutoff_iso}T00:00:00Z" \
                '[.[] | select(.createdAt >= $c) | select(.conclusion != null)] | length')
    ok=$(echo "$runs_json" | jq --arg c "${cutoff_iso}T00:00:00Z" \
         '[.[] | select(.createdAt >= $c) | select(.conclusion == "success")] | length')
    total=$((total + in_window))
    success=$((success + ok))
  done

  if [ "$total" -eq 0 ]; then
    gate_fail "no workflow runs in the last ${MIN_WAIT_DAYS} days — cannot compute success rate"
    return 1
  fi

  local rate threshold
  rate=$(awk -v s="$success" -v t="$total" 'BEGIN{printf "%.4f", s/t}')
  threshold="$BASELINE_SUCCESS_RATE"
  local pass
  pass=$(awk -v r="$rate" -v th="$threshold" 'BEGIN{print (r >= th) ? "yes" : "no"}')

  if [ "$pass" = "yes" ]; then
    gate_pass "success rate ${rate} (${success}/${total}) ≥ baseline ${threshold}"
    return 0
  fi
  gate_fail "success rate ${rate} (${success}/${total}) < baseline ${threshold}"
  return 1
}

# --- Gate 4: legacy entries still present (sanity check) ----------------------

gate_legacy_present() {
  log "Gate 4: legacy entries still present (Phase 4 has work to do)"

  local live legacy_found=0
  if ! live=$(gh secret list --repo "$REPO" --json name -q '.[].name' 2>/dev/null); then
    gate_fail "gh secret list failed"
    return 1
  fi
  for name in AI_SLACK_BOT_TOKEN OPENCLAW_SLACK_BOT_TOKEN; do
    if grep -qx "$name" <<<"$live"; then
      legacy_found=$((legacy_found + 1))
    fi
  done

  if [ "$legacy_found" -gt 0 ]; then
    gate_pass "${legacy_found} legacy token(s) still present — Phase 4 will delete them"
    return 0
  fi
  gate_fail "0 legacy tokens present — Phase 4 already complete or skipped (no-op)"
  return 1
}

# --- Main ---------------------------------------------------------------------

main() {
  printf '=== Phase 4 Readiness Check — %s ===\n\n' "$(today_iso)"
  printf 'Config:\n'
  printf '  REPO=%s\n' "$REPO"
  printf '  PHASE2_MERGE_DATE=%s\n' "$PHASE2_MERGE_DATE"
  printf '  MIN_WAIT_DAYS=%s\n' "$MIN_WAIT_DAYS"
  printf '  BASELINE_SUCCESS_RATE=%s\n' "$BASELINE_SUCCESS_RATE"
  printf '  VAULT_SNAPSHOT_PATH=%s\n\n' "${VAULT_SNAPSHOT_PATH:-(unset)}"

  local fails=0
  gate_calendar      || fails=$((fails + 1))
  gate_vault         || fails=$((fails + 1))
  gate_slack_health  || fails=$((fails + 1))
  gate_legacy_present || fails=$((fails + 1))

  printf '\n=== Verdict ===\n'
  if [ "$fails" -eq 0 ]; then
    printf '✓ ALL GATES PASS — Phase 4 deletion is ready.\n'
    printf '\nNext step:\n'
    printf '  bash scripts/migrate_slack_naming.sh --phase=4 \\\n'
    printf '    --vault=%s \\\n' "$VAULT_SNAPSHOT_PATH"
    printf '    --apply\n'
    return 0
  fi
  printf '✗ %d gate(s) FAILED — DO NOT run Phase 4.\n' "$fails"
  printf '\nRe-run this check daily (e.g. cron 0 9 * * *) until all gates pass.\n'
  return 1
}

main "$@"
