#!/usr/bin/env bash
# Run from your laptop: copies setup script to the server and runs it there.
# Requires in .env:  DEPLOY_HOST=ubuntu@YOUR_SERVER_IP
# Optional in .env: REPO_URL=https://github.com/Loveleet/lab_live.git

set -euo pipefail
cd "$(dirname "$0")/.."

if [ -f .env ]; then
  set -a
  . ./.env
  set +a
fi
REPO_URL="${REPO_URL:-https://github.com/Loveleet/lab_live.git}"

if [ -z "${DEPLOY_HOST:-}" ]; then
  echo "Add your server to .env first:"
  echo "  echo 'DEPLOY_HOST=ubuntu@YOUR_SERVER_IP' >> .env"
  echo "Then run: ./scripts/run-setup-on-cloud.sh"
  exit 1
fi

echo "→ Copying setup script to $DEPLOY_HOST ..."
scp scripts/setup-server-once.sh "$DEPLOY_HOST:/tmp/"

echo "→ Running one-time setup on server (install Node, clone repo, systemd) ..."
ssh "$DEPLOY_HOST" "REPO_URL=$REPO_URL /bin/bash /tmp/setup-server-once.sh"

echo ""
echo "Done. API should be running on the server. Add GitHub Secrets (SSH_HOST, SSH_USER, SSH_KEY) for push-to-deploy."
