#!/usr/bin/env bash
# external_watchdog.sh — Layer 4 alerting: monitors watchdog-zero-job-runs.yml
# from an external server so that a startup_failure of the watchdog itself is caught.
#
# Dependencies: curl, jq (both available on standard Ubuntu/macOS)
# Config: sourced from /etc/default/external_watchdog if present, then env vars.
# Cron example: */5 * * * * /usr/local/bin/external_watchdog.sh >> /var/log/external_watchdog.log 2>&1

set -euo pipefail

# ---------------------------------------------------------------------------
# 0. Source optional config file
# ---------------------------------------------------------------------------
CONFIG_FILE="${EXTERNAL_WATCHDOG_CONFIG:-/etc/default/external_watchdog}"
if [ -f "$CONFIG_FILE" ]; then
  # shellcheck source=/dev/null
  . "$CONFIG_FILE"
fi

# ---------------------------------------------------------------------------
# 1. Logging helper
# ---------------------------------------------------------------------------
log() {
  printf "%s [external_watchdog] %s\n" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"
}

# ---------------------------------------------------------------------------
# 2. Validate required env vars
# ---------------------------------------------------------------------------
GITHUB_TOKEN="${GITHUB_TOKEN:-}"
GITHUB_REPO="${GITHUB_REPO:-}"
SLACK_WEBHOOK_URL="${SLACK_WEBHOOK_URL:-}"
WATCHDOG_WORKFLOW_FILE="${WATCHDOG_WORKFLOW_FILE:-watchdog-zero-job-runs.yml}"
ALERT_THRESHOLD_MINUTES="${ALERT_THRESHOLD_MINUTES:-15}"
DEDUP_FILE="${DEDUP_FILE:-/var/log/external_watchdog_last_alert.txt}"
DEDUP_COOLDOWN_SECONDS="${DEDUP_COOLDOWN_SECONDS:-3600}"

for var in GITHUB_TOKEN GITHUB_REPO SLACK_WEBHOOK_URL; do
  if [ -z "$(eval echo \$${var})" ]; then
    log "ERROR: required env var ${var} is not set"
    exit 1
  fi
done

# ---------------------------------------------------------------------------
# 3. Fetch recent workflow runs (with one retry)
# ---------------------------------------------------------------------------
API_URL="https://api.github.com/repos/${GITHUB_REPO}/actions/workflows/${WATCHDOG_WORKFLOW_FILE}/runs?per_page=10"
log "Querying: ${API_URL}"

fetch_runs() {
  curl -sf \
    -H "Authorization: Bearer ${GITHUB_TOKEN}" \
    -H "Accept: application/vnd.github+json" \
    -H "X-GitHub-Api-Version: 2022-11-28" \
    --max-time 15 \
    "$API_URL"
}

if ! RUNS_JSON="$(fetch_runs 2>&1)"; then
  log "WARN: first attempt failed, retrying in 5s"
  sleep 5
  if ! RUNS_JSON="$(fetch_runs 2>&1)"; then
    log "ERROR: GitHub API call failed after retry: ${RUNS_JSON}"
    exit 1
  fi
fi

# ---------------------------------------------------------------------------
# 4. Parse: last success timestamp + recent startup_failure count
# ---------------------------------------------------------------------------
LAST_SUCCESS_TS="$(printf '%s' "$RUNS_JSON" | \
  jq -r '[.workflow_runs[] | select(.conclusion == "success")] | first | .created_at // empty')"

RECENT_STARTUP_FAIL_COUNT="$(printf '%s' "$RUNS_JSON" | \
  jq '[.workflow_runs[:3][] | select(.conclusion == "startup_failure")] | length')"

RECENT_SUCCESS_COUNT="$(printf '%s' "$RUNS_JSON" | \
  jq '[.workflow_runs[:3][] | select(.conclusion == "success")] | length')"

log "last_success_ts=${LAST_SUCCESS_TS:-none} recent_startup_failures=${RECENT_STARTUP_FAIL_COUNT} recent_successes=${RECENT_SUCCESS_COUNT}"

# ---------------------------------------------------------------------------
# 5. Determine if alert should fire
# ---------------------------------------------------------------------------
ALERT_REASON=""

# 5a. Last 3 runs are all startup_failure
if [ "$RECENT_STARTUP_FAIL_COUNT" -ge 3 ]; then
  ALERT_REASON="최근 3회 연속 startup_failure (watchdog 자체 장애)"
fi

# 5b. No successful run within threshold window
if [ -z "$ALERT_REASON" ]; then
  if [ -z "$LAST_SUCCESS_TS" ]; then
    ALERT_REASON="마지막 성공 실행 없음 (조회된 10개 실행 내)"
  else
    # Convert ISO-8601 to epoch — works on both GNU date and BSD date (macOS)
    if date --version >/dev/null 2>&1; then
      # GNU date
      LAST_SUCCESS_EPOCH="$(date -u -d "$LAST_SUCCESS_TS" +%s 2>/dev/null || echo 0)"
    else
      # BSD date (macOS)
      LAST_SUCCESS_EPOCH="$(date -u -j -f '%Y-%m-%dT%H:%M:%SZ' "$LAST_SUCCESS_TS" +%s 2>/dev/null || echo 0)"
    fi
    NOW_EPOCH="$(date -u +%s)"
    ELAPSED_MINUTES=$(( (NOW_EPOCH - LAST_SUCCESS_EPOCH) / 60 ))
    log "elapsed_since_last_success=${ELAPSED_MINUTES}m threshold=${ALERT_THRESHOLD_MINUTES}m"
    if [ "$ELAPSED_MINUTES" -gt "$ALERT_THRESHOLD_MINUTES" ]; then
      ALERT_REASON="마지막 성공 이후 ${ELAPSED_MINUTES}분 경과 (임계값: ${ALERT_THRESHOLD_MINUTES}분)"
    fi
  fi
fi

# ---------------------------------------------------------------------------
# 6. No alert needed
# ---------------------------------------------------------------------------
if [ -z "$ALERT_REASON" ]; then
  log "OK: watchdog is healthy, no alert needed"
  exit 0
fi

log "ALERT triggered: ${ALERT_REASON}"

# ---------------------------------------------------------------------------
# 7. Dedup: skip if we already alerted within the cooldown window for the same reason
# ---------------------------------------------------------------------------
NOW_EPOCH="$(date -u +%s)"
if [ -f "$DEDUP_FILE" ]; then
  LAST_ALERT_EPOCH="$(cat "$DEDUP_FILE" 2>/dev/null | tr -d '[:space:]' || echo 0)"
  SECONDS_SINCE="$(( NOW_EPOCH - LAST_ALERT_EPOCH ))"
  if [ "$SECONDS_SINCE" -lt "$DEDUP_COOLDOWN_SECONDS" ]; then
    log "DEDUP: already alerted ${SECONDS_SINCE}s ago (cooldown: ${DEDUP_COOLDOWN_SECONDS}s), skipping"
    exit 0
  fi
fi

# ---------------------------------------------------------------------------
# 8. Post Slack alert
# ---------------------------------------------------------------------------
PAYLOAD="$(jq -n \
  --arg reason "$ALERT_REASON" \
  --arg repo "$GITHUB_REPO" \
  --arg workflow "$WATCHDOG_WORKFLOW_FILE" \
  --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  '{
    text: (":rotating_light: *[Layer 4 외부 워치독 경보]* `" + $workflow + "` 가 장애 상태\n\n" +
           "*사유:* " + $reason + "\n" +
           "*저장소:* `" + $repo + "`\n" +
           "*감지 시각:* " + $ts + "\n\n" +
           "즉시 확인 필요: https://github.com/" + $repo + "/actions/workflows/" + $workflow)
  }')"

log "Posting Slack alert"
HTTP_STATUS="$(curl -sf -o /dev/null -w "%{http_code}" \
  -X POST "$SLACK_WEBHOOK_URL" \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD" || echo "000")"

if [ "$HTTP_STATUS" = "200" ]; then
  log "Slack alert posted successfully (HTTP 200)"
  printf "%s\n" "$NOW_EPOCH" > "$DEDUP_FILE"
else
  log "ERROR: Slack webhook returned HTTP ${HTTP_STATUS}"
  exit 1
fi

exit 0
