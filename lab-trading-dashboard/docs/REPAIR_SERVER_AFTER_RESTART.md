# Repair server.js on the cloud after a restart

If you restarted the server (or the machine) and **api.clubinfotech.com** or **/api/trade** is not working, follow these steps on the **cloud** to get the Node API (server.js) running again.

**Cloud server:** `root@150.241.244.130`

---

## 0. Transfer server.js (whenever you change it — not in Git)

**server.js is gitignored.** After any local change to `server/server.js`, copy it to the cloud and restart Node:

```bash
cd "/Volumes/Loveleet /Work/Binance/LAB_LIVE_NEW/lab_live/lab-trading-dashboard"
scp server/server.js root@150.241.244.130:/root/lab-trading-dashboard/server/
ssh root@150.241.244.130 "sudo systemctl restart lab-trading-dashboard"
```

See **[docs/TRANSFER_SERVER_JS_TO_CLOUD.md](TRANSFER_SERVER_JS_TO_CLOUD.md)** for the full reference.

---

## 1. Transfer scripts (from your laptop)

Run from the **lab-trading-dashboard** folder on your machine:

```bash
cd "/Volumes/Loveleet /Work/Binance/LAB_LIVE_NEW/lab_live/lab-trading-dashboard"

scp scripts/lab-trading-dashboard.service scripts/api-signals.service scripts/enable-services-on-boot.sh scripts/repair-and-start-server.sh scripts/check-python-signals-on-cloud.sh root@150.241.244.130:/root/lab-trading-dashboard/scripts/
```

---

## 2. Run on the cloud (SSH in, then run)

```bash
ssh root@150.241.244.130
```

Then on the server:

```bash
# Install/update systemd units
sudo cp /root/lab-trading-dashboard/scripts/lab-trading-dashboard.service /etc/systemd/system/
sudo cp /root/lab-trading-dashboard/scripts/api-signals.service /etc/systemd/system/
sudo systemctl daemon-reload

# Repair and start the Node API now
sudo bash /root/lab-trading-dashboard/scripts/repair-and-start-server.sh

# Enable on boot and restart on crash (do once)
sudo bash /root/lab-trading-dashboard/scripts/enable-services-on-boot.sh
```

**If "Information" and "Binance Data" sections don’t show (Loading signals… / Failed to fetch):** the UI gets that data from **api_signals.py**. Node must proxy to it. On the cloud, run the diagnostic first, then fix:

**Diagnose (on the cloud):**
```bash
bash /root/lab-trading-dashboard/scripts/check-python-signals-on-cloud.sh
```
This checks: (1) api-signals service running, (2) Python responding on port 5001, (3) Node has `PYTHON_SIGNALS_URL` in secrets.

**Fix:**

1. **Start the Python signals service** (and enable on boot):
   ```bash
   sudo systemctl start api-signals
   sudo systemctl enable api-signals
   ```
   If it fails to start, check logs: `sudo journalctl -u api-signals -n 50 --no-pager` (e.g. missing Python deps or wrong path).

2. **Tell Node where Python is** — create or edit `/etc/lab-trading-dashboard.secrets.env`:
   ```bash
   sudo nano /etc/lab-trading-dashboard.secrets.env
   ```
   Add (or uncomment) these lines:
   ```bash
   PYTHON_SIGNALS_URL=http://127.0.0.1:5001
   # If you see 401 Unauthorized on the dashboard, allow read-only signals without login:
   ALLOW_PUBLIC_READ_SIGNALS=true
   ```
   Save (Ctrl+O, Enter, Ctrl+X), then restart Node:
   ```bash
   sudo systemctl restart lab-trading-dashboard
   ```

3. **Confirm Node picked it up:**  
   `sudo journalctl -u lab-trading-dashboard -n 15 --no-pager` should show a line like `[SERVER] PYTHON_SIGNALS_URL = http://127.0.0.1:5001`.

After that, the Information and Binance Data sections should load (Node proxies `/api/calculate-signals` and `/api/open-position` to api_signals.py on port 5001).

**If the browser shows 404 for `/api/calculate-signals`:** the cloud is likely running an **old server.js** that doesn’t have the proxy route. Re-copy server.js and restart Node (see Section 0 above). Then open `https://api.clubinfotech.com/api/calculate-signals/health` in the browser: if you get `{"ok":true,"service":"calculate-signals"}`, the proxy is correct; if you get 502, Python (api_signals) is not running — start it with `sudo systemctl start api-signals`.

---

## Make it run on every reboot and crash (do this once)

So the website works **after every server restart** and **after crashes**:

1. **On the cloud server**, run the enable-on-boot script once:

   ```bash
   cd /root/lab-trading-dashboard
   sudo bash scripts/enable-services-on-boot.sh
   ```

   This enables **PostgreSQL** and **lab-trading-dashboard** to start on boot. The Node service is already configured to **restart on crash** (systemd `Restart=always`).

2. If the systemd unit is not installed yet, copy it and reload first:

   ```bash
   sudo cp /root/lab-trading-dashboard/scripts/lab-trading-dashboard.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo bash /root/lab-trading-dashboard/scripts/enable-services-on-boot.sh
   ```

After this, a reboot should bring up the API and DB automatically. If the Node process crashes, systemd will restart it.

---

## Option 1: Run the repair script (recommended)

From your **laptop**, copy the script to the cloud and run it there:

```bash
# Copy the script to the cloud (from your repo: lab-trading-dashboard/)
scp scripts/repair-and-start-server.sh root@150.241.244.130:/root/lab-trading-dashboard/scripts/

# SSH in and run it
ssh root@150.241.244.130 "cd /root/lab-trading-dashboard && sudo bash scripts/repair-and-start-server.sh"
```

Or, if you’re **already on the cloud** (e.g. after `ssh root@150.241.244.130`):

```bash
cd /root/lab-trading-dashboard
sudo bash scripts/repair-and-start-server.sh
```

The script will:

- Check Node is installed
- Check `server/server.js` exists
- Run `npm install` if `node_modules` is missing
- Restart the `lab-trading-dashboard` systemd service
- Report success or show how to check logs

---

## Option 2: Manual steps

### 1. SSH to the cloud

```bash
ssh root@150.241.244.130
```

### 2. Check if the service exists and its status

```bash
sudo systemctl status lab-trading-dashboard
```

- If you see **"Unit lab-trading-dashboard.service could not be found"**, install the unit file (see step 5).
- If it’s **inactive/failed**, continue below.

### 3. Ensure app and dependencies are present

```bash
cd /root/lab-trading-dashboard
ls -la server/server.js
ls -la node_modules/express
```

- If `server/server.js` is missing, copy it from your repo (from your laptop):

  ```bash
  # From your laptop, in the repo:
  rsync -avz lab-trading-dashboard/server/ root@150.241.244.130:/root/lab-trading-dashboard/server/
  ```

- If `node_modules` is missing or broken:

  ```bash
  cd /root/lab-trading-dashboard
  npm install --production
  ```

### 4. Ensure the service file is up to date

The service should run from the **project root** so `node_modules` is found:

- **WorkingDirectory:** `/root/lab-trading-dashboard`
- **ExecStart:** `/usr/bin/node server/server.js`

If your app is elsewhere (e.g. `/opt/lab-trading-dashboard`), change paths accordingly.

```bash
sudo nano /etc/systemd/system/lab-trading-dashboard.service
```

Set at least:

```ini
[Service]
WorkingDirectory=/root/lab-trading-dashboard
ExecStart=/usr/bin/node server/server.js
Environment=PORT=10000
EnvironmentFile=-/etc/lab-trading-dashboard.secrets.env
Restart=always
RestartSec=5
```

Save, then:

```bash
sudo systemctl daemon-reload
```

### 5. Install the unit file if it’s missing

If the service didn’t exist at all, copy it from your repo and install:

```bash
# From your laptop:
scp lab-trading-dashboard/scripts/lab-trading-dashboard.service root@150.241.244.130:/tmp/
# On cloud:
sudo cp /tmp/lab-trading-dashboard.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable lab-trading-dashboard
```

### 6. Start or restart the service

```bash
sudo systemctl start lab-trading-dashboard
# or
sudo systemctl restart lab-trading-dashboard
```

### 7. Check it’s running

```bash
sudo systemctl status lab-trading-dashboard
curl -s http://127.0.0.1:10000/api/health
curl -s http://127.0.0.1:10000/api/server-info
```

If `curl` returns JSON, the API is up. Then test from the browser: **https://api.clubinfotech.com/api/health**

### 8. If it still fails: check logs

```bash
sudo journalctl -u lab-trading-dashboard -n 80 --no-pager
```

Look for:

- **"Cannot find module 'express'"** → run `npm install` in `/root/lab-trading-dashboard`.
- **"EADDRINUSE"** → port 10000 is in use; stop the other process or change `PORT` in the service/env.
- **DB connection errors** → check `/etc/lab-trading-dashboard.secrets.env` (DB_HOST, DB_USER, DB_PASSWORD, DB_NAME or DATABASE_URL).

---

## Secrets file (DB and optional Python)

The service loads env from **/etc/lab-trading-dashboard.secrets.env** (optional). Create or edit it so the API can reach the DB:

```bash
sudo nano /etc/lab-trading-dashboard.secrets.env
```

Example:

```bash
DB_HOST=150.241.244.130
DB_PORT=5432
DB_USER=lab
DB_PASSWORD=your_password
DB_NAME=olab
PORT=10000
# Required for Information + Binance Data sections (Node proxies to Python):
# PYTHON_SIGNALS_URL=http://127.0.0.1:5001
```

Save, then:

```bash
sudo systemctl restart lab-trading-dashboard
```

---

## Summary

| Step | Command / action |
|------|-------------------|
| 1 | SSH: `ssh root@150.241.244.130` |
| 2 | **One-time (survive reboot):** `sudo bash /root/lab-trading-dashboard/scripts/enable-services-on-boot.sh` |
| 3 | **Repair now:** `sudo bash /root/lab-trading-dashboard/scripts/repair-and-start-server.sh` |
| 4 | If services missing: copy `lab-trading-dashboard.service` and `api-signals.service` to `/etc/systemd/system/`, then `daemon-reload` and run enable script again |
| 5 | **Information / Binance Data not showing:** Ensure `api-signals` is running and Node has `PYTHON_SIGNALS_URL=http://127.0.0.1:5001` in `/etc/lab-trading-dashboard.secrets.env`, then `sudo systemctl restart lab-trading-dashboard` |
| 6 | Restart Node: `sudo systemctl restart lab-trading-dashboard` |
| 7 | Test: `curl -s http://127.0.0.1:10000/api/health` and `curl -s http://127.0.0.1:5001/api/calculate-signals` (POST with body `{}` for Python) |
| 8 | Logs: `journalctl -u lab-trading-dashboard -f` or `journalctl -u api-signals -f` |

After this, **server.js** and **api_signals.py** should be running on the cloud. **https://api.clubinfotech.com** and the Information / Binance Data sections should work. With services enabled on boot, they will start automatically after every restart and restart on crash.
