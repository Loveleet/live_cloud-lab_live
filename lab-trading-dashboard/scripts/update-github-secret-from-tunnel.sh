#!/usr/bin/env bash
# Run on the CLOUD. Reads the tunnel URL from the log, updates GitHub secret API_BASE_URL,
# and triggers "Deploy frontend to GitHub Pages" so the site keeps working after reboot. No laptop needed.
#
# Requires: GH_TOKEN in /etc/lab-trading-dashboard.env (create at https://github.com/settings/tokens, repo scope)
# Optional: GITHUB_REPO (default: Loveleet/lab_live), GITHUB_DEPLOY_BRANCH (default: lab_live)

set -e
[ -f /etc/lab-trading-dashboard.env ] && set -a && . /etc/lab-trading-dashboard.env && set +a
LOG="${1:-/var/log/cloudflared-tunnel.log}"
REPO="${GITHUB_REPO:-Loveleet/lab_live}"
# Wait for URL to appear
for i in 1 2 3 4 5 6 7 8 9 10; do
  sleep 3
  [ -f "$LOG" ] || continue
  URL=$(grep -oE "https://[a-zA-Z0-9.-]+\.trycloudflare\.com" "$LOG" 2>/dev/null | tail -1)
  [ -n "$URL" ] && break
done
if [ -z "$URL" ]; then
  echo "No tunnel URL found in $LOG"
  exit 1
fi
echo "$URL" > /var/run/lab-tunnel-url 2>/dev/null || true
echo "Tunnel URL: $URL"
# Update GitHub secret and trigger frontend deploy (fully auto after reboot)
TOKEN="${GH_TOKEN:-$GITHUB_TOKEN}"
DEPLOY_BRANCH="${GITHUB_DEPLOY_BRANCH:-lab_live}"
if [ -n "$TOKEN" ]; then
  if command -v gh &>/dev/null; then
    if GH_TOKEN="$TOKEN" gh secret set API_BASE_URL --body "$URL" --repo "$REPO"; then
      echo "Updated GitHub secret API_BASE_URL"
      # Trigger frontend deploy so the new build uses the new URL (no laptop needed)
      GH_TOKEN="$TOKEN" gh workflow run "Deploy frontend to GitHub Pages" --ref "$DEPLOY_BRANCH" --repo "$REPO" && echo "Triggered Deploy frontend to GitHub Pages on $DEPLOY_BRANCH"
    fi
  else
    echo "Install gh CLI to auto-update GitHub secret: apt install gh"
  fi
else
  echo "Set GH_TOKEN in /etc/lab-trading-dashboard.env to auto-update GitHub secret."
fi
