# OpenCode Automation (Centralized)

This repository now uses centralized hourly automation managed from Desktop root.

## Control paths

- Runner: `/Users/namyongkim/Desktop/.twodragon0/bin/hourly-opencode-git-pull.sh`
- Cron installer: `/Users/namyongkim/Desktop/.twodragon0/bin/install-system-cron.sh`
- OpenClaw cron setup: `/Users/namyongkim/Desktop/.twodragon0/bin/setup-openclaw-cron.sh`

## Policy

- Pull mode is `--ff-only`.
- Dirty repositories are skipped.
- Per-repo OpenCode/OpenClaw cron scripts are deprecated.
