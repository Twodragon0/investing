#!/usr/bin/env bash
set -euo pipefail

SCOPE="${VERCEL_SCOPE:-twodragon0s-projects}"
PROJECT="${VERCEL_PROJECT:-investing}"
TOKEN="${VERCEL_TOKEN:-}"

if ! command -v vercel >/dev/null 2>&1; then
  echo "Error: vercel CLI not found in PATH. Install with: npm i -g vercel" >&2
  exit 127
fi

TOKEN_ARGS=()
if [ -n "$TOKEN" ]; then
  TOKEN_ARGS=(--token "$TOKEN")
fi

if [ -f ".vercel/project.json" ]; then
  detected_project=$(python3 - <<'PY'
import json
from pathlib import Path
path = Path('.vercel/project.json')
if path.exists():
    data = json.loads(path.read_text(encoding='utf-8'))
    print(data.get('projectName', ''))
PY
)
  if [ -n "${detected_project:-}" ]; then
    PROJECT="$detected_project"
  fi
fi

cmd="${1:-help}"
shift || true

case "$cmd" in
  whoami)
    vercel whoami "${TOKEN_ARGS[@]}"
    ;;
  pull)
    vercel pull --yes --scope "$SCOPE" "${TOKEN_ARGS[@]}"
    ;;
  ls)
    vercel ls "$PROJECT" --scope "$SCOPE" "${TOKEN_ARGS[@]}" "$@"
    ;;
  inspect)
    target="${1:-$PROJECT}"
    shift || true
    vercel inspect "$target" --scope "$SCOPE" "${TOKEN_ARGS[@]}" "$@"
    ;;
  deploy)
    vercel --prod --scope "$SCOPE" "${TOKEN_ARGS[@]}" "$@"
    ;;
  link)
    vercel link --scope "$SCOPE" "${TOKEN_ARGS[@]}" "$@"
    ;;
  context)
    echo "scope=$SCOPE"
    echo "project=$PROJECT"
    echo "token_set=$([ -n "$TOKEN" ] && echo true || echo false)"
    ;;
  *)
    echo "Usage: scripts/vercel_scope.sh {whoami|pull|ls|inspect|deploy|link|context} [args...]"
    echo "Env: VERCEL_SCOPE, VERCEL_PROJECT, VERCEL_TOKEN"
    exit 1
    ;;
esac
