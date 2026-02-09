# Make GitHub Pages work with data

To have **https://loveleet.github.io/lab_live/** show real data (not just the UI), the API must be reachable over **HTTPS**. Use a Cloudflare Tunnel so you don’t need a domain or nginx.

---

## Auto-update GitHub secret when tunnel restarts

**Already on the cloud:** `gh` is installed; `GH_TOKEN=` is in `/etc/lab-trading-dashboard.env`. To enable auto-update:

1. **Create a token:** https://github.com/settings/tokens → Generate new token (classic) → check **repo** (or fine-grained: Actions secrets read/write for Loveleet/lab_live).

2. **Set it on the cloud** (replace `ghp_YourTokenHere` with your token). Use `#` as delimiter so the token does not break sed:
   ```bash
   ssh root@150.241.244.130 'sudo sed -i "s#^GH_TOKEN=.*#GH_TOKEN=ghp_YourTokenHere#" /etc/lab-trading-dashboard.env'
   ```
   Or on the cloud: `sudo nano /etc/lab-trading-dashboard.env` and set `GH_TOKEN=ghp_xxxx`.

3. **Test:** Restart tunnel and run the script; you should see "Updated GitHub secret API_BASE_URL". Then run **Actions → Deploy frontend to GitHub Pages** once.

---

## Step 1: Expose the API over HTTPS

**Option 1 – From your laptop (one command):**

```bash
cd lab-trading-dashboard
./scripts/run-tunnel-from-laptop.sh
```

If the cloud has a broken `dpkg`, fix it first: `ssh root@150.241.244.130 "sudo dpkg --configure -a"`, then run the script again. The script will print the URL to add to GitHub.

**Option 2 – On the cloud server (SSH in first):**

```bash
# From your laptop (optional): copy the script to the cloud and run it
# scp -r lab-trading-dashboard/scripts root@150.241.244.130:/tmp/
# ssh root@150.241.244.130 "bash /tmp/scripts/start-https-tunnel-for-pages.sh"

# Or on the cloud server directly (if the repo is there):
cd /opt/apps/lab-trading-dashboard
sudo bash scripts/start-https-tunnel-for-pages.sh
```

Or install and run cloudflared manually:

```bash
# On the cloud (Ubuntu):
sudo apt-get update && sudo apt-get install -y curl
curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg | sudo tee /usr/share/keyrings/cloudflare-main.gpg >/dev/null
echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared jammy main" | sudo tee /etc/apt/sources.list.d/cloudflared.list
sudo apt-get update && sudo apt-get install -y cloudflared
cloudflared tunnel --url http://localhost:10000
```

**Copy the HTTPS URL** that appears (e.g. `https://abc-xyz-123.trycloudflare.com`). Leave the terminal running (or run it in tmux/screen so it keeps running).

---

## Step 2: Set the URL in GitHub

**Or get current URL from the cloud:** http://150.241.244.130:10000/api/tunnel-url

1. Open **https://github.com/Loveleet/lab_live** → **Settings** → **Secrets and variables** → **Actions**.
2. Click **New repository secret** (or edit existing).
3. **Name:** `API_BASE_URL`
4. **Value:** the URL you copied, e.g. `https://abc-xyz-123.trycloudflare.com` (no trailing slash).
5. Save.

---

## Step 3: Redeploy the frontend

So the new build uses the HTTPS API URL:

- **Option A:** Push any commit to `lab_live` (e.g. an empty commit: `git commit --allow-empty -m "Use HTTPS API" && git push origin lab_live`).
- **Option B:** **Actions** → **Deploy frontend to GitHub Pages** → **Run workflow** (branch: lab_live).

Wait for the workflow to finish (green).

---

## Step 4: Open the dashboard

Open **https://loveleet.github.io/lab_live/** and do a hard refresh (Ctrl+Shift+R / Cmd+Shift+R). Data should load.

---

## If the tunnel stops

The **quick tunnel** URL (trycloudflare.com) changes every time you restart `cloudflared`. If you restart the tunnel:

1. Copy the new HTTPS URL.
2. Update the **API_BASE_URL** secret in GitHub with that URL.
3. Run the **Deploy frontend to GitHub Pages** workflow again (or push a commit).

If the cloud runs `update-github-secret-from-tunnel.sh` (e.g. from cron), it will update the secret and trigger **Update API config**, which then triggers **Deploy frontend to GitHub Pages** so gh-pages gets the new URL automatically.

To keep a **stable URL**, use a [Cloudflare named tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/do-more-with-tunnels/tunnel-useful-terms/) with a free Cloudflare account.

---

## Troubleshooting: GitHub Pages shows "No trade records"

1. **api-config.json** – The frontend loads `https://loveleet.github.io/lab_live/api-config.json`. The deploy workflow writes this file and places it under the base path; after deploy it should be there. If the console shows "api-config.json not found", set **API_BASE_URL** to your tunnel HTTPS URL in repo Secrets and run **Deploy frontend to GitHub Pages** again.

2. **CORS** – The cloud server (150.241.244.130) must allow origin `https://loveleet.github.io`. The repo’s `server/server.js` includes this in `allowedOrigins`. Deploy the latest server to the cloud and restart (see **docs/CLOUD_UPDATE_FOR_GITHUB_PAGES.md**).

3. **Database** – The cloud server must use the **olab** database (real data). Set **DB_NAME=olab** in the cloud env (or leave DB_* unset so the server defaults to olab). See **docs/CLOUD_UPDATE_FOR_GITHUB_PAGES.md**.

4. **Verify** – Open `https://YOUR-TUNNEL.trycloudflare.com/api/server-info` in the browser. It should show `hasGitHubPagesOrigin: true` and `database: "olab"`. Then open `https://YOUR-TUNNEL.trycloudflare.com/api/trades` and confirm it returns a non-empty `trades` array.
