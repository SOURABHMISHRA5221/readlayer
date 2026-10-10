#!/usr/bin/env bash
# Local end-to-end harness (M7): Firestore + Auth emulators, seeded read-only from production,
# the API pointed at them (Vertex AI stays real, capped), and the web app in emulator mode.
# Nothing here writes to production. Ctrl+C stops everything.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
JAVA21="${JAVA21:-$HOME/.sdkman/candidates/java/21.0.12-amzn}"
export FIRESTORE_EMULATOR_HOST=127.0.0.1:8085
export FIREBASE_AUTH_EMULATOR_HOST=127.0.0.1:9099

cleanup() { kill 0 2>/dev/null || true; }
trap cleanup EXIT INT TERM

cd "$ROOT"
JAVA_HOME="$JAVA21" PATH="$JAVA21/bin:$PATH" \
  pnpm exec firebase emulators:start --project demo-readlayer --only firestore,auth &
for _ in $(seq 1 60); do
  curl -s -o /dev/null "http://$FIRESTORE_EMULATOR_HOST" && curl -s -o /dev/null "http://$FIREBASE_AUTH_EMULATOR_HOST" && break
  sleep 1
done

cd "$ROOT/apps/api"
SEED="$(uv run python -m scripts.seed_emulator)"
echo "$SEED"
BUDGET="$(echo "$SEED" | sed -n 's/^HARNESS_BUDGET_USD=//p')"

ENV=dev FIRESTORE_PROJECT=demo-readlayer FIREBASE_PROJECT=demo-readlayer \
  LLM_DAILY_BUDGET_USD="$BUDGET" uv run fastapi dev app/main.py --port 8000 &

cd "$ROOT"
VITE_USE_EMULATORS=1 pnpm --filter web dev &
wait
