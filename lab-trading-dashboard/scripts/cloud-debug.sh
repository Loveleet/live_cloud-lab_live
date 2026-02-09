#!/usr/bin/env bash
# Run this ON the cloud server (e.g. after: ssh root@150.241.244.130)
# Usage: ./scripts/cloud-debug.sh   or   bash scripts/cloud-debug.sh
# No credentials in this script — uses whatever env the app uses.

set -e
API_PORT="${API_PORT:-10000}"
BASE="http://127.0.0.1:${API_PORT}"

echo "=== Cloud API debug ($(hostname)) ==="
echo ""

echo "--- Environment (no secrets) ---"
echo "DATABASE_URL set: $([ -n \"$DATABASE_URL\" ] && echo yes || echo no)"
echo "DB_HOST: ${DB_HOST:-<not set>}"
echo "DB_NAME: ${DB_NAME:-<not set>}"
echo "DB_PORT: ${DB_PORT:-<not set>}"
echo "DB_USER: ${DB_USER:-<not set>}"
echo "NODE_ENV: ${NODE_ENV:-<not set>}"
echo ""

echo "--- Health Check ---"
curl -sS -o /dev/null -w "%{http_code}" "$BASE/api/health" && echo " ✅ $BASE/api/health" || echo " ❌ FAIL $BASE/api/health"
echo ""

echo "--- Database Debug (table counts + schema) ---"
curl -sS "$BASE/api/debug" 2>/dev/null | python3 -m json.tool 2>/dev/null || curl -sS "$BASE/api/debug" 2>/dev/null
echo ""

echo "--- Database Test (sample data) ---"
curl -sS "$BASE/api/test-db" 2>/dev/null | python3 -m json.tool 2>/dev/null || curl -sS "$BASE/api/test-db" 2>/dev/null
echo ""

echo "--- Trades API Response ---"
TRADES_RESPONSE=$(curl -sS "$BASE/api/trades" 2>/dev/null)
TRADES_COUNT=$(echo "$TRADES_RESPONSE" | grep -o '"count":[0-9]*' | grep -o '[0-9]*' | head -1 || echo "unknown")
echo "Trades count: ${TRADES_COUNT}"
echo "Response preview (first 300 chars):"
echo "$TRADES_RESPONSE" | head -c 300
echo ""
echo ""

echo "--- Process Check ---"
if pgrep -af "node.*server" > /dev/null 2>&1; then
  echo "✅ Node server process found:"
  pgrep -af "node.*server" 2>/dev/null | head -2
else
  echo "❌ No node server process found."
fi
echo ""

echo "--- Port Check ---"
if netstat -tuln 2>/dev/null | grep -q ":${API_PORT} " || ss -tuln 2>/dev/null | grep -q ":${API_PORT} "; then
  echo "✅ Port ${API_PORT} is listening"
else
  echo "⚠️ Port ${API_PORT} is not listening (server may not be running)"
fi
echo ""

echo "Done. Share this output (without DATABASE_URL password) if you need help."
