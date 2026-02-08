# GitHub Pages + Cloud API: HTTPS required

When you open the dashboard at **https://loveleet.github.io/lab_live/** (HTTPS), the browser only allows requests to **HTTPS** URLs. Requests to **http://150.241.244.130:10000** are blocked (mixed content).

So for data to load on GitHub Pages, your **cloud API must be reachable over HTTPS**.

---

## Option A: Use the dashboard on the cloud (no HTTPS needed)

Open **http://150.241.244.130:10000** in the browser. The frontend and API are same-origin, so data loads without any HTTPS setup.

---

## Option B: Use GitHub Pages and enable HTTPS on the cloud

1. **Serve the API over HTTPS** on your cloud server (150.241.244.130), for example:
   - **Nginx + Let’s Encrypt**: Nginx listens on 443 (HTTPS) and proxies to `http://localhost:10000`. Use a domain or the IP with a certificate.
   - **Caddy**: Same idea, Caddy can obtain a certificate automatically.
   - Or run the Node server with HTTPS (you need a TLS cert and key).

2. **Set the secret** so the frontend calls your HTTPS API:
   - GitHub repo → **Settings** → **Secrets and variables** → **Actions**
   - Add or edit **API_BASE_URL** = `https://your-cloud-domain-or-ip:443` (your real HTTPS API URL).

3. **Redeploy** the frontend (push to `lab_live` or run the “Deploy frontend to GitHub Pages” workflow). The new build will use the HTTPS API URL and data should load on loveleet.github.io/lab_live/.

---

## Summary

| Where you open the dashboard | API URL used        | What you need                    |
|-----------------------------|---------------------|----------------------------------|
| http://150.241.244.130:10000 | Same origin (no API base) | Nothing extra                    |
| https://loveleet.github.io/lab_live/ | HTTPS API           | Cloud API must be served over HTTPS |
