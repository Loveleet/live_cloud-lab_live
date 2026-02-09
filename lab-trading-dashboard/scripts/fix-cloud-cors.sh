#!/usr/bin/env bash
# Quick fix: Deploy latest server.js to cloud so GitHub Pages works (CORS + olab DB)

set -e
CLOUD_HOST="${DEPLOY_HOST:-root@150.241.244.130}"
SERVER_PATH="/opt/apps/lab-trading-dashboard/server"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "→ Deploying server.js to cloud for GitHub Pages CORS fix..."
echo "→ Target: $CLOUD_HOST:$SERVER_PATH"

# Copy server.js
scp "$REPO_ROOT/server/server.js" "$CLOUD_HOST:$SERVER_PATH/server.js"

echo "→ Restarting Node app on cloud..."
ssh "$CLOUD_HOST" "
  if systemctl is-active --quiet lab-trading-dashboard 2>/dev/null; then
    sudo systemctl restart lab-trading-dashboard
    echo '✅ Restarted lab-trading-dashboard service'
  else
    pkill -f 'node.*server.js' || true
    cd $SERVER_PATH && nohup node server.js >> /tmp/lab-dashboard.log 2>&1 &
    echo '✅ Started Node server in background'
  fi
  sleep 2
  echo '→ Testing server config...'
  curl -s http://localhost:10000/api/server-info | python3 -m json.tool 2>/dev/null || curl -s http://localhost:10000/api/server-info
"

echo ""
echo "✅ Done. Check output above - should show:"
echo "   - hasGitHubPagesOrigin: true"
echo "   - database: olab"
echo ""
echo "Then hard-refresh GitHub Pages: https://loveleet.github.io/lab_live/"
