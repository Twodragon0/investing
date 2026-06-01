# Runbook — Slack Legacy Token Vault Snapshot (Phase 0.5)

> Status: **Runbook (executable)**
> Owner: investing platform
> Related design: `docs/slack-secret-naming-unification.md` § 6 Phase 0.5
> Last updated: 2026-06-01

## 0. Why this exists

`docs/slack-secret-naming-unification.md` Phase 4 deletes 2 legacy GitHub
Actions secrets:

- `AI_SLACK_BOT_TOKEN`
- `OPENCLAW_SLACK_BOT_TOKEN`

`gh secret delete` is destructive — GitHub does not retain the plaintext value
after deletion. If we delete before backing up, rollback requires regenerating
the tokens from the Slack admin console (lossy, requires re-installation, and
may break running bots if the old token is invalidated).

This runbook captures the values in a durable vault and proves the restore
path works **before** Phase 4 unblocks.

## 1. Scope

| Item | What | Where |
|---|---|---|
| Backup target | 2 token values (legacy names) | GitHub repo secrets → vault |
| Vault entry name | `gh-investing-<SECRET_NAME>` | namespaced |
| Verification | 1 restore test (vault → fresh repo secret → delete) | once |
| Snapshot artifact path | runbook-only memo, value not committed | tracked separately |

Channel ID secrets are out of scope — they are public identifiers (`Cxxxxx`),
not credentials, and can be recovered from the Slack channel settings.

## 2. Prerequisites

- `gh` CLI authenticated to `Twodragon0/investing` with `repo` scope.
- One of: 1Password CLI (`op`), SOPS + age, or Bitwarden CLI (`bw`).
- Operator with admin access to the Slack workspace (recovery path only).

## 3. Procedure

### 3.1 Option A — 1Password CLI

```bash
# 1) Resolve current value from GitHub (NOT possible — gh does not expose values).
#    Operator must already hold the token via:
#      - Slack admin console (App Management → reinstall to view) — last resort
#      - Existing 1Password / Bitwarden / SOPS entry from when the token was first created
#      - Operator memory / sealed envelope

# 2) Write to 1Password (no value in shell history — uses stdin)
op item create \
  --category="API Credential" \
  --title="gh-investing-AI_SLACK_BOT_TOKEN" \
  --vault="Investing" \
  --tags="github,slack,migration-2026-06" \
  credential[password]="$(read -rs -p 'paste AI_SLACK_BOT_TOKEN: ' v && echo "$v"; echo >&2)"

op item create \
  --category="API Credential" \
  --title="gh-investing-OPENCLAW_SLACK_BOT_TOKEN" \
  --vault="Investing" \
  --tags="github,slack,migration-2026-06" \
  credential[password]="$(read -rs -p 'paste OPENCLAW_SLACK_BOT_TOKEN: ' v && echo "$v"; echo >&2)"

# 3) Verify retrieval works
op item get "gh-investing-AI_SLACK_BOT_TOKEN" --field credential >/dev/null && echo "OK: AI"
op item get "gh-investing-OPENCLAW_SLACK_BOT_TOKEN" --field credential >/dev/null && echo "OK: OPENCLAW"
```

### 3.2 Option B — SOPS + age

```bash
# 1) Ensure age key exists
test -f ~/.config/sops/age/keys.txt || age-keygen -o ~/.config/sops/age/keys.txt

# 2) Create encrypted YAML
cat > /tmp/slack-legacy.yaml.dec <<'YAML'
AI_SLACK_BOT_TOKEN: ""
OPENCLAW_SLACK_BOT_TOKEN: ""
YAML

# Edit with the real values — file is plaintext until encrypted
${EDITOR:-vi} /tmp/slack-legacy.yaml.dec

# 3) Encrypt in place
AGE_PUBKEY="$(grep '# public key:' ~/.config/sops/age/keys.txt | awk '{print $4}')"
sops --encrypt --age "$AGE_PUBKEY" /tmp/slack-legacy.yaml.dec > ~/Documents/vault/slack-legacy-2026-06-01.yaml.enc
shred -u /tmp/slack-legacy.yaml.dec

# 4) Verify decryption works
sops --decrypt ~/Documents/vault/slack-legacy-2026-06-01.yaml.enc | head -2
```

### 3.3 Option C — Bitwarden CLI

```bash
bw unlock --raw > /tmp/bw.session
export BW_SESSION="$(cat /tmp/bw.session)"

bw create item "$(jq -n \
  --arg name "gh-investing-AI_SLACK_BOT_TOKEN" \
  --arg pw "$(read -rs -p 'paste AI_SLACK_BOT_TOKEN: ' v && echo "$v"; echo >&2)" \
  '{type:1, name:$name, login:{password:$pw}, notes:"GH Actions legacy token, scheduled for Phase 4 deletion 2026-06-08"}' \
  | base64)"

# Repeat for OPENCLAW_SLACK_BOT_TOKEN
```

## 4. Restore Test (mandatory before Phase 4 proceeds)

The goal: prove the round-trip vault → `gh secret set` works for at least
one of the 2 tokens. This test uses a throwaway secret name so the live
secrets remain untouched.

```bash
# 1) Pick one token (e.g. AI_SLACK_BOT_TOKEN) and retrieve from vault
case "$VAULT_TYPE" in
  1password) VALUE="$(op item get 'gh-investing-AI_SLACK_BOT_TOKEN' --field credential --reveal)" ;;
  sops)      VALUE="$(sops --decrypt ~/Documents/vault/slack-legacy-2026-06-01.yaml.enc | yq '.AI_SLACK_BOT_TOKEN')" ;;
  bitwarden) VALUE="$(bw get password 'gh-investing-AI_SLACK_BOT_TOKEN')" ;;
esac

# 2) Sanity check value length (Slack bot tokens are typically ~57 chars, prefix xoxb-)
[ "${#VALUE}" -gt 30 ] && [[ "$VALUE" == xoxb-* ]] && echo "OK: shape looks like Slack bot token"

# 3) Register a TEST secret with a unique name
TEST_NAME="VAULT_RESTORE_TEST_$(date -u +%Y%m%d%H%M%S)"
printf '%s' "$VALUE" | gh secret set "$TEST_NAME" --repo Twodragon0/investing --body -

# 4) Confirm secret was created
gh secret list --repo Twodragon0/investing --json name -q '.[].name' | grep -qx "$TEST_NAME" && echo "OK: test secret created"

# 5) Clean up immediately
gh secret delete "$TEST_NAME" --repo Twodragon0/investing
echo "OK: test secret removed"

# 6) Wipe local copy
unset VALUE
```

If any step fails → STOP. Phase 4 must not proceed until restore is proven.

## 5. Acceptance Gate for Phase 4

Before running `scripts/migrate_slack_naming.sh --phase=4 --apply`, all of
the following must be true:

- [ ] Both legacy tokens are stored in vault under `gh-investing-<NAME>`.
- [ ] At least 1 restore test (§4) completed successfully today.
- [ ] Snapshot file path (for SOPS) or vault item URLs (for 1Password/Bitwarden) is recorded in the team runbook (not in git).
- [ ] D+7 has elapsed since Phase 2 merge.
- [ ] Slack post success rate over the past 7 days ≥ baseline (no regression).
- [ ] `--vault=PATH` argument points to an existing non-empty file (the migration script enforces this).

## 6. Recovery Path (if Phase 4 destroys data unexpectedly)

```bash
# 1) Pull value from vault
VALUE="$(op item get 'gh-investing-AI_SLACK_BOT_TOKEN' --field credential --reveal)"

# 2) Re-register under the LEGACY name (so existing workflows resume)
printf '%s' "$VALUE" | gh secret set AI_SLACK_BOT_TOKEN --repo Twodragon0/investing --body -

# 3) Verify workflows that previously used this token
gh workflow run respond-ai-mentions.yml --repo Twodragon0/investing
gh run watch --repo Twodragon0/investing
```

If the vault is also lost → fall back to Slack App Management:

1. https://api.slack.com/apps → select "Investing AI" or "OpenClaw" app.
2. OAuth & Permissions → Reinstall to Workspace.
3. Copy the new Bot User OAuth Token (starts with `xoxb-`).
4. Update both the vault entry and the GH secret with the new value.
5. Note: this invalidates the old token. Any process still using the old token will fail until restarted.

## 7. Cleanup (post Phase 4)

- Keep vault entries for at least 90 days as audit trail.
- Update entry tags from `migration-2026-06` to `archived-post-cleanup-2026-06`.
- After 90 days with no incident: delete vault entries.
