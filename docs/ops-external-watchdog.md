# Layer 4: External Watchdog

## Overview

This is the fourth and outermost layer of the alerting pyramid for the `investing` repo.
It runs on an **external server** (not GitHub Actions) and monitors `watchdog-zero-job-runs.yml` itself.

### Alerting pyramid

| Layer | What it catches | Where it runs | Failure mode covered |
|-------|----------------|---------------|----------------------|
| 1 | Collector N-consecutive failures | GitHub Actions (`alert-consecutive-failures.yml`) | Runtime errors in collectors |
| 2 | Layer 1 Slack failure | GitHub Actions (issue fallback, PR #803) | Slack API down or misconfigured token |
| 3 | ANY workflow `startup_failure` | GitHub Actions (`watchdog-zero-job-runs.yml`) | Permission bug class (13 collectors, 2026-04-23) |
| **4** | **Layer 3 itself fails** | **External server (cron)** | **watchdog startup_failure / GHA outage** |

Layer 4 closes the final blind spot: if `watchdog-zero-job-runs.yml` startup_fails (same
permission-bug class that broke 13 collectors), nobody notices unless something outside GitHub
Actions is watching.

---

## Files

| File | Purpose |
|------|---------|
| `scripts/ops/external_watchdog.sh` | Main poll-and-alert script |
| `scripts/ops/install_external_watchdog.sh` | One-command installer + cron setup |
| `tests/test_external_watchdog.py` | pytest wrapper (subprocess + stubbed curl) |

---

## Quick Install

On the external server (Ubuntu/macOS, requires `curl` and `jq`):

```bash
# 1. Copy scripts to the server
scp scripts/ops/external_watchdog.sh scripts/ops/install_external_watchdog.sh user@server:~/

# 2. Run installer (creates /usr/local/bin/external_watchdog.sh + cron)
sudo bash ~/install_external_watchdog.sh

# 3. Edit config (fill in real values)
sudo nano /etc/default/external_watchdog

# 4. Test run
/usr/local/bin/external_watchdog.sh
```

The installer registers this crontab entry (idempotent, safe to re-run):
```
*/5 * * * * /usr/local/bin/external_watchdog.sh >> /var/log/external_watchdog.log 2>&1
```

---

## Configuration

All config lives in `/etc/default/external_watchdog` (sourced at startup):

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GITHUB_TOKEN` | yes | — | PAT with `actions:read` scope only |
| `GITHUB_REPO` | yes | — | e.g. `Twodragon0/investing` |
| `SLACK_WEBHOOK_URL` | yes | — | Incoming webhook URL (see below) |
| `WATCHDOG_WORKFLOW_FILE` | no | `watchdog-zero-job-runs.yml` | Workflow filename to monitor |
| `ALERT_THRESHOLD_MINUTES` | no | `15` | Alert if no success within N minutes |
| `DEDUP_COOLDOWN_SECONDS` | no | `3600` | Suppress duplicate alerts for 1 hour |

---

## Verification

```bash
# Watch live log
tail -f /var/log/external_watchdog.log

# Simulate "no recent success" (temporarily set threshold to 0)
ALERT_THRESHOLD_MINUTES=0 /usr/local/bin/external_watchdog.sh

# Check crontab
crontab -l | grep watchdog

# Force alert (bypass dedup)
rm -f /var/log/external_watchdog_last_alert.txt && ALERT_THRESHOLD_MINUTES=0 /usr/local/bin/external_watchdog.sh
```

---

## Uninstall

```bash
sudo bash ~/install_external_watchdog.sh --uninstall
```

This removes the binary and crontab entry. The config file `/etc/default/external_watchdog`
is intentionally left behind (contains secrets; remove manually with `sudo rm`).

---

## Security

### GITHUB_TOKEN
- Use a **read-only fine-grained PAT** scoped to this repo with only `Actions: Read` permission.
- Do **not** use a classic PAT with broad permissions.
- Rotate every 90 days.

### SLACK_WEBHOOK_URL
- This is an **Incoming Webhook** URL created in a separate Slack app — completely independent
  of the in-repo `SLACK_BOT_TOKEN`. This decoupling ensures that if the repo's Slack secrets
  are wrong or rotated, Layer 4 still works.
- The webhook URL is a capability secret (anyone with it can post); guard it carefully.

### Config file permissions (mandatory)
```bash
sudo chown root:root /etc/default/external_watchdog
sudo chmod 600 /etc/default/external_watchdog
```

### Log file
`/var/log/external_watchdog.log` logs timestamps and alert reasons but never secrets.
Standard `logrotate` applies.
