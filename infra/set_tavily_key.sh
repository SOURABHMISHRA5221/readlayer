#!/usr/bin/env bash
# Replace the Tavily API key: a new Secret Manager version of `tavily-api-key`, then a new Cloud
# Run revision so the API picks it up, and (optionally) the local apps/api/.env.
#
#   bash infra/set_tavily_key.sh
#
# The key is typed or pasted at a hidden prompt; it is never echoed, written to a file other than
# Secret Manager (and .env if you say yes), or kept in shell history.
set -euo pipefail

ACCOUNT="sourabhlocalllm@gmail.com"
PROJECT="readlayer-sourabh-26"
REGION="asia-south1"
SERVICE="readlayer-api"
SECRET="tavily-api-key"
export CLOUDSDK_CONFIG="${CLOUDSDK_CONFIG:-$HOME/.config/gcloud-readlayer}"

now="$(gcloud config list --format='value(core.account,core.project)' | tr '\t' ' ')"
if [[ "$now" != "$ACCOUNT $PROJECT" ]]; then
  echo "Stopping: gcloud is on '$now', expected '$ACCOUNT $PROJECT'." >&2
  exit 1
fi

read -r -s -p "Paste the new Tavily API key (hidden), then Enter: " KEY
echo
KEY="$(printf '%s' "$KEY" | tr -d '[:space:]')"
if [[ ! "$KEY" =~ ^tvly-[A-Za-z0-9_-]{10,}$ ]]; then
  echo "That doesn't look like a Tavily key (it should start with 'tvly-'). Nothing changed." >&2
  exit 1
fi

printf '%s' "$KEY" | gcloud secrets versions add "$SECRET" --project "$PROJECT" --data-file=- >/dev/null
echo "Added a new version of $SECRET."

# A new revision reads the secret's latest version (the deploy pins TAVILY_API_KEY to :latest).
gcloud run services update "$SERVICE" --region "$REGION" --project "$PROJECT" \
  --update-secrets "TAVILY_API_KEY=$SECRET:latest" --quiet >/dev/null
echo "Cloud Run $SERVICE now runs revision $(gcloud run services describe "$SERVICE" --region "$REGION" \
  --project "$PROJECT" --format='value(status.latestReadyRevisionName)')."

ENV_FILE="$(cd "$(dirname "$0")/.." && pwd)/apps/api/.env"
if [[ -f "$ENV_FILE" ]]; then
  read -r -p "Also update TAVILY_API_KEY in apps/api/.env for local runs? [y/N] " yn
  if [[ "$yn" =~ ^[Yy]$ ]]; then
    tmp="$(mktemp)"
    grep -v '^TAVILY_API_KEY=' "$ENV_FILE" > "$tmp" || true
    printf 'TAVILY_API_KEY=%s\n' "$KEY" >> "$tmp"
    cat "$tmp" > "$ENV_FILE" && rm -f "$tmp"
    echo "Updated apps/api/.env."
  fi
fi

unset KEY
echo "Done. Old secret versions stay enabled; disable them in Secret Manager once this works."
