# Debug GitHub Pages Not Showing Data

When **https://loveleet.github.io/lab_live/** shows "No trade records" but local works, follow this checklist.

---

## Step 1: Check Browser Console (on GitHub Pages)

Open **https://loveleet.github.io/lab_live/** → **F12** → **Console** tab. Look for:

1. **`[LAB] API base URL (build-time):`** — Should show your Cloudflare tunnel URL (e.g. `https://xxx.trycloudflare.com`). If empty, **api-config.json** didn't load or **API_BASE_URL** secret isn't set.

2. **`[LAB] Fetching api-config.json:`** — Should show `https://loveleet.github.io/lab_live/api-config.json`. If you see **404**, the file wasn't deployed correctly.

3. **`[LAB] api-config.json loaded, API base:`** — Should show the tunnel URL. If missing, the file exists but is empty or malformed.

4. **`[DEBUG] Fetching trades from:`** — Should show full URL like `https://xxx.trycloudflare.com/api/trades`.

5. **`[DEBUG] Trades response status:`** — Check the status:
   - **200 OK** → API works, but data might be empty (check cloud DB).
   - **CORS error** → Cloud server doesn't allow `https://loveleet.github.io` (update server.js on cloud).
   - **404 / ERR_NAME_NOT_RESOLVED** → Tunnel URL is wrong or tunnel is down.
   - **Network error** → Tunnel not forwarding or cloud server down.

6. **Click "Test /api/server-info"** button (debug panel) — Should return JSON with:
   - `hasGitHubPagesOrigin: true`
   - `database: "olab"`
   - `requestOriginAllowed: true`

---

## Step 2: Verify api-config.json is Deployed

Open in browser: **https://loveleet.github.io/lab_live/api-config.json**

Should return JSON like:
```json
{
  "apiBaseUrl": "https://xxx.trycloudflare.com",
  "tunnelUrl": "https://xxx.trycloudflare.com"
}
```

If **404**: The deploy workflow didn't place it correctly. Check:
- **GitHub Actions** → **Deploy frontend to GitHub Pages** → latest run → check if "Place api-config.json under base path" step succeeded.
- The workflow should copy `dist/api-config.json` to `dist/lab_live/api-config.json`.

If **empty `{}`**: **API_BASE_URL** secret isn't set in GitHub.

---

## Step 3: Verify Cloud Server Config

**On the cloud (150.241.244.130):**

```bash
# Check server is running latest code
curl -s http://localhost:10000/api/server-info | python3 -m json.tool

# Should show:
# - "hasGitHubPagesOrigin": true
# - "database": "olab"
# - "allowedOrigins": [..., "https://loveleet.github.io", ...]
```

If **hasGitHubPagesOrigin: false** or **database: "labdb2"**:
1. Deploy latest `server/server.js` to cloud (has CORS + olab default).
2. Restart: `sudo systemctl restart lab-trading-dashboard` (or however you run it).

---

## Step 4: Test Tunnel → Cloud Connection

From your laptop (or browser):

```bash
# Replace YOUR-TUNNEL-URL with actual tunnel URL
curl -s https://YOUR-TUNNEL-URL.trycloudflare.com/api/server-info | python3 -m json.tool
curl -s https://YOUR-TUNNEL-URL.trycloudflare.com/api/trades | python3 -m json.tool | head -20
```

Should return:
- **server-info**: Shows CORS + DB config.
- **trades**: Non-empty `trades` array (1000+ rows if using olab).

If **CORS error** in browser console but curl works: The tunnel forwards correctly, but the cloud server's CORS doesn't allow `https://loveleet.github.io`. Update server.js on cloud.

If **404 / ERR_NAME_NOT_RESOLVED**: Tunnel URL changed or tunnel is down. Get new URL and update **API_BASE_URL** secret.

---

## Step 5: Verify GitHub Secret

**GitHub repo** → **Settings** → **Secrets and variables** → **Actions** → Check **API_BASE_URL**:

- Value should be your **current Cloudflare tunnel HTTPS URL** (e.g. `https://xxx.trycloudflare.com`, **no trailing slash**).
- If tunnel restarted, update this secret, then run **Deploy frontend to GitHub Pages** workflow.

---

## Step 6: Redeploy Frontend

After fixing any issues above:

1. **Push** code changes (or run **Deploy frontend to GitHub Pages** workflow manually).
2. Wait for workflow to finish (green checkmark).
3. **Hard refresh** GitHub Pages: **Ctrl+Shift+R** (or **Cmd+Shift+R** on Mac).

---

## Common Issues & Fixes

| Issue | Cause | Fix |
|-------|-------|-----|
| Console: "API base URL (build-time): (empty)" | api-config.json not loading or API_BASE_URL secret not set | Set **API_BASE_URL** secret, redeploy frontend |
| Console: "api-config.json not found (404)" | File not placed under `/lab_live/` | Check deploy workflow step "Place api-config.json under base path" |
| Console: "CORS blocked origin" | Cloud server doesn't allow `https://loveleet.github.io` | Deploy latest `server.js` (has CORS fix), restart cloud server |
| Console: "Trades response status: 200" but empty `trades: []` | Cloud server using wrong DB (`labdb2` instead of `olab`) | Set **DB_NAME=olab** in cloud env, or deploy server.js (defaults to olab) |
| Console: "ERR_NAME_NOT_RESOLVED" | Tunnel URL changed or tunnel down | Get new tunnel URL, update **API_BASE_URL** secret, redeploy |
| Debug panel: "Test /api/server-info" shows `hasGitHubPagesOrigin: false` | Cloud server running old code | Deploy latest `server/server.js`, restart |

---

## Quick Test Commands

**From browser console on GitHub Pages:**

```javascript
// Check API base
console.log("API Base:", getApiBaseUrl());

// Test server-info
fetch(api("/api/server-info")).then(r => r.json()).then(console.log);

// Test trades
fetch(api("/api/trades")).then(r => r.json()).then(d => console.log("Trades:", d.trades.length));
```

---

## Still Not Working?

1. **Check cloud logs**: `ssh root@150.241.244.130 "journalctl -u lab-trading-dashboard -n 50"` (or wherever logs are).
2. **Check tunnel is running**: `ssh root@150.241.244.130 "ps aux | grep cloudflared"`.
3. **Verify tunnel URL**: `ssh root@150.241.244.130 "cat /var/run/lab-tunnel-url"` (if script writes it there).
4. **Test direct cloud API** (bypass tunnel): `curl http://150.241.244.130:10000/api/trades` — should work from your laptop if firewall allows.
