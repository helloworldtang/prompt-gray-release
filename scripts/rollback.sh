#!/bin/bash
# One-command rollback to the last stable prompt version.
#
# Usage: ./scripts/rollback.sh <git-ref> [gateway-base-url]
#
# Steps (in order, fail-fast):
#   1. Restore prompts/ from the given git ref and deploy them
#   2. Restart the service and switch traffic back to the stable prompt
#   3. Health-check the restarted service
#   4. Notify the team (Slack webhook via $SLACK_WEBHOOK_URL, optional)
set -euo pipefail

VERSION=${1:-}
GATEWAY=${2:-http://127.0.0.1:8080}
PROMPT_NAME=product_desc.txt
DEPLOY_DIR=${DEPLOY_DIR:-/data/prompts}
SERVICE=${SERVICE:-ai-bot}
SLACK_WEBHOOK_URL=${SLACK_WEBHOOK_URL:-}

if [ -z "$VERSION" ]; then
    echo "Usage: ./scripts/rollback.sh <git-ref> [gateway-base-url]"
    echo "Example: ./scripts/rollback.sh v1.4.2"
    exit 1
fi

echo "[1/4] restoring prompts from $VERSION ..."
git checkout "$VERSION" -- prompts/
cp "prompts/product_desc_v1.txt" "$DEPLOY_DIR/$PROMPT_NAME"

echo "[2/4] restarting $SERVICE and switching traffic back to stable ..."
systemctl restart "$SERVICE"
# The gateway itself is switched off the candidate prompt (mode=off means
# 100% stable); this also resets the rollout gauge in Grafana.
curl -sS -X POST "$GATEWAY/release/plan" \
    -H 'Content-Type: application/json' \
    -d '{"mode": "off", "treatment_permille": 0}' >/dev/null

echo "[3/4] health check ..."
sleep 5
health=$(curl -sS "$GATEWAY/health" | tr -d '\n')
if [ "$health" != '{"status":"OK"}' ]; then
    echo "Rollback FAILED: health endpoint returned '$health'" >&2
    exit 1
fi

echo "[4/4] notifying team ..."
if [ -n "$SLACK_WEBHOOK_URL" ]; then
    curl -sS -X POST "$SLACK_WEBHOOK_URL" \
        -H 'Content-Type: application/json' \
        -d "{\"text\":\"Prompt rolled back to $VERSION\"}" >/dev/null
else
    echo "SLACK_WEBHOOK_URL not set; skipping notification"
fi

echo "Rollback success: $VERSION (remember to write the post-mortem)"
