#!/usr/bin/env bash
# Run this ON THE CLOUD SERVER (150.241.244.130) to expose the API over HTTPS
# so https://loveleet.github.io/lab_live/ can load data (no mixed-content block).
#
# Usage on cloud: sudo bash start-https-tunnel-for-pages.sh
# Then copy the https://xxx.trycloudflare.com URL into GitHub secret API_BASE_URL and redeploy.

set -e
PORT="${1:-10000}"

echo "→ Installing cloudflared if needed..."
if ! command -v cloudflared &>/dev/null; then
  if command -v apt-get &>/dev/null; then
    curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg | sudo tee /usr/share/keyrings/cloudflare-main.gpg >/dev/null
    echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared jammy main" | sudo tee /etc/apt/sources.list.d/cloudflared.list >/dev/null
    sudo apt-get update -qq && sudo apt-get install -y cloudflared
  else
    echo "Install cloudflared manually: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/download-and-install/"
    exit 1
  fi
fi

echo "→ Starting HTTPS tunnel to http://localhost:$PORT"
echo "  Copy the https://xxx.trycloudflare.com URL below into GitHub → Settings → Secrets → API_BASE_URL"
echo "  Then run the 'Deploy frontend to GitHub Pages' workflow (or push to lab_live)."
echo ""
exec cloudflared tunnel --url "http://localhost:$PORT"
