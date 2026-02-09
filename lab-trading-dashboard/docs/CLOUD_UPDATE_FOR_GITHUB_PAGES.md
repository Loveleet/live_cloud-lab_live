# Fix cloud server so GitHub Pages shows data

When GitHub Pages (loveleet.github.io/lab_live) shows "No trade records" and zeros, the app is calling your Cloudflare tunnel → cloud server. The **cloud** must run the latest `server.js` and use the **olab** database.

## 1. Deploy latest server to the cloud

From your laptop (in repo `lab-trading-dashboard`):

```bash
export DEPLOY_HOST=root@150.241.244.130
./scripts/deploy-to-server.sh
```

Or copy the server manually:

```bash
scp server/server.js root@150.241.244.130:/opt/apps/lab-trading-dashboard/server/
ssh root@150.241.244.130 "sudo systemctl restart lab-trading-dashboard"
```

## 2. Cloud env: use database **olab** (real data)

On the cloud, if you use an env file (e.g. `/etc/lab-trading-dashboard.env`), set:

- **DB_NAME=olab** (real trading data; `labdb2` has only demo/seed rows)
- Optionally **DB_HOST=localhost** if PostgreSQL runs on the same machine

Example:

```bash
# On cloud: sudo nano /etc/lab-trading-dashboard.env
DB_HOST=localhost
DB_NAME=olab
DB_USER=lab
DB_PASSWORD=IndiaNepal1-
```

If you **don’t** set any DB_* vars, the server defaults to host **150.241.244.130** and database **olab** (correct for real data).

## 3. Restart the app on the cloud

```bash
sudo systemctl restart lab-trading-dashboard
# Wait ~10s, then check:
curl -s http://localhost:10000/api/health
curl -s http://localhost:10000/api/server-info
curl -s http://localhost:10000/api/trades | head -c 300
```

## 4. Verify config

- **GET /api/server-info** should show:
  - `hasGitHubPagesOrigin: true`
  - `database: "olab"`
  - `message: "Cloud server config OK for GitHub Pages (CORS + olab)"`

- **GET /api/trades** should return a non‑empty `trades` array (e.g. 1000+ rows).

Via tunnel (from browser or laptop):

```text
https://YOUR-TUNNEL.trycloudflare.com/api/server-info
https://YOUR-TUNNEL.trycloudflare.com/api/trades
```

## 5. GitHub Pages

- Ensure GitHub secret **API_BASE_URL** = your current Cloudflare tunnel URL (e.g. `https://xxxx.trycloudflare.com`).
- Redeploy frontend (push to main or run “Deploy frontend to GitHub Pages”).
- Open https://loveleet.github.io/lab_live/ and hard‑refresh (Ctrl+Shift+R).

If the cloud has the latest server (CORS + olab) and the tunnel points at it, GitHub Pages will show real data.
