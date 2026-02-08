#!/usr/bin/env bash
# Run FROM LAPTOP (one time). Copies service + scripts to cloud and enables the tunnel service.
# After this, the tunnel runs on the cloud automatically; laptop is not needed.
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# Project root = parent of scripts (lab-trading-dashboard)
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"
# Load .env from project root or parent (lab_live)
[ -f .env ] && set -a && . ./.env && set +a
[ -f ../.env ] && set -a && . ../.env && set +a
DEPLOY_HOST="${DEPLOY_HOST:?}"
APP_DIR="/opt/apps/lab-trading-dashboard"
SERVICE_NAME="cloudflared-tunnel"

echo "→ Copying tunnel service and scripts to cloud..."
SSHPASS="${DEPLOY_PASSWORD}" sshpass -e scp -o StrictHostKeyChecking=no \
  "$SCRIPT_DIR/cloudflared-tunnel.service" \
  "$SCRIPT_DIR/update-github-secret-from-tunnel.sh" \
  "$DEPLOY_HOST:/tmp/"

echo "→ Installing and enabling tunnel service on cloud..."
SSHPASS="$DEPLOY_PASSWORD" sshpass -e ssh -o StrictHostKeyChecking=no "$DEPLOY_HOST" "
  sudo mv /tmp/cloudflared-tunnel.service /etc/systemd/system/
  sudo mv /tmp/update-github-secret-from-tunnel.sh $APP_DIR/scripts/
  sudo chmod +x $APP_DIR/scripts/update-github-secret-from-tunnel.sh
  sudo systemctl daemon-reload
  sudo systemctl enable $SERVICE_NAME
  sudo systemctl restart $SERVICE_NAME
  echo 'Waiting for tunnel URL (20s)...'
  sleep 20
  $APP_DIR/scripts/update-github-secret-from-tunnel.sh
"
echo ""
echo "→ If you see 'Tunnel URL: https://...' above, add that URL to GitHub:"
echo "  https://github.com/Loveleet/lab_live/settings/secrets/actions → API_BASE_URL"
echo "Then run Actions → Deploy frontend to GitHub Pages. Laptop not needed after that."
