#!/usr/bin/env bash
# Run from your LAPTOP. SSHs to the cloud, starts the HTTPS tunnel, and prints the URL
# to add to GitHub secret API_BASE_URL so loveleet.github.io/lab_live/ can load data.
#
# Usage: ./scripts/run-tunnel-from-laptop.sh
# Requires: .env with DEPLOY_HOST and DEPLOY_PASSWORD

set -e
cd "$(dirname "$0")/.."
[ -f .env ] && set -a && . ./.env && set +a

DEPLOY_HOST="${DEPLOY_HOST:?Set DEPLOY_HOST in .env}"
echo "→ Connecting to cloud and starting HTTPS tunnel (this may take ~30s)..."
echo ""

# Start cloudflared on the cloud in background, capture output to get URL
URL=$(SSHPASS="$DEPLOY_PASSWORD" sshpass -e ssh -o StrictHostKeyChecking=no "$DEPLOY_HOST" '
  command -v cloudflared &>/dev/null || {
    echo "Installing cloudflared..." >&2
    cd /tmp
    curl -sL "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64" -o cloudflared
    chmod +x cloudflared
    sudo mv cloudflared /usr/local/bin/cloudflared
  }
  pkill -f "cloudflared tunnel" 2>/dev/null || true
  sleep 1
  nohup cloudflared tunnel --url http://localhost:10000 > /tmp/tunnel.log 2>&1 &
  disown
  sleep 12
  grep -oE "https://[a-zA-Z0-9.-]+\.trycloudflare\.com" /tmp/tunnel.log | head -1
')

if [ -z "$URL" ]; then
  echo "Could not get tunnel URL. Run on the cloud manually:"
  echo "  ssh $DEPLOY_HOST"
  echo "  cloudflared tunnel --url http://localhost:10000"
  echo "  (then copy the https://... URL and add to GitHub → Settings → Secrets → API_BASE_URL)"
  exit 1
fi

echo "=============================================="
echo "Tunnel is running. Add this to GitHub:"
echo ""
echo "  1. Open: https://github.com/Loveleet/lab_live/settings/secrets/actions"
echo "  2. New repository secret (or edit API_BASE_URL)"
echo "     Name:  API_BASE_URL"
echo "     Value: $URL"
echo ""
echo "  3. Actions → Deploy frontend to GitHub Pages → Run workflow (branch: lab_live)"
echo "  4. When green, open https://loveleet.github.io/lab_live/ and hard-refresh"
echo "=============================================="
