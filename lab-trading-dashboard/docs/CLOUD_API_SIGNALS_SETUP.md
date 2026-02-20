# Cloud api-signals setup – why it broke and how to fix it

## Root cause (why it worked before, then broke)

1. **Before the new repo:** api_signals on the cloud was either:
   - Run manually or by another process (not the `api-signals` systemd unit), **or**
   - The same server had all Python deps already installed for `/usr/bin/python3` (e.g. from an earlier one-off setup).

2. **After the new repo:** We ran `deploy-server-to-cloud.py`, which:
   - Restarts **lab-trading-dashboard** (Node) ✅
   - Runs **`systemctl start api-signals`** → starts the **systemd** service.

3. The **api-signals** systemd unit uses **`/usr/bin/python3`** with **no virtualenv**. So the process runs with whatever packages that system Python has. On your cloud server, that Python did **not** have Flask, pandas, TA-Lib, etc., so the service kept exiting with `ModuleNotFoundError`.

4. **Conclusion:** The new repo didn’t change any “setting to call” the API. It started (or restarted) the api-signals **service** in an environment that was never fully set up for that service. Fix = install all required Python packages (and the TA-Lib C library) for `/usr/bin/python3` on the cloud, then start the service again.

---

## Step-by-step fix (run on your machine; commands SSH to the cloud)

Use the same host you always use (e.g. `root@150.241.244.130`). Replace if your user/host is different.

---

### Step 1: Stop the service so it stops crash-looping

```bash
ssh root@150.241.244.130 "sudo systemctl stop api-signals"
```

---

### Step 2: Install the TA-Lib C library on the cloud

TA-Lib’s Python package needs the C library installed first. **Option A** uses the system package (if available); **Option B** builds from source.

**Option A – Try system package (quick)**

```bash
ssh root@150.241.244.130 "sudo apt-get update && sudo apt-get install -y libta-lib-dev"
```

If that works, skip to Step 3. If you get “Unable to locate package” or similar, use Option B.

**Option B – Build from source**

```bash
ssh root@150.241.244.130 "sudo apt-get update && sudo apt-get install -y build-essential wget && cd /tmp && wget http://prdownloads.sourceforge.net/ta-lib/ta-lib-0.4.0-src.tar.gz && tar -xzf ta-lib-0.4.0-src.tar.gz && cd ta-lib && ./configure --prefix=/usr && make && sudo make install && cd /tmp && rm -rf ta-lib ta-lib-0.4.0-src.tar.gz"
```

---

### Step 3: Install Python dependencies for the same Python the service uses

The service runs `/usr/bin/python3`. Install everything with that interpreter:

```bash
ssh root@150.241.244.130 "cd /root/lab-trading-dashboard/python && /usr/bin/python3 -m pip install --upgrade pip && /usr/bin/python3 -m pip install -r requirements-api-signals.txt && /usr/bin/python3 -m pip install TA-Lib"
```

If `requirements-api-signals.txt` is not on the cloud yet, install packages explicitly:

```bash
ssh root@150.241.244.130 "cd /root/lab-trading-dashboard/python && /usr/bin/python3 -m pip install flask pandas numpy psutil python-telegram-bot binance-futures-connector TA-Lib"
```

---

### Step 4: Test run (see if any import still fails)

```bash
ssh root@150.241.244.130 "cd /root/lab-trading-dashboard/python && timeout 5 /usr/bin/python3 api_signals.py || true"
```

- If you see the process start and then exit after 5 seconds (timeout), that’s fine – it means imports and startup are OK.
- If you see a **traceback** (e.g. `ModuleNotFoundError` or `ImportError`), install the missing package the same way, e.g.:

  ```bash
  ssh root@150.241.244.130 "/usr/bin/python3 -m pip install <missing_module_name>"
  ```

  Then repeat Step 4 until the script starts without import errors.

---

### Step 5: Start the service and check status

```bash
ssh root@150.241.244.130 "sudo systemctl start api-signals && sleep 3 && systemctl status api-signals"
```

You want **Active: active (running)**. If it still says **active (auto-restart)** or **exited**, check logs:

```bash
ssh root@150.241.244.130 "journalctl -u api-signals -n 60 --no-pager"
```

Fix any remaining missing module or config, then run Step 5 again.

---

### Step 6: Verify Node can reach Python (optional)

From your machine:

```bash
curl -s http://150.241.244.130:10000/api/calculate-signals/health
```

Expected: `{"ok":true,"service":"calculate-signals"}` or similar. If you get 502, Node is up but Python isn’t; re-check Step 5 and logs.

---

## One-time: sync requirements file to the cloud

So that Step 3 can use `-r requirements-api-signals.txt` on the server, copy the file from your repo to the cloud:

```bash
scp "/Volumes/Loveleet /Work/Binance/LAB_LIVE_NEW/lab_live/lab-trading-dashboard/python/requirements-api-signals.txt" root@150.241.244.130:/root/lab-trading-dashboard/python/
```

(Adjust the local path if your project lives elsewhere.)

---

## Summary

| What broke | Why |
|-----------|-----|
| api-signals service exits immediately | systemd runs `/usr/bin/python3`; that Python had no Flask, pandas, TA-Lib, etc. |
| Seemed to start “after new repo” | Deploy script started the api-signals **service**; before, something else may have been running the script (or deps were already installed). |

| Fix | Do this |
|-----|--------|
| Install TA-Lib C library | Step 2 (apt or build from source). |
| Install Python deps | Step 3 for `/usr/bin/python3`. |
| Confirm no more import errors | Step 4 (manual test run). |
| Run the service | Step 5 (systemctl start + status + logs if needed). |

After these steps, the cloud is in the same “working” state as before, with the api-signals **service** properly configured.
