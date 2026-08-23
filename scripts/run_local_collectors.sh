#!/usr/bin/env bash
set -euo pipefail

# Ensure robust PATH for macOS
export PATH="$HOME/.rbenv/shims:/opt/homebrew/bin:/opt/homebrew/sbin:$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
export TZ="Asia/Seoul"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# Load local environment variables
for env_file in "$HOME/Desktop/.env" "$HOME/.env" "$REPO_ROOT/.env"; do
  if [[ -f "$env_file" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$env_file" 2>/dev/null || true
    set +a
  fi
done

run_py() {
  if [[ -x ".venv/bin/python" ]]; then
    .venv/bin/python "$@"
  else
    python3 "$@"
  fi
}

ALL_COLLECTORS=(
  "scripts/collect_crypto_news.py"
  "scripts/collect_stock_news.py"
  "scripts/collect_coinmarketcap.py"
  "scripts/collect_worldmonitor_news.py"
  "scripts/collect_social_media.py"
  "scripts/collect_defi_llama.py"
  "scripts/collect_defi_yields.py"
  "scripts/collect_blockchain.py"
  "scripts/collect_geopolitical.py"
  "scripts/collect_political_trades.py"
  "scripts/collect_regulatory.py"
  "scripts/collect_fmp_calendar.py"
  "scripts/collect_market_indicators.py"
)

FAST_COLLECTORS=(
  "scripts/collect_crypto_news.py"
  "scripts/collect_stock_news.py"
  "scripts/collect_coinmarketcap.py"
  "scripts/collect_worldmonitor_news.py"
  "scripts/collect_social_media.py"
)

CRYPTO_COLLECTORS=(
  "scripts/collect_crypto_news.py"
  "scripts/collect_coinmarketcap.py"
  "scripts/collect_defi_llama.py"
  "scripts/collect_defi_yields.py"
  "scripts/collect_blockchain.py"
)

STOCK_COLLECTORS=(
  "scripts/collect_stock_news.py"
  "scripts/collect_fmp_calendar.py"
  "scripts/collect_market_indicators.py"
  "scripts/collect_political_trades.py"
  "scripts/collect_regulatory.py"
  "scripts/collect_geopolitical.py"
)

TARGETS=()

if [[ $# -eq 0 ]] || [[ "${1:-}" == "--fast" ]]; then
  TARGETS=("${FAST_COLLECTORS[@]}")
elif [[ "${1:-}" == "--all" ]]; then
  TARGETS=("${ALL_COLLECTORS[@]}")
elif [[ "${1:-}" == "--crypto" ]]; then
  TARGETS=("${CRYPTO_COLLECTORS[@]}")
elif [[ "${1:-}" == "--stocks" ]]; then
  TARGETS=("${STOCK_COLLECTORS[@]}")
else
  for arg in "$@"; do
    if [[ -f "scripts/$arg" ]]; then
      TARGETS+=("scripts/$arg")
    elif [[ -f "$arg" ]]; then
      TARGETS+=("$arg")
    else
      echo "Warning: script not found: $arg" >&2
    fi
  done
fi

echo "=================================================="
echo " [Investing] Local Collectors Runner"
echo " Time: $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo " Targets: ${#TARGETS[@]} collectors"
echo "=================================================="

SUCCESS_COUNT=0
FAILURE_COUNT=0
FAILED_SCRIPTS=()

for script in "${TARGETS[@]}"; do
  name="$(basename "$script")"
  echo ""
  echo ">>> Running $name..."
  START_TIME=$(date +%s)

  if run_py "$script"; then
    END_TIME=$(date +%s)
    DURATION=$((END_TIME - START_TIME))
    echo "✓ $name succeeded (${DURATION}s)"
    SUCCESS_COUNT=$((SUCCESS_COUNT + 1))
  else
    END_TIME=$(date +%s)
    DURATION=$((END_TIME - START_TIME))
    echo "✗ $name failed (${DURATION}s)" >&2
    FAILURE_COUNT=$((FAILURE_COUNT + 1))
    FAILED_SCRIPTS+=("$name")
  fi
done

echo ""
echo "=================================================="
echo " Summary: Total: ${#TARGETS[@]}, Success: $SUCCESS_COUNT, Failed: $FAILURE_COUNT"
if [[ $FAILURE_COUNT -gt 0 ]]; then
  echo " Failed scripts: ${FAILED_SCRIPTS[*]}"
fi
echo "=================================================="

exit "$FAILURE_COUNT"
