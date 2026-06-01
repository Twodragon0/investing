#!/usr/bin/env bash
# migrate_slack_naming.sh
#
# Slack secret naming unification — Phase 1 interactive registration tool.
# Design: docs/slack-secret-naming-unification.md
#
# Safety contract (incorporates reviewer findings):
#   - Default mode is DRY-RUN. Use --apply to actually call `gh secret set`.
#   - Existing secrets are NEVER overwritten without --force-overwrite. The
#     reviewer warning is that Phase 1 SLACK_CHANNEL_ID overwrite can break
#     17 live workflows mid-migration.
#   - Phase 4 destructive deletion is gated behind --phase=4 AND a vault
#     snapshot path. The snapshot file must exist with non-empty content.
#   - All `gh secret set` calls use `printf '%s' "$value" | gh secret set NAME --body -`
#     to avoid bash word-splitting on values with backslashes/newlines.
#   - Whitespace-only values are rejected.
#   - Phase 0 (audit) prints the current Slack-related secret inventory
#     without taking any destructive action.

set -euo pipefail

REPO="${REPO:-Twodragon0/investing}"
DRY_RUN=true
PHASE="0"
FORCE_OVERWRITE=false
VAULT_SNAPSHOT=""

usage() {
  cat <<'USAGE'
Usage: migrate_slack_naming.sh [options]

Options:
  --phase=N           Phase to execute (0=audit, 1=register canonical, 4=delete legacy)
  --apply             Actually execute; default is dry-run
  --force-overwrite   Allow overwriting existing names (Phase 1 only, dangerous)
  --vault=PATH        Path to vault snapshot file (required for --phase=4)
  --repo=OWNER/NAME   Override target repo (default: Twodragon0/investing)
  -h, --help          Show this help

Phases:
  0  Audit: list Slack-related entries, classify legacy vs canonical, print counts.
  1  Register canonical entries interactively. Skips names that already exist
     unless --force-overwrite is set. Reads values via read -s with explicit prompt.
  4  Delete legacy entries after verifying vault snapshot. Idempotent (404 ignored).

Examples:
  ./migrate_slack_naming.sh --phase=0
  ./migrate_slack_naming.sh --phase=1                    # dry-run
  ./migrate_slack_naming.sh --phase=1 --apply
  ./migrate_slack_naming.sh --phase=4 --vault=/path/to/vault-2026-06-01.txt --apply
USAGE
}

for arg in "$@"; do
  case "$arg" in
    --phase=*)         PHASE="${arg#--phase=}" ;;
    --apply)           DRY_RUN=false ;;
    --force-overwrite) FORCE_OVERWRITE=true ;;
    --vault=*)         VAULT_SNAPSHOT="${arg#--vault=}" ;;
    --repo=*)          REPO="${arg#--repo=}" ;;
    -h|--help)         usage; exit 0 ;;
    *)                 echo "Unknown option: $arg" >&2; usage; exit 2 ;;
  esac
done

if ! command -v gh >/dev/null 2>&1; then
  echo "ERROR: gh CLI not found in PATH" >&2
  exit 1
fi

log()  { printf '[%s] %s\n' "$(date -u +%H:%M:%SZ)" "$*"; }
warn() { printf '[%s] WARN: %s\n' "$(date -u +%H:%M:%SZ)" "$*" >&2; }
die()  { printf '[%s] ERROR: %s\n' "$(date -u +%H:%M:%SZ)" "$*" >&2; exit 1; }

mode_label() {
  $DRY_RUN && printf '[DRY-RUN]' || printf '[APPLY]'
}

# --- Canonical / legacy catalogs --------------------------------------------

CANONICAL_TOKENS=(
  SLACK_BOT_TOKEN
  SLACK_AI_BOT_TOKEN
  SLACK_OPENCLAW_BOT_TOKEN
)

CANONICAL_CHANNELS=(
  SLACK_CHANNEL_ID
  SLACK_CHANNEL_ID_OPS
  SLACK_CHANNEL_ID_DEV
  SLACK_CHANNEL_ID_SECURITY
  SLACK_CHANNEL_ID_OPENCLAW
  SLACK_CHANNEL_ID_AI
  SLACK_CHANNEL_ID_INVESTING
)

LEGACY_TOKENS=(
  AI_SLACK_BOT_TOKEN
  OPENCLAW_SLACK_BOT_TOKEN
  SLACK_TOKEN
)

LEGACY_CHANNELS=(
  OPENCLAW_SLACK_CHANNEL_ID
  OPENCLAW_SLACK_CHANNEL_ID_OPS
  OPENCLAW_SLACK_CHANNEL_ID_DEV
  OPENCLAW_SLACK_CHANNEL_ID_SECURITY
  OPENCLAW_SLACK_CHANNEL_ID_OPENCLAW
  OPENCLAW_SLACK_CHANNEL_ID_AI
  OPENCLAW_SLACK_CHANNEL_ID_INVESTING
  AI_SLACK_CHANNEL_ID
  AI_SLACK_CHANNEL_ID_OPS
  AI_SLACK_CHANNEL_ID_DEV
  AI_SLACK_CHANNEL_ID_SECURITY
  AI_SLACK_CHANNEL_ID_OPENCLAW
  AI_SLACK_CHANNEL_ID_AI
  AI_SLACK_CHANNEL_ID_INVESTING
  SLACK_CHANNEL
  SLACK_CHANNEL_OPS
  SLACK_CHANNEL_DEV
  SLACK_CHANNEL_SECURITY
  SLACK_CHANNEL_OPENCLAW
  SLACK_CHANNEL_AI
  SLACK_CHANNEL_INVESTING
)

# --- Helpers ----------------------------------------------------------------

list_live() {
  gh secret list --repo "$REPO" --json name -q '.[].name' 2>/dev/null
}

name_present() {
  local name="$1"
  list_live | grep -qx "$name"
}

trim_ws() {
  local v="$1"
  v="${v#"${v%%[![:space:]]*}"}"
  v="${v%"${v##*[![:space:]]}"}"
  printf '%s' "$v"
}

prompt_value() {
  local name="$1"
  local value
  printf 'Enter value for %s (input hidden, empty to skip): ' "$name" >&2
  IFS= read -rs value
  printf '\n' >&2
  printf '%s' "$value"
}

apply_set() {
  local name="$1"
  local value="$2"
  if $DRY_RUN; then
    log "$(mode_label) would set $name (${#value} chars)"
    return 0
  fi
  printf '%s' "$value" | gh secret set "$name" --repo "$REPO" --body -
  log "[APPLY] set $name"
}

apply_delete() {
  local name="$1"
  if $DRY_RUN; then
    log "$(mode_label) would delete $name"
    return 0
  fi
  if gh secret delete "$name" --repo "$REPO" 2>/dev/null; then
    log "[APPLY] deleted $name"
  else
    log "[APPLY] skip $name (not present)"
  fi
}

# --- Phase implementations --------------------------------------------------

phase_audit() {
  log "Phase 0 audit on $REPO"
  local live
  if ! live="$(list_live)"; then
    die "gh secret list failed"
  fi

  local present_canonical=() missing_canonical=()
  local present_legacy=() missing_legacy=()

  for s in "${CANONICAL_TOKENS[@]}" "${CANONICAL_CHANNELS[@]}"; do
    if grep -qx "$s" <<<"$live"; then present_canonical+=("$s")
    else                              missing_canonical+=("$s"); fi
  done

  for s in "${LEGACY_TOKENS[@]}" "${LEGACY_CHANNELS[@]}"; do
    if grep -qx "$s" <<<"$live"; then present_legacy+=("$s")
    else                              missing_legacy+=("$s"); fi
  done

  printf '\nCanonical present (%d/%d):\n' \
    "${#present_canonical[@]}" \
    "$(( ${#CANONICAL_TOKENS[@]} + ${#CANONICAL_CHANNELS[@]} ))"
  printf '  - %s\n' "${present_canonical[@]:-(none)}"

  printf '\nCanonical missing (need Phase 1 registration):\n'
  printf '  - %s\n' "${missing_canonical[@]:-(none)}"

  printf '\nLegacy present (Phase 4 deletion candidates, %d total):\n' "${#present_legacy[@]}"
  printf '  - %s\n' "${present_legacy[@]:-(none)}"

  printf '\nLegacy absent (already removed or never set):\n'
  printf '  - %s\n' "${missing_legacy[@]:-(none)}"

  printf '\nSummary: canonical=%d/%d, legacy_present=%d/%d\n' \
    "${#present_canonical[@]}" \
    "$(( ${#CANONICAL_TOKENS[@]} + ${#CANONICAL_CHANNELS[@]} ))" \
    "${#present_legacy[@]}" \
    "$(( ${#LEGACY_TOKENS[@]} + ${#LEGACY_CHANNELS[@]} ))"
}

phase_register() {
  log "Phase 1 canonical registration on $REPO ($(mode_label))"
  log "Existing names are SKIPPED unless --force-overwrite is set"

  local total=$(( ${#CANONICAL_TOKENS[@]} + ${#CANONICAL_CHANNELS[@]} ))
  local processed=0 skipped=0 registered=0

  for name in "${CANONICAL_TOKENS[@]}" "${CANONICAL_CHANNELS[@]}"; do
    processed=$((processed + 1))
    printf '\n--- (%d/%d) %s ---\n' "$processed" "$total" "$name"

    if name_present "$name"; then
      if $FORCE_OVERWRITE; then
        warn "$name already exists — --force-overwrite is on, will overwrite"
      else
        log "skip: $name already exists (use --force-overwrite to overwrite)"
        skipped=$((skipped + 1))
        continue
      fi
    fi

    local raw trimmed
    raw="$(prompt_value "$name")"
    trimmed="$(trim_ws "$raw")"

    if [ -z "$trimmed" ]; then
      log "skip: empty/whitespace value entered for $name"
      skipped=$((skipped + 1))
      continue
    fi

    apply_set "$name" "$trimmed"
    registered=$((registered + 1))
  done

  printf '\nPhase 1 done: processed=%d, registered=%d, skipped=%d\n' \
    "$processed" "$registered" "$skipped"
}

phase_delete_legacy() {
  log "Phase 4 legacy deletion on $REPO ($(mode_label))"

  [ -n "$VAULT_SNAPSHOT" ] || die "--vault=PATH is required for Phase 4"
  [ -f "$VAULT_SNAPSHOT" ] || die "vault snapshot not found: $VAULT_SNAPSHOT"
  [ -s "$VAULT_SNAPSHOT" ] || die "vault snapshot is empty: $VAULT_SNAPSHOT"

  log "vault snapshot present: $VAULT_SNAPSHOT ($(wc -c <"$VAULT_SNAPSHOT" | tr -d ' ') bytes)"

  if ! $DRY_RUN; then
    printf 'About to DELETE %d legacy entries from %s.\n' \
      "$(( ${#LEGACY_TOKENS[@]} + ${#LEGACY_CHANNELS[@]} ))" "$REPO"
    printf 'Type the exact repo name to confirm: ' >&2
    local confirm
    IFS= read -r confirm
    [ "$confirm" = "$REPO" ] || die "confirmation mismatch — aborting"
  fi

  local processed=0
  for name in "${LEGACY_TOKENS[@]}" "${LEGACY_CHANNELS[@]}"; do
    apply_delete "$name"
    processed=$((processed + 1))
  done

  printf '\nPhase 4 done: processed=%d (idempotent — non-existent names skipped)\n' \
    "$processed"
}

# --- Dispatch ---------------------------------------------------------------

case "$PHASE" in
  0) phase_audit ;;
  1) phase_register ;;
  4) phase_delete_legacy ;;
  *) die "Unknown phase: $PHASE (valid: 0, 1, 4)" ;;
esac
