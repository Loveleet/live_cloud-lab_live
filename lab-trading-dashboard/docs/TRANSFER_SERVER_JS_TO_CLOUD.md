# Transfer server.js to the cloud

**server.js is not in Git** (gitignored). Whenever you change `server/server.js` locally, you must copy it to the cloud yourself or the cloud will keep running the old version.

---

## One-time: copy server.js to cloud

Run from your **laptop**, inside the **lab-trading-dashboard** folder:

```bash
cd "/Volumes/Loveleet /Work/Binance/LAB_LIVE_NEW/lab_live/lab-trading-dashboard"

scp server/server.js root@150.241.244.130:/root/lab-trading-dashboard/server/
```

Then **restart the Node service on the cloud** so it loads the new file:

```bash
ssh root@150.241.244.130 "sudo systemctl restart lab-trading-dashboard"
```

Or SSH in and run:

```bash
ssh root@150.241.244.130
sudo systemctl restart lab-trading-dashboard
```

---

## Summary

| Step | Command |
|------|--------|
| 1. Transfer | `scp server/server.js root@150.241.244.130:/root/lab-trading-dashboard/server/` |
| 2. Restart Node | `ssh root@150.241.244.130 "sudo systemctl restart lab-trading-dashboard"` |

**Cloud path:** `/root/lab-trading-dashboard/server/server.js`
