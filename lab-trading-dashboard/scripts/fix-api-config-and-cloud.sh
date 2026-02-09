#!/usr/bin/env bash
# Run FROM LAPTOP (one time). Copies update + cron scripts to cloud and installs cron
# so after cloud restart the new tunnel URL is synced to GitHub (secret + api-config.json on gh-pages).
# Pages URL: https://loveleet.github.io/lab_live/
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"
[ -f .env ] && set -a && . ./.env && set +a
[ -f ../.env ] && set -a && . ../.env && set +a
DEPLOY_HOST="${DEPLOY_HOST:?}"
APP_DIR="/opt/apps/lab-trading-dashboard"

echo "→ Copying scripts to cloud..."
SSHPASS="${DEPLOY_PASSWORD}" sshpass -e scp -o StrictHostKeyChecking=no \
  "$SCRIPT_DIR/update-github-secret-from-tunnel.sh" \
  "$SCRIPT_DIR/cron-tunnel-update.sh" \
  "$SCRIPT_DIR/install-cron-tunnel-update.sh" \
  "$DEPLOY_HOST:/tmp/"

echo "→ Installing scripts and cron on cloud..."
SSHPASS="$DEPLOY_PASSWORD" sshpass -e ssh -o StrictHostKeyChecking=no "$DEPLOY_HOST" "
  sudo mkdir -p $APP_DIR/scripts
  sudo mv /tmp/update-github-secret-from-tunnel.sh $APP_DIR/scripts/
  sudo mv /tmp/cron-tunnel-update.sh $APP_DIR/scripts/
  sudo mv /tmp/install-cron-tunnel-update.sh $APP_DIR/scripts/
  sudo chmod +x $APP_DIR/scripts/update-github-secret-from-tunnel.sh
  sudo chmod +x $APP_DIR/scripts/cron-tunnel-update.sh
  sudo chmod +x $APP_DIR/scripts/install-cron-tunnel-update.sh
  $APP_DIR/scripts/install-cron-tunnel-update.sh
"
echo "→ Done. Set GH_TOKEN (and optional GITHUB_REPO) in /etc/lab-trading-dashboard.env on the cloud. After reboot, open https://loveleet.github.io/lab_live/ (frontend picks up new URL from api-config.json)."
